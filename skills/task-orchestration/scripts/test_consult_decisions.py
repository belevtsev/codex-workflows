"""Offline consultation regressions; no live credentials or external requests."""

import copy
import io
import json
import multiprocessing
import os
from pathlib import Path
import signal
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib import error

import consult_decisions as dual
import consult_jev as jev
from validate_policy import DEFAULT_POLICY, PolicyError, load_policy


def sample_request():
    return {"state": {"evidence": "The service acknowledges work only after storing it.",
                      "claim": "Acknowledgement follows storage."},
            "questions": {"claim": {"type": "choice", "instructions": "Does the evidence support the claim?",
                "criteria": {"supported": "The evidence establishes the claim.",
                             "contradicted": "The evidence establishes an incompatible claim.",
                             "insufficient_evidence": "A necessary fact is missing."}}}}


def prepared_request(shared=None):
    shared = shared or sample_request()
    # Historical records must remain valid after the active model pin changes.
    return {name: jev.prepare_request(shared, model) for name, model in
            {"jev": "jev-1.13.0", "subq_snap": "subq-snap-preview"}.items()}


def success(prepared, choice="supported"):
    return {"request": prepared, "requested_model": prepared["model"], "resolved_model": prepared["model"],
            "status": "success", "duration_seconds": 0.01,
            "result": {"model": prepared["model"], "answers": {
                key: {"type": "choice", "choice": choice,
                      "probabilities": {option: float(option == choice) for option in question["criteria"]},
                      "confidence": 1.0}
                for key, question in prepared["questions"].items()},
                "usage": {"input_tokens": 20, "output_tokens": 0}}}


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def fixture_worker(sender, provider, prepared, deadline_at, credential):
    """Run the actual one-shot HTTP logic with an in-process synthetic transport."""
    if hasattr(credential, "wait"):
        credential.wait(timeout=2)
    scenario = prepared["state"].get("scenario") if isinstance(prepared["state"], dict) else None
    if scenario == "partial_frame" and provider == "subq_snap":
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        time.sleep(0.25)  # Let the other provider's complete record be collected first.
        os.write(sender.fileno(), struct.pack("!i", 1000) + b"partial")
        time.sleep(10)
        return

    def open_fixture(outgoing, timeout):
        endpoints = dict(dual.PROVIDERS, **dual.OPTIONAL_PROVIDERS)
        if outgoing.full_url != endpoints[provider][0] or timeout <= 0:
            raise AssertionError("incorrect endpoint or timeout")
        sent = json.loads(outgoing.data)
        expected = dual.openai.request_body(prepared) if provider == "openai_decisions" else prepared
        if sent != expected:
            raise AssertionError("different provider evidence")
        if isinstance(credential, dict):
            with credential["calls"].get_lock():
                credential["calls"].value += 1
        if (scenario == "hang" and provider == "subq_snap") or (scenario == "hang_openai" and provider == "openai_decisions"):
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
            time.sleep(10)
        if scenario == "http_error":
            raise error.HTTPError(outgoing.full_url, 429, "fake-secret-must-not-leak", {}, None)
        result = success(prepared)["result"]
        if provider == "openai_decisions":
            result["answers"] = [
                dict(answer, name=name, probabilities=[{"value": option, "probability": probability}
                                                       for option, probability in answer["probabilities"].items()])
                for name, answer in result["answers"].items()
            ]
            result["usage"].update(total_tokens=20, input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
                                   output_tokens_details={"reasoning_tokens": 0})
        return Response(json.dumps(result).encode())

    with mock.patch.object(jev, "open_once", side_effect=open_fixture):
        dual.provider_worker(sender, provider, prepared, deadline_at, "fake-secret-must-not-leak")


class ConsultationTests(unittest.TestCase):
    def setUp(self):
        self.shared = sample_request()
        self.prepared = prepared_request(self.shared)

    def record(self, snap_choice="supported", missing=()):
        raw = {name: dual.unavailable(value, "missing_credential") if name in missing else
               success(value, snap_choice if name == "subq_snap" else "supported")
               for name, value in self.prepared.items()}
        return dual.make_record(self.shared, self.prepared, raw)

    def decision(self, choice="supported", status="resolved", rejected=None):
        return {"questions": {"claim": {
            "status": status, "choice": choice, "reason": "Source and fixture establish storage before acknowledgement.",
            "evidence": ["fixture/service.go:12 at fixture-revision"],
            "verification": ["source inspected; storage-before-ack test passed"],
            "rejected_judgments": rejected or {},
        }}}

    def test_shared_contract_rejects_provider_specific_inputs(self):
        for extra in ({"model": "jev-1.13.0"}, {"images": []}):
            with self.subTest(extra=extra), self.assertRaises(PolicyError):
                dual.shared_request(dict(self.shared, **extra))
        invalid = copy.deepcopy(self.shared)
        invalid["questions"]["claim"]["type"] = "noul"
        with self.assertRaises(PolicyError):
            dual.shared_request(invalid)
        invalid = copy.deepcopy(self.shared)
        invalid["questions"]["x" * 101] = invalid["questions"].pop("claim")
        with self.assertRaises(PolicyError):
            dual.shared_request(invalid)

    def test_agreement_disagreement_and_independent_questions(self):
        self.shared["questions"]["other"] = copy.deepcopy(self.shared["questions"]["claim"])
        self.prepared = prepared_request(self.shared)
        raw = {name: success(value) for name, value in self.prepared.items()}
        snap = raw["subq_snap"]["result"]["answers"]["other"]
        snap.update(choice="contradicted", probabilities={"supported": 0.1, "contradicted": 0.9,
                                                        "insufficient_evidence": 0}, confidence=0.7)
        record = dual.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["comparison"]["claim"]["status"], "agreement")
        self.assertEqual(record["comparison"]["other"]["status"], "disagreement")
        self.assertEqual(record["final_decision"], {"status": "pending", "questions": {}})
        self.assertNotIn("winner", json.dumps(record))

    def test_partial_and_unavailable_remain_pending(self):
        for missing in (("jev",), ("subq_snap",), ("jev", "subq_snap")):
            record = self.record(missing=missing)
            expected = "unavailable" if len(missing) == 2 else "partial"
            self.assertEqual(record["status"], expected)
            self.assertEqual(record["comparison"]["claim"]["status"], expected)
            self.assertEqual(record["final_decision"]["status"], "pending")
        with mock.patch.object(multiprocessing, "get_context", side_effect=AssertionError("must not spawn")):
            records = dual.collect(self.prepared, {}, 30)
            self.assertEqual(len(records), 2)

    def test_malformed_provider_is_unavailable_without_discarding_other(self):
        mutations = [
            lambda raw: raw["result"].update(model="different-model"),
            lambda raw: raw["result"]["answers"]["claim"].update(type="noul"),
            lambda raw: raw["result"]["answers"]["claim"].update(confidence=float("nan")),
            lambda raw: raw["result"]["answers"]["claim"]["probabilities"].update(supported=0.7),
            lambda raw: raw["result"]["answers"]["claim"].update(choice="contradicted"),
            lambda raw: raw["result"]["answers"].clear(),
            lambda raw: raw.update(request=jev.prepare_request(dict(self.shared, state="different evidence"),
                                                              "subq-snap-preview")),
        ]
        for mutation in mutations:
            raw = {name: success(value) for name, value in self.prepared.items()}
            mutation(raw["subq_snap"])
            record = dual.make_record(self.shared, self.prepared, raw)
            self.assertEqual(record["providers"]["jev"]["status"], "success")
            self.assertEqual(record["providers"]["subq_snap"]["error"]["category"], "invalid_response")

    def test_spawned_requests_overlap_and_keep_endpoints_separate(self):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        records = dual.collect(self.prepared, {name: barrier for name in self.prepared}, 4,
                               context=context, worker=fixture_worker)
        self.assertEqual({value["status"] for value in records.values()}, {"success"})
        self.assertEqual(dual.make_record(self.shared, self.prepared, records)["status"], "success")

    def test_large_pipe_record_is_drained_before_join(self):
        shared = dict(self.shared, state="x" * 300000)
        prepared = prepared_request(shared)
        records = dual.collect(prepared, {name: "fake" for name in prepared}, 4, worker=fixture_worker)
        self.assertEqual({value["status"] for value in records.values()}, {"success"})
        self.assertEqual(dual.make_record(shared, prepared, records)["status"], "success")

    def test_hanging_worker_and_partial_frame_are_bounded_and_reaped(self):
        previous = {child.pid for child in multiprocessing.active_children()}
        for scenario in ("hang", "partial_frame"):
            shared = dict(self.shared, state=dict(self.shared["state"], scenario=scenario))
            prepared = prepared_request(shared)
            started = time.monotonic()
            records = dual.collect(prepared, {name: "fake" for name in prepared}, 1, worker=fixture_worker)
            self.assertLess(time.monotonic() - started, 3)
            self.assertEqual(records["jev"]["status"], "success")
            self.assertEqual(records["subq_snap"]["error"]["category"], "timeout")
            self.assertEqual({child.pid for child in multiprocessing.active_children()}, previous)

    def test_start_failure_preserves_other_provider_and_reaps_children(self):
        context = multiprocessing.get_context("spawn")

        class SecondStartFails:
            calls = 0

            def Pipe(self, **kwargs):
                return context.Pipe(**kwargs)

            def Process(self, **kwargs):
                self.calls += 1
                process = context.Process(**kwargs)
                if self.calls == 2:
                    process.start = mock.Mock(side_effect=OSError("fake-secret-must-not-leak"))
                return process

        previous = {child.pid for child in multiprocessing.active_children()}
        records = dual.collect(self.prepared, {name: "fake" for name in self.prepared}, 4,
                               context=SecondStartFails(), worker=fixture_worker)
        self.assertEqual(records["jev"]["status"], "success")
        self.assertEqual(records["subq_snap"]["error"]["category"], "worker_error")
        self.assertNotIn("fake-secret", json.dumps(records))
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, previous)

    def test_http_failure_is_one_attempt_and_never_exposes_raw_error(self):
        context = multiprocessing.get_context("spawn")
        calls = context.Value("i", 0)
        shared = dict(self.shared, state={"scenario": "http_error"})
        prepared = prepared_request(shared)
        credentials = {name: {"calls": calls} for name in prepared}
        records = dual.collect(prepared, credentials, 4, context=context, worker=fixture_worker)
        self.assertEqual(calls.value, 2)
        self.assertEqual({value["error"]["http_status"] for value in records.values()}, {429})
        self.assertNotIn("fake-secret", json.dumps(records))

    def test_non_main_thread_does_not_make_unbounded_requests(self):
        found = []
        thread = threading.Thread(target=lambda: found.append(dual.collect(
            self.prepared, {name: "fake" for name in self.prepared}, 30)))
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual({value["error"]["category"] for value in found[0].values()}, {"deadline_unavailable"})

    def test_final_decision_requires_verification_and_rejection_reasons(self):
        record = self.record(snap_choice="contradicted")
        decision = self.decision(rejected={"subq_snap": "The inspected source explicitly stores before acknowledgement."})
        final = dual.adjudicate(record, decision)
        self.assertEqual(final["final_decision"]["status"], "resolved")
        self.assertEqual(record["final_decision"]["status"], "pending")
        for key, value in (("evidence", []), ("verification", []), ("rejected_judgments", {}),
                           ("choice", "unknown"), ("reason", ""), ("choice", "insufficient_evidence")):
            variant = copy.deepcopy(decision)
            variant["questions"]["claim"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(PolicyError):
                dual.adjudicate(record, variant)
        with self.assertRaises(PolicyError):
            dual.adjudicate(record, {"questions": {}})

    def test_agreement_and_provider_outages_do_not_replace_source_verification(self):
        for record in (self.record(), self.record(missing=("jev",)), self.record(missing=("jev", "subq_snap"))):
            variant = self.decision()
            variant["questions"]["claim"]["verification"] = []
            with self.assertRaises(PolicyError):
                dual.adjudicate(record, variant)
            final = dual.adjudicate(record, self.decision())
            self.assertEqual(final["final_decision"]["status"], "resolved")

    def test_unresolved_and_tampered_records(self):
        decision = self.decision(choice=None, status="unresolved")
        decision["questions"]["claim"].update(reason="Storage durability is not established by the available source.",
                                             evidence=[], verification=[])
        final = dual.adjudicate(self.record(), decision)
        self.assertEqual(final["final_decision"]["status"], "unresolved")
        for change in (
            lambda record: record["request"].update(state="changed evidence"),
            lambda record: record["providers"]["jev"].update(request_sha256="different"),
            lambda record: record["comparison"]["claim"].update(status="disagreement"),
            lambda record: record["providers"]["jev"].update(raw_error="fake-secret"),
        ):
            record = self.record()
            change(record)
            with self.assertRaises(PolicyError):
                dual.adjudicate(record, decision)

    def test_cli_dry_run_reserves_private_output_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            output_path = root / "output.json"
            request_path.write_text(json.dumps(self.shared))
            pair_policy = copy.deepcopy(load_policy())
            pair_policy["consultation"].pop("optional_providers", None)
            pair_policy["consultation"]["providers"].pop("openai_decisions", None)
            with mock.patch.object(dual, "collect", side_effect=AssertionError("no network")), \
                    mock.patch.object(dual, "load_policy", return_value=pair_policy), \
                    mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake-key", "SUBQ_API_KEY": "fake-key"}, clear=True):
                self.assertEqual(dual.main(["--request", str(request_path), "--output", str(output_path), "--dry-run"]), 0)
                record = json.loads(output_path.read_text())
                self.assertEqual(record["status"], "dry_run")
                self.assertEqual(record["version"], 1)
                self.assertEqual(record["providers"], {
                    "jev": {"requested_model": "jev-1.14.0"},
                    "subq_snap": {"requested_model": "subq-snap-preview"},
                })
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("fake-key", output_path.read_text())
                self.assertEqual(dual.main(["--request", str(request_path), "--output", str(output_path)]), 1)

    def test_cli_partial_missing_keys_and_offline_adjudication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "advice.json"
            request_path.write_text(json.dumps(self.shared))
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(multiprocessing, "get_context", side_effect=AssertionError("no workers")):
                self.assertEqual(dual.main(["--request", str(request_path), "--output", str(output_path)]), 2)
            record = self.record(snap_choice="contradicted")
            output_path.write_text(json.dumps(record))
            decision_path, final_path = root / "decision.json", root / "final.json"
            decision_path.write_text(json.dumps(self.decision(rejected={"subq_snap": "Inspected source establishes the ordering."})))
            with mock.patch.object(dual, "collect", side_effect=AssertionError("no network")):
                self.assertEqual(dual.main(["--adjudicate", str(output_path), "--decision", str(decision_path),
                                            "--output", str(final_path)]), 0)
            self.assertEqual(json.loads(final_path.read_text())["final_decision"]["status"], "resolved")
            self.assertEqual(final_path.stat().st_mode & 0o777, 0o600)

    def test_cli_rejects_malformed_duration_without_traceback_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = self.record()
            record["providers"]["jev"]["duration_seconds"] = 10 ** 1000
            advice, decision, final = root / "advice.json", root / "decision.json", root / "final.json"
            advice.write_text(json.dumps(record))
            decision.write_text(json.dumps(self.decision()))
            captured = io.StringIO()
            with mock.patch("sys.stderr", captured), \
                    mock.patch.object(dual, "collect", side_effect=AssertionError("no network")):
                self.assertEqual(dual.main(["--adjudicate", str(advice), "--decision", str(decision),
                                            "--output", str(final)]), 1)
            self.assertIn("invalid provider duration", captured.getvalue())
            self.assertNotIn("Traceback", captured.getvalue())
            self.assertFalse(final.exists())

    def test_legacy_jev_helper_accepts_extended_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "legacy.json"
            request_path.write_text(json.dumps(self.shared))
            with mock.patch.object(jev, "consult", side_effect=AssertionError("no network")):
                self.assertEqual(jev.main(["--request", str(request_path), "--output", str(output_path),
                                           "--policy", str(DEFAULT_POLICY), "--dry-run"]), 0)
            self.assertEqual(json.loads(output_path.read_text())["requested_model"], "jev-1.14.0")


def optional_prepared(shared):
    return dict(prepared_request(shared), openai_decisions=dual.openai.prepare_request(shared))


def optional_success(prepared, choice="supported", refusals=()):
    record = success(prepared, choice)
    record["result"]["usage"].update(
        total_tokens=20, input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
        output_tokens_details={"reasoning_tokens": 0})
    for name in refusals:
        record["result"]["answers"][name] = {"type": "refusal"}
    record["status"] = dual.openai.response_status(record["result"])
    return record


class OptionalConsultationTests(unittest.TestCase):
    def setUp(self):
        self.shared = sample_request()
        self.prepared = optional_prepared(self.shared)

    def raw(self, choice="supported", refusals=()):
        return {name: optional_success(value, choice, refusals) if name == "openai_decisions" else success(value)
                for name, value in self.prepared.items()}

    def decision(self, **kwargs):
        return ConsultationTests().decision(**kwargs)

    def make_record(self, shared, prepared, raw):
        return dual.make_record(shared, prepared, raw, version=2)

    def test_three_way_comparison_keeps_judgments_independent_and_codex_owns_choice(self):
        raw = self.raw(choice="insufficient_evidence")
        raw["subq_snap"] = success(self.prepared["subq_snap"], "contradicted")
        record = self.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["version"], 2)
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["comparison"]["claim"], {
            "status": "disagreement", "choices": {"jev": "supported", "subq_snap": "contradicted",
                                                    "openai_decisions": "insufficient_evidence"}, "missing": {}})
        rejected = {"subq_snap": "Inspected storage-before-acknowledgement behavior contradicts this judgment.",
                    "openai_decisions": "The source and fixture supply the missing evidence."}
        decision = self.decision(rejected=rejected)
        self.assertEqual(dual.adjudicate(record, decision)["final_decision"]["status"], "resolved")
        for name in rejected:
            variant = copy.deepcopy(decision)
            del variant["questions"]["claim"]["rejected_judgments"][name]
            with self.subTest(name=name), self.assertRaises(PolicyError):
                dual.adjudicate(record, variant)

    def test_mixed_refusal_preserves_other_choice_and_needs_only_differing_choice_reasons(self):
        self.shared["questions"]["other"] = copy.deepcopy(self.shared["questions"]["claim"])
        self.prepared = optional_prepared(self.shared)
        record = self.make_record(self.shared, self.prepared, self.raw(choice="contradicted", refusals=("claim",)))
        self.assertEqual(record["providers"]["openai_decisions"]["status"], "partial")
        self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "refusal"})
        self.assertEqual(record["comparison"]["other"]["choices"]["openai_decisions"], "contradicted")
        self.assertEqual(record["comparison"]["claim"]["status"], "partial")
        decision = self.decision()
        decision["questions"]["other"] = copy.deepcopy(decision["questions"]["claim"])
        decision["questions"]["other"]["rejected_judgments"] = {"openai_decisions": "Source establishes the ordering."}
        self.assertEqual(dual.adjudicate(record, decision)["final_decision"]["status"], "resolved")
        variant = copy.deepcopy(decision)
        variant["questions"]["claim"]["rejected_judgments"] = {"openai_decisions": "A refusal is not a judgment."}
        with self.assertRaises(PolicyError):
            dual.adjudicate(record, variant)

    def test_all_refused_and_provider_outages_are_distinct_missing_advice(self):
        raw = self.raw(refusals=("claim",))
        record = self.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["providers"]["openai_decisions"]["status"], "refusal")
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "refusal"})
        self.assertEqual(dual.adjudicate(record, self.decision())["final_decision"]["status"], "resolved")
        for name in ("jev", "subq_snap"):
            raw[name] = dual.unavailable(self.prepared[name], "timeout")
        record = self.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["status"], "unavailable")
        self.assertEqual(record["comparison"]["claim"], {"status": "unavailable", "choices": {}, "missing": {
            "jev": "unavailable", "subq_snap": "unavailable", "openai_decisions": "refusal"}})

    def test_disabled_optional_preserves_pair_availability_but_forced_missing_key_is_partial(self):
        for reason in dual.DISABLED_REASONS:
            raw = self.raw()
            raw["openai_decisions"] = dual.disabled(self.prepared["openai_decisions"], reason)
            record = self.make_record(self.shared, self.prepared, raw)
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["comparison"]["claim"]["status"], "agreement")
            self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "disabled"})
            self.assertEqual(dual.adjudicate(record, self.decision())["final_decision"]["status"], "resolved")
        raw["openai_decisions"] = dual.unavailable(self.prepared["openai_decisions"], "missing_credential")
        record = self.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "unavailable"})

    def test_unsupported_openai_count_does_not_start_optional_worker_or_break_required_pair(self):
        shared = dict(self.shared, questions={str(index): self.shared["questions"]["claim"] for index in range(201)})
        prepared = optional_prepared(shared)
        # The fixture rejects an invalid OpenAI wire request if one is dispatched.
        records = dual.collect(prepared, {name: "fake" for name in prepared}, 4, worker=fixture_worker)
        self.assertEqual(records["openai_decisions"]["error"], {"category": "unsupported_request"})
        self.assertEqual(records["jev"]["status"], "success")
        self.assertEqual(records["subq_snap"]["status"], "success")
        record = self.make_record(shared, prepared, records)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["providers"]["openai_decisions"]["error"], {"category": "unsupported_request"})

    def test_all_three_workers_overlap_and_hanging_optional_worker_is_reaped(self):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(3)
        records = dual.collect(self.prepared, {name: barrier for name in self.prepared}, 4,
                               context=context, worker=fixture_worker)
        self.assertEqual({record["status"] for record in records.values()}, {"success"})
        previous = {child.pid for child in multiprocessing.active_children()}
        shared = dict(self.shared, state={"scenario": "hang_openai"})
        prepared = optional_prepared(shared)
        started = time.monotonic()
        records = dual.collect(prepared, {name: "fake" for name in prepared}, 1, worker=fixture_worker)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(records["openai_decisions"]["error"]["category"], "timeout")
        self.assertEqual(records["jev"]["status"], "success")
        self.assertEqual(records["subq_snap"]["status"], "success")
        self.assertEqual({child.pid for child in multiprocessing.active_children()}, previous)

    def test_optional_worker_receives_only_its_explicit_credential_and_keeps_global_state(self):
        sender = mock.Mock()
        endpoint = jev.ENDPOINT
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake-jev", "SUBQ_API_KEY": "fake-snap"}, clear=True), \
                mock.patch.object(dual.openai, "consult", return_value=(self.raw()["openai_decisions"], 0)) as consult, \
                mock.patch.object(jev, "consult", side_effect=AssertionError("wrong provider")):
            before = dict(os.environ)
            dual.provider_worker(sender, "openai_decisions", self.prepared["openai_decisions"],
                                 time.monotonic() + 3, "fake-openai")
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(consult.call_count, 1)
        self.assertEqual(consult.call_args.args[2], "fake-openai")
        self.assertEqual(jev.ENDPOINT, endpoint)
        sender.send.assert_called_once()

    def test_versioned_provider_sets_and_stored_optional_metadata_are_strict(self):
        original = self.make_record(self.shared, self.prepared, self.raw())
        for mutate in (
            lambda record: record.update(version=1),
            lambda record: record["providers"].pop("openai_decisions"),
            lambda record: record["providers"].update(other=record["providers"]["openai_decisions"]),
            lambda record: record["providers"]["openai_decisions"].update(requested_model="gpt-6-astra"),
            lambda record: record["providers"]["openai_decisions"].update(resolved_model="gpt-6-astra"),
            lambda record: record["providers"]["openai_decisions"].update(usage={"input_tokens": 7}),
            lambda record: record["providers"]["openai_decisions"]["result"]["usage"].update(input_tokens=-1),
            lambda record: record["providers"]["openai_decisions"].update(request_sha256="wrong"),
            lambda record: record["comparison"]["claim"]["missing"].update(openai_decisions="refusal"),
            lambda record: record["providers"]["openai_decisions"]["result"]["answers"]["claim"].update(type="refusal"),
            lambda record: record["providers"]["openai_decisions"].update(status="partial"),
            lambda record: record["providers"]["openai_decisions"].update(raw_error="fake-secret"),
        ):
            record = copy.deepcopy(original)
            mutate(record)
            with self.subTest(mutate=mutate), self.assertRaises(PolicyError):
                dual.adjudicate(record, self.decision())
        raw = self.raw()
        raw["openai_decisions"] = dual.disabled(self.prepared["openai_decisions"], "excluded")
        original = self.make_record(self.shared, self.prepared, raw)
        for mutate in (
            lambda record: record["providers"]["openai_decisions"].update(reason=[]),
            lambda record: record["providers"]["openai_decisions"].update(duration_seconds=1),
            lambda record: record["providers"]["openai_decisions"].update(result={"answers": {}}),
            lambda record: record["providers"]["jev"].update(status="disabled", reason="excluded"),
        ):
            record = copy.deepcopy(original)
            mutate(record)
            with self.subTest(disabled_mutate=mutate), self.assertRaises(PolicyError):
                dual.adjudicate(record, self.decision())

    def test_exact_historical_v1_jev_113_record_adjudicates_without_network_or_current_policy(self):
        digest = "9cbde4a76e716b876eca243a8b43bdad60bae597a6d65ebbddc488ed003d95cd"
        # Frozen v1 field shape and model IDs; do not generate through make_record.
        record = {"version": 1, "status": "success", "request": sample_request(), "request_sha256": digest,
                  "providers": {}, "comparison": {"claim": {"status": "agreement", "choices": {
                      "jev": "supported", "subq_snap": "supported"}}},
                  "final_decision": {"status": "pending", "questions": {}}}
        for name, model in (("jev", "jev-1.13.0"), ("subq_snap", "subq-snap-preview")):
            record["providers"][name] = {
                "status": "success", "requested_model": model, "request_sha256": digest, "duration_seconds": 0.01,
                "resolved_model": model, "result": {"model": model, "answers": {"claim": {
                    "type": "choice", "choice": "supported", "probabilities": {
                        "supported": 1.0, "contradicted": 0.0, "insufficient_evidence": 0.0}, "confidence": 1.0}},
                    "usage": {"input_tokens": 20, "output_tokens": 0}},
                "usage": {"input_tokens": 20, "output_tokens": 0}}
        unchanged = copy.deepcopy(record)
        with mock.patch.object(dual, "load_policy", side_effect=AssertionError("offline historical replay")), \
                mock.patch.object(dual, "collect", side_effect=AssertionError("no network")):
            self.assertEqual(dual.adjudicate(record, self.decision())["final_decision"]["status"], "resolved")
        self.assertEqual(record, unchanged)
        record["version"] = 2
        with self.assertRaises(PolicyError):
            dual.adjudicate(record, self.decision())

    def test_cli_auto_on_off_and_forced_missing_key(self):
        policy = {"consultation": {"providers": {"jev": "jev-1.14.0", "subq_snap": "subq-snap-preview"},
                                    "optional_providers": {"openai_decisions": "gpt-6-luna"}, "deadline_seconds": 30}}
        cases = (
            ([], {}, "disabled", "missing_credential", "success"),
            ([], {"OPENAI_API_KEY": "fake-openai"}, "success", None, "success"),
            (["--without-openai"], {"OPENAI_API_KEY": "fake-openai"}, "disabled", "excluded", "success"),
            (["--with-openai"], {}, "unavailable", "missing_credential", "partial"),
        )
        for flags, environment, expected_status, reason, overall in cases:
            with self.subTest(flags=flags, environment=bool(environment)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                request_path, output_path = root / "request.json", root / "record.json"
                request_path.write_text(json.dumps(self.shared))
                calls = []

                def collect_fixture(prepared, credentials, deadline, **kwargs):
                    calls.append((credentials, deadline, kwargs))
                    records = {name: success(value) for name, value in prepared.items() if name != "openai_decisions"}
                    optional = prepared["openai_decisions"]
                    disabled = kwargs["disabled_providers"]
                    records["openai_decisions"] = (
                        dual.disabled(optional, disabled["openai_decisions"]) if "openai_decisions" in disabled else
                        optional_success(optional) if credentials["openai_decisions"] else
                        dual.unavailable(optional, "missing_credential"))
                    return records

                with mock.patch.dict(os.environ, environment, clear=True), \
                        mock.patch.object(dual, "load_policy", return_value=policy), \
                        mock.patch.object(dual, "collect", side_effect=collect_fixture):
                    before = dict(os.environ)
                    code = dual.main(["--request", str(request_path), "--output", str(output_path), *flags])
                    self.assertEqual(dict(os.environ), before)
                record = json.loads(output_path.read_text())
                self.assertEqual(record["version"], 2)
                self.assertEqual(record["status"], overall)
                optional = record["providers"]["openai_decisions"]
                self.assertEqual(optional["status"], expected_status)
                if reason:
                    self.assertEqual(optional["reason"] if expected_status == "disabled" else optional["error"]["category"],
                                     reason)
                self.assertEqual(code, 0 if overall == "success" else 2)
                self.assertEqual(calls[0][1], 30)
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("fake-openai", output_path.read_text())

    def test_disabled_and_missing_key_do_not_spawn_optional_worker(self):
        required = {name: "fake" for name in dual.PAIR_PROVIDERS}
        for disabled in ({"openai_decisions": "missing_credential"}, {"openai_decisions": "excluded"}, {}):
            optional_key = "fake-openai" if disabled.get("openai_decisions") == "excluded" else None
            records = dual.collect(self.prepared, dict(required, openai_decisions=optional_key), 4,
                                   worker=fixture_worker, disabled_providers=disabled,
                                   required_providers=set(dual.PAIR_PROVIDERS))
            self.assertEqual(records["openai_decisions"]["status"], "disabled" if disabled else "unavailable")
            self.assertEqual(records["jev"]["status"], "success")
            self.assertEqual(records["subq_snap"]["status"], "success")

    def test_cli_openai_flags_are_mutually_exclusive_request_only_and_policy_declared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "record.json"
            request_path.write_text(json.dumps(self.shared))
            invalid = (
                ["--request", str(request_path), "--with-openai", "--without-openai"],
                ["--adjudicate", str(request_path), "--decision", str(request_path), "--with-openai"],
                ["--adjudicate", str(request_path), "--decision", str(request_path), "--without-openai"],
            )
            for flags in invalid:
                with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as failure:
                    dual.main([*flags, "--output", str(output_path)])
                self.assertEqual(failure.exception.code, 2)
                self.assertFalse(output_path.exists())
            pair_policy = {"consultation": {"providers": {"jev": "jev-1.14.0", "subq_snap": "subq-snap-preview"},
                                             "deadline_seconds": 30}}
            for flag in ("--with-openai", "--without-openai"):
                captured = io.StringIO()
                with mock.patch.object(dual, "load_policy", return_value=pair_policy), \
                        mock.patch("sys.stderr", captured), \
                        mock.patch.object(dual, "collect", side_effect=AssertionError("no network")):
                    self.assertEqual(dual.main(["--request", str(request_path), flag, "--output", str(output_path)]), 1)
                self.assertIn("policy does not configure the OpenAI adviser", captured.getvalue())
                self.assertFalse(output_path.exists())


class RequiredConsultationTests(unittest.TestCase):
    def setUp(self):
        self.shared = sample_request()
        self.policy = {"consultation": {"providers": {
            "jev": "jev-1.14.0", "subq_snap": "subq-snap-preview", "openai_decisions": "gpt-6-luna"},
            "deadline_seconds": 30}}
        self.prepared = self.prepare(self.shared)

    def prepare(self, shared):
        return {name: (dual.openai.prepare_request(shared, model) if name == "openai_decisions" else
                       jev.prepare_request(shared, model))
                for name, model in self.policy["consultation"]["providers"].items()}

    def raw(self, prepared=None):
        return {name: optional_success(value) if name == "openai_decisions" else success(value)
                for name, value in (prepared or self.prepared).items()}

    def decision(self, **kwargs):
        return ConsultationTests().decision(**kwargs)

    def test_new_triple_records_are_v3_with_all_three_required(self):
        record = dual.make_record(self.shared, self.prepared, self.raw())
        self.assertEqual(record["version"], 3)
        self.assertEqual(set(record["providers"]), {"jev", "subq_snap", "openai_decisions"})
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["comparison"]["claim"], {"status": "agreement", "choices": {
            "jev": "supported", "subq_snap": "supported", "openai_decisions": "supported"}, "missing": {}})
        self.assertEqual({provider["request_sha256"] for provider in record["providers"].values()},
                         {record["request_sha256"]})
        with mock.patch.object(dual, "load_policy", side_effect=AssertionError("self-contained record")):
            final = dual.adjudicate(record, self.decision())
        self.assertEqual(final["final_decision"]["status"], "resolved")

    def test_missing_required_openai_key_preserves_pair_as_partial_without_disabling(self):
        records = dual.collect(self.prepared, {name: "fake" for name in dual.PAIR_PROVIDERS}, 4,
                               worker=fixture_worker)
        self.assertEqual(records["openai_decisions"]["status"], "unavailable")
        self.assertEqual(records["openai_decisions"]["error"], {"category": "missing_credential"})
        self.assertEqual(records["jev"]["status"], "success")
        self.assertEqual(records["subq_snap"]["status"], "success")
        record = dual.make_record(self.shared, self.prepared, records)
        self.assertEqual(record["version"], 3)
        self.assertEqual(record["status"], "partial")
        self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "unavailable"})
        self.assertEqual(dual.adjudicate(record, self.decision())["final_decision"]["status"], "resolved")
        with mock.patch.object(multiprocessing, "get_context", side_effect=AssertionError("no credentials, no workers")):
            records = dual.collect(self.prepared, {}, 30)
        record = dual.make_record(self.shared, self.prepared, records)
        self.assertEqual(record["status"], "unavailable")
        self.assertEqual(set(record["providers"]), set(dual.PROVIDERS))

    def test_v3_disabled_provider_is_never_accepted_even_with_recomputed_coverage(self):
        for name in self.prepared:
            record = dual.make_record(self.shared, self.prepared, self.raw())
            record["providers"][name] = {
                "status": "disabled", "requested_model": self.prepared[name]["model"],
                "request_sha256": record["request_sha256"], "duration_seconds": 0.0, "reason": "excluded"}
            record["status"] = dual.availability(record["providers"])
            record["comparison"] = dual.comparison(self.shared, record["providers"])
            with self.subTest(name=name), self.assertRaises(PolicyError):
                dual.adjudicate(record, self.decision())
            with self.subTest(collect=name), self.assertRaisesRegex(PolicyError, "required provider cannot be disabled"):
                dual.collect(self.prepared, {}, 30, disabled_providers={name: "excluded"})
        raw = self.raw()
        raw["openai_decisions"] = dual.disabled(self.prepared["openai_decisions"], "excluded")
        record = dual.make_record(self.shared, self.prepared, raw)
        self.assertEqual(record["providers"]["openai_decisions"]["error"], {"category": "invalid_response"})
        self.assertEqual(record["providers"]["openai_decisions"]["status"], "unavailable")
        self.assertEqual(record["status"], "partial")

    def test_v3_cannot_silently_drop_a_provider_or_use_an_unknown_model(self):
        original = dual.make_record(self.shared, self.prepared, self.raw())
        for mutate in (
            lambda record: record["providers"].pop("openai_decisions"),
            lambda record: record["providers"].pop("jev"),
            lambda record: record["providers"].update(unknown=record["providers"]["openai_decisions"]),
            lambda record: record["providers"]["openai_decisions"].update(requested_model="gpt-6-astra"),
            lambda record: record["providers"]["openai_decisions"].update(resolved_model="gpt-6-astra"),
            lambda record: record.update(version=4),
        ):
            record = copy.deepcopy(original)
            mutate(record)
            with self.subTest(mutate=mutate), self.assertRaises(PolicyError):
                dual.adjudicate(record, self.decision())
        with self.assertRaises(PolicyError):
            dual.make_record(self.shared, prepared_request(self.shared), self.raw(), version=3)
        with self.assertRaises(PolicyError):
            dual.make_record(self.shared, self.prepared, self.raw(), version=1)

    def test_v3_partial_and_all_refused_advice_preserve_rejection_obligations(self):
        shared = copy.deepcopy(self.shared)
        shared["questions"]["other"] = copy.deepcopy(shared["questions"]["claim"])
        prepared = self.prepare(shared)
        raw = self.raw(prepared)
        raw["openai_decisions"] = optional_success(prepared["openai_decisions"], "contradicted", ("claim",))
        record = dual.make_record(shared, prepared, raw)
        self.assertEqual(record["version"], 3)
        self.assertEqual(record["providers"]["openai_decisions"]["status"], "partial")
        self.assertEqual(record["comparison"]["claim"]["missing"], {"openai_decisions": "refusal"})
        self.assertEqual(record["comparison"]["other"]["choices"]["openai_decisions"], "contradicted")
        decision = self.decision()
        decision["questions"]["other"] = copy.deepcopy(decision["questions"]["claim"])
        with self.assertRaisesRegex(PolicyError, "each rejected provider judgment"):
            dual.adjudicate(record, decision)
        decision["questions"]["other"]["rejected_judgments"] = {"openai_decisions": "Source and fixture establish this ordering."}
        self.assertEqual(dual.adjudicate(record, decision)["final_decision"]["status"], "resolved")
        raw["openai_decisions"] = optional_success(prepared["openai_decisions"], refusals=("claim", "other"))
        record = dual.make_record(shared, prepared, raw)
        self.assertEqual(record["providers"]["openai_decisions"]["status"], "refusal")
        self.assertEqual(record["status"], "partial")
        decision["questions"]["other"]["rejected_judgments"] = {}
        self.assertEqual(dual.adjudicate(record, decision)["final_decision"]["status"], "resolved")

    def test_frozen_v2_optional_record_remains_offline_adjudicable(self):
        # Exact v2 field shape, hash and model IDs, independent of the current writer.
        record = json.loads('''{
          "version": 2, "status": "success",
          "request": {"state": {"evidence": "The service acknowledges work only after storing it.",
            "claim": "Acknowledgement follows storage."}, "questions": {"claim": {"type": "choice",
            "instructions": "Does the evidence support the claim?", "criteria": {
              "supported": "The evidence establishes the claim.",
              "contradicted": "The evidence establishes an incompatible claim.",
              "insufficient_evidence": "A necessary fact is missing."}}}},
          "request_sha256": "9cbde4a76e716b876eca243a8b43bdad60bae597a6d65ebbddc488ed003d95cd",
          "providers": {
            "jev": {"status": "success", "requested_model": "jev-1.14.0", "resolved_model": "jev-1.14.0",
              "request_sha256": "9cbde4a76e716b876eca243a8b43bdad60bae597a6d65ebbddc488ed003d95cd", "duration_seconds": 0.01,
              "result": {"model": "jev-1.14.0", "answers": {"claim": {"type": "choice", "choice": "supported",
                "probabilities": {"supported": 1.0, "contradicted": 0.0, "insufficient_evidence": 0.0}, "confidence": 1.0}},
                "usage": {"input_tokens": 20, "output_tokens": 0}}, "usage": {"input_tokens": 20, "output_tokens": 0}},
            "subq_snap": {"status": "success", "requested_model": "subq-snap-preview", "resolved_model": "subq-snap-preview",
              "request_sha256": "9cbde4a76e716b876eca243a8b43bdad60bae597a6d65ebbddc488ed003d95cd", "duration_seconds": 0.01,
              "result": {"model": "subq-snap-preview", "answers": {"claim": {"type": "choice", "choice": "supported",
                "probabilities": {"supported": 1.0, "contradicted": 0.0, "insufficient_evidence": 0.0}, "confidence": 1.0}},
                "usage": {"input_tokens": 20, "output_tokens": 0}}, "usage": {"input_tokens": 20, "output_tokens": 0}},
            "openai_decisions": {"status": "disabled", "requested_model": "gpt-6-luna",
              "request_sha256": "9cbde4a76e716b876eca243a8b43bdad60bae597a6d65ebbddc488ed003d95cd",
              "duration_seconds": 0.0, "reason": "missing_credential"}},
          "comparison": {"claim": {"status": "agreement", "choices": {"jev": "supported", "subq_snap": "supported"},
            "missing": {"openai_decisions": "disabled"}}}, "final_decision": {"status": "pending", "questions": {}}
        }''')
        original = copy.deepcopy(record)
        with mock.patch.object(dual, "load_policy", side_effect=AssertionError("no current policy")), \
                mock.patch.object(dual, "collect", side_effect=AssertionError("no hosted calls")):
            self.assertEqual(dual.adjudicate(record, self.decision())["final_decision"]["status"], "resolved")
        self.assertEqual(record, original)
        record["version"] = 3
        with self.assertRaises(PolicyError):
            dual.adjudicate(record, self.decision())

    def test_default_cli_requires_all_three_and_with_openai_is_redundant(self):
        for flags in ([], ["--with-openai"]):
            for openai_key in (None, "fake-openai"):
                with self.subTest(flags=flags, openai_key=bool(openai_key)), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    request_path, output_path = root / "request.json", root / "advice.json"
                    request_path.write_text(json.dumps(self.shared))
                    environment = {"TYPESAFE_API_KEY": "fake-jev", "SUBQ_API_KEY": "fake-snap"}
                    if openai_key:
                        environment["OPENAI_API_KEY"] = openai_key

                    def collect_fixture(prepared, credentials, deadline, **kwargs):
                        self.assertEqual(set(prepared), set(dual.PROVIDERS))
                        self.assertEqual(kwargs["required_providers"], set(dual.PROVIDERS))
                        self.assertEqual(kwargs["disabled_providers"], {})
                        self.assertEqual(deadline, 30)
                        return {name: (optional_success(value) if name == "openai_decisions" else success(value))
                                if credentials[name] else dual.unavailable(value, "missing_credential")
                                for name, value in prepared.items()}

                    with mock.patch.dict(os.environ, environment, clear=True), \
                            mock.patch.object(dual, "load_policy", return_value=self.policy), \
                            mock.patch.object(dual, "collect", side_effect=collect_fixture) as collect:
                        code = dual.main(["--request", str(request_path), "--output", str(output_path), *flags])
                    self.assertEqual(collect.call_count, 1)
                    record = json.loads(output_path.read_text())
                    self.assertEqual(record["version"], 3)
                    self.assertEqual(record["status"], "success" if openai_key else "partial")
                    self.assertEqual(record["providers"]["openai_decisions"]["status"], "success" if openai_key else "unavailable")
                    self.assertEqual(code, 0 if openai_key else 2)
                    self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)
                    self.assertNotIn("fake-", output_path.read_text())

    def test_without_openai_rejects_required_policy_before_output_credentials_or_http(self):
        def environment_lookup(name, default=None):
            if name in {"TYPESAFE_API_KEY", "SUBQ_API_KEY", "OPENAI_API_KEY"}:
                raise AssertionError("no credential lookup")
            # argparse's locale discovery may inspect unrelated environment keys.
            return default

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for dry_run in ([], ["--dry-run"]):
                output_path = root / "advice.json"
                captured = io.StringIO()
                with mock.patch.object(dual, "load_policy", return_value=self.policy), \
                        mock.patch.object(os.environ, "get", side_effect=environment_lookup), \
                        mock.patch.object(dual, "collect", side_effect=AssertionError("no hosted calls")), \
                        mock.patch("sys.stderr", captured):
                    code = dual.main(["--request", str(root / "not-read.json"), "--output", str(output_path),
                                      "--without-openai", *dry_run])
                self.assertEqual(code, 1)
                self.assertIn("required OpenAI adviser cannot be disabled", captured.getvalue())
                self.assertFalse(output_path.exists())

    def test_required_dry_run_previews_all_three_without_disabled_or_http(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, output_path = root / "request.json", root / "advice.json"
            request_path.write_text(json.dumps(self.shared))
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(dual, "load_policy", return_value=self.policy), \
                    mock.patch.object(dual, "collect", side_effect=AssertionError("no hosted calls")):
                self.assertEqual(dual.main(["--request", str(request_path), "--output", str(output_path), "--dry-run"]), 0)
            record = json.loads(output_path.read_text())
            self.assertEqual(record["version"], 3)
            self.assertEqual(set(record["providers"]), set(dual.PROVIDERS))
            self.assertEqual(record["providers"]["openai_decisions"], {"requested_model": "gpt-6-luna", "status": "dry_run"})


if __name__ == "__main__":
    unittest.main()

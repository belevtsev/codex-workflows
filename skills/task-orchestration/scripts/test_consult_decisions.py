"""Offline dual-consultation regressions; no live credentials or external requests."""

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
from validate_policy import DEFAULT_POLICY, PolicyError


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
        if outgoing.full_url != dual.PROVIDERS[provider][0] or timeout <= 0:
            raise AssertionError("incorrect endpoint or timeout")
        sent = json.loads(outgoing.data)
        if sent != prepared:
            raise AssertionError("different provider evidence")
        if isinstance(credential, dict):
            with credential["calls"].get_lock():
                credential["calls"].value += 1
        if scenario == "hang" and provider == "subq_snap":
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
            time.sleep(10)
        if scenario == "http_error":
            raise error.HTTPError(outgoing.full_url, 429, "fake-secret-must-not-leak", {}, None)
        result = success(prepared)["result"]
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
            with mock.patch.object(dual, "collect", side_effect=AssertionError("no network")), \
                    mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake-key", "SUBQ_API_KEY": "fake-key"}, clear=True):
                self.assertEqual(dual.main(["--request", str(request_path), "--output", str(output_path), "--dry-run"]), 0)
                record = json.loads(output_path.read_text())
                self.assertEqual(record["status"], "dry_run")
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


if __name__ == "__main__":
    unittest.main()

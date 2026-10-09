"""Policy and consultation checks using temporary fixtures and mocked network only."""

from contextlib import redirect_stderr, redirect_stdout
import copy
from email.message import Message
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

import yaml


SKILL = Path(__file__).resolve().parents[1] / "skills" / "task-orchestration"
SCRIPTS = SKILL / "scripts"


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with mock.patch.object(sys, "dont_write_bytecode", True):
        spec.loader.exec_module(module)
    return module


POLICY = load_helper("validate_policy")
CONSULT = load_helper("consult_jev")


class FixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nol8-orchestration-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = yaml.safe_load((SKILL / "model-policy.yaml").read_text())
        reference = self.root / self.policy["consultation"]["questions"]
        reference.parent.mkdir(parents=True)
        reference.write_text((SKILL / "references" / "jev-questions.json").read_text())
        self.policy_path = self.root / "model-policy.yaml"
        self.write_policy()
        self.input = {
            "state": {"evidence": "The operation was acknowledged; recovery was not observed."},
            "questions": {
                "claim_support": {
                    "type": "choice", "instructions": "Classify the claim using evidence.",
                    "criteria": {"supported": "Evidence supports the claim.", "insufficient": "Evidence is incomplete."},
                },
            },
        }
        self.request_path = self.root / "request.json"
        self.output_path = self.root / "record.json"
        self.request_path.write_text(json.dumps(self.input))
        self.response = {
            "model": self.policy["consultation"]["model"],
            "answers": {"claim_support": {
                "type": "choice", "choice": "insufficient", "probabilities": {"supported": 0.1, "insufficient": 0.9},
                "confidence": 0.8,
            }},
            "usage": {"input_tokens": 25, "output_tokens": 8},
        }

    def write_policy(self):
        self.policy_path.write_text(yaml.safe_dump(self.policy, sort_keys=False))

    def run_helper(self, dry_run=False, key="fixture-secret-token"):
        self.request_path.write_text(json.dumps(self.input))
        args = ["--policy", str(self.policy_path), "--request", str(self.request_path), "--output", str(self.output_path)]
        if dry_run:
            args.append("--dry-run")
        environment = {} if key is None else {"TYPESAFE_API_KEY": key}
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), redirect_stdout(output), redirect_stderr(errors):
            code = CONSULT.main(args)
        return code, output.getvalue(), errors.getvalue()

    def mocked_response(self, response=None, body=None):
        handle = mock.MagicMock()
        handle.__enter__.return_value = handle
        handle.read.return_value = body if body is not None else json.dumps(response or self.response).encode()
        return handle

    def record(self):
        return json.loads(self.output_path.read_text())


class PolicyTests(FixtureTests):
    def test_current_policy_and_default_cli_validate(self):
        self.assertEqual(self.policy, POLICY.load_policy(self.policy_path))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, POLICY.main([]))

    def test_old_policy_schema_is_rejected_with_a_version_error(self):
        self.policy["version"] = 1
        self.policy.pop("effort_guidance")
        self.policy["sol_max_guidance"] = {"trigger": "historical_policy"}
        for profile in self.policy["profiles"].values():
            profile.pop("scope")
        self.write_policy()
        with self.assertRaisesRegex(POLICY.PolicyError, "policy version"):
            POLICY.load_policy(self.policy_path)

    def test_exact_future_jev_release_is_accepted_but_aliases_are_not(self):
        self.policy["consultation"]["model"] = "jev-2.4.0"
        self.write_policy()
        self.assertEqual("jev-2.4.0", POLICY.load_policy(self.policy_path)["consultation"]["model"])
        for model in ("jev", "jev-latest", "jev-1.13", "jev-1.13.0-preview"):
            with self.subTest(model=model):
                self.policy["consultation"]["model"] = model
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)

    def test_supported_profile_models_efforts_and_scopes_are_editable(self):
        self.policy["profiles"]["sol"].update(
            model="gpt-6-sol", reasoning_effort="xhigh", user_requested_efforts=["high", "max"],
        )
        self.policy["effort_policy"]["default_substantive"] = "xhigh"
        self.policy["profiles"]["luna"].update(reasoning_effort="medium", user_requested_efforts=["high"])
        self.policy["profiles"]["luna_execution"].update(reasoning_effort="high", user_requested_efforts=["max"])
        self.policy["effort_policy"]["configured_max_profiles"] = []
        self.policy["profiles"]["deep_review"] = {
            "model": "gpt-6-astra", "reasoning_effort": "ultra",
            "user_requested_efforts": ["max"], "scope": "substantive",
        }
        self.policy["roles"]["review"] = "deep_review"
        self.policy["roles"]["release_qualification"] = "deep_review"
        self.policy["unknown_role_profile"] = "deep_review"
        self.policy["fallbacks"]["luna_unavailable"] = "deep_review"
        self.write_policy()
        loaded = POLICY.load_policy(self.policy_path)
        self.assertEqual(self.policy, loaded)
        self.assertEqual(
            {"model": "gpt-6-sol", "reasoning_effort": "xhigh"},
            POLICY.resolve_worker(loaded, "coding"),
        )
        self.assertEqual(
            {"model": "gpt-6-sol", "reasoning_effort": "high"},
            POLICY.resolve_worker(loaded, "coding", requested_effort="high"),
        )
        self.assertEqual(
            {"model": "gpt-6-astra", "reasoning_effort": "ultra"},
            POLICY.resolve_worker(loaded, "review"),
        )

    def test_coordinator_default_tracks_its_selected_profile(self):
        self.policy["profiles"]["coordinator_review"] = {
            "model": "gpt-6-astra", "reasoning_effort": "high",
            "user_requested_efforts": ["ultra"], "scope": "substantive",
        }
        self.policy["roles"]["coordinator"] = "coordinator_review"
        self.policy["effort_policy"]["default_substantive"] = "high"
        self.write_policy()
        loaded = POLICY.load_policy(self.policy_path)
        self.assertEqual(
            {"model": "gpt-6-astra", "reasoning_effort": "high"},
            POLICY.resolve_worker(loaded, "coordinator"),
        )
        self.policy["effort_policy"]["default_substantive"] = "ultra"
        self.write_policy()
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.policy_path)

    def test_evidence_and_routine_execution_roles_can_be_promoted_to_substantive(self):
        for role in ("lookup", "summarization", "commit_execution", "pr_authoring_routine", "pr_submission"):
            self.policy["roles"][role] = "sol"
        self.write_policy()
        loaded = POLICY.load_policy(self.policy_path)
        for role in ("lookup", "summarization", "commit_execution", "pr_authoring_routine", "pr_submission"):
            with self.subTest(role=role):
                self.assertEqual(
                    {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"},
                    POLICY.resolve_worker(loaded, role),
                )

    def test_supported_max_profiles_are_derived_and_order_independent(self):
        self.policy["profiles"]["astra_review"] = {
            "model": "gpt-6-astra", "reasoning_effort": "max",
            "user_requested_efforts": ["ultra"], "scope": "substantive",
        }
        self.policy["profiles"]["luna"].update(reasoning_effort="max")
        self.policy["roles"]["coordinator"] = "astra_review"
        self.policy["effort_policy"]["default_substantive"] = "max"
        self.policy["effort_policy"]["configured_max_profiles"] = ["astra_review", "luna", "luna_execution"]
        self.write_policy()
        self.assertEqual(self.policy, POLICY.load_policy(self.policy_path))
        self.policy["effort_policy"]["configured_max_profiles"].reverse()
        self.write_policy()
        self.assertEqual(self.policy, POLICY.load_policy(self.policy_path))

    def test_unsupported_models_efforts_and_profile_shapes_fail(self):
        mutations = (
            lambda value: value["profiles"]["sol"].update(model="gpt-6-unknown"),
            lambda value: value["profiles"]["sol"].update(reasoning_effort="none"),
            lambda value: value["profiles"]["sol"].update(reasoning_effort="minimal"),
            lambda value: value["profiles"]["sol"].update(reasoning_effort="extreme"),
            lambda value: value["profiles"]["sol"].update(user_requested_efforts=["minimal"]),
            lambda value: value["profiles"]["sol"].update(user_requested_efforts=["max", "max"]),
            lambda value: value["profiles"]["sol"].update(scope="unbounded"),
            lambda value: value["profiles"]["sol"].update(model="gpt-6-luna", reasoning_effort="high", user_requested_efforts=[]),
            lambda value: value["profiles"]["luna"].update(reasoning_effort="ultra"),
            lambda value: value["profiles"]["luna"].update(user_requested_efforts=["ultra"]),
            lambda value: value["profiles"]["luna_execution"].update(reasoning_effort="ultra"),
            lambda value: value["profiles"]["luna_execution"].update(user_requested_efforts=["ultra"]),
            lambda value: value["profiles"]["luna_execution"].update(scope="substantive"),
            lambda value: value["profiles"]["sol"].pop("scope"),
            lambda value: value["profiles"].pop("luna"),
            lambda value: value["profiles"].update({" ": copy.deepcopy(value["profiles"]["sol"])}),
        )
        original = copy.deepcopy(self.policy)
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.policy = copy.deepcopy(original)
                mutate(self.policy)
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)

    def test_unsafe_routes_and_unknown_profile_references_fail(self):
        mutations = (
            lambda value: value["roles"].update(coding="missing"),
            lambda value: value["roles"].update(review="luna"),
            lambda value: value["roles"].update(pr_authoring="luna_execution"),
            lambda value: value["roles"].update(pr_authoring_routine="luna"),
            lambda value: value["roles"].update(commit_execution="luna"),
            lambda value: value["roles"].update(pr_submission="luna"),
            lambda value: value["roles"].update(lookup="luna_execution"),
            lambda value: value["roles"].update(summarization="luna_execution"),
            lambda value: value["roles"].update(unrecognized_role="luna"),
            lambda value: value["roles"].update(unrecognized_role="luna_execution"),
            lambda value: value["roles"].pop("review"),
            lambda value: value.update(unknown_role_profile="missing"),
            lambda value: value.update(unknown_role_profile="luna"),
            lambda value: value["fallbacks"].update(luna_unavailable="missing"),
            lambda value: value["fallbacks"].update(luna_unavailable="luna_execution"),
        )
        original = copy.deepcopy(self.policy)
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.policy = copy.deepcopy(original)
                mutate(self.policy)
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)

    def test_commit_and_pr_submission_use_luna_max_while_authoring_uses_sol(self):
        self.assertEqual("sol", self.policy["roles"]["pr_authoring"])
        self.assertEqual("luna_execution", self.policy["roles"]["pr_authoring_routine"])
        self.assertEqual("luna_execution", self.policy["roles"]["commit_execution"])
        self.assertEqual("luna_execution", self.policy["roles"]["pr_submission"])
        self.assertEqual("gpt-6-luna", self.policy["profiles"]["luna_execution"]["model"])
        self.assertEqual("max", self.policy["profiles"]["luna_execution"]["reasoning_effort"])
        self.assertEqual([], self.policy["profiles"]["luna_execution"]["user_requested_efforts"])
        self.assertEqual([], self.policy["profiles"]["luna"]["user_requested_efforts"])
        loaded = POLICY.load_policy(self.policy_path)
        self.assertEqual(
            {"model": "gpt-6-luna", "reasoning_effort": "max"},
            POLICY.resolve_worker(loaded, "commit_execution"),
        )
        self.assertEqual(
            {"model": "gpt-6-luna", "reasoning_effort": "high"},
            POLICY.resolve_worker(loaded, "lookup"),
        )

    def test_effort_policy_keeps_ultra_as_default_and_max_explicit(self):
        self.assertEqual("ultra", self.policy["effort_policy"]["default_substantive"])
        self.assertEqual("explicit_user_request", self.policy["effort_policy"]["max_for_sol"])
        self.assertEqual(["luna_execution"], self.policy["effort_policy"]["configured_max_profiles"])
        self.assertFalse(self.policy["effort_policy"]["automatic_escalation"])

    def test_effort_guidance_is_nonempty_and_editable(self):
        self.assertEqual({"ultra", "max", "comparison"}, set(self.policy["effort_guidance"]))
        for guidance in self.policy["effort_guidance"].values():
            self.assertTrue(guidance.strip())
        self.policy["effort_guidance"].update(
            ultra="Use the configured substantive default.",
            max="Use Sol max only when explicitly requested.",
            comparison="Choose using relevant evidence and the user's constraint.",
        )
        self.write_policy()
        self.assertEqual(self.policy, POLICY.load_policy(self.policy_path))

    def test_activation_accepts_a_unique_nonempty_subset(self):
        for conditions in (["cross_component_change"], ["consequential_uncertainty", "independent_workstreams"]):
            with self.subTest(conditions=conditions):
                self.policy["activation"]["any_of"] = conditions
                self.write_policy()
                self.assertEqual(self.policy, POLICY.load_policy(self.policy_path))

    def test_worker_resolution_keeps_defaults_and_requires_permitted_explicit_override(self):
        loaded = POLICY.load_policy(self.policy_path)
        original = copy.deepcopy(loaded)
        self.assertEqual(
            {"model": "gpt-6.1-sol", "reasoning_effort": "max"},
            POLICY.resolve_worker(loaded, "review", requested_effort="max"),
        )
        self.assertEqual(
            {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"},
            POLICY.resolve_worker(loaded, "review"),
        )
        self.assertEqual(
            {"model": "gpt-6.1-sol", "reasoning_effort": "ultra"},
            POLICY.resolve_worker(loaded, "coordinator"),
        )
        self.assertEqual(original, loaded)
        for role, effort in (("review", "high"), ("lookup", "ultra"), ("commit_execution", "high")):
            with self.subTest(role=role, effort=effort), self.assertRaises(POLICY.PolicyError):
                POLICY.resolve_worker(loaded, role, requested_effort=effort)

    def test_unknown_worker_role_uses_the_configured_substantive_fallback(self):
        self.policy["profiles"]["fallback_review"] = {
            "model": "gpt-6-sol", "reasoning_effort": "xhigh",
            "user_requested_efforts": ["max"], "scope": "substantive",
        }
        self.policy["unknown_role_profile"] = "fallback_review"
        self.write_policy()
        loaded = POLICY.load_policy(self.policy_path)
        self.assertEqual(
            {"model": "gpt-6-sol", "reasoning_effort": "xhigh"},
            POLICY.resolve_worker(loaded, "future_role"),
        )
        self.assertEqual(
            {"model": "gpt-6-sol", "reasoning_effort": "max"},
            POLICY.resolve_worker(loaded, "future_role", requested_effort="max"),
        )
        for profile in ("luna", "luna_execution", "missing"):
            with self.subTest(profile=profile):
                loaded["unknown_role_profile"] = profile
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.resolve_worker(loaded, "future_role")

    def test_sol_max_cannot_be_hidden_in_a_renamed_profile(self):
        for model in ("gpt-6.1-sol", "gpt-6-sol"):
            with self.subTest(model=model):
                self.policy["profiles"]["deep_review"] = {
                    "model": model, "reasoning_effort": "max",
                    "user_requested_efforts": [], "scope": "substantive",
                }
                self.policy["roles"]["review"] = "deep_review"
                self.policy["effort_policy"]["configured_max_profiles"] = ["deep_review", "luna_execution"]
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.resolve_worker(self.policy, "review")

    def test_versions_bools_and_request_limits_are_strict(self):
        mutations = (
            lambda value: value.update(version=True),
            lambda value: value.update(version="1"),
            lambda value: value["consultation"].update(deadline_seconds=31),
            lambda value: value["consultation"].update(deadline_seconds=30.0),
            lambda value: value["consultation"].update(attempts_per_evidence_batch=True),
            lambda value: value["consultation"].update(attempts_per_evidence_batch=2),
            lambda value: value["consultation"].update(automatic_retries="false"),
            lambda value: value["publication"].update(refresh_before_write=1),
            lambda value: value["fixed_specialists"]["context_explorer"].update(respect_runtime_model="true"),
            lambda value: value["effort_policy"].update(default_substantive="max"),
            lambda value: value["effort_policy"].update(max_for_sol="automatic"),
            lambda value: value["effort_policy"].update(configured_max_profiles=["sol"]),
            lambda value: value["effort_policy"].update(configured_max_profiles=[]),
            lambda value: value["effort_policy"].update(configured_max_profiles=["luna_execution", "luna_execution"]),
            lambda value: value["effort_policy"].update(configured_max_profiles=["missing"]),
            lambda value: value["effort_policy"].update(automatic_escalation=True),
            lambda value: value["profiles"]["sol"].update(reasoning_effort="max"),
            lambda value: value["effort_guidance"].update(ultra=" "),
            lambda value: value["effort_guidance"].update(max=[]),
            lambda value: value["effort_guidance"].pop("comparison"),
            lambda value: value["activation"].update(any_of=[]),
            lambda value: value["activation"].update(any_of=["unknown"]),
            lambda value: value["activation"].update(any_of=["cross_component_change", "cross_component_change"]),
            lambda value: value["activation"].update(bypass="all_tasks"),
            lambda value: value["consultation"].update(sharing="all_available_data"),
            lambda value: value["publication"].update(authority="consultation_advice"),
            lambda value: value["fallbacks"].update(sol_unavailable="luna_execution"),
        )
        original = copy.deepcopy(self.policy)
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.policy = copy.deepcopy(original)
                mutate(self.policy)
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)

    def test_missing_escaping_and_invalid_question_references_fail(self):
        for reference in ("references/missing.json", "../questions.json", "/tmp/questions.json"):
            with self.subTest(reference=reference):
                self.policy["consultation"]["questions"] = reference
                self.write_policy()
                with self.assertRaises(POLICY.PolicyError):
                    POLICY.load_policy(self.policy_path)
        self.policy["consultation"]["questions"] = "references/jev-questions.json"
        self.write_policy()
        reference = self.root / self.policy["consultation"]["questions"]
        reference.write_text('{"version": true, "questions": {}}')
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(self.policy_path)

    def test_duplicate_yaml_fields_and_invalid_yaml_fail_cli(self):
        for text in (self.policy_path.read_text() + "version: 1\n", "[broken"):
            self.policy_path.write_text(text)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(1, POLICY.main(["--policy", str(self.policy_path)]))


class ConsultationTests(FixtureTests):
    def test_edited_policy_supports_dry_run_and_mocked_consultation(self):
        self.policy["profiles"]["sol"].update(model="gpt-6-sol", reasoning_effort="xhigh")
        self.policy["effort_policy"]["default_substantive"] = "xhigh"
        self.policy["profiles"]["deep_review"] = {
            "model": "gpt-6-astra", "reasoning_effort": "max",
            "user_requested_efforts": ["ultra"], "scope": "substantive",
        }
        self.policy["effort_policy"]["configured_max_profiles"] = ["deep_review", "luna_execution"]
        self.policy["roles"].update(review="deep_review", commit_execution="sol", lookup="sol")
        self.policy["consultation"]["model"] = "jev-2.4.0"
        self.response["model"] = "jev-2.4.0"
        self.write_policy()
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run), mock.patch.object(
                CONSULT, "open_once", return_value=self.mocked_response(),
            ) as network:
                code, _, errors = self.run_helper(dry_run=dry_run, key=None if dry_run else "fixture-secret-token")
            self.assertEqual((0, ""), (code, errors))
            self.assertEqual("jev-2.4.0", self.record()["request"]["model"])
            self.assertEqual("dry_run" if dry_run else "success", self.record()["status"])
            if dry_run:
                network.assert_not_called()
            else:
                network.assert_called_once()
                self.assertEqual("jev-2.4.0", json.loads(network.call_args.args[0].data)["model"])
            self.output_path.unlink()

    def test_unsafe_policy_fails_helper_before_network_or_output(self):
        original = copy.deepcopy(self.policy)
        for mutate in (
            lambda value: value["profiles"]["luna"].update(reasoning_effort="ultra"),
            lambda value: value["roles"].update(review="missing"),
            lambda value: value["roles"].update(review="luna"),
            lambda value: value["effort_policy"].update(max_for_sol="automatic"),
        ):
            self.policy = copy.deepcopy(original)
            mutate(self.policy)
            self.write_policy()
            with mock.patch.object(CONSULT, "open_once") as network:
                self.assertEqual(1, self.run_helper()[0])
            network.assert_not_called()
            self.assertFalse(self.output_path.exists())

    def test_valid_response_records_exact_request_without_credentials(self):
        self.response["unknown"] = "fixture-secret-token"
        self.response["usage"]["unknown"] = "fixture-secret-token"
        self.response["answers"]["claim_support"]["unknown"] = "fixture-secret-token"
        with mock.patch.object(CONSULT, "open_once", return_value=self.mocked_response()) as network:
            code, stdout, stderr = self.run_helper()
        self.assertEqual((0, "Consultation success\n", ""), (code, stdout, stderr))
        network.assert_called_once()
        outgoing = network.call_args.args[0]
        self.assertEqual(CONSULT.ENDPOINT, outgoing.full_url)
        self.assertEqual("POST", outgoing.get_method())
        self.assertEqual(30, network.call_args.kwargs["timeout"])
        self.assertEqual("Bearer fixture-secret-token", outgoing.get_header("Authorization"))
        prepared = dict(self.input, model=self.policy["consultation"]["model"])
        self.assertEqual(prepared, json.loads(outgoing.data))
        record = self.record()
        self.assertEqual(prepared, record["request"])
        self.assertEqual("success", record["status"])
        self.assertEqual(prepared["model"], record["resolved_model"])
        self.assertEqual({"input_tokens": 25, "output_tokens": 8}, record["usage"])
        self.assertGreaterEqual(record["duration_seconds"], 0)
        self.assertNotIn("fixture-secret-token", self.output_path.read_text() + stdout + stderr)
        self.assertEqual(0o600, stat.S_IMODE(self.output_path.stat().st_mode))

    def test_dry_run_validates_without_network_or_credential(self):
        with mock.patch.object(CONSULT, "open_once") as network:
            code, _, _ = self.run_helper(dry_run=True, key=None)
        self.assertEqual(0, code)
        network.assert_not_called()
        self.assertEqual("dry_run", self.record()["status"])

    def test_missing_credential_still_records_unavailable_without_network(self):
        with mock.patch.object(CONSULT, "open_once") as network:
            code, _, _ = self.run_helper(key=None)
        self.assertEqual(2, code)
        network.assert_not_called()
        self.assertEqual({"category": "missing_credential"}, self.record()["error"])
        self.assertEqual("unavailable", self.record()["status"])

    def test_conflicting_requested_model_fails_before_network_and_output(self):
        self.input["model"] = "jev-1.12.0"
        with mock.patch.object(CONSULT, "open_once") as network:
            code, _, _ = self.run_helper()
        self.assertEqual(1, code)
        network.assert_not_called()
        self.assertFalse(self.output_path.exists())

    def test_equal_requested_model_is_accepted(self):
        self.input["model"] = self.policy["consultation"]["model"]
        with mock.patch.object(CONSULT, "open_once", return_value=self.mocked_response()):
            self.assertEqual(0, self.run_helper()[0])

    def test_nonchoice_malformed_and_nonfinite_inputs_are_rejected(self):
        mutations = (
            lambda value: value["questions"]["claim_support"].update(type="noul"),
            lambda value: value["questions"]["claim_support"].update(criteria={"only": "One"}),
            lambda value: value.update(questions={}),
            lambda value: value.update(extra="unexpected"),
            lambda value: value["state"].update(evidence=float("inf")),
        )
        original = copy.deepcopy(self.input)
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index), mock.patch.object(CONSULT, "open_once") as network:
                self.input = copy.deepcopy(original)
                mutate(self.input)
                self.assertEqual(1, self.run_helper()[0])
                network.assert_not_called()
                self.assertFalse(self.output_path.exists())

    def test_existing_output_and_symlink_are_preserved_before_network(self):
        self.output_path.write_text("previous consultation")
        with mock.patch.object(CONSULT, "open_once") as network:
            self.assertEqual(1, self.run_helper()[0])
        network.assert_not_called()
        self.assertEqual("previous consultation", self.output_path.read_text())
        self.output_path.unlink()
        target = self.root / "unrelated.json"
        target.write_text("unrelated data")
        self.output_path.symlink_to(target)
        with mock.patch.object(CONSULT, "open_once") as network:
            self.assertEqual(1, self.run_helper()[0])
        network.assert_not_called()
        self.assertTrue(self.output_path.is_symlink())
        self.assertEqual("unrelated data", target.read_text())

    def test_invalid_answer_models_ids_types_and_distributions_are_unavailable(self):
        mutations = (
            lambda value: value.update(model="jev-1.12.0"),
            lambda value: value.update(answers={}),
            lambda value: value["answers"].update(unexpected=copy.deepcopy(value["answers"]["claim_support"])),
            lambda value: value["answers"]["claim_support"].update(type="score"),
            lambda value: value["answers"]["claim_support"].update(choice="missing"),
            lambda value: value["answers"]["claim_support"].update(choice="supported"),
            lambda value: value["answers"]["claim_support"].update(probabilities={"supported": 0.2, "missing": 0.8}),
            lambda value: value["answers"]["claim_support"].update(probabilities={"supported": 0.1, "insufficient": 0.6}),
            lambda value: value["answers"]["claim_support"].update(probabilities={"supported": -0.1, "insufficient": 1.1}),
            lambda value: value["answers"]["claim_support"].update(probabilities={"supported": True, "insufficient": False}),
            lambda value: value["answers"]["claim_support"].update(confidence=True),
            lambda value: value["answers"]["claim_support"].update(confidence="0.8"),
            lambda value: value["answers"]["claim_support"].update(confidence=float("nan")),
            lambda value: value["usage"].update(input_tokens=True),
            lambda value: value["usage"].update(output_tokens=-1),
            lambda value: value.update(usage={}),
        )
        original = copy.deepcopy(self.response)
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.response = copy.deepcopy(original)
                mutate(self.response)
                with mock.patch.object(CONSULT, "open_once", return_value=self.mocked_response()) as network:
                    self.assertEqual(2, self.run_helper()[0])
                network.assert_called_once()
                self.assertEqual({"category": "invalid_response"}, self.record()["error"])
                self.assertNotIn("result", self.record())
                self.output_path.unlink()

    def test_maximum_ties_and_distribution_rounding_tolerance_are_valid(self):
        for probabilities in ({"supported": 0.5, "insufficient": 0.5}, {"supported": 0.4, "insufficient": 0.5999999}):
            self.response["answers"]["claim_support"]["probabilities"] = probabilities
            with mock.patch.object(CONSULT, "open_once", return_value=self.mocked_response()):
                self.assertEqual(0, self.run_helper()[0])
            self.output_path.unlink()

    def test_timeout_http_and_network_failures_are_safe_and_never_retried(self):
        cases = (
            (socket.timeout("fixture-secret-token"), {"category": "timeout"}),
            (URLError(socket.timeout("fixture-secret-token")), {"category": "timeout"}),
            (URLError("fixture-secret-token"), {"category": "network_error"}),
            (HTTPError(CONSULT.ENDPOINT, 429, "fixture-secret-token", {}, io.BytesIO(b"fixture-secret-token")),
             {"category": "http_error", "http_status": 429}),
        )
        for failure, expected in cases:
            with self.subTest(category=expected), mock.patch.object(CONSULT, "open_once", side_effect=failure) as network:
                code, stdout, stderr = self.run_helper()
            self.assertEqual(2, code)
            network.assert_called_once()
            self.assertEqual(expected, self.record()["error"])
            self.assertNotIn("fixture-secret-token", self.output_path.read_text() + stdout + stderr)
            self.output_path.unlink()

    def test_malformed_json_duplicate_keys_and_oversize_responses_are_safe(self):
        for body in (b"fixture-secret-token", b'{"model": "one", "model": "two"}', b"x" * (CONSULT.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(length=len(body)), mock.patch.object(CONSULT, "open_once", return_value=self.mocked_response(body=body)) as network:
                code, stdout, stderr = self.run_helper()
            self.assertEqual(2, code)
            network.assert_called_once()
            self.assertEqual({"category": "invalid_response"}, self.record()["error"])
            self.assertNotIn("fixture-secret-token", self.output_path.read_text() + stdout + stderr)
            self.output_path.unlink()

    def test_response_read_timeout_is_unavailable_and_does_not_retry(self):
        handle = self.mocked_response()
        handle.read.side_effect = socket.timeout("fixture-secret-token")
        with mock.patch.object(CONSULT, "open_once", return_value=handle) as network:
            self.assertEqual(2, self.run_helper()[0])
        network.assert_called_once()
        self.assertEqual({"category": "timeout"}, self.record()["error"])

    def test_total_deadline_covers_response_stream_and_restores_signal_handler(self):
        previous_handler = CONSULT.signal.getsignal(CONSULT.signal.SIGALRM)
        handle = self.mocked_response()

        def stalled_stream(_limit):
            remaining, _interval = CONSULT.signal.getitimer(CONSULT.signal.ITIMER_REAL)
            self.assertGreater(remaining, 0)
            self.assertLessEqual(remaining, 30)
            # Trigger the configured deadline without waiting or using a real socket.
            CONSULT.signal.getsignal(CONSULT.signal.SIGALRM)(CONSULT.signal.SIGALRM, None)

        handle.read.side_effect = stalled_stream
        with mock.patch.object(CONSULT, "open_once", return_value=handle) as network:
            self.assertEqual(2, self.run_helper()[0])
        network.assert_called_once()
        self.assertEqual({"category": "timeout"}, self.record()["error"])
        self.assertEqual(previous_handler, CONSULT.signal.getsignal(CONSULT.signal.SIGALRM))
        self.assertEqual((0, 0), CONSULT.signal.getitimer(CONSULT.signal.ITIMER_REAL))

    def test_redirect_is_unavailable_without_a_second_request_or_forwarded_token(self):
        response = io.BytesIO(b"fixture-secret-token")
        response.code = 302
        response.msg = "Found"
        response.headers = Message()
        response.headers["Location"] = "https://untrusted.example/collect"
        response.info = lambda: response.headers
        with mock.patch.object(CONSULT.request.HTTPSHandler, "https_open", return_value=response) as network:
            code, stdout, stderr = self.run_helper()
        self.assertEqual(2, code)
        network.assert_called_once()
        outgoing = network.call_args.args[0]
        self.assertEqual(CONSULT.ENDPOINT, outgoing.full_url)
        self.assertEqual("POST", outgoing.get_method())
        self.assertEqual({"category": "http_error", "http_status": 302}, self.record()["error"])
        self.assertNotIn("fixture-secret-token", self.output_path.read_text() + stdout + stderr)


if __name__ == "__main__":
    unittest.main()

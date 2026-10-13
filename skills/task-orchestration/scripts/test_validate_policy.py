"""Optional policy-helper regressions; needs PyYAML, never live credentials."""

import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from validate_policy import DEFAULT_POLICY, PolicyError, load_policy, resolve_worker


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()

    def load_variant(self, policy):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "references").mkdir()
            (root / "references" / "jev-questions.json").write_bytes(
                (DEFAULT_POLICY.parent / "references" / "jev-questions.json").read_bytes())
            path = root / "model-policy.yaml"
            path.write_text(yaml.safe_dump(policy), encoding="utf-8")
            return load_policy(path)

    def test_current_routes_and_explicit_overrides(self):
        for role in ("coordinator", "coding", "planning", "review", "documentation", "unknown-role"):
            with self.subTest(role=role):
                self.assertEqual(resolve_worker(self.policy, role),
                                 {"model": "gpt-6.1-sol", "reasoning_effort": "max"})
        for role in ("commit_execution", "pr_authoring_routine", "pr_submission"):
            self.assertEqual(resolve_worker(self.policy, role),
                             {"model": "gpt-6-luna", "reasoning_effort": "xhigh"})
        for role in ("lookup", "summarization"):
            self.assertEqual(resolve_worker(self.policy, role),
                             {"model": "gpt-6-luna", "reasoning_effort": "high"})
        for effort in ("max", "xhigh", "ultra"):
            self.assertEqual(resolve_worker(self.policy, "coding", effort)["reasoning_effort"], effort)
        self.assertEqual(self.policy["profiles"]["sol"]["reasoning_effort"], "max")
        for role, effort in (("lookup", "ultra"), ("commit_execution", "max"), ("coding", "high")):
            with self.subTest(role=role, effort=effort), self.assertRaises(PolicyError):
                resolve_worker(self.policy, role, effort)

    def test_historical_v2_policy(self):
        legacy = copy.deepcopy(self.policy)
        legacy["consultation"].pop("providers", None)
        legacy["consultation"].pop("comparison", None)
        legacy["profiles"]["sol"].update(reasoning_effort="ultra", user_requested_efforts=["max"])
        legacy["profiles"]["luna_execution"]["reasoning_effort"] = "max"
        legacy["effort_policy"].update(default_substantive="ultra", max_for_sol="explicit_user_request",
                                     configured_max_profiles=["luna_execution"])
        del legacy["effort_guidance"]["xhigh"]
        loaded = self.load_variant(legacy)
        self.assertEqual(resolve_worker(loaded, "coding")["reasoning_effort"], "ultra")
        self.assertEqual(resolve_worker(loaded, "coding", "max")["reasoning_effort"], "max")
        self.assertEqual(resolve_worker(loaded, "commit_execution")["reasoning_effort"], "max")

    def test_dual_consultation_policy(self):
        self.assertEqual(self.policy["consultation"]["providers"], {
            "jev": "jev-1.13.0", "subq_snap": "subq-snap-preview",
        })
        for missing in ("providers", "comparison"):
            variant = copy.deepcopy(self.policy)
            del variant["consultation"][missing]
            with self.subTest(missing=missing), self.assertRaises(PolicyError):
                self.load_variant(variant)
        for providers in ({"jev": "jev-1.13.0"},
                          {"jev": "jev-1.12.0", "subq_snap": "subq-snap-preview"},
                          {"jev": "jev-1.13.0", "subq_snap": "subq-preview"},
                          {"jev": "jev-1.13.0", "subq_snap": "subq-snap-preview", "other": "model"}):
            variant = copy.deepcopy(self.policy)
            variant["consultation"]["providers"] = providers
            with self.subTest(providers=providers), self.assertRaises(PolicyError):
                self.load_variant(variant)
        variant = copy.deepcopy(self.policy)
        variant["consultation"]["comparison"] = "highest_confidence"
        with self.assertRaises(PolicyError):
            self.load_variant(variant)

    def test_configured_max_declaration_is_exact(self):
        for names in ([], ["luna"], ["sol", "luna"], ["sol", "sol"], ["missing"]):
            variant = copy.deepcopy(self.policy)
            variant["effort_policy"]["configured_max_profiles"] = names
            with self.subTest(names=names), self.assertRaises(PolicyError):
                self.load_variant(variant)
        variant = copy.deepcopy(self.policy)
        variant["profiles"]["second_sol"] = copy.deepcopy(variant["profiles"]["sol"])
        variant["effort_policy"]["configured_max_profiles"].append("second_sol")
        self.load_variant(variant)

    def test_legacy_rule_rejects_configured_sol_max(self):
        variant = copy.deepcopy(self.policy)
        variant["effort_policy"]["max_for_sol"] = "explicit_user_request"
        with self.assertRaises(PolicyError):
            self.load_variant(variant)
        with self.assertRaises(PolicyError):
            resolve_worker(variant, "coding")

    def test_preserved_safeguards(self):
        cases = (
            ("effort_policy", "max_for_sol", "automatic"),
            ("effort_policy", "automatic_escalation", True),
            ("effort_policy", "default_substantive", "ultra"),
            ("roles", "coding", "luna_execution"),
            ("fallbacks", "luna_unavailable", "luna"),
            ("fallbacks", "sol_unavailable", "gpt-6-luna"),
            ("publication", "authority", "agent_choice"),
            ("consultation", "automatic_retries", True),
            ("effort_guidance", "xhigh", ""),
        )
        for section, key, value in cases:
            variant = copy.deepcopy(self.policy)
            variant[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(PolicyError):
                self.load_variant(variant)
        for field, value in (("model", "unknown"), ("reasoning_effort", "ultra"), ("scope", "substantive")):
            variant = copy.deepcopy(self.policy)
            variant["profiles"]["luna_execution"][field] = value
            with self.subTest(field=field), self.assertRaises(PolicyError):
                self.load_variant(variant)


if __name__ == "__main__":
    unittest.main()

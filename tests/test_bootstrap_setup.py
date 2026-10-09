"""One journal setup and model enrollment integration over isolated Git fixtures."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import unittest
from unittest import mock

import test_bootstrap as fixtures
from test_bootstrap import snapshot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap
import model_config


class SetupTests(unittest.TestCase):
    # Reuse fixture helpers without rerunning the inherited installer test suite.
    setUp = fixtures.BootstrapFixtures.setUp
    tearDown = fixtures.BootstrapFixtures.tearDown
    run_git = fixtures.BootstrapFixtures.run_git
    head = fixtures.BootstrapFixtures.head
    cli = fixtures.BootstrapFixtures.cli
    install = fixtures.BootstrapFixtures.install
    current = fixtures.BootstrapFixtures.current
    new_release = fixtures.BootstrapFixtures.new_release
    reset_source_to_first = fixtures.BootstrapFixtures.reset_source_to_first
    installer = fixtures.BootstrapFixtures.installer

    @property
    def config(self):
        return self.codex / "config.toml"

    def setup(self):
        return self.cli("setup", "--apply")

    def set_policy(self, model="gpt-6-sol", effort="high"):
        path = self.repo / self.manifest["model_policy"]
        data = path.read_text()
        data = re.sub(r"(  sol:\n    model: )[^\n]+", lambda match: match.group(1) + model, data)
        data = re.sub(r"(  sol:\n    model: [^\n]+\n    reasoning_effort: )[^\n]+", lambda match: match.group(1) + effort, data)
        data = re.sub(r"(  default_substantive: )[^\n]+", lambda match: match.group(1) + effort, data)
        path.write_text(data)
        self.run_git("add", str(path))
        self.run_git("commit", "-m", "Alternate valid coordinator defaults")
        return self.head()

    def test_fresh_setup_dry_run_has_no_writes_and_apply_owns_one_release(self):
        before_home, before_git = snapshot(self.home), snapshot(self.repo / ".git")
        report = self.cli("setup")
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["changed"])
        self.assertFalse(self.state.exists())
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)
        self.setup()
        status = self.cli("status")
        self.assertTrue(status["model_config"]["managed"])
        self.assertEqual(status["model_defaults"], {"model": "gpt-6.1-sol", "model_reasoning_effort": "ultra"})
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertFalse((self.state / "journal.json").exists())

    def test_same_sha_is_verified_noop_and_install_enrolls_without_history(self):
        self.install()
        self.assertFalse(self.cli("status")["model_config"]["managed"])
        self.codex.mkdir(exist_ok=True)
        original = b"model = 'prior'\n# user\n"
        self.config.write_bytes(original)
        self.assertTrue(self.setup()["changed"])
        self.assertEqual(self.installer("status").state()["history"], [])
        before_home, before_state, before_git = snapshot(self.home), snapshot(self.state), snapshot(self.repo / ".git")
        self.assertFalse(self.cli("setup")["changed"])
        self.assertFalse(self.setup()["changed"])
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)
        self.cli("uninstall", "--apply")
        self.assertEqual(self.config.read_bytes(), original)

    def test_setup_fast_forward_uses_local_sha_and_never_fetches(self):
        self.setup()
        second = self.set_policy()
        self.run_git("remote", "set-url", "origin", "https://invalid.invalid/no-network")
        before_git = snapshot(self.repo / ".git")
        self.assertEqual(self.setup()["release"], second)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)
        self.assertEqual(self.cli("status")["model_defaults"]["model"], "gpt-6-sol")
        self.assertEqual(self.installer("status").state()["history"][0]["release"], self.first)
        self.cli("rollback", "--apply")
        self.assertEqual(self.cli("status")["model_defaults"]["model"], "gpt-6.1-sol")
        self.assertIn(b'gpt-6.1-sol', self.config.read_bytes())

    def test_setup_refuses_rewind_divergence_dirty_and_changed_manifest(self):
        self.setup()
        second = self.new_release()
        self.setup()
        self.reset_source_to_first()
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("rewinds", self.cli("setup", "--apply", okay=False))
        path = self.repo / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + b"\nDivergent fixture\n")
        self.run_git("add", str(path))
        self.run_git("commit", "-m", "Divergent fixture")
        self.assertIn("diverged", self.cli("setup", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)
        self.run_git("reset", "--hard", second)
        (self.repo / "untracked").write_text("dirty")
        self.assertIn("dirty", self.cli("setup", "--apply", okay=False))
        (self.repo / "untracked").unlink()
        path = self.repo / "skills-manifest.json"
        manifest = json.loads(path.read_bytes())
        manifest["registrations"]["new-name"] = manifest["registrations"].pop("code-review")
        path.write_text(json.dumps(manifest))
        entrypoint = self.repo / manifest["registrations"]["new-name"] / "SKILL.md"
        entrypoint.write_text(entrypoint.read_text().replace("name: code-review", "name: new-name"))
        self.run_git("add", str(path), str(entrypoint))
        self.run_git("commit", "-m", "Change registration name")
        self.assertIn("Registration names", self.cli("setup", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_malformed_symlinked_and_changed_owned_model_refuse_without_writes(self):
        self.codex.mkdir()
        self.config.write_bytes(b"model =")
        before = snapshot(self.home)
        self.assertIn("malformed", self.cli("setup", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(self.state.exists())
        self.config.unlink()
        destination = self.base / "foreign.toml"
        destination.write_bytes(b"# foreign\n")
        self.config.symlink_to(destination)
        self.assertIn("symlinked", self.cli("setup", "--apply", okay=False))
        self.config.unlink()
        self.setup()
        self.config.write_text(self.config.read_text().replace('"ultra"', '"high"'))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        for command in ("status", "setup", "update", "uninstall"):
            self.assertIn("Owned model", self.cli(command, "--apply", okay=False))
            self.assertEqual(snapshot(self.home), before_home)
            self.assertEqual(snapshot(self.state), before_state)

    def test_fresh_setup_faults_recover_all_activation_boundaries(self):
        self.codex.mkdir()
        original = b"model = 'original'\nother = 'before'\n"
        self.config.write_bytes(original)
        labels = ["after-journal", "after-pointer", *["after-registration:" + name for name in self.manifest["registrations"]], "after-global", "after-model-config", "after-state"]
        for label in labels:
            with self.subTest(label=label):
                self.assertIn("Injected", self.cli("setup", "--apply", okay=False, fault=label))
                journal = json.loads((self.state / "journal.json").read_bytes())
                config_operations = [item for item in journal["operations"] if item["kind"] == "model_config"]
                self.assertEqual(len(config_operations), 1)
                self.assertNotIn("data", json.dumps(config_operations))
                self.config.write_bytes(self.config.read_bytes() + b"# independent later\n")
                self.cli("recover", "--apply")
                self.assertFalse(self.cli("status")["installed"])
                self.assertEqual(self.config.read_bytes(), original + b"# independent later\n")
                self.config.write_bytes(original)

    def test_publication_fault_leaves_config_untouched_and_exact_stage_can_resume(self):
        self.codex.mkdir()
        self.config.write_bytes(b"model = 'original'\n")
        before = snapshot(self.home)
        self.cli("setup", "--apply", okay=False, fault="after-release-publication")
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse((self.state / "journal.json").exists())
        self.assertFalse(self.cli("recover", "--apply")["pending"])
        self.assertEqual(self.setup()["release"], self.first)

    def test_update_rollback_and_uninstall_keep_initial_enrollment_origin(self):
        self.codex.mkdir()
        original = b"model = 'original' # keep\n[profile]\nmodel = 'profile'\n"
        self.config.write_bytes(original)
        self.install()
        self.new_release("Before model enrollment")
        self.cli("update", "--apply")
        self.setup()
        second = self.set_policy()
        self.run_git("push", str(self.remote), "main")
        self.cli("update", "--apply")
        self.assertEqual(self.cli("status")["release"], second)
        self.assertIn(b"gpt-6-sol", self.config.read_bytes())
        self.cli("rollback", "--apply")
        self.cli("rollback", "--apply")
        self.assertTrue(self.cli("status")["model_config"]["managed"])
        self.assertEqual(self.cli("status")["release"], self.first)
        self.assertIn(b"gpt-6.1-sol", self.config.read_bytes())
        self.config.write_bytes(self.config.read_bytes() + b"other = 'later'\n")
        self.cli("uninstall", "--apply")
        self.assertEqual(self.config.read_bytes(), original + b"other = 'later'\n")

    def test_existing_setup_faults_and_recovery_retry_keep_later_config_edits(self):
        self.setup()
        second = self.set_policy()
        for label in ("after-journal", "after-pointer", "after-global", "after-model-config", "after-state"):
            with self.subTest(label=label):
                self.cli("setup", "--apply", okay=False, fault=label)
                self.config.write_bytes(self.config.read_bytes() + b"# after failure\n")
                self.cli("recover", "--apply")
                self.assertEqual(self.cli("status")["release"], self.first)
                self.assertIn(b"# after failure", self.config.read_bytes())
                self.assertNotIn(b"gpt-6-sol", self.config.read_bytes())
        self.cli("setup", "--apply", okay=False, fault="after-model-config")
        self.config.write_bytes(self.config.read_bytes() + b"# first edit\n")
        self.cli("recover", "--apply", okay=False, fault="after-recover-model-config")
        self.config.write_bytes(self.config.read_bytes() + b"# second edit\n")
        self.cli("recover", "--apply")
        self.assertIn(b"# first edit\n# second edit\n", self.config.read_bytes())
        self.assertEqual(self.cli("status")["release"], self.first)
        self.assertEqual(self.setup()["release"], second)

    def test_model_recovery_edit_refuses_all_partial_reversals(self):
        self.setup()
        self.set_policy()
        self.cli("setup", "--apply", okay=False, fault="after-model-config")
        self.config.write_text(self.config.read_text().replace('"high"', '"medium"'))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("Owned model", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_managed_rollback_and_uninstall_faults_recover_model_values_and_modes(self):
        self.codex.mkdir()
        self.config.write_bytes(b"model = 'original'\n")
        self.setup()
        second = self.set_policy()
        self.setup()
        for command in ("rollback", "uninstall"):
            for label in ("after-global", "after-model-config", "after-pointer", "after-state"):
                with self.subTest(command=command, label=label):
                    self.cli(command, "--apply", okay=False, fault=label)
                    contents = self.config.read_bytes() if self.config.exists() else b""
                    self.config.write_bytes(contents + b"# unrelated after fault\n")
                    self.config.chmod(0o604)
                    self.cli("recover", "--apply")
                    self.assertEqual(self.cli("status")["release"], second)
                    self.assertIn(b"gpt-6-sol", self.config.read_bytes())
                    self.assertIn(b"# unrelated after fault", self.config.read_bytes())
                    self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o604)

    def test_enrollment_after_install_survives_fault_with_existing_release(self):
        self.install()
        self.config.write_bytes(b"model = 'original'\n")
        for label in ("after-journal", "after-model-config", "after-state"):
            with self.subTest(label=label):
                self.cli("setup", "--apply", okay=False, fault=label)
                self.config.write_bytes(self.config.read_bytes() + b"# enrollment edit\n")
                self.cli("recover", "--apply")
                self.assertFalse(self.cli("status")["model_config"]["managed"])
                self.assertEqual(self.config.read_bytes(), b"model = 'original'\n# enrollment edit\n")
                self.config.write_bytes(b"model = 'original'\n")

    def test_uninstall_deleted_created_config_recovery_restores_preimage_mode(self):
        self.setup()
        self.config.chmod(0o640)
        self.cli("uninstall", "--apply", okay=False, fault="after-model-config")
        self.assertFalse(self.config.exists())
        self.cli("recover", "--apply")
        self.assertTrue(self.cli("status")["model_config"]["managed"])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_uninstall_concurrent_mode_change_refuses_delete_and_recovery_keeps_mode(self):
        self.setup()
        self.config.chmod(0o640)
        installer = self.installer("uninstall")
        original = installer.transact
        def chmod_then_apply(command, operations):
            self.config.chmod(0o604)
            return original(command, operations)
        with mock.patch.object(installer, "transact", side_effect=chmod_then_apply):
            with self.assertRaisesRegex(model_config.ModelConfigError, "mode changed"):
                installer.uninstall()
        self.assertTrue(self.config.exists())
        self.cli("recover", "--apply")
        self.assertTrue(self.cli("status")["model_config"]["managed"])
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o604)

    def test_journal_allowlist_rejects_full_file_config_and_nonowned_keys(self):
        self.cli("setup", "--apply", okay=False, fault="after-journal")
        path = self.state / "journal.json"
        journal = json.loads(path.read_bytes())
        config_operation = next(item for item in journal["operations"] if item["kind"] == "model_config")
        config_operation["path"] = str(self.base / "foreign")
        path.write_bytes(bootstrap.json_bytes(bootstrap.sealed(journal)))
        self.assertIn("Unsafe model config path", self.cli("recover", "--apply", okay=False))
        config_operation["path"] = str(self.config)
        config_operation["kind"] = "path"
        path.write_bytes(bootstrap.json_bytes(bootstrap.sealed(journal)))
        self.assertIn("keyed", self.cli("recover", "--apply", okay=False))

    def test_setup_lock_and_owned_value_concurrency_refuse_or_preserve_unrelated(self):
        self.setup()
        with (self.state / "mutation.lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("lock", self.cli("setup", "--apply", okay=False))
        installer = self.installer("setup")
        self.set_policy()
        original = installer.transact
        def edit_then_apply(command, operations):
            self.config.write_bytes(self.config.read_bytes() + b"# concurrent independent\n")
            return original(command, operations)
        with mock.patch.object(installer, "transact", side_effect=edit_then_apply):
            installer.setup()
        self.assertIn(b"# concurrent independent", self.config.read_bytes())
        self.set_policy(model="gpt-6.1-sol", effort="ultra")
        def change_owned(command, operations):
            self.config.write_text(self.config.read_text().replace('"high"', '"medium"'))
            return original(command, operations)
        with mock.patch.object(installer, "transact", side_effect=change_owned):
            with self.assertRaisesRegex(model_config.ModelConfigError, "Owned"):
                installer.setup()
        self.assertIn(b'"medium"', self.config.read_bytes())


if __name__ == "__main__":
    unittest.main()

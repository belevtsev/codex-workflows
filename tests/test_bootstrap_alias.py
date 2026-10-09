"""Transactional cw enrollment over isolated Git and home fixtures."""
import json
from pathlib import Path
import stat
import sys
import unittest

import test_bootstrap as fixtures
from test_bootstrap import snapshot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap


class BootstrapAliasTests(unittest.TestCase):
    tearDown = fixtures.BootstrapFixtures.tearDown
    run_git = fixtures.BootstrapFixtures.run_git
    head = fixtures.BootstrapFixtures.head
    cli = fixtures.BootstrapFixtures.cli
    install = fixtures.BootstrapFixtures.install
    current = fixtures.BootstrapFixtures.current
    new_release = fixtures.BootstrapFixtures.new_release
    installer = fixtures.BootstrapFixtures.installer

    def setUp(self):
        fixtures.BootstrapFixtures.setUp(self)
        self.environment["SHELL"] = "/bin/bash"
        self.environment.pop("ZDOTDIR", None)
        self.rc = self.home / ".bashrc"

    def setup(self, *args):
        return self.cli("setup", "--apply", *args)

    def state_value(self):
        return json.loads((self.state / "state.json").read_bytes())

    def test_fresh_setup_dry_run_repeat_and_uninstall_are_reversible(self):
        before_home, before_git = snapshot(self.home), snapshot(self.repo / ".git")
        report = self.cli("setup")
        self.assertEqual(report["command_alias"]["shell"], "bash")
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)
        self.assertFalse(self.state.exists())
        self.assertTrue(self.setup()["command_alias"]["managed"])
        self.assertEqual(self.cli("status")["command_alias"]["path"], str(self.rc))
        metadata = self.state_value()["command_alias"]
        self.assertEqual(metadata["source"], str(self.repo))
        self.assertEqual(self.rc.read_text(), metadata["segment"])
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertFalse(self.setup()["changed"])
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)
        self.cli("uninstall", "--apply")
        self.assertFalse(self.rc.exists())
        self.assertFalse(self.cli("status")["command_alias"]["managed"])

    def test_existing_home_rc_enrollment_keeps_credentials_and_selective_uninstall(self):
        original = b"# private shell config\nexport USER_SECRET='do-not-record'"
        self.rc.write_bytes(original)
        self.rc.chmod(0o640)
        self.install()
        self.assertNotIn("command_alias", self.state_value())
        self.assertFalse(self.cli("status")["command_alias"]["managed"])
        self.setup()
        self.assertNotIn("USER_SECRET", (self.state / "state.json").read_text())
        self.rc.write_bytes(self.rc.read_bytes() + b"# independent later edit\n")
        self.rc.chmod(0o604)
        self.cli("uninstall", "--apply")
        self.assertEqual(self.rc.read_bytes(), original + b"# independent later edit\n")
        self.assertEqual(stat.S_IMODE(self.rc.stat().st_mode), 0o604)

    def test_explicit_optout_unsupported_shell_and_zdotdir_leave_rc_untouched(self):
        self.environment["SHELL"] = "/bin/fish"
        report = self.cli("setup")
        self.assertIn("unsupported shell fish", report["command_alias"]["status"])
        self.assertFalse(report["command_alias"]["managed"])
        self.environment["SHELL"] = "/bin/zsh"
        self.environment["ZDOTDIR"] = str(self.home / "nested")
        self.assertIn("ZDOTDIR", self.setup()["command_alias"]["status"])
        self.assertFalse((self.home / ".zshrc").exists())
        self.assertNotIn("command_alias", self.state_value())
        self.environment.pop("ZDOTDIR")
        self.assertEqual(self.setup("--shell", "none")["command_alias"]["status"], "disabled")
        self.assertFalse((self.home / ".zshrc").exists())
        self.assertTrue(self.setup("--shell", "bash")["command_alias"]["managed"])
        self.assertTrue(self.rc.exists())

    def test_zsh_selection_survives_setup_update_and_older_release_rollback(self):
        self.setup("--shell", "zsh")
        zshrc = self.home / ".zshrc"
        original = zshrc.read_bytes()
        self.environment["SHELL"] = "/bin/fish"
        self.assertFalse(self.setup()["changed"])
        self.new_release()
        self.cli("update", "--apply")
        self.cli("rollback", "--apply")
        self.assertEqual(zshrc.read_bytes(), original)
        self.assertFalse(self.rc.exists())
        self.assertEqual(self.cli("status")["command_alias"]["shell"], "zsh")
        self.cli("uninstall", "--apply")
        self.assertFalse(zshrc.exists())

    def test_setup_from_another_checkout_refuses_before_activation(self):
        self.setup()
        other = self.base / "alternate checkout"
        self.run_git("clone", str(self.repo), str(other))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        message = self.cli("setup", "--apply", "--source", str(other), okay=False)
        self.assertIn("enrolled checkout or uninstall", message)
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_definitions_markers_symlinks_refuse_before_installation_writes(self):
        for initial in (b"if true; then alias cw='prior'; fi\n", b"# >>> codex-workflows cw >>>\n", b"function cw { :; }\n"):
            self.rc.write_bytes(initial)
            before = snapshot(self.home)
            self.assertIn("cw", self.cli("setup", "--apply", okay=False))
            self.assertEqual(snapshot(self.home), before)
            self.assertFalse(self.state.exists())
        self.rc.unlink()
        target = self.base / "foreign.rc"
        target.write_bytes(b"foreign")
        self.rc.symlink_to(target)
        self.assertIn("symlinked", self.cli("setup", "--apply", okay=False))
        self.assertEqual(target.read_bytes(), b"foreign")
        self.assertFalse(self.state.exists())

    def test_fresh_fault_recovery_keeps_unrelated_rc_bytes_out_of_journal(self):
        original = b"export USER_SECRET='do-not-record'\n"
        self.rc.write_bytes(original)
        for label in ("after-journal", "after-command-alias", "after-state"):
            with self.subTest(label=label):
                self.cli("setup", "--apply", okay=False, fault=label)
                journal_bytes = (self.state / "journal.json").read_bytes()
                self.assertNotIn(b"USER_SECRET", journal_bytes)
                journal = json.loads(journal_bytes)
                operations = [item for item in journal["operations"] if item["kind"] == "command_alias"]
                self.assertEqual(len(operations), 1)
                self.assertNotIn("data", operations[0])
                self.rc.write_bytes(self.rc.read_bytes() + b"# edit during interruption\n")
                self.cli("recover", "--apply")
                self.assertFalse(self.cli("status")["installed"])
                self.assertEqual(self.rc.read_bytes(), original + b"# edit during interruption\n")
                self.rc.write_bytes(original)

    def test_uninstall_and_interrupted_recovery_restore_owned_alias_selectively(self):
        original = b"# original rc\n"
        self.rc.write_bytes(original)
        self.setup()
        self.cli("uninstall", "--apply", okay=False, fault="after-command-alias")
        self.assertEqual(self.rc.read_bytes(), original)
        self.rc.write_bytes(original + b"# edit after removal\n")
        self.cli("recover", "--apply", okay=False, fault="after-recover-command-alias")
        self.rc.write_bytes(self.rc.read_bytes() + b"# edit during recovery\n")
        self.cli("recover", "--apply")
        self.assertTrue(self.cli("status")["command_alias"]["managed"])
        self.cli("uninstall", "--apply")
        self.assertEqual(self.rc.read_bytes(), original + b"# edit after removal\n# edit during recovery\n")

    def test_modified_alias_blocks_preflight_all_reversals_and_owned_commands(self):
        self.setup()
        self.rc.write_bytes(self.rc.read_bytes().replace(b'"$@"', b'"$1"'))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        for command in ("status", "setup", "update", "rollback", "uninstall"):
            self.assertIn("cw", self.cli(command, "--apply", okay=False))
            self.assertEqual(snapshot(self.home), before_home)
            self.assertEqual(snapshot(self.state), before_state)
        metadata = self.state_value()["command_alias"]
        self.rc.write_text(metadata["segment"])
        self.cli("uninstall", "--apply", okay=False, fault="after-journal")
        self.rc.write_bytes(self.rc.read_bytes().replace(b'"$@"', b'"$1"'))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("cw", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_state_and_journal_alias_paths_are_whitelisted_and_keyed(self):
        self.setup()
        state_path = self.state / "state.json"
        original = self.state_value()
        invalid = dict(original, command_alias=dict(original["command_alias"], path=str(self.base / "foreign.rc")))
        state_path.write_bytes(bootstrap.json_bytes(bootstrap.sealed(invalid)))
        self.assertIn("cw startup path", self.cli("status", okay=False))
        state_path.write_bytes(bootstrap.json_bytes(original))
        self.cli("uninstall", "--apply", okay=False, fault="after-journal")
        journal_path = self.state / "journal.json"
        journal = json.loads(journal_path.read_bytes())
        original_journal = bootstrap.json_bytes(journal)
        operation = next(item for item in journal["operations"] if item["kind"] == "command_alias")
        operation.update(kind="path", before={"kind": "absent"}, after={"kind": "absent"})
        journal_path.write_bytes(bootstrap.json_bytes(bootstrap.sealed(journal)))
        before = snapshot(self.home)
        self.assertIn("Unsafe path", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)
        journal = json.loads(original_journal)
        state_operation = next(item for item in journal["operations"] if item["path"] == str(state_path))
        embedded_state = json.loads(bootstrap.decode(state_operation["before"]["data"]))
        embedded_state["command_alias"]["path"] = str(self.base / "foreign.rc")
        state_operation["before"]["data"] = bootstrap.encode(bootstrap.json_bytes(bootstrap.sealed(embedded_state)))
        journal_path.write_bytes(bootstrap.json_bytes(bootstrap.sealed(journal)))
        self.assertIn("cw startup path", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)


if __name__ == "__main__":
    unittest.main()

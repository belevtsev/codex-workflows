"""Byte-preserving shell block ownership and real-shell argv forwarding."""
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import command_alias as alias


class CommandAliasTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cw fixture '")
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "editable source ' $dollar"
        self.home = self.base / "home ' with spaces"
        self.codex = self.base / "codex ' home"
        self.state = self.base / "state ' dir"
        self.source.mkdir()
        self.home.mkdir()
        (self.source / "install.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.source / "install.sh").chmod(0o755)
        self.rc = self.home / ".bashrc"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, choice="bash", metadata=None):
        return alias.prepare(self.source, self.home, self.codex, self.state, choice, metadata)

    def apply(self, operation):
        data, mode = alias.render(operation, self.home, self.codex, self.state)
        path = Path(operation["path"])
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)
            path.chmod(mode)

    def test_missing_shell_defaults_bash_explicit_choices_and_zdotdir_limitation(self):
        self.assertEqual(alias.selected_shell("auto", self.home, {}), ("bash", "enrolled"))
        self.assertEqual(alias.selected_shell("auto", self.home, {"SHELL": "/bin/zsh"}), ("zsh", "enrolled"))
        self.assertIsNone(alias.selected_shell("auto", self.home, {"SHELL": "/bin/fish"})[0])
        self.assertEqual(alias.selected_shell("none", self.home, {}), (None, "disabled"))
        self.assertEqual(alias.selected_shell("zsh", self.home, {"ZDOTDIR": str(self.home)}), ("zsh", "enrolled"))
        for location in (self.base, self.home / "nested"):
            self.assertIn("ZDOTDIR", alias.selected_shell("zsh", self.home, {"ZDOTDIR": str(location)})[1])

    def test_quoted_paths_arguments_status_and_cwd_survive_real_shell(self):
        installer = self.source / "install.sh"
        installer.write_text('#!/usr/bin/env python3\nimport json, os, sys\nprint(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}))\nsys.exit(7)\n')
        metadata, operation, _report = self.prepare()
        self.apply(operation)
        arguments = ["status", "space argument", "apostrophe ' $() ;", "--help"]
        shells = ["bash"] + (["zsh"] if shutil.which("zsh") else [])
        for shell in shells:
            with self.subTest(shell=shell):
                command = 'source "$1"; shift; cw "$@"'
                result = subprocess.run([shell, "-c", command, "fixture", str(self.rc), *arguments], cwd=self.base, capture_output=True)
                self.assertEqual(result.returncode, 7, result.stderr.decode())
                self.assertEqual(json.loads(result.stdout), {"args": ["--home", str(self.home), "--codex-home", str(self.codex), "--state-dir", str(self.state), *arguments], "cwd": str(self.base)})
        self.assertIn(str(installer), metadata["segment"].replace("'\"'\"'", "'"))

    def test_enrollment_repeat_preserves_bytes_and_later_mode(self):
        initial = b"# personal credentials\nexport PRIVATE_TOKEN='preserve'" + bytes([0xff])
        self.rc.write_bytes(initial)
        self.rc.chmod(0o640)
        metadata, operation, _report = self.prepare()
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(metadata))
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(operation))
        self.apply(operation)
        self.assertEqual(self.rc.read_bytes(), initial + metadata["segment"].encode())
        self.rc.chmod(0o604)
        self.assertIsNone(self.prepare("zsh", metadata)[1])
        self.rc.write_bytes(self.rc.read_bytes() + b"# independent later\n")
        self.apply(alias.removal(metadata, self.home, self.codex, self.state))
        self.assertEqual(self.rc.read_bytes(), initial + b"# independent later\n")
        self.assertEqual(stat.S_IMODE(self.rc.stat().st_mode), 0o604)

    def test_original_absent_and_empty_are_restored_distinctly(self):
        for originally_exists in (False, True):
            with self.subTest(exists=originally_exists):
                if originally_exists:
                    self.rc.write_bytes(b"")
                    self.rc.chmod(0o640)
                metadata, operation, _report = self.prepare()
                self.apply(operation)
                self.apply(alias.removal(metadata, self.home, self.codex, self.state))
                self.assertEqual(self.rc.exists(), originally_exists)
                if originally_exists:
                    self.assertEqual(self.rc.read_bytes(), b"")
                    self.assertEqual(stat.S_IMODE(self.rc.stat().st_mode), 0o640)

    def test_conventional_conflicts_markers_and_conditional_definitions_refuse(self):
        definitions = [b"cw() { :; }\n", b"function cw { :; }\n", b"alias cw='prior'\n",
                       b"alias other='one' cw='prior'\n", b"if true; then cw() { :; }; fi\n",
                       b"if true; then alias cw='prior'; fi\n", b"command alias cw='prior'\n",
                       b"alias 'cw'='prior'\n", b'alias "cw"="prior"\n', b"alias \\\n" + b"cw='prior'\n", b"functions[cw]='prior'\n", alias.START + b"\n", b"# codex-workflows-cw-start\n"]
        for data in definitions:
            with self.subTest(data=data):
                self.rc.write_bytes(data)
                with self.assertRaises(alias.CommandAliasError):
                    self.prepare()
                self.assertEqual(self.rc.read_bytes(), data)
        self.rc.write_bytes(b"# cw() { example only; }\n# alias cw=example\n")
        self.prepare()

    def test_symlinked_rc_and_parent_and_noncanonical_metadata_refuse(self):
        target = self.base / "foreign"
        target.write_bytes(b"foreign")
        self.rc.symlink_to(target)
        with self.assertRaises(alias.CommandAliasError):
            self.prepare()
        self.rc.unlink()
        metadata, _operation, _report = self.prepare()
        for path in (target, self.home / "nested" / ".bashrc", self.home / "../foreign"):
            with self.assertRaises(alias.CommandAliasError):
                alias.validate_metadata(dict(metadata, path=str(path)), self.home, self.codex, self.state)
        self.home.rmdir()
        self.home.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(alias.CommandAliasError):
            self.prepare()

    def test_changed_owned_block_and_new_definition_refuse_all_phases(self):
        metadata, operation, _report = self.prepare()
        self.apply(operation)
        for data in (self.rc.read_bytes().replace(b'"$@"', b'"$1"'), self.rc.read_bytes() + b"alias cw='foreign'\n"):
            self.rc.write_bytes(data)
            for action in (lambda: alias.verify(metadata, self.home, self.codex, self.state),
                           lambda: alias.reversal(operation, self.home, self.codex, self.state),
                           lambda: alias.removal(metadata, self.home, self.codex, self.state)):
                with self.assertRaises(alias.CommandAliasError):
                    action()

    def test_setup_recovery_and_resumption_preserve_concurrent_bytes(self):
        original = b"# original\n"
        self.rc.write_bytes(original)
        _metadata, operation, _report = self.prepare()
        self.assertIsNone(alias.reversal(operation, self.home, self.codex, self.state))
        self.apply(operation)
        self.rc.write_bytes(self.rc.read_bytes() + b"# later\n")
        reversal = alias.reversal(operation, self.home, self.codex, self.state)
        self.rc.write_bytes(self.rc.read_bytes() + b"# before resumed recovery\n")
        self.apply(alias.pending(reversal, self.home, self.codex, self.state))
        self.assertIsNone(alias.pending(reversal, self.home, self.codex, self.state))
        self.assertEqual(self.rc.read_bytes(), original + b"# later\n# before resumed recovery\n")

    def test_uninstall_recovery_restores_only_owned_block(self):
        original = b"# original\n"
        self.rc.write_bytes(original)
        metadata, operation, _report = self.prepare()
        self.apply(operation)
        removal = alias.removal(metadata, self.home, self.codex, self.state)
        self.apply(removal)
        self.rc.write_bytes(b"# changed unrelated bytes without newline")
        reversal = alias.reversal(removal, self.home, self.codex, self.state)
        self.apply(reversal)
        alias.verify(metadata, self.home, self.codex, self.state)
        self.assertIsNone(alias.pending(reversal, self.home, self.codex, self.state))
        self.apply(alias.removal(metadata, self.home, self.codex, self.state))
        self.assertEqual(self.rc.read_bytes(), b"# changed unrelated bytes without newline")

    def test_mode_change_prevents_deleting_created_empty_rc(self):
        metadata, operation, _report = self.prepare()
        self.apply(operation)
        removal = alias.removal(metadata, self.home, self.codex, self.state)
        self.rc.chmod(0o640)
        with self.assertRaises(alias.CommandAliasError):
            self.apply(removal)

    def test_concurrent_empty_file_creation_is_not_adopted_as_an_absent_origin(self):
        _metadata, operation, _report = self.prepare()
        self.rc.write_bytes(b"")
        with self.assertRaises(alias.CommandAliasError):
            self.apply(operation)
        self.assertEqual(self.rc.read_bytes(), b"")

    def test_runtime_guard_keeps_indirect_functions_aliases_and_double_source_quiet(self):
        _metadata, operation, _report = self.prepare()
        self.apply(operation)
        shells = ["bash"] + (["zsh"] if shutil.which("zsh") else [])
        for shell in shells:
            for definition in ("alias cw='printf prior'", "function cw { printf prior; }"):
                with self.subTest(shell=shell, definition=definition):
                    # Separate the declaration and invocation parse phases so
                    # aliases behave as they do when sourcing real startup files.
                    definition_path = self.base / "indirect definition.rc"
                    definition_path.write_text(definition + "\n")
                    command = 'source "$1"; source "$2"; eval cw'
                    if shell == "bash":
                        command = "shopt -s expand_aliases; " + command
                    result = subprocess.run([shell, "-c", command, "fixture", str(definition_path), str(self.rc)], capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(result.stdout, b"prior")
                    self.assertIn(b"cw already exists; keeping current command", result.stderr)
            result = subprocess.run([shell, "-c", 'source "$1"; source "$1"; env', "fixture", str(self.rc)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b"")
            self.assertNotIn(b"_CODEX_WORKFLOWS_CW_OWNER=", result.stdout)

    def test_enrolled_source_is_frozen_and_other_checkout_requires_uninstall(self):
        metadata, operation, _report = self.prepare()
        self.apply(operation)
        other = self.base / "another source"
        other.mkdir()
        (other / "install.sh").write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaisesRegex(alias.CommandAliasError, "enrolled checkout or uninstall"):
            alias.prepare(other, self.home, self.codex, self.state, "auto", metadata)


if __name__ == "__main__":
    unittest.main()

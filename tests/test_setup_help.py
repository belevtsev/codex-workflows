"""Help is useful before installation and does not enter the setup coordinator."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE / "scripts"))
import setup


class HelpTests(unittest.TestCase):
    def help_output(self, arguments):
        output = io.StringIO()
        with mock.patch.object(setup, "Launcher", side_effect=AssertionError("Help entered setup")):
            with contextlib.redirect_stdout(output):
                self.assertEqual(setup.main(arguments), 0)
        return output.getvalue()

    def test_global_help_and_topic_forms_never_enter_setup(self):
        for arguments in (["help"], ["--help"], ["-h"]):
            with self.subTest(arguments=arguments):
                output = self.help_output(arguments)
                for command in setup.ACTIONS:
                    self.assertIn(command, output)
                self.assertIn("--shell", output)
        for command in setup.ACTIONS:
            with self.subTest(command=command):
                topic = self.help_output(["help", command])
                flag = self.help_output([command, "--help"])
                self.assertEqual(topic, flag)
                self.assertIn("cw " + command, topic)
                self.assertIn(setup.ACTION_HELP[command], topic)

    def test_captured_root_options_before_help_are_supported(self):
        prefix = ["--home", "/missing home", "--codex-home", "/missing Codex",
                  "--state-dir", "/missing state"]
        self.assertEqual(self.help_output(prefix + ["help", "update"]),
                         self.help_output(["update", "--help"]))

    def test_help_from_dirty_unprepared_checkout_changes_no_files(self):
        with tempfile.TemporaryDirectory(prefix="offline help with spaces ") as directory:
            source = Path(directory) / "dirty source"
            (source / "scripts").mkdir(parents=True)
            for relative in ("install.sh", "scripts/setup.py"):
                target = source / relative
                target.write_bytes((SUITE / relative).read_bytes())
                target.chmod((SUITE / relative).stat().st_mode & 0o777)
            before = {path.relative_to(source): path.read_bytes()
                      for path in source.rglob("*") if path.is_file()}
            result = subprocess.run([str(source / "install.sh"), "help", "setup"],
                                    cwd=directory, capture_output=True, text=True,
                                    env=setup.child_environment())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--shell", result.stdout)
            self.assertFalse((source / ".venv").exists())
            self.assertEqual(before, {path.relative_to(source): path.read_bytes()
                                      for path in source.rglob("*") if path.is_file()})

    def test_invalid_help_topics_and_nonsetup_shell_flags_fail_before_setup(self):
        for arguments in (["help", "unknown"], ["status", "setup"], ["status", "--shell", "bash"]):
            with self.subTest(arguments=arguments):
                with mock.patch.object(setup, "Launcher", side_effect=AssertionError("Entered setup")):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as raised:
                            setup.main(arguments)
                        self.assertEqual(raised.exception.code, 2)

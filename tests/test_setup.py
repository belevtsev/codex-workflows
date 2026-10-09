"""Launcher fixtures use temporary homes, local repositories, and no downloads."""
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import venv
import zipfile


SUITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SUITE / "scripts"))
import setup


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = ("link", os.readlink(str(path)))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        else:
            result[relative] = ("dir", stat.S_IMODE(path.stat().st_mode))
    return result


def local_dependencies(environment):
    """Copy the test runtime's pinned wheels into a fixture venv, without pip/network."""
    result = subprocess.run([str(environment / "bin" / "python"), "-c",
                             "import sysconfig; print(sysconfig.get_path('purelib'))"],
                            capture_output=True, check=True, env=setup.child_environment())
    destination = Path(result.stdout.decode().strip())
    for name, version in setup.DEPENDENCIES.items():
        distribution = importlib.metadata.distribution(name)
        if distribution.version != version:
            raise RuntimeError("Launcher tests require the pinned runtime dependencies")
        roots = {Path(entry).parts[0] for entry in distribution.files
                 if Path(entry).parts and ".." not in Path(entry).parts}
        for root in roots:
            source = Path(distribution.locate_file(root))
            target = destination / root
            if source.is_dir():
                shutil.copytree(str(source), str(target), dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(source), str(target))


def metadata_only_wheel(directory, name, version, module):
    """Small local wheel proves pip destination behavior, not dependency functionality."""
    normalized = name.lower()
    metadata = "{}-{}.dist-info".format(normalized, version)
    files = {
        module + "/__init__.py": "__version__ = {!r}\n".format(version),
        metadata + "/METADATA": "Metadata-Version: 2.1\nName: {}\nVersion: {}\n".format(name, version),
        metadata + "/WHEEL": "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = metadata + "/RECORD"
    files[record] = "".join("{},,\n".format(path) for path in sorted(files)) + record + ",,\n"
    path = directory / "{}-{}-py3-none-any.whl".format(normalized, version)
    with zipfile.ZipFile(path, "w") as wheel:
        for name, contents in files.items():
            wheel.writestr(name, contents)
    return path


class SetupFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="launcher fixtures with spaces ")
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "source checkout"
        shutil.copytree(str(SUITE), str(self.repo),
                        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
        self.home = self.base / "fixture home"
        self.home.mkdir()
        self.codex = self.home / "custom Codex root"
        self.state = self.base / "private state root"
        environment = setup.child_environment()
        environment.pop("CODEX_HOME", None)
        environment.pop("XDG_STATE_HOME", None)
        environment.pop("TYPESAFE_API_KEY", None)
        environment.pop("CODEX_WORKFLOWS_FAULT", None)
        environment["HOME"] = str(self.home)
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        self.environment_patch = mock.patch.dict(os.environ, environment, clear=True)
        self.environment_patch.start()
        self.git("init", "-b", "main")
        self.git("config", "gc.auto", "0")
        self.git("config", "maintenance.auto", "false")
        self.git("config", "user.name", "Fixture User")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", ".")
        self.git("commit", "-m", "Fixture suite")

    def tearDown(self):
        self.environment_patch.stop()
        self.temporary.cleanup()

    def git(self, *arguments):
        result = subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                                 "-C", str(self.repo), *arguments], capture_output=True,
                                env=setup.child_environment())
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def launcher(self, action="setup", *arguments):
        args = setup.parser().parse_args([action, "--home", str(self.home),
                                          "--codex-home", str(self.codex),
                                          "--state-dir", str(self.state), *arguments])
        return setup.Launcher(args, source=self.repo)

    def make_environment(self, dependencies=True):
        environment = self.repo / ".venv"
        venv.EnvBuilder(with_pip=False).create(str(environment))
        if dependencies:
            local_dependencies(environment)
        return environment

    def test_fresh_wrapper_dry_run_leaves_all_fixture_bytes_and_modes_unchanged(self):
        before = snapshot(self.base)
        result = subprocess.run([str(self.repo / "install.sh"), "--dry-run",
                                 "--home", str(self.home), "--codex-home", str(self.codex),
                                 "--state-dir", str(self.state)], cwd=self.home,
                                capture_output=True, env=setup.child_environment())
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        report = json.loads(result.stdout)
        self.assertEqual(report["action"], "setup")
        self.assertEqual(report["validation"], "deferred")
        self.assertIsNone(report["status"])
        self.assertTrue(report["preparation_plan"])
        self.assertEqual(snapshot(self.base), before)

    def test_status_without_dependencies_is_actionable_and_does_not_prepare(self):
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "Status is deferred"):
            self.launcher("status").execute()
        self.assertEqual(snapshot(self.base), before)

    def test_prepared_dry_run_runs_full_bootstrap_preflight_without_writes(self):
        self.make_environment()
        before = snapshot(self.base)
        report = self.launcher("setup", "--dry-run").execute()
        self.assertEqual(report["validation"], "complete")
        self.assertTrue(report["result"]["dry_run"])
        self.assertEqual(report["result"]["command"], "setup")
        self.assertEqual(snapshot(self.base), before)

    def test_reuses_compatible_environment_and_sets_custom_roots(self):
        environment = self.make_environment()
        before_environment = snapshot(environment)
        actual_run = setup.run
        commands = []

        def record(arguments, **kwargs):
            commands.append([str(argument) for argument in arguments])
            return actual_run(arguments, **kwargs)

        with mock.patch.object(setup, "run", side_effect=record):
            first = self.launcher().execute()
            second = self.launcher().execute()
            status = self.launcher("status").execute()
        self.assertFalse(any("venv" in command or "pip" in command for command in commands))
        self.assertEqual(snapshot(environment), before_environment)
        self.assertTrue(first["status"]["installed"])
        self.assertEqual(len(first["status"]["registrations"]), 10)
        self.assertFalse(second["result"]["changed"])
        self.assertTrue(status["status"]["installed"])
        self.assertTrue((self.codex / "AGENTS.md").is_file())
        self.assertTrue((self.codex / "config.toml").is_file())
        self.assertTrue((self.state / "state.json").is_file())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(first["integration"]["connectors"], "verify_in_codex")
        self.assertEqual(first["next_step"], "Open a fresh Codex chat")

    def test_missing_environment_is_prepared_before_validation_and_activation(self):
        launcher = self.launcher()
        actual_run = setup.run
        commands = []

        def prepare_locally(arguments, **kwargs):
            command = [str(argument) for argument in arguments]
            commands.append(command)
            if command[1:3] == ["-m", "pip"]:
                local_dependencies(self.repo / ".venv")
                return subprocess.CompletedProcess(command, 0, b"", b"")
            return actual_run(arguments, **kwargs)

        with mock.patch.object(setup, "run", side_effect=prepare_locally):
            report = launcher.execute()
        self.assertTrue(report["status"]["installed"])
        preparation = next(index for index, command in enumerate(commands)
                           if command[1:3] == ["-m", "venv"])
        dependency_install = next(index for index, command in enumerate(commands)
                                  if command[1:3] == ["-m", "pip"])
        validation = next(index for index, command in enumerate(commands)
                          if str(self.repo / "scripts" / "validate_suite.py") in command)
        activation = next(index for index, command in enumerate(commands)
                          if str(self.repo / "scripts" / "bootstrap.py") in command and "setup" in command)
        self.assertLess(preparation, dependency_install)
        self.assertLess(dependency_install, validation)
        self.assertLess(validation, activation)

    def test_download_failure_preserves_installed_workflow_and_hides_diagnostics(self):
        self.make_environment()
        self.launcher().execute()
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        launcher = self.launcher()
        actual_run = setup.run
        credential = "fixture-secret-never-print"

        def failed_download(arguments, **kwargs):
            command = [str(argument) for argument in arguments]
            if command[1:3] == ["-m", "pip"]:
                return subprocess.CompletedProcess(command, 1, credential.encode(), credential.encode())
            return actual_run(arguments, **kwargs)

        with mock.patch.object(launcher, "probe", return_value={"exists": True, "ready": False}), \
                mock.patch.object(setup, "run", side_effect=failed_download):
            with self.assertRaisesRegex(setup.SetupError, "Pinned dependency installation failed") as raised:
                launcher.execute()
        self.assertNotIn(credential, str(raised.exception))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_pip_site_root_and_user_config_cannot_redirect_environment_install(self):
        environment = self.repo / ".venv"
        venv.EnvBuilder(with_pip=True).create(str(environment))
        outside = self.base / "unrelated prefix root"
        outside.mkdir()
        (outside / "keep.txt").write_text("Preserve unrelated contents")
        before_outside = snapshot(outside)
        (environment / "pip.conf").write_text("[install]\nroot = {}\nuser = true\n".format(outside))
        configured = setup.run([environment / "bin" / "python", "-m", "pip", "--isolated",
                                "config", "get", "install.root"])
        self.assertEqual(configured.returncode, 0, configured.stderr.decode(errors="replace"))
        self.assertEqual(configured.stdout.decode().strip(), str(outside))
        wheels = self.base / "local fixture wheels"
        wheels.mkdir()
        metadata_only_wheel(wheels, "PyYAML", "6.0.3", "yaml")
        metadata_only_wheel(wheels, "tomlkit", "0.13.3", "tomlkit")
        actual_run = setup.run
        installed = []

        def offline_install(arguments, **kwargs):
            command = [str(argument) for argument in arguments]
            if command[1:3] == ["-m", "pip"] and "install" in command:
                installed.append(command)
                command.extend(["--no-index", "--find-links", str(wheels)])
            return actual_run(command, **kwargs)

        launcher = self.launcher()
        with mock.patch.object(setup, "run", side_effect=offline_install):
            launcher.prepare()
        self.assertEqual(len(installed), 1)
        command = installed[0]
        self.assertEqual(command[command.index("--root") + 1], "/")
        self.assertIn("--no-user", command)
        self.assertEqual(command[command.index("--prefix") + 1], str(environment))
        self.assertTrue(launcher.probe()["ready"])
        self.assertEqual(snapshot(outside), before_outside)

    def test_unidentified_or_symlink_environment_is_refused_without_changes(self):
        environment = self.repo / ".venv"
        environment.mkdir()
        (environment / "keep.txt").write_text("Unrelated environment contents")
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "unidentified"):
            self.launcher().execute()
        self.assertEqual(snapshot(self.base), before)
        shutil.rmtree(str(environment))
        destination = self.base / "external directory"
        destination.mkdir()
        environment.symlink_to(destination)
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "Symlinked"):
            self.launcher().execute()
        self.assertEqual(snapshot(self.base), before)

    def test_symlinked_environment_bin_directory_is_refused(self):
        environment = self.make_environment()
        destination = self.base / "external executables"
        (environment / "bin").rename(destination)
        (environment / "bin").symlink_to(destination)
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "Symlinked"):
            self.launcher().execute()
        self.assertEqual(snapshot(self.base), before)

    def test_symlinked_environment_package_directory_is_refused(self):
        environment = self.make_environment()
        site_packages = next((environment / "lib").glob("python*/site-packages"))
        destination = self.base / "external packages"
        site_packages.rename(destination)
        site_packages.symlink_to(destination)
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "Symlinked environment directory"):
            self.launcher().execute()
        self.assertEqual(snapshot(self.base), before)

    def test_dirty_checkout_is_refused_before_environment_preparation(self):
        (self.repo / "README.md").write_text("Uncommitted fixture change")
        before = snapshot(self.base)
        with self.assertRaisesRegex(setup.SetupError, "dirty"):
            self.launcher().execute()
        self.assertEqual(snapshot(self.base), before)

    def test_prepared_lifecycle_uses_owned_release_when_current_source_is_malformed(self):
        self.make_environment()
        self.launcher().execute()
        (self.repo / "skills-manifest.json").write_bytes(b"malformed fixture manifest")
        (self.repo / "requirements-dev.txt").write_bytes(b"malformed current requirements")
        self.assertTrue(self.launcher("status").execute()["status"]["installed"])
        self.assertTrue(self.launcher("recover").execute()["status"]["installed"])
        self.assertFalse(self.launcher("uninstall").execute()["status"]["installed"])

    def test_environment_preparation_lock_serializes_launchers(self):
        launcher = self.launcher()
        competing = """
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / 'scripts'))
import setup
launcher = setup.Launcher(setup.parser().parse_args(['status']), source=Path(sys.argv[1]))
try:
    with launcher.lock():
        print('Unexpected lock acquisition')
except setup.SetupError as error:
    if 'Another launcher' in str(error):
        print('Another launcher')
        sys.exit(75)
    raise
"""
        with launcher.lock():
            result = subprocess.run([sys.executable, "-c", competing, str(self.repo)],
                                    capture_output=True, env=setup.child_environment(), timeout=10)
            self.assertEqual(result.returncode, 75, result.stderr.decode(errors="replace"))
            self.assertEqual(result.stdout, b"Another launcher\n")
        with launcher.lock():
            pass  # The competing process did not steal or retain the lock.

    def test_unsafe_lock_symlink_is_refused(self):
        target = self.base / "unrelated lock"
        target.write_bytes(b"keep")
        (self.repo / ".git" / "codex-workflows-setup.lock").symlink_to(target)
        with self.assertRaisesRegex(setup.SetupError, "Unsafe"):
            with self.launcher().lock():
                self.fail("Unsafe lock was acquired")
        self.assertEqual(target.read_bytes(), b"keep")

    def test_routes_actions_and_flags_as_literal_argv(self):
        strange = str(self.base / 'a directory $() `literal` "quotes"')
        for action in setup.ACTIONS:
            launcher = self.launcher(action, "--migrate-from", strange,
                                     "--typesafe-legacy", strange, "--no-checkout")
            invocation = launcher.forwarded(action, apply=True)
            self.assertEqual(invocation[2], action)
            self.assertIn("--source", invocation)
            self.assertIn(self.repo, invocation)
            self.assertEqual("--apply" in invocation, action != "status")
            self.assertEqual(strange in invocation, action != "status")
            readback = launcher.forwarded("status")
            self.assertNotIn("--apply", readback)
            self.assertNotIn("--migrate-from", readback)

    def test_prepared_command_routing_applies_only_mutating_actions(self):
        for action in setup.ACTIONS:
            launcher = self.launcher(action)
            with mock.patch.object(launcher, "prerequisites"), \
                    mock.patch.object(launcher, "probe", return_value={"exists": True, "ready": True}), \
                    mock.patch.object(launcher, "prepare"), \
                    mock.patch.object(launcher, "lock", return_value=contextlib.nullcontext()), \
                    mock.patch.object(launcher, "validate"), \
                    mock.patch.object(launcher, "bootstrap", return_value={"installed": True}) as route:
                launcher.execute()
            calls = [mock.call(action, apply=action != "status")]
            if action != "status":
                calls.append(mock.call("status"))
            self.assertEqual(route.call_args_list, calls)

    def test_key_reports_only_nonempty_presence_without_value(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "fixture-secret-never-print"}):
            report = self.launcher("setup", "--dry-run").execute()
        self.assertTrue(report["integration"]["jev_credential_present"])
        self.assertNotIn("fixture-secret-never-print", json.dumps(report))
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            report = self.launcher("setup", "--dry-run").execute()
        self.assertFalse(report["integration"]["jev_credential_present"])


if __name__ == "__main__":
    unittest.main()

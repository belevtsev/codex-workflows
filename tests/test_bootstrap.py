"""Portable installer integration fixtures: every home and Git remote is temporary."""
import fcntl
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


SUITE = Path(__file__).resolve().parents[1]
SCRIPT = SUITE / "scripts" / "bootstrap.py"
ORIGIN = "https://github.com/belevtsev/codex-workflows.git"
sys.path.insert(0, str(SUITE / "scripts"))
import bootstrap


def snapshot(root):
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            result[relative] = ("link", os.readlink(str(path)))
        elif path.is_file():
            result[relative] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        else:
            result[relative] = ("dir", stat.S_IMODE(path.stat().st_mode))
    return result


class BootstrapFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workflow fixtures with spaces ")
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "source checkout"
        # Fixtures contain committed suite content, never the developer's local
        # environment (whose interpreter links may not exist inside Docker).
        shutil.copytree(str(SUITE), str(self.repo), ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"))
        self.home = self.base / "fake home"
        self.home.mkdir()
        self.state = self.base / "private state"
        self.codex = self.home / ".codex"
        self.agents = self.codex / "AGENTS.md"
        self.skills = self.home / ".agents" / "skills"
        self.environment = dict(os.environ)
        self.environment.pop("CODEX_HOME", None)
        self.environment.pop("XDG_STATE_HOME", None)
        self.environment.pop("CODEX_WORKFLOWS_FAULT", None)
        self.environment["GIT_CONFIG_NOSYSTEM"] = "1"
        self.environment["GIT_CONFIG_GLOBAL"] = os.devnull
        self.environment["GIT_OPTIONAL_LOCKS"] = "0"
        self.run_git("init", "-b", "main")
        self.run_git("config", "gc.auto", "0")
        self.run_git("config", "maintenance.auto", "false")
        self.run_git("config", "user.name", "Fixture User")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "Initial fixture suite")
        self.first = self.head()
        self.manifest = json.loads((self.repo / "skills-manifest.json").read_bytes())
        self.remote = self.base / "local origin.git"
        self.run_git("clone", "--bare", str(self.repo), str(self.remote))
        self.run_git("remote", "add", "origin", ORIGIN)
        # Fetch uses only the fixture repository. No test contacts GitHub.
        self.run_git("config", "url.{}.insteadOf".format(self.remote), ORIGIN)

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, *args, cwd=None):
        result = subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-C", str(cwd or self.repo), *args], capture_output=True, env=self.environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def head(self):
        return self.run_git("rev-parse", "HEAD")

    def cli(self, command, *args, okay=True, fault=None):
        environment = dict(self.environment)
        if fault:
            environment["CODEX_WORKFLOWS_FAULT"] = fault
        invocation = [sys.executable, str(SCRIPT), command, "--source", str(self.repo), "--home", str(self.home), "--state-dir", str(self.state), *args]
        result = subprocess.run(invocation, capture_output=True, env=environment)
        if okay:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
        return result.stderr.decode(errors="replace")

    def install(self, *args):
        return self.cli("install", "--apply", *args)

    def current(self):
        return os.readlink(str(self.state / "current"))

    def template(self):
        return (self.repo / self.manifest["global_instructions"]).read_bytes()

    def new_release(self, text="New fixture instructions"):
        path = self.repo / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + ("\n" + text + "\n").encode())
        self.run_git("add", str(path))
        self.run_git("commit", "-m", text)
        sha = self.head()
        self.run_git("push", str(self.remote), "main")
        return sha

    def reset_source_to_first(self):
        # This is only an isolated fixture checkout, never the installation source.
        self.run_git("reset", "--hard", self.first)

    def make_migration(self):
        old = self.base / "prior suite"
        shutil.copytree(str(self.repo), str(old), ignore=shutil.ignore_patterns(".git"))
        self.skills.mkdir(parents=True)
        for name, relative in self.manifest["registrations"].items():
            if name != "typesafe-ai":
                (self.skills / name).symlink_to(str(old / relative))
        legacy = self.home / ".codex" / "skills" / "typesafe-ai"
        legacy.parent.mkdir(parents=True)
        shutil.copytree(str(self.repo / self.manifest["registrations"]["typesafe-ai"]), str(legacy))
        return old, legacy

    def installer(self, command):
        args = bootstrap.parser().parse_args([command, "--apply", "--source", str(self.repo), "--home", str(self.home), "--state-dir", str(self.state)])
        return bootstrap.Installer(args)

    def test_status_and_install_dry_run_leave_home_state_and_git_unchanged(self):
        before_home, before_git = snapshot(self.home), snapshot(self.repo / ".git")
        self.assertFalse(self.cli("status")["installed"])
        report = self.cli("install")
        self.assertTrue(report["dry_run"])
        self.assertEqual(len(report["registrations"]), 10)
        self.assertFalse(self.state.exists())
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)

    def test_fresh_install_full_ten_status_and_uninstall(self):
        self.install()
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for name, relative in self.manifest["registrations"].items():
            self.assertEqual(os.readlink(str(self.skills / name)), str(self.state / "current" / relative))
            root = self.skills / name
            self.assertTrue(root.is_dir())
            self.assertTrue(any(root.rglob("SKILL.md")), "{} must expose a skill entrypoint".format(name))
        report = self.cli("status")
        self.assertEqual(report["release"], self.first)
        self.assertEqual(len(report["registrations"]), 10)
        self.cli("uninstall", "--apply")
        self.assertFalse(self.agents.exists())
        self.assertFalse((self.state / "current").is_symlink())
        self.assertFalse((self.state / "state.json").exists())
        self.assertFalse(any(path.is_symlink() for path in self.skills.iterdir()))
        self.assertFalse(self.cli("status")["installed"])

    def test_exact_tracked_snapshot_excludes_git_and_is_commit_pinned(self):
        self.install()
        release = self.state / "releases" / self.first
        self.assertFalse((release / ".git").exists())
        self.assertEqual((release / self.manifest["global_instructions"]).read_bytes(), self.template())
        self.new_release()
        self.assertEqual((release / self.manifest["global_instructions"]).read_bytes(), self.run_git("show", "{}:{}".format(self.first, self.manifest["global_instructions"])).encode() + b"\n")
        self.assertEqual(self.cli("status")["release"], self.first)

    def test_dirty_and_untracked_source_refused_without_home_changes(self):
        path = self.repo / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + b"dirty")
        self.assertIn("dirty", self.cli("install", "--apply", okay=False))
        self.assertFalse(self.state.exists())
        self.run_git("checkout", "--", str(path))
        (self.repo / "unexpected.tmp").write_text("untracked")
        self.assertIn("untracked", self.cli("install", okay=False))
        self.assertFalse(self.state.exists())

    def test_occupied_and_cross_root_registration_refused(self):
        name = next(iter(self.manifest["registrations"]))
        self.skills.mkdir(parents=True)
        (self.skills / name).mkdir()
        self.assertIn("occupied", self.cli("install", "--apply", okay=False))
        (self.skills / name).rmdir()
        duplicate = self.codex / "skills" / name
        duplicate.parent.mkdir(parents=True)
        duplicate.symlink_to(self.repo / self.manifest["registrations"][name])
        self.assertIn("Duplicate", self.cli("install", "--apply", okay=False))
        self.assertFalse(self.state.exists())

    def test_symlinked_home_components_refused(self):
        destination = self.base / "elsewhere"
        destination.mkdir()
        (self.home / ".agents").symlink_to(destination)
        self.assertIn("Symlinked", self.cli("install", "--apply", okay=False))
        self.assertEqual(list(destination.iterdir()), [])

    def test_install_preserves_unrelated_global_bytes_and_model_config(self):
        self.codex.mkdir()
        initial = b"Personal instructions without final newline"
        self.agents.write_bytes(initial)
        self.agents.chmod(0o640)
        config = self.codex / "config.toml"
        config.write_bytes(b'model = "fixture-user-model"\n')
        self.install()
        self.assertTrue(self.agents.read_bytes().startswith(initial))
        later = b"\nLater independent instructions\n"
        self.agents.write_bytes(self.agents.read_bytes() + later)
        self.cli("uninstall", "--apply")
        self.assertEqual(self.agents.read_bytes(), initial + later)
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o640)
        self.assertEqual(config.read_bytes(), b'model = "fixture-user-model"\n')

    def test_marker_duplicates_or_malformed_pair_refused(self):
        self.codex.mkdir()
        for data in (b"<!-- codex-workflows-start -->\n", b"<!-- codex-workflows-end -->\n", b"codex-workflows-start invalid"):
            self.agents.write_bytes(data)
            self.assertIn("markers", self.cli("install", "--apply", okay=False))
            self.assertEqual(self.agents.read_bytes(), data)

    def test_uninstall_preserves_later_file_mode(self):
        self.codex.mkdir()
        self.agents.write_bytes(b"Personal instructions\n")
        self.install()
        self.agents.chmod(0o604)
        self.cli("uninstall", "--apply")
        self.assertEqual(self.agents.read_bytes(), b"Personal instructions\n")
        self.assertEqual(stat.S_IMODE(self.agents.stat().st_mode), 0o604)

    def test_migration_preserves_raw_nine_links_legacy_and_prefix_suffix(self):
        old, legacy = self.make_migration()
        before_links = {name: os.readlink(str(self.skills / name)) for name in self.manifest["registrations"] if name != "typesafe-ai"}
        before_legacy = snapshot(legacy)
        prefix = self.template()
        suffix = b"\n# jbcontext suffix\nKeep this exact suffix.\n"
        self.agents.write_bytes(prefix + suffix)
        self.agents.chmod(0o640)
        self.install("--migrate-from", str(old), "--typesafe-legacy")
        self.assertFalse(legacy.exists())
        self.assertEqual(snapshot(self.state / "backups" / "typesafe-ai"), before_legacy)
        self.assertTrue(self.agents.read_bytes().endswith(suffix))
        later = b"Further independent text\n"
        self.agents.write_bytes(self.agents.read_bytes() + later)
        self.cli("uninstall", "--apply")
        self.assertEqual(self.agents.read_bytes(), prefix + suffix + later)
        self.assertEqual(snapshot(legacy), before_legacy)
        for name, target in before_links.items():
            self.assertEqual(os.readlink(str(self.skills / name)), target)
        self.assertFalse((self.skills / "typesafe-ai").is_symlink())

    def test_migration_wrong_raw_target_refuses_without_changes(self):
        old, legacy = self.make_migration()
        name = next(name for name in self.manifest["registrations"] if name != "typesafe-ai")
        (self.skills / name).unlink()
        (self.skills / name).symlink_to(str(old / self.manifest["registrations"][name]) + "/")
        before = snapshot(self.home)
        self.assertIn("occupied", self.cli("install", "--migrate-from", str(old), "--typesafe-legacy", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(self.state.exists())

    def test_legacy_alias_equivalence_preserves_all_other_raw_target_bytes(self):
        aliases = [("/var", "/private/var"), ("/tmp", "/private/tmp")]
        with mock.patch.object(bootstrap, "macos_aliases", return_value=aliases):
            self.assertTrue(bootstrap.equivalent_legacy_target("/var/suite/skills/example", "/private/var/suite/skills/example"))
            self.assertTrue(bootstrap.equivalent_legacy_target("/tmp/suite/skills/example", "/private/tmp/suite/skills/example"))
            for target in ("/var/suite/skills/example/", "/var/suite/skills/../skills/example", "/var//suite/skills/example", "var/suite/skills/example", "/variety/suite/skills/example", "/var/suite/user-alias/example"):
                with self.subTest(target=target):
                    self.assertFalse(bootstrap.equivalent_legacy_target(target, "/private/var/suite/skills/example"))
        with mock.patch.object(bootstrap, "macos_aliases", return_value=[]):
            self.assertFalse(bootstrap.equivalent_legacy_target("/var/suite/skills/example", "/private/var/suite/skills/example"))

    def test_os_alias_detection_requires_direct_maintained_links(self):
        links = {"/var": "private/var", "/tmp": "/private/tmp"}
        with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: str(path) in links), mock.patch.object(bootstrap.os, "readlink", side_effect=lambda path: links[path]):
            self.assertEqual(bootstrap.macos_aliases(), [("/var", "/private/var"), ("/tmp", "/private/tmp")])
            links["/var"] = "intermediary-var-link"
            links["/tmp"] = "../private/tmp"
            self.assertEqual(bootstrap.macos_aliases(), [])

    def test_native_macos_migration_restores_original_os_alias_targets(self):
        alias_pair = next(((alias, destination) for alias, destination in bootstrap.macos_aliases() if str(self.base).startswith(destination + "/")), None)
        if alias_pair is None:
            self.skipTest("Native macOS /var or /tmp alias is unavailable; lexical guard is tested separately")
        old, legacy = self.make_migration()
        alias, destination = alias_pair
        originals = {}
        for name in self.manifest["registrations"]:
            if name != "typesafe-ai":
                link = self.skills / name
                canonical = os.readlink(str(link))
                raw = alias + canonical[len(destination):]
                link.unlink()
                link.symlink_to(raw)
                originals[name] = raw
        self.agents.write_bytes(self.template() + b"\nKeep the native Mac suffix\n")
        self.install("--migrate-from", str(old), "--typesafe-legacy")
        self.cli("uninstall", "--apply")
        for name, raw in originals.items():
            self.assertEqual(os.readlink(str(self.skills / name)), raw)
        self.assertTrue(legacy.is_dir())

    def test_legacy_unexpected_file_refuses_before_migration(self):
        old, legacy = self.make_migration()
        (legacy / "unexpected.txt").write_text("keep")
        before = snapshot(self.home)
        self.assertIn("exactly", self.cli("install", "--apply", "--migrate-from", str(old), "--typesafe-legacy", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(self.state.exists())

    def test_migration_refuses_modified_legacy_global_prefix(self):
        old, legacy = self.make_migration()
        self.agents.write_bytes(b"User changed the legacy conventions\n" + self.template())
        before = snapshot(self.home)
        self.assertIn("prefix was modified", self.cli("install", "--apply", "--migrate-from", str(old), "--typesafe-legacy", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(self.state.exists())

    def test_migration_replaces_legacy_template_with_new_template_and_restores_original(self):
        old, legacy = self.make_migration()
        original = self.template()
        suffix = b"\nKeep the jbcontext suffix\n"
        self.agents.write_bytes(original + suffix)
        self.new_release("Portable conventions added")
        self.install("--migrate-from", str(old), "--typesafe-legacy")
        self.assertIn(b"Portable conventions added", self.agents.read_bytes())
        self.assertTrue(self.agents.read_bytes().endswith(suffix))
        self.cli("uninstall", "--apply")
        self.assertEqual(self.agents.read_bytes(), original + suffix)

    def test_owned_global_edit_refuses_update_rollback_and_uninstall(self):
        self.install()
        self.new_release()
        self.agents.write_bytes(self.agents.read_bytes().replace(b"<!-- codex-workflows-start -->", b"<!-- codex-workflows-start -->\nUser edit inside"))
        before = snapshot(self.home)
        for command in ("update", "rollback", "uninstall"):
            self.assertIn("modified", self.cli(command, "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))

    def test_update_dry_run_no_fetch_lock_state_or_git_writes(self):
        self.install()
        second = self.new_release()
        before_home, before_state, before_git = snapshot(self.home), snapshot(self.state), snapshot(self.repo / ".git")
        report = self.cli("update")
        self.assertEqual(report["local_head"], second)
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)
        self.assertEqual(snapshot(self.repo / ".git"), before_git)

    def test_update_fetches_validates_fast_forwards_and_rollback_preserves_edits(self):
        self.install()
        second = self.new_release()
        self.reset_source_to_first()
        before = b"Before managed instructions\n"
        after = b"After managed instructions\n"
        self.agents.write_bytes(before + self.agents.read_bytes() + after)
        self.cli("update", "--apply")
        self.assertEqual(self.head(), second)
        self.assertEqual(self.cli("status")["release"], second)
        self.assertIn(b"New fixture instructions", self.agents.read_bytes())
        self.cli("rollback", "--apply")
        self.assertEqual(self.cli("status")["release"], self.first)
        self.assertTrue(self.agents.read_bytes().startswith(before))
        self.assertTrue(self.agents.read_bytes().endswith(after))
        self.assertNotIn(b"New fixture instructions", self.agents.read_bytes())
        self.assertEqual(self.head(), second)

    def test_no_checkout_update_keeps_fixture_source_head(self):
        self.install()
        second = self.new_release()
        self.reset_source_to_first()
        self.cli("update", "--apply", "--no-checkout")
        self.assertEqual(self.head(), self.first)
        self.assertEqual(self.cli("status")["release"], second)

    def test_update_origin_dirty_divergence_and_invalid_release_refused(self):
        self.install()
        self.run_git("config", "remote.origin.url", "https://github.com/another/project.git")
        self.assertIn("belevtsev", self.cli("update", "--apply", okay=False))
        self.run_git("config", "remote.origin.url", ORIGIN)
        second = self.new_release()
        self.reset_source_to_first()
        # A local sibling commit diverges from the remote branch.
        path = self.repo / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + b"\nSibling local instructions\n")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "Sibling local commit")
        sibling = self.head()
        self.assertIn("diverged", self.cli("update", "--apply", okay=False))
        self.assertEqual(self.head(), sibling)
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))
        self.run_git("reset", "--hard", second)
        (self.repo / self.manifest["global_instructions"]).unlink()
        self.run_git("add", ".")
        self.run_git("commit", "-m", "Invalid remote suite")
        self.run_git("push", str(self.remote), "main")
        invalid = self.head()
        self.reset_source_to_first()
        self.assertIn("validation", self.cli("update", "--apply", okay=False))
        self.assertEqual(self.head(), self.first)
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))
        self.assertFalse((self.state / "releases" / invalid).exists())

    def test_release_corruption_and_missing_state_fail_without_overwrite(self):
        self.install()
        release = self.state / "releases" / self.first
        path = release / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + b"corrupt")
        before = snapshot(self.home)
        self.assertIn("modified immutable", self.cli("status", okay=False))
        self.assertIn("modified immutable", self.cli("uninstall", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)
        (self.state / "state.json").unlink()
        self.assertIn("without ownership", self.cli("status", okay=False))
        self.assertIn("already exists", self.cli("install", "--apply", okay=False))

    def test_missing_adoption_backup_refuses_uninstall(self):
        old, legacy = self.make_migration()
        self.install("--migrate-from", str(old), "--typesafe-legacy")
        shutil.rmtree(str(self.state / "backups" / "typesafe-ai"))
        before = snapshot(self.home)
        self.assertIn("backup", self.cli("uninstall", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)

    def test_concurrent_mutation_lock_refuses_without_home_changes(self):
        self.install()
        self.new_release()
        before = snapshot(self.home)
        with (self.state / "mutation.lock").open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("holds the lock", self.cli("update", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)

    def test_install_faults_are_recoverable_before_and_after_state_commit(self):
        labels = ["after-journal", "after-pointer", "after-registration:" + next(iter(self.manifest["registrations"])), "after-global", "after-state"]
        for label in labels:
            with self.subTest(label=label):
                self.assertIn("Injected", self.cli("install", "--apply", okay=False, fault=label))
                self.assertTrue((self.state / "journal.json").exists())
                self.assertIn("recover", self.cli("status", okay=False))
                before = snapshot(self.state)
                self.assertTrue(self.cli("recover")["dry_run"])
                self.assertEqual(snapshot(self.state), before)
                self.cli("recover", "--apply")
                self.assertFalse(self.cli("status")["installed"])
                self.assertFalse(self.agents.exists())
                self.assertFalse((self.state / "current").is_symlink())

    def test_update_fault_recovery_restores_prior_release_and_preserves_later_edits(self):
        self.install()
        second = self.new_release()
        for label in ("after-pointer", "after-global", "after-state"):
            with self.subTest(label=label):
                self.assertIn("Injected", self.cli("update", "--apply", okay=False, fault=label))
                unrelated = ("Later user edit after {}\n".format(label)).encode()
                self.agents.write_bytes(self.agents.read_bytes() + unrelated)
                self.cli("recover", "--apply")
                self.assertEqual(self.cli("status")["release"], self.first)
                self.assertTrue(self.agents.read_bytes().endswith(unrelated))
                self.assertNotIn(b"New fixture instructions", self.agents.read_bytes())
        self.assertEqual(self.head(), second)

    def test_recovery_refuses_changed_pointer_without_partial_reversal(self):
        self.install()
        self.new_release()
        self.cli("update", "--apply", okay=False, fault="after-global")
        pointer = self.state / "current"
        pointer.unlink()
        pointer.symlink_to(self.base / "unrelated")
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("Ownership changed", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_recovery_refuses_edited_owned_block_without_overwrite(self):
        self.install()
        self.new_release()
        self.cli("update", "--apply", okay=False, fault="after-global")
        self.agents.write_bytes(self.agents.read_bytes().replace(b"New fixture instructions", b"User changed owned instructions"))
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("modified", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)

    def test_migration_fault_restores_prefix_raw_links_and_legacy_directory(self):
        old, legacy = self.make_migration()
        self.agents.write_bytes(self.template())
        before = snapshot(self.home)
        for label in ("after-legacy", "after-global", "after-state"):
            with self.subTest(label=label):
                self.cli("install", "--apply", "--migrate-from", str(old), "--typesafe-legacy", okay=False, fault=label)
                self.cli("recover", "--apply")
                self.assertEqual(snapshot(self.home), before)

    def test_uninstall_fault_recovery_restores_installation(self):
        self.install()
        before_home = snapshot(self.home)
        self.cli("uninstall", "--apply", okay=False, fault="after-state")
        self.cli("recover", "--apply")
        self.assertEqual(self.cli("status")["release"], self.first)
        self.assertEqual(snapshot(self.home), before_home)

    def test_custom_codex_home_and_default_xdg_state(self):
        alternative = self.home / "custom codex"
        xdg = self.base / "custom state"
        environment = dict(self.environment, CODEX_HOME=str(alternative), XDG_STATE_HOME=str(xdg))
        command = [sys.executable, str(SCRIPT), "install", "--apply", "--source", str(self.repo), "--home", str(self.home)]
        result = subprocess.run(command, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue((alternative / "AGENTS.md").is_file())
        self.assertTrue((xdg / "codex-workflows" / "state.json").is_file())
        self.assertFalse(self.codex.exists())

    def test_publication_crash_repairs_only_unreferenced_exact_export(self):
        self.cli("install", "--apply", okay=False, fault="after-release-publication")
        self.assertFalse((self.state / "journal.json").exists())
        self.assertFalse(self.cli("recover", "--apply")["pending"])
        self.install()
        self.assertEqual(self.cli("status")["release"], self.first)

    def test_publication_crash_modified_export_refused_without_overwrite(self):
        self.cli("install", "--apply", okay=False, fault="after-release-publication")
        path = self.state / "releases" / self.first / self.manifest["global_instructions"]
        path.write_bytes(path.read_bytes() + b"unexpected modification")
        before = snapshot(self.home)
        self.assertIn("differs", self.cli("install", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse((self.state / "current").is_symlink())

    def test_global_prepare_refuses_raced_unrelated_bytes(self):
        self.install()
        installer = self.installer("update")
        before = installer.read_agents()
        self.agents.write_bytes(before + b"Concurrent user instructions\n")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "changed while preparing"):
            installer.global_operation(before, before, None, before, "global")
        self.assertTrue(self.agents.read_bytes().endswith(b"Concurrent user instructions\n"))

    def test_update_pointer_replacement_during_staging_is_not_adopted(self):
        self.install()
        self.new_release()
        installer = self.installer("update")
        original = installer.stage

        def replacement(sha):
            result = original(sha)
            (self.state / "current").unlink()
            (self.state / "current").symlink_to(self.base / "user-owned pointer")
            return result

        with mock.patch.dict(os.environ, self.environment, clear=True), mock.patch.object(installer, "stage", side_effect=replacement):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "pointer"):
                installer.update()
        self.assertEqual(self.current(), str(self.base / "user-owned pointer"))
        self.assertFalse((self.state / "journal.json").exists())

    def test_uninstall_registration_replacement_before_journal_is_not_deleted(self):
        self.install()
        installer = self.installer("uninstall")
        original = installer.global_operation
        name = next(iter(self.manifest["registrations"]))
        registration = self.skills / name

        def replacement(*args, **kwargs):
            registration.unlink()
            registration.write_bytes(b"A user-owned replacement")
            return original(*args, **kwargs)

        with mock.patch.object(installer, "global_operation", side_effect=replacement):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "changed during mutation"):
                installer.uninstall()
        self.assertEqual(registration.read_bytes(), b"A user-owned replacement")
        self.assertEqual(self.current(), str(self.state / "releases" / self.first))

    def test_recovery_itself_is_resumable_with_two_later_global_edits(self):
        self.cli("install", "--apply", okay=False, fault="after-global")
        first = b"First unrelated edit\n"
        second = b"Second unrelated edit\n"
        self.agents.write_bytes(self.agents.read_bytes() + first)
        self.cli("recover", "--apply", okay=False, fault="after-recover-global")
        self.agents.write_bytes(self.agents.read_bytes() + second)
        self.cli("recover", "--apply")
        self.assertEqual(self.agents.read_bytes(), first + second)
        self.assertFalse(self.cli("status")["installed"])

    def test_update_recovery_retry_preserves_edits_after_block_restoration(self):
        self.install()
        self.new_release()
        self.cli("update", "--apply", okay=False, fault="after-global")
        first = b"First unrelated edit\n"
        second = b"Second unrelated edit\n"
        self.agents.write_bytes(self.agents.read_bytes() + first)
        self.cli("recover", "--apply", okay=False, fault="after-recover-global")
        self.agents.write_bytes(self.agents.read_bytes() + second)
        self.cli("recover", "--apply")
        self.assertTrue(self.agents.read_bytes().endswith(first + second))
        self.assertEqual(self.cli("status")["release"], self.first)

    def test_uninstall_fault_and_recovery_retry_preserve_later_user_bytes(self):
        for label in ("after-global", "after-state"):
            with self.subTest(label=label):
                if not (self.state / "state.json").exists():
                    self.install()
                self.cli("uninstall", "--apply", okay=False, fault=label)
                first = ("First edit after {}\n".format(label)).encode()
                second = b"Second edit during recovery\n"
                self.agents.write_bytes((self.agents.read_bytes() if self.agents.exists() else b"") + first)
                self.cli("recover", "--apply", okay=False, fault="after-recover-global")
                self.agents.write_bytes(self.agents.read_bytes() + second)
                self.cli("recover", "--apply")
                self.assertEqual(self.cli("status")["release"], self.first)
                self.assertTrue(self.agents.read_bytes().endswith(first + second))

    def test_migrated_uninstall_recovery_refuses_non_line_legacy_prefix(self):
        old, legacy = self.make_migration()
        self.agents.write_bytes(self.template() + b"\nOriginal jbcontext suffix\n")
        self.install("--migrate-from", str(old), "--typesafe-legacy")
        self.cli("uninstall", "--apply", okay=False, fault="after-global")
        self.agents.write_bytes(b"Unrelated prefix" + self.agents.read_bytes())
        before_home, before_state = snapshot(self.home), snapshot(self.state)
        self.assertIn("valid line", self.cli("recover", "--apply", okay=False))
        self.assertEqual(snapshot(self.home), before_home)
        self.assertEqual(snapshot(self.state), before_state)


if __name__ == "__main__":
    unittest.main()

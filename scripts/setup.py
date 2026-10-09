#!/usr/bin/env python3
"""Prepare the local Python environment and configure an existing Codex app."""
import os

# Set this before importing any local modules or spawning Python children.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import contextlib
import fcntl
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys


SOURCE = Path(__file__).absolute().parents[1]
DEPENDENCIES = {"PyYAML": "6.0.3", "tomlkit": "0.13.3"}
ACTIONS = ("setup", "status", "update", "rollback", "recover", "uninstall")
ACTION_HELP = {
    "setup": "Prepare pinned dependencies, validate local HEAD, and configure Codex and cw.",
    "status": "Read back owned registrations, model defaults, cw, and local credential presence.",
    "update": "Fetch origin/main, validate the exact commit, and activate a fast-forward update.",
    "rollback": "Activate the previous validated release and its model defaults.",
    "recover": "Recover an interrupted owned installation change without replacing unrelated edits.",
    "uninstall": "Restore adopted skills and original model settings, and remove owned instructions and cw.",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
ENVIRONMENT_PROBE = r'''
import importlib.metadata
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
valid = (Path(sys.prefix).resolve() == root and sys.prefix != sys.base_prefix
         and sys.version_info >= (3, 9))
ready = valid
for name, version, module_name in (("PyYAML", "6.0.3", "yaml"),
                                    ("tomlkit", "0.13.3", "tomlkit")):
    try:
        distribution = importlib.metadata.distribution(name)
        if distribution.version != version or not Path(distribution.locate_file("")).resolve().is_relative_to(root):
            ready = False
            continue
        module = __import__(module_name)
        if not Path(module.__file__).resolve().is_relative_to(root):
            ready = False
    except (ImportError, importlib.metadata.PackageNotFoundError, OSError, ValueError, TypeError):
        ready = False
print(json.dumps({"valid": valid, "ready": ready}))
'''


class SetupError(Exception):
    """A prerequisite failure or a safe refusal; no credential contents included."""


def child_environment():
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    # The checkout environment must not borrow dependencies from another Python.
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment


def run(arguments, **kwargs):
    try:
        return subprocess.run([str(argument) for argument in arguments],
                              stdin=subprocess.DEVNULL, capture_output=True,
                              env=child_environment(), **kwargs)
    except OSError as exc:
        raise SetupError("Cannot run required command: {}".format(arguments[0])) from exc


def normalize_path(path):
    value = os.path.abspath(str(path))
    # macOS has these standard system aliases. Do not allow arbitrary links.
    for alias in ("/tmp", "/var"):
        destination = "/private" + alias
        if Path(alias).is_symlink() and os.readlink(alias) in (destination, "private" + alias):
            if value == alias or value.startswith(alias + "/"):
                value = destination + value[len(alias):]
    return Path(value)


def real_directory(path, required=False):
    path = normalize_path(path)
    for component in reversed([path] + list(path.parents)):
        if component.is_symlink():
            raise SetupError("Symlinked directory is unsafe: {}".format(component))
        if component.exists() and not component.is_dir():
            raise SetupError("Expected a real directory: {}".format(component))
    if required and not path.is_dir():
        raise SetupError("Required directory is missing: {}".format(path))
    return path


class Launcher:
    def __init__(self, args, source=SOURCE):
        self.args = args
        self.source = real_directory(source, required=True)
        self.environment = self.source / ".venv"
        self.python = self.environment / "bin" / "python"

    def git(self, *arguments):
        result = run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                      "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                      "-C", self.source, *arguments])
        if result.returncode:
            # Git diagnostics may contain remote URLs with embedded credentials.
            raise SetupError("Git prerequisite check failed; use a clean committed Git checkout")
        return result.stdout.decode(errors="replace").strip()

    def prerequisites(self):
        if sys.platform not in ("darwin", "linux"):
            raise SetupError("This launcher supports macOS and Linux")
        if sys.version_info < (3, 9):
            raise SetupError("Python 3.9+ is required")
        if shutil.which("git") is None:
            raise SetupError("Git is required; install Git and rerun ./install.sh")
        try:
            import venv  # noqa: F401 - verify the stdlib prerequisite without writes
        except ImportError as exc:
            raise SetupError("Python's venv module is required; install Python venv support") from exc
        top = normalize_path(self.git("rev-parse", "--show-toplevel"))
        if top != self.source:
            raise SetupError("The launcher must run from its own Git checkout")
        real_directory(self.environment)
        if self.args.action in ("setup", "update"):
            if self.git("status", "--porcelain", "--untracked-files=all"):
                raise SetupError("Source checkout is dirty or has untracked files; commit or discard changes before setup")
            if not SHA.fullmatch(self.git("rev-parse", "HEAD")):
                raise SetupError("Source checkout requires a committed HEAD")
        # No tracked or unignored environment may be hidden from suite validation.
        if self.git("ls-files", "--", ".venv"):
            raise SetupError("The checkout .venv must be untracked")
        ignored = run(["git", "-C", self.source, "check-ignore", "--quiet", "--no-index", "--", ".venv/"])
        if ignored.returncode:
            raise SetupError("The checkout must ignore its local .venv directory")
        if self.args.action in ("setup", "update"):
            self.verify_requirements()

    def verify_requirements(self):
        requirements = self.source / "requirements-dev.txt"
        if requirements.is_symlink() or not requirements.is_file():
            raise SetupError("Missing or unsafe pinned requirements-dev.txt")
        actual = requirements.read_text(encoding="utf-8").splitlines()
        expected = ["{}=={}".format(name, version) for name, version in DEPENDENCIES.items()]
        if actual != expected:
            raise SetupError("requirements-dev.txt must contain the maintained exact dependency pins")

    def probe(self):
        real_directory(self.environment)
        if not self.environment.exists():
            return {"exists": False, "ready": False}
        cfg = self.environment / "pyvenv.cfg"
        if cfg.is_symlink() or not cfg.is_file():
            raise SetupError("Existing .venv is unidentified; use a real Python virtual environment or move it aside")
        for directory, directories, _files in os.walk(str(self.environment), followlinks=False):
            for name in directories:
                path = Path(directory) / name
                if path.is_symlink():
                    # Linux venv creates this direct internal compatibility link.
                    if path == self.environment / "lib64" and os.readlink(str(path)) == "lib":
                        real_directory(self.environment / "lib", required=True)
                        continue
                    raise SetupError("Symlinked environment directory is unsafe: {}".format(path))
        real_directory(self.environment / "bin", required=True)
        if not self.python.is_file():
            raise SetupError("Existing .venv has no usable Python; move it aside and rerun")
        result = run([self.python, "-c", ENVIRONMENT_PROBE, self.environment])
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError) as exc:
            raise SetupError("Existing .venv is incompatible or unidentified; move it aside and rerun") from exc
        if result.returncode or report.get("valid") is not True:
            raise SetupError("Existing .venv is incompatible or unidentified; Python 3.9+ in this exact directory is required")
        return {"exists": True, "ready": report.get("ready") is True}

    @contextlib.contextmanager
    def lock(self):
        git_dir = real_directory(self.git("rev-parse", "--absolute-git-dir"), required=True)
        path = git_dir / "codex-workflows-setup.lock"
        if path.is_symlink():
            raise SetupError("Unsafe environment preparation lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SetupError("Unsafe environment preparation lock")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SetupError("Another launcher is preparing this checkout; wait for it to finish and rerun") from exc
            yield
        finally:
            os.close(fd)

    def prepare(self):
        probe = self.probe()
        if not probe["exists"]:
            result = run([sys.executable, "-m", "venv", self.environment])
            if result.returncode:
                # A failed process may have left a directory that another process
                # changed. Preserve it rather than claiming deletion ownership.
                raise SetupError("Cannot create .venv; install Python venv/ensurepip support. Move any partial .venv aside before rerunning")
            probe = self.probe()
        if not probe["ready"]:
            self.verify_requirements()
            result = run([self.python, "-m", "pip", "--isolated", "install",
                          "--disable-pip-version-check", "--require-virtualenv", "--no-input",
                          "--root", "/", "--no-user", "--prefix", self.environment,
                          "-r", self.source / "requirements-dev.txt"])
            if result.returncode:
                raise SetupError("Pinned dependency installation failed; check package-index/network access and rerun ./install.sh. Installed workflows were not changed")
            if not self.probe()["ready"]:
                raise SetupError("Pinned dependencies are unavailable in .venv; installed workflows were not changed")

    def forwarded(self, action, apply=False):
        arguments = [self.python, self.source / "scripts" / "bootstrap.py", action,
                     "--source", self.source]
        if apply and action != "status":
            arguments.append("--apply")
        for name in ("home", "codex_home", "state_dir"):
            value = getattr(self.args, name)
            if value is not None:
                arguments.extend(["--" + name.replace("_", "-"), value])
        if action == self.args.action and action != "status":
            if action == "setup":
                arguments.extend(["--shell", self.args.shell])
            if self.args.migrate_from is not None:
                arguments.extend(["--migrate-from", self.args.migrate_from])
            if self.args.typesafe_legacy is not None:
                arguments.append("--typesafe-legacy")
                if self.args.typesafe_legacy:
                    arguments.append(self.args.typesafe_legacy)
            if self.args.no_checkout:
                arguments.append("--no-checkout")
        return arguments

    def bootstrap(self, action, apply=False):
        result = run(self.forwarded(action, apply))
        if result.returncode:
            # Bootstrap diagnostics contain file paths and field names, never values.
            error = result.stderr.decode(errors="replace").strip()
            raise SetupError(error or "Bootstrap {} failed; inspect ./install.sh status".format(action))
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeError) as exc:
            raise SetupError("Bootstrap returned an invalid report; inspect ./install.sh status") from exc

    def validate(self):
        result = run([self.python, self.source / "scripts" / "validate_suite.py", "--source", self.source])
        if result.returncode:
            error = result.stderr.decode(errors="replace").strip()
            raise SetupError(error or "Complete suite validation failed; installed workflows were not changed")

    def report(self, result=None, status=None, deferred=False):
        report = {
            "action": self.args.action,
            "dry_run": self.args.dry_run,
            "validation": "deferred" if deferred else "complete",
            "result": result,
            "status": status,
            "integration": {
                "jev_credential_present": bool(os.environ.get("TYPESAFE_API_KEY")),
                "connectors": "verify_in_codex",
            },
            "next_step": "Open a fresh Codex chat" if not deferred else "Rerun ./install.sh to prepare dependencies and complete preflight",
        }
        if deferred:
            report["preparation_plan"] = [
                "Create or reuse this checkout's real .venv with Python 3.9+",
                "Install PyYAML==6.0.3 and tomlkit==0.13.3 in .venv",
                "Validate the complete suite, then run bootstrap {}{}".format(
                    self.args.action, " --apply" if self.args.action != "status" else ""),
                "Read back local installation status; verify connectors separately in Codex",
            ]
            if self.args.action == "setup":
                report["preparation_plan"].insert(-1, "Enroll cw in the selected Bash/zsh startup file unless disabled or unsupported")
        elif status is not None and status.get("command_alias", {}).get("managed"):
            report["next_step"] = "Reload your shell startup file for cw and open a fresh Codex chat"
        return report

    def execute_prepared(self):
        if self.args.action in ("setup", "update"):
            self.validate()
        result = self.bootstrap(self.args.action, apply=not self.args.dry_run and self.args.action != "status")
        status = result if self.args.action == "status" else None
        if not self.args.dry_run and self.args.action != "status":
            status = self.bootstrap("status")
        return self.report(result, status)

    def execute(self):
        self.prerequisites()
        probe = self.probe()
        if self.args.dry_run or self.args.action == "status":
            if not probe["ready"]:
                if self.args.dry_run:
                    return self.report(deferred=True)
                raise SetupError("Status is deferred because pinned .venv dependencies are missing. Run ./install.sh --dry-run for the preparation plan, then ./install.sh to prepare and configure Codex")
            return self.execute_prepared()
        with self.lock():
            # Recheck after waiting: another launcher may have prepared the environment.
            self.prerequisites()
            self.prepare()
            return self.execute_prepared()


def parser(help_action=None):
    epilog = "Help is offline and makes no changes. Use ./install.sh before cw is loaded."
    if help_action is None:
        commands = "\n".join("  {:10} {}".format(name, ACTION_HELP[name]) for name in ACTIONS)
        epilog = ("Commands (setup is the default):\n" + commands +
                  "\n  help       Show this help, or use cw help COMMAND.\n\n" +
                  "Examples:\n  cw status\n  cw update --dry-run\n  cw help setup\n\n" + epilog)
    result = argparse.ArgumentParser(
        prog="cw" if help_action is None else "cw " + help_action,
        description=__doc__ if help_action is None else ACTION_HELP[help_action],
        epilog=epilog, add_help=False, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if help_action is None:
        result.add_argument("action", nargs="?", choices=ACTIONS + ("help",))
        result.add_argument("help_topic", nargs="?", choices=ACTIONS, metavar="COMMAND")
    result.add_argument("-h", "--help", action="store_true", dest="show_help", help="Show help without preparing environments, downloading, or writing files")
    result.add_argument("--dry-run", action="store_true", help="Plan without creating environments, downloading, or changing home/Git state")
    result.add_argument("--home", help="User home or isolated fixture home")
    result.add_argument("--codex-home", help="Existing Codex home (otherwise CODEX_HOME or HOME/.codex)")
    result.add_argument("--state-dir", help="Private workflow ownership state")
    if help_action in (None, "setup"):
        result.add_argument("--shell", choices=("auto", "bash", "zsh", "none"), default="auto", help="Shell for the managed cw command (auto detects SHELL; none skips enrollment)")
        result.add_argument("--migrate-from", help="Adopt exact registrations from this prior source")
        result.add_argument("--typesafe-legacy", nargs="?", const="", help="Adopt the matching legacy TypeSafe skill")
    if help_action in (None, "update"):
        result.add_argument("--no-checkout", action="store_true", help="Do not fast-forward the source checkout during explicit update")
    return result


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.help_topic is not None and args.action != "help":
        argument_parser.error("COMMAND is only accepted after help")
    if args.action == "help" or args.show_help:
        topic = args.help_topic if args.action == "help" else args.action
        parser(topic).print_help()
        return 0
    args.action = args.action or "setup"
    if args.shell != "auto" and args.action != "setup":
        argument_parser.error("--shell only applies to setup")
    try:
        report = Launcher(args).execute()
        print(json.dumps(report, sort_keys=True))
        return 0
    except (SetupError, OSError, ValueError) as exc:
        print("codex-workflows: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

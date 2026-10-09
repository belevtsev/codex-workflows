#!/usr/bin/env python3
"""Install a validated, commit-pinned Codex workflow suite (Python 3.9+)."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

from validate_suite import SuiteError, validate_suite
import model_config


START = b"<!-- codex-workflows-start -->"
END = b"<!-- codex-workflows-end -->"
STATE_VERSION = 1
SHA = re.compile(r"^[0-9a-f]{40}$")


class BootstrapError(Exception):
    """A safe refusal or a failed operation requiring explicit recovery."""


def encode(data):
    return base64.b64encode(data).decode("ascii")


def decode(data):
    try:
        return base64.b64decode(data.encode("ascii"), validate=True)
    except (ValueError, AttributeError) as exc:
        raise BootstrapError("Corrupt encoded local state") from exc


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_process(source, *args):
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    # Git may otherwise spawn detached maintenance during an apparently read-only
    # invocation. These process-local settings never modify repository/global config.
    return subprocess.run(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-C", str(source), *args], capture_output=True, env=environment)


def git(source, *args):
    result = git_process(source, *args)
    if result.returncode:
        raise BootstrapError("git {} failed: {}".format(" ".join(args), result.stderr.decode(errors="replace").strip()))
    return result.stdout


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def sealed(value):
    value = dict(value)
    value.pop("integrity_sha256", None)
    value["integrity_sha256"] = digest(json_bytes(value))
    return value


def verify_seal(value):
    if not isinstance(value, dict) or value.get("integrity_sha256") != sealed(value)["integrity_sha256"]:
        raise BootstrapError("Corrupt local state integrity checksum")


def read_json(path):
    try:
        if path.is_symlink() or not path.is_file():
            raise BootstrapError("Missing or unsafe local state: {}".format(path))
        return json.loads(path.read_bytes())
    except (ValueError, OSError) as exc:
        raise BootstrapError("Cannot read local state {}: {}".format(path, exc)) from exc


def macos_aliases():
    """Return only OS aliases that point to their exact maintained destinations."""
    aliases = []
    for alias in (Path("/var"), Path("/tmp")):
        destination = Path("/private") / alias.name
        # macOS ships these direct links as "private/var" and "private/tmp".
        # Accept their equivalent absolute spelling, never intermediate symlinks.
        if alias.is_symlink() and os.readlink(str(alias)) in (str(destination), "private/" + alias.name):
            aliases.append((str(alias), str(destination)))
    return aliases


def normalized_alias_target(target):
    """Replace only a verified OS alias prefix, preserving every remaining raw byte."""
    for alias, destination in macos_aliases():
        if target == alias or target.startswith(alias + "/"):
            return destination + target[len(alias):]
    return target


def equivalent_legacy_target(actual, expected):
    # Do not use resolve/abspath here: '..', duplicate separators, trailing slashes
    # and arbitrary symlink hops must still fail the original raw-target check.
    return normalized_alias_target(actual) == normalized_alias_target(expected)


def normalized_path(path):
    """Canonicalize only the standard macOS aliases, never owned subdirectories."""
    return Path(normalized_alias_target(os.path.abspath(str(path))))


def ensure_real_directory(path, create=False):
    """Reject symlinked path components; mutations must stay in the chosen roots."""
    path = normalized_path(path)
    for component in reversed([path] + list(path.parents)):
        if component.is_symlink():
            raise BootstrapError("Symlinked directory is unsafe: {}".format(component))
        if component.exists() and not component.is_dir():
            raise BootstrapError("Expected a directory: {}".format(component))
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def atomic_write(path, data, mode=0o600):
    ensure_real_directory(path.parent, create=True)
    fd, name = tempfile.mkstemp(prefix=".codex-workflows-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(path))
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def observed(path):
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(str(path))}
    if not path.exists():
        return {"kind": "absent"}
    if path.is_file():
        return {"kind": "file", "data": encode(path.read_bytes()), "mode": stat.S_IMODE(path.stat().st_mode)}
    if path.is_dir():
        return {"kind": "directory", "inventory": inventory(path), "mode": stat.S_IMODE(path.stat().st_mode)}
    raise BootstrapError("Unsupported occupied path: {}".format(path))


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = {"kind": "symlink", "target": os.readlink(str(path))}
        elif path.is_file():
            result[name] = {"kind": "file", "sha256": digest(path.read_bytes()), "mode": stat.S_IMODE(path.stat().st_mode)}
        elif path.is_dir():
            result[name] = {"kind": "directory", "mode": stat.S_IMODE(path.stat().st_mode)}
        else:
            raise BootstrapError("Unsupported file in {}: {}".format(root, path))
    return result


def same(actual, expected):
    # Directory receipts include modes, because adoption must be lossless.
    return actual == expected


def write_observation(path, value):
    kind = value["kind"]
    if kind == "absent":
        if path.is_symlink() or path.is_file():
            path.unlink()
            sync_directory(path.parent)
        elif path.exists():
            raise BootstrapError("Refusing to remove a directory: {}".format(path))
    elif kind == "file":
        atomic_write(path, decode(value["data"]), value["mode"])
    elif kind == "symlink":
        ensure_real_directory(path.parent, create=True)
        temporary = path.parent / (".codex-workflows-link-" + next(tempfile._get_candidate_names()))
        try:
            temporary.symlink_to(value["target"])
            os.replace(str(temporary), str(path))
            sync_directory(path.parent)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    else:
        raise BootstrapError("Unsupported write kind: {}".format(kind))


def block(template, leading=b""):
    # The template bytes remain intact inside the wrapper, including final-newline policy.
    return leading + START + b"\n" + template + (b"" if template.endswith(b"\n") else b"\n") + END + b"\n"


def locate_block(data):
    if data.count(START) != 1 or data.count(END) != 1:
        raise BootstrapError("AGENTS.md must contain exactly one valid managed marker pair")
    start = data.index(START)
    end = data.index(END)
    if end <= start or (start and data[start - 1:start] != b"\n"):
        raise BootstrapError("Malformed managed block in AGENTS.md")
    if data[start + len(START):start + len(START) + 1] != b"\n":
        raise BootstrapError("Malformed managed start marker")
    tail = end + len(END)
    if data[tail:tail + 1] != b"\n":
        raise BootstrapError("Malformed managed end marker")
    return start, tail + 1


def contains_markers(data):
    return b"codex-workflows-start" in data or b"codex-workflows-end" in data


def replace_owned(data, expected, replacement):
    start, end = locate_block(data)
    prefix = len(expected) - len(expected.lstrip(b"\n"))
    begin = start - prefix
    if begin < 0 or data[begin:end] != expected:
        raise BootstrapError("The owned AGENTS.md block was modified; refusing to overwrite it")
    return data[:begin] + replacement + data[end:]


def source_manifest(root):
    try:
        validate_suite(root)
        manifest = json.loads((root / "skills-manifest.json").read_bytes())
    except (SuiteError, ValueError, OSError) as exc:
        raise BootstrapError("Suite validation failed: {}".format(exc)) from exc
    return manifest


def fault(label):
    if os.environ.get("CODEX_WORKFLOWS_FAULT") == label:
        raise BootstrapError("Injected failure at {} (check status and recover before retrying)".format(label))


class Installer:
    def __init__(self, args):
        self.args = args
        self.home = normalized_path(args.home or Path.home())
        self.source = normalized_path(args.source or Path(__file__).resolve().parents[1])
        self.codex = normalized_path(args.codex_home or os.environ.get("CODEX_HOME") or self.home / ".codex")
        default_state = Path(os.environ.get("XDG_STATE_HOME") or self.home / ".local" / "state") / "codex-workflows"
        self.root = normalized_path(args.state_dir or default_state)
        self.skills = self.home / ".agents" / "skills"
        self.current = self.root / "current"
        self.state_path = self.root / "state.json"
        self.journal_path = self.root / "journal.json"
        self.agents = self.codex / "AGENTS.md"
        self.config = self.codex / "config.toml"

    def state(self, required=True):
        ensure_real_directory(self.root)
        if not self.state_path.exists():
            if required:
                raise BootstrapError("No installation state exists")
            return None
        state = read_json(self.state_path)
        verify_seal(state)
        try:
            if state["version"] != STATE_VERSION or not SHA.fullmatch(state["release"]):
                raise BootstrapError("Unsupported or corrupt installation state")
            if state["home"] != str(self.home) or state["codex_home"] != str(self.codex) or state["state_dir"] != str(self.root):
                raise BootstrapError("Installation state belongs to different roots")
            if not isinstance(state["registrations"], dict) or not isinstance(state["history"], list):
                raise BootstrapError("Corrupt installation ownership state")
            decode(state["global_segment"])
            if "model_config" in state:
                model_config.validate_metadata(state["model_config"])
        except (KeyError, TypeError) as exc:
            raise BootstrapError("Corrupt installation state") from exc
        return state

    @contextlib.contextmanager
    def lock(self, recovery=False):
        ensure_real_directory(self.root, create=True)
        os.chmod(str(self.root), 0o700)
        path = self.root / "mutation.lock"
        if path.is_symlink():
            raise BootstrapError("Unsafe mutation lock")
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BootstrapError("Another installer mutation holds the lock") from exc
            if self.journal_path.exists() and not recovery:
                raise BootstrapError("An unfinished mutation requires recover --apply")
            yield
        finally:
            os.close(fd)

    def clean_head(self):
        if git(self.source, "status", "--porcelain", "--untracked-files=all").strip():
            raise BootstrapError("Source checkout is dirty or has untracked files")
        sha = git(self.source, "rev-parse", "HEAD").decode().strip()
        if not SHA.fullmatch(sha):
            raise BootstrapError("Source HEAD is not a full commit SHA")
        return sha

    def allowed_origin(self):
        url = git(self.source, "config", "--get", "remote.origin.url").decode().strip()
        allowed = {
            "git@github.com:belevtsev/codex-workflows.git", "git@github.com:belevtsev/codex-workflows",
            "https://github.com/belevtsev/codex-workflows.git", "https://github.com/belevtsev/codex-workflows",
            "ssh://git@github.com/belevtsev/codex-workflows.git", "ssh://git@github.com/belevtsev/codex-workflows",
        }
        if url not in allowed:
            raise BootstrapError("origin must be the private belevtsev/codex-workflows GitHub repository")

    def descendant(self, before, after):
        result = git_process(self.source, "merge-base", "--is-ancestor", before, after)
        if result.returncode:
            raise BootstrapError("Update is diverged or rewinds history; only a clean fast-forward is allowed")

    def export(self, sha, directory):
        archive = git(self.source, "-c", "tar.umask=0022", "archive", "--format=tar", sha)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            members = stream.getmembers()
            for member in members:
                parts = Path(member.name).parts
                if member.name.startswith("/") or ".." in parts or not (member.isfile() or member.isdir()):
                    raise BootstrapError("Archive contains an unsafe or nonregular entry: {}".format(member.name))
            if hasattr(tarfile, "data_filter"):
                stream.extractall(str(directory), filter=tarfile.data_filter)
            else:
                stream.extractall(str(directory))
            # The data filter omits directory modes; keep receipts independent of
            # the caller's umask and identical to Git's deterministic archive.
            for member in members:
                (directory / member.name).chmod(member.mode & 0o777)
        return source_manifest(directory)

    @contextlib.contextmanager
    def preview(self, sha):
        # OS temp files are allowed; no installation, source or .git writes occur in dry-run.
        with tempfile.TemporaryDirectory(prefix="codex-workflows-preview-") as temporary:
            directory = Path(temporary)
            manifest = self.export(sha, directory)
            yield directory, manifest

    def release(self, sha):
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise BootstrapError("Invalid release SHA in local state")
        path = self.root / "releases" / sha
        receipt = self.root / "releases" / (sha + ".receipt.json")
        ensure_real_directory(path)
        data = read_json(receipt)
        if data.get("sha") != sha or data.get("inventory") != inventory(path):
            raise BootstrapError("Missing or modified immutable release: {}".format(sha))
        return path, source_manifest(path)

    def stage(self, sha):
        parent = ensure_real_directory(self.root / "releases", create=True)
        path = parent / sha
        receipt = parent / (sha + ".receipt.json")
        if path.exists() and not receipt.exists() and not receipt.is_symlink():
            # A publication crash may leave an unactivated, exact commit export.
            # Never repair receipts for installed/history releases or unknown content.
            existing = self.state(required=False)
            referenced = existing is not None and (existing["release"] == sha or any(item["release"] == sha for item in existing["history"]))
            if referenced or (self.current.is_symlink() and os.readlink(str(self.current)) == str(path)):
                raise BootstrapError("Missing receipt for a referenced immutable release")
            ensure_real_directory(path)
            with self.preview(sha) as (candidate, manifest):
                contents = inventory(candidate)
                if contents != inventory(path):
                    raise BootstrapError("Unreceipted release differs from its exact Git export")
                source_manifest(path)
                atomic_write(receipt, json_bytes({"sha": sha, "inventory": contents}))
            return self.release(sha)
        if path.exists() or path.is_symlink() or receipt.exists() or receipt.is_symlink():
            return self.release(sha)
        temporary = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(parent)))
        try:
            manifest = self.export(sha, temporary)
            contents = inventory(temporary)
            os.replace(str(temporary), str(path))
            sync_directory(parent)
            fault("after-release-publication")
            atomic_write(receipt, json_bytes({"sha": sha, "inventory": contents}))
            return path, manifest
        finally:
            if temporary.exists():
                shutil.rmtree(str(temporary))

    def registration_path(self, name):
        if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\\" in name:
            raise BootstrapError("Unsafe registration name")
        return self.skills / name

    def target(self, relative):
        return str(self.current / relative)

    def verify_owned(self, state, check_release=True):
        ensure_real_directory(self.skills)
        ensure_real_directory(self.codex)
        if observed(self.current) != {"kind": "symlink", "target": str(self.root / "releases" / state["release"])}:
            raise BootstrapError("Active release pointer is missing or has changed")
        if check_release:
            path, manifest = self.release(state["release"])
            if manifest["registrations"] != state["manifest_registrations"]:
                raise BootstrapError("Release manifest differs from installation state")
            segment = decode(state["global_segment"])
            leading = segment[:len(segment) - len(segment.lstrip(b"\n"))]
            if segment != block((path / manifest["global_instructions"]).read_bytes(), leading):
                raise BootstrapError("Owned global block differs from its validated release")
        for name, item in state["registrations"].items():
            if name not in state["manifest_registrations"] or item["target"] != self.target(state["manifest_registrations"][name]):
                raise BootstrapError("Corrupt registration ownership record")
            expected = {"kind": "symlink", "target": item["target"]}
            if observed(self.registration_path(name)) != expected:
                raise BootstrapError("Owned registration changed: {}".format(name))
        data = self.read_agents()
        replace_owned(data, decode(state["global_segment"]), b"")
        self.duplicates(state["manifest_registrations"], allowed_legacy=False)
        self.verify_backups(state)
        if "model_config" in state:
            model_config.verify(self.config, state["model_config"])

    def verify_backups(self, state):
        for name, item in state["registrations"].items():
            original = item["original"]
            if original["kind"] == "legacy":
                backup = Path(original["backup"])
                if backup.parent != self.root / "backups" or observed(backup) != original["observation"]:
                    raise BootstrapError("Missing or modified adoption backup: {}".format(name))

    def read_agents(self):
        if self.agents.is_symlink() or (self.agents.exists() and not self.agents.is_file()):
            raise BootstrapError("AGENTS.md is an occupied or symlinked path")
        return self.agents.read_bytes() if self.agents.exists() else b""

    def duplicates(self, registrations, allowed_legacy):
        roots = {self.codex / "skills", self.home / ".codex" / "skills"}
        legacy = self.legacy_path()
        for root in roots:
            ensure_real_directory(root)
            for name in registrations:
                path = root / name
                if path.exists() or path.is_symlink():
                    if allowed_legacy and name == "typesafe-ai" and path == legacy:
                        continue
                    raise BootstrapError("Duplicate discovery registration exists: {}".format(path))

    def legacy_path(self):
        value = self.args.typesafe_legacy
        if value is None:
            return None
        return normalized_path(value or self.home / ".codex" / "skills" / "typesafe-ai")

    def preflight_install(self, release, manifest):
        if self.state(required=False) is not None or self.current.exists() or self.current.is_symlink():
            raise BootstrapError("An installation already exists; use status or update")
        ensure_real_directory(self.skills)
        ensure_real_directory(self.codex)
        self.duplicates(manifest["registrations"], allowed_legacy=True)
        migration = normalized_path(self.args.migrate_from) if self.args.migrate_from else None
        if migration:
            ensure_real_directory(migration)
        records = {}
        operations = []
        for name, relative in manifest["registrations"].items():
            path = self.registration_path(name)
            before = observed(path)
            original = before
            if before["kind"] != "absent":
                expected = str(migration / relative) if migration else None
                if before["kind"] != "symlink" or expected is None or not equivalent_legacy_target(before["target"], expected):
                    raise BootstrapError("Unrelated occupied registration: {}".format(path))
            records[name] = {"target": self.target(relative), "original": original}
            operations.append(self.operation(path, before, {"kind": "symlink", "target": self.target(relative)}, "registration:" + name))
        legacy = self.legacy_path()
        if legacy is not None:
            if "typesafe-ai" not in records:
                raise BootstrapError("The suite does not register typesafe-ai")
            expected_location = self.home / ".codex" / "skills" / "typesafe-ai"
            if legacy != expected_location:
                raise BootstrapError("Legacy adoption is restricted to HOME/.codex/skills/typesafe-ai")
            if records["typesafe-ai"]["original"]["kind"] != "absent":
                raise BootstrapError("typesafe-ai already exists in the user registration root")
            original = observed(legacy)
            expected = observed(release / manifest["registrations"]["typesafe-ai"])
            if original["kind"] != "directory" or original["inventory"] != expected.get("inventory"):
                raise BootstrapError("Legacy typesafe-ai must contain exactly the matching suite files and modes")
            files = [value for value in original["inventory"].values() if value["kind"] == "file"]
            if len(files) != 3 or any(value["kind"] not in ("file", "directory") for value in original["inventory"].values()):
                raise BootstrapError("Legacy typesafe-ai must contain its three files and expected directories only")
            backup = self.root / "backups" / "typesafe-ai"
            if backup.exists() or backup.is_symlink():
                raise BootstrapError("Legacy backup path is occupied")
            records["typesafe-ai"]["original"] = {"kind": "legacy", "path": str(legacy), "backup": str(backup), "observation": original}
            operations.insert(0, {"kind": "rename", "path": str(legacy), "destination": str(backup), "observation": original, "label": "legacy"})
        before = self.read_agents()
        template = (release / manifest["global_instructions"]).read_bytes()
        origin = {"kind": "absent" if not self.agents.exists() else "unmanaged", "mode": stat.S_IMODE(self.agents.stat().st_mode) if self.agents.exists() else 0o600}
        if contains_markers(before):
            raise BootstrapError("Preexisting managed markers require valid installation ownership state")
        legacy_template = None
        if migration and before:
            legacy_path = migration / manifest["global_instructions"]
            if legacy_path.is_symlink() or not legacy_path.is_file():
                raise BootstrapError("Missing maintained legacy global template")
            legacy_template = legacy_path.read_bytes()
            if not legacy_template or not before.startswith(legacy_template):
                raise BootstrapError("Legacy global conventions prefix was modified; refusing migration")
        if legacy_template is not None:
            segment = block(template)
            after = segment + before[len(legacy_template):]
            origin["kind"] = "prefix"
            origin["prefix"] = encode(legacy_template)
        else:
            segment = block(template, b"\n" if before and not before.endswith(b"\n") else b"")
            after = before + segment
        operations.append(self.global_operation(before, after, None, segment, "global", before_replacement=legacy_template if legacy_template is not None else b""))
        return records, origin, segment, operations

    def operation(self, path, before, after, label):
        return {"kind": "path", "path": str(path), "before": before, "after": after, "label": label}

    def global_operation(self, before, after, before_segment, after_segment, label, before_replacement=b"", after_replacement=b""):
        observation = observed(self.agents)
        captured = decode(observation["data"]) if observation["kind"] == "file" else b""
        if observation["kind"] not in ("file", "absent") or captured != before:
            raise BootstrapError("AGENTS.md changed while preparing its managed update")
        return {
            "kind": "global", "path": str(self.agents), "before": observation,
            "after": {"kind": "file", "data": encode(after), "mode": observation.get("mode", 0o600)},
            "before_segment": encode(before_segment) if before_segment is not None else None,
            "after_segment": encode(after_segment) if after_segment is not None else None,
            "before_replacement": encode(before_replacement), "after_replacement": encode(after_replacement), "label": label,
        }

    def transact(self, command, operations):
        journal = {"version": STATE_VERSION, "command": command, "home": str(self.home), "codex_home": str(self.codex), "state_dir": str(self.root), "operations": operations}
        atomic_write(self.journal_path, json_bytes(sealed(journal)))
        fault("after-journal")
        for operation in operations:
            self.perform(operation)
            fault("after-" + operation["label"])
        self.journal_path.unlink()
        sync_directory(self.root)

    def perform(self, operation):
        path = Path(operation["path"])
        if operation["kind"] == "model_config":
            ensure_real_directory(path.parent)
            data, mode = model_config.render(path, operation)
            if data is None:
                write_observation(path, {"kind": "absent"})
            else:
                atomic_write(path, data, mode)
            return
        if operation["kind"] == "rename":
            destination = Path(operation["destination"])
            if observed(path) != operation["observation"] or observed(destination)["kind"] != "absent":
                raise BootstrapError("Legacy adoption ownership changed")
            ensure_real_directory(destination.parent, create=True)
            os.rename(str(path), str(destination))
            sync_directory(path.parent)
            sync_directory(destination.parent)
            return
        if observed(path) != operation["before"]:
            raise BootstrapError("Path changed during mutation: {}".format(path))
        write_observation(path, operation["after"])

    def new_state(self, sha, manifest, records, origin, segment):
        return sealed({"version": STATE_VERSION, "release": sha, "home": str(self.home), "codex_home": str(self.codex), "state_dir": str(self.root), "manifest_registrations": manifest["registrations"], "registrations": records, "global_origin": origin, "global_segment": encode(segment), "history": []})

    def expected_pointer(self, state):
        return {"kind": "symlink", "target": str(self.root / "releases" / state["release"])}

    def expected_state(self, state):
        return {"kind": "file", "data": encode(json_bytes(state)), "mode": 0o600}

    def install(self):
        sha = self.clean_head()
        with self.preview(sha) as (release, manifest):
            records, origin, segment, operations = self.preflight_install(release, manifest)
        if not self.args.apply:
            return {"command": "install", "dry_run": True, "release": sha, "registrations": sorted(records)}
        with self.lock():
            if self.clean_head() != sha:
                raise BootstrapError("Source HEAD changed before install")
            release, manifest = self.stage(sha)
            records, origin, segment, operations = self.preflight_install(release, manifest)
            state = self.new_state(sha, manifest, records, origin, segment)
            operations.insert(0, self.operation(self.current, {"kind": "absent"}, {"kind": "symlink", "target": str(release)}, "pointer"))
            operations.append(self.operation(self.state_path, {"kind": "absent"}, self.expected_state(state), "state"))
            self.transact("install", operations)
        return {"command": "install", "dry_run": False, "release": sha, "registrations": sorted(records)}

    def status(self):
        if self.journal_path.exists():
            raise BootstrapError("An unfinished mutation requires recover --apply")
        state = self.state(required=False)
        if state is None:
            if self.current.exists() or self.current.is_symlink():
                raise BootstrapError("Active pointer exists without ownership state")
            return {"installed": False, "model_config": {"managed": False}}
        self.verify_owned(state)
        release, manifest = self.release(state["release"])
        return {"installed": True, "release": state["release"], "previous_release": state["history"][-1]["release"] if state["history"] else None, "registrations": sorted(state["registrations"]), "state_dir": str(self.root), "model_defaults": model_config.coordinator_defaults(release, manifest), "model_config": {"managed": "model_config" in state}}

    def activation(self, state, sha, release, manifest, enroll=False, rollback=False):
        """Build one owned journal for setup, update or rollback activation."""
        self.check_manifest(state, manifest)
        self.verify_owned(state)
        after = dict(state)
        operations = []
        changed = sha != state["release"]
        if changed:
            after["history"] = state["history"][:-1] if rollback else state["history"] + [{"release": state["release"], "global_segment": state["global_segment"]}]
            after["release"] = sha
            old_segment = decode(state["global_segment"])
            leading = old_segment[:len(old_segment) - len(old_segment.lstrip(b"\n"))]
            segment = block((release / manifest["global_instructions"]).read_bytes(), leading)
            after["global_segment"] = encode(segment)
            contents = self.read_agents()
            operations.extend([self.operation(self.current, self.expected_pointer(state), {"kind": "symlink", "target": str(release)}, "pointer"), self.global_operation(contents, replace_owned(contents, old_segment, segment), old_segment, segment, "global")])
        if enroll or "model_config" in state:
            defaults = model_config.coordinator_defaults(release, manifest)
            metadata, config_operation = model_config.prepare(self.config, defaults, state.get("model_config"))
            after["model_config"] = metadata
            if config_operation is not None:
                operations.append(config_operation)
        after = sealed(after)
        if after != state:
            operations.append(self.operation(self.state_path, self.expected_state(state), self.expected_state(after), "state"))
        return operations

    def setup(self):
        """Install/enroll or activate an exact clean local fast-forward; never fetch."""
        if self.journal_path.exists():
            raise BootstrapError("An unfinished mutation requires recover --apply")
        sha = self.clean_head()
        state = self.state(required=False)
        with self.preview(sha) as (release, manifest):
            if state is None:
                records, origin, segment, operations = self.preflight_install(release, manifest)
                defaults = model_config.coordinator_defaults(release, manifest)
                metadata, config_operation = model_config.prepare(self.config, defaults)
                changed = True
            else:
                self.descendant(state["release"], sha)
                operations = self.activation(state, sha, release, manifest, enroll=True)
                changed = bool(operations)
                defaults = model_config.coordinator_defaults(release, manifest)
        if not self.args.apply:
            return {"command": "setup", "dry_run": True, "release": sha, "changed": changed, "model_defaults": defaults, "model_config": {"managed": True}}
        with self.lock():
            if self.clean_head() != sha or self.state(required=False) != state:
                raise BootstrapError("Source HEAD or installation changed before setup")
            release, manifest = self.stage(sha)
            if state is None:
                records, origin, segment, operations = self.preflight_install(release, manifest)
                defaults = model_config.coordinator_defaults(release, manifest)
                metadata, config_operation = model_config.prepare(self.config, defaults)
                after = dict(self.new_state(sha, manifest, records, origin, segment), model_config=metadata)
                after = sealed(after)
                operations.insert(0, self.operation(self.current, {"kind": "absent"}, {"kind": "symlink", "target": str(release)}, "pointer"))
                if config_operation is not None:
                    operations.append(config_operation)
                operations.append(self.operation(self.state_path, {"kind": "absent"}, self.expected_state(after), "state"))
            else:
                self.descendant(state["release"], sha)
                operations = self.activation(state, sha, release, manifest, enroll=True)
            if self.clean_head() != sha:
                raise BootstrapError("Source HEAD changed during setup")
            changed = bool(operations)
            if operations:
                self.transact("setup", operations)
        return {"command": "setup", "dry_run": False, "release": sha, "changed": changed, "model_defaults": defaults, "model_config": {"managed": True}}

    def update(self):
        state = self.state()
        self.verify_owned(state)
        head = self.clean_head()
        self.allowed_origin()
        if not self.args.apply:
            # Deliberately no fetch: describe the validated locally available HEAD.
            try:
                self.descendant(state["release"], head)
            except BootstrapError:
                # --no-checkout may intentionally leave this clean checkout behind.
                self.descendant(head, state["release"])
            with self.preview(head) as (release, manifest):
                self.check_manifest(state, manifest)
            return {"command": "update", "dry_run": True, "local_head": head, "active_release": state["release"], "fetch": "origin/main only with --apply"}
        with self.lock():
            state = self.state()
            self.verify_owned(state)
            head = self.clean_head()
            self.allowed_origin()
            git(self.source, "fetch", "--no-tags", "origin", "main")
            sha = git(self.source, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
            self.descendant(head, sha)
            self.descendant(state["release"], sha)
            release, manifest = self.stage(sha)
            self.check_manifest(state, manifest)
            if self.clean_head() != head:
                raise BootstrapError("Source HEAD changed during update")
            # Validation precedes checkout and activation. Never reset a user's checkout.
            if not self.args.no_checkout and head != sha:
                self.clean_head()
                git(self.source, "merge", "--ff-only", sha)
            operations = self.activation(state, sha, release, manifest)
            if operations:
                self.transact("update", operations)
        return {"command": "update", "dry_run": False, "release": sha, "changed": bool(operations)}

    def check_manifest(self, state, manifest):
        if manifest["registrations"] != state["manifest_registrations"]:
            raise BootstrapError("Registration names or roots changed; explicit uninstall and install are required")

    def rollback(self):
        state = self.state()
        self.verify_owned(state)
        if not state["history"]:
            raise BootstrapError("No previous release is available")
        previous = state["history"][-1]
        release, manifest = self.release(previous["release"])
        self.check_manifest(state, manifest)
        segment = decode(previous["global_segment"])
        if segment != block((release / manifest["global_instructions"]).read_bytes(), segment[:len(segment) - len(segment.lstrip(b"\n"))]):
            raise BootstrapError("Previous managed block does not match the validated release")
        if not self.args.apply:
            return {"command": "rollback", "dry_run": True, "release": previous["release"]}
        with self.lock():
            # Recheck after obtaining the lock; never act on stale ownership evidence.
            if self.state() != state:
                raise BootstrapError("Installation changed before rollback")
            self.verify_owned(state)
            operations = self.activation(state, previous["release"], release, manifest, rollback=True)
            self.transact("rollback", operations)
        return {"command": "rollback", "dry_run": False, "release": previous["release"]}

    def uninstall(self):
        state = self.state()
        self.verify_owned(state)
        if not self.args.apply:
            return {"command": "uninstall", "dry_run": True, "release": state["release"]}
        with self.lock():
            if self.state() != state:
                raise BootstrapError("Installation changed before uninstall")
            self.verify_owned(state)
            operations = []
            for name, item in state["registrations"].items():
                path = self.registration_path(name)
                original = item["original"]
                restored = {"kind": "absent"} if original["kind"] == "legacy" else original
                operations.append(self.operation(path, {"kind": "symlink", "target": item["target"]}, restored, "registration:" + name))
                if original["kind"] == "legacy":
                    legacy = Path(original["path"])
                    if observed(legacy)["kind"] != "absent":
                        raise BootstrapError("Legacy restore destination is occupied")
                    operations.append({"kind": "rename", "path": original["backup"], "destination": original["path"], "observation": original["observation"], "label": "legacy"})
            contents = self.read_agents()
            segment = decode(state["global_segment"])
            origin = state["global_origin"]
            replacement = decode(origin["prefix"]) if origin["kind"] == "prefix" else b""
            after = replace_owned(contents, segment, replacement)
            global_operation = self.global_operation(contents, after, segment, None, "global", after_replacement=replacement)
            # Remove a created empty file only; later user content always remains.
            if not after and origin["kind"] == "absent":
                global_operation["after"] = {"kind": "absent"}
            operations.append(global_operation)
            if "model_config" in state:
                operations.append(model_config.removal(self.config, state["model_config"]))
            operations.append(self.operation(self.current, self.expected_pointer(state), {"kind": "absent"}, "pointer"))
            operations.append(self.operation(self.state_path, self.expected_state(state), {"kind": "absent"}, "state"))
            self.transact("uninstall", operations)
        return {"command": "uninstall", "dry_run": False, "restored_adoptions": True, "retained_release_cache": str(self.root / "releases")}

    def load_journal(self):
        journal = read_json(self.journal_path)
        verify_seal(journal)
        if journal.get("version") != STATE_VERSION or any(journal.get(key) != str(value) for key, value in (("home", self.home), ("codex_home", self.codex), ("state_dir", self.root))):
            raise BootstrapError("Corrupt journal or roots do not match")
        if not isinstance(journal.get("operations"), list):
            raise BootstrapError("Corrupt mutation journal")
        # Whitelist every journal path. A corrupt journal cannot write arbitrary files.
        allowed = {self.current, self.state_path, self.agents, self.config}
        for operation in journal["operations"] + journal.get("recovery_operations", []):
            path = Path(operation.get("path", ""))
            if operation.get("kind") not in {"path", "global", "global_recovery", "rename", "model_config"}:
                raise BootstrapError("Unsafe operation kind in mutation journal")
            if operation.get("kind") == "model_config":
                if path != self.config:
                    raise BootstrapError("Unsafe model config path in mutation journal")
                ensure_real_directory(self.config.parent)
                model_config.validate_operation(operation)
                continue
            if path == self.config:
                raise BootstrapError("Model config requires a keyed journal operation")
            if operation.get("kind") == "rename":
                pair = {path, Path(operation.get("destination", ""))}
                if pair != {self.root / "backups" / "typesafe-ai", self.home / ".codex" / "skills" / "typesafe-ai"}:
                    raise BootstrapError("Unsafe rename in mutation journal")
            elif path not in allowed and not (path.parent == self.skills and path.name not in (".", "..", "")):
                raise BootstrapError("Unsafe path in mutation journal")
            if path == self.current:
                for observation in (operation["before"], operation["after"]):
                    if observation["kind"] == "symlink":
                        release = Path(observation["target"])
                        if release.parent != self.root / "releases" or not SHA.fullmatch(release.name):
                            raise BootstrapError("Unsafe release pointer in mutation journal")
                        self.release(release.name)
            if path == self.state_path:
                for observation in (operation["before"], operation["after"]):
                    if observation["kind"] == "file":
                        try:
                            state = json.loads(decode(observation["data"]))
                            verify_seal(state)
                            if "model_config" in state:
                                model_config.validate_metadata(state["model_config"])
                            self.release(state["release"])
                            for previous in state["history"]:
                                self.release(previous["release"])
                        except (ValueError, KeyError, TypeError) as exc:
                            raise BootstrapError("Corrupt installation state in mutation journal") from exc
        return journal

    def recovery_plan(self, journal):
        # Preflight every reversal before writing any of them.
        reversals = []
        for operation in reversed(journal["operations"]):
            path = Path(operation["path"])
            if operation["kind"] == "model_config":
                reversal = model_config.reversal(path, operation)
                if reversal is not None:
                    reversals.append(reversal)
                continue
            if operation["kind"] == "rename":
                destination = Path(operation["destination"])
                left, right = observed(path), observed(destination)
                if left == operation["observation"] and right["kind"] == "absent":
                    continue
                if left["kind"] == "absent" and right == operation["observation"]:
                    reversals.append({"kind": "rename", "path": str(destination), "destination": str(path), "observation": operation["observation"], "label": "recover-legacy"})
                    continue
                raise BootstrapError("Legacy paths changed; recovery refuses to overwrite them")
            current = observed(path)
            if current == operation["before"]:
                continue
            if operation["kind"] == "global" and operation["after_segment"] is None:
                before_segment = decode(operation["before_segment"])
                if current["kind"] == "file" and contains_markers(decode(current["data"])):
                    replace_owned(decode(current["data"]), before_segment, b"")
                    continue  # Removal has not happened; retain unrelated edits.
                target = self.restore_removed_global(operation, current)
                reversal = self.operation(path, current, target, "recover-global")
                reversal.update(kind="global_recovery", source_segment=None, target_segment=operation["before_segment"], replacement=operation["after_replacement"], restoration=operation)
                reversals.append(reversal)
                continue
            if operation["kind"] == "global" and operation["after_segment"] is not None and current["kind"] == "file":
                after_segment = decode(operation["after_segment"])
                before_segment = decode(operation["before_segment"]) if operation["before_segment"] is not None else None
                replacement = before_segment if before_segment is not None else decode(operation["before_replacement"])
                try:
                    contents = replace_owned(decode(current["data"]), after_segment, replacement)
                except BootstrapError:
                    if before_segment is not None:
                        try:
                            replace_owned(decode(current["data"]), before_segment, b"")
                            continue
                        except BootstrapError:
                            pass
                    raise
                target = {"kind": "file", "data": encode(contents), "mode": operation["before"].get("mode", current["mode"])}
                if not contents and operation["before"]["kind"] == "absent":
                    target = {"kind": "absent"}
                reversal = self.operation(path, current, target, "recover-global")
                reversal.update(kind="global_recovery", source_segment=operation["after_segment"], target_segment=operation["before_segment"], replacement=encode(replacement), restoration=operation)
                reversals.append(reversal)
            elif current == operation["after"]:
                reversals.append(self.operation(path, current, operation["before"], "recover-" + operation["label"]))
            else:
                raise BootstrapError("Ownership changed at {}; recovery refuses to overwrite it".format(path))
        return reversals

    def restore_removed_global(self, operation, current):
        if current["kind"] not in ("absent", "file"):
            raise BootstrapError("AGENTS.md ownership changed during removal recovery")
        contents = decode(current["data"]) if current["kind"] == "file" else b""
        if contains_markers(contents):
            raise BootstrapError("Unexpected managed markers during removal recovery")
        segment = decode(operation["before_segment"])
        replacement = decode(operation["after_replacement"])
        if replacement:
            # Migration restored this exact original prefix. Only that prefix is owned.
            if contents.count(replacement) != 1:
                raise BootstrapError("Restored legacy prefix changed; refusing recovery")
            position = contents.index(replacement)
            if position and contents[position - 1:position] != b"\n" and not segment.startswith(b"\n"):
                raise BootstrapError("Legacy prefix no longer starts on a valid line; refusing recovery")
            contents = contents.replace(replacement, segment, 1)
        else:
            original = decode(operation["before"]["data"])
            start, end = locate_block(original)
            leading = len(segment) - len(segment.lstrip(b"\n"))
            prefix = original[:start - leading]
            # Keep the old position when its preceding text survives. If that text
            # changed, prepend the owned block without changing any user bytes.
            position = len(prefix) if contents.startswith(prefix) else 0
            contents = contents[:position] + segment + contents[position:]
        return {"kind": "file", "data": encode(contents), "mode": current.get("mode", operation["before"].get("mode", 0o600))}

    def recover(self):
        if not self.journal_path.exists():
            return {"command": "recover", "pending": False, "dry_run": not self.args.apply}
        journal = self.load_journal()
        reversals = self.pending_recovery(journal)
        if not self.args.apply:
            return {"command": "recover", "pending": True, "dry_run": True, "reversals": len(reversals)}
        with self.lock(recovery=True):
            journal = self.load_journal()
            reversals = self.pending_recovery(journal)
            if "recovery_operations" not in journal:
                journal["recovery_operations"] = reversals
                atomic_write(self.journal_path, json_bytes(sealed(journal)))
            for operation in reversals:
                self.perform(operation)
                fault("after-" + operation["label"])
            self.journal_path.unlink()
            sync_directory(self.root)
        return {"command": "recover", "pending": False, "dry_run": False, "recovered": journal["command"]}

    def pending_recovery(self, journal):
        if "recovery_operations" not in journal:
            return self.recovery_plan(journal)
        pending = []
        for operation in journal["recovery_operations"]:
            path = Path(operation["path"])
            if operation["kind"] == "model_config":
                pending_operation = model_config.pending(path, operation)
                if pending_operation is not None:
                    pending.append(pending_operation)
                continue
            current = observed(path)
            if operation["kind"] == "global_recovery":
                if current["kind"] not in ("file", "absent"):
                    raise BootstrapError("AGENTS.md ownership changed during interrupted recovery")
                contents = decode(current["data"]) if current["kind"] == "file" else b""
                source_segment = decode(operation["source_segment"]) if operation["source_segment"] is not None else None
                target_segment = decode(operation["target_segment"]) if operation["target_segment"] is not None else None
                if contains_markers(contents):
                    if target_segment is not None:
                        try:
                            replace_owned(contents, target_segment, b"")
                            continue  # Already restored; retain subsequent user edits.
                        except BootstrapError:
                            pass
                    if source_segment is None:
                        raise BootstrapError("Owned block changed during interrupted recovery")
                    result = replace_owned(contents, source_segment, target_segment if target_segment is not None else decode(operation["replacement"]))
                    target = {"kind": "file", "data": encode(result), "mode": current["mode"]}
                    if not result and operation["after"]["kind"] == "absent":
                        target = {"kind": "absent"}
                elif target_segment is None:
                    continue  # Managed removal completed; all remaining bytes are user-owned.
                elif source_segment is None:
                    target = self.restore_removed_global(operation["restoration"], current)
                else:
                    raise BootstrapError("Owned block disappeared during interrupted recovery")
                pending_operation = dict(operation, before=current, after=target)
                pending.append(pending_operation)
            elif operation["kind"] == "rename":
                destination = observed(Path(operation["destination"]))
                if current == operation["observation"] and destination["kind"] == "absent":
                    pending.append(operation)
                elif current["kind"] != "absent" or destination != operation["observation"]:
                    raise BootstrapError("Ownership changed during interrupted legacy recovery")
            elif current == operation["before"]:
                pending.append(operation)
            elif current != operation["after"]:
                raise BootstrapError("Ownership changed during interrupted recovery: {}".format(path))
        return pending


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("setup", "install", "status", "update", "rollback", "recover", "uninstall"))
    result.add_argument("--apply", action="store_true", help="Apply mutations; otherwise only preflight")
    result.add_argument("--source", help="Clean suite Git checkout (defaults to the script's repository)")
    result.add_argument("--home", help="User home or isolated fixture home")
    result.add_argument("--codex-home", help="Codex home (otherwise CODEX_HOME or HOME/.codex)")
    result.add_argument("--state-dir", help="Private state root (otherwise XDG_STATE_HOME/codex-workflows)")
    result.add_argument("--migrate-from", help="Adopt only raw symlinks to this prior suite root")
    result.add_argument("--typesafe-legacy", nargs="?", const="", help="Adopt matching legacy HOME/.codex/skills/typesafe-ai")
    result.add_argument("--no-checkout", action="store_true", help="Update the active release without fast-forwarding the source checkout")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        installer = Installer(args)
        report = getattr(installer, args.command)()
        print(json.dumps(report, sort_keys=True))
        return 0
    except (BootstrapError, model_config.ModelConfigError, OSError, KeyError, TypeError) as exc:
        print("codex-workflows: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

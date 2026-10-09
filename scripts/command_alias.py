"""Own one reversible cw shell function, without persisting unrelated rc bytes."""
import os
from pathlib import Path
import re
import shlex
import stat


START = b"# >>> codex-workflows cw >>>"
END = b"# <<< codex-workflows cw <<<"
MARKER = b"codex-workflows cw"
SHELLS = {"bash", "zsh"}


class CommandAliasError(Exception):
    """An unsafe shell path, conflicting definition, or changed owned block."""


def selected_shell(choice, home=None, environment=None):
    environment = os.environ if environment is None else environment
    shell = Path(environment.get("SHELL") or "bash").name if choice == "auto" else choice
    if shell == "none":
        return None, "disabled"
    if shell not in SHELLS:
        return None, "unsupported shell {}; add cw manually".format(shell)
    if (shell == "zsh" and environment.get("ZDOTDIR")
            and (home is None or os.path.abspath(environment["ZDOTDIR"]) != str(home))):
        # A process-specific ZDOTDIR may differ from the shell's startup value.
        # Keep automatic ownership restricted to the enrolled home rc paths.
        return None, "ZDOTDIR is set; add cw manually or unset ZDOTDIR for home .zshrc enrollment"
    return shell, "enrolled"


def rc_path(home, shell):
    if shell not in SHELLS:
        raise CommandAliasError("Corrupt cw shell selection")
    return Path(home) / ("." + shell + "rc")


def segment(source, home, codex_home, state_dir, leading=b""):
    arguments = [str(Path(source) / "install.sh"), "--home", str(home),
                 "--codex-home", str(codex_home), "--state-dir", str(state_dir)]
    command = " ".join(shlex.quote(argument) for argument in arguments)
    invocation = command + ' "$@"'
    owner = shlex.quote(invocation)
    script = ('if command -v cw >/dev/null 2>&1; then\n'
              '  if [ "${_CODEX_WORKFLOWS_CW_OWNER-}" != ' + owner + ' ]; then\n'
              "    printf '%s\\n' 'codex-workflows: cw already exists; keeping current command' >&2\n"
              '  fi\nelse\n  function cw {\n    ' + invocation + '\n  }\n'
              '  typeset +x _CODEX_WORKFLOWS_CW_OWNER=' + owner + '\nfi\n')
    return leading + START + b"\n" + script.encode("utf-8") + END + b"\n"


def real_parent(path):
    for component in reversed([path.parent] + list(path.parent.parents)):
        if component.is_symlink() or (component.exists() and not component.is_dir()):
            raise CommandAliasError("Unsafe shell startup directory: {}".format(component))


def read(path):
    real_parent(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise CommandAliasError("Shell startup path is occupied or symlinked: {}".format(path))
    if not path.exists():
        return b"", False, 0o600
    return path.read_bytes(), True, stat.S_IMODE(path.stat().st_mode)


def has_definition(data):
    # Conservatively detect declarations inside compound commands and eval text
    # too. An ambiguous declaration is safer to leave for manual enrollment.
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"(?m)^[ \t]*#.*$", "", text)
    text = text.replace("\\\n", "")
    functions = r"\b(?:function\s+[^\n{]*\bcw\b|cw\s*\(\s*\)|functions\s*\[\s*[\"']?cw\b)"
    aliases = r"\balias\s+([^\n;]*)"
    return bool(re.search(functions, text) or any(
        re.search(r"(?:^|\s)[\"']?cw[\"']?\s*=", match.group(1))
        for match in re.finditer(aliases, text)))


def locate(data, expected):
    if data.count(START) != 1 or data.count(END) != 1:
        raise CommandAliasError("Shell startup file must contain one owned cw marker pair")
    start = data.index(START)
    end = data.index(END) + len(END) + 1
    leading = len(expected) - len(expected.lstrip(b"\n"))
    begin = start - leading
    if (begin < 0 or (start and data[start - 1:start] != b"\n")
            or data[begin:end] != expected):
        raise CommandAliasError("Owned cw block changed; refusing to overwrite it")
    remainder = data[:begin] + data[end:]
    if MARKER in remainder:
        raise CommandAliasError("Unidentified cw markers in shell startup file")
    if has_definition(remainder):
        raise CommandAliasError("Another cw definition exists in shell startup file")
    return begin, end


def unowned(data):
    if MARKER in data or b"codex-workflows-cw" in data:
        raise CommandAliasError("Preexisting cw markers require installation ownership state")
    if has_definition(data):
        raise CommandAliasError("Existing cw definition in shell startup file; refusing to overwrite it")


def validate_segment(value, source, home, codex_home, state_dir):
    if not isinstance(value, str):
        raise CommandAliasError("Corrupt cw block metadata")
    data = value.encode("utf-8")
    if data not in (segment(source, home, codex_home, state_dir),
                    segment(source, home, codex_home, state_dir, b"\n")):
        raise CommandAliasError("Corrupt cw block metadata")
    return data


def validate_source(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or os.path.normpath(value) != value:
        raise CommandAliasError("Corrupt cw source checkout path")
    path = Path(value)
    real_parent(path / "install.sh")
    installer = path / "install.sh"
    if installer.is_symlink() or not installer.is_file():
        raise CommandAliasError("cw source checkout has no regular install.sh")


def validate_metadata(value, home, codex_home, state_dir):
    fields = {"shell", "path", "source", "segment", "original_exists", "original_mode"}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value.get("original_exists")) is not bool
            or type(value.get("original_mode")) is not int
            or not 0 <= value["original_mode"] <= 0o7777):
        raise CommandAliasError("Corrupt cw ownership metadata")
    if value["path"] != str(rc_path(home, value["shell"])):
        raise CommandAliasError("Unsafe cw startup path in ownership metadata")
    validate_source(value["source"])
    validate_segment(value["segment"], value["source"], home, codex_home, state_dir)


def verify(value, home, codex_home, state_dir):
    validate_metadata(value, home, codex_home, state_dir)
    data, exists, _mode = read(Path(value["path"]))
    if not exists:
        raise CommandAliasError("Owned cw block disappeared")
    locate(data, value["segment"].encode("utf-8"))


def operation(value, before_segment, after_segment, before_exists, after_exists,
              before_mode, after_mode, label="command-alias"):
    return {"kind": "command_alias", "path": value["path"], "shell": value["shell"],
            "source": value["source"], "before_segment": before_segment,
            "after_segment": after_segment, "before_exists": before_exists,
            "after_exists": after_exists, "before_mode": before_mode,
            "after_mode": after_mode, "label": label}


def prepare(source, home, codex_home, state_dir, choice, metadata=None):
    if metadata is not None:
        verify(metadata, home, codex_home, state_dir)
        if metadata["source"] != str(source):
            raise CommandAliasError("cw belongs to another source checkout; use the enrolled checkout or uninstall before setup here")
        return metadata, None, report(metadata, "preserved")
    shell, status = selected_shell(choice, home)
    if shell is None:
        return None, None, {"managed": False, "status": status}
    validate_source(str(source))
    path = rc_path(home, shell)
    data, exists, mode = read(path)
    unowned(data)
    owned = segment(source, home, codex_home, state_dir,
                    b"\n" if data and not data.endswith(b"\n") else b"")
    metadata = {"shell": shell, "path": str(path), "source": str(source),
                "segment": owned.decode("utf-8"), "original_exists": exists,
                "original_mode": mode}
    change = operation(metadata, None, metadata["segment"], exists, True, mode, mode)
    return metadata, change, report(metadata, status)


def report(metadata, status="enrolled"):
    if metadata is None:
        return {"managed": False}
    return {"managed": True, "shell": metadata["shell"], "path": metadata["path"],
            "status": status}


def removal(metadata, home, codex_home, state_dir):
    verify(metadata, home, codex_home, state_dir)
    _data, exists, mode = read(Path(metadata["path"]))
    return operation(metadata, metadata["segment"], None, exists,
                     metadata["original_exists"], mode, metadata["original_mode"])


def validate_operation(value, home, codex_home, state_dir):
    fields = {"kind", "path", "shell", "source", "before_segment", "after_segment",
              "before_exists", "after_exists", "before_mode", "after_mode", "label"}
    if (not isinstance(value, dict) or set(value) != fields or value.get("kind") != "command_alias"
            or value.get("label") not in {"command-alias", "recover-command-alias"}
            or any(type(value.get(key)) is not bool for key in ("before_exists", "after_exists"))
            or any(type(value.get(key)) is not int or not 0 <= value[key] <= 0o7777
                   for key in ("before_mode", "after_mode"))):
        raise CommandAliasError("Corrupt keyed cw operation")
    if value["path"] != str(rc_path(home, value["shell"])):
        raise CommandAliasError("Unsafe cw startup path in mutation journal")
    validate_source(value["source"])
    for key, exists in (("before_segment", "before_exists"), ("after_segment", "after_exists")):
        if value[key] is not None:
            validate_segment(value[key], value["source"], home, codex_home, state_dir)
            if not value[exists]:
                raise CommandAliasError("Corrupt absent cw operation")
    if value["before_segment"] == value["after_segment"]:
        raise CommandAliasError("Corrupt cw operation with no block change")
    read(Path(value["path"]))


def current_segment(data, value):
    if MARKER not in data and b"codex-workflows-cw" not in data:
        unowned(data)
        return None
    # Each valid operation owns at most one generated segment. Never mistake a
    # hand-edited block, duplicate marker, or second cw definition for a phase.
    for key in ("before_segment", "after_segment"):
        if value[key] is not None:
            try:
                locate(data, value[key].encode("utf-8"))
                return value[key]
            except CommandAliasError:
                pass
    raise CommandAliasError("Owned cw block changed; refusing recovery")


def render(value, home, codex_home, state_dir):
    """Re-read unowned bytes at execution; serialize only the owned segment."""
    validate_operation(value, home, codex_home, state_dir)
    data, exists, mode = read(Path(value["path"]))
    if (value["label"] == "command-alias" and value["before_segment"] is None
            and exists != value["before_exists"]):
        raise CommandAliasError("Shell startup file existence changed during enrollment")
    if current_segment(data, value) != value["before_segment"]:
        raise CommandAliasError("Owned cw block changed during mutation")
    if value["before_segment"] is None:
        target = value["after_segment"].encode("utf-8")
        # Recovery of removal can prepend the block if a concurrent edit no
        # longer ends on a newline; every user byte is retained unchanged.
        result = data + target if not data or data.endswith(b"\n") or target.startswith(b"\n") else target + data
    else:
        start, end = locate(data, value["before_segment"].encode("utf-8"))
        target = value["after_segment"].encode("utf-8") if value["after_segment"] is not None else b""
        result = data[:start] + target + data[end:]
    remove = not value["after_exists"] and not result
    if remove and exists and mode != value["before_mode"]:
        raise CommandAliasError("Shell startup file mode changed before removal; refusing to delete it")
    return None if remove else result, mode if exists else value["after_mode"]


def reversal(value, home, codex_home, state_dir):
    validate_operation(value, home, codex_home, state_dir)
    data, exists, mode = read(Path(value["path"]))
    current = current_segment(data, value)
    if current == value["before_segment"]:
        return None
    if current != value["after_segment"]:
        raise CommandAliasError("Owned cw block changed; recovery refuses to overwrite it")
    return operation(value, value["after_segment"], value["before_segment"], exists,
                     value["before_exists"], mode, value["before_mode"], "recover-command-alias")


def pending(value, home, codex_home, state_dir):
    validate_operation(value, home, codex_home, state_dir)
    data, _exists, _mode = read(Path(value["path"]))
    current = current_segment(data, value)
    if current == value["after_segment"]:
        return None
    if current != value["before_segment"]:
        raise CommandAliasError("Owned cw block changed during interrupted recovery")
    return value

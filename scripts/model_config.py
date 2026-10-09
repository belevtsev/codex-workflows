"""Own only Codex's two root model defaults, with format-preserving TOML edits."""
import copy
import importlib.util
from pathlib import Path
import stat
import sys

import tomlkit
from tomlkit.items import Comment


KEYS = ("model", "model_reasoning_effort")


class ModelConfigError(ValueError):
    """A config or ownership record cannot be safely changed."""


def coordinator_defaults(release, manifest):
    """Use the validated target release's maintained policy loader and resolver."""
    policy = Path(release) / manifest["model_policy"]
    validator = policy.parent / "scripts" / "validate_policy.py"
    try:
        spec = importlib.util.spec_from_file_location("_bootstrap_coordinator_policy", validator)
        if spec is None or spec.loader is None:
            raise ModelConfigError("Cannot load coordinator model policy")
        module = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous
        worker = module.resolve_worker(module.load_policy(policy), "coordinator")
        return {"model": worker["model"], "model_reasoning_effort": worker["reasoning_effort"]}
    except (OSError, ImportError, AttributeError, ValueError, TypeError, RecursionError, SyntaxError) as exc:
        raise ModelConfigError("Cannot resolve validated coordinator model defaults") from exc


def parse(data):
    try:
        return tomlkit.parse(data.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise ModelConfigError("Codex config.toml is malformed; refusing to change it") from exc


def read(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ModelConfigError("Codex config.toml is occupied or symlinked")
    if not path.exists():
        return tomlkit.document(), False, 0o600
    return parse(path.read_bytes()), True, stat.S_IMODE(path.stat().st_mode)


def snapshot(document):
    if any(key in document and not isinstance(document[key], str) for key in KEYS):
        raise ModelConfigError("Codex root model defaults must be TOML strings")
    return {key: {"present": True, "representation": document.item(key).as_string()} if key in document else {"present": False} for key in KEYS}


def representation_item(key, value):
    try:
        document = tomlkit.parse(key + " = " + value + "\n")
        if list(document) != [key]:
            raise ModelConfigError("Corrupt model config value representation")
        if not isinstance(document[key], str):
            raise ModelConfigError("Model config ownership values must be TOML strings")
        return document.item(key)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ModelConfigError("Corrupt model config value representation") from exc


def validate_snapshot(values):
    if not isinstance(values, dict) or set(values) != set(KEYS):
        raise ModelConfigError("Corrupt model config ownership keys")
    for key, value in values.items():
        if not isinstance(value, dict) or type(value.get("present")) is not bool:
            raise ModelConfigError("Corrupt model config ownership value")
        if value["present"]:
            if set(value) != {"present", "representation"} or not isinstance(value["representation"], str):
                raise ModelConfigError("Corrupt model config ownership representation")
            representation_item(key, value["representation"])
        elif set(value) != {"present"}:
            raise ModelConfigError("Corrupt absent model config ownership value")


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != {"original", "expected", "original_exists"} or type(metadata.get("original_exists")) is not bool:
        raise ModelConfigError("Corrupt model config ownership metadata")
    validate_snapshot(metadata["original"])
    validate_snapshot(metadata["expected"])
    if not metadata["original_exists"] and any(metadata["original"][key]["present"] for key in KEYS):
        raise ModelConfigError("Corrupt absent model config origin")
    if not all(metadata["expected"][key]["present"] for key in KEYS):
        raise ModelConfigError("Corrupt managed model defaults")


def verify(path, metadata):
    validate_metadata(metadata)
    document, exists, _mode = read(path)
    if not exists or snapshot(document) != metadata["expected"]:
        raise ModelConfigError("Owned model defaults changed; refusing to overwrite them")


def set_value(document, key, item):
    if key in document or not document.body:
        document[key] = item
        return
    # Insert before the first existing key instead of TOMLKit's append-before-
    # table heuristic, which adds a blank line to an unrelated table. Leading
    # user comments remain in place, and no existing item's trivia is changed.
    position = next((index for index, (body_key, _item) in enumerate(document.body)
                     if body_key is not None), 0)
    document._insert_at(position, key, item)


def replace(document, target):
    """Keep all user tables, spacing and comments while replacing owned values."""
    validate_snapshot(target)
    result = copy.deepcopy(document)
    for key in reversed(KEYS):
        item = target[key]
        if item["present"]:
            set_value(result, key, representation_item(key, item["representation"]))
        elif key in result:
            # TOMLKit removes an attached comment with its value. Keep that user
            # comment as a standalone line at the same position before deletion.
            previous = result.item(key)
            comment = previous.trivia.comment
            position = next(index for index, (body_key, _body_item) in enumerate(result.body)
                            if body_key is not None and body_key.key == key)
            del result[key]
            if comment:
                # Pinned TOMLKit leaves a Null body slot after deletion. Replacing
                # that slot with its own Comment changes no container key indices
                # and preserves the exact comment spelling, indentation and trail.
                result.body[position] = (None, Comment(copy.deepcopy(previous.trivia)))
    return result


def desired_snapshot(document, defaults):
    result = copy.deepcopy(document)
    for key in reversed(KEYS):
        set_value(result, key, representation_item(key, tomlkit.item(defaults[key]).as_string()))
    return snapshot(result)


def operation(path, before, after, before_exists, after_exists, before_mode, after_mode, label="model-config"):
    return {"kind": "model_config", "path": str(path), "before_keys": before, "after_keys": after,
            "before_exists": before_exists, "after_exists": after_exists,
            "before_mode": before_mode, "after_mode": after_mode, "label": label}


def validate_operation(value):
    fields = {"kind", "path", "before_keys", "after_keys", "before_exists", "after_exists", "before_mode", "after_mode", "label"}
    if not isinstance(value, dict) or set(value) != fields or value.get("kind") != "model_config" or type(value.get("before_exists")) is not bool or type(value.get("after_exists")) is not bool:
        raise ModelConfigError("Corrupt keyed model config operation")
    if not isinstance(value["path"], str) or value["label"] not in {"model-config", "recover-model-config"}:
        raise ModelConfigError("Corrupt model config operation path or label")
    if any(type(value[field]) is not int or not 0 <= value[field] <= 0o7777 for field in ("before_mode", "after_mode")):
        raise ModelConfigError("Corrupt model config operation mode")
    validate_snapshot(value.get("before_keys"))
    validate_snapshot(value.get("after_keys"))
    for exists, keys in ((value["before_exists"], value["before_keys"]), (value["after_exists"], value["after_keys"])):
        if not exists and any(item["present"] for item in keys.values()):
            raise ModelConfigError("Corrupt absent model config operation")


def prepare(path, defaults, metadata=None):
    document, exists, mode = read(path)
    if metadata is not None:
        verify(path, metadata)
    before = snapshot(document)
    validate_snapshot(before)
    after = desired_snapshot(document, defaults)
    owned = {"original": before, "original_exists": exists, "expected": after} if metadata is None else dict(metadata, expected=after)
    # Even values already matching defaults need enrollment, recorded by state.
    change = None if before == after and exists else operation(path, before, after, exists, True, mode, mode)
    return owned, change


def removal(path, metadata):
    verify(path, metadata)
    document, exists, mode = read(path)
    return operation(path, snapshot(document), metadata["original"], exists, metadata["original_exists"], mode, mode)


def render(path, value):
    """Re-read at execution time so unrelated concurrent edits always survive."""
    validate_operation(value)
    document, exists, mode = read(path)
    if snapshot(document) != value["before_keys"]:
        raise ModelConfigError("Owned model defaults changed during mutation; refusing to overwrite them")
    result = replace(document, value["after_keys"])
    data = tomlkit.dumps(result).encode("utf-8")
    remove = not value["after_exists"] and not data
    if remove and exists and mode != value["before_mode"]:
        raise ModelConfigError("Codex config.toml mode changed before removal; refusing to delete it")
    return None if remove else data, mode if exists else value["after_mode"]


def reversal(path, value):
    """Reverse only owned keys; both preflight and resumable recovery use this."""
    validate_operation(value)
    document, exists, mode = read(path)
    current = snapshot(document)
    if current == value["before_keys"]:
        return None  # Not applied, or its owned values were already restored.
    if current != value["after_keys"]:
        raise ModelConfigError("Owned model defaults changed; recovery refuses to overwrite them")
    return operation(path, value["after_keys"], value["before_keys"], exists,
                     value["before_exists"], mode, value["before_mode"], "recover-model-config")


def pending(path, value):
    validate_operation(value)
    document, _exists, _mode = read(path)
    current = snapshot(document)
    if current == value["after_keys"]:
        return None
    if current != value["before_keys"]:
        raise ModelConfigError("Owned model defaults changed during interrupted recovery")
    return value

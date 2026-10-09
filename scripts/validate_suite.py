#!/usr/bin/env python3
"""Validate a portable workflow source tree without changing files or settings."""

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml


DEFAULT_SOURCE = Path(__file__).resolve().parents[1]
MANIFEST_FIELDS = {
    "version", "registrations", "global_instructions", "required_licenses", "model_policy",
}
SKILL_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PRIVATE_DIRECTORIES = {
    ".agents", ".codex", ".private", ".baseline", "private-baseline", "baseline-private",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "node_modules",
}
PRIVATE_FILES = {"auth.json", "config.toml", ".DS_Store"}
ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}
LOCAL_ARTIFACT_DIRECTORIES = {".venv", "__pycache__"}
PROJECT_TEMPLATE_DOCUMENTS = {
    "LICENSE", "LICENSE.md", "LICENSE.txt", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "CHANGELOG.md", "SECURITY.md", "README.md",
}
TEMPLATE_PLACEHOLDER = re.compile(r"\{[a-z][a-z0-9_-]*\}", re.IGNORECASE)


class SuiteError(ValueError):
    """An invalid suite; diagnostics identify files or fields, never file contents."""


def require(condition, message):
    if not condition:
        raise SuiteError(message)


def unique_mapping(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate mapping key")
        result[key] = value
    return result


class FrontmatterLoader(yaml.SafeLoader):
    pass


def yaml_mapping(loader, node):
    loader.flatten_mapping(node)
    return unique_mapping(loader.construct_pairs(node))


FrontmatterLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_mapping)


def read_text(path, description):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SuiteError("cannot read " + description) from error


def relative_path(root, value, field):
    """Manifest paths use canonical POSIX spelling and stay within the source."""
    require(isinstance(value, str) and bool(value.strip()), field + " must be a relative path")
    require("\\" not in value and "\x00" not in value, field + " has an unsafe path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and not re.match(r"^[A-Za-z]:", value),
            field + " must be a relative path")
    require(path.parts and all(part not in {".", ".."} for part in path.parts) and
            path.as_posix() == value, field + " must be a canonical relative path")
    require(not any(part in PRIVATE_DIRECTORIES for part in path.parts),
            field + " must not reference a private or generated directory")
    result = root.joinpath(*path.parts)
    require(result.resolve().is_relative_to(root), field + " escapes the source directory")
    require(not result.is_symlink(), field + " must not be a symlink")
    return result


def load_manifest(root):
    path = root / "skills-manifest.json"
    try:
        manifest = json.loads(read_text(path, "skills-manifest.json"), object_pairs_hook=unique_mapping,
                              parse_constant=lambda _value: (_ for _ in ()).throw(
                                  SuiteError("manifest contains a nonfinite JSON number")))
    except (ValueError, RecursionError) as error:
        if isinstance(error, SuiteError):
            raise
        raise SuiteError("cannot read valid skills-manifest.json") from error
    require(isinstance(manifest, dict) and set(manifest) == MANIFEST_FIELDS,
            "manifest has invalid fields")
    require(type(manifest["version"]) is int and manifest["version"] == 1,
            "manifest version must be 1")
    registrations = manifest["registrations"]
    require(isinstance(registrations, dict) and bool(registrations),
            "registrations must be a nonempty mapping")
    roots = []
    for name, value in registrations.items():
        require(isinstance(name, str) and len(name) <= 64 and NAME.fullmatch(name),
                "registration name is invalid")
        source = relative_path(root, value, "registration source")
        require(source.is_dir(), "registration source directory is missing: " + value)
        require(not any(source == previous or source.is_relative_to(previous) or
                        previous.is_relative_to(source) for previous in roots),
                "registration source directories overlap")
        roots.append(source)
    global_path = relative_path(root, manifest["global_instructions"], "global_instructions")
    require(global_path.is_file() and global_path.suffix.lower() == ".md",
            "global_instructions must reference an existing Markdown file")
    require(bool(read_text(global_path, "global instructions").strip()), "global instructions are empty")
    licenses = manifest["required_licenses"]
    require(isinstance(licenses, list) and bool(licenses), "required_licenses must be a nonempty list")
    seen = set()
    for value in licenses:
        license_path = relative_path(root, value, "required license")
        require(value not in seen, "required_licenses contains a duplicate path")
        seen.add(value)
        require(license_path.is_file(), "required license is missing: " + value)
        require(bool(read_text(license_path, "required license").strip()),
                "required license is empty: " + value)
    policy = relative_path(root, manifest["model_policy"], "model_policy")
    require(policy.is_file() and policy.suffix.lower() in {".yaml", ".yml"},
            "model_policy must reference an existing YAML file")
    require(any(policy.is_relative_to(source) for source in roots),
            "model_policy must be inside a registered skill source")
    return manifest


def ignored_local_artifact_checker(root):
    """Allow disposable caches only in a Git checkout that ignores their contents.

    Exported releases have no Git administrative entry, so they stay strict. Git
    commands here inspect the index and ignore rules without locks or fsmonitor.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    checkout = None

    def git(*arguments):
        try:
            return subprocess.run(
                ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *arguments],
                cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, check=False, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def ignored(path):
        nonlocal checkout
        if checkout is None:
            checkout = False
            if (root / ".git").exists():
                result = git("rev-parse", "--show-toplevel")
                if result is not None and result.returncode == 0:
                    checkout = Path(os.fsdecode(result.stdout).strip()).resolve() == root
        if not checkout:
            return False
        relative = path.relative_to(root).as_posix()
        tracked = git("ls-files", "-z", "--", relative)
        if tracked is None or tracked.returncode != 0 or tracked.stdout:
            return False
        excluded = git("check-ignore", "--quiet", "--no-index", "--", relative)
        return excluded is not None and excluded.returncode == 0

    return ignored


def inspect_tree(root):
    """Do not follow links or inspect the top-level Git administrative directory."""
    files = []
    ignored_local_artifact = ignored_local_artifact_checker(root)

    def walk_error(error):
        raise SuiteError("cannot inspect source tree") from error

    try:
        for directory, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
            parent = Path(directory)
            for name in directories[:]:
                path = parent / name
                display = path.relative_to(root).as_posix()
                require(not path.is_symlink(), "symlink in source tree: " + display)
                if name == ".git":
                    require(parent == root, "nested Git checkout: " + display)
                    directories.remove(name)
                    continue
                if name in LOCAL_ARTIFACT_DIRECTORIES and ignored_local_artifact(path):
                    directories.remove(name)
                    continue
                require(name not in PRIVATE_DIRECTORIES, "private or generated directory: " + display)
            for name in filenames:
                path = parent / name
                display = path.relative_to(root).as_posix()
                require(not path.is_symlink(), "symlink in source tree: " + display)
                if name == ".git":
                    require(parent == root, "nested Git checkout: " + display)
                    continue
                require(name not in PRIVATE_FILES and not name.endswith((".pyc", ".pyo")) and
                        not ((name == ".env" or name.startswith(".env.")) and name not in ENV_TEMPLATES),
                        "private or generated file: " + display)
                require(path.is_file(), "unsupported filesystem entry: " + display)
                files.append(path)
    except OSError as error:
        raise SuiteError("cannot inspect source tree") from error
    return sorted(files)


def skill_frontmatter(root, path):
    display = path.relative_to(root).as_posix()
    lines = read_text(path, display).splitlines()
    require(lines and lines[0] == "---", "missing skill frontmatter: " + display)
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise SuiteError("unterminated skill frontmatter: " + display) from error
    try:
        value = yaml.load("\n".join(lines[1:end]), Loader=FrontmatterLoader)
    except (yaml.YAMLError, TypeError, ValueError, RecursionError) as error:
        raise SuiteError("invalid skill frontmatter: " + display) from error
    require(isinstance(value, dict) and {"name", "description"} <= set(value) and
            set(value) <= SKILL_FIELDS, "invalid skill frontmatter fields: " + display)
    name = value["name"]
    require(isinstance(name, str) and len(name) <= 64 and NAME.fullmatch(name),
            "invalid skill name: " + display)
    require(isinstance(value["description"], str) and bool(value["description"].strip()),
            "invalid skill description: " + display)
    for field in ("license", "compatibility", "allowed-tools"):
        if field in value:
            require(isinstance(value[field], str) and bool(value[field].strip()),
                    "invalid skill " + field + ": " + display)
    if "metadata" in value:
        require(isinstance(value["metadata"], dict) and
                all(isinstance(key, str) for key in value["metadata"]),
                "invalid skill metadata: " + display)
    return name


def prose_only(text):
    """Ignore literal examples, including Go generic calls that resemble links."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    result = []
    fence = None
    list_indent = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        list_marker = re.match(r"^( *)(?:[-+*]|[0-9]+[.)])\s+", line)
        if list_marker:
            list_indent = len(list_marker[1])
        elif line.strip() and not line.startswith((" ", "\t")):
            list_indent = None
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            result.append("\n")
        elif marker:
            fence = marker[1]
            result.append("\n")
        elif line.startswith(("    ", "\t")) and list_indent is None:
            result.append("\n")
        else:
            result.append(line)
    value = "".join(result)
    return re.sub(r"(`+).*?\1", "", value, flags=re.DOTALL)


def inline_destinations(text):
    """Read destinations with balanced parentheses or angle-bracket quoting."""
    for match in re.finditer(r"(?<![\w\\])!?\[", text):
        index = match.end()
        brackets = 1
        while index < len(text) and brackets:
            if text[index] == "\\" and index + 1 < len(text):
                index += 2
                continue
            if text[index] == "[":
                brackets += 1
            elif text[index] == "]":
                brackets -= 1
            index += 1
        if brackets or index >= len(text) or text[index] != "(":
            continue
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "<":
            end = text.find(">", index + 1)
            if end >= 0 and re.match(r"\s*(?:\"[^\"]*\"|'[^']*'|\([^)]*\))?\s*\)", text[end + 1:]):
                yield text[index + 1:end]
            continue
        start, depth = index, 0
        while index < len(text):
            character = text[index]
            if character == "\\" and index + 1 < len(text):
                index += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    yield text[start:index]
                    break
                depth -= 1
            elif character.isspace() and depth == 0:
                if re.match(r"\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\))?\s*\)", text[index:]):
                    yield text[start:index]
                break
            index += 1


def markdown_destinations(text):
    text = prose_only(text)
    yield from inline_destinations(text)
    # Validate definition destinations even when no current paragraph uses them.
    for match in re.finditer(r"^ {0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))", text, re.MULTILINE):
        yield match[1] if match[1] is not None else match[2]


def validate_markdown(root, path):
    display = path.relative_to(root).as_posix()
    text = read_text(path, display)
    parts = path.relative_to(root).parts
    generated_template = any(parts[index:index + 2] == ("assets", "templates")
                             for index in range(len(parts) - 1)) and TEMPLATE_PLACEHOLDER.search(text)
    for destination in markdown_destinations(text):
        destination = re.sub(r"\\([\\`*_{}\[\]()#+.!<> -])", r"\1", destination)
        require(not re.match(r"^[A-Za-z]:[\\/]", destination),
                "nonportable Markdown path: " + display)
        try:
            parsed = urlsplit(destination)
        except ValueError as error:
            raise SuiteError("invalid Markdown destination: " + display) from error
        if parsed.scheme or parsed.netloc:
            require(parsed.scheme.lower() != "file", "nonportable Markdown file URL: " + display)
            continue
        target = unquote(parsed.path)
        if not target:  # Same-document fragments are not filesystem references.
            continue
        require(not target.startswith("/") and "\\" not in target and "\x00" not in target,
                "nonportable Markdown path: " + display)
        require(not any(part in PRIVATE_DIRECTORIES for part in PurePosixPath(target).parts),
                "Markdown reference targets a private or generated directory: " + display)
        resolved = (path.parent / target).resolve()
        require(resolved.is_relative_to(root), "Markdown reference escapes source: " + display)
        # Reusable output templates refer to the consuming project's documents.
        # Their source-relative resource links still need to exist in this suite.
        relative = PurePosixPath(target)
        if generated_template and (TEMPLATE_PLACEHOLDER.search(target) or
                                   (len(relative.parts) == 1 and relative.name in PROJECT_TEMPLATE_DOCUMENTS)):
            continue
        require(resolved.exists(), "missing local Markdown reference: " + display + " -> " + target)


def validate_model_policy(root, manifest):
    policy = relative_path(root, manifest["model_policy"], "model_policy")
    validator = policy.parent / "scripts" / "validate_policy.py"
    require(validator.is_file(), "model policy validator is missing")
    # Execute a freshly loaded module while preventing importlib's bytecode cache.
    # This reuses the maintained policy contract rather than copying its rules.
    try:
        spec = importlib.util.spec_from_file_location("_workflow_suite_model_policy", validator)
        require(spec is not None and spec.loader is not None, "cannot load model policy validator")
        module = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous
        module.load_policy(policy)
    except SuiteError:
        raise
    except (OSError, ImportError, AttributeError, ValueError, TypeError, RecursionError, SyntaxError) as error:
        raise SuiteError("model policy is invalid or its validator cannot load") from error


def validate_suite(root: Path) -> dict:
    """Return a concise report after validating the complete portable source tree."""
    root = Path(root)
    require(not root.is_symlink(), "source directory must not be a symlink")
    root = root.resolve()
    require(root.is_dir(), "source directory does not exist")
    files = inspect_tree(root)
    manifest = load_manifest(root)
    names = {}
    for registration, value in manifest["registrations"].items():
        source = relative_path(root, value, "registration source")
        entrypoints = [path for path in files if path.name == "SKILL.md" and path.is_relative_to(source)]
        require(bool(entrypoints), "registration has no skill entrypoints: " + value)
        for path in entrypoints:
            name = skill_frontmatter(root, path)
            require(name not in names, "duplicate skill name: " + path.relative_to(root).as_posix())
            names[name] = path
            if path == source / "SKILL.md":
                require(name == registration, "registration does not match skill name: " + value)
    markdown = [path for path in files if path.suffix.lower() == ".md"]
    for path in markdown:
        validate_markdown(root, path)
    validate_model_policy(root, manifest)
    return {
        "version": manifest["version"],
        "registrations": dict(manifest["registrations"]),
        "global_instructions": manifest["global_instructions"],
        "model_policy": manifest["model_policy"],
        "skill_count": len(names),
        "markdown_files_checked": len(markdown),
        "required_licenses": len(manifest["required_licenses"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    try:
        report = validate_suite(args.source)
    except SuiteError as error:
        print("Invalid suite: " + str(error), file=sys.stderr)
        return 1
    print("Suite valid: " + str(len(report["registrations"])) + " registrations, " +
          str(report["skill_count"]) + " skills, " + str(report["markdown_files_checked"]) +
          " Markdown files, " + str(report["required_licenses"]) + " required licenses/notices")
    return 0


if __name__ == "__main__":
    sys.exit(main())

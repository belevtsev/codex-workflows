"""Portable suite checks using temporary files; no installed registration changes."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_suite", SOURCE / "scripts" / "validate_suite.py")
SUITE = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "dont_write_bytecode", True):
    spec.loader.exec_module(SUITE)


class SuiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workflow-suite-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = {
            "version": 1,
            "registrations": {"example": "skills/example", "task-orchestration": "skills/task-orchestration"},
            "global_instructions": "global/AGENTS.md",
            "required_licenses": ["LICENSE"],
            "model_policy": "skills/task-orchestration/model-policy.yaml",
        }
        self.write("global/AGENTS.md", "# Working conventions\n\nUse source evidence.\n")
        self.write("LICENSE", "Fixture permission notice.\n")
        self.skill("skills/example", "example")
        self.skill("skills/task-orchestration", "task-orchestration")
        for name in ("model-policy.yaml", "scripts/validate_policy.py", "references/jev-questions.json"):
            source = SOURCE / "skills/task-orchestration" / name
            target = self.root / "skills/task-orchestration" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.write_manifest()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def skill(self, path, name, body="", extra=None):
        fields = {"name": name, "description": "A bounded fixture workflow."}
        if extra:
            fields.update(extra)
        return self.write(path + "/SKILL.md", "---\n" + yaml.safe_dump(fields, sort_keys=False) +
                          "---\n\n# Fixture\n\n" + body)

    def write_manifest(self):
        self.write("skills-manifest.json", json.dumps(self.manifest))

    def assert_invalid(self, pattern):
        with self.assertRaisesRegex(SUITE.SuiteError, pattern):
            SUITE.validate_suite(self.root)

    def git(self, *arguments):
        subprocess.run(["git", *arguments], cwd=self.root, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=True)

    def test_valid_suite_returns_portable_report_and_does_not_write(self):
        before = {path.relative_to(self.root).as_posix(): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        report = SUITE.validate_suite(self.root)
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["registrations"], self.manifest["registrations"])
        self.assertEqual(report["global_instructions"], "global/AGENTS.md")
        self.assertEqual(report["skill_count"], 2)
        self.assertEqual(report["markdown_files_checked"], 3)
        self.assertEqual(report["required_licenses"], 1)
        after = {path.relative_to(self.root).as_posix(): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_bundle_entrypoints_and_vendored_metadata_are_accepted(self):
        self.manifest["registrations"]["bundle"] = "vendor/bundle"
        self.skill("vendor/bundle/skills/nested", "nested", extra={
            "license": "MIT", "allowed-tools": "Read Bash(go:*)", "compatibility": "Codex",
            "metadata": {"version": "1.4.1", "upstream": {"paths": ["**/*.go"], "user-invocable": True}},
        })
        self.write_manifest()
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 3)

    def test_duplicate_skill_names_across_bundle_and_direct_root(self):
        self.manifest["registrations"]["bundle"] = "vendor/bundle"
        self.skill("vendor/bundle/skills/duplicate", "example")
        self.write_manifest()
        self.assert_invalid("duplicate skill name")

    def test_registration_name_must_match_direct_entrypoint(self):
        self.skill("skills/example", "different")
        self.assert_invalid("registration does not match")

    def test_missing_and_malformed_frontmatter(self):
        for content in ("# No frontmatter\n", "---\nname: example\n", "---\n[]\n---\n",
                        "---\nname: example\nname: duplicate\ndescription: text\n---\n",
                        "---\nname: example\ndescription: !!python/object:object {}\n---\n"):
            with self.subTest(content=content):
                self.write("skills/example/SKILL.md", content)
                self.assert_invalid("frontmatter")

    def test_malformed_required_and_optional_fields(self):
        for fields in ({"name": "Bad Name"}, {"description": []}, {"description": "  "},
                       {"metadata": []}, {"license": []}, {"allowed-tools": []}, {"unexpected": True}):
            with self.subTest(fields=fields):
                self.skill("skills/example", "example", extra=fields)
                self.assert_invalid("invalid skill")

    def test_manifest_schema_and_duplicate_keys(self):
        for update in ({"version": True}, {"version": 2}, {"registrations": []},
                       {"required_licenses": []}, {"unexpected": "field"}):
            with self.subTest(update=update):
                manifest = copy.deepcopy(self.manifest)
                manifest.update(update)
                self.write("skills-manifest.json", json.dumps(manifest))
                self.assert_invalid("manifest|registrations|required_licenses")
        self.write("skills-manifest.json", '{"version": 1, "version": 1}')
        self.assert_invalid("duplicate mapping key")

    def test_manifest_paths_cannot_escape_or_use_noncanonical_spelling(self):
        for path in ("../elsewhere", "/tmp/elsewhere", "C:\\private", "skills/../example",
                     "skills//example", "./skills/example", "skills/example/"):
            with self.subTest(path=path):
                self.manifest["registrations"]["example"] = path
                self.write_manifest()
                self.assert_invalid("path")

    def test_missing_and_empty_required_licenses(self):
        (self.root / "LICENSE").unlink()
        self.assert_invalid("required license is missing")
        self.write("LICENSE", " \n")
        self.assert_invalid("required license is empty")

    def test_overlapping_registration_roots(self):
        self.manifest["registrations"]["bundle"] = "skills"
        self.write_manifest()
        self.assert_invalid("overlap")

    def test_empty_registration_is_invalid(self):
        self.manifest["registrations"]["empty"] = "skills/empty"
        (self.root / "skills/empty").mkdir()
        self.write_manifest()
        self.assert_invalid("no skill entrypoints")

    def test_symlink_files_and_directories_are_rejected(self):
        for name, target in (("linked-file", "LICENSE"), ("linked-directory", "skills")):
            with self.subTest(name=name):
                link = self.root / name
                link.symlink_to(self.root / target, target_is_directory=target == "skills")
                self.assert_invalid("symlink")
                link.unlink()

    def test_nested_git_checkouts_are_rejected_but_root_metadata_is_allowed(self):
        (self.root / ".git").mkdir()
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)
        self.write("skills/example/.git", "gitdir: /outside\n")
        self.assert_invalid("nested Git checkout")

    def test_ignored_untracked_local_environments_and_caches_are_allowed(self):
        self.git("init", "--quiet")
        self.write(".gitignore", ".venv/\n__pycache__/\n")
        self.write(".venv/lib/ignored.py", "disposable local environment\n")
        self.write("scripts/__pycache__/helper.pyc", "disposable bytecode\n")
        (self.root / ".venv/python").symlink_to("/outside/local-runtime")
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)

    def test_tracked_artifacts_stay_invalid_even_with_ignore_rules(self):
        self.git("init", "--quiet")
        self.write(".gitignore", ".venv/\n__pycache__/\n")
        for name in (".venv/lib/tracked.py", "scripts/__pycache__/tracked.pyc"):
            with self.subTest(name=name):
                path = self.write(name, "tracked generated artifact\n")
                self.git("add", "--force", "--", name)
                self.assert_invalid("private or generated directory")
                self.git("rm", "--cached", "--force", "--", name)
                path.unlink()

    def test_unignored_local_artifacts_and_exported_archives_stay_invalid(self):
        self.git("init", "--quiet")
        self.write(".venv/lib/local.py", "local environment\n")
        self.assert_invalid("private or generated directory")
        self.write(".gitignore", ".venv/\n")
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)
        shutil.rmtree(self.root / ".git")
        self.assert_invalid("private or generated directory")

    def test_manifest_cannot_reference_ignored_local_artifacts(self):
        self.git("init", "--quiet")
        self.write(".gitignore", ".venv/\n")
        self.write(".venv/LICENSE", "Ignored local notice\n")
        self.manifest["required_licenses"] = [".venv/LICENSE"]
        self.write_manifest()
        self.assert_invalid("must not reference a private or generated directory")

    def test_markdown_cannot_depend_on_ignored_local_artifacts(self):
        self.git("init", "--quiet")
        self.write(".gitignore", ".venv/\n")
        self.write(".venv/local.md", "Ignored local resource\n")
        self.skill("skills/example", "example", body="[Local environment](../../.venv/local.md)")
        self.assert_invalid("Markdown reference targets a private or generated directory")

    def test_private_artifacts_are_rejected_without_echoing_contents(self):
        for name in ("auth.json", "config.toml", ".env", "skills/example/__pycache__/helper.pyc",
                     "private-baseline/SKILL.md"):
            with self.subTest(name=name):
                path = self.write(name, "fixture-secret-that-must-not-appear")
                with self.assertRaises(SUITE.SuiteError) as caught:
                    SUITE.validate_suite(self.root)
                self.assertNotIn("fixture-secret-that-must-not-appear", str(caught.exception))
                path.unlink()
                if name.startswith("skills/example/__pycache__/"):
                    path.parent.rmdir()
                elif name.startswith("private-baseline/"):
                    path.parent.rmdir()

    def test_local_links_accept_shared_repository_paths_and_external_urls(self):
        self.write("docs/shared guide.md", "# Shared guide\n")
        self.write("skills/example/reference.md", "# Local\n")
        self.write("skills/example/local(part).md", "# Balanced path\n")
        self.skill("skills/example", "example", body="""
[local](reference.md#some-heading)
[label [with brackets]](local(part).md)
[shared](<../../docs/shared guide.md> "A title")
[query](reference.md?view=source#anchor)
![image](reference.md)
[external](https://example.invalid/missing)
[mail](mailto:author@example.invalid)
[same document](#heading)
[reference][shared]
- Nested list reference:
    [shared](<../../docs/shared guide.md>)

[shared]: <../../docs/shared guide.md> "A title"
""")
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)

    def test_literal_examples_and_go_generics_are_not_links(self):
        self.skill("skills/example", "example", body="""
`[literal](missing.md)`
```markdown
[example](missing.md)
```
    [indented example](missing.md)
do.Invoke[Database](injector)
<!-- [comment](missing.md) -->
""")
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)

    def test_generated_project_template_links_are_not_suite_resources(self):
        template = "skills/example/assets/templates/README.md"
        self.write(template, "# {project-name}\n\n[License](./LICENSE)\n" +
                   "[Contributing](CONTRIBUTING.md)\n[Generated](docs/{component}.md)\n")
        self.skill("skills/example", "example", body="[Copy template](assets/templates/README.md)")
        self.assertEqual(SUITE.validate_suite(self.root)["skill_count"], 2)
        self.write(template, "# {project-name}\n\n[Missing source resource](../missing.md)\n")
        self.assert_invalid("missing local Markdown reference")

    def test_normal_documentation_cannot_hide_missing_links_as_placeholders(self):
        self.skill("skills/example", "example", body="[Missing resource](references/{missing}.md)")
        self.assert_invalid("missing local Markdown reference")

    def test_comment_examples_do_not_hide_subsequent_live_links(self):
        self.skill("skills/example", "example", body="<!--\n```bash\nignored\n-->\n[Missing](missing.md)")
        self.assert_invalid("missing local Markdown reference")

    def test_missing_inline_image_and_definition_links_are_rejected(self):
        for body in ("[missing](missing.md)", "![missing](missing.png)",
                     "[missing]: missing.md\n"):
            with self.subTest(body=body):
                self.skill("skills/example", "example", body=body)
                self.assert_invalid("missing local Markdown reference")

    def test_escaped_and_absolute_markdown_paths_are_rejected(self):
        for target in ("../../../outside.md", "%2e%2e/%2e%2e/%2e%2e/outside.md",
                       "/Users/someone/private.md", "C:/private.md", "file:///tmp/private.md"):
            with self.subTest(target=target):
                self.skill("skills/example", "example", body="[unsafe](" + target + ")")
                self.assert_invalid("Markdown")

    def test_unsafe_model_policy_is_rejected_using_maintained_validator(self):
        path = self.root / self.manifest["model_policy"]
        policy = yaml.safe_load(path.read_text())
        policy["effort_policy"]["automatic_escalation"] = True
        path.write_text(yaml.safe_dump(policy), encoding="utf-8")
        self.assert_invalid("model policy is invalid")

    def test_missing_policy_validator_is_rejected(self):
        (self.root / "skills/task-orchestration/scripts/validate_policy.py").unlink()
        self.assert_invalid("model policy validator is missing")

    def test_cli_prints_readable_success_and_failure(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(SUITE.main(["--source", str(self.root)]), 0)
        self.assertIn("Suite valid: 2 registrations, 2 skills", output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.write("LICENSE", "")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(SUITE.main(["--source", str(self.root)]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Invalid suite: required license is empty", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

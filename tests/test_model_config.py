"""Keyed TOML ownership uses real temporary files and no user home."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_config


DEFAULTS = {"model": "gpt-6.1-sol", "model_reasoning_effort": "ultra"}


class ModelConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.config = Path(self.temporary.name) / "config.toml"

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, operation):
        data, mode = model_config.render(self.config, operation)
        if data is None:
            self.config.unlink(missing_ok=True)
        else:
            self.config.write_bytes(data)
            self.config.chmod(mode)

    def test_original_representation_comments_modes_tables_and_later_edits_survive(self):
        original = b"# User header\nmodel = 'original' # keep inline\nmodel_reasoning_effort=\"high\"\n\n[profiles.personal]\nmodel = 'profile'\n"
        self.config.write_bytes(original)
        self.config.chmod(0o640)
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.assertIn(b"# keep inline", self.config.read_bytes())
        self.assertIn(b"model_reasoning_effort=\"ultra\"", self.config.read_bytes())
        self.assertIn(b"model = 'profile'", self.config.read_bytes())
        self.config.write_bytes(self.config.read_bytes() + b"other = 'later'\n")
        self.config.chmod(0o604)
        self.write(model_config.removal(self.config, metadata))
        self.assertEqual(self.config.read_bytes(), original + b"other = 'later'\n")
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o604)

    def test_added_keys_removed_and_attached_comments_become_standalone(self):
        self.config.write_bytes(b"# existing\n[profile]\nmodel = 'profile'\n")
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        contents = self.config.read_text()
        contents = contents.replace('model = "gpt-6.1-sol"', 'model = "gpt-6.1-sol" # user explanation')
        self.config.write_text(contents)
        self.write(model_config.removal(self.config, metadata))
        self.assertIn("# user explanation", self.config.read_text())
        self.assertNotIn("gpt-6.1-sol", self.config.read_text())
        self.assertIn("[profile]\nmodel = 'profile'", self.config.read_text())
        model_config.parse(self.config.read_bytes())

    def test_removed_key_preserves_comment_hashes_spacing_and_indentation(self):
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.config.write_text(self.config.read_text().replace('model = "gpt-6.1-sol"', '  model = "gpt-6.1-sol"  ###   User heading'))
        self.write(model_config.removal(self.config, metadata))
        self.assertEqual(self.config.read_bytes(), b"  ###   User heading\n")

    def test_created_file_removed_only_if_no_unrelated_content(self):
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.write(model_config.removal(self.config, metadata))
        self.assertFalse(self.config.exists())
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.config.write_bytes(self.config.read_bytes() + b"# later user note\n")
        self.write(model_config.removal(self.config, metadata))
        self.assertEqual(self.config.read_bytes(), b"# later user note\n")
        self.config.unlink()
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        whitespace = b"\n  \n\t\n"
        self.config.write_bytes(self.config.read_bytes() + whitespace)
        self.write(model_config.removal(self.config, metadata))
        self.assertEqual(self.config.read_bytes(), whitespace)
        self.config.unlink()
        _metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.config.write_bytes(self.config.read_bytes() + whitespace)
        reverse = model_config.reversal(self.config, operation)
        self.write(model_config.pending(self.config, reverse))
        self.assertEqual(self.config.read_bytes(), whitespace)
        self.config.write_bytes(self.config.read_bytes() + b"  \n")
        self.assertIsNone(model_config.pending(self.config, reverse))
        self.assertEqual(self.config.read_bytes(), whitespace + b"  \n")

    def test_unrelated_edit_between_preflight_and_write_survives(self):
        self.config.write_bytes(b"other = 'before'\n")
        _metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.config.write_bytes(b"other = 'changed'\n# added\n")
        self.write(operation)
        self.assertIn(b"other = 'changed'\n# added\n", self.config.read_bytes())

    def test_missing_root_keys_do_not_change_unrelated_table_or_final_newline(self):
        for original in (b"# heading\n[profile]\nmodel = 'profile'\n", b"other='value'", b"# heading without final newline"):
            with self.subTest(original=original):
                self.config.write_bytes(original)
                metadata, operation = model_config.prepare(self.config, DEFAULTS)
                self.write(operation)
                self.write(model_config.removal(self.config, metadata))
                self.assertEqual(self.config.read_bytes(), original)

    def test_changed_owned_value_refuses_before_write(self):
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.config.write_text(self.config.read_text().replace('"ultra"', '"high"'))
        unchanged = self.config.read_bytes()
        with self.assertRaisesRegex(model_config.ModelConfigError, "Owned"):
            model_config.removal(self.config, metadata)
        with self.assertRaisesRegex(model_config.ModelConfigError, "Owned"):
            model_config.reversal(self.config, operation)
        self.assertEqual(self.config.read_bytes(), unchanged)

    def test_malformed_duplicate_and_symlinked_configs_refuse(self):
        for content in (b"x =", b"model = 'a'\nmodel = 'b'\n", b"\xff"):
            self.config.write_bytes(content)
            with self.assertRaisesRegex(model_config.ModelConfigError, "malformed"):
                model_config.prepare(self.config, DEFAULTS)
            self.assertEqual(self.config.read_bytes(), content)
        self.config.unlink()
        other = self.config.parent / "other.toml"
        other.write_bytes(b"# other\n")
        self.config.symlink_to(other)
        with self.assertRaisesRegex(model_config.ModelConfigError, "symlinked"):
            model_config.prepare(self.config, DEFAULTS)
        self.assertEqual(other.read_bytes(), b"# other\n")

    def test_invalid_root_model_types_and_malformed_optional_metadata_refuse(self):
        for content in (b"model = 42\n", b"model_reasoning_effort = true\n", b"[model]\nx=1\n"):
            self.config.write_bytes(content)
            with self.assertRaisesRegex(model_config.ModelConfigError, "strings"):
                model_config.prepare(self.config, DEFAULTS)
            self.assertEqual(self.config.read_bytes(), content)
        self.config.unlink()
        metadata, _operation = model_config.prepare(self.config, DEFAULTS)
        for value in (None, {}, dict(metadata, original_exists="false"), dict(metadata, expected={})):
            with self.assertRaises(model_config.ModelConfigError):
                model_config.validate_metadata(value)

    def test_recovery_and_retry_preserve_two_independent_edits(self):
        self.config.write_bytes(b"model = 'original'\n")
        _metadata, operation = model_config.prepare(self.config, DEFAULTS)
        self.write(operation)
        self.config.write_bytes(self.config.read_bytes() + b"first = 1\n")
        reverse = model_config.reversal(self.config, operation)
        self.config.write_bytes(self.config.read_bytes() + b"second = 2\n")
        self.write(model_config.pending(self.config, reverse))
        self.config.write_bytes(self.config.read_bytes() + b"third = 3\n")
        self.assertIsNone(model_config.pending(self.config, reverse))
        self.assertEqual(self.config.read_bytes(), b"model = 'original'\nfirst = 1\nsecond = 2\nthird = 3\n")

    def test_uninstall_removal_recovery_restores_owned_values_and_keeps_later_edits(self):
        metadata, install = model_config.prepare(self.config, DEFAULTS)
        self.write(install)
        removal = model_config.removal(self.config, metadata)
        self.write(removal)
        self.config.write_bytes(b"other = 'later'\n")
        self.write(model_config.reversal(self.config, removal))
        model_config.verify(self.config, metadata)
        self.assertIn(b"other = 'later'", self.config.read_bytes())

    def test_recovery_keeps_later_file_mode(self):
        self.config.write_bytes(b"model = 'original'\n")
        self.config.chmod(0o640)
        _metadata, install = model_config.prepare(self.config, DEFAULTS)
        self.write(install)
        self.config.chmod(0o604)
        self.write(model_config.reversal(self.config, install))
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o604)

    def test_corrupt_metadata_and_operations_refuse_nonowned_keys(self):
        metadata, operation = model_config.prepare(self.config, DEFAULTS)
        operation["after_keys"]["other"] = {"present": False}
        with self.assertRaisesRegex(model_config.ModelConfigError, "keys"):
            model_config.render(self.config, operation)
        metadata["original"]["model"] = {"present": True, "representation": "'x'\nother='unsafe'"}
        with self.assertRaisesRegex(model_config.ModelConfigError, "representation"):
            model_config.validate_metadata(metadata)


if __name__ == "__main__":
    unittest.main()

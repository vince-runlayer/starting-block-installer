import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('setup_helper', Path(__file__).parents[1] / 'installer/starting_block_setup.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class InstallerTests(unittest.TestCase):
    def test_comment_preservation_and_idempotence(self):
        source = '''{// Keep root\n "servers": { // Keep server\n "other": {"url":"https://other", "headers":{"token":"PRIVATE"}},\n }, "settings": true}\n'''
        status, updated = helper.plan(source, 'servers', 'json')
        self.assertEqual(status, 'missing')
        self.assertIn('// Keep root', updated)
        self.assertIn('// Keep server', updated)
        self.assertIn('"headers":{"token":"PRIVATE"}', updated)
        self.assertEqual(helper.plan(updated, 'servers', 'json'), ('already_configured', None))

    def test_existing_alias_disabled_and_name_conflict(self):
        for name in ('runlayer-plugin', 'my_alias'):
            s = json.dumps({'mcpServers': {name: {'url': helper.URL}}})
            self.assertEqual(helper.plan(s, 'mcpServers', 'json')[0], 'already_configured')
        s = json.dumps({'servers': {'alias': {'url': helper.URL, 'enabled': False}}})
        self.assertEqual(helper.plan(s, 'servers', 'json')[0], 'configured_disabled')
        s = json.dumps({'servers': {helper.NAME: {'url': 'https://other'}}})
        self.assertEqual(helper.plan(s, 'servers', 'json'), ('name_conflict', None))

    def test_toml_keeps_other_settings(self):
        source = '# Preserve me\nmodel = "example"\n[mcp_servers.other]\ncommand = "other"\n'
        _, updated = helper.plan(source, 'mcp_servers', 'toml')
        self.assertIn(source, updated)
        self.assertEqual(helper.plan(updated, 'mcp_servers', 'toml')[0], 'already_configured')

    def test_duplicate_keys_and_malformed_configs_fail_closed(self):
        for source in ('{"servers":{}, "servers":{}}', '{broken', '[]', '{"servers": []}'):
            with self.assertRaises(ValueError):
                helper.plan(source, 'servers', 'json')

    def test_selected_only_read_only_default_backup_and_second_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path, _, _ = helper.path_for('cursor', root, 'darwin')
            path.parent.mkdir()
            source = '{"unrelated": "PRIVATE"}\n'
            path.write_text(source)
            result = helper.configure('cursor', root, 'darwin')
            self.assertEqual(result['status'], 'missing')
            self.assertEqual(path.read_text(), source)
            result = helper.configure('cursor', root, 'darwin', True)
            self.assertEqual(result['status'], 'configured')
            backup = list(path.parent.glob('*starting-block-backup-*'))
            self.assertEqual(len(backup), 1)
            self.assertEqual(backup[0].read_text(), source)
            self.assertEqual(backup[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertFalse((root / '.codex').exists())
            before = path.read_bytes()
            self.assertEqual(helper.configure('cursor', root, 'darwin', True)['status'], 'already_configured')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(path.parent.glob('*starting-block-backup-*'))), 1)

    def test_symlinks_never_written_and_claude_desktop_uses_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            target = root / 'actual'
            target.mkdir()
            (root / '.cursor').symlink_to(target)
            self.assertEqual(helper.configure('cursor', root, 'darwin', True)['status'], 'manual_review')
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(helper.configure('claude_desktop', root, 'darwin', True)['status'], 'ui_check_required')

    def test_quoted_braces_comments_and_empty_objects(self):
        for source in ['{}', '{/*empty*/}', '{"servers": {/*empty*/}}',
                       '{"note":"} {", "servers":{}, "other":{"nested":true}}']:
            _, result = helper.plan(source, 'servers', 'json')
            self.assertEqual(helper.plan(result, 'servers', 'json')[0], 'already_configured')

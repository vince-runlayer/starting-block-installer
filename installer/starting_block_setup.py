# /// script
# requires-python = ">=3.9"
# dependencies = ["json5==0.12.1", "tomlkit==0.13.3"]
# ///
"""Selected-client, user-scope configuration only. Never reads OAuth stores.

Run with uv run starting_block_setup.py --clients codex cursor --apply.
Without --apply this is a read-only plan. Output contains no configuration values.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import json5
import tomlkit

URL = 'https://ecs.prod.runlayer.com/mcp'
# Exact ECS unified dynamic plugin endpoint verified through Runlayer metadata.
# Do not accept arbitrary plugin UUIDs or tenants as equivalent.
ACCEPTED_URLS = {URL, 'https://ecs.prod.runlayer.com/api/v1/proxy/plugins/a9d3ab20-4f5f-4d7b-a7b2-7b2b6f1d0d44/mcp'}
NAME = 'runlayer-plugin'
CLIENTS = ('codex', 'cursor', 'claude_code', 'vscode', 'claude_desktop')
MAX_SIZE = 2_000_000


def path_for(client, home, platform):
    if client == 'codex':
        return home / '.codex/config.toml', 'mcp_servers', 'toml'
    if client == 'cursor':
        return home / '.cursor/mcp.json', 'mcpServers', 'json'
    if client == 'claude_code':
        return home / '.claude.json', 'mcpServers', 'json'
    if client == 'vscode':
        if platform == 'darwin':
            folder = home / 'Library/Application Support/Code/User'
        elif platform == 'win32':
            folder = home / 'AppData/Roaming/Code/User'
        else:
            folder = home / '.config/Code/User'
        return folder / 'mcp.json', 'servers', 'json'
    raise ValueError('unsupported client')


def brace_pairs(text):
    """Locate object boundaries while respecting JSON5 strings and comments."""
    pairs, stack = [], []
    quote = None
    comment = None
    i = 0
    while i < len(text):
        c = text[i]
        nxt = text[i:i+2]
        if comment == 'line':
            if c in '\r\n':
                comment = None
        elif comment == 'block':
            if nxt == '*/':
                comment = None
                i += 1
        elif quote:
            if c == '\\':
                i += 1
            elif c == quote:
                quote = None
        elif nxt in ('//', '/*'):
            comment = 'line' if nxt == '//' else 'block'
            i += 1
        elif c in ('"', "'"):
            quote = c
        elif c == '{':
            stack.append(i)
        elif c == '}':
            if not stack:
                raise ValueError('invalid configuration')
            pairs.append((stack.pop(), i))
        i += 1
    if quote or comment == 'block' or stack:
        raise ValueError('invalid configuration')
    return pairs


def json_insert(text, key, entry):
    """Add one member without rewriting comments, whitespace or other fields."""
    pairs = brace_pairs(text)
    if not pairs:
        raise ValueError('object required')
    root_start, root_end = min(pairs)
    marker = '__starting_block_object_marker__'
    targets = []
    for start, end in pairs:
        if start == root_start:
            continue
        try:
            replaced = json5.loads(text[:start] + json.dumps(marker) + text[end+1:], allow_duplicate_keys=False)
            if replaced.get(key) == marker:
                targets.append((start, end))
        except (ValueError, AttributeError):
            pass
    doc = json5.loads(text, allow_duplicate_keys=False)
    if key in doc:
        if len(targets) != 1 or not isinstance(doc[key], dict):
            raise ValueError('ambiguous server object')
        start, end = targets[0]
        payload = json.dumps(NAME) + ': ' + json.dumps(entry)
    else:
        start, end = root_start, root_end
        payload = json.dumps(key) + ': ' + json.dumps({NAME: entry})
    # Insert first, avoiding ambiguity about trailing commas/comments.
    current = doc[key] if key in doc else doc
    updated = text[:start+1] + '\n  ' + payload + (',' if current else '') + '\n' + text[start+1:]
    parsed = json5.loads(updated, allow_duplicate_keys=False)
    expected = dict(doc)
    expected[key] = dict(doc.get(key, {}), **{NAME: entry})
    if parsed != expected:
        raise ValueError('preservation check failed')
    return updated


def plan(text, key, kind):
    doc = tomlkit.parse(text) if kind == 'toml' else json5.loads(text, allow_duplicate_keys=False)
    if not isinstance(doc, dict):
        raise ValueError('object required')
    servers = doc.get(key, {})
    if not isinstance(servers, dict):
        raise ValueError('invalid server collection')
    matches = [v for v in servers.values() if isinstance(v, dict) and isinstance(v.get('url'), str) and v.get('url') in ACCEPTED_URLS]
    if matches:
        disabled = all(v.get('enabled') is False or v.get('disabled') is True for v in matches)
        return ('configured_disabled' if disabled else 'already_configured'), None
    if NAME in servers:
        return 'name_conflict', None
    entry = {'url': URL}
    if key == 'servers' or key == 'mcpServers':
        entry['type'] = 'http'
    if kind == 'toml':
        if key not in doc:
            doc[key] = tomlkit.table()
        doc[key][NAME] = entry
        updated = tomlkit.dumps(doc)
    else:
        updated = json_insert(text, key, entry)
    return 'missing', updated


def safe_path(path):
    for p in (path, *path.parents):
        if p.is_symlink():
            raise ValueError('symlink configuration requires manual setup')


def configure(client, home, platform, apply=False):
    if client == 'claude_desktop':
        return {'client': client, 'status': 'ui_check_required', 'next': 'Claude: Customize → Connectors → Yours; check runlayer-plugin endpoint, connect only if needed.'}
    path, key, kind = path_for(client, home, platform)
    try:
        safe_path(path)
        before = path.read_bytes() if path.exists() else None
        if before is not None and len(before) > MAX_SIZE:
            raise ValueError('oversize configuration')
        text = before.decode('utf-8') if before is not None else ('' if kind == 'toml' else '{}\n')
        status, updated = plan(text, key, kind)
        if status == 'missing' and apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_path(path)
            # Recheck before backup/write; never overwrite a detected concurrent edit.
            if (path.read_bytes() if path.exists() else None) != before:
                raise ValueError('configuration changed during setup')
            if before is not None:
                fd, backup = tempfile.mkstemp(prefix=path.name+'.starting-block-backup-', dir=path.parent)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(before)
            fd, temporary = tempfile.mkstemp(prefix='.starting-block-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(updated.encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
                if (path.read_bytes() if path.exists() else None) != before:
                    raise ValueError('configuration changed during setup')
                os.replace(temporary, path)
                if path.read_text() != updated:
                    raise ValueError('readback failed')
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            status = 'configured'
        next_action = 'Test in this app; sign in only if prompted.' if status in ('already_configured', 'configured') else 'Review setup status; no connection verified.'
        return {'client': client, 'status': status, 'next': next_action}
    except (ValueError, OSError, UnicodeError):
        # Never expose parser errors: they can contain tokens from the config.
        return {'client': client, 'status': 'manual_review', 'next': 'Configuration could not be safely updated; no credentials were printed.'}


def parse_clients(values):
    clients = [item.strip() for value in values for item in value.split(',') if item.strip()]
    if not clients or any(client not in CLIENTS for client in clients):
        raise ValueError('unsupported client selection')
    return list(dict.fromkeys(clients))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', nargs='+', required=True)
    parser.add_argument('--apply', action='store_true', help='Add missing user-scope configuration, with backups')
    args = parser.parse_args()
    try:
        selected = parse_clients(args.clients)
    except ValueError:
        parser.error('Choose only: ' + ', '.join(CLIENTS))
    # Non-default locations require an explicit adapter rather than writing the wrong profile.
    overrides = {'codex': 'CODEX_HOME', 'vscode': 'VSCODE_PORTABLE', 'claude_code': 'CLAUDE_CONFIG_DIR'}
    results = []
    for client in selected:
        if os.environ.get(overrides.get(client, '__unused_starting_block_override__')):
            results.append({'client': client, 'status': 'custom_location', 'next': 'Use the client-specific guide for your custom configuration location.'})
        else:
            results.append(configure(client, Path.home(), sys.platform, args.apply))
    print(json.dumps({'scope': 'default_user_configuration', 'connectivity_verified': False, 'results': results}, indent=2))


if __name__ == '__main__':
    main()

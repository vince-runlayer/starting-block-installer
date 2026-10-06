# Starting Block installer

Checks only the requested apps and adds the Runlayer-wide MCP endpoint only where it is missing. Configuration is not proof of authentication or a successful MCP call.

## Run

Requires Python 3.9+ and [uv](https://docs.astral.sh/uv/getting-started/installation/). From a downloaded copy:

```sh
uv run --python python3 installer/starting_block_setup.py --clients claude_code codex cursor vscode claude_desktop --apply
```

Omit `--apply` for a read-only plan. Supply only the clients you want. Claude Desktop reports the UI step; its account-managed remote connector is not configured by editing a local file.

## Behavior

- Inspects default user configuration only; it does not inspect OAuth stores, transmit configurations, or call company services.
- Finds the exact endpoint even when an existing entry has a different name.
- Leaves an existing entry untouched. Disabled entries and name collisions need manual review; they are never overwritten.
- Adds only a missing entry. Existing JSON/JSONC comments and TOML settings are preserved. Ambiguous, invalid, duplicate-key and symbolic-link configurations are left for manual review.
- Creates a private backup next to an existing file before writing. Output never includes configuration values, credentials or parser error details.
- Reports configured state separately from authentication. Open each app to test; sign in only when it prompts you.

## Current limits

Only default user locations are supported. Custom Codex/Claude configuration locations and portable VS Code require the app-specific route. Project configuration, named VS Code profiles, IDE disabled-server state, and organization policies can affect whether a configured server is active. The helper does not claim to check these or infer a working connection from a file.

CLI-only, HTTP and plugin-specific legacy endpoints are not assumed equivalent. A same-name entry pointing elsewhere is reported as a conflict, not replaced.

## Tests

```sh
uv run --python python3 --with json5==0.12.1 --with tomlkit==0.13.3 python -m unittest discover -s tests -q
```

Tests use temporary synthetic configurations. Never run integration tests against an employee's live files without their authorization.

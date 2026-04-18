# kb-inbox

Review proposals that the validator chain deferred for human judgment.

## Commands

```bash
octopus-kb inbox --vault . --list --json
octopus-kb inbox --vault . --review <id> --json
octopus-kb inbox --vault . --review <id> --accept
octopus-kb inbox --vault . --review <id> --reject --reason 'out of scope'
```

## Example

`--list` shows:

```json
{"deferred": [{"id": "...", "operations": 2}], "count": 1}
```

Use `--review <id> --accept` to apply after human override.

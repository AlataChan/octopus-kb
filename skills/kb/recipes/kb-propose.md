# kb-propose

Ingest a raw source into the KB via LLM-assisted proposal and rule-gated validation.

## Command

```bash
octopus-kb propose raw/foo.md --vault . --json
```

## Example

Input: A markdown file under `raw/` with some content.

Output:

```json
{"proposal_id": "...", "path": ".octopus-kb/proposals/...", "operations": 3}
```

Then:

```bash
octopus-kb validate .octopus-kb/proposals/<id>.json --vault . --apply
```

# kb-lookup

Resolve a term before creating a page or alias so existing canonical identities are reused.

Command:

```bash
octopus-kb lookup "{term}" --vault . --json
```

Example input:

```text
RAG Ops
```

Output stub:

```json
{
  "term": "RAG Ops",
  "canonical": {"path": "wiki/concepts/RAG Operations.md", "title": "RAG Operations", "source_of_truth": "canonical"},
  "aliases": [{"text": "RAG Ops", "resolves_to": "wiki/concepts/RAG Operations.md"}],
  "ambiguous": false,
  "collisions": [],
  "next": ["octopus-kb retrieve-bundle \"wiki/concepts/RAG Operations.md\" --vault \".\" --json"]
}
```

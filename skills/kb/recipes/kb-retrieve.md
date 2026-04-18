# kb-retrieve

Retrieve the ordered evidence bundle for a task before reading or grepping vault content.

Command:

```bash
octopus-kb retrieve-bundle "{task}" --vault . --json
```

Example input:

```text
Find the canonical page for RAG operations and summarize the relevant context.
```

Output stub:

```json
{
  "query": "RAG operations",
  "bundle": {
    "schema": ["AGENTS.md"],
    "index": ["wiki/INDEX.md"],
    "concepts": [{"path": "wiki/concepts/RAG Operations.md", "title": "RAG Operations", "reason": "title_match"}],
    "entities": [],
    "raw_sources": []
  },
  "warnings": [],
  "token_estimate": 120,
  "next": ["octopus-kb lookup \"RAG operations\" --vault \".\" --json"]
}
```

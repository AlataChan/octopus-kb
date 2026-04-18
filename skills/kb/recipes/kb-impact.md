# kb-impact

Check impacted pages before editing so changes stay consistent with nearby graph context.

Command:

```bash
octopus-kb impacted-pages "{page_path}" --vault . --json
```

Example input:

```text
wiki/concepts/RAG Operations.md
```

Output stub:

```json
{
  "page": "wiki/concepts/RAG Operations.md",
  "impacted": [
    "wiki/concepts/RAG Operations.md",
    "wiki/INDEX.md",
    "wiki/LOG.md"
  ],
  "next": ["octopus-kb neighbors \"wiki/concepts/RAG Operations.md\" --vault \".\" --json"]
}
```

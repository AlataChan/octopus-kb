# Getting Started

1. Place the skills in your agent's skills directory or reference them directly.
2. Point the CLI at an Obsidian vault with markdown pages and YAML frontmatter.
3. Use `octopus-kb lint <vault>` to inspect metadata and graph issues.
4. Use the prompt pack to standardize retrieval and maintenance behavior in your LLM agent.
5. Start from `examples/minimal-vault/` if you want a working graph-shaped seed vault.

## Suggested First Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m octopus_kb_compound.cli lint examples/minimal-vault
python -m octopus_kb_compound.cli suggest-links \
  examples/minimal-vault/wiki/concepts/'RAG and Knowledge Augmentation.md' \
  --vault examples/minimal-vault
```

If you only want a quick smoke check without installing the package:

```bash
PYTHONPATH=src python3 -m octopus_kb_compound.cli --help
```

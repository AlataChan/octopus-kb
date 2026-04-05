# Contributing

## Scope

`octopus-kb-compound` is a framework repo, not a personal vault. Contributions should improve reusable skills, prompts, CLI behavior, or example assets that help other people build durable markdown knowledge bases.

## Preferred Contribution Types

- frontmatter and vault-inspection helpers
- link-suggestion and graph-hygiene improvements
- lint rules that catch structural drift
- prompt-pack improvements grounded in repeatable workflows
- example vault enhancements that make the intended operating model clearer

## Contribution Workflow

1. Open an issue or write down the problem the change is solving.
2. Keep the change small enough to verify with tests or CLI output.
3. Update docs or example assets when behavior changes.
4. Run the verification commands before asking for review.

## Verification

```bash
python3 -m pytest -q
PYTHONPATH=src python3 -m octopus_kb_compound.cli --help
PYTHONPATH=src python3 -m octopus_kb_compound.cli lint examples/minimal-vault
```

## Content Standards

- Use ASCII unless a file already contains non-ASCII content.
- Keep skills concise and trigger-focused.
- Prefer deterministic helpers over vague automation claims.
- Do not add decorative tags or duplicate canonical pages in the example vault.

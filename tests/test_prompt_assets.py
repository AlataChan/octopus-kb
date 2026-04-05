from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_kb_retrieve_skill_exists_and_mentions_retrieval_chain():
    text = (REPO_ROOT / "skills" / "kb-retrieve" / "SKILL.md").read_text(encoding="utf-8")

    assert "schema -> index -> concept -> raw source" in text
    assert "evidence" in text.lower()


def test_kb_maintain_skill_exists_and_mentions_ingest_and_lint():
    text = (REPO_ROOT / "skills" / "kb-maintain" / "SKILL.md").read_text(encoding="utf-8")

    assert "ingest" in text.lower()
    assert "lint" in text.lower()
    assert "wikilink" in text.lower()


def test_obsidian_prompt_pack_contains_linking_policy_and_prompt_files():
    policy = (REPO_ROOT / "prompts" / "obsidian-graph" / "linking-policy.md").read_text(encoding="utf-8")
    retrieve = (REPO_ROOT / "prompts" / "obsidian-graph" / "retrieve.md").read_text(encoding="utf-8")
    maintain = (REPO_ROOT / "prompts" / "obsidian-graph" / "maintain.md").read_text(encoding="utf-8")

    assert "canonical page" in policy.lower()
    assert "avoid overlinking" in policy.lower()
    assert "read schema first" in retrieve.lower()
    assert "update links" in maintain.lower()

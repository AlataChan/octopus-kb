from __future__ import annotations

import builtins
from pathlib import Path
import sys
import types

import pytest

from octopus_kb_compound.cli import main
from octopus_kb_compound.frontmatter import parse_document, render_frontmatter
from octopus_kb_compound.models import PageMeta


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._payload
        return self._payload[:size]

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_extract_title_reads_first_h1() -> None:
    from octopus_kb_compound.ingest import _extract_title

    body = "Intro line\n# Retrieval Augmented Generation Survey\n\nFirst paragraph."

    assert _extract_title(body) == "Retrieval Augmented Generation Survey"


def test_first_paragraph_returns_first_content_block() -> None:
    from octopus_kb_compound.ingest import _first_paragraph

    body = "# Example Source\n\nFirst paragraph.\nStill first paragraph.\n\nSecond paragraph."

    assert _first_paragraph(body) == "First paragraph. Still first paragraph."


def test_first_paragraph_returns_empty_string_for_blank_body() -> None:
    from octopus_kb_compound.ingest import _first_paragraph

    assert _first_paragraph(" \n\n\t") == ""


def test_resolve_unique_path_appends_numeric_suffix(tmp_path: Path) -> None:
    from octopus_kb_compound.ingest import _resolve_unique_path

    (tmp_path / "example-source.md").write_text("existing", encoding="utf-8")

    assert _resolve_unique_path(tmp_path, "example-source") == tmp_path / "example-source-2.md"


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/test.md",
        "ftp://example.com/file.md",
        "http://localhost:8000/page",
        "http://127.0.0.1/page",
        "http://10.0.0.5/page",
        "http://172.16.0.8/page",
        "http://192.168.1.10/page",
    ],
)
def test_validate_url_rejects_non_public_targets(url: str) -> None:
    from octopus_kb_compound.ingest import _validate_url

    with pytest.raises(ValueError):
        _validate_url(url)


def test_render_frontmatter_writes_ingest_provenance_fields() -> None:
    meta = PageMeta(
        title="RAG Survey",
        page_type="raw_source",
        lang="en",
        tags=["rag", "survey"],
        role="raw_source",
        layer="source",
        summary="A survey of retrieval augmented generation.",
        source_url="https://arxiv.org/abs/2312.10997",
        ingest_method="jina-reader",
        fetched_at="2026-04-06T15:30:00+08:00",
    )

    frontmatter = render_frontmatter(meta)
    parsed, _ = parse_document(frontmatter + "\n# Body\n")

    assert 'source_url: "https://arxiv.org/abs/2312.10997"' in frontmatter
    assert 'ingest_method: "jina-reader"' in frontmatter
    assert 'fetched_at: "2026-04-06T15:30:00+08:00"' in frontmatter
    assert parsed["source_url"] == "https://arxiv.org/abs/2312.10997"
    assert parsed["ingest_method"] == "jina-reader"
    assert parsed["fetched_at"] == "2026-04-06T15:30:00+08:00"


def test_generate_raw_page_writes_parseable_document(tmp_path: Path) -> None:
    from octopus_kb_compound.ingest import generate_raw_page

    raw_dir = tmp_path / "raw"
    metadata = {
        "title": "Example Source",
        "source_url": "https://example.com/articles/rag",
        "ingest_method": "jina-reader",
        "fetched_at": "2026-04-06T15:30:00+08:00",
    }

    output_path = generate_raw_page(
        "# Example Source\n\nThis source explains retrieval augmented generation.\n",
        metadata,
        raw_dir,
        lang="en",
        tags=["rag"],
    )

    raw = output_path.read_text(encoding="utf-8")
    frontmatter, body = parse_document(raw)

    assert output_path == raw_dir / "example-source.md"
    assert frontmatter["title"] == "Example Source"
    assert frontmatter["type"] == "raw_source"
    assert frontmatter["role"] == "raw_source"
    assert frontmatter["layer"] == "source"
    assert frontmatter["tags"] == ["rag"]
    assert frontmatter["source_url"] == "https://example.com/articles/rag"
    assert frontmatter["ingest_method"] == "jina-reader"
    assert frontmatter["summary"] == "This source explains retrieval augmented generation."
    assert body.startswith("# Example Source")


def test_fetch_url_as_markdown_uses_jina_reader_and_slug_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from octopus_kb_compound import ingest

    calls: dict[str, object] = {}

    def fake_urlopen(request, timeout: int = 30):
        calls["url"] = request.full_url
        calls["timeout"] = timeout
        calls["accept"] = request.get_header("Accept")
        return _FakeResponse(b"Paragraph without heading.\n")

    monkeypatch.setattr(ingest.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ingest, "_now_iso", lambda: "2026-04-06T15:30:00+08:00")

    body, metadata = ingest.fetch_url_as_markdown("https://example.com/articles/rag-survey", timeout=12)

    assert body == "Paragraph without heading.\n"
    assert metadata["title"] == "example-com-articles-rag-survey"
    assert metadata["source_url"] == "https://example.com/articles/rag-survey"
    assert metadata["ingest_method"] == "jina-reader"
    assert metadata["fetched_at"] == "2026-04-06T15:30:00+08:00"
    assert calls["url"] == "https://r.jina.ai/https://example.com/articles/rag-survey"
    assert calls["timeout"] == 12
    assert calls["accept"] == "text/markdown"


def test_cli_ingest_url_writes_raw_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from octopus_kb_compound import ingest

    vault = tmp_path / "vault"
    vault.mkdir()

    def fake_fetch(url: str, *, timeout: int = 30):
        assert url == "https://example.com/rag"
        assert timeout == 30
        return (
            "# Example Source\n\nThis source explains retrieval augmented generation.\n",
            {
                "title": "Example Source",
                "source_url": url,
                "ingest_method": "jina-reader",
                "fetched_at": "2026-04-06T15:30:00+08:00",
            },
        )

    monkeypatch.setattr(ingest, "fetch_url_as_markdown", fake_fetch)

    exit_code = main(
        [
            "ingest-url",
            "https://example.com/rag",
            "--vault",
            str(vault),
            "--tags",
            "rag,survey",
            "--lang",
            "en",
        ]
    )

    captured = capsys.readouterr()
    output_path = vault / "raw" / "example-source.md"

    assert exit_code == 0
    assert str(output_path) in captured.out
    assert output_path.exists()


def test_convert_file_to_markdown_uses_markitdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from octopus_kb_compound import ingest

    source_file = tmp_path / "Q3-report.pdf"
    source_file.write_text("ignored", encoding="utf-8")
    calls: dict[str, object] = {}

    fake_module = types.ModuleType("markitdown")

    class FakeMarkItDown:
        def convert(self, file_path: str):
            calls["file_path"] = file_path
            return types.SimpleNamespace(text_content="Converted body without heading.\n")

    fake_module.MarkItDown = FakeMarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake_module)
    monkeypatch.setattr(ingest, "_now_iso", lambda: "2026-04-06T16:30:00+08:00")

    body, metadata = ingest.convert_file_to_markdown(str(source_file))

    assert body == "Converted body without heading.\n"
    assert calls["file_path"] == str(source_file)
    assert metadata == {
        "source_file": "Q3-report.pdf",
        "original_format": "pdf",
        "converted_at": "2026-04-06T16:30:00+08:00",
        "ingest_method": "markitdown",
        "title": "Q3-report",
    }


def test_convert_file_to_markdown_raises_without_markitdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from octopus_kb_compound import ingest

    source_file = tmp_path / "report.pdf"
    source_file.write_text("ignored", encoding="utf-8")

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "markitdown":
            raise ImportError("No module named 'markitdown'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "markitdown", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match=r"pip install octopus-kb-compound\[ingest\]"):
        ingest.convert_file_to_markdown(str(source_file))


def test_cli_ingest_file_writes_raw_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from octopus_kb_compound import ingest

    vault = tmp_path / "vault"
    vault.mkdir()
    source_file = tmp_path / "report.pdf"
    source_file.write_text("ignored", encoding="utf-8")

    def fake_convert(file_path: str):
        assert file_path == str(source_file)
        return (
            "# Q3 Research Report\n\nThird-quarter architecture review.\n",
            {
                "title": "Q3 Research Report",
                "source_file": "report.pdf",
                "original_format": "pdf",
                "converted_at": "2026-04-06T16:30:00+08:00",
                "ingest_method": "markitdown",
            },
        )

    monkeypatch.setattr(ingest, "convert_file_to_markdown", fake_convert)

    exit_code = main(
        [
            "ingest-file",
            str(source_file),
            "--vault",
            str(vault),
            "--tags",
            "report,quarterly",
            "--lang",
            "zh",
        ]
    )

    captured = capsys.readouterr()
    output_path = vault / "raw" / "q3-research-report.md"
    raw = output_path.read_text(encoding="utf-8")
    frontmatter, body = parse_document(raw)

    assert exit_code == 0
    assert str(output_path) in captured.out
    assert frontmatter["source_file"] == "report.pdf"
    assert frontmatter["original_format"] == "pdf"
    assert frontmatter["ingest_method"] == "markitdown"
    assert frontmatter["summary"] == "Third-quarter architecture review."
    assert body.startswith("# Q3 Research Report")

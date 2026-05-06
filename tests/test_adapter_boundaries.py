from __future__ import annotations


def test_read_flows_do_not_import_vault_scanner_directly():
    import octopus_kb_compound.impact as impact
    import octopus_kb_compound.lookup as lookup
    import octopus_kb_compound.neighbors as neighbors
    import octopus_kb_compound.retrieve as retrieve

    assert not hasattr(lookup, "scan_markdown_files")
    assert not hasattr(neighbors, "scan_markdown_files")
    assert not hasattr(impact, "scan_markdown_files")
    assert not hasattr(impact, "load_page")
    assert not hasattr(retrieve, "scan_markdown_files")


def test_lint_layers_are_exposed():
    from octopus_kb_compound.adapters.obsidian.lint_obsidian import lint_obsidian_pages
    from octopus_kb_compound.ckr.lint import lint_ckr_pages

    assert callable(lint_ckr_pages)
    assert callable(lint_obsidian_pages)


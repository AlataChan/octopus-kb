"""Snapshot of octopus-kb MCP tool names and signatures."""

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "octopus_kb_mcp" / "server.py"
SNAPSHOT = Path(__file__).parent / "fixtures" / "mcp_tool_signatures.json"


def tool_signatures(source: str) -> dict:
    tree = ast.parse(source)
    tools = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not _is_mcp_tool(node):
            continue
        padding = [None] * (len(node.args.args) - len(node.args.defaults))
        parameters = []
        for arg, default in zip(node.args.args, padding + node.args.defaults):
            parameters.append(
                {
                    "name": arg.arg,
                    "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
                    "default": None if default is None else ast.unparse(default),
                }
            )
        tools[node.name] = {
            "parameters": parameters,
            "returns": ast.unparse(node.returns) if node.returns else None,
        }
    return tools


def _is_mcp_tool(node: ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
        ):
            return True
    return False


def test_mcp_tool_names_and_signatures_match_the_snapshot():
    current = tool_signatures(SERVER.read_text(encoding="utf-8"))
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert list(current) == [
        "kb_export_graph",
        "kb_retrieve_bundle",
        "kb_ingest",
        "kb_neighbors",
        "kb_lookup",
        "kb_propose",
        "kb_validate",
    ]
    assert current == expected

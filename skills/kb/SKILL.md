---
name: kb
description: Operating procedure for octopus-kb knowledge bases. Use this skill EVERY TIME you are asked to find, edit, or explain information in a vault under `wiki/` or `raw/`. Grep is forbidden until you have run retrieve-bundle.
---

# Operating Procedure

## 0. 执行前预检

执行任何知识库操作前，先读取并遵循[统一预检规则](references/runtime-preflight.md)。
即使本技能被单独调用，也必须先确定工具调用方式与知识库路径。
同一任务中已有有效验证记录时直接复用；下文的 `octopus-kb` 均替换为已验证的调用前缀，
命令工作目录使用知识库绝对路径，不假定全局安装、当前目录或激活状态。

## Workflow

1. Before any Grep or Read on `wiki/` or `raw/`, run:
   `octopus-kb retrieve-bundle "{task}" --vault . --json`
   Read pages in the returned order: schema → index → concepts → entities → raw_sources. Stop when you have enough context.

2. Before creating a new page or alias, run:
   `octopus-kb lookup "{term}" --vault . --json`
   If `canonical` is non-null and `ambiguous` is false, reuse that page.

3. Before editing an existing page, run:
   `octopus-kb impacted-pages "{page_path}" --vault . --json`
   Your edit must stay consistent with the returned impacted set.

4. To understand a page's graph context, run:
   `octopus-kb neighbors "{page_path}" --vault . --json`

5. To lint before finishing, run:
   `octopus-kb lint . --json`
   Fix every `DUPLICATE_CANONICAL_PAGE`, `CANONICAL_ALIAS_COLLISION`, `SCHEMA_INVALID_FIELD`, and `SCHEMA_MISSING_FIELD`.

6. To ingest a raw source into the KB:
   `octopus-kb propose raw/<file> --vault . --json`
   `octopus-kb validate .octopus-kb/proposals/<id>.json --vault . --apply --json`

7. At least weekly, triage deferred proposals:
   `octopus-kb inbox --vault . --list --json`
   `octopus-kb inbox --vault . --review <id> [--accept | --reject --reason "..."] --json`

8. If a `validate --apply` run is interrupted, recover before retrying:
   `octopus-kb recover <proposal_id> --vault .`

## Forbidden

- Grep on `wiki/**` or `raw/**` without first running `retrieve-bundle`.
- Creating a concept page without first running `lookup`.
- Editing a page without first running `impacted-pages`.
- Pasting raw page bodies into prompts. Use `retrieve-bundle` JSON output.

## Why

Grep finds strings. `retrieve-bundle` finds decisions. A 3MB vault returns 200 grep matches; `retrieve-bundle` returns the 5 pages that matter. Skipping step 1 means re-learning the vault every turn.

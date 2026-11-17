# Getting Started

1. Place the skills in your agent's skills directory or reference them directly.
2. Point the CLI at an Obsidian vault with markdown pages and YAML frontmatter.
3. Use `octopus-kb lint <vault>` to inspect metadata and graph issues.
4. Use the prompt pack to standardize retrieval and maintenance behavior in your LLM agent.
5. Start from `examples/minimal-vault/` if you want a working graph-shaped seed vault.
6. Use `scripts/bootstrap_vault.py` if you want to adopt the framework in an existing vault.
7. Use `examples/expanded-vault/` when you need concept, entity, comparison, timeline, log, migration, and export examples in one place.

四个技能都从执行前预检开始，规则位于各自的 `references/runtime-preflight.md`。
安装或复制技能时，应保留完整技能目录，包括 `references/`，不能只复制 `SKILL.md`。
预检会验证命令是否能运行，必要时使用源码后备入口，并分别记录工具位置与知识库路径。
这是 Agent 应遵循的使用规则，不是加载技能时自动执行的安装钩子；预检本身不会安装依赖。

## Suggested First Run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m octopus_kb_compound.cli lint examples/minimal-vault
python -m octopus_kb_compound.cli vault-summary examples/expanded-vault
python -m octopus_kb_compound.cli plan-maintenance \
  examples/expanded-vault/raw/rag-operations-source.md \
  --vault examples/expanded-vault
python -m octopus_kb_compound.cli export-graph examples/expanded-vault --out /tmp/octopus-expanded-export
python -m octopus_kb_compound.cli suggest-links \
  examples/minimal-vault/wiki/concepts/'RAG and Knowledge Augmentation.md' \
  --vault examples/minimal-vault
```

If you only want a quick smoke check without installing the package:

```bash
PYTHONPATH=src python3 -m octopus_kb_compound.cli --help
```

This source-mode check still requires the dependencies in `pyproject.toml`.
If that interpreter reports `No module named yaml`, use an environment with
the declared dependencies installed. `PYTHONPATH` locates the source package;
it does not install dependencies. A system Python is not inherently unsupported.

## 仓库移动或改名后的环境检查

虚拟环境包含绝对路径。移动仓库后，旧的命令入口、激活脚本和可编辑安装
记录可能仍指向原目录；这不表示现有依赖都已损坏。先在仓库根目录检查：

```bash
./.venv/bin/python -c "import yaml; import octopus_kb_compound; print(octopus_kb_compound.__file__)"
./.venv/bin/octopus-kb --help
```

如果解释器及依赖可用，只有包路径失效，可以临时使用源码入口：

```bash
PYTHONPATH="$PWD/src" ./.venv/bin/python -m octopus_kb_compound.cli --help
```

修复时，用与原环境兼容的 Python 版本重新生成环境入口，再重新安装项目。
以下操作保留现有环境目录，不使用 `--clear`。原环境若启用了
`include-system-site-packages = true`，创建环境时也应保留
`--system-site-packages`，否则原先可用的共享依赖会变得不可见。

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
source .venv/bin/activate
octopus-kb --help
python -c "import octopus_kb_compound; print(octopus_kb_compound.__file__)"
```

使用 `python -m pip`，避免调用仍带旧路径的 `pip` 包装脚本。
重新安装项目会修复项目的命令入口与可编辑安装记录；其他依赖若也有旧的
命令入口，需要分别重新生成或重新安装对应包。仅设置 `PYTHONPATH` 不会
修复激活脚本或这些命令入口。环境通常不应在不同路径之间直接复制使用。

## 自动化调用的结果判断

- `retrieve-bundle` 若无法写入检索标记，会在标准错误输出中打印
  `warning: could not touch retrieve-bundle marker`；检索成功时标准输出仍是
  正常结果，退出码为 `0`。不要只因标准错误输出非空而重试。
- `validate` 不加 `--apply`，也可能将拒绝或待复核结果写入
  `.octopus-kb/rejections/` 或 `.octopus-kb/inbox/`；它不是完全只读的预览。
- 应用变更中断且留下 `pending` 审计记录时，先执行 `recover`，再按返回
  状态安排后续操作；恢复后的原提案会被标记为已回滚，不能直接重复应用。

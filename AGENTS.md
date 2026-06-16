# AGENTS.md

## 约束

- **必须使用 `uv` 运行项目中的 Python 脚本**：`uv run python $SKILL_DIR/scripts/<script>.py`
- **不要安装或修改本地的 skill**：本仓库是 skill 源码，不要执行 `npx skills add` 等安装操作
- **不要自动修改 version 或提交 commit**：版本号和 git 操作需要用户明确指示
- **遇到缺失工具/包/字体不得自动安装**：必须先列出安装命令，等待用户确认
- **所有翻译工作在 `/tmp/latex-translate-<id>/` 中进行**：绝不修改原始源文件
- **本项目没有测试/lint/CI 命令**：不要尝试运行 pytest、ruff、mypy 等

## 常用命令

| 命令 | 用途 |
|------|------|
| `uv run python scripts/compile.py --check-tools` | 检测工具链 |
| `uv run python scripts/extract_blocks.py -d <dir> -o blocks.json` | 提取翻译块 |
| `uv run python scripts/backfill_blocks.py -d <dir> -t translations.json` | 回填译文 |
| `uv run python scripts/compile.py -d <zh_dir>` | 编译中文 PDF |
| `uv run python scripts/latex_compat_scan.py <dir>` | 中文兼容性扫描 |
| `uv run python scripts/match_cjk_font.py <main.tex>` | 字体风格匹配 |
| `uv run python scripts/compute_baselineskip.py <main.tex>` | 行距计算 |
| `uv run python scripts/check_cjk_variants.py <font>` | 粗斜体检查 |

## 结构

```
SKILL.md          # Agent 工作流指令（主规范）
scripts/
  compile.py      # XeLaTeX 编译
  extract_blocks.py   # 解析 .tex 提取翻译块
  backfill_blocks.py  # 回填译文（ThreadPoolExecutor 并行写入）
  latex_compat_scan.py # 中文兼容性预检
  grade_assertions.py  # 评估断言
  match_cjk_font.py    # 字体风格匹配
  compute_baselineskip.py  # 行距计算
  check_cjk_variants.py    # 粗斜体检查
```

## 注意事项

- `pyproject.toml` 没有 `[build-system]`，**不能作为包安装**，脚本直接通过路径调用
- `compile.py` 默认禁用 shell escape，`--shell-escape` 需要 `--trusted-source`
- `backfill_blocks.py` 跳过歧义匹配（原文出现多次），按长度排序避免部分匹配
- 远程仓库：`git@github.com:Wishrem/latex-translate-zh.git`，分支 `main`

## Commit 规范

```
type: 中文简述

英文补充说明（可选单行）。
Bump version to X.Y.Z（如涉及版本号变更）。
```

- `type`：`feat` / `fix` / `docs` / `refactor` / `chore`
- 标题一行、中文简述；详情最多 2-3 行英文，不用 bullet list

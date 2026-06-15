# latex-translate-zh

将 LaTeX 论文翻译成中文并编译 PDF —— AI Agent 技能。

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **当前测试状态**：OpenCode + Deepseek V4 Flash ✅，其他平台兼容性待验证。欢迎反馈。

## 为什么比网页翻译/PDF 翻译更好？

| 方式 | 公式 | 排版 | 交叉引用 | 图表标题 |
|------|:----:|:----:|:--------:|:--------:|
| arxiv 网页 + 翻译插件 | 错位/丢失 | 无 | 断裂 | 混在正文中 |
| PDF 提取翻译 | 乱码/图片 | 丢失结构 | 号对不上 | 图层分离 |
| **latex-translate-zh** | 对齐 | 保持 | 有效 | 原位替换 |

- **arxiv 网页翻译**：公式渲染成 MathJax 后被翻译破坏，`\cite` 变乱码，图表标题混入正文无法区分
- **PDF 翻译**：提取文字丢失 LaTeX 结构，数学符号变 `?`，引用编号错乱，编译后布局变形
- **latex-translate-zh**：直接在 `.tex` 源码层翻译后编译 —— 数学公式原样渲染、引用编号不变、图表标题位置精准、编排格式与原文一致，拿到的是**可打印的高保真中文 PDF**

## 按论文自然结构翻译

一篇论文的正文不是一整块连续文字——它由摘要、章节、小节、段落、图题、表题等结构单元组成。大多数翻译工具要么把整篇论文当一坨文本丢进去（上下文断裂），要么逐句翻译（丢失段落语义）。

**latex-translate-zh 的翻译块（Translation Block）设计参考了这个论文写作过程**：

- `\section{...}` → 一节标题，一个翻译块
- 连续几个展开同一主题的段落 → 一个翻译块（不会把"问题→分析→结论"拆成三句零散的话）
- `\caption{...}` → 图题/表题一个翻译块，独立于正文（因为caption 通常都是对图片进行描述）
- 公式前后的解释文字 → 和公式保持在同一块，翻译时能看见数学上下文

通过理解文档结构后按**语义完整单元**切分——这恰好也是译者在翻译论文时心里划的分段界限。

### 术语处理

学术论文中术语密度高，同一概念在不同段落反复出现。如果每次遇到都重新翻译，结果必然是"embedding"在第一章叫"嵌入"、第三章又叫"词向量"。

本技能在翻译前先扫描全文建立**术语表**，确保全文译法统一：

| 处理策略 | 示例 |
|----------|------|
| 缩写保留 | CNN、LLM、GPU、MAH 不翻译 |
| 技术名词保留英文 | Transformer（不是"变压器"）、PyTorch、CUDA |
| 人名不翻译 | Hinton、Vaswani、LeCun 不音译 |
| 首次出现括号注原文 | 多头注意力（Multi-head Attention），后续只用"多头注意力" |
| 全文一致 | 同一个 `\emph{overfitting}` 全文译法相同 |

这些规则不在 prompt 里写死让模型"尽量做到"——而是先执行扫描，生成术语表，翻译时作为硬约束传给每个翻译 subagent。

## 功能

输入 arxiv 链接、下载地址或本地 LaTeX 项目目录，此技能自动：

1. **提取可翻译文本块** — 解析 `.tex` 文件，保留 LaTeX 命令、数学公式、引用文献
2. **翻译为中文** — 术语一致，多文件项目用 subagent 并行翻译
3. **回填译文** — 并行写入，不改变任何文件结构和路径
4. **编译中文 PDF** — XeLaTeX + latexmk，自动处理 CJK 字体
5. **输出 PDF** — 复制到当前工作目录

**不修改原始文件**，翻译在沙箱工作副本中完成。

## 快速开始

```bash
npx skills add Wishrem/latex-translate-zh
```

在 agent 中说：

> 翻译这篇 arxiv 论文: https://arxiv.org/abs/1706.03762

或：

> 把 ~/papers/my-paper/ 里的 LaTeX 论文翻译成中文

## 环境要求

- **Python 3.10+** + `uv`
- **XeLaTeX** + **latexmk** + **bibtex** (TeX Live 或 MiKTeX)
- 至少一种中文字体 (Noto Serif CJK SC / Noto Sans CJK SC / WenQuanYi 等)

工具链检测会自动识别操作系统，通过 Web 搜索给出~~可能~~正确的安装命令。

## 项目结构

```
latex-translate-zh/
├── SKILL.md                  # 技能指令（agent 执行的规则）
└── scripts/                  # Python 辅助脚本
    ├── compile.py            # LaTeX 编译（latexmk + XeLaTeX）
    ├── extract_blocks.py     # 提取可翻译文本块
    ├── backfill_blocks.py    # 回填译文（并行写入）
    ├── latex_compat_scan.py  # 中文兼容性扫描
    └── grade_assertions.py   # 评估断言检查
```

## 翻译流程

### 提取 → 翻译 → 回填

1. **提取**: `extract_blocks.py` 解析 `.tex` 文件，输出 `blocks.json` — 包含精确源码位置的可翻译文本片段列表。自动跳过数学公式、引用、图表、参考文献。

2. **翻译**: Agent 翻译每个 block 的 `source_text` 字段。多文件项目按文件并行翻译。

3. **回填**: `backfill_blocks.py` 使用精确字符串匹配将译文写回工作副本，多文件用 `ThreadPoolExecutor` 并行写入。

## License

MIT — 详见 [LICENSE](LICENSE)。

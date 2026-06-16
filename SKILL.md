---
name: latex-translate-zh
description: >-
  LaTeX论文翻译成中文并编译PDF。用于arxiv论文翻译、英文LaTeX论文转中文版、
  学术论文中文翻译编译。触发于"翻译LaTeX论文""翻译这篇论文""arxiv翻译"
  "把论文翻译成中文""latex论文翻译""翻译并编译latex"等请求。
  Also for translating LaTeX papers to Chinese: "translate this paper to Chinese",
  "Chinese translation of arxiv paper", "translate latex paper".
metadata:
  category: academic-writing
  tags: [latex, translation, chinese, arxiv, xelatex, pdf, paper]
  version: "0.2.0"
  last_updated: "2026-06-16"
allowed-tools: Read, Glob, Grep, Bash, Write, Edit
---

# LaTeX论文翻译与中文编译

将英文LaTeX论文按翻译块维度翻译为中文，并编译输出中文PDF。

## 总体流程

**全局规则**：任何时候遇到缺失工具、缺失LaTeX包、缺失字体等，**不得自行执行安装命令**。必须先列出缺失项和安装命令，询问用户确认后再执行。无 sudo 权限时尤其不能静默跳过，必须明确告知用户手动安装。

0. **工具链与字体检测** — 检查编译工具和中文字体是否就绪，缺失则询问用户
1. **获取源文件** — 下载/拷贝 LaTeX 源码到 `/tmp/latex-translate-<id>/`
2. **结构分析** — 判定单文件/多文件，决定并行或串行翻译策略
2.5. **基线编译与兼容扫描** — 编译原始英文版，扫描中文兼容风险（fragile macro、负间距等）
3. **块级翻译** — 提取翻译块 → 翻译 → 回填，多文件时并行加速
4. **中文排版调优** — 字体匹配、行距计算、字号调节、粗斜体检查
   4.1 字体选型 — 用 match_cjk_font.py 根据拉丁字体风格匹配中文字体
   4.2 行距计算 — 用 compute_baselineskip.py 计算最佳 baselineskip
   4.3 字号调节 — CJK 字体默认比英文放大 1pt（Scale=1.1）
   4.4 粗斜体检查 — 用 check_cjk_variants.py 检查 Bold/Italic，生成 fallback
   4.5 注入配置 — 将 4.1-4.4 的产出写入 main.tex
5. **编译与兼容修复** — 编译并自动修复中文兼容问题
5.5. **PDF验收** — 多遍编译后检查交叉引用、排版和日志
6. **输出** — 将验收通过的 PDF 复制到当前目录

---

## Step 0: 工具链与字体检测（最先执行）

在开始翻译前，先检测编译工具链：

```bash
uv run python $SKILL_DIR/scripts/compile.py --check-tools
```

脚本输出：
- 操作系统和包管理器类型（apt/pacman/dnf/brew/winget）
- 编译引擎（xelatex/xetex/lualatex/luatex/pdflatex）和构建工具（latexmk/bibtex/biber）的可用状态
- 推荐中文字体（Noto Serif CJK SC, Noto Sans CJK SC, WenQuanYi 等）的安装状态
- 缺失工具/字体列表 + JSON结构化数据（供程序化处理）
- **不会输出硬编码的包名**——包名随时间变化，必须实时搜索确认

**如果检测到工具缺失**，**禁止自行执行安装命令**，执行以下步骤：

1. 解析脚本输出的 `[TOOLS_JSON]` 行中的 `search_query` 字段
2. 使用 WebFetch 搜索正确的包名（如 `install latexmk biber on Linux pacman`）
3. 将缺失工具和安装命令呈现给用户，**等待用户明确确认**：

```
检测到以下工具缺失：
  - latexmk → 安装: sudo pacman -S texlive-binextra
  - biber   → 安装: sudo pacman -S biber

是否需要我执行安装？[y/n]
```

4. 用户回复 y/yes 后才执行安装命令。用户回复 n/no 或未确认时不能执行
5. 如无 sudo 权限导致安装失败，向用户说明并提供手动安装命令

**工具说明：**

| 工具 | 必需 | 用途 |
|------|------|------|
| `xelatex` | **必需** | 中文编译（基于 xetex 引擎的 LaTeX 格式） |
| `xetex` | **必需** | XeTeX 基础引擎，xelatex 的底层依赖 |
| `bibtex` | **必需** | 参考文献处理 |
| `latexmk` | **必需** | 自动多遍编译，处理交叉引用/参考文献 |
| `lualatex` | 可选 | LuaLaTeX 备选引擎 |
| `luatex` | 可选 | LuaTeX 基础引擎 |
| `biber` | 可选 | 现代 biblatex 参考文献处理 |

**中文字体：** 至少需要一种中文字体（如 Noto Serif CJK SC、Noto Sans CJK SC、WenQuanYi 等），编译才能正常输出中文。脚本会自动检测推荐字体的安装状态。

---

## Step 1: 获取源文件

### 工作目录预检（最先执行）

在获取源文件前，先检查工作目录是否已存在：

```bash
ls /tmp/latex-translate-<id> 2>/dev/null && echo "EXISTS" || echo "FREE"
```

如果目录已存在（输出 `EXISTS`），不得自动删除或覆盖。必须提示用户：

```
工作目录 /tmp/latex-translate-<id> 已存在（可能是之前的翻译任务残留）。

请手动删除后再继续：
  rm -rf /tmp/latex-translate-<id>

是否已删除？[y/n]
```

用户确认后才能继续。

### Arxiv论文
```
arxiv URL: https://arxiv.org/abs/XXXX.XXXXX
源码下载: https://arxiv.org/e-print/XXXX.XXXXX
```

```bash
mkdir -p /tmp/latex-translate-<arxiv-id>
wget -O /tmp/latex-translate-<arxiv-id>/source.tar.gz "https://arxiv.org/e-print/XXXX.XXXXX"
tar -xzf /tmp/latex-translate-<arxiv-id>/source.tar.gz -C /tmp/latex-translate-<arxiv-id>/
# 如果有 .tar.gz 嵌套（arxiv有时双重打包）继续解压
```

解压后查找主文件 `main.tex` 或 `paper.tex`。

### 通用下载网址
```bash
mkdir -p /tmp/latex-translate-<name>
wget -O /tmp/latex-translate-<name>/source.<ext> "<URL>"
# 如需解压: tar -xzf /tmp/latex-translate-<name>/source.<ext> -C /tmp/latex-translate-<name>/
```

### 本地目录
```bash
cp -r /path/to/latex/project /tmp/latex-translate-<name>/
```

**注意**：所有工作在 `/tmp/latex-translate-<id>/` 下进行，不修改原始文件。原始项目作为只读基线保存。

### 创建中文工作目录

获取源文件后，创建完整的中文工作副本：

```bash
# 原始项目只读保存
# 复制整个项目到中文工作目录
cp -r /tmp/latex-translate-<id>/source /tmp/latex-translate-<id>/work_zh/
```

中文工作目录必须保持：
- 所有文件名不变
- 目录结构不变
- `\input{}`、`\include{}` 路径不变
- `\includegraphics{}` 路径不变
- `\bibliography{}` 路径不变
- `\label{}`、`\ref{}`、`\cite{}` 不变
- `figure`/`table` 环境结构不变

只替换正文文本节点，不改变项目文件依赖图。原始项目保存在 `/tmp/latex-translate-<id>/source/` 作为只读基线，用于 diff、回滚和结构校验。

---

## Step 2: 项目结构分析

获取源文件后，先分析项目是否已分文件（使用 `\input{}` / `\include{}` 拆分了章节）：

```bash
cd /tmp/latex-translate-<id>/source
# 检测所有 \input 和 \include 引用（忽略注释行）
grep -n '^[^%]*\\input{\|^[^%]*\\include{' main.tex
```

### 已分文件（推荐用并行翻译）

如果主文件通过 `\input{}` / `\include{}` 引入独立 .tex 文件（如 `sections/intro.tex`, `chapters/method.tex`），且每个文件对应一个章节：

1. 列出所有内容文件，排除 preamble-only 文件（宏包配置、自定义命令等）
2. 统计内容文件数量，确认可以并行
3. 直接进入 **Step 3.2 并行翻译**

### 未分文件（需要先拆分）

如果只有一个大的 `main.tex`（所有内容在一个文件内）：

1. 分析文档结构，按 `\section{...}` / `\subsection{...}` 边界识别可拆分的章节
2. 向用户呈现拆分方案：

```
原文件 main.tex 共 N 个章节，建议拆分为：
  sections/00_preamble.tex       — 导言区（documentclass、宏包、自定义命令）
  sections/01_abstract.tex       — Abstract
  sections/02_intro.tex          — 1. Introduction
  sections/03_related.tex        — 2. Related Work
  sections/04_method.tex         — 3. Method
  sections/05_experiments.tex    — 4. Experiments
  sections/06_conclusion.tex     — 5. Conclusion
  main.tex                       — 骨架文件（只含 \input{} 和少量结构命令）

是否按此方案拆分？[y/n]
```

3. 用户确认后，执行拆分：将各章节内容提取到独立文件，主文件用 `\input{}` 引用
4. **先编译一次拆分后的文件**，确认排版正确，呈现给用户确认：
   ```
   拆分后编译成功，PDF正常生成。排版是否OK？没问题的话继续翻译。[y/n]
   ```
5. 用户确认排版后，再进入翻译步骤

### 依赖文件处理

如果项目中有 `.sty`, `.cls`, `.bst`, `.bib`, 图片等依赖文件不存在于源码目录中，编译时会报错。遇到此类问题：

1. 解析编译错误，列出缺失的依赖（如 `file.sty not found`）
2. 向用户呈现：

```
LaTeX 依赖缺失：
  style/nips.sty              — 会议模板文件
  figures/architecture.pdf    — 图片资源
  mybib.bib                   — 参考文献数据库

如何处理？
  [A] 自动安装（Web搜索下载）
  [B] 手动安装（告诉我文件位置或提供URL）
  [C] 跳过（我自行处理）
```

3. 根据用户选择执行

---

## Step 2.5: 基线编译与中文兼容性扫描

在翻译前，必须先编译原始英文项目，建立基线。该步骤用于区分：
- 原始模板本身的问题
- 翻译过程中引入的问题
- 中文字体/ctex/XeTeX 与英文模板之间的兼容问题

### 2.5.1 原始项目基线编译

在 source/ 目录中对原始英文项目编译一次：

```bash
cd /tmp/latex-translate-<id>/source
latexmk -pdf -interaction=nonstopmode main.tex
```

如果原项目使用 XeLaTeX 或 LuaLaTeX，则：

```bash
latexmk -xelatex -interaction=nonstopmode main.tex
```

**如果基线编译失败（缺包/缺字体等）**，不得自行执行安装命令。必须解析错误，列出缺失项和安装命令，向用户呈现：

```
基线编译失败，缺少以下依赖：

  LaTeX 包：
    algpseudocode.sty     → sudo pacman -S texlive-publishers
    times.sty             → sudo pacman -S texlive-fontsrecommended

请手动安装后告知，或回复 [skip] 跳过基线编译直接进入翻译。
```

记录以下信息：
- 是否能生成 PDF
- 是否存在 undefined references/citations
- 是否存在 overfull/underfull box
- 是否存在 mdframed/tcolorbox/tabbing/caption 相关 warning/error
- 编译遍数

### 2.5.2 中文兼容性风险扫描

运行兼容性扫描脚本：

```bash
uv run python $SKILL_DIR/scripts/latex_compat_scan.py /tmp/latex-translate-<id>/source/
```

也可以直接 grep 辅助检查高风险结构：

```bash
grep -RInE '\\begin\{(mdframed|framed|tcolorbox|tabbing|wrapfigure|minipage|figure\*|table\*)\}|\\caption\{|\\section\{|\\subsection\{|\\noindent\\textbf|\\newcommand|\\renewcommand|\\DeclareRobustCommand|\\xspace|\\vspace\{-|\\hspace\{-|\\vskip -' .
```

重点记录以下风险：

1. **`mdframed` / `framed` / `tcolorbox`**：中文行高可能导致盒子高度计算不准，后续内容重叠
2. **`tabbing`**：中文翻译后缩进层级可能暴露缺少 `\=` tab 位的问题
3. **`\caption{}`、`\section{}`、`\subsection{}`**：属于 moving arguments，自定义宏可能 fragile
4. **含 `\xspace` 的宏**：在 caption、section、PDF bookmark 中高风险
5. **`\noindent\textbf{...}`**：run-in heading，中文变长后可能视觉拥挤
6. **负间距**：`\vspace{-...}`、`\hspace{-...}`、`\vskip -...`，英文模板中常见，中文后更容易触发重叠

### 2.5.3 风险清单输出

生成 `compatibility_report.md`，格式：

```markdown
# 中文兼容性风险报告

## Box/frame 环境
- main.tex:128 mdframed 后紧跟 \section — 可能需要 skipbelow 或额外 \vspace

## Tabbing 环境
- algorithm.tex:45 tabbing 有 N 层 \> 但只定义 M 个 tab 位

## Fragile macros in moving arguments
- \sys 使用了 \xspace
- \sys 出现在 \caption 中 (experiment.tex:72)

## Run-in headings
- overload.tex: Request level
- overload.tex: System level

## 负间距
- experiment.tex: figure* 含 \vspace{-0.05in}
```

翻译时必须针对报告中的每个风险点做防御处理。如果基线编译本身失败，排除项目自身问题后再翻译。

---

## Step 3: 翻译执行

### 3.1 翻译块判定规则

**翻译块定义**：文献中可以独立翻译、独立校对、且语义相对完整的最小内容单元。

**优先级顺序**：
1. 加粗字体摘要 / 小标题式概括语
2. 最小章节序号
3. 无编号但具有标题功能的小节标题
4. 连续段落的语义完整性

**判定流程**（按顺序执行）：

#### 第一步：排除非正文内容
以下内容不作为翻译块：
- 文章标题 `\title{...}`
- 作者、机构、邮箱、通讯作者信息
- 页眉、页脚、页码
- 引用文献列表 (`\begin{thebibliography}` ...)
- 尾页作者介绍、致谢中的作者履历
- 代码段 (`\begin{lstlisting}`, `\begin{verbatim}` 等)
- 算法伪代码本体 (`\begin{algorithm}` 内代码)
- 表格内部原始数据 (但表题/表注需翻译)
- 公式本体 (`\begin{equation}...` 内的数学公式)
- 图表中的坐标轴、图例、数值标签
- `\cite{}`, `\ref{}`, `\label{}` 命令

**例外**（这些应该翻译）：
- 图题/表题 (`\caption{...}` 中含解释性文字的)
- 公式前后的解释文字
- 算法说明段落（算法伪代码本体不翻译）
- 表格标题和说明文字
- 脚注和尾注（含解释性内容的）
- 摘要 (`\begin{abstract}...\end{abstract}`)

#### 第二步：识别加粗摘要
如果文档中有 `\textbf{...}` 加粗句子充当"摘要式标题"，它和后续解释段落合并为一个翻译块。

判断标准：加粗文字是否承担了"小标题/主题句/概括句"的结构功能。
- 如果是段内强调词，不单独作翻译块
- 如果多个连续加粗句分别引出不同段落，每个加粗句及其覆盖段落分别作为翻译块

#### 第三步：识别最小章节层级
- 如果有编号章节（如 2 → 2.1 → 2.1.1），以最小编号层级为翻译块单位
- 如果上级标题下没有正文，不单独作为翻译块
- 如果上级标题下有导言：
  - 导言能独立表达完整含义 → 单独翻译块
  - 导言只是引出后文 → 并入其后第一个最小章节翻译块
  - 导言概括整个大节 → 作为该大节的"总述翻译块"

#### 第四步：检查语义完整性
以下情况合并为一个翻译块：
- 同一小节下多个段落共同解释一个概念
- 一个段落提出问题，下一段给出方法或结论
- 多段共同解释同一个公式、模型、实验设置或结果
- 加粗摘要后连续若干段都在展开同一主题

不要仅因为换行或分段就拆成多个翻译块。

#### 第五步：检查是否破坏上下文
以下结构应尽量保持在同一个翻译块中：
- "提出概念 → 解释概念"
- "提出问题 → 给出解决方案"
- "实验设置 → 对应说明"
- "结果描述 → 结果分析"
- "公式 → 公式解释"

#### 特殊情况
- **Abstract**：作为独立翻译块。即使内部分多个段落，通常合并为一个翻译块
- **Keywords**：翻译但单独标记为"关键词块"
- **Acknowledgements**：询问用户是否翻译
- **Appendix**：询问用户；如含正文解释按章节规则划分，纯数据/证明/代码可排除

### 3.2 翻译写入策略

**禁止直接修改用户原始源码，禁止生成 `_zh.tex` 后缀文件。**

翻译在复制出的工作目录 `/tmp/latex-translate-<id>/work_zh/` 中进行：

1. 保持所有文件名、目录结构、`\input{}`、图片路径、bib 路径不变
2. 对 `.tex` 文件做原位文本替换——只替换正文文本，不动 LaTeX 结构
3. 不修改 `\input{sections/intro}` 为 `\input{sections/intro_zh}`
4. 原始目录作为只读基线，用于 diff、回滚和结构校验

#### 提取文本块

```bash
uv run python $SKILL_DIR/scripts/extract_blocks.py /tmp/latex-translate-<id>/work_zh/ > /tmp/latex-translate-<id>/blocks.json
```

输出 `blocks.json`，每个翻译块包含 `block_id`、`file`、`source_text`、`context`。

#### 翻译文本块

agent 只翻译 `source_text`，返回 `block_id → translation` 映射。**不修改 JSON 中的任何其他字段，不重写 .tex 文件。**

#### 回填译文

```bash
uv run python $SKILL_DIR/scripts/backfill_blocks.py /tmp/latex-translate-<id>/work_zh/ /tmp/latex-translate-<id>/translations.json --blocks /tmp/latex-translate-<id>/blocks.json
```

回填脚本根据 `block_id` 和 `source_text` 精确定位并替换为译文。多个文件时自动并行写入（ThreadPoolExecutor），大幅加速回填速度。串行模式可用 `--no-parallel` 禁用。

### 3.3 并行翻译（已分文件项目）

**触发条件**：项目已用 `\input{}` / `\include{}` 分文件，且内容文件数 ≥ 2。

**执行步骤**：

1. **复制项目到 work_zh/** — 保持目录结构和文件依赖不变
2. **扫描全文建术语表** — 主agent先读取所有内容文件，提取专有名词，确定统一译法，输出术语表
3. **提取文本块** — 运行 `extract_blocks.py` 生成 `blocks.json`
4. **分组并启子agent** — 按文件将 blocks 分组，对每组启动子agent翻译：

```
子agent翻译任务：
  翻译文件: /tmp/latex-translate-<id>/blocks.json 中 file="sections/intro.tex" 的所有块
  输出: /tmp/latex-translate-<id>/translations_intro.json
  
  术语表: [从主agent传入]
  
  对每个块，只翻译 source_text 字段为中文，其他字段原样保留。
  
  翻译规则：
  - 保留所有 \cite, \ref, \label 等命令不变（source_text 中可能含有）
  - 缩写保留原文，首次出现加全称
  - 技术名词保留英文
  - 人名不翻译
  - 专业术语：中文译名（英文原文）首次，后续只用中文
```

**数量控制**：超过5个文件时，每批5个。全部完成后再回填。

5. **合并翻译结果** — 主agent汇总所有子agent的翻译输出
6. **回填** — 运行 `backfill_blocks.py` 将译文写入 `work_zh/`
7. **注入中文支持** — 在 `work_zh/` 的主文件中添加 ctex 支持
8. **编译** — 编译 `work_zh/` 中的中文版

### 3.4 顺序翻译（未分文件项目）

**触发条件**：项目是单文件，或拆分后仍有较大内容块。

1. **复制项目到 work_zh/**
2. **建立术语表**
3. **提取文本块** — 运行 `extract_blocks.py`
4. **主agent按块翻译** — 生成翻译 JSON
5. **回填** — 运行 `backfill_blocks.py`
6. **编译**

### 3.5 翻译格式

翻译时：
- 保留所有 `\cite{...}`, `\ref{...}`, `\label{...}`, `\begin{...}`, `\end{...}` 不变
- 保留数学公式 `$...$`, `$$...$$`, `\begin{equation}...\end{equation}` 不变
- 保留交叉引用标记如 `[1]`, `(Smith et al., 2023)`, `Eq. (3)`, `Figure 2`, `Table 1`
- 保留 `\textbf{}`, `\emph{}`, `\textit{}` 等格式化命令，只翻译其内部文字
- 图表标题 `\caption{...}` 中的文字需翻译
- 章节标题 `\section{...}`, `\subsection{...}` 中的文字需翻译

### 3.6 术语翻译规则

#### 缩写保留原文
CNN, LLM, GPU, MAH, CAS 等缩写保留。首次出现时如有全称：
- `Large Language Model (LLM)` → `大语言模型（Large Language Model, LLM）`
- 原文只给缩写时不强行扩展

#### 技术名词保留英文
Nvidia, PyTorch, TensorFlow, Transformer, CUDA, GitHub 等品牌/框架/库名保留英文：
- `Transformer` → `Transformer`
- `Transformer architecture` → `Transformer 架构`

#### 人名不翻译
Hinton, LeCun, Vaswani, Turing 等人名保留原文，不音译。极稳定译名（如图灵）可用。

#### 专业术语：中文译名（英文原文）
首次出现：
- `Multi-head Attention` → `多头注意力（Multi-head Attention）`
- `Self-Attention` → `自注意力（Self-Attention）`
后续只用中文译名。

#### 术语一致性
同一术语全文译法统一。必须先扫描全文，建立术语表后再翻译。

| 原文术语 | 推荐译法 | 首次出现形式 |
|----------|----------|-------------|
| Multi-head Attention | 多头注意力 | 多头注意力（Multi-head Attention） |
| Embedding | 嵌入表示 | 嵌入表示（Embedding） |
| Fine-tuning | 微调 | 微调（Fine-tuning） |
| Token | 词元 | 词元（Token） |
| Layer Normalization | 层归一化 | 层归一化（Layer Normalization） |

### 3.7 LaTeX命令保留清单

翻译时绝不修改的命令：
`\cite`, `\ref`, `\label`, `\begin/\end`, 数学环境, `\bibliography`, `\bibliographystyle`, 模板宏命令

保留命令，只翻译内部文字：
`\textbf`, `\emph`, `\textit`, `\section`, `\subsection`, `\caption`

### 3.8 Run-in heading 翻译规则

英文论文常用以下形式作为行内小标题：

```latex
\noindent\textbf{Request level:} text...
\noindent\textbf{System level:} text...
```

这不是结构错误。翻译时应保留结构，只翻译标题文字。

**翻译原则**：

1. 尽量短译，不做解释性扩写：
   - `Request level:` → `请求级别：`
   - `System level:` → `系统级别：`
2. 不得把短标题翻译成很长的中文短语
3. 不得擅自改成 `\paragraph{}` 或 `\subsubsection{}`
4. 如果视觉验收发现行内标题过长或拥挤，再局部改成块状标题

**可选局部块状化修复**：

如果标题不超过 12 个汉字，保持行内形式：

```latex
\par\smallskip
\noindent\textbf{请求级别：}\quad
正文...
```

如果标题超过 12 个汉字，可改为块状：

```latex
\par\smallskip
\noindent\textbf{请求级别：}\par
正文...
```

---

## Step 4: 中文排版调优

在翻译完成后、中文编译前，对 CJK 字体进行排版调优。这一步骤独立于编译修复，
专门解决中文渲染的视觉质量。

### 4.1 字体选型

用 `match_cjk_font.py` 根据原始拉丁字体风格自动匹配中文字体：

```bash
uv run python $SKILL_DIR/scripts/match_cjk_font.py /tmp/latex-translate-<id>/work_zh/main.tex --code-only
```

脚本会：
- 解析 .tex/.cls 识别拉丁 rmfamily/sffamily/ttfamily 风格（衬线/无衬线/等宽）
- 通过 fc-list 查询系统可用中文字体
- 按风格匹配：衬线→Noto Serif CJK SC / 无衬线→Noto Sans CJK SC / 等宽→Noto Sans Mono CJK SC
- 输出 `\setCJKmainfont/sansfont/monofont` 配置

也可快速输出 JSON 格式供 pipeline 使用：

```bash
uv run python $SKILL_DIR/scripts/match_cjk_font.py /tmp/latex-translate-<id>/work_zh/main.tex --json
```

### 4.2 行距计算

用 `compute_baselineskip.py` 基于 CJK 字体度量计算最佳行距：

```bash
uv run python $SKILL_DIR/scripts/compute_baselineskip.py /tmp/latex-translate-<id>/work_zh/main.tex --cjk-scale 1.1 --code-only
```

`--cjk-scale` 参数接受 CJK 字体缩放因子（见 4.3），脚本会基于缩放后的序号计算行距。
输出 `\fontsize{...}{...}\selectfont` 或含 `\setCJKmainfont{...}[Scale=...]` 的完整配置。

公式依据：`baselineskip = effective_size × cjk_factor`，其中 `cjk_factor` 由拉丁文默认行距因子叠
加 CJK 字体密度补偿量得出，夹在 `[latin_skip × 1.04, effective_size × 1.6]` 区间。

### 4.3 字号调节

中文字体在相同 pt 值下视觉偏小，默认将 CJK 字体放大 1pt：

| 基础字号 | Scale 值 | 实际 CJK 字号 |
|---------|---------|-------------|
| 10pt    | 1.1     | 11pt        |
| 11pt    | 1.09    | ≈12pt       |
| 12pt    | 1.08    | ≈13pt       |

通过 `\setCJKmainfont{...}[Scale=<factor>]` 实现。**必须**将此 Scale 值传给 4.2 的
`--cjk-scale` 参数以确保行距同步缩放。

### 4.4 粗斜体检查

用 `check_cjk_variants.py` 检查 CJK 字体的 Bold/Italic 变体支持：

```bash
uv run python $SKILL_DIR/scripts/check_cjk_variants.py "Noto Serif CJK SC" --code-only
```

脚本会：
- 通过 fc-list 检测字体是否提供 Bold、Italic、BoldItalic 子面
- 缺失项自动生成 `\xeCJKsetup{AutoFakeBold=..., AutoFakeSlant=...}`
- 对已提供的变体生成 `BoldFont/ItalicFont` 映射

### 4.5 注入配置

将 4.1-4.4 产出的 LaTeX 代码注入到 main.tex：

| 配置项 | 注入位置 | 来源 |
|--------|---------|------|
| `\usepackage{xeCJK}` + `\xeCJKsetup{...}` | 导言区（`\begin{document}` 前） | 固定 |
| `\setCJKmainfont/sansfont/monofont` | 导言区 | 4.1 match_cjk_font.py |
| `\xeCJKsetup{AutoFakeBold/AutoFakeSlant}` | 导言区 | 4.4 check_cjk_variants.py |
| `\fontsize{...}{...}\selectfont` | `\begin{document}` **之后第一行** | 4.2 compute_baselineskip.py |
| `[Scale=...]` 加入 `\setCJKmainfont` 选项中 | 导言区 | 4.3 字号调节 |

示例完整配置（10pt 文档）：

```latex
% 导言区（\begin{document} 之前）
\usepackage{xeCJK}
\xeCJKsetup{CJKmath=true}
\setCJKmainfont{Noto Serif CJK SC}[Scale=1.1, BoldFont={Noto Serif CJK SC}, AutoFakeSlant={0.167}]
\setCJKsansfont{Noto Sans CJK SC}
\setCJKmonofont{Noto Sans Mono CJK SC}
\xeCJKsetup{AutoFakeSlant={0.167}}

\begin{document}
\fontsize{10}{14.5}\selectfont
% ... 其余正文 ...
```

**已注入包不要重复添加**：如果 4.1-4.4 产出的某些配置已在文件中存在，不要重复写入。

### 4.6 字体缺失处理

如果任一脚本报告字体未安装，不得自行安裝。列出缺失字体和安装命令，询问用户确认。

---

## Step 5: 编译与兼容修复

### 5.1 中文支持注入策略

优先采用最小侵入策略：**保留原始 `\documentclass`，只在导言区添加中文支持**。

`ctexart`/`ctexrep`/`ctexbook` 不仅提供中文支持，还会改变标题、字号、行距、中文标点、章节格式等排版参数。对论文模板，尤其是 arXiv 论文、会议模板、双栏模板、含 `mdframed` 的模板，替换 documentclass 极易引发兼容性问题。

#### 默认方案：保留原 documentclass

在 `\documentclass{...}` 之后添加：

```latex
\usepackage[UTF8]{ctex}
```

如果自动字体检测不可靠，指定已知字体：

```latex
\usepackage[UTF8,fontset=none]{ctex}
\setCJKmainfont{Noto Serif CJK SC}
\setCJKsansfont{Noto Sans CJK SC}
\setCJKmonofont{Noto Sans Mono CJK SC}
```

#### 仅在以下条件全部满足时，才替换为 ctexart/ctexrep/ctexbook

1. 原始文档类是裸 `article` / `report` / `book`（无模板宏包覆盖版式）
2. 没有会议/期刊模板宏包控制版式
3. 没有大量自定义标题格式、双栏布局、mdframed/tcolorbox、复杂浮动体
4. 基线编译和中文试编译均确认替换 documentclass 不造成版式异常

#### 禁止事项

- 不得在未知模板中直接把会议/期刊 class 或定制 article 模板替换成 `ctexart`
- 不得对含 `mdframed` + `fontspec` 的模板直接使用 ctexart

### 5.2 编译命令

```bash
uv run python $SKILL_DIR/scripts/compile.py /tmp/latex-translate-<id>/work_zh/main.tex
```

编译脚本自动：
- 检测中文内容，优先使用XeLaTeX
- 使用 latexmk 自动多遍编译（处理bibtex/biber交叉引用）
- 使用 `-no-shell-escape` 安全模式
- 报告编译错误时，给出具体行号和错误类型

### 5.3 Box/Frame 环境中文兼容修复

如果文档使用 `mdframed`、`framed`、`tcolorbox`，翻译后必须检查其后是否紧跟 `\section`、`\subsection`、正文段落或浮动体。

#### mdframed 安全规则

如果 `mdframed` 内含中文，且其后 5 行内出现 `\section` / `\subsection` / `\paragraph` / 正文段落，则优先添加安全间距：

```latex
\end{mdframed}
\par\addvspace{1em}
```

如果多个 `mdframed` 都出现类似问题，可在导言区统一添加（谨慎使用）：

```latex
\usepackage{etoolbox}
\AfterEndEnvironment{mdframed}{\par\addvspace{1em}}
```

全局补丁仅当大量 mdframed 同时出现问题时才使用，优先做局部补丁。

#### tcolorbox 安全规则

如果使用 `tcolorbox`，优先启用 `breakable` 并设置间距：

```latex
\usepackage[most]{tcolorbox}
```

需要跨页或长中文说明框时：

```latex
\begin{tcolorbox}[breakable, before skip=1em, after skip=1em]
...
\end{tcolorbox}
```

#### 修复原则

1. 不使用负间距修复重叠
2. 优先增加 `skipbelow` / `after skip` / `\addvspace`
3. 局部修复优先于全局修复
4. 修复后必须重新编译并检查相邻页面

### 5.4 Tabbing 环境修复规则

翻译前后必须扫描所有 `tabbing` 环境。

#### 检查规则

在每个 `tabbing` 环境中：

1. 统计正文中最大连续 `\>` 层级数
2. 检查是否存在 `\=...\kill` 行定义 tab 位
3. 如果最大 `\>` 层级数大于已定义 `\=` 数量，则必须补充 tab 位

#### 自动修复示例

如果环境中存在三重或四重 `\>`，添加足够的 tab 位：

```latex
\begin{tabbing}
\hspace{1.5em}\=\hspace{1.5em}\=\hspace{1.5em}\=\hspace{1.5em}\=\kill
...
\end{tabbing}
```

#### 禁止事项

不得通过删除 `\>` 或改变伪代码结构来规避错误。

### 5.5 Moving Arguments 中的 Fragile Macro 修复

LaTeX 中以下命令的参数属于 moving arguments 或类 moving arguments：

- `\caption{...}`
- `\section{...}`、`\subsection{...}`、`\subsubsection{...}`
- `\paragraph{...}`
- `\title{...}`

在这些参数中使用自定义宏前，必须检查宏定义是否 fragile。

#### 高风险宏定义

包含以下内容的自定义宏视为高风险：

- `\xspace`
- `\footnote`
- `\cite`
- `\ref`
- `\url`
- 复杂格式命令
- 未用 `\DeclareRobustCommand` 声明的项目名宏

#### 修复优先级（按推荐度排序）

1. **最佳**：在 `\caption{}` 中直接写普通文本，不要用宏：

```latex
\caption{Mooncake 的性能结果}
```

2. **次选**：将宏定义改为 robust：

```latex
\DeclareRobustCommand{\sys}{Mooncake\xspace}
```

3. **最后手段**：在 moving argument 中使用 `\protect`：

```latex
\caption{\protect\sys 的性能结果}
```

#### 自动扫描命令

```bash
grep -RInE '\\newcommand\{\\[A-Za-z@]+\}.*\\xspace|\\caption\{.*\\[A-Za-z@]+' *.tex sections/*.tex
```

### 5.6 依赖处理

编译过程中如遇到缺失依赖（LaTeX包、图片、字体、样式文件等），**禁止自行执行安装命令**。必须先呈现给用户，等待确认。

1. 解析编译输出，提取缺失依赖信息（如 `! LaTeX Error: File 'xxx.sty' not found`）
2. 分类依赖类型：
   - LaTeX包（.sty/.cls） — 可通过 tlmgr 安装
   - 图片资源（.pdf/.png/.jpg） — 可能需从原始项目拷贝或重新生成
   - 字体文件 — 需安装系统字体或指定已有字体
   - 参考文献（.bib） — 需确认路径或下载
3. 向用户呈现并询问处理方式：

```
编译缺少以下依赖：

  LaTeX包：
    algorithm.sty          — 算法环境
    subfigure.sty          — 子图支持

  图片资源：
    figures/arch.pdf       — 架构图

如何处理？
  [A] 自动安装LaTeX包（tlmgr install），图片跳过并添加占位
  [B] 全部手动处理（请告诉我文件位置）
  [C] 我自行解决，编译可以先跳过
```

4. 根据用户选择执行后重编译

### 5.7 编译失败处理：中文兼容错误库

除依赖缺失外，必须识别以下中文兼容错误模式：

| 错误现象 | 常见根因 | 修复动作 |
|---|---|---|
| 框与后文重叠 | mdframed/framed 高度计算与中文行高不匹配 | 在 `\end{mdframed}` 后添加 `\par\addvspace{1em}` 或配置 skipbelow |
| Undefined tab position | tabbing 缺少足够 `\=` tab 位 | 添加 `\=\=\=\kill` 行 |
| Undefined control sequence in caption | fragile macro 出现在 moving argument 中 | caption 中写普通文本，或 `\DeclareRobustCommand`，或 `\protect` |
| PDF bookmark warning | 中文/宏命令进入 section/bookmark | 使用 `\texorpdfstring{TeX文本}{PDF文本}` |
| Overfull boxes 大幅增加 | 中文译文过长、run-in heading 过长 | 短译标题、局部断行、调整段落 |
| 浮动体与正文重叠 | 原模板负间距在中文后不再安全 | 减少或删除局部负 `\vspace` |
| `\sys not defined` 或类似 | 翻译文件丢失原始宏定义 | 确认导言区宏定义未被移除，`\input` 路径正确 |

---

## Step 5.5: PDF验收

### 5.5.1 交叉引用验收

第一遍 XeLaTeX 中出现 `??`、undefined references、undefined citations **不立即视为翻译错误**。这是 LaTeX 正常行为。

必须先执行完整清理和多遍编译：

```bash
cd /tmp/latex-translate-<id>/work_zh
latexmk -C main.tex
latexmk -xelatex -bibtex -interaction=nonstopmode main.tex
```

或根据项目使用 biber：

```bash
latexmk -xelatex -use-biber -interaction=nonstopmode main_zh.tex
```

只有在最终编译后仍出现以下内容，才视为失败：

```bash
grep -RInE 'undefined references|Citation .* undefined|Reference .* undefined|There were undefined references|Label.*multiply defined' *.log
grep -RInE '§\?\?|图 *\?\?|表 *\?\?|\[\?, *\?, *\?\]|Figure *\?\?|Table *\?\?' *.tex *.aux *.log
```

如果最终 PDF 中引用正常，不得把第一遍 `??` 归因于翻译破坏结构。

### 5.5.2 结构一致性不是最终验收

翻译后必须检查：
1. LaTeX 结构是否一致（`\label`、`\cite`、`\ref`、`\begin/\end` 数量与位置）
2. 编译日志是否干净（没有新增的 error，warnings 与基线对比）
3. PDF 视觉排版是否正常

即使 `\label`、`\cite`、`\ref`、`\begin/\end` 完全一致，仍可能因为中文字体、行高、ctex、XeTeX、fragile macro、run-in heading、负间距导致 PDF 错乱。

**结构 diff 通过后，仍必须执行中文兼容性检查和视觉验收。**

### 5.5.3 视觉检查要点

打开生成的 PDF，逐页检查：

1. 文字是否与图表、框、页眉页脚重叠
2. `mdframed`/`tcolorbox` 等框环境后是否出现大段空白或内容重叠
3. `\section`/`\subsection` 标题是否过长导致换行异常
4. run-in heading 是否过于拥挤
5. 浮动体（图、表）位置是否正常
6. 页边距是否与原始 PDF 一致或有合理变化

如发现问题，回到 Step 5.3-5.7 对应的修复规则处理，然后重编译、重验收。

---

## Step 6: 输出

编译验收通过后，PDF位于 `/tmp/latex-translate-<id>/work_zh/main.pdf`，复制到当前工作目录：

```bash
cp /tmp/latex-translate-<id>/work_zh/main.pdf ./<paper-name>_zh.pdf
```

---

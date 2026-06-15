"""
从 LaTeX 项目中提取可翻译文本片段。

遍历项目中的 .tex 文件，识别可翻译的文本节点：
  - 章节标题: \\section, \\subsection, \\subsubsection
  - 图表标题: \\caption
  - 格式化文本: \\textbf, \\emph, \\textit
  - 摘要正文: \\begin{abstract}...\\end{abstract}
  - 脚注: \\footnote
  - 段落正文: 环境/命令之外的独立文本段落

跳过:
  - 数学模式 ($...$, $$...$$, \\[...\\], equation 环境)
  - 引用命令 (\\cite, \\ref, \\label, \\input, \\bibliography 等)
  - 代码/算法/verbatim 环境
  - 参考文献列表
  - 纯粹的结构命令和注释

输出 JSON 到 stdout，每行为一个翻译块，包含:
  block_id, file, line_start, line_end, source_text, context

Usage:
    uv run python extract_blocks.py /path/to/project > blocks.json
    uv run python extract_blocks.py /path/to/project --files sections/intro.tex
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Block:
    block_id: str
    file: str
    line_start: int
    line_end: int
    source_text: str
    context: str  # "section", "caption", "textbf", "emph", "abstract", "footnote", "plain"


# ── brace matching ──

def _find_matching_brace(s: str, pos: int) -> int:
    """Find matching closing brace/bracket.
    
    pos must point to the opening character ('{' or '[').
    Returns position of the matching closing character.
    """
    open_char = s[pos]
    close_char = '}' if open_char == '{' else ']'
    depth = 1
    i = pos + 1
    while i < len(s) and depth > 0:
        if s[i] == open_char:
            depth += 1
        elif s[i] == close_char:
            depth -= 1
        if depth == 0:
            return i
        i += 1
    return len(s)


def _strip_commands(text: str) -> str:
    """Remove LaTeX commands from text for comparison purposes.
    Replaces \\command{...} with just the inner content.
    """
    result = []
    i = 0
    while i < len(text):
        if text[i] == '\\':
            j = i + 1
            # Read command name
            while j < len(text) and text[j].isalpha():
                j += 1
            cmd = text[i+1:j]
            # If followed by {, skip to matching }
            if j < len(text) and text[j] == '{':
                result.append(text[i:j+1])  # Keep \cmd{
                close = _find_matching_brace(text, j)
                result.append(text[j+1:close])  # Inner content
                result.append('}')
                i = close + 1
            elif j < len(text) and text[j] == '[':
                close = _find_matching_brace(text, j)  # [] use same logic
                result.append(text[i:close+1])
                i = close + 1
            else:
                result.append(text[i:j])
                i = j
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


# ── extraction ──

# Commands whose argument is translatable (single brace arg)
TRANSLATABLE_COMMANDS = {
    r'\section', r'\subsection', r'\subsubsection', r'\paragraph',
    r'\caption',
    r'\textbf', r'\emph', r'\textit', r'\textsf', r'\texttt',
    r'\footnote',
}

# Environments whose body is translatable
TRANSLATABLE_ENVS = {
    'abstract',
}

# Environments to skip entirely (no translation)
SKIP_ENVS = {
    'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
    'multline', 'multline*', 'eqnarray', 'eqnarray*',
    'lstlisting', 'verbatim', 'Verbatim',
    'thebibliography', 'algorithm', 'algorithmic', 'algorithmicx',
    'tikzpicture', 'pgfpicture',
    'figure', 'figure*', 'table', 'table*',
    'minipage',
}

# Commands whose arguments are never translated
SKIP_COMMANDS = {
    r'\cite', r'\citep', r'\citet', r'\citeauthor', r'\citeyear',
    r'\ref', r'\eqref', r'\pageref',
    r'\label',
    r'\input', r'\include',
    r'\bibliography', r'\bibliographystyle',
    r'\usepackage', r'\documentclass',
    r'\includegraphics', r'\graphicspath',
    r'\url', r'\href',
    r'\newcommand', r'\renewcommand', r'\DeclareRobustCommand',
    r'\newenvironment', r'\newtheorem',
    r'\def', r'\let',
    r'\setlength', r'\addtolength', r'\settowidth',
    r'\makeatletter', r'\makeatother',
    r'\newcommand', r'\renewcommand', r'\providecommand',
}

# Short commands that are safe to ignore (no args or numeric args)
IGNORE_SHORT = {
    r'\\', r'\&', r'\%', r'\$', r'\#', r'\_', r'\{', r'\}',
    r'\ ', r'\,', r'\-', r'\/',
}

BLOCK_COUNTER = [0]


def _next_id() -> str:
    BLOCK_COUNTER[0] += 1
    return f"blk_{BLOCK_COUNTER[0]:04d}"


# Regex to find LaTeX commands with optional * and brace arguments
RE_CMD = re.compile(
    r'\\([a-zA-Z@]+)(\*?)'
)

RE_ENV_BEGIN = re.compile(
    r'\\begin\{([^}]+)\}'
)

RE_ENV_END = re.compile(
    r'\\end\{([^}]+)\}'
)


def _is_math_mode(text: str, pos: int) -> bool:
    """Quick check if position is inside math mode."""
    # Check for $$ ... $$ or \[ ... \] or $ ... $
    before = text[:pos]
    # Count unescaped $ signs before pos
    dollars = re.findall(r'(?<!\\)\$', before)
    return len(dollars) % 2 == 1


def _is_in_skip_env(env_stack: list[str]) -> bool:
    """Check if currently inside a skip environment."""
    return any(e in SKIP_ENVS for e in env_stack)


def _is_in_translatable_env(env_stack: list[str]) -> bool:
    """Check if currently inside a translatable environment."""
    return any(e in TRANSLATABLE_ENVS for e in env_stack)


def _extract_braced_text(file_content: str, pos: int) -> tuple[str, int]:
    """Extract text from brace group. pos points to the opening {."""
    close = _find_matching_brace(file_content, pos)
    inner = file_content[pos + 1 : close]
    return inner, close + 1  # position after }


def extract_file(filepath: Path, base_dir: Path) -> list[Block]:
    """Extract translatable blocks from a single .tex file."""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    rel_path = str(filepath.relative_to(base_dir))
    blocks: list[Block] = []

    lines = content.split('\n')
    # Build line-start positions for line number lookup
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line) + 1)

    def pos_to_line(pos: int) -> int:
        for i, start in enumerate(line_starts[:-1]):
            if start <= pos < line_starts[i + 1]:
                return i + 1
        return len(lines)

    i = 0
    env_stack: list[str] = []
    prev_i = -1
    stall_count = 0

    while i < len(content):
        # Safety: detect infinite loop
        if i == prev_i:
            stall_count += 1
            if stall_count > 3:
                print(f"[WARN] Stuck at pos {i} in {rel_path}, breaking", file=sys.stderr)
                break
        else:
            stall_count = 0
            prev_i = i

        # Skip comments
        if content[i] == '%' and (i == 0 or content[i-1] != '\\'):
            j = content.find('\n', i)
            if j == -1:
                break
            i = j + 1
            continue

        # Math mode: skip $...$, $$...$$, \[...\]
        if content[i:i+2] == '$$':
            j = content.find('$$', i+2)
            i = (j + 2) if j != -1 else len(content)
            continue
        if content[i:i+2] == r'\[':
            j = content.find(r'\]', i+2)
            i = (j + 2) if j != -1 else len(content)
            continue
        if content[i:i+2] == r'\(':
            j = content.find(r'\)', i+2)
            i = (j + 2) if j != -1 else len(content)
            continue
        if content[i] == '$' and (i == 0 or content[i-1] != '\\'):
            j = content.find('$', i+1)
            i = (j + 1) if j != -1 else len(content)
            continue

        # Environment end
        m_end = RE_ENV_END.match(content, i)
        if m_end:
            env_name = m_end.group(1)
            if env_stack and env_stack[-1] == env_name:
                env_stack.pop()
            i = m_end.end()
            continue

        # Environment begin
        m_begin = RE_ENV_BEGIN.match(content, i)
        if m_begin:
            env_name = m_begin.group(1)
            env_stack.append(env_name)
            i = m_begin.end()
            continue

        # LaTeX command
        if content[i] == '\\':
            m = RE_CMD.match(content, i)
            if not m:
                # Not a command we recognize, skip one char
                i += 1
                continue

            cmd = '\\' + m.group(1)
            i = m.end()
            star = m.group(2)

            # Skip non-translatable commands with their arguments
            if cmd in SKIP_COMMANDS:
                while i < len(content) and content[i] in ' [{':
                    if content[i] == ' ':
                        i += 1
                    elif content[i] == '[':
                        close = _find_matching_brace(content, i)
                        i = close + 1
                    elif content[i] == '{':
                        close = _find_matching_brace(content, i)
                        i = close + 1
                    else:
                        break
                continue

            # Skip if in non-translatable environment
            if _is_in_skip_env(env_stack):
                # Still need to skip any brace arguments
                while i < len(content) and content[i] in ' [{':
                    if content[i] == ' ':
                        i += 1
                    elif content[i] in '[{':
                        close = _find_matching_brace(content, i)
                        i = close + 1
                    else:
                        break
                continue

            # Translatable command: extract its brace argument
            if cmd in TRANSLATABLE_COMMANDS:
                # Skip whitespace and optional [...]
                while i < len(content) and content[i] in ' \n\t':
                    i += 1
                if i < len(content) and content[i] == '[':
                    close = _find_matching_brace(content, i)
                    i = close + 1
                    while i < len(content) and content[i] in ' \n\t':
                        i += 1
                if i < len(content) and content[i] == '{':
                    inner_text, new_i = _extract_braced_text(content, i)
                    i = new_i

                    # Only extract if there's actual text (not just commands/math)
                    stripped = re.sub(r'\\.*?(\{[^}]*\})?', '', inner_text).strip()
                    if stripped:
                        line_start = pos_to_line(i - len(inner_text) - 2)
                        line_end = pos_to_line(i)
                        ctx = cmd[1:]  # remove backslash
                        blocks.append(Block(
                            block_id=_next_id(),
                            file=rel_path,
                            line_start=line_start,
                            line_end=line_end,
                            source_text=inner_text,
                            context=ctx,
                        ))
                continue

            # Other command: skip its brace arguments
            while i < len(content) and content[i] in ' [{':
                if content[i] == ' ':
                    i += 1
                elif content[i] in '[{':
                    close = _find_matching_brace(content, i)
                    i = close + 1
                else:
                    break
            continue

        # Plain text: collect until next command, math, or environment marker
        if not _is_in_skip_env(env_stack) and not _is_math_mode(content, i):
            j = i
            while j < len(content):
                if content[j] == '\\':
                    # Check if it's a real command, not just \%, \&, etc.
                    if j + 1 < len(content) and content[j+1] in '%&$#_{}':
                        j += 2  # skip escaped special chars
                        continue
                    break
                if content[j] == '$':
                    # Skip escaped $
                    if j > 0 and content[j-1] == '\\':
                        j += 1
                        continue
                    break
                if content[j] == '%':
                    # Skip escaped %
                    if j > 0 and content[j-1] == '\\':
                        j += 1
                        continue
                    break
                if content[j] == '}' and env_stack:
                    # Closing brace might be end of env body
                    break
                j += 1

            text = content[i:j].strip()
            # Filter out text that's just braces/spaces
            text = re.sub(r'^[\s\}]+', '', text)
            text = re.sub(r'[\s\{]+$', '', text)

            if text and len(text) > 1:
                line_start = pos_to_line(i)
                line_end = pos_to_line(j)
                blocks.append(Block(
                    block_id=_next_id(),
                    file=rel_path,
                    line_start=line_start,
                    line_end=line_end,
                    source_text=text,
                    context="plain",
                ))

            i = j
        else:
            i += 1

    return blocks


def extract_project(project_dir: Path, files: Optional[list[str]] = None) -> list[Block]:
    """Extract all translatable blocks from a LaTeX project."""
    all_blocks: list[Block] = []

    if files:
        tex_files = [project_dir / f for f in files]
    else:
        tex_files = sorted(project_dir.rglob("*.tex"))

    for tex_file in tex_files:
        if not tex_file.is_file():
            continue
        try:
            blocks = extract_file(tex_file, project_dir)
            all_blocks.extend(blocks)
        except Exception as e:
            print(f"[WARN] 无法处理 {tex_file}: {e}", file=sys.stderr)

    return all_blocks


def main():
    parser = argparse.ArgumentParser(
        description="从 LaTeX 项目中提取可翻译文本片段",
    )
    parser.add_argument(
        "project_dir",
        help="LaTeX 项目目录",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        help="指定要处理的 .tex 文件（相对路径），默认处理全部",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="输出 JSONL 格式（每行一个块）",
    )
    args = parser.parse_args()

    root = Path(args.project_dir).resolve()
    if not root.is_dir():
        print(f"[ERROR] 目录不存在: {args.project_dir}", file=sys.stderr)
        sys.exit(1)

    blocks = extract_project(root, args.files)

    if args.jsonl:
        for b in blocks:
            print(json.dumps({
                "block_id": b.block_id,
                "file": b.file,
                "line_start": b.line_start,
                "line_end": b.line_end,
                "source_text": b.source_text,
                "context": b.context,
            }, ensure_ascii=False))
    else:
        output = {
            "project_dir": str(root),
            "total_blocks": len(blocks),
            "blocks": [
                {
                    "block_id": b.block_id,
                    "file": b.file,
                    "line_start": b.line_start,
                    "line_end": b.line_end,
                    "source_text": b.source_text,
                    "context": b.context,
                }
                for b in blocks
            ],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"\n提取完成: {len(blocks)} 个翻译块", file=sys.stderr)


if __name__ == "__main__":
    main()

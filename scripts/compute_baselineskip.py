"""
根据中英文字体度量计算最佳行距 (baselineskip)

acmart 模板默认为 \fontsize{10}{12}（ratio = 1.2），这对拉丁文合适，
但中文字符笔划密度大，需要更大行距。此脚本通过解析实际字体度量
（hhea/OS2 表）量化视觉差异，输出推荐的 \fontsize{size}{skip} 配置。

Usage:
    uv run python compute_baselineskip.py main.tex
    uv run python compute_baselineskip.py main.tex --json
    uv run python compute_baselineskip.py main.tex --cjk "Noto Serif CJK SC"
    uv run python compute_baselineskip.py main.tex --cjk-scale 1.1
    uv run python compute_baselineskip.py main.tex --cjk-scale 1.1 --code-only
"""

import argparse
import json
import re
import struct
import subprocess
import sys
from pathlib import Path


# ──────────────────────────── Font Metadata ────────────────────────────

# Standard CJK line spacing factor (Latin default = 1.2, CJK needs 1.3-1.5)
DEFAULT_CJK_FACTOR = 1.35

# For font sizes not explicitly listed in acmart.cls, interpolate
FONT_SIZE_BASELINE = {
    # acmart.cls \ACM@fontsize{size}{baselineskip} definitions
    7: (7, 8),         # \@acmtiny
    8: (8, 10),        # \@acmsmall
    9: (9, 11),        # interpolated (~1.22 ratio)
    10: (10, 12),      # \@acmnormal
    11: (11, 13),      # interpolated (~1.18 ratio)
    12: (12, 14),      # interpolated (~1.17 ratio)
}


def read_font_metrics(font_path: str, ttc_index: int = 0) -> dict:
    """
    从字体二进制文件中读取 hhea 和 OS/2 表的度量数据。

    支持 .otf/.ttf 和 .ttc 格式。返回 dict:
        upem: 单位 em 大小（通常 1000）
        ascender: hhea 表 ascender (font units)
        descender: hhea 表 descender（通常为负值）
        linegap: hhea 表 lineGap
        typo_ascender: OS/2 sTypoAscender
        typo_descender: OS/2 sTypoDescender（通常为负值）
        typo_linegap: OS/2 sTypoLineGap
    """
    with open(font_path, 'rb') as f:
        header = f.read(4)
        base_offset = 0
        if header == b'ttcf':
            _, num_fonts = struct.unpack('>II', f.read(8))
            if ttc_index >= num_fonts:
                raise ValueError(f"TTC index {ttc_index} out of range (0-{num_fonts - 1})")
            f.read(ttc_index * 4)
            base_offset = struct.unpack('>I', f.read(4))[0]
            f.seek(base_offset)
            _ = f.read(4)  # sfVersion

        # Table directory starts at base_offset + 4
        f.seek(base_offset + 4)
        num_tables, _, _, _ = struct.unpack('>HHHH', f.read(8))

        tables = {}
        for _ in range(num_tables):
            tag, _, off, length = struct.unpack('>4sIII', f.read(16))
            tables[tag] = (off, length)

        def get_table(tag: bytes):
            if tag not in tables:
                return None
            off, length = tables[tag]
            f.seek(off)
            return f.read(length)

        head = get_table(b'head')
        hhea = get_table(b'hhea')
        os2 = get_table(b'OS/2')

        upem = struct.unpack('>H', head[18:20])[0] if head and len(head) >= 20 else 1000
        ascender = struct.unpack('>h', hhea[4:6])[0] if hhea and len(hhea) >= 6 else 0
        descender = struct.unpack('>h', hhea[6:8])[0] if hhea and len(hhea) >= 8 else 0
        linegap = struct.unpack('>h', hhea[8:10])[0] if hhea and len(hhea) >= 10 else 0

        ta = struct.unpack('>h', os2[68:70])[0] if os2 and len(os2) >= 70 else ascender
        td = struct.unpack('>h', os2[70:72])[0] if os2 and len(os2) >= 72 else descender
        tl = struct.unpack('>h', os2[72:74])[0] if os2 and len(os2) >= 74 else linegap

        return {
            'upem': upem,
            'ascender': ascender,
            'descender': descender,
            'linegap': linegap,
            'typo_ascender': ta,
            'typo_descender': td,
            'typo_linegap': tl,
        }


def find_font_file(font_name: str) -> str | None:
    """通过 fc-match 查找字体文件路径。"""
    try:
        result = subprocess.run(
            ['fc-match', '-v', font_name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            m = re.match(r'\s*file:\s*"(.+?)"\s*', line)
            if m:
                return m.group(1)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ──────────────────────────── LaTeX Parsing ────────────────────────────

def parse_font_size_from_tex(main_tex: str) -> int:
    r"""从 \documentclass[...,<size>pt,...]{...} 提取基础字号。"""
    with open(main_tex, 'r') as f:
        content = f.read()

    m = re.search(
        r'\\documentclass\s*\[([^\]]*?)\]\s*\{',
        content, re.DOTALL,
    )
    if m:
        options = m.group(1)
        size_m = re.search(r'(\d+)\s*pt', options)
        if size_m:
            return int(size_m.group(1))

    # acmart default is 10pt
    doc_m = re.search(r'\\documentclass\s*\{(\w+)\}', content)
    if doc_m and doc_m.group(1) == 'acmart':
        return 10

    return 10


def parse_cjk_font_from_tex(main_tex: str) -> str | None:
    r"""从 \setCJKmainfont{<name>} 提取 CJK 主字体名。"""
    with open(main_tex, 'r') as f:
        content = f.read()

    m = re.search(r'\\setCJKmainfont\s*\{([^}]+)\}', content)
    if m:
        return m.group(1).strip()
    return None


def parse_cls_baselineskip(main_tex: str) -> float | None:
    """从关联的 .cls 文件中查找 \fontsize 定义获取原始行距。"""
    with open(main_tex, 'r') as f:
        content = f.read()
    m = re.search(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{(\w+)\}', content)
    if not m:
        return None
    cls_name = m.group(1)
    tex_dir = Path(main_tex).parent

    cls_path = tex_dir / f"{cls_name}.cls"
    if not cls_path.exists():
        cls_path = Path(f"{cls_name}.cls")

    if not cls_path.exists():
        try:
            result = subprocess.run(
                ['kpsewhich', f'{cls_name}.cls'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                cls_path = Path(result.stdout.strip())
        except Exception:
            pass

    if not cls_path.exists():
        return None

    with open(cls_path, 'r', errors='ignore') as f:
        cls_content = f.read()

    patterns = [
        r'\\@acmnormal\s*\{(.*?)\}',
        r'\\fontsize\s*\{(\d+)\}\s*\{(\d+)\}',
        r'\\newcommand\s*\{\\@acmnormal\}\s*\{[^}]*\\fontsize\s*\{(\d+)\}\s*\{(\d+)\}',
    ]
    for pat in patterns:
        m = re.search(pat, cls_content, re.DOTALL)
        if m:
            groups = m.groups()
            if len(groups) == 1:
                inner_m = re.search(r'\\fontsize\s*\{(\d+)\}\s*\{(\d+)\}', groups[0])
                if inner_m:
                    return float(inner_m.group(2))
            elif len(groups) == 2:
                return float(groups[1])

    return None


# ──────────────────────────── Core Calculation ────────────────────────────

def compute_baselineskip(
    font_size: int,
    latin_font: str | None = None,
    cjk_font: str | None = None,
    cjk_scale: float = 1.0,
) -> dict:
    """
    计算最佳行距。

    参数:
        font_size:  基础拉丁文字号（pt）
        cjk_scale:  中文字体缩放因子（`\\setCJKmainfont{...}[Scale=<cjk_scale>]`）
                    计算行距时会基于缩放后的实际字号。
    公式:
        cjk_eff_ratio = min(cjk_typo_body / cjk_upem, 1.0)
        cjk_factor = latin_factor * (1 + (1.0 - cjk_eff_ratio) * 0.5 + 0.12)
        # 当 CJK visual body 少于 em-square 时，说明字体内部空隙少、密度大
        # 需要增加行距；+0.12 是基准中文行距增量
        baselineskip = effective_size * cjk_factor

    回退策略:
        若无法读取字体度量 → 使用 DEFAULT_CJK_FACTOR = 1.35
    """
    # 计算 CJK 实际显示字号
    effective_size = font_size * cjk_scale

    # 1. 获取拉丁文默认行距因子
    latin_size, latin_skip = FONT_SIZE_BASELINE.get(
        font_size, (font_size, int(font_size * 1.2))
    )
    latin_factor = latin_skip / latin_size

    # 2. 获取 CJK 字体度量
    cjk_metrics = None
    cjk_path = None
    if cjk_font:
        cjk_path = find_font_file(cjk_font)
    if not cjk_path:
        cjk_path = find_font_file('Noto Serif CJK SC')

    if cjk_path:
        try:
            cjk_metrics = read_font_metrics(cjk_path)
        except Exception:
            pass

    # 3. 计算 CJK 视觉密度因子
    if cjk_metrics and cjk_metrics['upem'] > 0:
        cjk_body = cjk_metrics['typo_ascender'] + abs(cjk_metrics['typo_descender'])
        cjk_body_ratio = cjk_body / cjk_metrics['upem']
        # CJK typo body 通常等于 em (ratio=1.0)，但实际字符视觉密度更大
        # density = 1 - ratio: ratio 越小说明字体内空白越多，越不需要增加行距
        density = max(0.0, 1.0 - cjk_body_ratio)
        cjk_factor = latin_factor + density * 0.5 + 0.12
    else:
        cjk_factor = DEFAULT_CJK_FACTOR

    # 4. 计算并夹取行距（基于 CJK 实际显示字号）
    baselineskip = effective_size * cjk_factor
    baselineskip = max(baselineskip, latin_skip * 1.04)       # 不低于拉丁行距的 104%
    baselineskip = min(baselineskip, effective_size * 1.6)    # 不超过 CJK 字号的 1.6 倍
    baselineskip = round(baselineskip * 2) / 2  # 舍入到 0.5pt

    # 5. 拉丁字体信息（诊断用）
    latin_metrics = None
    latin_path = None
    if latin_font:
        latin_path = find_font_file(latin_font)
    if not latin_path:
        for name in ['Linux Libertine O', 'LinLibertine', 'Libertine',
                      'Latin Modern Roman', 'Noto Serif']:
            latin_path = find_font_file(name)
            if latin_path:
                break

    if latin_path:
        try:
            latin_metrics = read_font_metrics(latin_path)
        except Exception:
            pass

    return {
        'font_size': font_size,
        'cjk_scale': cjk_scale,
        'effective_size': effective_size,
        'original_baselineskip': latin_skip,
        'original_factor': round(latin_factor, 4),
        'cjk_factor': round(cjk_factor, 4),
        'recommended_baselineskip': baselineskip,
        'cjk_font': cjk_font,
        'cjk_path': cjk_path,
        'cjk_metrics': cjk_metrics,
        'latin_font_name': 'Linux Libertine O' if not latin_font else latin_font,
        'latin_path': latin_path,
        'latin_metrics': latin_metrics,
    }


def format_result(result: dict, json_mode: bool = False, code_only: bool = False) -> str:
    """格式化输出结果。"""
    if json_mode:
        output = {
            'font_size': result['font_size'],
            'cjk_scale': result['cjk_scale'],
            'effective_size': result['effective_size'],
            'baselineskip': result['recommended_baselineskip'],
            'factor': result['cjk_factor'],
            'original_baselineskip': result['original_baselineskip'],
            'cjk_font': result['cjk_font'],
        }
        return json.dumps(output, ensure_ascii=False)

    lines = []
    lines.append(f"基础字号:          {result['font_size']}pt")
    if result['cjk_scale'] != 1.0:
        lines.append(f"CJK 缩放:           {result['cjk_scale']} "
                     f"(实际字号 {result['effective_size']}pt)")
    lines.append(f"原始拉丁行距:       {result['original_baselineskip']}pt "
                 f"(因子 {result['original_factor']})")
    if result['cjk_metrics']:
        m = result['cjk_metrics']
        body = m['typo_ascender'] + abs(m['typo_descender'])
        cjk_label = result['cjk_font'] or '(自动检测)'
        lines.append(f"CJK 字体度量:       {cjk_label}")
        lines.append(f"  upem={m['upem']}  typo_body={body} "
                     f"({m['typo_ascender']}/{-abs(m['typo_descender'])})")
    else:
        cjk_label = result['cjk_font'] or '(未指定，使用默认因子)'
        lines.append(f"CJK 字体:          {cjk_label}")
    if result['latin_metrics']:
        m = result['latin_metrics']
        body = m['typo_ascender'] + abs(m['typo_descender'])
        lines.append(f"拉丁字体度量:       {result['latin_font_name']}")
        lines.append(f"  upem={m['upem']}  typo_body={body} "
                     f"({m['typo_ascender']}/{-abs(m['typo_descender'])})")
    lines.append(f"CJK 行距因子:       {result['cjk_factor']}")
    lines.append(f"\n推荐行距:           {result['recommended_baselineskip']}pt")

    if code_only:
        cjk_font = result.get('cjk_font')
        if cjk_font and result['cjk_scale'] != 1.0:
            return (f"\\setCJKmainfont{{{cjk_font}}}[Scale={{{result['cjk_scale']}}}]\n"
                    f"\\fontsize{{{result['font_size']}}}"
                    f"{{{result['recommended_baselineskip']}}}\\selectfont")
        return (f"\\fontsize{{{result['font_size']}}}"
                f"{{{result['recommended_baselineskip']}}}\\selectfont")

    if cjk_font := result.get('cjk_font'):
        if result['cjk_scale'] != 1.0:
            lines.append(f"\nLaTeX 代码:\n  "
                         f"\\setCJKmainfont{{{cjk_font}}}[Scale={{{result['cjk_scale']}}}]\n  "
                         f"\\fontsize{{{result['font_size']}}}"
                         f"{{{result['recommended_baselineskip']}}}\\selectfont")
        else:
            lines.append(f"\nLaTeX 代码:\n  "
                         f"\\fontsize{{{result['font_size']}}}"
                         f"{{{result['recommended_baselineskip']}}}\\selectfont")
    else:
        lines.append(f"\nLaTeX 代码:\n  "
                     f"\\fontsize{{{result['font_size']}}}"
                     f"{{{result['recommended_baselineskip']}}}\\selectfont")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="根据中英文字体度量计算最佳行距 (baselineskip)",
    )
    parser.add_argument(
        'main_tex', nargs='?',
        help='主 .tex 文件路径',
    )
    parser.add_argument(
        '--cjk', '--cjk-font', dest='cjk_font',
        help='CJK 主字体名称（如 "Noto Serif CJK SC"）',
    )
    parser.add_argument(
        '--latin', '--latin-font', dest='latin_font',
        help='拉丁字体名称（如 "Linux Libertine O"）',
    )
    parser.add_argument(
        '--json', action='store_true',
        help='以 JSON 格式输出',
    )
    parser.add_argument(
        '--font-size', '-s', type=int, default=None,
        help='显式指定基础字号 (pt)，不指定则从 .tex 文件解析',
    )
    parser.add_argument(
        '--cjk-scale', type=float, default=1.0,
        help='CJK 字体缩放因子（\\setCJKmainfont{...}[Scale=<val>]，默认 1.0）',
    )
    parser.add_argument(
        '--code-only', action='store_true',
        help='仅输出 LaTeX 代码行，供 pipeline 使用',
    )

    args = parser.parse_args()

    font_size = args.font_size

    if args.main_tex:
        tex_path = Path(args.main_tex)
        if not tex_path.exists():
            print(f"[ERROR] 文件不存在: {args.main_tex}", file=sys.stderr)
            sys.exit(1)
        if font_size is None:
            font_size = parse_font_size_from_tex(str(tex_path))
        if args.cjk_font is None:
            cjk_font = parse_cjk_font_from_tex(str(tex_path))
        else:
            cjk_font = args.cjk_font
    else:
        if font_size is None:
            font_size = 10
        cjk_font = args.cjk_font

    result = compute_baselineskip(
        font_size=font_size,
        latin_font=args.latin_font,
        cjk_font=cjk_font,
        cjk_scale=args.cjk_scale,
    )
    print(format_result(result, json_mode=args.json, code_only=args.code_only))


if __name__ == '__main__':
    main()

"""
根据拉丁字体风格自动匹配中文字体。

通过解析 .tex/.cls/.log 文件识别原始拉丁字体风格（衬线/无衬线/等宽），
然后从系统安装的中文字体中选择最佳匹配，输出 xeCJK 字体配置。

Usage:
    uv run python match_cjk_font.py main.tex
    uv run python match_cjk_font.py main.tex --json
    uv run python match_cjk_font.py main.tex --code-only
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ──────────────────────────── Latin Font Detection ────────────────────────────

SERIF_PACKAGES = {
    'libertine', 'libertinus', 'libertinust1math', 'times', 'mathptmx',
    'newtxtext', 'newtxmath', 'mathpazo', 'palatino', 'fouriernc',
    'bookman', 'charter', 'garamond', 'kpfonts', 'cochineal',
    'erewhon', 'baskervillef', 'stix', 'stix2',
}

SANS_PACKAGES = {
    'helvet', 'tgheros', 'tgadventor', 'arev',
    'sourcesanspro', 'noto', 'sfmath',
}

MONO_PACKAGES = {
    'courier', 'inconsolata', 'zi4', 'beramono',
    'luximono', 'tgcursor', 'sourcecodepro',
}


def _parse_font_packages(content: str) -> list[str]:
    """从 LaTeX 内容中提取所有 \\usepackage{...} 包名。"""
    packs = []
    for m in re.finditer(r'\\usepackage(?:\[[^\]]*\])?\s*\{([^}]+)\}', content):
        packs.extend(p.strip() for p in m.group(1).split(','))
    return packs


def _parse_font_families(content: str) -> dict:
    """从 LaTeX 内容中提取 \\renewcommand{\\(rm|sf|tt)default}{...} 设置。"""
    families = {}
    for key in ('rmdefault', 'sfdefault', 'ttdefault'):
        m = re.search(rf'\\renewcommand\s*\{{\\{key}\}}\s*\{{([^}}]+)\}}', content)
        if m:
            families[key] = m.group(1).strip()
    return families


def _parse_setmainfont(content: str) -> str | None:
    r"""从 LaTeX 内容中提取 \setmainfont{<name>}。"""
    m = re.search(r'\\setmainfont\s*\{([^}]+)\}', content)
    if m:
        return m.group(1).strip()
    return None


def classify_latin_style(tex_path: str) -> dict:
    """
    分析拉丁字体风格。

    返回:
        rm_style: 'serif' | 'sans' | 'mono' | 'unknown'
        sf_style: 'serif' | 'sans' | 'mono' | None
        tt_style: 'serif' | 'sans' | 'mono' | None
        main_font: 主字体名（若有）
    """
    tex_dir = Path(tex_path).parent

    # 1. 读取主 .tex 文件
    with open(tex_path, 'r', errors='ignore') as f:
        content = f.read()

    packages = _parse_font_packages(content)
    families = _parse_font_families(content)
    main_font = _parse_setmainfont(content)

    # 2. 读取文档类文件（.cls）
    cls_name = None
    m = re.search(r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{(\w+)\}', content)
    if m:
        cls_name = m.group(1)
    cls_content = ''
    if cls_name:
        cls_path = tex_dir / f"{cls_name}.cls"
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
        if cls_path.exists():
            with open(cls_path, 'r', errors='ignore') as f:
                cls_content = f.read()

    all_packages = packages + _parse_font_packages(cls_content)
    all_families = families
    cls_families = _parse_font_families(cls_content)
    for k, v in cls_families.items():
        if k not in all_families:
            all_families[k] = v

    # 3. 检测 rmfamily 风格
    rm_style = 'serif'  # 默认衬线
    for pkg in all_packages:
        if pkg in SERIF_PACKAGES:
            rm_style = 'serif'
            break
        if pkg in SANS_PACKAGES:
            rm_style = 'sans'
            break

    if 'rmdefault' in all_families:
        rmdefault = all_families['rmdefault'].lower()
        if any(s in rmdefault for s in ('phv', 'helv', 'arial', 'noto')):
            rm_style = 'sans'
        elif any(s in rmdefault for s in ('pcr', 'cmtt', 'lmtt', 'inconsolata')):
            rm_style = 'mono'

    # 4. 检测 sffamily 风格
    sf_style = None
    if 'sfdefault' in all_families:
        sfdefault = all_families['sfdefault'].lower()
        if any(s in sfdefault for s in ('phv', 'helv', 'arial', 'notosans')):
            sf_style = 'sans'
        elif any(s in sfdefault for s in ('lmr', 'cmr', 'times', 'libertine')):
            sf_style = 'serif'
        elif any(s in sfdefault for s in ('pcr', 'cmtt', 'lmtt')):
            sf_style = 'mono'
    else:
        sf_style = 'sans'  # LaTeX 默认 sffamily = 无衬线

    # 5. 检测 ttfamily 风格
    tt_style = 'mono'  # 默认等宽

    return {
        'rm_style': rm_style,
        'sf_style': sf_style,
        'tt_style': tt_style,
        'main_font': main_font,
    }


# ──────────────────────────── CJK Font Matching ────────────────────────────

CJK_SERIF_CANDIDATES = [
    'Noto Serif CJK SC',
    'Source Han Serif SC',
    'WenQuanYi Micro Hei',
    'WenQuanYi Zen Hei',
    'SimSun',
    'STSong',
    'AR PL UMing CN',
]

CJK_SANS_CANDIDATES = [
    'Noto Sans CJK SC',
    'Source Han Sans SC',
    'WenQuanYi Micro Hei',
    'WenQuanYi Zen Hei',
    'SimHei',
    'STHeiti',
    'AR PL UKai CN',
]

CJK_MONO_CANDIDATES = [
    'Noto Sans Mono CJK SC',
    'Source Han Sans SC',
    'WenQuanYi Micro Hei',
    'SimHei',
]


def get_available_cjk_fonts() -> list[str]:
    """通过 fc-list 获取系统可用的中日韩字体族名。"""
    try:
        result = subprocess.run(
            ['fc-list', ':lang=zh', 'family'],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        families = set()
        for line in result.stdout.splitlines():
            for part in line.split(','):
                part = part.strip()
                if part:
                    families.add(part)
        return sorted(families)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def match_font(candidates: list[str], available: list[str]) -> str | None:
    """从候选中选择第一个已安装的字体。"""
    avail_set = {f.lower() for f in available}
    for candidate in candidates:
        if candidate.lower() in avail_set:
            return candidate
        # 部分匹配
        for avail in available:
            if candidate.lower() in avail.lower():
                return avail
    return candidates[0] if candidates else None  # 回退到首选名


def match_cjk_fonts(tex_path: str) -> dict:
    """
    主逻辑：分析拉丁风格 → 匹配中文字体。

    返回 dict:
        cjk_main:   推荐 CJKmainfont
        cjk_sans:   推荐 CJKsansfont
        cjk_mono:   推荐 CJKmonofont
        rm_style:   拉丁 rmfamily 风格
        sf_style:   拉丁 sffamily 风格
        tt_style:   拉丁 ttfamily 风格
        main_font:  拉丁主字体名
        available:  系统可用 CJK 字体列表
    """
    style = classify_latin_style(tex_path)
    available = get_available_cjk_fonts()

    # 根据拉丁 rm 风格选择 CJK 主字体
    if style['rm_style'] == 'sans':
        cjk_main = match_font(CJK_SANS_CANDIDATES, available)
    elif style['rm_style'] == 'mono':
        cjk_main = match_font(CJK_MONO_CANDIDATES, available)
    else:
        cjk_main = match_font(CJK_SERIF_CANDIDATES, available)

    # sffamily
    if style['sf_style'] == 'serif':
        cjk_sans = match_font(CJK_SERIF_CANDIDATES, available)
    elif style['sf_style'] == 'mono':
        cjk_sans = match_font(CJK_MONO_CANDIDATES, available)
    else:
        cjk_sans = match_font(CJK_SANS_CANDIDATES, available)

    # ttfamily
    cjk_mono = match_font(CJK_MONO_CANDIDATES, available)

    return {
        'cjk_main': cjk_main,
        'cjk_sans': cjk_sans,
        'cjk_mono': cjk_mono,
        'rm_style': style['rm_style'],
        'sf_style': style['sf_style'],
        'tt_style': style['tt_style'],
        'main_font': style['main_font'],
        'available': available,
    }


# ──────────────────────────── Output Formatting ────────────────────────────

def format_result(result: dict, json_mode: bool = False, code_only: bool = False) -> str:
    """格式化输出匹配结果。"""
    if json_mode:
        return json.dumps({
            'cjk_main': result['cjk_main'],
            'cjk_sans': result['cjk_sans'],
            'cjk_mono': result['cjk_mono'],
            'latin_rm_style': result['rm_style'],
            'latin_sf_style': result['sf_style'],
            'latin_tt_style': result['tt_style'],
            'latin_main_font': result['main_font'],
        }, ensure_ascii=False)

    lines = []
    lines.append(f"拉丁 rmfamily 风格:  {result['rm_style']}")
    lines.append(f"拉丁 sffamily 风格:  {result['sf_style']}")
    lines.append(f"拉丁 ttfamily 风格:  {result['tt_style']}")
    if result['main_font']:
        lines.append(f"拉丁主字体:          {result['main_font']}")
    lines.append(f"推荐 CJKmainfont:   {result['cjk_main']}")
    lines.append(f"推荐 CJKsansfont:   {result['cjk_sans']}")
    lines.append(f"推荐 CJKmonofont:   {result['cjk_mono']}")
    if result['available']:
        lines.append(f"\n系统可用 CJK 字体:  {', '.join(result['available'][:8])}")
        if len(result['available']) > 8:
            lines.append(f"  ... 及其他 {len(result['available']) - 8} 种")

    if code_only:
        return (
            f"\\setCJKmainfont{{{result['cjk_main']}}}\n"
            f"\\setCJKsansfont{{{result['cjk_sans']}}}\n"
            f"\\setCJKmonofont{{{result['cjk_mono']}}}"
        )

    lines.append(f"\nLaTeX 代码:")
    lines.append(f"  \\setCJKmainfont{{{result['cjk_main']}}}")
    lines.append(f"  \\setCJKsansfont{{{result['cjk_sans']}}}")
    lines.append(f"  \\setCJKmonofont{{{result['cjk_mono']}}}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="根据拉丁字体风格自动匹配中文字体",
    )
    parser.add_argument(
        'main_tex',
        help='主 .tex 文件路径',
    )
    parser.add_argument(
        '--json', action='store_true',
        help='以 JSON 格式输出',
    )
    parser.add_argument(
        '--code-only', action='store_true',
        help='仅输出 LaTeX 代码行',
    )
    args = parser.parse_args()

    tex_path = Path(args.main_tex)
    if not tex_path.exists():
        print(f"[ERROR] 文件不存在: {args.main_tex}", file=sys.stderr)
        sys.exit(1)

    result = match_cjk_fonts(str(tex_path))
    print(format_result(result, json_mode=args.json, code_only=args.code_only))


if __name__ == '__main__':
    main()

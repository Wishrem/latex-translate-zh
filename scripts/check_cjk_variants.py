"""
检查 CJK 字体的粗体/斜体变体支持，输出 xeCJK fallback 配置。

通过 fc-list 查询指定字体的 Bold、Italic、BoldItalic 子面，
对缺失的变体生成 AutoFakeBold/AutoFakeSlant 配置。

Usage:
    uv run python check_cjk_variants.py "Noto Serif CJK SC"
    uv run python check_cjk_variants.py "Noto Serif CJK SC" --json
    uv run python check_cjk_variants.py "Noto Serif CJK SC" --code-only
"""

import argparse
import json
import re
import subprocess
import sys


# ──────────────────────────── Font Variant Detection ────────────────────────────

def get_font_styles(font_name: str) -> dict[str, str]:
    """
    通过 fc-list 查询字体的所有变体 (style → file path)。

    返回:
        'Regular':    /path/to/font.ttc
        'Bold':       /path/to/font.ttc  (or absent if not found)
        'Italic':     /path/to/font.ttc  (or absent)
        'Bold Italic': /path/to/font.ttc (or absent)
    """
    styles = {}
    try:
        result = subprocess.run(
            ['fc-list', font_name, 'style', 'file'],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return styles

        for line in result.stdout.splitlines():
            # Format: /path/to/font.ttc: style=Regular
            m = re.match(r'^(.+?):\s*style=(.+?)(?:,\w+)*\s*$', line)
            if m:
                file_path, style = m.group(1).strip(), m.group(2).strip()
                styles[style] = file_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return styles


def check_variants(font_name: str) -> dict:
    """
    检查字体变体支持。

    返回:
        font_name:    查询的字体名
        has_bold:     True/False
        has_italic:   True/False
        has_bold_italic: True/False
        styles:       所有检测到的 style 映射
        variants:     具体变体配置建议
        auto_fake_bold:  推荐的 AutoFakeBold 值（None 表示不需要）
        auto_fake_slant: 推荐的 AutoFakeSlant 值
    """
    styles = get_font_styles(font_name)

    style_names = set(s.lower() for s in styles.keys())

    has_bold = any(kw in style_names for kw in ('bold', 'black', 'heavy', 'semibold', 'demibold'))
    has_italic = any(kw in style_names for kw in ('italic', 'oblique', 'slanted'))
    has_bold_italic = any(
        ('bold' in s and ('italic' in s or 'oblique' in s)) for s in style_names
    )

    # 推荐配置
    variants = {}
    if has_bold:
        # 找到实际 Bold style 名
        for s in styles:
            if any(kw in s.lower() for kw in ('bold', 'black', 'heavy', 'semibold', 'demibold')):
                variants['BoldFont'] = font_name
                variants['BoldFeatures'] = f'{{Style={s}}}'
                break

    if has_italic:
        for s in styles:
            if any(kw in s.lower() for kw in ('italic', 'oblique', 'slanted')):
                variants['ItalicFont'] = font_name
                variants['ItalicFeatures'] = f'{{Style={s}}}'
                break

    if has_bold_italic:
        for s in styles:
            if 'bold' in s.lower() and ('italic' in s.lower() or 'oblique' in s.lower()):
                variants['BoldItalicFont'] = font_name
                variants['BoldItalicFeatures'] = f'{{Style={s}}}'
                break

    # AutoFake 建议值
    auto_fake_bold = 2.5 if not has_bold else None
    auto_fake_slant = 0.167 if not has_italic else None

    return {
        'font_name': font_name,
        'has_bold': has_bold,
        'has_italic': has_italic,
        'has_bold_italic': has_bold_italic,
        'styles': {k: v for k, v in styles.items()},
        'variants': variants,
        'auto_fake_bold': auto_fake_bold,
        'auto_fake_slant': auto_fake_slant,
    }


# ──────────────────────────── Output Formatting ────────────────────────────

def _format_font_options(variants: dict, auto_fake_bold: float | None,
                         auto_fake_slant: float | None, indent: str = '') -> str:
    """生成 xeCJK 字体选项（用于 setCJKmainfont 的 [] 内）。"""
    parts = []
    for key in ('BoldFont', 'ItalicFont', 'BoldItalicFont'):
        if key in variants:
            feat_key = key.replace('Font', 'Features')
            style_val = variants.get(feat_key, f'{{Style={variants[key]}}}')
            parts.append(f"{indent}  {key}={{{variants[key]}}},")
    if auto_fake_bold is not None:
        parts.append(f"{indent}  AutoFakeBold={{{auto_fake_bold}}},")
    if auto_fake_slant is not None:
        parts.append(f"{indent}  AutoFakeSlant={{{auto_fake_slant}}},")
    return "\n".join(parts)


def format_result(result: dict, json_mode: bool = False, code_only: bool = False) -> str:
    """格式化输出版本检查结果。"""
    if json_mode:
        return json.dumps({
            'font_name': result['font_name'],
            'has_bold': result['has_bold'],
            'has_italic': result['has_italic'],
            'has_bold_italic': result['has_bold_italic'],
            'auto_fake_bold': result['auto_fake_bold'],
            'auto_fake_slant': result['auto_fake_slant'],
            'detected_styles': list(result['styles'].keys()),
        }, ensure_ascii=False)

    lines = []
    fname = result['font_name']
    lines.append(f"字体:               {fname}")
    lines.append(f"检测到 {len(result['styles'])} 种变体: {', '.join(result['styles'].keys())}")

    bold_mark = "✓" if result['has_bold'] else "✗"
    italic_mark = "✓" if result['has_italic'] else "✗"
    bi_mark = "✓" if result['has_bold_italic'] else "✗"
    lines.append(f"Bold:               {bold_mark}")
    lines.append(f"Italic:             {italic_mark}")
    lines.append(f"BoldItalic:         {bi_mark}")

    # 推荐配置
    sections = []
    if result['auto_fake_bold'] is not None or result['auto_fake_slant'] is not None:
        xe = []
        if result['auto_fake_bold'] is not None:
            xe.append(f"AutoFakeBold={{{result['auto_fake_bold']}}}")
        if result['auto_fake_slant'] is not None:
            xe.append(f"AutoFakeSlant={{{result['auto_fake_slant']}}}")
        sections.append("\\xeCJKsetup{" + ", ".join(xe) + "}")

    # 字体级配置
    if result['variants'] or result['auto_fake_bold'] is not None or result['auto_fake_slant'] is not None:
        opts = _format_font_options(result['variants'],
                                     result['auto_fake_bold'],
                                     result['auto_fake_slant'])
        sections.append(f"\\setCJKmainfont{{{fname}}}[\n{opts}\n]")

    if code_only:
        return "\n".join(sections)

    if sections:
        lines.append(f"\n推荐配置:")
        lines.append("\n".join(sections))
    else:
        lines.append(f"\n无需额外配置（所有变体均已提供）。")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="检查 CJK 字体的粗体/斜体变体支持",
    )
    parser.add_argument(
        'font_name',
        help='CJK 字体名称（如 "Noto Serif CJK SC"）',
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

    result = check_variants(args.font_name)
    print(format_result(result, json_mode=args.json, code_only=args.code_only))


if __name__ == '__main__':
    main()

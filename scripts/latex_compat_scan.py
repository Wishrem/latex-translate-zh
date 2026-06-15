"""
LaTeX 中文兼容性风险扫描脚本

扫描 LaTeX 项目中的高风险结构，输出兼容性风险报告。
检测项：
  - mdframed/framed/tcolorbox 后紧跟 section/subsection
  - tabbing 中 \\> 层级是否超过 \\= 定义
  - \\xspace 宏是否出现在 caption/section/subsection 中
  - \\noindent\\textbf 形成 run-in heading
  - 负间距 \\vspace{-...} / \\hspace{-...} / \\vskip -...
  - ctexart 替换复杂模板风险

Usage:
    uv run python latex_compat_scan.py /path/to/latex/project
    uv run python latex_compat_scan.py /path/to/latex/project --json
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Finding:
    category: str
    file: str
    line: int
    content: str
    detail: str = ""


@dataclass
class ScanReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding):
        self.findings.append(finding)

    def by_category(self) -> dict[str, list[Finding]]:
        cats: dict[str, list[Finding]] = {}
        for f in self.findings:
            cats.setdefault(f.category, []).append(f)
        return cats

    def empty(self) -> bool:
        return len(self.findings) == 0


def _read_tex_files(root: Path) -> dict[str, str]:
    """Read all .tex files into a dict of {relpath: content}."""
    files = {}
    for tex in sorted(root.rglob("*.tex")):
        try:
            files[str(tex.relative_to(root))] = tex.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    return files


# ── Check: mdframed/framed/tcolorbox 后紧跟 section/subsection ──

def check_box_followed_by_section(files: dict[str, str], report: ScanReport):
    section_cmd = r"\\section\b|\\subsection\b|\\subsubsection\b|\\paragraph\b"
    for path, content in files.items():
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if re.search(r"\\end\{(mdframed|framed|tcolorbox|framedbox)\}", line):
                # Check next 5 lines for section
                for j in range(i, min(i + 6, len(lines) + 1)):
                    if re.search(section_cmd, lines[j - 1]):
                        report.add(Finding(
                            category="box_next_to_section",
                            file=path, line=j,
                            content=lines[j - 1].strip(),
                            detail=f"\\end{{{re.search(r'end\{([^}]+)\}', line).group(1)}}} 后 {j - i} 行出现 section",
                        ))
                        break


# ── Check: tabbing 中 \\> 层级超过 \\= 定义 ──

def _count_tabs_in_text(lines: list[str], start: int, end: int) -> int:
    """Count max consecutive \\> in body (between \\begin and \\end)."""
    max_depth = 0
    for i in range(start, end):
        line = lines[i]
        # Remove comments
        line = re.sub(r"(?<!\\)%.*$", "", line)
        # Count consecutive \>
        matches = re.findall(r"(\\>)+", line)
        for m in matches:
            depth = m.count("\\>")
            if depth > max_depth:
                max_depth = depth
    return max_depth


def _count_tab_stops_in_kill(lines: list[str], start: int, end: int) -> int:
    """Count \\= in \\kill line or set lines."""
    for i in range(start, end):
        line = lines[i]
        if "\\kill" in line:
            # Count \= in the kill line
            return line.count("\\=")
    return 0


def check_tabbing(files: dict[str, str], report: ScanReport):
    for path, content in files.items():
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)", line)
            indent_len = len(m.group(1)) if m else 0
            if re.search(r"\\begin\{tabbing\}", line):
                start = i
                # Find matching \end{tabbing} on same indent level
                end = None
                for j in range(i + 1, len(lines)):
                    m2 = re.match(r"^(\s*)", lines[j])
                    j_indent = len(m2.group(1)) if m2 else 0
                    if j_indent == indent_len and r"\end{tabbing}" in lines[j]:
                        end = j
                        break
                if end is None:
                    continue

                max_tabs = _count_tabs_in_text(lines, start + 1, end)
                tab_stops = _count_tab_stops_in_kill(lines, start + 1, end)

                if max_tabs > tab_stops:
                    report.add(Finding(
                        category="tabbing_insufficient_stops",
                        file=path, line=start + 1,
                        content=lines[start].strip(),
                        detail=f"最大 \\> 层级: {max_tabs}, \\= 定义数: {tab_stops}",
                    ))


# ── Check: \\xspace macro in caption/section ──

def check_fragile_in_moving_args(files: dict[str, str], report: ScanReport):
    moving_env = [
        r"\\caption\b",
        r"\\section\b", r"\\subsection\b", r"\\subsubsection\b",
        r"\\paragraph\b", r"\\title\b",
    ]
    moving_pattern = "|".join(moving_env)

    # Step 1: Find macros that use \xspace
    xspace_macros = set()
    for path, content in files.items():
        for m in re.finditer(
            r"\\newcommand\{\\([A-Za-z@]+)\}.*\\xspace|"
            r"\\DeclareRobustCommand\{\\([A-Za-z@]+)\}.*\\xspace|"
            r"\\def\\([A-Za-z@]+).*\\xspace",
            content,
        ):
            name = m.group(1) or m.group(2) or m.group(3) or ""
            if name:
                xspace_macros.add(name)

    if not xspace_macros:
        return

    # Step 2: Check if these macros appear in moving args
    for path, content in files.items():
        for m in re.finditer(
            rf"({moving_pattern})\s*\{{",
            content,
        ):
            cmd = m.group(1)
            # Find the matching closing brace for this specific caption/section
            pos = m.end()
            brace_count = 1
            end_pos = pos
            for j in range(pos, len(content)):
                if content[j] == "{":
                    brace_count += 1
                elif content[j] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = j
                        break

            arg_content = content[pos:end_pos]
            for macro in sorted(xspace_macros, key=len, reverse=True):
                if re.search(rf"\\{macro}\b", arg_content):
                    line_no = content[:m.start()].count("\n") + 1
                    report.add(Finding(
                        category="fragile_in_moving_arg",
                        file=path, line=line_no,
                        content=f"{cmd}... {{... \\{macro} ...}}",
                        detail=f"\\{macro} (含 \\xspace) 出现在 {cmd} 中",
                    ))


# ── Check: run-in heading (\\noindent\\textbf) ──

def check_runin_headings(files: dict[str, str], report: ScanReport):
    for path, content in files.items():
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            m = re.search(r"\\noindent\s*\\textbf\{([^}]+)\}", line)
            if m:
                title = m.group(1)
                report.add(Finding(
                    category="runin_heading",
                    file=path, line=i,
                    content=line.strip(),
                    detail=f'run-in heading: "{title}"',
                ))


# ── Check: negative spacing ──

def check_negative_spacing(files: dict[str, str], report: ScanReport):
    for path, content in files.items():
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if re.search(r"\\vspace\{-\d|\\hspace\{-\d|\\vskip\s*-\d", line):
                report.add(Finding(
                    category="negative_spacing",
                    file=path, line=i,
                    content=line.strip(),
                    detail="负间距在中文环境下可能触发重叠",
                ))


# ── Check: ctexart replacing complex template ──

def check_ctexart_risk(files: dict[str, str], report: ScanReport):
    for path, content in files.items():
        # Check for documentclass that might be replaced
        m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{(.+?)\}", content)
        if not m:
            continue
        cls_name = m.group(1).strip()

        if cls_name in ("article", "report", "book"):
            # Check if there are template-specific packages
            risk_signals = []
            if re.search(r"\\usepackage.*\{mdframed\}", content):
                risk_signals.append("mdframed")
            if re.search(r"\\usepackage.*\{tcolorbox\}", content):
                risk_signals.append("tcolorbox")
            if re.search(r"\\usepackage.*\{fontspec\}", content):
                risk_signals.append("fontspec")
            if re.search(r"\\(twocolumn|onecolumn)\b", content):
                risk_signals.append("多栏布局")
            if re.search(r"\\usepackage.*\{geometry\}", content):
                risk_signals.append("自定义版面")

            if risk_signals:
                report.add(Finding(
                    category="ctexart_risk",
                    file=path, line=1,
                    content=f"\\documentclass{{{cls_name}}} + {{{', '.join(risk_signals)}}}",
                    detail=f"包含 {'、'.join(risk_signals)}，替换为 ctex{cls_name[:3]} 有高风险",
                ))


# ── Main ──

def scan_project(root: Path) -> ScanReport:
    report = ScanReport()
    files = _read_tex_files(root)

    check_box_followed_by_section(files, report)
    check_tabbing(files, report)
    check_fragile_in_moving_args(files, report)
    check_runin_headings(files, report)
    check_negative_spacing(files, report)
    check_ctexart_risk(files, report)

    return report


def print_report(report: ScanReport, json_output: bool = False):
    if json_output:
        data = {
            "total_findings": len(report.findings),
            "by_category": {
                cat: [
                    {"file": f.file, "line": f.line, "detail": f.detail}
                    for f in findings
                ]
                for cat, findings in report.by_category().items()
            },
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if report.empty():
        print("✓ 未发现中文兼容性风险")
        return

    print(f"\n# 中文兼容性风险报告 ({len(report.findings)} 项)\n")

    cat_labels = {
        "box_next_to_section": "Box/Frame 环境后紧跟 section",
        "tabbing_insufficient_stops": "Tabbing tab 位不足",
        "fragile_in_moving_arg": "Fragile macro 出现在 moving arguments",
        "runin_heading": "Run-in heading",
        "negative_spacing": "负间距",
        "ctexart_risk": "ctexart 替换风险",
    }

    for cat, findings in sorted(report.by_category().items()):
        label = cat_labels.get(cat, cat)
        print(f"## {label}  ({len(findings)} 处)\n")
        for f in findings:
            print(f"  - {f.file}:{f.line}  {f.detail}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="LaTeX 中文兼容性风险扫描",
    )
    parser.add_argument(
        "project_dir",
        help="LaTeX 项目目录路径",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 格式",
    )
    args = parser.parse_args()

    root = Path(args.project_dir)
    if not root.is_dir():
        print(f"[ERROR] 目录不存在: {args.project_dir}", file=sys.stderr)
        sys.exit(1)

    report = scan_project(root)
    print_report(report, json_output=args.json)

    if not args.json:
        print(f"\n共发现 {len(report.findings)} 个潜在风险，翻译时请针对性防御。")

    sys.exit(0 if len(report.findings) == 0 else 1)


if __name__ == "__main__":
    main()

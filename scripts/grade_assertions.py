"""Grade assertions for latex-translate-zh eval."""
import json
import re
import sys
from pathlib import Path

def check_assertions(run_dir: str) -> list[dict]:
    tex_file = Path(run_dir) / "main_zh.tex"
    pdf_file = Path(run_dir) / "main_zh.pdf"
    log_file = Path(run_dir) / "build.log"

    results = []

    # Assertion 1: main_zh.tex exists
    tex_exists = tex_file.exists()
    results.append({
        "text": "main_zh.tex file created with translated content",
        "passed": tex_exists,
        "evidence": f"File {tex_file} exists={tex_exists}" + (
            f", size={tex_file.stat().st_size}B" if tex_exists else ""
        )
    })

    # Assertion 2: main_zh.pdf compiled
    pdf_exists = pdf_file.exists()
    results.append({
        "text": "main_zh.pdf compiled successfully from the translated tex",
        "passed": pdf_exists,
        "evidence": f"File {pdf_file} exists={pdf_exists}" + (
            f", size={pdf_file.stat().st_size}B" if pdf_exists else ""
        )
    })

    if not tex_exists:
        return results

    content = tex_file.read_text(encoding="utf-8", errors="ignore")

    # Assertion 3: LaTeX commands preserved
    latex_commands = [
        r'\\section\{', r'\\subsection\{', r'\\begin\{equation\}',
        r'\\cite\{', r'\\ref\{', r'\\label\{',
        r'\\begin\{table\}', r'\\begin\{figure\}',
        r'\\begin\{itemize\}', r'\\begin\{thebibliography\}'
    ]
    found_cmds = [c for c in latex_commands if re.search(c, content)]
    all_preserved = len(found_cmds) >= 7  # At least 7 of 10 key commands
    results.append({
        "text": "Translation preserves all LaTeX commands (section, equation, cite, ref, label)",
        "passed": all_preserved,
        "evidence": f"Found {len(found_cmds)}/10 key LaTeX commands: {found_cmds}"
    })

    # Assertion 4: Math environments preserved
    has_math = bool(re.search(r'\$.*\$|\$\$.*\$\$|\\begin\{equation\}', content, re.DOTALL))
    has_math_symbols = bool(re.search(r'\\mathcal|\\theta|\\eta|\\mathbb', content))
    results.append({
        "text": "Translation preserves math environments and formulas unchanged",
        "passed": has_math and has_math_symbols,
        "evidence": f"Has math env={has_math}, has math symbols={has_math_symbols}"
    })

    # Assertion 5: Figure/table captions translated (contain Chinese)
    caption_cn = bool(re.search(r'\\caption\{.*[\u4e00-\u9fff]', content, re.DOTALL))
    results.append({
        "text": "Figure/table captions translated to Chinese",
        "passed": caption_cn,
        "evidence": f"Chinese found in captions={caption_cn}"
    })

    # Assertion 6: Section titles translated (contain Chinese)
    section_cn = bool(re.search(r'\\section\{.*[\u4e00-\u9fff]', content, re.DOTALL))
    results.append({
        "text": "Section titles translated to Chinese",
        "passed": section_cn,
        "evidence": f"Chinese found in section titles={section_cn}"
    })

    # Assertion 7: References not translated (bibliography contains English)
    # Find thebibliography block and check it has English content
    bib_match = re.search(
        r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}',
        content, re.DOTALL
    )
    if bib_match:
        bib_content = bib_match.group(0)
        # References should have English author names, titles etc.
        has_english = bool(re.search(r'[A-Za-z]{10,}', bib_content))
        has_less_chinese = len(re.findall(r'[\u4e00-\u9fff]', bib_content)) < 20
        ref_preserved = has_english and has_less_chinese
    else:
        ref_preserved = False

    results.append({
        "text": "References section not translated (bibliography preserved as-is)",
        "passed": ref_preserved,
        "evidence": f"Bibliography found={bool(bib_match)}, has English content={has_english if bib_match else 'N/A'}"
    })

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: grade.py <run_outputs_dir>")
        sys.exit(1)

    run_dir = sys.argv[1]
    results = check_assertions(run_dir)

    out = Path(run_dir).parent / "grading.json"
    out.write_text(json.dumps({"expectations": results}, indent=2, ensure_ascii=False))
    print(f"Grading written to {out}")

    passed = sum(1 for r in results if r["passed"])
    print(f"Passed: {passed}/{len(results)}")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r['text']}")
        print(f"         {r['evidence']}")


if __name__ == "__main__":
    main()

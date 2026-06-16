"""
LaTeX Compilation Script - 中文学位论文编译器 (xelatex/lualatex)

默认行为:
    使用 latexmk + XeLaTeX 自动处理所有依赖（bibtex/biber、交叉引用、
    索引、术语表），并自动决定最优编译次数。这是中文论文的推荐方案。

Usage:
    uv run python compile.py main.tex                       # 默认: latexmk + xelatex
    uv run python compile.py main.tex --compiler xelatex    # 显式指定编译器
    uv run python compile.py main.tex --recipe xelatex-bibtex  # 传统 BibTeX
    uv run python compile.py main.tex --recipe xelatex-biber   # 现代 biblatex
    uv run python compile.py main.tex --watch               # 监视模式
    uv run python compile.py main.tex --clean               # 清理辅助文件

Recipes (中文论文推荐 XeLaTeX/LuaLaTeX):
    latexmk          - LaTeXmk + XeLaTeX 自动处理 (默认 - 推荐)
    xelatex          - XeLaTeX 单次编译
    lualatex         - LuaLaTeX 单次编译
    xelatex-bibtex   - xelatex -> bibtex -> xelatex*2 (传统)
    xelatex-biber    - xelatex -> biber -> xelatex*2 (现代 biblatex)
    lualatex-bibtex  - lualatex -> bibtex -> lualatex*2
    lualatex-biber   - lualatex -> biber -> lualatex*2
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


class LaTeXCompiler:
    """Unified LaTeX compilation with multiple recipes."""

    COMPILERS = {"pdflatex", "xelatex", "lualatex"}

    # Default recipe: latexmk with XeLaTeX for Chinese documents (best practice)
    # latexmk auto-detects bibtex/biber needs and runs the correct number of passes
    DEFAULT_RECIPE = "latexmk"

    # Recipes matching VS Code LaTeX Workshop configuration
    # Chinese thesis: XeLaTeX/LuaLaTeX recommended for proper CJK support
    # Recommended workflow:
    #   - latexmk (default): Auto-detect and handle all dependencies with XeLaTeX
    #   - xelatex-bibtex: Traditional BibTeX workflow (legacy .bst styles)
    #   - xelatex-biber: Modern biblatex + biber workflow (recommended for new theses)
    RECIPES = {
        # Single compilation (quick builds)
        "xelatex": ["xelatex"],
        "lualatex": ["lualatex"],
        "latexmk": ["latexmk-xelatex"],  # Default: XeLaTeX + auto-handles bibtex/biber
        # Full workflows (explicit control over compilation steps)
        "xelatex-bibtex": ["xelatex", "bibtex", "xelatex", "xelatex"],
        "xelatex-biber": ["xelatex", "biber", "xelatex", "xelatex"],
        "lualatex-bibtex": ["lualatex", "bibtex", "lualatex", "lualatex"],
        "lualatex-biber": ["lualatex", "biber", "lualatex", "lualatex"],
    }

    # Patterns indicating Chinese content
    CHINESE_PATTERNS = [
        r"\\usepackage.*{ctex}",
        r"\\usepackage.*{xeCJK}",
        r"\\documentclass.*{ctexart}",
        r"\\documentclass.*{ctexbook}",
        r"\\documentclass.*{ctexrep}",
        r"\\documentclass.*{thuthesis}",
        r"\\documentclass.*{pkuthss}",
        r"\\documentclass.*{ustcthesis}",
        r"\\documentclass.*{fduthesis}",
        r"[\u4e00-\u9fff]",  # Chinese characters
    ]

    def __init__(
        self,
        tex_file: str,
        compiler: Optional[str] = None,
        recipe: Optional[str] = None,
        shell_escape: bool = False,
    ):
        self.tex_file = Path(tex_file).resolve()
        self.work_dir = self.tex_file.parent
        self.compiler = compiler or self._detect_compiler()
        self.recipe = recipe
        self.shell_escape = shell_escape

    def _detect_compiler(self) -> str:
        """Auto-detect appropriate compiler based on document content."""
        try:
            content = self.tex_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return "pdflatex"  # Default fallback

        # Check for Chinese content
        for pattern in self.CHINESE_PATTERNS:
            if re.search(pattern, content):
                print("[INFO] Detected Chinese content, using xelatex")
                return "xelatex"

        # Check for explicit engine specification
        if re.search(r"%\s*!TEX\s+program\s*=\s*xelatex", content, re.IGNORECASE):
            return "xelatex"
        if re.search(r"%\s*!TEX\s+program\s*=\s*lualatex", content, re.IGNORECASE):
            return "lualatex"
        if re.search(r"%\s*!TEX\s+program\s*=\s*pdflatex", content, re.IGNORECASE):
            return "pdflatex"

        # Check for fontspec (requires xelatex or lualatex)
        if re.search(r"\\usepackage.*{fontspec}", content):
            print("[INFO] Detected fontspec package, using xelatex")
            return "xelatex"

        return "pdflatex"

    def _check_tools_for_compiler(self) -> tuple[bool, str]:
        """Check tools required for latexmk-based compilation."""
        if not shutil.which("latexmk"):
            return False, "latexmk not found — 请先安装"

        compiler_cmd = self.compiler
        if not shutil.which(compiler_cmd):
            return False, f"{compiler_cmd} not found — 请先安装"

        return True, "All tools available"

    def _check_tools_for_recipe(self) -> tuple[bool, str]:
        """Check tools required by a recipe."""
        steps = self.RECIPES.get(self.recipe, [])
        required = []
        for step in steps:
            if step == "latexmk-xelatex":
                required.extend(["latexmk", "xelatex"])
            elif step == "latexmk-lualatex":
                required.extend(["latexmk", "lualatex"])
            elif step in ("xelatex", "lualatex", "bibtex", "biber"):
                required.append(step)

        for tool in dict.fromkeys(required):
            if not shutil.which(tool):
                return False, f"{tool} not found. Install TeX Live or MiKTeX."

        return True, "All tools available"

    def _engine_shell_mode_arg(self) -> str:
        """Return the explicit shell-escape mode passed to TeX engines."""
        return "-shell-escape" if self.shell_escape else "-no-shell-escape"

    def _latexmk_engine_args(self) -> list[str]:
        """Build latexmk engine args with explicit shell-escape mode."""
        if self.compiler not in self.COMPILERS:
            return ["-pdf"]

        engine = self.compiler
        engine = f"{engine} {self._engine_shell_mode_arg()}"

        if self.compiler == "pdflatex":
            return ["-pdf", f"-pdflatex={engine} %O %S"]
        if self.compiler == "xelatex":
            return ["-xelatex", "-pdfxe", f"-xelatex={engine} %O %S"]
        return ["-lualatex", "-pdflua", f"-lualatex={engine} %O %S"]

    def _maybe_warn_shell_escape(self) -> None:
        if self.shell_escape:
            print("[WARNING] Shell escape enabled. Only use with trusted sources.")

    def _log_file(self, outdir: Optional[str] = None) -> Path:
        if outdir:
            return (self.work_dir / outdir / self.tex_file.with_suffix(".log").name).resolve()
        return self.tex_file.with_suffix(".log")

    def _validate_log(self, outdir: Optional[str] = None) -> tuple[bool, list[str]]:
        """Reject PDFs produced from logs that still contain real TeX errors."""
        log_file = self._log_file(outdir)
        if not log_file.exists():
            return False, [f"日志文件不存在: {log_file}"]

        text = log_file.read_text(encoding="utf-8", errors="ignore")
        problems: list[str] = []

        error_lines = []
        for line in text.splitlines():
            if line.startswith("! "):
                # Font warnings are logged as warnings, not bang-errors. Any
                # remaining bang line means TeX recovered after a real error.
                error_lines.append(line.strip())
                if len(error_lines) >= 12:
                    break
        if error_lines:
            problems.append("LaTeX 错误仍存在: " + " | ".join(error_lines))

        failure_patterns = [
            r"Emergency stop",
            r"Fatal error occurred",
            r"Undefined control sequence",
            r"Misplaced alignment tab character",
            r"Missing \$ inserted",
            r"Extra \}, or forgotten",
            r"File `[^']+' not found",
            r"Unable to load picture or PDF file",
            r"Package graphics Error",
        ]
        for pattern in failure_patterns:
            if re.search(pattern, text):
                problems.append(f"日志匹配失败模式: {pattern}")

        unresolved_patterns = [
            r"undefined references",
            r"Citation .* undefined",
            r"Reference .* undefined",
            r"There were undefined references",
            r"Label\(s\) may have changed",
        ]
        for pattern in unresolved_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                problems.append(f"交叉引用/引用未稳定: {pattern}")

        return not problems, problems

    def _report_validation(self, outdir: Optional[str] = None) -> int:
        pdf_file = self.tex_file.with_suffix(".pdf")
        if outdir:
            pdf_file = (self.work_dir / outdir / pdf_file.name).resolve()
        if not pdf_file.exists():
            print(f"\n[ERROR] PDF not found: {pdf_file}")
            return 1

        ok, problems = self._validate_log(outdir)
        if not ok:
            print(f"\n[ERROR] PDF was produced but validation failed: {pdf_file}")
            for problem in problems[:10]:
                print(f"  - {problem}")
            return 1

        print(f"\n[SUCCESS] PDF generated and validated: {pdf_file}")
        return 0

    def compile(
        self, watch: bool = False, biber: bool = False, outdir: Optional[str] = None
    ) -> int:
        """
        Compile the LaTeX document.

        Args:
            watch: Enable continuous compilation mode
            biber: Use biber instead of bibtex
            outdir: Output directory for generated files

        Returns:
            Exit code (0 for success)
        """
        # Check tools
        if self.recipe:
            ok, msg = self._check_tools_for_recipe()
            if not ok:
                print(f"[ERROR] {msg}")
                return 1
        else:
            ok, msg = self._check_tools_for_compiler()
            if not ok:
                print(f"[ERROR] {msg}")
                return 1

        # If recipe is set, use recipe-based compilation
        if self.recipe:
            return self._compile_with_recipe(outdir)

        print(f"[INFO] Compiling {self.tex_file.name} with {self.compiler}")
        print(f"[INFO] Working directory: {self.work_dir}")
        self._maybe_warn_shell_escape()

        # Build latexmk command
        cmd = ["latexmk"]

        # Add compiler-specific options
        cmd.extend(self._latexmk_engine_args())

        # Add common options
        cmd.extend(
            [
                "-interaction=nonstopmode",
                "-file-line-error",
                "-synctex=1",
            ]
        )

        # Biber support
        if biber:
            cmd.append("-use-biber")

        # Watch mode
        if watch:
            cmd.append("-pvc")
            print("[INFO] Watch mode enabled. Press Ctrl+C to stop.")

        # Add input file
        cmd.append(str(self.tex_file))

        # Run compilation
        try:
            result = subprocess.run(
                cmd,
                cwd=self.work_dir,
                capture_output=False,
            )
            if result.returncode == 0:
                return self._report_validation(outdir)
            else:
                print(f"\n[ERROR] Compilation failed with exit code {result.returncode}")
            return result.returncode

        except KeyboardInterrupt:
            print("\n[INFO] Compilation stopped by user")
            return 0
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1

    def _compile_with_recipe(self, outdir: Optional[str] = None) -> int:
        """Compile using a predefined recipe (VS Code LaTeX Workshop style)."""
        if self.recipe not in self.RECIPES:
            print(f"[ERROR] Unknown recipe: {self.recipe}")
            print(f"[INFO] Available recipes: {', '.join(self.RECIPES.keys())}")
            return 1

        steps = self.RECIPES[self.recipe]
        print(f"[INFO] Using recipe: {self.recipe}")
        print(f"[INFO] Steps: {' -> '.join(steps)}")
        print(f"[INFO] Working directory: {self.work_dir}")
        self._maybe_warn_shell_escape()

        tex_base = self.tex_file.stem

        for i, step in enumerate(steps, 1):
            print(f"\n[STEP {i}/{len(steps)}] Running {step}...")

            if step == "latexmk-xelatex":
                cmd = [
                    "latexmk",
                    "-xelatex",
                    f"-xelatex=xelatex {self._engine_shell_mode_arg()} %O %S",
                    "-interaction=nonstopmode",
                    "-synctex=1",
                    "-file-line-error",
                ]
                if outdir:
                    cmd.append(f"-outdir={outdir}")
                cmd.append(str(self.tex_file))
            elif step == "latexmk-lualatex":
                cmd = [
                    "latexmk",
                    "-lualatex",
                    f"-lualatex=lualatex {self._engine_shell_mode_arg()} %O %S",
                    "-interaction=nonstopmode",
                    "-synctex=1",
                    "-file-line-error",
                ]
                if outdir:
                    cmd.append(f"-outdir={outdir}")
                cmd.append(str(self.tex_file))
            elif step in ("xelatex", "lualatex"):
                cmd = [
                    step,
                    "-interaction=nonstopmode",
                    "-synctex=1",
                    self._engine_shell_mode_arg(),
                    str(self.tex_file),
                ]
            elif step == "bibtex":
                cmd = ["bibtex", tex_base]
            elif step == "biber":
                cmd = ["biber", tex_base]
            else:
                print(f"[ERROR] Unknown step: {step}")
                return 1

            try:
                result = subprocess.run(
                    cmd,
                    cwd=self.work_dir,
                    capture_output=False,
                )
                if result.returncode != 0:
                    # bibtex/biber may return non-zero for warnings, continue anyway
                    if step not in ("bibtex", "biber"):
                        print(f"[ERROR] Step {step} failed with exit code {result.returncode}")
                        return result.returncode
                    else:
                        print(f"[WARNING] {step} returned {result.returncode}, continuing...")

            except FileNotFoundError:
                print(f"[ERROR] {step} not found. Please install it.")
                return 1
            except Exception as e:
                print(f"[ERROR] {e}")
                return 1

        return self._report_validation(outdir)

    @staticmethod
    def _detect_os_info() -> dict:
        """Detect OS and package manager for install hints."""
        system = platform.system()
        if system == "Linux":
            # Check for specific distro
            try:
                import distro as distro_pkg
                distro_id = distro_pkg.id()
            except ImportError:
                distro_id = ""
            # Fallback: check known package managers
            if shutil.which("apt"):
                return {"os": "linux-deb", "pkg": "apt", "cmd": "sudo apt-get install -y", "prefix": ""}
            elif shutil.which("pacman"):
                return {"os": "linux-arch", "pkg": "pacman", "cmd": "sudo pacman -S --noconfirm", "prefix": ""}
            elif shutil.which("dnf"):
                return {"os": "linux-rpm", "pkg": "dnf", "cmd": "sudo dnf install -y", "prefix": "texlive-"}
            elif shutil.which("yum"):
                return {"os": "linux-rpm", "pkg": "yum", "cmd": "sudo yum install -y", "prefix": "texlive-"}
            elif shutil.which("zypper"):
                return {"os": "linux-suse", "pkg": "zypper", "cmd": "sudo zypper install -y", "prefix": "texlive-"}
            else:
                return {"os": "linux", "pkg": "unknown", "cmd": "", "prefix": ""}
        elif system == "Darwin":
            return {"os": "macos", "pkg": "brew", "cmd": "brew install", "prefix": ""}
        elif system == "Windows":
            return {"os": "windows", "pkg": "winget", "cmd": "winget install", "prefix": ""}
        else:
            return {"os": "unknown", "pkg": "unknown", "cmd": "", "prefix": ""}

    @classmethod
    def _check_chinese_fonts(cls) -> dict:
        """Check availability of common Chinese fonts.

        Returns:
            dict: {family_name: {"available": bool, "sample": str}}
        """
        RECOMMENDED = [
            "Noto Serif CJK SC", "Noto Sans CJK SC",
            "Source Han Serif SC", "Source Han Sans SC",
            "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
            "SimSun", "SimHei", "KaiTi", "FangSong",
            "AR PL UMing CN", "AR PL UKai CN",
        ]
        found = {f: {"available": False, "sample": ""} for f in RECOMMENDED}

        # Try fc-list first (standard on Linux/macOS with fontconfig)
        try:
            result = subprocess.run(
                ["fc-list", ":lang=zh", "family"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    family = line.strip().rstrip(',')
                    for name in RECOMMENDED:
                        if name in family:
                            found[name]["available"] = True
                            found[name]["sample"] = family[:80]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: check known font file paths
        for name in RECOMMENDED:
            if not found[name]["available"]:
                pass  # glob check skipped — fc-list is definitive enough

        return found

    @classmethod
    def check_tools(cls) -> dict:
        """Check availability of all compilation tools and Chinese fonts.

        Does NOT hardcode package names — caller should web-search for the
        correct install command on the detected distro.

        Returns:
            dict with keys: os_info, tools, fonts, missing
        """
        os_info = cls._detect_os_info()

        tools = {
            "xelatex": "xelatex", "xetex": "xetex",
            "lualatex": "lualatex", "luatex": "luatex",
            "pdflatex": "pdflatex", "latexmk": "latexmk",
            "bibtex": "bibtex", "biber": "biber",
        }
        results = {}
        for name, cmd in tools.items():
            path = shutil.which(cmd)
            results[name] = {"available": path is not None, "path": path or ""}

        # Chinese font detection
        fonts = cls._check_chinese_fonts()

        # Print report
        pkg_name = os_info["pkg"].upper()
        print("\n" + "=" * 55)
        print(f"  LaTeX 编译工具链检测  [{os_info['os']}/{pkg_name}]")
        print("=" * 55)
        print("  --- 编译引擎 ---")
        missing = []
        engine_names = ["xelatex", "xetex", "lualatex", "luatex", "pdflatex"]
        for name in engine_names:
            info = results[name]
            if info["available"]:
                print(f"  [OK]  {name:<12}  {info['path']}")
            else:
                print(f"  [MISS] {name:<12}  (请 web 搜索安装方式)")
                missing.append(name)
        print("  --- 构建工具 ---")
        for name in ["latexmk", "bibtex", "biber"]:
            info = results[name]
            if info["available"]:
                print(f"  [OK]  {name:<12}  {info['path']}")
            else:
                print(f"  [MISS] {name:<12}  (请 web 搜索安装方式)")
                missing.append(name)
        print("  --- 中文字体（推荐） ---")
        font_missing = []
        for fname, finfo in fonts.items():
            if finfo["available"]:
                print(f"  [OK]  {fname:<24}")
            else:
                font_missing.append(fname)
        if font_missing:
            print(f"  缺失推荐字体: {', '.join(font_missing)}")
            print(f"  (至少需要一种中文字体用于编译)")
        print("-" * 55)
        print(f"  编译工具: {sum(1 for n in tools if results[n]['available'])}/{len(tools)}")
        print(f"  中文字体: {sum(1 for f in fonts.values() if f['available'])}/{len(fonts)}")
        print("=" * 55)

        # Output structured JSON
        report = {
            "os": os_info["os"],
            "package_manager": os_info["pkg"],
            "tools": results,
            "fonts": {k: v["available"] for k, v in fonts.items()},
            "missing_tools": missing,
            "missing_fonts": font_missing,
            "search_query": f"install {' '.join(missing)} on {platform.system()} {os_info['pkg']}",
        }
        print("\n[TOOLS_JSON] " + json.dumps(report, ensure_ascii=False) + "\n")
        return report

    def clean(self, full: bool = False) -> int:
        """
        Clean auxiliary files.

        Args:
            full: Also remove output PDF

        Returns:
            Exit code (0 for success)
        """
        print(f"[INFO] Cleaning auxiliary files in {self.work_dir}")

        cmd = ["latexmk", "-c"]
        if full:
            cmd = ["latexmk", "-C"]

        cmd.append(str(self.tex_file))

        try:
            result = subprocess.run(cmd, cwd=self.work_dir, capture_output=True)
            if result.returncode == 0:
                print("[SUCCESS] Auxiliary files cleaned")
            return result.returncode
        except Exception as e:
            print(f"[ERROR] {e}")
            return 1


def main():
    parser = argparse.ArgumentParser(
        description="LaTeX 中文学位论文编译脚本 - 支持 xelatex/lualatex",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
默认行为:
  使用 latexmk + XeLaTeX 自动处理所有依赖（bibtex/biber、交叉引用等），
  并自动决定最优编译次数。这是中文论文的推荐方案。

Recipes (中文论文推荐 XeLaTeX):
  latexmk          LaTeXmk + XeLaTeX 自动处理 (默认 - 推荐)
  xelatex          XeLaTeX 单次编译
  lualatex         LuaLaTeX 单次编译
  xelatex-bibtex   xelatex -> bibtex -> xelatex*2 (传统 BibTeX)
  xelatex-biber    xelatex -> biber -> xelatex*2 (现代 biblatex)
  lualatex-bibtex  lualatex -> bibtex -> lualatex*2
  lualatex-biber   lualatex -> biber -> lualatex*2

Examples:
  uv run python compile.py main.tex                        # 默认: latexmk + xelatex
  uv run python compile.py main.tex --recipe xelatex-bibtex  # 传统 BibTeX
  uv run python compile.py main.tex --recipe xelatex-biber   # 现代 biblatex
  uv run python compile.py main.tex --watch                # 监视模式
        """,
    )
    parser.add_argument("tex_file", nargs="?", help="主 .tex 文件路径 (--check-tools 时可选)")
    parser.add_argument("-d", "--dir", dest="work_dir_arg", help="包含主 .tex 的目录（兼容 AGENTS.md 常用命令）")
    parser.add_argument("--main", default="main.tex", help="-d/--dir 模式下的主 .tex 文件名，默认 main.tex")
    parser.add_argument(
        "--compiler",
        "-c",
        choices=["pdflatex", "xelatex", "lualatex"],
        help="编译器 (未指定时自动检测，中文默认 xelatex)",
    )
    parser.add_argument(
        "--recipe",
        "-r",
        choices=[
            "xelatex",
            "lualatex",
            "latexmk",
            "xelatex-bibtex",
            "xelatex-biber",
            "lualatex-bibtex",
            "lualatex-biber",
        ],
        help="使用预定义编译配置 (中文推荐 XeLaTeX)",
    )
    parser.add_argument("--watch", "-w", action="store_true", help="启用监视模式 (持续编译)")
    parser.add_argument("--biber", "-b", action="store_true", help="使用 biber 处理参考文献")
    parser.add_argument(
        "--shell-escape",
        action="store_true",
        help="启用 shell-escape (需要 --trusted-source)",
    )
    parser.add_argument(
        "--trusted-source",
        action="store_true",
        help="确认 LaTeX 源文件可信后再启用 shell-escape",
    )
    parser.add_argument("--clean", action="store_true", help="清理辅助文件")
    parser.add_argument("--clean-all", action="store_true", help="清理所有生成文件 (含 PDF)")
    parser.add_argument("--outdir", "-o", help="输出目录 (仅 latexmk 配置支持)")
    parser.add_argument(
        "--check-tools",
        action="store_true",
        help="检测编译工具链可用性（不编译）",
    )

    args = parser.parse_args()

    # Tool check mode: no tex file needed
    if args.check_tools:
        LaTeXCompiler.check_tools()
        sys.exit(0)

    # Validate input file
    tex_arg = args.tex_file
    if args.work_dir_arg and not tex_arg:
        tex_arg = str(Path(args.work_dir_arg) / args.main)
    if not tex_arg:
        parser.error("需要提供 tex_file，或使用 -d/--dir 指定目录")

    tex_path = Path(tex_arg)
    if not tex_path.exists():
        print(f"[ERROR] 文件不存在: {tex_arg}")
        sys.exit(1)

    if tex_path.suffix != ".tex":
        print(f"[WARNING] 文件扩展名不是 .tex: {args.tex_file}")

    if args.shell_escape and not args.trusted_source:
        print(
            "[ERROR] --shell-escape 可执行 LaTeX 源文件中的命令。"
            "确认源文件可信后再同时传入 --trusted-source。"
        )
        sys.exit(1)

    # Create compiler instance
    compiler = LaTeXCompiler(
        tex_arg,
        args.compiler,
        args.recipe,
        shell_escape=args.shell_escape,
    )

    # Execute requested action
    if args.clean or args.clean_all:
        sys.exit(compiler.clean(full=args.clean_all))
    else:
        sys.exit(
            compiler.compile(
                watch=args.watch,
                biber=args.biber,
                outdir=args.outdir,
            )
        )


if __name__ == "__main__":
    main()

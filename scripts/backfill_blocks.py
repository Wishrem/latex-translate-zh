"""
将翻译结果回填到 LaTeX 文件中。

读取翻译 JSON（block_id → translation），在指定项目中
查找每个 block_id 对应的源文本并替换为译文。

Usage:
    uv run python backfill_blocks.py /path/to/project translations.json

translations.json 格式:
    {
      "blocks": [
        {"block_id": "blk_0001", "translation": "中文译文"},
        ...
      ]
    }
    或 JSONL 格式（每行一个翻译块）。
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional


def _find_matching_brace(s: str, pos: int) -> int:
    """Find matching closing brace/bracket. pos points to the opening char."""
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


def load_translations(trans_file: Path) -> dict[str, str]:
    """Load translations from JSON or JSONL file."""
    text = trans_file.read_text(encoding="utf-8", errors="ignore").strip()

    translations: dict[str, str] = {}

    # Try JSON array/object
    try:
        data = json.loads(text)
        if isinstance(data, list):
            for item in data:
                translations[item["block_id"]] = item["translation"]
        elif isinstance(data, dict):
            if "blocks" in data:
                for item in data["blocks"]:
                    translations[item["block_id"]] = item["translation"]
            elif "block_id" in data:
                translations[data["block_id"]] = data["translation"]
        return translations
    except json.JSONDecodeError:
        pass

    # Try JSONL
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            translations[item["block_id"]] = item["translation"]
        except (json.JSONDecodeError, KeyError):
            continue

    return translations


def load_source_blocks(blocks_file: Optional[Path], translations: dict[str, str]) -> dict[str, dict]:
    """Load source blocks to get source_text and file info."""
    if not blocks_file or not blocks_file.exists():
        return {}

    text = blocks_file.read_text(encoding="utf-8", errors="ignore").strip()
    blocks: dict[str, dict] = {}

    try:
        data = json.loads(text)
        items = data.get("blocks", data if isinstance(data, list) else [])
        for item in items:
            if item.get("block_id") in translations:
                blocks[item["block_id"]] = item
    except json.JSONDecodeError:
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if item.get("block_id") in translations:
                    blocks[item["block_id"]] = item
            except json.JSONDecodeError:
                continue

    return blocks


def backfill_file(
    filepath: Path,
    file_translations: dict[str, str],
    source_info: dict[str, dict],
) -> int:
    """Replace source text with translations in a file. Returns number of replacements."""
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    replaced = 0

    # Sort blocks by source_text length (longest first) to avoid partial matches
    for block_id, translation in sorted(
        file_translations.items(),
        key=lambda x: len(source_info.get(x[0], {}).get("source_text", "")),
        reverse=True,
    ):
        info = source_info.get(block_id, {})
        source_text = info.get("source_text", "")

        if not source_text:
            continue

        # Only replace if source_text appears exactly once
        count = content.count(source_text)
        if count == 1:
            content = content.replace(source_text, translation, 1)
            replaced += 1
        elif count > 1:
            # Source text appears multiple times - potentially ambiguous
            # For safety, skip ambiguous replacements
            print(f"  [SKIP] {block_id}: 源文本出现 {count} 次，跳过以避免歧义替换", file=sys.stderr)
        else:
            print(f"  [SKIP] {block_id}: 源文本未找到", file=sys.stderr)

    if replaced > 0:
        filepath.write_text(content, encoding="utf-8")
        print(f"  [OK] {filepath.name}: 替换 {replaced} 处", file=sys.stderr)

    return replaced


def backfill_project(
    project_dir: Path,
    translations: dict[str, str],
    source_blocks: dict[str, dict],
    parallel: bool = True,
) -> int:
    """Apply all translations to project files. Files are processed in parallel."""
    # Group translations by file
    by_file: dict[str, dict[str, str]] = {}
    for block_id, translation in translations.items():
        info = source_blocks.get(block_id, {})
        filename = info.get("file", "")
        if filename:
            by_file.setdefault(filename, {})[block_id] = translation

    if not by_file:
        print("[WARN] 没有可供回填的翻译块", file=sys.stderr)
        return 0

    total = 0
    file_count = len(by_file)

    if parallel and file_count > 1:
        print(f"  并行写入 {file_count} 个文件...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=min(file_count, 8)) as executor:
            futures = {
                executor.submit(
                    _backfill_one_file, project_dir, rel_path, file_trans, source_blocks
                ): rel_path
                for rel_path, file_trans in by_file.items()
            }
            for future in as_completed(futures):
                rel_path = futures[future]
                try:
                    n = future.result()
                    total += n
                except Exception as e:
                    print(f"  [ERR] {rel_path}: {e}", file=sys.stderr)
    else:
        for rel_path, file_trans in by_file.items():
            filepath = project_dir / rel_path
            if filepath.is_file():
                total += backfill_file(filepath, file_trans, source_blocks)
            else:
                print(f"  [MISS] 文件不存在: {rel_path}", file=sys.stderr)

    return total


def _backfill_one_file(
    project_dir: Path,
    rel_path: str,
    file_trans: dict[str, str],
    source_info: dict[str, dict],
) -> int:
    """Backfill a single file (for parallel execution)."""
    filepath = project_dir / rel_path
    if not filepath.is_file():
        print(f"  [MISS] 文件不存在: {rel_path}", file=sys.stderr)
        return 0
    return backfill_file(filepath, file_trans, source_info)


def main():
    parser = argparse.ArgumentParser(
        description="将翻译结果回填到 LaTeX 文件中",
    )
    parser.add_argument(
        "project_dir",
        help="LaTeX 项目目录（复制出的工作目录）",
    )
    parser.add_argument(
        "translations",
        help="翻译 JSON 文件（block_id → translation）",
    )
    parser.add_argument(
        "--blocks",
        help="提取阶段输出的 blocks JSON 文件（提供源文本定位信息）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查不实际写入",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="禁用并行写入（串行模式）",
    )
    args = parser.parse_args()

    root = Path(args.project_dir).resolve()
    if not root.is_dir():
        print(f"[ERROR] 目录不存在: {args.project_dir}", file=sys.stderr)
        sys.exit(1)

    trans_file = Path(args.translations)
    if not trans_file.is_file():
        print(f"[ERROR] 翻译文件不存在: {args.translations}", file=sys.stderr)
        sys.exit(1)

    translations = load_translations(trans_file)
    if not translations:
        print("[ERROR] 未加载到任何翻译", file=sys.stderr)
        sys.exit(1)

    blocks_file = Path(args.blocks) if args.blocks else None
    source_blocks = load_source_blocks(blocks_file, translations)

    print(f"加载 {len(translations)} 个翻译块，其中 {len(source_blocks)} 个有源文件信息", file=sys.stderr)

    if args.dry_run:
        print("\n[Dry run] 以下翻译将回填:", file=sys.stderr)
        for block_id, trans in translations.items():
            info = source_blocks.get(block_id, {})
            src = info.get("source_text", "?")[:60]
            print(f"  {block_id}: {src} → {trans[:60]}", file=sys.stderr)
        sys.exit(0)

    replaced = backfill_project(root, translations, source_blocks,
                                 parallel=not args.no_parallel)
    print(f"\n回填完成: {replaced} 处替换", file=sys.stderr)


if __name__ == "__main__":
    main()

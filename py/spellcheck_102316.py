from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

from dh import TXT_EXT
from spellchecker import SpellChecker


def find_text_files(root_dir: Path, extensions: set | None = None) -> list[Path]:
    if extensions is None:
        extensions = TXT_EXT
    text_files = []
    for path in root_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            text_files.append(path)
    return text_files


def extract_words(text: str) -> list[tuple[str, int, int]]:
    import re

    words = []
    for match in re.finditer(r"\b[a-zA-Z]+\b", text):
        words.append((match.group(), match.start(), match.end()))
    return words


def check_file(file_path: Path) -> dict:
    try:
        spell = SpellChecker()
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        words = extract_words(content)
        misspellings = []
        for word, start, end in words:
            if len(word) > 1 and word.lower() not in spell:
                if word.lower() != spell.correction(word.lower()):
                    misspellings.append(
                        {
                            "word": word,
                            "position": (start, end),
                            "correction": spell.correction(word.lower()),
                            "candidates": list(spell.candidates(word.lower()))[:5],
                        }
                    )
        return {"file": str(file_path), "misspellings": misspellings, "content": content}
    except Exception as e:
        return {"file": str(file_path), "error": str(e), "misspellings": [], "content": None}


def fix_file(file_path: Path, corrections: dict[str, str]) -> bool:
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        words = extract_words(content)
        corrections_to_apply = []
        for word, start, end in words:
            if word.lower() in corrections:
                corrections_to_apply.append((start, end, corrections[word.lower()]))
        corrections_to_apply.sort(key=lambda x: x[0], reverse=True)
        for start, end, correction in corrections_to_apply:
            content = content[:start] + correction + content[end:]
        file_path.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"Error fixing {file_path}: {e}", file=sys.stderr)
        return False


def process_files_parallel(files: list[Path], max_workers: int | None = None) -> dict:
    results = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(check_file, file_path): file_path for file_path in files}
        for i, future in enumerate(as_completed(future_to_file), 1):
            file_path = future_to_file[future]
            try:
                result = future.result()
                results[str(file_path)] = result
                if i % 10 == 0 or i == len(files):
                    print(f"\rProcessed {i}/{len(files)} files...", end="", flush=True)
            except Exception as e:
                print(f"\nError processing {file_path}: {e}", file=sys.stderr)
                results[str(file_path)] = {"file": str(file_path), "error": str(e), "misspellings": [], "content": None}
    print()
    return results


def display_results(results: dict, show_candidates: bool = False):
    total_misspellings = 0
    files_with_errors = 0
    for file_path, result in sorted(results.items()):
        if result.get("error"):
            print(f"\n❌ Error in {file_path}: {result['error']}")
            continue
        misspellings = result["misspellings"]
        if not misspellings:
            continue
        files_with_errors += 1
        total_misspellings += len(misspellings)
        rel_path = Path(file_path).relative_to(Path.cwd())
        print(f"\n📄 {rel_path} ({len(misspellings)} misspellings)")
        print("-" * 42)
        for ms in misspellings[:10]:
            context = get_context(result["content"], ms["position"])
            print(f"  • Line {context['line']}: '{ms['word']}' → '{ms['correction']}'")
            if show_candidates and ms["candidates"]:
                print(f"    Candidates: {', '.join(ms['candidates'])}")
            if context["text"]:
                print(f"    Context: {context['text']}")
        if len(misspellings) > 10:
            print(f"  ... and {len(misspellings) - 10} more")
    print("\n" + "=" * 42)
    print(f"📊 Summary: {files_with_errors} files with {total_misspellings} total misspellings")
    print("-" * 42)


def get_context(content: str, position: tuple[int, int], window: int = 40) -> dict:
    if not content:
        return {"line": 0, "text": ""}
    start, end = position
    before_start = max(0, start - window)
    after_end = min(len(content), end + window)
    line_num = content[:start].count("\n") + 1
    before = content[before_start:start].strip()
    after = content[end:after_end].strip()
    if before:
        before = "..." + before if before_start > 0 else before
    if after:
        after = after + "..." if after_end < len(content) else after
    return {"line": line_num, "text": f"{before} [{content[start:end]}] {after}".strip()}


def confirm_action(prompt: str) -> bool:
    while True:
        response = input(f"{prompt} (y/n): ").lower().strip()
        if response in ["y", "yes"]:
            return True
        elif response in ["n", "no"]:
            return False
        print("Please answer 'y' or 'n'")


def main():
    parser = argparse.ArgumentParser(
        description="Find and optionally fix misspelled words in text files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s -a
  %(prog)s -a --interactive
  %(prog)s -w 8
  %(prog)s -e .txt .md
        """,
    )
    parser.add_argument("directory", nargs="?", default=".", help="Directory to scan (default: current directory)")
    parser.add_argument("-a", "--autofix", action="store_true", help="Automatically fix misspelled words in-place")
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Ask for confirmation before each fix (only with -a)"
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=None, help="Number of parallel workers (default: CPU count)"
    )
    parser.add_argument("-e", "--extensions", nargs="+", help="File extensions to check (default: common text files)")
    parser.add_argument("-c", "--candidates", action="store_true", help="Show candidate corrections")
    parser.add_argument("--min-length", type=int, default=2, help="Minimum word length to check (default: 2)")
    args = parser.parse_args()
    if args.extensions:
        extensions = {ext if ext.startswith(".") else f".{ext}" for ext in args.extensions}
    else:
        extensions = TXT_EXT
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Error: Directory '{root_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    print(f"🔍 Scanning {root_dir} for text files...")
    files = find_text_files(root_dir, extensions)
    if not files:
        print("No text files found.")
        return
    print(f"📁 Found {len(files)} text files to check")
    print(f"⚡ Using {args.workers or 'default'} worker processes")
    print("\n🔄 Checking spelling...")
    results = process_files_parallel(files, args.workers)
    display_results(results, args.candidates)
    if args.autofix:
        total_misspellings = sum(len(r["misspellings"]) for r in results.values() if not r.get("error"))
        if total_misspellings == 0:
            print("✅ No misspellings to fix!")
            return
        if args.interactive:
            proceed = confirm_action(f"\n🔧 Found {total_misspellings} misspellings. Apply fixes?")
        else:
            print(f"\n🔧 Auto-fixing {total_misspellings} misspellings...")
            proceed = True
        if proceed:
            fixed_count = 0
            for file_path, result in sorted(results.items()):
                if result.get("error") or not result["misspellings"]:
                    continue
                corrections = {}
                for ms in result["misspellings"]:
                    if args.interactive:
                        print(f"\nFile: {file_path}")
                        print(f"  Word: '{ms['word']}'")
                        print(f"  Suggested: '{ms['correction']}'")
                        if ms["candidates"]:
                            print(f"  Candidates: {', '.join(ms['candidates'])}")
                        action = input("  Apply this fix? (y/n/s[kip all]/q[uit]): ").lower().strip()
                        if action in ["q", "quit"]:
                            print("Quitting...")
                            return
                        elif action in ["s", "skip"]:
                            continue
                        elif action not in ["y", "yes"]:
                            continue
                    corrections[ms["word"].lower()] = ms["correction"]
                if corrections and fix_file(Path(file_path), corrections):
                    fixed_count += len(corrections)
                    print(f"✅ Fixed {file_path}")
            print(f"\n✅ Fixed {fixed_count} misspellings across multiple files")
        else:
            print("❌ Fix cancelled")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import re
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

try:
    from spellchecker import SpellChecker
except ImportError:
    print("Error: spellchecker package not installed.")
    print("Install it with: pip install pyspellchecker")
    sys.exit(1)


class Personaldictionary:
    def __init__(self, dict_path: Path | None = None):
        self.dict_path = dict_path or Path.home() / ".spell_checker_dict.json"
        self.words: set[str] = set()
        self.load()

    def load(self) -> None:
        if self.dict_path.exists():
            try:
                with open(self.dict_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.words = {word.lower() for word in data.get("words", [])}
            except (OSError, json.JSONDecodeError) as e:
                print(f"Warning: Could not load personal dictionary: {e}", file=sys.stderr)
                self.words = set()
        else:
            self.words = set()

    def save(self) -> None:
        try:
            with open(self.dict_path, "w", encoding="utf-8") as f:
                json.dump({"words": sorted(self.words)}, f, indent=2, ensure_ascii=False)
            print(f"✓ dictionary saved to {self.dict_path}")
        except OSError as e:
            print(f"Error: Could not save dictionary: {e}", file=sys.stderr)

    def add_word(self, word: str) -> bool:
        word_lower = word.lower()
        if word_lower not in self.words:
            self.words.add(word_lower)
            return True
        return False

    def add_words(self, words: list[str]) -> int:
        count = sum(1 for word in words if self.add_word(word))
        return count

    def remove_word(self, word: str) -> bool:
        word_lower = word.lower()
        if word_lower in self.words:
            self.words.remove(word_lower)
            return True
        return False

    def contains(self, word: str) -> bool:
        return word.lower() in self.words

    def __len__(self) -> int:
        return len(self.words)

    def list_words(self) -> list[str]:
        return sorted(self.words)


class SpellCheckProcessor:
    def __init__(self, autofix: bool = False, personal_dict: Personaldictionary = None):
        self.autofix = autofix
        self.spell_checker = SpellChecker()
        self.personal_dict = personal_dict or Personaldictionary()

    def check_file(self, file_path: Path) -> dict:
        result = {
            "file": str(file_path),
            "errors": [],
            "total_errors": 0,
            "fixed": False,
        }
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as e:
            result["error"] = f"Could not read file: {e}"
            return result
        lines = content.split("\n")
        error_map = {}
        for line_num, line in enumerate(lines, 1):
            words = re.findall(r"\b[a-zA-Z]+\b", line)
            misspelled = self.spell_checker.unknown(words)
            misspelled = [word for word in misspelled if not self.personal_dict.contains(word)]
            for word in misspelled:
                if word not in error_map:
                    error_map[word] = []
                error_map[word].append(line_num)
        for word, line_numbers in error_map.items():
            suggestions = self.spell_checker.correction(word)
            if isinstance(suggestions, str):
                suggestions = [suggestions]
            else:
                suggestions = list(suggestions)[:5]
            result["errors"].append({"word": word, "lines": line_numbers, "suggestions": suggestions})
            result["total_errors"] += len(line_numbers)
        if self.autofix and result["errors"]:
            result["fixed"] = self._fix_file(file_path, content)
        return result

    def _fix_file(self, file_path: Path, content: str) -> bool:
        fixed_content = content
        lines = content.split("\n")
        for error in self._collect_errors(lines):
            word = error["word"]
            suggestion = self.spell_checker.correction(word)
            if isinstance(suggestion, str):
                fixed_content = re.sub(
                    r"\b" + re.escape(word) + r"\b",
                    suggestion,
                    fixed_content,
                    flags=re.IGNORECASE,
                )
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fixed_content)
            return True
        except OSError as e:
            print(f"Error writing to {file_path}: {e}", file=sys.stderr)
            return False

    def _collect_errors(self, lines: list[str]) -> list[dict]:
        errors = {}
        for line in lines:
            words = re.findall(r"\b[a-zA-Z]+\b", line)
            misspelled = self.spell_checker.unknown(words)
            misspelled = [word for word in misspelled if not self.personal_dict.contains(word)]
            for word in misspelled:
                if word not in errors:
                    errors[word] = {"word": word}
        return list(errors.values())


def get_input_files(inputs: list[str]) -> list[Path]:
    files = []
    if not inputs:
        inputs = ["."]
    for input_path in inputs:
        path = Path(input_path)
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.glob("**/*.txt"))
            files.extend(path.glob("**/*.md"))
            files.extend(path.glob("**/*.py"))
        else:
            print(f"Warning: {input_path} not found", file=sys.stderr)
    return files


def process_file_wrapper(args: tuple[Path, bool, Personaldictionary]) -> dict:
    file_path, autofix, personal_dict = args
    processor = SpellCheckProcessor(autofix=autofix, personal_dict=personal_dict)
    return processor.check_file(file_path)


def print_results(results: list[dict]) -> None:
    total_files = len(results)
    total_errors = sum(r.get("total_errors", 0) for r in results)
    files_with_errors = sum(1 for r in results if r.get("total_errors", 0) > 0)
    print("\n" + "=" * 42)
    print(f"Spell Check Report: {total_files} file(s) checked")
    print("-" * 42)
    for result in results:
        if result.get("error"):
            print(f"\n{result['file']}: ERROR - {result['error']}")
            continue
        if result.get("total_errors") == 0:
            print(f"\n✓ {result['file']}: No errors found")
            continue
        print(f"\n✗ {result['file']}: {result['total_errors']} error(s)")
        for error in result["errors"]:
            word = error["word"]
            lines = ", ".join(map(str, error["lines"]))
            suggestions = ", ".join(error["suggestions"][:3])
            print(f"  • '{word}' on line(s) {lines}")
            print(f"    Suggestions: {suggestions}")
        if result.get("fixed"):
            print("  ✓ Fixed!")
    print("\n" + "=" * 42)
    print(f"Summary: {total_errors} total error(s) in {files_with_errors} file(s)")
    print("-" * 42)


def handle_dictionary_operations(args) -> None:
    personal_dict = Personaldictionary(Path(args.dict_file) if args.dict_file else None)
    if args.add_words:
        count = personal_dict.add_words(args.add_words)
        print(f"✓ Added {count} word(s) to dictionary")
        personal_dict.save()
    if args.add_from_file:
        try:
            with open(args.add_from_file, encoding="utf-8") as f:
                words = [line.strip() for line in f if line.strip()]
            count = personal_dict.add_words(words)
            print(f"✓ Added {count} word(s) from {args.add_from_file}")
            personal_dict.save()
        except OSError as e:
            print(f"Error: Could not read file {args.add_from_file}: {e}", file=sys.stderr)
            sys.exit(1)
    if args.remove_words:
        count = sum(1 for word in args.remove_words if personal_dict.remove_word(word))
        print(f"✓ Removed {count} word(s) from dictionary")
        personal_dict.save()
    if args.list_dict:
        words = personal_dict.list_words()
        if words:
            print(f"\nPersonal dictionary ({len(words)} words):")
            print("-" * 42)
            for word in words:
                print(f"  {word}")
            print("-" * 42)
        else:
            print("Personal dictionary is empty.")
    if args.clear_dict:
        if input("Are you sure you want to clear the dictionary? (yes/no): ").lower() == "yes":
            personal_dict.words.clear()
            personal_dict.save()
            print("✓ dictionary cleared")
        else:
            print("Cancelled.")
    if any(
        [
            args.add_words,
            args.add_from_file,
            args.remove_words,
            args.list_dict,
            args.clear_dict,
        ]
    ):
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Check and optionally fix spelling errors in text files with personal dictionary support.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python checkspell.py
  python checkspell.py document.txt
  python checkspell.py -a document.txt
  python checkspell.py -d ~/.my_words.json document.txt
Personal dictionary Management:
  python checkspell.py --add-words myword1 myword2 myword3
  python checkspell.py --add-from-file custom_words.txt
  python checkspell.py --remove-words word1 word2
  python checkspell.py --list-dict
  python checkspell.py --clear-dict
  python checkspell.py -d /path/to/dict.json -a document.txt
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="File(s) or folder(s) to check (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--autofix",
        action="store_true",
        help="Automatically fix misspelled words",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of worker processes (default: {cpu_count()})",
    )
    parser.add_argument(
        "-d",
        "--dict-file",
        type=str,
        help="Path to personal dictionary file (default: ~/.personaldict.json)",
    )
    parser.add_argument(
        "--add-words",
        nargs="+",
        metavar="WORD",
        help="Add one or more words to personal dictionary",
    )
    parser.add_argument(
        "--add-from-file",
        type=str,
        metavar="FILE",
        help="Add words from file (one word per line) to dictionary",
    )
    parser.add_argument(
        "--remove-words",
        nargs="+",
        metavar="WORD",
        help="Remove one or more words from personal dictionary",
    )
    parser.add_argument("--list-dict", action="store_true", help="list all words in personal dictionary")
    parser.add_argument(
        "--clear-dict",
        action="store_true",
        help="Clear entire personal dictionary (with confirmation)",
    )
    args = parser.parse_args()
    personal_dict = Personaldictionary(Path(args.dict_file) if args.dict_file else None)
    handle_dictionary_operations(args)
    files = get_input_files(args.inputs)
    if not files:
        print("No files found to check.", file=sys.stderr)
        sys.exit(0)
    print(f"Processing {len(files)} file(s)")
    print(f"Using personal dictionary: {personal_dict.dict_path} ({len(personal_dict)} word(s))\n")
    if len(files) == 1:
        process_file_wrapper(filrs[0])
        sys.exit(0)
    with Pool(args.jobs) as pool:
        file_args = [(f, args.autofix, personal_dict) for f in files]
        results = pool.map(process_file_wrapper, file_args)
    print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())

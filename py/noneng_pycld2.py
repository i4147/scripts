from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path

import pycld2 as cld2

TEXT_EXTENSIONS = {
    ".txt",
    ".csv",
    ".log",
    ".md",
    ".rst",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".bat",
    ".ps1",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".sql",
    ".r",
    ".rb",
    ".php",
    ".pl",
    ".go",
    ".rs",
    ".ts",
    ".jsx",
    ".tsx",
    ".vue",
    ".tex",
    ".bib",
    ".toml",
    ".env",
    ".gitignore",
    ".dockerfile",
}
CLD2_LANG_MAP = {
    "en": "ENGLISH",
    "es": "SPANISH",
    "fr": "FRENCH",
    "de": "GERMAN",
    "it": "ITALIAN",
    "pt": "PORTUGUESE",
    "ru": "RUSSIAN",
    "zh": "CHINESE",
    "ja": "JAPANESE",
    "ko": "KOREAN",
    "ar": "ARABIC",
    "hi": "HINDI",
    "nl": "DUTCH",
    "pl": "POLISH",
    "tr": "TURKISH",
    "vi": "VIETNAMESE",
    "th": "THAI",
    "sv": "SWEDISH",
    "da": "DANISH",
    "fi": "FINNISH",
    "no": "NORWEGIAN",
    "cs": "CZECH",
    "hu": "HUNGARIAN",
    "el": "GREEK",
    "he": "HEBREW",
    "id": "INDONESIAN",
    "ms": "MALAY",
    "ro": "ROMANIAN",
    "sk": "SLOVAK",
    "uk": "UKRAINIAN",
    "bg": "BULGARIAN",
    "hr": "CROATIAN",
    "sr": "SERBIAN",
    "ca": "CATALAN",
    "sl": "SLOVENIAN",
    "lt": "LITHUANIAN",
    "lv": "LATVIAN",
    "et": "ESTONIAN",
    "fa": "PERSIAN",
    "tl": "TAGALOG",
    "sw": "SWAHILI",
    "bn": "BENGALI",
    "ta": "TAMIL",
    "te": "TELUGU",
    "mr": "MARATHI",
    "ur": "URDU",
    "gu": "GUJARATI",
    "kn": "KANNADA",
    "ml": "MALAYALAM",
    "pa": "PUNJABI",
    "unknown": "UNKNOWN",
}


def is_likely_text_file(file_path):
    return file_path.suffix.lower() in TEXT_EXTENSIONS


def detect_language(text):
    if not text.strip():
        return None, None, 0, True
    try:
        is_reliable, _text_bytes_found, details = cld2.detect(text)
        if not details:
            return "un", "UNKNOWN", 0, False
        lang_name, lang_code, percent, _score = details[0]
        lang_code = lang_code.lower() if lang_code else "un"
        return lang_code, lang_name, percent, is_reliable
    except Exception:
        return "un", "UNKNOWN", 0, False


def process_file(file_path):
    non_english_lines = []
    try:
        if file_path.stat().st_size > 10 * 1024 * 1024:
            return file_path, None, "File too large (>10MB)"
    except (OSError, PermissionError) as e:
        return file_path, None, f"Cannot access file: {e}"
    try:
        content = None
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.readlines()
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            return file_path, None, "Cannot decode file"
        for line_num, line in enumerate(content, 1):
            if not line.strip():
                continue
            lang_code, lang_name, confidence, _is_reliable = detect_language(line.strip())
            if (lang_code and lang_code != "en" and confidence >= 50) or (lang_code == "un" and confidence < 50):
                non_english_lines.append((line_num, line.strip(), lang_code, lang_name, confidence))
        return file_path, non_english_lines, None
    except Exception as e:
        return file_path, None, f"Error processing file: {e}"


def find_text_files(root_dir=".", extensions=TEXT_EXTENSIONS):
    root_path = Path(root_dir)
    text_files = []
    for ext in extensions:
        text_files.extend(root_path.rglob(f"*{ext}"))
    text_files = list(set(text_files))
    text_files = [f for f in text_files if is_likely_text_file(f)]
    text_files.sort()
    return text_files


def main():
    parser = argparse.ArgumentParser(description="Find non-English lines in text files using pycld2")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="noneng.txt",
        help="Output report file (default: noneng.txt)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel workers (default: {cpu_count()})",
    )
    parser.add_argument("--extensions", nargs="+", help="Additional file extensions to scan")
    parser.add_argument(
        "--min-confidence",
        type=int,
        default=50,
        help="Minimum confidence percentage for non-English detection (default: 50)",
    )
    args = parser.parse_args()
    extensions = TEXT_EXTENSIONS
    if args.extensions:
        extensions.update(args.extensions)
    print(f"Scanning directory: {args.directory}")
    text_files = find_text_files(args.directory, extensions)
    print(f"Found {len(text_files)} text files to process")
    non_english_results = []
    errors = []
    files_with_findings = 0
    total_non_eng_lines = 0
    print(f"Processing files using {args.workers} workers...")
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_file = {executor.submit(process_file, file): file for file in text_files}
        completed = 0
        for future in as_completed(future_to_file):
            completed += 1
            if completed % 100 == 0 or completed == len(text_files):
                print(f"Progress: {completed}/{len(text_files)} files processed")
            file_path, results, error = future.result()
            if error:
                errors.append((file_path, error))
            elif results:
                files_with_findings += 1
                total_non_eng_lines += len(results)
                non_english_results.append((file_path, results))
    output_path = Path(args.output)
    print(f"\nGenerating report: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("=" * 40 + "\n")
        f.write("Non-English Lines Detection Report\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Directory scanned: {Path(args.directory).resolve()}\n")
        f.write(f"Files scanned: {len(text_files)}\n")
        f.write(f"Files with non-English content: {files_with_findings}\n")
        f.write(f"Total non-English lines found: {total_non_eng_lines}\n")
        f.write(f"Minimum confidence threshold: {args.min_confidence}%\n")
        f.write("=" * 40 + "\n\n")
        if non_english_results:
            lang_counts = {}
            for _, lines in non_english_results:
                for _, _, lang_code, lang_name, _ in lines:
                    key = f"{lang_name} ({lang_code})"
                    lang_counts[key] = lang_counts.get(key, 0) + 1
            if lang_counts:
                f.write("Language Distribution:\n")
                f.write("-" * 40 + "\n")
                f.writelines(
                    f"  {lang}: {count} lines\n"
                    for lang, count in sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
                )
                f.write("\n")
            for file_path, lines in non_english_results:
                f.write(f"\n{'─' * 40}\n")
                f.write(f"File: {file_path}\n")
                f.write(f"Non-English lines: {len(lines)}\n")
                f.write(f"{'─' * 40}\n\n")
                for line_num, line_text, lang_code, lang_name, confidence in lines:
                    f.write(f"  Line {line_num}: [{lang_name}] ({lang_code}) - Confidence: {confidence}%\n")
                    f.write(f"  Content: {line_text}\n\n")
        else:
            f.write("No non-English lines found.\n")
        if errors:
            f.write(f"\n{'=' * 40}\n")
            f.write(f"Errors encountered: {len(errors)}\n")
            f.write(f"{'=' * 40}\n\n")
            for file_path, error in errors:
                f.write(f"  {file_path}: {error}\n")
    print(f"\n{'=' * 40}")
    print("Scan complete!")
    print(f"Files scanned: {len(text_files)}")
    print(f"Files with non-English content: {files_with_findings}")
    print(f"Total non-English lines found: {total_non_eng_lines}")
    print(f"Errors: {len(errors)}")
    print(f"Report saved to: {output_path.resolve()}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    raise SystemExit(main())

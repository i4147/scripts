from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

import cld3

TEXT_EXTENSIONS = {
    ".txt",
    ".py",
    ".js",
    ".html",
    ".css",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".md",
    ".rst",
    ".csv",
    ".tsv",
    ".log",
    ".sh",
    ".bash",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".lua",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".env",
}
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "build",
    "dist",
}
BATCH_SIZE = 100


def is_english(text: str) -> tuple[bool, float]:
    if not text or len(text.strip()) < 3:
        return (True, 1.0)
    try:
        result = cld3.get_language(text)
        if result is None or not result.is_reliable:
            return (True, 0.0)
        is_en = result.language == "en"
        return (is_en, result.probability)
    except Exception:
        return (True, 0.0)


def analyze_file(filepath: Path, detailed: bool = False) -> dict | None:
    try:
        content = None
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                content = filepath.read_text(encoding=encoding, errors="ignore")
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            return None
        lines = content.splitlines()
        if not lines:
            return None
        file_result = cld3.get_language(content[:10000])
        if file_result and file_result.is_reliable and (file_result.language != "en"):
            result = {
                "file": str(filepath),
                "language": file_result.language,
                "confidence": file_result.probability,
                "size_bytes": filepath.stat().st_size,
                "line_count": len(lines),
                "non_english_lines": [],
            }
            if detailed:
                non_eng_lines = []
                for idx, line in enumerate(lines, 1):
                    if not line.strip():
                        continue
                    is_en, prob = is_english(line)
                    if not is_en:
                        non_eng_lines.append(
                            {
                                "line_num": idx,
                                "text": line[:200],
                                "confidence": prob,
                                "full_text": line if len(line) <= 200 else f"{line[:200]}...",
                            }
                        )
                if non_eng_lines:
                    result["non_english_lines"] = non_eng_lines
                    result["non_eng_line_count"] = len(non_eng_lines)
                else:
                    pass
            return result
        if detailed:
            non_eng_lines = []
            for idx, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                is_en, prob = is_english(line)
                if not is_en:
                    non_eng_lines.append(
                        {
                            "line_num": idx,
                            "text": line[:200],
                            "confidence": prob,
                            "full_text": line if len(line) <= 200 else f"{line[:200]}...",
                        }
                    )
            if non_eng_lines:
                return {
                    "file": str(filepath),
                    "language": "en",
                    "confidence": 1.0,
                    "size_bytes": filepath.stat().st_size,
                    "line_count": len(lines),
                    "non_english_lines": non_eng_lines,
                    "non_eng_line_count": len(non_eng_lines),
                    "mixed": True,
                }
        return None
    except Exception as e:
        return {"file": str(filepath), "error": str(e), "non_english_lines": []}


def scan_files(root_dir: Path, detailed: bool = False, max_workers: int | None = None) -> list[dict]:
    if max_workers is None:
        max_workers = min(cpu_count(), 8)
    files = []
    for ext in TEXT_EXTENSIONS:
        files.extend(root_dir.rglob(f"*{ext}"))
    files = [f for f in files if not any(part in SKIP_DIRS for part in f.parts)]
    print(f"Found {len(files)} text files. Analyzing with {max_workers} workers...")
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(analyze_file, f, detailed): f for f in files}
        completed = 0
        for future in as_completed(future_to_file):
            filepath = future_to_file[future]
            completed += 1
            if completed % 50 == 0:
                print(f"Progress: {completed}/{len(files)} files...")
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                print(f"Error analyzing {filepath}: {e}")
    return results


def main():
    parser = argparse.ArgumentParser(description="Find non-English files recursively")
    parser.add_argument(
        "-l",
        "--detailed",
        action="store_true",
        help="Report non-English lines within each file",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="noneng.json",
        help="Output JSON file (default: noneng.json)",
    )
    parser.add_argument(
        "-d",
        "--dir",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count, max 8)",
    )
    args = parser.parse_args()
    root_dir = Path(args.dir).resolve()
    if not root_dir.exists():
        print(f"Error: Directory {root_dir} does not exist")
        sys.exit(1)
    print(f"Scanning: {root_dir}")
    print(f"Detailed mode: {args.detailed}")
    results = scan_files(root_dir, args.detailed, args.workers)
    results.sort(key=lambda x: x.get("file", ""))
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "scan_root": str(root_dir),
                "detailed": args.detailed,
                "total_non_english_files": len(results),
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n{'=' * 40}")
    print(f"Found {len(results)} non-English files")
    print(f"Results saved to: {output_path}")
    if results:
        print("\nSample (first 5 files):")
        for r in results[:5]:
            lang = r.get("language", "unknown")
            lines = r.get("non_eng_line_count", 0)
            print(f"  {r['file']} → {lang} (confidence: {r.get('confidence', 0):.2%})")
            if args.detailed and lines:
                print(f"    {lines} non-English lines")


if __name__ == "__main__":
    raise SystemExit(main())

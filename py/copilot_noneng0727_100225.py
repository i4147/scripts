from pathlib import Path
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Iterator, List, Dict, Any, Optional

try:
    import gcld3
except Exception as e:
    print("Missing dependency: gcld3. Install with: pip install gcld3", file=sys.stderr)
    raise

try:
    import pycld2 as cld2
except Exception as e:
    print("Missing dependency: pycld2. Install with: pip install pycld2", file=sys.stderr)
    raise

try:
    from langdetect import detect_langs, DetectorFactory

    DetectorFactory.seed = 0
except Exception as e:
    print("Missing dependency: langdetect. Install with: pip install langdetect", file=sys.stderr)
    raise

_print_lock = threading.Lock()
_results_lock = threading.Lock()
_results: list[dict[str, Any]] = []

_gcld3_detector = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=1000)


def iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for p in paths:
        p = p.expanduser()
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    yield f
        else:
            continue


def read_text_lines(path: Path, max_line_length: int = 2000) -> Iterator[str]:
    try:
        with path.open("r", encoding="utf-8", errors="strict") as fh:
            for ln in fh:
                yield ln.rstrip("\n")
            return
    except UnicodeDecodeError:
        try:
            with path.open("r", encoding="latin-1", errors="replace") as fh:
                for ln in fh:
                    yield ln.rstrip("\n")
                return
        except Exception:
            return
    except Exception:
        return


def detect_gcld3(text: str) -> Optional[str]:
    try:
        res = _gcld3_detector.FindLanguage(text[:1000])
        lang = getattr(res, "language", None)
        if lang:
            return lang
    except Exception:
        pass
    return None


def detect_pycld2(text: str) -> Optional[str]:
    try:
        is_reliable, _, details = cld2.detect(text, returnVectors=True)
        if details and len(details) > 0:
            code = details[0][1]
            return code
    except Exception:
        pass
    return None


def detect_langdetect(text: str) -> Optional[str]:
    try:
        langs = detect_langs(text)
        if langs:
            top = langs[0]
            return top.lang
    except Exception:
        pass
    return None


def combine_votes(g3: Optional[str], p2: Optional[str], ld: Optional[str]) -> dict[str, Any]:
    votes = {"gcld3": g3 or "unknown", "pycld2": p2 or "unknown", "langdetect": ld or "unknown"}

    def is_en(code: str) -> Optional[bool]:
        if not code or code == "unknown":
            return None
        return code.lower().startswith("en")

    en_flags = [is_en(v) for v in votes.values()]
    non_en_votes = sum(1 for v in votes.values() if v != "unknown" and not v.lower().startswith("en"))
    known_votes = sum(1 for v in votes.values() if v != "unknown")
    if non_en_votes >= 2:
        decision = True
    elif non_en_votes == 1 and known_votes == 1:
        if (votes["gcld3"] != "unknown" and not votes["gcld3"].lower().startswith("en")) or (
            votes["pycld2"] != "unknown" and not votes["pycld2"].lower().startswith("en")
        ):
            decision = True
        else:
            decision = False
    else:
        decision = False
    return {"votes": votes, "non_english": decision}


def process_file(path: Path, max_line_length: int = 2000) -> list[dict[str, Any]]:
    local_results: list[dict[str, Any]] = []
    text_extensions = {
        ".txt",
        ".md",
        ".py",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".json",
        ".csv",
        ".tsv",
        ".log",
        ".cfg",
        ".ini",
        ".rst",
        ".tex",
        ".html",
        ".htm",
        ".xml",
        ".yml",
        ".yaml",
    }
    if path.suffix and path.suffix.lower() not in text_extensions:
        pass

    for lineno, raw_line in enumerate(read_text_lines(path), start=1):
        if not raw_line or raw_line.strip() == "":
            continue
        line = raw_line if len(raw_line) <= max_line_length else raw_line[:max_line_length] + "…"
        g3 = detect_gcld3(line)
        p2 = detect_pycld2(line)
        ld = detect_langdetect(line)
        combined = combine_votes(g3, p2, ld)
        if combined["non_english"]:
            record = {
                "file": str(path),
                "line_no": lineno,
                "text": line,
                "detectors": combined["votes"],
                "non_english": True,
            }
            local_results.append(record)
            with _print_lock:
                print(f"{path}:{lineno}: {line}")
                print(f"  detectors: {combined['votes']}")
                print(f"  combined_non_english: {combined['non_english']}")
    if local_results:
        with _results_lock:
            _results.extend(local_results)
    return local_results


def gather_input_paths(args_paths: list[str]) -> list[Path]:
    if not args_paths:
        return [Path(".")]
    return [Path(p) for p in args_paths]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Detect non-English lines in text files recursively.")
    parser.add_argument("paths", nargs="*", help="Files or directories to scan (default: current directory).")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of parallel worker threads.")
    parser.add_argument("--out", "-o", default="noneng.json", help="Output JSON file (default: noneng.json).")
    parser.add_argument("--max-line-length", type=int, default=2000, help="Max chars of a line to consider/display.")
    args = parser.parse_args(argv)

    input_paths = gather_input_paths(args.paths)
    files_gen = iter_files(input_paths)

    files_to_process = []
    for f in files_gen:
        files_to_process.append(f)

    if not files_to_process:
        print("No files found to process.", file=sys.stderr)
        return 1

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_file, f, args.max_line_length): f for f in files_to_process}
        for fut in as_completed(futures):
            fpath = futures[fut]
            try:
                fut.result()
            except Exception as e:
                with _print_lock:
                    print(f"Error processing {fpath}: {e}", file=sys.stderr)

    try:
        out_path = Path(args.out)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(_results, fh, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(_results)} non-English line(s) to {out_path}")
    except Exception as e:
        print(f"Failed to write output file: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

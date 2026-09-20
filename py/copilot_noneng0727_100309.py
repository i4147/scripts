from pathlib import Path
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Iterator, Optional, Dict, Any, List, Tuple

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


def read_text_lines(path: Path, encoding_try: tuple[str, ...] = ("utf-8", "latin-1")) -> Iterator[str]:
    for enc in encoding_try:
        try:
            with path.open("r", encoding=enc, errors="strict") as fh:
                for ln in fh:
                    yield ln.rstrip("\n")
            return
        except UnicodeDecodeError:
            continue
        except Exception:
            return


def detect_gcld3(text: str) -> Optional[str]:
    try:
        res = _gcld3_detector.FindLanguage(text[:1000])
        return getattr(res, "language", None)
    except Exception:
        return None


def detect_pycld2(text: str) -> Optional[str]:
    try:
        is_reliable, _, details = cld2.detect(text, returnVectors=True)
        if details and len(details) > 0:
            return details[0][1]
    except Exception:
        return None


def detect_langdetect(text: str) -> Optional[str]:
    try:
        langs = detect_langs(text)
        if langs:
            return langs[0].lang
    except Exception:
        return None


def normalize_code(code: Optional[str]) -> str:
    if not code:
        return "unknown"
    return code.lower()


def combine_votes(g3: Optional[str], p2: Optional[str], ld: Optional[str]) -> dict[str, Any]:
    votes = {"gcld3": normalize_code(g3), "pycld2": normalize_code(p2), "langdetect": normalize_code(ld)}

    def is_unknown(v: str) -> bool:
        return v == "unknown"

    def is_english(v: str) -> bool:
        return v.startswith("en")

    non_en_votes = sum(1 for v in votes.values() if (not is_unknown(v)) and (not is_english(v)))
    known_votes = sum(1 for v in votes.values() if not is_unknown(v))

    if non_en_votes >= 2:
        decision = True
    elif non_en_votes == 1 and known_votes == 1:
        if (votes["gcld3"] != "unknown" and not is_english(votes["gcld3"])) or (
            votes["pycld2"] != "unknown" and not is_english(votes["pycld2"])
        ):
            decision = True
        else:
            decision = False
    else:
        decision = False

    return {"votes": votes, "non_english": decision}


def detect_line_task(file_path: Path, lineno: int, line: str, max_len: int) -> Optional[dict[str, Any]]:
    if not line or line.strip() == "":
        return None
    text = line if len(line) <= max_len else line[:max_len] + "…"
    g3 = detect_gcld3(text)
    p2 = detect_pycld2(text)
    ld = detect_langdetect(text)
    combined = combine_votes(g3, p2, ld)
    if combined["non_english"]:
        rec = {
            "file": str(file_path),
            "line_no": lineno,
            "text": text,
            "detectors": combined["votes"],
            "non_english": True,
        }
        return rec
    return None


def process_inputs(paths: list[str], workers: int, max_line_length: int) -> int:
    input_paths = [Path(p) for p in paths] if paths else [Path(".")]
    files_iter = iter_files(input_paths)

    files = []
    for f in files_iter:
        files.append(f)

    if not files:
        print("No files found to process.", file=sys.stderr)
        return 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for f in files:
            for lineno, raw_line in enumerate(read_text_lines(f), start=1):
                if not raw_line or raw_line.strip() == "":
                    continue
                fut = ex.submit(detect_line_task, f, lineno, raw_line, max_line_length)
                futures.append(fut)

        for fut in as_completed(futures):
            try:
                rec = fut.result()
                if rec:
                    with _print_lock:
                        print(f"{rec['file']}:{rec['line_no']}: {rec['text']}")
                        print(f"  detectors: {rec['detectors']}")
                    with _results_lock:
                        _results.append(rec)
            except Exception as e:
                with _print_lock:
                    print(f"Error in line detection task: {e}", file=sys.stderr)

    return 0


def save_results(out_path: str) -> None:
    try:
        p = Path(out_path)
        with p.open("w", encoding="utf-8") as fh:
            json.dump(_results, fh, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(_results)} non-English line(s) to {p}")
    except Exception as e:
        print(f"Failed to write output file: {e}", file=sys.stderr)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect non-English lines in text files recursively with per-line parallelism."
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to scan (default: current directory).")
    parser.add_argument("--workers", "-w", type=int, default=8, help="Number of parallel worker threads for lines.")
    parser.add_argument("--out", "-o", default="noneng.json", help="Output JSON file.")
    parser.add_argument("--max-line-length", type=int, default=2000, help="Max chars of a line to consider/display.")
    args = parser.parse_args(argv)

    rc = process_inputs(args.paths, args.workers, args.max_line_length)
    if rc != 0:
        return rc
    save_results(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

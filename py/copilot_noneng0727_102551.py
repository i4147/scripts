from pathlib import Path
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Iterator, Optional, Dict, Any, List, Tuple

3
import pycld2 as cld2
from langdetect import detect_langs, DetectorFactory
from fastwalk import walk_files
from binaryornot import is_binary

DetectorFactory.seed = 0

_print_lock = threading.Lock()
_results_lock = threading.Lock()
_results: list[dict[str, Any]] = []

_gcld3_detector = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=1000)


def iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for p in paths:
        p = p.expanduser()
        if p.is_file() and not is_binary(p):
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not f.is_symlink() and not is_binary(f):
                    yield f


def read_text_lines(path: Path) -> Iterator[str]:
    for enc in ("utf-8", "latin-1"):
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
        if details:
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


def normalize(code: Optional[str]) -> str:
    return "unknown" if not code else code.lower()


def combine_votes(g3: Optional[str], p2: Optional[str], ld: Optional[str]) -> dict[str, Any]:
    votes = {
        "gcld3": normalize(g3),
        "pycld2": normalize(p2),
        "langdetect": normalize(ld),
    }

    def is_en(v: str) -> bool:
        return v.startswith("en")

    non_en_votes = sum(1 for v in votes.values() if v != "unknown" and not is_en(v))
    known_votes = sum(1 for v in votes.values() if v != "unknown")

    if non_en_votes >= 2:
        decision = True
    elif non_en_votes == 1 and known_votes == 1:
        if (votes["gcld3"] != "unknown" and not is_en(votes["gcld3"])) or (
            votes["pycld2"] != "unknown" and not is_en(votes["pycld2"])
        ):
            decision = True
        else:
            decision = False
    else:
        decision = False

    return {"votes": votes, "non_english": decision}


def detect_line(file_path: Path, lineno: int, line: str, max_len: int) -> Optional[dict[str, Any]]:
    if not line.strip():
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


def process_file(file_path: Path, max_len: int) -> list[dict[str, Any]]:
    print(f"processing {file_path}")
    local = []
    for lineno, raw in enumerate(read_text_lines(file_path), start=1):
        rec = detect_line(file_path, lineno, raw, max_len)
        if rec:
            with _print_lock:
                print(f"{rec['file']}:{rec['line_no']}: {rec['text']}")
                print(f"  detectors: {rec['detectors']}")
            local.append(rec)
    return local


def run_per_file(files: list[Path], workers: int, max_len: int):
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(process_file, f, max_len): f for f in files}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    with _results_lock:
                        _results.extend(res)
            except Exception as e:
                print(f"Error processing {futures[fut]}: {e}", file=sys.stderr)


def run_per_line(files: list[Path], workers: int, max_len: int):
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = []
        for f in files:
            for lineno, raw in enumerate(read_text_lines(f), start=1):
                if raw.strip():
                    futures.append(ex.submit(detect_line, f, lineno, raw, max_len))

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
                print(f"Error in line task: {e}", file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Detect non-English lines in text files.")
    parser.add_argument("paths", nargs="*", help="Files or directories (default: .)")
    parser.add_argument("--workers", "-w", type=int, default=8)
    parser.add_argument("--out", "-o", default="noneng.json")
    parser.add_argument("--max-line-length", type=int, default=2000)
    parser.add_argument(
        "--parallel-mode",
        choices=["file", "line"],
        default="line",
        help="Parallelism mode: file or line (default: line)",
    )
    args = parser.parse_args(argv)

    input_paths = [Path(p) for p in args.paths] if args.paths else [Path(".")]
    files = list(iter_files(input_paths))

    if not files:
        print("No files found.", file=sys.stderr)
        return 1

    if args.parallel_mode == "file":
        run_per_file(files, args.workers, args.max_line_length)
    else:
        run_per_line(files, args.workers, args.max_line_length)

    with Path(args.out).open("w", encoding="utf-8") as fh:
        json.dump(_results, fh, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(_results)} non-English lines to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

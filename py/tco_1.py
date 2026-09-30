#!/data/data/com.termux/files/home/.local/bin/python
"""
Text file translator using the `translate` library.

Modes:
  default : translate the input file in CHUNKS (~450 chars, split at line
            boundaries), save to <input>.<target>
  -l      : line-by-line interactive mode — prints each translation
            immediately and saves {"<src>": ..., "<tgt>": ...} pairs to JSON.
            Lines longer than the query limit are split and re-joined.

Concurrency:
  - Off by default (1 worker = sequential).
  - Enable with -w N (e.g. -w 8) to run N concurrent translation threads.
  - A global rate limiter enforces a minimum delay between *requests*
    across all workers, so we don't hammer the backend.
  - Retries with exponential backoff on failure.

Common features:
  - Respects the translator's ~500 char query limit (MAX_CHARS)
  - Saves progress every 50 chunks/lines to a .progress sidecar
  - Resumes from previous progress if the sidecar exists
  - Uses pathlib for all file operations
  - Python 3.12 compatible
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from translate import Translator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SAVE_EVERY = 50  # persist progress every N chunks/lines
DEFAULT_WORKERS = 1  # 1 = sequential (concurrency OFF by default)
REQUEST_INTERVAL = 0.5  # min seconds between *any two* requests (global)
# Only enforced when workers > 1 (concurrent mode).
MAX_RETRIES = 5  # retries per request on failure
BACKOFF_BASE = 1.5  # exponential backoff multiplier (seconds)

# Defaults — Chinese → English
DEFAULT_SOURCE = "zh"
DEFAULT_TARGET = "en"

# Hard limit imposed by the translation backend (~500 chars per query).
MAX_CHARS = 450
CHUNK_SIZE = MAX_CHARS  # default target chars per chunk


# ---------------------------------------------------------------------------
# Global rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    Thread-safe minimum-interval limiter.

    Every call to wait() blocks until at least `interval` seconds have
    elapsed since the last release, so request bursts are smoothed out
    even with many concurrent workers.

    With a single worker, the interval defaults to 0 and this becomes a
    no-op (sequential mode handles pacing with a plain sleep).
    """

    def __init__(self, interval: float) -> None:
        self._interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if sleep_for > 0:
            time.sleep(sleep_for)


# A single global limiter shared by all workers.
_limiter = RateLimiter(0.0)

# Serializes stderr prints so concurrent workers don't interleave messages.
_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def progress_path(target: Path) -> Path:
    """Return the sidecar file that stores the number of completed units."""
    return target.with_suffix(target.suffix + ".progress")


def make_translator(source: str, target: str) -> Translator:
    """
    Build a Translator.  Some versions of the `translate` package accept
    `from_lang` in the constructor, others don't.
    """
    try:
        return Translator(from_lang=source, to_lang=target)
    except TypeError:
        return Translator(to_lang=target)


def translate_text(
    translator: Translator,
    text: str,
    *,
    apply_limiter: bool = True,
) -> str:
    """
    Translate a chunk of text with retries and exponential backoff.

    A global rate limiter is consulted before every request attempt when
    running concurrently.  Empty / whitespace-only input passes through.
    """
    if not text.strip():
        return text

    delay = BACKOFF_BASE
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        if apply_limiter:
            _limiter.wait()  # smooth requests across all workers
        try:
            return translator.translate(text)
        except Exception as err:  # noqa: BLE001
            last_err = err
            with _print_lock:
                print(
                    f"  ! attempt {attempt}/{MAX_RETRIES} failed: {err}",
                    file=sys.stderr,
                )
            time.sleep(delay)
            delay *= BACKOFF_BASE

    raise RuntimeError(f"Translation failed after {MAX_RETRIES} retries: {last_err}")


def split_long_line(line: str, max_chars: int = MAX_CHARS) -> list[str]:
    """
    Split a single line into pieces each <= `max_chars`.

    Prefers natural boundaries: sentence punctuation, then clause
    punctuation, then whitespace, then a hard character cut.
    """
    if len(line) <= max_chars:
        return [line]

    pieces: list[str] = []
    remaining = line

    soft_seps = ["。", "！", "？", "；", ".", "!", "?", ";", "\n"]
    hard_seps = ["，", "、", ",", ":", "：", " "]

    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = -1

        for sep in soft_seps:
            pos = window.rfind(sep)
            if pos > 0:
                cut = pos + len(sep)
                break

        if cut <= 0:
            for sep in hard_seps:
                pos = window.rfind(sep)
                if pos > 0:
                    cut = pos + len(sep)
                    break

        if cut <= 0:
            cut = max_chars

        pieces.append(remaining[:cut])
        remaining = remaining[cut:]

    if remaining:
        pieces.append(remaining)
    return pieces


def chunk_lines(lines: list[str], max_chars: int = CHUNK_SIZE) -> list[list[str]]:
    """
    Group lines into chunks whose combined length is at most `max_chars`.
    Splitting happens at line boundaries only.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line)
        if current and current_len + line_len > max_chars:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate a text file between languages.")
    parser.add_argument("input", help="Path to the input file (UTF-8).")
    parser.add_argument(
        "output",
        nargs="?",
        help="Optional output path. Defaults depend on mode.",
    )
    parser.add_argument(
        "-s",
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Source language code (default: {DEFAULT_SOURCE}).",
    )
    parser.add_argument(
        "-t",
        "--target",
        default=DEFAULT_TARGET,
        help=f"Target language code (default: {DEFAULT_TARGET}).",
    )
    parser.add_argument(
        "-l",
        "--line",
        action="store_true",
        help="Line-by-line mode: print each translation immediately and save source/target pairs to a JSON file.",
    )
    parser.add_argument(
        "-c",
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Target characters per chunk (default: {CHUNK_SIZE}, hard max: {MAX_CHARS}).",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent translation threads. "
        f"1 = sequential (default: {DEFAULT_WORKERS}). "
        f"Use 8 for the concurrent mode.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Minimum seconds between requests, globally. "
        "Only used when --workers > 1. "
        f"(default when concurrent: {REQUEST_INTERVAL})",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Sequential translation helpers
# ---------------------------------------------------------------------------


def translate_sequential(
    translator: Translator,
    jobs: dict[int, list[str]],
    *,
    progress_label: str,
) -> tuple[dict[tuple[int, int], str], list[str]]:
    """
    Translate all pieces in `jobs` sequentially (no threads).

    `jobs` maps a unit index -> list of pieces to translate for that unit.
    Returns (results, errors) where results is keyed by (unit_idx, piece_idx).
    """
    results: dict[tuple[int, int], str] = {}
    errors: list[str] = []

    total_pieces = sum(len(p) for p in jobs.values())
    completed = 0

    for unit_idx in sorted(jobs):
        for piece_idx, piece in enumerate(jobs[unit_idx]):
            try:
                results[(unit_idx, piece_idx)] = translate_text(translator, piece)
            except Exception as err:  # noqa: BLE001
                errors.append(f"{progress_label} {unit_idx + 1}, piece {piece_idx + 1}: {err}")
            completed += 1

            if completed % SAVE_EVERY == 0 or completed == total_pieces:
                print(f"  … {completed}/{total_pieces} pieces translated")

    return results, errors


def translate_concurrent(
    translator: Translator,
    jobs: dict[int, list[str]],
    *,
    workers: int,
    progress_label: str,
) -> tuple[dict[tuple[int, int], str], list[str]]:
    """
    Translate all pieces in `jobs` concurrently using a thread pool.

    Results come back out of order but are keyed by (unit_idx, piece_idx)
    so the caller can rebuild the original order.
    """
    results: dict[tuple[int, int], str] = {}
    errors: list[str] = []

    total_pieces = sum(len(p) for p in jobs.values())
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for unit_idx, pieces in jobs.items():
            for piece_idx, piece in enumerate(pieces):
                fut = pool.submit(translate_text, translator, piece)
                futures[fut] = (unit_idx, piece_idx)

        for fut in as_completed(futures):
            unit_idx, piece_idx = futures[fut]
            try:
                results[(unit_idx, piece_idx)] = fut.result()
            except Exception as err:  # noqa: BLE001
                errors.append(f"{progress_label} {unit_idx + 1}, piece {piece_idx + 1}: {err}")
            completed += 1

            if completed % SAVE_EVERY == 0 or completed == total_pieces:
                print(f"  … {completed}/{total_pieces} pieces translated")

    return results, errors


def run_jobs(
    translator: Translator,
    jobs: dict[int, list[str]],
    *,
    workers: int,
    progress_label: str,
) -> tuple[dict[tuple[int, int], str], list[str]]:
    """
    Dispatch to sequential or concurrent translation based on `workers`.
    A single worker means plain sequential execution — no thread pool,
    no rate limiter.
    """
    if workers <= 1:
        return translate_sequential(translator, jobs, progress_label=progress_label)
    return translate_concurrent(translator, jobs, workers=workers, progress_label=progress_label)


# ---------------------------------------------------------------------------
# Chunked mode (default)
# ---------------------------------------------------------------------------


def run_chunked(
    in_path: Path,
    out_path: Path,
    chunk_size: int,
    source: str,
    target: str,
    workers: int,
) -> int:
    """
    Default mode: split source into <=`chunk_size`-char blocks at line
    boundaries, translate each block, and write results back in order.

    Runs sequentially with 1 worker, concurrently with N > 1.
    """
    if chunk_size > MAX_CHARS:
        print(f"  ! --chunk-size capped at {MAX_CHARS} (backend limit)", file=sys.stderr)
        chunk_size = MAX_CHARS

    prog_path = progress_path(out_path)

    start_chunk = 0
    if prog_path.is_file():
        try:
            start_chunk = int(prog_path.read_text(encoding="utf-8").strip() or "0")
            print(f"↻ Resuming from chunk {start_chunk} (progress file found)")
        except ValueError:
            print("  ! Progress file unreadable, starting from scratch", file=sys.stderr)
            start_chunk = 0

    with in_path.open("r", encoding="utf-8") as f:
        src_lines = [ln.rstrip("\n") for ln in f]

    chunks = chunk_lines(src_lines, chunk_size)
    total = len(chunks)

    if start_chunk >= total:
        print("✔ Nothing to do — file already fully translated.")
        return 0

    translator = make_translator(source, target)
    mode_label = "sequential" if workers <= 1 else f"{workers} workers"
    print(f"→ {source} → {target}, {total} chunk(s), {mode_label}")

    # ---- Prepare each chunk's sub-pieces (for long-line splitting) --------
    jobs: dict[int, list[str]] = {}
    for idx in range(start_chunk, total):
        sub_pieces: list[str] = []
        for line in chunks[idx]:
            sub_pieces.extend(split_long_line(line, chunk_size))
        jobs[idx] = sub_pieces

    # ---- Translate all pieces (sequential or concurrent) ------------------
    results, errors = run_jobs(translator, jobs, workers=workers, progress_label="chunk")

    with out_path.open("a" if start_chunk > 0 else "w", encoding="utf-8") as fout:
        if errors:
            print(
                f"\n✖ {len(errors)} piece(s) failed. First few:\n  " + "\n  ".join(errors[:5]),
                file=sys.stderr,
            )
            done_chunks = _count_complete_chunks(jobs, results)
            prog_path.write_text(str(done_chunks), encoding="utf-8")
            return 2

        # ---- Write chunk results to file, in order ------------------------
        for chunk_idx in range(start_chunk, total):
            piece_translations = [results[(chunk_idx, p_idx)] for p_idx in range(len(jobs[chunk_idx]))]
            translated = "\n".join(piece_translations)
            fout.write(translated)
            if not translated.endswith("\n"):
                fout.write("\n")

            if (chunk_idx + 1) % SAVE_EVERY == 0 or (chunk_idx + 1) == total:
                prog_path.write_text(str(chunk_idx + 1), encoding="utf-8")
                print(f"  ✓ saved progress at chunk {chunk_idx + 1}/{total}")

        fout.flush()

    prog_path.write_text(str(total), encoding="utf-8")
    print(f"\n✔ Done. Output written to {out_path}")
    return 0


def _count_complete_chunks(
    jobs: dict[int, list[str]],
    results: dict[tuple[int, int], str],
) -> int:
    """Count how many chunks have all their pieces translated (in order)."""
    count = 0
    for chunk_idx in sorted(jobs):
        if chunk_idx != count:
            break
        if all((chunk_idx, p) in results for p in range(len(jobs[chunk_idx]))):
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Line-by-line mode (-l)
# ---------------------------------------------------------------------------


def load_pairs(json_path: Path, src_key: str, tgt_key: str) -> list[dict[str, str]]:
    """Load existing pairs if the JSON file already exists and uses the
    same language keys.  Otherwise start fresh."""
    if not json_path.is_file():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            if data and not (src_key in data[0] and tgt_key in data[0]):
                print(
                    f"  ! Existing JSON uses different keys (expected '{src_key}'/'{tgt_key}'), starting fresh",
                    file=sys.stderr,
                )
                return []
            return data
    except (json.JSONDecodeError, OSError) as err:
        print(f"  ! Could not read existing JSON ({err}), starting fresh", file=sys.stderr)
    return []


def run_line_mode(
    in_path: Path,
    out_path: Path,
    source: str,
    target: str,
    workers: int,
) -> int:
    """
    Translate line by line, print each translation as soon as it is ready,
    and persist {<source>: ..., <target>: ...} pairs into a JSON array.

    Lines longer than MAX_CHARS are split into pieces and re-joined.
    Runs sequentially with 1 worker, concurrently with N > 1.
    """
    prog_path = progress_path(out_path)
    pairs = load_pairs(out_path, source, target)

    start_line = len(pairs)
    if prog_path.is_file():
        try:
            stored = int(prog_path.read_text(encoding="utf-8").strip() or "0")
            start_line = max(start_line, stored)
        except ValueError:
            pass

    if start_line:
        print(f"↻ Resuming from line {start_line} ({len(pairs)} pairs loaded)")

    with in_path.open("r", encoding="utf-8") as f:
        src_lines = [ln.rstrip("\n") for ln in f]
    total = len(src_lines)

    if start_line >= total:
        print("✔ Nothing to do — file already fully translated.")
        return 0

    translator = make_translator(source, target)
    mode_label = "sequential" if workers <= 1 else f"{workers} workers"
    print(f"→ {source} → {target}, {total} line(s), {mode_label}")

    pairs = pairs[:start_line]

    # ---- Build the piece-job list for every remaining line ----------------
    line_pieces: dict[int, list[str]] = {}
    for idx in range(start_line, total):
        line_pieces[idx] = split_long_line(src_lines[idx], MAX_CHARS)

    # ---- Translate all pieces --------------------------------------------
    results, errors = run_jobs(translator, line_pieces, workers=workers, progress_label="line")

    if errors:
        print(
            f"\n✖ {len(errors)} piece(s) failed. First few:\n  " + "\n  ".join(errors[:5]),
            file=sys.stderr,
        )

    # ---- Reassemble pairs in original order, save incrementally -----------
    for idx in range(start_line, total):
        pieces = line_pieces[idx]

        # If any piece for this line failed, skip it (won't be in JSON).
        if not all((idx, p) in results for p in range(len(pieces))):
            print(f"  ! skipping line {idx + 1} (missing pieces)", file=sys.stderr)
            continue

        translated_pieces = [results[(idx, p)] for p in range(len(pieces))]
        translated_full = " ".join(p.strip() for p in translated_pieces).strip()

        pairs.append({source: src_lines[idx], target: translated_full})

        preview_src = src_lines[idx]
        preview_tgt = translated_full
        if len(preview_src) > 120:
            preview_src = preview_src[:117] + "…"
        if len(preview_tgt) > 120:
            preview_tgt = preview_tgt[:117] + "…"

        print(f"[{idx + 1}/{total}]")
        print(f"  {source}: {preview_src}")
        print(f"  {target}: {preview_tgt}")
        if len(pieces) > 1:
            print(f"  (line split into {len(pieces)} pieces)")
        print()

        if (idx + 1) % SAVE_EVERY == 0 or (idx + 1) == total:
            out_path.write_text(
                json.dumps(pairs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            prog_path.write_text(str(idx + 1), encoding="utf-8")
            print(f"  ✓ saved {len(pairs)} pairs to {out_path.name}")

    out_path.write_text(
        json.dumps(pairs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prog_path.write_text(str(len(pairs)), encoding="utf-8")
    print(f"✔ Done. {len(pairs)} pairs saved to {out_path}")
    return 2 if errors else 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    global _limiter  # noqa: PLW0603

    args = parse_args()

    # Validate workers.
    if args.workers < 1:
        print(f"  ! --workers must be >= 1 (got {args.workers}), using 1", file=sys.stderr)
        args.workers = 1

    # Configure the rate limiter:
    #   sequential (1 worker) -> no limiter, plain sleep between requests
    #   concurrent (N workers) -> global limiter with --delay (or default)
    if args.workers > 1:
        delay = args.delay if args.delay is not None else REQUEST_INTERVAL
        _limiter = RateLimiter(delay)
    else:
        _limiter = RateLimiter(0.0)  # disabled

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.is_file():
        print(f"Input file not found: {in_path}", file=sys.stderr)
        return 1

    source = args.source
    target = args.target

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    elif args.line:
        out_path = in_path.with_suffix(".json")
    else:
        out_path = in_path.with_name(f"{in_path.stem}.{target}{in_path.suffix}")

    if args.line:
        return run_line_mode(in_path, out_path, source, target, args.workers)
    return run_chunked(in_path, out_path, args.chunk_size, source, target, args.workers)


if __name__ == "__main__":
    sys.exit(main())

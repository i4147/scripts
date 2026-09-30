#!/data/data/com.termux/files/home/.local/bin/python
from __future__ import annotations

import multiprocessing as mp
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Iterator, Set

from spellchecker import SpellChecker

WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*", re.UNICODE)
_TEXT_CHARS = bytes({7, 8, 9, 10, 12, 13, 27} | (set(range(0x20, 0x100)) - {0x7F}))
_OUTPUT_NAME = "custom_dict.txt"


def _is_binary(file_path: Path, chunk_size: int = 1024, threshold: float = 0.30) -> bool:
    try:
        with file_path.open("rb") as f:
            chunk = f.read(chunk_size)
    except OSError:
        return True
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    nontext = chunk.translate(None, _TEXT_CHARS)
    return (len(nontext) / len(chunk)) > threshold


def _extract_words(file_path: Path) -> Set[str]:
    words: Set[str] = set()
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                for match in WORD_RE.findall(line):
                    token = match.strip("'\u2019").lower()
                    if len(token) > 1:
                        words.add(token)
    except OSError:
        return words
    return words


def _process_file(file_path_str: str) -> Set[str]:
    path = Path(file_path_str)
    try:
        if path.is_symlink() or not path.is_file():
            return set()
        if _is_binary(path):
            return set()
        return _extract_words(path)
    except OSError:
        return set()


def _iter_candidate_files(root: Path, skip: Path) -> Iterator[Path]:
    for entry in root.rglob("*"):
        try:
            if entry == skip:
                continue
            if entry.is_symlink() or not entry.is_file():
                continue
        except OSError:
            continue
        yield entry


def collect_words(root_dir: Path, output_path: Path, workers: int | None = None) -> Set[str]:
    all_words: Set[str] = set()
    files = [str(p) for p in _iter_candidate_files(root_dir, output_path)]
    if not files:
        return all_words
    if workers is None:
        workers = max(1, os.cpu_count() or 1)
    chunksize = max(1, len(files) // (workers * 8))
    with mp.Pool(processes=workers) as pool:
        try:
            for word_set in pool.imap_unordered(_process_file, files, chunksize=chunksize):
                all_words.update(word_set)
        except KeyboardInterrupt:
            pool.terminate()
            pool.join()
            raise
    return all_words


def filter_unknown_words(words: Set[str]) -> Set[str]:
    spell = SpellChecker()
    try:
        return set(spell.unknown(words))
    except Exception:
        unknown: Set[str] = set()
        for word in words:
            try:
                if word not in spell:
                    unknown.add(word)
            except Exception:
                continue
        return unknown


def save_words(words: Iterable[str], output_path: Path) -> None:
    text = "\n".join(sorted(words))
    if text:
        text += "\n"
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    root_dir = Path.cwd()
    output_path = root_dir / _OUTPUT_NAME

    try:
        all_words = collect_words(root_dir, output_path)
    except Exception as exc:
        print(f"error while collecting words: {exc}", file=sys.stderr)
        return 1

    try:
        unknown_words = filter_unknown_words(all_words)
    except Exception as exc:
        print(f"error while filtering words: {exc}", file=sys.stderr)
        return 1

    try:
        save_words(unknown_words, output_path)
    except OSError as exc:
        print(f"error while writing output: {exc}", file=sys.stderr)
        return 1

    print(f"Total unique words found: {len(all_words)}")
    print(f"Words not in pyspellchecker dictionary: {len(unknown_words)}")
    print(f"Saved to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

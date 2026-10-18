from pathlib import Path
from typing import Tuple, List
import re
import argparse
import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from loguru import logger


class CommentRemover:
    pass


class RegexRemover(CommentRemover):
    def __init__(self):
        self.inline_comment = re.compile("(?<!\\\\)#.*$", re.MULTILINE)
        self.shebang = re.compile("^#!.*$", re.MULTILINE)

    def process_file(self, content: str) -> Tuple[str, int]:
        original = content
        comment_count = 0
        shebangs = self.shebang.findall(content)
        comment_count += len(shebangs)
        content = self.shebang.sub("", content)
        matches = list(self.inline_comment.finditer(content))
        comment_count += len(matches)
        content = self.inline_comment.sub("", content)
        return (content, comment_count)


def is_bash_file(p: Path) -> bool:
    try:
        if p.suffix == ".sh":
            return True
        if not p.is_file():
            return False
        with p.open("rb") as f:
            first = f.readline(512)
        try:
            first_line = first.decode("utf-8", "ignore")
        except Exception:
            first_line = ""
        if first_line.startswith("#!"):
            lower = first_line.lower()
            return "sh" in lower or "bash" in lower or "dash" in lower
    except Exception:
        return False
    return False


def collect_targets(inputs: List[str]) -> List[Path]:
    paths: List[Path] = []
    if not inputs:
        inputs = ["."]
    for arg in inputs:
        p = Path(arg)
        if p.is_file():
            if is_bash_file(p):
                paths.append(p)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and is_bash_file(f):
                    paths.append(f)
    unique = list(dict.fromkeys(str(x.resolve()) for x in paths))
    return [Path(x) for x in unique]


def process_single(path_str: str) -> Tuple[str, bool, int, str]:
    path = Path(path_str)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        remover = RegexRemover()
        new_text, removed = remover.process_file(text)
        if new_text != text:
            mode = path.stat().st_mode
            path.write_text(new_text, encoding="utf-8", errors="replace")
            os.chmod(path, mode)
            return (path_str, True, removed, "")
        return (path_str, False, 0, "")
    except Exception as e:
        return (path_str, False, 0, str(e))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", help="files or directories to process")
    parser.add_argument("--workers", "-j", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if not args.quiet:
        logger.remove()
        logger.add(sys.stderr, level="INFO", colorize=True)
    targets = collect_targets(args.paths)
    total = len(targets)
    if total == 0:
        logger.info("no bash files found")
        return 0
    processed = 0
    modified = 0
    comments_removed = 0
    with ProcessPoolExecutor(max_workers=args.workers) as exe:
        futures = {exe.submit(process_single, str(p)): p for p in targets}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                path_str, changed, removed, err = fut.result()
                processed += 1
                if changed:
                    modified += 1
                    comments_removed += removed
                    logger.info("modified {} (removed {} comments)", path_str, removed)
                elif err:
                    logger.error("error processing {}: {}", path_str, err)
                else:
                    logger.info("unchanged {}", path_str)
            except Exception as e:
                logger.error("worker failure for {}: {}", p, e)
    logger.info("processed {} files, modified {}, total comments removed {}", total, modified, comments_removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

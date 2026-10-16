import pathlib
import re
import string
import sys
import tokenize
from io import StringIO

from cy_heu import heuristic_score
from tqdm import tqdm


def is_noise_line(line) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.search(r"\s{10,}", line):
        return True
    letters = sum(c.isalpha() for c in stripped)
    printable = sum(c in string.printable for c in stripped)
    if printable == 0:
        return True
    return letters / printable < 0.25


def tokenizer_valid_python(block: str) -> bool | None:
    try:
        tokenize.generate_tokens(StringIO(block).readline)
        return True
    except:
        return False


def is_python_block(lines) -> bool:
    block_text = "".join(lines)
    score = heuristic_score(lines)
    if score >= 3:
        return True
    return bool(score >= 1 and tokenizer_valid_python(block_text))


def analyze_block(block_lines) -> str:
    if is_python_block(block_lines):
        return "".join(block_lines)
    return ""


def extract_python_blocks(filename: str) -> None:
    pool = ProcessPoolExecutor(cpu_count())
    async_tasks = []
    total_size = pathlib.Path(filename).stat().st_size
    processed = 0
    inside_block = False
    current_block = []
    with (
        pathlib.Path(filename).open(encoding="utf-8") as f,
        tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc="Processing",
            ncols=80,
        ) as bar,
    ):
        for raw_line in f:
            processed += len(raw_line)
            bar.update(len(raw_line))
            stripped = raw_line.rstrip("\n")
            if not inside_block:
                if stripped.startswith("```"):
                    inside_block = True
                    current_block = []
                continue
            if stripped.startswith("```"):
                inside_block = False
                async_tasks.append(
                    pool.apply_async(
                        analyze_block,
                        (current_block,),
                    )
                )
                current_block = []
            else:
                current_block.append(raw_line)
    pool.close()
    pool.join()
    with pathlib.Path("out.txt").open("w", encoding="utf-8") as out:
        for task in async_tasks:
            block = task.get()
            if not block:
                continue
            cleaned = [line for line in block.splitlines(True) if not is_noise_line(line)]
            out.write("".join(cleaned))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: extractor.py <filename>")
        sys.exit(1)
    extract_python_blocks(sys.argv[1])


if __name__ == "__main__":
    main()

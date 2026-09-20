import sys
from collections import deque
from multiprocessing import Pool
from pathlib import Path

from dh import format_size, get_nobinary, get_size
from loguru import logger
from toolz import compose, frequencies
from toolz.curried import map

MAX_QUEUE = 16


def stem(word):
    return word.lower().rstrip(",.|;:'\"").lstrip("'\"")


def process_file(fp):
    word_count = compose(frequencies, map(stem), str.split)
    content = fp.read_text(encoding="utf-8")
    result = word_count(content)
    logger.info(sorted(result))
    return result


def main() -> None:
    root_dir = Path.cwd()
    before = get_size(root_dir)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_nobinary(root_dir)
    results = {}
    with Pool(8) as pool:
        pending = deque()
        for f in files:
            pending.append(pool.apply_async(process_file, (f,)))
            if len(pending) > MAX_QUEUE:
                result = pending.popleft().get()
                for x in result:
                    if x not in results:
                        results[x] = result.get(x)
                    else:
                        results[x] += result.get(x)
        while pending:
            result = pending.popleft().get()
            for x in result:
                if x not in results:
                    results[x] = result.get(x)
                else:
                    results[x] += result.get(x)
    outfile = Path("word_count.txt")
    logger.info(sorted(results))
    with Path(outfile).open("w", encoding="utf-8") as fo:
        fo.writelines(f"{v!s} : {results.get(v)!s}\n" for v in results)
    diff_size = before - get_size(root_dir)
    print(f"space saved : {format_size(diff_size)}")


if __name__ == "__main__":
    main()

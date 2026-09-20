import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dh import get_nobinary
import sys
from pathlib import Path
from dh import get_nobinary

def process_file(path: Path, max_blank_keep: int):
    try:
        text = path.read_text(encoding='utf-8')
    except Exception:
        return (path, 0)
    lines = text.splitlines(keepends=False)
    new_lines = []
    blank_run = 0
    removed = 0
    for line in lines:
        if line.strip() == '':
            blank_run += 1
            if blank_run <= max_blank_keep:
                new_lines.append('')
            else:
                removed += 1
        else:
            blank_run = 0
            new_lines.append(line)
    if removed > 0:
        path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    return (path, removed)

def main():
    parser = argparse.ArgumentParser(description='Remove blank lines from files recursively.')
    parser.add_argument('-n', type=int, default=1, help='Max number of consecutive blank lines to keep (default: 1).')
    args = parser.parse_args()
    cwd = Path.cwd()
    in_args = sys.argv[1:]
    files = []
    if in_args:
        for arg in in_args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_nobinary(p))
    else:
        files = get_nobinary(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    total_removed = 0
    with ThreadPoolExecutor() as exe:
        futures = {exe.submit(process_file, f, args.n): f for f in files}
        for fut in as_completed(futures):
            path, removed = fut.result()
            total_removed += removed
            print(f'{path}: removed {removed} blank lines')
    print(f'\nTotal blank lines removed: {total_removed}')
if __name__ == '__main__':
    main()
debug abd optimize

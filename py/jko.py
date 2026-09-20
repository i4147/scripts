import ast
import re
import sys
from multiprocessing import Pool
from pathlib import Path
from dh import format_size, get_pyfiles, get_size
from termcolor import cprint


def process_file(file_path: Path) -> None:
    before = get_size(file_path)
    content = file_path.read_text(encoding="utf-8")
    code = re.sub("#.*", "", content)
    code = re.sub('""".*?"""', "", code)
    code = re.sub("'''.*?'''", "", code)
    code = re.sub("\\n\\n+", "\n", code)
    try:
        ast.parse(code)
        file_path.write_text(code, encoding="utf-8")
        after = get_size(file_path)
        print(f"{file_path.name}", end=" ")
        print(format_size(before - after))
        return
    except:
        cprint(f"{file_path.name} ast parse error", "cyan")
        return


def main() -> None:
    dir = Path.cwd()
    initsize = get_size(dir)
    args = sys.argv[1:]
    if args:
        files = [Path(f) for f in args]
        for f in files:
            process_file(f)
    else:
        files = get_pyfiles(dir)
        p = Pool(8)
        for f in files:
            p.apply_async(process_file, (f,))
        p.close()
        p.join()
    diff_size = initsize - get_size(dir)
    print(f"space saved : {format_size(diff_size)}")


if __name__ == "__main__":
    main()

import ast
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Final
from loguru import logger



LIC_PATH = Path.home() / "lic"
IMPORT_LINE = "from dh import cprint\n"
POOL_SIZE = 8



def load_code_block():
    try:
        content = LIC_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"Failed to read {LIC_PATH}: {e}")
        raise
    
    return [line.rstrip() for line in content.strip("\n").splitlines()]
def find_block_range(lines, block_lines):
    normalized = [line.rstrip("\n").rstrip() for line in lines]
    n, m = len(normalized), len(block_lines)
    for i in range(n - m + 1):
        if normalized[i : i + m] == block_lines:
            return (i, i + m)
    return None
def already_imports_cprint(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "dh":
            if any(alias.name == "cprint" for alias in node.names):
                return True
        if isinstance(node, ast.Import) and any(
            alias.name == "cprint" for alias in node.names
        ):
            return True
    return False
def last_import_end_line(tree):
    last_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.end_lineno is not None:
                last_end = max(last_end, node.end_lineno)
        else:
            break
    return last_end



def process_file(path):
    path = Path(path)
    if path.resolve() == Path(__file__).resolve():
        return
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        logger.warning(f"Skipping {path}: {e}")
        return
    block_lines = load_code_block()
    lines = content.splitlines(keepends=True)
    match = find_block_range(lines, block_lines)
    if match is None:
        return
    start, end = match
    
    if start > 0 and lines[start - 1].strip() == "":
        start -= 1
    if end < len(lines) and lines[end].strip() == "":
        end += 1
    del lines[start:end]
    new_content = "".join(lines)
    
    try:
        tree = ast.parse(new_content)
    except SyntaxError as e:
        logger.warning(f"Skipping write for {path} (would break syntax): {e}")
        return
    
    if already_imports_cprint(tree):
        if new_content != content:
            path.write_text(new_content, encoding="utf-8")
            print(f"Removed block: {path} (cprint already imported)")
        return
    
    body_lines = new_content.splitlines(keepends=True)
    last_end = last_import_end_line(tree)
    if last_end > 0:
        insert_idx = last_end
    else:
        insert_idx = 1 if body_lines and body_lines[0].startswith("#!") else 0
    body_lines.insert(insert_idx, IMPORT_LINE)
    final_content = "".join(body_lines)
    path.write_text(final_content, encoding="utf-8")
    print(f"Removed block and added import: {path}")



def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    if args:
        py_files = [Path(p) for p in args]
    else:
        
        from dh import get_pyfiles  
        py_files = get_pyfiles(cwd)
    with Pool(POOL_SIZE) as pool:
        
        async_results = [pool.apply_async(process_file, (path,)) for path in py_files]
        for ar in async_results:
            try:
                ar.get()
            except Exception as e:
                logger.error(f"Error processing file: {e}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

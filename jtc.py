import ast
from pathlib import Path
from fastwalk import walk_files
def process_file(path):
    path = Path(path)
    try:
        cmd = f"just-the-code -s --language=python {path!s}"
        ret, new_code, _stderr = run_command(cmd)
        if ret == 0:
            try:
                ast.parse(new_code)
                path.write_text(new_code, encoding="utf-8")
                print(f"{path.name} updated.")
                return True
            except:
                print("result code is not valid")
                return False
    except Exception as e:
        print(f"Error processing {path.name}: {e}")
        return False
def walk_directory(root):
    files = []
    for pth in walk_files(root):
        path = Path(pth)
        if path.suffix == ".py":
            files.append(path)
    return files
def main():
    cwd = Path.cwd()
    files = walk_directory(cwd)
    for f in files:
        print(process_file(f))
if __name__ == "__main__":
    raise SystemExit(main())

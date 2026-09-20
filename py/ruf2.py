import os
import subprocess
import sys
from multiprocessing import Lock, Pool, cpu_count
from pathlib import Path

print_lock = Lock()


def is_python_file(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix == "":
        try:
            with Path(path).open("rb") as f:
                head = f.read(64)
                if b"python" in head and b"#!" in head:
                    return True
        except Exception:
            return False
    return False


def run_command(cmd: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return (result.returncode, result.stdout, result.stderr)
    except Exception as e:
        return (-1, "", str(e))


def process_file(file_path_str) -> None:
    path = Path(file_path_str)
    check_cmd = ["ruff", "check", "--fix", "--unsafe-fixes", "--line-length", "79", "--quiet", str(path)]
    rc_check, out_check, err_check = run_command(check_cmd)
    format_cmd = ["ruff", "format", "--config", "/data/data/com.termux/files/home/.config/ruff/ruff.toml", str(path)]
    rc_fmt, _out_fmt, err_fmt = run_command(format_cmd)
    output = []
    if rc_check != 0 or err_check.strip():
        output.append(f"--- Issues fixing {path.name} ---")
        if err_check.strip():
            output.append(err_check.strip())
        if out_check.strip():
            output.append(out_check.strip())
    if rc_fmt != 0 or err_fmt.strip():
        output.append(f"--- Issues formatting {path.name} ---")
        if err_fmt.strip():
            output.append(err_fmt.strip())
    if output:
        with print_lock:
            print("\n".join(output))
            sys.stdout.flush()


def get_all_files(root_dir: Path):
    py_files = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [
            d for d in dirs if d not in {".git", ".venv", "venv", "__pycache__", "build", "dist", "node_modules"}
        ]
        for file in files:
            file_path = Path(root) / file
            if is_python_file(file_path):
                py_files.append(str(file_path))
    return py_files


def main() -> None:
    try:
        subprocess.run(["ruff", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Error: 'ruff' is not installed or not in PATH.")
        print("Please run: pip install ruff")
        sys.exit(1)
    root_dir = Path.cwd()
    files = get_all_files(root_dir)
    if not files:
        return
    num_procs = min(len(files), cpu_count())
    with Pool(num_procs) as pool:
        pool.map(process_file, files)


if __name__ == "__main__":
    main()

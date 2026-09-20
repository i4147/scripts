import os
import subprocess
from sys import exit
from time import perf_counter


def run_command(cmd: str, shell: bool = True) -> tuple[str, str, int]:
    try:
        result = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
        )
        return (
            result.stdout,
            result.stderr,
            result.returncode,
        )
    except Exception as e:
        return "", str(e), -1


def process_file(fp: str) -> None:
    cmd = f"prettier -w {fp!s}"
    _out, _err, code = run_command(cmd)
    if code == 0:
        print("ok")
        return True
    else:
        print("error")
        return False


def main() -> None:
    start = perf_counter()
    for pth in os.listdir("."):
        process_file(pth)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())

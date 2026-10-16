import ctypes
import subprocess
import sys
from pathlib import Path

from dh import cprint, get_files
from loguru import logger

logger.remove()
logger.add("/sdcard/soverify.log")
N_JOBS = -1


class CtypesVerifier:
    def __init__(self, verbose: bool = True) -> None:
        self.verbose: bool = verbose
        self.platform: str = sys.platform

    def log(self, message: str) -> None:
        if self.verbose:
            logger.debug(f"[CTYPES] {message}")

    def verify_so_file(self, file_path: Path) -> tuple[bool, str]:
        if not file_path.exists():
            return (False, "File does not exist")
        try:
            ctypes.CDLL(str(file_path), use_errno=True)
            err = ctypes.get_errno()
            if err:
                self.log(f"Warning: errno set to {err}")
            return (True, "ok")
        except OSError as e:
            error_msg = f"OSError: {e!s}"
            self.log(f"Failed to load: {error_msg}")
            print(f"Failed to load: {error_msg}")
            cprint(f"Failed to load: {error_msg}", "yellow")
            return (False, error_msg)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e!s}"
            self.log(f"Failed to load: {error_msg}")
            return (False, error_msg)

    def verify_with_symbols(self, file_path: Path) -> tuple[bool, dict]:
        can_load, msg = self.verify_so_file(file_path)
        symbol_info = {
            "can_load": can_load,
            "message": msg,
            "has_symbols": False,
            "symbol_count": 0,
        }
        if not can_load:
            return (can_load, symbol_info)
        try:
            result = subprocess.run(["nm", str(file_path)], capture_output=True, timeout=10, text=True)
            if result.returncode == 0:
                lines = [l for l in result.stdout.split("\n") if l.strip()]
                symbol_info["symbol_count"] = len(lines)
                symbol_info["has_symbols"] = len(lines) > 0
                self.log(f"Found {len(lines)} symbols")
        except Exception as e:
            self.log(f"Could not extract symbols: {e!s}")
        return (can_load, symbol_info)


def process_file(path) -> bool | None:
    path = Path(path)
    try:
        verifier = CtypesVerifier()
        res = verifier.verify_so_file(path)[0]
        print(f"file:{path} | {res}")
        if res:
            return True
    except:
        return False


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd, ext=[".so"])
    for f in files:
        try:
            if not process_file(f):
                logger.debug(f"{f.name}: error")
        except:
            print(f"{f.name}: error")
            logger.debug(f"{f.name}: error")


if __name__ == "__main__":
    gil_state = ctypes.pythonapi.PyGILState_Ensure()
    print(gil_state)
    main()
    ctypes.pythonapi.PyGILState_Release(gil_state)
    sys.exit(1)

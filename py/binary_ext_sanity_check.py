from pathlib import Path
from sys import exit as _exit
from dh import BIN_EXT, TXT_EXT, get_filez, gext, is_binary, is_text_file
from termcolor import cprint


def is_really_binary(path: Path, blocksize: int = 32 * 1024 * 1024) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read()
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        text_chars = bytearray(range(32, 127)) + b"\n\r\t\b"
        nontext = sum(1 for b in chunk if b not in text_chars)
        percentage = nontext / len(chunk)
        for encoding in (
            "utf-8",
            "utf-16",
            "utf-32",
        ):
            try:
                chunk.decode(encoding)
                return False
            except (
                UnicodeDecodeError,
                LookupError,
            ):
                continue
        return percentage > 0.30
    except Exception:
        return True


def main() -> None:
    cwd = Path("/sdcard")
    seen = set()
    new_exts = []
    for path in get_filez(cwd):
        ext = gext(path)
        if ext and not ext in BIN_EXT and not ext in TXT_EXT:
            if not ext in seen:
                new_exts.append(ext)
                seen.add(ext)
                cprint(f"new extension: {ext}", "grey")
        if path.suffix in BIN_EXT:
            if not is_binary(path):
                cprint(f"{path.name} is_binary error", "blue")
            if not is_really_binary(path):
                cprint(f"{path.name} is_really_binary error", "red")
            if is_text_file(path):
                cprint(f"{path.name} is_text_file error", "magenta")
        if path.suffix in TXT_EXT:
            if is_binary(path):
                cprint(f"{path.name} is_binary error", "yellow")
            if is_really_binary(path):
                cprint(f"{path.name} is_really_binary error", "green")
            if not is_text_file(path):
                cprint(f"{path.name} is_text_file error", "cyan")
    with open("new_exts", "w") as f:
        for k in new_exts:
            f.write(f"{k}\n")


if __name__ == "__main__":
    _exit(main())

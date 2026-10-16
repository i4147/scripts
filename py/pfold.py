from _io import TextIOWrapper
import argparse
import pathlib
import shutil
import sys


def wrap_line(
    line: str,
    width: int,
    break_at_spaces: bool,
    count_bytes: bool,
):
    out = []
    remaining = line
    while True:
        if count_bytes:
            idx = 0
            total_bytes = 0
            for i, ch in enumerate(remaining):
                clen = len(ch.encode())
                if total_bytes + clen > width:
                    break
                total_bytes += clen
                idx = i + 1
        else:
            idx = min(len(remaining), width)
        if len(remaining) <= width:
            out.append(remaining)
            break
        if break_at_spaces:
            cut = remaining.rfind(" ", 0, idx + 1)
            if cut == -1:
                cut = idx
        else:
            cut = idx
        out.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return out


def fold_stream_to_lines(
    stream: TextIOWrapper,
    width: int,
    break_at_spaces: bool,
    count_bytes: bool,
):
    out = []
    for raw_line in stream:
        line = raw_line.rstrip("\n")
        wrapped = wrap_line(
            line,
            width,
            break_at_spaces,
            count_bytes,
        )
        out.extend(wrapped)
    return out


def fold_stream_print(
    stream,
    width: int,
    break_at_spaces: bool,
    count_bytes: bool,
) -> None:
    for raw_line in stream:
        line = raw_line.rstrip("\n")
        wrapped = wrap_line(
            line,
            width,
            break_at_spaces,
            count_bytes,
        )
        for w in wrapped:
            print(w)


def main() -> None:
    parser = argparse.ArgumentParser(description="Python implementation of GNU fold with auto mode as default.")
    parser.add_argument("-w", "--width", type=int, default=80)
    parser.add_argument("-s", "--spaces", action="store_true")
    parser.add_argument("-b", "--bytes", action="store_true")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto width = terminal_width - 5 (forces -s, disables -b)",
    )
    parser.add_argument(
        "-W",
        "--write",
        action="store_true",
        help="Overwrite the input file(s) in place, no backup",
    )
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    if not any(vars(args).values()):
        try:
            term_width = shutil.get_terminal_size().columns
        except OSError:
            term_width = 80
        auto_width = max(10, term_width - 5)
        args.width = auto_width
        args.spaces = True
        args.bytes = False
        args.auto = True
    if args.auto:
        try:
            term_width = shutil.get_terminal_size().columns
        except OSError:
            term_width = 80
        auto_width = max(10, term_width - 5)
        args.width = auto_width
        args.spaces = True
        args.bytes = False
    if args.width <= 0:
        msg = "width must be positive"
        raise ValueError(msg)
    if args.write:
        if not args.files:
            sys.exit("ERROR: --write requires at least one file (stdin not allowed).")
        for path in args.files:
            with pathlib.Path(path).open(encoding="utf-8", errors="replace") as f:
                folded_lines = fold_stream_to_lines(
                    f,
                    args.width,
                    args.spaces,
                    args.bytes,
                )
            with pathlib.Path(path).open("w", encoding="utf-8") as f:
                f.writelines(line + "\n" for line in folded_lines)
        return
    if not args.files:
        fold_stream_print(
            sys.stdin,
            args.width,
            args.spaces,
            args.bytes,
        )
    else:
        for path in args.files:
            with pathlib.Path(path).open(encoding="utf-8", errors="replace") as f:
                fold_stream_print(
                    f,
                    args.width,
                    args.spaces,
                    args.bytes,
                )


if __name__ == "__main__":
    main()

import os
import platform
import struct
import sys
import time

from colorama import Back, Fore, Style, init


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def get_terminal_size() -> tuple[int, int]:
    current_os = platform.system()
    tuple_xy = None
    if current_os == "Linux":
        tuple_xy = _get_terminal_size_linux()
    if tuple_xy is None:
        print("default")
        tuple_xy = (80, 25)
    return tuple_xy


def _get_terminal_size_linux() -> tuple[int, int] | None:
    def ioctl_GWINSZ(fd: int):
        try:
            import fcntl
            import termios

            return struct.unpack(
                "hh",
                fcntl.ioctl(fd, termios.TIOCGWINSZ, "1234"),
            )
        except:
            pass

    cr = ioctl_GWINSZ(0) or ioctl_GWINSZ(1) or ioctl_GWINSZ(2)
    if not cr:
        try:
            fd = os.open(os.ctermid(), os.O_RDONLY)
            cr = ioctl_GWINSZ(fd)
            os.close(fd)
        except:
            pass
    if not cr:
        try:
            cr = (
                os.environ["LINES"],
                os.environ["COLUMNS"],
            )
        except:
            return None
    return int(cr[1]), int(cr[0])


def aligncenter(content, width, height) -> None:
    length = len(content)
    if length < width:
        borderlength = int((width - length) / 2)
        print("\n")
        print(width * "=")
        print(
            " " * (borderlength - 1)
            + " "
            + Fore.RED
            + Style.BRIGHT
            + content
            + Style.RESET_ALL
            + " "
            + " " * (borderlength - 1)
        )
        print(width * "=")
        print("\n")


init()
print(Fore.RED + "some red text")
print(Back.GREEN + "and with a green background")
print(Style.BRIGHT + "and in dim text")
print(Fore.RESET + Back.RESET + Style.RESET_ALL)
print("back to normal now")
if __name__ == "__main__":
    sizex, sizey = get_terminal_size()
    print("width =", sizex, "height =", sizey)
    data = "Simplify"
    aligncenter(content=data, width=sizex, height=sizey)
    time.sleep(2)
    i = 0
    for i in range(50):
        print(
            "\r" + Back.RED + " " * 50 + Back.RESET,
        )
        print(
            "\r" + Back.GREEN + " " * (i - 2) + str(i) + "%" + Back.RESET,
        )
        if i % 4 == 0:
            print("\\\\")
        if i % 4 == 1:
            print("||")
        if i % 4 == 2:
            print("//")
        if i % 4 == 3:
            print("==")
        print(
            " " * (50 - i),
            "[" + str(i) + "%|50%]",
        )
        time.sleep(0.1)
        sys.stdout.flush()

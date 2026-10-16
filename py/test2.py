import os


def cmd1(strings) -> str:
    return os.popen(strings).readlines()[0].rstrip()


def cmd2(strings: str) -> list[str]:
    return cmd1(strings).split()


def main() -> None:
    cmd2("ls")


if __name__ == "__main__":
    main()

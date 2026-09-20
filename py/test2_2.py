import os
import subprocess


def cmd1(strings):
    return os.popen(strings).readlines()[0].rstrip()


def cmd2(strings):
    return cmd1(strings).split()


def main():
    cmd1("clang")
    cmd2("ls")


if __name__ == "__main__":
    main()

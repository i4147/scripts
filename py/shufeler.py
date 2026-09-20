import argparse
import random
import secrets
from pathlib import Path


def enhanced_shuffle(
    input_file,
) -> None:
    with Path(input_file).open(encoding="utf-8") as f:
        lines = f.readlines()
    original_count = len(lines)
    print(f"Read {original_count} lines from {input_file}")
    shuffled_lines = lines.copy()
    repeats = 1
    for _i in range(repeats):
        random.shuffle(shuffled_lines)
        crypto_shuffle(shuffled_lines)
        shuffle3(shuffled_lines)
        weighted_shuffle(shuffled_lines)
    with Path(input_path).open("w", encoding="utf-8") as f:
        f.writelines(shuffled_lines)
    print(f"Output written to: {output_path}")


def crypto_shuffle(lst: list[str]) -> None:
    for i in range(len(lst) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        lst[i], lst[j] = lst[j], lst[i]


def shuffle3(lst: list[str]) -> None:
    sys_random = random.SystemRandom()
    for i in range(len(lst) - 1, 0, -1):
        j = sys_random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]


def weighted_shuffle(lst: list[str]) -> None:
    n = len(lst)
    for i in range(n - 1, 0, -1):
        j = random.randint(0, i)
        lst[i], lst[j] = lst[j], lst[i]
    if n > 1:
        for i in range(n - 1):
            swap_pos = random.randint(i + 1, n - 1)
            lst[i], lst[swap_pos] = (
                lst[swap_pos],
                lst[i],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Randomize lines in a file")
    parser.add_argument("input_file", "-i", help="Input file to shuffle")
    args = parser.parse_args()
    enhanced_shuffle(args.input_file)


if __name__ == "__main__":
    main()

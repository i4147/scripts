from collections import Counter
from pathlib import Path


def levenshtein_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current_row = [i]
        for j, cb in enumerate(b, 1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (ca != cb)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def similarity(a: str, b: str) -> float:
    dist = levenshtein_distance(a, b)
    max_len = max(len(a), len(b))
    return 1 - dist / max_len if max_len else 1.0


def group_similar(names: list[str], threshold: float = 0.8):
    groups = []
    used = set()
    for name in names:
        if name in used:
            continue
        group = [name]
        used.add(name)
        for other in names:
            if other in used:
                continue
            if similarity(name.lower(), other.lower()) >= threshold:
                group.append(other)
                used.add(other)
        if len(group) > 1:
            groups.append(group)
    return groups


def main() -> None:
    cwd = Path.cwd()
    counter = Counter(p.stem for p in cwd.rglob("*") if not p.is_symlink() and p.is_file() and not ".git" in p.parts)
    for name, count in counter.most_common(100):
        if count > 2:
            print(f"{name}: {count}")
    print("\n=== Similar Filename Groups ===")
    groups = group_similar(list(counter.keys()), threshold=0.8)
    if not groups:
        print("No similar groups found.")
    else:
        for i, group in enumerate(groups, 1):
            print(f"Group {i}: {', '.join(group)}")


if __name__ == "__main__":
    main()

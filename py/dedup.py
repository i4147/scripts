import json
from pathlib import Path


def main():
    path = Path.cwd() / "merged.json"
    if not path.exists():
        print(f"{path.name} not found.")
        return

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned = {}
    total_before = total_after = 0

    for word, translations in data.items():
        if not isinstance(translations, list):
            translations = [translations]

        total_before += len(translations)
        deduped = list(dict.fromkeys(translations))  
        total_after += len(deduped)
        cleaned[word] = deduped

    with path.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    print(f"Processed {len(cleaned)} words in {path.name}")
    print(f"Removed {total_before - total_after} duplicate(s) ({total_before} -> {total_after})")


if __name__ == "__main__":
    main()

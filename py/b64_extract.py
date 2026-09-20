import os
import pathlib
import re


def extract_base64_from_file(filepath: str):
    content = pathlib.Path(filepath).read_text(encoding="utf-8", errors="ignore")
    base64_pattern = r"data:([a-zA-Z]+\/[a-zA-Z-+.]+)?;base64,([a-zA-Z0-9+/=]+)"
    return re.findall(base64_pattern, content)


def main() -> None:
    for filename in os.listdir("."):
        if filename.endswith((".js", ".css")):
            filepath = os.path.join(".", filename)
            matches = extract_base64_from_file(filepath)
            if matches:
                print(f"Found Base64 in {filename}:")
                for i, (mime, data) in enumerate(matches, 1):
                    print(f"  {i}. MIME: {mime or 'unknown'}, Data: {data[:50]}...")
                print()


if __name__ == "__main__":
    main()

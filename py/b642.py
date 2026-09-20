import base64
import os
import pathlib
import re


def extract_and_replace_base64(filepath: str):
    content = pathlib.Path(filepath).read_text(encoding="utf-8", errors="ignore")
    base64_pattern = r"(data:([a-zA-Z]+\/[a-zA-Z-+.]+)?;base64,([a-zA-Z0-9+/=]+))"
    matches = re.finditer(base64_pattern, content)
    new_content = content
    extracted_files = []
    for match in matches:
        full_match, mime, data = match.groups()
        mime_type = mime or "unknown"
        ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"
        extracted_filename = f"extracted_{pathlib.Path(filepath).name}_{len(extracted_files)}.{ext}"
        pathlib.Path(extracted_filename).write_bytes(base64.b64decode(data))
        new_content = new_content.replace(
            full_match,
            f"/* Extracted to {extracted_filename} */",
        )
        extracted_files.append(extracted_filename)
    if extracted_files:
        pathlib.Path(filepath).write_text(new_content, encoding="utf-8")
        return extracted_files
    return []


def main() -> None:
    for filename in os.listdir("."):
        if filename.endswith((".js", ".css")):
            filepath = os.path.join(".", filename)
            extracted = extract_and_replace_base64(filepath)
            if extracted:
                print(f"Processed {filename}, extracted files: {', '.join(extracted)}")


if __name__ == "__main__":
    main()

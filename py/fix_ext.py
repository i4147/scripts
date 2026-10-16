import pathlib

import magic


def detect_file_type(file_path: str) -> str:
    try:
        mime = magic.from_file(file_path, mime=True)
        description = magic.from_file(file_path)
        return f"{description} (MIME: {mime})"
    except FileNotFoundError:
        return "File not found."
    except Exception as e:
        return f"Error detecting file type: {e}"


if __name__ == "__main__":
    file_path = "example.txt"
    pathlib.Path(file_path).write_text("This is a test file.", encoding="utf-8")
    print(f"Detecting file type for '{file_path}':")
    print("Using 'magic' library:", detect_file_type(file_path))
    image_path = "example.jpg"
    pathlib.Path(image_path).write_bytes(b"\xff\xd8\xff\xe0")
    print(f"\nDetecting file type for '{image_path}':")
    print("Using 'magic' library:", detect_file_type(image_path))

import base64
import sys
from pathlib import Path


def decode_base64_lines(input_txt_path: str, output_folder: str = "decoded_files") -> None:
    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)
    success_count = 0
    error_count = 0
    try:
        with Path(input_txt_path).open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    decoded_bytes = base64.b64decode(line.strip())
                    output_filename = f"decoded_{i:04d}.bin"
                    output_path = output_dir / output_filename
                    Path(output_path).write_bytes(decoded_bytes)
                    print(f"✓ Line {i:4d} → {output_path}")
                    success_count += 1
                except Exception as e:
                    print(f"✗ Line {i:4d} failed: {e}")
                    error_count += 1
        print("\n" + "=" * 50)
        print("Finished!")
        print(f"Successfully decoded: {success_count} files")
        print(f"Failed            : {error_count} lines")
        if success_count > 0:
            print(f"Files saved in: {output_dir.resolve()}")
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_txt_path}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    INPUT_FILE = sys.argv[1]
    OUTPUT_FOLDER = "decoded_output"
    decode_base64_lines(INPUT_FILE, OUTPUT_FOLDER)

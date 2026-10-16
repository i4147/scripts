import subprocess
import sys
from pathlib import Path


def pdf_to_text_by_page(pdf_path: Path) -> None:
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        print(f"Error: Invalid PDF file path provided: {pdf_path}")
        return
    try:
        subprocess.run(["pdftotext", "-v"], capture_output=True, check=True)
        print("pdftotext found.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: 'pdftotext' command not found.")
        print("Please install 'poppler-utils' (Linux/macOS) or download poppler for Windows.")
        print("On Debian/Ubuntu: sudo apt-get install poppler-utils")
        print("On macOS (using Homebrew): brew install poppler")
        print("For Windows, search for 'poppler for windows' and add pdftotext.exe to your PATH.")
        return
    pdf_filename_base = pdf_path.stem
    output_folder = pdf_path.parent / pdf_filename_base
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"Saving page text files to: {output_folder}")
    except OSError as e:
        print(f"Error creating output directory {output_folder}: {e}")
        return
    num_pages = 0
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path)],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        page_breaks = result.stdout.count("\f")
        num_pages = page_breaks + 1
    except subprocess.CalledProcessError as e:
        print(f"Error determining page count for {pdf_path.name}: {e}")
        print(f"Stderr: {e.stderr}")
        return
    except Exception as e:
        print(f"An unexpected error occurred while processing page count: {e}")
        return
    print(f"Processing PDF: {pdf_path.name} ({num_pages} pages)")
    for page_num in range(num_pages):
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", "-f", str(page_num + 1), "-l", str(page_num + 1), str(pdf_path)],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            text = result.stdout
            page_filename = f"{pdf_filename_base}_page_{page_num + 1}.txt"
            output_filepath = output_folder / page_filename
            with output_filepath.open("w", encoding="utf-8") as txt_file:
                txt_file.write(text)
        except subprocess.CalledProcessError as e:
            print(f"Error extracting text for page {page_num + 1}: {e}")
            print(f"Stderr: {e.stderr}")
            continue
        except OSError as e:
            print(f"Error writing text file for page {page_num + 1}: {e}")
            continue
        except Exception as e:
            print(f"An unexpected error occurred processing page {page_num + 1}: {e}")
            continue
    print("PDF to text conversion complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <path_to_pdf_file>")
        sys.exit(1)
    pdf_file_path_str = sys.argv[1]
    pdf_file_path = Path(pdf_file_path_str)
    pdf_to_text_by_page(pdf_file_path)

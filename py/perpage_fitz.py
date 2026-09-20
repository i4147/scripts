import sys
from pathlib import Path
import fitz


def pdf_to_text_by_page(pdf_path: Path) -> None:
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        print(f"Error: Invalid PDF file path provided: {pdf_path}")
        return
    pdf_filename_base = pdf_path.stem
    output_folder = pdf_path.parent / pdf_filename_base
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"Saving page text files to: {output_folder}")
    except OSError as e:
        print(f"Error creating output directory {output_folder}: {e}")
        return
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error opening PDF file {pdf_path}: {e}")
        return
    num_pages = doc.page_count
    print(f"Processing PDF: {pdf_path.name} ({num_pages} pages)")
    for page_num in range(num_pages):
        try:
            page = doc.load_page(page_num)
            text = page.get_text()
            page_filename = f"{pdf_filename_base}_page_{page_num + 1}.txt"
            output_filepath = output_folder / page_filename
            with output_filepath.open("w", encoding="utf-8") as txt_file:
                txt_file.write(text)
        except Exception as e:
            print(f"Error processing page {page_num + 1}: {e}")
    doc.close()
    print("PDF to text conversion complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <path_to_pdf_file>")
        sys.exit(1)
    pdf_file_path_str = sys.argv[1]
    pdf_file_path = Path(pdf_file_path_str)
    pdf_to_text_by_page(pdf_file_path)

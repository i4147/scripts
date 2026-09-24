from __future__ import annotations

import sys
from pathlib import Path

from joblib import Parallel, delayed
from pypdf import PdfReader


def extract_pages_from_pdf(pdf_path, n_jobs=4):
    pdf_path = Path(pdf_path)
    output_dir = pdf_path.parent / pdf_path.stem
    output_dir.mkdir(exist_ok=True)
    reader = PdfReader(pdf_path)

    def extract_page(page_num):
        if page_num % 10 == 0:
            print(f"processing page {page_num}")
        try:
            page = reader.pages[page_num - 1]
            text = page.extract_text()
            page_file = output_dir / f"page_{page_num:03d}.txt"
            page_file.write_text(text, encoding="utf-8")
            return page_num, page_file
        except Exception as e:
            print(f"Error extracting page {page_num}: {e}", file=sys.stderr)
            return None

    results = Parallel(n_jobs=n_jobs, backend="threading")(
        delayed(extract_page)(i) for i in range(1, len(reader.pages) + 1)
    )
    return [r for r in results if r is not None]


def collect_pdf_files(inputs):
    pdf_files = []
    if not inputs:
        inputs = [Path(".")]
    for item in inputs:
        path = Path(item)
        if path.is_file() and path.suffix.lower() == ".pdf":
            pdf_files.append(path)
        elif path.is_dir():
            pdf_files.extend(path.rglob("*.pdf"))
        else:
            print(f"Warning: {path} is not a valid PDF file or directory", file=sys.stderr)
    return pdf_files


def main():
    inputs = sys.argv[1:] if len(sys.argv) > 1 else []
    pdf_files = collect_pdf_files(inputs)
    if not pdf_files:
        print("No PDF files found.", file=sys.stderr)
        return
    print(f"Found {len(pdf_files)} PDF file(s) to process.")
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"Processing file {i}/{len(pdf_files)}: {pdf_file.name}")
        try:
            results = extract_pages_from_pdf(pdf_file, n_jobs=8)
            print(f"  Extracted {len(results)} pages from {pdf_file.name}")
        except Exception as e:
            print(f"Failed to process {pdf_file}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

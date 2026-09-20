from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path

import pdfminer


for logger_name in [
    "pdfminer",
    "pdfminer.pdfinterp",
    "pdfminer.pdfpage",
    "pdfminer.pdfparser",
    "pdfminer.pdfdocument",
    "pdfminer.converter",
]:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)


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


def extract_single_page(page_num, page, output_dir):
    if page_num % 10 == 0:
        print(f"processing ... page {page_num}")
    try:
        output_string = StringIO()
        rsrcmgr = pdfminer.pdfinterp.PDFResourceManager()

        laparams = pdfminer.layout.LAParams()

        device = pdfminer.converter.TextConverter(rsrcmgr, output_string, laparams=laparams)
        interpreter = pdfminer.pdfinterp.PDFPageInterpreter(rsrcmgr, device)
        interpreter.process_page(page)
        text = output_string.getvalue()
        device.close()
        output_string.close()

        page_file = output_dir / f"page_{page_num:03d}.txt"
        page_file.write_text(text, encoding="utf-8")
        return page_num, page_file
    except Exception as e:
        print(f"Error extracting page {page_num}: {e}", file=sys.stderr)
        return None


def extract_pages_from_pdf(pdf_path):
    pdf_path = Path(pdf_path)
    output_dir = pdf_path.parent / pdf_path.stem
    output_dir.mkdir(exist_ok=True)
    results = []
    try:
        with open(pdf_path, "rb") as file:
            parser = pdfminer.pdfparser.PDFParser(file)
            document = pdfminer.pdfdocument.PDFDocument(parser)
            if not document.is_extractable:
                print(f"Warning: {pdf_path} is not extractable", file=sys.stderr)
                return results

            for page_num, page in enumerate(pdfminer.pdfpage.PDFPage.create_pages(document), start=1):
                result = extract_single_page(page_num, page, output_dir)
                if result is not None:
                    results.append(result)

    except Exception as e:
        print(f"Error processing {pdf_path}: {e}", file=sys.stderr)
    return results


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
            results = extract_pages_from_pdf(pdf_file)
            print(f"  Extracted {len(results)} pages from {pdf_file.name}")
        except Exception as e:
            print(f"Failed to process {pdf_file}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

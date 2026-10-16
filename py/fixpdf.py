import pathlib
import sys

import pdfminer
from pypdf import PdfReader, PdfWriter

fn = sys.argv[1]
reader = PdfReader(fn, strict=False)
writer = PdfWriter()
for page in reader.pages:
    text = pdfminer.high_level.extract_text(page)
    print(text)
    writer.add_page(page)
with pathlib.Path(fn).open("wb") as f:
    writer.write(f)

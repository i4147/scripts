import os
from multiprocessing import Pool
from pathlib import Path

import pdfplumber
from termcolor import cprint


def process_file(fp) -> None:
    i = 1
    with pdfplumber.open(fp) as pdf:
        numpages = len(pdf.pages)
        strn = len(str(numpages))
        Path(fp).stem.replace(str(numpages), "")
        if not Path(outdir).exists():
            Path(outdir).mkdir()
        for page in pdf.pages:
            stri = str(i)
            while len(stri) < strn:
                stri = "0" + stri
            txtfile = f"{outdir}/{stri}.txt"
            if Path(txtfile).exists():
                print(f"{Path(txtfile).name} exists")
                i += 1
                continue
            text = page.extract_text(encoding="utf-8")
            if text:
                Path(txtfile).write_text(text, encoding="utf-8")
                cprint(f"{txtfile} created", "cyan")
            else:
                Path(txtfile).write_text("empty page", encoding="utf-8")
                cprint(f"page {i} is empty", "blue")
            i += 1
    del i
    del text
    del pages


def main() -> None:
    files = [file for file in os.listdir(".") if file.endswith(".pdf")]
    if len(files) == 0:
        print("no pdf file found.")
        return
    pool = Pool(4)
    for f in files:
        _ = pool.apply_async(process_file, ((f),))
    pool.close()
    pool.join()
    del pool
    del files
    return


if __name__ == "__main__":
    main()

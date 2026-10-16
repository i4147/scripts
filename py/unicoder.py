import pathlib
import re
from sys import exit
from time import perf_counter

import regex
from dh import hex2dec

pattern = regex.compile(r"\p{Script=Arabic}|\p{Script=Devanagari}|\p{Script=Bengali}")
pat = re.compile(
    r"["
    r"\u0600-\u06FF"
    r"\u0750-\u077F"
    r"\u08A0-\u08FF"
    r"\uFB50-\uFDFF"
    r"\uFE70-\uFEFF"
    r"\u0900-\u0D7F"
    r"]+"
)


def process_text(txt: str) -> None:
    text = txt.strip()
    ln = len(text)
    cleaned = ""
    for i in range(ln):
        k = ord(text[i])
        if k >= hex2dec("f900") and k <= hex2dec("faff"):
            continue
        if k >= hex2dec("2f80") and k <= hex2dec("2fa1f"):
            continue
        if k >= hex2dec("4e00") and k <= hex2dec("9fff"):
            continue
        if k >= hex2dec("3400") and k <= hex2dec("4dbf"):
            continue
        if k >= hex2dec("20000") and k <= hex2dec("2a6df"):
            continue
        if k >= hex2dec("2a700") and k <= hex2dec("2b73f"):
            continue
        if k >= hex2dec("2b740") and k <= hex2dec("2b81f"):
            continue
        if k >= hex2dec("2b820") and k <= hex2dec("2ceaf"):
            continue
        if k >= hex2dec("2ceb0") and k <= hex2dec("2ebef"):
            continue
        if k >= hex2dec("30000") and k <= hex2dec("3134f"):
            continue
        if k >= hex2dec("31350") and k <= hex2dec("323af"):
            continue
        if k >= hex2dec("3040") and k <= hex2dec("309f"):
            continue
        if k >= hex2dec("30a0") and k <= hex2dec("30ff"):
            continue
        if k >= hex2dec("ac00") and k <= hex2dec("d7af"):
            continue
        if k >= hex2dec("1100") and k <= hex2dec("11ff"):
            continue
        if k >= hex2dec("3130") and k <= hex2dec("318f"):
            continue
        cleaned += text[i]
    cleaned = pattern.sub("", cleaned)
    cleaned = pat.sub("", cleaned)
    pathlib.Path("/sdcard/emoji2").write_text(cleaned, encoding="utf-8")


def main() -> None:
    start = perf_counter()
    with pathlib.Path("/sdcard/emoji").open(encoding="utf-8", errors="ignore") as f:
        data = f.read()
        process_text(data)
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())

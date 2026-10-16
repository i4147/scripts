from __future__ import annotations
import base64
import json
import re
import sys
from pathlib import Path


def extract_embedded_html(text: str) -> str | None:
    m = re.search(r"__SINGLEFILE(?:_Z)?__\s*=\s*(\{.*?\})\s*;?", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            for key in ("content", "html", "data"):
                if key in obj:
                    val = obj[key]
                    if isinstance(val, str):
                        try:
                            return base64.b64decode(val).decode("utf-8", errors="replace")
                        except Exception:
                            return val
        except Exception:
            pass
    m = re.search(r"data:text/html;charset=[^;]+;base64,([A-Za-z0-9+/=\s]+)", text, re.DOTALL)
    if not m:
        m = re.search(r"data:text/html;base64,([A-Za-z0-9+/=\s]+)", text, re.DOTALL)
    if m:
        b64 = re.sub(r"\s+", "", m.group(1))
        return base64.b64decode(b64).decode("utf-8", errors="replace")
    m = re.search(r'(?:const|let|var)\s+content\s*=\s*"((?:\.|[^"])*)"', text, re.DOTALL)
    if m:
        try:
            return bytes(m.group(1), "utf-8").decode("unicode_escape")
        except Exception:
            pass
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <singlefilez-file>")
        sys.exit(1)
    in_path = Path(sys.argv[1])
    if not in_path.exists():
        print(f"Error: file not found: {in_path}")
        sys.exit(1)
    raw = in_path.read_text(encoding="utf-8", errors="replace")
    html = extract_embedded_html(raw)
    if html is None:
        print("Error: could not find embedded HTML payload")
        sys.exit(2)
    out_path = in_path.with_suffix(".html")
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()

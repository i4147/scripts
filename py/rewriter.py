import sys
from ast import parse
from pathlib import Path

from astunparse import unparse
from dh import is_binary


def main():
    fn = Path(sys.argv[1])
    if is_binary(fn):
        print(f"{fn.name} is binary")
        sys.exit(0)
    if fn.suffix == ".py":
        try:
            code = fn.read_text(encoding="utf-8", errors="ignore")
            tree = parse(code)
            newcode = unparse(tree)
            print(newcode)
            fn.write_text(newcode, encoding="utf-8")
            print("ᜅ done.")
            sys.exit(0)
        except:
            print(f"syntax error in {fn.name}")
            sys.exit(0)
    else:
        content = fn.read_text(encoding="utf-8", errors="ignore")
        content = unicodedata.normalize("NFKD", content)
        fn.write_text(content, encoding="utf-8")
        sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())

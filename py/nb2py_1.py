import json
import sys
from pathlib import Path

if __name__ == "__main__":
    fn = Path(sys.argv[1].strip())
    py_file = fn.with_suffix(".py")
    with fn.open(encoding="utf-8") as data_file:
        ipynb = json.load(data_file)

    code = ""
    for c in ipynb["cells"]:
        if c["cell_type"] == "code":
            source = c["source"]
            for s in source:
                if s[0] != "%" and s[0] != "!":
                    code += s.rstrip("\n") + "\n"
    py_file.write_text(code, encoding="utf-8")

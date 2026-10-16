import pickle as pkl
from pathlib import Path

if __name__ == "__main__":
    import sys

    fn = Path(sys.argv[1].strip())
    with fn.open("rb") as f:
        data = pkl.load(f)
    outf = fn.with_suffix(".raw")
    outf.write_bytes(data)
    print(data)

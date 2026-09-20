import sys

if __name__ == "__main__":
    fn = sys.argv[1]
    nl = []
    with open(fn, encoding="utf8") as f:
        lines = f.readlines()
        for line in lines:
            if "." in line:
                indx = line.index(".")
                cleaned = line[:indx]
                nl.append(cleaned)
            else:
                nl.append(line)
    with open(fn, "w", encoding="utf8") as fo:
        fo.writelines(f"{k}\n" for k in nl)

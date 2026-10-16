import sys

nl = []

fn = sys.argv[1]
with open(fn) as f:
    for line in f:
        if not "." in line:
            nl.append(line)
        else:
            print(line)
with open(fn, "w") as fo:
    for k in nl:
        fo.write(k)

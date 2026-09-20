from dh import is_alpha, is_alphanum, is_digit, is_lower, is_upper

alpha = []
alphanum = []
upper = []
lower = []
dg = []
rest = []
sp = []
space = []
with open("word") as f:
    for line in f:
        striped = line.strip()
        if len(striped) < 4:
            continue
        if is_digit(striped):
            dg.append(line)
            continue
        if is_upper(striped):
            upper.append(line)
            continue
        if is_lower(striped):
            lower.append(line)
            continue
        if is_alpha(striped):
            alpha.append(line)
            continue
        if is_alphanum(striped):
            if not "kommen" in striped:
                alphanum.append(line)
            continue
        if striped.endswith("]"):
            sp.append(line)
            continue
        if " " in striped:
            space.append(line)
            continue
        if len(striped) < 6:
            continue
        else:
            rest.append(line)
with open("digits.txt", "w") as f:
    for k in dg:
        f.write(k)
with open("alphanum.txt", "w") as fan:
    for k in alphanum:
        fan.write(k)
with open("alpha.txt", "w") as fa:
    for c in alpha:
        fa.write(c)
with open("lower.txt", "w") as fl:
    for m in lower:
        fl.write(m)
with open("upper.txt", "w") as fu:
    for n in upper:
        fu.write(n)
with open("sp.txt", "w") as f:
    for x in sp:
        f.write(x)
with open("space.txt", "w") as f:
    for x in space:
        f.write(x)

with open("w2.txt", "w") as fo:
    for x in rest:
        fo.write(x)

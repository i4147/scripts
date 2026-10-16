from pathlib import Path
from pprint import pprint

import stringzilla as sz
from dh import is_binary
from fastwalk import walk_files


def find_similar_files(files, threshold=0.8, k=256):
    similar_groups = []
    sketches = {}
    for file in files:
        content = Path(file).read_bytes()
        sketches[file] = sz.minhash(content, k)
    for i, (file_a, sketch_a) in enumerate(sketches.items()):
        group = [file_a]
        for file_b, sketch_b in list(sketches.items())[i + 1 :]:
            similarity = sz.jaccard(sketch_a, sketch_b)
            if similarity >= threshold:
                group.append(file_b)
                del sketches[file_b]
        if len(group) > 1:
            similar_groups.append(group)
    return similar_groups


if __name__ == "__main__":
    fz = []
    root_dir = Path.cwd()
    for pth in walk_files(root_dir):
        path = Path(pth)
        if path.is_file() and not is_binary(path):
            fz.append(path)
    simg = find_similar_files(fz)
    for grp in simg:
        pprint(grp)

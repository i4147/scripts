import random
import string

from pbar import Pbar
from rapidfuzz import fuzz

words = ["".join(random.choice(string.ascii_letters + string.digits) for _ in range(10)) for _ in range(10_000)]
samples = words[:: len(words) // 100]
scorer = fuzz.ratio
with Pbar("processing") as pbar:
    for sample in pbar.wrap(samples):
        for word in words:
            ratio = scorer(sample, word)
            if ratio > 97:
                print(f"{word} >> {sample}")

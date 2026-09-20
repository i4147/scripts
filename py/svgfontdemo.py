import matplotlib.pyplot as plt
import svgfont
from matplotlib import patches

w, h = 200, 100
font = svgfont.load_font("HersheyScript1")
paths = svgfont.text_paths("Hello World", font, box=svgfont.rect(0, 0, w, h), padding=10)
plt.figure(figsize=(6, 3))
for P in paths:
    plt.plot(P[:, 0], P[:, 1], "k")
plt.gca().add_patch(patches.Rectangle((0, 0), w, h, fill=False, edgecolor="r"))
plt.axis("equal")
plt.gca().invert_yaxis()
plt.savefig("demo.png")

import os

import arabic_reshaper
import matplotlib.pyplot as plt
from bidi.algorithm import get_display

current_dir = os.getcwd()
subdir_sizes = {}
total_size = 0
for dirpath, dirnames, filenames in os.walk(current_dir):
    dir_size = 0
    for f in filenames:
        fp = os.path.join(dirpath, f)
        try:
            dir_size += os.path.getsize(fp)
        except OSError:
            pass
    if dirpath != current_dir:
        subdir_sizes[dirpath] = dir_size
        total_size += dir_size
    else:
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                pass
for subdir, size in subdir_sizes.items():
    if total_size > 0:
        percentage = (size / total_size) * 100
        subdir_percentages[os.path.basename(subdir)] = percentage
    else:
        subdir_percentages[os.path.basename(subdir)] = 0
labels = list(subdir_percentages.keys())
sizes = list(subdir_percentages.values())
reshaped_labels = []
for label in labels:
    reshaped_label = arabic_reshaper.reshape(label)
    bidi_label = get_display(reshaped_label)
    reshaped_labels.append(bidi_label)
fig, ax = plt.subplots(figsize=(10, 10))
ax.pie(sizes, labels=reshaped_labels, autopct="%1.1f%%", startangle=140)
ax.axis("equal")
title = "حجم دایرکتوری‌های زیرمجموعه"
reshaped_title = arabic_reshaper.reshape(title)
bidi_title = get_display(reshaped_title)
plt.title(bidi_title)
output_filename = "directory_tree_size.png"
plt.savefig(output_filename, bbox_inches="tight")
print(f"نمودار دایره‌ای با نام '{output_filename}' ذخیره شد.")
print(f"مجموع حجم دایرکتوری‌های زیرمجموعه: {total_size} بایت")

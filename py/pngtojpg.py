from __future__ import annotations

from pathlib import Path

from PIL import Image

for png_path in Path(".").rglob("*.png"):
    if png_path.is_file():
        jpg_path = png_path.with_suffix(".jpg")
        try:
            img = Image.open(png_path).convert("RGB")
            img.save(jpg_path, "JPEG")
            png_path.unlink()
            print(f"Converted and deleted: {png_path} -> {jpg_path}")
        except Exception as e:
            print(f"Failed to convert {png_path}: {e}")



- refactor above code with following changes
- use cv2 as main converion library, then fallback to pillow
- use pathlib
- use mp.pool.imap_unordered with 8 workers (no --workers or --jobs cli args)
- the script should accept multiple files/dirs as input
  (if no input is provided, the script should process files in current dir recursively)
- python version=3.12
- consider following factors in implementation:
    Speed / performance
    Code clarity / maintainability
    Memory efficiency
    Production-ready robustness
    Feature set (streaming, adaptive, edge cases)
- output filename = fname.with_suffix('.png')
- remove orig, if successfull
- return fully annotated code with main guard
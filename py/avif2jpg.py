from __future__ import annotations

from pathlib import Path

from PIL import Image

input_dir = Path("avif_images")
output_dir = Path("jpg_images")
output_dir.mkdir(exist_ok=True, parents=True)
if input_dir.exists() and input_dir.is_dir():
    for file in input_dir.iterdir():
        if file.is_file() and file.suffix.lower() in (".avif", ".aviff"):
            output_path = output_dir / (file.stem + ".jpg")
            with Image.open(file) as img:
                img = img.convert("RGB")
                img.save(output_path, "JPEG", quality=95)




- use pathlib
- use mp.pool.starmap with 8 workers (no --workers or --jobs cli args)
- the script should accept multiple files/dirs as input
  (if no input is provided, the script should process files in current dir recursively)
- python version=3.12
- consider following factors in implementation:
    Speed / performance
    Code clarity / maintainability
    Memory efficiency
    Production-ready robustness
    Feature set (streaming, adaptive, edge cases)
- add main guard, if missing
- output filename = fname.with_suffix(".jpg")
- return fully annotated code

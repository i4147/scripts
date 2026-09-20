import glob
from functools import partial
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pngquant

QUALITY_RANGE_STR = "60-70"
START_DIR = Path()
NUM_PROCESSES = cpu_count()
print(f"Using {NUM_PROCESSES} CPU cores for parallel processing.")


def compress_single_file(input_path: str, quality_range: str) -> None:
    input_path_obj = Path(input_path)
    output_path = input_path
    if "-fs8.png" in input_path_obj.name or "-or8.png" in input_path_obj.name:
        return
    try:
        pngquant.quant_image(
            image=input_path,
            dst=output_path,
            quality=quality_range,
            override=True,
            delete=True,
        )
        print(f"✅ Optimized: {input_path} (Quality: {quality_range})")
    except Exception as e:
        if "unexpected keyword argument 'quality'" in str(e):
            print(
                f"❌ Error compressing {input_path}: API does not accept 'quality' string either. Please check your specific library documentation."
            )
        else:
            print(f"❌ Error compressing {input_path}: {e}")


if __name__ == "__main__":
    all_png_files = glob.glob(
        str(START_DIR / "**" / "*.png"),
        recursive=True,
    )
    if not all_png_files:
        print(f"No PNG files found recursively in {START_DIR}.")
    else:
        print(f"Found {len(all_png_files)} PNG files to process...")
        compress_task = partial(
            compress_single_file,
            quality_range=QUALITY_RANGE_STR,
        )
        try:
            with Pool(NUM_PROCESSES) as pool:
                pool.map(compress_task, all_png_files)
            print("\n✨ All PNG files processed successfully. ✨")
        except Exception as e:
            print(f"\nAn unexpected error occurred during multiprocessing: {e}")

from __future__ import annotations

import argparse
import logging
import multiprocessing
import re
import zipfile
from concurrent.futures import TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fontTools.ttLib import TTFont

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class FontInfo:
    family_name: str
    style_name: str
    weight: int
    is_italic: bool
    extension: str
    original_path: Path


class APKFontExtractor:
    FONT_EXTENSIONS: set[str] = {".ttf", ".otf", ".woff", ".woff2", ".ttc", ".eot"}
    FONT_DIRS: set[str] = {"font", "fonts", "assets/fonts", "res/font", "assets"}

    def __init__(self, output_dir: Path = Path("fonts"), workers: int = 8):
        self.output_dir = Path(output_dir)
        self.workers = workers
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.processed_fonts: dict[str, Path] = {}
        logger.info(f"Initialized with output_dir={self.output_dir}, workers={self.workers}")

    def _find_apk_files(self, paths: list[Path]) -> list[Path]:
        apk_files: list[Path] = []
        for path in paths:
            if path.is_file() and path.suffix.lower() == ".apk":
                apk_files.append(path)
                logger.debug(f"Found APK file: {path}")
            elif path.is_dir():
                for apk_path in path.rglob("*.apk"):
                    apk_files.append(apk_path)
                    logger.debug(f"Found APK file: {apk_path}")
        logger.info(f"Found {len(apk_files)} APK file(s) to process")
        return apk_files

    def _extract_font_from_apk(self, apk_path: Path) -> list[tuple[Path, bytes, str]]:
        fonts: list[tuple[Path, bytes, str]] = []
        try:
            with zipfile.ZipFile(apk_path, "r") as zip_ref:
                for file_info in zip_ref.filelist:
                    file_path = Path(file_info.filename)
                    is_font_dir = any(font_dir in str(file_path.parent).lower() for font_dir in self.FONT_DIRS)
                    has_font_ext = file_path.suffix.lower() in self.FONT_EXTENSIONS
                    if is_font_dir or has_font_ext:
                        try:
                            font_data = zip_ref.read(file_info.filename)
                            fonts.append((file_path, font_data, file_path.suffix))
                            logger.debug(f"Extracted font: {file_path} from {apk_path.name}")
                        except Exception as e:
                            logger.warning(f"Failed to extract {file_path} from {apk_path.name}: {e}")
                            continue
        except zipfile.BadZipFile:
            logger.error(f"Invalid APK file: {apk_path}")
        except Exception as e:
            logger.error(f"Error processing {apk_path}: {e}")
        return fonts

    def _get_font_metadata(self, font_data: bytes) -> FontInfo | None:
        try:
            font = TTFont(io=None, fontData=font_data)
            family_name = "Unknown"
            style_name = "Regular"
            weight = 400
            is_italic = False
            if "name" in font:
                name_table = font["name"]
                family_record = name_table.getBestFamilyName()
                if family_record:
                    family_name = family_record
                style_record = name_table.getName(2, 3, 1, 1033)
                if style_record:
                    style_name = style_record.toStr()
                is_italic = "italic" in style_name.lower()
                if "OS/2" in font:
                    weight = font["OS/2"].usWeightClass
                else:
                    weight_lower = style_name.lower()
                    if "thin" in weight_lower:
                        weight = 100
                    elif "extralight" in weight_lower or "ultralight" in weight_lower:
                        weight = 200
                    elif "light" in weight_lower:
                        weight = 300
                    elif "medium" in weight_lower:
                        weight = 500
                    elif "semibold" in weight_lower or "demibold" in weight_lower:
                        weight = 600
                    elif "bold" in weight_lower:
                        weight = 700
                    elif "extrabold" in weight_lower or "ultrabold" in weight_lower:
                        weight = 800
                    elif "black" in weight_lower or "heavy" in weight_lower:
                        weight = 900
            font.close()
            if font_data[:4] == b"OTTO":
                extension = ".otf"
            elif font_data[:4] == b"wOFF":
                extension = ".woff"
            elif font_data[:4] == b"wOF2":
                extension = ".woff2"
            else:
                extension = ".ttf"
            return FontInfo(
                family_name=family_name,
                style_name=style_name,
                weight=weight,
                is_italic=is_italic,
                extension=extension,
                original_path=Path(""),
            )
        except Exception as e:
            logger.warning(f"Failed to extract font metadata: {e}")
            return None

    def _generate_font_filename(self, font_info: FontInfo, original_path: Path) -> str:
        family_name = re.sub(r"[^\w\s-]", "", font_info.family_name)
        family_name = re.sub(r"\s+", "-", family_name.strip())
        style_str = font_info.style_name
        style_str = re.sub(r"[^\w\s-]", "", style_str)
        style_str = re.sub(r"\s+", "-", style_str.strip())
        if style_str.lower() in ("regular", "normal", "medium", ""):
            if font_info.weight <= 300:
                style_str = "Light"
            elif font_info.weight >= 700:
                style_str = "Bold"
            else:
                style_str = "Regular"
        if font_info.is_italic and "italic" not in style_str.lower():
            style_str = f"{style_str}-Italic"
        filename = f"{family_name}-{style_str}{font_info.extension}"
        return filename

    def _handle_duplicate_filename(self, filename: str, source_apk: Path) -> str:
        base_name = Path(filename).stem
        extension = Path(filename).suffix
        counter = 1
        while True:
            if counter == 1:
                new_filename = filename
            else:
                new_filename = f"{base_name}-{counter}{extension}"
            output_path = self.output_dir / new_filename
            if output_path.exists():
                if self._is_same_font(output_path, source_apk):
                    logger.info(f"Font already exists: {new_filename}")
                    return new_filename
                counter += 1
            else:
                return new_filename

    def _is_same_font(self, existing_path: Path, source_apk: Path) -> bool:
        try:
            existing_size = existing_path.stat().st_size
            key = f"{source_apk.name}-{existing_size}"
            return key in self.processed_fonts
        except Exception:
            return False

    def _save_font(self, font_data: bytes, filename: str, source_apk: Path) -> Path | None:
        final_filename = self._handle_duplicate_filename(filename, source_apk)
        output_path = self.output_dir / final_filename
        try:
            output_path.write_bytes(font_data)
            logger.info(f"Saved font: {final_filename}")
            self.processed_fonts[f"{source_apk.name}-{len(font_data)}"] = output_path
            return output_path
        except Exception as e:
            logger.error(f"Failed to save font {final_filename}: {e}")
            return None

    def _process_apk(self, apk_path: Path) -> int:
        logger.info(f"Processing APK: {apk_path.name}")
        fonts = self._extract_font_from_apk(apk_path)
        extracted_count = 0
        for original_path, font_data, extension in fonts:
            font_info = self._get_font_metadata(font_data)
            if font_info:
                font_info.original_path = original_path
                font_info.extension = extension
                filename = self._generate_font_filename(font_info, original_path)
                output_path = self._save_font(font_data, filename, apk_path)
                if output_path:
                    extracted_count += 1
            else:
                fallback_filename = original_path.name
                output_path = self._save_font(font_data, fallback_filename, apk_path)
                if output_path:
                    extracted_count += 1
        logger.info(f"Extracted {extracted_count} font(s) from {apk_path.name}")
        return extracted_count

    def process(self, input_paths: list[Path] | None = None) -> int:
        if input_paths is None:
            input_paths = [Path.cwd()]
        else:
            input_paths = [Path(p) for p in input_paths]
        apk_files = self._find_apk_files(input_paths)
        if not apk_files:
            logger.warning("No APK files found to process")
            return 0
        total_extracted = 0
        try:
            with multiprocessing.Pool(processes=self.workers) as pool:
                async_results = []
                for apk_path in apk_files:
                    result = pool.apply_async(self._process_apk, (apk_path,))
                    async_results.append((apk_path, result))
                for apk_path, async_result in async_results:
                    try:
                        count = async_result.get(timeout=600)
                        total_extracted += count
                    except TimeoutError:
                        logger.error(f"Timeout processing {apk_path.name}")
                    except Exception as e:
                        logger.error(f"Error processing {apk_path.name}: {e}")
        except Exception as e:
            logger.error(f"Error in parallel processing: {e}")
        logger.info(f"Total fonts extracted: {total_extracted}")
        return total_extracted


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract fonts from APK files with parallel processing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all APKs in current directory recursively
  %(prog)s
  # Process specific APK files
  %(prog)s app1.apk app2.apk
  # Process APKs in specific directories
  %(prog)s /path/to/apks /another/path
  # Specify custom output directory
  %(prog)s -o custom_fonts /path/to/apks
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Input APK files or directories (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("fonts"),
        help="Output directory for extracted fonts (default: fonts)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=8,
        choices=range(1, 17),
        metavar="N",
        help="Number of parallel workers (default: 8)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot create output directory {args.output}: {e}")
        return 1
    extractor = APKFontExtractor(output_dir=args.output, workers=args.workers)
    try:
        total_fonts = extractor.process(input_paths=args.inputs if args.inputs else None)
        if total_fonts > 0:
            logger.info(f"✓ Successfully extracted {total_fonts} font(s)")
            return 0
        else:
            logger.warning("No fonts were extracted")
            return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

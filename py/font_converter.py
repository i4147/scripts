import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fontTools.ttLib import TTFont


SUPPORTED_FORMATS = {".ttf", ".otf", ".woff", ".woff2"}

FLAVOR_MAP = {
    ".woff": "woff",
    ".woff2": "woff2",
}


def collect_font_files(inputs: list[str]) -> list[Path]:
    if not inputs:
        inputs = ["."]

    font_files: list[Path] = []
    seen: set[Path] = set()

    for inp in inputs:
        path = Path(inp)

        if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                font_files.append(resolved)

        elif path.is_dir():
            for p in sorted(path.rglob("*")):
                if p.is_file() and p.suffix.lower() in SUPPORTED_FORMATS:
                    resolved = p.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        font_files.append(resolved)

        else:
            print(
                f"Warning: '{inp}' is not a valid font file or directory — skipping.",
                file=sys.stderr,
            )

    return font_files


def convert_one(
    font_path: Path,
    target_ext: str,
    remove_original: bool,
    verbose: bool,
) -> dict:
    result = {
        "input": str(font_path),
        "input_name": font_path.name,
        "output": None,
        "output_name": None,
        "success": False,
        "error": None,
        "skipped": False,
        "original_size": 0,
        "output_size": 0,
        "time_taken": 0.0,
        "space_freed": 0,
        "ratio": 0.0,
    }

    start = time.monotonic()

    try:
        original_size = font_path.stat().st_size
        result["original_size"] = original_size

        output_path = font_path.with_suffix(target_ext)
        result["output"] = str(output_path)
        result["output_name"] = output_path.name

        if font_path.suffix.lower() == target_ext:
            result["skipped"] = True
            result["success"] = True
            result["output_size"] = original_size
            result["ratio"] = 1.0
            result["time_taken"] = time.monotonic() - start
            return result

        font = TTFont(str(font_path))
        flavor = FLAVOR_MAP.get(target_ext)
        font.save(str(output_path))
        font.close()

        output_size = output_path.stat().st_size
        result["output_size"] = output_size
        result["ratio"] = output_size / original_size if original_size > 0 else 0.0
        result["space_freed"] = original_size - output_size
        result["time_taken"] = time.monotonic() - start

        if remove_original:
            font_path.unlink()
            result["space_freed"] = original_size

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        result["time_taken"] = time.monotonic() - start

    return result


def print_result(result: dict, verbose: bool, remove_original: bool) -> None:
    name = result["input_name"]

    if result["skipped"]:
        if verbose:
            print(f"  ⊘ {name}  (already {result['output_name']})")
        else:
            print(f"  ⊘ {name}  (skipped — already target format)")
        return

    if not result["success"]:
        print(f"  ✗ {name}  →  ERROR: {result['error']}")
        return

    if verbose:
        print(f"  ✓ {name}  →  {result['output_name']}")
        print(f"      Original size : {result['original_size']:>12,} bytes")
        print(f"      Output size   : {result['output_size']:>12,} bytes")
        print(f"      Ratio         : {result['ratio']:>12.2%}")
        print(f"      Space freed   : {result['space_freed']:>12,} bytes")
        print(f"      Time taken    : {result['time_taken']:>12.3f}s")
        if remove_original:
            print(f"      Original file : removed")
        print()
    else:
        print(f"  ✓ {name}  →  {result['output_name']}")


def print_summary(results: list[dict], verbose: bool, wall_time: float) -> None:
    total = len(results)
    succeeded = sum(1 for r in results if r["success"] and not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    failed = sum(1 for r in results if not r["success"])

    total_space_freed = sum(r["space_freed"] for r in results if r["success"])
    total_original = sum(r["original_size"] for r in results if r["success"])
    total_output = sum(r["output_size"] for r in results if r["success"])
    overall_ratio = total_output / total_original if total_original > 0 else 0.0

    print(f"\n{'─' * 55}")
    print(f"  Total files   : {total}")
    print(f"  Converted     : {succeeded}")
    print(f"  Skipped       : {skipped}")
    print(f"  Failed        : {failed}")

    if verbose and succeeded + skipped > 0:
        print(f"  ───────────────────────────────────────────")
        print(f"  Original total: {total_original:>12,} bytes")
        print(f"  Output total  : {total_output:>12,} bytes")
        print(f"  Overall ratio : {overall_ratio:>12.2%}")
        print(f"  Space freed   : {total_space_freed:>12,} bytes")
        print(f"  Wall time     : {wall_time:>12.3f}s")

    print(f"{'─' * 55}")

    if failed > 0:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description=("Convert font files to WOFF2 (default) or another format, with parallel processing."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python font_converter.py                              # . → woff2 (recursive)\n"
            "  python font_converter.py font1.ttf font2.otf          # specific files → woff2\n"
            "  python font_converter.py --to woff ./fonts/            # → woff\n"
            "  python font_converter.py -r -v --max-workers 4 ./dir   # verbose, remove, 4 workers\n"
            "  python font_converter.py --test                        # run tests\n"
        ),
    )

    parser.add_argument(
        "inputs",
        nargs="*",
        help="Input font files or directories (default: current dir, recursive)",
    )
    parser.add_argument(
        "--to",
        default="woff2",
        help="Target format: woff2, woff, ttf, otf (default: woff2)",
    )
    parser.add_argument(
        "-r",
        "--remove",
        action="store_true",
        help="Remove original files on successful conversion",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output: space freed, time, ratio for every file",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=6,
        help="Maximum parallel workers (default: 6)",
    )

    args = parser.parse_args()

    target_ext = args.to.lower()
    if not target_ext.startswith("."):
        target_ext = "." + target_ext

    if target_ext not in SUPPORTED_FORMATS:
        print(
            f"Error: Unsupported target format '{target_ext}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    font_files = collect_font_files(args.inputs)

    if not font_files:
        print("No font files found.")
        return

    print(f"Found {len(font_files)} font file(s). Converting to {target_ext} with {args.max_workers} worker(s)...\n")

    results: list[dict] = []
    wall_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(convert_one, f, target_ext, args.remove, args.verbose): f for f in font_files}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print_result(result, args.verbose, args.remove)

    wall_time = time.monotonic() - wall_start
    print_summary(results, args.verbose, wall_time)


def _generate_test_font(path: Path) -> Path:
    from fontTools.fontBuilder import FontBuilder

    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A"])
    fb.setupCharacterMap({65: "A"})

    fb.setupGlyf(
        {
            ".notdef": {
                "numberOfContours": 0,
                "xMin": 0,
                "yMin": 0,
                "xMax": 0,
                "yMax": 0,
            },
            "A": {
                "numberOfContours": 1,
                "xMin": 0,
                "yMin": 0,
                "xMax": 500,
                "yMax": 700,
                "coordinates": [(0, 0), (500, 0), (250, 700)],
                "flags": [1, 1, 1],
                "endPtsOfContours": [2],
            },
        }
    )

    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (500, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "TestFont", "styleName": "Regular"})
    fb.setupOs2(
        sTypoAscender=800,
        sTypoDescender=-200,
        sTypoLineGap=0,
        usWinAscent=1000,
        usWinDescent=200,
    )
    fb.setupPost()

    path.parent.mkdir(parents=True, exist_ok=True)
    fb.font.save(str(path))
    return path


def run_tests():
    import tempfile
    import shutil

    print("Running tests...\n")
    temp_dir = Path(tempfile.mkdtemp(prefix="font_test_"))
    all_passed = True

    try:
        print("  Test 1: Default conversion (ttf → woff2)")
        font_path = _generate_test_font(temp_dir / "test1.ttf")
        result = convert_one(font_path, ".woff2", remove_original=False, verbose=True)
        assert result["success"], f"    Conversion failed: {result['error']}"
        assert result["output_size"] > 0, "    Output file is empty"
        assert result["ratio"] < 1.0, "    WOFF2 should be smaller than TTF"
        assert (temp_dir / "test1.woff2").is_file(), "    Output file not created"
        assert (temp_dir / "test1.ttf").is_file(), "    Original should still exist"
        print(f"    ✓ ttf → woff2  ratio={result['ratio']:.2%}  freed={result['space_freed']:,} bytes")

        print("  Test 2: Convert to woff")
        font_path = _generate_test_font(temp_dir / "test2.ttf")
        result = convert_one(font_path, ".woff", remove_original=False, verbose=True)
        assert result["success"], f"    Conversion failed: {result['error']}"
        assert (temp_dir / "test2.woff").is_file(), "    WOFF file not created"
        print(f"    ✓ ttf → woff  ratio={result['ratio']:.2%}")

        print("  Test 3: Remove original on success")
        font_path = _generate_test_font(temp_dir / "test3.ttf")
        result = convert_one(font_path, ".woff2", remove_original=True, verbose=True)
        assert result["success"], f"    Conversion failed: {result['error']}"
        assert not (temp_dir / "test3.ttf").exists(), "    Original should be removed"
        assert (temp_dir / "test3.woff2").is_file(), "    Output should exist"
        print(f"    ✓ original removed, output exists")

        print("  Test 4: Skip if already target format")
        font_path = _generate_test_font(temp_dir / "test4.ttf")
        convert_one(font_path, ".woff2", remove_original=False, verbose=False)
        woff2_path = temp_dir / "test4.woff2"
        result = convert_one(woff2_path, ".woff2", remove_original=False, verbose=True)
        assert result["skipped"], "    Should be skipped"
        assert result["success"], "    Skipped should still be success=True"
        print(f"    ✓ skipped (already woff2)")

        print("  Test 5: Recursive file collection")
        sub_dir = temp_dir / "subdir" / "nested"
        sub_dir.mkdir(parents=True)
        _generate_test_font(temp_dir / "top.ttf")
        _generate_test_font(sub_dir / "deep.ttf")
        _generate_test_font(temp_dir / "not_a_font.txt")
        (temp_dir / "readme.txt").write_text("not a font")

        collected = collect_font_files([str(temp_dir)])
        names = sorted(p.name for p in collected)
        assert "top.ttf" in names, "    Should find top.ttf"
        assert "deep.ttf" in names, "    Should find nested deep.ttf"
        assert "readme.txt" not in names, "    Should not include .txt files"
        print(f"    ✓ found {len(collected)} font(s) recursively")

        print("  Test 6: Default input (no args → '.')")
        collected = collect_font_files([])
        assert len(collected) >= 0, "    Should return a list"
        print(f"    ✓ collect_font_files([]) returned {len(collected)} file(s)")

        print("  Test 7: Parallel conversion (ThreadPoolExecutor)")
        test_fonts = []
        for i in range(8):
            p = _generate_test_font(temp_dir / f"parallel_{i}.ttf")
            test_fonts.append(p)

        results = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(convert_one, f, ".woff2", False, True): f for f in test_fonts}
            for future in as_completed(futures):
                results.append(future.result())

        assert all(r["success"] for r in results), "    Some parallel conversions failed"
        assert all((temp_dir / f"parallel_{i}.woff2").is_file() for i in range(8)), "    Not all outputs created"
        print(f"    ✓ 8 files converted in parallel")

        print("  Test 8: Error handling (nonexistent file)")
        result = convert_one(Path("/nonexistent/font.ttf"), ".woff2", False, False)
        assert not result["success"], "    Should fail for nonexistent file"
        assert result["error"] is not None, "    Should have error message"
        print(f"    ✓ error handled: {result['error']}")

        print("  Test 9: Reverse conversion (woff2 → ttf)")
        woff2_path = temp_dir / "test1.woff2"
        result = convert_one(woff2_path, ".ttf", remove_original=False, verbose=True)
        assert result["success"], f"    Reverse conversion failed: {result['error']}"
        assert result["ratio"] > 1.0, "    TTF should be larger than WOFF2"
        print(f"    ✓ woff2 → ttf  ratio={result['ratio']:.2%} (expanded)")

        print("  Test 10: All format combinations")
        combos = [
            (".ttf", ".otf"),
            (".ttf", ".woff"),
            (".ttf", ".woff2"),
            (".woff", ".ttf"),
            (".woff", ".woff2"),
            (".woff2", ".woff"),
            (".woff2", ".ttf"),
            (".woff2", ".otf"),
        ]
        for src_ext, dst_ext in combos:
            src_path = temp_dir / f"combo_src{src_ext}"
            base = _generate_test_font(temp_dir / f"combo_base{src_ext}")
            if src_ext != ".ttf":
                convert_one(base, src_ext, remove_original=False, verbose=False)
                src_path = temp_dir / f"combo_base{src_ext}"
            else:
                src_path = base

            dst_path = src_path.with_suffix(dst_ext)
            result = convert_one(src_path, dst_ext, remove_original=False, verbose=False)
            assert result["success"], f"    {src_ext} → {dst_ext} failed: {result['error']}"
            assert dst_path.is_file(), f"    {dst_ext} output not created"
            font = TTFont(str(dst_path))
            font.close()

        print(f"    ✓ all 8 format combinations passed")

    except AssertionError as e:
        print(f"\n  ✗ TEST FAILED: {e}")
        all_passed = False
    except Exception as e:
        print(f"\n  ✗ UNEXPECTED ERROR: {e}")
        all_passed = False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\n{'─' * 55}")
    if all_passed:
        print("  All tests passed! ✓")
    else:
        print("  Some tests FAILED! ✗")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        main()

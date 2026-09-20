import gc
import os
import tempfile
import unittest
from pathlib import Path


def get_size(filepath: Path) -> int:
    try:
        return filepath.stat().st_size
    except OSError:
        return 0


class MockColorPrint:
    def __call__(self, text, color=None) -> None:
        print(text, end="")


cprint = MockColorPrint()


def process_file_optimized(filepath: Path) -> int:
    if filepath.is_symlink() or filepath.suffix == ".bak" or get_size(filepath) == 0:
        return 0
    removed_count = 0
    try:
        temp_file_path = None
        with tempfile.NamedTemporaryFile(
            mode="w+",
            encoding="utf-8",
            delete=False,
            dir=filepath.parent,
            suffix=".tmp",
        ) as temp_f:
            temp_file_path = Path(temp_f.name)
            with filepath.open("r", encoding="utf-8", errors="replace") as original_f:
                for line in original_f:
                    if line.strip():
                        temp_f.write(line)
                    else:
                        removed_count += 1
        if removed_count == 0:
            os.remove(temp_file_path)
            return 0
        os.replace(temp_file_path, filepath)
        gc.collect()
        return removed_count
    except OSError:
        if temp_file_path and temp_file_path.exists():
            os.remove(temp_file_path)
        return 0
    except Exception as e:
        if temp_file_path and temp_file_path.exists():
            os.remove(temp_file_path)
        print(f"An unexpected error occurred processing {filepath.name}: {e}")
        return 0


class TestProcessFileOptimized(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp())
        self.addCleanup(self.cleanup_test_dir)

    def cleanup_test_dir(self) -> None:
        import shutil

        shutil.rmtree(self.test_dir)

    def create_test_file(self, filename: str, content: str) -> Path:
        filepath = self.test_dir / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def read_file_content(self, filepath: Path) -> str:
        return filepath.read_text(encoding="utf-8")

    def test_remove_empty_lines(self) -> None:
        content = "line1\n\nline2\n  \nline3\n"
        expected_content = "line1\nline2\nline3\n"
        filepath = self.create_test_file("test_empty.txt", content)
        removed = process_file_optimized(filepath)
        assert removed == 2
        assert self.read_file_content(filepath) == expected_content

    def test_no_empty_lines(self) -> None:
        content = "line1\nline2\nline3\n"
        filepath = self.create_test_file("test_no_empty.txt", content)
        removed = process_file_optimized(filepath)
        assert removed == 0
        assert self.read_file_content(filepath) == content

    def test_only_empty_lines(self) -> None:
        content = "\n  \n\n   \n"
        expected_content = ""
        filepath = self.create_test_file("test_only_empty.txt", content)
        removed = process_file_optimized(filepath)
        assert removed == 4
        assert self.read_file_content(filepath) == expected_content

    def test_empty_file(self) -> None:
        content = ""
        expected_content = ""
        filepath = self.create_test_file("test_empty_file.txt", content)
        removed = process_file_optimized(filepath)
        assert removed == 0
        assert self.read_file_content(filepath) == expected_content

    def test_symlink(self) -> None:
        filepath = self.create_test_file("original.txt", "content\n")
        symlink_path = self.test_dir / "symlink.txt"
        symlink_path.symlink_to(filepath)
        removed = process_file_optimized(symlink_path)
        assert removed == 0
        assert self.read_file_content(filepath) == "content\n"

    def test_bak_file(self) -> None:
        content = "content\n\n"
        filepath = self.create_test_file("archive.txt.bak", content)
        removed = process_file_optimized(filepath)
        assert removed == 0
        assert self.read_file_content(filepath) == content

    def test_zero_size_file(self) -> None:
        filepath = self.create_test_file("zero_size.txt", "")
        filepath.unlink()
        filepath.touch()
        removed = process_file_optimized(filepath)
        assert removed == 0
        assert filepath.stat().st_size == 0

    def test_persian_characters_and_encoding(self) -> None:
        content = "خط اول\n\nخط دوم\n\n خط سوم\n"
        expected_content = "خط اول\nخط دوم\n خط سوم\n"
        filepath = self.create_test_file("test_persian.txt", content)
        removed = process_file_optimized(filepath)
        assert removed == 2
        assert self.read_file_content(filepath) == expected_content


if __name__ == "__main__":
    unittest.main()

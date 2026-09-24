import io
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final

from loguru import logger
from pypdf import PdfReader, PdfWriter

MAX_WORKERS: Final[int] = 8
DEFAULT_MAX_SIZE_MB: Final[int] = 5
DEFAULT_OUTPUT_DIR_NAME: Final[str] = "output"


def split_pdf_by_size(
    pdf_path: Path,
    output_dir: Path,
    max_size_mb: int = DEFAULT_MAX_SIZE_MB,
) -> tuple[Path, int, str | None]:
    max_size_bytes: int = max_size_mb * 1024 * 1024

    try:
        reader: PdfReader = PdfReader(str(pdf_path))
        stem: str = pdf_path.stem

        current_pages: list[object] = []
        file_count: int = 1

        for page in reader.pages:
            current_pages.append(page)

            writer: PdfWriter = PdfWriter()
            for p in current_pages:
                writer.add_page(p)
            buffer: io.BytesIO = io.BytesIO()
            writer.write(buffer)

            if buffer.tell() > max_size_bytes and len(current_pages) > 1:
                current_pages.pop()

                flush_writer: PdfWriter = PdfWriter()
                for p in current_pages:
                    flush_writer.add_page(p)
                flush_buffer: io.BytesIO = io.BytesIO()
                flush_writer.write(flush_buffer)

                output_path: Path = output_dir / f"{stem}_{file_count}.pdf"
                output_path.write_bytes(flush_buffer.getvalue())
                file_count += 1

                current_pages = [page]

        if current_pages:
            final_writer: PdfWriter = PdfWriter()
            for p in current_pages:
                final_writer.add_page(p)
            final_buffer: io.BytesIO = io.BytesIO()
            final_writer.write(final_buffer)

            output_path = output_dir / f"{stem}_{file_count}.pdf"
            output_path.write_bytes(final_buffer.getvalue())

        return pdf_path, file_count, None
    except Exception as e:
        return pdf_path, 0, str(e)


def _collect_pdf_files(input_paths: list[str] | None) -> list[Path]:
    if not input_paths:
        return list(Path.cwd().rglob("*.pdf"))

    pdf_files: list[Path] = []
    seen: set[Path] = set()
    for raw in input_paths:
        p: Path = Path(raw)
        candidates: list[Path]
        if p.is_file() and p.suffix.lower() == ".pdf":
            candidates = [p]
        elif p.is_dir():
            candidates = list(p.rglob("*.pdf"))
        else:
            candidates = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                pdf_files.append(c)
    return pdf_files


def process_pdfs(
    input_paths: list[str] | None = None,
    output_dir: Path | None = None,
) -> None:
    if output_dir is None:
        output_dir = Path.cwd() / DEFAULT_OUTPUT_DIR_NAME
    output_dir.mkdir(exist_ok=True)

    pdf_files: list[Path] = _collect_pdf_files(input_paths)

    if not pdf_files:
        logger.info("No PDF files found.")
        return

    logger.info(
        "Splitting {} PDF file(s) with {} workers into {}",
        len(pdf_files),
        MAX_WORKERS,
        output_dir,
    )

    jobs: list[tuple[Path, Path, int]] = [(pdf_file, output_dir, DEFAULT_MAX_SIZE_MB) for pdf_file in pdf_files]

    with Pool(processes=MAX_WORKERS) as pool:
        results: list[tuple[Path, int, str | None]] = pool.starmap(split_pdf_by_size, jobs)

    for pdf_path, parts, error in results:
        if error is not None:
            logger.error("❌ {}: {}", pdf_path.name, error)
        else:
            logger.info("✅ {}: wrote {} part(s)", pdf_path.name, parts)

    logger.info("Processing complete. Output files in: {}", output_dir)


def main() -> None:
    args: list[str] = sys.argv[1:]
    process_pdfs(input_paths=args if args else None)


if __name__ == "__main__":
    raise SystemExit(main())

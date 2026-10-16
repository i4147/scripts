import argparse
import json
import os
import re
import signal
import sys
import time
from multiprocessing import Pool, cpu_count
from pathlib import Path
from queue import Empty, Queue

try:
    from deep_translator import GoogleTranslator
except ImportError:
    sys.stderr.write("Missing dependency: pip install deep-translator\n")
    raise
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
TRANSLATE_CHUNK = 20
DEFAULT_SAVE_INTERVAL = 10.0
_shutdown = False


def _has_cyrillic(text):
    return bool(CYRILLIC_RE.search(text))


def _handle_signal(signum, _frame):
    global _shutdown
    _shutdown = True
    sys.stderr.write(f"\n[translate] received signal {signum}, finishing up...\n")


def _translate_texts(texts, src, tgt):
    translator = GoogleTranslator(source=src, target=tgt)
    result = translator.translate_batch(texts)
    if not result or len(result) != len(texts):
        raise RuntimeError(f"translate_batch returned unexpected result (got {result!r})")
    return [r if r is not None else t for r, t in zip(result, texts)]


def _translate_task(
    task,
):
    src, tgt, items = task
    results = []
    pending = []
    for idx, text in items:
        if not text.strip():
            results.append((idx, text))
            continue
        if src == "ru" and not _has_cyrillic(text):
            results.append((idx, text))
            continue
        pending.append((idx, text))
    for i in range(0, len(pending), TRANSLATE_CHUNK):
        batch = pending[i : i + TRANSLATE_CHUNK]
        texts = [t for _, t in batch]
        try:
            translated = _translate_texts(texts, src, tgt)
        except Exception as exc:
            sys.stderr.write(f"[translate] batch failed ({exc}); keeping originals\n")
            translated = texts
        for (idx, _original), tr in zip(batch, translated):
            results.append((idx, tr))
    return results


def _save_progress(
    output_path,
    meta_path,
    lines,
    translations,
    src,
    tgt,
    input_path,
    complete=False,
):
    out_lines = [translations.get(i, lines[i]) for i in range(len(lines))]
    tmp_out = output_path + ".tmp"
    Path(tmp_out).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.replace(tmp_out, output_path)
    meta = {
        "input": str(input_path),
        "output": output_path,
        "source_lang": src,
        "target_lang": tgt,
        "total_lines": len(lines),
        "translated_lines": len(translations),
        "complete": complete,
        "updated_at": time.time(),
    }
    tmp_meta = meta_path + ".tmp"
    Path(tmp_meta).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp_meta, meta_path)


def cmd_translate(args):
    input_path = Path(args.input)
    if not input_path.is_file():
        sys.exit(f"Input file not found: {input_path}")
    lines = input_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        sys.exit("Input file is empty")
    output_path = args.output or str(input_path) + ".translated.txt"
    meta_path = output_path + ".meta.json"
    indexed = list(enumerate(lines))
    batch_size = max(1, args.batch_size)
    batches = [indexed[i : i + batch_size] for i in range(0, len(indexed), batch_size)]
    tasks = [(args.source, args.target, b) for b in batches]
    translations = {}
    last_save = time.time()
    _save_progress(
        output_path,
        meta_path,
        lines,
        translations,
        args.source,
        args.target,
        input_path,
    )
    print(
        f"[translate] {len(lines)} lines / {len(batches)} batches, "
        f"{args.workers} workers, src={args.source} tgt={args.target}",
        file=sys.stderr,
    )
    print(f"[translate] output : {output_path}", file=sys.stderr)
    result_queue = Queue()

    def _on_ok(res):
        result_queue.put(("ok", res))

    def _on_err(exc):
        result_queue.put(("err", exc))

    pool = Pool(processes=args.workers)
    try:
        for t in tasks:
            pool.apply_async(_translate_task, (t,), callback=_on_ok, error_callback=_on_err)
        pending = len(tasks)
        while pending > 0:
            if _shutdown:
                break
            try:
                status, payload = result_queue.get(timeout=0.5)
            except Empty:
                continue
            pending -= 1
            if status == "ok":
                translations.update(dict(payload))
            else:
                sys.stderr.write(f"[translate] task failed: {payload}\n")
            now = time.time()
            if now - last_save >= args.save_interval:
                _save_progress(
                    output_path,
                    meta_path,
                    lines,
                    translations,
                    args.source,
                    args.target,
                    input_path,
                )
                done = len(translations)
                pct = 100.0 * done / len(lines)
                print(
                    f"[translate] progress: {done}/{len(lines)} ({pct:.1f}%)",
                    file=sys.stderr,
                )
                last_save = now
    except KeyboardInterrupt:
        _shutdown = True
    finally:
        pool.terminate()
        pool.join()
        complete = (not _shutdown) and len(translations) == len(lines)
        _save_progress(
            output_path,
            meta_path,
            lines,
            translations,
            args.source,
            args.target,
            input_path,
            complete=complete,
        )
    done = len(translations)
    tag = "complete" if complete else "interrupted"
    print(
        f"[translate] {tag}: wrote {output_path} ({done}/{len(lines)} lines)",
        file=sys.stderr,
    )
    if not complete:
        sys.exit(130 if _shutdown else 1)


def build_parser():
    p = argparse.ArgumentParser(
        description="Translate a text file with deep_translator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-i", "--input", help="Path to the input text file.")
    p.add_argument(
        "-s",
        "--source",
        default="auto",
        help="Source language code (e.g. 'ru', 'en', 'auto').",
    )
    p.add_argument("-t", "--target", default="en", help="Target language code (e.g. 'en').")
    p.add_argument("-o", "--output", help="Output file path (default: <input>.translated.txt).")
    p.add_argument(
        "--workers",
        type=int,
        default=min(4, cpu_count() or 1),
        help="Number of worker processes.",
    )
    p.add_argument("--batch-size", type=int, default=100, help="Number of lines per worker task.")
    p.add_argument(
        "--save-interval",
        type=float,
        default=DEFAULT_SAVE_INTERVAL,
        help="Seconds between periodic progress saves.",
    )
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)
    if not args.input:
        parser.error("--input/-i is required")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    cmd_translate(args)


if __name__ == "__main__":
    main()

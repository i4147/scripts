from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
import json


@dataclass
class Misspelling:
    word: str
    line_number: int
    offset: int
    suggestions: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        sugg = ",".join(self.suggestions)
        ctx = ", ".join(f'"{c}"' for c in self.context)
        return f"word: {self.word} | line: {self.line_number} | offset: {self.offset} | suggestions: {sugg} | context: [{ctx}]"


@dataclass
class Text:
    content: str
    context: list[str] = field(default_factory=list)

    def replace_content(self, new_content: str) -> Text:
        return Text(new_content, self.context)

    def with_context(self, *ctx: str) -> Text:
        return Text(self.content, list(ctx))


class Source(ABC):
    @abstractmethod
    def to_texts(self, context: list[str]) -> Generator[Text, None, None]:
        pass


class StringSource(Source):
    def __init__(self, text: str):
        self.text = text

    def to_texts(self, context: list[str]) -> Generator[Text, None, None]:
        yield Text(self.text, context)


class FileSource(Source):
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def to_texts(self, context: list[str]) -> Generator[Text, None, None]:
        if self.path.is_file():
            content = self.path.read_text(encoding="utf-8")
            yield Text(content, [str(self.path), *context])
        elif self.path.is_dir():
            for file_path in self.path.rglob("*"):
                if file_path.is_file() and file_path.suffix in {".txt", ".md", ".py", ".php", ".js"}:
                    content = file_path.read_text(encoding="utf-8")
                    yield Text(content, [str(file_path), *context])


class MultiSource(Source):
    def __init__(self, sources: Iterable[Source]):
        self.sources = list(sources)

    def to_texts(self, context: list[str]) -> Generator[Text, None, None]:
        for source in self.sources:
            yield from source.to_texts(context)


class TextProcessor(ABC):
    @abstractmethod
    def process(self, text: Text) -> Text:
        pass


class MarkdownRemover(TextProcessor):
    def process(self, text: Text) -> Text:
        content = text.content
        content = re.sub(r"#{1,6}\s+", "", content)
        content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)
        content = re.sub(r"`{1,3}.*?`{1,3}", "", content, flags=re.DOTALL)
        content = re.sub(r"\*{1,2}([^\*]+)\*{1,2}", r"\1", content)
        content = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", content)
        content = re.sub(r"^[-*+]\s+", "", content, flags=re.MULTILINE)
        return text.replace_content(content)


class HTMLRemover(TextProcessor):
    def process(self, text: Text) -> Text:
        content = re.sub(r"<[^>]+>", "", text.content)
        return text.replace_content(content)


class Spellchecker(ABC):
    @abstractmethod
    def check(self, text: str, languages: Sequence[str], context: list[str]) -> Generator[Misspelling, None, None]:
        pass


class Aspell(Spellchecker):
    def __init__(self, cmd: str = "aspell"):
        self.cmd = cmd

    def check(self, text: str, languages: Sequence[str], context: list[str]) -> Generator[Misspelling, None, None]:
        lang = languages[0] if languages else "en_US"
        try:
            result = subprocess.run(
                [self.cmd, "pipe", "-l", lang], input=text, capture_output=True, text=True, timeout=30
            )
            for misspelling in self._parse_output(result.stdout, text, context):
                yield misspelling
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return

    def _parse_output(self, output: str, text: str, context: list[str]) -> Generator[Misspelling, None, None]:
        lines = text.split("\n")
        for line in output.split("\n"):
            if line.startswith("&"):
                parts = line.split()
                word = parts[1]
                count = int(parts[2])
                offset = int(parts[3].rstrip(":"))
                suggestions = parts[4 : 4 + count]

                line_num = 1
                col = offset
                for i, text_line in enumerate(lines, 1):
                    if col <= len(text_line):
                        line_num = i
                        break
                    col -= len(text_line) + 1

                yield Misspelling(word, line_num, offset, suggestions, context)


class Hunspell(Spellchecker):
    def __init__(self, cmd: str = "hunspell"):
        self.cmd = cmd

    def check(self, text: str, languages: Sequence[str], context: list[str]) -> Generator[Misspelling, None, None]:
        lang = languages[0] if languages else "en_US"
        try:
            result = subprocess.run(
                [self.cmd, "-d", lang, "-l"], input=text, capture_output=True, text=True, timeout=30
            )
            for word in result.stdout.strip().split("\n"):
                if word:
                    yield Misspelling(word.strip(), 1, 0, [], context)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return


class MisspellingHandler(ABC):
    @abstractmethod
    def handle(self, misspelling: Misspelling) -> None:
        pass


class EchoHandler(MisspellingHandler):
    def handle(self, misspelling: Misspelling) -> None:
        print(misspelling)


class JSONHandler(MisspellingHandler):
    def __init__(self, output_path: Path | str):
        self.output_path = Path(output_path)
        self.misspellings: list[dict] = []

    def handle(self, misspelling: Misspelling) -> None:
        self.misspellings.append(
            {
                "word": misspelling.word,
                "line": misspelling.line_number,
                "offset": misspelling.offset,
                "suggestions": misspelling.suggestions,
                "context": misspelling.context,
            }
        )

    def flush(self) -> None:
        self.output_path.write_text(json.dumps(self.misspellings, indent=2))


class MisspellingFinder:
    def __init__(
        self, spellchecker: Spellchecker, handler: MisspellingHandler | None = None, *processors: TextProcessor
    ):
        self.spellchecker = spellchecker
        self.handler = handler or EchoHandler()
        self.processors = processors

    def find(self, source: Source | str, languages: Sequence[str], context: list[str] | None = None) -> None:
        if isinstance(source, str):
            source = StringSource(source)

        ctx = context or []
        for text in source.to_texts(ctx):
            for processor in self.processors:
                text = processor.process(text)

            for misspelling in self.spellchecker.check(text.content, languages, text.context):
                self.handler.handle(misspelling)


class ParallelMisspellingFinder:
    def __init__(
        self,
        spellchecker: Spellchecker,
        handler: MisspellingHandler | None = None,
        max_workers: int = 4,
        *processors: TextProcessor,
    ):
        self.spellchecker = spellchecker
        self.handler = handler or EchoHandler()
        self.processors = processors
        self.max_workers = max_workers

    def find(self, source: Source | str, languages: Sequence[str], context: list[str] | None = None) -> None:
        if isinstance(source, str):
            source = StringSource(source)

        ctx = context or []
        texts = list(source.to_texts(ctx))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._process_text, text, languages): text for text in texts}

            for future in as_completed(futures):
                for misspelling in future.result():
                    self.handler.handle(misspelling)

    def _process_text(self, text: Text, languages: Sequence[str]) -> Generator[Misspelling, None, None]:
        for processor in self.processors:
            text = processor.process(text)
        return self.spellchecker.check(text.content, languages, text.context)


def check_files(spellchecker_name: str, *paths: str, languages: list[str] | None = None) -> None:
    languages = languages or ["en_US"]

    if spellchecker_name.lower() == "aspell":
        spellchecker = Aspell()
    elif spellchecker_name.lower() == "hunspell":
        spellchecker = Hunspell()
    else:
        raise ValueError(f"Unknown spellchecker: {spellchecker_name}")

    sources = [FileSource(p) for p in (paths or [Path.cwd()])]
    source = MultiSource(sources) if len(sources) > 1 else sources[0]

    finder = ParallelMisspellingFinder(
        spellchecker,
        EchoHandler(),
        max_workers=4,
    )

    finder.find(source, languages)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        check_files("hunspell", *sys.argv[2:])
    else:
        finder = MisspellingFinder(Hunspell(), EchoHandler())
        finder.find("This is a mispelling in a sentance.", ["en_US"])

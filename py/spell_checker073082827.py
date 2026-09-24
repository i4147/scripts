import argparse
import json
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Iterable, Sequence


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

    def replace_content(self, new_content: str):
        return Text(new_content, self.context)

    def with_context(self, *ctx: str):
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
    def process(self, text: Text):
        pass


class MarkdownRemover(TextProcessor):
    def process(self, text: Text):
        content = text.content
        content = re.sub(r"#{1,6}\s+", "", content)
        content = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", content)
        content = re.sub(r"`{1,3}.*?`{1,3}", "", content, flags=re.DOTALL)
        content = re.sub(r"\*{1,2}([^\*]+)\*{1,2}", r"\1", content)
        content = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", content)
        content = re.sub(r"^[-*+]\s+", "", content, flags=re.MULTILINE)
        return text.replace_content(content)


class HTMLRemover(TextProcessor):
    def process(self, text: Text):
        content = re.sub(r"<[^>]+>", "", text.content)
        return text.replace_content(content)


class Spellchecker(ABC):
    @abstractmethod
    def check(self, text: str, languages: Sequence[str], context: list[str]) -> Generator[Misspelling, None, None]:
        pass


class Hunspell(Spellchecker):
    def __init__(
        self,
        cmd: str = "hunspell",
        personal_dict: Path | str | None = Path("/data/data/com.termux/files/home/.personal_dict"),
    ):
        self.cmd = cmd
        self.personal_dict = Path(personal_dict) if personal_dict else self._get_default_personal_dict()

    def _get_default_personal_dict(self) -> Path:
        home = Path.home()
        return home / ".personal_dict"

    def check(self, text: str, languages: Sequence[str], context: list[str]) -> Generator[Misspelling, None, None]:
        lang = languages[0] if languages else "en_US"
        try:
            cmd_args = [self.cmd, "-d", lang, "-a"]
            if self.personal_dict.exists():
                cmd_args.extend(["-p", str(self.personal_dict)])

            result = subprocess.run(cmd_args, input=text, capture_output=True, text=True, timeout=30)
            for line in result.stdout.strip().split("\n"):
                if line.startswith("&"):
                    parts = line.split()
                    word = parts[1]
                    count = int(parts[2])
                    offset = int(parts[3].rstrip(":"))
                    suggestions = parts[4 : 4 + count]

                    line_num = 1
                    col = offset
                    for i, text_line in enumerate(text.split("\n"), 1):
                        if col <= len(text_line):
                            line_num = i
                            break
                        col -= len(text_line) + 1

                    yield Misspelling(word, line_num, offset, suggestions, context)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return

    def add_word(self, word: str, language: str | None = None) -> None:
        if not self.personal_dict.exists():
            self.personal_dict.touch()
            self.personal_dict.write_text("0\n")

        words = self.personal_dict.read_text(encoding="utf-8").strip().split("\n")
        if len(words) > 0 and words[0].isdigit():
            count = int(words[0])
            word_list = words[1:]
        else:
            count = 0
            word_list = words

        if word not in word_list:
            word_list.append(word)
            content = f"{len(word_list)}\n" + "\n".join(sorted(word_list))
            self.personal_dict.write_text(content, encoding="utf-8")

    def add_words(self, words: Iterable[str], language: str | None = None) -> None:
        for word in words:
            self.add_word(word, language)

    def load_words_from_file(self, file_path: Path | str) -> None:
        file_path = Path(file_path)
        if file_path.exists():
            words = file_path.read_text(encoding="utf-8").strip().split("\n")
            self.add_words([w.strip() for w in words if w.strip()])

    def get_personal_dict_path(self) -> Path:
        return self.personal_dict

    def clear_personal_dict(self) -> None:
        if self.personal_dict.exists():
            self.personal_dict.unlink()

    def list_custom_words(self) -> list[str]:
        if not self.personal_dict.exists():
            return []
        lines = self.personal_dict.read_text(encoding="utf-8").strip().split("\n")
        if len(lines) > 0 and lines[0].isdigit():
            return lines[1:]
        return lines


class MisspellingHandler(ABC):
    @abstractmethod
    def handle(self, misspelling: Misspelling) -> None:
        pass


class EchoHandler(MisspellingHandler):
    def __init__(self, apply_fixes: bool = False):
        self.apply_fixes = apply_fixes

    def handle(self, misspelling: Misspelling) -> None:
        if misspelling.suggestions:
            print(f"{misspelling} | recommended: {misspelling.suggestions[0]}")
        else:
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
    def __init__(self, spellchecker: Spellchecker, handler: MisspellingHandler, *processors: TextProcessor):
        self.spellchecker = spellchecker
        self.handler = handler
        self.processors = processors
        self.max_workers = 4

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


def check_files(*paths: str, languages: list[str] | None = None, apply_fixes: bool = False) -> None:
    languages = languages or ["en_US"]

    spellchecker = Hunspell()
    sources = [FileSource(p) for p in (paths or [Path.cwd()])]
    source = MultiSource(sources) if len(sources) > 1 else sources[0]

    finder = ParallelMisspellingFinder(spellchecker, EchoHandler(apply_fixes), MarkdownRemover())

    finder.find(source, languages)


def main():
    parser = argparse.ArgumentParser(description="Spell checker using hunspell")
    parser.add_argument(
        "spellchecker", nargs="?", default="hunspell", help="Spellchecker to use (only hunspell supported)"
    )
    parser.add_argument("-a", "--apply", action="store_true", help="Apply spelling fixes")
    parser.add_argument("paths", nargs="*", help="Files or directories to check")
    args = parser.parse_args()

    check_files(*args.paths, apply_fixes=args.apply)


if __name__ == "__main__":
    main()

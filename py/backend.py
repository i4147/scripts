from typing import Iterator, Tuple, Any

from .cyjson_backend import CythonJSONParser


def parse(file_obj) -> Iterator[Tuple[str, Any]]:
    parser = CythonJSONParser(file_obj)
    for event, value in parser:
        yield event, value


def items(file_obj, prefix: str) -> Iterator[Any]:
    pass

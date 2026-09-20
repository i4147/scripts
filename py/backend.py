from pathlib import Path
from typing import Iterator, Tuple, Any, Union

from .cyjson_backend import CythonJSONParser


def parse(file_obj) -> Iterator[Tuple[str, Any]]:
    parser = CythonJSONParser(file_obj)
    for event, value in parser:
        yield event, value


def items(file_obj, prefix: str) -> Iterator[Any]:
    import ijson.backends.python as ijson_python

from __future__ import annotations

import ipaddress
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

pattern = re.compile(
    r"""(?:
            url\s*\(\s*["']?
          | (?:src|href)\s*=\s*["']
        )
        data:([^;,]+)
        (?:;[^,]*)?
        ;base64,\s*
        ([A-Za-z0-9+/]+={0,2})
        ["']?
        (?:\s*\))?
    """,
    re.IGNORECASE | re.VERBOSE,
)
WORD_PATTERN = re.compile(
    r"""
    [A-Z]+(?=[A-Z][a-z]|\d|\b)   # Acronym followed by lowercase or number
    |[A-Z]?[a-z]+                # Standard word
    |[A-Z]+                      # All caps word
    |\d+                         # Numbers (optional)
    """,
    re.VERBOSE,
)


def get_sha256(path: str | Path, chunk_size: int = 524288) -> str:
    from hashlib import sha256

    path = Path(path)
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def has_doc(code: str) -> bool:
    import tokenize
    from io import StringIO

    try:
        tokens = tokenize.generate_tokens(StringIO(code).readline)
        for tok_type, _, _, _, _ in tokens:
            if tok_type == tokenize.COMMENT:
                return True
    except:
        pass
    import ast

    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and ast.get_docstring(node) is not None
            ):
                return True
    except SyntaxError:
        pass
    return False


def _is_valid_hostname(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        ipaddress.IPv4Address(hostname)
        return True
    except ValueError:
        pass
    try:
        ipaddress.IPv6Address(hostname)
        return True
    except ValueError:
        pass
    if len(hostname) > 253:
        return False
    labels = hostname.split(".")
    if not labels:
        return False
    for _i, label in enumerate(labels):
        if not label or len(label) > 63:
            return False
        if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$", label):
            return False
    return True


def is_valid_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    url = url.strip()
    if "${" in url or "`" in url:
        return False
    if "://" not in url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https", "ftp", "ftps"):
        return False
    if parsed.port is not None and not (0 < parsed.port < 65536):
        return False
    if not parsed.hostname:
        return False
    hostname = parsed.hostname
    return _is_valid_hostname(hostname)


def slugify(string):
    normalized = unicodedata.normalize("NFKD", string).encode("ascii", "ignore").decode("ascii")
    return re.sub(
        r"[-\s]+",
        "-",
        re.sub(r"[^\w\s-]", "", normalized).strip().lower(),
    )


def tokenize_text(text: str) -> list[str]:
    tokens = []
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
        identifier = match.group()
        subwords = WORD_PATTERN.findall(identifier)
        tokens.extend(subwords if subwords else [identifier])
    return tokens

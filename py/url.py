from __future__ import annotations
import idna
import argparse
import sys
from importlib.metadata import version
import re
import unicodedata
from typing import NamedTuple
from urllib.parse import quote as quote_orig
from urllib.parse import unquote as unquote_orig
from urllib.parse import urlsplit, urlunsplit
from urllib.parse import unquote

DEFAULT_SCHEME = "https"
DEFAULT_PORT = {
    "ftp": "21",
    "gopher": "70",
    "http": "80",
    "https": "443",
    "news": "119",
    "nntp": "119",
    "snews": "563",
    "snntp": "563",
    "telnet": "23",
    "ws": "80",
    "wss": "443",
}
DEFAULT_CHARSET = "utf-8"
AUTHORITY_SCHEMES = frozenset(["http", "https", "ftp", "ftps"])
DEFAULT_ALLOWLIST = {
    "google.com": ["q", "ie"],
    "baidu.com": ["wd", "ie"],
    "bing.com": ["q"],
    "youtube.com": ["v", "search_query"],
}
QUERY_PARAM_SAFE_CHARS = "~:/?[]@!$'()*+,;"
UNICODE_REPLACEMENT_CHARACTER = "�"


def normalize_scheme(scheme: str) -> str:
    return scheme.lower()


def normalize_userinfo(userinfo: str) -> str:
    if userinfo in ["@", ":@"]:
        return ""
    return userinfo


def generic_url_cleanup(url: str) -> str:
    url = url.replace("#!", "?_escaped_fragment_=")
    return url.rstrip("&? ")


def normalize_port(port: str, scheme: str) -> str:
    if not port.isdigit():
        return port
    port = str(int(port))
    if DEFAULT_PORT.get(scheme) == port:
        return ""
    return port


def provide_url_domain(url: str, default_domain: (str | None) = None) -> str:
    if not default_domain or not url or url == "-":
        return url
    if url.startswith("/") and not url.startswith("//"):
        return "//" + default_domain + url
    return url


def normalize_fragment(fragment: str) -> str:
    return quote(unquote(fragment), safe="~=")


def normalize_host(host: str, charset: str = DEFAULT_CHARSET) -> str:
    host = force_unicode(host, charset)
    host = host.lower()
    host = host.strip(".")
    parts = host.split(".")
    try:
        parts = [idna.encode(p, uts46=True).decode(charset) for p in parts if p]
        return ".".join(parts)
    except idna.IDNAError:
        return host.encode("idna").decode(charset)


def provide_url_scheme(url: str, default_scheme: str = DEFAULT_SCHEME) -> str:
    has_scheme = ":" in url[:7]
    is_universal_scheme = url.startswith("//")
    is_file_path = url == "-" or url.startswith("/") and not is_universal_scheme
    if not url or is_file_path:
        return url
    if not has_scheme:
        return f"{default_scheme}://{url.lstrip('/')}"
    scheme_part, rest = url.split(":", 1)
    if scheme_part.lower() not in AUTHORITY_SCHEMES:
        return url
    return f"{scheme_part}://{rest.lstrip('/')}"


def get_allowed_params(host: (str | None) = None, allowlist: (dict | list | None) = None) -> set[str]:
    if isinstance(allowlist, list):
        return set(allowlist)
    if not host:
        return set()
    domain = host.lower()
    domain = domain.removeprefix("www.")
    domain = domain.split(":")[0]
    if allowlist is None:
        allowlist = DEFAULT_ALLOWLIST
    return set(allowlist.get(domain, []))


def normalize_path(path: str, scheme: str) -> str:
    path = quote(unquote(path), "~:/#[]@!$&'()*+,;=")
    if scheme in {"", "http", "https", "ftp", "file"}:
        output: list[str] = []
        for part in path.split("/"):
            if part == "":
                if not output:
                    output.append(part)
            elif part == ".":
                pass
            elif part == "..":
                if len(output) > 1:
                    output.pop()
            else:
                output.append(part)
        last_part = part
        if last_part in {"", ".", ".."}:
            output.append("")
        path = "/".join(output)
    if not path and scheme in {"http", "https", "ftp", "file"}:
        path = "/"
    return path


def process_query_param(param: str) -> str:
    if not param:
        return ""
    return quote(unquote(param), QUERY_PARAM_SAFE_CHARS)


def normalize_query(
    query: str, *, host: (str | None) = None, filter_params: bool = False, param_allowlist: (list | dict | None) = None
) -> str:
    if not query:
        return ""
    processed = []
    for param in query.split("&"):
        if not param:
            continue
        key, _, value = param.partition("=")
        key = process_query_param(key)
        if filter_params:
            allowed_params = get_allowed_params(host, param_allowlist)
            if key not in allowed_params:
                continue
        value = process_query_param(value)
        processed.append(f"{key}={value}" if value else key)
    return "&".join(processed)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Normalize a URL.")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {version('url-normalize')}")
    parser.add_argument("url", help="The URL to normalize.")
    parser.add_argument("-c", "--charset", default="utf-8", help="The charset of the URL. Default: utf-8")
    parser.add_argument(
        "-s", "--default-scheme", default="https", help="The default scheme to use if missing. Default: https"
    )
    parser.add_argument("-f", "--filter-params", action="store_true", help="Filter common tracking parameters.")
    parser.add_argument(
        "-d", "--default-domain", type=str, help="Default domain to use for absolute paths (starting with '/')."
    )
    parser.add_argument(
        "-p", "--param-allowlist", type=str, help="Comma-separated list of query parameters to allow (e.g., 'q,id')."
    )
    parser.add_argument(
        "-H", "--humanize", action="store_true", help="Print a human-readable URL that normalizes to the same value."
    )
    args = parser.parse_args()
    allowlist = args.param_allowlist.split(",") if args.param_allowlist else None
    transform_url = url_humanize if args.humanize else url_normalize
    try:
        output_url = transform_url(
            args.url,
            charset=args.charset,
            default_scheme=args.default_scheme,
            default_domain=args.default_domain,
            filter_params=args.filter_params,
            param_allowlist=allowlist,
        )
    except Exception as e:
        print(f"Error normalizing URL: {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print(output_url)


def deconstruct_url(url: str) -> URL:
    scheme, auth, path, query, fragment = urlsplit(url.strip())
    match = re.search("([^@]*@)?([^:]*):?(.*)", auth)
    userinfo, host, port = match.groups()
    return URL(
        fragment=fragment, host=host, path=path, port=port or "", query=query, scheme=scheme, userinfo=userinfo or ""
    )


def reconstruct_url(url: URL) -> str:
    auth = (url.userinfo or "") + url.host
    if url.port:
        auth += ":" + url.port
    return urlunsplit((url.scheme, auth, url.path, url.query, url.fragment))


def force_unicode(string: (str | bytes), charset: str = "utf-8") -> str:
    if isinstance(string, bytes):
        return string.decode(charset, "replace")
    return string


def unquote(string: str, charset: str = "utf-8") -> str:
    string = unquote_orig(string)
    string = force_unicode(string, charset)
    encoded_str = unicodedata.normalize("NFC", string).encode(charset)
    return encoded_str.decode(charset)


def quote(string: str, safe: str = "/") -> str:
    return quote_orig(string, safe)


def url_normalize(
    url: (str | None),
    *,
    charset: str = DEFAULT_CHARSET,
    default_scheme: str = DEFAULT_SCHEME,
    default_domain: (str | None) = None,
    filter_params: bool = False,
    param_allowlist: (dict | list | None) = None,
) -> str | None:
    if not url:
        return url
    url = provide_url_domain(url, default_domain)
    url = provide_url_scheme(url, default_scheme)
    url = generic_url_cleanup(url)
    url_elements = deconstruct_url(url)
    url_elements = url_elements._replace(
        scheme=normalize_scheme(url_elements.scheme),
        userinfo=normalize_userinfo(url_elements.userinfo),
        host=normalize_host(url_elements.host, charset),
        query=normalize_query(
            url_elements.query, host=url_elements.host, filter_params=filter_params, param_allowlist=param_allowlist
        ),
        fragment=normalize_fragment(url_elements.fragment),
    )
    url_elements = url_elements._replace(
        port=normalize_port(url_elements.port, url_elements.scheme),
        path=normalize_path(url_elements.path, url_elements.scheme),
    )
    return reconstruct_url(url_elements)


def _humanize_host(host: str) -> str:
    return ".".join(_humanize_host_label(label) for label in host.split("."))


def _humanize_host_label(label: str) -> str:
    try:
        return idna.decode(label)
    except idna.IDNAError:
        return label


def _replace_if_round_trips(url: URL, normalized: str, **changes: str) -> URL:
    candidate = url._replace(**changes)
    if url_normalize(reconstruct_url(candidate)) == normalized:
        return candidate
    return url


def _safe_unquote(value: str) -> str:
    decoded = unquote(value)
    if UNICODE_REPLACEMENT_CHARACTER in decoded:
        return value
    return decoded


def _format_query_param(key: str, separator: str, value: str) -> str:
    return f"{key}{separator}{value}" if separator else key


def _replace_query_part_if_round_trips(
    url: URL, normalized: str, parts: list[str], index: int, part: str
) -> tuple[URL, list[str]]:
    candidate_parts = [*parts]
    candidate_parts[index] = part
    candidate = url._replace(query="&".join(candidate_parts))
    if url_normalize(reconstruct_url(candidate)) == normalized:
        return candidate, candidate_parts
    return url, parts


def _humanize_query(url: URL, normalized: str) -> URL:
    parts = url.query.split("&")
    for index, param in enumerate(parts):
        key, separator, value = param.partition("=")
        url, parts = _replace_query_part_if_round_trips(
            url, normalized, parts, index, _format_query_param(_safe_unquote(key), separator, value)
        )
        key, separator, value = parts[index].partition("=")
        url, parts = _replace_query_part_if_round_trips(
            url, normalized, parts, index, _format_query_param(key, separator, _safe_unquote(value))
        )
    return url


def url_humanize(
    url: (str | None),
    *,
    charset: str = DEFAULT_CHARSET,
    default_scheme: str = DEFAULT_SCHEME,
    default_domain: (str | None) = None,
    filter_params: bool = False,
    param_allowlist: (dict | list | None) = None,
) -> str | None:
    normalized = url_normalize(
        url,
        charset=charset,
        default_scheme=default_scheme,
        default_domain=default_domain,
        filter_params=filter_params,
        param_allowlist=param_allowlist,
    )
    if not normalized:
        return normalized
    url_elements = deconstruct_url(normalized)
    url_elements = _replace_if_round_trips(url_elements, normalized, host=_humanize_host(url_elements.host))
    for component in ("userinfo", "path", "fragment"):
        value = getattr(url_elements, component)
        url_elements = _replace_if_round_trips(url_elements, normalized, **{component: _safe_unquote(value)})
    url_elements = _humanize_query(url_elements, normalized)
    return reconstruct_url(url_elements)


class URL(NamedTuple):
    scheme: str
    userinfo: str
    host: str
    port: str
    path: str
    query: str
    fragment: str


__all__ = [
    "AUTHORITY_SCHEMES",
    "DEFAULT_ALLOWLIST",
    "DEFAULT_CHARSET",
    "DEFAULT_PORT",
    "DEFAULT_SCHEME",
    "QUERY_PARAM_SAFE_CHARS",
    "UNICODE_REPLACEMENT_CHARACTER",
    "URL",
    "_format_query_param",
    "_humanize_host",
    "_humanize_host_label",
    "_humanize_query",
    "_replace_if_round_trips",
    "_replace_query_part_if_round_trips",
    "_safe_unquote",
    "deconstruct_url",
    "force_unicode",
    "generic_url_cleanup",
    "get_allowed_params",
    "main",
    "normalize_fragment",
    "normalize_host",
    "normalize_path",
    "normalize_port",
    "normalize_query",
    "normalize_scheme",
    "normalize_userinfo",
    "process_query_param",
    "provide_url_domain",
    "provide_url_scheme",
    "quote",
    "reconstruct_url",
    "unquote",
    "url_humanize",
    "url_normalize",
]

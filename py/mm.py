import contextlib
import copyreg as _copy_reg
from locale import getpreferredencoding as _getpreferredencoding
from threading import RLock as _RLock
from regex import _regex, _regex_core
from regex._regex_core import *
from regex._regex_core import _ALL_ENCODINGS, _ALL_VERSIONS
from regex._regex_core import ALNUM as _ALNUM
from regex._regex_core import OP as _OP
from regex._regex_core import Fuzzy as _Fuzzy
from regex._regex_core import Info as _Info
from regex._regex_core import Source as _Source
from regex._regex_core import (
    _check_group_features,
    _compile_firstset,
    _compile_replacement,
    _FirstSetError,
    _flatten_code,
    _fold_case,
    _get_required_string,
    _parse_pattern,
    _shrink_cache,
    _UnscopedFlagSet,
)

__all__ = [
    "ASCII",
    "BESTMATCH",
    "DEBUG",
    "DEFAULT_VERSION",
    "DOTALL",
    "ENHANCEMATCH",
    "FULLCASE",
    "IGNORECASE",
    "LOCALE",
    "MULTILINE",
    "POSIX",
    "REVERSE",
    "TEMPLATE",
    "UNICODE",
    "V0",
    "V1",
    "VERBOSE",
    "VERSION0",
    "VERSION1",
    "WORD",
    "A",
    "B",
    "D",
    "E",
    "F",
    "I",
    "L",
    "M",
    "P",
    "R",
    "Regex",
    "RegexFlag",
    "S",
    "Scanner",
    "T",
    "U",
    "W",
    "X",
    "__doc__",
    "__version__",
    "cache_all",
    "compile",
    "error",
    "escape",
    "findall",
    "finditer",
    "fullmatch",
    "match",
    "purge",
    "search",
    "split",
    "splititer",
    "sub",
    "subf",
    "subfn",
    "subn",
    "template",
]
__version__ = "2025.11.3"


def match(
    pattern,
    string,
    flags: int = 0,
    pos=None,
    endpos=None,
    partial: bool = False,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.match(string, pos, endpos, concurrent, partial, timeout)


def fullmatch(
    pattern,
    string,
    flags: int = 0,
    pos=None,
    endpos=None,
    partial: bool = False,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.fullmatch(string, pos, endpos, concurrent, partial, timeout)


def search(
    pattern,
    string,
    flags: int = 0,
    pos=None,
    endpos=None,
    partial: bool = False,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.search(string, pos, endpos, concurrent, partial, timeout)


def sub(
    pattern,
    repl,
    string,
    count: int = 0,
    flags: int = 0,
    pos=None,
    endpos=None,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.sub(repl, string, count, pos, endpos, concurrent, timeout)


def subf(
    pattern,
    format,
    string,
    count: int = 0,
    flags: int = 0,
    pos=None,
    endpos=None,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.subf(format, string, count, pos, endpos, concurrent, timeout)


def subn(
    pattern,
    repl,
    string,
    count: int = 0,
    flags: int = 0,
    pos=None,
    endpos=None,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.subn(repl, string, count, pos, endpos, concurrent, timeout)


def subfn(
    pattern,
    format,
    string,
    count: int = 0,
    flags: int = 0,
    pos=None,
    endpos=None,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.subfn(format, string, count, pos, endpos, concurrent, timeout)


def split(
    pattern,
    string,
    maxsplit: int = 0,
    flags: int = 0,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.split(string, maxsplit, concurrent, timeout)


def splititer(
    pattern,
    string,
    maxsplit: int = 0,
    flags: int = 0,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.splititer(string, maxsplit, concurrent, timeout)


def findall(
    pattern,
    string,
    flags: int = 0,
    pos=None,
    endpos=None,
    overlapped: bool = False,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.findall(string, pos, endpos, overlapped, concurrent, timeout)


def finditer(
    pattern,
    string,
    flags: int = 0,
    pos=None,
    endpos=None,
    overlapped: bool = False,
    partial: bool = False,
    concurrent=None,
    timeout=None,
    ignore_unused: bool = False,
    **kwargs,
):
    pat = _compile(pattern, flags, ignore_unused, kwargs, True)
    return pat.finditer(string, pos, endpos, overlapped, concurrent, partial, timeout)


def compile(pattern, flags: int = 0, ignore_unused: bool = False, cache_pattern=None, **kwargs):
    if cache_pattern is None:
        cache_pattern = _cache_all
    return _compile(pattern, flags, ignore_unused, kwargs, cache_pattern)


def purge() -> None:
    _cache.clear()
    _locale_sensitive.clear()


_cache_all = True


def cache_all(value: bool = True) -> bool | None:
    global _cache_all
    if value is None:
        return _cache_all
    _cache_all = value
    return None


def template(pattern, flags: int = 0):
    return _compile(pattern, flags | TEMPLATE, False, {}, False)


def escape(pattern, special_only: bool = True, literal_spaces: bool = False) -> bytes | str:
    p = pattern.decode("latin-1") if isinstance(pattern, bytes) else pattern
    s = []
    if special_only:
        for c in p:
            if c == " " and literal_spaces:
                s.append(c)
            elif c in _METACHARS or c.isspace():
                s.append("\\")
                s.append(c)
            else:
                s.append(c)
    else:
        for c in p:
            if c == " " and literal_spaces or c in _ALNUM:
                s.append(c)
            else:
                s.append("\\")
                s.append(c)
    r = "".join(s)
    if isinstance(pattern, bytes):
        r = r.encode("latin-1")
    return r


DEFAULT_VERSION = RegexFlag.VERSION0
_METACHARS = frozenset("()[]{}?*+|^$\\.-#&~")
_regex_core.DEFAULT_VERSION = DEFAULT_VERSION
_cache = {}
_cache_lock = _RLock()
_MAXCACHE = 500


def _compile(pattern: str, flags, ignore_unused, kwargs, cache_it):
    global DEFAULT_VERSION
    with contextlib.suppress(ImportError):
        from regex import DEFAULT_VERSION
    if flags & DEBUG != 0:
        cache_it = False
    locale_key = (type(pattern), pattern)
    pattern_locale = _getpreferredencoding() if _locale_sensitive.get(locale_key, True) or flags & LOCALE != 0 else None

    def complain_unused_args() -> None:
        if ignore_unused:
            return
        unused_kwargs = set(kwargs) - {k for k, v in args_needed}
        if unused_kwargs:
            any_one = next(iter(unused_kwargs))
            msg = f"unused keyword argument {any_one!a}"
            raise ValueError(msg)

    if cache_it:
        try:
            args_key = (pattern, type(pattern), flags)
            args_needed = _named_args[args_key]
            args_supplied = set()
            if args_needed:
                for k, _v in args_needed:
                    try:
                        args_supplied.add((k, frozenset(kwargs[k])))
                    except KeyError:
                        msg = f"missing named list: {k!r}"
                        raise error(msg)
            complain_unused_args()
            args_supplied = frozenset(args_supplied)
            pattern_key = (pattern, type(pattern), flags, args_supplied, DEFAULT_VERSION, pattern_locale)
            return _cache[pattern_key]
        except KeyError:
            pass
    if isinstance(pattern, str):
        guess_encoding = UNICODE
    elif isinstance(pattern, bytes):
        guess_encoding = ASCII
    elif isinstance(pattern, Pattern):
        if flags:
            msg = "cannot process flags argument with a compiled pattern"
            raise ValueError(msg)
        return pattern
    else:
        msg = "first argument must be a string or compiled pattern"
        raise TypeError(msg)
    _regex_core.DEFAULT_VERSION = DEFAULT_VERSION
    global_flags = flags
    while True:
        caught_exception = None
        try:
            source = _Source(pattern)
            info = _Info(global_flags, source.char_type, kwargs)
            info.guess_encoding = guess_encoding
            source.ignore_space = bool(info.flags & VERBOSE)
            parsed = _parse_pattern(source, info)
            break
        except _UnscopedFlagSet:
            global_flags = info.global_flags
        except error as e:
            caught_exception = e
        if caught_exception:
            raise error(caught_exception.msg, caught_exception.pattern, caught_exception.pos)
    if not source.at_end():
        msg = "unbalanced parenthesis"
        raise error(msg, pattern, source.pos)
    version = info.flags & _ALL_VERSIONS or DEFAULT_VERSION
    if version not in (0, VERSION0, VERSION1):
        msg = "VERSION0 and VERSION1 flags are mutually incompatible"
        raise ValueError(msg)
    if info.flags & _ALL_ENCODINGS not in (0, ASCII, LOCALE, UNICODE):
        msg = "ASCII, LOCALE and UNICODE flags are mutually incompatible"
        raise ValueError(msg)
    if isinstance(pattern, bytes) and info.flags & UNICODE:
        msg = "cannot use UNICODE flag with a bytes pattern"
        raise ValueError(msg)
    if not info.flags & _ALL_ENCODINGS:
        if isinstance(pattern, str):
            info.flags |= UNICODE
        else:
            info.flags |= ASCII
    reverse = bool(info.flags & REVERSE)
    fuzzy = isinstance(parsed, _Fuzzy)
    _locale_sensitive[locale_key] = info.inline_locale
    caught_exception = None
    try:
        parsed.fix_groups(pattern, reverse, False)
    except error as e:
        caught_exception = e
    if caught_exception:
        raise error(caught_exception.msg, caught_exception.pattern, caught_exception.pos)
    if flags & DEBUG:
        parsed.dump(indent=0, reverse=reverse)
    parsed = parsed.optimise(info, reverse)
    parsed = parsed.pack_characters(info)
    req_offset, req_chars, req_flags = _get_required_string(parsed, info.flags)
    named_lists = {}
    named_list_indexes = [None] * len(info.named_lists_used)
    args_needed = set()
    for key, index in info.named_lists_used.items():
        name, case_flags = key
        values = frozenset(kwargs[name])
        items = frozenset((_fold_case(info, v) for v in values)) if case_flags else values
        named_lists[name] = values
        named_list_indexes[index] = items
        args_needed.add((name, values))
    complain_unused_args()
    _check_group_features(info, parsed)
    code = parsed.compile(reverse)
    key = (0, reverse, fuzzy)
    ref = info.call_refs.get(key)
    if ref is not None:
        code = [(_OP.CALL_REF, ref), *code, (_OP.END,)]
    code += [(_OP.SUCCESS,)]
    for group, rev, fuz in info.additional_groups:
        code += group.compile(rev, fuz)
    code = _flatten_code(code)
    if not parsed.has_simple_start():
        try:
            fs_code = _compile_firstset(info, parsed.get_firstset(reverse))
            fs_code = _flatten_code(fs_code)
            code = fs_code + code
        except _FirstSetError:
            pass
    index_group = {v: n for n, v in info.group_index.items()}
    compiled_pattern = _regex.compile(
        pattern,
        info.flags | version,
        code,
        info.group_index,
        index_group,
        named_lists,
        named_list_indexes,
        req_offset,
        req_chars,
        req_flags,
        info.group_count,
    )
    if len(_cache) >= _MAXCACHE:
        with _cache_lock:
            _shrink_cache(_cache, _named_args, _locale_sensitive, _MAXCACHE)
    if cache_it:
        if info.flags & LOCALE == 0:
            pattern_locale = None
        args_needed = frozenset(args_needed)
        pattern_key = (pattern, type(pattern), flags, args_needed, DEFAULT_VERSION, pattern_locale)
        _cache[pattern_key] = compiled_pattern
        _named_args[args_key] = args_needed
    return compiled_pattern


def _compile_replacement_helper(pattern, template):
    key = (pattern.pattern, pattern.flags, template)
    compiled = _replacement_cache.get(key)
    if compiled is not None:
        return compiled
    if len(_replacement_cache) >= _MAXREPCACHE:
        _replacement_cache.clear()
    is_unicode = isinstance(template, str)
    source = _Source(template)
    if is_unicode:

        def make_string(char_codes) -> str:
            return "".join((chr(c) for c in char_codes))

    else:

        def make_string(char_codes) -> bytes:
            return bytes(char_codes)

    compiled = []
    literal = []
    while True:
        ch = source.get()
        if not ch:
            break
        if ch == "\\":
            is_group, items = _compile_replacement(source, pattern, is_unicode)
            if is_group:
                if literal:
                    compiled.append(make_string(literal))
                    literal = []
                compiled.extend(items)
            else:
                literal.extend(items)
        else:
            literal.append(ord(ch))
    if literal:
        compiled.append(make_string(literal))
    _replacement_cache[key] = compiled
    return compiled


_pat = _compile("", 0, False, {}, False)
Pattern = type(_pat)
Match = type(_pat.match(""))
del _pat
__all__.append("Pattern")
__all__.append("Match")
Regex = compile


def _pickle(pattern):
    return (_regex.compile, pattern._pickled_data)


_copy_reg.pickle(Pattern, _pickle)

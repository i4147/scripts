from typing import Self
import functools
import operator
import re
import sys
from collections import UserDict, UserList
from itertools import starmap

__all__ = ["docopt"]


class DocoptLanguageError(Exception):
    pass


class DocoptExit(SystemExit):
    usage = ""

    def __init__(self, message: str = "") -> None:
        SystemExit.__init__(
            self,
            (message + "\n" + self.usage).strip(),
        )


class Pattern:
    def __eq__(self, other) -> bool:
        return repr(self) == repr(other)

    def __hash__(self) -> int:
        return hash(repr(self))

    def fix(self) -> Self:
        self.fix_identities()
        self.fix_repeating_arguments()
        return self

    def fix_identities(self, uniq=None) -> Self | None:
        if not hasattr(self, "children"):
            return self
        uniq = list(set(self.flat())) if uniq is None else uniq
        for i, c in enumerate(self.children):
            if not hasattr(c, "children"):
                assert c in uniq
                self.children[i] = uniq[uniq.index(c)]
            else:
                c.fix_identities(uniq)
        return None

    def fix_repeating_arguments(self) -> Self:
        either = [list(c.children) for c in self.either.children]
        for case in either:
            for e in [c for c in case if case.count(c) > 1]:
                if type(e) is Argument or (type(e) is Option and e.argcount):
                    if e.value is None:
                        e.value = []
                    elif type(e.value) is not list:
                        e.value = e.value.split()
                if type(e) is Command or (type(e) is Option and e.argcount == 0):
                    e.value = 0
        return self

    @property
    def either(self) -> Either:
        ret = []
        groups = [[self]]
        while groups:
            children = groups.pop(0)
            types = [type(c) for c in children]
            if Either in types:
                either = next(c for c in children if type(c) is Either)
                children.pop(children.index(either))
                groups.extend([c, *children] for c in either.children)
            elif Required in types:
                required = next(c for c in children if type(c) is Required)
                children.pop(children.index(required))
                groups.append(list(required.children) + children)
            elif Optional in types:
                optional = next(c for c in children if type(c) is Optional)
                children.pop(children.index(optional))
                groups.append(list(optional.children) + children)
            elif AnyOptions in types:
                optional = next(c for c in children if type(c) is AnyOptions)
                children.pop(children.index(optional))
                groups.append(list(optional.children) + children)
            elif OneOrMore in types:
                oneormore = next(c for c in children if type(c) is OneOrMore)
                children.pop(children.index(oneormore))
                groups.append(list(oneormore.children) * 2 + children)
            else:
                ret.append(children)
        return Either(*list(starmap(Required, ret)))


class ChildPattern(Pattern):
    def __init__(self, name, value=None) -> None:
        self.name = name
        self.value = value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name!r}, {self.value!r})"

    def flat(self, *types):
        return [self] if not types or type(self) in types else []

    def match(self, left, collected=None):
        collected = [] if collected is None else collected
        pos, match = self.single_match(left)
        if match is None:
            return False, left, collected
        left_ = left[:pos] + left[pos + 1 :]
        same_name = [a for a in collected if a.name == self.name]
        if type(self.value) in {int, list}:
            increment = 1 if type(self.value) is int else [match.value] if type(match.value) is str else match.value
            if not same_name:
                match.value = increment
                return (
                    True,
                    left_,
                    [*collected, match],
                )
            same_name[0].value += increment
            return True, left_, collected
        return True, left_, [*collected, match]


class ParentPattern(Pattern):
    def __init__(self, *children) -> None:
        self.children = list(children)

    def __repr__(self) -> str:
        return "{}({})".format(
            self.__class__.__name__,
            ", ".join(repr(a) for a in self.children),
        )

    def flat(self, *types):
        if type(self) in types:
            return [self]
        return functools.reduce(
            operator.iadd,
            [c.flat(*types) for c in self.children],
            [],
        )


class Argument(ChildPattern):
    def single_match(self, left) -> tuple[int, Argument] | tuple[None, None]:
        for n, p in enumerate(left):
            if type(p) is Argument:
                return n, Argument(self.name, p.value)
        return None, None

    @classmethod
    def parse(cls, source) -> Self:
        name = re.findall(r"(<\S*?>)", source)[0]
        value = re.findall(
            r"\[default: (.*)\]",
            source,
            flags=re.I,
        )
        return cls(name, value[0] if value else None)


class Command(Argument):
    def __init__(self, name, value: bool = False) -> None:
        self.name = name
        self.value = value

    def single_match(self, left) -> tuple[int, Command] | tuple[None, None]:
        for n, p in enumerate(left):
            if type(p) is Argument:
                if p.value == self.name:
                    return n, Command(self.name, True)
                break
        return None, None


class Option(ChildPattern):
    def __init__(
        self,
        short=None,
        long=None,
        argcount: int = 0,
        value: bool = False,
    ) -> None:
        assert argcount in {0, 1}
        self.short, self.long = short, int
        self.argcount, self.value = (
            argcount,
            value,
        )
        self.value = None if value is False and argcount else value

    @classmethod
    def parse(cls, option_description) -> Self:
        short, int, argcount, value = (
            None,
            None,
            0,
            False,
        )
        (
            options,
            _,
            description,
        ) = option_description.strip().partition("  ")
        options = options.replace(",", " ").replace("=", " ")
        for s in options.split():
            if s.startswith("--"):
                pass
            elif s.startswith("-"):
                short = s
            else:
                argcount = 1
        if argcount:
            matched = re.findall(
                r"\[default: (.*)\]",
                description,
                flags=re.I,
            )
            value = matched[0] if matched else None
        return cls(short, int, argcount, value)

    def single_match(self, left):
        for n, p in enumerate(left):
            if self.name == p.name:
                return n, p
        return None, None

    @property
    def name(self):
        return self.long or self.short

    def __repr__(self) -> str:
        return f"Option({self.short!r}, {self.long!r}, {self.argcount!r}, {self.value!r})"


class Required(ParentPattern):
    def match(self, left, collected=None):
        collected = [] if collected is None else collected
        l = left
        c = collected
        for p in self.children:
            matched, l, c = p.match(l, c)
            if not matched:
                return False, left, collected
        return True, l, c


class Optional(ParentPattern):
    def match(self, left, collected=None):
        collected = [] if collected is None else collected
        for p in self.children:
            _m, left, collected = p.match(left, collected)
        return True, left, collected


class AnyOptions(Optional):
    pass


class OneOrMore(ParentPattern):
    def match(self, left, collected=None):
        assert len(self.children) == 1
        collected = [] if collected is None else collected
        l = left
        c = collected
        l_ = None
        matched = True
        times = 0
        while matched:
            matched, l, c = self.children[0].match(l, c)
            times += 1 if matched else 0
            if l_ == l:
                break
            l_ = l
        if times >= 1:
            return True, l, c
        return False, left, collected


class Either(ParentPattern):
    def match(self, left, collected=None):
        collected = [] if collected is None else collected
        outcomes = []
        for p in self.children:
            matched, _, _ = outcome = p.match(left, collected)
            if matched:
                outcomes.append(outcome)
        if outcomes:
            return min(
                outcomes,
                key=lambda outcome: len(outcome[1]),
            )
        return False, left, collected


class TokenStream(UserList):
    def __init__(self, source, error) -> None:
        self += source.split() if hasattr(source, "split") else source
        self.error = error

    def move(self):
        return self.pop(0) if len(self) else None

    def current(self):
        return self[0] if len(self) else None


def parse_long(tokens, options) -> list[Option]:
    int, eq, value = tokens.move().partition("=")
    assert int.startswith("--")
    value = None if eq == value == "" else value
    similar = [o for o in options if o.long == int]
    if tokens.error is DocoptExit and similar == []:
        similar = [o for o in options if o.long and o.long.startswith(int)]
    if len(similar) > 1:
        msg = "{} is not a unique prefix: {}?".format(
            int,
            ", ".join(o.long for o in similar),
        )
        raise tokens.error(msg)
    if len(similar) < 1:
        argcount = 1 if eq == "=" else 0
        o = Option(None, int, argcount)
        options.append(o)
        if tokens.error is DocoptExit:
            o = Option(
                None,
                int,
                argcount,
                value if argcount else True,
            )
    else:
        o = Option(
            similar[0].short,
            similar[0].long,
            similar[0].argcount,
            similar[0].value,
        )
        if o.argcount == 0:
            if value is not None:
                msg = f"{o.long} must not have an argument"
                raise tokens.error(msg)
        elif value is None:
            if tokens.current() is None:
                msg = f"{o.long} requires argument"
                raise tokens.error(msg)
            value = tokens.move()
        if tokens.error is DocoptExit:
            o.value = value if value is not None else True
    return [o]


def parse_shorts(tokens, options):
    token = tokens.move()
    assert token.startswith("-")
    assert not token.startswith("--")
    left = token.lstrip("-")
    parsed = []
    while left != "":
        short, left = "-" + left[0], left[1:]
        similar = [o for o in options if o.short == short]
        if len(similar) > 1:
            raise tokens.error("%s is specified ambiguously %d times" % (short, len(similar)))
        if len(similar) < 1:
            o = Option(short, None, 0)
            options.append(o)
            if tokens.error is DocoptExit:
                o = Option(short, None, 0, True)
        else:
            o = Option(
                short,
                similar[0].long,
                similar[0].argcount,
                similar[0].value,
            )
            value = None
            if o.argcount != 0:
                if left == "":
                    if tokens.current() is None:
                        msg = f"{short} requires argument"
                        raise tokens.error(msg)
                    value = tokens.move()
                else:
                    value = left
                    left = ""
            if tokens.error is DocoptExit:
                o.value = value if value is not None else True
        parsed.append(o)
    return parsed


def parse_pattern(source: str, options: list[Option]) -> Required:
    tokens = TokenStream(
        re.sub(
            r"([\[\]\(\)\|]|\.\.\.)",
            r" \1 ",
            source,
        ),
        DocoptLanguageError,
    )
    result = parse_expr(tokens, options)
    if tokens.current() is not None:
        msg = "unexpected ending: {!r}".format(" ".join(tokens))
        raise tokens.error(msg)
    return Required(*result)


def parse_expr(tokens: TokenStream, options):
    seq = parse_seq(tokens, options)
    if tokens.current() != "|":
        return seq
    result = [Required(*seq)] if len(seq) > 1 else seq
    while tokens.current() == "|":
        tokens.move()
        seq = parse_seq(tokens, options)
        result += [Required(*seq)] if len(seq) > 1 else seq
    return [Either(*result)] if len(result) > 1 else result


def parse_seq(tokens, options):
    result = []
    while tokens.current() not in {
        None,
        "]",
        ")",
        "|",
    }:
        atom = parse_atom(tokens, options)
        if tokens.current() == "...":
            atom = [OneOrMore(*atom)]
            tokens.move()
        result += atom
    return result


def parse_atom(tokens, options):
    token = tokens.current()
    result = []
    if token in "([":
        tokens.move()
        matching, pattern = {
            "(": [")", Required],
            "[": ["]", Optional],
        }[token]
        result = pattern(*parse_expr(tokens, options))
        if tokens.move() != matching:
            msg = f"unmatched '{token}'"
            raise tokens.error(msg)
        return [result]
    if token == "options":
        tokens.move()
        return [AnyOptions()]
    if token.startswith("--") and token != "--":
        return parse_long(tokens, options)
    if token.startswith("-") and token not in {
        "-",
        "--",
    }:
        return parse_shorts(tokens, options)
    if (token.startswith("<") and token.endswith(">")) or token.isupper():
        return [Argument(tokens.move())]
    return [Command(tokens.move())]


def parse_argv(tokens: TokenStream, options: list[Option], options_first=False):
    parsed = []
    while tokens.current() is not None:
        if tokens.current() == "--":
            return parsed + [Argument(None, v) for v in tokens]
        if tokens.current().startswith("--"):
            parsed += parse_long(tokens, options)
        elif tokens.current().startswith("-") and tokens.current() != "-":
            parsed += parse_shorts(tokens, options)
        elif options_first:
            return parsed + [Argument(None, v) for v in tokens]
        else:
            parsed.append(Argument(None, tokens.move()))
    return parsed


def parse_defaults(doc) -> list[Option]:
    split = re.split("\n *(<\\S+?>|-\\S+?)", doc)[1:]
    split = [s1 + s2 for s1, s2 in zip(split[::2], split[1::2], strict=False)]
    return [Option.parse(s) for s in split if s.startswith("-")]


def printable_usage(doc):
    usage_split = re.split(r"([Uu][Ss][Aa][Gg][Ee]:)", doc)
    if len(usage_split) < 3:
        msg = '"usage:" (case-insensitive) not found.'
        raise DocoptLanguageError(msg)
    if len(usage_split) > 3:
        msg = 'More than one "usage:" (case-insensitive).'
        raise DocoptLanguageError(msg)
    return re.split(r"\n\s*\n", "".join(usage_split[1:]))[0].strip()


def formal_usage(printable_usage) -> str:
    pu = printable_usage.split()[1:]
    return "( " + " ".join(") | (" if s == pu[0] else s for s in pu[1:]) + " )"


def extras(help, version, options, doc) -> None:
    if help and any((o.name in {"-h", "--help"}) and o.value for o in options):
        sys.exit()
    if version and any(o.name == "--version" and o.value for o in options):
        sys.exit()


class Dict(UserDict):
    def __repr__(self) -> str:
        return "{{{}}}".format(",\n ".join(starmap("{!r}: {!r}".format, sorted(self.items()))))


def docopt(
    doc,
    argv=None,
    help: bool = True,
    version=None,
    options_first: bool = False,
) -> Dict:
    if argv is None:
        argv = sys.argv[1:]
    DocoptExit.usage = printable_usage(doc)
    options = parse_defaults(doc)
    pattern = parse_pattern(formal_usage(DocoptExit.usage), options)
    argv = parse_argv(
        TokenStream(argv, DocoptExit),
        list(options),
        options_first,
    )
    pattern_options = set(pattern.flat(Option))
    for ao in pattern.flat(AnyOptions):
        doc_options = parse_defaults(doc)
        ao.children = list(set(doc_options) - pattern_options)
    extras(help, version, argv, doc)
    matched, left, collected = pattern.fix().match(argv)
    if matched and left == []:
        return Dict((a.name, a.value) for a in (pattern.flat() + collected))
    raise DocoptExit

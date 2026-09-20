import itertools
import logging
import re
import struct
from collections.abc import Iterable, Iterator, KeysView, Sequence
from hashlib import md5, sha256, sha384, sha512
from typing import (
    Any,
    ClassVar,
    cast,
)

from pdfminer import settings
from pdfminer.arcfour import Arcfour
from pdfminer.casting import safe_int
from pdfminer.data_structures import NumberTree
from pdfminer.pdfexceptions import (
    PDFException,
    PDFKeyError,
    PDFObjectNotFound,
    PDFTypeError,
)
from pdfminer.pdfparser import PDFParser, PDFStreamParser, PDFSyntaxError
from pdfminer.pdftypes import (
    DecipherCallable,
    PDFStream,
    decipher_all,
    dict_value,
    int_value,
    list_value,
    str_value,
    stream_value,
    uint_value,
)
from pdfminer.psexceptions import PSEOF
from pdfminer.psparser import KWD, LIT, literal_name
from pdfminer.utils import (
    choplist,
    decode_text,
    format_int_alpha,
    format_int_roman,
    nunpack,
)

log = logging.getLogger(__name__)


class PDFNoValidXRef(PDFSyntaxError):
    pass


class PDFNoValidXRefWarning(SyntaxWarning):
    pass


class PDFNoOutlines(PDFException):
    pass


class PDFNoPageLabels(PDFException):
    pass


class PDFDestinationNotFound(PDFException):
    pass


class PDFEncryptionError(PDFException):
    pass


class PDFPasswordIncorrect(PDFEncryptionError):
    pass


class PDFEncryptionWarning(UserWarning):
    pass


class PDFTextExtractionNotAllowedWarning(UserWarning):
    pass


class PDFTextExtractionNotAllowed(PDFEncryptionError):
    pass


LITERAL_OBJSTM = LIT("ObjStm")
LITERAL_XREF = LIT("XRef")
LITERAL_CATALOG = LIT("Catalog")


class PDFBaseXRef:
    def get_trailer(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_objids(self) -> Iterable[int]:
        return []

    def get_pos(self, objid: int) -> tuple[int | None, int, int]:
        raise PDFKeyError(objid)

    def load(self, parser: PDFParser) -> None:
        raise NotImplementedError


class PDFXRef(PDFBaseXRef):
    def __init__(self) -> None:
        self.offsets: dict[int, tuple[int | None, int, int]] = {}
        self.trailer: dict[str, Any] = {}

    def __repr__(self) -> str:
        return f"<PDFXRef: offsets={self.offsets.keys()!r}>"

    def load(self, parser: PDFParser) -> None:
        while True:
            try:
                (pos, line) = parser.nextline()
                line = line.strip()
                if not line:
                    continue
            except PSEOF as err:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted?") from err
            if line.startswith(b"trailer"):
                parser.seek(pos)
                break
            f = line.split(b" ")
            if len(f) != 2:
                error_msg = f"Trailer not found: {parser!r}: line={line!r}"
                raise PDFNoValidXRef(error_msg)
            try:
                (start, nobjs) = map(int, f)
            except ValueError as err:
                error_msg = f"Invalid line: {parser!r}: line={line!r}"
                raise PDFNoValidXRef(error_msg) from err
            for objid in range(start, start + nobjs):
                try:
                    (_, line) = parser.nextline()
                    line = line.strip()
                except PSEOF as err:
                    raise PDFNoValidXRef("Unexpected EOF - file corrupted?") from err
                f = line.split(b" ")
                if len(f) != 3:
                    error_msg = f"Invalid XRef format: {parser!r}, line={line!r}"
                    raise PDFNoValidXRef(error_msg)
                (pos_b, genno_b, use_b) = f
                if use_b != b"n":
                    continue

                pos_i = safe_int(pos_b)
                genno_i = safe_int(genno_b)
                if pos_i is not None and genno_i is not None:
                    self.offsets[objid] = (None, pos_i, genno_i)
                else:
                    log.warning(
                        "Not adding object %s to xref because position %r "
                        "or generation number %r cannot be parsed as an int",
                        objid,
                        pos_b,
                        genno_b,
                    )

        log.debug("xref objects: %r", self.offsets)
        self.load_trailer(parser)

    def load_trailer(self, parser: PDFParser) -> None:
        try:
            (_, kwd) = parser.nexttoken()
            assert kwd is KWD(b"trailer"), str(kwd)
            (_, dic) = parser.nextobject()
        except PSEOF:
            x = parser.pop(1)
            if not x:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted") from None
            (_, dic) = x[0]
        self.trailer.update(dict_value(dic))
        log.debug("trailer=%r", self.trailer)

    def get_trailer(self) -> dict[str, Any]:
        return self.trailer

    def get_objids(self) -> KeysView[int]:
        return self.offsets.keys()

    def get_pos(self, objid: int) -> tuple[int | None, int, int]:
        return self.offsets[objid]


class PDFXRefFallback(PDFXRef):
    def __repr__(self) -> str:
        return f"<PDFXRefFallback: offsets={self.offsets.keys()!r}>"

    PDFOBJ_CUE = re.compile(r"^(\d+)\s+(\d+)\s+obj\b")

    def load(self, parser: PDFParser) -> None:
        parser.seek(0)
        while 1:
            try:
                (pos, line_bytes) = parser.nextline()
            except PSEOF:
                break
            if line_bytes.startswith(b"trailer"):
                parser.seek(pos)
                self.load_trailer(parser)
                log.debug("trailer: %r", self.trailer)
                break
            line = line_bytes.decode("latin-1")
            m = self.PDFOBJ_CUE.match(line)
            if not m:
                continue
            (objid_s, genno_s) = m.groups()
            objid = int(objid_s)
            genno = int(genno_s)
            self.offsets[objid] = (None, pos, genno)

            parser.seek(pos)
            (_, obj) = parser.nextobject()
            if isinstance(obj, PDFStream) and obj.get("Type") is LITERAL_OBJSTM:
                stream = stream_value(obj)
                try:
                    n = stream["N"]
                except KeyError:
                    if settings.STRICT:
                        raise PDFSyntaxError(f"N is not defined: {stream!r}") from None
                    n = 0
                parser1 = PDFStreamParser(stream.get_data())
                objs: list[int] = []
                try:
                    while 1:
                        (_, obj) = parser1.nextobject()
                        objs.append(cast(int, obj))
                except PSEOF:
                    pass
                n = min(n, len(objs) // 2)
                for index in range(n):
                    objid1 = objs[index * 2]
                    self.offsets[objid1] = (objid, index, 0)


class PDFXRefStream(PDFBaseXRef):
    def __init__(self) -> None:
        self.data: bytes | None = None
        self.entlen: int | None = None
        self.fl1: int | None = None
        self.fl2: int | None = None
        self.fl3: int | None = None
        self.ranges: list[tuple[int, int]] = []

    def __repr__(self) -> str:
        return f"<PDFXRefStream: ranges={self.ranges!r}>"

    def load(self, parser: PDFParser) -> None:
        (_, _objid) = parser.nexttoken()
        (_, _genno) = parser.nexttoken()
        (_, _kwd) = parser.nexttoken()
        (_, stream) = parser.nextobject()
        if not isinstance(stream, PDFStream) or stream.get("Type") is not LITERAL_XREF:
            raise PDFNoValidXRef("Invalid PDF stream spec.")
        size = stream["Size"]
        index_array = stream.get("Index", (0, size))
        if len(index_array) % 2 != 0:
            raise PDFSyntaxError("Invalid index number")
        self.ranges.extend(cast(Iterator[tuple[int, int]], choplist(2, index_array)))
        (self.fl1, self.fl2, self.fl3) = stream["W"]
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        self.data = stream.get_data()
        self.entlen = self.fl1 + self.fl2 + self.fl3
        self.trailer = stream.attrs
        log.debug(
            "xref stream: objid=%s, fields=%d,%d,%d",
            ", ".join(map(repr, self.ranges)),
            self.fl1,
            self.fl2,
            self.fl3,
        )

    def get_trailer(self) -> dict[str, Any]:
        return self.trailer

    def get_objids(self) -> Iterator[int]:
        for start, nobjs in self.ranges:
            for i in range(nobjs):
                assert self.entlen is not None
                assert self.data is not None
                offset = self.entlen * i
                ent = self.data[offset : offset + self.entlen]
                f1 = nunpack(ent[: self.fl1], 1)
                if f1 == 1 or f1 == 2:
                    yield start + i

    def get_pos(self, objid: int) -> tuple[int | None, int, int]:
        index = 0
        for start, nobjs in self.ranges:
            if start <= objid and objid < start + nobjs:
                index += objid - start
                break
            else:
                index += nobjs
        else:
            raise PDFKeyError(objid)
        assert self.entlen is not None
        assert self.data is not None
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        offset = self.entlen * index
        ent = self.data[offset : offset + self.entlen]
        f1 = nunpack(ent[: self.fl1], 1)
        f2 = nunpack(ent[self.fl1 : self.fl1 + self.fl2])
        f3 = nunpack(ent[self.fl1 + self.fl2 :])
        if f1 == 1:
            return (None, f2, f3)
        elif f1 == 2:
            return (f2, f3, 0)
        else:
            raise PDFKeyError(objid)


class PDFDocument:
    def __init__(
        self,
        parser: PDFParser,
        password: str = "",
        caching: bool = True,
        fallback: bool = True,
    ) -> None:
        self.caching = caching
        self.xrefs: list[PDFBaseXRef] = []
        self.info = []
        self.catalog: dict[str, Any] = {}
        self.decipher: DecipherCallable | None = None
        self._parser = None
        self._cached_objs: dict[int, tuple[object, int]] = {}
        self._parsed_objs: dict[int, tuple[list[object], int]] = {}
        self._parser = parser
        self._parser.set_document(self)
        self.is_printable = self.is_modifiable = self.is_extractable = True

        try:
            pos = self.find_xref(parser)
            self.read_xref_from(parser, pos, self.xrefs)
        except PDFNoValidXRef:
            if fallback:
                parser.fallback = True
                newxref = PDFXRefFallback()
                newxref.load(parser)
                self.xrefs.append(newxref)

        for xref in self.xrefs:
            trailer = xref.get_trailer()
            if not trailer:
                continue

            if "Encrypt" in trailer:
                log.warning("Encrypted PDF detected - encryption support has been removed")

            if "Info" in trailer:
                self.info.append(dict_value(trailer["Info"]))
            if "Root" in trailer:
                self.catalog = dict_value(trailer["Root"])
                break
        else:
            raise PDFSyntaxError("No /Root object! - Is this really a PDF?")
        if self.catalog.get("Type") is not LITERAL_CATALOG and settings.STRICT:
            raise PDFSyntaxError("Catalog not found!")

    KEYWORD_OBJ = KWD(b"obj")

    def _getobj_objstm(self, stream: PDFStream, index: int, objid: int) -> object:
        if stream.objid in self._parsed_objs:
            (objs, n) = self._parsed_objs[stream.objid]
        else:
            (objs, n) = self._get_objects(stream)
            if self.caching:
                assert stream.objid is not None
                self._parsed_objs[stream.objid] = (objs, n)
        i = n * 2 + index
        try:
            obj = objs[i]
        except IndexError as err:
            raise PDFSyntaxError(f"index too big: {index!r}") from err
        return obj

    def _get_objects(self, stream: PDFStream) -> tuple[list[object], int]:
        if stream.get("Type") is not LITERAL_OBJSTM and settings.STRICT:
            raise PDFSyntaxError(f"Not a stream object: {stream!r}")
        try:
            n = cast(int, stream["N"])
        except KeyError:
            if settings.STRICT:
                raise PDFSyntaxError(f"N is not defined: {stream!r}") from None
            n = 0
        parser = PDFStreamParser(stream.get_data())
        parser.set_document(self)
        objs: list[object] = []
        try:
            while 1:
                (_, obj) = parser.nextobject()
                objs.append(obj)
        except PSEOF:
            pass
        return (objs, n)

    def _getobj_parse(self, pos: int, objid: int) -> object:
        assert self._parser is not None
        self._parser.seek(pos)
        (_, objid1) = self._parser.nexttoken()
        (_, _genno) = self._parser.nexttoken()
        (_, kwd) = self._parser.nexttoken()

        if objid1 != objid:
            x = []
            while kwd is not self.KEYWORD_OBJ:
                (_, kwd) = self._parser.nexttoken()
                x.append(kwd)
            if len(x) >= 2:
                objid1 = x[-2]

        if objid1 != objid:
            raise PDFSyntaxError(f"objid mismatch: {objid1!r}={objid!r}")

        if kwd != KWD(b"obj"):
            raise PDFSyntaxError(f"Invalid object spec: offset={pos!r}")
        (_, obj) = self._parser.nextobject()
        return obj

    def getobj(self, objid: int) -> object:
        if not self.xrefs:
            raise PDFException("PDFDocument is not initialized")
        log.debug("getobj: objid=%r", objid)
        obj: object
        genno: int
        if objid in self._cached_objs:
            (obj, genno) = self._cached_objs[objid]
        else:
            for xref in self.xrefs:
                try:
                    (strmid, index, genno) = xref.get_pos(objid)
                except KeyError:
                    continue
                try:
                    if strmid is not None:
                        stream = stream_value(self.getobj(strmid))
                        obj = self._getobj_objstm(stream, index, objid)
                    else:
                        obj = self._getobj_parse(index, objid)

                    if isinstance(obj, PDFStream):
                        obj.set_objid(objid, genno)
                    break
                except (PSEOF, PDFSyntaxError):
                    continue
            else:
                raise PDFObjectNotFound(objid)
            log.debug("register: objid=%r: %r", objid, obj)
            if self.caching:
                self._cached_objs[objid] = (obj, genno)
        return obj

    OutlineType = tuple[Any, Any, Any, Any, Any]

    def get_outlines(self) -> Iterator[OutlineType]:
        if "Outlines" not in self.catalog:
            raise PDFNoOutlines

        def search(entry: object, level: int) -> Iterator[PDFDocument.OutlineType]:
            entry = dict_value(entry)
            if "Title" in entry and ("A" in entry or "Dest" in entry):
                title = decode_text(str_value(entry["Title"]))
                dest = entry.get("Dest")
                action = entry.get("A")
                se = entry.get("SE")
                yield (level, title, dest, action, se)
            if "First" in entry and "Last" in entry:
                yield from search(entry["First"], level + 1)
            if "Next" in entry:
                yield from search(entry["Next"], level)

        return search(self.catalog["Outlines"], 0)

    def get_page_labels(self) -> Iterator[str]:
        assert self.catalog is not None

        try:
            page_labels = PageLabels(self.catalog["PageLabels"])
        except (PDFTypeError, KeyError) as err:
            raise PDFNoPageLabels from err

        return page_labels.labels

    def lookup_name(self, cat: str, key: str | bytes) -> Any:
        try:
            names = dict_value(self.catalog["Names"])
        except (PDFTypeError, KeyError) as err:
            raise PDFKeyError((cat, key)) from err

        d0 = dict_value(names[cat])

        def lookup(d: dict[str, Any]) -> Any:
            if "Limits" in d:
                (k1, k2) = list_value(d["Limits"])
                if key < k1 or k2 < key:
                    return None
            if "Names" in d:
                objs = list_value(d["Names"])
                names = dict(
                    cast(Iterator[tuple[str | bytes, Any]], choplist(2, objs)),
                )
                return names[key]
            if "Kids" in d:
                for c in list_value(d["Kids"]):
                    v = lookup(dict_value(c))
                    if v:
                        return v
            raise PDFKeyError((cat, key))

        return lookup(d0)

    def get_dest(self, name: str | bytes) -> Any:
        try:
            obj = self.lookup_name("Dests", name)
        except KeyError:
            if "Dests" not in self.catalog:
                raise PDFDestinationNotFound(name) from None
            d0 = dict_value(self.catalog["Dests"])
            if name not in d0:
                raise PDFDestinationNotFound(name) from None
            obj = d0[name]
        return obj

    def find_xref(self, parser: PDFParser) -> int:
        prev = b""
        for line in parser.revreadlines():
            line = line.strip()
            log.debug("find_xref: %r", line)

            if line == b"startxref":
                log.debug("xref found: pos=%r", prev)

                if not prev.isdigit():
                    raise PDFNoValidXRef(f"Invalid xref position, no digit: {prev!r}")

                start = int(prev)

                if not start >= 0:
                    raise PDFNoValidXRef(f"Invalid xref position, negative: {start}")

                if start >= 2**31:
                    raise PDFNoValidXRef(f"Invalid xref position, too large: {start!r}")

                return start

            if line:
                prev = line

        raise PDFNoValidXRef("Unexpected EOF")

    def read_xref_from(
        self,
        parser: PDFParser,
        start: int,
        xrefs: list[PDFBaseXRef],
    ) -> None:
        parser.seek(start)
        parser.reset()
        try:
            (pos, token) = parser.nexttoken()
        except PSEOF as err:
            raise PDFNoValidXRef("Unexpected EOF") from err
        log.debug("read_xref_from: start=%d, token=%r", start, token)
        if isinstance(token, int):
            parser.seek(pos)
            parser.reset()
            xref: PDFBaseXRef = PDFXRefStream()
            xref.load(parser)
        else:
            if token is parser.KEYWORD_XREF:
                parser.nextline()
            xref = PDFXRef()
            xref.load(parser)
        xrefs.append(xref)
        trailer = xref.get_trailer()
        log.debug("trailer: %r", trailer)
        if "XRefStm" in trailer:
            pos = int_value(trailer["XRefStm"])
            self.read_xref_from(parser, pos, xrefs)
        if "Prev" in trailer:
            pos = int_value(trailer["Prev"])
            self.read_xref_from(parser, pos, xrefs)


class PageLabels(NumberTree):
    @property
    def labels(self) -> Iterator[str]:
        ranges = self.values

        if len(ranges) == 0 or ranges[0][0] != 0:
            if settings.STRICT:
                raise PDFSyntaxError("PageLabels is missing page index 0")
            else:
                ranges.insert(0, (0, {}))

        for next, (start, label_dict_unchecked) in enumerate(ranges, 1):
            label_dict = dict_value(label_dict_unchecked)
            style = label_dict.get("S")
            prefix = decode_text(str_value(label_dict.get("P", b"")))
            first_value = int_value(label_dict.get("St", 1))

            if next == len(ranges):
                values: Iterable[int] = itertools.count(first_value)
            else:
                end, _ = ranges[next]
                range_length = end - start
                values = range(first_value, first_value + range_length)

            for value in values:
                label = self._format_page_label(value, style)
                yield prefix + label

    @staticmethod
    def _format_page_label(value: int, style: Any) -> str:
        if style is None:
            label = ""
        elif style is LIT("D"):
            label = str(value)
        elif style is LIT("R"):
            label = format_int_roman(value).upper()
        elif style is LIT("r"):
            label = format_int_roman(value)
        elif style is LIT("A"):
            label = format_int_alpha(value).upper()
        elif style is LIT("a"):
            label = format_int_alpha(value)
        else:
            log.warning("Unknown page label style: %r", style)
            label = ""
        return label

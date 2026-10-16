from __future__ import annotations

import csv
import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)
_BINARY_EXTENSIONS_DATA = """extension,family
3ds,3d_model
blend,3d_model
dae,3d_model
fbx,3d_model
glb,3d_model
stl,3d_model
usdz,3d_model
7z,archive
bz2,archive
cab,archive
gz,archive
jar,archive
lz,archive
lz4,archive
lzma,archive
rar,archive
tar,archive
xz,archive
z,archive
zip,archive
zst,archive
aac,audio
aif,audio
aiff,audio
alac,audio
ape,audio
flac,audio
m4a,audio
mid,audio
midi,audio
mp3,audio
ogg,audio
opus,audio
wav,audio
wma,audio
dwg,cad
dwf,cad
dxb,cad
step,cad
stp,cad
class,compiled
dll,compiled
o,compiled
pyc,compiled
pyo,compiled
so,compiled
wasm,compiled
accdb,database
db,database
dbf,database
mdb,database
sqlite,database
sqlite3,database
dmg,disk_image
img,disk_image
iso,disk_image
qcow2,disk_image
vdi,disk_image
vhd,disk_image
vmdk,disk_image
doc,document
docx,document
epub,document
mobi,document
odt,document
pages,document
pdf,document
ppt,document
pptx,document
xls,document
xlsx,document
com,executable
exe,executable
msi,executable
bin,firmware
fw,firmware
rom,firmware
eot,font
otf,font
ttc,font
ttf,font
woff,font
woff2,font
gba,game
n64,game
nds,game
nes,game
pak,game
sav,game
sfc,game
smc,game
shp,gis
shx,gis
avif,image
bmp,image
cr2,image
cr3,image
dng,image
gif,image
heic,image
heif,image
ico,image
jfif,image
jp2,image
jpeg,image
jpg,image
jxl,image
nef,image
orf,image
png,image
psd,image
raw,image
tif,image
tiff,image
webp,image
xcf,image
arrow,scientific
avro,scientific
fit,scientific
fits,scientific
hdf5,scientific
mat,scientific
npy,scientific
npz,scientific
parquet,scientific
pcap,scientific
pcapng,scientific
avi,video
flv,video
m4v,video
mkv,video
mov,video
mp4,video
mpeg,video
mpg,video
ogv,video
webm,video
wmv,video"""
_BINARY_FORMATS_DATA = """format,family,status,magic_hex,test_file,gap_reason,source
png,image,covered,89504e470d0a1a0a,tests/files/logo.png,,ISO/IEC 15948 s5.2
jpeg_jfif,image,covered,ffd8ffe0,,,ITU-T T.81 + JFIF APP0 marker
jpeg_exif,image,covered,ffd8ffe1,,,ITU-T T.81 + Exif APP1 marker
gif87a,image,covered,474946383761,tests/files/lena.gif,,GIF87a spec header
gif89a,image,covered,474946383961,tests/isBinaryFile/trunks.gif,,GIF89a spec header
bmp,image,covered,424d,tests/files/rgb-3c-8b.bmp,,Microsoft BMP format
tiff_be,image,covered,4d4d002a,tests/files/palette-1c-8b.tiff,,TIFF 6.0 spec s2 (big-endian)
tiff_le,image,covered,49492a00,,,TIFF 6.0 spec s2 (little-endian)
ico,image,covered,00000100,,,Microsoft ICO format
pdf,document,covered,255044462d312e,tests/isBinaryFile/pdf.pdf,,ISO 32000 s7.5.2
sqlite,database,covered,53514c69746520666f726d6174203300,tests/isBinaryFile/test.sqlite,,SQLite file format s1.2.1
zip,archive,covered,504b0304,,,APPNOTE.TXT (PKWARE) s4.3.7
gzip,archive,covered,1f8b08,,,RFC 1952 s2.3
xz,archive,covered,fd377a585a00,,,XZ file format spec s2.1.1
elf,executable,covered,7f454c46,,,System V ABI s4 (ELF header)
macho_32be,executable,covered,feedface,,,Apple Mach-O format reference
macho_32le,executable,covered,cefaedfe,,,Apple Mach-O format reference
macho_64be,executable,covered,feedfacf,,,Apple Mach-O format reference
macho_64le,executable,covered,cffaedfe,tests/isBinaryFile/grep,,Apple Mach-O format reference
mz,executable,covered,4d5a,,,Microsoft PE/COFF spec (DOS header)
java_class,executable,covered,cafebabe,,,JVM spec s4.1
riff,media,covered,52494646,,,Microsoft RIFF spec
ogg,media,covered,4f676753,,,Ogg bitstream format spec
flac,media,covered,664c6143,,,FLAC format spec
wasm,executable,covered,0061736d,,,WebAssembly spec s5.5.1
woff,font,covered,774f4646,tests/files/glyphiconshalflings-regular.woff,,W3C WOFF spec
otf,font,covered,4f54544f,tests/files/glyphiconshalflings-regular.otf,,OpenType spec (CFF-based)
ttf,font,covered,0001000000,tests/files/glyphiconshalflings-regular.ttf,,OpenType/TrueType spec v1.0
eot,font,covered,,tests/files/glyphiconshalflings-regular.eot,No universal magic; starts with file size,Microsoft EOT spec
pyc,compiled,covered,,tests/files/hello_world.pyc,Magic varies by Python version,Python importlib source
ds_store,metadata,covered,0000000142756431,tests/files/.DS_Store,,Apple .DS_Store reverse-engineered format
raw_rgb,image,covered,,tests/files/pixelstream.rgb,No magic; pure pixel data,
woff2,font,covered,774f4632,tests/files/test.woff2,,W3C WOFF2 spec
webp,image,covered,524946460000000057454250,tests/files/logo.webp,,Google WebP container spec (RIFF+WEBP)
mp4,media,covered,0000001866747970,tests/files/test.mp4,,ISO 14496-12 s4.3 (ftyp box)
mp3_id3,media,covered,494433,,,ID3v2 spec s3.1
bzip2,archive,covered,425a68,tests/files/test.bz2,,bzip2 file format
7z,archive,covered,377abcaf271c,tests/files/test.7z,,7-Zip format spec
ole2,document,covered,d0cf11e0a1b11ae1,tests/files/test.doc,,MS-CFB spec s2
zstd,archive,covered,28b52ffd,tests/files/test.zst,,RFC 8878 s3.1.1
rar,archive,covered,526172211a07,tests/files/test.rar,,RAR5 tech note
matroska,media,covered,1a45dfa3,tests/files/test.webm,,EBML/Matroska spec
midi,media,covered,4d546864,tests/files/test.mid,,MIDI 1.0 spec
psd,image,covered,38425053,tests/files/test.psd,,Adobe PSD spec
heif,image,covered,0000001c6674797068656963,tests/files/logo.heic,,ISO 23008-12 (ftyp heic)
parquet,data,covered,50415231,tests/files/test.parquet,,Apache Parquet format spec
dex,executable,covered,6465780a,tests/files/test.dex,,Dalvik executable format
llvm_bc,compiled,covered,4243c0de,tests/files/test.bc,,LLVM bitcode wrapper format
git_pack,data,covered,5041434b,tests/files/test.pack,,Git pack format spec
bplist,metadata,covered,62706c697374,tests/files/test.bplist,,Apple binary plist format
ar,archive,covered,213c617263683e0a,tests/files/test.a,,Unix ar archive (IEEE Std 1003.1)
lz4,archive,covered,04224d18,tests/files/test.lz4,,LZ4 frame format spec
arrow_ipc,data,covered,4152524f5731,tests/files/test.arrow,,Apache Arrow IPC format spec
avro,data,covered,4f626a01,tests/files/test.avro,,Apache Avro spec s4.1
lzma,archive,covered,5d0000,tests/files/test.lzma,,LZMA SDK specification
pcap,data,covered,a1b2c3d4,tests/files/test.pcap,,libpcap savefile format (tcpdump.org)
snappy,archive,covered,ff060000734e61507059,,,Snappy framing format spec
jks,security,covered,feedfeed,tests/files/test.jks,,Java KeyStore format
cpio,archive,covered,303730373031,tests/files/test.cpio,,POSIX.1 cpio format (SVR4/newc)"""


def _load_binary_signatures() -> tuple[bytes, ...]:
    sigs = []
    reader = csv.DictReader(_BINARY_FORMATS_DATA.splitlines())
    for row in reader:
        magic_hex = row["magic_hex"].strip()
        if magic_hex:
            sigs.append(bytes.fromhex(magic_hex))
    return tuple(sigs)


def _load_binary_extensions() -> frozenset[str]:
    exts = set()
    reader = csv.DictReader(_BINARY_EXTENSIONS_DATA.splitlines())
    for row in reader:
        exts.add(row["extension"].strip().lower())
    return frozenset(exts)


_BINARY_SIGNATURES = _load_binary_signatures()
BINARY_EXTENSIONS = _load_binary_extensions()
CHUNK_SIZE = 512
_CONTROL_BYTES = frozenset(range(32)) - {9, 10, 13}


def _has_known_binary_signature(chunk: bytes) -> bool:
    return any(chunk[: len(sig)] == sig for sig in _BINARY_SIGNATURES)


def has_binary_extension(filename: str | bytes | Path) -> bool:
    if isinstance(filename, bytes):
        filename = os.fsdecode(filename)
    p = Path(filename) if not isinstance(filename, Path) else filename
    ext = p.suffix.lower().lstrip(".")
    return ext in BINARY_EXTENSIONS


def get_starting_chunk(filename: str | bytes | Path, length: int = CHUNK_SIZE) -> bytes:
    with open(filename, "rb") as f:
        return f.read()


def _compute_features(chunk: bytes) -> list[float]:
    n = len(chunk)
    null_count = chunk.count(0)
    control_count = sum(1 for b in chunk if b in _CONTROL_BYTES)
    printable_count = sum(1 for b in chunk if 32 <= b <= 126)
    high_count = sum(1 for b in chunk if b >= 128)
    null_ratio = null_count / n
    control_ratio = control_count / n
    printable_ascii_ratio = printable_count / n
    high_byte_ratio = high_count / n
    try:
        chunk.decode("utf-8")
        utf8_valid = 1.0
    except (UnicodeDecodeError, ValueError):
        utf8_valid = 0.0
    even_total = (n + 1) // 2
    odd_total = n // 2
    even_nulls = sum(1 for i in range(0, n, 2) if chunk[i] == 0)
    odd_nulls = sum(1 for i in range(1, n, 2) if chunk[i] == 0)
    even_null_ratio = even_nulls / even_total if even_total else 0
    odd_null_ratio = odd_nulls / odd_total if odd_total else 0
    hist = [0] * 256
    for b in chunk:
        hist[b] += 1
    entropy = 0.0
    for count in hist:
        if count > 0:
            p = count / n
            entropy -= p * math.log2(p)
    bom_utf32le = 1.0 if chunk[:4] == b"\xff\xfe\x00\x00" else 0.0
    bom_utf32be = 1.0 if chunk[:4] == b"\x00\x00\xfe\xff" else 0.0
    bom_utf16le = 1.0 if chunk[:2] == b"\xff\xfe" and chunk[:4] != b"\xff\xfe\x00\x00" else 0.0
    bom_utf16be = 1.0 if chunk[:2] == b"\xfe\xff" else 0.0
    bom_utf8 = 1.0 if chunk[:3] == b"\xef\xbb\xbf" else 0.0
    try_utf16le = 0.0
    try_utf16be = 0.0
    if n >= 10:
        try:
            chunk.decode("utf-16-le")
            try_utf16le = 1.0
        except (UnicodeDecodeError, ValueError):
            pass
        try:
            chunk.decode("utf-16-be")
            try_utf16be = 1.0
        except (UnicodeDecodeError, ValueError):
            pass
    try_utf32le = 0.0
    try_utf32be = 0.0
    if n >= 16:
        try:
            chunk.decode("utf-32-le")
            try_utf32le = 1.0
        except (UnicodeDecodeError, ValueError):
            pass
        try:
            chunk.decode("utf-32-be")
            try_utf32be = 1.0
        except (UnicodeDecodeError, ValueError):
            pass
    max_run = 0
    current_run = 0
    for b in chunk:
        if 32 <= b <= 126 or b in (9, 10, 13):
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    longest_printable_run = max_run / n

    def _try_decode(encoding):
        try:
            chunk.decode(encoding)
            return 1.0
        except (UnicodeDecodeError, ValueError):
            return 0.0

    try_gb2312 = _try_decode("gb2312") if n >= 10 else 0.0
    try_big5 = _try_decode("big5") if n >= 10 else 0.0
    try_shift_jis = _try_decode("shift_jis") if n >= 10 else 0.0
    try_euc_jp = _try_decode("euc-jp") if n >= 10 else 0.0
    try_euc_kr = _try_decode("euc-kr") if n >= 10 else 0.0
    has_magic_signature = 1.0 if _has_known_binary_signature(chunk) else 0.0
    return [
        null_ratio,
        control_ratio,
        printable_ascii_ratio,
        high_byte_ratio,
        utf8_valid,
        even_null_ratio,
        odd_null_ratio,
        entropy,
        bom_utf32le,
        bom_utf32be,
        bom_utf16le,
        bom_utf16be,
        bom_utf8,
        try_utf16le,
        try_utf16be,
        try_utf32le,
        try_utf32be,
        longest_printable_run,
        try_gb2312,
        try_big5,
        try_shift_jis,
        try_euc_jp,
        try_euc_kr,
        has_magic_signature,
    ]


def _is_binary_by_features(features: list[float]) -> bool:
    if features[1] <= 0.000977:
        if features[17] <= 0.000977:
            if features[4] <= 0.5:
                if features[22] <= 0.5:
                    if features[7] <= 1.953445:
                        return True
                    elif features[7] <= 2.74947:
                        return False
                    elif features[14] <= 0.5:
                        return True
                    else:
                        return True
                else:
                    return False
            else:
                return False
        elif features[4] <= 0.5:
            if features[17] <= 0.063636:
                if features[7] <= 2.021329:
                    return True
                elif features[13] <= 0.5:
                    return False
                else:
                    return False
            elif features[7] <= 3.047898:
                return False
            elif features[2] <= 0.758706:
                if features[17] <= 0.134848:
                    if features[3] <= 0.633612:
                        if features[7] <= 3.851786:
                            return False
                        elif features[3] <= 0.483333:
                            return False
                        return features[17] <= 0.129167
                    return not features[2] <= 0.145455
                elif features[19] <= 0.5:
                    if features[7] <= 3.572021:
                        if features[3] <= 0.49:
                            return not features[2] <= 0.651515
                        elif features[7] <= 3.370112:
                            return True
                        elif features[3] <= 0.651515:
                            if features[17] <= 0.318182:
                                return True
                            else:
                                return True
                        else:
                            return True
                    elif features[2] <= 0.615079:
                        if features[20] <= 0.5:
                            if features[13] <= 0.5:
                                return True
                            else:
                                return True
                        return not features[17] <= 0.176923
                    return not features[17] <= 0.252381
                return features[7] <= 3.889752
            else:
                return False
        else:
            return False
    elif features[0] <= 0.163978:
        if features[4] <= 0.5:
            if features[7] <= 3.264621:
                if features[17] <= 0.022678:
                    if features[2] <= 0.000977:
                        return not features[5] <= 0.001953
                    else:
                        return True
                elif features[1] <= 0.095455:
                    if features[17] <= 0.306818:
                        if features[1] <= 0.055728:
                            return False
                        else:
                            return False
                    else:
                        return True
                else:
                    return False
            elif features[10] <= 0.5:
                if features[2] <= 0.455534:
                    if features[3] <= 0.79057:
                        if features[1] <= 0.485714:
                            if features[7] <= 3.540884:
                                if features[7] <= 3.528408:
                                    if features[2] <= 0.316667:
                                        if features[2] <= 0.286364:
                                            if features[17] <= 0.095455:
                                                return True
                                            else:
                                                return True
                                        return not features[13] <= 0.5
                                    else:
                                        return True
                                else:
                                    return False
                            elif features[2] <= 0.446657:
                                return True
                            elif features[17] <= 0.066638:
                                return not features[2] <= 0.450099
                            else:
                                return True
                        else:
                            return False
                    else:
                        return False
                elif features[3] <= 0.425959:
                    if features[3] <= 0.394552:
                        if features[7] <= 4.209417:
                            if features[7] <= 4.175213:
                                if features[3] <= 0.100962:
                                    return False
                                elif features[3] <= 0.248047:
                                    return True
                                return not features[17] <= 0.106443
                            else:
                                return False
                        elif features[23] <= 0.5:
                            return True
                        else:
                            return True
                    elif features[17] <= 0.082906:
                        return False
                    elif features[1] <= 0.025:
                        return False
                    elif features[7] <= 3.520764:
                        return False
                    elif features[1] <= 0.1225:
                        return True
                    return not features[0] <= 0.033333
                elif features[17] <= 0.098599:
                    if features[1] <= 0.012902:
                        return True
                    elif features[23] <= 0.5:
                        return False
                    elif features[3] <= 0.458087:
                        return True
                    else:
                        return True
                elif features[7] <= 4.453697:
                    if features[3] <= 0.472136:
                        if features[17] <= 0.121324:
                            return False
                        elif features[17] <= 0.302885:
                            return not features[7] <= 3.539612
                        else:
                            return False
                    else:
                        return True
                else:
                    return True
            elif features[14] <= 0.5:
                return False
            else:
                return False
        elif features[1] <= 0.45:
            return features[1] <= 0.006212
        else:
            return True
    elif features[23] <= 0.5:
        if features[3] <= 0.082843:
            if features[6] <= 0.282534:
                return False
            elif features[7] <= 3.088801:
                if features[0] <= 0.822852:
                    if features[2] <= 0.291667:
                        return False
                    return not features[1] <= 0.521739
                elif features[16] <= 0.5:
                    return True
                else:
                    return True
            return not features[5] <= 0.140625
        elif features[17] <= 0.291667:
            if features[7] <= 0.698576:
                return True
            elif features[7] <= 5.613847:
                if features[2] <= 0.361264:
                    if features[20] <= 0.5:
                        return False
                    elif features[14] <= 0.5:
                        return not features[0] <= 0.379808
                    else:
                        return False
                elif features[2] <= 0.408333:
                    return not features[1] <= 0.26
                else:
                    return False
            return not features[17] <= 0.012485
        else:
            return True
    elif features[20] <= 0.5:
        return True
    else:
        return True


def is_binary_string(bytes_to_check: bytes) -> bool:
    if not bytes_to_check:
        return False
    if _has_known_binary_signature(bytes_to_check):
        return True
    features = _compute_features(bytes_to_check)
    result = _is_binary_by_features(features)
    logger.debug(
        "is_binary_string: %r (features=%r)",
        result,
        dict(
            zip(
                [
                    "null",
                    "ctrl",
                    "ascii",
                    "high",
                    "utf8",
                    "even0",
                    "odd0",
                    "entropy",
                    "bom32le",
                    "bom32be",
                    "bom16le",
                    "bom16be",
                    "bom8",
                    "try16le",
                    "try16be",
                    "try32le",
                    "try32be",
                    "run",
                    "gb2312",
                    "big5",
                    "shiftjis",
                    "eucjp",
                    "euckr",
                    "magic",
                ],
                [f"{v:.3f}" for v in features],
                strict=True,
            ),
        ),
    )
    return result


def is_binary(filename: str | bytes | Path, *, check_extensions: bool = True) -> bool:
    path = Path(filename)
    from .const import BIN_EXT, TXT_EXT

    if path.suffix in TXT_EXT:
        return False
    if path.suffix in BIN_EXT:
        return True
    logger.debug("is_binary: %(filename)r", locals())
    if check_extensions and has_binary_extension(filename):
        logger.debug("is_binary: True (matched binary extension)")
        return True
    chunk = get_starting_chunk(filename)
    return is_binary_string(chunk)

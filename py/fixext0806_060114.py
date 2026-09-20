from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

MIME_TO_EXT: dict[str, list[str]] = {
    "application/pdf": [".pdf"],
    "application/msword": [".doc"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/vnd.ms-excel": [".xls"],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
    "application/vnd.ms-powerpoint": [".ppt"],
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
    "application/vnd.oasis.opendocument.text": [".odt"],
    "application/vnd.oasis.opendocument.spreadsheet": [".ods"],
    "application/vnd.oasis.opendocument.presentation": [".odp"],
    "application/vnd.oasis.opendocument.graphics": [".odg"],
    "application/vnd.oasis.opendocument.chart": [".odc"],
    "application/vnd.oasis.opendocument.formula": [".odf"],
    "application/vnd.oasis.opendocument.database": [".odb"],
    "application/rtf": [".rtf"],
    "application/vnd.wordperfect": [".wpd"],
    "application/x-abiword": [".abw"],
    "application/x-gnumeric": [".gnumeric"],
    "application/zip": [".zip", ".zipx"],
    "application/x-rar-compressed": [".rar"],
    "application/x-rar": [".rar"],
    "application/vnd.rar": [".rar"],
    "application/x-7z-compressed": [".7z"],
    "application/x-tar": [".tar"],
    "application/gzip": [".gz"],
    "application/x-gzip": [".gz"],
    "application/x-bzip2": [".bz2"],
    "application/x-xz": [".xz"],
    "application/x-zstd": [".zst"],
    "application/x-lzip": [".lz"],
    "application/x-lzma": [".lzma"],
    "application/x-lzop": [".lzo"],
    "application/x-compress": [".Z"],
    "application/x-archive": [".a"],
    "application/x-cpio": [".cpio"],
    "application/x-shar": [".shar"],
    "application/x-iso9660-image": [".iso"],
    "application/x-apple-diskimage": [".dmg"],
    "application/x-virtualbox-vdi": [".vdi"],
    "application/x-vmdk": [".vmdk"],
    "application/x-qemu-disk": [".qcow2"],
    "application/x-vhd": [".vhd"],
    "application/x-vhdx": [".vhdx"],
    "application/x-executable": [".exe"],
    "application/x-dosexec": [".exe"],
    "application/x-msdownload": [".exe", ".dll"],
    "application/x-sharedlib": [".so", ".dll"],
    "application/x-mach-binary": [".dylib"],
    "application/x-elf": [".elf"],
    "application/vnd.android.package-archive": [".apk"],
    "application/x-appimage": [".AppImage"],
    "application/x-debian-package": [".deb"],
    "application/x-rpm": [".rpm"],
    "application/x-flatpak": [".flatpak"],
    "application/x-snap": [".snap"],
    "application/java-archive": [".jar"],
    "application/x-java-class": [".class"],
    "application/wasm": [".wasm"],
    "application/x-bytecode.python": [".pyc"],
    "application/x-font-ttf": [".ttf"],
    "application/x-font-truetype": [".ttf"],
    "font/ttf": [".ttf"],
    "font/otf": [".otf"],
    "application/x-font-otf": [".otf"],
    "font/woff": [".woff"],
    "application/font-woff": [".woff"],
    "font/woff2": [".woff2"],
    "application/font-woff2": [".woff2"],
    "application/vnd.ms-fontobject": [".eot"],
    "application/x-font-type1": [".pfb"],
    "application/x-font-bdf": [".bdf"],
    "application/x-font-pcf": [".pcf"],
    "application/x-sqlite3": [".sqlite", ".db", ".sqlite3"],
    "application/x-dbf": [".dbf"],
    "application/json": [".json"],
    "application/ld+json": [".jsonld"],
    "application/xml": [".xml"],
    "application/xhtml+xml": [".xhtml"],
    "application/atom+xml": [".atom"],
    "application/rss+xml": [".rss"],
    "application/x-yaml": [".yaml", ".yml"],
    "text/yaml": [".yaml", ".yml"],
    "application/toml": [".toml"],
    "application/x-ndjson": [".ndjson"],
    "application/cbor": [".cbor"],
    "application/msgpack": [".msgpack"],
    "application/x-www-form-urlencoded": [".url"],
    "application/postscript": [".ps", ".eps", ".ai"],
    "application/illustrator": [".ai"],
    "application/x-indesign": [".indd"],
    "application/x-quark-xpress": [".qxd"],
    "application/vnd.scribus": [".sla"],
    "application/x-shockwave-flash": [".swf"],
    "application/x-director": [".dir", ".dcr"],
    "application/x-authorware-bin": [".aab"],
    "application/pgp-encrypted": [".gpg", ".pgp"],
    "application/pgp-signature": [".sig", ".asc"],
    "application/x-x509-ca-cert": [".crt", ".cer"],
    "application/pkcs8": [".p8"],
    "application/pkcs12": [".p12", ".pfx"],
    "application/x-pem-file": [".pem"],
    "application/x-pkcs12": [".p12", ".pfx"],
    "application/vnd.ms-cab-compressed": [".cab"],
    "application/x-stuffit": [".sit"],
    "application/x-stuffitx": [".sitx"],
    "application/x-ace-compressed": [".ace"],
    "application/x-alz-compressed": [".alz"],
    "application/x-arj": [".arj"],
    "application/x-lzh-compressed": [".lzh", ".lha"],
    "application/x-zoo": [".zoo"],
    "application/x-arc": [".arc"],
    "application/x-dms": [".dms"],
    "application/x-pak": [".pak"],
    "application/x-chrome-extension": [".crx"],
    "application/x-xpinstall": [".xpi"],
    "application/x-ms-application": [".application"],
    "application/x-ms-xbap": [".xbap"],
    "application/x-silverlight-app": [".xap"],
    "application/x-lotus-123": [".wk1", ".wks"],
    "application/vnd.lotus-1-2-3": [".123"],
    "application/vnd.lotus-wordpro": [".lwp"],
    "application/vnd.lotus-approach": [".apr"],
    "application/vnd.lotus-freelance": [".pre"],
    "application/vnd.lotus-notes": [".nsf"],
    "application/x-quattropro": [".qpw"],
    "application/x-dbase": [".dbf"],
    "application/mathematica": [".nb"],
    "application/vnd.wolfram.mathematica": [".nb"],
    "application/x-matlab-data": [".mat"],
    "application/x-sas": [".sas"],
    "application/x-spss-sav": [".sav"],
    "application/x-stata": [".dta"],
    "application/x-r-data": [".rda", ".rdata"],
    "audio/mpeg": [".mp3"],
    "audio/mp3": [".mp3"],
    "audio/flac": [".flac"],
    "audio/x-flac": [".flac"],
    "audio/aac": [".aac"],
    "audio/x-aac": [".aac"],
    "audio/ogg": [".ogg"],
    "audio/vorbis": [".ogg"],
    "audio/opus": [".opus"],
    "audio/wav": [".wav"],
    "audio/x-wav": [".wav"],
    "audio/wave": [".wav"],
    "audio/x-aiff": [".aiff", ".aif"],
    "audio/aiff": [".aiff", ".aif"],
    "audio/midi": [".midi", ".mid"],
    "audio/x-midi": [".midi", ".mid"],
    "audio/mp4": [".m4a"],
    "audio/x-m4a": [".m4a"],
    "audio/x-ms-wma": [".wma"],
    "audio/webm": [".weba"],
    "audio/amr": [".amr"],
    "audio/x-amr": [".amr"],
    "audio/3gpp": [".3gp"],
    "audio/3gpp2": [".3g2"],
    "audio/speex": [".spx"],
    "audio/x-speex": [".spx"],
    "audio/x-musepack": [".mpc"],
    "audio/musepack": [".mpc"],
    "audio/x-wavpack": [".wv"],
    "audio/x-ape": [".ape"],
    "audio/x-monkeys-audio": [".ape"],
    "audio/x-tta": [".tta"],
    "audio/x-shn": [".shn"],
    "audio/x-caf": [".caf"],
    "audio/x-dsd": [".dsd", ".dsf"],
    "audio/x-mod": [".mod"],
    "audio/x-xm": [".xm"],
    "audio/x-it": [".it"],
    "audio/x-s3m": [".s3m"],
    "audio/x-stm": [".stm"],
    "audio/x-669": [".669"],
    "audio/x-psf": [".psf"],
    "audio/x-spc": [".spc"],
    "audio/x-gym": [".gym"],
    "audio/x-nsf": [".nsf"],
    "audio/x-gbs": [".gbs"],
    "audio/x-vgm": [".vgm", ".vgz"],
    "audio/x-ay": [".ay"],
    "audio/x-sid": [".sid"],
    "audio/x-ahx": [".ahx"],
    "audio/x-hvl": [".hvl"],
    "audio/x-tfmx": [".tfmx"],
    "audio/x-sunvox": [".sunvox"],
    "audio/basic": [".au", ".snd"],
    "audio/x-au": [".au"],
    "audio/x-pn-realaudio": [".ra", ".ram"],
    "audio/vnd.rn-realaudio": [".ra"],
    "audio/x-gsm": [".gsm"],
    "audio/x-adpcm": [".adpcm"],
    "audio/x-ms-wax": [".wax"],
    "video/mp4": [".mp4", ".m4v"],
    "video/x-msvideo": [".avi"],
    "video/x-matroska": [".mkv"],
    "video/webm": [".webm"],
    "video/quicktime": [".mov", ".qt"],
    "video/x-ms-wmv": [".wmv"],
    "video/x-flv": [".flv"],
    "video/x-f4v": [".f4v"],
    "video/mpeg": [".mpeg", ".mpg", ".mpe"],
    "video/3gpp": [".3gp"],
    "video/3gpp2": [".3g2"],
    "video/ogg": [".ogv"],
    "video/x-ms-asf": [".asf", ".asx"],
    "video/x-ms-vob": [".vob"],
    "video/dvd": [".vob"],
    "video/mp2t": [".ts", ".m2ts"],
    "video/x-m2ts": [".m2ts", ".mts"],
    "video/x-dv": [".dv"],
    "video/x-mng": [".mng"],
    "video/x-sgi-movie": [".movie"],
    "video/x-pn-realvideo": [".rv", ".rmvb"],
    "video/vnd.rn-realvideo": [".rv"],
    "video/x-theora": [".ogv"],
    "video/x-dirac": [".drc"],
    "video/x-cavs": [".cavs"],
    "video/x-nuv": [".nuv"],
    "video/x-nsv": [".nsv"],
    "video/x-swf": [".swf"],
    "application/x-nes-rom": [".nes"],
    "application/x-snes-rom": [".smc", ".sfc"],
    "application/x-gameboy-rom": [".gb"],
    "application/x-gbc-rom": [".gbc"],
    "application/x-gba-rom": [".gba"],
    "application/x-n64-rom": [".z64", ".n64", ".v64"],
    "application/x-nds-rom": [".nds"],
    "application/x-genesis-rom": [".md", ".gen"],
    "application/x-sms-rom": [".sms"],
    "application/x-gg-rom": [".gg"],
    "application/x-pce-rom": [".pce"],
    "application/x-lynx-rom": [".lnx"],
    "application/x-atari-2600-rom": [".a26"],
    "application/x-atari-7800-rom": [".a78"],
    "application/x-atari-st-rom": [".st"],
    "application/x-c64-rom": [".d64", ".t64"],
    "application/x-amiga-rom": [".adf"],
    "image/jpeg": [".jpg", ".jpeg", ".jpe"],
    "image/png": [".png"],
    "image/gif": [".gif"],
    "image/webp": [".webp"],
    "image/avif": [".avif"],
    "image/heic": [".heic"],
    "image/heif": [".heif"],
    "image/tiff": [".tiff", ".tif"],
    "image/bmp": [".bmp"],
    "image/x-bmp": [".bmp"],
    "image/x-ms-bmp": [".bmp"],
    "image/svg+xml": [".svg"],
    "image/x-icon": [".ico"],
    "image/vnd.microsoft.icon": [".ico"],
    "image/x-xcf": [".xcf"],
    "image/x-gimp-xcf": [".xcf"],
    "image/vnd.adobe.photoshop": [".psd"],
    "image/x-photoshop": [".psd"],
    "image/x-portable-bitmap": [".pbm"],
    "image/x-portable-graymap": [".pgm"],
    "image/x-portable-pixmap": [".ppm"],
    "image/x-portable-anymap": [".pnm"],
    "image/x-xpixmap": [".xpm"],
    "image/x-xbitmap": [".xbm"],
    "image/x-tga": [".tga"],
    "image/x-targa": [".tga"],
    "image/x-pcx": [".pcx"],
    "image/vnd.zbrush.pcx": [".pcx"],
    "image/x-pict": [".pict", ".pct"],
    "image/x-rgb": [".rgb", ".sgi"],
    "image/x-sgi": [".sgi"],
    "image/x-ilbm": [".ilbm", ".iff"],
    "image/x-exr": [".exr"],
    "image/x-hdr": [".hdr"],
    "image/x-dds": [".dds"],
    "image/x-vtf": [".vtf"],
    "image/jp2": [".jp2", ".j2k"],
    "image/jpx": [".jpf", ".jpx"],
    "image/jpm": [".jpm"],
    "image/x-canon-cr2": [".cr2"],
    "image/x-canon-crw": [".crw"],
    "image/x-nikon-nef": [".nef"],
    "image/x-nikon-nrw": [".nrw"],
    "image/x-sony-arw": [".arw"],
    "image/x-sony-srf": [".srf"],
    "image/x-sony-sr2": [".sr2"],
    "image/x-adobe-dng": [".dng"],
    "image/x-olympus-orf": [".orf"],
    "image/x-panasonic-raw": [".raw", ".rw2"],
    "image/x-fuji-raf": [".raf"],
    "image/x-sigma-x3f": [".x3f"],
    "image/x-pentax-pef": [".pef"],
    "image/x-kodak-dcr": [".dcr"],
    "image/x-kodak-kdc": [".kdc"],
    "image/x-minolta-mrw": [".mrw"],
    "image/x-leica-rwl": [".rwl"],
    "image/x-hasselblad-3fr": [".3fr"],
    "image/x-hasselblad-fff": [".fff"],
    "image/x-phaseone-iiq": [".iiq"],
    "image/x-mamiya-mef": [".mef"],
    "image/x-epson-erf": [".erf"],
    "image/jxl": [".jxl"],
    "image/x-jxl": [".jxl"],
    "image/x-emf": [".emf"],
    "image/x-wmf": [".wmf"],
    "text/plain": [".txt"],
    "text/html": [".html", ".htm"],
    "text/css": [".css"],
    "text/javascript": [".js"],
    "application/javascript": [".js"],
    "text/x-python": [".py"],
    "application/x-python": [".py"],
    "text/x-python3": [".py"],
    "text/x-rust": [".rs"],
    "text/x-go": [".go"],
    "text/x-java": [".java"],
    "text/x-java-source": [".java"],
    "text/x-c": [".c"],
    "text/x-csrc": [".c"],
    "text/x-c++": [".cpp", ".cxx", ".cc"],
    "text/x-c++src": [".cpp", ".cxx", ".cc"],
    "text/x-chdr": [".h"],
    "text/x-c++hdr": [".hpp", ".hxx"],
    "text/x-csharp": [".cs"],
    "text/x-ruby": [".rb"],
    "text/x-perl": [".pl", ".pm"],
    "application/x-perl": [".pl"],
    "text/x-php": [".php"],
    "application/x-php": [".php"],
    "text/x-shellscript": [".sh"],
    "application/x-sh": [".sh"],
    "application/x-shellscript": [".sh"],
    "text/x-script.python": [".py"],
    "text/x-script.ruby": [".rb"],
    "text/x-script.perl": [".pl"],
    "text/x-script.sh": [".sh"],
    "text/x-awk": [".awk"],
    "text/x-tcl": [".tcl"],
    "text/x-lua": [".lua"],
    "text/x-r": [".r", ".R"],
    "text/x-matlab": [".m"],
    "text/x-julia": [".jl"],
    "text/x-haskell": [".hs"],
    "text/x-literate-haskell": [".lhs"],
    "text/x-erlang": [".erl"],
    "text/x-elixir": [".ex", ".exs"],
    "text/x-clojure": [".clj", ".cljs"],
    "text/x-scala": [".scala"],
    "text/x-kotlin": [".kt", ".kts"],
    "text/x-swift": [".swift"],
    "text/x-objc": [".m"],
    "text/x-objc++": [".mm"],
    "text/x-dart": [".dart"],
    "text/x-typescript": [".ts"],
    "text/x-coffeescript": [".coffee"],
    "text/x-vb": [".vb"],
    "text/x-pascal": [".pas", ".pp"],
    "text/x-fortran": [".f", ".f90", ".f95"],
    "text/x-cobol": [".cbl", ".cob"],
    "text/x-ada": [".ada", ".adb"],
    "text/x-d": [".d"],
    "text/x-nim": [".nim"],
    "text/x-crystal": [".cr"],
    "text/x-zig": [".zig"],
    "text/x-v": [".v"],
    "text/x-ocaml": [".ml", ".mli"],
    "text/x-fsharp": [".fs", ".fsx"],
    "text/x-scheme": [".scm", ".ss"],
    "text/x-commonlisp": [".lisp", ".cl"],
    "text/x-racket": [".rkt"],
    "text/x-prolog": [".pl", ".pro"],
    "text/x-sql": [".sql"],
    "text/x-plsql": [".sql"],
    "text/x-cmake": [".cmake"],
    "text/x-makefile": [".mk", ".mak"],
    "text/x-asm": [".asm", ".s"],
    "text/x-nasm": [".asm"],
    "text/x-verilog": [".v"],
    "text/x-vhdl": [".vhd", ".vhdl"],
    "text/x-systemverilog": [".sv"],
    "text/x-diff": [".diff", ".patch"],
    "text/x-patch": [".patch"],
    "text/markdown": [".md", ".markdown"],
    "text/x-markdown": [".md", ".markdown"],
    "text/x-rst": [".rst"],
    "text/x-asciidoc": [".adoc", ".asciidoc"],
    "text/xml": [".xml"],
    "text/csv": [".csv"],
    "text/tab-separated-values": [".tsv"],
    "text/x-ini": [".ini", ".cfg"],
    "text/x-properties": [".properties"],
    "text/troff": [".1", ".man"],
    "text/x-nfo": [".nfo"],
    "text/vcard": [".vcf", ".vcard"],
    "text/calendar": [".ics", ".ical"],
    "text/x-bibtex": [".bib"],
    "text/x-tex": [".tex"],
    "text/x-latex": [".tex", ".latex"],
    "text/x-log": [".log"],
    "text/x-m3u": [".m3u"],
    "text/x-pls": [".pls"],
    "application/x-subrip": [".srt"],
    "text/vtt": [".vtt"],
    "application/ttml+xml": [".ttml"],
    "image/x-xcursor": [".cur"],
    "application/x-navi-animation": [".ani"],
    "model/stl": [".stl"],
    "model/x-stl-binary": [".stl"],
    "model/obj": [".obj"],
    "model/gltf+json": [".gltf"],
    "model/gltf-binary": [".glb"],
    "model/vnd.collada+xml": [".dae"],
    "model/vrml": [".wrl", ".vrml"],
    "model/x3d+xml": [".x3d"],
    "model/x3d+binary": [".x3db"],
    "application/x-blender": [".blend"],
    "application/x-3ds": [".3ds"],
    "application/x-fbx": [".fbx"],
    "application/x-maya": [".ma", ".mb"],
    "application/x-cinema4d": [".c4d"],
    "application/x-sketchup": [".skp"],
    "application/x-autocad": [".dwg"],
    "image/vnd.dxf": [".dxf"],
    "application/x-step": [".step", ".stp"],
    "application/x-iges": [".iges", ".igs"],
    "application/x-pcb": [".kicad_pcb"],
    "application/x-gerber": [".gbr", ".ger"],
    "application/x-hdf": [".h4", ".hdf"],
    "application/x-hdf5": [".h5", ".hdf5"],
    "application/x-netcdf": [".nc", ".cdf"],
    "application/x-fits": [".fits", ".fit"],
    "application/x-bio-sequence": [".fasta", ".fa"],
    "application/x-genbank": [".gb", ".gbk"],
    "application/x-pdb": [".pdb"],
    "application/x-mmcif": [".cif"],
    "application/x-torrent": [".torrent"],
    "application/x-bittorrent": [".torrent"],
    "application/x-magnet": [".magnet"],
    "application/epub+zip": [".epub"],
    "application/x-mobipocket-ebook": [".mobi"],
    "application/vnd.amazon.ebook": [".azw"],
    "application/x-fictionbook": [".fb2"],
    "application/x-cbz": [".cbz"],
    "application/x-cbr": [".cbr"],
    "application/x-cb7": [".cb7"],
    "application/x-cbt": [".cbt"],
    "application/vnd.ms-htmlhelp": [".chm"],
    "application/x-info": [".info"],
    "application/x-ms-reader": [".lit"],
    "application/x-ibooks+zip": [".ibooks"],
    "application/x-palm-database": [".pdb", ".prc"],
    "application/x-tcl": [".tcl"],
    "application/x-ruby": [".rb"],
    "application/x-msdos-program": [".com", ".bat"],
    "application/x-ms-dos-executable": [".com"],
    "application/bat": [".bat"],
    "application/x-wine-extension-ini": [".ini"],
    "application/x-desktop": [".desktop"],
    "application/x-ms-shortcut": [".lnk"],
    "application/vnd.ms-windows.thumbnail-cache": [".db"],
    "application/x-trash": [".bak", ".tmp"],
    "application/x-profile": [".prof"],
    "application/x-core": [".core"],
    "application/x-object": [".o"],
    "application/x-archive-lib": [".a"],
    "application/x-cmake-cache": [".cmake"],
    "application/x-ninja": [".ninja"],
    "application/x-gradle": [".gradle"],
    "application/x-maven-pom": [".pom"],
    "application/x-ant-build": [".xml"],
    "application/x-wais-source": [".src"],
    "application/x-java-jnlp-file": [".jnlp"],
    "application/x-ms-manifest": [".manifest"],
    "application/x-ms-pdb": [".pdb"],
    "application/x-doom": [".wad"],
    "application/x-quake": [".pak"],
    "application/x-quake3-demo": [".pk3"],
    "application/x-valve-vpk": [".vpk"],
    "application/x-bethesda-bsa": [".bsa"],
    "application/x-bethesda-esm": [".esm", ".esp"],
    "application/x-minecraft-region": [".mca"],
    "application/x-minecraft-nbt": [".dat"],
    "application/x-save-data": [".sav"],
    "application/x-gzip-compressed-tar": [".tar.gz", ".tgz"],
    "application/x-bzip-compressed-tar": [".tar.bz2", ".tbz2"],
    "application/x-xz-compressed-tar": [".tar.xz", ".txz"],
    "application/x-zstd-compressed-tar": [".tar.zst"],
    "application/x-lzip-compressed-tar": [".tar.lz"],
    "application/x-lzma-compressed-tar": [".tar.lzma"],
}

SHEBANG_MAP: dict[str, str] = {
    "python": ".py",
    "python2": ".py",
    "python3": ".py",
    "bash": ".sh",
    "sh": ".sh",
    "zsh": ".sh",
    "fish": ".sh",
    "dash": ".sh",
    "ksh": ".sh",
    "tcsh": ".sh",
    "csh": ".sh",
    "perl": ".pl",
    "perl5": ".pl",
    "ruby": ".rb",
    "lua": ".lua",
    "tcl": ".tcl",
    "expect": ".exp",
    "awk": ".awk",
    "gawk": ".awk",
    "nawk": ".awk",
    "sed": ".sed",
    "make": ".mk",
    "gmake": ".mk",
    "node": ".js",
    "nodejs": ".js",
    "deno": ".js",
    "php": ".php",
    "php-cgi": ".php",
    "racket": ".rkt",
    "guile": ".scm",
    "clisp": ".lisp",
    "sbcl": ".lisp",
    "ccl": ".lisp",
    "octave": ".m",
    "Rscript": ".R",
    "R": ".R",
    "swipl": ".pl",
    "yap": ".pl",
    "ghc": ".hs",
    "runghc": ".hs",
    "erlc": ".erl",
    "escript": ".erl",
    "elixir": ".exs",
    "mix": ".exs",
    "scala": ".scala",
    "kotlin": ".kt",
    "dart": ".dart",
    "swift": ".swift",
    "crystal": ".cr",
    "nim": ".nim",
    "zig": ".zig",
    "v": ".v",
    "go": ".go",
    "rustc": ".rs",
    "cargo": ".rs",
    "julia": ".jl",
    "coffee": ".coffee",
    "csharp": ".cs",
    "dotnet": ".cs",
    "fsharp": ".fsx",
    "groovy": ".groovy",
    "gradle": ".gradle",
    "haxe": ".hx",
    "neko": ".neko",
    "valac": ".vala",
    "genie": ".gs",
    "meson": ".build",
    "ninja": ".ninja",
    "cmake": ".cmake",
    "qmake": ".pro",
    "scons": ".sconstruct",
    "waf": ".wscript",
    "autoconf": ".ac",
    "automake": ".am",
    "m4": ".m4",
    "bison": ".y",
    "yacc": ".y",
    "flex": ".l",
    "lex": ".l",
    "ant": ".xml",
    "mvn": ".xml",
    "sbt": ".sbt",
    "lein": ".clj",
    "boot": ".clj",
    "clojure": ".clj",
    "lisp": ".lisp",
    "scheme": ".scm",
    "chicken": ".scm",
    "csi": ".scm",
    "csc": ".scm",
    "bigloo": ".scm",
    "stklos": ".scm",
    "gosh": ".scm",
    "kawa": ".scm",
    "sisc": ".scm",
    "mit-scheme": ".scm",
    "tinyscheme": ".scm",
    "prolog": ".pl",
    "gprolog": ".pl",
    "xsb": ".pl",
    "mercury": ".m",
    "sqlite3": ".sql",
    "psql": ".sql",
    "mysql": ".sql",
    "isql": ".sql",
    "osql": ".sql",
    "tsql": ".sql",
    "bc": ".bc",
    "dc": ".dc",
    "factor": ".factor",
    "gforth": ".fs",
    "lush": ".lsh",
    "newlisp": ".lsp",
    "picolisp": ".lsp",
    "rebol": ".r",
    "red": ".red",
    "io": ".io",
    "self": ".self",
    "smalltalk": ".st",
    "gst": ".st",
    "squeak": ".st",
    "pharo": ".st",
    "cuis": ".st",
    "scratch": ".sb3",
    "pure": ".pure",
    "q": ".q",
    "k": ".k",
    "j": ".ijs",
    "apl": ".apl",
    "gnuapl": ".apl",
    "dzyn": ".dzyn",
    "bqn": ".bqn",
    "uiua": ".ua",
    "purescript": ".purs",
    "idris": ".idr",
    "agda": ".agda",
    "coq": ".v",
    "isabelle": ".thy",
    "lean": ".lean",
    "smt": ".smt2",
    "z3": ".smt2",
    "cvc4": ".smt2",
    "cvc5": ".smt2",
    "vampire": ".vampire",
    "eprover": ".eprover",
    "spass": ".spass",
    "tptp": ".tptp",
    "maude": ".maude",
    "elf": ".elf",
    "twelf": ".elf",
    "abella": ".abella",
    "lambda-prolog": ".lprolog",
    "minikanren": ".mk",
    "core.logic": ".clj",
    "datalog": ".dl",
    "souffle": ".dl",
    "clingo": ".lp",
    "gringo": ".lp",
    "dlv": ".dlv",
    "xsb": ".P",
    "eclipse": ".ecl",
    "sicstus": ".pl",
    "swi-prolog": ".pl",
    "yap-prolog": ".pl",
    "gnu-prolog": ".pl",
    "b-prolog": ".pl",
    "ciao": ".pl",
    "tuprolog": ".pl",
    "jiprolog": ".pl",
    "logtalk": ".lgt",
    "visual-prolog": ".pro",
    "pdc-prolog": ".pro",
    "amzi": ".pro",
    "arity": ".pro",
    "lpa": ".pro",
    "micro-prolog": ".pro",
    "poplog": ".pop",
    "pop-11": ".pop",
    "prolog++": ".pp",
    "object-prolog": ".op",
    "flora-2": ".flr",
    "er-go": ".ergo",
    "fril": ".fril",
    "godel": ".gdl",
    "hal": ".hal",
    "mozilla": ".moz",
    "oz": ".oz",
    "mz": ".mz",
    "scheme48": ".scm",
    "scsh": ".scm",
    "stalin": ".scm",
    "larceny": ".scm",
    "mosh": ".scm",
    "ypsilon": ".scm",
    "iron-scheme": ".scm",
    "sagittarius": ".scm",
    "foment": ".scm",
    "chibi": ".scm",
    "picrin": ".scm",
    "cyclone": ".scm",
    "gerbil": ".scm",
    "gambit": ".scm",
    "typed-racket": ".rkt",
    "lazy-racket": ".rkt",
    "frracket": ".rkt",
    "scribble": ".scrbl",
    "slideshow": ".scrbl",
    "pollen": ".pm",
    "raco": ".rkt",
    "planet": ".plt",
    "snow": ".snow",
    "snow2": ".snow",
    "snow3": ".snow",
    "snow4": ".snow",
    "snow5": ".snow",
    "snow6": ".snow",
    "snow7": ".snow",
    "snow8": ".snow",
    "snow9": ".snow",
    "snow10": ".snow",
    "snow11": ".snow",
    "snow12": ".snow",
    "snow13": ".snow",
    "snow14": ".snow",
    "snow15": ".snow",
    "snow16": ".snow",
    "snow17": ".snow",
    "snow18": ".snow",
    "snow19": ".snow",
    "snow20": ".snow",
    "snow21": ".snow",
    "snow22": ".snow",
    "snow23": ".snow",
    "snow24": ".snow",
    "snow25": ".snow",
    "snow26": ".snow",
    "snow27": ".snow",
    "snow28": ".snow",
    "snow29": ".snow",
    "snow30": ".snow",
    "snow31": ".snow",
    "snow32": ".snow",
    "snow33": ".snow",
    "snow34": ".snow",
    "snow35": ".snow",
    "snow36": ".snow",
    "snow37": ".snow",
    "snow38": ".snow",
    "snow39": ".snow",
    "snow40": ".snow",
    "snow41": ".snow",
    "snow42": ".snow",
    "snow43": ".snow",
    "snow44": ".snow",
    "snow45": ".snow",
    "snow46": ".snow",
    "snow47": ".snow",
    "snow48": ".snow",
    "snow49": ".snow",
    "snow50": ".snow",
    "snow51": ".snow",
    "snow52": ".snow",
    "snow53": ".snow",
    "snow54": ".snow",
    "snow55": ".snow",
    "snow56": ".snow",
    "snow57": ".snow",
    "snow58": ".snow",
    "snow59": ".snow",
    "snow60": ".snow",
    "snow61": ".snow",
    "snow62": ".snow",
    "snow63": ".snow",
    "snow64": ".snow",
    "snow65": ".snow",
    "snow66": ".snow",
    "snow67": ".snow",
    "snow68": ".snow",
    "snow69": ".snow",
    "snow70": ".snow",
    "snow71": ".snow",
    "snow72": ".snow",
    "snow73": ".snow",
    "snow74": ".snow",
    "snow75": ".snow",
    "snow76": ".snow",
    "snow77": ".snow",
    "snow78": ".snow",
    "snow79": ".snow",
    "snow80": ".snow",
    "snow81": ".snow",
    "snow82": ".snow",
    "snow83": ".snow",
    "snow84": ".snow",
    "snow85": ".snow",
    "snow86": ".snow",
    "snow87": ".snow",
    "snow88": ".snow",
    "snow89": ".snow",
    "snow90": ".snow",
    "snow91": ".snow",
    "snow92": ".snow",
    "snow93": ".snow",
    "snow94": ".snow",
    "snow95": ".snow",
    "snow96": ".snow",
    "snow97": ".snow",
    "snow98": ".snow",
    "snow99": ".snow",
    "snow100": ".snow",
}

SKIP_DIRS: frozenset[str] = frozenset({".git", "__pycache__"})
SKIP_EXTS: frozenset[str] = frozenset({".css", ".js"})


def runcmd(cmd: list[str], silent: bool = False, show_output: bool = False, timeout: int = 30) -> dict:
    result = {"exit_code": -1, "stdout": "", "stderr": ""}
    try:
        proc = subprocess.run(
            cmd,
            capture_output=not show_output,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        result["exit_code"] = proc.returncode
        result["stdout"] = proc.stdout or ""
        result["stderr"] = proc.stderr or ""
    except FileNotFoundError:
        result["stderr"] = "Command not found"
    except PermissionError:
        result["stderr"] = "Permission denied"
    except subprocess.TimeoutExpired:
        result["stderr"] = "Command timed out"
    except Exception as e:
        result["stderr"] = str(e)
    return result


def can_colorize() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("ANSI_COLORS_DISABLED"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


_COLORIZE: bool = can_colorize()


def colored(
    text: str,
    color: str | None = None,
    on_color: str | None = None,
    attrs: list[str] | None = None,
) -> str:
    if not _COLORIZE:
        return text
    codes: list[str] = []
    color_map = {
        "black": "30",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "white": "37",
        "light_black": "90",
        "light_red": "91",
        "light_green": "92",
        "light_yellow": "93",
        "light_blue": "94",
        "light_magenta": "95",
        "light_cyan": "96",
        "light_white": "97",
    }
    bg_map = {
        "on_black": "40",
        "on_red": "41",
        "on_green": "42",
        "on_yellow": "43",
        "on_blue": "44",
        "on_magenta": "45",
        "on_cyan": "46",
        "on_white": "47",
    }
    attr_map = {
        "bold": "1",
        "dark": "2",
        "italic": "3",
        "underline": "4",
        "blink": "5",
        "reverse": "7",
        "concealed": "8",
        "strikethrough": "9",
    }
    if color and color in color_map:
        codes.append(color_map[color])
    if on_color and on_color in bg_map:
        codes.append(bg_map[on_color])
    if attrs:
        for a in attrs:
            if a in attr_map:
                codes.append(attr_map[a])
    if not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def cprint(
    text: str,
    color: str | None = None,
    on_color: str | None = None,
    attrs: list[str] | None = None,
    **kwargs,
) -> None:
    print(colored(text, color, on_color, attrs), **kwargs)


def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            data = f.read(8192)
        if not data:
            return False
        if b"\x00" in data:
            return True
        non_text = sum(1 for b in data if b < 32 and b not in (9, 10, 13))
        return (non_text / len(data)) > 0.3
    except Exception:
        return False


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{suffix}"
        new_path = path.with_name(new_name)
        if not new_path.exists():
            return new_path
        counter += 1


def fix_by_shebang(path: Path) -> str | None:
    if is_binary(path):
        return None
    try:
        with open(path, "rb") as f:
            first_line = f.readline(256)
        if not first_line.startswith(b"#!"):
            return None
        shebang = first_line.decode("utf-8", errors="replace").strip()
        for interpreter, ext in SHEBANG_MAP.items():
            if interpreter in shebang:
                return ext
        return None
    except Exception:
        return None


def get_file_mime(path: Path) -> str | None:
    result = runcmd(["file", "--brief", "--mime-type", str(path)])
    if result["exit_code"] != 0:
        return None
    mime = result["stdout"].strip()
    if not mime:
        return None
    return mime


def safe_rename(old: Path, new: Path) -> bool:
    try:
        new = unique_path(new)
        old.rename(new)
        return True
    except Exception:
        return False


def process_directory(directory: Path, confirm: bool = False) -> list[dict]:
    mismatches: list[dict] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            file_path = Path(root) / file
            if not file_path.is_file() or file_path.is_symlink():
                continue
            if file_path.stat().st_size == 0:
                continue
            ext = file_path.suffix.lower()
            if ext in SKIP_EXTS:
                continue
            shebang_ext = fix_by_shebang(file_path)
            if shebang_ext:
                current_ext = file_path.suffix.lower()
                if current_ext != shebang_ext:
                    new_name = file_path.with_suffix(shebang_ext).name
                    new_path = file_path.with_name(new_name)
                    mismatches.append(
                        {
                            "path": file_path,
                            "mime": "shebang",
                            "current_ext": current_ext or "(none)",
                            "expected_ext": shebang_ext,
                            "new_path": new_path,
                        }
                    )
                continue
            mime = get_file_mime(file_path)
            if not mime:
                continue
            if mime == "text/plain":
                continue
            expected_exts = MIME_TO_EXT.get(mime, [])
            if not expected_exts:
                continue
            expected_ext = expected_exts[0]
            current_ext = file_path.suffix.lower()
            if current_ext == expected_ext:
                continue
            if current_ext in expected_exts:
                continue
            if current_ext:
                new_name = file_path.stem + expected_ext
            else:
                new_name = file.name + expected_ext
            new_path = file_path.with_name(new_name)
            mismatches.append(
                {
                    "path": file_path,
                    "mime": mime,
                    "current_ext": current_ext or "(none)",
                    "expected_ext": expected_ext,
                    "new_path": new_path,
                }
            )
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix file extension mismatches by analyzing file content.")
    parser.add_argument("-y", action="store_true", help="Enable confirmation mode")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        cprint(f"Error: {directory} is not a valid directory", color="red", attrs=["bold"])
        sys.exit(1)
    mismatches = process_directory(directory, confirm=args.y)
    if not mismatches:
        cprint("No mismatches found.", color="green", attrs=["bold"])
        sys.exit(0)
    cprint(
        f"\nFound {len(mismatches)} mismatched file(s):\n",
        color="yellow",
        attrs=["bold"],
    )
    for item in mismatches:
        orig = colored(str(item["path"]), color="red", attrs=["bold"])
        mime_info = colored(f"mime={item['mime']}", color="cyan")
        expected = colored(f"expected ext ={item['expected_ext']}", color="green")
        new_name = colored(item["new_path"].name, color="green", attrs=["bold"])
        print(f"{orig}")
        print(f"  {mime_info}")
        print(f"  {expected}")
        print(f"  new name = {new_name}")
        if args.y:
            response = input(f"  {item['path'].name} -> {item['new_path'].name} ? [y/N] ").strip().lower()
            if response != "y":
                print("  Skipped.")
                continue
        if safe_rename(item["path"], item["new_path"]):
            cprint(f"  Renamed to {item['new_path'].name}", color="green")
        else:
            cprint("  Failed to rename", color="red", attrs=["bold"])
        print()
    cprint("Done.", color="green", attrs=["bold"])


if __name__ == "__main__":
    main()

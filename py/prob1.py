import libcst as cst


src_crlf = "x = 1\r\ny = 2\r\n"
m = cst.parse_module(src_crlf)
print("CRLF preserved:", m.code == src_crlf, repr(m.default_newline), repr(m.code[:20]))
print("code_for_node:", repr(cst.Module([]).code_for_node(m))[:60])


for v in ("3.12", "3.13", "3.9"):
    try:
        cfg = cst.PartialParserConfig(python_version=v)
        print("cfg", v, "ok")
    except Exception as e:
        print("cfg", v, "fail:", type(e).__name__, e)


src = "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# hello\nimport os\n"
mod = cst.parse_module(src)
print("header:", [(type(i).__name__, repr(i.comment.value if i.comment else None)) for i in mod.header.items])


class DropAll(cst.CSTTransformer):
    def leave_Comment(self, o, u):
        return cst.RemoveFromParent()


class DropAndEmptyLines(cst.CSTTransformer):
    def leave_Comment(self, o, u):
        return cst.RemoveFromParent()

    def leave_EmptyLine(self, o, u):
        if o.comment is not None and u.comment is None:
            return cst.RemoveFromParent()
        return u


print("---- drop comments only ----")
print(repr(mod.visit(DropAll()).code))
print("---- drop comments + emptied lines ----")
print(repr(mod.visit(DropAndEmptyLines()).code))

src2 = "# a\n# b\n\nx = 1  # tail\n# after\n"
m2 = cst.parse_module(src2)
print("---- src2 raw ----")
print(repr(m2.code))
print("---- src2 drop+empty ----")
print(repr(m2.visit(DropAndEmptyLines()).code))
print("--- footer:", m2.footer)

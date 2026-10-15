#!/usr/bin/env python3
"""
gen_types.py - turn D2BS's D2Structs.h into a preprocessor-free C header that
Ghidra's C parser (ghidra.app.util.cparser.C.CParser) accepts, prove that the
translation keeps the MSVC x86 layout, and render docs/memory/structs.md.

Python 3 standard library only. Modes (combinable):

  --out FILE          write the Ghidra header (no external tools needed)
  --check             verify with clang (see "Verification" below); exit 1 on mismatch
  --structs-md FILE   write the struct reference (needs clang: offsets come from it)
  --layout-json FILE  dump the clang-computed layouts as JSON (needs clang)
  --ghidra-install DIR | --ghidra-cp CLASSPATH
                      additionally parse the header with Ghidra's CParser (needs javac/java)

Example (from the repo root):
  python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h
  python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check
  python3 docs/ghidra/tools/gen_types.py --repo . --structs-md docs/memory/structs.md \
      [--ghidra-install /opt/ghidra --ghidra-label "Ghidra 12.0.4"]

Verification (--check; also run by --structs-md and --layout-json):
  1. The ORIGINAL D2Structs.h is compiled by clang++ as MSVC x86
     (--target=i686-pc-windows-msvc -fms-extensions -fms-compatibility) against a
     tiny fake <windows.h>; sizeof/alignof/offsetof of every struct and field are
     emitted as LLVM-IR constants and read back.  Bit-field positions come from
     clang's -fdump-record-layouts-complete output.  This is the ground truth.
  2. The built-in Python MSVC layout engine (used for the offset comments in the
     header) must agree with (1) for every field.
  3. The GENERATED header is compiled as C (clang -x c, same target) behind a
     wrapper that typedefs wchar_t, with a _Static_assert for the offset of every
     field and the sizeof/alignof of every struct (values from (1)), plus
     __builtin_types_compatible_p asserts that function pointers keep their
     calling convention.  Bit-field positions are compared via the record dump.
  4. Every type identifier used by a FUNCPTR/VARPTR in D2Ptrs.h (and by the FUNC
     and DATA rows of docs/ghidra/d2bs_symbols.tsv when that file exists) must be
     defined or forward-declared in the header.
  5. Optional (--ghidra-install/--ghidra-cp): an embedded Java harness parses the
     header, and then header + d2bs_symbols.tsv prototypes, with Ghidra's CParser
     (x86win.cspec data organisation) and compares every composite with (1).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict

STRUCTS_H = "D2Structs.h"
PTRS_H = "D2Ptrs.h"
MPQSTATS_H = "MPQStats.h"
SYMBOLS_TSV = "docs/ghidra/d2bs_symbols.tsv"
DEFAULT_PACK = 8  # MSVC default /Zp8

# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------


class Tok(object):
    __slots__ = ("kind", "text", "line")

    def __init__(self, kind, text, line):
        self.kind, self.text, self.line = kind, text, line

    def __repr__(self):
        return "Tok(%s,%r,%d)" % (self.kind, self.text, self.line)


_ID_RE = re.compile(r"[A-Za-z_]\w*")
_NUM_RE = re.compile(r"(0[xX][0-9A-Fa-f]+|\d+)[uUlL]*")


def lex(text):
    """Return (tokens, comments{line: [text,...]}).  Preprocessor lines become
    single 'pp' tokens; // and /* */ comments are collected per starting line."""
    toks, comments = [], {}
    i, n, line, bol = 0, len(text), 1, True
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            bol = True
            continue
        if c in " \t\r\f":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.setdefault(line, []).append(text[i + 2:j].strip())
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j
            body = text[i + 2:j]
            comments.setdefault(line, []).append(" ".join(body.split()))
            line += body.count("\n")
            i = j + 2
            continue
        if bol and c == "#":
            start_line = line
            parts = []
            while True:
                j = text.find("\n", i)
                j = n if j < 0 else j
                seg = text[i:j]
                if seg.rstrip().endswith("\\"):
                    parts.append(seg.rstrip()[:-1])
                    i = j + 1
                    line += 1
                    continue
                parts.append(seg)
                i = j
                break
            d = " ".join(parts)
            d = re.sub(r"//.*$", "", d).strip()
            toks.append(Tok("pp", d, start_line))
            continue
        bol = False
        if c.isalpha() or c == "_":
            m = _ID_RE.match(text, i)
            toks.append(Tok("id", m.group(0), line))
            i = m.end()
            continue
        if c.isdigit():
            m = _NUM_RE.match(text, i)
            toks.append(Tok("num", m.group(0), line))
            i = m.end()
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            toks.append(Tok("str", text[i:j + 1], line))
            i = j + 1
            continue
        if text.startswith("::", i) or text.startswith("->", i):
            toks.append(Tok("p", text[i:i + 2], line))
            i += 2
            continue
        toks.append(Tok("p", c, line))
        i += 1
    return toks, comments


def num_value(s):
    return int(re.sub(r"[uUlL]+$", "", s), 0)


# --------------------------------------------------------------------------
# Model + parser for D2Structs.h (the C++ subset it uses)
# --------------------------------------------------------------------------

CALLCONV = ("__stdcall", "__fastcall", "__cdecl", "__thiscall")
SPEC_KEYWORDS = ("const", "volatile", "unsigned", "signed", "short", "long")


class Field(object):
    def __init__(self, name, line):
        self.name, self.line = name, line
        self.base = None      # type name (str) or Rec (anonymous pointee / hoisted)
        self.ptr = 0
        self.dims = []        # list of (value, text)
        self.bits = None
        self.func = None      # dict(ret, cc, params) for function pointers
        self.comment = None
        self.const = False
        # filled by layout
        self.off = None
        self.abs_off = None   # offset inside the layout root (set by annotate_abs)
        self.size = None
        self.bitpos = None
        # C-translation bookkeeping
        self.orig = None      # original Field this one was copied from


class Rec(object):
    def __init__(self, kind, name, line):
        self.kind, self.name, self.line = kind, name, line
        self.end_line = line
        self.members = []
        self.pack = None          # None = default packing
        self.pack_line = None     # line of the #pragma that set the pack value
        self.comment = None
        self.anon = name is None
        # layout
        self.off = None           # offset inside parent (inline anonymous members)
        self.size = None
        self.align = None
        self.abs_off = None       # offset inside the layout root (set by annotate_abs)
        # C translation
        self.cname = name


class ParseError(Exception):
    pass


class StructParser(object):
    def __init__(self, toks, comments, fname):
        self.t, self.c, self.fname = toks, comments, fname
        self.pos = 0
        self.pack = None
        self.pack_line = None
        self.pack_stack = []
        self.records = []           # top-level definitions, source order
        self.forward = OrderedDict()  # name -> line of 'struct X;'
        self.byname = {}

    # --- helpers
    def peek(self, k=0):
        p = self.pos + k
        return self.t[p] if p < len(self.t) else Tok("eof", "", -1)

    def take(self, text=None):
        tok = self.peek()
        if text is not None and tok.text != text:
            raise ParseError("%s:%d: expected %r, got %r" % (self.fname, tok.line, text, tok.text))
        self.pos += 1
        return tok

    def comment_at(self, line):
        v = self.c.get(line)
        return " // ".join(v) if v else None

    def pragma(self, tok):
        m = re.match(r"#\s*pragma\s+pack\s*\((.*)\)\s*$", tok.text)
        if not m:
            return
        args = [a.strip() for a in m.group(1).split(",") if a.strip()]
        if not args:
            self.pack, self.pack_line = None, tok.line
        elif args[0] == "push":
            self.pack_stack.append((self.pack, self.pack_line))
            nums = [a for a in args[1:] if re.match(r"^\d+$", a)]
            if nums:
                self.pack, self.pack_line = int(nums[0]), tok.line
        elif args[0] == "pop":
            if self.pack_stack:
                self.pack, self.pack_line = self.pack_stack.pop()
        elif re.match(r"^\d+$", args[0]):
            self.pack, self.pack_line = int(args[0]), tok.line

    # --- grammar
    def parse(self):
        while self.peek().kind != "eof":
            tok = self.peek()
            if tok.kind == "pp":
                self.pragma(tok)
                self.pos += 1
            elif tok.text in ("struct", "union"):
                self.toplevel_record()
            elif tok.text == ";":
                self.pos += 1
            else:
                raise ParseError("%s:%d: unexpected top-level token %r" % (self.fname, tok.line, tok.text))
        return self

    def toplevel_record(self):
        kw = self.take()
        name = None
        if self.peek().kind == "id":
            name = self.take().text
        if self.peek().text == ";":
            self.take(";")
            self.forward.setdefault(name, kw.line)
            return
        rec = self.body(kw.text, name, kw.line)
        hdr = []
        for ln in range(kw.line, rec.brace_line + 1):
            if self.comment_at(ln):
                hdr.append(self.comment_at(ln))
        if self.comment_at(rec.end_line):
            hdr.append(self.comment_at(rec.end_line))
        rec.comment = " // ".join(hdr) if hdr else None
        self.take(";")
        self.records.append(rec)
        self.byname[name] = rec

    def body(self, kind, name, line):
        rec = Rec(kind, name, line)
        rec.pack, rec.pack_line = self.pack, self.pack_line
        rec.brace_line = self.take("{").line
        while self.peek().text != "}":
            self.member(rec)
        rec.end_line = self.take("}").line
        return rec

    def member(self, rec):
        tok = self.peek()
        if tok.kind == "pp":
            self.pragma(tok)
            self.pos += 1
            return
        if tok.text in ("struct", "union") and self.peek(1).text == "{":
            self.take()
            sub = self.body(tok.text, None, tok.line)
            if self.peek().text == ";":
                sub.comment = self.comment_at(sub.end_line) or self.comment_at(sub.brace_line)
                self.take(";")
                rec.members.append(sub)
                return
            self.declarators(rec, sub, False)
            return
        const = False
        base = None
        while self.peek().kind == "id":
            w = self.peek().text
            if w in ("struct", "union", "enum"):
                self.take()
                continue
            if w in SPEC_KEYWORDS:
                self.take()
                if w == "const":
                    const = True
                else:
                    base = (base + " " + w) if base else w
                continue
            if base is None or base in ("unsigned", "signed"):
                base = (base + " " + w) if base else w
                self.take()
                continue
            break
        if base is None:
            raise ParseError("%s:%d: cannot parse member" % (self.fname, tok.line))
        self.declarators(rec, base, const)

    def declarators(self, rec, base, const):
        while True:
            f = self.declarator(base)
            f.const = const
            f.comment = self.comment_at(f.line)
            rec.members.append(f)
            if self.peek().text == ",":
                self.take(",")
                continue
            self.take(";")
            return

    def declarator(self, base):
        ptr = 0
        while self.peek().text == "*":
            self.take()
            ptr += 1
        if self.peek().text == "(":  # function pointer: RET (CC * name)(params)
            self.take("(")
            cc = None
            if self.peek().text in CALLCONV:
                cc = self.take().text
            self.take("*")
            nt = self.take()
            self.take(")")
            self.take("(")
            depth, params = 1, []
            while True:
                t = self.take()
                if t.text == "(":
                    depth += 1
                elif t.text == ")":
                    depth -= 1
                    if depth == 0:
                        break
                params.append(t.text)
            f = Field(nt.text, nt.line)
            f.base = base
            f.func = dict(ret=type_text(base, ptr), cc=cc, params=join_tokens(params))
            return f
        nt = self.take()
        if nt.kind != "id":
            raise ParseError("%s:%d: expected declarator name, got %r" % (self.fname, nt.line, nt.text))
        f = Field(nt.text, nt.line)
        f.base, f.ptr = base, ptr
        while self.peek().text == "[":
            self.take("[")
            d = self.take()
            self.take("]")
            f.dims.append((num_value(d.text), d.text))
        if self.peek().text == ":":
            self.take(":")
            f.bits = num_value(self.take().text)
        return f


def join_tokens(toks):
    out, prev = "", None
    for t in toks:
        if prev is not None:
            pw = bool(_ID_RE.match(prev) or prev[0].isdigit())
            tw = bool(_ID_RE.match(t) or t[0].isdigit())
            if (pw and tw) or prev == "," or (prev == "*" and tw):
                out += " "
        out += t
        prev = t
    return out


def type_text(base, ptr):
    b = base.cname if isinstance(base, Rec) else base
    return b + "*" * ptr


# --------------------------------------------------------------------------
# Primitive (Win32 / C) types: size, alignment for MSVC x86
# --------------------------------------------------------------------------

PRIM = {
    "char": (1, 1), "signed char": (1, 1), "unsigned char": (1, 1), "BYTE": (1, 1), "CHAR": (1, 1),
    "short": (2, 2), "unsigned short": (2, 2), "WORD": (2, 2), "wchar_t": (2, 2),
    "int": (4, 4), "unsigned": (4, 4), "unsigned int": (4, 4), "long": (4, 4), "unsigned long": (4, 4),
    "DWORD": (4, 4), "INT": (4, 4), "BOOL": (4, 4), "LONG": (4, 4), "ULONG_PTR": (4, 4), "size_t": (4, 4),
    "HWND": (4, 4), "HANDLE": (4, 4), "LPVOID": (4, 4), "LPSTR": (4, 4),
    "POINT": (8, 4), "RECT": (16, 4), "CRITICAL_SECTION": (24, 4),
}

# Win32 prelude emitted at the top of d2bs_types.h (C, Ghidra-safe: no
# preprocessor, no typedef of void).  Mirrors the Windows SDK x86 definitions.
PRELUDE = r"""
typedef unsigned char BYTE;
typedef unsigned short WORD;
typedef unsigned long DWORD;
typedef int BOOL;
typedef int INT;
typedef char CHAR;
typedef long LONG;
typedef unsigned long ULONG_PTR;
typedef unsigned int size_t;
typedef void* LPVOID;
typedef char* LPSTR;
typedef void* HANDLE;
typedef struct HWND__ HWND__;
struct HWND__ { int unused; };
typedef HWND__* HWND;
typedef struct tagPOINT { LONG x; LONG y; } POINT;
typedef struct tagRECT { LONG left; LONG top; LONG right; LONG bottom; } RECT;
typedef struct _RTL_CRITICAL_SECTION_DEBUG _RTL_CRITICAL_SECTION_DEBUG;
typedef struct _RTL_CRITICAL_SECTION {
    _RTL_CRITICAL_SECTION_DEBUG* DebugInfo;
    LONG LockCount;
    LONG RecursionCount;
    HANDLE OwningThread;
    HANDLE LockSemaphore;
    ULONG_PTR SpinCount;
} RTL_CRITICAL_SECTION;
typedef RTL_CRITICAL_SECTION CRITICAL_SECTION;
""".strip("\n")

WIN32_SIZED = ("BYTE", "WORD", "DWORD", "BOOL", "INT", "CHAR", "LONG", "ULONG_PTR", "size_t", "LPVOID", "LPSTR",
               "HANDLE", "HWND", "POINT", "RECT", "CRITICAL_SECTION")
PRELUDE_TYPES = ("BYTE", "WORD", "DWORD", "BOOL", "INT", "CHAR", "LONG", "ULONG_PTR", "size_t", "LPVOID",
                 "LPSTR", "HANDLE", "HWND__", "HWND", "tagPOINT", "POINT", "tagRECT", "RECT",
                 "_RTL_CRITICAL_SECTION_DEBUG", "_RTL_CRITICAL_SECTION", "RTL_CRITICAL_SECTION",
                 "CRITICAL_SECTION")
C_BUILTINS = ("void", "char", "short", "int", "long", "unsigned", "signed", "const", "volatile",
              "wchar_t", "float", "double")
# Fake <windows.h> for the clang++ probe of the ORIGINAL header (C++, x86 sizes).
FAKE_WINDOWS_H = "#pragma once\n#define VOID void\n" + PRELUDE.replace(
    "typedef unsigned int size_t;\n", "typedef __SIZE_TYPE__ size_t;\n") + "\n"


# --------------------------------------------------------------------------
# MSVC x86 layout engine (sufficient for the constructs used in D2Structs.h)
# --------------------------------------------------------------------------


def align_up(v, a):
    return (v + a - 1) // a * a


class Layout(object):
    def __init__(self, byname):
        self.byname = byname

    def type_size(self, f):
        if f.func is not None or f.ptr:
            sz, al = 4, 4
        elif isinstance(f.base, Rec):
            sz, al = self.rec(f.base)
        elif f.base in self.byname:
            sz, al = self.rec(self.byname[f.base])
        elif f.base in PRIM:
            sz, al = PRIM[f.base]
        else:
            raise KeyError("unknown type %r (field %s)" % (f.base, f.name))
        n = 1
        for d, _ in f.dims:
            n *= d
        return sz, al, sz * n

    def rec(self, r):
        if r.size is not None:
            return r.size, r.align
        pack = r.pack or DEFAULT_PACK
        maxal = 1
        if r.kind == "struct":
            off, bf = 0, None
            for m in r.members:
                if isinstance(m, Rec):
                    sz, al = self.rec(m)
                    al = min(al, pack)
                    off = align_up(off, al)
                    m.off = off
                    off += sz
                    bf = None
                else:
                    esz, al, sz = self.type_size(m)
                    al = min(al, pack)
                    if m.bits is not None:
                        if bf and bf[1] == esz and bf[2] + m.bits <= esz * 8:
                            m.off, m.bitpos = bf[0], bf[2]
                            bf[2] += m.bits
                        else:
                            off = align_up(off, al)
                            m.off, m.bitpos = off, 0
                            bf = [off, esz, m.bits]
                            off += esz
                        m.size = esz
                    else:
                        bf = None
                        off = align_up(off, al)
                        m.off, m.size = off, sz
                        off += sz
                maxal = max(maxal, al)
            size = align_up(off, maxal)
        else:
            size = 0
            for m in r.members:
                if isinstance(m, Rec):
                    sz, al = self.rec(m)
                    al = min(al, pack)
                else:
                    esz, al, sz = self.type_size(m)
                    al = min(al, pack)
                    if m.bits is not None:
                        m.bitpos, sz = 0, esz
                    m.size = sz
                m.off = 0
                size = max(size, sz)
                maxal = max(maxal, al)
            size = align_up(size, maxal)
        r.size, r.align = size, maxal
        return size, maxal


# --------------------------------------------------------------------------
# Walking the model
# --------------------------------------------------------------------------


def roots_of(records):
    """Layout roots: every named top-level record plus every anonymous record
    reached through a pointer (struct {...} *p).  Returns [(rootname, Rec, cxx_type_expr)]."""
    out = []

    def find_pointees(rec, top):
        for m in rec.members:
            if isinstance(m, Rec):
                find_pointees(m, top)
            elif isinstance(m.base, Rec):
                expr = "__typeof__(*((%s*)0)->%s)" % (top.name, m.name)
                out.append(("%s__%s_t" % (top.name, m.name), m.base, expr, top, m))
                find_pointees(m.base, top)

    for r in records:
        out.append((r.name, r, r.name, r, None))
        find_pointees(r, r)
    return out


def walk(rec, base=0, path=(), depth=0):
    """Yield (kind, obj, abs_off, depth, path) in declaration order.
    kind: 'field' for leaves, 'rec' for inline anonymous records."""
    for m in rec.members:
        if isinstance(m, Rec):
            yield ("rec", m, base + m.off, depth, path)
            for x in walk(m, base + m.off, path + (m,), depth + 1):
                yield x
        else:
            yield ("field", m, base + m.off, depth, path)


def leaves(rec):
    return [(f, off, path) for kind, f, off, depth, path in walk(rec) if kind == "field"]


# --------------------------------------------------------------------------
# C translation (hoist anonymous unions, flatten anonymous structs in structs)
# --------------------------------------------------------------------------


class CModel(object):
    """Holds the translated records, in emission order, plus a mapping from the
    original leaf Field objects to their C member path."""

    def __init__(self, parser):
        self.parser = parser
        self.emit_order = []      # list of Rec (translated), definition order
        self.cpath = {}           # id(orig Field) -> "a.b.c"
        self.root_cname = {}      # id(orig root Rec) -> C type name
        self.hoisted = []         # translated hoisted records
        self.forward_only = [n for n in parser.forward if n not in parser.byname]
        for r in parser.records:
            self.translate_root(r, r.name)

    def translate_root(self, orig, cname):
        out_defs = []
        new = self.translate(orig, cname, cname, (), out_defs, set())
        self.root_cname[id(orig)] = cname
        out_defs.append(new)
        self.emit_order.extend(out_defs)
        return new

    def translate(self, orig, cname, top, cprefix, out_defs, used, absbase=0):
        """Translate record `orig` into a named Rec `cname`.  `cprefix` is the C
        member path from the layout root down to this record."""
        new = Rec(orig.kind, cname, orig.line)
        new.anon = False
        new.pack, new.pack_line = orig.pack, orig.pack_line
        new.end_line, new.comment = orig.end_line, orig.comment
        new.orig = orig
        self._members(orig, new, top, cprefix, out_defs, used if orig.kind == "struct" else set(), absbase)
        return new

    def _members(self, orig, new, top, cprefix, out_defs, used, absbase):
        for m in orig.members:
            if isinstance(m, Rec):
                aoff = absbase + m.off
                if orig.kind == "struct" and m.kind == "struct":
                    # anonymous struct directly inside a struct: splice members
                    self._members(m, new, top, cprefix, out_defs, used, aoff)
                    continue
                base = ("u_" if m.kind == "union" else "s_") + "%02X" % aoff
                nm, k = base, 1
                while nm in used:
                    nm = "%s_%d" % (base, k)
                    k += 1
                used.add(nm)
                tname = "%s__%s" % (new.cname, nm)
                sub = self.translate(m, tname, top, cprefix + (nm,), out_defs, set(), aoff)
                out_defs.append(sub)
                self.hoisted.append(sub)
                f = Field(nm, m.line)
                f.base = sub
                f.comment = m.comment
                f.orig = m
                new.members.append(f)
            else:
                used.add(m.name)
                f = Field(m.name, m.line)
                f.ptr, f.dims, f.bits, f.func, f.comment, f.const = m.ptr, list(m.dims), m.bits, m.func, m.comment, m.const
                f.orig = m
                if isinstance(m.base, Rec):
                    pname = "%s__%s_t" % (top, m.name)
                    sub = self.translate(m.base, pname, pname, (), out_defs, set(), 0)
                    out_defs.append(sub)
                    self.hoisted.append(sub)
                    self.root_cname[id(m.base)] = pname
                    m.base.cname = pname
                    f.base = sub
                else:
                    f.base = m.base
                self.cpath[id(m)] = ".".join(cprefix + (m.name,))
                new.members.append(f)

    def all_names(self):
        names = [r.cname for r in self.emit_order]
        return names + self.forward_only


def c_field_decl(f):
    if f.func is not None:
        params = f.func["params"].strip() or "void"
        cc = (f.func["cc"] + " ") if f.func["cc"] else ""
        # 'RET CC (*name)(...)': CParser drops CC when written 'RET (CC *name)(...)'
        return "%s %s(*%s)(%s)" % (f.func["ret"], cc, f.name, params)
    base = f.base.cname if isinstance(f.base, Rec) else f.base
    s = ("const " if f.const else "") + base + "*" * f.ptr + " " + f.name
    s += "".join("[%s]" % t for _, t in f.dims)
    if f.bits is not None:
        s += " : %d" % f.bits
    return s


def claimed_offset(comment):
    if not comment:
        return None
    m = re.match(r"^\s*\+?\s*(0[xX][0-9A-Fa-f]+)\b", comment)
    if m:
        return int(m.group(1), 16)
    m = re.match(r"^\s*\+([0-9A-Fa-f]+)\b", comment)
    if m:
        return int(m.group(1), 16)
    return None


def claimed_size(comment):
    if not comment:
        return None
    m = re.search(r"size\s*=\s*(0[xX][0-9A-Fa-f]+|\d+)", comment)
    return int(m.group(1), 0) if m else None


def emit_header(parser, cmodel, ptrs, out_path):
    L = []
    w = L.append
    w("/*")
    w(" * d2bs_types.h - GENERATED by docs/ghidra/tools/gen_types.py from %s." % STRUCTS_H)
    w(" * Do not edit; re-run the generator.  Documentation: docs/memory/structs.md")
    w(" *")
    w(" * Target: Diablo II 1.14d Game.exe, x86, MSVC layout (default /Zp8 except the")
    w(" * #pragma pack(push, 1) regions, which mirror the pack(1) regions of %s)." % STRUCTS_H)
    w(" * Dialect: plain C, no preprocessor, for Ghidra's C parser (CParser).")
    w(" *  - '#pragma pack(push, 1)' / '#pragma pack(pop)' are interpreted by CParser")
    w(" *    itself (PragmaSpecifier in C.jj).  The bare '#pragma pack(push)' form used")
    w(" *    in the C++ source is NOT used here: CParser only pushes when a value or")
    w(" *    identifier follows 'push', so the later pop would not restore packing.")
    w(" *  - wchar_t is not defined here: Ghidra provides it as a built-in (2 bytes on")
    w(" *    Windows data organisations).  A C compiler needs it typedef'd first.")
    w(" *  - VOID is a macro in winnt.h ('#define VOID void') and is deliberately not")
    w(" *    defined: CParser accepts 'typedef void VOID;' but then fails on a '(VOID)'")
    w(" *    parameter list.  Replace the token VOID with void before parsing prototypes.")
    w(" *  - Function pointers are written 'RET __stdcall (*name)(...)'.  Written as")
    w(" *    'RET (__stdcall *name)(...)' (the source's form) CParser drops the calling")
    w(" *    convention; clang treats both forms the same.")
    w(" *  - Anonymous unions of the C++ source become named union types")
    w(" *    <Outer>__u_<OFF> with member u_<OFF> (OFF = hex offset in the outer root);")
    w(" *    anonymous structs inside unions become <...>__s_<OFF>[_n] / member s_<OFF>[_n];")
    w(" *    anonymous structs directly inside a struct are flattened (same offsets);")
    w(" *    'struct {...} *p' members point to <Outer>__p_t.")
    w(" *  - CParser stores types with DataTypeConflictHandler.REPLACE_HANDLER (addDef in")
    w(" *    C.jj): parsing this file again replaces same-named types in the same category.")
    w(" *  - Offsets in comments are computed (MSVC x86) and verified with clang by")
    w(" *    'gen_types.py --check' (add --ghidra-install DIR to also verify with")
    w(" *    Ghidra's CParser).  'src says' marks a source comment that disagrees.")
    w(" */")
    w("")
    w("/* ---- Win32 prelude (x86 Windows SDK equivalents) ---- */")
    w(PRELUDE)
    w("")
    w("/* ---- forward typedefs (so that X* works before X is defined) ---- */")
    for r in cmodel.emit_order:
        w("typedef %s %s %s;" % (r.kind, r.cname, r.cname))
    for n in cmodel.forward_only:
        w("typedef struct %s %s; /* only forward-declared in %s:%d; layout unknown */" % (
            n, n, STRUCTS_H, parser.forward[n]))
    w("")
    cbs = callback_typedefs(ptrs)
    if cbs:
        w("/* ---- function-pointer parameter types used by %s prototypes ---- */" % PTRS_H)
        for name, decl, line, _ in cbs:
            w("typedef %s; /* %s:%d */" % (decl, PTRS_H, line))
        w("")
    w("/* ---- structures (source order; hoisted anonymous types precede their owner) ---- */")
    cur_pack = None
    for r in cmodel.emit_order:
        if r.pack != cur_pack:
            if cur_pack is not None:
                w("#pragma pack(pop)")
                w("")
            if r.pack is not None:
                w("#pragma pack(push, %d) /* %s:%d */" % (r.pack, STRUCTS_H, r.pack_line))
            cur_pack = r.pack
        orig = r.orig
        size = orig.size
        src = "%s:%d" % (STRUCTS_H, orig.line)
        extra = ""
        if orig.anon:
            extra = " (anonymous in source)"
        w("/* %s%s, sizeof 0x%X, align %d */" % (src, extra, size, orig.align))
        w("%s %s {" % (r.kind, r.cname))
        for f, off in c_members_with_offsets(r):
            decl = c_field_decl(f)
            note = "+0x%03X" % off
            if f.bits is not None:
                note += " bit %d" % f.orig.bitpos
            note += "  %s:%d" % (STRUCTS_H, f.line)
            claim = claimed_offset(f.comment)
            if claim is not None and claim != off:
                note += "  (src says 0x%X)" % claim
            w("    %-44s /* %s */" % (decl + ";", note))
        w("};")
        w("")
    if cur_pack is not None:
        w("#pragma pack(pop)")
        w("")
    text = "\n".join(L).rstrip("\n") + "\n"
    with open(out_path, "w") as fh:
        fh.write(text)
    return text


def c_members_with_offsets(r):
    """Members of a translated record with offsets relative to the layout root
    the source comments use (root for named records; owner root for hoisted)."""
    out = []
    for f in r.members:
        o = f.orig
        out.append((f, o.abs_off))
    return out


def annotate_abs(parser):
    """Set .abs_off on every original Field / inline Rec, relative to its layout root."""
    for rootname, rec, expr, top, via in roots_of(parser.records):
        for kind, obj, off, depth, path in walk(rec):
            obj.abs_off = off


# --------------------------------------------------------------------------
# D2Ptrs.h: macro invocations and referenced type identifiers
# --------------------------------------------------------------------------


class PtrEntry(object):
    def __init__(self, macro, dll, name, args, line):
        self.macro, self.dll, self.name, self.args, self.line = macro, dll, name, args, line

    @property
    def symbol(self):
        return ("p_" if self.macro == "VARPTR" else "") + "%s_%s" % (self.dll, self.name)


def split_args(toks):
    args, cur, depth = [], [], 0
    for t in toks:
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        if t.text == "," and depth == 0:
            args.append(cur)
            cur = []
        else:
            cur.append(t)
    args.append(cur)
    return args


def parse_ptrs(repo):
    with open(os.path.join(repo, PTRS_H)) as fh:
        toks, _ = lex(fh.read())
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t.kind == "id" and t.text in ("FUNCPTR", "VARPTR", "ASMPTR") and i + 1 < len(toks) and toks[i + 1].text == "(":
            j, depth = i + 1, 0
            while True:
                if toks[j].text == "(":
                    depth += 1
                elif toks[j].text == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            args = split_args(toks[i + 2:j])
            out.append(PtrEntry(t.text, args[0][0].text, args[1][0].text, args, t.line))
            i = j + 1
            continue
        i += 1
    return out


def type_idents(toks):
    """Classify identifiers of a type / parameter-list token sequence.
    Returns list of (ident, is_declarator_name).  An identifier is a declarator
    (parameter or function) name when it follows a type/'*' and precedes
    ',', ')', '[' or '('; a lone type such as '(DWORD)' or '(Control*, DWORD)'
    is not a name."""
    res = []
    for k, t in enumerate(toks):
        if t.kind != "id" or t.text in CALLCONV:
            continue
        nxt = toks[k + 1].text if k + 1 < len(toks) else ""
        prev = toks[k - 1].text if k > 0 else ""
        is_decl = nxt in (",", ")", "[", "(") and prev not in ("(", ",", "")
        res.append((t.text, is_decl))
    return res


def ptrs_type_refs(ptrs):
    """Map type identifier -> list of (symbol, line, role)."""
    refs = OrderedDict()
    for e in ptrs:
        if e.macro == "FUNCPTR":
            parts = [("ret", e.args[2]), ("param", e.args[3])]
        elif e.macro == "VARPTR":
            parts = [("var", e.args[2])]
        else:
            continue
        for role, toks in parts:
            for ident, is_decl in type_idents(toks):
                if is_decl:
                    continue
                refs.setdefault(ident, []).append((e.symbol, e.line, role))
    return refs


def callback_typedefs(ptrs):
    """Function-pointer parameters in FUNCPTR prototypes -> typedefs
    <DLL>_<Name>_<param>_t."""
    out = []
    for e in ptrs:
        if e.macro != "FUNCPTR":
            continue
        toks = e.args[3]
        # params are inside the outer parentheses
        inner = toks[1:-1]
        for p in split_args(inner):
            txt = [t.text for t in p]
            if "(" in txt and "*" in txt:
                # RET ( CC * NAME ) ( PARAMS )
                o = txt.index("(")
                ret = join_tokens(txt[:o])
                k = o + 1
                cc = None
                if txt[k] in CALLCONV:
                    cc = txt[k]
                    k += 1
                assert txt[k] == "*"
                pname = txt[k + 1]
                assert txt[k + 2] == ")" and txt[k + 3] == "("
                params = join_tokens(txt[k + 4:-1]) or "void"
                tname = "%s_%s_%s_t" % (e.dll, e.name, pname)
                decl = "%s %s(*%s)(%s)" % (ret, (cc + " ") if cc else "", tname, params)
                out.append((tname, decl, e.line, "%s (%s*)(%s)" % (ret, (cc + " ") if cc else "", params)))
    return out


def tsv_type_refs(repo):
    """Type identifiers used by the FUNC prototypes / DATA types of
    docs/ghidra/d2bs_symbols.tsv (columns: kind, module, name, rva, type, ...),
    if that file exists.  Returns {ident: [symbol, ...]} or None."""
    path = os.path.join(repo, SYMBOLS_TSV)
    if not os.path.exists(path):
        return None
    refs = OrderedDict()
    with open(path) as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")]
    if not rows:
        return refs
    header = [h.strip().lower() for h in rows[0]]
    ki, ni, ti = header.index("kind"), header.index("name"), header.index("type")
    for cells in rows[1:]:
        if len(cells) <= ti or cells[ki] not in ("FUNC", "DATA"):
            continue
        toks, _ = lex(cells[ti])
        for ident, is_decl in type_idents(toks):
            if not is_decl:
                refs.setdefault(ident, []).append(cells[ni])
    return refs


# --------------------------------------------------------------------------
# clang ground truth
# --------------------------------------------------------------------------


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return p.returncode, p.stdout, p.stderr


def parse_ir_consts(ll):
    vals = {}
    for m in re.finditer(r"^@(\w+) = [^\n]*?constant i32 (-?\d+)", ll, re.M):
        vals[m.group(1)] = int(m.group(2)) & 0xFFFFFFFF
    return vals


def parse_bitfields(dump):
    """{(toprecord, fieldname): (byte_off, first_bit, last_bit)} from -fdump-record-layouts."""
    out = {}
    top = None
    for line in dump.splitlines():
        if line.startswith("*** Dumping AST Record Layout"):
            top = None
            continue
        m = re.match(r"^\s*(\d+)(?::(\d+)-(\d+))?\s+\|\s(\s*)(.*?)\s*$", line)
        if not m:
            continue
        if top is None:
            mm = re.match(r"^(?:struct|union|class)\s+(\S+)$", m.group(5))
            top = mm.group(1) if mm else "?anonymous"
            continue
        if m.group(2) is not None and not top.startswith("?"):
            name = m.group(5).split()[-1]
            key = (top, name)
            if key in out:
                raise RuntimeError("ambiguous bit-field %s.%s" % key)
            out[key] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return out


class Truth(object):
    """Layouts of the ORIGINAL D2Structs.h as compiled by clang for MSVC x86."""

    def __init__(self, repo, parser, work, clangxx):
        self.sizes, self.aligns, self.offs, self.fsizes, self.bits, self.win32 = {}, {}, {}, {}, {}, {}
        shim = os.path.join(work, "shim")
        os.makedirs(shim, exist_ok=True)
        with open(os.path.join(shim, "windows.h"), "w") as fh:
            fh.write(FAKE_WINDOWS_H)
        lines = ['#include <windows.h>', '#include "%s"' % STRUCTS_H,
                 '#define P(n, e) extern "C" const unsigned int n = (unsigned int)(e);']
        keys = {}
        k = 0
        for rootname, rec, expr, top, via in roots_of(parser.records):
            keys["S%d" % k] = ("size", rootname, None)
            lines.append("P(S%d, sizeof(%s))" % (k, expr))
            keys["A%d" % k] = ("align", rootname, None)
            lines.append("P(A%d, alignof(%s))" % (k, expr))
            for f, off, path in leaves(rec):
                if f.bits is not None:
                    continue
                keys["O%d_%s" % (k, f.name)] = ("off", rootname, f.name)
                lines.append("P(O%d_%s, __builtin_offsetof(%s, %s))" % (k, f.name, expr, f.name))
                keys["F%d_%s" % (k, f.name)] = ("fsize", rootname, f.name)
                lines.append("P(F%d_%s, sizeof(((%s*)0)->%s))" % (k, f.name, expr, f.name))
            k += 1
        for t in WIN32_SIZED:
            keys["W_" + t] = ("win32", t, None)
            lines.append("P(W_%s, sizeof(%s))" % (t, t))
        src = os.path.join(work, "truth_probe.cpp")
        with open(src, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        base = [clangxx, "--target=i686-pc-windows-msvc", "-fms-extensions", "-fms-compatibility",
                "-std=c++14", "-I", shim, "-I", repo]
        self.cmd_ir = base + ["-S", "-emit-llvm", "-O0", "-o", os.path.join(work, "truth_probe.ll"), src]
        rc, out, err = run(self.cmd_ir)
        if rc != 0:
            raise RuntimeError("clang++ probe failed:\n" + err)
        with open(os.path.join(work, "truth_probe.ll")) as fh:
            vals = parse_ir_consts(fh.read())
        for key, (what, rootname, fname) in keys.items():
            v = vals[key]
            if what == "size":
                self.sizes[rootname] = v
            elif what == "align":
                self.aligns[rootname] = v
            elif what == "off":
                self.offs[(rootname, fname)] = v
            elif what == "win32":
                self.win32[rootname] = v
            else:
                self.fsizes[(rootname, fname)] = v
        self.cmd_dump = base + ["-fsyntax-only", "-Xclang", "-fdump-record-layouts-complete", src]
        rc, out, err = run(self.cmd_dump)
        if rc != 0:
            raise RuntimeError("clang++ layout dump failed:\n" + err)
        with open(os.path.join(work, "truth_layouts.txt"), "w") as fh:
            fh.write(out)
        self.bits = parse_bitfields(out)
        self.clang_version = run([clangxx, "--version"])[1].splitlines()[0]


def compare_python_vs_truth(parser, truth):
    errs = []
    for t, v in truth.win32.items():
        if PRIM[t][0] != v:
            errs.append("sizeof %s: python %d clang %d" % (t, PRIM[t][0], v))
    for rootname, rec, expr, top, via in roots_of(parser.records):
        if truth.sizes[rootname] != rec.size:
            errs.append("sizeof %s: python 0x%X clang 0x%X" % (rootname, rec.size, truth.sizes[rootname]))
        if truth.aligns[rootname] != rec.align:
            errs.append("alignof %s: python %d clang %d" % (rootname, rec.align, truth.aligns[rootname]))
        for f, off, path in leaves(rec):
            if f.bits is not None:
                tb = truth.bits.get((top.name, f.name))
                if tb != (off, f.bitpos, f.bitpos + f.bits - 1):
                    errs.append("bitfield %s.%s: python %r clang %r" % (rootname, f.name,
                                                                       (off, f.bitpos, f.bitpos + f.bits - 1), tb))
                continue
            t = truth.offs[(rootname, f.name)]
            if t != off:
                errs.append("offset %s.%s: python 0x%X clang 0x%X" % (rootname, f.name, off, t))
            if truth.fsizes[(rootname, f.name)] != f.size:
                errs.append("size %s.%s: python %d clang %d" % (rootname, f.name, f.size, truth.fsizes[(rootname, f.name)]))
    return errs


def check_c_header(repo, parser, cmodel, truth, header, work, clang, ptrs):
    """Compile the generated header as C with static asserts from the truth."""
    lines = ["/* generated by gen_types.py --check */", "typedef unsigned short wchar_t;",
             '#include "%s"' % os.path.abspath(header), ""]
    n_off = n_size = n_align = 0
    root_ids = set(id(rec) for rn, rec, e, t, v in roots_of(parser.records))
    for t, v in truth.win32.items():
        lines.append('_Static_assert(sizeof(%s) == %d, "sizeof %s");' % (t, v, t))
        n_size += 1
    for rootname, rec, expr, top, via in roots_of(parser.records):
        cname = cmodel.root_cname[id(rec)]
        lines.append('_Static_assert(sizeof(%s) == 0x%X, "sizeof %s");' % (cname, truth.sizes[rootname], cname))
        lines.append('_Static_assert(_Alignof(%s) == %d, "alignof %s");' % (cname, truth.aligns[rootname], cname))
        n_size += 1
        n_align += 1
        for f, off, path in leaves(rec):
            if f.bits is not None:
                continue
            cp = cmodel.cpath[id(f)]
            lines.append('_Static_assert(__builtin_offsetof(%s, %s) == 0x%X, "%s.%s");' % (
                cname, cp, truth.offs[(rootname, f.name)], cname, cp))
            n_off += 1
    n_cc = 0
    for rootname, rec, expr, top, via in roots_of(parser.records):
        cname = cmodel.root_cname[id(rec)]
        for f, off, path in leaves(rec):
            if f.func is None:
                continue
            want = "%s (%s*)(%s)" % (f.func["ret"], (f.func["cc"] + " ") if f.func["cc"] else "",
                                     f.func["params"].strip() or "void")
            lines.append('_Static_assert(__builtin_types_compatible_p(__typeof__(((%s*)0)->%s), %s), "cc %s.%s");' % (
                cname, cmodel.cpath[id(f)], want, cname, f.name))
            n_cc += 1
    for tname, decl, line, want in callback_typedefs(ptrs):
        lines.append('_Static_assert(__builtin_types_compatible_p(%s, %s), "cc %s");' % (tname, want, tname))
        n_cc += 1
    for r in cmodel.hoisted:
        if id(r.orig) in root_ids:
            continue  # pointee roots are asserted above
        lines.append('_Static_assert(sizeof(%s) == 0x%X, "sizeof %s");' % (r.cname, r.orig.size, r.cname))
        n_size += 1
    src = os.path.join(work, "check_types.c")
    with open(src, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    cmd = [clang, "-x", "c", "-std=c11", "--target=i686-pc-windows-msvc", "-fsyntax-only",
           "-Wall", "-Wextra", "-Werror", "-Xclang", "-fdump-record-layouts-complete", src]
    rc, out, err = run(cmd)
    errs = []
    if rc != 0:
        errs.append("C compile of generated header failed:\n" + err)
        return errs, cmd, n_off, n_size, n_align, 0, n_cc
    cbits = parse_bitfields(out)
    n_bits = 0
    for rootname, rec, expr, top, via in roots_of(parser.records):
        cname = cmodel.root_cname[id(rec)]
        for f, off, path in leaves(rec):
            if f.bits is None:
                continue
            n_bits += 1
            want = truth.bits[(top.name, f.name)]
            got = cbits.get((cname, f.name))
            if got != want:
                errs.append("bitfield %s.%s: C %r, C++ %r" % (cname, f.name, got, want))
    return errs, cmd, n_off, n_size, n_align, n_bits, n_cc


def check_type_coverage(repo, cmodel, ptrs):
    defined = set(cmodel.all_names()) | set(PRELUDE_TYPES) | set(C_BUILTINS)
    defined |= set(c[0] for c in callback_typedefs(ptrs))
    problems, special = [], []
    for ident, uses in ptrs_type_refs(ptrs).items():
        if ident in defined:
            continue
        if ident == "VOID":
            special.append("VOID used by %d D2Ptrs.h prototypes (macro in winnt.h; replace with void)" % len(uses))
            continue
        problems.append("%s (D2Ptrs.h:%d %s)" % (ident, uses[0][1], uses[0][0]))
    tsv = tsv_type_refs(repo)
    if tsv is not None:
        for ident, uses in tsv.items():
            if ident in defined or ident == "VOID":
                continue
            problems.append("%s (%s, row %s)" % (ident, SYMBOLS_TSV, uses[0]))
    return problems, special, tsv is not None


# --------------------------------------------------------------------------
# Optional: parse the header with Ghidra's own CParser (--ghidra-cp / --ghidra-install)
# --------------------------------------------------------------------------

GHIDRA_HARNESS = r"""
import ghidra.app.util.cparser.C.CParser;
import ghidra.program.model.data.*;
import java.io.*;
import java.util.*;

/** Generated by gen_types.py: parse C files with Ghidra's CParser into a stand-alone data type
 *  manager that uses the data organisation of x86win.cspec, then dump every composite. */
public class D2bsParseHeader {
    public static void main(String[] a) throws Exception {
        ghidra.framework.Application.initializeApplication(
            new utility.application.DummyApplicationLayout("d2bs"), new ghidra.framework.ApplicationConfiguration());
        DataOrganizationImpl org = DataOrganizationImpl.getDefaultOrganization(null);
        org.setAbsoluteMaxAlignment(0); org.setMachineAlignment(8); org.setDefaultAlignment(1);
        org.setDefaultPointerAlignment(4); org.setPointerSize(4); org.setWideCharSize(2);
        org.setShortSize(2); org.setIntegerSize(4); org.setLongSize(4); org.setLongLongSize(8);
        org.setFloatSize(4); org.setDoubleSize(8); org.setLongDoubleSize(8);
        org.setSizeAlignment(1, 1); org.setSizeAlignment(2, 2); org.setSizeAlignment(4, 4); org.setSizeAlignment(8, 8);
        BitFieldPackingImpl bfp = new BitFieldPackingImpl(); bfp.setUseMSConvention(true); org.setBitFieldPacking(bfp);
        StandAloneDataTypeManager dtm = new StandAloneDataTypeManager("d2bs", org);
        int tx = dtm.startTransaction("parse");
        // A running Ghidra finds wchar_t in BuiltInDataTypeManager (filled by ClassSearcher, which
        // does not run here), so provide the same built-in type.
        dtm.resolve(WideCharDataType.dataType, null);
        CParser p = new CParser(dtm, true, null);
        p.setParseFileName(a[1]);
        String exc = "";
        try (InputStream in = new FileInputStream(a[1])) {
            p.parse(in);
        } catch (Throwable t) {
            exc = String.valueOf(t).replace('\n', ' ');
        }
        dtm.endTransaction(tx, true);
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        out.println("S\t" + p.didParseSucceed() + "\t" + exc);
        String msgs = p.getParseMessages();
        if (msgs != null)
            for (String m : msgs.split("\n"))
                if (!m.trim().isEmpty()) out.println("M\t" + m.trim());
        Iterator<Composite> it = dtm.getAllComposites();
        while (it.hasNext()) {
            Composite c = it.next();
            out.println("C\t" + c.getName() + "\t" + c.getLength() + "\t" + c.getAlignment() + "\t"
                + c.getPackingType() + "\t" + c.getExplicitPackingValue());
            for (DataTypeComponent dtc : c.getDefinedComponents()) {
                String bf = "";
                if (dtc.isBitFieldComponent()) {
                    BitFieldDataType b = (BitFieldDataType) dtc.getDataType();
                    bf = b.getBitOffset() + ":" + b.getBitSize();
                }
                out.println("F\t" + c.getName() + "\t" + dtc.getFieldName() + "\t" + dtc.getOffset() + "\t"
                    + dtc.getLength() + "\t" + dtc.getDataType().getDisplayName() + "\t" + bf);
            }
        }
        Iterator<DataType> all = dtm.getAllDataTypes();
        while (all.hasNext()) {
            DataType d = all.next();
            if (d instanceof FunctionDefinition)
                out.println("P\t" + d.getName() + "\t" + ((FunctionDefinition) d).getPrototypeString(true));
        }
        out.close();
        dtm.close();
    }
}
"""


def ghidra_classpath(a):
    if a.ghidra_cp:
        return a.ghidra_cp
    import glob
    jars = sorted(glob.glob(os.path.join(a.ghidra_install, "Ghidra", "Framework", "*", "lib", "*.jar")))
    jars += sorted(glob.glob(os.path.join(a.ghidra_install, "Ghidra", "Features", "Base", "lib", "*.jar")))
    return os.pathsep.join(jars)


def read_ghidra_dump(path):
    d = dict(ok=False, exc="", msgs=[], comps=OrderedDict(), fields={}, protos={})
    with open(path) as fh:
        for ln in fh:
            p = ln.rstrip("\n").split("\t")
            if p[0] == "S":
                d["ok"] = p[1] == "true" and not p[2]
                d["exc"] = p[2]
            elif p[0] == "M":
                d["msgs"].append(p[1])
            elif p[0] == "C":
                d["comps"][p[1]] = dict(len=int(p[2]), align=int(p[3]), pack=p[4], packval=int(p[5]))
                d["fields"].setdefault(p[1], {})
            elif p[0] == "F":
                d["fields"].setdefault(p[1], {})[p[2]] = dict(off=int(p[3]), len=int(p[4]), type=p[5], bf=p[6])
            elif p[0] == "P":
                d["protos"][p[1]] = p[2]
    return d


def ghidra_check(repo, parser, cmodel, truth, header, work, cp, ptrs):
    """Returns (errors, info).  info has counts and probe results for the docs."""
    errs, info = [], OrderedDict()
    hdir = os.path.join(work, "ghidra")
    os.makedirs(hdir, exist_ok=True)
    src = os.path.join(hdir, "D2bsParseHeader.java")
    with open(src, "w") as fh:
        fh.write(GHIDRA_HARNESS.lstrip())
    javac, java = find_tool(["javac"]), find_tool(["java"])
    if not javac or not java:
        return ["javac/java not found"], info
    rc, out, err = run([javac, "-nowarn", "-proc:none", "-cp", cp, "-d", hdir, src])
    if rc != 0:
        return ["javac of the Ghidra harness failed:\n" + err[-3000:]], info
    jcp = hdir + os.pathsep + cp

    def parse(path, tag):
        dump = os.path.join(hdir, tag + ".tsv")
        rc, out, err = run([java, "-cp", jcp, "D2bsParseHeader", dump, path], cwd=hdir)
        if rc != 0 or not os.path.exists(dump):
            raise RuntimeError("Ghidra harness failed on %s:\n%s" % (path, (out + err)[-3000:]))
        return read_ghidra_dump(dump)

    # 1. the header itself, compared field by field with the clang truth
    g = parse(os.path.abspath(header), "header")
    if not g["ok"]:
        errs.append("CParser rejected %s: %s" % (header, g["exc"]))
    if g["msgs"]:
        errs.append("CParser messages: " + " | ".join(g["msgs"][:10]))
    n = nb = 0
    for rootname, rec, expr, top, via in roots_of(parser.records):
        cname = cmodel.root_cname[id(rec)]
        c = g["comps"].get(cname)
        if c is None:
            errs.append("Ghidra: composite %s missing" % cname)
            continue
        if c["len"] != truth.sizes[rootname] or c["align"] != truth.aligns[rootname]:
            errs.append("Ghidra: %s length/alignment %d/%d, expected %d/%d" % (
                cname, c["len"], c["align"], truth.sizes[rootname], truth.aligns[rootname]))
        for f, off, path in leaves(rec):
            segs = cmodel.cpath[id(f)].split(".")
            cur, acc, comp = cname, 0, None
            for k, sname in enumerate(segs):
                comp = g["fields"].get(cur, {}).get(sname)
                if comp is None:
                    break
                acc += comp["off"]
                cur = comp["type"]
            if comp is None:
                errs.append("Ghidra: %s.%s missing" % (cname, ".".join(segs)))
                continue
            n += 1
            if f.bits is not None:
                nb += 1
                bo, bs = (int(x) for x in comp["bf"].split(":"))
                want = truth.bits[(top.name, f.name)]
                if (acc, bo, bs) != (want[0], want[1], want[2] - want[1] + 1):
                    errs.append("Ghidra: bit-field %s.%s at %r, expected %r" % (cname, f.name, (acc, bo, bs), want))
            else:
                if acc != truth.offs[(rootname, f.name)] or comp["len"] != truth.fsizes[(rootname, f.name)]:
                    errs.append("Ghidra: %s.%s at 0x%X size %d, expected 0x%X size %d" % (
                        cname, ".".join(segs), acc, comp["len"], truth.offs[(rootname, f.name)],
                        truth.fsizes[(rootname, f.name)]))
    packed = sum(1 for r in parser.records if r.pack)
    gpacked = sum(1 for r in parser.records if g["comps"].get(r.name, {}).get("packval") == 1)
    if packed != gpacked:
        errs.append("Ghidra: %d structs have explicit pack 1, expected %d" % (gpacked, packed))
    cc_ok = all("__stdcall" in g["protos"].get(t, "") for t, _, _, _ in callback_typedefs(ptrs))
    if not cc_ok:
        errs.append("Ghidra: callback typedef lost its calling convention")
    info.update(composites=len(roots_of(parser.records)), fields=n, bitfields=nb, packed=gpacked)

    # 2. header + every FUNC prototype / DATA type of d2bs_symbols.tsv
    tsvp = os.path.join(repo, SYMBOLS_TSV)
    if os.path.exists(tsvp):
        with open(header) as fh:
            body = [fh.read(), "/* ---- prototypes and data from %s ---- */" % SYMBOLS_TSV]
        nf = nd = nd_untyped = 0
        names = []
        with open(tsvp) as fh:
            rows = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")]
        hdr = [h.lower() for h in rows[0]]
        ki, ni, ti = hdr.index("kind"), hdr.index("name"), hdr.index("type")
        for cells in rows[1:]:
            if cells[ki] == "FUNC":
                body.append(re.sub(r"\bVOID\b", "void", cells[ti]) + ";")
                names.append(cells[ni])
                nf += 1
            elif cells[ki] == "DATA" and cells[ti].strip():
                body.append("%s %s;" % (re.sub(r"\bVOID\b", "void", cells[ti]), "d2bs_data_" + cells[ni]))
                nd += 1
            elif cells[ki] == "DATA":
                nd_untyped += 1
        pth = os.path.join(hdir, "header_plus_symbols.h")
        with open(pth, "w") as fh:
            fh.write("\n".join(body) + "\n")
        g2 = parse(pth, "symbols")
        missing = [x for x in names if x not in g2["protos"]]
        if not g2["ok"] or g2["msgs"] or missing:
            errs.append("Ghidra: header + %s: ok=%s exc=%s msgs=%s missing=%s" % (
                SYMBOLS_TSV, g2["ok"], g2["exc"], g2["msgs"][:5], missing[:5]))
        info.update(tsv_funcs=nf, tsv_data=nd, tsv_data_untyped=nd_untyped, tsv_funcs_parsed=nf - len(missing),
                    tsv_stdcall=sum(1 for x in names if "__stdcall" in g2["protos"].get(x, "")),
                    tsv_fastcall=sum(1 for x in names if "__fastcall" in g2["protos"].get(x, "")),
                    tsv_cdecl=sum(1 for x in names if "__cdecl" in g2["protos"].get(x, "")))

    # 3. probes for the packing claims made in the docs
    probes = OrderedDict([
        ("bare_push", "#pragma pack(push)\n#pragma pack(1)\nstruct A { char c; int i; };\n#pragma pack(pop)\n"
                      "struct B { char c; int i; };\n"),
        ("push_1", "#pragma pack(push, 1)\nstruct A { char c; int i; };\n#pragma pack(pop)\n"
                   "struct B { char c; int i; };\n"),
        ("attr_packed", "struct __attribute__((packed)) A { char c; int i; };\nstruct B { char c; int i; };\n"),
        ("void_typedef", "typedef void VOID;\nvoid __stdcall f(VOID);\nstruct A { char c; int i; };\nstruct B { char c; int i; };\n"),
        ("cc_inside", "typedef int (__stdcall *A_t)(int);\ntypedef int __stdcall (*B_t)(int);\n"
                      "struct A { char c; int i; };\nstruct B { char c; int i; };\n"),
    ])
    for tag, text in probes.items():
        pth = os.path.join(hdir, "probe_%s.h" % tag)
        with open(pth, "w") as fh:
            fh.write(text)
        gp = parse(pth, "probe_" + tag)
        info["probe_" + tag] = dict(ok=gp["ok"], A=gp["comps"].get("A", {}).get("len"),
                                    B=gp["comps"].get("B", {}).get("len"),
                                    A_t=gp["protos"].get("A_t"), B_t=gp["protos"].get("B_t"))
    pr = info
    if not (pr["probe_bare_push"]["B"] == 5 and pr["probe_push_1"]["B"] == 8 and pr["probe_attr_packed"]["A"] == 8
            and not pr["probe_void_typedef"]["ok"] and "__stdcall" not in (pr["probe_cc_inside"]["A_t"] or "")
            and "__stdcall" in (pr["probe_cc_inside"]["B_t"] or "")):
        errs.append("Ghidra probes no longer match the documented CParser behaviour: %r" % (
            {k: v for k, v in info.items() if k.startswith("probe_")},))
    return errs, info


# --------------------------------------------------------------------------
# structs.md
# --------------------------------------------------------------------------

DOMAINS = OrderedDict([
    ("units", ("Units & paths", ["UnitAny", "UnitHashTable", "PlayerData", "QuestInfo", "Waypoint", "MonsterData",
                                 "MonsterTxt", "ObjectData", "ObjectTxt", "Path", "ItemPath", "ObjectPath",
                                 "UnitInteraction", "Light", "OverheadMsg"])),
    ("items", ("Items & inventory", ["ItemData", "ItemTxt", "Inventory", "InventoryInfo", "InventoryLayout"])),
    ("world", ("Rooms, levels, acts & collision", ["Act", "ActMisc", "Level", "Room2", "Room1", "RoomTile", "CollMap",
                                                   "PresetUnit", "LevelTxt"])),
    ("skills", ("Skills & stats", ["Info", "Skill", "SkillInfo", "StatList", "StatVector", "Stat"])),
    ("ui", ("UI, controls, automap & graphics", ["Control", "ControlText", "NPCMenu", "TransactionDialogsInfo_t",
                                                  "TransactionDialogsLine_t", "AutomapLayer", "AutomapLayer2",
                                                  "AutomapCell", "CellFile", "CellContext", "GfxCell", "SplitText",
                                                  "WindowHandlerHashTable", "WindowHandlerList",
                                                  "MessageHandlerHashTable", "MessageHandlerList"])),
    ("net", ("Net & game info", ["GameStructInfo", "BnetData", "RosterUnit"])),
    ("misc", ("Misc (Warden, data tables, D2BS-side)", ["sgptDataTable", "D2MSG", "WardenClient_t", "WardenClientRegion_t",
                                                         "WardenIATInfo_t", "SMemBlock_t"])),
])

# Short, source-backed notes per struct.  Every File:LINE is checked by cite().
NOTES = {
    "UnitAny": [
        "The +0x14 union is selected by `dwType` (UNIT_* values at {c:Constants.h:361:UNIT_PLAYER 0}-{c:Constants.h:366:UNIT_TILE 5}): "
        "0 player -> `pPlayerData` ({c:D2Helpers.cpp:69:UNIT_PLAYER && pUnit->pPlayerData}), "
        "1 monster -> `pMonsterData` ({c:JSUnit.cpp:283:UNIT_MONSTER && pUnit->pMonsterData}), "
        "2 object and 5 tile -> `pObjectData` ({c:D2Helpers.cpp:85:UNIT_OBJECT || pUnit->dwType == UNIT_TILE}), "
        "4 item -> `pItemData` ({c:JSUnit.cpp:319:UNIT_ITEM && pUnit->pItemData}). No struct exists for 3 (missile).",
        "The +0x2C union: `pPath` for players/monsters ({c:Unit.cpp:75:player->pPath->pRoom1}), `pItemPath` for items "
        "({c:JSGame.cpp:475:pUnit->pItemPath->dwPosX}), `pObjectPath` for objects. ItemPath/ObjectPath only define the "
        "first 0x14 bytes (source: \"Use Path for the rest\").",
        "Lists: hash-table buckets chain through `pListNext` ({c:Unit.cpp:32:tmpUnit = tmpUnit->pListNext}); "
        "units of a room chain through `pRoomNext` ({c:D2Helpers.cpp:484:pMerc = pMerc->pRoomNext}).",
    ],
    "Room2": ["`pType2Info` points to an anonymous struct in the source; the header names it `Room2__pType2Info_t`."],
    "CollMap": ["Collision words are indexed as `pMapStart[(y - dwPosGameY) * dwSizeGameX + (x - dwPosGameX)]` "
                "({c:Map/Diablo_II/ActMap.cpp:178:map->pMapStart + (pt.second - map->dwPosGameY)}); flag bits are the "
                "`CollisionFlag` enum ({c:Map/Diablo_II/ActMap.h:45:enum CollisionFlag})."],
    "sgptDataTable": ["Defined but not used as a type: the global is declared as a plain DWORD "
                      "({c:D2Ptrs.h:349:VARPTR(D2COMMON, sgptDataTable, DWORD}) and MPQStats.cpp adds raw table offsets to it "
                      "({c:MPQStats.cpp:42:(*p_D2COMMON_sgptDataTable)}). `MpqTable` is only forward-declared "
                      "({c:D2Structs.h:745:struct MpqTable;}); `MPQTable` in {c:MPQStats.h:47:struct MPQTable} is a different, "
                      "D2BS-side descriptor (case differs)."],
    "NPCMenu": ["pack(1) changes this layout (see Packing). D2BS steps through an array of these by `sizeof(NPCMenu)` "
                "({c:D2Helpers.cpp:449:sizeof(NPCMenu)}), so sizeof matters. It casts `p_D2CLIENT_NPCMenu`, the address "
                "of the global, to `NPCMenu*` ({c:D2Helpers.cpp:414:(NPCMenu*)p_D2CLIENT_NPCMenu}), so it treats the "
                "global itself as the first element. The declared VARPTR type `NPCMenu*` "
                "({c:D2Ptrs.h:168:VARPTR(D2CLIENT, NPCMenu, NPCMenu*}) would instead mean a pointer stored there. "
                "The fields have no offset comments."],
    "TransactionDialogsLine_t": ["Source warns the placement of `handler` is a guess ({c:D2Structs.h:782:Not sure of the location of handler})."],
    "Control": ["The +0x5C union holds a textbox layout (`wText`, cursor, cloak flag) and a button layout (`_12`, `wText2`); "
                "C names `u_5C.s_5C.*` / `u_5C.s_5C_1.*`."],
    "MonsterData": ["The bit-field byte at +0x16 is read as `fMinion`/`fBoss`/`fChamp`/`fNormal` "
                    "({c:JSUnit.cpp:284:pUnit->pMonsterData->fMinion & 1})."],
    "ObjectData": ["`Type` and the `ChestLocked` bit share byte +0x04 ({c:JSUnit.cpp:514:pUnit->pObjectData->ChestLocked})."],
    "D2MSG": ["D2BS-side helper (HWND + buffer), not a game structure."],
    "WardenClient_t": ["Warden structures are declared but not referenced by D2Ptrs.h."],
}

# txt-record fields cross-checked against the BinField tables in MPQStats.h
MPQ_XCHECK = [
    ("ItemTxt", "dwCode", "itemTable", "code"), ("ItemTxt", "nLocaleTxtNo", "itemTable", "namestr"),
    ("ItemTxt", "xSize", "itemTable", "invwidth"), ("ItemTxt", "ySize", "itemTable", "invheight"),
    ("ItemTxt", "nType", "itemTable", "type"), ("ItemTxt", "fQuest", "itemTable", "quest"),
    ("MonsterTxt", "nLocaleTxtNo", "monstatsTable", "NameStr"), ("MonsterTxt", "velocity", "monstatsTable", "Velocity"),
    ("MonsterTxt", "tcs", "monstatsTable", "TreasureClass1"),
    ("ObjectTxt", "szName", "objectsTable", "Name"), ("ObjectTxt", "nSelectable0", "objectsTable", "Selectable0"),
    ("ObjectTxt", "nOrientation", "objectsTable", "Orientation"), ("ObjectTxt", "nSubClass", "objectsTable", "SubClass"),
    ("ObjectTxt", "nParm0", "objectsTable", "Parm0"), ("ObjectTxt", "nPopulateFn", "objectsTable", "PopulateFn"),
    ("ObjectTxt", "nOperateFn", "objectsTable", "OperateFn"), ("ObjectTxt", "nAutoMap", "objectsTable", "AutoMap"),
    ("LevelTxt", "dwLevelNo", "levelsTable", "Id"), ("LevelTxt", "szName", "levelsTable", "LevelName"),
    ("LevelTxt", "szEntranceText", "levelsTable", "LevelWarp"), ("LevelTxt", "nObjGroup", "levelsTable", "ObjGrp0"),
    ("LevelTxt", "nObjPrb", "levelsTable", "ObjPrb0"),
]

CHAINS = [
    ("Unit -> room -> level -> act", [("UnitAny", "pPath"), ("Path", "pRoom1"), ("Room1", "pRoom2"), ("Room2", "pLevel"),
                                      ("Level", "pMisc"), ("ActMisc", "pAct")]),
    ("Act -> levels -> rooms -> collision", [("UnitAny", "pAct"), ("Act", "pMisc"), ("ActMisc", "pLevelFirst"),
                                             ("Level", "pRoom2First"), ("Room2", "pRoom1"), ("Room1", "Coll"),
                                             ("CollMap", "pMapStart")]),
    ("Unit -> stats", [("UnitAny", "pStats"), ("StatList", "StatVec"), ("StatVector", "pStats")]),
    ("Unit -> items", [("UnitAny", "pInventory"), ("Inventory", "pFirstItem"), ("UnitAny", "pItemData")]),
    ("Unit -> skills", [("UnitAny", "pInfo"), ("Info", "pFirstSkill"), ("Skill", "pSkillInfo")]),
    ("Object unit -> txt record", [("UnitAny", "pObjectData"), ("ObjectData", "pTxt")]),
    ("Control -> text lines", [("Control", "pFirstText"), ("ControlText", "wText")]),
]

# Singly linked lists: (head struct, head field, element struct, next field)
LISTS = [
    ("ActMisc", "pLevelFirst", "Level", "pNextLevel"),
    ("Level", "pRoom2First", "Room2", "pRoom2Next"),
    ("Act", "pRoom1", "Room1", "pRoomNext"),
    ("Room2", "pPreset", "PresetUnit", "pPresetNext"),
    ("Room2", "pRoomTiles", "RoomTile", "pNext"),
    ("Room1", "pUnitFirst", "UnitAny", "pRoomNext"),
    ("UnitHashTable", "table", "UnitAny", "pListNext"),
    ("Info", "pFirstSkill", "Skill", "pNextSkill"),
    ("Control", "pFirstText", "ControlText", "pNext"),
    ("AutomapLayer", "pFloors", "AutomapCell", "pMore"),
    ("WindowHandlerHashTable", "table", "WindowHandlerList", "next"),
    ("MessageHandlerHashTable", "table", "MessageHandlerList", "next"),
]
LIST_NOTES = {
    ("Act", "pRoom1"): "{c:D2Helpers.cpp:483:pRoom = pRoom->pRoomNext}",
    ("Room1", "pUnitFirst"): "{c:D2Helpers.cpp:484:pMerc = pMerc->pRoomNext}",
    ("UnitHashTable", "table"): "{c:Unit.cpp:32:tmpUnit = tmpUnit->pListNext}",
    ("AutomapLayer", "pFloors"): "binary tree (`pLess`/`pMore`), not a list",
}

_cite_cache = {}


def cite(repo, spec):
    """spec 'File:LINE:needle' -> '`File:LINE`' after checking the needle is on that line."""
    fname, line, needle = spec.split(":", 2)
    line = int(line)
    if fname not in _cite_cache:
        with open(os.path.join(repo, fname), errors="replace") as fh:
            _cite_cache[fname] = fh.read().splitlines()
    text = _cite_cache[fname][line - 1]
    if needle not in text:
        raise RuntimeError("citation %s:%d does not contain %r (line is %r)" % (fname, line, needle, text))
    return "`%s:%d`" % (fname, line)


def expand_cites(repo, s):
    return re.sub(r"\{c:([^}]*)\}", lambda m: cite(repo, m.group(1)), s)


def parse_mpq_tables(repo):
    with open(os.path.join(repo, MPQSTATS_H)) as fh:
        lines = fh.read().splitlines()
    tables, cur = {}, None
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^static BinField (\w+)\[\]", ln)
        if m:
            cur = m.group(1)
            tables[cur] = {}
            continue
        if cur and ln.startswith("};"):
            cur = None
            continue
        if cur:
            for mm in re.finditer(r'\{"([^"]*)",\s*(\w+),\s*(0x[0-9A-Fa-f]+|\d+),\s*(0x[0-9A-Fa-f]+|\d+)\}', ln):
                tables[cur].setdefault(mm.group(1), (int(mm.group(4), 0), i))
    return tables


def md_esc(s):
    return (s or "").replace("|", "\\|").replace("`", "'")


def hx(v, w=3):
    return "0x%0*X" % (w, v)


def is_unknown(name):
    return bool(re.match(r"^(_\d+\w*|_|unk.*|Unk.*)$", name))


_src_cache = {}


def _source_files(repo):
    if repo not in _src_cache:
        files = []
        for dp, dn, fn in os.walk(repo):
            rel = os.path.relpath(dp, repo)
            top = rel.split(os.sep)[0]
            if top in (".git", "dependencies", "docs", "doc", "Debug", "Release", "resources"):
                dn[:] = []
                continue
            dn.sort()
            for f in sorted(fn):
                if not f.endswith((".cpp", ".h")) or f.startswith("sqlite3"):
                    continue
                p = os.path.normpath(os.path.join(rel, f))
                with open(os.path.join(dp, f), errors="replace") as fh:
                    files.append((p, fh.read().splitlines()))
        _src_cache[repo] = files
    return _src_cache[repo]


_STR_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def code_part(ln):
    """Line without string/char literals and // comments (heuristic)."""
    return _STR_RE.sub('""', ln).split("//")[0]


def src_uses(repo, ident, exclude=(STRUCTS_H,)):
    """(file, line) of lines mentioning `ident` as a word outside strings/comments."""
    pat = re.compile(r"\b%s\b" % re.escape(ident))
    hits = []
    for p, lines in _source_files(repo):
        if p in exclude:
            continue
        for i, ln in enumerate(lines, 1):
            if pat.search(code_part(ln)):
                hits.append((p, i))
    return hits


def field_uses(repo, name):
    pat = re.compile(r"(->|\.)%s\b" % re.escape(name))
    hits = []
    for p, lines in _source_files(repo):
        if p == STRUCTS_H:
            continue
        for i, ln in enumerate(lines, 1):
            if pat.search(code_part(ln)):
                hits.append((p, i))
    return hits


def type_str(f):
    if f.func is not None:
        return "%s(%s*)(%s)" % (f.func["ret"], (f.func["cc"] + " ") if f.func["cc"] else "", f.func["params"] or "")
    b = "struct {...}" if isinstance(f.base, Rec) else f.base
    s = b + "*" * f.ptr + "".join("[%s]" % t for _, t in f.dims)
    if f.bits is not None:
        s += " : %d" % f.bits
    return s


def discrepancies(parser):
    """Every source comment whose leading offset (or 'size =') disagrees with the
    computed layout, with a mechanically derived likely cause."""
    out = []
    for rootname, rec, expr, top, via in roots_of(parser.records):
        items = list(walk(rec))
        last_delta = None
        for idx, (kind, obj, off, depth, path) in enumerate(items):
            claim = claimed_offset(obj.comment)
            if claim is None or claim == off:
                continue
            delta = off - claim
            cause = None
            if idx > 0:
                pkind, pobj, poff, pdepth, ppath = items[idx - 1]
                pclaim = claimed_offset(pobj.comment)
                if pclaim is not None and pdepth == depth:
                    implied = claim - pclaim
                    if implied != pobj.size:
                        pname = getattr(pobj, "name", None) or "(anonymous %s)" % pobj.kind
                        if (pkind == "field" and pobj.base == "wchar_t" and pobj.dims and implied * 2 == pobj.size):
                            cause = "comments count the preceding `wchar_t %s[%s]` as %d bytes; it is 0x%X bytes" % (
                                pobj.name, pobj.dims[0][1], implied, pobj.size)
                        elif implied > 0:
                            cause = "comments imply the preceding `%s` is 0x%X bytes; it is declared 0x%X" % (
                                pname, implied, pobj.size)
                        else:
                            cause = "comment is below the preceding field's comment (stale or copied)"
                    elif pclaim == poff and off > poff + pobj.size:
                        cause = "%d byte(s) of alignment padding precede this field (struct is not packed)" % (
                            off - poff - pobj.size)
            if cause is None and last_delta == delta:
                cause = "same shift as the previous discrepancy"
            if cause is None:
                cause = "comment does not match the declared types before it"
            out.append(dict(root=rootname, rec=rec, obj=obj, kind=kind, claim=claim, off=off, delta=delta,
                            cause=cause, line=obj.line))
            last_delta = delta
        cs = claimed_size(rec.comment)
        if cs is not None and cs != rec.size:
            out.append(dict(root=rootname, rec=rec, obj=None, kind="size", claim=cs, off=rec.size,
                            delta=rec.size - cs, cause="declared size comment", line=rec.line))
    return out


def gen_markdown(repo, parser, cmodel, truth, ptrs, out_path, check_summary):
    R = lambda s: expand_cites(repo, s)
    roots = roots_of(parser.records)
    disc = discrepancies(parser)
    disc_by_obj = {id(d["obj"]): d for d in disc if d["obj"] is not None}
    refs = ptrs_type_refs(ptrs)
    mpq = parse_mpq_tables(repo)
    struct_lines = {r.name: (r.line, r.end_line) for r in parser.records}
    L = []
    w = L.append

    w("# Game structures (`D2Structs.h`) with computed MSVC x86 layouts")
    w("")
    w("Scope: every `struct`/`union` in `D2Structs.h`, plus the Win32 types that `D2Ptrs.h` prototypes use "
      "and that are defined outside the repo (`POINT`, `RECT`, `CRITICAL_SECTION`, `HWND`, ...). Offsets are not taken "
      "from the source comments: they are computed by compiling the unmodified header with clang in MSVC x86 mode, "
      "and cross-checked by an independent Python MSVC layout engine. Where a source comment claims a different "
      "offset the row is marked **DISCREPANCY**. Those are either stale comments or real bugs in what D2BS reads. "
      "The same layouts are used by the Ghidra header [`docs/ghidra/d2bs_types.h`](../ghidra/d2bs_types.h) "
      "(generator: [`docs/ghidra/tools/gen_types.py`](../ghidra/tools/gen_types.py)). Addresses of globals and functions "
      "are in [offsets.md](offsets.md), hooks in [patches-and-hooks.md](patches-and-hooks.md), asm stubs in "
      "[call-stubs.md](call-stubs.md), and the overview in [README.md](README.md).")
    w("")
    w("This file is generated: `python3 docs/ghidra/tools/gen_types.py --repo . --structs-md docs/memory/structs.md` "
      "(add `--ghidra-install DIR` or `--ghidra-cp CLASSPATH`, plus `--ghidra-label TEXT`, to include step 5 of "
      "[How this was verified](#how-this-was-verified); without them that step is left out).")
    w("")
    w("## Contents")
    w("")
    toc = ["Reading the tables", "Discrepancy summary", "Packing", "Relationships", ]
    toc += [v[0] for v in DOMAINS.values()]
    toc += ["Win32 types referenced by D2Ptrs.h", "Partially known structs", "Cross-check against MPQStats.h",
            "How this was verified", "Open questions"]
    for t in toc:
        w("- [%s](#%s)" % (t, anchor(t)))
    w("")

    # ---- reading
    w("## Reading the tables")
    w("")
    w("- **Offset**: computed byte offset from the start of the struct, hex. For members of an anonymous "
      "union/struct the offset is still from the start of the outer struct, as in the source comments. "
      "Rows prefixed with `↳` are nested inside the anonymous member above them.")
    w("- **Size**: computed size in bytes (hex). Bit-fields show the storage unit size and their bit range in Notes.")
    w("- **Type / Field**: as written in `D2Structs.h` (line in Notes).")
    w("- **Source comment**: the trailing `//` comment on the declaration line, verbatim.")
    w("- **Notes**: `DISCREPANCY` when the comment's leading offset disagrees with the computed offset; `unknown` for "
      "placeholder names (`_1`, `_2a`, `unk...`), which mark partially reverse-engineered regions; "
      "`C:` gives the member path in `d2bs_types.h` when it differs from the C++ name.")
    w("- `(padding)` rows are bytes that the compiler inserts for alignment. They are not declared in the source.")
    w("- All structs use MSVC default packing (/Zp8) unless marked `pack(1)`. Pointers are 4 bytes, `wchar_t` 2 bytes.")
    w("")

    # ---- discrepancy summary
    w("## Discrepancy summary")
    w("")
    w("%d source comments disagree with the computed layout. A wrong comment does not change what D2BS reads, "
      "because D2BS uses the declared types. But if the comment was right about the game, the declared layout "
      "(and every field after the first divergence) is wrong. The first discrepancy in a struct is the one to "
      "investigate; later ones with the same shift follow from it. "
      "\"Code uses\" lists `->name`/`.name` accesses in the repo. The match is by name only, so a hit can belong "
      "to a different struct with a field of the same name." % len(disc))
    w("")
    w("| Struct | Field | Line | Comment says | Computed | Shift | Likely cause | Code uses |")
    w("|---|---|---|---|---|---|---|---|")
    for d in disc:
        if d["obj"] is None:
            fname = "(sizeof)"
        elif d["kind"] == "rec":
            fname = "(anonymous %s)" % d["obj"].kind
        else:
            fname = "`%s`" % d["obj"].name
        uses = ""
        if d["kind"] == "field" and not is_unknown(d["obj"].name):
            u = field_uses(repo, d["obj"].name)
            uses = ", ".join("`%s:%d`" % x for x in u[:3]) + (" +%d" % (len(u) - 3) if len(u) > 3 else "")
        w("| %s | %s | `%s:%d` | %s | %s | %s0x%X | %s | %s |" % (
            d["root"], fname, STRUCTS_H, d["line"], hx(d["claim"]), hx(d["off"]), "+" if d["delta"] >= 0 else "-",
            abs(d["delta"]), d["cause"], uses or "-"))
    w("")

    # ---- packing
    w("## Packing")
    w("")
    packed = [r for r in parser.records if r.pack]
    regions = OrderedDict()
    for r in packed:
        regions.setdefault(r.pack_line, []).append(r.name)
    w("`D2Structs.h` has %d `#pragma pack(1)` regions:" % len(regions))
    w("")
    for ln, names in regions.items():
        w("- pack(1) set at %s: %s" % (
            cite(repo, "%s:%d:#pragma pack(1)" % (STRUCTS_H, ln)), ", ".join("`%s`" % n for n in names)))
    w("")
    w("Effect of pack(1), computed by laying each packed struct out again with default packing:")
    w("")
    w("| Struct | sizeof pack(1) | sizeof default | align pack(1) / default | Fields whose offset changes |")
    w("|---|---|---|---|---|")
    for r in packed:
        alt = relayout_default(parser, r)
        changed = [n for n, (a, b) in alt["fields"].items() if a != b]
        if changed:
            effect = (", ".join("`%s` 0x%X->0x%X" % (n, alt["fields"][n][0], alt["fields"][n][1])
                                for n in changed[:6]) + (" ... (%d total)" % len(changed) if len(changed) > 6 else ""))
        elif alt["align"] != r.align:
            effect = "none (only the alignment changes)"
        else:
            effect = "none (pack(1) has no effect)"
        w("| %s | 0x%X | 0x%X | %d / %d | %s |" % (r.name, r.size, alt["size"], r.align, alt["align"], effect))
    w("")
    w("In the Ghidra header these regions are written as `#pragma pack(push, 1)` ... `#pragma pack(pop)`. Ghidra's "
      "CParser reads this form itself (`PragmaSpecifier` in "
      "`Ghidra/Features/Base/src/main/javacc/ghidra/app/util/cparser/C/C.jj`). It does not support the source's bare "
      "`#pragma pack(push)`: the grammar only pushes when a value or identifier follows `push`, so the later `pop` "
      "would leave pack(1) active. CParser ignores `__attribute__((packed))` on structs (the `PACKED` qualifier is "
      "only used for enums).")
    w("")

    # ---- relationships
    w("## Relationships")
    w("")
    w("Pointer chains. Each hop is `Struct+offset field` and yields the type in parentheses; offsets are computed:")
    w("")
    byroot = {rn: rec for rn, rec, e, t, v in roots}
    for title, hops in CHAINS:
        parts = []
        for sname, fname in hops:
            f, off = find_leaf(byroot[sname], fname)
            parts.append("`%s+0x%X %s` (%s)" % (sname, off, fname, type_str(f)))
        w("- **%s**: %s" % (title, " → ".join(parts)))
    w("")
    w("Linked lists (head field → element type, element's next field):")
    w("")
    w("| Head | Element | Next link | Evidence / note |")
    w("|---|---|---|---|")
    for hs, hf, es, nf in LISTS:
        f1, o1 = find_leaf(byroot[hs], hf)
        f2, o2 = find_leaf(byroot[es], nf)
        note = R(LIST_NOTES.get((hs, hf), ""))
        w("| `%s+0x%X %s` (%s) | %s | `%s+0x%X %s` | %s |" % (hs, o1, hf, type_str(f1), es, es, o2, nf, note or "-"))
    w("")
    w("All pointer fields that point to another struct in this file:")
    w("")
    w("| From | Offset | Field | Points to |")
    w("|---|---|---|---|")
    for rn, rec, e, t, v in roots:
        for f, off, path in leaves(rec):
            if f.func is None and f.ptr and (isinstance(f.base, Rec) or f.base in parser.byname or f.base in parser.forward):
                tgt = f.base.cname if isinstance(f.base, Rec) else f.base
                w("| %s | %s | `%s` | %s%s |" % (rn, hx(off), f.name, tgt, "*" * (f.ptr - 1) + (" (array of pointers)" if f.dims else "")))
    w("")

    # ---- domains
    placed = set()
    for key, (title, names) in DOMAINS.items():
        w("## %s" % title)
        w("")
        for n in names:
            rec = parser.byname[n]
            placed.add(n)
            emit_struct(w, repo, parser, cmodel, rec, n, refs, disc_by_obj, R)
            for rn, prec, e, t, v in roots:
                if t is rec and prec is not rec:
                    emit_struct(w, repo, parser, cmodel, prec, rn, refs, disc_by_obj, R, pointee=(t, v))
    missing = [r.name for r in parser.records if r.name not in placed]
    if missing:
        raise RuntimeError("structs not assigned to a domain: %s" % missing)

    # ---- win32
    w("## Win32 types referenced by D2Ptrs.h")
    w("")
    w("These are defined by `<windows.h>` (MSVC x86), not by the repo. `d2bs_types.h` gives the equivalent "
      "definitions in its prelude. Sizes are computed by clang (MSVC x86) from the same definitions, and the C "
      "check asserts them against the prelude.")
    w("")
    w("| Type | sizeof | Definition used | D2Ptrs.h uses |")
    w("|---|---|---|---|")
    win = [("BYTE", "unsigned char"), ("WORD", "unsigned short"), ("DWORD", "unsigned long"),
           ("POINT", "struct tagPOINT { LONG x; LONG y; }"), ("RECT", "struct tagRECT { LONG left, top, right, bottom; }"),
           ("CRITICAL_SECTION", "RTL_CRITICAL_SECTION: DebugInfo*, LockCount, RecursionCount, OwningThread, LockSemaphore, SpinCount"),
           ("HWND", "struct HWND__* (STRICT)"), ("LPSTR", "char*"), ("LPVOID", "void*"), ("BOOL", "int"), ("INT", "int"),
           ("CHAR", "char"), ("size_t", "unsigned int"), ("VOID", "macro for void (`#define VOID void` in winnt.h)")]
    for t, d in win:
        u = refs.get(t, [])
        sz = PRIM.get(t, (None,))[0]
        lns = sorted(set(ln for _, ln, _ in u))
        w("| `%s` | %s | %s | %s |" % (t, ("0x%X" % sz) if sz else "-", d,
                                      (", ".join("`%s:%d`" % (PTRS_H, ln) for ln in lns[:4]) + (" +%d" % (len(lns) - 4) if len(lns) > 4 else "")) if lns else "-"))
    w("")
    w(R("`RECT` is not used by an active D2Ptrs.h entry. It is listed because the commented-out `DrawAutomapCell` "
        "prototype ({c:D2Ptrs.h:376:RECT *cliprect}) and the `D2GFX_DrawRectFrame_STUB` helper "
        "({c:D2Helpers.h:108:RECT* rect}) use it."))
    w("")

    # ---- partially known
    w("## Partially known structs")
    w("")
    w("Bytes declared with placeholder names (`_1`, `_2a`, `unk...`), plus compiler padding, as a share of sizeof. "
      "Anything not in a named field is unknown to D2BS.")
    w("")
    w("| Struct | sizeof | Named bytes | Placeholder bytes | Padding bytes | Named % |")
    w("|---|---|---|---|---|---|")
    for rn, rec, e, t, v in roots:
        named, unk = coverage(rec)
        pad = rec.size - named - unk
        w("| %s | 0x%X | %d | %d | %d | %d%% |" % (rn, rec.size, named, unk, pad, round(100.0 * named / rec.size) if rec.size else 0))
    w("")

    # ---- MPQ cross check
    w("## Cross-check against MPQStats.h")
    w("")
    w("`MPQStats.h` contains BinField tables (column name, type, length, offset). D2BS uses them for `getBaseStat`, "
      "and the source credits them to a dump by Sheppard. They come from a different source than "
      "`D2Structs.h`. For the `*Txt` records they give a second opinion on the offsets below. They may be from "
      "another game version, so a mismatch is a lead to check, not proof.")
    w("")
    w("| Struct.field | Computed | Source comment | MPQStats.h column | MPQStats.h offset | Agrees with |")
    w("|---|---|---|---|---|---|")
    for sname, fname, table, col in MPQ_XCHECK:
        f, off = find_leaf(parser.byname[sname], fname)
        if f is None:
            f, off = find_rec_member(parser.byname[sname], fname)
        claim = claimed_offset(f.comment) if f is not None else None
        mo, mline = mpq[table][col]
        agrees = []
        if mo == off:
            agrees.append("computed")
        if claim is not None and mo == claim:
            agrees.append("comment")
        w("| `%s.%s` | %s | %s | `%s.%s` (`%s:%d`) | %s | %s |" % (
            sname, fname, hx(off), hx(claim) if claim is not None else "-", table, col, MPQSTATS_H, mline, hx(mo),
            ", ".join(agrees) or "**neither**"))
    w("")

    # ---- verification
    w("## How this was verified")
    w("")
    for s in check_summary:
        w(s)
    w("")

    # ---- open questions
    w("## Open questions")
    w("")
    oq = [
        "Which side of each DISCREPANCY matches 1.14d? Answering this needs a memory dump or disassembly. D2BS "
        "reads the computed offsets, so these are the cases where a wrong comment could hide a live bug: "
        "`BnetData.ladderflag` (`me.ladder`, " + cite(repo, "JSUnit.cpp:126:pData->ladderflag") + ") is read at "
        "0x3C2 but commented 0x3C0, because `szGameDesc[0x104]` ends at 0x361 where the comments expect 0x35F. "
        "`Control.wText2` (button text, " + cite(repo, "Control.cpp:83:wcscmp(pControl->wText2, Text)") + ") is "
        "read at 0x64 but commented 0x6C. `ItemTxt.xSize`/`ySize` are read at 0x10F/0x110 (comments 0xFC/0xFD). "
        "MPQStats.h agrees with the code there. `ObjectTxt.nAutoMap` is read at 0x1BC (comment 0x1BB), and "
        "MPQStats.h agrees with the code. `CollMap.pMapEnd` is read at 0x24 (comment 0x22) and ends the collision "
        "loops in `LevelMap.cpp`.",
        "Fields D2BS does not read, where the code disagrees with an independent source: `ItemTxt.fQuest` (code 0x12C; "
        "comment and MPQStats.h 0x12A), `LevelTxt.nObjGroup`/`nObjPrb` (code 0x20E/0x216, comment 0x196/0x19E, "
        "MPQStats.h 0xE5/0xED, which falls inside `LevelTxt._1`), and `ObjectTxt.nOrientation`/`nSubClass` "
        "(MPQStats.h 0x13C/0x167). These should be fixed or removed before anyone relies on them.",
        "`UnitAny.pListNext` has the comment `0xE4 -> 0xD8`. D2BS walks the unit hash tables through 0xE4. Is 0xD8 "
        "the value for another game version?",
        "`MpqTable` is only forward-declared, so its layout is unknown. `sgptDataTable` declares only the first 7 "
        "members, and the code treats the global as a plain DWORD.",
        "`UnitAny` has no union member for missiles (dwType 3). The +0x2C path union has no member for tiles.",
        "Is the pack(1) on `Level`, `Room2`, `RosterUnit` and the others intended? Only `BnetData` and `NPCMenu` "
        "change layout under it; for the rest it only lowers the alignment to 1 (`Waypoint`, a single BYTE, is "
        "not affected at all).",
        "`d2bs_symbols.tsv` writes the callbacks of `D2WIN_SetEditBoxCallback`/`D2WIN_SetEditBoxProc` inline as "
        "`BOOL (__stdcall* FunCallBack)(...)`. CParser drops `__stdcall` in that form. Because both parameters are "
        "named `FunCallBack`, they also share a single function definition: the last signature parsed wins. "
        "`d2bs_types.h` provides `D2WIN_SetEditBoxCallback_FunCallBack_t` and `D2WIN_SetEditBoxProc_FunCallBack_t` "
        "with the calling convention preserved, for use in those prototypes.",
    ]
    for q in oq:
        w("- " + q)
    w("")
    text = "\n".join(L).rstrip("\n") + "\n"
    with open(out_path, "w") as fh:
        fh.write(text)


def anchor(t):
    a = t.strip().lower()
    a = re.sub(r"[^\w\- ]", "", a)
    return a.replace(" ", "-")


def find_leaf(rec, name):
    for f, off, path in leaves(rec):
        if f.name == name:
            return f, off
    return None, None


def find_rec_member(rec, name):
    for kind, obj, off, depth, path in walk(rec):
        if kind == "rec" and any((not isinstance(m, Rec)) and m.name == name for m in obj.members):
            return obj, off
    return None, None


def coverage(rec):
    """(named bytes, placeholder bytes); unions count once, as named."""
    named = unk = 0
    seen_units = set()
    for kind, obj, off, depth, path in walk(rec):
        if any(p.kind == "union" for p in path):
            continue
        if kind == "rec":
            if obj.kind == "union":
                named += obj.size
            continue
        if obj.bits is not None:
            if off in seen_units:
                continue
            seen_units.add(off)
        if is_unknown(obj.name):
            unk += obj.size
        else:
            named += obj.size
    return named, unk


def relayout_default(parser, rec):
    """Lay out `rec` with default packing (deep copy semantics via fresh Layout)."""
    import copy
    clone = copy.deepcopy(rec)

    def clear(r):
        r.size = r.align = None
        r.pack = None
        for m in r.members:
            if isinstance(m, Rec):
                clear(m)
            elif isinstance(m.base, Rec):
                clear(m.base)
    clear(clone)
    Layout(parser.byname).rec(clone)
    fields = OrderedDict()
    orig_leaves = leaves(rec)
    for (f1, o1, p1), (f2, o2, p2) in zip(orig_leaves, leaves(clone)):
        fields[f1.name] = (o1, o2)
    return dict(size=clone.size, align=clone.align, fields=fields)


def emit_struct(w, repo, parser, cmodel, rec, name, refs, disc_by_obj, R, pointee=None):
    cname = cmodel.root_cname[id(rec)]
    if pointee is not None:
        w("### %s" % name)
        w("")
        w("Anonymous struct in the source, reached through `%s.%s` (`%s:%d`)." % (
            pointee[0].name, pointee[1].name, STRUCTS_H, rec.line))
        w("")
    else:
        w("### %s" % name)
        w("")
    pk = ("pack(1) (set at `%s:%d`)" % (STRUCTS_H, rec.pack_line)) if rec.pack else "default (/Zp8)"
    span = "`%s:%d-%d`" % (STRUCTS_H, rec.line, rec.end_line)
    cs = claimed_size(rec.comment)
    szs = "sizeof **0x%X** (%d)" % (rec.size, rec.size)
    if cs is not None:
        szs += " (source comment: 0x%X%s)" % (cs, "" if cs == rec.size else " **DISCREPANCY**")
    w("%s · %s · align %d · packing %s" % (span, szs, rec.align, pk))
    w("")
    if pointee is None:
        r = refs.get(name, [])
        if r:
            seen = OrderedDict()
            for sym, ln, role in r:
                seen.setdefault((sym, ln), set()).add(role)
            items = ["`%s` (%s)" % (s, "/".join(sorted(rl))) for (s, ln), rl in seen.items()]
            w("D2Ptrs.h: %d symbol%s use%s it: %s." % (len(items), "" if len(items) == 1 else "s",
                                                     "s" if len(items) == 1 else "", ", ".join(items)))
            w("")
        uses = sorted(set(p for p, i in src_uses(repo, name, exclude=(STRUCTS_H, PTRS_H))))
        if uses:
            w("Named in %d other source file%s: %s." % (len(uses), "" if len(uses) == 1 else "s",
                                                      ", ".join("`%s`" % u for u in uses)))
            w("")
    for n in NOTES.get(name, []):
        w("> " + R(n))
        w("")
    w("| Offset | Size | Type | Field | Source comment | Notes |")
    w("|---|---|---|---|---|---|")
    prev_end = 0
    for kind, obj, off, depth, path in walk(rec):
        if depth == 0 and rec.kind == "struct" and off > prev_end:
            w("| %s | 0x%X | | (padding) | | compiler alignment padding |" % (hx(prev_end), off - prev_end))
        notes = []
        d = disc_by_obj.get(id(obj))
        if d:
            notes.append("**DISCREPANCY**: comment says 0x%X, computed 0x%X" % (d["claim"], d["off"]))
        prefix = "↳ " * depth
        if kind == "rec":
            tname = "%s (anonymous)" % obj.kind
            label = "%s(anonymous %s)" % (prefix, obj.kind)
            cn = c_name_of_rec(cmodel, rec, obj)
            if cn:
                notes.append("C: " + cn)
            else:
                notes.append("C: flattened into the parent")
            notes.append("`%s:%d`" % (STRUCTS_H, obj.line))
            w("| %s | 0x%X | %s | %s | %s | %s |" % (hx(off), obj.size, tname, label, md_esc(obj.comment), "; ".join(notes)))
        else:
            if is_unknown(obj.name):
                notes.append("unknown")
            if obj.bits is not None:
                notes.append("bits %d..%d" % (obj.bitpos, obj.bitpos + obj.bits - 1))
            cp = cmodel.cpath[id(obj)]
            if cp != obj.name:
                notes.append("C: `%s`" % cp)
            if isinstance(obj.base, Rec):
                notes.append("C type: `%s*`" % cmodel.root_cname[id(obj.base)])
            notes.append("`%s:%d`" % (STRUCTS_H, obj.line))
            w("| %s | 0x%X | `%s` | %s`%s` | %s | %s |" % (hx(off), obj.size, type_str(obj), prefix, obj.name,
                                                       md_esc(obj.comment), "; ".join(notes)))
        if depth == 0:
            prev_end = max(prev_end, off + obj.size)
    if rec.kind == "struct" and rec.size > prev_end:
        w("| %s | 0x%X | | (padding) | | tail padding to align %d |" % (hx(prev_end), rec.size - prev_end, rec.align))
    w("")


def c_name_of_rec(cmodel, root, obj):
    for r in cmodel.hoisted:
        if r.orig is obj:
            # path: find member in emit order that references r
            for o in cmodel.emit_order:
                for f in o.members:
                    if isinstance(f.base, Rec) and f.base is r and f.func is None and f.ptr == 0:
                        return "member `%s`, type `%s`" % (f.name, r.cname)
    return None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def load(repo):
    path = os.path.join(repo, STRUCTS_H)
    with open(path) as fh:
        toks, comments = lex(fh.read())
    parser = StructParser(toks, comments, STRUCTS_H).parse()
    lay = Layout(parser.byname)
    for r in parser.records:
        lay.rec(r)
    for rn, rec, e, t, v in roots_of(parser.records):
        lay.rec(rec)
    annotate_abs(parser)
    cmodel = CModel(parser)
    # self-check: translated model must give the same layout as the original
    clay = Layout({r.cname: r for r in cmodel.emit_order})
    for r in cmodel.emit_order:
        clay.rec(r)
        if r.size != r.orig.size or r.align != r.orig.align:
            raise RuntimeError("C translation changes sizeof/alignof of %s" % r.cname)
        base = r.orig.abs_off or 0  # inline anonymous record: its offset in the root; roots: 0
        for f in r.members:
            if f.off + base != f.orig.abs_off:
                raise RuntimeError("C translation moves %s.%s" % (r.cname, f.name))
    return parser, cmodel


def find_tool(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".", help="D2BS repository root")
    ap.add_argument("--out", help="write the Ghidra C header here (e.g. docs/ghidra/d2bs_types.h)")
    ap.add_argument("--check", action="store_true", help="verify layouts with clang (needs --out or an existing header)")
    ap.add_argument("--header", help="header to check (default: --out or docs/ghidra/d2bs_types.h)")
    ap.add_argument("--structs-md", help="write docs/memory/structs.md here (needs clang)")
    ap.add_argument("--layout-json", help="write clang-computed layouts as JSON (needs clang)")
    ap.add_argument("--work", help="directory for probe files (default: temporary)")
    ap.add_argument("--clang", default=None, help="clang executable (default: clang)")
    ap.add_argument("--clangxx", default=None, help="clang++ executable (default: clang++)")
    ap.add_argument("--ghidra-cp", help="also parse the header with Ghidra's CParser using this Java classpath")
    ap.add_argument("--ghidra-install", help="Ghidra installation dir; builds --ghidra-cp from its Framework and Base jars")
    ap.add_argument("--ghidra-label", default=None, help="Ghidra version label recorded in structs.md")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)
    parser, cmodel = load(repo)
    ptrs = parse_ptrs(repo)
    if a.out:
        emit_header(parser, cmodel, ptrs, a.out)
        print("wrote %s (%d structs/unions, %d hoisted anonymous types)" % (
            a.out, len(parser.records), len(cmodel.hoisted)))
    need_clang = a.check or a.structs_md or a.layout_json
    if not need_clang:
        return 0
    clang = a.clang or find_tool(["clang"])
    clangxx = a.clangxx or find_tool(["clang++"])
    if not clang or not clangxx:
        print("error: clang/clang++ not found (needed for --check/--structs-md/--layout-json)", file=sys.stderr)
        return 2
    if a.work:
        os.makedirs(a.work, exist_ok=True)
        return run_checks(a, repo, parser, cmodel, ptrs, clang, clangxx, os.path.abspath(a.work))
    with tempfile.TemporaryDirectory(prefix="gen_types_") as work:
        return run_checks(a, repo, parser, cmodel, ptrs, clang, clangxx, work)


def run_checks(a, repo, parser, cmodel, ptrs, clang, clangxx, work):
    truth = Truth(repo, parser, work, clangxx)
    errs = compare_python_vs_truth(parser, truth)
    n_fields = sum(len(leaves(rec)) for rn, rec, e, t, v in roots_of(parser.records))
    summary = []
    rc = 0
    header = a.header or a.out or os.path.join(repo, "docs/ghidra/d2bs_types.h")
    if errs:
        print("Python layout engine disagrees with clang:\n  " + "\n  ".join(errs), file=sys.stderr)
        rc = 1
    else:
        print("python layout engine == clang MSVC x86 for %d roots / %d fields" % (len(roots_of(parser.records)), n_fields))
    cerrs, ccmd, n_off, n_size, n_align, n_bits, n_cc = check_c_header(repo, parser, cmodel, truth, header, work, clang, ptrs)
    if cerrs:
        print("\n".join(cerrs), file=sys.stderr)
        rc = 1
    else:
        print("C header OK: %d offset, %d sizeof, %d alignof, %d calling-convention asserts; %d bit-fields match (%s)" % (
            n_off, n_size, n_align, n_cc, n_bits, header))
    problems, special, had_tsv = check_type_coverage(repo, cmodel, ptrs)
    if problems:
        print("undefined type identifiers: " + ", ".join(problems), file=sys.stderr)
        rc = 1
    else:
        print("type coverage OK for D2Ptrs.h%s" % (" and " + SYMBOLS_TSV if had_tsv else " (no %s yet)" % SYMBOLS_TSV))
    for s in special:
        print("note: " + s)
    ginfo = None
    if a.ghidra_cp or a.ghidra_install:
        gerrs, ginfo = ghidra_check(repo, parser, cmodel, truth, header, work, ghidra_classpath(a), ptrs)
        if gerrs:
            print("Ghidra CParser check FAILED:\n  " + "\n  ".join(gerrs), file=sys.stderr)
            rc = 1
            ginfo = None
        else:
            print("Ghidra CParser OK: %d composites / %d fields (%d bit-fields, %d explicit pack(1)) match clang%s" % (
                ginfo["composites"], ginfo["fields"], ginfo["bitfields"], ginfo["packed"],
                "; %d/%d FUNC prototypes + %d DATA types from %s parse" % (
                    ginfo["tsv_funcs_parsed"], ginfo["tsv_funcs"], ginfo["tsv_data"], SYMBOLS_TSV)
                if "tsv_funcs" in ginfo else ""))
    if a.layout_json:
        data = OrderedDict()
        for rn, rec, e, t, v in roots_of(parser.records):
            data[rn] = OrderedDict(size=truth.sizes[rn], align=truth.aligns[rn], pack=rec.pack or None,
                                   line=rec.line, c_type=cmodel.root_cname[id(rec)],
                                   fields=[OrderedDict(name=f.name, offset=off, size=f.size, type=type_str(f),
                                                       c_path=cmodel.cpath[id(f)], line=f.line,
                                                       bit=(f.bitpos if f.bits is not None else None),
                                                       bits=f.bits, comment=f.comment)
                                           for f, off, p in leaves(rec)])
        with open(a.layout_json, "w") as fh:
            json.dump(data, fh, indent=1)
    if a.structs_md:
        rel = lambda p: os.path.relpath(p, repo) if os.path.isabs(p) else p
        summary = [
            "All numbers in this file come from `docs/ghidra/tools/gen_types.py` (Python 3 stdlib only), which runs clang. "
            "Toolchain used for this revision: `%s`." % truth.clang_version,
            "",
            "1. **Ground truth.** `D2Structs.h` is compiled unmodified as MSVC x86 C++ against a minimal fake `<windows.h>`. "
            "The fake header contains the x86 SDK definitions of BYTE/WORD/DWORD/BOOL/HWND/POINT/RECT, and a "
            "24-byte CRITICAL_SECTION. A generated probe defines `extern \"C\" const unsigned` constants holding "
            "`sizeof`/`alignof`/`__builtin_offsetof` for %d structs and %d fields. The constants are read back from "
            "the LLVM IR:" % (len(roots_of(parser.records)), n_fields),
            "   ```",
            "   " + " ".join(shorten(x, work, repo) for x in truth.cmd_ir),
            "   ```",
            "   Bit-field positions (offsetof cannot take a bit-field) are read from clang's record dump:",
            "   ```",
            "   " + " ".join(shorten(x, work, repo) for x in truth.cmd_dump),
            "   ```",
            "2. **Independent engine.** A Python implementation of the MSVC rules (natural alignment capped by "
            "`#pragma pack`, /Zp8 default, MS bit-field allocation) recomputes every layout. It must match step 1 "
            "exactly: %s." % ("it does, for every struct and field" if not errs else "MISMATCH: " + "; ".join(errs)),
            "3. **Ghidra header.** The generated `d2bs_types.h` is compiled as C11 (`typedef unsigned short wchar_t;` "
            "then `#include`) with one `_Static_assert` per field offset (%d), per sizeof (%d, including hoisted "
            "anonymous types and the Win32 prelude types) and per struct alignment (%d). The values come from step 1. %d more asserts use "
            "`__builtin_types_compatible_p` to check that every function pointer keeps its calling convention. "
            "Bit-field positions (%d) are compared through the C record dump. Result: %s." % (
                n_off, n_size, n_align, n_cc, n_bits, "pass" if not cerrs else "FAIL"),
            "   ```",
            "   " + " ".join(shorten(x, work, repo) for x in ccmd),
            "   ```",
            "4. **Type coverage.** Every type identifier used by a `FUNCPTR`/`VARPTR` entry of `D2Ptrs.h`%s is "
            "defined or forward-declared in the header. The only exception is `VOID`, a winnt.h macro that has to be "
            "replaced by `void`. Result: %s." % (
                ", and by the FUNC/DATA `type` column of `%s`," % SYMBOLS_TSV if had_tsv else "",
                "pass" if not problems else "FAIL: " + ", ".join(problems)),
        ]
        if ginfo:
            summary += [
                "5. **Ghidra's own parser.** `--ghidra-cp` (or `--ghidra-install`) compiles a small Java harness "
                "(embedded in the script) against Ghidra's classes. The harness parses `d2bs_types.h` with "
                "`ghidra.app.util.cparser.C.CParser` into a `StandAloneDataTypeManager` that uses the "
                "x86win.cspec data organisation (MS bit-field convention), then compares every composite with step 1. "
                "`--ghidra-install DIR` builds the classpath from a release layout (`Ghidra/Framework/*/lib/*.jar`, "
                "`Ghidra/Features/Base/lib/*.jar`); this revision was checked through `%s`. "
                "Parser used: %s. Result: parse succeeded with no messages; %d composites and "
                "%d fields (%d bit-fields) match, %d structs carry explicit pack 1%s." % (
                    "--ghidra-cp" if a.ghidra_cp else "--ghidra-install",
                    a.ghidra_label or "Ghidra CParser from the given classpath", ginfo["composites"], ginfo["fields"],
                    ginfo["bitfields"], ginfo["packed"],
                    ("; `d2bs_types.h` followed by all %d FUNC prototypes and %d DATA declarations of `%s` also "
                     "parses (%d prototypes come out `__stdcall`, %d `__fastcall`, %d `__cdecl`%s)" % (
                         ginfo["tsv_funcs"], ginfo["tsv_data"], SYMBOLS_TSV, ginfo["tsv_stdcall"], ginfo["tsv_fastcall"],
                         ginfo["tsv_cdecl"],
                         "; %d DATA row(s) without a type are skipped" % ginfo["tsv_data_untyped"]
                         if ginfo["tsv_data_untyped"] else ""))
                    if "tsv_funcs" in ginfo else ""),
                "   The same run re-tests the CParser behaviour this page relies on, using small probe headers. "
                "Bare `#pragma pack(push)`/`pack(1)`/`pack(pop)` leaves the next struct packed (sizeof %s instead of 8). "
                "`pack(push, 1)`/`pack(pop)` restores it (%s). `__attribute__((packed))` is ignored (sizeof %s). "
                "After `typedef void VOID;` a `(VOID)` parameter list does not parse. "
                "`RET (__stdcall *p)(...)` loses the calling convention (`%s`), while `RET __stdcall (*p)(...)` keeps it (`%s`)." % (
                    ginfo["probe_bare_push"]["B"], ginfo["probe_push_1"]["B"], ginfo["probe_attr_packed"]["A"],
                    ginfo["probe_cc_inside"]["A_t"], ginfo["probe_cc_inside"]["B_t"]),
            ]
        summary += [
            "",
            "Re-run with `python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check` "
            "(add `--ghidra-install <ghidra dir>` or `--ghidra-cp <classpath>` for step 5, and `--work DIR` to keep "
            "the probe files).",
        ]
        gen_markdown(repo, parser, cmodel, truth, ptrs, a.structs_md, summary)
        print("wrote %s" % a.structs_md)
    return rc


def shorten(arg, work, repo=None):
    if arg.startswith(work):
        return "$WORK" + arg[len(work):]
    if repo and arg == repo:
        return "."
    if os.path.isabs(arg) and "/" in arg and (arg.endswith("clang") or arg.endswith("clang++")):
        return os.path.basename(arg)
    return arg


if __name__ == "__main__":
    sys.exit(main())

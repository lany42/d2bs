#!/usr/bin/env python3
"""Extract every Game.exe (Diablo II 1.14d) address used by D2BS into a TSV symbol file.

Usage:
    python3 docs/ghidra/tools/gen_symbols.py --repo <repo root> --out docs/ghidra/d2bs_symbols.tsv \
        [--markdown docs/memory/offsets.md] [--quiet]

Sources parsed (all paths relative to --repo):
  * D2Ptrs.h      FUNCPTR / VARPTR / ASMPTR entries (active and commented-out), alias #defines
  * Patch.h       Patches[] and Conditional[] PatchHook tables (active and commented-out)
  * MPQStats.cpp  BaseStatTable[] (absolute Game.exe VAs and sgptDataTable-relative offsets)
  * every other GetDllOffset("<dll>", <expr>) call site in the compiled sources (JSUnit.cpp today)
  * a sweep of numeric literals inside __asm blocks and of absolute-VA-looking literals

Output TSV (UTF-8, LF, tab separated, no quoting, header row first):
    kind  module  name  rva  type  extra  status  comment  source

--markdown FILE: if FILE exists and contains region markers
    <!-- BEGIN GENERATED:<region> -->  ...  <!-- END GENERATED:<region> -->
only those regions are rewritten (hand-written text outside them is preserved); otherwise FILE
is written from scratch with every region in order.

Python 3 standard library only. Output is deterministic (source order).
Exit status: 0 on success, 1 if a validation check fails, 2 on usage / parse errors.
"""

import argparse
import bisect
import collections
import os
import re
import sys

IMAGE_BASE = 0x400000                 # Game.exe preferred image base (1.14d)
D2_113_CLIENT_BASE = 0x6FAB0000       # 1.13 D2Client.dll preferred base (see stale-comment check)
DLLOFFSET_MAX = 0x7FFFFF              # (offset << 8) must stay positive in a 32-bit int

TSV_HEADER = ["kind", "module", "name", "rva", "type", "extra", "status", "comment", "source"]

KNOWN_MODULES = ["D2CLIENT", "D2COMMON", "D2GFX", "D2LANG", "D2WIN", "D2NET", "D2GAME", "D2LAUNCH",
                 "FOG", "BNCLIENT", "STORM", "D2CMP", "D2MULTI", "D2MCPCLIENT", "GAME"]

# ASMPTR entries that point at data rather than code (kind DATA, empty type).
ASMPTR_DATA = {"D2CLIENT_BodyClickTable"}

# One-off GetDllOffset() call sites outside Patch.h, keyed by (repo-relative file, VA literal).
# name/type are documentation choices (the game symbol names are unknown); see docs/memory/offsets.md.
ONE_OFF_SITES = {
    ("JSUnit.cpp", 0x7BCBE8): ("D2CLIENT_ItemDescFlag", "BYTE"),
    ("JSUnit.cpp", 0x7BCBF4): ("D2CLIENT_ItemDescUnit", "UnitAny*"),
    ("JSUnit.cpp", 0x841EC8): ("D2WIN_ItemDescText", "wchar_t"),
}

# Absolute-VA-looking literals that are NOT game addresses: (file, regex on the line) -> reason.
NON_ADDRESS_LITERALS = [
    ("Constants.h", r"ITEM_FLAG_\w+\s+0x00400000", "item flag bit (ITEM_FLAG_ETHEREAL), not an address"),
    ("D2Handlers.cpp", r"lParam\s*&\s*0xFF0000", "scan-code mask on lParam, not an address"),
    ("JSUnit.cpp", r"-\s*0x400000", "image base subtracted from a VA (GetDllOffset argument)"),
    ("MPQStats.cpp", r"-\s*0x400000", "image base subtracted when rebasing BaseStatTable VAs"),
]

CC_KEYWORDS = ("__stdcall", "__fastcall", "__cdecl", "__thiscall", "__pascal", "WINAPI")
CTYPE_NORMALIZE = {"VOID": "void", "INT": "int", "CHAR": "char"}
EXCLUDE_DIRS = {"dependencies", "doc", "docs", ".git", "Debug", "Release", "resources"}
EXCLUDE_FILES = {"sqlite3.c", "sqlite3.h"}
SRC_EXT = (".cpp", ".c", ".h", ".hpp")

ID_RE = re.compile(r"[A-Za-z_]\w*")


# --------------------------------------------------------------------------------------------
# Lexing helpers
# --------------------------------------------------------------------------------------------

class Source:
    """A source file with comments (and optionally string bodies) blanked out.

    code      : same length as text; comments replaced by spaces (newlines kept)
    comments  : list of (start, end, body) for every comment
    """

    def __init__(self, repo, rel):
        self.rel = rel.replace(os.sep, "/")
        with open(os.path.join(repo, rel), "r", encoding="utf-8", errors="replace", newline="") as fh:
            self.text = fh.read().replace("\r\n", "\n").replace("\r", "\n")
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", self.text)]
        self.code, self.comments = lex(self.text, keep_strings=True)
        self.code_nostr, _ = lex(self.text, keep_strings=False)
        self.lines = self.text.split("\n")

    def line_of(self, pos):
        return bisect.bisect_right(self.line_starts, pos)

    def comments_on_line(self, line):
        return [c for c in self.comments if self.line_of(c[0]) == line]


def lex(text, keep_strings):
    out = []
    comments = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            comments.append((i, j, text[i + 2:j]))
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            seg = text[i:j]
            comments.append((i, j, seg[2:-2]))
            out.append(re.sub(r"[^\n]", " ", seg))
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            seg = text[i:j]
            if keep_strings or len(seg) < 2:
                out.append(seg)
            else:
                out.append(seg[0] + re.sub(r"[^\n]", " ", seg[1:-1]) + seg[-1])
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out), comments


def match_paren(s, open_pos, open_ch="(", close_ch=")"):
    """Return index of the bracket matching s[open_pos], or -1."""
    depth = 0
    for k in range(open_pos, len(s)):
        ch = s[k]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return k
    return -1


def split_top(s, sep=","):
    """Split on sep at bracket depth 0 (round, curly and square brackets)."""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def preprocessor_spans(code):
    """Yield (start, end, text) for every preprocessor directive (with backslash continuations)."""
    spans = []
    pos = 0
    n = len(code)
    while pos < n:
        eol = code.find("\n", pos)
        eol = n if eol == -1 else eol
        line = code[pos:eol]
        if line.lstrip().startswith("#"):
            start = pos
            end = eol
            while code[start:end].rstrip().endswith("\\") and end < n:
                nxt = code.find("\n", end + 1)
                end = n if nxt == -1 else nxt
            spans.append((start, end, code[start:end]))
            pos = end + 1
        else:
            pos = eol + 1
    return spans


def blank(code, spans):
    chars = list(code)
    for s, e, _ in spans:
        for k in range(s, e):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)


def blank_if0(code):
    """Blank `#if 0` ... `#else/#endif` regions (only literal `#if 0`)."""
    lines = code.split("\n")
    out, skip_depth, depth = [], None, 0
    for ln in lines:
        s = ln.strip()
        if re.match(r"#\s*if(def|ndef)?\b", s):
            depth += 1
            if skip_depth is None and re.match(r"#\s*if\s+0\b", s):
                skip_depth = depth
                out.append(" " * len(ln))
                continue
        elif re.match(r"#\s*endif\b", s):
            if skip_depth is not None and depth == skip_depth:
                skip_depth = None
                depth -= 1
                out.append(" " * len(ln))
                continue
            depth -= 1
        elif re.match(r"#\s*(else|elif)\b", s) and skip_depth is not None and depth == skip_depth:
            skip_depth = None
            out.append(" " * len(ln))
            continue
        out.append(" " * len(ln) if skip_depth is not None else ln)
    return "\n".join(out)


def parse_int(expr):
    """Evaluate a tiny integer expression made of literals, + and - (e.g. "0x7BCBE8 - 0x400000")."""
    e = re.sub(r"^\((?:DWORD|BYTE|WORD|int|INT)\)\s*", "", expr.strip())
    if not re.fullmatch(r"[0-9A-Fa-fxX+\-\s()]+", e):
        raise ValueError("not a literal expression: %r" % expr)
    total, sign = 0, 1
    for part in re.findall(r"0[xX][0-9A-Fa-f]+|\d+|[+\-]", e):
        if part == "+":
            continue
        if part == "-":
            sign = -sign
            continue
        total += sign * int(part, 0)
        sign = 1
    return total


def hexs(v):
    return "0x%X" % v


def cell(s):
    return (s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


# --------------------------------------------------------------------------------------------
# C type normalisation
# --------------------------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+|\d+|\.\.\.|[*&(),\[\]]|\S")


def join_tokens(tokens):
    tokens = [CTYPE_NORMALIZE.get(t, t) for t in tokens]
    out = ""
    prev = None
    for k, t in enumerate(tokens):
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        word = bool(re.match(r"[A-Za-z_0-9]", t))
        if prev is None:
            out = t
        elif t == ",":
            out += ","
        elif t in (")", "]", "[", "*", "&"):
            out += t           # "*" attaches to the type on the left: "UnitAny*"
        elif t == "(":
            # declarator group of a function-pointer parameter: "BOOL (__stdcall* cb)(...)"
            out += " (" if (nxt == "*" or nxt in CC_KEYWORDS) and prev != "(" else "("
        elif word:
            out += t if prev in ("(", "[") else " " + t
        else:
            out += " " + t
        prev = t
    out = re.sub(r",(?=\S)", ", ", out)
    out = re.sub(r"\bunsigned(?!\s+(int|char|short|long))\b", "unsigned int", out)
    return out.strip()


def norm_type(s):
    return join_tokens(TOKEN_RE.findall(s.strip()))


def split_cc(t1):
    toks = TOKEN_RE.findall(t1)
    cc = [t for t in toks if t in CC_KEYWORDS]
    rest = [t for t in toks if t not in CC_KEYWORDS]
    ccs = cc[0] if cc else ""
    if ccs == "WINAPI":
        ccs = "__stdcall"
    return join_tokens(rest), ccs


def norm_params(t2):
    inner = t2.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    inner = inner.strip()
    if inner == "" or inner.upper() == "VOID":
        return "void"
    return ", ".join(join_tokens(TOKEN_RE.findall(p)) for p in split_top(inner))


# --------------------------------------------------------------------------------------------
# Comment classification
# --------------------------------------------------------------------------------------------

VA_BASE_RE = re.compile(r"(?<![0-9A-Za-z])(?:0x)?([0-9A-Fa-f]{6,8})\s*-\s*BASE", re.I)
VA_113_RE = re.compile(r"(?<![0-9A-Za-z])(?:0x)?(6F[0-9A-Fa-f]{6})(?![0-9A-Za-z])", re.I)


def classify_comment(comment):
    info = {
        "va": None, "va113": None,
        "m114d": bool(re.search(r"1\.14d", comment, re.I)),
        "m114b": bool(re.search(r"1\.14b", comment, re.I)),
        "m113": bool(re.search(r"1\.1[23]", comment)),
    }
    m = VA_BASE_RE.search(comment)
    if m:
        info["va"] = int(m.group(1), 16)
    m = VA_113_RE.search(comment)
    if m:
        info["va113"] = int(m.group(1), 16)
    return info


def version_status(rva, cinfo):
    """Status flags derived from the trailing comment (see docs/memory/offsets.md#status-flags)."""
    flags = []
    if rva is None:
        return flags
    va = IMAGE_BASE + rva
    if cinfo["va"] is not None and cinfo["va"] != va:
        flags.append("va-comment-mismatch")
    va_ok = cinfo["va"] is not None and cinfo["va"] == va
    if cinfo["va113"] is not None or (cinfo["m113"] and not cinfo["m114d"]):
        flags.append("stale-pre-1.14d?")
    elif cinfo["m114d"] and va_ok:
        flags.append("ported-1.14d")
    elif va_ok:
        flags.append("va-only")
    elif not cinfo["m114d"]:
        flags.append("stale-pre-1.14d?")
    else:
        flags.append("ported-1.14d-unverified")
    return flags


# --------------------------------------------------------------------------------------------
# D2Ptrs.h
# --------------------------------------------------------------------------------------------

MACRO_RE = re.compile(r"\b(FUNCPTR|VARPTR|ASMPTR)\s*\(")
NARGS = {"FUNCPTR": 5, "VARPTR": 4, "ASMPTR": 3}


def parse_macro_args(s, open_pos):
    close = match_paren(s, open_pos)
    if close < 0:
        return None, -1
    return split_top(s[open_pos + 1:close]), close


def parse_d2ptrs(src, errors):
    pp = preprocessor_spans(src.code)
    code = blank(src.code, pp)
    entries = []
    for m in MACRO_RE.finditer(code):
        macro = m.group(1)
        args, close = parse_macro_args(code, m.end() - 1)
        if args is None or len(args) != NARGS[macro]:
            errors.append("D2Ptrs.h:%d: cannot parse %s(...)" % (src.line_of(m.start()), macro))
            continue
        e = {"macro": macro, "start": m.start(), "close": close,
             "line": src.line_of(m.start()), "end_line": src.line_of(close),
             "module": args[0], "short": args[1]}
        if macro == "FUNCPTR":
            e["t1"], e["t2"], off = args[2], args[3], args[4]
        elif macro == "VARPTR":
            e["t1"], off = args[2], args[3]
        else:
            off = args[2]
        e["offset_text"] = off
        e["offset"] = parse_int(off)
        entries.append(e)
    # trailing comment: comments on the entry's last line, after its ')' and before the next entry
    for e in entries:
        same_line_later = [x for x in entries if x is not e and x["end_line"] == e["end_line"]
                           and x["close"] > e["close"]]
        texts = []
        for (cs, ce, body) in src.comments_on_line(e["end_line"]):
            if cs > e["close"] and not any(x["close"] < cs for x in same_line_later):
                texts.append(body.strip())
        e["comment"] = " //".join(t for t in texts)
        e["comment"] = re.sub(r"\s+", " ", e["comment"]).strip()
    # alias macros (#define NAME(...) body) in D2Ptrs.h, excluding the X-macro machinery
    aliases = []
    for s, e_, text in pp:
        m = re.match(r"\s*#\s*define\s+(\w+)(\([^)]*\))?\s*(.*)", text.replace("\\\n", " "), re.S)
        if not m or m.group(1) in ("FUNCPTR", "VARPTR", "ASMPTR", "DLLOFFSET", "__D2PTRS_H__"):
            continue
        aliases.append({"name": m.group(1), "params": m.group(2) or "", "body": m.group(3).strip(),
                        "line": src.line_of(s)})
    # DLLNO enum
    m = re.search(r"enum\s*\{([^}]*DLLNO_[^}]*)\}", code)
    dllno = [x.strip()[len("DLLNO_"):] for x in m.group(1).split(",") if x.strip()] if m else []
    # disabled (commented-out) entries and aliases
    disabled = []
    for (cs, ce, body) in src.comments:
        line = src.line_of(cs)
        for mm in MACRO_RE.finditer(body):
            close = match_paren(body, mm.end() - 1)
            if close < 0:
                disabled.append({"line": line, "raw": body.strip(), "parsed": False})
                continue
            args = split_top(body[mm.end():close])
            rest = body[close + 1:].strip()
            # continuation comment on the next line of the form "// //004F6510-BASE"
            nxt = src.comments_on_line(line + 1)
            if nxt and src.lines[line].strip().startswith("//") and not MACRO_RE.search(nxt[0][2]) \
                    and nxt[0][2].strip().startswith("//"):
                rest = (rest + " " + nxt[0][2].strip()).strip()
            d = {"line": line, "macro": mm.group(1), "args": args, "rest": rest, "parsed": True,
                 "raw": body.strip()}
            try:
                d["offset"] = parse_int(args[-1])
            except (ValueError, IndexError):
                d["offset"] = None
            disabled.append(d)
        dm = re.match(r"\s*#\s*define\s+(\w+)", body)
        if dm:
            disabled.append({"line": line, "macro": "#define", "args": [dm.group(1)], "rest": body.strip(),
                             "parsed": True, "raw": body.strip(), "offset": None})
    return entries, aliases, dllno, disabled


# --------------------------------------------------------------------------------------------
# Patch.h
# --------------------------------------------------------------------------------------------

PATCH_ENTRY_RE = re.compile(r"\{\s*(Patch(?:Call|Jmp|Bytes))\s*,")
GDO_RE = re.compile(r'GetDllOffset\(\s*"([^"]+)"\s*,\s*([^)]+?)\s*\)')


def dll_module(dll):
    base = re.sub(r"\.dll$", "", dll, flags=re.I).upper()
    return base if base in KNOWN_MODULES else "GAME"


def parse_patch_entry(text):
    m = PATCH_ENTRY_RE.match(text.strip())
    if not m:
        return None
    inner = text.strip()[1:]
    inner = inner[:match_paren("{" + inner, 0, "{", "}") - 1] if "}" in inner else inner
    fields = split_top(inner)
    if len(fields) < 4:
        return None
    g = GDO_RE.search(fields[1])
    if not g:
        return None
    tgt = fields[2]
    mt = re.match(r"\(\s*(DWORD|BYTE|WORD)\s*\)\s*(\w+)", tgt)
    cast, target = (mt.group(1), mt.group(2)) if mt else ("", tgt)
    return {"func": m.group(1), "dll": g.group(1), "offset_text": g.group(2),
            "offset": parse_int(g.group(2)), "cast": cast, "target": target,
            "len": parse_int(fields[3]),
            "cond": fields[4].lstrip("&").strip() if len(fields) > 4 else ""}


def parse_patch_h(src, errors):
    tables = []
    disabled = []
    code = src.code
    for m in re.finditer(r"PatchHook\s+(\w+)\s*\[\s*\]\s*=\s*\{", code):
        open_pos = m.end() - 1
        close = match_paren(code, open_pos, "{", "}")
        body_start = open_pos + 1
        k = body_start
        entries = []
        while k < close:
            if code[k] == "{":
                c2 = match_paren(code, k, "{", "}")
                txt = code[k:c2 + 1]
                p = parse_patch_entry(txt)
                if p is None:
                    errors.append("Patch.h:%d: cannot parse entry" % src.line_of(k))
                else:
                    p["line"] = src.line_of(k)
                    p["end_line"] = src.line_of(c2)
                    texts = [b.strip() for (cs, ce, b) in src.comments_on_line(p["end_line"]) if cs > c2]
                    p["comment"] = re.sub(r"\s+", " ", " //".join(texts)).strip()
                    p["table"] = m.group(1)
                    entries.append(p)
                k = c2 + 1
            else:
                k += 1
        tables.append((m.group(1), src.line_of(m.start()), entries))
    for (cs, ce, body) in src.comments:
        b = re.sub(r"/\*.*?\*/", "", body)
        mm = PATCH_ENTRY_RE.search(b)
        if mm:
            p = parse_patch_entry(b[mm.start():])
            line = src.line_of(cs)
            if p:
                close = b.find("}", mm.start())
                p["line"] = line
                p["rest"] = b[close + 1:].strip(" ,") if close >= 0 else ""
                p["raw"] = body.strip()
                disabled.append(p)
    return tables, disabled


# --------------------------------------------------------------------------------------------
# MPQStats.cpp
# --------------------------------------------------------------------------------------------

def parse_mpqstats(src, errors):
    rows = []
    m = re.search(r"MPQTable\s+(\w+)\s*\[\s*\]\s*=\s*\{", src.code)
    if not m:
        errors.append("MPQStats.cpp: BaseStatTable[] not found")
        return None, rows
    close = match_paren(src.code, m.end() - 1, "{", "}")
    k = m.end()
    index = 0
    while k < close:
        if src.code[k] == "{":
            c2 = match_paren(src.code, k, "{", "}")
            f = split_top(src.code[k + 1:c2])
            if len(f) >= 4:
                name = re.match(r'"([^"]*)"', f[3]).group(1)
                texts = [b.strip() for (cs, ce, b) in src.comments_on_line(src.line_of(c2)) if cs > c2]
                rows.append({"index": index, "entry": parse_int(f[0]), "max": parse_int(f[1]),
                             "field_table": f[2], "name": name, "line": src.line_of(k),
                             "comment": re.sub(r"\s+", " ", " //".join(texts)).strip()})
                index += 1
            k = c2 + 1
        else:
            k += 1
    # confirm the rebasing rule the rows rely on
    rule = {}
    for ln_no, ln in enumerate(src.lines, 1):
        if re.search(r"dwTableOffset\s*<=\s*0xFFFF", ln):
            rule["le_ffff"] = ln_no
        if re.search(r"dwTableOffset\s*-\s*0x400000", ln):
            rule["rebase_entry"] = ln_no
        if re.search(r"dwMaxEntriesOffset\s*>\s*0xFFFF", ln):
            rule["gt_ffff_max"] = ln_no
        if re.search(r"dwMaxEntries\s*=\s*0xFF\b", ln):
            rule["default_max"] = ln_no
    return {"var": m.group(1), "line": src.line_of(m.start()), "rule": rule}, rows


# --------------------------------------------------------------------------------------------
# Whole-repo code model: contexts, macros, references, reachability
# --------------------------------------------------------------------------------------------

def list_sources(repo):
    out = []
    for root, dirs, files in os.walk(repo):
        rel_root = os.path.relpath(root, repo)
        parts = [] if rel_root == "." else rel_root.split(os.sep)
        if parts and parts[0] in EXCLUDE_DIRS:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not (not parts and d in EXCLUDE_DIRS))
        for f in sorted(files):
            if f.endswith(SRC_EXT) and f not in EXCLUDE_FILES:
                out.append(os.path.normpath(os.path.join(rel_root, f)) if parts else f)
    return sorted(out, key=lambda p: p.replace(os.sep, "/").lower())


def top_level_has(s, ch):
    depth = 0
    for k, c in enumerate(s):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == ch and depth == 0:
            if ch == "=" and (s[k + 1:k + 2] == "=" or s[k - 1:k] in "=!<>"):
                continue
            return True
    return False


SKIP_CALLEES = {"__declspec", "__attribute__", "alignas", "decltype", "throw", "noexcept", "sizeof", "__pragma"}


def func_name(header):
    h = header
    k = 0
    while k < len(h):
        if h[k] == "(":
            close = match_paren(h, k)
            if close < 0:
                return None
            before = h[:k].rstrip()
            m = re.search(r"([~A-Za-z_][\w]*(?:\s*::\s*~?[A-Za-z_]\w*)*)$", before)
            ident = re.sub(r"\s+", "", m.group(1)) if m else ""
            if ident and ident.split("::")[-1] not in SKIP_CALLEES:
                inner = h[k + 1:close].strip()
                if re.fullmatch(r"[A-Z0-9_]+", ident) and re.fullmatch(r"[A-Za-z_]\w*", inner) \
                        and h[close + 1:].strip() == "":
                    return inner                    # JSAPI_FUNC(name) style definitions
                return ident.split("::")[-1]
            k = close + 1
            continue
        k += 1
    return None


class CodeModel:
    def __init__(self, repo, files, exclude_ctx=("D2Ptrs.h",)):
        self.ctx = []           # dicts: file, kind(func|init|container), name, start_line, end_line, wrapper, native
        self.occ = []           # (ident, file, line, ctx_index or None, where) where in ctx|macro|decl
        self.macros = {}        # name -> list of (file, line, body identifiers)
        self.srcs = {}
        for rel in files:
            src = Source(repo, rel)
            self.srcs[src.rel] = src
            self._scan(src, parse_contexts=src.rel not in exclude_ctx)

    def _scan(self, src, parse_contexts):
        code = blank_if0(src.code_nostr)
        pp = preprocessor_spans(code)
        for s, e, text in pp:
            t = text.replace("\\\n", " ")
            m = re.match(r"\s*#\s*define\s+(\w+)(\([^)]*\))?(.*)", t, re.S)
            if m:
                body = m.group(3)
                ids = ID_RE.findall(body)
                self.macros.setdefault(m.group(1), []).append((src.rel, src.line_of(s), ids))
                for mm in ID_RE.finditer(body):
                    self.occ.append((mm.group(0), src.rel, src.line_of(s), None, "macro:" + m.group(1)))
        code = blank(code, pp)
        if not parse_contexts:
            return
        depth, seg_start, transparent, cur = 0, 0, 0, None
        n = len(code)
        k = 0
        while k < n:
            c = code[k]
            if c == "{":
                if depth == 0:
                    header = code[seg_start:k]
                    hs = re.sub(r"\s+", " ", header).strip()
                    if re.match(r"^(namespace\b.*|extern\s*\"\s*\")$", hs):
                        transparent += 1
                        seg_start = k + 1
                        k += 1
                        continue
                    hs = re.sub(r"^template\s*<.*?>\s*", "", hs)
                    if top_level_has(hs, "="):
                        kind, name = "init", (re.findall(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*=", hs) or ["?"])[-1]
                    elif "(" in hs and not re.match(r"^(typedef\s+)?(struct|class|union|enum)\b[^(]*$", hs):
                        name = func_name(hs)
                        kind = "func" if name else "container"
                    else:
                        kind, name = "container", hs[:40]
                    cur = {"file": src.rel, "kind": kind, "name": name or "?", "header": hs,
                           "start": k, "start_line": src.line_of(seg_start + len(header) - len(header.lstrip())),
                           "native": bool(re.match(r"^JSAPI_(FUNC|PROP|STRICT_PROP)\s*\(", hs)),
                           "naked": "naked" in hs}
                depth += 1
            elif c == "}":
                if depth == 0:
                    if transparent:
                        transparent -= 1
                    seg_start = k + 1
                else:
                    depth -= 1
                    if depth == 0 and cur is not None:
                        cur["end"] = k
                        cur["end_line"] = src.line_of(k)
                        body = code[cur["start"]:k]
                        cur["asm"] = bool(re.search(r"\b_?_asm\b", body))
                        cur["wrapper"] = cur["kind"] == "func" and (
                            cur["naked"] or cur["asm"] or re.search(r"_?(ASM|STUB)$", cur["name"]) is not None)
                        idx = len(self.ctx)
                        self.ctx.append(cur)
                        cases = [(mm.start() + cur["start"], mm.group(1)) for mm in
                                 re.finditer(r"\bcase\s+([A-Za-z_]\w*)\s*:", body)]
                        case_pos = [p for p, _ in cases]
                        for mm in ID_RE.finditer(body):
                            pos = mm.start() + cur["start"]
                            ci = bisect.bisect_right(case_pos, pos) - 1
                            case = cases[ci][1] if ci >= 0 else None
                            self.occ.append((mm.group(0), src.rel, src.line_of(pos), idx, case))
                        # the header (parameter list, return type) is part of the context too
                        cur = None
                        seg_start = k + 1
            elif c == ";" and depth == 0:
                stmt = code[seg_start:k]
                ss = re.sub(r"\s+", " ", stmt).strip()
                if ss and top_level_has(ss, "=") and not ss.startswith("typedef"):
                    idx = len(self.ctx)
                    name = (re.findall(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*=", ss) or ["?"])[-1]
                    self.ctx.append({"file": src.rel, "kind": "init", "name": name, "header": ss[:60],
                                     "start_line": src.line_of(seg_start), "end_line": src.line_of(k),
                                     "native": False, "naked": False, "asm": False, "wrapper": False})
                    rhs = stmt[stmt.find("=") + 1:]
                    base = seg_start + stmt.find("=") + 1
                    for mm in ID_RE.finditer(rhs):
                        self.occ.append((mm.group(0), src.rel, src.line_of(base + mm.start()), idx, None))
                seg_start = k + 1
            k += 1

    # ---- derived indexes ------------------------------------------------------------------
    def build(self):
        self.by_ident = collections.defaultdict(list)
        for o in self.occ:
            self.by_ident[o[0]].append(o)
        self.funcs = collections.defaultdict(list)          # name -> ctx indexes
        for i, c in enumerate(self.ctx):
            if c["kind"] == "func":
                self.funcs[c["name"]].append(i)
        self.body_ids = collections.defaultdict(set)        # ctx index -> identifiers
        for o in self.occ:
            if o[3] is not None:
                self.body_ids[o[3]].add(o[0])
        # liveness: roots are initializers/containers + DllMain + exported QueryInterface
        live = set(["DllMain", "QueryInterface"])
        work = list(live)
        for i, c in enumerate(self.ctx):
            if c["kind"] in ("init", "container"):
                for ident in self.body_ids[i]:
                    if ident not in live:
                        live.add(ident)
                        work.append(ident)
        while work:
            name = work.pop()
            nxt = set()
            for i in self.funcs.get(name, []):
                nxt |= self.body_ids[i]
            for (_f, _l, ids) in self.macros.get(name, []):
                nxt |= set(ids)
            for ident in nxt:
                if ident not in live:
                    live.add(ident)
                    work.append(ident)
        self.live = live

    def is_wrapper_ctx(self, idx):
        return idx is not None and self.ctx[idx]["wrapper"]

    def carriers(self, ident):
        """Wrapper functions and macros whose body references ident (one level)."""
        out = []
        for o in self.by_ident.get(ident, []):
            if o[3] is not None and self.ctx[o[3]]["wrapper"]:
                out.append(("wrapper", self.ctx[o[3]]["name"]))
            elif o[3] is None and isinstance(o[4], str) and o[4].startswith("macro:"):
                out.append(("macro", o[4][6:]))
        return sorted(set(out))

    def use_sites(self, ident):
        """Occurrences that are uses: in a function body or initializer, not a macro/decl."""
        return [o for o in self.by_ident.get(ident, []) if o[3] is not None]

    def analyse_symbol(self, idents):
        """Return dict with direct sites, carrier chain, transparent use sites, liveness."""
        names = list(idents)
        via = []
        seen = set(names)
        queue = list(names)
        while queue:
            n = queue.pop(0)
            for kind, cname in self.carriers(n):
                if cname not in seen:
                    seen.add(cname)
                    via.append((kind, cname))
                    queue.append(cname)
        all_names = names + [c for _, c in via]
        sites = []
        for n in all_names:
            for o in self.use_sites(n):
                sites.append(o)
        # "transparent" uses: sites not inside a wrapper body (wrappers are pass-through)
        # wrappers/macros are pass-through: an occurrence inside a wrapper body is not a use by
        # itself; the wrapper's own use sites (its name is in all_names) are.
        uses = [o for o in sites if not self.ctx[o[3]]["wrapper"]]
        live = any(n in self.live for n in names)
        return {"names": names, "via": via, "sites": sites, "uses": uses, "live": live}

    def reverse_entrypoints(self, idents, limit=400):
        """Name-based reverse reachability from idents to JS natives / initializer roots."""
        natives = {}            # native name -> set(case labels)
        roots = set()
        seen = set(idents)
        queue = list(idents)
        steps = 0
        while queue and steps < 20000:
            steps += 1
            n = queue.pop(0)
            for o in self.by_ident.get(n, []):
                if o[3] is None:
                    if isinstance(o[4], str) and o[4].startswith("macro:"):
                        mname = o[4][6:]
                        if mname not in seen:
                            seen.add(mname)
                            queue.append(mname)
                    continue
                c = self.ctx[o[3]]
                if c["kind"] in ("init", "container"):
                    if c["name"] not in getattr(self, "js_tables", ()):
                        roots.add("%s[] (%s:%d)" % (c["name"], c["file"], c["start_line"]))
                    continue
                if c["native"]:
                    natives.setdefault(c["name"], set())
                    if o[4]:
                        natives[c["name"]].add(o[4])
                if c["name"] not in seen and c["name"] in self.live:
                    seen.add(c["name"])
                    queue.append(c["name"])
        return natives, roots


# --------------------------------------------------------------------------------------------
# JS name tables (JS_FS / JS_FN / JSPropertySpec)
# --------------------------------------------------------------------------------------------

def js_name_tables(model):
    funcs = collections.defaultdict(list)       # C native -> ["table.jsname"]
    props = collections.defaultdict(list)       # (getter/setter native, TINYID) -> ["table.jsname"]
    for rel, src in model.srcs.items():
        code = src.code
        for m in re.finditer(r"(\w+)\s*\[\s*\]\s*=\s*\{", code):
            table = m.group(1)
            close = match_paren(code, m.end() - 1, "{", "}")
            body = code[m.end():close]
            for f in re.finditer(r'JS_F[SN]\(\s*"([^"]+)"\s*,\s*(\w+)', body):
                funcs[f.group(2)].append("%s.%s" % (table, f.group(1)))
            for p in re.finditer(r'\{\s*"([^"]+)"\s*,\s*(\w+)\s*,[^{}]*?JSOP_WRAPPER\((\w+)\)(?:\s*,\s*JSOP_WRAPPER\((\w+)\))?',
                                 body):
                for nat in (p.group(3), p.group(4)):
                    if nat:
                        props[(nat, p.group(2))].append("%s.%s" % (table, p.group(1)))
    return funcs, props


# --------------------------------------------------------------------------------------------
# Main extraction
# --------------------------------------------------------------------------------------------

def build_rows(repo, errors, warnings):
    rows = []
    d2p = Source(repo, "D2Ptrs.h")
    entries, aliases, dllno, d2p_disabled = parse_d2ptrs(d2p, errors)
    for e in entries:
        ident = "%s_%s" % (e["module"], e["short"])
        cinfo = classify_comment(e["comment"])
        r = {"origin": "D2Ptrs.h", "macro": e["macro"], "module": e["module"], "ident": ident,
             "name": ident, "rva": e["offset"], "ordinal": None, "comment": e["comment"], "cinfo": cinfo,
             "source": "D2Ptrs.h:%d" % e["line"], "line": e["line"], "type": "", "cc": "", "extra": "",
             "status": []}
        if e["offset"] < 0:
            r["ordinal"], r["rva"] = -e["offset"], None
        if e["macro"] == "FUNCPTR":
            ret, cc = split_cc(e["t1"])
            r["kind"] = "FUNC"
            r["cc"] = cc
            r["ret"] = ret
            r["params"] = norm_params(e["t2"])
            r["type"] = "%s %s %s(%s)" % (ret, cc, ident, r["params"]) if cc else "%s %s(%s)" % (ret, ident, r["params"])
            r["decl_t1"], r["decl_t2"] = e["t1"], e["t2"]
        elif e["macro"] == "VARPTR":
            r["kind"] = "DATA"
            r["ident"] = "p_" + ident
            r["type"] = norm_type(e["t1"])
        else:
            r["kind"] = "DATA" if ident in ASMPTR_DATA else "LABEL"
        r["status"] += version_status(r["rva"], cinfo)
        rows.append(r)

    pat = Source(repo, "Patch.h")
    tables, patch_disabled = parse_patch_h(pat, errors)
    handler_count = collections.Counter()
    for tname, tline, pentries in tables:
        for p in pentries:
            kind = "PATCH" if tname == "Patches" else "COND_PATCH"
            ptype = {"PatchCall": "CALL", "PatchJmp": "JMP", "PatchBytes": "BYTES"}[p["func"]]
            if ptype == "BYTES":
                val = parse_int(p["target"]) & 0xFF       # PatchBytes memsets (BYTE)dwValue
                handler = "BYTES_%02X" % val
                target = "0x%02X" % val
            else:
                handler = p["target"]
                target = p["target"]
            handler_count[handler] += 1
            name = "D2BS_PATCH_%s" % handler + ("" if handler_count[handler] == 1 else "_%d" % handler_count[handler])
            extra = "len=%d;target=%s" % (p["len"], target)
            if kind == "COND_PATCH":
                extra += ";cond=%s" % p["cond"]
            cinfo = classify_comment(p["comment"])
            r = {"origin": "Patch.h", "kind": kind, "module": dll_module(p["dll"]), "ident": name, "name": name,
                 "rva": p["offset"], "ordinal": None, "type": ptype, "extra": extra, "comment": p["comment"],
                 "cinfo": cinfo, "source": "Patch.h:%d" % p["line"], "line": p["line"], "cc": "",
                 "status": version_status(p["offset"], cinfo), "patch": p, "dll": p["dll"], "table": tname}
            rows.append(r)

    mpq = Source(repo, "MPQStats.cpp")
    mpq_info, mpq_rows = parse_mpqstats(mpq, errors)
    for m in mpq_rows:
        for which, val, typ, suffix in (("entry", m["entry"], "void*", "Records"), ("max", m["max"], "DWORD", "Count")):
            if val > 0xFFFF:
                name = "D2COMMON_MPQ_%s_%s" % (m["name"], suffix)
                r = {"origin": "MPQStats.cpp", "kind": "DATA", "module": "D2COMMON", "ident": name, "name": name,
                     "rva": val - IMAGE_BASE, "ordinal": None, "type": typ, "extra": "", "comment": m["comment"],
                     "cinfo": classify_comment(m["comment"]), "source": "MPQStats.cpp:%d" % m["line"],
                     "line": m["line"], "cc": "", "status": ["va-only"], "mpq": m, "mpq_field": which,
                     "va_literal": val}
                rows.append(r)

    # every other GetDllOffset("<dll>", <expr>) call site
    other_sites = []
    for rel in list_sources(repo):
        rel = rel.replace(os.sep, "/")
        if rel in ("Patch.h", "Offset.cpp", "Offset.h", "D2Ptrs.h"):
            continue
        src = Source(repo, rel)
        for m in re.finditer(r"\bGetDllOffset\s*\(", src.code):
            close = match_paren(src.code, m.end() - 1)
            args = split_top(src.code[m.end():close])
            line = src.line_of(m.start())
            site = {"file": rel, "line": line, "args": args, "text": src.lines[line - 1].strip()}
            other_sites.append(site)
            if len(args) == 2 and re.fullmatch(r'"[^"]*"', args[0]):
                dll = args[0].strip('"')
                rva = parse_int(args[1])
                va = rva + IMAGE_BASE
                key = (rel, va)
                if key not in ONE_OFF_SITES:
                    warnings.append("%s:%d: GetDllOffset site not in ONE_OFF_SITES table (VA %s)" % (rel, line, hexs(va)))
                    name, typ = "GAME_%s_%d" % (re.sub(r"\W", "_", rel), line), ""
                else:
                    name, typ = ONE_OFF_SITES[key]
                texts = [b.strip() for (cs, ce, b) in src.comments_on_line(line)]
                comment = re.sub(r"\s+", " ", " //".join(texts)).strip()
                rows.append({"origin": rel, "kind": "DATA", "module": dll_module(dll), "ident": name, "name": name,
                             "rva": rva, "ordinal": None, "type": typ, "extra": "", "comment": comment,
                             "cinfo": classify_comment(comment), "source": "%s:%d" % (rel, line), "line": line,
                             "cc": "", "status": ["va-only"], "site": site, "dll": dll})
                site["row"] = name
            else:
                warnings.append("%s:%d: non-literal GetDllOffset call: %s" % (rel, line, site["text"]))
    ctx = {"d2p": d2p, "entries": entries, "aliases": aliases, "dllno": dllno, "d2p_disabled": d2p_disabled,
           "pat": pat, "tables": tables, "patch_disabled": patch_disabled, "mpq": mpq, "mpq_info": mpq_info,
           "mpq_rows": mpq_rows, "other_sites": other_sites}
    return rows, ctx


def mark_duplicates(rows):
    first = {}
    for r in rows:
        if r["rva"] is None:
            continue
        key = r["rva"]
        if key in first:
            r["status"].append("duplicate-address")
            if "duplicate-address" not in first[key]["status"]:
                first[key]["status"].append("duplicate-address")
            if r["kind"] not in ("PATCH", "COND_PATCH") and not r["extra"]:
                r["extra"] = "alias_of=%s" % first[key]["name"]
            r["dup_of"] = first[key]["name"]
        else:
            first[key] = r


def apply_usage_types(rows, model, casts):
    """VARPTRs whose every use casts p_X to a different pointer type: the object at the address
    is the cast's pointee (e.g. the InventoryLayout struct itself, not an InventoryLayout*)."""
    by_ident = collections.defaultdict(list)
    for c in casts:
        by_ident[c["ident"]].append(c)
    for r in rows:
        if r.get("macro") != "VARPTR" or r["ident"] not in by_ident:
            continue
        cs = by_ident[r["ident"]]
        uses = model.use_sites(r["ident"])
        kinds = set(c["cast"] for c in cs)
        if len(uses) == len(cs) and len(kinds) == 1:
            r["declared_type"] = r["type"]
            r["type"] = list(kinds)[0][:-1].strip()
            r["status"].append("type-from-usage")
            for c in cs:
                c["applied"] = True


def mark_static_captures(rows, model, dllno):
    """File-scope initialisers run during CRT start-up, before Startup() calls DefineOffsets()
    (D2BS.cpp). A D2Ptrs variable read there still holds its DLLOFFSET() encoding."""
    d2 = {r["ident"]: r for r in rows if r["origin"] == "D2Ptrs.h"}
    for ident, r in d2.items():
        caps = [o for o in model.use_sites(ident) if model.ctx[o[3]]["kind"] == "init"]
        if caps:
            r["status"].append("captured-encoded")
            r["captures"] = caps
            r["encoded"] = dllno.index(r["module"]) | (r["rva"] << 8)
    for r in rows:
        if r["origin"] == "Patch.h" and r["patch"]["target"] in d2:
            t = d2[r["patch"]["target"]]
            r["status"].append("captured-encoded")
            r["encoded_target"] = dllno.index(t["module"]) | (t["rva"] << 8)
            r["intended_target"] = IMAGE_BASE + t["rva"]


def analyse_references(rows, model, js_funcs, js_props):
    js_tables = set(v.split(".")[0] for vs in js_funcs.values() for v in vs) | \
        set(v.split(".")[0] for vs in js_props.values() for v in vs)
    model.js_tables = js_tables
    for r in rows:
        if r["origin"] != "D2Ptrs.h":
            continue
        a = model.analyse_symbol([r["ident"]])
        r["ref"] = a
        files = collections.Counter(o[1] for o in a["sites"] if o[1] != "D2Ptrs.h")
        r["ref_files"] = sorted(files.items(), key=lambda kv: kv[0].lower())
        if not a["uses"]:
            r["status"].append("unused")
        elif not a["live"]:
            r["status"].append("dead-code-only")
        if r["kind"] == "FUNC":
            direct = model.use_sites(r["ident"])
            if direct and all(model.ctx[o[3]]["asm"] or model.ctx[o[3]]["naked"] for o in direct):
                r["status"].append("asm-only")
        nats, roots = model.reverse_entrypoints([r["ident"]])
        r["natives"] = nats
        r["roots"] = roots
        r["js"] = js_names_for(nats, js_funcs, js_props)


def js_names_for(natives, js_funcs, js_props):
    out = set()
    for nat, cases in natives.items():
        names = []
        for case in sorted(cases):
            names += js_props.get((nat, case), [])
        if not names:
            names = js_funcs.get(nat, [])
        if not names:
            prop_any = sorted(set(v for (n, _), vs in js_props.items() if n == nat for v in vs))
            names = ["%s(*%d props)" % (nat, len(prop_any))] if prop_any else [nat]
        out |= set(names)
    return sorted(out)


# --------------------------------------------------------------------------------------------
# Hardcoded-literal sweeps
# --------------------------------------------------------------------------------------------

def asm_literal_sweep(model):
    out = []
    for rel, src in sorted(model.srcs.items()):
        code = src.code_nostr
        for m in re.finditer(r"\b_?_asm\b\s*\{", code):
            close = match_paren(code, m.end() - 1, "{", "}")
            body = code[m.end():close]
            base = m.end()
            for lm in re.finditer(r"[^\n]+", body):
                ln = lm.group(0)
                instr = re.sub(r"\s+", " ", ln.split(";")[0]).strip()
                for nm in re.finditer(r"(?<![\w$])(0[xX][0-9A-Fa-f]+|[0-9][0-9A-Fa-f]*[hH]|\d+)(?![\w])", ln.split(";")[0]):
                    tok = nm.group(1)
                    val = int(tok[:-1], 16) if tok[-1] in "hH" else int(tok, 0)
                    line = src.line_of(base + lm.start() + nm.start())
                    func = enclosing(model, rel, line)
                    out.append({"file": rel, "line": line, "func": func, "literal": tok, "value": val,
                                "instr": instr, "address": val >= 0x10000})
    return out


def enclosing(model, rel, line):
    best = None
    for c in model.ctx:
        if c["file"] == rel and c["start_line"] <= line <= c.get("end_line", -1):
            best = c["name"]
    return best or "?"


def absolute_literal_sweep(model, rows_sources):
    hits = []
    lit_re = re.compile(r"\b0[xX]([0-9A-Fa-f]{6,8})\b")
    for rel, src in sorted(model.srcs.items()):
        if rel in ("D2Ptrs.h", "Patch.h"):
            continue
        for ln_no, ln in enumerate(src.code_nostr.split("\n"), 1):
            for m in lit_re.finditer(ln):
                v = int(m.group(1), 16)
                if not (0x400000 <= v < 0x1000000 or 0x6F000000 <= v < 0x70000000):
                    continue
                full = src.lines[ln_no - 1]
                reason = None
                if "%s:%d" % (rel, ln_no) in rows_sources:
                    reason = "emitted as TSV row(s) (%s)" % ", ".join(rows_sources["%s:%d" % (rel, ln_no)])
                for f, rx, why in NON_ADDRESS_LITERALS:
                    if reason is None and rel == f and re.search(rx, full):
                        reason = why
                hits.append({"file": rel, "line": ln_no, "literal": m.group(0), "value": v,
                             "reason": reason or "UNCLASSIFIED", "text": full.strip()})
    return hits


def p_casts(model, rows):
    """(T*)p_X casts whose pointee type differs from the VARPTR type."""
    decl = {r["ident"]: r["type"] for r in rows if r.get("macro") == "VARPTR"}
    out = []
    for rel, src in sorted(model.srcs.items()):
        for m in re.finditer(r"\(\s*([A-Za-z_][\w\s]*?\s*\*+)\s*\)\s*(p_[A-Z0-9]+_\w+)", src.code_nostr):
            ident = m.group(2)
            if ident not in decl:
                continue
            cast = norm_type(m.group(1))
            declared = decl[ident] + "*"
            if cast != declared:
                out.append({"file": rel, "line": src.line_of(m.start()), "ident": ident, "declared": declared,
                            "cast": cast, "text": src.lines[src.line_of(m.start()) - 1].strip()})
    return out


# --------------------------------------------------------------------------------------------
# Independent (grep-style) counts for validation
# --------------------------------------------------------------------------------------------

def grep_counts(repo):
    def lines(rel):
        with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        # drop /* ... */ block comments (keeping their newlines) so a block-commented entry is not counted
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        return text.split("\n")
    c = collections.Counter()
    for ln in lines("D2Ptrs.h"):
        if ln.lstrip().startswith("#"):
            continue
        code = ln.split("//")[0]
        for k in ("FUNCPTR", "VARPTR", "ASMPTR"):
            c[k] += len(re.findall(r"\b%s\s*\(" % k, code))
    table = None
    for ln in lines("Patch.h"):
        mt = re.search(r"PatchHook\s+(\w+)\s*\[", ln)
        if mt:
            table = mt.group(1)
        code = ln.split("//")[0]
        c["patch:" + str(table)] += len(re.findall(r"GetDllOffset\s*\(", code))
    for ln in lines("MPQStats.cpp"):
        code = ln.split("//")[0]
        mt = re.match(r"\s*\{\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,", code)
        if mt:
            c["mpq_abs"] += sum(1 for v in mt.groups() if int(v, 0) > 0xFFFF)
    return c


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------

def rva_text(r):
    if r["ordinal"] is not None:
        return "ORD:%d" % r["ordinal"]
    return hexs(r["rva"])


def write_tsv(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(TSV_HEADER) + "\n")
        for r in rows:
            fields = [r["kind"], r["module"], r["name"], rva_text(r), r["type"], r["extra"],
                      ",".join(r["status"]), r["comment"], r["source"]]
            fh.write("\t".join(cell(f) for f in fields) + "\n")


def md_escape(s):
    return (s or "").replace("|", "\\|").replace("`", "'")


def code_span(s):
    return "`%s`" % s.replace("`", "'") if s else ""


def link(source, prefix="../../"):
    f, _, line = source.partition(":")
    return "[%s](%s%s#L%s)" % (source, prefix, f, line)


def refs_text(r, limit=14):
    if not r.get("ref_files"):
        return "-"
    parts = ["%s(%d)" % (f, n) for f, n in r["ref_files"]]
    if len(parts) > limit:
        parts = parts[:limit] + ["+%d files" % (len(parts) - limit)]
    s = ", ".join(parts)
    if r["ref"]["via"]:
        s += "; via " + ", ".join(code_span(n) for _, n in r["ref"]["via"])
    return s


def module_order(m):
    return KNOWN_MODULES.index(m) if m in KNOWN_MODULES else len(KNOWN_MODULES)


KIND_ORDER = {"FUNC": 0, "DATA": 1, "LABEL": 2, "PATCH": 3, "COND_PATCH": 4}


def md_symbols(rows):
    out = []
    d2 = [r for r in rows if r["origin"] == "D2Ptrs.h"]
    mods = sorted(set(r["module"] for r in d2), key=module_order)
    out.append("Rows: %d (FUNCPTR %d, VARPTR %d, ASMPTR %d). Generated from `D2Ptrs.h`; do not edit by hand.\n" % (
        len(d2), sum(1 for r in d2 if r["macro"] == "FUNCPTR"), sum(1 for r in d2 if r["macro"] == "VARPTR"),
        sum(1 for r in d2 if r["macro"] == "ASMPTR")))
    for mod in mods:
        out.append("### %s\n" % mod)
        for kind in ("FUNC", "DATA", "LABEL"):
            rs = [r for r in d2 if r["module"] == mod and r["kind"] == kind]
            if not rs:
                continue
            out.append("#### %s %s (%d)\n" % (mod, {"FUNC": "functions (FUNCPTR)", "DATA": "data (VARPTR / data ASMPTR)",
                                                     "LABEL": "code labels (ASMPTR)"}[kind], len(rs)))
            out.append("| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |")
            out.append("|---|---|---|---|---|---|---|---|---|")
            for r in rs:
                va = hexs(IMAGE_BASE + r["rva"]) if r["rva"] is not None else "-"
                kind_s = r["macro"] if r["kind"] != "DATA" or r["macro"] == "VARPTR" else "ASMPTR (data)"
                out.append("| %s<br>%s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    code_span(r["ident"]), link(r["source"]), kind_s, rva_text(r), va,
                    code_span(md_escape(r["type"])) + ("<br>(declared `%s`)" % r["declared_type"] if r.get("declared_type") else ""),
                    r["cc"] or "-", code_span(md_escape(r["comment"])) or "-",
                    md_escape(", ".join(r["status"])) or "-", refs_text(r)))
            out.append("")
    return "\n".join(out)


def md_disabled(ctx):
    out = ["#### `D2Ptrs.h` (commented out)\n",
           "| Source | Macro | Module / name | Old offset | 0x400000 + offset | Comment check | Remainder of comment |",
           "|---|---|---|---|---|---|---|"]
    for d in ctx["d2p_disabled"]:
        if not d.get("parsed"):
            out.append("| %s | ? | %s | | | | |" % (link("D2Ptrs.h:%d" % d["line"]), code_span(md_escape(d["raw"]))))
            continue
        if d["macro"] == "#define":
            out.append("| %s | `#define` | %s | - | - | - | %s |" % (link("D2Ptrs.h:%d" % d["line"]), code_span(d["args"][0]),
                                                                    code_span(md_escape(d["rest"]))))
            continue
        name = "%s_%s" % (d["args"][0], d["args"][1]) if len(d["args"]) > 1 else "?"
        off = d.get("offset")
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            link("D2Ptrs.h:%d" % d["line"]), d["macro"], code_span(name), hexs(off) if off is not None else "?",
            hexs(IMAGE_BASE + off) if off is not None else "-", comment_check(off, d["rest"]),
            code_span(md_escape(d["rest"])) or "-"))
    out.append("")
    out.append("#### `Patch.h` (commented out)\n")
    out.append("| Source | Patch | DLL string | Old offset | Handler | Len | Comment check | Remainder of comment |")
    out.append("|---|---|---|---|---|---|---|---|")
    for p in ctx["patch_disabled"]:
        out.append("| %s | %s | `%s` | %s | %s | %d | %s | %s |" % (
            link("Patch.h:%d" % p["line"]), p["func"], p["dll"], hexs(p["offset"]), code_span(p["target"]), p["len"],
            comment_check(p["offset"], p["rest"]), code_span(md_escape(p["rest"])) or "-"))
    out.append("")
    return "\n".join(out)


def comment_check(off, comment):
    if off is None:
        return "-"
    ci = classify_comment(comment or "")
    out = []
    if ci["va"] is not None:
        out.append("VA comment %s" % ("matches" if ci["va"] == IMAGE_BASE + off else "MISMATCH (%s)" % hexs(ci["va"])))
    if ci["va113"] is not None:
        out.append("1.13-style VA, VA-offset = %s" % hexs(ci["va113"] - off))
    for key, label in (("m114d", "says 1.14d"), ("m114b", "says 1.14b")):
        if ci[key]:
            out.append(label)
    if ci["m113"]:
        out.append("mentions 1.12/1.13")
    return "; ".join(out) or "no version info"


def md_asm_only(rows, model):
    out = ["FUNCPTRs that are only ever reached from inline-asm stubs. The C prototype in `D2Ptrs.h` is never used by "
           "the compiler for these calls; the stub's register shuffling shows the real ABI. See "
           "[call-stubs.md](call-stubs.md).\n",
           "| FUNCPTR | Declared prototype | Stub (file:line) | Stub instructions |", "|---|---|---|---|"]
    for r in rows:
        if "asm-only" not in r["status"]:
            continue
        stubs = []
        for o in model.use_sites(r["ident"]):
            c = model.ctx[o[3]]
            src = model.srcs[c["file"]]
            body = src.code_nostr[c["start"]:c["end"]]
            m = re.search(r"\b_?_asm\b\s*\{", body)
            instrs = []
            if m:
                close = match_paren(body, m.end() - 1, "{", "}")
                for ln in body[m.end():close].split("\n"):
                    t = re.sub(r"\s+", " ", ln.split(";")[0]).strip()
                    if t:
                        instrs.append(t)
            stubs.append((c["name"], "%s:%d" % (c["file"], c["start_line"]), "; ".join(instrs)))
        for name, where, instr in sorted(set(stubs)):
            out.append("| %s | %s | %s %s | %s |" % (code_span(r["ident"]), code_span(md_escape(r["type"])),
                                                    code_span(name), link(where), code_span(md_escape(instr))))
    out.append("")
    return "\n".join(out)


def md_patches(rows):
    out = ["| Name | Kind | DLL string | RVA | VA | Op | Len | Target | Condition | Source comment | Status |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["origin"] != "Patch.h":
            continue
        p = r["patch"]
        tgt = re.search(r"target=([^;]+)", r["extra"]).group(1)
        tgt_cell = code_span(tgt)
        if r.get("encoded_target") is not None:
            tgt_cell += "<br>**installed as %s** (DLLOFFSET-encoded value captured at static init; intended %s)" % (
                hexs(r["encoded_target"]), hexs(r["intended_target"]))
        out.append("| %s<br>%s | %s | `%s` | %s | %s | %s | %d | %s | %s | %s | %s |" % (
            code_span(r["name"]), link(r["source"]), r["kind"], p["dll"], rva_text(r), hexs(IMAGE_BASE + r["rva"]),
            r["type"], p["len"], tgt_cell, code_span(p["cond"]) or "-", code_span(md_escape(r["comment"])) or "-",
            ", ".join(r["status"]) or "-"))
    out.append("")
    return "\n".join(out)


def fillbasestat_sites(model, ctx, js_funcs):
    absolute = set(m["name"] for m in ctx["mpq_rows"] if m["entry"] > 0xFFFF)
    out = []
    for o in model.by_ident.get("FillBaseStat", []):
        if o[3] is None or o[1] == "MPQStats.cpp":
            continue
        c = model.ctx[o[3]]
        if c["kind"] != "func":
            continue
        line = model.srcs[o[1]].lines[o[2] - 1]
        m = re.search(r'FillBaseStat\(\s*(?:cx\s*,\s*&\w+\s*,\s*)?("([^"]*)"|[^,]+)', line)
        arg = m.group(1).strip() if m else "?"
        lit = m.group(2) if m and m.group(2) is not None else None
        if lit is None:
            hit = "dynamic"
        else:
            hit = "yes" if lit in absolute else "no (sgptDataTable-relative)"
        out.append({"file": o[1], "line": o[2], "func": c["name"], "arg": arg, "hit": hit,
                    "js": js_funcs.get(c["name"], [])})
    return sorted(out, key=lambda x: (x["file"].lower(), x["line"]))


def md_mpq(ctx, rows, fbs=()):
    info = ctx["mpq_info"]
    out = ["`%s[]` ([MPQStats.cpp:%d](../../MPQStats.cpp#L%d)). Rebasing rule, read from source: "
           "`dwEntry <= 0xFFFF` is an offset into `*p_D2COMMON_sgptDataTable` (line %s); otherwise it is an "
           "absolute 1.14d VA rebased as `VA - 0x400000 + GetModuleHandle(NULL)` (line %s, `d2CommonOff` from "
           "[MPQStats.h:10](../../MPQStats.h#L10)); `dwMaxEntriesOffset > 0xFFFF` is rebased the same way (line %s); "
           "`0` means \"use 0xFF rows\" (line %s).\n" % (
               info["var"], info["line"], info["line"], info["rule"].get("le_ffff", "?"),
               info["rule"].get("rebase_entry", "?"), info["rule"].get("gt_ffff_max", "?"),
               info["rule"].get("default_max", "?")),
           "| # | Table | dwEntry | Meaning | dwMaxEntriesOffset | Meaning | TSV rows | Source | Comment |",
           "|---|---|---|---|---|---|---|---|---|"]
    names = collections.defaultdict(list)
    for r in rows:
        if r["origin"] == "MPQStats.cpp":
            names[r["mpq"]["index"]].append("%s (RVA %s)" % (code_span(r["name"]), rva_text(r)))

    def meaning(v):
        if v == 0:
            return "none (0xFF rows)"
        if v <= 0xFFFF:
            return "sgptDataTable+%s" % hexs(v)
        return "VA %s = RVA %s" % (hexs(v), hexs(v - IMAGE_BASE))
    for m in ctx["mpq_rows"]:
        out.append("| %d | `%s` | %s | %s | %s | %s | %s | %s | %s |" % (
            m["index"], m["name"], hexs(m["entry"]), meaning(m["entry"]), hexs(m["max"]), meaning(m["max"]),
            "<br>".join(names[m["index"]]) or "-", link("MPQStats.cpp:%d" % m["line"]),
            code_span(md_escape(m["comment"])) or "-"))
    out.append("")
    out.append("`FillBaseStat()` call sites outside MPQStats.cpp (who can reach an absolute-VA table):\n")
    out.append("| Site | Function | JS name | Table argument | Absolute-VA table? |")
    out.append("|---|---|---|---|---|")
    seen = set()
    for f in fbs:
        key = (f["file"], f["line"], f["arg"])
        if key in seen:
            continue
        seen.add(key)
        out.append("| %s | `%s` | %s | %s | %s |" % (link("%s:%d" % (f["file"], f["line"])), f["func"],
                                                   ", ".join(code_span(j) for j in f["js"]) or "-",
                                                   code_span(md_escape(f["arg"])), f["hit"]))
    out.append("")
    return "\n".join(out)


def md_gdo_sites(ctx, rows):
    out = ["| Site | Call | VA | RVA | TSV row | Code |", "|---|---|---|---|---|---|"]
    for s in ctx["other_sites"]:
        args = s["args"]
        try:
            rva = parse_int(args[1])
            va, rv = hexs(rva + IMAGE_BASE), hexs(rva)
        except (ValueError, IndexError):
            va = rv = "?"
        out.append("| %s | `GetDllOffset(%s)` | %s | %s | %s | %s |" % (
            link("%s:%d" % (s["file"], s["line"])), md_escape(", ".join(args)), va, rv, code_span(s.get("row", "")) or "-",
            code_span(md_escape(s["text"][:110]))))
    out.append("")
    return "\n".join(out)


def md_asm(asm_hits):
    out = ["Every numeric literal inside an `__asm { }` block of the scanned sources. `addr?` is `yes` when the value "
           "is >= 0x10000 (could be an absolute address); everything else is an immediate, a stack/struct "
           "displacement or a constant.\n",
           "| Site | Function | Literal | Value | addr? | Instruction |", "|---|---|---|---|---|---|"]
    for h in asm_hits:
        out.append("| %s | `%s` | `%s` | %s | %s | %s |" % (link("%s:%d" % (h["file"], h["line"])), h["func"], h["literal"],
                                                        hexs(h["value"]), "yes" if h["address"] else "no",
                                                        code_span(md_escape(h["instr"]))))
    out.append("")
    return "\n".join(out)


def md_abs(abs_hits):
    out = ["Hex literals in `[0x400000, 0x1000000)` (1.14d Game.exe VA range) or `[0x6F000000, 0x70000000)` (1.13 DLL "
           "range) outside `D2Ptrs.h`/`Patch.h`, with the classification applied by the generator.\n",
           "| Site | Literal | Classification | Code |", "|---|---|---|---|"]
    for h in abs_hits:
        out.append("| %s | `%s` | %s | %s |" % (link("%s:%d" % (h["file"], h["line"])), h["literal"], md_escape(h["reason"]),
                                             code_span(md_escape(h["text"][:110]))))
    out.append("")
    return "\n".join(out)


def md_casts(casts):
    if not casts:
        return "No mismatching casts found.\n"
    out = ["`(T*)p_X` casts where `T*` differs from the `p_` pointer type declared by `VARPTR`. When every use of a "
           "`VARPTR` is such a cast (column *TSV type*), the generator emits the cast's pointee as the TSV type and adds "
           "`type-from-usage`.\n",
           "| Site | Pointer | Declared (`p_` type) | Cast to | TSV type | Code |", "|---|---|---|---|---|---|"]
    for c in casts:
        out.append("| %s | `%s` | `%s` | `%s` | %s | %s |" % (
            link("%s:%d" % (c["file"], c["line"])), c["ident"], c["declared"], c["cast"],
            "`%s`" % c["cast"][:-1].strip() if c.get("applied") else "declared kept",
            code_span(md_escape(c["text"][:100]))))
    out.append("")
    return "\n".join(out)


def md_suspects(rows):
    out = ["| Name | RVA | Status | Evidence (strength) | Use sites (function @ file:line) | JS / hook entry points |",
           "|---|---|---|---|---|---|"]
    mpq_done = False
    for r in rows:
        st = set(r["status"])
        if not (st & {"stale-pre-1.14d?", "va-comment-mismatch", "va-only", "ported-1.14d-unverified",
                      "dead-code-only", "captured-encoded"}):
            continue
        if r["origin"] == "MPQStats.cpp":
            if mpq_done:
                continue
            mpq_done = True
            mrows = [x for x in rows if x["origin"] == "MPQStats.cpp"]
            entry = ", ".join(code_span(j) for j in r.get("js", []))
            roots = ", ".join(sorted(r.get("roots", [])))
            out.append("| `D2COMMON_MPQ_*` (%d rows, %s) | %s .. %s | va-only | absolute 1.14 VA literals in "
                       "`BaseStatTable[]`, no version marker (weak) | GetBaseTable() via FillBaseStat() "
                       "(MPQStats.cpp) | only callers that select one of these tables; see the `FillBaseStat` "
                       "call-site table in the MPQ section |" % (
                           len(mrows), ", ".join(sorted(set(x["mpq"]["name"] for x in mrows))),
                           hexs(min(x["rva"] for x in mrows)), hexs(max(x["rva"] for x in mrows))))
            continue
        ci = r["cinfo"]
        ev = []
        strength = "weak"
        if ci["va113"] is not None or (ci["m113"] and not ci["m114d"]):
            strength = "strong"
        if "va-only" in st or ("dead-code-only" in st and "stale-pre-1.14d?" not in st):
            strength = "n/a"
        if ci["va113"] is not None and r["rva"] is not None:
            base = ci["va113"] - r["rva"]
            ev.append("1.13-style VA %s; VA-RVA = %s%s" % (hexs(ci["va113"]), hexs(base),
                                                         " (1.13 D2Client.dll base)" if base == D2_113_CLIENT_BASE else ""))
        if ci["m113"] and ci["va113"] is None:
            ev.append("comment mentions 1.12/1.13")
        if not r["comment"]:
            ev.append("no comment")
        elif not ci["m114d"] and ci["va"] is None and ci["va113"] is None:
            ev.append("comment has no version/VA")
        if ci["va"] is not None and r["rva"] is not None and ci["va"] == IMAGE_BASE + r["rva"]:
            ev.append("VA comment matches")
        if r.get("va_literal"):
            ev.append("absolute VA literal in code")
        if r.get("encoded_target") is not None:
            ev.append("JMP target is the encoded value %s, not %s" % (hexs(r["encoded_target"]), hexs(r["intended_target"])))
            strength = "strong"
        if r.get("captures"):
            ev.append("read by a file-scope initialiser while still encoded (%s)" % hexs(r["encoded"]))
            strength = "strong"   # proven from source (initialisation order), not a version guess
        if r["origin"] not in ("D2Ptrs.h", "Patch.h", "MPQStats.cpp"):
            ev.append("absolute VA literal in code")
        sites = []
        if r.get("ref"):
            for o in r["ref"]["sites"]:
                c = r_ctx_name(o)
                sites.append("%s @ %s:%d" % (c, o[1], o[2]))
        elif r["origin"] == "Patch.h":
            sites.append("installed by %s (%s)" % ("InstallPatches()" if r["kind"] == "PATCH" else
                                                   "InstallConditional() if %s" % r["patch"]["cond"], r["source"]))
        else:
            sites.append(r["source"])
        entry = ", ".join(code_span(j) for j in r.get("js", [])[:12])
        if r.get("js") and len(r["js"]) > 12:
            entry += " +%d more" % (len(r["js"]) - 12)
        roots = ", ".join(sorted(r.get("roots", [])))
        out.append("| %s | %s | %s | %s (%s) | %s | %s |" % (
            code_span(r["ident"]), rva_text(r), ", ".join(r["status"]), "; ".join(ev) or "-", strength,
            "<br>".join(md_escape(s) for s in sorted(set(sites))) or "-",
            (entry + ("<br>" if entry and roots else "") + md_escape(roots)) or "-"))
    out.append("")
    return "\n".join(out)


_MODEL = None


def r_ctx_name(o):
    c = _MODEL.ctx[o[3]]
    tag = c["name"]
    if c["kind"] != "func":
        tag = "%s[] initializer" % c["name"]
    if c["name"] not in _MODEL.live and c["kind"] == "func":
        tag += " (no live caller)"
    if o[4]:
        tag += " case %s" % o[4]
    return tag


def md_js_index(rows):
    out = ["Name-based reverse reachability from each `D2Ptrs.h` symbol to SpiderMonkey natives (`JSAPI_FUNC` / "
           "`JSAPI_PROP` definitions) and their JS names from `JS_FS`/`JS_FN`/`JSPropertySpec` tables. It "
           "over-approximates (any function sharing a name is treated as a caller); `table.name` is the spec "
           "array and the JS-visible name.\n",
           "| Symbol | # natives | JS entry points (first 10) |", "|---|---|---|"]
    for r in rows:
        if r["origin"] != "D2Ptrs.h":
            continue
        js = r.get("js", [])
        shown = ", ".join(code_span(j) for j in js[:10]) + (" +%d more" % (len(js) - 10) if len(js) > 10 else "")
        out.append("| %s | %d | %s |" % (code_span(r["ident"]), len(r.get("natives", {})), shown or "-"))
    out.append("")
    return "\n".join(out)


def md_summary(rows, counts):
    c = collections.Counter()
    for r in rows:
        c["kind:" + r["kind"]] += 1
        for s in r["status"]:
            c["status:" + s] += 1
    out = ["| Kind | Rows |", "|---|---|"]
    for k in ("FUNC", "DATA", "LABEL", "PATCH", "COND_PATCH"):
        out.append("| %s | %d |" % (k, c["kind:" + k]))
    out.append("| **total** | **%d** |" % len(rows))
    out.append("")
    out.append("| Status flag | Rows |")
    out.append("|---|---|")
    for s in ("ported-1.14d", "va-only", "ported-1.14d-unverified", "stale-pre-1.14d?", "va-comment-mismatch",
              "duplicate-address", "unused", "dead-code-only", "asm-only", "type-from-usage", "captured-encoded"):
        out.append("| `%s` | %d |" % (s, c["status:" + s]))
    out.append("")
    return "\n".join(out)


REGIONS = ["summary", "symbols", "patches", "mpq", "gdo-sites", "asm-literals", "abs-literals", "casts",
           "asm-only", "disabled", "suspects", "js-index"]


def write_markdown(path, regions):
    text = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if text and "<!-- BEGIN GENERATED:" in text:
        for name in REGIONS:
            b = "<!-- BEGIN GENERATED:%s -->" % name
            e = "<!-- END GENERATED:%s -->" % name
            if b in text and e in text:
                pre, rest = text.split(b, 1)
                _, post = rest.split(e, 1)
                text = pre + b + "\n" + regions[name].rstrip() + "\n" + e + post
    else:
        parts = ["# D2BS symbol tables (generated)\n"]
        for name in REGIONS:
            parts.append("## %s\n\n<!-- BEGIN GENERATED:%s -->\n%s\n<!-- END GENERATED:%s -->\n" % (
                name, name, regions[name].rstrip(), name))
        text = "\n".join(parts)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# --------------------------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", required=True, help="D2BS repository root")
    ap.add_argument("--out", required=True, help="TSV output path")
    ap.add_argument("--markdown", help="markdown file to (re)generate tables in")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    repo = os.path.abspath(args.repo)
    errors, warnings = [], []
    try:
        rows, ctx = build_rows(repo, errors, warnings)
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    mark_duplicates(rows)

    global _MODEL
    model = CodeModel(repo, list_sources(repo))
    model.build()
    _MODEL = model
    js_funcs, js_props = js_name_tables(model)
    casts = p_casts(model, rows)
    apply_usage_types(rows, model, casts)
    mark_static_captures(rows, model, ctx["dllno"])
    analyse_references(rows, model, js_funcs, js_props)
    for r in rows:
        if r["origin"] == "MPQStats.cpp":
            r["natives"], r["roots"] = model.reverse_entrypoints(["BaseStatTable"])
            r["js"] = js_names_for(r["natives"], js_funcs, js_props)
        elif r["origin"] not in ("D2Ptrs.h", "Patch.h"):
            fn = enclosing(model, r["site"]["file"], r["site"]["line"])
            r["natives"], r["roots"] = model.reverse_entrypoints([fn])
            if model.ctx and any(c["native"] and c["name"] == fn for c in model.ctx):
                r["natives"].setdefault(fn, set())
                case = [o[4] for o in model.by_ident.get("GetDllOffset", []) if o[1] == r["site"]["file"]
                        and o[2] == r["site"]["line"] and o[4]]
                r["natives"][fn] |= set(case)
            r["js"] = js_names_for(r["natives"], js_funcs, js_props)

    # ---------------- validation ----------------
    fail = False
    gc = grep_counts(repo)
    d2 = [r for r in rows if r["origin"] == "D2Ptrs.h"]
    checks = [
        ("D2Ptrs.h FUNCPTR -> FUNC", sum(1 for r in d2 if r["macro"] == "FUNCPTR" and r["kind"] == "FUNC"), gc["FUNCPTR"]),
        ("D2Ptrs.h VARPTR -> DATA", sum(1 for r in d2 if r["macro"] == "VARPTR" and r["kind"] == "DATA"), gc["VARPTR"]),
        ("D2Ptrs.h ASMPTR -> LABEL+DATA", sum(1 for r in d2 if r["macro"] == "ASMPTR"), gc["ASMPTR"]),
        ("Patch.h Patches[] -> PATCH", sum(1 for r in rows if r["kind"] == "PATCH"), gc["patch:Patches"]),
        ("Patch.h Conditional[] -> COND_PATCH", sum(1 for r in rows if r["kind"] == "COND_PATCH"), gc["patch:Conditional"]),
        ("MPQStats.cpp absolute VAs -> DATA", sum(1 for r in rows if r["origin"] == "MPQStats.cpp"), gc["mpq_abs"]),
    ]
    va_checked = va_ok = 0
    mism = []
    for r in rows:
        if r["cinfo"]["va"] is not None and r["rva"] is not None:
            va_checked += 1
            if r["cinfo"]["va"] == IMAGE_BASE + r["rva"]:
                va_ok += 1
            else:
                mism.append(r)
    names = collections.Counter(r["name"] for r in rows)
    dup_names = [n for n, k in names.items() if k > 1]
    bad_names = [r["name"] for r in rows if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", r["name"])]
    mods_bad = [r["name"] for r in rows if r["module"] not in KNOWN_MODULES]
    ordinals = [r for r in rows if r["ordinal"] is not None]
    too_big = [r for r in d2 if r["rva"] is not None and r["rva"] > DLLOFFSET_MAX]
    # Offset.cpp dll table vs enum
    off = Source(repo, "Offset.cpp")
    m = re.search(r"dlls\[\]\s*=\s*\{([^}]*)\}", off.code)
    dll_names = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    g = re.search(r"\(num\s*&\s*0xff\)\s*>\s*(\d+)", off.code)
    guard = int(g.group(1)) if g else None
    enum_ok = [d.upper().replace(".DLL", "") for d in dll_names] == ctx["dllno"]
    abs_hits = absolute_literal_sweep(model, collections.defaultdict(list, {
        r["source"]: [x["name"] for x in rows if x["source"] == r["source"]] for r in rows}))
    unclassified = [h for h in abs_hits if h["reason"] == "UNCLASSIFIED"]
    asm_hits = asm_literal_sweep(model)
    asm_addr = [h for h in asm_hits if h["address"]]

    lines = ["gen_symbols.py summary", "  rows: %d" % len(rows)]
    for k in ("FUNC", "DATA", "LABEL", "PATCH", "COND_PATCH"):
        lines.append("    %-10s %d" % (k, sum(1 for r in rows if r["kind"] == k)))
    for label, got, want in checks:
        ok = got == want
        fail |= not ok
        lines.append("  [%s] %-38s parsed=%d grep=%d" % ("ok" if ok else "FAIL", label, got, want))
    lines.append("  [%s] VA comments checked=%d match=%d mismatch=%d" % ("ok" if not mism else "WARN", va_checked, va_ok, len(mism)))
    for r in mism:
        lines.append("        mismatch %s rva=%s comment-va=%s (%s)" % (r["name"], rva_text(r), hexs(r["cinfo"]["va"]), r["source"]))
    lines.append("  [%s] unique names (%d duplicates)" % ("ok" if not dup_names else "FAIL", len(dup_names)))
    lines.append("  [%s] valid Ghidra labels (%d bad)" % ("ok" if not bad_names else "FAIL", len(bad_names)))
    lines.append("  [%s] module tokens (%d unknown)" % ("ok" if not mods_bad else "FAIL", len(mods_bad)))
    lines.append("  [%s] DLLNO enum matches Offset.cpp dlls[] (%d entries, guard > %s)" % (
        "ok" if enum_ok and guard == len(dll_names) - 1 else "FAIL", len(dll_names), guard))
    lines.append("  [info] ordinal (negative-offset) entries: %d" % len(ordinals))
    lines.append("  [%s] all D2Ptrs.h offsets <= 0x%X (DLLOFFSET encoding limit)" % ("ok" if not too_big else "FAIL", DLLOFFSET_MAX))
    lines.append("  [%s] absolute-VA literal sweep: %d hits, %d unclassified" % ("ok" if not unclassified else "WARN", len(abs_hits), len(unclassified)))
    lines.append("  [info] __asm numeric literals: %d (>= 0x10000: %d)" % (len(asm_hits), len(asm_addr)))
    st = collections.Counter(s for r in rows for s in r["status"])
    lines.append("  status: " + ", ".join("%s=%d" % kv for kv in sorted(st.items())))
    for w in warnings:
        lines.append("  warning: " + w)
    for e in errors:
        lines.append("  ERROR: " + e)
    fail |= bool(errors) or bool(dup_names) or bool(bad_names) or bool(mods_bad) or bool(too_big) or not enum_ok
    write_tsv(args.out, rows)
    with open(args.out, "rb") as fh:
        raw = fh.read()
    tsv_lines = raw.decode("utf-8").split("\n")
    tsv_ok = (b"\r" not in raw and tsv_lines[-1] == "" and tsv_lines[0].split("\t") == TSV_HEADER
              and all(len(l.split("\t")) == len(TSV_HEADER) for l in tsv_lines[1:-1])
              and len(tsv_lines) - 2 == len(rows))
    fail |= not tsv_ok
    lines.append("  [%s] TSV re-read: %d data rows x %d columns, LF only" % ("ok" if tsv_ok else "FAIL",
                                                                         len(tsv_lines) - 2, len(TSV_HEADER)))
    lines.append("  wrote %s" % args.out)
    if args.markdown:
        regions = {
            "summary": md_summary(rows, gc),
            "symbols": md_symbols(rows),
            "patches": md_patches(rows),
            "mpq": md_mpq(ctx, rows, fillbasestat_sites(model, ctx, js_funcs)),
            "gdo-sites": md_gdo_sites(ctx, rows),
            "asm-literals": md_asm(asm_hits),
            "abs-literals": md_abs(abs_hits),
            "casts": md_casts(casts),
            "asm-only": md_asm_only(rows, model),
            "disabled": md_disabled(ctx),
            "suspects": md_suspects(rows),
            "js-index": md_js_index(rows),
        }
        write_markdown(args.markdown, regions)
        lines.append("  wrote %s" % args.markdown)
    if not args.quiet or fail:
        print("\n".join(lines))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

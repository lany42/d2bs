#!/usr/bin/env python3
"""jsapi_inventory.py -- mechanical inventory of SpiderMonkey (JSAPI) coupling in D2BS.

Scans the D2BS C++ sources (repo root *.cpp/*.h and Map/**; sqlite3.*, StackWalker.*,
dependencies/ and doc/ are excluded) and prints GitHub-flavoured Markdown tables that are
pasted verbatim into docs/spidermonkey/jsapi-inventory.md.

Python 3 standard library only.

Usage
    python3 docs/spidermonkey/tools/jsapi_inventory.py [--repo DIR] [--section NAME ...]
    python3 docs/spidermonkey/tools/jsapi_inventory.py --list-sections
    python3 docs/spidermonkey/tools/jsapi_inventory.py --update docs/spidermonkey/jsapi-inventory.md

    --repo DIR      repository root (default: three levels above this file)
    --section NAME  emit only the named section(s); default: all, in canonical order
    --update DOC    regenerate, in place, every block of DOC delimited by
                    "<!-- jsapi_inventory.py --section NAME -->" ... "<!-- /jsapi_inventory.py -->"

Method (deliberately simple and reproducible)
  * Comments, string literals and `#if 0` blocks are blanked (line numbers preserved);
    `#include` lines are ignored. Counts therefore cover live code only.
  * A "JSAPI symbol" is an identifier matching the SpiderMonkey naming patterns
    (JS*, js*, *_TO_JSVAL, JS::*) that is either declared under dependencies/include
    (as a function, macro, type, enum constant or extern const -- a bare mention does
    not count) or defined by the D2BS wrapper files js32.h / js32.cpp / AutoRoot.h /
    AutoRoot.cpp (names listed in WRAPPER_DESC). Plain local variable names such as
    `jsunit` are therefore not counted.
  * C++ member calls on SpiderMonkey types (vp.setInt32(), buf->write(cx, ..),
    opts.setUTF8()) are counted by regex as pseudo-symbols (MEMBER_CALLS).
  * "refs" = number of token occurrences; definitions inside the wrapper files count too.
  * Native bodies are found by brace matching after JSAPI_FUNC/JSAPI_PROP/
    JSAPI_STRICT_PROP/CLASS_CTOR and finalizer signatures.
  * "logic lines" = non-blank body lines that contain no JSAPI symbol and are not just
    braces / `return JS_TRUE;` -- a rough proxy for embedded non-binding logic.
  * Signatures are matched at namespace/class scope after blanking preprocessor directives
    (including backslash continuations); constructors, destructors and operators count.
  * Leak scans (locks, stack roots) walk the statements after the acquire block by block and
    report every return/throw reached before the release; they are not path-sensitive.
  * "Unset return value" = a JSAPI_FUNC body without JS_SET_RVAL/THROW_WARNING, or a
    `return JS_TRUE` textually before the first one (a lower bound).
"""

import argparse
import collections
import glob
import os
import re
import sys

# --------------------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------------------

EXCLUDE_BASENAMES = {"sqlite3.c", "sqlite3.h", "StackWalker.cpp", "StackWalker.h"}
WRAPPER_FILES = ["js32.h", "js32.cpp", "AutoRoot.h", "AutoRoot.cpp"]
BUILD_FILES = ["D2BS.vcxproj", "D2BS.vcxproj.filters", "D2BS.sln", "build.bat",
               "Release/Build Instructions.txt"]

SECTIONS = ["summary", "symbols", "wrappers", "typedefs", "files", "mixed", "members",
            "natives", "locks", "strings", "clone", "roots", "build", "deps"]

# per-file classification (manual, verified against source; see jsapi-inventory.md §2)
#   a = pure binding layer      b = engine core
#   c = mixed (game/infra logic intertwined with JS types)   d = JS-free game/infra code
# A trailing note is printed in the table. The script warns when a "d" file has refs.
CLASSIFICATION = {
    # binding layer (natives + spec tables)
    "JSArea.cpp": "a", "JSArea.h": "a", "JSControl.cpp": "a", "JSControl.h": "a",
    "JSCore.cpp": "a", "JSCore.h": "a", "JSDirectory.cpp": "a", "JSDirectory.h": "a",
    "JSExits.cpp": "a", "JSExits.h": "a", "JSFile.cpp": "a", "JSFile.h": "a",
    "JSFileTools.cpp": "a", "JSFileTools.h": "a", "JSGame.cpp": "a", "JSGame.h": "a",
    "JSGlobalClasses.cpp": "a", "JSGlobalClasses.h": "a", "JSGlobalFuncs.h": "a",
    "JSHash.cpp": "a", "JSHash.h": "a", "JSMenu.cpp": "a", "JSMenu.h": "a",
    "JSParty.cpp": "a", "JSParty.h": "a", "JSPresetUnit.cpp": "a", "JSPresetUnit.h": "a",
    "JSProfile.cpp": "a", "JSProfile.h": "a", "JSRoom.cpp": "a", "JSRoom.h": "a",
    "JSSQLite.cpp": "a", "JSSQLite.h": "a", "JSSandbox.cpp": "a", "JSSandbox.h": "a",
    "JSScreenHook.cpp": "a", "JSScreenHook.h": "a", "JSScript.cpp": "a", "JSScript.h": "a",
    "JSSocket.cpp": "a", "JSSocket.h": "a", "JSUnit.cpp": "a", "JSUnit.h": "a",
    "Map/Path/Reduction/JSPathReducer.h": "a",
    # engine core
    "js32.h": "b", "js32.cpp": "b", "AutoRoot.h": "b", "AutoRoot.cpp": "b",
    "Script.h": "b", "Script.cpp": "b", "ScriptEngine.h": "b", "ScriptEngine.cpp": "b",
    # mixed
    "Events.h": "c", "Events.cpp": "c", "File.h": "c", "File.cpp": "c",
    "MPQStats.h": "c", "MPQStats.cpp": "c", "D2Helpers.h": "c", "D2Helpers.cpp": "c",
    "ScreenHook.h": "c", "ScreenHook.cpp": "c", "Profile.h": "c",
    # everything else defaults to "d"; engine clients are flagged by the "engine API" column
}

NOTES = {
    "js32.h": "jsapi.h/jsfriendapi.h entry point; wrapper macros; generic typedefs (uint, uint32, ...)",
    "js32.cpp": "BuildObject, JS_CompileFile, JS_Get/SetPrivate(cx,..) shims",
    "AutoRoot.h": "AutoRoot class (rooted jsval holder)",
    "AutoRoot.cpp": "AutoRoot impl; default cx = ScriptEngine::GetGlobalContext() (always NULL)",
    "Script.h": "Script class + Event struct (holds JSContext/JSRuntime/JSScript/AutoRoot/clone buffers)",
    "Script.cpp": "per-script runtime/context, compile/run main(), include, listener registry",
    "ScriptEngine.h": "engine facade; ScriptEngine::runtime/context statics (never assigned)",
    "ScriptEngine.cpp": "context callback (globals/classes/me), operation callback, ExecScriptEvent dispatch, timers",
    "Events.h": "ScriptBroadcastEvent(JSContext*, uint, jsval*); BCastEventHelper",
    "Events.cpp": "game->script event fan-out; scriptmsg structured clone",
    "File.h": "writeValue(.., JSContext*, jsval, ..), fileOpenRelScript(.., JSContext*)",
    "File.cpp": "jsval serialisation + JS_ReportError inside file helpers",
    "MPQStats.h": "FillBaseStat(JSContext*, jsval*, ..) overload; includes js32.h",
    "MPQStats.cpp": "FillBaseStat writes jsval results",
    "D2Helpers.h": "SetSkill(JSContext*, ..); includes js32.h",
    "D2Helpers.cpp": "SetSkill pumps the calling script's event queue via JS_GetContextPrivate",
    "ScreenHook.h": "Genhook stores JSObject* self + jsval clicked/hovered",
    "ScreenHook.cpp": "hook click/hover dispatch builds AutoRoot + Event",
    "Profile.h": "`friend JSAPI_PROP(profile_getProperty)` inside class Profile",
    "Helpers.h": "engine client: includes Script.h (-> js32.h); declares StartScript(.., ScriptState)",
    "Helpers.cpp": "engine client: StartScript -> ScriptEngine::CompileFile; Startup/RunCommand/StopAll/FlushCache/GetCount",
    "D2Handlers.cpp": "engine client: game-thread loop, input/packet hooks fire Events.h functions, Genhook click/draw",
    "D2NetHandlers.cpp": "engine client: packet handlers fire Events.h functions",
    "Console.cpp": "includes ScriptEngine.h only; commands go through Helpers.cpp ProcessCommand",
    "D2BS.cpp": "engine client: Genhook::Initialize/Destroy (ScriptEngine via Helpers/D2Handlers)",
    "D2BS.h": "defines XP_WIN (SpiderMonkey platform macro); includes ScreenHook.h -> Script.h -> js32.h",
    "dde.cpp": "engine client: DDE execute -> ScriptEngine::RunCommand",
    "CriticalSections.h": "AutoCriticalRoom = Vars.cGameLoopSection (taken by natives)",
    "Map/Path/Reduction/JSPathReducer.h": "path reducer calling JS callbacks (reject/reduce/mutate)",
}

# SpiderMonkey symbol category rules (first match wins)
CATEGORY_RULES = [
    ("structured clone", r"StructuredClone"),
    ("debugging", r"^(NUM|NAME|JS_SetGCZeal|JS_DumpHeap|JS_GetScriptedCaller)$"),
    ("errors/exceptions", r"^(JS_(Report\w*|SetPendingException|ClearPendingException|IsExceptionPending|"
                          r"GetPendingException|SetErrorReporter|ThrowError)|JSREPORT_\w+|JSErrorReport|"
                          r"JSErrorReporter|THROW_ERROR|THROW_WARNING)$"),
    ("strings/encoding", r"^(JS_(Encode\w*|NewStringCopy\w*|NewUCString\w*|GetString\w*|Intern\w*|"
                         r"NewString\w*|free|strdup|malloc)|JSString|JSFlatString|jschar)$"),
    ("GC/rooting", r"(Root|^JS_(GC|MaybeGC|SetGCParameter|GetGCParameter|SetGCCallback)$|^JSGC\w*$|"
                   r"^JS::(Rooted\w*|Handle\w*|MutableHandle\w*)$|^JSHandle\w+$|^JSMutableHandle\w+$|"
                   r"LocalRootScope)"),
    ("runtime/context/threads", r"^(JS_(NewRuntime|DestroyRuntime|NewContext|DestroyContext|ShutDown|"
                                r"BeginRequest|EndRequest|SuspendRequest|ResumeRequest|IsInRequest|"
                                r"SetContextPrivate|GetContextPrivate|SetContextCallback|SetOperationCallback|"
                                r"TriggerOperationCallback|SetOptions|GetOptions|ToggleOptions|SetVersion|"
                                r"SetNativeStackQuota|GetRuntime|SetRuntimeThread|ClearRuntimeThread|"
                                r"SetContextThread|ClearContextThread|GetGlobalObject|NewGlobalObject|"
                                r"InitStandardClasses|IsRunning|NO_HELPER_THREADS)|JSOPTION_\w+|JSVERSION_\w+|"
                                r"JSCONTEXT_\w+|JSRuntime|JSContext|JSAutoRequest|JSContextCallback|"
                                r"JSOperationCallback)$"),
    ("compile/execute", r"^(JS_(Compile\w*|Execute\w*|Evaluate\w*|BufferIsCompilableUnit|DestroyScript|"
                        r"ClearScope)|JS::Compile\w*|JSScript)$"),
    ("classes", r"^(JSCLASS_\w+|JSClass|JS_(InitClass|PropertyStub|StrictPropertyStub|EnumerateStub|"
                r"ResolveStub|ConvertStub|FinalizeStub|InstanceOf|GetInstancePrivate|GetPrivate|SetPrivate|"
                r"GetReservedSlot|SetReservedSlot|New|ConstructObject|GET_CLASS|DefineClasses|"
                r"GetProtoForClass|NewObjectWithProto|CS|CS_END|MS|MS_END)|JSFreeOp|JSFinalizeOp|"
                r"JSPropertyOp|JSStrictPropertyOp|JSClassSpec|JSModuleSpec|CLASS_CTOR|EMPTY_CTOR|"
                r"JSExtendedClass|BuildObject|PRIVATE_TO_JSVAL|JSVAL_TO_PRIVATE)$"),
    ("functions/natives", r"^(JS_(ARGV|RVAL|SET_RVAL|THIS|THIS_OBJECT|CALLEE|FN|FS|FS_END|CallFunction\w*|"
                          r"DefineFunction\w*|ObjectIsFunction|GetFunctionObject|NewFunction)|JSFUN_\w+|"
                          r"JSFunction|JSFunctionSpec|JSNative|JSAPI_\w+|FUNCTION_FLAGS|JSVAL_IS_FUNCTION|"
                          r"JS::CallArgs\w*)$"),
    ("objects/properties", r"^(JS_(NewObject|GetProperty|SetProperty|DefineProperty|DefineProperties|"
                           r"LookupProperty|HasProperty|DeleteProperty|GetElement|SetElement|NewArrayObject|"
                           r"GetArrayLength|IsArrayObject|NewUint8Array|NewUint16Array|IsArrayBufferObject|"
                           r"GetArrayBuffer\w*|PS|PS_END|PSG\w*)|JSPROP_\w+|JSPropertySpec|JSObject|"
                           r"JSOP_WRAPPER|JSOP_NULLWRAPPER|JSRESOLVE_\w+|JSITER_\w+)$"),
    ("values/conversion", r"^(JSVAL_\w+|\w+_TO_JSVAL|JS_(ValueTo\w+|NumberValue|NewNumberValue|ConvertValue|"
                          r"ConvertArguments|TypeOfValue|IdToValue|TRUE|FALSE|ArrayToVector|VectorToArray)|"
                          r"JSTYPE_\w+|JSID_\w+|jsval|jsid|JSBool|JSType|JS::Value|jsint|jsuint|jsdouble|"
                          r"jsrefcount|Converter)$"),
]

# short description of every D2BS wrapper defined in js32.h / js32.cpp / AutoRoot.*
WRAPPER_DESC = {
    "NUM": "stringize helper for NAME",
    "NAME": "builds \"file:line -> var\" root names",
    "JS_AddValueRoot": "macro -> JS_AddNamedValueRoot(cx, vp, NAME(..)) (shadows jsapi function)",
    "JS_AddStringRoot": "macro -> JS_AddNamedStringRoot (shadows jsapi)",
    "JS_AddObjectRoot": "macro -> JS_AddNamedObjectRoot (shadows jsapi)",
    "JS_AddGCThingRoot": "macro -> JS_AddNamedGCThingRoot (not declared by SpiderMonkey 22 headers)",
    "JS_GetPrivate": "overload JS_GetPrivate(cx, obj) -> JS_GetPrivate(obj)",
    "JS_SetPrivate": "overload JS_SetPrivate(cx, obj, p) -> JS_SetPrivate(obj, p)",
    "JSVAL_IS_OBJECT": "function re-creating the removed macro as !JSVAL_IS_PRIMITIVE(v); false for null (null is primitive in SM22, dependencies/include/js/Value.h:196, :460)",
    "JSClassSpec": "class registration row {classp, proto, ctor, argc, methods, props, static methods, static props}",
    "JSModuleSpec": "module row {name, classes, static methods, static props}",
    "JSAutoRoot": "RAII rooted jsval (heap jsval + JS_AddValueRoot)",
    "JS_AddRoot": "macro -> JS_AddObjectRoot(cx, (JSObject**)vp) -- also used on jsval slots",
    "JS_RemoveRoot": "macro -> JS_RemoveObjectRoot(cx, (JSObject**)vp); (note trailing ';')",
    "JSVAL_IS_FUNCTION": "macro: !JSVAL_IS_PRIMITIVE(v) && JS_ObjectIsFunction(cx, obj)",
    "JSPROP_PERMANENT_VAR": "JSPROP_READONLY|JSPROP_ENUMERATE|JSPROP_PERMANENT",
    "JSPROP_STATIC_VAR": "JSPROP_ENUMERATE|JSPROP_PERMANENT",
    "CLASS_CTOR": "declares JSBool name_ctor(JSContext*, uint, jsval*)",
    "BuildObject": "JS_NewObject + JS_DefineFunctions/Properties + JS_SetPrivate inside a request",
    "JS_CompileFile": "reads file, strips UTF-8 BOM, JS::Compile with UTF-8 option (name mimics removed jsapi)",
    "THROW_ERROR": "JS_ReportError(cx, msg); return JS_FALSE;",
    "THROW_WARNING": "JS_ReportWarning; rval = false; return JS_TRUE;",
    "JS_DefineClasses": "EXPORT declaration only -- never defined",
    "JS_GetProtoForClass": "EXPORT declaration only -- never defined",
    "JS_NewObjectWithProto": "EXPORT declaration only -- never defined",
    "JSPROP_DEFAULT": "JSPROP_ENUMERATE|JSPROP_PERMANENT (unparenthesised)",
    "JSPROP_STATIC": "JSPROP_ENUMERATE|JSPROP_PERMANENT|JSPROP_READONLY (unparenthesised)",
    "JSAPI_FUNC": "JSBool name(JSContext* cx, uint argc, jsval* vp) -- JSNative signature",
    "FUNCTION_FLAGS": "JSFUN_STUB_GSOPS",
    "EMPTY_CTOR": "ctor that throws \"Invalid Operation\"",
    "JSAPI_PROP": "JSBool name(cx, JSHandleObject, JSHandleId, JSMutableHandleValue) -- JSPropertyOp",
    "JSAPI_STRICT_PROP": "as JSAPI_PROP plus JSBool strict -- JSStrictPropertyOp",
    "JS_PS": "{name, id, flags, getter, setter} initializer; unused (live tables write JSOP_WRAPPER(...) rows directly)",
    "JS_PS_END": "JS_PS(0,0,0,0,0)",
    "JS_CS": "JSClassSpec initializer",
    "JS_CS_END": "{0}",
    "JS_MS": "JSModuleSpec initializer",
    "JS_MS_END": "{0,0,0,0}",
    "JSCLASS_SPEC": "fills JSClass hooks add..finalize, NULL checkAccess/call/hasInstance, ctor as construct, NULL trace",
    "JSCLASS_DEFAULT_WITH_CTOR": "JSCLASS_SPEC with stubs (references JS_FinalizeStub, absent in SM22)",
    "JSCLASS_DEFAULT_STANDARD_MEMBERS": "stub members (references JS_FinalizeStub, absent in SM22)",
    "Converter": "template jsval<->C++ converters for JS_ArrayToVector/JS_VectorToArray",
    "JS_ArrayToVector": "JS array -> std::vector<T>",
    "JS_VectorToArray": "std::vector<T> -> JS array",
    "AutoRoot": "ref-counted rooted jsval holder (Take/Release); stored in listener lists",
    "EXPORT": "__declspec(dllexport) when EXPORTING",
    "jsrefcount": "typedef unsigned int (legacy JSAPI type)",
    "jsdouble": "typedef double (legacy JSAPI type)",
    "jsint": "typedef int32_t (legacy JSAPI type)",
    "jsuint": "typedef uint32_t (legacy JSAPI type)",
}

GENERIC_TYPEDEFS = ["uint", "uint32", "int32", "uint16"]

# member functions of SpiderMonkey C++ types, invisible to the identifier scan
#   pseudo-symbol -> (regex, category, declared-in)
MEMBER_CALLS = {
    "JS::MutableHandleValue::set*/get": (r"\bvp\s*\.\s*(?:set\w*|get)\s*\(", "values/conversion", "js/RootingAPI.h, js/Value.h (MutableValueOperations)"),
    "JS::MutableHandleValue::is*/to*": (r"\bvp\s*\.\s*(?:is|to)\w+\s*\(", "values/conversion", "js/Value.h (ValueOperations)"),
    "JSAutoStructuredCloneBuffer::write": (r"->\s*write\s*\(\s*(?:cx|helper->cx)\b", "structured clone", "jsapi.h (class JSAutoStructuredCloneBuffer)"),
    "JSAutoStructuredCloneBuffer::read": (r"->\s*read\s*\(\s*(?:cx|context)\b", "structured clone", "jsapi.h (class JSAutoStructuredCloneBuffer)"),
    "JSAutoStructuredCloneBuffer::clear": (r"argv\[\w+\]\s*->\s*clear\s*\(", "structured clone", "jsapi.h (class JSAutoStructuredCloneBuffer)"),
    "JS::CompileOptions::setUTF8/setFileAndLine": (r"\.\s*set(?:UTF8|FileAndLine)\s*\(", "compile/execute", "jsapi.h (struct CompileOptions)"),
}

# calls whose arity tells which overload is used (SpiderMonkey vs D2BS shim)
ARITY_SPLIT = {"JS_GetPrivate": {1: "SpiderMonkey JS_GetPrivate(obj)", 2: "D2BS shim JS_GetPrivate(cx, obj)"},
               "JS_SetPrivate": {2: "SpiderMonkey JS_SetPrivate(obj, p)", 3: "D2BS shim JS_SetPrivate(cx, obj, p)"}}

# engine-layer (non-JSAPI) entry points used by game/infra code
ENGINE_API = (r"\bScriptEngine::\w+|\bScript\s*\*|\bGenhook::\w+|\b(?:ChatEvent|ChatInputEvent|LifeEvent|ManaEvent|"
              r"CopyDataEvent|GameActionEvent|WhisperEvent|KeyDownUpEvent|PlayerAssignEvent|MouseClickEvent|MouseMoveEvent|"
              r"ScriptBroadcastEvent|ItemActionEvent|GamePacketEvent|GamePacketSentEvent|RealmPacketEvent|ReleaseGameLock|"
              r"TakeGameLock|StartScript|ExecScriptEvent|StopIngameScript)\s*\(")

# JS "state" types: a C++ object holding one of these keeps live engine state
STATE_TYPES = r"\b(jsval|JS::Value|JSObject|JSContext|JSRuntime|JSScript|JSString|JSFunction|AutoRoot|JSAutoRoot|" \
              r"FunctionList|FunctionMap|JSAutoStructuredCloneBuffer)\b"
# types that indicate a JS-typed signature
SIG_TYPES = r"\b(jsval|jsid|JS::\w+|JSObject|JSContext|JSRuntime|JSScript|JSString|JSFunction|JSBool|JSFreeOp|" \
            r"JSClass|JSHandle\w+|JSMutableHandle\w+|JSErrorReport|JSAutoStructuredCloneBuffer|AutoRoot|JSGCStatus|" \
            r"JSGCCallback|jschar)\b"

ENCODING_FUNCS = ["JS_EncodeStringToUTF8", "JS_EncodeString", "JS_EncodeStringToBuffer", "JS_GetStringCharsZ",
                  "JS_NewStringCopyZ", "JS_NewUCStringCopyZ", "JS_NewUCStringCopyN", "JS_InternString",
                  "JS_InternUCString", "JS_free"]

ROOT_ADD = ["JS_AddRoot", "JS_AddValueRoot", "JS_AddObjectRoot", "JS_AddStringRoot", "JS_AddNamedValueRoot",
            "JS_AddNamedObjectRoot", "JS_AddNamedStringRoot", "JS_AddNamedScriptRoot", "JS_AddGCThingRoot",
            "JS_AddNamedGCThingRoot"]
ROOT_REMOVE = ["JS_RemoveRoot", "JS_RemoveValueRoot", "JS_RemoveObjectRoot", "JS_RemoveStringRoot",
               "JS_RemoveScriptRoot", "JS_RemoveGCThingRoot"]

CONTROL_KEYWORDS = {"if", "while", "for", "switch", "return", "sizeof", "catch", "else", "do", "case",
                    "new", "delete", "throw", "__try", "__except", "defined"}

# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def read(path):
    with open(path, encoding="latin-1") as fh:
        return fh.read()


def strip_code(src, keep_strings=False):
    """Blank comments (and string literals unless keep_strings), #if 0 blocks and #include
    lines, preserving every newline so offsets map to the same line numbers."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                j += 1
            j = min(j + 1, n)
            if keep_strings or c == "'":
                out.append(src[i:j])
            else:
                out.append(c + " " * max(0, j - i - 2) + (c if j - i >= 2 else ""))
            i = j
            continue
        out.append(c)
        i += 1
    lines = "".join(out).split("\n")
    res, skipping = [], 0
    for ln in lines:
        t = ln.strip()
        if skipping:
            if re.match(r"#\s*if", t):
                skipping += 1
            elif re.match(r"#\s*endif", t):
                skipping -= 1
            elif re.match(r"#\s*(else|elif)", t) and skipping == 1:
                skipping = 0
            res.append(" " * len(ln))
            continue
        if re.match(r"#\s*if\s+0\b", t):
            skipping = 1
            res.append(" " * len(ln))
            continue
        if re.match(r"#\s*include\b", t):
            res.append(" " * len(ln))
            continue
        res.append(ln)
    return "\n".join(res)


def blank_pp(text):
    """Blank every preprocessor directive including its backslash-continued lines (newlines
    kept), so that braces and parentheses inside macro bodies do not disturb scope scanning."""
    out, cont = [], False
    for ln in text.split("\n"):
        if cont or ln.lstrip().startswith("#"):
            cont = ln.rstrip().endswith("\\")
            out.append(" " * len(ln))
        else:
            out.append(ln)
    return "\n".join(out)


def line_of(text, off):
    return text.count("\n", 0, off) + 1


def md_escape(s):
    return s.replace("|", "\\|")


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(md_escape(str(x)) for x in r) + " |")
    return "\n".join(out)


def match_brace(text, open_off):
    depth = 0
    for k in range(open_off, len(text)):
        ch = text[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return k
    return len(text) - 1


TOKEN_RE = re.compile(r"\bJS::\w+|\bjs::\w+|\b[A-Za-z_]\w*\b")
CANDIDATE_RE = re.compile(r"^(JS::\w+|js::\w+|JS\w*|js[a-z]\w*|[A-Z_]+_TO_JSVAL|AutoRoot|BuildObject|"
                          r"THROW_ERROR|THROW_WARNING|CLASS_CTOR|EMPTY_CTOR|FUNCTION_FLAGS|Converter|NUM|NAME|EXPORT)$")


class Repo:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.files = self._collect()
        self.raw = {f: read(os.path.join(self.root, f)) for f in self.files}
        self.code = {f: strip_code(self.raw[f]) for f in self.files}
        self.code_s = {f: strip_code(self.raw[f], keep_strings=True) for f in self.files}
        self.header_decl = self._scan_headers()
        self.wrapper_defs = self._scan_wrappers()
        self.symbols = self._classify_symbols()
        self.refs = self._count_refs()
        self.member_calls = self._count_member_calls()
        self.classes = class_names(self.code.values())

    # ---- file collection ------------------------------------------------------------
    def _collect(self):
        fs = []
        for pat in ("*.cpp", "*.h", "Map/**/*.cpp", "Map/**/*.h"):
            for p in glob.glob(os.path.join(self.root, pat), recursive=True):
                rel = os.path.relpath(p, self.root).replace(os.sep, "/")
                if os.path.basename(rel) in EXCLUDE_BASENAMES:
                    continue
                fs.append(rel)
        return sorted(set(fs), key=lambda s: (s.count("/"), s.lower()))

    # ---- SpiderMonkey header declarations -------------------------------------------
    def _scan_headers(self):
        """Map identifier -> (header, line, kind). Higher-priority patterns win over a mere
        mention; within one pattern the first header (sorted path) wins."""
        decl = {}
        inc = os.path.join(self.root, "dependencies", "include")
        paths = sorted(glob.glob(os.path.join(inc, "**", "*.h"), recursive=True))
        texts = [(os.path.relpath(p, self.root).replace(os.sep, "/"), strip_code(read(p))) for p in paths]
        passes = [
            (r"JS_(?:PUBLIC|FRIEND)_API\s*\([^)]*\)\s*\n?\s*(\w+)\s*\(", "function"),
            (r"JS_(?:PUBLIC|FRIEND)_DATA\s*\([^)]*\)\s*(\w+)\s*;", "extern const"),
            (r"#\s*define\s+(\w+)", "macro"),
            (r"\b(?:class|struct)\s+JS_PUBLIC_API\s*\(\s*(\w+)\s*\)", "type"),
            (r"\b(?:struct|class|union)\s+(\w+)\s*(?:[:{]|MOZ_FINAL)", "type"),
            (r"\btypedef\b[^;]*?\(\s*\*\s*(\w+)\s*\)", "type (fn ptr)"),
            (r"\btypedef\b[^;]*?\b(\w+)\s*(?:\[[^\]]*\])?\s*;", "type"),
            (r"\b(?:static\s+)?(?:JS_ALWAYS_INLINE|inline|MOZ_ALWAYS_INLINE)\b[^;{(]*?\b(\w+)\s*\(", "inline function"),
        ]
        for pat, kind in passes:
            rx = re.compile(pat)
            for rel, txt in texts:
                for m in rx.finditer(txt):
                    decl.setdefault(m.group(1), (rel, line_of(txt, m.start(1)), kind))
        # enum constants
        for rel, txt in texts:
            for em in re.finditer(r"\benum\b[^{;]*\{([^}]*)\}", txt):
                base = em.start(1)
                for cm in re.finditer(r"(?:^|,)\s*([A-Za-z_]\w*)\s*(?==|,|$)", em.group(1)):
                    decl.setdefault(cm.group(1), (rel, line_of(txt, base + cm.start(1)), "enum constant"))
        # anything else that merely appears in the headers
        for rel, txt in texts:
            for m in TOKEN_RE.finditer(txt):
                if m.group().startswith(("JS::", "js::")):
                    continue
                decl.setdefault(m.group(), (rel, line_of(txt, m.start()), "identifier"))
        return decl

    # ---- D2BS wrapper definitions ---------------------------------------------------
    def _scan_wrappers(self):
        defs = {}
        for f in WRAPPER_FILES:
            if f not in self.code:
                continue
            txt = self.code[f]
            pats = [
                (r"#\s*define\s+(\w+)", "macro"),
                (r"\b(?:struct|class)\s+(\w+)\s*[{:]", "type"),
                (r"\btypedef\b[^;]*?\b(\w+)\s*;", "typedef"),
                (r"template\s*<[^>]*>\s*(?:struct|class)\s+(\w+)", "template type"),
                (r"template\s*<[^>]*>\s*inline\s+[\w\*\s]+?__fastcall\s+(\w+)\s*\(", "template function"),
                (r"^\s*(?:EXPORT\s+)?[\w\*&:<> ]+?[\s\*&]+(\w+)\s*\([^;{]*\)\s*[;{]", "function"),
                (r"^(\w+)::\1\s*\(", "ctor"),
            ]
            for pat, kind in pats:
                for m in re.finditer(pat, txt, re.M):
                    name = m.group(1)
                    if name in CONTROL_KEYWORDS or name.startswith("__"):
                        continue
                    defs.setdefault(name, (f, line_of(txt, m.start(1)), kind))
        # ignore the include-guard macro and helper locals
        for junk in ("__AUTOROOT_H__", "XP_WIN", "rval", "obj", "main"):
            defs.pop(junk, None)
        return defs

    # ---- symbol table ---------------------------------------------------------------
    def _classify_symbols(self):
        syms = {}
        for f in self.files:
            for m in TOKEN_RE.finditer(self.code[f]):
                t = m.group()
                if t in syms:
                    continue
                base = t.split("::")[-1]
                hd = self.header_decl.get(base if "::" in t else t)
                # a bare mention in a header (kind "identifier") is not a SpiderMonkey API symbol
                in_sm = bool(CANDIDATE_RE.match(t)) and hd is not None and hd[2] != "identifier"
                in_d2 = t in self.wrapper_defs and t in WRAPPER_DESC
                if in_d2 and in_sm:
                    origin = "both"
                elif in_d2:
                    origin = "d2bs"
                elif in_sm:
                    origin = "sm"
                else:
                    continue
                syms[t] = origin
        return syms

    def category(self, sym):
        for cat, pat in CATEGORY_RULES:
            if re.search(pat, sym):
                return cat
        return "other"

    def _count_refs(self):
        refs = collections.defaultdict(collections.Counter)  # sym -> file -> count
        for f in self.files:
            for m in TOKEN_RE.finditer(self.code[f]):
                t = m.group()
                if t in self.symbols:
                    refs[t][f] += 1
        return refs

    def _count_member_calls(self):
        res = {}
        for name, (pat, _, _) in MEMBER_CALLS.items():
            c = collections.Counter()
            for f in self.files:
                n = len(re.findall(pat, self.code[f]))
                if n:
                    c[f] = n
            if c:
                res[name] = c
        return res

    def arity_counts(self, name):
        cnt = collections.Counter()
        for f in self.files:
            txt = self.code[f]
            for m in re.finditer(r"\b%s\s*\(" % name, txt):
                depth, k, commas = 1, m.end(), 0
                while k < len(txt) and depth:
                    ch = txt[k]
                    if ch in "([{":
                        depth += 1
                    elif ch in ")]}":
                        depth -= 1
                    elif ch == "," and depth == 1:
                        commas += 1
                    k += 1
                cnt[commas + 1] += 1
        return cnt

    def file_refs(self, f):
        return sum(self.refs[s][f] for s in self.refs)

    def file_syms(self, f):
        return sorted(s for s in self.refs if self.refs[s][f])

    # ---- include graph --------------------------------------------------------------
    def includes(self):
        inc = {}
        names = {os.path.basename(f).lower(): f for f in self.files}
        for f in self.files:
            lst = []
            for m in re.finditer(r'^\s*#\s*include\s*"([^"]+)"', self.raw[f], re.M):
                target = os.path.basename(m.group(1).replace("\\", "/")).lower()
                lst.append(names.get(target, m.group(1)))
            inc[f] = lst
        return inc

    def js_exposure(self):
        inc = self.includes()
        direct = {f: any("jsapi.h" in i or "jsfriendapi.h" in i or i == "js32.h" for i in inc[f]) for f in self.files}
        direct["js32.h"] = True
        trans = {}

        def visit(f, seen):
            if f in trans:
                return trans[f]
            if f in seen or f not in inc:
                return False
            seen.add(f)
            r = direct.get(f, False) or any(visit(i, seen) for i in inc[f] if i in inc)
            return r

        for f in self.files:
            trans[f] = visit(f, set())
        return direct, trans


# --------------------------------------------------------------------------------------
# scope scanner (for signatures and members)
# --------------------------------------------------------------------------------------


def scan_scopes(text):
    """Yield (kind, stmt_text, start_offset, scope_stack) for each statement terminated by ';'
    or for each '{' opening, at class/namespace/global level. Also returns a per-offset
    'allowed' predicate for function-signature matching."""
    stack = []  # list of (kind, name)
    stmts = []
    buf_start = 0
    i = 0
    n = len(text)
    allowed_ranges = []  # (start, end) offsets where we are in global/class/namespace scope
    cur_allowed_start = 0

    def in_decl_scope():
        return all(k in ("class", "namespace", "extern") for k, _ in stack)

    while i < n:
        ch = text[i]
        if ch == "{":
            head = re.sub(r"(?m)^[ \t]*#.*$", "", text[buf_start:i])
            hs = head.strip()
            if re.search(r"\b(class|struct|union)\b", hs) and "(" not in hs.split("=")[0] and "=" not in hs:
                m = re.search(r"\b(?:class|struct|union)\s+(\w+)", hs)
                kind, name = "class", (m.group(1) if m else "<anon>")
            elif re.search(r"\bnamespace\b", hs):
                kind, name = "namespace", hs
            elif re.search(r'extern\s+"C"', head) or re.search(r"\bextern\s*$", hs):
                kind, name = "extern", "C"
            elif re.search(r"\benum\b", hs):
                kind, name = "enum", hs
            elif "=" in hs and not hs.endswith(")"):
                kind, name = "init", hs
            elif ")" in hs or hs.endswith("const") or re.search(r"\b(else|do|try)$", hs):
                kind, name = "func", hs
            else:
                kind, name = "block", hs
            if in_decl_scope() and kind not in ("class", "namespace", "extern"):
                allowed_ranges.append((cur_allowed_start, i + 1))
            if in_decl_scope() and kind in ("class", "namespace", "extern", "func", "init", "enum", "block"):
                stmts.append(("open", kind, hs, buf_start, [s for s in stack]))
            stack.append((kind, name))
            buf_start = i + 1
        elif ch == "}":
            if stack:
                kind, _ = stack.pop()
            else:
                kind = "?"
            if in_decl_scope() and kind not in ("class", "namespace", "extern"):
                cur_allowed_start = i + 1
            buf_start = i + 1
        elif ch == ";":
            if in_decl_scope():
                stmts.append(("stmt", stack[-1][0] if stack else "global", text[buf_start:i], buf_start,
                              [s for s in stack]))
            buf_start = i + 1
        i += 1
    if in_decl_scope():
        allowed_ranges.append((cur_allowed_start, n))
    return stmts, allowed_ranges


SIG_ARGS = r"\(\s*(?P<args>[^;{}()]*(?:\([^()]*\)[^;{}()]*)*)\)\s*(?:const\s*)?(?P<end>[;{:])"
SIG_RE = re.compile(r"(?P<ret>(?:[\w:\*&<>~]+[ \t\*&]+)+?)(?P<name>~?[A-Za-z_][\w:]*(?<=operator)(?:\s*(?:\(\)|[^\s\w(]{1,3}))|"
                    r"~?[A-Za-z_][\w:]*)\s*" + SIG_ARGS)
# constructors/destructors have no return type: `Name(`, `Name::Name(`, `Name::~Name(` at line start
CTOR_RE = re.compile(r"(?m)^[ \t]*(?:explicit\s+|inline\s+)?(?P<name>(?:(?P<cls>\w+)::)?~?(?P<base>\w+))\s*" + SIG_ARGS)


def class_names(texts):
    return {m.group(1) for t in texts for m in re.finditer(r"\b(?:class|struct)\s+(\w+)\s*[:{]", t)}


def find_signatures(text, classes=None):
    """(offset, return type, name, args, end) for every function signature at namespace/class
    scope. Constructors/destructors (empty return type) are included when their name is
    `X::X`/`X::~X` or the name of a class in `classes`."""
    text = blank_pp(text)
    _, ranges = scan_scopes(text)
    classes = classes or set()
    res, seen = [], set()
    for m in SIG_RE.finditer(text):
        off = m.start("name")
        if not any(a <= off < b for a, b in ranges):
            continue
        name = m.group("name")
        base = name.split("::")[-1]
        if base in CONTROL_KEYWORDS:
            continue
        ret = m.group("ret").strip()
        if re.match(r"^(return|else|new|delete|case|goto)\b", ret):
            continue
        res.append((off, ret, name, m.group("args"), m.group("end")))
        seen.add(off)
    for m in CTOR_RE.finditer(text):
        off = m.start("name")
        if off in seen or not any(a <= off < b for a, b in ranges):
            continue
        base = m.group("base")
        if not ((m.group("cls") and m.group("cls") == base) or base in classes):
            continue
        res.append((off, "", m.group("name"), m.group("args"), m.group("end")))
    res.sort()
    return res


# --------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------


def sec_summary(repo):
    direct, trans = repo.js_exposure()
    total_refs = sum(sum(c.values()) for c in repo.refs.values())
    sm = [s for s, o in repo.symbols.items() if o in ("sm", "both")]
    d2 = [s for s, o in repo.symbols.items() if o in ("d2bs", "both")]
    files_with = [f for f in repo.files if repo.file_refs(f)]
    loc = sum(repo.raw[f].count("\n") + 1 for f in repo.files)
    out = ["| metric | value |", "|---|---|"]
    out.append("| source files scanned | %d |" % len(repo.files))
    out.append("| total lines (scanned files) | %d |" % loc)
    out.append("| distinct SpiderMonkey symbols referenced | %d |" % len(sm))
    out.append("| distinct D2BS wrapper symbols referenced (js32.h/js32.cpp/AutoRoot.*) | %d |" % len(d2))
    out.append("| ... of which shadow a SpiderMonkey name (macro/overload) | %d |" % sum(1 for o in repo.symbols.values() if o == "both"))
    out.append("| member-call pseudo-symbols (handle/clone/options methods) | %d distinct, %d calls |" % (
        len(repo.member_calls), sum(sum(c.values()) for c in repo.member_calls.values())))
    out.append("| total JSAPI symbol references (live code) | %d |" % total_refs)
    out.append("| files with >=1 JSAPI reference | %d |" % len(files_with))
    out.append("| files that #include js32.h/jsapi.h directly | %d |" % sum(1 for f in repo.files if direct.get(f)))
    out.append("| files that reach jsapi.h transitively | %d |" % sum(1 for f in repo.files if trans.get(f)))
    return "\n".join(out)


def sec_symbols(repo):
    rows = []
    for s in sorted(repo.symbols, key=lambda s: (repo.category(s), s.lower())):
        if repo.symbols[s] not in ("sm", "both"):
            continue
        c = repo.refs[s]
        tot = sum(c.values())
        if not tot:
            continue
        hf, hl, kind = repo.header_decl.get(s, repo.header_decl.get(s.split("::")[-1], ("?", 0, "?")))
        hf = hf.replace("dependencies/include/", "")
        files = ", ".join("%s(%d)" % (f, n) for f, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))
        shadow = " + D2BS shadow" if repo.symbols[s] == "both" else ""
        rows.append(("`%s`" % s, repo.category(s), kind + shadow, "%s:%d" % (hf, hl), tot, len(c), files))
    for s in sorted(repo.member_calls):
        c = repo.member_calls[s]
        files = ", ".join("%s(%d)" % (f, n) for f, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))
        rows.append(("`%s`" % s, MEMBER_CALLS[s][1], "member function", MEMBER_CALLS[s][2], sum(c.values()), len(c), files))
    out = table(["symbol", "category", "kind", "declared (dependencies/include/...)", "refs", "files", "files (refs)"], rows)
    cat = collections.OrderedDict((c, [0, 0, 0, 0, set()]) for c, _ in CATEGORY_RULES)
    cat["other"] = [0, 0, 0, 0, set()]
    for s, o in repo.symbols.items():
        c = cat[repo.category(s)]
        n = sum(repo.refs[s].values())
        if o in ("sm", "both"):
            c[0] += 1
            c[1] += n
        if o in ("d2bs", "both"):
            c[2] += 1
            c[3] += n
        c[4] |= set(repo.refs[s])
    for s, c in repo.member_calls.items():
        cat[MEMBER_CALLS[s][1]][0] += 1
        cat[MEMBER_CALLS[s][1]][1] += sum(c.values())
        cat[MEMBER_CALLS[s][1]][4] |= set(c)
    crows = [(k, v[0], v[1], v[2], v[3], len(v[4])) for k, v in cat.items() if v[0] or v[2]]
    out += "\n\nPer category (SpiderMonkey symbols incl. member-call pseudo-symbols; wrappers from js32.h/AutoRoot.h):\n\n"
    out += table(["category", "SM symbols", "SM refs", "D2BS wrappers", "wrapper refs", "files touched"], crows)
    return out


def sec_wrappers(repo):
    rows = []
    for s in sorted(repo.wrapper_defs, key=lambda s: (repo.wrapper_defs[s][0], repo.wrapper_defs[s][1])):
        if s not in WRAPPER_DESC:
            continue
        f, l, kind = repo.wrapper_defs[s]
        c = repo.refs.get(s, collections.Counter())
        tot = sum(c.values())
        users = sorted(x for x in c if x not in WRAPPER_FILES)
        status = "used in %d files" % len(users) if users else ("internal only" if tot > 1 else "unused")
        rows.append(("`%s`" % s, repo.category(s), "%s:%d" % (f, l), kind, tot, status, WRAPPER_DESC[s]))
    out = table(["wrapper", "category", "defined", "kind", "refs", "use", "meaning"], rows)
    arows = []
    for name, labels in ARITY_SPLIT.items():
        cnt = repo.arity_counts(name)
        for n in sorted(cnt):
            arows.append(("`%s`" % name, n, labels.get(n, "declaration/other"), cnt[n]))
    out += "\n\n" + table(["call", "args", "resolves to", "occurrences (incl. declarations)"], arows)
    # JSAPI-looking identifiers that neither the bundled headers nor the wrappers declare
    unres = collections.defaultdict(collections.Counter)
    for f in repo.files:
        for m in TOKEN_RE.finditer(repo.code[f]):
            t = m.group()
            if t not in repo.symbols and re.match(r"^(JS_\w+|JSVAL_\w+|JSPROP_\w+|JSCLASS_\w+|JSFUN_\w+|JSOPTION_\w+|"
                                                  r"JS::\w+|js::\w+|\w+_TO_JSVAL)$", t):
                unres[t][f] += 1
    urows = [("`%s`" % t, ", ".join("%s(%d)" % kv for kv in sorted(c.items()))) for t, c in sorted(unres.items())]
    out += "\n\nJSAPI-pattern identifiers in live code that the bundled SpiderMonkey 22 headers do not declare:\n\n"
    out += table(["identifier", "files (refs)"], urows)
    return out


def sec_typedefs(repo):
    rows = []
    for t in GENERIC_TYPEDEFS:
        cnt = collections.Counter()
        for f in repo.files:
            k = len(re.findall(r"\b%s\b" % t, repo.code[f]))
            if k:
                cnt[f] = k
        nonjs = sorted(f for f in cnt if CLASSIFICATION.get(f, "d") in ("c", "d"))
        d = repo.wrapper_defs.get(t, ("js32.h", 0, ""))
        rows.append(("`%s`" % t, "%s:%d" % (d[0], d[1]), sum(cnt.values()), len(cnt), ", ".join(nonjs) or "-"))
    return table(["typedef", "defined", "refs", "files", "non-binding files using it"], rows)


def sec_files(repo):
    direct, trans = repo.js_exposure()
    rows = []
    warn = []
    for f in repo.files:
        raw = repo.raw[f]
        loc = raw.count("\n") + (0 if raw.endswith("\n") else 1) if raw else 0
        code_loc = sum(1 for ln in repo.code[f].split("\n") if ln.strip())
        r = repo.file_refs(f)
        cls = CLASSIFICATION.get(f, "d")
        if cls == "d" and r:
            warn.append(f)
        eng = len(re.findall(ENGINE_API, repo.code[f])) if cls in ("c", "d") else ""
        rows.append((f, loc, code_loc, r, len(repo.file_syms(f)), "yes" if direct.get(f) else "",
                     "yes" if trans.get(f) else "", eng or "", cls, NOTES.get(f, "")))
    out = table(["file", "LOC", "code LOC", "JSAPI refs", "distinct syms", "direct JS include", "reaches jsapi.h",
                 "engine API refs", "class", "note"], rows)
    if warn:
        out += "\n\nWARNING: classified 'd' but has JSAPI refs: " + ", ".join(warn)
    counts = collections.Counter(CLASSIFICATION.get(f, "d") for f in repo.files)
    locs = collections.Counter()
    for f in repo.files:
        locs[CLASSIFICATION.get(f, "d")] += repo.raw[f].count("\n") + 1
    out += "\n\n" + table(["class", "files", "LOC"], [(k, counts[k], locs[k]) for k in "abcd"])
    return out


def sec_mixed(repo):
    rows = []
    for f in repo.files:
        if CLASSIFICATION.get(f, "d") not in ("b", "c"):
            continue
        txt = repo.code[f]
        for off, ret, name, args, end in find_signatures(txt, repo.classes):
            sig_js = sorted(set(re.findall(SIG_TYPES, ret + " (" + args + ")")))
            if not sig_js:
                continue
            kind = "def" if end in "{:" else "decl"
            sig = re.sub(r"\s+", " ", "%s %s(%s)" % (ret, name, args)).strip()
            rows.append((f, line_of(txt, off), kind, "`%s`" % sig, ", ".join(sig_js)))
    return table(["file", "line", "def/decl", "signature", "JS types"], rows)


def sec_members(repo):
    rows = []
    for f in repo.files:
        txt = blank_pp(repo.code[f])
        stmts, _ = scan_scopes(txt)
        for st in stmts:
            if st[0] != "stmt":
                continue
            _, scope, body, off, stack = st
            body = re.sub(r"(?m)^[ \t]*#.*$", lambda m: " " * len(m.group()), body)
            body = re.sub(r"\b(public|private|protected)\s*:", lambda m: re.sub(r"\S", " ", m.group()), body)
            b = body.strip()
            if not b or "(" in b and not re.search(r"\(\s*\*", b):
                continue
            if b.startswith(("typedef", "using", "friend", "return", "#")):
                continue
            if not re.search(STATE_TYPES, b):
                continue
            # skip static metadata tables
            if re.search(r"\b(JSClass|JSFunctionSpec|JSPropertySpec|JSClassSpec)\b", b) and not re.search(STATE_TYPES.replace("JSObject|", ""), b):
                continue
            owner = "::".join(n for k, n in stack if k == "class") or "<global>"
            lead = len(body) - len(body.lstrip())
            rows.append((f, line_of(txt, off + lead), owner, "`%s`" % re.sub(r"\s+", " ", b)))
    return table(["file", "line", "owner", "declaration"], rows)


NATIVE_PATTERNS = [
    (re.compile(r"\bJSAPI_FUNC\(\s*(\w+)\s*\)\s*\{"), "FUNC", lambda n: n),
    (re.compile(r"\bJSAPI_PROP\(\s*(\w+)\s*\)\s*\{"), "GETTER/PROP", lambda n: n),
    (re.compile(r"\bJSAPI_STRICT_PROP\(\s*(\w+)\s*\)\s*\{"), "SETTER", lambda n: n),
    (re.compile(r"\bCLASS_CTOR\(\s*(\w+)\s*\)\s*\{"), "CTOR", lambda n: n + "_ctor"),
    (re.compile(r"\bEMPTY_CTOR\(\s*(\w+)\s*\)"), "CTOR(empty)", lambda n: n + "_ctor"),
    (re.compile(r"\bvoid\s+(\w+)\s*\(\s*JSFreeOp\s*\*\s*\w*\s*,\s*JSObject\s*\*\s*\w*\s*\)\s*\{"), "FINALIZER", lambda n: n),
    (re.compile(r"\bJSBool\s+(\w+)\s*\(\s*JSContext\s*\*\s*\w+\s*,\s*JSObject\s*\*\s*\w+\s*,\s*jsval\s+\w+\s*,\s*JSBool\s*\*\s*\w+\s*\)\s*\{"),
     "EQUALITY", lambda n: n),
]


def spec_tables(repo):
    """Return (func_names: cfunc -> [js names], prop_names: cfunc -> Counter(table))."""
    fn = collections.defaultdict(list)
    props = collections.defaultdict(collections.Counter)
    table_of = {}
    # JSClass C name -> JS class name
    jsclass = {}
    for f in repo.files:
        t = repo.code_s[f]
        for m in re.finditer(r"\bJSClass\s+(\w+)\s*=\s*\{\s*\"([^\"]+)\"", t):
            jsclass[m.group(1)] = m.group(2)
    # table name -> owning JS class
    for f in repo.files:
        t = repo.code_s[f]
        for m in re.finditer(r"\{\s*&(\w+)\s*,\s*\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\}", t):
            cls = jsclass.get(m.group(1), m.group(1))
            for i, suffix in ((2, ""), (3, ""), (4, " (static)"), (5, " (static)")):
                if m.group(i) not in ("NULL", "0"):
                    table_of.setdefault(m.group(i), cls + suffix)
        for m in re.finditer(r"BuildObject\(\s*cx\s*,\s*&(\w+)\s*,\s*(\w+)\s*,\s*(\w+)", t):
            cls = jsclass.get(m.group(1), m.group(1))
            for g in (2, 3):
                if m.group(g) not in ("NULL", "0"):
                    table_of.setdefault(m.group(g), cls)
    table_of["global_funcs"] = "global"
    table_of["me_props"] = "me"
    # JSClass C names that reach the engine (global_classes rows, BuildObject/JS_NewObject/
    # JS_NewGlobalObject/JS_InitClass arguments); any other JSClass is never registered
    registered = set()
    for f in repo.files:
        t = repo.code_s[f]
        registered |= set(re.findall(r"\{\s*&(\w+)\s*,\s*\w+\s*,\s*\w+\s*,", t))
        registered |= set(re.findall(r"\b(?:BuildObject|JS_NewObject|JS_NewGlobalObject|JS_InitClass)\s*\([^;]*?&(\w+)", t))
    for f in repo.files:
        t = repo.code_s[f]
        for tm in re.finditer(r"\b(?:static\s+)?(JSFunctionSpec|JSPropertySpec)\s+(\w+)\s*\[\s*\]\s*=\s*\{", t):
            kind, tname = tm.group(1), tm.group(2)
            end = match_brace(t, tm.end() - 1)
            body = t[tm.end():end]
            owner = table_of.get(tname, "UNREGISTERED:" + tname)
            if kind == "JSFunctionSpec":
                for m in re.finditer(r"JS_F[NS]\(\s*\"([^\"]+)\"\s*,\s*(\w+)", body):
                    fn[m.group(2)].append(("%s()" % m.group(1)) if owner == "global" else "%s.%s()" % (owner, m.group(1)))
            else:
                for m in re.finditer(r"\{\s*\"([^\"]+)\"\s*,\s*[^,]+,\s*[^,]+,\s*JSOP_WRAPPER\((\w+)\)\s*,\s*(JSOP_NULLWRAPPER|JSOP_WRAPPER\((\w+)\))", body):
                    props[m.group(2)][owner + " get"] += 1
                    if m.group(4):
                        props[m.group(4)][owner + " set"] += 1
        for m in re.finditer(r"JS_DefineFunction\(\s*cx\s*,\s*\w+\s*,\s*\"([^\"]+)\"\s*,\s*(\w+)", t):
            fn[m.group(2)].append("DialogLine.%s()" % m.group(1))
    # ctors and finalizers from JSClass definitions
    for f in repo.files:
        t = repo.code_s[f]
        for m in re.finditer(r"\bJSClass\s+(\w+)\s*=\s*\{\s*\"([^\"]+)\"(.*?)\};", t, re.S):
            sm = re.search(r"JSCLASS_SPEC\(([^;]*)\)\s*$", m.group(3).strip(), re.S)
            if not sm:
                continue
            parts = [p.strip() for p in sm.group(1).split(",")]
            if len(parts) >= 9:
                fin, ctor = parts[7], parts[8]
                note = "" if m.group(1) in registered else " [class %s never registered]" % m.group(1)
                if fin not in ("NULL", "0"):
                    fn[fin].append("%s finalize%s" % (m.group(2), note))
                if ctor not in ("NULL", "0"):
                    fn[ctor].append("new %s()%s" % (m.group(2), note))
                for idx, hook in ((0, "addProperty"), (1, "delProperty"), (2, "getProperty"), (3, "setProperty")):
                    p = re.sub(r"\(\w+\)", "", parts[idx]).strip()
                    if not p.startswith("JS_"):
                        fn[p].append("%s.%s hook" % (m.group(2), hook))
    return fn, props


def native_list(repo):
    sm_names = {s for s, o in repo.symbols.items()}
    helper_names = set()
    for f in repo.files:
        if CLASSIFICATION.get(f, "d") == "a":
            continue
        for off, ret, name, args, end in find_signatures(repo.code[f]):
            base = name.split("::")[-1]
            if ret and base not in sm_names and not base.startswith("JS"):
                helper_names.add(base)
    res = []
    for f in repo.files:
        if CLASSIFICATION.get(f, "d") != "a":
            continue
        txt = repo.code[f]
        for pat, kind, namefn in NATIVE_PATTERNS:
            for m in pat.finditer(txt):
                name = namefn(m.group(1))
                start_line = line_of(txt, m.start())
                if kind == "CTOR(empty)":
                    res.append(dict(file=f, line=start_line, name=name, kind=kind, loc=1, js=0, d2=[], helpers=[],
                                    logic=0, body="", flags="", bare=0, body_off=m.start(), text=txt))
                    continue
                ob = m.end() - 1
                cb = match_brace(txt, ob)
                body = txt[ob + 1:cb]
                loc = line_of(txt, cb) - start_line + 1
                js = sum(1 for t in TOKEN_RE.findall(body) if t in repo.symbols)
                d2 = sorted(set(re.findall(r"\b(?:p_)?D2[A-Z0-9]+_\w+", body)))
                calls = set(re.findall(r"(?<![\.>:\w])([A-Za-z_]\w*)\s*\(", body)) | \
                    set("ScriptEngine::" + x for x in re.findall(r"ScriptEngine::(\w+)\s*\(", body))
                helpers = sorted(c for c in calls if (c in helper_names or c.startswith("ScriptEngine::"))
                                 and not re.match(r"(?:p_)?D2[A-Z0-9]+_", c))
                logic = 0
                for ln in body.split("\n"):
                    s = ln.strip()
                    if not s or re.fullmatch(r"[{}();\s]*", s) or re.fullmatch(r"(return\s+JS_(TRUE|FALSE)|break|else|default:);?\s*\}?", s):
                        continue
                    if any(t in repo.symbols for t in TOKEN_RE.findall(s)):
                        continue
                    logic += 1
                res.append(dict(file=f, line=start_line, name=name, kind=kind, loc=loc, js=js, d2=d2, helpers=helpers,
                                logic=logic, body=body, flags=native_flags(body), bare=bare_false(body),
                                body_off=ob + 1, text=txt))
    res.sort(key=lambda d: (d["file"], d["line"]))
    return res


FLAG_RULES = [
    ("L", r"\bAutoCriticalRoom\b"),                       # takes Vars.cGameLoopSection (game-loop lock)
    ("W", r"\bWaitForGameReady\s*\("),                    # may block until the game is ready
    ("B", r"\bSleep\s*\(|\bWaitForSingleObject(?:Ex)?\s*\(|->\s*Join\s*\(|\bSendMessage\s*\(|\bInternetOpenUrl\s*\("),
    ("E", r"\bExecScriptEvent\s*\(|\bSetSkill\s*\("),     # runs queued JS events re-entrantly
    ("P", r"\bD2NET_SendPacket\s*\(|\bD2NET_ReceivePacket\s*\(|\bD2CLIENT_SendGamePacket\s*\("),
    ("M", r"\bWriteProcessMemory\b|\bReadProcessBYTES\b|\bGetDllOffset\s*\("),
    ("S", r"\bScriptEngine::\w+|->\s*(?:RegisterEvent|UnregisterEvent|ClearEvent|ClearAllEvents|FireEvent|Include|Stop|Pause|Resume)\s*\("),
    ("C", r"JSAutoStructuredCloneBuffer"),
]


def native_flags(body):
    return "".join(f for f, pat in FLAG_RULES if re.search(pat, body))


def split_statements(text, base=0):
    out, start = [], 0
    for k, ch in enumerate(text):
        if ch in ";{}":
            st = text[start:k + (1 if ch == ";" else 0)]
            if st.strip():
                out.append((base + start + (len(st) - len(st.lstrip())), st.strip()))
            start = k + 1
    return out


def bare_false(body):
    """`return JS_FALSE` with no JS_Report*/ConvertArguments/ConvertValue in the same or the two
    previous statements: the script is terminated without a catchable exception."""
    sts = split_statements(body)
    n = 0
    for i, (_, st) in enumerate(sts):
        if re.search(r"\breturn\s+JS_FALSE\b", st):
            window = " ".join(x[1] for x in sts[max(0, i - 2):i + 1])
            if not re.search(r"JS_Report\w*|JS_ConvertArguments|JS_ConvertValue", window):
                n += 1
    return n


def lock_leaks(d):
    """Lines of return/THROW_* statements that can be reached after `new AutoCriticalRoom`
    while no `delete cRoom` has executed in the current or an enclosing block. The scan
    stops when the block that contains the `new` closes."""
    body = d["body"]
    m = re.search(r"\bnew\s+AutoCriticalRoom\b", body)
    if not m:
        return []
    deleted = [False]          # per open block (relative to the block holding the `new`)
    bad, start = [], m.end()
    k = m.end()
    while k < len(body):
        ch = body[k]
        if ch in ";{}":
            st = body[start:k]
            if "delete cRoom" in st:
                deleted[-1] = True
            elif re.search(r"\breturn\b|\bTHROW_(?:ERROR|WARNING)\b", st) and not any(deleted):
                off = start + len(st) - len(st.lstrip())
                bad.append(line_of(d["text"], d["body_off"] + off))
            if ch == "{":
                deleted.append(False)
            elif ch == "}":
                deleted.pop()
                if not deleted:
                    break
            start = k + 1
        k += 1
    return bad


def weight(d):
    if d["logic"] <= 5:
        return "thin"
    if d["logic"] < 25:
        return "moderate"
    return "heavy"


def sec_natives(repo):
    fn, props = spec_tables(repo)
    rows = []
    for d in native_list(repo):
        names = list(fn.get(d["name"], []))
        if d["name"] in props:
            names += [("%d props (%s)" % (n, t)) if not t.startswith("UNREGISTERED:") else
                      ("%d props in %s [table never registered]" % (n, t.split(":", 1)[1].replace(" get", ""))) +
                      (" set" if t.endswith(" set") else "")
                      for t, n in sorted(props[d["name"]].items())]
        rows.append(("%s:%d" % (d["file"], d["line"]), "`%s`" % d["name"], d["kind"], "; ".join(names) or "(not registered)",
                     d["loc"], d["js"], d["logic"], weight(d), len(d["d2"]), d["flags"] or "-", d["bare"] or "",
                     ", ".join(d["helpers"]) or "-"))
    out = table(["location", "C function", "kind", "JS-visible as", "body LOC", "JSAPI refs", "logic lines", "weight",
                 "D2 ptrs", "flags", "bare JS_FALSE", "D2BS helpers called"], rows)
    nl = native_list(repo)
    w = collections.Counter(weight(d) for d in nl)
    out += "\n\n" + table(["weight", "natives"], [(k, w[k]) for k in ("thin", "moderate", "heavy")])
    fl = collections.Counter(c for d in nl for c in d["flags"])
    out += "\n\n" + table(["flag", "natives"], [(k, fl[k]) for k, _ in FLAG_RULES])
    # non-native functions living in binding files
    nat = {(d["file"], d["name"]) for d in nl}
    hrows = []
    for f in repo.files:
        if CLASSIFICATION.get(f, "d") != "a":
            continue
        for off, ret, name, args, end in find_signatures(repo.code[f], repo.classes):
            if end not in "{:" or (f, name) in nat or name in WRAPPER_DESC:
                continue
            sig = re.sub(r"\s+", " ", "%s %s(%s)" % (ret, name, args)).strip()
            hrows.append(("%s:%d" % (f, line_of(repo.code[f], off)), "`%s`" % sig,
                          ", ".join(sorted(set(re.findall(SIG_TYPES, sig)))) or "-"))
    out += "\n\nNon-native helper functions defined in binding files:\n\n" + table(["location", "signature", "JS types"], hrows)
    rrows = []
    for d in nl:
        if d["kind"] != "FUNC":
            continue
        never, early = rval_unset(d)
        if never or early:
            rrows.append(("%s:%d" % (d["file"], d["line"]), "`%s`" % d["name"], "; ".join(fn.get(d["name"], [])) or "(not registered)",
                          "never sets it" if never else ", ".join("%s:%d" % (d["file"], l) for l in early)))
    out += "\n\nFUNC natives that return `JS_TRUE` without having set the return value (no `JS_SET_RVAL`/`THROW_WARNING` " \
           "anywhere in the body, or a `return JS_TRUE` that textually precedes the first one; a lower bound, since " \
           "sets inside branches are not path-checked):\n\n"
    out += table(["location", "C function", "JS-visible as", "unset-rval returns"], rrows)
    return out


RVAL_SET = r"\bJS_SET_RVAL\s*\(|\bTHROW_WARNING\s*\(|\*\s*vp\s*=|\bvp\s*\[\s*0\s*\]\s*="


def rval_unset(d):
    """(never, early_lines) for a FUNC native: never = the body contains no return-value store;
    early_lines = `return JS_TRUE` statements that come before the first store."""
    sets = [m.start() for m in re.finditer(RVAL_SET, d["body"])]
    rets = [m.start() for m in re.finditer(r"\breturn\s+JS_TRUE\b", d["body"])]
    if not sets:
        return bool(rets), []
    return False, [line_of(d["text"], d["body_off"] + r) for r in rets if r < sets[0]]


def sec_locks(repo):
    rows = []
    for d in native_list(repo):
        if "L" not in d["flags"]:
            continue
        leaks = lock_leaks(d)
        rows.append(("%s:%d" % (d["file"], d["line"]), "`%s`" % d["name"], "native",
                     ", ".join("%s:%d" % (d["file"], l) for l in leaks) or "-"))
    # JS-free helpers (any file) that take the lock themselves
    nat = {(d["file"], d["line"]) for d in native_list(repo)}
    for f in repo.files:
        txt = repo.code[f]
        for off, ret, name, args, end in find_signatures(txt, repo.classes):
            if end != "{" or (f, line_of(txt, off)) in nat:
                continue
            ob = txt.find("{", off)
            cb = match_brace(txt, ob)
            body = txt[ob + 1:cb]
            if not re.search(r"\bnew\s+AutoCriticalRoom\b", body):
                continue
            d = dict(body=body, text=txt, body_off=ob + 1)
            leaks = lock_leaks(d)
            rows.append(("%s:%d" % (f, line_of(txt, off)), "`%s`" % name, "helper (%s)" % CLASSIFICATION.get(f, "d"),
                         ", ".join("%s:%d" % (f, l) for l in leaks) or "-"))
    return table(["function", "C function", "kind (file class)",
                  "return/throw reachable while the lock is still held (statement start line)"], rows)


def sec_strings(repo):
    rows = []
    for f in repo.files:
        c = [sum(1 for _ in re.finditer(r"\b%s\b" % fn, repo.code[f])) for fn in ENCODING_FUNCS]
        a2u = len(re.findall(r"\bAnsiToUnicode\b", repo.code[f]))
        u2a = len(re.findall(r"\bUnicodeToAnsi\b", repo.code[f]))
        if any(c):
            rows.append([f] + [x or "" for x in c] + [a2u or "", u2a or ""])
    return table(["file"] + ["`%s`" % x for x in ENCODING_FUNCS] + ["`AnsiToUnicode`", "`UnicodeToAnsi`"], rows)


def sec_clone(repo):
    rows = []
    for f in repo.files:
        txt = repo.code[f]
        for m in re.finditer(r"JSAutoStructuredCloneBuffer|(?:->|\.)\s*(write|read|clear)\s*\(\s*(?:cx|context|helper->cx)?", txt):
            ln = line_of(txt, m.start())
            src = repo.raw[f].split("\n")[ln - 1].strip()
            if "JSAutoStructuredCloneBuffer" in m.group(0) or re.search(r"argv\[\w*\s*-?\s*\d*\]\s*->\s*(write|read|clear)", src):
                rows.append((f, ln, "`%s`" % src))
    seen, out = set(), []
    for r in rows:
        if (r[0], r[1]) not in seen:
            seen.add((r[0], r[1]))
            out.append(r)
    return table(["file", "line", "code"], out)


def func_start(text, off):
    """Offset just after the '{' that opens the outermost function (non class/namespace)
    block enclosing `off`, or None at namespace/class scope. `text` should be blank_pp()'d."""
    stack, buf = [], 0
    for k in range(off):
        ch = text[k]
        if ch == "{":
            head = text[buf:k]
            iscls = bool(re.search(r"\b(class|struct|union|namespace)\b|extern\s*$", head.strip())) and \
                "(" not in head and "=" not in head
            stack.append((iscls, k))
            buf = k + 1
        elif ch == "}":
            if stack:
                stack.pop()
            buf = k + 1
        elif ch == ";":
            buf = k + 1
    for iscls, k in stack:
        if not iscls:
            return k + 1
    return None


def innermost_head(text, off):
    """Text between the previous statement end and the '{' of the innermost block enclosing
    `off` (e.g. "for (int i = 0; ...)" for a loop body)."""
    stack, buf = [], 0
    for k in range(off):
        ch = text[k]
        if ch == "{":
            stack.append(text[buf:k])
            buf = k + 1
        elif ch == "}":
            if stack:
                stack.pop()
            buf = k + 1
        elif ch == ";" and not re.search(r"\bfor\s*\([^)]*$", text[buf:k]):
            buf = k + 1
    return stack[-1].strip() if stack else ""


ROOT_RX = re.compile(r"\b(%s)\s*\(\s*([^,]+?)\s*,\s*([^,)]+(?:\([^)]*\))?)" % "|".join(ROOT_ADD + ROOT_REMOVE))
LOCAL_DECL = r"\b(?:JSObject|jsval|JSScript|JSString|JSFunction|JS::\w+)\b[^;{}]*?(?<![\w>.])%s\b"


def root_sites(repo):
    """(file, line, call, arg, storage, offset) for every explicit root add/remove call
    (macro definitions in js32.h excluded). Storage: a name declared in the enclosing function
    body is a stack local; `->`/`.` paths and undeclared names are C++ object members; an
    indexed name is an element of a `new jsval[]` array."""
    sites = []
    for f in repo.files:
        txt = repo.code[f]
        bp = blank_pp(txt)
        for m in ROOT_RX.finditer(txt):
            ln = line_of(txt, m.start())
            if f == "js32.h" and re.match(r"\s*#\s*define", repo.raw[f].split("\n")[ln - 1]):
                continue
            arg = m.group(3).strip()
            name = re.match(r"&?\s*(\w+)", arg)
            fs = func_start(bp, m.start())
            if re.search(r"->|\.", arg):
                where = "heap (C++ object member)"
            elif "[" in arg:
                where = "heap (new jsval[])"
            elif fs is not None and name and re.search(LOCAL_DECL % name.group(1), txt[fs:m.start()]):
                where = "stack local"
            elif fs is None:
                where = "global"
            else:
                where = "heap (C++ object member)"
            sites.append((f, ln, m.group(1), arg, where, m.start()))
    return sites


def root_leaks(repo):
    """Native or helper bodies in which a `return`/`THROW_*` (or, when the add sits directly in a
    loop body, a `continue` in that body or one block below it) can be reached after a JS_Add*Root on a stack local and before
    the matching JS_Remove*Root, scanning the statements that follow the add with the same
    block rule as lock_leaks(). The `if (JS_AddRoot(..) == JS_FALSE) {..}` failure block is
    skipped."""
    adds = [s for s in root_sites(repo) if s[2] in ROOT_ADD and s[4] == "stack local"]
    rows = []
    for f, ln, call, arg, where, off in adds:
        txt = repo.code[f]
        name = re.match(r"&?\s*(\w+)", arg).group(1)
        rm = re.compile(r"\b(?:%s)\s*\(\s*[^,]+,\s*&?\s*%s\b" % ("|".join(ROOT_REMOVE), name))
        # continue right after the add call's closing parenthesis
        k, depth = txt.index("(", off) + 1, 1
        while k < len(txt) and depth:
            depth += {"(": 1, ")": -1}.get(txt[k], 0)
            k += 1
        fail = re.match(r"\s*==\s*JS_FALSE\s*\)\s*\{", txt[k:])
        if fail:  # `if (JS_AddRoot(..) == JS_FALSE) {...}`: that block is the add-failed path
            k = match_brace(txt, k + fail.end() - 1) + 1
        in_loop = bool(re.match(r"\s*(?:for|while)\b|\s*do\s*$", innermost_head(blank_pp(txt), off)))
        removed, bad, start = [False], [], k
        while k < len(txt):
            ch = txt[k]
            if ch in ";{}":
                st = txt[start:k]
                if rm.search(st):
                    removed[-1] = True
                elif not any(removed) and (re.search(r"\breturn\b|\bTHROW_(?:ERROR|WARNING)\b", st) or
                                           (in_loop and len(removed) <= 2 and re.search(r"\bcontinue\b", st))):
                    bad.append(line_of(txt, start + len(st) - len(st.lstrip())))
                if ch == "{":
                    removed.append(False)
                elif ch == "}":
                    removed.pop()
                    if not removed:
                        break
                start = k + 1
            k += 1
        if bad:
            rows.append(("%s:%d" % (f, ln), "`%s(%s)`" % (call, arg), ", ".join("%s:%d" % (f, b) for b in bad)))
    return rows


def sec_roots(repo):
    """every explicit root add/remove site and every AutoRoot construction, with the rooted
    address expression; then the early exits that leave a stack-slot root registered"""
    rows = [s[:4] + (s[4],) for s in root_sites(repo)]
    rows = [(f, ln, call, "`%s`" % arg, where) for f, ln, call, arg, where in rows]
    for f in repo.files:
        txt = repo.code[f]
        for m in re.finditer(r"\bnew\s+AutoRoot\s*\(", txt):
            depth, k = 1, m.end()
            while k < len(txt) and depth:
                depth += {"(": 1, ")": -1}.get(txt[k], 0)
                k += 1
            rows.append((f, line_of(txt, m.start()), "new AutoRoot", "`%s`" % re.sub(r"\s+", " ", txt[m.end():k - 1]).strip(),
                         "heap (AutoRoot::var)"))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = table(["file", "line", "call", "rooted address / args", "storage"], rows)
    out += "\n\nStack-slot roots that stay registered on an early exit (return/throw reachable after the add and " \
           "before the matching remove, statement start lines):\n\n"
    out += table(["add site", "call", "early exits"], root_leaks(repo))
    return out


def sec_build(repo):
    pat = re.compile(r"(?i)mozjs|js_static|mozilla|XP_WIN|STATIC_JS_API|dependencies|Filter Include=\"Spidermonkey|"
                     r"RuntimeLibrary|ExceptionHandling|<Command>|COPY /B|XCOPY|RMDIR|MKDIR|unzip|bob-18|IncludePath|"
                     r"PreprocessorDefinitions>WIN32|msbuild|vcvarsall|Visual Studio|ProjectConfiguration Include|"
                     r"DisableSpecificWarnings|WindowsTargetPlatformVersion|AdditionalIncludeDirectories|RuntimeTypeInfo|"
                     r"ConfigurationType|CharacterSet")
    rows = []
    for bf in BUILD_FILES:
        p = os.path.join(repo.root, bf)
        if not os.path.exists(p):
            rows.append((bf, "-", "(missing)"))
            continue
        lines = read(p).split("\n")
        for i, ln in enumerate(lines, 1):
            if not pat.search(ln):
                continue
            s_ = ln.strip().lstrip("\ufeff\xef\xbb\xbf")
            if bf.endswith(".filters") and s_.startswith("<Filter>"):
                continue
            # a filters entry for a dependencies header: show it with its filter on one row
            if bf.endswith(".filters") and "dependencies" in s_ and i < len(lines):
                s_ += " " + lines[i].strip()
            rows.append((bf, i, "`%s`" % (s_ if len(s_) < 260 else s_[:257] + "...")))
    return table(["file", "line", "content"], rows)


def sec_deps(repo):
    base = os.path.join(repo.root, "dependencies")
    rows = []
    groups = collections.OrderedDict()
    for p in sorted(glob.glob(os.path.join(base, "**", "*"), recursive=True)):
        if os.path.isdir(p):
            continue
        rel = os.path.relpath(p, repo.root).replace(os.sep, "/")
        d = os.path.dirname(rel)
        if d.endswith("include/mozilla") or d.endswith("include/js"):
            g = groups.setdefault(d + "/*", [0, 0])
            g[0] += 1
            g[1] += os.path.getsize(p)
            continue
        rows.append((rel, os.path.getsize(p)))
    for g, (n, sz) in groups.items():
        rows.append(("%s (%d files)" % (g, n), sz))
    total = sum(r[1] for r in rows)
    rows.append(("**total**", total))
    return table(["path", "bytes"], rows)


SECTION_FUNCS = {
    "summary": sec_summary, "symbols": sec_symbols, "wrappers": sec_wrappers, "typedefs": sec_typedefs,
    "files": sec_files, "mixed": sec_mixed, "members": sec_members, "natives": sec_natives, "locks": sec_locks,
    "strings": sec_strings, "clone": sec_clone, "roots": sec_roots, "build": sec_build, "deps": sec_deps,
}


BEGIN = "<!-- jsapi_inventory.py --section %s -->"
END = "<!-- /jsapi_inventory.py -->"


def update_doc(repo, path):
    """Replace every BEGIN(section) ... END block of `path` with freshly generated output."""
    with open(path, encoding="utf-8") as fh:
        doc = fh.read()
    rx = re.compile(r"<!-- jsapi_inventory\.py --section (\w+) -->\n.*?<!-- /jsapi_inventory\.py -->", re.S)
    done = []

    def sub(m):
        done.append(m.group(1))
        return BEGIN % m.group(1) + "\n" + SECTION_FUNCS[m.group(1)](repo) + "\n" + END

    doc = rx.sub(sub, doc)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print("updated %d block(s) in %s: %s" % (len(done), path, ", ".join(done)))


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=os.path.normpath(os.path.join(here, "..", "..", "..")))
    ap.add_argument("--section", action="append", choices=SECTIONS)
    ap.add_argument("--list-sections", action="store_true")
    ap.add_argument("--update", metavar="DOC", help="rewrite the generated blocks of DOC in place")
    a = ap.parse_args(argv)
    if a.list_sections:
        print("\n".join(SECTIONS))
        return 0
    repo = Repo(a.repo)
    if a.update:
        update_doc(repo, a.update)
        return 0
    for s in a.section or SECTIONS:
        print(BEGIN % s)
        print(SECTION_FUNCS[s](repo))
        print(END)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

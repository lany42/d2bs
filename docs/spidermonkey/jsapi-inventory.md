# SpiderMonkey coupling inventory (JSAPI)

Scope: a mechanical, source-verified inventory of every place the D2BS C++ code (repo root `*.cpp`/`*.h` and `Map/`; `sqlite3.*`, `StackWalker.*`, `dependencies/` and `doc/` excluded) touches the SpiderMonkey API that ships in `dependencies/include` (JS_VERSION 185, mozilla-release ~22, see `dependencies/include/jsversion.h:14`, `dependencies/libs/release/js_static.lib.desc`). It answers "what would have to change if SpiderMonkey were removed": which identifiers are used and where, how each source file is coupled, which natives contain game logic that must first be extracted into a JS-free layer for an RPC server to reuse, how the build depends on the engine, and the couplings that do not show up as plain JSAPI calls. Embedding mechanics (runtimes, contexts, script lifecycle, GC rules) are described in [embedding.md](embedding.md); per-function JS semantics live in [../js-api/](../js-api/README.md). The RPC-oriented synthesis built on these facts is [../rpc-considerations.md](../rpc-considerations.md). Every generated table below is produced by [`tools/jsapi_inventory.py`](tools/jsapi_inventory.py); every hand-written claim cites `File:line`.

## Contents

1. [Regenerating this document](#1-regenerating-this-document)
2. [Headline numbers](#2-headline-numbers)
3. [SpiderMonkey identifier inventory](#3-spidermonkey-identifier-inventory)
4. [Per-file coupling map](#4-per-file-coupling-map)
5. [Logic living inside natives](#5-logic-living-inside-natives)
6. [Build integration](#6-build-integration)
7. [Non-obvious couplings](#7-non-obvious-couplings)
8. [Findings](#8-findings)
9. [Legacy-doc discrepancies](#9-legacy-doc-discrepancies)
10. [Open questions](#10-open-questions)

---

## 1. Regenerating this document

```sh
# every section to stdout (Markdown)
python3 docs/spidermonkey/tools/jsapi_inventory.py
# a single section
python3 docs/spidermonkey/tools/jsapi_inventory.py --section natives
# list section names
python3 docs/spidermonkey/tools/jsapi_inventory.py --list-sections
# rewrite every generated block of this file in place
python3 docs/spidermonkey/tools/jsapi_inventory.py --update docs/spidermonkey/jsapi-inventory.md
```

Python 3 standard library only; a full run takes a few seconds. `--repo DIR` overrides the repository root (default: three directories above the script).

Generated blocks are delimited by `<!-- jsapi_inventory.py --section NAME -->` and `<!-- /jsapi_inventory.py -->`; anything outside those markers is hand-written and is not touched by `--update`.

Method and its limits (also in the script docstring):

| step | rule | consequence |
|---|---|---|
| preprocessing | comments, string literals, `#if 0` blocks and `#include` lines are blanked, line numbers preserved | counts are for live code; commented-out JSAPI (there is a lot, e.g. `JS_SuspendRequest`, `JS_ClearScope`) is not counted |
| what is a "SpiderMonkey symbol" | identifier matching `JS*`, `js*`, `*_TO_JSVAL`, `JS::*` **and** declared in `dependencies/include` as a function, macro, type, enum constant or extern const | local variables such as `jsunit` are excluded; a name that merely appears in a header (e.g. inside a macro body) does not qualify |
| what is a "D2BS wrapper" | name defined in `js32.h`, `js32.cpp`, `AutoRoot.h`, `AutoRoot.cpp` and described in the script's `WRAPPER_DESC` table | 5 wrappers shadow a SpiderMonkey name (macro or overload); they appear in both tables |
| member calls | `vp.setInt32(...)`, `buf->write(cx, ...)`, `opts.setUTF8(...)` are counted by regex as pseudo-symbols | these are C++ methods of `JS::MutableHandleValue`, `JSAutoStructuredCloneBuffer`, `JS::CompileOptions` |
| natives | bodies found by brace matching after `JSAPI_FUNC`/`JSAPI_PROP`/`JSAPI_STRICT_PROP`/`CLASS_CTOR`/`EMPTY_CTOR`, finalizer signatures `void f(JSFreeOp*, JSObject*)` | macro-generated signatures are counted once per definition |
| "logic lines" | non-blank body lines with no JSAPI symbol that are not just braces/`return JS_TRUE;` | a proxy for embedded non-binding logic, not a semantic measure |
| signatures (§4.3, §5.1 helpers) | regex over namespace/class scope after blanking preprocessor directives (with their `\` continuation lines); constructors, destructors and operators included | a signature split by a macro is missed |
| registration | a `JSClass` counts as registered when it appears in a `global_classes` row or as `&cls` in `BuildObject`/`JS_NewObject`/`JS_NewGlobalObject`/`JS_InitClass`; a spec table counts when a registered class or `BuildObject` call names it | unregistered ones are tagged "never registered" in §5.1 |
| leak scans (§5.4, §7.4) | after `new AutoCriticalRoom` / a stack-local `JS_Add*Root`, walk the following statements block by block and report every `return`/`THROW_*` reached before `delete cRoom` / the matching remove | branch-insensitive: an exit inside a block that ran the release is not reported, a release in a sibling branch is not credited |
| unset return value (§5.1) | a `JSAPI_FUNC` body with no `JS_SET_RVAL`/`THROW_WARNING`, or a `return JS_TRUE` textually before the first one | lower bound; sets inside branches are not path-checked |
| per-file class | manual table `CLASSIFICATION` in the script; the script warns when a file classed `d` has JSAPI references | see [§4.1](#41-classification-legend) |

---

## 2. Headline numbers

<!-- jsapi_inventory.py --section summary -->
| metric | value |
|---|---|
| source files scanned | 123 |
| total lines (scanned files) | 29043 |
| distinct SpiderMonkey symbols referenced | 198 |
| distinct D2BS wrapper symbols referenced (js32.h/js32.cpp/AutoRoot.*) | 50 |
| ... of which shadow a SpiderMonkey name (macro/overload) | 5 |
| member-call pseudo-symbols (handle/clone/options methods) | 6 distinct, 361 calls |
| total JSAPI symbol references (live code) | 7230 |
| files with >=1 JSAPI reference | 63 |
| files that #include js32.h/jsapi.h directly | 31 |
| files that reach jsapi.h transitively | 90 |
<!-- /jsapi_inventory.py -->

What the numbers mean for a removal:

* 44 binding files (class `a`, ~11 kLOC) exist only to expose JS; they disappear, but [§5](#5-logic-living-inside-natives) lists the game logic that lives inside them and must be moved first.
* 8 engine files (class `b`) are the SpiderMonkey host: `js32.*`, `AutoRoot.*`, `Script.*`, `ScriptEngine.*`. They also own the script thread model, the event queue and timers ([embedding.md §2](embedding.md#2-runtime--context--thread-topology), [§6](embedding.md#6-events-and-timers-integration)), which an RPC server needs in some other form.
* 11 non-binding files (class `c`) carry JS types in signatures or fields ([§4.3](#43-mixed-functions-js-types-in-gameinfra-signatures), [§4.4](#44-c-state-that-holds-js-values)).
* Even files with zero JSAPI references compile against `jsapi.h`: 90 of 123 files reach it through `D2BS.h -> ScreenHook.h -> Script.h -> js32.h` ([§4.2](#42-include-graph-exposure)).

---

## 3. SpiderMonkey identifier inventory

### 3.1 SpiderMonkey symbols

Every SpiderMonkey identifier used in live code, ordered by category, with the header where the bundled SpiderMonkey 22 declares it. "kind = ... + D2BS shadow" means `js32.h` redefines the name (see §3.2). The final rows are member-function pseudo-symbols. The per-category table at the end sums them.

<!-- jsapi_inventory.py --section symbols -->
| symbol | category | kind | declared (dependencies/include/...) | refs | files | files (refs) |
|---|---|---|---|---|---|---|
| `JS::RootedObject` | GC/rooting | type | js/RootingAPI.h:555 | 1 | 1 | js32.cpp(1) |
| `JS_AddNamedObjectRoot` | GC/rooting | function | jsapi.h:2370 | 1 | 1 | js32.h(1) |
| `JS_AddNamedScriptRoot` | GC/rooting | function | jsapi.h:2373 | 2 | 2 | Script.cpp(1), js32.cpp(1) |
| `JS_AddNamedStringRoot` | GC/rooting | function | jsapi.h:2367 | 1 | 1 | js32.h(1) |
| `JS_AddNamedValueRoot` | GC/rooting | function | jsapi.h:2361 | 3 | 3 | AutoRoot.cpp(1), Script.cpp(1), js32.h(1) |
| `JS_AddObjectRoot` | GC/rooting | function + D2BS shadow | jsapi.h:2350 | 4 | 3 | js32.h(2), JSGame.cpp(1), js32.cpp(1) |
| `JS_AddStringRoot` | GC/rooting | function + D2BS shadow | jsapi.h:2347 | 1 | 1 | js32.h(1) |
| `JS_AddValueRoot` | GC/rooting | function + D2BS shadow | jsapi.h:2344 | 14 | 3 | ScriptEngine.cpp(9), Script.cpp(3), js32.h(2) |
| `JS_GC` | GC/rooting | function | jsapi.h:2617 | 1 | 1 | JSCore.cpp(1) |
| `JS_GetGCParameter` | GC/rooting | function | jsapi.h:2736 | 3 | 2 | JSCore.cpp(2), JSScript.cpp(1) |
| `JS_MaybeGC` | GC/rooting | function | jsapi.h:2620 | 1 | 1 | ScriptEngine.cpp(1) |
| `JS_RemoveObjectRoot` | GC/rooting | function | jsapi.h:2382 | 3 | 3 | JSGame.cpp(1), js32.cpp(1), js32.h(1) |
| `JS_RemoveScriptRoot` | GC/rooting | function | jsapi.h:2385 | 1 | 1 | js32.cpp(1) |
| `JS_RemoveValueRoot` | GC/rooting | function | jsapi.h:2376 | 14 | 4 | ScriptEngine.cpp(9), Script.cpp(3), AutoRoot.cpp(1), js32.h(1) |
| `JS_SetGCParameter` | GC/rooting | function | jsapi.h:2733 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSGC_BYTES` | GC/rooting | enum constant | jsapi.h:2658 | 3 | 2 | JSCore.cpp(2), JSScript.cpp(1) |
| `JSGC_MODE` | GC/rooting | enum constant | jsapi.h:2667 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSGCCallback` | GC/rooting | type (fn ptr) | jsapi.h:1005 | 1 | 1 | ScriptEngine.h(1) |
| `JSGCStatus` | GC/rooting | type | jsapi.h:1002 | 1 | 1 | ScriptEngine.h(1) |
| `JSHandleId` | GC/rooting | type | jsapi.h:779 | 2 | 1 | js32.h(2) |
| `JSHandleObject` | GC/rooting | type | jsapi.h:776 | 2 | 1 | js32.h(2) |
| `JSMutableHandleValue` | GC/rooting | type | jsapi.h:785 | 2 | 1 | js32.h(2) |
| `JS_ConvertStub` | classes | function | jsapi.h:2982 | 26 | 2 | JSGlobalClasses.cpp(24), js32.h(2) |
| `JS_EnumerateStub` | classes | function | jsapi.h:2976 | 26 | 2 | JSGlobalClasses.cpp(24), js32.h(2) |
| `JS_GetInstancePrivate` | classes | function | jsapi.h:3096 | 49 | 6 | JSSQLite.cpp(16), JSFile.cpp(13), JSSandbox.cpp(8), JSScript.cpp(7), JSSocket.cpp(4), JSUnit.cpp(1) |
| `JS_GetPrivate` | classes | function + D2BS shadow | jsapi.h:3090 | 92 | 18 | JSUnit.cpp(23), JSGame.cpp(12), JSScreenHook.cpp(12), JSRoom.cpp(11), JSControl.cpp(7), JSDirectory.cpp(6), JSParty.cpp(3), JSProfile.cpp(3), JSArea.cpp(2), JSExits.cpp(2), JSPresetUnit.cpp(2), JSSQLite.cpp(2), js32.cpp(2), JSFile.cpp(1), JSSandbox.cpp(1), JSSocket.cpp(1), Script.cpp(1), js32.h(1) |
| `JS_GetReservedSlot` | classes | function | jsapi.h:3553 | 1 | 1 | JSGame.cpp(1) |
| `JS_InitClass` | classes | function | jsapi.h:3068 | 1 | 1 | ScriptEngine.cpp(1) |
| `JS_InstanceOf` | classes | function | jsapi.h:3084 | 1 | 1 | JSUnit.cpp(1) |
| `JS_New` | classes | function | jsapi.h:3181 | 1 | 1 | JSSQLite.cpp(1) |
| `JS_PropertyStub` | classes | function | jsapi.h:2970 | 75 | 2 | JSGlobalClasses.cpp(69), js32.h(6) |
| `JS_ResolveStub` | classes | function | jsapi.h:2979 | 26 | 2 | JSGlobalClasses.cpp(24), js32.h(2) |
| `JS_SetPrivate` | classes | function + D2BS shadow | jsapi.h:3093 | 27 | 13 | JSScreenHook.cpp(7), JSSQLite.cpp(3), JSUnit.cpp(3), js32.cpp(3), JSControl.cpp(2), JSProfile.cpp(2), JSArea.cpp(1), JSParty.cpp(1), JSPresetUnit.cpp(1), JSRoom.cpp(1), JSSandbox.cpp(1), JSScript.cpp(1), js32.h(1) |
| `JS_SetReservedSlot` | classes | function | jsapi.h:3556 | 1 | 1 | JSGame.cpp(1) |
| `JS_StrictPropertyStub` | classes | function | jsapi.h:2973 | 25 | 2 | JSGlobalClasses.cpp(23), js32.h(2) |
| `JSClass` | classes | type | jsapi.h:2780 | 55 | 6 | JSGlobalClasses.cpp(24), JSGlobalClasses.h(24), js32.h(4), ScriptEngine.cpp(1), ScriptEngine.h(1), js32.cpp(1) |
| `JSCLASS_GLOBAL_FLAGS` | classes | macro | jsapi.h:2870 | 1 | 1 | JSGlobalClasses.cpp(1) |
| `JSCLASS_HAS_PRIVATE` | classes | macro | jsapi.h:2804 | 22 | 1 | JSGlobalClasses.cpp(22) |
| `JSCLASS_HAS_RESERVED_SLOTS` | classes | macro | jsapi.h:2824 | 1 | 1 | JSGlobalClasses.cpp(1) |
| `JSCLASS_NO_OPTIONAL_MEMBERS` | classes | macro | jsapi.h:2888 | 2 | 2 | JSGlobalClasses.cpp(1), js32.h(1) |
| `JSFreeOp` | classes | type | jsapi.h:900 | 26 | 24 | JSSQLite.cpp(2), JSSQLite.h(2), JSArea.cpp(1), JSArea.h(1), JSControl.cpp(1), JSControl.h(1), JSDirectory.cpp(1), JSDirectory.h(1), JSExits.cpp(1), JSExits.h(1), JSFile.cpp(1), JSFile.h(1), JSPresetUnit.cpp(1), JSPresetUnit.h(1), JSProfile.cpp(1), JSProfile.h(1), JSSandbox.cpp(1), JSSandbox.h(1), JSScreenHook.cpp(1), JSScreenHook.h(1), JSSocket.cpp(1), JSSocket.h(1), JSUnit.cpp(1), JSUnit.h(1) |
| `JSPropertyOp` | classes | type (fn ptr) | jsapi.h:805 | 1 | 1 | JSGlobalClasses.cpp(1) |
| `JSStrictPropertyOp` | classes | type (fn ptr) | jsapi.h:815 | 1 | 1 | JSGlobalClasses.cpp(1) |
| `JSVAL_TO_PRIVATE` | classes | inline function | js/Value.h:1759 | 1 | 1 | JSGame.cpp(1) |
| `PRIVATE_TO_JSVAL` | classes | inline function | js/Value.h:1753 | 1 | 1 | JSGame.cpp(1) |
| `JS::Compile` | compile/execute | function | jsapi.h:3811 | 1 | 1 | js32.cpp(1) |
| `JS::CompileOptions` | compile/execute | type | jsapi.h:3777 | 1 | 1 | js32.cpp(1) |
| `JS_BufferIsCompilableUnit` | compile/execute | function | jsapi.h:3728 | 1 | 1 | JSSandbox.cpp(1) |
| `JS_CompileScript` | compile/execute | function | jsapi.h:3731 | 1 | 1 | Script.cpp(1) |
| `JS_EvaluateScript` | compile/execute | function | jsapi.h:3900 | 1 | 1 | JSSandbox.cpp(1) |
| `JS_EvaluateUCScript` | compile/execute | function | jsapi.h:3920 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_ExecuteScript` | compile/execute | function | jsapi.h:3887 | 3 | 2 | Script.cpp(2), JSSandbox.cpp(1) |
| `JSScript` | compile/execute | type | jspubtd.h:204 | 6 | 5 | js32.cpp(2), JSSandbox.cpp(1), Script.cpp(1), Script.h(1), js32.h(1) |
| `JS_ReportError` | errors/exceptions | function | jsapi.h:4558 | 23 | 6 | JSCore.cpp(14), File.cpp(2), JSDirectory.cpp(2), JSGame.cpp(2), JSMenu.cpp(2), js32.h(1) |
| `JS_ReportPendingException` | errors/exceptions | function | jsapi.h:4754 | 2 | 1 | Script.cpp(2) |
| `JS_ReportWarning` | errors/exceptions | function | jsapi.h:4592 | 2 | 2 | JSCore.cpp(1), js32.h(1) |
| `JS_SetErrorReporter` | errors/exceptions | function | jsapi.h:4665 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JSErrorReport` | errors/exceptions | type | jsapi.h:4616 | 2 | 2 | ScriptEngine.cpp(1), ScriptEngine.h(1) |
| `JSREPORT_IS_STRICT` | errors/exceptions | macro | jsapi.h:4658 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSREPORT_IS_WARNING` | errors/exceptions | macro | jsapi.h:4656 | 2 | 1 | ScriptEngine.cpp(2) |
| `JS_ARGV` | functions/natives | macro | js/CallArgs.h:319 | 620 | 19 | JSGame.cpp(158), JSScreenHook.cpp(93), JSUnit.cpp(91), JSCore.cpp(88), JSSQLite.cpp(35), JSProfile.cpp(26), JSFileTools.cpp(22), JSFile.cpp(18), JSRoom.cpp(17), JSMenu.cpp(15), JSHash.cpp(10), JSControl.cpp(8), JSDirectory.cpp(7), JSScript.cpp(7), JSParty.cpp(6), JSPresetUnit.cpp(6), JSSandbox.cpp(6), JSSocket.cpp(5), JSArea.cpp(2) |
| `JS_CallFunctionName` | functions/natives | function | jsapi.h:3976 | 2 | 1 | ScriptEngine.cpp(2) |
| `JS_CallFunctionValue` | functions/natives | function | jsapi.h:3980 | 16 | 3 | ScriptEngine.cpp(12), Map/Path/Reduction/JSPathReducer.h(3), Script.cpp(1) |
| `JS_DefineFunction` | functions/natives | function | jsapi.h:3701 | 1 | 1 | JSGame.cpp(1) |
| `JS_DefineFunctions` | functions/natives | function | jsapi.h:3698 | 3 | 3 | JSSandbox.cpp(1), ScriptEngine.cpp(1), js32.cpp(1) |
| `JS_FN` | functions/natives | macro | jsapi.h:3062 | 124 | 3 | JSGlobalFuncs.h(108), JSFile.h(12), JSSocket.h(4) |
| `JS_FS` | functions/natives | macro | jsapi.h:3060 | 80 | 11 | JSUnit.h(25), JSSQLite.h(14), JSRoom.h(9), JSFileTools.h(7), JSScript.h(6), JSScreenHook.h(5), JSControl.h(4), JSDirectory.h(4), JSSandbox.h(4), JSParty.h(1), JSProfile.h(1) |
| `JS_FS_END` | functions/natives | macro | jsapi.h:3053 | 21 | 14 | JSScreenHook.h(5), JSFile.h(2), JSSQLite.h(2), JSSocket.h(2), JSControl.h(1), JSDirectory.h(1), JSFileTools.h(1), JSGlobalFuncs.h(1), JSParty.h(1), JSProfile.h(1), JSRoom.h(1), JSSandbox.h(1), JSScript.h(1), JSUnit.h(1) |
| `JS_ObjectIsFunction` | functions/natives | function | jsapi.h:3677 | 1 | 1 | js32.h(1) |
| `JS_RVAL` | functions/natives | macro | js/CallArgs.h:320 | 3 | 2 | JSSQLite.cpp(2), JSUnit.cpp(1) |
| `JS_SET_RVAL` | functions/natives | macro | js/CallArgs.h:321 | 329 | 20 | JSGame.cpp(75), JSUnit.cpp(59), JSCore.cpp(40), JSRoom.cpp(35), JSSQLite.cpp(23), JSFile.cpp(14), JSControl.cpp(11), JSHash.cpp(10), JSScript.cpp(10), JSMenu.cpp(9), JSScreenHook.cpp(9), JSDirectory.cpp(5), JSParty.cpp(5), JSPresetUnit.cpp(5), JSSandbox.cpp(5), JSArea.cpp(4), JSFileTools.cpp(4), JSSocket.cpp(3), JSProfile.cpp(2), js32.h(1) |
| `JS_THIS` | functions/natives | inline function | js/CallArgs.h:328 | 1 | 1 | JSGame.cpp(1) |
| `JS_THIS_OBJECT` | functions/natives | macro | js/CallArgs.h:318 | 95 | 13 | JSUnit.cpp(22), JSFile.cpp(18), JSSQLite.cpp(14), JSRoom.cpp(11), JSScript.cpp(7), JSControl.cpp(6), JSDirectory.cpp(4), JSSandbox.cpp(4), JSParty.cpp(3), JSSocket.cpp(3), JSGame.cpp(1), JSProfile.cpp(1), JSScreenHook.cpp(1) |
| `JSFUN_STUB_GSOPS` | functions/natives | macro | jsapi.h:1428 | 1 | 1 | js32.h(1) |
| `JSFunction` | functions/natives | type | jspubtd.h:202 | 1 | 1 | JSGame.cpp(1) |
| `JSFunctionSpec` | functions/natives | type | jsapi.h:3041 | 30 | 18 | JSScreenHook.h(5), js32.h(4), JSFile.h(2), JSSQLite.h(2), JSSocket.h(2), ScriptEngine.cpp(2), ScriptEngine.h(2), JSControl.h(1), JSDirectory.h(1), JSFileTools.h(1), JSGlobalFuncs.h(1), JSParty.h(1), JSProfile.h(1), JSRoom.h(1), JSSandbox.h(1), JSScript.h(1), JSUnit.h(1), js32.cpp(1) |
| `JSNative` | functions/natives | type (fn ptr) | js/CallArgs.h:46 | 1 | 1 | js32.h(1) |
| `JS_DefineProperties` | objects/properties | function | jsapi.h:3191 | 1 | 1 | js32.cpp(1) |
| `JS_DefineProperty` | objects/properties | function | jsapi.h:3194 | 4 | 2 | JSSandbox.cpp(2), ScriptEngine.cpp(2) |
| `JS_DeleteProperty` | objects/properties | function | jsapi.h:3332 | 2 | 1 | JSSandbox.cpp(2) |
| `JS_GetArrayBufferByteLength` | objects/properties | function | jsfriendapi.h:1113 | 2 | 1 | JSCore.cpp(2) |
| `JS_GetArrayBufferData` | objects/properties | function | jsfriendapi.h:1125 | 2 | 1 | JSCore.cpp(2) |
| `JS_GetArrayLength` | objects/properties | function | jsapi.h:3428 | 2 | 2 | JSUnit.cpp(1), js32.h(1) |
| `JS_GetElement` | objects/properties | function | jsapi.h:3447 | 5 | 3 | JSUnit.cpp(2), Map/Path/Reduction/JSPathReducer.h(2), js32.h(1) |
| `JS_GetProperty` | objects/properties | function | jsapi.h:3303 | 13 | 4 | JSGame.cpp(6), JSScreenHook.cpp(4), Script.cpp(2), ScriptEngine.cpp(1) |
| `JS_HasProperty` | objects/properties | function | jsapi.h:3258 | 2 | 1 | JSSandbox.cpp(2) |
| `JS_IsArrayBufferObject` | objects/properties | function | jsfriendapi.h:1103 | 2 | 1 | JSCore.cpp(2) |
| `JS_IsArrayObject` | objects/properties | function | jsapi.h:3425 | 2 | 2 | JSUnit.cpp(1), js32.h(1) |
| `JS_LookupProperty` | objects/properties | function | jsapi.h:3264 | 4 | 1 | JSSandbox.cpp(4) |
| `JS_NewArrayObject` | objects/properties | function | jsapi.h:3422 | 33 | 12 | JSUnit.cpp(12), JSGame.cpp(4), JSRoom.cpp(4), JSControl.cpp(3), JSDirectory.cpp(2), JSFile.cpp(2), JSArea.cpp(1), JSPresetUnit.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), Map/Path/Reduction/JSPathReducer.h(1), js32.h(1) |
| `JS_NewObject` | objects/properties | function | jsapi.h:3146 | 7 | 4 | JSScreenHook.cpp(3), JSSandbox.cpp(2), JSGame.cpp(1), js32.cpp(1) |
| `JS_NewUint16Array` | objects/properties | function | jsfriendapi.h:938 | 1 | 1 | JSRoom.cpp(1) |
| `JS_NewUint8Array` | objects/properties | function | jsfriendapi.h:931 | 1 | 1 | ScriptEngine.cpp(1) |
| `JS_SetElement` | objects/properties | function | jsapi.h:3463 | 43 | 11 | JSUnit.cpp(20), JSGame.cpp(5), JSRoom.cpp(5), JSControl.cpp(4), JSDirectory.cpp(2), JSFile.cpp(2), JSArea.cpp(1), JSPresetUnit.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), ScriptEngine.cpp(1) |
| `JS_SetProperty` | objects/properties | function | jsapi.h:3326 | 28 | 6 | JSGame.cpp(8), JSScreenHook.cpp(8), JSSQLite.cpp(4), JSUnit.cpp(4), JSSandbox.cpp(2), Map/Path/Reduction/JSPathReducer.h(2) |
| `JSObject` | objects/properties | type | jspubtd.h:203 | 174 | 38 | JSUnit.cpp(27), js32.h(16), JSRoom.cpp(14), JSScreenHook.cpp(12), JSGame.cpp(10), JSSQLite.cpp(9), ScreenHook.h(7), js32.cpp(7), JSControl.cpp(6), JSDirectory.cpp(5), ScriptEngine.cpp(5), JSFile.cpp(4), JSPresetUnit.cpp(4), Map/Path/Reduction/JSPathReducer.h(4), Script.h(4), JSArea.cpp(3), JSSQLite.h(3), JSSandbox.cpp(3), JSScript.cpp(3), JSArea.h(2), JSCore.cpp(2), JSFile.h(2), JSProfile.cpp(2), JSSandbox.h(2), JSSocket.cpp(2), JSSocket.h(2), JSUnit.h(2), ScriptEngine.h(2), JSControl.h(1), JSDirectory.h(1), JSExits.cpp(1), JSExits.h(1), JSParty.cpp(1), JSPresetUnit.h(1), JSProfile.h(1), JSScreenHook.h(1), ScreenHook.cpp(1), Script.cpp(1) |
| `JSOP_NULLWRAPPER` | objects/properties | macro | jsapi.h:3021 | 248 | 14 | JSUnit.h(123), JSProfile.h(17), JSFile.h(14), JSParty.h(12), JSRoom.h(11), JSSQLite.h(11), JSControl.h(10), JSScreenHook.h(10), JSArea.h(9), JSPresetUnit.h(9), JSExits.h(8), JSScript.h(7), JSSocket.h(4), JSDirectory.h(3) |
| `JSOP_WRAPPER` | objects/properties | macro | jsapi.h:3020 | 330 | 14 | JSUnit.h(139), JSScreenHook.h(94), JSControl.h(16), JSFile.h(14), JSProfile.h(13), JSParty.h(10), JSRoom.h(9), JSArea.h(7), JSPresetUnit.h(7), JSSQLite.h(7), JSExits.h(6), JSScript.h(5), JSSocket.h(2), JSDirectory.h(1) |
| `JSPROP_ENUMERATE` | objects/properties | macro | jsapi.h:1409 | 7 | 3 | js32.h(4), JSSandbox.cpp(2), JSGame.cpp(1) |
| `JSPROP_PERMANENT` | objects/properties | macro | jsapi.h:1414 | 4 | 1 | js32.h(4) |
| `JSPROP_READONLY` | objects/properties | macro | jsapi.h:1410 | 2 | 1 | js32.h(2) |
| `JSPropertySpec` | objects/properties | type | jsapi.h:3028 | 30 | 18 | JSScreenHook.h(5), js32.h(4), JSProfile.h(2), JSSQLite.h(2), JSUnit.h(2), ScriptEngine.cpp(2), ScriptEngine.h(2), JSArea.h(1), JSControl.h(1), JSDirectory.h(1), JSExits.h(1), JSFile.h(1), JSParty.h(1), JSPresetUnit.h(1), JSRoom.h(1), JSScript.h(1), JSSocket.h(1), js32.cpp(1) |
| `JS_BeginRequest` | runtime/context/threads | function | jsapi.h:1818 | 107 | 20 | JSGame.cpp(22), JSUnit.cpp(18), ScriptEngine.cpp(14), JSCore.cpp(12), JSControl.cpp(7), JSRoom.cpp(7), JSFile.cpp(4), Script.cpp(4), JSPresetUnit.cpp(3), JSScreenHook.cpp(3), JSArea.cpp(2), JSDirectory.cpp(2), JSParty.cpp(2), AutoRoot.cpp(1), JSFileTools.cpp(1), JSMenu.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), JSSocket.cpp(1), js32.cpp(1) |
| `JS_DestroyContext` | runtime/context/threads | function | jsapi.h:1910 | 8 | 3 | JSSandbox.cpp(5), Script.cpp(2), ScriptEngine.cpp(1) |
| `JS_DestroyRuntime` | runtime/context/threads | function | jsapi.h:1803 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_EndRequest` | runtime/context/threads | function | jsapi.h:1821 | 151 | 19 | JSGame.cpp(34), JSUnit.cpp(25), JSCore.cpp(22), ScriptEngine.cpp(14), JSRoom.cpp(12), JSControl.cpp(9), JSScreenHook.cpp(6), Script.cpp(6), JSFile.cpp(4), JSPresetUnit.cpp(4), JSArea.cpp(3), JSParty.cpp(3), JSDirectory.cpp(2), JSMenu.cpp(2), AutoRoot.cpp(1), JSFileTools.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), js32.cpp(1) |
| `JS_GetContextPrivate` | runtime/context/threads | function | jsapi.h:1916 | 20 | 5 | JSCore.cpp(11), JSScreenHook.cpp(5), ScriptEngine.cpp(2), D2Helpers.cpp(1), JSScript.cpp(1) |
| `JS_GetGlobalObject` | runtime/context/threads | function | jsapi.h:2135 | 16 | 2 | ScriptEngine.cpp(14), Script.cpp(2) |
| `JS_GetOptions` | runtime/context/threads | function | jsapi.h:2017 | 2 | 1 | JSCore.cpp(2) |
| `JS_GetRuntime` | runtime/context/threads | function | jsapi.h:1812 | 3 | 3 | JSCore.cpp(1), Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_InitStandardClasses` | runtime/context/threads | function | jsapi.h:2148 | 2 | 2 | JSSandbox.cpp(1), ScriptEngine.cpp(1) |
| `JS_IsInRequest` | runtime/context/threads | function | jsapi.h:1824 | 1 | 1 | Script.cpp(1) |
| `JS_NewContext` | runtime/context/threads | function | jsapi.h:1907 | 2 | 2 | JSSandbox.cpp(1), Script.cpp(1) |
| `JS_NewGlobalObject` | runtime/context/threads | function | jsapi.h:3142 | 1 | 1 | ScriptEngine.cpp(1) |
| `JS_NewRuntime` | runtime/context/threads | function | jsapi.h:1800 | 1 | 1 | Script.cpp(1) |
| `JS_NO_HELPER_THREADS` | runtime/context/threads | enum constant | jsapi.h:1795 | 1 | 1 | Script.cpp(1) |
| `JS_SetContextCallback` | runtime/context/threads | function | jsapi.h:1904 | 1 | 1 | Script.cpp(1) |
| `JS_SetContextPrivate` | runtime/context/threads | function | jsapi.h:1919 | 1 | 1 | Script.cpp(1) |
| `JS_SetNativeStackQuota` | runtime/context/threads | function | jsapi.h:2771 | 1 | 1 | Script.cpp(1) |
| `JS_SetOperationCallback` | runtime/context/threads | function | jsapi.h:4024 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_SetOptions` | runtime/context/threads | function | jsapi.h:2020 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_SetVersion` | runtime/context/threads | function | jsapi.h:1937 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_ShutDown` | runtime/context/threads | function | jsapi.h:1806 | 1 | 1 | ScriptEngine.cpp(1) |
| `JS_ToggleOptions` | runtime/context/threads | function | jsapi.h:2023 | 2 | 1 | JSCore.cpp(2) |
| `JS_TriggerOperationCallback` | runtime/context/threads | function | jsapi.h:4030 | 2 | 2 | Script.cpp(1), Script.h(1) |
| `JSContext` | runtime/context/threads | type | jspubtd.h:174 | 80 | 25 | js32.h(29), ScriptEngine.cpp(7), ScriptEngine.h(7), JSUnit.cpp(4), Script.h(4), js32.cpp(4), AutoRoot.h(2), Events.h(2), File.cpp(2), File.h(2), Map/Path/Reduction/JSPathReducer.h(2), Script.cpp(2), AutoRoot.cpp(1), D2Helpers.cpp(1), D2Helpers.h(1), Events.cpp(1), JSFile.h(1), JSSQLite.h(1), JSSandbox.cpp(1), JSSandbox.h(1), JSSocket.h(1), JSUnit.h(1), MPQStats.cpp(1), MPQStats.h(1), ScreenHook.cpp(1) |
| `JSCONTEXT_DESTROY` | runtime/context/threads | enum constant | jsapi.h:980 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSCONTEXT_NEW` | runtime/context/threads | enum constant | jsapi.h:979 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSOPTION_ASMJS` | runtime/context/threads | macro | jsapi.h:2012 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSOPTION_ION` | runtime/context/threads | macro | jsapi.h:2011 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSOPTION_METHODJIT` | runtime/context/threads | macro | jsapi.h:1996 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSOPTION_STRICT` | runtime/context/threads | macro | jsapi.h:1952 | 8 | 3 | JSCore.cpp(6), Script.cpp(1), ScriptEngine.cpp(1) |
| `JSOPTION_TYPE_INFERENCE` | runtime/context/threads | macro | jsapi.h:2005 | 1 | 1 | ScriptEngine.cpp(1) |
| `JSOPTION_VAROBJFIX` | runtime/context/threads | macro | jsapi.h:1954 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JSRuntime` | runtime/context/threads | type | jspubtd.h:186 | 6 | 3 | ScriptEngine.h(3), Script.h(2), ScriptEngine.cpp(1) |
| `JSVERSION_LATEST` | runtime/context/threads | enum constant | jspubtd.h:90 | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_EncodeStringToBuffer` | strings/encoding | function | jsapi.h:4281 | 2 | 1 | ScriptEngine.cpp(2) |
| `JS_EncodeStringToUTF8` | strings/encoding | function | jsapi.h:4262 | 35 | 9 | JSCore.cpp(9), JSHash.cpp(5), JSSQLite.cpp(5), JSSandbox.cpp(5), JSUnit.cpp(4), JSGame.cpp(3), JSSocket.cpp(2), File.cpp(1), JSParty.cpp(1) |
| `JS_free` | strings/encoding | function | jsapi.h:2295 | 48 | 9 | JSCore.cpp(10), JSSQLite.cpp(10), JSSandbox.cpp(9), JSUnit.cpp(6), JSGame.cpp(5), JSHash.cpp(5), File.cpp(1), JSParty.cpp(1), JSSocket.cpp(1) |
| `JS_GetStringCharsZ` | strings/encoding | function | jsapi.h:4170 | 66 | 17 | JSProfile.cpp(13), JSCore.cpp(9), JSFileTools.cpp(9), JSMenu.cpp(8), JSHash.cpp(5), JSDirectory.cpp(4), JSScreenHook.cpp(4), JSControl.cpp(2), JSGame.cpp(2), JSSandbox.cpp(2), JSUnit.cpp(2), JSFile.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), Script.cpp(1), ScriptEngine.cpp(1), js32.h(1) |
| `JS_InternString` | strings/encoding | function | jsapi.h:4093 | 14 | 4 | JSUnit.cpp(7), JSHash.cpp(5), JSArea.cpp(1), JSSQLite.cpp(1) |
| `JS_InternUCString` | strings/encoding | function | jsapi.h:4108 | 10 | 7 | JSUnit.cpp(3), JSScreenHook.cpp(2), JSControl.cpp(1), JSCore.cpp(1), JSDirectory.cpp(1), JSScript.cpp(1), JSSocket.cpp(1) |
| `JS_NewStringCopyZ` | strings/encoding | function | jsapi.h:4084 | 22 | 8 | JSUnit.cpp(7), JSHash.cpp(5), ScriptEngine.cpp(3), JSCore.cpp(2), MPQStats.cpp(2), JSGame.cpp(1), JSParty.cpp(1), js32.h(1) |
| `JS_NewUCStringCopyN` | strings/encoding | function | jsapi.h:4099 | 2 | 2 | JSFile.cpp(1), JSFileTools.cpp(1) |
| `JS_NewUCStringCopyZ` | strings/encoding | function | jsapi.h:4102 | 32 | 10 | JSSQLite.cpp(5), JSDirectory.cpp(4), JSFile.cpp(4), JSProfile.cpp(4), JSUnit.cpp(4), JSGame.cpp(3), ScriptEngine.cpp(3), JSControl.cpp(2), JSCore.cpp(2), js32.h(1) |
| `jschar` | strings/encoding | type | jspubtd.h:72 | 6 | 2 | JSMenu.cpp(3), js32.h(3) |
| `JSAutoStructuredCloneBuffer` | structured clone | type | jsapi.h:4416 | 13 | 7 | JSCore.cpp(3), Script.h(3), Events.cpp(2), JSScript.cpp(2), Script.cpp(1), ScriptEngine.cpp(1), ScriptEngine.h(1) |
| `BOOLEAN_TO_JSVAL` | values/conversion | inline function | js/Value.h:1726 | 28 | 10 | JSGame.cpp(9), JSCore.cpp(4), JSFileTools.cpp(3), JSUnit.cpp(3), JSMenu.cpp(2), JSRoom.cpp(2), JSSQLite.cpp(2), JSSandbox.cpp(1), ScriptEngine.cpp(1), js32.h(1) |
| `DOUBLE_TO_JSVAL` | values/conversion | inline function | js/Value.h:1648 | 1 | 1 | js32.h(1) |
| `INT_TO_JSVAL` | values/conversion | inline function | js/Value.h:1627 | 94 | 14 | JSUnit.cpp(26), JSRoom.cpp(18), JSGame.cpp(16), JSScreenHook.cpp(8), Map/Path/Reduction/JSPathReducer.h(7), JSCore.cpp(4), JSControl.cpp(3), MPQStats.cpp(3), JSFile.cpp(2), JSSQLite.cpp(2), Script.cpp(2), JSMenu.cpp(1), ScriptEngine.cpp(1), js32.h(1) |
| `JS::Value` | values/conversion | type | js/Value.h:857 | 2 | 1 | ScriptEngine.cpp(2) |
| `JS_ConvertArguments` | values/conversion | function | jsapi.h:1513 | 13 | 5 | JSGame.cpp(5), JSCore.cpp(3), JSMenu.cpp(3), JSParty.cpp(1), JSUnit.cpp(1) |
| `JS_ConvertValue` | values/conversion | function | jsapi.h:1523 | 6 | 4 | JSCore.cpp(3), JSGame.cpp(1), Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_FALSE` | values/conversion | macro | jstypes.h:193 | 111 | 18 | JSScreenHook.cpp(18), JSCore.cpp(15), JSDirectory.cpp(13), JSGame.cpp(13), JSSandbox.cpp(12), ScriptEngine.cpp(7), JSControl.cpp(6), JSFile.cpp(4), JSFileTools.cpp(4), JSMenu.cpp(4), JSUnit.cpp(3), Script.cpp(3), File.cpp(2), JSArea.cpp(2), JSSQLite.cpp(2), JSSocket.cpp(1), ScreenHook.cpp(1), js32.h(1) |
| `JS_IdToValue` | values/conversion | function | jsapi.h:2953 | 32 | 15 | JSScreenHook.cpp(10), JSSandbox.cpp(4), JSControl.cpp(2), JSFile.cpp(2), JSProfile.cpp(2), JSSQLite.cpp(2), JSUnit.cpp(2), JSArea.cpp(1), JSDirectory.cpp(1), JSExits.cpp(1), JSParty.cpp(1), JSPresetUnit.cpp(1), JSRoom.cpp(1), JSScript.cpp(1), JSSocket.cpp(1) |
| `JS_NumberValue` | values/conversion | inline function | jsapi.h:1204 | 28 | 6 | ScriptEngine.cpp(16), JSSQLite.cpp(5), JSGame.cpp(2), JSUnit.cpp(2), MPQStats.cpp(2), JSCore.cpp(1) |
| `JS_TRUE` | values/conversion | macro | jstypes.h:192 | 530 | 22 | JSUnit.cpp(127), JSGame.cpp(96), JSRoom.cpp(51), JSCore.cpp(41), JSScreenHook.cpp(32), JSControl.cpp(29), JSSandbox.cpp(25), JSSQLite.cpp(24), JSScript.cpp(16), JSFile.cpp(14), JSMenu.cpp(12), JSHash.cpp(10), JSParty.cpp(10), JSFileTools.cpp(8), JSSocket.cpp(8), JSDirectory.cpp(7), JSPresetUnit.cpp(7), JSArea.cpp(4), JSProfile.cpp(4), JSExits.cpp(2), js32.h(2), ScriptEngine.cpp(1) |
| `JS_TypeOfValue` | values/conversion | function | jsapi.h:1761 | 4 | 3 | JSSQLite.cpp(2), File.cpp(1), JSControl.cpp(1) |
| `JS_ValueToECMAInt32` | values/conversion | function | jsapi.h:1610 | 24 | 4 | JSGame.cpp(19), JSControl.cpp(2), JSUnit.cpp(2), JSArea.cpp(1) |
| `JS_ValueToECMAUint32` | values/conversion | function | jsapi.h:1741 | 31 | 6 | JSUnit.cpp(11), JSCore.cpp(7), JSRoom.cpp(6), JSControl.cpp(3), JSGame.cpp(2), JSPresetUnit.cpp(2) |
| `JS_ValueToInt32` | values/conversion | function | jsapi.h:1749 | 22 | 7 | JSScreenHook.cpp(8), JSSandbox.cpp(4), JSFile.cpp(3), JSUnit.cpp(3), File.cpp(2), JSGame.cpp(1), JSSocket.cpp(1) |
| `JS_ValueToNumber` | values/conversion | function | jsapi.h:1541 | 2 | 1 | File.cpp(2) |
| `JS_ValueToObject` | values/conversion | function | jsapi.h:1526 | 5 | 4 | JSCore.cpp(2), JSRoom.cpp(1), JSSQLite.cpp(1), JSScreenHook.cpp(1) |
| `JS_ValueToString` | values/conversion | function | jsapi.h:1535 | 33 | 10 | JSHash.cpp(10), JSUnit.cpp(6), JSGame.cpp(5), JSCore.cpp(4), JSDirectory.cpp(2), JSScreenHook.cpp(2), JSControl.cpp(1), JSMenu.cpp(1), Script.cpp(1), ScriptEngine.cpp(1) |
| `JS_ValueToUint16` | values/conversion | function | jsapi.h:1755 | 5 | 1 | JSGame.cpp(5) |
| `JSBool` | values/conversion | type | jstypes.h:191 | 30 | 12 | js32.h(8), ScriptEngine.cpp(5), JSSandbox.cpp(3), JSFile.h(2), JSSQLite.h(2), JSSocket.h(2), JSUnit.h(2), ScriptEngine.h(2), D2Helpers.cpp(1), JSCore.cpp(1), JSMenu.cpp(1), js32.cpp(1) |
| `JSID_IS_STRING` | values/conversion | inline function | jsapi.h:1238 | 1 | 1 | JSControl.cpp(1) |
| `JSID_IS_VOID` | values/conversion | inline function | jsapi.h:1344 | 1 | 1 | JSControl.cpp(1) |
| `JSID_IS_ZERO` | values/conversion | inline function | jsapi.h:1251 | 1 | 1 | JSControl.cpp(1) |
| `JSID_TO_INT` | values/conversion | inline function | jsapi.h:1276 | 1 | 1 | JSControl.cpp(1) |
| `JSType` | values/conversion | type | jspubtd.h:103 | 1 | 1 | JSControl.cpp(1) |
| `JSTYPE_BOOLEAN` | values/conversion | enum constant | jspubtd.h:100 | 3 | 2 | JSSQLite.cpp(2), File.cpp(1) |
| `JSTYPE_NULL` | values/conversion | enum constant | jspubtd.h:101 | 1 | 1 | File.cpp(1) |
| `JSTYPE_NUMBER` | values/conversion | enum constant | jspubtd.h:99 | 3 | 2 | JSSQLite.cpp(2), File.cpp(1) |
| `JSTYPE_STRING` | values/conversion | enum constant | jspubtd.h:98 | 9 | 6 | JSCore.cpp(3), JSSQLite.cpp(2), File.cpp(1), JSGame.cpp(1), Script.cpp(1), ScriptEngine.cpp(1) |
| `JSTYPE_VOID` | values/conversion | enum constant | jspubtd.h:95 | 3 | 2 | JSSQLite.cpp(2), File.cpp(1) |
| `jsval` | values/conversion | type | js/Value.h:1594 | 209 | 37 | ScriptEngine.cpp(33), js32.h(24), JSUnit.cpp(22), JSScreenHook.cpp(20), JSGame.cpp(13), Map/Path/Reduction/JSPathReducer.h(13), Script.cpp(9), JSSQLite.cpp(7), JSControl.cpp(6), JSRoom.cpp(6), JSSandbox.cpp(6), AutoRoot.h(5), ScreenHook.h(5), JSFile.cpp(4), JSCore.cpp(3), JSDirectory.cpp(3), Script.h(3), AutoRoot.cpp(2), Events.h(2), JSArea.cpp(2), JSPresetUnit.cpp(2), JSProfile.cpp(2), JSScript.cpp(2), ScreenHook.cpp(2), Events.cpp(1), File.cpp(1), File.h(1), JSExits.cpp(1), JSFile.h(1), JSParty.cpp(1), JSSQLite.h(1), JSSocket.cpp(1), JSSocket.h(1), JSUnit.h(1), MPQStats.cpp(1), MPQStats.h(1), js32.cpp(1) |
| `JSVAL_FALSE` | values/conversion | extern const | jsapi.h:1199 | 53 | 12 | JSGame.cpp(19), JSUnit.cpp(12), JSCore.cpp(5), JSPresetUnit.cpp(3), JSRoom.cpp(3), Map/Path/Reduction/JSPathReducer.h(3), JSArea.cpp(2), JSParty.cpp(2), JSControl.cpp(1), JSSandbox.cpp(1), JSSocket.cpp(1), js32.h(1) |
| `JSVAL_IS_BOOLEAN` | values/conversion | inline function | js/Value.h:1713 | 28 | 10 | JSGame.cpp(7), JSFile.cpp(5), JSScreenHook.cpp(5), ScriptEngine.cpp(5), JSCore.cpp(1), JSFileTools.cpp(1), JSRoom.cpp(1), JSSQLite.cpp(1), JSScript.cpp(1), JSUnit.cpp(1) |
| `JSVAL_IS_DOUBLE` | values/conversion | inline function | js/Value.h:1633 | 4 | 2 | File.cpp(2), JSSQLite.cpp(2) |
| `JSVAL_IS_INT` | values/conversion | inline function | js/Value.h:1614 | 126 | 14 | JSGame.cpp(42), JSScreenHook.cpp(34), JSUnit.cpp(17), JSSQLite.cpp(7), JSProfile.cpp(5), JSCore.cpp(4), JSRoom.cpp(4), JSSandbox.cpp(4), JSControl.cpp(3), File.cpp(2), JSArea.cpp(1), JSFile.cpp(1), JSParty.cpp(1), JSScript.cpp(1) |
| `JSVAL_IS_NULL` | values/conversion | inline function | js/Value.h:1602 | 24 | 5 | JSUnit.cpp(12), JSCore.cpp(7), JSGame.cpp(3), Script.cpp(1), ScriptEngine.cpp(1) |
| `JSVAL_IS_NUMBER` | values/conversion | inline function | js/Value.h:1673 | 23 | 3 | JSUnit.cpp(11), JSCore.cpp(7), JSGame.cpp(5) |
| `JSVAL_IS_PRIMITIVE` | values/conversion | inline function | js/Value.h:1732 | 2 | 2 | js32.cpp(1), js32.h(1) |
| `JSVAL_IS_STRING` | values/conversion | inline function | js/Value.h:1679 | 53 | 16 | JSCore.cpp(10), JSFileTools.cpp(9), JSSandbox.cpp(7), JSUnit.cpp(5), JSGame.cpp(4), JSSQLite.cpp(4), JSMenu.cpp(3), JSScreenHook.cpp(2), JSSocket.cpp(2), JSControl.cpp(1), JSDirectory.cpp(1), JSFile.cpp(1), JSParty.cpp(1), JSProfile.cpp(1), JSScript.cpp(1), ScriptEngine.cpp(1) |
| `JSVAL_IS_VOID` | values/conversion | inline function | js/Value.h:1608 | 9 | 5 | ScreenHook.cpp(4), JSSandbox.cpp(2), JSUnit.cpp(1), Script.cpp(1), ScriptEngine.cpp(1) |
| `JSVAL_NULL` | values/conversion | extern const | jsapi.h:1196 | 38 | 9 | JSCore.cpp(15), JSScript.cpp(6), JSMenu.cpp(5), JSGame.cpp(4), JSSQLite.cpp(3), JSRoom.cpp(2), AutoRoot.h(1), JSUnit.cpp(1), Map/Path/Reduction/JSPathReducer.h(1) |
| `JSVAL_TO_BOOLEAN` | values/conversion | inline function | js/Value.h:1719 | 33 | 13 | JSFile.cpp(5), JSScreenHook.cpp(5), ScriptEngine.cpp(5), JSGame.cpp(4), JSSQLite.cpp(3), File.cpp(2), JSCore.cpp(2), Map/Path/Reduction/JSPathReducer.h(2), JSFileTools.cpp(1), JSRoom.cpp(1), JSScript.cpp(1), JSUnit.cpp(1), js32.h(1) |
| `JSVAL_TO_DOUBLE` | values/conversion | inline function | js/Value.h:1639 | 3 | 2 | JSSQLite.cpp(2), js32.h(1) |
| `JSVAL_TO_INT` | values/conversion | inline function | js/Value.h:1620 | 127 | 19 | JSScreenHook.cpp(36), JSGame.cpp(24), JSUnit.cpp(18), JSSQLite.cpp(9), JSProfile.cpp(8), JSCore.cpp(6), JSPresetUnit.cpp(5), JSRoom.cpp(4), JSFile.cpp(3), js32.h(3), JSScript.cpp(2), Map/Path/Reduction/JSPathReducer.h(2), JSArea.cpp(1), JSControl.cpp(1), JSDirectory.cpp(1), JSExits.cpp(1), JSMenu.cpp(1), JSParty.cpp(1), JSSocket.cpp(1) |
| `JSVAL_TO_OBJECT` | values/conversion | inline function | js/Value.h:1698 | 34 | 9 | JSGame.cpp(19), JSUnit.cpp(5), JSScreenHook.cpp(2), Map/Path/Reduction/JSPathReducer.h(2), ScriptEngine.cpp(2), JSParty.cpp(1), JSRoom.cpp(1), Script.cpp(1), js32.h(1) |
| `JSVAL_TO_STRING` | values/conversion | inline function | js/Value.h:1685 | 68 | 14 | JSCore.cpp(15), JSProfile.cpp(13), JSFileTools.cpp(9), JSMenu.cpp(7), JSSandbox.cpp(7), JSSQLite.cpp(6), JSDirectory.cpp(2), JSSocket.cpp(2), ScriptEngine.cpp(2), File.cpp(1), JSFile.cpp(1), JSParty.cpp(1), JSScript.cpp(1), js32.h(1) |
| `JSVAL_TRUE` | values/conversion | extern const | jsapi.h:1200 | 42 | 8 | JSGame.cpp(16), JSUnit.cpp(10), JSSQLite.cpp(7), JSCore.cpp(5), JSDirectory.cpp(1), JSFile.cpp(1), JSRoom.cpp(1), JSScript.cpp(1) |
| `JSVAL_VOID` | values/conversion | extern const | jsapi.h:1201 | 49 | 16 | JSScreenHook.cpp(11), JSUnit.cpp(9), MPQStats.cpp(7), JSGame.cpp(5), JSControl.cpp(3), JSRoom.cpp(2), JSSandbox.cpp(2), ScreenHook.cpp(2), JSArea.cpp(1), JSExits.cpp(1), JSMenu.cpp(1), JSParty.cpp(1), JSProfile.cpp(1), JSScript.cpp(1), Script.cpp(1), js32.h(1) |
| `JSVAL_ZERO` | values/conversion | extern const | jsapi.h:1197 | 2 | 2 | JSUnit.cpp(1), Map/Path/Reduction/JSPathReducer.h(1) |
| `OBJECT_TO_JSVAL` | values/conversion | inline function | js/Value.h:1705 | 93 | 17 | JSUnit.cpp(16), JSRoom.cpp(13), JSFile.cpp(10), JSGame.cpp(10), JSScreenHook.cpp(9), JSSQLite.cpp(7), JSControl.cpp(6), JSDirectory.cpp(4), JSArea.cpp(3), JSPresetUnit.cpp(3), JSScript.cpp(3), JSParty.cpp(2), Map/Path/Reduction/JSPathReducer.h(2), ScriptEngine.cpp(2), JSProfile.cpp(1), JSSandbox.cpp(1), JSSocket.cpp(1) |
| `STRING_TO_JSVAL` | values/conversion | inline function | js/Value.h:1692 | 50 | 13 | JSHash.cpp(10), ScriptEngine.cpp(6), JSCore.cpp(5), JSUnit.cpp(5), JSDirectory.cpp(4), JSFile.cpp(4), JSGame.cpp(4), JSSQLite.cpp(4), JSControl.cpp(2), MPQStats.cpp(2), js32.h(2), JSFileTools.cpp(1), JSSocket.cpp(1) |
| `UINT_TO_JSVAL` | values/conversion | inline function | js/Value.h:1665 | 4 | 3 | js32.h(2), JSCore.cpp(1), ScriptEngine.cpp(1) |
| `JS::CompileOptions::setUTF8/setFileAndLine` | compile/execute | member function | jsapi.h (struct CompileOptions) | 2 | 1 | js32.cpp(2) |
| `JS::MutableHandleValue::is*/to*` | values/conversion | member function | js/Value.h (ValueOperations) | 99 | 4 | JSScreenHook.cpp(74), JSUnit.cpp(17), JSControl.cpp(6), JSFile.cpp(2) |
| `JS::MutableHandleValue::set*/get` | values/conversion | member function | js/RootingAPI.h, js/Value.h (MutableValueOperations) | 254 | 15 | JSUnit.cpp(88), JSScreenHook.cpp(57), JSFile.cpp(20), JSControl.cpp(14), JSSandbox.cpp(12), JSParty.cpp(10), JSProfile.cpp(9), JSRoom.cpp(8), JSArea.cpp(7), JSExits.cpp(7), JSPresetUnit.cpp(7), JSSQLite.cpp(7), JSScript.cpp(5), JSSocket.cpp(2), JSDirectory.cpp(1) |
| `JSAutoStructuredCloneBuffer::clear` | structured clone | member function | jsapi.h (class JSAutoStructuredCloneBuffer) | 1 | 1 | ScriptEngine.cpp(1) |
| `JSAutoStructuredCloneBuffer::read` | structured clone | member function | jsapi.h (class JSAutoStructuredCloneBuffer) | 2 | 2 | Script.cpp(1), ScriptEngine.cpp(1) |
| `JSAutoStructuredCloneBuffer::write` | structured clone | member function | jsapi.h (class JSAutoStructuredCloneBuffer) | 3 | 3 | Events.cpp(1), JSCore.cpp(1), JSScript.cpp(1) |

Per category (SpiderMonkey symbols incl. member-call pseudo-symbols; wrappers from js32.h/AutoRoot.h):

| category | SM symbols | SM refs | D2BS wrappers | wrapper refs | files touched |
|---|---|---|---|---|---|
| structured clone | 4 | 19 | 0 | 0 | 7 |
| debugging | 0 | 0 | 2 | 7 | 1 |
| errors/exceptions | 7 | 34 | 2 | 269 | 24 |
| strings/encoding | 10 | 237 | 0 | 0 | 22 |
| GC/rooting | 22 | 63 | 8 | 109 | 20 |
| runtime/context/threads | 34 | 435 | 0 | 0 | 40 |
| compile/execute | 9 | 18 | 1 | 6 | 6 |
| classes | 23 | 462 | 17 | 243 | 41 |
| functions/natives | 17 | 1329 | 5 | 711 | 49 |
| objects/properties | 25 | 949 | 6 | 277 | 41 |
| values/conversion | 53 | 2452 | 8 | 104 | 42 |
| other | 0 | 0 | 1 | 5 | 1 |
<!-- /jsapi_inventory.py -->

Reading notes (hand-written):

* `JS_ARGV`, `JS_SET_RVAL`, `JS_THIS_OBJECT`, `JS_RVAL`, `JS_THIS` (`dependencies/include/js/CallArgs.h:318-328`) are the pre-`CallArgs` native calling convention; 1 329 references in the "functions/natives" category are almost all of these plus `JS_FN`/`JS_FS`. They have no counterpart in an RPC layer: they are argument plumbing.
* The property-op signature `JSAPI_PROP` uses the partial rooting API (`JSHandleObject`, `JSHandleId`, `JSMutableHandleValue`, `js32.h:141-142`); property getters write results through `vp.set*()` (254 calls) and setters read through `vp.is*()/to*()` (99 calls). No other part of the code uses `JS::Rooted*` except one `JS::RootedObject` in `js32.cpp:51`.
* Property specs pass a per-property `tinyid` (`JSPropertySpec::tinyid` is `int8_t`, `dependencies/include/jsapi.h:3030`). The getter switches on `JSVAL_TO_INT(ID)` (e.g. `JSUnit.cpp:55`). The `me` ids run from 90 to 125 (`JSUnit.h:121-158`), close to the `int8_t` ceiling of 127.
* `JS_BeginRequest`/`JS_EndRequest` (107/151 references) are scattered through natives, but `dependencies/include/js-config.h:16` leaves `JS_THREADSAFE` undefined, so the bundled engine is a non-thread-safe build. See [Open questions](#10-open-questions).

### 3.2 D2BS wrapper layer (`js32.h`, `js32.cpp`, `AutoRoot.h`, `AutoRoot.cpp`)

<!-- jsapi_inventory.py --section wrappers -->
| wrapper | category | defined | kind | refs | use | meaning |
|---|---|---|---|---|---|---|
| `AutoRoot` | GC/rooting | AutoRoot.h:8 | type | 28 | used in 4 files | ref-counted rooted jsval holder (Take/Release); stored in listener lists |
| `jsrefcount` | values/conversion | js32.h:29 | typedef | 1 | unused | typedef unsigned int (legacy JSAPI type) |
| `jsdouble` | values/conversion | js32.h:30 | typedef | 21 | used in 8 files | typedef double (legacy JSAPI type) |
| `jsint` | values/conversion | js32.h:31 | typedef | 49 | used in 5 files | typedef int32_t (legacy JSAPI type) |
| `jsuint` | values/conversion | js32.h:32 | typedef | 4 | used in 1 files | typedef uint32_t (legacy JSAPI type) |
| `EXPORT` | other | js32.h:36 | macro | 5 | internal only | __declspec(dllexport) when EXPORTING |
| `NUM` | debugging | js32.h:43 | macro | 2 | internal only | stringize helper for NAME |
| `NAME` | debugging | js32.h:44 | macro | 5 | internal only | builds "file:line -> var" root names |
| `JS_AddValueRoot` | GC/rooting | js32.h:45 | macro | 14 | used in 2 files | macro -> JS_AddNamedValueRoot(cx, vp, NAME(..)) (shadows jsapi function) |
| `JS_AddStringRoot` | GC/rooting | js32.h:46 | macro | 1 | unused | macro -> JS_AddNamedStringRoot (shadows jsapi) |
| `JS_AddObjectRoot` | GC/rooting | js32.h:47 | macro | 4 | used in 1 files | macro -> JS_AddNamedObjectRoot (shadows jsapi) |
| `JS_AddGCThingRoot` | GC/rooting | js32.h:48 | macro | 1 | unused | macro -> JS_AddNamedGCThingRoot (not declared by SpiderMonkey 22 headers) |
| `JS_GetPrivate` | classes | js32.h:50 | function | 92 | used in 16 files | overload JS_GetPrivate(cx, obj) -> JS_GetPrivate(obj) |
| `JS_SetPrivate` | classes | js32.h:51 | function | 27 | used in 11 files | overload JS_SetPrivate(cx, obj, p) -> JS_SetPrivate(obj, p) |
| `JSVAL_IS_OBJECT` | values/conversion | js32.h:52 | function | 24 | used in 8 files | function re-creating the removed macro as !JSVAL_IS_PRIMITIVE(v); false for null (null is primitive in SM22, dependencies/include/js/Value.h:196, :460) |
| `JSClassSpec` | classes | js32.h:55 | type | 8 | used in 3 files | class registration row {classp, proto, ctor, argc, methods, props, static methods, static props} |
| `JSModuleSpec` | classes | js32.h:66 | type | 1 | unused | module row {name, classes, static methods, static props} |
| `JSAutoRoot` | GC/rooting | js32.h:73 | type | 7 | internal only | RAII rooted jsval (heap jsval + JS_AddValueRoot) |
| `JS_AddRoot` | GC/rooting | js32.h:96 | macro | 23 | used in 12 files | macro -> JS_AddObjectRoot(cx, (JSObject**)vp) -- also used on jsval slots |
| `JS_RemoveRoot` | GC/rooting | js32.h:97 | macro | 31 | used in 13 files | macro -> JS_RemoveObjectRoot(cx, (JSObject**)vp); (note trailing ';') |
| `JSVAL_IS_FUNCTION` | functions/natives | js32.h:98 | macro | 23 | used in 5 files | macro: !JSVAL_IS_PRIMITIVE(v) && JS_ObjectIsFunction(cx, obj) |
| `JSPROP_PERMANENT_VAR` | objects/properties | js32.h:100 | macro | 210 | used in 14 files | JSPROP_READONLY\|JSPROP_ENUMERATE\|JSPROP_PERMANENT |
| `JSPROP_STATIC_VAR` | objects/properties | js32.h:101 | macro | 62 | used in 4 files | JSPROP_ENUMERATE\|JSPROP_PERMANENT |
| `CLASS_CTOR` | classes | js32.h:103 | macro | 17 | used in 15 files | declares JSBool name_ctor(JSContext*, uint, jsval*) |
| `BuildObject` | classes | js32.h:110 | function | 49 | used in 16 files | JS_NewObject + JS_DefineFunctions/Properties + JS_SetPrivate inside a request |
| `JS_CompileFile` | compile/execute | js32.h:112 | function | 6 | used in 2 files | reads file, strips UTF-8 BOM, JS::Compile with UTF-8 option (name mimics removed jsapi) |
| `THROW_ERROR` | errors/exceptions | js32.h:113 | macro | 212 | used in 19 files | JS_ReportError(cx, msg); return JS_FALSE; |
| `THROW_WARNING` | errors/exceptions | js32.h:118 | macro | 57 | used in 5 files | JS_ReportWarning; rval = false; return JS_TRUE; |
| `JS_DefineClasses` | classes | js32.h:126 | function | 1 | unused | EXPORT declaration only -- never defined |
| `JS_GetProtoForClass` | classes | js32.h:127 | function | 1 | unused | EXPORT declaration only -- never defined |
| `JS_NewObjectWithProto` | classes | js32.h:128 | function | 1 | unused | EXPORT declaration only -- never defined |
| `JSPROP_DEFAULT` | objects/properties | js32.h:130 | macro | 1 | unused | JSPROP_ENUMERATE\|JSPROP_PERMANENT (unparenthesised) |
| `JSPROP_STATIC` | objects/properties | js32.h:131 | macro | 1 | unused | JSPROP_ENUMERATE\|JSPROP_PERMANENT\|JSPROP_READONLY (unparenthesised) |
| `JSAPI_FUNC` | functions/natives | js32.h:133 | macro | 414 | used in 38 files | JSBool name(JSContext* cx, uint argc, jsval* vp) -- JSNative signature |
| `FUNCTION_FLAGS` | functions/natives | js32.h:134 | macro | 205 | used in 14 files | JSFUN_STUB_GSOPS |
| `EMPTY_CTOR` | classes | js32.h:136 | macro | 15 | used in 14 files | ctor that throws "Invalid Operation" |
| `JSAPI_PROP` | functions/natives | js32.h:141 | macro | 48 | used in 31 files | JSBool name(cx, JSHandleObject, JSHandleId, JSMutableHandleValue) -- JSPropertyOp |
| `JSAPI_STRICT_PROP` | functions/natives | js32.h:142 | macro | 21 | used in 12 files | as JSAPI_PROP plus JSBool strict -- JSStrictPropertyOp |
| `JS_PS` | objects/properties | js32.h:146 | macro | 2 | internal only | {name, id, flags, getter, setter} initializer; unused (live tables write JSOP_WRAPPER(...) rows directly) |
| `JS_PS_END` | objects/properties | js32.h:149 | macro | 1 | unused | JS_PS(0,0,0,0,0) |
| `JS_CS` | classes | js32.h:151 | macro | 1 | unused | JSClassSpec initializer |
| `JS_CS_END` | classes | js32.h:154 | macro | 1 | unused | {0} |
| `JS_MS` | classes | js32.h:157 | macro | 1 | unused | JSModuleSpec initializer |
| `JS_MS_END` | classes | js32.h:160 | macro | 1 | unused | {0,0,0,0} |
| `JSCLASS_SPEC` | classes | js32.h:163 | macro | 25 | used in 1 files | fills JSClass hooks add..finalize, NULL checkAccess/call/hasInstance, ctor as construct, NULL trace |
| `JSCLASS_DEFAULT_WITH_CTOR` | classes | js32.h:166 | macro | 1 | unused | JSCLASS_SPEC with stubs (references JS_FinalizeStub, absent in SM22) |
| `JSCLASS_DEFAULT_STANDARD_MEMBERS` | classes | js32.h:169 | macro | 1 | unused | stub members (references JS_FinalizeStub, absent in SM22) |
| `Converter` | values/conversion | js32.h:173 | type | 3 | internal only | template jsval<->C++ converters for JS_ArrayToVector/JS_VectorToArray |
| `JS_ArrayToVector` | values/conversion | js32.h:216 | template function | 1 | unused | JS array -> std::vector<T> |
| `JS_VectorToArray` | values/conversion | js32.h:231 | template function | 1 | unused | std::vector<T> -> JS array |

| call | args | resolves to | occurrences (incl. declarations) |
|---|---|---|---|
| `JS_GetPrivate` | 1 | SpiderMonkey JS_GetPrivate(obj) | 14 |
| `JS_GetPrivate` | 2 | D2BS shim JS_GetPrivate(cx, obj) | 78 |
| `JS_SetPrivate` | 2 | SpiderMonkey JS_SetPrivate(obj, p) | 9 |
| `JS_SetPrivate` | 3 | D2BS shim JS_SetPrivate(cx, obj, p) | 18 |

JSAPI-pattern identifiers in live code that the bundled SpiderMonkey 22 headers do not declare:

| identifier | files (refs) |
|---|---|
| `JS_AddNamedGCThingRoot` | js32.h(1) |
| `JS_FinalizeStub` | js32.h(2) |
<!-- /jsapi_inventory.py -->

Notes:

* `JSVAL_IS_OBJECT` is a D2BS **function** (`js32.cpp:62`) that re-creates a macro SpiderMonkey removed. `JS_CompileFile` (`js32.cpp:29`) has the name of a removed JSAPI function but is D2BS code (it reads the file, blanks a UTF-8 BOM (`js32.cpp:43-47`) and calls `JS::Compile` with `setUTF8(true)` (`js32.cpp:51-54`)).
* `JS_AddRoot`/`JS_RemoveRoot` (`js32.h:96-97`) cast the address to `JSObject**` and call the object-root API. They are also applied to `jsval` slots (`ScreenHook.cpp:307`, `Map/Path/Reduction/JSPathReducer.h:24-26`), and `Script.cpp:467` uses `JS_RemoveRoot` to remove a value root that was added with `JS_AddNamedValueRoot` at `Script.cpp:459` (inside `RunCommandThread`, which nothing starts: its only `CreateThread` is commented out at `Script.cpp:89`). On a 32-bit little-endian build the first four bytes of a `jsval` are the payload and the next four the tag (`dependencies/include/js/Value.h:243-264`), so an object root on a `jsval` slot sees the object pointer only while the slot holds an object. That is an accident of the layout.
* Dead wrapper code: `JSModuleSpec`, `JSAutoRoot`, `JS_PS*`, `JS_CS*`, `JS_MS*`, `JSCLASS_DEFAULT_*`, `Converter`, `JS_ArrayToVector`, `JS_VectorToArray` are unused. `JS_DefineClasses`, `JS_GetProtoForClass`, `JS_NewObjectWithProto` are declared `EXPORT` (`js32.h:126-128`) but never defined. `JSCLASS_DEFAULT_WITH_CTOR`/`..._STANDARD_MEMBERS` reference `JS_FinalizeStub`, and `JS_AddGCThingRoot` references `JS_AddNamedGCThingRoot`; neither name is declared by the bundled headers (last table above). They compile only because nobody expands them.
* `JSClassSpec.ctor` and `.argc` in `global_classes` (`JSGlobalClasses.cpp:143-168`) are ignored: `ScriptEngine::InitClass` passes `classp->construct` (filled by `JSCLASS_SPEC`, `js32.h:163-164`) and `nargs = 0` to `JS_InitClass` (`ScriptEngine.cpp:230-233`).

### 3.3 Generic typedefs that leak from `js32.h`

`js32.h` is also the place that defines general-purpose integer typedefs and legacy JSAPI aliases (`js32.h:26-33`). Game/infra code uses them, so deleting `js32.h` breaks files that never call SpiderMonkey:

<!-- jsapi_inventory.py --section typedefs -->
| typedef | defined | refs | files | non-binding files using it |
|---|---|---|---|---|
| `uint` | js32.h:26 | 155 | 25 | Core.cpp, D2Handlers.cpp, D2Helpers.cpp, D2Helpers.h, Events.cpp, Events.h, Map/Path/Reduction/TeleportPathReducer.h, ScreenHook.cpp, ScreenHook.h, dde.cpp |
| `uint32` | js32.h:27 | 52 | 9 | - |
| `int32` | js32.h:28 | 25 | 11 | File.cpp |
| `uint16` | js32.h:33 | 3 | 2 | - |
<!-- /jsapi_inventory.py -->

---

## 4. Per-file coupling map

### 4.1 Classification legend

| class | meaning | action on removal |
|---|---|---|
| a | pure binding layer: natives, spec tables, private-data structs that exist only for JS | delete, after extracting logic listed in §5 |
| b | engine core: SpiderMonkey host (runtime/context/compile/run, listener registry, event dispatch, rooting helpers) | replace by the RPC host's own session/event/timer machinery |
| c | mixed: game/infra code with JS types in signatures or fields | split: keep the game part, move the JS marshalling into the binding layer (or delete) |
| d | JS-free game/infra code. "engine API refs" > 0 marks **engine clients**: no JSAPI symbol, but they call `ScriptEngine::*`, `Script*`, `Genhook::*` or the `Events.h` fan-out functions | keep; re-target the engine calls to the RPC layer |

### 4.2 Include-graph exposure

The "reaches jsapi.h" column is the transitive closure of local `#include "..."` edges. Main paths:

* `D2BS.h:16` includes `ScreenHook.h`; `ScreenHook.h:7-8` includes `Script.h` and `ScriptEngine.h`; `Script.h:8` includes `js32.h`; `js32.h:13-14` includes `dependencies\include\jsapi.h` and `jsfriendapi.h`. Every file that includes `D2BS.h` (the `Vars` global) therefore compiles against SpiderMonkey.
* `D2Helpers.h:6`, `File.h:4` and `MPQStats.h:5` include `js32.h` directly, only to declare the JS-typed helpers listed in §4.3.
* `Helpers.h:6` includes `Script.h`.
* `Events.h` uses `JSContext`/`jsval` (`Events.h:17`, `Events.h:72-73`) without including any JS header; it compiles only because each of its includers has already pulled in `js32.h`: `Script.h:8` before `Script.h:12`, `ScriptEngine.h:9` before `ScriptEngine.cpp:14`, `Script.h` before `D2Handlers.cpp:13` and `D2NetHandlers.cpp:8`, `JSCore.h:3` before `JSCore.cpp:15`.
* `D2BS.h:6-8` and `js32.h:4-6` both `#define XP_WIN`, a SpiderMonkey platform macro.

<!-- jsapi_inventory.py --section files -->
| file | LOC | code LOC | JSAPI refs | distinct syms | direct JS include | reaches jsapi.h | engine API refs | class | note |
|---|---|---|---|---|---|---|---|---|---|
| ArrayEx.h | 437 | 323 | 0 | 0 |  |  |  | d |  |
| AutoRoot.cpp | 35 | 28 | 15 | 7 |  | yes |  | b | AutoRoot impl; default cx = ScriptEngine::GetGlobalContext() (always NULL) |
| AutoRoot.h | 35 | 29 | 18 | 4 | yes | yes |  | b | AutoRoot class (rooted jsval holder) |
| CommandLine.cpp | 96 | 56 | 0 | 0 |  | yes |  | d |  |
| CommandLine.h | 33 | 11 | 0 | 0 |  |  |  | d |  |
| Console.cpp | 255 | 205 | 0 | 0 |  | yes |  | d | includes ScriptEngine.h only; commands go through Helpers.cpp ProcessCommand |
| Console.h | 55 | 44 | 0 | 0 |  | yes |  | d |  |
| Constants.h | 873 | 678 | 0 | 0 |  |  |  | d |  |
| Control.cpp | 588 | 481 | 0 | 0 |  | yes |  | d |  |
| Control.h | 15 | 11 | 0 | 0 |  |  |  | d |  |
| Core.cpp | 235 | 162 | 0 | 0 |  | yes |  | d |  |
| Core.h | 18 | 11 | 0 | 0 |  |  |  | d |  |
| CriticalSections.h | 55 | 46 | 0 | 0 |  | yes |  | d | AutoCriticalRoom = Vars.cGameLoopSection (taken by natives) |
| D2BS.cpp | 179 | 124 | 0 | 0 |  | yes | 2 | d | engine client: Genhook::Initialize/Destroy (ScriptEngine via Helpers/D2Handlers) |
| D2BS.h | 131 | 105 | 0 | 0 |  | yes |  | d | defines XP_WIN (SpiderMonkey platform macro); includes ScreenHook.h -> Script.h -> js32.h |
| D2Handlers.cpp | 564 | 428 | 0 | 0 |  | yes | 40 | d | engine client: game-thread loop, input/packet hooks fire Events.h functions, Genhook click/draw |
| D2Handlers.h | 37 | 33 | 0 | 0 |  |  |  | d |  |
| D2Helpers.cpp | 1036 | 806 | 3 | 3 |  | yes | 3 | c | SetSkill pumps the calling script's event queue via JS_GetContextPrivate |
| D2Helpers.h | 118 | 96 | 1 | 1 | yes | yes |  | c | SetSkill(JSContext*, ..); includes js32.h |
| D2Intercepts.cpp | 420 | 339 | 0 | 0 |  | yes |  | d |  |
| D2Intercepts.h | 27 | 23 | 0 | 0 |  |  |  | d |  |
| D2Loader.h | 32 | 22 | 0 | 0 |  |  |  | d |  |
| D2NetHandlers.cpp | 178 | 128 | 0 | 0 |  | yes | 7 | d | engine client: packet handlers fire Events.h functions |
| D2NetHandlers.h | 11 | 8 | 0 | 0 |  |  |  | d |  |
| D2Ptrs.h | 516 | 296 | 0 | 0 |  |  |  | d |  |
| D2Skills.h | 232 | 226 | 0 | 0 |  |  |  | d |  |
| D2Structs.h | 803 | 724 | 0 | 0 |  |  |  | d |  |
| dde.cpp | 102 | 84 | 0 | 0 |  | yes | 1 | d | engine client: DDE execute -> ScriptEngine::RunCommand |
| dde.h | 8 | 5 | 0 | 0 |  |  |  | d |  |
| Events.cpp | 355 | 300 | 4 | 3 |  | yes | 49 | c | game->script event fan-out; scriptmsg structured clone |
| Events.h | 80 | 67 | 4 | 2 |  |  | 18 | c | ScriptBroadcastEvent(JSContext*, uint, jsval*); BCastEventHelper |
| File.cpp | 266 | 152 | 29 | 19 |  | yes |  | c | jsval serialisation + JS_ReportError inside file helpers |
| File.h | 12 | 8 | 3 | 2 | yes | yes |  | c | writeValue(.., JSContext*, jsval, ..), fileOpenRelScript(.., JSContext*) |
| Game.cpp | 40 | 27 | 0 | 0 |  | yes |  | d |  |
| Game.h | 6 | 3 | 0 | 0 |  |  |  | d |  |
| Hash.cpp | 158 | 127 | 0 | 0 |  | yes |  | d |  |
| Hash.h | 18 | 14 | 0 | 0 |  |  |  | d |  |
| Helpers.cpp | 512 | 415 | 0 | 0 |  | yes | 16 | d | engine client: StartScript -> ScriptEngine::CompileFile; Startup/RunCommand/StopAll/FlushCache/GetCount |
| Helpers.h | 32 | 26 | 0 | 0 |  | yes | 1 | d | engine client: includes Script.h (-> js32.h); declares StartScript(.., ScriptState) |
| js32.cpp | 70 | 51 | 39 | 26 | yes | yes |  | b | BuildObject, JS_CompileFile, JS_Get/SetPrivate(cx,..) shims |
| js32.h | 243 | 178 | 240 | 103 | yes | yes |  | b | jsapi.h/jsfriendapi.h entry point; wrapper macros; generic typedefs (uint, uint32, ...) |
| JSArea.cpp | 140 | 112 | 51 | 28 |  | yes |  | a |  |
| JSArea.h | 32 | 21 | 30 | 9 | yes | yes |  | a |  |
| JSControl.cpp | 354 | 285 | 160 | 43 |  | yes |  | a |  |
| JSControl.h | 66 | 49 | 58 | 15 | yes | yes |  | a |  |
| JSCore.cpp | 717 | 567 | 478 | 58 |  | yes |  | a |  |
| JSCore.h | 40 | 37 | 36 | 1 | yes | yes |  | a |  |
| JSDirectory.cpp | 230 | 156 | 102 | 31 |  | yes |  | a |  |
| JSDirectory.h | 42 | 23 | 25 | 13 | yes | yes |  | a |  |
| JSExits.cpp | 44 | 36 | 12 | 10 |  | yes |  | a |  |
| JSExits.h | 31 | 22 | 25 | 8 | yes | yes |  | a |  |
| JSFile.cpp | 587 | 479 | 194 | 36 |  | yes |  | a |  |
| JSFile.h | 113 | 65 | 92 | 18 | yes | yes |  | a |  |
| JSFileTools.cpp | 245 | 158 | 100 | 17 |  | yes |  | a |  |
| JSFileTools.h | 41 | 19 | 24 | 6 | yes | yes |  | a |  |
| JSGame.cpp | 1485 | 1154 | 864 | 66 |  | yes |  | a |  |
| JSGame.h | 50 | 44 | 40 | 1 | yes | yes |  | a |  |
| JSGlobalClasses.cpp | 202 | 96 | 239 | 14 | yes | yes |  | a |  |
| JSGlobalClasses.h | 33 | 26 | 25 | 2 | yes | yes |  | a |  |
| JSGlobalFuncs.h | 79 | 46 | 218 | 4 | yes | yes |  | a |  |
| JSHash.cpp | 160 | 125 | 100 | 12 |  | yes |  | a |  |
| JSHash.h | 14 | 11 | 10 | 1 | yes | yes |  | a |  |
| JSMenu.cpp | 183 | 138 | 103 | 21 |  | yes |  | a |  |
| JSMenu.h | 17 | 13 | 9 | 1 | yes | yes |  | a |  |
| JSParty.cpp | 152 | 116 | 61 | 31 |  | yes |  | a |  |
| JSParty.h | 29 | 20 | 41 | 11 | yes | yes |  | a |  |
| JSPresetUnit.cpp | 209 | 163 | 65 | 25 |  | yes |  | a |  |
| JSPresetUnit.h | 44 | 34 | 30 | 9 | yes | yes |  | a |  |
| JSProfile.cpp | 162 | 116 | 102 | 24 |  | yes |  | a |  |
| JSProfile.h | 54 | 38 | 56 | 13 | yes | yes |  | a |  |
| JSRoom.cpp | 579 | 466 | 269 | 37 |  | yes |  | a |  |
| JSRoom.h | 58 | 46 | 62 | 11 | yes | yes |  | a |  |
| JSSandbox.cpp | 233 | 200 | 170 | 48 |  | yes |  | a |  |
| JSSandbox.h | 29 | 20 | 23 | 10 |  | yes |  | a |  |
| JSScreenHook.cpp | 840 | 737 | 437 | 38 |  | yes |  | a |  |
| JSScreenHook.h | 124 | 84 | 196 | 13 | yes | yes |  | a |  |
| JSScript.cpp | 228 | 179 | 98 | 36 |  | yes |  | a |  |
| JSScript.h | 42 | 31 | 42 | 11 | yes | yes |  | a |  |
| JSSocket.cpp | 173 | 126 | 58 | 28 |  | yes |  | a |  |
| JSSocket.h | 34 | 19 | 35 | 17 | yes | yes |  | a |  |
| JSSQLite.cpp | 589 | 476 | 312 | 53 |  | yes |  | a |  |
| JSSQLite.h | 65 | 50 | 88 | 16 | yes | yes |  | a |  |
| JSUnit.cpp | 1981 | 1500 | 774 | 67 |  | yes |  | a |  |
| JSUnit.h | 309 | 285 | 481 | 18 | yes | yes |  | a |  |
| MapHeader.h | 11 | 3 | 0 | 0 |  | yes |  | d |  |
| Matrix.h | 267 | 184 | 0 | 0 |  |  |  | d |  |
| MPQStats.cpp | 286 | 243 | 19 | 8 |  | yes |  | c | FillBaseStat writes jsval results |
| MPQStats.h | 2124 | 2110 | 2 | 2 | yes | yes |  | c | FillBaseStat(JSContext*, jsval*, ..) overload; includes js32.h |
| Offset.cpp | 124 | 95 | 0 | 0 |  | yes |  | d |  |
| Offset.h | 35 | 30 | 0 | 0 |  |  |  | d |  |
| Patch.h | 57 | 36 | 0 | 0 |  | yes |  | d |  |
| Profile.cpp | 297 | 248 | 0 | 0 |  | yes |  | d |  |
| Profile.h | 69 | 49 | 1 | 1 |  | yes |  | c | `friend JSAPI_PROP(profile_getProperty)` inside class Profile |
| resource.h | 15 | 8 | 0 | 0 |  |  |  | d |  |
| Room.cpp | 110 | 75 | 0 | 0 |  | yes |  | d |  |
| Room.h | 9 | 5 | 0 | 0 |  |  |  | d |  |
| ScreenHook.cpp | 458 | 352 | 19 | 10 |  | yes | 18 | c | hook click/hover dispatch builds AutoRoot + Event |
| ScreenHook.h | 413 | 347 | 12 | 2 |  | yes | 9 | c | Genhook stores JSObject* self + jsval clicked/hovered |
| Script.cpp | 484 | 359 | 87 | 51 |  | yes |  | b | per-script runtime/context, compile/run main(), include, listener registry |
| Script.h | 218 | 184 | 19 | 8 | yes | yes |  | b | Script class + Event struct (holds JSContext/JSRuntime/JSScript/AutoRoot/clone buffers) |
| ScriptEngine.cpp | 840 | 651 | 240 | 78 |  | yes |  | b | context callback (globals/classes/me), operation callback, ExecScriptEvent dispatch, timers |
| ScriptEngine.h | 88 | 65 | 25 | 12 | yes | yes |  | b | engine facade; ScriptEngine::runtime/context statics (never assigned) |
| stringhash.cpp | 60 | 46 | 0 | 0 |  |  |  | d |  |
| stringhash.h | 5 | 2 | 0 | 0 |  |  |  | d |  |
| SyncObj.h | 45 | 22 | 0 | 0 |  |  |  | d |  |
| TimedAlloc.h | 124 | 99 | 0 | 0 |  |  |  | d |  |
| Unit.cpp | 280 | 124 | 0 | 0 |  | yes |  | d |  |
| Unit.h | 11 | 8 | 0 | 0 |  |  |  | d |  |
| Map/BlankMap.h | 51 | 41 | 0 | 0 |  |  |  | d |  |
| Map/Map.h | 54 | 41 | 0 | 0 |  |  |  | d |  |
| Map/Diablo_II/ActMap.cpp | 734 | 593 | 0 | 0 |  | yes |  | d |  |
| Map/Diablo_II/ActMap.h | 163 | 122 | 0 | 0 |  | yes |  | d |  |
| Map/Diablo_II/LevelMap.cpp | 704 | 541 | 0 | 0 |  | yes |  | d |  |
| Map/Diablo_II/LevelMap.h | 153 | 118 | 0 | 0 |  | yes |  | d |  |
| Map/Diablo_II/Points.cpp | 0 | 0 | 0 | 0 |  |  |  | d |  |
| Map/Diablo_II/Points.h | 0 | 0 | 0 | 0 |  |  |  | d |  |
| Map/Path/AStarPath.h | 205 | 157 | 0 | 0 |  |  |  | d |  |
| Map/Path/Path.h | 26 | 16 | 0 | 0 |  |  |  | d |  |
| Map/Path/Reduction/JSPathReducer.h | 100 | 79 | 55 | 19 | yes | yes |  | a | path reducer calling JS callbacks (reject/reduce/mutate) |
| Map/Path/Reduction/NoPathReducer.h | 62 | 50 | 0 | 0 |  |  |  | d |  |
| Map/Path/Reduction/PathReducer.h | 24 | 19 | 0 | 0 |  |  |  | d |  |
| Map/Path/Reduction/TeleportPathReducer.h | 218 | 125 | 0 | 0 |  | yes |  | d |  |
| Map/Path/Reduction/WalkPathReducer.h | 276 | 105 | 0 | 0 |  | yes |  | d |  |

| class | files | LOC |
|---|---|---|
| a | 44 | 10973 |
| b | 8 | 2020 |
| c | 11 | 5224 |
| d | 60 | 10826 |
<!-- /jsapi_inventory.py -->

### 4.3 Mixed functions (JS types in game/infra signatures)

Every function, constructor or operator declared or defined in class `b`/`c` files whose signature mentions a JS type (`js32.h:174-211` are the operators of the unused `Converter` template):

<!-- jsapi_inventory.py --section mixed -->
| file | line | def/decl | signature | JS types |
|---|---|---|---|---|
| AutoRoot.cpp | 4 | def | `AutoRoot::AutoRoot(JSContext* ncx, jsval nvar)` | JSContext, jsval |
| AutoRoot.cpp | 7 | def | `AutoRoot::AutoRoot(jsval nvar)` | jsval |
| AutoRoot.h | 13 | decl | `AutoRoot(const AutoRoot&)` | AutoRoot |
| AutoRoot.h | 14 | decl | `AutoRoot& operator=(const AutoRoot&)` | AutoRoot |
| AutoRoot.h | 19 | decl | `AutoRoot(JSContext* cx, jsval var)` | JSContext, jsval |
| AutoRoot.h | 20 | decl | `AutoRoot(jsval var)` | jsval |
| AutoRoot.h | 24 | def | `jsval* value()` | jsval |
| AutoRoot.h | 27 | def | `jsval operator*()` | jsval |
| AutoRoot.h | 30 | def | `bool operator==(AutoRoot& other)` | AutoRoot |
| D2Helpers.cpp | 238 | def | `BOOL SetSkill(JSContext* cx, WORD wSkillId, BOOL bLeft, DWORD dwItemId)` | JSContext |
| D2Helpers.h | 43 | decl | `BOOL SetSkill(JSContext* cx, WORD wSkillId, BOOL bLeft, DWORD dwItemId = 0xFFFFFFFF)` | JSContext |
| Events.cpp | 168 | def | `void ScriptBroadcastEvent(JSContext* cx, uint argc, jsval* args)` | JSContext, jsval |
| Events.h | 17 | decl | `void ScriptBroadcastEvent(JSContext* cx, uint argc, jsval* argv)` | JSContext, jsval |
| File.cpp | 49 | def | `bool writeValue(FILE* fptr, JSContext* cx, jsval value, bool isBinary, bool locking)` | JSContext, jsval |
| File.cpp | 188 | def | `FILE* fileOpenRelScript(const wchar_t* filename, const wchar_t* mode, JSContext* cx)` | JSContext |
| File.h | 7 | decl | `bool writeValue(FILE* fptr, JSContext* cx, jsval value, bool isBinary, bool locking)` | JSContext, jsval |
| File.h | 8 | decl | `FILE* fileOpenRelScript(const wchar_t* filename, const wchar_t* mode, JSContext* cx)` | JSContext |
| js32.cpp | 8 | def | `JSObject* BuildObject(JSContext* cx, JSClass* classp, JSFunctionSpec* funcs, JSPropertySpec* props, void* priv, JSObject* proto, JSObject* parent)` | JSClass, JSContext, JSObject |
| js32.cpp | 29 | def | `JSScript* JS_CompileFile(JSContext* cx, JSObject* globalObject, std::wstring fileName)` | JSContext, JSObject, JSScript |
| js32.cpp | 62 | def | `JSBool JSVAL_IS_OBJECT(jsval v)` | JSBool, jsval |
| js32.cpp | 65 | def | `void* JS_GetPrivate(JSContext* cx, JSObject* obj)` | JSContext, JSObject |
| js32.cpp | 68 | def | `void JS_SetPrivate(JSContext* cx, JSObject* obj, void* data)` | JSContext, JSObject |
| js32.h | 50 | decl | `void* JS_GetPrivate(JSContext* cx, JSObject* obj)` | JSContext, JSObject |
| js32.h | 51 | decl | `void JS_SetPrivate(JSContext* cx, JSObject* obj, void* data)` | JSContext, JSObject |
| js32.h | 52 | decl | `JSBool JSVAL_IS_OBJECT(jsval v)` | JSBool, jsval |
| js32.h | 82 | def | `JSAutoRoot(JSContext* cx, jsval value)` | JSContext, jsval |
| js32.h | 90 | def | `jsval* get()` | jsval |
| js32.h | 110 | decl | `JSObject* BuildObject(JSContext* cx, JSClass* classp = NULL, JSFunctionSpec* funcs = NULL, JSPropertySpec* props = NULL, void* priv = NULL, JSObject* proto = NULL, JSObject* parent = NULL)` | JSClass, JSContext, JSObject |
| js32.h | 112 | decl | `JSScript* JS_CompileFile(JSContext* cx, JSObject* globalObject, std::wstring fileName)` | JSContext, JSObject, JSScript |
| js32.h | 126 | decl | `EXPORT void JS_DefineClasses(JSContext* cx, JSObject* obj, JSClassSpec* classes)` | JSContext, JSObject |
| js32.h | 127 | decl | `EXPORT JSObject* JS_GetProtoForClass(JSContext* cx, JSClass* classp)` | JSClass, JSContext, JSObject |
| js32.h | 128 | decl | `EXPORT JSObject* JS_NewObjectWithProto(JSContext* cx, JSObject* obj, JSClassSpec* classp, JSClassSpec* proto, JSObject* parent)` | JSContext, JSObject |
| js32.h | 174 | def | `jsval operator()(JSContext* cx, const jschar* c)` | JSContext, jschar, jsval |
| js32.h | 177 | def | `jsval operator()(JSContext* cx, unsigned char c)` | JSContext, jsval |
| js32.h | 180 | def | `jsval operator()(JSContext* cx, char* c)` | JSContext, jsval |
| js32.h | 183 | def | `jsval operator()(JSContext* cx, int i)` | JSContext, jsval |
| js32.h | 186 | def | `jsval operator()(JSContext* cx, double d)` | JSContext, jsval |
| js32.h | 189 | def | `jsval operator()(JSContext* cx, uint32 ui)` | JSContext, jsval |
| js32.h | 192 | def | `jsval operator()(JSContext* cx, bool b)` | JSContext, jsval |
| js32.h | 196 | def | `const jschar* operator()(JSContext* cx, jsval v, const jschar*)` | JSContext, jschar, jsval |
| js32.h | 199 | def | `unsigned char operator()(JSContext* cx, jsval v, unsigned char)` | JSContext, jsval |
| js32.h | 202 | def | `int operator()(JSContext* cx, jsval v, int)` | JSContext, jsval |
| js32.h | 205 | def | `double operator()(JSContext* cx, jsval v, double)` | JSContext, jsval |
| js32.h | 208 | def | `uint32 operator()(JSContext* cx, jsval v, uint32)` | JSContext, jsval |
| js32.h | 211 | def | `bool operator()(JSContext* cx, jsval v, bool)` | JSContext, jsval |
| js32.h | 216 | def | `template <typename T> inline JSBool __fastcall JS_ArrayToVector(JSContext* cx, JSObject* arr, std::vector<T>& vec)` | JSBool, JSContext, JSObject |
| js32.h | 231 | def | `template <typename T> inline JSObject* __fastcall JS_VectorToArray(JSContext* cx, std::vector<T>& vec)` | JSContext, JSObject |
| MPQStats.cpp | 175 | def | `DWORD FillBaseStat(JSContext* cx, jsval* argv, int table, int row, int column, char* szTable, char* szStat)` | JSContext, jsval |
| MPQStats.h | 61 | decl | `DWORD FillBaseStat(JSContext* cx, jsval* argv, int table, int row, int column, char* szTable, char* szStat)` | JSContext, jsval |
| ScreenHook.cpp | 174 | def | `Genhook::Genhook(Script* nowner, JSObject* nself, uint x, uint y, ushort nopacity, bool nisAutomap, Align nalign, ScreenhookState ngameState)` | JSObject |
| ScreenHook.cpp | 265 | def | `void Genhook::SetClickHandler(jsval handler)` | jsval |
| ScreenHook.cpp | 295 | def | `void Genhook::SetHoverHandler(jsval handler)` | jsval |
| ScreenHook.h | 51 | decl | `Genhook::Genhook(Script* nowner, JSObject* nself, uint x, uint y, ushort nopacity, bool nisAutomap = false, Align nalign = Left, ScreenhookState ngameState = Perm)` | JSObject |
| ScreenHook.h | 138 | decl | `void SetClickHandler(jsval handler)` | jsval |
| ScreenHook.h | 139 | decl | `void SetHoverHandler(jsval handler)` | jsval |
| ScreenHook.h | 168 | def | `jsval GetClickHandler(void)` | jsval |
| ScreenHook.h | 171 | def | `jsval GetHoverHandler(void)` | jsval |
| ScreenHook.h | 197 | def | `TextHook(Script* owner, JSObject* nself, const wchar_t* text, uint x, uint y, ushort nfont, ushort ncolor, bool automap = false, Align align = Left, ScreenhookState state = Perm)` | JSObject |
| ScreenHook.h | 245 | def | `ImageHook(Script* owner, JSObject* nself, const wchar_t* nloc, uint x, uint y, ushort ncolor, bool automap = false, Align align = Left, ScreenhookState state = Perm, bool fromFile = true)` | JSObject |
| ScreenHook.h | 286 | def | `LineHook(Script* owner, JSObject* nself, uint x, uint y, uint nx2, uint ny2, ushort ncolor, bool automap = false, Align align = Left, ScreenhookState state = Perm)` | JSObject |
| ScreenHook.h | 336 | def | `BoxHook(Script* owner, JSObject* nself, uint x, uint y, uint nxsize, uint nysize, ushort ncolor, ushort opacity, bool automap = false, Align align = Left, ScreenhookState state = Perm)` | JSObject |
| ScreenHook.h | 384 | def | `FrameHook(Script* owner, JSObject* nself, uint x, uint y, uint nxsize, uint nysize, bool automap = false, Align align = Left, ScreenhookState state = Perm)` | JSObject |
| Script.cpp | 15 | def | `Script::Script(const wchar_t* file, ScriptState state, uint argc, JSAutoStructuredCloneBuffer** argv)` | JSAutoStructuredCloneBuffer |
| Script.cpp | 352 | def | `void Script::RegisterEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.cpp | 361 | def | `bool Script::IsRegisteredEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.cpp | 378 | def | `void Script::UnregisterEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.h | 128 | decl | `Script(const wchar_t* file, ScriptState state, uint argc = 0, JSAutoStructuredCloneBuffer** argv = NULL)` | JSAutoStructuredCloneBuffer |
| Script.h | 156 | def | `inline JSContext* GetContext(void)` | JSContext |
| Script.h | 159 | def | `inline JSRuntime* GetRuntime(void)` | JSRuntime |
| Script.h | 162 | def | `inline JSObject* GetGlobalObject(void)` | JSObject |
| Script.h | 165 | def | `inline JSObject* GetScriptObject(void)` | JSObject |
| Script.h | 185 | def | `inline void SetContext(JSContext* cx)` | JSContext |
| Script.h | 200 | decl | `void RegisterEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.h | 201 | decl | `bool IsRegisteredEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.h | 202 | decl | `void UnregisterEvent(const char* evtName, jsval evtFunc)` | jsval |
| Script.h | 218 | decl | `bool callEventFunction(JSContext* cx, Event* evt)` | JSContext |
| ScriptEngine.cpp | 31 | def | `Script* ScriptEngine::CompileFile(const wchar_t* file, ScriptState state, uint argc, JSAutoStructuredCloneBuffer** argv, bool recompile)` | JSAutoStructuredCloneBuffer |
| ScriptEngine.cpp | 230 | def | `void ScriptEngine::InitClass(JSContext* context, JSObject* globalObject, JSClass* classp, JSFunctionSpec* methods, JSPropertySpec* props, JSFunctionSpec* s_methods, JSPropertySpec* s_props)` | JSClass, JSContext, JSObject |
| ScriptEngine.cpp | 236 | def | `void ScriptEngine::DefineConstant(JSContext* context, JSObject* globalObject, const char* name, int value)` | JSContext, JSObject |
| ScriptEngine.cpp | 260 | def | `JSBool operationCallback(JSContext* cx)` | JSBool, JSContext |
| ScriptEngine.cpp | 329 | def | `JSBool contextCallback(JSContext* cx, uint contextOp)` | JSBool, JSContext |
| ScriptEngine.cpp | 428 | def | `void reportError(JSContext* cx, const char* message, JSErrorReport* report)` | JSContext, JSErrorReport |
| ScriptEngine.h | 45 | decl | `static Script* CompileFile(const wchar_t* file, ScriptState state, uint argc = 0, JSAutoStructuredCloneBuffer** argv = NULL, bool recompile = false)` | JSAutoStructuredCloneBuffer |
| ScriptEngine.h | 55 | def | `static JSRuntime* GetRuntime(void)` | JSRuntime |
| ScriptEngine.h | 58 | def | `static JSContext* GetGlobalContext(void)` | JSContext |
| ScriptEngine.h | 63 | decl | `static void ExecEventAsync(char* evtName, AutoRoot** argv, uint argc)` | AutoRoot |
| ScriptEngine.h | 64 | decl | `static void InitClass(JSContext* context, JSObject* globalObject, JSClass* classp, JSFunctionSpec* methods, JSPropertySpec* props, JSFunctionSpec* s_methods, JSPropertySpec* s_props)` | JSClass, JSContext, JSObject |
| ScriptEngine.h | 66 | decl | `static void DefineConstant(JSContext* context, JSObject* globalObject, const char* name, int value)` | JSContext, JSObject |
| ScriptEngine.h | 70 | decl | `JSGCCallback gcCallback(JSRuntime* rt, JSGCStatus status)` | JSGCCallback, JSGCStatus, JSRuntime |
| ScriptEngine.h | 82 | decl | `JSBool operationCallback(JSContext* cx)` | JSBool, JSContext |
| ScriptEngine.h | 83 | decl | `JSBool contextCallback(JSContext* cx, uint contextOp)` | JSBool, JSContext |
| ScriptEngine.h | 85 | decl | `void reportError(JSContext* cx, const char* message, JSErrorReport* report)` | JSContext, JSErrorReport |
<!-- /jsapi_inventory.py -->

The class `c` (non-engine) entries, and what each one does with the JS type:

| function | JS types | what the JS dependency is for | JS-free core already present? |
|---|---|---|---|
| `SetSkill(JSContext*, WORD, BOOL, DWORD)` `D2Helpers.cpp:238` | `JSContext*` | Sends packet 0x3C, then polls up to ~11 x 100 ms for the hand skill to change. While waiting it gets the calling `Script` via `JS_GetContextPrivate(cx)` and runs that script's queued events (`D2Helpers.cpp:268-284`) to avoid a packet deadlock. | No. The polling loop and the event pump are fused; split into "send + wait" and "pump caller's queue" |
| `FillBaseStat(JSContext*, jsval*, int, int, int, char*, char*)` `MPQStats.cpp:175` | `JSContext*`, `jsval*` | Resolves table/column by name, then converts the field to a `jsval` by `eFieldType` (string, number, int; `MPQStats.cpp:212-283`) | Yes: the raw overload `FillBaseStat(table,row,column,void*,size)` (used at `MPQStats.cpp:216`). Only the type switch needs a JS-free variant returning a tagged value |
| `ScriptBroadcastEvent(JSContext*, uint, jsval*)` `Events.cpp:168` | `JSContext*`, `jsval*` | Structured-clones each argument once per receiving script (`Events.cpp:157-161`) | No (see §7.2) |
| `writeValue(FILE*, JSContext*, jsval, bool, bool)` `File.cpp:49` | `JSContext*`, `jsval` | Serialises a JS value to a file by `JS_TypeOfValue` (`File.cpp:56-171`) | No; only JS File/FileTools call it |
| `fileOpenRelScript(const wchar_t*, const wchar_t*, JSContext*)` `File.cpp:188` | `JSContext*` | `cx` is used only for `JS_ReportError` (`File.cpp:194`, `File.cpp:202`) | Trivially; return an error code instead |
| `Genhook::SetClickHandler(jsval)` / `SetHoverHandler(jsval)` / `GetClickHandler()` / `GetHoverHandler()` `ScreenHook.cpp:265`, `ScreenHook.cpp:295`, `ScreenHook.h:168-171` | `jsval` | The hook keeps the JS callback values itself (§7.3) | The drawing part of `Genhook` is JS-free; the callback slots are not |
| `Genhook(Script*, JSObject*, ...)` and subclass constructors `ScreenHook.h:51`, `ScreenHook.h:197`, `:245`, `:286`, `:336`, `:384` | `JSObject*` | `self` is stored (`ScreenHook.cpp:179`) but its rooting is commented out (`ScreenHook.cpp:180-181`) | `self` has no use outside the binding |
| `friend JSAPI_PROP(profile_getProperty)` `Profile.h:62` | `JSAPI_PROP` | grants the JS getter access to `Profile` internals | remove the friend, add accessors |

### 4.4 C++ state that holds JS values

Struct/class members and globals whose type is a JS value, object, context, runtime, script, `AutoRoot`, a listener list or a clone buffer:

<!-- jsapi_inventory.py --section members -->
| file | line | owner | declaration |
|---|---|---|---|
| AutoRoot.h | 10 | AutoRoot | `jsval var` |
| AutoRoot.h | 12 | AutoRoot | `JSContext* cx` |
| Events.h | 72 | BCastEventHelper | `JSContext* cx` |
| Events.h | 73 | BCastEventHelper | `jsval* argv` |
| js32.h | 78 | JSAutoRoot | `JSContext* cx` |
| js32.h | 79 | JSAutoRoot | `jsval* ref` |
| JSArea.h | 29 | myArea | `JSObject* ExitArray` |
| JSSandbox.h | 21 | sandbox | `JSContext* context` |
| JSSandbox.h | 22 | sandbox | `JSObject* innerObj` |
| JSSQLite.cpp | 41 | DBStmt | `JSObject* current_row` |
| ScreenHook.h | 40 | Genhook | `jsval clicked, hovered` |
| ScreenHook.h | 41 | Genhook | `JSObject* self` |
| Script.h | 25 | Event | `JSObject* object` |
| Script.h | 26 | Event | `FunctionList functions` |
| Script.h | 27 | Event | `JSAutoStructuredCloneBuffer** argv` |
| Script.h | 111 | Script | `JSContext* context` |
| Script.h | 112 | Script | `JSScript* script` |
| Script.h | 113 | Script | `JSRuntime* runtime` |
| Script.h | 116 | Script | `JSAutoStructuredCloneBuffer** argv` |
| Script.h | 118 | Script | `JSObject *globalObject, *scriptObject` |
| Script.h | 136 | Script | `FunctionMap functions` |
| ScriptEngine.cpp | 19 | <global> | `JSRuntime* ScriptEngine::runtime = NULL` |
| ScriptEngine.cpp | 26 | <global> | `JSContext* ScriptEngine::context = NULL` |
| ScriptEngine.h | 24 | ScriptEngine | `static JSRuntime* runtime` |
| ScriptEngine.h | 25 | ScriptEngine | `static JSContext* context` |
| ScriptEngine.h | 78 | EventHelper | `AutoRoot** argv` |
| Map/Path/Reduction/JSPathReducer.h | 16 | JSPathReducer | `JSContext* cx` |
| Map/Path/Reduction/JSPathReducer.h | 17 | JSPathReducer | `JSObject* obj` |
| Map/Path/Reduction/JSPathReducer.h | 18 | JSPathReducer | `jsval reject, reduce, mutate` |
<!-- /jsapi_inventory.py -->

The scan sees types only. JS values are also hidden in `void*` event slots. `setTimeout`/`setInterval` store `new jsval(callback)` in `Event::arg3` (`JSCore.cpp:91`, `JSCore.cpp:111`), and `my_getDialogLines` stores a raw game pointer `&pTdi->dialogLines[i]` in a JS reserved slot via `PRIVATE_TO_JSVAL` (`JSGame.cpp:200`). Rooting status of each entry is in §7.3/§7.4.

---

## 5. Logic living inside natives

### 5.1 Native inventory (generated)

Columns: `body LOC` = lines of the native; `logic lines` see §1; `weight` = thin (≤5 logic lines), moderate (<25), heavy (≥25); `D2 ptrs` = distinct `D2*_`/`p_D2*_` game pointers referenced directly in the body; `bare JS_FALSE` = `return JS_FALSE` with no `JS_Report*`/`JS_ConvertArguments`/`JS_ConvertValue` in the same or the two preceding statements. Such a return terminates the script without a catchable exception. "JS-visible as" comes from the spec tables and `JSClass` definitions; `[class ... never registered]` / `[table never registered]` mark code that no script can reach (`profileType_class` and `profileType_props` exist, but their `global_classes` row is commented out, `JSGlobalClasses.cpp:184`). The block ends with the natives that can return without setting a return value (see §7.7).

Flags (regex over the body, see `FLAG_RULES` in the script):

| flag | meaning | why it matters for RPC |
|---|---|---|
| L | constructs `AutoCriticalRoom` = enters `Vars.cGameLoopSection` (`CriticalSections.h:31-55`) | the call must run while the game thread is parked; see §5.4 |
| W | calls `WaitForGameReady()` | may block before doing anything |
| B | blocks: `Sleep`, `WaitForSingleObject[Ex]`, `Join`, `SendMessage`, `InternetOpenUrl` | latency inside the call |
| E | runs queued JS events re-entrantly (`ExecScriptEvent`, `SetSkill`) | a JS-free version must not depend on a script queue |
| P | sends/receives a game packet | side effect is a network action |
| M | reads/writes process memory or computes `GetDllOffset` addresses | hardcoded-address coupling, see [../memory/offsets.md](../memory/offsets.md) |
| S | calls the script engine (`ScriptEngine::*`, `Script` methods) | engine API, not game API |
| C | uses `JSAutoStructuredCloneBuffer` | inter-script message passing |

<!-- jsapi_inventory.py --section natives -->
| location | C function | kind | JS-visible as | body LOC | JSAPI refs | logic lines | weight | D2 ptrs | flags | bare JS_FALSE | D2BS helpers called |
|---|---|---|---|---|---|---|---|---|---|---|---|
| JSArea.cpp:7 | `area_ctor` | CTOR(empty) | new Area() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSArea.cpp:9 | `area_finalize` | FINALIZER | Area finalize | 9 | 2 | 2 | thin | 0 | - |  | - |
| JSArea.cpp:19 | `area_getProperty` | GETTER/PROP | 7 props (Area get) | 74 | 21 | 35 | heavy | 1 | - | 2 | GetLevel |
| JSArea.cpp:94 | `my_getArea` | FUNC | getArea() | 47 | 23 | 14 | moderate | 0 | W |  | GetLevel, GetPlayerArea, WaitForGameReady |
| JSControl.cpp:6 | `control_ctor` | CTOR(empty) | new Control() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSControl.cpp:8 | `control_finalize` | FINALIZER | Control finalize | 8 | 2 | 2 | thin | 0 | - |  | - |
| JSControl.cpp:17 | `control_getProperty` | GETTER/PROP | 12 props (Control get) | 79 | 19 | 30 | heavy | 0 | - | 3 | ClientState, findControl |
| JSControl.cpp:97 | `control_setProperty` | SETTER | 4 props (Control set) | 56 | 20 | 19 | moderate | 1 | - | 3 | ClientState, findControl |
| JSControl.cpp:154 | `control_getNext` | FUNC | Control.getNext() | 33 | 12 | 14 | moderate | 0 | - |  | ClientState, findControl |
| JSControl.cpp:188 | `control_click` | FUNC | Control.click() | 27 | 18 | 6 | moderate | 0 | - |  | ClientState, clickControl, findControl |
| JSControl.cpp:216 | `control_setText` | FUNC | Control.setText() | 24 | 15 | 6 | moderate | 1 | - |  | ClientState, findControl |
| JSControl.cpp:241 | `control_getText` | FUNC | Control.getText() | 50 | 30 | 14 | moderate | 0 | - |  | ClientState, findControl |
| JSControl.cpp:292 | `my_getControl` | FUNC | getControl() | 33 | 16 | 14 | moderate | 0 | - |  | ClientState, findControl |
| JSControl.cpp:325 | `my_getControls` | FUNC | getControls() | 30 | 17 | 11 | moderate | 1 | - |  | ClientState |
| JSCore.cpp:22 | `my_stringToEUC` | FUNC | stringToEUC(); utf8ToEuc() | 26 | 23 | 3 | thin | 0 | - |  | UnicodeToAnsi |
| JSCore.cpp:49 | `my_print` | FUNC | print() | 28 | 19 | 5 | thin | 0 | - |  | Print |
| JSCore.cpp:78 | `my_setTimeout` | FUNC | setTimeout() | 19 | 18 | 3 | thin | 0 | S |  | ScriptEngine::AddDelayedEvent |
| JSCore.cpp:98 | `my_setInterval` | FUNC | setInterval() | 19 | 18 | 3 | thin | 0 | S |  | ScriptEngine::AddDelayedEvent |
| JSCore.cpp:117 | `my_clearInterval` | FUNC | clearTimeout(); clearInterval() | 8 | 8 | 0 | thin | 0 | S |  | ScriptEngine::RemoveDelayedEvent |
| JSCore.cpp:125 | `my_delay` | FUNC | delay() | 42 | 16 | 15 | moderate | 0 | BE |  | ClientState, ExecScriptEvent |
| JSCore.cpp:168 | `my_load` | FUNC | load() | 43 | 19 | 14 | moderate | 0 | SC |  | ClientState, Print, ScriptEngine::CompileFile, StringReplace |
| JSCore.cpp:212 | `my_include` | FUNC | include() | 24 | 13 | 5 | thin | 0 | S |  | - |
| JSCore.cpp:237 | `my_stop` | FUNC | stop() | 11 | 10 | 4 | thin | 0 | S | 1 | ScriptEngine::StopAll |
| JSCore.cpp:249 | `my_stacktrace` | FUNC | stacktrace() | 5 | 3 | 1 | thin | 0 | - |  | GetStackWalk |
| JSCore.cpp:255 | `my_beep` | FUNC | beep() | 10 | 8 | 1 | thin | 0 | - |  | - |
| JSCore.cpp:266 | `my_getTickCount` | FUNC | getTickCount() | 8 | 7 | 0 | thin | 0 | - |  | - |
| JSCore.cpp:275 | `my_getThreadPriority` | FUNC | getThreadPriority() | 4 | 3 | 0 | thin | 0 | - |  | - |
| JSCore.cpp:280 | `my_isIncluded` | FUNC | isIncluded() | 14 | 9 | 3 | thin | 0 | - |  | - |
| JSCore.cpp:295 | `my_version` | FUNC | version() | 11 | 7 | 2 | thin | 1 | - |  | Print |
| JSCore.cpp:307 | `my_debugLog` | FUNC | debugLog() | 28 | 17 | 6 | moderate | 0 | - |  | Log |
| JSCore.cpp:335 | `my_copy` | FUNC | copy() | 19 | 7 | 10 | moderate | 0 | - |  | - |
| JSCore.cpp:354 | `my_paste` | FUNC | paste() | 11 | 4 | 6 | moderate | 0 | - |  | AnsiToUnicode |
| JSCore.cpp:365 | `my_sendCopyData` | FUNC | sendCopyData() | 53 | 43 | 10 | moderate | 1 | B |  | - |
| JSCore.cpp:419 | `my_sendDDE` | FUNC | sendDDE() | 40 | 38 | 7 | moderate | 0 | - |  | AnsiToUnicode, SendDDE |
| JSCore.cpp:460 | `my_keystate` | FUNC | keystate() | 9 | 10 | 0 | thin | 0 | - |  | - |
| JSCore.cpp:470 | `my_addEventListener` | FUNC | addEventListener() | 12 | 12 | 2 | thin | 0 | S |  | - |
| JSCore.cpp:483 | `my_removeEventListener` | FUNC | removeEventListener() | 12 | 12 | 2 | thin | 0 | S |  | - |
| JSCore.cpp:496 | `my_clearEvent` | FUNC | clearEvent() | 9 | 8 | 1 | thin | 0 | S |  | - |
| JSCore.cpp:506 | `my_clearAllEvents` | FUNC | clearAllEvents() | 5 | 2 | 1 | thin | 0 | S |  | - |
| JSCore.cpp:512 | `my_js_strict` | FUNC | js_strict() | 19 | 16 | 5 | thin | 0 | - |  | - |
| JSCore.cpp:532 | `my_scriptBroadcast` | FUNC | scriptBroadcast() | 8 | 5 | 1 | thin | 0 | - |  | ScriptBroadcastEvent |
| JSCore.cpp:541 | `my_showConsole` | FUNC | showConsole() | 5 | 3 | 1 | thin | 0 | - |  | - |
| JSCore.cpp:547 | `my_hideConsole` | FUNC | hideConsole() | 5 | 3 | 1 | thin | 0 | - |  | - |
| JSCore.cpp:553 | `my_handler` | FUNC | handler() | 4 | 3 | 0 | thin | 0 | - |  | - |
| JSCore.cpp:558 | `my_loadMpq` | FUNC | loadMpq() | 10 | 6 | 2 | thin | 0 | - |  | LoadMPQ, isValidPath |
| JSCore.cpp:569 | `my_sendPacket` | FUNC | sendPacket() | 44 | 24 | 11 | moderate | 1 | P |  | - |
| JSCore.cpp:614 | `my_getPacket` | FUNC | getPacket() | 44 | 24 | 11 | moderate | 1 | P |  | - |
| JSCore.cpp:660 | `my_getIP` | FUNC | getIP() | 16 | 6 | 9 | moderate | 0 | B |  | - |
| JSCore.cpp:677 | `my_sendClick` | FUNC | sendClick() | 17 | 9 | 7 | moderate | 0 | B |  | SendMouseClick |
| JSCore.cpp:695 | `my_sendKey` | FUNC | sendKey() | 23 | 9 | 11 | moderate | 0 | B |  | SendKeyPress |
| JSDirectory.cpp:35 | `dir_ctor` | CTOR(empty) | new Folder() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSDirectory.cpp:37 | `my_openDir` | FUNC | dopen() | 29 | 12 | 12 | moderate | 0 | - | 2 | Log, UnicodeToAnsi, isValidPath |
| JSDirectory.cpp:74 | `dir_getFiles` | FUNC | Folder.getFiles() | 47 | 25 | 18 | moderate | 0 | - | 4 | Log |
| JSDirectory.cpp:122 | `dir_getFolders` | FUNC | Folder.getFolders() | 47 | 25 | 18 | moderate | 0 | - | 4 | Log |
| JSDirectory.cpp:170 | `dir_create` | FUNC | Folder.create() | 22 | 16 | 6 | moderate | 0 | - | 1 | isValidPath |
| JSDirectory.cpp:193 | `dir_delete` | FUNC | Folder.remove() | 17 | 7 | 5 | thin | 0 | - |  | - |
| JSDirectory.cpp:211 | `dir_getProperty` | GETTER/PROP | 1 props (Folder get) | 15 | 7 | 2 | thin | 0 | - | 1 | - |
| JSDirectory.cpp:227 | `dir_finalize` | FINALIZER | Folder finalize | 4 | 1 | 1 | thin | 0 | - |  | - |
| JSExits.cpp:3 | `exit_ctor` | CTOR(empty) | new Exit() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSExits.cpp:5 | `exit_finalize` | FINALIZER | Exit finalize | 4 | 1 | 1 | thin | 0 | - |  | - |
| JSExits.cpp:10 | `exit_getProperty` | GETTER/PROP | 6 props (Exit get) | 35 | 7 | 13 | moderate | 0 | - |  | - |
| JSFile.cpp:39 | `file_ctor` | CTOR(empty) | new File() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSFile.cpp:54 | `file_getProperty` | GETTER/PROP | 13 props (File get) | 78 | 13 | 45 | heavy | 0 | - |  | - |
| JSFile.cpp:133 | `file_setProperty` | SETTER | 1 props (File set) | 16 | 6 | 5 | thin | 0 | - |  | - |
| JSFile.cpp:150 | `file_open` | FUNC | File (static).open() | 82 | 36 | 35 | heavy | 0 | - | 1 | fileOpenRelScript |
| JSFile.cpp:233 | `file_close` | FUNC | File.close() | 21 | 9 | 12 | moderate | 0 | - |  | - |
| JSFile.cpp:255 | `file_reopen` | FUNC | File.reopen() | 23 | 8 | 12 | moderate | 0 | - | 1 | fileOpenRelScript |
| JSFile.cpp:279 | `file_read` | FUNC | File.read() | 76 | 24 | 40 | heavy | 0 | - |  | AnsiToUnicode |
| JSFile.cpp:356 | `file_readLine` | FUNC | File.readLine() | 30 | 7 | 16 | moderate | 0 | - |  | AnsiToUnicode, readLine |
| JSFile.cpp:387 | `file_readAllLines` | FUNC | File.readAllLines() | 38 | 14 | 18 | moderate | 0 | - |  | AnsiToUnicode, readLine |
| JSFile.cpp:426 | `file_readAll` | FUNC | File.readAll() | 56 | 9 | 32 | heavy | 0 | - |  | AnsiToUnicode |
| JSFile.cpp:483 | `file_write` | FUNC | File.write() | 16 | 7 | 6 | moderate | 0 | - |  | writeValue |
| JSFile.cpp:500 | `file_seek` | FUNC | File.seek() | 33 | 21 | 13 | moderate | 0 | - |  | readLine |
| JSFile.cpp:534 | `file_flush` | FUNC | File.flush() | 11 | 6 | 4 | thin | 0 | - |  | - |
| JSFile.cpp:546 | `file_reset` | FUNC | File.reset() | 11 | 8 | 3 | thin | 0 | - |  | - |
| JSFile.cpp:558 | `file_end` | FUNC | File.end() | 11 | 8 | 3 | thin | 0 | - |  | - |
| JSFile.cpp:570 | `file_finalize` | FINALIZER | File finalize | 18 | 1 | 13 | moderate | 0 | - |  | - |
| JSFileTools.cpp:32 | `filetools_ctor` | CTOR(empty) | new FileTools() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSFileTools.cpp:34 | `filetools_remove` | FUNC | FileTools (static).remove() | 13 | 8 | 3 | thin | 0 | - |  | getPathRelScript |
| JSFileTools.cpp:48 | `filetools_rename` | FUNC | FileTools (static).rename() | 21 | 15 | 5 | thin | 0 | - |  | getPathRelScript |
| JSFileTools.cpp:70 | `filetools_copy` | FUNC | FileTools (static).copy() | 56 | 23 | 24 | moderate | 0 | - | 1 | fileOpenRelScript, getPathRelScript |
| JSFileTools.cpp:127 | `filetools_exists` | FUNC | FileTools (static).exists() | 13 | 10 | 2 | thin | 0 | - |  | getPathRelScript |
| JSFileTools.cpp:141 | `filetools_readText` | FUNC | FileTools (static).readText() | 46 | 14 | 20 | moderate | 0 | - | 1 | AnsiToUnicode, fileOpenRelScript |
| JSFileTools.cpp:188 | `filetools_writeText` | FUNC | FileTools (static).writeText() | 28 | 11 | 10 | moderate | 0 | - | 1 | fileOpenRelScript, writeValue |
| JSFileTools.cpp:217 | `filetools_appendText` | FUNC | FileTools (static).appendText() | 29 | 11 | 10 | moderate | 0 | - | 1 | fileOpenRelScript, writeValue |
| JSGame.cpp:19 | `my_copyUnit` | FUNC | copyUnit() | 43 | 29 | 15 | moderate | 0 | - |  | - |
| JSGame.cpp:63 | `my_clickMap` | FUNC | clickMap() | 42 | 54 | 8 | moderate | 1 | W |  | ClickMap, WaitForGameReady |
| JSGame.cpp:106 | `my_acceptTrade` | FUNC | acceptTrade() | 40 | 24 | 12 | moderate | 5 | LW |  | WaitForGameReady |
| JSGame.cpp:147 | `my_tradeOk` | FUNC | tradeOk() | 22 | 3 | 10 | moderate | 3 | LW |  | WaitForGameReady |
| JSGame.cpp:170 | `my_getDialogLines` | FUNC | getDialogLines() | 43 | 27 | 6 | moderate | 1 | L |  | - |
| JSGame.cpp:213 | `my_clickDialog` | FUNC | DialogLine.handler() | 15 | 10 | 3 | thin | 0 | - |  | - |
| JSGame.cpp:229 | `my_getPath` | FUNC | getPath() | 94 | 37 | 37 | heavy | 0 | W | 1 | GetLevel, WaitForGameReady |
| JSGame.cpp:324 | `my_getCollision` | FUNC | getCollision() | 32 | 14 | 7 | moderate | 0 | W |  | GetLevel, WaitForGameReady |
| JSGame.cpp:357 | `my_clickItem` | FUNC | clickItem() | 305 | 77 | 162 | heavy | 20 | LW |  | GetItemLocation, GetMercUnit, WaitForGameReady |
| JSGame.cpp:663 | `my_getLocaleString` | FUNC | getLocaleString() | 13 | 11 | 2 | thin | 1 | - |  | - |
| JSGame.cpp:677 | `my_rand` | FUNC | rand() | 36 | 21 | 11 | moderate | 2 | - |  | ClientState |
| JSGame.cpp:714 | `my_getDistance` | FUNC | getDistance() | 94 | 111 | 18 | moderate | 4 | W |  | GetDistance, WaitForGameReady |
| JSGame.cpp:809 | `my_gold` | FUNC | gold() | 16 | 12 | 2 | thin | 0 | W |  | SendGold, WaitForGameReady |
| JSGame.cpp:826 | `my_checkCollision` | FUNC | checkCollision() | 24 | 22 | 5 | thin | 2 | W |  | WaitForGameReady |
| JSGame.cpp:851 | `my_getCursorType` | FUNC | getCursorType() | 10 | 6 | 1 | thin | 2 | - |  | - |
| JSGame.cpp:862 | `my_getSkillByName` | FUNC | getSkillByName() | 18 | 11 | 3 | thin | 0 | - |  | - |
| JSGame.cpp:881 | `my_getSkillById` | FUNC | getSkillById() | 18 | 15 | 4 | thin | 1 | - |  | FillBaseStat |
| JSGame.cpp:900 | `my_getTextSize` | FUNC | getTextSize() | 37 | 41 | 3 | thin | 0 | - |  | CalculateTextLen |
| JSGame.cpp:938 | `my_getTradeInfo` | FUNC | getTradeInfo() | 36 | 19 | 7 | moderate | 1 | W |  | WaitForGameReady |
| JSGame.cpp:975 | `my_getUIFlag` | FUNC | getUIFlag() | 14 | 12 | 1 | thin | 1 | W |  | WaitForGameReady |
| JSGame.cpp:990 | `my_getWaypoint` | FUNC | getWaypoint() | 18 | 12 | 3 | thin | 2 | W |  | WaitForGameReady |
| JSGame.cpp:1009 | `my_quitGame` | FUNC | quitGame() | 11 | 3 | 4 | thin | 1 | - |  | ClientState, Shutdown |
| JSGame.cpp:1021 | `my_quit` | FUNC | quit() | 8 | 3 | 3 | thin | 1 | - |  | ClientState |
| JSGame.cpp:1030 | `my_playSound` | FUNC | playSound() | 13 | 11 | 0 | thin | 0 | - |  | - |
| JSGame.cpp:1044 | `my_say` | FUNC | say() | 29 | 22 | 4 | thin | 0 | - |  | Say |
| JSGame.cpp:1074 | `my_clickParty` | FUNC | clickParty() | 68 | 27 | 26 | heavy | 6 | W |  | WaitForGameReady |
| JSGame.cpp:1143 | `my_useStatPoint` | FUNC | useStatPoint() | 15 | 8 | 4 | thin | 0 | W |  | UseStatPoint, WaitForGameReady |
| JSGame.cpp:1159 | `my_useSkillPoint` | FUNC | useSkillPoint() | 15 | 8 | 4 | thin | 0 | W |  | UseSkillPoint, WaitForGameReady |
| JSGame.cpp:1175 | `my_getBaseStat` | FUNC | getBaseStat() | 47 | 40 | 7 | moderate | 0 | - |  | FillBaseStat |
| JSGame.cpp:1223 | `my_weaponSwitch` | FUNC | weaponSwitch() | 34 | 18 | 11 | moderate | 3 | WP |  | WaitForGameReady |
| JSGame.cpp:1258 | `my_transmute` | FUNC | transmute() | 16 | 4 | 7 | moderate | 3 | W |  | WaitForGameReady |
| JSGame.cpp:1275 | `my_getPlayerFlag` | FUNC | getPlayerFlag() | 20 | 19 | 3 | thin | 1 | W |  | WaitForGameReady |
| JSGame.cpp:1296 | `my_getMouseCoords` | FUNC | getMouseCoords() | 47 | 37 | 10 | moderate | 5 | - |  | - |
| JSGame.cpp:1344 | `my_submitItem` | FUNC | submitItem() | 33 | 16 | 19 | moderate | 8 | WP |  | GetPlayerArea, WaitForGameReady |
| JSGame.cpp:1378 | `my_getIsTalkingNPC` | FUNC | getIsTalkingNPC() | 7 | 4 | 1 | thin | 0 | W |  | IsScrollingText, WaitForGameReady |
| JSGame.cpp:1386 | `my_getInteractedNPC` | FUNC | getInteractedNPC() | 29 | 11 | 13 | moderate | 1 | W |  | WaitForGameReady |
| JSGame.cpp:1416 | `my_takeScreenshot` | FUNC | takeScreenshot() | 5 | 1 | 1 | thin | 0 | - |  | - |
| JSGame.cpp:1421 | `my_moveNPC` | FUNC | moveNPC() | 34 | 17 | 12 | moderate | 1 | WP |  | WaitForGameReady |
| JSGame.cpp:1456 | `my_revealLevel` | FUNC | revealLevel() | 30 | 8 | 11 | moderate | 1 | L |  | GameReady, RevealRoom |
| JSHash.cpp:7 | `my_md5` | FUNC | md5() | 12 | 9 | 4 | thin | 0 | - |  | md5 |
| JSHash.cpp:20 | `my_sha1` | FUNC | sha1() | 12 | 9 | 4 | thin | 0 | - |  | sha1 |
| JSHash.cpp:33 | `my_sha256` | FUNC | sha256() | 12 | 9 | 4 | thin | 0 | - |  | sha256 |
| JSHash.cpp:46 | `my_sha384` | FUNC | sha384() | 12 | 9 | 4 | thin | 0 | - |  | sha384 |
| JSHash.cpp:59 | `my_sha512` | FUNC | sha512() | 12 | 9 | 4 | thin | 0 | - |  | sha512 |
| JSHash.cpp:72 | `my_md5_file` | FUNC | md5_file() | 17 | 9 | 7 | moderate | 0 | - |  | isValidPath, md5_file |
| JSHash.cpp:90 | `my_sha1_file` | FUNC | sha1_file() | 17 | 9 | 7 | moderate | 0 | - |  | isValidPath, sha1_file |
| JSHash.cpp:108 | `my_sha256_file` | FUNC | sha256_file() | 17 | 9 | 7 | moderate | 0 | - |  | isValidPath, sha256_file |
| JSHash.cpp:126 | `my_sha384_file` | FUNC | sha384_file() | 17 | 9 | 7 | moderate | 0 | - |  | isValidPath, sha384_file |
| JSHash.cpp:144 | `my_sha512_file` | FUNC | sha512_file() | 17 | 9 | 7 | moderate | 0 | - |  | isValidPath, sha512_file |
| JSMenu.cpp:10 | `my_login` | FUNC | login() | 32 | 13 | 14 | moderate | 0 | - |  | ClientState |
| JSMenu.cpp:43 | `my_selectChar` | FUNC | selectCharacter() | 17 | 12 | 4 | thin | 0 | - |  | OOG_SelectCharacter |
| JSMenu.cpp:61 | `my_createGame` | FUNC | createGame() | 26 | 17 | 7 | moderate | 0 | - |  | ClientState, OOG_CreateGame |
| JSMenu.cpp:88 | `my_joinGame` | FUNC | joinGame() | 23 | 17 | 6 | moderate | 0 | - |  | ClientState, OOG_JoinGame |
| JSMenu.cpp:112 | `my_addProfile` | FUNC | addProfile() | 42 | 14 | 19 | moderate | 0 | - |  | StringReplace |
| JSMenu.cpp:155 | `my_getOOGLocation` | FUNC | getLocation() | 9 | 6 | 1 | thin | 0 | - |  | ClientState, OOG_GetLocation |
| JSMenu.cpp:165 | `my_createCharacter` | FUNC | (not registered) | 19 | 17 | 3 | thin | 0 | - |  | ClientState, OOG_CreateCharacter |
| JSParty.cpp:8 | `party_ctor` | CTOR(empty) | new Party() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSParty.cpp:10 | `party_getProperty` | GETTER/PROP | 10 props (Party get) | 46 | 10 | 19 | moderate | 0 | - |  | - |
| JSParty.cpp:57 | `party_getNext` | FUNC | Party.getNext() | 25 | 14 | 5 | thin | 0 | W |  | WaitForGameReady |
| JSParty.cpp:83 | `my_getParty` | FUNC | getParty() | 70 | 33 | 22 | moderate | 2 | W |  | WaitForGameReady |
| JSPresetUnit.cpp:7 | `presetunit_ctor` | CTOR(empty) | new PresetUnit() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSPresetUnit.cpp:9 | `presetunit_finalize` | FINALIZER | PresetUnit finalize | 8 | 2 | 2 | thin | 0 | - |  | - |
| JSPresetUnit.cpp:18 | `presetunit_getProperty` | GETTER/PROP | 7 props (PresetUnit get) | 34 | 6 | 15 | moderate | 0 | - |  | - |
| JSPresetUnit.cpp:53 | `my_getPresetUnits` | FUNC | getPresetUnits() | 82 | 29 | 35 | heavy | 3 | LW |  | GetLevel, WaitForGameReady |
| JSPresetUnit.cpp:136 | `my_getPresetUnit` | FUNC | getPresetUnit() | 74 | 22 | 34 | heavy | 3 | LW |  | GetLevel, WaitForGameReady |
| JSProfile.cpp:16 | `profile_ctor` | CTOR | new Profile() | 75 | 75 | 20 | moderate | 0 | - |  | - |
| JSProfile.cpp:92 | `profile_login` | FUNC | Profile.login() | 12 | 6 | 3 | thin | 0 | - |  | - |
| JSProfile.cpp:105 | `profile_finalize` | FINALIZER | Profile finalize | 10 | 2 | 3 | thin | 0 | - |  | - |
| JSProfile.cpp:116 | `profile_getProperty` | GETTER/PROP | 8 props (Profile get) | 37 | 9 | 14 | moderate | 0 | - |  | - |
| JSProfile.cpp:154 | `profileType_ctor` | CTOR(empty) | new ProfileType() [class profileType_class never registered] | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSProfile.cpp:156 | `profileType_getProperty` | GETTER/PROP | 5 props in profileType_props [table never registered] | 7 | 3 | 1 | thin | 0 | - |  | - |
| JSRoom.cpp:7 | `room_ctor` | CTOR(empty) | new Room() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSRoom.cpp:9 | `room_getProperty` | GETTER/PROP | 9 props (Room get) | 43 | 6 | 21 | moderate | 0 | - |  | - |
| JSRoom.cpp:53 | `room_getNext` | FUNC | Room.getNext() | 21 | 16 | 4 | thin | 0 | - |  | - |
| JSRoom.cpp:75 | `room_getPresetUnits` | FUNC | Room.getPresetUnits() | 61 | 28 | 25 | heavy | 3 | L |  | GameReady |
| JSRoom.cpp:136 | `room_getCollisionTypeArray` | FUNC | Room.getCollisionA() | 77 | 21 | 36 | heavy | 3 | L |  | GameReady |
| JSRoom.cpp:213 | `room_getCollision` | FUNC | Room.getCollision() | 89 | 29 | 40 | heavy | 3 | L |  | GameReady |
| JSRoom.cpp:303 | `room_getNearby` | FUNC | Room.getNearby() | 24 | 19 | 3 | thin | 0 | - |  | - |
| JSRoom.cpp:329 | `room_getStat` | FUNC | Room.getStat() | 66 | 45 | 28 | heavy | 3 | L |  | GameReady |
| JSRoom.cpp:396 | `room_getFirst` | FUNC | Room.getFirst() | 14 | 11 | 2 | thin | 0 | - |  | - |
| JSRoom.cpp:411 | `room_unitInRoom` | FUNC | Room.unitInRoom() | 24 | 14 | 5 | thin | 2 | - |  | - |
| JSRoom.cpp:436 | `room_reveal` | FUNC | Room.reveal() | 17 | 10 | 5 | thin | 0 | L |  | GameReady, RevealRoom |
| JSRoom.cpp:454 | `my_getRoom` | FUNC | getRoom() | 126 | 58 | 51 | heavy | 4 | LW |  | GetLevel, WaitForGameReady |
| JSSQLite.cpp:67 | `my_sqlite_version` | FUNC | sqlite_version() | 4 | 4 | 0 | thin | 0 | - |  | - |
| JSSQLite.cpp:72 | `my_sqlite_memusage` | FUNC | sqlite_memusage() | 5 | 5 | 0 | thin | 0 | - |  | - |
| JSSQLite.cpp:78 | `sqlite_stmt_ctor` | CTOR(empty) | new DBStatement() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSSQLite.cpp:80 | `sqlite_ctor` | FUNC | new SQLite() | 50 | 18 | 23 | moderate | 0 | - |  | isValidPath |
| JSSQLite.cpp:131 | `sqlite_execute` | FUNC | SQLite.execute() | 19 | 15 | 5 | thin | 0 | - |  | - |
| JSSQLite.cpp:151 | `sqlite_query` | FUNC | SQLite.query() | 67 | 44 | 21 | moderate | 0 | - |  | - |
| JSSQLite.cpp:219 | `sqlite_close` | FUNC | SQLite.close() | 10 | 6 | 3 | thin | 0 | - |  | - |
| JSSQLite.cpp:230 | `sqlite_open` | FUNC | SQLite.open() | 12 | 6 | 4 | thin | 0 | - |  | - |
| JSSQLite.cpp:243 | `sqlite_getProperty` | GETTER/PROP | 5 props (SQLite get) | 36 | 16 | 12 | moderate | 0 | - |  | - |
| JSSQLite.cpp:280 | `sqlite_finalize` | FINALIZER | SQLite finalize | 9 | 2 | 4 | thin | 0 | - |  | - |
| JSSQLite.cpp:307 | `sqlite_stmt_getobject` | FUNC | DBStatement.getObject() | 62 | 37 | 17 | moderate | 0 | - |  | AnsiToUnicode |
| JSSQLite.cpp:370 | `sqlite_stmt_colcount` | FUNC | DBStatement.getColumnCount() | 10 | 6 | 2 | thin | 0 | - |  | - |
| JSSQLite.cpp:381 | `sqlite_stmt_colval` | FUNC | DBStatement.getColumnValue() | 37 | 22 | 10 | moderate | 0 | - |  | AnsiToUnicode |
| JSSQLite.cpp:419 | `sqlite_stmt_colname` | FUNC | DBStatement.getColumnName() | 16 | 12 | 4 | thin | 0 | - |  | AnsiToUnicode |
| JSSQLite.cpp:436 | `sqlite_stmt_execute` | FUNC | DBStatement.go() | 11 | 6 | 3 | thin | 0 | - |  | - |
| JSSQLite.cpp:448 | `sqlite_stmt_bind` | FUNC | DBStatement.bind() | 45 | 40 | 8 | moderate | 0 | - |  | - |
| JSSQLite.cpp:494 | `sqlite_stmt_next` | FUNC | DBStatement.next() | 16 | 7 | 5 | thin | 0 | - |  | - |
| JSSQLite.cpp:511 | `sqlite_stmt_skip` | FUNC | DBStatement.skip() | 20 | 15 | 7 | moderate | 0 | - |  | - |
| JSSQLite.cpp:532 | `sqlite_stmt_reset` | FUNC | DBStatement.reset() | 8 | 6 | 2 | thin | 0 | - |  | - |
| JSSQLite.cpp:541 | `sqlite_stmt_close` | FUNC | DBStatement.close() | 16 | 12 | 3 | thin | 0 | - |  | - |
| JSSQLite.cpp:558 | `sqlite_stmt_getProperty` | GETTER/PROP | 2 props (DBStatement get) | 18 | 6 | 5 | thin | 0 | - |  | AnsiToUnicode |
| JSSQLite.cpp:577 | `sqlite_stmt_finalize` | FINALIZER | DBStatement finalize | 13 | 2 | 5 | thin | 0 | - |  | - |
| JSSandbox.cpp:6 | `sandbox_ctor` | FUNC | new Sandbox() | 41 | 24 | 8 | moderate | 0 | S |  | ScriptEngine::GetRuntime |
| JSSandbox.cpp:48 | `sandbox_addProperty` | GETTER/PROP | Sandbox.addProperty hook | 34 | 29 | 5 | thin | 0 | - | 1 | - |
| JSSandbox.cpp:83 | `sandbox_delProperty` | GETTER/PROP | Sandbox.delProperty hook | 23 | 17 | 3 | thin | 0 | - | 1 | - |
| JSSandbox.cpp:107 | `sandbox_getProperty` | GETTER/PROP | Sandbox.getProperty hook | 31 | 26 | 3 | thin | 0 | - | 1 | - |
| JSSandbox.cpp:139 | `sandbox_setProperty` | SETTER | Sandbox.setProperty hook | 24 | 17 | 4 | thin | 0 | - | 1 | - |
| JSSandbox.cpp:164 | `sandbox_finalize` | FINALIZER | Sandbox finalize | 8 | 2 | 2 | thin | 0 | - |  | - |
| JSSandbox.cpp:173 | `sandbox_eval` | FUNC | Sandbox.evaluate() | 14 | 14 | 2 | thin | 0 | - |  | - |
| JSSandbox.cpp:188 | `sandbox_include` | FUNC | Sandbox.include() | 27 | 16 | 7 | moderate | 0 | - |  | - |
| JSSandbox.cpp:216 | `sandbox_isIncluded` | FUNC | Sandbox.isIncluded() | 11 | 11 | 3 | thin | 0 | - |  | - |
| JSSandbox.cpp:228 | `sandbox_clear` | FUNC | Sandbox.clearScope() | 6 | 3 | 0 | thin | 0 | - |  | - |
| JSScreenHook.cpp:8 | `hook_finalize` | FINALIZER | Frame finalize; Box finalize; Line finalize; Text finalize; Image finalize | 9 | 2 | 4 | thin | 0 | - |  | - |
| JSScreenHook.cpp:18 | `hook_remove` | FUNC | Frame.remove(); Box.remove(); Line.remove(); Text.remove(); Image.remove() | 16 | 7 | 4 | thin | 0 | - |  | - |
| JSScreenHook.cpp:37 | `frame_ctor` | FUNC | new Frame() | 43 | 42 | 8 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:81 | `frame_getProperty` | GETTER/PROP | 9 props (Frame get) | 38 | 6 | 19 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:120 | `frame_setProperty` | SETTER | 9 props (Frame set) | 45 | 6 | 26 | heavy | 0 | - |  | - |
| JSScreenHook.cpp:169 | `box_ctor` | FUNC | new Box() | 48 | 50 | 10 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:217 | `box_getProperty` | GETTER/PROP | 11 props (Box get) | 44 | 6 | 23 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:262 | `box_setProperty` | SETTER | 11 props (Box set) | 53 | 6 | 32 | heavy | 0 | - |  | - |
| JSScreenHook.cpp:319 | `line_ctor` | FUNC | new Line() | 43 | 42 | 9 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:363 | `line_getProperty` | GETTER/PROP | 9 props (Line get) | 38 | 6 | 19 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:402 | `line_setProperty` | SETTER | 9 props (Line set) | 45 | 6 | 26 | heavy | 0 | - |  | - |
| JSScreenHook.cpp:451 | `text_ctor` | FUNC | new Text() | 49 | 48 | 12 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:501 | `text_getProperty` | GETTER/PROP | 10 props (Text get) | 41 | 7 | 20 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:543 | `text_setProperty` | SETTER | 10 props (Text set) | 53 | 8 | 30 | heavy | 0 | - |  | - |
| JSScreenHook.cpp:600 | `image_ctor` | FUNC | new Image() | 53 | 45 | 15 | moderate | 0 | - |  | isValidPath |
| JSScreenHook.cpp:654 | `image_getProperty` | GETTER/PROP | 8 props (Image get) | 35 | 7 | 16 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:690 | `image_setProperty` | SETTER | 8 props (Image set) | 45 | 8 | 24 | moderate | 0 | - |  | - |
| JSScreenHook.cpp:736 | `screenToAutomap` | FUNC | screenToAutomap() | 46 | 57 | 9 | moderate | 0 | - |  | ScreenToAutomap |
| JSScreenHook.cpp:783 | `automapToScreen` | FUNC | automapToScreen() | 58 | 58 | 11 | moderate | 0 | - |  | AutomapToScreen |
| JSScript.cpp:7 | `script_ctor` | CTOR(empty) | new D2BSScript() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSScript.cpp:18 | `script_getProperty` | GETTER/PROP | 5 props (D2BSScript get) | 32 | 9 | 10 | moderate | 0 | - |  | - |
| JSScript.cpp:51 | `script_getNext` | FUNC | D2BSScript.getNext() | 26 | 10 | 8 | moderate | 0 | S |  | ScriptEngine::LockScriptList, ScriptEngine::UnLockScriptList |
| JSScript.cpp:78 | `script_stop` | FUNC | D2BSScript.stop() | 8 | 5 | 2 | thin | 0 | S |  | - |
| JSScript.cpp:87 | `script_pause` | FUNC | D2BSScript.pause() | 9 | 5 | 2 | thin | 0 | S |  | - |
| JSScript.cpp:97 | `script_resume` | FUNC | D2BSScript.resume() | 9 | 5 | 2 | thin | 0 | S |  | - |
| JSScript.cpp:107 | `script_send` | FUNC | D2BSScript.send() | 25 | 9 | 13 | moderate | 0 | SC |  | ScriptEngine::LockScriptList, ScriptEngine::UnLockScriptList |
| JSScript.cpp:133 | `script_join` | FUNC | D2BSScript.join() | 8 | 5 | 1 | thin | 0 | B |  | - |
| JSScript.cpp:142 | `my_getScript` | FUNC | getScript() | 46 | 26 | 19 | moderate | 0 | S |  | ScriptEngine::ForEachScript, ScriptEngine::LockScriptList, ScriptEngine::UnLockScriptList, StringReplace |
| JSScript.cpp:188 | `my_getScripts` | FUNC | getScripts() | 22 | 14 | 5 | thin | 0 | S |  | ScriptEngine::LockScriptList, ScriptEngine::UnLockScriptList |
| JSSocket.cpp:24 | `socket_ctor` | CTOR(empty) | new Socket() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSSocket.cpp:26 | `socket_getProperty` | GETTER/PROP | 2 props (Socket get) | 38 | 6 | 19 | moderate | 0 | - |  | - |
| JSSocket.cpp:65 | `socket_setProperty` | SETTER | (not registered) | 3 | 1 | 0 | thin | 0 | - |  | - |
| JSSocket.cpp:69 | `socket_open` | FUNC | Socket (static).open() | 51 | 23 | 20 | moderate | 0 | - |  | - |
| JSSocket.cpp:121 | `socket_close` | FUNC | Socket.close() | 8 | 3 | 2 | thin | 0 | - |  | - |
| JSSocket.cpp:130 | `socket_send` | FUNC | Socket.send() | 11 | 8 | 2 | thin | 0 | - |  | - |
| JSSocket.cpp:142 | `socket_read` | FUNC | Socket.read() | 24 | 7 | 12 | moderate | 0 | - |  | AnsiToUnicode |
| JSSocket.cpp:167 | `socket_finalize` | FINALIZER | Socket finalize | 7 | 1 | 3 | thin | 0 | - |  | - |
| JSUnit.cpp:11 | `unit_ctor` | CTOR(empty) | new Unit() | 1 | 0 | 0 | thin | 0 | - |  | - |
| JSUnit.cpp:13 | `unit_finalize` | FINALIZER | Unit finalize | 19 | 2 | 8 | moderate | 0 | - |  | - |
| JSUnit.cpp:47 | `unit_getProperty` | GETTER/PROP | 49 props (Unit get); 80 props (me get) | 479 | 63 | 263 | heavy | 27 | LM |  | AnsiToUnicode, ClientState, GameReady, GetDllOffset, GetUnitName, ReadProcessBYTES |
| JSUnit.cpp:527 | `unit_setProperty` | SETTER | 10 props (me set) | 44 | 4 | 27 | heavy | 3 | - |  | - |
| JSUnit.cpp:572 | `unit_getUnit` | FUNC | getUnit() | 69 | 43 | 25 | heavy | 3 | - |  | GetUnit |
| JSUnit.cpp:642 | `unit_getNext` | FUNC | Unit.getNext() | 87 | 61 | 21 | moderate | 1 | - |  | GetInvNextUnit, GetNextUnit |
| JSUnit.cpp:730 | `unit_cancel` | FUNC | Unit.cancel() | 40 | 11 | 20 | moderate | 7 | W |  | IsScrollingText, WaitForGameReady |
| JSUnit.cpp:771 | `unit_repair` | FUNC | Unit.repair() | 24 | 9 | 8 | moderate | 3 | P |  | - |
| JSUnit.cpp:796 | `unit_useMenu` | FUNC | Unit.useMenu() | 19 | 14 | 3 | thin | 1 | - |  | ClickNPCMenu |
| JSUnit.cpp:816 | `unit_interact` | FUNC | Unit.interact() | 71 | 25 | 27 | heavy | 8 | WP |  | ClickMap, FillBaseStat, GetItemLocation, WaitForGameReady |
| JSUnit.cpp:891 | `unit_getStat` | FUNC | Unit.getStat() | 109 | 53 | 39 | heavy | 6 | W |  | WaitForGameReady |
| JSUnit.cpp:1097 | `unit_getState` | FUNC | Unit.getState() | 32 | 21 | 4 | thin | 2 | W |  | WaitForGameReady |
| JSUnit.cpp:1130 | `item_getFlags` | FUNC | Unit.getFlags() | 18 | 8 | 4 | thin | 1 | W |  | WaitForGameReady |
| JSUnit.cpp:1149 | `item_getFlag` | FUNC | Unit.getFlag() | 23 | 14 | 4 | thin | 1 | W |  | WaitForGameReady |
| JSUnit.cpp:1224 | `item_getItemCost` | FUNC | Unit.getItemCost() | 67 | 39 | 17 | moderate | 6 | W |  | FillBaseStat, WaitForGameReady |
| JSUnit.cpp:1292 | `unit_getItems` | FUNC | Unit.getItems() | 54 | 24 | 19 | moderate | 2 | W |  | WaitForGameReady |
| JSUnit.cpp:1347 | `unit_getSkill` | FUNC | Unit.getSkill() | 116 | 64 | 37 | heavy | 3 | W |  | FillBaseStat, WaitForGameReady |
| JSUnit.cpp:1464 | `item_shop` | FUNC | Unit.shop() | 107 | 18 | 25 | heavy | 8 | LW |  | WaitForGameReady |
| JSUnit.cpp:1572 | `unit_getParent` | FUNC | Unit.getParent() | 84 | 31 | 41 | heavy | 3 | W |  | GetUnit, WaitForGameReady |
| JSUnit.cpp:1658 | `unit_getMerc` | FUNC | Unit.getMerc() | 30 | 12 | 14 | moderate | 1 | W |  | GetMercUnit, WaitForGameReady |
| JSUnit.cpp:1689 | `unit_getMercHP` | FUNC | getMercHP(); Unit.getMercHP() | 18 | 9 | 5 | thin | 3 | W |  | GetMercUnit, WaitForGameReady |
| JSUnit.cpp:1709 | `unit_setskill` | FUNC | Unit.setSkill() | 40 | 31 | 9 | moderate | 0 | WE |  | GetSkillByName, SetSkill, WaitForGameReady |
| JSUnit.cpp:1750 | `my_overhead` | FUNC | Unit.overhead() | 36 | 17 | 10 | moderate | 3 | W |  | UnicodeToAnsi, WaitForGameReady |
| JSUnit.cpp:1787 | `my_revive` | FUNC | Unit.revive() | 8 | 2 | 3 | thin | 1 | WP |  | WaitForGameReady |
| JSUnit.cpp:1796 | `unit_getItem` | FUNC | Unit.getItem() | 64 | 38 | 24 | moderate | 1 | W |  | GetInvUnit, UnicodeToAnsi, WaitForGameReady |
| JSUnit.cpp:1861 | `unit_move` | FUNC | Unit.move() | 38 | 15 | 14 | moderate | 4 | WB |  | ClickMap, WaitForGameReady |
| JSUnit.cpp:1900 | `unit_getEnchant` | FUNC | Unit.getEnchant() | 28 | 15 | 6 | moderate | 1 | W |  | WaitForGameReady |
| JSUnit.cpp:1929 | `unit_getQuest` | FUNC | Unit.getQuest() | 14 | 15 | 1 | thin | 2 | W |  | WaitForGameReady |
| JSUnit.cpp:1944 | `unit_getMinionCount` | FUNC | Unit.getMinionCount() | 23 | 14 | 4 | thin | 2 | W |  | WaitForGameReady |
| JSUnit.cpp:1968 | `me_getRepairCost` | FUNC | Unit.getRepairCost() | 14 | 9 | 2 | thin | 5 | W |  | WaitForGameReady |

| weight | natives |
|---|---|
| thin | 130 |
| moderate | 109 |
| heavy | 28 |

| flag | natives |
|---|---|
| L | 15 |
| W | 50 |
| B | 7 |
| E | 2 |
| P | 8 |
| M | 1 |
| S | 18 |
| C | 2 |

Non-native helper functions defined in binding files:

| location | signature | JS types |
|---|---|---|
| JSDirectory.h:37 | `DirData(const wchar_t* newname)` | - |
| JSScript.cpp:210 | `bool __fastcall FindScriptByName(Script* script, void* argv, uint argc)` | - |
| JSScript.cpp:221 | `bool __fastcall FindScriptByTid(Script* script, void* argv, uint argc)` | - |
| JSSQLite.cpp:47 | `bool clean_sqlite_db(SqliteDB* db)` | - |
| JSSQLite.cpp:59 | `void close_db_stmt(DBStmt* stmt)` | - |
| JSUnit.cpp:1001 | `void InsertStatsToGenericObject(UnitAny* pUnit, StatList* pStatList, JSContext* cx, JSObject* pArray)` | JSContext, JSObject |
| JSUnit.cpp:1021 | `void InsertStatsNow(Stat* pStat, int nStat, JSContext* cx, JSObject* pArray)` | JSContext, JSObject |
| Map/Path/Reduction/JSPathReducer.h:23 | `JSPathReducer(ActMap* m, JSContext* cx, JSObject* obj, jsval _reject, jsval _reduce, jsval _mutate)` | JSContext, JSObject, jsval |
| Map/Path/Reduction/JSPathReducer.h:28 | `~JSPathReducer(void)` | - |
| Map/Path/Reduction/JSPathReducer.h:34 | `void Reduce(PointList const& in, PointList& out, bool abs)` | - |
| Map/Path/Reduction/JSPathReducer.h:65 | `bool Reject(Point const& pt, bool abs)` | - |
| Map/Path/Reduction/JSPathReducer.h:71 | `void GetOpenNodes(Point const& center, PointList& out, Point const& endpoint)` | - |
| Map/Path/Reduction/JSPathReducer.h:80 | `int GetPenalty(Point const& pt, bool abs)` | - |
| Map/Path/Reduction/JSPathReducer.h:83 | `void MutatePoint(Point& pt, bool abs)` | - |

FUNC natives that return `JS_TRUE` without having set the return value (no `JS_SET_RVAL`/`THROW_WARNING` anywhere in the body, or a `return JS_TRUE` that textually precedes the first one; a lower bound, since sets inside branches are not path-checked):

| location | C function | JS-visible as | unset-rval returns |
|---|---|---|---|
| JSControl.cpp:154 | `control_getNext` | Control.getNext() | JSControl.cpp:156, JSControl.cpp:160 |
| JSControl.cpp:188 | `control_click` | Control.click() | JSControl.cpp:190, JSControl.cpp:194 |
| JSControl.cpp:216 | `control_setText` | Control.setText() | JSControl.cpp:218, JSControl.cpp:222 |
| JSCore.cpp:125 | `my_delay` | delay() | never sets it |
| JSCore.cpp:307 | `my_debugLog` | debugLog() | never sets it |
| JSCore.cpp:335 | `my_copy` | copy() | never sets it |
| JSCore.cpp:470 | `my_addEventListener` | addEventListener() | never sets it |
| JSCore.cpp:483 | `my_removeEventListener` | removeEventListener() | never sets it |
| JSCore.cpp:496 | `my_clearEvent` | clearEvent() | never sets it |
| JSCore.cpp:506 | `my_clearAllEvents` | clearAllEvents() | never sets it |
| JSDirectory.cpp:37 | `my_openDir` | dopen() | JSDirectory.cpp:39 |
| JSFileTools.cpp:34 | `filetools_remove` | FileTools (static).remove() | never sets it |
| JSFileTools.cpp:48 | `filetools_rename` | FileTools (static).rename() | never sets it |
| JSFileTools.cpp:70 | `filetools_copy` | FileTools (static).copy() | never sets it |
| JSGame.cpp:663 | `my_getLocaleString` | getLocaleString() | JSGame.cpp:665 |
| JSGame.cpp:862 | `my_getSkillByName` | getSkillByName() | JSGame.cpp:864 |
| JSGame.cpp:881 | `my_getSkillById` | getSkillById() | JSGame.cpp:883 |
| JSGame.cpp:1275 | `my_getPlayerFlag` | getPlayerFlag() | JSGame.cpp:1277 |
| JSGame.cpp:1296 | `my_getMouseCoords` | getMouseCoords() | JSGame.cpp:1337 |
| JSGame.cpp:1416 | `my_takeScreenshot` | takeScreenshot() | never sets it |
| JSGame.cpp:1456 | `my_revealLevel` | revealLevel() | never sets it |
| JSMenu.cpp:165 | `my_createCharacter` | (not registered) | JSMenu.cpp:167 |
| JSRoom.cpp:75 | `room_getPresetUnits` | Room.getPresetUnits() | JSRoom.cpp:92 |
| JSRoom.cpp:136 | `room_getCollisionTypeArray` | Room.getCollisionA() | JSRoom.cpp:145, JSRoom.cpp:157, JSRoom.cpp:167, JSRoom.cpp:195 |
| JSRoom.cpp:213 | `room_getCollision` | Room.getCollision() | JSRoom.cpp:222, JSRoom.cpp:228, JSRoom.cpp:243, JSRoom.cpp:272, JSRoom.cpp:288 |
| JSRoom.cpp:303 | `room_getNearby` | Room.getNearby() | JSRoom.cpp:308, JSRoom.cpp:314, JSRoom.cpp:320 |
| JSRoom.cpp:411 | `room_unitInRoom` | Room.unitInRoom() | JSRoom.cpp:414, JSRoom.cpp:419, JSRoom.cpp:424, JSRoom.cpp:429 |
| JSRoom.cpp:436 | `room_reveal` | Room.reveal() | JSRoom.cpp:446 |
| JSSQLite.cpp:72 | `my_sqlite_memusage` | sqlite_memusage() | never sets it |
| JSSandbox.cpp:6 | `sandbox_ctor` | new Sandbox() | JSSandbox.cpp:11, JSSandbox.cpp:17, JSSandbox.cpp:23, JSSandbox.cpp:33, JSSandbox.cpp:39 |
| JSSandbox.cpp:228 | `sandbox_clear` | Sandbox.clearScope() | never sets it |
| JSScreenHook.cpp:18 | `hook_remove` | Frame.remove(); Box.remove(); Line.remove(); Text.remove(); Image.remove() | never sets it |
| JSScreenHook.cpp:451 | `text_ctor` | new Text() | JSScreenHook.cpp:465 |
| JSScreenHook.cpp:600 | `image_ctor` | new Image() | JSScreenHook.cpp:615 |
| JSSocket.cpp:121 | `socket_close` | Socket.close() | never sets it |
| JSSocket.cpp:130 | `socket_send` | Socket.send() | never sets it |
| JSUnit.cpp:1347 | `unit_getSkill` | Unit.getSkill() | JSUnit.cpp:1349 |
<!-- /jsapi_inventory.py -->

### 5.2 Embedded logic to extract (hand-written)

Natives where substantive game/infra logic sits inside the `JSNative` body and has no JS-free equivalent. An RPC server that wants the same behaviour has to lift this code out first. "Helper" means an existing JS-free function the native already delegates to. Argument parsing and object building are not listed.

| native (JS name) | location | embedded logic | existing JS-free helper |
|---|---|---|---|
| `clickItem` | `JSGame.cpp:357` | Full inventory click engine. Refuses while transaction dialogs are open (`JSGame.cpp:366`). Equipment clicks go through the body-click jump table `D2CLIENT_BodyClickTable + 4*loc` (`JSGame.cpp:417`, `:432`, `:546`). Merc gear uses `D2CLIENT_MercItemAction(0x61, loc)`. Inventory/stash/cube/trade pixel coordinates come from `InventoryLayout` (`Left + x*SlotPixelWidth + 10`, `JSGame.cpp:510-511`, `:604-605`). Belt slot geometry depends on `D2GFX_GetScreenSize()` (440/580 vs 360/460, 29 px, `JSGame.cpp:529-535`, `:637-643`). Click types 0/1/2 select left, right or shift-left (`JSGame.cpp:607-612`). Multi-cell cursor items are adjusted (`JSGame.cpp:569-581`). Hover globals are overwritten (`JSGame.cpp:399-400`). Quirk to not copy: the `(type, unit)` belt branch passes `(pInventory, pPlayer, ...)` to `D2CLIENT_ClickBeltRight` (`JSGame.cpp:539`), whose macro takes `(pPlayer, pInventory, ...)` (`D2Ptrs.h:502`); the 4-argument branch uses the right order (`JSGame.cpp:648`, `:650`). | `GetItemLocation`, `GetMercUnit` only |
| `getPath` | `JSGame.cpp:229` | Maps reduction type 0-3 to Walk/Teleport/No/JS reducers (`JSGame.cpp:260-276`), builds `ActMap::GetMap(level)`, runs `AStarPath::GetPath`, and returns `[{x,y}]` | `Map/` (A*, reducers) is JS-free except `JSPathReducer` |
| `acceptTrade` | `JSGame.cpp:106` | Trade state machine: query modes 1/2/3, then for `RecentTradeId ∈ {3,5,7}` toggles accept/cancel unless `bTradeBlock` (`JSGame.cpp:127-142`) | none |
| `tradeOk` | `JSGame.cpp:147` | Scans transaction dialog lines for the `D2CLIENT_TradeOK` handler and invokes it only if `*p_D2CLIENT_TransactionDialogs == 1` (`JSGame.cpp:155-164`) | none |
| `getDialogLines` / `DialogLine.handler()` | `JSGame.cpp:170`, `JSGame.cpp:213` | Exposes NPC dialog lines and calls a line's game `handler()` through a raw pointer kept in a reserved slot (`JSGame.cpp:200`, `JSGame.cpp:217-221`) | none |
| `clickParty` | `JSGame.cpp:1074` | Validates the roster entry (`JSGame.cpp:1092-1097`), blocks loot on non-hardcore (`JSGame.cpp:1104`), blocks re-party/leave-without-party via `wPartyId 0xFFFF` checks, maps modes 0/1/4/5 to `D2CLIENT_HostilePartyUnit(...,2/1/3/4)` and 2 to `D2CLIENT_ClickParty`, mode 3 to `D2CLIENT_LeaveParty` (`JSGame.cpp:1108-1136`) | none |
| `submitItem` | `JSGame.cpp:1344` | Act 2 (`dwAct == 1`) staff-in-orifice packet 0x44 with `*p_D2CLIENT_OrificeId` when standing in the tomb level. Acts 1/5 use `D2CLIENT_SubmitItem` when interacting in town (`JSGame.cpp:1349-1373`) | none |
| `weaponSwitch` | `JSGame.cpp:1223` | Expansion check on `BnData.nCharFlags`, packet 0x60 (`JSGame.cpp:1239-1251`) | none |
| `moveNPC` | `JSGame.cpp:1421` | Gated on `Vars.bEnableUnsupported` (otherwise `THROW_WARNING`, `JSGame.cpp:1425-1427`). Builds packet 0x59 (type, id, x, y) (`JSGame.cpp:1444-1451`). Checks `argc < 2` but reads `argv[2]` (`JSGame.cpp:1429`, `:1439`) | none |
| `rand` | `JSGame.cpp:677` | In game: `D2GAME_Rand(player->dwSeed)`; out of game: `rand()` seeded once (`JSGame.cpp:684-694`) | none |
| `getMouseCoords` | `JSGame.cpp:1296` | Screen to map: adds viewport offsets, then `D2COMMON_AbsScreenToMap` (`JSGame.cpp:1306-1313`) | none |
| `transmute` | `JSGame.cpp:1258` | Opens the cube UI state around `D2CLIENT_Transmute` (`JSGame.cpp:1263-1270`) | none |
| `getSkillById` / `Unit.getSkill(0/1)` | `JSGame.cpp:881`, `JSUnit.cpp:1347` | Skill name lookup chain skills -> skilldesc -> "str name" -> `D2LANG_GetLocaleText` (`JSGame.cpp:890-894`, `JSUnit.cpp:1393-1405`) | `FillBaseStat` (raw) |
| `revealLevel` / `Room.reveal()` | `JSGame.cpp:1456`, `JSRoom.cpp:436` | Iterates `Room2` list under the game lock calling `RevealRoom` | `RevealRoom` |
| `Unit` getter (all props) | `JSUnit.cpp:47` | 85 distinct property ids in one `switch` (`JSUnit.cpp:55`) serve both `unit_props` (49) and `me_props` (80), which share 44 ids (`JSUnit.h:160-297`). HP/MP/stamina are 8.8 fixed point (`>>8`, `JSUnit.cpp:255-271`). Monster spectype bits are synthesised from `MonsterData` flags (`JSUnit.cpp:280-296`). Item code is 3 chars from `ItemTxt` (`JSUnit.cpp:304-316`). Affix names come from `D2COMMON_GetItemMagicalMods`. `me.*` reads `Vars`, `BnData`, `GameStructInfo` and game globals (`JSUnit.cpp:55-181`). **Item description** uses `WriteProcessMemory` into two hardcoded addresses (VA `0x7BCBE8` = 1, VA `0x7BCBF4` = unit pointer), then `D2CLIENT_LoadItemDesc`, then reads 2047 bytes from the hardcoded buffer at VA `0x841EC8` (`JSUnit.cpp:453-458`; the addresses are not in `D2Ptrs.h`, see [../memory/offsets.md](../memory/offsets.md)). Object type is masked by level (`JSUnit.cpp:503-510`). | `GetUnitName`, `ReadProcessBYTES` |
| `me` setter | `JSUnit.cpp:527` | Writes `Vars.*` flags and game globals `AlwaysRun`, `AutomapOn`, `NoPickUp` (`JSUnit.cpp:530-568`) | none |
| `getUnit` | `JSUnit.cpp:572` | Selector semantics. Type 100 = cursor item, 101 = selected unit or selected inventory item (`JSUnit.cpp:603-610`), otherwise `GetUnit(name, classId, type, mode, id)`. The returned handle stores type+id, not a pointer (`JSUnit.cpp:624-628`). | `GetUnit` (`Unit.cpp`) |
| `Unit.getNext` | `JSUnit.cpp:642` | Iteration state lives in the JS object's private data. It is updated in place, plus owner tracking for inventory items (`JSUnit.cpp:649-725`). | `GetNextUnit`, `GetInvNextUnit` |
| `Unit.cancel` | `JSUnit.cpp:730` | Infers the mode when none is given: scrolling text -> 3, NPC -> 2, cursor item -> 1, else 0. Each mode has its own close action. Restores the automap flag afterwards (`JSUnit.cpp:737-766`). | `IsScrollingText` |
| `Unit.repair` | `JSUnit.cpp:771` | Packet 0x35 with `RecentInteractId`, flag byte 0x80 (`JSUnit.cpp:783-787`) | none |
| `Unit.interact` | `JSUnit.cpp:816` | Inventory/stash item -> packet 0x20 with player position. Belt item -> packet 0x26 (`JSUnit.cpp:832-852`). Waypoint objects are validated through `levels.Waypoint != 255` before `D2CLIENT_TakeWaypoint`. Anything else -> `ClickMap` on the unit (`JSUnit.cpp:854-883`). | `ClickMap`, `FillBaseStat` |
| `Unit.getStat` (+ `InsertStatsToGenericObject`, `InsertStatsNow`) | `JSUnit.cpp:891`, `:1001`, `:1021` | Stat semantics. 6..11 are shifted `>>8`. Experience is unsigned. `-1` = de-duplicated merge of `D2COMMON_CopyStatList` and `StatVec` (`JSUnit.cpp:924-971`). `-2` = sparse `[stat][sub]` object with skill-charge decoding (`sub>>6` skill, `&0x3F` level, `value&0xFF` charges, `>>8` max, `JSUnit.cpp:1022-1028`). Missing stats fall back to the preset list (`JSUnit.cpp:980-993`). | none; the two helpers take `JSContext*`/`JSObject*` |
| `Unit.getItemCost` / `me.getRepairCost` | `JSUnit.cpp:1224`, `JSUnit.cpp:1968` | Default NPC Charsi `0x9A` (`JSUnit.cpp:1230`). Invalid NPCs are replaced via `monstats.inventory == 0` (`JSUnit.cpp:1270-1271`). Price modes buy/sell/repair(3) go through `D2COMMON_GetItemPrice`, repair cost through `D2COMMON_GetRepairCost`. | `FillBaseStat` |
| `Unit.getItems` / `Unit.getItem` | `JSUnit.cpp:1292`, `JSUnit.cpp:1796` | Inventory walk / `GetInvUnit` search, building owner-linked item handles | `GetInvUnit` |
| `Unit.getSkill` | `JSUnit.cpp:1347` | Left/right skill ids, the `[id, base, total]` list, and charged vs non-charged skill-level selection (`JSUnit.cpp:1449-1458`) | none |
| `Unit.shop` | `JSUnit.cpp:1464` | Shop preconditions: no transaction dialog, `UI_NPCSHOP`, interacting NPC, mode ∈ {1,2,6}, ownership checks. Then `D2CLIENT_ShopAction` (`JSUnit.cpp:1472-1528`) | none |
| `Unit.getParent` | `JSUnit.cpp:1572` | Owner resolution per unit type: monster -> `D2CLIENT_GetMonsterOwner`, object -> `szOwner` string, item -> owner inventory, missile -> `D2COMMON_GetMissileOwnerUnit` (`JSUnit.cpp:1587-1653`) | `GetUnit` |
| `Unit.getMerc` / `getMercHP` | `JSUnit.cpp:1658`, `JSUnit.cpp:1689` | Merc lookup. HP percent, 0 when the owner's mode is 12 (dead) (`JSUnit.cpp:1700-1702`) | `GetMercUnit` |
| `Unit.setSkill` | `JSUnit.cpp:1709` | Name -> id via `GetSkillByName`, optional item id from a Unit argument, then `SetSkill` (§4.3) | `SetSkill` (JS-typed) |
| `Unit.overhead` | `JSUnit.cpp:1750` | Converts to `CP_ACP` and attaches `D2COMMON_GenerateOverheadMsg` to `pUnit->pOMsg` (`JSUnit.cpp:1771-1775`) | none |
| `Unit.move` | `JSUnit.cpp:1861` | Move = `ClickMap(0)`, `Sleep(50)`, `ClickMap(2)`; other units move to their position (`JSUnit.cpp:1879-1895`) | `ClickMap` |
| `Unit.getEnchant` | `JSUnit.cpp:1900` | Scans `pMonsterData->anEnchants[0..8]` | none |
| `Room.getPresetUnits`, `getCollisionA`, `getCollision`, `getStat` | `JSRoom.cpp:75`, `:136`, `:213`, `:329` | Temporarily loads room data (`D2COMMON_AddRoomData`/`RemoveRoomData` when `pRoom1` is missing) under the game lock. Reads `CollMap` into flat `Uint16Array` or nested arrays. `getStat` maps indices 0-16 to `Room1`/`Room2`/`CollMap` fields (`JSRoom.cpp:355-388`). | none |
| `getRoom` | `JSRoom.cpp:454` | Room lookup by level, by player, or by coordinate scan over `Room2` with temporary room loading (`JSRoom.cpp:535-559`) | `GetLevel` |
| `getPresetUnits` / `getPresetUnit` | `JSPresetUnit.cpp:53`, `JSPresetUnit.cpp:136` | Level-wide preset scan with temporary room loading and type/class filtering (`JSPresetUnit.cpp:85-125`) | `GetLevel` |
| `Area.exits` | `JSArea.cpp:19` | `ActMap::GetMap(level)->GetExits`, then converts into exit objects and caches them (`JSArea.cpp:32-66`) | `ActMap` |
| `getParty` | `JSParty.cpp:83` | Roster search by name, id or Unit (`JSParty.cpp:94-142`) | none |
| `getControl(s)`, `Control.*` | `JSControl.cpp:292`, `:325`, `:154`, `:188`, `:216`, `:241` | Control lookup by `(type, x, y, xsize, ysize)` on every access (`JSControl.cpp:25`, `JSControl.cpp:105`, `JSControl.cpp:162`) | `findControl`, `clickControl` (`Control.cpp`) |
| `addProfile` | `JSMenu.cpp:112` | Validates arguments and writes a `d2bs.ini` profile section (`JSMenu.cpp:143-150`) | none (`Profile.cpp` reads, does not write) |
| `delay` | `JSCore.cpp:125` | Alertable wait loop that pumps the script's event queue. Explicit GC every 512 KiB of growth (`JSCore.cpp:138-161`). | engine-specific |
| `load` | `JSCore.cpp:168` | Builds the script path, chooses InGame/OutOfGame for console-launched scripts, structured-clones extra args (`JSCore.cpp:184-198`) | `ScriptEngine::CompileFile` |
| `sendPacket` / `getPacket` | `JSCore.cpp:569`, `JSCore.cpp:614` | Both gated on `Vars.bEnableUnsupported` (`JSCore.cpp:572-574`, `:617-619`). Packet assembly from an ArrayBuffer or from `(size, value)` pairs: each value is stored as a 4-byte little-endian `uint32` at the running offset, which then advances by `size`, inside a `2*argc`-byte buffer (`JSCore.cpp:580-605`); with sizes above 4 the later writes and the final length exceed that buffer. `sendPacket` hands the bytes to `D2NET_SendPacket(len, 1, ...)`, `getPacket` injects them with `D2NET_ReceivePacket` (`JSCore.cpp:608`, `:653`) | none |
| `sendCopyData`, `sendDDE`, `copy`/`paste`, `getIP`, `sendClick`, `sendKey` | `JSCore.cpp:365`, `:419`, `:335`, `:354`, `:660`, `:677`, `:695` | OS IPC/clipboard/HTTP/input sequencing (100 ms sleeps) inside the native | `SendDDE`, `SendMouseClick`, `SendKeyPress` |
| `File.*`, `FileTools.*`, `Folder.*`, `SQLite`/`DBStatement`, `Socket.*`, `Sandbox` | `JSFile.cpp`, `JSFileTools.cpp`, `JSDirectory.cpp`, `JSSQLite.cpp`, `JSSocket.cpp`, `JSSandbox.cpp` | File I/O, path sandboxing, SQL, TCP, nested JS contexts. All of the logic is in the natives and only JS consumes it. | `File.cpp` helpers (JS-typed, §4.3) |

### 5.3 Thin wrappers

130 natives are "thin" in §5.1. Representative groups (all verified against their bodies):

* Pure pass-through to a JS-free function: `md5`…`sha512` and `*_file` (`JSHash.cpp:7-160` -> `Hash.cpp`), `gold` -> `SendGold`, `useStatPoint`/`useSkillPoint` -> `UseStatPoint`/`UseSkillPoint`, `selectCharacter`/`createGame`/`joinGame`/`getLocation` -> `OOG_*` in `Control.cpp`, `login` -> `Profile::login`, `say` -> `Say`, `print`/`debugLog` -> `Print`/`Log`, `getTextSize` -> `CalculateTextLen`, `screenToAutomap`/`automapToScreen` -> `D2Helpers.cpp` (the natives are long only because of argument overloads), `getDistance` -> `GetDistance` (94 lines, all overload resolution).
* Single game read: `getUIFlag`, `getWaypoint`, `getLocaleString`, `getCursorType`, `getPlayerFlag`, `checkCollision`, `Unit.getState`, `getFlags`/`getFlag`, `getQuest`, `getMinionCount`, `getTradeInfo`, `getIsTalkingNPC`.
* Engine-only: `addEventListener`/`removeEventListener`/`clearEvent`/`clearAllEvents`, `setTimeout`/`setInterval`/`clear*`, `include`/`isIncluded`, `stop`, `js_strict`, `version`, `D2BSScript.*` (`JSScript.cpp`). These have no game logic; their semantics belong to the engine and are documented in [embedding.md](embedding.md) and [../js-api/globals-core.md](../js-api/globals-core.md).
* Screen hooks: `Frame`/`Box`/`Line`/`Text`/`Image` getters/setters (`JSScreenHook.cpp`) map properties 1:1 onto `Genhook` setters/getters in `ScreenHook.cpp`. They are flagged "heavy" only because of the long `switch` statements.

### 5.4 Game-loop lock discipline

15 natives take `AutoCriticalRoom` (flag L). The lock is `Vars.cGameLoopSection` (`CriticalSections.h:31-55`). The game thread holds it continuously and releases it only briefly: in `GameDraw` when `Vars.SectionCount` (the number of waiting script threads) is non-zero (`D2Handlers.cpp:410-416`), in every game-timer callback `TimerProc`, which also sleeps 5 ms while waiters are counted (`D2Handlers.cpp:493-503`), and around packet-event waits (`Events.cpp:312-314`, `Events.cpp:347-355`). The overall thread model is in [../architecture.md](../architecture.md). A native that leaves the scope without `delete cRoom` therefore keeps the game thread blocked. The script checks every return/throw reachable while the lock is held, in natives (flag L) and in every other function that constructs `AutoCriticalRoom` itself (two JS-free helpers, `GetLevel` and `RevealRoom`):

<!-- jsapi_inventory.py --section locks -->
| function | C function | kind (file class) | return/throw reachable while the lock is still held (statement start line) |
|---|---|---|---|
| JSGame.cpp:106 | `my_acceptTrade` | native | - |
| JSGame.cpp:147 | `my_tradeOk` | native | - |
| JSGame.cpp:170 | `my_getDialogLines` | native | - |
| JSGame.cpp:357 | `my_clickItem` | native | - |
| JSGame.cpp:1456 | `my_revealLevel` | native | - |
| JSPresetUnit.cpp:53 | `my_getPresetUnits` | native | - |
| JSPresetUnit.cpp:136 | `my_getPresetUnit` | native | - |
| JSRoom.cpp:75 | `room_getPresetUnits` | native | - |
| JSRoom.cpp:136 | `room_getCollisionTypeArray` | native | JSRoom.cpp:156 |
| JSRoom.cpp:213 | `room_getCollision` | native | JSRoom.cpp:227 |
| JSRoom.cpp:329 | `room_getStat` | native | - |
| JSRoom.cpp:436 | `room_reveal` | native | - |
| JSRoom.cpp:454 | `my_getRoom` | native | - |
| JSUnit.cpp:47 | `unit_getProperty` | native | - |
| JSUnit.cpp:1464 | `item_shop` | native | - |
| D2Helpers.cpp:172 | `GetLevel` | helper (c) | D2Helpers.cpp:175 |
| Room.cpp:5 | `RevealRoom` | helper (d) | - |
<!-- /jsapi_inventory.py -->

The two native hits (`JSRoom.cpp:156-157`, `JSRoom.cpp:227-228`) are `if (!jsobjy) return JS_TRUE;` after a failed `JS_NewUint16Array`/`JS_NewArrayObject`. On that path they also leave a root registered on a stack slot that is about to die (§7.4) and, in `getCollisionA`, skip the `D2COMMON_RemoveRoomData` for a room they added (`JSRoom.cpp:148-151`).

The helper hit matters more: `GetLevel` (`D2Helpers.cpp:172`) enters the lock and returns `nullptr` without `delete cRoom` when `!GameReady()` (`D2Helpers.cpp:175-176`). It is JS-free and called from 8 natives (`JSArea.cpp:25`, `:115`, `JSGame.cpp:250`, `:338`, `JSPresetUnit.cpp:66`, `:149`, `JSRoom.cpp:469`, `:509`); the critical section stays owned by the calling script thread, so the game thread's next `EnterCriticalSection` (`D2Handlers.cpp:416`, `:503`) blocks. An RPC layer that reuses `GetLevel` inherits this.

An RPC server that calls game functions needs the same locking rule: take `cGameLoopSection` only for the duration of game-memory access.

---

## 6. Build integration

### 6.1 Build files

Every line in the build files that touches SpiderMonkey, the runtime library, defines, post-build steps or the toolchain:

<!-- jsapi_inventory.py --section build -->
| file | line | content |
|---|---|---|
| D2BS.vcxproj | 2 | `<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">` |
| D2BS.vcxproj | 4 | `<ProjectConfiguration Include="Debug\|Win32">` |
| D2BS.vcxproj | 8 | `<ProjectConfiguration Include="Packaging\|Win32">` |
| D2BS.vcxproj | 12 | `<ProjectConfiguration Include="Release\|Win32">` |
| D2BS.vcxproj | 20 | `<WindowsTargetPlatformVersion>10.0</WindowsTargetPlatformVersion>` |
| D2BS.vcxproj | 24 | `<ConfigurationType>DynamicLibrary</ConfigurationType>` |
| D2BS.vcxproj | 25 | `<CharacterSet>MultiByte</CharacterSet>` |
| D2BS.vcxproj | 28 | `<ConfigurationType>DynamicLibrary</ConfigurationType>` |
| D2BS.vcxproj | 29 | `<CharacterSet>MultiByte</CharacterSet>` |
| D2BS.vcxproj | 32 | `<ConfigurationType>DynamicLibrary</ConfigurationType>` |
| D2BS.vcxproj | 33 | `<CharacterSet>MultiByte</CharacterSet>` |
| D2BS.vcxproj | 69 | `<IncludePath Condition="'$(Configuration)\|$(Platform)'=='Release\|Win32'">C:\Program Files %28x86%29\boost\boost_1_46_1;$(ProgramFiles)\boost;$(IncludePath);$(SolutionDir)\Engine;$(SolutionDir)\Engine\dependencies\include</IncludePath>` |
| D2BS.vcxproj | 83 | `<AdditionalIncludeDirectories>$(ProjectDir);%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>` |
| D2BS.vcxproj | 84 | `<PreprocessorDefinitions>WIN32;_WINDOWS;DEBUG;_DEBUG;_MSVC_DEBUG;WIN32_LEAN_AND_MEAN;_SECURE_SCL#0;_SECURE_SCL_THROWS#0;_HAS_ITERATOR_DEBUGGING#0;%(PreprocessorDefinitions)</PreprocessorDefinitions>` |
| D2BS.vcxproj | 89 | `<RuntimeLibrary>MultiThreadedDebugDLL</RuntimeLibrary>` |
| D2BS.vcxproj | 90 | `<RuntimeTypeInfo>false</RuntimeTypeInfo>` |
| D2BS.vcxproj | 102 | `<DisableSpecificWarnings>4100;%(DisableSpecificWarnings)</DisableSpecificWarnings>` |
| D2BS.vcxproj | 109 | `<AdditionalDependencies>kernel32.lib;user32.lib;gdi32.lib;shlwapi.lib;advapi32.lib;dbghelp.lib;dependencies\libs\debug\mozjs.lib</AdditionalDependencies>` |
| D2BS.vcxproj | 137 | `<AdditionalIncludeDirectories>$(ProjectDir);%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>` |
| D2BS.vcxproj | 138 | `<PreprocessorDefinitions>WIN32;XP_WIN;_WINDOWS;NDEBUG;_NDEBUG;WIN32_LEAN_AND_MEAN;STATIC_JS_API;_MSVC_DEBUG;_LIB;MOZILLA_STRICT_API;%(PreprocessorDefinitions)</PreprocessorDefinitions>` |
| D2BS.vcxproj | 142 | `<RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>` |
| D2BS.vcxproj | 145 | `<RuntimeTypeInfo>false</RuntimeTypeInfo>` |
| D2BS.vcxproj | 155 | `<DisableSpecificWarnings>4100;4127;4800;4480;4740;4530;%(DisableSpecificWarnings)</DisableSpecificWarnings>` |
| D2BS.vcxproj | 157 | `<ExceptionHandling>false</ExceptionHandling>` |
| D2BS.vcxproj | 164 | `<AdditionalDependencies>kernel32.lib;user32.lib;gdi32.lib;shlwapi.lib;advapi32.lib;dbghelp.lib;Winmm.lib;dependencies\libs\release\js_static.lib</AdditionalDependencies>` |
| D2BS.vcxproj | 185 | `<Command>COPY /B "$(OutDir)$(TargetFileName)" /B "$(OutDir)$(TargetName).bin" /Y /V` |
| D2BS.vcxproj | 190 | `<LinkLibraryDependencies>false</LinkLibraryDependencies>` |
| D2BS.vcxproj | 205 | `<AdditionalIncludeDirectories>$(ProjectDir);%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>` |
| D2BS.vcxproj | 206 | `<PreprocessorDefinitions>WIN32;_WINDOWS;NDEBUG;_NDEBUG;WIN32_LEAN_AND_MEAN;_SECURE_SCL#0;_SECURE_SCL_THROWS#0;_HAS_ITERATOR_DEBUGGING#0;%(PreprocessorDefinitions)</PreprocessorDefinitions>` |
| D2BS.vcxproj | 210 | `<RuntimeLibrary>MultiThreadedDLL</RuntimeLibrary>` |
| D2BS.vcxproj | 213 | `<RuntimeTypeInfo>false</RuntimeTypeInfo>` |
| D2BS.vcxproj | 223 | `<DisableSpecificWarnings>4100;%(DisableSpecificWarnings)</DisableSpecificWarnings>` |
| D2BS.vcxproj | 230 | `<AdditionalDependencies>kernel32.lib;user32.lib;gdi32.lib;shlwapi.lib;advapi32.lib;dbghelp.lib;dependencies\libs\release\mozjs.lib</AdditionalDependencies>` |
| D2BS.vcxproj | 249 | `<Command>RMDIR /S /Q "$(OutDir)release-pkg"` |
| D2BS.vcxproj | 250 | `MKDIR "$(OutDir)release-pkg"` |
| D2BS.vcxproj | 251 | `COPY /B "$(OutDir)$(TargetFileName)" /B "$(OutDir)release-pkg\$(TargetName).bin" /Y /V` |
| D2BS.vcxproj | 252 | `XCOPY "$(ProjectDir)resources" "$(OutDir)release-pkg"` |
| D2BS.vcxproj | 328 | `<ClInclude Include="..\bob-18_ff20\Pipe.h" />` |
| D2BS.vcxproj | 329 | `<ClInclude Include="..\bob-18_ff20\Socket.h" />` |
| D2BS.vcxproj | 330 | `<ClInclude Include="..\bob-18_ff20\Stream.h" />` |
| D2BS.vcxproj | 339 | `<ClInclude Include="dependencies\include\jsfriendapi.h" />` |
| D2BS.vcxproj | 360 | `<ClInclude Include="dependencies\include\js-config.h" />` |
| D2BS.vcxproj | 361 | `<ClInclude Include="dependencies\include\jsapi.h" />` |
| D2BS.vcxproj | 362 | `<ClInclude Include="dependencies\include\jscompat.h" />` |
| D2BS.vcxproj | 363 | `<ClInclude Include="dependencies\include\jscpucfg.h" />` |
| D2BS.vcxproj | 364 | `<ClInclude Include="dependencies\include\jsinttypes.h" />` |
| D2BS.vcxproj | 365 | `<ClInclude Include="dependencies\include\jsotypes.h" />` |
| D2BS.vcxproj | 366 | `<ClInclude Include="dependencies\include\jspubtd.h" />` |
| D2BS.vcxproj | 367 | `<ClInclude Include="dependencies\include\jstypes.h" />` |
| D2BS.vcxproj | 368 | `<ClInclude Include="dependencies\include\jsutil.h" />` |
| D2BS.vcxproj | 369 | `<ClInclude Include="dependencies\include\jsval.h" />` |
| D2BS.vcxproj | 370 | `<ClInclude Include="dependencies\include\jsversion.h" />` |
| D2BS.vcxproj | 418 | `<None Include="dependencies\include\jsproto.tbl" />` |
| D2BS.vcxproj.filters | 2 | `<Project ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">` |
| D2BS.vcxproj.filters | 19 | `<Filter Include="Spidermonkey Engine">` |
| D2BS.vcxproj.filters | 22 | `<Filter Include="Spidermonkey Engine\Engine Imports">` |
| D2BS.vcxproj.filters | 25 | `<Filter Include="Spidermonkey Engine\Core">` |
| D2BS.vcxproj.filters | 28 | `<Filter Include="Spidermonkey Engine\Core\C">` |
| D2BS.vcxproj.filters | 31 | `<Filter Include="Spidermonkey Engine\Core\JS">` |
| D2BS.vcxproj.filters | 34 | `<Filter Include="Spidermonkey Engine\Core\API">` |
| D2BS.vcxproj.filters | 37 | `<Filter Include="Spidermonkey Engine\Engine">` |
| D2BS.vcxproj.filters | 270 | `<ClInclude Include="dependencies\include\js-config.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 273 | `<ClInclude Include="dependencies\include\jsapi.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 276 | `<ClInclude Include="dependencies\include\jscompat.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 279 | `<ClInclude Include="dependencies\include\jscpucfg.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 282 | `<ClInclude Include="dependencies\include\jsinttypes.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 285 | `<ClInclude Include="dependencies\include\jsotypes.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 288 | `<ClInclude Include="dependencies\include\jspubtd.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 291 | `<ClInclude Include="dependencies\include\jstypes.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 294 | `<ClInclude Include="dependencies\include\jsutil.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 297 | `<ClInclude Include="dependencies\include\jsval.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 300 | `<ClInclude Include="dependencies\include\jsversion.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 442 | `<ClInclude Include="..\bob-18_ff20\Stream.h">` |
| D2BS.vcxproj.filters | 445 | `<ClInclude Include="..\bob-18_ff20\Socket.h">` |
| D2BS.vcxproj.filters | 448 | `<ClInclude Include="..\bob-18_ff20\Pipe.h">` |
| D2BS.vcxproj.filters | 451 | `<ClInclude Include="dependencies\include\jsfriendapi.h"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.vcxproj.filters | 469 | `<None Include="dependencies\include\jsproto.tbl"> <Filter>Spidermonkey Engine\Engine Imports</Filter>` |
| D2BS.sln | 2 | `Microsoft Visual Studio Solution File, Format Version 11.00` |
| D2BS.sln | 3 | `# Visual Studio 2010` |
| D2BS.sln | 25 | `Manager = AnkhSVN - Subversion Support for Visual Studio` |
| build.bat | 1 | `call "C:\Program Files\Microsoft Visual Studio 9.0\VC\vcvarsall.bat" x86` |
| build.bat | 2 | `msbuild /p:configuration=debug` |
| build.bat | 3 | `msbuild /p:configuration=release` |
| Release/Build Instructions.txt | 1 | `unzip bob-18\dependencies\libs\release\js_static.zip into that folder` |
| Release/Build Instructions.txt | 2 | `use visual studio 2010` |
<!-- /jsapi_inventory.py -->

### 6.2 Configuration matrix (from `D2BS.vcxproj`)

| | Debug | Release | Packaging |
|---|---|---|---|
| JS library linked | `dependencies\libs\debug\mozjs.lib` (import library for `mozjs.dll`), `D2BS.vcxproj:109` | `dependencies\libs\release\js_static.lib`, `D2BS.vcxproj:164`. Only `js_static.zip` is checked in; `Release/Build Instructions.txt:1` says to unzip it (the zip holds one 127 MB `js_static.lib`) | `dependencies\libs\release\mozjs.lib`, `D2BS.vcxproj:230`. **This file does not exist in the repo** |
| SpiderMonkey-relevant defines | `DEBUG;_DEBUG` (`D2BS.vcxproj:84`). No `XP_WIN`/`STATIC_JS_API` in the project; `XP_WIN` comes from `js32.h:4-6`/`D2BS.h:6-8`. Without `STATIC_JS_API`, `JS_PUBLIC_API` expands to `MOZ_IMPORT_API` (`dependencies/include/jstypes.h:61-70`) | `XP_WIN;STATIC_JS_API;MOZILLA_STRICT_API` (`D2BS.vcxproj:138`); `STATIC_JS_API` makes `JS_PUBLIC_API(t)` plain `t` (`dependencies/include/jstypes.h:61-63`) | none (`D2BS.vcxproj:206`); imports, like Debug |
| CRT | `MultiThreadedDebugDLL` (`/MDd`, `D2BS.vcxproj:89`) | `MultiThreadedDLL` (`/MD`, `D2BS.vcxproj:142`); the static `js_static.lib` must be built against the same CRT | `MultiThreadedDLL` (`D2BS.vcxproj:210`) |
| C++ exceptions | default | `ExceptionHandling=false` (`D2BS.vcxproj:157`) with warning 4530 suppressed (`D2BS.vcxproj:155`), although `Script.cpp:119-172` and `ScriptEngine.cpp:38-53` use `try/catch` | default |
| post-build | none; `mozjs.dll` is not copied anywhere | copy DLL to `D2BS.bin` (`D2BS.vcxproj:185`) | `release-pkg` with `.bin` + `resources\` (`D2BS.vcxproj:249-252`) |

Other build facts:

* The project lists headers that are not in `dependencies/include`: `jscompat.h`, `jsinttypes.h`, `jsotypes.h`, `jsval.h` (`D2BS.vcxproj:362`, `:364`, `:365`, `:369`) and `jsproto.tbl` (`D2BS.vcxproj:418`). It also lists `..\bob-18_ff20\Pipe.h`, `Socket.h`, `Stream.h` outside the repo (`D2BS.vcxproj:328-330`). These are 1.8.x-era leftovers. As headers they do not break the build.
* The Release `IncludePath` points to boost and `$(SolutionDir)\Engine\dependencies\include` (`D2BS.vcxproj:69`), neither of which exists. JS headers are found through the relative `#include "dependencies\include\jsapi.h"` in `js32.h:13`.
* `build.bat:1` calls the VS 9.0 (2008) `vcvarsall.bat`, but the solution is VS 2010 format (`D2BS.sln:2-3`) and the project sets `WindowsTargetPlatformVersion 10.0` (`D2BS.vcxproj:20`).
* `Release/Build Instructions.txt:1` refers to `bob-18\dependencies\...`, an old checkout directory name.
* The vcxproj filters group files under `Spidermonkey Engine\...` (`D2BS.vcxproj.filters:19-37`). Files filtered as `Spidermonkey Engine\Core\C` (`Control.cpp`, `Core.cpp`, `dde.cpp`, `File.cpp`, `Game.cpp`, `Hash.cpp`, `MPQStats.cpp`, `Room.cpp`, `ScreenHook.cpp`, `Unit.cpp`, `Profile.cpp`) are mostly JS-free (§4). The filter names are not a coupling indicator.
* `jsfriendapi.h` is needed for the typed-array/ArrayBuffer functions (`JS_NewUint8Array` `ScriptEngine.cpp:746`, `JS_NewUint16Array` `JSRoom.cpp:153`, `JS_IsArrayBufferObject`/`JS_GetArrayBuffer*` `JSCore.cpp:584-591`).

### 6.3 `dependencies/` and what becomes removable

<!-- jsapi_inventory.py --section deps -->
| path | bytes |
|---|---|
| dependencies/include/js-config.h | 2195 |
| dependencies/include/js.msg | 36476 |
| dependencies/include/jsalloc.h | 2908 |
| dependencies/include/jsapi.h | 166904 |
| dependencies/include/jsclass.h | 14937 |
| dependencies/include/jsclist.h | 2616 |
| dependencies/include/jscpucfg.h | 3416 |
| dependencies/include/jsdbgapi.h | 15513 |
| dependencies/include/jsdhash.h | 25571 |
| dependencies/include/jsfriendapi.h | 46703 |
| dependencies/include/jslock.h | 1233 |
| dependencies/include/json.h | 1410 |
| dependencies/include/jsperf.h | 4358 |
| dependencies/include/jsprf.h | 3000 |
| dependencies/include/jsprototypes.h | 3278 |
| dependencies/include/jsproxy.h | 18230 |
| dependencies/include/jsprvtd.h | 7819 |
| dependencies/include/jspubtd.h | 12450 |
| dependencies/include/jstypes.h | 9439 |
| dependencies/include/jsutil.h | 12510 |
| dependencies/include/jsversion.h | 9053 |
| dependencies/include/jswrapper.h | 13397 |
| dependencies/libs/debug/mozjs.dll | 11860480 |
| dependencies/libs/debug/mozjs.lib | 469134 |
| dependencies/libs/release/generated.pdb | 5091328 |
| dependencies/libs/release/js_static.lib.desc | 11273 |
| dependencies/libs/release/js_static.zip | 22923617 |
| dependencies/include/js/* (15 files) | 238798 |
| dependencies/include/mozilla/* (31 files) | 194655 |
| **total** | 41202701 |
<!-- /jsapi_inventory.py -->

Everything under `dependencies/` is SpiderMonkey: headers (`include/`, `include/js/`, `include/mozilla/`), the debug DLL and import library, the zipped static release library with its object list (`js_static.lib.desc`), and `generated.pdb`. No non-JS code includes anything from it except through `js32.h` (§4.2). After the binding and engine layers are gone, the whole directory (~41 MB) can be removed, together with the `AdditionalDependencies` entries, the `XP_WIN;STATIC_JS_API;MOZILLA_STRICT_API` defines, the `dependencies\include\*` `ClInclude` items and the `Spidermonkey Engine\Engine Imports` filter. `sqlite3.c` (compiled as part of the project, `D2BS.vcxproj:271-281`) is JS-independent but has no consumer besides `JSSQLite.cpp` (§7.8).

---

## 7. Non-obvious couplings

### 7.1 String encoding

<!-- jsapi_inventory.py --section strings -->
| file | `JS_EncodeStringToUTF8` | `JS_EncodeString` | `JS_EncodeStringToBuffer` | `JS_GetStringCharsZ` | `JS_NewStringCopyZ` | `JS_NewUCStringCopyZ` | `JS_NewUCStringCopyN` | `JS_InternString` | `JS_InternUCString` | `JS_free` | `AnsiToUnicode` | `UnicodeToAnsi` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| File.cpp | 1 |  |  |  |  |  |  |  |  | 1 |  |  |
| js32.h |  |  |  | 1 | 1 | 1 |  |  |  |  |  |  |
| JSArea.cpp |  |  |  |  |  |  |  | 1 |  |  |  |  |
| JSControl.cpp |  |  |  | 2 |  | 2 |  |  | 1 |  |  |  |
| JSCore.cpp | 9 |  |  | 9 | 2 | 2 |  |  | 1 | 10 | 2 | 1 |
| JSDirectory.cpp |  |  |  | 4 |  | 4 |  |  | 1 |  |  | 2 |
| JSFile.cpp |  |  |  | 1 |  | 4 | 1 |  |  |  | 4 |  |
| JSFileTools.cpp |  |  |  | 9 |  |  | 1 |  |  |  | 1 |  |
| JSGame.cpp | 3 |  |  | 2 | 1 | 3 |  |  |  | 5 |  |  |
| JSHash.cpp | 5 |  |  | 5 | 5 |  |  | 5 |  | 5 |  |  |
| JSMenu.cpp |  |  |  | 8 |  |  |  |  |  |  |  |  |
| JSParty.cpp | 1 |  |  |  | 1 |  |  |  |  | 1 |  |  |
| JSProfile.cpp |  |  |  | 13 |  | 4 |  |  |  |  |  |  |
| JSSandbox.cpp | 5 |  |  | 2 |  |  |  |  |  | 9 |  |  |
| JSScreenHook.cpp |  |  |  | 4 |  |  |  |  | 2 |  |  |  |
| JSScript.cpp |  |  |  | 1 |  |  |  |  | 1 |  |  |  |
| JSSocket.cpp | 2 |  |  |  |  |  |  |  | 1 | 1 | 1 |  |
| JSSQLite.cpp | 5 |  |  | 1 |  | 5 |  | 1 |  | 10 | 4 |  |
| JSUnit.cpp | 4 |  |  | 2 | 7 | 4 |  | 7 | 3 | 6 | 1 | 2 |
| MPQStats.cpp |  |  |  |  | 2 |  |  |  |  |  |  |  |
| Script.cpp |  |  |  | 1 |  |  |  |  |  |  |  |  |
| ScriptEngine.cpp |  |  | 2 | 1 | 3 | 3 |  |  |  |  | 3 |  |
<!-- /jsapi_inventory.py -->

* SpiderMonkey strings are UTF-16 `jschar`. D2BS uses three different conversions:
  * `JS_GetStringCharsZ` returns a `const jschar*` that points into the GC'd string, used as `wchar_t*`. It is valid only while the string is alive (for arguments: for the duration of the call). Where the text must outlive the call, D2BS copies it, e.g. `my_login` into `Vars.szProfile` (`JSMenu.cpp:24-25`).
  * `JS_EncodeStringToUTF8` + `JS_free` for `char*` consumers (event names, SQL, packet data, file data).
  * `JS_NewStringCopyZ(char*)` for game `char*` strings (account, realm, game name: `JSUnit.cpp:67-104`, `JSUnit.cpp:131-135`). The SM22 header does not document how this decodes bytes (`dependencies/include/jsapi.h:4084`).
* The helper `AnsiToUnicode`/`UnicodeToAnsi` defaults to **CP_UTF8**, despite its name (`Helpers.h:9-10`). The same game text therefore reaches JS on different paths: unit names go `GetUnitName` -> `AnsiToUnicode` (UTF-8 decode) -> `JS_InternUCString` (`JSUnit.cpp:207-213`), while account names use `JS_NewStringCopyZ`. Outbound game text is converted with explicit `CP_ACP` in `stringToEUC` (`JSCore.cpp:43`), `Unit.overhead` (`JSUnit.cpp:1771`) and `Unit.getItem` (`JSUnit.cpp:1818`). Event text from the game is decoded with explicit `CP_ACP` before it is queued: whispers (`D2Handlers.cpp:466`), realm chat (`D2Handlers.cpp:537`), in-game chat (`D2NetHandlers.cpp:58`) and the `gameevent` name argument (`D2NetHandlers.cpp:123`); the queued `char*` arguments (nick, item code, `gameevent` name1) are later turned into JS strings with `JS_NewStringCopyZ` (`ScriptEngine.cpp:470`, `:499`, `:552`). So a unit name (UTF-8 decode) and the same player's chat nick (`JS_NewStringCopyZ` of the raw bytes) can arrive differently.
* `JS_free` is called on string literals in several fallbacks: `getUnit` (`JSUnit.cpp:582`, `:613-630`), `getParty` (`JSParty.cpp:96`, `:139`), `sendCopyData` (`JSCore.cpp:407`, `:415`), `sendDDE` (`JSCore.cpp:422`, `:444-447`). See §8.
* Script files are compiled as UTF-8 with a BOM strip (`js32.cpp:43-47`, `js32.cpp:53`). Console commands are wide strings (`ScriptEngine.cpp:697`).
* RPC consequence: the wire protocol needs one encoding (UTF-8), and the game-side conversions (`CP_ACP` for game text, UTF-8 elsewhere) have to be stated explicitly instead of being implied by which JSAPI string function a native happens to call.

### 7.2 Structured clone (inter-script messages, `load()` arguments)

<!-- jsapi_inventory.py --section clone -->
| file | line | code |
|---|---|---|
| Events.cpp | 157 | `evt->argv = new JSAutoStructuredCloneBuffer*[argc];` |
| Events.cpp | 159 | `evt->argv[i] = new JSAutoStructuredCloneBuffer;` |
| Events.cpp | 160 | `evt->argv[i]->write(helper->cx, helper->argv[i]);` |
| JSCore.cpp | 192 | `JSAutoStructuredCloneBuffer** autoBuffer = new JSAutoStructuredCloneBuffer*[argc - 1];` |
| JSCore.cpp | 194 | `autoBuffer[i - 1] = new JSAutoStructuredCloneBuffer;` |
| JSScript.cpp | 118 | `evt->argv = new JSAutoStructuredCloneBuffer*[argc];` |
| JSScript.cpp | 120 | `evt->argv[i] = new JSAutoStructuredCloneBuffer;` |
| JSScript.cpp | 121 | `evt->argv[i]->write(cx, JS_ARGV(cx, vp)[i]);` |
| Script.cpp | 15 | `Script::Script(const wchar_t* file, ScriptState state, uint argc, JSAutoStructuredCloneBuffer** argv)` |
| Script.cpp | 185 | `argv[i]->read(context, &argvalue[i]);` |
| Script.h | 27 | `JSAutoStructuredCloneBuffer** argv;` |
| Script.h | 116 | `JSAutoStructuredCloneBuffer** argv;` |
| Script.h | 128 | `Script(const wchar_t* file, ScriptState state, uint argc = 0, JSAutoStructuredCloneBuffer** argv = NULL);` |
| ScriptEngine.cpp | 31 | `Script* ScriptEngine::CompileFile(const wchar_t* file, ScriptState state, uint argc, JSAutoStructuredCloneBuffer** argv, bool recompile) {` |
| ScriptEngine.cpp | 715 | `evt->argv[i]->read(cx, &argv[i]);` |
| ScriptEngine.cpp | 730 | `evt->argv[i]->clear();` |
| ScriptEngine.h | 45 | `static Script* CompileFile(const wchar_t* file, ScriptState state, uint argc = 0, JSAutoStructuredCloneBuffer** argv = NULL, bool recompile = false);` |
<!-- /jsapi_inventory.py -->

* Three producers: `load(file, ...args)` clones the extra arguments into `Script::argv` (`JSCore.cpp:192-198`), `scriptBroadcast(...)` clones per receiving script (`Events.cpp:157-161`), and `D2BSScript.send(...)` clones into the target's event (`JSScript.cpp:117-122`).
* Two consumers: `Script::Run` reads `load` arguments into the new runtime before calling `main` (`Script.cpp:183-186`), and `ExecScriptEvent("scriptmsg")` reads, calls the listeners, then `clear()`s and deletes the buffers (`ScriptEngine.cpp:713-732`).
* Each script has its **own `JSRuntime`** (`Script.cpp:120`), so every message is written on the sender's thread and runtime and read on the receiver's. The clone buffer is the only thing that crosses runtimes. No `JSStructuredCloneCallbacks` are passed, so D2BS objects (`Unit`, `Room`, hooks, ...) cannot be cloned. Only plain data survives. The return value of `write()` is ignored at all three sites.
* `load` argument buffers are never freed (the cleanup is commented out "crashes", `Script.cpp:201-205`).
* This is the existing "message bus" between scripts. An RPC design that keeps multiple clients or scripts needs its own serialisation (e.g. JSON) with the same "plain data only" contract.

### 7.3 JS values and objects stored in C++

Combining the §4.4 member list with the void-pointer cases:

| holder | JS state | rooted? | lifetime owner |
|---|---|---|---|
| `Script::functions` (`FunctionMap`, `Script.h:136`) | listener functions as `AutoRoot*` | yes: the `AutoRoot` ctor calls `Take()` (`AutoRoot.cpp:4-5`), which does `JS_AddNamedValueRoot` (`AutoRoot.cpp:24`); `~AutoRoot` removes it (`AutoRoot.cpp:17-19`) | `UnregisterEvent`/`ClearEvent` (`Script.cpp:378-410`) |
| `Event::arg3` for timers | `new jsval(fn)` (`JSCore.cpp:91`, `:111`) | the copy itself is not rooted; the same function is rooted through `RegisterEvent("setTimeout"/"setInterval", fn)` (`JSCore.cpp:87`, `:107`) | `ScriptEngine::RemoveDelayedEvent` (`ScriptEngine.cpp:818-836`) |
| `Event::functions` for hook clicks/hovers | `AutoRoot` created on the **game thread** (`ScreenHook.cpp:231`, `:257`) | yes, cross-thread (§7.4) | deleted by the game thread after the wait (`ScreenHook.cpp:243`) |
| `Genhook::clicked` (`ScreenHook.h:40`) | click handler | **no** (rooting commented out, `ScreenHook.cpp:280-290`) | the hook |
| `Genhook::hovered` | hover handler | `JS_AddRoot` on the jsval slot (`ScreenHook.cpp:307`); **never removed** in `~Genhook` (`ScreenHook.cpp:189-212`) | the hook |
| `Genhook::self` (`ScreenHook.h:41`) | the hook's own JS object | no (commented out, `ScreenHook.cpp:180-181`) | JS GC (finalizer deletes the hook) |
| `JSPathReducer::reject/reduce/mutate` (`Map/Path/Reduction/JSPathReducer.h:18`) | JS callbacks for `getPath(..., 3, ...)` | yes (`Map/Path/Reduction/JSPathReducer.h:24-26`), but members `cx` and `obj` are **never initialised**: the constructor parameters shadow them (`Map/Path/Reduction/JSPathReducer.h:23`), and `Reduce`/`Reject`/`MutatePoint`/the destructor use the members (`Map/Path/Reduction/JSPathReducer.h:29-31`, `:57`, `:68`, `:86`) | `new` in `my_getPath`, deleted at its end (`JSGame.cpp:271`, `:319`) |
| `myArea::ExitArray` (`JSArea.h:29`) | cached exits array | rooted only while being built, then `JS_RemoveRoot` right after the first read (`JSArea.cpp:36`, `:64-65`) | `area_finalize` deletes the struct (`JSArea.cpp:9-17`) |
| `DBStmt::current_row` (`JSSQLite.cpp:41`) | current row object | `JS_AddRoot` (`JSSQLite.cpp:363-364`); removed on `next()`/`close()` (`JSSQLite.cpp:503-505`, `:544-545`) but **not** in `sqlite_stmt_finalize` (commented out, `JSSQLite.cpp:583-584`) | statement finalizer |
| `sandbox::context/innerObj` (`JSSandbox.h:21-22`) | a second context in `ScriptEngine::GetRuntime()` | no | `sandbox_finalize` (`JSSandbox.cpp:164-171`) |
| DialogLine reserved slot 0 | raw `TransactionDialogsLine_t*` into game memory (`JSGame.cpp:200`) | n/a (private value) | game; no finalizer (`JSGlobalClasses.cpp:120-122`) |
| `Room`, `Party`, `D2BSScript` private data | raw `Room2*` (`JSRoom.cpp:476`), `RosterUnit*` (`JSParty.cpp:145`), `Script*` (`JSScript.cpp:180`) | n/a | game / engine; their classes have no finalizer (`JSGlobalClasses.cpp:40-42`, `:68-70`, `:76-78`) |
| `Unit`, `PresetUnit`, `Control`, `Exit`, `Area` private data | heap **copies** of identity fields (`myUnit`/`invUnit` type+id, `ControlData`, ...), re-resolved on every call (`D2CLIENT_FindUnit`, `findControl`) | n/a | finalizers delete the copies |

For RPC: the `Unit` model (identity tuple, re-resolved per call) maps directly onto opaque handles. `Room`/`Party`/`D2BSScript` hand out raw pointers that can go stale; an RPC layer must not copy that pattern.

### 7.4 Roots and cross-thread JSAPI use

Every explicit root add/remove site and `AutoRoot` construction:

<!-- jsapi_inventory.py --section roots -->
| file | line | call | rooted address / args | storage |
|---|---|---|---|---|
| AutoRoot.cpp | 18 | JS_RemoveValueRoot | `&var` | heap (C++ object member) |
| AutoRoot.cpp | 24 | JS_AddNamedValueRoot | `&var` | heap (C++ object member) |
| JSArea.cpp | 36 | JS_AddRoot | `&pArea->ExitArray` | heap (C++ object member) |
| JSArea.cpp | 65 | JS_RemoveRoot | `&pArea->ExitArray` | heap (C++ object member) |
| JSControl.cpp | 335 | JS_AddRoot | `&pReturnArray` | stack local |
| JSControl.cpp | 351 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSGame.cpp | 186 | JS_AddObjectRoot | `&pReturnArray` | stack local |
| JSGame.cpp | 208 | JS_RemoveObjectRoot | `&pReturnArray` | stack local |
| JSGame.cpp | 920 | JS_AddRoot | `&pObj` | stack local |
| JSGame.cpp | 928 | JS_AddRoot | `&pObj` | stack local |
| JSGame.cpp | 934 | JS_RemoveRoot | `&pObj` | stack local |
| JSGame.cpp | 1320 | JS_AddRoot | `&pObj` | stack local |
| JSGame.cpp | 1330 | JS_AddRoot | `&pObj` | stack local |
| JSGame.cpp | 1340 | JS_RemoveRoot | `&pObj` | stack local |
| JSPresetUnit.cpp | 86 | JS_AddRoot | `&pReturnArray` | stack local |
| JSPresetUnit.cpp | 130 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSRoom.cpp | 101 | JS_AddRoot | `&pReturnArray` | stack local |
| JSRoom.cpp | 132 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSRoom.cpp | 154 | JS_AddRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 163 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 192 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 208 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 226 | JS_AddRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 239 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 269 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 285 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSRoom.cpp | 297 | JS_RemoveRoot | `&jsobjy` | stack local |
| JSSQLite.cpp | 364 | JS_AddRoot | `&stmtobj->current_row` | heap (C++ object member) |
| JSSQLite.cpp | 504 | JS_RemoveRoot | `&stmtobj->current_row` | heap (C++ object member) |
| JSSQLite.cpp | 545 | JS_RemoveRoot | `&stmtobj->current_row` | heap (C++ object member) |
| JSSandbox.cpp | 30 | JS_AddRoot | `&res` | stack local |
| JSSandbox.cpp | 36 | JS_RemoveRoot | `&box->innerObj` | heap (C++ object member) |
| JSSandbox.cpp | 42 | JS_RemoveRoot | `&res` | stack local |
| JSScript.cpp | 194 | JS_AddRoot | `&pReturnArray` | stack local |
| JSScript.cpp | 206 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSUnit.cpp | 952 | JS_AddRoot | `&pArrayInsert` | stack local |
| JSUnit.cpp | 968 | JS_RemoveRoot | `&pArrayInsert` | stack local |
| JSUnit.cpp | 1048 | JS_AddRoot | `&arr` | stack local |
| JSUnit.cpp | 1053 | JS_RemoveRoot | `&arr` | stack local |
| JSUnit.cpp | 1312 | JS_AddRoot | `&pReturnArray` | stack local |
| JSUnit.cpp | 1334 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSUnit.cpp | 1342 | JS_RemoveRoot | `&pReturnArray` | stack local |
| JSUnit.cpp | 1420 | JS_AddRoot | `&pArrayInsert` | stack local |
| JSUnit.cpp | 1436 | JS_RemoveRoot | `&pArrayInsert` | stack local |
| Map/Path/Reduction/JSPathReducer.h | 24 | JS_AddRoot | `&reject` | heap (C++ object member) |
| Map/Path/Reduction/JSPathReducer.h | 25 | JS_AddRoot | `&reduce` | heap (C++ object member) |
| Map/Path/Reduction/JSPathReducer.h | 26 | JS_AddRoot | `&mutate` | heap (C++ object member) |
| Map/Path/Reduction/JSPathReducer.h | 29 | JS_RemoveRoot | `&reject` | heap (C++ object member) |
| Map/Path/Reduction/JSPathReducer.h | 30 | JS_RemoveRoot | `&reduce` | heap (C++ object member) |
| Map/Path/Reduction/JSPathReducer.h | 31 | JS_RemoveRoot | `&mutate` | heap (C++ object member) |
| ScreenHook.cpp | 231 | new AutoRoot | `evt->owner->GetContext(), clicked` | heap (AutoRoot::var) |
| ScreenHook.cpp | 257 | new AutoRoot | `(owner->GetContext(), hovered)` | heap (AutoRoot::var) |
| ScreenHook.cpp | 303 | JS_RemoveRoot | `&hovered` | heap (C++ object member) |
| ScreenHook.cpp | 307 | JS_AddRoot | `&hovered` | heap (C++ object member) |
| Script.cpp | 153 | JS_AddNamedScriptRoot | `&script` | heap (C++ object member) |
| Script.cpp | 165 | JS_RemoveRoot | `&scriptObject` | heap (C++ object member) |
| Script.cpp | 188 | JS_AddValueRoot | `&argvalue[j]` | heap (new jsval[]) |
| Script.cpp | 190 | JS_AddValueRoot | `&main` | stack local |
| Script.cpp | 191 | JS_AddValueRoot | `&dummy` | stack local |
| Script.cpp | 196 | JS_RemoveValueRoot | `&main` | stack local |
| Script.cpp | 197 | JS_RemoveValueRoot | `&dummy` | stack local |
| Script.cpp | 199 | JS_RemoveValueRoot | `&argvalue[j]` | heap (new jsval[]) |
| Script.cpp | 355 | new AutoRoot | `context, evtFunc` | heap (AutoRoot::var) |
| Script.cpp | 459 | JS_AddNamedValueRoot | `&rval` | stack local |
| Script.cpp | 467 | JS_RemoveRoot | `&rval` | stack local |
| ScriptEngine.cpp | 473 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 482 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 503 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 511 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 530 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 538 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 556 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 565 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 586 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 598 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 616 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 624 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 641 | JS_AddValueRoot | `&argv[0]` | heap (new jsval[]) |
| ScriptEngine.cpp | 648 | JS_RemoveValueRoot | `&argv[0]` | heap (new jsval[]) |
| ScriptEngine.cpp | 669 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 680 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 718 | JS_AddValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 727 | JS_RemoveValueRoot | `&argv[j]` | heap (new jsval[]) |
| ScriptEngine.cpp | 749 | JS_AddRoot | `&arr` | stack local |
| ScriptEngine.cpp | 764 | JS_RemoveRoot | `&arr` | stack local |
| js32.cpp | 15 | JS_AddObjectRoot | `&obj` | stack local |
| js32.cpp | 24 | JS_RemoveObjectRoot | `&obj` | stack local |
| js32.cpp | 55 | JS_AddNamedScriptRoot | `&rval` | stack local |
| js32.cpp | 56 | JS_RemoveScriptRoot | `&rval` | stack local |
| js32.h | 84 | JS_AddValueRoot | `ref` | heap (C++ object member) |
| js32.h | 87 | JS_RemoveValueRoot | `ref` | heap (C++ object member) |

Stack-slot roots that stay registered on an early exit (return/throw reachable after the add and before the matching remove, statement start lines):

| add site | call | early exits |
|---|---|---|
| JSGame.cpp:920 | `JS_AddRoot(&pObj)` | JSGame.cpp:921, JSGame.cpp:923 |
| JSGame.cpp:1320 | `JS_AddRoot(&pObj)` | JSGame.cpp:1321, JSGame.cpp:1323, JSGame.cpp:1325 |
| JSPresetUnit.cpp:86 | `JS_AddRoot(&pReturnArray)` | JSPresetUnit.cpp:113 |
| JSRoom.cpp:101 | `JS_AddRoot(&pReturnArray)` | JSRoom.cpp:117 |
| JSRoom.cpp:154 | `JS_AddRoot(&jsobjy)` | JSRoom.cpp:156 |
| JSRoom.cpp:226 | `JS_AddRoot(&jsobjy)` | JSRoom.cpp:227 |
| JSSandbox.cpp:30 | `JS_AddRoot(&res)` | JSSandbox.cpp:39 |
| JSUnit.cpp:952 | `JS_AddRoot(&pArrayInsert)` | JSUnit.cpp:954 |
| JSUnit.cpp:1420 | `JS_AddRoot(&pArrayInsert)` | JSUnit.cpp:1422 |
<!-- /jsapi_inventory.py -->

Cross-thread or unsafe patterns:

* **Hook click dispatch roots on the game thread.** `Genhook::Click` runs inside the game's input handling (called from `D2Handlers.cpp:316-334`). It does `new AutoRoot(owner->GetContext(), clicked)`, which calls `JS_AddNamedValueRoot` on the *script's* runtime from the game thread. It then waits up to 3 s on `Vars.eventSignal` and `delete`s the root, `JS_RemoveValueRoot` again from the game thread (`ScreenHook.cpp:219-244`). On timeout it returns early and leaks the event and the root (`ScreenHook.cpp:235-236`).
* **Hover dispatch** would build `new AutoRoot((owner->GetContext(), hovered))`. The comma operator makes this the one-argument `AutoRoot(jsval)` constructor, which uses `ScriptEngine::GetGlobalContext()`, and that is always NULL (§7.9) (`ScreenHook.cpp:257`, `AutoRoot.cpp:7`). The caller is commented out (`D2Handlers.cpp:343`), so the path is currently dead.
* **Dangling roots**: `Genhook::hovered` stays registered after the hook is deleted (`ScreenHook.cpp:189-212`), and `DBStmt::current_row` stays registered after statement finalization (`JSSQLite.cpp:577-588`). Stack-slot roots stay registered on the early exits listed in the second table above (9 add sites in `getTextSize`, `getMouseCoords`, `getPresetUnits`, `Room.getPresetUnits`, `Room.getCollisionA`, `Room.getCollision`, `new Sandbox()`, `Unit.getStat(-1)`, `Unit.getSkill`). In `new Sandbox()` the failure path removes `&box->innerObj`, which was never rooted, instead of `&res` (`JSSandbox.cpp:35-39`). A root left on a dead stack slot or freed heap object makes the next GC read that memory as a GC pointer.
* **Listener lookup without lock**: game-thread fan-out calls `script->IsListenerRegistered(...)` (e.g. `Events.cpp:6`, `:45`, `:151`), which reads `Script::functions` (`Script.cpp:348-350`) while the script thread may modify it under `Script::lock` (`Script.cpp:352-358`).
* **Cross-runtime reads**: `D2BSScript.memory` calls `JS_GetGCParameter` on another script's runtime from the caller's thread (`JSScript.cpp:41-42`). `Script::TriggerOperationCallback` (`Script.h:171-174`) is called from other threads; that is the one JSAPI entry point designed for cross-thread use (`dependencies/include/jsapi.h:4010-4030`).
* `ScriptEngine::DisposeScript` avoids cross-thread destruction by posting a `DisposeMe` event to the owning thread (`ScriptEngine.cpp:81-89`).

Thread and request topology is detailed in [embedding.md §7](embedding.md#7-gc-rooting-and-thread-rules).

### 7.5 Event dispatch rides on the JS engine

These are the coupling facts only; the full mechanics are in [embedding.md §6](embedding.md#6-events-and-timers-integration) and [../js-api/events.md](../js-api/events.md).

* Game-side producers (`Events.cpp`, `ScreenHook.cpp`) push `Event` objects onto `Script::EventList` and call `JS_TriggerOperationCallback(runtime)` (`Script.cpp:419-430`, `Script.h:171-174`).
* Listeners run only at three kinds of points:
  * inside the **operation callback**, in the middle of whatever JS code the script is running (`ScriptEngine.cpp:315-323`);
  * inside `delay()` (`JSCore.cpp:145-151`);
  * inside `SetSkill` (`D2Helpers.cpp:275-281`).

  Packet events are the one exception: they run synchronously when the producer is already on the script's own thread (`Events.cpp:306-307`). A script that never calls back into the engine never sees an event.
* **Blocking events** ("…blocker", game/realm packets, hook clicks) make the game thread wait on the single shared manual-reset `Vars.eventSignal` (`Helpers.cpp:155`): 1 s for key blockers (`Events.cpp:66`), 0.5 s for chat blockers (`Events.cpp:200`), 0.5 s for packets with the game lock released (`Events.cpp:309-317`), 3 s for hook clicks (`ScreenHook.cpp:235`). The script thread writes the verdict into `evt->arg4` and calls `SetEvent` (`ScriptEngine.cpp:567-569`, `:650-652`, `:682-683`, `:763-765`). One event object is shared by all scripts and all blocker kinds.
* **Timers** are Win32 waitable timers with an APC completion routine (`ScriptEngine.cpp:798-816`, `ScriptEngine.cpp:837-840`). The APC runs only while the creating script thread is in an alertable wait, i.e. inside `delay()` (`WaitForSingleObjectEx(..., TRUE)`, `JSCore.cpp:140`) or `SetSkill` (`D2Helpers.cpp:273`).
* For RPC, every one of these points needs a non-JS equivalent: an event queue per client, request/response with deadlines for blocking events, and timers that do not depend on an alertable JS thread.

### 7.6 GC finalizers that own game-side or OS resources

Finalizers (rows of kind `FINALIZER` in §5.1) decide when native resources are released, so resource lifetime follows JS garbage collection:

| class | finalizer | what is released | consequence |
|---|---|---|---|
| Frame/Box/Line/Text/Image | `hook_finalize` `JSScreenHook.cpp:8` | `delete Genhook` (removes the on-screen hook) | an unreferenced hook stays drawn until a GC runs, unless `remove()` is called (`JSScreenHook.cpp:18-34`) |
| File | `file_finalize` `JSFile.cpp:570` | `fclose` / unlock of the `FILE*` | file handles stay open until GC |
| Socket | `socket_finalize` `JSSocket.cpp:167` | `closesocket` + `WSACleanup` per socket; `SocketData` itself is leaked | sockets stay open until GC |
| SQLite / DBStatement | `sqlite_finalize` `JSSQLite.cpp:280`, `sqlite_stmt_finalize` `JSSQLite.cpp:577` | `sqlite3_close`, `sqlite3_finalize` | database handles stay open until GC. The explicit `DBStatement.close()` deletes its `DBStmt` without erasing it from `assoc_db->stmts` (`JSSQLite.cpp:541-549`; only the finalizer erases, `JSSQLite.cpp:582`), so a later `SQLite.close()`/finalize or the `SQLite` getter walks a freed pointer (`JSSQLite.cpp:49-51`, `:263-264`). That getter also wraps each live `DBStmt*` in a fresh `DBStatement` object (`JSSQLite.cpp:265`), so two JS objects, and two finalizers, own the same struct |
| Sandbox | `sandbox_finalize` `JSSandbox.cpp:164` | `JS_DestroyContext` | |
| Unit/Area/Control/Exit/PresetUnit/Profile/Folder | `unit_finalize` `JSUnit.cpp:13`, `area_finalize` `JSArea.cpp:9`, `control_finalize` `JSControl.cpp:8`, `exit_finalize` `JSExits.cpp:5`, `presetunit_finalize` `JSPresetUnit.cpp:9`, `profile_finalize` `JSProfile.cpp:105`, `dir_finalize` `JSDirectory.cpp:227` | the heap copy of the private struct | memory only |

When a script's context is destroyed, `contextCallback(JSCONTEXT_DESTROY)` drains the event queue, clears listeners and calls `Genhook::Clean` (`ScriptEngine.cpp:376-389`). `Genhook::Clean` only unlinks hooks from the lists without deleting them (`ScreenHook.cpp:144-170`), so the final `delete` again comes from the finalizers during `JS_DestroyRuntime`.

### 7.7 Error semantics

* `THROW_ERROR` = `JS_ReportError` + `return JS_FALSE` (`js32.h:113-117`): a catchable exception.
* `THROW_WARNING` = `JS_ReportWarning`, rval `false`, `return JS_TRUE` (`js32.h:118-123`). This is how all "Game not ready" conditions surface (flag W natives).
* A bare `return JS_FALSE` without a pending exception terminates the script uncatchably. §5.1 column "bare JS_FALSE" counts them. Notable cases:
  * property getters `area_getProperty` (`JSArea.cpp:22-27`) and `control_getProperty`/`control_setProperty` (`JSControl.cpp:18-27`, `JSControl.cpp:98-106`);
  * `my_getPath` when the level is not loaded (`JSGame.cpp:252-253`);
  * `stop()`, which returns `JS_FALSE` on purpose (`JSCore.cpp:246`).
* A native that returns `JS_TRUE` without storing a return value leaves whatever is in `vp[0]`. `JS_CALLEE` and `JS_RVAL` are the same slot (`dependencies/include/js/CallArgs.h:317`, `:320`), the callee must be read before the rval is touched (`dependencies/include/js/CallArgs.h:60-63`), and the header calls the initial rval contents unspecified and says a successful native *must* set it (`dependencies/include/js/CallArgs.h:133-143`). The last table of §5.1 lists the natives that do not, e.g. `delay()`, `addEventListener()`, `copy()`, `FileTools.remove/rename/copy()`, `Socket.send/close()`, `sqlite_memusage()`, `revealLevel()`, `takeScreenshot()`, and early exits of `getSkillByName()`, `getLocaleString()`, the `Room` methods and `Control.*`. What JS actually receives there is not specified by the header; an RPC schema has to define these results explicitly instead of inheriting them.
* All errors go through `reportError` (`ScriptEngine.cpp:428-450`): it logs, prints, and with `QuitOnError` exits the game (`ScriptEngine.cpp:446-447`).
* For RPC these become three distinct outcomes: error result, "not ready" result, and "session terminated".

### 7.8 Classes whose only consumer is JS

`File`, `FileTools`, `Folder`/`dopen`, `SQLite`/`DBStatement`, `Socket`, `Sandbox`, and the hash functions with their `_file` variants have no non-JS callers. `File.cpp`'s `readLine`, `writeValue`, `fileOpenRelScript`, `getPathRelScript` and `isValidPath` are used only by `JS*.cpp` files and `File.cpp` itself (checked with `grep -lw`). `sqlite3.c` is compiled into the DLL solely for `JSSQLite.cpp`. An RPC client has its own file, SQL and socket facilities, so these classes can be dropped rather than ported. The script-path sandbox (`isValidPath`, `File.cpp:258`; `getPathRelScript`, `File.cpp:220`) is the only security-relevant piece. See [../js-api/utility-classes.md](../js-api/utility-classes.md).

### 7.9 Engine statics that are never initialised

`ScriptEngine::runtime` and `ScriptEngine::context` are defined as NULL (`ScriptEngine.cpp:19`, `:26`) and are never assigned anywhere in the source. Each script creates its own runtime and context instead (`Script.cpp:120-125`). Consequences:

* `AutoRoot(jsval)` roots with a NULL context (`AutoRoot.cpp:7-9`).
* `new Sandbox()` calls `JS_NewContext(NULL, 0x2000)` (`JSSandbox.cpp:8`).
* `ScriptEngine::Shutdown` never reaches `JS_DestroyContext/JS_DestroyRuntime/JS_ShutDown` (`ScriptEngine.cpp:155-160`).

---

## 8. Findings

Bugs and quirks found while building the inventory. Each is cited; where another doc covers the API in depth it is linked.

1. **JSPathReducer uses uninitialised `cx`/`obj`**: constructor parameters shadow the members (`Map/Path/Reduction/JSPathReducer.h:16-17`, `:23-27`). `getPath` with reduction type 3 (`JSGame.cpp:271`) calls `JS_CallFunctionValue` with a garbage context (`Map/Path/Reduction/JSPathReducer.h:57`, `:68`, `:86`).
2. **Use-after-free in `ExecScriptEvent("Command")`**: the branch frees `evt->name` and `evt` but has no `return` (`ScriptEngine.cpp:687-708`). Execution falls through to `strcmp(evtName, ...)` on freed memory (`ScriptEngine.cpp:709`, `:738`, `:776`, `:792`). With `clearList == true` the `Command` branch also uses an uninitialised `cx` (`ScriptEngine.cpp:453-456`, `:694`).
3. **Every timer fires every callback**: `ExecScriptEvent("setTimeout"/"setInterval")` calls *all* functions registered under that name (`ScriptEngine.cpp:780-782`), not just the timer's own callback (`JSCore.cpp:87`, `:91`).
4. **Unbalanced critical section**: `ScriptEngine::RemoveDelayedEvent` calls `LeaveCriticalSection(&Vars.cEventSection)` without entering it (`ScriptEngine.cpp:818-836`). It is reached from `clearTimeout/clearInterval` (`JSCore.cpp:122`) and from timeout expiry (`ScriptEngine.cpp:787`).
5. **`Genhook::Clean` erases a `visible` iterator from `invisible`** (`ScreenHook.cpp:151-155`). This is undefined behaviour on the `JSCONTEXT_DESTROY` path (`ScriptEngine.cpp:388`).
6. **Dangling GC roots**: `Genhook::hovered` (`ScreenHook.cpp:307` vs `~Genhook` `ScreenHook.cpp:189-212`) and `DBStmt::current_row` (`JSSQLite.cpp:364` vs `JSSQLite.cpp:583-584`). Stack roots stay registered on the early exits listed in §7.4 (9 add sites, e.g. `JSGame.cpp:920-923`, `JSGame.cpp:1320-1325`, `JSRoom.cpp:154-156`); `new Sandbox()` removes the wrong root on failure (`JSSandbox.cpp:36`).
7. **Unrooted cached JS objects**: `myArea::ExitArray` is unrooted after the first `area.exits` read (`JSArea.cpp:64-65`) but returned again on later reads (`JSArea.cpp:63`). `Genhook::clicked` is never rooted (`ScreenHook.cpp:279-290`).
8. **Game-loop lock leak** on OOM paths `JSRoom.cpp:156-157` and `JSRoom.cpp:227-228` (§5.4).
9. **`ScriptEngine::runtime/context` never set** (`ScriptEngine.cpp:19`, `:26`). Effects: `new Sandbox()` passes a NULL runtime (`JSSandbox.cpp:8`), `AutoRoot(jsval)` gets a NULL cx (`AutoRoot.cpp:7`), and `JS_ShutDown` is never called (`ScriptEngine.cpp:155-160`).
10. **Comma-operator bug** `new AutoRoot((owner->GetContext(), hovered))` (`ScreenHook.cpp:257`). Dead path today (`D2Handlers.cpp:343`).
11. **JIT options overwritten**: `contextCallback` enables METHODJIT/TI/ION/ASMJS (`ScriptEngine.cpp:337`), then `Script::Run` immediately re-sets the options to `STRICT|VAROBJFIX` (`Script.cpp:131`) after `JS_NewContext` returns (`Script.cpp:125`).
12. **`JS_free` on string literals** (fallback paths): `JSUnit.cpp:582` + `:613/:620/:630`, `JSParty.cpp:96` + `:139`, `JSCore.cpp:407` + `:415`, `JSCore.cpp:422` + `:444-447`.
13. **`sendDDE` reads the mode from the wrong argument**: it tests `argv[0]` and converts `argv[1]` (`JSCore.cpp:425-426`); `mode` is uninitialised otherwise (`JSCore.cpp:421`).
14. **`getSkillByName` always throws for a non-empty name**: inverted test `if (!lpszText || lpszText[0])` (`JSGame.cpp:867`).
15. **`sqlite_memusage()` never returns the memory figure**: it computes into a local `jsval` copy that is never stored back (`JSSQLite.cpp:72-76`), so the call returns the unset rval slot, which the header calls unspecified (§7.7).
16. **`Sandbox.include` is a no-op**: `box->list.count(...) == -1` is never true (`JSSandbox.cpp:196`).
17. **`load()` with no argument**: `new JSAutoStructuredCloneBuffer*[argc - 1]` with `argc == 0` underflows (`JSCore.cpp:192`), and `argv[0]` is read without a check (`JSCore.cpp:177`).
18. **`Unit.getStat(-1)` stack overflow risk**: `aStatList[256]` is appended past `D2COMMON_CopyStatList`'s count without a bound (`JSUnit.cpp:925`, `:934-947`). In `InsertStatsNow` the array append writes at `len+1`, leaving holes (`JSUnit.cpp:1058-1063`).
19. **`ExecScriptEvent` leaks every `argv` array** (`new jsval[...]` never deleted, e.g. `ScriptEngine.cpp:465`, `:494`, `:524`, `:550`, `:580`, `:608`, `:638`, `:663`, `:713`). `itemaction` reads an uninitialised `bool block` (`ScriptEngine.cpp:475`, `:478`). `ScreenHookHover` passes `evt->argc + 1` (=3) arguments from a 2-element array (`ScriptEngine.cpp:591`).
20. **`Event::threadFinished` deletes `this` and then calls `Event::~Event()` again** (`Script.h:100-101`). The function is never called (no reference outside `Script.h`).
21. **`Script::Include` returns with `Script::lock` held** when `_wcsdup` fails (`Script.cpp:298-301`). `Script::Run`'s catch block leaves a critical section it never entered (`Script.cpp:170`). `RunCommandThread` removes a value root with the object-root macro (`Script.cpp:459`, `:467`); it is dead code, its `CreateThread` is commented out (`Script.cpp:89`).
22. **Requests are unbalanced on early returns** in many natives (e.g. `unit_getProperty` enters a request at `JSUnit.cpp:52` and returns without `JS_EndRequest` at `JSUnit.cpp:69`, `:75`, `:102`). Harmless only if requests are no-ops in this build (§10).
23. **`DailogLine`** typo in the JS class name (`JSGlobalClasses.cpp:121`). `profileType_class`/`dialogLine_class` are not in `global_classes`, so they have no constructor on the global object (`JSGlobalClasses.cpp:143-168`). `dialogLine_class` is still used through `BuildObject` (`JSGame.cpp:191`); `profileType_class`, `profileType_props` and their natives `profileType_ctor`/`profileType_getProperty` (`JSProfile.cpp:154-156`) are referenced by nothing live (the row is commented out, `JSGlobalClasses.cpp:184`), so the `ProfileType` constants are unreachable from scripts.
24. **Declared but undefined engine symbols**: `ScriptEngine::ExecEventAsync` (`ScriptEngine.h:63`), `callEventFunction`, `FuncThread`, `EventThread` (`Script.h:216-218`), `GameMsgEvent`, `GoldDropEvent` (`Events.h:10`, `:18`), `unit_equal` (`JSUnit.h:42`), `file_equality` (`JSFile.h:11`), `sqlite_equal` (`JSSQLite.h:18`), `socket_equality` (`JSSocket.h:11`) (their bodies are commented out, e.g. `JSFile.cpp:41`, `JSSQLite.cpp:290`, `JSUnit.cpp:33`), `ScriptEngine::gcCallback` (`ScriptEngine.h:70`). There is no linker error only because none of them is called.
25. **`tinyid` headroom**: `me` property ids reach 125 (`JSUnit.h:121-158`) in an `int8_t` field (`dependencies/include/jsapi.h:3030`).
26. **`keyupblocker` listeners stall the game for 1 s per key release and are never called**: `KeyEventCallback` fires `keyupblocker` and waits on `Vars.eventSignal` (`Events.cpp:55-67`), but `ExecScriptEvent` only handles `keydownblocker` (`ScriptEngine.cpp:634-658`), so nobody signals.
27. **Build**: the Packaging configuration links a non-existent `dependencies\libs\release\mozjs.lib` (`D2BS.vcxproj:230`). The vcxproj references 5 missing SpiderMonkey headers/tables and 3 out-of-tree headers (`D2BS.vcxproj:328-330`, `:362-369`, `:418`). `build.bat` uses the VS 2008 environment (`build.bat:1`). Release disables C++ EH (`D2BS.vcxproj:157`) although the engine uses `try/catch`.
28. **`GetLevel` leaks the game-loop lock** when `!GameReady()`: `new AutoCriticalRoom` at `D2Helpers.cpp:173`, `return nullptr` at `D2Helpers.cpp:176` without `delete cRoom`. 8 natives call it (§5.4).
29. **`clickItem(type, unit)` on a belt item passes swapped arguments** to `D2CLIENT_ClickBeltRight`: `(pInventory, pPlayer, shift, pos)` at `JSGame.cpp:539` versus the macro's `(pPlayer, pInventory, dwShift, dwPotPos)` (`D2Ptrs.h:502`).
30. **`getPath` leaks its point array**: `jsval* vec = new jsval[count]` (`JSGame.cpp:303`) is never deleted, and its elements are not registered as roots while later `BuildObject` calls allocate (`JSGame.cpp:304-312`). `JSPathReducer::Reduce` has the same unrooted pattern but frees the array (`Map/Path/Reduction/JSPathReducer.h:40-63`).
31. **Arguments read past `argc`**: `acceptTrade()` with no argument reads `argv[0]` (`JSGame.cpp:115`), `getPath` with reduction type 3 reads `argv[7..9]` after only checking `argc >= 5` (`JSGame.cpp:233`, `:244`), `moveNPC` reads `argv[2]` after checking `argc >= 2` (`JSGame.cpp:1429`, `:1439`). The bundled headers do not define what those slots hold.
32. **Natives that do not set a return value** on some or all successful paths (last table of §5.1, §7.7); their JS-visible result is unspecified by the header.
33. **SQLite statement lifetime**: `DBStatement.close()` frees its `DBStmt` but leaves it in `assoc_db->stmts` (`JSSQLite.cpp:541-549`), and `db.statements` wraps each `DBStmt*` in a new JS object (`JSSQLite.cpp:265`), so one struct can be reached after free or finalized twice (§7.6).

---

## 9. Legacy-doc discrepancies

| topic | legacy docs | code |
|---|---|---|
| `scriptBroadcast` recipients | "Broadcast a message to all other scripts" (`doc/globalFuncs.h:1081-1086`) | iterates all scripts including the sender; any script with a `scriptmsg` listener receives it (`Events.cpp:148-171`) |
| `load()` return value | returns `D2BSScript` (`doc/globalFuncs.h:793`) | returns `null` on success and failure; the object construction is commented out (`JSCore.cpp:202-207`) |
| `sqlite_memusage()` | returns `double` memory usage (`doc/globalFuncs.h:1096-1100`) | never stores a return value; the result is the unset rval slot (`JSSQLite.cpp:72-76`, §7.7) |
| `Sandbox` | documented as working (`doc/Sandbox.h:1-40`), method `isInclude` | constructor uses a NULL runtime (`JSSandbox.cpp:8`); method is `isIncluded` (`JSSandbox.h:27`); `include` never runs (`JSSandbox.cpp:196`); `clearScope` is empty (`JSSandbox.cpp:228-233`) |
| timers | `setTimeout`/`setInterval` absent from `doc/*.h` and `README.md` (0 matches); present in `resources/api.html` (15 occurrences on 11 lines) | registered in `JSGlobalFuncs.h:41-42` |

---

## 10. Open questions

* **Is the bundled engine safe for one runtime per thread?** `dependencies/include/js-config.h:16` has `JS_THREADSAFE` undefined, and the static library was built from `build-unsafe` (`dependencies/libs/release/js_static.lib.desc`). D2BS nevertheless creates one `JSRuntime` per script thread (`Script.cpp:120`). Whether SpiderMonkey 22 without `JS_THREADSAFE` keeps all per-runtime state thread-local cannot be determined from the headers in the repo. This part stays open as [OQ-SM-11](../OPEN_QUESTIONS.md#oq-sm-11). Whether `JS_BeginRequest`/`JS_EndRequest` (declared unconditionally, `dependencies/include/jsapi.h:1818-1824`) are no-ops is *resolved*: they are. Each is a single `ret` in the release `jsapi.obj` and an empty function in the debug DLL ([../OPEN_QUESTIONS.md](../OPEN_QUESTIONS.md#appendix-a-resolved-during-triage), R-01).
* **Which configuration ships?** Debug needs `mozjs.dll` at runtime, but no post-build step copies it. Release needs `js_static.lib` unzipped. Which binary the owner currently deploys cannot be told from the repo. Narrowed: `Release/Build Instructions.txt` documents the Release path (unzip `js_static.zip`, VS2010), and the lib's `/FAILIFMISMATCH:"_MSC_VER=1600"` forces VS2010 for Release ([OQ-BLD-01](../OPEN_QUESTIONS.md#oq-bld-01)).
* **`JS_NewStringCopyZ` byte decoding.** *Resolved* (R-04): Latin-1. `dependencies/include/js/CharacterEncoding.h:19-23` states that all 1-byte strings passed into the JSAPI are treated as ISO-8859-1, and the headers offer no switch. So non-ASCII account, realm and game names reach JS today as U+0080-U+00FF characters, one per byte, whatever their real encoding.
* **Debug-build layout.** *Resolved* (R-05): Debug defines `DEBUG` (`D2BS.vcxproj:84`), and `dependencies/libs/debug/mozjs.dll` is a `DEBUG` build too, so the `#ifdef DEBUG` header layouts match (e.g. `dependencies/include/jsapi.h:74`). The DLL contains `MOZ_ASSERT` expression strings and 175 copies of `Assertion failure: %s, at %s:%d`, against 2 in the release lib. `MOZ_ASSERT` is compiled only under `DEBUG` (`dependencies/include/mozilla/Assertions.h:247-290`).
* **Hover handlers**: the hover dispatch is disabled (`D2Handlers.cpp:343`). It is unknown whether any script relies on `onHover`.
* **Unrooted locals and heap arrays.** *Resolved* (R-06): `js-config.h` does not define `JSGC_USE_EXACT_ROOTING`, so `JS::Rooted` compiles in its non-exact form (`dependencies/include/js/RootingAPI.h:549`), and `dependencies/include/js/Anchor.h:27-30` documents the GC's conservative stack scanner. Unrooted `JSObject*`/`JSString*`/`jsval` locals on the stack are therefore protected. `new jsval[]` heap arrays such as `JSGame.cpp:303` are not.
* **Constructors without a return value**: `new Sandbox()`, `new Text()` and `new Image()` have exits that set no rval (last table of §5.1). What `new` evaluates to in that case depends on engine internals not in the headers ([OQ-SM-02](../OPEN_QUESTIONS.md#oq-sm-02)). For `new Sandbox()` the question is moot: `JS_NewContext(NULL, …)` crashes first (R-03).

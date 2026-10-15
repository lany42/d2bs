# Core globals (`JSCore.cpp`, `JSHash.cpp`)

This page documents every JavaScript global whose native lives in `JSCore.cpp` (38 names, 36 natives) or `JSHash.cpp` (10 names): script control and loading, timers and `delay`, listener registration, inter-script messaging, console and logging, clipboard and OS IPC, input simulation, raw packets, a few miscellaneous helpers, and hashing. Each entry is checked against the C++ source and covers argument handling, return values, the thread it runs on, blocking behaviour, side effects and bugs. The event catalog (names, arguments, who fires them) is in [events.md](events.md). How runtimes, contexts and globals are created is in [../spidermonkey/embedding.md](../spidermonkey/embedding.md). Other globals registered in the same table (`rand`, `sqlite_version`, `sqlite_memusage`, `dopen`, ...) are documented with their own subsystems; see [README.md](README.md).

## Contents

- [Quick reference](#quick-reference)
- [Conventions shared by all entries](#conventions-shared-by-all-entries)
- [Script control & loading](#script-control--loading): `load`, `include`, `isIncluded`, `stop`, `js_strict`, `version`, `stacktrace`, `getThreadPriority`, `handler`
- [Timers & delay](#timers--delay): `delay`, `setTimeout`, `setInterval`, `clearTimeout`, `clearInterval`
- [Event listener registration](#event-listener-registration): `addEventListener`, `removeEventListener`, `clearEvent`, `clearAllEvents`
- [Inter-script messaging](#inter-script-messaging): `scriptBroadcast`
- [Console & logging](#console--logging): `print`, `debugLog`, `showConsole`, `hideConsole`
- [Clipboard & OS IPC](#clipboard--os-ipc): `copy`, `paste`, `sendCopyData`, `sendDDE`
- [Input simulation](#input-simulation): `keystate`, `sendClick`, `sendKey`, `beep`
- [Packets](#packets): `sendPacket`, `getPacket`
- [Misc](#misc): `getTickCount`, `getIP`, `loadMpq`, `stringToEUC`, `utf8ToEuc`
- [Hashing](#hashing): `md5`, `sha1`, `sha256`, `sha384`, `sha512`, `*_file`
- [Facts that constrain a replacement API](#facts-that-constrain-a-replacement-api)
- [Legacy-doc discrepancies](#legacy-doc-discrepancies)
- [Open questions](#open-questions)

---

## Quick reference

All entries are registered in `global_funcs[]` (`JSGlobalFuncs.h:23`) with `FUNCTION_FLAGS`. "Blocks" means the native can keep the calling script thread waiting for longer than a trivial amount of time.

| JS name | Native | Defined | Registered | Arity | Returns | Blocks |
|---|---|---|---|---|---|---|
| `getThreadPriority` | `my_getThreadPriority` | `JSCore.cpp:275` | `JSGlobalFuncs.h:29` | 0 | number (always -2) | no |
| `getTickCount` | `my_getTickCount` | `JSCore.cpp:266` | `JSGlobalFuncs.h:36` | 0 | number | no |
| `print` | `my_print` | `JSCore.cpp:49` | `JSGlobalFuncs.h:40` | 1 | null | no |
| `stringToEUC` | `my_stringToEUC` | `JSCore.cpp:22` | `JSGlobalFuncs.h:40` | 1 | string / null | no |
| `utf8ToEuc` | **alias**, same native `my_stringToEUC` | `JSCore.cpp:22` | `JSGlobalFuncs.h:40` | 1 | string / null | no |
| `setTimeout` | `my_setTimeout` | `JSCore.cpp:78` | `JSGlobalFuncs.h:41` | 0 | int id / null | no |
| `clearTimeout` | **alias**, uses `my_clearInterval` | `JSCore.cpp:117` | `JSGlobalFuncs.h:41` | 1 | null | no |
| `setInterval` | `my_setInterval` | `JSCore.cpp:98` | `JSGlobalFuncs.h:42` | 0 | int id / null | no |
| `clearInterval` | `my_clearInterval` | `JSCore.cpp:117` | `JSGlobalFuncs.h:42` | 1 | null | no |
| `delay` | `my_delay` | `JSCore.cpp:125` | `JSGlobalFuncs.h:42` | 1 | (unset) | **yes**, for the requested ms |
| `load` | `my_load` | `JSCore.cpp:168` | `JSGlobalFuncs.h:43` | 1 | null | up to 500 ms (stops an older instance) |
| `isIncluded` | `my_isIncluded` | `JSCore.cpp:280` | `JSGlobalFuncs.h:43` | 1 | boolean | no |
| `include` | `my_include` | `JSCore.cpp:212` | `JSGlobalFuncs.h:43` | 1 | boolean | runs the included code synchronously |
| `stop` | `my_stop` | `JSCore.cpp:237` | `JSGlobalFuncs.h:44` | 0 | never returns (terminates) | up to 500 ms for each other script |
| `stacktrace` | `my_stacktrace` | `JSCore.cpp:249` | `JSGlobalFuncs.h:44` | 0 | true | yes (walks every thread) |
| `copy` | `my_copy` | `JSCore.cpp:335` | `JSGlobalFuncs.h:45` | 0 | (unset) | no |
| `paste` | `my_paste` | `JSCore.cpp:354` | `JSGlobalFuncs.h:45` | 0 | string | no |
| `sendCopyData` | `my_sendCopyData` | `JSCore.cpp:365` | `JSGlobalFuncs.h:45` | 4 | int / false | **yes**, `SendMessage` with no timeout |
| `sendDDE` | `my_sendDDE` | `JSCore.cpp:419` | `JSGlobalFuncs.h:46` | 0 | string / false | up to 5 s per transaction |
| `keystate` | `my_keystate` | `JSCore.cpp:460` | `JSGlobalFuncs.h:46` | 0 | boolean | no |
| `addEventListener` | `my_addEventListener` | `JSCore.cpp:470` | `JSGlobalFuncs.h:46` | 2 | (unset) | no |
| `removeEventListener` | `my_removeEventListener` | `JSCore.cpp:483` | `JSGlobalFuncs.h:47` | 2 | (unset) | no |
| `clearEvent` | `my_clearEvent` | `JSCore.cpp:496` | `JSGlobalFuncs.h:47` | 1 | (unset) | no |
| `clearAllEvents` | `my_clearAllEvents` | `JSCore.cpp:506` | `JSGlobalFuncs.h:48` | 0 | (unset) | no |
| `js_strict` | `my_js_strict` | `JSCore.cpp:512` | `JSGlobalFuncs.h:48` | 0 | boolean / (unset) | no |
| `version` | `my_version` | `JSCore.cpp:295` | `JSGlobalFuncs.h:48` | 0 | string / true | no |
| `scriptBroadcast` | `my_scriptBroadcast` | `JSCore.cpp:532` | `JSGlobalFuncs.h:49` | 1 | null | no (serialises once per recipient) |
| `debugLog` | `my_debugLog` | `JSCore.cpp:307` | `JSGlobalFuncs.h:50` | 1 | (unset) | file I/O |
| `showConsole` | `my_showConsole` | `JSCore.cpp:541` | `JSGlobalFuncs.h:51` | 0 | null | no |
| `hideConsole` | `my_hideConsole` | `JSCore.cpp:547` | `JSGlobalFuncs.h:51` | 0 | null | no |
| `handler` | `my_handler` | `JSCore.cpp:553` | `JSGlobalFuncs.h:51` | 0 | number | no |
| `loadMpq` | `my_loadMpq` | `JSCore.cpp:558` | `JSGlobalFuncs.h:58` | 1 | null | game MPQ load |
| `beep` | `my_beep` | `JSCore.cpp:255` | `JSGlobalFuncs.h:63` | 0 | true | no |
| `getPacket` | `my_getPacket` | `JSCore.cpp:614` | `JSGlobalFuncs.h:69` | 0 | true / false | runs the game receive path |
| `sendPacket` | `my_sendPacket` | `JSCore.cpp:569` | `JSGlobalFuncs.h:69` | 0 | true / false | up to 500 ms for each other listening script |
| `getIP` | `my_getIP` | `JSCore.cpp:660` | `JSGlobalFuncs.h:70` | 0 | string | **yes**, synchronous HTTP |
| `sendClick` | `my_sendClick` | `JSCore.cpp:677` | `JSGlobalFuncs.h:70` | 0 | null | about 300 ms of `Sleep` |
| `sendKey` | `my_sendKey` | `JSCore.cpp:695` | `JSGlobalFuncs.h:70` | 0 | null | about 300 ms of `Sleep` |
| `md5` / `sha1` / `sha256` / `sha384` / `sha512` | `my_md5` ... `my_sha512` | `JSHash.cpp:7/20/33/46/59` | `JSGlobalFuncs.h:76-77` | 1 | hex string / (unset) | no |
| `md5_file` ... `sha512_file` | `my_md5_file` ... `my_sha512_file` | `JSHash.cpp:72/90/108/126/144` | `JSGlobalFuncs.h:77-79` | 1 | hex string / (unset) | file I/O |

Not in scope despite sitting in the same "utility" block of `JSGlobalFuncs.h:39-51`: `rand` (`JSGame.cpp:677`, see [globals-game.md](globals-game.md)), `sqlite_version`/`sqlite_memusage` (`JSSQLite.cpp:67/72`) and `dopen` (`JSDirectory.cpp:37`), both in [utility-classes.md](utility-classes.md). No `JSCore.cpp`/`JSHash.cpp` entry is commented out. The only commented-out entry in `global_funcs` is `createCharacter` (`JSGlobalFuncs.h:55`, native `my_createCharacter` at `JSMenu.cpp:165`), covered by [out-of-game.md](out-of-game.md).

---

## Conventions shared by all entries

### Registration

- `global_funcs[]` is installed with `JS_DefineFunctions(cx, globalObject, global_funcs)` in `contextCallback` when a context is created (`ScriptEngine.cpp:345`). Every `Script` has its own `JSRuntime` and `JSContext` (`Script.cpp:120`, `Script.cpp:125`), so each script gets its own copy of every function object. Function values cannot be shared between scripts. Anything that crosses scripts (arguments to `load`, `scriptBroadcast` payloads) goes through structured clone.
- `JS_FN(name, native, nargs, flags)` (`dependencies/include/jsapi.h:3062`) ORs in `JSFUN_STUB_GSOPS` (`dependencies/include/jsapi.h:1428`). `FUNCTION_FLAGS` is defined as that same flag (`js32.h:134`). The flags word therefore carries no `JSPROP_*` attribute bits: `JSPROP_ENUMERATE`/`READONLY`/`PERMANENT` are `0x01`/`0x02`/`0x04` (`dependencies/include/jsapi.h:1409-1414`), while the `JSFUN_*` bits are masked by `0xe00` (`dependencies/include/jsapi.h:1447`). The global properties are thus defined writable, deletable and not enumerable, and a script can overwrite `print`, `delay` and the rest.
- `nargs` (the "arity" column) only becomes the function's `length`. It does **not** validate anything: every native checks `argc` itself, or doesn't check it at all.
- `JSAPI_FUNC(name)` expands to `JSBool name(JSContext* cx, uint argc, jsval* vp)` (`js32.h:133`). The calling script is recovered with `(Script*)JS_GetContextPrivate(cx)`, which is set at `Script.cpp:135`. Arguments are `JS_ARGV(cx,vp)[i]` (`dependencies/include/js/CallArgs.h:319`). The return value is `JS_SET_RVAL` (`dependencies/include/js/CallArgs.h:321`). No native in scope uses `this`.

### Reading arguments past `argc`

The JSAPI contract only defines argument slots `0..argc-1`: `CallArgs::operator[]` asserts `i < argc_` (`dependencies/include/js/CallArgs.h:239`). Many natives here read `JS_ARGV(cx,vp)[i]` without checking `argc` first. Those reads are marked **"argc unchecked"** below. The headers don't say whether this engine build pads missing arguments up to `nargs` with `undefined` (see [Open questions](#open-questions)). Treat such calls as undefined behaviour. For natives that also apply `JSVAL_TO_STRING`/`JSVAL_TO_INT` to the slot without a type test, a missing or wrong-typed argument becomes an invalid pointer or a garbage integer.

`JSVAL_TO_INT` on a double-typed number returns the low 32 bits of the IEEE payload, not the value: the release build has no assertion (`dependencies/include/js/Value.h:1620`). Natives that test only `JSVAL_IS_NUMBER` and then call `JSVAL_TO_INT` (`setTimeout`, `setInterval`) therefore misread non-integral or out-of-int32-range numbers.

### Return values

**(unset)** in this page means the native returns `JS_TRUE` without calling `JS_SET_RVAL`. The header says the initial contents of the return slot are unspecified (`dependencies/include/js/CallArgs.h:134-142`). By the `vp` convention, `vp[0]` holds the callee on entry (`JS_CALLEE`, `dependencies/include/js/CallArgs.h:317`), so such calls most likely evaluate to the function object itself. This is unverified (see [Open questions](#open-questions)). Don't rely on the value.

### Errors

| Mechanism | Definition | JS-visible effect |
|---|---|---|
| `THROW_ERROR(cx, msg)` | `JS_ReportError` + `return JS_FALSE` (`js32.h:113`) | A catchable `Error` with that message. If uncaught, `reportError` prints and logs it (`ScriptEngine.cpp:428-439`), and with `QuitOnError=true` in game it calls `D2CLIENT_ExitGame()` (`ScriptEngine.cpp:446-447`). |
| `THROW_WARNING(cx, vp, msg)` | `JS_ReportWarning` + rval `false` + `return JS_TRUE` (`js32.h:118`) | Not an exception. Printed as `[Warning ...]` through `reportError`, and the call returns `false`. |
| `JS_ConvertArguments` failure | engine error, native returns `JS_FALSE` | A catchable `TypeError`. A missing argument gives `JSMSG_MORE_ARGS_NEEDED`, "`{0} requires more than {1} argument{2}`" (`dependencies/include/js.msg:56`). |
| `JS_ReportError` then `return JS_TRUE` | `setTimeout`/`setInterval`/`clearInterval` | An error is raised but the native reports success. The exception is left pending, which breaks the JSAPI contract; the outcome is engine-defined (see [Open questions](#open-questions)). |
| `return JS_FALSE` with no exception | `stop` | Uncatchable termination of the running JS. |

`JSOPTION_STRICT` (extra warnings) is on by default (`Script.cpp:131`) and `JSOPTION_WERROR` is never set, so warnings never turn into exceptions.

### Threading

Every native runs on the calling script's own OS thread: `Script::BeginThread` uses `CreateThread` (`Script.cpp:108`), and console commands run on the console script's thread. Any D2BS hook code that a native re-enters (for example `GamePacketSent` from `sendPacket`) also runs on that thread. **No native in this page takes the game-loop lock** (`AutoCriticalRoom`, `CriticalSections.h:31`). Natives that call into the game (`sendPacket`, `getPacket`, `loadMpq`) run concurrently with the game thread. Event delivery to a script is described in [Timers & delay](#timers--delay) and [events.md](events.md).

### Strings and encodings

| Helper | Behaviour |
|---|---|
| `JS_GetStringCharsZ` | UTF-16 (`wchar_t*`), owned by the engine |
| `JS_EncodeStringToUTF8` | heap UTF-8, which the caller frees with `JS_free` |
| `JS_NewStringCopyZ(char*)` | **inflates each byte to one UTF-16 code unit** (Latin-1 style). There is no UTF-8 decoding: `JS_SetCStringsAreUTF8` is neither used nor declared in these headers. |
| `AnsiToUnicode(s, cp = CP_UTF8)` / `UnicodeToAnsi(s, cp = CP_UTF8)` | `Helpers.cpp:16`/`Helpers.cpp:24`, defaults at `Helpers.h:9-10`. The names say "Ansi" but the default code page is **UTF-8**. |

### Paths

`Vars.szScriptPath` is `<D2BS dir><ScriptPath>`, where `ScriptPath` defaults to `scripts` (`Helpers.cpp:133`). A profile switch rewrites it (`Helpers.cpp:94`; `WM_COPYDATA` mode `0x31337`, `-profile`, and nominally a DDE poke, which passes an empty name, see [`sendDDE`](#sendddemode-server-topic-item-data); details in [../architecture.md](../architecture.md)). `isValidPath` (`File.cpp:258`) resolves the name against the script path and rejects anything outside it, plus `..\`, `../` and `":?*<>|`. **On this page, only `loadMpq` and the `*_file` hash functions call `isValidPath`.** `load`, `include` and `isIncluded` don't validate, so `..\` escapes the script folder.

---

## Script control & loading

### `load(file, ...args)`

Creates a new script (its own runtime, context and OS thread) from `<scripts>\file`, and passes `args` to its `main`.

- **Native:** `my_load` at `JSCore.cpp:168`; registered at `JSGlobalFuncs.h:43` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `file`: must be a JS string. `JSVAL_TO_STRING` is applied with no type test (`JSCore.cpp:177`), and argc is unchecked. A non-string, or no argument at all, dereferences a garbage pointer. With `argc == 0`, `new JSAutoStructuredCloneBuffer*[argc - 1]` also asks for `0xFFFFFFFF` elements (`JSCore.cpp:192`).
  - The full path is built as `swprintf_s("%s\\%s", Vars.szScriptPath, file)` and then `/` is replaced with `\` (`JSCore.cpp:188-190`). There is no `isValidPath` check.
  - If `wcslen(file) > 516 - wcslen(szScriptPath)` (`_MAX_FNAME + _MAX_PATH`), the native throws `"File name too long!"` (`JSCore.cpp:179-182`). If the context has no `Script`, it throws `"Failed to get script object"` (`JSCore.cpp:172-175`).
  - `...args`: each is serialised with `JSAutoStructuredCloneBuffer::write(cx, v)` in the **caller's** context. The return value isn't checked (`JSCore.cpp:192-196`). No custom clone callbacks exist anywhere in the code base. Only structured-clone-able data survives: primitives, plain objects, arrays, Date, RegExp, typed arrays. Functions and D2BS host objects (Unit, File, ...) do not.
- **Returns:** `null` on success and on "not found" (`JSCore.cpp:203`, `JSCore.cpp:207`). The code that would return a `Script` object is commented out (`JSCore.cpp:202`). It throws in the two error cases above.
- **Preconditions:** either game state. The engine must be `Running`; otherwise `CompileFile` returns `NULL` (`ScriptEngine.cpp:32-33`) and the caller sees the misleading "not found" message.
- **Threading & blocking:**
  - `ScriptEngine::CompileFile` (`ScriptEngine.cpp:31`) runs on the caller's thread. It lowercases the path (`ScriptEngine.cpp:35-36`). If `ScriptEngine::scripts` already holds that key, it calls `Stop()` on that instance first (`ScriptEngine.cpp:39-40`). When the instance is another thread's script, `Script::Stop` polls `hasActiveCX` every 10 ms for up to 500 ms (`Script.cpp:270-278`).
  - It then constructs `Script`. The constructor calls `_waccess` and throws `"File not found"`, which is caught and printed (`Script.cpp:27-31`, `ScriptEngine.cpp:46-53`). The new instance is put in the map (`ScriptEngine.cpp:43`) and `BeginThread(ScriptThread)` is called (`JSCore.cpp:201`).
  - On the new thread, `Script::Run` (`Script.cpp:118`) runs these steps:
    1. `JS_NewRuntime(Vars.dwMemUsage)`, where `MemoryLimit` is in MB, defaults to 100, and is clamped to 50 if below 1 (`Helpers.cpp:125`, `Helpers.cpp:156-160`).
    2. `JS_NewContext`, which runs `contextCallback` to build the global, the functions, the classes and `me` (`ScriptEngine.cpp:329-375`).
    3. Compile with `JS_CompileFile` (`js32.cpp:29`: the file is read as UTF-8 and a BOM is blanked).
    4. Deserialise the args into the new context (`Script.cpp:183-188`), then execute the top-level code.
    5. Only if the top-level code completed without error, and a global `main` exists and is a function, call `main(...args)` with `this` = global (`Script.cpp:192-195`). Its return value is discarded.
  - **`load()` returns before any of this.** Compile and runtime errors surface on the new thread through `reportError`. The caller can't detect them.
  - `ScriptState` of the new script: the caller's state. If the caller is the console (`Command`), the state is `InGame` when `ClientState()==ClientStateInGame` and `OutOfGame` otherwise (`JSCore.cpp:184-186`). An `InGame` script is terminated at its next operation callback while the client is at the menu (`ScriptEngine.cpp:315-326`).
- **Side effects:** a new OS thread, runtime and context. If the file is missing, `Print("File \"%s\" not found.")` (`JSCore.cpp:206`), plus the exception text from `CompileFile` (`ScriptEngine.cpp:48-49`). A replaced older instance prints `"Script <name> ended"` (`Script.cpp:260-263`).
- **Game internals:** only `ClientState()` (`D2Helpers.cpp:125`: `D2CLIENT_GetPlayerUnit` at `D2Ptrs.h:122`, `p_D2WIN_FirstControl` at `D2Ptrs.h:462`, `UnitAny.pUpdateUnit/pInventory/pPath->pRoom1->pRoom2->pLevel->dwLevelNo`).
- **Quirks / bugs:**
  - **Reloading restarts.** `load()` of a file that is already in the script map stops the existing instance and starts a new one. Legacy docs don't mention this.
  - **Self-load orphans the new instance.** `load()` of the caller's own file goes like this:
    1. `Stop()` on self marks the caller aborted and returns without waiting, because it runs on the same thread (`Script.cpp:271`). The caller is terminated at its next operation-callback check.
    2. The new instance is stored under the same key.
    3. When the old instance unwinds, `ScriptThread` calls `DisposeScript` (default `DisableCache=true`, `Helpers.cpp:124`, `Script.cpp:480-481`). That function erases the map entry **by file name** (`ScriptEngine.cpp:76-77`), removing the new instance.

    The new script keeps running but is invisible to `ForEachScript`: no events, no `scriptBroadcast`, not stopped by `stop()`/`StopAll`, not found by `getScript`. The same race happens for any reload whose old instance takes longer than 500 ms to stop.
  - The structured-clone buffers and the pointer array are never freed. The cleanup is commented out with "crashes" (`Script.cpp:201-205`). The deserialised `jsval` array (`Script.cpp:183`) also leaks.
  - **With `DisableCache=false`, reloading a finished script costs 500 ms and leaks the old instance.** A finished cached script still has its context, so `hasActiveCX` stays `true` (it is only cleared at context destruction, `ScriptEngine.cpp:378`). `Stop()` on it (it was never aborted) prints `"Script <name> ended"` again and polls for the full 500 ms. `scripts[fileName] = script` then overwrites the map entry without deleting the old `Script`, its runtime or its context (`ScriptEngine.cpp:39-43`).
  - The `CompileFile` catch block calls `LeaveCriticalSection(&lock)` on `ScriptEngine::lock` (`ScriptEngine.cpp:47`). That lock is never entered and never initialised: it is zero-initialised at `ScriptEngine.cpp:22` and its `InitializeCriticalSection` is commented out at `ScriptEngine.cpp:121`. This is an unbalanced leave on every "file not found".
  - A compile failure makes `Script::Run` rethrow `std::exception` out of the thread procedure (`Script.cpp:157-171`; `ScriptThread` at `Script.cpp:473` has no handler). The catch block also calls `LeaveCriticalSection(&lock)` on the `Script` lock it never entered (`Script.cpp:170`). See [Open questions](#open-questions).
  - Off-by-two in the length check: a name of `515-L` or `516-L` characters passes the check but overflows `buf`, and `swprintf_s` then invokes the CRT invalid-parameter handler.
  - Legacy docs disagree on the return value (see [discrepancies](#legacy-doc-discrepancies)).

### `include(file)`

Compiles and runs `<scripts>\libs\file` in the calling script's global scope, at most once per script.

- **Native:** `my_include` at `JSCore.cpp:212`; registered at `JSGlobalFuncs.h:43` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `file` is a string. `JSVAL_TO_STRING` is applied with no type test and argc unchecked (`JSCore.cpp:221`). The path is `"%s\\libs\\%s"` (`JSCore.cpp:229`) and isn't validated, so `..\` works. If `wcslen(file) > 510 - wcslen(szScriptPath)`, it throws `"File name too long!"` (`JSCore.cpp:223-226`). That check has an off-by-one.
- **Returns:**
  - `false` if `_waccess` fails (missing file; no message) (`JSCore.cpp:213`, `JSCore.cpp:231`).
  - Otherwise the boolean result of `Script::Include` (`Script.cpp:296`):
    - `true` if the file was already included, is currently being included (circular include), or is the script's own main file (`Script.cpp:308`).
    - `true` after a successful compile and execute.
    - `false` on a compile error or an uncaught exception from top-level code.
- **Preconditions:** either game state.
- **Threading & blocking:**
  - Synchronous on the caller's thread. `Script::Include` holds the script's `lock` (a recursive `CRITICAL_SECTION`) for the whole compile and execute (`Script.cpp:298`, `Script.cpp:335`).
  - Other threads that call `Stop()` on this script block on that lock until the include finishes (`Script.cpp:255`). An included file whose top-level code calls `delay()` therefore delays `stop()` from other scripts by the same amount.
  - Included top-level code can call any native, including listener registration and `delay`, which re-enters the event loop.
- **Side effects:**
  - Compiles from disk with `JS_CompileFile` (`Script.cpp:319`) and runs it with `JS_ExecuteScript(cx, globalObject, ...)` (`Script.cpp:323`). Definitions always land on the global object, even when `include` is called inside a function.
  - The path is lowercased and `/` replaced with `\`, both for the `includes`/`inProgress` maps and for the compiled file name, so error messages show the lowercase path (`Script.cpp:302-303`).
  - Errors are reported with `JS_ReportPendingException` (`Script.cpp:327`, `Script.cpp:331`). They print and log, and with `QuitOnError` they exit the game. They are **not** propagated to the caller.
- **Game internals:** none.
- **Quirks / bugs:**
  - **No compile cache.** Every successful first include compiles from disk. "Cache" in D2BS (`DisableCache`) refers to keeping `Script` objects, not bytecode.
  - A failed include isn't recorded, so the next `include()` executes the file again, on top of any partial definitions left by the failed run.
  - A circular include returns `true` while the inner file is only partly executed.
  - If `_wcsdup` fails, `Script::Include` returns without `LeaveCriticalSection` (`Script.cpp:300-301`).
  - The compiled `JSScript*` is unrooted between compile and execute: `js32.cpp:55-56` adds and immediately removes the root. This is a GC hazard.

### `isIncluded(file)`

Reports whether `<scripts>\libs\file` has been **successfully** included by the calling script.

- **Native:** `my_isIncluded` at `JSCore.cpp:280`; registered at `JSGlobalFuncs.h:43` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `file` is a string. `JSVAL_TO_STRING` is applied with no type test and argc unchecked (`JSCore.cpp:281`). Same path construction as `include` (`JSCore.cpp:289`). If too long, it throws `"File name too long"` (no `!`) (`JSCore.cpp:283-286`).
- **Returns:** a boolean: `includes.count(lowercased, backslashed path)` (`Script.cpp:282-294`). Includes that are still in progress, and the script's main file, return `false`.
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Reads the per-script `includes` map without locking.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** per-script state. Another script's includes are invisible. Unlike `load`/`include`, the `Script*` from the context isn't null-checked before use (`JSCore.cpp:290-291`).

### `stop([self])`

Terminates JavaScript execution: either the calling script only, or **every non-console script**.

- **Native:** `my_stop` at `JSCore.cpp:237`; registered at `JSGlobalFuncs.h:44` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - The condition is `(argc > 0 && JSVAL_IS_INT(a0) && a0 == 1) || (JSVAL_IS_BOOLEAN(a0) && a0 == true)` (`JSCore.cpp:238-239`). Because of operator precedence, the boolean branch reads `argv[0]` even when `argc == 0`.
  - `stop(1)` or `stop(true)` calls `Script::Stop()` on the caller (`JSCore.cpp:240-242`).
  - **Anything else** calls `ScriptEngine::StopAll()` (`JSCore.cpp:244`): `stop()`, `stop(0)`, `stop(false)`, `stop(2)`, `stop("1")`, `stop(1.0)` if stored as a double.
- **Returns:** nothing. The native returns `JS_FALSE` with no pending exception (`JSCore.cpp:246`), which is an uncatchable termination of the current JS execution. `try/catch` can't intercept it. Inside an event handler this only ends that handler call, because dispatch ignores the call result (for example `ScriptEngine.cpp:780-782`). The script itself ends later, at its next operation-callback check, because it is now aborted. A console-thread caller (`Command` state) of `stop()` without arguments is not aborted at all; only its current command is cut short.
- **Preconditions:** either game state.
- **Threading & blocking:**
  - `StopAll` calls `ForEachScript(StopScript)` (`ScriptEngine.cpp:168-176`). For every script not in `Command` state (`ScriptEngine.cpp:247-252`), that includes the caller, it calls `Script::Stop(false)`:
    1. Return at once if already aborted (`Script.cpp:253-254`); otherwise take the target's `lock`, set `isAborted`, and clear `isPaused`/`isReallyPaused`, so a paused target is released (`Script.cpp:255-259`).
    2. Print `"Script <short name> ended"`.
    3. `JS_TriggerOperationCallback` if `hasActiveCX`.
    4. `SetEvent(eventSignal)`.
    5. If the target isn't the current thread, poll `hasActiveCX` every 10 ms for up to 500 ms while still holding the target's `lock` (`Script.cpp:269-279`).
  - `hasActiveCX` only clears when the context is destroyed (`ScriptEngine.cpp:378`, `Script.cpp:46`). The caller can therefore block up to 500 ms for each other script that is slow to unwind.
  - Stopping is cooperative. A target notices it in `delay()` or in its next operation callback (`ScriptEngine.cpp:315-326`).
- **Side effects:** console line per stopped script. The console script (`Command` state) is never stopped by `StopAll`.
- **Game internals:** none.
- **Quirks / bugs:**
  - `stop(1)` typed **into the console** aborts the console script itself, with no message (`Script.cpp:260`). Its `main` then ends at the next operation-callback check. That `main` is the built-in `while (true){delay(10000)}` (`Script.cpp:150`) unless `DefaultConsoleScript` is set. With the default `DisableCache=true`, `ScriptThread` deletes the console `Script` (`Script.cpp:480-481`). But `DisposeScript` looks it up by file name, while the console is stored under the map key `L"console"` (`ScriptEngine.cpp:74-77` vs `ScriptEngine.cpp:131`), so `ScriptEngine::console` and `scripts[L"console"]` are left as dangling pointers. Later console commands (`ScriptEngine.cpp:61`) and every `ForEachScript` (event dispatch, broadcasts) then touch freed memory. With `DisableCache=false`, commands are queued to the aborted console and never run; `Script::RunCommand` only logs `"Console Aborted HELP!"` (`Script.cpp:82-90`).
  - The meaning is inverted compared with `resources/api.html:1455` (see [discrepancies](#legacy-doc-discrepancies)).

### `js_strict([enable])`

Gets or sets `JSOPTION_STRICT` ("warn on dubious practice", `dependencies/include/jsapi.h:1952`) on the caller's context. This is **not** ES5 strict mode.

- **Native:** `my_js_strict` at `JSCore.cpp:512`; registered at `JSGlobalFuncs.h:48` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `js_strict()` is the getter (`JSCore.cpp:513-516`).
  - `js_strict(x)` uses `JSVAL_TO_BOOLEAN(x)` raw, with no type test or coercion (`JSCore.cpp:520`). An int `1` gives true and `0` gives false. Objects and strings read the pointer payload, so they are effectively true.
  - It flips the option with `JS_ToggleOptions` only if the state differs (`JSCore.cpp:518-527`). Two or more arguments do nothing.
- **Returns:** a boolean in the getter form. The setter form is (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Per-context; other scripts aren't affected.
- **Side effects:** controls strict *warnings* printed as `[Strict Warning ...]` (`ScriptEngine.cpp:430-439`).
- **Game internals:** none.
- **Quirks / bugs:**
  - The default is **on**. `Script::Run` sets `JSOPTION_STRICT | JSOPTION_VAROBJFIX` (`Script.cpp:131`).
  - That same `JS_SetOptions` call replaces the options set in `contextCallback` (`ScriptEngine.cpp:337`: METHODJIT/TI/ION/ASMJS). See [../spidermonkey/embedding.md](../spidermonkey/embedding.md).
  - Legacy `api.html` says the default is "disabled".

### `version([print])`

Returns the D2BS version string, or prints a banner.

- **Native:** `my_version` at `JSCore.cpp:295`; registered at `JSGlobalFuncs.h:48` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `version()` returns the string. `version(anything)` prints instead (the value is ignored) (`JSCore.cpp:298`).
- **Returns:**
  - No args: interned string `D2BS_VERSION`, which is `"1.6.4U"` (`D2BS.h:10`, `JSCore.cpp:299`).
  - With an arg: `true` (`JSCore.cpp:296`).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread.
- **Side effects:** `Print("ÿc4D2BSÿc1 ÿc31.6.4U for Diablo II 1.14d.")` (`JSCore.cpp:303`).
- **Game internals:** none.
- **Quirks / bugs:** the legacy `resources/api.html:1464` says "prints, and returns if returnAsWell". In the code the two forms are mutually exclusive.

### `stacktrace()`

Writes the **native** (C/C++) call stacks of every thread in the process to the D2BS log. It doesn't touch the JS stack.

- **Native:** `my_stacktrace` at `JSCore.cpp:249`; registered at `JSGlobalFuncs.h:44` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `true` always (`JSCore.cpp:250`). The result of `GetStackWalk()` is ignored.
- **Preconditions:** either game state.
- **Threading & blocking:** `GetStackWalk` (`Helpers.cpp:490`):
  1. Enumerate the process's threads with a Toolhelp snapshot (`Helpers.cpp:451`).
  2. For each thread other than the current one, `OpenThread(THREAD_GET_CONTEXT)` and `StackWalker::ShowCallstack(hThread)` (`StackWalker.cpp:1034`). That function calls `SuspendThread` (`StackWalker.cpp:1075`), `GetThreadContext` (`StackWalker.cpp:1083`) and DbgHelp.
  3. Walk the current thread last.

  This is slow: symbol loading plus file I/O for every line.
- **Side effects:** `Log` lines `"Stack Walk Thread: %d"` followed by the frames (`Helpers.cpp:504-509`, `MyStackWalker::OnOutput` at `Helpers.cpp:446`).
- **Game internals:** none.
- **Quirks / bugs:**
  - `OpenThread` returns `NULL` on failure, but the code compares against `INVALID_HANDLE_VALUE` (`Helpers.cpp:501`).
  - The handles are never closed.
  - They are opened without `THREAD_SUSPEND_RESUME`, so `SuspendThread` inside StackWalker most likely fails and running threads are walked live.

### `getThreadPriority()`

Intended to return the thread priority. It actually returns the `GetCurrentThread()` pseudo-handle.

- **Native:** `my_getThreadPriority` at `JSCore.cpp:275`; registered at `JSGlobalFuncs.h:29` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** `INT_TO_JSVAL((uint)GetCurrentThread())` (`JSCore.cpp:276`). `GetCurrentThread()` is the constant pseudo-handle `(HANDLE)-2`, so the result is always `-2`.
- **Preconditions:** either game state.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** `GetThreadPriority` is never called. The legacy docs (`doc/globalFuncs.h:218`, `resources/api.html:1161`) claim it returns the priority.

### `handler()`

Returns the window handle given on the command line with `-handle <n>`. This is usually a launcher or manager window, used as the target for `sendCopyData`.

- **Native:** `my_handler` at `JSCore.cpp:553`; registered at `JSGlobalFuncs.h:51` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** a number: `UINT_TO_JSVAL((uint32_t)Vars.hHandle)` (`JSCore.cpp:554`). `0` if `-handle` was absent: `Vars` is a zero-initialised global, set only at `D2Handlers.cpp:46` as `(HWND)_wtoi(text)`.
- **Preconditions:** either game state.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** `Vars.hHandle` (`D2BS.h:79`). Command-line parsing is covered in [../architecture.md](../architecture.md).
- **Quirks / bugs:** not documented in the legacy docs.

---

## Timers & delay

### How timers and event servicing work

Facts shared by `delay`, `setTimeout`, `setInterval`, `clearTimeout` and `clearInterval`:

1. **Per-script event queue.** Each `Script` has a `std::list<Event*> EventList` (`Script.h:206`) and a manual-reset `eventSignal` (`Script.cpp:22`). `Script::FireEvent` runs these steps (`Script.cpp:419-430`):
   1. `push_front` the event under the global `Vars.cEventSection`.
   2. Call `JS_TriggerOperationCallback` if the script `IsRunning()`.
   3. `SetEvent(eventSignal)`.

   Consumers `pop_back`, so each script handles events FIFO.
2. **Where queued events run.** Always on the owning script's thread, in one of three loops:
   - `delay()` (`JSCore.cpp:145-151`);
   - `SetSkill`'s wait loop in 100 ms slices (`D2Helpers.cpp:273-281`), used by `Unit.prototype.setSkill` (`JSUnit.cpp:1744`; see [unit-methods.md](unit-methods.md));
   - the operation callback (`ScriptEngine.cpp:316-322`).

   D2BS triggers the operation callback (`Script::TriggerOperationCallback`, `Script.h:171`, a no-op unless `hasActiveCX`) only from `FireEvent` (`Script.cpp:426`), `Pause`/`Resume`/`Stop` (`Script.cpp:220`, `Script.cpp:236`, `Script.cpp:266`), `RunCommand` (`Script.cpp:100`), `StopScript` (`ScriptEngine.cpp:248`) and `Script.prototype.send` (`JSScript.cpp:127`). There is no periodic trigger: `D2Handlers.cpp:110-113` is commented out. Whether the engine also invokes the callback on its own (for example for GC requests) can't be told from the headers. Once triggered, it runs at the engine's next interrupt check. **Event handlers can therefore pre-empt the main script at arbitrary interrupt points, not only inside `delay()`.** See [events.md](events.md) for dispatch details.
3. **`setTimeout(fn, ms)` / `setInterval(fn, ms)`** (`JSCore.cpp:78`, `JSCore.cpp:98`) run these steps:
   1. `Script::RegisterEvent("setTimeout"|"setInterval", fn)`, which appends a GC-rooted copy of `fn` to the **same listener map that `addEventListener` uses** (`Script.cpp:352-359`).
   2. Build an `Event{owner=self, name="setTimeout"|"setInterval", arg3=new jsval(fn)}`.
   3. Call `ScriptEngine::AddDelayedEvent(evt, ms)` (`ScriptEngine.cpp:798-816`):
      1. `key = ++delayedExecKey`. This is a process-global, non-atomic `static int` starting at 0, so the first id is 1 (`ScriptEngine.cpp:25`, `ScriptEngine.cpp:799`).
      2. `arg1 = new DWORD(key)`; `arg2 = CreateWaitableTimer(NULL, TRUE, NULL)`.
      3. Due time `ms * -10000` (relative, 100 ns units). This is **computed in 32-bit `int`** (`ScriptEngine.cpp:804`).
      4. Period `ms` for `setInterval`, `0` for `setTimeout` (`ScriptEngine.cpp:809`).
      5. Append to the global `DelayedExecList` under `Vars.cEventSection`.
      6. `SetWaitableTimer(..., EventTimerProc, evt, FALSE)` (`ScriptEngine.cpp:810-813`).
4. **Expiry.** The completion routine `EventTimerProc` (`ScriptEngine.cpp:837-839`) is an APC queued by Windows to **the thread that called `SetWaitableTimer`**, which is the script's thread. It runs only while that thread is in an *alertable* wait: `delay()`'s `WaitForSingleObjectEx(..., TRUE)` (`JSCore.cpp:140`) or `SetSkill` (`D2Helpers.cpp:273`). These are the only alertable waits in the code base. `EventTimerProc` calls `owner->FireEvent(evt)`.
5. **Dispatch.** `ExecScriptEvent` (`ScriptEngine.cpp:776-791`) calls **every** function registered under the event name (`"setTimeout"` or `"setInterval"`), with 0 arguments and `this` = global. Return values and failures are ignored. For `setTimeout` it then calls `RemoveDelayedEvent(key)`.
6. **Cancellation.** `ScriptEngine::RemoveDelayedEvent(key)` (`ScriptEngine.cpp:818-836`) scans the **global** list for a matching key. For each match it calls `CancelWaitableTimer` and `CloseHandle`, then `owner->UnregisterEvent(name, *arg3)` (which removes the first function whose `jsval` is equal), then frees the `Event`. Finally it calls `LeaveCriticalSection(&Vars.cEventSection)` **without having entered it** (`ScriptEngine.cpp:835`).

Consequences for timers. Each item is a bug or a behaviour, as labelled:

- **Every pending timer of the same kind fires on every tick (bug).** With `setTimeout(a, 100)` and `setTimeout(b, 1000)` pending, `a` and `b` both run at 100 ms, and `b` runs again at 1000 ms. Every interval tick runs all of the script's `setInterval` callbacks.
- **Timers only advance inside `delay()` or `setSkill` (behaviour).** A script that loops without calling `delay()` never sees its timers. Overdue APCs are delivered at the next alertable wait. After `main` returns, the thread exits (and with default `DisableCache=true` the script is disposed, `Script.cpp:480-481`), so pending timers never fire.
- **Delays above 214 748 ms are corrupted (bug).** `ms * -10000` overflows `int32` (`ScriptEngine.cpp:804`). For example, 300 000 ms wraps to a positive (absolute, in the past) due time and fires immediately.
- **Non-integral delays are misread (bug).** `ms` is checked with `JSVAL_IS_NUMBER` but read with `JSVAL_TO_INT` (`JSCore.cpp:86`, `JSCore.cpp:106`). Any double-typed value gives garbage. For example, `1000.5` (IEEE `0x408F440000000000`) reads as 0 and fires immediately.
- **`setInterval(fn, 0)` fires once (behaviour).** The period is 0, so it is never re-armed and never removed.
- **Negative delays (behaviour).** A negative `ms` makes the due time positive, which `SetWaitableTimer` treats as an absolute time in the past, so the timer fires at once. Neither the `CreateWaitableTimer` nor the `SetWaitableTimer` result is checked (`ScriptEngine.cpp:801`, `ScriptEngine.cpp:812`), so a rejected timer (for example a negative `setInterval` period) leaves a registered listener and a list entry that never fire.
- **Unbalanced `LeaveCriticalSection` on `Vars.cEventSection` (bug).** It happens on every `clearTimeout`/`clearInterval` and after every `setTimeout` fires (`ScriptEngine.cpp:835`). That lock guards every script's event queue (`Script.cpp:97`, `Script.cpp:421`, `JSCore.cpp:146`, `D2Helpers.cpp:276`, `ScriptEngine.cpp:317`, `JSScript.cpp:124`). Microsoft documents that leaving an unowned critical section "may cause another thread using EnterCriticalSection to wait indefinitely". `DelayedExecList` is also scanned and erased without the lock while other threads append to it.
- **Ids are global and unowned (behaviour/bug).** `clearTimeout(id)` cancels the timer with that id **in any script** and mutates that script's listener map from the caller's thread (`ScriptEngine.cpp:826`). Deleting the removed `AutoRoot` runs `JS_BeginRequest`/`JS_RemoveValueRoot` on the **owner's** context from the caller's thread (`AutoRoot.cpp:10-20`), which is a JSAPI call on a runtime from a foreign thread.
- **Clearing a timer from inside its own callback is unsafe (bug).** The dispatch loop is iterating the listener list that `UnregisterEvent` modifies, and the `AutoRoot` node is deleted (iterator invalidation). For `setTimeout`, `ExecScriptEvent` then reads `*(DWORD*)evt->arg1` from the already-freed `Event` (`ScriptEngine.cpp:787`).
- **Freed events can still be queued (bug).** A `setInterval` `Event` whose APCs run while the queue isn't drained (for example an `InGame` script at the menu: `delay()`'s alertable wait still runs APCs but the drain loop is suppressed, `JSCore.cpp:140-145`) is pushed several times as the same pointer. `clearTimeout`/`clearInterval` between expiry and dispatch frees an `Event` that is still in `EventList`, leaving a dangling pointer there.
- **Leak on script end (bug).** The script's `DelayedExecList` entries are not removed at context destruction (`ScriptEngine.cpp:376-389` only drains `EventList`). Un-fired `setTimeout`s and all `setInterval`s leak their timer handles and keep an `owner` pointer to a deleted `Script`. A later `clearTimeout(thatId)` from any script is a use-after-free.
- **Timers share the listener map with `addEventListener` (behaviour).** `addEventListener("setTimeout", f)` makes `f` run whenever any of the script's `setTimeout`s fires. `clearEvent("setInterval")` or `clearAllEvents()` silences pending timers but leaves the Windows timers armed.

### `delay(ms)`

Sleeps the calling script for `ms` milliseconds while servicing its event queue.

- **Native:** `my_delay` at `JSCore.cpp:125`; registered at `JSGlobalFuncs.h:42` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `JS_ConvertArguments(..., "u", &nDelay)`, which is ECMA `ToUint32` (`JSCore.cpp:128`). Strings are coerced.
  - Missing: throws `TypeError` "delay requires more than 0 arguments" (JSMSG_MORE_ARGS_NEEDED).
  - `0` (also `NaN`, `"abc"`, `undefined`): `JS_ReportWarning("delay(0) called, argument must be >= 1")` and return immediately (`JSCore.cpp:164`).
  - Values ≥ 2^31 make the signed remainder `amt` negative, so it returns immediately with no warning (`JSCore.cpp:136-139`). Negative inputs wrap, for example `delay(-1)` becomes 4294967295, which returns immediately.
  - Extra arguments are ignored.
- **Returns:** (unset) on every path.
- **Preconditions:** either game state.
- **Threading & blocking:** runs on the caller's thread. It loops until `GetTickCount() - start >= ms` (`JSCore.cpp:139-161`). Each iteration:
  1. `WaitForSingleObjectEx(script->eventSignal, amt, TRUE)`. This is an **alertable** wait: it wakes on a new event, on timeout, or after running queued APCs such as timer expiries (`JSCore.cpp:140`).
  2. `ResetEvent` (`JSCore.cpp:141`).
  3. If `IsAborted()`, `break` (`JSCore.cpp:142-143`).
  4. While `EventList` isn't empty, and the script isn't aborted, and not (`InGame` state and `ClientState()==ClientStateMenu`): `pop_back` under `Vars.cEventSection` and call `ExecScriptEvent(evt, false)` (`JSCore.cpp:145-151`). Listeners run synchronously here, re-entrantly on the same thread. A listener that calls `delay()` nests another loop on the same queue.
  5. If `JSGC_BYTES - LastGC > 524288`, run a full `JS_GC` on the script's runtime (`JSCore.cpp:152-156`).
  6. Recompute `amt` (`JSCore.cpp:159`).

  No locks are held while waiting. Timing granularity is that of `GetTickCount`.
- **Pause and stop while sleeping:**
  - **Pause** (`Script::Pause`, `Script.cpp:217`) sets `isPaused`, triggers the operation callback and signals. `delay` doesn't check `isPaused`: it keeps sleeping and keeps calling handlers. Because the operation callback was triggered, the next interrupt check in JS (inside a handler, or in the code after `delay` returns) enters `operationCallback`, which spins in `Sleep(50)` plus `JS_MaybeGC` while paused (`ScriptEngine.cpp:304-313`).
  - **Stop** (`Script::Stop`, `Script.cpp:251`) sets `isAborted`, triggers and signals, so `delay` wakes and breaks. **`delay` then returns normally (`JS_TRUE`).** Termination happens at the engine's next operation-callback check, which returns false for an aborted script (`ScriptEngine.cpp:315-326`). Statements right after `delay()`, such as a native call, may still execute.
  - An `InGame` script at the menu doesn't drain events during `delay`. When it next reaches the operation callback, it is terminated.
- **Side effects:** runs this script's queued events of every type: listeners, timers, `scriptmsg`, the console's `"Command"` events, and `"DisposeMe"`. Can trigger a GC.
- **Game internals:** `ClientState()` per drained event (`D2Helpers.cpp:125`).
- **Quirks / bugs:**
  - A `"DisposeMe"` event fired by another thread's `DisposeScript` (`ScriptEngine.cpp:85-88`, from `FlushCache`/`Shutdown`) deletes the `Script` *inside* `delay()` (`ScriptEngine.cpp:792-793`). The loop then dereferences the freed `script`.
  - On the console script, a `"Command"` event frees `evt->name` and then keeps comparing it, because the block has no `return` (`ScriptEngine.cpp:687-709`). With `clearList=true` it would also use an uninitialised `cx` (`ScriptEngine.cpp:453-456`).
  - `EventList.size()` is read outside the lock (`JSCore.cpp:145`).
  - The legacy description ("suspending the context ... 50 ms") is stale (`doc/globalFuncs.h:772-781`).

### `setTimeout(callback, ms)`

Schedules `callback` to run once after `ms` milliseconds (see [How timers and event servicing work](#how-timers-and-event-servicing-work)).

- **Native:** `my_setTimeout` at `JSCore.cpp:78`; registered at `JSGlobalFuncs.h:41` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `callback` must be a function (`JSVAL_IS_FUNCTION`). String code isn't supported: the call silently returns `null`.
  - `ms` must pass `JSVAL_IS_NUMBER` and is read with `JSVAL_TO_INT` (`JSCore.cpp:84-86`).
  - If `argc < 2` or `ms` isn't a number, `JS_ReportError("invalid params passed to setTimeout")` is called, **but execution continues** and returns `JS_TRUE` (`JSCore.cpp:81-82`). The following `JSVAL_IS_FUNCTION(argv[0])` is an argc-unchecked read.
  - Extra arguments are ignored. The callback is called with 0 arguments.
- **Returns:** an integer timer id: global, sequential, starting at 1, shared with `setInterval` (`JSCore.cpp:92`). `null` if the arguments don't match.
- **Preconditions:** either game state.
- **Threading & blocking:** non-blocking. The callback later runs on **this script's thread**, only after the due time and only while the thread is in `delay()`/`setSkill`, or at an operation-callback point once queued.
- **Side effects:** creates a Win32 waitable timer and an `Event`. Adds a rooted listener under `"setTimeout"`. Appends to the global `DelayedExecList`.
- **Game internals:** none.
- **Quirks / bugs:** all of [the timer consequences](#how-timers-and-event-servicing-work) apply. In particular, every pending `setTimeout` callback of the script runs whenever any one of them fires. Not documented in `doc/globalFuncs.h`.

### `setInterval(callback, ms)`

Schedules `callback` to run every `ms` milliseconds.

- **Native:** `my_setInterval` at `JSCore.cpp:98`; registered at `JSGlobalFuncs.h:42` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** identical to `setTimeout`, with the error message `"invalid params passed to setInterval"` (`JSCore.cpp:101-102`). The period is `ms` (`ScriptEngine.cpp:809`).
- **Returns:** an integer id, or `null` (`JSCore.cpp:112`).
- **Preconditions:** either game state.
- **Threading & blocking:** as `setTimeout`. Ticks that come due while the thread isn't in an alertable wait are delivered at its next alertable wait; whether several missed ticks produce several APCs or coalesce into one is Windows behaviour that the source doesn't determine.
- **Side effects:** as `setTimeout`, under the name `"setInterval"`. The same `Event` object is re-queued on every tick.
- **Game internals:** none.
- **Quirks / bugs:**
  - Every interval callback of the script runs on every tick of any interval.
  - `ms == 0` fires once.
  - The timer is never cleaned up when the script ends.
  - `clearInterval` inside the callback causes iterator invalidation.

### `clearTimeout(id)`

**Alias:** registered with the `my_clearInterval` native, so it behaves exactly like [`clearInterval`](#clearintervalid).

- **Native:** `my_clearInterval` at `JSCore.cpp:117`; registered at `JSGlobalFuncs.h:41` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** see `clearInterval`. The error text says `"clearInterval"` even when called as `clearTimeout`.
- **Returns:** `null`.
- **Preconditions:** either game state.
- **Threading & blocking:** see `clearInterval`.
- **Side effects:** see `clearInterval`. It works on both timeout and interval ids.
- **Game internals:** none.
- **Quirks / bugs:** see `clearInterval`.

### `clearInterval(id)`

Cancels the timer whose id is `id`, in **any** script.

- **Native:** `my_clearInterval` at `JSCore.cpp:117`; registered at `JSGlobalFuncs.h:42` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - If `argc != 1` or `id` isn't a number, `JS_ReportError("invalid params passed to clearInterval")` is called, **and execution continues** (`JSCore.cpp:119-120`).
  - It then calls `RemoveDelayedEvent(JSVAL_TO_INT(argv[0]))` (`JSCore.cpp:122`). `clearInterval(undefined)` and `clearInterval(null)` therefore read payload 0, which matches nothing. A string or object id passes its pointer payload as the key; a double id passes the low 32 bits of the IEEE value. Either can, by coincidence, cancel an unrelated timer.
- **Returns:** `null` (`JSCore.cpp:118`).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Scans the global `DelayedExecList` **without a lock**, then leaves `Vars.cEventSection` without having entered it (`ScriptEngine.cpp:818-835`).
- **Side effects:** `CancelWaitableTimer` and `CloseHandle`; `UnregisterEvent` on the timer owner's listener map (which takes the owner's lock); frees the `Event`.
- **Game internals:** none.
- **Quirks / bugs:**
  - Can cancel another script's timer.
  - Use-after-free if the id belongs to a script that has already ended.
  - Unbalanced critical-section leave.
  - Unsafe when called from inside the timer's own callback.

---

## Event listener registration

This section covers registration only. Event names, arguments, origins and blocking semantics are in [events.md](events.md).

### Listener storage

| Aspect | Fact |
|---|---|
| Container | `Script::functions`: `std::map<std::string, std::list<AutoRoot*>>` (`Script.h:17-19`, `Script.h:136`). One per script. |
| Key | Event name as UTF-8 (`JS_EncodeStringToUTF8`), exact and case-sensitive. **Any non-empty name is accepted.** Names are not validated against the events D2BS fires, so typos register silently (for example the legacy `keydownblock`/`keyupblock`, `doc/globalFuncs.h:943-945`; the code fires `keydownblocker`/`keyupblocker`, `Events.cpp:55`). |
| Value | The function `jsval` wrapped in `AutoRoot`, which calls `JS_AddNamedValueRoot(cx, &var, "AutoRoot")` (`AutoRoot.cpp:4-6`, `AutoRoot.cpp:22-25`). The closure is kept alive until it is removed. |
| Duplicates | Allowed. `RegisterEvent` always `push_back`s (`Script.cpp:352-359`); `IsRegisteredEvent` (`Script.cpp:361`) is never called. A function added twice runs twice per event. |
| Limits | None, on names or on listeners per name. |
| Order | Insertion order. Dispatch iterates `begin()`→`end()` (for example `ScriptEngine.cpp:721`). |
| Identity | Removal compares raw `jsval` bits (`Script.cpp:385`), so it means the same function object. A fresh closure or a `bind()` result never matches. |
| Locking | Mutations hold the script's `lock` (`Script.cpp:353`, `Script.cpp:382`, `Script.cpp:402`, `Script.cpp:413`). `IsListenerRegistered` (`Script.cpp:348-350`) is called from the game and other threads by every event producer (`Events.cpp`) **without** that lock, which is a data race on `std::map`. Dispatch on the script thread iterates the list without the lock. |
| Shared with timers | `setTimeout`/`setInterval` store their callbacks under the names `"setTimeout"`/`"setInterval"` in this same map. |
| Cost of registering | Producers create an `Event` per script for which `IsListenerRegistered(name)` is true. For blocking events (`*blocker`, `gamepacket`, `gamepacketsent`, `realmpacket`), the producing thread, often the **game thread**, waits for this script: up to 500 ms for chat blockers and packets, up to 1000 ms for key blockers (`Events.cpp:189-201`, `Events.cpp:308-318`, `Events.cpp:55-67`). |
| Re-entrancy | Removing listeners of the event being dispatched from inside a handler invalidates the dispatcher's iterator and deletes the node (UB). Adding a listener to the same event during dispatch is safe for `std::list`, and the new listener runs in the same dispatch. |
| Lifetime | Cleared by `ClearAllEvents` when the context is destroyed (`ScriptEngine.cpp:387`). |

### `addEventListener(name, listener)`

Appends `listener` to the calling script's list for `name`.

- **Native:** `my_addEventListener` at `JSCore.cpp:470`; registered at `JSGlobalFuncs.h:46` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `name` must be a string and `listener` a function (`JSCore.cpp:471`). Otherwise the call is silently ignored. argc is not checked against 2.
  - An empty or unencodable name throws `"Event name is invalid!"` (`JSCore.cpp:473-477`).
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Takes the script's `lock`.
- **Side effects:** adds a GC root. From now on, producers of `name` queue events to this script, and blocking producers wait for it.
- **Game internals:** none.
- **Quirks / bugs:**
  - No duplicate check.
  - Any string is accepted.
  - On the empty-name throw path, the `evtName` buffer leaks (the `JS_free` at `JSCore.cpp:478` is skipped).

### `removeEventListener(name, listener)`

Removes the **first** registration of `listener` under `name`.

- **Native:** `my_removeEventListener` at `JSCore.cpp:483`; registered at `JSGlobalFuncs.h:47` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:** same type gate and `"Event name is invalid!"` throw as `addEventListener` (`JSCore.cpp:484-490`).
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Takes the script's `lock`.
- **Side effects:** `Script::UnregisterEvent` (`Script.cpp:378-399`) finds the first `jsval`-equal entry, removes it and deletes it, which removes the GC root. If the list becomes empty, the map key is erased (`Script.cpp:395-396`), and `IsListenerRegistered(name)` becomes false. If nothing matches, it is a harmless no-op.
- **Game internals:** none.
- **Quirks / bugs:**
  - A function registered twice must be removed twice.
  - Unsafe while `name` is being dispatched (see [Listener storage](#listener-storage)).

### `clearEvent(name)`

Removes all listeners for `name` from the calling script.

- **Native:** `my_clearEvent` at `JSCore.cpp:496`; registered at `JSGlobalFuncs.h:47` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `name` must be a string; otherwise the call does nothing (`JSCore.cpp:497`). argc unchecked.
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Takes the script's `lock`.
- **Side effects:** `Script::ClearEvent` (`Script.cpp:401-410`) releases and deletes each `AutoRoot` and empties the list.
- **Game internals:** none.
- **Quirks / bugs:**
  - **The map key is left in place** with an empty list, and `functions[name]` even *creates* the key for a name that was never registered. `IsListenerRegistered(name)` therefore stays **true** (`Script.cpp:349`). Producers keep creating events for this script, and blocking producers keep waiting for it (up to 500 or 1000 ms per event on the game thread if the script is busy), even though nothing listens. Use `removeEventListener` or `clearAllEvents` instead.
  - `clearEvent("setTimeout")` and `clearEvent("setInterval")` disable pending timer callbacks without cancelling the timers.

### `clearAllEvents()`

Removes every listener, for every name, from the calling script, including timer callbacks.

- **Native:** `my_clearAllEvents` at `JSCore.cpp:506`; registered at `JSGlobalFuncs.h:48` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Takes the script's `lock` (recursive), calls `ClearEvent` per key, then `functions.clear()` (`Script.cpp:412-418`).
- **Side effects:** all GC roots are released and all keys removed, so `IsListenerRegistered` becomes false for everything.
- **Game internals:** none.
- **Quirks / bugs:**
  - Pending `setTimeout`/`setInterval` timers stay armed and in `DelayedExecList`; they now dispatch to nothing.
  - Calling it from inside a handler is unsafe (iterator invalidation).

---

## Inter-script messaging

### `scriptBroadcast(...values)`

Queues a `"scriptmsg"` event carrying deep copies of `values` to every running script that listens for `scriptmsg`, **including the sender**.

- **Native:** `my_scriptBroadcast` at `JSCore.cpp:532`; registered at `JSGlobalFuncs.h:49` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** one or more values of any structured-clone-able type. `argc < 1` throws `"You must specify something to broadcast"` (`JSCore.cpp:534-535`).
- **Returns:** `null` (`JSCore.cpp:533`). There is no delivery count or acknowledgement.
- **Preconditions:** either game state.
- **Threading & blocking:**
  - `ScriptBroadcastEvent` (`Events.cpp:168-171`) calls `ScriptEngine::ForEachScript(BCastEventCallback, ...)` synchronously on the sender's thread.
  - `ForEachScript` copies the script map into a vector under `scriptListLock`, releases the lock, and then calls the callback for each script (`ScriptEngine.cpp:204-228`). A recipient can be disposed concurrently, so this is a use-after-free race.
  - For each script with `IsRunning()` and `IsListenerRegistered("scriptmsg")` (`Events.cpp:151`):
    1. Allocate an `Event{name="scriptmsg", arg1=new DWORD(argc), argc}`.
    2. **Serialise each value separately for this recipient** with `JSAutoStructuredCloneBuffer::write(senderCx, v)` (`Events.cpp:152-160`). That is N recipients × M values serialisations on the sender thread, and the `write` result is unchecked.
    3. Call `FireEvent` (`Events.cpp:163`).

    The sender does not wait.
- **Delivery:**
  - Each recipient handles the event on its own thread, in `delay()`, in `setSkill`'s wait loop, or at an operation-callback point (`ScriptEngine.cpp:709-737`).
  - Values are deserialised into the **recipient's** context with `read(cx, &argv[i])`. Each listener is called as `listener(v0, v1, ...)` with `this` = global, and return values are ignored.
  - The clone buffers are then cleared and freed. The `argv` pointer array itself leaks.
  - Order is FIFO per recipient. There is no ordering across recipients.
- **Side effects:** heap allocations per recipient. Recipients' operation callbacks are triggered.
- **Game internals:** none.
- **Quirks / bugs:**
  - **The sender receives its own broadcast** if it listens. Legacy `doc/globalFuncs.h:1086` says "all *other* scripts".
  - **Paused scripts are skipped**: `IsRunning()` is false while paused (`Script.cpp:340-342`), so the message is dropped, not queued.
  - Scripts that have no `scriptmsg` listener at broadcast time never see the message.
  - Non-cloneable values (functions, `Unit` and other host objects) make `write` fail (no custom clone callbacks exist). What the sender sees, and what the recipient's `read` of an empty buffer does, are open questions.
  - The same `"scriptmsg"` path is used by `Script.prototype.send` (`JSScript.cpp:107`). See [utility-classes.md](utility-classes.md).

---

## Console & logging

### `print(...values)`

Converts each non-null argument to a string and queues it, as a separate line, for the D2BS console (and optionally the in-game chat).

- **Native:** `my_print` at `JSCore.cpp:49`; registered at `JSGlobalFuncs.h:40` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - Any number of values.
  - `null` arguments are skipped silently (`JSCore.cpp:52`).
  - Everything else goes through `JS_ConvertValue(JSTYPE_STRING)`, which can call user `toString` (`JSCore.cpp:54`).
  - A conversion failure throws `"Converting to string failed"`; a NULL char pointer throws `"Could not get string for value"` (`JSCore.cpp:56`, `JSCore.cpp:63`).
- **Returns:** `null` (`JSCore.cpp:50`).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. `Print` (`Core.cpp:51`) formats the text and pushes it onto `Vars.qPrintBuffer` under `Vars.cPrintSection` (`Core.cpp:60-62`).
- **Delivery:**
  - The **game thread** drains the queue in `FlushPrint` (`D2Handlers.cpp:353`). It is called from `GameDraw` only while `Vars.bActive` and in game (`D2Handlers.cpp:400-401`), and from `GameDrawOOG` only while at the menu (`D2Handlers.cpp:423-424`).
  - In loading or busy states, lines wait in the queue. `FlushPrint` uses `TryEnterCriticalSection` and skips a frame on contention (`D2Handlers.cpp:354`).
  - Each queued string is split on `\n` and added with `Console::AddLine`, which wraps at console width, caps history at 300 lines, and copies to the log when `LogConsoleOutput=true` (`Console.cpp:101-119`).
  - With `UseGamePrint=true` and in game, the text also goes to `D2CLIENT_PrintGameString(line, 0)` (`D2Handlers.cpp:374-382`).
- **Side effects:** console buffer; optional log file; optional game chat.
- **Game internals:** `D2CLIENT_PrintGameString` (`D2Ptrs.h:103`), only through `FlushPrint`.
- **Quirks / bugs:**
  - Each argument becomes its own line: `print("a", "b")` prints two lines.
  - `print(null)` prints nothing.
  - D2 colour codes (`ÿcN`) are interpreted by the renderer.
  - The `if (!Text)` branch is dead code (`JSCore.cpp:68`).

### `debugLog(...values)`

Writes each non-null argument, converted to a string, as its own line in the D2BS log file.

- **Native:** `my_debugLog` at `JSCore.cpp:307`; registered at `JSGlobalFuncs.h:50` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** same conversion rules and error messages as `print` (`JSCore.cpp:309-321`).
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:**
  - Caller's thread, synchronous file I/O.
  - `Log` (`D2Helpers.cpp:17`) strips one trailing `\n`. `LogNoFormat` (`D2Helpers.cpp:33`) opens `<szLogPath>d2bs-<profile>-<YYYYMMDD>.log` with `_wfsopen(..., "a+", _SH_DENYNO)` for every line, writes `"[%x %X] D2BS <pid>: <utf-8 text>"`, flushes and closes it.
  - No lock is taken, so concurrent writers interleave.
- **Side effects:** log file append. In `DEBUG` builds the output goes to `stderr` instead.
- **Game internals:** none.
- **Quirks / bugs:** the text is converted with `UnicodeToAnsi(..., CP_UTF8)`, so the log file is UTF-8.

### `showConsole()`

Makes the D2BS console buffer visible and enables its input prompt.

- **Native:** `my_showConsole` at `JSCore.cpp:541`; registered at `JSGlobalFuncs.h:51` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. `Console::Show` (`Console.cpp:179`) sets `visible=true` and `enabled=true` under `Vars.cConsoleSection`. The game thread draws the console in `GameDraw`/`GameDrawOOG`.
- **Side effects:** while the prompt is enabled, D2BS's keyboard hook routes keystrokes to the console (`D2Handlers.cpp:241`).
- **Game internals:** none.
- **Quirks / bugs:** none found.

### `hideConsole()`

Hides the console buffer and disables the prompt.

- **Native:** `my_hideConsole` at `JSCore.cpp:547`; registered at `JSGlobalFuncs.h:51` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** either game state.
- **Threading & blocking:** `Console::Hide` (`Console.cpp:158`) sets `enabled=false` and `visible=false` under `Vars.cConsoleSection`.
- **Side effects:** console UI state.
- **Game internals:** none.
- **Quirks / bugs:** `reportError` calls `Console::ShowBuffer()` after every reported error or warning, except when `QuitOnError` exits the game instead (`ScriptEngine.cpp:446-449`). The console therefore reappears.

---

## Clipboard & OS IPC

The receiving side of D2BS IPC (D2BS's own `WM_COPYDATA` handler and its DDE server `d2bs-<pid>`) is in [../architecture.md](../architecture.md).

### `copy(text)`

Puts `text` on the Windows clipboard as `CF_TEXT`.

- **Native:** `my_copy` at `JSCore.cpp:335`; registered at `JSGlobalFuncs.h:45` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `text` must be a string. `JSVAL_TO_STRING` is applied with no type test and argc unchecked (`JSCore.cpp:336`), so a number, or no argument, dereferences an invalid pointer. The `JS_ValueToString` call on the next line has no effect (`JSCore.cpp:338`).
- **Returns:** (unset).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Win32 clipboard calls.
- **Side effects:**
  - `GlobalAlloc(GMEM_DDESHARE|GMEM_MOVEABLE)` and a copy of the **UTF-8** bytes (`JSCore.cpp:341-345`).
  - `OpenClipboard(NULL)`, `EmptyClipboard`, `SetClipboardData(CF_TEXT)`, `CloseClipboard` (`JSCore.cpp:347-350`).
- **Game internals:** none.
- **Quirks / bugs:**
  - Neither the `OpenClipboard` nor the `SetClipboardData` result is checked. On failure the `HGLOBAL` leaks and nothing is copied.
  - The clipboard is opened with a NULL owner window. Microsoft documents that after `OpenClipboard(NULL)`, `EmptyClipboard` sets the owner to NULL and `SetClipboardData` then fails. Whether that happens on the target systems is not determinable from source (see [Open questions](#open-questions)).
  - If `JS_EncodeStringToUTF8` returns NULL, `strlen(NULL)` crashes (`JSCore.cpp:336`, `JSCore.cpp:341`).
  - The data is UTF-8 but labelled `CF_TEXT` (ANSI), so other applications see mojibake for non-ASCII text.

### `paste()`

Returns the clipboard's `CF_TEXT` content.

- **Native:** `my_paste` at `JSCore.cpp:354`; registered at `JSGlobalFuncs.h:45` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** a string, decoded from `CF_TEXT` bytes **as UTF-8** (`AnsiToUnicode` default, `JSCore.cpp:360`).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:**
  - The clipboard is closed **before** `GlobalLock` is called on its handle (`JSCore.cpp:355-358`), which the clipboard API doesn't allow. The handle is never unlocked.
  - With no text on the clipboard, `GlobalLock(NULL)` gives NULL, `AnsiToUnicode(NULL)` allocates a zero-length unterminated buffer, and `JS_NewUCStringCopyZ` reads garbage or crashes.
  - Non-ASCII text from other applications (ANSI code page) is mis-decoded as UTF-8. It only round-trips with `copy()`.

### `sendCopyData(windowClass, windowNameOrHwnd, mode, data)`

Sends a `WM_COPYDATA` message to a window, synchronously.

- **Native:** `my_sendCopyData` at `JSCore.cpp:365`; registered at `JSGlobalFuncs.h:45` (declared arity 4, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc < 4` returns `false` (`JSCore.cpp:367-369`).

  | Arg | Accepted | Meaning (`JSCore.cpp:377-394`) |
  |---|---|---|
  | `windowClass` | string or anything | A string is the `FindWindowW` class name; anything else means NULL. |
  | `windowNameOrHwnd` | number / string / null | A number is converted with `ToUint32` and used directly as the `HWND` (e.g. `handler()`). A string is the `FindWindowW` window name. `null` means neither. |
  | `mode` | number | `COPYDATASTRUCT.dwData` (`ToUint32`). Any non-number becomes 0. |
  | `data` | string | Encoded as UTF-8 and sent including the NUL. A non-string sends `""`. |

  `FindWindowW(class, name)` is only called when no HWND was given **and** a window name string was given (`JSCore.cpp:397-403`). Passing only a class name sends to `NULL`.
- **Returns:**
  - `false` if `argc < 4` or `FindWindowW` fails.
  - Otherwise the integer LRESULT of `SendMessage(hWnd, WM_COPYDATA, (WPARAM)D2GFX_GetHwnd(), &cds)` (`JSCore.cpp:412`), which is 0 when `hWnd` is NULL or invalid. A D2BS receiver always returns `TRUE`, so the result is `1` for any mode (`D2Handlers.cpp:200`).
- **Preconditions:** either game state.
- **Threading & blocking:** **`SendMessage` blocks the script thread with no timeout** until the target's window procedure returns. If the target is this game's own window, the message is handled on the game thread (`GameEventHandler`, `D2Handlers.cpp:176`, `WM_COPYDATA` case at `D2Handlers.cpp:179`). The script then waits on the game thread. If the game thread is itself waiting on this script in a blocking event, the two wait on each other until the producer's 500/1000 ms timeout expires. A D2BS receiver handling mode `0x1337` also spins in `Sleep(100)` until the engine is running (`D2Handlers.cpp:186-188`), and the sender waits through that.
- **Side effects:**
  - Cross-process IPC. `wParam` is the sender's D2 window.
  - A D2BS receiver interprets `mode 0x1337` as "run this as a console command" and `0x31337` as "switch profile". Any other mode fires a `"copydata"` event (`D2Handlers.cpp:184-196`). A D2BS receiver decodes the data as UTF-8 (`D2Handlers.cpp:183`), which matches this sender.
- **Game internals:** `D2GFX_GetHwnd` (`D2Ptrs.h:382`).
- **Quirks / bugs:**
  - When `data` isn't a string, `data = ""` (a string literal) is later passed to `JS_free` (`JSCore.cpp:406-415`). That frees a static literal and corrupts the heap.
  - There is no `SendMessageTimeout`.
  - The legacy two-overload description (`doc/globalFuncs.h:874`, `doc/globalFuncs.h:892`) matches loosely, but the "dummy" second argument is in fact the name/HWND slot.

### `sendDDE(mode, server, topic, item, data)`

Performs one DDEML client transaction (request, poke or execute).

- **Native:** `my_sendDDE` at `JSCore.cpp:419`; registered at `JSGlobalFuncs.h:46` (declared arity 0, `FUNCTION_FLAGS`). argc is never checked, and all five slots are read (`JSCore.cpp:425-438`).
- **Arguments / overloads:**
  - `mode`: **bug.** The code tests `JSVAL_IS_INT(argv[0])` but converts **`argv[1]`** (`JSCore.cpp:425-426`). With the normal call shape, `argv[1]` is the server name string, and `ToUint32("name")` is 0, so **mode is always 0 (XTYP_REQUEST)**. If `argv[0]` isn't an int, `mode` stays uninitialised stack data (`JSCore.cpp:421`).
  - `server`, `topic`, `item`, `data`: strings encoded as UTF-8. A non-string falls back to the literal `"\"\""` (`JSCore.cpp:422`).
- **Returns:**
  - `mode == 0`: up to 254 bytes of the response, decoded as UTF-8 (`JSCore.cpp:452-456`).
  - Other modes: `false`, even on success (`JSCore.cpp:420`).
  - Throws `"DDE Failed! Check the log for the error message."` when `SendDDE` returns FALSE, which only happens if `DdeInitialize` or string-handle creation fails (`JSCore.cpp:449-450`, `dde.cpp:64-78`).
- **Preconditions:** either game state.
- **Threading & blocking:** `SendDDE` (`dde.cpp:57`) runs these steps on the script thread:
  1. Create a fresh `DdeInitialize(APPCMD_CLIENTONLY)` instance.
  2. `DdeConnect`.
  3. `DdeClientTransaction` with a **5000 ms** timeout (`dde.cpp:60`, `dde.cpp:82-94`).
  4. Free the string handles and call `DdeUninitialize`.
- **Side effects:**
  - Logs all arguments: `"SendDDE(%d, server, topic, item, data, ...)"` (`dde.cpp:62`).
  - Mode 0: `XTYP_REQUEST` on `item` with `CF_TEXT`. Mode 1: `XTYP_POKE` of `data` to `item`. Mode 2: `XTYP_EXECUTE` of `data`.
- **Game internals:** none.
- **Quirks / bugs:**
  - Whenever any of args 1-4 isn't a string, its default literal is passed to `JS_free` (`JSCore.cpp:444-447`), which corrupts the heap. The legacy 4-argument form `sendDDE(mode, server, topic, item)` (`doc/globalFuncs.h:915`) always hits this, because `data` (slot 4) is missing.
  - **Against a D2BS DDE server** (`d2bs-<pid>`, see [../architecture.md](../architecture.md)), mode 0 can't work: the server is registered with `CBF_FAIL_REQUESTS` (`dde.cpp:36`). Its poke and execute handlers also convert `pszItem` to UTF-16 **before** `DdeGetData` fills it (`dde.cpp:10-11` vs `dde.cpp:16`/`dde.cpp:23`), so they act on an empty string.
  - A `DdeConnect` failure is not detected (`dde.cpp:80`): in mode 0 the call returns an empty string, otherwise `false`.
  - The response isn't NUL-terminated when it is 255 bytes or longer (`dde.cpp:85`, buffer at `JSCore.cpp:441`), so the decode over-reads.
  - Strings are UTF-8 but the handles are created with `CP_WINANSI`.
  - The request data handle is never freed with `DdeFreeDataHandle`.
  - The error path at `dde.cpp:74-77` leaks the DDE instance.

---

## Input simulation

### `keystate(vk)`

Returns `!!GetAsyncKeyState(vk)`.

- **Native:** `my_keystate` at `JSCore.cpp:460`; registered at `JSGlobalFuncs.h:46` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `vk` must be an int jsval. A missing or non-int argument (a double included) returns `false` (`JSCore.cpp:462-463`).
- **Returns:** a boolean (`JSCore.cpp:465`).
- **Preconditions:** either game state.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:**
  - Physical, system-wide key state. Keys posted by `sendKey` aren't reflected.
  - `!!` also counts the "pressed since last call" low bit, so it can return `true` for a key that has already been released.

### `sendClick(x, y)`

Posts a left-button down and up at client coordinates (x, y) to the D2 window.

- **Native:** `my_sendClick` at `JSCore.cpp:677`; registered at `JSGlobalFuncs.h:70` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments("uu")` (`JSCore.cpp:682`). A missing argument throws `TypeError` (JSMSG_MORE_ARGS_NEEDED). Values are converted with ToUint32.
- **Returns:** `null` (`JSCore.cpp:678`).
- **Preconditions:** either game state. No UI check.
- **Threading & blocking:** **about 300 ms of plain `Sleep`** on the script thread (`JSCore.cpp:687-691`). The sleep isn't alertable, so no events or timers are serviced.
- **Side effects:** `SendMouseClick(x, y, 0)` then `(x, y, 1)` calls `PostMessage(D2GFX_GetHwnd(), WM_LBUTTONDOWN/UP, 0, x + (y << 16))` (`D2Helpers.cpp:305-322`). The messages are handled later by the game thread.
- **Game internals:** `D2GFX_GetHwnd` (`D2Ptrs.h:382`).
- **Quirks / bugs:**
  - `x > 0xFFFF` spills into `y`.
  - `wParam` is 0 (no `MK_LBUTTON`).
  - D2BS's own `WH_MOUSE` hook (`MouseMove`, `D2Handlers.cpp:296`, installed as a thread hook on the game window's thread at `Helpers.cpp:187`) takes its coordinates from `MOUSEHOOKSTRUCT.pt`, not from the posted `lParam` (`D2Handlers.cpp:297-299`). If the hook sees these posted messages at all (see [Open questions](#open-questions)), any `mouseclick` event or screen-hook hit test it triggers uses the point Windows reports for the message, not necessarily (x, y).
  - Not in the legacy docs.

### `sendKey(vk)`

Posts `WM_KEYDOWN` and `WM_KEYUP` for virtual key `vk` to the D2 window, temporarily disabling the console prompt.

- **Native:** `my_sendKey` at `JSCore.cpp:695`; registered at `JSGlobalFuncs.h:70` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments("u")` (`JSCore.cpp:699`). A missing argument throws `TypeError`.
- **Returns:** `null` (`JSCore.cpp:696`).
- **Preconditions:** either game state.
- **Threading & blocking:** about 300 ms of plain `Sleep` (`JSCore.cpp:708-712`).
- **Side effects:**
  - If the console prompt is enabled, calls `Console::HidePrompt()` before and `Console::ShowPrompt()` after (`JSCore.cpp:704-715`). The apparent intent: while the prompt is enabled, D2BS's `WH_KEYBOARD` thread hook (`Helpers.cpp:185`) routes keys into the console and returns 1 (`D2Handlers.cpp:241-288`). That only matters if the hook sees posted messages (see [Open questions](#open-questions)).
  - `SendKeyPress` (`D2Helpers.cpp:324-334`) posts with `lParam = 1 | MapVirtualKey(vk, MAPVK_VK_TO_VSC) << 16`, plus `0xC0000000` for key-up.
- **Game internals:** `D2GFX_GetHwnd`.
- **Quirks / bugs:**
  - Messages are posted, so the prompt may be restored before the game thread processes them. That is a race; the 100 ms sleep only mitigates it.
  - No extended-key bit and no `WM_CHAR` is posted explicitly.
  - Not in the legacy docs.

### `beep([type])`

Calls `MessageBeep(type)`.

- **Native:** `my_beep` at `JSCore.cpp:255`; registered at `JSGlobalFuncs.h:63` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** an optional int (`JSCore.cpp:258-259`). A missing or non-int argument means 0 (`MB_OK` sound).
- **Returns:** `true`. The `MessageBeep` result is ignored (`JSCore.cpp:262`).
- **Preconditions:** either game state.
- **Threading & blocking:** none (asynchronous sound).
- **Side effects:** a system sound.
- **Game internals:** none.
- **Quirks / bugs:** none found.

---

## Packets

### Packet buffer encoding (shared by `sendPacket` and `getPacket`)

Both natives build a byte buffer in one of two ways (`JSCore.cpp:580-605`, `JSCore.cpp:625-650`):

1. **ArrayBuffer form:** `f(arrayBuffer)`. If `argv[0]` is an object (D2BS's own `JSVAL_IS_OBJECT`, which excludes `null`, `js32.cpp:62-64`), it must pass `JS_IsArrayBufferObject` (`dependencies/include/jsfriendapi.h:1103`); otherwise the call fails with the warning `"invalid ArrayBuffer parameter"`. **Typed arrays are rejected**, so pass `u8.buffer`. `byteLength` bytes are copied. There is no minimum or maximum length.
2. **(size, value) pairs:** `f(size0, value0, size1, value1, ...)`. An odd `argc` fails with the warning `"invalid packet format"`. A buffer of `2*argc` bytes (four bytes per pair) is allocated. For each pair:
   1. `size = ToUint32(size_i)`.
   2. `ToUint32(value_i)` is written as a **4-byte little-endian `uint32` at offset `len`**, whatever `size` is.
   3. `len += size`.

   Sizes 1 to 4 therefore produce correct little-endian fields: bytes beyond the field are overwritten by the next write or lie past `len`. They also keep every write inside the buffer, because the last write starts at most at offset `4*(pairs-1)`. **Sizes are not validated.** A size of 5 or more has three effects:
   - it leaves uninitialised gap bytes inside the packet;
   - it can make `len` exceed the allocation, so heap bytes are sent (over-read);
   - it pushes later 4-byte writes past the end (a **heap overflow**).

   Huge sizes wrap `len`. Example: `sendPacket(8,0, 8,0, 1,0x3c)` allocates 12 bytes, writes at offsets 0, 8 and 16, and sends 17 bytes.

Example of a well-formed call: `sendPacket(1,0x3c, 2,skillId, 1,0, 1,0x80, 4,itemId)` produces the 9 bytes `3c lo hi 00 80 id0 id1 id2 id3`.

### `sendPacket(...)`

Sends a raw client→server game packet through `D2NET_SendPacket`.

- **Native:** `my_sendPacket` at `JSCore.cpp:569`; registered at `JSGlobalFuncs.h:69` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** [ArrayBuffer or (size, value) pairs](#packet-buffer-encoding-shared-by-sendpacket-and-getpacket). With `argc == 0`, the `JSVAL_IS_OBJECT(argv[0])` test is an argc-unchecked read; if it falls through to the pairs path, an empty packet is sent.
- **Returns:** `true` after the send (`JSCore.cpp:610`). `false` plus a warning when `EnableUnsupported` is off (`"sendPacket requires EnableUnsupported = true in d2bs.ini"`, `JSCore.cpp:572-574`) or the format is invalid.
- **Preconditions:** `EnableUnsupported=true` in d2bs.ini (default `false`, `Helpers.cpp:130`, `Helpers.cpp:153`). **No in-game check**: out of game it still calls into `D2NET`, with unknown effect.
- **Threading & blocking:**
  - Calls `D2NET_SendPacket(len, 1, buf)` **directly on the script thread** (`JSCore.cpp:608`). No game lock is taken, and no D2NET critical section either: `p_D2NET_CriticalPacketSection` is declared "unused but we need to use it" with what looks like a stale offset (`D2Ptrs.h:370`).
  - D2BS patches a `JMP` to `GamePacketSent_Interception` at RVA `0x12AE5A` (`Patch.h:12`), 10 bytes into `D2NET_SendPacket` (RVA `0x12AE50`). Assuming that point is reached (see [Open questions](#open-questions)), each packet goes through `GamePacketSent` → `GamePacketSentEvent` (`D2Handlers.cpp:172-174`, `Events.cpp:337-340`):
    - The **calling script's own `gamepacketsent` listeners run synchronously inside `sendPacket`**, because the producer is on the owner's thread (`Events.cpp:306-307`).
    - For every other script that listens, the sender **waits up to 500 ms** on the shared `Vars.eventSignal` (`Events.cpp:308-318`). `ReleaseGameLock`/`TakeGameLock` around that wait only act on the game thread (`Events.cpp:347-355`), so they are no-ops here. `Vars.eventSignal` is a single process-wide manual-reset event used by every blocking producer (`Helpers.cpp:155`). A concurrent producer, or a late verdict from an earlier timed-out event (`ScriptEngine.cpp:763-765`), can therefore release this wait before the listener has decided.
    - A listener returning `true` blocks the packet. `GamePacketSent` then returns 0 (`D2Handlers.cpp:172-174`), and the stub writes 0 into a caller stack slot (`D2Intercepts.cpp:58`) before resuming at `D2CLIENT_SendPacket_II` (RVA `0x12AE62`, `D2Ptrs.h:284`; `D2Intercepts.cpp:60-67`). With `pushf` taking 2 bytes (implied by the `0x22` offsets), that is the same slot the size was read from (`D2Intercepts.cpp:51` vs `D2Intercepts.cpp:58`). So a blocked packet isn't skipped; the original code continues with length 0, and what D2 does with that can't be told from source. Details are in [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md).
- **Side effects:** network traffic to the game server. Byte layout is exactly as built (D2BS adds nothing). The buffer is freed after the call.
- **Game internals:** `D2NET_SendPacket`: `void __stdcall (size_t aLen, DWORD arg1, BYTE* aPacket)`, RVA `0x12AE50`, VA `0x0052AE50` (`D2Ptrs.h:362`). `arg1` is always `1`, as at every other call site (for example `JSGame.cpp:1250`). See [../memory/offsets.md](../memory/offsets.md) and [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md).
- **Quirks / bugs:**
  - Heap overflow or over-read with sizes of 5 or more.
  - Legacy docs claim "Maximum packet length is 20" (`doc/globalFuncs.h:1838`). No such limit exists.
  - Unsynchronised with the game thread.

### `getPacket(...)`

Injects a raw server→client packet into the client's receive path through `D2NET_ReceivePacket`, as if the server had sent it.

- **Native:** `my_getPacket` at `JSCore.cpp:614`; registered at `JSGlobalFuncs.h:69` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** same encoding as `sendPacket`.
- **Returns:** `true` (`JSCore.cpp:655`). `false` plus a warning when `EnableUnsupported` is off (`"getPacket requires EnableUnsupported = true in d2bs.ini"`, `JSCore.cpp:617-619`) or the format is invalid.
- **Preconditions:** `EnableUnsupported=true`. No in-game check.
- **Threading & blocking:** calls `D2NET_ReceivePacket(buf, len)` **on the script thread** (`JSCore.cpp:653`), so the client's packet handlers run concurrently with the game thread. No lock is taken.
- **Side effects:** client state changes as dictated by the packet.
- **Game internals:**
  - `D2NET_ReceivePacket`: `void __fastcall (BYTE* aPacket, DWORD aLen)`, RVA `0x12AEB0`, VA `0x0052AEB0` (`D2Ptrs.h:363`).
  - D2BS's receive hook is a different call site: `GamePacketReceived_Intercept` at D2Client RVA `0x5F802` (`Patch.h:11`), which calls `D2NET_ReceivePacket_I` (RVA `0x12B920`, `D2Ptrs.h:364`; `D2Intercepts.cpp:24-43`). Whether an injected packet passes through it (and so fires `gamepacket` listeners, or triggers the `0xAE` "Warden" `TerminateProcess` at `D2Handlers.cpp:147-149`) can't be told from the source.
- **Quirks / bugs:**
  - Same buffer overflow as `sendPacket`.
  - Legacy "max 20" claim (`doc/globalFuncs.h:1826`).
  - The legacy doc describes it as "Send a packet to the client", which is accurate.

---

## Misc

### `getTickCount()`

Returns `GetTickCount()`.

- **Native:** `my_getTickCount` at `JSCore.cpp:266`; registered at `JSGlobalFuncs.h:36` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** a number in `[0, 2^32)`, in milliseconds since boot, built with `JS_NumberValue((jsdouble)GetTickCount())` (`JSCore.cpp:269`). `JS_NumberValue` int-tags values that fit in int32 and makes a double otherwise (`dependencies/include/jsapi.h:1204-1211`), so after about 24.9 days of uptime the value is a double. It wraps after about 49.7 days.
- **Preconditions:** either game state.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** granularity is the system tick (about 10-16 ms).

### `getIP()`

Fetches the external IPv4 address from a hard-coded HTTP service.

- **Native:** `my_getIP` at `JSCore.cpp:660`; registered at `JSGlobalFuncs.h:70` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** a string of at most 31 bytes, each inflated to one UTF-16 unit (`JSCore.cpp:668-672`).
- **Preconditions:** either game state. Needs network access.
- **Threading & blocking:** **synchronous WinINet on the script thread**: `InternetOpen(PRECONFIG)`, then `InternetOpenUrl("http://ipv4bot.whatismyipaddress.com", INTERNET_FLAG_RELOAD)`, then a single `InternetReadFile` of 32 bytes (`JSCore.cpp:665-667`). WinINet's default timeouts apply.
- **Side effects:** a plain-HTTP request to a third party.
- **Game internals:** none.
- **Quirks / bugs:**
  - No call is checked for failure. `rSize` starts **uninitialised** (`JSCore.cpp:662`) and `buffer` is not cleared. Microsoft documents that `InternetReadFile` sets the byte count to zero before any error checking, which would make a failed fetch return `""`. If it doesn't, the result is uninitialised stack bytes. The source alone can't decide this.
  - It reads only once (no loop).
  - Legacy docs name a different URL (`doc/globalFuncs.h:1847`).
  - The service's availability is outside the code.

### `loadMpq(path)`

Loads an MPQ archive into the game through `D2WIN_InitMPQ`, then clears the BNClient CD-key pointers.

- **Native:** `my_loadMpq` at `JSCore.cpp:558`; registered at `JSGlobalFuncs.h:58` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `path` must be a string. `JSVAL_TO_STRING` is applied with no type test and argc unchecked (`JSCore.cpp:560`).
- **Returns:** `null` always, including when the path is rejected (`JSCore.cpp:559`).
- **Preconditions:** either game state. `isValidPath(path)` must pass, which means relative and inside the script folder (`JSCore.cpp:562`).
- **Threading & blocking:** game code called on the script thread, with no game lock.
- **Side effects:**
  - `LoadMPQ(const wchar_t*)` (`Core.cpp:187`) converts the path to UTF-8 and calls `LoadMPQ(const char*)` (`Core.cpp:181`).
  - That calls `D2WIN_InitMPQ(path, 0, 0, 3000)` and sets `*p_BNCLIENT_XPacKey = *p_BNCLIENT_ClassicKey = *p_BNCLIENT_KeyOwner = NULL` (`Core.cpp:182-183`).
- **Game internals:**
  - `D2WIN_InitMPQ`: `DWORD __fastcall (const char* mpqfile, char* mpqname, int v4, int v5)`, RVA `0x117332` (`D2Ptrs.h:456`).
  - `p_BNCLIENT_ClassicKey`/`XPacKey`/`KeyOwner`: `char*` variables at RVA `0x482744`/`0x48274C`/`0x482750` (`D2Ptrs.h:469-471`).
  - The same routine is used for the `-mpq` command-line switch (`D2Handlers.cpp:49-55`).
- **Quirks / bugs:**
  - **The validated path and the loaded path differ.** `isValidPath` resolves `path` against the script folder (`File.cpp:220-249`), but the raw relative `path`, not the resolved full path, is passed to `D2WIN_InitMPQ` (`JSCore.cpp:563`). How `D2WIN_InitMPQ` resolves a relative path (process current directory, game directory or MPQ search path) can't be determined from source (see [Open questions](#open-questions)). The check therefore doesn't guarantee that the file loaded is the one validated.
  - The UTF-8 path is passed to an ANSI API.
  - The `InitMPQ` result is ignored.

### `stringToEUC(value)`

Converts `value` to the system ANSI code page (`CP_ACP`) and returns the bytes as a JS string, one byte per UTF-16 code unit. On a Korean system the ANSI code page is CP949, an EUC-KR superset, hence the name.

- **Native:** `my_stringToEUC` at `JSCore.cpp:22`; registered at `JSGlobalFuncs.h:40` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `argc == 0` or `null` returns `null` (`JSCore.cpp:24-26`).
  - Anything else is converted with `JS_ConvertValue(JSTYPE_STRING)`. Errors: `"Converting to string failed"` or `"Could not get string for value"` (`JSCore.cpp:29-41`).
- **Returns:** a string from `JS_NewStringCopyZ(UnicodeToAnsi(text, CP_ACP))` (`JSCore.cpp:43-44`). Characters that can't be mapped become `?` (`Helpers.cpp:26`; no conversion flags are passed, so Windows' default best-fit mapping applies first). The result is truncated at the first NUL.
- **Preconditions:** either game state.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:**
  - Despite the alias `utf8ToEuc`, the input is never UTF-8 bytes: it is the JS (UTF-16) string.
  - The output depends on the machine's ANSI code page.
  - Not in the legacy docs.

### `utf8ToEuc(value)`

**Alias of [`stringToEUC`](#stringtoeucvalue).** It is registered with the same native, so the behaviour is identical.

- **Native:** `my_stringToEUC` at `JSCore.cpp:22`; registered at `JSGlobalFuncs.h:40` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals / Quirks:** see `stringToEUC`.

---

## Hashing

### Shared implementation (`Hash.cpp`)

| Path | Function | Details |
|---|---|---|
| String hashes | `HashString(char*, ALG_ID)` (`Hash.cpp:8`) | 1. `CryptAcquireContext(PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)`. 2. `CryptCreateHash(algo)`. 3. Hash `strlen(input)` bytes of the **UTF-8** encoding (`JSHash.cpp:11`), which stops at an embedded NUL. 4. Return lowercase hex (`%.2x`). |
| File hashes | `HashFile(wchar_t*, ALG_ID)` (`Hash.cpp:57`) | 1. `CryptAcquireContext(PROV_RSA_FULL, 0)`. This is **not** `CRYPT_VERIFYCONTEXT`, so it needs a default key container. 2. `_wfopen_s(..., L"r")` (**text mode**). 3. `fseek`/`ftell` to get the size. 4. `fread` into `new char[size]`. 5. Hash `size` bytes. 6. Return lowercase hex. |
| Algorithms | `md5`/`sha1`/`sha256`/`sha384`/`sha512` (`Hash.cpp:128-142`), `*_file` (`Hash.cpp:144-158`) | `CALG_MD5`, `CALG_SHA1`, `CALG_SHA_256`, `CALG_SHA_384`, `CALG_SHA_512` |
| JS wrappers | `JSHash.cpp` | `argc != 1` throws `"Invalid arguments"`. The argument is coerced with `JS_ValueToString` (`null` becomes `"null"`). On success the native returns the hex string: interned with `JS_InternString` for string hashes, `JS_NewStringCopyZ` for file hashes. **On failure (NULL or empty result) the rval is (unset).** |
| File path | `*_file` | `isValidPath(file)` must pass, otherwise the native throws `"Invalid file path!"`. The hashed file is `<szScriptPath>\file` (`JSHash.cpp:76-81`). |

Bugs in the shared code:

- **SHA-2 with `PROV_RSA_FULL`.** Per Microsoft's CryptoAPI documentation, `CALG_SHA_256/384/512` need a `PROV_RSA_AES` provider; the `PROV_RSA_FULL` providers don't implement them. `sha256`, `sha384` and `sha512` (and their `_file` variants) are then expected to fail in `CryptCreateHash` and return (unset). This is unverified at runtime.
- **Text-mode `fread`.** It translates CRLF to LF (and stops at `0x1A`), so fewer bytes are read than `ftell` reported. `ferror` is false, so the code proceeds and hashes `size` bytes, including the **uninitialised tail** of the buffer (`Hash.cpp:72-90`). File hashes of CRLF files are therefore wrong and non-deterministic. LF-only files hash correctly.
- **Leak on `fopen` failure.** The hash and provider handles are leaked (`Hash.cpp:73-74`).
- **Key container.** `HashFile`'s `CryptAcquireContext(..., 0)` fails (and the hash is (unset)) when the user has no default key container.

### `md5(str)`

Returns the MD5 of the UTF-8 encoding of `String(str)` as lowercase hex.

- **Native:** `my_md5` at `JSHash.cpp:7`; registered at `JSGlobalFuncs.h:76` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** exactly one argument (`JSHash.cpp:8-9`), coerced to a string.
- **Returns:** a 32-character hex string, or (unset) on CryptoAPI failure.
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. CryptoAPI calls.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** the input is truncated at an embedded `\0`. The result string is interned.

### `sha1(str)`

As `md5`, with `CALG_SHA1`, giving 40 hex characters.

- **Native:** `my_sha1` at `JSHash.cpp:20`; registered at `JSGlobalFuncs.h:76` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals / Quirks:** as `md5`.

### `sha256(str)`

As `md5`, with `CALG_SHA_256`, giving 64 hex characters **if the provider supports it**.

- **Native:** `my_sha256` at `JSHash.cpp:33`; registered at `JSGlobalFuncs.h:76` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5`.
- **Quirks / bugs:** likely always (unset) because of `PROV_RSA_FULL`.

### `sha384(str)`

As `md5`, with `CALG_SHA_384`, giving 96 hex characters.

- **Native:** `my_sha384` at `JSHash.cpp:46`; registered at `JSGlobalFuncs.h:77` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5`.
- **Quirks / bugs:** as `sha256`.

### `sha512(str)`

As `md5`, with `CALG_SHA_512`, giving 128 hex characters.

- **Native:** `my_sha512` at `JSHash.cpp:59`; registered at `JSGlobalFuncs.h:77` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5`.
- **Quirks / bugs:** as `sha256`.

### `md5_file(path)`

Returns the MD5 of `<scripts>\path` as lowercase hex.

- **Native:** `my_md5_file` at `JSHash.cpp:72`; registered at `JSGlobalFuncs.h:77` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** exactly one argument, coerced to a string. An empty path, or one that fails `isValidPath`, throws `"Invalid file path!"` (`JSHash.cpp:77-78`).
- **Returns:** a hex string, or (unset) on any failure, including a missing file (no exception).
- **Preconditions:** either game state.
- **Threading & blocking:** caller's thread. Reads the whole file into memory.
- **Side effects:** file read.
- **Game internals:** none.
- **Quirks / bugs:** the text-mode/CRLF bug, the key-container dependency, and the leak on open failure.

### `sha1_file(path)`

As `md5_file`, with `CALG_SHA1`.

- **Native:** `my_sha1_file` at `JSHash.cpp:90`; registered at `JSGlobalFuncs.h:78` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals / Quirks:** as `md5_file`.

### `sha256_file(path)`

As `md5_file`, with `CALG_SHA_256`.

- **Native:** `my_sha256_file` at `JSHash.cpp:108`; registered at `JSGlobalFuncs.h:78` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5_file`.
- **Quirks / bugs:** as `md5_file`, plus the `PROV_RSA_FULL` SHA-2 issue.

### `sha384_file(path)`

As `md5_file`, with `CALG_SHA_384`.

- **Native:** `my_sha384_file` at `JSHash.cpp:126`; registered at `JSGlobalFuncs.h:78` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5_file`.
- **Quirks / bugs:** as `sha256_file`.

### `sha512_file(path)`

As `md5_file`, with `CALG_SHA_512`.

- **Native:** `my_sha512_file` at `JSHash.cpp:144`; registered at `JSGlobalFuncs.h:79` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads / Returns / Preconditions / Threading / Side effects / Game internals:** as `md5_file`.
- **Quirks / bugs:** as `sha256_file`.

---

## Facts that constrain a replacement API

These are facts collected from the entries above. The design synthesis is in [../rpc-considerations.md](../rpc-considerations.md).

- **Execution model.**
  - Each script is a separate OS thread with a private JS runtime (`Script.cpp:108`, `Script.cpp:120`).
  - Asynchronous work (events, timers, `scriptmsg`) only runs on that thread: inside `delay()` or `setSkill`, or at an operation-callback interrupt (`JSCore.cpp:145-151`, `ScriptEngine.cpp:316-322`).
  - A `main` that returns ends all of the script's event handling.
- **Game-thread blocking.** Registering a listener for a blocking event makes the **game thread** wait on the script: up to 500 ms for packets and chat blockers, 1000 ms for key blockers (`Events.cpp:189-201`, `Events.cpp:308-318`, `Events.cpp:55-67`). `clearEvent` doesn't undo this (`Script.cpp:401-410`).
- **No serialisation with the game.** `sendPacket`, `getPacket` and `loadMpq` call game code from script threads without the game-loop lock.
- **Global, unauthenticated namespaces.** Timer ids are process-wide (`ScriptEngine.cpp:799`). `stop()` with no argument stops every non-console script. `sendCopyData` to a D2BS window with mode `0x1337` executes arbitrary console JS there (`D2Handlers.cpp:184-189`).
- **Cross-script data.** Data only crosses scripts by structured clone (`JSCore.cpp:192-196`, `Events.cpp:157-160`). There is no shared state, no reply channel and no delivery acknowledgement.
- **Existing inbound IPC.** `WM_COPYDATA` is handled on the game thread and always answers `1` (`D2Handlers.cpp:179-200`). The DDE server is effectively broken: it refuses requests (`CBF_FAIL_REQUESTS`, `dde.cpp:36`), and its poke/execute handlers act on an empty string (`dde.cpp:10-11`). The outgoing `sendDDE` can only issue requests (mode bug, `JSCore.cpp:425-426`).
- **One shared rendezvous event.** Every blocking producer waits on the same manual-reset `Vars.eventSignal` (`Helpers.cpp:155`, `Events.cpp:63-66`, `Events.cpp:197-200`, `Events.cpp:309-313`), so verdicts from concurrent or timed-out events can be mismatched.
- **Memory-safety defects reachable from script arguments.** These include:
  - `sendPacket`/`getPacket` size fields (heap overflow);
  - `sendCopyData`/`sendDDE` non-string arguments (`JS_free` of string literals);
  - `copy`/`load`/`include`/`isIncluded`/`loadMpq` with non-string arguments;
  - the timer-list critical-section imbalance (`ScriptEngine.cpp:835`).

---

## Legacy-doc discrepancies

| Function | Legacy docs | Code |
|---|---|---|
| `load` | `doc/globalFuncs.h:783-793`: returns the new `D2BSScript` or null. `resources/api.html:1243`: returns bool. | Always `null` (`JSCore.cpp:203`, `JSCore.cpp:207`). Asynchronous. Stops an already-loaded instance of the same file. |
| `stop` | `resources/api.html:1455`: "stops the current script, if stopAll is true then it stops all". `doc/globalFuncs.h:822-830`: "conditionally stop current script". | `stop(1)`/`stop(true)` stops **only the caller**. Every other call stops **all non-console scripts**, the caller included (`JSCore.cpp:238-244`). |
| `delay` | `doc/globalFuncs.h:772-781`: suspend/resume the context in 50 ms slices. | Alertable `WaitForSingleObjectEx` loop that services events and GCs (`JSCore.cpp:138-161`). |
| `version` | `resources/api.html:1464`: prints, and also returns if `returnAsWell`. | No args: returns the string without printing. Any arg: prints and returns `true`. |
| `js_strict` | `resources/api.html:1237`: defaults to disabled. | Enabled by default (`Script.cpp:131`). |
| `getThreadPriority` | `doc/globalFuncs.h:218`, `resources/api.html:1161`: returns the thread priority. | Returns `GetCurrentThread()` cast to int, always -2 (`JSCore.cpp:276`). |
| `scriptBroadcast` | `doc/globalFuncs.h:1086`: to all *other* scripts. `resources/api.html:1415`: "as-is". | Includes the sender. Values are deep-copied by structured clone. Paused scripts are skipped. |
| `sendDDE` | `doc/globalFuncs.h:894-915`: 4 args; modes 1/2 send `""`. `resources/api.html:1421`: 5 args, modes 0/1/2. | 5 args read. Mode is taken from **arg 1**, so effectively always 0. Modes 1/2 would send `data` (arg 4). |
| `sendCopyData` | `resources/api.html:1418`: returns false if the window isn't found, else true/false. | Returns the integer LRESULT. The HWND form is in the 2nd slot (`doc/globalFuncs.h:892` calls the 2nd argument "dummy"; it actually selects the name/HWND). |
| `sendPacket` / `getPacket` | `doc/globalFuncs.h:1826`, `doc/globalFuncs.h:1838`: "Maximum packet length is 20"; pairs only. | No length limit (heap overflow possible). An ArrayBuffer form also exists. Requires `EnableUnsupported`. |
| `getIP` | `doc/globalFuncs.h:1847`: `automation.whatismyip.com/n09230945.asp`. | `http://ipv4bot.whatismyipaddress.com` (`JSCore.cpp:666`). |
| `addEventListener` event names | `doc/globalFuncs.h:943-945`: `keyupblock`, `keydownblock`. | The producer fires `keyupblocker`/`keydownblocker` (`Events.cpp:55`). `ExecScriptEvent` only handles `keydownblocker` (`ScriptEngine.cpp:634`, `ScriptEngine.cpp:650`), so a `keyupblocker` listener is never called and the producer times out after 1000 ms (`Events.cpp:66`). See [events.md](events.md). |
| Undocumented | `setTimeout`, `setInterval`, `clearTimeout`, `clearInterval`, `stacktrace`, `handler`, `sendClick`, `sendKey`, `stringToEUC`, `utf8ToEuc` are absent from `doc/globalFuncs.h` and `api.html`. | Present (`JSGlobalFuncs.h:40-51`, `JSGlobalFuncs.h:70`). |
| Stale names | `api.html` lists `iniread`, `iniwrite`, `blockMinimize`, `getTextWidthHeight`, `profileExists`. | Not registered in `global_funcs`. |

---

## Open questions

1. **Argument slots past `argc`.** Does this SpiderMonkey build (mozilla-release ~22) pad a native's `vp` array with `undefined` up to the declared `nargs`? If not, every "argc unchecked" read reads stale interpreter or JIT stack slots. The headers only document `CallArgs::operator[]` asserting `i < argc` (`dependencies/include/js/CallArgs.h:239`). This needs a runtime test, or a check of `js::Invoke`/`CallJSNative` in the matching engine source.
2. **Unset return values.** What do natives that return `JS_TRUE` without `JS_SET_RVAL` actually return to JS? The convention suggests the callee function object (`dependencies/include/js/CallArgs.h:134-142`, `dependencies/include/js/CallArgs.h:317`). Unverified.
3. **`JS_ReportError` followed by `return JS_TRUE`** in `setTimeout`, `setInterval` and `clearInterval` (`JSCore.cpp:81-82`, `JSCore.cpp:101-102`, `JSCore.cpp:119-120`). Is the pending exception thrown later, reported, or silently lost in this build?
4. **Compile failure of a `load()`ed file.** `Script::Run` rethrows `std::exception("Couldn't compile the script")` (`Script.cpp:157-171`), and nothing above it catches: `ScriptThread` at `Script.cpp:473` has none, and the Release config sets `<ExceptionHandling>false</ExceptionHandling>` (`D2BS.vcxproj:157`). Does this reach `ExceptionHandler` (`Helpers.cpp:396`, which returns `EXCEPTION_EXECUTE_HANDLER`) and terminate the process, or is it handled somewhere not visible in source?
5. **Structured-clone failures.** What happens when `JSAutoStructuredCloneBuffer::write` fails for a non-cloneable value in `load`/`scriptBroadcast`? Does the sender get an exception (the natives still return `JS_TRUE`), and what does the recipient's `read` of the empty buffer do (`Script.cpp:185`, `ScriptEngine.cpp:715`)?
6. **`getPacket` routing.** Does `D2NET_ReceivePacket` (RVA `0x12AEB0`) reach D2BS's `GamePacketReceived_Intercept` call site (D2Client RVA `0x5F802`, `Patch.h:11`)? That decides whether injected packets fire `gamepacket` listeners and the `0xAE` terminate check. Needs disassembly (see [../ghidra/README.md](../ghidra/README.md)).
7. **`sendPacket` hook coverage.** Is the `GamePacketSent_Interception` patch at RVA `0x12AE5A` reached on every `D2NET_SendPacket` call, or only on some branch? It is 10 bytes into the function, and an early exit before `+0xA` is possible. Also, what does `arg1 = 1` select?
8. **`D2WIN_InitMPQ` path resolution.** Which base directory does `D2WIN_InitMPQ` (RVA `0x117332`) resolve the relative path from `loadMpq` against: the process's current directory, the game directory or the MPQ search path? And what do the arguments `0, 0, 3000` mean (`Core.cpp:182`)?
9. **SHA-2 via CryptoAPI.** Do `sha256`/`sha384`/`sha512` really fail with the `PROV_RSA_FULL` provider on the supported Windows versions? Does `HashFile`'s non-`VERIFYCONTEXT` acquire fail on accounts without a default key container?
10. **Keyboard and mouse hooks for posted messages.** Do the posted `WM_KEYDOWN`/`WM_LBUTTONDOWN` messages from `sendKey`/`sendClick` reach D2BS's `WH_KEYBOARD`/`WH_MOUSE` thread hooks (`Helpers.cpp:185-187`), and so fire `keydown`/`mouseclick` events? What does `MOUSEHOOKSTRUCT.pt` hold for a posted message? Does D2's own input handling use the posted `lParam` coordinates?
11. **`getIP` endpoint.** Is `ipv4bot.whatismyipaddress.com` still reachable? This can't be determined from source.
12. **`copy` with a NULL clipboard owner.** Does `SetClipboardData` succeed after `OpenClipboard(NULL)` + `EmptyClipboard` (`JSCore.cpp:347-349`) on the target Windows versions, given Microsoft documents that it fails?
13. **Periodic timer APCs.** When a `setInterval` timer expires several times while its thread isn't alertable, does Windows queue one completion APC per expiry or only one in total? This decides how many times the same `Event` is pushed (`ScriptEngine.cpp:837-839`).

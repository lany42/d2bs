# Utility classes: `File`, `FileTools`, `Folder`, `SQLite`, `DBStatement`, `Socket`, `Sandbox`, `D2BSScript`

Scope: every JS-visible member of the non-game "utility" classes registered in `global_classes` (`JSGlobalClasses.cpp:143-168`), plus the globals that create their instances (`dopen`, `getScript`, `getScripts`) or belong to them (`sqlite_version`, `sqlite_memusage`), and the path-security layer they share (`File.cpp`). Sources: `File.cpp/.h`, `JSFile.cpp/.h`, `JSFileTools.cpp/.h`, `JSDirectory.cpp/.h`, `JSSQLite.cpp/.h`, `JSSocket.cpp/.h`, `JSSandbox.cpp/.h`, `JSScript.cpp/.h`, with `Script.cpp`, `ScriptEngine.cpp` and `js32.*` for the machinery they call. None of these classes touch Diablo II memory; what matters for an RPC replacement is blocking behaviour on the script thread, handle ownership, cross-thread use of `Script*`, encodings, and how the script-folder sandbox works. Engine-level detail (runtimes, rooting, the event queue) lives in [`../spidermonkey/embedding.md`](../spidermonkey/embedding.md) and [`events.md`](events.md). It is linked here, not repeated.

## Contents

1. [Conventions](#conventions)
2. [Path security layer (`File.cpp`)](#path-security-layer-filecpp)
3. [File](#file)
4. [FileTools](#filetools)
5. [Folder](#folder) (+ `dopen`)
6. [SQLite](#sqlite) (+ `sqlite_version`, `sqlite_memusage`)
7. [DBStatement](#dbstatement)
8. [Socket](#socket)
9. [Sandbox](#sandbox)
10. [D2BSScript](#d2bsscript) (+ `getScript`, `getScripts`)
11. [Handle ownership and lifetime summary](#handle-ownership-and-lifetime-summary)
12. [Facts relevant to an RPC replacement](#facts-relevant-to-an-rpc-replacement)
13. [Legacy-doc discrepancies](#legacy-doc-discrepancies)
14. [Defects and quirks (summary)](#defects-and-quirks-summary)
15. [Open questions](#open-questions)

---

## Conventions

The shared conventions in [globals-core.md, "Conventions shared by all entries"](globals-core.md#conventions-shared-by-all-entries) apply here too: registration flags, arguments read past `argc`, the meaning of **(unset)** return values, `THROW_ERROR`/`THROW_WARNING`, and string helpers. What follows is specific to classes.

### Class registration

| JS class name | `JSClass` (flags, finalizer, ctor) | `global_classes` entry | Instances come from |
|---|---|---|---|
| `File` | `file_class`, `JSCLASS_HAS_PRIVATE`, `file_finalize`, `file_ctor` (`JSGlobalClasses.cpp:84-86`) | `JSGlobalClasses.cpp:154` (+ static `file_s_methods`) | `File.open` |
| `FileTools` | `filetools_class`, flags `NULL` (no private), no finalizer, `filetools_ctor` (`JSGlobalClasses.cpp:80-82`) | `JSGlobalClasses.cpp:156` (statics only) | none (static-only) |
| `Folder` | `folder_class`, `JSCLASS_HAS_PRIVATE`, `dir_finalize`, `dir_ctor` (`JSGlobalClasses.cpp:96-98`) | `JSGlobalClasses.cpp:149` | `dopen`, `Folder.prototype.create` |
| `SQLite` | `sqlite_db`, `JSCLASS_HAS_PRIVATE`, `sqlite_finalize`, `sqlite_ctor` (`JSGlobalClasses.cpp:32-34`) | `JSGlobalClasses.cpp:157` | `new SQLite(...)` / `SQLite(...)` |
| `DBStatement` | `sqlite_stmt`, `JSCLASS_HAS_PRIVATE`, `sqlite_stmt_finalize`, `sqlite_stmt_ctor` (`JSGlobalClasses.cpp:36-38`) | `JSGlobalClasses.cpp:158` | `SQLite.prototype.query`, `SQLite.prototype.statements` |
| `Socket` | `socket_class`, `JSCLASS_HAS_PRIVATE`, `socket_finalize`, `socket_ctor` (`JSGlobalClasses.cpp:88-90`) | `JSGlobalClasses.cpp:155` (+ static `socket_s_methods`) | `Socket.open` |
| `Sandbox` | `sandbox_class`, `JSCLASS_HAS_PRIVATE`, add/del/get/set hooks `sandbox_*Property`, `sandbox_finalize`, `sandbox_ctor` (`JSGlobalClasses.cpp:64-66`) | `JSGlobalClasses.cpp:159` | `new Sandbox()` (crashes, [Sandbox](#sandbox)) |
| `D2BSScript` | `script_class`, `JSCLASS_HAS_PRIVATE`, **no finalizer** (`NULL`), `script_ctor` (`JSGlobalClasses.cpp:40-42`) | `JSGlobalClasses.cpp:160` | `getScript`, `getScripts` |

Mechanics:

- `contextCallback` loops over `global_classes` (`ScriptEngine.cpp:358-359`) and calls `ScriptEngine::InitClass` (`ScriptEngine.cpp:230-234`), which runs `JS_InitClass(cx, global, NULL, classp, classp->construct, 0, props, methods, s_props, s_methods)`. The constructor is the `JSClass`'s `construct` slot, filled by the `JSCLASS_SPEC` macro (`js32.h:163-164`). `nargs` is always `0`. The `ctor`/`argc` fields of the `JSClassSpec` row are ignored. Instance properties and methods therefore exist on **`X.prototype`**, and statics on the constructor.
- Every instance except a `Sandbox` is made by `BuildObject` (`js32.cpp:8-28`). It calls `JS_NewObject(cx, classp, NULL, NULL)` (so the engine picks the class prototype), then defines **the same methods and properties again as own properties of the instance** (`js32.cpp:18-21`), then calls `JS_SetPrivate`. `sandbox_ctor` calls `JS_NewObject` + `JS_DefineFunctions` itself instead (`JSSandbox.cpp:29-35`). `dopen`, `Folder.prototype.create` and `getScripts` don't check `BuildObject`'s result, so a failure there yields `null` instead of an exception (`JSDirectory.cpp:60-61`, `:187-188`, `JSScript.cpp:198-200`).
- `EMPTY_CTOR` (`js32.h:136-139`) throws `"Invalid Operation"`. `File`, `FileTools`, `Folder`, `DBStatement`, `Socket` and `D2BSScript` use it, so `new File()` and the rest always throw.
- Prototype objects have a NULL private. A property getter that runs against a prototype (e.g. `JSON.stringify(SQLite.prototype)`) behaves per class: `File` throws `"Couldn't get file object"` (`JSFile.cpp:128`); `SQLite` and `DBStatement` dereference NULL (`JSSQLite.cpp:244-250`, `:559-571`); `Folder` returns `JS_FALSE` with no exception, which aborts the script uncatchably (`JSDirectory.cpp:214-215`); `D2BSScript` and `Socket` return `undefined` (`JSScript.cpp:22-23`, `JSSocket.cpp:29`). Methods called with a foreign `this` follow the same pattern. The `JS_GetInstancePrivate(..., NULL)` calls never report an error, and most methods do not NULL-check. `Folder` is worse: its methods and getter use the js32 wrapper `JS_GetPrivate(cx, obj)` (`js32.cpp:65-67`), which does **no class check** (`JSDirectory.cpp:80`, `:128`, `:171`, `:194`, `:212`). Calling a `Folder` method on its prototype dereferences NULL, and calling one with a foreign `this` (e.g. `Folder.prototype.remove.call(someFile)`) reinterprets that object's private struct as `DirData`.
- All method tables use `JS_FS`/`JS_FN` with `FUNCTION_FLAGS` = `JSFUN_STUB_GSOPS` (`js32.h:134`). The "declared arity" in each entry is only `Function.length`.
- Properties use tinyid specs: getter/setter `JSOP_WRAPPER(...)`, flags `JSPROP_PERMANENT_VAR` = READONLY|ENUMERATE|PERMANENT or `JSPROP_STATIC_VAR` = ENUMERATE|PERMANENT (`js32.h:100-101`). Writes to read-only properties don't throw. Strict mode is not enabled at the language level (`JSOPTION_STRICT`, `Script.cpp:131`, only adds warnings). Numeric tinyids are listed in each properties table, since a replacement that keeps the switch-based getters needs them.

### Threading model (all classes)

- Every native runs on the **calling script's own thread**, inside that script's single-threaded `JSRuntime` (`Script.cpp:120-125`). See [embedding.md §7.4](../spidermonkey/embedding.md#74-requests-and-the-single-thread-runtime-rule).
- No native on this page takes the game lock (`AutoCriticalRoom`) or reads game state. A grep of the eight source files finds only `Vars.cFileSection` (`JSFileTools.cpp:192`, `:221`), `Vars.cEventSection` (`JSScript.cpp:124`) and the script-list lock (`ScriptEngine::LockScriptList`, `JSScript.cpp:54`, `:113`, `:170`, `:195`). Indirectly, `getScript` takes the list lock through `ForEachScript` (`ScriptEngine.cpp:210`), and `D2BSScript.stop()`/`join()` take the target's `Script::lock` (`Script.cpp:255`, `:225`).
- A native that blocks (disk, `connect`, `recv`, `WaitForSingleObject`) freezes its script completely. Queued events (including `scriptmsg`) are only drained in `delay()` and in the operation callback (`JSCore.cpp:140-150`, `ScriptEngine.cpp:315-323`). `Script::Stop` cannot interrupt native code either: it sets `isAborted`, triggers the operation callback, and waits at most 500 ms for `hasActiveCX` to drop (`Script.cpp:251-280`). The script ends only when control returns to the interpreter.
- Finalizers run on the owning script thread, during GC (`JS_GC` in `delay()` once the heap has grown 0.5 MiB, `JSCore.cpp:152-156`; `JS_MaybeGC` while paused, `ScriptEngine.cpp:310`; engine-scheduled GC) and during `JS_DestroyRuntime` in `~Script` (`Script.cpp:53-55`). GC timing is unpredictable, so **relying on finalizers to close handles leaves them open indefinitely**.

### Text encodings used on this page

| Data | Conversion | Source |
|---|---|---|
| Every path / file name / DB name | JS UTF-16 (`JS_GetStringCharsZ`) passed straight to wide APIs (`_wfopen_s`, `_wremove`, `_wrename`, `_waccess`, `_wmkdir`, `_wrmdir`, `_wchdir`, `_wfindfirst`, `GetFullPathNameW`, `sqlite3_open16`). Full Unicode, no lossy step. | e.g. `JSFile.cpp:159`, `File.cpp:199`, `JSSQLite.cpp:107` |
| Bytes read from files, SQLite TEXT, socket data | `AnsiToUnicode(s)`. Despite the name, the default code page is **`CP_UTF8`** (`Helpers.h:9`, `Helpers.cpp:16-22`). `MultiByteToWideChar` is called with length `-1`, so decoding **stops at the first NUL byte**. It also uses flags `0`, so invalid sequences get the API's default replacement. | `JSFile.cpp:347`, `:379`, `:415`, `:474`; `JSFileTools.cpp:180`; `JSSQLite.cpp:345`, `:403`, `:430`, `:565`; `JSSocket.cpp:161` |
| UTF-8 BOM | `EF BB BF` is skipped only if the read **started at file offset 0** (File methods) or always (`FileTools.readText`). | `JSFile.cpp:344`, `:375`, `:411`, `:471`; `JSFileTools.cpp:174` |
| Strings written to files, SQL text, bound strings, socket sends | `JS_EncodeStringToUTF8` (UTF-8, no terminator written) | `File.cpp:67`, `JSSQLite.cpp:138`, `:158`, `:176`, `:458`, `:472`; `JSSocket.cpp:135` |
| Names passed to `char*` JSAPI calls | `getObject` column names (`sqlite3_column_name`, UTF-8) and the `Sandbox` property hooks (`JS_EncodeStringToUTF8`) go to name-based `JS_SetProperty`/`JS_DefineProperty`/`JS_LookupProperty`/… calls. Those inflate each byte to one UTF-16 unit ([globals-core.md strings table](globals-core.md#strings-and-encodings)), so non-ASCII names are mangled. | `JSSQLite.cpp:331-336`, `JSSandbox.cpp:69-76`, `:124-126` |
| Socket host names | UTF-8 (`JSSocket.cpp:78`), matched against `Vars.szHosts`, which is UTF-8 too (`Helpers.cpp:138-139`), then passed to the ANSI-code-page API `gethostbyname` (`JSSocket.cpp:97`) | |
| Text-mode CRT translation | Files opened with `t` (or with no `t`/`b`, which defaults to text) translate `\r\n`↔`\n`. On input, Ctrl-Z (`0x1A`) is treated as end of file (MSVC text-mode semantics). | `JSFile.cpp:193`, `JSFileTools.cpp:90-91`, `:145`, `:195`, `:224` |
| Error messages | `JS_ReportError` takes narrow `printf`-style formats. A wide string passed to `%s` shows only its first character (`JSDirectory.cpp:183`); see Open questions for `%ls` (`File.cpp:202`). | |

---

## Path security layer (`File.cpp`)

The **script root** is `Vars.szScriptPath` (`D2BS.h:83`), built as `<D2BS dir><ScriptPath>` with `ScriptPath` defaulting to `scripts` (`Helpers.cpp:114`, `:133`). A profile switch rewrites it at runtime (`Helpers.cpp:94`; see [architecture.md §5](../architecture.md#5-configuration-d2bsini-and-the-command-line)). It is not normalised or cached: every check resolves it again, so a profile switch moves the sandbox for all later calls, including `File.prototype.reopen` on files that are already open.

### C helper `getPathRelScript` (`File.cpp:220`)

Signature: `wchar_t* getPathRelScript(const wchar_t* filename, int bufLen, wchar_t* fullPath)`.

1. Builds `relPath = szScriptPath + L"\\" + filename` in an `_alloca` buffer sized to the inputs (`File.cpp:226-232`). The length of `filename` is unbounded, so a huge JS string can overflow the stack.
2. `GetFullPathNameW(relPath, bufLen, fullPath, NULL)` collapses `.`/`..` and duplicate separators and converts `/` to `\` (`File.cpp:235`). Its return value is **not checked**: if the result is longer than `bufLen` (callers pass `_MAX_PATH + _MAX_FNAME` = 516 wchar), `fullPath` is left uninitialised.
3. `GetFullPathNameW(szScriptPath)` → `fullScriptPath`, `scrPathLen` (`File.cpp:238`).
4. Accepts only if `wcsncmp(fullPath, fullScriptPath, scrPathLen) == 0` **and** (`fullScriptPath` ends in `\` or `fullPath[scrPathLen] == '\\'`) (`File.cpp:243`). Otherwise it sets `fullPath[0] = 0` and returns `NULL`.

Consequences:

- Traversal is judged on the **resolved** path. `..\x` is accepted as long as the result stays inside the root, so `sub\..\a.txt` is fine and `..\d2bs.ini` is rejected. A sibling directory sharing the prefix (`scripts2\`) is rejected by the separator test.
- The comparison is **case-sensitive** (`wcsncmp`). That can only cause false rejections (e.g. `..\Scripts\x` when the root is `scripts`), never escapes.
- A leading `/` or `\` in `filename` is harmless: the legacy examples use `'/logs/mylog.txt'`. Absolute paths (`C:\...`) are glued under the root and then fail to open. NTFS stream syntax (`a.txt:stream`) passes this function.
- Junctions, symlinks and other reparse points inside the root are followed by the OS. Nothing checks for them.
- The root itself is accepted only when it resolves with a trailing separator (empty name). `"."` resolves to the root without one and is rejected.

### C helper `fileOpenRelScript` (`File.cpp:188`)

Signature: `FILE* fileOpenRelScript(const wchar_t* filename, const wchar_t* mode, JSContext* cx)`.

`getPathRelScript`, and on failure `JS_ReportError("Invalid file name")` → `NULL` (`File.cpp:193-196`). Otherwise `_wfopen_s(&f, fullPath, mode)`, and on failure `JS_ReportError("Couldn't open file %ls: %s", filename, strerror-text)` → `NULL` (`File.cpp:199-204`). Callers return `JS_FALSE` on `NULL`, so the reported error becomes a catchable exception. The `%s` part is the CRT's `_strerror_s(…, NULL)` text for the current `errno`, which ends in a newline.

Sharing: MSVC documents `_wfopen_s` files as **not shareable**. The CRT opens them in `_SH_SECURE` mode, which shares read access only when the open itself is read-only (CRT behaviour, not visible in this repo). As a result:

- A read-mode handle (`r`, `rt`, `rb`) lets other readers open the file but no writers.
- A write or append handle (`w`, `w+t`, `a+`, …) blocks every other open.

Any open handle can make other opens of that file, from any script or process, fail with `"Couldn't open file …"`. That includes a handle held by an unreachable `File` that hasn't been GC'd yet, and one leaked by [`FileTools.copy`](#filetoolscopysrcpath-dstpath-overwrite).

### C helper `isValidPath` (`File.cpp:258`)

Signature: `bool isValidPath(const wchar_t* name)`.

`getPathRelScript(name)` must succeed **and** `name` must contain no literal `..\` or `../` and none of `"` `:` `?` `*` `<` `>` `|` (`File.cpp:262-265`). This is strictly stronger than [getPathRelScript](#c-helper-getpathrelscript-filecpp220): no drive letters, no NTFS streams, and no `..` sequences even when they would stay inside the root. A trailing `..` with no separator after it (`a\..`) still passes the literal test. Callers then **rebuild the path themselves** with `swprintf(L"%s\\%s", szScriptPath, name)`; the normalised path is thrown away.

### Which API uses which check

| API | Check | Notes |
|---|---|---|
| `File.open`, `File.prototype.reopen` | [`fileOpenRelScript`](#c-helper-fileopenrelscript-filecpp188) | `JSFile.cpp:194`, `:260` |
| `FileTools.remove`, `.rename`, `.exists` | [`getPathRelScript`](#c-helper-getpathrelscript-filecpp220) | `JSFileTools.cpp:41`, `:60-64`, `:133` |
| `FileTools.copy` | `getPathRelScript(new)` + `fileOpenRelScript` for both | `JSFileTools.cpp:84`, `:90-91` |
| `FileTools.readText`, `.writeText`, `.appendText` | `fileOpenRelScript` | `JSFileTools.cpp:145`, `:195`, `:224` |
| `dopen`, `Folder.prototype.create` | [`isValidPath`](#c-helper-isvalidpath-filecpp258) | `JSDirectory.cpp:44`, `:177` |
| `Folder.prototype.getFiles/getFolders` pattern | **none**: the pattern is passed to `_wfindfirst` after `_wchdir` into the folder, so `"..\\..\\*"` lists names outside the root | `JSDirectory.cpp:81`, `:102`, `:129`, `:150` |
| `Folder.prototype.remove` | none at call time (the name was validated when the `Folder` was made) | `JSDirectory.cpp:197` |
| `new SQLite(path)` | `isValidPath`, **skipped when `path[0] == ':'`**; such names go verbatim to `sqlite3_open16`, relative to the process CWD | `JSSQLite.cpp:91-99` |
| `Sandbox.prototype.include/isIncluded` | none (`include` is dead code, [Sandbox](#sandbox)) | `JSSandbox.cpp:195`, `:221` |
| Out of scope, same layer | `md5_file`… (`JSHash.cpp:77`…), `loadMpq` (`JSCore.cpp:562`), `Image` hooks (`JSScreenHook.cpp:631`) use `isValidPath`; `load`/`include`/`isIncluded` use none ([globals-core.md#paths](globals-core.md#paths)) | |

### C helper `readLine` (`File.cpp:31`)

Signature: `char* readLine(FILE* fptr, bool locking)`.

Returns `NULL` if `feof` is **already** set on entry. Otherwise it reads bytes with `fgetc`/`_fgetc_nolock` up to and including `\n`, **drops every `\r` and `\n`** (a `\r` in mid-line is removed, not treated as a terminator) and returns a `_strdup` copy (`File.cpp:31-47`). Embedded NULs truncate the line. EOF is noticed only after a read past the end, so a file ending in `\n` yields one extra empty line, and an empty file yields `""` once before `NULL`.

### C helper `writeValue` (`File.cpp:49`)

Signature: `bool writeValue(FILE* fptr, JSContext* cx, jsval value, bool isBinary, bool locking)`.

Dispatches on `JS_TypeOfValue`, which follows `typeof` (`dependencies/include/jspubtd.h:93`): `null` reports as `JSTYPE_OBJECT`, so the `JSTYPE_NULL` label at `File.cpp:58` does not catch it (see Open questions).

| JS value | Text mode (`isBinary=false`) | Binary mode | Returns | Source |
|---|---|---|---|---|
| `undefined` | **4 zero bytes** (an `int` 0), even in text mode | 4 zero bytes | `true` on success | `File.cpp:57-65` |
| string | UTF-8 bytes, no terminator. Length is `strlen`, so a string containing U+0000 is **silently cut at the first NUL** | same | compares `strlen(str)` **after `JS_free(str)`** (use-after-free); a NULL from `JS_EncodeStringToUTF8` (OOM) crashes in `strlen` | `File.cpp:66-75` |
| int-tagged number | decimal (`_itoa_s`) | locked: 4-byte LE `int32`. Unlocked: **writes 4 bytes of `dval` (0.0)** instead of `ival` (`File.cpp:92`), so the output is always `00 00 00 00` | `true` if fully written | `File.cpp:87-96`, `:112-125` |
| double-tagged number | `sprintf_s("%.16f")` into a 64-char buffer. **x ≥ ~1e46, or x ≤ ~-1e45 (the sign takes a byte), overflows it**, which triggers the CRT invalid-parameter handler and terminates the process (no custom handler is installed; only `SetUnhandledExceptionFilter`, `D2BS.cpp:93`) | 8-byte IEEE double | `true` if fully written | `File.cpp:78-86`, `:98-111` |
| boolean | `"true"` / `"false"` | 1 byte (`sizeof(bool)`) | `true` if fully written | `File.cpp:128-144` |
| `null`, objects, arrays, functions | nothing written | nothing written | `false` (array support is commented out, `File.cpp:146-170`) | `File.cpp:172` |

Whether a number is int- or double-tagged is an engine detail: integral results of arithmetic may be doubles, e.g. writing `3` might produce `3.0000000000000000`.

---

## File

- **JSClass:** `"File"`, `JSCLASS_HAS_PRIVATE`, finalizer `file_finalize` (`JSGlobalClasses.cpp:84-86`). Registered from `JSGlobalClasses.cpp:154` with `file_methods`, `file_props` and static `file_s_methods` (`JSFile.h:50-63`, `:98-111`). Mode constants `FILE_READ`=0, `FILE_WRITE`=1, `FILE_APPEND`=2 (`JSFile.h:66-69`) are defined as read-only globals in every context (`ScriptEngine.cpp:368-371`).
- **Constructor:** `new File()` throws `"Invalid Operation"` (`JSFile.cpp:39`). Instances come only from `File.open`.
- **Private data:** `FileData` (`JSFile.cpp:28-37`): `int mode` (0-2 = text read/write/append, 3-5 = binary), `wchar_t* path` (`_wcsdup` of the name **as passed**), `bool autoflush`, `bool locked`, `FILE* fptr` (NULL while closed), plus `lockLocation`/`line` in DEBUG builds. Owned by the wrapper. `file_finalize` (`JSFile.cpp:570-587`) frees `path`, unlocks the stream if `locked`, closes `fptr` if open, and deletes the struct.
- **Identity & lifetime:** each `File` owns one CRT stream. Closing does not detach the private, so a closed `File` can be reopened. There is no equality hook (`file_equality` is declared at `JSFile.h:11` but commented out at `JSFile.cpp:41-52`), so `==` is object identity. Nothing is shared between scripts.
- **Locking (`lockFile`):** `_lock_file(fptr)` at open/reopen (`JSFile.cpp:211-212`, `:266-267`), `_unlock_file` at close/finalize (`:238`, `:576`). This is the CRT's **in-process, per-`FILE*` recursive lock**, held by the opening script thread. It does not stop other scripts or processes from opening the file. Exclusivity against other openers comes from `_wfopen_s` sharing ([fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)), whatever `lockFile` is: a `FILE_READ` handle keeps writers out, and a `FILE_WRITE`/`FILE_APPEND` handle keeps everyone out. With `locked`, the code calls the locking CRT functions, otherwise the `_nolock` variants. Every access happens on the owning thread anyway.

### File properties

All are own properties of each instance (and of `File.prototype`), with getter `file_getProperty` (`JSFile.cpp:54`). Every row except `autoflush` is read-only. All return values below assume a private exists; otherwise the getter throws `"Couldn't get file object"` (`JSFile.cpp:128`).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `readable` | `FILE_READABLE` = 3 (`JSFile.h:98`) | boolean | R | any | `fptr && !feof && !ferror` (`JSFile.cpp:62-63`) | Ignores mode; `w+`/`a+` are readable. |
| `writeable` | `FILE_WRITEABLE` = 4 (`JSFile.h:99`) | boolean | R | any | `fptr && !ferror && mode%3 > FILE_READ` (`JSFile.cpp:65-66`) | Spelled `writeable`; legacy says `writable`. |
| `seekable` | `FILE_SEEKABLE` = 5 (`JSFile.h:100`) | boolean | R | any | `fptr && !ferror` (`JSFile.cpp:68-69`) | |
| `mode` | `FILE_MODE` = 6 (`JSFile.h:101`) | number | R | any | `mode % 3` (`JSFile.cpp:71-72`) | Compare with `FILE_READ/WRITE/APPEND`. |
| `binaryMode` | `FILE_BINARYMODE` = 12 (`JSFile.h:102`) | boolean | R | any | `mode > 2` (`JSFile.cpp:74-75`) | |
| `length` | `FILE_LENGTH` = 7 (`JSFile.h:103`) | number | R | open → size, closed → 0 | `_filelength(_fileno(fptr))` (`JSFile.cpp:77-82`) | On-disk size: unflushed buffered writes are not counted. |
| `path` | `FILE_PATH` = 8 (`JSFile.h:104`) | string | R | any | `fdata->path + 1` (`JSFile.cpp:84`) | **Drops the first character** of the name as passed. Correct only for names written with a leading `/` or `\` (`File.open("a.txt")` → `".txt"`). An empty name can't reach here (rejected at open). |
| `position` | `FILE_POSITION` = 9 (`JSFile.h:105`) | number | R | open → offset, closed → 0 | `ftell` / `_ftell_nolock` (`JSFile.cpp:86-94`) | Byte offset; text-mode `ftell` accounts for CRLF. |
| `eof` | `FILE_EOF` = 10 (`JSFile.h:106`) | boolean | R | open → `feof`, closed → `true` | `JSFile.cpp:95-100` | Becomes true only after a read hits the end. |
| `accessed` | `FILE_ACCESSED` = 13 (`JSFile.h:107`) | number | R | open → time, closed → 0 | `_fstat(...).st_atime` (`JSFile.cpp:104-110`) | Seconds since 1970-01-01 UTC, 32-bit `time_t` (`_USE_32BIT_TIME_T`, `JSFile.cpp:17`). Not a `Date`. |
| `created` | `FILE_CREATED` = 14 (`JSFile.h:108`) | number | R | as above | `st_ctime` (`JSFile.cpp:118-124`) | Windows `st_ctime` is creation time. |
| `modified` | `FILE_MODIFIED` = 15 (`JSFile.h:109`) | number | R | as above | `st_mtime` (`JSFile.cpp:111-117`) | |
| `autoflush` | `FILE_AUTOFLUSH` = 11 (`JSFile.h:110`) | boolean | R/W | any | `fdata->autoflush`; setter `file_setProperty` (`JSFile.cpp:133-148`) | Assigning a non-boolean is silently ignored (`:140`). |

### `File.open(path, mode[, binary[, autoflush[, lockFile]]])`

Opens a file under the script root and returns a new `File`.

- **Native:** `file_open` at `JSFile.cpp:150`; registered at `JSFile.h:63` (declared arity 2, `JSFUN_STUB_GSOPS`), as a static on the `File` constructor.
- **Arguments / overloads:** `argc < 2` → throws `"Not enough parameters, 2 or more expected"` (`:151-152`). `path` must be a string, else `"Parameter 1 not a string"` (`:153-154`). `mode` must be an **int-tagged** number, else `"Parameter 2 not a mode"` (`:155-156`), and must be 0, 1 or 2, else `"Invalid file mode"` (`:179-188`). `binary`, `autoflush` and `lockFile` count only if they are booleans; any other type silently means `false` (`:166-171`). An empty `path` throws `"Invalid file name"` (`:174-175`).
- **Mode table** (`JSFile.cpp:190-193`):

  | `mode` | text | binary | Effect |
  |---|---|---|---|
  | `FILE_READ` (0) | `rt` | `rb` | must exist |
  | `FILE_WRITE` (1) | `w+t` | `w+b` | **create/truncate**, read+write |
  | `FILE_APPEND` (2) | `a+t` | `a+b` | create, read anywhere, writes always append |
- **Returns:** a `File` object. On failure throws: [`fileOpenRelScript`](#c-helper-fileopenrelscript-filecpp188) messages, or `"Failed to define the file object"` if `BuildObject` fails (`:219-228`). The `"Couldn't allocate memory…"` branch (`:201-204`) can't fire, because `new` throws rather than returning NULL.
- **Preconditions:** either in or out of game; no game-state check.
- **Threading & blocking:** synchronous `_wfopen_s` on the script thread. No D2BS locks; `_lock_file` if `lockFile`.
- **Side effects:** creates or truncates the file on disk (modes 1/2), and holds an OS handle with `_SH_SECURE` sharing ([fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)) until `close()` or finalization.
- **Game internals:** none.
- **Quirks / bugs:** a `mode` computed as a double (e.g. `2/2`) may be double-tagged and get rejected. `path` is validated by [`getPathRelScript`](#c-helper-getpathrelscript-filecpp220) only, so `..` that stays inside the root and NTFS streams are allowed. The stored name is the raw argument, which matters for `reopen` and `path`.

### `File.prototype.close()`

Closes the stream and keeps the object for `reopen`.

- **Native:** `file_close` at `JSFile.cpp:233`; registered at `JSFile.h:50` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none read.
- **Returns:** `this`. Throws `"File is not open"` if already closed (`:248-249`). If `fclose` fails it throws `_strerror("Close failed")`, i.e. `"Close failed: <errno text>\n"` (`:243-246`). If `this` has no `FileData`, nothing happens and `this` is returned (`:235`, `:251`).
- **Preconditions:** either.
- **Threading & blocking:** flushes and closes on the script thread.
- **Side effects:** releases the CRT lock (`_unlock_file`, `:238`) and the OS handle. `fptr = NULL` (`:247`) is set only on success.
- **Game internals:** none.
- **Quirks / bugs:** if `fclose` fails, `fptr` keeps the dangling pointer (the CRT has already freed the stream), and the finalizer will `fclose` it again.

### `File.prototype.reopen()`

Reopens a closed file with the original name and mode.

- **Native:** `file_reopen` at `JSFile.cpp:255`; registered at `JSFile.h:51` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `this`. Throws `"File is not closed"` if open (`:273-274`), or the `fileOpenRelScript` errors (`:260-264`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous open.
- **Side effects:** **`FILE_WRITE` truncates again** (`w+`). The path is re-resolved against the *current* `szScriptPath`. The CRT lock is retaken if `lockFile` was set (`:266-267`).
- **Game internals:** none.
- **Quirks / bugs:** `autoflush` keeps its previous value.

### `File.prototype.read(count)`

Reads `count` bytes (text mode) or `count` 32-bit integers (binary mode).

- **Native:** `file_read` at `JSFile.cpp:279`; registered at `JSFile.h:52` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** the guard `argc > 0 && JSVAL_TO_INT(argv[0]) > 0 && JS_ValueToInt32(...)` (`:284`) applies `JSVAL_TO_INT` **before any type test**. Only an int-tagged positive number works reliably; double-tagged numbers and other types are misread (see [globals-core.md](globals-core.md#reading-arguments-past-argc)). Failure throws `"Invalid arguments"`.
- **Returns:**
  - *Binary* (`mode > 2`, `:287-312`): reads `count` × `sizeof(int)` = **4-byte little-endian signed ints**. `count == 1` → a number; otherwise an array of exactly `count` numbers. On a short read (EOF) the tail is **uninitialised heap memory**, because only `count+1` *bytes* of the `int[count+1]` buffer are zeroed (`:290`).
  - *Text* (`:313-351`): `fflush`es the stream first (`:326-329`), then reads up to `count` bytes (after CRT CRLF translation), skips a BOM if the read started at offset 0, decodes UTF-8, truncates at a NUL, and returns a string (`""` at EOF).
  - `ferror` after a short read → throws `"Read failed: …"` (`:297-300`, `:339-342`).
  - Closed file or missing private → **(unset)**, no error (`:281`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous `fread` on the script thread. `clearerr` first (`:282`).
- **Side effects:** advances the position.
- **Game internals:** none.
- **Quirks / bugs:** the legacy docs promise "bytes" in binary mode, but the code reads ints. A text-mode `count` can split a multi-byte UTF-8 sequence. The BOM test uses the number of bytes read (`size > 2`, `:344`). The buffer is `new int[count + 1]` / `new char[count + 1]` (`:289`, `:331`), so a huge `count` (up to 2³¹−1) makes `new` throw `std::bad_alloc` through the engine. Nothing on the script thread catches it (`Script.cpp:192-195`, `:473-484`), so the process dies.

### `File.prototype.readLine()`

Reads one line without its terminator.

- **Native:** `file_readLine` at `JSFile.cpp:356`; registered at `JSFile.h:53` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** a string (UTF-8 decoded, BOM skipped if the read started at offset 0, `:375`). At EOF (`feof` already set) it throws `_strerror("Read failed")` (`:371-373`). Closed file → **(unset)**.
- **Preconditions:** either.
- **Threading & blocking:** byte-at-a-time `fgetc` loop ([readLine](#c-helper-readline-filecpp31)).
- **Side effects:** advances the position.
- **Game internals:** none.
- **Quirks / bugs:** no binary-mode check, although the legacy docs say it throws in binary mode. Removes every `\r`. The line after a final `\n` is `""`, and only the call after that throws.

### `File.prototype.readAllLines()`

Reads the remaining lines into an array.

- **Native:** `file_readAllLines` at `JSFile.cpp:387`; registered at `JSFile.h:54` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** an array of strings from the current position to EOF (`:394-420`). A file ending in `\n` gets a **trailing `""`** element, and an empty file gives `[""]` ([readLine](#c-helper-readline-filecpp31)). Closed file → **(unset)**.
- **Preconditions:** either.
- **Threading & blocking:** synchronous; reads the whole remainder in one call.
- **Side effects:** position ends at EOF.
- **Game internals:** none.
- **Quirks / bugs:** no binary-mode check. The `THROW_ERROR` at `:408-409` can't fire (the loop already tests `feof`), and if it did it would skip `JS_EndRequest`.

### `File.prototype.readAll()`

Returns the entire file as one string, wherever the position was.

- **Native:** `file_readAll` at `JSFile.cpp:426`; registered at `JSFile.h:55` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** a string. Seeks to the end to get the size, seeks to the start, and reads everything (`:442-464`). The BOM is skipped **only if the position was 0 before the call** (`:433-440`, `:471`). Truncated at the first NUL. `ferror` → throws `"Read failed: …"`. Closed file → **(unset)**.
- **Preconditions:** either.
- **Threading & blocking:** synchronous; loads the whole file into memory.
- **Side effects:** position ends at EOF.
- **Game internals:** none.
- **Quirks / bugs:** binary mode also returns a decoded *string*, although `JSFile.h:43-44` says it returns an array.

### `File.prototype.write(...values)`

Writes each argument using [`writeValue`](#c-helper-writevalue-filecpp49).

- **Native:** `file_write` at `JSFile.cpp:483`; registered at `JSFile.h:56` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** any number of values, each handled as in the [writeValue](#c-helper-writevalue-filecpp49) table. Binary vs text follows the file's open mode (`mode > 2`).
- **Returns:** `this` in every case (`:496`). **Per-value failures are ignored** (`:486-487`), so nothing ever throws. Closed file → no-op, still returns `this`.
- **Preconditions:** either.
- **Threading & blocking:** synchronous `fwrite`; `fflush` afterwards if `autoflush` (`:489-494`).
- **Side effects:** disk writes. In `FILE_APPEND` mode, writes always go to the end.
- **Game internals:** none.
- **Quirks / bugs:** binary int writes on unlocked files write zeros (`File.cpp:92`). Large doubles in text mode kill the process (`File.cpp:103`). `null`, arrays and objects are silently dropped. C requires a flush or seek between a write and a following read, and a seek between a read and a following write. Text-mode `read()` flushes before reading (`:326-329`) and `readAll()` seeks before reading (`:442-456`), so read-after-write is fine for those two. `readLine`, `readAllLines` and binary `read()` do neither, and nothing seeks before `write()`. So in `w+`/`a+` a `write()` right after any read, or one of those three right after a `write()`, needs an explicit `seek`/`reset`/`end` (or `flush`, for write→read) in between; without one the behaviour is undefined.

### `File.prototype.seek(n[, isLines[, fromStart]])`

Moves the position by `n` bytes, or skips `n` lines.

- **Native:** `file_seek` at `JSFile.cpp:500`; registered at `JSFile.h:57` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `n` via `JS_ValueToInt32` (full coercion; `"Could not convert parameter 1"` on failure, `:506-507`). `isLines` and `fromStart` count only if boolean (`:508-511`). No arguments → throws `"Not enough parameters"` (`:527-528`).
- **Returns:** `this`. Throws `"Seek failed: …"` if `fseek` fails. Closed file → no-op, returns `this`.
- **Preconditions:** either.
- **Threading & blocking:** synchronous. Line mode reads and discards `n` lines.
- **Side effects:** `fromStart` → `rewind` (also clears EOF/error, `:513-514`). Byte mode: `SEEK_CUR` by `n` (`:516-520`). Line mode: `while (n--) free(readLine(...))` (`:524-525`).
- **Game internals:** none.
- **Quirks / bugs:** **files opened with `lockFile` seek twice.** `if (locked && fseek(...)) throw; else if (_fseek_nolock(...)) throw` falls through to the second seek when the first succeeds (`:517-519`), so `seek(n)` moves `2n`. A **negative `n` with `isLines`** loops about 2³² times (signed wrap), a long stall. In text mode MSVC only guarantees `fseek` with offset 0 or a value from `ftell`.

### `File.prototype.flush()`

Flushes the CRT buffer.

- **Native:** `file_flush` at `JSFile.cpp:534`; registered at `JSFile.h:58` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `this`; errors are ignored.
- **Preconditions:** either.
- **Threading & blocking:** synchronous `fflush`.
- **Side effects:** buffered data reaches the OS.
- **Game internals:** none.
- **Quirks / bugs:** none beyond the shared ones.

### `File.prototype.reset()`

Seeks to offset 0.

- **Native:** `file_reset` at `JSFile.cpp:546`; registered at `JSFile.h:59` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `this`; throws `"Seek failed: …"` on failure.
- **Preconditions:** either.
- **Threading & blocking:** synchronous.
- **Side effects:** position 0. Uses `fseek`, not `rewind`, so the error indicator is not cleared.
- **Game internals:** none.
- **Quirks / bugs:** the same double seek as `seek` when locked (`:549-551`); harmless here because the seek is absolute.

### `File.prototype.end()`

Seeks to the end of the file.

- **Native:** `file_end` at `JSFile.cpp:558`; registered at `JSFile.h:60` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `this`; throws `"Seek failed: …"` on failure.
- **Preconditions:** either.
- **Threading & blocking:** synchronous.
- **Side effects:** position = size. `eof` stays false until a read.
- **Game internals:** none.
- **Quirks / bugs:** double seek when locked (`:561-563`); harmless.

---

## FileTools

- **JSClass:** `"FileTools"`, flags `NULL` (no private slot), no finalizer (`JSGlobalClasses.cpp:80-82`). Registered from `JSGlobalClasses.cpp:156` with static methods only (`JSFileTools.h:32-39`).
- **Constructor:** `new FileTools()` throws `"Invalid Operation"` (`JSFileTools.cpp:32`). The class is only a namespace.
- **Private data:** none.
- **Identity & lifetime:** stateless. Each call opens and closes its own handles. `writeText`/`appendText` serialise against each other across **all scripts** through `Vars.cFileSection` (`D2BS.h:119`, initialised at `D2BS.cpp:123`). Nothing else takes that lock, including `readText` and `File`.
- **Properties:** none.

### `FileTools.remove(path)`

Deletes a file.

- **Native:** `filetools_remove` at `JSFileTools.cpp:34`; registered at `JSFileTools.h:32` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `path` must be a string, else `"You must supply a file name"` (`:35-36`). Outside the root → `"Invalid file name"` (`:41-42`).
- **Returns:** **(unset)** on every non-throwing path; the `_wremove` result is ignored (`:44-45`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous `_wremove`.
- **Side effects:** deletes the file. Directories can't be removed, and files held open (by any `File`, even an unreachable one) fail silently.
- **Game internals:** none.
- **Quirks / bugs:** api.html says it returns `bool`; nothing is returned.

### `FileTools.rename(oldPath, newPath)`

Renames or moves a file inside the root.

- **Native:** `filetools_rename` at `JSFileTools.cpp:48`; registered at `JSFileTools.h:33` (declared arity 2, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** both must be strings: `"You must supply an original file name"` / `"You must supply a new file name"` (`:49-52`). Validation messages: `"Invalid original file name"` / `"Invalid new file name"` (`:60-64`).
- **Returns:** **(unset)**; the `_wrename` result is ignored (`:66-67`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous.
- **Side effects:** fails silently if the target exists or the source is open. Works on directories too (CRT `_wrename` semantics).
- **Game internals:** none.
- **Quirks / bugs:** api.html promises `bool`.

### `FileTools.copy(srcPath, dstPath[, overwrite])`

Copies a file byte by byte **in text mode**.

- **Native:** `filetools_copy` at `JSFileTools.cpp:70`; registered at `JSFileTools.h:34` (declared arity 2, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** string checks as for `rename` (`:71-74`). `overwrite` counts only if boolean (`:81-82`). `dstPath` is checked with `getPathRelScript` (`"Invalid new file name"`, `:84-85`), then both are opened through `fileOpenRelScript` (`"r"` and `"w"`, `:90-91`).
- **Returns:** **(unset)** on success (`:121-124`) and on the `overwrite` early exit (`:87-88`). Throws on open or I/O errors (`"Read Error: …"`, `"Write Error: …"`, `:99-108`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous `fgetc`/`fputc` loop, one byte at a time, on the script thread.
- **Side effects:** creates or truncates `dstPath`.
- **Game internals:** none.
- **Quirks / bugs:**
  - **`overwrite` is inverted:** `overwrite === true` with an existing target returns *without copying* (`:87-88`), while the default (`false`) always overwrites.
  - **The destination is truncated even when the source can't be opened.** Both opens run before the NULL check (`:90-95`), so `copy("missing", "important")` empties `important`. The surviving `FILE*` has no owner and is **never closed**, so it holds its sharing lock ([fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)) until Game.exe exits. A leaked destination handle (write mode) blocks every later open of that file. A leaked source handle (read mode) blocks every later writer.
  - Text mode corrupts binary files (CRLF conversion; `0x1A` ends the input).
  - Copying a file onto itself: given `_wfopen_s`'s sharing, the `"w"` open of the already-open (read-mode) source fails with `"Couldn't open file …"` before anything is truncated, and the source handle leaks as above.
  - A mid-loop error throws without closing either file (`:99-108`), so both handles leak permanently, the error-cleanup block at `:111-119` is unreachable, and the partial target is never deleted.

### `FileTools.exists(path)`

Tests whether a path exists.

- **Native:** `filetools_exists` at `JSFileTools.cpp:127`; registered at `JSFileTools.h:35` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** non-string or outside the root → throws `"Invalid file name"` (`:128-134`).
- **Returns:** boolean `!(_waccess(path,0) != 0 && errno == ENOENT)` (`:136`): `true` for directories, and `true` when access fails for any reason other than `ENOENT`.
- **Preconditions:** either.
- **Threading & blocking:** synchronous.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** throws rather than returning `false` for out-of-root paths.

### `FileTools.readText(path)`

Reads a whole file as text.

- **Native:** `filetools_readText` at `JSFileTools.cpp:141`; registered at `JSFileTools.h:36` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** a string is required (`"You must supply a file name"`, `:142-143`). Open errors come from `fileOpenRelScript` (mode `"r"`, text, `:145-149`).
- **Returns:** a string: BOM skipped, UTF-8 decoded, truncated at the first NUL, CRLF→LF, cut at Ctrl-Z (`:155-182`). Throws `"Read failed: …"` if the error indicator is set.
- **Preconditions:** either.
- **Threading & blocking:** synchronous whole-file read. It does **not** take `cFileSection`, so it doesn't wait for a concurrent `writeText`/`appendText`. While that call holds its write handle, the `"r"` open fails with a sharing violation (`"Couldn't open file …"`, [fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)) instead.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** `ferror(fptr)` is evaluated **after `fclose(fptr)`** (`:165-168`), which is use-after-close.

### `FileTools.writeText(path, ...values)`

Truncates or creates a file and writes the values as text.

- **Native:** `filetools_writeText` at `JSFileTools.cpp:188`; registered at `JSFileTools.h:37` (declared arity 2, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `path` must be a string (`:189-190`). Values from index 1 go through `writeValue(fptr, cx, v, false, true)` ([writeValue](#c-helper-writevalue-filecpp49), text mode, `:204-206`). With no values, an empty file is created.
- **Returns:** `true` if every value was written, else `false` (`:213`). Open failure → throws (fileOpenRelScript).
- **Preconditions:** either.
- **Threading & blocking:** holds **`Vars.cFileSection`** (process-wide) across open, writes, flush and close (`:192`, `:211`), so it blocks every other script's `writeText`/`appendText` for the duration of the disk I/O.
- **Side effects:** mode `"w"` (default text mode, LF→CRLF). The open fails (throws) if any other handle to the file is open, e.g. a live `File`, because of `_wfopen_s` sharing.
- **Game internals:** none.
- **Quirks / bugs:** `null` and objects make it return `false` without writing anything for them. Doubles of magnitude ≥ ~1e45 to 1e46 crash the process (`File.cpp:103`). The legacy docs mention "binary representation (for binary files)", but output is always text.

### `FileTools.appendText(path, ...values)`

Like `writeText`, but appends.

- **Native:** `filetools_appendText` at `JSFileTools.cpp:217`; registered at `JSFileTools.h:38` (declared arity 2, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** as `writeText`; mode `"a+"` (`:224`).
- **Returns:** boolean, as `writeText` (`:242`).
- **Preconditions:** either.
- **Threading & blocking:** `Vars.cFileSection` held (`:221`, `:240`).
- **Side effects:** creates the file if missing.
- **Game internals:** none.
- **Quirks / bugs:** same as `writeText`.

---

## Folder

- **JSClass:** `"Folder"`, `JSCLASS_HAS_PRIVATE`, finalizer `dir_finalize` (`JSGlobalClasses.cpp:96-98`). Registered from `JSGlobalClasses.cpp:149` with `dir_methods`/`dir_props` (`JSDirectory.h:28-32`). Legacy api.html calls it "Directory".
- **Constructor:** `new Folder()` throws `"Invalid Operation"` (`JSDirectory.cpp:35`). Instances come from `dopen` and `Folder.prototype.create`.
- **Private data:** `DirData { wchar_t name[_MAX_FNAME]; }` (`JSDirectory.h:34-40`): the **relative** name as passed. `wcscpy_s` into 256 wchar means a longer name invokes the CRT invalid-parameter handler (process exit). `dir_finalize` deletes it (`JSDirectory.cpp:227-230`).
- **Identity & lifetime:** holds only a name. Every operation rebuilds `szScriptPath\name` (with the current root). There is no OS handle and no equality hook.

### Folder properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `name` | `DIR_NAME` = 0 (`JSDirectory.h:26`, `:28`) | string | R | any | `JS_InternUCString(d->name)` (`JSDirectory.cpp:220-221`) | Interned (pinned for the runtime's lifetime). A missing private → `JS_FALSE` without an exception (`:214-215`), i.e. uncatchable abort. |

### `dopen(name)`

Returns a `Folder` for `scripts\<name>`, **creating the directory if needed**.

- **Native:** `my_openDir` at `JSDirectory.cpp:37`; registered at `JSGlobalFuncs.h:50` (declared arity 1, `JSFUN_STUB_GSOPS`), as a global function.
- **Arguments / overloads:** `argc != 1` → returns **(unset)** without doing anything (`:38-39`). The argument goes through `JSVAL_TO_STRING` **without a type test** (`:42`); a non-string is undefined behaviour, likely a crash. `isValidPath` failure → `Log("The following path was deemed invalid…")` and **`return JS_FALSE` with no exception** (`:44-47`): an uncatchable abort of the calling script.
- **Returns:** a new `Folder`. If `_wmkdir` fails with `ENOENT` (missing parent), it throws `"Couldn't get directory <n>, path '<p>' not found"` (UTF-8 converted, `:51-57`). If `BuildObject` fails, the result is `null` and the `DirData` leaks, because the result is not checked (`:59-61`).
- **Preconditions:** either.
- **Threading & blocking:** synchronous `_wmkdir`.
- **Side effects:** **creates the directory** (one level only) if it doesn't exist. `EEXIST` and other errors are ignored, and the `Folder` is returned anyway (`:58-61`). That includes the case where `name` is an existing *file*.
- **Game internals:** none.
- **Quirks / bugs:** a path over `_MAX_PATH` overflows `swprintf_s` and the CRT handler terminates the process (`:49`). `dopen("")` refers to the script root itself.

### `Folder.prototype.create(name)`

Creates a sub-directory.

- **Native:** `dir_create` at `JSDirectory.cpp:170`; registered at `JSDirectory.h:31` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `argv[0]` must be a string (`"No path passed to dir.create()"`, `:173-174`; argc unchecked). `isValidPath` failure → **`JS_FALSE` with no exception** (`:177-179`).
- **Returns:** a new `Folder`. `ENOENT` → throws `"Couldn't create directory %s, path %s not found"`, but with **wide strings passed to `%s`**, so only the first character of each shows (`:182-184`). Any other `_wmkdir` error, including `EEXIST`, is ignored and a `Folder` is returned (`:185-189`). The `BuildObject` result is unchecked (`null` on failure).
- **Preconditions:** either.
- **Threading & blocking:** synchronous.
- **Side effects:** `_wmkdir(szScriptPath\<this.name>\<name>)` (`:181-182`).
- **Game internals:** none.
- **Quirks / bugs:** **the returned `Folder` is named `name`, not `<this.name>\<name>`** (`:186`), so it points at `scripts\<name>`, the wrong directory. `this` has no NULL check (`:171`, `:181`).

### `Folder.prototype.remove()`

Removes the (empty) directory.

- **Native:** `dir_delete` at `JSDirectory.cpp:193`; registered at `JSDirectory.h:31` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none read.
- **Returns:** `true` (`:206`). Throws `"Tried to delete directory, but it is not empty or is the current working directory"` on `ENOTEMPTY`, or `"Path not found"` on `ENOENT` (`:199-205`). **Any other failure (e.g. `EACCES`) still returns `true`.**
- **Preconditions:** either.
- **Threading & blocking:** synchronous `_wrmdir`.
- **Side effects:** deletes the directory.
- **Game internals:** none.
- **Quirks / bugs:** no NULL or class check on the private (`:194`, `:197`). Not recursive. `dopen("")` names the script root, so `dopen("").remove()` removes the root folder itself if it's empty.

### `Folder.prototype.getFiles([pattern])`

Lists file names (not sub-directories) matching a wildcard.

- **Native:** `dir_getFiles` at `JSDirectory.cpp:74`; registered at `JSDirectory.h:32` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `argc > 1` → **`JS_FALSE` with no exception** (`:75-76`). With no argument it **writes** `"*.*"` into `argv[0]` (past `argc`, `:77-78`). The pattern is `JS_ValueToString`-coerced (`:81`), which runs a user `toString` for objects. That result goes straight into `JS_GetStringCharsZ`, so a NULL (conversion threw) is dereferenced. `"Failed to get search string"` (`:82-83`) fires only if `JS_GetStringCharsZ` itself returns NULL. The pattern is **not validated** ([path-check matrix](#which-api-uses-which-check)). The private comes from the unchecked `JS_GetPrivate` (`:80`) and is dereferenced at `:87`: a prototype `this` crashes.
- **Returns:** an array of bare names, in `_wfindfirst`/`_wfindnext` order, `_A_SUBDIR` entries skipped (`:99-112`). An empty array if nothing matches.
- **Preconditions:** either.
- **Threading & blocking:** synchronous. **Changes the process-wide current directory** with `_wchdir(folder)` and restores it afterwards (`:89-96`, `:114-117`). This races with every other thread in Game.exe (other scripts, the game itself) that uses relative paths. Failure to get or set the CWD → `Log(...)` + **`JS_FALSE` with no exception**.
- **Side effects:** temporary CWD change.
- **Game internals:** none.
- **Quirks / bugs:** the `_wfindfirst` handle is never `_findclose`d (a leak per call). The pattern can reach outside the root (`"..\\..\\*"`; names only). Hidden and system files are included. Matching also hits 8.3 short names (CRT semantics).

### `Folder.prototype.getFolders([pattern])`

Lists sub-directory names matching a wildcard.

- **Native:** `dir_getFolders` at `JSDirectory.cpp:122`; registered at `JSDirectory.h:32` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** identical to `getFiles` (`:123-131`).
- **Returns:** an array of names with `_A_SUBDIR` set, excluding `.` and `..` (`:150-160`).
- **Preconditions:** either.
- **Threading & blocking:** same CWD race as `getFiles` (`:137-144`, `:162-165`).
- **Side effects:** temporary CWD change.
- **Game internals:** none.
- **Quirks / bugs:** same handle leak and pattern escape as `getFiles`.

---

## SQLite

Embedded SQLite **3.8.8** (`sqlite3.h:108`), compiled into the DLL (`D2BS.vcxproj:271`) with default options. `SQLITE_OMIT_AUTORESET` is not defined, so `sqlite3_step` after `SQLITE_DONE` resets automatically (`sqlite3.c:68744-68751`). No busy timeout is set anywhere, so two scripts writing the same database file get `SQLITE_BUSY` errors ("database is locked").

- **JSClass:** `"SQLite"`, `JSCLASS_HAS_PRIVATE`, finalizer `sqlite_finalize`, constructor `sqlite_ctor` (`JSGlobalClasses.cpp:32-34`). Registered from `JSGlobalClasses.cpp:157` with `sqlite_methods`/`sqlite_props` (`JSSQLite.h:39-47`).
- **Constructor:** real. `sqlite_ctor` builds and returns its own object, ignoring the `this` that `new` created, so `SQLite(...)` without `new` works identically.
- **Private data:** `SqliteDB { sqlite3* db; bool open; wchar_t* path; std::set<DBStmt*> stmts; }` (`JSSQLite.cpp:30-35`). `path` is the full sandboxed path, or the raw `:`-prefixed name. `stmts` holds raw pointers to every statement created by `query`.
- **Finalizer:** `sqlite_finalize` (`JSSQLite.cpp:280-288`) clears the private, calls `clean_sqlite_db` (finalizes every listed statement and `sqlite3_close`s the connection when `open`, `:47-57`), then frees `path` and the struct.
- **Identity & lifetime:** one connection per object. Statements do **not** keep their database object alive, and nothing stops the database being finalized while its statements are still referenced (see [DBStatement](#dbstatement)). `open` is never reset to `false` (see `close`). The equality hook `sqlite_equal` is commented out (`JSSQLite.cpp:290-305`).
- **Error messages are format strings:** every SQLite error is raised with `THROW_ERROR(cx, text)`, i.e. `JS_ReportError(cx, text)` with the text as the *format* (`js32.h:113-117`). That holds for the raw `sqlite3_errmsg` (`JSSQLite.cpp:162`, `:442`, `:500`, `:525`, `:535`) and for messages built around it (`:109-110`, `:141-144`, `:223-224`, `:235-236`). An error text containing `%`, such as SQLite's `near "%": syntax error` for user SQL, is read as a printf directive: garbage output or a bad varargs read.

### SQLite properties

Getter `sqlite_getProperty` (`JSSQLite.cpp:243`). There is **no NULL check** on the private (a prototype read crashes).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `path` | `SQLITE_PATH` = 0 (`JSSQLite.h:42`) | string | R | any | `dbobj->path` (`:249-251`) | Full path (`<root>\name`) or `:memory:` etc. |
| `statements` | `SQLITE_STMTS` = 1 (`JSSQLite.h:43`) | array of `DBStatement` | R | any | **new wrapper objects** around each `DBStmt*` in `stmts` whose `open` is set (`:258-271`) | Array length = `stmts.size()`, with holes (`undefined`) for closed statements. Each read makes a *second* wrapper sharing the same `DBStmt*`; when both are finalized, the struct is **freed twice** ([DBStatement](#dbstatement)). |
| `isOpen` | `SQLITE_OPEN` = 2 (`JSSQLite.h:44`) | boolean | R | any | `dbobj->open` (`:252-254`) | `true` after auto-open. Never set by `open()`, never cleared by `close()`. |
| `lastRowId` | `SQLITE_LASTROWID` = 3 (`JSSQLite.h:45`) | number | R | open | `sqlite3_last_insert_rowid` → `setInt32` (`:255-257`) | **Truncated to int32.** With `db == NULL` (constructed with `autoOpen = false`) this dereferences NULL: this build has no `SQLITE_ENABLE_API_ARMOR` (`sqlite3.c:127199-127207`). After `close()` it reads the freed handle. |
| `changes` | `SQLITE_CHANGES` = 4 (`JSSQLite.h:46`) | number | R | open | `sqlite3_changes` → `setDouble` (`:272-275`) | Rows changed by the last statement. Same NULL/freed-handle crash as `lastRowId` (`sqlite3.c:127212-127220`). |

### `SQLite([path[, autoOpen]])`

Creates a database object and opens it by default.

- **Native:** `sqlite_ctor` at `JSSQLite.cpp:80`; registered as `sqlite_db.construct` (`JSGlobalClasses.cpp:34`), installed by `JS_InitClass` (`ScriptEngine.cpp:232`, nargs 0).
- **Arguments / overloads:** `path`, if present, must be a string (`"Invalid parameters in SQLite constructor"`, `:81-82`); the default is `":memory:"` (`:85-88`). A path not starting with `:` must pass `isValidPath` (`"Invalid characters in database name"`, `:91-93`) and becomes `<root>\path` (`:95-98`). `autoOpen` is read from `argv[1]` **without checking `argc`** (`:102-103`); only a boolean counts, and the default is `true`.
- **Returns:** a `SQLite` object. Open failure → throws `"Could not open database: <sqlite3_errmsg>"` (`:107-111`).
- **Preconditions:** either.
- **Threading & blocking:** `sqlite3_open16` synchronously on the script thread.
- **Side effects:** creates the database file if absent.
- **Game internals:** none.
- **Quirks / bugs:** `path` leaks on the `isValidPath` and open-failure paths, and so does the handle that `sqlite3_open16` allocates on failure. A `:`-prefixed name bypasses the sandbox ([path-check matrix](#which-api-uses-which-check)). If `BuildObject` fails, it closes the handle and throws `"Could not create the sqlite object"` (`:119-125`). The open-failure message embeds `sqlite3_errmsg` in a format string ([SQLite](#sqlite) class notes).

### `SQLite.prototype.execute(sql)`

Runs one or more SQL statements; result rows are discarded.

- **Native:** `sqlite_execute` at `JSSQLite.cpp:131`; registered at `JSSQLite.h:39` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** exactly one string, else `"Invalid parameters in SQLite.execute"` (`:135-136`). The `isOpen` test comes first: `!open` → `"Database must first be opened!"` (`:133-134`).
- **Returns:** `true`. On SQL error throws the SQLite message (`sqlite3_exec` error text, `:139-145`). Every statement in the string runs, up to the first error (`sqlite3_exec` semantics).
- **Preconditions:** `isOpen` (`:133`); game state irrelevant.
- **Threading & blocking:** synchronous `sqlite3_exec`; long queries freeze the script.
- **Side effects:** database writes.
- **Game internals:** none.
- **Quirks / bugs:** `strcpy_s(msg, 2048, err)` (`:141`) runs the CRT invalid-parameter handler (process exit) if `err` is NULL or longer than 2047 bytes. No NULL check on the private (`:133`).

### `SQLite.prototype.query(sql, ...binds)`

Prepares a statement and binds positional parameters.

- **Native:** `sqlite_query` at `JSSQLite.cpp:151`; registered at `JSSQLite.h:39` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `sql` must be a string (`"Invalid parameters to SQLite.query"`, `:155-156`). Only the **first** statement is compiled (`pzTail` ignored, `:160`). Each extra argument `i` binds to parameter `i` (`:170-197`):

  | JS type | Bound as |
  |---|---|
  | `undefined` | NULL |
  | string | UTF-8 text, `SQLITE_STATIC`, **buffer freed immediately** (`:176-178`) |
  | int-tagged / double-tagged number | `sqlite3_bind_int` / `sqlite3_bind_double` |
  | boolean | text `"true"` / `"false"` |
  | `null`, object, function | throws `"Invalid bound parameter <i>"` |
- **Returns:** a new `DBStatement` (not yet stepped; `ready === false`). Prepare errors throw `sqlite3_errmsg` (`:160-163`). An empty statement throws `"Statement has no effect"` (`:164-167`). If `BuildObject` fails it throws `"Could not create the sqlite row object"` (`:207-213`).
- **Preconditions:** `isOpen` (`:153-154`).
- **Threading & blocking:** synchronous prepare.
- **Side effects:** adds a `DBStmt` to `stmts` (`:199-205`).
- **Game internals:** none.
- **Quirks / bugs:** **bound strings are a use-after-free.** SQLite is told the buffer is static, but it is `JS_free`d straight away, so at `step` time the parameter reads freed memory, and with several string parameters the allocator may hand the same block to the next one. If `BuildObject` fails, the `DBStmt` is deleted while still in `stmts`, leaving a dangling pointer (`:207-213`). There is no named binding here; use `bind`. The `sqlite3_bind_*` return codes are ignored, so extra arguments beyond the statement's parameter count (`SQLITE_RANGE`) are dropped silently.

### `SQLite.prototype.open()`

Opens the connection if `isOpen` is false.

- **Native:** `sqlite_open` at `JSSQLite.cpp:230`; registered at `JSSQLite.h:40` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true`. Throws `"Could not open database: …"` on failure.
- **Preconditions:** none checked; no NULL check on the private (`:231-232`). A no-op returning `true` when `isOpen` is already true.
- **Threading & blocking:** synchronous.
- **Side effects:** `sqlite3_open16(path, &db)` (`:232-237`). It overwrites `db` without closing the previous value; on failure the failed handle is stored there.
- **Game internals:** none.
- **Quirks / bugs:** **never sets `dbobj->open = true`**, so after `new SQLite(p, false); db.open()` the database is connected but `isOpen` stays false and `execute`/`query` keep throwing `"Database must first be opened!"`. Each further `open()` leaks a new connection.

### `SQLite.prototype.close()`

Finalizes all statements and closes the connection.

- **Native:** `sqlite_close` at `JSSQLite.cpp:219`; registered at `JSSQLite.h:40` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true`. Throws `"Could not close database: …"` if `sqlite3_close` fails (`:221-225`).
- **Preconditions:** none (a NULL private is tolerated by `clean_sqlite_db`).
- **Threading & blocking:** synchronous.
- **Side effects:** only if `isOpen` is true: `sqlite3_finalize` on every listed statement (sets their `stmt = NULL`, `open = false`), **`stmts.clear()`**, then `sqlite3_close` (`clean_sqlite_db`, `:47-57`). The `DBStmt` structs themselves stay owned by their `DBStatement` wrappers.
- **Game internals:** none.
- **Quirks / bugs:** **`open` is not cleared and `db` is not nulled** (`:47-57`). `isOpen` still reads `true`, and later `execute`/`query` (or a second `close()`, or the finalizer) use the **closed `sqlite3*`**, which is use-after-free. Conversely, when `isOpen` is false (after `new SQLite(p, false); db.open()`), `close()` does nothing and returns `true`, so the connection made by `open()` is never closed, not even by the finalizer.

### `sqlite_version()`

Returns the linked SQLite version string.

- **Native:** `my_sqlite_version` at `JSSQLite.cpp:67`; registered at `JSGlobalFuncs.h:49` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** string `sqlite3_version` (`"3.8.8"`), interned (`:68`).
- **Preconditions:** either.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** none.

### `sqlite_memusage()`

Meant to return `sqlite3_memory_used()`.

- **Native:** `my_sqlite_memusage` at `JSSQLite.cpp:72`; registered at `JSGlobalFuncs.h:50` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** **(unset)**. The value goes into a local copy of `JS_RVAL` and is never stored back (`:73-75`).
- **Preconditions:** either.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** broken as described. The legacy docs promise a `double` (`doc/globalFuncs.h:1100`).

---

## DBStatement

- **JSClass:** `"DBStatement"`, `JSCLASS_HAS_PRIVATE`, finalizer `sqlite_stmt_finalize` (`JSGlobalClasses.cpp:36-38`). Registered from `JSGlobalClasses.cpp:158` with `sqlite_stmt_methods`/`sqlite_stmt_props` (`JSSQLite.h:49-63`).
- **Constructor:** `new DBStatement()` throws `"Invalid Operation"` (`JSSQLite.cpp:78`). Instances come from `SQLite.prototype.query` and `SQLite.prototype.statements`.
- **Private data:** `DBStmt { sqlite3_stmt* stmt; bool open, canGet; SqliteDB* assoc_db; JSObject* current_row; }` (`JSSQLite.cpp:37-42`). `canGet` is "a row is available". `current_row` caches `getObject()`'s result and is **explicitly rooted** (`JSSQLite.cpp:364`).
- **Finalizer:** `sqlite_stmt_finalize` (`JSSQLite.cpp:577-589`). If the statement is still open, it erases itself from `assoc_db->stmts` and finalizes the statement; it always `delete`s the struct. It does **not** remove the `current_row` root (commented out, `:583-584`).
- **Identity & lifetime:** a raw `SqliteDB*` back-pointer with no reference to the database's JS object. Hazards, all from the code above:
  - `go()` marks the statement closed (`open = false`) but leaves it in `stmts`. When the wrapper is later finalized it is deleted **without being erased**, because the erase is guarded by `open` (`:581-582`). `stmts` then keeps a dangling pointer that a later `SQLite.close()`, database finalize or `statements` read dereferences. `SQLite.close()` doesn't cause this: `clean_sqlite_db` empties `stmts` (`:52`).
  - `close()` (`:541-556`) deletes the struct **without erasing it from `stmts`**, with the same result.
  - `statements` creates extra wrappers sharing one `DBStmt*` ([SQLite properties](#sqlite-properties)): **double free** at GC.
  - A statement whose database object was GC'd keeps `assoc_db` pointing at freed memory. The database finalizer has already finalized it (`stmt = NULL`), so the next `next()`/`go()`/`skip()` gets `SQLITE_MISUSE` and its error path calls `sqlite3_errmsg(assoc_db->db)` on freed memory.
  - A finalized statement with a live `current_row` root leaves a **root pointing into freed memory**. That happens whenever the script drops the statement after `getObject()` without a later `next()`/`close()` (e.g. breaking out of a `while (s.next())` loop early), or after `getObject()` followed by `go()`/`reset()`, which don't unroot.
  - After `close()` the private is NULL (`:549`), and **every method and property dereferences NULL** (crash).

### DBStatement properties

Getter `sqlite_stmt_getProperty` (`JSSQLite.cpp:558`). No NULL check.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `sql` | `SQLITE_STMT_SQL` = 0 (`JSSQLite.h:61`) | string | R | not closed/finalized | `sqlite3_sql(stmt)`, UTF-8 decoded (`:564-569`) | After `go()` the stmt is NULL, so `sqlite3_sql` returns NULL. `AnsiToUnicode(NULL)` then allocates a zero-length, unterminated buffer (`Helpers.cpp:16-22`), and `JS_NewUCStringCopyZ` over-reads it. |
| `ready` | `SQLITE_STMT_READY` = 1 (`JSSQLite.h:62`) | boolean | R | any | `canGet` (`:570-572`) | `true` only after a `next()`/`skip()` that produced a row. |

### `DBStatement.prototype.next()`

Steps to the next row.

- **Native:** `sqlite_stmt_next` at `JSSQLite.cpp:494`; registered at `JSSQLite.h:54` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true` if a row is available (`SQLITE_ROW`), `false` at `SQLITE_DONE` (`:507`). Other results throw `sqlite3_errmsg` (`:499-500`).
- **Preconditions:** statement not closed.
- **Threading & blocking:** synchronous `sqlite3_step`; this is where the query actually runs.
- **Side effects:** `canGet = (res == ROW)`; unroots and clears the cached `current_row` (`:502-506`). Calling it after `false` silently restarts the query (auto-reset).
- **Game internals:** none.
- **Quirks / bugs:** none beyond the lifetime hazards.

### `DBStatement.prototype.getObject()`

Returns the current row as an object keyed by column name.

- **Native:** `sqlite_stmt_getobject` at `JSSQLite.cpp:307`; registered at `JSSQLite.h:49` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `null` if no row (`:311-314`). The cached object if already built (`:315-318`). `true` if the statement has 0 columns (`:320-324`). Otherwise an object with INTEGER→number (via double, exact only to 2⁵³), FLOAT→number, TEXT→UTF-8-decoded string, NULL→`null`; BLOB throws `"Blob type not supported (yet)"` (`:330-362`).
- **Preconditions:** a row is available.
- **Threading & blocking:** synchronous.
- **Side effects:** roots the new object in `current_row` (`:363-365`).
- **Game internals:** none.
- **Quirks / bugs:** column names are UTF-8 `char*` passed to `JS_SetProperty`, so non-ASCII names are mangled ([encodings](#text-encodings-used-on-this-page)). If `JS_AddRoot` fails the call returns **(unset)** (`:364-365`). **The row object is created with `JS_New(cx, NULL, NULL, NULL)`** (`:325`), i.e. "construct with a NULL constructor". `JS_New` takes the constructor object as its second parameter (`dependencies/include/jsapi.h:3181`), so for any row with ≥1 column this is expected to dereference NULL inside the engine (crash; see Open questions). Use `getColumnValue`/`getColumnName` instead. Duplicate column names overwrite each other.

### `DBStatement.prototype.getColumnCount()`

Returns the number of result columns.

- **Native:** `sqlite_stmt_colcount` at `JSSQLite.cpp:370`; registered at `JSSQLite.h:50` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** number (`:377`). Throws `"Statement is not ready"` unless a row is available (`:374-375`).
- **Preconditions:** `ready`.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** the column count is known before stepping, but the method still insists on a row.

### `DBStatement.prototype.getColumnValue(index)`

Returns one column of the current row.

- **Native:** `sqlite_stmt_colval` at `JSSQLite.cpp:381`; registered at `JSSQLite.h:51` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** exactly one int-tagged number (0-based), else `"Invalid parameter for SQLiteStatement.getColumnValue"` (`:388-389`). `"Statement is not ready"` without a row.
- **Returns:** number / string / `null`, mapped as in `getObject`; BLOB throws (`:392-415`). An out-of-range index → SQLite reports `SQLITE_NULL` → `null`.
- **Preconditions:** `ready`.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** none further.

### `DBStatement.prototype.getColumnName(index)`

Returns a column name.

- **Native:** `sqlite_stmt_colname` at `JSSQLite.cpp:419`; registered at `JSSQLite.h:52` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** as `getColumnValue`. The error message also says `getColumnValue` (`:426-427`).
- **Returns:** string (UTF-8 decoded, `:429-433`).
- **Preconditions:** `ready`.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** an out-of-range index makes `sqlite3_column_name` return NULL, which goes to `AnsiToUnicode`: zero-length unterminated buffer → heap over-read (`Helpers.cpp:16-22`). The index is not range-checked.

### `DBStatement.prototype.go()`

Executes one step and **finalizes** the statement (for INSERT/UPDATE/DDL).

- **Native:** `sqlite_stmt_execute` at `JSSQLite.cpp:436`; registered at `JSSQLite.h:53` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true` if the step returned `SQLITE_DONE`, `false` if it returned a row (which is then discarded) (`:444`). Errors throw `sqlite3_errmsg` (`:441-442`).
- **Preconditions:** statement open.
- **Threading & blocking:** synchronous step.
- **Side effects:** `close_db_stmt`: `sqlite3_finalize`, `stmt = NULL`, `open = false` (`:443`, `:59-65`). The entry stays in `stmts`.
- **Game internals:** none.
- **Quirks / bugs:** later `next()`/`go()`/`skip()` calls step a NULL statement. `sqlite3_step(NULL)` returns `SQLITE_MISUSE` without recording an error on the connection, so the thrown text is whatever error the connection last recorded (`"not an error"` if none). `sql` then over-reads ([DBStatement properties](#dbstatement-properties)), while `reset()` returns `true` (`sqlite3_reset(NULL)` is `SQLITE_OK`). `current_row` is not unrooted. Causes the dangling-pointer chain described in [DBStatement](#dbstatement).

### `DBStatement.prototype.skip(n)`

Intended to skip `n` rows.

- **Native:** `sqlite_stmt_skip` at `JSSQLite.cpp:511`; registered at `JSSQLite.h:55` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** an int-tagged number, else `"Invalid parameter to SQLiteStatement.skip"` (`:514-515`).
- **Returns:** `n ≤ 0`: returns `n` (rval preset to the argument, `:512`) and does nothing. **`n > 0`: never returns.** The loop is `for (i = n-1; i >= 0; i++)`, which counts up (`:516`). On `SQLITE_DONE` it sets `i = 0` and continues (`:519-523`), and auto-reset restarts the query, so the loop spins forever unless `sqlite3_step` reports an error (which throws).
- **Preconditions:** statement open.
- **Threading & blocking:** **hangs the script thread** in native code. `Script::Stop` can't interrupt it ([threading model](#threading-model-all-classes)).
- **Side effects:** endless `sqlite3_step`.
- **Game internals:** none.
- **Quirks / bugs:** as above. The legacy docs promise "the number of rows actually skipped".

### `DBStatement.prototype.reset()`

Resets the statement to before the first row.

- **Native:** `sqlite_stmt_reset` at `JSSQLite.cpp:532`; registered at `JSSQLite.h:56` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true`. If `sqlite3_reset` reports the previous step's error, throws `sqlite3_errmsg` (`:534-535`).
- **Preconditions:** statement open.
- **Threading & blocking:** none.
- **Side effects:** `canGet = false`. Bindings are kept (no `sqlite3_clear_bindings`). `current_row` is **not** cleared or unrooted, so a stale cached row object stays rooted until the next `next()`.
- **Game internals:** none.
- **Quirks / bugs:** see side effects.

### `DBStatement.prototype.close()`

Finalizes and frees the statement.

- **Native:** `sqlite_stmt_close` at `JSSQLite.cpp:541`; registered at `JSSQLite.h:57` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true` (`:550`).
- **Preconditions:** private present. A second `close()` dereferences NULL (`:543-544`).
- **Threading & blocking:** none.
- **Side effects:** unroots `current_row`, `sqlite3_finalize`, `delete` struct, private set to NULL (`:544-549`).
- **Game internals:** none.
- **Quirks / bugs:** does not erase the struct from `assoc_db->stmts`, so the database keeps a dangling pointer ([DBStatement](#dbstatement)). `JS_ValueToObject(cx, JSVAL_NULL, &obj)` (`:552-553`) is dead code.

### `DBStatement.prototype.bind(param, value)`

Binds one parameter by 1-based index or by name.

- **Native:** `sqlite_stmt_bind` at `JSSQLite.cpp:448`; registered at `JSSQLite.h:58` (declared arity 2, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** exactly 2 arguments; `param` must be an int-tagged number or a string, else `"Invalid parameters for SQLiteStatement.bind"` (`:451-452`). A string is resolved with `sqlite3_bind_parameter_index` and must include the prefix (`":name"`, `"@name"`, `"$name"`). An unknown name or index 0 → `"Invalid parameter number, parameters start at 1"` (`:463-464`). Value mapping as in `query`; `null` and objects → `"Invalid bound parameter"` (`:485-486`).
- **Returns:** `true` (`:490`). The `sqlite3_bind_*` result code is ignored, so an out-of-range index or binding a running statement fails silently.
- **Preconditions:** before the first `next()`/`go()`, or after `reset()`.
- **Threading & blocking:** none.
- **Side effects:** binds.
- **Game internals:** none.
- **Quirks / bugs:** strings use `SQLITE_STATIC` and are then freed (`:472-474`), the same use-after-free as `query`.

---

## Socket

Undocumented in every legacy source. A blocking, IPv4-only TCP client.

- **JSClass:** `"Socket"`, `JSCLASS_HAS_PRIVATE`, finalizer `socket_finalize` (`JSGlobalClasses.cpp:88-90`). Registered from `JSGlobalClasses.cpp:155` with `socket_methods`, `socket_props` and static `socket_s_methods` (`JSSocket.h:25-32`).
- **Constructor:** `new Socket()` throws `"Invalid Operation"` (`JSSocket.cpp:24`). Instances come only from `Socket.open`.
- **Private data:** `SocketData { int mode; SOCKET socket; }` (`JSSocket.cpp:20-23`). `mode` is set to the socket value and never read (`:105`).
- **Finalizer:** `socket_finalize` (`JSSocket.cpp:167-173`) calls `closesocket` + `WSACleanup` and **does not free `SocketData`** (an 8-byte leak per socket).
- **Identity & lifetime:**
  - One OS socket per object. `close()` neither marks the socket closed nor clears the private, so **the finalizer closes the same SOCKET value again and calls `WSACleanup` a second time**. By then the handle value may belong to another socket in the process.
  - Each successful `open` does one `WSAStartup` (`:88`), while `close()` plus finalization do two `WSACleanup`s. The Winsock refcount is process-wide, so the imbalance can drain the count of other Winsock users in Game.exe.
  - No equality hook (`socket_equality` is declared at `JSSocket.h:11`, never defined).
- **Host allow-list:** `Vars.szHosts` (`D2BS.h:88`), from `[settings] Hosts=` (default empty, `Helpers.cpp:118`, `:138-140`). See [architecture.md §5.2](../architecture.md#52-settings-keys).

### Socket properties

Getter `socket_getProperty` (`JSSocket.cpp:26`). `socket_setProperty` (`:65-67`) exists but is not wired to any property.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `readable` | `SOCKET_READABLE` = 0 (`JSSocket.h:30`) | number | R | any | `select(1, {sock}, NULL, NULL, {0 s, 100 µs})` (`:36-45`) | `1` ready, `0` not, `-1` error. The comment says 100 ms, but `tv_usec = 100` is **0.1 ms**. Readable also means "peer closed". |
| `writeable` | `SOCKET_WRITEABLE` = 1 (`JSSocket.h:31`) | number | R | any | same with the write set (`:47-58`) | |

Both getters call `JS_BeginRequest` without ever calling `JS_EndRequest` (`:32`), so the request depth grows on each read.

### `Socket.open(host, port)`

Resolves `host` and connects a TCP socket.

- **Native:** `socket_open` at `JSSocket.cpp:69`; registered at `JSSocket.h:28` (declared arity 2, `JSFUN_STUB_GSOPS`), as a static on `Socket`.
- **Arguments / overloads:** `argc < 2` → returns `false` (`:71-74`). `host` is UTF-8-encoded only if it is a string (`:77-78`). A **non-string leaves `hostName` NULL and crashes in `strstr`** (`:80`). The allow-list check is `strstr(Vars.szHosts, host)`, a **substring** match: `"e.com"` passes if `Hosts=example.com`, and `""` always passes (resolving the local host). Failure → `"Invalid hostname specified"` (`:80-81`). `port` is `JS_ValueToInt32`-coerced (`"Could not convert parameter 2"`, `:83-84`), then `htons`, so it is truncated to 16 bits.
- **Returns:** a `Socket` on success. `WSAStartup` failure → **(unset)** (`:88-90`). Throws `"Cannot find host"` (`:99-100`), `"Failed to connect"` (`:107-109`) or `"Failed to define the socket object"` (`:112-116`).
- **Preconditions:** either; the host must be allow-listed.
- **Threading & blocking:** **blocking `gethostbyname` (DNS) and blocking `connect`** (no timeout, so the OS default applies) on the script thread.
- **Side effects:** `WSAStartup(2.2)`; `socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)`; outbound TCP connection.
- **Game internals:** none.
- **Quirks / bugs:** on the "Invalid hostname", port-conversion and `WSAStartup`-failure paths `hostName` leaks. On the DNS and connect failure paths, `SocketData`, the socket and a `WSAStartup` reference leak. The `socket()` result is not checked. Only the first IPv4 address is used.

### `Socket.prototype.send(text)`

Sends a string as UTF-8.

- **Native:** `socket_send` at `JSSocket.cpp:130`; registered at `JSSocket.h:25` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** `argv[0]` (argc unchecked). A **non-string leaves `msg` NULL → `strlen(NULL)` crash** (`:134-137`).
- **Returns:** **(unset)**. The `send` result (bytes sent, or error) is discarded.
- **Preconditions:** connected socket.
- **Threading & blocking:** blocking `send` (may block while the TCP send buffer is full).
- **Side effects:** network write without a terminator. Partial sends are not retried.
- **Game internals:** none.
- **Quirks / bugs:** the UTF-8 buffer is never `JS_free`d (a leak per call). No NULL check on the private. The length is `strlen(msg)`, so text containing U+0000 is cut at the first NUL. The API is text-only, not binary-safe.

### `Socket.prototype.read()`

Receives once and returns the data as a string.

- **Native:** `socket_read` at `JSSocket.cpp:142`; registered at `JSSocket.h:26` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** a string, UTF-8-decoded and **interned** (`JS_InternUCString`, `:162`, pinned for the runtime's lifetime). `""` when the peer has closed (`recv` = 0). `recv` = -1 → throws `"Socket Error"` (`:155-157`).
- **Preconditions:** connected socket.
- **Threading & blocking:** **blocking `recv` with no timeout.** The script stalls until data arrives or the peer closes, and can't be stopped meanwhile. Check `readable` first.
- **Side effects:** consumes up to 10000 bytes.
- **Game internals:** none.
- **Quirks / bugs:** exactly one `recv` (the loop condition `iResult > 10000` is never true, `:159`). Data is appended as a C string (`:154`), so it **stops at the first NUL** and is not binary-safe. A full 10000-byte read has no terminator, and `append` **reads past the stack buffer**. Interning every message leaks memory in long-running scripts.

### `Socket.prototype.close()`

Closes the socket.

- **Native:** `socket_close` at `JSSocket.cpp:121`; registered at `JSSocket.h:25` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** **(unset)**.
- **Preconditions:** private present (no NULL check, `:122-124`).
- **Threading & blocking:** `closesocket` (graceful close semantics).
- **Side effects:** `closesocket` + `WSACleanup` (`:124-125`). The private is left in place, so the double close happens at finalization (see class notes).
- **Game internals:** none.
- **Quirks / bugs:** calling it twice repeats both calls.

---

## Sandbox

Engine-level analysis (context/compartment problems, rooting) is in [embedding.md §8](../spidermonkey/embedding.md#8-sandbox). Only the JS contract is given here.

- **JSClass:** `"Sandbox"`, `JSCLASS_HAS_PRIVATE`, class hooks `sandbox_addProperty` / `sandbox_delProperty` / `sandbox_getProperty` / `sandbox_setProperty`, finalizer `sandbox_finalize`, constructor `sandbox_ctor` (`JSGlobalClasses.cpp:64-66`). Registered from `JSGlobalClasses.cpp:159` with `sandbox_methods` (`JSSandbox.h:26-27`); no property specs.
- **Constructor:** real (`sandbox_ctor`, `JSSandbox.cpp:6`), but **its first statement is `JS_NewContext(ScriptEngine::GetRuntime(), 0x2000)` (`:8`), and `ScriptEngine::runtime` is never assigned a non-NULL value** (initialised `NULL` at `ScriptEngine.cpp:19`; the only other write is `runtime = NULL` at `:159`; getter at `ScriptEngine.h:55-57`). Constructing a `Sandbox` therefore passes a NULL runtime into SpiderMonkey, which is expected to crash Game.exe (see Open questions). The rest of this section describes what the code *would* do.
- **Private data:** `struct sandbox { JSContext* context; JSObject* innerObj; IncludeList list; }` (`JSSandbox.h:20-24`). The inner global is `JS_NewObject(box->context, &global_obj, ...)` with standard classes only and **no D2BS globals** (`JSSandbox.cpp:13-24`). It is never rooted.
- **Finalizer:** `JS_DestroyContext(box->context); delete box` (`JSSandbox.cpp:164-171`), destroying a context from inside GC.
- **Identity & lifetime / property hooks:** reads, writes, adds and deletes of non-method properties on the wrapper are forwarded **by name** to `innerObj` through `box->context` (`JSSandbox.cpp:48-162`). Integer ids are stringified. Values are copied raw between contexts, with no wrapping. A get returns the inner value, or `undefined` when the inner object lacks the name. The fallback lookup on the wrapper itself (`:121`, `:130`) runs only when there is no box or the inner lookup fails. With no box (e.g. on `Sandbox.prototype`), add defines the property on the object itself (`:50-51`). Several hook paths return `JS_FALSE` without an exception, an uncatchable abort: add with a non-int/string id (`:80`); delete and set with no box or when the inner call fails (`:104`, `:161`); get only when the fallback lookup also fails (`:136`). Names cross as UTF-8 `char*`, so non-ASCII names are mangled ([encodings](#text-encodings-used-on-this-page)). Methods are unaffected (`JSFUN_STUB_GSOPS`).
- **Properties:** none defined; arbitrary names are proxied as above.

### `Sandbox()`

Creates a sandbox (crashes, see above).

- **Native:** `sandbox_ctor` at `JSSandbox.cpp:6`; registered as `sandbox_class.construct` (`JSGlobalClasses.cpp:66`), installed by `JS_InitClass` (nargs 0).
- **Arguments / overloads:** none read.
- **Returns:** the new wrapper. Every failure path returns **(unset)** without throwing (`:9-40`).
- **Preconditions:** either.
- **Threading & blocking:** would create a context on a runtime the calling thread does not own.
- **Side effects:** the failure path at `:35-40` removes the wrong root (`&box->innerObj`) and leaves `&res` rooted.
- **Game internals:** none.
- **Quirks / bugs:** non-functional, as above.

### `Sandbox.prototype.evaluate(code)`

Evaluates source text in the inner global.

- **Native:** `sandbox_eval` at `JSSandbox.cpp:173`; registered at `JSSandbox.h:26` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** a string, else `"Invalid parameter, string expected"` (`:183-184`). No private → `"Invalid execution object!"` (`:176-177`).
- **Returns:** the completion value if `JS_BufferIsCompilableUnit` **and** `JS_EvaluateScript(..., "sandbox", 0, ...)` succeed (`:180-182`). Otherwise **(unset)**, and errors are not propagated to the caller.
- **Preconditions:** a working sandbox (impossible, see the constructor).
- **Threading & blocking:** runs JS synchronously. The operation callback of the inner context is not set, so the caller can't be interrupted while it runs.
- **Side effects:** arbitrary JS in the inner global.
- **Game internals:** none.
- **Quirks / bugs:** the UTF-8 `code` buffer is never freed (a leak).

### `Sandbox.prototype.include(file)`

Intended to run `<root>\libs\<file>` in the inner global.

- **Native:** `sandbox_include` at `JSSandbox.cpp:188`; registered at `JSSandbox.h:26` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** a string, else `"Invalid parameter, file expected"` (`:210-211`). The length must be ≤ `_MAX_FNAME` (`:193`); a longer name, or a missing private, silently returns `false`. There is no path validation.
- **Returns:** `false` (preset, `:189`). The guard `box->list.count(file) == -1` (`:196`) compares an unsigned `0`/`1` with `-1` and is never true, so **nothing is ever compiled or executed**.
- **Preconditions:** n/a.
- **Threading & blocking:** none in practice.
- **Side effects:** none in practice.
- **Game internals:** none.
- **Quirks / bugs:** dead code; the path would have escaped the root with `..\`.

### `Sandbox.prototype.isIncluded(file)`

Reports whether `include` recorded the file.

- **Native:** `sandbox_isIncluded` at `JSSandbox.cpp:216`; registered at `JSSandbox.h:27` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** a string and a private, else `"Invalid parameter, file expected"` (`:223-224`).
- **Returns:** boolean: looks up the **full path** `<root>\libs\<file>` (`:221-222`), whereas `include` would have stored the bare name. Always `false`.
- **Preconditions:** n/a.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** legacy name `isInclude` (`doc/Sandbox.h:32`). Unlike `include`, there's no length check before `swprintf_s` into a 516-wchar buffer (`:220-221`), so a long `file` hits the CRT invalid-parameter handler (process exit).

### `Sandbox.prototype.clearScope()`

No-op.

- **Native:** `sandbox_clear` at `JSSandbox.cpp:228`; registered at `JSSandbox.h:27` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** **(unset)**. The `JS_ClearScope` call is commented out (`:230-231`).
- **Preconditions:** none.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** none further.

---

## D2BSScript

A handle on another (or the current) script: its name, state, pause/resume/stop/join, and message sending. This is the closest existing analogue of an RPC "session" or "job" object.

- **JSClass:** `"D2BSScript"`, `JSCLASS_HAS_PRIVATE`, **no finalizer** (`JSGlobalClasses.cpp:40-42`). Registered from `JSGlobalClasses.cpp:160` with `script_methods`/`script_props` (`JSScript.h:29-42`).
- **Constructor:** `new D2BSScript()` throws `"Invalid Operation"` (`JSScript.cpp:7`). Instances come from `getScript` and `getScripts`. `load()` returns `null`, not a script object ([globals-core.md](globals-core.md#loadfile-args)).
- **Private data:** a **borrowed raw `Script*`** (`Script.h:106-207`) taken from `ScriptEngine::scripts`. No reference count, no notification. Nothing is freed when the wrapper dies.
- **Identity & lifetime:** every call creates a new wrapper, so `getScript(true) === getScript(true)` is `false`. `getNext()` **mutates** the wrapper to point at another script. The pointer is **not revalidated**: once a script is disposed (`ScriptEngine::DisposeScript` → `delete script`, `ScriptEngine.cpp:71-90`), for example when its thread ends with `DisableCache=true` (`Script.cpp:480-481`), every outstanding wrapper dangles and any property or method access is a use-after-free. See [embedding.md §5.6](../spidermonkey/embedding.md#56-disposal-and-the-jscontext_destroy-path) for when disposal happens.
- **Cross-thread use:** the target `Script` usually lives on another thread. Its state flags (`isPaused`, `isAborted`, `hasActiveCX`) are plain `bool`s with no synchronisation. The only engine call made on the other runtime is `JS_TriggerOperationCallback`, the one documented thread-safe entry point (`dependencies/include/jsapi.h:4010-4030`). Exception: the `memory` getter calls `JS_GetGCParameter(otherRuntime)`.
- **Script ordering:** `ScriptEngine::scripts` is a `std::map<std::wstring, Script*>` (`ScriptEngine.h:13`). Keys are lower-cased full paths (`ScriptEngine.cpp:35-36`), plus `L"console"` for the console script (`ScriptEngine.cpp:131`). Iteration order (`getScripts`, `getNext`, `getScript()`) is wide-string lexicographic order of those keys.

### D2BSScript properties

Getter `script_getProperty` (`JSScript.cpp:18`). A missing private returns `undefined` (`:22-23`).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `name` | `SCRIPT_FILENAME` = 0 (`JSScript.h:29`) | string | R | any | `JS_InternUCString(Script::GetShortFilename())` (`:29-31`; `Script.cpp:244-249`) | Lower-cased path relative to the root, with `\`. `"Command Line"` for a file-less console. The offset is computed from the *current* `wcslen(szScriptPath)`, so it is wrong (or overruns) after a profile switch changes the root length. |
| `type` | `SCRIPT_GAMETYPE` = 1 (`JSScript.h:30`) | **boolean** | R | any | `GetState() == InGame ? false : true` (`:32-34`) | `false` = in-game, `true` = out-of-game or console. Legacy says int 0/1. |
| `running` | `SCRIPT_RUNNING` = 2 (`JSScript.h:31`) | boolean | R | any | `Script::IsRunning()` = `context && !(aborted \|\| paused \|\| !hasActiveCX)` (`:35-37`; `Script.cpp:340-342`) | **A paused script reports `false`.** |
| `threadid` | `SCRIPT_THREADID` = 3 (`JSScript.h:32`) | number | R | any | `GetThreadId()` (`:38-40`; `Script.cpp:73-75`) | `-1` if no thread handle. A DWORD stored as int32. |
| `memory` | `SCRIPT_MEMORY` = 4 (`JSScript.h:33`) | number | R | started scripts | `JS_GetGCParameter(script->GetRuntime(), JSGC_BYTES)` (`:41-43`) | Reads another thread's runtime. `Script::runtime` is **not initialised** by the constructor (`Script.cpp:15-17`) and is only set in `Run` (`Script.cpp:120`), so for a script that hasn't started this dereferences garbage. Not in the legacy docs. |

### `getScript([selector])`

Returns a `D2BSScript` for the current script, a thread id, a file name, or the first script.

- **Native:** `my_getScript` at `JSScript.cpp:142`; registered at `JSGlobalFuncs.h:31` (declared arity 0, `JSFUN_STUB_GSOPS`), as a global function.
- **Arguments / overloads** (only `argc == 1` selects; anything else falls through to "first"):

  | Call | Selection | Source |
  |---|---|---|
  | `getScript(true)` | the calling script (`JS_GetContextPrivate(cx)`) | `:145-146` |
  | `getScript(tid)` (int-tagged) | `ForEachScript(FindScriptByTid)`: `Script::GetThreadId() == tid`. `-1` matches scripts without a thread. | `:147-155`, `:221-228` |
  | `getScript("name")` | `/`→`\`, then `_wcsicmp` against `GetShortFilename()` (case-insensitive, relative to the root, extension included) | `:156-166`, `:210-219` |
  | `getScript()`, `getScript(false)`, any other type, `argc > 1` | `scripts.begin()->second` (first in map order) | `:167-178` |
- **Returns:** a new `D2BSScript`, or `null` if nothing matched or the map is empty (`:143`, `:155`, `:166`, `:176-177`). `"Failed to build the script object"` if `BuildObject` fails (`:182-183`).
- **Preconditions:** either.
- **Threading & blocking:** `ForEachScript` snapshots the map under the script-list lock and runs the callbacks **unlocked** (`ScriptEngine.cpp:204-228`). The callback's return value doesn't stop the iteration, so with several matches the **last** one wins. `scripts.size()` is read without the lock (`:168`).
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** the returned pointer can be disposed before it is used (TOCTOU). `getScript("Command Line")` finds a file-less console script.

### `getScripts()`

Returns wrappers for every entry in the script map.

- **Native:** `my_getScripts` at `JSScript.cpp:188`; registered at `JSGlobalFuncs.h:31` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none read.
- **Returns:** an array of `D2BSScript` in map order. Includes the console and **cached, not-running** scripts (with `DisableCache=false`).
- **Preconditions:** either.
- **Threading & blocking:** holds the script-list lock while building every wrapper (`:195-204`), so allocation and possibly GC happen under the lock.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** a `BuildObject` failure stores `null` into the array silently.

### `D2BSScript.prototype.getNext()`

Advances the wrapper to the next script in map order.

- **Native:** `script_getNext` at `JSScript.cpp:51`; registered at `JSScript.h:36` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `true` after retargeting `this` (`JS_SetPrivate`, `:63-64`). **`undefined`** at the end, or if the current script is no longer in the map (`:74`). Legacy says `bool`.
- **Preconditions:** either.
- **Threading & blocking:** linear scan under the script-list lock (`:54-72`).
- **Side effects:** mutates the wrapper's private.
- **Game internals:** none.
- **Quirks / bugs:** if the current script was removed, iteration can't continue.

### `D2BSScript.prototype.pause()`

Asks the target to pause at its next operation callback.

- **Native:** `script_pause` at `JSScript.cpp:87`; registered at `JSScript.h:37` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** acts only if `IsRunning()` (`:91`). No NULL check on the private.
- **Threading & blocking:** non-blocking for the caller. `Script::Pause` sets `isPaused`, calls `TriggerOperationCallback` and `SetEvent(eventSignal)` (`Script.cpp:217-222`). The target then spins `Sleep(50)` + `JS_MaybeGC` inside its operation callback until resumed (`ScriptEngine.cpp:304-313`). A target sitting in `delay()` keeps waiting and draining its event queue, because `delay`'s loop never checks `isPaused` (`JSCore.cpp:137-161`). The pause takes effect at the next operation-callback check, when JS next runs: inside the first event listener `delay` dispatches, or after `delay` returns. Pausing yourself takes effect at your own next callback, and only another script can resume you.
- **Side effects:** while paused, the target processes **no events** (its queue keeps filling).
- **Game internals:** none.
- **Quirks / bugs:** none further.

### `D2BSScript.prototype.resume()`

Clears the pause flag.

- **Native:** `script_resume` at `JSScript.cpp:97`; registered at `JSScript.h:38` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** acts only if `IsPaused()` (`:101`).
- **Threading & blocking:** non-blocking (`Script.cpp:233-238`).
- **Side effects:** the target leaves its pause loop within about 50 ms.
- **Game internals:** none.
- **Quirks / bugs:** none.

### `D2BSScript.prototype.stop()`

Aborts the target script.

- **Native:** `script_stop` at `JSScript.cpp:78`; registered at `JSScript.h:39` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** acts only if `IsRunning()` (`:81`), so **a paused script cannot be stopped this way**; resume it first. No NULL check.
- **Threading & blocking:** `Script::Stop(false)` (`Script.cpp:251-280`): returns at once if already aborted, else takes the target's `Script::lock`, sets `isAborted` (and clears `isPaused`), prints `"Script <name> ended"` unless the target is the console (`Command` state, `:260-263`), triggers the callback and signals `eventSignal`. If the caller is another thread, it **polls `hasActiveCX` every 10 ms for up to 500 ms** while holding the lock. Stopping yourself doesn't wait.
- **Side effects:** the target's operation callback returns `false` (uncatchable termination), and then the script is disposed per the cache setting. Stopping the console script is not prevented.
- **Game internals:** none.
- **Quirks / bugs:** a target stuck in native code (`Socket.read`, `join`, `DBStatement.skip`) is not stopped. The caller just waits out the 500 ms.

### `D2BSScript.prototype.join()`

Blocks until the target's thread exits.

- **Native:** `script_join` at `JSScript.cpp:133`; registered at `JSScript.h:40` (declared arity 0, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** none.
- **Returns:** `null`.
- **Preconditions:** none checked (no NULL check, `:135-137`).
- **Threading & blocking:** returns at once if the target has no thread handle (never started, or `CreateThread` failed, `Script.cpp:229`). Otherwise `WaitForSingleObject(threadHandle, INFINITE)` (`Script.cpp:224-231`): **no timeout**, no event processing, and the caller can't be stopped meanwhile. **Joining yourself deadlocks forever.** Joining the console script (which loops forever) hangs.
- **Side effects:** none.
- **Game internals:** none.
- **Quirks / bugs:** with `DisableCache=true` the target closes its own thread handle in `~Script` (`Script.cpp:63-64`) before the thread actually exits, while the joiner is still waiting on that handle (Win32 says behaviour is undefined in that case). Joining a disposed script is use-after-free.

### `D2BSScript.prototype.send(...values)`

Queues a `scriptmsg` event carrying structured-clone copies of the arguments.

- **Native:** `script_send` at `JSScript.cpp:107`; registered at `JSScript.h:41` (declared arity 1, `JSFUN_STUB_GSOPS`).
- **Arguments / overloads:** any number of values. Each is serialised with `JSAutoStructuredCloneBuffer::write(cx, v)` in the **sender's** runtime (`:118-122`), with no custom callbacks, so only clonable data (primitives, plain objects/arrays, Date, RegExp, typed arrays) survives. Functions and D2BS host objects (`Unit`, `File`, hooks, …) can't be cloned, **and the `write` failure is ignored**.
- **Returns:** `null` in every case, including non-delivery (`:108`).
- **Preconditions:** the target must be `IsRunning()` (paused targets are skipped). Otherwise the call silently does nothing, and the pre-allocated `Event` leaks (`:110-112`).
- **Threading & blocking:** non-blocking. Holds the script-list lock during cloning (`:113-128`) and `Vars.cEventSection` while pushing to the front of the target's `EventList` (`:124-126`). Calls `TriggerOperationCallback` but **not `SetEvent(eventSignal)`** (`:127`), so a target blocked in `delay(n)` sees the message only when its wait times out. `scriptBroadcast` does signal it: it delivers through `Script::FireEvent` (`Events.cpp:147-163`), which calls `SetEvent` (`Script.cpp:428`).
- **Side effects / delivery:** on the target's thread, during its operation callback or `delay()` drain, `ExecScriptEvent` reads each buffer into the target's runtime and calls every `scriptmsg` listener with `(...values)` (`ScriptEngine.cpp:709-737`). The `read` result is not checked, so a failed clone leaves an **uninitialised `jsval`** in the argument array (`:713-715`). The `new jsval[]` array is never freed. The message is dropped silently if the target has no listener; `functions[evtName]` also creates an empty entry. Ordering is FIFO per target (push front, pop back). See [events.md `scriptmsg`](events.md#scriptmsg).
- **Game internals:** none.
- **Quirks / bugs:** unlike `scriptBroadcast`, it doesn't check `IsListenerRegistered`. `IsRunning` is checked before taking the lock (a race with disposal). **Re-entrancy under a global lock:** structured-clone `write` reads object properties with ordinary property gets (structured-clone semantics; the engine's clone code isn't in the repo), so a getter on an argument runs user JS while the process-wide script-list lock is held (`:113-122`). If that getter blocks (e.g. calls `delay`), every other thread that needs the list (`ForEachScript`, so all event dispatch) stalls until it returns.

---

## Handle ownership and lifetime summary

| Class | Native resource | Explicit release | Finalizer | Closed at script end? |
|---|---|---|---|---|
| `File` | `FILE*` (+ CRT stream lock if `lockFile`; OS handle with `_SH_SECURE` sharing) | `close()` | yes: unlock + `fclose` (`JSFile.cpp:570-587`) | Only via GC or `JS_DestroyRuntime` in `~Script` (`Script.cpp:53-55`). Until then the file stays open and blocks other writers (read handles) or all other opens (write/append handles). |
| `FileTools` | none on success; `copy` error paths leak `FILE*`s permanently ([FileTools.copy](#filetoolscopysrcpath-dstpath-overwrite)) | n/a | n/a | never closed |
| `Folder` | none (name only) | n/a | deletes `DirData` | n/a. Each `getFiles`/`getFolders` call that matches anything leaks one find handle. |
| `SQLite` | `sqlite3*`, `std::set<DBStmt*>` | `close()` (but `open` stays true) | yes: `clean_sqlite_db` + free (`JSSQLite.cpp:280-288`). After `close()` this is a **second close**. | Same as `File` |
| `DBStatement` | `sqlite3_stmt*`, rooted `current_row` | `close()`, `go()` | yes, but does not unroot `current_row` and does not always erase from `stmts` | Same; dangling-pointer hazards ([DBStatement](#dbstatement)) |
| `Socket` | `SOCKET`, one `WSAStartup` ref | `close()` (not marked closed) | `closesocket` + `WSACleanup` again; `SocketData` leaked | Same; double close / double cleanup |
| `Sandbox` | `JSContext*` | none | `JS_DestroyContext` | n/a (constructor crashes) |
| `D2BSScript` | borrowed `Script*` | none | none | Wrapper may dangle after the target is disposed |

When `~Script` actually runs depends on the dispose path. With `DisableCache=true` (the default, `Helpers.cpp:124`) it runs at the end of the script thread (`Script.cpp:480-481`). With `DisableCache=false` nothing tears the runtime down when the thread ends: `Script::Run` has no cleanup after `main` returns (`Script.cpp:192-211`). So a finished script's `File`, `SQLite` and `Socket` handles stay open, still holding their file-sharing locks and connections, until the script is disposed. Other routes, and the leaks they cause, are in [embedding.md §5.6](../spidermonkey/embedding.md#56-disposal-and-the-jscontext_destroy-path). `JS_DestroyRuntime` is expected to finalize every remaining unrooted object (see Open questions).

---

## Facts relevant to an RPC replacement

(Synthesis lives in [`../rpc-considerations.md`](../rpc-considerations.md). These are the facts from this page.)

- `File`, `FileTools`, `Folder`, `SQLite`/`DBStatement` and `Socket` are **generic host services**: filesystem, embedded DB, TCP client. None of them reads game memory. An out-of-process controller already has these natively, so they don't need RPC equivalents, except where scripts used them to share state *with each other*. In that case the `Vars.cFileSection` serialisation (`writeText`/`appendText` only) and `_wfopen_s` sharing rules ([fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)) are the only coordination that exists today.
- If any file access is kept in-process, keep the **resolve-then-prefix-check** model ([getPathRelScript](#c-helper-getpathrelscript-filecpp220)) and use `isValidPath`'s stricter character rules ([isValidPath](#c-helper-isvalidpath-filecpp258)) consistently. The current code applies three different strengths of check ([path-check matrix](#which-api-uses-which-check)), and `Folder` search patterns and SQLite `:` names bypass it.
- Every utility native is **synchronous on the script thread**. Long or blocking calls (`Socket.read`/`open`, `DBStatement.skip`, `join`, large reads) stop that script's event processing and make it unstoppable until they return. An RPC design should give the controller timeouts and cancellation that don't depend on the script yielding.
- `D2BSScript` is the existing **script-management surface**: list (`getScripts`), identify (`name`/`threadid`/`type`), control (`pause`/`resume`/`stop`/`join`), message (`send`). It relies on raw `Script*` pointers with no lifetime protection. An RPC equivalent needs stable script ids, re-resolved per call (the map key, or the thread id), and explicit "not found" results. Note also that `running` is false for paused scripts and that `stop()` ignores paused scripts.
- Inter-script data crosses runtimes only by **structured clone**, with no host-object support. That is already a value-only "wire format", and it maps directly to JSON or MessagePack payloads. Delivery is asynchronous, FIFO per target, and happens only when the target yields (`delay` or the operation callback).
- Encodings: paths are UTF-16 end to end. File, DB and socket text is UTF-8, decoded with NUL truncation. A replacement should be binary-safe, which none of these APIs are.

---

## Legacy-doc discrepancies

| # | Legacy says | Code does |
|---|---|---|
| 1 | `JSFile.h:34-36`: `lockFile` locks the file "so other threads/programs can't open it" | `_lock_file` is an in-process CRT stream lock (`JSFile.cpp:211-212`); exclusivity against other openers comes from `_wfopen_s` sharing regardless of `lockFile` (read handles keep writers out, write/append handles keep everyone out) |
| 2 | `JSFile.h:40`, `doc/File.h:28-35`: binary `read(n)` returns n bytes | reads n 4-byte ints (`JSFile.cpp:289-295`) |
| 3 | `JSFile.h:41-43`: `readLine`/`readAllLines` throw in binary mode | no mode check (`JSFile.cpp:356-424`) |
| 4 | `JSFile.h:43-44`: `readAll` returns an array in binary mode | always a string (`JSFile.cpp:474-475`) |
| 5 | `JSFile.h:44`: `write` throws if not all parameters could be written; "objects/array-of-bytes" | per-value failures ignored (`JSFile.cpp:486-487`); objects and arrays unsupported (`File.cpp:146-172`) |
| 6 | `JSFile.h:87`, api.html: property `writable` | `writeable` (`JSFile.h:99`) |
| 7 | `doc/File.h:173-175`: `path` is the name given at open | name minus its first character (`JSFile.cpp:84`) |
| 8 | `doc/File.h:110-114`: modes `r`/`w+`/`a+` | `rt`/`w+t`/`a+t` or `rb`/`w+b`/`a+b` (`JSFile.cpp:193`). The 5-argument overload's text (`doc/File.h:130-132`) does mention the `t`/`b` suffix. |
| 9 | `JSFile.h:85-96` lists no `accessed`/`created`/`modified` | defined (`JSFile.h:107-109`), numeric seconds |
| 10 | api.html: `FileTools.remove/rename/copy` return `bool` | return **(unset)** (`JSFileTools.cpp:44-45`, `:66-67`, `:121-124`) |
| 11 | `doc/FileTools.h:21-27`: `copy(orig, newName)` | third `overwrite` parameter exists and is inverted (`JSFileTools.cpp:81-88`) |
| 12 | `doc/FileTools.h:45-61`: writeText/appendText write binary representations for binary files | always text (`JSFileTools.cpp:205`, `:234`) |
| 13 | `doc/Directory.h:10-17`: `create` returns the new sub-folder | returned `Folder` refers to `<root>\name`, not `<this>\name` (`JSDirectory.cpp:186`) |
| 14 | `doc/Directory.h:19-23`: `remove` returns `true` | throws on `ENOTEMPTY`/`ENOENT`, returns `true` on other failures (`JSDirectory.cpp:199-206`) |
| 15 | `doc/Directory.h:25-35`: `getFiles()`/`getFolders()` take no parameter | optional wildcard pattern, default `"*.*"`; more than one argument aborts the script (`JSDirectory.cpp:75-81`, `:123-129`) |
| 16 | `doc/SQLite.h:34-38`: `open()` opens the database | opens but never sets `isOpen` (`JSSQLite.cpp:230-241`) |
| 17 | `doc/SQLite.h:40-44`: `close()` closes | closes but leaves `isOpen` true and the handle reachable (`JSSQLite.cpp:47-57`) |
| 18 | `doc/SQLite.h:58-60`: `lastRowId` int | truncated int32 of an int64 (`JSSQLite.cpp:256`) |
| 19 | `doc/globalFuncs.h:1094-1100`: `sqlite_memusage()` returns double | **(unset)** (`JSSQLite.cpp:72-76`) |
| 20 | `doc/DBStatement.h:21-35`: `getColumnValue` returns double or String | also `null`; BLOB throws (`JSSQLite.cpp:392-415`) |
| 21 | `doc/DBStatement.h:61-67`: `skip(n)` returns rows skipped | never returns for n > 0 (`JSSQLite.cpp:516-528`) |
| 22 | `doc/DBStatement.h:83-121`: `bind(colnum, val)` | also accepts named parameters; `undefined`→NULL; `null` throws (`JSSQLite.cpp:451-488`) |
| 23 | `doc/Sandbox.h`: working sandbox; method `isInclude` | constructor crashes; method `isIncluded`; `include` dead; `clearScope` no-op ([Sandbox](#sandbox)) |
| 24 | `doc/D2BSScript.h:39-45`: `type` int 0/1 | boolean (`JSScript.cpp:32-34`) |
| 25 | `doc/D2BSScript.h:7-11`: `getNext()` returns bool | `true` or `undefined` (`JSScript.cpp:64`, `:74`) |
| 26 | `doc/D2BSScript.h` | no `memory` property documented (`JSScript.h:33`) |
| 27 | `doc/D2BSScript.h:47-49`: `running` = whether the script is running | false while paused (`Script.cpp:340-342`) |
| 28 | `doc/D2BSScript.h:13-32`: `pause`/`resume`/`join`/`stop`/`send` return `void` | all return `null` (`JSScript.cpp:79`, `:88`, `:98`, `:108`, `:134`) |
| 29 | `doc/globalFuncs.h:266-303`: four `getScript` overloads, no `getScripts` | `getScripts()` exists (`JSGlobalFuncs.h:31`). Every `getScript` form returns `null` when nothing matches (`JSScript.cpp:143`) |
| 30 | (none) | `Socket` has no legacy documentation at all |
| 31 | api.html calls the folder class "Directory" | JS class name `Folder` (`JSGlobalClasses.cpp:97`) |

---

## Defects and quirks (summary)

Crash / memory-safety:

- `Sandbox()` passes a NULL runtime to `JS_NewContext` (`JSSandbox.cpp:8`, `ScriptEngine.cpp:19`).
- `DBStatement.getObject()` calls `JS_New(cx, NULL, …)` (`JSSQLite.cpp:325`).
- SQLite string binds are use-after-free (`JSSQLite.cpp:176-178`, `:472-474`).
- `SQLite.close()` leaves the closed handle in use (`JSSQLite.cpp:47-57`).
- `statements` double free (`JSSQLite.cpp:265`).
- `DBStatement.close()`/`go()` leave dangling `stmts` entries (`JSSQLite.cpp:547`, `:581-582`).
- `lastRowId`/`changes` dereference a NULL `sqlite3*` when constructed with `autoOpen = false` (`JSSQLite.cpp:256`, `:273`).
- SQLite error texts are used as `JS_ReportError` format strings, so a `%` in the message is a format-string bug (`JSSQLite.cpp:162`, `:442`, `:500`, `:525`, `:535`, `:109-110`, `:141-144`).
- Unremoved `current_row` root at finalize (`JSSQLite.cpp:583-584`).
- Methods after `DBStatement.close()` dereference NULL (`JSSQLite.cpp:549`).
- `Socket.open(nonString)` / `send(nonString)` NULL crash (`JSSocket.cpp:80`, `:137`).
- `Socket.read` over-read at 10000 bytes (`JSSocket.cpp:152-154`).
- `writeValue` string use-after-free (`File.cpp:73-74`) and `%.16f` buffer overflow → process exit (`File.cpp:103`).
- `FileTools.readText` uses the stream after `fclose` (`JSFileTools.cpp:165-168`).
- `dopen(nonString)` (`JSDirectory.cpp:42`).
- `Folder` methods do no class or NULL check on `this` (`JSDirectory.cpp:80`, `:128`, `:171`, `:194`), and a throwing `toString` on the `getFiles`/`getFolders` pattern dereferences NULL (`:81`, `:129`).
- `File.read(hugeCount)` throws an uncaught `std::bad_alloc` (`JSFile.cpp:289`, `:331`).
- `Sandbox.isIncluded(longName)` overflows `swprintf_s` → process exit (`JSSandbox.cpp:221`).
- `D2BSScript.memory` on an unstarted script (`JSScript.cpp:42`, `Script.cpp:15-17`).
- Dangling `D2BSScript` wrappers after disposal (`JSScript.cpp:19`, `ScriptEngine.cpp:82`).

Hangs:

- `DBStatement.skip(n>0)` (`JSSQLite.cpp:516`).
- `D2BSScript.join()` on self/console (`Script.cpp:230`).
- `Socket.read`/`open` blocking (`JSSocket.cpp:97`, `:107`, `:152`).
- `File.seek(-n, true)` (`JSFile.cpp:524`).

Wrong results:

- Unlocked binary int writes are zeros (`File.cpp:92`).
- Locked `seek` moves twice (`JSFile.cpp:517-519`).
- `File.path` drops its first char (`JSFile.cpp:84`).
- Binary `read` returns uninitialised tail (`JSFile.cpp:290`).
- `FileTools.copy` inverted `overwrite`, and truncates the destination on a missing source (`JSFileTools.cpp:87-95`).
- `Folder.create` returns the wrong folder (`JSDirectory.cpp:186`).
- `SQLite.open()` never sets `isOpen` (`JSSQLite.cpp:233`).
- `sqlite_memusage` returns nothing (`JSSQLite.cpp:73-75`).
- `lastRowId` int32 (`JSSQLite.cpp:256`).
- `Sandbox.include` never runs (`JSSandbox.cpp:196`).
- `D2BSScript.send` doesn't wake a `delay()`ing target (`JSScript.cpp:127`), and runs argument getters while holding the script-list lock (`JSScript.cpp:113-122`).
- Strings written by `File.write`/`writeText`/`appendText`/`Socket.send` are cut at the first U+0000 (`File.cpp:69-71`, `JSSocket.cpp:137`).
- `stop()`/`pause()` ignore paused targets (`JSScript.cpp:81`, `:91`).

Security / sandbox:

- `Folder` search patterns escape the root (`JSDirectory.cpp:81`, `:102`).
- SQLite `:` names bypass validation (`JSSQLite.cpp:91`).
- Host allow-list is a substring match and accepts `""` (`JSSocket.cpp:80`).
- `getPathRelScript` allows NTFS streams and follows reparse points (`File.cpp:243`).
- `Folder.getFiles`/`getFolders` change the process CWD (`JSDirectory.cpp:93`, `:141`).

Leaks:

- Find handles (`JSDirectory.cpp:102`, `:150`).
- `FileTools.copy` error paths leak `FILE*`s with no owner, keeping their sharing locks until process exit (`JSFileTools.cpp:90-108`).
- `new SQLite(p, false)` + `open()`: that connection is never closed (`JSSQLite.cpp:48`, `:232-233`).
- `SocketData` (`JSSocket.cpp:167-173`), the `send` buffer (`JSSocket.cpp:135`), and `WSAStartup` refs on error paths.
- `SQLite` ctor path/handle on errors (`JSSQLite.cpp:92-93`, `:107-111`).
- Sandbox `evaluate` code buffer (`JSSandbox.cpp:178`).
- `send` Event when the target isn't running (`JSScript.cpp:110-112`).
- Interned strings from `Socket.read`/`Folder.name`/`D2BSScript.name`.
- Unbalanced `JS_BeginRequest` in `Socket` getters (`JSSocket.cpp:32`).

Uncatchable aborts (`JS_FALSE` with no exception): `dopen` with an invalid path (`JSDirectory.cpp:46`), `Folder.create` with an invalid path (`:178`), `getFiles`/`getFolders` with `argc > 1` or a chdir failure (`:76`, `:95`), the `Folder.name` getter without a private (`:215`), and the `Sandbox` property hooks (`JSSandbox.cpp:80`, `:104`, `:136`, `:161`).

---

## Open questions

1. **Arguments past `argc`.** Several natives read or write `JS_ARGV(cx,vp)[i]` beyond `argc`: `SQLite` ctor `argv[1]` (`JSSQLite.cpp:102`), `Folder.getFiles/getFolders` writing `argv[0]` (`JSDirectory.cpp:78`, `:126`), `Folder.create` (`:173`), `Socket.send` (`JSSocket.cpp:134`). Whether this mozilla-release-22 build pads the argument vector to the declared `nargs` can't be determined from the headers. The class constructors have `nargs` 0 regardless (`ScriptEngine.cpp:232`).
2. **(unset) return value.** `dependencies/include/js/CallArgs.h:134-143` calls it unspecified. It is probably the callee function object, but this is not verified in the shipped `js_static.lib`.
3. **`JS_New(cx, NULL, …)`** (`JSSQLite.cpp:325`) and **`JS_NewContext(NULL, …)`** (`JSSandbox.cpp:8`) are expected to crash by the JSAPI contract, but the engine source isn't in the repo. Confirm against the binary or by testing.
4. **`JS_ReportError` with `%ls`** (`File.cpp:202`): SpiderMonkey formats with its own printf implementation, and how it handles the `l` modifier on `%s` wasn't checked. The file name in `"Couldn't open file …"` may come out truncated.
5. **`JS_TypeOfValue(null)`**: assumed `JSTYPE_OBJECT` per the "Result of typeof" comment (`dependencies/include/jspubtd.h:93`). If the engine returned `JSTYPE_NULL`, `writeValue(null)` would write 4 zero bytes instead of nothing (`File.cpp:58`).
6. **Finalization at runtime teardown**: assumed that `JS_DestroyRuntime` (`Script.cpp:55`) finalizes every remaining `File`/`SQLite`/`Socket` object. Objects kept alive by leaked roots (e.g. `DBStatement.current_row`) may be skipped, and debug engines report leaked roots. Not verified.
7. **Interned-string lifetime**: assumed pinned until runtime destruction (`JS_InternUCString`). Whether this engine version ever collects interned atoms isn't visible in the headers.
8. **CRT sharing mode.** The `_wfopen_s` sharing behaviour ([fileOpenRelScript](#c-helper-fileopenrelscript-filecpp188)) and the `FileTools.copy` self-copy outcome rest on MSVC's documented `_SH_SECURE` semantics. The CRT source isn't in the repo, so confirm them against the CRT D2BS actually links.
9. **Winsock refcount interaction** with Game.exe's own networking: D2BS's extra `WSACleanup` calls (`JSSocket.cpp:125`, `:171`) affect the process-wide count, but whether and when the game's own Winsock usage depends on that count can't be determined from this repository.

# JS globals: in-game queries and actions (`JSGame.cpp`)

Scope: every global function implemented in `JSGame.cpp` and registered in `global_funcs` (`JSGlobalFuncs.h:24-79`) — 38 globals — plus the `DailogLine` (sic) objects returned by `getDialogLines()` and their per-object `handler` native (`my_clickDialog`). `JSGame.h` also declares `unit_getMercHP` (`JSGame.h:36`), but it is implemented in `JSUnit.cpp:1689` and covered by [unit-methods.md](unit-methods.md). For each callable this documents the exact accepted call shapes, return values on every path, game-state preconditions, thread/lock/blocking behaviour, side effects (game functions called, packets built by D2BS with byte layouts, memory writes) and the D2Ptrs.h identifiers involved. Map/ pathing internals are only described as far as they define `getPath`/`getCollision` semantics; the subsystem itself is in [world.md](world.md). Source of truth is the C++; legacy docs (`doc/globalFuncs.h`, `resources/api.html`, `README.md`) are only cross-checked and every disagreement is called out.

## Contents

- [Conventions and shared mechanics](#conventions-and-shared-mechanics)
- [Summary table](#summary-table)
- [Queries](#queries)
  - [`getUIFlag`](#getuiflagid) · [`getCursorType`](#getcursortypetype) · [`getSkillByName`](#getskillbynamename) · [`getSkillById`](#getskillbyidid) · [`getLocaleString`](#getlocalestringid) · [`getTextSize`](#gettextsizetext-font-asobject) · [`getWaypoint`](#getwaypointindex) · [`getPlayerFlag`](#getplayerflagunitid1-unitid2-flag) · [`getInteractedNPC`](#getinteractednpc) · [`getIsTalkingNPC`](#getistalkingnpc) · [`getDialogLines`](#getdialoglines) · [`getBaseStat`](#getbasestattable-row-column) · [`getTradeInfo`](#gettradeinfomode) · [`getDistance`](#getdistancea-b-c-d) · [`checkCollision`](#checkcollisionunita-unitb-mask) · [`getCollision`](#getcollisionarea-x-y) · [`getPath`](#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) · [`getMouseCoords`](#getmousecoordstomap-asobject)
- [Actions](#actions)
  - [`clickMap`](#clickmaptype-shift-unit--x-y) · [`clickItem`](#clickitemitem--clicktype-bodyloc--clicktype-item--button-x-y-location) · [`clickParty`](#clickpartyparty-mode) · [`acceptTrade`](#accepttrademode) · [`tradeOk`](#tradeok) · [`gold`](#goldamount-mode) · [`say`](#sayvalues) · [`useStatPoint`](#usestatpointstat-count) · [`useSkillPoint`](#useskillpointskill-count) · [`transmute`](#transmute) · [`weaponSwitch`](#weaponswitchquery) · [`submitItem`](#submititem) · [`moveNPC`](#movenpcnpc-x-y) · [`revealLevel`](#reveallevelpresets) · [`takeScreenshot`](#takescreenshot) · [`playSound`](#playsoundid) · [`quit`](#quit) · [`quitGame`](#quitgame)
- [Misc](#misc) — [`rand`](#randlow-high) · [`copyUnit`](#copyunitunit)
- [DailogLine](#dailogline) (class returned by `getDialogLines`)
- [Code tables](#code-tables) — UI flags, PvP flags, locations, body locations, MPQ tables, collision flags
- [Open questions](#open-questions)

Related: [globals-core.md](globals-core.md) (`sendPacket`, `delay`, the *global* `handler()`), [unit-properties.md](unit-properties.md) / [unit-methods.md](unit-methods.md) (Unit objects, `getUnit`, identity), [world.md](world.md) (Map/ pathing, Room, Party), [events.md](events.md), [out-of-game.md](out-of-game.md) (`findControl`), [screenhooks.md](screenhooks.md) (fonts, automap), [../architecture.md](../architecture.md) (threads, `Vars`, `d2bs.ini`), [../spidermonkey/embedding.md](../spidermonkey/embedding.md) (JSNative conventions, rooting, errors), [../memory/offsets.md](../memory/offsets.md), [../memory/structs.md](../memory/structs.md), [../memory/call-stubs.md](../memory/call-stubs.md), [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md).

---

## Conventions and shared mechanics

These facts apply to every entry below; entries reference them by the **bold tag**.

| Tag | Fact | Source |
|---|---|---|
| **Registration** | All 38 globals are `JS_FN(name, native, nargs, FUNCTION_FLAGS)` entries of `global_funcs`, defined on each script's global object by `JS_DefineFunctions` at `ScriptEngine.cpp:345`. `FUNCTION_FLAGS` = `JSFUN_STUB_GSOPS` (`js32.h:134`), which `JS_FN` ORs in again (`dependencies/include/jsapi.h:3062-3063`). Declared `nargs` only sets `.length`. | `JSGlobalFuncs.h:24-79` |
| **Native signature** | `JSAPI_FUNC(name)` = `JSBool name(JSContext* cx, uint argc, jsval* vp)`. | `js32.h:133` |
| **Throws** | `THROW_ERROR(cx, msg)` = `JS_ReportError(cx, msg); return JS_FALSE;` → a catchable JS `Error` with that message. | `js32.h:113-117` |
| **Game not ready** | `THROW_WARNING(cx, vp, "Game not ready")` = `JS_ReportWarning` (printed/logged by `reportError`, `ScriptEngine.cpp:428`) + return value `false` + `JS_TRUE` (not an exception). | `js32.h:118-123` |
| **WaitForGameReady** | Returns `false` immediately if `ClientState()` is `ClientStateNull` or `ClientStateMenu`; `true` if `ClientStateInGame`; while `ClientStateBusy` polls every 10 ms (`Sleep(10)`) for up to `Vars.dwGameTimeout` ms (`GameReadyTimeout` in d2bs.ini, default 5 → 5000 ms; 0 = wait forever). `ClientState()`: player unit present and `*p_D2WIN_FirstControl == NULL` with player `pInventory`, `pPath->pRoom1->pRoom2->pLevel->dwLevelNo` all set → InGame; player with `pUpdateUnit` or incomplete path → Busy; no player + a control → Menu; player and a control both present, or neither → Null. | `D2Helpers.cpp:125-147`, `D2Helpers.cpp:153-166`, `Helpers.cpp:127`, `Helpers.cpp:144` |
| **callee-return** | Some paths return `JS_TRUE` without `JS_SET_RVAL`. `JS_RVAL` and `JS_CALLEE` are the same slot `vp[0]` (`dependencies/include/js/CallArgs.h:317-321`), so such a call evaluates to **the native function object itself** (truthy), not `undefined`. | `dependencies/include/js/CallArgs.h:317-321` |
| **argv over-read** | Several natives read `JS_ARGV(cx,vp)[i]` for `i >= argc`. JSAPI only defines `vp[2 .. 2+argc-1]`. Whether the engine pads up to the declared `nargs` cannot be determined from the headers in `dependencies/include/` (see [embedding.md](../spidermonkey/embedding.md), which states it pads up to `nargs`). Every over-read in this file is at an index ≥ the declared `nargs` anyway, except `getMouseCoords`' `argv[0]`. So even with padding these reads hit an undefined slot (stale stack contents). | `dependencies/include/js/CallArgs.h:317-321` |
| **Int tag tests** | `JSVAL_IS_INT` is a tag test: integral values stored as doubles fail it. `JSVAL_TO_INT`/`JSVAL_TO_BOOLEAN` are unchecked bit extractions (a double passed where an int is extracted yields garbage). | — |
| **Object test** | `JSVAL_IS_OBJECT` is overridden as `!JSVAL_IS_PRIMITIVE(v)` (so `null` is *not* an object, unlike stock 1.8.5). | `js32.cpp:62-64` |
| **Private without class check** | `JS_GetPrivate(cx,obj)` wraps `JS_GetPrivate(obj)` with no class check (`js32.cpp:65-67`). Any object is accepted where a Unit/Party is expected; its private struct is reinterpreted. Objects whose class has no private slot give undefined behaviour. | `js32.cpp:65-67` |
| **Malformed bool** | `BOOLEAN_TO_JSVAL(b)` only asserts `b ∈ {0,1}` in debug builds (`dependencies/include/js/Value.h:438-444`); natives that pass a raw game `DWORD` can produce a boolean whose payload is ≠ 1 (truthy, but `=== true` may be false). | `dependencies/include/js/Value.h:438-444` |
| **ConvertArguments** | `JS_ConvertArguments` format chars (`dependencies/include/jsapi.h:1480-1511`): `u` = ECMA ToUint32, `i` = ToInt32, `c` = ToUint16, `/` = rest optional. Missing required args → `TypeError` "*name* requires more than *N* argument(s)" (`dependencies/include/js.msg:56`). Coercions never fail for primitives. | `dependencies/include/jsapi.h:1480-1511` |
| **Unit argument** | Unit objects carry a `myUnit` (`JSUnit.h:44-51`) or `invUnit` (`JSUnit.h:53-62`) snapshot: `{_dwPrivateType, dwUnitId, dwClassId, dwType, dwMode, szName[128] (+dwOwnerId, dwOwnerType)}`. Natives test `(_dwPrivateType & PRIVATE_UNIT) == PRIVATE_UNIT`; with `PRIVATE_UNIT=1`, `PRIVATE_ITEM=3` (`D2BS.h:22-23`) items pass. The live `UnitAny*` is re-resolved with `D2CLIENT_FindUnit(id,type)` = `FindServerSideUnit` then `FindClientSideUnit` (`D2Helpers.cpp:500-505`). Details: [unit-properties.md](unit-properties.md). | `D2Helpers.cpp:500-505` |
| **Game-loop lock** | `AutoCriticalRoom` (heap-allocated with `new`, released on `delete`) enters `Vars.cGameLoopSection`, a Win32 `CRITICAL_SECTION` (`CriticalSections.h:31-55`, `D2BS.h:117`). It is recursive for the owning thread, so nested acquisition (e.g. `GetLevel` inside `getPath`) does not deadlock, but one release does not free a section entered twice. A leaked `AutoCriticalRoom` keeps the section owned, even after the owning script thread exits, and the game thread then blocks forever at its next re-enter. The game thread holds that section while running and yields it only inside `GameDraw` when `Vars.SectionCount>0` (`D2Handlers.cpp:410-417`) and in `TimerProc` (`D2Handlers.cpp:493-504`). Acquiring therefore waits for the next game-thread yield; while held, the game loop is frozen. Natives without this lock call game code concurrently with the game thread. See [architecture.md](../architecture.md). | `CriticalSections.h:31-55` |
| **Thread** | Unless stated otherwise every native runs synchronously on the thread executing the calling script (each script has its own thread, `Script.cpp:108`, and its own `JSRuntime`/`JSContext`, `Script.cpp:120-125`), so blocking inside a native stalls only that script plus whatever waits on the game-loop lock. | `Script.cpp:108-125` |
| **Packet paths** | D2BS-built packets go out through either `D2NET_SendPacket(len, 1, buf)` (FUNCPTR, RVA `0x12AE50`, `D2Ptrs.h:362`; raw net send) or `D2CLIENT_SendGamePacket(len, buf)` (macro, `D2Ptrs.h:505`) → `D2CLIENT_SendGamePacket_ASM` (`D2Helpers.cpp:955-965`) → `SendGamePacket_I` (RVA `0x78350`, `D2Ptrs.h:283`). Neither path takes a lock; `D2NET_CriticalPacketSection` is declared "unused" (`D2Ptrs.h:370`). All packet bytes below are client→server, little-endian. | `D2Ptrs.h:362`, `D2Ptrs.h:283` |

D2Ptrs.h offsets are RVAs inside Game.exe (`GetDllOffset` ignores the legacy DLL name); see [../memory/README.md](../memory/README.md) and [../memory/offsets.md](../memory/offsets.md).

---

## Summary table

| Function | Native (`JSGame.cpp`) | nargs | Requires | Lock | Blocks / waits | Normal return |
|---|---|---|---|---|---|---|
| `getUIFlag` | `my_getUIFlag` :975 | 1 | in game | – | WaitForGameReady | bool (raw DWORD) |
| `getCursorType` | `my_getCursorType` :851 | 0 | – | – | – | int |
| `getSkillByName` | `my_getSkillByName` :862 | 1 | – | – | – | **broken**: throws for any non-empty string |
| `getSkillById` | `my_getSkillById` :881 | 1 | data tables | – | – | string |
| `getLocaleString` | `my_getLocaleString` :663 | 1 | – | – | – | string |
| `getTextSize` | `my_getTextSize` :900 | 2 | – | – | – | `[w,h]` / `{width,height}` |
| `getWaypoint` | `my_getWaypoint` :990 | 1 | in game | – | WaitForGameReady | bool |
| `getPlayerFlag` | `my_getPlayerFlag` :1275 | 2 | in game | – | WaitForGameReady | bool (raw DWORD) |
| `getInteractedNPC` | `my_getInteractedNPC` :1386 | 0 | in game | – | WaitForGameReady | Unit / `false` |
| `getIsTalkingNPC` | `my_getIsTalkingNPC` :1378 | 0 | in game | – | WaitForGameReady ×2 | bool |
| `getDialogLines` | `my_getDialogLines` :170 | 0 | – | game-loop | lock wait | `DailogLine[]` / `undefined` |
| `getBaseStat` | `my_getBaseStat` :1175 | 0 | data tables | – | – | number / string / `undefined` / garbage |
| `getTradeInfo` | `my_getTradeInfo` :938 | 0 | in game | – | WaitForGameReady | int / null / false |
| `getDistance` | `my_getDistance` :714 | 2 | in game | – | WaitForGameReady | number |
| `checkCollision` | `my_checkCollision` :826 | 2 | in game | – | WaitForGameReady | int |
| `getCollision` | `my_getCollision` :324 | 0 | in game | game-loop | lock wait | int |
| `getPath` | `my_getPath` :229 | 0 | in game | game-loop (whole search) | A* search, JS callbacks | `{x,y}[]` |
| `getMouseCoords` | `my_getMouseCoords` :1296 | 1 | – | – | – | `[x,y]` / `{x,y}` |
| `clickMap` | `my_clickMap` :63 | 3 | in game | – | WaitForGameReady | bool |
| `clickItem` | `my_clickItem` :357 | 0 | in game | game-loop | lock wait | true / false / null |
| `clickParty` | `my_clickParty` :1074 | 1 | in game | – | WaitForGameReady | bool |
| `acceptTrade` | `my_acceptTrade` :106 | 0 | in game | game-loop (action) | lock wait | bool / int |
| `tradeOk` | `my_tradeOk` :147 | 0 | in game | game-loop | lock wait | callee-return / throws |
| `gold` | `my_gold` :809 | 1 | in game | – | WaitForGameReady | callee-return |
| `say` | `my_say` :1044 | 1 | – | – | – | `true` |
| `useStatPoint` | `my_useStatPoint` :1143 | 1 | in game | – | `Sleep(500)` × (count−1) | callee-return |
| `useSkillPoint` | `my_useSkillPoint` :1159 | 1 | in game | – | `Sleep(500)` × (count−1) | callee-return |
| `transmute` | `my_transmute` :1258 | 0 | in game | – | WaitForGameReady | `null` |
| `weaponSwitch` | `my_weaponSwitch` :1223 | 0 | in game | – | WaitForGameReady | bool / int |
| `submitItem` | `my_submitItem` :1344 | 0 | in game | – | WaitForGameReady | bool |
| `moveNPC` | `my_moveNPC` :1421 | 0 | in game + EnableUnsupported | – | WaitForGameReady ×2 | bool |
| `revealLevel` | `my_revealLevel` :1456 | 0 | in game | game-loop | lock wait | callee-return |
| `takeScreenshot` | `my_takeScreenshot` :1416 | 0 | – | – | async (next draw) | callee-return |
| `playSound` | `my_playSound` :1030 | 1 | – | – | – | bool (no-op) |
| `quit` | `my_quit` :1021 | 0 | – | – | – | `false` |
| `quitGame` | `my_quitGame` :1009 | 0 | – | – | `Shutdown()` waits | never returns |
| `rand` | `my_rand` :677 | 0 | – | – | – | int |
| `copyUnit` | `my_copyUnit` :19 | 1 | – | – | – | Unit / `undefined` |
| *(DailogLine)* `.handler` | `my_clickDialog` :213 | 0 | – | – | – | `true` / throws |

---

## Queries

### `getUIFlag(id)`

Returns whether the client UI variable `id` is set (whether a given panel/screen is open).

- **Native:** `my_getUIFlag` at `JSGame.cpp:975`; registered at `JSGlobalFuncs.h:29` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `id` must pass `JSVAL_IS_INT`; `argc < 1` or non-int → returns `undefined` explicitly (`JSGame.cpp:976-979`). No range check on `id` (any int32 is forwarded). Values: [UI flags table](#ui-flags-getuiflag).
- **Returns:** `BOOLEAN_TO_JSVAL(D2CLIENT_GetUIState(id))` (`JSGame.cpp:985`) — the raw DWORD of the UI var (**Malformed bool** if the var holds a value other than 0/1). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:981-982`, checked *after* the argument test).
- **Threading & blocking:** script thread; no lock; may wait up to `GameReadyTimeout` while loading.
- **Side effects:** none.
- **Game internals:** `D2CLIENT_GetUIState(x)` macro → `D2CLIENT_GetUIVar_STUB` (`D2Ptrs.h:493`, `D2Helpers.cpp:720-726`: `mov eax, ecx; jmp D2CLIENT_GetUiVar_I`) → `D2CLIENT_GetUiVar_I` (FUNCPTR, RVA `0x538D0`, `D2Ptrs.h:116`).
- **Quirks / bugs:** out-of-range ids read past the game's UI-var array (no validation). Legacy docs: `resources/api.html` (getUIFlag tiddler) numbers flags differently from `Constants.h` from value 9 upward (e.g. api.html "27 - Cube screen" vs `UI_CUBE 0x1A`=26, which the code itself uses in `transmute`); the code has no table, `Constants.h:15-54` is the only in-source list.

### `getCursorType([type])`

Returns the client's regular or shop cursor-type global.

- **Native:** `my_getCursorType` at `JSGame.cpp:851`; registered at `JSGlobalFuncs.h:26` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `getCursorType()` → regular cursor type; `getCursorType(type)`: `nType = JSVAL_TO_INT(argv[0])` with **no type check** (`JSGame.cpp:854-855`); `nType == 1` → shop cursor type, anything else → regular. `true` works as 1 by payload coincidence; a double gives garbage.
- **Returns:** int: `*p_D2CLIENT_ShopCursorType` if `nType==1`, else `*p_D2CLIENT_RegularCursorType` (`JSGame.cpp:857`). Value meanings are not defined anywhere in source (no cursor constants in `Constants.h`).
- **Preconditions:** none checked — reads the globals in any client state.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** none.
- **Game internals:** `p_D2CLIENT_RegularCursorType` (VARPTR DWORD, RVA `0x3A6AF0`, `D2Ptrs.h:178`), `p_D2CLIENT_ShopCursorType` (VARPTR DWORD, RVA `0x3BCBF0`, `D2Ptrs.h:179`).
- **Quirks / bugs:** legacy docs (`doc/globalFuncs.h:138-152`, api.html) also leave values undocumented.

### `getSkillByName(name)`

Intended to map an English skill name to a skill id via the static `Game_Skills` table; as written it never succeeds.

- **Native:** `my_getSkillByName` at `JSGame.cpp:862`; registered at `JSGlobalFuncs.h:27` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `name` must pass `JSVAL_IS_STRING`; `argc < 1` or non-string → **callee-return** (`JSGame.cpp:863-864`). String is UTF-8 encoded with `JS_EncodeStringToUTF8`.
- **Returns:** the check `if (!lpszText || lpszText[0]) THROW_ERROR(cx, "Could not convert string")` (`JSGame.cpp:867-868`) throws **for every non-empty string**. For `""` the loop over `Game_Skills` (218 entries, `D2Skills.h:11`) finds nothing (`_strcmpi`) → **callee-return**. The intended path (`INT_TO_JSVAL(Game_Skills[i].skillID)`, `JSGame.cpp:872`) is unreachable.
- **Preconditions:** none (static table, `D2Skills.h`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** leaks the `JS_EncodeStringToUTF8` buffer on the throw path (`JS_free` at `JSGame.cpp:877` is skipped).
- **Game internals:** none (`Game_Skills` is a D2BS-compiled table, `D2Skills.h:11`; the C helper `GetSkillByName` in `D2Helpers.cpp:291-296` is not used here. It is the working name lookup used by `unit_setskill` (`JSUnit.cpp:1709`, lookup at `JSUnit.cpp:1723`; see [unit-methods.md](unit-methods.md)), but it iterates only 216 of the 218 entries, so the last two skills are never found).
- **Quirks / bugs:** inverted condition at `JSGame.cpp:867` (should be `!lpszText[0]`). Legacy docs: api.html example `getSkillByName('kick')` — code throws.

### `getSkillById(id)`

Returns the localized skill name for a skill id via the MPQ `skills` → `skilldesc` → locale string chain.

- **Native:** `my_getSkillById` at `JSGame.cpp:881`; registered at `JSGlobalFuncs.h:27` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `id` must pass `JSVAL_IS_INT`; `argc < 1` or non-int → **callee-return** (`JSGame.cpp:882-883`).
- **Returns:** string. Starts as `"Unknown"` (`JSGame.cpp:887`); if `FillBaseStat("skills", id, "skilldesc", &row, 4)` and `FillBaseStat("skilldesc", row, "str name", &row, 4)` both succeed, `D2LANG_GetLocaleText((WORD)row)` (`JSGame.cpp:890-894`). Out-of-range or negative ids → `"Unknown"` (row bound check in `GetBaseTable`, `MPQStats.cpp:58`).
- **Preconditions:** no game-state check; requires the game's data tables (`*p_D2COMMON_sgptDataTable`) to be loaded (see [Open questions](#open-questions)).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `skills.skilldesc` = `FIELDTYPE_NAME_TO_WORD` @ `0x194` (`MPQStats.h:742`); `skilldesc."str name"` = `FIELDTYPE_KEY_TO_WORD` @ `0x8` (`MPQStats.h:512`); 2-byte reads into an `int` initialised to 0. Table access via `GetBaseTable` (`MPQStats.cpp:34-66`, see [`getBaseStat`](#getbasestattable-row-column)); `D2LANG_GetLocaleText` (FUNCPTR fastcall, RVA `0x124A30`, `D2Ptrs.h:418`).
- **Quirks / bugs:** Legacy docs: api.html says it uses "the internal table"; code uses MPQ data + locale (so it returns the client-language name).

### `getLocaleString(id)`

Returns the string with locale index `id` from the client's string tables.

- **Native:** `my_getLocaleString` at `JSGame.cpp:663`; registered at `JSGlobalFuncs.h:28` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `id` must pass `JSVAL_IS_INT`; `argc < 1` or non-int → **callee-return** (`JSGame.cpp:664-665`). Converted with `JS_ValueToUint16` (ECMA ToUint16, i.e. modulo 65536; negative ids wrap).
- **Returns:** `JS_NewUCStringCopyZ(cx, D2LANG_GetLocaleText(id))` (`JSGame.cpp:670-671`). What the game returns for unknown ids is not determined by D2BS source.
- **Preconditions:** none checked.
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `D2LANG_GetLocaleText` (FUNCPTR `wchar_t* __fastcall(WORD)`, RVA `0x124A30`, `D2Ptrs.h:418`).
- **Quirks / bugs:** none beyond callee-return on bad input.

### `getTextSize(text, font[, asObject])`

Measures a string in a D2 font.

- **Native:** `my_getTextSize` at `JSGame.cpp:900`; registered at `JSGlobalFuncs.h:28` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `text` must be a string (`JSVAL_IS_STRING`), `font` an int (`JSVAL_IS_INT`); otherwise returns `false` (`JSGame.cpp:901-904`). Optional `asObject`: only a boolean `true` selects object form (`JSGame.cpp:915`). Font ids are passed straight to `D2WIN_SetTextSize` (no validation; see [screenhooks.md](screenhooks.md)).
- **Returns:** default `[width, height]` (Array); with `asObject === true` a plain object `{width, height}`. `width` = `dwWidth` out-param of `D2WIN_GetTextSize`, `height` = its return value (`D2Helpers.cpp:219-221`). Throws "Could not convert string", "Could not build object", "Could not set width property", "Could not set height property" on JSAPI failures.
- **Preconditions:** none (works in and out of game).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** temporarily changes the global D2Win font: `old = D2WIN_SetTextSize(font)` … `D2WIN_SetTextSize(old)` (`D2Helpers.cpp:212-225`) — unsynchronised with the game thread, which may be drawing text concurrently.
- **Game internals:** `CalculateTextLen(const wchar_t*, int)` (`D2Helpers.cpp:212`), `D2WIN_SetTextSize` (RVA `0x102EF0`, `D2Ptrs.h:447`), `D2WIN_GetTextSize` (RVA `0x102520`, `D2Ptrs.h:446`).
- **Quirks / bugs:** `JS_AddRoot(cx, &pObj)` (`JSGame.cpp:920`, `928`) registers the *address of a stack local* as a GC root. If a later `THROW_ERROR` fires (`JSGame.cpp:922`, `924`), `JS_RemoveRoot` (`JSGame.cpp:934`) is skipped. The runtime then keeps a dangling root into a dead stack frame, and later GCs read whatever occupies that slot. The array path does not NULL-check `JS_NewArrayObject` (`JSGame.cpp:927`). Legacy docs: api.html documents this as `getTextWidthHeight(text[, returnObject])` (old name, no font argument).

### `getWaypoint(index)`

Returns whether the player has waypoint number `index`.

- **Native:** `my_getWaypoint` at `JSGame.cpp:990`; registered at `JSGlobalFuncs.h:30` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `index` must pass `JSVAL_IS_INT`, else `false` (`JSGame.cpp:991-994`). `index > 40` is silently replaced by 0 (`JSGame.cpp:1001-1002`); negative values are passed through.
- **Returns:** `!!D2COMMON_CheckWaypoint(*p_D2CLIENT_WaypointTable, index)` as a proper boolean (`JSGame.cpp:1004`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:996-997`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `p_D2CLIENT_WaypointTable` (VARPTR DWORD, RVA `0x3BF081`, `D2Ptrs.h:200`; its value is passed as the table argument), `D2COMMON_CheckWaypoint` (stdcall, RVA `0x260E50`, `D2Ptrs.h:336`).
- **Quirks / bugs:** `getWaypoint(41+)` reports waypoint 0 (Rogue Encampment) instead of failing. Legacy docs: `doc/globalFuncs.h:257-264` says the argument is "the area id of the waypoint"; code (and api.html) treat it as the waypoint index (0-40). api.html also says a waypoint must have been interacted with first (table is filled by the server; not verifiable from source).

### `getPlayerFlag(unitId1, unitId2, flag)`

Tests a PvP/party relationship flag between two player unit ids.

- **Native:** `my_getPlayerFlag` at `JSGame.cpp:1275`; registered at `JSGlobalFuncs.h:35` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:** exactly 3 arguments, all `JSVAL_IS_NUMBER`; anything else → **callee-return** (`JSGame.cpp:1276-1277`). Ids converted with `JS_ValueToECMAUint32`; `flag` with unchecked `JSVAL_TO_INT` (a double flag yields garbage) (`JSGame.cpp:1285-1289`). Flag values: [PvP flags](#pvp-flags-getplayerflag).
- **Returns:** `BOOLEAN_TO_JSVAL(D2CLIENT_TestPvpFlag(id1, id2, flag))` (`JSGame.cpp:1291`) — raw DWORD (**Malformed bool** if the game returns the masked bit rather than 0/1). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1279-1280`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `D2CLIENT_TestPvpFlag` (FUNCPTR `DWORD __fastcall(DWORD,DWORD,DWORD)`, RVA `0xDC440`, `D2Ptrs.h:130`); an older register stub is commented out (`D2Helpers.cpp:905-917`).
- **Quirks / bugs:** declared arity 2 but exactly 3 required. Legacy docs (`doc/globalFuncs.h:733-748`) list the flags as "to determine"; `Constants.h:125-129` has them.

### `getInteractedNPC()`

Returns a Unit object for the NPC the player is currently interacting with.

- **Native:** `my_getInteractedNPC` at `JSGame.cpp:1386`; registered at `JSGlobalFuncs.h:36` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** a new `Unit` object (`unit_class`, built with `unit_methods`/`unit_props`, `JSGame.cpp:1408`) whose `myUnit` holds `_dwPrivateType=PRIVATE_UNIT`, `dwClassId=pNPC->dwTxtFileNo`, `dwMode`, `dwType`, `dwUnitId`, `szName=""` (`JSGame.cpp:1401-1406`); `false` if `D2CLIENT_GetCurrentInteractingNPC()` returns NULL (`JSGame.cpp:1391-1393`); **callee-return** on allocation/`BuildObject` failure; `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1387-1388`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** allocates a `myUnit`, owned by the new object and freed by `unit_finalize` (`JSUnit.cpp:13-28`) — the "leaked?" comment at `JSGame.cpp:1396` is wrong except when `BuildObject` fails.
- **Game internals:** `D2CLIENT_GetCurrentInteractingNPC` (FUNCPTR fastcall, RVA `0xB1620`, `D2Ptrs.h:69`); `UnitAny` fields `dwType/dwTxtFileNo/dwUnitId/dwMode` (`D2Structs.h:605-610`).
- **Quirks / bugs:** the returned unit is an id/type snapshot like any Unit (re-resolved on property access, see [unit-properties.md](unit-properties.md)). Legacy docs: api.html says `undefined` when not interacting; code returns `false`.

### `getIsTalkingNPC()`

Returns whether an NPC's scrolling speech text is currently on screen.

- **Native:** `my_getIsTalkingNPC` at `JSGame.cpp:1378`; registered at `JSGlobalFuncs.h:37` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `BOOLEAN_TO_JSVAL(IsScrollingText())` (proper bool). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady** in the native, `JSGame.cpp:1379-1380`, and again inside `IsScrollingText`, `D2Helpers.cpp:1000-1001`).
- **Threading & blocking:** script thread; no lock; up to two `GameReadyTimeout` waits.
- **Side effects:** none (read-only walk of Storm's window-message handler hash, unsynchronised with the game thread).
- **Game internals:** `IsScrollingText` (`D2Helpers.cpp:998-1029`): bucket `p_STORM_WindowHandlers->table[(0x534D5347 ^ hwnd) % length]` (`'SMSG'` key; VARPTR `WindowHandlerHashTable`, RVA `0x379300`, `D2Ptrs.h:473`), entries with `unk_0 == 0x534D5347 && hWnd == D2GFX_GetHwnd()`; in its `msgHandlers` table bucket `0x201 % length` (WM_LBUTTONDOWN) looks for a `MessageHandlerList` with `message != 0`, `unk_4 < 0xFFFFFFFF` and `handler == D2CLIENT_CloseNPCTalk` (RVA `0xA17D0`, `D2Ptrs.h:128`). Structs: `D2Structs.h:757-780`.
- **Quirks / bugs:** `% p_STORM_WindowHandlers->length` is taken without a zero check (`D2Helpers.cpp:1004`); a 0-length table would fault (integer divide by zero). The match criterion (a `CloseNPCTalk` handler registered for `WM_LBUTTONDOWN`) is a heuristic from the source, not a game flag. No legacy documentation exists for this function.

### `getDialogLines()`

Returns the lines of the currently open NPC transaction/dialog menu as `DailogLine` objects.

- **Native:** `my_getDialogLines` at `JSGame.cpp:170`; registered at `JSGlobalFuncs.h:37` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `undefined` if `*p_D2CLIENT_pTransactionDialogsInfo == NULL` (`JSGame.cpp:171`, `183`); otherwise an Array of `numLines` [DailogLine](#dailogline) objects, each with own properties `text` (string copy of `dialogLines[i].text`), `selectable` (`BOOLEAN_TO_JSVAL(bMaybeSelectable)`, **Malformed bool** risk) and `handler` (native function) (`JSGame.cpp:187-206`).
- **Preconditions:** none — no WaitForGameReady; reads the pointer in any state.
- **Threading & blocking:** script thread; holds the **Game-loop lock** for the whole build (`JSGame.cpp:181`, `210`), so it waits for the next game-thread yield.
- **Side effects:** each line's reserved slot 0 stores a raw pointer `&pTdi->dialogLines[i]` into game memory (`JSGame.cpp:200`). Creates one unused plain object per line (`jso_addr`, `JSGame.cpp:196`, dead code).
- **Game internals:** `p_D2CLIENT_pTransactionDialogsInfo` (VARPTR `TransactionDialogsInfo_t*`, RVA `0x3C0E54`, `D2Ptrs.h:196`); `TransactionDialogsInfo_t{numLines@0x50, dialogLines[10]@0x68}` and `TransactionDialogsLine_t{text[120]@0, handler@0x108, bMaybeSelectable@0x10C}` (`D2Structs.h:785-798`, line stride 0x110).
- **Quirks / bugs:** `numLines` is not clamped to the 10-element array (`JSGame.cpp:187`); `text[120]` is assumed NUL-terminated. The `BuildObject` result is not NULL-checked before `JS_SetProperty` (`JSGame.cpp:191-193`). The source itself says the placement of `handler` and of the line struct inside the game's dialog info is a guess (`D2Structs.h:782-784`). Legacy docs (`doc/globalFuncs.h:1490-1501`) document only `text`/`selectable`, not `handler`.

### `getBaseStat(table, row, column)`

Reads one cell of a game data (.txt/.bin) table from memory.

- **Native:** `my_getBaseStat` at `JSGame.cpp:1175`; registered at `JSGlobalFuncs.h:34` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** requires `argc > 2`, else **callee-return** (`JSGame.cpp:1176`).
  - `table`: string → case-insensitive (`_strcmpi`) match against `BaseStatTable[i].szTableName`; number → index (`JS_ValueToECMAInt32`); else throws "Invalid table value" (`JSGame.cpp:1182-1193`).
  - `row`: any value, `JS_ValueToECMAInt32` (result unchecked) (`JSGame.cpp:1195`).
  - `column`: string → case-insensitive match against the table's `BinField.szFieldName`; number → field index; else throws "Invalid column value" (`JSGame.cpp:1197-1210`).
- **Lookup mechanism** (`FillBaseStat(JSContext*, jsval*, …)`, `MPQStats.cpp:175-286`, and `GetBaseTable`, `MPQStats.cpp:34-66`):
  1. Table descriptor `MPQTable{dwEntry, dwMaxEntriesOffset, BinField* pTable, szTableName[15], wTableSize}` from `BaseStatTable[]` (`MPQStats.cpp:4-32`, struct `MPQStats.h:47-54`). [Table list](#mpq-tables-getbasestat).
  2. Base pointer: if `dwEntry <= 0xFFFF` it is an offset into the struct pointed to by `*p_D2COMMON_sgptDataTable` (VARPTR, RVA `0x344304`, `D2Ptrs.h:349`); otherwise it is an absolute 0x400000-based VA rebased with `d2CommonOff = GetModuleHandle(NULL)` (`MPQStats.h:10`, `MPQStats.cpp:41-46`). The DWORD there is the pointer to the record array.
  3. Row count: DWORD at `dwMaxEntriesOffset` (same addressing); `0` means "assume 0xFF rows" (`MPQStats.cpp:52-56`). `(DWORD)row < count` required, else the cell read fails.
  4. Record size = `dwFieldOffset` of the table's last `BinField` (the `"end"` sentinel) (`MPQStats.cpp:59`); record address = `array + row * size`.
  5. Field: `BinField{szFieldName[64], eFieldType, dwFieldLength, dwFieldOffset}` (`MPQStats.h:40-45`); the per-table field arrays (`itemTable` … `superuniquesTable`) are in `MPQStats.h:65-2124`.
- **Returns** (by `eFieldType`, `MPQStats.cpp:212-285`):

  | Field type(s) | Read | JS result |
  |---|---|---|
  | `DATA_ASCII` | `dwFieldLength` bytes | string |
  | `DATA_DWORD` | 4 bytes | number (unsigned) |
  | `CALC_TO_DWORD`, `NAME_TO_DWORD`, `DATA_DWORD_2`, `UNKNOWN_11` | 4 bytes | number (signed, via `(long)`) |
  | `NAME_TO_INDEX(_2)`, `NAME_TO_WORD(_2)`, `KEY_TO_WORD`, `DATA_WORD`, `CODE_TO_WORD` | 2 bytes | int 0..65535 |
  | `CODE_TO_BYTE`, `DATA_BYTE`, `DATA_BYTE_2` | `min(nextField.offset − offset, 4)` bytes | int |
  | `DATA_BIT` | 4 bytes, then `(v >> dwFieldLength) & 1` | int 0/1 |
  | `ASCII_TO_CODE`, `DATA_RAW` | 4 bytes | string (≤4 chars, stops at NUL) |
  | row out of range (`(DWORD)row >= count`), or computed record address 0 | — | `undefined` (a NULL table pointer with row > 0, or NULL `sgptDataTable`, instead dereferences a near-NULL address) |
  | table or column name not found, `column > wTableSize`, the `"end"` column, `MONSTER_COMPS` | — | **uninitialised `jsval`** (see bugs) |
- **Preconditions:** no game-state check; requires data tables loaded (see [Open questions](#open-questions)).
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** none (read-only).
- **Game internals:** `p_D2COMMON_sgptDataTable` (`D2Ptrs.h:349`); hard-coded absolute VAs in `BaseStatTable` (`0x8426F0`, `0x96D470`, `0x96CA08`, … `MPQStats.cpp:6-31`) are not in D2Ptrs.h — see [../memory/offsets.md](../memory/offsets.md).
- **Quirks / bugs:**
  - `jsval rval;` is uninitialised (`JSGame.cpp:1211`; `JS::Value` has no default initialiser, `dependencies/include/js/Value.h:860-863`) and `FillBaseStat` returns early without writing it for unknown table/column names (`MPQStats.cpp:184-185`, `198-199`), `column > wTableSize` (`MPQStats.cpp:202-203`) and unhandled types (`FIELDTYPE_END`, `MONSTER_COMPS`, `MPQStats.cpp:281-285`) → the script receives stack garbage (possible crash/GC corruption). In `MPQStats.h` the only field type that reaches this path is `FIELDTYPE_END`, the `"end"` sentinel of each table. No field is declared `MONSTER_COMPS` or any `UNKNOWN_*` type except `UNKNOWN_11`, which is handled.
  - Numeric `table` is never bounds-checked: `BaseStatTable[table].pTable` is dereferenced directly (`MPQStats.cpp:188`); index 26 is the `{0}` terminator (NULL `pTable`); the only "check" `table < sizeof(BaseStatTable)` compares against the byte size (`MPQStats.cpp:38`).
  - Column check is `>` instead of `>=` and negative numeric columns are not rejected (`MPQStats.cpp:202`): `pTable[column]`/`pTable[column+1]` read past the static arrays.
  - Byte-type width is derived from the next field's offset: 103 of the 662 byte-typed fields are followed by a gap of 2-4 bytes and are read as 16-32-bit little-endian values, correct only if the padding is zero (computed from `MPQStats.h`, e.g. `skills.charclass`, `objects.TrapProb`).
  - `NAME_TO_INDEX_2`/`NAME_TO_WORD_2` sign fix-up casts the *pointer* `result` to `WORD` (`MPQStats.cpp:142-143`) — dead/incorrect logic (JS path then returns the unsigned 16-bit value).
  - Legacy docs: api.html lists table 24 as `pettype`; the name string the code matches is `"pettable"` (`MPQStats.cpp:30`). `doc/globalFuncs.h:440-708` documents 16 return-type overloads with "\todo Determine what these tables are".

### `getTradeInfo(mode)`

Returns the client's recent trade state id.

- **Native:** `my_getTradeInfo` at `JSGame.cpp:938`; registered at `JSGlobalFuncs.h:30` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc < 1` → `false` (checked before game state, `JSGame.cpp:942-943`); non-int `mode` → `false` (`JSGame.cpp:948-949`).
- **Returns:** `mode 0` → int `*p_D2CLIENT_RecentTradeId`; `mode 1` → `null` (name lookup disabled, "FIXME", `JSGame.cpp:957-964`); `mode 2` → int `*p_D2CLIENT_RecentTradeId` (same value as mode 0); other → `false` (`JSGame.cpp:953-971`). `false` + warning if not in game. Known `RecentTradeId` values: `TRADE_OPEN 3`, `TRADE_ACCEPTED 5`, `TRADE_ACCEPT 7` (`Constants.h:141-143`).
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:945-946`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `p_D2CLIENT_RecentTradeId` (VARPTR DWORD, RVA `0x3C0E7C`, `D2Ptrs.h:213`); `RecentTradeName` is commented out (`D2Ptrs.h:212`, 1.13 RVA).
- **Quirks / bugs:** Legacy docs: `doc/globalFuncs.h:232-254` says mode 0 = "TradeFlag", 2 = "RecentTradeId"; api.html says mode 1 = partner name, mode 2 = partner gid. Code returns the same `RecentTradeId` for 0 and 2 and `null` for 1.

### `getDistance(a[, b[, c[, d]]])`

Euclidean distance between two points given as units, `{x,y}` objects or coordinates; the player is the implicit first point in the 1-object and 2-int forms.

- **Native:** `my_getDistance` at `JSGame.cpp:714`; registered at `JSGlobalFuncs.h:64` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads** (dispatch on `argc` and `JSVAL_IS_INT`/`JSVAL_IS_OBJECT`, `JSGame.cpp:724-799`):

  | argc | Shape | Point 1 | Point 2 |
  |---|---|---|---|
  | 1 | object `o` | player (`D2CLIENT_GetUnitX/Y(player)`) | `o.x`, `o.y` via `JS_GetProperty` + `JS_ValueToECMAInt32` (any object; Unit `x`/`y` props work) |
  | 2 | int, int | player | `(a, b)` |
  | 2 | object, object | `a.x, a.y` | `b.x, b.y` (JS properties) |
  | 3 | Unit, int, int | `GetUnitX/Y(FindUnit(a))` | `(b, c)` |
  | 3 | int, int, Unit | `GetUnitX/Y(FindUnit(c))` | `(a, b)` |
  | 4 | int ×4 | `(a, b)` | `(c, d)` |

  Missing `x`/`y` properties coerce `undefined` → 0. Any other shape leaves all four coordinates 0.
- **Returns:** JS number `abs(GetDistance(x1,y1,x2,y2))` with `DistanceType` default `Euclidean` (`JSGame.cpp:800`, `D2Helpers.cpp:967-996`, `D2Helpers.h:115`) — a non-integer double. Non-matching shapes → `0`. In the 3-arg Unit forms, an invalid private or unresolvable unit → **callee-return** (`JSGame.cpp:758-764`, `775-781`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:715-716`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none (JS getters on argument objects may run).
- **Game internals:** `D2CLIENT_GetUnitX/Y` (fastcall, RVA `0x5ADF0`/`0x5AE20`, `D2Ptrs.h:80-81`), `D2CLIENT_GetPlayerUnit` (RVA `0x63DD0`, `D2Ptrs.h:122`).
- **Quirks / bugs:** int forms require int-tagged values (**Int tag tests**) — e.g. `getDistance(10.5, 3)` silently returns 0. Legacy docs: api.html says the return type is int; code returns a double.

### `checkCollision(unitA, unitB, mask)`

Calls the game's unit-to-unit collision test.

- **Native:** `my_checkCollision` at `JSGame.cpp:826`; registered at `JSGlobalFuncs.h:64` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:** exactly 3 args: object, object, int (`JSVAL_IS_INT`) (`JSGame.cpp:830`). Both objects must carry a unit private passing the `PRIVATE_UNIT` bit test and resolve via `D2CLIENT_FindUnit`. Mask is truncated to `WORD`. Collision bits: [collision flags](#collision-flags-getcollision-checkcollision).
- **Returns:** int `D2COMMON_CheckUnitCollision(pA, pB, (WORD)mask)` (`JSGame.cpp:844`). Any other shape, invalid private or unresolved unit → **callee-return** (`JSGame.cpp:835-836`, `841-842`, `848`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:827-828`).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none known (game function semantics not in source).
- **Game internals:** `D2COMMON_CheckUnitCollision` (stdcall, RVA `0x222AA0`, `D2Ptrs.h:309`).
- **Quirks / bugs:** declared arity 2 but 3 required. Legacy docs: api.html says it returns bool; code returns the raw DWORD as int.

### `getCollision(area, x, y)`

Returns the 16-bit collision word at absolute map coordinate `(x, y)`.

- **Native:** `my_getCollision` at `JSGame.cpp:324`; registered at `JSGlobalFuncs.h:25` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments(… "uuu" …)` (`JSGame.cpp:331`): all three required and ToUint32-coerced (`TypeError` "getCollision requires more than N argument(s)" if fewer). `area` is a level id; `x`,`y` are absolute subtile coordinates.
- **Returns:** JS number: the room `CollMap` word at the point (`Map/Diablo_II/ActMap.cpp:177-178`). In levels 111/112/117/74 it is OR-ed with `ActMap::Avoid` (0xFFFF) when the point is exactly the coordinate of a preset with `dwTxtFileNo == 435` (barricade tower; the preset type is not checked) in that room (`Map/Diablo_II/ActMap.cpp:151-170`, `182-184`). The result is `0xFFFF` (`ActMap::Avoid`) if the point lies in no room of any level of the current act (`Map/Diablo_II/ActMap.cpp:84-136`). Throws "Level Not loaded" if `GetLevel(area)` returns NULL (`JSGame.cpp:339-341`). That happens only when no level with that id is in the act's level list, or when `GameReady()` is false inside `GetLevel`. A level whose rooms `D2COMMON_InitLevel` failed to create is still returned (`D2Helpers.cpp:182-196`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:325-327`); `area` must be a level of the player's current act (`GetLevel` walks `player->pAct->pMisc->pLevelFirst`, `D2Helpers.cpp:178-191`).
- **Threading & blocking:** script thread. Takes the **Game-loop lock** inside `GetLevel` (`D2Helpers.cpp:173`) and again for the ActMap lifetime (`ActMap::ActMap` → `actCrit->EnterSection()`, `Map/Diablo_II/ActMap.cpp:44-45`) until `map->CleanUp()` (`JSGame.cpp:352`, `Map/Diablo_II/ActMap.cpp:188-196`).
- **Side effects:** `D2COMMON_InitLevel` on uninitialised levels (`D2Helpers.cpp:182-183`, `Map/Diablo_II/ActMap.cpp:58-59`, `110-111`); temporary `D2COMMON_AddRoomData`/`RemoveRoomData` for rooms without `pRoom1` (`Map/Diablo_II/ActMap.cpp:172-176`, `188-191`); deletes the previously cached ActMap (`ActMap::GetMap`, `Map/Diablo_II/ActMap.cpp:14-31`); `Print("ActMap Level Not Loaded")` if act room data is missing (`Map/Diablo_II/ActMap.cpp:103-106`).
- **Game internals:** `GetLevel` (`D2Helpers.cpp:172`), `D2COMMON_InitLevel` (RVA `0x2424A0`, `D2Ptrs.h:290`), `D2COMMON_AddRoomData`/`RemoveRoomData` (`D2Ptrs.h:328-329`), `CollMap` (`D2Structs.h:256-267`). Internals: [world.md](world.md).
- **Quirks / bugs:** the `area` argument only selects which act/level is initialised; the point may resolve to a different level of the same act (search order: room cache, `level`, level cache, every level of the act). `GetLevel` leaks its `AutoCriticalRoom` (lock never released → game thread frozen) if `GameReady()` turns false between the native's check and `D2Helpers.cpp:175-176`. Shares the global ActMap cache race with `getPath` (see there). `getCollFromRoom` indexes `CollMap.pMapStart` with the point minus `CollMap.dwPosGameX/Y` and has no bounds check (`Map/Diablo_II/ActMap.cpp:177-178`). Room membership is tested with `Room2` coordinates ×5 (`Map/Diablo_II/ActMap.cpp:138-143`), so the read is in bounds only if the two coordinate systems agree.

### `getPath(area, x, y, dx, dy[, reductionType[, radius[, reject, reduce, mutate]]])`

Runs D2BS's A* pather over the collision map and returns a reduced list of waypoints.

- **Native:** `my_getPath` at `JSGame.cpp:229`; registered at `JSGlobalFuncs.h:25` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**

  | # | Name | Conversion | Default | Meaning |
  |---|---|---|---|---|
  | 0 | `area` | `u` | required | level id; 0 → throws "Invalid level passed to getPath" |
  | 1-2 | `x`, `y` | `u` | required | start, absolute subtile coords |
  | 3-4 | `dx`, `dy` | `u` | required | destination |
  | 5 | `reductionType` | `u` | 0 | 0 walk, 1 teleport, 2 none, 3 JS callbacks; other → throws "Invalid path reducer value!" |
  | 6 | `radius` | `u` | 20 | max spacing of output nodes for types 0/1 (reducers use `range = radius*10`, compared with `Euclidean()*10`), ignored by 2/3 |
  | 7 | `reject(x, y)` | must be function if type 3 | — | return true to reject a node |
  | 8 | `reduce(pt, i, pts)` | must be function if type 3 | — | return true to keep raw node `i` |
  | 9 | `mutate(x, y)` | must be function if type 3 | — | return `[x, y]` to move a rejected start/end |

  `argc < 5` → throws "Not enough parameters were passed to getPath!" (`JSGame.cpp:233-234`). Conversion uses `JS_ConvertArguments("uuuuu/uu")` (`JSGame.cpp:239`); a failing coercion returns `JS_FALSE` with the engine's error. For type 3, `argv[7..9]` are tested with `JSVAL_IS_FUNCTION` (`js32.h:98`) → throws "Invalid function values for reduction type" (`JSGame.cpp:244-246`); this reads past `argc` if fewer than 10 args were passed (**argv over-read**).
- **Returns:** Array of plain objects `{x: int, y: int}` in absolute coordinates (`JSGame.cpp:299-315`). Shape per reducer:
  - Type 0 (`WalkPathReducer::Reduce`, `Map/Path/Reduction/WalkPathReducer.h:106-136`) works on an 8-neighbour A* path. It emits the start, then the node *before* each change of the integer step slope `(int)(dy/dx)`. It also emits the previous node once the current node is `Euclidean×10 ≥ radius×10` from the last emitted node, so emitted nodes are about `radius` apart or less. The last node is always emitted. Paths with fewer than 2 nodes are returned unchanged.
  - Type 1 also shapes the search itself. `TeleportPathReducer::GetOpenNodes` offers the end directly when it is closer than `radius − 2`. Otherwise it offers non-rejected points on a precomputed ring (`range−5 < Euclidean×10 < range`) around the current node, and falls back to the 8 neighbours (`Map/Path/Reduction/TeleportPathReducer.h:26-39`, `60-125`). The raw path is therefore already a chain of teleport hops. `Reduce` then greedily emits the farthest raw node closer than `radius` to the previous output (`Map/Path/Reduction/TeleportPathReducer.h:41-57`).
  - Type 2 returns every A* node (`Map/Path/Reduction/NoPathReducer.h:19-21`).
  - Failure paths: the result is an empty array if there is no path, or if the search aborted because `GameReady()` became false, the player's level changed ("Pather lvl change while pathing" logged) or `Vars.bQuitting` was set (`Map/Path/AStarPath.h:122-127`). If `GetLevel(area)` returns NULL the native returns `JS_FALSE` **without** reporting an error (`JSGame.cpp:252-253`). This is an uncatchable, silent abort of the calling script. If the NULL came from `GameReady()` failing inside `GetLevel`, the game-loop lock is also leaked (`D2Helpers.cpp:173-176`; see **Game-loop lock**). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:230-231`); `area` must be in the player's current act (`D2Helpers.cpp:178-191`).
- **Threading & blocking:** script thread; synchronous and potentially long (A* until the open set is empty; no node cap, `Map/Path/AStarPath.h:106-152`). Holds the **Game-loop lock** from `ActMap::GetMap` (`JSGame.cpp:255` → `Map/Diablo_II/ActMap.cpp:44-45`) through `path.GetPath` until `map->CleanUp()` (`JSGame.cpp:288`); every 500 ms the search calls `map->AllowCritSpace()` (`Map/Path/AStarPath.h:118-121`), which runs `CleanUp()` (clears room/level caches, removes temporarily added rooms, leaves the lock), sleeps 5 ms and re-enters (`Map/Diablo_II/ActMap.cpp:197-202`). The game is frozen for the rest of the time.
- **JS callbacks (type 3), as designed:** invoked synchronously on the script thread through `JS_CallFunctionValue(cx, obj, fn, …)` (`Map/Path/Reduction/JSPathReducer.h:57`, `68`, `86`) **while the game-loop lock is held**. The intended `this` is the `this` of the `getPath` call, passed at `JSGame.cpp:271`, but see "Non-functional in practice" below.
  - `reject(x, y)` — for start and end before the search (`Map/Path/AStarPath.h:177-180`) and for every neighbour candidate except the end (`Map/Path/AStarPath.h:139`). That is up to 8 calls per expanded node (`Map/Path/Reduction/JSPathReducer.h:71-79`), and A* has no node cap.
  - `mutate(x, y)` — once for a rejected start and once for a rejected end; an object result's elements 0/1 are read with unchecked `JSVAL_TO_INT` (`Map/Path/Reduction/JSPathReducer.h:83-92`).
  - `reduce(pt, i, pts)` — once per raw node, `pt` an `{x,y}` object, `pts` the full raw array (`Map/Path/Reduction/JSPathReducer.h:34-64`).
  - Results are read with `JSVAL_TO_BOOLEAN` (payload, not ToBoolean — return strict booleans); a throwing callback leaves `rval = false` and its exception pending.
  - Re-entrancy: a callback that calls `getPath`/`getCollision` makes `ActMap::GetMap` delete the map the outer search is using (use-after-free); callbacks that wait on the game thread stall because the lock is held.
  - **Non-functional in practice:** the `JSPathReducer` constructor never assigns its `cx`/`obj` members (only the shadowing parameters are used to add roots) (`Map/Path/Reduction/JSPathReducer.h:16-27`). The first callback, which is `reject(start)` at `Map/Path/AStarPath.h:177`, therefore passes an uninitialised context pointer and `this` object to `JS_CallFunctionValue`. The destructor's `JS_RemoveRoot` does the same. Type 3 cannot work as compiled and is expected to crash while holding the game-loop lock. Roots are also added with `JS_AddRoot` = `JS_AddObjectRoot` on `jsval*` slots (`js32.h:96`).
- **Side effects:** same room/level side effects as `getCollision` (InitLevel, Add/RemoveRoomData); deletes the previous cached ActMap; teleport reducer fills `ActMap::PathingPointList` (`Map/Path/Reduction/TeleportPathReducer.h:88`, `104`); `_TIME` builds append allocator stats to `<Vars.szPath>\stats.txt` (`JSGame.cpp:290-297`, uses `%s` with a `wchar_t*`).
- **Game internals:** `GetLevel` (`D2Helpers.cpp:172`), `ActMap::GetMap` (`Map/Diablo_II/ActMap.cpp:14`), `AStarPath<>` with `EstimateDistance` = `DiagonalShortcut` heuristic and `DiagonalShortcut` step cost (`Map/Path/AStarPath.h:19-23`, `50-52`, `158`), node rejection `checkFlag(SpaceGetData)` = `(BlockWalk|BlockPlayer) & flag` (`Map/Path/AStarPath.h:45-48`), walk penalties 50/60/80 (`Map/Path/Reduction/WalkPathReducer.h:220-238`). Full description: [world.md](world.md).
- **Quirks / bugs:**
  - `ActMap::GetMap` keeps one global `cache[0]` and deletes it on every call before the new map takes the lock (`Map/Diablo_II/ActMap.cpp:18-24`). Two scripts pathing concurrently can therefore delete each other's map mid-search, and the deleting thread calls `CleanUp()`/`LeaveCriticalSection` on a `CriticalRoom` owned by another thread. The room and level caches are namespace-scope statics shared by every `ActMap` (`Map/Diablo_II/ActMap.h:40-41`).
  - **Teleport reducer with `radius ≤ 1` hangs the game.** With `range ≤ 10` the ring is empty and no 8-neighbour step is `< range` (straight steps are 10, diagonal steps 14). `TeleportPathReducer::Reduce` then never advances: it pushes the first node forever with unbounded memory growth, while the game-loop lock is held (`Map/Path/Reduction/TeleportPathReducer.h:44-56`). With `radius == 0` the first `it--` also steps before `begin()` (UB). See [world.md](world.md).
  - `radius` is ToUint32-coerced and multiplied by 10 into an `int` (`Map/Path/Reduction/WalkPathReducer.h:71`, `Map/Path/Reduction/TeleportPathReducer.h:26`). Values ≥ 2³¹/10 overflow. The teleport ring precomputation loops over `(2·radius+1)²` offsets in the constructor, so a very large `radius` costs a lot of time and memory there.
  - The "Invalid path reducer value!" throw happens after `ActMap::GetMap` entered the lock and without `CleanUp()` (`JSGame.cpp:255`, `273-275`): the game loop stays blocked until the same thread calls `getPath`/`getCollision` again.
  - `jsval* vec = new jsval[count]` is never freed (`JSGame.cpp:303`). Its elements live in untraced heap memory while further `BuildObject` calls allocate, which is a GC hazard. `JSPathReducer::Reduce` has the same unrooted-heap-array hazard but does free its array (`Map/Path/Reduction/JSPathReducer.h:40-63`).
  - `WalkPathReducer`'s `Slope()` computes `dy/dx` as doubles and converts the result to `int` (`Map/Path/AStarPath.h:39-43`). The first comparison is the 0/0 of the start node with itself, and every vertical step is ±1/0. Both give NaN/±inf, and converting those to `int` is undefined in C++. The slope check therefore relies on the compiler's out-of-range conversion result.
  - Legacy docs: api.html documents `getPath(area | areas[], sx, sy, ex, ey[, bool useTeleport[, radius[, bool useReduction]]])`; arrays are not supported (a one-element array works only through ToUint32 coercion) and the 8th argument is ignored unless type 3. `doc/globalFuncs.h:42-104` matches the code's parameter list.

### `getMouseCoords([toMap[, asObject]])`

Returns the client mouse position in screen or map coordinates.

- **Native:** `my_getMouseCoords` at `JSGame.cpp:1296`; registered at `JSGlobalFuncs.h:61` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `toMap` and `asObject` are taken from int or boolean args via `!!JSVAL_TO_BOOLEAN` (non-zero int → true). Operator precedence makes the tests `(argc > 0 && IS_INT(argv[0])) || IS_BOOLEAN(argv[0])` (`JSGame.cpp:1299-1302`), so `argv[0]`/`argv[1]` are inspected even when not passed (**argv over-read**).
- **Returns:** `[x, y]` Array by default, `{x, y}` object if `asObject`. Screen coords = `*p_D2CLIENT_MouseX/Y`; with `toMap`, `ViewportX/Y` are added and `D2COMMON_AbsScreenToMap` converts in place (`JSGame.cpp:1306-1313`). Throws "Could not build object", "Could not set x property", "Could not set y property"; **callee-return** if array creation failed (`JSGame.cpp:1336-1337`).
- **Preconditions:** none checked (out of game `toMap` gives meaningless values).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** none.
- **Game internals:** `p_D2CLIENT_MouseX/Y` (RVA `0x3A6AB0`/`0x3A6AAC`, `D2Ptrs.h:144-145`), `p_D2CLIENT_ViewportX/Y` (RVA `0x3A520C`/`0x3A5208`, `D2Ptrs.h:162-163`), `D2COMMON_AbsScreenToMap` (RVA `0x243510`, `D2Ptrs.h:334`).
- **Quirks / bugs:** `JS_AddRoot(cx, &pObj)` roots the address of a stack local before the NULL check (`JSGame.cpp:1320`, `1330`). It is not removed on the throw paths (`JSGame.cpp:1321-1326`) or on the array-failure early return (`JSGame.cpp:1336-1337`). Each of these leaves a dangling root into a dead stack frame that later GCs will read.

---

## Actions

### `clickMap(type, shift, unit | x, y)`

Simulates a mouse click on the game world at a unit or map coordinate.

- **Native:** `my_clickMap` at `JSGame.cpp:63`; registered at `JSGlobalFuncs.h:62` (declared arity 3, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `clickMap(type, shift, unit)` — exactly 3 args; `type` int, `shift` int or boolean, `unit` object with a unit private (bit test) that resolves via `D2CLIENT_FindUnit` (`JSGame.cpp:83-97`). Click point = unit position.
  - `clickMap(type, shift, x, y)` — `argc > 3`, all ints (shift may be boolean) (`JSGame.cpp:98-101`).
  - `type`, `shift`, `x`, `y` are converted with `JS_ValueToUint16` (coordinates wrap modulo 65536) (`JSGame.cpp:74-81`); `argv[3]` is read even when `argc == 3` (**argv over-read**, harmless because unused on that path).
  - `type` is passed unvalidated as `D2CLIENT_ClickMap`'s first argument. In-source usage: 0 then 2 for a move (down/up, `JSUnit.cpp:1893-1895`), 0 with a unit for interact (`JSUnit.cpp:881`). Legacy enumeration (api.html only): 0 left down, 1 left held, 2 left up, 3 right down, 4 right held, 5 right up.
  - `shift` non-zero → game flag `0x0C`; otherwise `0x08` if `*p_D2CLIENT_AlwaysRun` else `0` (`Core.cpp:161`, `172`).
- **Returns:** `true` if `ClickMap()` ran (client in game), else `false`; `false` for `argc < 3`, any other shape, invalid private or unresolved unit (`JSGame.cpp:69-72`, `87-93`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:64-65`; `ClickMap` re-checks `ClientState`, `Core.cpp:135-136`).
- **Threading & blocking:** script thread; **no lock** — game input code runs concurrently with the game thread; non-blocking.
- **Side effects** (`ClickMap`, `Core.cpp:134-179`): converts map→screen with `D2COMMON_MapToAbsScreen` minus `ViewportX/Y`; saves, zeroes and later restores `*p_D2CLIENT_MouseX/Y`; for a unit target other than the player sets `Vars.dwSelectedUnitId/Type` + `Vars.bClickAction` so the patched `GetSelectedUnit` call inside `D2CLIENT_ClickMap` (`Patch.h:13`, RVA `0x62D72` → `GetSelectedUnit_Intercept`, `D2Intercepts.cpp:92-104`) returns that unit, then calls `D2CLIENT_SetSelectedUnit(NULL)` and clears the globals; for coordinate clicks (and clicks on the player) `bClickAction` is set with id 0, so the intercept returns NULL and the click never targets the unit under the real cursor (`Core.cpp:167-174`). The game generates the resulting packets.
- **Game internals:** `D2CLIENT_ClickMap` (FUNCPTR `__fastcall(MouseFlag, x, y, Type)`, RVA `0x62D00`, `D2Ptrs.h:95`), `D2COMMON_MapToAbsScreen` (RVA `0x243260`, `D2Ptrs.h:333`), `p_D2CLIENT_AlwaysRun` (RVA `0x3A0660`, `D2Ptrs.h:219`), `D2CLIENT_SetSelectedUnit` → `D2CLIENT_SetSelectedUnit_STUB` (`D2Ptrs.h:497`, `D2Helpers.cpp:728-734`) → `SetSelectedUnit_I` (RVA `0x66DE0`, `D2Ptrs.h:73`).
- **Quirks / bugs:** `Vars.dwSelectedUnitId/Type/bClickAction` and the mouse globals are process-wide: concurrent `clickMap` calls from two scripts (or real mouse input) race. The FUNCPTR names its parameters `(MouseFlag, x, y, Type)` (`D2Ptrs.h:95`), but `ClickMap` passes the click type as the first argument and the shift/run flag as the last (`Core.cpp:161`, `172`). The names in D2Ptrs.h are therefore swapped relative to their use. Legacy docs (`doc/globalFuncs.h:1384-1456`) leave `nClickType` undocumented.

### `clickItem(item | clickType, bodyLoc | clickType, item | button, x, y, location)`

Simulates inventory/belt/equipment/merc clicks by calling the client's UI click handlers directly.

- **Native:** `my_clickItem` at `JSGame.cpp:357`; registered at `JSGlobalFuncs.h:63` (declared arity 0, `FUNCTION_FLAGS`).
- **Common prologue:** **WaitForGameReady** (`JSGame.cpp:360-361`); return value preset to `null` (`JSGame.cpp:362`); takes the **Game-loop lock** (`JSGame.cpp:364`); returns `false` if any of `*p_D2CLIENT_TransactionDialog`, `*p_D2CLIENT_TransactionDialogs`, `*p_D2CLIENT_TransactionDialogs_2` is non-zero (an NPC transaction dialog is open) (`JSGame.cpp:366-370`); then writes `*p_D2CLIENT_CursorHoverX = *p_D2CLIENT_CursorHoverY = 0xFFFFFFFF` (`JSGame.cpp:399-400`).
- **Arguments / overloads:**

  **A. `clickItem(item)`** — `argc == 1`, object (`JSGame.cpp:402-426`). Unit private (bit test) + `FindUnit`; then calls `BodyClickTable[pUnit->pItemData->BodyLocation](player, player->pInventory, BodyLocation)` (click on the equipment slot the item occupies). Returns `null` (also when the private/unit/table entry is invalid).

  **B. `clickItem(clickType, bodyLoc)`** — `argc == 2`, int, int (`JSGame.cpp:427-454`):

  | clickType | Action | Return |
  |---|---|---|
  | 0 | `BodyClickTable[bodyLoc](player, inv, bodyLoc)` — click player equipment slot `bodyLoc` ([body locations](#body-locations-clickitem)) | `null` |
  | 4 | if `bodyLoc ∈ {1,3,4}` and `GetMercUnit(player)` finds the merc: `D2CLIENT_MercItemAction(0x61, bodyLoc)` | `true`, else `null` |
  | other | nothing | `null` |

  **C. `clickItem(clickType, item)`** — `argc == 2`, int, object (`JSGame.cpp:455-554`). Unit private (bit test) + `FindUnit`; throws "Object is not an item!" if unresolved, not `UNIT_ITEM` or no `pItemData` (`JSGame.cpp:467-470`). `loc = pItemData->GameLocation`; grid `(x,y) = pItemPath->dwPosX/Y`, also written to `CursorHoverX/Y`.

  | Condition (first match) | Action | Return |
  |---|---|---|
  | `clickType == 4` | if merc exists and `pItemData->pOwner->dwUnitId == merc id`: `D2CLIENT_MercItemAction(0x61, BodyLocation)` | `true`, else `null` |
  | `loc` ∈ INVENTORY(3)/STASH(7)/CUBE(6) | pixel `px = layout.Left + x*SlotPixelWidth + 10`, `py = layout.Top + y*SlotPixelHeight + 10`; `clickType 0` → `D2CLIENT_LeftClickItem(target, player, inv, px, py, 0, layout)`; any other → `D2CLIENT_RightClickItem(px, py, target, player, inv)`; target = `CLICKTARGET_INVENTORY 0` / `STASH 4` / `CUBE 3` | `true` |
  | `loc == BELT(2)` | slot `i = dwPosX` (0..15 else return `null`); screen `px = 440 + col*29, py = 580 − row*29` if `D2GFX_GetScreenSize() == 2`, else `360 + col*29, 460 − row*29` (`Belt[]` table `JSGame.cpp:377-397`); `clickType 0` → `D2CLIENT_ClickBelt(px, py, inv)`; else → `D2CLIENT_ClickBeltRight(inv, player, clickType == 1 ? FALSE : TRUE, i)` | `true` |
  | item is the cursor item | `clickType` must be 1..12 (else `null`): `BodyClickTable[clickType](player, inv, clickType)` — put the cursor item on body location `clickType` | `true` |
  | otherwise (ground, equipped, store, trade…) | nothing | `true` |

  **D. `clickItem(button, x, y, location)`** — `argc == 4`, all ints (`JSGame.cpp:555-656`). Writes `CursorHoverX/Y = (x, y)`. If `location != BELT` and a cursor item exists whose `ItemTxt.ySize > 1` / `xSize > 1`, adds 1 to `y` / `x` (`JSGame.cpp:569-581`).

  | location | Mapping | button 0 | button 1 | button 2 | Return |
  |---|---|---|---|---|---|
  | INVENTORY 3 / TRADE 5 / CUBE 6 / STASH 7 | `InventoryLayout`/`TradeLayout`/`CubeLayout`/`StashLayout`, target `CLICKTARGET_INVENTORY 0`/`TRADE 2`/`CUBE 3`/`STASH 4`; pixel formula as in C | `LeftClickItem(…, 1, layout)` | `RightClickItem(…)` | `LeftClickItem(…, 5, layout)` (shift-left) | `true` |
  | BELT 2 | `(x,y)` must equal a `Belt[]` cell (col 0-3, row 0-3) else `null`; screen pixels as in C | `ClickBelt(px, py, inv)` | `ClickBeltRight(player, inv, FALSE, z)` | `ClickBeltRight(player, inv, TRUE, z)` | `true` |
  | other | nothing | | | | `true` |

  **Any other call shape** (no args, 3 args, 2 args of other types, ≥5 args) → `true` with no action (`JSGame.cpp:658`).
- **Returns:** see tables; `false` (transaction dialog open) or `false` + warning (not in game).
- **Preconditions:** in game; no NPC transaction dialog open. Required UI state (inventory/stash/cube/trade open) is **not** checked.
- **Threading & blocking:** script thread; game-loop lock held for the whole call (waits for the next game-thread yield). No waiting for the click's result.
- **Side effects:** calls client UI handlers (which send the corresponding item packets themselves); writes `CursorHoverX/Y`. `MercItemAction`'s first argument is named `bPacketType` and is 0x61 (`D2Helpers.h:104`); the packet is built by the game.
- **Game internals:** `D2CLIENT_BodyClickTable` (ASMPTR used as a table of `__fastcall(UnitAny*, Inventory*, int)` pointers, RVA `0x321E58`, `D2Ptrs.h:258`, typedef `JSGame.cpp:358`); `D2CLIENT_LeftClickItem` wrapper (`D2Helpers.cpp:790-798`) → `LeftClickItem_I` (RVA `0x8FFE0`, `D2Ptrs.h:96-98`); `D2CLIENT_RightClickItem` macro (`D2Ptrs.h:501`) → `D2CLIENT_ClickItemRight_ASM` (`D2Helpers.cpp:800-808`) → `ClickItemRight_I` (RVA `0x87740`, `D2Ptrs.h:237`); `D2CLIENT_ClickBelt` (`D2Helpers.cpp:783-788`) → `ClickBelt_I` (RVA `0x98870`, `D2Ptrs.h:235`); `D2CLIENT_ClickBeltRight` macro (`D2Ptrs.h:502`) → `_ASM` (`D2Helpers.cpp:810-817`) → `ClickBeltRight_I` (RVA `0x98A90`, `D2Ptrs.h:236`); `D2CLIENT_MercItemAction` (`D2Ptrs.h:504`, `D2Helpers.cpp:847-854`) → `MercItemAction_I` (RVA `0x785B0`, `D2Ptrs.h:238`); layouts `D2Ptrs.h:171-175`; `TransactionDialog(s)(_2)` `D2Ptrs.h:193-195`; `CursorHoverX/Y` `D2Ptrs.h:141-142`; `D2GFX_GetScreenSize` (`D2Ptrs.h:383`); `D2COMMON_GetItemText` (`D2Ptrs.h:299`); `D2CLIENT_GetCursorItem` (`D2Ptrs.h:71`); `GetMercUnit` (`D2Helpers.cpp:482-498`, merc class ids `Constants.h:156-159`); `GetItemLocation` = `pItemData->GameLocation` (`D2Helpers.cpp:455-460`). Struct fields: `ItemData.BodyLocation@0x44`, `GameLocation@0x68`, `pOwner@0x84` (`D2Structs.h:476-507`), `ItemPath.dwPosX/Y@0x0C/0x10` (`D2Structs.h:393-398`), `InventoryLayout` (`D2Structs.h:732-743`), `ItemTxt.xSize/ySize` at computed offsets 0x10F/0x110; the source comments say 0xFC/0xFD, but `_2a` is declared `[0x19]` (`D2Structs.h:515-519`, see [../memory/structs.md](../memory/structs.md)). Stub conventions: [../memory/call-stubs.md](../memory/call-stubs.md).
- **Quirks / bugs:**
  - Form A does not check that the unit is an item: for a non-item, `pItemData` aliases another union member (`D2Structs.h:611-617`) and an arbitrary byte indexes `BodyClickTable`, followed by an indirect call. Forms A and B never bounds-check the table index (`BodyLocation` byte, `bodyLoc` int, `JSGame.cpp:417`, `432`). Form C limits it to 1..12 (`JSGame.cpp:541`).
  - `D2CLIENT_ClickBeltRight` is called with `(inv, player, …)` in form C (`JSGame.cpp:539`) but `(player, inv, …)` in form D (`JSGame.cpp:648`, `650`); the macro/stub parameter names (`D2Ptrs.h:502`, `D2Helpers.cpp:810`) disagree with each other too, so one of the two forms passes the arguments swapped.
  - Form C left-click passes click type `0`, form D passes `1` (and `5` for shift) to the same `LeftClickItem`.
  - Form C dereferences `pUnit->pItemPath` without a NULL check (`JSGame.cpp:475-476`). In form D, a `button` other than 0/1/2 on a valid location performs no click but still returns `true` (`JSGame.cpp:607-616`, `645-654`).
  - Layout pointers are formed as `(InventoryLayout*)p_D2CLIENT_InventoryLayout` — the VARPTR *address* is used as the struct although the VARPTR type is `InventoryLayout*` (`JSGame.cpp:497`, `D2Ptrs.h:175`).
  - Belt pixel positions are hard-coded for 640×480/800×600.
  - Legacy docs: `doc/globalFuncs.h:1584-1592` says 4-arg `nLoc 4 = player trade` (code: `LOCATION_TRADE` = 5; 4 is `LOCATION_STORE`, unsupported) and lists "4 - left click merc location" for the 4-arg form (unsupported); api.html lists locations "0 inventory, 2 trade, 3 cube, 4 stash, 5 belt" (those are `CLICKTARGET_*` values, not what the code accepts) and click type "3 - Mercenary Item" (code uses 4).

### `clickParty(party, mode)`

Presses a party-screen button for a roster entry.

- **Native:** `my_clickParty` at `JSGame.cpp:1074`; registered at `JSGlobalFuncs.h:66` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 2`, `party` an object, `mode` int; otherwise `false`. This check runs *before* the game-state wait, so a bad call returns `false` without a warning even out of game (`JSGame.cpp:1077-1078`). `party`'s private is taken as a `RosterUnit*` (a Party object from `getParty`, whose private is a raw game pointer — [world.md](world.md)); no class check.
- **Mode logic** (`JSGame.cpp:1099-1136`, evaluated in this order; `myRoster = *p_D2CLIENT_PlayerUnitList`, the first roster entry):

  | mode | Guard (returns `false`) | Action | Return |
  |---|---|---|---|
  | 0 loot | `BnData` present and character not hardcore (`nCharFlags & PLAYER_TYPE_HARDCORE`) | `D2CLIENT_HostilePartyUnit(p, 2)` | `true` |
  | 1 hostile | — | `D2CLIENT_HostilePartyUnit(p, 1)` | `true` |
  | 2 party | `p->wPartyId != 0xFFFF && myRoster->wPartyId == p->wPartyId` | `D2CLIENT_ClickParty(p, 2)` | `true` |
  | 3 leave | `p->wPartyId == 0xFFFF` (checks the *passed* player's party) | `D2CLIENT_LeaveParty()` | `true` |
  | 4 | — | `D2CLIENT_HostilePartyUnit(p, 3)` | `true` |
  | 5 | — | `D2CLIENT_HostilePartyUnit(p, 4)` | `true` |
  | <0, >5 | always | — | `false` |

  Common guards: `p` and `myRoster` non-NULL; `p->dwUnitId` must appear in the roster list (`JSGame.cpp:1090-1097`); modes other than 3 refuse `p->dwUnitId == player->dwUnitId` (`JSGame.cpp:1123-1125`).
- **Returns:** bool as above; `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1080-1081`). Party screen need not be open.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** game party-button handlers (they send the party packets).
- **Game internals:** `p_D2CLIENT_PlayerUnitList` (RVA `0x3BB5C0`, `D2Ptrs.h:205`), `p_D2LAUNCH_BnData` (RVA `0x3795D4`, `D2Ptrs.h:430`), `D2CLIENT_HostilePartyUnit` (`D2Helpers.cpp:947-953`: `mov eax, edx; jmp [ClickParty_II]`, RVA `0x9B990`, `D2Ptrs.h:243`), `D2CLIENT_ClickParty` macro (`D2Ptrs.h:500`) → `ClickParty_ASM` (`D2Helpers.cpp:752-758`) → `ClickParty_I` (RVA `0x79EB0`, `D2Ptrs.h:242`), `D2CLIENT_LeaveParty` (RVA `0x79FC0`, `D2Ptrs.h:106`); `RosterUnit{dwUnitId@0x10, wPartyId@0x22, pNext@0x80}` (`D2Structs.h:216-235`); `BnetData.nCharFlags@0x1EF` (`D2Structs.h:190`); `PLAYER_TYPE_HARDCORE 4` (`Constants.h:134`).
- **Quirks / bugs:** `p->dwUnitId` is read from the possibly stale raw pointer before validation, and after validation the original pointer (not the matching live roster entry) is passed to the game. Legacy docs: `doc/globalFuncs.h:1724-1740` and api.html document modes 0-3 only; 4 and 5 exist in code (meaning not stated in source); doc says mode 3 "doesn't matter which party is passed in" — code requires the passed player to be in a party.

### `acceptTrade([mode])`

Toggles trade acceptance, or (with a mode) returns trade state.

- **Native:** `my_acceptTrade` at `JSGame.cpp:106`; registered at `JSGlobalFuncs.h:62` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `acceptTrade(1)` → `BOOLEAN_TO_JSVAL(*p_D2CLIENT_bTradeAccepted)` (**Malformed bool** risk) (`JSGame.cpp:111-114`).
  - `acceptTrade(2)` → int `*p_D2CLIENT_RecentTradeId` (`JSGame.cpp:115-118`).
  - `acceptTrade(3)` → `BOOLEAN_TO_JSVAL(*p_D2CLIENT_bTradeBlock)` ("check is red") (`JSGame.cpp:119-122`).
  - `acceptTrade()` / other values → action. `argv[0]` is extracted with unchecked `JSVAL_TO_INT`, and the mode-2/3 tests read `argv[0]` even when `argc == 0` (**argv over-read**: a no-arg call can be misread as a query).
- **Action** (`JSGame.cpp:125-144`, under the **Game-loop lock**): only if `RecentTradeId ∈ {3, 5, 7}` (`TRADE_OPEN`, `TRADE_ACCEPTED`, `TRADE_ACCEPT`, `Constants.h:141-143`): if `bTradeBlock` → `false`; else if `bTradeAccepted` → writes `bTradeAccepted = FALSE`, calls `D2CLIENT_CancelTrade()`, returns `true`; else writes `bTradeAccepted = TRUE`, calls `D2CLIENT_AcceptTrade()`, returns `true`. Any other trade id → throws "Invalid parameter passed to acceptTrade!" (a state error, despite the message).
- **Returns:** as above; `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:107-108`, applies to the query modes too); for the action, a trade window state 3/5/7.
- **Threading & blocking:** script thread; the action path waits for the game-loop lock; query modes take no lock.
- **Side effects:** direct write of the client global `bTradeAccepted` before calling the game function; the game sends the trade packet.
- **Game internals:** `D2CLIENT_AcceptTrade`/`CancelTrade` (fastcall, RVA `0xB9070`/`0xB90B0`, `D2Ptrs.h:108-109`), `p_D2CLIENT_bTradeAccepted`/`bTradeBlock` (RVA `0x3BCE18`/`0x3BCE28`, `D2Ptrs.h:209-210`), `p_D2CLIENT_RecentTradeId` (`D2Ptrs.h:213`).
- **Quirks / bugs:** `TODO: Fix this nonsense.` (`JSGame.cpp:110`). Legacy docs agree on modes 1-3; api.html says the no-arg form returns "true if the trade action was not blocked" — it also toggles (cancels if already accepted).

### `tradeOk()`

Clicks the "OK" line of the trade-request dialog.

- **Native:** `my_tradeOk` at `JSGame.cpp:147`; registered at `JSGlobalFuncs.h:63` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** on success **callee-return** (no return value is set, `JSGame.cpp:159-162`); otherwise throws "Not in proper state to click ok to trade." (`JSGame.cpp:167`). `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:148-149`); `*p_D2CLIENT_pTransactionDialogsInfo` non-NULL, one of its lines has `handler == D2CLIENT_TradeOK`, and `*p_D2CLIENT_TransactionDialogs == 1` (`JSGame.cpp:155-160`; per the source comment a crash is "guaranteed" otherwise).
- **Threading & blocking:** script thread; under the **Game-loop lock**.
- **Side effects:** calls `D2CLIENT_TradeOK()` (stdcall, RVA `0xB8A30`, `D2Ptrs.h:110`).
- **Game internals:** `TransactionDialogsInfo_t` (`D2Structs.h:785-798`), `p_D2CLIENT_TransactionDialogs` (`D2Ptrs.h:194`).
- **Quirks / bugs:** `numLines` is not clamped to 10 (`JSGame.cpp:156`). Legacy docs (`doc/globalFuncs.h:1484-1490`): "void"; code returns the function object on success.

### `gold([amount[, mode]])`

Performs a gold-dialog action (drop/stash/withdraw-style transfers) with an amount.

- **Native:** `my_gold` at `JSGame.cpp:809`; registered at `JSGlobalFuncs.h:64` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `amount` (default 0) and `mode` (default 1) are used only if `JSVAL_IS_INT`; non-int values silently keep the defaults (`JSGame.cpp:813-820`). No validation of amount or mode; mode values are not defined in source (see [Open questions](#open-questions)).
- **Returns:** **callee-return** after the action; `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:810-811`). No UI or gold-balance check.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** `SendGold` (`Game.cpp:8-12`) writes `*p_D2CLIENT_GoldDialogAmount = amount`, `*p_D2CLIENT_GoldDialogAction = mode`, then calls `D2CLIENT_PerformGoldDialogAction()`; the game sends any packet.
- **Game internals:** `p_D2CLIENT_GoldDialogAction`/`GoldDialogAmount` (RVA `0x3A279C`/`0x3A2A68`, `D2Ptrs.h:165-166`), `D2CLIENT_PerformGoldDialogAction` (fastcall, RVA `0x54080`, `D2Ptrs.h:120`).
- **Quirks / bugs:** Legacy docs: api.html "Modes: Currently unknown"; `doc/globalFuncs.h:1672-1682` same.

### `say(...values)`

Sends each argument as a separate chat line (in game) or channel message (out of game, in a chat channel).

- **Native:** `my_say` at `JSGame.cpp:1044`; registered at `JSGlobalFuncs.h:66` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** any number. Each non-`null` argument is converted to string in place (`JS_ConvertValue(…, JSTYPE_STRING, &argv[i])`, which overwrites the argument slot) and sent with `Say(L"%s", text)` (`JSGame.cpp:1047-1067`); `null` is skipped, `undefined` is sent as `"undefined"`. Conversion failures report "Converting to string failed" / "Could not get string for value" and return `JS_FALSE`.
- **Returns:** `true` always (also with zero arguments) (`JSGame.cpp:1070`).
- **Preconditions:** none checked by the native. `Say` (`Core.cpp:85-132`) acts only if `*p_D2CLIENT_PlayerUnit != NULL` (in game) or, out of game, if `findControl(CONTROL_BUTTON, 5308, -1, 187, 470, 80, 20)` exists and `findControl(CONTROL_BUTTON, 5102, -1, 351, 337, 96, 32)` does not ("help button and ! ok msg for disconnected", `Core.cpp:123-124`; `findControl` in `Control.cpp:7`); otherwise nothing is sent.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:**
  - Always sets `Vars.bDontCatchNextMsg = TRUE` (`Core.cpp:93`), even when nothing is sent. The flag is cleared by whichever of these runs first:
    - The `GameInput`/`ChannelInput` intercept. That line skips `.`-command parsing and the `chatinput` event but is still sent (`D2Handlers.cpp:121-143`).
    - `WhisperHandler`, which suppresses that `whispermsg` event (`D2Handlers.cpp:464-471`).
    - `ChatEventHandler`, which only clears the flag; the `chatmsg` event still fires (`D2NetHandlers.cpp:55-64`, `Events.cpp:214`).
  - In game:
    - Copies the formatted text into the client chat buffer `p_D2CLIENT_ChatMsg`. The VARPTR address itself is used as the buffer, and the length is unbounded (`Core.cpp:96`).
    - Heap-allocates `MSG{hwnd=D2GFX_GetHwnd(), WM_CHAR, wParam=VK_RETURN, lParam=0x11C0001, pt={0x79,1}}` and calls `Say_ASM((DWORD)&aMsg)`. The argument is the address of the local `MSG*` variable, i.e. a `MSG**` (`Core.cpp:98-109`).
    - `Say_ASM` rebuilds the target's prologue: it pushes the argument as a stack parameter, sets up an EBP frame with 0x110 bytes of locals, pushes EBX/ESI/EDI and sets EBX = the argument. It then `JMP`s into the middle of the client's chat-input routine at `D2CLIENT_Say_I` (`Core.cpp:67-83`).
    - Whatever is sent is decided by that game routine. The D2BS-built packet 0x15 path is commented out (`Core.cpp:111-121`).
  - Out of game: converts to ANSI (`CP_ACP`), copies into `p_D2MULTI_ChatBoxMsg` (unbounded) and calls `D2MULTI_DoChat()` (`Core.cpp:124-129`).
- **Game internals:** `p_D2CLIENT_PlayerUnit` (RVA `0x3A6A70`, `D2Ptrs.h:202`), `p_D2CLIENT_ChatMsg` (RVA `0x3BB638`, `D2Ptrs.h:224`), `D2CLIENT_Say_I` (ASMPTR, RVA `0x7CBDA`, `D2Ptrs.h:256`), `p_D2MULTI_ChatBoxMsg` (RVA `0x37AE40`, `D2Ptrs.h:396`), `D2MULTI_DoChat` (RVA `0x42810`, `D2Ptrs.h:389`). Stub: [../memory/call-stubs.md](../memory/call-stubs.md).
- **Quirks / bugs:**
  - Long messages overflow the buffer: neither `memcpy` has a length bound.
  - If nothing was sent (not in game and not on the chat screen), the stale `bDontCatchNextMsg` is still set. The next user-typed line then bypasses `.`-commands and the `chatinput` event, or the next incoming whisper raises no `whispermsg` event.
  - Each argument is a separate injected chat line.
  - Legacy docs: "true if at least one parameter was sent in" (`doc/globalFuncs.h:1716-1722`); code always returns `true`.

### `useStatPoint(stat[, count])`

Spends unallocated stat points by sending stat-allocation packets.

- **Native:** `my_useStatPoint` at `JSGame.cpp:1143`; registered at `JSGlobalFuncs.h:67` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments("c/u")` (`JSGame.cpp:1150`): `stat` ToUint16 (required; missing → `TypeError` "useStatPoint requires more than 0 arguments"), `count` ToUint32 stored in an `int32` (default 1). `stat` is not validated (`STAT_STRENGTH 0`, `ENERGY 1`, `DEXTERITY 2`, `VITALITY 3`, `Constants.h:164-167`).
- **Returns:** **callee-return** in all non-error cases (including "not enough points"); `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1144-1145`); `UseStatPoint` silently does nothing if `D2COMMON_GetUnitStat(player, STAT_STATPOINTSLEFT=4, 0) < count` (signed/unsigned compare; `count` ≥ 2³¹ becomes negative → rejected) (`Game.cpp:15-16`).
- **Threading & blocking:** script thread; no lock; **sleeps 500 ms between packets** (`count − 1` sleeps, `Game.cpp:21-25`) without processing script events.
- **Side effects:** sends `count` packets via `D2CLIENT_SendGamePacket(3, buf)`:

  | Offset | Size | Value |
  |---|---|---|
  | 0 | 1 | `0x3A` |
  | 1 | 2 | `stat` (WORD) |
- **Game internals:** `UseStatPoint` (`Game.cpp:14`), `D2COMMON_GetUnitStat` (stdcall, RVA `0x225480`, `D2Ptrs.h:306`), send path in **Packet paths**.
- **Quirks / bugs:** Legacy docs (`doc/globalFuncs.h:1768-1782`) warn that it "directly sends packets without checks"; code does check remaining points (but not the stat id).

### `useSkillPoint(skill[, count])`

Spends unallocated skill points by sending skill-allocation packets.

- **Native:** `my_useSkillPoint` at `JSGame.cpp:1159`; registered at `JSGlobalFuncs.h:68` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** as `useStatPoint` (`"c/u"`, `JSGame.cpp:1166`); `skill` is a skill id, not validated.
- **Returns:** **callee-return**; `false` + warning if not in game.
- **Preconditions:** in game (`JSGame.cpp:1160-1161`); silently nothing if `GetUnitStat(player, STAT_SKILLPOINTSLEFT=5, 0) < count` (`Game.cpp:29-30`).
- **Threading & blocking:** script thread; no lock; `Sleep(500)` between packets (`Game.cpp:35-39`).
- **Side effects:** `count` × `D2CLIENT_SendGamePacket(3, {0x3B, WORD skill})` (`Game.cpp:32-36`).
- **Game internals:** `UseSkillPoint` (`Game.cpp:28`), `STAT_SKILLPOINTSLEFT` (`Constants.h:169`).
- **Quirks / bugs:** as `useStatPoint`; does not check that the skill is learnable.

### `transmute()`

Presses the Horadric Cube "transmute" button, opening the cube UI temporarily if needed.

- **Native:** `my_transmute` at `JSGame.cpp:1258`; registered at `JSGlobalFuncs.h:67` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `null` always (`JSGame.cpp:1259`); `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1260-1261`). No check that the player has a cube.
- **Threading & blocking:** script thread; no lock; non-blocking (does not wait for the result).
- **Side effects:** if `D2CLIENT_GetUIState(UI_CUBE)` is 0: `D2CLIENT_SetUIState(UI_CUBE, TRUE)` = `D2CLIENT_SetUIVar(0x1A, 1, 0)`; then `D2CLIENT_Transmute()`; then `SetUIVar(0x1A, 0, 0)` if it was closed (`JSGame.cpp:1263-1270`). The game sends the transmute request.
- **Game internals:** `D2CLIENT_Transmute` (fastcall, RVA `0x8A0D0`, `D2Ptrs.h:65`), `D2CLIENT_SetUIVar` (RVA `0x55F20`, `D2Ptrs.h:79`, macro `D2Ptrs.h:494`), `UI_CUBE 0x1A` (`Constants.h:43`).
- **Quirks / bugs:** the meaning of `SetUIVar`'s `howset` argument (TRUE/FALSE) is assumed by D2BS naming only. Legacy docs: api.html says "The cube must be open for this function to work"; code opens it itself.

### `weaponSwitch([query])`

Swaps weapon sets, or returns the active set.

- **Native:** `my_weaponSwitch` at `JSGame.cpp:1223`; registered at `JSGlobalFuncs.h:66` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc > 0` → `JS_ValueToInt32(argv[0])` (rounding, fails on NaN/out-of-range, `dependencies/include/jsapi.h:1743-1749`) → throws "Could not convert value" (`JSGame.cpp:1230-1237`; e.g. `weaponSwitch(undefined)`).
  - `query == 0` or no argument → perform switch.
  - `query != 0` → return `*p_D2CLIENT_bWeapSwitch` (int) (`JSGame.cpp:1252-1253`).
- **Returns:** switch: `true` after sending; `false` if the character is not expansion (`!(BnData->nCharFlags & PLAYER_TYPE_EXPAC)`), throws "Could not acquire BnData" if `*p_D2LAUNCH_BnData == NULL` (`JSGame.cpp:1241-1246`). Query: int. `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1226-1227`).
- **Threading & blocking:** script thread; no lock; non-blocking (does not wait for the server's confirmation; `bWeapSwitch` changes later).
- **Side effects:** `D2NET_SendPacket(1, 1, {0x60})` — one-byte packet `0x60` (weapon-set swap) sent straight to the network layer (`JSGame.cpp:1248-1250`).
- **Game internals:** `p_D2LAUNCH_BnData` (`D2Ptrs.h:430`), `PLAYER_TYPE_EXPAC 32` (`Constants.h:135`), `p_D2CLIENT_bWeapSwitch` (RVA `0x3BCC4C`, `D2Ptrs.h:207`), `D2NET_SendPacket` (`D2Ptrs.h:362`).
- **Quirks / bugs:** Legacy docs: api.html says passing `true` performs the switch and returns `true`, otherwise returns the current switch — the code is the opposite (`true` → 1 → query). `doc/globalFuncs.h:1742-1760` matches the code.

### `submitItem()`

Submits the cursor item to the current quest receptacle (Horadric Staff into the Orifice in Act 2, or the town NPC "submit item" screen in Acts 1/5).

- **Native:** `my_submitItem` at `JSGame.cpp:1344`; registered at `JSGlobalFuncs.h:61` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** bool, by the following branch table (`JSGame.cpp:1349-1373`); `false` + warning if not in game:

  | Condition | Action | Return |
  |---|---|---|
  | no cursor item (`D2CLIENT_GetCursorItem() == NULL`) | — | `false` |
  | `player->dwAct == 1` (Act 2) and `GetPlayerArea() == player->pAct->pMisc->dwStaffTombLevel` | writes `*p_D2CLIENT_CursorItemMode = 3`; sends packet 0x44 (below) via `D2NET_SendPacket(17, 1, buf)` | `true` |
  | Act 2, other area | — | `false` |
  | `dwAct == 0` or `4` (Act 1/5) and `*p_D2CLIENT_RecentInteractId != 0` and `D2COMMON_IsTownByLevelNo(area)` | `D2CLIENT_SubmitItem(cursorItem->dwUnitId)` | `true` |
  | Act 1/5 otherwise, Acts 3/4 | — | `false` |

  Packet 0x44 (17 bytes):

  | Offset | Size | Value |
  |---|---|---|
  | 0 | 1 | `0x44` |
  | 1 | 4 | player `dwUnitId` |
  | 5 | 4 | `*p_D2CLIENT_OrificeId` |
  | 9 | 4 | cursor item `dwUnitId` |
  | 13 | 4 | `3` |
- **Preconditions:** in game (**WaitForGameReady**, `JSGame.cpp:1346-1347`); return preset `null` (`JSGame.cpp:1345`) is always overwritten.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** client memory write (`CursorItemMode`), packet or game call as above.
- **Game internals:** `D2CLIENT_GetCursorItem` (`D2Ptrs.h:71`), `D2CLIENT_SubmitItem` (fastcall, RVA `0xB2370`, `D2Ptrs.h:64`), `p_D2CLIENT_OrificeId`/`CursorItemMode` (RVA `0x3C547C`/`0x3C5474`, `D2Ptrs.h:225-226`), `p_D2CLIENT_RecentInteractId` (RVA `0x3C0D25`, `D2Ptrs.h:189`), `D2COMMON_IsTownByLevelNo` (RVA `0x21AAF0`, `D2Ptrs.h:338`), `GetPlayerArea` (`D2Helpers.cpp:168-170`), `ActMisc.dwStaffTombLevel@0x94` (`D2Structs.h:352`), `UnitAny.dwAct@0x18` (`D2Structs.h:618`).
- **Quirks / bugs:** the Orifice packet does not check that the cursor item is the staff or that the player is near the orifice. Legacy docs: api.html "returns nothing"; code returns bool.

### `moveNPC(npc, x, y)`

Sends a raw "move entity" request for an NPC (flagged unsupported/exploit).

- **Native:** `my_moveNPC` at `JSGame.cpp:1421`; registered at `JSGlobalFuncs.h:69` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc < 2` → throws "Not enough parameters were passed to moveNPC!" (`JSGame.cpp:1429-1430`), yet `argv[2]` is read (**argv over-read** when `argc == 2`). `npc`: `JSVAL_TO_OBJECT(argv[0])` with **no object check** (a primitive yields a bogus pointer), private as `myUnit*`; `!pNpc || pNpc->dwType != 1` (`UNIT_MONSTER`) → throws "Invalid NPC passed to moveNPC!" (`JSGame.cpp:1433-1436`). `x`, `y`: unchecked `JSVAL_TO_INT`.
- **Returns:** `true` after sending; `false` + warning "moveNPC requires EnableUnsupported = true in d2bs.ini" if `!Vars.bEnableUnsupported` (`JSGame.cpp:1425-1427`); `false` + warning if not in game.
- **Preconditions:** in game (**WaitForGameReady** twice, `JSGame.cpp:1422-1423`, `1441-1442`); `EnableUnsupported=true` in d2bs.ini `[settings]` (`Helpers.cpp:130`, `153`). The unit is not re-resolved with `FindUnit`.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** `D2NET_SendPacket(17, 1, buf)` (`JSGame.cpp:1444-1451`):

  | Offset | Size | Value |
  |---|---|---|
  | 0 | 1 | `0x59` |
  | 1 | 4 | `npc.dwType` (always 1) |
  | 5 | 4 | `npc.dwUnitId` |
  | 9 | 4 | `x` |
  | 13 | 4 | `y` |
- **Game internals:** `D2NET_SendPacket` (`D2Ptrs.h:362`), `myUnit` (`JSUnit.h:44-51`).
- **Quirks / bugs:** Legacy docs (`doc/globalFuncs.h:1808-1820`) mark it "an exploit function" and say it returns `true`.

### `revealLevel([presets])`

Reveals every room of the player's current level on the automap.

- **Native:** `my_revealLevel` at `JSGame.cpp:1456`; registered at `JSGlobalFuncs.h:71` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `presets` honoured only if `argc == 1` and boolean (`JSGame.cpp:1471-1473`); default `false`.
- **Returns:** **callee-return** on every path.
- **Preconditions:** player unit non-NULL (`JSGame.cpp:1459-1461`); `GameReady()` checked *after* dereferencing `unit->pPath->pRoom1->pRoom2->pLevel` (`JSGame.cpp:1463`, `1475-1478`) — no WaitForGameReady.
- **Threading & blocking:** script thread; **Game-loop lock** for the whole loop (`JSGame.cpp:1474`), re-entered per room in `RevealRoom` (`Room.cpp:14`).
- **Side effects:** for each `Room2` of the level `RevealRoom(room, presets)` (`Room.cpp:5-49`): `D2COMMON_AddRoomData` if the room has no `pRoom1` (removed afterwards), `D2CLIENT_RevealAutomapRoom(pRoom1, TRUE, *p_D2CLIENT_AutomapLayer)`, optional `DrawPresets` (adds automap cells for special presets, `Room.cpp:54+`). Client-side only; nothing sent.
- **Game internals:** `D2CLIENT_RevealAutomapRoom` (RVA `0x58F40`, `D2Ptrs.h:92`), `p_D2CLIENT_AutomapLayer` (`D2Ptrs.h:154`), `InitAutomapLayer` (`D2Helpers.cpp:347-350`), `D2COMMON_AddRoomData`/`RemoveRoomData` (`D2Ptrs.h:328-329`). Details: [world.md](world.md) (`Room.reveal`).
- **Quirks / bugs:** crashes if called while the player exists but its path/room chain is NULL (loading, `ClientStateBusy`). No legacy documentation.

### `takeScreenshot()`

Requests a game screenshot on the next frame.

- **Native:** `my_takeScreenshot` at `JSGame.cpp:1416`; registered at `JSGlobalFuncs.h:68` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** **callee-return**.
- **Preconditions:** none (works in and out of game).
- **Threading & blocking:** sets a flag and returns immediately; the screenshot is taken asynchronously on the game thread by `GameDraw` (`D2Handlers.cpp:406-409`) or `GameDrawOOG` (`D2Handlers.cpp:429-432`), which clear the flag and call `D2WIN_TakeScreenshot()`.
- **Side effects:** `Vars.bTakeScreenshot = true` (`JSGame.cpp:1417`); the game writes the screenshot file (location/format decided by the game).
- **Game internals:** `D2WIN_TakeScreenshot` (fastcall, RVA `0xFA7A0`, `D2Ptrs.h:444`); draw hooks `Patch.h:10`, `Patch.h:35` ([../memory/patches-and-hooks.md](../memory/patches-and-hooks.md)).
- **Quirks / bugs:** no completion signal; multiple calls before the next frame coalesce into one screenshot.

### `playSound(id)`

No-op placeholder.

- **Native:** `my_playSound` at `JSGame.cpp:1030`; registered at `JSGlobalFuncs.h:65` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `id` must pass `JSVAL_IS_INT`, else `false` (`JSGame.cpp:1032-1035`).
- **Returns:** `true` for an int argument; nothing is played (`D2CLIENT_PlaySound` call commented out, `JSGame.cpp:1038`).
- **Preconditions:** none.
- **Threading & blocking:** none.
- **Side effects:** none.
- **Game internals:** the helper `D2CLIENT_PlaySound` (`D2Helpers.cpp:856-870`) has its `CALL` commented out and pushes three NULLs before `RETN` (unbalanced stack if it were ever called).
- **Quirks / bugs:** Legacy docs (`doc/globalFuncs.h:1696-1702`) describe it as playing a sound.

### `quit()`

Leaves the current game.

- **Native:** `my_quit` at `JSGame.cpp:1021`; registered at `JSGlobalFuncs.h:65` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `false` always.
- **Preconditions:** none; `D2CLIENT_ExitGame()` is called whenever `ClientState() != ClientStateMenu` (so also in `Null`/`Busy` states).
- **Threading & blocking:** script thread; no lock; returns immediately (the game leave happens asynchronously).
- **Side effects:** `Vars.bQuitting = true` (`JSGame.cpp:1023`) — aborts running `getPath` searches (`Map/Path/AStarPath.h:126-127`); reset on game join (`D2Handlers.cpp:86`) and in `GameLeave` (`D2Handlers.cpp:519`). Calls `D2CLIENT_ExitGame()` (fastcall, RVA `0x4DD60`, `D2Ptrs.h:114`) from the script thread.
- **Game internals:** as above.
- **Quirks / bugs:** none beyond running `ExitGame` off the game thread.

### `quitGame()`

Leaves the game, shuts D2BS down and terminates the process.

- **Native:** `my_quitGame` at `JSGame.cpp:1009`; registered at `JSGlobalFuncs.h:65` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** never returns normally (`TerminateProcess`); return value preset `false`.
- **Preconditions:** none.
- **Threading & blocking:** runs on the script thread.
  - `Shutdown()` (`D2BS.cpp:143-179`) is a no-op if `!Vars.bNeedShutdown` (`D2BS.cpp:144-145`).
  - Otherwise it sets `Vars.bActive = FALSE` and, unless `Vars.bShutdownFromDllMain`, waits `INFINITE` for the D2BS main thread. That thread leaves its `while (Vars.bActive)` loop (`D2Handlers.cpp:70`) and runs `ScriptEngine::Shutdown()` (`D2Handlers.cpp:116`, `ScriptEngine.cpp:140-166`):
    - `StopAll(true)` stops every script. For the caller it waits at most 100 ms, because it is not the caller's thread and the engine is `Stopping` (`ScriptEngine.cpp:247-252`, `Script.cpp:269-278`).
    - `DisposeScript` only queues a `"DisposeMe"` event for scripts on other threads, including the caller (`ScriptEngine.cpp:81-89`).
    - It then destroys the engine's own context and runtime and calls `JS_ShutDown()` (`ScriptEngine.cpp:155-160`).
  - Back on the caller's thread, `Shutdown()` restores the WNDPROC, removes patches, hooks, the DDE server and the timer, and deletes all `Vars` critical sections, including `cGameLoopSection` (`D2BS.cpp:151-175`).
- **Side effects:** `D2CLIENT_ExitGame()` if not at menu (`JSGame.cpp:1011-1012`), `Shutdown()`, `TerminateProcess(GetCurrentProcess(), 0)` (`JSGame.cpp:1015-1016`).
- **Game internals:** `D2CLIENT_ExitGame` (`D2Ptrs.h:114`).
- **Quirks / bugs:** the caller's own runtime is not destroyed: its disposal is only queued. But `JS_ShutDown()` has already run while that runtime and other script runtimes are alive. The native touches no JSAPI after `Shutdown()` and goes straight to `TerminateProcess`, so the process ends inside the native. Critical sections are deleted while the game thread may still use them (`D2BS.cpp:162-175`). `D2CLIENT_ExitGame()` is called from the script thread. See [../architecture.md](../architecture.md) for the shutdown sequence.

---

## Misc

### `rand(low, high)`

Returns a pseudo-random integer, from the game RNG in game or the CRT RNG out of game.

- **Native:** `my_rand` at `JSGame.cpp:677`; registered at `JSGlobalFuncs.h:44` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** two int-tagged arguments required; otherwise returns `0` (`JSGame.cpp:678-681`). (The subsequent `JS_ConvertArguments("ii")` cannot fail; its "Could not convert Rand aruments" throw is dead code.)
- **Returns:** `seed = D2GAME_Rand(player->dwSeed)` if `ClientState() == ClientStateInGame`, else CRT `rand()` (`JSGame.cpp:690-694`). The first `rand()` call in the process, in or out of game, runs `srand(GetTickCount())` once (`JSGame.cpp:684-688`). Then, if `high > low + 1`, the result is `(seed % (high − low + 1)) + low`; otherwise it is `high` (`JSGame.cpp:705-709`).
- **Preconditions:** none.
- **Threading & blocking:** script thread; no lock.
- **Side effects:** in game, passes a pointer to the player unit's `dwSeed[2]` (`UnitAny+0x20`, `D2Structs.h:620`) to the game RNG (presumably advancing it in place — see [Open questions](#open-questions)). The first call in the process (any state, any thread) calls `srand`.
- **Game internals:** `D2GAME_Rand` (FUNCPTR `DWORD __fastcall(DWORD* seed)`, RVA `0x5C370`, `D2Ptrs.h:479`).
- **Quirks / bugs:**
  - Off-by-one: `rand(n, n+1)` always returns `n+1` (`JSGame.cpp:705`), `rand(high, low)` with `high < low` returns the second argument.
  - `low + 1` and `high − low + 1` are signed `int` arithmetic. Spans ≥ 2³¹ overflow. Int-tagged bounds INT32_MIN/INT32_MAX wrap the divisor to 0, causing an integer-divide fault; smaller overflowing spans give a negative divisor and out-of-range results. `low = 2147483647` overflows `low + 1`.
  - Out of game the result is limited by `RAND_MAX` (32767 in MSVC). The seed guard is one process-wide `static bool` (`JSGame.cpp:684-688`). The MSVC CRT keeps `rand` state per thread (CRT behaviour, not visible in this source), so only the first calling thread is seeded and other script threads start from the default seed.
  - Legacy docs: range "[low,high]" (`doc/globalFuncs.h:832-843`) — not true for adjacent bounds.

### `copyUnit(unit)`

Returns a new, independent Unit object with a copy of the argument's identity snapshot.

- **Native:** `my_copyUnit` at `JSGame.cpp:19`; registered at `JSGlobalFuncs.h:62` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 1` and a non-null object (`JSGame.cpp:22`); else `undefined`. The private's first DWORD is compared **exactly** with `PRIVATE_UNIT` → copies `sizeof(myUnit)` into a new `myUnit`; with `PRIVATE_ITEM` → copies `sizeof(invUnit)` into a new `invUnit` (`JSGame.cpp:29-57`). No class check: other objects' privates are reinterpreted.
- **Returns:** a new `Unit` object (`unit_class` + `unit_methods`/`unit_props`, `JSGame.cpp:35`, `49`); `undefined` for NULL private or other private types; throws "Couldn't copy unit" if `BuildObject` fails.
- **Preconditions:** none (does not touch game memory; the unit need not exist).
- **Threading & blocking:** script thread; no lock.
- **Side effects:** allocates the new struct, owned and freed by `unit_finalize` (`JSUnit.cpp:13-28`).
- **Game internals:** none (`myUnit`/`invUnit` `JSUnit.h:44-62`).
- **Quirks / bugs:** the copy is decoupled from later in-place mutations of the source (e.g. by `Unit.getNext`, per api.html's rationale) — see [unit-methods.md](unit-methods.md).

---

## DailogLine

- **JSClass:** `dialogLine_class`, name string `"DailogLine"` (sic), flags `JSCLASS_HAS_PRIVATE | JSCLASS_HAS_RESERVED_SLOTS(1)`, all stub hooks, finalizer `NULL`, constructor `NULL` (`JSGlobalClasses.cpp:120-122`; extern `JSGlobalClasses.h:30`). Not listed in `global_classes` (`JSGlobalClasses.cpp:143-170`): no global constructor or prototype object is registered; instances get `Object.prototype` (so `Object.prototype.toString` yields `[object DailogLine]`).
- **Constructor:** none — `DailogLine` is not a global name. Instances are created only by [`getDialogLines()`](#getdialoglines) via `BuildObject(cx, &dialogLine_class, 0, 0, 0, 0)` (`JSGame.cpp:191`).
- **Private data:** none (`JS_SetPrivate` is never called; earlier attempts are commented out, `JSGame.cpp:201-203`). **Reserved slot 0** = `PRIVATE_TO_JSVAL(&pTdi->dialogLines[i])` — a raw pointer to a `TransactionDialogsLine_t` inside the game's `TransactionDialogsInfo_t` (`JSGame.cpp:200`, `D2Structs.h:785-798`). Not owned by D2BS; nothing is freed.
- **Identity & lifetime:** `text`/`selectable` are snapshots taken at `getDialogLines()` time; `handler()` dereferences the stored raw pointer at call time and re-reads `bMaybeSelectable` and `handler` from game memory. When the dialog closes or is rebuilt the pointer may refer to freed or different data; nothing detects this. No equality semantics beyond object identity.
- **Properties:**

  | Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
  |---|---|---|---|---|---|---|
  | `text` | plain own data property (`JS_SetProperty`) | string | R/W (ordinary) | every line | `TransactionDialogsLine_t.text` (`wchar_t[120]` @0x000), copied | snapshot |
  | `selectable` | plain own data property | boolean | R/W (ordinary) | every line | `BOOLEAN_TO_JSVAL(bMaybeSelectable)` (@0x10C) | snapshot; **Malformed bool** risk; field name says "maybe" |
  | `handler` | own function property, `JSPROP_ENUMERATE` (`JS_DefineFunction`, `JSGame.cpp:195`) | function | R/W (ordinary) | every line | native `my_clickDialog` | see below |

- **Methods:**

### `DailogLine.prototype.handler()`

Invokes the game's click handler for this dialog line (e.g. an NPC menu entry). Note: `handler` is an own property defined on each instance, not a prototype method; it is unrelated to the global `handler()` (`my_handler`, `JSCore.cpp:553`, [globals-core.md](globals-core.md)).

- **Native:** `my_clickDialog` at `JSGame.cpp:213`; defined per object at `JSGame.cpp:195` (declared arity 0, `JSPROP_ENUMERATE`); declared in `JSGame.h:14`; not in `global_funcs`.
- **Arguments / overloads:** none read. The line is located via `JS_GetReservedSlot(JSVAL_TO_OBJECT(JS_THIS(cx, vp)), 0)` (`JSGame.cpp:217`) — depends on `this` being the DailogLine object.
- **Returns:** `true` after calling the game handler; throws "That dialog is not currently clickable." if the slot pointer is NULL or `bMaybeSelectable == 0` (`JSGame.cpp:220-223`).
- **Preconditions:** none checked (no WaitForGameReady, no check that the dialog still exists).
- **Threading & blocking:** script thread; **no lock** — the game's dialog handler runs concurrently with the game thread; non-blocking.
- **Side effects:** calls `tdl->handler()` (`void __stdcall(void)` at line offset 0x108) — whatever the game bound to that line (open shop, trade, gamble, quest dialog, …); the game sends any packets.
- **Game internals:** `TransactionDialogsLine_t` (`D2Structs.h:785-790`), `p_D2CLIENT_pTransactionDialogsInfo` (`D2Ptrs.h:196`).
- **Quirks / bugs:** detached calls (`var h = line.handler; h()`, or `handler.call(obj)`) read reserved slot 0 of the global or another object and reinterpret it as a line pointer → arbitrary indirect call; stale pointer after the dialog changes → use-after-free/indirect call into garbage. Legacy docs (`doc/globalFuncs.h:1490-1501`) do not mention `handler`; there is no "clickDialog" global despite the native's name.

---

## Code tables

### UI flags (`getUIFlag`)

From `Constants.h:15-54` (header comment: "From D2JSP, updated with info from TheUnknownSoldier"; validity for 1.14d not verified in source). api.html column shows the legacy label at the *same numeric value* for comparison.

| Value | Constants.h | api.html label at same value |
|---|---|---|
| 0x00 | `UI_GAME` | Nothing |
| 0x01 | `UI_INVENTORY` | Inventory screen |
| 0x02 | `UI_CHARACTER` | Character screen |
| 0x03 | `UI_MINISKILL` | Skill speedbar |
| 0x04 | `UI_SKILLTREE` | Skill tree |
| 0x05 | `UI_CHAT_CONSOLE` | Chat box |
| 0x06 | `UI_UNK` ("auto disabled") | Unknown |
| 0x07 | `UI_UNK_EX` ("auto disabled") | Unknown |
| 0x08 | `UI_NPCMENU` = `UI_DIALOG` | NPC menu |
| 0x09 | `UI_ESCMENU_MAIN` | NPC dialog |
| 0x0A | `UI_AUTOMAP` | Main ESC menu |
| 0x0B | `UI_HOTKEY_CONFIG` | Automap |
| 0x0C | `UI_NPCSHOP` | Hotkey configuration |
| 0x0D | `UI_ALTDOWN` = `UI_GROUND_ITEMS` | NPC shop menu |
| 0x0E | `UI_ANVIL` | ALT held |
| 0x0F | `UI_QUEST` | Item submit screen |
| 0x10 | `UI_BARKSCROLL` | Quest button visible |
| 0x11 | `UI_QUEST_LOG` | Bark scroll |
| 0x12 | `UI_STATUS_AREA` | Quest screen |
| 0x13 | `UI_ESCMENU_EX` | Status area |
| 0x14 | `UI_WPMENU` | ESC menu extras |
| 0x15 | `UI_MINIPANEL` | Waypoint screen |
| 0x16 | `UI_PARTY` | Mini-panel visible |
| 0x17 | `UI_TRADE` | Party screen |
| 0x18 | `UI_MESSAGE_LOG` | Trade screen |
| 0x19 | `UI_STASH` | Message log |
| 0x1A | `UI_CUBE` (used by `transmute`) | Stash screen |
| 0x1B | `UI_UNUSED` | Cube screen |
| 0x1C | `UI_INVENTORY_EX` | Inventory extras |
| 0x1D | `UI_INVENTORY_EXX` | Inventory extras 2 |
| 0x1E | `UI_UNUSED_EX` | Belt open |
| 0x1F | `UI_BELT` | Help screen |
| 0x20 | `UI_UNUSED_EXX` | Help button visible |
| 0x21 | `UI_HELP_MENU` | ESC menu (unused?) |
| 0x22 | `UI_HELP_BUTTON` | Mercenary screen |
| 0x23 | `UI_ESCMENU` ("unused??") | Scroll |
| 0x24 | `UI_MERC` | — |
| 0x25 | `UI_SCROLL` | — |

### PvP flags (`getPlayerFlag`)

`Constants.h:125-129`: `PVP_INVITED_YOU 0x01`, `PVP_INVITED_BY_YOU 0x02`, `PVP_ALLIED 0x04`, `PVP_HOSTILED_YOU 0x08`, `PVP_HOSTILED_BY_YOU 0x10`.

### Locations (`clickItem`)

`ItemData.GameLocation` values (`Constants.h:254-262`): `GROUND 0`, `EQUIP 1`, `BELT 2`, `INVENTORY 3`, `STORE 4`, `TRADE 5`, `CUBE 6`, `STASH 7`, `NULL 255`. Click targets passed to the game (`Constants.h:265-269`): `CLICKTARGET_INVENTORY 0`, `TRADE 2`, `CUBE 3`, `STASH 4`, `BELT 5` (unused by `clickItem`).

### Body locations (`clickItem`)

`Constants.h:234-248`: `0 NONE`, `1 HEAD`, `2 AMULET`, `3 BODY`, `4 RIGHT_PRIMARY`, `5 LEFT_PRIMARY`, `6 RIGHT_RING`, `7 LEFT_RING`, `8 BELT`, `9 FEET`, `10 GLOVES`, `11 RIGHT_SECONDARY`, `12 LEFT_SECONDARY`. Merc slots accepted by form B: 1, 3, 4.

### MPQ tables (`getBaseStat`)

`BaseStatTable` (`MPQStats.cpp:4-32`). "rel" = offset into `*p_D2COMMON_sgptDataTable`; "abs" = 0x400000-based VA rebased to the module (`MPQStats.cpp:41-50`). Fields = `wTableSize` (incl. `"end"`); record = `"end"` offset.

| # | Name | Entry | Max-rows | Fields | Record | Field array |
|---|---|---|---|---|---|---|
| 0 | `items` | abs `0x8426F0` | abs `0x8426EC` | 194 | 0x1A8 | `MPQStats.h:65` |
| 1 | `monstats` | rel `0xA78` | rel `0xA80` | 246 | 0x1A8 | `MPQStats.h:261` |
| 2 | `skilldesc` | rel `0xB8C` | rel `0xB94` | 114 | 0x120 | `MPQStats.h:509` |
| 3 | `skills` | rel `0xB98` | rel `0xBA0` | 239 | 0x23C | `MPQStats.h:549` |
| 4 | `objects` | abs `0x96D470` | abs `0x96D474` | 158 | 0x1C0 | `MPQStats.h:790` |
| 5 | `missiles` | rel `0xB64` | rel `0xB6C` | 147 | 0x1A4 | `MPQStats.h:950` |
| 6 | `monstats2` | rel `0xA90` | rel `0xA98` | 110 | 0x134 | `MPQStats.h:1099` |
| 7 | `itemstatcost` | rel `0xBCC` | rel `0xBD4` | 52 | 0x144 | `MPQStats.h:1211` |
| 8 | `levels` | rel `0xC58` | rel `0xC5C` | 142 | 0x220 | `MPQStats.h:1265` |
| 9 | `leveldefs` | rel `0xC60` | none (0xFF) | 43 | 0x9C | `MPQStats.h:1409` |
| 10 | `lvlmaze` | abs `0x96CA08` | abs `0x96CA0C` | 8 | 0x1C | `MPQStats.h:1454` |
| 11 | `lvlsub` | abs `0x96CA10` | abs `0x96CA14` | 23 | 0x15C | `MPQStats.h:1459` |
| 12 | `lvlwarp` | abs `0x96CA00` | abs `0x96CA04` | 13 | 0x30 | `MPQStats.h:1484` |
| 13 | `lvlprest` | rel `0xC64` | rel `0xC68` | 24 | 0x1B0 | `MPQStats.h:1499` |
| 14 | `lvltypes` | abs `0x96C9F0` | abs `0x96C9FC` | 35 | 0x788 | `MPQStats.h:1509` |
| 15 | `charstats` | rel `0xBC4` | rel `0xBC8` | 73 | 0xC4 | `MPQStats.h:1546` |
| 16 | `setitems` | rel `0xC18` | rel `0xC1C` | 96 | 0x1B8 | `MPQStats.h:1621` |
| 17 | `uniqueitems` | rel `0xC24` | rel `0xC28` | 70 | 0x14C | `MPQStats.h:1719` |
| 18 | `sets` | rel `0xC0C` | rel `0xC10` | 68 | 0x128 | `MPQStats.h:1791` |
| 19 | `itemtypes` | rel `0xBF8` | rel `0xBFC` | 36 | 0xE4 | `MPQStats.h:1827` |
| 20 | `runes` | abs `0x96CA9C` | abs `0x96CA98` | 48 | 0x120 | `MPQStats.h:1841` |
| 21 | `cubemain` | abs `0x96D628` | abs `0x96D62C` | 196 | 0x148 | `MPQStats.h:1859` |
| 22 | `gems` | abs `0x96CA94` | abs `0x96CA90` | 42 | 0xC0 | `MPQStats.h:2057` |
| 23 | `experience` | abs `0x96C8A8` | none (0xFF) | 8 | 0x20 | `MPQStats.h:2101` |
| 24 | `pettable` | rel `0xBE8` | rel `0xBF0` | 21 | 0xE0 | `MPQStats.h:2107` |
| 25 | `superuniques` | rel `0xAD4` | rel `0xADC` | 21 | 0x34 | `MPQStats.h:2116` |

Source comment on `experience`: "doesnt tap the last 2 levels of exp, ends at level 97" (`MPQStats.cpp:29`).

### Collision flags (`getCollision`, `checkCollision`)

`ActMap::CollisionFlag` (`Map/Diablo_II/ActMap.h:45-66`): `None 0x0000`, `BlockWalk 0x0001`, `BlockLineOfSight 0x0002`, `Wall 0x0004`, `BlockPlayer 0x0008`, `AlternateTile 0x0010`, `Blank 0x0020`, `Missile 0x0040`, `Player 0x0080`, `NPCLocation 0x0100`, `Item 0x0200`, `Object 0x0400`, `ClosedDoor 0x0800`, `NPCCollision 0x1000`, `FriendlyNPC 0x2000`, `Unknown 0x4000`, `DeadBody 0x8000` ("also portal"), `Avoid 0xFFFF`, `Special 0xF000`. These are D2BS's names for the game's collision word; the game's own interpretation of `checkCollision`'s mask is not in source.

---

## Open questions

- `gold(amount, mode)`: the meaning of `D2CLIENT_GoldDialogAction` values (drop / stash deposit / withdraw / trade) is not defined anywhere in source (`Game.cpp:8-12`).
- `clickParty` modes 4 and 5 call `D2CLIENT_HostilePartyUnit(p, 3)` / `(p, 4)`; which party-screen buttons these are is not stated in source.
- `clickMap` click-type values: only 0 (down) and 2 (up) are corroborated by in-source usage (`JSUnit.cpp:1893-1895`); the 0-5 table exists only in `resources/api.html`.
- `getCursorType` value meanings are not documented in source.
- Whether `D2GAME_Rand(DWORD* seed)` advances `player->dwSeed` in place (mutating client RNG state on every `rand()` call) cannot be confirmed from D2BS source.
- Whether `*p_D2COMMON_sgptDataTable` is populated out of game (affects `getBaseStat`/`getSkillById` at the menu) is not determined by source.
- The semantics of `D2CLIENT_SetUIVar`'s `howset` argument (1/0 used as open/close by `transmute`) are inferred from naming only.
- Which of the two `D2CLIENT_ClickBeltRight` argument orders (`JSGame.cpp:539` vs `JSGame.cpp:648`) matches `ClickBeltRight_I` at RVA `0x98A90` needs disassembly (see [../memory/call-stubs.md](../memory/call-stubs.md)).
- What `D2LANG_GetLocaleText` returns for unknown ids, and the size of the chat buffers behind `p_D2CLIENT_ChatMsg` / `p_D2MULTI_ChatBoxMsg` (overflow bound for `say`).
- Whether the UI-flag numbering in `Constants.h` (1.13-era origin) is correct for 1.14d.
- Whether SpiderMonkey (mozilla-release v22) pads native `argv` up to the declared `nargs`. [embedding.md](../spidermonkey/embedding.md) says it does, but the shipped headers do not settle it. Every over-read listed here except `getMouseCoords`' `argv[0]` is at or beyond the declared `nargs`, so the answer does not change those findings.
- Whether the chat line injected by `say()` in game passes through the `GameInput` intercept, and so consumes `bDontCatchNextMsg` itself. This depends on the code path inside `D2CLIENT_Say_I` (RVA `0x7CBDA`). It is also unknown whether that routine expects a `MSG*` or the `MSG**` that `Say_ASM` actually passes in EBX (`Core.cpp:79`, `107`).

# Unit properties and the global `me`

Scope: the `Unit` JS class (`unit_class`) as seen through its **properties**: class registration, constructor, private data (`myUnit` / `invUnit`), finalizer, equality, how a JS `Unit` is re-resolved to a live `UnitAny*` on every access, what a stale handle returns, threading, and every property in `unit_props` and `me_props` (`JSUnit.h`) together with every `case` of `unit_getProperty` / `unit_setProperty` (`JSUnit.cpp`). It also covers the per-script global `me` object: how it is created, which properties only it has, and how it follows the local player from game to game. Methods (`getNext`, `getStat`, `interact`, ...) and unit search/iteration are documented in [unit-methods.md](unit-methods.md). Everything here was checked against the C++ source. Engine (SpiderMonkey) behaviour that cannot be checked from this repo is marked as such and listed under [Open questions](#open-questions).

## Contents

1. [Quick facts for an RPC replacement](#quick-facts-for-an-rpc-replacement)
2. [Unit](#unit)
   - [Class and registration](#class-and-registration)
   - [Constructor and how instances are obtained](#constructor-and-how-instances-are-obtained)
   - [Private data: `myUnit` / `invUnit`](#private-data-myunit--invunit)
   - [Finalizer](#finalizer)
   - [Identity, resolution and lifetime](#identity-resolution-and-lifetime)
   - [Getter / setter mechanics](#getter--setter-mechanics)
   - [Threading and memory safety](#threading-and-memory-safety)
   - [Properties: common](#properties-common-all-unit-types)
   - [Properties: monster](#properties-monster)
   - [Properties: item](#properties-item)
   - [Properties: object](#properties-object)
   - [Properties: local-player-bound](#properties-local-player-bound-runwalk-weaponswitch)
   - [Methods](#methods)
3. [The global `me`](#the-global-me)
   - [Creation](#creation)
   - [Property set: `me_props` vs `unit_props`](#property-set-me_props-vs-unit_props)
   - [Tracking the player across games](#tracking-the-player-across-games)
   - [me-only properties, any client state](#me-only-properties-any-client-state)
   - [me-only properties, in game only](#me-only-properties-in-game-only)
   - [Settable properties (setter semantics)](#settable-properties-setter-semantics)
4. [Tinyid reference](#tinyid-reference)
5. [Legacy-doc discrepancies](#legacy-doc-discrepancies)
6. [Open questions](#open-questions)

Notation used in the tables:

- **unset**: the getter returns `JS_TRUE` without writing `vp`. The script then sees whatever the engine passed in, which is `undefined` on the first read and, if the slot-caching behaviour described [below](#getter--setter-mechanics) holds, the value currently in the property's slot otherwise (normally the last value successfully read; for a writable `me` property possibly the last value assigned).
- Offsets are byte offsets computed from `D2Structs.h` (32-bit layout, MSVC packing; `#pragma pack(1)` for `D2Structs.h:170-330`). Where a struct's `//` comment disagrees with the computed offset, the table uses the computed one and the difference is listed under [Legacy-doc discrepancies](#legacy-doc-discrepancies). Global VAs assume Game.exe at 0x400000 (`Offset.cpp:21-28` adds the RVA to `GetModuleHandle(NULL)`). See [../memory/offsets.md](../memory/offsets.md) and [../memory/structs.md](../memory/structs.md).

---

## Quick facts for an RPC replacement

| Fact | Source |
|---|---|
| A JS `Unit` holds **no game pointer**. It holds `(dwUnitId, dwType)` plus search-filter fields, and resolves them again on **every** property read via `D2CLIENT_FindUnit` (server-side hash first, then client-side). | `JSUnit.cpp:187-191`, `D2Helpers.cpp:500-505` |
| Every property is a native getter that reads live game memory, calls a D2 function, or reads D2BS global state (`Vars.*`). No property is a snapshot, except the cached slot value returned on failure (see "unset"). | `JSUnit.cpp:47-525` |
| Unit-backed properties return **unset** (no exception, no `undefined` guarantee) when the client is not `ClientStateInGame` or the unit cannot be found. | `JSUnit.cpp:183-194` |
| Reads take **no lock** and run on the script's own thread, while the game thread mutates the same structures. Only `description` takes `cGameLoopSection`. | `JSUnit.cpp:448`, `CriticalSections.h:31-55` |
| `description` **writes game memory** (`p_D2CLIENT_SelectedInvItem` and an unnamed byte at VA 0x7BCBE8, neither restored) and calls `D2CLIENT_LoadItemDesc`, under `cGameLoopSection`. It runs whenever the property is read. Because every property is `JSPROP_ENUMERATE`, anything that reads all enumerable properties (`JSON.stringify(item)`, `for (k in item) f(item[k])`, generic copy/dump helpers) triggers it. Enumerating keys alone (`for...in`, `Object.keys`) does not call getters. | `JSUnit.cpp:444-466`, `js32.h:100-101` |
| `me` is a `Unit` whose handle is `(player gid, UNIT_PLAYER)`. Its gid is refreshed by the D2BS main thread on each game entry. 10 `me` properties are writable: 7 write D2BS `Vars` and 3 (`runwalk`, `automap`, `nopickup`) poke game globals directly. | `ScriptEngine.cpp:348-366`, `Script.cpp:213-215`, `JSUnit.cpp:527-570` |
| Equality is plain object identity: there is no equality hook, so two `Unit` objects for the same game unit are `!=`. Compare `gid` and `type`. | `JSUnit.cpp:33-45` (commented out), `JSGlobalClasses.cpp:108-110` |
| A natural RPC handle is `{type, gid}`. Natives that take a Unit argument resolve it from `dwUnitId`/`dwType` only. The search-filter and owner fields are read only by `getNext` on its own `this` (`JSUnit.cpp:663-704`). `copyUnit` `memcpy`s the whole private (`JSGame.cpp:34`, `:48`). | e.g. `JSGame.cpp:85-90`, `JSRoom.cpp:416-421` |

---

## Unit

### Class and registration

- **JSClass:** `unit_class = {"Unit", JSCLASS_HAS_PRIVATE, JSCLASS_SPEC(JS_PropertyStub, JS_PropertyStub, JS_PropertyStub, JS_StrictPropertyStub, JS_EnumerateStub, JS_ResolveStub, JS_ConvertStub, unit_finalize, unit_ctor)}` at `JSGlobalClasses.cpp:108-110`. `JSCLASS_SPEC` (`js32.h:163-164`) expands to `add, del, get, set, enumerate, resolve, convert, finalize, NULL, NULL, NULL, ctor, NULL`, i.e. `checkAccess`, `call`, `hasInstance` and `trace` are NULL and `unit_ctor` is the `construct` hook (field order: `dependencies/include/jsapi.h:2780-2802`). The class-level `getProperty`/`setProperty` are the no-op `JS_PropertyStub`/`JS_StrictPropertyStub`. Each property has its own native getter/setter.
- **Registration:** `global_classes[0] = {&unit_class, 0, unit_ctor, 0, unit_methods, unit_props, NULL, NULL}` (`JSGlobalClasses.cpp:145`). For every script context, `contextCallback` (`ScriptEngine.cpp:329`) loops over `global_classes` (`ScriptEngine.cpp:358-359`) and calls `ScriptEngine::InitClass` → `JS_InitClass(cx, global, NULL, classp, classp->construct, 0, props, methods, s_props, s_methods)` (`ScriptEngine.cpp:230-234`; both static tables are NULL for Unit). A failure throws a C++ `std::exception("Couldn't initialize the class")`. Result: a global `Unit` constructor (arity 0, prototype chained to `Object.prototype` because `parent_proto` is NULL), with `unit_props` and `unit_methods` defined on `Unit.prototype`.
- **Per-instance definitions:** instances are built with `BuildObject(cx, &unit_class, unit_methods, unit_props|me_props, priv)` (`js32.cpp:8-28`). `BuildObject` calls `JS_NewObject(cx, classp, NULL, NULL)`, then `JS_DefineFunctions` and `JS_DefineProperties` **on the instance itself**, then `JS_SetPrivate`. So every Unit object carries its own copy of all 25 method function objects and 49 accessor properties (80 for `me`), which shadow the identical ones on `Unit.prototype`.
- **Property flags:** `JSPROP_PERMANENT_VAR = READONLY|ENUMERATE|PERMANENT` for read-only properties, and `JSPROP_STATIC_VAR = ENUMERATE|PERMANENT` for writable ones (`js32.h:100-101`). Neither includes `JSPROP_SHARED`, so every property has a value slot (`dependencies/include/jsapi.h:1419`). Each is defined with a tinyid (`JSPropertySpec.tinyid` is `int8_t`, `dependencies/include/jsapi.h:3028-3034`; the largest id used is 125). All getters are `unit_getProperty`. The setter is `unit_setProperty` for the 10 writable `me` properties and NULL otherwise.

### Constructor and how instances are obtained

`new Unit(...)` always throws. `unit_ctor` is declared by `CLASS_CTOR(unit)` (`JSUnit.h:7`) and defined by `EMPTY_CTOR(unit)` (`JSUnit.cpp:11`), which expands to `JS_ReportError(cx, "Invalid Operation"); return JS_FALSE;` (`js32.h:113-117`, `js32.h:136-139`). Calling `Unit(...)` without `new` also invokes `unit_ctor` (it is the `JS_InitClass` constructor native) and throws the same way.

Scripts obtain Unit objects only from these natives (full semantics in [unit-methods.md](unit-methods.md) and [globals-game.md](globals-game.md)):

| Creator | Native / line | Private struct, `_dwPrivateType` | `dwUnitId` / `dwType` | `dwClassId` / `dwMode` / `szName` | Owner fields |
|---|---|---|---|---|---|
| `getUnit(type, name\|classid, mode, gid)` | `unit_getUnit` `JSUnit.cpp:572` (alloc `:617-629`) | `myUnit`, `PRIVATE_UNIT` | actual id / actual type | **search filters** as passed (`-1` if omitted), filter name (UTF-8) | – |
| `getUnit(100)` (cursor item), `getUnit(101)` (selected unit, else `*p_D2CLIENT_SelectedInvItem`) | `JSUnit.cpp:603-608` | same | same | filters (`-1`) | – |
| `unit.getNext(...)` | `unit_getNext` `JSUnit.cpp:642` | **mutates `this` in place** (`:678`, `:721`). Does not create an object. | new id | filters may be replaced (`:656-666`) | – |
| `unit.getItems()` | `unit_getItems` `JSUnit.cpp:1292` (alloc `:1317-1329`) | **`invUnit` tagged `PRIVATE_UNIT`** (`:1322`) | item id / `UNIT_ITEM` | actual classid / actual mode / `""` | owner id/type set |
| `unit.getItem(...)` | `unit_getItem` `JSUnit.cpp:1796` (alloc `:1837-1849`) | `invUnit`, `PRIVATE_ITEM` | actual | filters / filter name (CP_ACP, `:1818`) | owner = `this` |
| `unit.getParent()` (monster owner / item owner / missile owner) | `unit_getParent` `JSUnit.cpp:1572` (`:1596`, `:1621`, `:1637`) | `myUnit`, `PRIVATE_UNIT` | actual | actual / actual / `""` | – |
| `unit.getMerc()` | `unit_getMerc` `JSUnit.cpp:1658` | `myUnit`, `PRIVATE_UNIT` | merc id / `UNIT_MONSTER` | actual classid / **0** / `""` | – |
| `getInteractedNPC()` | `my_getInteractedNPC` `JSGame.cpp:1386` (`:1396-1408`) | `myUnit`, `PRIVATE_UNIT` | actual | actual / actual / `""` | – |
| `copyUnit(u)` | `my_copyUnit` `JSGame.cpp:19` (`:29-57`) | `memcpy` of the source private, `sizeof(myUnit)` if its tag `== PRIVATE_UNIT`, `sizeof(invUnit)` if `== PRIVATE_ITEM` (no class check on `u`; a `getItems()` object is copied as a `myUnit`) | copied | copied | copied (`PRIVATE_ITEM` only) |
| global `me` | `contextCallback` `ScriptEngine.cpp:348-366` | `myUnit`, `PRIVATE_UNIT` | player gid or 0 / `UNIT_PLAYER` | `-1` / `-1` / `""` | – |

`copyUnit(me)` produces an ordinary Unit (built with `unit_props`, not `me_props`) whose gid is frozen: `UpdatePlayerGid` only updates the original `me` (`Script.cpp:213-215`).

### Private data: `myUnit` / `invUnit`

Defined in `JSUnit.h:44-62`. Both start with the same `DWORD` layout as `struct Private { DWORD dwPrivateType; }` (`D2BS.h:25-27`). Type tags: `PRIVATE_UNIT 1`, `PRIVATE_ITEM 3` (`D2BS.h:22-23`).

| Off | Field | Struct | Meaning / who reads it |
|---|---|---|---|
| 0x00 | `_dwPrivateType` | both | `PRIVATE_UNIT` or `PRIVATE_ITEM`. Read by `unit_finalize` (to choose the delete type), `unit_getNext` (world iteration vs inventory iteration) and `copyUnit`. Almost every native, `unit_getProperty` included (`JSUnit.cpp:188`), tests `(t & PRIVATE_UNIT) == PRIVATE_UNIT`, which **both** tags pass (3 & 1 == 1). |
| 0x04 | `dwUnitId` | both | Game unit id (`UnitAny.dwUnitId`). **Identity key.** Changed only by `getNext` (`JSUnit.cpp:678`, `:721`) and, for `me`, by `Script::UpdatePlayerGid` (`Script.cpp:214`). |
| 0x08 | `dwClassId` | both | For `getUnit`/`getItem` objects this is the **class-id filter** (possibly `-1`), not the unit's class. For `me` it is `-1` (`ScriptEngine.cpp:353`). For the other creators it is the real `dwTxtFileNo`. Read only by `getNext`. No property reads it: `classid` reads live `UnitAny.dwTxtFileNo`. |
| 0x0C | `dwType` | both | Unit type, the second half of the identity key. Always the actual type (`UNIT_PLAYER` for `me`). |
| 0x10 | `dwMode` | both | Mode filter (`getUnit`/`getItem`), `-1` (`me`, `ScriptEngine.cpp:352`), 0 (`getMerc`, `JSUnit.cpp:1676`), or the actual mode at creation time (other creators). Read only by `getNext`. |
| 0x14 | `szName[128]` | both | Name filter for `getNext` (`""` when none): UTF-8 for `getUnit`/`getNext` (`JSUnit.cpp:589`, `:657`), CP_ACP for `getItem` (`JSUnit.cpp:1818`). Never returned by a property. |
| 0x94 | `dwOwnerId` | `invUnit` | Owner gid. Read only by the `PRIVATE_ITEM` branch of `getNext` (`JSUnit.cpp:688`). `getItems()` fills it (`JSUnit.cpp:1328`) but tags the object `PRIVATE_UNIT`, so for those objects it is never read. |
| 0x98 | `dwOwnerType` | `invUnit` | Owner type (same use). |

Sizes: `myUnit` 0x94, `invUnit` 0x9C. Ownership: allocated with `new` by the creator, attached with `JS_SetPrivate` by `BuildObject` (`js32.cpp:22-23`), and freed only by `unit_finalize`. The `// leaked?` comments at `JSUnit.cpp:617`, `JSUnit.cpp:1837` and `JSGame.cpp:1396`, and `// leaks` at `JSUnit.cpp:1621`, are not real leaks once the object is built. The struct does leak on every path that returns after `new` without building the object, because nothing frees it there: `BuildObject` failure (`JSUnit.cpp:634-635`, `:1332-1335`, `:1608-1609`, `:1680-1682`, `:1853-1854`, `JSGame.cpp:1409-1410`; the item and missile branches of `getParent` do not check the result at all and return `OBJECT_TO_JSVAL(NULL)`, `JSUnit.cpp:1632-1634`, `:1650-1651`), and `getParent` on a missile whose owner is not found (`new` at `JSUnit.cpp:1637`, early return at `:1641`).

### Finalizer

`unit_finalize(JSFreeOp*, JSObject*)` at `JSUnit.cpp:13-31`:

- `PRIVATE_UNIT` → `delete (myUnit*)p`; `PRIVATE_ITEM` → `delete (invUnit*)p`; any other tag is not freed. Then `JS_SetPrivate(obj, NULL)`.
- `getItems()` objects are `invUnit` allocations tagged `PRIVATE_UNIT` (`JSUnit.cpp:1317`, `:1322`), so they are deleted through a `myUnit*`. That is a size/type mismatch: formally UB, but harmless with MSVC's default `operator delete` for POD types.
- It runs during GC of the script's own runtime (one runtime per script, `Script.cpp:120`), normally on that script's thread, and for every remaining Unit when `~Script` calls `JS_DestroyRuntime` (`Script.cpp:55`). `ScriptEngine::DisposeScript` deletes the script directly only on the script's own thread and otherwise posts a `DisposeMe` event (`ScriptEngine.cpp:81-89`). `Unit.prototype` has a NULL private, which the `if (lpUnit)` check handles.
- At script teardown, the finalizer for `me` frees the `myUnit` that `Script::me` still points to. See [Threading and memory safety](#threading-and-memory-safety).

There is **no** equality hook. `unit_equal` is declared at `JSUnit.h:42`, but its body is commented out (`JSUnit.cpp:33-45`, "not 1.8 compatable") and it is never registered (the `JSExtendedClass unit_class_ex` is commented out at `JSGlobalClasses.cpp:124-128`). `==` and `===` therefore compare object identity.

### Identity, resolution and lifetime

On every property get, `unit_getProperty` (`JSUnit.cpp:47`) does the following:

1. Handles the me-only ids (first `switch`, `JSUnit.cpp:55-181`). These need no unit.
2. Returns if `ClientState() != ClientStateInGame` (`JSUnit.cpp:183-184`). `ClientState()` (`D2Helpers.cpp:125`) is itself a live check: it calls `D2CLIENT_GetPlayerUnit()` (`D2Ptrs.h:122`), reads `*p_D2WIN_FirstControl` (`D2Ptrs.h:462`) and follows `player->pPath->pRoom1->pRoom2->pLevel->dwLevelNo`. In-game requires a player unit, no menu controls (`*p_D2WIN_FirstControl == NULL`), `pUpdateUnit == NULL`, `pInventory` and `pPath` set, and a complete `pPath->pRoom1->pRoom2->pLevel` chain with a non-zero `dwLevelNo` (`D2Helpers.cpp:130-140`). A player with `pUpdateUnit` set or an incomplete chain gives `ClientStateBusy`. Which game situations (loading, act change) produce that is not visible in source.
3. Reads the private with `JS_GetPrivate(cx, obj)` with **no class check** (`JSUnit.cpp:187`), and returns if it is NULL or fails the `& PRIVATE_UNIT` test (`:188-189`). If the getter is ever invoked with a receiver of another class (e.g. an object whose prototype is a Unit; see [Open questions](#open-questions)), this reads that object's private slot unchecked.
4. Calls `pUnit = D2CLIENT_FindUnit(dwUnitId, dwType)` (`JSUnit.cpp:191`). This is a D2BS helper (`D2Helpers.cpp:500-505`): it returns NULL for id `-1`, otherwise tries `D2CLIENT_FindServerSideUnit(id, type)` (`D2Ptrs.h:68`, VA 0x4639B0) and then `D2CLIENT_FindClientSideUnit(id, type)` (`D2Ptrs.h:67`, VA 0x463990). Both are D2's own lookups keyed by id and type. (The D2BS search helpers in `Unit.cpp` walk `p_D2CLIENT_ServerSideUnitHashTables` / `ClientSideUnitHashTables` instead, `D2Ptrs.h:159-160`. See [unit-methods.md](unit-methods.md).)
5. If `pUnit` is NULL, returns unset (`JSUnit.cpp:192-194`). Otherwise it reads fields from `pUnit` (second `switch`, `JSUnit.cpp:197-522`).

Consequences:

- **Stale handle:** when the unit is no longer in the client's unit tables (e.g. it went out of range and was removed, or the game changed), every unit-backed property quietly returns unset. Nothing throws, and no `isValid` flag exists. Scripts detect a vanished unit only by re-querying (e.g. `getUnit(type, -1, -1, gid)`) or by comparing a value with its last reading.
- **Aliasing:** resolution is by `(id, type)` only. If the game later assigns the same id to a different unit of the same type (most likely in a new game; whether ids are reused within a game is an [open question](#open-questions)), an old handle silently resolves to the new unit. `InGame` scripts are aborted on return to the menu (`ScriptEngine.cpp:315`), so only `OutOfGame` and `Command` (console) scripts can hold handles across games.
- **No snapshot:** a Unit object freezes nothing. `classid`, `mode`, `name` and so on are re-read on each access.
- **Cost per read:** two global reads (`JSUnit.cpp:48-49`), one `ClientState()` (a `D2CLIENT_GetPlayerUnit()` call, a global read and a pointer chase), and up to two D2 hash lookups, even for properties such as `type` that the handle already holds. The me-only phase-1 ids pay the same cost: after phase 1 they still go through the client-state check and `D2CLIENT_FindUnit` before falling through phase 2's `default`.

### Getter / setter mechanics

- **Signatures:** `JSAPI_PROP(unit_getProperty)` = `JSBool (JSContext*, JSHandleObject obj, JSHandleId id, JSMutableHandleValue vp)`; `JSAPI_STRICT_PROP(unit_setProperty)` adds `JSBool strict` (`js32.h:141-142`). The property is identified by `JSVAL_TO_INT` of `JS_IdToValue(id)`, i.e. the tinyid (`JSUnit.cpp:50-55`, `:528-530`). `strict` is ignored.
- **Two-phase getter:** phase 1 (`JSUnit.cpp:55-181`) runs for every id and every receiver, **before** any game-state check. Only me-only ids have cases there. Phase 2 (`JSUnit.cpp:197-522`) needs in-game state and a resolved unit. A me-only id that phase 1 handled falls through phase 2's `default` without effect.
- **Slot caching (engine behaviour, not verifiable here):** the properties are not `JSPROP_SHARED`, so each has a value slot. In SpiderMonkey of this era, the generic native-get path seeds `vp` with the slot's current value before calling the getter and writes the getter's result back into the slot. If that holds, an unset return yields the **last value stored in the slot** (initially `undefined`): normally the last value the getter produced, so a stale `unit.x` would keep returning its last coordinate instead of `undefined`. For a writable property the slot can also hold the last value a script assigned (see [Settable properties](#settable-properties-setter-semantics)). Script contexts end up with only `JSOPTION_STRICT | JSOPTION_VAROBJFIX`: `Script.cpp:131` runs after `JS_NewContext` and replaces the `METHODJIT|ION|...` options set by the context callback at `ScriptEngine.cpp:337`. The method and Ion JIT options are therefore off, and property reads are expected to go through the interpreter's generic path. See [Open questions](#open-questions) and [../spidermonkey/embedding.md](../spidermonkey/embedding.md).
- **Read-only properties:** assignment never reaches `unit_setProperty`. Sloppy code ignores it. Strict-mode code gets a TypeError. With `JSOPTION_STRICT` (extra warnings) enabled, sloppy code also gets a "read-only" strict warning. Both of these are engine behaviour. Warnings never trigger `quitonerror` (`ScriptEngine.cpp:446`).
- **Writable `me` properties:** `unit_setProperty` (`JSUnit.cpp:527-570`) always returns `JS_TRUE`. It never throws, and values of the wrong type are ignored silently. It does not check client state. Details are in [Settable properties](#settable-properties-setter-semantics).
- **JS types:** `setInt32` for most numeric fields (a `DWORD` above 0x7FFFFFFF would come back negative); `setNumber((jsdouble)...)` for `gid`, `owner` (unsigned-safe; stored as int32 when it fits, `dependencies/include/js/Value.h:925-933`); `setDouble` for `pid`, `gamestarttime`, `ladder`.
- **String encodings:**
  - `JS_NewStringCopyZ` (`account`, `charname`, `gamename`, `gamepassword`, `gameserverip`, `realm`, `realmshort`) and `JS_InternString` (`code`, `prefix`, `suffix`, `prefixes`, `suffixes`) take a C `char*`. SpiderMonkey 22 has no "C strings are UTF-8" switch (no `JS_SetCStringsAreUTF8` exists in the headers), so these bytes are widened 1:1, i.e. read as Latin-1 (engine behaviour).
  - `name` is the one byte string decoded as UTF-8 (`AnsiToUnicode` defaults to `CP_UTF8`, `Helpers.h:9`).
  - `fname`, `description`, `profile` and `windowtitle` come from UTF-16 sources and are passed through unchanged.
  - `name`, `fname`, `description`, `code` (including its `"Unknown"` fallback), `prefix`, `suffix` and every element of `prefixes`/`suffixes` are **interned** (`JS_InternUCString` / `JS_InternString`). Whether interned atoms stay pinned for the runtime's lifetime is engine behaviour (open question). If they do, reading many distinct descriptions grows memory until the script ends.
- **Arrays** (`prefixes`, `suffixes`, `prefixnums`, `suffixnums`): a new `Array` is created on every read, so `u.prefixes !== u.prefixes`. Elements are set only for slots that pass the test (non-NULL `D2COMMON_GetItemMagicalMods` result for the string arrays, non-zero id for the number arrays), so the array can be **sparse** (e.g. `[ , <affix>]`, `length` 2). The `JS_NewArrayObject` result is not NULL-checked (`JSUnit.cpp:339`, `:355`, `:371`, `:387`).
- **Requests:** `JS_BeginRequest` at `JSUnit.cpp:52` has no matching `JS_EndRequest` on the early `return JS_TRUE` paths at `:69`, `:75`, `:92`, `:97`, `:102`. This is harmless because `JS_THREADSAFE` is undefined (`dependencies/include/js-config.h:16`), so requests do no real work. It would leak a request in a thread-safe build.

### Threading and memory safety

- Getters and setters run on the thread of the script that touched the property: each script has its own thread (`Script.cpp:104-116`) and its own `JSRuntime` (`Script.cpp:120`). Event handlers run on the owning script's thread through `ExecScriptEvent`, e.g. from the operation callback (`ScriptEngine.cpp:315-322`); a packet event raised on the script's own thread runs synchronously there (`Events.cpp:306-307`). See [events.md](events.md) and [../architecture.md](../architecture.md).
- **No synchronization** with the game thread, except for `description`. All other cases read `UnitAny` and its sub-structures (`pPath`, `pItemData`, `pMonsterData`, `pObjectData`, `pInventory`, `pStats`) and call D2 functions (`D2COMMON_GetUnitStat`, `D2CLIENT_GetUnitX`, `D2CLIENT_GetItemName`, ...) while the game thread may be freeing or moving those structures. A unit can be freed between `D2CLIENT_FindUnit` returning it and the dereference. In that case the read uses freed memory (garbage value or access violation). Nothing in the getter prevents this.
- `description` creates an `AutoCriticalRoom` (`JSUnit.cpp:448`), which enters `Vars.cGameLoopSection` (`CriticalSections.h:31-55`). The game thread owns that section and releases it only briefly: in `GameDraw` when `Vars.SectionCount > 0` (`D2Handlers.cpp:410-418`) and in `TimerProc` (`D2Handlers.cpp:493-504`). So a `description` read blocks until the next frame or timer yield, and the game loop is held off while the getter runs. While the game thread waits on a blocking packet event it releases the section (`ReleaseGameLock`, `Events.cpp:312`, `:347-350`), so a `description` read inside such a handler can proceed. `CRITICAL_SECTION` is recursive, so a thread that already owns the section does not deadlock on it.
- `me.windowtitle` calls `GetWindowTextW(D2GFX_GetHwnd())` (`JSUnit.cpp:142`). For a window in the same process but on another thread, Win32 sends `WM_GETTEXT` synchronously, so the read waits on the window thread's message loop.
- Writes to `me`'s handle: `Script::UpdatePlayerGid` (`Script.cpp:213-215`) runs on the D2BS main thread `D2Thread`, for every script in `ScriptEngine::scripts` (`D2Handlers.cpp:84`, through `ForEachScript`) and then once more for the console (`D2Handlers.cpp:85` → `ScriptEngine.cpp:178-180`). The console is also in `scripts` under the key `L"console"` (`ScriptEngine.cpp:131`), so it is updated twice. The write is an aligned DWORD store, which is atomic on x86. However:
  - `Script::me` (`Script.h:114`) is not in the constructor's initializer list (`Script.cpp:15-17`). It is assigned only in `Script::Run` (`Script.cpp:141-144`), on the script's thread.
  - A script is inserted into `ScriptEngine::scripts` at `CompileFile` (`ScriptEngine.cpp:42-43`), before its thread runs. `ForEachScript` copies the list under `LockScriptList` but invokes the callbacks **after** unlocking (`ScriptEngine.cpp:210-224`).
  - When a script's `main` returns and `DisableCache` is on, `ScriptThread` calls `DisposeScript`, which erases it from the map and `delete`s it on its own thread (`Script.cpp:479-481`, `ScriptEngine.cpp:71-82`). `~Script` destroys the runtime (`Script.cpp:53-55`), whose finalizer frees the `myUnit`.
  - So a game-entry `UpdatePlayerGid` can write through an uninitialized `me` (script registered but `Run` not reached yet) or through a freed `Script`/`myUnit` (script disposed between the list copy and the callback).

### Properties: common (all unit types)

All rows are phase 2: in game, unit resolved, else unset. "Both" means the property is in `unit_props` and `me_props`.

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `type` | `UNIT_TYPE` (0) | number (int32) | R | all; both | `pUnit->dwType` (UnitAny+0x00) | 0 player, 1 monster, 2 object, 3 missile, 4 item, 5 tile (`Constants.h:361-366`). `JSUnit.cpp:198`. |
| `classid` | `UNIT_CLASSID` (1) | int32 | R | all; both | `pUnit->dwTxtFileNo` (+0x04) | Row in the type's txt table. Not `myUnit.dwClassId`. `JSUnit.cpp:201`. |
| `gid` | `UNIT_ID` (2) | number | R | all; both | `pUnit->dwUnitId` (+0x0C) via `setNumber(double)` | Equals the handle's id while the unit resolves; stale → unset. `JSUnit.cpp:228-232`. |
| `mode` | `UNIT_MODE` (3) | int32 | R | all; both | `pUnit->dwMode` (+0x10) | Mode enum per type, e.g. `ITEM_MODE_*` (`Constants.h:348-356`). `JSUnit.cpp:204`. |
| `name` | `UNIT_NAME` (4) | string (interned) | R | all; both | `GetUnitName(pUnit, tmp, 128)` (`D2Helpers.cpp:59`), then `AnsiToUnicode` (UTF-8): monster `D2CLIENT_GetUnitName` = `D2CLIENT_GetUnitName_STUB` → `jmp D2CLIENT_GetUnitName_I` (`D2Helpers.cpp:712-717`, ASMPTR `D2Ptrs.h:247`, VA 0x464A60), UTF-16 → UTF-8; player `pPlayerData->szName` (PlayerData+0x00, `char[16]`); item `D2CLIENT_GetItemName(pUnit, buf, 256)` (`D2Ptrs.h:74`, VA 0x48C060), text before the first `'\n'`; object/tile `pObjectData->pTxt->szName` (ObjectTxt+0x00, `char[0x40]`, the untranslated objects.txt name); otherwise `"Unknown"` | Missiles, players with NULL `pPlayerData` and objects/tiles with NULL `pObjectData`/`pTxt` give `"Unknown"`. 128-byte buffer (`JSUnit.cpp:208`). Item names go UTF-16 → `UnicodeToAnsi` (UTF-8, `Helpers.h:10`) → cut at `'\n'` → `AnsiToUnicode` (UTF-8), which is lossless. `strcpy_s` into the buffer (`D2Helpers.cpp:71`, `:81`, `:87`) calls the CRT invalid-parameter handler if the source is ≥128 bytes. The repo installs no `_set_invalid_parameter_handler`, so the CRT default applies (it terminates the process in release builds). In practice only an item name's first line could be that long, and a non-Latin first line is 2-3 UTF-8 bytes per character. Monster names: `WideCharToMultiByte` returns 0 for a NULL name (result `""`, because `tmp` is pre-zeroed) or for a name longer than 127 UTF-8 bytes (the buffer may then be left unterminated). Player names are decoded as UTF-8 even if they are ANSI. `JSUnit.cpp:207-213`. |
| `act` | `UNIT_ACT` (6) | int32 | R | all; both | `pUnit->dwAct + 1` (+0x18) | 1-based act. `JSUnit.cpp:220-222`. |
| `x` | `UNIT_XPOS` (7) | int32 | R | all; both | `D2CLIENT_GetUnitX(pUnit)` (`D2Ptrs.h:80`, `__fastcall`, VA 0x45ADF0) | Computed by the game function; D2BS does not read the path struct itself. `JSUnit.cpp:233-235`. |
| `y` | `UNIT_YPOS` (8) | int32 | R | all; both | `D2CLIENT_GetUnitY(pUnit)` (`D2Ptrs.h:81`, VA 0x45AE20) | `JSUnit.cpp:236-238`. |
| `targetx` | `UNIT_TARGETX` (52) | int32 | R | `dwType` 0, 1, 3 only; both | `pUnit->pPath->xTarget` (UnitAny+0x2C → Path+0x10, WORD) | Other types unset. No `pPath` NULL check (crashes if NULL). `JSUnit.cpp:239-246`. |
| `targety` | `UNIT_TARGETY` (53) | int32 | R | `dwType` 0, 1, 3; both | `pUnit->pPath->yTarget` (Path+0x12) | Same as `targetx`. `JSUnit.cpp:247-254`. |
| `area` | `UNIT_AREA` (10) | int32 | R | units in a room; both | `D2COMMON_GetRoomFromUnit(pUnit)` (`D2Ptrs.h:310`, VA 0x620BB0) → `Room1->pRoom2` (+0x10) → `Room2->pLevel` (+0x58) → `Level->dwLevelNo` (+0x1D0) | Unset if any link is NULL (e.g. a unit that has no room). `JSUnit.cpp:223-227`. |
| `hp` | `UNIT_HP` (11) | int32 | R | all; both | `D2COMMON_GetUnitStat(pUnit, 6, 0) >> 8` (`D2Ptrs.h:306`, VA 0x625480) | Stat 6 = `STAT_HP` (`Constants.h:170`). The `>> 8` drops the low 8 bits (D2 keeps life/mana/stamina with 8 fractional bits; the source only shows the shift). Unsigned shift of a `DWORD`, so no sign extension. `JSUnit.cpp:255-257`. |
| `hpmax` | `UNIT_HPMAX` (12) | int32 | R | all; both | `GetUnitStat(pUnit, 7, 0) >> 8` | `STAT_MAXHP` (`Constants.h:171`). `JSUnit.cpp:258-260`. |
| `mp` | `UNIT_MP` (13) | int32 | R | all; both | `GetUnitStat(pUnit, 8, 0) >> 8` | `STAT_MANA` (`Constants.h:172`). `JSUnit.cpp:261-263`. |
| `mpmax` | `UNIT_MPMAX` (14) | int32 | R | all; both | `GetUnitStat(pUnit, 9, 0) >> 8` | `STAT_MAXMANA` (`Constants.h:173`). `JSUnit.cpp:264-266`. |
| `stamina` | `UNIT_STAMINA` (15) | int32 | R | all; both | `GetUnitStat(pUnit, 10, 0) >> 8` | `STAT_STAMINA` (`Constants.h:174`). `JSUnit.cpp:267-269`. |
| `staminamax` | `UNIT_STAMINAMAX` (16) | int32 | R | all; both | `GetUnitStat(pUnit, 11, 0) >> 8` | `STAT_MAXSTAMINA` (`Constants.h:175`). `JSUnit.cpp:270-272`. |
| `charlvl` | `UNIT_CHARLVL` (17) | int32 | R | all; both | `GetUnitStat(pUnit, 12, 0)` (`STAT_LEVEL`, `Constants.h:176`) | Not scaled. `JSUnit.cpp:273-275`. |
| `itemcount` | `UNIT_ITEMCOUNT` (36) | int32 | R | units with `pInventory`; both | `pUnit->pInventory->dwItemCount` (UnitAny+0x60 → Inventory+0x28) | Unset if there is no inventory. `JSUnit.cpp:471-474`. |
| `owner` | `UNIT_OWNER` (38) | number | R | all; both | `pUnit->dwOwnerId` (+0x98) via `setNumber(double)` | What the field means for each unit type cannot be determined from source. To find an item's container unit use `getParent()`. `JSUnit.cpp:481-483`. |
| `ownertype` | `UNIT_OWNERTYPE` (39) | int32 | R | all; both | `pUnit->dwOwnerType` (+0x94) | `JSUnit.cpp:484-486`. |
| `direction` | `UNIT_DIRECTION` (42) | int32 | R | units with `pPath && pPath->pRoom1`; both | `pUnit->pPath->bDirection` (Path+0x64, BYTE) | Applied to every type. For items and objects the +0x2C union holds `ItemPath`/`ObjectPath` (`D2Structs.h:393-398`, `:597-603`), which define fields only up to +0x14. Reading `pRoom1` (+0x1C) and +0x64 through them goes beyond the declared struct. `JSUnit.cpp:498-502`. |

### Properties: monster

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `spectype` | `UNIT_SPECTYPE` (33) | int32 | R | `dwType == UNIT_MONSTER && pMonsterData`; both | Bitfield byte MonsterData+0x16 (`D2Structs.h:549-556`): `fMinion` (bit 4) → `0x08`; `fBoss` (bit 3) → `0x04`; `fChamp` (bit 2) → `0x02`; `fBoss && fNormal` (bit 1) → `0x01`; `fNormal` alone → `SpecType \|= 0x00` (no-op) | Other types unset. Ordinary monsters give `0`. Despite its name, `fNormal` only contributes when combined with `fBoss`. The legacy docs call `0x01` a "Normal" boss (`doc/Unit.h:621-629`). `JSUnit.cpp:280-297`. |
| `uniqueid` | `UNIT_UNIQUEID` (40) | int32 | R | all types; **`unit_props` only** | If `dwType == UNIT_MONSTER && pMonsterData->fBoss && pMonsterData->fNormal`: `pMonsterData->wUniqueNo` (MonsterData+0x26, WORD); otherwise `-1` | Non-monsters return `-1` (not unset). `pMonsterData` is not NULL-checked here (`JSUnit.cpp:299`), unlike `spectype`. `JSUnit.cpp:298-303`. |

### Properties: item

Unless a row says otherwise, the condition is `pUnit->dwType == UNIT_ITEM && pUnit->pItemData`. Other units get unset. All rows are phase 2.

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `code` | `ITEM_CODE` (19) | string (interned) | R | **see quirk**; both | `D2COMMON_GetItemText(pUnit->dwTxtFileNo)` (`D2Ptrs.h:299`, VA 0x6335F0) → `ItemTxt.szCode`, first 3 bytes copied and NUL-terminated (ItemTxt+0x80) | Returns `"Unknown"` if there is no txt. Wrong guard: `if (!(dwType == UNIT_ITEM) && pItemData) break;` (`JSUnit.cpp:305`) skips only non-items whose +0x14 union pointer is non-NULL. A non-item with a NULL data pointer, or any item (even with NULL `pItemData`), falls through and gets an item code looked up by its classid. Only 3 bytes are copied, so 4-character codes are truncated. `JSUnit.cpp:304-317`. |
| `prefix` | `ITEM_PREFIX` (20) | string (interned) | R | item | `D2COMMON_GetItemMagicalMods(pItemData->wMagicPrefix[0])` (`D2Ptrs.h:321`, VA 0x633EE0; ItemData+0x38) | Unset if the name is NULL. The id is passed even when it is 0; whether the game returns NULL for id 0 is not visible in source (open question). The result is a `char*` widened as Latin-1. Rare-name affixes (`wRarePrefix`/`wRareSuffix`, ItemData+0x32/+0x34) and `wAutoPrefix` (+0x36) are not exposed. The function is called twice. `JSUnit.cpp:318-322`. |
| `suffix` | `ITEM_SUFFIX` (21) | string (interned) | R | item | `GetItemMagicalMods(pItemData->wMagicSuffix[0])` (ItemData+0x3E) | `JSUnit.cpp:323-327`. |
| `prefixnum` | `ITEM_PREFIXNUM` (44) | int32 | R | item | `pItemData->wMagicPrefix[0]` | `JSUnit.cpp:328-331`. |
| `suffixnum` | `ITEM_SUFFIXNUM` (43) | int32 | R | item | `pItemData->wMagicSuffix[0]` | `JSUnit.cpp:332-335`. |
| `prefixes` | `ITEM_PREFIXES` (45) | Array of string | R | item | For i in 0..2: element i = `GetItemMagicalMods(wMagicPrefix[i])` when non-NULL | New array per read. Can be sparse. Gated on the function's result, not on a non-zero id (unlike `prefixnums`). `GetItemMagicalMods` is called twice per slot. `JSUnit.cpp:337-352`. |
| `suffixes` | `ITEM_SUFFIXES` (46) | Array of string | R | item | Same with `wMagicSuffix[i]` | `JSUnit.cpp:369-384`. |
| `prefixnums` | `ITEM_PREFIXNUMS` (48) | Array of int | R | item | Element i = `wMagicPrefix[i]` when non-zero | Sparse. `JSUnit.cpp:353-368`. |
| `suffixnums` | `ITEM_SUFFIXNUMS` (47) | Array of int | R | item | Element i = `wMagicSuffix[i]` when non-zero | `JSUnit.cpp:385-400`. |
| `fname` | `ITEM_FNAME` (22) | string (interned) | R | item | `D2CLIENT_GetItemName(pUnit, wbuf, 256)` (`D2Ptrs.h:74`) | Full multi-line name, with D2's `'\n'` separators kept (compare `name`, which keeps only the first line). `if (wszfname)` tests an array and is always true, so a failed call returns `""`. `JSUnit.cpp:402-410`. |
| `quality` | `ITEM_QUALITY` (23) | int32 | R | item | `pItemData->dwQuality` (ItemData+0x00) | 1..8 = `ITEM_QUALITY_*` (`Constants.h:274-281`). `JSUnit.cpp:411-414`. |
| `node` | `ITEM_NODE` (24) | int32 | R | item | `pItemData->NodePage` (ItemData+0x69, BYTE) | `NODEPAGE_STORAGE 1 / BELTSLOTS 2 / EQUIP 3` (`Constants.h:227-229`). The struct comment calls this "the most reliable by far" (`D2Structs.h:503`). `JSUnit.cpp:415-418`. |
| `location` | `ITEM_LOC` (26) | int32 | R | item | `pItemData->GameLocation` (ItemData+0x68, BYTE) | `LOCATION_*` 0..7 and 255 (`Constants.h:254-262`). `JSUnit.cpp:419-422`. |
| `sizex` | `ITEM_SIZEX` (27) | int32 | R | item with txt | `GetItemText(dwTxtFileNo)->xSize` (ItemTxt+0x10F computed; comment says 0xFC) | Unset if there is no txt. `GetItemText` is called twice. `JSUnit.cpp:423-429`. |
| `sizey` | `ITEM_SIZEY` (28) | int32 | R | item with txt | `GetItemText(...)->ySize` (ItemTxt+0x110 computed; comment 0xFD) | `JSUnit.cpp:430-436`. |
| `itemType` | `ITEM_TYPE` (29) | int32 | R | item with txt | `GetItemText(...)->nType` (ItemTxt+0x11E, **BYTE**) | `nType` is declared as a BYTE (`D2Structs.h:521`), so only one byte is read. `JSUnit.cpp:437-443`. |
| `description` | `ITEM_DESC` (34) | string (interned) | R | `dwType == UNIT_ITEM`; text only if `pItemData && pItemData->pOwnerInventory && pOwnerInventory->pOwner` | **Side-effecting**, under `AutoCriticalRoom`: (1) `WriteProcessMemory` writes byte `0x01` (low byte of `wchar_t bBuffer[1] = {1}`) to VA 0x7BCBE8, which has no `D2Ptrs.h` name; (2) writes `pUnit` to VA 0x7BCBF4, which is `p_D2CLIENT_SelectedInvItem` (`D2Ptrs.h:203`); (3) calls `D2CLIENT_LoadItemDesc(pOwnerInventory->pOwner, 0)` (`D2Ptrs.h:75`, `__stdcall`, VA 0x48DD90); (4) `ReadProcessBYTES` copies 2047 **bytes** from VA 0x841EC8 (passed as `GetDllOffset("D2Win.dll", ...)`; no `D2Ptrs.h` name) into `wchar_t[2048]` (`D2Helpers.cpp:1031-1036`, which wraps the read in `VirtualProtectEx` to `PAGE_READWRITE` and back) | Unset when the copied text is empty or `pOwnerInventory`/`pOwner` is NULL (which items lack an owner inventory, e.g. ground items, is not determinable from source). The lock is taken (`JSUnit.cpp:448`) **before** that check, so even an item that gets no text blocks the script until the game thread yields `cGameLoopSection`. It does **not** restore `SelectedInvItem` or the 0x7BCBE8 byte. It passes the *owner* where the declared parameter is `pItem`. The output is capped at about 1023 UTF-16 code units, and the 2047-byte copy leaves the last code unit with only its low byte. Addresses are hard-coded via `GetDllOffset("D2Client.dll"/"D2Win.dll", VA-0x400000)`. Because the property is enumerable, `JSON.stringify(item)` or any loop that reads every property of an item triggers all of this. `JSUnit.cpp:444-466`. |
| `bodylocation` | `ITEM_BODYLOCATION` (35) | int32 | R | item | `pItemData->BodyLocation` (ItemData+0x44, BYTE) | `EQUIP_*` 0..12 (`Constants.h:234-248`). Struct comment: "Not always cleared" (`D2Structs.h:493`). `JSUnit.cpp:475-480`. |
| `ilvl` | `ITEM_LEVEL` (41) | int32 | R | item | `pItemData->dwItemLevel` (ItemData+0x2C) | `JSUnit.cpp:487-492`. |
| `lvlreq` | `ITEM_LEVELREQ` (37) | int32 | R | `dwType == UNIT_ITEM` (no `pItemData` check); **`unit_props` only** | `D2COMMON_GetItemLevelRequirement(pUnit, D2CLIENT_GetPlayerUnit())` (`D2Ptrs.h:315`, VA 0x62BA60) | Always computed against the local player. `JSUnit.cpp:493-497`. |
| `gfx` | `ITEM_GFX` (49) | int32 | R | item; **`unit_props` only** | `pItemData->bInvGfxIdx` (ItemData+0x49, BYTE) | Inventory graphic variant index. `JSUnit.cpp:467-470`. |

### Properties: object

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `objtype` | `OBJECT_TYPE` (50) | int32 | R | `dwType == UNIT_OBJECT && pObjectData`; **`unit_props` only** | `pObjectData->Type` (ObjectData+0x04, BYTE) | It branches on `D2COMMON_GetRoomFromUnit` + `D2COMMON_GetLevelNoFromRoom` (`D2Ptrs.h:339`) to choose `Type & 255` or `Type`, but `Type` is a BYTE, so both branches give the same value. `Type` shares its byte with the `ChestLocked:1` bitfield (union at `D2Structs.h:586-592`), so the value includes bit 7 (0x80) on locked chests. The struct comment says shrine type 0x0F = experience shrine (`D2Structs.h:587`). `JSUnit.cpp:503-511`. |
| `islocked` | `OBJECT_LOCKED` (51) | int32 (0/1) | R | same; **`unit_props` only** | `pObjectData->ChestLocked` (bit 7 of ObjectData+0x04) | Same byte as `objtype`. `JSUnit.cpp:512-515`. |

### Properties: local-player-bound (`runwalk`, `weaponswitch`)

Both appear in `unit_props` and `me_props`. Both return the global flag only when the resolved unit **is** the local player (`pUnit == D2CLIENT_GetPlayerUnit()`); for any other unit they are unset.

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `runwalk` | `ME_RUNWALK` (18) | int32 | **RW on `me`** (`JSPROP_STATIC_VAR`, `JSUnit.h:179`); R on other Units (`JSUnit.h:292`) | local player | `*p_D2CLIENT_AlwaysRun` (`D2Ptrs.h:219`, VA 0x7A0660, DWORD) | Setter: see [below](#settable-properties-setter-semantics). `JSUnit.cpp:276-279`. |
| `weaponswitch` | `ME_WSWITCH` (9) | int32 | **R everywhere** (`JSUnit.h:180`, `:293`; no setter case) | local player | `*p_D2CLIENT_bWeapSwitch` (`D2Ptrs.h:207`, VA 0x7BCC4C) | The legacy docs say it is settable; it is not. Switching is done with the global `weaponSwitch()` ([globals-game.md](globals-game.md)). `JSUnit.cpp:516-519`. |

### Methods

`unit_methods` (`JSUnit.h:299-309`) defines `getNext`, `cancel`, `repair`, `useMenu`, `interact`, `getItem`, `getItems`, `getMerc`, `getMercHP`, `getSkill`, `getParent`, `overhead`, `revive`, `getFlags`, `getFlag`, `getStat`, `getState`, `getEnchant`, `shop`, `setSkill`, `move`, `getQuest`, `getMinionCount`, `getRepairCost` and `getItemCost` on `Unit.prototype` and on every instance, `me` included. They are documented in [unit-methods.md](unit-methods.md).

---

## The global `me`

### Creation

- Created once per script context in `contextCallback(cx, JSCONTEXT_NEW)` (`ScriptEngine.cpp:329-375`). That callback runs inside `JS_NewContext` (`Script.cpp:123-125`) on the script's thread, at the start of `Script::Run`.
- `new myUnit` and `memset` to 0 (`ScriptEngine.cpp:348-349`); `dwMode = dwClassId = -1`, `dwType = UNIT_PLAYER`, `dwUnitId = D2CLIENT_GetPlayerUnit() ? player->dwUnitId : 0`, `_dwPrivateType = PRIVATE_UNIT` (`:351-356`).
- After the classes are registered (`:358-359`): `BuildObject(cx, &unit_class, unit_methods, me_props, lpUnit)` (`:361`). It is defined on the global as `me` with `JSPROP_PERMANENT_VAR`, i.e. read-only, permanent and enumerable (`:365`). `me = x` therefore has no effect in sloppy code (a TypeError in strict-mode code, engine behaviour), and `delete me` fails. If `BuildObject` or `JS_DefineProperty` fails, the callback returns `JS_FALSE` (`:362-366`). On the `BuildObject` failure path the `myUnit` was never attached and is leaked.
- `Script::Run` then fetches the global's `me` property and caches its private pointer in `Script::me` (`Script.cpp:139-144`). That pointer is the target of `UpdatePlayerGid`.
- Every script has its own runtime, global and `me`. There is no shared `me` object. A `Sandbox` creates its context with `JS_NewContext(ScriptEngine::GetRuntime(), ...)` (`JSSandbox.cpp:8`). `ScriptEngine::runtime` is initialised to NULL (`ScriptEngine.cpp:19`) and never assigned a runtime anywhere in the tree (it is only reset to NULL at `ScriptEngine.cpp:159`), so no `contextCallback` is registered for it and no `me` can be created in a sandbox. What `JS_NewContext` does with a NULL runtime is engine behaviour (see [utility-classes.md](utility-classes.md)).

### Property set: `me_props` vs `unit_props`

`me` is built with `me_props` (`JSUnit.h:160-243`), not `unit_props`.

- Own properties on `me` only (not on other Units): `account`, `charname`, `diff`, `maxdiff`, `gamename`, `gamepassword`, `gameserverip`, `gamestarttime`, `gametype`, `itemoncursor`, `automap`, `ladder`, `ping`, `fps`, `locale`, `playertype`, `realm`, `realmshort`, `mercrevivecost`, `chickenhp`, `chickenmp`, `quitonhostile`, `blockKeys`, `blockMouse`, `gameReady`, `profile`, `nopickup`, `pid`, `unsupported`, `charflags`, `screensize`, `windowtitle`, `ingame`, `quitonerror`, `maxgametime`, `mapid`.
- Shared with `unit_props` (same getter): `type`, `classid`, `mode`, `name`, `act`, `gid`, `x`, `y`, `targetx`, `targety`, `area`, `hp`, `hpmax`, `mp`, `mpmax`, `stamina`, `staminamax`, `charlvl`, `itemcount`, `owner`, `ownertype`, `spectype`, `direction`, every item property except `lvlreq`/`gfx`, plus `runwalk` (writable on `me`) and `weaponswitch`.
- In `unit_props` but **not** own on `me`: `uniqueid`, `lvlreq`, `gfx`, `objtype`, `islocked`. `me` can still reach them through `Unit.prototype`, whose `unit_props` were installed by `JS_InitClass`. If the engine calls the getter with `me` as the receiver (open question), the results are: `me.uniqueid` → `-1` (non-monster branch, `JSUnit.cpp:302`), and the other four → unset for a player unit.

### Tracking the player across games

- At creation, `dwUnitId` is the current player gid, or 0 if there is no player (e.g. scripts started at the menu) (`ScriptEngine.cpp:354-355`). `dwType` is always `UNIT_PLAYER`.
- On the first `ClientStateInGame` iteration while its local `bInGame` flag is false (at startup, and after each return to the menu resets it, `D2Handlers.cpp:99-102`), the D2BS main loop `D2Thread` (`D2Handlers.cpp:72-90`) sets `Vars.dwGameTime`, `Sleep(500)`, `D2CLIENT_InitInventory()`, then `ScriptEngine::ForEachScript(UpdatePlayerGid)` (`D2Handlers.cpp:24-27`, `:84`) and `ScriptEngine::UpdateConsole()` (`:85`, `ScriptEngine.cpp:178-180`). Each of these executes `me->dwUnitId = D2CLIENT_GetPlayerUnit() ? ->dwUnitId : 0` (`Script.cpp:213-215`). After that, `GameJoined()` (`D2Handlers.cpp:87`) starts the in-game scripts, whose fresh contexts read the current gid directly.
- `me` itself is resolved like any Unit: `D2CLIENT_FindUnit(me.dwUnitId, UNIT_PLAYER)`. It does **not** use `D2CLIENT_GetPlayerUnit()` directly. Only `runwalk`/`weaponswitch` compare against `GetPlayerUnit()`.
- Gap: for at least 500 ms after the game becomes `InGame` (`D2Handlers.cpp:81`), `OutOfGame`/`Command` scripts still hold the previous game's gid. During that window `me`'s unit-backed properties are unset, or resolve to whichever player in the new game happens to have the old id.
- `gid` is not reset when returning to the menu: nothing on the menu path (`D2Handlers.cpp:93-104`) calls `UpdatePlayerGid`, which is called only from `D2Handlers.cpp:84-85`. Out of game, unit-backed properties are unset anyway (`JSUnit.cpp:183`).

### me-only properties, any client state

These cases sit in phase 1 (`JSUnit.cpp:55-181`) and run regardless of `ClientState()`.

- `pData = *p_D2LAUNCH_BnData` (`D2Ptrs.h:430`, VA 0x7795D4, `BnetData*`, pack(1)).
- `pInfo = *p_D2CLIENT_GameInfo` (`D2Ptrs.h:198`, VA 0x7A0438, `GameStructInfo*`).

Both are read at `JSUnit.cpp:48-49` on **every** property get of any Unit.

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `pid` | `ME_PID` (123) | number (double) | R | any | `GetCurrentProcessId()` | `JSUnit.cpp:56-59`. |
| `profile` | `ME_PROFILE` (121) | string | R | any | `Vars.szProfile` (`wchar_t[256]`, `D2BS.h:84`) | `JSUnit.cpp:60-62`. |
| `gameReady` | `ME_GAMEREADY` (120) | boolean | R | any | `GameReady()` = `ClientState() == ClientStateInGame` (`D2Helpers.cpp:149-151`) | Does not wait. `JSUnit.cpp:63-66`. |
| `ingame` | `OOG_INGAME` (115) | boolean | R | any | `ClientState() != ClientStateMenu` | Also `true` for `ClientStateNull` and `ClientStateBusy`. `JSUnit.cpp:154-156`. |
| `account` | `ME_ACCOUNT` (90) | string | R | `pData != NULL` | `pData->szAccountName` (BnetData+0x8D, `char[0x30]`) | Unset (with an unbalanced request) if `pData` is NULL. Not tied to being in game. `JSUnit.cpp:67-72`. |
| `charname` | `ME_CHARNAME` (91) | string | R | `pData != NULL` | `pData->szPlayerName` (BnetData+0xBD, `char[0x18]`) | Compare `me.name`, which comes from `PlayerData.szName`. `JSUnit.cpp:73-77`. |
| `diff` | `ME_DIFF` (94) | int32 | R | any (called unconditionally) | `D2CLIENT_GetDifficulty()` (`D2Ptrs.h:112`, `__stdcall BYTE`, VA 0x44DCD0) | 0/1/2 per the legacy docs. Out-of-game behaviour of the D2 function is unknown. `JSUnit.cpp:84-86`. |
| `maxdiff` | `ME_MAXDIFF` (95) | int32 | R | any | `pData->nMaxDiff` (BnetData+0x1F0) | **No NULL check**: dereferences NULL when `pData` is NULL. `JSUnit.cpp:87-89`. |
| `gamename` | `ME_GAMENAME` (96) | string | R | `pInfo != NULL` | `pInfo->szGameName` (GameStructInfo+0x1F, `char[0x18]`) | `JSUnit.cpp:90-94`. |
| `gamepassword` | `ME_GAMEPASSWORD` (97) | string | R | `pInfo != NULL` | `pInfo->szGamePassword` (GameStructInfo+0x245) | `JSUnit.cpp:95-99`. |
| `gameserverip` | `ME_GAMESERVERIP` (98) | string | R | `pInfo != NULL` | `pInfo->szGameServerIp` (GameStructInfo+0x37, `char[0x56]`) | `JSUnit.cpp:100-104`. |
| `gamestarttime` | `ME_GAMESTARTTIME` (99) | number (double) | R | any | `Vars.dwGameTime` (`D2BS.h:42`) | `GetTickCount()` value in ms, set at config load (`Helpers.cpp:142`, so before the first game it is the load time, not 0) and on each game entry (`D2Handlers.cpp:79`, about 500 ms before scripts learn the new gid); 0 after returning to the menu from a game (`D2Handlers.cpp:99-100`). `JSUnit.cpp:105-107`. |
| `gametype` | `ME_GAMETYPE` (100) | int32 | R | any | `*p_D2CLIENT_ExpCharFlag` (`D2Ptrs.h:215`, VA 0x7A04F4) | 0 classic / 1 expansion per the legacy docs. `JSUnit.cpp:108-110`. |
| `playertype` | `ME_PLAYERTYPE` (107) | boolean | R | `pData != NULL` | `!!(pData->nCharFlags & PLAYER_TYPE_HARDCORE)` (BnetData+0x1EF; `Constants.h:134` = 4) | `true` = hardcore. Unset if `pData` is NULL. `JSUnit.cpp:111-114`. |
| `charflags` | `ME_CHARFLAGS` (125) | int32 | R | `pData != NULL` | `pData->nCharFlags` (BnetData+0x1EF, BYTE) | Bits `PLAYER_TYPE_HARDCORE 4`, `_EXPAC 32`, `_LADDER 64` (`Constants.h:134-136`). `JSUnit.cpp:175-178`. |
| `ladder` | `ME_LADDER` (103) | number (double) | R | `pData != NULL` | `pData->ladderflag` (BnetData+**0x3C2** computed; comment says +0x3C0) | Raw byte (`LADDERFLAG_*`, `Constants.h:149-151`), not a boolean. A commented-out boolean version is at `JSUnit.cpp:125`. `JSUnit.cpp:123-127`. |
| `realm` | `ME_REALM` (109) | string | R | any | `pData->szRealmName` (BnetData+0xD5, `char[8]`) | **No NULL check**. `JS_NewStringCopyZ` reads up to the first NUL, so an 8-character name with no NUL runs on into `_8`. `JSUnit.cpp:131-133`. |
| `realmshort` | `ME_REALMSHORT` (110) | string | R | any | `pData->szRealmName2` (BnetData+0x22D, `char[0x18]`) | **No NULL check**. Which field is the long name and which the short one is an open question. `JSUnit.cpp:134-136`. |
| `itemoncursor` | `ME_ITEMONCURSOR` (101) | boolean | R | any (called unconditionally) | `!!D2CLIENT_GetCursorItem()` (`D2Ptrs.h:71`, VA 0x4680A0) | `JSUnit.cpp:115-117`. |
| `automap` | `ME_AUTOMAP` (102) | boolean | **RW** | any | `*p_D2CLIENT_AutomapOn` (`D2Ptrs.h:151`, VA 0x7A27E8, DWORD) | Setter: see [below](#settable-properties-setter-semantics). `JSUnit.cpp:118-122`. |
| `ping` | `ME_PING` (104) | int32 | R | any | `*p_D2CLIENT_Ping` (`D2Ptrs.h:181`, VA 0x7A04A4) | `JSUnit.cpp:145-147`. |
| `fps` | `ME_FPS` (105) | int32 | R | any | `*p_D2CLIENT_FPS` (`D2Ptrs.h:183`, VA 0x7BB390) | `JSUnit.cpp:148-150`. |
| `locale` | `ME_LOCALE` (106) | int32 | R | any | `Vars.dwLocale` | Set once at init from `D2CLIENT_GetGameLanguageCode()` (`Helpers.cpp:205-206`). `JSUnit.cpp:151-153`. |
| `mercrevivecost` | `ME_MERCREVIVECOST` (111) | int32 | R | any | `*p_D2CLIENT_MercReviveCost` (`D2Ptrs.h:157`, VA 0x7C0DD0) | `JSUnit.cpp:163-165`. |
| `screensize` | `OOG_SCREENSIZE` (114) | int32 | R | any | `D2GFX_GetScreenSize()` (`D2Ptrs.h:383`, VA 0x4F5160) | A resolution-mode index (legacy: 0 = 640x480, 1 = 800x600), not pixels. `JSUnit.cpp:137-139`. |
| `windowtitle` | `OOG_WINDOWTITLE` (113) | string | R | any | `GetWindowTextW(D2GFX_GetHwnd(), buf, 256)` (`D2Ptrs.h:382`) | Cross-thread `WM_GETTEXT`. Truncated to 255 characters. `JSUnit.cpp:140-144`. |
| `chickenhp` | `ME_CHICKENHP` (92) | int32 | **RW** | any | `Vars.nChickenHP` (`D2BS.h:39`) | `JSUnit.cpp:78-80`. |
| `chickenmp` | `ME_CHICKENMP` (93) | int32 | **RW** | any | `Vars.nChickenMP` (`D2BS.h:40`) | `JSUnit.cpp:81-83`. |
| `quitonhostile` | `ME_QUITONHOSTILE` (108) | boolean | **RW** | any | `Vars.bQuitOnHostile` (`D2BS.h:57`) | `JSUnit.cpp:128-130`. |
| `quitonerror` | `OOG_QUITONERROR` (116) | boolean | **RW** | any | `Vars.bQuitOnError` (`D2BS.h:56`) | `JSUnit.cpp:157-159`. |
| `maxgametime` | `OOG_MAXGAMETIME` (117) | int32 | **RW** | any | `Vars.dwMaxGameTime` (`D2BS.h:53`, `DWORD`), **milliseconds** | `setInt32` of a `DWORD`, so a stored negative value reads back negative. `JSUnit.cpp:160-162`. |
| `blockKeys` | `ME_BLOCKKEYS` (118) | boolean | **RW** | any | `Vars.bBlockKeys` (`D2BS.h:60`) | `JSUnit.cpp:166-168`. |
| `blockMouse` | `ME_BLOCKMOUSE` (119) | boolean | **RW** | any | `Vars.bBlockMouse` (`D2BS.h:61`) | `JSUnit.cpp:169-171`. |
| `unsupported` | `ME_UNSUPPORTED` (124) | boolean | R | any | `Vars.bEnableUnsupported` (`D2BS.h:66`; from ini, `Helpers.cpp:153`) | Mirrors the gate that unsupported natives check (`JSCore.cpp:572`, `:617`, `JSGame.cpp:1425`). Cannot be changed from JS. `JSUnit.cpp:172-174`. |

### me-only properties, in game only

These are phase-2 cases: they need `ClientStateInGame` and a resolved `me` unit, even though the value is a global.

| Property | Enum id | JS type | R/W | Applies to / conditions | Value source | Notes / quirks |
|---|---|---|---|---|---|---|
| `mapid` | `ME_MAPID` (112) | int32 | R | in game, `me` resolves | `*p_D2CLIENT_MapId` (`D2Ptrs.h:217`, VA 0x7A0638) | The legacy docs call it the map seed; the D2Ptrs comment says "unused but I want to add it". `JSUnit.cpp:214-216`. |
| `nopickup` | `ME_NOPICKUP` (122) | boolean | **RW** | get: in game, `me` resolves; set: any state | `!!*p_D2CLIENT_NoPickUp` (`D2Ptrs.h:220`, VA 0x7A6A90, `DWORD`) | Same "unused but I want to add it" comment in `D2Ptrs.h:220`. Setter writes regardless of state (`JSUnit.cpp:565-567`). `JSUnit.cpp:217-219`. |
| `runwalk` | `ME_RUNWALK` (18) | int32 | **RW** | see [local-player-bound](#properties-local-player-bound-runwalk-weaponswitch) | `*p_D2CLIENT_AlwaysRun` | |
| `weaponswitch` | `ME_WSWITCH` (9) | int32 | R | same | `*p_D2CLIENT_bWeapSwitch` | |

### Settable properties (setter semantics)

`unit_setProperty` (`JSUnit.cpp:527-570`) is attached only to the 10 `JSPROP_STATIC_VAR` entries of `me_props` (`JSUnit.h:170`, `:179`, `:181-185`, `:188`, `:196-197`). It:

- runs on the assigning script's thread;
- has no client-state or receiver check;
- takes no lock;
- never throws, and wrong types are ignored silently;
- writes process-global state only (`Vars.*` or game memory). An assignment from one script is visible through every other script's `me` and affects D2BS as a whole.

`isInt32()`/`isBoolean()` test the jsval's tag, not its numeric value: `me.chickenhp = 50.5` or `me.blockKeys = 1` is ignored rather than coerced. Whether an integral number computed by script is tagged int32 or double depends on the engine (SpiderMonkey normally stores integral results that fit as int32; `-0` stays a double).

Values that fail the `vp.is*()` test are dropped. After the setter returns, SpiderMonkey of this era stores the assigned value in the property's slot (engine behaviour, same caveat as [slot caching](#getter--setter-mechanics)). For the seven `Vars`-backed properties the getter is phase 1 and always writes `vp`, so a rejected value is never observed. `runwalk` and `nopickup` are phase-2 getters: read while not in game, or while `me` does not resolve, they return unset, which would expose the raw value last assigned (e.g. `me.nopickup = "x"` at the menu, then `me.nopickup` gives `"x"`), not the 0/1 that was written to game memory.

| Property | Setter line | Accepted values | Effect | Consumer of the value |
|---|---|---|---|---|
| `chickenhp` | `JSUnit.cpp:531-534` | int32 only (`vp.isInt32()`) | `Vars.nChickenHP = v` | `D2Thread` (D2BS main thread) calls `D2CLIENT_ExitGame()` when `nChickenHP != 0`, the player is not in town (`D2COMMON_IsTownByLevelNo(GetPlayerArea())`) and `nChickenHP >= GetUnitHP(player)` (stat 6 `>> 8`; `D2Handlers.cpp:74-77`, `Unit.cpp:274-276`). Checked only on loop iterations after the game-entry iteration (`bInGame`), about every 50 ms (`D2Handlers.cpp:109`). 0 or a negative value never fires. |
| `chickenmp` | `:535-538` | int32 only | `Vars.nChickenMP = v` | Same loop, against `GetUnitMP` (`D2Handlers.cpp:76`, `Unit.cpp:278-280`). As written (`(!town && hpCond) \|\| mpCond`), the MP clause is OR-ed **outside** the not-in-town condition, so MP chicken also fires in town. |
| `quitonhostile` | `:539-542` | boolean only | `Vars.bQuitOnHostile = v` | `EventMessagesHandler` (`D2NetHandlers.cpp:81`), the game-event packet handler: mode `0x07` (player relation) with `param2 == 0x03` (hostile) → `D2CLIENT_ExitGame()` (`D2NetHandlers.cpp:104-115`). It does not check who was made hostile. Ini default `QuitOnHostile` (`Helpers.cpp:121`, `:146`). |
| `quitonerror` | `:543-546` | boolean only | `Vars.bQuitOnError = v` | `reportError` (error reporter of every script context, `ScriptEngine.cpp:333`, `Script.cpp:129`): a non-warning JS error from **any** script while `ClientStateInGame` → `D2CLIENT_ExitGame()` instead of `Console::ShowBuffer()` (`ScriptEngine.cpp:446-449`). The flag is process-global, so one script setting it affects errors in all scripts. Ini default `QuitOnError` (`Helpers.cpp:122`, `:147`). |
| `maxgametime` | `:547-550` | int32 only (so values ≥ 2^31 ms are rejected; negative ints are stored and wrap to huge DWORDs) | `Vars.dwMaxGameTime = v` (ms) | `D2Thread` calls `D2CLIENT_ExitGame()` once `dwMaxGameTime != 0 && dwGameTime != 0 && GetTickCount() - Vars.dwGameTime > dwMaxGameTime` (`D2Handlers.cpp:74`); 0 disables. The ini value is converted with `abs(... * 1000)` (`Helpers.cpp:143`); the JS value is not converted. |
| `blockKeys` | `:551-554` | boolean only (`me.blockKeys = 1` is ignored) | `Vars.bBlockKeys = v` | The keyboard hook swallows keys, except that Alt+F4 passes through first (`D2Handlers.cpp:220-224`). `Profile::login` overwrites the flag (TRUE during login, FALSE on exit, `Profile.cpp:112`, `:277`, `:283`, `:294`). |
| `blockMouse` | `:555-558` | boolean only | `Vars.bBlockMouse = v` | The mouse hook returns 1 after recording coordinates (`D2Handlers.cpp:304-306`). Also overwritten by `Profile::login`. |
| `runwalk` | `:559-561` | **anything**: raw `vp.toInt32()` with no type check | `*p_D2CLIENT_AlwaysRun = !!v` | Game memory write (VA 0x7A0660). On this 32-bit build (`JS_BITS_PER_WORD == 32` branch, `dependencies/include/js/Value.h:337-572`), `toInt32()` returns the low 32-bit payload word (`dependencies/include/js/Value.h:375-378`, `:1048-1051`; the `MOZ_ASSERT` is debug-only), so `true`/`1` → 1; `false`/`0`/`null`/`undefined` → 0; any string (even `""`) or object (non-NULL pointer payload) → 1; a double gives its low 32 bits, so `0.5` → 0. D2BS itself reads the flag in `ClickMap` (`Core.cpp:134`, used by the `clickMap` global), which passes flag `0x08` to `D2CLIENT_ClickMap` when it is set and shift is not requested (`Core.cpp:161`, `:172`). |
| `automap` | `:562-564` | **anything**: raw `vp.toBoolean()` (`dependencies/include/js/Value.h:432-435`, `:1083-1086`) | `*p_D2CLIENT_AutomapOn = v ? 1 : 0` | Game memory write (VA 0x7A27E8). Only the flag changes; no UI refresh function is called. Non-booleans are read by payload as for `runwalk`. D2BS consumer: automap screenhooks are drawn only while the flag is set (`ScreenHook.cpp:39-42`). |
| `nopickup` | `:565-567` | **anything**: raw `toInt32()` | `*p_D2CLIENT_NoPickUp = !!v` | Game memory write (VA 0x7A6A90), accepted even out of game (the getter, by contrast, needs in-game state). No other D2BS code reads the flag; its game-side effect is not visible in source. |

---

## Tinyid reference

`unit_tinyid` (`JSUnit.h:64-119`, ids 0-53) and `me_tinyid` (`JSUnit.h:121-158`, ids 90-125). Generated from the source: R/RW is the flag in the spec table (`JSPROP_PERMANENT_VAR` / `JSPROP_STATIC_VAR`) with the spec line; the getter phase is 1 (`JSUnit.cpp:55-181`, any client state) or 2 (`JSUnit.cpp:197-522`, in game and unit resolved). Dead ids have no spec entry and no case.

| Id | Enum | JS name | `unit_props` | `me_props` | Getter case (phase) | Setter case |
|---|---|---|---|---|---|---|
| 0 | `UNIT_TYPE` | `type` | R (`JSUnit.h:245`) | R (`JSUnit.h:199`) | `JSUnit.cpp:198` (2) | – |
| 1 | `UNIT_CLASSID` | `classid` | R (`JSUnit.h:246`) | R (`JSUnit.h:200`) | `JSUnit.cpp:201` (2) | – |
| 2 | `UNIT_ID` | `gid` | R (`JSUnit.h:250`) | R (`JSUnit.h:205`) | `JSUnit.cpp:228` (2) | – |
| 3 | `UNIT_MODE` | `mode` | R (`JSUnit.h:247`) | R (`JSUnit.h:201`) | `JSUnit.cpp:204` (2) | – |
| 4 | `UNIT_NAME` | `name` | R (`JSUnit.h:248`) | R (`JSUnit.h:202`) | `JSUnit.cpp:207` (2) | – |
| 5 | `UNIT_BUSY` | — (dead) | – | – | **none** | – |
| 6 | `UNIT_ACT` | `act` | R (`JSUnit.h:249`) | R (`JSUnit.h:204`) | `JSUnit.cpp:220` (2) | – |
| 7 | `UNIT_XPOS` | `x` | R (`JSUnit.h:251`) | R (`JSUnit.h:206`) | `JSUnit.cpp:233` (2) | – |
| 8 | `UNIT_YPOS` | `y` | R (`JSUnit.h:252`) | R (`JSUnit.h:207`) | `JSUnit.cpp:236` (2) | – |
| 9 | `ME_WSWITCH` | `weaponswitch` | R (`JSUnit.h:293`) | R (`JSUnit.h:180`) | `JSUnit.cpp:516` (2) | – |
| 10 | `UNIT_AREA` | `area` | R (`JSUnit.h:255`) | R (`JSUnit.h:210`) | `JSUnit.cpp:223` (2) | – |
| 11 | `UNIT_HP` | `hp` | R (`JSUnit.h:256`) | R (`JSUnit.h:211`) | `JSUnit.cpp:255` (2) | – |
| 12 | `UNIT_HPMAX` | `hpmax` | R (`JSUnit.h:257`) | R (`JSUnit.h:212`) | `JSUnit.cpp:258` (2) | – |
| 13 | `UNIT_MP` | `mp` | R (`JSUnit.h:258`) | R (`JSUnit.h:213`) | `JSUnit.cpp:261` (2) | – |
| 14 | `UNIT_MPMAX` | `mpmax` | R (`JSUnit.h:259`) | R (`JSUnit.h:214`) | `JSUnit.cpp:264` (2) | – |
| 15 | `UNIT_STAMINA` | `stamina` | R (`JSUnit.h:260`) | R (`JSUnit.h:215`) | `JSUnit.cpp:267` (2) | – |
| 16 | `UNIT_STAMINAMAX` | `staminamax` | R (`JSUnit.h:261`) | R (`JSUnit.h:216`) | `JSUnit.cpp:270` (2) | – |
| 17 | `UNIT_CHARLVL` | `charlvl` | R (`JSUnit.h:262`) | R (`JSUnit.h:217`) | `JSUnit.cpp:273` (2) | – |
| 18 | `ME_RUNWALK` | `runwalk` | R (`JSUnit.h:292`) | RW (`JSUnit.h:179`) | `JSUnit.cpp:276` (2) | `JSUnit.cpp:559` |
| 19 | `ITEM_CODE` | `code` | R (`JSUnit.h:270`) | R (`JSUnit.h:224`) | `JSUnit.cpp:304` (2) | – |
| 20 | `ITEM_PREFIX` | `prefix` | R (`JSUnit.h:271`) | R (`JSUnit.h:225`) | `JSUnit.cpp:318` (2) | – |
| 21 | `ITEM_SUFFIX` | `suffix` | R (`JSUnit.h:272`) | R (`JSUnit.h:226`) | `JSUnit.cpp:323` (2) | – |
| 22 | `ITEM_FNAME` | `fname` | R (`JSUnit.h:279`) | R (`JSUnit.h:233`) | `JSUnit.cpp:402` (2) | – |
| 23 | `ITEM_QUALITY` | `quality` | R (`JSUnit.h:280`) | R (`JSUnit.h:234`) | `JSUnit.cpp:411` (2) | – |
| 24 | `ITEM_NODE` | `node` | R (`JSUnit.h:281`) | R (`JSUnit.h:235`) | `JSUnit.cpp:415` (2) | – |
| 25 | `UNIT_SELECTABLE` | — (dead) | – | – | **none** | – |
| 26 | `ITEM_LOC` | `location` | R (`JSUnit.h:282`) | R (`JSUnit.h:236`) | `JSUnit.cpp:419` (2) | – |
| 27 | `ITEM_SIZEX` | `sizex` | R (`JSUnit.h:283`) | R (`JSUnit.h:237`) | `JSUnit.cpp:423` (2) | – |
| 28 | `ITEM_SIZEY` | `sizey` | R (`JSUnit.h:284`) | R (`JSUnit.h:238`) | `JSUnit.cpp:430` (2) | – |
| 29 | `ITEM_TYPE` | `itemType` | R (`JSUnit.h:285`) | R (`JSUnit.h:239`) | `JSUnit.cpp:437` (2) | – |
| 30 | `MISSILE_DIR` | — (dead) | – | – | **none** | – |
| 31 | `MISSILE_VEL` | — (dead) | – | – | **none** | – |
| 32 | `ITEM_CLASS` | — (dead) | – | – | **none** | – |
| 33 | `UNIT_SPECTYPE` | `spectype` | R (`JSUnit.h:266`) | R (`JSUnit.h:221`) | `JSUnit.cpp:280` (2) | – |
| 34 | `ITEM_DESC` | `description` | R (`JSUnit.h:286`) | R (`JSUnit.h:240`) | `JSUnit.cpp:444` (2) | – |
| 35 | `ITEM_BODYLOCATION` | `bodylocation` | R (`JSUnit.h:287`) | R (`JSUnit.h:241`) | `JSUnit.cpp:475` (2) | – |
| 36 | `UNIT_ITEMCOUNT` | `itemcount` | R (`JSUnit.h:263`) | R (`JSUnit.h:218`) | `JSUnit.cpp:471` (2) | – |
| 37 | `ITEM_LEVELREQ` | `lvlreq` | R (`JSUnit.h:289`) | – | `JSUnit.cpp:493` (2) | – |
| 38 | `UNIT_OWNER` | `owner` | R (`JSUnit.h:264`) | R (`JSUnit.h:219`) | `JSUnit.cpp:481` (2) | – |
| 39 | `UNIT_OWNERTYPE` | `ownertype` | R (`JSUnit.h:265`) | R (`JSUnit.h:220`) | `JSUnit.cpp:484` (2) | – |
| 40 | `UNIT_UNIQUEID` | `uniqueid` | R (`JSUnit.h:268`) | – | `JSUnit.cpp:298` (2) | – |
| 41 | `ITEM_LEVEL` | `ilvl` | R (`JSUnit.h:288`) | R (`JSUnit.h:242`) | `JSUnit.cpp:487` (2) | – |
| 42 | `UNIT_DIRECTION` | `direction` | R (`JSUnit.h:267`) | R (`JSUnit.h:222`) | `JSUnit.cpp:498` (2) | – |
| 43 | `ITEM_SUFFIXNUM` | `suffixnum` | R (`JSUnit.h:276`) | R (`JSUnit.h:230`) | `JSUnit.cpp:332` (2) | – |
| 44 | `ITEM_PREFIXNUM` | `prefixnum` | R (`JSUnit.h:275`) | R (`JSUnit.h:229`) | `JSUnit.cpp:328` (2) | – |
| 45 | `ITEM_PREFIXES` | `prefixes` | R (`JSUnit.h:273`) | R (`JSUnit.h:227`) | `JSUnit.cpp:337` (2) | – |
| 46 | `ITEM_SUFFIXES` | `suffixes` | R (`JSUnit.h:274`) | R (`JSUnit.h:228`) | `JSUnit.cpp:369` (2) | – |
| 47 | `ITEM_SUFFIXNUMS` | `suffixnums` | R (`JSUnit.h:278`) | R (`JSUnit.h:232`) | `JSUnit.cpp:385` (2) | – |
| 48 | `ITEM_PREFIXNUMS` | `prefixnums` | R (`JSUnit.h:277`) | R (`JSUnit.h:231`) | `JSUnit.cpp:353` (2) | – |
| 49 | `ITEM_GFX` | `gfx` | R (`JSUnit.h:290`) | – | `JSUnit.cpp:467` (2) | – |
| 50 | `OBJECT_TYPE` | `objtype` | R (`JSUnit.h:295`) | – | `JSUnit.cpp:503` (2) | – |
| 51 | `OBJECT_LOCKED` | `islocked` | R (`JSUnit.h:296`) | – | `JSUnit.cpp:512` (2) | – |
| 52 | `UNIT_TARGETX` | `targetx` | R (`JSUnit.h:253`) | R (`JSUnit.h:208`) | `JSUnit.cpp:239` (2) | – |
| 53 | `UNIT_TARGETY` | `targety` | R (`JSUnit.h:254`) | R (`JSUnit.h:209`) | `JSUnit.cpp:247` (2) | – |
| 90 | `ME_ACCOUNT` | `account` | – | R (`JSUnit.h:160`) | `JSUnit.cpp:67` (1) | – |
| 91 | `ME_CHARNAME` | `charname` | – | R (`JSUnit.h:161`) | `JSUnit.cpp:73` (1) | – |
| 92 | `ME_CHICKENHP` | `chickenhp` | – | RW (`JSUnit.h:181`) | `JSUnit.cpp:78` (1) | `JSUnit.cpp:531` |
| 93 | `ME_CHICKENMP` | `chickenmp` | – | RW (`JSUnit.h:182`) | `JSUnit.cpp:81` (1) | `JSUnit.cpp:535` |
| 94 | `ME_DIFF` | `diff` | – | R (`JSUnit.h:162`) | `JSUnit.cpp:84` (1) | – |
| 95 | `ME_MAXDIFF` | `maxdiff` | – | R (`JSUnit.h:163`) | `JSUnit.cpp:87` (1) | – |
| 96 | `ME_GAMENAME` | `gamename` | – | R (`JSUnit.h:164`) | `JSUnit.cpp:90` (1) | – |
| 97 | `ME_GAMEPASSWORD` | `gamepassword` | – | R (`JSUnit.h:165`) | `JSUnit.cpp:95` (1) | – |
| 98 | `ME_GAMESERVERIP` | `gameserverip` | – | R (`JSUnit.h:166`) | `JSUnit.cpp:100` (1) | – |
| 99 | `ME_GAMESTARTTIME` | `gamestarttime` | – | R (`JSUnit.h:167`) | `JSUnit.cpp:105` (1) | – |
| 100 | `ME_GAMETYPE` | `gametype` | – | R (`JSUnit.h:168`) | `JSUnit.cpp:108` (1) | – |
| 101 | `ME_ITEMONCURSOR` | `itemoncursor` | – | R (`JSUnit.h:169`) | `JSUnit.cpp:115` (1) | – |
| 102 | `ME_AUTOMAP` | `automap` | – | RW (`JSUnit.h:170`) | `JSUnit.cpp:118` (1) | `JSUnit.cpp:562` |
| 103 | `ME_LADDER` | `ladder` | – | R (`JSUnit.h:171`) | `JSUnit.cpp:123` (1) | – |
| 104 | `ME_PING` | `ping` | – | R (`JSUnit.h:172`) | `JSUnit.cpp:145` (1) | – |
| 105 | `ME_FPS` | `fps` | – | R (`JSUnit.h:173`) | `JSUnit.cpp:148` (1) | – |
| 106 | `ME_LOCALE` | `locale` | – | R (`JSUnit.h:174`) | `JSUnit.cpp:151` (1) | – |
| 107 | `ME_PLAYERTYPE` | `playertype` | – | R (`JSUnit.h:175`) | `JSUnit.cpp:111` (1) | – |
| 108 | `ME_QUITONHOSTILE` | `quitonhostile` | – | RW (`JSUnit.h:183`) | `JSUnit.cpp:128` (1) | `JSUnit.cpp:539` |
| 109 | `ME_REALM` | `realm` | – | R (`JSUnit.h:176`) | `JSUnit.cpp:131` (1) | – |
| 110 | `ME_REALMSHORT` | `realmshort` | – | R (`JSUnit.h:177`) | `JSUnit.cpp:134` (1) | – |
| 111 | `ME_MERCREVIVECOST` | `mercrevivecost` | – | R (`JSUnit.h:178`) | `JSUnit.cpp:163` (1) | – |
| 112 | `ME_MAPID` | `mapid` | – | R (`JSUnit.h:203`) | `JSUnit.cpp:214` (2) | – |
| 113 | `OOG_WINDOWTITLE` | `windowtitle` | – | R (`JSUnit.h:194`) | `JSUnit.cpp:140` (1) | – |
| 114 | `OOG_SCREENSIZE` | `screensize` | – | R (`JSUnit.h:193`) | `JSUnit.cpp:137` (1) | – |
| 115 | `OOG_INGAME` | `ingame` | – | R (`JSUnit.h:195`) | `JSUnit.cpp:154` (1) | – |
| 116 | `OOG_QUITONERROR` | `quitonerror` | – | RW (`JSUnit.h:196`) | `JSUnit.cpp:157` (1) | `JSUnit.cpp:543` |
| 117 | `OOG_MAXGAMETIME` | `maxgametime` | – | RW (`JSUnit.h:197`) | `JSUnit.cpp:160` (1) | `JSUnit.cpp:547` |
| 118 | `ME_BLOCKKEYS` | `blockKeys` | – | RW (`JSUnit.h:184`) | `JSUnit.cpp:166` (1) | `JSUnit.cpp:551` |
| 119 | `ME_BLOCKMOUSE` | `blockMouse` | – | RW (`JSUnit.h:185`) | `JSUnit.cpp:169` (1) | `JSUnit.cpp:555` |
| 120 | `ME_GAMEREADY` | `gameReady` | – | R (`JSUnit.h:186`) | `JSUnit.cpp:63` (1) | – |
| 121 | `ME_PROFILE` | `profile` | – | R (`JSUnit.h:187`) | `JSUnit.cpp:60` (1) | – |
| 122 | `ME_NOPICKUP` | `nopickup` | – | RW (`JSUnit.h:188`) | `JSUnit.cpp:217` (2) | `JSUnit.cpp:565` |
| 123 | `ME_PID` | `pid` | – | R (`JSUnit.h:189`) | `JSUnit.cpp:56` (1) | – |
| 124 | `ME_UNSUPPORTED` | `unsupported` | – | R (`JSUnit.h:190`) | `JSUnit.cpp:172` (1) | – |
| 125 | `ME_CHARFLAGS` | `charflags` | – | R (`JSUnit.h:191`) | `JSUnit.cpp:175` (1) | – |

---

## Legacy-doc discrepancies

| Topic | Legacy docs | Code |
|---|---|---|
| `me.classId` | `doc/Me.h:571` spells it `classId` | `classid` (`JSUnit.h:200`). `me.classId` is `undefined`. |
| `weaponswitch` writable | `doc/Unit.h:801-803` "Set the weapon switch"; `resources/api.html` "can also be set to toggle the weapon switch" | Read-only on every Unit (`JSUnit.h:180`, `:293`), with no setter case. |
| `me.maxgametime` unit | `resources/api.html` "in seconds" | Milliseconds (raw store `JSUnit.cpp:549`, compared with a `GetTickCount` delta at `D2Handlers.cpp:74`). `doc/Me.h:962-964` says milliseconds, which is correct. |
| `me.ladder` type | `doc/Me.h:864` and api.html: `bool` | Raw `ladderflag` byte as a double (`JSUnit.cpp:126`), read from BnetData+0x3C2, while the struct comment says +0x3C0 (`D2Structs.h:204`). |
| `me.playertype` type | `doc/Me.h:876` `int`; api.html "0 - Softcore 1 - Hardcore" | boolean (`JSUnit.cpp:113`). |
| `me.runwalk` type | api.html `bool` ("true if run/walk is set to run") | int32 (`JSUnit.cpp:278`). The setter accepts anything (`:560`). |
| `me.gamestarttime` | api.html `int` (ticks); `doc/Me.h:846-850` "\todo Figure out" | double `GetTickCount()` ms at game entry (`D2Handlers.cpp:79`); 0 at the menu after a game (`:100`); the config-load tick before the first game (`Helpers.cpp:142`). |
| `me.charname` OOG | api.html "an empty string if not in a game" | Read from BnetData whatever the game state; unset (normally `undefined`) only if `*p_D2LAUNCH_BnData` is NULL (`JSUnit.cpp:73-77`). |
| `me.diff` OOG | api.html "or 0 if not in a game" | `D2CLIENT_GetDifficulty()` is called unconditionally (`JSUnit.cpp:85`); the return value OOG is whatever the game function gives. |
| `me.account` | api.html "undefined if not logged into Battle.net" | Unset (normally `undefined`) only if the BnData pointer is NULL (`JSUnit.cpp:68-69`); otherwise whatever `szAccountName` holds. |
| `runwalk` listed twice | `doc/Me.h:806` and `:897` | Single entry (`JSUnit.h:179`). |
| Missing from legacy `me` docs | `doc/Me.h` and api.html lack `automap`, `locale`, `unsupported`, `charflags`, `prefixes`, `suffixes`, `prefixnums`, `suffixnums`; the api.html list also lacks `gameReady`, `profile`, `nopickup`, `pid`, `mapid` | All present in `me_props` (`JSUnit.h:160-243`). |
| `spectype` values | `doc/Unit.h:621-629`: 1 "Normal" Boss, 2 Champion, 4 Boss, 8 Minion | Same bits, but 0x01 means `fBoss && fNormal`, i.e. MonsterData+0x16 bits 3 and 1 (`JSUnit.cpp:290-291`). The field named `fNormal` is not a "normal monster" flag. |
| Type 5 name | `doc/Unit.h:509-525` (`type`) and `doc/Me.h:557`: "5 - Warp" | `UNIT_TILE 5` (`Constants.h:366`). |
| Equality | none documented | No equality hook (`JSUnit.cpp:33-45` commented out). |
| `ItemTxt` comments | `D2Structs.h:513-523` comments: `szCode` 0x40, `xSize` 0xFC, `ySize` 0xFD; `fQuest` 0x12A | Computed: `szCode` 0x80 (0x40 `wchar_t` = 0x80 bytes), `xSize` 0x10F, `ySize` 0x110, `nType` 0x11E (matches its comment), `fQuest` 0x12C. The comment chain is self-inconsistent (`_2a[0x19]` at "0xF7" cannot end at "0xFC"). |
| `BnetData` tail comments | `channelname` "+0x35f", `charlevel` "+0x3bf", `ladderflag` "+0x3c0" (`D2Structs.h:201-204`) | Computed with pack(1): 0x361 / 0x3C1 / 0x3C2. `szGameDesc[0x104]` at 0x25D ends at 0x361. |

---

## Open questions

1. **Slot caching on unset paths.** The claim that an unset getter return yields the property slot's previous value (not `undefined`) relies on SpiderMonkey 22's generic native-get path (getter receives the slot value in `vp`, result written back to the slot for non-`JSPROP_SHARED` properties). Engine source is not in the repo (only headers and `dependencies/libs/release/js_static.lib`). The same engine path is assumed to store an assigned value into the slot after `unit_setProperty` returns, which matters for `me.runwalk`/`me.nopickup` read out of game. Needs a runtime test: read `u.x`, let the unit despawn, read again; assign `me.nopickup = "x"` at the menu and read it back.
2. **Receiver for inherited getters.** `JS_NewObject(cx, &unit_class, NULL, NULL)` in `BuildObject` (`js32.cpp:11`) is expected to take `Unit.prototype` as the proto, so `u instanceof Unit` holds and `me` inherits `uniqueid`/`lvlreq`/`gfx`/`objtype`/`islocked`. Also unverified: that the getter is then called with `me`, not `Unit.prototype`, as `obj`. Both are engine behaviour; unverified.
3. **Unit id reuse.** Does Diablo II 1.14d reuse `dwUnitId` values within one game (e.g. for monsters or items after removal)? This determines whether a stale handle can silently alias another unit in the same game. It cannot be determined from source.
4. **Realm fields.** Which of `BnetData.szRealmName` (+0xD5, 8 bytes) and `szRealmName2` (+0x22D, 24 bytes) holds the long realm name and which the short one. The code maps `realm` → the former and `realmshort` → the latter. The legacy docs say `realm` is the long name.
5. **BnetData `ladderflag` / `ItemTxt` sizes.** Which offset matches 1.14d memory: the computed one (0x3C2; ItemTxt 0x10F/0x110) or the commented one (0x3C0; 0xFC/0xFD)? The code uses the computed layout.
6. **VA 0x7BCBE8.** What the byte that `description` sets to 1 controls (next to `ShopCursorType` 0x7BCBF0 and `SelectedInvItem` 0x7BCBF4). Also, whether leaving `SelectedInvItem` pointing at the item has visible UI effects.
7. **When `*p_D2LAUNCH_BnData` is NULL** (single-player? before the first login?). `maxdiff`, `realm` and `realmshort` would then crash the game.
8. **Out-of-game safety** of `D2CLIENT_GetDifficulty`, `D2CLIENT_GetCursorItem` and `D2GFX_GetScreenSize`, which the `me` getters call in every client state.
9. **Monster `hp`/`hpmax` client-side.** Whether stats 6/7 on non-owned monsters are real values or scaled approximations.
10. **`owner` / `ownertype`** (UnitAny+0x98/+0x94): what they mean for each unit type.
11. **Interned string lifetime.** Whether atoms from `JS_Intern*` are pinned until the runtime is destroyed, which would mean unbounded growth when reading many distinct `description`/`fname` values in a long-lived script.
12. **`D2COMMON_GetItemMagicalMods(0)`.** `prefix`/`suffix` and the `prefixes`/`suffixes` arrays pass the id even when it is 0 and gate only on a NULL return (`JSUnit.cpp:320`, `:342`). Whether the game returns NULL or a real affix name for id 0 (i.e. whether non-magic items get a bogus `prefix`) cannot be determined from source.
13. **Which game states make `ClientState()` return `ClientStateBusy`** (loading screens, act transitions) and therefore make every unit-backed property unset. The source only shows the struct conditions (`D2Helpers.cpp:130-140`).

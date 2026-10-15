# Unit methods, unit search and `getUnit` / `getMercHP`

Scope: every JS-callable function in the `unit_methods` table (`JSUnit.h:299-309`, 25 entries), the two global natives implemented in `JSUnit.cpp` (`getUnit`, `getMercHP`), and the unit search and iteration model behind them (`Unit.cpp`, `D2Helpers.cpp`). Everything comes from the C++ source; legacy docs (`doc/Unit.h`, `doc/Me.h`, `doc/globalFuncs.h`, `resources/api.html`, `README.md`) are used only to cross-check, and each place they disagree with the code is called out. Unit properties, `me`-only properties and most class facts are in [unit-properties.md](unit-properties.md). Event dispatch is in [events.md](events.md). Offsets, structs and asm stubs are in [../memory/](../memory/README.md).

## Table of contents

- [Conventions used on this page](#conventions-used-on-this-page)
- [Unit (class recap)](#unit)
- [Unit search and iteration model](#unit-search-and-iteration-model)
- [Global functions](#global-functions)
- [Method summary](#method-summary)
- [Methods: iteration and inventory](#methods-iteration-and-inventory)
- [Methods: stats, state, skills, flags](#methods-stats-state-skills-flags)
- [Methods: relations (parent / merc)](#methods-relations-parent--merc)
- [Methods: game actions](#methods-game-actions)
- [Methods: prices](#methods-prices)
- [Game internals referenced](#game-internals-referenced)
- [Legacy-doc discrepancies](#legacy-doc-discrepancies)
- [Open questions](#open-questions)

---

## Conventions used on this page

These patterns repeat across almost every native, so they are defined once here. Entries below refer to them by name.

| Term | Meaning (source) |
|---|---|
| **resolve `this`** | `JS_GetPrivate(cx, JS_THIS_OBJECT(cx, vp))`. The wrapper at `js32.cpp:65` calls the class-unchecked `JS_GetPrivate(obj)`. Most natives then test `(priv->_dwPrivateType & PRIVATE_UNIT) == PRIVATE_UNIT`, which passes for both `PRIVATE_UNIT` (1) and `PRIVATE_ITEM` (3) (`D2BS.h:22-23`). The native then calls `D2CLIENT_FindUnit(priv->dwUnitId, priv->dwType)` (`D2Helpers.cpp:500`), which tries the game's `FindServerSideUnit` and falls back to `FindClientSideUnit` (`D2Helpers.cpp:503-504`) and returns `NULL` for id `-1`. If any step fails, the native returns its failure value. Only `getMercHP` uses the class-checked `JS_GetInstancePrivate` (`JSUnit.cpp:1694`). Because the check is class-unchecked and the only private tags are 1 and 3 (`D2BS.h:22-25`), calling a method with a foreign `this` (e.g. `me.getStat.call(someRoom, 6)`, or a non-Unit object passed where a Unit is expected) reinterprets that object's private as a `myUnit` whenever its first DWORD has bit 0 set. |
| **int-tag test** | `JSVAL_IS_INT(v)` tests the jsval tag, not the numeric value. Strings, booleans, non-integral numbers, and any number the engine happens to hold as a double fail it (when an integral number is stored as a double is engine behavior, not visible in the repo). Natives that accept "an int" use this test (`getState`, `getFlag`, `getEnchant`, `getQuest`, `getMinionCount`, `getSkill`, `setSkill`, `getItemCost`, `getRepairCost`, `useMenu`, `interact(area)`, the `type` argument of `getUnit`); `JSVAL_IS_NUMBER` + `JS_ValueToECMAUint32` (`getUnit`, `getNext`, `getItem`, `cancel`) accepts both representations. |
| **"Game not ready" warning** | `if (!WaitForGameReady()) THROW_WARNING(cx, vp, "Game not ready")`. `THROW_WARNING` (`js32.h:118-123`) calls `JS_ReportWarning`, sets the return value to `false` and returns `JS_TRUE`, so nothing is thrown. `WaitForGameReady` (`D2Helpers.cpp:153`) returns false at once in menu/null state and true in game. While the client is *busy* (`ClientState()`, `D2Helpers.cpp:125`, for example `pUpdateUnit` set or the room/level not loaded) it polls every 10 ms for up to `Vars.dwGameTimeout` ms (`D2Helpers.cpp:164`). That timeout is ini `[settings] GameReadyTimeout`, default 5 s, multiplied by 1000 (`Helpers.cpp:127,144`); 0 means it waits forever. |
| **rval unset** | The native returns `JS_TRUE` without calling `JS_SET_RVAL`. In this JSAPI the return slot is `vp[0]`, which also holds the callee (`dependencies/include/js/CallArgs.h:317,321`). Its initial contents are documented as "unspecified" and natives "*must* set this" (`dependencies/include/js/CallArgs.h:133-145`). If the engine leaves `vp[0]` as it was on entry, the call evaluates to the function object itself (truthy), **not** `undefined`; this cannot be confirmed from the repo, see [Open questions](#open-questions). Treat "rval unset" as "unspecified, possibly truthy". |
| **argv beyond argc** | A native reads `JS_ARGV(cx,vp)[n]` with `n >= argc`. The JSAPI headers in `dependencies/include` do not say that natives get argv padded to their declared arity, so the value read is engine-dependent (see [Open questions](#open-questions)). |
| **pending-error-but-true** | A JSAPI helper (`JS_ConvertArguments` on too few arguments; `JS_InstanceOf` with a non-NULL `argv` on a class mismatch, which is engine behavior not visible in the repo's headers) reports an error, but the native still returns `JS_TRUE`. The script sees the native's normal failure value, and the engine is left with a reported error and a "success" return at the same time. |
| **no lock** | Unless an entry says otherwise, the native runs on the calling script's thread and reads and writes game memory *without* taking `Vars.cGameLoopSection`. The game thread holds that section except for short yields in `GameDraw` / `TimerProc` (`D2Handlers.cpp:399-419,493-504`), and only `AutoCriticalRoom` users wait for those yields (`CriticalSections.h:31-55`). |

All natives below are `JSNative(cx, argc, vp)` registered with `FUNCTION_FLAGS` = `JSFUN_STUB_GSOPS` (`js32.h:133-134`). Script threads and contexts are described in [../spidermonkey/embedding.md](../spidermonkey/embedding.md).

---

## Unit

Class recap only. Full property tables and identity details are in [unit-properties.md](unit-properties.md).

- **JSClass:** `"Unit"`, `JSCLASS_HAS_PRIVATE`, finalizer `unit_finalize`, constructor `unit_ctor` (`JSGlobalClasses.cpp:108-110`). It is registered through `global_classes` entry `{&unit_class, 0, unit_ctor, 0, unit_methods, unit_props, NULL, NULL}` (`JSGlobalClasses.cpp:145`) → `JS_InitClass` (`ScriptEngine.cpp:232`, called per context at `ScriptEngine.cpp:358-359`). That puts `unit_methods` and `unit_props` on `Unit.prototype`.
- **Methods are also own properties.** Every instance is made by `BuildObject(cx, &unit_class, unit_methods, props, priv)` with `props` = `unit_props` (or `me_props` for the global `me`, `ScriptEngine.cpp:361`), which calls `JS_DefineFunctions` / `JS_DefineProperties` **on the instance** (`js32.cpp:8-28`). Replacing `Unit.prototype.getStat` (or any other name in `unit_methods`) has no effect on existing or new instances because the own copy shadows it; only names that are *not* in the table are inherited from the prototype. Every Unit object costs 25 function objects plus its property slots.
- **Constructor:** `EMPTY_CTOR(unit)` (`JSUnit.cpp:11`, macro `js32.h:136-139`). `new Unit()` throws `"Invalid Operation"`.
- **How instances are obtained:** `getUnit`, `Unit.prototype.getItem`, `getItems`, `getParent`, `getMerc` (this page). Also `copyUnit`, `getInteractedNPC` (`JSGame.cpp:19`, `JSGame.cpp:1386`; see [globals-game.md](globals-game.md)) and the per-context global `me` (`ScriptEngine.cpp:348-366`). `getNext` does **not** create objects: it rewrites the receiver's private data in place.
- **Private data:** `myUnit {_dwPrivateType, dwUnitId, dwClassId, dwType, dwMode, szName[128]}` or `invUnit` (same prefix plus `dwOwnerId, dwOwnerType`) (`JSUnit.h:44-62`). `dwClassId`, `dwMode` and `szName` are **search filters**, not cached unit data (see [Filter persistence](#filter-persistence-on-the-object)). `unit_finalize` deletes the struct by its tag (`JSUnit.cpp:13-31`).
- **Identity:** the object holds `(dwUnitId, dwType)` only and re-resolves the `UnitAny*` on every call (resolve `this`). If the game unit is gone, methods return their failure value. There is no equality hook (`unit_equal` is commented out, `JSUnit.cpp:33-45`), so `==` compares object identity.

---

## Unit search and iteration model

### Where units come from

| JS entry | C++ walk | Container walked | Source |
|---|---|---|---|
| `getUnit(t, …)` t = 0,1,2,4,5 | `GetUnit` → `GetUnitFromTables` | `p_D2CLIENT_ServerSideUnitHashTables[t]` | `Unit.cpp:42-54,14-40` |
| `getUnit(3, …)` (missiles) | same | `p_D2CLIENT_ClientSideUnitHashTables[3]` | `Unit.cpp:48-49` |
| `getUnit(-1 or non-int, …)` | same | server-side tables 0..5 in ascending type order (player, monster, object, missile, item, tile), so the first match comes from the lowest type that has one; client-side missiles are **not** searched | `Unit.cpp:51-54,28` |
| `getUnit(100)` | `D2CLIENT_GetCursorItem()` | n/a | `JSUnit.cpp:603-604` |
| `getUnit(101)` | `D2CLIENT_GetSelectedUnit()` or else `*p_D2CLIENT_SelectedInvItem` | n/a | `JSUnit.cpp:605-608` |
| `unit.getNext()` (PRIVATE_UNIT) | `GetNextUnit` → `GetNextUnitFromTables` | same table family as `getUnit`, keyed on the stored `dwType` | `Unit.cpp:139-151,99-137` |
| `unit.getItem(…)` | `GetInvUnit` | `D2COMMON_GetItemFromInventory(owner->pInventory)` → `D2COMMON_GetNextItemFromInventory` | `Unit.cpp:214-221` |
| `item.getNext()` (PRIVATE_ITEM) | `GetInvNextUnit` | rest of owner's inventory list | `Unit.cpp:223-236` |
| `unit.getItems()` | inline loop | `pInventory->pFirstItem` → `D2COMMON_GetNextItemFromInventory` | `JSUnit.cpp:1316` |

`UnitHashTable` is `UnitAny* table[128]` (`D2Structs.h:664-666`), and both table symbols are indexed `unitTables[type]` for type 0..5, so each is an array of six 0x200-byte tables. The addresses agree with this: `0x7A5270 + 6*0x200 = 0x7A5E70` (server-side start) and `0x7A5E70 + 6*0x200 = 0x7A6A70` (`p_D2CLIENT_PlayerUnit`, `D2Ptrs.h:159-160,202`). Chains are linked through `UnitAny.pListNext` (+0xE4, `D2Structs.h:660`). A unit sits in bucket `dwUnitId & 0x7F` (`Unit.cpp:21,116`).

### `getUnit` argument decoding (`JSUnit.cpp:572-640`)

| Position | Accepted when | Stored into | Default |
|---|---|---|---|
| 0 `type` | `JSVAL_IS_INT` | `nType` | `-1` (any non-int value, including a numeric string or a non-integral double, is treated as "any type") |
| 1 `name` | `JSVAL_IS_STRING` → `JS_EncodeStringToUTF8` | `szName` | `""` |
| 1 `classId` | `JSVAL_IS_NUMBER` → `JS_ValueToECMAUint32` | `nClassId` | `0xFFFFFFFF` |
| 2 `mode` | `JSVAL_IS_NUMBER` → ECMA uint32 | `nMode` | `0xFFFFFFFF` |
| 3 `gid` | `JSVAL_IS_NUMBER` → ECMA uint32 | `nUnitId` | `0xFFFFFFFF` |

`null` / `undefined` / objects in positions 1-3 are ignored, which means "no filter". `-1` in a numeric position becomes `0xFFFFFFFF`, which also means "no filter".

### Filter semantics (`CheckUnit`, `Unit.cpp:238-272`)

The checks run in this order. All must pass.

1. **gid**: `dwUnitId != -1 && pUnit->dwUnitId != dwUnitId` → reject. When a gid is given, `GetUnitFromTables` scans only bucket `gid & 0x7F` of each type in range (`Unit.cpp:20-25`).
2. **type**: the *requested* type (`-1` = any) against `UnitAny.dwType`. Requested types 6..99, ≥102 and negative values other than -1 (all compared as `DWORD`) scan all six server-side tables (`Unit.cpp:51-54`) and never match, so the result is `undefined` after a full scan.
3. **classId**: against `UnitAny.dwTxtFileNo` (+0x04).
4. **mode** (`Unit.cpp:242-258`):

   | `mode` value | Unit type | Test |
   |---|---|---|
   | `0xFFFFFFFF` (-1) | any | no filter |
   | `>= 100` | item (`dwType == 4`) | if `pItemData` is non-NULL: `mode - 100 == pItemData->ItemLocation` (BYTE at ItemData+0x45, `D2Structs.h:494`). An item with NULL `pItemData` passes. The struct comment says this byte is the "Non-body/belt location (Body/Belt == 0xFF)", so equipped and belt items would only match `mode == 355`; the value set is not otherwise defined in the C++. |
   | bit 29 set (`0x20000000`) | non-item | bitmask: passes if `pUnit->dwMode == i` for some set bit `i` in **0..27** (`Unit.cpp:250`) |
   | otherwise | any | `pUnit->dwMode == mode` |

   Consequences:
   - (a) The item-location form compares against `ItemData.ItemLocation` (+0x45). The `location` property returns `ItemData.GameLocation` (+0x68) instead (`JSUnit.cpp:419-421`), so the two numbering schemes differ.
   - (b) Every bitmask is ≥ 100, so for item units it is taken as a location filter and **never matches**. Mode bitmasks cannot be used to search items (`getUnit(4,…)`, `getItem`, `getNext` on items), and in an any-type search all items are dropped.
   - (c) Bits 28-31 other than 29 are ignored.
5. **name** (only if `szName` is non-empty, `Unit.cpp:260-269`): the comparison is `_stricmp`, i.e. byte-wise and ASCII case-insensitive.
   - If the *requested* type is 4 (`UNIT_ITEM`), the unit's name is the 3-character item code `ItemTxt.szCode[0..2]` (`GetItemCode`, `D2Helpers.cpp:96-104`). `"hp5"` matches; a localized name never does.
   - Otherwise it is `GetUnitName` (`D2Helpers.cpp:59-93`):

     | Unit type | Name used |
     |---|---|
     | monster | `D2CLIENT_GetUnitName` (localized) converted to UTF-8 |
     | player | `PlayerData.szName` |
     | item (only reachable from an any-type search) | first line of `D2CLIENT_GetItemName` (localized), UTF-8 |
     | object / tile | `ObjectTxt.szName` (internal ASCII name, not localized) |
     | anything else | `"Unknown"`. A name filter of `"Unknown"` therefore matches every unnamed unit. |

   - "Requested type" means the `dwType` argument of `CheckUnit`. In `getNext` that is the **stored** type, i.e. the first match's concrete type (`JSUnit.cpp:627,668`). So `getUnit(-1, "Short Sword")` can match an item by its localized name, but the following `getNext()` compares the same string against 3-character item codes (type 4), so it cannot match again unless the search string is itself an item code.
   - The JS-side name comes from `JS_EncodeStringToUTF8` in `getUnit` and `getNext`. In `getItem` it is converted to `CP_ACP` (`JSUnit.cpp:1818`), which only matters if item codes were ever non-ASCII.
   - A name search calls the game's name functions **once per scanned unit**, so it is far more expensive than a classId search.

### `getNext` walk order (`GetNextUnitFromTables`, `Unit.cpp:99-137`)

- The receiver's `dwType` is always a concrete 0..5 value: it is copied from the found unit (`JSUnit.cpp:627`, likewise in every other creator). `GetNextUnit` is therefore always called with `dwTypeLow == dwTypeHigh == dwType`, so an any-type `getUnit(-1, …)` iteration **never leaves the first match's type**.
- The walk has two steps. (1) It follows the rest of the current chain from `pListNext` (`Unit.cpp:110-113`). (2) It scans buckets `(gid & 0x7F) + 1 .. 127` of the same type's table (`Unit.cpp:116-121`). The "remaining types" loop (`Unit.cpp:125-134`) is dead for every receiver D2BS creates. If it ever ran it would skip bucket 127 (`j < 127`, `Unit.cpp:127`).
- **Order**: ascending `gid & 0x7F` bucket, then the game's chain order inside a bucket. The chain insertion policy is not visible in the source.
- The **gid filter is not persisted**: `GetNextUnit` passes `(DWORD)-1` (`Unit.cpp:112,120,131`).
- The cursor unit is re-resolved with `D2CLIENT_FindUnit` on every call (`JSUnit.cpp:651`). If that finds it only in the client-side table for a non-missile type, the walk continues along that unit's `pListNext` chain and then over the server-side buckets. The reverse also happens: a missile first found by an any-type `getUnit(-1, …)` comes from the **server-side** table 3, but because the stored type is 3, `getNext` follows its server-side chain and then scans the **client-side** missile buckets (`Unit.cpp:145-146`).

### Inventory iteration

- `getItem` walks `D2COMMON_GetItemFromInventory(owner->pInventory)` → `D2COMMON_GetNextItemFromInventory(item)` with `CheckUnit(..., type 4, ...)` (`Unit.cpp:214-221`). The name filter is therefore always an item code, and mode bitmasks never match (see above).
- `getNext` on a `getItem` result (`PRIVATE_ITEM`) re-resolves the item *and* the owner. It continues only if `item->pItemData->pOwnerInventory == owner->pInventory`, i.e. the item is still in that owner's inventory (`Unit.cpp:224-233`). Otherwise it returns `false`. (The field comment says "Socketed Items owner Inv", `D2Structs.h:499`; that `pOwnerInventory` is set for every inventory item is assumed by `getParent`, `shop` and this check, but is not shown by the source.)
- `getItems` takes a snapshot array, in list order, starting at `Inventory.pFirstItem` (+0x0C, `D2Structs.h:437`). Each element is tagged `PRIVATE_UNIT` even though it is an `invUnit` (`JSUnit.cpp:1317,1322`), so `getNext` on such an element walks the **global item hash table (type 4)**, filtered by that item's own classId and mode. It does not walk the inventory.
- Which items the game links into an inventory list (equipped, belt, stash, cube, cursor, socketed) is game-defined and not visible in the source.

### Filter persistence on the object

| Creator | Tag | `dwType` | `dwClassId` | `dwMode` | `szName` | `getNext` walks |
|---|---|---|---|---|---|---|
| `getUnit(t, f1, f2, f3)` | UNIT | found unit's type | requested or -1 | requested or -1 | requested or "" | that type's table (`JSUnit.cpp:624-629`) |
| `getUnit(100/101, f1, f2, f3)` | UNIT | cursor/selected unit's type | arg 1 if a number, else -1 | arg 2 or -1 | arg 1 if a string, else "" | that type's table, with the filters applied (`JSUnit.cpp:603-610,624-629`) |
| global `me` | UNIT | 0 | -1 | -1 | "" | player table; **rebinds `me`** (see getNext) (`ScriptEngine.cpp:348-356`) |
| `unit.getItem(f1, f2, f3)` | ITEM | 4 | requested | requested | requested | owner's inventory; owner = receiver's stored id and type (`JSUnit.cpp:1842-1849`) |
| `unit.getItems()[i]` | UNIT (an `invUnit` allocation) | 4 | item's own classId | item's own mode | "" | global type-4 table (`JSUnit.cpp:1322-1329`) |
| `getParent()` (monster, item, missile) | UNIT | owner's | owner's classId | owner's mode | "" | owner type's table (`JSUnit.cpp:1600-1605,1626-1631,1643-1648`) |
| `getMerc()` | UNIT | 1 | merc classId | **0** | "" | monster table, filtered to mode 0 (`JSUnit.cpp:1673-1678`) |
| `getInteractedNPC()` | UNIT | NPC's type | NPC's classId | NPC's current mode | "" | NPC type's table, filtered to the NPC's class **and its mode at creation time** (`JSGame.cpp:1401-1406`; see [globals-game.md](globals-game.md)) |
| `copyUnit(u)` | same tag as `u` | copied | copied | copied | copied | same as `u`; `memcpy` of the whole private, including owner fields for `PRIVATE_ITEM` (`JSGame.cpp:29-48`), so the copy and the original iterate independently |

`getNext(nameOrClassId, mode)` overwrites these fields permanently (see its entry).

### Concurrency and staleness

- No search or iteration path takes a lock (no `AutoCriticalRoom` in `Unit.cpp` or in `unit_getUnit` / `unit_getNext`). The game thread can insert and remove units, and free them, while a script thread walks `pListNext` chains, so a script can follow a freed pointer. The commented-out code at `Unit.cpp:56-71,153-182` shows an earlier design that used a D2BS-maintained id list under `Vars.cUnitListSection`.
- When the cursor unit disappears between calls, `getNext` returns `undefined` (`JSUnit.cpp:643,653-654`), **not** `false`. A loop such as `do {…} while (u.getNext())` stops quietly in that case.
- A unit inserted into a bucket or chain position the cursor has already passed is missed. One inserted ahead of the cursor is found.
- When iteration ends (`false`), the object still refers to the last unit it matched (`JSUnit.cpp:676`).
- `getUnit` and `getNext` (PRIVATE_UNIT) check `ClientState() == ClientStateInGame` (`Unit.cpp:43,140`) without waiting. While the client is busy (loading, `pUpdateUnit`) they fail: `getUnit` returns `undefined`, and `getNext` returns `false` if the cursor still resolves. The PRIVATE_ITEM `getNext` path has no state check at all.

---

## Global functions

### `getUnit(type[, nameOrClassId[, mode[, gid]]])`
Finds the first unit that matches the filters and returns a new Unit object whose private data stores those filters for later `getNext` calls.
- **Native:** `unit_getUnit` at `JSUnit.cpp:572`; registered at `JSGlobalFuncs.h:25` (declared arity 1, `JS_FN` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc < 1` → returns `undefined` (`JSUnit.cpp:573-576`). Decoding is in the [table above](#getunit-argument-decoding-jsunitcpp572-640). Special types: `100` = the item on the cursor and `101` = the selected unit (or, failing that, the hovered inventory item). Both ignore the other filters for the lookup but still store them for `getNext`. Nothing throws.
- **Returns:** a Unit object, or `undefined` when nothing matches, when not in game (types other than 100/101), or when `BuildObject` fails.
- **Preconditions:** for types other than 100 and 101, `ClientState() == ClientStateInGame` (`Unit.cpp:43`), with no waiting. Types 100 and 101 do no state check (`JSUnit.cpp:603-608`).
- **Threading & blocking:** runs on the caller's thread with **no lock** and never blocks. It takes a JS request around argument decoding (`JSUnit.cpp:584-599`).
- **Side effects:** none on the game. It allocates a `myUnit` (`JSUnit.cpp:617`), which the finalizer frees.
- **Game internals:** `p_D2CLIENT_ServerSideUnitHashTables`, `p_D2CLIENT_ClientSideUnitHashTables`, `D2CLIENT_GetCursorItem`, `D2CLIENT_GetSelectedUnit`, `p_D2CLIENT_SelectedInvItem`. Name filters use `D2CLIENT_GetUnitName_I` (via `D2CLIENT_GetUnitName_STUB`, `D2Helpers.cpp:712`), `D2CLIENT_GetItemName` and `D2COMMON_GetItemText`. Fields read: `UnitAny.{dwType,dwTxtFileNo,dwUnitId,dwMode,pItemData,pListNext}`, `ItemData.ItemLocation`.
- **Quirks / bugs:**
  - When no string name is given, `szName` points at the literal `""`, which is still passed to `JS_free` (`JSUnit.cpp:582,613,630`). `JS_free` is only declared in the headers (`dependencies/include/jsapi.h:2295`) and implemented in `js_static.lib`; the header-level allocator it pairs with is `js_free` → `free()` (`dependencies/include/js/Utility.h:166-169`). If the library uses that path, this frees a pointer that was never heap-allocated: undefined behavior whose outcome depends on the CRT heap (see [Open questions](#open-questions)).
  - `strcpy_s` into the 128-byte `szName` (`JSUnit.cpp:629`). A name of 128 or more UTF-8 bytes triggers the CRT invalid-parameter handler. The repo installs none (only `SetUnhandledExceptionFilter`, `D2BS.cpp:93`), so the default handler terminates the process.
  - The `// leaked?` comment at `JSUnit.cpp:617` only applies when `BuildObject` fails. Normally the finalizer frees the struct.
  - The `description` property getter writes `p_D2CLIENT_SelectedInvItem` and never restores it (`JSUnit.cpp:453-454`, VA 0x7BCBF4, the same variable as `D2Ptrs.h:203`). `getUnit(101)` can therefore return the last item whose description was read.
  - Legacy docs: `doc/globalFuncs.h:13-14` says the bitmask covers "bits 0-28", but the code tests 0-27 (`Unit.cpp:250`). `resources/api.html:1210-1211` says "bit 30" and "scans the local rooms", but the code uses bit 29 and the unit hash tables. `doc/globalFuncs.h:20,39` declares `type = -1` as a default, but `getUnit()` with no arguments returns `undefined` (`JSUnit.cpp:575-576`). `resources/api.html:1210` calls argument 1 a "localizedName", but for `type == 4` it is the item code and for objects the internal `ObjectTxt.szName` (see [name matching](#filter-semantics-checkunit-unitcpp238-272)).

### `getMercHP()`
Returns the HP percentage of the mercenary owned by the player (global form) or by the receiver (method form, see [below](#unitprototypegetmerchp)).
- **Native:** `unit_getMercHP` at `JSUnit.cpp:1689`; registered as a global at `JSGlobalFuncs.h:26` (declared arity 0, `JS_FN` + `FUNCTION_FLAGS`) and as a method at `JSUnit.h:302` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`). It is also declared in `JSGame.h:36`.
- **Arguments / overloads:** none read. `this` goes through `JS_GetInstancePrivate(cx, this, &unit_class, NULL)`. For a global call `this` is the global object, so the private is NULL and the native uses `D2CLIENT_GetPlayerUnit()` (`JSUnit.cpp:1692-1697`).
- **Returns:** an integer percent (`D2CLIENT_GetUnitHPPercent(merc.gid)`), or `0` if the **owner's** `dwMode == 12` (`JSUnit.cpp:1702`). rval is unset when there is no owner or no merc. `false` plus a warning if the game is not ready.
- **Preconditions:** in game (the "Game not ready" warning).
- **Threading & blocking:** **no lock**. The only wait is the possible `WaitForGameReady` poll.
- **Side effects:** none.
- **Game internals:** `GetMercUnit` (`D2Helpers.cpp:482-498`) walks `pUnit->pAct->pRoom1` → `Room1.pRoomNext`, and each room's `pUnitFirst` → `pRoomNext`. It looks for a monster whose class is one of `MERC_A1/A2/A3/A5` (0x10F/0x152/0x167/0x231, `Constants.h:156-159`) and for which `D2CLIENT_GetMonsterOwner(gid) == owner.gid`. Also `D2CLIENT_GetUnitHPPercent`.
- **Quirks / bugs:** the death check reads the owner's mode instead of the merc's. Mode 12 is `PLAYER_MODE_KICK` for players and `NPC_MODE_DEAD` for monsters (`Constants.h:299,325`), so the function returns 0 while the player is kicking, and a dead merc still reports its percentage. `GetMercUnit` dereferences `pUnit->pAct` without a NULL check. Legacy docs: `doc/globalFuncs.h:122-128` says "health points", but the value is a percent (`doc/Me.h:143-149` and `resources/api.html:1126` say percent correctly).

---

## Method summary

Registration-order summary (`JSUnit.h:300-309`):

| Method | Native | Arity | `this` used? | Blocks? | Game effect |
|---|---|---|---|---|---|
| getNext | `unit_getNext` | 0 | yes | no | none |
| cancel | `unit_cancel` | 0 | **no** | ready-wait | UI close / click |
| repair | `unit_repair` | 0 | resolve only | no | packet 0x35 |
| useMenu | `unit_useMenu` | 0 | classId | no | calls NPC menu callback |
| interact | `unit_interact` | 0 | yes | ready-wait | packet 0x20/0x26, waypoint, or map click |
| getItem | `unit_getItem` | 3 | yes | ready-wait | none |
| getItems | `unit_getItems` | 0 | yes | ready-wait | none |
| getMerc | `unit_getMerc` | 0 | player | ready-wait | none |
| getMercHP | `unit_getMercHP` | 0 | optional | ready-wait | none |
| getSkill | `unit_getSkill` | 0 | yes | ready-wait | none |
| getParent | `unit_getParent` | 0 | yes | ready-wait | none |
| overhead | `my_overhead` | 0 | yes | ready-wait | writes `UnitAny.pOMsg` |
| revive | `my_revive` | 0 | **no** | ready-wait | packet 0x41 |
| getFlags | `item_getFlags` | 1 | item | ready-wait | none |
| getFlag | `item_getFlag` | 1 | item | ready-wait | none |
| getStat | `unit_getStat` | 1 | yes | ready-wait | none |
| getState | `unit_getState` | 1 | yes | ready-wait | none |
| getEnchant | `unit_getEnchant` | 1 | monster | ready-wait | none |
| shop | `item_shop` | 2 | item | ready-wait + **game lock** | `D2CLIENT_ShopAction` |
| setSkill | `unit_setskill` | 2 | **no** | ready-wait + **≈1.1 s poll** | packet 0x3C |
| move | `unit_move` | 2 | yes | ready-wait + **50 ms** | 2 map clicks |
| getQuest | `unit_getQuest` | 2 | **no** | ready-wait | none |
| getMinionCount | `unit_getMinionCount` | 1 | player/monster | ready-wait | none |
| getRepairCost | `me_getRepairCost` | 1 | **no** | ready-wait | none |
| getItemCost | `item_getItemCost` | 1 | item | ready-wait | none |

"Blocks?" lists only waits inside D2BS code. Every native that sends through `D2NET_SendPacket` (`repair`, `interact` item branch, `revive`) can additionally wait on other scripts' `gamepacketsent` listeners (up to 500 ms per listening script, see [interact](#unitprototypeinteractdestareaid)); whether `shop` (`D2CLIENT_ShopAction`) and `setSkill` (`D2CLIENT_SendGamePacket_I`) reach that hook is an open question.

The registered list also contains a commented-out `geSPrice` / `item_getPrice` (`JSUnit.h:27,306`; body commented out at `JSUnit.cpp:1173-1222`), so `getPrice` does not exist.

## Methods: iteration and inventory

### `Unit.prototype.getNext([nameOrClassId[, mode]])`
Moves this Unit object, in place, to the next unit that matches its stored filters. The filters can be overwritten first. Any unit object; behavior differs for `getItem` results.
- **Native:** `unit_getNext` at `JSUnit.cpp:642`; registered at `JSUnit.h:300` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `getNext()`: uses the stored filters.
  - `getNext(string)`: replaces `szName` (UTF-8, `strcpy_s` 128) (`JSUnit.cpp:656-660,692-696`). An empty string clears the name filter.
  - `getNext(number)`: replaces `dwClassId` via ECMA uint32 (`-1` clears it), but only if `!JSVAL_IS_NULL(argv[1])` (`JSUnit.cpp:662,698`).
  - `getNext(x, number)`: replaces `dwMode`, but only if `!JSVAL_IS_NULL(argv[2])` (`JSUnit.cpp:665,701`).
  - A string and a classId filter are independent, so setting one does not clear the other.
- **Returns:** `true` when the object now refers to the next match (its `dwUnitId` is updated, `JSUnit.cpp:678,721`). `false` when there is no further match, or when not in game on the PRIVATE_UNIT path. `undefined` when the private is missing, or when the current unit (or, on the PRIVATE_ITEM path, its owner) no longer resolves (`JSUnit.cpp:643-654,687-690`).
- **Preconditions:** PRIVATE_UNIT path: in game, no wait (`Unit.cpp:140`). PRIVATE_ITEM path: none.
- **Threading & blocking:** **no lock**, no blocking. It takes a JS request around argument parsing.
- **Side effects:** mutates the receiver's private struct (filters and gid). `JS_SetPrivate` with the same pointer is a no-op re-store (`JSUnit.cpp:679,722`). No game effect.
- **Game internals:** `GetNextUnit` / `GetNextUnitFromTables` (`Unit.cpp:139,99`) or `GetInvNextUnit` (`Unit.cpp:223`); `UnitAny.pListNext`, the hash tables, `ItemData.pOwnerInventory` (+0x5C), `UnitAny.pInventory` (+0x60), `D2COMMON_GetNextItemFromInventory`.
- **Quirks / bugs:**
  - The null tests check the *next* argument (`argv[1]` for the classId, `argv[2]` for the mode). For `getNext(5)` and `getNext(x, 3)` that reads beyond argc, and `getNext(5, null)` silently ignores the 5. The intended null check on the same argument would have been redundant anyway, because `JSVAL_IS_NUMBER` already excludes null.
  - `me.getNext()` rewrites the private struct of the global `me`. `me` then refers to another player until `Script::UpdatePlayerGid` runs (`Script.cpp:213-215`), which happens only on game join (`D2Handlers.cpp:84`).
  - On `getItems()` elements and `getMerc()` results, the stored classId and mode filters are the unit's own values (mode 0 for the merc), so their `getNext` behavior is surprising (see [Filter persistence](#filter-persistence-on-the-object)).
  - Legacy docs: `resources/api.html:1006` (copyUnit) correctly states that `getNext` mutates the object in place.

### `Unit.prototype.getItem([nameOrClassId[, mode[, gid]]])`
Returns the first item in the receiver's inventory that matches the filters, as a PRIVATE_ITEM Unit whose `getNext` continues through that inventory. Units with an inventory only.
- **Native:** `unit_getItem` at `JSUnit.cpp:1796`; registered at `JSUnit.h:301` (declared arity 3, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** arg 0 is a string (converted `JS_GetStringCharsZ` → `UnicodeToAnsi(CP_ACP)` → `strcpy_s` into a 128-byte buffer, `JSUnit.cpp:1816-1821`) or a number (classId, ECMA uint32). Arg 1 is the mode (number) and arg 2 the gid (number). Other types are ignored. The name is matched against the **3-character item code** (`CheckUnit` with type 4, `Unit.cpp:216`). Mode follows the [mode table](#filter-semantics-checkunit-unitcpp238-272), but bitmasks never match items.
- **Returns:** a Unit object (`PRIVATE_ITEM`) or `undefined` (no private, unit not found, no `pInventory`, no match, or BuildObject failure). `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait). The receiver must have `UnitAny.pInventory != NULL` (`JSUnit.cpp:1808`).
- **Threading & blocking:** **no lock**. The only wait is `WaitForGameReady`.
- **Side effects:** allocates an `invUnit` holding the filters plus owner = the receiver's stored `dwUnitId` and `dwType` (`JSUnit.cpp:1842-1849`).
- **Game internals:** `D2COMMON_GetItemFromInventory`, `D2COMMON_GetNextItemFromInventory`, `D2COMMON_GetItemText` (`ItemTxt.szCode`, computed offset **+0x80** because it follows `wchar_t szName2[0x40]`; the struct comment says 0x40, `D2Structs.h:510-514`), `ItemData.ItemLocation`.
- **Quirks / bugs:** a name of 128 or more ANSI bytes hits `strcpy_s` (process termination, see getUnit). `JS_ValueToECMAUint32` is called outside a JS request (`JSUnit.cpp:1823-1830`), unlike in `getUnit`. Legacy docs: `doc/Unit.h:98-126` describes mode bitmasks for `getItem`, but for items they never match. It also calls the first argument a "name", but it is an item code.

### `Unit.prototype.getItems()`
Returns an array snapshot of every item in the receiver's inventory list. Units with an inventory only.
- **Native:** `unit_getItems` at `JSUnit.cpp:1292`; registered at `JSUnit.h:302` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** an array of Unit objects in inventory-list order. rval is unset (not an empty array) when the receiver does not resolve, has no `pInventory`, or `pInventory->pFirstItem == NULL` (`JSUnit.cpp:1298-1304`). Throws `"Failed to build item array"` if `BuildObject` fails (`JSUnit.cpp:1332-1336`). `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**. It roots the array and holds a JS request for the whole loop.
- **Side effects:** allocates one `invUnit` per item.
- **Game internals:** `Inventory.pFirstItem` (+0x0C), `D2COMMON_GetNextItemFromInventory`, `UnitAny.{dwMode,dwTxtFileNo,dwUnitId}`.
- **Quirks / bugs:**
  - Elements are tagged `PRIVATE_UNIT` (`JSUnit.cpp:1322`), so `getNext` on one walks the global item table, not the inventory. `dwOwnerId` and `dwOwnerType` are filled in but never used.
  - `unit_finalize` deletes these elements as `myUnit*` although they were allocated as `invUnit` (`JSUnit.cpp:18-21`). This is a size-mismatched delete, which is harmless for a POD struct under MSVC but formally undefined behavior.
  - The first item comes from `pInventory->pFirstItem`, while `getItem` starts from `D2COMMON_GetItemFromInventory`. Whether the two always agree is not determinable from the source.
  - On a BuildObject failure the `invUnit` leaks.

---

## Methods: stats, state, skills, flags

### `Unit.prototype.getStat(stat[, subIndex])`
Reads a stat value, or returns all of the unit's stats as an array (`-1`) or as a sparse table (`-2`). Any unit.
- **Native:** `unit_getStat` at `JSUnit.cpp:891`; registered at `JSUnit.h:305` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments(argc, argv, "i/i", &nStat, &nSubIndex)` (`JSUnit.cpp:910`), which applies ToInt32 to both (numeric strings work; a non-numeric value such as `"abc"` or an explicit `undefined` becomes 0, i.e. stat 0; an object argument can run its `valueOf`). `subIndex` defaults to 0. With no arguments, conversion fails and the native returns `false` (pending-error-but-true). The forms are:

  | `stat` | Computation | JS result | Scaling |
  |---|---|---|---|
  | 6..11 (`STAT_HP`..`STAT_MAXSTAMINA`, `Constants.h:170-175`) | `D2COMMON_GetUnitStat(u, stat, sub) >> 8` | int | **÷256** (`>> 8`) |
  | 13, 29, 30 (`STAT_EXP`, `STAT_LASTEXP`, `STAT_NEXTEXP`, `Constants.h:177,184-185`) | `(unsigned)GetUnitStat` | number (unsigned 32-bit) | none |
  | 92 (`STAT_ITEMLEVELREQ`, `Constants.h:206`) | `D2COMMON_GetItemLevelRequirement(u, player)`; `sub` is ignored, and the call is made for any unit type | int | none |
  | -1 | Copies `D2COMMON_GetStatList(u, NULL, 0x40)` into `Stat[256]` via `D2COMMON_CopyStatList`, then appends each `u->pStats->StatVec` entry not already present (deduplicated on exact `(value, stat, sub)`) (`JSUnit.cpp:924-948`) | array of `[statId, subIndex, value]` (`JSUnit.cpp:957-963`) or **`false`** if `GetStatList` returns NULL | **raw**: HP/mana/stamina stay ×256, and values ≥ 2^31 become negative (`INT_TO_JSVAL`) |
  | -2 | `InsertStatsToGenericObject(u, u->pStats)` then the same for `GetStatList(u, NULL, 0x40)` (`JSUnit.cpp:972-979`) | sparse array indexed by stat id (see below) | ids 6..11 shifted `>> 8` (`JSUnit.cpp:1074-1075`) |
  | anything else | `(long)GetUnitStat(u, stat, sub)`. If 0, it searches a copy of the 0x40 stat list for an exact `(stat, sub)` match and the last match wins (`JSUnit.cpp:980-993`) | number (signed 32-bit) | none |

  Layout of `getStat(-2)` (`InsertStatsNow`, `JSUnit.cpp:1021-1095`). A stat list's `StatVec` is included only if the list belongs to this unit (`dwUnitId` and `dwUnitType` match, or `pUnit == u`). Its `SetStatVec` is included if `(dwFlags >> 24) & 0x80`, i.e. bit 31 is set (`JSUnit.cpp:1005-1018`, `StatList` fields at `D2Structs.h:413-431`). Each `Stat {wSubIndex, wStatIndex, dwStatValue}` (`D2Structs.h:400-404`) is placed as follows:
  - `wSubIndex <= 0x200`: `result[statId][subIndex] = value`. Both levels are sparse arrays.
  - `wSubIndex > 0x200` (skill-encoded): `result[statId] = {skill: sub >> 6, level: sub & 0x3F}`. When `value > 0x200` the object also gets `charges: value & 0xFF` and `maxcharges: value >> 8`; these two keys are present only when `maxcharges > 0`. A second object for the same stat id turns the slot into `[old, new]`, and later ones are appended (see the bug below). If the slot already holds the sparse array of a normal stat, `JS_IsArrayObject` is true and the object is appended into that array at `length + 1`.
- **Returns:** as in the table. `false` when `this` cannot be resolved, the conversion fails, or the game is not ready (with a warning).
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**. The `-1` path takes a JS request per element.
- **Side effects:** none on the game.
- **Game internals:** `D2COMMON_GetUnitStat`, `D2COMMON_GetStatList`, `D2COMMON_CopyStatList`, `D2COMMON_GetItemLevelRequirement`, `D2CLIENT_GetPlayerUnit`; `UnitAny.pStats` (+0x5C), `StatList.{pUnit,dwUnitType,dwUnitId,dwFlags,StatVec,SetStatVec}`.
- **Quirks / bugs:**
  - `-1`: there is no bounds check when appending to `aStatList[256]` (`JSUnit.cpp:943-946`), so a combined count above 256 overflows the stack buffer. `pUnit->pStats` is dereferenced without a NULL check (`JSUnit.cpp:934`). On the `!pArrayInsert` path a JS root and a JS request leak (`JSUnit.cpp:950-955`).
  - `-2`: appending to an existing array writes at index `len+1` after `len++` (`JSUnit.cpp:1058-1063`), which leaves holes (`[a, b, , c]`). A skill object stored in a slot that a normal stat later writes into gains numeric keys. If `pUnit->pStats` and the 0x40 list overlap, skill-encoded entries appear twice. Skill-encoded sub-indices with skill id ≤ 7 (`sub ≤ 0x1FF`), and skill 8 at level 0 (`sub == 0x200`), fail the `> 0x200` test and are stored as normal stats.
  - Negative `stat` values other than -1 and -2 go straight to `D2COMMON_GetUnitStat` with a huge index.
  - `GetStatList`'s third parameter is declared `dwMaxEntries` (`D2Ptrs.h:304`) but receives `0x40`, which looks like a flag (see Open questions).
  - Legacy docs: `doc/Unit.h:301-310` says "first 64 stats" for -1, but the code copies up to 256 plus extras. `-2` is undocumented (`doc/Me.h:305` "TODO"). `doc/Unit.h:275,289` says only stat 13 is a double, but 29 and 30 are unsigned as well.

### `Unit.prototype.getState(state)`
Tests whether the unit currently has the given state id. Any unit.
- **Native:** `unit_getState` at `JSUnit.cpp:1097`; registered at `JSUnit.h:305` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argv[0]` must be `JSVAL_IS_INT` (tested without an argc check), and is then passed through `JS_ValueToInt32`. A non-int returns `false`. A value outside `0..183` returns `false` (`JSUnit.cpp:1122-1123`).
- **Returns:** boolean `!!D2COMMON_GetUnitState(u, state)`, or `false` on any failure.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `D2COMMON_GetUnitState`.
- **Quirks / bugs:** the upper bound 183 is hardcoded (`// TODO: make these constants`, `JSUnit.cpp:1121`). `getState()` reads argv beyond argc.

### `Unit.prototype.getFlags()`
Returns the raw item flag word. Items only.
- **Native:** `item_getFlags` at `JSUnit.cpp:1130`; registered at `JSUnit.h:304` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** int `ItemData.dwFlags` (+0x18, `D2Structs.h:482`) via `INT_TO_JSVAL`, so bit 31 makes it negative. rval is unset if the receiver does not resolve or is not an item.
- **Preconditions:** in game (ready-wait). The unit must be an item.
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `UnitAny.pItemData` (+0x14) → `ItemData.dwFlags`.
- **Quirks / bugs:** `pItemData` is not NULL-checked. The flag meanings in `doc/Unit.h:219-259` (0x10 identified, 0x400000 ethereal, …) are not defined anywhere in the C++.

### `Unit.prototype.getFlag(mask)`
Tests whether any of the bits in `mask` are set in `ItemData.dwFlags`. Items only.
- **Native:** `item_getFlag` at `JSUnit.cpp:1149`; registered at `JSUnit.h:304` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 1` and `JSVAL_IS_INT(argv[0])` are required. Otherwise rval is unset (`JSUnit.cpp:1153-1154`).
- **Returns:** boolean `!!(mask & dwFlags)`. rval is unset on failure.
- **Preconditions:** in game (ready-wait). The unit must be an item.
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `ItemData.dwFlags`.
- **Quirks / bugs:** any-bit semantics (matches `doc/Unit.h:261-271`). The return value is unset rather than `false` on failure.

### `Unit.prototype.getEnchant(enchant)`
Tests whether a monster has the given enchant id. Monsters only.
- **Native:** `unit_getEnchant` at `JSUnit.cpp:1900`; registered at `JSUnit.h:307` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 1` and an int argument are required. Otherwise rval is unset.
- **Returns:** `true` if any of `MonsterData.anEnchants[0..8]` (+0x1C, BYTE[9], `D2Structs.h:558`) equals the argument. Otherwise the **number `0`** (`JSUnit.cpp:1918`). rval is unset if the receiver does not resolve or is not a monster.
- **Preconditions:** in game (ready-wait). The unit must be a monster.
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `UnitAny.pMonsterData` → `anEnchants`.
- **Quirks / bugs:** returns `0`, not `false`, on a miss. `pMonsterData` is not NULL-checked. Each enchant slot is a BYTE, so only values 0..255 can match. Legacy docs: `doc/Unit.h:378-384` says it returns bool.

### `Unit.prototype.getSkill(selectorOrSkillId[, bTotal[, chargedOnly]])`
Reads hand skills or the full skill list (1-argument form), or the level of a specific skill (2- and 3-argument forms). Units with a non-NULL `UnitAny.pInfo`. Which unit types carry one is game-defined.
- **Native:** `unit_getSkill` at `JSUnit.cpp:1347`; registered at `JSUnit.h:303` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc == 0` or `argc > 3` → rval unset (`JSUnit.cpp:1348-1349`; this check runs *before* the ready-wait). Arg 0 and arg 1 must be `JSVAL_IS_INT` and arg 2 `JSVAL_IS_BOOLEAN`; anything else → rval unset (`JSUnit.cpp:1366-1385`).
  - `getSkill(0)`: localized name of the **right**-hand skill. `getSkill(1)`: the **left**-hand skill's name. Each is looked up as `skills.txt[id].skilldesc` → `skilldesc.txt[row]."str name"` → `D2LANG_GetLocaleText` (`JSUnit.cpp:1391-1406`).
  - `getSkill(2)`: right-hand skill id. `getSkill(3)`: left-hand skill id (`JSUnit.cpp:1408-1413`).
  - `getSkill(4)`: array of `[skillId, baseLevel (Skill.dwSkillLevel +0x28), totalLevel (D2COMMON_GetSkillLevel(u, s, 1))]` over the whole `pInfo->pFirstSkill` → `pNextSkill` list (`JSUnit.cpp:1414-1440`).
  - Any other single int → `false`.
  - `getSkill(id, bTotal)`: the first skill with that id **and `IsCharge == 0`** → `D2COMMON_GetSkillLevel(u, s, bTotal)`.
  - `getSkill(id, bTotal, chargedOnly)`: with `chargedOnly == false`, the first skill with that id regardless of charge. With `true`, the first skill with that id and `IsCharge == 1` (`Skill.IsCharge` +0x3C) (`JSUnit.cpp:1449-1458`).
- **Returns:** a string, int or array as above. `false` when no skill matches or the selector is unknown. rval is unset on bad argument types, when the private is missing, when the unit does not resolve, or when a name lookup fails. `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait). Every 1-argument form, including `getSkill(4)` and unknown selectors, requires non-NULL `pInfo`, `pLeftSkill` and `pRightSkill` (both hand ids are read before the `switch`, `JSUnit.cpp:1386-1389`).
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `UnitAny.pInfo` (+0xA8) → `Info.{pFirstSkill,pLeftSkill,pRightSkill}` (`D2Structs.h:469-474`), `Skill.{pSkillInfo->wSkillId,dwSkillLevel,IsCharge}`, `D2COMMON_GetSkillLevel`, `D2LANG_GetLocaleText`, MPQ tables via `FillBaseStat` (`MPQStats.cpp:68`).
- **Quirks / bugs:**
  - There is no private-type check (`JSUnit.cpp:1358-1360`).
  - The 1-argument form dereferences `pInfo->pLeftSkill->pSkillInfo` and `pRightSkill->pSkillInfo` with no NULL checks (`JSUnit.cpp:1388-1389`), so it crashes on units without `pInfo` (e.g. items, objects).
  - In `getSkill(4)`, `pSkillInfo` is not checked, and the `continue` on an `!pArrayInsert` failure leaks a root (`JSUnit.cpp:1420-1423`).
  - Legacy docs: `doc/Unit.h:177-189` says "Only the first 256 skills are read", but the code has no limit. `doc/Unit.h:191-197` leaves `nExt` unexplained; it is the `bTotal` flag passed to `D2COMMON_GetSkillLevel` (`D2Ptrs.h:313`).

### `Unit.prototype.getQuest(act, quest)`
Returns a quest flag from the **local player's** client quest record. `this` is ignored.
- **Native:** `unit_getQuest` at `JSUnit.cpp:1929`; registered at `JSUnit.h:308` (declared arity 2, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 2` and two `JSVAL_IS_INT` arguments are required. Otherwise rval is unset.
- **Returns:** int `D2COMMON_GetQuestFlag(D2CLIENT_GetQuestInfo(), act, quest)` (`JSUnit.cpp:1939`).
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `D2CLIENT_GetQuestInfo`, `D2COMMON_GetQuestFlag`.
- **Quirks / bugs:** does not read `this`, so `anyUnit.getQuest()` returns the player's flags. The act and quest ranges are not validated.

### `Unit.prototype.getMinionCount(type)`
Returns the game's minion count of the given type for a player or monster.
- **Native:** `unit_getMinionCount` at `JSUnit.cpp:1944`; registered at `JSUnit.h:308` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 1` and an int argument are required. Otherwise rval is unset.
- **Returns:** int `D2CLIENT_GetMinionCount(u, type)`. rval is unset when the unit does not resolve or is not a player or monster (`JSUnit.cpp:1960-1961`).
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** none known.
- **Game internals:** the `__cdecl` wrapper at `D2Helpers.cpp:927-945` loads `ECX=pUnit` and `EDX=type` and calls the ASMPTR `D2CLIENT_GetMinionCount_I` (`D2Ptrs.h:262`). See [../memory/call-stubs.md](../memory/call-stubs.md).
- **Quirks / bugs:** the meaning of `type` (pet type index) is not defined in the C++.

---

## Methods: relations (parent / merc)

### `Unit.prototype.getParent()`
Returns a unit's owner: a Unit for monsters, items and missiles, or the owner-name string for objects.
- **Native:** `unit_getParent` at `JSUnit.cpp:1572`; registered at `JSUnit.h:303` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:**
  - **monster:** `D2CLIENT_GetMonsterOwner(gid)`. If that is `-1` → `undefined`. Otherwise `GetUnit(NULL, -1, -1, -1, ownerId)` (any server-side type) → a Unit (`JSUnit.cpp:1587-1611`).
  - **object:** a string copy of `ObjectData.szOwner` (+0x28, char[16], `D2Structs.h:594`), interned. `undefined` if `pObjectData` is NULL (`JSUnit.cpp:1612-1618`).
  - **item:** a Unit for `pItemData->pOwnerInventory->pOwner` if the whole chain is non-NULL (`JSUnit.cpp:1619-1635`).
  - **missile:** a Unit for `D2COMMON_GetMissileOwnerUnit(u)` (`JSUnit.cpp:1636-1652`).
  - **player / tile, or the receiver not resolving:** `undefined`.
  - `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** allocates `myUnit` structs whose classId and mode filters are the owner's own values.
- **Game internals:** `D2CLIENT_GetMonsterOwner`, `D2COMMON_GetMissileOwnerUnit` (named D2COMMON, but RVA 0x639D0 sits in the D2Client range next to `FindServerSideUnit` 0x639B0, `D2Ptrs.h:344,68`), `ItemData.pOwnerInventory`, `Inventory.pOwner` (+0x08), `ObjectData.szOwner`.
- **Quirks / bugs:** in the missile branch `new myUnit` runs before the owner NULL check, so it leaks when there is no owner (`JSUnit.cpp:1637-1641`). The item and missile branches do not check the `BuildObject` result (`JSUnit.cpp:1632-1634,1650-1651`). For objects, `JS_InternString` permanently interns every owner name.

### `Unit.prototype.getMerc()`
Returns the mercenary owned by this player as a Unit, or `null`. Players only.
- **Native:** `unit_getMerc` at `JSUnit.cpp:1658`; registered at `JSUnit.h:302` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** a Unit (type 1), or `null` if the receiver does not resolve, is not a player, or has no merc (`JSUnit.cpp:1664-1686`). `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait). The unit must be a player.
- **Threading & blocking:** **no lock**. It walks every Room1 of the act (`GetMercUnit`, `D2Helpers.cpp:482-489`).
- **Side effects:** allocates a `myUnit` with `dwMode = 0` (`JSUnit.cpp:1676`).
- **Game internals:** `UnitAny.pAct` (+0x1C) → `Act.pRoom1` (+0x10) → `Room1.pRoomNext` (+0x7C); `Room1.pUnitFirst` (+0x74) → `UnitAny.pRoomNext` (+0xE8) (`D2Structs.h:332-366,661`); `D2CLIENT_GetMonsterOwner`.
- **Quirks / bugs:** the stored mode filter is 0, so `merc.getNext()` looks only for mode-0 (death mode) monsters of the same class. Legacy docs: `doc/Unit.h:134-143` documents `getMerc(bool dummy)` returning a bool, but the code reads no arguments.

### `Unit.prototype.getMercHP()`
Same native as the global [`getMercHP()`](#getmerchp). As a method it reports the receiver's merc: `JS_GetInstancePrivate` succeeds for any Unit, including items and monsters, and `GetMercUnit(pUnit)` then dereferences `pUnit->pAct`.
- **Native:** `unit_getMercHP` at `JSUnit.cpp:1689`; registered at `JSUnit.h:302` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read. If the receiver's private is a Unit private it is used; otherwise the player is used.
- **Returns:** as for the global.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** as for the global.
- **Quirks / bugs:** as for the global. There is no type check (`JSUnit.cpp:1697-1700`).

---

## Methods: game actions

### `Unit.prototype.interact([destAreaId])`
Interacts with a unit. Inventory, stash and belt items get a packet (0x20 / 0x26). A waypoint object given an area id travels there. Everything else gets a single left-down click on the map with that unit selected. Not for `me`.
- **Native:** `unit_interact` at `JSUnit.cpp:816`; registered at `JSUnit.h:301` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `interact()`. For objects only: `interact(areaId)` with **exactly** one int argument (`argc == 1 && JSVAL_IS_INT`) → `JS_ValueToECMAInt32` (`JSUnit.cpp:854-862`). Any other argument shape falls back to the click.
- **Returns:** `false` if the receiver does not resolve or is the player (`JSUnit.cpp:829-830`). **`false`** after sending the inventory/stash/belt item packet (rval is never switched to true, `JSUnit.cpp:822,843,850`). `false` if the waypoint target's `levels.txt` `Waypoint` field is 255 (`JSUnit.cpp:864-866`). `true` after a waypoint take or a map click. `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait). The game state the click needs (range, UI) is not checked.
- **Threading & blocking:** **no lock**. It does not wait for the interaction to happen.
- **Side effects:**
  - **Item, mode ∉ {3 on-ground, 5 being-dropped}, `GetItemLocation` (= `ItemData.GameLocation`, `D2Helpers.cpp:455-460`):**
    - `LOCATION_INVENTORY` (3) or `LOCATION_STASH` (7): sends a 13-byte packet via `D2NET_SendPacket(13, 1, p)`: `[0]=0x20, [1..4]=item gid, [5..8]=player Path.xPos, [9..12]=player Path.yPos` (`JSUnit.cpp:837-843`).
    - `LOCATION_BELT` (2): `[0]=0x26, [1..4]=item gid, [5..12]=0` (`JSUnit.cpp:844-850`).
    - Other locations (equip, store, trade, cube, …) fall through to the click.
    The source never names what these packets mean. `doc/Unit.h:83-88` says inventory/stash items are "picked up".
  - **Object + areaId:** `D2CLIENT_TakeWaypoint(objectGid, areaId)` (`JSUnit.cpp:868`; naked stub `D2Helpers.cpp:872-904`, which reserves a 0x20-byte local struct with its first DWORD zeroed, sets `ESI=&struct`, `EDI=0`, `EBX=1`, `EDX=gid` and pushes `ECX=area`, then jumps to the mid-function address in `D2CLIENT_TakeWaypoint_I` 0x49D0F1). Then, if `!D2CLIENT_GetUIState(UI_GAME)`, it calls `D2CLIENT_CloseInteract()` (`JSUnit.cpp:869-870`).
  - **Otherwise:** `ClickMap(0, x, y, FALSE, pUnit)` (`Core.cpp:134-179`). This computes screen coordinates (`D2COMMON_MapToAbsScreen` minus `p_D2CLIENT_ViewportX/Y`), temporarily zeroes `p_D2CLIENT_MouseX/Y`, and sets `Vars.dwSelectedUnitId/Type` and `Vars.bClickAction` so that the patched `GetSelectedUnit` call inside `D2CLIENT_ClickMap` (`Patch.h:13` at 0x462D72 → `GetSelectedUnit_Intercept`, `D2Intercepts.cpp:92-104`) returns this unit. It then calls `D2CLIENT_ClickMap(0, sx, sy, AlwaysRun ? 0x08 : 0)` and `D2CLIENT_SetSelectedUnit(NULL)`. Only click type 0 is sent; no matching button-up click follows (contrast `move`).
  - Packets sent through `D2NET_SendPacket` pass through D2BS's own sent-packet hook (`Patch.h:12`, 0x52AE5A) → `GamePacketSentEvent` (`Events.cpp:337-340`). Listener scripts can therefore block the packet: `GamePacketSent` returns `!GamePacketSentEvent(...)` (`D2Handlers.cpp:171-173`), and the native still reports its normal result because it never learns the packet was dropped. A `gamepacketsent` listener in the *calling* script runs synchronously inside this native (re-entrant JS), and a listener in another script is waited for for up to 500 ms (`Events.cpp:306-318`). `ScriptEngine::ForEachScript` visits the scripts one after another (`ScriptEngine.cpp:221-224`), so the worst case is 500 ms per listening script. See [events.md](events.md).
- **Game internals:** `GetItemLocation`, `D2NET_SendPacket`, `D2CLIENT_GetPlayerUnit()->pPath->{xPos,yPos}` (Path +0x02/+0x06), `FillBaseStat("levels", id, "Waypoint")` (`MPQStats.h:1383`, DATA_BYTE), `D2CLIENT_TakeWaypoint_I`, `D2CLIENT_GetUiVar_I` (via `D2CLIENT_GetUIVar_STUB`, `D2Helpers.cpp:720`), `D2CLIENT_CloseInteract`, `D2CLIENT_ClickMap`, `D2CLIENT_GetUnitX/Y`.
- **Quirks / bugs:**
  - The waypoint validation passes when `FillBaseStat` fails (e.g. an out-of-range or negative area id, because `GetBaseTable` bounds-checks with `(DWORD)row < max`, `MPQStats.cpp:58`), and `TakeWaypoint` is then called with the unchecked id.
  - Neither branch checks that the object is actually a waypoint.
  - The item packet paths return `false` even though they acted.
  - The player's `pPath` is dereferenced without a check.
  - The click branch sets rval `true` before calling `ClickMap` (`JSUnit.cpp:880-881`). `ClickMap` re-checks `ClientState()` and silently does nothing if the client is no longer in game (`Core.cpp:135-136`), so `true` does not prove a click was issued.
  - The selection override uses the unsynchronized globals `Vars.bClickAction` / `Vars.dwSelectedUnitId` / `Vars.dwSelectedUnitType` (`D2BS.h:44,121-122`). Two scripts clicking at the same time, or a user click that the game thread routes through the same `GetSelectedUnit` call site during the window, see each other's selection.

### `Unit.prototype.move([x, y])`
Sends a map click (type 0, 50 ms pause, type 2) at map coordinates `(x, y)` when the receiver resolves to the local player unit (`me`, or any Unit that resolves to the same `UnitAny*`, `JSUnit.cpp:1879`), or at the receiver's current position for any other unit, with no unit selected; the game then moves the player there.
- **Native:** `unit_move` at `JSUnit.cpp:1861`; registered at `JSUnit.h:308` (declared arity 2, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** if the receiver resolves to the player: `argc >= 2` is required, then `JS_ValueToInt32(argv[0])` and `JS_ValueToInt32(argv[1])` (coercing). On failure rval is unset. For any other unit, the arguments are ignored and the target is `D2CLIENT_GetUnitX/Y(u)` (`JSUnit.cpp:1879-1891`).
- **Returns:** rval is **always unset**, except for `false` plus a warning when the game is not ready.
- **Preconditions:** in game (ready-wait). The player unit must exist.
- **Threading & blocking:** **no lock**. It calls `Sleep(50)` between the two clicks on the script thread (`JSUnit.cpp:1894`). It does not wait for the movement.
- **Side effects:** `ClickMap(0, (WORD)x, (WORD)y, FALSE, NULL)`, then `ClickMap(2, …)` (`JSUnit.cpp:1893-1895`). With `pUnit == NULL`, `ClickMap` clears `Vars.dwSelectedUnitId` and sets `bClickAction`, so the intercept returns NULL and the click targets the map rather than a unit. Click types 0 and 2 are "left down" and "left up" according to the legacy table at `resources/api.html:989-995`; the C++ does not name them. The `0x08` run flag is added when `*p_D2CLIENT_AlwaysRun` is set (`Core.cpp:172`).
- **Game internals:** `D2CLIENT_ClickMap`, `D2COMMON_MapToAbsScreen`, `p_D2CLIENT_ViewportX/Y`, `p_D2CLIENT_MouseX/Y`, `p_D2CLIENT_AlwaysRun`, `D2CLIENT_GetUnitX/Y`.
- **Quirks / bugs:** coordinates are truncated to 16 bits (`(WORD)` casts). `JS_ValueToInt32` runs outside a JS request and, for an object argument, can invoke script code (`valueOf`). Each `ClickMap` silently does nothing if the client is not in game at that instant (`Core.cpp:135-136`), so a state change during the 50 ms sleep can leave a button-down without its button-up. The commented-out `D2CLIENT_Move` (`JSUnit.cpp:1896`) shows that an earlier version moved the player directly. Legacy docs: `doc/Unit.h:422-432` says void; the actual return is unset.

### `Unit.prototype.useMenu(menuId)`
Invokes an NPC dialog menu entry by calling the game's menu callback for the receiver NPC's class directly. NPC units.
- **Native:** `unit_useMenu` at `JSUnit.cpp:796`; registered at `JSUnit.h:301` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argc >= 1` and `JSVAL_IS_INT(argv[0])` are required. Otherwise the result is `false` (`JSUnit.cpp:800-801`).
- **Returns:** boolean `ClickNPCMenu(u->dwTxtFileNo, menuId)`. `false` if `this` does not resolve.
- **Preconditions:** in game. There is **no** `WaitForGameReady` call; the in-game state only matters through `D2CLIENT_FindUnit`. The NPC menu being open is *not* checked.
- **Threading & blocking:** **no lock**. The game callback runs on the script thread.
- **Side effects:** `ClickNPCMenu` (`D2Helpers.cpp:413-453`) treats the address `p_D2CLIENT_NPCMenu` (0x726C48) as an **inline array** of packed `NPCMenu` records (sizeof 0x27 under `#pragma pack(1)`, `D2Structs.h:700-716`) of length `*p_D2CLIENT_NPCMenuAmount`. For the record whose `dwNPCClassId` matches, the first `wEntryIdN == menuId` (N = 1..4) selects `dwEntryFuncN`. That function is called as `void(*)(void)`, and the result is `TRUE`. A NULL function pointer gives `FALSE`.
- **Game internals:** `p_D2CLIENT_NPCMenu` (declared `NPCMenu*` in `D2Ptrs.h:168`, but used as the table itself and never dereferenced), `p_D2CLIENT_NPCMenuAmount`, `NPCMenu.{dwNPCClassId,wEntryId1..4,dwEntryFunc1..4}`.
- **Quirks / bugs:** `menuId` is a menu *entry id* matched against `wEntryId1..4`, not an index; `doc/Unit.h:77` says "Index of the menu item". A game UI callback is invoked off the game thread without a lock.

### `Unit.prototype.cancel([mode])`
Closes the current interaction, NPC dialog or scrolling text, or, when an item is on the cursor, clicks the map at screen (10,10). `this` is ignored.
- **Native:** `unit_cancel` at `JSUnit.cpp:730`; registered at `JSUnit.h:300` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `cancel(number)`: `JS_ValueToECMAUint32` into a signed int (`JSUnit.cpp:737-741`).
  - `cancel(non-number)`: mode stays `-1` and nothing happens.
  - `cancel()`: auto-detects the mode (`JSUnit.cpp:742-749`): `IsScrollingText()` → 3, `D2CLIENT_GetCurrentInteractingNPC()` → 2, `D2CLIENT_GetCursorItem()` → 1, otherwise 0.
- **Returns:** always `true` (`JSUnit.cpp:767`), except for `false` plus a warning when the game is not ready.
- **Preconditions:** in game (ready-wait). `IsScrollingText` also calls `WaitForGameReady` (`D2Helpers.cpp:1000`).
- **Threading & blocking:** **no lock**.
- **Side effects:** mode 0 → `D2CLIENT_CloseInteract()`. Mode 1 → raw `D2CLIENT_ClickMap(0, 10, 10, 0x08)` at screen (10,10), bypassing the `ClickMap` wrapper and selection override (`JSUnit.cpp:756`). Mode 2 → `D2CLIENT_CloseNPCInteract()`. Mode 3 → `D2CLIENT_ClearScreen()`. Other values do nothing. `*p_D2CLIENT_AutomapOn` is saved before and restored after (`JSUnit.cpp:734,766`).
- **Game internals:** `D2CLIENT_CloseInteract`, `D2CLIENT_ClickMap`, `D2CLIENT_CloseNPCInteract`, `D2CLIENT_ClearScreen`, `D2CLIENT_GetCurrentInteractingNPC`, `D2CLIENT_GetCursorItem`, `p_D2CLIENT_AutomapOn`. `IsScrollingText` (`D2Helpers.cpp:998-1029`) walks `p_STORM_WindowHandlers` for the D2 HWND and looks for a 0x201 handler equal to `D2CLIENT_CloseNPCTalk`.
- **Quirks / bugs:** works on any receiver. The cursor-item click bypasses D2BS's selection override: `Vars.bClickAction` is FALSE, so the patched `GetSelectedUnit` call inside `D2CLIENT_ClickMap` returns the game's own current selection (`D2Intercepts.cpp:92-104`), and the mouse position is not zeroed; the effect therefore depends on what the game currently has selected/hovered, not only on screen (10,10). Legacy docs: `doc/Unit.h:54-61` says the cursor item is "dropped"; the source only shows the click. The explicit `mode` argument is undocumented.

### `Unit.prototype.repair()`
Sends a "repair" packet addressed to the **most recently interacted** NPC. The receiver must resolve but is not used otherwise.
- **Native:** `unit_repair` at `JSUnit.cpp:771`; registered at `JSUnit.h:300` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `true` after sending. `false` if `this` does not resolve.
- **Preconditions:** no `WaitForGameReady`. The receiver must resolve. Whether a repair UI is open is not checked.
- **Threading & blocking:** **no lock**. It goes through the sent-packet hook (see interact).
- **Side effects:** a 17-byte packet via `D2NET_SendPacket(17, 1, p)`: `[0]=0x35, [1..4]=*p_D2CLIENT_RecentInteractId, [5..15]=0, [16]=0x80` (`JSUnit.cpp:783-787`). The commented-out `D2CLIENT_PerformNpcAction` path "crashes while minimized" (`JSUnit.cpp:789-790`).
- **Game internals:** `p_D2CLIENT_RecentInteractId` (VA 0x7C0D25, unaligned, `D2Ptrs.h:189`), `D2NET_SendPacket`.
- **Quirks / bugs:** the receiver's gid is not put into the packet, so `anyUnit.repair()` repairs at whatever NPC was last interacted with. Legacy docs: `doc/Unit.h:63-70` implies the receiver is the NPC.

### `Unit.prototype.shop(mode)`
Buys (mode 2 or 6) or sells (mode 1) this item at the open NPC shop by calling the game's `ShopAction`, while holding the game-loop lock. Items only.
- **Native:** `item_shop` at `JSUnit.cpp:1464`; registered at `JSUnit.h:307` (declared arity 2, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** the mode is taken from the **last** argument: `JSVAL_TO_INT(argv[argc-1])` with no type check (`JSUnit.cpp:1497`). Other arguments are ignored. With `argc == 0` this reads `argv[-1]`, which is `this`. A non-int jsval decodes to garbage, which almost always fails the `{1,2,6}` check.
- **Returns:** `true` once `ShopAction` has been called. Otherwise `false`: `this` does not resolve or is not an item, `UI_NPCSHOP` (0x0C) is closed, a transaction dialog is pending, there is no interacting NPC, the mode is invalid, or the ownership check fails. `false` plus a warning if the game is not ready.
- **Preconditions:**
  - In game (ready-wait).
  - `*p_D2CLIENT_TransactionDialog == 0`, `*p_D2CLIENT_TransactionDialogs == 0` and `*p_D2CLIENT_TransactionDialogs_2 == 0` (`JSUnit.cpp:1472`).
  - `D2CLIENT_GetUIState(UI_NPCSHOP)` (`JSUnit.cpp:1491`).
  - `D2CLIENT_GetCurrentInteractingNPC() != NULL`.
  - Sell: the item's `pOwnerInventory->pOwner` is the player. Buy: it is the NPC (`JSUnit.cpp:1512-1527`).
- **Threading & blocking:** allocates an `AutoCriticalRoom` right after the ready-wait and **before** the dialog, UI and ownership checks (`JSUnit.cpp:1470`). The script thread blocks on `Vars.cGameLoopSection` until the game thread yields in `GameDraw` / `TimerProc` (`D2Handlers.cpp:410-416,493-503`), and the game thread stays parked until the native returns. Every exit path deletes the room.
- **Side effects:** sell → `D2CLIENT_ShopAction(pNPC, pItem, 1, 0, 0, 1, 1, NULL)`; buy → `D2CLIENT_ShopAction(pNPC, pItem, 0, 0, 0, mode, 1, NULL)` (`JSUnit.cpp:1519,1527`; prototype `D2Ptrs.h:83-84`). The game builds and sends the packet. The commented-out D2BS packet builder (`JSUnit.cpp:1530-1565`) shows the old layout: 17 bytes, `0x32` buy / `0x33` sell, `[1..4]` NPC gid, `[5..8]` item gid, `[9..12]` a type DWORD (sell: 4 if the item is on the cursor else 0; buy: 0 if flag 0x10 else 2; mode 6: byte 12 = 0x80), `[13..16]` price from `D2COMMON_GetItemPrice`.
- **Game internals:** `D2CLIENT_ShopAction` (0x4B3870), `p_D2CLIENT_TransactionDialog*`, `D2CLIENT_GetUIVar_STUB`, `D2CLIENT_GetCurrentInteractingNPC`, `ItemData.pOwnerInventory` → `Inventory.pOwner`.
- **Quirks / bugs:** `pItemData->pOwnerInventory->pOwner` is dereferenced without NULL checks (`JSUnit.cpp:1514,1522`). The heap-allocated `AutoCriticalRoom` is used like a scope guard. The meaning of mode 6 is not named in the source (`doc/Unit.h:386-392`: "6 - ?").

### `Unit.prototype.setSkill(skill, hand[, item])`
Asks the server to put a skill on the player's left or right hand, then polls for up to about 1.1 s for the change, running the calling script's queued events in between. `this` is ignored.
- **Native:** `unit_setskill` at `JSUnit.cpp:1709`; helper `SetSkill` at `D2Helpers.cpp:238`; registered at `JSUnit.h:307` (declared arity 2, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `skill`: a string → `GetSkillByName` (`D2Helpers.cpp:291-296`, `_stricmp` against the English `Game_Skills` table in `D2Skills.h`; unknown names → `0xFFFF`), or an int → `(WORD)` id. Any other type → `false`.
  - `hand`: `JSVAL_IS_INT(argv[1])` is required (no argc check), and non-zero means **left** (`JSUnit.cpp:1730-1733`). Otherwise the result is `false`.
  - `item` (only when `argc == 3` and the argument is an object): if `JS_InstanceOf(cx, obj, &unit_class, argv)` and the private's `dwType == UNIT_ITEM`, its gid becomes `dwItemId`. Otherwise `0xFFFFFFFF` is used (`JSUnit.cpp:1735-1742`).
- **Returns:** `true` if the requested hand shows the skill id within the polling window. Otherwise `false`: argument problems, `ClientState() != InGame`, the player lacking the skill (`GetSkill(id)` returns 0, which happens when it is absent or its total level is 0, `D2Helpers.cpp:227-236,242-243`), a timeout, or leaving the game. `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait, then `ClientState` again).
- **Threading & blocking:** sends the packet, then loops while in game (`D2Helpers.cpp:259-285`). Each iteration compares `Me->pInfo->pLeftSkill` or `pRightSkill` `->pSkillInfo->wSkillId` with the target. A match returns TRUE. A failed check increments `timeout`, and the loop returns FALSE on the 12th failed check (`timeout > 10`), i.e. after 11 waits. Between checks it spends about 100 ms in `WaitForSingleObjectEx(script->eventSignal, amt, TRUE)` (alertable). It then pops and runs **this script's queued events** (FIFO: `FireEvent` pushes to the front, `Script.cpp:422`, and this loop pops from the back) with `ExecScriptEvent(evt, false)` (`ScriptEngine.cpp:452`) while the script is not aborted, so **JS listeners run re-entrantly inside `setSkill`**. The inner loop keeps waiting until 100 ms have passed since the iteration started, but event handlers run inside it, so a slow listener lengthens each step; "about 1.1 s" is the duration with quick or no listeners, not an upper bound. The first check happens right after the packet is sent, so if the hand already shows the skill the call returns `true` at once. **No lock** is held.
- **Side effects:** a 9-byte packet `[0]=0x3C, [1..2]=WORD skillId, [3]=0, [4]=0x80 if left else 0, [5..8]=DWORD itemGid or 0xFFFFFFFF`, sent with `D2CLIENT_SendGamePacket(9, p)`. That is the ASM stub `D2Helpers.cpp:955-965` (`EDI=len`, push packet) → `D2CLIENT_SendGamePacket_I` 0x478350. D2BS does not call `D2NET_SendPacket` here; whether `SendGamePacket_I` reaches it, and so the sent-packet hook, is an open question.
- **Game internals:** `D2CLIENT_SendGamePacket_I`, `D2COMMON_GetSkillLevel`, `UnitAny.pInfo` → `Info.{pFirstSkill,pLeftSkill,pRightSkill}`.
- **Quirks / bugs:**
  - `GetSkillByName` loops `i < 216`, but `Game_Skills` has 218 entries (`D2Skills.h:11-230`). "Shadow Master" (279) and "Phoenix Strike" (280) can therefore never be selected by name.
  - Passing a non-Unit object as `item` makes `JS_InstanceOf` report an incompatible-receiver error because argv is non-NULL (pending-error-but-true), and the call continues without an item.
  - Passing `Unit.prototype` (NULL private) as `item` dereferences NULL (`JSUnit.cpp:1738-1739`).
  - `pInfo` and the hand pointers are not NULL-checked inside the poll loop, and `GetSkill` dereferences `pInfo` and every `pSkill->pSkillInfo` without checks (`D2Helpers.cpp:231-232`). `GetSkill` returns the level of the **first** list entry with that id, so a charged copy that happens to come first decides the "has skill" test.
  - Legacy docs: `doc/Unit.h:394-420` says it "Waits up to one second" and has "\todo Fix argc < 1, should be argc < 2"; that todo is still open, since `argv[1]` is read with `argc == 1`.

### `Unit.prototype.overhead(message)`
Shows `message` as an overhead chat bubble above the receiver by attaching a game-allocated overhead message to the unit. Any unit.
- **Native:** `my_overhead` at `JSUnit.cpp:1750`; registered at `JSUnit.h:303` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `argv[0]` is read without an argc check. If it is neither `null` nor `undefined`, it goes through `JS_ValueToString` → `JS_GetStringCharsZ` → `UnicodeToAnsi(CP_ACP)` (`JSUnit.cpp:1765-1771`). An empty string adds no message.
- **Returns:** `true` whenever the receiver resolves, even if no message was added. Otherwise `false`. `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** `pMsg = D2COMMON_GenerateOverheadMsg(NULL, text, *p_D2CLIENT_OverheadTrigger)`. If `pMsg` is non-NULL, `pUnit->pOMsg = pMsg` (UnitAny+0xA4) (`JSUnit.cpp:1772-1776`). That is a direct write into game memory from the script thread. The previous `pOMsg` is overwritten, not freed.
- **Game internals:** `D2COMMON_GenerateOverheadMsg`, `p_D2CLIENT_OverheadTrigger`, `UnitAny.pOMsg`, `OverheadMsg` (`D2Structs.h:718-723`).
- **Quirks / bugs:** `overhead()` with no arguments reads argv beyond argc. The text is converted to the ANSI code page with `"?"` as the default character (`Helpers.cpp:24-29`; `CP_ACP` is 0), so characters outside it become `?`. `JS_ValueToString` runs outside a JS request and can invoke an object's `toString`. The commented-out `D2COMMON_FixOverheadMsg` call (`JSUnit.cpp:1774`) means messages are attached without that step.

### `Unit.prototype.revive()`
Sends the one-byte "revive" packet with no state checks. `this` is ignored.
- **Native:** `my_revive` at `JSUnit.cpp:1787`; registered at `JSUnit.h:304` (declared arity 0, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** rval is **unset** after sending, or `false` plus a warning when the game is not ready.
- **Preconditions:** in game (ready-wait). Whether the player is dead is not checked.
- **Threading & blocking:** **no lock**. It goes through the sent-packet hook (see interact).
- **Side effects:** `D2NET_SendPacket(1, 1, {0x41})` (`JSUnit.cpp:1791-1792`).
- **Game internals:** `D2NET_SendPacket`.
- **Quirks / bugs:** works from any receiver. `doc/Me.h:217-222` warns that sending it while alive can get you flagged.

---

## Methods: prices

### `Unit.prototype.getItemCost(mode[, npc[, difficulty]])`
Computes the buy, sell or repair price of this item at an NPC. Items only.
- **Native:** `item_getItemCost` at `JSUnit.cpp:1224`; registered at `JSUnit.h:309` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `mode`: `JSVAL_IS_INT` is required, otherwise rval is unset. 0 = buy, 1 = sell, 2 = repair. Other values → rval unset (`JSUnit.cpp:1277-1287`).
  - `npc` (if `argc > 1`): a Unit object, private-checked and resolved (if it does not resolve, rval is unset), or an int class id.
  - After that, `FillBaseStat("monstats", npcId, "inventory")`; if the lookup succeeds and the bit is 0, the NPC id falls back to `0x9A` (154) (`JSUnit.cpp:1269-1271`).
  - `difficulty` (if `argc > 2` and int): overrides `D2CLIENT_GetDifficulty()`.
  - Default NPC: the current interacting NPC's class, otherwise `0x9A` (`JSUnit.cpp:1229-1230`).
- **Returns:** int from `D2COMMON_GetItemPrice(player, item, difficulty, *p_D2CLIENT_ItemPriceList, npcId, mode)`, with mode 0 or 1 passed through and repair mapped to 3 (`JSUnit.cpp:1280,1283`). rval is unset on failures.
- **Preconditions:** in game (ready-wait). The unit must be an item.
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `D2COMMON_GetItemPrice`, `p_D2CLIENT_ItemPriceList` (VA 0x7C0D43), `D2CLIENT_GetDifficulty`, `D2CLIENT_GetCurrentInteractingNPC`, MPQ `monstats`.
- **Quirks / bugs:** the `monstats` validation only happens when `argc > 1` (whatever the type of argument 1, so `getItemCost(0, "x")` validates the default NPC), and an out-of-range id (lookup fails) is used unchanged. `GetCurrentInteractingNPC` and `GetDifficulty` are called before the argument checks. The NPC argument's private is read through the untyped `JS_GetPrivate`. Legacy docs: `doc/Unit.h:461-507` gives the default as 154; the code first uses the interacting NPC.

### `Unit.prototype.getRepairCost([npcClassId])`
Returns the player's total repair cost at an NPC class. `this` is ignored.
- **Native:** `me_getRepairCost` at `JSUnit.cpp:1968`; registered at `JSUnit.h:309` (declared arity 1, `JS_FS` + `FUNCTION_FLAGS`).
- **Arguments / overloads:** `npcClassId` must be an int to be used. The default is the interacting NPC's class, otherwise `0x9A` (`JSUnit.cpp:1972-1976`). There is no validation.
- **Returns:** int `D2COMMON_GetRepairCost(NULL, player, npcId, D2CLIENT_GetDifficulty(), *p_D2CLIENT_ItemPriceList, 0)` (`JSUnit.cpp:1978`). `false` plus a warning if the game is not ready.
- **Preconditions:** in game (ready-wait).
- **Threading & blocking:** **no lock**.
- **Side effects:** none.
- **Game internals:** `D2COMMON_GetRepairCost`, `p_D2CLIENT_ItemPriceList`, `D2CLIENT_GetDifficulty`.
- **Quirks / bugs:** always computed for the player. Legacy docs: `doc/Unit.h:452-459` says "repair this unit".

---

## Game internals referenced

VA = 0x400000 + RVA, because `GetDllOffset` ignores the DLL name and adds the offset to `GetModuleHandle(NULL)` (`Offset.cpp:21-28`). For signatures, status and Ghidra names see [../memory/offsets.md](../memory/offsets.md). Struct layouts are in [../memory/structs.md](../memory/structs.md), stubs in [../memory/call-stubs.md](../memory/call-stubs.md), and hooks in [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md).

| Identifier | Kind | VA | `D2Ptrs.h` | Used by |
|---|---|---|---|---|
| `D2CLIENT_FindServerSideUnit` / `FindClientSideUnit` | FUNCPTR | 0x4639B0 / 0x463990 | 68 / 67 | every receiver resolution |
| `D2CLIENT_GetPlayerUnit` | FUNCPTR | 0x463DD0 | 122 | interact, move, getStat(92), getMercHP, setSkill, prices |
| `p_D2CLIENT_ServerSideUnitHashTables` / `ClientSideUnitHashTables` | VARPTR | 0x7A5E70 / 0x7A5270 | 159 / 160 | getUnit, getNext |
| `D2CLIENT_GetCursorItem` | FUNCPTR | 0x4680A0 | 71 | getUnit(100), cancel |
| `D2CLIENT_GetSelectedUnit`, `p_D2CLIENT_SelectedInvItem` | FUNCPTR / VARPTR | 0x467A10 / 0x7BCBF4 | 70 / 203 | getUnit(101) |
| `D2CLIENT_GetUnitName_I` | ASMPTR | 0x464A60 | 247 | name filter (monsters) |
| `D2CLIENT_GetItemName`, `D2COMMON_GetItemText` | FUNCPTR | 0x48C060 / 0x6335F0 | 74 / 299 | name filter (items) |
| `D2COMMON_GetItemFromInventory` / `GetNextItemFromInventory` | FUNCPTR | 0x63B2C0 / 0x63DFA0 | 322 / 323 | getItem, getItems, item getNext |
| `D2COMMON_GetUnitStat`, `GetStatList`, `CopyStatList` | FUNCPTR | 0x625480 / 0x6257D0 / 0x625C90 | 306 / 304 / 305 | getStat |
| `D2COMMON_GetItemLevelRequirement` | FUNCPTR | 0x62BA60 | 315 | getStat(92) |
| `D2COMMON_GetUnitState` | FUNCPTR | 0x639DF0 | 307 | getState |
| `D2COMMON_GetSkillLevel`, `D2LANG_GetLocaleText` | FUNCPTR | 0x6442A0 / 0x524A30 | 313 / 418 | getSkill (both); setSkill (`GetSkillLevel` via `GetSkill`) |
| `D2CLIENT_GetMonsterOwner`, `D2COMMON_GetMissileOwnerUnit` | FUNCPTR | 0x479150 / 0x4639D0 | 76 / 344 | getParent, getMerc, getMercHP |
| `D2CLIENT_GetUnitHPPercent` | FUNCPTR | 0x479080 | 77 | getMercHP |
| `D2CLIENT_GetQuestInfo`, `D2COMMON_GetQuestFlag` | FUNCPTR | 0x4B32D0 / 0x65C310 | 62 / 331 | getQuest |
| `D2CLIENT_GetMinionCount_I` | ASMPTR | 0x478EE0 | 262 | getMinionCount |
| `D2COMMON_GetItemPrice`, `GetRepairCost`, `p_D2CLIENT_ItemPriceList` | FUNCPTR / VARPTR | 0x62FDC0 / 0x62FE60 / 0x7C0D43 | 317 / 319 / 191 | getItemCost, getRepairCost |
| `D2CLIENT_GetDifficulty`, `GetCurrentInteractingNPC` | FUNCPTR | 0x44DCD0 / 0x4B1620 | 112 / 69 | prices, shop, cancel |
| `D2CLIENT_ShopAction`, `p_D2CLIENT_TransactionDialog`, `…Dialogs`, `…Dialogs_2` | FUNCPTR / VARPTR | 0x4B3870 / 0x7C0D63 / 0x7C0E5C / 0x7C0E58 | 83 / 193-195 | shop |
| `D2CLIENT_GetUiVar_I` | FUNCPTR (via stub) | 0x4538D0 | 116, macro 493 | shop, interact |
| `D2NET_SendPacket` | FUNCPTR | 0x52AE50 | 362 | repair, interact, revive |
| `D2CLIENT_SendGamePacket_I` | ASMPTR | 0x478350 | 283 | setSkill |
| `p_D2CLIENT_RecentInteractId` | VARPTR | 0x7C0D25 | 189 | repair |
| `p_D2CLIENT_NPCMenu`, `NPCMenuAmount` | VARPTR | 0x726C48 / 0x725A74 | 168 / 169 | useMenu |
| `D2CLIENT_TakeWaypoint_I` | ASMPTR | 0x49D0F1 | 232 | interact(area) |
| `D2CLIENT_ClickMap`, `D2CLIENT_GetUnitX/Y`, `D2COMMON_MapToAbsScreen` | FUNCPTR | 0x462D00 / 0x45ADF0 / 0x45AE20 / 0x643260 | 95 / 80 / 81 / 333 | interact, move, cancel |
| `p_D2CLIENT_ViewportX/Y`, `MouseX/Y`, `AlwaysRun`, `AutomapOn` | VARPTR | 0x7A520C / 0x7A5208 / 0x7A6AB0 / 0x7A6AAC / 0x7A0660 / 0x7A27E8 | 162-163, 144-145, 219, 151 | interact, move, cancel |
| `D2CLIENT_CloseInteract`, `CloseNPCInteract`, `ClearScreen` | FUNCPTR | 0x44C6B0 / 0x4B3F10 / 0x4B4620 | 87 / 86 / 126 | cancel, interact |
| `D2COMMON_GenerateOverheadMsg`, `p_D2CLIENT_OverheadTrigger` | FUNCPTR / VARPTR | 0x661110 / 0x7BF20E | 325 / 187 | overhead |
| `D2CLIENT_SetSelectedUnit_I` | FUNCPTR (via stub `D2Helpers.cpp:728`) | 0x466DE0 | 73 | `ClickMap` wrapper (interact) |
| `D2CLIENT_CloseNPCTalk`, `p_STORM_WindowHandlers`, `D2GFX_GetHwnd` | FUNCPTR / VARPTR / FUNCPTR | 0x4A17D0 / 0x779300 / 0x4F59A0 | 128 / 473 / 382 | `IsScrollingText` (cancel) |
| `p_D2WIN_FirstControl` (with `D2CLIENT_GetPlayerUnit`) | VARPTR | 0x7D55BC | 462 | `ClientState()` / `WaitForGameReady()` (`D2Helpers.cpp:125-165`): every in-game check on this page |
| `p_D2COMMON_sgptDataTable` | VARPTR | 0x744304 | 349 | `FillBaseStat` (interact waypoint check, getSkill names, getItemCost NPC check) |
| Patch: `GetSelectedUnit_Intercept` call in ClickMap | PatchCall | 0x462D72 | `Patch.h:13` | interact |
| Patch: `GamePacketSent_Interception` in SendPacket | PatchJmp | 0x52AE5A | `Patch.h:12` | packets from repair, interact, revive |

---

## Legacy-doc discrepancies

| Topic | Legacy docs | Code |
|---|---|---|
| Mode bitmask | `doc/globalFuncs.h:13-14`, `doc/Unit.h:36-37`, `README.md:168`: "bit 29 set and bits 0-28" | bits 0-27 tested (`Unit.cpp:250`). Never works for items (`Unit.cpp:243`). |
| Mode bitmask | `resources/api.html:1210-1211`: "bit 30"; "scans the local rooms" | bit 29 (`Unit.cpp:247`); unit hash tables (`Unit.cpp:42-54`) |
| `getMercHP` | `doc/globalFuncs.h:122-128`: "health points" | percent (`JSUnit.cpp:1702`) |
| `getMerc(bool)` | `doc/Unit.h:134-143` | no arguments read (`JSUnit.cpp:1658-1687`) |
| `getPrice` | `doc/Unit.h:320-376`, `doc/Me.h:316-380` | not registered (`JSUnit.h:306`) |
| `getStat(-1)` | "first 64 stats" (`doc/Unit.h:301-310`) | up to 256 from the stat list plus extra `pStats` entries (`JSUnit.cpp:925-948`) |
| `getStat(-2)` | undocumented / TODO (`doc/Me.h:305`) | sparse table (`JSUnit.cpp:972-1095`) |
| `getSkill(4)` | "first 256 skills" (`doc/Unit.h:186-187`) | no limit (`JSUnit.cpp:1418`) |
| `setSkill` | "waits up to one second" | about 11 × 100 ms, running events (`D2Helpers.cpp:259-285`) |
| `interact` | inventory/stash item is "picked up" (`doc/Unit.h:83-88`) | packets 0x20 / 0x26 (belt); returns false (`JSUnit.cpp:837-851`) |
| `cancel` | cursor item is "dropped" (`doc/Unit.h:54-61`) | screen click at (10,10) (`JSUnit.cpp:756`); explicit `mode` argument undocumented |
| `useMenu` | "Index of the menu item" (`doc/Unit.h:77`) | entry id matched against `wEntryId1..4` (`D2Helpers.cpp:419-446`) |
| `repair` | receiver is the NPC (`doc/Unit.h:63-70`) | uses `RecentInteractId` (`JSUnit.cpp:785`) |
| `getRepairCost` | "repair this unit" (`doc/Unit.h:452-459`) | player's total; ignores `this` (`JSUnit.cpp:1978`) |
| `getEnchant` | returns bool | `true` or `0` (`JSUnit.cpp:1918-1922`) |
| `move` | `void` | rval unset (`JSUnit.cpp:1861-1898`) |
| `getItemCost` / `getRepairCost` default NPC | 154 | interacting NPC first, then 154 (0x9A) (`JSUnit.cpp:1229-1230,1972-1973`) |
| `getUnit()` defaults | `type = -1` default (`doc/globalFuncs.h:20,39`) | zero arguments → `undefined` (`JSUnit.cpp:575-576`) |
| `getUnit` name argument | "localizedName" (`resources/api.html:1210`) | item code for `type == 4`; internal `ObjectTxt.szName` for objects/tiles; localized only for monsters and (any-type search) items (`Unit.cpp:263-266`, `D2Helpers.cpp:59-93`) |
| `getItem(name, …)` | "name of the unit" (`doc/Unit.h:98-113`) | 3-character item code (`Unit.cpp:216,263-264`) |
| `getSkill(id, bTotal, chargedOnly)` | only `getSkill(nSkillId, nExt)` documented (`doc/Unit.h:191-197`) | 3-argument charged-skill form exists (`JSUnit.cpp:1380-1385,1449-1458`) |

---

## Open questions

- **Unset rval value:** does a native that returns `JS_TRUE` without `JS_SET_RVAL` evaluate to the callee function object (vp[0]) in this engine build, or to something else? `dependencies/include/js/CallArgs.h:133-145` calls the value unspecified. This needs a runtime check, e.g. `typeof me.move(0,0)`.
- **argv padding:** does this SpiderMonkey build pad a native's argv to its declared `nargs`? This affects `getNext` (reads `argv[1]` / `argv[2]`), `overhead()` (argv[0] with arity 0), `setSkill` (argv[1]) and `getState()` (argv[0]). `shop()` with no arguments reads `argv[-1]`, which is the `this` slot and always defined.
- Does `D2CLIENT_SendGamePacket_I` (0x478350, setSkill) reach `D2NET_SendPacket` and so the `gamepacketsent` hook? Does `D2CLIENT_ShopAction` send through it? If it does, `shop` would run `PacketEventCallback` while the script thread holds `Vars.cGameLoopSection`. `ReleaseGameLock` only releases on the game thread (`Events.cpp:347-349`), so a 500 ms wait could happen under the lock.
- Which values does `ItemData.ItemLocation` (+0x45, used by the `mode >= 100` filter) take, and how do they map to `GameLocation` (+0x68, the `location` property) and `NodePage` (+0x69)? Only the struct comments hint at it ("Body/Belt == 0xFF", `D2Structs.h:494`; NodePage "most reliable", `D2Structs.h:503`).
- Is `ItemData.pOwnerInventory` set for every item in an inventory, or only for socketed items as its comment says (`D2Structs.h:499`)? `getItem().getNext()`, `getParent()` on items and `shop` ownership checks all depend on it.
- Chain order inside a hash bucket (where the game inserts new units) determines `getNext` order inside a bucket. D2BS's source does not show it.
- The semantics of the 0x40 argument to `D2COMMON_GetStatList`. Is that list ever identical to `UnitAny.pStats`? If so, `getStat(-2)` duplicates skill-encoded entries.
- The meaning of `StatList.dwFlags` bit 31 (which gates `SetStatVec`), and of `D2CLIENT_GetUIState(UI_GAME)` (UI var 0) in the waypoint branch.
- Does the game free a unit's previous `pOMsg` when `overhead` replaces it?
- Shop mode 6: the source only shows a 0x80 flag byte in the dead packet code.
- `getUnit` without a string name passes the literal `""` to `JS_free`. *Partly resolved:* `JS_free` in `js_static.lib` calls the DLL CRT's `free` directly (`push p; call [__imp__free]`; [../OPEN_QUESTIONS.md](../OPEN_QUESTIONS.md#appendix-a-resolved-during-triage), R-08). Still open: whether MSVCR100's `free` fails silently or aborts with heap corruption on a non-heap pointer ([OQ-WIN-06](../OPEN_QUESTIONS.md#oq-win-06)).
- *Resolved* (R-09): `JS_GetPrivate` on an object whose class lacks `JSCLASS_HAS_PRIVATE` (a plain `{}` passed as `this` via `call`/`apply`, or as the `npc` argument of `getItemCost`) does no check. It returns the word just past the object's fixed slots (`[obj + 0x10 + 8 * nfixed]`, disassembly of `jsapi.obj`). The class-unchecked private reads are therefore type confusion with adjacent GC-heap memory: neither a reliable NULL nor a reliable crash.
- Are `D2CLIENT_GetCursorItem` / `D2CLIENT_GetSelectedUnit` safe to call out of game (`getUnit(100/101)` has no state check)?
- Is the 183 upper bound in `getState` right for 1.14d state counts?

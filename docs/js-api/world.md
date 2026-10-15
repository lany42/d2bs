# World: Room, Area, Exit, PresetUnit, Party and the `Map/` pathing subsystem

Scope: this page covers the map/world JS classes `Room` (`JSRoom.cpp/.h`, `Room.cpp/.h`), `Area` (`JSArea.cpp/.h`), `Exit` (`JSExits.cpp/.h`), `PresetUnit` (`JSPresetUnit.cpp/.h`) and `Party` (`JSParty.cpp/.h`), with every property and method. It also covers their global getters `getRoom`, `getArea`, `getPresetUnit`, `getPresetUnits` and `getParty` in every argument form. The second half documents the C++ map and pathing subsystem under `Map/` plus `MapHeader.h` and `Matrix.h`. That subsystem backs `getPath`, `getCollision` and `Area.exits`. It also documents the game data model the subsystem walks (`Level` → `Room2` → `Room1` → `CollMap`), room loading and unloading (`D2COMMON_AddRoomData` / `RemoveRoomData`), and locking and lifetime, which matter for thread safety. The JS entry points `getPath`, `getCollision`, `checkCollision`, `clickParty` and `revealLevel` are fully specified in [globals-game.md](globals-game.md). This page explains the machinery behind them. The source of truth is the C++. Legacy docs (`doc/Room.h`, `doc/Area.h`, `doc/Exit.h`, `doc/PresetUnit.h`, `doc/Party.h`, `doc/globalFuncs.h`, `resources/api.html`) were used only to cross-check, and every disagreement is listed. Offsets are RVAs in Game.exe 1.14d. See [../memory/README.md](../memory/README.md), [../memory/offsets.md](../memory/offsets.md) and [../memory/structs.md](../memory/structs.md).

## Contents

- [Conventions used on this page](#conventions-used-on-this-page)
- [World data model](#world-data-model)
  - [Struct graph and traversal](#struct-graph-and-traversal)
  - [Coordinate systems](#coordinate-systems)
  - [Level initialisation and `GetLevel`](#level-initialisation-and-getlevel)
  - [Room loading: `AddRoomData` / `RemoveRoomData`](#room-loading-addroomdata--removeroomdata)
  - [Locking summary](#locking-summary)
- [Room](#room)
- [Area](#area)
- [Exit](#exit)
- [PresetUnit](#presetunit)
- [Party](#party)
- [Map & pathing subsystem (Map/)](#map--pathing-subsystem-map)
  - [File inventory](#file-inventory)
  - [ActMap: construction, "cache", lifetime, lock](#actmap-construction-cache-lifetime-lock)
  - [Collision lookup (`ActMap::GetMapData`)](#collision-lookup-actmapgetmapdata)
  - [Neighbourhood predicates](#neighbourhood-predicates)
  - [Exit discovery (`ActMap::GetExits`)](#exit-discovery-actmapgetexits)
  - [A* (`AStarPath`)](#a-astarpath)
  - [Path reducers](#path-reducers)
  - [How the JS entry points use it](#how-the-js-entry-points-use-it)
  - [Dead or unused code](#dead-or-unused-code)
  - [Races and thread-safety summary](#races-and-thread-safety-summary)
- [Game internals referenced](#game-internals-referenced)
- [Legacy-doc discrepancies](#legacy-doc-discrepancies)
- [Open questions](#open-questions)

---

## Conventions used on this page

The shared terms are defined in [globals-game.md § Conventions](globals-game.md#conventions-and-shared-mechanics) and [unit-methods.md § Conventions](unit-methods.md#conventions-used-on-this-page). This page uses them by name.

| Term | Meaning here |
|---|---|
| **callee-return** | The native returns `JS_TRUE` without `JS_SET_RVAL`. `vp[0]` still holds the callee, so the call probably evaluates to the function object itself (truthy), not `undefined` (`dependencies/include/js/CallArgs.h:317-321`). Unverified at runtime. |
| **uncatchable abort** | A native or getter returns `JS_FALSE` with no pending exception. The running script is terminated silently, and `try/catch` cannot intercept it. |
| **Game-loop lock** | `AutoCriticalRoom` (`CriticalSections.h:31-55`) or `CriticalRoom` (`CriticalSections.h:5-29`) entering `Vars.cGameLoopSection`. The game thread holds that section and yields it only in `GameDraw` when `Vars.SectionCount > 0` (`D2Handlers.cpp:410-417`), in `TimerProc` (`D2Handlers.cpp:493-504`), and while it waits up to 500 ms for a script thread to handle a blocking packet event (`ReleaseGameLock`/`TakeGameLock` around `WaitForSingleObject`, `Events.cpp:312-314`, `:347-355`). Acquiring it waits for the next yield. While a script thread holds it, the game loop is frozen. `CRITICAL_SECTION` is recursive, so nested acquisition on one thread is safe. `Vars.cRoomSection` is initialised (`D2BS.cpp:110`) but never entered anywhere. |
| **lock leak** | An `AutoCriticalRoom` created with `new` and never `delete`d. The section stays owned by that script thread, and the game thread blocks forever at its next `EnterCriticalSection` (`D2Handlers.cpp:416`, `:503`). The game freezes. |
| **raw pointer private** | The JS object's private slot holds a pointer into game memory, which D2BS does not own. Nothing invalidates it when the game frees the object. |
| **snapshot private** | The private slot holds a heap struct copied from game memory at creation. It is freed by the class finalizer. |
| **Int tag test / argv over-read / private without class check / object test** | As defined in [globals-game.md](globals-game.md#conventions-and-shared-mechanics). Object test: D2BS overrides `JSVAL_IS_OBJECT` as `!JSVAL_IS_PRIMITIVE(v)` (`js32.cpp:62-64`), so `null` is **not** an object in any test on this page. |
| **dangling root** | `JS_AddRoot(cx, &local)` (`JS_AddObjectRoot`, `js32.h:96`) registers the *address* of a stack variable or heap field. An early return that skips the matching `JS_RemoveRoot` leaves the runtime's root table pointing at a dead stack slot (or freed heap), which every later GC reads. |

All natives are `JSNative(cx, argc, vp)` registered with `FUNCTION_FLAGS` = `JSFUN_STUB_GSOPS` (`js32.h:133-134`). They run synchronously on the calling script's thread ([../spidermonkey/embedding.md](../spidermonkey/embedding.md)). All properties on this page use `JSPROP_PERMANENT_VAR` = `READONLY|ENUMERATE|PERMANENT` (`js32.h:100`) with a getter and no setter, so they are read-only. Instances are made by `BuildObject(cx, classp, funcs, props, priv)` (`js32.cpp:8-28`), which defines the method and property specs as **own properties on each instance** and then sets the private. The same specs are also on `Class.prototype` through `JS_InitClass` (`ScriptEngine.cpp:230-233`, loop at `ScriptEngine.cpp:358-359`). `BuildObject` passes `proto = NULL` to `JS_NewObject` (`js32.cpp:11`). Whether instances therefore inherit from `Class.prototype` (so `instanceof` works) is engine behaviour, not verified (see [unit-properties.md](unit-properties.md)).

---

## World data model

### Struct graph and traversal

Struct layouts are in `D2Structs.h`. Offsets below were computed from the declarations. `RoomTile`…`Room2` sit inside `#pragma pack(1)` (`D2Structs.h:170-171`, `:330`). Full layouts and the comment discrepancies are in [../memory/structs.md](../memory/structs.md).

```
UnitAny(player) ─pAct(0x1C)──────────────► Act ─pMisc(0x48)─► ActMisc ─pLevelFirst(0x47C)─► Level ─pNextLevel(0x1AC)─► Level …
       └─pPath─► Path ─pRoom1(0x1C)─► Room1 (current room)          │  dwStaffTombLevel(0x94)        │
                                                                     └─pAct(0x46C)                    ├─pRoom2First(0x10)─► Room2 ─pRoom2Next(0x24)─► Room2 …
Act ─pRoom1(0x10)─► Room1 ─pRoomNext(0x7C)─► Room1 … (loaded rooms)                                   ├─pMisc(0x1B4)  dwLevelNo(0x1D0)
                                                                                                       └─dwPosX/Y(0x1C/0x20) dwSizeX/Y(0x24/0x28)  [tiles]
Room2: pRoom2Near(0x08)[dwRoomsNear(0x2C)] → Room2* (may belong to other levels)
       pRoom1(0x30)  → Room1 or NULL (not loaded)       pLevel(0x58) → Level
       pPreset(0x5C) → PresetUnit ─pPresetNext(0x0C)─► …  pRoomTiles(0x4C) → RoomTile{pRoom2(0x00) dest, pNext(0x04), nNum(0x10)*}
       pType2Info(0x20) → {dwRoomNumber, _, pdwSubNumber}   dwPresetType(0x48)   dwPosX/Y(0x34/0x38) dwSizeX/Y(0x3C/0x40) [tiles]
Room1: pRoom2(0x10) back-pointer, Coll(0x20) → CollMap, pUnitFirst(0x74) → UnitAny ─pRoomNext(0xE8)─► …
       dwXStart/dwYStart/dwXSize/dwYSize (0x4C..0x58)
CollMap: dwPosGameX/Y(0x00/0x04) dwSizeGameX/Y(0x08/0x0C) [subtiles], dwPosRoomX/Y, dwSizeRoomX/Y (0x10..0x1C), pMapStart(0x20) WORD[]
```

| Traversal | Code that does it |
|---|---|
| Levels of the **current act only**: `player->pAct->pMisc->pLevelFirst → pNextLevel` | `GetLevel` (`D2Helpers.cpp:178-191`). `ActMap::GetMapData` walks `act->pMisc->pLevelFirst` (`Map/Diablo_II/ActMap.cpp:108`) |
| All Room2 of a level: `pLevel->pRoom2First → pRoom2Next` (singly linked) | `Room.getNext` (`JSRoom.cpp:60`), `getRoom(x,y)` (`JSRoom.cpp:536`), `getPresetUnit(s)` (`JSPresetUnit.cpp:87`, `:166`), `revealLevel` (`JSGame.cpp:1480`), ActMap (`Map/Diablo_II/ActMap.cpp:124`, `:209`, `:270`) |
| Adjacent Room2: `pRoom2Near[0..dwRoomsNear)` | `Room.getNearby` (`JSRoom.cpp:310-311`), linkage-exit search (`Map/Diablo_II/ActMap.cpp:271-272`) |
| Preset list: `pRoom2->pPreset → pPresetNext` | `Room.getPresetUnits` (`JSRoom.cpp:102`), `getPresetUnit(s)` (`JSPresetUnit.cpp:95`, `:175`), `DrawPresets` (`Room.cpp:57`), ActMap (`Map/Diablo_II/ActMap.cpp:156`, `:250`) |
| Warp tile → destination level: `pRoom2->pRoomTiles` until `*nNum == preset.dwTxtFileNo`, then `pRoomTile->pRoom2->pLevel->dwLevelNo` | `GetTileLevelNo` (`D2Helpers.cpp:473-480`) |
| Loaded Room1 of the act: `pAct->pRoom1 → pRoomNext`, units via `pUnitFirst → pRoomNext` | `GetMercUnit` (`D2Helpers.cpp:483-484`). No class on this page walks it. |

Room2 objects hold layout data (position, size, presets, neighbours, warp tiles). D2BS treats `Room2.pRoom1 == NULL` as "not loaded" and loads the room with `D2COMMON_AddRoomData` before it reads `Room1` data (collision map, `dwXStart…`, units) (`Room.cpp:16-21`: "Check if we have Room1(Needed in order to reveal)").

### Coordinate systems

| Quantity | Unit | Evidence |
|---|---|---|
| `Level.dwPosX/dwPosY/dwSizeX/dwSizeY` | **tiles** (×5 = subtiles) | `Map/Diablo_II/ActMap.cpp:53-56`, `:148` |
| `Room2.dwPosX/dwPosY/dwSizeX/dwSizeY` | **tiles** | `Map/Diablo_II/ActMap.cpp:142`; `JSRoom.cpp:30-33` multiplies sizes by 5 |
| `CollMap.dwPosGameX/Y`, `dwSizeGameX/Y` | absolute **subtiles** ("world" / game coords) | compared with world points at `JSRoom.cpp:544`, `Map/Diablo_II/ActMap.cpp:178` |
| `PresetUnit.dwPosX/dwPosY` | subtiles **relative to the Room2 origin**: world = `room.dwPosX*5 + preset.dwPosX` | `Map/Diablo_II/ActMap.cpp:157`, `:255`; `Room.cpp:102-103` |
| `getPath` / `getCollision` arguments and results, `Exit.x/y` | absolute subtiles | `JSGame.cpp:257`, `:337`; `Map/Diablo_II/ActMap.cpp:255`, `:364` |
| ActMap "relative" points | `abs − (level.dwPosX*5, level.dwPosY*5)` (0 when `dwPosX == -1`) | `Map/Diablo_II/ActMap.cpp:64-65`, `:76-82` |
| Automap pixel (preset icons) | `xPixel = ((x − y)*16)/10 + 1`, `yPixel = ((x + y)*8)/10 − 3` with x, y absolute subtiles | `Room.cpp:102-105` |
| `Room1.dwXStart/…`, `CollMap.dwPosRoomX/…`, `RosterUnit.Xpos/Ypos` | not determinable from source (no arithmetic uses them) | — |

CollMap layout: one `WORD` per subtile, row-major, stride `dwSizeGameX`. The word for world `(x, y)` is `pMapStart[(y − dwPosGameY)*dwSizeGameX + (x − dwPosGameX)]` (`Map/Diablo_II/ActMap.cpp:178`). D2BS's names for the bits are in [§ Collision lookup](#collision-lookup-actmapgetmapdata).

### Level initialisation and `GetLevel`

`Level* GetLevel(DWORD dwLevelNo)` (`D2Helpers.cpp:172`) is used by `getRoom`, `getArea`, every `Area` property read, `getPresetUnit(s)`, `getPath` and `getCollision`:

1. `new AutoCriticalRoom` (`D2Helpers.cpp:173`) takes the **Game-loop lock**.
2. `if (!GameReady()) return nullptr;` (`D2Helpers.cpp:175-176`). The lock object is not deleted, so this path is a **lock leak** and freezes the game.
3. It walks `player->pAct->pMisc->pLevelFirst` (`D2Helpers.cpp:178`). For the matching `dwLevelNo`, if `pRoom2First == NULL` it calls `D2COMMON_InitLevel(pLevel)` (`D2Helpers.cpp:182-183`). It returns the level if `pRoom2First` is now set.
4. If `InitLevel` left `pRoom2First == NULL`, it `break`s and returns **that level anyway**, with no rooms (`D2Helpers.cpp:185-186`, `:195-196`). If no level matches it returns NULL.
5. `D2COMMON_GetLevel` is commented out: "this crashes pretty much every time it's called" (`D2Helpers.cpp:193-194`).

Consequences: only levels of the **player's current act** can be found. On success `GetLevel` releases its lock before returning (`D2Helpers.cpp:187-188`), so every caller uses the returned `Level*` after a window in which the game thread may run: `getPresetUnit(s)` re-lock only afterwards (`JSPresetUnit.cpp:79`, `:162`), and `getPath`/`getCollision`/`Area.exits` construct the ActMap (which re-locks) afterwards (`JSGame.cpp:250-255`, `:338-343`, `JSArea.cpp:25-38`). `getRoom` is the exception: it already holds its own lock around the nested call (`JSRoom.cpp:460`). `D2COMMON_InitLevel` is also called by `ActMap::ActMap` (`Map/Diablo_II/ActMap.cpp:58-59`) and `ActMap::GetMapData` (`Map/Diablo_II/ActMap.cpp:110-111`). D2BS never undoes `InitLevel`. The Room2 lists it creates are owned and freed by the game, and when the game frees them is not visible in the source.

### Room loading: `AddRoomData` / `RemoveRoomData`

`D2COMMON_AddRoomData(Act*, levelId, x, y, Room1*)` and `D2COMMON_RemoveRoomData(…)` (stdcall, RVAs `0x21A070`/`0x21A0C0`, `D2Ptrs.h:328-329`). `x, y` are the Room2 tile position. Every call site:

| Caller | Add condition | `Act*` / last arg | Paired remove |
|---|---|---|---|
| `Room.getPresetUnits` | `!pRoom2->pRoom1` (`JSRoom.cpp:95-98`) | `player->pAct` / `player->pPath->pRoom1` | before return (`JSRoom.cpp:128-129`); **not** on the `BuildObject` failure path (`JSRoom.cpp:114-118`) |
| `Room.getCollisionA` | `!pRoom1` (`JSRoom.cpp:148-151`) | same | yes (`:164-165`, `:189-191`, `:204-205`); **not** if `JS_NewUint16Array` fails (`:156-157`) |
| `Room.getCollision` | `!pRoom1` (`JSRoom.cpp:230-233`) | same | yes (`:240-241`, `:266-268`, `:282-284`, `:293-294`) |
| `Room.getStat` | `!pRoom1` (`JSRoom.cpp:345-348`) | same | yes (`:390-391`) |
| `getRoom(area,x,y)` / `getRoom(x,y)` | per scanned room `!pRoom->pRoom1` (`JSRoom.cpp:538-541`) | same | yes, per room (`:545-546`, `:557-558`) |
| `getPresetUnits` | per room **`!pRoom->pPreset`** (`JSPresetUnit.cpp:90-93`) | same | yes (`:123-126`); **not** on the `BuildObject` failure path (`:109-114`) |
| `getPresetUnit` | per room `!pRoom->pRoom1` (`JSPresetUnit.cpp:170-173`) | same | for non-matching rooms (`:201-204`); **not for the room that matches**, which returns at `:195-197` (or throws at `:190-194`) and leaves the room loaded |
| `RevealRoom` (`Room.reveal`, `revealLevel`) | `!(pRoom2->pLevel && pRoom2->pRoom1)` (`Room.cpp:18-21`) | `pRoom2->pLevel->pMisc->pAct` / `NULL` | yes (`Room.cpp:41-42`) |
| `ActMap::getCollFromRoom` | `!room->pRoom1` (`Map/Diablo_II/ActMap.cpp:173-176`) | inline helper `AddRoomData(room)`: `room->pLevel->pMisc->pAct` / `room->pRoom1` (NULL here) (`D2Helpers.h:77-79`) | **deferred**: queued in `RoomsAdded`, removed in `ActMap::CleanUp` (`Map/Diablo_II/ActMap.cpp:188-191`) with `RemoveRoomData(room)` passing the now non-NULL `room->pRoom1` (`D2Helpers.h:80-82`) |
| `ActMap::GetExits` | `!room->pRoom1` (`Map/Diablo_II/ActMap.cpp:210-213`) | helper | end of `GetExits` (`:222-224`). Rooms of *neighbouring* levels touched by the linkage search are loaded through `getCollFromRoom` and removed later by `CleanUp` |
| `ActMap::DumpLevel` (debug, no caller) | `!room->pRoom1` (`Map/Diablo_II/ActMap.cpp:658-661`) | helper | yes (`:673-675`) |

Observations:

- Every add happens under the **Game-loop lock**: the natives take `AutoCriticalRoom` first, and ActMap holds `actCrit` (see [ActMap](#actmap-construction-cache-lifetime-lock)).
- The last argument differs between call sites: the player's current `Room1`, `NULL`, or the room's own `pRoom1`. What the game does with it cannot be determined from the source.
- `getPresetUnits` keys on `pPreset` instead of `pRoom1`. For a room that is already loaded but has no presets, it calls Add and then Remove on a room the game had loaded itself. Whether the game reference-counts this cannot be determined from the source.
- The returned JS objects never keep a room loaded. `Room` objects hold the `Room2*` only.
- For RPC design: the tuple `(act, levelNo, room.dwPosX, room.dwPosY)` is what the game uses to identify a room in these two calls. It is a stable key, unlike the `Room2*` pointer.

### Locking summary

| Entry point | Lock | Game check |
|---|---|---|
| `Room` property getters, `Room.getNext/getNearby/getFirst/unitInRoom` | none | none |
| `Room.getPresetUnits/getCollision/getCollisionA/getStat/reveal` | `AutoCriticalRoom` taken **before** the validity check | `GameReady()` |
| `getRoom` | `AutoCriticalRoom` for the whole call (`JSRoom.cpp:460`) + nested in `GetLevel` | `WaitForGameReady` → throws |
| `Area` property getters | `GetLevel` (transient lock; **lock leak** if not `GameReady`). `exits` also holds the ActMap lock while it builds | inside `GetLevel` only |
| `getArea` | `GetLevel` (transient) | `WaitForGameReady` → throws |
| `Exit` / `PresetUnit` getters | none (snapshot) | none |
| `getPresetUnit(s)` | `GetLevel`, then `AutoCriticalRoom` for the room walk | `WaitForGameReady` → warning |
| `Party` getters, `getParty`, `Party.getNext` | **none** | `WaitForGameReady` (getter: none) |
| `getPath`, `getCollision` | `GetLevel` + ActMap `actCrit` from `GetMap` to `CleanUp` | `WaitForGameReady` → warning |

---

## Room

- **JSClass:** `"Room"`, `JSCLASS_HAS_PRIVATE`, no finalizer (`NULL`), constructor `room_ctor` (`JSGlobalClasses.cpp:68-70`). Registered by the `global_classes` entry `{&room_class, 0, room_ctor, 0, room_methods, room_props, NULL, NULL}` (`JSGlobalClasses.cpp:152`).
- **Constructor:** `EMPTY_CTOR(room)` (`JSRoom.cpp:7`; macro `js32.h:136-139`), so `new Room()` throws `"Invalid Operation"`. Instances come from `getRoom` (all forms), `Room.prototype.getNearby` (one object per neighbour) and `Room.prototype.getFirst`. `getNext` does not create objects; it rewrites the receiver.
- **Private data:** a **raw pointer private** to `Room2` (`D2Structs.h:305`). There is no ownership and no finalizer, and nothing is freed.
- **Identity & lifetime:** the object holds the game's `Room2*`, and every access dereferences it live. Nothing re-validates it. After an act change or leaving the game, any access is a potential use-after-free. When the game frees Room2 lists is not visible in source. `GameReady()` checks do not validate the pointer. A stale Room passed to `getPresetUnits`, `getCollision` and similar methods calls `AddRoomData` with the *current* player act and the stale level/position. There is no equality hook, so every getter call makes a new object, and two objects for the same room compare unequal with `==`. Compare `level`, `x` and `y` instead.
- **Units:** `x`/`y` are in **tiles** and `xsize`/`ysize` in **subtiles** (×5). The world bounds of a room are `[x*5, x*5 + xsize) × [y*5, y*5 + ysize)`.

### Room properties

Getter `room_getProperty` (`JSRoom.cpp:9`). If the private is NULL (e.g. `Room.prototype.x`) it returns `JS_TRUE` without touching `vp`, so the value is `undefined` (`JSRoom.cpp:12-13`). Every "`undefined`" in this table is such an untouched `vp`; whether it can instead repeat a previously read value is an [open question](#open-questions). No lock and no game check.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `number` | `ROOM_NUM` 0 | int | R | `-1` if `dwPresetType != 2`; else `pType2Info->dwRoomNumber` if `pType2Info`; else `undefined` | `Room2.dwPresetType` (0x48), `Room2.pType2Info->dwRoomNumber` (`JSRoom.cpp:17-22`) | meaning of the "room number" is not stated in source |
| `x` | `ROOM_XPOS` 1 | int | R | always | `Room2.dwPosX` (0x34), tiles (`JSRoom.cpp:23-25`) | not multiplied by 5 |
| `y` | `ROOM_YPOS` 2 | int | R | always | `Room2.dwPosY` (0x38), tiles (`JSRoom.cpp:26-28`) | |
| `xsize` | `ROOM_XSIZE` 3 | int | R | always | `Room2.dwSizeX * 5`, subtiles (`JSRoom.cpp:29-31`) | mixed units vs `x` |
| `ysize` | `ROOM_YSIZE` 4 | int | R | always | `Room2.dwSizeY * 5` (`JSRoom.cpp:32-34`) | |
| `subnumber` | `ROOM_SUBNUMBER` 5 | undefined | R | never set | no `case` (falls to `default`, `JSRoom.cpp:46-47`) | `pType2Info->pdwSubNumber` exists in the struct but is unused |
| `area` | `ROOM_AREA` 6 | int | R | `pLevel != NULL` | `Room2.pLevel->dwLevelNo` (`JSRoom.cpp:35-39`) | same as `level` |
| `level` | `ROOM_LEVEL` 7 | int | R | `pLevel != NULL` | `Room2.pLevel->dwLevelNo` | |
| `correcttomb` | `ROOM_CORRECTTOMB` 8 | int | R | `pLevel->pMisc->dwStaffTombLevel != 0`, else `undefined` | `ActMisc.dwStaffTombLevel` (0x94) (`JSRoom.cpp:41-44`) | per act (`ActMisc`), so every room of the act returns the same value. `JSGame.cpp:1351` compares it with the player area |

### `Room.prototype.getNext()`

Advances this Room object in place to the next `Room2` of the same level.

- **Native:** `room_getNext` at `JSRoom.cpp:53`; registered at `JSRoom.h:47` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `true` if `pRoom2Next` was non-NULL and the private was replaced with it (`JSRoom.cpp:67-69`). `false` at the end of the list (`JSRoom.cpp:62-66`); the private is **unchanged**, so the object still refers to the last room. `false` if the private is NULL (`JSRoom.cpp:55-58`).
- **Preconditions:** none checked.
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** mutates the receiver's private (`JS_SetPrivate`). Every JS reference to this object moves with it.
- **Game internals:** `Room2.pRoom2Next` (0x24).
- **Quirks / bugs:** the end-of-list branch calls `JS_ValueToObject(cx, JSVAL_NULL, &obj)` on a local, which has no effect (`JSRoom.cpp:65`). Iteration order is the game's list order.

### `Room.prototype.reveal([drawPresets])`

Reveals this room on the automap and optionally adds icons for special presets.

- **Native:** `room_reveal` at `JSRoom.cpp:436`; registered at `JSRoom.h:48` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `drawPresets` is honoured only when `argc == 1` and the value is a boolean (`JSVAL_IS_BOOLEAN`) (`JSRoom.cpp:439-441`). Otherwise it defaults to `false`.
- **Returns:** bool from `RevealRoom` (`JSRoom.cpp:449`). `true` if revealed. `false` if the room could not be loaded (`Room.cpp:22-25`). **callee-return** if the private is NULL or `!GameReady()` (`JSRoom.cpp:444-447`).
- **Preconditions:** in game (`GameReady()`, not waited). `RevealRoom` dereferences `player->pPath->pRoom1->pRoom2->pLevel` unconditionally first (`Room.cpp:9`).
- **Threading & blocking:** script thread. **Game-loop lock** (`JSRoom.cpp:443`), re-entered inside `RevealRoom` (`Room.cpp:14`). It waits for the next game yield even when the call then fails.
- **Side effects** (`RevealRoom`, `Room.cpp:5-49`):
  1. If the room has no `pRoom1`: `D2COMMON_AddRoomData(pRoom2->pLevel->pMisc->pAct, levelNo, dwPosX, dwPosY, NULL)` (`Room.cpp:18-21`).
  2. If the room's level differs from the player's (or any link of the player's `pPath->pRoom1->pRoom2->pLevel` chain is NULL, or the room's `dwLevelNo` is 0): `InitAutomapLayer(room level)` (`Room.cpp:28-32`). That is `D2COMMON_GetLayer(levelNo)` → `D2CLIENT_InitAutomapLayer(layer->nLayerNo)` (`D2Helpers.cpp:347-350`), with the `GetLayer` result not NULL-checked. D2BS then reads `*p_D2CLIENT_AutomapLayer` in steps 3-4, so it relies on the game call having switched the client's current layer; the game-side effect itself is not visible in source.
  3. `D2CLIENT_RevealAutomapRoom(pRoom1, TRUE, *p_D2CLIENT_AutomapLayer)` (`Room.cpp:35`).
  4. If `drawPresets`: `DrawPresets(pRoom2)` (`Room.cpp:37-38`, body `Room.cpp:54-110`). For each preset it chooses an automap cell, starting from `-1` (= none). Type 1 (NPC): txt 256 → cell 300 ("Izzy"), 745 → 745 ("Hephasto"); other NPCs get none. Type 2 (object), as a sequence of independent `if`s where a later match overwrites an earlier one: 580 in level 79 → 318; 371 → 301; 152 → 300; 460 → 1468; 402 in level 46 → 0; 267 outside levels 75/103 → 0; 376 in level 107 → 376; then txt > 574 → 0; if still `-1`, `D2COMMON_GetObjectText(txt)->nAutoMap` (`Room.cpp:65-96`). Other preset types get none. If `0 < cell < 1258` it calls `D2CLIENT_NewAutomapCell()`, sets `nCellNo`/`xPixel`/`yPixel` (formula in [Coordinate systems](#coordinate-systems)) and `D2CLIENT_AddAutomapCell(cell, &(*p_D2CLIENT_AutomapLayer)->pObjects)` (`Room.cpp:99-107`).
  5. `RemoveRoomData` if step 1 added the room; `InitAutomapLayer(player level)` if step 2 switched layers (`Room.cpp:41-45`).
  This is all client-side; no packet is sent.
- **Game internals:** `D2CLIENT_RevealAutomapRoom` (RVA `0x58F40`, `D2Ptrs.h:92`), `D2CLIENT_InitAutomapLayer_I` (RVA `0x58D40`, `D2Ptrs.h:93`, via `D2CLIENT_InitAutomapLayer_STUB` `D2Helpers.cpp:336`), `D2COMMON_GetLayer` (RVA `0x21E470`, `D2Ptrs.h:301`), `D2CLIENT_NewAutomapCell` (`0x57C30`, `D2Ptrs.h:90`), `D2CLIENT_AddAutomapCell` (`0x57B00`, `D2Ptrs.h:91`), `p_D2CLIENT_AutomapLayer` (`0x3A5164`, `D2Ptrs.h:154`), `D2COMMON_GetObjectText` (`0x240E90`, `D2Ptrs.h:298`), `AutomapCell` (`D2Structs.h:43`), `ObjectTxt.nAutoMap` (`D2Structs.h:581`).
- **Quirks / bugs:**
  - Every `reveal(true)` adds new automap cells and never de-duplicates them, so repeated calls stack duplicate icons.
  - The Lower Kurast chest icon is dead code: txt 580 first gets cell 318 (`Room.cpp:68-69`), but the later `txt > 574 → 0` test overwrites it (`Room.cpp:85-86`), so nothing is drawn for it.
  - `GetObjectText` is not NULL-checked (`Room.cpp:90-93`).
  - `ObjectTxt.nAutoMap` is commented `0x1BB`, but the declared fields before it end at `0x1B4 + 8 = 0x1BC` (`_5[8]` at `0x1B4`), so the `DWORD` is at `0x1BC` regardless of packing (`D2Structs.h:578-581`). If the game's record really has it at `0x1BB`, the default cell number is read 1 byte off. See [../memory/structs.md](../memory/structs.md).
  - If `pRoom2->pLevel` is NULL the add path dereferences it (`Room.cpp:18-19`).
  - The same `RevealRoom` backs the global `revealLevel` ([globals-game.md](globals-game.md#reveallevelpresets)).

### `Room.prototype.getPresetUnits([type[, classId]])`

Returns PresetUnit snapshots for this room's preset list, filtered by type and class id.

- **Native:** `room_getPresetUnits` at `JSRoom.cpp:75`; registered at `JSRoom.h:49` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `type` is used only if `argc > 0` and it passes the Int tag test. `classId` is used only if `argc > 1` and it passes the Int tag test (`JSRoom.cpp:81-84`). Other values are ignored and leave the filter at 0. A filter value of 0 means "any" (`JSRoom.cpp:103`), so type 0 and class id 0 cannot be selected specifically.
- **Returns:** Array of `PresetUnit` objects (possibly empty) (`JSRoom.cpp:131`). **callee-return** if the private is NULL or `!GameReady()` (`JSRoom.cpp:90-93`). `false` if `BuildObject` fails (`JSRoom.cpp:114-118`).
- **Preconditions:** in game (`GameReady()`, not waited).
- **Threading & blocking:** **Game-loop lock**, acquired before the validity check (`JSRoom.cpp:89`).
- **Side effects:** temporary `AddRoomData`/`RemoveRoomData` if `pRoom1` is NULL ([table](#room-loading-addroomdata--removeroomdata)).
- **Game internals:** `Room2.pPreset` (0x5C), `PresetUnit{dwTxtFileNo 0x04, dwPosX 0x08, pPresetNext 0x0C, dwType 0x14, dwPosY 0x18}` (`D2Structs.h:269-277`), `D2CLIENT_GetPlayerUnit` (`D2Ptrs.h:122`).
- **Quirks / bugs:**
  - `myPresetUnit.dwLevel` is **never assigned** (`JSRoom.cpp:104-111`). `new myPresetUnit` without `()` leaves it indeterminate, so `.level` on these objects returns garbage. `getPresetUnit(s)` set it correctly.
  - The `BuildObject` failure path (`JSRoom.cpp:114-118`) leaks the `myPresetUnit`, leaves a **dangling root** on the local `pReturnArray` (`JS_AddRoot` at `JSRoom.cpp:101`) and skips `RemoveRoomData`.
  - `pRoom2->pLevel` and the player's `pPath` are dereferenced without NULL checks on the add/remove path (`JSRoom.cpp:97`, `:129`).
  - The type is not class-checked; any receiver's private is read as a `Room2*`.

### `Room.prototype.getCollision()`

Returns this room's collision map as a 2-D array of 16-bit words.

- **Native:** `room_getCollision` at `JSRoom.cpp:213`; registered at `JSRoom.h:50` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `Array` of `dwSizeGameY` rows. Each row is an `Array` of `dwSizeGameX` ints. `result[row][col]` is the CollMap word for world point `(dwPosGameX + col, dwPosGameY + row)`, so the outer index is **y** (`JSRoom.cpp:246-291`). **callee-return** if the private is NULL, `!GameReady()` (`JSRoom.cpp:220-223`), there is no `Room1`/`CollMap` after the load attempt (`:238-244`), or a `JS_SetElement` failed (`:265-273`, `:281-289`).
- **Preconditions:** in game (`GameReady()`).
- **Threading & blocking:** **Game-loop lock** for the whole copy (`JSRoom.cpp:219`).
- **Side effects:** temporary `AddRoomData`/`RemoveRoomData`.
- **Game internals:** `Room2.pRoom1` (0x30), `Room1.Coll` (0x20), `CollMap` (`D2Structs.h:256-267`), `Level.dwPosX/dwPosY` (used only to compute loop bounds, `JSRoom.cpp:246-247`). Flag meanings: [Collision lookup](#collision-lookup-actmapgetmapdata).
- **Quirks / bugs:** if `JS_NewArrayObject` fails it returns at `JSRoom.cpp:227-228` (before any room is loaded) without deleting the lock (**lock leak**) and leaves a **dangling root** on the local `jsobjy` (`JSRoom.cpp:226`). The row arrays `jsobjx` are not rooted while further allocations run (`JSRoom.cpp:259`); they rely on the conservative stack scan ([embedding.md](../spidermonkey/embedding.md)). `pRoom2->pLevel` is dereferenced without a NULL check (`JSRoom.cpp:232`, `:246-247`). The values are raw CollMap words; unlike `getCollision(area,x,y)`, no avoid-layer OR is applied.

### `Room.prototype.getCollisionA()`

Like `getCollision()`, but returns a flat `Uint16Array`.

- **Native:** `room_getCollisionTypeArray` at `JSRoom.cpp:136`; registered at `JSRoom.h:51` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `Uint16Array` of length `(dwSizeX*5)*(dwSizeY*5)` (Room2 size, `JSRoom.cpp:153`). Element `row*dwSizeGameX + col` = CollMap word (`JSRoom.cpp:188`). **callee-return** on the same failure paths as `getCollision` (`JSRoom.cpp:143-146`, `:162-168`, `:188-196`).
- **Preconditions:** in game (`GameReady()`).
- **Threading & blocking:** **Game-loop lock** (`JSRoom.cpp:142`).
- **Side effects:** temporary `AddRoomData`/`RemoveRoomData`.
- **Game internals:** as `getCollision`; `JS_NewUint16Array` (`dependencies/include/jsfriendapi.h:938`).
- **Quirks / bugs:**
  - The length comes from the Room2 size but the indexing uses the CollMap size. If they differ, out-of-range writes go through `JS_SetElement` on a typed array, which is engine behaviour.
  - If the array allocation fails it returns at `JSRoom.cpp:156-157` with a **lock leak**, leaked room data and a **dangling root** on the local `jsobjy` (`JSRoom.cpp:154`).
  - It is undocumented in legacy docs.

### `Room.prototype.getNearby()`

Returns new Room objects for every entry of `pRoom2Near`.

- **Native:** `room_getNearby` at `JSRoom.cpp:303`; registered at `JSRoom.h:52` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** Array of `dwRoomsNear` Room objects, which may belong to **other levels** (`JSRoom.cpp:310-322`). **callee-return** on allocation or `JS_SetElement` failure.
- **Preconditions:** none.
- **Threading & blocking:** no lock; no game check.
- **Side effects:** none.
- **Game internals:** `Room2.pRoom2Near` (0x08), `Room2.dwRoomsNear` (0x2C).
- **Quirks / bugs:** the private is not NULL-checked (`JSRoom.cpp:304`, `:310`), so `Room.prototype.getNearby()` dereferences NULL and crashes the process. A NULL `pRoom2Near[i]` entry would yield a Room with no private, because `BuildObject` skips `JS_SetPrivate` for a NULL `priv` (`js32.cpp:22-23`).

### `Room.prototype.getStat(n)`

Returns one raw field of the Room2, Room1 or CollMap.

- **Native:** `room_getStat` at `JSRoom.cpp:329`; registered at `JSRoom.h:53` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `n` must pass the Int tag test, otherwise the call returns `null` (`JSRoom.cpp:332-334`).

  | n | Field | n | Field |
  |---|---|---|---|
  | 0 | `Room1.dwXStart` | 9 | `CollMap.dwPosGameX` |
  | 1 | `Room1.dwYStart` | 10 | `CollMap.dwPosGameY` |
  | 2 | `Room1.dwXSize` | 11 | `CollMap.dwSizeGameX` |
  | 3 | `Room1.dwYSize` | 12 | `CollMap.dwSizeGameY` |
  | 4 | `Room2.dwPosX` (tiles) | 13 | `CollMap.dwPosRoomX` |
  | 5 | `Room2.dwPosY` | 14 | **`CollMap.dwPosGameY`** (bug) |
  | 6 | `Room2.dwSizeX` (tiles, not ×5) | 15 | `CollMap.dwSizeRoomX` |
  | 7 | `Room2.dwSizeY` | 16 | `CollMap.dwSizeRoomY` |
  | 8, other | `null` | | |

  (`JSRoom.cpp:355-388`)
- **Returns:** int, or `null` for an invalid `n`, a NULL private, `!GameReady()`, or a room that could not be loaded (`JSRoom.cpp:341-353`).
- **Preconditions:** in game (`GameReady()`).
- **Threading & blocking:** **Game-loop lock** (`JSRoom.cpp:340`).
- **Side effects:** temporary `AddRoomData`/`RemoveRoomData`. A room is loaded even when `n` maps to a Room2 field.
- **Game internals:** `Room1` (`D2Structs.h:332`), `CollMap` (`D2Structs.h:256`).
- **Quirks / bugs:** `n == 14` returns `dwPosGameY` instead of `dwPosRoomY`, so `dwPosRoomY` is unreachable (`JSRoom.cpp:383-384`). `Room1.Coll` is not NULL-checked for 9-16. Source comment: "Don't know whether it works or not" (`JSRoom.cpp:328`).

### `Room.prototype.getFirst()`

Returns a new Room object for the first room of this room's level.

- **Native:** `room_getFirst` at `JSRoom.cpp:396`; registered at `JSRoom.h:54` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** a Room object (`Room2.pLevel->pRoom2First`). `undefined` if the private, `pLevel` or `pRoom2First` is NULL, or if `BuildObject` fails (`JSRoom.cpp:397-404`).
- **Preconditions:** none checked (no game check).
- **Threading & blocking:** script thread; no lock; non-blocking.
- **Side effects:** none.
- **Game internals:** `Room2.pLevel` (0x58), `Level.pRoom2First` (0x10).
- **Quirks / bugs:** none beyond the stale-pointer risk.

### `Room.prototype.unitInRoom(unit)`

Tests whether the game unit is currently in this room.

- **Native:** `room_unitInRoom` at `JSRoom.cpp:411`; registered at `JSRoom.h:55` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `unit` must be a non-null object whose private passes `(_dwPrivateType & PRIVATE_UNIT) == PRIVATE_UNIT` (Unit or item objects; there is no class check) (`JSRoom.cpp:413-419`).
- **Returns:** bool `D2COMMON_GetRoomFromUnit(pUnit)->pRoom2 == this Room2` (`JSRoom.cpp:426-431`). **callee-return** if the receiver's private is NULL, the argument is invalid, `D2CLIENT_FindUnit` fails, or the unit has no room.
- **Preconditions:** none checked (no game check).
- **Threading & blocking:** no lock.
- **Side effects:** none.
- **Game internals:** `D2CLIENT_FindUnit` (`D2Helpers.cpp:500`), `D2COMMON_GetRoomFromUnit` (RVA `0x220BB0`, `D2Ptrs.h:310`), `Room1.pRoom2` (0x10).
- **Quirks / bugs:** none further.

### `getRoom([area | x, y | area, x, y])`

Returns a Room for a level's first room, the player's current room, or the room containing a world point.

- **Native:** `my_getRoom` at `JSRoom.cpp:454`; registered at `JSGlobalFuncs.h:31` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads** (dispatch at `JSRoom.cpp:462`, `:500`, `:568`):

  | Call shape | Condition | Result |
  |---|---|---|
  | `getRoom(area)`, `area != 0` | `argc == 1` and the Int tag test passes | first Room2 of `GetLevel(area)` (`JSRoom.cpp:467-483`); `undefined` if the level is missing or has no rooms |
  | `getRoom(0)` | same, value 0 | the room the player is in: `D2COMMON_GetRoomFromUnit(player)->pRoom2` (`JSRoom.cpp:484-499`) |
  | `getRoom(x, y)` | `argc == 2` | scan of the **player's current level** for the room whose CollMap contains `(x, y)` (`JSRoom.cpp:510-512`, `:522-524`) |
  | `getRoom(area, x, y)` | `argc == 3` | same scan in `GetLevel(area)` (`JSRoom.cpp:508-509`, `:525-527`) |
  | anything else: `argc == 0`, `argc == 1` with a non-int (e.g. string or double), `argc ≥ 4` | — | first Room2 of the player's current level (`JSRoom.cpp:568-576`) |

  Integer arguments are coerced with `JS_ValueToECMAUint32` (`JSRoom.cpp:465`, `:506`, `:523-527`); the return value is ignored. On a failed conversion (e.g. a throwing `valueOf`), the level id stays uninitialised (`uint32 levelId;`, `JSRoom.cpp:504`), `x`/`y` stay 0, and the exception stays pending while the native continues. Negative areas become large uint32 values and are not found. The point test is `x ≥ dwPosGameX && y ≥ dwPosGameY && x < dwPosGameX+dwSizeGameX && y < dwPosGameY+dwSizeGameY` (`JSRoom.cpp:544`), in absolute subtiles. `x == 0` or `y == 0` returns `undefined` (`JSRoom.cpp:530-533`).
- **Returns:** a Room object, or `undefined` on the failure paths above (`JSRoom.cpp:455`). **If no room contains the point, the first room of the level is returned, not `undefined`** (`JSRoom.cpp:561-567`).
- **Preconditions:** in game. If `WaitForGameReady()` fails it throws `"Get Room Game not ready"`, a catchable Error (`JSRoom.cpp:457-458`). The area must be in the player's act (`GetLevel`).
- **Threading & blocking:** script thread. **Game-loop lock** for the entire call (`JSRoom.cpp:460`), plus the nested lock in `GetLevel`. `WaitForGameReady` may poll (10 ms steps) for up to `Vars.dwGameTimeout` ms, or forever when it is 0 (`D2Helpers.cpp:153-166`), before the lock is taken. `JS_ValueToECMAUint32` on an object argument runs its `valueOf` **while the lock is held**.
- **Side effects:** `D2COMMON_InitLevel` via `GetLevel`. For the point scan, per room: `AddRoomData` if not loaded, then `RemoveRoomData`.
- **Game internals:** `GetLevel` (`D2Helpers.cpp:172`), `D2COMMON_GetRoomFromUnit` (`D2Ptrs.h:310`), `CollMap` (`D2Structs.h:256`), `D2COMMON_AddRoomData`/`RemoveRoomData` (`D2Ptrs.h:328-329`).
- **Quirks / bugs:**
  - During the scan, `pRoom->pRoom1->Coll` is dereferenced without checking that `AddRoomData` produced a `Room1` or that `Coll` is non-NULL (`JSRoom.cpp:543`).
  - The fallback branch (`argc` 0, ≥ 4, or one non-int argument) dereferences `player->pPath->pRoom1->pRoom2->pLevel->pRoom2First` with no NULL checks (`JSRoom.cpp:569`). If `pRoom2First` is NULL it still returns a Room object, one with **no private** (`BuildObject` skips `JS_SetPrivate` for NULL, `js32.cpp:22-23`), whose properties read as `undefined`.
  - For `argc == 2`, argument 0 is also converted as a level id and discarded (`JSRoom.cpp:504-507`).
  - The 2-argument form never searches adjacent levels.
  - Legacy docs: api.html says "If area is 0, then the current area is assumed". In code, `getRoom(0)` returns the *current room* (which `doc/globalFuncs.h:305-314` does document: "or 0 to get the room the controlled unit is in"), and `getRoom(0, x, y)` calls `GetLevel(0)`; no level with `dwLevelNo == 0` is expected in the act list (not verifiable from source), which would give `undefined`. `doc/globalFuncs.h:316-340` says the point forms return "the room at the given point". The code falls back to the first room.

---

## Area

- **JSClass:** `"Area"`, `JSCLASS_HAS_PRIVATE`, finalizer `area_finalize`, constructor `area_ctor` (`JSGlobalClasses.cpp:104-106`). It is registered by `{&area_class, 0, area_ctor, 0, NULL, area_props, NULL, NULL}` (`JSGlobalClasses.cpp:147`) and has no methods.
- **Constructor:** `EMPTY_CTOR(area)` (`JSArea.cpp:7`), so `new Area()` throws `"Invalid Operation"`. Instances come only from `getArea`.
- **Private data:** `myArea {DWORD AreaId; DWORD Exits; JSObject* ExitArray;}` (`JSArea.h:26-30`). `Exits` is never used. `ExitArray` is the cached `exits` array. `area_finalize` deletes the struct (`JSArea.cpp:9-17`) and does not touch `ExitArray`.
- **Identity & lifetime:** the private holds the level **id**. Every property read calls `GetLevel(AreaId)` again (`JSArea.cpp:25`), so values are live. `exits` is computed once and then cached in the private. There is no equality hook.

### Area properties

Getter `area_getProperty` (`JSArea.cpp:19`). It runs `GetLevel` on **every** read, including `id`. That takes the **Game-loop lock**, may call `D2COMMON_InitLevel`, and waits for the next game yield.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `exits` | `AUNIT_EXITS` 0 | Array of `Exit` | R | level found | `ActMap::GetMap(pLevel)->GetExits()` then `CleanUp()` (`JSArea.cpp:32-68`) | built on first read and cached; see below |
| `name` | `AUNIT_NAME` 1 | string | R | `D2COMMON_GetLevelText(AreaId)` non-NULL, else `undefined` | `LevelTxt.szName` (0xF5, `char[40]`), `JS_InternString` (`JSArea.cpp:69-73`) | ANSI bytes |
| `x` | `AUNIT_X` 2 | int | R | level found | `Level.dwPosX` (0x1C), **tiles** (`JSArea.cpp:74-76`) | |
| `xsize` | `AUNIT_XSIZE` 3 | int | R | level found | `Level.dwSizeX` (0x24), tiles (`JSArea.cpp:80-82`) | |
| `y` | `AUNIT_Y` 4 | int | R | level found | `Level.dwPosY` (0x20), tiles (`JSArea.cpp:77-79`) | |
| `ysize` | `AUNIT_YSIZE` 5 | int | R | level found | `Level.dwSizeY` (0x28), tiles (`JSArea.cpp:83-85`) | |
| `id` | `AUNIT_ID` 6 | int | R | level found | `Level.dwLevelNo` (0x1D0) (`JSArea.cpp:86-88`) | |

Failure semantics:

- A NULL private (e.g. `Area.prototype.x`), or `GetLevel` returning NULL, makes the getter return `JS_FALSE` with no exception (`JSArea.cpp:22-27`). That is an **uncatchable abort** of the script. `GetLevel` returns NULL after an act change (the level is not in the current act) or when not `GameReady()`.
- If `GameReady()` is false (menu, loading, `ClientStateBusy`), `GetLevel` also **leaks the lock** (`D2Helpers.cpp:173-176`). Reading any property of a cached Area object during a loading screen or after leaving the game can freeze the game.

`exits` details:

- On the first read: `JS_NewArrayObject` + `JS_AddRoot(&pArea->ExitArray)` (`JSArea.cpp:35-36`). Then `ActMap::GetMap(pLevel)`, which deletes the previous global ActMap and takes `actCrit` (see [ActMap](#actmap-construction-cache-lifetime-lock)). Then `GetExits(exits)` and `map->CleanUp()`, which releases `actCrit` (`JSArea.cpp:38-42`). Then one `Exit` object per entry (`JSArea.cpp:44-61`).
- After building, the getter calls `JS_RemoveRoot(cx, &pArea->ExitArray)` on **every** read (`JSArea.cpp:64-65`). From then on the cached array is referenced only from the C++ heap struct, which the conservative stack scanner does not see ([embedding.md](../spidermonkey/embedding.md)). If the script drops every JS reference to it and a GC runs, the next `area.exits` returns a **dangling `JSObject*`**.
- If `BuildObject` fails for an exit it throws `"Failed to create exit object!"` (`JSArea.cpp:54-58`). The partly filled array stays cached and rooted (the `JS_RemoveRoot` at `:64-65` is skipped). Later reads return that partial array and unroot it. If the Area object is finalized while that root is still registered, `area_finalize` deletes the `myArea` holding the rooted field (`JSArea.cpp:15`), leaving a **dangling root** into freed heap.
- `ActMap::GetMap` runs even though `exits` is only a property read, so a first `area.exits` read (including one triggered by code that reads every property, e.g. `JSON.stringify(area)`) destroys any in-flight ActMap of another thread ([Races](#races-and-thread-safety-summary)).
- Exits are a snapshot of the first read. Order: tile exits in room order, then linkage exits in ascending target-level order ([Exit discovery](#exit-discovery-actmapgetexits)).

### `getArea([area])`

Returns an Area object for a level id, or for the player's current level.

- **Native:** `my_getArea` at `JSArea.cpp:94`; registered at `JSGlobalFuncs.h:33` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `argc == 0`, or `argc ≥ 2` (extra arguments are ignored): the current area from `GetPlayerArea()` (`JSArea.cpp:100`; `D2Helpers.cpp:168-170`).
  - `argc == 1`: the argument must pass the Int tag test, else it throws `"Invalid parameter passed to getArea!"`. It is converted with `JS_ValueToECMAInt32` (`JSArea.cpp:102-110`).
  - A negative id throws the same message (`JSArea.cpp:112-113`).
- **Returns:** an Area object. `false` if `GetLevel(id)` is NULL (`JSArea.cpp:117-120`): levels of other acts, unknown ids, and presumably id 0 (no level with `dwLevelNo == 0` is expected in the act list; not verifiable from source). If `BuildObject` fails it throws `"Failed to build area unit!"` (`JSArea.cpp:132-136`).
- **Preconditions:** in game. If `WaitForGameReady()` fails it throws `"Get Area: Game not ready"` (`JSArea.cpp:97-98`).
- **Threading & blocking:** `WaitForGameReady` polling; transient **Game-loop lock** in `GetLevel`.
- **Side effects:** `D2COMMON_InitLevel` via `GetLevel`.
- **Game internals:** `GetPlayerArea` (`player->pPath->pRoom1->pRoom2->pLevel->dwLevelNo`), `GetLevel`, `D2COMMON_GetLevelText` (RVA `0x21DB70`, `D2Ptrs.h:297`).
- **Quirks / bugs:**
  - The level is validated at creation only; later reads can hit the uncatchable abort or lock leak described above.
  - `if (!pArea)` after `new` is dead code (`JSArea.cpp:123-126`).
  - `GetPlayerArea()` is evaluated on every call, even when an id is passed, and dereferences `player->pPath->pRoom1->pRoom2->pLevel` without NULL checks (it only tests `ClientState()`, `D2Helpers.cpp:168-170`).
  - The `myArea.Exits` field is never read or written (`JSArea.h:28`).
  - Legacy docs: `doc/Area.h` describes `x`/`y` as the map's left/bottom coordinates without stating units. They are tiles; multiply by 5 for world coordinates.

---

## Exit

- **JSClass:** `"Exit"`, `JSCLASS_HAS_PRIVATE`, finalizer `exit_finalize`, constructor `exit_ctor` (`JSGlobalClasses.cpp:92-94`). It is registered by `{&exit_class, 0, exit_ctor, 0, NULL, exit_props, NULL, NULL}` (`JSGlobalClasses.cpp:150`) and has no methods.
- **Constructor:** `EMPTY_CTOR(exit)` (`JSExits.cpp:3`), so `new Exit()` throws `"Invalid Operation"`. Instances come only from the `exits` property getter of Area objects (`JSArea.cpp:45-53`).
- **Private data:** a **snapshot private** `myExit {x, y, id, type, tileid, level}` (`JSExits.h:22-29`), copied from `Mapping::Exit {Target, Position, Type, TileId}` (`Map/Diablo_II/ActMap.h:18-27`). `exit_finalize` deletes it (`JSExits.cpp:5-8`).
- **Identity & lifetime:** an immutable value object; safe after leaving the game. There is no equality hook.

### Exit properties

Getter `exit_getProperty` (`JSExits.cpp:10`). It sets `undefined` first and returns `undefined` if the private is NULL (`JSExits.cpp:13-16`).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `EXIT_X` 0 | int | R | always | `Exit.Position.first`, absolute subtiles | tile exit: room origin×5 + preset offset (`Map/Diablo_II/ActMap.cpp:255`). Linkage exit: midpoint of the chosen walkable edge run (`:364`) |
| `y` | `EXIT_Y` 1 | int | R | always | `Exit.Position.second` | |
| `target` | `EXIT_TARGET` 2 | int | R | always | `Exit.Target`, destination level id | tile exit: `GetTileLevelNo` (`D2Helpers.cpp:473`). Linkage exit: neighbour room's `pLevel->dwLevelNo` |
| `type` | `EXIT_TYPE` 3 | int | R | always | `Exit.Type`: `Linkage = 1` (walk across the level border), `Tile = 2` (warp/stairs preset) (`Map/Diablo_II/ActMap.h:16`) | |
| `tileid` | `EXIT_TILEID` 4 | int | R | always | `Exit.TileId` = preset `dwTxtFileNo` for tile exits, `0` for linkage exits | |
| `level` | `EXIT_LEVELID` 5 | int | R | always | the source Area's `AreaId` (`JSArea.cpp:51`) | |

---

## PresetUnit

- **JSClass:** `"PresetUnit"`, `JSCLASS_HAS_PRIVATE`, finalizer `presetunit_finalize`, constructor `presetunit_ctor` (`JSGlobalClasses.cpp:72-74`). It is registered by `{&presetunit_class, 0, presetunit_ctor, 0, NULL, presetunit_props, NULL, NULL}` (`JSGlobalClasses.cpp:146`) and has no methods.
- **Constructor:** `EMPTY_CTOR(presetunit)` (`JSPresetUnit.cpp:7`), so `new PresetUnit()` throws `"Invalid Operation"`. Instances come from `getPresetUnit`, `getPresetUnits` and `Room.prototype.getPresetUnits`.
- **Private data:** a **snapshot private** `myPresetUnit {dwType, dwRoomX, dwRoomY, dwPosX, dwPosY, dwId, dwLevel}` (`JSPresetUnit.h:34-42`). `presetunit_finalize` deletes it (`JSPresetUnit.cpp:9-16`).
- **Identity & lifetime:** an immutable copy, safe after the room or level is gone. There is no equality hook. The world position is `(roomx*5 + x, roomy*5 + y)`.

### PresetUnit properties

Getter `presetunit_getProperty` (`JSPresetUnit.cpp:18`). A NULL private gives `undefined` (`JSPresetUnit.cpp:21-22`).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `type` | `PUNIT_TYPE` 0 | int | R | always | `PresetUnit.dwType` (0x14) | unit type: 1 monster/NPC, 2 object, 5 tile, as used by `Room.cpp:59`, `:65` and `Map/Diablo_II/ActMap.cpp:251`; constants `Constants.h:361-366` |
| `roomx` | `PUNIT_ROOMX` 1 | int | R | always | `Room2.dwPosX` (tiles) | |
| `roomy` | `PUNIT_ROOMY` 2 | int | R | always | `Room2.dwPosY` (tiles) | |
| `x` | `PUNIT_X` 3 | int | R | always | `PresetUnit.dwPosX` (0x08), subtile offset in the room | |
| `y` | `PUNIT_Y` 4 | int | R | always | `PresetUnit.dwPosY` (0x18) | |
| `id` | `PUNIT_ID` 5 | int | R | always | `PresetUnit.dwTxtFileNo` (0x04), the class id (monstats / objects / tile number) | not a unique id |
| `level` | `PUINT_LEVEL` 6 | int | R | correct from `getPresetUnit(s)` (the requested `area`, `JSPresetUnit.cpp:106`, `:187`); **garbage** from `Room.getPresetUnits` (never assigned) | `myPresetUnit.dwLevel` | `case` has no `break` and falls into `default` (harmless) (`JSPresetUnit.cpp:45-48`) |

### `getPresetUnit(area[, type[, classId]])`

Returns the first PresetUnit in a level that matches type and class id.

- **Native:** `my_getPresetUnit` at `JSPresetUnit.cpp:136`; registered at `JSGlobalFuncs.h:32` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `argc < 1` returns `false` (`JSPresetUnit.cpp:140-143`).
  - `area` is converted with `JS_ValueToECMAUint32`; any type is accepted and the result is ignored (`JSPresetUnit.cpp:147`). If the conversion fails (e.g. a throwing `valueOf`), `levelId` stays uninitialised (`uint32 levelId;`, `:145`) and the exception stays pending while the native continues.
  - `type` (if `argc ≥ 2`) and `classId` (if `argc ≥ 3`) are read with an unchecked `JSVAL_TO_INT`, so non-int values give garbage bits (`JSPresetUnit.cpp:157-160`).
  - 0 means "any" (`JSPresetUnit.cpp:177`).
- **Returns:** a PresetUnit object for the first match in `pRoom2First → pRoom2Next` order, then preset-list order (`JSPresetUnit.cpp:166-198`). `false` if nothing matches (`JSPresetUnit.cpp:206`).
  - If `GetLevel(area)` is NULL it throws `"getPresetUnits failed, couldn't access the level!"` (plural message, `JSPresetUnit.cpp:151-152`).
  - If `BuildObject` fails it throws `"Failed to create presetunit object"` (`JSPresetUnit.cpp:190-194`).
- **Preconditions:** in game. If `WaitForGameReady()` fails: warning plus `false` (`JSPresetUnit.cpp:137-138`). The level must be in the current act.
- **Threading & blocking:** `GetLevel`, then the **Game-loop lock** for the room walk (`JSPresetUnit.cpp:162`).
- **Side effects:** `InitLevel` via `GetLevel`. `AddRoomData` for each room without `pRoom1`. **The room that contains the match is never removed** (`JSPresetUnit.cpp:195-197`), so it stays loaded. Non-matching rooms are removed (`:201-204`).
- **Game internals:** `Level.pRoom2First`, `Room2.pPreset`, `PresetUnit`, `D2COMMON_AddRoomData`/`RemoveRoomData`.
- **Quirks / bugs:** the room-data leak above. The `BuildObject` failure path also skips `RemoveRoomData`. It cannot search for class id 0 or type 0. The room walk dereferences `D2CLIENT_GetPlayerUnit()->pPath->pRoom1` for every Add/Remove without NULL checks (`JSPresetUnit.cpp:171`, `:202`).

### `getPresetUnits(area[, type[, classId]])`

Returns every PresetUnit in a level that matches type and class id.

- **Native:** `my_getPresetUnits` at `JSPresetUnit.cpp:53`; registered at `JSGlobalFuncs.h:33` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** identical to `getPresetUnit` (`JSPresetUnit.cpp:57-77`), including the uninitialised `levelId` on a failed conversion (`:62-64`).
- **Returns:** Array (possibly empty) of PresetUnit objects (`JSPresetUnit.cpp:128`).
  - `false` if `argc < 1`.
  - If `GetLevel` is NULL it throws `"getPresetUnits failed, couldn't access the level!"` (`JSPresetUnit.cpp:68-69`).
  - If `BuildObject` fails it throws `"Failed to build object?"` (`JSPresetUnit.cpp:109-114`). That path leaves a **dangling root** on the local `pReturnArray` (`JS_AddRoot` at `:86`) and skips the pending `RemoveRoomData`.
  - A level whose `InitLevel` failed (no rooms) gives an empty array.
- **Preconditions:** in game (`WaitForGameReady` → warning plus `false`, `JSPresetUnit.cpp:54-55`).
- **Threading & blocking:** **Game-loop lock** for the whole level walk (`JSPresetUnit.cpp:79`).
- **Side effects:** `InitLevel`. Per room, Add/Remove keyed on **`!pRoom->pPreset`** rather than `!pRoom1` (`JSPresetUnit.cpp:90-93`); see [Room loading](#room-loading-addroomdata--removeroomdata).
- **Game internals:** as `getPresetUnit`.
- **Quirks / bugs:** the `JS_SetElement` result is ignored (`JSPresetUnit.cpp:117`).
- **Legacy docs:** `doc/PresetUnit.h` calls `id` "The unique ID". In code it is the class id (`dwTxtFileNo`).

---

## Party

- **JSClass:** `"Party"`, `JSCLASS_HAS_PRIVATE`, no finalizer, constructor `party_ctor` (`JSGlobalClasses.cpp:76-78`). It is registered by `{&party_class, 0, party_ctor, 0, party_methods, party_props, NULL, NULL}` (`JSGlobalClasses.cpp:151`).
- **Constructor:** `EMPTY_CTOR(party)` (`JSParty.cpp:8`), so `new Party()` throws `"Invalid Operation"`. Instances come only from `getParty` (`JSParty.cpp:145`).
- **Private data:** a **raw pointer private** to the game's `RosterUnit` (`D2Structs.h:216-235`). It is never freed by D2BS.
- **Identity & lifetime:** properties read the roster entry live, so values update as the game updates the entry, but nothing re-validates the pointer. When a player leaves or the game ends, the entry is presumably freed by the game (not visible in source), and further reads, `getNext()` or `clickParty(obj, …)` are use-after-free. The stable key for the entry is `gid` (`dwUnitId`). There is no equality hook.
- **Roster traversal:** `*p_D2CLIENT_PlayerUnitList` (VARPTR, RVA `0x3BB5C0`, `D2Ptrs.h:205`) heads a singly linked list through `RosterUnit.pNext` (0x80). D2BS walks it in `getParty` (`JSParty.cpp:126`), `Party.getNext` (`JSParty.cpp:68`), `clickParty` (`JSGame.cpp:1092`) and the game-event packet handler that resolves player names (`D2NetHandlers.cpp:106`, game thread). These are the only uses of the list (`grep p_D2CLIENT_PlayerUnitList`). No lock is ever taken, so script threads read a list that the game owns and updates; when the game inserts or frees entries is not visible in source.
- **Party flags:** `partyid` is `wPartyId`. `0xFFFF` is treated as "not in a party" by `clickParty` (`JSGame.cpp:1108`, `:1112-1114`). The meanings of `partyflag` (`dwPartyFlags`) values are not defined anywhere in source.

### Party properties

Getter `party_getProperty` (`JSParty.cpp:10`). A NULL private gives `undefined`. There is no lock and no game check.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `PARTY_X` 1 | int | R | always | `RosterUnit.Xpos` (0x28) | units not stated in source |
| `y` | `PARTY_Y` 2 | int | R | always | `RosterUnit.Ypos` (0x2C) | |
| `area` | `PARTY_AREA` 0 | int | R | always | `RosterUnit.dwLevelId` (0x24) | |
| `gid` | `PARTY_GID` 3 | number | R | always | `RosterUnit.dwUnitId` (0x10) as double (`JSParty.cpp:32-34`) | only field kept unsigned |
| `life` | `PARTY_LIFE` 4 | int | R | always | `RosterUnit.dwPartyLife` (0x14) | scale not stated in source |
| `partyflag` | `PARTY_FLAG` 6 | int | R | always | `RosterUnit.dwPartyFlags` (0x30) | values undefined in source |
| `partyid` | `PARTY_ID` 7 | int | R | always | `RosterUnit.wPartyId` (0x22) | `0xFFFF` = none (see above) |
| `name` | `PARTY_NAME` 5 | string | R | always | `RosterUnit.szName` (0x00, `char[16]`) via `JS_NewStringCopyZ` (`JSParty.cpp:20-22`) | byte string; a new string per read |
| `classid` | `PARTY_CLASSID` 8 | int | R | always | `RosterUnit.dwClassId` (0x1C) | |
| `level` | `PARTY_LEVEL` 9 | int | R | always | `RosterUnit.wLevel` (0x20) | |

### `Party.prototype.getNext()`

Advances this Party object in place to the next roster entry.

- **Native:** `party_getNext` at `JSParty.cpp:57`; registered at `JSParty.h:27` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** **the same object** (`this`) after its private was set to `pNext` (`JSParty.cpp:70-72`). `false` at the end of the list, with the private unchanged (`JSParty.cpp:73-78`). `false` if the private is NULL (`JSParty.cpp:63-66`).
- **Preconditions:** in game. If `WaitForGameReady()` fails: warning plus `false` (`JSParty.cpp:58-59`).
- **Threading & blocking:** no lock.
- **Side effects:** mutates the receiver's private.
- **Game internals:** `RosterUnit.pNext` (0x80).
- **Quirks / bugs:** this returns the object where `Room.getNext` returns `true`. Legacy `doc/Party.h` declares `void getNext()`.

### `getParty([name | gid | unit])`

Returns a Party object for the first roster entry, or for the entry matching a name, unit id or Unit.

- **Native:** `my_getParty` at `JSParty.cpp:83`; registered at `JSGlobalFuncs.h:32` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads** (`argc == 1` only; with `argc != 1` the arguments are ignored and the first entry is returned, `JSParty.cpp:94`, `:145`):

  | Argument | Handling | Match |
  |---|---|---|
  | string | `JS_EncodeStringToUTF8` (`JSParty.cpp:99-100`) | `_stricmp(szName, name) == 0`, case-insensitive (`JSParty.cpp:132`) |
  | int (Int tag test) | `JS_ConvertArguments("u")` (`JSParty.cpp:103`); a conversion failure would throw `"Unable to get ID"` (`:104-105`), which cannot happen for an int-tagged value | `dwUnitId == id` (`JSParty.cpp:127`). `getParty(0)` leaves the id at 0, so it falls back to the empty-name match below |
  | object | private read as `myUnit*` with no class check (`JSParty.cpp:109`). NULL private → `undefined`. `D2CLIENT_FindUnit(dwUnitId, dwType)`; on failure it throws `"Unable to get Unit"` (`JSParty.cpp:114-116`) | the found unit's `dwUnitId` (any unit type) |
  | anything else (bool, `null`, `undefined`, double, e.g. a gid ≥ 2³¹ stored as a double) | no branch taken | only entries with an empty name (see bug) |

- **Returns:** a Party object. `undefined` if the roster list is empty (`JSParty.cpp:91-92`), nothing matches (`JSParty.cpp:141-142`), or `BuildObject` fails.
- **Preconditions:** in game. If `WaitForGameReady()` fails: warning plus `false` (`JSParty.cpp:84-85`).
- **Threading & blocking:** no lock.
- **Side effects:** none on the game.
- **Game internals:** `p_D2CLIENT_PlayerUnitList` (`D2Ptrs.h:205`), `RosterUnit` (`D2Structs.h:216`), `D2CLIENT_FindUnit` (`D2Helpers.cpp:500`).
- **Quirks / bugs:**
  - `nPlayerName` is initialised to the string literal `""` (`JSParty.cpp:96`), and `JS_free(cx, nPlayerName)` runs unconditionally after the scan (`JSParty.cpp:139`). For the int, object and "anything else" forms this **frees a pointer into the DLL's read-only data** through the CRT allocator. That is undefined behaviour: likely heap corruption or a crash. Only the string form frees a real allocation.
  - Because `nPlayerName` is never NULL, the guard `if (!nPlayerName && !nPlayerId)` is dead (`JSParty.cpp:121-122`). The non-string forms also match any roster entry whose name is empty.
  - The `THROW_ERROR` paths (`JSParty.cpp:105`, `:116`) and the early return for a NULL private (`JSParty.cpp:111-112`) skip the free, which is correct there.
  - The string form compares the UTF-8 encoding of the argument with the game's byte string `szName` via `_stricmp` (`JSParty.cpp:100`, `:132`), so non-ASCII names only match if the game also stores them as UTF-8 (not determinable from source).
- **Order:** which entry is first is not stated in source. `clickParty` treats the first entry as the local player (`mypUnit`, `JSGame.cpp:1085`, `:1108`).
- **Legacy docs:** api.html documents only `getParty()`. `doc/globalFuncs.h:356-386` documents all four forms without the crash.

### `clickParty` interplay

`clickParty(party, mode)` is fully specified in [globals-game.md](globals-game.md#clickpartyparty-mode). In relation to this class:

- It reads the Party object's private as a `RosterUnit*` with no class check. Its "still in the list" check itself dereferences the possibly stale `pUnit->dwUnitId` and only looks for a live entry with the same id. It then reads `wPartyId` from, and passes to the game, the original pointer, not the live list entry it matched (`JSGame.cpp:1084-1097`, `:1108-1136`).
- Mode 2 refuses if `pUnit->wPartyId != 0xFFFF` and it equals the first entry's `wPartyId`. Mode 3 refuses if the *passed* entry's `wPartyId == 0xFFFF`; otherwise it calls `D2CLIENT_LeaveParty()` whichever entry was passed (`JSGame.cpp:1108-1118`).
- A Party object obtained before a player left the game is unsafe to pass. Look it up again with `getParty(gid)` (which itself has the `JS_free` bug above) or `getParty(name)`.

---

## Map & pathing subsystem (Map/)

### File inventory

| File | Contents | Live? |
|---|---|---|
| `Map/Map.h` | `Mapping::Point = std::pair<int,int>`, `PointList = std::vector<Point>` (`:9-10`). Abstract `Map` (`:12-25`): `Dump`, `CleanUp`, `GetWidth`, `GetHeight`, `GetMapData`, `IsValidPoint`, `SpaceHasFlag`, `PathHasFlag`, `AllowCritSpace`. `Matrix<T>` (`:27-52`), a vector of vectors indexed `[x][y]` | yes (interface; `Matrix` is only a never-filled `ActMap` member) |
| `Map/Diablo_II/ActMap.h/.cpp` | the only concrete map: a **lazy view over game CollMaps**, plus exit discovery | yes |
| `Map/Path/Path.h` | `Estimator`/`Distance` function-pointer typedefs (`:14-15`), abstract `MapPath` (`:17-23`) | yes |
| `Map/Path/AStarPath.h` | heuristics, `checkFlag`, `Node`, `AStarPath<Allocator>` | yes |
| `Map/Path/Reduction/PathReducer.h` | abstract `PathReducer`: `Reduce`, `GetOpenNodes`, `Reject`, `GetPenalty`, `MutatePoint` (`:9-20`) | yes |
| `Map/Path/Reduction/WalkPathReducer.h`, `TeleportPathReducer.h`, `NoPathReducer.h`, `JSPathReducer.h` | `getPath` reduction types 0, 1, 2, 3 | yes (3 is broken) |
| `MapHeader.h` | includes `Map.h`, `ActMap.h`, `AStarPath.h`, then `NoPathReducer.h`, `JSPathReducer.h`, `WalkPathReducer.h`, `TeleportPathReducer.h`, plus `using namespace Mapping; Pathing; Reducing;` (`MapHeader.h:1-11`). The reducers depend on this order because they use `checkFlag`/`Euclidean`/`Slope` from `AStarPath.h` without including it (`NoPathReducer.h` also uses `ActMap` without including `ActMap.h`) | included by `JSArea.cpp:5`, `JSGame.cpp:13`, `D2Handlers.cpp:17` |
| `Map/Diablo_II/LevelMap.h/.cpp` | an older precomputed-grid map | **dead** (see below) |
| `Map/BlankMap.h` | trivial `Map` returning 0 | **unused** |
| `Map/Diablo_II/Points.h/.cpp` | empty files | — |
| `Matrix.h` (root) | `CMatrix<TYPE,ARG_TYPE>` (Abin), derived from `CSyncObj` when `USE_MULTI_THREAD` (`Matrix.h:12-35`) | **unused**: included nowhere and not listed in `D2BS.vcxproj` |
| `TimedAlloc.h` | allocator with stats, used by `getPath` only `#if defined(_TIME)` (`JSGame.cpp:279-283`) | `_TIME` is not defined in any `D2BS.vcxproj` configuration |

### ActMap: construction, "cache", lifetime, lock

`ActMap` (`Map/Diablo_II/ActMap.h:43`) does **not** build a grid. Despite the `Matrix<CollisionFlag> mapPoints` member (`Map/Diablo_II/ActMap.h:76`), and the declared but undefined `Build()`, `ShrinkMap()` and `SpaceIsThickenedWall()` (`Map/Diablo_II/ActMap.h:82`, `:88`, `:156`), every query reads the game's `CollMap` words directly ([Collision lookup](#collision-lookup-actmapgetmapdata)).

- **Factory `ActMap::GetMap(Level*)`** (`Map/Diablo_II/ActMap.cpp:14-31`): if `previousLevelNo != 0`, it calls `cache[0]->CleanUp()` and `delete cache[0]` (`:18-21`). Then it sets `previousLevelNo = level->dwLevelNo` and stores `new ActMap(level)` in `cache[0]`. The per-level reuse branch is commented out (`:16-17`, `:25-29`). In effect:
  - the "cache" is a **single global slot**, `static ActMapList cache` (`Map/Diablo_II/ActMap.cpp:11`), keyed 0;
  - **every** `getPath`, `getCollision` and first `Area.exits` read destroys the previous ActMap and builds a new one;
  - `previousLevelNo` serves only as a "slot occupied" flag.
- **Constructor** (`Map/Diablo_II/ActMap.cpp:41-66`, private):
  - creates a per-instance `CRITICAL_SECTION lock`;
  - `actCrit = new CriticalRoom; actCrit->EnterSection();` (`:44-45`) takes the **Game-loop lock** and **keeps holding it after the constructor returns**;
  - stores `level` and `act = level->pMisc->pAct`;
  - sets `height = dwSizeX*5`, `width = dwSizeY*5` (X extent is "height", Y extent is "width"; `Map/Diablo_II/ActMap.h:134` "If these are backwards, it's not me.");
  - sets `posX/posY = dwPosX*5/dwPosY*5`, or 0 when `-1` (`:64-65`);
  - calls `D2COMMON_InitLevel` if the level has no rooms (`:58-59`);
  - `assert(act != NULL)` (`:46`) reads the member before it is assigned; this matters only in debug builds, since release builds define `NDEBUG`.
- **`CleanUp()`** (`Map/Diablo_II/ActMap.cpp:188-196`):
  - calls `RemoveRoomData` for every room in `RoomsAdded`;
  - clears `RoomsAdded`, `levelCache`, `roomCache` and `avoidRoomPointSet`;
  - calls `actCrit->LeaveSection()`, which **releases the lock**. A second call is harmless because the flag is already false.
- **`AllowCritSpace()`** (`Map/Diablo_II/ActMap.cpp:197-202`): `CleanUp(); actCrit->LeaveSection(); Sleep(5); actCrit->EnterSection();`. A* uses it to let the game run for about 5 ms.
- **Destructor** (`:68-74`): deletes `lock` and `actCrit` (`~CriticalRoom` → `LeaveSection`, `CriticalSections.h:12-14`) and clears `PathingPointList`. It does not call `CleanUp`, so rooms still in `RoomsAdded` are not removed.
- **`ClearCache()`** (`:33-39`): deletes every cached map and resets `previousLevelNo`. Called only from `GameLeave` (`D2Handlers.cpp:521`), on the game thread, after `StopIngameScript` for every script (`D2Handlers.cpp:520`). `Script::Stop(true)` waits at most about 300 ms for the script to leave JS (`Script.cpp:270-277`).
- **Process-global working sets:** `avoidRoomPointSet`, `RoomsAdded`, `roomCache` and `levelCache` are declared `static` **in the header** (`Map/Diablo_II/ActMap.h:38-41`). Each translation unit that includes it gets a private copy. Only `ActMap.cpp`'s copies are used, because every accessor is defined there. So effectively there is one set per process, shared by all ActMap instances and all script threads. Only the Game-loop lock serialises access.
- **`GetMap` itself runs unlocked.** Callers reach it right after `GetLevel` has released its transient lock (`JSGame.cpp:250-255`, `:338-343`, `JSArea.cpp:25-38`), so the `CleanUp()`/`delete` of the previous map and the `new ActMap` happen without holding cGameLoopSection; only the new constructor's `EnterSection` waits for it.
- **Lock map:** the per-instance `lock` is entered only by `GetExits`, `Dump` and `DumpLevel` (`Map/Diablo_II/ActMap.cpp:205`, `:560`, `:627`). It excludes nothing between instances. `Dump`/`DumpLevel` return early on `fopen` failure without leaving it (`:563-564`, `:630-631`); they are debug code with no callers. Real exclusion comes from `actCrit` (cGameLoopSection).
- **Lifetime summary:**

  | Event | What happens |
  |---|---|
  | `getPath` / `getCollision` / first `Area.exits` | previous ActMap destroyed; new one created; **game frozen** until `CleanUp` (with 5 ms windows every 500 ms during A*) |
  | `CleanUp` | rooms the map loaded are unloaded; caches cleared; lock released. The object stays in `cache[0]` |
  | next `GetMap` (any thread) | `CleanUp` + `delete` of the old object |
  | `GameLeave` | `ClearCache` |

### Collision lookup (`ActMap::GetMapData`)

`int ActMap::GetMapData(const Point& p, bool abs = true)` (`Map/Diablo_II/ActMap.cpp:84-136`). Relative points are first converted to absolute (`:85-86`). Then:

1. **Room cache:** linear search of `roomCache`. The first Room2 whose tile rectangle×5 contains `p` (`isPointInRoom`, `:138-143`) answers via `getCollFromRoom` (`:89-91`).
2. **Level selection:**
   - this map's `level` if it contains `p` (`isPointInLevel`, `:145-149`);
   - else the last match in `levelCache` (`:97-102`);
   - else every level of `act->pMisc->pLevelFirst`. Each containing level gets `D2COMMON_InitLevel` if it has no rooms and is pushed to `levelCache`. The loop does not `break`; the last match wins (`:107-116`).
3. If `act`, `act->pMisc` or `act->pRoom1` is NULL: `Print("ÿc1ActMap Level Not Loaded")` and return `Avoid` (`:103-106`). This check runs after step 1, so cached rooms still answer.
4. Walk `currLevel->pRoom2First → pRoom2Next`. The first room containing `p` is pushed to `roomCache` and answers via `getCollFromRoom` (`:124-131`). If no room contains the point: `Avoid` (0xFFFF).

`getCollFromRoom(room, p)` (`:172-186`):

- if `room->pRoom1 == NULL`: `AddRoomData(room)` and push to `RoomsAdded`, held until `CleanUp`;
- `val = CollMap.pMapStart[(y − dwPosGameY)*dwSizeGameX + (x − dwPosGameX)]`. There is no check that the room loaded or that `Coll` is non-NULL;
- in levels **111, 112, 117 and 74**, it ORs `getAvoidLayerPoint`. That function builds, per room and cached in `avoidRoomPointSet`, the set of absolute points of presets with `dwTxtFileNo == 435` ("barricade tower", any preset type), and returns `Avoid` (0xFFFF) for exactly those single subtiles (`:151-170`, `:182-184`).

Consequence: a query can resolve to **any level of the current act**, not just the `area` passed to `getPath`/`getCollision`. Pathing crosses level borders inside an act. Points outside every level and room are `Avoid`, and so are unwalkable.

D2BS's names for the collision word bits (`ActMap::CollisionFlag`, `Map/Diablo_II/ActMap.h:45-66`): `None 0x0000`, `BlockWalk 0x0001`, `BlockLineOfSight 0x0002`, `Wall 0x0004`, `BlockPlayer 0x0008`, `AlternateTile 0x0010`, `Blank 0x0020`, `Missile 0x0040`, `Player 0x0080`, `NPCLocation 0x0100`, `Item 0x0200`, `Object 0x0400`, `ClosedDoor 0x0800`, `NPCCollision 0x1000`, `FriendlyNPC 0x2000`, `Unknown 0x4000`, `DeadBody 0x8000` ("also portal"), `Avoid 0xFFFF`, `Special 0xF000`. `ThickenedWall 0xFEFE` is commented out here and exists only in dead `LevelMap` (`Map/Diablo_II/LevelMap.h:56`). The game's own semantics for these bits are not in source.

### Neighbourhood predicates

All of these take absolute points by default and are built on `GetMapData` (`Map/Diablo_II/ActMap.cpp:464-556`):

| Function | Definition |
|---|---|
| `SpaceGetData(p)` | OR of `GetMapData` at `p` and its 4 orthogonal neighbours at distance 1 (plus shape) (`:478-485`) |
| `SpaceGetDataWide(p)` | OR at `p` and the 4 orthogonal points at distance **2**; diagonals commented out (`:496-510`) |
| `SpaceHasFlag(f, p)` | `(SpaceGetData-style OR & f) == f` (`:487-494`). For a single-bit `f` this means "some cell of the plus has the bit"; with `f = Avoid` it means the OR of the five words has all 16 bits set (bits may come from different cells) |
| `OneSpaceHasFlag(f, p)` | single-point test (`:470-476`) |
| `SpaceIsWalkable(p)` | not `SpaceHasFlag` of Avoid, BlockWalk, BlockPlayer, NPCCollision or Object; closed doors are deliberately allowed (`:520-527`). No live caller: only `PathIsWalkable` (`:542-548`) uses it, and that is called only from commented-out code (`Map/Path/Reduction/WalkPathReducer.h:52`, `:91`) |
| `SpaceIsWalkableForExit(p)` | not Avoid, BlockWalk or BlockPlayer (`:529-532`) |
| `SpaceHasLineOfSight`, `SpaceIsInvalid`, `PathIsWalkable`, `PathHasLineOfSight`, `PathHasFlag` | as named (`:512-556`); no JS caller |
| `IsValidPoint(p)` | inside this map's level rectangle (`:464-468`); used only by `GetEdgeCenterPoint` |
| `checkFlag(v)` (`Map/Path/AStarPath.h:45-48`) | `((BlockWalk \| BlockPlayer) & v) > 0`, i.e. mask `0x0009`. This is **the** rejection test of every built-in reducer. `Avoid` contains both bits |

### Exit discovery (`ActMap::GetExits`)

`GetExits(ExitArray&)` (`Map/Diablo_II/ActMap.cpp:203-227`) runs under the instance `lock` (and `actCrit`, held since construction):

1. For every Room2 of the level: `AddRoomData` if not loaded (removed at the end, `:222-224`), then, only if `room->pLevel->dwLevelNo` equals this map's level (`:215-216`), `FindRoomTileExits` (`:249-263`). For each preset with `dwType == 5` (UNIT_TILE), `GetTileLevelNo(room, dwTxtFileNo)` (`D2Helpers.cpp:473-480`) finds the warp's destination level through `pRoomTiles`. If it is non-zero and no exit already exists at that exact position, it pushes `Exit(room*5 + preset offset, destLevel, Tile, dwTxtFileNo)`.
2. `FindRoomLinkageExits` (`:265-401`). For every room of the level and every neighbour in `pRoom2Near` that belongs to a **different** level (`:273`), and only if no exit to that level was found yet (`:277-286`; at this point `exits` holds only tile exits, so a level reachable by a warp gets no linkage exit):
   - It computes the touching edge from the two subtile rectangles (`:294-323`). It skips corner-only contact, overlapping rooms, and edges shorter than 3 subtiles (`:325-336`).
   - It walks along the edge. A point counts if `EdgeIsWalkable` (`:438-462`) holds, i.e. `SpaceIsWalkableForExit` at edge−n, edge, edge+n and edge+2n, where n is the outward normal. That is 4 points; the comment claims six.
   - For every maximal walkable run it records `(GetEdgeCenterPoint(...), (run midpoint, run length))` in a `multimap` keyed by target level (`:353-369`). `GetEdgeCenterPoint` (`:403-420`) scans the whole edge line in both directions while inside this level's rectangle, and returns the midpoint between the outermost walkable-for-exit points.
   - Per target level, it keeps the run whose midpoint is closest (Euclidean, `GetDistance`, `D2Helpers.cpp:967`) to its edge-center point, and pushes `Exit(run midpoint, level, Linkage, 0)` (`:373-400`).
3. Output order: tile exits in room-list order, then linkage exits in ascending level id.

### A* (`AStarPath`)

`template <class Allocator = std::allocator<Node>> class AStarPath : public MapPath` (`Map/Path/AStarPath.h:73`). `getPath` uses `AStarPath<> path(map, reducer)` (`JSGame.cpp:282`) with the default `estimate = EstimateDistance` and `distance = DiagonalShortcut` (`Map/Path/AStarPath.h:158`).

| Item | Definition |
|---|---|
| Grid | 8-connected over absolute subtiles. The reducer's `GetOpenNodes` defines the neighbours |
| Step cost `g` | `parent.g + DiagonalShortcut(parent, p) + reducer->GetPenalty(p)` (`Map/Path/AStarPath.h:147-148`). `DiagonalShortcut` = octile distance ×10 (straight 10, diagonal 14) (`:19-23`) |
| Heuristic `h` | `EstimateDistance` = `DiagonalShortcut(p, end)` (`:50-52`), admissible for these costs |
| Open set | `std::priority_queue<Node*, vector, NodeComparer>`, a min-heap on `g + h` (`:67-71`, `:91`). Duplicates are allowed and pruned on pop through the closed set (`:110-111`) |
| Closed set | `std::set<Point>` (`:92`). Rejected neighbours are also inserted into it (`:139-142`) |
| Rejection | `if (point != end && reducer->Reject(point))` (`:139`). The **end point is never rejected**, so a path may end inside a blocked cell next to reachable space |
| Start/end fix-up | `GetPath`: if `Reject(start)`, then `MutatePoint(start)`; likewise for end (`:177-180`). The mutated start is not re-checked |
| Termination | the end is popped → success (`:113-116`); the open set is empty → no path; or an abort |
| Aborts (empty result) | `!GameReady()`, or the player's level differs from the level at search start (`startLvl`, `:95-96`, `:122-125`; both cases log "Pather lvl change while pathing"), or `Vars.bQuitting` (`:126-127`), or a `Node` allocation returns NULL (`:99-100`, `:145-146`) |
| Yield | every 500 ms of wall time, `map->AllowCritSpace()` (`:118-121`). This unloads rooms and clears caches, releases the game-loop lock for about 5 ms, and re-acquires it |
| Bounds | there is **no node, time or distance cap**. An unreachable target explores the whole connected walkable region of the act. Every allocated `Node` is kept in `nodes` until the end (`:149`, `:194-198`). The release loop passes `sizeof(*it)` (pointer size, 4) instead of 1 as the element count to `alloc.deallocate` (`:197`); whether that matters depends on the allocator implementation (it is wrong for any allocator that uses the count, e.g. for statistics) |
| Output | `ReverseList` (parent chain, start→end) (`:82-88`), then `reducer->Reduce(in, out)` (`:187-190`) |
| Other heuristics | `Manhattan`, `Chebyshev` (missing `abs`, so wrong for negative deltas), `Euclidean` (`int(sqrt(dx²+dy²)*10)`) and `Slope` (`int(dy/dx)`) are defined (`:15-43`). Only `Euclidean` and `Slope` are used, by the reducers |

Costs per expansion (walk reducer): 8 neighbours × (`Reject`: 5 `GetMapData` calls, plus `GetPenalty`: up to 10 more). Each `GetMapData` is a linear scan of `roomCache` (a `std::list`).

`startLvl` is read through `player->pPath->pRoom1->pRoom2->pLevel` without NULL checks (`Map/Path/AStarPath.h:95-96`). `getPath` has just passed `WaitForGameReady`, so the chain was valid a moment earlier.

### Path reducers

All reducers are constructed per `getPath` call and deleted after it (`JSGame.cpp:260-276`, `:319`). The `Distance` argument passed to Walk and Teleport is stored but never used.

| | Walk (type 0) `WalkPathReducer.h` | Teleport (type 1) `TeleportPathReducer.h` | None (type 2) `NoPathReducer.h` | JS (type 3) `JSPathReducer.h` |
|---|---|---|---|---|
| ctor | `range = radius*10` (`:71`) | `range = radius*10`; precomputes `distanceList` = offsets with `range−5 < Euclidean(o,0) < range`, a ring of radius just under `radius` subtiles (`:26-39`) | — | adds 3 roots via the ctor's `cx` parameter; the `cx`/`obj` members are never assigned (`:23-27`) |
| `GetOpenNodes` | 8 neighbours (`:199-218`) | see below (`:60-125`) | 8 neighbours (`:29-37`) | 8 neighbours (`:71-79`) |
| `Reject(p)` | `checkFlag(SpaceGetData(p))` (`:192-197`) | same, with `abs=true` hard-coded for ring candidates (`:79`, `:99`, `:127-132`) | same (`:23-28`) | JS `reject(x, y)` (`:65-70`) |
| `GetPenalty(p)` | `+50` if `checkFlag(SpaceGetDataWide(p))` (blocked 2 subtiles away); else `+60` if `SpaceGetData` has `Object`; else `+80` if it has `ClosedDoor`; else 0 (`:220-238`) | 0 (`:139-141`) | 0 (`:38-40`) | 0 (`:80-82`) |
| `MutatePoint(p)` | 5×5 scan, below (`:240-269`) | identical copy (`:182-211`) | if rejected: first non-rejected of `p + (i, j)`, i, j ∈ 0..2 (positive quadrant only) (`:41-57`) | JS `mutate(x, y)`; object result `[x, y]` read with unchecked `JSVAL_TO_INT` (`:83-93`) |
| `Reduce` | slope/spacing filter (`:106-136`) | greedy farthest-in-range (`:41-57`) | identity (`:19-21`) | JS `reduce(pt, i, pts)` per node (`:34-64`) |

**Walk `Reduce`** (`Map/Path/Reduction/WalkPathReducer.h:106-136`; the commented-out older versions at `:24-97` and `:137-189` are dead): input with fewer than 2 points is copied as-is. Otherwise it iterates `it` from `begin` while `*it != in.back()`:

- it computes `slope_next = Slope(prev, cur)` = `int(dy/dx)` of each single step: 0 (horizontal), ±1 (diagonal), or, for vertical steps (`dx == 0`), a double ±∞/NaN converted to int. That conversion is UB in C++; MSVC/x86 yields `INT_MIN`;
- it pushes the previous point whenever the step slope changes, or when `Euclidean(lastPushed, cur) ≥ range`;
- it always pushes `in.back()`.

The first iteration computes `Slope(p0, p0)` = NaN → `INT_MIN`. If the first real step is not vertical, the start point is therefore pushed **twice**. The slope test does not distinguish opposite directions with equal slope, which cannot occur in an A* path.

**Teleport `GetOpenNodes`** (`Map/Path/Reduction/TeleportPathReducer.h:60-125`):

1. If `Euclidean(end, center) < range − 20`, it returns only `end`, a direct jump (`:64-67`).
2. It initialises `bestPtSoFar = center` on first use (`:69-70`). If `Euclidean(bestPtSoFar, center) < 500` (50 subtiles):
   - it scans the ring `distanceList + center`, pushing every non-rejected candidate that improves on the best distance to `end` so far (`:76-86`);
   - if the overall best has `best.first != 0`, is not in `map->PathingPointList`, and is closer to `end` than `center`, it records it in `PathingPointList`, pushes it again (so it appears twice), sets `bestPtSoFar = best` if that is closer to `end` than the old `bestPtSoFar`, and returns (`:87-93`).
3. Otherwise it **also** pushes the 8 non-rejected neighbours and records them in `PathingPointList` (`:95-106`). The ring candidates already pushed in step 2 stay in `out`, so a fallback expansion yields both. `justExpand` is set and never read.

`bestPtSoFar` and `PathingPointList` persist for the whole search (one reducer and one ActMap per `getPath` call). Jump cost is `DiagonalShortcut(center, candidate)` with zero penalty, i.e. the same octile cost as walking that displacement, so the cost function does not favour jumps. The node savings come from `GetOpenNodes` offering only ring candidates whenever an improving one exists.

**Teleport `Reduce`** (`:41-57`): `out = [in[0]]`. Then it repeatedly advances while `Euclidean(*it, out.back()) < range`, steps back one, and pushes that point. The last input point is always emitted. A one-point path (`start == end`) comes out as `[p, p]`.

- With `radius ≤ 1` (`range ≤ 10`) no single grid step satisfies `< range`: a straight step is exactly 10 and a diagonal is 14. The loop then never advances and pushes `in[0]` forever. That is an **infinite loop with unbounded memory growth** while the game-loop lock is held.
- With `radius == 0` the first `it--` steps before `begin()` (UB).
- `radius ≥ 2` is safe, because ring and endpoint jumps are always `< range`.

**Walk/Teleport `MutatePoint`** (`Map/Path/Reduction/WalkPathReducer.h:240-269`):

- It reads a 7×7 neighbourhood with `GetMapData`, skipping the centre and the 4 corners.
- It scans `i = −2..2`, `j = −2..2`, skipping `(0,0)` and cells with `|i + j| == 1`. After every failed candidate it skips the next `j` (`else { j++; }`).
- It moves `p` to the first candidate whose plus-shaped 5-cell OR passes `!checkFlag`.

The result is the first hit in that irregular scan order, not the nearest walkable cell. If nothing qualifies, `p` is unchanged. The cells it never assigns (centre, corners) are never read.

**JS reducer (type 3):** callback semantics, re-entrancy and the fact that it is broken (the constructor never assigns the `cx`/`obj` members, `Map/Path/Reduction/JSPathReducer.h:16-27`) are documented in [globals-game.md](globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate).

### How the JS entry points use it

| JS entry | Uses | Flow |
|---|---|---|
| `getPath(area, x, y, dx, dy[, type[, radius[, …]]])` ([spec](globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate)) | `GetLevel` → `ActMap::GetMap` → reducer → `AStarPath<>::GetPath(start, end, list, abs=true)` → `CleanUp` ×2 (`JSGame.cpp:250-320`) | the `area` only seeds the ActMap; the path may cross into other levels of the act. Points are absolute subtiles. An invalid `type` throws **after** `GetMap` without `CleanUp`, so the lock stays held (`JSGame.cpp:255`, `:273-275`) |
| `getCollision(area, x, y)` ([spec](globals-game.md#getcollisionarea-x-y)) | `GetLevel` → `GetMap` → `GetMapData(point, true)` → `CleanUp` (`JSGame.cpp:338-352`) | single word including the avoid-layer OR; `0xFFFF` off-map |
| `Area.exits` | `GetMap` → `GetExits` → `CleanUp` (`JSArea.cpp:38-42`) | see [Area](#area) |
| `Room.getCollision[A]` | **not** ActMap; reads `Room1.Coll` directly | no avoid layer |
| `checkCollision(a, b, mask)` ([spec](globals-game.md#checkcollisionunita-unitb-mask)) | **not** Map/; `D2COMMON_CheckUnitCollision` (RVA `0x222AA0`, `D2Ptrs.h:309`) | game-side unit/unit test |
| `revealLevel([presets])` ([spec](globals-game.md#reveallevelpresets)) | **not** Map/; `RevealRoom` per Room2 | see `Room.reveal` |

### Dead or unused code

- **`LevelMap`** (`Map/Diablo_II/LevelMap.h/.cpp`): compiled (`D2BS.vcxproj:325`) but unreachable. `LevelMap::GetMap` is declared (`Map/Diablo_II/LevelMap.h:108`) but its definition is commented out (`Map/Diablo_II/LevelMap.cpp:10-17`). The constructor is private. The class does not override `Map::AllowCritSpace`, so it is abstract anyway. `Build()`'s body is commented out (`Map/Diablo_II/LevelMap.cpp:65-79`), and so is the `AddCollisionMap` call in `AddRoom` (`:99-100`). It is a precomputed-grid design: `AddCollisionMap` copies CollMap words into `mapPoints`, zeroing closed-door and player cells, NPC/dead-body/item cells unless they are also BlockWalk/Wall/Object, AlternateTile cells unless BlockWalk/Wall, and the cells of `Barrel`/`Door`/`door`/`Urn`/`LargeUrn` object units (`Map/Diablo_II/LevelMap.cpp:114-152`); `FillGaps` (`:191-200`), `ThickenWalls` with the `0xFEFE` marker (`:202-223`) and `DrillExits` (`:277-324`) follow. It redefines `Mapping::Exit`/`ExitType` and header-static caches (`Map/Diablo_II/LevelMap.h:14-35`), so it can never share a translation unit with `ActMap.h`.
- **`BlankMap`** (`Map/BlankMap.h:7`): does not implement `CleanUp`/`AllowCritSpace`, so it is abstract, and it is never referenced.
- **`Matrix.h` / `CMatrix`**: not included anywhere. `Map::Matrix<T>` is used only as the unused `mapPoints` members.
- **`ActMap::Dump`/`DumpLevel`**: no callers (the calls in `Map/Path/Reduction/WalkPathReducer.h:183-189` are commented out).

### Races and thread-safety summary

1. **Global single-slot ActMap.** Thread A is inside `getPath` and releases the lock in `AllowCritSpace` (`Sleep(5)`). Thread B, waiting in `GetLevel`'s `AutoCriticalRoom`, gets the lock in that window, and `GetLevel` releases it again before returning. B then calls `GetMap` **without holding the lock** (see [ActMap](#actmap-construction-cache-lifetime-lock)), so the following can happen at any later point, also after A has re-entered: `GetMap` calls `cache[0]->CleanUp()` and deletes A's map (`Map/Diablo_II/ActMap.cpp:18-21`). If A's `actCrit` is entered at that moment, B's `CleanUp()` calls `LeaveCriticalSection` from thread B on a section owned by A, which is UB and can let the game thread run while A is mid-search. Either way A continues the search (and its later `AllowCritSpace`/`CleanUp`) on freed memory, which is a use-after-free. The same applies to `getCollision` and a first `Area.exits` read on any thread.
2. **`GameLeave` vs in-flight `getPath`.** The game thread runs `ClearCache()` after waiting at most about 300 ms per script (`D2Handlers.cpp:520-521`, `Script.cpp:270-277`). A search blocked in `AllowCritSpace`'s re-enter resumes on a deleted map.
3. **Lock leaks freeze the game:**
   - `GetLevel` when `!GameReady()` (`D2Helpers.cpp:173-176`). The realistic trigger is an `Area` property read during loading or out of game;
   - `getPath` with an invalid reducer type (`JSGame.cpp:273-275`);
   - `Room.getCollision`/`getCollisionA` on allocation failure (`JSRoom.cpp:227-228`, `:156-157`);
   - Teleport `Reduce` with `radius ≤ 1` (an infinite loop that holds the lock).
4. **JS re-entrancy under the lock:** JS reducer callbacks (type 3), and `valueOf` on `getRoom` arguments, run while cGameLoopSection is held. A callback that waits for the game thread (e.g. `delay`, waiting on game state) deadlocks or stalls. A callback that calls `getPath`/`getCollision`/`area.exits` deletes the outer ActMap.
5. **Lock-free reads of game memory:** `Room` getters, `getNext`, `getNearby`, `getFirst` and `unitInRoom`, and all of `Party`, read game-owned structures while the game thread may be running. Party reads the roster list with no synchronisation at all, not even `WaitForGameReady` in its property getter.
6. **Stale raw pointers:** `Room` (`Room2*`) and `Party` (`RosterUnit*`) objects are never invalidated (no finalizer, no game-exit hook).
7. **Long freezes:** A* holds the game loop for 500 ms slices with no total cap. The game thread can run only in the 5 ms windows.
8. **Unlocked gap after `GetLevel`.** `GetLevel` releases its lock before returning the `Level*` (`D2Helpers.cpp:187-188`), and `getPresetUnit(s)`, `getPath`, `getCollision` and `Area` getters lock again only afterwards, so the game may change or free the level's Room2 list in between ([Level initialisation](#level-initialisation-and-getlevel)).

---

## Game internals referenced

| Identifier | Kind / RVA | Declared | Used by |
|---|---|---|---|
| `D2CLIENT_GetPlayerUnit` | FUNCPTR `0x63DD0` | `D2Ptrs.h:122` | everywhere (act, current room, `pRoom1` arg) |
| `D2CLIENT_FindServerSideUnit` / `FindClientSideUnit` | FUNCPTR `0x639B0` / `0x63990` | `D2Ptrs.h:68`, `:67` | `D2CLIENT_FindUnit` (`D2Helpers.cpp:500-505`) → `unitInRoom`, `getParty(unit)` |
| `D2COMMON_AddRoomData` / `RemoveRoomData` | FUNCPTR `0x21A070` / `0x21A0C0` (stdcall) | `D2Ptrs.h:328-329` | [table](#room-loading-addroomdata--removeroomdata) |
| `D2COMMON_InitLevel` | FUNCPTR `0x2424A0` | `D2Ptrs.h:290` | `GetLevel`, `ActMap` |
| `D2COMMON_GetLevel` | FUNCPTR `0x242AE0` | `D2Ptrs.h:302` | unused (commented out, `D2Helpers.cpp:194`) |
| `D2COMMON_GetRoomFromUnit` | FUNCPTR `0x220BB0` | `D2Ptrs.h:310` | `getRoom(0)`, `unitInRoom` |
| `D2COMMON_GetLevelText` | FUNCPTR `0x21DB70` | `D2Ptrs.h:297` | `Area.name`, `GetLevelName` (`D2Helpers.h:83-88`) |
| `D2COMMON_GetObjectText` | FUNCPTR `0x240E90` | `D2Ptrs.h:298` | `DrawPresets` |
| `D2COMMON_GetLayer` | FUNCPTR `0x21E470` | `D2Ptrs.h:301` | `InitAutomapLayer` |
| `D2CLIENT_InitAutomapLayer_I` | FUNCPTR `0x58D40` (via `_STUB`, `D2Helpers.cpp:336`; macro `D2Ptrs.h:495`) | `D2Ptrs.h:93` | `RevealRoom` |
| `D2CLIENT_RevealAutomapRoom` | FUNCPTR `0x58F40` | `D2Ptrs.h:92` | `RevealRoom` |
| `D2CLIENT_NewAutomapCell` / `AddAutomapCell` | FUNCPTR `0x57C30` / `0x57B00` | `D2Ptrs.h:90-91` | `DrawPresets` |
| `p_D2CLIENT_AutomapLayer` | VARPTR `0x3A5164` | `D2Ptrs.h:154` | `RevealRoom`, `DrawPresets` |
| `p_D2CLIENT_PlayerUnitList` | VARPTR `0x3BB5C0` | `D2Ptrs.h:205` | `getParty`, `clickParty` |
| `D2COMMON_CheckUnitCollision` | FUNCPTR `0x222AA0` | `D2Ptrs.h:309` | `checkCollision` |
| `p_D2WIN_FirstControl` | VARPTR `0x3D55BC` | `D2Ptrs.h:462` | `ClientState` (game-ready checks) |
| `D2CLIENT_GetUnitX/Y` | FUNCPTR `0x5ADF0` / `0x5AE20` | `D2Ptrs.h:80-81` | `ActMap::DumpLevel` (debug) |
| Structs | `Level` `D2Structs.h:279`, `Room2` `:305`, `Room1` `:332`, `ActMisc` `:350`, `Act` `:359`, `CollMap` `:256`, `PresetUnit` `:269`, `RoomTile` `:209`, `RosterUnit` `:216`, `LevelTxt` `:111`, `ObjectTxt` `:566`, `AutomapCell` `:43`, `AutomapLayer` `:96`, `AutomapLayer2` `:106` | | see [../memory/structs.md](../memory/structs.md) |

Comment and layout mismatches seen while computing offsets (details belong in structs.md):

- `CollMap.pMapEnd` is commented `0x22` but sits at `0x24` (`D2Structs.h:266`);
- `Level._5` is commented `0x1BC` but sits at `0x1B8`, while `dwLevelNo`'s `0x1D0` is correct (`D2Structs.h:291-292`);
- `ObjectTxt.nAutoMap` is commented `0x1BB` but the preceding fields end at `0x1BC`, so it sits at `0x1BC` with or without packing (`D2Structs.h:580-581`).

---

## Legacy-doc discrepancies

| Item | Legacy docs | Code |
|---|---|---|
| `Room.reveal` | `doc/Room.h:17`: `bool reveal()` | optional boolean `drawPresets` (`JSRoom.cpp:440-441`) |
| `Room.getCollisionA` | absent from `doc/Room.h`, `README.md`, api.html | exists (`JSRoom.h:51`) |
| `Room.getStat(14)` | `doc/Room.h:75`: "14 - posGameY (coll)" | returns `dwPosGameY` too; the doc copies the bug. `dwPosRoomY` is unreachable |
| `Room.getStat(8)` | not listed | returns `null` |
| `Room.x/y/xsize/ysize` | "x coordinate", "x size (width)" (`doc/Room.h:105-119`) | `x`/`y` in tiles, sizes ×5 in subtiles (mixed units) |
| `Room.subnumber` | "No implementation." | consistent: always `undefined` |
| `getRoom(0)` | api.html: "If area is 0, then the current area is assumed" (`doc/globalFuncs.h:309-310` correctly says "the room the controlled unit is in") | the player's current **room**; `getRoom(0, x, y)` → `GetLevel(0)` → presumably `undefined` |
| `getRoom(area, x, y)` / `(x, y)` | "The room at the given point" (`doc/globalFuncs.h:316-340`) | falls back to the level's first room when no room contains the point |
| `getRoom()` | "first room in the current area" | consistent (also for any non-int single argument) |
| `Party.getNext` | `void getNext()` (`doc/Party.h:57`) | returns the same object, or `false` |
| `getParty(id \| unit)` | documented as normal forms (`doc/globalFuncs.h:376-386`) | frees a string literal (UB) |
| `getParty` forms | api.html: no arguments only | 4 forms |
| `PresetUnit.id` | "The unique ID of the PresetUnit" (`doc/PresetUnit.h:29-31`) | class id (`dwTxtFileNo`) |
| `PresetUnit.level` | "The Area ID of the Area the PresetUnit is in" | garbage for `Room.getPresetUnits` results |
| `PresetUnit.roomx/roomy/x/y` | "(?)" | room tile origin + subtile offset; world = `roomx*5 + x` |
| `Exit.type` | "1 - A walk through Exit, 2 - A stairs type Exit" | consistent (`Linkage = 1`, `Tile = 2`) |
| `Area.x/y` | "x coordinate of the left side of the map" | tile units (×5 for world) |
| `getPath` | api.html: `int area or int[] areas … bool useTeleportPathing … bool useReduction` | see [globals-game.md](globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) |

---

## Open questions

- Which roster entry `*p_D2CLIENT_PlayerUnitList` points to first (the local player?), and when the game frees `RosterUnit` entries. `clickParty` assumes the first entry is the local player (`JSGame.cpp:1085`, `:1108`).
- Meanings and scales of `RosterUnit.dwPartyFlags`, `dwPartyLife`, `Xpos`/`Ypos`, and `Room2.pType2Info->dwRoomNumber`.
- What the last argument of `D2COMMON_AddRoomData`/`RemoveRoomData` means. D2BS passes the player's `Room1`, `NULL`, or the room's own `pRoom1` at different sites. Whether the game reference-counts room loading: `getPresetUnits` can Add/Remove an already-loaded room, and `getPresetUnit` leaves a matching room loaded.
- When the game frees `Level`/`Room2` lists (act change? game exit?), i.e. the exact validity window of `Room` objects.
- Whether `D2COMMON_InitLevel` can fail for valid levels, which is the case that makes `GetLevel` return a level with no rooms.
- Whether `JS_NewObject` with `proto = NULL` (`js32.cpp:11`) gives these instances `Class.prototype`, which decides whether `instanceof Room` etc. work. This is engine behaviour.
- What a getter that leaves `vp` untouched returns (Room `number`/`subnumber`/`correcttomb`, Area `name`, any getter with a NULL private). This page writes `undefined`. But every property here is defined without `JSPROP_SHARED` (`JSPROP_PERMANENT_VAR`, `js32.h:100`), so each has a value slot (`dependencies/include/jsapi.h:1419`). If the engine seeds `vp` with the slot's current value and stores the getter's result back, an untouched `vp` returns the **last value read** for that property on that object. That matters for objects whose private changes underneath (`Room.getNext`, `Party.getNext`), e.g. `room.number` on a type-2 room without `pType2Info` would repeat the previous room's number. Engine behaviour, not visible in the repo.
- The units of `Room1.dwXStart/dwYStart/dwXSize/dwYSize` and `CollMap.dwPosRoomX/…` (`getStat` 0-3, 13-16).
- Whether the game's `objects.txt` record really has `nAutoMap` at `0x1BB`, in which case D2BS reads the wrong offset at `0x1BC`.
- How the game's own pathing interprets the collision bits D2BS names in `ActMap::CollisionFlag`, and whether the `checkFlag` mask (`BlockWalk|BlockPlayer`) is sufficient for 1.14d.

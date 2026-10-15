# Game structures (`D2Structs.h`) with computed MSVC x86 layouts

Scope: every `struct`/`union` in `D2Structs.h`, plus the Win32 types that `D2Ptrs.h` prototypes use and that are defined outside the repo (`POINT`, `RECT`, `CRITICAL_SECTION`, `HWND`, ...). Offsets are not taken from the source comments: they are computed by compiling the unmodified header with clang in MSVC x86 mode, and cross-checked by an independent Python MSVC layout engine. Where a source comment claims a different offset the row is marked **DISCREPANCY**. Those are either stale comments or real bugs in what D2BS reads. The same layouts are used by the Ghidra header [`docs/ghidra/d2bs_types.h`](../ghidra/d2bs_types.h) (generator: [`docs/ghidra/tools/gen_types.py`](../ghidra/tools/gen_types.py)). Addresses of globals and functions are in [offsets.md](offsets.md), hooks in [patches-and-hooks.md](patches-and-hooks.md), asm stubs in [call-stubs.md](call-stubs.md), and the overview in [README.md](README.md).

This file is generated: `python3 docs/ghidra/tools/gen_types.py --repo . --structs-md docs/memory/structs.md` (add `--ghidra-install DIR` or `--ghidra-cp CLASSPATH`, plus `--ghidra-label TEXT`, to include step 5 of [How this was verified](#how-this-was-verified); without them that step is left out).

## Contents

- [Reading the tables](#reading-the-tables)
- [Discrepancy summary](#discrepancy-summary)
- [Packing](#packing)
- [Relationships](#relationships)
- [Units & paths](#units--paths)
- [Items & inventory](#items--inventory)
- [Rooms, levels, acts & collision](#rooms-levels-acts--collision)
- [Skills & stats](#skills--stats)
- [UI, controls, automap & graphics](#ui-controls-automap--graphics)
- [Net & game info](#net--game-info)
- [Misc (Warden, data tables, D2BS-side)](#misc-warden-data-tables-d2bs-side)
- [Win32 types referenced by D2Ptrs.h](#win32-types-referenced-by-d2ptrsh)
- [Partially known structs](#partially-known-structs)
- [Cross-check against MPQStats.h](#cross-check-against-mpqstatsh)
- [How this was verified](#how-this-was-verified)
- [Open questions](#open-questions)

## Reading the tables

- **Offset**: computed byte offset from the start of the struct, hex. For members of an anonymous union/struct the offset is still from the start of the outer struct, as in the source comments. Rows prefixed with `↳` are nested inside the anonymous member above them.
- **Size**: computed size in bytes (hex). Bit-fields show the storage unit size and their bit range in Notes.
- **Type / Field**: as written in `D2Structs.h` (line in Notes).
- **Source comment**: the trailing `//` comment on the declaration line, verbatim.
- **Notes**: `DISCREPANCY` when the comment's leading offset disagrees with the computed offset; `unknown` for placeholder names (`_1`, `_2a`, `unk...`), which mark partially reverse-engineered regions; `C:` gives the member path in `d2bs_types.h` when it differs from the C++ name.
- `(padding)` rows are bytes that the compiler inserts for alignment. They are not declared in the source.
- All structs use MSVC default packing (/Zp8) unless marked `pack(1)`. Pointers are 4 bytes, `wchar_t` 2 bytes.

## Discrepancy summary

19 source comments disagree with the computed layout. A wrong comment does not change what D2BS reads, because D2BS uses the declared types. But if the comment was right about the game, the declared layout (and every field after the first divergence) is wrong. The first discrepancy in a struct is the one to investigate; later ones with the same shift follow from it. "Code uses" lists `->name`/`.name` accesses in the repo. The match is by name only, so a hit can belong to a different struct with a field of the same name.

| Struct | Field | Line | Comment says | Computed | Shift | Likely cause | Code uses |
|---|---|---|---|---|---|---|---|
| LevelTxt | `nObjGroup` | `D2Structs.h:120` | 0x196 | 0x20E | +0x78 | comment is below the preceding field's comment (stale or copied) | - |
| LevelTxt | `nObjPrb` | `D2Structs.h:121` | 0x19E | 0x216 | +0x78 | same shift as the previous discrepancy | - |
| Control | `wText2` | `D2Structs.h:165` | 0x06C | 0x064 | -0x8 | comments imply the preceding `_12` is 0x10 bytes; it is declared 0x8 | `Control.cpp:81`, `Control.cpp:83`, `Control.cpp:249` +2 |
| BnetData | `channelname` | `D2Structs.h:201` | 0x35F | 0x361 | +0x2 | comments imply the preceding `szGameDesc` is 0x102 bytes; it is declared 0x104 | - |
| BnetData | `_14` | `D2Structs.h:202` | 0x37F | 0x381 | +0x2 | same shift as the previous discrepancy | - |
| BnetData | `charlevel` | `D2Structs.h:203` | 0x3BF | 0x3C1 | +0x2 | same shift as the previous discrepancy | - |
| BnetData | `ladderflag` | `D2Structs.h:204` | 0x3C0 | 0x3C2 | +0x2 | same shift as the previous discrepancy | `JSUnit.cpp:126` |
| BnetData | `passhash` | `D2Structs.h:205` | 0x3C1 | 0x3C3 | +0x2 | same shift as the previous discrepancy | - |
| BnetData | `passlength` | `D2Structs.h:206` | 0x3C5 | 0x3C7 | +0x2 | same shift as the previous discrepancy | - |
| CollMap | `pMapEnd` | `D2Structs.h:266` | 0x022 | 0x024 | +0x2 | comments imply the preceding `pMapStart` is 0x2 bytes; it is declared 0x4 | `Map/Diablo_II/LevelMap.cpp:123`, `Map/Diablo_II/LevelMap.cpp:124` |
| Level | `_5` | `D2Structs.h:291` | 0x1BC | 0x1B8 | -0x4 | comments imply the preceding `pMisc` is 0x8 bytes; it is declared 0x4 | - |
| ItemTxt | (anonymous union) | `D2Structs.h:511` | 0x040 | 0x080 | +0x40 | comments count the preceding `wchar_t szName2[0x40]` as 64 bytes; it is 0x80 bytes | - |
| ItemTxt | `_2a` | `D2Structs.h:517` | 0x0F7 | 0x0F6 | -0x1 | comments imply the preceding `nLocaleTxtNo` is 0x3 bytes; it is declared 0x2 | - |
| ItemTxt | `xSize` | `D2Structs.h:518` | 0x0FC | 0x10F | +0x13 | comments imply the preceding `_2a` is 0x5 bytes; it is declared 0x19 | `D2Helpers.cpp:113`, `JSGame.cpp:577`, `JSUnit.cpp:427` |
| ItemTxt | `ySize` | `D2Structs.h:519` | 0x0FD | 0x110 | +0x13 | same shift as the previous discrepancy | `D2Helpers.cpp:113`, `JSGame.cpp:574`, `JSUnit.cpp:434` |
| ItemTxt | `_2b` | `D2Structs.h:520` | 0x0FE | 0x111 | +0x13 | same shift as the previous discrepancy | - |
| ItemTxt | `fQuest` | `D2Structs.h:523` | 0x12A | 0x12C | +0x2 | comments imply the preceding `_3` is 0xB bytes; it is declared 0xD | - |
| MonsterTxt | `_3` | `D2Structs.h:545` | 0x12C | 0x168 | +0x3C | comments count the preceding `wchar_t szDescriptor[0x3c]` as 60 bytes; it is 0x78 bytes | - |
| ObjectTxt | `nAutoMap` | `D2Structs.h:581` | 0x1BB | 0x1BC | +0x1 | comments imply the preceding `_5` is 0x7 bytes; it is declared 0x8 | `Room.cpp:93` |

## Packing

`D2Structs.h` has 2 `#pragma pack(1)` regions:

- pack(1) set at `D2Structs.h:171`: `BnetData`, `RoomTile`, `RosterUnit`, `QuestInfo`, `Waypoint`, `PlayerData`, `CollMap`, `PresetUnit`, `Level`, `Room2`
- pack(1) set at `D2Structs.h:701`: `NPCMenu`, `OverheadMsg`

Effect of pack(1), computed by laying each packed struct out again with default packing:

| Struct | sizeof pack(1) | sizeof default | align pack(1) / default | Fields whose offset changes |
|---|---|---|---|---|
| BnetData | 0x3C8 | 0x3D0 | 1 / 4 | `_3` 0x35->0x36, `szGameIP` 0x37->0x38, `_5` 0x47->0x48, `dwId4` 0x89->0x8C, `szAccountName` 0x8D->0x90, `szPlayerName` 0xBD->0xC0 ... (26 total) |
| RoomTile | 0x14 | 0x14 | 1 / 4 | none (only the alignment changes) |
| RosterUnit | 0x84 | 0x84 | 1 / 4 | none (only the alignment changes) |
| QuestInfo | 0x8 | 0x8 | 1 / 4 | none (only the alignment changes) |
| Waypoint | 0x1 | 0x1 | 1 / 1 | none (pack(1) has no effect) |
| PlayerData | 0x28 | 0x28 | 1 / 4 | none (only the alignment changes) |
| CollMap | 0x28 | 0x28 | 1 / 4 | none (only the alignment changes) |
| PresetUnit | 0x1C | 0x1C | 1 / 4 | none (only the alignment changes) |
| Level | 0x22C | 0x22C | 1 / 4 | none (only the alignment changes) |
| Room2 | 0x60 | 0x60 | 1 / 4 | none (only the alignment changes) |
| NPCMenu | 0x27 | 0x2C | 1 / 4 | `dwEntryFunc1` 0x12->0x14, `dwEntryFunc2` 0x16->0x18, `dwEntryFunc3` 0x1A->0x1C, `dwEntryFunc4` 0x1E->0x20, `_2` 0x22->0x24 |
| OverheadMsg | 0xF8 | 0xF8 | 1 / 4 | none (only the alignment changes) |

In the Ghidra header these regions are written as `#pragma pack(push, 1)` ... `#pragma pack(pop)`. Ghidra's CParser reads this form itself (`PragmaSpecifier` in `Ghidra/Features/Base/src/main/javacc/ghidra/app/util/cparser/C/C.jj`). It does not support the source's bare `#pragma pack(push)`: the grammar only pushes when a value or identifier follows `push`, so the later `pop` would leave pack(1) active. CParser ignores `__attribute__((packed))` on structs (the `PACKED` qualifier is only used for enums).

## Relationships

Pointer chains. Each hop is `Struct+offset field` and yields the type in parentheses; offsets are computed:

- **Unit -> room -> level -> act**: `UnitAny+0x2C pPath` (Path*) → `Path+0x1C pRoom1` (Room1*) → `Room1+0x10 pRoom2` (Room2*) → `Room2+0x58 pLevel` (Level*) → `Level+0x1B4 pMisc` (ActMisc*) → `ActMisc+0x46C pAct` (Act*)
- **Act -> levels -> rooms -> collision**: `UnitAny+0x1C pAct` (Act*) → `Act+0x48 pMisc` (ActMisc*) → `ActMisc+0x47C pLevelFirst` (Level*) → `Level+0x10 pRoom2First` (Room2*) → `Room2+0x30 pRoom1` (Room1*) → `Room1+0x20 Coll` (CollMap*) → `CollMap+0x20 pMapStart` (WORD*)
- **Unit -> stats**: `UnitAny+0x5C pStats` (StatList*) → `StatList+0x24 StatVec` (StatVector) → `StatVector+0x0 pStats` (Stat*)
- **Unit -> items**: `UnitAny+0x60 pInventory` (Inventory*) → `Inventory+0xC pFirstItem` (UnitAny*) → `UnitAny+0x14 pItemData` (ItemData*)
- **Unit -> skills**: `UnitAny+0xA8 pInfo` (Info*) → `Info+0x4 pFirstSkill` (Skill*) → `Skill+0x0 pSkillInfo` (SkillInfo*)
- **Object unit -> txt record**: `UnitAny+0x14 pObjectData` (ObjectData*) → `ObjectData+0x0 pTxt` (ObjectTxt*)
- **Control -> text lines**: `Control+0x48 pFirstText` (ControlText*) → `ControlText+0x0 wText` (wchar_t*[5])

Linked lists (head field → element type, element's next field):

| Head | Element | Next link | Evidence / note |
|---|---|---|---|
| `ActMisc+0x47C pLevelFirst` (Level*) | Level | `Level+0x1AC pNextLevel` | - |
| `Level+0x10 pRoom2First` (Room2*) | Room2 | `Room2+0x24 pRoom2Next` | - |
| `Act+0x10 pRoom1` (Room1*) | Room1 | `Room1+0x7C pRoomNext` | `D2Helpers.cpp:483` |
| `Room2+0x5C pPreset` (PresetUnit*) | PresetUnit | `PresetUnit+0xC pPresetNext` | - |
| `Room2+0x4C pRoomTiles` (RoomTile*) | RoomTile | `RoomTile+0x4 pNext` | - |
| `Room1+0x74 pUnitFirst` (UnitAny*) | UnitAny | `UnitAny+0xE8 pRoomNext` | `D2Helpers.cpp:484` |
| `UnitHashTable+0x0 table` (UnitAny*[128]) | UnitAny | `UnitAny+0xE4 pListNext` | `Unit.cpp:32` |
| `Info+0x4 pFirstSkill` (Skill*) | Skill | `Skill+0x4 pNextSkill` | - |
| `Control+0x48 pFirstText` (ControlText*) | ControlText | `ControlText+0x1C pNext` | - |
| `AutomapLayer+0x8 pFloors` (AutomapCell*) | AutomapCell | `AutomapCell+0x10 pMore` | binary tree (`pLess`/`pMore`), not a list |
| `WindowHandlerHashTable+0x0 table` (WindowHandlerList**) | WindowHandlerList | `WindowHandlerList+0x10 next` | - |
| `MessageHandlerHashTable+0x0 table` (MessageHandlerList**) | MessageHandlerList | `MessageHandlerList+0xC next` | - |

All pointer fields that point to another struct in this file:

| From | Offset | Field | Points to |
|---|---|---|---|
| SplitText | 0x004 | `lpsNext` | SplitText |
| AutomapCell | 0x00C | `pLess` | AutomapCell |
| AutomapCell | 0x010 | `pMore` | AutomapCell |
| UnitInteraction | 0x004 | `lpPlayerUnit` | UnitAny |
| UnitInteraction | 0x008 | `lpTargetUnit` | UnitAny |
| UnitInteraction | 0x01C | `pSkill` | Skill |
| CellFile | 0x018 | `cells` | GfxCell (array of pointers) |
| CellContext | 0x034 | `pCellFile` | CellFile |
| AutomapLayer | 0x008 | `pFloors` | AutomapCell |
| AutomapLayer | 0x00C | `pWalls` | AutomapCell |
| AutomapLayer | 0x010 | `pObjects` | AutomapCell |
| AutomapLayer | 0x014 | `pExtras` | AutomapCell |
| AutomapLayer | 0x018 | `pNextLayer` | AutomapLayer |
| ControlText | 0x01C | `pNext` | ControlText |
| Control | 0x03C | `pNext` | Control |
| Control | 0x048 | `pFirstText` | ControlText |
| Control | 0x04C | `pLastText` | ControlText |
| Control | 0x050 | `pSelectedText` | ControlText |
| RoomTile | 0x000 | `pRoom2` | Room2 |
| RoomTile | 0x004 | `pNext` | RoomTile |
| RosterUnit | 0x080 | `pNext` | RosterUnit |
| PlayerData | 0x010 | `pNormalQuest` | QuestInfo |
| PlayerData | 0x014 | `pNightmareQuest` | QuestInfo |
| PlayerData | 0x018 | `pHellQuest` | QuestInfo |
| PlayerData | 0x01C | `pNormalWaypoint` | Waypoint |
| PlayerData | 0x020 | `pNightmareWaypoint` | Waypoint |
| PlayerData | 0x024 | `pHellWaypoint` | Waypoint |
| PresetUnit | 0x00C | `pPresetNext` | PresetUnit |
| Level | 0x010 | `pRoom2First` | Room2 |
| Level | 0x1AC | `pNextLevel` | Level |
| Level | 0x1B4 | `pMisc` | ActMisc |
| Room2 | 0x008 | `pRoom2Near` | Room2* |
| Room2 | 0x020 | `pType2Info` | Room2__pType2Info_t |
| Room2 | 0x024 | `pRoom2Next` | Room2 |
| Room2 | 0x030 | `pRoom1` | Room1 |
| Room2 | 0x04C | `pRoomTiles` | RoomTile |
| Room2 | 0x058 | `pLevel` | Level |
| Room2 | 0x05C | `pPreset` | PresetUnit |
| Room1 | 0x000 | `pRoomsNear` | Room1* |
| Room1 | 0x010 | `pRoom2` | Room2 |
| Room1 | 0x020 | `Coll` | CollMap |
| Room1 | 0x074 | `pUnitFirst` | UnitAny |
| Room1 | 0x07C | `pRoomNext` | Room1 |
| ActMisc | 0x46C | `pAct` | Act |
| ActMisc | 0x47C | `pLevelFirst` | Level |
| Act | 0x010 | `pRoom1` | Room1 |
| Act | 0x048 | `pMisc` | ActMisc |
| Path | 0x01C | `pRoom1` | Room1 |
| Path | 0x020 | `pRoomUnk` | Room1 |
| Path | 0x030 | `pUnit` | UnitAny |
| Path | 0x058 | `pTargetUnit` | UnitAny |
| StatVector | 0x000 | `pStats` | Stat |
| StatList | 0x004 | `pUnit` | UnitAny |
| StatList | 0x02C | `pPrevLink` | StatList |
| StatList | 0x034 | `pPrev` | StatList |
| StatList | 0x03C | `pNext` | StatList |
| StatList | 0x040 | `pSetList` | StatList |
| Inventory | 0x008 | `pOwner` | UnitAny |
| Inventory | 0x00C | `pFirstItem` | UnitAny |
| Inventory | 0x010 | `pLastItem` | UnitAny |
| Inventory | 0x020 | `pCursorItem` | UnitAny |
| Skill | 0x000 | `pSkillInfo` | SkillInfo |
| Skill | 0x004 | `pNextSkill` | Skill |
| Info | 0x004 | `pFirstSkill` | Skill |
| Info | 0x008 | `pLeftSkill` | Skill |
| Info | 0x00C | `pRightSkill` | Skill |
| ItemData | 0x05C | `pOwnerInventory` | Inventory |
| ItemData | 0x064 | `pNextInvItem` | UnitAny |
| ItemData | 0x084 | `pOwner` | UnitAny |
| ObjectData | 0x000 | `pTxt` | ObjectTxt |
| ObjectPath | 0x000 | `pRoom1` | Room1 |
| UnitAny | 0x014 | `pPlayerData` | PlayerData |
| UnitAny | 0x014 | `pItemData` | ItemData |
| UnitAny | 0x014 | `pMonsterData` | MonsterData |
| UnitAny | 0x014 | `pObjectData` | ObjectData |
| UnitAny | 0x01C | `pAct` | Act |
| UnitAny | 0x02C | `pPath` | Path |
| UnitAny | 0x02C | `pItemPath` | ItemPath |
| UnitAny | 0x02C | `pObjectPath` | ObjectPath |
| UnitAny | 0x05C | `pStats` | StatList |
| UnitAny | 0x060 | `pInventory` | Inventory |
| UnitAny | 0x064 | `ptLight` | Light |
| UnitAny | 0x070 | `pUpdateUnit` | UnitAny |
| UnitAny | 0x0A4 | `pOMsg` | OverheadMsg |
| UnitAny | 0x0A8 | `pInfo` | Info |
| UnitAny | 0x0E0 | `pChangedNext` | UnitAny |
| UnitAny | 0x0E4 | `pListNext` | UnitAny |
| UnitAny | 0x0E8 | `pRoomNext` | UnitAny |
| UnitHashTable | 0x000 | `table` | UnitAny (array of pointers) |
| WardenClient_t | 0x000 | `pWardenRegion` | WardenClientRegion_t |
| sgptDataTable | 0x000 | `pPlayerClass` | MpqTable |
| sgptDataTable | 0x008 | `pBodyLocs` | MpqTable |
| sgptDataTable | 0x010 | `pStorePage` | MpqTable |
| sgptDataTable | 0x018 | `pElemTypes` | MpqTable |
| MessageHandlerList | 0x00C | `next` | MessageHandlerList |
| MessageHandlerHashTable | 0x000 | `table` | MessageHandlerList* |
| WindowHandlerHashTable | 0x000 | `table` | WindowHandlerList* |
| WindowHandlerList | 0x00C | `msgHandlers` | MessageHandlerHashTable |
| WindowHandlerList | 0x010 | `next` | WindowHandlerList |

## Units & paths

### UnitAny

`D2Structs.h:605-662` · sizeof **0xEC** (236) · align 4 · packing default (/Zp8)

D2Ptrs.h: 28 symbols use it: `D2CLIENT_FindClientSideUnit` (ret), `D2CLIENT_FindServerSideUnit` (ret), `D2CLIENT_GetCurrentInteractingNPC` (ret), `D2CLIENT_GetSelectedUnit` (ret), `D2CLIENT_GetCursorItem` (ret), `D2CLIENT_SetSelectedUnit_I` (param), `D2CLIENT_GetItemName` (param), `D2CLIENT_LoadItemDesc` (param), `D2CLIENT_GetUnitX` (param), `D2CLIENT_GetUnitY` (param), `D2CLIENT_ShopAction` (param), `D2CLIENT_LeftClickItem_I` (param), `D2CLIENT_GetPlayerUnit` (ret), `p_D2CLIENT_PlayerUnit` (var), `p_D2CLIENT_SelectedInvItem` (var), `D2COMMON_GetStatList` (param), `D2COMMON_GetUnitStat` (param), `D2COMMON_GetUnitState` (param), `D2COMMON_CheckUnitCollision` (param), `D2COMMON_GetRoomFromUnit` (param), `D2COMMON_GetSkillLevel` (param), `D2COMMON_GetItemLevelRequirement` (param), `D2COMMON_GetItemPrice` (param), `D2COMMON_GetRepairCost` (param), `D2COMMON_GetItemFromInventory` (ret), `D2COMMON_GetNextItemFromInventory` (param/ret), `D2COMMON_GetItemPalette` (param), `D2COMMON_GetMissileOwnerUnit` (param/ret).

Named in 20 other source files: `Core.cpp`, `Core.h`, `D2Handlers.cpp`, `D2Handlers.h`, `D2Helpers.cpp`, `D2Helpers.h`, `D2Intercepts.cpp`, `D2Intercepts.h`, `JSGame.cpp`, `JSParty.cpp`, `JSRoom.cpp`, `JSUnit.cpp`, `Map/Diablo_II/ActMap.cpp`, `Map/Diablo_II/LevelMap.cpp`, `Map/Diablo_II/LevelMap.h`, `Map/Path/AStarPath.h`, `Room.cpp`, `ScriptEngine.cpp`, `Unit.cpp`, `Unit.h`.

> The +0x14 union is selected by `dwType` (UNIT_* values at `Constants.h:361`-`Constants.h:366`): 0 player -> `pPlayerData` (`D2Helpers.cpp:69`), 1 monster -> `pMonsterData` (`JSUnit.cpp:283`), 2 object and 5 tile -> `pObjectData` (`D2Helpers.cpp:85`), 4 item -> `pItemData` (`JSUnit.cpp:319`). No struct exists for 3 (missile).

> The +0x2C union: `pPath` for players/monsters (`Unit.cpp:75`), `pItemPath` for items (`JSGame.cpp:475`), `pObjectPath` for objects. ItemPath/ObjectPath only define the first 0x14 bytes (source: "Use Path for the rest").

> Lists: hash-table buckets chain through `pListNext` (`Unit.cpp:32`); units of a room chain through `pRoomNext` (`D2Helpers.cpp:484`).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwType` | 0x00 | `D2Structs.h:606` |
| 0x004 | 0x4 | `DWORD` | `dwTxtFileNo` | 0x04 | `D2Structs.h:607` |
| 0x008 | 0x4 | `DWORD` | `_1` | 0x08 | unknown; `D2Structs.h:608` |
| 0x00C | 0x4 | `DWORD` | `dwUnitId` | 0x0C | `D2Structs.h:609` |
| 0x010 | 0x4 | `DWORD` | `dwMode` | 0x10 | `D2Structs.h:610` |
| 0x014 | 0x4 | union (anonymous) | (anonymous union) | 0x14 | C: member `u_14`, type `UnitAny__u_14`; `D2Structs.h:611` |
| 0x014 | 0x4 | `PlayerData*` | ↳ `pPlayerData` |  | C: `u_14.pPlayerData`; `D2Structs.h:612` |
| 0x014 | 0x4 | `ItemData*` | ↳ `pItemData` |  | C: `u_14.pItemData`; `D2Structs.h:613` |
| 0x014 | 0x4 | `MonsterData*` | ↳ `pMonsterData` |  | C: `u_14.pMonsterData`; `D2Structs.h:614` |
| 0x014 | 0x4 | `ObjectData*` | ↳ `pObjectData` |  | C: `u_14.pObjectData`; `D2Structs.h:615` |
| 0x018 | 0x4 | `DWORD` | `dwAct` | 0x18 | `D2Structs.h:618` |
| 0x01C | 0x4 | `Act*` | `pAct` | 0x1C | `D2Structs.h:619` |
| 0x020 | 0x8 | `DWORD[2]` | `dwSeed` | 0x20 | `D2Structs.h:620` |
| 0x028 | 0x4 | `DWORD` | `_2` | 0x28 | unknown; `D2Structs.h:621` |
| 0x02C | 0x4 | union (anonymous) | (anonymous union) | 0x2C | C: member `u_2C`, type `UnitAny__u_2C`; `D2Structs.h:622` |
| 0x02C | 0x4 | `Path*` | ↳ `pPath` |  | C: `u_2C.pPath`; `D2Structs.h:623` |
| 0x02C | 0x4 | `ItemPath*` | ↳ `pItemPath` |  | C: `u_2C.pItemPath`; `D2Structs.h:624` |
| 0x02C | 0x4 | `ObjectPath*` | ↳ `pObjectPath` |  | C: `u_2C.pObjectPath`; `D2Structs.h:625` |
| 0x030 | 0x14 | `DWORD[5]` | `_3` | 0x30 | unknown; `D2Structs.h:627` |
| 0x044 | 0x4 | `DWORD` | `dwGfxFrame` | 0x44 | `D2Structs.h:628` |
| 0x048 | 0x4 | `DWORD` | `dwFrameRemain` | 0x48 | `D2Structs.h:629` |
| 0x04C | 0x2 | `WORD` | `wFrameRate` | 0x4C | `D2Structs.h:630` |
| 0x04E | 0x2 | `WORD` | `_4` | 0x4E | unknown; `D2Structs.h:631` |
| 0x050 | 0x4 | `BYTE*` | `pGfxUnk` | 0x50 | `D2Structs.h:632` |
| 0x054 | 0x4 | `DWORD*` | `pGfxInfo` | 0x54 | `D2Structs.h:633` |
| 0x058 | 0x4 | `DWORD` | `_5` | 0x58 | unknown; `D2Structs.h:634` |
| 0x05C | 0x4 | `StatList*` | `pStats` | 0x5C | `D2Structs.h:635` |
| 0x060 | 0x4 | `Inventory*` | `pInventory` | 0x60 | `D2Structs.h:636` |
| 0x064 | 0x4 | `Light*` | `ptLight` | 0x64 | `D2Structs.h:637` |
| 0x068 | 0x4 | `DWORD` | `dwStartLightRadius` | 0x68 | `D2Structs.h:638` |
| 0x06C | 0x2 | `WORD` | `nPl2ShiftIdx` | 0x6C | `D2Structs.h:639` |
| 0x06E | 0x2 | `WORD` | `nUpdateType` | 0x6E | `D2Structs.h:640` |
| 0x070 | 0x4 | `UnitAny*` | `pUpdateUnit` | 0x70 - Used when updating unit. | `D2Structs.h:641` |
| 0x074 | 0x4 | `DWORD*` | `pQuestRecord` | 0x74 | `D2Structs.h:642` |
| 0x078 | 0x4 | `DWORD` | `bSparklyChest` | 0x78 bool | `D2Structs.h:643` |
| 0x07C | 0x4 | `DWORD*` | `pTimerArgs` | 0x7C | `D2Structs.h:644` |
| 0x080 | 0x4 | `DWORD` | `dwSoundSync` | 0x80 | `D2Structs.h:645` |
| 0x084 | 0x8 | `DWORD[2]` | `_6` | 0x84 | unknown; `D2Structs.h:646` |
| 0x08C | 0x2 | `WORD` | `wX` | 0x8C | `D2Structs.h:647` |
| 0x08E | 0x2 | `WORD` | `wY` | 0x8E | `D2Structs.h:648` |
| 0x090 | 0x4 | `DWORD` | `_7` | 0x90 | unknown; `D2Structs.h:649` |
| 0x094 | 0x4 | `DWORD` | `dwOwnerType` | 0x94 | `D2Structs.h:650` |
| 0x098 | 0x4 | `DWORD` | `dwOwnerId` | 0x98 | `D2Structs.h:651` |
| 0x09C | 0x8 | `DWORD[2]` | `_8` | 0x9C | unknown; `D2Structs.h:652` |
| 0x0A4 | 0x4 | `OverheadMsg*` | `pOMsg` | 0xA4 | `D2Structs.h:653` |
| 0x0A8 | 0x4 | `Info*` | `pInfo` | 0xA8 | `D2Structs.h:654` |
| 0x0AC | 0x18 | `DWORD[6]` | `_9` | 0xAC | unknown; `D2Structs.h:655` |
| 0x0C4 | 0x4 | `DWORD` | `dwFlags` | 0xC4 | `D2Structs.h:656` |
| 0x0C8 | 0x4 | `DWORD` | `dwFlags2` | 0xC8 | `D2Structs.h:657` |
| 0x0CC | 0x14 | `DWORD[5]` | `_10` | 0xCC | unknown; `D2Structs.h:658` |
| 0x0E0 | 0x4 | `UnitAny*` | `pChangedNext` | 0xE0 | `D2Structs.h:659` |
| 0x0E4 | 0x4 | `UnitAny*` | `pListNext` | 0xE4 -> 0xD8 | `D2Structs.h:660` |
| 0x0E8 | 0x4 | `UnitAny*` | `pRoomNext` | 0xE8 | `D2Structs.h:661` |

### UnitHashTable

`D2Structs.h:664-666` · sizeof **0x200** (512) · align 4 · packing default (/Zp8)

D2Ptrs.h: 2 symbols use it: `p_D2CLIENT_ServerSideUnitHashTables` (var), `p_D2CLIENT_ClientSideUnitHashTables` (var).

Named in 1 other source file: `Unit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x200 | `UnitAny*[128]` | `table` |  | `D2Structs.h:665` |

### PlayerData

`D2Structs.h:246-254` · sizeof **0x28** (40) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x10 | `char[0x10]` | `szName` | 0x00 | `D2Structs.h:247` |
| 0x010 | 0x4 | `QuestInfo*` | `pNormalQuest` | 0x10 | `D2Structs.h:248` |
| 0x014 | 0x4 | `QuestInfo*` | `pNightmareQuest` | 0x14 | `D2Structs.h:249` |
| 0x018 | 0x4 | `QuestInfo*` | `pHellQuest` | 0x18 | `D2Structs.h:250` |
| 0x01C | 0x4 | `Waypoint*` | `pNormalWaypoint` | 0x1c | `D2Structs.h:251` |
| 0x020 | 0x4 | `Waypoint*` | `pNightmareWaypoint` | 0x20 | `D2Structs.h:252` |
| 0x024 | 0x4 | `Waypoint*` | `pHellWaypoint` | 0x24 | `D2Structs.h:253` |

### QuestInfo

`D2Structs.h:237-240` · sizeof **0x8** (8) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `void*` | `pBuffer` | 0x00 | `D2Structs.h:238` |
| 0x004 | 0x4 | `DWORD` | `_1` | 0x04 | unknown; `D2Structs.h:239` |

### Waypoint

`D2Structs.h:242-244` · sizeof **0x1** (1) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x1 | `BYTE` | `flags` | 0x00 | `D2Structs.h:243` |

### MonsterData

`D2Structs.h:548-564` · sizeof **0x64** (100) · align 4 · packing default (/Zp8)

> The bit-field byte at +0x16 is read as `fMinion`/`fBoss`/`fChamp`/`fNormal` (`JSUnit.cpp:284`).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x16 | `BYTE[22]` | `_1` | 0x00 | unknown; `D2Structs.h:549` |
| 0x016 | 0x1 | struct (anonymous) | (anonymous struct) | 0x16 | C: flattened into the parent; `D2Structs.h:550` |
| 0x016 | 0x1 | `BYTE : 1` | ↳ `fUnk` |  | bits 0..0; `D2Structs.h:551` |
| 0x016 | 0x1 | `BYTE : 1` | ↳ `fNormal` |  | bits 1..1; `D2Structs.h:552` |
| 0x016 | 0x1 | `BYTE : 1` | ↳ `fChamp` |  | bits 2..2; `D2Structs.h:553` |
| 0x016 | 0x1 | `BYTE : 1` | ↳ `fBoss` |  | bits 3..3; `D2Structs.h:554` |
| 0x016 | 0x1 | `BYTE : 1` | ↳ `fMinion` |  | bits 4..4; `D2Structs.h:555` |
| 0x017 | 0x5 | `BYTE[5]` | `_2` |  | unknown; `D2Structs.h:557` |
| 0x01C | 0x9 | `BYTE[9]` | `anEnchants` | 0x1C | `D2Structs.h:558` |
| 0x025 | 0x1 | | (padding) | | compiler alignment padding |
| 0x026 | 0x2 | `WORD` | `wUniqueNo` | 0x26 | `D2Structs.h:559` |
| 0x028 | 0x4 | `DWORD` | `_5` | 0x28 | unknown; `D2Structs.h:560` |
| 0x02C | 0x38 | struct (anonymous) | (anonymous struct) | 0x2C | C: flattened into the parent; `D2Structs.h:561` |
| 0x02C | 0x38 | `wchar_t[28]` | ↳ `wName` |  | `D2Structs.h:562` |

### MonsterTxt

`D2Structs.h:526-546` · sizeof **0x308** (776) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x6 | `BYTE[0x6]` | `_1` | 0x00 | unknown; `D2Structs.h:527` |
| 0x006 | 0x2 | `WORD` | `nLocaleTxtNo` | 0x06 | `D2Structs.h:528` |
| 0x008 | 0x2 | `WORD` | `flag` | 0x08 | `D2Structs.h:529` |
| 0x00A | 0x2 | `WORD` | `_1a` | 0x0A | unknown; `D2Structs.h:530` |
| 0x00C | 0x4 | union (anonymous) | (anonymous union) |  | C: member `u_0C`, type `MonsterTxt__u_0C`; `D2Structs.h:531` |
| 0x00C | 0x4 | `DWORD` | ↳ `flag1` | 0x0C | C: `u_0C.flag1`; `D2Structs.h:532` |
| 0x00C | 0x4 | struct (anonymous) | ↳ (anonymous struct) |  | C: member `s_0C`, type `MonsterTxt__u_0C__s_0C`; `D2Structs.h:533` |
| 0x00C | 0x1 | `BYTE` | ↳ ↳ `flag1a` | 0x0C | C: `u_0C.s_0C.flag1a`; `D2Structs.h:534` |
| 0x00D | 0x1 | `BYTE` | ↳ ↳ `flag1b` | 0x0D | C: `u_0C.s_0C.flag1b`; `D2Structs.h:535` |
| 0x00E | 0x2 | `BYTE[2]` | ↳ ↳ `flag1c` | 0x0E | C: `u_0C.s_0C.flag1c`; `D2Structs.h:536` |
| 0x010 | 0x22 | `BYTE[0x22]` | `_2` | 0x10 | unknown; `D2Structs.h:539` |
| 0x032 | 0x2 | `WORD` | `velocity` | 0x32 | `D2Structs.h:540` |
| 0x034 | 0x52 | `BYTE[0x52]` | `_2a` | 0x34 | unknown; `D2Structs.h:541` |
| 0x086 | 0x18 | `WORD[3][4]` | `tcs` | 0x86 | `D2Structs.h:542` |
| 0x09E | 0x52 | `BYTE[0x52]` | `_2b` | 0x9E | unknown; `D2Structs.h:543` |
| 0x0F0 | 0x78 | `wchar_t[0x3c]` | `szDescriptor` | 0xF0 | `D2Structs.h:544` |
| 0x168 | 0x1A0 | `BYTE[0x1a0]` | `_3` | 0x12C | **DISCREPANCY**: comment says 0x12C, computed 0x168; unknown; `D2Structs.h:545` |

### ObjectData

`D2Structs.h:584-595` · sizeof **0x38** (56) · align 4 · packing default (/Zp8)

> `Type` and the `ChestLocked` bit share byte +0x04 (`JSUnit.cpp:514`).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `ObjectTxt*` | `pTxt` | 0x00 | `D2Structs.h:585` |
| 0x004 | 0x1 | union (anonymous) | (anonymous union) |  | C: member `u_04`, type `ObjectData__u_04`; `D2Structs.h:586` |
| 0x004 | 0x1 | `BYTE` | ↳ `Type` | 0x04 (0x0F would be a Exp Shrine) | C: `u_04.Type`; `D2Structs.h:587` |
| 0x004 | 0x1 | struct (anonymous) | ↳ (anonymous struct) |  | C: member `s_04`, type `ObjectData__u_04__s_04`; `D2Structs.h:588` |
| 0x004 | 0x1 | `BYTE : 7` | ↳ ↳ `_1` |  | unknown; bits 0..6; C: `u_04.s_04._1`; `D2Structs.h:589` |
| 0x004 | 0x1 | `BYTE : 1` | ↳ ↳ `ChestLocked` |  | bits 7..7; C: `u_04.s_04.ChestLocked`; `D2Structs.h:590` |
| 0x005 | 0x3 | | (padding) | | compiler alignment padding |
| 0x008 | 0x20 | `DWORD[8]` | `_2` | 0x08 | unknown; `D2Structs.h:593` |
| 0x028 | 0x10 | `char[0x10]` | `szOwner` | 0x28 | `D2Structs.h:594` |

### ObjectTxt

`D2Structs.h:566-582` · sizeof **0x1C0** (448) · align 4 · packing default (/Zp8)

D2Ptrs.h: 2 symbols use it: `D2COMMON_GetObjectTxt` (ret), `D2COMMON_GetObjectText` (ret).

Named in 2 other source files: `Map/Diablo_II/ActMap.cpp`, `Room.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x40 | `char[0x40]` | `szName` | 0x00 | `D2Structs.h:567` |
| 0x040 | 0x80 | `wchar_t[0x40]` | `wszName` | 0x40 | `D2Structs.h:568` |
| 0x0C0 | 0x4 | `BYTE[4]` | `_1` | 0xC0 | unknown; `D2Structs.h:569` |
| 0x0C4 | 0x1 | `BYTE` | `nSelectable0` | 0xC4 | `D2Structs.h:570` |
| 0x0C5 | 0x87 | `BYTE[0x87]` | `_2` | 0xC5 | unknown; `D2Structs.h:571` |
| 0x14C | 0x1 | `BYTE` | `nOrientation` | 0x14C | `D2Structs.h:572` |
| 0x14D | 0x19 | `BYTE[0x19]` | `_2b` | 0x14D | unknown; `D2Structs.h:573` |
| 0x166 | 0x1 | `BYTE` | `nSubClass` | 0x166 | `D2Structs.h:574` |
| 0x167 | 0x11 | `BYTE[0x11]` | `_3` | 0x167 | unknown; `D2Structs.h:575` |
| 0x178 | 0x1 | `BYTE` | `nParm0` | 0x178 | `D2Structs.h:576` |
| 0x179 | 0x39 | `BYTE[0x39]` | `_4` | 0x179 | unknown; `D2Structs.h:577` |
| 0x1B2 | 0x1 | `BYTE` | `nPopulateFn` | 0x1B2 | `D2Structs.h:578` |
| 0x1B3 | 0x1 | `BYTE` | `nOperateFn` | 0x1B3 | `D2Structs.h:579` |
| 0x1B4 | 0x8 | `BYTE[8]` | `_5` | 0x1B4 | unknown; `D2Structs.h:580` |
| 0x1BC | 0x4 | `DWORD` | `nAutoMap` | 0x1BB | **DISCREPANCY**: comment says 0x1BB, computed 0x1BC; `D2Structs.h:581` |

### Path

`D2Structs.h:368-391` · sizeof **0x68** (104) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetTargetUnitType` (param/ret).

Named in 1 other source file: `D2Helpers.h`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x2 | `WORD` | `xOffset` | 0x00 | `D2Structs.h:369` |
| 0x002 | 0x2 | `WORD` | `xPos` | 0x02 | `D2Structs.h:370` |
| 0x004 | 0x2 | `WORD` | `yOffset` | 0x04 | `D2Structs.h:371` |
| 0x006 | 0x2 | `WORD` | `yPos` | 0x06 | `D2Structs.h:372` |
| 0x008 | 0x8 | `DWORD[2]` | `_1` | 0x08 | unknown; `D2Structs.h:373` |
| 0x010 | 0x2 | `WORD` | `xTarget` | 0x10 | `D2Structs.h:374` |
| 0x012 | 0x2 | `WORD` | `yTarget` | 0x12 | `D2Structs.h:375` |
| 0x014 | 0x8 | `DWORD[2]` | `_2` | 0x14 | unknown; `D2Structs.h:376` |
| 0x01C | 0x4 | `Room1*` | `pRoom1` | 0x1C | `D2Structs.h:377` |
| 0x020 | 0x4 | `Room1*` | `pRoomUnk` | 0x20 | `D2Structs.h:378` |
| 0x024 | 0xC | `DWORD[3]` | `_3` | 0x24 | unknown; `D2Structs.h:379` |
| 0x030 | 0x4 | `UnitAny*` | `pUnit` | 0x30 | `D2Structs.h:380` |
| 0x034 | 0x4 | `DWORD` | `dwFlags` | 0x34 | `D2Structs.h:381` |
| 0x038 | 0x4 | `DWORD` | `_4` | 0x38 | unknown; `D2Structs.h:382` |
| 0x03C | 0x4 | `DWORD` | `dwPathType` | 0x3C | `D2Structs.h:383` |
| 0x040 | 0x4 | `DWORD` | `dwPrevPathType` | 0x40 | `D2Structs.h:384` |
| 0x044 | 0x4 | `DWORD` | `dwUnitSize` | 0x44 | `D2Structs.h:385` |
| 0x048 | 0x10 | `DWORD[4]` | `_5` | 0x48 | unknown; `D2Structs.h:386` |
| 0x058 | 0x4 | `UnitAny*` | `pTargetUnit` | 0x58 | `D2Structs.h:387` |
| 0x05C | 0x4 | `DWORD` | `dwTargetType` | 0x5C | `D2Structs.h:388` |
| 0x060 | 0x4 | `DWORD` | `dwTargetId` | 0x60 | `D2Structs.h:389` |
| 0x064 | 0x1 | `BYTE` | `bDirection` | 0x64 | `D2Structs.h:390` |
| 0x065 | 0x3 | | (padding) | | tail padding to align 4 |

### ItemPath

`D2Structs.h:393-398` · sizeof **0x14** (20) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0xC | `DWORD[3]` | `_1` | 0x00 | unknown; `D2Structs.h:394` |
| 0x00C | 0x4 | `DWORD` | `dwPosX` | 0x0C | `D2Structs.h:395` |
| 0x010 | 0x4 | `DWORD` | `dwPosY` | 0x10 | `D2Structs.h:396` |

### ObjectPath

`D2Structs.h:597-603` · sizeof **0x14** (20) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `Room1*` | `pRoom1` | 0x00 | `D2Structs.h:598` |
| 0x004 | 0x8 | `DWORD[2]` | `_1` | 0x04 | unknown; `D2Structs.h:599` |
| 0x00C | 0x4 | `DWORD` | `dwPosX` | 0x0C | `D2Structs.h:600` |
| 0x010 | 0x4 | `DWORD` | `dwPosY` | 0x10 | `D2Structs.h:601` |

### UnitInteraction

`D2Structs.h:65-74` · sizeof **0x20** (32) · align 4 · packing default (/Zp8)

Named in 3 other source files: `D2Handlers.cpp`, `D2Handlers.h`, `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwMoveType` | 0x00 | `D2Structs.h:66` |
| 0x004 | 0x4 | `UnitAny*` | `lpPlayerUnit` | 0x04 | `D2Structs.h:67` |
| 0x008 | 0x4 | `UnitAny*` | `lpTargetUnit` | 0x08 | `D2Structs.h:68` |
| 0x00C | 0x4 | `DWORD` | `dwTargetX` | 0x0C | `D2Structs.h:69` |
| 0x010 | 0x4 | `DWORD` | `dwTargetY` | 0x10 | `D2Structs.h:70` |
| 0x014 | 0x4 | `DWORD` | `_1` | 0x14 | unknown; `D2Structs.h:71` |
| 0x018 | 0x4 | `DWORD` | `_2` | 0x18 | unknown; `D2Structs.h:72` |
| 0x01C | 0x4 | `Skill*` | `pSkill` |  | `D2Structs.h:73` |

### Light

`D2Structs.h:446-452` · sizeof **0x34** (52) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0xC | `DWORD[3]` | `_1` | 0x00 | unknown; `D2Structs.h:447` |
| 0x00C | 0x4 | `DWORD` | `dwType` | 0x0C | `D2Structs.h:448` |
| 0x010 | 0x1C | `DWORD[7]` | `_2` | 0x10 | unknown; `D2Structs.h:449` |
| 0x02C | 0x4 | `DWORD` | `dwStaticValid` | 0x2C | `D2Structs.h:450` |
| 0x030 | 0x4 | `int*` | `pnStaticMap` | 0x30 | `D2Structs.h:451` |

### OverheadMsg

`D2Structs.h:718-723` · sizeof **0xF8** (248) · align 1 · packing pack(1) (set at `D2Structs.h:701`)

D2Ptrs.h: 2 symbols use it: `D2COMMON_GenerateOverheadMsg` (ret), `D2COMMON_FixOverheadMsg` (param).

Named in 1 other source file: `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `_1` |  | unknown; `D2Structs.h:719` |
| 0x004 | 0x4 | `DWORD` | `dwTrigger` |  | `D2Structs.h:720` |
| 0x008 | 0x8 | `DWORD[2]` | `_2` |  | unknown; `D2Structs.h:721` |
| 0x010 | 0xE8 | `char[232]` | `Msg` |  | `D2Structs.h:722` |

## Items & inventory

### ItemData

`D2Structs.h:476-507` · sizeof **0x88** (136) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwQuality` | 0x00 | `D2Structs.h:477` |
| 0x004 | 0x8 | `DWORD[2]` | `dwSeed` | 0x04 | `D2Structs.h:478` |
| 0x00C | 0x4 | `DWORD` | `dwItemFlags` | 0x0C 1 = Owned by player, 0xFFFFFFFF = Not owned | `D2Structs.h:479` |
| 0x010 | 0x4 | `DWORD` | `dwFingerPrint` | 0x10 Initial seed | `D2Structs.h:480` |
| 0x014 | 0x4 | `DWORD` | `_1` | 0x14 CommandFlags? | unknown; `D2Structs.h:481` |
| 0x018 | 0x4 | `DWORD` | `dwFlags` | 0x18 | `D2Structs.h:482` |
| 0x01C | 0x8 | `DWORD[2]` | `_2` | 0x1C | unknown; `D2Structs.h:483` |
| 0x024 | 0x4 | `DWORD` | `dwActionStamp` | 0x24 Changes when an item is changed | `D2Structs.h:484` |
| 0x028 | 0x4 | `DWORD` | `dwFileIndex` | 0x28 Data file index UniqueItems.txt etc. | `D2Structs.h:485` |
| 0x02C | 0x4 | `DWORD` | `dwItemLevel` | 0x2C | `D2Structs.h:486` |
| 0x030 | 0x2 | `WORD` | `wItemFormat` | 0x30 | `D2Structs.h:487` |
| 0x032 | 0x2 | `WORD` | `wRarePrefix` | 0x32 | `D2Structs.h:488` |
| 0x034 | 0x2 | `WORD` | `wRareSuffix` | 0x34 | `D2Structs.h:489` |
| 0x036 | 0x2 | `WORD` | `wAutoPrefix` | 0x36 | `D2Structs.h:490` |
| 0x038 | 0x6 | `WORD[3]` | `wMagicPrefix` | 0x38 | `D2Structs.h:491` |
| 0x03E | 0x6 | `WORD[3]` | `wMagicSuffix` | 0x3E | `D2Structs.h:492` |
| 0x044 | 0x1 | `BYTE` | `BodyLocation` | 0x44 Not always cleared | `D2Structs.h:493` |
| 0x045 | 0x1 | `BYTE` | `ItemLocation` | 0x45 Non-body/belt location (Body/Belt == 0xFF) | `D2Structs.h:494` |
| 0x046 | 0x2 | `WORD` | `_4` | 0x46 | unknown; `D2Structs.h:495` |
| 0x048 | 0x1 | `BYTE` | `bEarLevel` | 0x48 | `D2Structs.h:496` |
| 0x049 | 0x1 | `BYTE` | `bInvGfxIdx` | 0x49 | `D2Structs.h:497` |
| 0x04A | 0x10 | `char[16]` | `szPlayerName` | 0x4A Personalized / Ear name | `D2Structs.h:498` |
| 0x05A | 0x2 | | (padding) | | compiler alignment padding |
| 0x05C | 0x4 | `Inventory*` | `pOwnerInventory` | 0x5C Socketed Items owner Inv | `D2Structs.h:499` |
| 0x060 | 0x4 | `DWORD` | `_10` | 0x60 | unknown; `D2Structs.h:500` |
| 0x064 | 0x4 | `UnitAny*` | `pNextInvItem` | 0x64 Next item in socketed item if OwnerInventory is set | `D2Structs.h:501` |
| 0x068 | 0x1 | `BYTE` | `GameLocation` | 0x68 Location per docs.d2bs.org (unit.location) | `D2Structs.h:502` |
| 0x069 | 0x1 | `BYTE` | `NodePage` | 0x69 Actual location, this is the most reliable by far | `D2Structs.h:503` |
| 0x06A | 0x2 | `WORD` | `_12` | 0x6A | unknown; `D2Structs.h:504` |
| 0x06C | 0x18 | `WORD[12]` | `_13` | 0x6C | unknown; `D2Structs.h:505` |
| 0x084 | 0x4 | `UnitAny*` | `pOwner` | 0x84 | `D2Structs.h:506` |

### ItemTxt

`D2Structs.h:509-524` · sizeof **0x130** (304) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetItemText` (ret).

Named in 3 other source files: `D2Helpers.cpp`, `JSGame.cpp`, `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x80 | `wchar_t[0x40]` | `szName2` | 0x00 | `D2Structs.h:510` |
| 0x080 | 0x4 | union (anonymous) | (anonymous union) | 0x40 | **DISCREPANCY**: comment says 0x40, computed 0x80; C: member `u_80`, type `ItemTxt__u_80`; `D2Structs.h:511` |
| 0x080 | 0x4 | `DWORD` | ↳ `dwCode` |  | C: `u_80.dwCode`; `D2Structs.h:512` |
| 0x080 | 0x4 | `char[4]` | ↳ `szCode` |  | C: `u_80.szCode`; `D2Structs.h:513` |
| 0x084 | 0x70 | `BYTE[0x70]` | `_2` | 0x84 | unknown; `D2Structs.h:515` |
| 0x0F4 | 0x2 | `WORD` | `nLocaleTxtNo` | 0xF4 | `D2Structs.h:516` |
| 0x0F6 | 0x19 | `BYTE[0x19]` | `_2a` | 0xF7 | **DISCREPANCY**: comment says 0xF7, computed 0xF6; unknown; `D2Structs.h:517` |
| 0x10F | 0x1 | `BYTE` | `xSize` | 0xFC | **DISCREPANCY**: comment says 0xFC, computed 0x10F; `D2Structs.h:518` |
| 0x110 | 0x1 | `BYTE` | `ySize` | 0xFD | **DISCREPANCY**: comment says 0xFD, computed 0x110; `D2Structs.h:519` |
| 0x111 | 0xD | `BYTE[13]` | `_2b` | 0xFE | **DISCREPANCY**: comment says 0xFE, computed 0x111; unknown; `D2Structs.h:520` |
| 0x11E | 0x1 | `BYTE` | `nType` | 0x11E | `D2Structs.h:521` |
| 0x11F | 0xD | `BYTE[0x0d]` | `_3` | 0x11F | unknown; `D2Structs.h:522` |
| 0x12C | 0x1 | `BYTE` | `fQuest` | 0x12A | **DISCREPANCY**: comment says 0x12A, computed 0x12C; `D2Structs.h:523` |
| 0x12D | 0x3 | | (padding) | | tail padding to align 4 |

### Inventory

`D2Structs.h:433-444` · sizeof **0x2C** (44) · align 4 · packing default (/Zp8)

D2Ptrs.h: 2 symbols use it: `D2CLIENT_LeftClickItem_I` (param), `D2COMMON_GetItemFromInventory` (param).

Named in 3 other source files: `D2Helpers.cpp`, `D2Helpers.h`, `JSGame.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwSignature` | 0x00 | `D2Structs.h:434` |
| 0x004 | 0x4 | `BYTE*` | `bGame1C` | 0x04 | `D2Structs.h:435` |
| 0x008 | 0x4 | `UnitAny*` | `pOwner` | 0x08 | `D2Structs.h:436` |
| 0x00C | 0x4 | `UnitAny*` | `pFirstItem` | 0x0C | `D2Structs.h:437` |
| 0x010 | 0x4 | `UnitAny*` | `pLastItem` | 0x10 | `D2Structs.h:438` |
| 0x014 | 0x8 | `DWORD[2]` | `_1` | 0x14 | unknown; `D2Structs.h:439` |
| 0x01C | 0x4 | `DWORD` | `dwLeftItemUid` | 0x1C | `D2Structs.h:440` |
| 0x020 | 0x4 | `UnitAny*` | `pCursorItem` | 0x20 | `D2Structs.h:441` |
| 0x024 | 0x4 | `DWORD` | `dwOwnerId` | 0x24 | `D2Structs.h:442` |
| 0x028 | 0x4 | `DWORD` | `dwItemCount` | 0x28 | `D2Structs.h:443` |

### InventoryInfo

`D2Structs.h:26-30` · sizeof **0xC** (12) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `int` | `nLocation` |  | `D2Structs.h:27` |
| 0x004 | 0x4 | `int` | `nMaxXCells` |  | `D2Structs.h:28` |
| 0x008 | 0x4 | `int` | `nMaxYCells` |  | `D2Structs.h:29` |

### InventoryLayout

`D2Structs.h:732-743` · sizeof **0x18** (24) · align 4 · packing default (/Zp8)

D2Ptrs.h: 7 symbols use it: `D2CLIENT_LeftClickItem_I` (param), `p_D2CLIENT_TradeLayout` (var), `p_D2CLIENT_StashLayout` (var), `p_D2CLIENT_StoreLayout` (var), `p_D2CLIENT_CubeLayout` (var), `p_D2CLIENT_InventoryLayout` (var), `p_D2CLIENT_MercLayout` (var).

Named in 3 other source files: `D2Helpers.cpp`, `D2Helpers.h`, `JSGame.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x1 | `BYTE` | `SlotWidth` |  | `D2Structs.h:733` |
| 0x001 | 0x1 | `BYTE` | `SlotHeight` |  | `D2Structs.h:734` |
| 0x002 | 0x1 | `BYTE` | `unk1` |  | unknown; `D2Structs.h:735` |
| 0x003 | 0x1 | `BYTE` | `unk2` |  | unknown; `D2Structs.h:736` |
| 0x004 | 0x4 | `DWORD` | `Left` |  | `D2Structs.h:737` |
| 0x008 | 0x4 | `DWORD` | `Right` |  | `D2Structs.h:738` |
| 0x00C | 0x4 | `DWORD` | `Top` |  | `D2Structs.h:739` |
| 0x010 | 0x4 | `DWORD` | `Bottom` |  | `D2Structs.h:740` |
| 0x014 | 0x1 | `BYTE` | `SlotPixelWidth` |  | `D2Structs.h:741` |
| 0x015 | 0x1 | `BYTE` | `SlotPixelHeight` |  | `D2Structs.h:742` |
| 0x016 | 0x2 | | (padding) | | tail padding to align 4 |

## Rooms, levels, acts & collision

### Act

`D2Structs.h:359-366` · sizeof **0x4C** (76) · align 4 · packing default (/Zp8)

D2Ptrs.h: 5 symbols use it: `D2COMMON_UnloadAct` (param), `D2COMMON_LoadAct` (ret), `D2COMMON_AddRoomData` (param), `D2COMMON_RemoveRoomData` (param), `D2COMMON_FindRoom1` (param).

Named in 2 other source files: `Map/Diablo_II/ActMap.h`, `Map/Diablo_II/LevelMap.h`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0xC | `DWORD[3]` | `_1` | 0x00 | unknown; `D2Structs.h:360` |
| 0x00C | 0x4 | `DWORD` | `dwMapSeed` | 0x0C | `D2Structs.h:361` |
| 0x010 | 0x4 | `Room1*` | `pRoom1` | 0x10 | `D2Structs.h:362` |
| 0x014 | 0x4 | `DWORD` | `dwAct` | 0x14 | `D2Structs.h:363` |
| 0x018 | 0x30 | `DWORD[12]` | `_2` | 0x18 | unknown; `D2Structs.h:364` |
| 0x048 | 0x4 | `ActMisc*` | `pMisc` | 0x48 | `D2Structs.h:365` |

### ActMisc

`D2Structs.h:350-357` · sizeof **0x480** (1152) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetLevel` (param).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x94 | `DWORD[37]` | `_1` | 0x00 | unknown; `D2Structs.h:351` |
| 0x094 | 0x4 | `DWORD` | `dwStaffTombLevel` | 0x94 | `D2Structs.h:352` |
| 0x098 | 0x3D4 | `DWORD[245]` | `_2` | 0x98 | unknown; `D2Structs.h:353` |
| 0x46C | 0x4 | `Act*` | `pAct` | 0x46C | `D2Structs.h:354` |
| 0x470 | 0xC | `DWORD[3]` | `_3` | 0x470 | unknown; `D2Structs.h:355` |
| 0x47C | 0x4 | `Level*` | `pLevelFirst` | 0x47C | `D2Structs.h:356` |

### Level

`D2Structs.h:279-303` · sizeof **0x22C** (556) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

D2Ptrs.h: 2 symbols use it: `D2COMMON_InitLevel` (param), `D2COMMON_GetLevel` (ret).

Named in 10 other source files: `D2Helpers.cpp`, `D2Helpers.h`, `JSArea.cpp`, `JSGame.cpp`, `JSPresetUnit.cpp`, `JSRoom.cpp`, `Map/Diablo_II/ActMap.cpp`, `Map/Diablo_II/ActMap.h`, `Map/Diablo_II/LevelMap.cpp`, `Map/Diablo_II/LevelMap.h`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x10 | `DWORD[4]` | `_1` | 0x00 | unknown; `D2Structs.h:280` |
| 0x010 | 0x4 | `Room2*` | `pRoom2First` | 0x10 | `D2Structs.h:281` |
| 0x014 | 0x8 | `DWORD[2]` | `_2` | 0x14 | unknown; `D2Structs.h:282` |
| 0x01C | 0x4 | `DWORD` | `dwPosX` | 0x1C | `D2Structs.h:283` |
| 0x020 | 0x4 | `DWORD` | `dwPosY` | 0x20 | `D2Structs.h:284` |
| 0x024 | 0x4 | `DWORD` | `dwSizeX` | 0x24 | `D2Structs.h:285` |
| 0x028 | 0x4 | `DWORD` | `dwSizeY` | 0x28 | `D2Structs.h:286` |
| 0x02C | 0x180 | `DWORD[96]` | `_3` | 0x2C | unknown; `D2Structs.h:287` |
| 0x1AC | 0x4 | `Level*` | `pNextLevel` | 0x1AC | `D2Structs.h:288` |
| 0x1B0 | 0x4 | `DWORD` | `_4` | 0x1B0 | unknown; `D2Structs.h:289` |
| 0x1B4 | 0x4 | `ActMisc*` | `pMisc` | 0x1B4 | `D2Structs.h:290` |
| 0x1B8 | 0x18 | `DWORD[6]` | `_5` | 0x1BC | **DISCREPANCY**: comment says 0x1BC, computed 0x1B8; unknown; `D2Structs.h:291` |
| 0x1D0 | 0x4 | `DWORD` | `dwLevelNo` | 0x1D0 | `D2Structs.h:292` |
| 0x1D4 | 0xC | `DWORD[3]` | `_6` | 0x1D4 | unknown; `D2Structs.h:293` |
| 0x1E0 | 0x24 | union (anonymous) | (anonymous union) | 0x1E0 | C: member `u_1E0`, type `Level__u_1E0`; `D2Structs.h:294` |
| 0x1E0 | 0x24 | `DWORD[9]` | ↳ `RoomCenterX` |  | C: `u_1E0.RoomCenterX`; `D2Structs.h:295` |
| 0x1E0 | 0x24 | `DWORD[9]` | ↳ `WarpX` |  | C: `u_1E0.WarpX`; `D2Structs.h:296` |
| 0x204 | 0x24 | union (anonymous) | (anonymous union) | 0x204 | C: member `u_204`, type `Level__u_204`; `D2Structs.h:298` |
| 0x204 | 0x24 | `DWORD[9]` | ↳ `RoomCenterY` |  | C: `u_204.RoomCenterY`; `D2Structs.h:299` |
| 0x204 | 0x24 | `DWORD[9]` | ↳ `WarpY` |  | C: `u_204.WarpY`; `D2Structs.h:300` |
| 0x228 | 0x4 | `DWORD` | `dwRoomEntries` | 0x228 | `D2Structs.h:302` |

### Room2

`D2Structs.h:305-328` · sizeof **0x60** (96) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

Named in 12 other source files: `D2Helpers.cpp`, `D2Helpers.h`, `JSGame.cpp`, `JSPresetUnit.cpp`, `JSRoom.cpp`, `Map/Diablo_II/ActMap.cpp`, `Map/Diablo_II/ActMap.h`, `Map/Diablo_II/LevelMap.cpp`, `Map/Diablo_II/LevelMap.h`, `Room.cpp`, `Room.h`, `Unit.cpp`.

> `pType2Info` points to an anonymous struct in the source; the header names it `Room2__pType2Info_t`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x8 | `DWORD[2]` | `_1` | 0x00 | unknown; `D2Structs.h:306` |
| 0x008 | 0x4 | `Room2**` | `pRoom2Near` | 0x08 | `D2Structs.h:307` |
| 0x00C | 0x14 | `DWORD[5]` | `_2` | 0x0C | unknown; `D2Structs.h:308` |
| 0x020 | 0x4 | `struct {...}*` | `pType2Info` | 0x20 | C type: `Room2__pType2Info_t*`; `D2Structs.h:313` |
| 0x024 | 0x4 | `Room2*` | `pRoom2Next` | 0x24 | `D2Structs.h:314` |
| 0x028 | 0x4 | `DWORD` | `dwRoomFlags` | 0x28 | `D2Structs.h:315` |
| 0x02C | 0x4 | `DWORD` | `dwRoomsNear` | 0x2C | `D2Structs.h:316` |
| 0x030 | 0x4 | `Room1*` | `pRoom1` | 0x30 | `D2Structs.h:317` |
| 0x034 | 0x4 | `DWORD` | `dwPosX` | 0x34 | `D2Structs.h:318` |
| 0x038 | 0x4 | `DWORD` | `dwPosY` | 0x38 | `D2Structs.h:319` |
| 0x03C | 0x4 | `DWORD` | `dwSizeX` | 0x3C | `D2Structs.h:320` |
| 0x040 | 0x4 | `DWORD` | `dwSizeY` | 0x40 | `D2Structs.h:321` |
| 0x044 | 0x4 | `DWORD` | `_3` | 0x44 | unknown; `D2Structs.h:322` |
| 0x048 | 0x4 | `DWORD` | `dwPresetType` | 0x48 | `D2Structs.h:323` |
| 0x04C | 0x4 | `RoomTile*` | `pRoomTiles` | 0x4C | `D2Structs.h:324` |
| 0x050 | 0x8 | `DWORD[2]` | `_4` | 0x50 | unknown; `D2Structs.h:325` |
| 0x058 | 0x4 | `Level*` | `pLevel` | 0x58 | `D2Structs.h:326` |
| 0x05C | 0x4 | `PresetUnit*` | `pPreset` | 0x5C | `D2Structs.h:327` |

### Room2__pType2Info_t

Anonymous struct in the source, reached through `Room2.pType2Info` (`D2Structs.h:309`).

`D2Structs.h:309-313` · sizeof **0xC** (12) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwRoomNumber` | 0x00 | `D2Structs.h:310` |
| 0x004 | 0x4 | `DWORD` | `_1` | 0x04 | unknown; `D2Structs.h:311` |
| 0x008 | 0x4 | `DWORD*` | `pdwSubNumber` | 0x08 | `D2Structs.h:312` |

### Room1

`D2Structs.h:332-348` · sizeof **0x80** (128) · align 4 · packing default (/Zp8)

D2Ptrs.h: 6 symbols use it: `D2CLIENT_RevealAutomapRoom` (param), `D2COMMON_GetRoomFromUnit` (ret), `D2COMMON_AddRoomData` (param), `D2COMMON_RemoveRoomData` (param), `D2COMMON_GetLevelNoFromRoom` (param), `D2COMMON_FindRoom1` (ret).

Named in 6 other source files: `D2Helpers.cpp`, `JSRoom.cpp`, `JSUnit.cpp`, `Map/Diablo_II/LevelMap.cpp`, `Map/Diablo_II/LevelMap.h`, `Unit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `Room1**` | `pRoomsNear` | 0x00 | `D2Structs.h:333` |
| 0x004 | 0xC | `DWORD[3]` | `_1` | 0x04 | unknown; `D2Structs.h:334` |
| 0x010 | 0x4 | `Room2*` | `pRoom2` | 0x10 | `D2Structs.h:335` |
| 0x014 | 0xC | `DWORD[3]` | `_2` | 0x14 | unknown; `D2Structs.h:336` |
| 0x020 | 0x4 | `CollMap*` | `Coll` | 0x20 | `D2Structs.h:337` |
| 0x024 | 0x4 | `DWORD` | `dwRoomsNear` | 0x24 | `D2Structs.h:338` |
| 0x028 | 0x24 | `DWORD[9]` | `_3` | 0x28 | unknown; `D2Structs.h:339` |
| 0x04C | 0x4 | `DWORD` | `dwXStart` | 0x4C | `D2Structs.h:340` |
| 0x050 | 0x4 | `DWORD` | `dwYStart` | 0x50 | `D2Structs.h:341` |
| 0x054 | 0x4 | `DWORD` | `dwXSize` | 0x54 | `D2Structs.h:342` |
| 0x058 | 0x4 | `DWORD` | `dwYSize` | 0x58 | `D2Structs.h:343` |
| 0x05C | 0x18 | `DWORD[6]` | `_4` | 0x5C | unknown; `D2Structs.h:344` |
| 0x074 | 0x4 | `UnitAny*` | `pUnitFirst` | 0x74 | `D2Structs.h:345` |
| 0x078 | 0x4 | `DWORD` | `_5` | 0x78 | unknown; `D2Structs.h:346` |
| 0x07C | 0x4 | `Room1*` | `pRoomNext` | 0x7C | `D2Structs.h:347` |

### RoomTile

`D2Structs.h:209-214` · sizeof **0x14** (20) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `Room2*` | `pRoom2` | 0x00 | `D2Structs.h:210` |
| 0x004 | 0x4 | `RoomTile*` | `pNext` | 0x04 | `D2Structs.h:211` |
| 0x008 | 0x8 | `DWORD[2]` | `_2` | 0x08 | unknown; `D2Structs.h:212` |
| 0x010 | 0x4 | `DWORD*` | `nNum` | 0x10 | `D2Structs.h:213` |

### CollMap

`D2Structs.h:256-267` · sizeof **0x28** (40) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

Named in 3 other source files: `JSRoom.cpp`, `Map/Diablo_II/ActMap.cpp`, `Map/Diablo_II/LevelMap.cpp`.

> Collision words are indexed as `pMapStart[(y - dwPosGameY) * dwSizeGameX + (x - dwPosGameX)]` (`Map/Diablo_II/ActMap.cpp:178`); flag bits are the `CollisionFlag` enum (`Map/Diablo_II/ActMap.h:45`).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwPosGameX` | 0x00 | `D2Structs.h:257` |
| 0x004 | 0x4 | `DWORD` | `dwPosGameY` | 0x04 | `D2Structs.h:258` |
| 0x008 | 0x4 | `DWORD` | `dwSizeGameX` | 0x08 | `D2Structs.h:259` |
| 0x00C | 0x4 | `DWORD` | `dwSizeGameY` | 0x0C | `D2Structs.h:260` |
| 0x010 | 0x4 | `DWORD` | `dwPosRoomX` | 0x10 | `D2Structs.h:261` |
| 0x014 | 0x4 | `DWORD` | `dwPosRoomY` | 0x14 | `D2Structs.h:262` |
| 0x018 | 0x4 | `DWORD` | `dwSizeRoomX` | 0x18 | `D2Structs.h:263` |
| 0x01C | 0x4 | `DWORD` | `dwSizeRoomY` | 0x1C | `D2Structs.h:264` |
| 0x020 | 0x4 | `WORD*` | `pMapStart` | 0x20 | `D2Structs.h:265` |
| 0x024 | 0x4 | `WORD*` | `pMapEnd` | 0x22 | **DISCREPANCY**: comment says 0x22, computed 0x24; `D2Structs.h:266` |

### PresetUnit

`D2Structs.h:269-277` · sizeof **0x1C** (28) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

Named in 5 other source files: `JSPresetUnit.cpp`, `JSRoom.cpp`, `Map/Diablo_II/ActMap.cpp`, `Map/Diablo_II/LevelMap.cpp`, `Room.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `_1` | 0x00 | unknown; `D2Structs.h:270` |
| 0x004 | 0x4 | `DWORD` | `dwTxtFileNo` | 0x04 | `D2Structs.h:271` |
| 0x008 | 0x4 | `DWORD` | `dwPosX` | 0x08 | `D2Structs.h:272` |
| 0x00C | 0x4 | `PresetUnit*` | `pPresetNext` | 0x0C | `D2Structs.h:273` |
| 0x010 | 0x4 | `DWORD` | `_3` | 0x10 | unknown; `D2Structs.h:274` |
| 0x014 | 0x4 | `DWORD` | `dwType` | 0x14 | `D2Structs.h:275` |
| 0x018 | 0x4 | `DWORD` | `dwPosY` | 0x18 | `D2Structs.h:276` |

### LevelTxt

`D2Structs.h:111-122` · sizeof **0x220** (544) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetLevelText` (ret).

Named in 1 other source file: `JSArea.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwLevelNo` | 0x00 | `D2Structs.h:112` |
| 0x004 | 0xF0 | `DWORD[60]` | `_1` | 0x04 | unknown; `D2Structs.h:113` |
| 0x0F4 | 0x1 | `BYTE` | `_2` | 0xF4 | unknown; `D2Structs.h:114` |
| 0x0F5 | 0x28 | `char[40]` | `szName` | 0xF5 | `D2Structs.h:115` |
| 0x11D | 0x28 | `char[40]` | `szEntranceText` | 0x11D | `D2Structs.h:116` |
| 0x145 | 0x29 | `char[41]` | `szLevelDesc` | 0x145 | `D2Structs.h:117` |
| 0x16E | 0x50 | `wchar_t[40]` | `wName` | 0x16E | `D2Structs.h:118` |
| 0x1BE | 0x50 | `wchar_t[40]` | `wEntranceText` | 0x1BE | `D2Structs.h:119` |
| 0x20E | 0x8 | `BYTE[8]` | `nObjGroup` | 0x196 | **DISCREPANCY**: comment says 0x196, computed 0x20E; `D2Structs.h:120` |
| 0x216 | 0x8 | `BYTE[8]` | `nObjPrb` | 0x19E | **DISCREPANCY**: comment says 0x19E, computed 0x216; `D2Structs.h:121` |
| 0x21E | 0x2 | | (padding) | | tail padding to align 4 |

## Skills & stats

### Info

`D2Structs.h:469-474` · sizeof **0x10** (16) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `BYTE*` | `pGame1C` | 0x00 | `D2Structs.h:470` |
| 0x004 | 0x4 | `Skill*` | `pFirstSkill` | 0x04 | `D2Structs.h:471` |
| 0x008 | 0x4 | `Skill*` | `pLeftSkill` | 0x08 | `D2Structs.h:472` |
| 0x00C | 0x4 | `Skill*` | `pRightSkill` | 0x0C | `D2Structs.h:473` |

### Skill

`D2Structs.h:458-467` · sizeof **0x40** (64) (source comment: 0x40) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetSkillLevel` (param).

Named in 2 other source files: `D2Helpers.cpp`, `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `SkillInfo*` | `pSkillInfo` | 0x00 | `D2Structs.h:459` |
| 0x004 | 0x4 | `Skill*` | `pNextSkill` | 0x04 | `D2Structs.h:460` |
| 0x008 | 0x20 | `DWORD[8]` | `_1` | 0x08 | unknown; `D2Structs.h:461` |
| 0x028 | 0x4 | `DWORD` | `dwSkillLevel` | 0x28 | `D2Structs.h:462` |
| 0x02C | 0x8 | `DWORD[2]` | `_2` | 0x2C | unknown; `D2Structs.h:463` |
| 0x034 | 0x4 | `DWORD` | `ItemId` | 0x34 0xFFFFFFFF if not a charge | `D2Structs.h:464` |
| 0x038 | 0x4 | `DWORD` | `ChargesLeft` | 0x38 | `D2Structs.h:465` |
| 0x03C | 0x4 | `DWORD` | `IsCharge` | 0x3C 1 for charge, else 0 | `D2Structs.h:466` |

### SkillInfo

`D2Structs.h:454-456` · sizeof **0x2** (2) · align 2 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x2 | `WORD` | `wSkillId` | 0x00 | `D2Structs.h:455` |

### StatList

`D2Structs.h:413-431` · sizeof **0x70** (112) · align 4 · packing default (/Zp8)

D2Ptrs.h: 2 symbols use it: `D2COMMON_GetStatList` (ret), `D2COMMON_CopyStatList` (param).

Named in 1 other source file: `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `_1` | 0x00 | unknown; `D2Structs.h:414` |
| 0x004 | 0x4 | `UnitAny*` | `pUnit` | 0x04 | `D2Structs.h:415` |
| 0x008 | 0x4 | `DWORD` | `dwUnitType` | 0x08 | `D2Structs.h:416` |
| 0x00C | 0x4 | `DWORD` | `dwUnitId` | 0x0C | `D2Structs.h:417` |
| 0x010 | 0x4 | `DWORD` | `dwFlags` | 0x10 | `D2Structs.h:418` |
| 0x014 | 0x10 | `DWORD[4]` | `_2` | 0x14 | unknown; `D2Structs.h:419` |
| 0x024 | 0x8 | `StatVector` | `StatVec` | 0x24 | `D2Structs.h:420` |
| 0x02C | 0x4 | `StatList*` | `pPrevLink` | 0x2C | `D2Structs.h:421` |
| 0x030 | 0x4 | `DWORD` | `_3` | 0x30 | unknown; `D2Structs.h:422` |
| 0x034 | 0x4 | `StatList*` | `pPrev` | 0x34 | `D2Structs.h:423` |
| 0x038 | 0x4 | `DWORD` | `_4` | 0x38 | unknown; `D2Structs.h:424` |
| 0x03C | 0x4 | `StatList*` | `pNext` | 0x3C | `D2Structs.h:425` |
| 0x040 | 0x4 | `StatList*` | `pSetList` | 0x40 | `D2Structs.h:426` |
| 0x044 | 0x4 | `DWORD` | `_5` | 0x44 | unknown; `D2Structs.h:427` |
| 0x048 | 0x8 | `StatVector` | `SetStatVec` | 0x48 | `D2Structs.h:428` |
| 0x050 | 0x8 | `DWORD[2]` | `_6` | 0x50 | unknown; `D2Structs.h:429` |
| 0x058 | 0x18 | `DWORD[6]` | `StateBits` | 0x58 | `D2Structs.h:430` |

### StatVector

`D2Structs.h:406-410` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `Stat*` | `pStats` |  | `D2Structs.h:407` |
| 0x004 | 0x2 | `WORD` | `wCount` |  | `D2Structs.h:408` |
| 0x006 | 0x2 | `WORD` | `wSize` |  | `D2Structs.h:409` |

### Stat

`D2Structs.h:400-404` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_CopyStatList` (param).

Named in 1 other source file: `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x2 | `WORD` | `wSubIndex` | 0x00 | `D2Structs.h:401` |
| 0x002 | 0x2 | `WORD` | `wStatIndex` | 0x02 | `D2Structs.h:402` |
| 0x004 | 0x4 | `DWORD` | `dwStatValue` | 0x04 | `D2Structs.h:403` |

## UI, controls, automap & graphics

### Control

`D2Structs.h:132-168` · sizeof **0x264** (612) · align 4 · packing default (/Zp8)

D2Ptrs.h: 9 symbols use it: `p_D2MULTI_GameListControl` (var), `D2WIN_SetControlText` (param), `D2WIN_DestroyEditBox` (param), `D2WIN_DestroyControl` (param), `D2WIN_SetEditBoxCallback` (param), `D2WIN_SetEditBoxProc` (param), `D2WIN_SelectEditBoxText` (param), `p_D2WIN_FirstControl` (var), `p_D2WIN_FocusedControl` (var).

Named in 6 other source files: `Control.cpp`, `Control.h`, `D2Helpers.cpp`, `JSControl.cpp`, `JSControl.h`, `Profile.cpp`.

> The +0x5C union holds a textbox layout (`wText`, cursor, cloak flag) and a button layout (`_12`, `wText2`); C names `u_5C.s_5C.*` / `u_5C.s_5C_1.*`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwType` | 0x00 | `D2Structs.h:133` |
| 0x004 | 0x4 | `DWORD*` | `_1` | 0x04 // unsure? definitely a ptr but not obvious, usually points to 6 when dwType is 6 I think | unknown; `D2Structs.h:134` |
| 0x008 | 0x4 | `DWORD` | `dwDisabled` | 0x08 | `D2Structs.h:135` |
| 0x00C | 0x4 | `DWORD` | `dwPosX` | 0x0C | `D2Structs.h:136` |
| 0x010 | 0x4 | `DWORD` | `dwPosY` | 0x10 | `D2Structs.h:137` |
| 0x014 | 0x4 | `DWORD` | `dwSizeX` | 0x14 | `D2Structs.h:138` |
| 0x018 | 0x4 | `DWORD` | `dwSizeY` | 0x18 | `D2Structs.h:139` |
| 0x01C | 0x4 | `DWORD*` | `_2` | 0x1C // some sort of function (maybe click?) | unknown; `D2Structs.h:141` |
| 0x020 | 0x4 | `DWORD` | `_3` | 0x20 | unknown; `D2Structs.h:142` |
| 0x024 | 0x4 | `DWORD*` | `_4` | 0x24 // some sort of function | unknown; `D2Structs.h:143` |
| 0x028 | 0x4 | `DWORD*` | `_5` | 0x28 | unknown; `D2Structs.h:144` |
| 0x02C | 0x4 | `DWORD` | `_6` | 0x2C | unknown; `D2Structs.h:145` |
| 0x030 | 0x4 | `DWORD*` | `_7` | 0x30 // ptr to something... | unknown; `D2Structs.h:146` |
| 0x034 | 0x4 | `DWORD*` | `_8` | 0x34 // another random ptr... mostly dead ends when I examined them | unknown; `D2Structs.h:147` |
| 0x038 | 0x4 | `DWORD` | `_9` | 0x38 | unknown; `D2Structs.h:148` |
| 0x03C | 0x4 | `Control*` | `pNext` | 0x3C | `D2Structs.h:149` |
| 0x040 | 0x4 | `DWORD` | `_10` | 0x40 | unknown; `D2Structs.h:150` |
| 0x044 | 0x4 | `DWORD` | `unkState` | 0x44 _11 0 when button avail to be clicked 1 when greyed - still need to look at this more | unknown; `D2Structs.h:151` |
| 0x048 | 0x4 | `ControlText*` | `pFirstText` | 0x48 | `D2Structs.h:152` |
| 0x04C | 0x4 | `ControlText*` | `pLastText` | 0x4C | `D2Structs.h:153` |
| 0x050 | 0x4 | `ControlText*` | `pSelectedText` | 0x50 | `D2Structs.h:154` |
| 0x054 | 0x4 | `DWORD` | `dwSelectEnd` | 0x54 | `D2Structs.h:155` |
| 0x058 | 0x4 | `DWORD` | `dwSelectStart` | 0x58 | `D2Structs.h:156` |
| 0x05C | 0x208 | union (anonymous) | (anonymous union) |  | C: member `u_5C`, type `Control__u_5C`; `D2Structs.h:157` |
| 0x05C | 0x208 | struct (anonymous) | ↳ (anonymous struct) | Textboxes | C: member `s_5C`, type `Control__u_5C__s_5C`; `D2Structs.h:158` |
| 0x05C | 0x200 | `wchar_t[256]` | ↳ ↳ `wText` | 0x5C | C: `u_5C.s_5C.wText`; `D2Structs.h:159` |
| 0x25C | 0x4 | `DWORD` | ↳ ↳ `dwCursorPos` |  | C: `u_5C.s_5C.dwCursorPos`; `D2Structs.h:160` |
| 0x260 | 0x4 | `DWORD` | ↳ ↳ `dwIsCloaked` |  | C: `u_5C.s_5C.dwIsCloaked`; `D2Structs.h:161` |
| 0x05C | 0x208 | struct (anonymous) | ↳ (anonymous struct) | Buttons | C: member `s_5C_1`, type `Control__u_5C__s_5C_1`; `D2Structs.h:163` |
| 0x05C | 0x8 | `DWORD[2]` | ↳ ↳ `_12` | 0x5C | unknown; C: `u_5C.s_5C_1._12`; `D2Structs.h:164` |
| 0x064 | 0x200 | `wchar_t[256]` | ↳ ↳ `wText2` | 0x6C | **DISCREPANCY**: comment says 0x6C, computed 0x64; C: `u_5C.s_5C_1.wText2`; `D2Structs.h:165` |

### ControlText

`D2Structs.h:124-130` · sizeof **0x20** (32) (source comment: 0x20) · align 4 · packing default (/Zp8)

Named in 2 other source files: `Control.cpp`, `JSControl.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x14 | `wchar_t*[5]` | `wText` | 0x00 for each field | `D2Structs.h:126` |
| 0x014 | 0x4 | `DWORD` | `dwColor` | 0x14 | `D2Structs.h:127` |
| 0x018 | 0x4 | `DWORD` | `dwAlign` | 0x18 | `D2Structs.h:128` |
| 0x01C | 0x4 | `ControlText*` | `pNext` | 0x1C | `D2Structs.h:129` |

### NPCMenu

`D2Structs.h:703-716` · sizeof **0x27** (39) · align 1 · packing pack(1) (set at `D2Structs.h:701`)

D2Ptrs.h: 1 symbol uses it: `p_D2CLIENT_NPCMenu` (var).

Named in 1 other source file: `D2Helpers.cpp`.

> pack(1) changes this layout (see Packing). D2BS steps through an array of these by `sizeof(NPCMenu)` (`D2Helpers.cpp:449`), so sizeof matters. It casts `p_D2CLIENT_NPCMenu`, the address of the global, to `NPCMenu*` (`D2Helpers.cpp:414`), so it treats the global itself as the first element. The declared VARPTR type `NPCMenu*` (`D2Ptrs.h:168`) would instead mean a pointer stored there. The fields have no offset comments.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwNPCClassId` |  | `D2Structs.h:704` |
| 0x004 | 0x4 | `DWORD` | `dwEntryAmount` |  | `D2Structs.h:705` |
| 0x008 | 0x2 | `WORD` | `wEntryId1` |  | `D2Structs.h:706` |
| 0x00A | 0x2 | `WORD` | `wEntryId2` |  | `D2Structs.h:707` |
| 0x00C | 0x2 | `WORD` | `wEntryId3` |  | `D2Structs.h:708` |
| 0x00E | 0x2 | `WORD` | `wEntryId4` |  | `D2Structs.h:709` |
| 0x010 | 0x2 | `WORD` | `_1` |  | unknown; `D2Structs.h:710` |
| 0x012 | 0x4 | `DWORD` | `dwEntryFunc1` |  | `D2Structs.h:711` |
| 0x016 | 0x4 | `DWORD` | `dwEntryFunc2` |  | `D2Structs.h:712` |
| 0x01A | 0x4 | `DWORD` | `dwEntryFunc3` |  | `D2Structs.h:713` |
| 0x01E | 0x4 | `DWORD` | `dwEntryFunc4` |  | `D2Structs.h:714` |
| 0x022 | 0x5 | `BYTE[5]` | `_2` |  | unknown; `D2Structs.h:715` |

### TransactionDialogsInfo_t

`D2Structs.h:792-798` · sizeof **0xB0C** (2828) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `p_D2CLIENT_pTransactionDialogsInfo` (var).

Named in 1 other source file: `JSGame.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x50 | `DWORD[0x14]` | `unk` | 0x000 | unknown; `D2Structs.h:793` |
| 0x050 | 0x4 | `DWORD` | `numLines` | 0x050 | `D2Structs.h:794` |
| 0x054 | 0x14 | `DWORD[0x5]` | `unk_2` | 0x054 | unknown; `D2Structs.h:795` |
| 0x068 | 0xAA0 | `TransactionDialogsLine_t[10]` | `dialogLines` | 0x068 | `D2Structs.h:796` |
| 0xB08 | 0x4 | `void*` | `something` | 0xB08 | `D2Structs.h:797` |

### TransactionDialogsLine_t

`D2Structs.h:785-790` · sizeof **0x110** (272) · align 4 · packing default (/Zp8)

Named in 1 other source file: `JSGame.cpp`.

> Source warns the placement of `handler` is a guess (`D2Structs.h:782`).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0xF0 | `wchar_t[120]` | `text` | 0x000 | `D2Structs.h:786` |
| 0x0F0 | 0x18 | `DWORD[6]` | `unk` | 0x0F0 | unknown; `D2Structs.h:787` |
| 0x108 | 0x4 | `void(__stdcall *)()` | `handler` | 0x108 | `D2Structs.h:788` |
| 0x10C | 0x4 | `DWORD` | `bMaybeSelectable` | 0x10C | `D2Structs.h:789` |

### AutomapLayer

`D2Structs.h:96-104` · sizeof **0x1C** (28) · align 4 · packing default (/Zp8)

D2Ptrs.h: 3 symbols use it: `D2CLIENT_RevealAutomapRoom` (param), `D2CLIENT_InitAutomapLayer_I` (ret), `p_D2CLIENT_AutomapLayer` (var).

Named in 2 other source files: `D2Helpers.cpp`, `D2Helpers.h`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `nLayerNo` | 0x00 | `D2Structs.h:97` |
| 0x004 | 0x4 | `DWORD` | `fSaved` | 0x04 | `D2Structs.h:98` |
| 0x008 | 0x4 | `AutomapCell*` | `pFloors` | 0x08 | `D2Structs.h:99` |
| 0x00C | 0x4 | `AutomapCell*` | `pWalls` | 0x0C | `D2Structs.h:100` |
| 0x010 | 0x4 | `AutomapCell*` | `pObjects` | 0x10 | `D2Structs.h:101` |
| 0x014 | 0x4 | `AutomapCell*` | `pExtras` | 0x14 | `D2Structs.h:102` |
| 0x018 | 0x4 | `AutomapLayer*` | `pNextLayer` | 0x18 | `D2Structs.h:103` |

### AutomapLayer2

`D2Structs.h:106-109` · sizeof **0xC** (12) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2COMMON_GetLayer` (ret).

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x8 | `DWORD[2]` | `_1` | 0x00 | unknown; `D2Structs.h:107` |
| 0x008 | 0x4 | `DWORD` | `nLayerNo` | 0x08 | `D2Structs.h:108` |

### AutomapCell

`D2Structs.h:43-51` · sizeof **0x14** (20) · align 4 · packing default (/Zp8)

D2Ptrs.h: 2 symbols use it: `D2CLIENT_NewAutomapCell` (ret), `D2CLIENT_AddAutomapCell` (param).

Named in 1 other source file: `Room.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `fSaved` | 0x00 | `D2Structs.h:44` |
| 0x004 | 0x2 | `WORD` | `nCellNo` | 0x04 | `D2Structs.h:45` |
| 0x006 | 0x2 | `WORD` | `xPixel` | 0x06 | `D2Structs.h:46` |
| 0x008 | 0x2 | `WORD` | `yPixel` | 0x08 | `D2Structs.h:47` |
| 0x00A | 0x2 | `WORD` | `wWeight` | 0x0A | `D2Structs.h:48` |
| 0x00C | 0x4 | `AutomapCell*` | `pLess` | 0x0C | `D2Structs.h:49` |
| 0x010 | 0x4 | `AutomapCell*` | `pMore` | 0x10 | `D2Structs.h:50` |

### CellFile

`D2Structs.h:76-88` · sizeof **0x414** (1044) · align 4 · packing default (/Zp8)

D2Ptrs.h: 3 symbols use it: `D2CMP_InitCellFile` (param), `D2CMP_DeleteCellFile` (param), `D2WIN_LoadCellFile` (ret).

Named in 4 other source files: `D2BS.h`, `D2Helpers.cpp`, `D2Helpers.h`, `ScreenHook.h`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwVersion` | 0x00 | `D2Structs.h:77` |
| 0x004 | 0x4 | struct (anonymous) | (anonymous struct) | 0x04 | C: flattened into the parent; `D2Structs.h:78` |
| 0x004 | 0x2 | `WORD` | ↳ `dwFlags` |  | `D2Structs.h:79` |
| 0x006 | 0x1 | `BYTE` | ↳ `mylastcol` |  | `D2Structs.h:80` |
| 0x007 | 0x1 | `BYTE : 1` | ↳ `mytabno` |  | bits 0..0; `D2Structs.h:81` |
| 0x008 | 0x4 | `DWORD` | `eFormat` | 0x08 | `D2Structs.h:83` |
| 0x00C | 0x4 | `DWORD` | `termination` | 0x0C | `D2Structs.h:84` |
| 0x010 | 0x4 | `DWORD` | `numdirs` | 0x10 | `D2Structs.h:85` |
| 0x014 | 0x4 | `DWORD` | `numcells` | 0x14 | `D2Structs.h:86` |
| 0x018 | 0x3FC | `GfxCell*[255]` | `cells` | 0x18 | `D2Structs.h:87` |

### CellContext

`D2Structs.h:90-94` · sizeof **0x48** (72) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `D2GFX_DrawAutomapCell2` (param).

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x34 | `DWORD[13]` | `_1` | 0x00 | unknown; `D2Structs.h:91` |
| 0x034 | 0x4 | `CellFile*` | `pCellFile` | 0x34 | `D2Structs.h:92` |
| 0x038 | 0x10 | `DWORD[4]` | `_2` | 0x38 | unknown; `D2Structs.h:93` |

### GfxCell

`D2Structs.h:53-63` · sizeof **0x24** (36) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `flags` | 0x00 | `D2Structs.h:54` |
| 0x004 | 0x4 | `DWORD` | `width` | 0x04 | `D2Structs.h:55` |
| 0x008 | 0x4 | `DWORD` | `height` | 0x08 | `D2Structs.h:56` |
| 0x00C | 0x4 | `DWORD` | `xoffs` | 0x0C | `D2Structs.h:57` |
| 0x010 | 0x4 | `DWORD` | `yoffs` | 0x10 | `D2Structs.h:58` |
| 0x014 | 0x4 | `DWORD` | `_2` | 0x14 | unknown; `D2Structs.h:59` |
| 0x018 | 0x4 | `DWORD` | `lpParent` | 0x18 | `D2Structs.h:60` |
| 0x01C | 0x4 | `DWORD` | `length` | 0x1C | `D2Structs.h:61` |
| 0x020 | 0x1 | `BYTE` | `cols` | 0x20 | `D2Structs.h:62` |
| 0x021 | 0x3 | | (padding) | | tail padding to align 4 |

### SplitText

`D2Structs.h:21-24` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `wchar_t*` | `lpwszText` |  | `D2Structs.h:22` |
| 0x004 | 0x4 | `SplitText*` | `lpsNext` |  | `D2Structs.h:23` |

### WindowHandlerHashTable

`D2Structs.h:769-772` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `p_STORM_WindowHandlers` (var).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `WindowHandlerList**` | `table` |  | `D2Structs.h:770` |
| 0x004 | 0x4 | `DWORD` | `length` |  | `D2Structs.h:771` |

### WindowHandlerList

`D2Structs.h:774-780` · sizeof **0x14** (20) · align 4 · packing default (/Zp8)

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `unk_0` |  | unknown; `D2Structs.h:775` |
| 0x004 | 0x4 | `HWND` | `hWnd` |  | `D2Structs.h:776` |
| 0x008 | 0x4 | `DWORD` | `unk_8` |  | unknown; `D2Structs.h:777` |
| 0x00C | 0x4 | `MessageHandlerHashTable*` | `msgHandlers` |  | `D2Structs.h:778` |
| 0x010 | 0x4 | `WindowHandlerList*` | `next` |  | `D2Structs.h:779` |

### MessageHandlerHashTable

`D2Structs.h:764-767` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `MessageHandlerList**` | `table` |  | `D2Structs.h:765` |
| 0x004 | 0x4 | `DWORD` | `length` |  | `D2Structs.h:766` |

### MessageHandlerList

`D2Structs.h:757-762` · sizeof **0x10** (16) · align 4 · packing default (/Zp8)

Named in 1 other source file: `D2Helpers.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `message` |  | `D2Structs.h:758` |
| 0x004 | 0x4 | `DWORD` | `unk_4` |  | unknown; `D2Structs.h:759` |
| 0x008 | 0x4 | `DWORD(__stdcall *)(void*)` | `handler` |  | `D2Structs.h:760` |
| 0x00C | 0x4 | `MessageHandlerList*` | `next` |  | `D2Structs.h:761` |

## Net & game info

### GameStructInfo

`D2Structs.h:32-41` · sizeof **0x25D** (605) · align 1 · packing default (/Zp8)

D2Ptrs.h: 1 symbol uses it: `p_D2CLIENT_GameInfo` (var).

Named in 1 other source file: `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x1F | `BYTE[0x1F]` | `_1` | 0x00 // was 0x1B | unknown; `D2Structs.h:33` |
| 0x01F | 0x18 | `char[0x18]` | `szGameName` | 0x1F | `D2Structs.h:34` |
| 0x037 | 0x56 | `char[0x56]` | `szGameServerIp` | 0x37 | `D2Structs.h:35` |
| 0x08D | 0x30 | `char[0x30]` | `szAccountName` | 0x8D | `D2Structs.h:36` |
| 0x0BD | 0x18 | `char[0x18]` | `szCharName` | 0xBD | `D2Structs.h:37` |
| 0x0D5 | 0x18 | `char[0x18]` | `szRealmName` | 0xD5 | `D2Structs.h:38` |
| 0x0ED | 0x158 | `BYTE[0x158]` | `_2` | 0xED | unknown; `D2Structs.h:39` |
| 0x245 | 0x18 | `char[0x18]` | `szGamePassword` | 0x245 | `D2Structs.h:40` |

### BnetData

`D2Structs.h:173-207` · sizeof **0x3C8** (968) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

D2Ptrs.h: 1 symbol uses it: `p_D2LAUNCH_BnData` (var).

Named in 3 other source files: `D2Handlers.cpp`, `JSGame.cpp`, `JSUnit.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `dwId` | 0x00 | `D2Structs.h:174` |
| 0x004 | 0x4 | `DWORD` | `dwId2` | 0x04 | `D2Structs.h:175` |
| 0x008 | 0x10 | `BYTE[0x10]` | `_1` | 0x08 | unknown; `D2Structs.h:176` |
| 0x018 | 0x4 | `DWORD` | `dwId3` | 0x18 | `D2Structs.h:177` |
| 0x01C | 0x2 | `WORD` | `Unk3` | 0x1C | unknown; `D2Structs.h:178` |
| 0x01E | 0x1 | `BYTE` | `_2` | 0x1E | unknown; `D2Structs.h:179` |
| 0x01F | 0x16 | `char[0x16]` | `szGameName` | 0x1F | `D2Structs.h:180` |
| 0x035 | 0x2 | `WORD` | `_3` | 0x35 | unknown; `D2Structs.h:181` |
| 0x037 | 0x10 | `char[0x10]` | `szGameIP` | 0x37 | `D2Structs.h:182` |
| 0x047 | 0x42 | `BYTE[0x42]` | `_5` | 0x47 | unknown; `D2Structs.h:183` |
| 0x089 | 0x4 | `DWORD` | `dwId4` | 0x89 | `D2Structs.h:184` |
| 0x08D | 0x30 | `char[0x30]` | `szAccountName` | 0x8D | `D2Structs.h:185` |
| 0x0BD | 0x18 | `char[0x18]` | `szPlayerName` | 0xBD | `D2Structs.h:186` |
| 0x0D5 | 0x8 | `char[0x08]` | `szRealmName` | 0xD5 | `D2Structs.h:187` |
| 0x0DD | 0x111 | `BYTE[0x111]` | `_8` | 0xDD | unknown; `D2Structs.h:188` |
| 0x1EE | 0x1 | `BYTE` | `nCharClass` | 0x1EE | `D2Structs.h:189` |
| 0x1EF | 0x1 | `BYTE` | `nCharFlags` | 0x1EF | `D2Structs.h:190` |
| 0x1F0 | 0x1 | `BYTE` | `nMaxDiff` | 0x1F0 | `D2Structs.h:191` |
| 0x1F1 | 0x1F | `BYTE[0x1F]` | `_9` | 0x1F1 | unknown; `D2Structs.h:192` |
| 0x210 | 0x1 | `BYTE` | `CreatedGameDifficulty` | 0x210 | `D2Structs.h:193` |
| 0x211 | 0x4 | `void*` | `_10` | 0x211 | unknown; `D2Structs.h:194` |
| 0x215 | 0x15 | `BYTE[0x15]` | `_11` | 0x215 | unknown; `D2Structs.h:195` |
| 0x22A | 0x2 | `WORD` | `_12` | 0x22A | unknown; `D2Structs.h:196` |
| 0x22C | 0x1 | `BYTE` | `_13` | 0x22C | unknown; `D2Structs.h:197` |
| 0x22D | 0x18 | `char[0x18]` | `szRealmName2` | 0x22D | `D2Structs.h:198` |
| 0x245 | 0x18 | `char[0x18]` | `szGamePass` | 0x245 | `D2Structs.h:199` |
| 0x25D | 0x104 | `char[0x104]` | `szGameDesc` | 0x25D | `D2Structs.h:200` |
| 0x361 | 0x20 | `char[0x20]` | `channelname` | +0x35f | **DISCREPANCY**: comment says 0x35F, computed 0x361; `D2Structs.h:201` |
| 0x381 | 0x40 | `BYTE[0x40]` | `_14` | +0x37f | **DISCREPANCY**: comment says 0x37F, computed 0x381; unknown; `D2Structs.h:202` |
| 0x3C1 | 0x1 | `BYTE` | `charlevel` | +0x3bf | **DISCREPANCY**: comment says 0x3BF, computed 0x3C1; `D2Structs.h:203` |
| 0x3C2 | 0x1 | `BYTE` | `ladderflag` | +0x3c0 | **DISCREPANCY**: comment says 0x3C0, computed 0x3C2; `D2Structs.h:204` |
| 0x3C3 | 0x4 | `DWORD` | `passhash` | +0x3c1 | **DISCREPANCY**: comment says 0x3C1, computed 0x3C3; `D2Structs.h:205` |
| 0x3C7 | 0x1 | `BYTE` | `passlength` | +0x3c5 | **DISCREPANCY**: comment says 0x3C5, computed 0x3C7; `D2Structs.h:206` |

### RosterUnit

`D2Structs.h:216-235` · sizeof **0x84** (132) · align 1 · packing pack(1) (set at `D2Structs.h:171`)

D2Ptrs.h: 1 symbol uses it: `p_D2CLIENT_PlayerUnitList` (var).

Named in 5 other source files: `D2Helpers.cpp`, `D2Helpers.h`, `D2NetHandlers.cpp`, `JSGame.cpp`, `JSParty.cpp`.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x10 | `char[16]` | `szName` | 0x00 | `D2Structs.h:217` |
| 0x010 | 0x4 | `DWORD` | `dwUnitId` | 0x10 | `D2Structs.h:218` |
| 0x014 | 0x4 | `DWORD` | `dwPartyLife` | 0x14 | `D2Structs.h:219` |
| 0x018 | 0x4 | `DWORD` | `_1` | 0x18 | unknown; `D2Structs.h:220` |
| 0x01C | 0x4 | `DWORD` | `dwClassId` | 0x1C | `D2Structs.h:221` |
| 0x020 | 0x2 | `WORD` | `wLevel` | 0x20 | `D2Structs.h:222` |
| 0x022 | 0x2 | `WORD` | `wPartyId` | 0x22 | `D2Structs.h:223` |
| 0x024 | 0x4 | `DWORD` | `dwLevelId` | 0x24 | `D2Structs.h:224` |
| 0x028 | 0x4 | `DWORD` | `Xpos` | 0x28 | `D2Structs.h:225` |
| 0x02C | 0x4 | `DWORD` | `Ypos` | 0x2C | `D2Structs.h:226` |
| 0x030 | 0x4 | `DWORD` | `dwPartyFlags` | 0x30 | `D2Structs.h:227` |
| 0x034 | 0x4 | `BYTE*` | `_5` | 0x34 | unknown; `D2Structs.h:228` |
| 0x038 | 0x2C | `DWORD[11]` | `_6` | 0x38 | unknown; `D2Structs.h:229` |
| 0x064 | 0x2 | `WORD` | `_7` | 0x64 | unknown; `D2Structs.h:230` |
| 0x066 | 0x10 | `char[16]` | `szName2` | 0x66 | `D2Structs.h:231` |
| 0x076 | 0x2 | `WORD` | `_8` | 0x76 | unknown; `D2Structs.h:232` |
| 0x078 | 0x8 | `DWORD[2]` | `_9` | 0x78 | unknown; `D2Structs.h:233` |
| 0x080 | 0x4 | `RosterUnit*` | `pNext` | 0x80 | `D2Structs.h:234` |

## Misc (Warden, data tables, D2BS-side)

### sgptDataTable

`D2Structs.h:747-755` · sizeof **0x1C** (28) · align 4 · packing default (/Zp8)

> Defined but not used as a type: the global is declared as a plain DWORD (`D2Ptrs.h:349`) and MPQStats.cpp adds raw table offsets to it (`MPQStats.cpp:42`). `MpqTable` is only forward-declared (`D2Structs.h:745`); `MPQTable` in `MPQStats.h:47` is a different, D2BS-side descriptor (case differs).

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `MpqTable*` | `pPlayerClass` |  | `D2Structs.h:748` |
| 0x004 | 0x4 | `DWORD` | `dwPlayerClassRecords` |  | `D2Structs.h:749` |
| 0x008 | 0x4 | `MpqTable*` | `pBodyLocs` |  | `D2Structs.h:750` |
| 0x00C | 0x4 | `DWORD` | `dwBodyLocsRecords` |  | `D2Structs.h:751` |
| 0x010 | 0x4 | `MpqTable*` | `pStorePage` |  | `D2Structs.h:752` |
| 0x014 | 0x4 | `DWORD` | `dwStorePageRecords` |  | `D2Structs.h:753` |
| 0x018 | 0x4 | `MpqTable*` | `pElemTypes` |  | `D2Structs.h:754` |

### D2MSG

`D2Structs.h:727-730` · sizeof **0x104** (260) · align 4 · packing default (/Zp8)

> D2BS-side helper (HWND + buffer), not a game structure.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `HWND` | `myHWND` |  | `D2Structs.h:728` |
| 0x004 | 0x100 | `char[256]` | `lpBuf` |  | `D2Structs.h:729` |

### WardenClient_t

`D2Structs.h:687-693` · sizeof **0x14** (20) · align 4 · packing default (/Zp8)

> Warden structures are declared but not referenced by D2Ptrs.h.

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `WardenClientRegion_t*` | `pWardenRegion` | +00 | `D2Structs.h:688` |
| 0x004 | 0x4 | `DWORD` | `cbSize` | +04 | `D2Structs.h:689` |
| 0x008 | 0x4 | `DWORD` | `nModuleCount` | +08 | `D2Structs.h:690` |
| 0x00C | 0x4 | `DWORD` | `param` | +0c | `D2Structs.h:691` |
| 0x010 | 0x4 | `DWORD` | `fnSetupWarden` | +10 | `D2Structs.h:692` |

### WardenClientRegion_t

`D2Structs.h:668-678` · sizeof **0x28** (40) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `cbAllocSize` | +00 | `D2Structs.h:669` |
| 0x004 | 0x4 | `DWORD` | `offsetFunc1` | +04 | `D2Structs.h:670` |
| 0x008 | 0x4 | `DWORD` | `offsetRelocAddressTable` | +08 | `D2Structs.h:671` |
| 0x00C | 0x4 | `DWORD` | `nRelocCount` | +0c | `D2Structs.h:672` |
| 0x010 | 0x4 | `DWORD` | `offsetWardenSetup` | +10 | `D2Structs.h:673` |
| 0x014 | 0x8 | `DWORD[2]` | `_2` |  | unknown; `D2Structs.h:674` |
| 0x01C | 0x4 | `DWORD` | `offsetImportAddressTable` | +1c | `D2Structs.h:675` |
| 0x020 | 0x4 | `DWORD` | `nImportDllCount` | +20 | `D2Structs.h:676` |
| 0x024 | 0x4 | `DWORD` | `nSectionCount` | +24 | `D2Structs.h:677` |

### WardenIATInfo_t

`D2Structs.h:695-698` · sizeof **0x8** (8) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x4 | `DWORD` | `offsetModuleName` |  | `D2Structs.h:696` |
| 0x004 | 0x4 | `DWORD` | `offsetImportTable` |  | `D2Structs.h:697` |

### SMemBlock_t

`D2Structs.h:680-685` · sizeof **0x9C** (156) · align 4 · packing default (/Zp8)

| Offset | Size | Type | Field | Source comment | Notes |
|---|---|---|---|---|---|
| 0x000 | 0x18 | `DWORD[6]` | `_1` |  | unknown; `D2Structs.h:681` |
| 0x018 | 0x4 | `DWORD` | `cbSize` | +18 | `D2Structs.h:682` |
| 0x01C | 0x7C | `DWORD[31]` | `_2` |  | unknown; `D2Structs.h:683` |
| 0x098 | 0x1 | `BYTE[1]` | `data` | +98 | `D2Structs.h:684` |
| 0x099 | 0x3 | | (padding) | | tail padding to align 4 |

## Win32 types referenced by D2Ptrs.h

These are defined by `<windows.h>` (MSVC x86), not by the repo. `d2bs_types.h` gives the equivalent definitions in its prelude. Sizes are computed by clang (MSVC x86) from the same definitions, and the C check asserts them against the prelude.

| Type | sizeof | Definition used | D2Ptrs.h uses |
|---|---|---|---|
| `BYTE` | 0x1 | unsigned char | `D2Ptrs.h:112`, `D2Ptrs.h:341`, `D2Ptrs.h:362`, `D2Ptrs.h:363` +2 |
| `WORD` | 0x2 | unsigned short | `D2Ptrs.h:321`, `D2Ptrs.h:418` |
| `DWORD` | 0x4 | unsigned long | `D2Ptrs.h:64`, `D2Ptrs.h:67`, `D2Ptrs.h:68`, `D2Ptrs.h:74` +90 |
| `POINT` | 0x8 | struct tagPOINT { LONG x; LONG y; } | `D2Ptrs.h:153` |
| `RECT` | 0x10 | struct tagRECT { LONG left, top, right, bottom; } | - |
| `CRITICAL_SECTION` | 0x18 | RTL_CRITICAL_SECTION: DebugInfo*, LockCount, RecursionCount, OwningThread, LockSemaphore, SpinCount | `D2Ptrs.h:370` |
| `HWND` | 0x4 | struct HWND__* (STRICT) | `D2Ptrs.h:382` |
| `LPSTR` | 0x4 | char* | `D2Ptrs.h:410` |
| `LPVOID` | 0x4 | void* | `D2Ptrs.h:410` |
| `BOOL` | 0x4 | int | `D2Ptrs.h:74`, `D2Ptrs.h:75`, `D2Ptrs.h:313`, `D2Ptrs.h:338` +3 |
| `INT` | 0x4 | int | `D2Ptrs.h:313` |
| `CHAR` | 0x1 | char | `D2Ptrs.h:325` |
| `size_t` | 0x4 | unsigned int | `D2Ptrs.h:362` |
| `VOID` | - | macro for void (`#define VOID void` in winnt.h) | `D2Ptrs.h:100`, `D2Ptrs.h:101`, `D2Ptrs.h:118`, `D2Ptrs.h:326` +3 |

`RECT` is not used by an active D2Ptrs.h entry. It is listed because the commented-out `DrawAutomapCell` prototype (`D2Ptrs.h:376`) and the `D2GFX_DrawRectFrame_STUB` helper (`D2Helpers.h:108`) use it.

## Partially known structs

Bytes declared with placeholder names (`_1`, `_2a`, `unk...`), plus compiler padding, as a share of sizeof. Anything not in a named field is unknown to D2BS.

| Struct | sizeof | Named bytes | Placeholder bytes | Padding bytes | Named % |
|---|---|---|---|---|---|
| SplitText | 0x8 | 8 | 0 | 0 | 100% |
| InventoryInfo | 0xC | 12 | 0 | 0 | 100% |
| GameStructInfo | 0x25D | 230 | 375 | 0 | 38% |
| AutomapCell | 0x14 | 20 | 0 | 0 | 100% |
| GfxCell | 0x24 | 29 | 4 | 3 | 81% |
| UnitInteraction | 0x20 | 24 | 8 | 0 | 75% |
| CellFile | 0x414 | 1044 | 0 | 0 | 100% |
| CellContext | 0x48 | 4 | 68 | 0 | 6% |
| AutomapLayer | 0x1C | 28 | 0 | 0 | 100% |
| AutomapLayer2 | 0xC | 4 | 8 | 0 | 33% |
| LevelTxt | 0x220 | 301 | 241 | 2 | 55% |
| ControlText | 0x20 | 32 | 0 | 0 | 100% |
| Control | 0x264 | 568 | 44 | 0 | 93% |
| BnetData | 0x3C8 | 485 | 483 | 0 | 50% |
| RoomTile | 0x14 | 12 | 8 | 0 | 60% |
| RosterUnit | 0x84 | 68 | 64 | 0 | 52% |
| QuestInfo | 0x8 | 4 | 4 | 0 | 50% |
| Waypoint | 0x1 | 1 | 0 | 0 | 100% |
| PlayerData | 0x28 | 40 | 0 | 0 | 100% |
| CollMap | 0x28 | 40 | 0 | 0 | 100% |
| PresetUnit | 0x1C | 20 | 8 | 0 | 71% |
| Level | 0x22C | 108 | 448 | 0 | 19% |
| Room2 | 0x60 | 56 | 40 | 0 | 58% |
| Room2__pType2Info_t | 0xC | 8 | 4 | 0 | 67% |
| Room1 | 0x80 | 40 | 88 | 0 | 31% |
| ActMisc | 0x480 | 12 | 1140 | 0 | 1% |
| Act | 0x4C | 16 | 60 | 0 | 21% |
| Path | 0x68 | 53 | 48 | 3 | 51% |
| ItemPath | 0x14 | 8 | 12 | 0 | 40% |
| Stat | 0x8 | 8 | 0 | 0 | 100% |
| StatVector | 0x8 | 8 | 0 | 0 | 100% |
| StatList | 0x70 | 72 | 40 | 0 | 64% |
| Inventory | 0x2C | 36 | 8 | 0 | 82% |
| Light | 0x34 | 12 | 40 | 0 | 23% |
| SkillInfo | 0x2 | 2 | 0 | 0 | 100% |
| Skill | 0x40 | 24 | 40 | 0 | 38% |
| Info | 0x10 | 16 | 0 | 0 | 100% |
| ItemData | 0x88 | 90 | 44 | 2 | 66% |
| ItemTxt | 0x130 | 138 | 163 | 3 | 45% |
| MonsterTxt | 0x308 | 154 | 622 | 0 | 20% |
| MonsterData | 0x64 | 68 | 31 | 1 | 68% |
| ObjectTxt | 0x1C0 | 202 | 246 | 0 | 45% |
| ObjectData | 0x38 | 21 | 32 | 3 | 38% |
| ObjectPath | 0x14 | 12 | 8 | 0 | 60% |
| UnitAny | 0xEC | 138 | 98 | 0 | 58% |
| UnitHashTable | 0x200 | 512 | 0 | 0 | 100% |
| WardenClientRegion_t | 0x28 | 32 | 8 | 0 | 80% |
| SMemBlock_t | 0x9C | 5 | 148 | 3 | 3% |
| WardenClient_t | 0x14 | 20 | 0 | 0 | 100% |
| WardenIATInfo_t | 0x8 | 8 | 0 | 0 | 100% |
| NPCMenu | 0x27 | 32 | 7 | 0 | 82% |
| OverheadMsg | 0xF8 | 236 | 12 | 0 | 95% |
| D2MSG | 0x104 | 260 | 0 | 0 | 100% |
| InventoryLayout | 0x18 | 20 | 2 | 2 | 83% |
| sgptDataTable | 0x1C | 28 | 0 | 0 | 100% |
| MessageHandlerList | 0x10 | 12 | 4 | 0 | 75% |
| MessageHandlerHashTable | 0x8 | 8 | 0 | 0 | 100% |
| WindowHandlerHashTable | 0x8 | 8 | 0 | 0 | 100% |
| WindowHandlerList | 0x14 | 12 | 8 | 0 | 60% |
| TransactionDialogsLine_t | 0x110 | 248 | 24 | 0 | 91% |
| TransactionDialogsInfo_t | 0xB0C | 2728 | 100 | 0 | 96% |

## Cross-check against MPQStats.h

`MPQStats.h` contains BinField tables (column name, type, length, offset). D2BS uses them for `getBaseStat`, and the source credits them to a dump by Sheppard. They come from a different source than `D2Structs.h`. For the `*Txt` records they give a second opinion on the offsets below. They may be from another game version, so a mismatch is a lead to check, not proof.

| Struct.field | Computed | Source comment | MPQStats.h column | MPQStats.h offset | Agrees with |
|---|---|---|---|---|---|
| `ItemTxt.dwCode` | 0x080 | - | `itemTable.code` (`MPQStats.h:70`) | 0x080 | computed |
| `ItemTxt.nLocaleTxtNo` | 0x0F4 | 0x0F4 | `itemTable.namestr` (`MPQStats.h:103`) | 0x0F4 | computed, comment |
| `ItemTxt.xSize` | 0x10F | 0x0FC | `itemTable.invwidth` (`MPQStats.h:121`) | 0x10F | computed |
| `ItemTxt.ySize` | 0x110 | 0x0FD | `itemTable.invheight` (`MPQStats.h:122`) | 0x110 | computed |
| `ItemTxt.nType` | 0x11E | 0x11E | `itemTable.type` (`MPQStats.h:136`) | 0x11E | computed, comment |
| `ItemTxt.fQuest` | 0x12C | 0x12A | `itemTable.quest` (`MPQStats.h:143`) | 0x12A | comment |
| `MonsterTxt.nLocaleTxtNo` | 0x006 | 0x006 | `monstatsTable.NameStr` (`MPQStats.h:265`) | 0x006 | computed, comment |
| `MonsterTxt.velocity` | 0x032 | 0x032 | `monstatsTable.Velocity` (`MPQStats.h:315`) | 0x032 | computed, comment |
| `MonsterTxt.tcs` | 0x086 | 0x086 | `monstatsTable.TreasureClass1` (`MPQStats.h:358`) | 0x086 | computed, comment |
| `ObjectTxt.szName` | 0x000 | 0x000 | `objectsTable.Name` (`MPQStats.h:791`) | 0x000 | computed, comment |
| `ObjectTxt.nSelectable0` | 0x0C4 | 0x0C4 | `objectsTable.Selectable0` (`MPQStats.h:794`) | 0x0C4 | computed, comment |
| `ObjectTxt.nOrientation` | 0x14C | 0x14C | `objectsTable.Orientation` (`MPQStats.h:873`) | 0x13C | **neither** |
| `ObjectTxt.nSubClass` | 0x166 | 0x166 | `objectsTable.SubClass` (`MPQStats.h:909`) | 0x167 | **neither** |
| `ObjectTxt.nParm0` | 0x178 | 0x178 | `objectsTable.Parm0` (`MPQStats.h:920`) | 0x178 | computed, comment |
| `ObjectTxt.nPopulateFn` | 0x1B2 | 0x1B2 | `objectsTable.PopulateFn` (`MPQStats.h:940`) | 0x1B2 | computed, comment |
| `ObjectTxt.nOperateFn` | 0x1B3 | 0x1B3 | `objectsTable.OperateFn` (`MPQStats.h:941`) | 0x1B3 | computed, comment |
| `ObjectTxt.nAutoMap` | 0x1BC | 0x1BB | `objectsTable.AutoMap` (`MPQStats.h:947`) | 0x1BC | computed |
| `LevelTxt.dwLevelNo` | 0x000 | 0x000 | `levelsTable.Id` (`MPQStats.h:1266`) | 0x000 | computed, comment |
| `LevelTxt.szName` | 0x0F5 | 0x0F5 | `levelsTable.LevelName` (`MPQStats.h:1400`) | 0x0F5 | computed, comment |
| `LevelTxt.szEntranceText` | 0x11D | 0x11D | `levelsTable.LevelWarp` (`MPQStats.h:1401`) | 0x11D | computed, comment |
| `LevelTxt.nObjGroup` | 0x20E | 0x196 | `levelsTable.ObjGrp0` (`MPQStats.h:1384`) | 0x0E5 | **neither** |
| `LevelTxt.nObjPrb` | 0x216 | 0x19E | `levelsTable.ObjPrb0` (`MPQStats.h:1392`) | 0x0ED | **neither** |

## How this was verified

All numbers in this file come from `docs/ghidra/tools/gen_types.py` (Python 3 stdlib only), which runs clang. Toolchain used for this revision: `Ubuntu clang version 18.1.3 (1ubuntu1)`.

1. **Ground truth.** `D2Structs.h` is compiled unmodified as MSVC x86 C++ against a minimal fake `<windows.h>`. The fake header contains the x86 SDK definitions of BYTE/WORD/DWORD/BOOL/HWND/POINT/RECT, and a 24-byte CRITICAL_SECTION. A generated probe defines `extern "C" const unsigned` constants holding `sizeof`/`alignof`/`__builtin_offsetof` for 61 structs and 547 fields. The constants are read back from the LLVM IR:
   ```
   clang++ --target=i686-pc-windows-msvc -fms-extensions -fms-compatibility -std=c++14 -I $WORK/shim -I . -S -emit-llvm -O0 -o $WORK/truth_probe.ll $WORK/truth_probe.cpp
   ```
   Bit-field positions (offsetof cannot take a bit-field) are read from clang's record dump:
   ```
   clang++ --target=i686-pc-windows-msvc -fms-extensions -fms-compatibility -std=c++14 -I $WORK/shim -I . -fsyntax-only -Xclang -fdump-record-layouts-complete $WORK/truth_probe.cpp
   ```
2. **Independent engine.** A Python implementation of the MSVC rules (natural alignment capped by `#pragma pack`, /Zp8 default, MS bit-field allocation) recomputes every layout. It must match step 1 exactly: it does, for every struct and field.
3. **Ghidra header.** The generated `d2bs_types.h` is compiled as C11 (`typedef unsigned short wchar_t;` then `#include`) with one `_Static_assert` per field offset (539), per sizeof (89, including hoisted anonymous types and the Win32 prelude types) and per struct alignment (61). The values come from step 1. 4 more asserts use `__builtin_types_compatible_p` to check that every function pointer keeps its calling convention. Bit-field positions (8) are compared through the C record dump. Result: pass.
   ```
   clang -x c -std=c11 --target=i686-pc-windows-msvc -fsyntax-only -Wall -Wextra -Werror -Xclang -fdump-record-layouts-complete $WORK/check_types.c
   ```
4. **Type coverage.** Every type identifier used by a `FUNCPTR`/`VARPTR` entry of `D2Ptrs.h`, and by the FUNC/DATA `type` column of `docs/ghidra/d2bs_symbols.tsv`, is defined or forward-declared in the header. The only exception is `VOID`, a winnt.h macro that has to be replaced by `void`. Result: pass.
5. **Ghidra's own parser.** `--ghidra-cp` (or `--ghidra-install`) compiles a small Java harness (embedded in the script) against Ghidra's classes. The harness parses `d2bs_types.h` with `ghidra.app.util.cparser.C.CParser` into a `StandAloneDataTypeManager` that uses the x86win.cspec data organisation (MS bit-field convention), then compares every composite with step 1. `--ghidra-install DIR` builds the classpath from a release layout (`Ghidra/Framework/*/lib/*.jar`, `Ghidra/Features/Base/lib/*.jar`); this revision was checked through `--ghidra-cp`. Parser used: Ghidra 12.0.4 (CParser generated from C.jj of tag Ghidra_12.0.4_build with JavaCC 5.0, compiled with its framework sources on JDK 21). The C.jj of the local checkout (918acd7) differs from that tag only in enum declarations (underlying type, packed enums), integer-literal suffixes, the `packed` keyword token and built-in typedef replacement (applied only to names such as `uint32_t` or `wchar_t`, which this header does not typedef), so the constructs used here parse the same way. Result: parse succeeded with no messages; 61 composites and 547 fields (8 bit-fields) match, 12 structs carry explicit pack 1; `d2bs_types.h` followed by all 111 FUNC prototypes and 92 DATA declarations of `docs/ghidra/d2bs_symbols.tsv` also parses (52 prototypes come out `__stdcall`, 58 `__fastcall`, 1 `__cdecl`; 1 DATA row(s) without a type are skipped).
   The same run re-tests the CParser behaviour this page relies on, using small probe headers. Bare `#pragma pack(push)`/`pack(1)`/`pack(pop)` leaves the next struct packed (sizeof 5 instead of 8). `pack(push, 1)`/`pack(pop)` restores it (8). `__attribute__((packed))` is ignored (sizeof 8). After `typedef void VOID;` a `(VOID)` parameter list does not parse. `RET (__stdcall *p)(...)` loses the calling convention (`int A_t(int )`), while `RET __stdcall (*p)(...)` keeps it (`int __stdcall B_t(int )`).

Re-run with `python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check` (add `--ghidra-install <ghidra dir>` or `--ghidra-cp <classpath>` for step 5, and `--work DIR` to keep the probe files).

## Open questions

- Which side of each DISCREPANCY matches 1.14d? Answering this needs a memory dump or disassembly. D2BS reads the computed offsets, so these are the cases where a wrong comment could hide a live bug: `BnetData.ladderflag` (`me.ladder`, `JSUnit.cpp:126`) is read at 0x3C2 but commented 0x3C0, because `szGameDesc[0x104]` ends at 0x361 where the comments expect 0x35F. `Control.wText2` (button text, `Control.cpp:83`) is read at 0x64 but commented 0x6C. `ItemTxt.xSize`/`ySize` are read at 0x10F/0x110 (comments 0xFC/0xFD). MPQStats.h agrees with the code there. `ObjectTxt.nAutoMap` is read at 0x1BC (comment 0x1BB), and MPQStats.h agrees with the code. `CollMap.pMapEnd` is read at 0x24 (comment 0x22) and ends the collision loops in `LevelMap.cpp`.
- Fields D2BS does not read, where the code disagrees with an independent source: `ItemTxt.fQuest` (code 0x12C; comment and MPQStats.h 0x12A), `LevelTxt.nObjGroup`/`nObjPrb` (code 0x20E/0x216, comment 0x196/0x19E, MPQStats.h 0xE5/0xED, which falls inside `LevelTxt._1`), and `ObjectTxt.nOrientation`/`nSubClass` (MPQStats.h 0x13C/0x167). These should be fixed or removed before anyone relies on them.
- `UnitAny.pListNext` has the comment `0xE4 -> 0xD8`. D2BS walks the unit hash tables through 0xE4. Is 0xD8 the value for another game version?
- `MpqTable` is only forward-declared, so its layout is unknown. `sgptDataTable` declares only the first 7 members, and the code treats the global as a plain DWORD.
- `UnitAny` has no union member for missiles (dwType 3). The +0x2C path union has no member for tiles.
- Is the pack(1) on `Level`, `Room2`, `RosterUnit` and the others intended? Only `BnetData` and `NPCMenu` change layout under it; for the rest it only lowers the alignment to 1 (`Waypoint`, a single BYTE, is not affected at all).
- `d2bs_symbols.tsv` writes the callbacks of `D2WIN_SetEditBoxCallback`/`D2WIN_SetEditBoxProc` inline as `BOOL (__stdcall* FunCallBack)(...)`. CParser drops `__stdcall` in that form. Because both parameters are named `FunCallBack`, they also share a single function definition: the last signature parsed wins. `d2bs_types.h` provides `D2WIN_SetEditBoxCallback_FunCallBack_t` and `D2WIN_SetEditBoxProc_FunCallBack_t` with the calling convention preserved, for use in those prototypes.

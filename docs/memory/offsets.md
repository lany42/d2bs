# Offsets, patches and hardcoded addresses (Game.exe 1.14d)

Scope: every game address the D2BS C++ code uses — the 213 `FUNCPTR`/`VARPTR`/`ASMPTR` entries of
`D2Ptrs.h`, the 31 `Patch.h` patch sites, the absolute VAs in `MPQStats.cpp` and `JSUnit.cpp` — with
RVA, VA, normalised C type, calling convention, source comment, a computed status and where each
one is referenced (directly or through alias macros and asm wrappers). Tables between
`<!-- BEGIN GENERATED:... -->` markers are produced by
[`gen_symbols.py`](../ghidra/tools/gen_symbols.py) from the sources and must not be edited by hand;
the same data is in [`d2bs_symbols.tsv`](../ghidra/d2bs_symbols.tsv) for Ghidra. RVAs are relative to
Game.exe; VA = `0x400000 + RVA` (see [README.md](README.md) for the address model). Nothing here was
verified against a Game.exe binary: "ported" means the source comments are internally consistent,
not that the address is right.

## Contents

1. [Reading the tables](#1-reading-the-tables)
2. [Summary](#2-summary)
3. [Stale and suspect entries: what depends on them](#3-stale-and-suspect-entries-what-depends-on-them)
4. [`D2Ptrs.h` symbols by module](#4-d2ptrsh-symbols-by-module)
5. [`Patch.h` patch sites](#5-patchh-patch-sites)
6. [Hardcoded addresses outside `D2Ptrs.h`](#6-hardcoded-addresses-outside-d2ptrsh)
7. [Declared vs used types, asm-only prototypes](#7-declared-vs-used-types-asm-only-prototypes)
8. [Commented-out and disabled entries (historical hints)](#8-commented-out-and-disabled-entries-historical-hints)
9. [JS entry points per symbol](#9-js-entry-points-per-symbol)
10. [Open questions](#10-open-questions)

## 1. Reading the tables

Columns of the symbol tables:

| Column | Meaning |
|---|---|
| Name | Code identifier (`p_` prefix for `VARPTR`) and the `D2Ptrs.h` line where the entry starts. In the TSV, `VARPTR` names drop the `p_`. |
| Kind | `FUNCPTR`, `VARPTR`, `ASMPTR`; `ASMPTR (data)` for `D2CLIENT_BodyClickTable`, which is a table, not code. |
| RVA / VA | Offset from the macro; VA = `0x400000 + RVA`. |
| Type / prototype | `FUNCPTR`: normalised C prototype (`VOID`→`void`, `()`→`(void)`, clang-format `T * p`→`T* p`). Data: type of the object at the address (the `VARPTR` type, or the usage-derived type, see `type-from-usage`). |
| CC | Calling convention from the `FUNCPTR` return-type argument. |
| Source comment | Trailing `//` comment of the entry's last line. |
| Referenced in | `File(count)` of identifier occurrences in compiled sources (comments, strings, `#if 0` blocks, prototypes and `D2Ptrs.h` itself excluded), plus occurrences of every alias macro / asm wrapper that (transitively) expands to the symbol, listed after "via". |

Status flags (comma separated, same strings as the TSV `status` column):

| Flag | Rule (computed by the generator) |
|---|---|
| `ported-1.14d` | Comment contains `1.14d` **and** a `<hex>-BASE` VA equal to `0x400000 + RVA`. |
| `va-only` | A matching `-BASE` VA comment or an absolute `0x400000`-based literal in code, but no `1.14d` text. Probably authored for 1.14, not proven 1.14d. |
| `stale-pre-1.14d?` | Comment shows a 1.13-style `0x6Fxxxxxx` address or mentions 1.12/1.13, **or** nothing ties the entry to 1.14d (no `1.14d` text, no matching VA). The *Evidence (strength)* column of §3 separates the two cases (strong / weak). |
| `va-comment-mismatch` | A `-BASE` VA comment that differs from `0x400000 + RVA`. Currently none. |
| `ported-1.14d-unverified` | `1.14d` text, but no `-BASE` VA that confirms the RVA (missing, or mismatching together with `va-comment-mismatch`). Currently none. |
| `duplicate-address` | Same RVA as another row; later rows carry `alias_of=<first>` in the TSV `extra` column. |
| `unused` | No use site: neither the identifier nor any alias macro / asm wrapper that reaches it is used in a function body or initialiser. A wrapper's own body does not count as a use. |
| `dead-code-only` | Has use sites, but none in code reachable from a live root (file-scope initialisers such as `Patches[]` and JS spec tables, `DllMain`, the exported `QueryInterface`). Name-based, so it errs towards "live". |
| `asm-only` | `FUNCPTR` referenced only from `__asm`/naked functions: the declared prototype is never used by the compiler and may not be the real ABI (§7). |
| `type-from-usage` | Every use casts `p_X` to a different pointer type; the TSV type is the cast's pointee (§7). |
| `captured-encoded` | Read by a file-scope initialiser before `DefineOffsets()` runs, so the copy holds the `DLLOFFSET` encoding (README §5.1). |

## 2. Summary

<!-- BEGIN GENERATED:summary -->
| Kind | Rows |
|---|---|
| FUNC | 111 |
| DATA | 93 |
| LABEL | 31 |
| PATCH | 22 |
| COND_PATCH | 9 |
| **total** | **266** |

| Status flag | Rows |
|---|---|
| `ported-1.14d` | 225 |
| `va-only` | 24 |
| `ported-1.14d-unverified` | 0 |
| `stale-pre-1.14d?` | 17 |
| `va-comment-mismatch` | 0 |
| `duplicate-address` | 16 |
| `unused` | 39 |
| `dead-code-only` | 3 |
| `asm-only` | 6 |
| `type-from-usage` | 7 |
| `captured-encoded` | 2 |
<!-- END GENERATED:summary -->

Highlights (details in §3):

- All 227 `-BASE` VA comments in `D2Ptrs.h`/`Patch.h` equal `0x400000 + RVA`; no `va-comment-mismatch`.
- One definite bug: the `Fog.dll` `0x82E0` patch jumps to `0x576F06` (encoded `D2GAME_exit0`)
  instead of `0x40576F` ([Patch.h:42](../../Patch.h#L42)).
- One unconditional patch has no 1.14d evidence at all: `RealmPacketRecv_Interception` at
  `"D2MCPClient.dll"` `0x4B1AE` ([Patch.h:39](../../Patch.h#L39)).
- The four `D2Ptrs.h` entries with 1.13 D2Client.dll addresses, and the three `D2MULTI_Channel*_I`
  1.13d labels, are all unused or dead code today.
- 39 `D2Ptrs.h` symbols are `unused`, 3 are `dead-code-only`.

## 3. Stale and suspect entries: what depends on them

Hand-written impact analysis built on the generated table below it. "Live" means reachable from
an installed patch, a JS native or start-up code.

| Entry | Evidence | Live? | What breaks if the address is wrong |
|---|---|---|---|
| `D2BS_PATCH_D2GAME_exit0` ([Patch.h:42](../../Patch.h#L42)), JMP at VA `0x4082E0` | `captured-encoded`: `dwFunc` is copied from `D2GAME_exit0` at static init, value `0x576F06` | Installed unconditionally by `InstallPatches()` | Not "if": the jump target is already wrong. Any execution of the patched Fog-region code at `0x4082E0` jumps to `0x576F06`. No JS API involved. |
| `D2BS_PATCH_RealmPacketRecv_Interception` ([Patch.h:39](../../Patch.h#L39)), `"D2MCPClient.dll"` RVA `0x4B1AE`, CALL, 6 bytes | No comment, no 1.14d text; the only `D2MCPCLIENT` row, so nothing to compare it with | Installed unconditionally | If wrong, 6 bytes of unrelated code at VA `0x44B1AE` are overwritten at injection. If right, it feeds the JS `realmpacket` event ([D2Handlers.cpp:526-528](../../D2Handlers.cpp#L526-L528) → [Events.cpp:342-345](../../Events.cpp#L342-L345)); the stub expects the original callee in `esi` ([D2Intercepts.cpp:7-22](../../D2Intercepts.cpp#L7-L22)). **Verify first.** |
| Conditional patches without markers: `FailToJoin` `0x4EF28`, `Multi` `0xF5623`, `Windowname` `0xF5831`, `CacheFix` `0x11944E` / `0x119434`, Sleep `0x51C31`, OOG Sleep `0xFA66F` ([Patch.h:50-56](../../Patch.h#L50-L56)) | No `1.14d` text, no VA comment (weak). The same offsets are already present in the repository's first commit `e877bb5` (2018-12-10), whose other entries are 1.14d, so history neither confirms nor refutes them. The D2GFX/D2WIN/D2CLIENT sites fall inside the RVA span of their module's ported code rows; the two CacheFix sites lie `0x86D2`/`0x86EC` below the lowest ported BNCLIENT row (`0x121B20`). The large RVAs rule out nothing by themselves. | Only with `-ftj`, `-multi`, `-cachefix`, `-sleepy` ([D2BS.cpp:56-66](../../D2BS.cpp#L56-L66), gate checked at [Offset.cpp:55](../../Offset.cpp#L55)) | FTJ reducer, multi-instance window/class naming, per-instance `bncache.dat`, CPU-sleep patches. Wrong addresses corrupt code only when the flag is given. |
| `D2CLIENT_Interact_I` ([D2Ptrs.h:240](../../D2Ptrs.h#L240)) | 1.13 VA `6FADB2E0` = `0x6FAB0000 + RVA` (1.13 D2Client.dll base) — strong | No: only via `D2CLIENT_Interact_ASM` ← `D2CLIENT_Interact_STUB` ← `D2CLIENT_Interact()` ([D2Helpers.cpp:398-409](../../D2Helpers.cpp#L398-L409)), whose only call is commented out ([JSUnit.cpp:882](../../JSUnit.cpp#L882)) | Nothing today. Re-enabling that path in `unit.interact()` would jump into 1.14d code at a 1.13 offset. |
| `D2CLIENT_ShopAction_I`, `D2CLIENT_GetItemDesc_I`, `D2CLIENT_GameAddUnit_I` ([D2Ptrs.h:245](../../D2Ptrs.h#L245), [:248](../../D2Ptrs.h#L248), [:273](../../D2Ptrs.h#L273)) | 1.13 VAs, same `0x6FAB0000` base — strong | No (`unused`): wrappers without callers, or `AddUnit_Intercept` whose patch is commented out ([Patch.h:22](../../Patch.h#L22)) | Nothing. `unit.shop()` uses the ported `D2CLIENT_ShopAction` FUNCPTR; `unit.description` uses `D2CLIENT_LoadItemDesc` plus the JSUnit VAs. |
| `D2MULTI_ChannelChat_I`, `_ChannelEmote_I`, `_ChannelWhisper_I` ([D2Ptrs.h:403](../../D2Ptrs.h#L403)) | No comment (weak by rule), but `0x14BE6` / `0x14856` equal the commented-out 1.13d patch sites `0x14BE0` / `0x14850` plus their 6-byte length ([Patch.h:32-33](../../Patch.h#L32-L33)) — effectively strong | No (`unused`) | Nothing. |
| `D2COMMON_GetTargetUnitType` `0x773C0`, `p_D2NET_CriticalPacketSection` `0xB400` ([D2Ptrs.h:311](../../D2Ptrs.h#L311), [:370](../../D2Ptrs.h#L370)) | No 1.14d text (weak by rule). Range inference (not proof): `0x773C0` is outside the span of all 34 `ported-1.14d` D2COMMON FUNC rows (`0x2194A0`..`0x261230`); `0xB400` is far below every `ported-1.14d` data row (`0x311254`..`0x482750`, 70 rows) and sits between ported *code* sites (`0x8CC4` .. `0x42810`). Both look like un-ported 1.13 per-DLL offsets. | No (`unused`) | Nothing. Do not "start using" `CriticalPacketSection` without re-deriving it. |
| `D2COMMON_GetMissileOwnerUnit` ([D2Ptrs.h:344](../../D2Ptrs.h#L344)) | `va-only`: comment `0x4639D0-BASE` matches; added in `de5dd07` (2021-03-14, "Unit.getParent support for missiles") | Yes: `unit.getParent()` on missiles ([JSUnit.cpp:1640](../../JSUnit.cpp#L1640)) | Wrong owner or a crash in `getParent()` for missile units. |
| `D2BS_PATCH_BYTES_75` "Congrats Screen" ([Patch.h:16](../../Patch.h#L16)) | `va-only` | Installed unconditionally | 1-byte patch (`0x75`) at VA `0x44EBFB`; works with the `CongratsScreen_Intercept` CALL at `0x44EBEF` ([Patch.h:17](../../Patch.h#L17)). |
| `D2COMMON_MPQ_*` (19 rows, [MPQStats.cpp:6-29](../../MPQStats.cpp#L6-L29)) | `va-only`: absolute VAs, no version text | Yes, but only for tables `items`, `objects`, `lvlmaze`, `lvlsub`, `lvlwarp`, `lvltypes`, `runes`, `cubemain`, `gems`, `experience` | `getBaseStat()` with those table names (or their numeric index) ([JSGame.cpp:1212](../../JSGame.cpp#L1212)); the `0x5A` "slain by" game message for object slayers, which looks up `objects` ([D2NetHandlers.cpp:91-100](../../D2NetHandlers.cpp#L91-L100), reached from the `GamePacketReceived` patch). All literal-table callers use `sgptDataTable`-relative tables (§6). |
| `D2CLIENT_ItemDescFlag` / `_ItemDescUnit` / `D2WIN_ItemDescText` ([JSUnit.cpp:453-458](../../JSUnit.cpp#L453-L458)) | `va-only`; `0x3BCBF4` equals `p_D2CLIENT_SelectedInvItem` ([D2Ptrs.h:203](../../D2Ptrs.h#L203)) | Yes: `unit.description` / `me.description` (`ITEM_DESC`) | Wrong or empty description text; `WriteProcessMemory` into a wrong address. |
| `D2CLIENT_GetMouseXOffset`, `_GetMouseYOffset` ([D2Ptrs.h:100-101](../../D2Ptrs.h#L100-L101)) | ported | No (`dead-code-only`): only `WorldToScreen` / `ScreenToWorld`, which have no callers ([D2Helpers.cpp:352-362](../../D2Helpers.cpp#L352-L362)) | Nothing. |

Not address problems but relevant when re-hosting this layer:

- `getBaseStat()` with a numeric table index is not bounds-checked: `FillBaseStat(JSContext*, ...)`
  indexes `BaseStatTable[table]` directly, and `GetBaseTable()` compares `table` with
  `sizeof(BaseStatTable)` (a byte count) instead of the element count
  ([MPQStats.cpp:38](../../MPQStats.cpp#L38)).
- `RemoveConditional()` is never called ([Offset.cpp:64](../../Offset.cpp#L64); `Shutdown()` only
  calls `RemovePatches()`, [D2BS.cpp:153](../../D2BS.cpp#L153)).

Generated list of every row with a version/liveness concern:

<!-- BEGIN GENERATED:suspects -->
| Name | RVA | Status | Evidence (strength) | Use sites (function @ file:line) | JS / hook entry points |
|---|---|---|---|---|---|
| `D2CLIENT_GetMouseXOffset` | 0x5AFC0 | ported-1.14d, dead-code-only | VA comment matches (n/a) | ScreenToWorld (no live caller) @ D2Helpers.cpp:360<br>WorldToScreen (no live caller) @ D2Helpers.cpp:354 | - |
| `D2CLIENT_GetMouseYOffset` | 0x5AFB0 | ported-1.14d, dead-code-only | VA comment matches (n/a) | ScreenToWorld (no live caller) @ D2Helpers.cpp:361<br>WorldToScreen (no live caller) @ D2Helpers.cpp:355 | - |
| `D2CLIENT_Interact_I` | 0x2B2E0 | stale-pre-1.14d?, dead-code-only | 1.13-style VA 0x6FADB2E0; VA-RVA = 0x6FAB0000 (1.13 D2Client.dll base) (strong) | D2CLIENT_Interact (no live caller) @ D2Helpers.cpp:408<br>D2CLIENT_Interact_ASM (no live caller) @ D2Helpers.cpp:748 | - |
| `D2CLIENT_ShopAction_I` | 0x7D030 | stale-pre-1.14d?, unused | 1.13-style VA 0x6FB2D030; VA-RVA = 0x6FAB0000 (1.13 D2Client.dll base) (strong) | D2CLIENT_ShopAction_ASM (no live caller) @ D2Helpers.cpp:779 | - |
| `D2CLIENT_GetItemDesc_I` | 0x2E380 | stale-pre-1.14d?, unused | 1.13-style VA 0x6FADE380; VA-RVA = 0x6FAB0000 (1.13 D2Client.dll base) (strong) | D2CLIENT_GetItemDesc_ASM (no live caller) @ D2Helpers.cpp:827 | - |
| `D2CLIENT_GameAddUnit_I` | 0x628E0 | stale-pre-1.14d?, unused | 1.13-style VA 0x6FB128E0; VA-RVA = 0x6FAB0000 (1.13 D2Client.dll base) (strong) | AddUnit_Intercept (no live caller) @ D2Intercepts.cpp:252 | - |
| `D2COMMON_GetTargetUnitType` | 0x773C0 | stale-pre-1.14d?, unused | no comment (weak) | - | - |
| `D2COMMON_GetMissileOwnerUnit` | 0x639D0 | va-only | VA comment matches (n/a) | unit_getParent @ JSUnit.cpp:1640 | `unit_methods.getParent` |
| `p_D2NET_CriticalPacketSection` | 0xB400 | stale-pre-1.14d?, unused | comment has no version/VA (weak) | - | - |
| `D2MULTI_ChannelChat_I` | 0x14BE6 | stale-pre-1.14d?, unused | no comment (weak) | - | - |
| `D2MULTI_ChannelEmote_I` | 0x14856 | stale-pre-1.14d?, unused | no comment (weak) | - | - |
| `D2MULTI_ChannelWhisper_I` | 0x142F0 | stale-pre-1.14d?, unused | no comment (weak) | - | - |
| `D2GAME_exit0` | 0x576F | ported-1.14d, captured-encoded | VA comment matches; read by a file-scope initialiser while still encoded (0x576F06) (strong) | Patches[] initializer @ Patch.h:42 | Patches[] (Patch.h:8) |
| `D2BS_PATCH_BYTES_75` | 0x4EBFB | va-only | VA comment matches (n/a) | installed by InstallPatches() (Patch.h:16) | - |
| `D2BS_PATCH_RealmPacketRecv_Interception` | 0x4B1AE | stale-pre-1.14d? | no comment (weak) | installed by InstallPatches() (Patch.h:39) | - |
| `D2BS_PATCH_D2GAME_exit0` | 0x82E0 | ported-1.14d, captured-encoded | VA comment matches; JMP target is the encoded value 0x576F06, not 0x40576F (strong) | installed by InstallPatches() (Patch.h:42) | - |
| `D2BS_PATCH_FailToJoin` | 0x4EF28 | stale-pre-1.14d? | comment has no version/VA (weak) | installed by InstallConditional() if Vars.bReduceFTJ (Patch.h:50) | - |
| `D2BS_PATCH_Multi` | 0xF5623 | stale-pre-1.14d? | no comment (weak) | installed by InstallConditional() if Vars.bMulti (Patch.h:51) | - |
| `D2BS_PATCH_Windowname` | 0xF5831 | stale-pre-1.14d? | no comment (weak) | installed by InstallConditional() if Vars.bMulti (Patch.h:52) | - |
| `D2BS_PATCH_CacheFix` | 0x11944E | stale-pre-1.14d? | no comment (weak) | installed by InstallConditional() if Vars.bCacheFix (Patch.h:53) | - |
| `D2BS_PATCH_CacheFix_2` | 0x119434 | stale-pre-1.14d? | no comment (weak) | installed by InstallConditional() if Vars.bCacheFix (Patch.h:54) | - |
| `D2BS_PATCH_BYTES_90` | 0x51C31 | stale-pre-1.14d? | comment has no version/VA (weak) | installed by InstallConditional() if Vars.bSleepy (Patch.h:55) | - |
| `D2BS_PATCH_BYTES_EB` | 0xFA66F | stale-pre-1.14d? | comment has no version/VA (weak) | installed by InstallConditional() if Vars.bSleepy (Patch.h:56) | - |
| `D2COMMON_MPQ_*` (19 rows, cubemain, experience, gems, items, lvlmaze, lvlsub, lvltypes, lvlwarp, objects, runes) | 0x4426EC .. 0x56D62C | va-only | absolute 1.14 VA literals in `BaseStatTable[]`, no version marker (weak) | GetBaseTable() via FillBaseStat() (MPQStats.cpp) | only callers that select one of these tables; see the `FillBaseStat` call-site table in the MPQ section |
| `D2CLIENT_ItemDescFlag` | 0x3BCBE8 | va-only | no comment; absolute VA literal in code (n/a) | JSUnit.cpp:453 | `me_props.description`, `unit_props.description` |
| `D2CLIENT_ItemDescUnit` | 0x3BCBF4 | va-only, duplicate-address | no comment; absolute VA literal in code (n/a) | JSUnit.cpp:454 | `me_props.description`, `unit_props.description` |
| `D2WIN_ItemDescText` | 0x441EC8 | va-only | no comment; absolute VA literal in code (n/a) | JSUnit.cpp:458 | `me_props.description`, `unit_props.description` |
<!-- END GENERATED:suspects -->

## 4. `D2Ptrs.h` symbols by module

Grouped by legacy module token (order of the `DLLNO_*` enum), then kind. The module token is not
used for resolution (README §2).

<!-- BEGIN GENERATED:symbols -->
Rows: 213 (FUNCPTR 111, VARPTR 70, ASMPTR 32). Generated from `D2Ptrs.h`; do not edit by hand.

### D2CLIENT

#### D2CLIENT functions (FUNCPTR) (45)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2CLIENT_GetQuestInfo`<br>[D2Ptrs.h:62](../../D2Ptrs.h#L62) | FUNCPTR | 0xB32D0 | 0x4B32D0 | `void* __stdcall D2CLIENT_GetQuestInfo(void)` | __stdcall | `Updated 1.14d //004B32D0-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2CLIENT_SubmitItem`<br>[D2Ptrs.h:64](../../D2Ptrs.h#L64) | FUNCPTR | 0xB2370 | 0x4B2370 | `void __fastcall D2CLIENT_SubmitItem(DWORD dwItemId)` | __fastcall | `Updated 1.14d //004B2370-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_Transmute`<br>[D2Ptrs.h:65](../../D2Ptrs.h#L65) | FUNCPTR | 0x8A0D0 | 0x48A0D0 | `void __fastcall D2CLIENT_Transmute(void)` | __fastcall | `Updated 1.14d //0048A0D0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_FindClientSideUnit`<br>[D2Ptrs.h:67](../../D2Ptrs.h#L67) | FUNCPTR | 0x63990 | 0x463990 | `UnitAny* __fastcall D2CLIENT_FindClientSideUnit(DWORD dwId, DWORD dwType)` | __fastcall | `Updated 1.14d //00463990-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2CLIENT_FindServerSideUnit`<br>[D2Ptrs.h:68](../../D2Ptrs.h#L68) | FUNCPTR | 0x639B0 | 0x4639B0 | `UnitAny* __fastcall D2CLIENT_FindServerSideUnit(DWORD dwId, DWORD dwType)` | __fastcall | `Updated 1.14d //004639B0-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2CLIENT_GetCurrentInteractingNPC`<br>[D2Ptrs.h:69](../../D2Ptrs.h#L69) | FUNCPTR | 0xB1620 | 0x4B1620 | `UnitAny* __fastcall D2CLIENT_GetCurrentInteractingNPC(void)` | __fastcall | `Updated 1.14d //004B1620-BASE` | ported-1.14d | JSGame.cpp(1), JSUnit.cpp(4) |
| `D2CLIENT_GetSelectedUnit`<br>[D2Ptrs.h:70](../../D2Ptrs.h#L70) | FUNCPTR | 0x67A10 | 0x467A10 | `UnitAny* __stdcall D2CLIENT_GetSelectedUnit(void)` | __stdcall | `Updated 1.14d //00467A10-BASE` | ported-1.14d | D2Intercepts.cpp(2), JSUnit.cpp(1), Patch.h(1); via `GameAttack_Intercept` |
| `D2CLIENT_GetCursorItem`<br>[D2Ptrs.h:71](../../D2Ptrs.h#L71) | FUNCPTR | 0x680A0 | 0x4680A0 | `UnitAny* __fastcall D2CLIENT_GetCursorItem(void)` | __fastcall | `Updated 1.14d //004680A0-BASE` | ported-1.14d | JSGame.cpp(3), JSUnit.cpp(3) |
| `D2CLIENT_SetSelectedUnit_I`<br>[D2Ptrs.h:73](../../D2Ptrs.h#L73) | FUNCPTR | 0x66DE0 | 0x466DE0 | `void __fastcall D2CLIENT_SetSelectedUnit_I(UnitAny* pUnit)` | __fastcall | `Updated 1.14d //00466DE0-BASE` | ported-1.14d, asm-only | Core.cpp(1), D2Helpers.cpp(1); via `D2CLIENT_SetSelectedUnit_STUB`, `D2CLIENT_SetSelectedUnit` |
| `D2CLIENT_GetItemName`<br>[D2Ptrs.h:74](../../D2Ptrs.h#L74) | FUNCPTR | 0x8C060 | 0x48C060 | `BOOL __fastcall D2CLIENT_GetItemName(UnitAny* pItem, wchar_t* wBuffer, DWORD dwSize)` | __fastcall | `Updated 1.14d //0048C060-BASE` | ported-1.14d | D2Helpers.cpp(1), JSUnit.cpp(1) |
| `D2CLIENT_LoadItemDesc`<br>[D2Ptrs.h:75](../../D2Ptrs.h#L75) | FUNCPTR | 0x8DD90 | 0x48DD90 | `BOOL __stdcall D2CLIENT_LoadItemDesc(UnitAny* pItem, int type)` | __stdcall | `Updated 1.14d //0048DD90-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2CLIENT_GetMonsterOwner`<br>[D2Ptrs.h:76](../../D2Ptrs.h#L76) | FUNCPTR | 0x79150 | 0x479150 | `DWORD __fastcall D2CLIENT_GetMonsterOwner(DWORD nMonsterId)` | __fastcall | `Updated 1.14d //00479150-BASE` | ported-1.14d | D2Helpers.cpp(1), JSUnit.cpp(1) |
| `D2CLIENT_GetUnitHPPercent`<br>[D2Ptrs.h:77](../../D2Ptrs.h#L77) | FUNCPTR | 0x79080 | 0x479080 | `DWORD __fastcall D2CLIENT_GetUnitHPPercent(DWORD dwUnitId)` | __fastcall | `Updated 1.14d //00479080-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2CLIENT_InitInventory`<br>[D2Ptrs.h:78](../../D2Ptrs.h#L78) | FUNCPTR | 0x845A0 | 0x4845A0 | `void __fastcall D2CLIENT_InitInventory(void)` | __fastcall | `Updated 1.14d //004845A0-BASE` | ported-1.14d | D2Handlers.cpp(1) |
| `D2CLIENT_SetUIVar`<br>[D2Ptrs.h:79](../../D2Ptrs.h#L79) | FUNCPTR | 0x55F20 | 0x455F20 | `DWORD __fastcall D2CLIENT_SetUIVar(DWORD varno, DWORD howset, DWORD unknown1)` | __fastcall | `Updated 1.14d //00455F20-BASE` | ported-1.14d | JSGame.cpp(2); via `D2CLIENT_SetUIState` |
| `D2CLIENT_GetUnitX`<br>[D2Ptrs.h:80](../../D2Ptrs.h#L80) | FUNCPTR | 0x5ADF0 | 0x45ADF0 | `int __fastcall D2CLIENT_GetUnitX(UnitAny* pUnit)` | __fastcall | `Updated 1.14d //0045ADF0-BASE` | ported-1.14d | Core.cpp(1), D2Helpers.cpp(1), JSGame.cpp(4), JSUnit.cpp(3), Map/Diablo_II/ActMap.cpp(1), Map/Diablo_II/LevelMap.cpp(1) |
| `D2CLIENT_GetUnitY`<br>[D2Ptrs.h:81](../../D2Ptrs.h#L81) | FUNCPTR | 0x5AE20 | 0x45AE20 | `int __fastcall D2CLIENT_GetUnitY(UnitAny* pUnit)` | __fastcall | `Updated 1.14d //0045AE20-BASE` | ported-1.14d | Core.cpp(1), D2Helpers.cpp(1), JSGame.cpp(4), JSUnit.cpp(3), Map/Diablo_II/ActMap.cpp(1), Map/Diablo_II/LevelMap.cpp(1) |
| `D2CLIENT_ShopAction`<br>[D2Ptrs.h:83](../../D2Ptrs.h#L83) | FUNCPTR | 0xB3870 | 0x4B3870 | `void __fastcall D2CLIENT_ShopAction(UnitAny* pNpc, UnitAny* pItem, DWORD dwSell, DWORD unk, DWORD dwItemCost, DWORD dwMode, DWORD _2, DWORD _3)` | __fastcall | `Updated 1.14d //004B3870-BASE` | ported-1.14d | JSUnit.cpp(2) |
| `D2CLIENT_CloseNPCInteract`<br>[D2Ptrs.h:86](../../D2Ptrs.h#L86) | FUNCPTR | 0xB3F10 | 0x4B3F10 | `void __fastcall D2CLIENT_CloseNPCInteract(void)` | __fastcall | `Updated 1.14d //004B3F10-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2CLIENT_CloseInteract`<br>[D2Ptrs.h:87](../../D2Ptrs.h#L87) | FUNCPTR | 0x4C6B0 | 0x44C6B0 | `void __fastcall D2CLIENT_CloseInteract(void)` | __fastcall | `Updated 1.14d //0044C6B0-BASE` | ported-1.14d | JSUnit.cpp(2) |
| `D2CLIENT_GetAutomapSize`<br>[D2Ptrs.h:89](../../D2Ptrs.h#L89) | FUNCPTR | 0x5A710 | 0x45A710 | `DWORD __stdcall D2CLIENT_GetAutomapSize(void)` | __stdcall | `Updated 1.14d //0045A710-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2CLIENT_NewAutomapCell`<br>[D2Ptrs.h:90](../../D2Ptrs.h#L90) | FUNCPTR | 0x57C30 | 0x457C30 | `AutomapCell* __fastcall D2CLIENT_NewAutomapCell(void)` | __fastcall | `Updated 1.14d //00457C30-BASE` | ported-1.14d | Room.cpp(1) |
| `D2CLIENT_AddAutomapCell`<br>[D2Ptrs.h:91](../../D2Ptrs.h#L91) | FUNCPTR | 0x57B00 | 0x457B00 | `void __fastcall D2CLIENT_AddAutomapCell(AutomapCell* aCell, AutomapCell** node)` | __fastcall | `Updated 1.14d //00457B00-BASE` | ported-1.14d | Room.cpp(1) |
| `D2CLIENT_RevealAutomapRoom`<br>[D2Ptrs.h:92](../../D2Ptrs.h#L92) | FUNCPTR | 0x58F40 | 0x458F40 | `void __stdcall D2CLIENT_RevealAutomapRoom(Room1* pRoom1, DWORD dwClipFlag, AutomapLayer* aLayer)` | __stdcall | `Updated 1.14d //00458F40-BASE` | ported-1.14d | Room.cpp(1) |
| `D2CLIENT_InitAutomapLayer_I`<br>[D2Ptrs.h:93](../../D2Ptrs.h#L93) | FUNCPTR | 0x58D40 | 0x458D40 | `AutomapLayer* __fastcall D2CLIENT_InitAutomapLayer_I(DWORD nLayerNo)` | __fastcall | `Updated 1.14d //00458D40-BASE` | ported-1.14d, asm-only | D2Helpers.cpp(2); via `D2CLIENT_InitAutomapLayer_STUB`, `D2CLIENT_InitAutomapLayer` |
| `D2CLIENT_ClickMap`<br>[D2Ptrs.h:95](../../D2Ptrs.h#L95) | FUNCPTR | 0x62D00 | 0x462D00 | `void __fastcall D2CLIENT_ClickMap(DWORD MouseFlag, DWORD x, DWORD y, DWORD Type)` | __fastcall | `Updated 1.14d //00462D00-BASE` | ported-1.14d | Core.cpp(2), JSUnit.cpp(1) |
| `D2CLIENT_LeftClickItem_I`<br>[D2Ptrs.h:96](../../D2Ptrs.h#L96) | FUNCPTR | 0x8FFE0 | 0x48FFE0 | `void __stdcall D2CLIENT_LeftClickItem_I(UnitAny* pPlayer, Inventory* pInventory, int x, int y, DWORD dwClickType, InventoryLayout* pLayout, DWORD Location)` | __stdcall | `Updated 1.14d //0048FFE0-BASE` | ported-1.14d, asm-only | D2Helpers.cpp(1), JSGame.cpp(3); via `D2CLIENT_LeftClickItem` |
| `D2CLIENT_GetMouseXOffset`<br>[D2Ptrs.h:100](../../D2Ptrs.h#L100) | FUNCPTR | 0x5AFC0 | 0x45AFC0 | `DWORD __fastcall D2CLIENT_GetMouseXOffset(void)` | __fastcall | `Updated 1.14d //0045AFC0-BASE` | ported-1.14d, dead-code-only | D2Helpers.cpp(2) |
| `D2CLIENT_GetMouseYOffset`<br>[D2Ptrs.h:101](../../D2Ptrs.h#L101) | FUNCPTR | 0x5AFB0 | 0x45AFB0 | `DWORD __fastcall D2CLIENT_GetMouseYOffset(void)` | __fastcall | `Updated 1.14d //0045AFB0-BASE` | ported-1.14d, dead-code-only | D2Helpers.cpp(2) |
| `D2CLIENT_PrintGameString`<br>[D2Ptrs.h:103](../../D2Ptrs.h#L103) | FUNCPTR | 0x9E3A0 | 0x49E3A0 | `void __fastcall D2CLIENT_PrintGameString(wchar_t* wMessage, int nColor)` | __fastcall | `Updated 1.14d //0049E3A0-BASE` | ported-1.14d | D2Handlers.cpp(1) |
| `D2CLIENT_PrintPartyString`<br>[D2Ptrs.h:104](../../D2Ptrs.h#L104) | FUNCPTR | 0x9E5C0 | 0x49E5C0 | `void __fastcall D2CLIENT_PrintPartyString(wchar_t* wMessage, int nColor)` | __fastcall | `Updated 1.14d //0049E5C0-BASE` | ported-1.14d, unused | - |
| `D2CLIENT_LeaveParty`<br>[D2Ptrs.h:106](../../D2Ptrs.h#L106) | FUNCPTR | 0x79FC0 | 0x479FC0 | `void __fastcall D2CLIENT_LeaveParty(void)` | __fastcall | `Updated 1.14d //00479FC0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_AcceptTrade`<br>[D2Ptrs.h:108](../../D2Ptrs.h#L108) | FUNCPTR | 0xB9070 | 0x4B9070 | `void __fastcall D2CLIENT_AcceptTrade(void)` | __fastcall | `Updated 1.14d //004B9070-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_CancelTrade`<br>[D2Ptrs.h:109](../../D2Ptrs.h#L109) | FUNCPTR | 0xB90B0 | 0x4B90B0 | `void __fastcall D2CLIENT_CancelTrade(void)` | __fastcall | `Updated 1.14d //004B90B0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_TradeOK`<br>[D2Ptrs.h:110](../../D2Ptrs.h#L110) | FUNCPTR | 0xB8A30 | 0x4B8A30 | `void __stdcall D2CLIENT_TradeOK(void)` | __stdcall | `Updated 1.14d //004B8A30-BASE` | ported-1.14d | JSGame.cpp(2) |
| `D2CLIENT_GetDifficulty`<br>[D2Ptrs.h:112](../../D2Ptrs.h#L112) | FUNCPTR | 0x4DCD0 | 0x44DCD0 | `BYTE __stdcall D2CLIENT_GetDifficulty(void)` | __stdcall | `Updated 1.14d //0044DCD0-BASE` | ported-1.14d | D2Handlers.cpp(1), JSUnit.cpp(3) |
| `D2CLIENT_ExitGame`<br>[D2Ptrs.h:114](../../D2Ptrs.h#L114) | FUNCPTR | 0x4DD60 | 0x44DD60 | `void __fastcall D2CLIENT_ExitGame(void)` | __fastcall | `Updated 1.14d //0044DD60-BASE` | ported-1.14d | D2Handlers.cpp(1), D2NetHandlers.cpp(1), JSGame.cpp(2), ScriptEngine.cpp(1) |
| `D2CLIENT_GetUiVar_I`<br>[D2Ptrs.h:116](../../D2Ptrs.h#L116) | FUNCPTR | 0x538D0 | 0x4538D0 | `DWORD __fastcall D2CLIENT_GetUiVar_I(DWORD dwVarNo)` | __fastcall | `Updated 1.14d //004538D0-BASE` | ported-1.14d, asm-only | D2Handlers.cpp(2), D2Helpers.cpp(1), JSGame.cpp(2), JSUnit.cpp(2); via `D2CLIENT_GetUIVar_STUB`, `D2CLIENT_GetUIState` |
| `D2CLIENT_DrawRectFrame`<br>[D2Ptrs.h:118](../../D2Ptrs.h#L118) | FUNCPTR | 0x52E50 | 0x452E50 | `void __fastcall D2CLIENT_DrawRectFrame(DWORD Rect)` | __fastcall | `Updated 1.14d //00452E50-BASE` | ported-1.14d, asm-only | D2Helpers.cpp(1), ScreenHook.cpp(1); via `D2GFX_DrawRectFrame_STUB`, `D2GFX_DrawFrame` |
| `D2CLIENT_PerformGoldDialogAction`<br>[D2Ptrs.h:120](../../D2Ptrs.h#L120) | FUNCPTR | 0x54080 | 0x454080 | `void __fastcall D2CLIENT_PerformGoldDialogAction(void)` | __fastcall | `Updated 1.14d //00454080-BASE` | ported-1.14d | Game.cpp(1) |
| `D2CLIENT_GetPlayerUnit`<br>[D2Ptrs.h:122](../../D2Ptrs.h#L122) | FUNCPTR | 0x63DD0 | 0x463DD0 | `UnitAny* __stdcall D2CLIENT_GetPlayerUnit(void)` | __stdcall | `Updated 1.14d //00463DD0-BASE` | ported-1.14d | Core.cpp(1), D2Handlers.cpp(2), D2Helpers.cpp(8), D2Helpers.h(1), D2NetHandlers.cpp(1), Game.cpp(2), JSGame.cpp(38), JSPresetUnit.cpp(8), JSRoom.cpp(39), JSUnit.cpp(13), Map/Path/AStarPath.h(1), Room.cpp(2), Script.cpp(2), ScriptEngine.cpp(1) |
| `D2CLIENT_ClearScreen`<br>[D2Ptrs.h:126](../../D2Ptrs.h#L126) | FUNCPTR | 0xB4620 | 0x4B4620 | `void __fastcall D2CLIENT_ClearScreen(void)` | __fastcall | `Updated 1.14d //004B4620-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2CLIENT_CloseNPCTalk`<br>[D2Ptrs.h:128](../../D2Ptrs.h#L128) | FUNCPTR | 0xA17D0 | 0x4A17D0 | `DWORD __stdcall D2CLIENT_CloseNPCTalk(void* unk)` | __stdcall | `Updated 1.14d //004A17D0-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2CLIENT_TestPvpFlag`<br>[D2Ptrs.h:130](../../D2Ptrs.h#L130) | FUNCPTR | 0xDC440 | 0x4DC440 | `DWORD __fastcall D2CLIENT_TestPvpFlag(DWORD dwUnitId1, DWORD dwUnitId2, DWORD dwFlag)` | __fastcall | `Updated 1.14d //004DC440-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_GetGameLanguageCode`<br>[D2Ptrs.h:132](../../D2Ptrs.h#L132) | FUNCPTR | 0x125150 | 0x525150 | `DWORD __fastcall D2CLIENT_GetGameLanguageCode(void)` | __fastcall | `New 1.14d //00525150-BASE` | ported-1.14d | Helpers.cpp(1) |

#### D2CLIENT data (VARPTR / data ASMPTR) (59)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2CLIENT_ScreenSizeX`<br>[D2Ptrs.h:138](../../D2Ptrs.h#L138) | VARPTR | 0x31146C | 0x71146C | `DWORD` | - | `Updated 1.14d //0071146C-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `p_D2CLIENT_ScreenSizeY`<br>[D2Ptrs.h:139](../../D2Ptrs.h#L139) | VARPTR | 0x311470 | 0x711470 | `DWORD` | - | `Updated 1.14d //00711470-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `p_D2CLIENT_CursorHoverX`<br>[D2Ptrs.h:141](../../D2Ptrs.h#L141) | VARPTR | 0x321E4C | 0x721E4C | `DWORD` | - | `Updated 1.14d //00721E4C-BASE` | ported-1.14d | JSGame.cpp(3) |
| `p_D2CLIENT_CursorHoverY`<br>[D2Ptrs.h:142](../../D2Ptrs.h#L142) | VARPTR | 0x321E50 | 0x721E50 | `DWORD` | - | `Updated 1.14d //00721E50-BASE` | ported-1.14d | JSGame.cpp(3) |
| `p_D2CLIENT_MouseY`<br>[D2Ptrs.h:144](../../D2Ptrs.h#L144) | VARPTR | 0x3A6AAC | 0x7A6AAC | `DWORD` | - | `Updated 1.14d //007A6AAC-BASE` | ported-1.14d | Core.cpp(3), D2Intercepts.cpp(1), JSGame.cpp(1), Patch.h(1); via `GameAttack_Intercept` |
| `p_D2CLIENT_MouseX`<br>[D2Ptrs.h:145](../../D2Ptrs.h#L145) | VARPTR | 0x3A6AB0 | 0x7A6AB0 | `DWORD` | - | `Updated 1.14d //007A6AB0-BASE` | ported-1.14d | Core.cpp(3), JSGame.cpp(1) |
| `p_D2CLIENT_MouseOffsetY`<br>[D2Ptrs.h:147](../../D2Ptrs.h#L147) | VARPTR | 0x3A5208 | 0x7A5208 | `int` | - | `Updated 1.14d //007A5208-BASE` | ported-1.14d, duplicate-address, unused | - |
| `p_D2CLIENT_MouseOffsetZ`<br>[D2Ptrs.h:148](../../D2Ptrs.h#L148) | VARPTR | 0x3A5214 | 0x7A5214 | `int` | - | `Updated 1.14d //007A5214-BASE` | ported-1.14d, unused | - |
| `p_D2CLIENT_MouseOffsetX`<br>[D2Ptrs.h:149](../../D2Ptrs.h#L149) | VARPTR | 0x3A520C | 0x7A520C | `int` | - | `Updated 1.14d //007A520C-BASE` | ported-1.14d, duplicate-address, unused | - |
| `p_D2CLIENT_AutomapOn`<br>[D2Ptrs.h:151](../../D2Ptrs.h#L151) | VARPTR | 0x3A27E8 | 0x7A27E8 | `DWORD` | - | `Updated 1.14d //007A27E8-BASE` | ported-1.14d | JSUnit.cpp(4), ScreenHook.cpp(1) |
| `p_D2CLIENT_AutomapMode`<br>[D2Ptrs.h:152](../../D2Ptrs.h#L152) | VARPTR | 0x311254 | 0x711254 | `int` | - | `Updated 1.14d //00711254-BASE **Divisor**` | ported-1.14d, duplicate-address | D2Helpers.cpp(2) |
| `p_D2CLIENT_Offset`<br>[D2Ptrs.h:153](../../D2Ptrs.h#L153) | VARPTR | 0x3A5198 | 0x7A5198 | `POINT` | - | `Updated 1.14d //007A5198-BASE` | ported-1.14d | D2Helpers.cpp(4) |
| `p_D2CLIENT_AutomapLayer`<br>[D2Ptrs.h:154](../../D2Ptrs.h#L154) | VARPTR | 0x3A5164 | 0x7A5164 | `AutomapLayer*` | - | `Updated 1.14d //007A5164-BASE` | ported-1.14d | Room.cpp(2) |
| `p_D2CLIENT_MercReviveCost`<br>[D2Ptrs.h:157](../../D2Ptrs.h#L157) | VARPTR | 0x3C0DD0 | 0x7C0DD0 | `DWORD` | - | `Updated 1.14d //007C0DD0-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_ServerSideUnitHashTables`<br>[D2Ptrs.h:159](../../D2Ptrs.h#L159) | VARPTR | 0x3A5E70 | 0x7A5E70 | `UnitHashTable` | - | `Updated 1.14d //007A5E70-BASE` | ported-1.14d | Unit.cpp(4) |
| `p_D2CLIENT_ClientSideUnitHashTables`<br>[D2Ptrs.h:160](../../D2Ptrs.h#L160) | VARPTR | 0x3A5270 | 0x7A5270 | `UnitHashTable` | - | `Updated 1.14d //007A5270-BASE` | ported-1.14d | Unit.cpp(2) |
| `p_D2CLIENT_ViewportY`<br>[D2Ptrs.h:162](../../D2Ptrs.h#L162) | VARPTR | 0x3A5208 | 0x7A5208 | `int` | - | `Updated 1.14d //007A5208-BASE **MouseOffsetY` | ported-1.14d, duplicate-address | Core.cpp(1), JSGame.cpp(1) |
| `p_D2CLIENT_ViewportX`<br>[D2Ptrs.h:163](../../D2Ptrs.h#L163) | VARPTR | 0x3A520C | 0x7A520C | `int` | - | `Updated 1.14d //007A520C-BASE **MouseOffsetX` | ported-1.14d, duplicate-address | Core.cpp(1), JSGame.cpp(1) |
| `p_D2CLIENT_GoldDialogAction`<br>[D2Ptrs.h:165](../../D2Ptrs.h#L165) | VARPTR | 0x3A279C | 0x7A279C | `DWORD` | - | `Updated 1.14d //007A279C-BASE` | ported-1.14d | Game.cpp(1) |
| `p_D2CLIENT_GoldDialogAmount`<br>[D2Ptrs.h:166](../../D2Ptrs.h#L166) | VARPTR | 0x3A2A68 | 0x7A2A68 | `DWORD` | - | `Updated 1.14d //007A2A68-BASE` | ported-1.14d | Game.cpp(1) |
| `p_D2CLIENT_NPCMenu`<br>[D2Ptrs.h:168](../../D2Ptrs.h#L168) | VARPTR | 0x326C48 | 0x726C48 | `NPCMenu`<br>(declared `NPCMenu*`) | - | `Updated 1.14d //00726C48-BASE` | ported-1.14d, type-from-usage | D2Helpers.cpp(1) |
| `p_D2CLIENT_NPCMenuAmount`<br>[D2Ptrs.h:169](../../D2Ptrs.h#L169) | VARPTR | 0x325A74 | 0x725A74 | `DWORD` | - | `Updated 1.14d //00725A74-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `p_D2CLIENT_TradeLayout`<br>[D2Ptrs.h:171](../../D2Ptrs.h#L171) | VARPTR | 0x3BCA30 | 0x7BCA30 | `InventoryLayout`<br>(declared `InventoryLayout*`) | - | `Updated 1.14d //007BCA30-BASE` | ported-1.14d, type-from-usage | JSGame.cpp(1) |
| `p_D2CLIENT_StashLayout`<br>[D2Ptrs.h:172](../../D2Ptrs.h#L172) | VARPTR | 0x3BCA78 | 0x7BCA78 | `InventoryLayout`<br>(declared `InventoryLayout*`) | - | `Updated 1.14d //007BCA78-BASE` | ported-1.14d, type-from-usage | JSGame.cpp(2) |
| `p_D2CLIENT_StoreLayout`<br>[D2Ptrs.h:173](../../D2Ptrs.h#L173) | VARPTR | 0x3BCB58 | 0x7BCB58 | `InventoryLayout*` | - | `Updated 1.14d //007BCB58-BASE` | ported-1.14d, unused | - |
| `p_D2CLIENT_CubeLayout`<br>[D2Ptrs.h:174](../../D2Ptrs.h#L174) | VARPTR | 0x3BCB70 | 0x7BCB70 | `InventoryLayout`<br>(declared `InventoryLayout*`) | - | `Updated 1.14d //007BCB70-BASE` | ported-1.14d, type-from-usage | JSGame.cpp(2) |
| `p_D2CLIENT_InventoryLayout`<br>[D2Ptrs.h:175](../../D2Ptrs.h#L175) | VARPTR | 0x3BCB88 | 0x7BCB88 | `InventoryLayout`<br>(declared `InventoryLayout*`) | - | `Updated 1.14d //007BCB88-BASE` | ported-1.14d, type-from-usage | JSGame.cpp(2) |
| `p_D2CLIENT_MercLayout`<br>[D2Ptrs.h:176](../../D2Ptrs.h#L176) | VARPTR | 0x3BCD4C | 0x7BCD4C | `InventoryLayout*` | - | `Updated 1.14d //007BCD4C-BASE` | ported-1.14d, unused | - |
| `p_D2CLIENT_RegularCursorType`<br>[D2Ptrs.h:178](../../D2Ptrs.h#L178) | VARPTR | 0x3A6AF0 | 0x7A6AF0 | `DWORD` | - | `Updated 1.14d //007A6AF0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `p_D2CLIENT_ShopCursorType`<br>[D2Ptrs.h:179](../../D2Ptrs.h#L179) | VARPTR | 0x3BCBF0 | 0x7BCBF0 | `DWORD` | - | `Updated 1.14d //007BCBF0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `p_D2CLIENT_Ping`<br>[D2Ptrs.h:181](../../D2Ptrs.h#L181) | VARPTR | 0x3A04A4 | 0x7A04A4 | `DWORD` | - | `Updated 1.14d //007A04A4-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_Skip`<br>[D2Ptrs.h:182](../../D2Ptrs.h#L182) | VARPTR | 0x3A04B0 | 0x7A04B0 | `DWORD` | - | `Updated 1.14d //007A04B0-BASE` | ported-1.14d, unused | - |
| `p_D2CLIENT_FPS`<br>[D2Ptrs.h:183](../../D2Ptrs.h#L183) | VARPTR | 0x3BB390 | 0x7BB390 | `DWORD` | - | `Updated 1.14d //007BB390-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_Lang`<br>[D2Ptrs.h:184](../../D2Ptrs.h#L184) | VARPTR | 0x3BB5DC | 0x7BB5DC | `DWORD` | - | `Updated 1.14d //007BB5DC-BASE` | ported-1.14d | Helpers.cpp(2) |
| `p_D2CLIENT_Divisor`<br>[D2Ptrs.h:185](../../D2Ptrs.h#L185) | VARPTR | 0x311254 | 0x711254 | `int` | - | `Updated 1.14d //00711254-BASE` | ported-1.14d, duplicate-address | D2Helpers.cpp(2) |
| `p_D2CLIENT_OverheadTrigger`<br>[D2Ptrs.h:187](../../D2Ptrs.h#L187) | VARPTR | 0x3BF20E | 0x7BF20E | `DWORD` | - | `Updated 1.14d //007BF20E-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_RecentInteractId`<br>[D2Ptrs.h:189](../../D2Ptrs.h#L189) | VARPTR | 0x3C0D25 | 0x7C0D25 | `DWORD` | - | `Updated 1.14d //007C0D25-BASE` | ported-1.14d | JSGame.cpp(1), JSUnit.cpp(1) |
| `p_D2CLIENT_ItemPriceList`<br>[D2Ptrs.h:191](../../D2Ptrs.h#L191) | VARPTR | 0x3C0D43 | 0x7C0D43 | `DWORD` | - | `Updated 1.14d //007C0D43-BASE` | ported-1.14d | JSUnit.cpp(3) |
| `p_D2CLIENT_TransactionDialog`<br>[D2Ptrs.h:193](../../D2Ptrs.h#L193) | VARPTR | 0x3C0D63 | 0x7C0D63 | `void*` | - | `Updated 1.14d //007C0D63-BASE` | ported-1.14d | JSGame.cpp(1), JSUnit.cpp(1) |
| `p_D2CLIENT_TransactionDialogs`<br>[D2Ptrs.h:194](../../D2Ptrs.h#L194) | VARPTR | 0x3C0E5C | 0x7C0E5C | `DWORD` | - | `Updated 1.14d //007C0E5C-BASE` | ported-1.14d | JSGame.cpp(2), JSUnit.cpp(1) |
| `p_D2CLIENT_TransactionDialogs_2`<br>[D2Ptrs.h:195](../../D2Ptrs.h#L195) | VARPTR | 0x3C0E58 | 0x7C0E58 | `DWORD` | - | `Updated 1.14d //007C0E58-BASE` | ported-1.14d | JSGame.cpp(1), JSUnit.cpp(1) |
| `p_D2CLIENT_pTransactionDialogsInfo`<br>[D2Ptrs.h:196](../../D2Ptrs.h#L196) | VARPTR | 0x3C0E54 | 0x7C0E54 | `TransactionDialogsInfo_t*` | - | `Updated 1.14d //007C0E54-BASE` | ported-1.14d | JSGame.cpp(2) |
| `p_D2CLIENT_GameInfo`<br>[D2Ptrs.h:198](../../D2Ptrs.h#L198) | VARPTR | 0x3A0438 | 0x7A0438 | `GameStructInfo*` | - | `Updated 1.14d //007A0438-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_WaypointTable`<br>[D2Ptrs.h:200](../../D2Ptrs.h#L200) | VARPTR | 0x3BF081 | 0x7BF081 | `DWORD` | - | `Updated 1.14d //007BF081-BASE` | ported-1.14d | JSGame.cpp(1) |
| `p_D2CLIENT_PlayerUnit`<br>[D2Ptrs.h:202](../../D2Ptrs.h#L202) | VARPTR | 0x3A6A70 | 0x7A6A70 | `UnitAny*` | - | `Updated 1.14d //007A6A70-BASE` | ported-1.14d | Core.cpp(1), D2Helpers.cpp(1); via `D2CLIENT_PlaySound` |
| `p_D2CLIENT_SelectedInvItem`<br>[D2Ptrs.h:203](../../D2Ptrs.h#L203) | VARPTR | 0x3BCBF4 | 0x7BCBF4 | `UnitAny*` | - | `Updated 1.14d //007BCBF4-BASE` | ported-1.14d, duplicate-address | JSUnit.cpp(1) |
| `p_D2CLIENT_PlayerUnitList`<br>[D2Ptrs.h:205](../../D2Ptrs.h#L205) | VARPTR | 0x3BB5C0 | 0x7BB5C0 | `RosterUnit*` | - | `Updated 1.14d //007BB5C0-BASE` | ported-1.14d | D2NetHandlers.cpp(1), JSGame.cpp(1), JSParty.cpp(1) |
| `p_D2CLIENT_bWeapSwitch`<br>[D2Ptrs.h:207](../../D2Ptrs.h#L207) | VARPTR | 0x3BCC4C | 0x7BCC4C | `DWORD` | - | `Updated 1.14d //007BCC4C-BASE` | ported-1.14d | JSGame.cpp(1), JSUnit.cpp(1) |
| `p_D2CLIENT_bTradeAccepted`<br>[D2Ptrs.h:209](../../D2Ptrs.h#L209) | VARPTR | 0x3BCE18 | 0x7BCE18 | `DWORD` | - | `Updated 1.14d //007BCE18-BASE` | ported-1.14d | JSGame.cpp(4) |
| `p_D2CLIENT_bTradeBlock`<br>[D2Ptrs.h:210](../../D2Ptrs.h#L210) | VARPTR | 0x3BCE28 | 0x7BCE28 | `DWORD` | - | `Updated 1.14d //007BCE28-BASE` | ported-1.14d | JSGame.cpp(2) |
| `p_D2CLIENT_RecentTradeId`<br>[D2Ptrs.h:213](../../D2Ptrs.h#L213) | VARPTR | 0x3C0E7C | 0x7C0E7C | `DWORD` | - | `Updated 1.14d //007C0E7C-BASE` | ported-1.14d | JSGame.cpp(6) |
| `p_D2CLIENT_ExpCharFlag`<br>[D2Ptrs.h:215](../../D2Ptrs.h#L215) | VARPTR | 0x3A04F4 | 0x7A04F4 | `DWORD` | - | `Updated 1.14d //007A04F4-BASE` | ported-1.14d | D2Handlers.cpp(1), JSUnit.cpp(1) |
| `p_D2CLIENT_MapId`<br>[D2Ptrs.h:217](../../D2Ptrs.h#L217) | VARPTR | 0x3A0638 | 0x7A0638 | `DWORD` | - | `Updated 1.14d //007A0638-BASE // unused but I want to add it` | ported-1.14d | JSUnit.cpp(1) |
| `p_D2CLIENT_AlwaysRun`<br>[D2Ptrs.h:219](../../D2Ptrs.h#L219) | VARPTR | 0x3A0660 | 0x7A0660 | `DWORD` | - | `Updated 1.14d //007A0660-BASE` | ported-1.14d | Core.cpp(2), JSUnit.cpp(2) |
| `p_D2CLIENT_NoPickUp`<br>[D2Ptrs.h:220](../../D2Ptrs.h#L220) | VARPTR | 0x3A6A90 | 0x7A6A90 | `DWORD` | - | `Updated 1.14d //007A6A90-BASE // unused but I want to add it` | ported-1.14d | JSUnit.cpp(2) |
| `p_D2CLIENT_ChatMsg`<br>[D2Ptrs.h:224](../../D2Ptrs.h#L224) | VARPTR | 0x3BB638 | 0x7BB638 | `wchar_t`<br>(declared `wchar_t*`) | - | `Updated 1.14d //007BB638-BASE` | ported-1.14d, type-from-usage | Core.cpp(1) |
| `p_D2CLIENT_OrificeId`<br>[D2Ptrs.h:225](../../D2Ptrs.h#L225) | VARPTR | 0x3C547C | 0x7C547C | `DWORD` | - | `Updated 1.14d //007C547C-BASE` | ported-1.14d | JSGame.cpp(1) |
| `p_D2CLIENT_CursorItemMode`<br>[D2Ptrs.h:226](../../D2Ptrs.h#L226) | VARPTR | 0x3C5474 | 0x7C5474 | `DWORD` | - | `Updated 1.14d //007C5474-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2CLIENT_BodyClickTable`<br>[D2Ptrs.h:258](../../D2Ptrs.h#L258) | ASMPTR (data) | 0x321E58 | 0x721E58 |  | - | `Updated 1.14d //00721E58-BASE` | ported-1.14d | JSGame.cpp(3) |

#### D2CLIENT code labels (ASMPTR) (22)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2CLIENT_TakeWaypoint_I`<br>[D2Ptrs.h:232](../../D2Ptrs.h#L232) | ASMPTR | 0x9D0F1 | 0x49D0F1 |  | - | `Updated 1.14d //0049D0F1-BASE` | ported-1.14d | D2Helpers.cpp(1), JSUnit.cpp(1); via `D2CLIENT_TakeWaypoint` |
| `D2CLIENT_ClickShopItem_I`<br>[D2Ptrs.h:234](../../D2Ptrs.h#L234) | ASMPTR | 0xB2653 | 0x4B2653 |  | - | `Updated 1.14d //004B2653-BASE` | ported-1.14d, unused | D2Helpers.cpp(1); via `D2CLIENT_ClickShopItem_ASM` |
| `D2CLIENT_ClickBelt_I`<br>[D2Ptrs.h:235](../../D2Ptrs.h#L235) | ASMPTR | 0x98870 | 0x498870 |  | - | `Updated 1.14d //00498870-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(2); via `D2CLIENT_ClickBelt` |
| `D2CLIENT_ClickBeltRight_I`<br>[D2Ptrs.h:236](../../D2Ptrs.h#L236) | ASMPTR | 0x98A90 | 0x498A90 |  | - | `Updated 1.14d //00498A90-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(3); via `D2CLIENT_ClickBeltRight_ASM`, `D2CLIENT_ClickBeltRight` |
| `D2CLIENT_ClickItemRight_I`<br>[D2Ptrs.h:237](../../D2Ptrs.h#L237) | ASMPTR | 0x87740 | 0x487740 |  | - | `Updated 1.14d //00487740-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(2); via `D2CLIENT_ClickItemRight_ASM`, `D2CLIENT_RightClickItem` |
| `D2CLIENT_MercItemAction_I`<br>[D2Ptrs.h:238](../../D2Ptrs.h#L238) | ASMPTR | 0x785B0 | 0x4785B0 |  | - | `Updated 1.14d //004785B0-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(2); via `D2CLIENT_MercItemAction_ASM`, `D2CLIENT_MercItemAction` |
| `D2CLIENT_Interact_I`<br>[D2Ptrs.h:240](../../D2Ptrs.h#L240) | ASMPTR | 0x2B2E0 | 0x42B2E0 |  | - | `6FADB2E0` | stale-pre-1.14d?, dead-code-only | D2Helpers.cpp(2); via `D2CLIENT_Interact_ASM`, `D2CLIENT_Interact_STUB` |
| `D2CLIENT_ClickParty_I`<br>[D2Ptrs.h:242](../../D2Ptrs.h#L242) | ASMPTR | 0x79EB0 | 0x479EB0 |  | - | `Updated 1.14d //00479EB0-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(1); via `D2CLIENT_ClickParty_ASM`, `D2CLIENT_ClickParty` |
| `D2CLIENT_ClickParty_II`<br>[D2Ptrs.h:243](../../D2Ptrs.h#L243) | ASMPTR | 0x9B990 | 0x49B990 |  | - | `Updated 1.14d //0049B990-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(4); via `D2CLIENT_HostilePartyUnit` |
| `D2CLIENT_ShopAction_I`<br>[D2Ptrs.h:245](../../D2Ptrs.h#L245) | ASMPTR | 0x7D030 | 0x47D030 |  | - | `6FB2D030 **ShopAction**` | stale-pre-1.14d?, unused | D2Helpers.cpp(1); via `D2CLIENT_ShopAction_ASM` |
| `D2CLIENT_GetUnitName_I`<br>[D2Ptrs.h:247](../../D2Ptrs.h#L247) | ASMPTR | 0x64A60 | 0x464A60 |  | - | `Updated 1.14d //00464A60-BASE` | ported-1.14d | D2Helpers.cpp(2); via `D2CLIENT_GetUnitName_STUB`, `D2CLIENT_GetUnitName` |
| `D2CLIENT_GetItemDesc_I`<br>[D2Ptrs.h:248](../../D2Ptrs.h#L248) | ASMPTR | 0x2E380 | 0x42E380 |  | - | `6FADE380` | stale-pre-1.14d?, unused | D2Helpers.cpp(1); via `D2CLIENT_GetItemDesc_ASM`, `D2CLIENT_GetItemDesc` |
| `D2CLIENT_AssignPlayer_I`<br>[D2Ptrs.h:250](../../D2Ptrs.h#L250) | ASMPTR | 0x66200 | 0x466200 |  | - | `Updated 1.14d //00466200-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `PlayerAssignment_Intercept` |
| `D2CLIENT_InputCall_I`<br>[D2Ptrs.h:254](../../D2Ptrs.h#L254) | ASMPTR | 0x787B0 | 0x4787B0 |  | - | `Updated 1.14d //004787B0-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `GameInput_Intercept` |
| `D2CLIENT_Say_I`<br>[D2Ptrs.h:256](../../D2Ptrs.h#L256) | ASMPTR | 0x7CBDA | 0x47CBDA |  | - | `Updated 1.14d //0047CBDA-BASE` | ported-1.14d | Core.cpp(2); via `Say_ASM` |
| `D2CLIENT_LoadUIImage_I`<br>[D2Ptrs.h:260](../../D2Ptrs.h#L260) | ASMPTR | 0x788B0 | 0x4788B0 |  | - | `Updated 1.14d //004788B0-BASE /// switch to d2win LoadCellFile //` | ported-1.14d, unused | - |
| `D2CLIENT_GetMinionCount_I`<br>[D2Ptrs.h:262](../../D2Ptrs.h#L262) | ASMPTR | 0x78EE0 | 0x478EE0 |  | - | `Updated 1.14d //00478EE0-BASE` | ported-1.14d | D2Helpers.cpp(1), JSUnit.cpp(1); via `D2CLIENT_GetMinionCount` |
| `D2CLIENT_GameLeave_I`<br>[D2Ptrs.h:264](../../D2Ptrs.h#L264) | ASMPTR | 0x81830 | 0x481830 |  | - | `Updated 1.14d //00481830-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `GameLeave_Intercept` |
| `D2CLIENT_CongratsScreen_I`<br>[D2Ptrs.h:266](../../D2Ptrs.h#L266) | ASMPTR | 0xF6190 | 0x4F6190 |  | - | `Updated 1.14d //004F6190-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `CongratsScreen_Intercept` |
| `D2CLIENT_GameAddUnit_I`<br>[D2Ptrs.h:273](../../D2Ptrs.h#L273) | ASMPTR | 0x628E0 | 0x4628E0 |  | - | `6FB128E0` | stale-pre-1.14d?, unused | D2Intercepts.cpp(1); via `AddUnit_Intercept` |
| `D2CLIENT_SendGamePacket_I`<br>[D2Ptrs.h:283](../../D2Ptrs.h#L283) | ASMPTR | 0x78350 | 0x478350 |  | - | `Updated 1.14d //00478350-BASE //SendPacket_I` | ported-1.14d | D2Helpers.cpp(2), Game.cpp(2); via `D2CLIENT_SendGamePacket_ASM`, `D2CLIENT_SendGamePacket` |
| `D2CLIENT_SendPacket_II`<br>[D2Ptrs.h:284](../../D2Ptrs.h#L284) | ASMPTR | 0x12AE62 | 0x52AE62 |  | - | `Updated **NEW** 1.14d //0052AE62-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `GamePacketSent_Interception` |

### D2COMMON

#### D2COMMON functions (FUNCPTR) (36)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2COMMON_InitLevel`<br>[D2Ptrs.h:290](../../D2Ptrs.h#L290) | FUNCPTR | 0x2424A0 | 0x6424A0 | `void __stdcall D2COMMON_InitLevel(Level* pLevel)` | __stdcall | `Updated 1.14d //006424A0-BASE` | ported-1.14d | D2Helpers.cpp(1), Map/Diablo_II/ActMap.cpp(2) |
| `D2COMMON_UnloadAct`<br>[D2Ptrs.h:291](../../D2Ptrs.h#L291) | FUNCPTR | 0x21AFD3 | 0x61AFD3 | `unsigned int __stdcall D2COMMON_UnloadAct(Act* pAct)` | __stdcall | `Updated 1.14d //0061AFD3-BASE` | ported-1.14d, unused | - |
| `D2COMMON_GetObjectTxt`<br>[D2Ptrs.h:292](../../D2Ptrs.h#L292) | FUNCPTR | 0x240E90 | 0x640E90 | `ObjectTxt* __stdcall D2COMMON_GetObjectTxt(DWORD objno)` | __stdcall | `Updated 1.14d //00640E90-BASE` | ported-1.14d, duplicate-address, unused | - |
| `D2COMMON_LoadAct`<br>[D2Ptrs.h:293](../../D2Ptrs.h#L293) | FUNCPTR | 0x2194A0 | 0x6194A0 | `Act* __stdcall D2COMMON_LoadAct(DWORD ActNumber, DWORD MapId, DWORD Unk, DWORD Unk_2, DWORD Unk_3, DWORD Unk_4, DWORD TownLevelId, DWORD Func_1, DWORD Func_2)` | __stdcall | `Updated 1.14d //006194A0-BASE` | ported-1.14d, unused | - |
| `D2COMMON_GetLevelText`<br>[D2Ptrs.h:297](../../D2Ptrs.h#L297) | FUNCPTR | 0x21DB70 | 0x61DB70 | `LevelTxt* __stdcall D2COMMON_GetLevelText(DWORD levelno)` | __stdcall | `Updated 1.14d //0061DB70-BASE` | ported-1.14d | D2Helpers.h(2), JSArea.cpp(1) |
| `D2COMMON_GetObjectText`<br>[D2Ptrs.h:298](../../D2Ptrs.h#L298) | FUNCPTR | 0x240E90 | 0x640E90 | `ObjectTxt* __stdcall D2COMMON_GetObjectText(DWORD objno)` | __stdcall | `Updated 1.14d //00640E90-BASE` | ported-1.14d, duplicate-address | Map/Diablo_II/ActMap.cpp(1), Room.cpp(1) |
| `D2COMMON_GetItemText`<br>[D2Ptrs.h:299](../../D2Ptrs.h#L299) | FUNCPTR | 0x2335F0 | 0x6335F0 | `ItemTxt* __stdcall D2COMMON_GetItemText(DWORD itemno)` | __stdcall | `Updated 1.14d //006335F0-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(1), JSUnit.cpp(7) |
| `D2COMMON_GetLayer`<br>[D2Ptrs.h:301](../../D2Ptrs.h#L301) | FUNCPTR | 0x21E470 | 0x61E470 | `AutomapLayer2* __fastcall D2COMMON_GetLayer(DWORD dwLevelNo)` | __fastcall | `Updated 1.14d //0061E470-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2COMMON_GetLevel`<br>[D2Ptrs.h:302](../../D2Ptrs.h#L302) | FUNCPTR | 0x242AE0 | 0x642AE0 | `Level* __fastcall D2COMMON_GetLevel(ActMisc* pMisc, DWORD dwLevelNo)` | __fastcall | `Updated 1.14d //00642AE0-BASE` | ported-1.14d, unused | - |
| `D2COMMON_GetStatList`<br>[D2Ptrs.h:304](../../D2Ptrs.h#L304) | FUNCPTR | 0x2257D0 | 0x6257D0 | `StatList* __stdcall D2COMMON_GetStatList(UnitAny* pUnit, DWORD dwUnk, DWORD dwMaxEntries)` | __stdcall | `Updated 1.14d //006257D0-BASE` | ported-1.14d | JSUnit.cpp(3) |
| `D2COMMON_CopyStatList`<br>[D2Ptrs.h:305](../../D2Ptrs.h#L305) | FUNCPTR | 0x225C90 | 0x625C90 | `DWORD __stdcall D2COMMON_CopyStatList(StatList* pStatList, Stat* pStatArray, DWORD dwMaxEntries)` | __stdcall | `Updated 1.14d //0625C90-BASE` | ported-1.14d | JSUnit.cpp(2) |
| `D2COMMON_GetUnitStat`<br>[D2Ptrs.h:306](../../D2Ptrs.h#L306) | FUNCPTR | 0x225480 | 0x625480 | `DWORD __stdcall D2COMMON_GetUnitStat(UnitAny* pUnit, DWORD dwStat, DWORD dwStat2)` | __stdcall | `Updated 1.14d //00625480-BASE` | ported-1.14d | Game.cpp(2), JSUnit.cpp(10), Unit.cpp(2) |
| `D2COMMON_GetUnitState`<br>[D2Ptrs.h:307](../../D2Ptrs.h#L307) | FUNCPTR | 0x239DF0 | 0x639DF0 | `int __stdcall D2COMMON_GetUnitState(UnitAny* pUnit, DWORD dwStateNo)` | __stdcall | `Updated 1.14d //00639DF0-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2COMMON_CheckUnitCollision`<br>[D2Ptrs.h:309](../../D2Ptrs.h#L309) | FUNCPTR | 0x222AA0 | 0x622AA0 | `DWORD __stdcall D2COMMON_CheckUnitCollision(UnitAny* pUnitA, UnitAny* pUnitB, DWORD dwBitMask)` | __stdcall | `Updated 1.14d //00622AA0-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2COMMON_GetRoomFromUnit`<br>[D2Ptrs.h:310](../../D2Ptrs.h#L310) | FUNCPTR | 0x220BB0 | 0x620BB0 | `Room1* __stdcall D2COMMON_GetRoomFromUnit(UnitAny* ptUnit)` | __stdcall | `Updated 1.14d //00620BB0-BASE` | ported-1.14d | JSRoom.cpp(2), JSUnit.cpp(2) |
| `D2COMMON_GetTargetUnitType`<br>[D2Ptrs.h:311](../../D2Ptrs.h#L311) | FUNCPTR | 0x773C0 | 0x4773C0 | `Path* __stdcall D2COMMON_GetTargetUnitType(Path* pPath)` | __stdcall | - | stale-pre-1.14d?, unused | - |
| `D2COMMON_GetSkillLevel`<br>[D2Ptrs.h:313](../../D2Ptrs.h#L313) | FUNCPTR | 0x2442A0 | 0x6442A0 | `int __stdcall D2COMMON_GetSkillLevel(UnitAny* pUnit, Skill* pSkill, BOOL bTotal)` | __stdcall | `Updated 1.14d //006442A0-BASE` | ported-1.14d | D2Helpers.cpp(1), JSUnit.cpp(2) |
| `D2COMMON_GetItemLevelRequirement`<br>[D2Ptrs.h:315](../../D2Ptrs.h#L315) | FUNCPTR | 0x22BA60 | 0x62BA60 | `DWORD __stdcall D2COMMON_GetItemLevelRequirement(UnitAny* pItem, UnitAny* pPlayer)` | __stdcall | `Updated 1.14d //0062BA60-BASE` | ported-1.14d | JSUnit.cpp(2) |
| `D2COMMON_GetItemPrice`<br>[D2Ptrs.h:317](../../D2Ptrs.h#L317) | FUNCPTR | 0x22FDC0 | 0x62FDC0 | `DWORD __stdcall D2COMMON_GetItemPrice(UnitAny* MyUnit, UnitAny* pItem, DWORD U1_, DWORD U2_, DWORD U3_, DWORD U4_)` | __stdcall | `Updated 1.14d //0062FDC0-BASE` | ported-1.14d | JSUnit.cpp(2) |
| `D2COMMON_GetRepairCost`<br>[D2Ptrs.h:319](../../D2Ptrs.h#L319) | FUNCPTR | 0x22FE60 | 0x62FE60 | `DWORD __stdcall D2COMMON_GetRepairCost(DWORD _1, UnitAny* pUnit, DWORD dwNpcId, DWORD dwDifficulty, DWORD dwItemPriceList, DWORD _2)` | __stdcall | `Updated 1.14d //0062FE60-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2COMMON_GetItemMagicalMods`<br>[D2Ptrs.h:321](../../D2Ptrs.h#L321) | FUNCPTR | 0x233EE0 | 0x633EE0 | `char* __stdcall D2COMMON_GetItemMagicalMods(WORD wPrefixNum)` | __stdcall | `Updated 1.14d //00633EE0-BASE` | ported-1.14d | JSUnit.cpp(8) |
| `D2COMMON_GetItemFromInventory`<br>[D2Ptrs.h:322](../../D2Ptrs.h#L322) | FUNCPTR | 0x23B2C0 | 0x63B2C0 | `UnitAny* __stdcall D2COMMON_GetItemFromInventory(Inventory* inv)` | __stdcall | `Updated 1.14d //0063B2C0-BASE` | ported-1.14d | Unit.cpp(1) |
| `D2COMMON_GetNextItemFromInventory`<br>[D2Ptrs.h:323](../../D2Ptrs.h#L323) | FUNCPTR | 0x23DFA0 | 0x63DFA0 | `UnitAny* __stdcall D2COMMON_GetNextItemFromInventory(UnitAny* pItem)` | __stdcall | `Updated 1.14d //0063DFA0-BASE` | ported-1.14d | JSUnit.cpp(1), Unit.cpp(3) |
| `D2COMMON_GenerateOverheadMsg`<br>[D2Ptrs.h:325](../../D2Ptrs.h#L325) | FUNCPTR | 0x261110 | 0x661110 | `OverheadMsg* __stdcall D2COMMON_GenerateOverheadMsg(DWORD dwUnk, char* szMsg, DWORD dwTrigger)` | __stdcall | `Updated 1.14d //00661110-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2COMMON_FixOverheadMsg`<br>[D2Ptrs.h:326](../../D2Ptrs.h#L326) | FUNCPTR | 0x261230 | 0x661230 | `void __stdcall D2COMMON_FixOverheadMsg(OverheadMsg* pMsg, DWORD dwUnk)` | __stdcall | `Updated 1.14d //00661230-BASE` | ported-1.14d, unused | - |
| `D2COMMON_AddRoomData`<br>[D2Ptrs.h:328](../../D2Ptrs.h#L328) | FUNCPTR | 0x21A070 | 0x61A070 | `void __stdcall D2COMMON_AddRoomData(Act* ptAct, int LevelId, int Xpos, int Ypos, Room1* pRoom)` | __stdcall | `Updated 1.14d //0061A070-BASE` | ported-1.14d | D2Helpers.h(1), JSPresetUnit.cpp(2), JSRoom.cpp(5), Room.cpp(1) |
| `D2COMMON_RemoveRoomData`<br>[D2Ptrs.h:329](../../D2Ptrs.h#L329) | FUNCPTR | 0x21A0C0 | 0x61A0C0 | `void __stdcall D2COMMON_RemoveRoomData(Act* ptAct, int LevelId, int Xpos, int Ypos, Room1* pRoom)` | __stdcall | `Updated 1.14d //0061A0C0-BASE` | ported-1.14d | D2Helpers.h(1), JSPresetUnit.cpp(2), JSRoom.cpp(11), Room.cpp(1) |
| `D2COMMON_GetQuestFlag`<br>[D2Ptrs.h:331](../../D2Ptrs.h#L331) | FUNCPTR | 0x25C310 | 0x65C310 | `int __stdcall D2COMMON_GetQuestFlag(void* QuestInfo, DWORD dwAct, DWORD dwQuest)` | __stdcall | `Updated 1.14d //0065C310-BASE` | ported-1.14d | JSUnit.cpp(1) |
| `D2COMMON_MapToAbsScreen`<br>[D2Ptrs.h:333](../../D2Ptrs.h#L333) | FUNCPTR | 0x243260 | 0x643260 | `void __stdcall D2COMMON_MapToAbsScreen(long* pX, long* pY)` | __stdcall | `Updated 1.14d //00643260-BASE` | ported-1.14d | Core.cpp(1), D2Helpers.cpp(1) |
| `D2COMMON_AbsScreenToMap`<br>[D2Ptrs.h:334](../../D2Ptrs.h#L334) | FUNCPTR | 0x243510 | 0x643510 | `void __stdcall D2COMMON_AbsScreenToMap(long* ptMouseX, long* ptMouseY)` | __stdcall | `Updated 1.14d //00643510-BASE` | ported-1.14d | D2Helpers.cpp(1), JSGame.cpp(1) |
| `D2COMMON_CheckWaypoint`<br>[D2Ptrs.h:336](../../D2Ptrs.h#L336) | FUNCPTR | 0x260E50 | 0x660E50 | `DWORD __stdcall D2COMMON_CheckWaypoint(DWORD WaypointTable, DWORD dwLevelId)` | __stdcall | `Updated 1.14d //00660E50-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2COMMON_IsTownByLevelNo`<br>[D2Ptrs.h:338](../../D2Ptrs.h#L338) | FUNCPTR | 0x21AAF0 | 0x61AAF0 | `BOOL __stdcall D2COMMON_IsTownByLevelNo(DWORD dwLevelNo)` | __stdcall | `Updated 1.14d //0061AAF0-BASE` | ported-1.14d | D2Handlers.cpp(1), JSGame.cpp(1) |
| `D2COMMON_GetLevelNoFromRoom`<br>[D2Ptrs.h:339](../../D2Ptrs.h#L339) | FUNCPTR | 0x21A1B0 | 0x61A1B0 | `BOOL __stdcall D2COMMON_GetLevelNoFromRoom(Room1* pRoom1)` | __stdcall | `Updated 1.14d //0061A1B0-BASE` | ported-1.14d, duplicate-address | JSUnit.cpp(1) |
| `D2COMMON_FindRoom1`<br>[D2Ptrs.h:340](../../D2Ptrs.h#L340) | FUNCPTR | 0x219DA3 | 0x619DA3 | `Room1* __stdcall D2COMMON_FindRoom1(Act* pAct, int x, int y)` | __stdcall | `Updated 1.14d //00619DA3-BASE` | ported-1.14d, unused | - |
| `D2COMMON_GetItemPalette`<br>[D2Ptrs.h:341](../../D2Ptrs.h#L341) | FUNCPTR | 0x22C100 | 0x62C100 | `int __stdcall D2COMMON_GetItemPalette(UnitAny* pPlayer, UnitAny* pItem, BYTE* pColor, int nTransType)` | __stdcall | `Updated 1.14d //0062C100-BASE` | ported-1.14d, unused | - |
| `D2COMMON_GetMissileOwnerUnit`<br>[D2Ptrs.h:344](../../D2Ptrs.h#L344) | FUNCPTR | 0x639D0 | 0x4639D0 | `UnitAny* __fastcall D2COMMON_GetMissileOwnerUnit(UnitAny* pMissile)` | __fastcall | `0x4639D0-BASE` | va-only | JSUnit.cpp(1) |

#### D2COMMON data (VARPTR / data ASMPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2COMMON_sgptDataTable`<br>[D2Ptrs.h:349](../../D2Ptrs.h#L349) | VARPTR | 0x344304 | 0x744304 | `DWORD` | - | `Updated 1.14d //00744304-BASE` | ported-1.14d | MPQStats.cpp(1) |

#### D2COMMON code labels (ASMPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2COMMON_DisplayOverheadMsg_I`<br>[D2Ptrs.h:355](../../D2Ptrs.h#L355) | ASMPTR | 0x2611A0 | 0x6611A0 |  | - | `Updated 1.14d //006611A0-BASE` | ported-1.14d, unused | D2Helpers.cpp(1); via `D2COMMON_DisplayOverheadMsg_ASM`, `D2COMMON_DisplayOverheadMsg` |
| `D2COMMON_GetLevelIdFromRoom_I`<br>[D2Ptrs.h:356](../../D2Ptrs.h#L356) | ASMPTR | 0x21A1B0 | 0x61A1B0 |  | - | `Updated 1.14d //0061A1B0-BASE` | ported-1.14d, duplicate-address, unused | - |

### D2GFX

#### D2GFX functions (FUNCPTR) (5)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2GFX_DrawRectangle`<br>[D2Ptrs.h:378](../../D2Ptrs.h#L378) | FUNCPTR | 0xF6300 | 0x4F6300 | `void __stdcall D2GFX_DrawRectangle(int X1, int Y1, int X2, int Y2, DWORD dwColor, DWORD dwTrans)` | __stdcall | `Updated 1.14d //004F6300-BASE` | ported-1.14d | Console.cpp(2), ScreenHook.cpp(1) |
| `D2GFX_DrawLine`<br>[D2Ptrs.h:379](../../D2Ptrs.h#L379) | FUNCPTR | 0xF6380 | 0x4F6380 | `void __stdcall D2GFX_DrawLine(int X1, int Y1, int X2, int Y2, DWORD dwColor, DWORD dwUnk)` | __stdcall | `Updated 1.14d //004F6380-BASE` | ported-1.14d | ScreenHook.cpp(1) |
| `D2GFX_DrawAutomapCell2`<br>[D2Ptrs.h:380](../../D2Ptrs.h#L380) | FUNCPTR | 0xF6480 | 0x4F6480 | `void __stdcall D2GFX_DrawAutomapCell2(CellContext* context, DWORD xpos, DWORD ypos, DWORD bright2, DWORD bright, BYTE* coltab)` | __stdcall | `Updated 1.14d //004F6480-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2GFX_GetHwnd`<br>[D2Ptrs.h:382](../../D2Ptrs.h#L382) | FUNCPTR | 0xF59A0 | 0x4F59A0 | `HWND __stdcall D2GFX_GetHwnd(void)` | __stdcall | `Updated 1.14d //004F59A0-BASE` | ported-1.14d | Core.cpp(1), D2BS.cpp(2), D2Helpers.cpp(6), D2Intercepts.cpp(1), Helpers.cpp(4), JSCore.cpp(1), JSUnit.cpp(1), ScriptEngine.cpp(3) |
| `D2GFX_GetScreenSize`<br>[D2Ptrs.h:383](../../D2Ptrs.h#L383) | FUNCPTR | 0xF5160 | 0x4F5160 | `DWORD __stdcall D2GFX_GetScreenSize(void)` | __stdcall | `Updated 1.14d //004F5160-BASE` | ported-1.14d | JSGame.cpp(2), JSUnit.cpp(1) |

### D2LANG

#### D2LANG functions (FUNCPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2LANG_GetLocaleText`<br>[D2Ptrs.h:418](../../D2Ptrs.h#L418) | FUNCPTR | 0x124A30 | 0x524A30 | `wchar_t* __fastcall D2LANG_GetLocaleText(WORD nLocaleTxtNo)` | __fastcall | `Updated 1.14d //00524A30-BASE` | ported-1.14d | Control.cpp(2), D2NetHandlers.cpp(1), JSGame.cpp(2), JSUnit.cpp(2) |

#### D2LANG code labels (ASMPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2LANG_Say_II`<br>[D2Ptrs.h:424](../../D2Ptrs.h#L424) | ASMPTR | 0x126800 | 0x526800 |  | - | `Updated 1.14d //00526800-BASE` | ported-1.14d, unused | - |

### D2WIN

#### D2WIN functions (FUNCPTR) (14)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2WIN_SetControlText`<br>[D2Ptrs.h:436](../../D2Ptrs.h#L436) | FUNCPTR | 0xFF5A0 | 0x4FF5A0 | `void* __fastcall D2WIN_SetControlText(Control* box, const wchar_t* txt)` | __fastcall | `Updated 1.14d //004FF5A0-BASE` | ported-1.14d | Control.cpp(1), JSControl.cpp(2) |
| `D2WIN_DrawSprites`<br>[D2Ptrs.h:437](../../D2Ptrs.h#L437) | FUNCPTR | 0xF9870 | 0x4F9870 | `void __fastcall D2WIN_DrawSprites(void)` | __fastcall | `Updated 1.14d //004F9870-BASE` | ported-1.14d | D2Handlers.cpp(1) |
| `D2WIN_LoadCellFile`<br>[D2Ptrs.h:438](../../D2Ptrs.h#L438) | FUNCPTR | 0xFA9B0 | 0x4FA9B0 | `CellFile* __fastcall D2WIN_LoadCellFile(const char* szFile, int Type)` | __fastcall | `Updated 1.14d //004FA9B0-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2WIN_TakeScreenshot`<br>[D2Ptrs.h:444](../../D2Ptrs.h#L444) | FUNCPTR | 0xFA7A0 | 0x4FA7A0 | `void __fastcall D2WIN_TakeScreenshot(void)` | __fastcall | `Updated 1.14d //004FA7A0-BASE` | ported-1.14d | D2Handlers.cpp(2) |
| `D2WIN_DrawText`<br>[D2Ptrs.h:445](../../D2Ptrs.h#L445) | FUNCPTR | 0x102320 | 0x502320 | `void __fastcall D2WIN_DrawText(const wchar_t* wStr, int xPos, int yPos, DWORD dwColor, DWORD dwUnk)` | __fastcall | `Updated 1.14d //00502320-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2WIN_GetTextSize`<br>[D2Ptrs.h:446](../../D2Ptrs.h#L446) | FUNCPTR | 0x102520 | 0x502520 | `DWORD __fastcall D2WIN_GetTextSize(wchar_t* wStr, DWORD* dwWidth, DWORD* dwFileNo)` | __fastcall | `Updated 1.14d //00502520-BASE` | ported-1.14d, duplicate-address | D2Helpers.cpp(2) |
| `D2WIN_SetTextSize`<br>[D2Ptrs.h:447](../../D2Ptrs.h#L447) | FUNCPTR | 0x102EF0 | 0x502EF0 | `DWORD __fastcall D2WIN_SetTextSize(DWORD dwSize)` | __fastcall | `Updated 1.14d //00502EF0-BASE` | ported-1.14d | D2Helpers.cpp(6) |
| `D2WIN_GetTextWidthFileNo`<br>[D2Ptrs.h:448](../../D2Ptrs.h#L448) | FUNCPTR | 0x102520 | 0x502520 | `DWORD __fastcall D2WIN_GetTextWidthFileNo(wchar_t* wStr, DWORD* dwWidth, DWORD* dwFileNo)` | __fastcall | `Updated 1.14d //00502520-BASE` | ported-1.14d, duplicate-address, unused | - |
| `D2WIN_DestroyEditBox`<br>[D2Ptrs.h:449](../../D2Ptrs.h#L449) | FUNCPTR | 0xFDAA0 | 0x4FDAA0 | `DWORD __fastcall D2WIN_DestroyEditBox(Control* box)` | __fastcall | `Updated 1.14d //004FDAA0-BASE` | ported-1.14d, unused | - |
| `D2WIN_DestroyControl`<br>[D2Ptrs.h:450](../../D2Ptrs.h#L450) | FUNCPTR | 0xF95C0 | 0x4F95C0 | `void __stdcall D2WIN_DestroyControl(Control* pControl)` | __stdcall | `Updated 1.14d // 004f95c0-BASE` | ported-1.14d, unused | - |
| `D2WIN_SetEditBoxCallback`<br>[D2Ptrs.h:451](../../D2Ptrs.h#L451) | FUNCPTR | 0xFDAD0 | 0x4FDAD0 | `void __fastcall D2WIN_SetEditBoxCallback(Control* pControl, BOOL (__stdcall* FunCallBack)(Control* pControl, DWORD dwInputType, char* pChar))` | __fastcall | `Updated 1.14d //004FDAD0-BASE` | ported-1.14d, duplicate-address, unused | - |
| `D2WIN_SetEditBoxProc`<br>[D2Ptrs.h:453](../../D2Ptrs.h#L453) | FUNCPTR | 0xFDAD0 | 0x4FDAD0 | `void __fastcall D2WIN_SetEditBoxProc(Control* box, BOOL (__stdcall* FunCallBack)(Control*, DWORD, DWORD))` | __fastcall | `Updated 1.14d //004FDAD0-BASE` | ported-1.14d, duplicate-address, unused | - |
| `D2WIN_SelectEditBoxText`<br>[D2Ptrs.h:455](../../D2Ptrs.h#L455) | FUNCPTR | 0xFDD00 | 0x4FDD00 | `void __fastcall D2WIN_SelectEditBoxText(Control* box)` | __fastcall | `Updated 1.14d //004fdd00-BASE` | ported-1.14d, unused | - |
| `D2WIN_InitMPQ`<br>[D2Ptrs.h:456](../../D2Ptrs.h#L456) | FUNCPTR | 0x117332 | 0x517332 | `DWORD __fastcall D2WIN_InitMPQ(const char* mpqfile, char* mpqname, int v4, int v5)` | __fastcall | `Updated 1.14d //00517332-BASE` | ported-1.14d | Core.cpp(1) |

#### D2WIN data (VARPTR / data ASMPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2WIN_FirstControl`<br>[D2Ptrs.h:462](../../D2Ptrs.h#L462) | VARPTR | 0x3D55BC | 0x7D55BC | `Control*` | - | `Updated 1.14d //007D55BC-BASE` | ported-1.14d | Control.cpp(2), D2Helpers.cpp(1), Helpers.cpp(1), JSControl.cpp(1), Profile.cpp(1) |
| `p_D2WIN_FocusedControl`<br>[D2Ptrs.h:463](../../D2Ptrs.h#L463) | VARPTR | 0x3D55CC | 0x7D55CC | `Control*` | - | `Updated 1.14d //007D55CC-BASE unused, but we ought to use it` | ported-1.14d, unused | - |

### D2NET

#### D2NET functions (FUNCPTR) (3)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2NET_SendPacket`<br>[D2Ptrs.h:362](../../D2Ptrs.h#L362) | FUNCPTR | 0x12AE50 | 0x52AE50 | `void __stdcall D2NET_SendPacket(size_t aLen, DWORD arg1, BYTE* aPacket)` | __stdcall | `Updated 1.14d //0052AE50-BASE` | ported-1.14d | JSCore.cpp(1), JSGame.cpp(3), JSUnit.cpp(4) |
| `D2NET_ReceivePacket`<br>[D2Ptrs.h:363](../../D2Ptrs.h#L363) | FUNCPTR | 0x12AEB0 | 0x52AEB0 | `void __fastcall D2NET_ReceivePacket(BYTE* aPacket, DWORD aLen)` | __fastcall | `Updated 1.14d //0052AEB0-BASE` | ported-1.14d | JSCore.cpp(1) |
| `D2NET_ReceivePacket_I`<br>[D2Ptrs.h:364](../../D2Ptrs.h#L364) | FUNCPTR | 0x12B920 | 0x52B920 | `void __fastcall D2NET_ReceivePacket_I(BYTE* aPacket, DWORD aLen, int* arg3)` | __fastcall | `Updated 1.14d //0052B920-BASE` | ported-1.14d, asm-only | D2Intercepts.cpp(1), Patch.h(1); via `GamePacketReceived_Intercept` |

#### D2NET data (VARPTR / data ASMPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2NET_CriticalPacketSection`<br>[D2Ptrs.h:370](../../D2Ptrs.h#L370) | VARPTR | 0xB400 | 0x40B400 | `CRITICAL_SECTION` | - | `unused but we need to use it` | stale-pre-1.14d?, unused | - |

### D2GAME

#### D2GAME functions (FUNCPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2GAME_Rand`<br>[D2Ptrs.h:479](../../D2Ptrs.h#L479) | FUNCPTR | 0x5C370 | 0x45C370 | `DWORD __fastcall D2GAME_Rand(DWORD* seed)` | __fastcall | `Updated 1.14d //0045C370-BASE` | ported-1.14d | JSGame.cpp(1) |
| `D2GAME_exit0`<br>[D2Ptrs.h:481](../../D2Ptrs.h#L481) | FUNCPTR | 0x576F | 0x40576F | `DWORD __fastcall D2GAME_exit0(void)` | __fastcall | `NEW 1.14d //0040576F-BASE` | ported-1.14d, captured-encoded | Patch.h(1) |

### D2LAUNCH

#### D2LAUNCH data (VARPTR / data ASMPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2LAUNCH_BnData`<br>[D2Ptrs.h:430](../../D2Ptrs.h#L430) | VARPTR | 0x3795D4 | 0x7795D4 | `BnetData*` | - | `Updated 1.14d //007795D4-BASE` | ported-1.14d | D2Handlers.cpp(1), JSGame.cpp(2), JSUnit.cpp(1) |

### BNCLIENT

#### BNCLIENT functions (FUNCPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `BNCLIENT_DecodeAndLoadKeys`<br>[D2Ptrs.h:472](../../D2Ptrs.h#L472) | FUNCPTR | 0x1234D0 | 0x5234D0 | `char __cdecl BNCLIENT_DecodeAndLoadKeys(void)` | __cdecl | `Updated 1.14d //005234D0-BASE` | ported-1.14d, unused | - |

#### BNCLIENT data (VARPTR / data ASMPTR) (3)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_BNCLIENT_ClassicKey`<br>[D2Ptrs.h:469](../../D2Ptrs.h#L469) | VARPTR | 0x482744 | 0x882744 | `char*` | - | `Updated 1.14d //00882744-BASE` | ported-1.14d | Core.cpp(1), D2Intercepts.cpp(1), Patch.h(1); via `ClassicSTUB` |
| `p_BNCLIENT_XPacKey`<br>[D2Ptrs.h:470](../../D2Ptrs.h#L470) | VARPTR | 0x48274C | 0x88274C | `char*` | - | `Updated 1.14d //0088274C-BASE` | ported-1.14d | Core.cpp(1), D2Intercepts.cpp(1), Patch.h(1); via `LodSTUB` |
| `p_BNCLIENT_KeyOwner`<br>[D2Ptrs.h:471](../../D2Ptrs.h#L471) | VARPTR | 0x482750 | 0x882750 | `char*` | - | `Updated 1.14d //00882750-BASE` | ported-1.14d | Core.cpp(1) |

#### BNCLIENT code labels (ASMPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `BNCLIENT_DClass`<br>[D2Ptrs.h:466](../../D2Ptrs.h#L466) | ASMPTR | 0x123673 | 0x523673 |  | - | `Updated 1.14d //00523673-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `ClassicSTUB` |
| `BNCLIENT_DLod`<br>[D2Ptrs.h:467](../../D2Ptrs.h#L467) | ASMPTR | 0x12395D | 0x52395D |  | - | `Updated 1.14d //0052395D-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `LodSTUB` |

### STORM

#### STORM data (VARPTR / data ASMPTR) (1)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_STORM_WindowHandlers`<br>[D2Ptrs.h:473](../../D2Ptrs.h#L473) | VARPTR | 0x379300 | 0x779300 | `WindowHandlerHashTable` | - | `Updated 1.14d //00779300-BASE` | ported-1.14d | D2Helpers.cpp(2) |

### D2CMP

#### D2CMP functions (FUNCPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2CMP_InitCellFile`<br>[D2Ptrs.h:410](../../D2Ptrs.h#L410) | FUNCPTR | 0x201340 | 0x601340 | `void __stdcall D2CMP_InitCellFile(LPVOID File, CellFile** Out, LPSTR SourceFile, DWORD Line, DWORD FileVersion, LPSTR Filename)` | __stdcall | `Updated 1.14d //00601340-BASE` | ported-1.14d | D2Helpers.cpp(1) |
| `D2CMP_DeleteCellFile`<br>[D2Ptrs.h:412](../../D2Ptrs.h#L412) | FUNCPTR | 0x201A50 | 0x601A50 | `void __stdcall D2CMP_DeleteCellFile(CellFile* File)` | __stdcall | `Updated 1.14d //00601A50-BASE` | ported-1.14d, unused | - |

### D2MULTI

#### D2MULTI functions (FUNCPTR) (2)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2MULTI_DoChat`<br>[D2Ptrs.h:389](../../D2Ptrs.h#L389) | FUNCPTR | 0x42810 | 0x442810 | `void __fastcall D2MULTI_DoChat(void)` | __fastcall | `Updated 1.14d //00442810-BASE` | ported-1.14d | Core.cpp(1) |
| `D2MULTI_PrintChannelText_`<br>[D2Ptrs.h:390](../../D2Ptrs.h#L390) | FUNCPTR | 0x47AB0 | 0x447AB0 | `void __fastcall D2MULTI_PrintChannelText_(int unused, char* szText, DWORD dwColor)` | __fastcall | `Updated 1.14d //00447AB0-BASE` | ported-1.14d, unused | - |

#### D2MULTI data (VARPTR / data ASMPTR) (3)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `p_D2MULTI_ChatBoxMsg`<br>[D2Ptrs.h:396](../../D2Ptrs.h#L396) | VARPTR | 0x37AE40 | 0x77AE40 | `char`<br>(declared `char*`) | - | `Updated 1.14d //0077AE40-BASE` | ported-1.14d, type-from-usage | Core.cpp(1) |
| `p_D2MULTI_GameListControl`<br>[D2Ptrs.h:397](../../D2Ptrs.h#L397) | VARPTR | 0x398BC0 | 0x798BC0 | `Control*` | - | `Updated 1.14d //00798BC0-BASE` | ported-1.14d, unused | - |
| `p_D2MULTI_ChatInputBox`<br>[D2Ptrs.h:464](../../D2Ptrs.h#L464) | VARPTR | 0x398C80 | 0x798C80 | `DWORD*` | - | `Updated 1.14d //00798C80-BASE` | ported-1.14d, unused | - |

#### D2MULTI code labels (ASMPTR) (4)

| Name | Kind | RVA | VA | Type / prototype | CC | Source comment | Status | Referenced in |
|---|---|---|---|---|---|---|---|---|
| `D2MULTI_ChannelChat_I`<br>[D2Ptrs.h:403](../../D2Ptrs.h#L403) | ASMPTR | 0x14BE6 | 0x414BE6 |  | - | - | stale-pre-1.14d?, unused | - |
| `D2MULTI_ChannelEmote_I`<br>[D2Ptrs.h:403](../../D2Ptrs.h#L403) | ASMPTR | 0x14856 | 0x414856 |  | - | - | stale-pre-1.14d?, unused | - |
| `D2MULTI_ChannelWhisper_I`<br>[D2Ptrs.h:403](../../D2Ptrs.h#L403) | ASMPTR | 0x142F0 | 0x4142F0 |  | - | - | stale-pre-1.14d?, unused | - |
| `D2MULTI_ChannelInput_I`<br>[D2Ptrs.h:404](../../D2Ptrs.h#L404) | ASMPTR | 0x428D0 | 0x4428D0 |  | - | `Updated 1.14d //004428D0-BASE` | ported-1.14d | D2Intercepts.cpp(1), Patch.h(1); via `ChannelInput_Intercept` |
<!-- END GENERATED:symbols -->

## 5. `Patch.h` patch sites

Address view of `Patches[]` (always installed) and `Conditional[]` (installed when the `Vars`
flag is `TRUE`). Mechanics, stub semantics and displaced instructions are in
[patches-and-hooks.md](patches-and-hooks.md). TSV names are `D2BS_PATCH_<handler>`; byte patches
use `BYTES_<value>`; repeated handlers get `_2`.

<!-- BEGIN GENERATED:patches -->
| Name | Kind | DLL string | RVA | VA | Op | Len | Target | Condition | Source comment | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `D2BS_PATCH_GameInput_Intercept`<br>[Patch.h:9](../../Patch.h#L9) | PATCH | `D2Client.dll` | 0x7C89D | 0x47C89D | CALL | 5 | `GameInput_Intercept` | - | `Updated 1.14d //0047C89D-BASE` | ported-1.14d |
| `D2BS_PATCH_GameDraw_Intercept`<br>[Patch.h:10](../../Patch.h#L10) | PATCH | `D2Client.dll` | 0x53B30 | 0x453B30 | JMP | 5 | `GameDraw_Intercept` | - | `Updated 1.14d //00453B30-BASE` | ported-1.14d |
| `D2BS_PATCH_GamePacketReceived_Intercept`<br>[Patch.h:11](../../Patch.h#L11) | PATCH | `D2Client.dll` | 0x5F802 | 0x45F802 | CALL | 5 | `GamePacketReceived_Intercept` | - | `Updated 1.14d //0045F802-BASE` | ported-1.14d |
| `D2BS_PATCH_GamePacketSent_Interception`<br>[Patch.h:12](../../Patch.h#L12) | PATCH | `D2Client.dll` | 0x12AE5A | 0x52AE5A | JMP | 5 | `GamePacketSent_Interception` | - | `Updated 1.14d //0052AE5A-BASE` | ported-1.14d |
| `D2BS_PATCH_GetSelectedUnit_Intercept`<br>[Patch.h:13](../../Patch.h#L13) | PATCH | `D2Client.dll` | 0x62D72 | 0x462D72 | CALL | 5 | `GetSelectedUnit_Intercept` | - | `Updated 1.14d //00462D72-BASE` | ported-1.14d |
| `D2BS_PATCH_PlayerAssignment_Intercept`<br>[Patch.h:14](../../Patch.h#L14) | PATCH | `D2Client.dll` | 0x5E4D5 | 0x45E4D5 | JMP | 5 | `PlayerAssignment_Intercept` | - | `Updated 1.14d //0045E4D5-BASE` | ported-1.14d |
| `D2BS_PATCH_BYTES_C3`<br>[Patch.h:15](../../Patch.h#L15) | PATCH | `D2Client.dll` | 0x68770 | 0x468770 | BYTES | 1 | `0xC3` | - | `Updated 1.14d //00468770-BASE` | ported-1.14d |
| `D2BS_PATCH_BYTES_75`<br>[Patch.h:16](../../Patch.h#L16) | PATCH | `D2CLIENT.DLL` | 0x4EBFB | 0x44EBFB | BYTES | 1 | `0x75` | - | `Congrats Screen //0044EBFB-BASE` | va-only |
| `D2BS_PATCH_CongratsScreen_Intercept`<br>[Patch.h:17](../../Patch.h#L17) | PATCH | `D2Client.dll` | 0x4EBEF | 0x44EBEF | CALL | 5 | `CongratsScreen_Intercept` | - | `Updated 1.14d //0044EBEF-BASE` | ported-1.14d |
| `D2BS_PATCH_GameActChange_Intercept`<br>[Patch.h:18](../../Patch.h#L18) | PATCH | `D2Client.dll` | 0x547B6 | 0x4547B6 | CALL | 5 | `GameActChange_Intercept` | - | `Updated 1.14d //004547B6-BASE` | ported-1.14d |
| `D2BS_PATCH_GameActChange2_Intercept`<br>[Patch.h:19](../../Patch.h#L19) | PATCH | `D2Client.dll` | 0x567EB | 0x4567EB | JMP | 5 | `GameActChange2_Intercept` | - | `Updated 1.14d //004567EB-BASE` | ported-1.14d |
| `D2BS_PATCH_GameLeave_Intercept`<br>[Patch.h:20](../../Patch.h#L20) | PATCH | `D2Client.dll` | 0x4F57C | 0x44F57C | CALL | 5 | `GameLeave_Intercept` | - | `Updated 1.14d //0044F57C-BASE` | ported-1.14d |
| `D2BS_PATCH_GameAttack_Intercept`<br>[Patch.h:21](../../Patch.h#L21) | PATCH | `D2Client.dll` | 0x61704 | 0x461704 | CALL | 5 | `GameAttack_Intercept` | - | `Updated 1.14d //00461704-BASE` | ported-1.14d |
| `D2BS_PATCH_ChatPacketRecv_Interception`<br>[Patch.h:26](../../Patch.h#L26) | PATCH | `BNCLIENT.DLL` | 0x121B20 | 0x521B20 | CALL | 7 | `ChatPacketRecv_Interception` | - | `Updated 1.14d //00521B20-BASE` | ported-1.14d |
| `D2BS_PATCH_Whisper_Intercept`<br>[Patch.h:28](../../Patch.h#L28) | PATCH | `D2Multi.dll` | 0x48813 | 0x448813 | CALL | 7 | `Whisper_Intercept` | - | `Updated 1.14d //00448813-BASE` | ported-1.14d |
| `D2BS_PATCH_ChannelInput_Intercept`<br>[Patch.h:29](../../Patch.h#L29) | PATCH | `D2Multi.dll` | 0x42A61 | 0x442A61 | CALL | 5 | `ChannelInput_Intercept` | - | `Updated 1.14d //00442A61-BASE` | ported-1.14d |
| `D2BS_PATCH_GameDrawOOG_Intercept`<br>[Patch.h:35](../../Patch.h#L35) | PATCH | `D2Win.dll` | 0xF9A0D | 0x4F9A0D | CALL | 5 | `GameDrawOOG_Intercept` | - | `Updated 1.14d //004F9A0D-BASE` | ported-1.14d |
| `D2BS_PATCH_GameCrashFix_Intercept`<br>[Patch.h:37](../../Patch.h#L37) | PATCH | `D2CMP.dll` | 0x2091E5 | 0x6091E5 | CALL | 10 | `GameCrashFix_Intercept` | - | `1.14d //006091E5-BASE` | ported-1.14d |
| `D2BS_PATCH_RealmPacketRecv_Interception`<br>[Patch.h:39](../../Patch.h#L39) | PATCH | `D2MCPClient.dll` | 0x4B1AE | 0x44B1AE | CALL | 6 | `RealmPacketRecv_Interception` | - | - | stale-pre-1.14d? |
| `D2BS_PATCH_LogMessageBoxA_Intercept`<br>[Patch.h:41](../../Patch.h#L41) | PATCH | `Fog.dll` | 0x8CC4 | 0x408CC4 | CALL | 6 | `LogMessageBoxA_Intercept` | - | `Updated 1.14d //00408CC4-BASE` | ported-1.14d |
| `D2BS_PATCH_D2GAME_exit0`<br>[Patch.h:42](../../Patch.h#L42) | PATCH | `Fog.dll` | 0x82E0 | 0x4082E0 | JMP | 6 | `D2GAME_exit0`<br>**installed as 0x576F06** (DLLOFFSET-encoded value captured at static init; intended 0x40576F) | - | `NEW 1.14d //004082E0-BASE` | ported-1.14d, captured-encoded |
| `D2BS_PATCH_ErrorReportLaunch`<br>[Patch.h:44](../../Patch.h#L44) | PATCH | `Fog.dll` | 0x1790 | 0x401790 | JMP | 6 | `ErrorReportLaunch` | - | `NEW 1.14d //00401790-BASE` | ported-1.14d |
| `D2BS_PATCH_ClassicSTUB`<br>[Patch.h:48](../../Patch.h#L48) | COND_PATCH | `BNCLIENT.DLL` | 0x12366C | 0x52366C | JMP | 5 | `ClassicSTUB` | `Vars.bUseRawCDKey` | `Updated 1.14d //0052366C-BASE` | ported-1.14d |
| `D2BS_PATCH_LodSTUB`<br>[Patch.h:49](../../Patch.h#L49) | COND_PATCH | `BNCLIENT.DLL` | 0x123958 | 0x523958 | JMP | 5 | `LodSTUB` | `Vars.bUseRawCDKey` | `Updated 1.14d //00523958-BASE` | ported-1.14d |
| `D2BS_PATCH_FailToJoin`<br>[Patch.h:50](../../Patch.h#L50) | COND_PATCH | `D2CLIENT.DLL` | 0x4EF28 | 0x44EF28 | CALL | 6 | `FailToJoin` | `Vars.bReduceFTJ` | `FTJ Reducer` | stale-pre-1.14d? |
| `D2BS_PATCH_Multi`<br>[Patch.h:51](../../Patch.h#L51) | COND_PATCH | `D2Gfx.DLL` | 0xF5623 | 0x4F5623 | CALL | 6 | `Multi` | `Vars.bMulti` | - | stale-pre-1.14d? |
| `D2BS_PATCH_Windowname`<br>[Patch.h:52](../../Patch.h#L52) | COND_PATCH | `D2Gfx.DLL` | 0xF5831 | 0x4F5831 | CALL | 6 | `Windowname` | `Vars.bMulti` | - | stale-pre-1.14d? |
| `D2BS_PATCH_CacheFix`<br>[Patch.h:53](../../Patch.h#L53) | COND_PATCH | `BNCLIENT.DLL` | 0x11944E | 0x51944E | CALL | 6 | `CacheFix` | `Vars.bCacheFix` | - | stale-pre-1.14d? |
| `D2BS_PATCH_CacheFix_2`<br>[Patch.h:54](../../Patch.h#L54) | COND_PATCH | `BNCLIENT.DLL` | 0x119434 | 0x519434 | CALL | 6 | `CacheFix` | `Vars.bCacheFix` | - | stale-pre-1.14d? |
| `D2BS_PATCH_BYTES_90`<br>[Patch.h:55](../../Patch.h#L55) | COND_PATCH | `D2CLIENT.DLL` | 0x51C31 | 0x451C31 | BYTES | 2 | `0x90` | `Vars.bSleepy` | `Sleep` | stale-pre-1.14d? |
| `D2BS_PATCH_BYTES_EB`<br>[Patch.h:56](../../Patch.h#L56) | COND_PATCH | `D2Win.DLL` | 0xFA66F | 0x4FA66F | BYTES | 1 | `0xEB` | `Vars.bSleepy` | `OOG Sleep` | stale-pre-1.14d? |
<!-- END GENERATED:patches -->

## 6. Hardcoded addresses outside `D2Ptrs.h`

### 6.1 `MPQStats.cpp` `BaseStatTable[]`

Only entries above `0xFFFF` are addresses (TSV rows `D2COMMON_MPQ_<table>_Records` = the pointer
to the record array, `_Count` = the record count). Entries `<= 0xFFFF` are field offsets inside
the structure pointed to by `*p_D2COMMON_sgptDataTable` and belong to [structs.md](structs.md).

<!-- BEGIN GENERATED:mpq -->
`BaseStatTable[]` ([MPQStats.cpp:4](../../MPQStats.cpp#L4)). Rebasing rule, read from source: `dwEntry <= 0xFFFF` is an offset into `*p_D2COMMON_sgptDataTable` (line 41); otherwise it is an absolute 1.14d VA rebased as `VA - 0x400000 + GetModuleHandle(NULL)` (line 45, `d2CommonOff` from [MPQStats.h:10](../../MPQStats.h#L10)); `dwMaxEntriesOffset > 0xFFFF` is rebased the same way (line 49); `0` means "use 0xFF rows" (line 56).

| # | Table | dwEntry | Meaning | dwMaxEntriesOffset | Meaning | TSV rows | Source | Comment |
|---|---|---|---|---|---|---|---|---|
| 0 | `items` | 0x8426F0 | VA 0x8426F0 = RVA 0x4426F0 | 0x8426EC | VA 0x8426EC = RVA 0x4426EC | `D2COMMON_MPQ_items_Records` (RVA 0x4426F0)<br>`D2COMMON_MPQ_items_Count` (RVA 0x4426EC) | [MPQStats.cpp:6](../../MPQStats.cpp#L6) | - |
| 1 | `monstats` | 0xA78 | sgptDataTable+0xA78 | 0xA80 | sgptDataTable+0xA80 | - | [MPQStats.cpp:7](../../MPQStats.cpp#L7) | - |
| 2 | `skilldesc` | 0xB8C | sgptDataTable+0xB8C | 0xB94 | sgptDataTable+0xB94 | - | [MPQStats.cpp:8](../../MPQStats.cpp#L8) | - |
| 3 | `skills` | 0xB98 | sgptDataTable+0xB98 | 0xBA0 | sgptDataTable+0xBA0 | - | [MPQStats.cpp:9](../../MPQStats.cpp#L9) | - |
| 4 | `objects` | 0x96D470 | VA 0x96D470 = RVA 0x56D470 | 0x96D474 | VA 0x96D474 = RVA 0x56D474 | `D2COMMON_MPQ_objects_Records` (RVA 0x56D470)<br>`D2COMMON_MPQ_objects_Count` (RVA 0x56D474) | [MPQStats.cpp:10](../../MPQStats.cpp#L10) | - |
| 5 | `missiles` | 0xB64 | sgptDataTable+0xB64 | 0xB6C | sgptDataTable+0xB6C | - | [MPQStats.cpp:11](../../MPQStats.cpp#L11) | - |
| 6 | `monstats2` | 0xA90 | sgptDataTable+0xA90 | 0xA98 | sgptDataTable+0xA98 | - | [MPQStats.cpp:12](../../MPQStats.cpp#L12) | - |
| 7 | `itemstatcost` | 0xBCC | sgptDataTable+0xBCC | 0xBD4 | sgptDataTable+0xBD4 | - | [MPQStats.cpp:13](../../MPQStats.cpp#L13) | - |
| 8 | `levels` | 0xC58 | sgptDataTable+0xC58 | 0xC5C | sgptDataTable+0xC5C | - | [MPQStats.cpp:14](../../MPQStats.cpp#L14) | - |
| 9 | `leveldefs` | 0xC60 | sgptDataTable+0xC60 | 0x0 | none (0xFF rows) | - | [MPQStats.cpp:15](../../MPQStats.cpp#L15) | - |
| 10 | `lvlmaze` | 0x96CA08 | VA 0x96CA08 = RVA 0x56CA08 | 0x96CA0C | VA 0x96CA0C = RVA 0x56CA0C | `D2COMMON_MPQ_lvlmaze_Records` (RVA 0x56CA08)<br>`D2COMMON_MPQ_lvlmaze_Count` (RVA 0x56CA0C) | [MPQStats.cpp:16](../../MPQStats.cpp#L16) | - |
| 11 | `lvlsub` | 0x96CA10 | VA 0x96CA10 = RVA 0x56CA10 | 0x96CA14 | VA 0x96CA14 = RVA 0x56CA14 | `D2COMMON_MPQ_lvlsub_Records` (RVA 0x56CA10)<br>`D2COMMON_MPQ_lvlsub_Count` (RVA 0x56CA14) | [MPQStats.cpp:17](../../MPQStats.cpp#L17) | `v` |
| 12 | `lvlwarp` | 0x96CA00 | VA 0x96CA00 = RVA 0x56CA00 | 0x96CA04 | VA 0x96CA04 = RVA 0x56CA04 | `D2COMMON_MPQ_lvlwarp_Records` (RVA 0x56CA00)<br>`D2COMMON_MPQ_lvlwarp_Count` (RVA 0x56CA04) | [MPQStats.cpp:18](../../MPQStats.cpp#L18) | `v` |
| 13 | `lvlprest` | 0xC64 | sgptDataTable+0xC64 | 0xC68 | sgptDataTable+0xC68 | - | [MPQStats.cpp:19](../../MPQStats.cpp#L19) | - |
| 14 | `lvltypes` | 0x96C9F0 | VA 0x96C9F0 = RVA 0x56C9F0 | 0x96C9FC | VA 0x96C9FC = RVA 0x56C9FC | `D2COMMON_MPQ_lvltypes_Records` (RVA 0x56C9F0)<br>`D2COMMON_MPQ_lvltypes_Count` (RVA 0x56C9FC) | [MPQStats.cpp:20](../../MPQStats.cpp#L20) | `v - Fixed to fully dump the same as d2jsp - TechnoHunter` |
| 15 | `charstats` | 0xBC4 | sgptDataTable+0xBC4 | 0xBC8 | sgptDataTable+0xBC8 | - | [MPQStats.cpp:21](../../MPQStats.cpp#L21) | - |
| 16 | `setitems` | 0xC18 | sgptDataTable+0xC18 | 0xC1C | sgptDataTable+0xC1C | - | [MPQStats.cpp:22](../../MPQStats.cpp#L22) | - |
| 17 | `uniqueitems` | 0xC24 | sgptDataTable+0xC24 | 0xC28 | sgptDataTable+0xC28 | - | [MPQStats.cpp:23](../../MPQStats.cpp#L23) | - |
| 18 | `sets` | 0xC0C | sgptDataTable+0xC0C | 0xC10 | sgptDataTable+0xC10 | - | [MPQStats.cpp:24](../../MPQStats.cpp#L24) | - |
| 19 | `itemtypes` | 0xBF8 | sgptDataTable+0xBF8 | 0xBFC | sgptDataTable+0xBFC | - | [MPQStats.cpp:25](../../MPQStats.cpp#L25) | - |
| 20 | `runes` | 0x96CA9C | VA 0x96CA9C = RVA 0x56CA9C | 0x96CA98 | VA 0x96CA98 = RVA 0x56CA98 | `D2COMMON_MPQ_runes_Records` (RVA 0x56CA9C)<br>`D2COMMON_MPQ_runes_Count` (RVA 0x56CA98) | [MPQStats.cpp:26](../../MPQStats.cpp#L26) | `v` |
| 21 | `cubemain` | 0x96D628 | VA 0x96D628 = RVA 0x56D628 | 0x96D62C | VA 0x96D62C = RVA 0x56D62C | `D2COMMON_MPQ_cubemain_Records` (RVA 0x56D628)<br>`D2COMMON_MPQ_cubemain_Count` (RVA 0x56D62C) | [MPQStats.cpp:27](../../MPQStats.cpp#L27) | `v` |
| 22 | `gems` | 0x96CA94 | VA 0x96CA94 = RVA 0x56CA94 | 0x96CA90 | VA 0x96CA90 = RVA 0x56CA90 | `D2COMMON_MPQ_gems_Records` (RVA 0x56CA94)<br>`D2COMMON_MPQ_gems_Count` (RVA 0x56CA90) | [MPQStats.cpp:28](../../MPQStats.cpp#L28) | - |
| 23 | `experience` | 0x96C8A8 | VA 0x96C8A8 = RVA 0x56C8A8 | 0x0 | none (0xFF rows) | `D2COMMON_MPQ_experience_Records` (RVA 0x56C8A8) | [MPQStats.cpp:29](../../MPQStats.cpp#L29) | `v - doesnt tap the last 2 levels of exp, ends at level 97 - TechnoHunter` |
| 24 | `pettable` | 0xBE8 | sgptDataTable+0xBE8 | 0xBF0 | sgptDataTable+0xBF0 | - | [MPQStats.cpp:30](../../MPQStats.cpp#L30) | - |
| 25 | `superuniques` | 0xAD4 | sgptDataTable+0xAD4 | 0xADC | sgptDataTable+0xADC | - | [MPQStats.cpp:31](../../MPQStats.cpp#L31) | - |

`FillBaseStat()` call sites outside MPQStats.cpp (who can reach an absolute-VA table):

| Site | Function | JS name | Table argument | Absolute-VA table? |
|---|---|---|---|---|
| [D2NetHandlers.cpp:100](../../D2NetHandlers.cpp#L100) | `EventMessagesHandler` | - | `tables[param2]` | dynamic |
| [JSGame.cpp:890](../../JSGame.cpp#L890) | `my_getSkillById` | `global_funcs.getSkillById` | `"skills"` | no (sgptDataTable-relative) |
| [JSGame.cpp:891](../../JSGame.cpp#L891) | `my_getSkillById` | `global_funcs.getSkillById` | `"skilldesc"` | no (sgptDataTable-relative) |
| [JSGame.cpp:1212](../../JSGame.cpp#L1212) | `my_getBaseStat` | `global_funcs.getBaseStat` | `nBaseStat` | dynamic |
| [JSUnit.cpp:864](../../JSUnit.cpp#L864) | `unit_interact` | `unit_methods.interact` | `"levels"` | no (sgptDataTable-relative) |
| [JSUnit.cpp:1270](../../JSUnit.cpp#L1270) | `item_getItemCost` | `unit_methods.getItemCost` | `"monstats"` | no (sgptDataTable-relative) |
| [JSUnit.cpp:1393](../../JSUnit.cpp#L1393) | `unit_getSkill` | `unit_methods.getSkill` | `"skills"` | no (sgptDataTable-relative) |
| [JSUnit.cpp:1394](../../JSUnit.cpp#L1394) | `unit_getSkill` | `unit_methods.getSkill` | `"skilldesc"` | no (sgptDataTable-relative) |
| [JSUnit.cpp:1401](../../JSUnit.cpp#L1401) | `unit_getSkill` | `unit_methods.getSkill` | `"skills"` | no (sgptDataTable-relative) |
| [JSUnit.cpp:1402](../../JSUnit.cpp#L1402) | `unit_getSkill` | `unit_methods.getSkill` | `"skilldesc"` | no (sgptDataTable-relative) |
<!-- END GENERATED:mpq -->

### 6.2 Other `GetDllOffset()` call sites

Every `GetDllOffset(` call outside `Offset.cpp`, `Offset.h`, `D2Ptrs.h` and `Patch.h` (the
remaining calls are the resolver itself: [Offset.cpp:17](../../Offset.cpp#L17) in
`DefineOffsets()` and [Offset.cpp:35](../../Offset.cpp#L35) in `GetDllOffset(int)`). The
JSUnit sites write a flag byte and the item pointer, call `D2CLIENT_LoadItemDesc`, then read
2047 bytes of wide text ([JSUnit.cpp:450-459](../../JSUnit.cpp#L450-L459)). The names
`D2CLIENT_ItemDescFlag`, `D2CLIENT_ItemDescUnit`, `D2WIN_ItemDescText` are this document's labels;
the game's names are unknown.

<!-- BEGIN GENERATED:gdo-sites -->
| Site | Call | VA | RVA | TSV row | Code |
|---|---|---|---|---|---|
| [JSUnit.cpp:453](../../JSUnit.cpp#L453) | `GetDllOffset("D2Client.dll", 0x7BCBE8 - 0x400000)` | 0x7BCBE8 | 0x3BCBE8 | `D2CLIENT_ItemDescFlag` | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBE8 - 0x400000), bBuffer, 1` |
| [JSUnit.cpp:454](../../JSUnit.cpp#L454) | `GetDllOffset("D2Client.dll", 0x7BCBF4 - 0x400000)` | 0x7BCBF4 | 0x3BCBF4 | `D2CLIENT_ItemDescUnit` | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBF4 - 0x400000), &pUnit, 4,` |
| [JSUnit.cpp:458](../../JSUnit.cpp#L458) | `GetDllOffset("D2Win.dll", 0x841EC8 - 0x400000)` | 0x841EC8 | 0x441EC8 | `D2WIN_ItemDescText` | `ReadProcessBYTES(GetCurrentProcess(), GetDllOffset("D2Win.dll", 0x841EC8 - 0x400000), wBuffer, 2047);` |
<!-- END GENERATED:gdo-sites -->

### 6.3 Numeric literals inside `__asm` blocks

<!-- BEGIN GENERATED:asm-literals -->
Every numeric literal inside an `__asm { }` block of the scanned sources. `addr?` is `yes` when the value is >= 0x10000 (could be an absolute address); everything else is an immediate, a stack/struct displacement or a constant.

| Site | Function | Literal | Value | addr? | Instruction |
|---|---|---|---|---|---|
| [Core.cpp:75](../../Core.cpp#L75) | `Say_ASM` | `0x110` | 0x110 | no | `SUB ESP,0x110` |
| [Core.cpp:79](../../Core.cpp#L79) | `Say_ASM` | `8` | 0x8 | no | `MOV EBX, [EBP+8]` |
| [D2Helpers.cpp:770](../../D2Helpers.cpp#L770) | `D2CLIENT_ClickShopItem_ASM` | `1` | 0x1 | no | `push 1` |
| [D2Helpers.cpp:825](../../D2Helpers.cpp#L825) | `D2CLIENT_GetItemDesc_ASM` | `1` | 0x1 | no | `PUSH 1` |
| [D2Helpers.cpp:836](../../D2Helpers.cpp#L836) | `D2COMMON_DisplayOverheadMsg_ASM` | `0xA4` | 0xA4 | no | `LEA ESI, [ECX+0xA4]` |
| [D2Helpers.cpp:837](../../D2Helpers.cpp#L837) | `D2COMMON_DisplayOverheadMsg_ASM` | `0xA4` | 0xA4 | no | `MOV EAX, [ECX+0xA4]` |
| [D2Helpers.cpp:840](../../D2Helpers.cpp#L840) | `D2COMMON_DisplayOverheadMsg_ASM` | `0` | 0x0 | no | `PUSH 0` |
| [D2Helpers.cpp:876](../../D2Helpers.cpp#L876) | `D2CLIENT_TakeWaypoint` | `0x20` | 0x20 | no | `SUB ESP, 0x20` |
| [D2Helpers.cpp:880](../../D2Helpers.cpp#L880) | `D2CLIENT_TakeWaypoint` | `0x20` | 0x20 | no | `AND DWORD PTR SS:[EBP-0x20],0` |
| [D2Helpers.cpp:880](../../D2Helpers.cpp#L880) | `D2CLIENT_TakeWaypoint` | `0` | 0x0 | no | `AND DWORD PTR SS:[EBP-0x20],0` |
| [D2Helpers.cpp:881](../../D2Helpers.cpp#L881) | `D2CLIENT_TakeWaypoint` | `0` | 0x0 | no | `PUSH 0` |
| [D2Helpers.cpp:887](../../D2Helpers.cpp#L887) | `D2CLIENT_TakeWaypoint` | `8` | 0x8 | no | `RETN 8` |
| [D2Helpers.cpp:896](../../D2Helpers.cpp#L896) | `D2CLIENT_TakeWaypoint` | `1` | 0x1 | no | `MOV EBX, 1` |
| [D2Helpers.cpp:897](../../D2Helpers.cpp#L897) | `D2CLIENT_TakeWaypoint` | `8` | 0x8 | no | `MOV EDX, DWORD PTR SS : [EBP + 8]` |
| [D2Helpers.cpp:898](../../D2Helpers.cpp#L898) | `D2CLIENT_TakeWaypoint` | `0xC` | 0xC | no | `MOV ECX, DWORD PTR SS : [EBP + 0xC]` |
| [D2Helpers.cpp:900](../../D2Helpers.cpp#L900) | `D2CLIENT_TakeWaypoint` | `0x20` | 0x20 | no | `LEA ESI, DWORD PTR SS : [EBP - 0x20]` |
| [D2Intercepts.cpp:14](../../D2Intercepts.cpp#L14) | `RealmPacketRecv_Interception` | `0` | 0x0 | no | `cmp eax, 0` |
| [D2Intercepts.cpp:34](../../D2Intercepts.cpp#L34) | `GamePacketReceived_Intercept` | `0` | 0x0 | no | `mov edx, 0` |
| [D2Intercepts.cpp:37](../../D2Intercepts.cpp#L37) | `GamePacketReceived_Intercept` | `4` | 0x4 | no | `mov eax, [esp + 4]` |
| [D2Intercepts.cpp:41](../../D2Intercepts.cpp#L41) | `GamePacketReceived_Intercept` | `4` | 0x4 | no | `ret 4` |
| [D2Intercepts.cpp:50](../../D2Intercepts.cpp#L50) | `GamePacketSent_Interception` | `0x22` | 0x22 | no | `mov ecx, [esp + 0x22 + 4 + 0xC]` |
| [D2Intercepts.cpp:50](../../D2Intercepts.cpp#L50) | `GamePacketSent_Interception` | `4` | 0x4 | no | `mov ecx, [esp + 0x22 + 4 + 0xC]` |
| [D2Intercepts.cpp:50](../../D2Intercepts.cpp#L50) | `GamePacketSent_Interception` | `0xC` | 0xC | no | `mov ecx, [esp + 0x22 + 4 + 0xC]` |
| [D2Intercepts.cpp:51](../../D2Intercepts.cpp#L51) | `GamePacketSent_Interception` | `0x22` | 0x22 | no | `mov edx, [esp + 0x22 + 4 + 0x4]` |
| [D2Intercepts.cpp:51](../../D2Intercepts.cpp#L51) | `GamePacketSent_Interception` | `4` | 0x4 | no | `mov edx, [esp + 0x22 + 4 + 0x4]` |
| [D2Intercepts.cpp:51](../../D2Intercepts.cpp#L51) | `GamePacketSent_Interception` | `0x4` | 0x4 | no | `mov edx, [esp + 0x22 + 4 + 0x4]` |
| [D2Intercepts.cpp:58](../../D2Intercepts.cpp#L58) | `GamePacketSent_Interception` | `0x4` | 0x4 | no | `mov[esp + 0x4 + 4 + 2], 0` |
| [D2Intercepts.cpp:58](../../D2Intercepts.cpp#L58) | `GamePacketSent_Interception` | `4` | 0x4 | no | `mov[esp + 0x4 + 4 + 2], 0` |
| [D2Intercepts.cpp:58](../../D2Intercepts.cpp#L58) | `GamePacketSent_Interception` | `2` | 0x2 | no | `mov[esp + 0x4 + 4 + 2], 0` |
| [D2Intercepts.cpp:58](../../D2Intercepts.cpp#L58) | `GamePacketSent_Interception` | `0` | 0x0 | no | `mov[esp + 0x4 + 4 + 2], 0` |
| [D2Intercepts.cpp:65](../../D2Intercepts.cpp#L65) | `GamePacketSent_Interception` | `0Ch` | 0xC | no | `ret 0Ch` |
| [D2Intercepts.cpp:80](../../D2Intercepts.cpp#L80) | `GameInput_Intercept` | `1` | 0x1 | no | `cmp eax, -1` |
| [D2Intercepts.cpp:109](../../D2Intercepts.cpp#L109) | `Whisper_Intercept` | `674h` | 0x674 | no | `mov [esp-674h-4+4], edi` |
| [D2Intercepts.cpp:109](../../D2Intercepts.cpp#L109) | `Whisper_Intercept` | `4` | 0x4 | no | `mov [esp-674h-4+4], edi` |
| [D2Intercepts.cpp:109](../../D2Intercepts.cpp#L109) | `Whisper_Intercept` | `4` | 0x4 | no | `mov [esp-674h-4+4], edi` |
| [D2Intercepts.cpp:111](../../D2Intercepts.cpp#L111) | `Whisper_Intercept` | `678h` | 0x678 | no | `sub esp, 678h` |
| [D2Intercepts.cpp:114](../../D2Intercepts.cpp#L114) | `Whisper_Intercept` | `8` | 0x8 | no | `mov edx, [ebp+8]` |
| [D2Intercepts.cpp:124](../../D2Intercepts.cpp#L124) | `ChatPacketRecv_Interception` | `8` | 0x8 | no | `mov edx, [ebp + 8]` |
| [D2Intercepts.cpp:127](../../D2Intercepts.cpp#L127) | `ChatPacketRecv_Interception` | `4` | 0x4 | no | `sub ecx, 4` |
| [D2Intercepts.cpp:128](../../D2Intercepts.cpp#L128) | `ChatPacketRecv_Interception` | `4` | 0x4 | no | `add edx, 4` |
| [D2Intercepts.cpp:146](../../D2Intercepts.cpp#L146) | `GameAttack_Intercept` | `1` | 0x1 | no | `cmp eax, -1` |
| [D2Intercepts.cpp:152](../../D2Intercepts.cpp#L152) | `GameAttack_Intercept` | `0` | 0x0 | no | `cmp eax, 0` |
| [D2Intercepts.cpp:155](../../D2Intercepts.cpp#L155) | `GameAttack_Intercept` | `0x08` | 0x8 | no | `mov [esp+0x08+0x4+0x4], 1` |
| [D2Intercepts.cpp:155](../../D2Intercepts.cpp#L155) | `GameAttack_Intercept` | `0x4` | 0x4 | no | `mov [esp+0x08+0x4+0x4], 1` |
| [D2Intercepts.cpp:155](../../D2Intercepts.cpp#L155) | `GameAttack_Intercept` | `0x4` | 0x4 | no | `mov [esp+0x08+0x4+0x4], 1` |
| [D2Intercepts.cpp:155](../../D2Intercepts.cpp#L155) | `GameAttack_Intercept` | `1` | 0x1 | no | `mov [esp+0x08+0x4+0x4], 1` |
| [D2Intercepts.cpp:177](../../D2Intercepts.cpp#L177) | `GameCrashFix_Intercept` | `0` | 0x0 | no | `CMP ECX, 0` |
| [D2Intercepts.cpp:179](../../D2Intercepts.cpp#L179) | `GameCrashFix_Intercept` | `0x10` | 0x10 | no | `MOV DWORD PTR DS:[ECX+0x10],EDX` |
| [D2Intercepts.cpp:181](../../D2Intercepts.cpp#L181) | `GameCrashFix_Intercept` | `0xC` | 0xC | no | `MOV DWORD PTR DS:[EAX+0xC],0` |
| [D2Intercepts.cpp:181](../../D2Intercepts.cpp#L181) | `GameCrashFix_Intercept` | `0` | 0x0 | no | `MOV DWORD PTR DS:[EAX+0xC],0` |
| [D2Intercepts.cpp:207](../../D2Intercepts.cpp#L207) | `GameActChange_Intercept` | `0` | 0x0 | no | `CMP [Vars.bChangedAct], 0` |
| [D2Intercepts.cpp:208](../../D2Intercepts.cpp#L208) | `GameActChange_Intercept` | `0` | 0x0 | no | `MOV [Vars.bChangedAct], 0` |
| [D2Intercepts.cpp:218](../../D2Intercepts.cpp#L218) | `GameActChange2_Intercept` | `1` | 0x1 | no | `MOV [Vars.bChangedAct], 1` |
| [D2Intercepts.cpp:264](../../D2Intercepts.cpp#L264) | `RemoveUnit_Intercept` | `4` | 0x4 | no | `push dword ptr ds:[esi+edx*4]` |
| [D2Intercepts.cpp:267](../../D2Intercepts.cpp#L267) | `RemoveUnit_Intercept` | `0xE4` | 0xE4 | no | `mov eax,dword ptr ds:[ecx+0xE4]` |
| [D2Intercepts.cpp:268](../../D2Intercepts.cpp#L268) | `RemoveUnit_Intercept` | `4` | 0x4 | no | `mov DWORD PTR ds:[esi+edx*4], eax` |
| [D2Intercepts.cpp:292](../../D2Intercepts.cpp#L292) | `FailToJoin` | `4000` | 0xFA0 | no | `cmp esi, 4000` |
<!-- END GENERATED:asm-literals -->

### 6.4 Absolute-VA-looking literals

<!-- BEGIN GENERATED:abs-literals -->
Hex literals in `[0x400000, 0x1000000)` (1.14d Game.exe VA range) or `[0x6F000000, 0x70000000)` (1.13 DLL range) outside `D2Ptrs.h`/`Patch.h`, with the classification applied by the generator.

| Site | Literal | Classification | Code |
|---|---|---|---|
| [Constants.h:863](../../Constants.h#L863) | `0x00400000` | item flag bit (ITEM_FLAG_ETHEREAL), not an address | `#define ITEM_FLAG_ETHEREAL 0x00400000     // Ethreal` |
| [D2Handlers.cpp:281](../../D2Handlers.cpp#L281) | `0xFF0000` | scan-code mask on lParam, not an address | `if (GetKeyboardState(layout) && ToAscii(wParam, (lParam & 0xFF0000), layout, out, 0) != 0) {` |
| [JSUnit.cpp:453](../../JSUnit.cpp#L453) | `0x7BCBE8` | emitted as TSV row(s) (D2CLIENT_ItemDescFlag) | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBE8 - 0x400000), bBuffer, 1` |
| [JSUnit.cpp:453](../../JSUnit.cpp#L453) | `0x400000` | emitted as TSV row(s) (D2CLIENT_ItemDescFlag) | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBE8 - 0x400000), bBuffer, 1` |
| [JSUnit.cpp:454](../../JSUnit.cpp#L454) | `0x7BCBF4` | emitted as TSV row(s) (D2CLIENT_ItemDescUnit) | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBF4 - 0x400000), &pUnit, 4,` |
| [JSUnit.cpp:454](../../JSUnit.cpp#L454) | `0x400000` | emitted as TSV row(s) (D2CLIENT_ItemDescUnit) | `::WriteProcessMemory(GetCurrentProcess(), (void*)GetDllOffset("D2Client.dll", 0x7BCBF4 - 0x400000), &pUnit, 4,` |
| [JSUnit.cpp:458](../../JSUnit.cpp#L458) | `0x841EC8` | emitted as TSV row(s) (D2WIN_ItemDescText) | `ReadProcessBYTES(GetCurrentProcess(), GetDllOffset("D2Win.dll", 0x841EC8 - 0x400000), wBuffer, 2047);` |
| [JSUnit.cpp:458](../../JSUnit.cpp#L458) | `0x400000` | emitted as TSV row(s) (D2WIN_ItemDescText) | `ReadProcessBYTES(GetCurrentProcess(), GetDllOffset("D2Win.dll", 0x841EC8 - 0x400000), wBuffer, 2047);` |
| [MPQStats.cpp:6](../../MPQStats.cpp#L6) | `0x8426F0` | emitted as TSV row(s) (D2COMMON_MPQ_items_Records, D2COMMON_MPQ_items_Count) | `{0x8426F0, 0x8426EC, itemTable, "items", ARRAYSIZE(itemTable), 0xFFFF},` |
| [MPQStats.cpp:6](../../MPQStats.cpp#L6) | `0x8426EC` | emitted as TSV row(s) (D2COMMON_MPQ_items_Records, D2COMMON_MPQ_items_Count) | `{0x8426F0, 0x8426EC, itemTable, "items", ARRAYSIZE(itemTable), 0xFFFF},` |
| [MPQStats.cpp:10](../../MPQStats.cpp#L10) | `0x96D470` | emitted as TSV row(s) (D2COMMON_MPQ_objects_Records, D2COMMON_MPQ_objects_Count) | `{0x96D470, 0x96D474, objectsTable, "objects", ARRAYSIZE(objectsTable), 0xFFFF},` |
| [MPQStats.cpp:10](../../MPQStats.cpp#L10) | `0x96D474` | emitted as TSV row(s) (D2COMMON_MPQ_objects_Records, D2COMMON_MPQ_objects_Count) | `{0x96D470, 0x96D474, objectsTable, "objects", ARRAYSIZE(objectsTable), 0xFFFF},` |
| [MPQStats.cpp:16](../../MPQStats.cpp#L16) | `0x96CA08` | emitted as TSV row(s) (D2COMMON_MPQ_lvlmaze_Records, D2COMMON_MPQ_lvlmaze_Count) | `{0x96CA08, 0x96CA0C, lvlmazeTable, "lvlmaze", ARRAYSIZE(lvlmazeTable), 0xFFFF},` |
| [MPQStats.cpp:16](../../MPQStats.cpp#L16) | `0x96CA0C` | emitted as TSV row(s) (D2COMMON_MPQ_lvlmaze_Records, D2COMMON_MPQ_lvlmaze_Count) | `{0x96CA08, 0x96CA0C, lvlmazeTable, "lvlmaze", ARRAYSIZE(lvlmazeTable), 0xFFFF},` |
| [MPQStats.cpp:17](../../MPQStats.cpp#L17) | `0x96CA10` | emitted as TSV row(s) (D2COMMON_MPQ_lvlsub_Records, D2COMMON_MPQ_lvlsub_Count) | `{0x96CA10, 0x96CA14, lvlsubTable, "lvlsub", ARRAYSIZE(lvlsubTable), 0xFFFF},    // v` |
| [MPQStats.cpp:17](../../MPQStats.cpp#L17) | `0x96CA14` | emitted as TSV row(s) (D2COMMON_MPQ_lvlsub_Records, D2COMMON_MPQ_lvlsub_Count) | `{0x96CA10, 0x96CA14, lvlsubTable, "lvlsub", ARRAYSIZE(lvlsubTable), 0xFFFF},    // v` |
| [MPQStats.cpp:18](../../MPQStats.cpp#L18) | `0x96CA00` | emitted as TSV row(s) (D2COMMON_MPQ_lvlwarp_Records, D2COMMON_MPQ_lvlwarp_Count) | `{0x96CA00, 0x96CA04, lvlwarpTable, "lvlwarp", ARRAYSIZE(lvlwarpTable), 0xFFFF}, // v` |
| [MPQStats.cpp:18](../../MPQStats.cpp#L18) | `0x96CA04` | emitted as TSV row(s) (D2COMMON_MPQ_lvlwarp_Records, D2COMMON_MPQ_lvlwarp_Count) | `{0x96CA00, 0x96CA04, lvlwarpTable, "lvlwarp", ARRAYSIZE(lvlwarpTable), 0xFFFF}, // v` |
| [MPQStats.cpp:20](../../MPQStats.cpp#L20) | `0x96C9F0` | emitted as TSV row(s) (D2COMMON_MPQ_lvltypes_Records, D2COMMON_MPQ_lvltypes_Count) | `{0x96C9F0, 0x96C9FC, lvltypesTable, "lvltypes", ARRAYSIZE(lvltypesTable), 0xFFFF}, // v - Fixed to fully dump ` |
| [MPQStats.cpp:20](../../MPQStats.cpp#L20) | `0x96C9FC` | emitted as TSV row(s) (D2COMMON_MPQ_lvltypes_Records, D2COMMON_MPQ_lvltypes_Count) | `{0x96C9F0, 0x96C9FC, lvltypesTable, "lvltypes", ARRAYSIZE(lvltypesTable), 0xFFFF}, // v - Fixed to fully dump ` |
| [MPQStats.cpp:26](../../MPQStats.cpp#L26) | `0x96CA9C` | emitted as TSV row(s) (D2COMMON_MPQ_runes_Records, D2COMMON_MPQ_runes_Count) | `{0x96CA9C, 0x96CA98, runesTable, "runes", ARRAYSIZE(runesTable), 0xFFFF},          // v` |
| [MPQStats.cpp:26](../../MPQStats.cpp#L26) | `0x96CA98` | emitted as TSV row(s) (D2COMMON_MPQ_runes_Records, D2COMMON_MPQ_runes_Count) | `{0x96CA9C, 0x96CA98, runesTable, "runes", ARRAYSIZE(runesTable), 0xFFFF},          // v` |
| [MPQStats.cpp:27](../../MPQStats.cpp#L27) | `0x96D628` | emitted as TSV row(s) (D2COMMON_MPQ_cubemain_Records, D2COMMON_MPQ_cubemain_Count) | `{0x96D628, 0x96D62C, cubemainTable, "cubemain", ARRAYSIZE(cubemainTable), 0xFFFF}, // v` |
| [MPQStats.cpp:27](../../MPQStats.cpp#L27) | `0x96D62C` | emitted as TSV row(s) (D2COMMON_MPQ_cubemain_Records, D2COMMON_MPQ_cubemain_Count) | `{0x96D628, 0x96D62C, cubemainTable, "cubemain", ARRAYSIZE(cubemainTable), 0xFFFF}, // v` |
| [MPQStats.cpp:28](../../MPQStats.cpp#L28) | `0x96CA94` | emitted as TSV row(s) (D2COMMON_MPQ_gems_Records, D2COMMON_MPQ_gems_Count) | `{0x96CA94, 0x96CA90, gemsTable, "gems", ARRAYSIZE(gemsTable), 0xFFFF},` |
| [MPQStats.cpp:28](../../MPQStats.cpp#L28) | `0x96CA90` | emitted as TSV row(s) (D2COMMON_MPQ_gems_Records, D2COMMON_MPQ_gems_Count) | `{0x96CA94, 0x96CA90, gemsTable, "gems", ARRAYSIZE(gemsTable), 0xFFFF},` |
| [MPQStats.cpp:29](../../MPQStats.cpp#L29) | `0x96C8A8` | emitted as TSV row(s) (D2COMMON_MPQ_experience_Records) | `{0x96C8A8, 0x0, experienceTable, "experience", ARRAYSIZE(experienceTable), 0xFFFF}, // v - doesnt tap the last` |
| [MPQStats.cpp:45](../../MPQStats.cpp#L45) | `0x400000` | image base subtracted when rebasing BaseStatTable VAs | `dwTableOffset = DWORD((dwTableOffset - 0x400000) + d2CommonOff);` |
| [MPQStats.cpp:50](../../MPQStats.cpp#L50) | `0x400000` | image base subtracted when rebasing BaseStatTable VAs | `dwMaxEntriesOffset = DWORD((dwMaxEntriesOffset - 0x400000) + d2CommonOff);` |
<!-- END GENERATED:abs-literals -->

## 7. Declared vs used types, asm-only prototypes

### 7.1 `VARPTR` casts

<!-- BEGIN GENERATED:casts -->
`(T*)p_X` casts where `T*` differs from the `p_` pointer type declared by `VARPTR`. When every use of a `VARPTR` is such a cast (column *TSV type*), the generator emits the cast's pointee as the TSV type and adds `type-from-usage`.

| Site | Pointer | Declared (`p_` type) | Cast to | TSV type | Code |
|---|---|---|---|---|---|
| [Core.cpp:96](../../Core.cpp#L96) | `p_D2CLIENT_ChatMsg` | `wchar_t**` | `wchar_t*` | `wchar_t` | `memcpy((wchar_t*)p_D2CLIENT_ChatMsg, szBuffer, (len + 1) * sizeof(wchar_t));` |
| [Core.cpp:126](../../Core.cpp#L126) | `p_D2MULTI_ChatBoxMsg` | `char**` | `char*` | `char` | `memcpy((char*)p_D2MULTI_ChatBoxMsg, lBuffer, strlen(lBuffer) + 1);` |
| [D2Helpers.cpp:414](../../D2Helpers.cpp#L414) | `p_D2CLIENT_NPCMenu` | `NPCMenu**` | `NPCMenu*` | `NPCMenu` | `NPCMenu* pMenu = (NPCMenu*)p_D2CLIENT_NPCMenu;` |
| [JSGame.cpp:497](../../JSGame.cpp#L497) | `p_D2CLIENT_InventoryLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_InventoryLayout;` |
| [JSGame.cpp:501](../../JSGame.cpp#L501) | `p_D2CLIENT_StashLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_StashLayout;` |
| [JSGame.cpp:505](../../JSGame.cpp#L505) | `p_D2CLIENT_CubeLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_CubeLayout;` |
| [JSGame.cpp:587](../../JSGame.cpp#L587) | `p_D2CLIENT_InventoryLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_InventoryLayout;` |
| [JSGame.cpp:591](../../JSGame.cpp#L591) | `p_D2CLIENT_TradeLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_TradeLayout;` |
| [JSGame.cpp:595](../../JSGame.cpp#L595) | `p_D2CLIENT_CubeLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_CubeLayout;` |
| [JSGame.cpp:599](../../JSGame.cpp#L599) | `p_D2CLIENT_StashLayout` | `InventoryLayout**` | `InventoryLayout*` | `InventoryLayout` | `pLayout = (InventoryLayout*)p_D2CLIENT_StashLayout;` |
<!-- END GENERATED:casts -->

`D2CLIENT_StoreLayout` and `D2CLIENT_MercLayout` are declared like the other layout globals but
unused, so the generator keeps their declared `InventoryLayout*`; by analogy they are probably
structs too (unverified).

### 7.2 `asm-only` FUNCPTRs

<!-- BEGIN GENERATED:asm-only -->
FUNCPTRs that are only ever reached from inline-asm stubs. The C prototype in `D2Ptrs.h` is never used by the compiler for these calls; the stub's register shuffling shows the real ABI. See [call-stubs.md](call-stubs.md).

| FUNCPTR | Declared prototype | Stub (file:line) | Stub instructions |
|---|---|---|---|
| `D2CLIENT_SetSelectedUnit_I` | `void __fastcall D2CLIENT_SetSelectedUnit_I(UnitAny* pUnit)` | `D2CLIENT_SetSelectedUnit_STUB` [D2Helpers.cpp:728](../../D2Helpers.cpp#L728) | `mov eax, ecx; jmp D2CLIENT_SetSelectedUnit_I` |
| `D2CLIENT_InitAutomapLayer_I` | `AutomapLayer* __fastcall D2CLIENT_InitAutomapLayer_I(DWORD nLayerNo)` | `D2CLIENT_InitAutomapLayer_STUB` [D2Helpers.cpp:336](../../D2Helpers.cpp#L336) | `push edi; mov edi, ecx; call D2CLIENT_InitAutomapLayer_I; pop edi; ret` |
| `D2CLIENT_LeftClickItem_I` | `void __stdcall D2CLIENT_LeftClickItem_I(UnitAny* pPlayer, Inventory* pInventory, int x, int y, DWORD dwClickType, InventoryLayout* pLayout, DWORD Location)` | `D2CLIENT_LeftClickItem` [D2Helpers.cpp:790](../../D2Helpers.cpp#L790) | `pop eax; xchg eax, [esp]; jmp D2CLIENT_LeftClickItem_I` |
| `D2CLIENT_GetUiVar_I` | `DWORD __fastcall D2CLIENT_GetUiVar_I(DWORD dwVarNo)` | `D2CLIENT_GetUIVar_STUB` [D2Helpers.cpp:720](../../D2Helpers.cpp#L720) | `mov eax, ecx; jmp D2CLIENT_GetUiVar_I` |
| `D2CLIENT_DrawRectFrame` | `void __fastcall D2CLIENT_DrawRectFrame(DWORD Rect)` | `D2GFX_DrawRectFrame_STUB` [D2Helpers.cpp:919](../../D2Helpers.cpp#L919) | `mov eax, ecx; jmp D2CLIENT_DrawRectFrame` |
| `D2NET_ReceivePacket_I` | `void __fastcall D2NET_ReceivePacket_I(BYTE* aPacket, DWORD aLen, int* arg3)` | `GamePacketReceived_Intercept` [D2Intercepts.cpp:24](../../D2Intercepts.cpp#L24) | `pushad; call GamePacketReceived; test eax, eax; popad; jnz OldCode; mov edx, 0; OldCode:; mov eax, [esp + 4]; push eax; call D2NET_ReceivePacket_I; ret 4` |
<!-- END GENERATED:asm-only -->

When applying these prototypes in Ghidra, prefer a custom storage signature derived from the stub
(e.g. `D2CLIENT_GetUiVar_I` takes its argument in `eax`).

## 8. Commented-out and disabled entries (historical hints)

Not in the TSV. Old offsets are hints only: some are 1.13 (`6F...` comments), two are 1.14b, a few
claim 1.14d.

<!-- BEGIN GENERATED:disabled -->
#### `D2Ptrs.h` (commented out)

| Source | Macro | Module / name | Old offset | 0x400000 + offset | Comment check | Remainder of comment |
|---|---|---|---|---|---|---|
| [D2Ptrs.h:72](../../D2Ptrs.h#L72) | FUNCPTR | `D2CLIENT_GetMercUnit` | 0x78A90 | 0x478A90 | VA comment matches; says 1.14d | `//Updated 1.14d //00478A90-BASE 478F20 with 7 0 args` |
| [D2Ptrs.h:124](../../D2Ptrs.h#L124) | FUNCPTR | `D2CLIENT_GetLevelName_I` | 0x53E70 | 0x453E70 | VA comment matches; says 1.14d | `//Updated 1.14d //00453E70-BASE` |
| [D2Ptrs.h:156](../../D2Ptrs.h#L156) | VARPTR | `D2CLIENT_MercStrIndex` | 0x325494 | 0x725494 | VA comment matches; says 1.14d | `//Updated 1.14d //00725494-BASE` |
| [D2Ptrs.h:204](../../D2Ptrs.h#L204) | VARPTR | `D2CLIENT_SelectedUnit` | 0x11C4D8 | 0x51C4D8 | mentions 1.12/1.13 | `// unused, but can we use it somewhere maybe? // 1.12 still` |
| [D2Ptrs.h:212](../../D2Ptrs.h#L212) | VARPTR | `D2CLIENT_RecentTradeName` | 0x12334C | 0x52334C | no version info | - |
| [D2Ptrs.h:222](../../D2Ptrs.h#L222) | VARPTR | `D2CLIENT_ScreenCovered` | 0x1E8F9 | 0x41E8F9 | no version info | `// unused, appears to be an int specifying which screens (if any) are opened...` |
| [D2Ptrs.h:252](../../D2Ptrs.h#L252) | ASMPTR | `D2CLIENT_TestPvpFlag_I` | 0x6A720 | 0x46A720 | 1.13-style VA, VA-offset = 0x6FAB0000 | `//6FB1A720 - Fastcall now` |
| [D2Ptrs.h:268](../../D2Ptrs.h#L268) | ASMPTR | `D2CLIENT_ClickMap_I` | 0x11C8B4 | 0x51C8B4 | 1.13-style VA, VA-offset = 0x6FAB0000 | `//6FBCC8B4` |
| [D2Ptrs.h:269](../../D2Ptrs.h#L269) | ASMPTR | `D2CLIENT_ClickMap_II` | 0x11D2CC | 0x51D2CC | 1.13-style VA, VA-offset = 0x6FAB0000 | `//6FBCD2CC //MoveOn` |
| [D2Ptrs.h:270](../../D2Ptrs.h#L270) | ASMPTR | `D2CLIENT_ClickMap_III` | 0x5BB50 | 0x45BB50 | no version info | `//ClickMap_III //CallOne` |
| [D2Ptrs.h:271](../../D2Ptrs.h#L271) | ASMPTR | `D2CLIENT_ClickMap_IV` | 0x2B499 | 0x42B499 | 1.13-style VA, VA-offset = 0x6FAB0000 | `//6FADB499` |
| [D2Ptrs.h:275](../../D2Ptrs.h#L275) | ASMPTR | `D2CLIENT_LoadAct_1` | 0x547F0 | 0x4547F0 | VA comment matches; says 1.14b | `//Updated 1.14b //004547F0-BASE` |
| [D2Ptrs.h:276](../../D2Ptrs.h#L276) | ASMPTR | `D2CLIENT_LoadAct_2` | 0x5E4A0 | 0x45E4A0 | VA comment matches; says 1.14b | `//Updated 1.14b //0045E4A0-BASE` |
| [D2Ptrs.h:278](../../D2Ptrs.h#L278) | ASMPTR | `D2CLIENT_GetUnitFromId_I` | 0x61480 | 0x461480 | 1.13-style VA, VA-offset = 0x6FAB0000 | `//GetUnitFromId_II //6FB11480` |
| [D2Ptrs.h:279](../../D2Ptrs.h#L279) | VARPTR | `D2CLIENT_pUnitTable` | 0x1047B8 | 0x5047B8 | 1.13-style VA, VA-offset = 0x6FAB0000 | `//6FBB47B8 //GetUnitFromId_I //IrC` |
| [D2Ptrs.h:281](../../D2Ptrs.h#L281) | ASMPTR | `D2CLIENT_OverrideShrinePatch_ORIG` | 0x3A3150 | 0x7A3150 | VA comment matches; says 1.14d | `//Updated 1.14d //007A3150-BASE` |
| [D2Ptrs.h:376](../../D2Ptrs.h#L376) | FUNCPTR | `D2GFX_DrawAutomapCell` | 0xF6510 | 0x4F6510 | VA comment matches; says 1.14d | `//Updated 1.14d //004F6510-BASE` |
| [D2Ptrs.h:491](../../D2Ptrs.h#L491) | `#define` | `D2CLIENT_TestPvpFlag` | - | - | - | `#define D2CLIENT_TestPvpFlag(dwId1, dwId2, dwFlag)		(D2CLIENT_TestPvpFlag_STUB(dwId1, dwId2, dwFlag))` |
| [D2Ptrs.h:498](../../D2Ptrs.h#L498) | `#define` | `D2CLIENT_LoadUIImage` | - | - | - | `#define D2CLIENT_LoadUIImage(x)							((CellFile*)D2CLIENT_LoadUIImage_ASM(x))` |

#### `Patch.h` (commented out)

| Source | Patch | DLL string | Old offset | Handler | Len | Comment check | Remainder of comment |
|---|---|---|---|---|---|---|---|
| [Patch.h:22](../../Patch.h#L22) | PatchCall | `D2Client.dll` | 0xA7364 | `AddUnit_Intercept` | 5 | no version info | - |
| [Patch.h:23](../../Patch.h#L23) | PatchCall | `D2Client.dll` | 0xA6F25 | `RemoveUnit_Interept` | 9 | no version info | - |
| [Patch.h:31](../../Patch.h#L31) | PatchCall | `D2Multi.dll` | 0x14A9A | `ChannelWhisper_Intercept` | 5 | mentions 1.12/1.13 | `//1.13d //not used` |
| [Patch.h:32](../../Patch.h#L32) | PatchJmp | `D2Multi.dll` | 0x14BE0 | `ChannelChat_Intercept` | 6 | mentions 1.12/1.13 | `//1.13d` |
| [Patch.h:33](../../Patch.h#L33) | PatchJmp | `D2Multi.dll` | 0x14850 | `ChannelEmote_Intercept` | 6 | mentions 1.12/1.13 | `//1.13d` |
| [Patch.h:43](../../Patch.h#L43) | PatchJmp | `Fog.dll` | 0x8900 | `FogException` | 6 | VA comment matches; says 1.14d | `//NEW 1.14d //00408900-BASE` |
<!-- END GENERATED:disabled -->

## 9. JS entry points per symbol

Useful for scoping an RPC replacement: which SpiderMonkey natives (and so which JS APIs) can reach
each address. See [../js-api/](../js-api/) for the API itself.

<!-- BEGIN GENERATED:js-index -->
Name-based reverse reachability from each `D2Ptrs.h` symbol to SpiderMonkey natives (`JSAPI_FUNC` / `JSAPI_PROP` definitions) and their JS names from `JS_FS`/`JS_FN`/`JSPropertySpec` tables. It over-approximates (any function sharing a name is treated as a caller); `table.name` is the spec array and the JS-visible name.

| Symbol | # natives | JS entry points (first 10) |
|---|---|---|
| `D2CLIENT_GetQuestInfo` | 1 | `unit_methods.getQuest` |
| `D2CLIENT_SubmitItem` | 1 | `global_funcs.submitItem` |
| `D2CLIENT_Transmute` | 1 | `global_funcs.transmute` |
| `D2CLIENT_FindClientSideUnit` | 27 | `global_funcs.checkCollision`, `global_funcs.clickItem`, `global_funcs.clickMap`, `global_funcs.getDistance`, `global_funcs.getMercHP`, `global_funcs.getParty`, `me_props.charflags`, `room_methods.unitInRoom`, `unit_methods.getEnchant`, `unit_methods.getFlag` +18 more |
| `D2CLIENT_FindServerSideUnit` | 27 | `global_funcs.checkCollision`, `global_funcs.clickItem`, `global_funcs.clickMap`, `global_funcs.getDistance`, `global_funcs.getMercHP`, `global_funcs.getParty`, `me_props.charflags`, `room_methods.unitInRoom`, `unit_methods.getEnchant`, `unit_methods.getFlag` +18 more |
| `D2CLIENT_GetCurrentInteractingNPC` | 5 | `global_funcs.getInteractedNPC`, `unit_methods.cancel`, `unit_methods.getItemCost`, `unit_methods.getRepairCost`, `unit_methods.shop` |
| `D2CLIENT_GetSelectedUnit` | 1 | `global_funcs.getUnit` |
| `D2CLIENT_GetCursorItem` | 5 | `global_funcs.clickItem`, `global_funcs.getUnit`, `global_funcs.submitItem`, `me_props.itemoncursor`, `unit_methods.cancel` |
| `D2CLIENT_SetSelectedUnit_I` | 3 | `global_funcs.clickMap`, `unit_methods.interact`, `unit_methods.move` |
| `D2CLIENT_GetItemName` | 5 | `global_funcs.getUnit`, `me_props.fname`, `me_props.name`, `unit_methods.getItem`, `unit_methods.getNext`, `unit_methods.getParent`, `unit_props.fname`, `unit_props.name` |
| `D2CLIENT_LoadItemDesc` | 1 | `me_props.description`, `unit_props.description` |
| `D2CLIENT_GetMonsterOwner` | 4 | `global_funcs.clickItem`, `global_funcs.getMercHP`, `unit_methods.getMerc`, `unit_methods.getMercHP`, `unit_methods.getParent` |
| `D2CLIENT_GetUnitHPPercent` | 1 | `global_funcs.getMercHP`, `unit_methods.getMercHP` |
| `D2CLIENT_InitInventory` | 0 | - |
| `D2CLIENT_SetUIVar` | 1 | `global_funcs.transmute` |
| `D2CLIENT_GetUnitX` | 5 | `global_funcs.clickMap`, `global_funcs.getDistance`, `me_props.x`, `unit_methods.interact`, `unit_methods.move`, `unit_props.x` |
| `D2CLIENT_GetUnitY` | 5 | `global_funcs.clickMap`, `global_funcs.getDistance`, `me_props.y`, `unit_methods.interact`, `unit_methods.move`, `unit_props.y` |
| `D2CLIENT_ShopAction` | 1 | `unit_methods.shop` |
| `D2CLIENT_CloseNPCInteract` | 1 | `unit_methods.cancel` |
| `D2CLIENT_CloseInteract` | 2 | `unit_methods.cancel`, `unit_methods.interact` |
| `D2CLIENT_GetAutomapSize` | 1 | `global_funcs.screenToAutomap` |
| `D2CLIENT_NewAutomapCell` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2CLIENT_AddAutomapCell` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2CLIENT_RevealAutomapRoom` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2CLIENT_InitAutomapLayer_I` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2CLIENT_ClickMap` | 4 | `global_funcs.clickMap`, `unit_methods.cancel`, `unit_methods.interact`, `unit_methods.move` |
| `D2CLIENT_LeftClickItem_I` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_GetMouseXOffset` | 0 | - |
| `D2CLIENT_GetMouseYOffset` | 0 | - |
| `D2CLIENT_PrintGameString` | 0 | - |
| `D2CLIENT_PrintPartyString` | 0 | - |
| `D2CLIENT_LeaveParty` | 1 | `global_funcs.clickParty` |
| `D2CLIENT_AcceptTrade` | 1 | `global_funcs.acceptTrade` |
| `D2CLIENT_CancelTrade` | 1 | `global_funcs.acceptTrade` |
| `D2CLIENT_TradeOK` | 1 | `global_funcs.tradeOk` |
| `D2CLIENT_GetDifficulty` | 3 | `me_props.diff`, `unit_methods.getItemCost`, `unit_methods.getRepairCost` |
| `D2CLIENT_ExitGame` | 3 | `global_funcs.load`, `global_funcs.quit`, `global_funcs.quitGame` |
| `D2CLIENT_GetUiVar_I` | 4 | `global_funcs.getUIFlag`, `global_funcs.transmute`, `unit_methods.interact`, `unit_methods.shop` |
| `D2CLIENT_DrawRectFrame` | 0 | - |
| `D2CLIENT_PerformGoldDialogAction` | 1 | `global_funcs.gold` |
| `D2CLIENT_GetPlayerUnit` | 81 | `area_props.exits`, `control_funcs.click`, `control_funcs.getNext`, `control_funcs.getText`, `control_funcs.setText`, `control_getProperty(*12 props)`, `control_setProperty(*4 props)`, `global_funcs.acceptTrade`, `global_funcs.checkCollision`, `global_funcs.clickItem` +79 more |
| `D2CLIENT_ClearScreen` | 1 | `unit_methods.cancel` |
| `D2CLIENT_CloseNPCTalk` | 2 | `global_funcs.getIsTalkingNPC`, `unit_methods.cancel` |
| `D2CLIENT_TestPvpFlag` | 1 | `global_funcs.getPlayerFlag` |
| `D2CLIENT_GetGameLanguageCode` | 0 | - |
| `p_D2CLIENT_ScreenSizeX` | 0 | - |
| `p_D2CLIENT_ScreenSizeY` | 0 | - |
| `p_D2CLIENT_CursorHoverX` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_CursorHoverY` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_MouseY` | 4 | `global_funcs.clickMap`, `global_funcs.getMouseCoords`, `unit_methods.interact`, `unit_methods.move` |
| `p_D2CLIENT_MouseX` | 4 | `global_funcs.clickMap`, `global_funcs.getMouseCoords`, `unit_methods.interact`, `unit_methods.move` |
| `p_D2CLIENT_MouseOffsetY` | 0 | - |
| `p_D2CLIENT_MouseOffsetZ` | 0 | - |
| `p_D2CLIENT_MouseOffsetX` | 0 | - |
| `p_D2CLIENT_AutomapOn` | 3 | `me_props.automap`, `unit_methods.cancel` |
| `p_D2CLIENT_AutomapMode` | 1 | `global_funcs.automapToScreen` |
| `p_D2CLIENT_Offset` | 2 | `global_funcs.automapToScreen`, `global_funcs.screenToAutomap` |
| `p_D2CLIENT_AutomapLayer` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `p_D2CLIENT_MercReviveCost` | 1 | `me_props.mercrevivecost` |
| `p_D2CLIENT_ServerSideUnitHashTables` | 3 | `global_funcs.getUnit`, `unit_methods.getNext`, `unit_methods.getParent` |
| `p_D2CLIENT_ClientSideUnitHashTables` | 3 | `global_funcs.getUnit`, `unit_methods.getNext`, `unit_methods.getParent` |
| `p_D2CLIENT_ViewportY` | 4 | `global_funcs.clickMap`, `global_funcs.getMouseCoords`, `unit_methods.interact`, `unit_methods.move` |
| `p_D2CLIENT_ViewportX` | 4 | `global_funcs.clickMap`, `global_funcs.getMouseCoords`, `unit_methods.interact`, `unit_methods.move` |
| `p_D2CLIENT_GoldDialogAction` | 1 | `global_funcs.gold` |
| `p_D2CLIENT_GoldDialogAmount` | 1 | `global_funcs.gold` |
| `p_D2CLIENT_NPCMenu` | 1 | `unit_methods.useMenu` |
| `p_D2CLIENT_NPCMenuAmount` | 1 | `unit_methods.useMenu` |
| `p_D2CLIENT_TradeLayout` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_StashLayout` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_StoreLayout` | 0 | - |
| `p_D2CLIENT_CubeLayout` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_InventoryLayout` | 1 | `global_funcs.clickItem` |
| `p_D2CLIENT_MercLayout` | 0 | - |
| `p_D2CLIENT_RegularCursorType` | 1 | `global_funcs.getCursorType` |
| `p_D2CLIENT_ShopCursorType` | 1 | `global_funcs.getCursorType` |
| `p_D2CLIENT_Ping` | 1 | `me_props.ping` |
| `p_D2CLIENT_Skip` | 0 | - |
| `p_D2CLIENT_FPS` | 1 | `me_props.fps` |
| `p_D2CLIENT_Lang` | 0 | - |
| `p_D2CLIENT_Divisor` | 1 | `global_funcs.screenToAutomap` |
| `p_D2CLIENT_OverheadTrigger` | 1 | `unit_methods.overhead` |
| `p_D2CLIENT_RecentInteractId` | 2 | `global_funcs.submitItem`, `unit_methods.repair` |
| `p_D2CLIENT_ItemPriceList` | 2 | `unit_methods.getItemCost`, `unit_methods.getRepairCost` |
| `p_D2CLIENT_TransactionDialog` | 2 | `global_funcs.clickItem`, `unit_methods.shop` |
| `p_D2CLIENT_TransactionDialogs` | 3 | `global_funcs.clickItem`, `global_funcs.tradeOk`, `unit_methods.shop` |
| `p_D2CLIENT_TransactionDialogs_2` | 2 | `global_funcs.clickItem`, `unit_methods.shop` |
| `p_D2CLIENT_pTransactionDialogsInfo` | 2 | `global_funcs.getDialogLines`, `global_funcs.tradeOk` |
| `p_D2CLIENT_GameInfo` | 1 | `unit_getProperty(*129 props)` |
| `p_D2CLIENT_WaypointTable` | 1 | `global_funcs.getWaypoint` |
| `p_D2CLIENT_PlayerUnit` | 1 | `global_funcs.say` |
| `p_D2CLIENT_SelectedInvItem` | 1 | `global_funcs.getUnit` |
| `p_D2CLIENT_PlayerUnitList` | 2 | `global_funcs.clickParty`, `global_funcs.getParty` |
| `p_D2CLIENT_bWeapSwitch` | 2 | `global_funcs.weaponSwitch`, `me_props.weaponswitch`, `unit_props.weaponswitch` |
| `p_D2CLIENT_bTradeAccepted` | 1 | `global_funcs.acceptTrade` |
| `p_D2CLIENT_bTradeBlock` | 1 | `global_funcs.acceptTrade` |
| `p_D2CLIENT_RecentTradeId` | 2 | `global_funcs.acceptTrade`, `global_funcs.getTradeInfo` |
| `p_D2CLIENT_ExpCharFlag` | 1 | `me_props.gametype` |
| `p_D2CLIENT_MapId` | 1 | `me_props.mapid` |
| `p_D2CLIENT_AlwaysRun` | 5 | `global_funcs.clickMap`, `me_props.runwalk`, `unit_methods.interact`, `unit_methods.move`, `unit_props.runwalk` |
| `p_D2CLIENT_NoPickUp` | 2 | `me_props.nopickup` |
| `p_D2CLIENT_ChatMsg` | 1 | `global_funcs.say` |
| `p_D2CLIENT_OrificeId` | 1 | `global_funcs.submitItem` |
| `p_D2CLIENT_CursorItemMode` | 1 | `global_funcs.submitItem` |
| `D2CLIENT_TakeWaypoint_I` | 1 | `unit_methods.interact` |
| `D2CLIENT_ClickShopItem_I` | 0 | - |
| `D2CLIENT_ClickBelt_I` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_ClickBeltRight_I` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_ClickItemRight_I` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_MercItemAction_I` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_Interact_I` | 0 | - |
| `D2CLIENT_ClickParty_I` | 1 | `global_funcs.clickParty` |
| `D2CLIENT_ClickParty_II` | 1 | `global_funcs.clickParty` |
| `D2CLIENT_ShopAction_I` | 0 | - |
| `D2CLIENT_GetUnitName_I` | 5 | `global_funcs.getUnit`, `me_props.name`, `unit_methods.getItem`, `unit_methods.getNext`, `unit_methods.getParent`, `unit_props.name` |
| `D2CLIENT_GetItemDesc_I` | 0 | - |
| `D2CLIENT_AssignPlayer_I` | 0 | - |
| `D2CLIENT_InputCall_I` | 0 | - |
| `D2CLIENT_Say_I` | 1 | `global_funcs.say` |
| `D2CLIENT_BodyClickTable` | 1 | `global_funcs.clickItem` |
| `D2CLIENT_LoadUIImage_I` | 0 | - |
| `D2CLIENT_GetMinionCount_I` | 1 | `unit_methods.getMinionCount` |
| `D2CLIENT_GameLeave_I` | 0 | - |
| `D2CLIENT_CongratsScreen_I` | 0 | - |
| `D2CLIENT_GameAddUnit_I` | 0 | - |
| `D2CLIENT_SendGamePacket_I` | 3 | `global_funcs.useSkillPoint`, `global_funcs.useStatPoint`, `unit_methods.setSkill` |
| `D2CLIENT_SendPacket_II` | 0 | - |
| `D2COMMON_InitLevel` | 7 | `area_props.exits`, `global_funcs.getArea`, `global_funcs.getCollision`, `global_funcs.getPath`, `global_funcs.getPresetUnit`, `global_funcs.getPresetUnits`, `global_funcs.getRoom` |
| `D2COMMON_UnloadAct` | 0 | - |
| `D2COMMON_GetObjectTxt` | 0 | - |
| `D2COMMON_LoadAct` | 0 | - |
| `D2COMMON_GetLevelText` | 1 | `area_props.name` |
| `D2COMMON_GetObjectText` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2COMMON_GetItemText` | 6 | `global_funcs.clickItem`, `global_funcs.getUnit`, `me_props.code`, `me_props.itemType`, `me_props.sizex`, `me_props.sizey`, `unit_methods.getItem`, `unit_methods.getNext`, `unit_methods.getParent`, `unit_props.code` +3 more |
| `D2COMMON_GetLayer` | 2 | `global_funcs.revealLevel`, `room_methods.reveal` |
| `D2COMMON_GetLevel` | 0 | - |
| `D2COMMON_GetStatList` | 1 | `unit_methods.getStat` |
| `D2COMMON_CopyStatList` | 1 | `unit_methods.getStat` |
| `D2COMMON_GetUnitStat` | 4 | `global_funcs.useSkillPoint`, `global_funcs.useStatPoint`, `me_props.charlvl`, `me_props.hp`, `me_props.hpmax`, `me_props.mp`, `me_props.mpmax`, `me_props.stamina`, `me_props.staminamax`, `unit_methods.getStat` +7 more |
| `D2COMMON_GetUnitState` | 1 | `unit_methods.getState` |
| `D2COMMON_CheckUnitCollision` | 1 | `global_funcs.checkCollision` |
| `D2COMMON_GetRoomFromUnit` | 3 | `global_funcs.getRoom`, `me_props.area`, `room_methods.unitInRoom`, `unit_props.area`, `unit_props.objtype` |
| `D2COMMON_GetTargetUnitType` | 0 | - |
| `D2COMMON_GetSkillLevel` | 2 | `unit_methods.getSkill`, `unit_methods.setSkill` |
| `D2COMMON_GetItemLevelRequirement` | 2 | `unit_methods.getStat`, `unit_props.lvlreq` |
| `D2COMMON_GetItemPrice` | 1 | `unit_methods.getItemCost` |
| `D2COMMON_GetRepairCost` | 1 | `unit_methods.getRepairCost` |
| `D2COMMON_GetItemMagicalMods` | 1 | `me_props.prefix`, `me_props.prefixes`, `me_props.suffix`, `me_props.suffixes`, `unit_props.prefix`, `unit_props.prefixes`, `unit_props.suffix`, `unit_props.suffixes` |
| `D2COMMON_GetItemFromInventory` | 1 | `unit_methods.getItem` |
| `D2COMMON_GetNextItemFromInventory` | 3 | `unit_methods.getItem`, `unit_methods.getItems`, `unit_methods.getNext` |
| `D2COMMON_GenerateOverheadMsg` | 1 | `unit_methods.overhead` |
| `D2COMMON_FixOverheadMsg` | 0 | - |
| `D2COMMON_AddRoomData` | 11 | `area_props.exits`, `global_funcs.getCollision`, `global_funcs.getPresetUnit`, `global_funcs.getPresetUnits`, `global_funcs.getRoom`, `global_funcs.revealLevel`, `room_methods.getCollision`, `room_methods.getCollisionA`, `room_methods.getPresetUnits`, `room_methods.getStat` +1 more |
| `D2COMMON_RemoveRoomData` | 12 | `area_props.exits`, `global_funcs.getCollision`, `global_funcs.getPath`, `global_funcs.getPresetUnit`, `global_funcs.getPresetUnits`, `global_funcs.getRoom`, `global_funcs.revealLevel`, `room_methods.getCollision`, `room_methods.getCollisionA`, `room_methods.getPresetUnits` +2 more |
| `D2COMMON_GetQuestFlag` | 1 | `unit_methods.getQuest` |
| `D2COMMON_MapToAbsScreen` | 3 | `global_funcs.clickMap`, `unit_methods.interact`, `unit_methods.move` |
| `D2COMMON_AbsScreenToMap` | 1 | `global_funcs.getMouseCoords` |
| `D2COMMON_CheckWaypoint` | 1 | `global_funcs.getWaypoint` |
| `D2COMMON_IsTownByLevelNo` | 1 | `global_funcs.submitItem` |
| `D2COMMON_GetLevelNoFromRoom` | 1 | `unit_props.objtype` |
| `D2COMMON_FindRoom1` | 0 | - |
| `D2COMMON_GetItemPalette` | 0 | - |
| `D2COMMON_GetMissileOwnerUnit` | 1 | `unit_methods.getParent` |
| `p_D2COMMON_sgptDataTable` | 5 | `global_funcs.getBaseStat`, `global_funcs.getSkillById`, `unit_methods.getItemCost`, `unit_methods.getSkill`, `unit_methods.interact` |
| `D2COMMON_DisplayOverheadMsg_I` | 0 | - |
| `D2COMMON_GetLevelIdFromRoom_I` | 0 | - |
| `D2NET_SendPacket` | 7 | `global_funcs.moveNPC`, `global_funcs.sendPacket`, `global_funcs.submitItem`, `global_funcs.weaponSwitch`, `unit_methods.interact`, `unit_methods.repair`, `unit_methods.revive` |
| `D2NET_ReceivePacket` | 1 | `global_funcs.getPacket` |
| `D2NET_ReceivePacket_I` | 0 | - |
| `p_D2NET_CriticalPacketSection` | 0 | - |
| `D2GFX_DrawRectangle` | 0 | - |
| `D2GFX_DrawLine` | 0 | - |
| `D2GFX_DrawAutomapCell2` | 0 | - |
| `D2GFX_GetHwnd` | 15 | `control_funcs.click`, `global_funcs.createGame`, `global_funcs.getIsTalkingNPC`, `global_funcs.joinGame`, `global_funcs.load`, `global_funcs.login`, `global_funcs.quitGame`, `global_funcs.say`, `global_funcs.selectCharacter`, `global_funcs.sendClick` +5 more |
| `D2GFX_GetScreenSize` | 2 | `global_funcs.clickItem`, `me_props.screensize` |
| `D2MULTI_DoChat` | 1 | `global_funcs.say` |
| `D2MULTI_PrintChannelText_` | 0 | - |
| `p_D2MULTI_ChatBoxMsg` | 1 | `global_funcs.say` |
| `p_D2MULTI_GameListControl` | 0 | - |
| `D2MULTI_ChannelChat_I` | 0 | - |
| `D2MULTI_ChannelEmote_I` | 0 | - |
| `D2MULTI_ChannelWhisper_I` | 0 | - |
| `D2MULTI_ChannelInput_I` | 0 | - |
| `D2CMP_InitCellFile` | 1 | `image_props.location` |
| `D2CMP_DeleteCellFile` | 0 | - |
| `D2LANG_GetLocaleText` | 17 | `control_funcs.click`, `control_funcs.getNext`, `control_funcs.getText`, `control_funcs.setText`, `control_getProperty(*12 props)`, `control_setProperty(*4 props)`, `global_funcs.createGame`, `global_funcs.getControl`, `global_funcs.getLocaleString`, `global_funcs.getLocation` +7 more |
| `D2LANG_Say_II` | 0 | - |
| `p_D2LAUNCH_BnData` | 3 | `global_funcs.clickParty`, `global_funcs.weaponSwitch`, `unit_getProperty(*129 props)` |
| `D2WIN_SetControlText` | 6 | `control_funcs.setText`, `control_props.text`, `global_funcs.createGame`, `global_funcs.joinGame`, `global_funcs.login`, `profile_methods.login` |
| `D2WIN_DrawSprites` | 0 | - |
| `D2WIN_LoadCellFile` | 1 | `image_props.location` |
| `D2WIN_TakeScreenshot` | 0 | - |
| `D2WIN_DrawText` | 0 | - |
| `D2WIN_GetTextSize` | 4 | `global_funcs.clickMap`, `global_funcs.getTextSize`, `unit_methods.interact`, `unit_methods.move` |
| `D2WIN_SetTextSize` | 4 | `global_funcs.clickMap`, `global_funcs.getTextSize`, `unit_methods.interact`, `unit_methods.move` |
| `D2WIN_GetTextWidthFileNo` | 0 | - |
| `D2WIN_DestroyEditBox` | 0 | - |
| `D2WIN_DestroyControl` | 0 | - |
| `D2WIN_SetEditBoxCallback` | 0 | - |
| `D2WIN_SetEditBoxProc` | 0 | - |
| `D2WIN_SelectEditBoxText` | 0 | - |
| `D2WIN_InitMPQ` | 1 | `global_funcs.loadMpq` |
| `p_D2WIN_FirstControl` | 81 | `area_getProperty(*7 props)`, `control_funcs.click`, `control_funcs.getNext`, `control_funcs.getText`, `control_funcs.setText`, `control_getProperty(*12 props)`, `control_setProperty(*4 props)`, `global_funcs.acceptTrade`, `global_funcs.checkCollision`, `global_funcs.clickItem` +74 more |
| `p_D2WIN_FocusedControl` | 0 | - |
| `p_D2MULTI_ChatInputBox` | 0 | - |
| `BNCLIENT_DClass` | 0 | - |
| `BNCLIENT_DLod` | 0 | - |
| `p_BNCLIENT_ClassicKey` | 1 | `global_funcs.loadMpq` |
| `p_BNCLIENT_XPacKey` | 1 | `global_funcs.loadMpq` |
| `p_BNCLIENT_KeyOwner` | 1 | `global_funcs.loadMpq` |
| `BNCLIENT_DecodeAndLoadKeys` | 0 | - |
| `p_STORM_WindowHandlers` | 2 | `global_funcs.getIsTalkingNPC`, `unit_methods.cancel` |
| `D2GAME_Rand` | 1 | `global_funcs.rand` |
| `D2GAME_exit0` | 0 | - |
<!-- END GENERATED:js-index -->

## 10. Open questions

- None of the addresses has been checked against a Game.exe 1.14d binary from this repository; the
  status flags only grade the source's own evidence. Rows to check first in Ghidra:
  `RealmPacketRecv_Interception` (`0x4B1AE`), the Fog `0x82E0` patch target, the `Conditional[]`
  sites, `D2COMMON_GetMissileOwnerUnit`, the MPQ absolute VAs and the JSUnit description VAs.
- What the game code at the `D2GAME_exit0` (`0x40576F`) and Fog `0x4082E0` sites actually is.
- Exact element types/sizes of `D2CLIENT_BodyClickTable`, `D2WIN_ItemDescText` and the
  `type-from-usage` buffers (`ChatMsg`, `ChatBoxMsg`, `NPCMenu`) are not determinable from source.
- Whether `D2CLIENT_StoreLayout` / `D2CLIENT_MercLayout` are structs (like the other layout
  globals) or pointers.
- Duplicate-address pairs (`MouseOffsetX/Y` = `ViewportX/Y`, `AutomapMode` = `Divisor`,
  `GetObjectTxt` = `GetObjectText`, `GetTextSize` = `GetTextWidthFileNo`,
  `SetEditBoxCallback` = `SetEditBoxProc`, `GetLevelNoFromRoom` = `GetLevelIdFromRoom_I`) are
  deliberate aliases in the source; which name matches the game's semantics is unknown. The eighth
  pair, `SelectedInvItem` = `ItemDescUnit` (RVA `0x3BCBF4`), comes from the hardcoded literal in
  [JSUnit.cpp:454](../../JSUnit.cpp#L454), which bypasses `p_D2CLIENT_SelectedInvItem`.

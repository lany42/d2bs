# Memory model: how D2BS addresses Game.exe 1.14d

Scope: how the C++ side of D2BS turns the numbers in `D2Ptrs.h`, `Patch.h`, `MPQStats.cpp` and
`JSUnit.cpp` into live addresses inside Diablo II 1.14d, what the `FUNCPTR` / `VARPTR` / `ASMPTR`
X-macros expand to, when the pointers become valid, and how to port everything to another game
build. Everything here is derived from the C++ sources (cited as `File:line`); nothing was checked
against a Game.exe binary. Per-symbol tables live in [offsets.md](offsets.md); patch/hook
mechanics in [patches-and-hooks.md](patches-and-hooks.md); asm thunks in
[call-stubs.md](call-stubs.md); structure layouts in [structs.md](structs.md); the Ghidra import in
[../ghidra/README.md](../ghidra/README.md).

## Contents

1. [Summary](#1-summary)
2. [One image, legacy module names](#2-one-image-legacy-module-names)
3. [Encoding and resolution: `DLLOFFSET` and `GetDllOffset`](#3-encoding-and-resolution-dlloffset-and-getdlloffset)
4. [`D2Ptrs.h` is included three ways](#4-d2ptrsh-is-included-three-ways)
5. [Start-up order and when pointers become valid](#5-start-up-order-and-when-pointers-become-valid)
6. [Worked expansions](#6-worked-expansions)
7. [Naming conventions, wrappers and aliases](#7-naming-conventions-wrappers-and-aliases)
8. [Other address sources outside `D2Ptrs.h`](#8-other-address-sources-outside-d2ptrsh)
9. [Porting to another game build](#9-porting-to-another-game-build)
10. [Regenerating the tables and the Ghidra import](#10-regenerating-the-tables-and-the-ghidra-import)
11. [Open questions](#11-open-questions)

## 1. Summary

- Every `D2Ptrs.h` / `Patch.h` offset, and every `GetDllOffset()` argument, is an **RVA into
  Game.exe**. The legacy module token (`D2CLIENT`, `D2COMMON`, ...) is carried through the macros but
  ignored at resolution time. The exception is `MPQStats.cpp`, which stores absolute `0x400000`-based
  VAs and rebases them itself ([§8](#8-other-address-sources-outside-d2ptrsh)).
- `GetDllOffset(char*, int)` returns `GetModuleHandle(NULL) + offset`
  ([Offset.cpp:21-28](../../Offset.cpp#L21-L28)). `GetModuleHandle(NULL)` is the process's main
  module, i.e. Game.exe.
- Game.exe 1.14d's preferred image base is `0x400000`, so **VA = 0x400000 + RVA**. The
  `//004B32D0-BASE` comments in `D2Ptrs.h`/`Patch.h` are such VAs (`-BASE` means "subtract the base
  to get the RVA"). The generator checked all 227 VA comments: every one equals `0x400000 + RVA`
  (see [offsets.md](offsets.md)).
- The `D2Ptrs.h` globals start out holding an *encoded* value (`DLLNO | offset << 8`) and are
  rewritten in place by `DefineOffsets()` in `Startup()` ([D2BS.cpp:132](../../D2BS.cpp#L132)).
  Anything that reads them earlier gets the encoded value. One place does:
  `Patches[]` copies `D2GAME_exit0` during static initialisation (see
  [§5.1](#51-static-initialisers-see-encoded-values-bug)).

```
D2Ptrs.h entry ──(Offset.cpp, _DEFINE_VARS)──► global = DLLNO | (RVA << 8)        [static data]
                                              │
DllMain ► Startup ► DefineOffsets() ──────────┘ global = GetModuleHandle(NULL) + RVA
                  ► InstallPatches()      (Patches[]     : already absolute, built at static init)
                  ► InstallConditional()  (Conditional[] : same, gated by Vars flags)
```

## 2. One image, legacy module names

In 1.13 and earlier, the game shipped as separate DLLs (D2Client.dll, D2Common.dll, ...). In 1.14
they were linked into Game.exe. D2BS kept the 1.13 naming: the 13-entry `DLLNO_*` enum
([D2Ptrs.h:24-38](../../D2Ptrs.h#L24-L38)) and the matching name table
([Offset.cpp:31-32](../../Offset.cpp#L31-L32)) still list D2Client.DLL ... D2Multi.DLL, and
`Patch.h` passes strings such as `"D2Client.dll"`, `"BNCLIENT.DLL"`, `"D2MCPClient.dll"`. None of
them affect the result:

```cpp
DWORD GetDllOffset(char* DllName, int Offset) {      // Offset.cpp:21
    HMODULE hMod = GetModuleHandle(NULL);             // Offset.cpp:22  -> Game.exe, DllName unused
    if (Offset < 0)
        return (DWORD)GetProcAddress(hMod, (LPCSTR)(-Offset));   // Offset.cpp:24-25
    return ((DWORD)hMod) + Offset;                    // Offset.cpp:27
}
```

Consequences:

- The module token is documentation only. It reflects which 1.13 DLL the function used to live in
  and is sometimes imprecise for 1.14d (e.g. the `GamePacketSent` patch is filed under
  `"D2Client.dll"` at RVA `0x12AE5A`, inside `D2NET_SendPacket` at `0x12AE50`,
  [Patch.h:12](../../Patch.h#L12), [D2Ptrs.h:362](../../D2Ptrs.h#L362);
  `D2COMMON_GetMissileOwnerUnit` at `0x639D0` sits next to `D2CLIENT_FindServerSideUnit` at
  `0x639B0`, [D2Ptrs.h:344](../../D2Ptrs.h#L344), [D2Ptrs.h:68](../../D2Ptrs.h#L68)).
- The `MPQStats.h` and `Helpers.cpp` comments/code still mention per-DLL handles:
  `d2CommonOff` is now `GetModuleHandle(NULL)` with the old `GetModuleHandle("D2Common.DLL")` code
  left in a comment ([MPQStats.h:10](../../MPQStats.h#L10)); `DllLoadAddrStrs()` still logs
  `GetModuleHandle("D2Client.DLL")` etc. in crash reports ([Helpers.cpp:372-394](../../Helpers.cpp#L372-L394)),
  which presumably prints `0x00000000` for every entry on 1.14d (not verified at runtime).
- Because the runtime base is added (not the constant `0x400000`), all three resolution paths
  (D2Ptrs, Patch.h, MPQ/JSUnit rebasing) would still work if Game.exe were loaded elsewhere; only
  the `-BASE` comments and the absolute literals in `MPQStats.cpp`/`JSUnit.cpp` are written as
  `0x400000`-based VAs.

## 3. Encoding and resolution: `DLLOFFSET` and `GetDllOffset`

```cpp
#define DLLOFFSET(a1, b1) ((DLLNO_##a1) | ((b1) << 8))       // D2Ptrs.h:40

DWORD GetDllOffset(int num) {                               // Offset.cpp:30
    static char* dlls[] = {"D2Client.DLL", ..., "D2Multi.DLL"};   // 13 names, Offset.cpp:31-32
    if ((num & 0xff) > 12)                                  // Offset.cpp:33
        return 0;
    return GetDllOffset(dlls[num & 0xff], num >> 8);       // Offset.cpp:35
}
```

| Bits of the stored value | Meaning |
|---|---|
| `[7:0]` | `DLLNO_*` index 0..12 (`D2CLIENT`=0 ... `D2MULTI`=12, [D2Ptrs.h:24-38](../../D2Ptrs.h#L24-L38)) |
| `[31:8]` | signed offset; `num >> 8` on an `int` is an arithmetic shift, so negatives survive |

- **Guard**: an index above 12 resolves to `0` (NULL pointer). The generator checks that the enum
  and `dlls[]` have the same 13 names in the same order and that the guard is `> 12`.
- **Ordinal path**: a negative offset `-n` becomes `GetProcAddress(Game.exe, MAKEINTRESOURCE(n))`,
  i.e. an export of Game.exe by ordinal. **No entry uses it today** (generator: 0 negative
  offsets; the TSV schema reserves `ORD:<n>` for them).
- **Range limit**: `b1 << 8` must fit in a positive 32-bit `int`, so offsets must be `<= 0x7FFFFF`.
  A larger RVA would turn negative and be treated as an ordinal. The largest current offset is
  `0x482750` (`BNCLIENT_KeyOwner`, [D2Ptrs.h:471](../../D2Ptrs.h#L471)); the generator fails if any
  entry exceeds the limit. The absolute tables in `MPQStats.cpp` reach RVA `0x56D62C` but do not
  go through `DLLOFFSET`.
- `#pragma warning(disable : 4245)` ([D2Ptrs.h:9-10](../../D2Ptrs.h#L9-L10)) silences
  signed/unsigned conversion warnings from these casts. `#pragma optimize("", off)` /
  `("", on)` ([D2Ptrs.h:12](../../D2Ptrs.h#L12), [:514](../../D2Ptrs.h#L514)) brackets a region
  that contains no function bodies, so it appears to have no effect on code generation.

## 4. `D2Ptrs.h` is included three ways

`D2Ptrs.h` is an X-macro list: 213 entries between [D2Ptrs.h:62](../../D2Ptrs.h#L62) and
[D2Ptrs.h:481](../../D2Ptrs.h#L481) (111 `FUNCPTR`, 70 `VARPTR`, 32 `ASMPTR`; counts from the
generator, cross-checked with grep). The meaning of each macro depends on two switches:

| Mode | Where | Switches | `FUNCPTR(d1,v1,t1,t2,o1)` | `VARPTR(d1,v1,t1,o1)` | `ASMPTR(d1,v1,o1)` |
|---|---|---|---|---|---|
| A: declarations | every other TU (`#include "D2Ptrs.h"`, e.g. [D2Helpers.h:5](../../D2Helpers.h#L5), [Game.h:2](../../Game.h#L2)) | none | `typedef t1 d1_v1_t t2; extern d1_v1_t* d1_v1;` ([D2Ptrs.h:52-54](../../D2Ptrs.h#L52-L54)) | `typedef t1 d1_v1_t; extern d1_v1_t* p_d1_v1;` ([:55-57](../../D2Ptrs.h#L55-L57)) | `extern DWORD d1_v1;` ([:58](../../D2Ptrs.h#L58)) |
| B: definitions | [Offset.cpp:1-3](../../Offset.cpp#L1-L3) | `_DEFINE_VARS`, `__D2PTRS_ONCE_` | `typedef ...; d1_v1_t* d1_v1 = (d1_v1_t*)DLLOFFSET(d1, o1);` ([:41-43](../../D2Ptrs.h#L41-L43)) | `typedef ...; d1_v1_t* p_d1_v1 = (d1_v1_t*)DLLOFFSET(d1, o1);` ([:44-46](../../D2Ptrs.h#L44-L46)) | `DWORD d1_v1 = DLLOFFSET(d1, o1);` ([:47](../../D2Ptrs.h#L47)) |
| C: address list | [Offset.cpp:4-6](../../Offset.cpp#L4-L6) | `_DEFINE_VARS`, `__D2PTRS_LIST_`, guard `#undef`'d | `&d1_v1,` ([:18](../../D2Ptrs.h#L18)) | `&p_d1_v1,` ([:19](../../D2Ptrs.h#L19)) | `&d1_v1,` ([:20](../../D2Ptrs.h#L20)) |

(`d1_v1` stands for the token paste `d1##_##v1`.)

- Mode C wraps the entries in `void* d2ptrs_list[] = {` ... `};`
  ([D2Ptrs.h:21](../../D2Ptrs.h#L21), [:487-488](../../D2Ptrs.h#L487-L488)), producing one slot per
  entry, in source order, holding the *address of* each global.
- `__D2PTRS_ONCE_` disables the `#pragma once` ([D2Ptrs.h:1-3](../../D2Ptrs.h#L1-L3)) and
  `#undef __D2PTRS_H__` ([Offset.cpp:4](../../Offset.cpp#L4)) re-opens the include guard
  ([D2Ptrs.h:4-5](../../D2Ptrs.h#L4-L5)), which is what allows Offset.cpp to include the header twice.
- The `DLLNO_*` enum and `DLLOFFSET` exist only in mode B ([D2Ptrs.h:24-40](../../D2Ptrs.h#L24-L40)).
- The alias `#define`s at the bottom ([D2Ptrs.h:491-509](../../D2Ptrs.h#L491-L509)) are emitted in
  modes A and B only (the `#else` branch of `#ifdef __D2PTRS_LIST_`, [:487-511](../../D2Ptrs.h#L487-L511)).
- The macros are `#undef`'d after the list ([D2Ptrs.h:483-485](../../D2Ptrs.h#L483-L485)), so they
  cannot be reused elsewhere.

`DefineOffsets()` walks the list and rewrites each global through the stored address:

```cpp
void DefineOffsets() {                                   // Offset.cpp:14
    DWORD** p = (DWORD**)d2ptrs_list;
    do {
        **p = GetDllOffset(**p);                         // read encoded value, write absolute address
    } while (ptrdiff_t(++p) < ((ptrdiff_t)d2ptrs_list) + sizeof(d2ptrs_list));
}
```

It treats every global as a `DWORD` regardless of its declared type (all are 32-bit pointers or
`DWORD`s on x86). It is not idempotent: a second call would decode already-absolute values.

## 5. Start-up order and when pointers become valid

| Step | Where | What happens to addresses |
|---|---|---|
| CRT static initialisation of D2BS.dll | before `DllMain` runs | D2Ptrs globals get their encoded constants. `Patches[]` / `Conditional[]` ([Patch.h:8](../../Patch.h#L8), [:47](../../Patch.h#L47)) are dynamically initialised: each `GetDllOffset("<dll>", off)` already returns `GetModuleHandle(NULL) + off`. `d2CommonOff` = `GetModuleHandle(NULL)` ([MPQStats.h:10](../../MPQStats.h#L10)). |
| `DllMain(DLL_PROCESS_ATTACH)` | [D2BS.cpp:23](../../D2BS.cpp#L23) | Command line parsed; `Vars.bSleepy`, `bCacheFix`, `bMulti`, `bReduceFTJ`, `bUseRawCDKey` set from `-sleepy`, `-cachefix`, `-multi`, `-ftj`, `-d2c` ([D2BS.cpp:49-73](../../D2BS.cpp#L49-L73)); then `Startup()` ([D2BS.cpp:94](../../D2BS.cpp#L94)). |
| `Startup()` | [D2BS.cpp:108](../../D2BS.cpp#L108) | `Genhook::Initialize()` ([:131](../../D2BS.cpp#L131)), **`DefineOffsets()`** ([:132](../../D2BS.cpp#L132)), `InstallPatches()` ([:133](../../D2BS.cpp#L133)), `InstallConditional()` ([:134](../../D2BS.cpp#L134)), DDE server, then the `D2Thread` ([:137](../../D2BS.cpp#L137)). |
| `Shutdown()` | [D2BS.cpp:143](../../D2BS.cpp#L143) | `RemovePatches()` restores `Patches[]` bytes ([:153](../../D2BS.cpp#L153)). `RemoveConditional()` ([Offset.cpp:64](../../Offset.cpp#L64)) is never called anywhere, so conditional patches stay installed after shutdown. |

`InstallPatches()` saves the original bytes with `ReadProcessMemory` and calls
`PatchCall`/`PatchJmp`/`PatchBytes` ([Offset.cpp:38-44](../../Offset.cpp#L38-L44),
[:104-119](../../Offset.cpp#L104-L119)). `InterceptLocalCode` writes opcode + `rel32 = target - (site + 5)`
and NOP-fills the rest of `dwLen` ([Offset.cpp:92-102](../../Offset.cpp#L92-L102)). `PatchBytes`
memsets the low byte of the value `dwLen` times ([Offset.cpp:112-119](../../Offset.cpp#L112-L119)),
so `(WORD)0x9090` with length 2 ([Patch.h:55](../../Patch.h#L55)) writes `90 90`.

### 5.1 Static initialisers see encoded values (bug)

`Patches[]` is a file-scope array initialised during CRT start-up. One entry reads a D2Ptrs global:

```cpp
{PatchJmp, GetDllOffset("Fog.dll", 0x82E0), (DWORD)D2GAME_exit0, 6},   // Patch.h:42
```

`D2GAME_exit0` is `FUNCPTR(D2GAME, exit0, ..., 0x576F)` ([D2Ptrs.h:481](../../D2Ptrs.h#L481)). At
static-init time it still holds `DLLOFFSET(D2GAME, 0x576F)` = `6 | 0x576F << 8` = **`0x576F06`**.
`DefineOffsets()` later fixes the global but not the copy in `Patches[x].dwFunc`, so
`InstallPatches()` writes `E9 21 EC 16 00 90` at VA `0x4082E0`: a `JMP 0x576F06` instead of
`JMP 0x40576F` (intended `rel32` = `0xFFFFD48A`). Whatever path reaches `0x4082E0` (the Fog-region
function this patch is meant to short-circuit, presumably an error/exit path) jumps into the
middle of unrelated code. To verify: after injection, disassemble `0x4082E0`. Fix: install that
patch with `(DWORD)GetDllOffset("Game.exe", 0x576F)` or patch `dwFunc` after `DefineOffsets()`.
The generator flags both rows `captured-encoded`; it found no other file-scope initialiser that
reads a D2Ptrs global.

## 6. Worked expansions

### `FUNCPTR` — callable function pointer

[D2Ptrs.h:122](../../D2Ptrs.h#L122): `FUNCPTR(D2CLIENT, GetPlayerUnit, UnitAny* __stdcall, (), 0x63DD0) // Updated 1.14d //00463DD0-BASE`

```cpp
// mode A (any TU)
typedef UnitAny* __stdcall D2CLIENT_GetPlayerUnit_t ();
extern D2CLIENT_GetPlayerUnit_t* D2CLIENT_GetPlayerUnit;
// mode B (Offset.cpp)
D2CLIENT_GetPlayerUnit_t* D2CLIENT_GetPlayerUnit =
    (D2CLIENT_GetPlayerUnit_t*)((DLLNO_D2CLIENT) | ((0x63DD0) << 8));   // = 0x063DD000
// mode C (Offset.cpp)
&D2CLIENT_GetPlayerUnit,
// DefineOffsets(): GetDllOffset(0x063DD000) -> index 0 -> GetDllOffset("D2Client.DLL", 0x63DD0)
//                  -> GetModuleHandle(NULL) + 0x63DD0 = 0x463DD0 (matches the comment)
```

C++ calls it directly: `D2CLIENT_GetPlayerUnit()` ([D2Helpers.h:75](../../D2Helpers.h#L75)). The
compiler uses the declared calling convention, so `t1`/`t2` must describe the real ABI. For
`FUNCPTR`s only reached from asm stubs the prototype is never used by the compiler
(generator flag `asm-only`, see [offsets.md](offsets.md)).

### `VARPTR` — pointer to a game global

[D2Ptrs.h:473](../../D2Ptrs.h#L473): `VARPTR(STORM, WindowHandlers, WindowHandlerHashTable, 0x379300) // Updated 1.14d //00779300-BASE`

```cpp
typedef WindowHandlerHashTable STORM_WindowHandlers_t;
STORM_WindowHandlers_t* p_STORM_WindowHandlers = (STORM_WindowHandlers_t*)((DLLNO_STORM) | ((0x379300) << 8));
// DLLNO_STORM = 10 -> encoded 0x3793000A -> resolved 0x779300
```

The variable is a **pointer to** the game object: `*p_D2CLIENT_PlayerUnit` reads the game's
`UnitAny*` ([Core.cpp:95](../../Core.cpp#L95)), `p_STORM_WindowHandlers->table[...]`
([D2Helpers.cpp:1004](../../D2Helpers.cpp#L1004)). Several declarations disagree with how the
address is used: `p_D2CLIENT_InventoryLayout` is declared `InventoryLayout**` but every use casts
it to `InventoryLayout*` ([JSGame.cpp:497](../../JSGame.cpp#L497)), i.e. the struct itself lives at
the address; same for `ChatMsg`, `ChatBoxMsg`, `NPCMenu` and the Trade/Stash/Cube layout globals
([Core.cpp:96](../../Core.cpp#L96), [Core.cpp:126](../../Core.cpp#L126),
[D2Helpers.cpp:414](../../D2Helpers.cpp#L414)). The TSV uses the usage-derived type for those
(flag `type-from-usage`).

### `ASMPTR` — raw address for inline asm

[D2Ptrs.h:256](../../D2Ptrs.h#L256): `ASMPTR(D2CLIENT, Say_I, 0x7CBDA) // Updated 1.14d //0047CBDA-BASE`

```cpp
DWORD D2CLIENT_Say_I = ((DLLNO_D2CLIENT) | ((0x7CBDA) << 8));   // 0x07CBDA00 -> 0x47CBDA
```

Used from MSVC inline asm, where a C variable operand is a memory operand: `JMP D2CLIENT_Say_I`
([Core.cpp:81](../../Core.cpp#L81)) assembles to `jmp dword ptr [D2CLIENT_Say_I]`, an indirect jump
through the resolved value. The explicit forms `call [D2CLIENT_GameAddUnit_I]`
([D2Intercepts.cpp:252](../../D2Intercepts.cpp#L252)) and `JMP [D2CLIENT_TakeWaypoint_I]`
([D2Helpers.cpp:901](../../D2Helpers.cpp#L901)) are equivalent. `FUNCPTR` variables are used the same
way inside asm (`call D2NET_ReceivePacket_I`, [D2Intercepts.cpp:39](../../D2Intercepts.cpp#L39)), and
`VARPTR`s need a double load (`mov eax, [p_D2CLIENT_MouseY]` / `mov eax, [eax]`,
[D2Intercepts.cpp:158-159](../../D2Intercepts.cpp#L158-L159)). Many `ASMPTR`s are mid-function
labels (e.g. `Say_I` is entered after `Say_ASM` rebuilds the prologue,
[Core.cpp:67-83](../../Core.cpp#L67-L83)); one, `D2CLIENT_BodyClickTable`
([D2Ptrs.h:258](../../D2Ptrs.h#L258)), is a data table indexed as `*(DWORD*)(D2CLIENT_BodyClickTable + 4*i)`
([JSGame.cpp:417](../../JSGame.cpp#L417)).

## 7. Naming conventions, wrappers and aliases

| Pattern | Meaning | Example |
|---|---|---|
| `<MODULE>_<Name>` | `FUNCPTR` (call it) or `ASMPTR` (a `DWORD` address) | `D2CLIENT_GetPlayerUnit`, `D2CLIENT_Say_I` |
| `p_<MODULE>_<Name>` | `VARPTR`: pointer to the game global; dereference it | `*p_D2CLIENT_MouseX` |
| `<MODULE>_<Name>_t` | typedef generated by `FUNCPTR`/`VARPTR` | `D2CLIENT_GetPlayerUnit_t` |
| suffix `_I`, `_II` | internal entry point or mid-function label used by an asm stub or intercept (register ABI, not C) | `D2CLIENT_GetUnitName_I`, `D2CLIENT_ClickParty_II`, `D2CLIENT_SendPacket_II` |
| suffix `_STUB` / `_ASM` | `__declspec(naked)` C++ wrapper that sets up registers and jumps/calls the `_I` address; defined in [D2Helpers.cpp](../../D2Helpers.cpp) (prototypes [D2Helpers.h:61](../../D2Helpers.h#L61), [:90-113](../../D2Helpers.h#L90-L113)), `Say_ASM` in [Core.cpp:67](../../Core.cpp#L67) | `D2CLIENT_GetUnitName_STUB` |
| trailing `_` | raw pointer hidden behind an alias that fixes an argument | `D2MULTI_PrintChannelText_` |
| `*_Intercept` / `*_Interception` / `*STUB` in D2Intercepts.cpp | patch targets installed by `Patch.h` | `GameInput_Intercept`, `ClassicSTUB` |

Some naked wrappers have no suffix and are called directly: `D2CLIENT_ClickBelt`,
`D2CLIENT_LeftClickItem`, `D2CLIENT_TakeWaypoint`, `D2CLIENT_HostilePartyUnit`
([D2Helpers.cpp:783](../../D2Helpers.cpp#L783), [:790](../../D2Helpers.cpp#L790),
[:872](../../D2Helpers.cpp#L872), [:947](../../D2Helpers.cpp#L947)),
plus the `__cdecl` asm wrapper `D2CLIENT_GetMinionCount` ([D2Helpers.cpp:927](../../D2Helpers.cpp#L927)).
`D2CLIENT_PlaySound` ([D2Helpers.cpp:856](../../D2Helpers.cpp#L856)) has the same shape but is dead:
its `CALL D2CLIENT_PlaySound_I` is commented out ([D2Helpers.cpp:867](../../D2Helpers.cpp#L867)), and
so is its only call site in `playSound()` ([JSGame.cpp:1038](../../JSGame.cpp#L1038)).

Alias macros at the end of `D2Ptrs.h` (active ones only; the two commented-out aliases are listed
in [offsets.md](offsets.md)):

| Alias | Line | Expands to | Address reached |
|---|---|---|---|
| `D2MULTI_PrintChannelText(text, color)` | [492](../../D2Ptrs.h#L492) | `D2MULTI_PrintChannelText_(0, text, color)` | FUNCPTR `D2MULTI_PrintChannelText_` |
| `D2CLIENT_GetUIState(dwVarNo)` | [493](../../D2Ptrs.h#L493) | `D2CLIENT_GetUIVar_STUB` ([D2Helpers.cpp:720](../../D2Helpers.cpp#L720)) | FUNCPTR `D2CLIENT_GetUiVar_I` (arg in `eax`) |
| `D2CLIENT_SetUIState(dwVarNo, value)` | [494](../../D2Ptrs.h#L494) | `D2CLIENT_SetUIVar(dwVarNo, value, 0)` | FUNCPTR `D2CLIENT_SetUIVar` |
| `D2CLIENT_InitAutomapLayer(layerlvl)` | [495](../../D2Ptrs.h#L495) | `D2CLIENT_InitAutomapLayer_STUB` ([D2Helpers.cpp:336](../../D2Helpers.cpp#L336)) | FUNCPTR `D2CLIENT_InitAutomapLayer_I` (arg in `edi`) |
| `D2CLIENT_GetUnitName(x)` | [496](../../D2Ptrs.h#L496) | `D2CLIENT_GetUnitName_STUB` ([D2Helpers.cpp:712](../../D2Helpers.cpp#L712)) | ASMPTR `D2CLIENT_GetUnitName_I` |
| `D2CLIENT_SetSelectedUnit(x)` | [497](../../D2Ptrs.h#L497) | `D2CLIENT_SetSelectedUnit_STUB` ([D2Helpers.cpp:728](../../D2Helpers.cpp#L728)) | FUNCPTR `D2CLIENT_SetSelectedUnit_I` (arg in `eax`) |
| `D2CLIENT_Interact_STUB(x)` | [499](../../D2Ptrs.h#L499) | `D2CLIENT_Interact_ASM` ([D2Helpers.cpp:745](../../D2Helpers.cpp#L745)) | ASMPTR `D2CLIENT_Interact_I` (stale, dead code) |
| `D2CLIENT_ClickParty(x, y)` | [500](../../D2Ptrs.h#L500) | `D2CLIENT_ClickParty_ASM` ([D2Helpers.cpp:752](../../D2Helpers.cpp#L752)) | ASMPTR `D2CLIENT_ClickParty_I` |
| `D2CLIENT_RightClickItem(...)` | [501](../../D2Ptrs.h#L501) | `D2CLIENT_ClickItemRight_ASM` ([D2Helpers.cpp:800](../../D2Helpers.cpp#L800)) | ASMPTR `D2CLIENT_ClickItemRight_I` |
| `D2CLIENT_ClickBeltRight(...)` | [502](../../D2Ptrs.h#L502) | `D2CLIENT_ClickBeltRight_ASM` ([D2Helpers.cpp:810](../../D2Helpers.cpp#L810)) | ASMPTR `D2CLIENT_ClickBeltRight_I` |
| `D2CLIENT_GetItemDesc(pUnit, pBuffer)` | [503](../../D2Ptrs.h#L503) | `D2CLIENT_GetItemDesc_ASM` ([D2Helpers.cpp:819](../../D2Helpers.cpp#L819)) | ASMPTR `D2CLIENT_GetItemDesc_I` (stale, unused) |
| `D2CLIENT_MercItemAction(...)` | [504](../../D2Ptrs.h#L504) | `D2CLIENT_MercItemAction_ASM` ([D2Helpers.cpp:847](../../D2Helpers.cpp#L847)) | ASMPTR `D2CLIENT_MercItemAction_I` |
| `D2CLIENT_SendGamePacket(dwLen, bPacket)` | [505](../../D2Ptrs.h#L505) | `D2CLIENT_SendGamePacket_ASM` ([D2Helpers.cpp:955](../../D2Helpers.cpp#L955)) | ASMPTR `D2CLIENT_SendGamePacket_I` |
| `D2COMMON_DisplayOverheadMsg(pUnit)` | [507](../../D2Ptrs.h#L507) | `D2COMMON_DisplayOverheadMsg_ASM` ([D2Helpers.cpp:833](../../D2Helpers.cpp#L833)) | ASMPTR `D2COMMON_DisplayOverheadMsg_I` (unused) |
| `D2GFX_DrawFrame(Rect)` | [509](../../D2Ptrs.h#L509) | `D2GFX_DrawRectFrame_STUB` ([D2Helpers.cpp:919](../../D2Helpers.cpp#L919)) | FUNCPTR `D2CLIENT_DrawRectFrame` (arg in `eax`) |

Because of these layers, grepping for an address's identifier is not enough to know whether it
is used; [offsets.md](offsets.md) resolves the alias/wrapper chains and reports `Referenced in`,
`unused` and `dead-code-only` per symbol.

## 8. Other address sources outside `D2Ptrs.h`

| Source | Form | Resolution | Rows in TSV |
|---|---|---|---|
| `Patches[]`, [Patch.h:8-45](../../Patch.h#L8-L45) | `GetDllOffset("<dll>", RVA)` per entry | static init, `GetModuleHandle(NULL) + RVA` | 22 `PATCH` |
| `Conditional[]`, [Patch.h:47-57](../../Patch.h#L47-L57) | same, plus `BOOL* enabled` (`&Vars.b...`) | same; installed only if `*enabled == TRUE` ([Offset.cpp:55](../../Offset.cpp#L55)) | 9 `COND_PATCH` |
| `BaseStatTable[]`, [MPQStats.cpp:4-32](../../MPQStats.cpp#L4-L32) | `dwEntry` / `dwMaxEntriesOffset`: `<= 0xFFFF` = offset into `*p_D2COMMON_sgptDataTable`; `> 0xFFFF` = absolute 1.14d **VA** | `VA - 0x400000 + d2CommonOff` ([MPQStats.cpp:41-50](../../MPQStats.cpp#L41-L50)) | 19 `DATA` (`D2COMMON_MPQ_*`) |
| `unit.description` getter, [JSUnit.cpp:453-458](../../JSUnit.cpp#L453-L458) | `GetDllOffset("D2Client.dll", 0x7BCBE8 - 0x400000)` etc. (VA minus base) | `GetModuleHandle(NULL) + RVA` | 3 `DATA` |

`Patch.h` is included only by [Offset.cpp:7](../../Offset.cpp#L7) (it defines the arrays). The
generator sweeps every compiled source for further `GetDllOffset(` call sites, for numeric
literals inside `__asm` blocks (none is an address; all are immediates and stack/struct
displacements) and for literals in the `0x400000..0xFFFFFF` / `0x6F000000..0x6FFFFFFF` ranges;
all hits are classified in [offsets.md](offsets.md). Struct field offsets used by the asm stubs
(e.g. `[ECX+0xA4]` in `D2COMMON_DisplayOverheadMsg_ASM`, [D2Helpers.cpp:836](../../D2Helpers.cpp#L836))
belong to [structs.md](structs.md).

## 9. Porting to another game build

Applies to a different Game.exe (another 1.14 revision) or to re-validating 1.14d. The macro
machinery does not need to change; the data does.

1. **Get a labelled reference.** Import 1.14d Game.exe into Ghidra and apply
   [`d2bs_symbols.tsv`](../ghidra/d2bs_symbols.tsv) with
   [`D2BSImport.java`](../ghidra/D2BSImport.java) ([../ghidra/README.md](../ghidra/README.md)).
   Treat rows flagged `stale-pre-1.14d?`, `va-only` or `captured-encoded` as unverified first.
2. **Map to the new binary.** Use Ghidra Version Tracking (or byte signatures around each
   label) from the labelled 1.14d program to the new one. `FUNC` rows are function entries; `LABEL`
   rows are mid-function addresses (jump/return targets) and need instruction-level matching;
   `PATCH` rows are instruction addresses whose `len=` bytes are overwritten.
3. **Update `D2Ptrs.h`.** Replace the offset (RVA = new VA − image base) and keep the comment
   convention `// Updated <ver> //<VA>-BASE`. The generator's status flags key on the literal
   text `1.14d` and on `VA == 0x400000 + RVA` (`classify_comment()` / `version_status()` and
   `IMAGE_BASE` in [gen_symbols.py](../ghidra/tools/gen_symbols.py)); adjust them for a new
   version string or base. Keep RVAs `<= 0x7FFFFF` ([§3](#3-encoding-and-resolution-dlloffset-and-getdlloffset)).
4. **Re-derive asm ABIs.** For every `_I`/`_II` symbol and `asm-only` FUNCPTR, re-check the
   register set-up in the corresponding stub ([call-stubs.md](call-stubs.md)). Intercepts encode
   stack layouts of the patched function: e.g. `Whisper_Intercept` relies on a `0x678`-byte frame
   ([D2Intercepts.cpp:109-111](../../D2Intercepts.cpp#L109-L111)), `GamePacketSent_Interception` on
   `[esp + 0x22 + 4 + 0xC]` ([D2Intercepts.cpp:50-51](../../D2Intercepts.cpp#L50-L51)),
   `GameAttack_Intercept` re-executes the overwritten `mov eax, [MouseY]`
   ([D2Intercepts.cpp:158-160](../../D2Intercepts.cpp#L158-L160)), and the `ChatPacketRecv` patch
   "needs a constant in ChatPacketRecv_Interception updated also" ([Patch.h:25](../../Patch.h#L25)).
5. **Patches.** Verify each site is an instruction boundary, that `len` covers whole
   instructions, and that the displaced instructions are re-created by the intercept or are
   meant to be dropped ([patches-and-hooks.md](patches-and-hooks.md)).
6. **Absolute VAs.** Update `MPQStats.cpp` (`> 0xFFFF` entries are VAs; `<= 0xFFFF` entries are
   `sgptDataTable` field offsets, which may also differ between builds) and the three VAs in
   [JSUnit.cpp:453-458](../../JSUnit.cpp#L453-L458).
7. **Structures.** Re-check `D2Structs.h` layouts ([structs.md](structs.md)); D2BS reads game
   structs directly everywhere.
8. **Regenerate and diff.** Run the generator (below); it fails on parse/count/name problems and
   reports every VA-comment mismatch.

For the planned RPC replacement nothing in this layer depends on SpiderMonkey: `D2Ptrs.h`,
`Offset.cpp`, `Patch.h`, the stubs and the intercepts can be kept as the native back end, with the
JS natives listed in the `js-index` section of [offsets.md](offsets.md) as the inventory of what
an RPC surface would have to re-expose.

## 10. Regenerating the tables and the Ghidra import

```sh
python3 docs/ghidra/tools/gen_symbols.py --repo . --out docs/ghidra/d2bs_symbols.tsv \
    --markdown docs/memory/offsets.md
```

Python 3 standard library only, deterministic output. It rewrites only the
`<!-- BEGIN GENERATED:... -->` regions of `offsets.md`, validates per-kind counts against
independent line-based counts, checks every VA comment, the `DLLNO`/`dlls[]` agreement, label
validity and the `DLLOFFSET` range, and exits non-zero on failure. The TSV schema and the Ghidra
script that consumes it are documented in [../ghidra/README.md](../ghidra/README.md).

## 11. Open questions

- Is 1.14d Game.exe ever loaded at a base other than `0x400000`? The code handles it, but all VA
  comments, the MPQ table literals and the JSUnit literals assume it; not checkable from source.
- What does Game.exe do at VA `0x4082E0`/`0x40576F` (the `D2GAME_exit0` patch, [§5.1](#51-static-initialisers-see-encoded-values-bug))?
  The intended effect of the patch cannot be determined from source; only that the installed jump
  target is wrong.
- The legacy module token is unreliable for 1.14d; deciding the true owning module of each
  function needs the binary.

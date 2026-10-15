# Call stubs: inline-asm bridges into Game.exe

Scope: every place where D2BS *calls into* Game.exe 1.14d code with a non-standard (register)
convention, i.e. the `__declspec(naked)` and inline-`__asm` wrappers in `D2Helpers.cpp` and
`Core.cpp` (`*_STUB`, `*_ASM` and a few unsuffixed ones), the alias macros at the end of
`D2Ptrs.h` that route ordinary-looking calls through them, and the game calls made from inside
the patch intercepts in `D2Intercepts.cpp`. For each stub: the C prototype, the `ASMPTR` /
`FUNCPTR` it reaches, what goes in which register and on the stack, who cleans the stack, where
the result comes back, and which D2BS code and JS APIs use it. Source of truth is the C++ in this
repository, cited as `File:line`; nothing was checked against a Game.exe binary. Statements of
the form "the callee must `ret N`" are what the stub requires to stay balanced, not observed
facts. VA = `0x400000` + RVA ([README.md](README.md)). Patch sites and the intercepts' own
contracts are in [patches-and-hooks.md](patches-and-hooks.md); per-symbol status in
[offsets.md](offsets.md); struct layouts in [structs.md](structs.md); the JS functions named
here in [../js-api/globals-game.md](../js-api/globals-game.md) and
[../js-api/unit-methods.md](../js-api/unit-methods.md).

## Contents

1. [Summary](#1-summary)
2. [How the stubs work](#2-how-the-stubs-work)
3. [Stub index](#3-stub-index)
4. [Alias macros in `D2Ptrs.h`](#4-alias-macros-in-d2ptrsh)
5. [Register and stack contracts](#5-register-and-stack-contracts)
6. [Game calls made from intercepts](#6-game-calls-made-from-intercepts)
7. [Thread and lock context](#7-thread-and-lock-context)
8. [ASMPTR usage](#8-asmptr-usage)
9. [Problems found](#9-problems-found)
10. [Open questions](#10-open-questions)

## 1. Summary

- 22 asm wrappers: 21 in `D2Helpers.cpp` (20 naked, 1 non-naked: `D2CLIENT_GetMinionCount`) and 1 in `Core.cpp` (`Say_ASM`). 17 alias macros, 2 of them commented out (`D2Ptrs.h:491-509`).
- Live (reachable from a JS native or a hook): `InitAutomapLayer_STUB`, `GetUnitName_STUB`,
  `GetUIVar_STUB`, `SetSelectedUnit_STUB`, `ClickParty_ASM`, `ClickBelt`, `LeftClickItem`,
  `ClickItemRight_ASM`, `ClickBeltRight_ASM`, `MercItemAction_ASM`, `TakeWaypoint`,
  `DrawRectFrame_STUB`, `GetMinionCount`, `HostilePartyUnit`, `SendGamePacket_ASM`, `Say_ASM`.
- Dead or unused: `Interact_ASM`, `ClickShopItem_ASM`, `ShopAction_ASM`, `GetItemDesc_ASM`,
  `DisplayOverheadMsg_ASM`, `PlaySound`. Three of them target **stale 1.13 ASMPTRs**
  (`Interact_I`, `ShopAction_I`, `GetItemDesc_I`; also `GameAddUnit_I` from the disabled
  `AddUnit_Intercept`). `D2CLIENT_PlaySound` would crash if called (returns to address 0).
- Several stubs write callee-saved registers (`ESI`, `EDI`, `EBX`) without restoring them; all of
  those are in the dead set.
- `D2CLIENT_ClickBeltRight` is called with two different argument orders
  ([§9](#9-problems-found)).
- Two stubs jump into the **middle** of a game function after rebuilding its prologue by hand:
  `Say_ASM` → `D2CLIENT_Say_I` and `D2CLIENT_TakeWaypoint` → `D2CLIENT_TakeWaypoint_I`. They hard-code
  that function's frame layout.

## 2. How the stubs work

- `__declspec(naked)`: no compiler prologue/epilogue; the asm block is the whole function and must
  return itself. Arguments arrive per the declared convention: `__fastcall` = arg1 in `ECX`,
  arg2 in `EDX`, the rest on the stack, callee pops them; `__stdcall` = all on the stack, callee
  pops; `__cdecl` = all on the stack, caller pops. MSVC x86 treats `EBX`, `ESI`, `EDI`, `EBP` as
  callee-saved; compiled C++ around a stub assumes they survive.
- Operands: a C variable in MSVC inline asm is a memory operand. `jmp D2CLIENT_X_I` /
  `call D2CLIENT_X_I` therefore assemble to `jmp/call dword ptr [D2CLIENT_X_I]`: an indirect transfer
  through the global that `DefineOffsets()` filled with the absolute address. This works the same
  for `ASMPTR` (`DWORD`) and `FUNCPTR` (function-pointer) globals; brackets (`JMP [D2CLIENT_TakeWaypoint_I]`)
  change nothing. `VARPTR`s need a double load (`MOV EAX, p_D2CLIENT_PlayerUnit` / `MOV EAX, [EAX]`,
  `D2Helpers.cpp:863-864`).
- Two transfer styles:
  - **tail jump** (`jmp`): the caller's return address stays on top of the stack, so the game
    function returns straight to the C++ caller and pops whatever stack arguments are still
    there. The stub can only reshuffle registers and stack slots first.
  - **call + ret**: the stub saves registers, pushes the game function's stack arguments, calls,
    restores and returns. The game function must pop exactly what the stub pushed.
- The `FUNCPTR` prototype in `D2Ptrs.h` is irrelevant for a target reached only from asm; the
  compiler never uses it. Where it disagrees with the stub, the stub's register set-up is the one
  that runs ([offsets.md §7.2](offsets.md#72-asm-only-funcptrs)).
- The alias macros make these calls look like plain C calls (`D2CLIENT_GetUIState(x)`), so a grep
  for the `_I` symbol alone does not find the users.

## 3. Stub index

Generated. "JS entry points" is the static call graph from the stub (and its alias) up to JS
natives and property getters, ignoring branches. `table.name` uses the `JSFunctionSpec` /
`JSPropertySpec` table and the JS-visible name (`global_funcs.x()` = global function `x`,
`unit_methods.x()` = method on Unit objects, `unit_props.x` = property). A chain that ends in a
function with no C++ caller (window hook, virtual method) is listed as such.

| Stub | Definition | Declared | Form | Game target(s) (kind, VA, D2Ptrs status) | Alias macro | Direct call sites | JS entry points (static call graph) |
|---|---|---|---|---|---|---|---|
| `D2CLIENT_InitAutomapLayer_STUB` | `D2Helpers.cpp:336-345` | `D2Helpers.h:61` | naked `__fastcall` | `D2CLIENT_InitAutomapLayer_I` (FUNCPTR, `0x00458D40`, 1.14d) | `D2CLIENT_InitAutomapLayer` (`D2Ptrs.h:495`) | `D2Helpers.cpp:349` in `InitAutomapLayer` | `global_funcs.revealLevel()`, `room_methods.reveal()` |
| `D2CLIENT_GetUnitName_STUB` | `D2Helpers.cpp:712-718` | `D2Helpers.h:90` | naked `__fastcall` | `D2CLIENT_GetUnitName_I` (ASMPTR, `0x00464A60`, 1.14d) | `D2CLIENT_GetUnitName` (`D2Ptrs.h:496`) | `D2Helpers.cpp:65` in `GetUnitName` | `global_funcs.getUnit()`, `me_props.name`, `unit_methods.getItem()`, `unit_methods.getNext()`, `unit_methods.getParent()`, `unit_props.name`<br>chain ends at (no C++ caller): `ActMap::DumpLevel`, `LevelMap::AddCollisionMap` |
| `D2CLIENT_GetUIVar_STUB` | `D2Helpers.cpp:720-726` | `D2Helpers.h:91` | naked `__fastcall` | `D2CLIENT_GetUiVar_I` (FUNCPTR, `0x004538D0`, 1.14d) | `D2CLIENT_GetUIState` (`D2Ptrs.h:493`) | `D2Handlers.cpp:217` in `KeyPress`<br>`D2Handlers.cpp:218` in `KeyPress`<br>`JSGame.cpp:985` in `my_getUIFlag`<br>`JSGame.cpp:1263` in `my_transmute`<br>`JSUnit.cpp:869` in `unit_interact`<br>`JSUnit.cpp:1491` in `item_shop` | `global_funcs.getUIFlag()`, `global_funcs.transmute()`, `unit_methods.interact()`, `unit_methods.shop()`<br>chain ends at (no C++ caller): `KeyPress` |
| `D2CLIENT_SetSelectedUnit_STUB` | `D2Helpers.cpp:728-734` | `D2Helpers.h:93` | naked `__fastcall` | `D2CLIENT_SetSelectedUnit_I` (FUNCPTR, `0x00466DE0`, 1.14d) | `D2CLIENT_SetSelectedUnit` (`D2Ptrs.h:497`) | `Core.cpp:162` in `ClickMap` | `global_funcs.clickMap()`, `unit_methods.interact()`, `unit_methods.move()` |
| `D2CLIENT_Interact_ASM` | `D2Helpers.cpp:745-750` | `D2Helpers.h:94` | naked `__fastcall` | `D2CLIENT_Interact_I` (ASMPTR, `0x0042B2E0`, stale (1.13 VA 6FADB2E0)) | `D2CLIENT_Interact_STUB` (`D2Ptrs.h:499`) | `D2Helpers.cpp:408` in `D2CLIENT_Interact` | chain ends at (no C++ caller): `D2CLIENT_Interact` |
| `D2CLIENT_ClickParty_ASM` | `D2Helpers.cpp:752-758` | `D2Helpers.h:95` | naked `__fastcall` | `D2CLIENT_ClickParty_I` (ASMPTR, `0x00479EB0`, 1.14d) | `D2CLIENT_ClickParty` (`D2Ptrs.h:500`) | `JSGame.cpp:1136` in `my_clickParty` | `global_funcs.clickParty()` |
| `D2CLIENT_ClickShopItem_ASM` | `D2Helpers.cpp:762-774` | `D2Helpers.h:96` | naked `__fastcall` | `D2CLIENT_ClickShopItem_I` (ASMPTR, `0x004B2653`, 1.14d) | - | **none** | - (unreachable) |
| `D2CLIENT_ShopAction_ASM` | `D2Helpers.cpp:776-781` | `D2Helpers.h:97` | naked `__fastcall` | `D2CLIENT_ShopAction_I` (ASMPTR, `0x0047D030`, stale (1.13 VA 6FB2D030)) | - | **none** | - (unreachable) |
| `D2CLIENT_ClickBelt` | `D2Helpers.cpp:783-788` | `D2Helpers.h:100` | naked `__fastcall` | `D2CLIENT_ClickBelt_I` (ASMPTR, `0x00498870`, 1.14d) | - | `JSGame.cpp:537` in `my_clickItem`<br>`JSGame.cpp:646` in `my_clickItem` | `global_funcs.clickItem()` |
| `D2CLIENT_LeftClickItem` | `D2Helpers.cpp:790-798` | `D2Helpers.h:113` | naked `__stdcall` | `D2CLIENT_LeftClickItem_I` (FUNCPTR, `0x0048FFE0`, 1.14d) | - | `JSGame.cpp:514` in `my_clickItem`<br>`JSGame.cpp:608` in `my_clickItem`<br>`JSGame.cpp:612` in `my_clickItem` | `global_funcs.clickItem()` |
| `D2CLIENT_ClickItemRight_ASM` | `D2Helpers.cpp:800-808` | `D2Helpers.h:99` | naked `__fastcall` | `D2CLIENT_ClickItemRight_I` (ASMPTR, `0x00487740`, 1.14d) | `D2CLIENT_RightClickItem` (`D2Ptrs.h:501`) | `JSGame.cpp:518` in `my_clickItem`<br>`JSGame.cpp:610` in `my_clickItem` | `global_funcs.clickItem()` |
| `D2CLIENT_ClickBeltRight_ASM` | `D2Helpers.cpp:810-817` | `D2Helpers.h:101` | naked `__fastcall` | `D2CLIENT_ClickBeltRight_I` (ASMPTR, `0x00498A90`, 1.14d) | `D2CLIENT_ClickBeltRight` (`D2Ptrs.h:502`) | `JSGame.cpp:539` in `my_clickItem`<br>`JSGame.cpp:648` in `my_clickItem`<br>`JSGame.cpp:650` in `my_clickItem` | `global_funcs.clickItem()` |
| `D2CLIENT_GetItemDesc_ASM` | `D2Helpers.cpp:819-831` | `D2Helpers.h:102` | naked `__fastcall` | `D2CLIENT_GetItemDesc_I` (ASMPTR, `0x0042E380`, stale (1.13 VA 6FADE380)) | `D2CLIENT_GetItemDesc` (`D2Ptrs.h:503`) | **none** | - (unreachable) |
| `D2COMMON_DisplayOverheadMsg_ASM` | `D2Helpers.cpp:833-845` | `D2Helpers.h:103` | naked `__fastcall` | `D2COMMON_DisplayOverheadMsg_I` (ASMPTR, `0x006611A0`, 1.14d) | `D2COMMON_DisplayOverheadMsg` (`D2Ptrs.h:507`) | **none** | - (unreachable) |
| `D2CLIENT_MercItemAction_ASM` | `D2Helpers.cpp:847-854` | `D2Helpers.h:104` | naked `__fastcall` | `D2CLIENT_MercItemAction_I` (ASMPTR, `0x004785B0`, 1.14d) | `D2CLIENT_MercItemAction` (`D2Ptrs.h:504`) | `JSGame.cpp:448` in `my_clickItem`<br>`JSGame.cpp:490` in `my_clickItem` | `global_funcs.clickItem()` |
| `D2CLIENT_PlaySound` | `D2Helpers.cpp:856-870` | `D2Helpers.h:106` | naked `__fastcall` | `p_D2CLIENT_PlayerUnit` (VARPTR, `0x007A6A70`, 1.14d) | - | **none** | - (unreachable) |
| `D2CLIENT_TakeWaypoint` | `D2Helpers.cpp:872-904` | `D2Helpers.h:111` | naked `__stdcall` | `D2CLIENT_TakeWaypoint_I` (ASMPTR, `0x0049D0F1`, 1.14d) | - | `JSUnit.cpp:868` in `unit_interact` | `unit_methods.interact()` |
| `D2GFX_DrawRectFrame_STUB` | `D2Helpers.cpp:919-925` | `D2Helpers.h:108` | naked `__fastcall` | `D2CLIENT_DrawRectFrame` (FUNCPTR, `0x00452E50`, 1.14d) | `D2GFX_DrawFrame` (`D2Ptrs.h:509`) | `ScreenHook.cpp:447` in `FrameHook::Draw` | chain ends at (no C++ caller): `FrameHook::Draw` |
| `D2CLIENT_GetMinionCount` | `D2Helpers.cpp:927-945` | `D2Helpers.h:109` | non-naked `__cdecl` | `D2CLIENT_GetMinionCount_I` (ASMPTR, `0x00478EE0`, 1.14d) | - | `JSUnit.cpp:1963` in `unit_getMinionCount` | `unit_methods.getMinionCount()` |
| `D2CLIENT_HostilePartyUnit` | `D2Helpers.cpp:947-953` | `D2Helpers.h:110` | naked `__fastcall` | `D2CLIENT_ClickParty_II` (ASMPTR, `0x0049B990`, 1.14d) | - | `JSGame.cpp:1128` in `my_clickParty`<br>`JSGame.cpp:1130` in `my_clickParty`<br>`JSGame.cpp:1132` in `my_clickParty`<br>`JSGame.cpp:1134` in `my_clickParty` | `global_funcs.clickParty()` |
| `D2CLIENT_SendGamePacket_ASM` | `D2Helpers.cpp:955-965` | `D2Helpers.h:112` | naked `__fastcall` | `D2CLIENT_SendGamePacket_I` (ASMPTR, `0x00478350`, 1.14d) | `D2CLIENT_SendGamePacket` (`D2Ptrs.h:505`) | `D2Helpers.cpp:253` in `SetSkill`<br>`Game.cpp:22` in `UseStatPoint`<br>`Game.cpp:36` in `UseSkillPoint` | `global_funcs.useSkillPoint()`, `global_funcs.useStatPoint()`, `unit_methods.setSkill()` |
| `Say_ASM` | `Core.cpp:67-83` | - | naked `__fastcall` | `D2CLIENT_Say_I` (ASMPTR, `0x0047CBDA`, 1.14d) | - | `Core.cpp:107` in `Say` | `global_funcs.say()` |

## 4. Alias macros in `D2Ptrs.h`

Generated from `D2Ptrs.h:491-509`. The aliases
exist in every translation unit that includes `D2Ptrs.h` (the `#else` branch of `__D2PTRS_LIST_`,
see [README.md §4](README.md#4-d2ptrsh-is-included-three-ways)).

| Line | Alias | Expands to | Status | Target stub / function | Live call sites |
|---|---|---|---|---|---|
| `D2Ptrs.h:491` | `D2CLIENT_TestPvpFlag(dwId1, dwId2, dwFlag)` | `(D2CLIENT_TestPvpFlag_STUB(dwId1, dwId2, dwFlag))` | commented out | `D2CLIENT_TestPvpFlag_STUB` (stub (not defined)) | - |
| `D2Ptrs.h:492` | `D2MULTI_PrintChannelText(text, color)` | `(D2MULTI_PrintChannelText_(0, text, color))` | active | `D2MULTI_PrintChannelText_` (D2Ptrs FUNCPTR) | **none** |
| `D2Ptrs.h:493` | `D2CLIENT_GetUIState(dwVarNo)` | `(D2CLIENT_GetUIVar_STUB(dwVarNo))` | active | `D2CLIENT_GetUIVar_STUB` (stub `D2Helpers.cpp:720`) | `D2Handlers.cpp:217`, `D2Handlers.cpp:218`, `JSGame.cpp:985`, `JSGame.cpp:1263`, `JSUnit.cpp:869`, `JSUnit.cpp:1491` |
| `D2Ptrs.h:494` | `D2CLIENT_SetUIState(dwVarNo, value)` | `(D2CLIENT_SetUIVar(dwVarNo, value, 0))` | active | `D2CLIENT_SetUIVar` (D2Ptrs FUNCPTR) | `JSGame.cpp:1265`, `JSGame.cpp:1270` |
| `D2Ptrs.h:495` | `D2CLIENT_InitAutomapLayer(layerlvl)` | `((AutomapLayer*)D2CLIENT_InitAutomapLayer_STUB(layerlvl))` | active | `D2CLIENT_InitAutomapLayer_STUB` (stub `D2Helpers.cpp:336`) | `D2Helpers.cpp:349` |
| `D2Ptrs.h:496` | `D2CLIENT_GetUnitName(x)` | `(wchar_t*)D2CLIENT_GetUnitName_STUB((DWORD)x)` | active | `D2CLIENT_GetUnitName_STUB` (stub `D2Helpers.cpp:712`) | `D2Helpers.cpp:65` |
| `D2Ptrs.h:497` | `D2CLIENT_SetSelectedUnit(x)` | `(D2CLIENT_SetSelectedUnit_STUB((DWORD)x))` | active | `D2CLIENT_SetSelectedUnit_STUB` (stub `D2Helpers.cpp:728`) | `Core.cpp:162` |
| `D2Ptrs.h:498` | `D2CLIENT_LoadUIImage(x)` | `((CellFile*)D2CLIENT_LoadUIImage_ASM(x))` | commented out | `D2CLIENT_LoadUIImage_ASM` (stub (not defined)) | - |
| `D2Ptrs.h:499` | `D2CLIENT_Interact_STUB(x)` | `(D2CLIENT_Interact_ASM((DWORD)x))` | active | `D2CLIENT_Interact_ASM` (stub `D2Helpers.cpp:745`) | `D2Helpers.cpp:408` |
| `D2Ptrs.h:500` | `D2CLIENT_ClickParty(x, y)` | `(D2CLIENT_ClickParty_ASM((DWORD)x, (DWORD)y))` | active | `D2CLIENT_ClickParty_ASM` (stub `D2Helpers.cpp:752`) | `JSGame.cpp:1136` |
| `D2Ptrs.h:501` | `D2CLIENT_RightClickItem(x, y, loc, player, invdata)` | `D2CLIENT_ClickItemRight_ASM(x, y, loc, (DWORD)player, (DWORD)invdata)` | active | `D2CLIENT_ClickItemRight_ASM` (stub `D2Helpers.cpp:800`) | `JSGame.cpp:518`, `JSGame.cpp:610` |
| `D2Ptrs.h:502` | `D2CLIENT_ClickBeltRight(pPlayer, pInventory, dwShift, dwPotPos)` | `D2CLIENT_ClickBeltRight_ASM((DWORD)pPlayer, (DWORD)pInventory, dwShift, dwPotPos)` | active | `D2CLIENT_ClickBeltRight_ASM` (stub `D2Helpers.cpp:810`) | `JSGame.cpp:539`, `JSGame.cpp:648`, `JSGame.cpp:650` |
| `D2Ptrs.h:503` | `D2CLIENT_GetItemDesc(pUnit, pBuffer)` | `D2CLIENT_GetItemDesc_ASM((DWORD)pUnit, pBuffer)` | active | `D2CLIENT_GetItemDesc_ASM` (stub `D2Helpers.cpp:819`) | **none** |
| `D2Ptrs.h:504` | `D2CLIENT_MercItemAction(bPacketType, dwSlotId)` | `D2CLIENT_MercItemAction_ASM(bPacketType, dwSlotId)` | active | `D2CLIENT_MercItemAction_ASM` (stub `D2Helpers.cpp:847`) | `JSGame.cpp:448`, `JSGame.cpp:490` |
| `D2Ptrs.h:505` | `D2CLIENT_SendGamePacket(dwLen, bPacket)` | `D2CLIENT_SendGamePacket_ASM(dwLen, bPacket)` | active | `D2CLIENT_SendGamePacket_ASM` (stub `D2Helpers.cpp:955`) | `D2Helpers.cpp:253`, `Game.cpp:22`, `Game.cpp:36` |
| `D2Ptrs.h:507` | `D2COMMON_DisplayOverheadMsg(pUnit)` | `D2COMMON_DisplayOverheadMsg_ASM((DWORD)pUnit)` | active | `D2COMMON_DisplayOverheadMsg_ASM` (stub `D2Helpers.cpp:833`) | **none** |
| `D2Ptrs.h:509` | `D2GFX_DrawFrame(Rect)` | `D2GFX_DrawRectFrame_STUB(Rect)` | active | `D2GFX_DrawRectFrame_STUB` (stub `D2Helpers.cpp:919`) | `ScreenHook.cpp:447` |

Notes: `D2CLIENT_SetUIState` and `D2MULTI_PrintChannelText` are plain argument-fixing aliases of
`FUNCPTR`s (no asm). `D2CLIENT_TestPvpFlag` is commented out because 1.14d's `TestPvpFlag` is a
normal `__fastcall` `FUNCPTR` (`D2Ptrs.h:130`); the old `D2CLIENT_TestPvpFlag_STUB`
is commented out too (`D2Helpers.cpp:905`).
`D2CLIENT_LoadUIImage_ASM` is declared twice (`D2Helpers.h:92`,
`D2Helpers.h:105`) but its definition is
commented out (`D2Helpers.cpp:735`); any call
would fail to link.

## 5. Register and stack contracts

Notation: `[ESP]` = return address at the moment control enters the game code; `+4`, `+8`, ...
the next stack slots. "C in" is what the C++ caller provides per the declared convention.

### 5.1 Register-shuffle tail jumps

| Stub (definition) | C in | At game entry | Target | Callee must | Result |
|---|---|---|---|---|---|
| `D2CLIENT_GetUnitName_STUB` `D2Helpers.cpp:712-718` | `ECX` = `UnitAny*` | `ECX` = unit (the 1.13 `mov eax, ecx` is commented out, `D2Helpers.cpp:715`) | `D2CLIENT_GetUnitName_I` (ASMPTR, RVA `0x64A60`, VA `0x00464A60`, `D2Ptrs.h:247`) | `ret` | `EAX` = `wchar_t*` name (cast by the alias) |
| `D2CLIENT_GetUIVar_STUB` `D2Helpers.cpp:720-726` | `ECX` = UI var number | `EAX` = `ECX` = var | `D2CLIENT_GetUiVar_I` (FUNCPTR, RVA `0x538D0`, VA `0x004538D0`, `D2Ptrs.h:116`; declared `DWORD __fastcall (DWORD)`) | `ret` | `EAX` = state |
| `D2CLIENT_SetSelectedUnit_STUB` `D2Helpers.cpp:728-734` | `ECX` = `UnitAny*` (or 0) | `EAX` = `ECX` = unit | `D2CLIENT_SetSelectedUnit_I` (FUNCPTR, RVA `0x66DE0`, VA `0x00466DE0`, `D2Ptrs.h:73`) | `ret` | none |
| `D2CLIENT_Interact_ASM` `D2Helpers.cpp:745-750` | `ECX` = `UnitInteraction*` | `ESI` = `ECX` = struct; **`ESI` not restored** | `D2CLIENT_Interact_I` (ASMPTR, RVA `0x2B2E0`, VA `0x0042B2E0`, `D2Ptrs.h:240`) **stale** | `ret` | none |
| `D2CLIENT_ClickParty_ASM` `D2Helpers.cpp:752-758` | `ECX` = `RosterUnit*`, `EDX` = mode | `EAX` = `ECX` = roster unit, `EDX` = mode | `D2CLIENT_ClickParty_I` (ASMPTR, RVA `0x79EB0`, VA `0x00479EB0`, `D2Ptrs.h:242`) | `ret` | `EAX` (declared `DWORD`, unused by the caller) |
| `D2CLIENT_HostilePartyUnit` `D2Helpers.cpp:947-953` | `ECX` = `RosterUnit*`, `EDX` = button | `ECX` = roster unit, `EAX` = `EDX` = button | `D2CLIENT_ClickParty_II` (ASMPTR, RVA `0x9B990`, VA `0x0049B990`, `D2Ptrs.h:243`) | `ret` | none |
| `D2CLIENT_MercItemAction_ASM` `D2Helpers.cpp:847-854` | `ECX` = packet type, `EDX` = slot | unchanged (the 1.13 `mov eax, ecx` / `mov ecx, edx` are commented out, `D2Helpers.cpp:850`) | `D2CLIENT_MercItemAction_I` (ASMPTR, RVA `0x785B0`, VA `0x004785B0`, `D2Ptrs.h:238`) | `ret` | none |
| `D2GFX_DrawRectFrame_STUB` `D2Helpers.cpp:919-925` | `ECX` = `RECT*` | `EAX` = `ECX` = rect | `D2CLIENT_DrawRectFrame` (FUNCPTR, RVA `0x52E50`, VA `0x00452E50`, `D2Ptrs.h:118`; declared `VOID __fastcall (DWORD Rect)`; note the `D2GFX_` name but `D2CLIENT_` target) | `ret` | none |
| `D2CLIENT_ShopAction_ASM` `D2Helpers.cpp:776-781` | `ECX` = arg1, `EDX` = arg2, 6 stack args | unchanged | `D2CLIENT_ShopAction_I` (ASMPTR, RVA `0x7D030`, VA `0x0047D030`, `D2Ptrs.h:245`) **stale** | `ret 18h` | none |

`D2CLIENT_ShopAction_ASM`'s parameter names differ between the header
(`D2Helpers.h:97`: `pTable, pItem, pNPC, ...`) and the
definition (`D2Helpers.cpp:776`: `pItem, pNpc, pNPC, ...`). The JS shop code does not use
it; `unit.shop()` calls the 1.14d `FUNCPTR` `D2CLIENT_ShopAction` (FUNCPTR, RVA `0xB3870`, VA `0x004B3870`, `D2Ptrs.h:83`)
directly (`JSUnit.cpp:1519`).

### 5.2 Stack-rewriting tail jumps (inventory and belt clicks)

These pop the caller's return address, move one stack argument into `EAX`, and put the return
address back where that argument was, so the game function sees one stack argument fewer.

| Stub (definition) | C in | At game entry | Target | Callee must | Callers |
|---|---|---|---|---|---|
| `D2CLIENT_LeftClickItem` `D2Helpers.cpp:790-798`, `__stdcall` (7 args) | stack: `Location, pPlayer, pInventory, x, y, dwClickType, pLayout` | `EAX` = `Location`; `[ESP+4..+18h]` = `pPlayer, pInventory, x, y, dwClickType, pLayout` | `D2CLIENT_LeftClickItem_I` (FUNCPTR, RVA `0x8FFE0`, VA `0x0048FFE0`, `D2Ptrs.h:96`) | `ret 18h` | `clickItem()` |
| `D2CLIENT_ClickItemRight_ASM` `D2Helpers.cpp:800-808`, `__fastcall` | `ECX` = x, `EDX` = y, stack: `Location, Player, pUnitInventory` | `ECX` = y, `EDX` = x (`xchg`), `EAX` = `Location`; `[ESP+4]` = player, `[ESP+8]` = inventory | `D2CLIENT_ClickItemRight_I` (ASMPTR, RVA `0x87740`, VA `0x00487740`, `D2Ptrs.h:237`) | `ret 8` | `clickItem()` via `D2CLIENT_RightClickItem` |
| `D2CLIENT_ClickBeltRight_ASM` `D2Helpers.cpp:810-817`, `__fastcall` | `ECX` = arg1, `EDX` = arg2, stack: `HoldShift, dwPotPos` | `ECX`, `EDX` unchanged, `EAX` = `HoldShift` (the comment says "location"), `[ESP+4]` = `dwPotPos` | `D2CLIENT_ClickBeltRight_I` (ASMPTR, RVA `0x98A90`, VA `0x00498A90`, `D2Ptrs.h:236`) | `ret 4` | `clickItem()` via `D2CLIENT_ClickBeltRight` |
| `D2CLIENT_ClickBelt` `D2Helpers.cpp:783-788`, `__fastcall` | `ECX` = x, `EDX` = y, stack: `pInventoryData` | `ECX` = x, `EAX` = `EDX` = y, `[ESP+4]` = inventory | `D2CLIENT_ClickBelt_I` (ASMPTR, RVA `0x98870`, VA `0x00498870`, `D2Ptrs.h:235`) | `ret 4` | `clickItem()` |
| `D2CLIENT_ClickShopItem_ASM` `D2Helpers.cpp:762-774`, `__fastcall` | `ECX` = x, `EDX` = y, stack: `BuyOrSell` | `ESI` = x, `EDI` = y (**neither restored**); stack rebuilt as `[ESP+4]` = 1, `[ESP+8]` = `BuyOrSell` | `D2CLIENT_ClickShopItem_I` (ASMPTR, RVA `0xB2653`, VA `0x004B2653`, `D2Ptrs.h:234`, unaligned: a mid-function label) | `ret 8` | none ("obsoleted", "isn't finished anyway!", `D2Helpers.cpp:761`) |

- `D2CLIENT_LeftClickItem_I`'s `FUNCPTR` prototype declares seven stack parameters with `Location`
  last (`D2Ptrs.h:96-98`). The stub passes six
  on the stack and `Location` in `EAX`; only the stub's form is ever executed.
- `D2CLIENT_ClickItemRight_ASM`'s last two parameters are named `pItem, pItemPath` in the header
  (`D2Helpers.h:99`) and `Player, pUnitInventory` in the
  definition; the alias `D2CLIENT_RightClickItem(x, y, loc, player, invdata)` (`D2Ptrs.h:501`)
  passes player and inventory.
- `D2CLIENT_ClickBeltRight(pPlayer, pInventory, dwShift, dwPotPos)` (`D2Ptrs.h:502`)
  forwards its first argument to `ECX` and its second to `EDX`. The call sites disagree on the
  order ([§9](#9-problems-found)).

### 5.3 Call-and-return stubs

| Stub (definition) | C in | Saved / restored | At game entry | Target | Callee must | Result |
|---|---|---|---|---|---|---|
| `D2CLIENT_InitAutomapLayer_STUB` `D2Helpers.cpp:336-345`, `__fastcall` | `ECX` = layer number | `EDI` | `EDI` = `ECX` = layer number ("Updated 1.14d Registers changed.", `D2Helpers.cpp:339`) | `D2CLIENT_InitAutomapLayer_I` (FUNCPTR, RVA `0x58D40`, VA `0x00458D40`, `D2Ptrs.h:93`) | `ret` (no stack args) | `EAX` = `AutomapLayer*` |
| `D2CLIENT_SendGamePacket_ASM` `D2Helpers.cpp:955-965`, `__fastcall` | `ECX` = length, `EDX` = `BYTE*` | `EDI` | `EDI` = length, `[ESP+4]` = packet pointer | `D2CLIENT_SendGamePacket_I` (ASMPTR, RVA `0x78350`, VA `0x00478350`, `D2Ptrs.h:283`) | `ret 4` (the stub `pop edi`s straight after the call) | `EAX` (declared `DWORD`; no caller reads it) |
| `D2CLIENT_GetItemDesc_ASM` `D2Helpers.cpp:819-831`, `__fastcall` | `ECX` = item, `EDX` = `wchar_t*` buffer | `EDI` | `EDI` = buffer; `[ESP+4]` = item, `[ESP+8]` = 1 ("TRUE = New lines"), `[ESP+0xC]` = 0 | `D2CLIENT_GetItemDesc_I` (ASMPTR, RVA `0x2E380`, VA `0x0042E380`, `D2Ptrs.h:248`) **stale** | `ret 0Ch` | none |
| `D2COMMON_DisplayOverheadMsg_ASM` `D2Helpers.cpp:833-845`, `__fastcall` | `ECX` = `UnitAny*` | none; **`ESI` clobbered** | `ESI` = `&unit->pOMsg` (`ECX+0xA4`), `EAX` = `unit->pOMsg`; `[ESP+4]` = 0, `[ESP+8]` = `pOMsg` | `D2COMMON_DisplayOverheadMsg_I` (ASMPTR, RVA `0x2611A0`, VA `0x006611A0`, `D2Ptrs.h:355`) | `ret 8` | none |
| `D2CLIENT_GetMinionCount` `D2Helpers.cpp:927-945`, **non-naked `__cdecl`** | stack: `pUnit`, `dwType` (compiler frame) | `EAX`, `ECX`, `EDX` pushed/popped around the call; the compiler handles the rest | `ECX` = unit, `EDX` = type | `D2CLIENT_GetMinionCount_I` (ASMPTR, RVA `0x78EE0`, VA `0x00478EE0`, `D2Ptrs.h:262`) | `ret` (nothing pushed) | `EAX`, stored to `dwResult` and returned normally |
| `D2CLIENT_PlaySound` `D2Helpers.cpp:856-870`, `__fastcall` | `ECX` = sound id | none; **`EBX` clobbered** | `EBX` = id, three `NULL`s pushed, `ECX` = `*p_D2CLIENT_PlayerUnit`, `EDX` = id; the call is commented out (`D2Helpers.cpp:867`) | none (`D2CLIENT_PlaySound_I` does not exist in `D2Ptrs.h`) | - | `RETN` pops one of the pushed `NULL`s as its return address: **jumps to 0** |

`UnitAny+0xA4` is `pOMsg` ([structs.md](structs.md)). `D2COMMON_DisplayOverheadMsg_ASM` has no
callers; JS `unit.overhead()` builds the message through `D2COMMON_GenerateOverheadMsg` instead.

### 5.4 `Say_ASM` — entering `D2CLIENT_Say_I` mid-function

Definition `Core.cpp:67-83`, `void __declspec(naked) __fastcall Say_ASM(DWORD dwPtr)`; target ASMPTR
`D2CLIENT_Say_I` (ASMPTR, RVA `0x7CBDA`, VA `0x0047CBDA`, `D2Ptrs.h:256`), an unaligned address, i.e. a label inside a game function.

```
POP  EAX            ; caller's return address
PUSH ECX            ; dwPtr becomes a stack argument
PUSH EAX            ; return address back on top: now looks like a 1-arg __stdcall call
PUSH EBP
MOV  EBP, ESP
SUB  ESP, 0x110     ; the game function's local frame size
PUSH EBX
PUSH ESI
PUSH EDI            ; the game function's register saves, in its order
MOV  EBX, [EBP+8]   ; EBX = dwPtr (what the game code after its prologue expects)
JMP  D2CLIENT_Say_I ; continue in the game function past its prologue
```

- State at `D2CLIENT_Say_I`: `EBP` frame with `[EBP+4]` = return into `Say()`, `[EBP+8]` = `dwPtr`;
  `0x110` bytes of locals; `EBX`, `ESI`, `EDI` saved; `EBX` = `dwPtr`.
- The game function's own epilogue must undo exactly this (`pop edi/esi/ebx`, `mov esp, ebp`,
  `pop ebp`, `ret 4`) for the stack to balance in the `__fastcall` caller.
- Hard-coded: the `0x110` frame and the push order, both of which must match the game function
  that contains `0x0047CBDA`. A leftover `// MOV EBP, [D2LANG_Say_II]` (`Core.cpp:80`)
  refers to the otherwise unused `D2LANG_Say_II` (ASMPTR, RVA `0x126800`, VA `0x00526800`, `D2Ptrs.h:424`).
- Caller: `Say()` (`Core.cpp:85`) passes `(DWORD)&aMsg`, the address of a local `MSG*`
  (`Core.cpp:107`), after copying the text into the game's chat buffer at
  `p_D2CLIENT_ChatMsg` (`Core.cpp:96`) and setting
  `Vars.bDontCatchNextMsg` so D2BS's own chat hook lets the line through
  ([patches-and-hooks.md §5.1](patches-and-hooks.md#51-gameinput_intercept--in-game-chat-line)). Only
  in game (`*p_D2CLIENT_PlayerUnit` non-NULL); out of game, when a chat-channel screen is detected,
  `Say()` copies the text to `p_D2MULTI_ChatBoxMsg` and calls `D2MULTI_DoChat` instead
  (`Core.cpp:127`).
- JS: `say()` (`JSGame.cpp:1065`).

### 5.5 `D2CLIENT_TakeWaypoint` — entering `D2CLIENT_TakeWaypoint_I` mid-function

Definition `D2Helpers.cpp:872-904`,
`__declspec(naked) void __stdcall D2CLIENT_TakeWaypoint(DWORD dwWaypointId, DWORD dwArea)`; target
`D2CLIENT_TakeWaypoint_I` (ASMPTR, RVA `0x9D0F1`, VA `0x0049D0F1`, `D2Ptrs.h:232`), unaligned (mid-function).

1. Outer frame: `PUSH EBP; MOV EBP, ESP; SUB ESP, 0x20; PUSH EBX; PUSH ESI; PUSH EDI;
   AND DWORD PTR [EBP-0x20], 0` (a 0x20-byte struct whose first dword is 0); `PUSH 0`;
   `CALL _TakeWaypoint`.
2. `_TakeWaypoint:` `PUSH EBP; PUSH EBX; PUSH ESI; PUSH EDI` (the game function's saves, but no
   `MOV EBP, ESP`: `EBP` still points at the outer frame); `XOR EDI, EDI`; `MOV EBX, 1`;
   `MOV EDX, [EBP+8]` (= `dwWaypointId`); `MOV ECX, [EBP+0xC]` (= `dwArea`); `PUSH ECX`;
   `LEA ESI, [EBP-0x20]` (= the struct); `JMP [D2CLIENT_TakeWaypoint_I]`
   (`D2Helpers.cpp:889-901`).
3. State at the game label: `EDI` = 0, `EBX` = 1, `EDX` = waypoint unit id, `ECX` = destination
   area, `ESI` = struct pointer; stack: `[ESP]` = area (just pushed), then saved
   `EDI`, `ESI`, `EBX`, `EBP`, the return address into the outer frame, and the pushed `0` (the
   game function's one stack argument).
4. Return: the game function is expected to consume the pushed area value, pop its saves and
   `ret 4` (dropping the `0`); the outer frame then restores `EBX/ESI/EDI`, `LEAVE`, `RETN 8` (the two `__stdcall`
   arguments).

Hard-coded: the struct size `0x20`, the constants `EBX = 1` / `EDI = 0` / argument `0`, the push
order, and which value is in which register; all must match the game function containing
`0x0049D0F1`. Caller: `unit.interact(areaId)` on a waypoint, passing `pUnit->dwUnitId` and the area
(`JSUnit.cpp:868`).

## 6. Game calls made from intercepts

The intercepts are entered *from* game code ([patches-and-hooks.md §5](patches-and-hooks.md#5-intercept-reference))
but also call or jump back into it. Generated list of every `D2Ptrs.h` symbol referenced in
`D2Intercepts.cpp`:

| Intercept | Line | Instruction | Game symbol | Kind | VA | D2Ptrs status |
|---|---|---|---|---|---|---|
| `GamePacketReceived_Intercept` | `D2Intercepts.cpp:39` | `call D2NET_ReceivePacket_I` | `D2NET_ReceivePacket_I` | FUNCPTR | `0x0052B920` | 1.14d |
| `GamePacketSent_Interception` | `D2Intercepts.cpp:67` | `jmp D2CLIENT_SendPacket_II` | `D2CLIENT_SendPacket_II` | ASMPTR | `0x0052AE62` | 1.14d |
| `GameInput_Intercept` | `D2Intercepts.cpp:83` | `call D2CLIENT_InputCall_I` | `D2CLIENT_InputCall_I` | ASMPTR | `0x004787B0` | 1.14d |
| `GetSelectedUnit_Intercept` | `D2Intercepts.cpp:103` | `return D2CLIENT_GetSelectedUnit()` | `D2CLIENT_GetSelectedUnit` | FUNCPTR | `0x00467A10` | 1.14d |
| `GameAttack_Intercept` | `D2Intercepts.cpp:150` | `call D2CLIENT_GetSelectedUnit` | `D2CLIENT_GetSelectedUnit` | FUNCPTR | `0x00467A10` | 1.14d |
| `GameAttack_Intercept` | `D2Intercepts.cpp:158` | `mov eax, [p_D2CLIENT_MouseY]` | `p_D2CLIENT_MouseY` | VARPTR | `0x007A6AAC` | 1.14d |
| `PlayerAssignment_Intercept` | `D2Intercepts.cpp:168` | `CALL D2CLIENT_AssignPlayer_I` | `D2CLIENT_AssignPlayer_I` | ASMPTR | `0x00466200` | 1.14d |
| `CongratsScreen_Intercept` | `D2Intercepts.cpp:193` | `call D2CLIENT_CongratsScreen_I` | `D2CLIENT_CongratsScreen_I` | ASMPTR | `0x004F6190` | 1.14d |
| `GameLeave_Intercept` | `D2Intercepts.cpp:227` | `jmp D2CLIENT_GameLeave_I` | `D2CLIENT_GameLeave_I` | ASMPTR | `0x00481830` | 1.14d |
| `ChannelInput_Intercept` | `D2Intercepts.cpp:242` | `call D2MULTI_ChannelInput_I` | `D2MULTI_ChannelInput_I` | ASMPTR | `0x004428D0` | 1.14d |
| `AddUnit_Intercept` | `D2Intercepts.cpp:252` | `call [D2CLIENT_GameAddUnit_I]` | `D2CLIENT_GameAddUnit_I` | ASMPTR | `0x004628E0` | stale (1.13 VA 6FB128E0) |
| `ClassicSTUB` | `D2Intercepts.cpp:274` | `*p_BNCLIENT_ClassicKey = Vars.szClassic` | `p_BNCLIENT_ClassicKey` | VARPTR | `0x00882744` | 1.14d |
| `ClassicSTUB` | `D2Intercepts.cpp:277` | `jmp BNCLIENT_DClass` | `BNCLIENT_DClass` | ASMPTR | `0x00523673` | 1.14d |
| `LodSTUB` | `D2Intercepts.cpp:282` | `*p_BNCLIENT_XPacKey = Vars.szLod` | `p_BNCLIENT_XPacKey` | VARPTR | `0x0088274C` | 1.14d |
| `LodSTUB` | `D2Intercepts.cpp:285` | `jmp BNCLIENT_DLod` | `BNCLIENT_DLod` | ASMPTR | `0x0052395D` | 1.14d |
| `CacheFix` | `D2Intercepts.cpp:353` | `GetWindowText(D2GFX_GetHwnd(), szTitle, 128)` | `D2GFX_GetHwnd` | FUNCPTR | `0x004F59A0` | 1.14d |

Register set-up for these transfers: `D2NET_ReceivePacket_I` gets the original `ECX` (packet),
`EDX` (length, or 0 when blocked) and a re-pushed copy of the stack argument; `D2CLIENT_InputCall_I`,
`D2MULTI_ChannelInput_I`, `D2CLIENT_AssignPlayer_I`, `D2CLIENT_CongratsScreen_I` are called with the
registers as they were at the patch site (`ChannelInput_I`: `ECX` only); `D2CLIENT_GameLeave_I`
is tail-jumped to and returns straight to the patch site; `D2CLIENT_SendPacket_II`,
`BNCLIENT_DClass` and `BNCLIENT_DLod` are labels inside the patched game function where execution
resumes. Details per intercept in [patches-and-hooks.md §5](patches-and-hooks.md#5-intercept-reference).

## 7. Thread and lock context

JS natives run on script threads, not the game thread. The game-loop lock
(`Vars.cGameLoopSection`, taken with `AutoCriticalRoom`, `CriticalSections.h:31-55`)
is the only thing that keeps the game thread parked while a script thread runs game code
([patches-and-hooks.md §8](patches-and-hooks.md#8-hooks-that-are-not-code-patches)). Generated:
which JS natives that reach a stub take the lock directly in their body (a lock taken inside a
helper they call is not counted). "no" means nothing on that path parks the game thread, so the
stub runs concurrently with it.

`AutoCriticalRoom` is created with `new` and released only by `delete`, so an early `return`
without `delete` keeps the lock for good: for example `GetLevel()` returns without releasing when
the game is not ready (`D2Helpers.cpp:176`), after which `GameDraw` /
`TimerProc` block in `EnterCriticalSection` (not on a stub path; noted because an RPC layer would
reuse this lock).

| JS native | Definition | Takes `AutoCriticalRoom` (game-loop lock)? | Stubs reached |
|---|---|---|---|
| `item_shop` | `JSUnit.cpp:1464` | yes, `JSUnit.cpp:1470` | `D2CLIENT_GetUIVar_STUB` |
| `my_clickItem` | `JSGame.cpp:357` | yes, `JSGame.cpp:364` | `D2CLIENT_ClickBelt`, `D2CLIENT_ClickBeltRight_ASM`, `D2CLIENT_ClickItemRight_ASM`, `D2CLIENT_LeftClickItem`, `D2CLIENT_MercItemAction_ASM` |
| `my_clickMap` | `JSGame.cpp:63` | no | `D2CLIENT_SetSelectedUnit_STUB` |
| `my_clickParty` | `JSGame.cpp:1074` | no | `D2CLIENT_ClickParty_ASM`, `D2CLIENT_HostilePartyUnit` |
| `my_getUIFlag` | `JSGame.cpp:975` | no | `D2CLIENT_GetUIVar_STUB` |
| `my_revealLevel` | `JSGame.cpp:1456` | yes, `JSGame.cpp:1474` | `D2CLIENT_InitAutomapLayer_STUB` |
| `my_say` | `JSGame.cpp:1044` | no | `Say_ASM` |
| `my_transmute` | `JSGame.cpp:1258` | no | `D2CLIENT_GetUIVar_STUB` |
| `my_useSkillPoint` | `JSGame.cpp:1159` | no | `D2CLIENT_SendGamePacket_ASM` |
| `my_useStatPoint` | `JSGame.cpp:1143` | no | `D2CLIENT_SendGamePacket_ASM` |
| `room_reveal` | `JSRoom.cpp:436` | yes, `JSRoom.cpp:443` | `D2CLIENT_InitAutomapLayer_STUB` |
| `unit_getItem` | `JSUnit.cpp:1796` | no | `D2CLIENT_GetUnitName_STUB` |
| `unit_getMinionCount` | `JSUnit.cpp:1944` | no | `D2CLIENT_GetMinionCount` |
| `unit_getNext` | `JSUnit.cpp:642` | no | `D2CLIENT_GetUnitName_STUB` |
| `unit_getParent` | `JSUnit.cpp:1572` | no | `D2CLIENT_GetUnitName_STUB` |
| `unit_getProperty` | `JSUnit.cpp:47` | yes, `JSUnit.cpp:448` (only in `case ITEM_DESC`) | `D2CLIENT_GetUnitName_STUB` |
| `unit_getUnit` | `JSUnit.cpp:572` | no | `D2CLIENT_GetUnitName_STUB` |
| `unit_interact` | `JSUnit.cpp:816` | no | `D2CLIENT_GetUIVar_STUB`, `D2CLIENT_SetSelectedUnit_STUB`, `D2CLIENT_TakeWaypoint` |
| `unit_move` | `JSUnit.cpp:1861` | no | `D2CLIENT_SetSelectedUnit_STUB` |
| `unit_setskill` | `JSUnit.cpp:1709` | no | `D2CLIENT_SendGamePacket_ASM` |

The window-hook path (`KeyPress` → `D2CLIENT_GetUIState`, `D2Handlers.cpp:217`)
runs on the game's window thread, and `FrameHook::Draw` → `D2GFX_DrawFrame` runs inside
`GameDraw`/`GameDrawOOG`, i.e. on the game thread.

## 8. ASMPTR usage

Generated: every `ASMPTR` in `D2Ptrs.h`, where inline asm references it, and other C++ uses.

| ASMPTR | VA | D2Ptrs status | Referenced from inline asm | Other C++ uses |
|---|---|---|---|---|
| `D2CLIENT_TakeWaypoint_I` (`D2Ptrs.h:232`) | `0x0049D0F1` | 1.14d | `D2Helpers.cpp:901` in `D2CLIENT_TakeWaypoint` | - |
| `D2CLIENT_ClickShopItem_I` (`D2Ptrs.h:234`) | `0x004B2653` | 1.14d | `D2Helpers.cpp:772` in `D2CLIENT_ClickShopItem_ASM` | - |
| `D2CLIENT_ClickBelt_I` (`D2Ptrs.h:235`) | `0x00498870` | 1.14d | `D2Helpers.cpp:786` in `D2CLIENT_ClickBelt` | - |
| `D2CLIENT_ClickBeltRight_I` (`D2Ptrs.h:236`) | `0x00498A90` | 1.14d | `D2Helpers.cpp:815` in `D2CLIENT_ClickBeltRight_ASM` | - |
| `D2CLIENT_ClickItemRight_I` (`D2Ptrs.h:237`) | `0x00487740` | 1.14d | `D2Helpers.cpp:806` in `D2CLIENT_ClickItemRight_ASM` | - |
| `D2CLIENT_MercItemAction_I` (`D2Ptrs.h:238`) | `0x004785B0` | 1.14d | `D2Helpers.cpp:852` in `D2CLIENT_MercItemAction_ASM` | - |
| `D2CLIENT_Interact_I` (`D2Ptrs.h:240`) | `0x0042B2E0` | stale (1.13 VA 6FADB2E0) | `D2Helpers.cpp:748` in `D2CLIENT_Interact_ASM` | - |
| `D2CLIENT_ClickParty_I` (`D2Ptrs.h:242`) | `0x00479EB0` | 1.14d | `D2Helpers.cpp:756` in `D2CLIENT_ClickParty_ASM` | - |
| `D2CLIENT_ClickParty_II` (`D2Ptrs.h:243`) | `0x0049B990` | 1.14d | `D2Helpers.cpp:951` in `D2CLIENT_HostilePartyUnit` | - |
| `D2CLIENT_ShopAction_I` (`D2Ptrs.h:245`) | `0x0047D030` | stale (1.13 VA 6FB2D030) | `D2Helpers.cpp:779` in `D2CLIENT_ShopAction_ASM` | - |
| `D2CLIENT_GetUnitName_I` (`D2Ptrs.h:247`) | `0x00464A60` | 1.14d | `D2Helpers.cpp:716` in `D2CLIENT_GetUnitName_STUB` | - |
| `D2CLIENT_GetItemDesc_I` (`D2Ptrs.h:248`) | `0x0042E380` | stale (1.13 VA 6FADE380) | `D2Helpers.cpp:827` in `D2CLIENT_GetItemDesc_ASM` | - |
| `D2CLIENT_AssignPlayer_I` (`D2Ptrs.h:250`) | `0x00466200` | 1.14d | `D2Intercepts.cpp:168` in `PlayerAssignment_Intercept` | - |
| `D2CLIENT_InputCall_I` (`D2Ptrs.h:254`) | `0x004787B0` | 1.14d | `D2Intercepts.cpp:83` in `GameInput_Intercept` | - |
| `D2CLIENT_Say_I` (`D2Ptrs.h:256`) | `0x0047CBDA` | 1.14d | `Core.cpp:81` in `Say_ASM` | - |
| `D2CLIENT_BodyClickTable` (`D2Ptrs.h:258`) | `0x00721E58` | 1.14d | **none** | `JSGame.cpp:417`, `JSGame.cpp:432`, `JSGame.cpp:546` |
| `D2CLIENT_LoadUIImage_I` (`D2Ptrs.h:260`) | `0x004788B0` | 1.14d | **none** | - |
| `D2CLIENT_GetMinionCount_I` (`D2Ptrs.h:262`) | `0x00478EE0` | 1.14d | `D2Helpers.cpp:937` in `D2CLIENT_GetMinionCount` | - |
| `D2CLIENT_GameLeave_I` (`D2Ptrs.h:264`) | `0x00481830` | 1.14d | `D2Intercepts.cpp:227` in `GameLeave_Intercept` | - |
| `D2CLIENT_CongratsScreen_I` (`D2Ptrs.h:266`) | `0x004F6190` | 1.14d | `D2Intercepts.cpp:193` in `CongratsScreen_Intercept` | - |
| `D2CLIENT_GameAddUnit_I` (`D2Ptrs.h:273`) | `0x004628E0` | stale (1.13 VA 6FB128E0) | `D2Intercepts.cpp:252` in `AddUnit_Intercept` | - |
| `D2CLIENT_SendGamePacket_I` (`D2Ptrs.h:283`) | `0x00478350` | 1.14d | `D2Helpers.cpp:961` in `D2CLIENT_SendGamePacket_ASM` | - |
| `D2CLIENT_SendPacket_II` (`D2Ptrs.h:284`) | `0x0052AE62` | 1.14d | `D2Intercepts.cpp:67` in `GamePacketSent_Interception` | - |
| `D2COMMON_DisplayOverheadMsg_I` (`D2Ptrs.h:355`) | `0x006611A0` | 1.14d | `D2Helpers.cpp:841` in `D2COMMON_DisplayOverheadMsg_ASM` | - |
| `D2COMMON_GetLevelIdFromRoom_I` (`D2Ptrs.h:356`) | `0x0061A1B0` | 1.14d | **none** | - |
| `D2MULTI_ChannelChat_I` (`D2Ptrs.h:403`) | `0x00414BE6` | no comment | **none** | - |
| `D2MULTI_ChannelEmote_I` (`D2Ptrs.h:403`) | `0x00414856` | no comment | **none** | - |
| `D2MULTI_ChannelWhisper_I` (`D2Ptrs.h:403`) | `0x004142F0` | no comment | **none** | - |
| `D2MULTI_ChannelInput_I` (`D2Ptrs.h:404`) | `0x004428D0` | 1.14d | `D2Intercepts.cpp:242` in `ChannelInput_Intercept` | - |
| `D2LANG_Say_II` (`D2Ptrs.h:424`) | `0x00526800` | 1.14d | **none** | - |
| `BNCLIENT_DClass` (`D2Ptrs.h:466`) | `0x00523673` | 1.14d | `D2Intercepts.cpp:277` in `ClassicSTUB` | - |
| `BNCLIENT_DLod` (`D2Ptrs.h:467`) | `0x0052395D` | 1.14d | `D2Intercepts.cpp:285` in `LodSTUB` | - |

`D2CLIENT_BodyClickTable` is a data table, read from C++ ([README.md §6](README.md#asmptr--raw-address-for-inline-asm)).

## 9. Problems found

| Problem | Where | Impact |
|---|---|---|
| `D2CLIENT_ClickBeltRight` argument order differs between call sites: `(pInventory, pPlayer, ...)` at `JSGame.cpp:539` vs `(pPlayer, pInventory, ...)` at `JSGame.cpp:648` and the next line | macro `D2Ptrs.h:502` → `ECX`/`EDX` | one of the two `clickItem()` belt paths passes player and inventory swapped to `ClickBeltRight_I`; which one is right needs the binary |
| Stale 1.13 targets | `D2CLIENT_Interact_I` `D2Ptrs.h:240`, `D2CLIENT_ShopAction_I` `D2Ptrs.h:245`, `D2CLIENT_GetItemDesc_I` `D2Ptrs.h:248`, `D2CLIENT_GameAddUnit_I` `D2Ptrs.h:273` | none today (no live callers); re-enabling `D2CLIENT_Interact()` (`D2Helpers.cpp:398`, its only caller commented out at `JSUnit.cpp:882`) would jump into unrelated 1.14d code |
| Returns to address 0 | `D2CLIENT_PlaySound` `D2Helpers.cpp:856-870` | any call crashes; `playSound()` has the call commented out (`JSGame.cpp:1038`) |
| Callee-saved registers clobbered | `ESI` in `D2CLIENT_Interact_ASM`, `D2COMMON_DisplayOverheadMsg_ASM`; `ESI`/`EDI` in `D2CLIENT_ClickShopItem_ASM`; `EBX` in `D2CLIENT_PlaySound` | all unused; any revival must save/restore them |
| Prototype/stub mismatch | `D2CLIENT_LeftClickItem_I` (7 stack params declared, 6 + `EAX` used); header vs definition parameter names of `ShopAction_ASM`, `ClickItemRight_ASM` | documentation hazard only |
| Declared but undefined | `D2CLIENT_LoadUIImage_ASM` (two declarations) | link error if used |
| Mid-function entry with hand-built frames | `Say_ASM`, `D2CLIENT_TakeWaypoint` | break silently if the game function's frame differs (another build, or a wrong 1.14d offset) |
| No game-loop lock | `clickMap()`, `clickParty()`, `say()`, `useStatPoint()`, `useSkillPoint()`, `unit.interact()`, `unit.setSkill()`, `unit.getMinionCount()`, ... ([§7](#7-thread-and-lock-context)) | game code runs on a script thread concurrently with the game thread |

## 10. Open questions

- Stack cleanup of every target (`ret` vs `ret N` in [§5](#5-register-and-stack-contracts)) is
  inferred from what keeps each stub balanced; confirm in Ghidra.
- `D2CLIENT_ClickBeltRight_I`: which register gets the player and which the inventory.
- `Say_I` / `TakeWaypoint_I`: do the containing functions really use a `0x110`-byte frame / the
  `EBX=1, EDI=0, ESI=struct, ECX pushed` state, and does `TakeWaypoint_I`'s function rely on `EBP`
  (the stub leaves it pointing at its own frame)?
- `D2CLIENT_GetUnitName_I` / `GetUiVar_I` / `SetSelectedUnit_I`: are `ECX` and/or `EAX` the real
  inputs (the stubs set both in some cases)?
- Is `D2CLIENT_SendGamePacket_I` the same send path as `D2NET_SendPacket`, i.e. do packets sent
  through `useStatPoint()`/`useSkillPoint()`/`unit.setSkill()` also raise `gamepacketsent`?

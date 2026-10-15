# Patches and hooks (Game.exe 1.14d)

Scope: every byte D2BS writes into Game.exe code, and every way game execution is diverted into
D2BS. That covers the patch engine in `Offset.cpp`, the `Patches[]` / `Conditional[]` tables in
`Patch.h`, each intercept in `D2Intercepts.cpp` with its register/stack contract, the C++ handlers
those intercepts call (`D2Handlers.cpp`, `D2NetHandlers.cpp`, `Events.cpp`) and what they return,
the command-line flags that turn on the conditional patches, and the Win32 hooks (window
procedure, timer, keyboard/mouse hooks) that complement them. Everything is derived from the C++
source and cited as `File:line`. Nothing was checked against a Game.exe binary. Rows about the
*original* game instructions are **inferences** from what each intercept re-executes; they are
marked as such and come with the bytes to look for in Ghidra. Addresses: VA = `0x400000` + RVA,
because `GetDllOffset()` ignores the DLL name and adds the offset to `GetModuleHandle(NULL)`
(`Offset.cpp:21-27`).
Related: [README.md](README.md) (address model), [offsets.md](offsets.md) (symbol tables and
staleness flags), [call-stubs.md](call-stubs.md) (asm wrappers D2BS uses to *call* game code),
[structs.md](structs.md), [../architecture.md](../architecture.md) (threads, `Vars`),
[../js-api/events.md](../js-api/events.md) (the JS side of every event named here),
[../ghidra/README.md](../ghidra/README.md) (the import, which labels these sites `D2BS_PATCH_*`).

## Contents

1. [Summary](#1-summary)
2. [The patch engine](#2-the-patch-engine)
3. [Patch table](#3-patch-table)
4. [Displaced instructions and expected original bytes](#4-displaced-instructions-and-expected-original-bytes)
5. [Intercept reference](#5-intercept-reference)
6. [Handlers, events and blocking](#6-handlers-events-and-blocking)
7. [Conditional patches and their flags](#7-conditional-patches-and-their-flags)
8. [Hooks that are not code patches](#8-hooks-that-are-not-code-patches)
9. [Notes for replacing the JS layer with RPC](#9-notes-for-replacing-the-js-layer-with-rpc)
10. [Open questions](#10-open-questions)

## 1. Summary

- 22 `Patches[]` entries, 9 `Conditional[]` entries, 6 commented-out entries (`Patch.h`). `Patches[]` is always installed; each `Conditional[]` entry is
  installed only when its `BOOL*` flag is `TRUE` (`Offset.cpp:55`).
- Three patch forms: `CALL rel32` or `JMP rel32` to a D2BS function, NOP-padded to the entry
  length, and `PatchBytes`, which fills the entry with one repeated byte (`Offset.cpp:92-112`).
- Everything is installed once, from `DllMain` → `Startup()` (`D2BS.cpp:133`,
  `D2BS.cpp:134`), before any script runs. `Shutdown()` restores only
  `Patches[]` (`D2BS.cpp:153`). `RemoveConditional()` is defined
  (`Offset.cpp:64`) but never called.
- The engine does not suspend other threads, and it switches each patched page to
  `PAGE_READWRITE` (non-executable) while writing (`Offset.cpp:76`). See [§2.5](#25-thread-safety-and-failure-modes).
- **Bug, installed unconditionally**: the `Fog.dll 0x82E0` JMP targets `0x00576F06`, not
  `D2GAME_exit0` (`0x0040576F`), because `Patches[]` copies the D2Ptrs global before
  `DefineOffsets()` decodes it ([§2.6](#26-the-d2game_exit0-static-initialisation-bug)).
- **Dead flag**: `-ftj` is tested in `DllMain` (`D2BS.cpp:65`) but is not
  in the `CLine[]` table that `ParseCommandLine()` matches (`CommandLine.cpp:30`),
  so `Vars.bReduceFTJ` is never set and the FTJ-reducer patch is never installed ([§7](#7-conditional-patches-and-their-flags)).
- **Unverified site, installed unconditionally**: `RealmPacketRecv_Interception` at VA `0x0044B1AE`
  (`Patch.h:39`) has no 1.14d marker and uses the module string
  `"D2MCPClient.dll"`. If the offset is stale, D2BS overwrites 6 bytes of unrelated code at
  injection. Check for `85 F6 74 02 FF D6` there ([§4](#4-displaced-instructions-and-expected-original-bytes)).
- Data flow for the RPC rewrite: packet in/out, chat input, chat/whisper receipt, player
  assignment and realm packets enter D2BS through these intercepts and leave as JS events
  ([§6](#6-handlers-events-and-blocking)). Drawing (`GameDraw`) and the timer double as the
  *game-loop lock* that lets script threads call game code safely ([§8](#8-hooks-that-are-not-code-patches)).

## 2. The patch engine

### 2.1 Data structure

```cpp
typedef struct PatchHook_t {                 // Offset.h
    void (*pFunc)(DWORD, DWORD, DWORD);      // PatchCall / PatchJmp / PatchBytes
    DWORD dwAddr;                            // absolute VA of the patch site
    DWORD dwFunc;                            // target address (CALL/JMP) or fill value (BYTES)
    DWORD dwLen;                             // bytes overwritten
    BOOL* enabled;                           // Conditional[] only; NULL in Patches[]
    BYTE* bOldCode;                          // saved original bytes, heap-allocated at install
} PatchHook;
```

Declared at `Offset.h:10-17`. `Patches[]` initialisers
have four fields, so `enabled` and `bOldCode` start as `NULL`
(`Patch.h:8`). `Patch.h` is included only by `Offset.cpp`
(`Offset.cpp:7`); the arrays are defined there.

`dwAddr` is computed by `GetDllOffset("<dll>", RVA)` **during C++ dynamic initialisation of
D2BS.dll**, i.e. before `DllMain` runs. That is safe for `dwAddr` (Game.exe is already mapped
and `GetModuleHandle(NULL)` is its base), but not for `dwFunc` values read from `D2Ptrs.h`
globals ([§2.6](#26-the-d2game_exit0-static-initialisation-bug)).

### 2.2 Life cycle

| Step | Code | What happens |
|---|---|---|
| Static init | `Patch.h:8`, `Patch.h:47` | `dwAddr` = `GetModuleHandle(NULL)` + RVA; `dwFunc` = address of the D2BS handler (or the `D2Ptrs.h` global's *current* value) |
| Flags | `D2BS.cpp:45-78` | `DllMain` parses the command line and sets `Vars.bSleepy`, `bCacheFix`, `bMulti`, `bReduceFTJ`, `bUseRawCDKey`, `szTitle`, `szClassic`, `szLod` |
| `Startup()` | `D2BS.cpp:108` | initialises all critical sections (including `cGameLoopSection`, `D2BS.cpp:121`), `Genhook::Initialize()`, then `DefineOffsets()` (`D2BS.cpp:132`) |
| `InstallPatches()` | `Offset.cpp:38-44` | for every entry: `bOldCode = new BYTE[dwLen]`, `ReadProcessMemory(self, dwAddr, bOldCode, dwLen)`, then `pFunc(dwAddr, dwFunc, dwLen)` |
| `InstallConditional()` | `Offset.cpp:53-62` | same, but skips entries whose `enabled` is `NULL` or `*enabled != TRUE` |
| `D2Thread` starts | `D2BS.cpp:137` | after the patches; hooks can fire before the script engine exists (they cope: `ForEachScript` returns `false` with no scripts, `ScriptEngine.cpp:205`) |
| `Shutdown()` | `D2BS.cpp:143` | `bActive = FALSE`, waits for `D2Thread` (unless called from `DllMain`), restores the WNDPROC, then `RemovePatches()` (`Offset.cpp:46-51`): `WriteBytes(dwAddr, bOldCode, dwLen)` and `delete[] bOldCode` for every `Patches[]` entry |
| never | `Offset.cpp:64-71` | would restore the conditional patches; no caller anywhere |

`Shutdown()` is reached from `DLL_PROCESS_DETACH` (`D2BS.cpp:100`) and from the JS
native `quitGame()` (`JSGame.cpp:1015`), which then calls
`TerminateProcess`. Because conditional patches stay in place, unloading D2BS.dll with `-multi`,
`-cachefix` or `-d2c` active leaves `CALL`/`JMP`s into freed memory.

`FillBytes()` (`Offset.cpp:83`) and `RetrievePatchHooks()` (`Offset.cpp:121`) have
no callers.

### 2.3 Exact bytes written

```cpp
void InterceptLocalCode(BYTE bInst, DWORD pAddr, DWORD pFunc, DWORD dwLen) {   // Offset.cpp
    BYTE* bCode = new BYTE[dwLen];
    ::memset(bCode, 0x90, dwLen);              // NOP fill
    DWORD dwFunc = pFunc - (pAddr + 5);        // rel32 relative to the end of a 5-byte insn
    bCode[0] = bInst;                          // 0xE8 (PatchCall) or 0xE9 (PatchJmp)
    *(DWORD*)&bCode[1] = dwFunc;
    WriteBytes((void*)pAddr, bCode, dwLen);
    delete[] bCode;
}
```

| Form | Function | Bytes at `dwAddr` | Return address pushed |
|---|---|---|---|
| CALL | `PatchCall` `Offset.cpp:104` → `InterceptLocalCode(INST_CALL, ...)` | `E8 r32` + `90` × (`dwLen` − 5) | `dwAddr + 5`, i.e. the first NOP (or the next instruction when `dwLen` = 5) |
| JMP | `PatchJmp` `Offset.cpp:108` → `InterceptLocalCode(INST_JMP, ...)` | `E9 r32` + `90` × (`dwLen` − 5) | none |
| BYTES | `PatchBytes` `Offset.cpp:112` | `(BYTE)dwFunc` × `dwLen` (`memset`) | - |

`r32` = little-endian `dwFunc − (dwAddr + 5)`. `INST_CALL`/`INST_JMP` are `0xE8`/`0xE9`
(`Offset.h:5`, `Offset.h:7`). `PatchBytes` uses only the
low byte of `dwFunc`, so `(WORD)0x9090` with length 2 writes `90 90` and `(DWORD)0xc3` writes
`C3`. With a `CALL` patch the intercept returns to `dwAddr + 5`; the NOP padding then slides
execution to `dwAddr + dwLen`. No CALL intercept resumes anywhere else: two of them pop the
return address into a register and jump back to it instead of returning, because they rebuild the
stack underneath it (`GameActChange_Intercept` via `EAX`, `Whisper_Intercept` via `EDI`), and
`GameLeave_Intercept` lets the game function it tail-jumps to return there. A JMP patch pushes
nothing; its intercept jumps to a label inside the patched function (`GamePacketSent_Interception`
→ `D2CLIENT_SendPacket_II`, `ClassicSTUB` → `BNCLIENT_DClass`, `LodSTUB` → `BNCLIENT_DLod`),
returns to the enclosing function's caller (`GameDraw_Intercept`, `PlayerAssignment_Intercept`,
`GameActChange2_Intercept`), never returns (`ErrorReportLaunch`), or, for the `D2GAME_exit0` entry,
is a jump to a game address ([§2.6](#26-the-d2game_exit0-static-initialisation-bug)).
D2BS.dll handler addresses are only known at run time, so the table in [§3](#3-patch-table)
shows `r32` symbolically.

### 2.4 Saved bytes and memory protection

- Original bytes are read with `ReadProcessMemory(GetCurrentProcess(), ...)` into a fresh
  `new BYTE[dwLen]` (`Offset.cpp:41`). Its return value is
  ignored; so is every `WriteBytes()` result.
- `WriteBytes()` (`Offset.cpp:73-81`): `VirtualProtect(pAddr, dwLen, PAGE_READWRITE, &dwOld)`,
  `memcpy`, then `VirtualProtect(pAddr, dwLen, dwOld, &dwOld)`. `VirtualProtect` works on whole
  pages, so for the duration of the copy the entire 4 KiB page(s) holding the site are
  read/write and **not executable**.
- No `FlushInstructionCache()` call. (x86 keeps instruction fetch coherent with same-process
  stores, so this matters less than the missing thread synchronisation.)
- Removal writes back exactly the saved bytes without checking that the site still holds D2BS's
  patch.

### 2.5 Thread safety and failure modes

- `InstallPatches()`/`InstallConditional()` run inside `DllMain(DLL_PROCESS_ATTACH)` (loader lock
  held). Game threads are **not** suspended. A game thread that executes a page while it is
  `PAGE_READWRITE` faults if DEP is enforced for Game.exe (whether it is depends on the binary's
  NX flag and the system policy; not determinable from source). A thread executing the 5–10
  patched bytes mid-`memcpy` sees a torn instruction.
- `RemovePatches()` runs after `D2Thread` has exited, but the game's own threads may be inside an
  intercept at that moment. Restoring the bytes is harmless for them; unloading the DLL right
  afterwards is not.
- Nothing serialises install/remove against each other; both run on one thread in practice.
- The intercepts themselves run on whichever game thread hits the site: presumably the game's
  main (window) thread for the drawing and input hooks, and whatever thread the game processes
  packets on for the network hooks (neither is determinable from source). The C++ handlers they call take D2BS
  locks (script list, `Vars.cEventSection`, ...) and may block for up to 500 ms or 1000 ms
  waiting for scripts ([§6.2](#62-blocking-and-timeouts)).

### 2.6 The `D2GAME_exit0` static-initialisation bug

`{PatchJmp, GetDllOffset("Fog.dll", 0x82E0), (DWORD)D2GAME_exit0, 6}` (`Patch.h:42`)
copies the *variable* `D2GAME_exit0` (`D2Ptrs.h:481`). During static initialisation it
still holds the encoded `DLLOFFSET(D2GAME, 0x576F)` = `6 | 0x576F << 8` = `0x00576F06`;
`DefineOffsets()` rewrites the global later (`D2BS.cpp:132`) but not the copy in
`Patches[20].dwFunc`. Result: `E9 21 EC 16 00 90` at VA `0x004082E0`, a jump to `0x00576F06`
instead of `0x0040576F`. It only matters when the game reaches `0x4082E0` (the comment calls it
"NEW 1.14d"; the commented-out alternative a line below targets `FogException`,
`Patch.h:43`). Fix: resolve the target after `DefineOffsets()`, or use
`GetDllOffset("Game.exe", 0x576F)` in the initialiser. The same analysis is in
[README.md §5.1](README.md#51-static-initialisers-see-encoded-values-bug); no other `Patch.h`
entry reads a `D2Ptrs.h` global.

## 3. Patch table

Generated from `Patch.h` and `D2Ptrs.h`. `P[i]` = `Patches[i]`, `C[i]` = `Conditional[i]`.
"Nearest known symbol" is the closest `FUNCPTR`/`ASMPTR` at or below the site; it is a
navigation aid, not proof that the site lies inside that function. The module string is
ignored at run time ([README.md §2](README.md#2-one-image-legacy-module-names)).

| # | Line | Kind | VA | RVA | Module string | Len | Handler / value | Enabled by | Bytes written | Resumes at | Nearest known symbol (VA &le; site) | Feeds | Source comment |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P[0] | `Patch.h:9` | CALL | `0x0047C89D` | `0x7C89D` | `D2Client.dll` | 5 | `GameInput_Intercept` | always | `E8 r32` | site+5 (intercept `ret`) | `D2CLIENT_LeaveParty` +0x28DD<br>next `D2CLIENT_Say_I` at 0x0047CBDA | `GameInput` &rarr; `chatinput`(+blocker), `.` commands; can block the line | `Updated 1.14d //0047C89D-BASE` |
| P[1] | `Patch.h:10` | JMP | `0x00453B30` | `0x53B30` | `D2Client.dll` | 5 | `GameDraw_Intercept` | always | `E9 r32` | returns to the caller of the patched game function (JMP patch, C `ret`) | `D2CLIENT_GetUiVar_I` +0x260<br>next `D2CLIENT_PerformGoldDialogAction` at 0x00454080 | `GameDraw` &rarr; in-game screenhooks, console, `print()`, screenshots, game-loop lock hand-off | `Updated 1.14d //00453B30-BASE` |
| P[2] | `Patch.h:11` | CALL | `0x0045F802` | `0x5F802` | `D2Client.dll` | 5 | `GamePacketReceived_Intercept` | always | `E8 r32` | site+5, popping the original stack argument (`ret 4`) | `D2GAME_Rand` +0x3492<br>next `D2CLIENT_GameAddUnit_I` at 0x004628E0 | `GamePacketReceived` &rarr; `gamepacket` + per-id handlers (&sect;5.3); can block (length 0) | `Updated 1.14d //0045F802-BASE` |
| P[3] | `Patch.h:12` | JMP | `0x0052AE5A` | `0x12AE5A` | `D2Client.dll` | 5 | `GamePacketSent_Interception` | always | `E9 r32` | `D2CLIENT_SendPacket_II` (0x0052AE62) or the re-created early `retn 0Ch` | `D2NET_SendPacket` +0xA<br>next `D2CLIENT_SendPacket_II` at 0x0052AE62 | `GamePacketSent` &rarr; `gamepacketsent`; can block (length 0) | `Updated 1.14d //0052AE5A-BASE` |
| P[4] | `Patch.h:13` | CALL | `0x00462D72` | `0x62D72` | `D2Client.dll` | 5 | `GetSelectedUnit_Intercept` | always | `E8 r32` | site+5 | `D2CLIENT_ClickMap` +0x72<br>next `D2CLIENT_FindClientSideUnit` at 0x00463990 | click target for `ClickMap()` (`clickMap()`, `unit.interact()`, `unit.move()`) | `Updated 1.14d //00462D72-BASE` |
| P[5] | `Patch.h:14` | JMP | `0x0045E4D5` | `0x5E4D5` | `D2Client.dll` | 5 | `PlayerAssignment_Intercept` | always | `E9 r32` | caller of the enclosing game function | `D2GAME_Rand` +0x2165<br>next `D2CLIENT_GameAddUnit_I` at 0x004628E0 | `GamePlayerAssignment` &rarr; `playerassign` | `Updated 1.14d //0045E4D5-BASE` |
| P[6] | `Patch.h:15` | BYTES | `0x00468770` | `0x68770` | `D2Client.dll` | 1 | `(DWORD)0xc3` | always | `C3` | - | `D2CLIENT_GetCursorItem` +0x6D0<br>next `D2COMMON_GetTargetUnitType` at 0x004773C0 | disables the code at the site (function unknown) | `Updated 1.14d //00468770-BASE` |
| P[7] | `Patch.h:16` | BYTES | `0x0044EBFB` | `0x4EBFB` | `D2CLIENT.DLL` | 1 | `(BYTE)0x75` | always | `75` | - | `D2CLIENT_ExitGame` +0xE9B<br>next `D2CLIENT_DrawRectFrame` at 0x00452E50 | congrats-screen branch (meaning unknown) | `Congrats Screen //0044EBFB-BASE` |
| P[8] | `Patch.h:17` | CALL | `0x0044EBEF` | `0x4EBEF` | `D2Client.dll` | 5 | `CongratsScreen_Intercept` | always | `E8 r32` | site+5 | `D2CLIENT_ExitGame` +0xE8F<br>next `D2CLIENT_DrawRectFrame` at 0x00452E50 | `SetMaxDiff` &rarr; `BnetData.nMaxDiff = 10` | `Updated 1.14d //0044EBEF-BASE` |
| P[9] | `Patch.h:18` | CALL | `0x004547B6` | `0x547B6` | `D2Client.dll` | 5 | `GameActChange_Intercept` | always | `E8 r32` | site+5 via `JMP EAX` (return address popped into EAX) | `D2CLIENT_PerformGoldDialogAction` +0x736<br>next `D2CLIENT_SetUIVar` at 0x00455F20 | reads/clears `Vars.bChangedAct` into the flags | `Updated 1.14d //004547B6-BASE` |
| P[10] | `Patch.h:19` | JMP | `0x004567EB` | `0x567EB` | `D2Client.dll` | 5 | `GameActChange2_Intercept` | always | `E9 r32` | caller of the enclosing game function | `D2CLIENT_SetUIVar` +0x8CB<br>next `D2CLIENT_AddAutomapCell` at 0x00457B00 | sets `Vars.bChangedAct` | `Updated 1.14d //004567EB-BASE` |
| P[11] | `Patch.h:20` | CALL | `0x0044F57C` | `0x4F57C` | `D2Client.dll` | 5 | `GameLeave_Intercept` | always | `E8 r32` | site+5 (GameLeave_I returns there directly) | `D2CLIENT_ExitGame` +0x181C<br>next `D2CLIENT_DrawRectFrame` at 0x00452E50 | `GameLeave` &rarr; stops in-game scripts, clears map cache | `Updated 1.14d //0044F57C-BASE` |
| P[12] | `Patch.h:21` | CALL | `0x00461704` | `0x61704` | `D2Client.dll` | 5 | `GameAttack_Intercept` | always | `E8 r32` | site+5 | `D2GAME_Rand` +0x5394<br>next `D2CLIENT_GameAddUnit_I` at 0x004628E0 | `GameAttack` &rarr; attacks on monsters become shift-attacks | `Updated 1.14d //00461704-BASE` |
| P[13] | `Patch.h:26` | CALL | `0x00521B20` | `0x121B20` | `BNCLIENT.DLL` | 7 | `ChatPacketRecv_Interception` | always | `E8 r32 90 90` | site+5 (2 NOPs) = end of the displaced block | `D2WIN_InitMPQ` +0xA7EE<br>next `BNCLIENT_DecodeAndLoadKeys` at 0x005234D0 | `ChatPacketRecv` &rarr; `chatmsg`, `whispermsg` (never blocks) | `Updated 1.14d //00521B20-BASE` |
| P[14] | `Patch.h:28` | CALL | `0x00448813` | `0x48813` | `D2Multi.dll` | 7 | `Whisper_Intercept` | always | `E8 r32 90 90` | site+5 via `jmp edi` (return address popped into EDI), then 2 NOPs | `D2MULTI_PrintChannelText_` +0xD63<br>next `D2CLIENT_CloseInteract` at 0x0044C6B0 | `WhisperHandler` &rarr; `whispermsg` (never blocks) | `Updated 1.14d //00448813-BASE` |
| P[15] | `Patch.h:29` | CALL | `0x00442A61` | `0x42A61` | `D2Multi.dll` | 5 | `ChannelInput_Intercept` | always | `E8 r32` | site+5 | `D2MULTI_ChannelInput_I` +0x191<br>next `D2MULTI_PrintChannelText_` at 0x00447AB0 | `ChannelInput` &rarr; `chatinput`(+blocker), `.` commands; can block the line | `Updated 1.14d //00442A61-BASE` |
| P[16] | `Patch.h:35` | CALL | `0x004F9A0D` | `0xF9A0D` | `D2Win.dll` | 5 | `GameDrawOOG_Intercept` | always | `E8 r32` | site+5 | `D2WIN_DrawSprites` +0x19D<br>next `D2WIN_TakeScreenshot` at 0x004FA7A0 | `GameDrawOOG` &rarr; out-of-game screenhooks, console, `print()`, screenshots | `Updated 1.14d //004F9A0D-BASE` |
| P[17] | `Patch.h:37` | CALL | `0x006091E5` | `0x2091E5` | `D2CMP.dll` | 10 | `GameCrashFix_Intercept` | always | `E8 r32 90 90 90 90 90` | site+5 (5 NOPs) = end of the displaced block | `D2CMP_DeleteCellFile` +0x7795<br>next `D2COMMON_LoadAct` at 0x006194A0 | NULL guard, no handler | `1.14d //006091E5-BASE` |
| P[18] | `Patch.h:39` | CALL | `0x0044B1AE` | `0x4B1AE` | `D2MCPClient.dll` | 6 | `RealmPacketRecv_Interception` | always | `E8 r32 90` | site+5 (1 NOP) = end of the displaced block | `D2MULTI_PrintChannelText_` +0x36FE<br>next `D2CLIENT_CloseInteract` at 0x0044C6B0 | `RealmPacketRecv` &rarr; `realmpacket`; can block (skips dispatch) | - |
| P[19] | `Patch.h:41` | CALL | `0x00408CC4` | `0x8CC4` | `Fog.dll` | 6 | `LogMessageBoxA_Intercept` | always | `E8 r32 90` | site+5 (1 NOP) | `D2GAME_exit0` +0x3555<br>next `D2MULTI_ChannelWhisper_I` at 0x004142F0 | stack walk + log, then the real `MessageBoxA` | `Updated 1.14d //00408CC4-BASE` |
| P[20] | `Patch.h:42` | JMP | `0x004082E0` | `0x82E0` | `Fog.dll` | 6 | `D2GAME_exit0` | always | `E9 21 EC 16 00 90`<br>**target `0x00576F06`** (encoded `DLLOFFSET` value), not `0x0040576F` | no return to the site (JMP); intended target `D2GAME_exit0` | `D2GAME_exit0` +0x2B71<br>next `D2MULTI_ChannelWhisper_I` at 0x004142F0 | exit path; **wrong target** | `NEW 1.14d //004082E0-BASE` |
| P[21] | `Patch.h:44` | JMP | `0x00401790` | `0x1790` | `Fog.dll` | 6 | `ErrorReportLaunch` | always | `E9 r32 90` | never returns | next `D2GAME_exit0` at 0x0040576F | stack walk + log, `exit(0)` | `NEW 1.14d //00401790-BASE` |
| C[0] | `Patch.h:48` | JMP | `0x0052366C` | `0x12366C` | `BNCLIENT.DLL` | 5 | `ClassicSTUB` | `Vars.bUseRawCDKey` | `E9 r32` | `BNCLIENT_DClass` (0x00523673) | `BNCLIENT_DecodeAndLoadKeys` +0x19C<br>next `BNCLIENT_DClass` at 0x00523673 | classic CD key from `-d2c` | `Updated 1.14d //0052366C-BASE` |
| C[1] | `Patch.h:49` | JMP | `0x00523958` | `0x123958` | `BNCLIENT.DLL` | 5 | `LodSTUB` | `Vars.bUseRawCDKey` | `E9 r32` | `BNCLIENT_DLod` (0x0052395D) | `BNCLIENT_DClass` +0x2E5<br>next `BNCLIENT_DLod` at 0x0052395D | LoD CD key from `-d2x` | `Updated 1.14d //00523958-BASE` |
| C[2] | `Patch.h:50` | CALL | `0x0044EF28` | `0x4EF28` | `D2CLIENT.DLL` | 6 | `FailToJoin` | `Vars.bReduceFTJ` | `E8 r32 90` | site+5 (1 NOP) | `D2CLIENT_ExitGame` +0x11C8<br>next `D2CLIENT_DrawRectFrame` at 0x00452E50 | FTJ timeout 4000 (never installed) | `FTJ Reducer` |
| C[3] | `Patch.h:51` | CALL | `0x004F5623` | `0xF5623` | `D2Gfx.DLL` | 6 | `Multi` | `Vars.bMulti` | `E8 r32 90` | site+5 (1 NOP) | `D2GFX_GetScreenSize` +0x4C3<br>next `D2GFX_GetHwnd` at 0x004F59A0 | allow a second game instance | - |
| C[4] | `Patch.h:52` | CALL | `0x004F5831` | `0xF5831` | `D2Gfx.DLL` | 6 | `Windowname` | `Vars.bMulti` | `E8 r32 90` | site+5 (1 NOP) | `D2GFX_GetScreenSize` +0x6D1<br>next `D2GFX_GetHwnd` at 0x004F59A0 | window title from `-title` | - |
| C[5] | `Patch.h:53` | CALL | `0x0051944E` | `0x11944E` | `BNCLIENT.DLL` | 6 | `CacheFix` | `Vars.bCacheFix` | `E8 r32 90` | site+5 (1 NOP) | `D2WIN_InitMPQ` +0x211C<br>next `BNCLIENT_DecodeAndLoadKeys` at 0x005234D0 | per-instance `bncache` file | - |
| C[6] | `Patch.h:54` | CALL | `0x00519434` | `0x119434` | `BNCLIENT.DLL` | 6 | `CacheFix` | `Vars.bCacheFix` | `E8 r32 90` | site+5 (1 NOP) | `D2WIN_InitMPQ` +0x2102<br>next `BNCLIENT_DecodeAndLoadKeys` at 0x005234D0 | per-instance `bncache` file | - |
| C[7] | `Patch.h:55` | BYTES | `0x00451C31` | `0x51C31` | `D2CLIENT.DLL` | 2 | `(WORD)0x9090` | `Vars.bSleepy` | `90 90` | - | `D2CLIENT_ExitGame` +0x3ED1<br>next `D2CLIENT_DrawRectFrame` at 0x00452E50 | "Sleep" (`-sleepy`) | `Sleep` |
| C[8] | `Patch.h:56` | BYTES | `0x004FA66F` | `0xFA66F` | `D2Win.DLL` | 1 | `(BYTE)0xEB` | `Vars.bSleepy` | `EB` | - | `D2WIN_DrawSprites` +0xDFF<br>next `D2WIN_TakeScreenshot` at 0x004FA7A0 | "OOG Sleep" (`-sleepy`) | `OOG Sleep` |

Commented-out entries (not installed; listed because the handlers still exist or the offsets
are referenced elsewhere):

| Line | Kind | Module string | RVA | 0x400000 + RVA | Len | Handler | Handler defined? |
|---|---|---|---|---|---|---|---|
| `Patch.h:22` | CALL | `D2Client.dll` | `0xA7364` | `0x004A7364` | 5 | `AddUnit_Intercept` | `D2Intercepts.cpp:249` |
| `Patch.h:23` | CALL | `D2Client.dll` | `0xA6F25` | `0x004A6F25` | 9 | `RemoveUnit_Interept` | no (name not defined) |
| `Patch.h:31` | CALL | `D2Multi.dll` | `0x14A9A` | `0x00414A9A` | 5 | `ChannelWhisper_Intercept` | no (name not defined) |
| `Patch.h:32` | JMP | `D2Multi.dll` | `0x14BE0` | `0x00414BE0` | 6 | `ChannelChat_Intercept` | no (name not defined) |
| `Patch.h:33` | JMP | `D2Multi.dll` | `0x14850` | `0x00414850` | 6 | `ChannelEmote_Intercept` | no (name not defined) |
| `Patch.h:43` | JMP | `Fog.dll` | `0x8900` | `0x00408900` | 6 | `FogException` | `D2Intercepts.cpp:405` |

`RemoveUnit_Interept` at `Patch.h:23` is a typo for `RemoveUnit_Intercept`
(`D2Intercepts.cpp:261`); the line would not compile if uncommented. The `0x14BE0` /
`0x14850` sites are 1.13d D2Multi offsets ("1.13d" comments) and match the unused ASMPTRs
`D2MULTI_ChannelChat_I` / `D2MULTI_ChannelEmote_I` minus 6 (`D2Ptrs.h:403`).

## 4. Displaced instructions and expected original bytes

**Inference.** For each site: what the overwritten game instructions most likely were, derived
from what the intercept re-executes, skips or replaces. Byte strings with `rel32` are computed
from `D2Ptrs.h` (`target − (site + 5)`); other encodings are the canonical MSVC forms (an
alternative encoding is listed where one is common). `??` = not determinable from source. To
verify, open the address in an unpatched Game.exe 1.14d.

| # | VA | Patch | Displaced original instruction(s) (inferred) | Expected original bytes | Basis |
|---|---|---|---|---|---|
| P[0] | `0x0047C89D` | CALL 5 | `call D2CLIENT_InputCall_I` | `E8 0E BF FF FF` | re-issued by the intercept with the original registers (`D2Intercepts.cpp:83`) |
| P[1] | `0x00453B30` | JMP 5 | unknown (5 bytes; never re-created) | - | the intercept is a plain C function that calls `GameDraw()` and returns (`D2Intercepts.cpp:71-73`); nothing of the original code is re-executed |
| P[2] | `0x0045F802` | CALL 5 | `call D2NET_ReceivePacket_I` (ecx=packet, edx=length, one stack arg) | `E8 19 C1 0C 00` | the intercept re-pushes `[esp+4]`, calls `D2NET_ReceivePacket_I` and returns with `ret 4` (`D2Intercepts.cpp:37-41`) |
| P[3] | `0x0052AE5A` | JMP 5 | `jnz short 0x0052AE62` / `xor eax,eax` / `pop ebp` / `retn 0Ch` (8 bytes, first 5 overwritten) | `75 06 33 C0 5D C2 0C 00` | the intercept re-creates exactly this sequence after `popf` (`D2Intercepts.cpp:61-67`); the resume label `D2CLIENT_SendPacket_II` is site+8, and 2+2+1+3 = 8 bytes gives the computed rel8 0x6 |
| P[4] | `0x00462D72` | CALL 5 | `call D2CLIENT_GetSelectedUnit` | `E8 99 4C 00 00` | the intercept falls back to `D2CLIENT_GetSelectedUnit()` (`D2Intercepts.cpp:103`) and has its signature |
| P[5] | `0x0045E4D5` | JMP 5 | `jmp D2CLIENT_AssignPlayer_I` (tail call), or `call D2CLIENT_AssignPlayer_I` followed by a plain `ret` | `E9 26 7D 00 00` (tail jump) or `E8 26 7D 00 00` (call) | the intercept calls `D2CLIENT_AssignPlayer_I` and then leaves the enclosing function with `RETN` (`D2Intercepts.cpp:168-171`) |
| P[6] | `0x00468770` | BYTES 1 | 1 byte (not recorded) | - | `PatchBytes` writes `C3` (`ret`); 0x468770 is 16-byte aligned, which is consistent with (not proof of) a function entry |
| P[7] | `0x0044EBFB` | BYTES 1 | 1 byte (not recorded) | - | `0x75` is the `JNZ rel8` opcode if the byte is an opcode; it sits 0x7 bytes after the CongratsScreen call's return address |
| P[8] | `0x0044EBEF` | CALL 5 | `call D2CLIENT_CongratsScreen_I` | `E8 9C 75 0A 00` | re-issued first thing in the intercept (`D2Intercepts.cpp:193`) |
| P[9] | `0x004547B6` | CALL 5 | `push esi` / `xor esi,esi` + one 2-byte instruction that is not re-created | `56 33 F6 ?? ??` or `56 31 F6 ?? ??` | the intercept re-creates `PUSH ESI` / `XOR ESI, ESI` and substitutes `CMP [Vars.bChangedAct], 0` for the flags (`D2Intercepts.cpp:204-209`) |
| P[10] | `0x004567EB` | JMP 5 | `mov esp,ebp` / `pop ebp` / `ret` (4 bytes) + 1 byte at 0x004567EF | `8B E5 5D C3 ??` or `89 EC 5D C3 ??` | the intercept is that epilogue plus `MOV [Vars.bChangedAct], 1` (`D2Intercepts.cpp:213-221`); the 5th byte is the last byte before the 16-byte boundary 0x004567F0, consistent with inter-function padding |
| P[11] | `0x0044F57C` | CALL 5 | `call D2CLIENT_GameLeave_I` | `E8 AF 22 03 00` | the intercept tail-jumps to `D2CLIENT_GameLeave_I` after `GameLeave()` (`D2Intercepts.cpp:226-227`) |
| P[12] | `0x00461704` | CALL 5 | `mov eax, [0x007A6AAC]` (`D2CLIENT_MouseY`) | `A1 AC 6A 7A 00` | re-created at `OldCode:` as a load through `p_D2CLIENT_MouseY` (`D2Intercepts.cpp:158-160`); `A1 moffs32` is the 5-byte form |
| P[13] | `0x00521B20` | CALL 7 | `mov edx,[ebp+8]` / `mov ecx,ebx` / `call edi` (7 bytes) | `8B 55 08 8B CB FF D7` | the first two instructions run before `pushad` and survive it; `call edi` is re-issued unless blocked (`D2Intercepts.cpp:124-135`) |
| P[14] | `0x00448813` | CALL 7 | `sub esp, 674h` / `push edi` (7 bytes) | `81 EC 74 06 00 00 57` | after the intercept ESP = ESP_site - 0x678 and `[ESP]` = original EDI, i.e. the state `sub esp,674h; push edi` leaves (`D2Intercepts.cpp:109-111`) |
| P[15] | `0x00442A61` | CALL 5 | `call D2MULTI_ChannelInput_I` | `E8 6A FE FF FF` | re-issued unless blocked (`D2Intercepts.cpp:242`) |
| P[16] | `0x004F9A0D` | CALL 5 | `call D2WIN_DrawSprites` | `E8 5E FE FF FF` | `GameDrawOOG()` calls `D2WIN_DrawSprites()` as its first statement (`D2Handlers.cpp:422`) |
| P[17] | `0x006091E5` | CALL 10 | `mov [ecx+10h], edx` / `mov dword ptr [eax+0Ch], 0` (10 bytes) | `89 51 10 C7 40 0C 00 00 00 00` | the intercept is exactly these two stores with a NULL check on ECX in front of the first (`D2Intercepts.cpp:175-184`) |
| P[18] | `0x0044B1AE` | CALL 6 | `test esi,esi` / `jz short +2` / `call esi` (6 bytes) | `85 F6 74 02 FF D6` | the intercept starts with `test esi, esi; jz` and ends with a conditional `call esi` (`D2Intercepts.cpp:7-22`); the `jz` target is assumed to be the instruction after `call esi` |
| P[19] | `0x00408CC4` | CALL 6 | `call dword ptr [__imp_MessageBoxA]` (6 bytes) | `FF 15 <IAT slot>` | the replacement has MessageBoxA's exact `WINAPI` signature and forwards to it (`D2Intercepts.cpp:374-380`); a 6-byte call is the `FF 15 disp32` form |
| P[20] | `0x004082E0` | JMP 6 | unknown (6 bytes) | - | JMP patch; see the static-initialisation bug below |
| P[21] | `0x00401790` | JMP 6 | unknown (6 bytes; function entry assumed) | - | the replacement has a full C signature (`char __fastcall (const char*, int)`, `D2Intercepts.cpp:416`) and calls `exit(0)` |
| C[0] | `0x0052366C` | JMP 5 | 7 bytes [0x0052366C, 0x00523673) skipped; content unknown | - | the stub resumes at `BNCLIENT_DClass` = site+7 (`D2Intercepts.cpp:277`) |
| C[1] | `0x00523958` | JMP 5 | 5 bytes [0x00523958, 0x0052395D) skipped; content unknown | - | the stub resumes at `BNCLIENT_DLod` = site+5 (`D2Intercepts.cpp:285`) |
| C[2] | `0x0044EF28` | CALL 6 | `cmp esi, imm32` (6 bytes) | `81 FE ?? ?? ?? ??` | the stub is `cmp esi, 4000; ret` and the flags survive `ret` (`D2Intercepts.cpp:289-295`) |
| C[3] | `0x004F5623` | CALL 6 | `call dword ptr [__imp_FindWindowA]` (6 bytes) | `FF 15 <IAT slot>` | the replacement takes `(LPSTR Class, LPSTR Window)` `__stdcall`, FindWindowA's shape (`D2Intercepts.cpp:326`) |
| C[4] | `0x004F5831` | CALL 6 | `call dword ptr [__imp_CreateWindowExA]` (6 bytes) | `FF 15 <IAT slot>` | the replacement takes CreateWindowExA's 12 parameters `__stdcall` (`D2Intercepts.cpp:330`) |
| C[5] | `0x0051944E` | CALL 6 | `call dword ptr [__imp_CreateFileA]` (6 bytes) | `FF 15 <IAT slot>` | the replacement takes CreateFileA's 7 parameters `__stdcall` and returns its result (`D2Intercepts.cpp:345`) |
| C[6] | `0x00519434` | CALL 6 | `call dword ptr [__imp_CreateFileA]` (6 bytes) | `FF 15 <IAT slot>` | the replacement takes CreateFileA's 7 parameters `__stdcall` and returns its result (`D2Intercepts.cpp:345`) |
| C[7] | `0x00451C31` | BYTES 2 | 2 bytes (not recorded) | - | NOP-ing exactly 2 bytes is consistent with removing a short `Jcc`/`JMP rel8` |
| C[8] | `0x004FA66F` | BYTES 1 | 1 byte (not recorded) | - | `EB` is `JMP rel8`; consistent with turning a short `Jcc` (`7x rel8`) into an unconditional jump |

## 5. Intercept reference

All functions defined in `D2Intercepts.cpp` (generated index), then one entry per function.
Conventions used below: *site* = patch VA; `ESP_site` = `ESP` just before the patched instruction
executed; a CALL patch enters the intercept with `[ESP]` = site + 5. MSVC inline-asm semantics
that matter here: a C variable used as an operand is a memory operand, so `call D2CLIENT_X_I`
assembles to `call dword ptr [D2CLIENT_X_I]` (indirect through the resolved address, see
[README.md §6](README.md#asmptr--raw-address-for-inline-asm)); `pushad`/`popad` save and restore
EAX..EDI (32 bytes) but not flags; un-annotated C functions are `__cdecl`
(`<CallingConvention>Cdecl</CallingConvention>` at `D2BS.vcxproj:101`;
the Release configurations use the compiler default, also `__cdecl`) and preserve
EBX/ESI/EDI/EBP while clobbering EAX/ECX/EDX and flags.

| Function | Lines | Form | Installed by | Calls (D2BS C++) | Game symbols used |
|---|---|---|---|---|---|
| `RealmPacketRecv_Interception` | `D2Intercepts.cpp:7-22` | naked asm | `Patch.h:39` (always) | `RealmPacketRecv` | - |
| `GamePacketReceived_Intercept` | `D2Intercepts.cpp:24-43` | naked asm | `Patch.h:11` (always) | `GamePacketReceived` | `D2NET_ReceivePacket_I` |
| `GamePacketSent_Interception` | `D2Intercepts.cpp:45-69` | naked asm | `Patch.h:12` (always) | `GamePacketSent` | `D2CLIENT_SendPacket_II` |
| `GameDraw_Intercept` | `D2Intercepts.cpp:71-73` | C | `Patch.h:10` (always) | `GameDraw` | - |
| `GameInput_Intercept` | `D2Intercepts.cpp:75-90` | naked asm | `Patch.h:9` (always) | `GameInput` | `D2CLIENT_InputCall_I` |
| `GetSelectedUnit_Intercept` | `D2Intercepts.cpp:92-104` | C | `Patch.h:13` (always) | `D2CLIENT_FindUnit` | `D2CLIENT_GetSelectedUnit` |
| `Whisper_Intercept` | `D2Intercepts.cpp:106-120` | naked asm | `Patch.h:28` (always) | `WhisperHandler` | - |
| `ChatPacketRecv_Interception` | `D2Intercepts.cpp:122-139` | naked asm | `Patch.h:26` (always) | `ChatPacketRecv` | - |
| `GameAttack_Intercept` | `D2Intercepts.cpp:141-162` | naked asm | `Patch.h:21` (always) | `GameAttack` | `D2CLIENT_GetSelectedUnit`, `p_D2CLIENT_MouseY` |
| `PlayerAssignment_Intercept` | `D2Intercepts.cpp:164-173` | naked asm | `Patch.h:14` (always) | `GamePlayerAssignment` | `D2CLIENT_AssignPlayer_I` |
| `GameCrashFix_Intercept` | `D2Intercepts.cpp:175-184` | naked asm | `Patch.h:37` (always) | - | - |
| `GameDrawOOG_Intercept` | `D2Intercepts.cpp:186-188` | C | `Patch.h:35` (always) | `GameDrawOOG` | - |
| `CongratsScreen_Intercept` | `D2Intercepts.cpp:190-199` | naked asm | `Patch.h:17` (always) | `SetMaxDiff` | `D2CLIENT_CongratsScreen_I` |
| `GameActChange_Intercept` | `D2Intercepts.cpp:201-211` | naked asm | `Patch.h:18` (always) | - | - |
| `GameActChange2_Intercept` | `D2Intercepts.cpp:213-221` | naked asm | `Patch.h:19` (always) | - | - |
| `GameLeave_Intercept` | `D2Intercepts.cpp:223-229` | naked asm | `Patch.h:20` (always) | `GameLeave` | `D2CLIENT_GameLeave_I` |
| `ChannelInput_Intercept` | `D2Intercepts.cpp:231-247` | naked asm | `Patch.h:29` (always) | `ChannelInput` | `D2MULTI_ChannelInput_I` |
| `AddUnit_Intercept` | `D2Intercepts.cpp:249-259` | naked asm | `Patch.h:22` (commented out) | `AddUnit` | `D2CLIENT_GameAddUnit_I` |
| `RemoveUnit_Intercept` | `D2Intercepts.cpp:261-271` | naked asm | nothing (unreferenced) | `RemoveUnit` | - |
| `ClassicSTUB` | `D2Intercepts.cpp:273-279` | naked asm | `Patch.h:48` (Vars.bUseRawCDKey) | - | `BNCLIENT_DClass`, `p_BNCLIENT_ClassicKey` |
| `LodSTUB` | `D2Intercepts.cpp:281-287` | naked asm | `Patch.h:49` (Vars.bUseRawCDKey) | - | `BNCLIENT_DLod`, `p_BNCLIENT_XPacKey` |
| `FailToJoin` | `D2Intercepts.cpp:289-295` | naked asm | `Patch.h:50` (Vars.bReduceFTJ) | - | - |
| `EraseCacheFiles` | `D2Intercepts.cpp:297-324` | C | helper of `CacheFix` | - | - |
| `Multi` | `D2Intercepts.cpp:326-328` | C | `Patch.h:51` (Vars.bMulti) | - | - |
| `Windowname` | `D2Intercepts.cpp:330-343` | C | `Patch.h:52` (Vars.bMulti) | `AnsiToUnicode` | - |
| `CacheFix` | `D2Intercepts.cpp:345-369` | C | `Patch.h:53` (Vars.bCacheFix)<br>`Patch.h:54` (Vars.bCacheFix) | `EraseCacheFiles` | `D2GFX_GetHwnd` |
| `LogMessageBoxA_Intercept` | `D2Intercepts.cpp:374-380` | C | `Patch.h:41` (always) | `DllLoadAddrStrs`, `GetStackWalk`, `Log` | - |
| `MyUnhandledExceptionFilter` | `D2Intercepts.cpp:383-402` | C | nothing (unreferenced) | - | - |
| `FogException` | `D2Intercepts.cpp:405-414` | C | `Patch.h:43` (commented out) | - | - |
| `ErrorReportLaunch` | `D2Intercepts.cpp:416-420` | C | `Patch.h:44` (always) | `GetStackWalk`, `Log` | - |

### 5.1 `GameInput_Intercept` — in-game chat line

- Patch: CALL 5 at `0x0047C89D` (`Patch.h:9`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `call D2CLIENT_InputCall_I` (ASMPTR, RVA `0x787B0`, VA `0x004787B0`, `D2Ptrs.h:254`).
- Entry state: `EBX` = `wchar_t*` line typed into the in-game chat box (the intercept passes
  `EBX` as the `__fastcall` argument, `D2Intercepts.cpp:78`).
- Body (`D2Intercepts.cpp:75-90`): `pushad`; `ECX = EBX`; `call GameInput`; `cmp eax, -1`;
  `popad` (flags survive `popad`); if equal → `xor eax, eax; ret` (blocked); else
  `call D2CLIENT_InputCall_I` with every original register restored, then `ret` to site + 5
  with the game function's `EAX`.
- Stack note: the re-issued call runs one return address deeper than the original, so
  `InputCall_I` must take no stack arguments (inference: the intercept does not copy any).
- Handler: `DWORD __fastcall GameInput(wchar_t* wMsg)` (`D2Handlers.cpp:121`). If
  `Vars.bDontCatchNextMsg` is set (D2BS's own `say()` sets it, `Core.cpp:93`)
  it clears the flag and lets the line through. Otherwise the line is blocked when it starts
  with `.` and `ProcessCommand(wMsg + 1, false)` (`Helpers.cpp:252`) handles it, or when any
  script's `chatinputblocker` listener returns `true` (`ChatInputEvent`, `Events.cpp:218`).
  Returns `-1` = block, `0` = send (`D2Handlers.cpp:130`).
- Feeds: `chatinput` / `chatinputblocker` events; D2BS console commands typed with a leading `.`.

### 5.2 `GameDraw_Intercept` — in-game frame

- Patch: **JMP** 5 at `0x00453B30` (`Patch.h:10`). Nothing of the
  original code is re-executed; `GameDraw_Intercept` is an ordinary `__cdecl` function
  (`D2Intercepts.cpp:71-73`) whose `ret` returns to whoever called the code at the site. The
  site is 16-byte aligned, consistent with D2BS replacing a whole game function (one that takes
  no stack arguments or whose caller removes them; otherwise the plain `ret` would unbalance the
  stack). `EAX`/`ECX`/`EDX` and the flags come back as the C code leaves them. Which function: not
  determinable from source.
- Handler: `void GameDraw(void)` (`D2Handlers.cpp:399`). When `Vars.bActive` and in game:
  `FlushPrint()` (queued `print()` output to the console / game chat), `Genhook::DrawAll(IG)`
  (all in-game screenhooks), `DrawLogo()`, `Console::Draw()`. Then a pending
  `takeScreenshot()` (`D2WIN_TakeScreenshot`). Then the **game-loop lock hand-off**: if a
  script thread is waiting (`Vars.SectionCount`), leave `Vars.cGameLoopSection` (on the first pass,
  while `Vars.bGameLoopEntered` is still false, only set that flag instead), `Sleep(0)`, enter
  it; otherwise `Sleep(10)` (`D2Handlers.cpp:410-418`).
- Feeds: in-game screenhooks, console, `print()`, `takeScreenshot()`, and every JS native that
  takes `AutoCriticalRoom` ([§8](#8-hooks-that-are-not-code-patches)).

### 5.3 `GamePacketReceived_Intercept` — server → client game packets

- Patch: CALL 5 at `0x0045F802` (`Patch.h:11`).
  Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes)) `call D2NET_ReceivePacket_I` (FUNCPTR, RVA `0x12B920`, VA `0x0052B920`, `D2Ptrs.h:364`).
- Entry state (inferred from the handler signature): `ECX` = packet bytes, `EDX` = length,
  `[ESP+4]` = the call's one stack argument (declared `int* arg3`, `D2Ptrs.h:364`).
- Body (`D2Intercepts.cpp:24-43`): `pushad`; `call GamePacketReceived` (`ECX`/`EDX`
  as at the site); `test eax, eax`; `popad`; if zero → `mov edx, 0`; then
  `mov eax, [esp+4]; push eax` (so `EAX` is the stack argument, not the site's `EAX`, when the game
  function runs); `call D2NET_ReceivePacket_I`; `ret 4`.
- Block semantics: the game call is **always** made; a blocked packet is passed with length 0.
  `ret 4` removes the original stack argument (the callee removed the re-pushed copy), so the
  stack is as after the original `__fastcall` call.
- Handler: `DWORD __fastcall GamePacketReceived(BYTE* pPacket, DWORD dwSize)`
  (`D2Handlers.cpp:145`). Non-zero = deliver, 0 = block. Dispatch on `pPacket[0]`:

  | Id | Action | Handler |
  |---|---|---|
  | `0xAE` | logs "Warden activity detected" and `TerminateProcess` | `D2Handlers.cpp:147` |
  | `0x15` | `gamepacket`, then: own unit id at `[2]` → `pPacket[10] = 0` (packet edited in place) | `ReassignPlayerHandler` `D2NetHandlers.cpp:18` |
  | `0x26` | `gamepacket`, then `chatmsg`; blocked if a `chatmsgblocker` returns `true` | `ChatEventHandler` `D2NetHandlers.cpp:55` |
  | `0x2A` | `gamepacket`, then `itemaction` with mode `100 + pPacket[2]` | `NPCTransactionHandler` `D2NetHandlers.cpp:71` |
  | `0x5A` | `gamepacket`, then `gameevent`; `QuitOnHostile` → `D2CLIENT_ExitGame()` on mode 7/param 3 | `EventMessagesHandler` `D2NetHandlers.cpp:81` |
  | `0x18`, `0x95` | `gamepacket`, then `melife` / `memana` when the value changed | `HPMPUpdateHandler` `D2NetHandlers.cpp:25` |
  | `0x9C`, `0x9D` | `gamepacket`, then `itemaction` (global flag = `0x9D`) | `ItemActionHandler` `D2NetHandlers.cpp:132` |
  | `0xA7` | `gamepacket`; then blocked when `pPacket[6] == AFFECT_JUST_PORTALED` (102) | `DelayedStateHandler` `D2NetHandlers.cpp:173` |
  | other | `gamepacket` only | `D2Handlers.cpp:169` |

  Each case is `return !GamePacketEvent(...) && Handler(...)`, so when a script blocks the packet
  the specific handler (and its event) is skipped.

### 5.4 `GamePacketSent_Interception` — client → server game packets

- Patch: **JMP** 5 at `0x0052AE5A` (`Patch.h:12`),
  `+0xA` into `D2NET_SendPacket` (FUNCPTR, RVA `0x12AE50`, VA `0x0052AE50`, `D2Ptrs.h:362`, `void __stdcall (size_t aLen, DWORD arg1, BYTE* aPacket)`).
  Resumes at `D2CLIENT_SendPacket_II` (ASMPTR, RVA `0x12AE62`, VA `0x0052AE62`, `D2Ptrs.h:284`) = site + 8.
- Entry state: inside `D2NET_SendPacket` after `push ebp`: `[ESP]` = saved EBP, `[ESP+4]` =
  return address, `[ESP+8]` = `aLen`, `[ESP+0xC]` = `arg1`, `[ESP+0x10]` = `aPacket`. Flags hold
  the result of a test that the original `jnz` consumes. (This layout is what the intercept's
  displacements imply.)
- Body (`D2Intercepts.cpp:45-69`):
  1. `pushf` + `pushad`. The code addresses the stack as `esp + 0x22 + ...`; `0x22` = `0x20`
     (`pushad`) + 2, i.e. the 16-bit `PUSHF` form (MASM's `PUSHF`, as opposed to `PUSHFD`).
  2. `ECX = [esp+0x22+4+0xC]` = `aPacket`, `EDX = [esp+0x22+4+0x4]` = `aLen`
     (`D2Intercepts.cpp:50-51`);
     `call GamePacketSent`; `test eax, eax`; `popad`.
  3. If blocked: `mov [esp + 0x4 + 4 + 2], 0` (`D2Intercepts.cpp:58`).
     After `popad` only the 2-byte flags word is still pushed (`ESP` = entry `ESP` − 2), so
     `[ESP+0xA]` is entry `[ESP+8]` = `aLen`. The operand size is not written out; see [§10](#10-open-questions).
  4. `popf`; re-created original code: `jnz good` → `jmp D2CLIENT_SendPacket_II`, else
     `xor eax, eax; pop ebp; ret 0Ch`.
- Block semantics: the send path still runs, with `aLen` cleared.
- Handler: `DWORD __fastcall GamePacketSent(BYTE* pPacket, DWORD dwSize)` (`D2Handlers.cpp:172`)
  = `!GamePacketSentEvent(...)`: 0 (block) when any `gamepacketsent` listener returns `true`.
- Note: the handler runs before the original branch, so it also sees calls that the game would
  have rejected via the early `ret 0Ch` path. D2BS's own sends through `D2NET_SendPacket`
  (`sendPacket()`, `JSCore.cpp:608`, and others) enter the same function and
  therefore presumably the same `gamepacketsent` event.

### 5.5 `GetSelectedUnit_Intercept` — click target override

- Patch: CALL 5 at `0x00462D72` (`Patch.h:13`),
  `+0x72` past `D2CLIENT_ClickMap` (FUNCPTR, RVA `0x62D00`, VA `0x00462D00`, `D2Ptrs.h:95`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `call D2CLIENT_GetSelectedUnit` (FUNCPTR, RVA `0x67A10`, VA `0x00467A10`, `D2Ptrs.h:70`, `UnitAny* __stdcall ()`).
- Body: a C function, `UnitAny* GetSelectedUnit_Intercept(void)` (`D2Intercepts.cpp:92-104`).
  No arguments, so `__cdecl` and `__stdcall` are interchangeable here. If `Vars.bClickAction`:
  return `D2CLIENT_FindUnit(Vars.dwSelectedUnitId, Vars.dwSelectedUnitType)` (`D2Helpers.cpp:500`)
  or `NULL` when no id is set; otherwise the real `D2CLIENT_GetSelectedUnit()`.
- Driven by `ClickMap()` (`Core.cpp:134`), which sets `bClickAction`/`dwSelectedUnit*` around its
  `D2CLIENT_ClickMap` calls (`Core.cpp:156-173`).
  So the game's click handler acts on the unit the script asked for (or on the ground) instead
  of what is under the mouse.
- Feeds: JS `clickMap()` and `unit.interact()` / `unit.move()` (callers of `ClickMap`, see
  [call-stubs.md](call-stubs.md)).

### 5.6 `Whisper_Intercept` — channel whisper text

- Patch: CALL 7 at `0x00448813` (`Patch.h:28`); returns to site + 5,
  then two NOPs.
- Entry state: `[ESP]` = site + 5; `EBX` = `char*` sender, `[EBP+8]` = `char*` text (the enclosing
  function's first argument), as passed to the handler.
- Body (`D2Intercepts.cpp:106-120`):
  1. `mov [esp-674h-4+4], edi` stores the original EDI at `ESP_site − 0x678`.
  2. `pop edi` (EDI = return address, `ESP` = `ESP_site`); `sub esp, 678h`. Now `ESP` =
     `ESP_site − 0x678` and `[ESP]` = original EDI: the state `sub esp, 674h; push edi` would
     produce (the displaced instructions, [§4](#4-displaced-instructions-and-expected-original-bytes)).
  3. `pushad`; `ECX = EBX`; `EDX = [EBP+8]`; `call WhisperHandler`; `popad`; `jmp edi`.
- Hard-coded: `0x674` / `0x678` (the enclosing function's frame size) and the `[EBP+8]` argument
  slot.
- Register effect: `popad` restores the `EDI` that `pushad` saved, and that is the popped return
  address. The game code after the site therefore runs with `EDI` = site + 5, not its original
  `EDI` (which survives only in the stack slot `[ESP]`, as the displaced `push edi` would have
  left it). Harmless only if that code writes `EDI` before reading it; not determinable from
  source ([§10](#10-open-questions)).
- Inference: site − 3 is 16-byte aligned, consistent with a 3-byte `push ebp; mov ebp, esp`
  prologue right before the displaced `sub esp, 674h`; that prologue is also what makes
  `[EBP+8]` the function's first stack argument.
- Handler: `void __fastcall WhisperHandler(char* szAcc, char* szText)` (`D2Handlers.cpp:464`):
  unless `bDontCatchNextMsg` (then it clears it), converts the text and calls `WhisperEvent`.
  The return value of the event is ignored, so `whispermsgblocker` cannot block here.
- Feeds: `whispermsg` (and the `whispermsgblocker` listeners run but have no effect).

### 5.7 `ChatPacketRecv_Interception` — Battle.net chat packets

- Patch: CALL 7 at `0x00521B20` (`Patch.h:26`).
  `Patch.h` warns: "this patch needs a constant in ChatPacketRecv_Interception updated also"
  (`Patch.h:25`).
- Body (`D2Intercepts.cpp:122-139`): `mov edx, [ebp+8]`; `mov ecx, ebx` (both kept after
  `popad`: these re-create the first two displaced instructions); `pushad`; `sub ecx, 4`;
  `add edx, 4`; `call ChatPacketRecv`; `test eax, eax`; `popad`; if zero → skip; else
  `call edi` (the third displaced instruction); `ret`.
- Stack note: the re-issued `call edi` runs one return address deeper than the original (the
  intercept's own return address to site + 5 is still on the stack), so the dispatch target sees
  the stack unchanged only if it takes no stack arguments, i.e. just `ECX`/`EDX` (inference). The
  same holds for `call esi` in [§5.16](#516-realmpacketrecv_interception--realm-mcp-packets) and
  for the re-issued game calls in [§5.1](#51-gameinput_intercept--in-game-chat-line),
  [§5.12](#512-congratsscreen_intercept-and-the-0x75-byte) and
  [§5.15](#515-channelinput_intercept--chat-channel-input-line).
- Handler arguments: `ECX = EBX − 4`, `EDX = [EBP+8] + 4`. `ChatPacketRecv` reads
  `pPacket[1] == 0x0F` and fields at `+4` and `+28` (`D2Handlers.cpp:533-536`),
  which fits a full BNCS message (`FF id len16` header + `SID_CHATEVENT` body); so `EBX`
  presumably points past the 4-byte header and `[EBP+8]` is the body length.
- Constants tied to the site (candidates for the one the comment means; it does not say which):
  the `[ebp+8]` displacement, the `-4`/`+4` header adjustment, and the dispatch register `EDI`.
- Handler: `BOOL __fastcall ChatPacketRecv(BYTE* pPacket, int len)` (`D2Handlers.cpp:530`). For
  `SID_CHATEVENT` (`0x0F`), by event id at `pPacket[4]`: `0x02` → `chatmsg` "joined the
  channel"; `0x03` → `chatmsg` "left the channel"; `0x04`, `0x0A` → `whispermsg`; `0x05`,
  `0x12`, `0x13`, `0x17` → `chatmsg`. It always returns `TRUE` (`blockPacket` is never set), so
  `call edi` always runs; blocker results are ignored.
- Feeds: out-of-game `chatmsg`, `whispermsg`.

### 5.8 `GameAttack_Intercept` — attack type rewrite

- Patch: CALL 5 at `0x00461704` (`Patch.h:21`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `mov eax, [D2CLIENT_MouseY]` (`p_D2CLIENT_MouseY` (VARPTR, RVA `0x3A6AAC`, VA `0x007A6AAC`, `D2Ptrs.h:144`)), re-created at `OldCode:`
  (`D2Intercepts.cpp:158-159`).
- Entry state: `ESI` = `UnitInteraction*` (`D2Intercepts.cpp:144`;
  layout `D2Structs.h`, see [structs.md](structs.md)).
- Body (`D2Intercepts.cpp:141-162`): `pushad`; `ECX = ESI`; `call GameAttack`; `cmp eax, -1`;
  `popad`. If `-1` → `OldCode`. Otherwise `call D2CLIENT_GetSelectedUnit` (the real one) and, if
  it returns non-NULL, `mov [esp+0x08+0x4+0x4], 1`: with the return address on top this is
  `[ESP_site + 0xC]`, a slot in the game function's frame (commented "bool unit"; operand size not
  written out, see [§10](#10-open-questions)). `OldCode`: `EAX = *p_D2CLIENT_MouseY`; `retn`.
- Register effects beyond the original: on the non-`-1` path `ECX`/`EDX` are clobbered by
  `D2CLIENT_GetSelectedUnit` after `popad`; on every path the flags are those of the intercept's
  last `cmp`, whereas the displaced `mov` sets none.
- Handler: `DWORD __fastcall GameAttack(UnitInteraction* pAttack)` (`D2Handlers.cpp:473`): returns
  `-1` unless the target is a monster; for monsters rewrites `dwMoveType`
  `ATTACKTYPE_UNITLEFT` (`0xC5`) → `ATTACKTYPE_SHIFTLEFT` (`0xE5`) and `ATTACKTYPE_RIGHT` (`0x46`)
  → `ATTACKTYPE_SHIFTRIGHT` (`0x66`) (`Constants.h:7-10`) and returns 0.
- Effect: every left/right unit attack on a monster that passes this site (scripted or by the
  user) becomes a stand-still (shift) attack. No JS event.

### 5.9 `PlayerAssignment_Intercept` — player unit assigned

- Patch: **JMP** 5 at `0x0045E4D5` (`Patch.h:14`).
- Body (`D2Intercepts.cpp:164-173`): `FNOP` (an x87 no-op); `CALL D2CLIENT_AssignPlayer_I`
  (ASMPTR, RVA `0x66200`, VA `0x00466200`, `D2Ptrs.h:250`); `MOV ECX, EAX`; `CALL GamePlayerAssignment`; `RETN`.
- Inference: the 5 overwritten bytes were either a tail `jmp D2CLIENT_AssignPlayer_I`, or a
  `call D2CLIENT_AssignPlayer_I` whose following `ret` the intercept re-creates with its `RETN`.
  In the tail-jump case the intercept's `CALL` runs `AssignPlayer_I` one return address deeper
  than the original, so it must take register arguments only; in the call-plus-`ret` case the
  stack depth is the same as in the original. Either way the enclosing function must end with a
  plain `ret` (no `ret N`) at that point, and `EAX` at the final `RETN` is whatever
  `GamePlayerAssignment` left, not `AssignPlayer_I`'s result.
- Handler: `void __fastcall GamePlayerAssignment(UnitAny* pPlayer)` (`D2Handlers.cpp:486`)
  → `PlayerAssignEvent(pPlayer->dwUnitId)` → `playerassign`.

### 5.10 `GameCrashFix_Intercept` — NULL guard (D2CMP region)

- Patch: CALL 10 at `0x006091E5` (`Patch.h:37`).
- Body (`D2Intercepts.cpp:175-184`): `CMP ECX, 0; JE Skip; MOV [ECX+0x10], EDX;
  Skip: MOV DWORD PTR [EAX+0xC], 0; RETN`. Re-creates both displaced stores and skips the first
  when `ECX` is NULL. The `CMP` leaves flags that the displaced `MOV`s would not have changed.
  No handler, no event.

### 5.11 `GameDrawOOG_Intercept` — out-of-game frame

- Patch: CALL 5 at `0x004F9A0D` (`Patch.h:35`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `call D2WIN_DrawSprites` (FUNCPTR, RVA `0xF9870`, VA `0x004F9870`, `D2Ptrs.h:437`).
- Body: C function (`D2Intercepts.cpp:186-188`) → `GameDrawOOG()` (`D2Handlers.cpp:421`):
  `D2WIN_DrawSprites()` first (the displaced call), then in the menu `FlushPrint()`,
  `Genhook::DrawAll(OOG)`, `DrawLogo()`, `Console::Draw()`; pending screenshot; always
  `Sleep(10)` (every out-of-game frame).
- Feeds: out-of-game screenhooks, console, `print()`, `takeScreenshot()`.

### 5.12 `CongratsScreen_Intercept` and the `0x75` byte

- Patches: CALL 5 at `0x0044EBEF` (`Patch.h:17`) and
  `PatchBytes` `0x75` at `0x0044EBFB` (`Patch.h:16`, comment "Congrats Screen").
- Body (`D2Intercepts.cpp:190-199`): `call D2CLIENT_CongratsScreen_I`
  (ASMPTR, RVA `0xF6190`, VA `0x004F6190`, `D2Ptrs.h:266`, the displaced call) first, then `pushad; call SetMaxDiff;
  popad; retn` (`EAX` from the game call is preserved). The re-issued call runs one return
  address deeper than the original, so `CongratsScreen_I` must not read stack arguments
  (inference).
- Handler: `void SetMaxDiff(void)` (`D2Handlers.cpp:436`): if `D2CLIENT_GetDifficulty() == 1` and
  `*p_D2CLIENT_ExpCharFlag` is non-zero, sets `(*p_D2LAUNCH_BnData)->nMaxDiff = 10`.
- The one-byte patch's original value is not recorded; if the byte is a short-`Jcc` opcode,
  `0x75` makes it `JNZ rel8`. No JS event.

### 5.13 `GameActChange_Intercept` / `GameActChange2_Intercept` — act-change flag

- `GameActChange2_Intercept`: **JMP** 5 at `0x004567EB`
  (`Patch.h:19`). Body (`D2Intercepts.cpp:213-221`):
  `MOV ESP, EBP; POP EBP; MOV [Vars.bChangedAct], 1; retn`, i.e. the enclosing function's
  epilogue plus "set the flag".
- `GameActChange_Intercept`: CALL 5 at `0x004547B6` (`Patch.h:18`).
  Body (`D2Intercepts.cpp:201-211`): `POP EAX` (return address); `PUSH ESI; XOR ESI, ESI`
  (re-created); `CMP [Vars.bChangedAct], 0` (ZF for the game code that follows);
  `MOV [Vars.bChangedAct], 0` (does not change flags); `JMP EAX`.
- `Vars.bChangedAct` is a `BOOL` (`D2BS.h:48`), so both accesses are 32-bit;
  it is reset in `Startup()` (`D2BS.cpp:126`) and used nowhere else.
- Side effects: `EAX` = site + 5 on return. Two of the five displaced bytes are not re-created;
  the intercept's `CMP` replaces whatever flag-setting instruction was there (inference).
- Net effect: the first pass through `0x004547B6` after any pass through
  `0x004567EB` continues with `ZF` = 0 and clears the flag; every other pass
  continues with `ZF` = 1. Whatever condition the overwritten instruction tested is no longer
  evaluated. The game-level meaning is not
  determinable from source. No JS event.

### 5.14 `GameLeave_Intercept` — leaving a game

- Patch: CALL 5 at `0x0044F57C` (`Patch.h:20`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `call D2CLIENT_GameLeave_I` (ASMPTR, RVA `0x81830`, VA `0x00481830`, `D2Ptrs.h:264`).
- Body (`D2Intercepts.cpp:223-229`): `call GameLeave` then `jmp D2CLIENT_GameLeave_I`. The jump
  leaves the original return address on the stack, so `GameLeave_I` returns straight to site + 5
  and sees any stack arguments where the original call put them. `GameLeave()` is `__cdecl`
  and may clobber `EAX`/`ECX`/`EDX` first, so `GameLeave_I` cannot take arguments in those
  registers (inference).
- Handler: `void GameLeave(void)` (`D2Handlers.cpp:506`): `Vars.bQuitting = false`, stops every
  in-game script (`StopIngameScript`), `ActMap::ClearCache()`. Runs before the game's own
  leave code. No JS event (scripts are stopped instead).

### 5.15 `ChannelInput_Intercept` — chat-channel input line

- Patch: CALL 5 at `0x00442A61` (`Patch.h:29`). Overwrites (inferred, [§4](#4-displaced-instructions-and-expected-original-bytes))
  `call D2MULTI_ChannelInput_I` (ASMPTR, RVA `0x428D0`, VA `0x004428D0`, `D2Ptrs.h:404`).
- Entry state: `ESI` = `wchar_t*` line typed into the Battle.net channel box.
- Body (`D2Intercepts.cpp:231-247`): `push ecx`; `ECX = ESI`; `call ChannelInput`;
  `test eax, eax`; `pop ecx`; if zero → `ret` (`EAX` = 0); else `call D2MULTI_ChannelInput_I`;
  `ret`. Only `ECX` is preserved; `EAX`/`EDX` are whatever `ChannelInput` left, so
  `ChannelInput_I` cannot take arguments in them, nor stack arguments (one return address deeper).
- Handler: `DWORD __fastcall ChannelInput(wchar_t* wMsg)` (`D2Handlers.cpp:133`): same logic as
  `GameInput` but returns `TRUE` = send, `FALSE` = block.
- Feeds: `chatinput` / `chatinputblocker`; `.` commands out of game.

### 5.16 `RealmPacketRecv_Interception` — realm (MCP) packets

- Patch: CALL 6 at `0x0044B1AE` (`Patch.h:39`).
  **No 1.14d marker** (the only `"D2MCPClient.dll"` entry); see [§1](#1-summary).
- Body (`D2Intercepts.cpp:7-22`): `test esi, esi; jz block` (→ `ret`); `pushad`;
  `call RealmPacketRecv` (`ECX`/`EDX` as at the site); `cmp eax, 0`; `popad`; if zero → `ret`;
  else `call esi`; `ret`. `jz block` names the label `Block:` in a different case; MSVC inline
  asm labels are not case-sensitive, so both go to `Block:`.
- Inference: the displaced bytes were `test esi,esi; jz short +2; call esi`, i.e. "if a handler
  pointer exists, call it", with `ECX`/`EDX` = packet and length. The re-issued `call esi` is one
  return address deeper than the original (stack note in
  [§5.7](#57-chatpacketrecv_interception--battlenet-chat-packets)). On the skip and block paths
  `EAX` is the site's `EAX` (restored by `popad`), not a handler result.
- Handler: `BOOL __fastcall RealmPacketRecv(BYTE* pPacket, DWORD dwSize)` (`D2Handlers.cpp:526`)
  = `!RealmPacketEvent(...)`: block (skip `call esi`) when a `realmpacket` listener returns `true`.

### 5.17 `ClassicSTUB` / `LodSTUB` — raw CD keys (`-d2c` / `-d2x`)

- Patches: **JMP** 5 at `0x0052366C` and `0x00523958` (`Patch.h:48`,
  `Patch.h:49`), both gated by `Vars.bUseRawCDKey`. Both sites lie `0x19C` /
  `0x488` bytes after `BNCLIENT_DecodeAndLoadKeys` (FUNCPTR, RVA `0x1234D0`, VA `0x005234D0`, `D2Ptrs.h:472`).
- `ClassicSTUB` (`D2Intercepts.cpp:273-279`): `*p_BNCLIENT_ClassicKey = Vars.szClassic;` then
  `jmp BNCLIENT_DClass` (ASMPTR, RVA `0x123673`, VA `0x00523673`, `D2Ptrs.h:466` = site + 7: 5 patched + 2 untouched bytes skipped).
- `LodSTUB` (`D2Intercepts.cpp:281-287`): `*p_BNCLIENT_XPacKey = Vars.szLod;` then `jmp BNCLIENT_DLod`
  (ASMPTR, RVA `0x12395D`, VA `0x0052395D`, `D2Ptrs.h:467` = site + 5).
- The globals: `p_BNCLIENT_ClassicKey` (VARPTR, RVA `0x482744`, VA `0x00882744`, `D2Ptrs.h:469`), `p_BNCLIENT_XPacKey` (VARPTR, RVA `0x48274C`, VA `0x0088274C`, `D2Ptrs.h:470`) (`char*`); D2BS stores
  pointers to its own `char[30]` buffers (`D2BS.h:89`, `D2BS.h:90`).
- These are `__declspec(naked)` functions containing a C statement; the compiler emits that
  assignment with scratch registers of its choosing (not visible in source), so at least one of
  `EAX`/`ECX`/`EDX` is clobbered at the site.

### 5.18 `FailToJoin` — FTJ reducer (never installed)

- Patch: CALL 6 at `0x0044EF28` (`Patch.h:50`), gated by `Vars.bReduceFTJ`.
- Body (`D2Intercepts.cpp:289-295`): `cmp esi, 4000; ret`. Replaces a `cmp esi, imm32` with a 4000
  (`0xFA0`) threshold; the flags survive the `ret` for the following `Jcc` (inference: `ESI` is
  an elapsed-time value in ms). Dead: the flag can never be set ([§7](#7-conditional-patches-and-their-flags)).

### 5.19 `Multi`, `Windowname` — multiple instances (`-multi`)

- `Multi` (`D2Intercepts.cpp:326-328`): CALL 6 at `0x004F5623` (`Patch.h:51`).
  `HMODULE __stdcall Multi(LPSTR Class, LPSTR Window)` returns 0. Same shape as `FindWindowA`
  (inference: replaces the game's "is another instance's window open?" lookup, so a second
  client starts).
- `Windowname` (`D2Intercepts.cpp:330-343`): CALL 6 at `0x004F5831` (`Patch.h:52`).
  CreateWindowExA-shaped `__stdcall` replacement that calls `CreateWindowExW` with title
  `Vars.szTitle` (from `-title`, used when longer than 1 character) or `L"D2"`, and the class name
  widened from the ANSI argument.
- Both stay installed after shutdown.

### 5.20 `CacheFix`, `EraseCacheFiles` — per-instance `bncache` (`-cachefix`)

- Patches: CALL 6 at `0x0051944E` and `0x00519434` (`Patch.h:53`, `Patch.h:54`).
- `CacheFix` (`D2Intercepts.cpp:345-369`), CreateFileA-shaped `__stdcall`: calls `EraseCacheFiles()`
  (`D2Intercepts.cpp:297-324`), which **deletes every `*.dat` file in the current directory**; then
  opens `<cwd>\bncache<N>.dat` with the caller's other arguments. `lpFileName` is ignored.
- `N`: if the window title is longer than 1 character, `sprintf_s(Def, "\\bncache%d.dat", szTitle)`
  (`D2Intercepts.cpp:357`) formats the *address* of the
  local `szTitle` buffer with `%d` (bug: not the title); otherwise `rand() % 0x2000` seeded with
  `GetTickCount()`.

### 5.21 `LogMessageBoxA_Intercept`, `ErrorReportLaunch`, `D2GAME_exit0` — crash paths

- `LogMessageBoxA_Intercept` (`D2Intercepts.cpp:374-380`): CALL 6 at
  `0x00408CC4` (`Patch.h:41`). `int WINAPI` with
  `MessageBoxA`'s signature: `GetStackWalk()` (all threads), logs caption, text and
  `DllLoadAddrStrs()` (`Helpers.cpp:372`, which on 1.14d logs `GetModuleHandle` of the
  legacy DLL names), then calls the real `MessageBoxA`.
- `ErrorReportLaunch` (`D2Intercepts.cpp:416-420`): **JMP** 6 at `0x00401790`
  (`Patch.h:44`). `char __fastcall (const char* crash_file, int a2)`: stack walk,
  logs the crash file name, `exit(0)`. Replaces the game's error-report launch; never returns.
- `D2GAME_exit0` (`Patch.h:42`): **JMP** 6 at `0x004082E0`, meant to send that
  code path to `D2GAME_exit0` (FUNCPTR, RVA `0x576F`, VA `0x0040576F`, `D2Ptrs.h:481`); actually jumps to `0x00576F06`
  ([§2.6](#26-the-d2game_exit0-static-initialisation-bug)).

### 5.22 Functions with no installed patch

- `AddUnit_Intercept` (`D2Intercepts.cpp:249-259`): `call [D2CLIENT_GameAddUnit_I]` (stale 1.13
  ASMPTR, `D2CLIENT_GameAddUnit_I` (ASMPTR, RVA `0x628E0`, VA `0x004628E0`, `D2Ptrs.h:273`)), then `pushad; push esi; call AddUnit; popad; retn`.
  `AddUnit` (`D2Handlers.cpp:444`) is `__stdcall` (pops its argument) and its body is commented out.
  Patch commented out at `Patch.h:22`.
- `RemoveUnit_Intercept` (`D2Intercepts.cpp:261-271`): `pushad; push [esi+edx*4]; call RemoveUnit;
  popad; mov eax, [ecx+0xE4]; mov [esi+edx*4], eax; retn`, i.e. a 9-byte unlink
  (`8B 81 E4 00 00 00 89 04 96`) with a notification first; `UnitAny+0xE4` is `pListNext`
  ([structs.md](structs.md)). `RemoveUnit` (`D2Handlers.cpp:450`) is empty. Patch commented out.
- `FogException` (`D2Intercepts.cpp:405-414`): raises exception 1 and `exit(0)` from the filter; its
  patch line is commented out (`Patch.h:43`).
- `MyUnhandledExceptionFilter` (`D2Intercepts.cpp:383-402`): writes `CrashNNN.dump`; marked
  "NOT WORKING ONE, WORKING ONE IS IN Helpers.cpp"; never referenced. The installed filter is
  `ExceptionHandler` (`Helpers.cpp:396`, set at `D2BS.cpp:93`).

### 5.23 Constants that move with the patch sites

When a site is re-located (another build, or a corrected 1.14d offset), these literals inside
the intercepts and stubs encode the surrounding game code and must be re-derived with it.

| Constant | Where | Encodes |
|---|---|---|
| `0x22`, `+4+0xC`, `+4+0x4`, `+0x4+4+2` | `D2Intercepts.cpp:50-51`, `D2Intercepts.cpp:58` | 16-bit `PUSHF` + `PUSHAD`, and `D2NET_SendPacket`'s frame (saved EBP, then `aLen`, `arg1`, `aPacket`) |
| re-created `jnz` / `xor eax,eax` / `pop ebp` / `ret 0Ch`, resume label `D2CLIENT_SendPacket_II` | `D2Intercepts.cpp:61-67` | the 8 bytes at the `GamePacketSent` site |
| `[esp + 4]`, `ret 4` | `D2Intercepts.cpp:37-41` | one stack argument of `D2NET_ReceivePacket_I` |
| `0x674`, `0x678`, `[ebp+8]` | `D2Intercepts.cpp:109-114` | frame size and text argument of the whisper function |
| `[ebp + 8]`, `-4`, `+4`, `EDI`, `EBX` | `D2Intercepts.cpp:124-128`, `D2Intercepts.cpp:135` | BNCS dispatch registers and header size (the constant `Patch.h:25` refers to is one of these) |
| `[esp+0x08+0x4+0x4]` | `D2Intercepts.cpp:155` | "bool unit" slot in the attack function's frame |
| `MouseY` reload | `D2Intercepts.cpp:158-159` | the displaced `mov eax, [MouseY]` |
| `PUSH ESI` / `XOR ESI, ESI` | `D2Intercepts.cpp:205-206` | displaced code at the act-change site |
| `MOV ESP, EBP` / `POP EBP` | `D2Intercepts.cpp:216-217` | displaced epilogue at the second act-change site |
| `[ECX+0x10]`, `[EAX+0xC]` | `D2Intercepts.cpp:179-181` | the two stores displaced by the crash fix |
| `ESI`, `ECX`/`EDX` | `D2Intercepts.cpp:7-22` | realm dispatch registers |
| `ESI` (channel text), `EBX` (chat text) | `D2Intercepts.cpp:234`, `D2Intercepts.cpp:78` | input-line registers |
| `ESI` (attack struct) | `D2Intercepts.cpp:144` | attack-struct register |
| `4000` | `D2Intercepts.cpp:292` | FTJ threshold (and `ESI` as its register) |
| resume labels `BNCLIENT_DClass` (site+7), `BNCLIENT_DLod` (site+5) | `D2Ptrs.h:466`, `D2Ptrs.h:467` | code skipped after the CD-key stores |

## 6. Handlers, events and blocking

### 6.1 Intercept → handler → JS event (generated)

Event names are the string literals in the `Events.cpp` functions (and their callbacks) that each
handler reaches; `...blocker` variants are the synchronous listeners whose `true` return value
can veto. JS-side semantics: [../js-api/events.md](../js-api/events.md).

| Intercept | C++ handler | Handler calls (event fns / sub-handlers) | JS events fired |
|---|---|---|---|
| `GameInput_Intercept` | `GameInput` (`D2Handlers.cpp:121`) | `ChatInputEvent` (`Events.cpp:218`) | `chatinput`, `chatinputblocker` |
| `ChannelInput_Intercept` | `ChannelInput` (`D2Handlers.cpp:133`) | `ChatInputEvent` (`Events.cpp:218`) | `chatinput`, `chatinputblocker` |
| `GamePacketReceived_Intercept` | `GamePacketReceived` (`D2Handlers.cpp:145`) | `GamePacketEvent` (`Events.cpp:332`), `ChatEvent` (`Events.cpp:213`), `GameActionEvent` (`Events.cpp:288`), `LifeEvent` (`Events.cpp:18`), `ManaEvent` (`Events.cpp:37`), `ItemActionEvent` (`Events.cpp:265`), `ChatEventHandler` (`D2NetHandlers.cpp:55`), `DelayedStateHandler` (`D2NetHandlers.cpp:173`), `EventMessagesHandler` (`D2NetHandlers.cpp:81`), `HPMPUpdateHandler` (`D2NetHandlers.cpp:25`), `ItemActionHandler` (`D2NetHandlers.cpp:132`), `NPCTransactionHandler` (`D2NetHandlers.cpp:71`), `ReassignPlayerHandler` (`D2NetHandlers.cpp:18`) | `gamepacket`, `chatmsg`, `chatmsgblocker`, `gameevent`, `melife`, `memana`, `itemaction` |
| `GamePacketSent_Interception` | `GamePacketSent` (`D2Handlers.cpp:172`) | `GamePacketSentEvent` (`Events.cpp:337`) | `gamepacketsent` |
| `RealmPacketRecv_Interception` | `RealmPacketRecv` (`D2Handlers.cpp:526`) | `RealmPacketEvent` (`Events.cpp:342`) | `realmpacket` |
| `ChatPacketRecv_Interception` | `ChatPacketRecv` (`D2Handlers.cpp:530`) | `ChatEvent` (`Events.cpp:213`), `WhisperEvent` (`Events.cpp:223`) | `chatmsg`, `chatmsgblocker`, `whispermsg`, `whispermsgblocker` |
| `Whisper_Intercept` | `WhisperHandler` (`D2Handlers.cpp:464`) | `WhisperEvent` (`Events.cpp:223`) | `whispermsg`, `whispermsgblocker` |
| `PlayerAssignment_Intercept` | `GamePlayerAssignment` (`D2Handlers.cpp:486`) | `PlayerAssignEvent` (`Events.cpp:99`) | `playerassign` |
| `GameAttack_Intercept` | `GameAttack` (`D2Handlers.cpp:473`) | - | - (no JS event) |
| `GameLeave_Intercept` | `GameLeave` (`D2Handlers.cpp:506`) | - | - (no JS event) |
| `CongratsScreen_Intercept` | `SetMaxDiff` (`D2Handlers.cpp:436`) | - | - (no JS event) |
| `GameDraw_Intercept` | `GameDraw` (`D2Handlers.cpp:399`) | - | - (no JS event) |
| `GameDrawOOG_Intercept` | `GameDrawOOG` (`D2Handlers.cpp:421`) | - | - (no JS event) |

### 6.2 Blocking and timeouts

| Mechanism | Code | Behaviour |
|---|---|---|
| Fan-out | `ScriptEngine::ForEachScript` `ScriptEngine.cpp:204` | calls the callback for every script; returns `true` if any callback returned `true` (`ScriptEngine.cpp:223`) |
| Packet events (`gamepacket`, `gamepacketsent`, `realmpacket`) | `PacketEventCallback` `Events.cpp:293` | copies the packet; runs the listener inline if the hook fires on the script's own thread, otherwise queues the event, releases the game-loop lock (`ReleaseGameLock`, `Events.cpp:347`), waits up to **500 ms** on `Vars.eventSignal`, retakes the lock. Timeout = not blocked. |
| Chat blockers (`chatmsgblocker`, `chatinputblocker`, `whispermsgblocker`) | `ChatEventCallback` `Events.cpp:173` | non-blocking `<name>` event, then `<name>blocker` with a **500 ms** wait (`Events.cpp:200`); unlike packet events the game-loop lock is **not** released while waiting |
| Key blockers (Win32 keyboard hook, not a patch) | `KeyEventCallback` `Events.cpp:42` | `keydownblocker` / `keyupblocker`, **1000 ms** wait (`Events.cpp:66`). `ExecScriptEvent` has a branch for `keydownblocker` but not for `keyupblocker` (`ScriptEngine.cpp:634`), so nothing signals a `keyupblocker` wait: it always runs into the timeout and never blocks |
| Listener result | `ExecScriptEvent` packet branch `ScriptEngine.cpp:738` | `block \|= (rval is boolean true)` across the script's listeners, stored in `arg4`, then `SetEvent(Vars.eventSignal)` |

- Every wait uses the single process-wide manual-reset `Vars.eventSignal`
  (`Helpers.cpp:155`) and runs on the
  thread that hit the hook, so a slow script stalls the game thread for up to the timeout per
  listening script. `PacketEventCallback` keeps its wait result in a function-`static`
  (`Events.cpp:311`), shared by all threads.
- Because the event is manual-reset and shared, any `SetEvent` releases every thread waiting at
  that moment, and a listener that finishes after its caller timed out still sets it. A waiter
  released early reads its own `arg4` (still `false`, so "not blocked") and frees its `Event`
  while that event is still queued for the script thread, which later dereferences the freed
  object in `ExecScriptEvent` (use-after-free). Screen-hook click handlers signal the same event
  (`ScriptEngine.cpp:660`). A waiter that times out
  returns without freeing its `Event` (leak).
- Which hooks honour a veto: `GameInput`, `ChannelInput`, `GamePacketReceived` (including the
  in-game `0x26` chat), `GamePacketSent`, `RealmPacketRecv`. `WhisperHandler` and
  `ChatPacketRecv` ignore the event result.

## 7. Conditional patches and their flags

Generated from `Patch.h`, `D2BS.h`, `D2BS.cpp` and `CommandLine.cpp`:

| Flag | Declared | Set to TRUE at | Switch | Switch in `CLine[]` (`CommandLine.cpp:30`)? | Gates |
|---|---|---|---|---|---|
| `Vars.bUseRawCDKey` | `D2BS.h:68` | `D2BS.cpp:69` | `-d2c` | yes | `Patch.h:48` `ClassicSTUB`<br>`Patch.h:49` `LodSTUB` |
| `Vars.bReduceFTJ` | `D2BS.h:73` | `D2BS.cpp:66` | `-ftj` | **no** | `Patch.h:50` `FailToJoin` |
| `Vars.bMulti` | `D2BS.h:71` | `D2BS.cpp:63` | `-multi` | yes | `Patch.h:51` `Multi`<br>`Patch.h:52` `Windowname` |
| `Vars.bCacheFix` | `D2BS.h:70` | `D2BS.cpp:60` | `-cachefix` | yes | `Patch.h:53` `CacheFix`<br>`Patch.h:54` `CacheFix` |
| `Vars.bSleepy` | `D2BS.h:72` | `D2BS.cpp:57` | `-sleepy` | yes | `Patch.h:55` `0x9090`<br>`Patch.h:56` `0xEB` |

- Parsing: `InitCommandLine()` copies at most 256 wide characters of `GetCommandLineW()` into
  `Vars.szCommandLine` and then overwrites the process command line buffer with a fixed
  `"...\Game.exe -w"` string (`Helpers.cpp:483-488`; the `memcpy` uses `sizeof(LPWSTR)` per
  character, i.e. twice the string's byte length). `ParseCommandLine()` (`CommandLine.cpp:52`)
  searches that copy, case-insensitively and anywhere in the string, for each `CLine[]` option and
  records the ones found; text options take the next double-quoted value. `GetCommand()`
  (`CommandLine.cpp:90`) only returns recorded options, so a switch missing from `CLine[]` can never
  match.
- Order: `DllMain` parses and sets the flags (`D2BS.cpp:45-78`)
  before `Startup()` → `InstallConditional()`. Nothing reads `d2bs.ini` for these flags
  (`InitSettings`, `Helpers.cpp:107-162`). Changing `Vars` later has no effect.
- `-d2c "<key>"` sets `bUseRawCDKey` and fills `szClassic`; `-d2x "<key>"` only fills `szLod`. Both
  stubs are gated by `bUseRawCDKey`, so `-d2x` without `-d2c` does nothing, and `-d2c` alone
  installs `LodSTUB` with an empty `szLod`. `bUseRawCDKey` is reset to `FALSE` first
  (`D2BS.cpp:49`). Keys are appended with `strncat_s` into `char[30]`.
- `-title "<text>"` is not a patch flag but feeds `Windowname` (with `-multi`) and, through the
  window text, `CacheFix`.
- History: before commit `a1f0409` (2019-02-28) the FTJ entry sat in the index range installed by
  `-multi` (`git show a1f0409 -- Offset.cpp`); that commit gave it its own `-ftj` switch without
  adding `-ftj` to `CLine[]`.

| Flag | Patch effect (details in §5) |
|---|---|
| `bUseRawCDKey` | game reads the CD keys from D2BS's buffers ([§5.17](#517-classicstub--lodstub--raw-cd-keys--d2c---d2x)) |
| `bReduceFTJ` | would replace a timeout comparison with `cmp esi, 4000` ([§5.18](#518-failtojoin--ftj-reducer-never-installed)); unreachable |
| `bMulti` | instance check returns "none found"; window created with `-title` ([§5.19](#519-multi-windowname--multiple-instances--multi)) |
| `bCacheFix` | `bncache.dat` replaced by `bncache<N>.dat` after deleting all `*.dat` ([§5.20](#520-cachefix-erasecachefiles--per-instance-bncache--cachefix)) |
| `bSleepy` | NOPs 2 bytes at `0x00451C31` ("Sleep") and writes `EB` at `0x004FA66F` ("OOG Sleep"); consistent with disabling / forcing short branches around the game's idle sleeps (original bytes not recorded) |

## 8. Hooks that are not code patches

Installed by `InitHooks()` (`Helpers.cpp:164-208`) on `D2Thread` once the game window exists; removed
in `Shutdown()`.

| Hook | Installed | Handler | Feeds |
|---|---|---|---|
| Window procedure subclass (`SetWindowLong(GWL_WNDPROC)`) | `Helpers.cpp:176` | `GameEventHandler` `D2Handlers.cpp:176` | `WM_COPYDATA`: `dwData` `0x1337` runs a script command, `0x31337` switches profile, anything else → `copydata` event; all other messages go to the original WNDPROC |
| Timer, 0 ms (`SetTimer`) | `Helpers.cpp:180` | `TimerProc` `D2Handlers.cpp:493` | first call (while `Vars.bGameLoopEntered` is false): sets that flag, records `Vars.dwGameThreadId` and enters `Vars.cGameLoopSection`; later calls release and re-take it, sleeping 5 ms in between if a script is waiting. Windows raises a 0 ms `SetTimer` interval to `USER_TIMER_MINIMUM` (10 ms) |
| `WH_KEYBOARD` on the window's thread | `Helpers.cpp:185` | `KeyPress` `D2Handlers.cpp:206` | console keys, `keyup`/`keydown`(+blocker) events; `Vars.bBlockKeys` swallows input |
| `WH_MOUSE` on the window's thread | `Helpers.cpp:187` | `MouseMove` `D2Handlers.cpp:296` | `mouseclick`, `mousemove`, screenhook click handlers; `Vars.bBlockMouse` |
| Unhandled-exception filter | `D2BS.cpp:93` | `ExceptionHandler` `Helpers.cpp:396` | crash log (registers, stack walk) |
| DDE server | `D2BS.cpp:135` | `CreateDdeServer` `dde.cpp:31` | external command channel |

**Game-loop lock.** The game thread holds `Vars.cGameLoopSection` while it runs game code and
releases it only inside `GameDraw` (when `Vars.SectionCount > 0`) and `TimerProc`. Script threads
that call game functions take it through `AutoCriticalRoom` (`CriticalSections.h:31-55`), which increments
`Vars.SectionCount` while waiting. `PacketEventCallback` releases the lock while it waits for a
script ([§6.2](#62-blocking-and-timeouts)), so a script can call game code from inside a packet
handler, but only when the hook runs on the thread recorded in `Vars.dwGameThreadId`
(`ReleaseGameLock`, `Events.cpp:347`). That id is written only by the first `TimerProc` call
(`D2Handlers.cpp:498`); if `GameDraw` takes the
first-entry branch first (`D2Handlers.cpp:414`), the id stays 0 and the
lock is never released for a packet wait. Chat and key blocker waits never release it, so when
the waiting thread is the lock owner, a blocker listener that calls a locking JS native stalls
until the wait times out. Which JS natives take the lock: [call-stubs.md §7](call-stubs.md#7-thread-and-lock-context).

## 9. Notes for replacing the JS layer with RPC

- The patch engine, `Patch.h`, the intercepts and the C++ handlers do not touch SpiderMonkey.
  The coupling points are the `Events.cpp` functions (`*Event()`), which go through
  `ScriptEngine::ForEachScript`, and `ProcessCommand()` for `.` commands. Replacing those
  functions keeps every hook.
- Vetoes are synchronous on a game thread. An RPC design needs either a local rule engine
  (filters pushed to the DLL) or a bounded round-trip with a default, as today (500 ms /
  1000 ms timeouts, [§6.2](#62-blocking-and-timeouts)).
- Blocking is implemented differently per hook: received/sent game packets are not dropped but
  passed on with length 0; input lines and realm dispatch skip the game call (the chat-packet
  intercept could skip `call edi` too, but `ChatPacketRecv` never asks it to). Some handlers
  edit packets in place (`0x15`) or act on their own (`0xAE` kills the process, `0xA7` with
  state 102 is always blocked, `QuitOnHostile` exits the game).
- Game calls made from outside the game thread need the game-loop lock hand-off that
  `GameDraw`/`TimerProc` provide ([§8](#8-hooks-that-are-not-code-patches)); an RPC server thread
  must use the same mechanism or marshal calls onto the game thread.
- Before relying on any site, verify the expected bytes in [§4](#4-displaced-instructions-and-expected-original-bytes),
  fix the `D2GAME_exit0` target, and decide whether to keep `GameAttack_Intercept` (it changes
  user-visible game behaviour for all attacks) and the `CacheFix` deletion of `*.dat` files.

## 10. Open questions

- **Operand size of two immediate stores.** `mov [esp + 0x4 + 4 + 2], 0` in
  `GamePacketSent_Interception` (`D2Intercepts.cpp:58`) and
  `mov [esp+0x08+0x4+0x4], 1` in `GameAttack_Intercept` (`D2Intercepts.cpp:155`)
  have no `dword ptr`/`byte ptr`. If MSVC emitted a byte store, a blocked sent packet keeps
  `aLen & ~0xFF` (only packets shorter than 256 bytes are fully blocked). Check the compiled
  D2BS.dll.
- **`PUSHF` width.** The `0x22` displacement assumes a 2-byte `PUSHF` ([§5.4](#54-gamepacketsent_interception--client--server-game-packets)); confirm `66 9C` in the compiled intercept.
- **RealmPacketRecv site** (`0x0044B1AE`): no 1.14d marker; expected bytes
  `85 F6 74 02 FF D6`. If they differ, the always-installed patch corrupts code.
- **Conditional sites without markers**: `FailToJoin`, `Multi`, `Windowname`, both `CacheFix`
  sites, and both `bSleepy` byte patches (`Patch.h:50-56`). Their
  1.14d validity is not provable from source ([offsets.md §3](offsets.md#3-stale-and-suspect-entries-what-depends-on-them)).
- **Which constant** `Patch.h` means for `ChatPacketRecv_Interception` (`Patch.h:25`).
- **Enclosing game functions** of every site, what `C3` at `0x00468770` disables, the original
  byte at `0x0044EBFB`, and what the act-change flag pair (`0x004547B6`,
  `0x004567EB`) is for, including which 2-byte instruction
  `GameActChange_Intercept` drops and whether the clobbered `EAX` matters.
- **`0x453B30`**: is it a function entry, and does that function take stack arguments (it would
  then need `ret N`, which `GameDraw_Intercept` does not do)?
- **Double whisper events**: a channel whisper may reach both `Whisper_Intercept` and the
  `SID_CHATEVENT 0x04` case of `ChatPacketRecv`; not determinable without running it.
- **`D2GAME_exit0`**: what the code at `0x4082E0` and `0x40576F` is.
- **DEP**: whether Game.exe 1.14d runs with DEP enforced (decides whether the
  `PAGE_READWRITE` window in `WriteBytes` can crash a game thread).
- **Packet thread**: which game thread runs the packet intercepts (decides whether
  `PacketEventCallback`'s `ReleaseGameLock` path is taken).
- **`EDI` after `Whisper_Intercept`**: does the code after `0x00448813` + 7 read `EDI`
  before writing it? The intercept leaves `EDI` = site + 5 ([§5.6](#56-whisper_intercept--channel-whisper-text)).
- **Stack arguments of re-issued calls**: do `D2CLIENT_InputCall_I`, `D2CLIENT_CongratsScreen_I`,
  `D2MULTI_ChannelInput_I` and the `call esi` / `call edi` dispatch targets read stack
  arguments? Each runs one return address deeper than the original call.

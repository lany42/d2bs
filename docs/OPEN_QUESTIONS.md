# Open questions

Scope: every question about D2BS 1.6.4U on Diablo II 1.14d that could **not** be answered by reading the C++ source in this repository, the bundled SpiderMonkey headers (`dependencies/include`) or the bundled build artifacts (`dependencies/libs`, `Debug/`, `Release/`). Each entry says why the answer matters for the next-generation D2BS (SpiderMonkey removed, JS API replaced by a networked RPC control API), what is already known, and how to settle it. Candidates came from every "Open questions" section and every "unknown / unverified / not determinable" statement under `docs/`, plus the open questions and remaining concerns reported by the agents that wrote and verified those docs. The Ghidra importer's questions were added after it was finished: [OQ-BLD-05](#oq-bld-05) and [OQ-BLD-06](#oq-bld-06). Duplicates were merged. Each candidate was then checked against the source, the headers and the shipped binaries. Questions closed that way are in [Appendix A](#appendix-a-resolved-during-triage), and the doc that raised them was updated in place.

## Contents

- [How to read this page](#how-to-read-this-page)
- [Summary table](#summary-table)
- [1. Game memory & offsets (MEM)](#1-game-memory--offsets-mem)
- [2. Struct layouts & field semantics (STR)](#2-struct-layouts--field-semantics-str)
- [3. Game logic & data semantics (GAME)](#3-game-logic--data-semantics-game)
- [4. Network protocol & packet paths (NET)](#4-network-protocol--packet-paths-net)
- [5. Game UI, input & rendering (UI)](#5-game-ui-input--rendering-ui)
- [6. Out-of-game, Battle.net & realm flows (OOG)](#6-out-of-game-battlenet--realm-flows-oog)
- [7. Threading & runtime concurrency (THR)](#7-threading--runtime-concurrency-thr)
- [8. SpiderMonkey engine semantics (SM)](#8-spidermonkey-engine-semantics-sm)
- [9. Windows platform & CRT behaviour (WIN)](#9-windows-platform--crt-behaviour-win)
- [10. External tooling & IPC consumers (EXT)](#10-external-tooling--ipc-consumers-ext)
- [11. Build, toolchain & RE tooling (BLD)](#11-build-toolchain--re-tooling-bld)
- [12. Intent & legacy behaviour (INT)](#12-intent--legacy-behaviour-int)
- [Appendix A. Resolved during triage](#appendix-a-resolved-during-triage)
- [Appendix B. Candidates not carried over](#appendix-b-candidates-not-carried-over)
- [Appendix C. Reproducing the binary checks](#appendix-c-reproducing-the-binary-checks)

## How to read this page

- **Ids are stable.** `OQ-<CAT>-<nn>`. When a question is answered, move it to Appendix A under the same id and update the doc that raised it. Ids are never reused.
- Every entry has five fields: **Question**, **RPC impact** (one line), **Known** (source `File:line` and doc links), **Resolve by** (a concrete action) and **Raised in**.
- "Game.exe" means the Diablo II 1.14d executable. All game code lives there. Module names such as `D2Client` are legacy labels for address ranges inside it ([memory/README.md §2](memory/README.md#2-one-image-legacy-module-names)). VAs assume image base `0x400000` (see [OQ-MEM-04](#oq-mem-04)).
- "Thread **G**" and "thread **W**" follow [events.md §2.1](js-api/events.md#21-threads): G is the game thread that runs a patched call site, W is the thread that owns the game window.
- Ghidra tooling for the disassembly tasks: [ghidra/README.md](ghidra/README.md), `docs/ghidra/D2BSImport.java`, `docs/ghidra/d2bs_symbols.tsv`.

## Summary table

| Id | Category | Question | Resolution method |
|---|---|---|---|
| [OQ-MEM-01](#oq-mem-01) | Memory | Which `D2Ptrs.h`/`Patch.h`/literal addresses are wrong for 1.14d? | Ghidra import of `d2bs_symbols.tsv`; byte dump of every patch site before `InstallPatches` |
| [OQ-MEM-02](#oq-mem-02) | Memory | Are the unmarked conditional and byte-patch sites valid, and what do they replace? | Disassemble each site in Game.exe |
| [OQ-MEM-03](#oq-mem-03) | Memory | What is at 0x4082E0 / 0x40576F, and what was `D2GAME_exit0` meant to do? | Disassemble both VAs |
| [OQ-MEM-04](#oq-mem-04) | Memory | Is Game.exe ever loaded away from 0x400000? | Read the PE header; runtime check under forced ASLR |
| [OQ-MEM-05](#oq-mem-05) | Memory | Which functions contain the patch sites, and what does the `GameDraw` JMP replace? | Disassemble 0x453B30 and the other sites |
| [OQ-MEM-06](#oq-mem-06) | Memory | What do the act-change sites do, and what is `bChangedAct` for? | Disassemble 0x4547B6 / 0x4567EB; trace act changes |
| [OQ-MEM-07](#oq-mem-07) | Memory | Do intercepts leak `EDI` or shift stack arguments into game code? | Disassemble the code after each site and each re-issued callee |
| [OQ-MEM-08](#oq-mem-08) | Memory | Which constant goes with the `ChatPacketRecv` patch? | Disassemble 0x521B20's function |
| [OQ-MEM-09](#oq-mem-09) | Memory | `ret` vs `ret N` and real register inputs of each stub target | Disassemble each target |
| [OQ-MEM-10](#oq-mem-10) | Memory | Argument/register order of `ClickBeltRight_I` | Disassemble 0x498A90; test both orders |
| [OQ-MEM-11](#oq-mem-11) | Memory | Do `Say_I`/`TakeWaypoint_I` frames match the stubs, and is EBX a `MSG*` or `MSG**`? | Disassemble 0x47CBDA / 0x49D0F1 with their prologues |
| [OQ-MEM-12](#oq-mem-12) | Memory | Types and sizes of game buffers and tables (chat buffers, layouts) | Ghidra xrefs and allocation sizes |
| [OQ-MEM-13](#oq-mem-13) | Memory | Which name is right for each aliased address, and which module owns each symbol? | Ghidra review of each alias |
| [OQ-MEM-14](#oq-mem-14) | Memory | Is DEP enforced, and is the `PAGE_READWRITE` patch window safe? | PE `NX_COMPAT` flag; `GetProcessDEPPolicy` |
| [OQ-STR-01](#oq-str-01) | Structs | Which offset is right for each discrepant field that D2BS reads? | Memory dump in game and at the menu |
| [OQ-STR-02](#oq-str-02) | Structs | Which offset is right for unread fields that disagree with `MPQStats.h`, and should they be fixed or removed? | Data-table dump; owner decision |
| [OQ-STR-03](#oq-str-03) | Structs | Which build does the `pListNext` "0xE4 -> 0xD8" comment refer to? | Compare 1.13d/1.14d layouts |
| [OQ-STR-04](#oq-str-04) | Structs | Layouts not declared at all (`MpqTable`, rest of `sgptDataTable`, missile/tile unions, placeholder regions) | Ghidra structure recovery |
| [OQ-STR-05](#oq-str-05) | Structs | `Control.dwDisabled`/`unkState` values; contents of `+0x5C`/`+0x260` on non-edit controls | Dump control lists on each menu screen |
| [OQ-STR-06](#oq-str-06) | Structs | Meaning and units of roster, room and collision-map fields | Runtime correlation with known positions |
| [OQ-STR-07](#oq-str-07) | Structs | Meaning of `UnitAny.dwOwnerId`/`dwOwnerType` per unit type | Runtime dump per unit type |
| [OQ-STR-08](#oq-str-08) | Structs | Item location fields and when `pOwnerInventory` is set | Runtime dump across all item locations |
| [OQ-GAME-01](#oq-game-01) | Game logic | Are unit ids reused within one game? | Long-session id logging |
| [OQ-GAME-02](#oq-game-02) | Game logic | Where are new units inserted in a hash bucket chain? | Disassemble the unit-add routine |
| [OQ-GAME-03](#oq-game-03) | Game logic | `GetStatList`'s 0x40 argument and `StatList.dwFlags` bit 31 | Disassemble `D2COMMON_GetStatList` (0x6257D0) |
| [OQ-GAME-04](#oq-game-04) | Game logic | Are monster stats 6/7 real or scaled client-side? | Compare with packet data on known monsters |
| [OQ-GAME-05](#oq-game-05) | Game logic | Does `D2GAME_Rand` advance the player's seed in place? | Disassemble; read `dwSeed` around `rand()` |
| [OQ-GAME-06](#oq-game-06) | Game logic | Are the data tables and MPQ VAs valid at the menu? | Runtime read at the main menu |
| [OQ-GAME-07](#oq-game-07) | Game logic | What do `GetLocaleText`, `GetItemMagicalMods(0)` and `GetLevel(0)` return? | Runtime calls with edge ids |
| [OQ-GAME-08](#oq-game-08) | Game logic | Which game functions and globals are safe out of game? | Call each at the menu under a debugger |
| [OQ-GAME-09](#oq-game-09) | Game logic | Which game states make `ClientState()` return busy? | Log `ClientState()` across loads and act changes |
| [OQ-GAME-10](#oq-game-10) | Game logic | Semantics of `AddRoomData`/`RemoveRoomData`, `InitLevel`, `InitAutomapLayer` | Disassemble the three routines |
| [OQ-GAME-11](#oq-game-11) | Game logic | When are `Level`/`Room2`/`RosterUnit`/`Control` objects freed, and who is first in the roster? | Watchpoints on the list heads |
| [OQ-GAME-12](#oq-game-12) | Game logic | How does game pathing interpret the collision bits? | Disassemble the pathing collision checks |
| [OQ-GAME-13](#oq-game-13) | Game logic | Does the game free a replaced `pOMsg`? | Heap trace around `overhead()` |
| [OQ-GAME-14](#oq-game-14) | Game logic | How many states does 1.14d define? | Read `states.txt` record count |
| [OQ-GAME-15](#oq-game-15) | Game logic | Which units does `AssignPlayer_I` assign? | Log `playerassign` with several players in game |
| [OQ-GAME-16](#oq-game-16) | Game logic | How does `D2WIN_InitMPQ` resolve paths, and what are its arguments? | Disassemble 0x517332 |
| [OQ-GAME-17](#oq-game-17) | Game logic | What does the command-line overwrite do to 1.14d, and why is it there? | Disassemble the command-line parser; runtime test |
| [OQ-NET-01](#oq-net-01) | Network | Do `getPacket` injections reach the 0x45F802 hook? | Breakpoint on 0x45F802 during `getPacket` |
| [OQ-NET-02](#oq-net-02) | Network | Do `SendGamePacket_I` and `ShopAction` go through `D2NET_SendPacket`? | Disassemble 0x478350 and the shop routine |
| [OQ-NET-03](#oq-net-03) | Network | Is the send hook at +0xA reached on every path, and what is `arg1`? | Disassemble `D2NET_SendPacket` (0x52AE50) |
| [OQ-NET-04](#oq-net-04) | Network | What exactly does `realmpacket` receive? | Capture MCP traffic and compare |
| [OQ-NET-05](#oq-net-05) | Network | Do whispers fire twice (packet 0x26; whisper hook plus BNCS 0x04)? | Runtime: send whispers in game and in channel |
| [OQ-NET-06](#oq-net-06) | Network | Do `melife`/`memana` equal `me.hp`/`me.mp`? | Runtime comparison |
| [OQ-UI-01](#oq-ui-01) | UI & input | Font indices, text colour indices and `\n` in `D2WIN_DrawText` | Draw each index; disassemble `DrawText` |
| [OQ-UI-02](#oq-ui-02) | UI & input | `dwTrans` and `dwColor` semantics of rectangle/line drawing | Draw each value |
| [OQ-UI-03](#oq-ui-03) | UI & input | Is `DrawAutomapCell2`'s `ypos` the cell's top or bottom? | Draw a known DC6 at a known point |
| [OQ-UI-04](#oq-ui-04) | UI & input | Does `D2CMP_InitCellFile` work in place or allocate? | Disassemble `InitCellFile` |
| [OQ-UI-05](#oq-ui-05) | UI & input | Are the 1.13-era UI flag numbers right for 1.14d? | Toggle each panel and read the UI vars |
| [OQ-UI-06](#oq-ui-06) | UI & input | Undocumented mode values (gold, party buttons, map clicks, cursor types, shop 6) | Disassemble the consumers; runtime trials |
| [OQ-UI-07](#oq-ui-07) | UI & input | What do byte 0x7BCBE8 and the `SelectedInvItem` write control? | Disassemble `LoadItemDesc`; observe UI |
| [OQ-UI-08](#oq-ui-08) | UI & input | Does `say()`'s injected line pass through the `GameInput` hook? | Breakpoint on 0x47C89D during `say()` |
| [OQ-UI-09](#oq-ui-09) | UI & input | Does D2 hit-test posted clicks from `lParam` or from the cursor? | Post a click with the cursor elsewhere |
| [OQ-OOG-01](#oq-oog-01) | Out-of-game | Which BnetData field is the long realm name? | Log both fields on each realm |
| [OQ-OOG-02](#oq-oog-02) | Out-of-game | When is `*p_D2LAUNCH_BnData` NULL? | Read it in single player, at the menu and after login |
| [OQ-OOG-03](#oq-oog-03) | Out-of-game | Do the hard-coded menu geometry and control order match 1.14d? | Dump control lists per screen |
| [OQ-OOG-04](#oq-oog-04) | Out-of-game | Actual strings of the locale ids used by `getLocation` | Read the 1.14d string tables |
| [OQ-OOG-05](#oq-oog-05) | Out-of-game | Is `D2WIN_SetControlText` safe off the UI thread and on non-edit controls? | Disassemble; stress test |
| [OQ-OOG-06](#oq-oog-06) | Out-of-game | Is BNCS chat event 0x0A an incoming or an outgoing whisper? | Capture `SID_CHATEVENT` while whispering |
| [OQ-OOG-07](#oq-oog-07) | Out-of-game | How does the game encode non-ASCII names? | Use a non-ASCII account/character name |
| [OQ-THR-01](#oq-thr-01) | Threading | Which OS thread runs each patched call site? | Log `GetCurrentThreadId()` in every intercept |
| [OQ-THR-02](#oq-thr-02) | Threading | Does `TimerProc` ever fire, and is `dwGameThreadId` ever set? | Log `SetTimer` result and `TimerProc` calls |
| [OQ-THR-03](#oq-thr-03) | Threading | Which thread services the DDE server? | Runtime DDE connect under each loader |
| [OQ-THR-04](#oq-thr-04) | Threading | How often do the shared-`eventSignal` races fire? | Multi-script stress test under page heap |
| [OQ-THR-05](#oq-thr-05) | Threading | Do the lifecycle races (missed join, 0x1337 spin, console dangling) occur in practice? | Scripted join/leave and shutdown tests |
| [OQ-THR-06](#oq-thr-06) | Threading | How large are the TOCTOU windows on game lists read from script threads? | Stress test in menus and loading screens |
| [OQ-THR-07](#oq-thr-07) | Threading | Which game functions are safe to call off the main thread? | Ghidra audit of shared state; worker-thread stress tests |
| [OQ-SM-01](#oq-sm-01) | SpiderMonkey | Are native `argv` slots padded to `nargs`? | Runtime test, or `js::Invoke` in mozilla-release 22 |
| [OQ-SM-02](#oq-sm-02) | SpiderMonkey | What does a native (or `new`) yield when rval is never set? | Runtime `typeof` tests |
| [OQ-SM-03](#oq-sm-03) | SpiderMonkey | What happens after `JS_ReportError` + `return JS_TRUE`? | Runtime test; `jscntxt.cpp` |
| [OQ-SM-04](#oq-sm-04) | SpiderMonkey | Fate of exceptions left pending by handlers; can the operation callback re-enter? | Runtime test; `js_InvokeOperationCallback` source |
| [OQ-SM-05](#oq-sm-05) | SpiderMonkey | Structured-clone failure behaviour on sender and receiver | Runtime test; `jsclone.cpp` |
| [OQ-SM-06](#oq-sm-06) | SpiderMonkey | Slot semantics of non-`JSPROP_SHARED` native accessors | Runtime test; `js_NativeGet`/`js_NativeSet` source |
| [OQ-SM-07](#oq-sm-07) | SpiderMonkey | Which default proto does `JS_NewObject(proto=NULL)` pick, and which receiver do inherited getters see? | `instanceof` test; `FindProto` source |
| [OQ-SM-08](#oq-sm-08) | SpiderMonkey | Does `JS_ConvertArguments` `W` write back into `argv`? | Disassemble `JS_ConvertArgumentsVA` |
| [OQ-SM-09](#oq-sm-09) | SpiderMonkey | Are interned atoms pinned until runtime destruction? | `MarkAtoms` in `jsatom.cpp`; memory test |
| [OQ-SM-10](#oq-sm-10) | SpiderMonkey | Order of GC and `contextCallback` in `JS_DestroyContext`; is everything finalized? | Disassemble `js::DestroyContext`; finalizer logging |
| [OQ-SM-11](#oq-sm-11) | SpiderMonkey | Is one runtime per thread safe without `JS_THREADSAFE`? | Audit process-global state in the engine source |
| [OQ-SM-12](#oq-sm-12) | SpiderMonkey | What does `JS_New(cx, NULL, …)` do? | Disassemble `JS_New`/`InvokeConstructor` |
| [OQ-SM-13](#oq-sm-13) | SpiderMonkey | Does `JS_TypeOfValue(null)` return `JSTYPE_OBJECT`? | Disassemble `js::TypeOfValue` |
| [OQ-SM-14](#oq-sm-14) | SpiderMonkey | How does SpiderMonkey's printf handle `%ls`? | Read `jsprf.cpp`; runtime test |
| [OQ-SM-15](#oq-sm-15) | SpiderMonkey | Do scripts run interpreted, and at what cost? | Benchmark with and without the JIT bits |
| [OQ-SM-16](#oq-sm-16) | SpiderMonkey | What does an out-of-range `JS_SetElement` on a typed array do? | Runtime test |
| [OQ-WIN-01](#oq-win-01) | Windows/CRT | Do thread hooks see posted input, and what does `MOUSEHOOKSTRUCT.pt` hold? | Runtime test with `sendKey`/`sendClick` |
| [OQ-WIN-02](#oq-win-02) | Windows/CRT | Does `SetClipboardData` work after `OpenClipboard(NULL)`? | Runtime test of `copy()` |
| [OQ-WIN-03](#oq-win-03) | Windows/CRT | Do periodic waitable-timer APCs coalesce? | Runtime test with a busy script |
| [OQ-WIN-04](#oq-win-04) | Windows/CRT | Do SHA-2 hashes work with `PROV_RSA_FULL`? | Runtime test on target Windows versions |
| [OQ-WIN-05](#oq-win-05) | Windows/CRT | Do unhandled exceptions in script threads kill the process? | Runtime: compile error in `load()`, `new Sandbox()` |
| [OQ-WIN-06](#oq-win-06) | Windows/CRT | What does MSVCR100 `free()` do with a non-heap pointer? | Runtime under page heap |
| [OQ-WIN-07](#oq-win-07) | Windows/CRT | `_SH_SECURE` sharing and `FileTools.copy` onto itself | Runtime test with the linked CRT |
| [OQ-WIN-08](#oq-win-08) | Windows/CRT | Can D2BS's extra `WSACleanup` calls break the game's sockets? | Runtime test with sockets open in a realm game |
| [OQ-WIN-09](#oq-win-09) | Windows/CRT | Does `InternetReadFile` zero the byte count on failure? | Runtime test with the network blocked |
| [OQ-EXT-01](#oq-ext-01) | External | Which `copydata`/DDE codes and payloads do managers use? | Inspect D2Bot-style manager and script-library source |
| [OQ-EXT-02](#oq-ext-02) | External | Which loader injects D2BS into 1.14d, and how? | Decompile the bundled loaders; inspect current loaders |
| [OQ-EXT-03](#oq-ext-03) | External | Do script libraries rely on dead features (`onHover`, `Sandbox`, DDE)? | Grep the script libraries |
| [OQ-EXT-04](#oq-ext-04) | External | Is the `getIP` endpoint still alive? | HTTP probe from a user machine |
| [OQ-BLD-01](#oq-bld-01) | Build | Which configuration and toolset produce the deployed `D2BS.dll`? | Ask the owner; inspect a shipped DLL |
| [OQ-BLD-02](#oq-bld-02) | Build | Do the headers match the `build-unsafe` lib, and where is Packaging's `mozjs.lib`? | Rebuild mozilla-release 22 with the same config |
| [OQ-BLD-03](#oq-bld-03) | Build | Facts visible only in the compiled `D2BS.dll` (store widths, `PUSHF`, `abs` overload) | Build with v100 and disassemble |
| [OQ-BLD-04](#oq-bld-04) | Build | Open choices in the Ghidra import tooling | Run against a real Ghidra install; owner decision |
| [OQ-BLD-05](#oq-bld-05) | Build | How does `D2BSImport.java` behave inside a real Ghidra install and on the real Game.exe? | `dry-run` then a real run, GUI and `analyzeHeadless`, on 10.x/11.x/12.x |
| [OQ-BLD-06](#oq-bld-06) | Build | Should register-ABI `_I`/`_II` entry points be imported as functions instead of labels? | Disassemble each entry; generator/importer owner decision |
| [OQ-INT-01](#oq-int-01) | Intent | Is `pack(1)` on the non-network structs intended? | Owner decision |
| [OQ-INT-02](#oq-int-02) | Intent | Keep, fix or drop `Sandbox`? | Owner decision |
| [OQ-INT-03](#oq-int-03) | Intent | Was `-ftj` (FailToJoin) meant to be dropped? | Owner decision; git history |
| [OQ-INT-04](#oq-int-04) | Intent | Which legacy-documented behaviours should the RPC API keep? | Owner decision |

---

## 1. Game memory & offsets (MEM)

### OQ-MEM-01

**Unverified 1.14d addresses.**

- **Question:** Which `D2Ptrs.h`, `Patch.h` and hard-coded literal addresses are wrong for Game.exe 1.14d?
- **RPC impact:** every RPC method that reads game memory or calls game code inherits these addresses. A stale one crashes the client or silently corrupts state.
- **Known:** no address in the repo has been checked against a 1.14d binary. The status flags grade only the source's own evidence ([offsets.md §1](memory/offsets.md#1-reading-the-tables), [§3](memory/offsets.md#3-stale-and-suspect-entries-what-depends-on-them)). Highest risk:
  - `RealmPacketRecv_Interception` at VA 0x0044B1AE has no 1.14d marker and is installed unconditionally (`Patch.h:39`). Expected original bytes are `85 F6 74 02 FF D6` ([patches-and-hooks.md §4](memory/patches-and-hooks.md#4-displaced-instructions-and-expected-original-bytes)). If they differ, the patch corrupts code.
  - `D2COMMON_GetMissileOwnerUnit` has only a VA comment (`D2Ptrs.h:344`).
  - The MPQ table absolute VAs ([offsets.md §6.1](memory/offsets.md#61-mpqstatscpp-basestattable)).
  - The item-description literals 0x7BCBE8, 0x7BCBF4 and 0x841EC8 (`JSUnit.cpp:453-458`).
  - 1.13-era ASMPTRs, reached only from dead stubs (`D2Ptrs.h:240`, `:245`, `:248`, `:273`).
- **Resolve by:** importing `docs/ghidra/d2bs_symbols.tsv` into a Game.exe 1.14d project with `D2BSImport.java` ([ghidra/README.md](ghidra/README.md)) and reviewing each row. For patch sites, also break before `InstallPatches()` (`D2BS.cpp:133`), dump the bytes at each VA and compare them with patches-and-hooks.md §4.
- **Raised in:** [offsets.md §10](memory/offsets.md#10-open-questions), [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), [events.md §15](js-api/events.md#15-open-questions) item 4, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 5.

### OQ-MEM-02

**Conditional sites and byte patches.**

- **Question:** Are the unmarked `Conditional[]` sites valid in 1.14d? What original bytes, and so what game behaviour, do the byte patches replace?
- **RPC impact:** these back launch options (`-multi`, `-cachefix`, `-sleepy`, raw CD keys) that a manager will want to keep. An invalid site corrupts code only when its flag is set, so the damage is easy to miss.
- **Known:** `FailToJoin` 0x44EF28, `Multi` 0x4F5623, `Windowname` 0x4F5831, `CacheFix` 0x51944E/0x519434, Sleep 0x451C31 (`90 90`) and OOG Sleep 0x4FA66F (`EB`) carry no "Updated 1.14d" marker (`Patch.h:50-56`). It is also unknown what the `C3` at 0x00468770 disables and what the original byte at 0x0044EBFB was (`Patch.h:15-16`). [patches-and-hooks.md §7](memory/patches-and-hooks.md#7-conditional-patches-and-their-flags) has the flag mapping.
- **Resolve by:** disassembling each VA in Game.exe 1.14d. For the byte patches, identify the instruction overwritten and its branch targets.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), [offsets.md §10](memory/offsets.md#10-open-questions).

### OQ-MEM-03

**`D2GAME_exit0` and the Fog patch site.**

- **Question:** What code sits at VA 0x004082E0 (the Fog patch site) and at 0x0040576F (the intended `D2GAME_exit0` target)? What was the patch meant to achieve?
- **RPC impact:** this decides whether next-gen keeps an "exit quietly instead of the crash/exit path" patch, and which routine it has to hook.
- **Known:** the installed JMP goes to 0x00576F06, because `Patch.h:42` copies the still-encoded `DLLOFFSET` value before `DefineOffsets()` runs (`D2Ptrs.h:40-43`, `D2BS.cpp:132`; [memory/README.md §5.1](memory/README.md#51-static-initialisers-see-encoded-values-bug), [patches-and-hooks.md §2.6](memory/patches-and-hooks.md#26-the-d2game_exit0-static-initialisation-bug)). Nothing in the source shows whether `D2GAME_exit0` returns.
- **Resolve by:** disassembling both VAs. At runtime, drive the Fog error path once with the patch corrected and once without it.
- **Raised in:** [offsets.md §10](memory/offsets.md#10-open-questions), [memory/README.md §11](memory/README.md#11-open-questions), [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-MEM-04

**Image base.**

- **Question:** Is Game.exe 1.14d ever loaded at a base other than 0x400000?
- **RPC impact:** low for the code, which rebases every address onto `GetModuleHandle(NULL)` (`Offset.cpp:21-28`; the absolute literals at `MPQStats.cpp:45`, `:50` and `JSUnit.cpp:453-458` subtract 0x400000 first; the `D2GAME_exit0` jump target is wrong at any base, [OQ-MEM-03](#oq-mem-03)). VA-based tooling (the `-BASE` comments, these docs' VA columns, the Ghidra importer) assumes 0x400000.
- **Known:** the VA comments assume 0x400000, and so does the Ghidra importer (`D2BSImport.java`, `EXPECTED_IMAGE_BASE`). D2BS.dll itself is linked without ASLR ([architecture.md §10.1](architecture.md#101-solution-and-project)).
- **Resolve by:** reading Game.exe 1.14d's PE header (`DllCharacteristics` `DYNAMIC_BASE`, presence of a `.reloc` section). At runtime, compare `GetModuleHandle(NULL)` with mandatory ASLR forced through Windows Exploit Protection.
- **Raised in:** [memory/README.md §11](memory/README.md#11-open-questions); agent report for offsets.md.

### OQ-MEM-05

**Enclosing functions of the patch sites; the `GameDraw` site.**

- **Question:** Which game function contains each patch site? Is 0x00453B30 a function entry that takes no stack arguments, and which routine does the `GameDraw` JMP replace?
- **RPC impact:** this decides whether in-game overlays paint above or below the game's UI panels, and whether the replaced routine did work that an RPC-era hook must keep.
- **Known:** `GameDraw_Intercept` is a plain C function that calls `GameDraw()` and returns with `ret` (`D2Intercepts.cpp:71-73`). The original code at the site is never re-executed (`Patch.h:10`; [patches-and-hooks.md §5.2](memory/patches-and-hooks.md#52-gamedraw_intercept--in-game-frame)). If the replaced function takes stack arguments it would need `ret N`.
- **Resolve by:** disassembling 0x453B30 and its callers, and the function around every other site in the patch table.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), [screenhooks.md](js-api/screenhooks.md#open-questions) item 10.

### OQ-MEM-06

**The act-change flag pair.**

- **Question:** What does the game do at 0x004547B6 and 0x004567EB? Which 2-byte instruction does `GameActChange_Intercept` drop, does its `EAX` clobber matter, and what does `bChangedAct` mean in the game's control flow?
- **RPC impact:** act change is a state event an RPC client will subscribe to. If the patch changes game control flow, the replacement must reproduce that change.
- **Known:** the CMP result left by `GameActChange_Intercept` is consumed by game code after it returns ([patches-and-hooks.md §5.13](memory/patches-and-hooks.md#513-gameactchange_intercept--gameactchange2_intercept--act-change-flag)). `bChangedAct` starts FALSE (`D2BS.cpp:126`).
- **Resolve by:** disassembling both sites and the code that consumes the flags. At runtime, trace act transitions (waypoint, portal, quest warp) with and without the patch.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 7, [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-MEM-07

**Register and stack side effects of intercepts.**

- **Question:** `Whisper_Intercept` returns with `EDI` = site + 5. Does the code after 0x00448813 read `EDI` before writing it? The re-issued calls (`D2CLIENT_InputCall_I`, `D2CLIENT_CongratsScreen_I`, `D2MULTI_ChannelInput_I`, the `call esi`/`call edi` dispatch targets, `AssignPlayer_I`) each run one return address deeper than the call they replace. Do any of them read stack arguments?
- **RPC impact:** these intercepts are the event sources the RPC layer will keep. Latent corruption here shows up as random crashes whether or not JS is present.
- **Known:** `Whisper_Intercept` stores `EDI`, pops the return address into `EDI` and resumes with `jmp edi` after `popad` (`D2Intercepts.cpp:106-119`). Stack-depth notes: [patches-and-hooks.md §5.6](memory/patches-and-hooks.md#56-whisper_intercept--channel-whisper-text), §5.7, §5.12, §5.16, and [call-stubs.md §6](memory/call-stubs.md#6-game-calls-made-from-intercepts).
- **Resolve by:** disassembling the instructions after each site and the prologue of each re-issued callee.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-MEM-08

**The constant tied to the `ChatPacketRecv` patch.**

- **Question:** `Patch.h:25` says "this patch needs a constant in ChatPacketRecv_Interception updated also". Is that constant `[ebp + 8]`, the `-4`/`+4` header adjustment, or the `EDI` dispatch register?
- **RPC impact:** if BNCS chat is re-hooked, or the site moves in another build, the dependent constant must move with it.
- **Known:** the stub reads `[ebp + 8]` into EDX, copies EBX into ECX, subtracts 4 from ECX, adds 4 to EDX, and re-issues `call edi` unless the handler blocks (`D2Intercepts.cpp:122-139`). Git history in this clone starts at 2018-12-10 with the stub already in its 1.14d form.
- **Resolve by:** disassembling the function around 0x00521B20 and checking which frame slot and register hold the packet and its length.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-MEM-09

**Calling contracts of the call-stub targets.**

- **Question:** For each stub target, does it return with `ret` or `ret N`? Which registers are real inputs? In particular, is it `ECX` or `EAX` for `D2CLIENT_GetUnitName_I`, `GetUiVar_I` and `SetSelectedUnit_I` (`D2Ptrs.h:247`, `:116`, `:73`)?
- **RPC impact:** the RPC layer will call the same game functions. A wrong contract unbalances the stack.
- **Known:** stack cleanup is inferred from what keeps each stub balanced ([call-stubs.md §5](memory/call-stubs.md#5-register-and-stack-contracts)). Some stubs set both `ECX` and `EAX`.
- **Resolve by:** disassembling each target in Game.exe 1.14d.
- **Raised in:** [call-stubs.md §10](memory/call-stubs.md#10-open-questions), [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-MEM-10

**`ClickBeltRight_I` argument order.**

- **Question:** Which register gets the player and which the inventory in `D2CLIENT_ClickBeltRight_I` (0x00498A90, `D2Ptrs.h:236`)? So which of the two D2BS call sites is right?
- **RPC impact:** belt right-click RPCs must pass the right order.
- **Known:** the stub's parameters are named `pInventory, pPlayer` (`D2Helpers.cpp:810`), the reverse of the macro's `pPlayer, pInventory` (`D2Ptrs.h:502`). `JSGame.cpp:539` follows the stub's names, `JSGame.cpp:648` follows the macro's ([call-stubs.md §9](memory/call-stubs.md#9-problems-found)).
- **Resolve by:** disassembling 0x498A90. At runtime, right-click a belt potion with each order.
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions), [call-stubs.md §10](memory/call-stubs.md#10-open-questions).

### OQ-MEM-11

**Mid-function entry into `Say_I` and `TakeWaypoint_I`.**

- **Question:** Do the functions containing `D2CLIENT_Say_I` (0x0047CBDA) and `D2CLIENT_TakeWaypoint_I` (0x0049D0F1) really use the frames the stubs rebuild (0x110 bytes of locals; a 0x20-byte struct with `EBX=1`, `EDI=0`, `ECX` pushed and `EBP` left pointing at the stub frame)? Does `Say_I` expect a `MSG*` or the `MSG**` that `Say_ASM` actually passes in `EBX`?
- **RPC impact:** `say` and waypoint travel are core RPC commands. Entering a function mid-body with a wrong frame corrupts the stack.
- **Known:** `Say` passes `&aMsg` (a `MSG**`) as `dwPtr`. `Say_ASM` builds a 0x110-byte frame and loads `EBX` from `[EBP+8]`, which is that pointer (`Core.cpp:67-82`, `:107`). See [call-stubs.md §5.4](memory/call-stubs.md#54-say_asm--entering-d2client_say_i-mid-function) and [§5.5](memory/call-stubs.md#55-d2client_takewaypoint--entering-d2client_takewaypoint_i-mid-function).
- **Resolve by:** disassembling the prologues of both containing functions and the uses of `EBX`, `EDI` and `EBP` after each entry point.
- **Raised in:** [call-stubs.md §10](memory/call-stubs.md#10-open-questions), [globals-game.md](js-api/globals-game.md#open-questions).

### OQ-MEM-12

**Types and sizes of game buffers and tables.**

- **Question:** What are the element types and sizes of `D2CLIENT_BodyClickTable`, `D2WIN_ItemDescText` and the `ChatMsg`, `ChatBoxMsg` and `NPCMenu` buffers? Are `D2CLIENT_StoreLayout` and `D2CLIENT_MercLayout` structs, like the other layout globals, or pointers?
- **RPC impact:** these are the bounds for any RPC that writes text into game buffers. `Say` copies a string of any length into `p_D2CLIENT_ChatMsg` (`Core.cpp:96`).
- **Known:** the types come from usage only ([offsets.md §7.1](memory/offsets.md#71-varptr-casts)).
- **Resolve by:** in Ghidra, following the xrefs and the allocation or `.data` sizes. At runtime, inspect the memory around each buffer.
- **Raised in:** [offsets.md §10](memory/offsets.md#10-open-questions), [globals-game.md](js-api/globals-game.md#open-questions).

### OQ-MEM-13

**Aliased addresses and owning modules.**

- **Question:** For each duplicate-address pair, which name matches what the game does? The pairs are `MouseOffsetX/Y` = `ViewportX/Y`, `AutomapMode` = `Divisor`, `GetObjectTxt` = `GetObjectText`, `GetTextSize` = `GetTextWidthFileNo`, `SetEditBoxCallback` = `SetEditBoxProc`, `GetLevelNoFromRoom` = `GetLevelIdFromRoom_I` and `SelectedInvItem` = `ItemDescUnit`. And what is the true owning module of each symbol?
- **RPC impact:** these names become RPC and API vocabulary, and wrong module tokens mislead porting.
- **Known:** the aliases are deliberate in the source ([offsets.md §10](memory/offsets.md#10-open-questions)). Module tokens are unreliable for 1.14d. For example, the `GamePacketSent` patch filed under D2Client sits inside `D2NET_SendPacket` ([memory/README.md §2](memory/README.md#2-one-image-legacy-module-names)).
- **Resolve by:** in Ghidra, comparing each address's function body and callers with the semantics each name implies.
- **Raised in:** [offsets.md §10](memory/offsets.md#10-open-questions), [memory/README.md §11](memory/README.md#11-open-questions).

### OQ-MEM-14

**DEP and live patching.**

- **Question:** Does Game.exe 1.14d run with DEP enforced? Can a game thread execute a page while `WriteBytes` has it at `PAGE_READWRITE`?
- **RPC impact:** if next-gen installs or removes patches at runtime, for example when an RPC toggles a feature, the patching window must be safe.
- **Known:** `WriteBytes` uses `VirtualProtect(..., PAGE_READWRITE, ...)` and suspends no threads (`Offset.cpp:76`; [patches-and-hooks.md §2.5](memory/patches-and-hooks.md#25-thread-safety-and-failure-modes)).
- **Resolve by:** checking the `NX_COMPAT` bit in Game.exe's PE header and the system DEP policy, and calling `GetProcessDEPPolicy` in a running game.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

## 2. Struct layouts & field semantics (STR)

### OQ-STR-01

**Discrepant offsets of fields D2BS reads.**

- **Question:** Where the computed offset and the source comment disagree, which one matches 1.14d?
  - `BnetData.ladderflag`: read at 0x3C2, commented 0x3C0 (`JSUnit.cpp:126`).
  - `Control.wText2`: read at 0x64, commented 0x6C (`Control.cpp:83`).
  - `ItemTxt.xSize`/`ySize`: read at 0x10F/0x110, commented 0xFC/0xFD.
  - `CollMap.pMapEnd`: read at 0x24, commented 0x22.
  - `ObjectTxt.nAutoMap`: read at 0x1BC, commented 0x1BB.
- **RPC impact:** these fields back `me.ladder`, out-of-game button text, item sizes, collision maps and automap flags, all of which the RPC API will expose.
- **Known:** D2BS reads the computed offsets. For the ItemTxt sizes and `nAutoMap`, `MPQStats.h` agrees with the code ([structs.md § Discrepancy summary](memory/structs.md#discrepancy-summary), [§ Cross-check against MPQStats.h](memory/structs.md#cross-check-against-mpqstatsh)).
- **Resolve by:** dumping memory in game and at the menu, or reading each field's consumers in Ghidra.
- **Raised in:** [structs.md](memory/structs.md#open-questions), [unit-properties.md](js-api/unit-properties.md#open-questions) item 5, [out-of-game.md](js-api/out-of-game.md#open-questions) item 4, [world.md](js-api/world.md#open-questions).

### OQ-STR-02

**Unread fields that disagree with `MPQStats.h`.**

- **Question:** What are the right offsets for `ItemTxt.fQuest` (code 0x12C, comment and `MPQStats.h` 0x12A), `LevelTxt.nObjGroup`/`nObjPrb` (code 0x20E/0x216, comment 0x196/0x19E, `MPQStats.h` 0xE5/0xED) and `ObjectTxt.nOrientation`/`nSubClass` (`MPQStats.h` 0x13C/0x167)? Should they be corrected or removed?
- **RPC impact:** none today, since D2BS never reads them. They become live bugs the moment an RPC method exposes them.
- **Known:** [structs.md § Open questions](memory/structs.md#open-questions).
- **Resolve by:** dumping the records from the 1.14d data tables. Correcting or removing them is the owner's call.
- **Raised in:** [structs.md](memory/structs.md#open-questions).

### OQ-STR-03

**The `UnitAny.pListNext` comment.**

- **Question:** The comment reads `0xE4 -> 0xD8`. Which game version uses 0xD8?
- **RPC impact:** low. It matters only when porting to another build.
- **Known:** D2BS walks the unit hash tables through 0xE4 (`Unit.cpp:32`).
- **Resolve by:** comparing 1.13d and 1.14d layouts in a dump or in Ghidra.
- **Raised in:** [structs.md](memory/structs.md#open-questions).

### OQ-STR-04

**Layouts that are not declared at all.**

- **Question:** What are the layouts of `MpqTable` (only forward-declared) and of `sgptDataTable` beyond its first 7 members? Where are the `UnitAny` union member for missiles (dwType 3) and the path-union member for tiles? What fills the placeholder regions (`_1`, `_2a`, `unk…`)?
- **RPC impact:** this caps what an RPC "unit/data inspector" can expose safely.
- **Known:** the code treats the data-table global as a plain DWORD. Placeholder coverage per struct: [structs.md § Partially known structs](memory/structs.md#partially-known-structs).
- **Resolve by:** recovering the structures in Ghidra from their consumers, then cross-checking against a memory dump.
- **Raised in:** [structs.md](memory/structs.md#open-questions).

### OQ-STR-05

**Control state fields.**

- **Question:** What do `Control.dwDisabled` and `unkState` values mean, and why is `state = dwDisabled - 2`? What lives at `Control+0x5C` and `+0x260` on non-edit controls, which `text` and `password` read for any control type?
- **RPC impact:** the out-of-game RPC surface (`getControl`, `click`, `setText`) depends on telling enabled controls from disabled ones and text fields from others.
- **Known:** the code implies only `0x0d` (clickable single-player difficulty) and `0x4` (unavailable create-character radio button) ([out-of-game.md](js-api/out-of-game.md#open-questions) items 5, 11).
- **Resolve by:** dumping every control on each menu screen in each state at runtime.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions).

### OQ-STR-06

**Roster, room and collision-map fields.**

- **Question:** What do `RosterUnit.dwPartyFlags`, `dwPartyLife` (scale) and `Xpos`/`Ypos` mean, and what is `Room2.pType2Info->dwRoomNumber`? In what units are `Room1.dwXStart`/`dwYStart`/`dwXSize`/`dwYSize` and `CollMap.dwPosRoomX`/`dwPosRoomY`/`dwSizeRoomX`/`dwSizeRoomY` (`getStat` 0-3, 13-16)?
- **RPC impact:** party and room RPCs need documented units.
- **Known:** no arithmetic in D2BS uses them, so the source gives no hint of their units ([world.md § Coordinate systems](js-api/world.md#coordinate-systems)).
- **Resolve by:** correlating the values with known player and room positions at runtime.
- **Raised in:** [world.md](js-api/world.md#open-questions).

### OQ-STR-07

**`UnitAny.dwOwnerId` / `dwOwnerType`.**

- **Question:** What do `dwOwnerId` (+0x98) and `dwOwnerType` (+0x94) mean for each unit type?
- **RPC impact:** they are exposed as `owner`/`ownertype`. An RPC schema needs their semantics, or should drop them.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 10.
- **Resolve by:** dumping both fields for players, monsters, summons, missiles, items and objects at runtime.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions).

### OQ-STR-08

**Item location fields and `pOwnerInventory`.**

- **Question:** Which values does `ItemData.ItemLocation` (+0x45) take, and how do they map to `GameLocation` (+0x68) and `NodePage` (+0x69)? For which items is `pOwnerInventory` set: all inventory items, or only socketed ones as its comment says? Which items does the game link into an inventory's list, and do `Inventory.pFirstItem` and `D2COMMON_GetItemFromInventory` always agree?
- **RPC impact:** inventory enumeration, `getParent`, `shop` ownership checks and item descriptions all depend on this.
- **Known:** the struct comments say "Body/Belt == 0xFF" (`D2Structs.h:494`), "Socketed Items owner Inv" (`D2Structs.h:499`) and NodePage is "the most reliable by far" (`D2Structs.h:503`). The description getter returns nothing when `pOwnerInventory` is NULL (`JSUnit.cpp:452`).
- **Resolve by:** dumping these fields at runtime for items equipped, in the belt, inventory, stash and cube, on the cursor, socketed and on the ground.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions), agent report for unit-properties.md.

## 3. Game logic & data semantics (GAME)

### OQ-GAME-01

**Unit id reuse.**

- **Question:** Does 1.14d reuse `dwUnitId` values within one game, for example for monsters or items after they are removed?
- **RPC impact:** RPC unit handles will be `(type, id)` pairs. Reuse means a stale handle can silently alias another unit.
- **Known:** resolution is by `(id, type)` only ([unit-properties.md § Identity, resolution and lifetime](js-api/unit-properties.md#identity-resolution-and-lifetime)).
- **Resolve by:** logging every id assigned during a long session, for example several full clears.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 3, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 7.

### OQ-GAME-02

**Hash bucket order.**

- **Question:** Where does the game insert new units in a unit hash bucket chain?
- **RPC impact:** this decides whether unit enumeration order is stable between calls.
- **Known:** `getNext` walks buckets in index order and chains through `pListNext` ([unit-methods.md § getNext walk order](js-api/unit-methods.md#getnext-walk-order-getnextunitfromtables-unitcpp99-137)).
- **Resolve by:** disassembling the unit-add routine.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-GAME-03

**Stat-list internals.**

- **Question:** What does the `0x40` argument of `D2COMMON_GetStatList` mean (declared `dwMaxEntries`, `D2Ptrs.h:304`)? Can the list it returns be the same as `UnitAny.pStats`, which would duplicate skill-encoded entries in `getStat(-2)`? What does `StatList.dwFlags` bit 31 mean? It gates `SetStatVec`.
- **RPC impact:** stats are the most-read data. Duplicates or a wrong vector would corrupt RPC stat snapshots.
- **Known:** [unit-methods.md](js-api/unit-methods.md#open-questions).
- **Resolve by:** disassembling `D2COMMON_GetStatList` (0x006257D0) and the code that sets bit 31.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-GAME-04

**Client-side monster HP.**

- **Question:** For monsters the client does not own, are stats 6/7 (`hp`/`hpmax`) real values or scaled approximations?
- **RPC impact:** health thresholds in client logic built on the RPC API.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 9.
- **Resolve by:** comparing the stats with the monster life byte in the server packets for known monsters.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions).

### OQ-GAME-05

**`rand()` and the player seed.**

- **Question:** Does `D2GAME_Rand(DWORD* seed)` advance `player->dwSeed` (UnitAny+0x20) in place, so that every JS `rand()` call mutates the client's RNG state?
- **RPC impact:** an RPC `rand` should not perturb game state. If it does, it must be replaced by a host-side RNG.
- **Known:** [globals-game.md](js-api/globals-game.md#open-questions).
- **Resolve by:** disassembling `D2GAME_Rand`, or reading `dwSeed` before and after a `rand()` call at runtime.
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions).

### OQ-GAME-06

**Data tables out of game.**

- **Question:** Is `*p_D2COMMON_sgptDataTable` populated at the menu, and are the absolute MPQ VAs valid there?
- **RPC impact:** this decides whether data-table RPCs (`getBaseStat`, `getSkillById`) can be served before login.
- **Known:** neither native checks the game state ([globals-game.md](js-api/globals-game.md#open-questions)).
- **Resolve by:** reading the pointer and a known record at the main menu, before any game has been joined.
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions).

### OQ-GAME-07

**Return values for edge ids.**

- **Question:** What does `D2LANG_GetLocaleText` return for unknown ids? What does `D2COMMON_GetItemMagicalMods(0)` return, NULL or a real affix name? Does any level have `dwLevelNo == 0`?
- **RPC impact:** non-magic items may get a bogus `prefix`/`suffix` (`JSUnit.cpp:320`, `:342`), and `getArea(0)` may misbehave.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 12, [globals-game.md](js-api/globals-game.md#open-questions), [world.md § getArea](js-api/world.md#getareaarea).
- **Resolve by:** calling each function with the edge id at runtime.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions), [globals-game.md](js-api/globals-game.md#open-questions), [world.md](js-api/world.md#open-questions).

### OQ-GAME-08

**Out-of-game safety of game functions and globals.**

- **Question:** Which of these are safe in every client state?
  - `D2CLIENT_GetDifficulty`, `D2CLIENT_GetCursorItem`, `D2CLIENT_GetSelectedUnit` and `D2GFX_GetScreenSize`, called by the `me` getters and by `getUnit(100/101)`.
  - `*p_D2CLIENT_Divisor`: can it be 0 at the menu? `screenToAutomap` divides by it.
  - `D2CLIENT_DrawRectFrame`: why does it crash out of game? `JSScreenHook.cpp:66` gives that crash as the reason `Frame` is forced in-game.
  - `sendPacket`: what does it do out of game?
- **RPC impact:** the RPC layer must gate each method on client state. The gates are only as good as this list.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 8, [unit-methods.md](js-api/unit-methods.md#open-questions), [screenhooks.md](js-api/screenhooks.md#open-questions) items 8 and 11, [globals-core.md § sendPacket](js-api/globals-core.md#sendpacket).
- **Resolve by:** calling each function at the main menu, character select and lobby under a debugger.
- **Raised in:** the docs above.

### OQ-GAME-09

**Busy client states.**

- **Question:** Which game states (loading screens, act transitions) make `ClientState()` return `ClientStateBusy`?
- **RPC impact:** every unit-backed RPC returns nothing in that state, so clients need to know when it happens.
- **Known:** only the struct conditions are visible (`D2Helpers.cpp:130-140`).
- **Resolve by:** logging `ClientState()` every frame across game creation, act changes and exits.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 13.

### OQ-GAME-10

**Room-loading API semantics.**

- **Question:** What does the last `Room1*` argument of `D2COMMON_AddRoomData`/`RemoveRoomData` mean? D2BS passes the player's room, NULL or the room's own `pRoom1` at different sites. Does the game reference-count room loading? Can `D2COMMON_InitLevel` fail for a valid level? What does `InitAutomapLayer` do to `*p_D2CLIENT_AutomapLayer`?
- **RPC impact:** map and reveal RPCs load rooms on demand. Wrong usage leaks or unloads rooms the game itself needs.
- **Known:** `getPresetUnits` can Add/Remove a room the game had already loaded, and `getPresetUnit` leaves a matching room loaded ([world.md § Room loading](js-api/world.md#room-loading-addroomdata--removeroomdata)). The `InitAutomapLayer` effect is inferred from how D2BS uses it.
- **Resolve by:** disassembling the three routines and checking for a load counter on `Room2`.
- **Raised in:** [world.md](js-api/world.md#open-questions).

### OQ-GAME-11

**Lifetimes of game lists.**

- **Question:** When does the game free `Level`/`Room2` lists (act change, game exit), `RosterUnit` entries and menu `Control` objects? Which entry does `*p_D2CLIENT_PlayerUnitList` point to first?
- **RPC impact:** this sets the validity window of every RPC handle to a room, party member or control.
- **Known:** `clickParty` assumes the first roster entry is the local player (`JSGame.cpp:1085`, `:1108`).
- **Resolve by:** hardware watchpoints on the list heads across act changes, game exit and menu transitions.
- **Raised in:** [world.md](js-api/world.md#open-questions), [out-of-game.md](js-api/out-of-game.md#open-questions) item 13.

### OQ-GAME-12

**Collision bits.**

- **Question:** How does the game's own pathing interpret the bits D2BS names in `ActMap::CollisionFlag` (`Map/Diablo_II/ActMap.h:45-66`)? Is `checkFlag`'s `BlockWalk|BlockPlayer` mask enough for 1.14d?
- **RPC impact:** a server-side path API must agree with the game about which tiles are walkable.
- **Known:** the names come from D2BS ([world.md § Collision lookup](js-api/world.md#collision-lookup-actmapgetmapdata)).
- **Resolve by:** disassembling the game's movement and collision checks.
- **Raised in:** [world.md](js-api/world.md#open-questions).

### OQ-GAME-13

**Overhead message ownership.**

- **Question:** Does the game free a unit's previous `pOMsg` when `overhead()` replaces it?
- **RPC impact:** whether an RPC overhead-text method leaks.
- **Known:** [unit-methods.md](js-api/unit-methods.md#open-questions).
- **Resolve by:** a heap trace around repeated `overhead()` calls.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-GAME-14

**State count.**

- **Question:** Is the hard-coded `0..183` range in `getState` right for 1.14d?
- **RPC impact:** this is the bounds check on a state-query RPC.
- **Known:** [unit-methods.md](js-api/unit-methods.md#open-questions).
- **Resolve by:** reading the `states.txt` record count from the 1.14d data table.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-GAME-15

**`playerassign` coverage.**

- **Question:** Which units does `D2CLIENT_AssignPlayer_I` (0x00466200) assign: only the local player, or every player unit?
- **RPC impact:** whether a `playerassign` subscription reports other players joining.
- **Known:** the event fires whenever `AssignPlayer_I` returns a non-NULL unit ([events.md § playerassign](js-api/events.md#playerassign)).
- **Resolve by:** at runtime, log the event while other players join a game.
- **Raised in:** [events.md §15](js-api/events.md#15-open-questions) item 9.

### OQ-GAME-16

**`D2WIN_InitMPQ`.**

- **Question:** Which base directory does `D2WIN_InitMPQ` (0x00517332) resolve a relative path against: the current directory, the game directory or the MPQ search path? What do its arguments `0, 0, 3000` mean (`Core.cpp:182`)?
- **RPC impact:** a `loadMpq` RPC needs path semantics that callers can rely on.
- **Known:** `isValidPath` checks the path against the script folder, but the raw relative path is what reaches the game ([globals-core.md § loadMpq](js-api/globals-core.md#loadmpqpath)).
- **Resolve by:** disassembling 0x517332.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 8.

### OQ-GAME-17

**The command-line overwrite.**

- **Question:** Does Game.exe 1.14d read the wide or the ANSI command line, and has it parsed its switches before D2BS is loaded? What effect does overwriting the process command line with `"C:\Program Files (x86)\Diablo II\Game.exe -w"` have, and why does D2BS do it?
- **RPC impact:** next-gen must decide whether to keep this write, which can overflow the buffer.
- **Known:** `InitCommandLine` copies `sizeof(LPWSTR) * wcslen(cline)` = 4 × 44 = 176 bytes from a 90-byte literal into the buffer returned by `GetCommandLineW()` (`Helpers.cpp:483-488`, called from `D2BS.cpp:45`). Whether that buffer holds 176 bytes depends on how the process was started ([architecture.md §11](architecture.md#11-open-questions) item 4).
- **Resolve by:** disassembling Game.exe's command-line parsing to see when it runs and which API it reads. At runtime, compare game options with and without the overwrite.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 4.

## 4. Network protocol & packet paths (NET)

### OQ-NET-01

**Injected receive packets.**

- **Question:** Does `getPacket()` → `D2NET_ReceivePacket` (0x0052AEB0, `D2Ptrs.h:363`) reach the `GamePacketReceived_Intercept` call site (0x0045F802, `Patch.h:11`)?
- **RPC impact:** if it does, injected packets fire `gamepacket` listeners on the caller's thread and run the 0xAE terminate check. A blocker produced for the same script would then wait out its full 500 ms.
- **Known:** [events.md §15](js-api/events.md#15-open-questions) item 2, [globals-core.md](js-api/globals-core.md#open-questions) item 6.
- **Resolve by:** setting a breakpoint on 0x45F802 and calling `getPacket()`.
- **Raised in:** the docs above, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 4.

### OQ-NET-02

**Send paths and `gamepacketsent`.**

- **Question:** Do `D2CLIENT_SendGamePacket_I` (0x00478350, `D2Ptrs.h:283`; used by `setSkill`, `useStatPoint`, `useSkillPoint`) and `D2CLIENT_ShopAction` send through `D2NET_SendPacket`, and so fire `gamepacketsent`?
- **RPC impact:** if `ShopAction` does, `shop` waits up to 500 ms per foreign listener while it holds `Vars.cGameLoopSection`, because `ReleaseGameLock` only releases on the game thread (`Events.cpp:347-349`).
- **Known:** [unit-methods.md](js-api/unit-methods.md#open-questions), [call-stubs.md §10](memory/call-stubs.md#10-open-questions), [events.md §15](js-api/events.md#15-open-questions) item 3.
- **Resolve by:** disassembling 0x478350 and the shop routine, or breaking in `GamePacketSent_Interception` during each call.
- **Raised in:** the docs above, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 3.

### OQ-NET-03

**Coverage of the send hook.**

- **Question:** Is the patch at 0x0052AE5A, 10 bytes into `D2NET_SendPacket` (0x0052AE50, `Patch.h:12`), reached on every call, or can the function exit before `+0xA`? What does `arg1 = 1` select (`D2Ptrs.h:362`)?
- **RPC impact:** packet-filtering RPCs must see every outgoing packet.
- **Known:** [globals-core.md](js-api/globals-core.md#open-questions) item 7, [patches-and-hooks.md §5.4](memory/patches-and-hooks.md#54-gamepacketsent_interception--client--server-game-packets).
- **Resolve by:** disassembling 0x52AE50.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions).

### OQ-NET-04

**`realmpacket` payload.**

- **Question:** What exactly does `realmpacket` receive? Is the MCP header included, and what does `dwSize` count?
- **RPC impact:** this is the wire format of any realm-packet subscription.
- **Known:** `RealmPacketRecv` passes the buffer and size through unchanged (`D2Handlers.cpp:526-528`). Whether the site itself is valid is part of [OQ-MEM-01](#oq-mem-01).
- **Resolve by:** capturing MCP traffic (a proxy or `WSARecv` logging) and comparing it with the bytes delivered to listeners.
- **Raised in:** [events.md §15](js-api/events.md#15-open-questions) item 4.

### OQ-NET-05

**Duplicate chat and whisper events.**

- **Question:** Do in-game whispers also arrive as packet 0x26, so that one whisper fires both `chatmsg` and `whispermsg`? Does a channel whisper reach both `Whisper_Intercept` (0x00448813) and the `SID_CHATEVENT` 0x04 case of `ChatPacketRecv`, firing `whispermsg` twice?
- **RPC impact:** event de-duplication in the RPC event stream.
- **Known:** `ChatEventHandler` ignores the chat-type byte ([events.md §15](js-api/events.md#15-open-questions) item 5). `ChatPacketRecv` maps 0x04 and 0x0A to `WhisperEvent` (`D2Handlers.cpp:546-549`).
- **Resolve by:** at runtime, whisper the client in game, in a channel and in the lobby, and count events.
- **Raised in:** [events.md §15](js-api/events.md#15-open-questions), [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions).

### OQ-NET-06

**`melife` / `memana` values.**

- **Question:** Do the values decoded from packet 0x95 equal `me.hp`/`me.mp`?
- **RPC impact:** whether a life/mana push event can stand in for polling.
- **Known:** the handler clears bit 15 of life and bits 15 and 14 of mana, then doubles mana (`D2NetHandlers.cpp:26-38`; dispatched for 0x95 at `D2Handlers.cpp:160-161`).
- **Resolve by:** logging both side by side at runtime, including with mana above 16384.
- **Raised in:** [events.md §15](js-api/events.md#15-open-questions) item 7.

## 5. Game UI, input & rendering (UI)

### OQ-UI-01

**Text rendering.**

- **Question:** What is the valid range of `D2WIN_SetTextSize` font indices in 1.14d, and which glyph set does each select? What does each `D2WIN_DrawText` colour index mean, and do the indices match the `ÿc<N>` codes? Does `DrawText` render `\n` as a line break?
- **RPC impact:** an overlay/text RPC needs a documented font and colour domain.
- **Known:** the community convention lists fonts 0-13, unverified ([screenhooks.md § Value domains](js-api/screenhooks.md#value-domains-alignment-colors-fonts-opacity)).
- **Resolve by:** drawing each index at runtime, and disassembling `DrawText`'s handling of control characters.
- **Raised in:** [screenhooks.md](js-api/screenhooks.md#open-questions) items 1, 2, 12.

### OQ-UI-02

**Rectangle and line parameters.**

- **Question:** What does `D2GFX_DrawRectangle`'s `dwTrans` (Box `opacity`) do? Is the `dwColor` of `D2GFX_DrawRectangle`/`D2GFX_DrawLine` an 8-bit palette index, and what do values above 255 do?
- **RPC impact:** validation of overlay draw parameters.
- **Known:** known only empirically (`doc/ScreenHooks.h`). D2BS itself uses colours `0xDF`/`0xFF`.
- **Resolve by:** drawing each value at runtime.
- **Raised in:** [screenhooks.md](js-api/screenhooks.md#open-questions) items 3, 13.

### OQ-UI-03

**Image anchoring.**

- **Question:** Does `D2GFX_DrawAutomapCell2` treat `ypos` as the cell's top or its bottom?
- **RPC impact:** pixel placement of image overlays and their hit boxes.
- **Known:** `myDrawAutomapCell` shifts by `x -= w/2; y += h/2` (`D2Helpers.cpp:585-586`), and its clip test treats `ypos2` as the top (`D2Helpers.cpp:588-589`).
- **Resolve by:** drawing a DC6 of known size at a known point.
- **Raised in:** [screenhooks.md](js-api/screenhooks.md#open-questions) item 4.

### OQ-UI-04

**`D2CMP_InitCellFile` ownership.**

- **Question:** Does `D2CMP_InitCellFile` fix up the DC6 buffer in place, or allocate a new `CellFile` on the game heap?
- **RPC impact:** if it allocates, `SetImage`'s `delete[]` frees game-heap memory and the original buffer leaks. An image-upload RPC needs this right.
- **Known:** [screenhooks.md](js-api/screenhooks.md#open-questions) item 5.
- **Resolve by:** disassembling `InitCellFile`, or comparing the out pointer with the input at runtime.
- **Raised in:** [screenhooks.md](js-api/screenhooks.md#open-questions).

### OQ-UI-05

**UI variable numbering.**

- **Question:** Is the UI flag numbering in `Constants.h:15-54` (1.13-era, "From D2JSP") correct for 1.14d? What does `D2CLIENT_GetUIState(UI_GAME = 0)` mean in `interact`'s waypoint branch? What are the semantics of `D2CLIENT_SetUIVar`'s `howset` argument (1/0 as open/close in `transmute`, `D2Ptrs.h:79`)?
- **RPC impact:** UI-state queries and panel toggles are core RPCs.
- **Known:** [globals-game.md § UI flags](js-api/globals-game.md#ui-flags-getuiflag), [unit-methods.md](js-api/unit-methods.md#open-questions).
- **Resolve by:** opening each panel at runtime and reading the UI vars, and disassembling `SetUIVar` (0x00455F20).
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions), [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-UI-06

**Undocumented mode values.**

- **Question:** What do these values mean?
  - `gold()` modes (`D2CLIENT_GoldDialogAction`, `Game.cpp:8-12`).
  - `clickParty` modes 4/5, i.e. `D2CLIENT_HostilePartyUnit(p, 3/4)` (`JSGame.cpp:1131-1134`).
  - `clickMap` click types 1, 3, 4 and 5. Only 0 and 2 are corroborated in source (`JSUnit.cpp:1893-1895`); the 0-5 table exists only in `resources/api.html`.
  - `getCursorType` values.
  - `shop` mode 6, which appears only as a 0x80 flag byte in dead code.
- **RPC impact:** the RPC schema needs enums, not magic numbers.
- **Known:** [globals-game.md](js-api/globals-game.md#open-questions), [unit-methods.md](js-api/unit-methods.md#open-questions).
- **Resolve by:** disassembling the consumers of each variable, and trying each value at runtime.
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions), [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-UI-07

**The item-description side channel.**

- **Question:** What does the byte at VA 0x7BCBE8 control? The `description` getter sets it to 1 (`JSUnit.cpp:453`). Does leaving `SelectedInvItem` (0x7BCBF4) pointing at the item (`JSUnit.cpp:454`) have visible UI effects?
- **RPC impact:** item descriptions are a likely RPC. If producing one has UI side effects, the RPC needs a different method.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 6.
- **Resolve by:** disassembling `D2CLIENT_LoadItemDesc` and its reads of those globals, and watching the UI while reading descriptions.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions).

### OQ-UI-08

**`say()` and the `GameInput` hook.**

- **Question:** Does the chat line injected by `say()` in game pass through the `GameInput` intercept (0x0047C89D) and so consume `Vars.bDontCatchNextMsg` itself?
- **RPC impact:** whether RPC-sent chat echoes back as a `chatinput` event, and whether the next real user line is swallowed.
- **Known:** `Say` sets `bDontCatchNextMsg = TRUE` before entering `Say_I` (`Core.cpp:93`). The register question is [OQ-MEM-11](#oq-mem-11).
- **Resolve by:** setting a breakpoint on 0x47C89D during `say()`.
- **Raised in:** [globals-game.md](js-api/globals-game.md#open-questions).

### OQ-UI-09

**Game-side hit-testing of posted clicks.**

- **Question:** Do D2's in-game input and D2WIN's menu controls hit-test a posted `WM_LBUTTONDOWN`/`UP` using its `lParam` or the real cursor position?
- **RPC impact:** every synthesized click RPC (menu and in game) works only in the first case. `SendMouseClick` never moves the cursor (`D2Helpers.cpp:305-313`).
- **Known:** [out-of-game.md § Input synthesis](js-api/out-of-game.md#input-synthesis-clickcontrol), [out-of-game.md](js-api/out-of-game.md#open-questions) item 12, [globals-core.md](js-api/globals-core.md#open-questions) item 10.
- **Resolve by:** at runtime, posting a click on a control with the cursor parked elsewhere.
- **Raised in:** the docs above, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 8.

## 6. Out-of-game, Battle.net & realm flows (OOG)

### OQ-OOG-01

**Realm name fields.**

- **Question:** Which of `BnetData.szRealmName` (+0xD5, 8 bytes) and `szRealmName2` (+0x22D, 24 bytes) holds the long realm name, and which the short one?
- **RPC impact:** realm identification in RPC session info.
- **Known:** the code maps `realm` to the first field and `realmshort` to the second. The legacy docs say `realm` is the long name ([unit-properties.md](js-api/unit-properties.md#open-questions) item 4).
- **Resolve by:** logging both fields on each realm at runtime.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions).

### OQ-OOG-02

**When BnData is NULL.**

- **Question:** When is `*p_D2LAUNCH_BnData` NULL: in single player, before the first login, or never?
- **RPC impact:** `maxdiff`, `realm` and `realmshort` dereference it without a check, so it decides which RPC session fields are safe.
- **Known:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 7.
- **Resolve by:** reading the pointer in single player, at the main menu, after login and after logout.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions).

### OQ-OOG-03

**Menu geometry and control order.**

- **Question:** Do the hard-coded menu coordinates in `Control.cpp`/`Profile.cpp`, none tagged "Updated 1.14d", still match the 1.14d menus? Does `OOG_SelectCharacter`'s start control `(237, 178, 72, 93)` precede every character slot in D2WIN's control list?
- **RPC impact:** the login and lobby RPCs are built on these probes.
- **Known:** [out-of-game.md § Hard-coded UI geometry](js-api/out-of-game.md#hard-coded-ui-geometry-all-callers), [out-of-game.md](js-api/out-of-game.md#open-questions) items 6, 10.
- **Resolve by:** dumping the control list on each menu screen at runtime and diffing it against the constants.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions).

### OQ-OOG-04

**Locale ids used for location detection.**

- **Question:** What are the actual strings of locale ids 5116, 5118, 5119, 5138, 5139, 5159, 5161, 5181, 5200, 5226, 5243, 5288, 5347, 5351, 11065, 11066, 11097, 11162 and 21882?
- **RPC impact:** this documents the out-of-game location enum.
- **Known:** they are interpreted only through the location they map to ([out-of-game.md](js-api/out-of-game.md#open-questions) item 9).
- **Resolve by:** reading the 1.14d string tables (`.tbl`), or calling `D2LANG_GetLocaleText` for each id.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions).

### OQ-OOG-05

**`D2WIN_SetControlText` off the UI thread.**

- **Question:** Is calling `D2WIN_SetControlText` from a script thread safe? What does it do to non-edit controls, given that `Control.setText` accepts any control type?
- **RPC impact:** RPC text entry will run off the UI thread unless it is marshalled.
- **Known:** [out-of-game.md](js-api/out-of-game.md#open-questions) item 8.
- **Resolve by:** disassembling the routine for shared state, and stress-testing `setText` while the menu redraws.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions).

### OQ-OOG-06

**BNCS chat event 0x0A.**

- **Question:** Is `SID_CHATEVENT` event id 0x0A, mapped to `whispermsg` together with 0x04 (`D2Handlers.cpp:546-549`), an incoming or an outgoing whisper?
- **RPC impact:** if it is the echo of the client's own whisper, `whispermsg` currently reports sent whispers as received.
- **Known:** the source comment only says "whispers". Public BNCS protocol documentation (for example BNETDocs) lists 0x04 as `EID_WHISPER` and 0x0A as `EID_WHISPERSENT`. That cannot be verified from this repository.
- **Resolve by:** capturing BNCS traffic while sending and receiving a whisper in a channel.
- **Raised in:** [events.md §15](js-api/events.md#15-open-questions) item 12.

### OQ-OOG-07

**Encoding of non-ASCII names.**

- **Question:** How does the game store account, character and game names that contain non-ASCII characters: UTF-8, or the ANSI code page?
- **RPC impact:** RPC strings will be UTF-8. Lookups such as `getParty(name)` compare UTF-8 against the game's bytes (`JSParty.cpp:100`), and whispers are decoded with `CP_ACP` ([architecture.md §2.2](architecture.md#22-entry-points-on-game-threads-hooks-intercepts-window-procedure)).
- **Known:** non-ASCII names match only if the game also stores UTF-8 ([world.md § getParty](js-api/world.md#getpartyname--gid--unit)).
- **Resolve by:** at runtime, using an account or character with a non-ASCII name, then dumping the bytes from `RosterUnit.szName` and from the chat packets.
- **Raised in:** [world.md](js-api/world.md#getpartyname--gid--unit).

## 7. Threading & runtime concurrency (THR)

### OQ-THR-01

**Thread identity of each patched call site.**

- **Question:** Which OS thread executes each patched call site in 1.14d: 0x45F802, 0x45E4D5, 0x448813, 0x442A61, 0x47C89D, 0x521B20, 0x44B1AE and the others? Is G = W for each?
- **RPC impact:** this decides where the RPC layer may block, which locks a producer already holds, and whether `PacketEventCallback`'s lock release path is ever taken.
- **Known:** the source proves only that the hooks and the subclassed WndProc run on the window thread (`Helpers.cpp:176-187`). "Main thread" for the D2Client intercepts is inferred. `PacketEventCallback` releases the game lock only when it runs on `dwGameThreadId` (`Events.cpp:305-315`, `:347-355`; [architecture.md §2.2](architecture.md#22-entry-points-on-game-threads-hooks-intercepts-window-procedure)).
- **Resolve by:** at runtime, logging `GetCurrentThreadId()` in every intercept and comparing it with `GetWindowThreadProcessId(D2GFX_GetHwnd())`.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 1, [events.md §15](js-api/events.md#15-open-questions) item 1, [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 7, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 1.

### OQ-THR-02

**Does `TimerProc` fire?**

- **Question:** `SetTimer(D2GFX_GetHwnd(), 1, 0, TimerProc)` is called from `D2Thread` for a window owned by another thread (`Helpers.cpp:180`), and its result is never checked. Does the timer get created and does `TimerProc` run?
- **RPC impact:** the game-lock hand-off that any in-process RPC executor will reuse depends on it.
- **Known:** `dwGameThreadId` is written only in `TimerProc`'s first-entry branch (`D2Handlers.cpp:493-503`). If `GameDraw` enters first, it stays 0 and `ReleaseGameLock`/`TakeGameLock` never act (`Events.cpp:347-355`). Out of game there is then no hand-off at all ([architecture.md §4.2](architecture.md#42-the-game-lock-cgameloopsection-in-detail)). Win32 documents that the window must belong to the calling thread.
- **Resolve by:** at runtime, logging `Vars.uTimer` and `GetLastError()` after `SetTimer`, counting `TimerProc` calls, and reading `dwGameThreadId` in game.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 3, [events.md §15](js-api/events.md#15-open-questions) item 11, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 2.

### OQ-THR-03

**DDE server thread.**

- **Question:** Which thread services the DDE server? DDEML delivers callbacks on the thread that called `DdeInitialize`, which here is the `LoadLibrary` caller (`D2BS.cpp:135`).
- **RPC impact:** decides whether DDE is worth keeping at all as a transport. With remote-thread injection, the serving thread exits.
- **Known:** the server also cannot work as written (empty-buffer bug, [architecture.md §7.4](architecture.md#74-dde)).
- **Resolve by:** at runtime, connecting a DDE client under each loader in use ([OQ-EXT-02](#oq-ext-02)).
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 2.

### OQ-THR-04

**Shared `eventSignal` races in practice.**

- **Question:** How often does a late `SetEvent` wake an unrelated blocker or packet waiter, which then frees an `Event` that is still queued (use-after-free in `ExecScriptEvent`)? How many timed-out events leak in a long session?
- **RPC impact:** sizes the stability gain of replacing these waits with RPC request/response correlation.
- **Known:** `Vars.eventSignal` is manual-reset and shared (`Helpers.cpp:155`). Waiters reset it and wait 500 ms (`Events.cpp:305-315`). The analysis is in [patches-and-hooks.md §6.2](memory/patches-and-hooks.md#62-blocking-and-timeouts), and it is code-path analysis only.
- **Resolve by:** a stress test with several scripts holding `gamepacket`, `chatmsgblocker` and screen-hook listeners, run under Application Verifier with full page heap.
- **Raised in:** agent report for patches-and-hooks.md.

### OQ-THR-05

**Lifecycle races.**

- **Question:** Do these code-path findings happen in real sessions?
  - A leave and re-join between two 50 ms polls skips `GameJoined()` ([architecture.md §1.5](architecture.md#15-d2thread-d2bss-long-lived-worker)).
  - A `0x1337` copydata message after `Shutdown()` spins the window thread forever ([architecture.md §7.1](architecture.md#71-inbound-wm_copydata)).
  - `.flush` with `DisableCache=false` leaves `ScriptEngine::console` dangling ([architecture.md §6.2](architecture.md#62-built-in-commands-processcommand)).
  - Restarting a running script replaces its map entry without `scriptListLock` ([architecture.md §8.4](architecture.md#84-which-scripts-run-when)).
- **RPC impact:** an RPC manager will drive join, leave, reload and shutdown far faster than a human, which makes these windows likelier.
- **Known:** each finding is labelled code-path analysis in architecture.md.
- **Resolve by:** scripted fast leave/join cycles, `0x1337` sent during unload, and `.flush` under `DisableCache=false`, with a debugger attached.
- **Raised in:** agent report for architecture.md.

### OQ-THR-06

**TOCTOU windows on game lists.**

- **Question:** Between two probes from a script thread, does the game thread free or rebuild `Control` objects (out of game) and unit or room lists? Does the `WH_MOUSE` hook ever run without the game thread holding `cGameLoopSection` (before the first hand-off, while `bGameLoopEntered` is false)?
- **RPC impact:** every RPC handler that reads game memory from a non-game thread has this window.
- **Known:** [out-of-game.md](js-api/out-of-game.md#open-questions) item 13. The screen-hook locking claim is inferred from the `GameDraw`/`TimerProc` hand-off ([screenhooks.md § Threading and locking](js-api/screenhooks.md#threading-and-locking)).
- **Resolve by:** a stress test that probes controls in a tight loop during menu transitions, and hook logging of lock ownership.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions), agent report for screenhooks.md.

### OQ-THR-07

**Thread-safety of game functions.**

- **Question:** Which game functions and globals can safely be called or read from a thread other than the game's main thread, with or without `cGameLoopSection` held?
- **RPC impact:** this decides where an RPC executor runs game calls: on the main thread, under the game lock, or on its own thread ([rpc-considerations.md §2.5](rpc-considerations.md#25-options-for-where-an-rpc-executor-runs-game-calls-trade-offs-only)).
- **Known:** the game lock is a hand-off, not a mutex around game access. The main thread holds it except in `TimerProc`, in `GameDraw` and around packet waits ([architecture.md §4.2](architecture.md#42-the-game-lock-cgameloopsection-in-detail)). Today, `ClickMap`, `Say_I`, `D2WIN_SetControlText` and `D2NET_SendPacket` are called from script threads without the lock, and drawing happens only on the main thread ([rpc-considerations.md §2.3](rpc-considerations.md#23-unsynchronised-game-memory-access-risk-inventory), [§2.4](rpc-considerations.md#24-operations-tied-to-the-main-thread-today)). `SendMouseClick` carries the comment "HACK: Using PostMessage instead of SendMessage--need to fix this ASAP!" (`D2Helpers.cpp:306`).
- **Resolve by:** in Ghidra, listing the shared mutable state (allocators, unit tables, UI vars, net buffers) that each function the RPC API needs touches. At runtime, stress each call from a worker thread with and without the game lock under Application Verifier.
- **Raised in:** [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 6.

## 8. SpiderMonkey engine semantics (SM)

These matter for next-gen mainly in two ways: they explain present behaviour that RPC clients may depend on, and they decide which existing quirks must be reproduced or can be dropped. The shipped engine is the `moz22` mozilla-release build in `dependencies/libs` ([embedding.md §1.1](spidermonkey/embedding.md#11-which-spidermonkey)). Its source is not in the repo.

### OQ-SM-01

**Argument slots past `argc`.**

- **Question:** Does this build pad a native's `vp` array with `undefined` up to the declared `nargs`?
- **RPC impact:** this decides what today's argument-unchecked natives (`createGame(name)`, `stop()`, `setTimeout`, …) actually do, i.e. which behaviour an RPC schema should reproduce.
- **Known:** the headers only say `CallArgs::operator[]` asserts `i < argc` (`dependencies/include/js/CallArgs.h:239`). Every page that depends on it ([embedding.md §4.3](spidermonkey/embedding.md#43-how-natives-receive-arguments-return-values-and-report-errors), globals-core.md, globals-game.md, out-of-game.md, unit-methods.md, utility-classes.md) treats it as unverified. An earlier draft of embedding.md §4.3 stated that padding happens without a citation; that sentence was withdrawn.
- **Resolve by:** a runtime test, e.g. a native with `nargs = 1` called with no arguments that logs `vp[2]`. Alternatively, read `js::Invoke`/`CallJSNative` in mozilla-release 22.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 1, [globals-game.md](js-api/globals-game.md#open-questions), [out-of-game.md](js-api/out-of-game.md#open-questions) item 1, [unit-methods.md](js-api/unit-methods.md#open-questions), [utility-classes.md](js-api/utility-classes.md#open-questions) item 1, [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 12.

### OQ-SM-02

**Unset return values.**

- **Question:** What does a native that returns `JS_TRUE` without `JS_SET_RVAL` evaluate to? Probably the callee function object in `vp[0]`. And what does `new` yield for a constructor that leaves rval unset (`new Text()`, `new Image()` failure exits)?
- **RPC impact:** clients that test results for truthiness today get a truthy function where they may expect `undefined`.
- **Known:** the header calls the initial contents unspecified (`dependencies/include/js/CallArgs.h:134-142`).
- **Resolve by:** runtime tests such as `typeof me.move(0,0)` out of game, and `new Text()` with bad arguments.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 2, [out-of-game.md](js-api/out-of-game.md#open-questions) item 3, [unit-methods.md](js-api/unit-methods.md#open-questions), [utility-classes.md](js-api/utility-classes.md#open-questions) item 2, [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions).

### OQ-SM-03

**`JS_ReportError` followed by `return JS_TRUE`.**

- **Question:** `setTimeout`, `setInterval`, `clearTimeout` and `clearInterval` report an error and then return success (`JSCore.cpp:81-82`, `:101-102`, `:119-120`). Is the pending exception thrown later, reported immediately, or lost?
- **RPC impact:** this decides the error semantics an RPC timer API should mirror.
- **Known:** `JSOPTION_DONT_REPORT_UNCAUGHT` is not set (`dependencies/include/jsapi.h:1973-1978`).
- **Resolve by:** a runtime test, or reading `js_ReportErrorVA`/`js_ErrorToException` in mozilla-release 22.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 10, [globals-core.md](js-api/globals-core.md#open-questions) item 3.

### OQ-SM-04

**Exceptions from handlers; operation-callback re-entry.**

- **Question:** What happens to an exception that an event listener or screen-hook click handler leaves pending, when `ExecScriptEvent` ignores the failed `JS_CallFunctionValue` inside the operation callback or `delay()`? Is it reported, swallowed, or surfaced in the interrupted frame? Can the operation callback re-enter itself during a nested drain?
- **RPC impact:** decides whether the current "a throwing handler breaks the main loop" behaviour exists, which a migration guide must mention.
- **Known:** [embedding.md §2.5](spidermonkey/embedding.md#25-the-operation-callback-operationcallback-scriptenginecpp260), [events.md §15](js-api/events.md#15-open-questions) item 6.
- **Resolve by:** a runtime test with a throwing listener during `delay()` and during a busy loop, or reading `js_InvokeOperationCallback` in mozilla-release 22.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 5, [events.md §15](js-api/events.md#15-open-questions), [screenhooks.md](js-api/screenhooks.md#open-questions) item 7.

### OQ-SM-05

**Structured-clone failures.**

- **Question:** What does `JSAutoStructuredCloneBuffer::write` leave behind for a non-cloneable value (function, `Unit`) passed to `load()`, `send()` or `scriptBroadcast()`: a pending exception on the sender's context, an empty buffer, or both? What does the recipient's `read` of that buffer produce, and what does `Script::Run` then pass for the unchecked, uninitialised `argvalue` entries (`Script.cpp:183-188`)? Does `write` invoke getters on host objects?
- **RPC impact:** this is the baseline for RPC payload validation, and documents what inter-script messages carry today.
- **Known:** the engine writes primitives, Objects, Arrays, Dates, RegExps, TypedArrays and ArrayBuffers. Any other object needs callbacks (`dependencies/include/jsapi.h:1167-1176`), and D2BS passes none. The results are unchecked (`JSCore.cpp:195`, `Events.cpp:160`, `JSScript.cpp:121`; [jsapi-inventory.md §7.2](spidermonkey/jsapi-inventory.md#72-structured-clone-inter-script-messages-load-arguments)).
- **Resolve by:** a runtime test with `scriptBroadcast(function(){})`, or reading `jsclone.cpp` in mozilla-release 22.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 6, [globals-core.md](js-api/globals-core.md#open-questions) item 5, [events.md §15](js-api/events.md#15-open-questions) item 10.

### OQ-SM-06

**Slot semantics of native accessors.**

- **Question:** Every D2BS property is defined without `JSPROP_SHARED`, so each has a value slot (`dependencies/include/jsapi.h:1419`). Does the engine seed a native getter's `vp` with the slot value and store the result back, and does it store an assigned value in the slot after the setter? If so, a getter that leaves `vp` untouched returns the property's **last** value, not `undefined`.
- **RPC impact:** decides whether "property keeps last value when the unit/room is gone" is real behaviour that scripts rely on. Examples: `u.x` after despawn, `room.number` through `getNext`, `me.nopickup` read back at the menu, removed screen hooks, and click functions kept alive only through the slot.
- **Known:** [unit-properties.md § Getter / setter mechanics](js-api/unit-properties.md#getter--setter-mechanics), [world.md](js-api/world.md#open-questions), [screenhooks.md](js-api/screenhooks.md#open-questions) items 6 and 15.
- **Resolve by:** a runtime test: read `u.x`, let the unit despawn, read again. Or read `js_NativeGet`/`js_NativeSet` in mozilla-release 22.
- **Raised in:** the docs above; agent report for embedding.md.

### OQ-SM-07

**Default prototype and inherited-getter receiver.**

- **Question:** `JS_NewObject(cx, &class, NULL, NULL)` (`js32.cpp:11`): which prototype does the engine compute, and is it `Class.prototype` from `JS_InitClass`, so that `instanceof Unit`/`Room` holds? When `me` reaches an inherited `unit_props` getter (`uniqueid`, `lvlreq`, `gfx`, `objtype`, `islocked`), is the getter called with `me` or with `Unit.prototype` as `obj`?
- **RPC impact:** decides whether type checks and those five `me` properties work today.
- **Known:** the header confirms that a default prototype *is* computed when `proto` is NULL: "Unlike JS_NewObject, JS_NewObjectWithGivenProto does not compute a default proto" (`dependencies/include/jsapi.h:3159-3160`). Which object it is remains engine-internal.
- **Resolve by:** runtime tests `getUnit(1) instanceof Unit` and `me.gfx`. Or read `FindProto`/`js_FindClassObject` in mozilla-release 22.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 2, [world.md](js-api/world.md#open-questions).

### OQ-SM-08

**`JS_ConvertArguments` `W` write-back.**

- **Question:** Does `JS_ConvertArguments` store the converted string back into `argv`? `my_createGame`, `my_joinGame` and `my_createCharacter` re-read `argv` as strings after a `"W"` conversion.
- **RPC impact:** decides whether `createGame(123)` crashes today. Low impact for RPC, which gets typed arguments.
- **Known:** the header promises the converted memory stays valid "so long as argv refers to allocated stack space" (`dependencies/include/jsapi.h:1499-1504`), which implies storage in `argv` but does not state it.
- **Resolve by:** disassembling `JS_ConvertArgumentsVA` in `jsapi.obj` (see [Appendix C](#appendix-c-reproducing-the-binary-checks)), or a runtime test with a numeric game name.
- **Raised in:** [out-of-game.md](js-api/out-of-game.md#open-questions) item 2.

### OQ-SM-09

**Lifetime of interned strings.**

- **Question:** Are atoms from `JS_InternString`/`JS_InternUCString` pinned until runtime destruction? The `name`, `fname`, `description`, `code`, `prefix`/`suffix`, Text `text`, Socket `read`, `Folder.name` and `D2BSScript.name` getters intern on every read.
- **RPC impact:** explains memory growth in long-running scripts. It disappears with SpiderMonkey but should not be copied into a replacement string cache.
- **Known:** `JS_InternUCString` calls `AtomizeChars` with `InternBehavior` = 1 (`InternAtom`), per a disassembly of `jsapi.obj` (Appendix C). Whether interned atoms survive GC is decided in `jsatom.cpp`.
- **Resolve by:** reading `js::MarkAtoms` in mozilla-release 22, or a runtime test that reads 100k distinct descriptions and watches `JSGC_BYTES`.
- **Raised in:** [unit-properties.md](js-api/unit-properties.md#open-questions) item 11, [screenhooks.md](js-api/screenhooks.md#open-questions) item 9, [utility-classes.md](js-api/utility-classes.md#open-questions) item 7.

### OQ-SM-10

**Finalization at script teardown.**

- **Question:** `~Script` calls `JS_DestroyContext` and then `JS_DestroyRuntime` (`Script.cpp:53-55`). Does the GC run before or after `contextCallback(JSCONTEXT_DESTROY)` (which calls `Genhook::Clean`)? Is every remaining `File`, `SQLite`, `Socket` and screen-hook object finalized, including objects reachable only from leaked roots such as `DBStatement.current_row`?
- **RPC impact:** decides which OS resources (file handles, sockets, SQLite handles) leak when a script ends today. The RPC host must own those resources explicitly.
- **Known:** `JS_DestroyContext` calls `js::DestroyContext(cx, 1)`, while `JS_DestroyContextNoGC` passes 0 (disassembly of `jsapi.obj`, Appendix C). So this is the GC-requesting variant. The order of operations inside `js::DestroyContext` was not traced.
- **Resolve by:** finishing the disassembly of `js::DestroyContext` in `jscntxt.obj`, or adding finalizer logging and ending a script that holds one object of each class.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 11, [screenhooks.md](js-api/screenhooks.md#open-questions) item 14, [utility-classes.md](js-api/utility-classes.md#open-questions) item 6.

### OQ-SM-11

**One runtime per thread without `JS_THREADSAFE`.**

- **Question:** D2BS creates one `JSRuntime` per script thread (`Script.cpp:120`) on an engine built without `JS_THREADSAFE` (`dependencies/include/js-config.h:16`, `build-unsafe`). Does SpiderMonkey 22 then keep any process-global mutable state that several runtimes on several threads race on?
- **RPC impact:** none after the removal. It explains intermittent crashes in today's multi-script setups that a regression comparison may hit.
- **Known:** requests and owner-thread checks are no-ops in both shipped builds ([Appendix A](#appendix-a-resolved-during-triage), R-01/R-02), so nothing in the engine serialises cross-runtime access.
- **Resolve by:** auditing statics in mozilla-release 22 (`jsapi.cpp` `JS_NewRuntime`/`JS_ShutDown`, `jsgc.cpp`, `jsatom.cpp`, `vm/Runtime`).
- **Raised in:** [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions).

### OQ-SM-12

**`JS_New` with a NULL constructor.**

- **Question:** What does `JS_New(cx, NULL, NULL, NULL)` (`JSSQLite.cpp:325`) do: crash, or fail with an exception?
- **RPC impact:** low, since the path is replaced. It documents today's `DBStatement` behaviour.
- **Known:** the call is outside the JSAPI contract ([utility-classes.md](js-api/utility-classes.md#open-questions) item 3).
- **Resolve by:** disassembling `JS_New`/`InvokeConstructor`, or a runtime test of the `DBStatement` path.
- **Raised in:** [utility-classes.md](js-api/utility-classes.md#open-questions).

### OQ-SM-13

**`JS_TypeOfValue(null)`.**

- **Question:** Does `JS_TypeOfValue(null)` return `JSTYPE_OBJECT`, as the "Result of typeof operator" comment implies (`dependencies/include/jspubtd.h:93`)?
- **RPC impact:** low. If it returned `JSTYPE_NULL`, `File.writeValue(null)` would write 4 zero bytes (`File.cpp:58`).
- **Known:** `JS_TypeOfValue` just forwards to `js::TypeOfValue` (disassembly of `jsapi.obj`).
- **Resolve by:** disassembling `js::TypeOfValue`, or the runtime test `file.write(null)`.
- **Raised in:** [utility-classes.md](js-api/utility-classes.md#open-questions) item 5.

### OQ-SM-14

**`%ls` in `JS_ReportError`.**

- **Question:** How does SpiderMonkey's own printf handle the `l` modifier in `"%ls"` (`File.cpp:202`)?
- **RPC impact:** low. File names in "Couldn't open file" errors may be truncated.
- **Known:** a wide string passed to `%s` shows only its first character (`JSDirectory.cpp:183`, [utility-classes.md](js-api/utility-classes.md#open-questions)).
- **Resolve by:** reading `jsprf.cpp`, or opening a missing file at runtime.
- **Raised in:** [utility-classes.md](js-api/utility-classes.md#open-questions) item 4.

### OQ-SM-15

**JIT state and performance.**

- **Question:** With the JIT option bits cleared, do scripts run interpreted, and what does that cost? Can the engine enable a JIT internally?
- **RPC impact:** sets the performance baseline that an out-of-process client is compared with.
- **Known:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 8.
- **Resolve by:** benchmarking a CPU-bound script with and without `JSOPTION_METHODJIT`/`ION` set.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions).

### OQ-SM-16

**Out-of-range typed-array writes.**

- **Question:** When `getCollisionA` indexes past the typed array's length (the Room2 size and the CollMap size differ), what does `JS_SetElement` do?
- **RPC impact:** low. It documents whether today's collision arrays can carry silently dropped cells.
- **Known:** [world.md § getCollisionA](js-api/world.md#roomprototypegetcollisiona).
- **Resolve by:** a runtime test on a room where the two sizes differ.
- **Raised in:** agent report for world.md.

## 9. Windows platform & CRT behaviour (WIN)

### OQ-WIN-01

**Thread hooks and posted input.**

- **Question:** Do the `WH_KEYBOARD`/`WH_MOUSE` thread hooks (`Helpers.cpp:184-187`) see the messages `sendKey`/`sendClick` post with `PostMessage` (`D2Helpers.cpp:305-333`), and so fire `keydown`/`mouseclick` and honour `Vars.bBlockMouse`? For a posted message, does `MOUSEHOOKSTRUCT.pt` hold the posted coordinates or the real cursor position?
- **RPC impact:** decides whether synthesized input from the RPC layer echoes back as user-input events, and whether `login` can click while it blocks the mouse.
- **Known:** D2BS's mouse hook takes its coordinates from `MOUSEHOOKSTRUCT.pt`, not from `lParam` ([globals-core.md](js-api/globals-core.md#open-questions) item 10). The `login` flow relies on posted clicks bypassing the block ([out-of-game.md](js-api/out-of-game.md#open-questions) item 7).
- **Resolve by:** at runtime, calling `sendClick` with listeners attached and `bBlockMouse` set, and logging what the hooks receive.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions), [events.md §15](js-api/events.md#15-open-questions) item 8, [out-of-game.md](js-api/out-of-game.md#open-questions), [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 8.

### OQ-WIN-02

**Clipboard with a NULL owner.**

- **Question:** Does `SetClipboardData` succeed after `OpenClipboard(NULL)` + `EmptyClipboard` (`JSCore.cpp:347-349`) on the target Windows versions?
- **RPC impact:** whether a clipboard RPC needs a real owner window.
- **Known:** Microsoft documents that it fails.
- **Resolve by:** calling `copy()` at runtime on each supported Windows version.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 12.

### OQ-WIN-03

**Periodic waitable-timer APCs.**

- **Question:** If a `setInterval` timer expires several times while its thread is not alertable, does Windows queue one completion APC per expiry or one in total?
- **RPC impact:** decides how many times the same `Event` is pushed (`ScriptEngine.cpp:837-839`), i.e. today's burst behaviour of intervals.
- **Known:** [globals-core.md](js-api/globals-core.md#open-questions) item 13.
- **Resolve by:** at runtime, a 10 ms interval in a script that busy-loops for 1 s, counting callbacks.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions).

### OQ-WIN-04

**SHA-2 through CryptoAPI.**

- **Question:** Do `sha256`, `sha384` and `sha512` fail with `PROV_RSA_FULL` on the supported Windows versions? Does `HashFile`'s non-`VERIFYCONTEXT` `CryptAcquireContext` fail on accounts without a default key container?
- **RPC impact:** whether a hash RPC must switch provider or move host-side.
- **Known:** per Microsoft's documentation, SHA-2 needs `PROV_RSA_AES` ([globals-core.md § sha256](js-api/globals-core.md#sha256str)).
- **Resolve by:** calling each function at runtime on clean user profiles.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 9.

### OQ-WIN-05

**Unhandled exceptions in script threads.**

- **Question:** Does an exception that escapes a script thread terminate the process? Two cases: the C++ exception from a compile failure in `load()` (`Script.cpp:157-171`, no handler in `ScriptThread` at `Script.cpp:473`, Release built with `ExceptionHandling=false`, `D2BS.vcxproj:157`), and the access violation that `new Sandbox()` now provably raises ([Appendix A](#appendix-a-resolved-during-triage), R-03). Does the game replace D2BS's top-level filter later?
- **RPC impact:** decides whether one bad script can kill the client today, and whether the RPC host needs its own guard threads.
- **Known:** threads are created with plain `CreateThread` (`Script.cpp:108`), so no CRT frame catches anything. `SetUnhandledExceptionFilter(ExceptionHandler)` runs in `DllMain` (`D2BS.cpp:93`), and `ExceptionHandler` returns `EXCEPTION_EXECUTE_HANDLER` (`Helpers.cpp:396-432`; [architecture.md §9.2](architecture.md#92-crash-and-exit-handling)).
- **Resolve by:** at runtime, `load()` a file with a syntax error, and separately call `new Sandbox()`. Afterwards check `SetUnhandledExceptionFilter`'s current value from a debugger.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 4, [globals-core.md](js-api/globals-core.md#open-questions) item 4, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 10.

### OQ-WIN-06

**`free()` of a non-heap pointer.**

- **Question:** What does the MSVCR100 `free()` do with a pointer to a string literal: return silently, or abort with heap corruption? `getUnit` without a name, `sendCopyData` with non-string data and `sendDDE` with non-string arguments all pass a literal `""` to `JS_free` (`JSUnit.cpp:582`, `:613`, `:630`; `JSCore.cpp:406-415`, `:422`, `:444-447`).
- **RPC impact:** explains intermittent crashes in today's API. The RPC host has no equivalent.
- **Known:** `JS_free` calls the DLL CRT's `free` directly ([Appendix A](#appendix-a-resolved-during-triage), R-08). The result depends on the CRT heap and on whether termination-on-corruption is enabled for the process.
- **Resolve by:** at runtime, calling `getUnit(1)` repeatedly under Application Verifier and without it.
- **Raised in:** [unit-methods.md](js-api/unit-methods.md#open-questions).

### OQ-WIN-07

**CRT file-sharing semantics.**

- **Question:** Does `_wfopen_s` with MSVC's `_SH_SECURE` behave as documented for the CRT D2BS links (read-only opens shared, writes exclusive)? What does `FileTools.copy(a, a)` do?
- **RPC impact:** a file RPC needs the sharing rules spelled out.
- **Known:** [utility-classes.md](js-api/utility-classes.md#open-questions) item 8.
- **Resolve by:** at runtime, opening one file twice in each mode, and copying a file onto itself.
- **Raised in:** [utility-classes.md](js-api/utility-classes.md#open-questions).

### OQ-WIN-08

**Winsock reference count.**

- **Question:** D2BS calls `WSACleanup` more often than `WSAStartup` (`JSSocket.cpp:125`, `:171`). Does the game's own networking share that process-wide count, and could it be torn down?
- **RPC impact:** the RPC transport will share Winsock with the game, so its startup and cleanup must be balanced.
- **Known:** [utility-classes.md](js-api/utility-classes.md#open-questions) item 9.
- **Resolve by:** at runtime, opening and closing many `Socket` objects while in a realm game, watching for disconnects and `WSANOTINITIALISED`.
- **Raised in:** [utility-classes.md](js-api/utility-classes.md#open-questions).

### OQ-WIN-09

**`InternetReadFile` on failure.**

- **Question:** If `InternetOpenUrl` fails, does `InternetReadFile` still zero the uninitialised byte count `rSize` (`JSCore.cpp:662`, `:667`), so that `getIP` returns `""`, or does it return stack garbage?
- **RPC impact:** low. `getIP` should become a host-side call.
- **Known:** Microsoft documents zeroing before error checks ([globals-core.md § getIP](js-api/globals-core.md#getip)).
- **Resolve by:** calling `getIP()` at runtime with the network blocked.
- **Raised in:** agent report for globals-core.md.

## 10. External tooling & IPC consumers (EXT)

### OQ-EXT-01

**Manager protocol.**

- **Question:** Which `dwData` values and payloads do external managers (D2Bot-style) send as generic `copydata` events, and what do scripts reply through `sendCopyData(null, handler(), …)`? Does any current manager use `0x1337` (execute JS), `0x31337` (switch profile) or the DDE server?
- **RPC impact:** this is the compatibility surface the RPC API replaces. The first RPC version should cover every message in real use.
- **Known:** D2BS itself defines only `0x1337` and `0x31337`. Everything else is passed to scripts ([architecture.md §7.1](architecture.md#71-inbound-wm_copydata), [§7.2](architecture.md#72-outbound-sendcopydata-handler)). Native code never sends to `hHandle`. The DDE server cannot work as written ([architecture.md §7.4](architecture.md#74-dde)), although HISTORY 1.4 describes DDE profile selection.
- **Resolve by:** inspecting the source of D2Bot# (or whichever manager the owner targets) and of the script library it drives (e.g. kolbot), and listing every mode constant.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 8, [rpc-considerations.md §10.2](rpc-considerations.md#102-open-questions-that-affect-an-rpc-design) item 9.

### OQ-EXT-02

**Loader for 1.14d.**

- **Question:** Which loader injects D2BS into Game.exe 1.14d in practice, on which thread, and does the bundled .NET loader still work?
- **RPC impact:** decides the thread `DllMain` runs on (DDE, loader lock) and whether next-gen must ship its own loader.
- **Known:** `Debug/D2BS.exe` and `Release/D2BS.exe` are a .NET "D2BS Loader" from 2013/2014. Their strings show `CreateProcess`, `VirtualAllocEx`, `WriteProcessMemory`, `CreateRemoteThread` and `LoadLibrary`, plus `D2Gfx.dll`, `d2loader`, `cGuard.dll` and `game.exe` ([architecture.md §1.2](architecture.md#12-how-the-dll-gets-into-the-process)). `D2Gfx.dll` does not exist in 1.14d. D2BS also supports cGuard and D2Loader plugin loading.
- **Resolve by:** decompiling the bundled loader (ILSpy) to see the module it waits for, and identifying the loader the owner's users actually run.
- **Raised in:** [architecture.md §11](architecture.md#11-open-questions) item 5.

### OQ-EXT-03

**Script reliance on dead or broken features.**

- **Question:** Does any maintained script library rely on screen-hook `onHover` (dispatch disabled at `D2Handlers.cpp:343`), `Sandbox` (crashes, R-03), or DDE (broken)?
- **RPC impact:** decides which legacy features need an RPC equivalent at all.
- **Known:** [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions).
- **Resolve by:** grepping the target script libraries for `hover`, `Sandbox`, `sendDDE`.
- **Raised in:** [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions).

### OQ-EXT-04

**`getIP` endpoint.**

- **Question:** Is `http://ipv4bot.whatismyipaddress.com` (`JSCore.cpp:666`) still a working endpoint?
- **RPC impact:** if not, `getIP` is already broken and need not be carried over.
- **Known:** not determinable from source. It was not probed during triage because outbound probes from the build sandbox were not permitted.
- **Resolve by:** an HTTP GET from a user machine.
- **Raised in:** [globals-core.md](js-api/globals-core.md#open-questions) item 11.

## 11. Build, toolchain & RE tooling (BLD)

### OQ-BLD-01

**Deployed configuration and toolset.**

- **Question:** Which configuration (Debug with `mozjs.dll`, or Release with `js_static.lib`) and which compiler produced the `D2BS.dll` that users run? Was the 2021 work (`159b4bb` added `WindowsTargetPlatformVersion 10.0`, a VS2015+ element) built with the v100 toolset inside a newer Visual Studio?
- **RPC impact:** the next-gen build must reproduce, or knowingly drop, the deployed behaviour, including compiler-dependent quirks ([OQ-BLD-03](#oq-bld-03)).
- **Known:** Release requires VS2010, as documented and enforced ([Appendix A](#appendix-a-resolved-during-triage), R-07). Debug needs `mozjs.dll` next to the game, and no build step copies it ([jsapi-inventory.md §6.2](spidermonkey/jsapi-inventory.md#62-configuration-matrix-from-d2bsvcxproj)).
- **Resolve by:** asking the owner, or inspecting a shipped `D2BS.dll` (imports `MSVCR100.dll` vs `mozjs.dll`, the Rich header).
- **Raised in:** [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions).

### OQ-BLD-02

**Header/library match.**

- **Question:** Were the shipped headers generated from the same `build-unsafe` configuration as `js_static.lib`? Where is the `dependencies\libs\release\mozjs.lib` that the Packaging configuration links (`D2BS.vcxproj:230`)?
- **RPC impact:** low. This is only relevant if the old engine is kept for a transition period.
- **Known:** `js-config.h` is consistent with the lib (non-threadsafe, `JS_METHODJIT`, `JS_GC_ZEAL`). The lib was built with MSVC 16.00 SP1 from `c:\moz22\mozilla-release\js\src\build-unsafe` (`dependencies/libs/release/js_static.lib.desc`; R-07).
- **Resolve by:** rebuilding mozilla-release 22 with the same configure flags and diffing the generated headers.
- **Raised in:** [embedding.md §13](spidermonkey/embedding.md#13-open-questions) item 9.

### OQ-BLD-03

**Facts visible only in a compiled `D2BS.dll`.**

- **Question:** What did MSVC actually emit for these?
  - `mov [esp + 0x4 + 4 + 2], 0` (`D2Intercepts.cpp:58`) and `mov [esp+0x08+0x4+0x4], 1` (`D2Intercepts.cpp:155`): byte or dword stores?
  - `PUSHF` in `GamePacketSent_Interception`: the 2-byte `66 9C`, as the `0x22` displacement assumes?
  - `abs(GetDistance(...))` (`JSGame.cpp:800`, `<cmath>` at `JSGame.cpp:17`): the `double` overload of `abs`, or a truncating integer one?
- **RPC impact:** if the first store is a byte store, a blocked sent packet keeps `aLen & ~0xFF`, so only packets shorter than 256 bytes are fully blocked. The answer decides what "block this outgoing packet" does today.
- **Known:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), [§5.4](memory/patches-and-hooks.md#54-gamepacketsent_interception--client--server-game-packets). `GetDistance` returns `double` (`D2Helpers.h:115`).
- **Resolve by:** building Release with VS2010 and disassembling the three sites, or disassembling a shipped `D2BS.dll`.
- **Raised in:** [patches-and-hooks.md §10](memory/patches-and-hooks.md#10-open-questions), agent report for globals-game.md.

### OQ-BLD-04

**Open choices in the Ghidra import tooling.**

- **Question:**
  - Should `d2bs_symbols.tsv` use the `D2WIN_SetEditBoxCallback_FunCallBack_t`/`D2WIN_SetEditBoxProc_FunCallBack_t` typedefs from `d2bs_types.h`? CParser drops `__stdcall` from the inline `BOOL (__stdcall* FunCallBack)(...)` form, and both rows share one function definition.
  - How should Win32 typedef names that already exist in a program be handled?
  - Should struct-member function pointers get named typedefs instead of anonymous `_func_N` definitions?
  - Does `gen_types.py --ghidra-install` work against a real Ghidra binary release? It has only been run with a CParser built from tag `Ghidra_12.0.4_build`.
- **RPC impact:** none directly. These affect how reliable the disassembly work behind most of this page is.
- **Known:** [structs.md § Open questions](memory/structs.md#open-questions). The TSV still uses the inline form (`docs/ghidra/d2bs_symbols.tsv`, rows for `D2WIN_SetEditBoxCallback`/`SetEditBoxProc`).
- **Resolve by:** running `docs/ghidra/tools/gen_types.py --ghidra-install` against a Ghidra 12 release. The rest is the importer owner's decision.
- **Raised in:** [structs.md](memory/structs.md#open-questions), agent reports for structs.md.

### OQ-BLD-05

**End-to-end behaviour of the Ghidra importer in a real installation.**

- **Question:** Does `docs/ghidra/D2BSImport.java` behave in a real Ghidra installation as it did in the verification harnesses, in both the Script Manager and `analyzeHeadless`? Specifically:
  - Disassembly and `CreateFunctionCmd` body splitting at the 111 `FUNC` rows.
  - The patch-site boundary check, data-type conflicts and which rows land on `FUN_*` entries, given the real Game.exe 1.14d bytes.
  - Layout computation by the 10.x/11.x framework classes. Only their C grammars ran.
  - Association of the `/D2BS` types with the in-memory "D2BS header" source archive on 10.x/11.x.
  - Interplay with an auto-analysis that is still running in the GUI.
- **RPC impact:** none directly. The importer is the main tool for settling the MEM/STR/NET questions above, so wrong or partial imports would mislead that work.
- **Known:** The script compiles with `-Xlint:all -Werror` against API stubs copied from Ghidra source at 12.3-DEV, 12.0.4, 11.0, 10.4, 10.2 and 10.1, and against real 12.0.4 framework classes. The real 12.0.4 `CParser` parses `d2bs_types.h` (all composite sizes match) and all 111 prototypes. A run against a real 12.0.4 `ProgramDB` over synthetic memory, plus static-helper harnesses over all 266 TSV rows, passed, including re-run idempotency and dry-run counter parity. Nothing ran inside a Ghidra application, and no Game.exe was available ([ghidra/README.md §11](ghidra/README.md#11-verification-performed), [§12](ghidra/README.md#12-known-limitations), [§14](ghidra/README.md#14-open-questions)).
- **Resolve by:** importing Game.exe 1.14d (base 0x400000, `x86:LE:32:default`, windows compiler spec). Let auto-analysis finish, run the script with `dry-run`, then run it for real, then re-run it to confirm nothing changes. Repeat headless and on one 10.x/11.x install. Run `docs/ghidra/tools/gen_types.py --ghidra-install <dir>` against the same installs to compare layouts.
- **Raised in:** [ghidra/README.md §14](ghidra/README.md#14-open-questions), agent reports for the Ghidra script and its API and integration verifiers.

### OQ-BLD-06

**Register-ABI entry points imported as labels.**

- **Question:** Several `ASMPTR` rows with `_I`/`_II` suffixes are imported as `LABEL` but are in practice function entries with register-based calling conventions (e.g. `D2CLIENT_GetUnitName_I`, `D2CLIENT_ClickParty_I`). Should `gen_symbols.py` emit them as `FUNC` rows with custom storage, so Ghidra creates functions with correct parameters? Separately, six asm-only `FUNC` rows have declared prototypes that do not match the register ABI their stubs set up, and are skipped by default (`asm-only=skip`). Should their true storage be encoded in the data?
- **RPC impact:** none directly. Correct prototypes at these entries make the remaining call-stub questions ([OQ-MEM-09](#oq-mem-09)) much easier to settle.
- **Known:** the script creates no functions for `LABEL` rows; at a default-named `FUN_*` entry a `LABEL` row names that function ([ghidra/README.md §7](ghidra/README.md#7-what-each-row-kind-does)). The register contracts the stubs assume are listed in [memory/call-stubs.md](memory/call-stubs.md).
- **Resolve by:** disassembling each `_I`/`_II` entry to confirm its inputs, return and stack cleanup ([OQ-MEM-09](#oq-mem-09)). Then decide whether to extend the TSV schema, for example with a custom-storage column.
- **Raised in:** agent reports for the Ghidra script ([ghidra/README.md §12](ghidra/README.md#12-known-limitations)).

## 12. Intent & legacy behaviour (INT)

### OQ-INT-01

**`pack(1)` on non-network structs.**

- **Question:** Is `#pragma pack(1)` on `Level`, `Room2`, `RosterUnit`, `CollMap` and the others intended?
- **RPC impact:** whether next-gen headers may use natural alignment.
- **Known:** only `BnetData` and `NPCMenu` change layout under it. For the rest it only lowers the alignment to 1 ([structs.md § Packing](memory/structs.md#packing)).
- **Resolve by:** an owner decision, after [OQ-STR-01](#oq-str-01) confirms the real layouts.
- **Raised in:** [structs.md](memory/structs.md#open-questions).

### OQ-INT-02

**`Sandbox`.**

- **Question:** `doc/Sandbox.h` describes a working sandbox, but the code crashes on construction (R-03), and `include`/`isIncluded` could never work (`JSSandbox.cpp:196`). Keep, fix or drop?
- **RPC impact:** an RPC API has no in-process sandbox concept. Recommend dropping it, unless [OQ-EXT-03](#oq-ext-03) finds users.
- **Known:** [embedding.md §8](spidermonkey/embedding.md#8-sandbox).
- **Resolve by:** owner decision.
- **Raised in:** [embedding.md §8](spidermonkey/embedding.md#8-sandbox), [embedding.md §13](spidermonkey/embedding.md#13-open-questions).

### OQ-INT-03

**The lost `-ftj` switch.**

- **Question:** `D2BS.cpp:65` installs the FailToJoin reducer only for `-ftj`, but `CLine[]` has no `-ftj` entry (`CommandLine.cpp:30`), so the patch is never installed. Before `a1f0409` it came with `-multi`. Was dropping it intended, and is the FTJ reducer still wanted?
- **RPC impact:** decides whether next-gen exposes an FTJ option.
- **Known:** [patches-and-hooks.md §5.18](memory/patches-and-hooks.md#518-failtojoin--ftj-reducer-never-installed). Site validity is [OQ-MEM-02](#oq-mem-02).
- **Resolve by:** owner decision (`git show a1f0409`).
- **Raised in:** agent report for patches-and-hooks.md.

### OQ-INT-04

**Legacy-documented behaviour to keep.**

- **Question:** Where the legacy docs (`doc/*.h`, `resources/api.html`, `resources/HISTORY.txt`) promise behaviour that the code does not have, which should the RPC API honour?
  - `clickMap` types 0-5.
  - `realm` as the long name.
  - DDE POKE selecting the profile (HISTORY 1.4).
  - The `sendCopyData(HWND, dummy, …)` form.
  - `Sandbox.isInclude`.
- **RPC impact:** this defines the compatibility target for the RPC schema.
- **Known:** the "Legacy-doc discrepancies" sections of [embedding.md §12](spidermonkey/embedding.md#12-legacy-doc-discrepancies), [jsapi-inventory.md §9](spidermonkey/jsapi-inventory.md#9-legacy-doc-discrepancies), [world.md](js-api/world.md#legacy-doc-discrepancies), [unit-methods.md](js-api/unit-methods.md#legacy-doc-discrepancies) and [architecture.md §7](architecture.md#7-external-control-surfaces).
- **Resolve by:** owner decision.
- **Raised in:** the sections above.

---

## Appendix A. Resolved during triage

Answers found in the repository's own source, headers or bundled binaries. Each raising doc's Open questions section was updated in place. Disassembly commands are in [Appendix C](#appendix-c-reproducing-the-binary-checks).

| Ref | Question | Answer | Evidence | Raised in |
|---|---|---|---|---|
| R-01 | Are `JS_BeginRequest`/`JS_EndRequest` no-ops in this non-`JS_THREADSAFE` build? | **Yes, in both shipped builds.** The never-ended request in `socket_getProperty` (`JSSocket.cpp:32`) has no effect. | Release `js_static.lib` → `jsapi.obj`: `?JS_BeginRequest@@YAXPAUJSContext@@@Z` and `?JS_EndRequest@@…` are each a single `ret`. Debug `mozjs.dll`: both exports reach empty functions (`push ebp; mov ebp,esp; pop ebp; ret`), and `JS_IsInRequest` returns 0. | [embedding.md §13](spidermonkey/embedding.md#13-open-questions) 1, [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions) |
| R-02 | Are SpiderMonkey's owner-thread checks (`jsapi.h:4804-4810`) compiled in, so that D2BS's cross-thread JSAPI calls would fire them? | **No.** There is no owner-thread enforcement, so the cross-thread calls in [embedding.md §7.4](spidermonkey/embedding.md#74-requests-and-the-single-thread-runtime-rule) are unsynchronised data races, not aborts. | Release: `JS_AbortIfWrongThread` is a bare `ret`, and `JS_GetCurrentThread` is `xor eax,eax; ret`. The owner-thread check that `js::NewContext` and `js::DestroyContext` make is a call to that no-op. Debug: `JS_AbortIfWrongThread` calls a `JSRuntime` method whose body is empty. | [embedding.md §13](spidermonkey/embedding.md#13-open-questions) 2 |
| R-03 | What does `JS_NewContext(NULL, 0x2000)` do in `sandbox_ctor` (`JSSandbox.cpp:8`): crash or return NULL? | **It crashes** with an access violation. `new Sandbox()` never returns, so the "returns NULL" branch (`JSSandbox.cpp:9-12`) is dead. What the AV does to the process is [OQ-WIN-05](#oq-win-05). | `JS_NewContext` jumps to `js::NewContext` (`jscntxt.obj`). That function mallocs the context, runs its constructor, then executes `lea eax,[ebp+0x9B4]; cmp [eax],eax` with `ebp` = `rt`, i.e. it reads address 0x9B4 when `rt` is NULL (offsets 0x7C-0x82). `ScriptEngine::runtime` is never assigned (`ScriptEngine.cpp:19`). | [embedding.md §13](spidermonkey/embedding.md#13-open-questions) 3, [utility-classes.md](js-api/utility-classes.md#open-questions) 3, [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions) |
| R-04 | How does `JS_NewStringCopyZ` decode bytes: Latin-1 or UTF-8? | **Latin-1.** Every byte becomes U+0000-U+00FF, so UTF-8 or code-page bytes from the game are mangled. The same holds for every narrow-char JSAPI entry point (`JS_InternString`, `JS_NewStringCopyN`, …). There is no API in these headers to switch the default. | `dependencies/include/js/CharacterEncoding.h:19-23`: "By default, all C/C++ 1-byte-per-character strings passed into the JSAPI are treated as ISO/IEC 8859-1". There is no `JS_SetCStringsAreUTF8` in `jsapi.h`. | [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions) |
| R-05 | Was `dependencies/libs/debug/mozjs.dll` built with `DEBUG`? | **Yes.** That matches D2BS's Debug configuration defining `DEBUG` (`D2BS.vcxproj:84`). | `MOZ_ASSERT`/`JS_ASSERT` expand to code only under `DEBUG` (`dependencies/include/mozilla/Assertions.h:247-290`, `js/Utility.h:42`). The DLL contains assertion expression strings (e.g. `tag != JSVAL_TAG_CLEAR`), 175 copies of `Assertion failure: %s, at %s:%d` and about 9,600 `c:\moz22\mozilla-release\js\src\build-dd` path strings. The release lib has only 2 `Assertion failure` strings. | [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions) |
| R-06 | Does the library scan the native stack conservatively, protecting unrooted locals? | **Yes.** The GC's conservative stack scanner finds `JSObject*`, `JSString*` and `Value` locals on the stack. It does not see heap arrays such as `new jsval[]` (`JSGame.cpp:303`) or derived pointers such as `jschar*`. | `dependencies/include/js/Anchor.h:27-30`, `:64-67`. `JSGC_USE_EXACT_ROOTING` is not defined in `js-config.h`, so `Rooted` takes its non-exact form (`js/RootingAPI.h:549`). Also stated in [embedding.md §1.1](spidermonkey/embedding.md#11-which-spidermonkey). | [jsapi-inventory.md §10](spidermonkey/jsapi-inventory.md#10-open-questions) |
| R-07 | Which toolchain is intended? (No `PlatformToolset`; `build.bat` references VS 2008.) | **Visual Studio 2010 (MSVC 16.00 SP1, v100)**, both documented and enforced for Release. With any other major compiler version, the Release link fails with LNK2038, because D2BS's own STL-using objects emit a different `_MSC_VER`. What was actually used for later builds is [OQ-BLD-01](#oq-bld-01). | `Release/Build Instructions.txt:2`: "use visual studio 2010". `jsapi.obj` in `js_static.lib` carries `/FAILIFMISMATCH:"_MSC_VER=1600"` and `@comp.id` 0x00AB9D1B (build 40219). Debug `mozjs.dll` imports `MSVCR100D.dll`/`MSVCP100D.dll`. `D2BS.sln:2-3` is "Visual Studio 2010" and `D2BS.vcxproj:2` has `ToolsVersion="4.0"`. | [architecture.md §11](architecture.md#11-open-questions) 6 |
| R-08 | Does `JS_free` reach CRT `free()`, or is it deferred? | **It calls the DLL CRT's `free` directly:** `push p; call [__imp__free]; ret`, with `/DEFAULTLIB:"msvcprt"`, i.e. MSVCR100 in Release. What `free` does with a literal `""` is [OQ-WIN-06](#oq-win-06). | Disassembly of `?JS_free@@YAXPAUJSContext@@PAX@Z` in `jsapi.obj`, and its `.drectve` section. The header's "may delay" wording (`jsapi.h:2289-2295`) does not apply to this build. | [unit-methods.md](js-api/unit-methods.md#open-questions) |
| R-09 | What does `JS_GetPrivate` return for an object whose class lacks `JSCLASS_HAS_PRIVATE` (e.g. `{}` passed as `this` or as `getItemCost`'s `npc`)? | **Whatever word follows the object's fixed slots.** There is no class or flag check, so D2BS's class-unchecked private reads are type confusion with arbitrary adjacent GC-heap memory. The result is neither a reliable NULL nor a reliable crash. | `JS_GetPrivate`: `mov ecx,[obj]` (shape); `mov edx,[ecx+8]; shr edx,27` (number of fixed slots); `mov eax,[obj+0x10+edx*8]`. | [unit-methods.md](js-api/unit-methods.md#open-questions) |
| R-10 | Does the Ghidra importer understand the extra status flags (`asm-only`, `captured-encoded`, …), and avoid applying prototypes to `asm-only` rows? | **Yes.** `D2BSImport.java` handles `asm-only` with an `asm-only=skip\|apply` option, defaulting to not applying the prototype, and handles `captured-encoded` (checked against the script as committed; re-check if the script changes). | `docs/ghidra/D2BSImport.java` (option block and `asm-only`/`captured-encoded` branches). | agent reports for offsets.md |

Narrowed, still open. Each has its own entry above.

| Ref | Narrowing fact | Evidence | Open entry |
|---|---|---|---|
| N-01 | `JS_NewObject` with `proto == NULL` computes a default prototype; which object it picks is still open. | `dependencies/include/jsapi.h:3159-3160` | [OQ-SM-07](#oq-sm-07) |
| N-02 | `JS_InternUCString` atomizes with `InternBehavior` = 1 (`InternAtom`). | `jsapi.obj` disassembly (`push 1` before `AtomizeChars`) | [OQ-SM-09](#oq-sm-09) |
| N-03 | `JS_DestroyContext` is the GC-requesting variant: it passes mode 1 to `js::DestroyContext`, while `JS_DestroyContextNoGC` passes 0. | `jsapi.obj` disassembly | [OQ-SM-10](#oq-sm-10) |
| N-04 | `Say_ASM` really passes `MSG**` in `EBX`. Only what `Say_I` expects is open. | `Core.cpp:67-82`, `:107` | [OQ-MEM-11](#oq-mem-11) |
| N-05 | The engine clones only primitives, Objects, Arrays, Dates, RegExps, TypedArrays and ArrayBuffers without callbacks, and D2BS passes no callbacks. | `dependencies/include/jsapi.h:1167-1176` | [OQ-SM-05](#oq-sm-05) |
| N-06 | The Release build must use VS2010, and `Release/Build Instructions.txt` documents the Release path. | R-07 | [OQ-BLD-01](#oq-bld-01) |

## Appendix B. Candidates not carried over

These came up in the collection pass but are not questions about the system:

- **Documentation-process notes from the agents:** sibling docs or links that did not exist at verification time (`rpc-considerations.md`, `js-api/README.md`, `ghidra/README.md`), Mermaid diagrams not rendered, heuristic or name-based scans in `docs/spidermonkey/tools/jsapi_inventory.py` and the offsets generator, the manual a/b/c/d classification table, rows checked for line accuracy only, a stale generator copy in a scratch directory, and `git status` noise.
- **Labels chosen by the generators,** not taken from the game (`D2CLIENT_ItemDescFlag`, `D2COMMON_MPQ_<table>_Records`, `D2BS_PATCH_BYTES_<hex>`, …). [offsets.md §1](memory/offsets.md#1-reading-the-tables) records them.
- **Defects that the source fully determines.** They belong in each doc's defects section, not here. Examples: `keyupblocker` always times out (no branch in `ExecScriptEvent`), `RemoveConditional` has no caller, the DDE empty-buffer bug, the `D2GAME_exit0` encoded-target bug, and the never-installed FailToJoin patch. Only the *intent* behind the last is asked, in [OQ-INT-03](#oq-int-03).
- **Cross-doc conflicts that the source settles.** Examples: the stale "`sqlite_memusage()` returns undefined" concern, and [embedding.md §9.1](spidermonkey/embedding.md#91-inventory) calling `CriticalRoom` unused although `ActMap` allocates and enters one (`Map/Diablo_II/ActMap.cpp:44-45`). The owning docs and [rpc-considerations.md §10.1](rpc-considerations.md#101-inconsistencies-found-among-the-sibling-docs) handle these. The one cross-doc conflict that the source does *not* settle, argument padding, is [OQ-SM-01](#oq-sm-01).

## Appendix C. Reproducing the binary checks

All checks use stock binutils on the files in `dependencies/libs`. Extract the zip into a scratch directory and do not execute anything from it.

```sh
S=/path/to/scratch
mkdir -p "$S/jszip" "$S/objs"
unzip -q dependencies/libs/release/js_static.zip -d "$S/jszip"
cd "$S/objs"
ar x ../jszip/js_static.lib jsapi.obj jscntxt.obj
objdump -d -r jsapi.obj   > jsapi.dis       # JS_BeginRequest, JS_EndRequest, JS_AbortIfWrongThread,
                                            # JS_GetCurrentThread, JS_free, JS_GetPrivate, JS_InternUCString,
                                            # JS_TypeOfValue, JS_DestroyContext(NoGC), JS_NewContext
objdump -d -r jscntxt.obj > jscntxt.dis     # js::NewContext (rt+0x9B4 read), js::DestroyContext
objdump -s -j .drectve jsapi.obj            # /FAILIFMISMATCH:"_MSC_VER=1600", /DEFAULTLIB:"msvcprt"
objdump -t jsapi.obj | grep comp.id         # 0x00ab9d1b
# Debug DLL (image base 0x10000000): export RVA -> thunk -> body
objdump -p /path/to/repo/dependencies/libs/debug/mozjs.dll | grep -E 'DLL Name|JS_(Begin|End)Request|JS_IsInRequest|JS_AbortIfWrongThread'
strings -n 6 /path/to/repo/dependencies/libs/debug/mozjs.dll | grep -c 'Assertion failure'   # 175
strings -n 6 "$S/jszip/js_static.lib" | grep -c 'Assertion failure'                         # 2
```

Function symbols are C++-mangled (`?JS_BeginRequest@@YAXPAUJSContext@@@Z`). The JSAPI in this build has C++ linkage, so a replacement shim would have to match those names.

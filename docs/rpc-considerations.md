# RPC considerations: facts for replacing the JS API

Scope: the factual synthesis an architect needs before designing an external, networked RPC control API to replace D2BS's embedded SpiderMonkey JS API. It inventories the API surface, the thread and lock context every operation runs in today, every blocking or waiting behaviour, how object identity and lifetimes work, the event streams and their volumes, the existing external control surfaces, the SpiderMonkey coupling that has to be cut, the game-internals each API depends on, and the defects that an RPC layer would inherit or must route around. It is built from the C++ in the repository root (cited as `File.cpp:LINE`) and from the verified sibling documents (linked by section). Where design choices follow from the facts, they are listed as **options with trade-offs**, not as decisions. Anything the source cannot settle is in [§10](#10-cross-document-notes-and-open-questions).

## Contents

- [Summary](#summary)
- [1. API surface census](#1-api-surface-census)
- [2. Execution-context constraints](#2-execution-context-constraints)
- [3. Synchronous and blocking semantics](#3-synchronous-and-blocking-semantics)
- [4. Object identity and lifetimes](#4-object-identity-and-lifetimes)
- [5. Event streams](#5-event-streams)
- [6. Existing external control surfaces](#6-existing-external-control-surfaces)
- [7. Coupling hotspots for removing SpiderMonkey](#7-coupling-hotspots-for-removing-spidermonkey)
- [8. Game-internals dependencies](#8-game-internals-dependencies)
- [9. Known defects that matter for the redesign](#9-known-defects-that-matter-for-the-redesign)
- [10. Cross-document notes and open questions](#10-cross-document-notes-and-open-questions)

Related documents: [architecture.md](architecture.md) · [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) (consolidated open questions) · [js-api/README.md](js-api/README.md) (JS API index) · [js-api/events.md](js-api/events.md) · [js-api/globals-core.md](js-api/globals-core.md) · [js-api/globals-game.md](js-api/globals-game.md) · [js-api/out-of-game.md](js-api/out-of-game.md) · [js-api/unit-properties.md](js-api/unit-properties.md) · [js-api/unit-methods.md](js-api/unit-methods.md) · [js-api/world.md](js-api/world.md) · [js-api/screenhooks.md](js-api/screenhooks.md) · [js-api/utility-classes.md](js-api/utility-classes.md) · [spidermonkey/embedding.md](spidermonkey/embedding.md) · [spidermonkey/jsapi-inventory.md](spidermonkey/jsapi-inventory.md) · [memory/README.md](memory/README.md) · [memory/offsets.md](memory/offsets.md) · [memory/patches-and-hooks.md](memory/patches-and-hooks.md) · [memory/call-stubs.md](memory/call-stubs.md) · [memory/structs.md](memory/structs.md). The Ghidra import ([ghidra/README.md](ghidra/README.md), `docs/ghidra/D2BSImport.java`) is the tool for the binary-level open questions.

Terms: **GL** = the game lock `Vars.cGameLoopSection` taken through `AutoCriticalRoom`/`CriticalRoom` (`CriticalSections.h:5-54`). **WFGR** = `WaitForGameReady()`, a 10 ms poll for up to `GameReadyTimeout` seconds (default 5, `0` = forever) while the client is `Busy` (`D2Helpers.cpp:153-166`, `Helpers.cpp:127`, `Helpers.cpp:144`). **Main thread** = the thread that owns the game window and runs the game loop. **IG/OOG** = in game / out of game (menu).

---

## Summary

- **Surface size.** 108 global function names (106 distinct natives; `utf8ToEuc` and `clearTimeout` are aliases) are registered in `global_funcs` (`JSGlobalFuncs.h:23-79`), and 21 classes in `global_classes` (`JSGlobalClasses.cpp:143-168`). The classes carry 87 instance methods, 9 static methods and 183 properties; the per-script `me` object adds an 80-property table (`JSUnit.h:160`). By category the globals are 28 game-state queries, 21 in-game actions, 6 out-of-game actions, 4 rendering helpers, 17 script-runtime/control functions, 25 host utilities and 7 diagnostics. 54 of the 108 globals never touch game memory ([§1](#1-api-surface-census)).
- **Every native runs on the calling script's own OS thread**, each script having a private `JSRuntime` (`Script.cpp:104-120`). Game memory is therefore read and written from many threads concurrently with the game's main thread ([§2](#2-execution-context-constraints)).
- **Only 15 natives take the game lock** (plus the helpers `GetLevel`, `RevealRoom` and the `ActMap` used by `getPath`/`getCollision`/`Area.exits`); every other game-touching native, all `Unit` property reads except `description`, all unit iteration, `Party`, `Room` getters and the whole out-of-game layer run unsynchronised ([§2.3](#23-unsynchronised-game-memory-access-risk-inventory); [jsapi-inventory.md §5.4](spidermonkey/jsapi-inventory.md#54-game-loop-lock-discipline)).
- **The game lock is a hand-off, not a mutex around game access.** The main thread holds `cGameLoopSection` permanently and yields it only in `TimerProc`, in game in `GameDraw` when a script is waiting, and around packet-event waits on the recorded game thread (`D2Handlers.cpp:410-418`, `D2Handlers.cpp:493-504`, `Events.cpp:347-355`). Out of game only `TimerProc` (and packet waits) yield, and whether `TimerProc` fires at all (it is armed cross-thread, `Helpers.cpp:180`) is an open question ([architecture.md §4.2](architecture.md#42-the-game-lock-cgameloopsection-in-detail)).
- **Synchronous verdicts block game threads.** `keydownblocker` (1000 ms), `chatmsgblocker`/`chatinputblocker` (500 ms), `gamepacket`/`gamepacketsent`/`realmpacket` (500 ms) and screen-hook `click` (3000 ms) make the producing thread wait for **each** listening script in turn, all through one process-wide manual-reset event `Vars.eventSignal` (`Helpers.cpp:155`), which races into use-after-free. `keyupblocker` and `whispermsgblocker` cost the wait but never block ([§3.1](#31-blocking-events-verdicts)).
- **Packet events see every game packet.** `gamepacket` fires for every received packet except Warden `0xAE` (which terminates the process, `D2Handlers.cpp:147-150`) and blocking it also suppresses D2BS's own handlers and the derived events `chatmsg`, `itemaction`, `gameevent`, `melife`, `memana` (`D2Handlers.cpp:151-166`) ([§5](#5-event-streams)).
- **Everything else is fire-and-forget with no metadata.** There are no event ids, timestamps, sequence numbers or acknowledgements; delivery happens only when the script pumps (`delay()`, the operation callback, `me.setSkill()`) ([events.md §10.3](js-api/events.md#103-drain-points-where-listeners-run)).
- **Timers are APCs** (`SetWaitableTimer` + `EventTimerProc`) that fire only during an alertable wait inside `delay()` or `SetSkill`; ids are process-global and the implementation has several bugs, one of which corrupts the lock that guards every event queue (`ScriptEngine.cpp:798-840`) ([§3.3](#33-timers)).
- **Identity is mostly "re-resolve by key" or "raw pointer".** `Unit` = `(gid, type)` re-resolved on every access and silently "unset" when stale; `Area` = level id; `Control` = `(type, x, y, w, h)`; `Room`, `Party`, `DailogLine` and `D2BSScript` hold raw game or engine pointers that nothing revalidates; `Exit`, `PresetUnit` and `Profile` are snapshots ([§4](#4-object-identity-and-lifetimes)).
- **Long calls without a per-call cancel exist:** `login()` (some states loop forever with input blocked), `getPath` (A* with no node cap while holding the game lock; it aborts only on `quit()`, a level change or game-not-ready), `sendCopyData` (`SendMessage`, no timeout), `getIP`, `Socket.open/read`, `D2BSScript.join()` (`INFINITE`), and WFGR inside most in-game natives ([§3.2](#32-natives-that-sleep-poll-or-wait)).
- **External control today is `WM_COPYDATA` to the game window**: `0x1337` evaluates arbitrary JS in the console script, `0x31337` switches profile (once, and only with `UseProfileScript=true`), any other code becomes a `copydata` event; outbound is `sendCopyData` to the `-handle` window. There is no authentication and no reply channel; the DDE server cannot work as written ([§6](#6-existing-external-control-surfaces)).
- **The patch and hook layer is JS-free.** The seam is `Events.cpp` (`*Event()` → `ScriptEngine::ForEachScript`) plus `ProcessCommand`; 44 pure-binding files (~11 kLOC) can go once the game logic embedded in the natives of [§7.2](#72-game-logic-living-inside-natives) is extracted (28 natives are classed "heavy" in [jsapi-inventory.md §5.1](spidermonkey/jsapi-inventory.md#51-native-inventory-generated)), and ~41 MB of `dependencies/` becomes removable ([§7](#7-coupling-hotspots-for-removing-spidermonkey)).
- **Some game-internals inputs are unverified or wrong**: the `RealmPacketRecv` patch at VA `0x44B1AE` has no 1.14d evidence but is installed unconditionally; the Fog `0x82E0` patch jumps to `0x576F06` instead of `0x40576F`; `unit.description` and `getBaseStat` use hard-coded absolute VAs; several live struct reads sit behind comment/layout discrepancies ([§8](#8-game-internals-dependencies)).
- **Reusing existing helpers inherits defects**, notably `GetLevel` leaking the game lock when the game is not ready (`D2Helpers.cpp:172-176`), the single global `ActMap` slot shared across threads (`Map/Diablo_II/ActMap.cpp:14-31`), and `ForEachScript` calling producers on an unlocked snapshot (`ScriptEngine.cpp:204-228`) ([§9](#9-known-defects-that-matter-for-the-redesign)).

---

## 1. API surface census

### 1.1 Counts

| Item | Count | Source |
|---|---|---|
| Global function names in `global_funcs` | 108 | `JSGlobalFuncs.h:23-79` |
| Distinct native functions behind them | 106 (`utf8ToEuc` → `my_stringToEUC`, `clearTimeout` → `my_clearInterval`) | `JSGlobalFuncs.h:40-42` |
| Commented-out global | 1 (`createCharacter`, native `JSMenu.cpp:165`) | `JSGlobalFuncs.h:55` |
| Classes in `global_classes` | 21 | `JSGlobalClasses.cpp:143-168` |
| Classes defined but not in `global_classes` | 2: `DailogLine` (instances only, built by `getDialogLines`), `ProfileType` (unreachable) | `JSGlobalClasses.cpp:116-122`, `JSGame.cpp:191` |
| Instance methods / static methods / properties on registered classes | 87 / 9 / 183 | spec tables in `JS*.h` (counted from source) |
| `me` property table | 80 properties, 10 writable | `JSUnit.h:160` |
| Event names that scripts can register for | 22 via `addEventListener` (`keyupblocker` is queued but never delivered, `ScriptEngine.cpp:634-635`) + the screen-hook `click` callback (hook `hover` is dead) | [events.md §1](js-api/events.md#1-summary-table) |
| Constants defined on the global | 3 (`FILE_READ`, `FILE_WRITE`, `FILE_APPEND`) | `ScriptEngine.cpp:369-371` |

### 1.2 Legend for the tables

| Column | Values |
|---|---|
| **Cat** | **Q** game-state query · **A** in-game action · **O** out-of-game/menu action · **R** rendering/screen hooks · **S** script runtime & control (load, include, delay, timers, events, messaging) · **H** host utility (file, dir, SQLite, socket, hash, clipboard, DDE, copydata, OS input) · **D** debugging/diagnostics |
| **State** | **IG** requires `ClientStateInGame` (returns a warning/`false`/`undefined` or throws otherwise) · **OOG** requires `ClientStateMenu` · **any** no state check |
| **Blocks / waits** | what can keep the calling script thread waiting beyond a trivial amount of time; "packet send" = may wait up to 500 ms for each *other* script with a `gamepacketsent` listener ([§3.1](#31-blocking-events-verdicts)) |
| **Game memory** | **R** reads game memory or calls read-only game functions · **W** writes game memory or calls game functions that change client state or send packets · **R/W** both · **–** neither |
| **Lock** | **GL** takes the game lock for (most of) the call · **GL\*** only transiently inside `GetLevel` · **–** none |

### 1.3 Global functions (108 names)

Derived from the per-function entries in the js-api docs and checked against the registration table `JSGlobalFuncs.h:23-79`. Footnotes follow the table.

| JS name | Cat | State | Blocks / waits | Game memory | Lock | Doc |
|---|---|---|---|---|---|---|
| `getUnit` | Q | IG¹ | – | R | – | [doc](js-api/unit-methods.md#getunittype-nameorclassid-mode-gid) |
| `getPath` | Q | IG | WFGR; whole A* under GL, no node cap, 5 ms yield every 500 ms | R/W | GL | [doc](js-api/globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) |
| `getCollision` | Q | IG | WFGR; GL wait | R/W | GL | [doc](js-api/globals-game.md#getcollisionarea-x-y) |
| `getMercHP` | Q | IG | WFGR | R | – | [doc](js-api/unit-methods.md#getmerchp) |
| `getCursorType` | Q | any | – | R | – | [doc](js-api/globals-game.md#getcursortypetype) |
| `getSkillByName` | Q | any | – | – | – | [doc](js-api/globals-game.md#getskillbynamename) |
| `getSkillById` | Q | any | – | R | – | [doc](js-api/globals-game.md#getskillbyidid) |
| `getLocaleString` | Q | any | – | R | – | [doc](js-api/globals-game.md#getlocalestringid) |
| `getTextSize` | R | any | – | R/W² | – | [doc](js-api/globals-game.md#gettextsizetext-font-asobject) |
| `getThreadPriority` | D | any | – | – | – | [doc](js-api/globals-core.md#getthreadpriority) |
| `getUIFlag` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#getuiflagid) |
| `getTradeInfo` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#gettradeinfomode) |
| `getWaypoint` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#getwaypointindex) |
| `getScript` | S | any | script-list lock | – | – | [doc](js-api/utility-classes.md#getscriptselector) |
| `getScripts` | S | any | script-list lock held while building | – | – | [doc](js-api/utility-classes.md#getscripts) |
| `getRoom` | Q | IG | WFGR (throws); GL wait | R/W | GL | [doc](js-api/world.md#getroomarea--x-y--area-x-y) |
| `getParty` | Q | IG | WFGR | R | – | [doc](js-api/world.md#getpartyname--gid--unit) |
| `getPresetUnit` | Q | IG | WFGR; GL wait | R/W | GL | [doc](js-api/world.md#getpresetunitarea-type-classid) |
| `getPresetUnits` | Q | IG | WFGR; GL wait | R/W | GL | [doc](js-api/world.md#getpresetunitsarea-type-classid) |
| `getArea` | Q | IG | WFGR (throws); GL wait | R/W | GL* | [doc](js-api/world.md#getareaarea) |
| `getBaseStat` | Q | any | – | R | – | [doc](js-api/globals-game.md#getbasestattable-row-column) |
| `getControl` | Q | OOG | – | R | – | [doc](js-api/out-of-game.md#getcontroltype-x-y-xsize-ysize) |
| `getControls` | Q | OOG | – | R | – | [doc](js-api/out-of-game.md#getcontrols) |
| `getPlayerFlag` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#getplayerflagunitid1-unitid2-flag) |
| `getTickCount` | H | any | – | – | – | [doc](js-api/globals-core.md#gettickcount) |
| `getInteractedNPC` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#getinteractednpc) |
| `getIsTalkingNPC` | Q | IG | WFGR ×2 | R | – | [doc](js-api/globals-game.md#getistalkingnpc) |
| `getDialogLines` | Q | any | GL wait | R | GL | [doc](js-api/globals-game.md#getdialoglines) |
| `print` | D | any | – (queued, drawn by game thread) | – | – | [doc](js-api/globals-core.md#printvalues) |
| `stringToEUC` | H | any | – | – | – | [doc](js-api/globals-core.md#stringtoeucvalue) |
| `utf8ToEuc` | H | any | – (alias of `stringToEUC`) | – | – | [doc](js-api/globals-core.md#utf8toeucvalue) |
| `setTimeout` | S | any | – | – | – | [doc](js-api/globals-core.md#settimeoutcallback-ms) |
| `clearTimeout` | S | any | – (alias of `clearInterval`) | – | – | [doc](js-api/globals-core.md#cleartimeoutid) |
| `setInterval` | S | any | – | – | – | [doc](js-api/globals-core.md#setintervalcallback-ms) |
| `clearInterval` | S | any | – | – | – | [doc](js-api/globals-core.md#clearintervalid) |
| `delay` | S | any | **ms**; pumps events | – | – | [doc](js-api/globals-core.md#delayms) |
| `load` | S | any | ≤ 500 ms (stops older instance) | – | – | [doc](js-api/globals-core.md#loadfile-args) |
| `isIncluded` | S | any | – | – | – | [doc](js-api/globals-core.md#isincludedfile) |
| `include` | S | any | runs file synchronously under `Script::lock` | – | – | [doc](js-api/globals-core.md#includefile) |
| `stop` | S | any | ≤ 500 ms per other script; never returns | – | – | [doc](js-api/globals-core.md#stopself) |
| `stacktrace` | D | any | walks every thread | – | – | [doc](js-api/globals-core.md#stacktrace) |
| `rand` | H | any | – | W³ | – | [doc](js-api/globals-game.md#randlow-high) |
| `copy` | H | any | – | – | – | [doc](js-api/globals-core.md#copytext) |
| `paste` | H | any | – | – | – | [doc](js-api/globals-core.md#paste) |
| `sendCopyData` | H | any | **`SendMessage`, no timeout** | – | – | [doc](js-api/globals-core.md#sendcopydatawindowclass-windownameorhwnd-mode-data) |
| `sendDDE` | H | any | ≤ 5 s per transaction | – | – | [doc](js-api/globals-core.md#sendddemode-server-topic-item-data) |
| `keystate` | H | any | – | – | – | [doc](js-api/globals-core.md#keystatevk) |
| `addEventListener` | S | any | – | – | – | [doc](js-api/globals-core.md#addeventlistenername-listener) |
| `removeEventListener` | S | any | – | – | – | [doc](js-api/globals-core.md#removeeventlistenername-listener) |
| `clearEvent` | S | any | – | – | – | [doc](js-api/globals-core.md#cleareventname) |
| `clearAllEvents` | S | any | – | – | – | [doc](js-api/globals-core.md#clearallevents) |
| `js_strict` | S | any | – | – | – | [doc](js-api/globals-core.md#js_strictenable) |
| `version` | D | any | – | – | – | [doc](js-api/globals-core.md#versionprint) |
| `scriptBroadcast` | S | any | – (one clone per recipient) | – | – | [doc](js-api/globals-core.md#scriptbroadcastvalues) |
| `sqlite_version` | H | any | – | – | – | [doc](js-api/utility-classes.md#sqlite_version) |
| `sqlite_memusage` | H | any | – | – | – | [doc](js-api/utility-classes.md#sqlite_memusage) |
| `dopen` | H | any | – | – | – | [doc](js-api/utility-classes.md#dopenname) |
| `debugLog` | D | any | file I/O | – | – | [doc](js-api/globals-core.md#debuglogvalues) |
| `showConsole` | D | any | – | – | – | [doc](js-api/globals-core.md#showconsole) |
| `hideConsole` | D | any | – | – | – | [doc](js-api/globals-core.md#hideconsole) |
| `handler` | H | any | – | – | – | [doc](js-api/globals-core.md#handler) |
| `login` | O | OOG | **until done / error / timeout; some states loop forever** | R/W | – | [doc](js-api/out-of-game.md#loginprofile) |
| `selectCharacter` | O | OOG | ≤ 600 ms | R/W | – | [doc](js-api/out-of-game.md#selectcharacterprofile) |
| `createGame` | O | OOG | ≈ 1.2 s | R/W | – | [doc](js-api/out-of-game.md#creategamename-password-difficulty) |
| `joinGame` | O | OOG | ≈ 0.7 s | R/W | – | [doc](js-api/out-of-game.md#joingamename-password) |
| `addProfile` | O | any | INI file I/O | – | – | [doc](js-api/out-of-game.md#addprofileprofile-mode-gateway-username-password-character-spdifficulty) |
| `getLocation` | Q | OOG | – | R | – | [doc](js-api/out-of-game.md#getlocation) |
| `loadMpq` | O | any | MPQ load | W | – | [doc](js-api/globals-core.md#loadmpqpath) |
| `submitItem` | A | IG | WFGR; packet send⁵ (Act II orifice branch) | W | – | [doc](js-api/globals-game.md#submititem) |
| `getMouseCoords` | Q | any | – | R | – | [doc](js-api/globals-game.md#getmousecoordstomap-asobject) |
| `copyUnit` | Q | any | – | – | – | [doc](js-api/globals-game.md#copyunitunit) |
| `clickMap` | A | IG | WFGR | W | – | [doc](js-api/globals-game.md#clickmaptype-shift-unit--x-y) |
| `acceptTrade` | A | IG | WFGR; GL wait (action modes) | R/W | GL | [doc](js-api/globals-game.md#accepttrademode) |
| `tradeOk` | A | IG | WFGR; GL wait | W | GL | [doc](js-api/globals-game.md#tradeok) |
| `beep` | H | any | – | – | – | [doc](js-api/globals-core.md#beeptype) |
| `clickItem` | A | IG | WFGR; GL wait | W | GL | [doc](js-api/globals-game.md#clickitemitem--clicktype-bodyloc--clicktype-item--button-x-y-location) |
| `getDistance` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#getdistancea-b-c-d) |
| `gold` | A | IG | WFGR | W | – | [doc](js-api/globals-game.md#goldamount-mode) |
| `checkCollision` | Q | IG | WFGR | R | – | [doc](js-api/globals-game.md#checkcollisionunita-unitb-mask) |
| `playSound` | A | any | – (no-op) | – | – | [doc](js-api/globals-game.md#playsoundid) |
| `quit` | A | any | – | W | – | [doc](js-api/globals-game.md#quit) |
| `quitGame` | A | any | `Shutdown()` waits `INFINITE` for D2Thread, then `TerminateProcess` | W | – | [doc](js-api/globals-game.md#quitgame) |
| `say` | A | any⁴ | – | W | – | [doc](js-api/globals-game.md#sayvalues) |
| `clickParty` | A | IG | WFGR | W | – | [doc](js-api/globals-game.md#clickpartyparty-mode) |
| `weaponSwitch` | A | IG | WFGR; packet send⁵ | W | – | [doc](js-api/globals-game.md#weaponswitchquery) |
| `transmute` | A | IG | WFGR | W | – | [doc](js-api/globals-game.md#transmute) |
| `useStatPoint` | A | IG | WFGR; `Sleep(500)` × (count − 1) | W | – | [doc](js-api/globals-game.md#usestatpointstat-count) |
| `useSkillPoint` | A | IG | WFGR; `Sleep(500)` × (count − 1) | W | – | [doc](js-api/globals-game.md#useskillpointskill-count) |
| `takeScreenshot` | R | any | – (deferred to next draw) | W⁶ | – | [doc](js-api/globals-game.md#takescreenshot) |
| `moveNPC` | A | IG⁷ | WFGR ×2; packet send⁵ | W | – | [doc](js-api/globals-game.md#movenpcnpc-x-y) |
| `getPacket` | A | any⁷ | runs the game receive path | W | – | [doc](js-api/globals-core.md#getpacket) |
| `sendPacket` | A | any⁷ | packet send⁵ | W | – | [doc](js-api/globals-core.md#sendpacket) |
| `getIP` | H | any | **synchronous HTTP** | – | – | [doc](js-api/globals-core.md#getip) |
| `sendClick` | A | any | ≈ 300 ms `Sleep` | –⁸ | – | [doc](js-api/globals-core.md#sendclickx-y) |
| `sendKey` | A | any | ≈ 300 ms `Sleep` | –⁸ | – | [doc](js-api/globals-core.md#sendkeyvk) |
| `revealLevel` | A | IG | GL wait, then held for the whole level (no WFGR) | W | GL | [doc](js-api/globals-game.md#reveallevelpresets) |
| `screenToAutomap` | R | any | – | R | – | [doc](js-api/screenhooks.md#screentoautomappoint--x-y) |
| `automapToScreen` | R | any | – | R | – | [doc](js-api/screenhooks.md#automaptoscreenpoint--x-y) |
| `md5` | H | any | – | – | – | [doc](js-api/globals-core.md#md5str) |
| `sha1` | H | any | – | – | – | [doc](js-api/globals-core.md#sha1str) |
| `sha256` | H | any | – | – | – | [doc](js-api/globals-core.md#sha256str) |
| `sha384` | H | any | – | – | – | [doc](js-api/globals-core.md#sha384str) |
| `sha512` | H | any | – | – | – | [doc](js-api/globals-core.md#sha512str) |
| `md5_file` | H | any | file I/O | – | – | [doc](js-api/globals-core.md#md5_filepath) |
| `sha1_file` | H | any | file I/O | – | – | [doc](js-api/globals-core.md#sha1_filepath) |
| `sha256_file` | H | any | file I/O | – | – | [doc](js-api/globals-core.md#sha256_filepath) |
| `sha384_file` | H | any | file I/O | – | – | [doc](js-api/globals-core.md#sha384_filepath) |
| `sha512_file` | H | any | file I/O | – | – | [doc](js-api/globals-core.md#sha512_filepath) |

Footnotes:
1. `getUnit(100)` (cursor item) and `getUnit(101)` (selected unit) skip the state check (`JSUnit.cpp:603-608`); every other form needs `ClientStateInGame` with no waiting (`Unit.cpp:43`).
2. `getTextSize` calls `D2WIN_SetTextSize` (a global font setting) and restores it (`D2Helpers.cpp:212-223`), racing `TextHook::Draw` on the main thread ([screenhooks.md](js-api/screenhooks.md#threading-and-locking)).
3. In game `rand` passes the player's `dwSeed[2]` to `D2GAME_Rand` (`JSGame.cpp:690-694`, `D2Structs.h:620`); whether that advances the client's RNG state in place is an open question.
4. `say` has no `ClientState` check. While a player unit exists (`*p_D2CLIENT_PlayerUnit`) it copies into `p_D2CLIENT_ChatMsg` and enters `D2CLIENT_Say_I` mid-function through `Say_ASM`; otherwise it uses `D2MULTI_DoChat` when the channel screen's controls are present. Either way it first sets the one-shot `Vars.bDontCatchNextMsg` (`Core.cpp:85-132`).
5. Natives that call `D2NET_SendPacket` directly (`JSCore.cpp:608`, `JSGame.cpp:1250`, `JSGame.cpp:1359`, `JSGame.cpp:1451`, `JSUnit.cpp:787`, `JSUnit.cpp:842`, `JSUnit.cpp:849`, `JSUnit.cpp:1792`) run the caller's own `gamepacketsent` listeners inline and wait up to 500 ms for every other listening script ([events.md `gamepacketsent`](js-api/events.md#gamepacketsent)).
6. `takeScreenshot` only sets `Vars.bTakeScreenshot`; `D2WIN_TakeScreenshot` runs on the main thread in the next `GameDraw`/`GameDrawOOG` (`JSGame.cpp:1416-1419`, `D2Handlers.cpp:406-409`, `D2Handlers.cpp:429-432`).
7. `moveNPC`, `getPacket` and `sendPacket` require `EnableUnsupported=true` (`JSGame.cpp:1425-1427`, `JSCore.cpp:572-574`, `JSCore.cpp:617-619`); `sendPacket`/`getPacket` have no client-state check.
8. `sendClick`/`sendKey` post `WM_LBUTTON*`/`WM_KEY*` messages to the game window (`D2Helpers.cpp:305-334`); they do not touch game memory themselves.

Totals: Q 28, A 21, O 6, R 4, S 17, H 25, D 7. State: 30 IG, 7 OOG, 71 any. Game memory: 22 R, 20 W, 12 R/W, 54 none. Lock: 10 GL, 1 GL\*.

### 1.4 Classes

"Ctor" is what `new X()` does (`EMPTY_CTOR` throws `"Invalid Operation"`, `js32.h:136-139`). "Props (w)" = properties (writable; a setter on a `JSPROP_READONLY` entry such as `Control.disabled` is not counted). Instances are built with `BuildObject`, which defines own copies of the methods and properties on every object (`js32.cpp:8-28`).

| Class | Row | Ctor | Methods | Static | Props (w) | Cat | State | Game memory | Identity (see [§4](#4-object-identity-and-lifetimes)) | Doc |
|---|---|---|---|---|---|---|---|---|---|---|
| `Unit` | `JSGlobalClasses.cpp:145` | throws | 25 | – | 49 (0); `me` 80 (10) | Q/A | IG | R/W | `(gid, type)` re-resolved per access | [props](js-api/unit-properties.md#unit), [methods](js-api/unit-methods.md#method-summary) |
| `PresetUnit` | `JSGlobalClasses.cpp:146` | throws | 0 | – | 7 (0) | Q | IG to create | – after creation | snapshot | [doc](js-api/world.md#presetunit) |
| `Area` | `JSGlobalClasses.cpp:147` | throws | 0 | – | 7 (0) | Q | IG | R/W (`InitLevel`) | level id; `exits` cached | [doc](js-api/world.md#area) |
| `Control` | `JSGlobalClasses.cpp:148` | throws | 4 | – | 12 (3) | O | OOG | R/W | `(type, x, y, w, h)` re-resolved | [doc](js-api/out-of-game.md#control) |
| `Folder` | `JSGlobalClasses.cpp:149` | throws | 4 | – | 1 (0) | H | any | – | path | [doc](js-api/utility-classes.md#folder) |
| `Exit` | `JSGlobalClasses.cpp:150` | throws | 0 | – | 6 (0) | Q | IG to create | – after creation | snapshot | [doc](js-api/world.md#exit) |
| `Party` | `JSGlobalClasses.cpp:151` | throws | 1 | – | 10 (0) | Q | IG | R | raw `RosterUnit*` | [doc](js-api/world.md#party) |
| `Room` | `JSGlobalClasses.cpp:152` | throws | 9 | – | 9 (0) | Q (+`reveal` A) | IG | R/W | raw `Room2*` | [doc](js-api/world.md#room) |
| `File` | `JSGlobalClasses.cpp:154` | throws | 11 | 1 (`open`) | 13 (1) | H | any | – | `FILE*` | [doc](js-api/utility-classes.md#file) |
| `Socket` | `JSGlobalClasses.cpp:155` | throws | 3 | 1 (`open`) | 2 (0) | H | any | – | `SOCKET` | [doc](js-api/utility-classes.md#socket) |
| `FileTools` | `JSGlobalClasses.cpp:156` | throws | 0 | 7 | 0 | H | any | – | static only | [doc](js-api/utility-classes.md#filetools) |
| `SQLite` | `JSGlobalClasses.cpp:157` | constructs | 4 | – | 5 (0) | H | any | – | `sqlite3*` | [doc](js-api/utility-classes.md#sqlite) |
| `DBStatement` | `JSGlobalClasses.cpp:158` | throws | 10 | – | 2 (0) | H | any | – | `sqlite3_stmt*` | [doc](js-api/utility-classes.md#dbstatement) |
| `Sandbox` | `JSGlobalClasses.cpp:159` | crashes (NULL runtime) | 4 | – | 0 | S | any | – | `JSContext*` | [doc](js-api/utility-classes.md#sandbox) |
| `D2BSScript` | `JSGlobalClasses.cpp:160` | throws | 6 | – | 5 (0) | S | any | – | borrowed `Script*` | [doc](js-api/utility-classes.md#d2bsscript) |
| `Frame` | `JSGlobalClasses.cpp:162` | constructs | 1 | – | 9 (9) | R | any | – (drawn on main thread) | owned C++ hook | [doc](js-api/screenhooks.md#frame) |
| `Box` | `JSGlobalClasses.cpp:163` | constructs | 1 | – | 11 (11) | R | any | – | owned C++ hook | [doc](js-api/screenhooks.md#box) |
| `Line` | `JSGlobalClasses.cpp:164` | constructs | 1 | – | 9 (9) | R | any | – | owned C++ hook | [doc](js-api/screenhooks.md#line) |
| `Text` | `JSGlobalClasses.cpp:165` | constructs | 1 | – | 10 (10) | R | any | – | owned C++ hook | [doc](js-api/screenhooks.md#text) |
| `Image` | `JSGlobalClasses.cpp:166` | constructs | 1 | – | 8 (8) | R | any | – | owned C++ hook | [doc](js-api/screenhooks.md#image) |
| `Profile` | `JSGlobalClasses.cpp:167` | constructs | 1 (`login`) | – | 8 (0) | O | any (`login` needs OOG) | R/W via `login` | INI snapshot | [doc](js-api/out-of-game.md#profile) |
| `DailogLine` (sic) | not registered | – | own `handler` | – | 2 own data props | A | any | W (`handler()` calls the game) | raw dialog-line pointer | [doc](js-api/globals-game.md#dailogline) |
| `ProfileType` | not registered | – | – | – | 5 (unreachable) | – | – | – | – | [doc](js-api/out-of-game.md#profiletype-not-registered) |

### 1.5 What the census implies

- **About half the surface is not game API.** The 25 host utilities (all except `rand`, which uses the player's seed in game) and the `File`/`FileTools`/`Folder`/`SQLite`/`DBStatement`/`Socket` classes have no game dependency and no non-JS consumer ([jsapi-inventory.md §7.8](spidermonkey/jsapi-inventory.md#78-classes-whose-only-consumer-is-js)). A client running elsewhere has its own file, database, socket and hash facilities. The utilities that act on the game machine itself (clipboard `copy`/`paste`, `keystate`, `beep`, `sendCopyData`/`sendDDE` to local windows, `getIP` as seen from that host, files under the game's script directory) only have meaning there.
- **The script-runtime functions (17 globals, `D2BSScript`, `Sandbox`) describe the embedded-engine model itself:** threads per script, include, timers, listener registration, messaging. If scripts leave the process, these become session, subscription and job-control concepts of the RPC protocol rather than calls ([§7.4](#74-engine-responsibilities-that-need-a-non-js-home)).
- **Queries dominate the game part (28 of 55 game globals plus all class getters).** Most read live memory without a lock ([§2.3](#23-unsynchronised-game-memory-access-risk-inventory)); a remote client calling them one property at a time would multiply the cost of `ClientState()` + `D2CLIENT_FindUnit` that every `Unit` property read already pays ([unit-properties.md](js-api/unit-properties.md#identity-resolution-and-lifetime)).
- **Rendering is small and already C++-side.** Screen hooks are `Genhook` objects drawn by the main thread; JS only constructs, mutates and owns them ([screenhooks.md](js-api/screenhooks.md#facts-relevant-to-an-rpc-replacement)).

---

## 2. Execution-context constraints

### 2.1 Which thread runs what today

| Kind of operation | Thread | Holds GL? | Source |
|---|---|---|---|
| Every JS native, property getter/setter, event listener and timer callback | the owning script's OS thread (one per script, own `JSRuntime`) | only inside GL-taking natives | `Script.cpp:104-120`; [globals-core.md](js-api/globals-core.md#threading) |
| Console evaluation (prompt line, chat `.exec`, `WM_COPYDATA 0x1337`) | queued from the main thread, evaluated on the console script's thread | no | `ScriptEngine.cpp:56-69`, `Script.cpp:77-102`, `D2Handlers.cpp:184-189` |
| Built-in commands `start`/`stop`/`flush`/`load`/`reload` typed at the console or as `.cmd` in game chat | main thread (`KeyPress` / `GameInput`) | yes, once the hand-off has started | `Helpers.cpp:252-313`, `D2Handlers.cpp:121-131` |
| Keyboard and mouse hooks, subclassed WndProc, `TimerProc` | main (window) thread | yes, after the first hand-off | `D2Handlers.cpp:176-351`, `D2Handlers.cpp:493-504` |
| Game packet receive, player assignment, game leave, in-game chat input, act change, attack rewrite intercepts | main thread (inferred from the game loop, not proven) | yes | `Patch.h:9-21`; [architecture.md §2.2](architecture.md#22-entry-points-on-game-threads-hooks-intercepts-window-procedure) |
| BNCS chat (`0x521B20`), realm/MCP (`0x44B1AE`), channel input (`0x442A61`), whisper (`0x448813`) intercepts | **not determinable from source** | unknown | [architecture.md §11](architecture.md#11-open-questions) item 1 |
| Packet-send intercept (`0x52AE5A`) | whichever thread calls `D2NET_SendPacket`: game or script | that thread's state | `D2Handlers.cpp:172-174`, `Events.cpp:306-307` |
| Drawing: screen hooks, console, `print()` flush, screenshots | main thread in `GameDraw` (in game) / `GameDrawOOG` (menu) | in game: yes | `D2Handlers.cpp:399-434` |
| Script auto-start on join and first menu, chicken / max-game-time exits, `-mpq`, `-profile`, `StartAtMenu` | `D2Thread` (50 ms poll) | no | `D2Handlers.cpp:29-119`, `Helpers.cpp:192-206` |
| Stopping `InGame` scripts on leave | main thread in `GameLeave`, up to 300 ms per script | yes | `D2Handlers.cpp:506-524`, `Script.cpp:269-278` |
| Patch installation, DDE server initialisation | the `LoadLibrary` caller inside `DllMain` | n/a | `D2BS.cpp:108-141` |
| `ClientState()` | every thread, unlocked | no | `D2Helpers.cpp:125-147` |

### 2.2 Locks and which natives take them

Full inventory: [architecture.md §4.1](architecture.md#41-inventory), [embedding.md §9](spidermonkey/embedding.md#9-locks-and-synchronisation-objects).

| Lock | Protects | Taken by (natives or paths) | Notes |
|---|---|---|---|
| `Vars.cGameLoopSection` (GL) | the game loop vs script threads, by hand-off | 15 natives: `acceptTrade` (action modes), `tradeOk`, `getDialogLines`, `clickItem`, `revealLevel`, `getPresetUnit(s)`, `Room.getPresetUnits/getCollision/getCollisionA/getStat/reveal`, `getRoom`, `unit.description`, `item.shop` (`JSGame.cpp:125`, `:151`, `:181`, `:364`, `:1474`; `JSPresetUnit.cpp:79`, `:162`; `JSRoom.cpp:89`, `:142`, `:219`, `:340`, `:443`, `:460`; `JSUnit.cpp:448`, `:1470`). Helpers `GetLevel` (`D2Helpers.cpp:173`) and `RevealRoom` (`Room.cpp:14`). `ActMap` holds it from construction to `CleanUp` (`Map/Diablo_II/ActMap.cpp:44-45`, `:188-202`) for `getPath`, `getCollision`, `Area.exits`. | Main thread holds it except in `TimerProc` and in-game `GameDraw` windows (`D2Handlers.cpp:410-418`, `:493-504`). Packet events release it around their wait only on `Vars.dwGameThreadId` (`Events.cpp:347-355`). |
| `Vars.cEventSection` | every script's `EventList`; `DelayedExecList` push | `FireEvent` from any producer thread, drains in `delay()`/operation callback/`SetSkill`, `D2BSScript.send` | One lock for all scripts. Left without being entered by `RemoveDelayedEvent` (`ScriptEngine.cpp:835`). |
| `ScriptEngine::scriptListLock` | `ScriptEngine::scripts` map | `ForEachScript` snapshot, `getScript(s)`, `D2BSScript.getNext/send`, `DisposeScript` | Not taken by `CompileFile`'s insert (`ScriptEngine.cpp:39-43`); callbacks run after it is released (`ScriptEngine.cpp:210-224`). |
| `Script::lock` (per script) | thread handle, stop state, includes, listener map | `Stop` (held while polling up to 500 ms), `Join`, `Include` (**held while the included code runs**), listener (un)registration | `Script.cpp:251-280`, `Script.cpp:296-336` |
| `Genhook::globalSection` | screen-hook lists | hook ctor/dtor/`remove`, `visible`/`text` setters, finalizer, `Genhook::Clean`; held by every draw pass and by click dispatch **including its 3000 ms waits** | `ScreenHook.cpp:58-247` |
| `Vars.cPrintSection`, `cConsoleSection`, `cFileSection`, `cFlushCacheSection`, `ActMap::lock` | print queue; console buffers; `FileTools.writeText/appendText`; `FlushCache`; `ActMap::GetExits` | as named | leaf locks |
| `Vars.eventSignal` (event, not a lock) | blocking-event rendezvous | every blocker producer and consumer | single manual-reset event for the whole process (`Helpers.cpp:155`) |
| Dead or no-op | `cRoomSection`, `cMiscSection`, `cScreenhookSection`, `cUnitListSection`, `ScriptEngine::lock` (never initialised), `CSyncObj` (`Lock`/`Unlock` empty), per-hook `Genhook::Lock()`/`Unlock()` (bodies commented out), `cTextHookSection`/`cImageHookSection`/`cLineHookSection`/`cBoxHookSection`/`cFrameHookSection` (entered only around each draw call on the main thread, so they exclude nothing), `p_D2NET_CriticalPacketSection` (never taken; offset suspect) | – | `D2BS.cpp:110-122`, `ScriptEngine.cpp:121`, `SyncObj.h:29-34`, `ScreenHook.h:182-184`, `ScreenHook.cpp:324-326`, `D2Ptrs.h:370` |

### 2.3 Unsynchronised game-memory access (risk inventory)

Everything below runs on a non-main thread with no GL while the main thread may mutate or free the same structures. "Failure" is what can follow from the code path; none is proven to occur at a given rate.

| # | Area | Natives / paths | What is touched without a lock | Possible failure | Source |
|---|---|---|---|---|---|
| 1 | Client-state gate | every state-checking native, `D2Thread`, the operation callback | `D2CLIENT_GetPlayerUnit()`, `*p_D2WIN_FirstControl`, `player->pPath->pRoom1->pRoom2->pLevel` chain | stale or torn state; dereference of a chain being torn down | `D2Helpers.cpp:125-147` |
| 2 | `Unit` properties | all `unit_props`/`me_props` except `description` | `UnitAny` and `pPath`, `pItemData`, `pMonsterData`, `pStats`; D2 getters | unit freed between `D2CLIENT_FindUnit` and the dereference (use-after-free) | `JSUnit.cpp:183-522`; [unit-properties.md](js-api/unit-properties.md#threading-and-memory-safety) |
| 3 | Unit search and iteration | `getUnit`, `Unit.getNext`, `getItem`, `getItems` | unit hash tables and `pListNext` chains; inventory lists | following a freed link; missed or repeated units | `Unit.cpp:14-54`, `Unit.cpp:99-151`, `Unit.cpp:214-236`; [unit-methods.md](js-api/unit-methods.md#concurrency-and-staleness) |
| 4 | Unit reads via helpers | `getStat`, `getSkill`, `getParent`, `getMerc`, `getMercHP` (walks act rooms), `getEnchant`, `get*Cost` | stat lists, room unit lists, `pInfo` | as row 2 | `JSUnit.cpp:891-1028`, `D2Helpers.cpp:482-498` |
| 5 | Unit actions | `interact`, `move`, `cancel`, `repair`, `revive`, `setSkill`, `overhead`, `useMenu` | `ClickMap` (saves/zeroes/restores `MouseX/Y`, sets `Vars.dwSelectedUnitId/bClickAction`), packets, `pUnit->pOMsg` write, NPC menu callbacks | game input code running concurrently with the main thread; cross-script races on the process-wide click globals | `Core.cpp:134-179`, `JSUnit.cpp:1771-1775`; [call-stubs.md §7](memory/call-stubs.md#7-thread-and-lock-context) |
| 6 | `me` setters | `runwalk`, `automap`, `nopickup` | `p_D2CLIENT_AlwaysRun`, `AutomapOn`, `NoPickUp` | plain racing stores | `JSUnit.cpp:527-570` |
| 7 | In-game queries | `getUIFlag`, `getWaypoint`, `getPlayerFlag`, `getDistance`, `checkCollision`, `getTradeInfo`, `getInteractedNPC`, `getIsTalkingNPC`, `getMouseCoords`, `getCursorType`, `getBaseStat`, `getSkillById`, `getLocaleString` | game globals, data tables, STORM window-handler table | stale values; data tables are presumably static once loaded (not shown by source) | [globals-game.md summary](js-api/globals-game.md#summary-table) |
| 8 | In-game actions | `clickMap`, `clickParty`, `gold`, `say`, `weaponSwitch`, `transmute`, `submitItem`, `useStatPoint`, `useSkillPoint`, `moveNPC`, `quit`, `quitGame`, `DailogLine.handler` | UI state vars, chat buffers, party/trade code, `D2CLIENT_ExitGame` | game UI/state code entered from a foreign thread | [call-stubs.md §7](memory/call-stubs.md#7-thread-and-lock-context) |
| 9 | Raw packets | `sendPacket`, `getPacket`, every direct `D2NET_SendPacket` caller | game network code; the game's own packet lock is never taken | concurrent sends with the game's own; injected receive path | `JSCore.cpp:608`, `JSCore.cpp:653`, `D2Ptrs.h:370` |
| 10 | World objects | `Room` getters, `getNext`, `getNearby`, `getFirst`, `unitInRoom`; all of `Party`; `Area` getters after `GetLevel` returns; `getPresetUnit(s)` between `GetLevel` and its re-lock | `Room2*`, `RosterUnit*`, `Level*` held across unlocked windows | use-after-free after act change, leave or roster change | [world.md](js-api/world.md#races-and-thread-safety-summary) items 5, 6, 8 |
| 11 | Out of game | `getControl(s)`, `Control.*`, `login`, `selectCharacter`, `createGame`, `joinGame`, `getLocation` | D2WIN control list and `Control` structs; `D2WIN_SetControlText` called on the script thread | list rebuilt by the main thread mid-walk | [out-of-game.md](js-api/out-of-game.md#facts-for-an-rpc-replacement) |
| 12 | Screen hooks and fonts | hook property setters (plain stores), `Image.location` (frees the `CellFile` being drawn), `getTextSize`, `screenToAutomap`, `automapToScreen`; image cache `Vars.mCachedCellFiles` | draw-thread data | torn draws; use-after-free on `location`; unlocked `std::map` | [screenhooks.md](js-api/screenhooks.md#threading-and-locking), `D2Helpers.cpp:511-553` |
| 13 | `D2Thread` | chicken/max-time `D2CLIENT_ExitGame`, `D2CLIENT_InitInventory`, `LoadMPQ`, `clickControl` at start | game exit, inventory init, MPQ load | as row 8 | `D2Handlers.cpp:49-55`, `D2Handlers.cpp:73-83`, `Helpers.cpp:198-206` |
| 14 | Process-wide D2BS state shared by scripts | `Vars.dwSelectedUnitId/Type`, `bClickAction`, `bDontCatchNextMsg`, `bBlockKeys/bBlockMouse` (overwritten by `login`); the `me` setters `chickenhp`, `chickenmp`, `quitonhostile`, `quitonerror`, `maxgametime`, `blockKeys`, `blockMouse` also write process-wide `Vars` | D2BS globals with no lock | one script's click, chat line or setting takes effect for every other script | `Core.cpp:93`, `Core.cpp:156-173`, `Profile.cpp:112`, `Profile.cpp:294`, `JSUnit.cpp:531-558` |

### 2.4 Operations tied to the main thread today

What the source shows, without claiming which game functions are thread-safe (that is not determinable from the repository):

- **Only ever run on the main thread:** all drawing (`D2GFX_Draw*`, `D2WIN_DrawText`, `D2GFX_DrawAutomapCell2`) from `Genhook::DrawAll`, `Console::Draw` and `FlushPrint`, and `D2WIN_TakeScreenshot`. `print()` and `takeScreenshot()` reach them by **queueing** (`Core.cpp:51-65`, `JSGame.cpp:1416-1419`, `D2Handlers.cpp:399-434`). This is the one existing "marshal onto the game thread" pattern.
- **Serialised with the main thread by GL:** room loading (`D2COMMON_AddRoomData`/`RemoveRoomData`, `InitLevel`), automap reveal, collision and path reads, trade accept/OK, dialog-line listing, inventory clicks, shop actions and the item-description buffer ([world.md](js-api/world.md#room-loading-addroomdata--removeroomdata); [jsapi-inventory.md §5.4](spidermonkey/jsapi-inventory.md#54-game-loop-lock-discipline)).
- **Game-state-changing calls made from other threads without GL:** `ClickMap` (`clickMap`, `interact`, `move`), `Say_I` (`say`), `D2WIN_SetControlText` (`login`, `createGame`, `joinGame`, `Control.setText`/`text=`), `D2NET_SendPacket`/`D2CLIENT_SendGamePacket` (footnote 5 senders, `setSkill`, `useStatPoint`, `useSkillPoint`), `D2NET_ReceivePacket` (`getPacket`), `D2CLIENT_ExitGame` (`quit`, `quitGame`, `D2Thread`, and `reportError` on the script thread when `QuitOnError` is set, `ScriptEngine.cpp:446-447`), `D2CLIENT_SetUIVar` (`transmute`), party and gold actions, `DailogLine.handler`, `D2WIN_InitMPQ` (`loadMpq`, `-mpq`).
- **Win32 constraints:** the keyboard/mouse hooks are thread-local to the window thread (`Helpers.cpp:182-188`); `me.windowtitle` calls `GetWindowTextW` on another thread's window, which sends `WM_GETTEXT` synchronously (`JSUnit.cpp:140-144`); `SetTimer` is called from `D2Thread` for a window it does not own (`Helpers.cpp:180`); DDEML callbacks arrive on the thread that called `DdeInitialize` (the loader thread, `D2BS.cpp:135`; [architecture.md §11](architecture.md#11-open-questions) item 2).
- **Source comments that acknowledge the problem:** `SendMouseClick` "HACK: Using PostMessage instead of SendMessage--need to fix this ASAP!" (`D2Helpers.cpp:306`); the commented-out unit-id list under `Vars.cUnitListSection` (`Unit.cpp:56-71`, `Unit.cpp:153-182`).

### 2.5 Options for where an RPC executor runs game calls (trade-offs only)

| Option | How it maps onto today's code | Trade-offs |
|---|---|---|
| A. RPC worker thread(s) take GL per request, as `AutoCriticalRoom` does | Reuses `CriticalSections.h` and the `SectionCount` hand-off | Each request waits for the next yield (one frame in game; only `TimerProc` out of game, if it fires at all); the game is frozen while a request holds GL; inherits the `GetLevel` and `ActMap` defects if those helpers are reused ([§9](#9-known-defects-that-matter-for-the-redesign)) |
| B. Queue requests and execute them on the main thread from `GameDraw`/`GameDrawOOG`/`TimerProc` | Same pattern as `print()`/`takeScreenshot()` | No cross-thread game access at all; latency bounded by the frame/timer cadence (`Sleep(10)` per frame, `D2Handlers.cpp:418`, `:433`); a long request (A*, room scan) stalls the frame; waits inside requests (`Sleep`-based clicks, WFGR) would have to become multi-frame state machines |
| C. Main thread publishes snapshots each frame; queries are served from them, actions use A or B | No equivalent today | Consistent reads without per-call locking; staleness of up to one frame; cost of copying whatever subset is published; still needs A or B for actions |
| D. Keep unlocked reads as today | Current behaviour for most natives | No added latency; keeps every race in [§2.3](#23-unsynchronised-game-memory-access-risk-inventory) |

---

## 3. Synchronous and blocking semantics

### 3.1 Blocking events (verdicts)

The handshake is the same for all ([events.md §10.6](js-api/events.md#106-blocking-handshake)): the producer `ResetEvent(Vars.eventSignal)`, queues the event with a result slot, waits on `Vars.eventSignal`, and on timeout treats the script as "not blocked" and leaks the `Event`. Scripts are asked **one after another** in `ScriptEngine::scripts` map-key order, and all are asked even after one has blocked (`ScriptEngine.cpp:204-228`). A listener blocks only by returning the boolean primitive `true`.

| Event | Producer thread | Timeout per listening script | GL released while waiting | Effect of `true` | Source |
|---|---|---|---|---|---|
| `keydownblocker` | main (WH_KEYBOARD) | 1000 ms | no | key message swallowed (hook returns 1) | `Events.cpp:55-75`, `D2Handlers.cpp:289-291` |
| `keyupblocker` | main | 1000 ms | no | **none**: no consumer branch, so every key-up costs the full 1000 ms per registering script | `Events.cpp:55-67`, `ScriptEngine.cpp:634-635` |
| `chatmsgblocker` | game thread (in game) / undetermined (BNCS) | 500 ms | no | in game: packet `0x26` forwarded with size 0; out of game: **ignored** | `Events.cpp:185-201`, `D2NetHandlers.cpp:64`, `D2Handlers.cpp:531`, `D2Handlers.cpp:563` |
| `chatinputblocker` | main (game chat) / undetermined (channel) | 500 ms | no | typed line not sent | `D2Handlers.cpp:121-143` |
| `whispermsgblocker` | undetermined | 500 ms | no | **none** on either path | `D2Handlers.cpp:464-471`, `D2Handlers.cpp:548` |
| `gamepacket` | game thread (receive intercept) | 500 ms | yes, only if on `Vars.dwGameThreadId` | packet passed on with size 0; D2BS handlers and derived events skipped | `Events.cpp:293-330`, `Events.cpp:347-355`, `D2Handlers.cpp:145-170` |
| `gamepacketsent` | the sending thread (game or script) | 500 ms; inline (no wait) for the sender's own listeners | same rule | packet sent with length 0 | `D2Handlers.cpp:172-174`, `D2Intercepts.cpp:45-67` |
| `realmpacket` | undetermined | 500 ms | same rule | MCP handler not called | `D2Handlers.cpp:526-528`, `D2Intercepts.cpp:7-22` |
| screen-hook `click` | main (WH_MOUSE) | 3000 ms per in-range hook with a handler | no, and `Genhook::globalSection` is held | button-down swallowed (the button-up never is) | `ScreenHook.cpp:214-247`, `D2Handlers.cpp:313-347` |

Consequences that an RPC design would either replicate or replace:

- **Budget.** The producing game thread stalls for up to (number of listening scripts) × timeout per key, chat line, packet or click. A busy listener costs the full timeout every time.
- **Defaults on timeout are "allow".** The late answer still runs the listener after the input or packet has been processed.
- **Same-thread shortcut.** Packet events run a listener inline when the producer is that script's own thread (`Events.cpp:306-307`), which is what lets `sendPacket` inside a script call its own `gamepacketsent` listeners without deadlocking. The other blockers have no such shortcut.
- **Shared rendezvous.** One manual-reset event serves every verdict on every thread; a late or concurrent `SetEvent` wakes the wrong waiter, which then frees an `Event` that is still queued (use-after-free on the script thread) ([events.md §14](js-api/events.md#14-defects-and-quirks) item 3).
- **Lock context.** Non-packet blockers wait while the main thread holds GL, so a verdict handler that calls any GL-taking native stalls until the timeout ([embedding.md §9.3](spidermonkey/embedding.md#93-deadlock-and-stall-risks-visible-in-the-code) item 2).

Options for verdicts (trade-offs only):

| Option | Trade-offs |
|---|---|
| Remote round-trip with a deadline and an "allow" default, as today | Network RTT plus client processing must fit in 500/1000/3000 ms per subscriber; the game thread stalls for that long on every matching input or packet; requires correlation ids that do not exist today |
| Filters/rules pushed into the DLL and evaluated locally (packet id masks, key codes, chat patterns, "hook consumes clicks" attribute) | No game-thread wait on the network; verdict logic limited to what the rule language can express; notification can follow asynchronously |
| Hybrid: local rule decides, remote client is notified and may update rules | Bounded latency; rule updates race with the traffic they govern |
| Drop blocking entirely for some sources | `keyupblocker` and `whispermsgblocker` have no effect today; others are used for packet suppression and input capture by scripts (usage outside the repo is unknown) |

### 3.2 Natives that sleep, poll or wait

| Native / path | Wait | Cancellable? | Source |
|---|---|---|---|
| `delay(ms)` | alertable wait loop until `ms` elapsed; drains events, runs timer APCs, GCs every 0.5 MiB | stop sets abort and wakes it; `delay` then **returns normally** | `JSCore.cpp:125-165` |
| WFGR at 51 active call sites in 50 natives and methods (`JSGame.cpp` 23, `moveNPC` twice; `JSUnit.cpp` 22, a 23rd is commented out at `JSUnit.cpp:1177`; `JSArea.cpp`, `JSParty.cpp`, `JSPresetUnit.cpp`, `JSRoom.cpp` 6), plus one inside `IsScrollingText` (`D2Helpers.cpp:1000`) behind `getIsTalkingNPC` | 10 ms poll while `Busy`, up to `GameReadyTimeout` (5 s default, **0 = forever**) | no | `D2Helpers.cpp:153-166`; [globals-game.md conventions](js-api/globals-game.md#conventions-and-shared-mechanics) |
| GL-taking natives ([§2.2](#22-locks-and-which-natives-take-them)) | until the main thread's next yield; then the game is frozen while held | no | `CriticalSections.h:31-54` |
| `getPath` | A* with no node cap under GL; 5 ms yield every 500 ms (which also discards the loaded-room cache); teleport reducer with `radius ≤ 1` never terminates | no per-call cancel and not interrupted by script stop; the A* loop exits only when `Vars.bQuitting` is set (by `quit()`), the player's level changes or the game is not ready (`Map/Path/AStarPath.h:122-127`, `JSGame.cpp:1023`) | `Map/Path/AStarPath.h:106-152`, `Map/Diablo_II/ActMap.cpp:188-202`; [globals-game.md](js-api/globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) |
| `login()` / `Profile.prototype.login()` | 100 ms loop; timeout counts only some states; several states **spin forever with keyboard and mouse blocked** | no | `Profile.cpp:97-297`; [out-of-game.md](js-api/out-of-game.md#the-login-state-machine) |
| `clickControl` (`Control.click`, `selectCharacter`, `createGame`, `joinGame`, `login`) | 3 × `Sleep(100)` = 300 ms per click; `createGame` ≈ 1.2 s, `joinGame` ≈ 0.7 s, `selectCharacter` ≤ 600 ms | no | `Control.cpp:113-131`, `Control.cpp:480-510`, `Control.cpp:560-572` |
| `sendClick`, `sendKey` | 3 × `Sleep(100)` | no | `JSCore.cpp:687-691`, `JSCore.cpp:708-712` |
| `useStatPoint`, `useSkillPoint` | `Sleep(500)` between packets, no event pumping | no | `Game.cpp:21-25`, `Game.cpp:35-39` |
| `Unit.move` | `Sleep(50)` between two map clicks | no | `JSUnit.cpp:1893-1895` |
| `Unit.setSkill` → `SetSkill` | up to 11 slices of 100 ms, **pumping the script's events** ("avoid packet block deadlock") | no | `D2Helpers.cpp:238-287` |
| packet-sending natives (footnote 5) | ≤ 500 ms per other `gamepacketsent` listener | no | `Events.cpp:309-317` |
| `sendCopyData` | `SendMessage`, **no timeout** | no | `JSCore.cpp:412` |
| `sendDDE` | 5000 ms per transaction | no | `dde.cpp:60`, `dde.cpp:84-92` |
| `getIP` | synchronous WinINet GET | no | `JSCore.cpp:660-675` |
| `Socket.open` / `Socket.read` | blocking `gethostbyname`/`connect` / `recv` | no | `JSSocket.cpp:97`, `JSSocket.cpp:107`, `JSSocket.cpp:152` |
| `D2BSScript.join()` | `WaitForSingleObject(thread, INFINITE)`; joining self or the console never returns | no | `Script.cpp:224-231` |
| `stop()`, `D2BSScript.stop()`, `load()` of an already-loaded file | `Script::Stop` polls `hasActiveCX` every 10 ms for up to 500 ms (300 forced, 100 "really forced") **while holding the target's `Script::lock`** | – | `Script.cpp:251-280`, `ScriptEngine.cpp:39-40` |
| `include()` | runs the included file synchronously while holding the caller's `Script::lock` | no | `Script.cpp:296-336` |
| `quitGame()` | `Shutdown()` waits `INFINITE` for `D2Thread`, then `TerminateProcess` | no | `JSGame.cpp:1009-1019`, `D2BS.cpp:147-149` |
| `stacktrace()` | walks every thread with StackWalker (symbol server enabled) | no | `Helpers.cpp:490-512` |
| `DBStatement.skip(n > 0)` | never returns | no | [utility-classes.md](js-api/utility-classes.md#defects-and-quirks-summary) |
| Paused script | spins `Sleep(50)` + `JS_MaybeGC` in the operation callback | resume | `ScriptEngine.cpp:304-313` |

Non-script waits that affect an RPC host as well:

| Path | Wait | Thread | Source |
|---|---|---|---|
| Join detection | 50 ms poll, then `Sleep(500)` before scripts start | `D2Thread` | `D2Handlers.cpp:78-90`, `D2Handlers.cpp:109` |
| `UseProfileScript=true` at the menu | `while (bUseProfileScript) Sleep(100)` until a profile switch | `D2Thread` | `D2Handlers.cpp:94-96` |
| `GameLeave` | `Stop(true)` ≤ 300 ms per `InGame` script, holding GL | main | `D2Handlers.cpp:506-524` |
| Console `stop` / `reload` | ≤ 500 ms per script; `reload` adds `Sleep(500)` | main (when typed) | `Helpers.cpp:231-250`, `Helpers.cpp:269-288` |
| `WM_COPYDATA 0x1337` | `Sleep(100)` loop in the WndProc until the engine is running; forever after shutdown | main | `D2Handlers.cpp:184-189` |

### 3.3 Timers

`setTimeout`/`setInterval` (`JSCore.cpp:78-115`, `ScriptEngine.cpp:798-840`; [globals-core.md](js-api/globals-core.md#how-timers-and-event-servicing-work)):

- **Mechanism.** One Win32 waitable timer per call, with completion routine `EventTimerProc`. The APC is queued to the thread that armed it and runs only during an alertable wait: `delay()` (`JSCore.cpp:140`) or `SetSkill` (`D2Helpers.cpp:273`). `EventTimerProc` only re-queues the event; the callback runs at the next drain.
- **Semantics that differ from browsers:** callbacks are stored under the listener names `"setTimeout"`/`"setInterval"`, so every pending callback of the same kind runs on every expiry (`ScriptEngine.cpp:776-791`); delays above 214 748 ms overflow (`ScriptEngine.cpp:804`); non-integral delays are misread; `setInterval(fn, 0)` fires once.
- **Ownership.** Ids are process-global, non-atomic and sequential (`ScriptEngine.cpp:25`, `ScriptEngine.cpp:799`); any script can clear any other script's timer, mutating the owner's listener map from the caller's thread (`ScriptEngine.cpp:818-836`).
- **Lock damage.** `RemoveDelayedEvent` ends with `LeaveCriticalSection(&Vars.cEventSection)` without entering it, on every `clearTimeout`/`clearInterval` and after every `setTimeout` fires (`ScriptEngine.cpp:835`). That section guards every script's event queue.
- **Lifetime.** Timers are not cleaned up at script end; their `Event` keeps an `owner` pointer to the deleted `Script` (`ScriptEngine.cpp:376-389`).
- For RPC: a remote client normally owns its own timing, so these semantics only matter if in-process scheduling is kept (for example for local verdict rules or heartbeats).

### 3.4 Contracts to replicate or redesign

| Today's contract | Facts | Options (trade-offs) |
|---|---|---|
| Calls are synchronous on the caller's thread and may wait seconds | [§3.2](#32-natives-that-sleep-poll-or-wait) | Keep request/response with server-side deadlines (simple; long calls tie up a worker) · turn long calls (`login`, `getPath`, multi-click OOG actions, `useStatPoint(n)`) into jobs with progress and cancel (more protocol; matches the existing absence of cancellation) |
| "Game not ready" is a warning + `false`, or a wait of up to `GameReadyTimeout` | `js32.h:118-123`, `D2Helpers.cpp:153-166` | Explicit "not ready" result vs server-side wait with a caller-supplied deadline; three outcomes are distinct today in practice: error, not-ready, session terminated ([jsapi-inventory.md §7.7](spidermonkey/jsapi-inventory.md#77-error-semantics)) |
| Actions do not wait for their effect | clicks are `PostMessage` + sleeps; packets are fire-and-forget; only `login` and `setSkill` poll for a result | Return "issued" and let the client confirm via events/queries (as today) vs server-side confirmation (requires defining success per action) |
| Verdicts are synchronous on game threads | [§3.1](#31-blocking-events-verdicts) | see the verdict options table above |
| Delivery only at pump points | [events.md §10.3](js-api/events.md#103-drain-points-where-listeners-run) | A remote stream has no pump points; back-pressure and queue bounds have no existing counterpart (queues are unbounded today) |

---

## 4. Object identity and lifetimes

### 4.1 Handle models today

| Object | What the JS object holds | Re-resolved per access? | Stale behaviour | Aliasing / equality | Stable key a remote client could use | Source / doc |
|---|---|---|---|---|---|---|
| `Unit` (incl. `getItems()` elements, `getParent`, `getMerc`, `getInteractedNPC`) | `myUnit`/`invUnit`: `dwUnitId`, `dwType` + `getNext` filters (`dwClassId`, `dwMode`, `szName`) + owner for `getItem` results | yes: `ClientState()` + `D2CLIENT_FindUnit(id, type)` (server-side then client-side table) on **every** property read and method call | properties return **unset** (no throw, no flag); methods return their failure value | an id reused for another unit of the same type resolves silently (whether ids are reused within a game is open); no equality hook, `==` is object identity | `{type, gid}` | `JSUnit.cpp:183-194`, `D2Helpers.cpp:500-505`; [unit-properties.md](js-api/unit-properties.md#identity-resolution-and-lifetime) |
| `me` | `(player gid, UNIT_PLAYER)` | yes | gid rewritten by `D2Thread` on each join (`UpdatePlayerGid`), racing script start/dispose | `copyUnit(me)` freezes the gid | "self" | `ScriptEngine.cpp:348-366`, `Script.cpp:213-215`; [unit-properties.md](js-api/unit-properties.md#tracking-the-player-across-games) |
| Unit iteration cursor | the receiver itself: `getNext` **rewrites the object in place**; filters persist; gid filter is not persisted | per call | `undefined` if the cursor unit vanished, `false` at the end; an `any`-type search never leaves the first match's type | – | server-side iterator, or a snapshot list | `JSUnit.cpp:642-725`, `Unit.cpp:99-151`; [unit-methods.md](js-api/unit-methods.md#filter-persistence-on-the-object) |
| `Room` | raw `Room2*` | no: dereferenced live, never revalidated | use-after-free after act change or leave | new object per call; compare `level`, `x`, `y` | `(act, levelNo, room.dwPosX, room.dwPosY)` (what `AddRoomData` itself uses) | [world.md](js-api/world.md#room) |
| `Area` | level id; `exits` cached after first read | yes, `GetLevel(id)` per property | only levels of the current act resolve; lock leak if read while not `GameReady` | – | level id | [world.md](js-api/world.md#area) |
| `Exit`, `PresetUnit` | heap snapshot | no (immutable) | safe after the level is gone | – | value object | [world.md](js-api/world.md#exit) |
| `Party` | raw `RosterUnit*` | no: live reads of the game's entry | use-after-free when the player leaves or the game ends | – | `gid` | [world.md](js-api/world.md#party) |
| `Control` | `(type, x, y, w, h)` | yes: `findControl` returns the **first** match | getters/setters return `JS_FALSE` with no exception (uncatchable termination) when gone | non-unique keys alias the first control | the geometry key, or a list index/pointer with explicit invalidation | [out-of-game.md](js-api/out-of-game.md#control) |
| `Profile` | INI values at construction | no | later INI edits not seen | – | profile name | [out-of-game.md](js-api/out-of-game.md#profile) |
| `DailogLine` | `text`/`selectable` snapshots + raw pointer to the game's dialog line in a reserved slot | `handler()` dereferences it at call time | stale pointer after the dialog changes → indirect call into garbage | – | (dialog, line index) | `JSGame.cpp:183-225`; [globals-game.md](js-api/globals-game.md#dailogline) |
| `D2BSScript` | borrowed `Script*` | no | use-after-free once the script is disposed (with the default `DisableCache=true`, when its thread ends) | new wrapper per call; `getNext` rewrites | map key (lower-cased path) or thread id | `JSScript.cpp:19`, `ScriptEngine.cpp:71-90`; [utility-classes.md](js-api/utility-classes.md#d2bsscript) |
| Screen hooks | owned C++ `Genhook`; JS object is the only handle | – | destroyed by `remove()`, by GC of an unreferenced object (arbitrary later time), or on script destruction (unlinked; freed only if finalized) | no enumeration, lookup or equality | explicit hook id | [screenhooks.md](js-api/screenhooks.md#ownership-and-lifetime) |
| `File`, `SQLite`/`DBStatement`, `Socket`, `Folder` | native handles | – | closed by explicit call or by the finalizer at GC/runtime destruction; several double-close and dangling paths | – | not needed remotely (client-side facilities) | [utility-classes.md](js-api/utility-classes.md#handle-ownership-and-lifetime-summary) |
| Timer ids | process-global ints | – | leak at script end; clearing a dead script's id is use-after-free | any script can cancel any id | – | [§3.3](#33-timers) |

### 4.2 What a remote client would have to model

- **Value handles vs server-side tables.** `Unit` already behaves like a value handle `{type, gid}` re-resolved per call; `Room`/`Party`/`DailogLine`/`D2BSScript` behave like unchecked pointers. A uniform scheme needs either (a) value keys re-resolved per call (no server state; staleness surfaces as "not found"), or (b) server-side handle tables with generation counters and explicit invalidation on game leave / act change (detects staleness; needs invalidation hooks, which exist only for leave: `GameLeave`, `D2Handlers.cpp:506-524`).
- **Iteration.** `getNext` cursors live in the object and race with unit insertion and removal. Options: server-side iterators (stateful, must expire), or snapshot queries returning lists (one round-trip; the list may contain units that vanish before use, which a value-handle scheme already tolerates).
- **"Unset" is not a value.** Several getters and natives return without setting a value ([jsapi-inventory.md §7.7](spidermonkey/jsapi-inventory.md#77-error-semantics)); a wire schema has no "unset", so these results would need an explicit encoding.
- **Game-session scope.** `InGame` scripts are aborted on return to the menu (`ScriptEngine.cpp:315-326`); handles from one game are meaningless in the next. Only `OutOfGame` and console scripts outlive a game today.
- **Ownership by session.** Hooks, files, sockets and DB handles are owned per script and released by GC or script teardown; nothing else enumerates them. Without a GC on the server side, such handles are released only by an explicit destroy call or by whatever session-end cleanup the protocol defines.

---

## 5. Event streams

### 5.1 Catalogue with payload and volume

Producer threads as in [§2.1](#21-which-thread-runs-what-today): **main** = window/game-loop thread, **game?** = a game-code intercept whose thread is not determinable from source, **sender** = the thread that triggered it. Every recipient gets its own heap copy at fire time ([events.md §2.6](js-api/events.md#26-payload-copying)). The only source-side gate today is per script: `IsRunning()` plus "a listener is registered under this name"; screen-hook clicks and `D2BSScript.send` check less ([events.md §2.2](js-api/events.md#22-gating-per-script)). No producer filters by content.

| Event | Producer | Payload (per recipient) | Approx. size | Volume | Possible source-side filter (not implemented) | Verdict |
|---|---|---|---|---|---|---|
| `keydown`, `keyup` | main | `vk` | 4 B | one per key message that passes the console/chat/`bBlockKeys` gates; auto-repeat produces repeated `keydown` (inferred) | virtual-key code | no |
| `keydownblocker` | main | `vk` | 4 B | same | key code | **yes, 1000 ms** |
| `keyupblocker` | main | `vk` | 4 B | every key-up | – | produced, never answered |
| `mouseclick` | main | `button, x, y, up` | 16 B | every L/R/M button down and up | button | no |
| `mousemove` | main | `x, y` | 8 B | **every `WM_MOUSEMOVE`, no coalescing** | rate / coalescing | no |
| `chatmsg` (+`blocker`) | game? | `nick` (bytes widened 1:1), `msg` (UTF-16, `CP_ACP`-decoded) | strings | every in-game `0x26` packet (chat-type byte not inspected) and BNCS `0x0F` chat events of types `0x02`/`0x03` (join/leave, synthesised text), `0x05`, `0x12`, `0x13`, `0x17` (`D2Handlers.cpp:530-563`) | message type | blocker: **yes in game, 500 ms**; ignored out of game |
| `chatinput` (+`blocker`) | main / game? | `"me"`, `msg` | string | every typed line not consumed by a `.` command or by `say()`'s one-shot flag | – | blocker: **yes, 500 ms** |
| `whispermsg` (+`blocker`) | game? | `nick`, `msg` | strings | every in-game whisper not consumed by `say()`'s one-shot flag, and BNCS `0x0F` types `0x04`/`0x0A` | – | blocker: waited 500 ms, result ignored |
| `gamepacket` | game thread (receive intercept) | raw bytes | `dwSize` given by the game | **every received game packet** except `0xAE` | packet id: the receive handler already switches on `pPacket[0]` (`D2Handlers.cpp:146-169`) | **yes, 500 ms** |
| `gamepacketsent` | sender (game or script) | raw bytes | send length | every `D2NET_SendPacket` call; whether `D2CLIENT_SendGamePacket` also passes the hook is open | packet id | **yes, 500 ms** (inline for the sender's own listeners) |
| `realmpacket` | game? | raw bytes | `dwSize` | every MCP packet through the `0x44B1AE` site (site unverified, [§8.2](#82-stale-and-suspect-entries-and-what-they-break)) | packet id | **yes, 500 ms** |
| `melife`, `memana` | game thread | value | 4 B | on `0x18`/`0x95` **only when the value changed** against a function-static never reset between games (`D2NetHandlers.cpp:40-50`) | already de-duplicated | no |
| `itemaction` | game thread | `gid, mode, code (4 bytes of a shifted `INT64`, a trailing space cut; empty for `0x2A`), global` | ~13 B + ≤ 4 B string | every `0x9C`/`0x9D`; NPC transactions `0x2A` as mode 100+ | mode / code | no |
| `gameevent` | game thread | `mode, param1, param2, name1 (< 16 B), name2 (< 16 chars)` | ≤ ~60 B | every `0x5A` | mode | no |
| `playerassign` | game thread | `unitId` | 4 B | each non-NULL `AssignPlayer_I` result (which units is open) | – | no |
| `copydata` | main | `mode, msg` | 4 B + string | each inbound `WM_COPYDATA` other than `0x1337`/`0x31337` | mode | no (sender always gets `TRUE`) |
| `scriptmsg` | sender | structured-clone buffers | variable | per `scriptBroadcast` (sender included) / `D2BSScript.send` | – | no |
| hook `click` | main | `button, x, y` | 12 B | each button-down × each in-range hook with a handler (no state/automap check) | per-hook "consumes clicks" attribute | **yes, 3000 ms per hook** |
| hook `hover` | – | – | – | **never produced** (`D2Handlers.cpp:341-343`) | – | – |

Costs per delivered event today: one `Event` plus payload allocations per recipient, a `_strdup` of the name, a `push_front` under the global `cEventSection`, a leaked `new jsval[n]` on most consumer branches (`ScriptEngine.cpp:465`, `:494`, `:524`, `:550`, `:580`, `:608`, `:638`, `:663`, `:713`), and for packets a `Uint8Array` filled element by element (`ScriptEngine.cpp:738-775`).

### 5.2 Ordering, metadata and coupling

- **Ordering:** FIFO per recipient queue; scripts are visited in map-key order per producer call; no ordering across producer threads ([events.md §10.7](js-api/events.md#107-ordering-guarantees)).
- **No metadata:** no event id, timestamp, sequence number or acknowledgement exists anywhere in the pipeline ([events.md §12](js-api/events.md#12-facts-that-constrain-an-rpc-replacement)).
- **Payloads are snapshots taken before D2BS's own handlers act:** listeners see the `0x15` packet before `ReassignPlayerHandler` zeroes `p[10]`, and `0xA7` packets that `DelayedStateHandler` then drops (`D2NetHandlers.cpp:18-23`, `D2NetHandlers.cpp:173-178`).
- **Hidden couplings:** a `gamepacket` verdict of `true` skips the D2BS handler for `0x15`/`0x26`/`0x2A`/`0x5A`/`0x18`/`0x95`/`0x9C`/`0x9D`/`0xA7` and every derived event (`D2Handlers.cpp:151-166`); `QuitOnHostile` exits the game before `gameevent` fires (`D2NetHandlers.cpp:110-113`); `say()` sets a single global one-shot flag that the next input/whisper/`0x26` path consumes (`Core.cpp:93`, `D2NetHandlers.cpp:61-62`).
- **Unbounded queues:** a script that stops pumping accumulates events without limit; with `DisableCache=false` a finished script keeps receiving and blocking producers pay the full timeout ([events.md §10.8](js-api/events.md#108-script-state-effects)).
- **Encodings are lossy and mixed** (Latin-1 widening for `char*` names, `CP_ACP` for received chat, UTF-8 for `copydata`) ([events.md §2.4](js-api/events.md#24-string-encodings)).

### 5.3 Options for a remote event stream (trade-offs only)

| Option | Trade-offs |
|---|---|
| Push every subscribed event as today, with added sequence numbers and timestamps | Simple mapping; `mousemove` and `gamepacket` dominate bandwidth; a slow client needs a bounded queue and a drop/backpressure policy, which does not exist today |
| Server-side filters per subscription (packet ids, key codes, modes) | Cuts volume at the hook (the receive handler already dispatches on packet id); filter evaluation runs on game threads |
| Coalesce high-rate streams (`mousemove`, HP/MP) | Lower volume; loses intermediate values |
| Keep derived events as separate subscriptions vs raw packets only | Derived events encode D2BS parsing (`itemaction` code extraction, `gameevent` name rewrites); raw-only pushes that parsing to clients |

---

## 6. Existing external control surfaces

Full detail: [architecture.md §7](architecture.md#7-external-control-surfaces), [§5](architecture.md#5-configuration-d2bsini-and-the-command-line), [§6](architecture.md#6-console-and-built-in-commands).

| Surface | Dir. | Mechanism | Semantics today | Limits / defects | Source |
|---|---|---|---|---|---|
| `WM_COPYDATA` `0x1337` | in | `SendMessage` to `D2GFX_GetHwnd()`; NUL-terminated UTF-8 | queue arbitrary JS to the console script (`try{…}catch(e){print(e)}`); async; no result returned | busy-waits `Sleep(100)` on the window thread until the engine runs, forever after shutdown; `cbData` unchecked; no sender authentication | `D2Handlers.cpp:176-204`, `ScriptEngine.cpp:687-708` |
| `WM_COPYDATA` `0x31337` | in | same | `SwitchToProfile(name)` | works once, only with `UseProfileScript=true`; afterwards always "not found" | `D2Handlers.cpp:190-194`, `Helpers.cpp:80-105` |
| `WM_COPYDATA` other `dwData` | in | same | `copydata(mode, msg)` to every listening script; sender always gets `TRUE` | no reply channel | `D2Handlers.cpp:195-200`, `Events.cpp:228-246` |
| `sendCopyData(class, nameOrHwnd, mode, data)` | out | `SendMessage(WM_COPYDATA)` from the script thread, `wParam` = game window | returns the receiver's `LRESULT` | no timeout | `JSCore.cpp:365-417` |
| `-handle "<HWND>"` / `handler()` | config | decimal HWND on the command line | only exposed to scripts; native code never sends to it | – | `D2Handlers.cpp:43-47`, `JSCore.cpp:553-556` |
| DDE server `d2bs-<pid>` | in | DDEML `XTYP_POKE` (profile) / `XTYP_EXECUTE` (JS) | **non-functional**: data converted before `DdeGetData`, returns 0 instead of `DDE_FACK`; callbacks bound to the loader thread | requests/advises rejected | `dde.cpp:9-55` |
| `sendDDE(...)` | out | per-call DDEML client, 5 s timeout | only `XTYP_REQUEST` is ever issued (mode read from the wrong argument) | `JS_free` of literals | `JSCore.cpp:419-458`, `dde.cpp:57-102` |
| `d2bs.ini` `[settings]` | config | read once by `InitSettings` in `DllMain` (`D2BS.cpp:47`); only `MaxLoginTime`/`MaxCharSelectTime` are re-read at every `Profile` construction (`Profile.cpp:25-26`) | script names/path, `Hosts`, `MaxGameTime`, `QuitOnHostile`, `QuitOnError`, `StartAtMenu`, `DisableCache`, `MemoryLimit`, `GameReadyTimeout`, `UseProfileScript`, `EnableUnsupported`, logging, console font, login timeouts | booleans by first character; 5-character value buffers | `Helpers.cpp:107-162`; [architecture.md §5.2](architecture.md#52-settings-keys) |
| `d2bs.ini` profile sections | config | read at profile switch / `login` | mode, character, difficulty, `username`, **`password` in plaintext**, gateway, per-profile scripts | `addProfile` writes unescaped values, never updates | `Profile.cpp:6-34`, `JSMenu.cpp:112-150` |
| Command line | config | 9 recognised switches `-d2c -d2x -title -mpq -profile -handle -multi -sleepy -cachefix` (`-ftj` dead) | conditional patches, raw CD keys, manager handle, profile | substring matching, quoted values only, parsed twice; `InitCommandLine` overwrites the process command line (possible overflow) | `CommandLine.cpp:30-93`, `Helpers.cpp:483-488`; [architecture.md §5.4](architecture.md#54-command-line-switches) |
| Console prompt / chat `.` commands | in (local) | `HOME`/`Alt+HOME` prompt; `.start .stop .flush .load .reload .exec` in game or channel chat | built-ins on the main thread, else JS eval on the console script | received chat is never treated as a command | `Helpers.cpp:252-313`, `D2Handlers.cpp:121-143` |
| Log file | out | `logs\d2bs-<profile>-<YYYYMMDD>.log`, PID per line | errors, `debugLog`, optional console copy | on engine-startup failure it logs the full command line, which can contain raw CD keys (`-d2c`/`-d2x`) | `D2Helpers.cpp:33-56`, `D2Handlers.cpp:36` |
| Window title | out | `-title` applied only with `-multi` | lets a manager find an instance | `CacheFix` derives a file name from it incorrectly | `D2Intercepts.cpp:326-369` |

**Who uses them, as far as the repository shows.** No manager or protocol definition is in the repository. The evidence is indirect: the prebuilt .NET "D2BS Loader" binaries (`Debug/D2BS.exe`, `Release/D2BS.exe`) inject the DLL and accept `--pid --dll --path --exe --params` ([architecture.md §1.2](architecture.md#12-how-the-dll-gets-into-the-process)); the sample INI says `UseProfileScript` "requires external support" (`resources/d2bs.ini:5`); legacy doc stubs link to `forums.d2botnet.org` (`doc/Me.h:271`, `doc/globalFuncs.h:118`). The `copydata` mode values and payloads that a D2Bot-style manager and the script libraries exchange via `handler()`/`sendCopyData` are defined outside the repo ([architecture.md §11](architecture.md#11-open-questions) item 8).

**Where a networked control plane intersects.** Remote eval (`0x1337`, DDE execute, `.exec`); profile selection (`0x31337`, `-profile`, `login(name)`); manager messaging (`copydata`/`sendCopyData`/`-handle`); script lifecycle (`.start/.stop/.reload`, `load`, `stop`, `D2BSScript`); configuration (`d2bs.ini`, command line); monitoring (log file, `print` console). Security fact: any local process that can send window messages to the game window can already execute arbitrary JS through `0x1337` (`D2Handlers.cpp:184-189`).

Options (trade-offs only): keep a `WM_COPYDATA` bridge for existing managers (compatibility; keeps an unauthenticated local eval path) · replace it by the network API (one authenticated surface; existing managers and script libraries stop working) · keep `0x31337`/`-profile` semantics but lift the single-use gate (`Helpers.cpp:102`) (needed if a remote controller switches profiles more than once).

---

## 7. Coupling hotspots for removing SpiderMonkey

Source: [jsapi-inventory.md](spidermonkey/jsapi-inventory.md) and [embedding.md §10](spidermonkey/embedding.md#10-removal-impact-checklist).

### 7.1 Size of the coupling

| Metric | Value | Doc |
|---|---|---|
| Files scanned / with ≥ 1 JSAPI reference / reaching `jsapi.h` transitively | 123 / 63 / 90 | [§2](spidermonkey/jsapi-inventory.md#2-headline-numbers) |
| Distinct SpiderMonkey symbols / total live references | 198 / 7230 | [§2](spidermonkey/jsapi-inventory.md#2-headline-numbers) |
| Class **a** (pure binding: delete after extracting logic) | 44 files, ~11.0 kLOC (`JS*.cpp/h`, `JSPathReducer.h`) | [§4.1](spidermonkey/jsapi-inventory.md#41-classification-legend) |
| Class **b** (engine core: replace) | 8 files, ~2.0 kLOC: `js32.*`, `AutoRoot.*`, `Script.*`, `ScriptEngine.*` | same |
| Class **c** (mixed: split) | 11 files, ~5.2 kLOC: `D2Helpers.*`, `Events.*`, `File.*`, `MPQStats.*`, `Profile.h`, `ScreenHook.*` | same |
| Class **d** with engine calls (keep, re-target) | `D2Handlers.cpp` (40 refs), `Helpers.cpp` (16), `D2NetHandlers.cpp` (7), `D2BS.cpp`, `dde.cpp`, `Helpers.h` | same |
| Include path that drags `jsapi.h` everywhere | `D2BS.h:16` → `ScreenHook.h:7-8` → `Script.h:8` → `js32.h:13-14` | [§4.2](spidermonkey/jsapi-inventory.md#42-include-graph-exposure) |

### 7.2 Game logic living inside natives

These natives contain game logic with no JS-free equivalent; an RPC server that wants the same behaviour has to lift it out first ([jsapi-inventory.md §5.2](spidermonkey/jsapi-inventory.md#52-embedded-logic-to-extract-hand-written)):

| Group | Natives | What is embedded |
|---|---|---|
| Inventory and UI clicks | `clickItem` (`JSGame.cpp:357`) | body-click jump table, merc item actions, layout-based pixel maths, belt geometry by screen size, cursor-item size adjustment |
| Pathing | `getPath` (`JSGame.cpp:229`) | reducer selection, `ActMap` construction, A*, result shaping (the `Map/` code itself is JS-free except `JSPathReducer`) |
| Trade, dialog, party | `acceptTrade`, `tradeOk`, `getDialogLines`/`handler`, `clickParty` (`JSGame.cpp:106-225`, `:1074`) | trade state machine, dialog handler lookup, party mode mapping and guards |
| Misc actions | `submitItem`, `weaponSwitch`, `moveNPC`, `transmute`, `rand`, `getMouseCoords` | packet construction, UI state toggling, coordinate transforms |
| Unit getter | `unit_getProperty` (`JSUnit.cpp:47`) | 85 distinct property ids (the union of `unit_props` and `me_props`, `JSUnit.h`) in one `switch`: fixed-point HP/MP, spectype synthesis, item codes and affixes, `me.*` from `Vars`/`BnData`; item description via hard-coded VAs |
| Unit methods | `getStat` (+ `InsertStatsToGenericObject`, `InsertStatsNow`, which take `JSContext*`), `getSkill`, `shop`, `interact`, `cancel`, `repair`, `getParent`, `getMerc(HP)`, `setSkill`, `overhead`, `move`, `getEnchant`, `getItemCost`/`getRepairCost`, `getItem(s)`, `getNext`, `getUnit` | stat merging and skill-charge decoding, shop preconditions, interact dispatch, owner resolution, iteration state |
| World | `Room.getPresetUnits/getCollision/getCollisionA/getStat`, `getRoom`, `getPresetUnit(s)`, `Area.exits`, `getParty` | temporary room loading, collision extraction, preset and roster scans |
| Out of game | `getControl(s)`, `Control.*`, `addProfile` | control re-resolution by geometry; INI writing (the state machines themselves are already in `Control.cpp`/`Profile.cpp`) |
| Engine-flavoured | `delay`, `load`, `sendPacket`/`getPacket`, `sendCopyData`, `sendDDE`, `getIP`, `sendClick`, `sendKey` | event pumping, script launch with cloned args, packet assembly, OS IPC sequencing |

Thin wrappers that already delegate to JS-free helpers (hashes, `gold`, `useStatPoint`, `say`, `print`, OOG `OOG_*` calls, `getDistance`, `getTextSize`, automap transforms) are listed in [jsapi-inventory.md §5.3](spidermonkey/jsapi-inventory.md#53-thin-wrappers).

### 7.3 JS types in non-binding code

| Item | Where | What removal implies |
|---|---|---|
| `SetSkill(JSContext*, …)` both waits for the skill switch and pumps the calling script's event queue | `D2Helpers.cpp:238-287`, `D2Helpers.h:43` | the wait and the pumping are one function today; without JS the pumping half has no meaning |
| `FillBaseStat(JSContext*, jsval*, …)` writes JS values | `MPQStats.h:61`, `MPQStats.cpp` | four JS-free overloads already exist (`MPQStats.h:57-60`) |
| `writeValue`, `fileOpenRelScript` take `JSContext*`/`jsval` | `File.cpp:49`, `File.cpp:188` | only JS consumers; they go with the File classes |
| `ScriptBroadcastEvent(JSContext*, uint, jsval*)`, `BCastEventHelper` | `Events.cpp:168`, `Events.h:17`, `Events.h:72-73` | the only `Events.cpp` front-end whose arguments are JS values |
| `Genhook` stores `JSObject* self`, `jsval clicked, hovered` | `ScreenHook.h:40-41` | hook callbacks are JS values; a non-JS host needs another callback identity |
| `Event` struct holds `JSAutoStructuredCloneBuffer**`, `FunctionList`, `JSObject*`; `void*` slots hold `new jsval(callback)` for timers | `Script.h:22-104`, `JSCore.cpp:91`, `JSCore.cpp:111` | every producer in `Events.cpp` builds this struct |
| `friend JSAPI_PROP(profile_getProperty)` in `Profile` | `Profile.h:62` | declaration only |
| `myArea::ExitArray` (`JSObject*`), `DBStmt::current_row`, `JSPathReducer` members | `JSArea.h:29`, `JSSQLite.cpp:41`, `Map/Path/Reduction/JSPathReducer.h:16-18` | disappear with their classes |

Full lists: [jsapi-inventory.md §4.3](spidermonkey/jsapi-inventory.md#43-mixed-functions-js-types-in-gameinfra-signatures), [§4.4](spidermonkey/jsapi-inventory.md#44-c-state-that-holds-js-values).

### 7.4 Engine responsibilities that need a non-JS home

Condensed from [embedding.md §10](spidermonkey/embedding.md#10-removal-impact-checklist):

| Responsibility today | Where | Question it leaves for an RPC host |
|---|---|---|
| Isolation unit = one OS thread + one runtime per script; console is a script | `Script.cpp:104-135` | how sessions are isolated (state, crash containment) |
| Script registry keyed by lower-cased path, `"console"` entry | `ScriptEngine.cpp:31-50`, `ScriptEngine.cpp:117-138` | how sessions/jobs are identified (paths and raw pointers are racy today, [§9.4](#94-script-lifecycle)) |
| Auto-start (starter at first menu, default on each join), `UseProfileScript` gating, `reload`/`start` | `Helpers.cpp:210-250`, `Helpers.cpp:315-339`, `D2Handlers.cpp:78-104` | how controllers learn of join, leave and menu transitions |
| `InGame` scripts stopped on leave; aborted at the menu | `D2Handlers.cpp:506-524`, `ScriptEngine.cpp:315-326` | what is revoked when a game ends |
| Event fan-out, per-script queues, blocking verdicts | `Events.cpp`, `Script.cpp:419-430`, `ScriptEngine.cpp:452-797` | subscription, verdict and back-pressure model |
| Timers via APC | `ScriptEngine.cpp:798-840` | whether any in-process scheduling remains |
| Console eval (`RunCommand`) and its entry points | `ScriptEngine.cpp:56-69` | whether an eval endpoint remains |
| Output (`Print` queue drawn on the main thread), error reporting with optional `ExitGame` | `Core.cpp:51-65`, `ScriptEngine.cpp:428-450` | how output and errors reach clients |
| Object lifetimes by GC finalizers (hooks, files, sockets, DBs) | [jsapi-inventory.md §7.6](spidermonkey/jsapi-inventory.md#76-gc-finalizers-that-own-game-side-or-os-resources) | how handles are released and when |
| Engine shutdown via `DisposeMe` events and `D2Thread` | `ScriptEngine.cpp:140-165` | teardown order without pump points |

### 7.5 Build changes and removable dependencies

- **Removable:** all of `dependencies/` (SpiderMonkey headers, `mozjs.dll`/`.lib`, `js_static.zip`, `generated.pdb`; ~41 MB), the `AdditionalDependencies` entries, the `XP_WIN;STATIC_JS_API;MOZILLA_STRICT_API` defines, the SpiderMonkey `ClInclude` items and filter ([jsapi-inventory.md §6.3](spidermonkey/jsapi-inventory.md#63-dependencies-and-what-becomes-removable)). `sqlite3.c` is JS-independent but its only consumer is `JSSQLite.cpp` (`D2BS.vcxproj:271-281`).
- **Build hygiene facts that a new build inherits:** no `PlatformToolset`; `build.bat` targets VS 2008; Release sets `ExceptionHandling false` although the engine uses `try`/`throw`; the Packaging configuration links a non-existent `mozjs.lib`; `RandomizedBaseAddress false` ([architecture.md §10.1](architecture.md#101-solution-and-project)).
- **What stays JS-free already:** the patch engine, `Patch.h`, the intercepts and their C++ handlers ([patches-and-hooks.md §9](memory/patches-and-hooks.md#9-notes-for-replacing-the-js-layer-with-rpc)), `Map/` except `JSPathReducer`, `Control.cpp`/`Profile.cpp` state machines, `Unit.cpp` search, `Hash.cpp`.

---

## 8. Game-internals dependencies

All addresses are RVAs into `Game.exe` resolved by `GetModuleHandle(NULL) + offset`; the legacy DLL names are ignored (`Offset.cpp:21-28`; [memory/README.md](memory/README.md)). Reverse reachability from every `D2Ptrs.h` symbol to JS entry points is generated in [offsets.md §9](memory/offsets.md#9-js-entry-points-per-symbol).

### 8.1 API family → what it depends on

| API family | Functions / data | Stubs and patches | Struct reads | Doc |
|---|---|---|---|---|
| Client state (gates almost everything) | `D2CLIENT_GetPlayerUnit`, `p_D2WIN_FirstControl` | – | `UnitAny.pPath → Room1 → Room2 → Level.dwLevelNo`, `pUpdateUnit` | [architecture.md §8.1](architecture.md#81-clientstate) |
| Units (props, search, methods) | `D2CLIENT_FindServerSideUnit`/`FindClientSideUnit`, server/client unit hash tables, `D2COMMON_GetUnitStat`, `D2CLIENT_GetUnitX/Y`, `D2CLIENT_GetItemName`, `D2COMMON_GetItemMagicalMods`, `D2COMMON_GetMissileOwnerUnit` | `D2CLIENT_GetUnitName_STUB`; item description writes VA `0x7BCBE8`/`0x7BCBF4` and reads `0x841EC8` (hard-coded) | `UnitAny`, `ItemData`, `ItemTxt.xSize/ySize`, `MonsterData`, `StatList` | [unit-properties.md](js-api/unit-properties.md#quick-facts-for-an-rpc-replacement), [unit-methods.md](js-api/unit-methods.md#game-internals-referenced) |
| Movement and interaction | `D2CLIENT_ClickMap`, `D2COMMON_MapToAbsScreen`, `D2CLIENT_TakeWaypoint` | `GetSelectedUnit_Intercept` patch (VA `0x462D72`) forces the click target; `SetSelectedUnit_STUB`; `TakeWaypoint` enters mid-function | – | [call-stubs.md §5.5](memory/call-stubs.md#55-d2client_takewaypoint--entering-d2client_takewaypoint_i-mid-function) |
| Inventory, trade, shop | `D2CLIENT_BodyClickTable`, `LeftClickItem_I`, `ClickItemRight_I`, `ClickBelt(Right)_I`, `MercItemAction_I`, `D2CLIENT_ShopAction`, trade globals | stack-rewriting tail-jump stubs | `InventoryLayout`, `ItemPath`, `TransactionDialogsInfo_t` | [call-stubs.md §5.2](memory/call-stubs.md#52-stack-rewriting-tail-jumps-inventory-and-belt-clicks) |
| Chat | `p_D2CLIENT_ChatMsg`, `D2CLIENT_Say_I`, `D2MULTI_DoChat` | `Say_ASM` enters `Say_I` mid-function with a hand-built frame | – | [call-stubs.md §5.4](memory/call-stubs.md#54-say_asm--entering-d2client_say_i-mid-function) |
| Packets | `D2NET_SendPacket` (`0x52AE50`), `D2CLIENT_SendGamePacket_I` (`0x478350`), `D2NET_ReceivePacket` | send hook 10 bytes into `D2NET_SendPacket`; receive hook at `0x45F802` | – | [patches-and-hooks.md §3](memory/patches-and-hooks.md#3-patch-table) |
| World and pathing | `GetLevel` (walks `ActMisc.pLevelFirst`), `D2COMMON_InitLevel`, `AddRoomData`/`RemoveRoomData`, `D2COMMON_GetLevelText`, `D2COMMON_CheckUnitCollision`, `D2CLIENT_RevealAutomapRoom` | – | `Level`, `Room1`, `Room2`, `CollMap`, `PresetUnit`, `RosterUnit`, `ObjectTxt.nAutoMap` | [world.md](js-api/world.md#game-internals-referenced) |
| Data tables | `p_D2COMMON_sgptDataTable`; **19 absolute VAs** in `MPQStats.cpp` `BaseStatTable[]` | – | `MPQStats.h` field tables | [offsets.md §6.1](memory/offsets.md#61-mpqstatscpp-basestattable) |
| Out of game | `p_D2WIN_FirstControl`, `D2WIN_SetControlText`, `D2LANG_GetLocaleText`, `D2GFX_GetHwnd` (posted clicks) | – | `Control` (`wText2` offset discrepancy), hard-coded 800×600 geometry | [out-of-game.md](js-api/out-of-game.md#game-internals-touched) |
| Rendering | `D2GFX_DrawRectangle`/`DrawLine`/`DrawAutomapCell2`, `D2WIN_SetTextSize`/`DrawText`/`GetTextSize`, `D2CMP_InitCellFile`, automap globals | draw intercepts `GameDraw` (`0x453B30`) and `GameDrawOOG` (`0x4F9A0D`) | `CellFile`, `AutomapLayer` | [screenhooks.md](js-api/screenhooks.md#facts-relevant-to-an-rpc-replacement) |
| Lifecycle and the game lock | `D2CLIENT_ExitGame`, `D2CLIENT_InitInventory` | `GameDraw`/`TimerProc` hand-off; `GameLeave_Intercept` (`0x44F57C`) | – | [patches-and-hooks.md §8](memory/patches-and-hooks.md#8-hooks-that-are-not-code-patches) |

### 8.2 Stale and suspect entries and what they break

From [offsets.md §3](memory/offsets.md#3-stale-and-suspect-entries-what-depends-on-them) and [patches-and-hooks.md §2.6](memory/patches-and-hooks.md#26-the-d2game_exit0-static-initialisation-bug). Nothing has been checked against a real 1.14d binary.

| Entry | Status | Live? | APIs / behaviour affected |
|---|---|---|---|
| `RealmPacketRecv_Interception`, VA `0x44B1AE` (`Patch.h:39`) | no 1.14d evidence at all | installed unconditionally | `realmpacket` event; if wrong, 6 bytes of unrelated code are overwritten at injection. Expected original bytes are listed in [patches-and-hooks.md §4](memory/patches-and-hooks.md#4-displaced-instructions-and-expected-original-bytes) |
| Fog `0x4082E0` JMP (`Patch.h:42`) | **wrong target** `0x576F06` (encoded value copied before `DefineOffsets`) | installed unconditionally | crash/exit path only; no JS API |
| `D2COMMON_GetMissileOwnerUnit` (`D2Ptrs.h:344`) | VA-only | yes | `unit.getParent()` on missiles |
| Item-description VAs `0x7BCBE8`/`0x7BCBF4`/`0x841EC8` (`JSUnit.cpp:453-458`) | VA-only, not in `D2Ptrs.h` | yes | `unit.description`, `me.description`, and anything that enumerates unit properties |
| `MPQStats.cpp` absolute VAs (19 rows) | VA-only | yes | `getBaseStat` for `items`, `objects`, `lvlmaze`, `lvlsub`, `lvlwarp`, `lvltypes`, `runes`, `cubemain`, `gems`, `experience`; the `0x5A` "slain by object" name lookup |
| Conditional sites (`FailToJoin`, `Multi`, `Windowname`, `CacheFix` ×2, Sleep ×2) | no markers | only with `-ftj` (dead), `-multi`, `-cachefix`, `-sleepy` | multi-instance, cache file, CPU-sleep patches |
| `D2CLIENT_Interact_I`, `ShopAction_I`, `GetItemDesc_I`, `GameAddUnit_I`; `D2MULTI_Channel*_I`; `D2COMMON_GetTargetUnitType`; `p_D2NET_CriticalPacketSection` | 1.13 offsets or unported | unused / dead | nothing today; reviving them (or "starting to use" the packet lock) would be wrong |

### 8.3 Patches that feed events and behaviour

From [patches-and-hooks.md §3](memory/patches-and-hooks.md#3-patch-table) and [§6.2](memory/patches-and-hooks.md#62-blocking-and-timeouts):

| Patch (VA) | Handler | Feeds | Can veto? |
|---|---|---|---|
| `0x47C89D` | `GameInput` | `.` commands, `chatinput`(+`blocker`) | yes (line not sent) |
| `0x453B30` | `GameDraw` | in-game drawing, print flush, screenshots, GL hand-off | – |
| `0x45F802` | `GamePacketReceived` | `gamepacket`, `chatmsg`(+`blocker`), `itemaction`, `gameevent`, `melife`, `memana`, Warden kill, `0x15` fix-up, `0xA7` filter, `QuitOnHostile` | yes (size 0) |
| `0x52AE5A` | `GamePacketSent` | `gamepacketsent` | yes (length 0) |
| `0x462D72` | `GetSelectedUnit_Intercept` | click target for `ClickMap` | – |
| `0x45E4D5` | `GamePlayerAssignment` | `playerassign` | – |
| `0x44F57C` | `GameLeave` | stop `InGame` scripts, clear `ActMap` cache | – |
| `0x4547B6` / `0x4567EB` | act-change intercepts | `Vars.bChangedAct` (no event) | – |
| `0x461704` | `GameAttack_Intercept` | turns attacks on monsters into shift-attacks for **all** input | – |
| `0x521B20` | `ChatPacketRecv` | BNCS `chatmsg`, `whispermsg` | no (result never used) |
| `0x448813` | `WhisperHandler` | `whispermsg` | no |
| `0x442A61` | `ChannelInput` | channel `.` commands, `chatinput`(+`blocker`) | yes |
| `0x4F9A0D` | `GameDrawOOG` | menu drawing (no GL hand-off) | – |
| `0x44B1AE` (unverified) | `RealmPacketRecv` | `realmpacket` | yes (dispatch skipped) |

The other entries of `Patches[]` feed no event: the `0x468770` RET byte patch, the congratulations-screen pair `0x44EBFB`/`0x44EBEF`, `GameCrashFix` (`0x6091E5`), Fog's `LogMessageBoxA` (`0x408CC4`), `D2GAME_exit0` (`0x4082E0`, wrong target, [§8.2](#82-stale-and-suspect-entries-and-what-they-break)) and `ErrorReportLaunch` (`0x401790`) (`Patch.h:15-17`, `Patch.h:37`, `Patch.h:41-44`); neither do the conditional patches (`Patch.h:47-56`).

Non-patch hooks: WndProc subclass (`copydata`, `0x1337`, `0x31337`), `WH_KEYBOARD` (key events, console), `WH_MOUSE` (mouse events, hook clicks), `SetTimer` (`TimerProc` GL hand-off) (`Helpers.cpp:164-208`).

### 8.4 Layout discrepancies on live read paths

[structs.md](memory/structs.md#discrepancy-summary) lists 19 comment/layout disagreements. Those that live code reads, with the affected API: `ItemTxt.xSize/ySize` (`unit.sizex/sizey`, `clickItem` cursor adjustment; `JSUnit.cpp:427`, `JSUnit.cpp:434`, `JSGame.cpp:574-577`), `BnetData.ladderflag` (`me.ladder`, `JSUnit.cpp:126`), `Control.wText2` (button-text matching in every OOG probe, `Control.cpp:81-83`), `ObjectTxt.nAutoMap` (`Room.reveal(true)` preset icons, `Room.cpp:93`). Which side is right for 1.14d needs the binary.

---

## 9. Known defects that matter for the redesign

Curated: each item either would be inherited by an RPC layer that reuses the code, or constrains what the protocol can promise. Labels follow the source docs; "code-path analysis" items are not runtime-confirmed.

### 9.1 Event dispatch and verdicts

| Defect | Source | Impact on an RPC design |
|---|---|---|
| One process-wide manual-reset `Vars.eventSignal` for every verdict on every thread; a late or concurrent `SetEvent` wakes the wrong waiter, which frees a still-queued `Event` (use-after-free) | `Helpers.cpp:155`, `Events.cpp:63`, `Events.cpp:197`, `Events.cpp:309`, `ScreenHook.cpp:230` | Any verdict path that reuses `Events.cpp` inherits it; answers to different requests are indistinguishable without per-request correlation |
| `static DWORD result` shared by all packet producers | `Events.cpp:311` | same |
| `keyupblocker` never dispatched; `whispermsgblocker` and out-of-game `chatmsgblocker` results ignored, yet all wait | `ScriptEngine.cpp:634-635`, `D2Handlers.cpp:464-471`, `D2Handlers.cpp:531`, `D2Handlers.cpp:563` | Exposing these names remotely would promise semantics the hooks do not have |
| Timed-out blocking events are leaked; packet events are not answered during context destruction | `Events.cpp:66-67`, `Events.cpp:316-317`, `ScriptEngine.cpp:740` | Memory growth under slow consumers |
| `ForEachScript` runs producers on an unlocked snapshot | `ScriptEngine.cpp:204-228` | A script disposed concurrently is dereferenced from game threads |
| Listener map read and iterated without `Script::lock`; dispatch's `operator[]` re-inserts removed names | `Script.cpp:348-350`, `ScriptEngine.cpp:476` | Unsubscribe is not reliable today |
| `ExecScriptEvent("Command")` frees the name and keeps comparing it; `DisposeMe` deletes the `Script` inside its own drain loop | `ScriptEngine.cpp:687-709`, `ScriptEngine.cpp:792-794` | Remote eval or dispose built on these paths inherits the use-after-free |

### 9.2 Timers

| Defect | Source | Impact |
|---|---|---|
| Unbalanced `LeaveCriticalSection(&Vars.cEventSection)` on every `clearTimeout`/`clearInterval` and fired `setTimeout` | `ScriptEngine.cpp:835`, `ScriptEngine.cpp:787` | Corrupts the lock every event queue depends on; an in-process scheduler reusing `RemoveDelayedEvent` would carry this over |
| Every pending callback of a kind fires on each expiry; int overflow above 214 748 ms; ids global; timers leak at script end | `ScriptEngine.cpp:776-804`, `ScriptEngine.cpp:376-389` | In-process timers do not behave like conventional timers; anything layered on them inherits that |

### 9.3 Game lock, world and pathing

| Defect | Source | Impact |
|---|---|---|
| `GetLevel` returns without releasing GL when `!GameReady()`; the main thread then blocks forever | `D2Helpers.cpp:172-176` | Any reuse of `GetLevel` can freeze the client. Today it has 8 call sites: `getRoom` ×2, `getPresetUnits`, `getPresetUnit`, the `Area` property getter, `getArea`, `getPath`, `getCollision` (`JSRoom.cpp:469`, `JSRoom.cpp:509`, `JSPresetUnit.cpp:66`, `JSPresetUnit.cpp:149`, `JSArea.cpp:25`, `JSArea.cpp:115`, `JSGame.cpp:250`, `JSGame.cpp:338`) |
| `getPath` with an invalid reducer throws after `ActMap` took GL; teleport reducer with `radius ≤ 1` loops forever under GL; reducer type 3 uses an uninitialised `JSContext*` | `JSGame.cpp:255`, `JSGame.cpp:273-275`, `Map/Path/Reduction/TeleportPathReducer.h:44-56`, `Map/Path/Reduction/JSPathReducer.h:16-27` | Unvalidated remote `getPath` parameters can freeze the client or crash it while GL is held |
| Single global `ActMap` slot: another thread's `getPath`/`getCollision`/`Area.exits` deletes the map in use and leaves a critical section it does not own | `Map/Diablo_II/ActMap.cpp:14-31`, `Map/Diablo_II/ActMap.cpp:188-202` | Concurrent path/collision requests from several workers would hit this; no serialisation exists today |
| `dwGameThreadId` stays 0 if `GameDraw` takes the first hand-off; `GameDrawOOG` never hands off | `D2Handlers.cpp:410-416`, `D2Handlers.cpp:494-499`, `D2Handlers.cpp:421-434` | Out-of-game GL availability depends on `TimerProc` alone |
| `include()` holds `Script::lock` while a GL-taking native waits, and `GameLeave` (holding GL) waits for the same `Script::lock`: deadlock | `Script.cpp:298`, `CriticalSections.h:37`, `D2Handlers.cpp:520`, `Script.cpp:255` | Any per-session lock that a game hook also takes can form the same cycle |
| `cGameLoopSection` deleted in `Shutdown()` while the main thread may own it | `D2BS.cpp:173` | Teardown order matters for any host that owns or waits on GL |

### 9.4 Script lifecycle

| Defect | Source | Impact |
|---|---|---|
| Restart race: the old instance's `DisposeScript` erases the map entry by name and can remove the new instance | `Script.cpp:479-481`, `ScriptEngine.cpp:71-79` | Path-keyed job identity has this race today |
| `CompileFile` inserts into `scripts` without `scriptListLock` from several threads | `ScriptEngine.cpp:39-43` | The script registry is not thread-safe today |
| Join detection by 50 ms polling can miss leave/re-join sequences that never show `Menu` | `D2Handlers.cpp:73`, `D2Handlers.cpp:99-102` | "Game joined" notifications built on the poll can be missed (code-path analysis) |
| `UpdatePlayerGid` writes through an uninitialised or freed `me` | `Script.cpp:141-144`, `Script.cpp:213-215`, `ScriptEngine.cpp:210-224` | Per-session copies of the player handle are updated from another thread without synchronisation |
| Missing `DefaultConsoleScript` throws out of `ScriptEngine::Startup` with `scriptListLock` held | `ScriptEngine.cpp:123-127` | Startup failure leaves the engine stuck in `Starting` |
| `quitGame()` → `Shutdown()` can wait forever if `D2Thread` spins in the `bUseProfileScript` loop | `JSGame.cpp:1009-1019`, `D2Handlers.cpp:94-96` | A quit path that goes through `Shutdown()` inherits this wait |

### 9.5 IPC and inputs

| Defect | Source | Impact |
|---|---|---|
| `0x1337` busy-waits on the window thread; after shutdown it spins forever | `D2Handlers.cpp:184-189` | A bridge that keeps this handler keeps the window-thread stall |
| `cbData` and `lpData == NULL` unchecked | `D2Handlers.cpp:183`, `Helpers.cpp:16-22` | Over-read on malformed messages |
| DDE server non-functional; `sendDDE` mode from wrong argument | `dde.cpp:10-28`, `JSCore.cpp:425-426` | DDE cannot be assumed to work for any existing client |
| `InitCommandLine` copies `sizeof(LPWSTR) * wcslen(cline)` = 176 bytes from a 44-character (88-byte) literal into the buffer returned by `GetCommandLineW`: it over-reads the literal and overflows any shorter command line | `Helpers.cpp:484-487` | Startup memory corruption independent of the API |

### 9.6 Out of game and screen hooks

| Defect | Source | Impact |
|---|---|---|
| `login` spins forever in several states with input blocked; `OOG_DIFFICULTY` falls through; literal `L"EXIT"` | `Profile.cpp:126-218`, `Profile.cpp:144`, `Profile.cpp:196-198` | A remote login built on `Profile::login` has no timeout or cancel of its own |
| Crashes on bad input: `createGame`/`joinGame` without password, `selectCharacter` with a long `character`, `Profile(type, …)`, `getControl` with > 5 ints, `OOG_SelectGateway` double free | `JSMenu.cpp:52-54`, `JSMenu.cpp:74`, `JSMenu.cpp:99`, `Profile.h:27-30`, `JSControl.cpp:299-303`, `Control.cpp:286` | Unvalidated remote arguments reaching these functions can crash the process |
| Screen-hook click waits 3 s while holding `Genhook::globalSection` and GL; a handler that touches hooks or GL self-deadlocks until timeout; JSAPI used cross-thread; handler unrooted | `ScreenHook.cpp:89-105`, `ScreenHook.cpp:214-247`, `ScreenHook.cpp:265-292` | A remote click callback awaited from the mouse hook would hold both locks for the whole round-trip |
| `Image.location` setter frees the `CellFile` the draw thread may be using; non-virtual `~Genhook` leaks text/image buffers; `Genhook::Clean` erases a `visible` iterator from `invisible` | `ScreenHook.cpp:380-388`, `ScreenHook.h:52`, `ScreenHook.cpp:151-155` | Remote hook mutation from a non-main thread has the same races |

### 9.7 Units, handles and argument safety

| Defect | Source | Impact |
|---|---|---|
| `description` getter writes `SelectedInvItem` and a flag byte and never restores them; enumeration (e.g. `JSON.stringify`) triggers it | `JSUnit.cpp:444-466` | A generic "dump unit" RPC would mutate game state unless `description` is excluded |
| Name filters are copied with `strcpy_s` into 128-byte buffers: unconditionally in `getItem` and `getNext(string)`, and in `getUnit` once a unit is found (so `getUnit(100/101, name)`, which ignores the name, is the reachable case). 128 or more bytes hit the CRT invalid-parameter handler (process exit). `JS_free` of the literal `""` in `getUnit`/`getParty` | `JSUnit.cpp:629`, `JSUnit.cpp:658`, `JSUnit.cpp:1819`, `JSUnit.cpp:582`, `JSUnit.cpp:613-630`, `JSParty.cpp:96`, `JSParty.cpp:139` | Remote strings of 128 bytes or more would terminate the process through these paths; the marshalling itself is unsafe |
| `sendPacket`/`getPacket` size fields overflow the `2*argc` buffer; `clickItem` indexes `BodyClickTable` unchecked; `getBaseStat` numeric index unchecked | `JSCore.cpp:580-605`, `JSGame.cpp:417`, `JSGame.cpp:432`, `MPQStats.cpp:38` | Memory-safety holes reachable from arguments; remote arguments reach them unless checked first |
| `Room`, `Party`, `DailogLine`, `D2BSScript` raw pointers never revalidated | [§4.1](#41-handle-models-today) | Remote handles to these objects would be unchecked pointers unless re-resolved or invalidated |

---

## 10. Cross-document notes and open questions

### 10.1 Inconsistencies found among the sibling docs

These were found while this page was written. Each has since been corrected in the owning page against the source, so the pages now agree; the list stays as a record.

- `CriticalRoom` (`CriticalSections.h:5-29`) was called "unused" in [embedding.md §9.1](spidermonkey/embedding.md#91-inventory). It is used: `ActMap` allocates and enters one (`Map/Diablo_II/ActMap.cpp:44-45`, member at `Map/Diablo_II/ActMap.h:110`), as [world.md](js-api/world.md#actmap-construction-cache-lifetime-lock) and [architecture.md §4.2](architecture.md#42-the-game-lock-cgameloopsection-in-detail) describe. Fixed in embedding.md.
- [embedding.md §4.3](spidermonkey/embedding.md#43-how-natives-receive-arguments-return-values-and-report-errors) stated, without a citation, that SpiderMonkey pads a native's arguments with `undefined` up to the declared `nargs`. [globals-core.md](js-api/globals-core.md#reading-arguments-past-argc), [globals-game.md](js-api/globals-game.md#conventions-and-shared-mechanics) and [out-of-game.md](js-api/out-of-game.md#open-questions) treat this as not determinable from the bundled headers. embedding.md now does too; the question is [OQ-SM-01](OPEN_QUESTIONS.md#oq-sm-01) and matters only while JS remains.
- [screenhooks.md](js-api/screenhooks.md#facts-relevant-to-an-rpc-replacement) phrased "consume the click must be a hook attribute decided locally" as a requirement. It now presents it as one of the options in [§3.1](#31-blocking-events-verdicts).
- [jsapi-inventory.md §5.2](spidermonkey/jsapi-inventory.md#52-embedded-logic-to-extract-hand-written) counted "86 distinct property ids" in `unit_getProperty`. The source has 85: `unit_props` (49) and `me_props` (80) share 44 ids, and the getter's `switch` has exactly those 85 named labels (`JSUnit.h:160-297`, `JSUnit.cpp:47-525`). [§7.2](#72-game-logic-living-inside-natives) and jsapi-inventory.md now both use 85.
- [embedding.md §9.1](spidermonkey/embedding.md#91-inventory) said `GameDraw`/`TimerProc` "only yield the lock when it is non-zero". `TimerProc` leaves and re-enters `cGameLoopSection` on every tick; `Vars.SectionCount` only decides whether it sleeps 5 ms in between (`D2Handlers.cpp:493-504`). `GameDraw` does yield only when `SectionCount` is non-zero (`D2Handlers.cpp:410-418`). Fixed in embedding.md.

### 10.2 Open questions that affect an RPC design

Each item is also tracked, with a resolution method, in [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) under the id in the last column.

| # | Question | Why it matters | Where tracked |
|---|---|---|---|
| 1 | Which thread runs the BNCS chat, MCP realm, channel-input and whisper intercepts? | Whether those producers hold GL while waiting; where an executor may run OOG work | [architecture.md §11](architecture.md#11-open-questions) item 1; [OQ-THR-01](OPEN_QUESTIONS.md#oq-thr-01) |
| 2 | Does `TimerProc` fire, given `SetTimer` is called from `D2Thread` for a window it does not own? | If not, there is no GL hand-off out of game and `dwGameThreadId` stays 0 | [architecture.md §11](architecture.md#11-open-questions) item 3, [events.md §15](js-api/events.md#15-open-questions) item 11; [OQ-THR-02](OPEN_QUESTIONS.md#oq-thr-02) |
| 3 | Do `D2CLIENT_SendGamePacket_I` (setSkill, stat/skill points) and `D2CLIENT_ShopAction` pass the `gamepacketsent` hook? | Completeness of an outgoing-packet stream; whether `shop` waits on listeners while holding GL | [events.md §15](js-api/events.md#15-open-questions) item 3, [call-stubs.md §10](memory/call-stubs.md#10-open-questions); [OQ-NET-02](OPEN_QUESTIONS.md#oq-net-02) |
| 4 | Does `getPacket` → `D2NET_ReceivePacket` reach the receive intercept? | Whether injected packets fire `gamepacket`, derived events and the Warden check on a script thread | [events.md §15](js-api/events.md#15-open-questions) item 2; [OQ-NET-01](OPEN_QUESTIONS.md#oq-net-01) |
| 5 | Is the `RealmPacketRecv` site `0x44B1AE` valid for 1.14d? | Installed unconditionally; feeds `realmpacket` | [offsets.md §10](memory/offsets.md#10-open-questions); [OQ-MEM-01](OPEN_QUESTIONS.md#oq-mem-01) |
| 6 | Which game functions are safe to call off the main thread? | Decides between executor options A–D in [§2.5](#25-options-for-where-an-rpc-executor-runs-game-calls-trade-offs-only) | not answerable from source; [OQ-THR-07](OPEN_QUESTIONS.md#oq-thr-07) |
| 7 | Are unit ids reused within one game? | Whether `{type, gid}` handles can alias inside a game | [unit-properties.md](js-api/unit-properties.md#open-questions); [OQ-GAME-01](OPEN_QUESTIONS.md#oq-game-01) |
| 8 | Do posted `WM_LBUTTON*`/`WM_KEY*` messages reach the D2BS hooks, and does D2WIN hit-test their `lParam`? | All OOG clicks and `sendClick`/`sendKey` depend on it | [globals-core.md](js-api/globals-core.md#open-questions) item 10, [out-of-game.md](js-api/out-of-game.md#open-questions); [OQ-UI-09](OPEN_QUESTIONS.md#oq-ui-09), [OQ-WIN-01](OPEN_QUESTIONS.md#oq-win-01) |
| 9 | What `copydata` modes and payloads do existing managers use? | Compatibility of any bridge | outside the repository; [OQ-EXT-01](OPEN_QUESTIONS.md#oq-ext-01) |
| 10 | Does a compile failure in a `load()`ed file terminate the process (Release has C++ EH disabled)? | Whether remote-loaded code can take the client down | [globals-core.md](js-api/globals-core.md#open-questions) item 4; [OQ-WIN-05](OPEN_QUESTIONS.md#oq-win-05) |

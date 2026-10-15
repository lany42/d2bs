# JS API reference: index and reading guide

Scope: the index for `docs/js-api/`. It lists every name that D2BS registers on a script's global object: the 108 global functions in `global_funcs` (`JSGlobalFuncs.h:23-79`), the 21 classes in `global_classes` (`JSGlobalClasses.cpp:143-168`) with all their members, the global `me`, the three constants, and every event name a listener can receive. Each name links to the heading where it is specified. The page also explains how those pages are organised: the per-entry template, the shared tags and the citation and legacy-doc conventions. Behaviour is not restated here; follow the links. Names, counts, registration lines and native locations were extracted mechanically from the registration tables in the C++ source (the source of truth). The one-line summaries and the State column condense the linked entries.

## Contents

1. [At a glance](#1-at-a-glance)
2. [Doc map](#2-doc-map)
3. [How a script's global scope is built](#3-how-a-scripts-global-scope-is-built)
4. [Entry template](#4-entry-template)
5. [Conventions](#5-conventions)
6. [Global functions](#6-global-functions)
7. [Classes](#7-classes)
8. [Class members](#8-class-members)
9. [The `me` object](#9-the-me-object)
10. [Global constants](#10-global-constants)
11. [Events](#11-events)
12. [Not registered, commented out, or legacy-only names](#12-not-registered-commented-out-or-legacy-only-names)
13. [Related documentation](#13-related-documentation)

---

## 1. At a glance

| Item | Count | Where registered |
|---|---|---|
| Global function names | 108, backed by 106 natives (`utf8ToEuc` reuses `my_stringToEUC`, `clearTimeout` reuses `my_clearInterval`) | `global_funcs`, `JSGlobalFuncs.h:23-79` |
| ... by client-state requirement | in game 30, OOG 7, either 71 (legend in [§5](#state-column)) | per entry |
| Commented-out global | 1: `createCharacter` | `JSGlobalFuncs.h:55` |
| Registered classes | 21 | `global_classes`, `JSGlobalClasses.cpp:143-168` |
| Classes defined but not registered | 2: `DailogLine` (sic; instances only), `ProfileType` (unreachable) | `JSGlobalClasses.cpp:116-122` |
| Instance methods / static methods / properties of the registered classes | 87 / 9 / 183 | spec tables in `JS*.h` |
| `me` | one `Unit` object per script: 80 properties (10 writable) and the 25 `Unit` methods | `ScriptEngine.cpp:361-366`, `me_props` (`JSUnit.h:160-242`) |
| Global constants | 3 (`FILE_READ`, `FILE_WRITE`, `FILE_APPEND`) | `ScriptEngine.cpp:368-371` |
| Event names | 22 via `addEventListener`, plus the screen-hook `click` and `hover` callbacks (`hover` is never produced) | [events.md](events.md#1-summary-table) |
| Distinct names in all `JSFunctionSpec`/`JSPropertySpec` tables (global functions and members, including the unreachable `profileType_props`) | 326 | spec tables in `JS*.h` and `JSGlobalFuncs.h` |

---

## 2. Doc map

Start with the convention sections of [globals-core.md](globals-core.md#conventions-shared-by-all-entries), [globals-game.md](globals-game.md#conventions-and-shared-mechanics) and [unit-methods.md](unit-methods.md#conventions-used-on-this-page). Every page defines the tags it uses, but these three hold the definitions that the other pages refer back to. Then read [unit-properties.md](unit-properties.md#identity-resolution-and-lifetime) for the handle model behind every `Unit`, and [events.md](events.md#10-dispatch-mechanics) for how listeners and timers actually run.

| Page | Covers | Globals | Classes | Main sources |
|---|---|---|---|---|
| [globals-core.md](globals-core.md) | Core globals: script control and loading, timers and `delay`, listener registration, `scriptBroadcast`, console and logging, clipboard and OS IPC, input simulation, raw packets, misc, hashing. | 48 | – | `JSCore.cpp`, `JSHash.cpp` |
| [globals-game.md](globals-game.md) | In-game query and action globals, `rand`, `copyUnit`, the `DailogLine` objects, code tables (UI flags, locations, MPQ tables, collision flags). | 38 | `DailogLine` | `JSGame.cpp` |
| [out-of-game.md](out-of-game.md) | Menu globals, `getControl(s)`, the `Control`, `Profile` and `ProfileType` classes, OOG location codes, the login state machine, `d2bs.ini` profiles. | 8 | `Control`, `Profile`, `ProfileType` | `JSMenu.cpp`, `JSControl.cpp`, `JSProfile.cpp`, `Control.cpp`, `Profile.cpp` |
| [unit-properties.md](unit-properties.md) | `Unit` class registration, private data and identity; every `unit_props` and `me_props` property; the global `me`. | – | `Unit` | `JSUnit.h`, `JSUnit.cpp` |
| [unit-methods.md](unit-methods.md) | `Unit` methods, `getUnit`, `getMercHP`, the unit search/iteration model. | 2 | `Unit` | `JSUnit.cpp`, `Unit.cpp` |
| [world.md](world.md) | `Room`, `Area`, `Exit`, `PresetUnit`, `Party` and their getters; the `Map/` pathing subsystem behind `getPath`. | 5 | `PresetUnit`, `Area`, `Exit`, `Party`, `Room` | `JSRoom.cpp`, `JSArea.cpp`, `JSExits.cpp`, `JSPresetUnit.cpp`, `JSParty.cpp`, `Map/` |
| [screenhooks.md](screenhooks.md) | `Frame`, `Box`, `Line`, `Text`, `Image`; rendering, click/hover model; `screenToAutomap`, `automapToScreen`. | 2 | `Frame`, `Box`, `Line`, `Text`, `Image` | `JSScreenHook.cpp`, `ScreenHook.cpp` |
| [utility-classes.md](utility-classes.md) | `File`, `FileTools`, `Folder`, `SQLite`, `DBStatement`, `Socket`, `Sandbox`, `D2BSScript`, plus `dopen`, `sqlite_version`, `sqlite_memusage`, `getScript(s)`; the path security layer. | 5 | `Folder`, `File`, `Socket`, `FileTools`, `SQLite`, `DBStatement`, `Sandbox`, `D2BSScript` | `JSFile.cpp`, `JSFileTools.cpp`, `JSDirectory.cpp`, `JSSQLite.cpp`, `JSSocket.cpp`, `JSSandbox.cpp`, `JSScript.cpp`, `File.cpp` |
| [events.md](events.md) | Every `addEventListener` event name and the screen-hook callbacks; origin chains, threads, blocking verdicts, dispatch mechanics. | – | – | `Events.cpp`, `ScriptEngine.cpp`, `D2Handlers.cpp`, `D2NetHandlers.cpp` |

"Globals" counts the `global_funcs` entries specified on that page. `Unit` spans two pages: properties and identity in [unit-properties.md](unit-properties.md), methods in [unit-methods.md](unit-methods.md).

---

## 3. How a script's global scope is built

Every script gets its own `JSRuntime` and `JSContext` (`Script.cpp:120`, `Script.cpp:125`). Creating the context runs `contextCallback(cx, JSCONTEXT_NEW)` (`ScriptEngine.cpp:329-330`), which fills a fresh global in this order:

1. The global object: `JS_NewGlobalObject(cx, &global_obj, NULL)` (`ScriptEngine.cpp:340`; class `"global"`, `JSGlobalClasses.cpp:19-21`), then `JS_InitStandardClasses` (`ScriptEngine.cpp:343`).
2. The 108 functions: `JS_DefineFunctions(cx, globalObject, global_funcs)` (`ScriptEngine.cpp:345`).
3. The 21 classes: a loop over `global_classes` (`ScriptEngine.cpp:358-359`) calls `ScriptEngine::InitClass`, which calls `JS_InitClass(cx, global, NULL, classp, classp->construct, 0, props, methods, s_props, s_methods)` (`ScriptEngine.cpp:230-234`). The constructor is the `JSClass` `construct` hook that `JSCLASS_SPEC` fills in (`js32.h:163-164`). The `JSClassSpec` constructor and arity fields are not used.
4. `me`: `BuildObject(cx, &unit_class, unit_methods, me_props, lpUnit)` (`ScriptEngine.cpp:361`), defined as the global `me` with `JSPROP_PERMANENT_VAR` (`ScriptEngine.cpp:365`). See [§9](#9-the-me-object).
5. Constants: `DEFCONST(FILE_READ/FILE_WRITE/FILE_APPEND)` (`ScriptEngine.cpp:368-371`).

Consequences that every page relies on:

- **Nothing is shared between scripts.** Function objects, prototypes and `me` exist once per script. Data that crosses scripts (`load` arguments, `scriptBroadcast`, `D2BSScript.prototype.send`) is copied by structured clone ([globals-core.md](globals-core.md#registration)).
- **Global functions are ordinary writable properties.** `FUNCTION_FLAGS` is `JSFUN_STUB_GSOPS` (`js32.h:134`) and carries no `JSPROP_*` bits, so a script can overwrite or delete `print`, `delay` and the rest. Declared `nargs` only sets `.length` ([globals-core.md](globals-core.md#registration)).
- **Instances carry their own copies of members.** `BuildObject` (`js32.cpp:8-28`) defines the method and property tables again on each new object (`js32.cpp:18-21`), and these shadow the identical ones on the prototype.
- **Property attributes.** `JSPROP_PERMANENT_VAR` = read-only, enumerable, permanent. `JSPROP_STATIC_VAR` = enumerable, permanent, writable (`js32.h:100-101`). In this index, **(w)** marks a `JSPROP_STATIC_VAR` property that has a setter.
- **Script state is a separate gate.** A script started as `InGame` is terminated at its next operation callback while the client is at the menu (`ScriptEngine.cpp:315-323`). This is independent of the per-native [State column](#state-column).

Engine-level detail is in [../spidermonkey/embedding.md](../spidermonkey/embedding.md#3-global-object-setup).

---

## 4. Entry template

Each global function, method and working constructor gets an H3 heading that holds the JS call shape in backticks, with optional arguments in brackets: `name(a[, b])` for globals, `Class.prototype.name(...)` for methods, `Class.name(...)` for static methods, and `new Class(...)` or `Class(...)` for constructors. A short summary follows, then these bullets in this order:

| Field (bold label) | What it records |
|---|---|
| **Native** | The C++ native and its definition (`File.cpp:LINE`), the registration line, the declared arity and the flags. |
| **Arguments / overloads** | How each `argv` slot is tested and converted, how an overload is chosen, and what a missing or wrong-typed argument does. |
| **Returns** | Every return path: value, `false` plus a warning, a thrown `Error`, or a return value that is never set. |
| **Preconditions** | Required client state (in game, menu, either), INI gates such as `EnableUnsupported`, required UI state, and what happens when a precondition is not met. |
| **Threading & blocking** | The thread it runs on (the calling script's own thread unless stated otherwise), locks taken (the game-loop lock), and sleeps, polls and waits on other scripts. |
| **Side effects** | Game-memory writes, packets sent, files, D2BS `Vars`, console output. |
| **Game internals** | The Game.exe functions, globals and structs touched, by their `D2Ptrs.h` / `D2Structs.h` names, with links into [../memory/](../memory/README.md). |
| **Quirks / bugs** | Defects, crashes, leaks, races, and how this entry differs from the legacy docs. |

Variations:

- When entries share behaviour, a combined label stands in for the bullets, for example "**Arguments / overloads / Returns / ... :** as `md5`" for the hash family, or "see `stringToEUC`" for aliases.
- Class sections (`## ClassName`) open with bullets **JSClass**, **Constructor**, **Private data**, **Identity & lifetime** and, where the class has one, **Finalizer** ([unit-properties.md](unit-properties.md#unit) uses subsections for the same items). A property table follows with the columns `Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes`.
- Event entries in [events.md](events.md#2-conventions) use **Signature**, **Origin**, **Thread**, **Delivery**, **Return effect** and **Payload** instead.
- Page structure: each page opens with a scope paragraph, a contents list and a conventions section. Pages close with some of these sections: facts for an RPC replacement, legacy-doc discrepancies, defects and quirks, and open questions. [globals-game.md](globals-game.md) has no separate legacy table; its legacy notes sit in each entry's **Quirks / bugs**.

---

## 5. Conventions

### Citations

A source fact is cited as `File.cpp:LINE` or `File.cpp:A-B`, with paths relative to the repo root (`Map/...`, and `dependencies/include/...` for the bundled SpiderMonkey headers). Inside an entry, a bare `:LINE` means a line in the file named in that entry's **Native** bullet (or the file cited just before it). A doc fact is a relative link to the heading that states it. Facts that cannot be settled from this repository, such as engine-internal behaviour or what Game.exe does inside a called function, are flagged as unverified and listed under the page's "Open questions".

### Shared tags

Every page defines the tags it uses in its own conventions section, and entries then refer to them in bold. The wording varies a little from page to page. These are the common ones:

| Tag | Meaning | Defined in |
|---|---|---|
| **(unset)** / **unset** / **rval unset** / **callee-return** | The native returns `JS_TRUE` without `JS_SET_RVAL`, so the script sees whatever the return slot holds: most likely the callee for functions and the property's cached slot value for getters. This is engine-defined; see the linked definitions and their Open questions. | [globals-core](globals-core.md#return-values), [globals-game](globals-game.md#conventions-and-shared-mechanics), [unit-properties](unit-properties.md#getter--setter-mechanics) |
| **argc unchecked** / **argv over-read** / **argv beyond argc** | `JS_ARGV(cx,vp)[i]` is read for `i >= argc`. | [globals-core](globals-core.md#reading-arguments-past-argc), [unit-methods](unit-methods.md#conventions-used-on-this-page) |
| **Throws** | `THROW_ERROR` = `JS_ReportError` + `return JS_FALSE` (`js32.h:113-117`), a catchable `Error`. | [globals-core](globals-core.md#errors) |
| **Game not ready** (warning) | `THROW_WARNING` = `JS_ReportWarning` + return value `false` + `JS_TRUE` (`js32.h:118-123`). This is not an exception. | [globals-game](globals-game.md#conventions-and-shared-mechanics) |
| **WaitForGameReady** / ready-wait | Returns `false` at once for `ClientStateNull`/`ClientStateMenu`. While `ClientStateBusy` it polls every 10 ms for up to `Vars.dwGameTimeout` = `GameReadyTimeout` seconds × 1000, default 5 s, 0 = no limit (`D2Helpers.cpp:153-166`, `Helpers.cpp:127`, `Helpers.cpp:144`). | [globals-game](globals-game.md#conventions-and-shared-mechanics) |
| **Game-loop lock** | `AutoCriticalRoom` on `Vars.cGameLoopSection` (`CriticalSections.h:31-55`). While it is held the game loop is frozen. | [globals-game](globals-game.md#conventions-and-shared-mechanics), [../architecture.md](../architecture.md#42-the-game-lock-cgameloopsection-in-detail) |
| **Malformed bool**, **Private without class check**, **Int tag tests** / **int-tag test**, **Object test** | Value-encoding and private-pointer hazards of the binding layer. | [globals-game](globals-game.md#conventions-and-shared-mechanics) |
| Page-specific tags, e.g. **resolve `this`**, **pending-error-but-true**, **no lock**, **uncatchable abort**, **lock leak**, **raw pointer private**, **snapshot private**, **dangling root**, **new optional** | Defined where they are used. | [unit-methods](unit-methods.md#conventions-used-on-this-page), [world](world.md#conventions-used-on-this-page), [screenhooks](screenhooks.md#conventions), [utility-classes](utility-classes.md#conventions), [out-of-game](out-of-game.md#conventions-specific-to-this-page), [events](events.md#2-conventions) |

### Client states

`ClientState()` (`D2Helpers.cpp:125-147`) returns one of four values:

- `ClientStateInGame`: a player unit exists with an inventory and a complete path → room → level chain, and there is no D2WIN control.
- `ClientStateBusy`: a player unit exists and there is no D2WIN control, but the unit has `pUpdateUnit` set or an incomplete chain.
- `ClientStateMenu`: there is no player unit and a D2WIN control exists.
- `ClientStateNull`: anything else.

Background: [../architecture.md](../architecture.md#81-clientstate).

### State column

Used by the [global function table](#6-global-functions):

- **in game**: the native requires `ClientStateInGame` (through `WaitForGameReady`, `GameReady()` or a `ClientState()` test) and otherwise fails with a warning plus `false`, a throw, `undefined` or an unset value.
- **OOG**: the native requires `ClientStateMenu` (for example `JSMenu.cpp:12`, `JSControl.cpp:295`) and otherwise returns early.
- **either**: the native has no client-state check. It may still touch game memory that only makes sense in one state, or need `EnableUnsupported`; the summary or the linked entry says so.

The classification matches the census in [../rpc-considerations.md](../rpc-considerations.md#13-global-functions-108-names).

### Legacy-doc discrepancy notes

The legacy references are:

- `doc/*.h`: Doxygen stub headers.
- The repo-root `README.md`: a Markdown rendering of the same Doxygen groups.
- `resources/api.html`: a TiddlyWiki 2.5.3 page.

Pages cite them as `doc/globalFuncs.h:LINE`, `README.md:LINE` and `resources/api.html:LINE`, and record each difference in a "Legacy-doc discrepancies" table (legacy claim vs. code, with the code citation) or in the entry's **Quirks / bugs**. Where they disagree, the code wins.

### Names

JS names are case-sensitive and spelled exactly as registered, including the source's own spellings: `DailogLine`, `writeable` (File, Socket), lower-case `cursorpos` (Control).

---

## 6. Global functions

This table lists every `JS_FN` entry of `global_funcs` (`JSGlobalFuncs.h:23-79`), sorted by name, with aliases on their own rows. **Reg.** is the line in `JSGlobalFuncs.h`. **Native** is the C function and the line where `JSAPI_FUNC(...)` defines it. **State** follows the [legend above](#state-column). Category counts: Game query (18), Game action (18), Script control (11), Hashing (10), Menu (8), World (5), Host misc (5), Timers (5), Console (4), Clipboard & IPC (4), Input (4), Events (4), Units (3), Files & DB (3), Packets (2), Screen hooks (2), Misc (1), Messaging (1).

| Name | Category | State | Summary | Native (defined) | Reg. | Doc |
|---|---|---|---|---|---|---|
| [`acceptTrade`](globals-game.md#accepttrademode) | Game action | in game | Toggles trade acceptance, or returns trade state when given a mode. | `my_acceptTrade` `JSGame.cpp:106` | `:62` | [globals-game](globals-game.md#accepttrademode) |
| [`addEventListener`](globals-core.md#addeventlistenername-listener) | Events | either | Appends a listener for an event name to the caller's list ([events](#11-events)). | `my_addEventListener` `JSCore.cpp:470` | `:46` | [globals-core](globals-core.md#addeventlistenername-listener) |
| [`addProfile`](out-of-game.md#addprofileprofile-mode-gateway-username-password-character-spdifficulty) | Menu | either | Appends a profile section to `d2bs.ini` if none of that name exists. | `my_addProfile` `JSMenu.cpp:112` | `:58` | [out-of-game](out-of-game.md#addprofileprofile-mode-gateway-username-password-character-spdifficulty) |
| [`automapToScreen`](screenhooks.md#automaptoscreenpoint--x-y) | Screen hooks | either | Applies D2BS's automap-to-screen formula. | `automapToScreen` `JSScreenHook.cpp:783` | `:73` | [screenhooks](screenhooks.md#automaptoscreenpoint--x-y) |
| [`beep`](globals-core.md#beeptype) | Input | either | Calls `MessageBeep(type)`. | `my_beep` `JSCore.cpp:255` | `:63` | [globals-core](globals-core.md#beeptype) |
| [`checkCollision`](globals-game.md#checkcollisionunita-unitb-mask) | Game query | in game | The game's unit-to-unit collision test; returns an int. | `my_checkCollision` `JSGame.cpp:826` | `:64` | [globals-game](globals-game.md#checkcollisionunita-unitb-mask) |
| [`clearAllEvents`](globals-core.md#clearallevents) | Events | either | Removes all of the caller's listeners, timer callbacks included. | `my_clearAllEvents` `JSCore.cpp:506` | `:48` | [globals-core](globals-core.md#clearallevents) |
| [`clearEvent`](globals-core.md#cleareventname) | Events | either | Removes all of the caller's listeners for one name. | `my_clearEvent` `JSCore.cpp:496` | `:47` | [globals-core](globals-core.md#cleareventname) |
| [`clearInterval`](globals-core.md#clearintervalid) | Timers | either | Cancels the timer with that id, in any script. | `my_clearInterval` `JSCore.cpp:117` | `:42` | [globals-core](globals-core.md#clearintervalid) |
| [`clearTimeout`](globals-core.md#cleartimeoutid) | Timers | either | **Alias**: registered with the `clearInterval` native. | `my_clearInterval` `JSCore.cpp:117` | `:41` | [globals-core](globals-core.md#cleartimeoutid) |
| [`clickItem`](globals-game.md#clickitemitem--clicktype-bodyloc--clicktype-item--button-x-y-location) | Game action | in game | Simulates inventory/belt/equipment/merc clicks through the client UI handlers. | `my_clickItem` `JSGame.cpp:357` | `:63` | [globals-game](globals-game.md#clickitemitem--clicktype-bodyloc--clicktype-item--button-x-y-location) |
| [`clickMap`](globals-game.md#clickmaptype-shift-unit--x-y) | Game action | in game | Simulates a world click at a unit or map coordinate. | `my_clickMap` `JSGame.cpp:63` | `:62` | [globals-game](globals-game.md#clickmaptype-shift-unit--x-y) |
| [`clickParty`](globals-game.md#clickpartyparty-mode) | Game action | in game | Presses a party-screen button for a roster entry. | `my_clickParty` `JSGame.cpp:1074` | `:66` | [globals-game](globals-game.md#clickpartyparty-mode) |
| [`copy`](globals-core.md#copytext) | Clipboard & IPC | either | Puts text on the Windows clipboard as `CF_TEXT`. | `my_copy` `JSCore.cpp:335` | `:45` | [globals-core](globals-core.md#copytext) |
| [`copyUnit`](globals-game.md#copyunitunit) | Units | either | New, independent Unit holding a copy of the argument's identity snapshot. | `my_copyUnit` `JSGame.cpp:19` | `:62` | [globals-game](globals-game.md#copyunitunit) |
| [`createGame`](out-of-game.md#creategamename-password-difficulty) | Menu | OOG | Creates a Battle.net/Open game from the lobby (on the SP difficulty screen: picks a difficulty). | `my_createGame` `JSMenu.cpp:61` | `:57` | [out-of-game](out-of-game.md#creategamename-password-difficulty) |
| [`debugLog`](globals-core.md#debuglogvalues) | Console | either | Writes each non-null argument as a line of the D2BS log file. | `my_debugLog` `JSCore.cpp:307` | `:50` | [globals-core](globals-core.md#debuglogvalues) |
| [`delay`](globals-core.md#delayms) | Timers | either | Sleeps the caller for `ms` while servicing its event queue. | `my_delay` `JSCore.cpp:125` | `:42` | [globals-core](globals-core.md#delayms) |
| [`dopen`](utility-classes.md#dopenname) | Files & DB | either | `Folder` for `scripts\<name>`, creating the directory if needed. | `my_openDir` `JSDirectory.cpp:37` | `:50` | [utility-classes](utility-classes.md#dopenname) |
| [`getArea`](world.md#getareaarea) | World | in game | Area for a level id or the player's current level. | `my_getArea` `JSArea.cpp:94` | `:33` | [world](world.md#getareaarea) |
| [`getBaseStat`](globals-game.md#getbasestattable-row-column) | Game query | either | Reads one cell of a game data table from memory (needs the data tables loaded). | `my_getBaseStat` `JSGame.cpp:1175` | `:34` | [globals-game](globals-game.md#getbasestattable-row-column) |
| [`getCollision`](globals-game.md#getcollisionarea-x-y) | Game query | in game | 16-bit collision word at an absolute map coordinate. | `my_getCollision` `JSGame.cpp:324` | `:25` | [globals-game](globals-game.md#getcollisionarea-x-y) |
| [`getControl`](out-of-game.md#getcontroltype-x-y-xsize-ysize) | Menu | OOG | First D2WIN control matching type and geometry, as a `Control`. | `my_getControl` `JSControl.cpp:292` | `:34` | [out-of-game](out-of-game.md#getcontroltype-x-y-xsize-ysize) |
| [`getControls`](out-of-game.md#getcontrols) | Menu | OOG | One `Control` per entry of the D2WIN control list. | `my_getControls` `JSControl.cpp:325` | `:35` | [out-of-game](out-of-game.md#getcontrols) |
| [`getCursorType`](globals-game.md#getcursortypetype) | Game query | either | Returns the regular or shop cursor-type global. | `my_getCursorType` `JSGame.cpp:851` | `:26` | [globals-game](globals-game.md#getcursortypetype) |
| [`getDialogLines`](globals-game.md#getdialoglines) | Game query | either | Lines of the open NPC dialog as [`DailogLine`](#dailogline) objects. No state check. | `my_getDialogLines` `JSGame.cpp:170` | `:37` | [globals-game](globals-game.md#getdialoglines) |
| [`getDistance`](globals-game.md#getdistancea-b-c-d) | Game query | in game | Euclidean distance between units/points; the player is implicit in the short forms. | `my_getDistance` `JSGame.cpp:714` | `:64` | [globals-game](globals-game.md#getdistancea-b-c-d) |
| [`getInteractedNPC`](globals-game.md#getinteractednpc) | Game query | in game | Unit for the NPC currently interacted with, or `false`. | `my_getInteractedNPC` `JSGame.cpp:1386` | `:36` | [globals-game](globals-game.md#getinteractednpc) |
| [`getIP`](globals-core.md#getip) | Host misc | either | Fetches the external IPv4 address over synchronous HTTP. | `my_getIP` `JSCore.cpp:660` | `:70` | [globals-core](globals-core.md#getip) |
| [`getIsTalkingNPC`](globals-game.md#getistalkingnpc) | Game query | in game | Whether an NPC's scrolling speech text is on screen. | `my_getIsTalkingNPC` `JSGame.cpp:1378` | `:37` | [globals-game](globals-game.md#getistalkingnpc) |
| [`getLocaleString`](globals-game.md#getlocalestringid) | Game query | either | String with locale index `id` from the client string tables. | `my_getLocaleString` `JSGame.cpp:663` | `:28` | [globals-game](globals-game.md#getlocalestringid) |
| [`getLocation`](out-of-game.md#getlocation) | Menu | OOG | Current OOG screen code, from probing the D2WIN control list. | `my_getOOGLocation` `JSMenu.cpp:155` | `:58` | [out-of-game](out-of-game.md#getlocation) |
| [`getMercHP`](unit-methods.md#getmerchp) | Units | in game | HP percentage of the player's mercenary. | `unit_getMercHP` `JSUnit.cpp:1689` | `:26` | [unit-methods](unit-methods.md#getmerchp) |
| [`getMouseCoords`](globals-game.md#getmousecoordstomap-asobject) | Game query | either | Mouse position in screen or map coordinates. | `my_getMouseCoords` `JSGame.cpp:1296` | `:61` | [globals-game](globals-game.md#getmousecoordstomap-asobject) |
| [`getPacket`](globals-core.md#getpacket) | Packets | either | Injects a raw server-to-client packet into the receive path. Needs `EnableUnsupported`; no client-state check. | `my_getPacket` `JSCore.cpp:614` | `:69` | [globals-core](globals-core.md#getpacket) |
| [`getParty`](world.md#getpartyname--gid--unit) | World | in game | Party roster entry: the first one, or by name, gid or Unit. | `my_getParty` `JSParty.cpp:83` | `:32` | [world](world.md#getpartyname--gid--unit) |
| [`getPath`](globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) | Game query | in game | D2BS A* path over the collision map, reduced to waypoints. | `my_getPath` `JSGame.cpp:229` | `:25` | [globals-game](globals-game.md#getpatharea-x-y-dx-dy-reductiontype-radius-reject-reduce-mutate) |
| [`getPlayerFlag`](globals-game.md#getplayerflagunitid1-unitid2-flag) | Game query | in game | Tests a PvP/party relationship flag between two player unit ids. | `my_getPlayerFlag` `JSGame.cpp:1275` | `:35` | [globals-game](globals-game.md#getplayerflagunitid1-unitid2-flag) |
| [`getPresetUnit`](world.md#getpresetunitarea-type-classid) | World | in game | First PresetUnit in a level matching type and class id. | `my_getPresetUnit` `JSPresetUnit.cpp:136` | `:32` | [world](world.md#getpresetunitarea-type-classid) |
| [`getPresetUnits`](world.md#getpresetunitsarea-type-classid) | World | in game | Every PresetUnit in a level matching type and class id. | `my_getPresetUnits` `JSPresetUnit.cpp:53` | `:33` | [world](world.md#getpresetunitsarea-type-classid) |
| [`getRoom`](world.md#getroomarea--x-y--area-x-y) | World | in game | Room for a level's first room, the player's room, or the room at a point. | `my_getRoom` `JSRoom.cpp:454` | `:31` | [world](world.md#getroomarea--x-y--area-x-y) |
| [`getScript`](utility-classes.md#getscriptselector) | Script control | either | `D2BSScript` for the current script, a thread id, a file name, or the first script. | `my_getScript` `JSScript.cpp:142` | `:31` | [utility-classes](utility-classes.md#getscriptselector) |
| [`getScripts`](utility-classes.md#getscripts) | Script control | either | `D2BSScript` wrappers for every entry of the script map. | `my_getScripts` `JSScript.cpp:188` | `:31` | [utility-classes](utility-classes.md#getscripts) |
| [`getSkillById`](globals-game.md#getskillbyidid) | Game query | either | Localized skill name for a skill id (needs the data tables loaded). | `my_getSkillById` `JSGame.cpp:881` | `:27` | [globals-game](globals-game.md#getskillbyidid) |
| [`getSkillByName`](globals-game.md#getskillbynamename) | Game query | either | Intended skill-name to id lookup; **broken**, throws for any non-empty name. | `my_getSkillByName` `JSGame.cpp:862` | `:27` | [globals-game](globals-game.md#getskillbynamename) |
| [`getTextSize`](globals-game.md#gettextsizetext-font-asobject) | Game query | either | Measures a string in a D2 font: `[w, h]` or `{width, height}`. | `my_getTextSize` `JSGame.cpp:900` | `:28` | [globals-game](globals-game.md#gettextsizetext-font-asobject) |
| [`getThreadPriority`](globals-core.md#getthreadpriority) | Script control | either | Returns the `GetCurrentThread()` pseudo-handle (always -2), not a priority. | `my_getThreadPriority` `JSCore.cpp:275` | `:29` | [globals-core](globals-core.md#getthreadpriority) |
| [`getTickCount`](globals-core.md#gettickcount) | Host misc | either | Returns `GetTickCount()`. | `my_getTickCount` `JSCore.cpp:266` | `:36` | [globals-core](globals-core.md#gettickcount) |
| [`getTradeInfo`](globals-game.md#gettradeinfomode) | Game query | in game | Returns the client's recent trade state id. | `my_getTradeInfo` `JSGame.cpp:938` | `:30` | [globals-game](globals-game.md#gettradeinfomode) |
| [`getUIFlag`](globals-game.md#getuiflagid) | Game query | in game | Whether client UI variable `id` (a panel or screen) is set. | `my_getUIFlag` `JSGame.cpp:975` | `:29` | [globals-game](globals-game.md#getuiflagid) |
| [`getUnit`](unit-methods.md#getunittype-nameorclassid-mode-gid) | Units | in game | First unit matching type / name or classid / mode / gid; the object keeps the filters for `getNext`. Types 100/101 skip the state check. | `unit_getUnit` `JSUnit.cpp:572` | `:25` | [unit-methods](unit-methods.md#getunittype-nameorclassid-mode-gid) |
| [`getWaypoint`](globals-game.md#getwaypointindex) | Game query | in game | Whether the player has waypoint number `index`. | `my_getWaypoint` `JSGame.cpp:990` | `:30` | [globals-game](globals-game.md#getwaypointindex) |
| [`gold`](globals-game.md#goldamount-mode) | Game action | in game | Performs a gold-dialog transfer (drop/stash/withdraw) of an amount. | `my_gold` `JSGame.cpp:809` | `:64` | [globals-game](globals-game.md#goldamount-mode) |
| [`handler`](globals-core.md#handler) | Script control | either | Returns the window handle passed with `-handle <n>` on the command line. | `my_handler` `JSCore.cpp:553` | `:51` | [globals-core](globals-core.md#handler) |
| [`hideConsole`](globals-core.md#hideconsole) | Console | either | Hides the D2BS console and disables its prompt. | `my_hideConsole` `JSCore.cpp:547` | `:51` | [globals-core](globals-core.md#hideconsole) |
| [`include`](globals-core.md#includefile) | Script control | either | Compiles and runs `<scripts>\libs\file` in the caller's global, at most once per script. | `my_include` `JSCore.cpp:212` | `:43` | [globals-core](globals-core.md#includefile) |
| [`isIncluded`](globals-core.md#isincludedfile) | Script control | either | Whether `libs\file` was successfully included by the caller. | `my_isIncluded` `JSCore.cpp:280` | `:43` | [globals-core](globals-core.md#isincludedfile) |
| [`joinGame`](out-of-game.md#joingamename-password) | Menu | OOG | Types a game name and password on the Join tab and joins. | `my_joinGame` `JSMenu.cpp:88` | `:57` | [out-of-game](out-of-game.md#joingamename-password) |
| [`js_strict`](globals-core.md#js_strictenable) | Script control | either | Gets/sets `JSOPTION_STRICT` (extra warnings, not ES5 strict) on the caller's context. | `my_js_strict` `JSCore.cpp:512` | `:48` | [globals-core](globals-core.md#js_strictenable) |
| [`keystate`](globals-core.md#keystatevk) | Input | either | Returns `!!GetAsyncKeyState(vk)`. | `my_keystate` `JSCore.cpp:460` | `:46` | [globals-core](globals-core.md#keystatevk) |
| [`load`](globals-core.md#loadfile-args) | Script control | either | Starts `<scripts>\file` as a new script thread; extra args are structured-cloned to its `main`. Returns `null`. | `my_load` `JSCore.cpp:168` | `:43` | [globals-core](globals-core.md#loadfile-args) |
| [`loadMpq`](globals-core.md#loadmpqpath) | Host misc | either | Loads an MPQ archive via `D2WIN_InitMPQ`; the path must pass `isValidPath`. | `my_loadMpq` `JSCore.cpp:558` | `:58` | [globals-core](globals-core.md#loadmpqpath) |
| [`login`](out-of-game.md#loginprofile) | Menu | OOG | Drives the menus to a lobby or into a game using a `d2bs.ini` profile. | `my_login` `JSMenu.cpp:10` | `:54` | [out-of-game](out-of-game.md#loginprofile) |
| [`md5`](globals-core.md#md5str) | Hashing | either | MD5 of the UTF-8 encoding of `String(str)`, lowercase hex. | `my_md5` `JSHash.cpp:7` | `:76` | [globals-core](globals-core.md#md5str) |
| [`md5_file`](globals-core.md#md5_filepath) | Hashing | either | MD5 of the file `<scripts>\path`, lowercase hex. | `my_md5_file` `JSHash.cpp:72` | `:77` | [globals-core](globals-core.md#md5_filepath) |
| [`moveNPC`](globals-game.md#movenpcnpc-x-y) | Game action | in game | Raw "move entity" request for an NPC. Needs `EnableUnsupported`. | `my_moveNPC` `JSGame.cpp:1421` | `:69` | [globals-game](globals-game.md#movenpcnpc-x-y) |
| [`paste`](globals-core.md#paste) | Clipboard & IPC | either | Returns the clipboard's `CF_TEXT` content. | `my_paste` `JSCore.cpp:354` | `:45` | [globals-core](globals-core.md#paste) |
| [`playSound`](globals-game.md#playsoundid) | Game action | either | No-op placeholder. | `my_playSound` `JSGame.cpp:1030` | `:65` | [globals-game](globals-game.md#playsoundid) |
| [`print`](globals-core.md#printvalues) | Console | either | Queues each non-null argument as a console line (also game chat with `UseGamePrint`). | `my_print` `JSCore.cpp:49` | `:40` | [globals-core](globals-core.md#printvalues) |
| [`quit`](globals-game.md#quit) | Game action | either | Leaves the current game (`D2CLIENT_ExitGame` unless at the menu). | `my_quit` `JSGame.cpp:1021` | `:65` | [globals-game](globals-game.md#quit) |
| [`quitGame`](globals-game.md#quitgame) | Game action | either | Leaves the game, shuts D2BS down and terminates the process. | `my_quitGame` `JSGame.cpp:1009` | `:65` | [globals-game](globals-game.md#quitgame) |
| [`rand`](globals-game.md#randlow-high) | Misc | either | Random integer: game RNG in game, CRT RNG out of game. | `my_rand` `JSGame.cpp:677` | `:44` | [globals-game](globals-game.md#randlow-high) |
| [`removeEventListener`](globals-core.md#removeeventlistenername-listener) | Events | either | Removes the first registration of a listener under a name. | `my_removeEventListener` `JSCore.cpp:483` | `:47` | [globals-core](globals-core.md#removeeventlistenername-listener) |
| [`revealLevel`](globals-game.md#reveallevelpresets) | Game action | in game | Reveals every room of the current level on the automap. | `my_revealLevel` `JSGame.cpp:1456` | `:71` | [globals-game](globals-game.md#reveallevelpresets) |
| [`say`](globals-game.md#sayvalues) | Game action | either | Sends each argument as a chat line in game, or as a channel message at the menu. | `my_say` `JSGame.cpp:1044` | `:66` | [globals-game](globals-game.md#sayvalues) |
| [`screenToAutomap`](screenhooks.md#screentoautomappoint--x-y) | Screen hooks | either | Projects a world (map) coordinate to automap pixel coordinates. | `screenToAutomap` `JSScreenHook.cpp:736` | `:73` | [screenhooks](screenhooks.md#screentoautomappoint--x-y) |
| [`scriptBroadcast`](globals-core.md#scriptbroadcastvalues) | Messaging | either | Queues a `scriptmsg` with deep copies of the values to every listening script, sender included. | `my_scriptBroadcast` `JSCore.cpp:532` | `:49` | [globals-core](globals-core.md#scriptbroadcastvalues) |
| [`selectCharacter`](out-of-game.md#selectcharacterprofile) | Menu | OOG | Clicks the profile's character on the character-select screen, then OK. | `my_selectChar` `JSMenu.cpp:43` | `:57` | [out-of-game](out-of-game.md#selectcharacterprofile) |
| [`sendClick`](globals-core.md#sendclickx-y) | Input | either | Posts a left-button down/up at client (x, y) to the D2 window. | `my_sendClick` `JSCore.cpp:677` | `:70` | [globals-core](globals-core.md#sendclickx-y) |
| [`sendCopyData`](globals-core.md#sendcopydatawindowclass-windownameorhwnd-mode-data) | Clipboard & IPC | either | Sends `WM_COPYDATA` to a window synchronously (no timeout). | `my_sendCopyData` `JSCore.cpp:365` | `:45` | [globals-core](globals-core.md#sendcopydatawindowclass-windownameorhwnd-mode-data) |
| [`sendDDE`](globals-core.md#sendddemode-server-topic-item-data) | Clipboard & IPC | either | Performs one DDEML client transaction (request, poke or execute). | `my_sendDDE` `JSCore.cpp:419` | `:46` | [globals-core](globals-core.md#sendddemode-server-topic-item-data) |
| [`sendKey`](globals-core.md#sendkeyvk) | Input | either | Posts `WM_KEYDOWN`/`WM_KEYUP` for a virtual key to the D2 window. | `my_sendKey` `JSCore.cpp:695` | `:70` | [globals-core](globals-core.md#sendkeyvk) |
| [`sendPacket`](globals-core.md#sendpacket) | Packets | either | Sends a raw client-to-server packet via `D2NET_SendPacket`. Needs `EnableUnsupported`; no client-state check. | `my_sendPacket` `JSCore.cpp:569` | `:69` | [globals-core](globals-core.md#sendpacket) |
| [`setInterval`](globals-core.md#setintervalcallback-ms) | Timers | either | Schedules a repeating callback; returns a timer id. | `my_setInterval` `JSCore.cpp:98` | `:42` | [globals-core](globals-core.md#setintervalcallback-ms) |
| [`setTimeout`](globals-core.md#settimeoutcallback-ms) | Timers | either | Schedules a one-shot callback; returns a timer id. | `my_setTimeout` `JSCore.cpp:78` | `:41` | [globals-core](globals-core.md#settimeoutcallback-ms) |
| [`sha1`](globals-core.md#sha1str) | Hashing | either | As `md5`, with SHA-1. | `my_sha1` `JSHash.cpp:20` | `:76` | [globals-core](globals-core.md#sha1str) |
| [`sha1_file`](globals-core.md#sha1_filepath) | Hashing | either | As `md5_file`, with SHA-1. | `my_sha1_file` `JSHash.cpp:90` | `:78` | [globals-core](globals-core.md#sha1_filepath) |
| [`sha256`](globals-core.md#sha256str) | Hashing | either | As `md5`, with SHA-256 (if the CryptoAPI provider supports it). | `my_sha256` `JSHash.cpp:33` | `:76` | [globals-core](globals-core.md#sha256str) |
| [`sha256_file`](globals-core.md#sha256_filepath) | Hashing | either | As `md5_file`, with SHA-256. | `my_sha256_file` `JSHash.cpp:108` | `:78` | [globals-core](globals-core.md#sha256_filepath) |
| [`sha384`](globals-core.md#sha384str) | Hashing | either | As `md5`, with SHA-384. | `my_sha384` `JSHash.cpp:46` | `:77` | [globals-core](globals-core.md#sha384str) |
| [`sha384_file`](globals-core.md#sha384_filepath) | Hashing | either | As `md5_file`, with SHA-384. | `my_sha384_file` `JSHash.cpp:126` | `:78` | [globals-core](globals-core.md#sha384_filepath) |
| [`sha512`](globals-core.md#sha512str) | Hashing | either | As `md5`, with SHA-512. | `my_sha512` `JSHash.cpp:59` | `:77` | [globals-core](globals-core.md#sha512str) |
| [`sha512_file`](globals-core.md#sha512_filepath) | Hashing | either | As `md5_file`, with SHA-512. | `my_sha512_file` `JSHash.cpp:144` | `:79` | [globals-core](globals-core.md#sha512_filepath) |
| [`showConsole`](globals-core.md#showconsole) | Console | either | Shows the D2BS console and enables its prompt. | `my_showConsole` `JSCore.cpp:541` | `:51` | [globals-core](globals-core.md#showconsole) |
| [`sqlite_memusage`](utility-classes.md#sqlite_memusage) | Files & DB | either | Meant to return `sqlite3_memory_used()`; **broken**, the return value is never set. | `my_sqlite_memusage` `JSSQLite.cpp:72` | `:50` | [utility-classes](utility-classes.md#sqlite_memusage) |
| [`sqlite_version`](utility-classes.md#sqlite_version) | Files & DB | either | Linked SQLite version string. | `my_sqlite_version` `JSSQLite.cpp:67` | `:49` | [utility-classes](utility-classes.md#sqlite_version) |
| [`stacktrace`](globals-core.md#stacktrace) | Script control | either | Writes the native call stacks of every thread to the D2BS log. | `my_stacktrace` `JSCore.cpp:249` | `:44` | [globals-core](globals-core.md#stacktrace) |
| [`stop`](globals-core.md#stopself) | Script control | either | Terminates the caller (`stop(1)`/`stop(true)`) or every non-console script. | `my_stop` `JSCore.cpp:237` | `:44` | [globals-core](globals-core.md#stopself) |
| [`stringToEUC`](globals-core.md#stringtoeucvalue) | Host misc | either | Converts to the ANSI code page (`CP_ACP`); one byte per UTF-16 code unit. | `my_stringToEUC` `JSCore.cpp:22` | `:40` | [globals-core](globals-core.md#stringtoeucvalue) |
| [`submitItem`](globals-game.md#submititem) | Game action | in game | Submits the cursor item to the current quest receptacle. | `my_submitItem` `JSGame.cpp:1344` | `:61` | [globals-game](globals-game.md#submititem) |
| [`takeScreenshot`](globals-game.md#takescreenshot) | Game action | either | Requests a screenshot on the next drawn frame. | `my_takeScreenshot` `JSGame.cpp:1416` | `:68` | [globals-game](globals-game.md#takescreenshot) |
| [`tradeOk`](globals-game.md#tradeok) | Game action | in game | Clicks OK on the trade-request dialog. | `my_tradeOk` `JSGame.cpp:147` | `:63` | [globals-game](globals-game.md#tradeok) |
| [`transmute`](globals-game.md#transmute) | Game action | in game | Presses the Horadric Cube transmute button, opening the cube UI if needed. | `my_transmute` `JSGame.cpp:1258` | `:67` | [globals-game](globals-game.md#transmute) |
| [`useSkillPoint`](globals-game.md#useskillpointskill-count) | Game action | in game | Spends unallocated skill points with allocation packets. | `my_useSkillPoint` `JSGame.cpp:1159` | `:68` | [globals-game](globals-game.md#useskillpointskill-count) |
| [`useStatPoint`](globals-game.md#usestatpointstat-count) | Game action | in game | Spends unallocated stat points with allocation packets. | `my_useStatPoint` `JSGame.cpp:1143` | `:67` | [globals-game](globals-game.md#usestatpointstat-count) |
| [`utf8ToEuc`](globals-core.md#utf8toeucvalue) | Host misc | either | **Alias** of `stringToEUC` (same native). | `my_stringToEUC` `JSCore.cpp:22` | `:40` | [globals-core](globals-core.md#utf8toeucvalue) |
| [`version`](globals-core.md#versionprint) | Script control | either | Returns the D2BS version string; with any argument prints a banner and returns `true`. | `my_version` `JSCore.cpp:295` | `:48` | [globals-core](globals-core.md#versionprint) |
| [`weaponSwitch`](globals-game.md#weaponswitchquery) | Game action | in game | Swaps weapon sets, or returns the active set. | `my_weaponSwitch` `JSGame.cpp:1223` | `:66` | [globals-game](globals-game.md#weaponswitchquery) |

Not in the table: `createCharacter`. Its `JS_FN` line is commented out with "this function is not finished" (`JSGlobalFuncs.h:55-56`), but the native `my_createCharacter` (`JSMenu.cpp:165`) is still compiled. It is described in [out-of-game.md](out-of-game.md#createcharactername-classid-hardcore-ladder) so that a replacement doesn't assume it works.

---

## 7. Classes

These are the 21 entries of `global_classes` (`JSGlobalClasses.cpp:145-167`), in registration order, followed by the two classes that are defined but not registered. **Constructible?** says whether `new X()` reaches a real constructor. Every "no" class uses `EMPTY_CTOR` (`js32.h:136-139`), so `new X()` and `X()` throw `"Invalid Operation"`. **Props** counts the property-spec entries, and "w" is how many of them are writable. Member lists follow in [§8](#8-class-members).

| Class | JSClass name (C variable, definition) | `global_classes` row | How obtained | Constructible? | Props | Methods | Static | Doc |
|---|---|---|---|---|---|---|---|---|
| [`Unit`](#unit) | `"Unit"` (`unit_class`, `JSGlobalClasses.cpp:108`) | `:145` | `getUnit`, `Unit.prototype.getItem/getItems/getParent/getMerc`, `getInteractedNPC`, `copyUnit`, global `me`; `getNext` rebinds in place | no (`JSUnit.cpp:11`) | 49 | 25 | – | [unit-properties](unit-properties.md#unit), [unit-methods](unit-methods.md#unit) |
| [`PresetUnit`](#presetunit) | `"PresetUnit"` (`presetunit_class`, `JSGlobalClasses.cpp:72`) | `:146` | `getPresetUnit`, `getPresetUnits`, `Room.prototype.getPresetUnits` | no (`JSPresetUnit.cpp:7`) | 7 | 0 | – | [world](world.md#presetunit) |
| [`Area`](#area) | `"Area"` (`area_class`, `JSGlobalClasses.cpp:104`) | `:147` | `getArea` | no (`JSArea.cpp:7`) | 7 | 0 | – | [world](world.md#area) |
| [`Control`](#control) | `"Control"` (`control_class`, `JSGlobalClasses.cpp:100`) | `:148` | `getControl`, `getControls`; `getNext` rebinds in place | no (`JSControl.cpp:6`) | 12 (3 w) | 4 | – | [out-of-game](out-of-game.md#control) |
| [`Folder`](#folder) | `"Folder"` (`folder_class`, `JSGlobalClasses.cpp:96`) | `:149` | `dopen`, `Folder.prototype.create` | no (`JSDirectory.cpp:35`) | 1 | 4 | – | [utility-classes](utility-classes.md#folder) |
| [`Exit`](#exit) | `"Exit"` (`exit_class`, `JSGlobalClasses.cpp:92`) | `:150` | the `exits` property of an `Area` | no (`JSExits.cpp:3`) | 6 | 0 | – | [world](world.md#exit) |
| [`Party`](#party) | `"Party"` (`party_class`, `JSGlobalClasses.cpp:76`) | `:151` | `getParty`; `getNext` advances in place | no (`JSParty.cpp:8`) | 10 | 1 | – | [world](world.md#party) |
| [`Room`](#room) | `"Room"` (`room_class`, `JSGlobalClasses.cpp:68`) | `:152` | `getRoom`, `Room.prototype.getNearby/getFirst`; `getNext` advances in place | no (`JSRoom.cpp:7`) | 9 | 9 | – | [world](world.md#room) |
| [`File`](#file) | `"File"` (`file_class`, `JSGlobalClasses.cpp:84`) | `:154` | `File.open` | no (`JSFile.cpp:39`) | 13 (1 w) | 11 | 1 | [utility-classes](utility-classes.md#file) |
| [`Socket`](#socket) | `"Socket"` (`socket_class`, `JSGlobalClasses.cpp:88`) | `:155` | `Socket.open` | no (`JSSocket.cpp:24`) | 2 | 3 | 1 | [utility-classes](utility-classes.md#socket) |
| [`FileTools`](#filetools) | `"FileTools"` (`filetools_class`, `JSGlobalClasses.cpp:80`) | `:156` | static namespace only | no (`JSFileTools.cpp:32`) | 0 | 0 | 7 | [utility-classes](utility-classes.md#filetools) |
| [`SQLite`](#sqlite) | `"SQLite"` (`sqlite_db`, `JSGlobalClasses.cpp:32`) | `:157` | `new SQLite(...)` / `SQLite(...)` | **yes** (`JSSQLite.cpp:80`) | 5 | 4 | – | [utility-classes](utility-classes.md#sqlite) |
| [`DBStatement`](#dbstatement) | `"DBStatement"` (`sqlite_stmt`, `JSGlobalClasses.cpp:36`) | `:158` | `SQLite.prototype.query`, `SQLite.prototype.statements` | no (`JSSQLite.cpp:78`) | 2 | 10 | – | [utility-classes](utility-classes.md#dbstatement) |
| [`Sandbox`](#sandbox) | `"Sandbox"` (`sandbox_class`, `JSGlobalClasses.cpp:64`) | `:159` | `new Sandbox()` | **yes**, but it passes a NULL runtime to `JS_NewContext` (`JSSandbox.cpp:8`), which crashes ([R-03](../OPEN_QUESTIONS.md#appendix-a-resolved-during-triage)) | 0 | 4 | – | [utility-classes](utility-classes.md#sandbox) |
| [`D2BSScript`](#d2bsscript) | `"D2BSScript"` (`script_class`, `JSGlobalClasses.cpp:40`) | `:160` | `getScript`, `getScripts`; `getNext` advances in place | no (`JSScript.cpp:7`) | 5 | 6 | – | [utility-classes](utility-classes.md#d2bsscript) |
| [`Frame`](#frame) | `"Frame"` (`frame_class`, `JSGlobalClasses.cpp:44`) | `:162` | `new Frame(...)` | **yes** (`JSScreenHook.cpp:37`) | 9 (9 w) | 1 | – | [screenhooks](screenhooks.md#frame) |
| [`Box`](#box) | `"Box"` (`box_class`, `JSGlobalClasses.cpp:48`) | `:163` | `new Box(...)` | **yes** (`JSScreenHook.cpp:169`) | 11 (11 w) | 1 | – | [screenhooks](screenhooks.md#box) |
| [`Line`](#line) | `"Line"` (`line_class`, `JSGlobalClasses.cpp:52`) | `:164` | `new Line(...)` | **yes** (`JSScreenHook.cpp:319`) | 9 (9 w) | 1 | – | [screenhooks](screenhooks.md#line) |
| [`Text`](#text) | `"Text"` (`text_class`, `JSGlobalClasses.cpp:56`) | `:165` | `new Text(...)` | **yes** (`JSScreenHook.cpp:451`) | 10 (10 w) | 1 | – | [screenhooks](screenhooks.md#text) |
| [`Image`](#image) | `"Image"` (`image_class`, `JSGlobalClasses.cpp:60`) | `:166` | `new Image(...)` | **yes** (`JSScreenHook.cpp:600`) | 8 (8 w) | 1 | – | [screenhooks](screenhooks.md#image) |
| [`Profile`](#profile) | `"Profile"` (`profile_class`, `JSGlobalClasses.cpp:112`) | `:167` | `new Profile(...)` / `Profile(...)` | **yes** (`JSProfile.cpp:16`) | 8 | 1 | – | [out-of-game](out-of-game.md#profile) |
| [`DailogLine`](#dailogline) | `"DailogLine"` (`dialogLine_class`, `JSGlobalClasses.cpp:120`) | not registered | elements of the `getDialogLines()` array (`JSGame.cpp:191`) | n/a (no constructor, not a global) | 2 own data props | 1 own function | – | [globals-game](globals-game.md#dailogline) |
| [`ProfileType`](#profiletype) | `"ProfileType"` (`profileType_class`, `JSGlobalClasses.cpp:116`) | not registered | unreachable: not in `global_classes` | n/a (never registered) | 5 (static, unreachable) | 0 | – | [out-of-game](out-of-game.md#profiletype-not-registered) |

---

## 8. Class members

For each class: the spec tables with their source ranges, then every member linked to its entry. Methods and constructors link to their own headings. Properties have no per-property headings, so each group links to the table that specifies it. **(w)** marks a writable property.

### Unit

Registered at `JSGlobalClasses.cpp:145`; properties `unit_props` (`JSUnit.h:245-296`); methods `unit_methods` (`JSUnit.h:300-309`).

- **Properties (49):**
  - [common (all unit types)](unit-properties.md#properties-common-all-unit-types): `type`, `classid`, `mode`, `name`, `act`, `gid`, `x`, `y`, `targetx`, `targety`, `area`, `hp`, `hpmax`, `mp`, `mpmax`, `stamina`, `staminamax`, `charlvl`, `itemcount`, `owner`, `ownertype`, `direction`
  - [monster](unit-properties.md#properties-monster): `spectype`, `uniqueid`
  - [item](unit-properties.md#properties-item): `code`, `prefix`, `suffix`, `prefixes`, `suffixes`, `prefixnum`, `suffixnum`, `prefixnums`, `suffixnums`, `fname`, `quality`, `node`, `location`, `sizex`, `sizey`, `itemType`, `description`, `bodylocation`, `ilvl`, `lvlreq`, `gfx`
  - [object](unit-properties.md#properties-object): `objtype`, `islocked`
  - [local-player-bound (runwalk, weaponswitch)](unit-properties.md#properties-local-player-bound-runwalk-weaponswitch): `runwalk`, `weaponswitch`
- **Methods (25):** [`getNext`](unit-methods.md#unitprototypegetnextnameorclassid-mode), [`cancel`](unit-methods.md#unitprototypecancelmode), [`repair`](unit-methods.md#unitprototyperepair), [`useMenu`](unit-methods.md#unitprototypeusemenumenuid), [`interact`](unit-methods.md#unitprototypeinteractdestareaid), [`getItem`](unit-methods.md#unitprototypegetitemnameorclassid-mode-gid), [`getItems`](unit-methods.md#unitprototypegetitems), [`getMerc`](unit-methods.md#unitprototypegetmerc), [`getMercHP`](unit-methods.md#unitprototypegetmerchp), [`getSkill`](unit-methods.md#unitprototypegetskillselectororskillid-btotal-chargedonly), [`getParent`](unit-methods.md#unitprototypegetparent), [`overhead`](unit-methods.md#unitprototypeoverheadmessage), [`revive`](unit-methods.md#unitprototyperevive), [`getFlags`](unit-methods.md#unitprototypegetflags), [`getFlag`](unit-methods.md#unitprototypegetflagmask), [`getStat`](unit-methods.md#unitprototypegetstatstat-subindex), [`getState`](unit-methods.md#unitprototypegetstatestate), [`getEnchant`](unit-methods.md#unitprototypegetenchantenchant), [`shop`](unit-methods.md#unitprototypeshopmode), [`setSkill`](unit-methods.md#unitprototypesetskillskill-hand-item), [`move`](unit-methods.md#unitprototypemovex-y), [`getQuest`](unit-methods.md#unitprototypegetquestact-quest), [`getMinionCount`](unit-methods.md#unitprototypegetminioncounttype), [`getRepairCost`](unit-methods.md#unitprototypegetrepaircostnpcclassid), [`getItemCost`](unit-methods.md#unitprototypegetitemcostmode-npc-difficulty)

### PresetUnit

Registered at `JSGlobalClasses.cpp:146`; properties `presetunit_props` (`JSPresetUnit.h:25-31`).

- **Properties (7):**
  - [table](world.md#presetunit-properties): `type`, `roomx`, `roomy`, `x`, `y`, `id`, `level`

### Area

Registered at `JSGlobalClasses.cpp:147`; properties `area_props` (`JSArea.h:17-23`).

- **Properties (7):**
  - [table](world.md#area-properties): `exits`, `name`, `x`, `xsize`, `y`, `ysize`, `id`

### Control

Registered at `JSGlobalClasses.cpp:148`; properties `control_props` (`JSControl.h:49-62`); methods `control_funcs` (`JSControl.h:65-66`).

- **Properties (12, 3 writable):**
  - [table](out-of-game.md#control): `text` (w), `x`, `y`, `xsize`, `ysize`, `state` (w), `password`, `type`, `cursorpos` (w), `selectstart`, `selectend`, `disabled`
- **Methods (4):** [`getNext`](out-of-game.md#controlprototypegetnext), [`click`](out-of-game.md#controlprototypeclickx-y), [`setText`](out-of-game.md#controlprototypesettexttext), [`getText`](out-of-game.md#controlprototypegettext)

### Folder

Registered at `JSGlobalClasses.cpp:149`; properties `dir_props` (`JSDirectory.h:28`); methods `dir_methods` (`JSDirectory.h:31-32`).

- **Properties (1):**
  - [table](utility-classes.md#folder-properties): `name`
- **Methods (4):** [`create`](utility-classes.md#folderprototypecreatename), [`remove`](utility-classes.md#folderprototyperemove), [`getFiles`](utility-classes.md#folderprototypegetfilespattern), [`getFolders`](utility-classes.md#folderprototypegetfolderspattern)

### Exit

Registered at `JSGlobalClasses.cpp:150`; properties `exit_props` (`JSExits.h:14-19`).

- **Properties (6):**
  - [table](world.md#exit-properties): `x`, `y`, `target`, `type`, `tileid`, `level`

### Party

Registered at `JSGlobalClasses.cpp:151`; properties `party_props` (`JSParty.h:15-24`); methods `party_methods` (`JSParty.h:27`).

- **Properties (10):**
  - [table](world.md#party-properties): `x`, `y`, `area`, `gid`, `life`, `partyflag`, `partyid`, `name`, `classid`, `level`
- **Methods (1):** [`getNext`](world.md#partyprototypegetnext)

### Room

Registered at `JSGlobalClasses.cpp:152`; properties `room_props` (`JSRoom.h:36-44`); methods `room_methods` (`JSRoom.h:47-55`).

- **Properties (9):**
  - [table](world.md#room-properties): `number`, `x`, `y`, `xsize`, `ysize`, `subnumber`, `area`, `level`, `correcttomb`
- **Methods (9):** [`getNext`](world.md#roomprototypegetnext), [`reveal`](world.md#roomprototyperevealdrawpresets), [`getPresetUnits`](world.md#roomprototypegetpresetunitstype-classid), [`getCollision`](world.md#roomprototypegetcollision), [`getCollisionA`](world.md#roomprototypegetcollisiona), [`getNearby`](world.md#roomprototypegetnearby), [`getStat`](world.md#roomprototypegetstatn), [`getFirst`](world.md#roomprototypegetfirst), [`unitInRoom`](world.md#roomprototypeunitinroomunit)

### File

Registered at `JSGlobalClasses.cpp:154`; properties `file_props` (`JSFile.h:98-110`); methods `file_methods` (`JSFile.h:50-60`); static methods `file_s_methods` (`JSFile.h:63`).

- **Properties (13, 1 writable):**
  - [table](utility-classes.md#file-properties): `readable`, `writeable`, `seekable`, `mode`, `binaryMode`, `length`, `path`, `position`, `eof`, `accessed`, `created`, `modified`, `autoflush` (w)
- **Methods (11):** [`close`](utility-classes.md#fileprototypeclose), [`reopen`](utility-classes.md#fileprototypereopen), [`read`](utility-classes.md#fileprototypereadcount), [`readLine`](utility-classes.md#fileprototypereadline), [`readAllLines`](utility-classes.md#fileprototypereadalllines), [`readAll`](utility-classes.md#fileprototypereadall), [`write`](utility-classes.md#fileprototypewritevalues), [`seek`](utility-classes.md#fileprototypeseekn-islines-fromstart), [`flush`](utility-classes.md#fileprototypeflush), [`reset`](utility-classes.md#fileprototypereset), [`end`](utility-classes.md#fileprototypeend)
- **Static methods (1):** [`open`](utility-classes.md#fileopenpath-mode-binary-autoflush-lockfile)

### Socket

Registered at `JSGlobalClasses.cpp:155`; properties `socket_props` (`JSSocket.h:30-31`); methods `socket_methods` (`JSSocket.h:25-26`); static methods `socket_s_methods` (`JSSocket.h:28`).

- **Properties (2):**
  - [table](utility-classes.md#socket-properties): `readable`, `writeable`
- **Methods (3):** [`close`](utility-classes.md#socketprototypeclose), [`send`](utility-classes.md#socketprototypesendtext), [`read`](utility-classes.md#socketprototyperead)
- **Static methods (1):** [`open`](utility-classes.md#socketopenhost-port)

### FileTools

Registered at `JSGlobalClasses.cpp:156`; static methods `filetools_s_methods` (`JSFileTools.h:32-38`).

- **Static methods (7):** [`remove`](utility-classes.md#filetoolsremovepath), [`rename`](utility-classes.md#filetoolsrenameoldpath-newpath), [`copy`](utility-classes.md#filetoolscopysrcpath-dstpath-overwrite), [`exists`](utility-classes.md#filetoolsexistspath), [`readText`](utility-classes.md#filetoolsreadtextpath), [`writeText`](utility-classes.md#filetoolswritetextpath-values), [`appendText`](utility-classes.md#filetoolsappendtextpath-values)

### SQLite

Registered at `JSGlobalClasses.cpp:157`; properties `sqlite_props` (`JSSQLite.h:42-46`); methods `sqlite_methods` (`JSSQLite.h:39-40`).

- **Constructor:** [`SQLite([path[, autoOpen]])`](utility-classes.md#sqlitepath-autoopen)
- **Properties (5):**
  - [table](utility-classes.md#sqlite-properties): `path`, `statements`, `isOpen`, `lastRowId`, `changes`
- **Methods (4):** [`execute`](utility-classes.md#sqliteprototypeexecutesql), [`query`](utility-classes.md#sqliteprototypequerysql-binds), [`open`](utility-classes.md#sqliteprototypeopen), [`close`](utility-classes.md#sqliteprototypeclose)

### DBStatement

Registered at `JSGlobalClasses.cpp:158`; properties `sqlite_stmt_props` (`JSSQLite.h:61-62`); methods `sqlite_stmt_methods` (`JSSQLite.h:49-58`).

- **Properties (2):**
  - [table](utility-classes.md#dbstatement-properties): `sql`, `ready`
- **Methods (10):** [`getObject`](utility-classes.md#dbstatementprototypegetobject), [`getColumnCount`](utility-classes.md#dbstatementprototypegetcolumncount), [`getColumnValue`](utility-classes.md#dbstatementprototypegetcolumnvalueindex), [`getColumnName`](utility-classes.md#dbstatementprototypegetcolumnnameindex), [`go`](utility-classes.md#dbstatementprototypego), [`next`](utility-classes.md#dbstatementprototypenext), [`skip`](utility-classes.md#dbstatementprototypeskipn), [`reset`](utility-classes.md#dbstatementprototypereset), [`close`](utility-classes.md#dbstatementprototypeclose), [`bind`](utility-classes.md#dbstatementprototypebindparam-value)

### Sandbox

Registered at `JSGlobalClasses.cpp:159`; methods `sandbox_methods` (`JSSandbox.h:26-27`).

- **Constructor:** [`Sandbox()`](utility-classes.md#sandbox-1)
- **Methods (4):** [`evaluate`](utility-classes.md#sandboxprototypeevaluatecode), [`include`](utility-classes.md#sandboxprototypeincludefile), [`isIncluded`](utility-classes.md#sandboxprototypeisincludedfile), [`clearScope`](utility-classes.md#sandboxprototypeclearscope)

### D2BSScript

Registered at `JSGlobalClasses.cpp:160`; properties `script_props` (`JSScript.h:29-33`); methods `script_methods` (`JSScript.h:36-41`).

- **Properties (5):**
  - [table](utility-classes.md#d2bsscript-properties): `name`, `type`, `running`, `threadid`, `memory`
- **Methods (6):** [`getNext`](utility-classes.md#d2bsscriptprototypegetnext), [`pause`](utility-classes.md#d2bsscriptprototypepause), [`resume`](utility-classes.md#d2bsscriptprototyperesume), [`stop`](utility-classes.md#d2bsscriptprototypestop), [`join`](utility-classes.md#d2bsscriptprototypejoin), [`send`](utility-classes.md#d2bsscriptprototypesendvalues)

### Frame

Registered at `JSGlobalClasses.cpp:162`; properties `frame_props` (`JSScreenHook.h:18-26`); methods `frame_methods` (`JSScreenHook.h:29`).

- **Constructor:** [`new Frame(x, y, xsize, ysize, align, automap, click, hover)`](screenhooks.md#new-framex-y-xsize-ysize-align-automap-click-hover)
- **Properties (9, 9 writable):**
  - [table](screenhooks.md#properties): `x` (w), `y` (w), `xsize` (w), `ysize` (w), `visible` (w), `align` (w), `zorder` (w), `click` (w), `hover` (w)
- **Methods (1):** [`remove`](screenhooks.md#frameprototyperemove)

### Box

Registered at `JSGlobalClasses.cpp:163`; properties `box_props` (`JSScreenHook.h:40-50`); methods `box_methods` (`JSScreenHook.h:53`).

- **Constructor:** [`new Box(x, y, xsize, ysize, color, opacity, align, automap, click, hover)`](screenhooks.md#new-boxx-y-xsize-ysize-color-opacity-align-automap-click-hover)
- **Properties (11, 11 writable):**
  - [table](screenhooks.md#properties-1): `x` (w), `y` (w), `xsize` (w), `ysize` (w), `visible` (w), `color` (w), `opacity` (w), `align` (w), `zorder` (w), `click` (w), `hover` (w)
- **Methods (1):** [`remove`](screenhooks.md#boxprototyperemove)

### Line

Registered at `JSGlobalClasses.cpp:164`; properties `line_props` (`JSScreenHook.h:64-72`); methods `line_methods` (`JSScreenHook.h:75`).

- **Constructor:** [`new Line(x, y, x2, y2, color, automap, click, hover)`](screenhooks.md#new-linex-y-x2-y2-color-automap-click-hover)
- **Properties (9, 9 writable):**
  - [table](screenhooks.md#properties-2): `x` (w), `y` (w), `x2` (w), `y2` (w), `visible` (w), `color` (w), `zorder` (w), `click` (w), `hover` (w)
- **Methods (1):** [`remove`](screenhooks.md#lineprototyperemove)

### Text

Registered at `JSGlobalClasses.cpp:165`; properties `text_props` (`JSScreenHook.h:86-95`); methods `text_methods` (`JSScreenHook.h:98`).

- **Constructor:** [`new Text(text, x, y, color, font, align, automap, click, hover)`](screenhooks.md#new-texttext-x-y-color-font-align-automap-click-hover)
- **Properties (10, 10 writable):**
  - [table](screenhooks.md#properties-3): `x` (w), `y` (w), `color` (w), `font` (w), `visible` (w), `text` (w), `align` (w), `zorder` (w), `click` (w), `hover` (w)
- **Methods (1):** [`remove`](screenhooks.md#textprototyperemove)

### Image

Registered at `JSGlobalClasses.cpp:166`; properties `image_props` (`JSScreenHook.h:109-116`); methods `image_methods` (`JSScreenHook.h:119`).

- **Constructor:** [`new Image(path, x, y, color, align, automap, click, hover)`](screenhooks.md#new-imagepath-x-y-color-align-automap-click-hover)
- **Properties (8, 8 writable):**
  - [table](screenhooks.md#properties-4): `x` (w), `y` (w), `visible` (w), `location` (w), `align` (w), `zorder` (w), `click` (w), `hover` (w)
- **Methods (1):** [`remove`](screenhooks.md#imageprototyperemove)

### Profile

Registered at `JSGlobalClasses.cpp:167`; properties `profile_props` (`JSProfile.h:31-38`); methods `profile_methods` (`JSProfile.h:41`).

- **Constructor:** [`Profile(...args)`](out-of-game.md#profileargs)
- **Properties (8):**
  - [table](out-of-game.md#profile): `type`, `ip`, `username`, `gateway`, `character`, `difficulty`, `maxLoginTime`, `maxCharacterSelectTime`
- **Methods (1):** [`login`](out-of-game.md#profileprototypelogin)

### DailogLine

Not in `global_classes`; `getDialogLines` builds each element with `BuildObject(cx, &dialogLine_class, 0, 0, 0, 0)` and then sets own members on it (`JSGame.cpp:191-201`). The class name is misspelt in the source (`JSGlobalClasses.cpp:121`).

- **Own data properties (2):** [`text`, `selectable`](globals-game.md#dailogline) (`JSGame.cpp:192-193`)
- **Own function (1):** [`handler`](globals-game.md#dailoglineprototypehandler) (`my_clickDialog`, `JSGame.cpp:195`, defined `JSGame.cpp:213`)

### ProfileType

Defined (`JSGlobalClasses.cpp:116`) with static properties `profileType_props` (`JSProfile.h:47-51`), but absent from the active `global_classes` table (`JSGlobalClasses.cpp:143-170`); only the obsolete commented-out table mentions it (`JSGlobalClasses.cpp:184`). Scripts cannot reach it.

- **Static properties (5, unreachable):** [`singlePlayer`, `battleNet`, `openBattleNet`, `tcpIpHost`, `tcpIpJoin`](out-of-game.md#profiletype-not-registered)

---

## 9. The `me` object

`me` is not a class. It is one `Unit` instance per script, built with `me_props` instead of `unit_props` (`ScriptEngine.cpp:361`) and defined read-only on the global (`ScriptEngine.cpp:365`). Its handle is `(player gid, UNIT_PLAYER)`. The gid is taken when the context is created and refreshed on each game entry. Full treatment: [unit-properties.md](unit-properties.md#the-global-me), in particular [Tracking the player across games](unit-properties.md#tracking-the-player-across-games).

- **Properties:** 80 in `me_props` (`JSUnit.h:160-242`), 10 of them writable: `automap`, `runwalk`, `chickenhp`, `chickenmp`, `quitonhostile`, `blockKeys`, `blockMouse`, `nopickup`, `quitonerror`, `maxgametime`. Setter semantics: [Settable properties](unit-properties.md#settable-properties-setter-semantics).
  - [me-only, any client state](unit-properties.md#me-only-properties-any-client-state) (34): `account`, `charname`, `diff`, `maxdiff`, `gamename`, `gamepassword`, `gameserverip`, `gamestarttime`, `gametype`, `itemoncursor`, `automap` (w), `ladder`, `ping`, `fps`, `locale`, `playertype`, `realm`, `realmshort`, `mercrevivecost`, `chickenhp` (w), `chickenmp` (w), `quitonhostile` (w), `blockKeys` (w), `blockMouse` (w), `gameReady`, `profile`, `pid`, `unsupported`, `charflags`, `screensize`, `windowtitle`, `ingame`, `quitonerror` (w), `maxgametime` (w)
  - [me-only, in game only](unit-properties.md#me-only-properties-in-game-only) (2): `nopickup` (w), `mapid`
  - Shared with `unit_props`, same getter (44), specified in the [Unit property tables](#unit): `runwalk` (w), `weaponswitch`, `type`, `classid`, `mode`, `name`, `act`, `gid`, `x`, `y`, `targetx`, `targety`, `area`, `hp`, `hpmax`, `mp`, `mpmax`, `stamina`, `staminamax`, `charlvl`, `itemcount`, `owner`, `ownertype`, `spectype`, `direction`, `code`, `prefix`, `suffix`, `prefixes`, `suffixes`, `prefixnum`, `suffixnum`, `prefixnums`, `suffixnums`, `fname`, `quality`, `node`, `location`, `sizex`, `sizey`, `itemType`, `description`, `bodylocation`, `ilvl`
  - In `unit_props` but not an own property of `me`: `uniqueid`, `lvlreq`, `gfx`, `objtype`, `islocked`. See [Property set](unit-properties.md#property-set-me_props-vs-unit_props) for what reading them through `Unit.prototype` does.
- **Methods:** the 25 `Unit` methods ([§8 Unit](#unit)), defined on `me` itself by `BuildObject`.

---

## 10. Global constants

`ScriptEngine::DefineConstant` (`ScriptEngine.cpp:236-239`) defines each constant with `JSPROP_PERMANENT_VAR`, and it is called only for these three (`ScriptEngine.cpp:368-371`). There are no JS constants for UI flags, OOG location codes, control types or profile types; scripts pass the numbers. The tables for those numbers are in [globals-game.md](globals-game.md#code-tables) and [out-of-game.md](out-of-game.md#oog-location-codes).

| Name | Value | Value from | Used by |
|---|---|---|---|
| `FILE_READ` | 0 | `JSFile.h:67` | `File.open` mode ([utility-classes.md](utility-classes.md#fileopenpath-mode-binary-autoflush-lockfile)) |
| `FILE_WRITE` | 1 | `JSFile.h:68` | same |
| `FILE_APPEND` | 2 | `JSFile.h:69` | same |

Details: [../spidermonkey/embedding.md](../spidermonkey/embedding.md#35-every-constant).

---

## 11. Events

These are the names a listener can be registered under with [`addEventListener`](globals-core.md#addeventlistenername-listener), plus the two screen-hook callbacks, which use the same per-script queue. "Blocking" means the producer waits for the listeners' verdict, with a timeout. "Inline" means the listener runs on the producer's own thread when that is the listening script. Threads, timeouts and return effects are in the [summary table](events.md#1-summary-table).

| Event name | Group | Listener args | Delivery |
|---|---|---|---|
| [`keydown`](events.md#keydown) | Input | `vk` | queued |
| [`keyup`](events.md#keyup) | Input | `vk` | queued |
| [`keydownblocker`](events.md#keydownblocker) | Input | `vk` | blocking (`true` swallows the key) |
| [`keyupblocker`](events.md#keyupblocker) | Input | `vk` | **broken**: never dispatched |
| [`mouseclick`](events.md#mouseclick) | Input | `button, x, y, up` | queued |
| [`mousemove`](events.md#mousemove) | Input | `x, y` | queued |
| [`chatmsg`](events.md#chatmsg) | Chat | `nick, msg` | queued |
| [`chatmsgblocker`](events.md#chatmsgblocker) | Chat | `nick, msg` | blocking |
| [`chatinput`](events.md#chatinput) | Chat | `"me", msg` | queued |
| [`chatinputblocker`](events.md#chatinputblocker) | Chat | `"me", msg` | blocking |
| [`whispermsg`](events.md#whispermsg) | Chat | `nick, msg` | queued |
| [`whispermsgblocker`](events.md#whispermsgblocker) | Chat | `nick, msg` | blocking, verdict ignored |
| [`gamepacket`](events.md#gamepacket) | Packets | `Uint8Array` | blocking / inline |
| [`gamepacketsent`](events.md#gamepacketsent) | Packets | `Uint8Array` | blocking / inline |
| [`realmpacket`](events.md#realmpacket) | Packets | `Uint8Array` | blocking / inline |
| [`melife`](events.md#melife) | Game state | `life` | queued |
| [`memana`](events.md#memana) | Game state | `mana` | queued |
| [`itemaction`](events.md#itemaction) | Game state | `gid, mode, code, global` | queued |
| [`gameevent`](events.md#gameevent) | Game state | `mode, param1, param2, name1, name2` | queued |
| [`playerassign`](events.md#playerassign) | Game state | `unitId` | queued |
| [`copydata`](events.md#copydata) | IPC | `mode, msg` | queued |
| [`scriptmsg`](events.md#scriptmsg) | IPC | `...values` | queued |
| [`ScreenHookClick`](events.md#screenhookclick-hook-click-handler) | Screen-hook callback (hook `click` property) | `button, x, y` | blocking (`true` swallows the click) |
| [`ScreenHookHover`](events.md#screenhookhover-hook-hover-handler) | Screen-hook callback (hook `hover` property) | `x, y` | **dead code**: never produced |

Event names are case-sensitive. A listener under any other name is accepted and never fires. Names with special meaning are listed in [events.md §9](events.md#9-reserved-internal-and-phantom-names): `setTimeout`/`setInterval` (shared with timers), `Command` and `DisposeMe` (internal), and the phantom or misspelt legacy names `golddrop`, `gamemsg`, `keydownblock` and `keyupblock`.

---

## 12. Not registered, commented out, or legacy-only names

| Name | Status | Source | Doc |
|---|---|---|---|
| `createCharacter` | `JS_FN` line commented out ("this function is not finished"); native still compiled | `JSGlobalFuncs.h:55-56`, `JSMenu.cpp:165` | [out-of-game.md](out-of-game.md#createcharactername-classid-hardcore-ladder) |
| `ProfileType` | class and static properties defined, never registered | `JSGlobalClasses.cpp:116-118`, `JSProfile.h:47-51`, commented-out row `JSGlobalClasses.cpp:184` | [out-of-game.md](out-of-game.md#profiletype-not-registered) |
| `DailogLine` | class defined but not in `global_classes`; no global constructor; instances only from `getDialogLines` | `JSGlobalClasses.cpp:120-122`, `JSGame.cpp:191` | [globals-game.md](globals-game.md#dailogline) |
| `Unit.prototype.geSPrice` / `getPrice` | commented-out method row | `JSUnit.h:306` | [unit-methods.md](unit-methods.md#method-summary) |
| `Control` `maxlength`, `visible` | commented-out property rows; their getter cases are empty (`JSControl.cpp:68-70`, `JSControl.cpp:74-76`) | `JSControl.h:56`, `JSControl.h:58` | [out-of-game.md](out-of-game.md#control) |
| `Pipe` | class and spec commented out | `JSGlobalClasses.cpp:26-30` | – |
| `Sandbox.prototype.isInclude` | legacy name; the code registers `isIncluded` | `doc/Sandbox.h:32`, `README.md:4662`; code `JSSandbox.h:26-27` | [utility-classes.md](utility-classes.md#sandboxprototypeisincludedfile) |
| `keydownblock`, `keyupblock`, `golddrop`, `gamemsg` | legacy or phantom event names | see events.md | [events.md §9](events.md#9-reserved-internal-and-phantom-names) |
| `iniread`, `iniwrite`, `blockMinimize`, `getTextWidthHeight`, `profileExists` | listed in `resources/api.html`, not registered | `resources/api.html:713-784` | [globals-core.md](globals-core.md#legacy-doc-discrepancies) |

---

## 13. Related documentation

- [../architecture.md](../architecture.md): process, threads, hooks, `Vars`, locks, `d2bs.ini`, external control surfaces.
- [../rpc-considerations.md](../rpc-considerations.md): facts for the RPC replacement, including an API census by category, state, blocking, game-memory access and lock ([§1.3](../rpc-considerations.md#13-global-functions-108-names), [§1.4](../rpc-considerations.md#14-classes)).
- [../spidermonkey/embedding.md](../spidermonkey/embedding.md): runtime/context topology, binding macros, script lifecycle, event and timer integration.
- [../spidermonkey/jsapi-inventory.md](../spidermonkey/jsapi-inventory.md): mechanical JSAPI coupling inventory, including every native ([§5.1](../spidermonkey/jsapi-inventory.md#51-native-inventory-generated)).
- [../memory/README.md](../memory/README.md), [../memory/offsets.md](../memory/offsets.md), [../memory/structs.md](../memory/structs.md), [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md), [../memory/call-stubs.md](../memory/call-stubs.md): the Game.exe addresses, structs, patches and call stubs that the **Game internals** bullets name.
- [../ghidra/README.md](../ghidra/README.md): importing the D2BS symbols and types into Ghidra.

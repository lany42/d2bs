# Out-of-game API: menu globals, `Control`, `Profile`

Scope: the JS surface that drives the Diablo II menus ("out of game", OOG). It includes the six registered globals in `JSMenu.cpp` (`login`, `selectCharacter`, `createGame`, `joinGame`, `addProfile`, `getLocation`) and the unregistered `createCharacter`. It also covers the `Control` class with `getControl`/`getControls` (`JSControl.cpp/.h`), the `Profile` class and the unregistered `ProfileType` (`JSProfile.cpp/.h`), and the C++ layer they call: `Control.cpp/.h` (`findControl`, `clickControl`, `SetControlText`, `OOG_*`) and `Profile.cpp/.h` (`Profile::init`, `ProfileExists`, `Profile::login`). Every statement is taken from the C++ in this repo. Citations are `File:line`. JSNative conventions (argument slots past `argc`, "unset" return values, error mechanics) are defined once in [globals-core.md § Conventions](globals-core.md#conventions-shared-by-all-entries) and [../spidermonkey/embedding.md § 4.3](../spidermonkey/embedding.md#43-how-natives-receive-arguments-return-values-and-report-errors). This page uses the same markers.

## Contents

- [Quick reference](#quick-reference)
- [Conventions specific to this page](#conventions-specific-to-this-page)
- [Menu globals](#menu-globals)
  - [`login`](#loginprofile) · [`selectCharacter`](#selectcharacterprofile) · [`createGame`](#creategamename-password-difficulty) · [`joinGame`](#joingamename-password) · [`addProfile`](#addprofileprofile-mode-gateway-username-password-character-spdifficulty) · [`getLocation`](#getlocation) · [`createCharacter` (not exposed)](#createcharactername-classid-hardcore-ladder)
- [OOG location codes](#oog-location-codes): value → meaning → detection probe
- [The login state machine](#the-login-state-machine)
- [Profile storage (`d2bs.ini`)](#profile-storage-d2bsini)
- [Profile](#profile) class · [ProfileType (not registered)](#profiletype-not-registered)
- [Control](#control) class: [`getControl`](#getcontroltype-x-y-xsize-ysize), [`getControls`](#getcontrols), properties, methods
- [Internals](#internals): client-state gate, `findControl`, `clickControl`, text entry, `OOG_SelectCharacter`, `OOG_SelectGateway`, `OOG_CreateGame`, `OOG_JoinGame`, `OOG_CreateCharacter`, hard-coded geometry
- [Game internals touched](#game-internals-touched)
- [Facts for an RPC replacement](#facts-for-an-rpc-replacement)
- [Defects and quirks](#defects-and-quirks)
- [Legacy-doc discrepancies](#legacy-doc-discrepancies)
- [Open questions](#open-questions)

Related: [globals-core.md](globals-core.md) (`sendClick`, `loadMpq`, which is registered in the "out of game" group at `JSGlobalFuncs.h:58` but implemented in `JSCore.cpp:558`), [unit-properties.md](unit-properties.md) (`me.profile`, `me.blockKeys`, `me.blockMouse`), [events.md](events.md), [../architecture.md](../architecture.md) (threads, `Vars`, `d2bs.ini` `[settings]`, `-profile`, `WM_COPYDATA`/DDE profile switching), [../memory/offsets.md](../memory/offsets.md), [../memory/structs.md](../memory/structs.md), [../rpc-considerations.md](../rpc-considerations.md).

---

## Quick reference

| JS name | Native | Defined | Registered | Arity | Returns | Blocking |
|---|---|---|---|---|---|---|
| `login` | `my_login` | `JSMenu.cpp:10` | `JSGlobalFuncs.h:54` | 1 | `undefined` or throws | until done, error or timeout; can loop forever |
| `selectCharacter` | `my_selectChar` | `JSMenu.cpp:43` | `JSGlobalFuncs.h:57` | 1 | boolean | ≤ 600 ms (600 ms on success) |
| `createGame` | `my_createGame` | `JSMenu.cpp:61` | `JSGlobalFuncs.h:57` | 3 | `null` or throws | up to ≈ 1.2 s |
| `joinGame` | `my_joinGame` | `JSMenu.cpp:88` | `JSGlobalFuncs.h:57` | 2 | `null` or throws | up to ≈ 0.7 s |
| `addProfile` | `my_addProfile` | `JSMenu.cpp:112` | `JSGlobalFuncs.h:58` | 6 | `null` or throws | INI file I/O |
| `getLocation` | `my_getOOGLocation` | `JSMenu.cpp:155` | `JSGlobalFuncs.h:58` | 0 | integer or `null` | no |
| `createCharacter` | `my_createCharacter` | `JSMenu.cpp:165` | **commented out** `JSGlobalFuncs.h:55` | – | not exposed | – |
| `getControl` | `my_getControl` | `JSControl.cpp:292` | `JSGlobalFuncs.h:34` | 0 | `Control` or `undefined` | no |
| `getControls` | `my_getControls` | `JSControl.cpp:325` | `JSGlobalFuncs.h:35` | 0 | `Control[]` or `undefined` | no |
| `Control.prototype.getNext` | `control_getNext` | `JSControl.cpp:154` | `JSControl.h:65` | 0 | `this` (rebound), `false`, or unset | no |
| `Control.prototype.click` | `control_click` | `JSControl.cpp:188` | `JSControl.h:65` | 0 | unset, or `0` | 300 ms |
| `Control.prototype.setText` | `control_setText` | `JSControl.cpp:216` | `JSControl.h:66` | 1 | unset, or `0` | no |
| `Control.prototype.getText` | `control_getText` | `JSControl.cpp:241` | `JSControl.h:66` | 0 | array, `undefined`, or `0` | no |
| `Profile(...)` | `profile_ctor` | `JSProfile.cpp:16` | `JSGlobalClasses.cpp:167` | 0 | `Profile` or throws | INI file I/O |
| `Profile.prototype.login` | `profile_login` | `JSProfile.cpp:92` | `JSProfile.h:41` | 0 | `undefined` or throws | like `login` |

`ProfileType` is defined (`JSGlobalClasses.cpp:116`) but has no entry in the active `global_classes[]` table (`JSGlobalClasses.cpp:143-170`); only the obsolete, fully commented-out table below it mentions it (`JSGlobalClasses.cpp:184`). It is therefore **not** a JS global. See [ProfileType](#profiletype-not-registered).

`my_getControl`/`my_getControls` are declared in `JSMenu.h:7-8` but defined in `JSControl.cpp`. No named constants exist for location codes, control types or profile types: the only constants `contextCallback` defines are `FILE_READ`/`FILE_WRITE`/`FILE_APPEND` (`ScriptEngine.cpp:369-371`), so scripts pass and compare raw integers.

## Conventions specific to this page

- **Menu gate.** Almost everything checks `ClientState() == ClientStateMenu` (`D2Helpers.cpp:125`). "Menu" means `D2CLIENT_GetPlayerUnit()` is NULL and `*p_D2WIN_FirstControl` is non-NULL (`D2Helpers.cpp:141-142`). If both are non-NULL the state is `ClientStateNull` (`D2Helpers.cpp:126`, no branch matches), so menu functions also refuse in that case. The global natives return early **silently** when not at the menu. `Control` property getters/setters instead return `JS_FALSE` with no exception, which [terminates the running JS uncatchably](globals-core.md#errors).
- **Thread.** Every native here runs on the calling script's own thread (`Script.cpp:108`). Each script has its own runtime (`Script.cpp:120`). No native in this page takes any lock. None of `Control.cpp`, `Profile.cpp`, `JSControl.cpp`, `JSMenu.cpp` or `JSProfile.cpp` references a critical section. They read and write the game's D2WIN control list and `Control` structs while the game's main thread may be rebuilding them.
- **Clicks are posted window messages**, not D2WIN calls: `clickControl` → `SendMouseClick` → `PostMessage(D2GFX_GetHwnd(), WM_LBUTTONDOWN/UP, 0, x | y<<16)` (`Control.cpp:113`, `D2Helpers.cpp:305-313`). The game thread processes them later. **Text entry is a direct game call**: `D2WIN_SetControlText(Control*, const wchar_t*)` (`D2Ptrs.h:436`, VA `0x4FF5A0`) is called on the script thread. See [Internals](#internals).
- **Probe notation** used in tables: `B(id, x, y, w, h)` = `findControl(CONTROL_BUTTON, id, -1, x, y, w, h)`, a button (type 6) whose `wText2` equals `D2LANG_GetLocaleText(id)` exactly. `T(id, …)` = textbox (type 4) whose *first row* is a substring of the locale text. `E(…)` = edit box (type 1). `*` in the id slot = no text criterion. `B0(...)` = additionally `dwDisabled == 0` **and** `unkState != 1` (the button-greyed test, `Control.cpp:41-46`). Geometry is `dwPosX, dwPosY, dwSizeX, dwSizeY`. `-1` = wildcard (any negative value acts as a wildcard inside `findControl`, `Control.cpp:34-78`).
- **(unset)** = the native returns `JS_TRUE` without `JS_SET_RVAL`. The value is unspecified and most likely the callee function object ([globals-core.md § Return values](globals-core.md#return-values)).
- **argc unchecked** = the native reads `JS_ARGV[i]` with `i >= argc` ([globals-core.md § Reading arguments past argc](globals-core.md#reading-arguments-past-argc)).

---

## Menu globals

### `login([profile])`

Drives the menu UI from the current screen to a Battle.net/Open lobby, or into a game for single player and TCP/IP, using a `d2bs.ini` profile.

- **Native:** `my_login` at `JSMenu.cpp:10`; registered at `JSGlobalFuncs.h:54` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `login(name)`: if `JSVAL_IS_STRING(argv[0])` (`JSMenu.cpp:18`), the native takes `JS_GetStringCharsZ` (`:24`) and **immediately copies it into `Vars.szProfile`** with `wcscpy_s(Vars.szProfile, 256, …)` (`:25`), before any validation.
  - `login()` or any non-string first argument (numbers and objects are not coerced): uses `Vars.szProfile` (`:19-20`). The guard `Vars.szProfile != NULL` tests an array (`wchar_t szProfile[256]`, `D2BS.h:84`) and is always true. "Invalid profile specified!" (`:22`) is therefore unreachable. An empty `szProfile` fails with "Profile does not exist!". argc unchecked for `argv[0]`.
  - Throws "Could not get profile!" if the string chars are NULL (`:28-29`). Throws "Profile does not exist!" if `Profile::ProfileExists(name)` is false (`:30-31`). That check is a case-insensitive match against all section names of `d2bs.ini`, `Profile.cpp:59`.
  - Then `new Profile(name)` (`:33`) and `prof->login(&error)` (`:34`). A non-zero result throws `error` via `THROW_ERROR` (`:35-36`). See [the login state machine](#the-login-state-machine) for every message.
- **Returns:** `undefined` (`:11`) on success, and also when not at the menu. Otherwise it throws.
- **Preconditions:** `ClientState() == ClientStateMenu` (`:12-13`), else immediate `undefined`. Any starting screen is accepted. Unknown screens fail with "Unhandled login location".
- **Threading & blocking:** Runs on the script thread and blocks inside `Profile::login` (`Profile.cpp:97`). Each loop iteration sleeps 100 ms (`Profile.cpp:291`). Each `clickControl` adds 300 ms (`Control.cpp:123-127`). The timeout counts only some states, and several states spin forever ([details](#the-login-state-machine)). No JS runs during the call: listeners for this script are not serviced. The operation callback cannot interrupt a native, and `Script::Stop` only waits ≤ 500 ms and never kills the thread (`Script.cpp:251-280`), so a stuck `login` cannot be cancelled.
- **Side effects:**
  - `Vars.szProfile` is overwritten. This feeds `me.profile` (`JSUnit.cpp:60-61`), later argument-less `login()` / `new Profile()`, and the log file name `d2bs-<profile>-<date>.log` (`D2Helpers.cpp:41`).
  - `Vars.bBlockKeys = Vars.bBlockMouse = TRUE` for the duration and **FALSE on every normal return** (`Profile.cpp:112`, `:277`, `:283`, `:294`). This blocks physical input and the D2BS key/mouse script events and screen-hook clicks (the hooks return early, `D2Handlers.cpp:223`, `:305`); only Alt+F4 still passes the keyboard hook (`D2Handlers.cpp:220-221`). It also discards any value a script had set through `me.blockKeys` / `me.blockMouse` (setters `JSUnit.cpp:553`, `:557`).
  - Posted clicks, `D2WIN_SetControlText` writes into edit boxes (username, password, IP), and INI reads.
- **Game internals:** `p_D2WIN_FirstControl` (`D2Ptrs.h:462`), `D2WIN_SetControlText` (`D2Ptrs.h:436`), `D2LANG_GetLocaleText` (`D2Ptrs.h:418`), `D2GFX_GetHwnd` (`D2Ptrs.h:382`), `D2CLIENT_GetPlayerUnit` (`D2Ptrs.h:122`). Struct `Control` (`D2Structs.h:132`): `dwType`, `dwDisabled`, `dwPos*`, `dwSize*`, `pNext`, `wText2`, `pFirstText`.
- **Quirks / bugs:**
  - If the profile's `spdifficulty` is outside 0..3, `Profile::init` throws a C++ `const char*` (`Profile.cpp:33-34`). `my_login` has no `try` around `new Profile` (`JSMenu.cpp:33`). The exception would unwind through SpiderMonkey frames; the only `try` on the script thread covers runtime/context setup and compilation, not script execution (`Script.cpp:119-172`; execution is at `:192-194`), and catches only `std::exception`. No D2BS frame catches it, so (unless SpiderMonkey internals do) it reaches the process-wide `SetUnhandledExceptionFilter(ExceptionHandler)` (`D2BS.cpp:93`), which logs registers and returns `EXCEPTION_EXECUTE_HANDLER` (`Helpers.cpp:396-433`): the process terminates. `Profile(...)` does catch it (`JSProfile.cpp:79`).
  - A profile name of 256 or more characters makes `wcscpy_s` invoke the CRT invalid-parameter handler. D2BS installs none (no `_set_invalid_parameter_handler` in the source), so the process terminates.
  - Any INI section counts as a profile, including `[settings]`.

### `selectCharacter(profile)`

Clicks the character named by a profile's `character` key on the character-select screen, then clicks OK.

- **Native:** `my_selectChar` at `JSMenu.cpp:43`; registered at `JSGlobalFuncs.h:57` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** exactly one string. `argc != 1 || !JSVAL_IS_STRING` throws "Invalid parameters specified to selectCharacter" (`:45-46`). The argument is a **profile (INI section) name, not a character name**. If the profile is unknown it throws "Invalid profile specified" (`:50-51`). The `character` key is read with default `"ERROR"` (`:54`).
- **Returns:** boolean from `OOG_SelectCharacter` (`:56`). `true` means the slot click and the OK click were posted. `false` covers no match, no OK button, an empty slot row, or not at the menu. The initial `null` (`:44`) is always overwritten on non-throwing paths.
- **Preconditions:** none in the wrapper. `OOG_SelectCharacter` returns FALSE unless at the menu (`Control.cpp:180-181`). There is **no location check**: it acts on whatever screen has matching controls.
- **Threading & blocking:** script thread; on success two `clickControl` calls = 600 ms of `Sleep`; failure paths return earlier (0 or 300 ms).
- **Side effects:** posted clicks on the matching slot and on `B(*, 627, 572, 128, 35)` (OK). `Vars.szProfile` and profile state are untouched.
- **Game internals:** see [`OOG_SelectCharacter`](#oog_selectcharacter).
- **Quirks / bugs:** `GetPrivateProfileStringW(..., charname, _countof(file), file)` passes the size of `file` (516 wchar) for the 24-wchar `charname` (`JSMenu.cpp:52`, `:54`). A `character` value longer than 23 characters overflows the stack; the Release build has no `/GS` cookie (`<BufferSecurityCheck>false</BufferSecurityCheck>`, `D2BS.vcxproj:143`). Matching is case-insensitive. Only slots currently on screen are searched. The argument is passed through a redundant `JS_ValueToString` (`JSMenu.cpp:48`).

### `createGame(name, [password], [difficulty])`

Creates a Battle.net/Open game from the lobby, chat or create tab. On the single-player difficulty screen it only clicks a difficulty button.

- **Native:** `my_createGame` at `JSMenu.cpp:61`; registered at `JSGlobalFuncs.h:57` (declared arity 3, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `JS_ConvertArguments(cx, argc, argv, "W/Wi", …)` (`:69`): `name` is required and ToString-converted. `password` is optional and ToString-converted. `difficulty` is optional, ECMA int32, default `3` (`:68`). If conversion fails (in practice `argc == 0`) the native reports "Invalid arguments specified to createGame" (`:70`) on top of the engine's own error and returns `JS_FALSE`.
  - The converted `jschar*` outputs are ignored. The native re-reads `JSVAL_TO_STRING(argv[0])` and `argv[1]` (`:73-74`), so a non-string argument only works if the `W` conversion stores the string back into `argv` (see [Open questions](#open-questions)).
  - **`createGame("x")` with one argument:** `argv[1]` is not a string. If padded with `undefined`, `JSVAL_TO_STRING` returns a NULL `JSString*` (the payload of `undefined` is 0, `dependencies/include/js/Value.h:872`) and `JS_GetStringCharsZ(cx, NULL)` dereferences it. Expect a crash. The fallback `if (!pass) pass = L""` (`:76-77`) never gets the chance. Explicit `null`/`undefined` becomes the password `"null"` / `"undefined"` (ToString), given the write-back of [open question 2](#open-questions).
  - `wcslen(name) > 15 || wcslen(pass) > 15` throws "Invalid game name or password length" (`:79-80`). `difficulty` is not range-checked here. A value outside 0..3 makes `OOG_CreateGame` fail, which throws "createGame failed" (`:82-83`), but on the lobby/chat/Create-tab path the tab has already been clicked (lobby/chat only) and the name and password typed before the difficulty `switch` rejects it (`Control.cpp:485-504`, `:534-535`).
- **Returns:** `null` (`:62`) on success and when not at the menu. "Success" means the clicks and text writes were issued. It does not mean the game exists. Poll `getLocation()` or wait for in-game state.
- **Preconditions:** menu (`:63-64`). `OOG_GetLocation()` must be `OOG_LOBBY`(1), `OOG_CHAT`(3), `OOG_DIFFICULTY`(20) or `OOG_CREATE`(4), else the native throws "createGame failed" (`Control.cpp:445-447`).
- **Threading & blocking:** script thread. Sleeps on the success path: from the lobby ≈ 1.2 s (tab click 300 + 100 + 100 + 100 + radio click 300 + Create Game click 300 ms), from `OOG_CREATE` ≈ 0.8 s, from `OOG_DIFFICULTY` 0.3 s or 0 if nothing is clicked (`Control.cpp:489`, `:497`, `:504` + 300 ms per click). It does not wait for the game to react.
- **Side effects:** posted clicks on the Create tab `B(*, 533, 469, 120, 20)`, a difficulty radio and Create Game `B(*, 594, 433, 172, 32)`. `D2WIN_SetControlText` on `E(*, 432, 162, 158, 20)` (name) and `E(*, 432, 217, 158, 20)` (password). See [`OOG_CreateGame`](#oog_creategame).
- **Game internals:** `OOG_CreateGame` (`Control.cpp:434`), `findControl`, `clickControl`, `SetControlText`, `Control.dwDisabled`.
- **Quirks / bugs:** reverse-ordered difficulty logic for `difficulty == 3` on the SP screen. Silent success when the Create tab hasn't opened within the fixed sleep. NULL dereference if the difficulty buttons are missing. See [`OOG_CreateGame`](#oog_creategame).

### `joinGame(name, [password])`

Opens the Join tab if needed, types the game name and password, and clicks Join Game.

- **Native:** `my_joinGame` at `JSMenu.cpp:88`; registered at `JSGlobalFuncs.h:57` (declared arity 2, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `JS_ConvertArguments("W/W")` (`:94`). On failure the error message wrongly says "Invalid arguments specified to **createGame**" (`:95`). Argument handling is identical to `createGame` (`:98-101`), including the expected crash when `password` is omitted. Lengths > 15 throw "Invalid game name or password length" (`:103-104`). If `OOG_JoinGame` fails it throws "joinGame failed" (`:106-107`).
- **Returns:** `null` (`:89`) on success and when not at the menu.
- **Preconditions:** menu (`:90-91`). Location must be `OOG_LOBBY`, `OOG_CHAT` or `OOG_JOIN`, else the native throws "joinGame failed" (`Control.cpp:559-560`).
- **Threading & blocking:** script thread; ≈ 0.7 s from the lobby, 0.3 s from the Join tab.
- **Side effects:** posted clicks on the Join tab `B(*, 652, 469, 120, 20)` and Join Game `B(*, 594, 433, 172, 32)`. Text written into `E(*, 432, 148, 155, 20)` and `E(*, 606, 148, 155, 20)`. See [`OOG_JoinGame`](#oog_joingame).
- **Game internals:** `OOG_JoinGame` (`Control.cpp:548`).
- **Quirks / bugs:** silent success when the Join tab is not open after 100 ms. `OOG_GetLocation()` is evaluated up to three times for one condition (`Control.cpp:559`).

### `addProfile(profile, mode, gateway, username, password, character, [spDifficulty])`

Appends a new profile section to `<D2BS dir>\d2bs.ini` if no section of that name exists.

- **Native:** `my_addProfile` at `JSMenu.cpp:112`; registered at `JSGlobalFuncs.h:58` (declared arity 6, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `argc` must be 6 or 7, else it throws "Invalid arguments passed to addProfile" (`:118-119`).
  - Arguments 0–5 must be strings (`JSVAL_IS_STRING`, no coercion), else it throws "Invalid argument passed to addProfile" (`:122-127`). If `JS_GetStringCharsZ` returns NULL it throws "Failed to convert string" (`:129-132`).
  - The 7th argument goes through `JSVAL_TO_INT` with **no type test** (`:134-135`). A double or a non-number gives a garbage integer. The default is `3` (`:117`). Outside 0..3 it throws "Invalid argument passed to addProfile" (`:137-138`).

  | # | Parameter | Written as key | Used by |
  |---|---|---|---|
  | 0 | `profile` | section name `[profile]` | `ProfileExists`, `login`, `Profile(name)`, `selectCharacter`, `SwitchToProfile` |
  | 1 | `mode` | `mode=` | first character → profile type (`Profile.cpp:40-56`). Not validated. |
  | 2 | `gateway` | `gateway=` | `OOG_SelectGateway` (substring match) |
  | 3 | `username` | `username=` | Battle.net account, **or the host IP for TCP/IP join** (union, `Profile.h:11-14`) |
  | 4 | `password` | `password=` | stored in plaintext |
  | 5 | `character` | `character=` | `OOG_SelectCharacter` |
  | 6 | `spDifficulty` | `spdifficulty=` (`%d`) | SP / TCP-host difficulty button. Written as `3` when omitted, whereas a section without the key reads back as `0` (`Profile.cpp:20`). |
- **Returns:** `null` (`:113`) always, including when the profile already existed and nothing was written.
- **Preconditions:** none. Works in game and at the menu.
- **Threading & blocking:** script thread; synchronous Win32 INI I/O.
- **Side effects:** builds `"mode=%s\tgateway=%s\tusername=%s\tpassword=%s\tcharacter=%s\tspdifficulty=%d\t"` into `wchar_t settings[600]` (`:144-146`). It turns each `\t` into `\0` (`StringReplace`, `:148`, `Helpers.cpp:73`) and calls `WritePrivateProfileSectionW(profile, settings, file)` (`:149`). It does not write `ScriptPath`/`Default*Script` (see [storage](#profile-storage-d2bsini)).
- **Game internals:** none.
- **Quirks / bugs:**
  - Existing profiles are **never updated** (`:143`). The existence test is case-insensitive.
  - Values are not escaped. A tab inside a value is turned into `\0`, which splits the value and makes the remainder a separate entry (a `k=v` remainder becomes an extra key). CR/LF inside a value goes into the file raw and can inject lines or sections.
  - A formatted string of 600 or more characters makes `swprintf_s` invoke the invalid-parameter handler, which terminates the process.
  - `mode` is not validated. An unknown first letter gives `PROFILETYPE_INVALID`, which makes `login` spin forever at the main menu.

### `getLocation()`

Returns the current OOG screen code computed by probing the D2WIN control list.

- **Native:** `my_getOOGLocation` at `JSMenu.cpp:155`; registered at `JSGlobalFuncs.h:58` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** integer `OOG_Location` (`INT_TO_JSVAL(OOG_GetLocation())`, `:160`) at the menu. `null` (`:156`) when `ClientState() != ClientStateMenu` (`:157-158`), *not* `0`. `0` (`OOG_NONE`) means at the menu but no rule matched. Codes are listed in [OOG location codes](#oog-location-codes).
- **Preconditions:** menu.
- **Threading & blocking:** script thread; non-blocking. At most 24 `findControl` probes per call (longest paths: the 6 first-chain heads `:323-354` + the 18 second-chain probes `:389-428`, or 4 heads + the 2 nested CANCEL@351,337 probes + 18), each one walk of the control list; locale-id probes add a `D2LANG_GetLocaleText` + `_wcsdup` + `free` (`Control.cpp:12-18`). `ClientState()` is re-run inside every probe (twice for locale-id probes, `Control.cpp:8`, `:25`).
- **Side effects:** none. Read-only.
- **Game internals:** `OOG_GetLocation` (`Control.cpp:319`); `p_D2WIN_FirstControl`; `D2LANG_GetLocaleText`; `Control.dwType/dwDisabled/dwPos*/dwSize*/unkState/wText2/pFirstText`.
- **Quirks / bugs:** the result is a heuristic over hard-coded geometry and locale ids (language-independent, resolved through `D2LANG_GetLocaleText`). Code 37 is never produced. Popups overlaying a screen take precedence according to the fixed probe order.

### `createCharacter(name, classId, [hardcore], [ladder])`

**Not exposed to JS.** The registration is commented out ("this function is not finished", `JSGlobalFuncs.h:55-56`). It is documented here so a replacement doesn't assume it works.

- **Native:** `my_createCharacter` at `JSMenu.cpp:165`; **not registered** (would be arity 4).
- **Arguments / overloads:** `JS_ConvertArguments("Wi/bb")` (`:174`). On failure it throws "Failed to Convert Args createCharacter" (`:176`). `name` is re-read via `JSVAL_TO_STRING(argv[0])` (`:179`).
- **Returns:** boolean from `OOG_CreateCharacter` (`:181`), which **always returns FALSE** (`Control.cpp:176`). When not at the menu it returns (unset) (`:166-167`).
- **Preconditions / behaviour:** see [`OOG_CreateCharacter`](#oog_createcharacter). It requires location 12 (`OOG_CHAR_SELECT`, i.e. at least one existing character), so it could never create the first character of an empty account (location 42). It never types a name, ignores `hardcore`/`ladder`, and never clicks OK.

---

## OOG location codes

`OOG_Location` is defined at `Constants.h:75-121`. Value N is on line `Constants.h:76+N`. `OOG_GetLocation()` is `Control.cpp:319-432`. Probe notation is defined in [Conventions](#conventions-specific-to-this-page). Locale-id meanings come from code comments where present (5101 EXIT, 5102 OK, 5103 CANCEL, 5106 SINGLE PLAYER, 5190 "If using a modem", 5308 HELP, 10018 NORMAL, 10832 create new, 11126 ENTER CHAT). The others are inferred from the returned name.

| Value | Enum | Meaning | Detection rule (conditions in precedence context) | Line |
|---|---|---|---|---|
| 0 | `OOG_NONE` | not at the menu, or no rule matched | `ClientState() != ClientStateMenu`, or end of chain. JS `getLocation()` returns `null` for the first case. | `Control.cpp:320-321`, `:431` |
| 1 | `OOG_LOBBY` | Battle.net lobby | `B(11126 ENTER CHAT, 27, 480, 120, 20)` | `Control.cpp:406-407` |
| 2 | `OOG_INLINE` | waiting in line | `B(5103 CANCEL, 433, 433, 96, 32)` ∧ `T(*, 427, 234, 300, 100)` | `Control.cpp:343-345` |
| 3 | `OOG_CHAT` | chat channel | `B(5308 HELP, 187, 470, 80, 20)` | `Control.cpp:408-409` |
| 4 | `OOG_CREATE` | Create Game tab | CANCEL@433,433 ∧ `T(10018, 459, 380, 150, 12)` | `Control.cpp:346-347` |
| 5 | `OOG_JOIN` | Join Game tab | CANCEL@433,433 ∧ `B(5119, 594, 433, 172, 32)` | `Control.cpp:348-349` |
| 6 | `OOG_LADDER` | Ladder tab | CANCEL@433,433 ∧ none of 2/4/5/7 | `Control.cpp:352-353` |
| 7 | `OOG_CHANNEL` | channel list | CANCEL@433,433 ∧ `B(5102 OK, 671, 433, 96, 32)` | `Control.cpp:350-351` |
| 8 | `OOG_MAIN_MENU` | main menu | `B(5106 SINGLE PLAYER, 264, 324, 272, 35)` | `Control.cpp:404-405` |
| 9 | `OOG_LOGIN` | Battle.net account login | `B(5101 EXIT, 33, 572, 128, 35)` ∧ `B(5288, 264, 484, 272, 35)` | `Control.cpp:354-357` |
| 10 | `OOG_LOGIN_ERROR` | bad account/password popup | `B(5102 OK, 335, 412, 128, 35)` (2nd probe) | `Control.cpp:325-326` |
| 11 | `OOG_UNABLE_TO_CONNECT` | unable to connect | `B(5102 OK, 335, 450, 128, 35)` ∧ ¬19 ∧ `T(5190, 162, 420, 477, 100)` | `Control.cpp:389`, `:392-393` |
| 12 | `OOG_CHAR_SELECT` | character select, list loaded | EXIT@33,572 ∧ ¬9 ∧ ¬43 ∧ `B(5102 OK, 627, 572, 128, 35)` ∧ `B(10832, 33, 528, 168, 60)` ∧ ¬20 ∧ `T(*, 37, 178, 200, 92)` with `pFirstText && pFirstText->pNext` (≥ 2 rows) | `Control.cpp:360`, `:364-366` |
| 13 | `OOG_REALM_DOWN` | realm down (on char select) | same prefix as 12 ∧ ¬12 ∧ (`T(11162, 45, 318, 531, 140)` ∨ `T(11066, 45, 318, 531, 140)`) | `Control.cpp:368-369` |
| 14 | `OOG_DISCONNECTED` | disconnected popup | `B(5102 OK, 351, 337, 96, 32)` ∧ ¬17 ∧ `T(5347, 268, 320, 264, 120)` | `Control.cpp:331-332` |
| 15 | `OOG_NEW_CHARACTER` | char create, no class picked | EXIT@33,572 ∧ ¬9 ∧ ¬43 ∧ ¬(OK@627,572 ∧ create-new) ∧ ¬29 ∧ ¬32 (EXIT-branch catch-all) | `Control.cpp:384-385` |
| 16 | `OOG_CHARACTER_SELECT_PLEASE_WAIT` | "please wait" over char select | `B(5103 CANCEL, 351, 337, 96, 32)` ∧ `T(5243, 268, 300, 264, 100)` | `Control.cpp:337-340` |
| 17 | `OOG_LOST_CONNECTION` | lost connection popup | OK@351,337 ∧ `T(5351, 268, 320, 264, 120)` | `Control.cpp:329-330` |
| 18 | `OOG_D2SPLASH` | splash screen | `T(21882, 100, 580, 600, 80)` | `Control.cpp:410-411` |
| 19 | `OOG_CDKEY_IN_USE` | CD key in use | OK@335,450 ∧ `T(5200, 162, 270, 477, 50)` | `Control.cpp:390-391` |
| 20 | `OOG_DIFFICULTY` | SP / TCP-host difficulty picker | prefix of 12 ∧ `B(10018 NORMAL, 264, 297, 272, 35)` | `Control.cpp:362-363` |
| 21 | `OOG_MAIN_MENU_CONNECTING` | "connecting to Battle.net" | `B(5103 CANCEL, 330, 416, 128, 35)` (**first probe**) | `Control.cpp:323-324` |
| 22 | `OOG_INVALID_CDKEY` | invalid CD key | OK@335,450 ∧ ¬19 ∧ ¬11 | `Control.cpp:394-395` |
| 23 | `OOG_CONNECTING` | "connecting…" on char select | prefix of 12 ∧ ¬12 ∧ ¬13 ∧ `T(11065, 0x2D, 0x13E, 0x213, 0x8C)` = (45, 318, 531, 140) | `Control.cpp:371-372` |
| 24 | `OOG_SERVER_DOWN` | server down | `T(5139, 438, 300, 326, 150)` | `Control.cpp:402-403` |
| 25 | `OOG_PLEASE_WAIT` | generic "Please wait…" | CANCEL@351,337 ∧ ¬16 ∧ `T(*, 268, 320, 264, 120)` | `Control.cpp:341-342` |
| 26 | `OOG_GAME_EXIST` | game already exists | `T(5138, 438, 300, 326, 150)` | `Control.cpp:400-401` |
| 27 | `OOG_GATEWAY` | gateway list | `B(5102 OK, 281, 538, 96, 32)` | `Control.cpp:412-413` |
| 28 | `OOG_GAME_DOES_NOT_EXIST` | game does not exist | `T(5159, 438, 300, 326, 150)` | `Control.cpp:396-397` |
| 29 | `OOG_CHARACTER_CREATE` | char create, class picked | EXIT@33,572 ∧ ¬9 ∧ ¬43 ∧ ¬(OK@627,572 ∧ create-new) ∧ `B0(5102 OK, 627, 572, 128, 35)` | `Control.cpp:379-380` |
| 30 | `OOG_CHARACTER_CREATE_ALREADY_EXISTS` | duplicate char name (catch-all for OK@351,337) | OK@351,337 ∧ ¬17 ∧ ¬14 ∧ ¬44 | `Control.cpp:335-336` |
| 31 | `OOG_AGREE_TO_TERMS` | agree to terms | `B(5181, 525, 513, 128, 35)` | `Control.cpp:414-415` |
| 32 | `OOG_NEW_ACCOUNT` | create Battle.net account | EXIT-branch ∧ ¬29 ∧ `T(5226, 321, 448, 300, 32)` | `Control.cpp:382-383` |
| 33 | `OOG_PLEASE_READ` | "please read" | `B(5102 OK, 525, 513, 128, 35)` | `Control.cpp:416-417` |
| 34 | `OOG_REGISTER_EMAIL` | register e-mail | `B(11097, 265, 527, 272, 35)` | `Control.cpp:418-419` |
| 35 | `OOG_CREDITS` | credits | `B(5101 EXIT, 33, 578, 128, 35)` | `Control.cpp:420-421` |
| 36 | `OOG_CINEMATICS` | cinematics list | `B(5103 CANCEL, 334, 488, 128, 35)` | `Control.cpp:422-423` |
| 37 | `OOG_CHARACTOR_CHANGE_REALM` | (spelling as in source) | **never returned** | `Constants.h:113` |
| 38 | `OOG_GAME_IS_FULL` | game is full | `T(5161, 438, 300, 326, 150)` | `Control.cpp:398-399` |
| 39 | `OOG_OTHER_MULTIPLAYER` | Other Multiplayer menu | `B(5116, 264, 350, 272, 35)` | `Control.cpp:424-425` |
| 40 | `OOG_TCP_IP` | TCP/IP Host/Join menu | `B(5118, 265, 206, 272, 35)` | `Control.cpp:428-429` |
| 41 | `OOG_ENTER_IP_ADDRESS` | enter host IP | `B(5103 CANCEL, 281, 337, 96, 32)` | `Control.cpp:426-427` |
| 42 | `OOG_CHARACTER_SELECT_NO_CHARS` | char select, list not loaded or empty | prefix of 12 ∧ ¬12 ∧ ¬13 ∧ ¬23 | `Control.cpp:373-374` |
| 43 | `OOG_CHARACTER_SELECT_CHANGE_REALM` | change-realm dialog on char select | EXIT@33,572 ∧ ¬9 ∧ `B(5102 OK, 495, 438, 96, 32)` | `Control.cpp:358-359` |
| 44 | `OOG_UNABLE_TO_CONNECT_TCPIP` | TCP/IP connect failed popup | OK@351,337 ∧ ¬17 ∧ ¬14 ∧ `B(*, 265, 206, 272, 35)` | `Control.cpp:333-334` |

**Evaluation order** (first match wins; the `else if` chain `Control.cpp:323-388` is followed by a second chain `:389-429`):

```
ClientState()!=Menu                        -> 0
B(5103,330,416,128,35)                     -> 21
B(5102,335,412,128,35)                     -> 10
B(5102,351,337,96,32):  T(5351..)->17 | T(5347..)->14 | B(*,265,206,272,35)->44 | else 30
B(5103,351,337,96,32):  T(5243..)->16 | T(*,268,320,264,120)->25 | else FALL THROUGH to second chain
B(5103,433,433,96,32):  T(*,427,234..)->2 | T(10018..)->4 | B(5119..)->5 | B(5102,671,433..)->7 | else 6
B(5101,33,572,128,35):  B(5288..)->9 | B(5102,495,438..)->43
                        | [B(5102,627,572..) && B(10832,33,528..)]: B(10018,264,297..)->20 | slot T(*,37,178,200,92) with >=2 rows ->12
                                                                   | T(11162|11066..)->13 | T(11065..)->23 | else 42
                        | (redundant re-test of EXIT, :377) B0(5102,627,572..)->29 | T(5226..)->32 | else 15
second chain: B(5102,335,450..): T(5200..)->19 | T(5190..)->11 | else 22
  T(5159)->28  T(5161)->38  T(5138)->26  T(5139)->24  B(5106)->8  B(11126)->1  B(5308)->3  T(21882)->18
  B(5102,281,538)->27  B(5181)->31  B(5102,525,513)->33  B(11097)->34  B(5101,33,578)->35  B(5103,334,488)->36
  B(5116)->39  B(5103,281,337)->41  B(5118)->40   else 0
```

Text-match semantics (from [`findControl`](#findcontrol-matching)): for buttons the comparison is exact `wcscmp` against the locale string. For textboxes the control's **first row must be a substring of the locale string**, so a textbox whose first row is `L""` matches any locale id.

---

## The login state machine

`Profile::login(char** error)` (`Profile.cpp:97-297`) is used by both `login()` and `Profile.prototype.login()`. It returns `0` on success, `1` on timeout (`*error = "login time out"`) and `2` on error (`*error = errorMsg`). The JS wrappers throw `error` for any non-zero value.

**Loop** (`Profile.cpp:114-292`): `location = OOG_GetLocation()`, then the `switch` below. Then:

1. if `errorMsg` is non-empty: unblock input, return 2 (`:276-280`). One failed lookup aborts the whole login; there is no retry.
2. if `timeout * 100 > maxLoginTime`: unblock input, return 1 (`:282-286`). `maxLoginTime` is `[settings] MaxLoginTime` × 1000 ms, default 5 s (`Profile.cpp:25`, `:28`). Only iterations marked **T** below increment `timeout`.
3. if `ClientState() == ClientStateInGame`: done (`:288-289`).
4. `Sleep(100)` (`:291`).

Input is blocked (`Vars.bBlockKeys = Vars.bBlockMouse = TRUE`) from `:112` until return. `maxCharTime` (`[settings] MaxCharSelectTime`) is read but **never used** by the loop. A path that sets `loginComplete` in the `switch` still runs steps 1–4 once (including the final `Sleep(100)`) before the loop exits and returns 0 (`:294-296`).

Local state: `skippedToBnet` (starts TRUE, `:99`), `clickedOnce` (starts false, `:110`), `timeout` (starts 0, `:103`), `errorMsg` (starts `""`, `:101`). Helper predicates: `isOtherMP(type)` is true for OPEN_BATTLENET, TCPIP_HOST and TCPIP_JOIN (`Profile.cpp:76-85`); `isTcpIp(type)` for TCPIP_HOST and TCPIP_JOIN (`Profile.cpp:87-95`). `errorMsg` is a plain assignment, so when several checks fail in one iteration the **last** message set wins (e.g. both login edit boxes missing reports only "Failed to set the 'Password' text-edit box.").

| Location (value) | Action (by profile type) | T | Error message on failure | Lines |
|---|---|---|---|---|
| `OOG_D2SPLASH` (18) | `clickControl(*p_D2WIN_FirstControl)` (centre of the first control in the list) | – | – (no check) | `Profile.cpp:117-119` |
| `OOG_CHAR_SELECT` (12) | `OOG_SelectCharacter(charname)` | – | "Invalid character name" | `:121-125` |
| `OOG_MAIN_MENU` (8) | SP: click `B(*, 264, 324, 272, 35)`. BNET: `OOG_SelectGateway(gateway, 256)` (result ignored), then click `B(*, 264, 366, 272, 35)`. OpenBNet/Host/Join (`isOtherMP`): click `B(*, 264, 433, 272, 35)`; only if that click is posted, set `skippedToBnet = FALSE`. INVALID: nothing. | – | "Failed to click the Single button?" / "Failed to click the 'Battle.net' button?" / "Failed to click the 'Other Multiplayer' button?" | `:126-141` |
| `OOG_LOGIN` (9) | If (SP or `isOtherMP`) and `skippedToBnet` is still TRUE: click `findControl(6, L"EXIT", -1, 33, 572, 128, 35)` and end the iteration (`break` before `timeout++`; literal English text, not a locale id). Otherwise: `SetControlText(E(*, 322, 342, 162, 19), username)`, `SetControlText(E(*, 322, 396, 162, 19), password)`, click `B(*, 264, 484, 272, 35)` if present. | **T** (credential branch only) | "Failed to click the exit button?" / "Failed to set the 'Username' text-edit box." / "Failed to set the 'Password' text-edit box." / "Failed to click the 'Log in' button?" (only if the button was found but the click failed) | `:142-165` |
| `OOG_DIFFICULTY` (20) | normal `B(*, 264, 297, 272, 35)`, nightmare `(264, 340)`, hell `(264, 383)` (all 272×35). `diff` 0/1/2: requires `dwDisabled == 0x0d`, then click. `diff` 3: first of hell → nightmare → normal with `dwDisabled == 0x0d`. **Missing `break`: falls through into `OOG_OTHER_MULTIPLAYER`.** | – | "Failed to click the 'Normal Difficulty' button?" / "…'Nightmare Difficulty'…" / "…'Hell Difficulty'…" / "Failed to click ANY difficulty button?" / "Invalid single player difficulty level specified!" | `:166-197` |
| `OOG_OTHER_MULTIPLAYER` (39) | OpenBNet: click `B(*, 264, 310, 272, 35)`. Host/Join (`isTcpIp`): click `B(*, 264, 350, 272, 35)`; the dangling `else` binds to the inner `if`, so the error is raised only if the click failed **and** `clickedOnce` is false, otherwise `clickedOnce = true` (`:204-208`). SP/BNET/INVALID: nothing. | – | "Failed to click the 'Open Battle.net' button?" / "Failed to click the 'TCP/IP Game' button?" | `:198-210` |
| `OOG_TCP_IP` (40) | Host: click `B(*, 265, 206, 272, 35)`. Join: click `B(*, 265, 264, 272, 35)`. Others: nothing. | – | "Failed to click the 'Host Game' button?" / "Failed to click the 'Join Game' button?" | `:211-218` |
| `OOG_ENTER_IP_ADDRESS` (41) | if `ip != ""` (`_wcsicmp`, `:220`): `SetControlText(E(*, 300, 268, -1, -1), ip)`, click OK `B(*, 421, 337, 96, 32)`. Any profile type reaches this code. `ip` is the INI `username` value, so a missing key types the default `"ERROR"` as the IP; only an explicitly empty `username=` triggers the "Could not get the IP address…" error. | – | "Failed to click the OK button" / "Failed to find the 'Host IP Address' text-edit box." / "Could not get the IP address from the profile in the d2bs.ini file." | `:219-235` |
| `OOG_UNABLE_TO_CONNECT_TCPIP` (44) | – | – | "Failed to join Host IP Address" | `:236-238` |
| 21, 16, 25, 27, 42, 23, 0 | wait | **T** | – | `:239-247` |
| 1, 2, 3, 4, 5, 6, 7, 26, 28 | `loginComplete = TRUE` → return 0 | – | – | `:248-258` |
| `OOG_UNABLE_TO_CONNECT` (11) | – | – | "Unable to connect" | `:259-261` |
| `OOG_CDKEY_IN_USE` (19) | – | – | "CD-Key in use" | `:262-264` |
| `OOG_LOGIN_ERROR` (10) | – | – | "Bad account or password" | `:265-267` |
| `OOG_REALM_DOWN` (13) | – | – | "Realm Down" | `:268-270` |
| any other (14, 15, 17, 22, 24, 29–38, 43) | – | – | "Unhandled login location" | `:271-273` |

**Happy paths** (each arrow is one or more loop iterations):

| Profile type (`mode` first letter) | Path |
|---|---|
| single player (`s`) | [18 splash] → 8 main → Single Player → 12 char select → slot + OK → 20 difficulty → (0 while loading, **T**) → in game |
| Battle.net (`b`) | 8 main → gateway fix-up + Battle.net → 21 connecting (**T**) → 9 login → credentials + Log in (**T**) → 16/42/23 (**T**) → 12 → slot + OK → 1/3 lobby or chat → done |
| Open Battle.net (`o`) | 8 → Other Multiplayer → 39 → Open Battle.net → 9 (credentials, because `skippedToBnet` is now FALSE) → … → 12 → lobby → done |
| TCP/IP host (`h`) | 8 → Other Multiplayer → 39 → TCP/IP Game → 40 → Host Game → 12 → 20 difficulty (falls through to the 39 code; harmless only if this same call already clicked TCP/IP Game, which sets `clickedOnce`. A call started at 12/20 instead fails with "Failed to click the 'TCP/IP Game' button?" after clicking the difficulty) → in game |
| TCP/IP join (`j`) | 8 → 39 → 40 → Join Game → 41 → IP (from the INI `username` key) + OK → 12 → in game |

**Non-terminating and fragile cases:**

- States that never increment `timeout` and take no action spin forever with input blocked: `PROFILETYPE_INVALID` at 8; SP/BNET at 39; SP/BNET/OpenBNet at 40; and 18/8/12/20/39/40/41 whenever the posted click has no effect.
- `OOG_DIFFICULTY` dereferences `normal/nightmare/hell` without NULL checks (`:174`, `:178`, `:182`, `:186-188`).
- The timeout charges a flat 100 ms per counted iteration and ignores click sleeps and uncounted states, so wall-clock time always exceeds `MaxLoginTime`. Loading time counts too (state 0 while `ClientState()` is Busy): a slow game load can return "login time out" even though the game then loads.
- `MaxLoginTime=0` fails on the first counted iteration.
- An account with no characters stays in 42, which is counted, so login ends with a timeout. Character creation is not attempted.
- During `OOG_LOGIN` the username and password are retyped and the button re-clicked on every iteration while the screen persists.
- The literal `L"EXIT"` (`:144`) fails on non-English clients, where the button text differs.

---

## Profile storage (`d2bs.ini`)

The file is `Vars.szPath + L"d2bs.ini"`, i.e. the D2BS directory (`Profile.cpp:16`, `JSMenu.cpp:53`, `:142`; `Vars.szPath` set in `D2BS.cpp:33-39`). It is accessed only through Win32 `GetPrivateProfileStringW` / `WritePrivateProfileSectionW`. Section names are case-insensitive. **Every section is a "profile"**, `[settings]` included (`Profile.cpp:59-74` enumerates all section names into a 65535-wchar stack buffer; a longer list is truncated).

| Section | Key | Read at | Default | Buffer | Meaning / conversion |
|---|---|---|---|---|---|
| `[<profile>]` | `mode` | `Profile.cpp:18` | `single` | 256 | `tolower(mode[0])`: `s`→1 SINGLEPLAYER, `b`→2 BATTLENET, `o`→3 OPEN_BATTLENET, `h`→4 TCPIP_HOST, `j`→5 TCPIP_JOIN, else 0 INVALID (`:40-56`) |
| `[<profile>]` | `character` | `Profile.cpp:19`, `JSMenu.cpp:54` | `ERROR` | 24 (23 chars) | character to select (case-insensitive) |
| `[<profile>]` | `spdifficulty` | `Profile.cpp:20` | `0` | 10 | `_wtoi`; must be 0..3, else `throw "Invalid difficulty."` (`:31-36`). 3 = hardest available. |
| `[<profile>]` | `username` | `Profile.cpp:21` | `ERROR` | 48 | Battle.net account. For `j` profiles this is also the **host IP**: `ip[16]` and `username[48]` share a union (`Profile.h:11-14`) and there is no `ip` key. |
| `[<profile>]` | `password` | `Profile.cpp:22` | `ERROR` | 256 | plaintext |
| `[<profile>]` | `gateway` | `Profile.cpp:23` | `ERROR` | 256 | substring of the gateway label. A value containing `ERROR` skips gateway selection (`Control.cpp:243-244`). |
| `[<profile>]` | `ScriptPath`, `DefaultConsoleScript`, `DefaultGameScript`, `DefaultStarterScript` | `Helpers.cpp:88-91` | `scripts`, `""`… | – | only via `SwitchToProfile` (`Helpers.cpp:80`), which requires `[settings] UseProfileScript=true`. It then clears `Vars.bUseProfileScript` (`Helpers.cpp:102`), so only one switch per process succeeds. See [../architecture.md](../architecture.md). |
| `[settings]` | `MaxLoginTime` | `Profile.cpp:25` | `5` | 10 | seconds → `abs(_wtoi(v) * 1000)` ms (`:28`) |
| `[settings]` | `MaxCharSelectTime` | `Profile.cpp:26` | `5` | 10 | seconds → ms (`:29`). Exposed as `Profile.maxCharacterSelectTime`, unused by `login`. |

Who sets the *active* profile `Vars.szProfile` (`wchar_t[256]`, `D2BS.h:84`; used by `login()` and `new Profile()` with no argument): `login(name)` (`JSMenu.cpp:25`), and `SwitchToProfile` (`Helpers.cpp:93`), which succeeds only while `Vars.bUseProfileScript` is TRUE (`[settings] UseProfileScript`, default `false`, `Helpers.cpp:81`, `:128`) and clears it on success (`:102`), so at most one switch per process. `SwitchToProfile` is reached from the `-profile` command line (`D2Handlers.cpp:57-64`), `WM_COPYDATA` `dwData == 0x31337` (`D2Handlers.cpp:190-191`; the payload goes through `AnsiToUnicode`, `D2Handlers.cpp:183`), DDE `XTYP_POKE` (`dde.cpp:17`) and the debug-build console command `profile` (`Helpers.cpp:295-297`, inside `#if DEBUG`). The DDE path is dead in practice: `pslzItem` is converted from the still-empty `pszItem` buffer **before** `DdeGetData` fills it (`dde.cpp:10-11` vs `:16`), so `SwitchToProfile` always receives `""` and fails. Readers of `Vars.szProfile`: `me.profile` (`JSUnit.cpp:60-61`), the log file name (`D2Helpers.cpp:41`), `login()`, `Profile()`. Sample file: `resources/d2bs.ini:43-66`. See also [../architecture.md § 5.3](../architecture.md#53-profile-section-keys) and [§ 7.5](../architecture.md#75-profile-selection).

---

## Profile

- **JSClass:** `"Profile"`, `JSCLASS_HAS_PRIVATE`, finalizer `profile_finalize`, constructor `profile_ctor` (`JSGlobalClasses.cpp:112-114`). Registered from `global_classes` (`JSGlobalClasses.cpp:167`) by `JS_InitClass(cx, global, NULL, &profile_class, profile_ctor, 0, profile_props, profile_methods, NULL, NULL)` (`ScriptEngine.cpp:232`, `:358-359`). Props and methods therefore live on `Profile.prototype`, and `BuildObject` defines them again as own properties of each instance (`js32.cpp:18-21`).
- **Constructor:** real. `new Profile(...)` and `Profile(...)` both run `profile_ctor`. It builds a **fresh** object with `BuildObject(cx, &profile_class, profile_methods, profile_props)` (`JSProfile.cpp:83`), attaches the C++ `Profile*` (`:86`) and returns it (`:87`); `this` is ignored. No other native creates `Profile` objects.
- **Private data:** a heap `Profile` (`Profile.h:8-67`): `type` (ProfileType), `union { ip[16]; username[48]; }`, `password[256]`, `gateway[256]`, `charname[24]`, `diff` (wchar_t), `maxLoginTime`, `maxCharTime` (ms). `profile_finalize` deletes it (`JSProfile.cpp:105-114`). `struct jsProfilePrivate { char* password; }` (`JSProfile.h:16-18`) is unused.
- **Identity & lifetime:** the object holds a **snapshot** of the INI values taken at construction. Later INI edits are not seen. It holds no game pointer. Equality is object identity.
- **Prototype hazard:** `profile_getProperty` and `profile_login` do not NULL-check the private (`JSProfile.cpp:119`, `:97-99`). `Profile.prototype.type` or `Profile.prototype.login()` dereferences NULL. Neither uses `JS_GetInstancePrivate`, so `Profile.prototype.login.call(otherObj)` treats another class's private as a `Profile*`.

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `type` | `PROFILE_TYPE` (0) | int | R | all | `prof->type` | 0..5, see [ProfileType](#profiletype-not-registered) |
| `ip` | `PROFILE_IP` (1) | string | R | all | `prof->ip` | **same storage as `username`** (union): always equals `username` |
| `username` | `PROFILE_USERNAME` (2) | string | R | all | `prof->username` | `"ERROR"` if the key is missing |
| `gateway` | `PROFILE_GATEWAY` (3) | string | R | all | `prof->gateway` | |
| `character` | `PROFILE_CHARACTER` (4) | string | R | all | `prof->charname` | |
| `difficulty` | `PROFILE_DIFFICULTY` (5) | int | R | all | `prof->diff` | 0..3 |
| `maxLoginTime` | `PROFILE_MAXLOGINTIME` (6) | int | R | all | `prof->maxLoginTime` (ms) | 5000 for constructed profiles (`Profile.h:49`, `:54`, `:59`) |
| `maxCharacterSelectTime` | `PROFILE_MAXCHARSELTIME` (7) | int | R | all | `prof->maxCharTime` (ms) | unused by `login` |

Property specs are at `JSProfile.h:31-39`, all `JSPROP_PERMANENT_VAR` (read-only), getter `profile_getProperty` (`JSProfile.cpp:116-152`). The password is not exposed.

### `Profile(...args)`

Constructs a `Profile` snapshot from the INI, or from explicit fields.

- **Native:** `profile_ctor` at `JSProfile.cpp:16`; registered as the `Profile` constructor at `JSGlobalClasses.cpp:112-114`/`:167` (nargs 0).
- **Arguments / overloads:**

  | Call shape | Test | C++ constructor | Lines |
  |---|---|---|---|
  | `Profile()` | `argc == 0` | `Profile()` → `init(Vars.szProfile)` | `JSProfile.cpp:30-35`, `Profile.h:38-40` |
  | `Profile(name)` | `argc == 1 && JSVAL_IS_STRING` | `Profile(name)` → `init(name)`. **No existence check**: unknown names give defaults (`mode` single, `character` "ERROR", …). | `:37-40`, `Profile.cpp:6` |
  | `Profile(1, charname, diff)` | `argc == 3`, `argv[0]` int == SINGLEPLAYER | `Profile(pt, charName, (char)diff)` | `:42-46` |
  | `Profile(2, account, pass, charname, gateway)` | `argc == 5`, == BATTLENET | `Profile(pt, account, pass, charname, gateway)` | `:48-55` |
  | `Profile(3, account, pass, charname, gateway)` | `argc == 5`, == OPEN_BATTLENET | same | `:57-64` |
  | `Profile(4, charname, diff)` | `argc == 3`, == TCPIP_HOST | `Profile(pt, charName, (char)diff)` | `:66-70` |
  | `Profile(5, charname, ip)` | `argc == 3`, == TCPIP_JOIN | `Profile(pt, charname, ip)` | `:72-76` |
  | anything else | – | throws "Invalid parameters." | `:77-78` |

  For the explicit shapes, the string arguments get `JSVAL_TO_STRING` and the difficulty gets `JSVAL_TO_INT` with **no type tests**, so a wrong type gives an invalid pointer or garbage. `init(name)` throws `"Can't open null profile name."`, `"Can't open empty profile name."` (an empty `Vars.szProfile` with `Profile()`) or `"Invalid difficulty."` (`Profile.cpp:10-14`, `:33-34`). These are caught by `catch (char* ex)` and re-thrown as JS errors (`JSProfile.cpp:79-81`). Catching a string literal with `catch (char*)` relies on MSVC's non-strict string-literal typing: there is no `/permissive-` / `/Zc:strictStrings` in `D2BS.vcxproj`, and Release builds have `<ExceptionHandling>false</ExceptionHandling>` (`D2BS.vcxproj:157`) with warning C4530 ("C++ exception handler used, but unwind semantics are not enabled") suppressed (`D2BS.vcxproj:155`), so `try`/`catch` compiles without unwind semantics. "No active profile!" (`:34`) is unreachable (array test).
- **Returns:** a new `Profile` object. If `BuildObject` fails it throws "Failed to create profile object" (`:84-85`; the C++ `Profile` leaks).
- **Preconditions:** none (works in game).
- **Threading & blocking:** script thread; INI reads for the name shapes.
- **Side effects:** none besides INI reads.
- **Game internals:** none.
- **Quirks / bugs:** **every explicit-field shape is broken.** The inline `init(pt, …)` copies with `wcscpy_s(dst, wcslen(dst), src)` (`Profile.h:27-30`) on freshly `new`-ed, uninitialised buffers. The size argument is the length of whatever garbage is in the buffer (and `wcslen` itself may read past it). If that is 0 or not larger than the source length, `wcscpy_s` calls the invalid-parameter handler and the process terminates; otherwise the copy happens with a meaningless bound (a source longer than the real buffer, e.g. a 24+ char `charname`, overflows the object). `diff` and the timing fields are set correctly (`Profile.h:31-33`). Use `Profile(name)` only.

### `Profile.prototype.login()`

Runs [the login state machine](#the-login-state-machine) with this snapshot.

- **Native:** `profile_login` at `JSProfile.cpp:92`; registered at `JSProfile.h:41` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `undefined` (`:93`); a non-zero result throws the error string (`:99-100`).
- **Preconditions:** **none.** Unlike `login()` there is no menu check. In game the first iteration sees location 0 (counted), then `ClientState()==InGame` ends the loop. The net effect is about 100 ms and `blockKeys`/`blockMouse` forced to FALSE, or "login time out" if `MaxLoginTime=0`. While the client is Busy (loading) or Null, `OOG_GetLocation()` keeps returning 0, which is counted, so the call blocks until the game is ready or throws "login time out" after `MaxLoginTime`. `Vars.szProfile` is **not** changed.
- **Threading & blocking:** as `login()`.
- **Side effects:** as `login()`, except for `Vars.szProfile`.
- **Game internals:** as `login()`.
- **Quirks / bugs:** NULL private crash on `Profile.prototype.login()`.

## ProfileType (not registered)

`profileType_class` (`"ProfileType"`, `JSCLASS_HAS_PRIVATE`, ctor `profileType_ctor`, no finalizer) is defined at `JSGlobalClasses.cpp:116-118`. The active `global_classes[]` (`JSGlobalClasses.cpp:143-170`) has no entry for it; it appears only in the obsolete commented-out table (`JSGlobalClasses.cpp:184`), and it is not created anywhere else (the only other reference is the `extern` at `JSGlobalClasses.h:29`), so **`ProfileType` is undefined in scripts**. `profileType_props` (`JSProfile.h:47-52`: `singlePlayer`, `battleNet`, `openBattleNet`, `tcpIpHost`, `tcpIpJoin`), `EMPTY_CTOR(profileType)` (`JSProfile.cpp:154`, would throw "Invalid Operation") and `profileType_getProperty` (`:156-162`, returns the tinyid itself) are dead code. Scripts must pass raw integers. Values come from `enum ProfileType` (`Profile.h:6`):

| Value | Enum | Intended JS name |
|---|---|---|
| 0 | `PROFILETYPE_INVALID` | – |
| 1 | `PROFILETYPE_SINGLEPLAYER` | `singlePlayer` |
| 2 | `PROFILETYPE_BATTLENET` | `battleNet` |
| 3 | `PROFILETYPE_OPEN_BATTLENET` | `openBattleNet` |
| 4 | `PROFILETYPE_TCPIP_HOST` | `tcpIpHost` |
| 5 | `PROFILETYPE_TCPIP_JOIN` | `tcpIpJoin` |

---

## Control

- **JSClass:** `"Control"`, `JSCLASS_HAS_PRIVATE`, finalizer `control_finalize`, constructor `control_ctor` (`JSGlobalClasses.cpp:100-102`). Registered from `global_classes` (`JSGlobalClasses.cpp:148`) through `JS_InitClass` with `control_props`/`control_funcs` on the prototype (`ScriptEngine.cpp:232`). Instances also get them as own properties (`BuildObject`, `js32.cpp:18-21`).
- **Constructor:** `EMPTY_CTOR(control)` (`JSControl.cpp:6`): `new Control()` throws "Invalid Operation" (`js32.h:136-139`). Instances come only from [`getControl`](#getcontroltype-x-y-xsize-ysize) and [`getControls`](#getcontrols). [`getNext`](#controlprototypegetnext) rebinds an existing instance instead of creating one.
- **Private data:** `struct ControlData` (`JSControl.h:21-30`), allocated with `new` in `getControl`/`getControls`:

  | Field | Meaning |
  |---|---|
  | `_dwPrivate` | never initialised or read |
  | `pControl` | raw `Control*` captured at creation. Written by `getNext` (`JSControl.cpp:169`) but **never used to access the control**. |
  | `dwType, dwX, dwY, dwSizeX, dwSizeY` | the identity key: `dwType`, `dwPosX`, `dwPosY`, `dwSizeX`, `dwSizeY` at creation |

  `control_finalize` deletes it (`JSControl.cpp:8-15`).
- **Identity & lifetime:** every property access and method call **re-resolves** the control with `findControl(dwType, NULL, -1, dwX, dwY, dwSizeX, dwSizeY)` (`JSControl.cpp:25`, `:105`, `:162`, `:196`, `:224`, `:250`). That returns the *first* control in the D2WIN list with that type and geometry. Consequences:
  - Two controls with identical type and geometry are indistinguishable. All objects alias the first, including objects from `getControls()`.
  - After a screen change the object silently binds to any control on the new screen with the same key.
  - When nothing matches, getters/setters return `JS_FALSE` with no exception, which uncatchably ends the running JS (`:26-27`, `:106-107`). `click`/`setText`/`getText` return `0` instead.
  - Each `getControl`/`getControls` call creates new objects, so `==` between two objects for the same control is `false`.
  - The `Control*` returned by `findControl` is used without any lock while the game thread may free it (TOCTOU).
- **Prototype:** `Control.prototype` has a NULL private. Getters return `JS_FALSE` (`:22-23`), which terminates the JS. The methods use `JS_GetPrivate` (not `JS_GetInstancePrivate`), so calling them with a foreign `this` reinterprets another class's private as `ControlData`.

**Control types** (`Constants.h:59-70`; legacy names from `doc/Control.h:66-91`):

| `type` | Constant | Legacy name |
|---|---|---|
| 1 | `CONTROL_EDITBOX` | TextBox |
| 2 | `CONTROL_IMAGE` | Image |
| 3 | `CONTROL_UNUSED` | Image2 |
| 4 | `CONTROL_TEXTBOX` | LabelBox |
| 5 | `CONTROL_SCROLLBAR` | ScrollBar |
| 6 | `CONTROL_BUTTON` | Button |
| 7 | `CONTROL_LIST` | List |
| 8 | `CONTROL_TIMER` | Timer |
| 9 | `CONTROL_SMACK` | Smack |
| 10 | `CONTROL_PROGRESSBAR` | ProgressBar |
| 11 | `CONTROL_POPUP` | Popup |
| 12 | `CONTROL_ACCOUNTLIST` | AccountList |

**Properties** (`JSControl.h:49-63`; getter `control_getProperty` `JSControl.cpp:17`, setter `control_setProperty` `JSControl.cpp:97`). All require the menu and a resolvable control, else `JS_FALSE` (terminate). Offsets are the compiled layout of `struct Control` (`D2Structs.h:132-168`); see [../memory/structs.md](../memory/structs.md).

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `text` | `CONTROL_TEXT` (0) | string / `undefined` | RW | getter: only if `dwIsCloaked != 33`; for password boxes `vp` is left untouched (the property's slot value, normally `undefined`). Setter: `dwType == 1` and string value only. | type 6: `wText2` (+0x64). Otherwise `wText` (+0x5C). Via `JS_InternUCString` (`JSControl.cpp:47-51`). | Setter → `D2WIN_SetControlText(ctrl, text)` on the script thread (`:112-119`). Other types or non-strings are silently ignored. `JS_InternUCString` interns (pins) every string read, and reads up to the first NUL with no bound on the 256-wchar buffer. For types other than 1/6 the value is whatever lives at +0x5C. |
| `x` | `CONTROL_X` (1) | number | R | any | `dwPosX` (+0x0C) | `:52-55` |
| `y` | `CONTROL_Y` (2) | number | R | any | `dwPosY` (+0x10) | Apparently the **bottom** edge: `clickControl` uses `y - ysize/2` as the centre (`Control.cpp:121`). |
| `xsize` | `CONTROL_XSIZE` (3) | number | R | any | `dwSizeX` (+0x14) | |
| `ysize` | `CONTROL_YSIZE` (4) | number | R | any | `dwSizeY` (+0x18) | |
| `state` | `CONTROL_STATE` (5) | number | RW | any | `dwDisabled - 2` (unsigned arithmetic, `:65-67`) | `dwDisabled < 2` reads as 4294967294/4294967295. Setter: int32 0..3 only, else throws "Invalid state value" (non-int32 is ignored). It then does **`memset(&dwDisabled, nState + 2, 4)`** (`:128`), producing `0x02020202`…`0x05050505`, not `nState + 2`. |
| `password` | `CONTROL_PASSWORD` (12) | boolean | R | any | `dwIsCloaked == 33` (+0x260) | Edit boxes. For other types this reads +0x260, possibly past the game's allocation. |
| `type` | `CONTROL_TYPE` (7) | number | R | any | `dwType` (+0x00) | table above |
| `cursorpos` | `CONTROL_CURSORPOS` (9) | number | RW | any | `dwCursorPos` (+0x25C) | Setter: int32 only, `JS_ValueToECMAUint32`, then **`memset(&dwCursorPos, dwPos, 4)`** (`:141`), so only the low byte, replicated (5 → `0x05050505`). "Invalid cursor position value" is effectively unreachable. Lower-case name (legacy `cursorPos`). |
| `selectstart` | `CONTROL_SELECTSTART` (10) | number | R | any | `dwSelectStart` (+0x58) | |
| `selectend` | `CONTROL_SELECTEND` (11) | number | R | any | `dwSelectEnd` (+0x54) | |
| `disabled` | `CONTROL_DISABLED` (13) | number | R | any | raw `dwDisabled` (+0x08) | A setter is wired (`:144-148`, also `memset`), but the spec is `JSPROP_PERMANENT_VAR`, which includes `JSPROP_READONLY` (`js32.h:100`; "assignment is no-op", `dependencies/include/jsapi.h:1410`). So the setter is not reached. Observed values in code: `0x0d` = clickable SP difficulty button, `0x4` = unavailable create-game radio (`Profile.cpp:174`, `Control.cpp:511`). |
| *(maxlength)* | `CONTROL_MAXLENGTH` (6) | – | – | **not registered** (commented, `JSControl.h:56`) | getter case is empty (`JSControl.cpp:68-70`) | |
| *(visible)* | `CONTROL_VISIBLE` (8) | – | – | **not registered** (`JSControl.h:58`) | empty case (`:74-76`) | |

Getter mechanics: it calls `JS_BeginRequest` (`:31`) and returns early without `JS_EndRequest` for string, void or zero ids (`:35-45`). Those ids cannot occur for these tinyid properties, so the imbalance is dormant.

### `getControl([type], [x], [y], [xsize], [ysize])`

Returns the first control in the D2WIN list matching all given criteria. `-1` or omitted means "any".

- **Native:** `my_getControl` at `JSControl.cpp:292`; registered at `JSGlobalFuncs.h:34` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** positional `type, x, y, xsize, ysize`, all defaulting to `-1` (`:298`). For each `i < argc`, if `JSVAL_IS_INT(argv[i])` the slot is converted with `JS_ValueToECMAInt32` (`:301-303`). Doubles (even integral-valued doubles not stored as int), strings and other types are **silently ignored** and stay wildcards. There is **no `argc ≤ 5` check**: a 6th or later *int* argument writes through `args[i]` past the 5-element pointer array (`:299`, `:303`), which is stack corruption. Text and disabled-state criteria are not available (`findControl(nType, NULL, -1, …)`, `:306`).
- **Returns:** a new `Control` (`:318-322`), or `undefined` if not at the menu or nothing matched (`:293`, `:307-308`). With no criteria at all, it returns the head of the list (`Control.cpp:28-29`). If `BuildObject` fails it throws "Failed to build control!" (`:319-320`; `ControlData` leaks).
- **Preconditions:** menu (`:295-296`).
- **Threading & blocking:** script thread; one list walk.
- **Side effects:** none.
- **Game internals:** `p_D2WIN_FirstControl`; `Control.pNext/dwType/dwPos*/dwSize*`.
- **Quirks / bugs:** the OOB write above. Matching semantics are those of [`findControl`](#findcontrol-matching).

### `getControls()`

Returns an array with one `Control` per entry of the D2WIN control list, in list order.

- **Native:** `my_getControls` at `JSControl.cpp:325`; registered at `JSGlobalFuncs.h:35` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read. There is no filter.
- **Returns:** an array (`:333`, `:350`), or `undefined` when not at the menu (`:326-329`). An element is `null` if `BuildObject` failed (`OBJECT_TO_JSVAL(NULL)`, `:345-347`; `ControlData` leaks).
- **Preconditions:** menu.
- **Threading & blocking:** script thread. It walks `*p_D2WIN_FirstControl → pNext` (`:336`) with no lock while the game thread may mutate the list. The array is rooted with `JS_AddRoot` for the duration (`:335`, `:351`).
- **Side effects:** none.
- **Game internals:** `p_D2WIN_FirstControl`, `Control.pNext`.
- **Quirks / bugs:** elements whose key is not unique all re-resolve to the first such control (see Identity). Not documented in the legacy docs.

### `Control.prototype.getNext()`

Rebinds **this same object** to the control that follows it in the D2WIN list.

- **Native:** `control_getNext` at `JSControl.cpp:154`; registered at `JSControl.h:65` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `this` (`:176`) after copying `pNext`'s type and geometry into its `ControlData` (`:169-175`). `false` if the current control can't be resolved or has no `pNext` (`:182`). (unset) when not at the menu or the private is NULL (`:155-160`).
- **Preconditions:** menu.
- **Threading & blocking:** script thread; one list walk.
- **Side effects:** mutates the receiver. `var b = a.getNext()` makes `a === b`, and both now denote the next control. The `pNext` successor is taken from the *first* control matching the old key, which may not be the control this object came from.
- **Game internals:** `Control.pNext` (+0x3C).
- **Quirks / bugs:** iteration can loop or skip when keys are duplicated.

### `Control.prototype.click([x, y])`

Posts a left click at the control's centre, or at the given absolute client coordinates.

- **Native:** `control_click` at `JSControl.cpp:188`; registered at `JSControl.h:65` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** `click()` clicks the centre. `click(x, y)` is used only if `argc > 1` and **both** are int jsvals (`:204-209`, `JS_ValueToECMAUint32`). The coordinates are absolute window client coordinates, not relative to the control, and need not lie inside it. Other shapes fall back to the centre silently. The values round-trip `uint32 → int` into `clickControl`, where `-1` still means "centre" per axis (`Control.cpp:118-121`), so `click(-1, 300)` clicks the centre x at y = 300.
- **Returns:** `0` if the control can't be resolved (`:197-200`); otherwise (unset) (`:211-213`). Also (unset) when not at the menu.
- **Preconditions:** menu.
- **Threading & blocking:** script thread; 300 ms of `Sleep` inside `clickControl`.
- **Side effects:** `WM_LBUTTONDOWN` + `WM_LBUTTONUP` posted to the game window. See [`clickControl`](#input-synthesis-clickcontrol).
- **Game internals:** `D2GFX_GetHwnd`.
- **Quirks / bugs:** the result of `clickControl` is discarded. There is no way to know whether the game acted on the click.

### `Control.prototype.setText(text)`

Writes `text` into the resolved control with the game's own setter.

- **Native:** `control_setText` at `JSControl.cpp:216`; registered at `JSControl.h:66` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:** the first argument must be a string (`JSVAL_IS_STRING`), else (unset) with no effect (`:230-231`). `argc < 0` is never true, so `setText()` reads `argv[0]` (argc unchecked, within the declared arity).
- **Returns:** `0` if the control can't be resolved (`:225-228`); otherwise (unset).
- **Preconditions:** menu.
- **Threading & blocking:** script thread; calls `D2WIN_SetControlText` directly (`:237`), unsynchronised with the game thread.
- **Side effects:** modifies the control's text buffer in game memory.
- **Game internals:** `D2WIN_SetControlText` (`D2Ptrs.h:436`, `__fastcall`, VA `0x4FF5A0`).
- **Quirks / bugs:** unlike the `text` setter, there is **no type check**. It can be applied to buttons, textboxes or images, with unknown effect on non-edit controls.

### `Control.prototype.getText()`

Returns the rows of a textbox (type 4) control.

- **Native:** `control_getText` at `JSControl.cpp:241`; registered at `JSControl.h:66` (declared arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none read.
- **Returns:** `undefined` (`:242`) when not at the menu, when the private is NULL (`:246-248`), when `dwType != 4`, or when there is no `pFirstText` (`:256-257`). `0` when the control can't be resolved (`:251-254`). Otherwise an array (`:259-260`). For each `ControlText` row (`pFirstText → pNext`), rows whose `wText[0]` pointer is NULL are skipped (`:265-266`). A row with only `wText[0]` becomes a string. A row with `wText[1]` set becomes a nested array of columns 0–4, *sparse* where a column pointer is NULL (`:268-279`).
- **Preconditions:** menu.
- **Threading & blocking:** script thread; walks the game's `ControlText` list unlocked.
- **Side effects:** none.
- **Game internals:** `Control.pFirstText` (+0x48); `ControlText.wText[5]`, `pNext` (+0x1C) (`D2Structs.h:124-130`).
- **Quirks / bugs:** row indices in the result are compacted, so skipped rows shift later ones.

---

## Internals

### Client-state gate

`ClientState()` (`D2Helpers.cpp:125-147`) calls `D2CLIENT_GetPlayerUnit()` and reads `*p_D2WIN_FirstControl` on **every** `findControl`, `clickControl`, `SetControlText` and `OOG_*` call (`Control.cpp:8`, `:25`, `:114`, `:180`, `:231`, `:240`, `:320`, `:435`, `:549`).

### `findControl` matching

Two overloads (`Control.h:6-7`):

- `findControl(int Type, int LocaleID, int Disabled, int PosX, int PosY, int SizeX, int SizeY)` (`Control.cpp:7`). If `LocaleID >= 0`: `_wcsdup(D2LANG_GetLocaleText((WORD)LocaleID))`, delegates to the text overload, then frees (`:12-19`). If `LocaleID < 0` it **returns NULL** (`:21`).
- `findControl(int Type, const wchar_t* Text, int Disabled, int PosX, int PosY, int SizeX, int SizeY)` (`Control.cpp:24`). If every criterion is **exactly** `-1` and `Text == NULL` it returns `*p_D2WIN_FirstControl` (`:28-29`). Otherwise it walks `pNext` from the head (`:33`) and returns the **first** control where each criterion that is not a wildcard holds and at least one criterion matched. Every numeric test is `>= 0`, so any negative value is a wildcard inside the loop; but a call whose only "criteria" are negative values other than `-1` (e.g. `getControl(-2)`) skips the shortcut, matches nothing (`bFound` stays FALSE) and returns NULL:
  - `Type >= 0`: `dwType == Type` (`:34-39`).
  - `Disabled >= 0`: `dwDisabled == Disabled`, and additionally, for buttons, `unkState != 1` (`:41-50`; `unkState` +0x44 "1 when greyed", `D2Structs.h:151`).
  - `PosX/PosY/SizeX/SizeY >= 0`: exact equality on `dwPosX/dwPosY/dwSizeX/dwSizeY` (`:52-78`).
  - `Text != NULL` and `dwType == CONTROL_BUTTON`: `wcscmp(wText2, Text) == 0` (`:80-89`). The `!pControl->wText2` "abort search" check (`:81-82`) is dead, because `wText2` is an inline array.
  - `Text != NULL` and `dwType == CONTROL_TEXTBOX`: requires `pFirstText && pFirstText->wText[0]`, then **`wcsstr(Text, pFirstText->wText[0])`**. The haystack is the search text, so the control's first row must be a *substring of the search text*. An empty first row matches anything (`:91-105`).
  - `Text != NULL` with any other `dwType`: the text criterion is ignored.

Coordinates are exact. There is no tolerance and no resolution scaling. The hard-coded probes imply an 800×600 menu layout (e.g. the full-width textbox `T(*, 0, 180, 800, 100)`, `Control.cpp:166`, and the bottom-row buttons at y = 572), but no code checks the resolution.

### Input synthesis: `clickControl`

`bool clickControl(Control* pControl, int x = -1, int y = -1)` (`Control.cpp:113`, default args `Control.h:8`):

1. Returns false if not at the menu or if `pControl` is NULL (`:114-115`, `:131`).
2. `x = dwPosX + dwSizeX/2` if `x == -1`; `y = dwPosY - dwSizeY/2` if `y == -1` (`:118-121`). Unsigned arithmetic.
3. `Sleep(100)`, `SendMouseClick(x, y, 0)`, `Sleep(100)`, `SendMouseClick(x, y, 1)`, `Sleep(100)` (`:123-127`), then returns true.

`SendMouseClick` (`D2Helpers.cpp:305`) does `PostMessage(D2GFX_GetHwnd(), WM_LBUTTONDOWN|WM_LBUTTONUP, 0, x + (y << 16))` (`:310`, `:313`). There is no `WM_MOUSEMOVE`, no `MK_LBUTTON` in `wParam`, and no `SetCursorPos`. Messages are queued to the game's window thread, which subclasses the window with `GameEventHandler` (passes mouse messages through, `D2Handlers.cpp:176-203`). The `WH_MOUSE` hook (`D2Handlers.cpp:296`, installed at `Helpers.cpp:187`) is the place where `Vars.bBlockMouse` swallows input (`D2Handlers.cpp:305`). `login` sets that flag while relying on its own posted clicks still reaching the game (see [Open questions](#open-questions)). `true` means "posted", not "handled". The same primitive backs the JS `sendClick` ([globals-core.md](globals-core.md#sendclickx-y)).

### Text entry: `SetControlText` / `D2WIN_SetControlText`

`SetControlText(Control*, const wchar_t*)` (`Control.cpp:230-237`) checks the menu state and non-NULL arguments, then calls `D2WIN_SetControlText(pControl, Text)`. That is `FUNCPTR(D2WIN, SetControlText, void* __fastcall, (Control*, const wchar_t*), 0xFF5A0)` (`D2Ptrs.h:436`): a direct call into game code on the **script thread**. `Control.text = …` and `Control.setText()` call `D2WIN_SetControlText` directly (`JSControl.cpp:117`, `:237`) after their own menu check. There is no keyboard synthesis (no `WM_CHAR`/`WM_KEYDOWN`), so per-keystroke edit-box input handling is not exercised; whether `D2WIN_SetControlText` itself runs the box's callback (cf. the unused `D2WIN_SetEditBoxCallback`, `D2Ptrs.h:451`) or enforces a length limit is not visible in source. D2BS itself length-checks only game name and password (≤ 15, `JSMenu.cpp:79`, `:103`, `Control.cpp:439`, `:553`); `Control.text`/`setText` and the login username/password/IP writes pass any length.

### `OOG_SelectCharacter`

`BOOL OOG_SelectCharacter(const wchar_t* szCharacter)` (`Control.cpp:179-228`):

1. Not at the menu → FALSE (`:180-181`).
2. Start at `findControl(CONTROL_TEXTBOX, NULL, -1, 237, 178, 72, 93)` (`:185`) and walk `pNext` **to the end of the list** (`:188`, `:225`). Any type is visited.
3. For each textbox with at least 2 rows, the 2nd row's `wText[0]` is the candidate name (`:189-192`). If that pointer is NULL it **returns FALSE** (aborts) (`:195-196`).
4. Case-insensitive comparison (lower-case copies, equal length plus `wcsstr`, i.e. equality) (`:198-203`).
5. On match: `clickControl(slot)` (centre), then `clickControl(B(*, 627, 572, 128, 35))` (OK). TRUE if both were posted, FALSE if OK is missing (`:206-218`).

The start control `(237, 178, 72, 93)` differs from the slot geometry that `OOG_GetLocation` uses to detect character select `(37, 178, 200, 92)` (`Control.cpp:364`). Slots that precede the start control in list order are never examined. Only on-screen slots are searched (no scrolling).

### `OOG_SelectGateway`

`BOOL OOG_SelectGateway(const wchar_t* szGateway, size_t strSize)` (`Control.cpp:239-317`). `strSize` is unused.

1. Not at the menu → FALSE. A gateway containing `"ERROR"` (the INI default; case-sensitive `wcsstr`) → FALSE (`:240-244`).
2. Gateway button `B(*, 264, 391, 272, 25)` (`:246`). Missing → FALSE (`:316`). The `pControl->wText2` test at `:249` is always true (inline array).
3. If the lower-cased button text contains the lower-cased gateway → TRUE (`:249-259`). An empty `gateway=` value is a substring of anything, so it always takes this branch and never changes the gateway.
4. Otherwise it clicks the button to open the list (`:264`) and finds list `T(*, 257, 500, 292, 160)` (`:271`). It takes the first row whose lower-cased `wText[0]` contains the gateway (`:273-293`) and clicks at `(centre-x, 344 + index*24 + 12)` (`:296`).
5. It clicks OK `B(*, 281, 538, 96, 32)` (`:306-311`) and returns TRUE, **even if the gateway was not in the list** or the list had not opened yet (300 ms after the click).

**Double free:** on the found path `wzGate` is freed at `:286`, then again at `:303`, or at `:297` if the click failed. This is heap corruption on every successful gateway change. `_wcsdup(cText->wText[0])` with a NULL row pointer returns NULL, and then the function returns FALSE (`:276-280`).

### `OOG_CreateGame`

`bool OOG_CreateGame(const wchar_t* name, const wchar_t* pass, int difficulty)` (`Control.cpp:434-546`):

1. Not at the menu, NULL arguments, or lengths > 15 → FALSE (`:435-440`).
2. `loc = OOG_GetLocation()` must be 1, 3, 20 or 4 (`:445-447`).
3. **`loc == OOG_DIFFICULTY` (SP/TCP host):** buttons normal `(264, 297)`, nightmare `(264, 340)` and hell `(264, 383)`, all 272×35 (`:451-453`), dereferenced without NULL checks.
   - `difficulty` 0/1/2: requires `dwDisabled == 0x0d`, then clicks (`:456-467`).
   - `difficulty` 3: clicks the first of hell/nightmare/normal whose `dwDisabled != 0x0d` (`:468-479`). That is the **opposite** of the 0x0d = clickable convention used two lines above and in `Profile::login` (`Profile.cpp:186-188`). If all three are `0x0d`, nothing is clicked and the function returns TRUE.
   - Anything else → FALSE. The name and password are unused on this path.
4. **Otherwise (lobby/chat/create):**
   - If not already on Create: click the Create tab `B(*, 533, 469, 120, 20)` (FALSE if missing), then `Sleep(100)` (`:485-490`).
   - If `OOG_GetLocation() == OOG_CREATE` **now** (`:491`):
     - `SetControlText(E(*, 432, 162, 158, 20), name)`, `Sleep(100)`; `SetControlText(E(*, 432, 217, 158, 20), pass)`, `Sleep(100)` (`:493-504`). A missing edit box is ignored (`SetControlText(NULL, …)` is a no-op).
     - Radios normal `(430, 381)`, nightmare `(555, 381)`, hell `(698, 381)`, all 16×16 (`:505-507`), dereferenced without NULL checks. `dwDisabled == 0x4` means unavailable. `difficulty` 0/1/2: FALSE if unavailable. `difficulty` 3: hell, else nightmare, else normal; if all three are `0x4` no radio is clicked and the function still proceeds to Create Game (`:522-533`). Any other `difficulty` → FALSE (`:534-535`), after the tab click and both text writes have already happened.
     - Click Create Game `B(*, 594, 433, 172, 32)` (`:539-541`).
   - If the tab has not switched yet, **returns TRUE having done nothing** but open the tab.

### `OOG_JoinGame`

`bool OOG_JoinGame(const wchar_t* name, const wchar_t* pass)` (`Control.cpp:548-588`):

1. Not at the menu → FALSE. `wcslen` > 15 → FALSE; there is no NULL check before `wcslen` (`:549-554`).
2. The location must be 1, 3 or 5, computed by up to three separate `OOG_GetLocation()` calls (`:559-560`).
3. If not on Join: click the Join tab `B(*, 652, 469, 120, 20)`, then `Sleep(100)` (`:563-568`).
4. If `OOG_GetLocation() == OOG_JOIN`: set `E(*, 432, 148, 155, 20)` = name and `E(*, 606, 148, 155, 20)` = password, then click Join Game `B(*, 594, 433, 172, 32)` (FALSE if missing) (`:569-585`).
5. Returns TRUE (`:587`). It is silently TRUE if the tab didn't switch.

### `OOG_CreateCharacter`

`BOOL OOG_CreateCharacter(const wchar_t* szCharacter, int type, bool hardcore, bool ladder)` (`Control.cpp:134-177`). This backs the unexposed `createCharacter`.

1. Requires location 12 (character select with at least one listed character, so not an empty account at 42), name ≤ 15 and `type` 0..6 (`:135`). There is no direct `ClientState()` call; the menu check comes from `OOG_GetLocation()`. `wcslen(szCharacter)` has no NULL check.
2. Clicks "Create New" `B(*, 33, 528, 168, 60)` (`:139-141`).
3. Polls `OOG_GetLocation()` for 29 up to 30 × 100 ms (`:144-146`).
4. Finds the class image `(type 2, locs[type][0..1], 88×184)` and clicks it twice at `locs[type][2..3]`, 500 ms apart (`:148-163`). The class table is amazon, sorceress, necromancer, paladin, barbarian, druid, assassin, with locale ids 4011, 4010, 4009, 4008, 4007, 4012, 4013.
5. Compares `T(*, 0, 180, 800, 100)`'s first row to `D2LANG_GetLocaleText(locs[type][4])`, with a NULL dereference if the textbox is missing (`:166-169`).
6. **Always returns FALSE** (`:176`). Typing the name, the hardcore/ladder checkboxes and the OK click are not implemented (only a comment, `:171-174`).

### Hard-coded UI geometry (all callers)

| Purpose | Probe | Used at |
|---|---|---|
| Main menu: Single Player / Battle.net / Other Multiplayer | `B(*, 264, 324\|366\|433, 272, 35)` | `Profile.cpp:128`, `:132`, `:136` |
| Main menu: gateway button | `B(*, 264, 391, 272, 25)` | `Control.cpp:246` |
| Gateway list / OK | `T(*, 257, 500, 292, 160)`, rows at y = 344 + 24·i + 12; `B(*, 281, 538, 96, 32)` | `Control.cpp:271`, `:296`, `:306` |
| Login: username / password / Log in / Exit | `E(*, 322, 342, 162, 19)`, `E(*, 322, 396, 162, 19)`, `B(*, 264, 484, 272, 35)`, `B("EXIT", 33, 572, 128, 35)` | `Profile.cpp:148`, `:154`, `:160`, `:144` |
| Other MP: Open Battle.net / TCP/IP Game | `B(*, 264, 310, 272, 35)`, `B(*, 264, 350, 272, 35)` | `Profile.cpp:201`, `:205` |
| TCP/IP: Host / Join | `B(*, 265, 206, 272, 35)`, `B(*, 265, 264, 272, 35)` | `Profile.cpp:213`, `:216` |
| Enter IP: edit / OK | `E(*, 300, 268, -1, -1)`, `B(*, 421, 337, 96, 32)` | `Profile.cpp:221`, `:227` |
| Char select: slot scan start / OK / Create New | `T(*, 237, 178, 72, 93)`, `B(*, 627, 572, 128, 35)`, `B(*, 33, 528, 168, 60)` | `Control.cpp:185`, `:211`, `:139` |
| SP difficulty: normal / nightmare / hell | `B(*, 264, 297\|340\|383, 272, 35)` | `Profile.cpp:168-170`, `Control.cpp:451-453` |
| Lobby: Create tab / Join tab | `B(*, 533, 469, 120, 20)`, `B(*, 652, 469, 120, 20)` | `Control.cpp:486`, `:564` |
| Create tab: name / password / radios / Create Game | `E(*, 432, 162, 158, 20)`, `E(*, 432, 217, 158, 20)`, `B(*, 430\|555\|698, 381, 16, 16)`, `B(*, 594, 433, 172, 32)` | `Control.cpp:494`, `:501`, `:505-507`, `:539` |
| Join tab: name / password / Join Game | `E(*, 432, 148, 155, 20)`, `E(*, 606, 148, 155, 20)`, `B(*, 594, 433, 172, 32)` | `Control.cpp:572`, `:577`, `:582` |

### Other consumers of this layer

- `Say()` out of game: if `B(5308, 187, 470, 80, 20)` is present and `B(5102, 351, 337, 96, 32)` is absent (chat screen, no popup), it converts the text with `UnicodeToAnsi(…, CP_ACP)`, `memcpy`s it into `p_D2MULTI_ChatBoxMsg` (`VARPTR char*`, VA `0x77AE40`, `D2Ptrs.h:396`; no length check) and calls `D2MULTI_DoChat()` (`void __fastcall (void)`, VA `0x442810`, `D2Ptrs.h:389`) on the script thread (`Core.cpp:124-128`). JS entry point: [`say`](globals-game.md#sayvalues).
- `InitHooks` with `StartAtMenu=true`: `clickControl(*p_D2WIN_FirstControl)` once at startup (`Helpers.cpp:198-199`), the same "click the first control" trick as the splash handling in `login`.
- A commented-out OOG game-print path in `D2Handlers.cpp:384`.

---

## Game internals touched

All are resolved against `Game.exe` (image base 0x400000); RVA = VA − 0x400000. See [../memory/offsets.md](../memory/offsets.md) and [../memory/structs.md](../memory/structs.md).

| Identifier | Kind / prototype | VA | Declared | Used by |
|---|---|---|---|---|
| `p_D2WIN_FirstControl` | `VARPTR Control*` (head of the D2WIN control list) | `0x7D55BC` | `D2Ptrs.h:462` | `ClientState`, `findControl`, `getControls`, `login` (splash) |
| `D2WIN_SetControlText` | `void* __fastcall (Control*, const wchar_t*)` | `0x4FF5A0` | `D2Ptrs.h:436` | `SetControlText`, `Control.text=`, `Control.setText` |
| `D2LANG_GetLocaleText` | `wchar_t* __fastcall (WORD)` | `0x524A30` | `D2Ptrs.h:418` | `findControl(…, LocaleID, …)`, `OOG_CreateCharacter` |
| `D2GFX_GetHwnd` | `HWND __stdcall (void)` | `0x4F59A0` | `D2Ptrs.h:382` | `SendMouseClick` |
| `D2CLIENT_GetPlayerUnit` | `UnitAny* __stdcall (void)` | `0x463DD0` | `D2Ptrs.h:122` | `ClientState` |
| `p_D2WIN_FocusedControl` | `VARPTR Control*` | `0x7D55CC` | `D2Ptrs.h:463` | **unused** ("we ought to use it") |
| `p_D2MULTI_GameListControl`, `p_D2MULTI_ChatInputBox` | `VARPTR` | `0x798BC0`, `0x798C80` | `D2Ptrs.h:397`, `:464` | **unused** in source |
| `D2WIN_DestroyEditBox`, `D2WIN_DestroyControl`, `D2WIN_SetEditBoxCallback`, `D2WIN_SetEditBoxProc`, `D2WIN_SelectEditBoxText` | FUNCPTRs | see offsets.md | `D2Ptrs.h:449-455` | **unused** |

`struct Control` (`D2Structs.h:132`), compiled 32-bit layout (no `#pragma pack` before `D2Structs.h:170`):

| Offset | Field | Used here as |
|---|---|---|
| 0x00 | `dwType` | type criterion, `type` |
| 0x08 | `dwDisabled` | `state`, `disabled`, Disabled criterion, difficulty availability (`0x0d`, `0x4`) |
| 0x0C / 0x10 / 0x14 / 0x18 | `dwPosX`, `dwPosY`, `dwSizeX`, `dwSizeY` | identity key, click centre |
| 0x3C | `pNext` | list walk |
| 0x44 | `unkState` | button greyed check in `findControl` |
| 0x48 | `pFirstText` (`ControlText*`) | textbox rows |
| 0x54 / 0x58 | `dwSelectEnd`, `dwSelectStart` | `selectend`, `selectstart` |
| 0x5C | `wText[256]` (edit-box arm of the union) | `text` (non-button) |
| 0x64 | `wText2[256]` (button arm; **source comment says 0x6C**, `D2Structs.h:165`) | button text matching, `text` (type 6) |
| 0x25C | `dwCursorPos` | `cursorpos` |
| 0x260 | `dwIsCloaked` (33 = password) | `password`, `text` suppression |

`sizeof(Control)` = 0x264 as compiled. `ControlText` (`D2Structs.h:124-130`): `wText[5]` (0x00), `dwColor` (0x14), `dwAlign` (0x18), `pNext` (0x1C), size 0x20.

---

## Facts for an RPC replacement

- **Whole OOG model = poll + probe.** There is no event for screen changes. Every query walks the live D2WIN list and matches hard-coded geometry and locale ids (`Control.cpp:319-432`). A networked API needs either the same polling or a hook on D2WIN screen construction (no such hook exists today; see [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md)). The one existing per-frame menu callback on the game thread is the OOG draw intercept (`Patch.h:35` → `GameDrawOOG`, `D2Handlers.cpp:421`), which already gates on `ClientState() == ClientStateMenu` (`D2Handlers.cpp:423`). It is the natural place to run probes, clicks and `D2WIN_SetControlText` on the UI thread instead of on a foreign thread.
- **Control handles are not stable.** The only identity is `(type, x, y, w, h)`, re-resolved per call. An RPC handle design should either keep that key with "first match" semantics or address controls by list index or pointer with explicit invalidation.
- **Actions are fire-and-forget.** Clicks are `PostMessage` with fixed 100 ms sleeps. Text entry calls game code on a foreign thread. No function verifies the resulting screen. `login` is the only closed loop, and its exit conditions are incomplete (infinite-loop states, no cancellation, timeout counts only waiting states).
- **Long blocking calls with no cancellation**, and input blocked during them (`Vars.bBlockKeys/bBlockMouse`, overwritten on exit).
- **Credentials live in plaintext** in `d2bs.ini` (`password=`). `addProfile` writes unescaped values. `Profile` hides the password from JS but `login` types it into the game.
- **Thread-safety is absent.** The control list, `Control` fields and `D2WIN_SetControlText` are all touched from script threads without the game-loop lock (`AutoCriticalRoom`, `CriticalSections.h:31`).
- **Several entry points crash the process on bad input:** `createGame`/`joinGame` without a password, `Profile(type, …)`, `login` with an invalid `spdifficulty`, `selectCharacter` with a long `character`, `getControl` with more than 5 int arguments, long profile names, and long `addProfile` values. An RPC layer must validate before calling the existing C++.

---

## Defects and quirks

| # | Defect | Where |
|---|---|---|
| 1 | `OOG_SelectGateway` double-frees `wzGate` on the success path | `Control.cpp:286` + `:303` (or `:297`) |
| 2 | `Profile` explicit-field constructors use `wcscpy_s(dst, wcslen(dst), src)` on uninitialised buffers, which hits the invalid-parameter handler (process termination) or garbage | `Profile.h:27-30` |
| 3 | `login()` leaves the `const char*` thrown by `Profile::init` ("Invalid difficulty.") uncaught; it propagates through SpiderMonkey | `JSMenu.cpp:33`, `Profile.cpp:33-34` |
| 4 | `selectCharacter` passes a 516-wchar size for a 24-wchar buffer, a stack overflow | `JSMenu.cpp:52-54` |
| 5 | `createGame`/`joinGame` with an omitted password do `JS_GetStringCharsZ(JSVAL_TO_STRING(undefined))`, a NULL `JSString*` | `JSMenu.cpp:74`, `:99` |
| 6 | `getControl` with more than 5 int arguments writes through `args[i]` out of bounds | `JSControl.cpp:299-303` |
| 7 | `state`/`cursorpos` setters use `memset` on a DWORD, so the value byte is replicated | `JSControl.cpp:128`, `:141` |
| 8 | The `disabled` setter is unreachable (`JSPROP_READONLY`) | `JSControl.h:62`, `js32.h:100` |
| 9 | `OOG_CreateGame` difficulty 3 on the SP screen uses inverted `0x0d` logic | `Control.cpp:469-478` |
| 10 | `login` `OOG_DIFFICULTY` case falls through into `OOG_OTHER_MULTIPLAYER` (missing `break`) | `Profile.cpp:196-198` |
| 11 | `login` spins forever in several states with input blocked | `Profile.cpp:126-141`, `:198-218` |
| 12 | `login` uses literal `L"EXIT"` (not localised) | `Profile.cpp:144` |
| 13 | NULL dereferences of difficulty buttons/radios and of the class textbox | `Profile.cpp:174-188`, `Control.cpp:457-530`, `:168` |
| 14 | `createGame`/`joinGame` return success when the tab didn't open in time | `Control.cpp:491`, `:569` |
| 15 | `Vars.szProfile != NULL` array tests: dead error paths ("Invalid profile specified!", "No active profile!") | `JSMenu.cpp:19`, `JSProfile.cpp:31` |
| 16 | `login(name)` stores the name in `Vars.szProfile` before validation | `JSMenu.cpp:25` |
| 17 | `Profile.prototype.*` / `Profile.prototype.login()` dereference a NULL private | `JSProfile.cpp:97-99`, `:119-126` |
| 18 | `Profile.ip` and `.username` alias (union). TCP/IP join profiles take the IP from the INI `username` key. | `Profile.h:11-14`, `Profile.cpp:21` |
| 19 | `MaxCharSelectTime` is read and exposed but unused | `Profile.cpp:26`, `:29` |
| 20 | `OOG_SelectCharacter` starts scanning at `(237,178,72,93)`, while detection uses `(37,178,200,92)` | `Control.cpp:185`, `:364` |
| 21 | `findControl` textbox text match is reversed (control row ⊂ search text); an empty row matches all | `Control.cpp:95` |
| 22 | `Control` getters/setters return `JS_FALSE` with no exception when the control is gone or the client is not at the menu, terminating the JS | `JSControl.cpp:18-27`, `:98-107` |
| 23 | `joinGame` conversion error mentions `createGame` | `JSMenu.cpp:95` |
| 24 | `addProfile` never updates existing profiles; values unescaped; `spDifficulty` via unchecked `JSVAL_TO_INT` | `JSMenu.cpp:135`, `:143-149` |
| 25 | `Control.state` getter underflows for `dwDisabled < 2` | `JSControl.cpp:66` |
| 26 | `ProfileType` is defined but not registered | `JSGlobalClasses.cpp:116`, `:184` |
| 27 | `wText2` compiled at +0x64, comment says 0x6C | `D2Structs.h:164-165` |
| 28 | `OOG_CHARACTOR_CHANGE_REALM` (37) is never produced | `Constants.h:113` |
| 29 | `Profile.prototype.login()` has no menu check and forces `blockKeys/blockMouse` FALSE even in game | `JSProfile.cpp:92-103`, `Profile.cpp:294` |
| 30 | DDE `XTYP_POKE` profile switch converts the item buffer before `DdeGetData` fills it, so it always passes `""` and never switches | `dde.cpp:10-17` |
| 31 | `OOG_SelectGateway` treats an empty gateway as matching any label (never switches); `"ERROR"` test is case-sensitive | `Control.cpp:243`, `:255` |
| 32 | `OOG_CreateGame` with an invalid difficulty fails only after typing name/password; difficulty 3 with all radios unavailable clicks Create Game with no radio | `Control.cpp:491-541` |
| 33 | `login`'s `OOG_ENTER_IP_ADDRESS` branch types the `username` default `"ERROR"` as the IP when the key is missing | `Profile.cpp:21`, `:220-223` |
| 34 | `OOG_CreateCharacter` requires location 12, so even if finished it could not create the first character of an empty account | `Control.cpp:135` |

---

## Legacy-doc discrepancies

| Topic | Legacy docs | Code |
|---|---|---|
| `ProfileType` | `doc/ProfileType.h:3-12`: enum `singlePlayer` … `tcpIpJoin` starting at 0; `JSProfile.cpp:11-15` comments use `ProfileType.*` | Not registered: absent from the active `global_classes[]` (`JSGlobalClasses.cpp:143-170`). Values start at 1 (`Profile.h:6`). |
| `Profile(pt, charName, ip)` | `doc/Profile.h:47-56`: "handles singlePlayer and tcpIpHost types" | It is the `tcpIpJoin` shape (`JSProfile.cpp:72-76`), and all explicit shapes are broken (`Profile.h:27-30`). |
| `Profile.difficulty` | `doc/Profile.h:84-86`: 0–2 | 0–3 (3 = hardest available, `Profile.cpp:33`, `:185`) |
| `Profile.maxCharacterSelectTime` | "time to wait for the characters to load" (`doc/Profile.h:92-94`) | unused |
| `login` errors | `doc/globalFuncs.h:1130-1261`: "invalid character name", "Failed to click the 'TCP/IP' button?" | "Invalid character name", "Failed to click the 'TCP/IP Game' button?". Undocumented: "login time out", "Failed to click ANY difficulty button?", "Failed to join Host IP Address", and the wrapper's "Profile does not exist!" / "Could not get profile!". The legacy list also does not say which ~16 codes produce "Unhandled login location". |
| `selectCharacter` | "Keeps all details except the character name from old profile" (`doc/globalFuncs.h:1263-1272`) | Reads only `character`, clicks; no profile state is kept or changed (`JSMenu.cpp:43-59`). |
| `createGame` / `joinGame` | `void`, `pass = ""` default (`doc/globalFuncs.h:1285`, `:1295`) | Return `null`, throw on failure; omitting `pass` is expected to crash (`JSMenu.cpp:74`, `:99`). |
| `addProfile` | `doc/globalFuncs.h:1297-1318`: "charname (case sensitive)". api.html: 6 arguments, no difficulty. | Matching is case-insensitive (`Control.cpp:200-203`). 6 or 7 arguments (`JSMenu.cpp:118`). |
| `profileExists` | api.html documents a global `profileExists(name)` | No such global (only C++ `Profile::ProfileExists`, `Profile.cpp:59`) |
| `getLocation` | api.html lists 0–43; 37 = "Switch Realm" | 44 = `OOG_UNABLE_TO_CONNECT_TCPIP` exists (`Constants.h:120`). 37 is never returned. Out of game it returns `null`. |
| `getControls` | absent from `doc/` and api.html | registered (`JSGlobalFuncs.h:35`) |
| `getControl` | `doc/globalFuncs.h:729-730`: `int32_t` parameters, returns a `Control` | only int-tagged jsvals are honoured (doubles/strings silently become wildcards); returns `undefined` when nothing matches or not at the menu (`JSControl.cpp:293-308`) |
| `login()` profile source | "Loads the default (either from config or copydata or DDE) profile" (`doc/globalFuncs.h:1130-1132`) | `Vars.szProfile` comes from `-profile`, `WM_COPYDATA 0x31337` or a prior `login(name)`; the DDE path never delivers a name (`dde.cpp:10-17`), and there is no `[settings]` default-profile key read by `login` |
| `Control.cursorPos` | `doc/Control.h:98` | property is `cursorpos` (`JSControl.h:59`) |
| `Control.disabled` | "Whether the Control is disabled" (`doc/Control.h:112-114`) | raw `dwDisabled` value; read-only despite a setter |
| `Control.getNext` | "Gets the next Control" (`doc/Control.h:6-9`) | mutates and returns `this`, or `false` |
| `Control.click(x, y)` | `uint32_t` coordinates (`doc/Control.h:15-22`) | both must be int jsvals, else the centre is clicked (`JSControl.cpp:204`) |
| `d2bs.ini` sample | `resources/d2bs.ini:52-54`: modes "single, battle.net, other multiplayer"; `spdifficulty` 0–2 | Only the first letter matters (`s/b/o/h/j`). "other multiplayer" → Open Battle.net. TCP/IP needs `h`/`j`. `spdifficulty` 0–3. |

---

## Open questions

1. **Argument padding.** Does this SpiderMonkey build pad native `argv` up to the declared `nargs` with `undefined`? This decides whether `createGame(name)` / `joinGame(name)` crash deterministically (NULL `JSString*`) or read stale stack. It also affects `login()` with no arguments. The shipped headers don't say; see also [globals-core.md § Open questions](globals-core.md#open-questions). ([../spidermonkey/embedding.md § 4.3](../spidermonkey/embedding.md#43-how-natives-receive-arguments-return-values-and-report-errors) asserts padding without a citation; this page does not rely on it.)
2. **`JS_ConvertArguments` `W` write-back.** `my_createGame`/`my_joinGame` (and the unexposed `my_createCharacter`) re-read `argv` as strings after `"W"` conversion. That is only safe if the engine stores the converted string back into `argv`, and the headers don't show it.
3. **(unset) return value.** For `click`, `setText` and `getNext`, is it the callee function object or something else?
4. **Button-text offset.** Is the button label at +0x64 (compiled `wText2`) or +0x6C (source comment) in 1.14d? Button-text probes in `OOG_GetLocation` depend on it.
5. **`dwDisabled` / `unkState` semantics.** Only `0x0d` (clickable SP difficulty) and `0x4` (unavailable create radio) are implied by code. The `state = dwDisabled − 2` mapping is unexplained.
6. **D2WIN list order and `OOG_SelectCharacter`'s start control** `(237, 178, 72, 93)`: does it precede all character slots in 1.14d?
7. **Posted clicks vs `bBlockMouse`.** `login` blocks mouse input via the `WH_MOUSE` hook and still expects its `PostMessage` clicks to work. This implies posted messages bypass the hook (Win32 behaviour), which source alone cannot confirm.
8. **Thread safety of `D2WIN_SetControlText`** from a non-UI thread, and its behaviour on non-edit controls (`Control.setText` allows any type).
9. **Locale ids** 5116, 5118, 5119, 5138, 5139, 5159, 5161, 5181, 5200, 5226, 5243, 5288, 5347, 5351, 11065, 11066, 11097, 11162, 21882 are interpreted only through the location they map to. Their actual strings need the game's string tables.
10. **Coordinates for 1.14d.** `Control.cpp`/`Profile.cpp` carry no "Updated 1.14d" annotations. Whether every hard-coded geometry still matches 1.14d menus can't be confirmed from source.
11. **Contents at `Control+0x5C` / `+0x260`** for textbox (type 4) and other non-edit controls, which `text`/`password` read for any type.
12. **Hit-testing of posted clicks.** `SendMouseClick` posts `WM_LBUTTONDOWN/UP` with the target in `lParam` but never moves the cursor (`D2Helpers.cpp:305-313`). Whether D2WIN hit-tests menu controls from the message `lParam` or from the real cursor position is not visible in source; every click in this page depends on the former.
13. **List-mutation timing.** Whether the game thread frees or rebuilds `Control` objects between two script-thread probes (the TOCTOU window behind every `findControl` → use sequence) cannot be determined from source.

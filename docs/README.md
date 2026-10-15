# D2BS documentation (`docs/`)

Scope: the entry point for `docs/`. It states what the tree is for, which game and engine builds it describes and the evidence for them, and what every file under `docs/` contains. It gives reading orders for three tasks (RPC design, reverse engineering, removing SpiderMonkey), the conventions all pages share, how the pages were produced and checked, how to regenerate the generated parts, how the tree relates to the legacy `doc/` folder, the root `README.md` and `resources/api.html`, and the caveats that apply to everything here. This page adds no new facts. Each fact is cited to the C++ as `File.cpp:LINE` or linked to the page that establishes it.

## Contents

1. [Purpose](#1-purpose)
2. [Target versions](#2-target-versions)
3. [Doc map](#3-doc-map)
4. [Reading orders](#4-reading-orders)
5. [Conventions](#5-conventions)
6. [How these docs were produced and verified](#6-how-these-docs-were-produced-and-verified)
7. [Regenerating the generated parts](#7-regenerating-the-generated-parts)
8. [Relationship to the legacy documentation](#8-relationship-to-the-legacy-documentation)
9. [Caveats](#9-caveats)

---

## 1. Purpose

These docs prepare the ground for the owner's planned next-generation D2BS: a simpler DLL in which the embedded SpiderMonkey engine is removed and the JavaScript API is replaced by an external, networked RPC control API. The pages describe today's D2BS 1.6.4U exactly as the C++ in this repository implements it, defects included. That covers the process and thread model, every JS-visible name, the engine embedding and its coupling, and every Game.exe address, patch, call stub and struct the code depends on. With that in hand, an RPC surface can be designed from facts and the game-facing native layer can be reused or rewritten knowingly. The pages do not design the RPC. Where design choices follow from the facts, [rpc-considerations.md](rpc-considerations.md) and [NEXT_STEPS.md](NEXT_STEPS.md) list them as options with trade-offs, not as decisions.

## 2. Target versions

| Component | Version | Evidence |
|---|---|---|
| D2BS | 1.6.4U | `D2BS_VERSION L"1.6.4U"` (`D2BS.h:10`); `FILEVERSION 1,6,4,0` (`version.rc:54`); [architecture.md §1.1](architecture.md#11-what-gets-loaded) |
| Game | Diablo II 1.14d, where all game code is in `Game.exe` | `version()` with an argument prints "… for Diablo II 1.14d." (`JSCore.cpp:303`). `GetDllOffset()` ignores its DLL name and adds the offset to `GetModuleHandle(NULL)` (`Offset.cpp:21-28`), so the legacy module names (`D2Client`, `D2Common`, …) only label address ranges inside Game.exe ([memory/README.md §2](memory/README.md#2-one-image-legacy-module-names)). 225 of the 266 address rows carry the `ported-1.14d` flag ([offsets.md §2](memory/offsets.md#2-summary)). |
| Image base | `0x400000`, so VA = `0x400000` + RVA | All 227 `-BASE` VA comments in `D2Ptrs.h`/`Patch.h` equal `0x400000 + RVA` ([memory/README.md §1](memory/README.md#1-summary)). The absolute literals in `MPQStats.cpp` and `JSUnit.cpp:453-458` are written as `0x400000`-based VAs and rebased onto `GetModuleHandle(NULL)` at run time (`MPQStats.cpp:45`, `MPQStats.cpp:50`). The Ghidra importer checks it (`EXPECTED_IMAGE_BASE` in [`ghidra/D2BSImport.java`](ghidra/D2BSImport.java)). Whether the image is ever relocated is open: [OQ-MEM-04](OPEN_QUESTIONS.md#oq-mem-04). |
| JS engine | SpiderMonkey from a `mozilla-release` ~22 ("moz22") checkout, `JS_VERSION 185`, non-threadsafe build | `#define JS_VERSION 185` (`dependencies/include/jsversion.h:14`). Object paths `c:\moz22\mozilla-release\js\src\build-unsafe\*.obj` (`dependencies/libs/release/js_static.lib.desc`). `/* #undef JS_THREADSAFE */` (`dependencies/include/js-config.h:16`). Post-1.8.5 API shape: the two-argument `JS_NewRuntime` (`dependencies/include/jsapi.h:1799-1800`) and the `JSOPTION_ION`/`JSOPTION_ASMJS` bits (`dependencies/include/jsapi.h:1996-2012`). The "JavaScript-C 1.8.5+" implementation string is not the real version. Full evidence table: [embedding.md §1.1](spidermonkey/embedding.md#11-which-spidermonkey). |
| Source revision described | `f4b99bb` (2021-04-05, "update version, optimize walk pathing") | The last commit that touches anything outside `docs/`. The documentation commits after it change only `docs/`, so every `File:LINE` citation is valid for `f4b99bb` and for those commits. A later source change invalidates them ([§5](#5-conventions)). |

## 3. Doc map

Kind: **hand** = authored (by the agents of [§6](#6-how-these-docs-were-produced-and-verified)) rather than produced by a generator, **gen** = produced by a generator in this repository, **hand+gen** = authored with generated regions, **hand+tables** = authored with tables produced by one-off scripts that are *not* in the repository ([§7.2](#72-what-has-no-generator-in-the-repository)), **tool** = a generator script ([§7.1](#71-commands)).

### Top level

| File | Kind | What it is |
|---|---|---|
| [README.md](README.md) | hand | This page. |
| [architecture.md](architecture.md) | hand | System picture: loading modes and the start-up/shutdown sequence, thread inventory and the game lock, every `Vars` field and lock, `d2bs.ini` keys and command-line switches, the console, existing external control surfaces (`WM_COPYDATA`, DDE), the client-state model, logging and crash handling, build and repository layout. |
| [rpc-considerations.md](rpc-considerations.md) | hand | Synthesis for the RPC architect: API census by category, thread and lock context, blocking semantics, object identity, event streams, control surfaces, SpiderMonkey coupling hotspots, game-internals dependencies, defects an RPC layer would inherit. Options are trade-offs only. |
| [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) | hand | Every question the source cannot settle: 107 entries with stable ids `OQ-<CAT>-<nn>` in 12 categories. Each entry has its RPC impact, what is known and how to settle it. Appendix A holds questions closed during triage, Appendix C the binutils checks of the bundled binaries. |
| [NEXT_STEPS.md](NEXT_STEPS.md) | hand | Planning aid made only of suggestions: validation before design, a possible layer decomposition, RPC surface and transport options, a migration path, testing and tooling, risks. |

### `js-api/`: the JS surface that the RPC replaces

| File | Kind | What it is |
|---|---|---|
| [js-api/README.md](js-api/README.md) | hand+tables | Index of every registered name (108 globals, 21 classes with all members, `me`, 3 constants, every event), each linked to its entry. Also the entry template, shared tags and citation conventions. |
| [js-api/globals-core.md](js-api/globals-core.md) | hand | `JSCore.cpp` and `JSHash.cpp` globals (48): script control, timers, `delay`, listeners, messaging, console, clipboard and IPC, input, raw packets, hashing. |
| [js-api/globals-game.md](js-api/globals-game.md) | hand | `JSGame.cpp` globals (38) and `DailogLine`: in-game queries and actions, packets D2BS builds, code tables. |
| [js-api/out-of-game.md](js-api/out-of-game.md) | hand | Menu globals, `Control`, `Profile`, `ProfileType`, the login state machine, `Control.cpp`/`Profile.cpp`. |
| [js-api/unit-properties.md](js-api/unit-properties.md) | hand | `Unit` class, handle resolution and lifetime, every `unit_props`/`me_props` property, the global `me`. |
| [js-api/unit-methods.md](js-api/unit-methods.md) | hand | The 25 `Unit` methods, `getUnit`, `getMercHP`, the unit search and iteration model. |
| [js-api/world.md](js-api/world.md) | hand | `Room`, `Area`, `Exit`, `PresetUnit`, `Party` and their getters; the `Map/` pathing subsystem behind `getPath`/`getCollision`. |
| [js-api/screenhooks.md](js-api/screenhooks.md) | hand | `Frame`, `Box`, `Line`, `Text`, `Image`, automap coordinate helpers, drawing thread, click/hover path. |
| [js-api/utility-classes.md](js-api/utility-classes.md) | hand | `File`, `FileTools`, `Folder`, `SQLite`, `DBStatement`, `Socket`, `Sandbox`, `D2BSScript` and the path-security layer. |
| [js-api/events.md](js-api/events.md) | hand | Every `addEventListener` event and the screen-hook callbacks: origin chain, producing thread, delivery, verdicts, payload copying, dispatch mechanics. |

### `spidermonkey/`: the engine that gets removed

| File | Kind | What it is |
|---|---|---|
| [spidermonkey/embedding.md](spidermonkey/embedding.md) | hand | Engine version and dialect, runtime/context/thread topology, global object setup, binding macros, script lifecycle, event and timer integration, GC and rooting, `Sandbox`, locks, removal impact checklist. |
| [spidermonkey/jsapi-inventory.md](spidermonkey/jsapi-inventory.md) | hand+gen | Mechanical inventory of every JSAPI use: identifiers, per-file coupling, logic inside natives, build integration, non-obvious couplings. |
| [spidermonkey/tools/jsapi_inventory.py](spidermonkey/tools/jsapi_inventory.py) | tool | Generator of the inventory's generated blocks (Python 3 stdlib). |

### `memory/`: Game.exe internals the native layer depends on

| File | Kind | What it is |
|---|---|---|
| [memory/README.md](memory/README.md) | hand | Address model: `DLLOFFSET`/`GetDllOffset`, the `FUNCPTR`/`VARPTR`/`ASMPTR` X-macros, when pointers become valid, porting to another game build. |
| [memory/offsets.md](memory/offsets.md) | hand+gen | Every address the code uses (213 `D2Ptrs.h` entries, 31 `Patch.h` sites, absolute VAs) with type, convention, status flags, references and JS entry points; stale/suspect analysis. |
| [memory/patches-and-hooks.md](memory/patches-and-hooks.md) | hand+tables | Patch engine, the `Patches[]`/`Conditional[]` tables, every intercept's register/stack contract, handlers and events, conditional-patch flags, Win32 hooks. |
| [memory/call-stubs.md](memory/call-stubs.md) | hand+tables | Every inline-asm bridge into Game.exe (`*_STUB`, `*_ASM`), alias macros, register/stack contracts, thread and lock context. |
| [memory/structs.md](memory/structs.md) | gen | Every `D2Structs.h` layout computed for MSVC x86, with source-comment discrepancies marked. |

### `ghidra/`: importing the address map into Ghidra

| File | Kind | What it is |
|---|---|---|
| [ghidra/README.md](ghidra/README.md) | hand | What the import does, GUI and headless use, options, re-run behaviour, verification performed, limitations. |
| [ghidra/D2BSImport.java](ghidra/D2BSImport.java) | hand | GhidraScript that applies the types and symbols below to a Game.exe program. It never patches bytes. |
| [ghidra/d2bs_symbols.tsv](ghidra/d2bs_symbols.tsv) | gen | 266 address rows (`FUNC`, `DATA`, `LABEL`, `PATCH`, `COND_PATCH`) with status flags; schema in [ghidra/README.md §2](ghidra/README.md#2-files). |
| [ghidra/d2bs_types.h](ghidra/d2bs_types.h) | gen | `D2Structs.h` turned into preprocessor-free C for Ghidra's `CParser`, keeping the MSVC x86 layouts. |
| [ghidra/tools/gen_symbols.py](ghidra/tools/gen_symbols.py) | tool | Generates the TSV and the generated regions of `memory/offsets.md`, and validates counts and VA comments. |
| [ghidra/tools/gen_types.py](ghidra/tools/gen_types.py) | tool | Generates `d2bs_types.h` and `memory/structs.md` and proves the layouts with clang. |

## 4. Reading orders

### 4.1 For RPC design

1. [rpc-considerations.md, Summary](rpc-considerations.md#summary), then its §1–§6.
2. [architecture.md §2](architecture.md#2-threads-and-the-hooks-that-bridge-them) and [§4.2](architecture.md#42-the-game-lock-cgameloopsection-in-detail): which thread runs what. The game lock is a hand-off, not a mutex.
3. [architecture.md §7](architecture.md#7-external-control-surfaces): what existing managers talk to today.
4. [events.md §1](js-api/events.md#1-summary-table), [§10](js-api/events.md#10-dispatch-mechanics) and [§12](js-api/events.md#12-facts-that-constrain-an-rpc-replacement): subscription and verdict model.
5. [js-api/README.md §1–§2](js-api/README.md#1-at-a-glance), then the per-family pages when you design that family's methods. Start with the identity sections: [unit-properties.md](js-api/unit-properties.md#identity-resolution-and-lifetime), [world.md](js-api/world.md#races-and-thread-safety-summary), [out-of-game.md](js-api/out-of-game.md#facts-for-an-rpc-replacement), [screenhooks.md](js-api/screenhooks.md#facts-relevant-to-an-rpc-replacement).
6. [rpc-considerations.md §8](rpc-considerations.md#8-game-internals-dependencies) and [§9](rpc-considerations.md#9-known-defects-that-matter-for-the-redesign): what each family depends on and what reuse would inherit.
7. [OPEN_QUESTIONS.md summary table](OPEN_QUESTIONS.md#summary-table), THR, EXT and NET first.
8. [NEXT_STEPS.md §4](NEXT_STEPS.md#4-possible-shape-of-the-rpc-surface) and [§5](NEXT_STEPS.md#5-transport-and-protocol-options). [NEXT_STEPS.md §1](NEXT_STEPS.md#1-how-to-use-these-docs) maps each design question to its doc in more detail.

### 4.2 For reverse engineering Game.exe 1.14d

1. [memory/README.md §1–§5](memory/README.md#1-summary): address model and when pointers become valid.
2. [offsets.md §1](memory/offsets.md#1-reading-the-tables) and [§3](memory/offsets.md#3-stale-and-suspect-entries-what-depends-on-them): status flags, then the entries to check first.
3. [patches-and-hooks.md §3–§5](memory/patches-and-hooks.md#3-patch-table): patch sites, expected original bytes (inferred) and each intercept's contract.
4. [call-stubs.md §5](memory/call-stubs.md#5-register-and-stack-contracts): register ABIs that Ghidra's named conventions cannot express.
5. [structs.md, Discrepancy summary](memory/structs.md#discrepancy-summary) and [Partially known structs](memory/structs.md#partially-known-structs).
6. [ghidra/README.md](ghidra/README.md): prerequisites, headless use, [known limitations](ghidra/README.md#12-known-limitations).
7. [OPEN_QUESTIONS.md MEM](OPEN_QUESTIONS.md#1-game-memory--offsets-mem), [STR](OPEN_QUESTIONS.md#2-struct-layouts--field-semantics-str) and [NET](OPEN_QUESTIONS.md#4-network-protocol--packet-paths-net); [NEXT_STEPS.md §2](NEXT_STEPS.md#2-suggested-validation-work-before-design) for a suggested validation pass.
8. [memory/README.md §9](memory/README.md#9-porting-to-another-game-build) if the target build changes.

### 4.3 For removing SpiderMonkey

1. [embedding.md §1](spidermonkey/embedding.md#1-version-and-build) and [§2](spidermonkey/embedding.md#2-runtime--context--thread-topology): which engine, one runtime per script thread.
2. [embedding.md §10](spidermonkey/embedding.md#10-removal-impact-checklist): removal impact checklist.
3. [jsapi-inventory.md §2](spidermonkey/jsapi-inventory.md#2-headline-numbers), [§4](spidermonkey/jsapi-inventory.md#4-per-file-coupling-map) and [§5.2](spidermonkey/jsapi-inventory.md#52-embedded-logic-to-extract-hand-written): size of the coupling and the game logic to lift out of natives first.
4. [jsapi-inventory.md §6](spidermonkey/jsapi-inventory.md#6-build-integration) and [§7](spidermonkey/jsapi-inventory.md#7-non-obvious-couplings): build, `dependencies/`, and couplings that are not plain JSAPI calls (encodings, structured clone, finalizers that own resources).
5. [rpc-considerations.md §7](rpc-considerations.md#7-coupling-hotspots-for-removing-spidermonkey), especially [§7.4](rpc-considerations.md#74-engine-responsibilities-that-need-a-non-js-home): engine duties that need a non-JS home.
6. [embedding.md §5](spidermonkey/embedding.md#5-script-lifecycle), [§6](spidermonkey/embedding.md#6-events-and-timers-integration), [§9](spidermonkey/embedding.md#9-locks-and-synchronisation-objects) and [events.md §10](js-api/events.md#10-dispatch-mechanics): script lifecycle, event pump, timers and locks that ride on the engine.
7. [architecture.md §6](architecture.md#6-console-and-built-in-commands) and [§7.1](architecture.md#71-inbound-wm_copydata): the console and `WM_COPYDATA` `0x1337` both evaluate JS.
8. [NEXT_STEPS.md §3](NEXT_STEPS.md#3-possible-decomposition-of-the-dll-into-layers) and [§6](NEXT_STEPS.md#6-suggested-incremental-migration-path); [OPEN_QUESTIONS.md SM](OPEN_QUESTIONS.md#8-spidermonkey-engine-semantics-sm).

## 5. Conventions

- **Source citations.** `File.cpp:LINE` or `File.cpp:A-B`, paths relative to the repository root (`Map/...`; `dependencies/include/...` for the SpiderMonkey headers, also written `jsapi.h:N`/`js/Value.h:N` inside [embedding.md](spidermonkey/embedding.md)). Line numbers refer to the source at `f4b99bb` and later ([§2](#2-target-versions)). Any edit to a cited source file invalidates them. Inside an entry, a bare `:LINE` means the file cited just before it ([js-api/README.md §5](js-api/README.md#citations)). [memory/README.md](memory/README.md) and [offsets.md](memory/offsets.md) render citations as links into the source file (`../../Offset.cpp#L21-L28`).
- **Doc citations.** A relative link to the heading that states the fact. Anchors follow GitHub's rules.
- **Unverified claims.** Behaviour the repository cannot settle, such as engine internals, what Game.exe does inside a called function, or which game thread runs an intercept, is marked as unverified or as an inference and listed under the page's "Open questions". [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md#how-to-read-this-page) consolidates those lists under stable ids. Ids are never reused, and an answered question moves to Appendix A.
- **Legacy-doc discrepancy notes.** Legacy sources are cited as `doc/X.h:LINE`, `README.md:LINE` and `resources/api.html:LINE`. Each difference is recorded in the page's "Legacy-doc discrepancies" section or in the entry's **Quirks / bugs**. The code wins ([js-api/README.md §5](js-api/README.md#legacy-doc-discrepancy-notes); [§8](#8-relationship-to-the-legacy-documentation)).
- **Addresses.** RVA = offset into Game.exe as written in `D2Ptrs.h`/`Patch.h`; VA = `0x400000` + RVA. Module tokens (`D2CLIENT`, …) are documentation only ([memory/README.md §2](memory/README.md#2-one-image-legacy-module-names)).
- **Status flags on addresses.** Every row of [offsets.md](memory/offsets.md#1-reading-the-tables) and of the TSV's `status` column carries flags that [`gen_symbols.py`](ghidra/tools/gen_symbols.py) computes. They grade the *source's own evidence* (comments, VA literals, use sites), not the binary: `ported-1.14d` (1.14d comment and a matching `-BASE` VA), `va-only` (matching VA, no 1.14d text), `stale-pre-1.14d?` (1.13-style address, or nothing ties it to 1.14d), `va-comment-mismatch` and `ported-1.14d-unverified` (none today), `duplicate-address`, `unused`, `dead-code-only`, `asm-only`, `type-from-usage`, `captured-encoded`. "Ported" means the comments agree with each other, not that the address is right. The Ghidra script turns `stale-pre-1.14d?` into a `Warning` bookmark ([ghidra/README.md §9](ghidra/README.md#9-status-flags-and-how-the-script-treats-them)).
- **Struct discrepancies.** [structs.md](memory/structs.md#reading-the-tables) marks a field **DISCREPANCY** where a `D2Structs.h` offset comment disagrees with the computed layout. There are 19 ([Discrepancy summary](memory/structs.md#discrepancy-summary)).
- **Shared tags and terms.** JS-entry tags such as **(unset)**, **Throws**, **WaitForGameReady** and **Game-loop lock** are defined in [js-api/README.md §5](js-api/README.md#shared-tags). Thread names **G**/**W** come from [events.md §2.1](js-api/events.md#21-threads). **GL**, **WFGR** and **IG/OOG** are defined in the "Terms" paragraph after the [contents of rpc-considerations.md](rpc-considerations.md#contents).
- **Generated regions.** Text between `<!-- BEGIN GENERATED:... -->` markers in `offsets.md`, between `<!-- jsapi_inventory.py --section ... -->` markers in `jsapi-inventory.md`, and all of `structs.md` is overwritten by the generators. Do not edit it by hand ([§7](#7-regenerating-the-generated-parts)).
- **Facts vs suggestions.** The pages state facts, with two exceptions that are suggestions to evaluate: the "options / trade-offs" lists in [rpc-considerations.md](rpc-considerations.md) and all of [NEXT_STEPS.md](NEXT_STEPS.md).

## 6. How these docs were produced and verified

### 6.1 Process

- **Written from source by agents.** Each reference page was written by an AI agent working from the C++, the bundled SpiderMonkey headers and the bundled binaries: [architecture.md](architecture.md), the nine family pages under `js-api/`, both `spidermonkey/` pages, and the `memory/` pages with the Ghidra data files. Tables that can be extracted mechanically came from scripts: the three repository generators ([§7.1](#71-commands)) and one-off scripts ([§7.2](#72-what-has-no-generator-in-the-repository)).
- **Adversarial re-derivation.** A separate verifier agent then re-derived each reference page from the source on its own (not from the writer's notes) and corrected the page in place. For example, by their own reports, the offsets verifier wrote its own parser and diffed it against the TSV, and the structs verifier used its own clang probes and shim headers.
- **Synthesis pages.** [rpc-considerations.md](rpc-considerations.md) was built from the verified pages plus the source. [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) collects every open-question section and the agents' own reported open questions and concerns. Each candidate was re-checked against the source, the headers and the shipped binaries in `dependencies/libs`, `Debug/` and `Release/`, and the doc that raised a question closed this way was updated ([Appendix A](OPEN_QUESTIONS.md#appendix-a-resolved-during-triage), [Appendix C](OPEN_QUESTIONS.md#appendix-c-reproducing-the-binary-checks)). [NEXT_STEPS.md](NEXT_STEPS.md) links its facts to the verified pages. The index in [js-api/README.md](js-api/README.md) was extracted from the registration tables.

### 6.2 Mechanical checks

The first six rows were re-run in the final cross-document pass, with this page included. Pages edited later change the link and citation counts. The Ghidra parts of the last two rows are as reported in [structs.md](memory/structs.md#how-this-was-verified) and [ghidra/README.md §11](ghidra/README.md#11-verification-performed); they need Ghidra classes and were not re-run. The link, coverage and citation checkers are scratch tools of the documentation run and are not in the repository, so their logic is described here.

| Check | What it does | Result |
|---|---|---|
| JS name coverage | Collects every quoted name in every `JSFunctionSpec`/`JSPropertySpec` table of the root `*.h`/`*.cpp` (comments stripped; `sqlite3*`, `StackWalker*` skipped) and looks for each as a whole word in `docs/js-api/*.md`. It checks presence only, not depth. | 326 registered names; **0 missing**. The count matches [js-api/README.md §1](js-api/README.md#1-at-a-glance). |
| Links | Every relative Markdown link under `docs/` must resolve to a file, and every `#anchor` to a heading (GitHub anchor rules) or an explicit `<a name>`/`<a id>`. | 3305 relative links, **0 broken**. |
| Citation ranges | Every backticked `File.ext:A[-B]` under `docs/` must name an existing repository file, and its lines must be within the file's length. A range check only; it says nothing about what the line contains. | 9178 citations, **0 out of range**; 7 name Ghidra's own Java sources (not in the repository), in [ghidra/README.md](ghidra/README.md). |
| Generator reproducibility | Run each repository generator into a scratch directory and compare with the committed file. | `d2bs_symbols.tsv`, `offsets.md`, `d2bs_types.h` and `jsapi-inventory.md`: **byte-identical**. `structs.md`: identical except step 5 of [How this was verified](memory/structs.md#how-this-was-verified), which needs a Ghidra classpath ([§7.1](#71-commands)). |
| `gen_symbols.py` self-checks | Per-kind counts against independent line counts, VA comments, `DLLNO`/`dlls[]` agreement, label validity, the `DLLOFFSET` range. | All pass. 266 rows; 227 of 227 VA comments match ([memory/README.md §10](memory/README.md#10-regenerating-the-tables-and-the-ghidra-import)). |
| Struct layouts | `D2Structs.h` compiled unmodified with `clang++ --target=i686-pc-windows-msvc` (clang 18.1.3) as ground truth. An independent Python MSVC layout engine must match it. `d2bs_types.h` must compile as C11 against 539 offset, 89 `sizeof`, 61 `alignof` and 4 calling-convention `_Static_assert`s, plus 8 bit-field positions. | All pass; 61 structs and 547 fields agree ([structs.md, How this was verified](memory/structs.md#how-this-was-verified)). Reported: Ghidra's `CParser`, built from Ghidra 12.0.4 sources, also parsed the header with matching layouts. |
| Ghidra script | `javac -Xlint:all -Werror` against Ghidra API stubs copied declaration by declaration from the Ghidra source of five versions, plus harnesses over the real TSV/header and an in-memory fake `Program`. | Reported: compiles with no warnings and passes its harnesses ([ghidra/README.md §11](ghidra/README.md#11-verification-performed)). |

### 6.3 What was not available and not done

No Game.exe binary, no Diablo II installation, no Windows machine and no Ghidra installation were available. **Nothing was runtime-tested.** D2BS was not built or run. No address, patch site, register contract or struct layout was checked against the real game. `D2BSImport.java` has never run inside a real Ghidra. Every statement about what the game does is read from the code or inferred from it, and each such inference is marked.

## 7. Regenerating the generated parts

### 7.1 Commands

Run from the repository root. Python 3 standard library only; output is deterministic. `gen_types.py` needs `clang`/`clang++`; its optional Ghidra parse needs Java and Ghidra's jars. The commands are taken from [ghidra/README.md §10](ghidra/README.md#10-regenerating-the-data), [memory/README.md §10](memory/README.md#10-regenerating-the-tables-and-the-ghidra-import), [structs.md](memory/structs.md#how-this-was-verified) and [jsapi-inventory.md §1](spidermonkey/jsapi-inventory.md#1-regenerating-this-document).

```sh
# symbol table + the generated regions of docs/memory/offsets.md (exits non-zero on a failed check)
python3 docs/ghidra/tools/gen_symbols.py --repo . --out docs/ghidra/d2bs_symbols.tsv \
    --markdown docs/memory/offsets.md

# Ghidra header, with the clang layout check (fails if any layout differs from clang's MSVC x86 layout)
python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check

# optional: also parse the header with Ghidra's own CParser
python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check \
    --ghidra-install /path/to/ghidra    # or --ghidra-cp <classpath>

# docs/memory/structs.md (needs clang); add --ghidra-install DIR or --ghidra-cp CP
# plus --ghidra-label TEXT to keep step 5 of "How this was verified"
python3 docs/ghidra/tools/gen_types.py --repo . --structs-md docs/memory/structs.md

# every generated block of the JSAPI inventory, in place
python3 docs/spidermonkey/tools/jsapi_inventory.py --update docs/spidermonkey/jsapi-inventory.md
# or one section to stdout: --section <name>; list names: --list-sections
```

Without the Ghidra options, the `structs.md` command drops step 5 from "How this was verified", which the committed file contains. After regenerating the TSV or the header, re-run `D2BSImport.java` with `dry-run` and read its summary before applying ([ghidra/README.md §10](ghidra/README.md#10-regenerating-the-data)).

### 7.2 What has no generator in the repository

- Tables marked "Generated" in [patches-and-hooks.md](memory/patches-and-hooks.md#3-patch-table) and [call-stubs.md](memory/call-stubs.md#3-stub-index), and the index tables of [js-api/README.md](js-api/README.md#6-global-functions), came from one-off scripts that were not committed. After a source change, update them by hand or rewrite the extraction.
- Every authored page. Its `File:LINE` citations and counts drift with any edit to the cited source. Re-run a citation range check and the coverage check, and re-read the affected entries.

## 8. Relationship to the legacy documentation

| Legacy source | What it is | Status |
|---|---|---|
| `doc/` | Doxygen stub headers (`doc/*.h`), `doc/D2BS.conf` (Doxyfile) and `doc/Makefile`, which runs `doxygen` and copies the HTML to a web root. `doc/MainPage.h:3`: "These docs are based on code from /branches/patch-113d r1725." | Stale. Written for the 1.13d branch. |
| `README.md` (repository root) | About 278 KB (5858 lines) of Markdown generated from `doc/*.h` ([architecture.md §10.2](architecture.md#102-repository-layout)). | Stale. Same content as `doc/`. |
| `resources/api.html` | TiddlyWiki 2.5.3 page (`resources/api.html:6`). Some listed functions are not registered (`iniread`, `iniwrite`, `blockMinimize`, …; [js-api/README.md §12](js-api/README.md#12-not-registered-commented-out-or-legacy-only-names)), and the screen-hook objects have no pages. | Stale. |
| `resources/HISTORY.txt` | Version history 0.1 → 1.4 only; nothing for 1.5/1.6 ([architecture.md §10.2](architecture.md#102-repository-layout)). | Historical. |

The legacy material was used only to cross-check. Where it disagrees with the code, the code wins and the difference is called out per entry. Discrepancy sections: [globals-core](js-api/globals-core.md#legacy-doc-discrepancies), [out-of-game](js-api/out-of-game.md#legacy-doc-discrepancies), [unit-properties](js-api/unit-properties.md#legacy-doc-discrepancies), [unit-methods](js-api/unit-methods.md#legacy-doc-discrepancies), [world](js-api/world.md#legacy-doc-discrepancies), [screenhooks](js-api/screenhooks.md#legacy-doc-discrepancies), [utility-classes](js-api/utility-classes.md#legacy-doc-discrepancies), [events §13](js-api/events.md#13-legacy-doc-discrepancies), [embedding §12](spidermonkey/embedding.md#12-legacy-doc-discrepancies), [jsapi-inventory §9](spidermonkey/jsapi-inventory.md#9-legacy-doc-discrepancies). [globals-game.md](js-api/globals-game.md) and [architecture.md](architecture.md) put their legacy notes inline (**Quirks / bugs**, "Legacy docs:" paragraphs). Questions about legacy intent are in [OPEN_QUESTIONS.md §12](OPEN_QUESTIONS.md#12-intent--legacy-behaviour-int).

## 9. Caveats

- **Addresses are unverified.** The flags grade the source's evidence only. 17 rows are `stale-pre-1.14d?`. The `RealmPacketRecv` patch at VA `0x44B1AE` has no 1.14d evidence but is installed unconditionally. The `0x82E0` patch jumps to `0x576F06` instead of `0x40576F` (`Patch.h:42`). See [offsets.md §3](memory/offsets.md#3-stale-and-suspect-entries-what-depends-on-them) before trusting any address.
- **Layouts are the compiler's view of `D2Structs.h`, not the game's.** They are exact for what D2BS reads, but where one of the 19 discrepant comments is right about the game, the declared layout is wrong from that field on ([structs.md](memory/structs.md#discrepancy-summary); [OQ-STR-01](OPEN_QUESTIONS.md#oq-str-01)).
- **Original instructions at patch sites are inferences** from what each intercept re-executes ([patches-and-hooks.md §4](memory/patches-and-hooks.md#4-displaced-instructions-and-expected-original-bytes)).
- **Engine behaviour is read from headers and binaries, not observed.** One example is what JS receives when a native leaves its return value unset ([OPEN_QUESTIONS.md SM](OPEN_QUESTIONS.md#8-spidermonkey-engine-semantics-sm)).
- **Thread claims come from reading the code.** Which game thread runs some intercepts is unknown ([architecture.md §11](architecture.md#11-open-questions); [OPEN_QUESTIONS.md THR](OPEN_QUESTIONS.md#7-threading--runtime-concurrency-thr)).
- **Counts are for this revision.** Generated counts refresh when you regenerate; authored counts (for example "108 globals", "107 open questions") do not.
- **Agent-written.** The reference pages were independently re-derived and the synthesis pages re-checked, but errors can remain in any page, this one included. When a page and the source disagree, the source is right. Fix the page, and if the fact was an open question, move it to Appendix A of [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md#appendix-a-resolved-during-triage).

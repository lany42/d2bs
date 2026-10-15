# Ghidra import: `D2BSImport.java`

Scope: how to load the D2BS address map of Diablo II 1.14d `Game.exe` into your own Ghidra
project. `D2BSImport.java` is a Java GhidraScript that reads two generated data files that sit
next to it: [`d2bs_types.h`](d2bs_types.h) (the `D2Structs.h` layouts as Ghidra-parsable C) and
[`d2bs_symbols.tsv`](d2bs_symbols.tsv) (every Game.exe address the C++ code uses: functions,
globals, code labels, patch sites). This page covers what the script imports, how to run it in
the GUI and headless, its options, how re-runs behave, how to regenerate the data, what was
verified and what was not. The address model (one image, `VA = image base + RVA`, legacy module
names) is explained in [../memory/README.md](../memory/README.md), per-symbol tables and status
rules in [../memory/offsets.md](../memory/offsets.md), structure layouts in
[../memory/structs.md](../memory/structs.md), patch sites in
[../memory/patches-and-hooks.md](../memory/patches-and-hooks.md) and register-level stubs in
[../memory/call-stubs.md](../memory/call-stubs.md). Nothing in the data was checked against a
Game.exe binary. The script was not run inside a Ghidra installation (none was available); it
was run end to end against a real `ProgramDB` with the real x86 language, built from the Ghidra
12.0.4 sources, on synthetic memory contents ([§11](#11-verification-performed)).

## Contents

1. [What gets imported](#1-what-gets-imported)
2. [Files](#2-files)
3. [Prerequisites](#3-prerequisites)
4. [GUI usage](#4-gui-usage)
5. [Headless usage](#5-headless-usage)
6. [Options](#6-options)
7. [What each row kind does](#7-what-each-row-kind-does)
8. [Re-running (idempotency)](#8-re-running-idempotency)
9. [Status flags and how the script treats them](#9-status-flags-and-how-the-script-treats-them)
10. [Regenerating the data](#10-regenerating-the-data)
11. [Verification performed](#11-verification-performed)
12. [Known limitations](#12-known-limitations)
13. [Troubleshooting](#13-troubleshooting)
14. [Open questions](#14-open-questions)

## 1. What gets imported

Counts are for the files as committed (re-run the generators and they change).

| Phase | Source | Result in the program |
|---|---|---|
| 1. types | `d2bs_types.h` | 102 named types in data type category `/D2BS` (79 structs/unions incl. the Win32 prelude and two empty placeholders, 19 typedefs, 4 function definitions under `/D2BS/functions`) |
| 2. symbols | `d2bs_symbols.tsv`, 266 rows | 111 `FUNC`, 93 `DATA`, 31 `LABEL`, 22 `PATCH`, 9 `COND_PATCH` rows at 258 distinct addresses (8 rows are `alias_of` duplicates) |

Per row kind ([§7](#7-what-each-row-kind-does) has the exact rules):

| Kind | Origin in the C++ | Applied as |
|---|---|---|
| `FUNC` | `FUNCPTR` in `D2Ptrs.h` | function (disassembled and created if missing), name, prototype (calling convention + parameters), plate comment |
| `DATA` | `VARPTR`, data `ASMPTR`, absolute VAs in `MPQStats.cpp` / `JSUnit.cpp` | label, data type of the object at the address (only where it cannot overwrite anything), EOL comment |
| `LABEL` | code `ASMPTR` (mid-function jump/return targets, register-ABI entries) | label (never replaces an existing primary symbol; at the entry of a default-named `FUN_*` function it becomes that function's name, [§7](#7-what-each-row-kind-does)), EOL comment |
| `PATCH` / `COND_PATCH` | `Patches[]` / `Conditional[]` in `Patch.h` | label (none where a default-named function starts), pre-comment `D2BS patch: CALL len=5 -> <target>`, `Note` bookmark in category `D2BS`, read-only instruction-boundary check |
| any row flagged `stale-pre-1.14d?` | | `Warning` bookmark in category `D2BS` (plus the above, limited by `stale=`, [§6](#6-options)) |

The script never patches bytes; patch rows only document where D2BS writes at run time.

## 2. Files

| File | Kind | Produced by |
|---|---|---|
| [`D2BSImport.java`](D2BSImport.java) | GhidraScript (category `D2BS`) | hand-written |
| [`d2bs_symbols.tsv`](d2bs_symbols.tsv) | symbol table, schema below | [`tools/gen_symbols.py`](tools/gen_symbols.py) |
| [`d2bs_types.h`](d2bs_types.h) | C header for Ghidra's `CParser` | [`tools/gen_types.py`](tools/gen_types.py) |

TSV schema (the script validates it and rejects rows that do not conform): UTF-8, LF line
endings (CRLF is tolerated), first line is the header row, tab-separated, no quoting, 9 fields:

| Column | Content |
|---|---|
| `kind` | `FUNC`, `DATA`, `LABEL`, `PATCH`, `COND_PATCH` |
| `module` | legacy module token (`D2CLIENT`, `D2COMMON`, ...); documentation only, Game.exe 1.14d is one image ([../memory/README.md §2](../memory/README.md#2-one-image-legacy-module-names)) |
| `name` | label to apply; `VARPTR` names without the `p_` prefix; patches `D2BS_PATCH_<handler>[_n]` |
| `rva` | `0x`-prefixed hex RVA relative to the image base; `ORD:<n>` reserved for ordinal imports (none exist; the script skips them) |
| `type` | `FUNC`: C prototype `RET CC NAME(params)`; `DATA`: C type of the object at the address (may be empty); `LABEL`: empty; patches: `CALL`, `JMP` or `BYTES` |
| `extra` | patches: `len=<n>;target=<handler or 0xNN>` plus `;cond=<Vars flag>` for `COND_PATCH`; other kinds: empty or `alias_of=<name>` |
| `status` | comma-separated flags ([§9](#9-status-flags-and-how-the-script-treats-them)) |
| `comment` | trailing source comment |
| `source` | `File:line` of the entry (`D2Ptrs.h:122`, `Patch.h:9`, `MPQStats.cpp:6`, ...) |

## 3. Prerequisites

- **Ghidra 10.1 or later.** The script was compiled (`javac -Xlint:all -Werror`) against stubs
  copied from the Ghidra sources of 12.3-DEV (master `918acd7`, 2026-10-13) and of the tags
  `Ghidra_12.0.4_build`, `Ghidra_11.0_build`, `Ghidra_10.4_build`, `Ghidra_10.2_build` and
  `Ghidra_10.1_build`, and against Ghidra 12.0.4 classes compiled from source, with which it was
  also run end to end ([§11](#11-verification-performed)). Ghidra source line numbers on this
  page refer to 12.3-DEV `918acd7` unless a tag is named. Version differences handled in the code:
  `CParser.getParseMessages()` (10.2+) is called reflectively; the scratch data type manager is
  `TransientDataTypeManager` (12.2+) or `StandAloneDataTypeManager` (deprecated for removal in
  12.2), looked up reflectively; comments go through `FlatProgramAPI.get/set*Comment`, which
  exist in all these versions, so neither the old `CodeUnit.*_COMMENT` int constants nor the
  newer `CommentType` enum is referenced. Ghidra compiles the script itself with the JDK it runs
  on; the source is pure ASCII because Ghidra's script compiler reads it in the platform
  default charset (`ResourceFileJavaFileManager.java:53`).
- **Diablo II 1.14d `Game.exe`**, imported with the PE loader as **`x86:LE:32:default`** and
  compiler spec **`windows`** ("Visual Studio"; `clangwindows` uses the same `x86win.cspec`,
  which defines `__stdcall`, `__cdecl`, `__fastcall` and `__thiscall`). The script stops on any
  other processor/endianness/size unless `force` is given, and warns on another compiler spec.
- **Image base `0x400000`** (Game.exe's preferred base, which the `-BASE` comments and the
  absolute literals in `MPQStats.cpp`/`JSUnit.cpp` assume, [../memory/README.md
  §1](../memory/README.md#1-summary)). The script always computes `address = image base + rva`
  and only warns if the base differs, so a rebased program still gets correct addresses but the
  VAs printed in the TSV comments will not match.
- **Auto-analysis finished.** The script uses the default `GhidraScript.AnalysisMode.ENABLED`:
  it starts at once and auto-analysis reacts to its changes afterwards. It does not wait for a
  running analysis, so start it only when analysis is done; then most `FUNC` addresses already
  are functions and only need naming, and the conflict checks see the final listing.

## 4. GUI usage

1. Open Game.exe in the CodeBrowser and let auto-analysis finish.
2. Window → Script Manager. Either add the directory: "Manage Script Directories" → add
   `<d2bs repo>/docs/ghidra`; or copy the three files (`D2BSImport.java`, `d2bs_symbols.tsv`,
   `d2bs_types.h`) into `~/ghidra_scripts`. The data files must be in the same directory as the
   script; otherwise the script opens a file chooser for each missing file.
3. Select `D2BSImport.java` (category `D2BS`) and run it. Output and the summary go to the
   Console. All changes of the run are one transaction (named `D2BSImport` in the undo list,
   opened by `FlatProgramAPI.start()`); auto-analysis that reacts to them adds its own
   transactions after it. `GhidraScript` commits that transaction even when the script is
   cancelled or fails (`GhidraScript.java:457-465`): a cancelled run keeps what it did so far
   (no comments or bookmarks, which are written last) and prints a summary marked `CANCELLED`;
   one Undo reverts the whole run.

Options in the GUI: edit the `DEFAULT_*` constants at the top of `D2BSImport.java` (Script
Manager → "Edit Script with basic editor"). For a first look use `DEFAULT_DRY_RUN = true`.
Script arguments, when a caller supplies them (`GhidraScript.setScriptArgs`), override the
constants in the GUI too.

## 5. Headless usage

Import, analyze and apply in one go (`support/analyzeHeadless[.bat]` in the Ghidra install):

```sh
analyzeHeadless /path/to/projects D2 \
    -import /path/to/Game.exe -processor x86:LE:32:default -cspec windows \
    -scriptPath /path/to/d2bs/docs/ghidra \
    -postScript D2BSImport.java
```

Program already in the project (and already analyzed):

```sh
analyzeHeadless /path/to/projects D2 -process Game.exe -noanalysis \
    -scriptPath /path/to/d2bs/docs/ghidra \
    -postScript D2BSImport.java dry-run
```

- Script arguments follow the script name, without leading dashes; analyzeHeadless passes every
  token up to its next own option to the script. Unknown arguments stop the script before it
  changes anything.
- The data files are looked up next to the script found on `-scriptPath`; `symbols=<file>` and
  `header=<file>` override that. The script never opens a dialog in headless mode: a missing
  `d2bs_symbols.tsv` aborts the run (nothing changed), a missing header only skips phase 1.
- A dry run changes nothing; add `-readOnly` as well if you do not want analyzeHeadless to save
  the analysis it ran itself.

## 6. Options

| Argument | GUI constant | Default | Effect |
|---|---|---|---|
| `dry-run` | `DEFAULT_DRY_RUN` | off | Parse and validate everything (header, every prototype, every data type), print one `[dry-run]` line per row with the actions it would take, change nothing; the summary counts are what a real run would do |
| `skip-types` | `DEFAULT_SKIP_TYPES` | off | Do not parse or import `d2bs_types.h`; prototypes and data types resolve against the `/D2BS` types already in the program |
| `skip-signatures` | `DEFAULT_SKIP_SIGNATURES` | off | Do not apply `FUNC` prototypes (functions are still created and named) |
| `names=auto\|keep\|force` | `DEFAULT_NAMES` | `auto` | Who may replace an existing name: `auto` replaces only `DEFAULT` names (`FUN_*`, `DAT_*`, `LAB_*`) and analyzer names (`ANALYSIS`, and `AI` on Ghidra 12); `keep` never renames an existing function, also not through a label (functions the run itself creates are still named); `force` renames everything. A kept user/imported/analysis name gets the D2BS name as a secondary label (a kept `FUN_*` name gets none, see [§7](#7-what-each-row-kind-does)); a replaced non-default name is kept as a secondary label |
| `types=replace\|keep` | `DEFAULT_TYPES` | `replace` | Conflict handler when a `/D2BS` type from the header differs from the program's: `replace` (`DataTypeConflictHandler.REPLACE_HANDLER`, the header is the source of truth; your edits to `/D2BS` types are overwritten) or `keep` (`KEEP_HANDLER`) |
| `stale=mark\|apply\|skip` | `DEFAULT_STALE` | `mark` | Rows whose status contains `stale`: `mark` = label + comment + `Warning` bookmark only (no function creation, disassembly, data type or prototype); `apply` = treat like any row; `skip` = ignore. Patch rows are always processed (they change nothing) |
| `asm-only=skip\|apply` | `DEFAULT_ASM_ONLY` | `skip` | `FUNC` rows flagged `asm-only`: their `D2Ptrs.h` prototype is never used by the compiler and does not describe the register ABI ([§12](#12-known-limitations)); `skip` names the function and records the declared prototype in the plate comment only |
| `symbols=<file>` | - | next to the script | TSV to read |
| `header=<file>` | - | next to the script | header to read |
| `max-errors=<n>` | `DEFAULT_MAX_ERRORS` | 25 | number of errors and of warnings listed in the summary |
| `force` | - | off | continue although the language is not 32-bit little-endian x86 |

Flags also accept `=true`/`=false`.

## 7. What each row kind does

Address of a row = `currentProgram.getImageBase() + rva`. Rows whose address is in no memory
block are skipped and listed. Rows with the same address are processed together, so their
comment lines and bookmark texts are combined. Comments are merged, never replaced: the script
owns exactly the lines that start with `D2BS:` or `D2BS ` and leaves all other text alone.

Where comments go: Ghidra stores a comment on the code unit that *contains* an address
(`SetCommentCmd.java:101`: the instruction, or for data the primitive component at that
offset), while reading returns the record at exactly the address (`CodeManager.java:2920`).
Comments and bookmarks are therefore written after all rows, when the listing no longer
changes. A row whose address lies inside an instruction or data primitive (typical for stale
rows and misplaced patch sites) has its lines added to the comment of that code unit, tagged
with the row address as Ghidra prints it: `D2BS @<address>: ...`, `D2BS @<address> patch:
...`. Bookmarks always stay at the exact row address.

Labels at default-named functions: Ghidra's `SymbolTable.createLabel` does not add a label where
a function with a default name (`FUN_*`, `thunk_FUN_*`) starts; it renames that function to the
label (`SymbolManager.java:3150`, `tryUpdatingDefaultFunction`; same code in 10.1, 11.0 and
12.0.4). The script therefore creates a label at such an entry only for a non-stale `LABEL` row
and only with `names=auto|force` (the function takes the `LABEL` name, counted as "default-named
functions named by a LABEL row"). Alias, `DATA`, stale and patch rows, and `names=keep`, create
no label there (counted as "not created at a default-named function"; a warning except for patch
rows): the name stays in the row's comment, the patch keeps its bookmark.

`FUNC`

1. Alias row (`alias_of=`): secondary label (none while the function still has a default name)
   + `D2BS alias:` plate line; no second prototype.
2. Otherwise ensure a function: use the one at the address; else, if there is no instruction,
   refuse when the address is inside another instruction, inside defined (non-`undefined`) data,
   or in a non-executable/uninitialized block; clear `undefined1..8` data at the address,
   disassemble, create the function (`CreateFunctionCmd`; it removes the new body from any
   existing function that overlapped it). If no function can be made, the name becomes a plain
   label and the row counts as failed.
3. Name per `names=` ([§6](#6-options)); a function created by this run is always named; a
   same-named plain label at the entry is deleted first (it would collide with the function
   symbol). If the function is a thunk, the name goes on the thunk while Ghidra applies the
   prototype to the thunked function (`FunctionDB.updateFunction` forwards it); a warning says so.
4. Prototype: `VOID` → `void`; a function-pointer parameter `R (CC* P)(...)` is replaced by the
   typedef `<name>_<P>_t` from the header (`D2WIN_SetEditBoxCallback`, `D2WIN_SetEditBoxProc`;
   in the inline form `CParser` drops the calling convention, see the header comment of
   `d2bs_types.h`). The text is parsed with `CParser` against a scratch copy of the program's
   `/D2BS` types, the definition is renamed to the function's current name (so the command never
   renames), and applied with `ApplyFunctionSignatureCmd(entry, signature, USER_DEFINED)`. The
   resulting calling convention is compared with the TSV; a mismatch is a warning. A prototype
   that does not parse is an error; the function keeps its name.
5. Plate comment: `D2BS: <name> [<module>] <flags>`, `D2BS proto: ...`, `D2BS src: <File:line>
   // <source comment>`, plus `D2BS note:` lines for a kept name or a skipped `asm-only`
   prototype.

`DATA`: label (primary if the current primary symbol may be taken over per `names=`; never over
a function, none at a default-named function entry); EOL comment. Unless alias or untyped:
resolve the type (`/D2BS/<base>` or a C keyword type, then one pointer per `*`); apply it only
if the whole range is inside the block and contains no instruction and no defined data; then
clear the `undefined` code units in the range and create the data. Equivalent data already
there counts as applied. Anything else is a warning and the row stays label-only.

`LABEL`: label, primary only if the address has no symbol besides Ghidra's default
`LAB_*`/`DAT_*` name; at a default-named function entry it names the function (see above); EOL
comment.

`PATCH` / `COND_PATCH`: label as for `LABEL`, except that a patch row never names a function
(a patch at the start of a `FUN_*` function gets no label); pre-comment `D2BS patch:
<CALL|JMP|BYTES> len=<n> -> <target>[ (<target address>)][ (cond <Vars flag>)]`, `D2BS patch
src: ...`, and for `captured-encoded` a note that the installed jump goes to the `DLLOFFSET` encoding
([../memory/README.md §5.1](../memory/README.md#51-static-initialisers-see-encoded-values-bug));
`Note` bookmark (category `D2BS`). For `CALL`/`JMP` the site must be an instruction start and
`len` must end on an instruction boundary; otherwise `D2BS patch check:` is added and a warning
logged (`BYTES` patches rewrite opcode bytes by design and are not checked).

Labels are created with `SourceType.USER_DEFINED` in the global namespace. Bookmark types are
the standard `Note` and `Warning`; filter on category `D2BS` in the Bookmarks window.

The run ends with a summary: rows per kind applied / skipped / failed, counters for functions,
prototypes, labels, data types, patch checks, comments and bookmarks, then the first
`max-errors` errors and warnings.

## 8. Re-running (idempotency)

Running the script again with the same files changes nothing that is already in place:

| Item | Rule |
|---|---|
| labels | created only if no symbol with that name exists at that address |
| function names | renamed only if different; policy re-evaluated each run |
| prototypes | re-applied every run (same result for unchanged input). `ApplyFunctionSignatureCmd` uses `DYNAMIC_STORAGE_FORMAL_PARAMS` (`ApplyFunctionSignatureCmd.java:203`), so a re-run **overwrites signature edits and custom storage you made by hand** on non-`asm-only` functions; use `skip-signatures` after hand-editing |
| data | skipped when equivalent data is already at the address |
| comments | the script's own lines are replaced, not appended; unchanged text is not rewritten; read and write use the same (containing code unit) address, so rows inside an instruction do not overwrite its comment |
| bookmarks | one per address, type and category (`BookmarkManager.setBookmark` replaces the comment); written only when the text differs; a `D2BS` bookmark whose rows no longer call for it is removed |
| types | with `replace`, equivalent types are left as they are; the real-`CParser` test re-imported the header into the same manager and got no new type and no `.conflict` copy |

Not undone: artifacts at addresses that are no longer in the TSV, and data types or functions
created by an earlier run. To start over, use Undo right after the run, or delete the `/D2BS`
category and the `D2BS` bookmarks by hand.

## 9. Status flags and how the script treats them

The rules that set each flag are in [../memory/offsets.md
§1](../memory/offsets.md#1-reading-the-tables); counts are in its §2. Every flag is shown in the
row's comment. Behaviour:

| Flag | Meaning (short) | Script |
|---|---|---|
| `ported-1.14d` | source comment says 1.14d and its `-BASE` VA equals `0x400000 + RVA` | normal |
| `va-only` | matching VA but no `1.14d` text (or an absolute VA literal in code) | normal; treat as unverified |
| `stale-pre-1.14d?` | 1.13-style address or no evidence for 1.14d | `Warning` bookmark; `stale=` decides the rest (default label + comment only) |
| `ported-1.14d-unverified`, `va-comment-mismatch` | inconsistent comment (none today) | normal |
| `duplicate-address` | another row has the same RVA; later rows carry `alias_of` | alias rows: secondary label only |
| `unused`, `dead-code-only` | no (live) use in D2BS | normal (informational) |
| `asm-only` | `FUNCPTR` reached only from inline asm | prototype not applied unless `asm-only=apply` |
| `type-from-usage` | DATA type taken from the casts at every use, not from the declaration | normal |
| `captured-encoded` | read by a static initialiser before `DefineOffsets()` | normal; patch rows get a pre-comment note |

## 10. Regenerating the data

From the repository root (Python 3 standard library only; output is deterministic):

```sh
# symbol table + the generated regions of docs/memory/offsets.md
python3 docs/ghidra/tools/gen_symbols.py --repo . --out docs/ghidra/d2bs_symbols.tsv \
    --markdown docs/memory/offsets.md

# header, with the clang layout check (needs clang/clang++)
python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check

# optional: also parse the header with Ghidra's own CParser
python3 docs/ghidra/tools/gen_types.py --repo . --out docs/ghidra/d2bs_types.h --check \
    --ghidra-install /path/to/ghidra    # or --ghidra-cp <classpath>

# docs/memory/structs.md (needs clang). The committed file also has the "Ghidra's own parser"
# paragraph (verification step 5): add --ghidra-install DIR or --ghidra-cp CP, plus
# --ghidra-label TEXT, or that paragraph is left out
python3 docs/ghidra/tools/gen_types.py --repo . --structs-md docs/memory/structs.md
```

`gen_symbols.py` exits non-zero when a validation fails (counts, VA comments, `DLLNO` table,
label validity, `DLLOFFSET` range); `gen_types.py --check` fails when a layout differs from
clang's MSVC x86 layout ([../memory/structs.md, How this was
verified](../memory/structs.md#how-this-was-verified)). After regenerating, re-run the script
with `dry-run` and read the summary before applying.

## 11. Verification performed

Done on the files as committed (scratch harnesses, not part of the repository; no Ghidra
installation and no Game.exe were available):

| Check | Result |
|---|---|
| `gen_symbols.py` and `gen_types.py` re-run twice into scratch files | byte-identical to the committed `d2bs_symbols.tsv`, `d2bs_types.h` and the generated regions of `offsets.md`; all generator validations `[ok]`; `gen_types.py --check` (clang MSVC x86 layouts, 539 offset / 89 sizeof / 61 alignof / 4 calling-convention asserts) and `--ghidra-cp` (Ghidra 12.0.4 `CParser`: 61 composites, all 111 prototypes, 92 DATA types) pass |
| independent re-parse of `D2Ptrs.h` (`FUNCPTR`/`VARPTR`/`ASMPTR`), `Patch.h` (`Patches[]`/`Conditional[]`), `MPQStats.cpp` and `JSUnit.cpp` with a separate parser, diffed against the TSV | 244 + 22 rows match in kind, module, name, RVA, prototype, patch type/len/target/cond; the only type differences are the 7 `type-from-usage` rows (VARPTR `X*` used as a buffer/struct at the address) |
| every type identifier in the 111 prototypes and 92 typed DATA rows looked up in `d2bs_types.h` | 39 identifiers, all declared (or the Ghidra built-in `wchar_t`) |
| `javac -Xlint:all -Werror D2BSImport.java` against stubs whose declarations are copied verbatim from the sources of 12.3-DEV `918acd7`, `Ghidra_12.0.4_build`, `Ghidra_11.0_build`, `Ghidra_10.4_build`, `Ghidra_10.2_build`, `Ghidra_10.1_build`; and against Ghidra 12.0.4 framework classes compiled from source plus 12.0.4 `CreateFunctionCmd`, `DisassembleCommand`, `SetCommentCmd`, `ApplyFunctionSignatureCmd` | compiles with no warning against all seven |
| static helpers over every TSV row, expectations computed by an independent Python script (row fields, extra fields, flags, alias, prototype split, normalization and its idempotency, data type split, patch and row comment lines, grouping, comment merge, options, header units), plus the script's own header/prototype path with the real 12.0.4 `CParser` (`parseHeader`, `collectTypes`, `typedefNames`, `parsePrototype`, `resolveDataType`) | 3615 checks, 0 failures; 102 named `/D2BS` types (71 structs, 8 unions, 19 typedefs, 4 function definitions); 111 prototypes parse with the TSV's convention (52 `__stdcall`, 58 `__fastcall`, 1 `__cdecl`) |
| the `C.jj` grammars of `Ghidra_10.1_build` and `Ghidra_11.0_build` turned into parsers with JavaCC 5.0 (with their `CompositeHandler`/`Declaration`) and run on the header (`#line 1 "D2BS"` prefix as the script does) and on all normalized prototypes | both: header parses, 102 `/D2BS` types, 60 composite sizes as in the header, both function-pointer typedefs `__stdcall`, 111/111 prototypes with the right convention and argument count (layout arithmetic came from the 12.0.4 framework classes) |
| `run()` end to end against a real `ProgramDB` with the real `x86:LE:32:default` `SleighLanguage` (`x86.sla` compiled by the 12.0.4 `SleighCompile`) and compiler spec `windows`, real 12.0.4 commands; only `GhidraScript`/`FlatProgramAPI` are shims whose used members copy the 12.0.4 bodies (`executeNormal`: one transaction, committed). Memory: `.text`/`.data`/uninitialized `.bss` at image base `0x400000`, code written at every code row so each row address is an instruction start; pre-state like after analysis: `FUN_*` functions, analysis/imported/user names, a same-named label, undisassembled code, a thunk, `undefined4`/`dword`/`char[16]` data, user comments, a `DAT_` reference | 1868 checks, 0 failures: 109 of 111 `FUNC` rows applied (the 2 planted refusals: entry inside an instruction, entry over defined data) with name, calling convention, parameter names, types and storage (`__fastcall` `ECX`/`EDX`, `CX` for a `WORD`, then the stack; `__stdcall` on the stack), return type, all resolved to the program's `/D2BS` types (no `.conflict` copies); 85 data types applied, 2 refused over defined data; aliases secondary; stale rows marked; Note/Warning bookmark counts; planted patch-site defects reported; second run changes nothing; dry run changes nothing (modification number unchanged) and predicts the real run's counts; `names=keep`, `stale=apply`, `asm-only=apply`, `skip-types`, missing files headless and in GUI mode without dialog, bad argument, ORD/out-of-memory/malformed/`__thiscall`/CRLF rows, broken header (line reported, nothing imported), image base `0x10000000`, a TSV edit that clears a stale flag (Warning removed, comment rewritten) |

The end-to-end run found two defects that the earlier fake-`Program` tests could not show, both
fixed: Ghidra's `createLabel` renames a default-named function instead of adding a label, so
`names=keep` still renamed `FUN_*` functions and patch, alias and stale rows renamed the function
they sit on ([§7](#7-what-each-row-kind-does)); and the dry run under-counted labels at such
entries.

Not verified: behaviour inside a Ghidra installation (Script Manager, `analyzeHeadless`, OSGi
script compilation), interplay with running auto-analysis, real Game.exe bytes (the code islands
are synthetic, so "patch site" and conflict outcomes on the real binary are unknown), and the
runtime of Ghidra 10.x/11.x beyond their C grammar.

## 12. Known limitations

- **Addresses are unverified.** The flags grade the source's own evidence, not the binary.
  Check first the rows listed in [../memory/offsets.md
  §3](../memory/offsets.md#3-stale-and-suspect-entries-what-depends-on-them) (the
  `RealmPacketRecv_Interception` patch at RVA `0x4B1AE`, the `Conditional[]` sites, the
  `D2COMMON_MPQ_*` and `JSUnit.cpp` VAs, `D2COMMON_GetMissileOwnerUnit`).
- **Stale entries** (17 rows) are pre-1.14d offsets or have no evidence; with the default
  `stale=mark` they get only a label (none where a default-named function starts), which can
  sit in unrelated code.
- **Prototypes are D2BS's declarations, not recovered signatures.** Parameter names such as
  `_2`, `unk`, `Unk_3` and `DWORD` for pointers come from `D2Ptrs.h`. They match how D2BS calls
  the function, which is not proof of the game's real types.
- **Register-based ABIs.** The six `asm-only` functions are entered through asm stubs that pass
  arguments in registers Ghidra's named conventions cannot express (`__fastcall` means
  `ECX`/`EDX`). From the stubs: `D2CLIENT_GetUiVar_I`, `D2CLIENT_SetSelectedUnit_I` and
  `D2CLIENT_DrawRectFrame` take their argument in `EAX` (`D2Helpers.cpp:720`, `:728`, `:919`);
  `D2CLIENT_InitAutomapLayer_I` in `EDI` (`D2Helpers.cpp:336`); `D2CLIENT_LeftClickItem_I` gets
  `Location` in `EAX` and six stack arguments (`D2Helpers.cpp:790`); `D2NET_ReceivePacket_I` is
  called from `GamePacketReceived_Intercept` (`D2Intercepts.cpp:24`). Details:
  [../memory/call-stubs.md §5](../memory/call-stubs.md#5-register-and-stack-contracts) and
  [../memory/offsets.md §7.2](../memory/offsets.md#72-asm-only-funcptrs). Set these by hand:
  right-click the function → Edit Function → "Use Custom Storage", then assign each parameter's
  register. The same applies to `LABEL` rows with an `_I`/`_II` suffix that are function entries
  in practice (the script creates no functions for `LABEL` rows; where analysis already made a
  `FUN_*` function there, the `LABEL` row names it and nothing else).
- **`__thiscall`.** `x86win.cspec` defines it, but Ghidra's C parser has no `__thiscall`
  keyword (`C.jj` knows `__cdecl`, `__stdcall`, `__fastcall`, `__vectorcall`, ...), so a
  `__thiscall` prototype is reported as an error and not applied. No row uses it today.
- **Data at buffers and tables.** `char`/`wchar_t` rows (`D2CLIENT_ChatMsg`,
  `D2MULTI_ChatBoxMsg`, `D2WIN_ItemDescText`) are typed as one element; the buffer length is not
  known from source. `D2CLIENT_BodyClickTable` is untyped. `D2CLIENT_StoreLayout` and
  `D2CLIENT_MercLayout` keep their declared pointer type although the other layout globals are
  structs ([../memory/offsets.md §7.1](../memory/offsets.md#71-varptr-casts)).
- **Types.** `MpqTable` and `_RTL_CRITICAL_SECTION_DEBUG` are empty placeholders; anonymous
  unions/structs are named `<Outer>__u_<OFF>` / `__s_<OFF>`; the two function-pointer struct
  members (`MessageHandlerList.handler`, `TransactionDialogsLine_t.handler`) get CParser's
  anonymous definitions `/D2BS/functions/_func_<n>`; 19 source offset comments disagree
  with the declared layouts ([../memory/structs.md, Discrepancy
  summary](../memory/structs.md#discrepancy-summary)). `types=replace` overwrites local edits
  of `/D2BS` types.
- **Source archive of the `/D2BS` types (Ghidra 10.x/11.x).** Before 12.x the scratch manager
  is a `StandAloneDataTypeManager` whose archive type is `TEST` (10.1 and 11.0 sources), and
  `DataTypeManagerDB.resolve` keeps the identity of types from any non-`PROGRAM` archive, so the
  imported types are associated with an in-memory source archive named `D2BS header` (shown as
  their source archive in the Data Type Manager; a later run that adds or replaces types links
  them to that run's new archive). Layouts are not affected; Data Type Manager → right-click →
  "Disassociate From Archive" removes the link. Not exercised in a running Ghidra. 12.x managers are
  `TEMPORARY` archives (`TransientDataTypeManager.java:132`; also the 12.0.4 class files) whose
  types are added as local types.
- **Names.** Module tokens are not turned into namespaces; all labels are global. `ORD:<n>`
  rows would be skipped (none exist).
- **Header parse is all or nothing.** If `d2bs_types.h` does not parse, no type is imported (a
  partial import could give wrong layouts); every failing declaration is listed with its line.

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Script not in the Script Manager | directory not added, or the file was copied without being picked up: refresh the Script Manager; category is `D2BS` |
| `language is ..., expected x86:LE:32:default` | re-import Game.exe with that language and compiler spec `windows`; `force` overrides at your own risk |
| `image base is 0x..., expected 0x400000` | addresses still follow image base + RVA; to match the TSV VAs, Window → Memory Map → Set Image Base `0x400000` |
| `d2bs_symbols.tsv is not next to the script` (headless) | pass `symbols=<file>` or keep the three files in the `-scriptPath` directory |
| `types: d2bs_types.h:<line>: ...` | the header did not parse with this Ghidra's `CParser`; regenerate it, or report the line; phase 2 continues with existing `/D2BS` types |
| `prototype did not parse (...)` | a type the prototype uses is missing under `/D2BS` (typical with `skip-types` on a fresh program); run once without `skip-types` |
| `data type '...' not applied: instruction at ...` / `defined data ...` | the script never overwrites; clear the range yourself (Clear Code Bytes) and re-run |
| `patch site: site is inside the instruction at ...` | either the address is wrong for this binary or analysis disassembled a different instruction stream there; compare with the expected original bytes in [../memory/patches-and-hooks.md §4](../memory/patches-and-hooks.md#4-displaced-instructions-and-expected-original-bytes) |
| `calling convention is 'unknown', expected __fastcall` | the program's compiler spec lacks that convention: use `windows` |
| `ApplyFunctionSignatureCmd failed: ...` | message from Ghidra; often a parameter type that cannot be resolved |
| `cannot read ... as UTF-8` | the TSV was re-saved in another encoding; regenerate it |
| a `D2BS @<address>: ...` line on an instruction or data item | the row's address is inside that code unit (wrong address for this binary, or a different disassembly there); the bookmark sits at the exact address |
| hand-made signature or custom storage reverted | re-runs re-apply prototypes ([§8](#8-re-running-idempotency)); re-run with `skip-signatures` |
| `label <name> not created: the default-named function FUN_... starts here` | a stale, alias or `DATA` row (or `names=keep`) at the entry of a function Ghidra still names by default: a label would rename the function ([§7](#7-what-each-row-kind-does)); name the function yourself if the row is right |
| `function at ... is a thunk: ...` | the address holds a jump stub; the name is on the stub, the prototype went to the function it jumps to; check that target |
| `prototype: Ghidra's C parser has no __thiscall keyword ...` | set the calling convention of that function by hand ([§12](#12-known-limitations)) |

## 14. Open questions

- End-to-end behaviour inside Ghidra (GUI and headless) has not been observed; first real runs
  should start with `dry-run`.
- The 10.1 and 11.0 C grammars parse the header and all prototypes
  ([§11](#11-verification-performed)), but their layout code (framework classes of those versions) was not executed;
  `gen_types.py --ghidra-install` compares the layouts for a given installation.
- Which of the duplicate-address names matches the game's semantics, and the true owning module
  of each function, cannot be decided from source ([../memory/offsets.md
  §10](../memory/offsets.md#10-open-questions)).

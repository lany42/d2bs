# Screen hooks: `Frame`, `Box`, `Line`, `Text`, `Image` and the automap helpers

Scope: the five drawable "screen hook" classes (`JSScreenHook.cpp/.h` for the JS binding, `ScreenHook.cpp/.h` for the C++ `Genhook` hierarchy) and the two coordinate globals `screenToAutomap` / `automapToScreen`. Covers every constructor argument, property and method, and the machinery behind them: the global hook lists and z-order, which thread draws (the `GameDraw` / `GameDrawOOG` intercepts), locking between script threads and the draw thread, ownership and destruction (script end, `remove()`, GC finalisation), in-game / out-of-game visibility, screen vs automap coordinates, alignment, value domains (colors, fonts, opacity), image loading (BMP → D2 `CellFile`), and the click / hover callback path (WH_MOUSE hook → per-script event → blocking wait). Source of truth is the C++; the legacy docs (`doc/Frame.h`, `doc/Box.h`, `doc/Line.h`, `doc/Text.h`, `doc/Image.h`, `doc/ScreenHooks.h`, `doc/globalFuncs.h`, generated `README.md`) are cross-checked and every disagreement is listed in [Legacy-doc discrepancies](#legacy-doc-discrepancies). `resources/api.html` only names `FrameObject` … `ImageObject` in its object index (`resources/api.html:845-849`) and has no pages for them.

## Contents

- [Conventions](#conventions)
- [Object model](#object-model)
- [Rendering model](#rendering-model) — hook lists & z-order · draw thread & entry points · in/out of game · primitives
- [Coordinates, alignment and the automap transform](#coordinates-alignment-and-the-automap-transform)
- [Threading and locking](#threading-and-locking)
- [Ownership and lifetime](#ownership-and-lifetime)
- [Click and hover model](#click-and-hover-model)
- [Common property semantics](#common-property-semantics)
- [Value domains: alignment, colors, fonts, opacity](#value-domains-alignment-colors-fonts-opacity)
- [Image loading](#image-loading)
- Classes: [Frame](#frame) · [Box](#box) · [Line](#line) · [Text](#text) · [Image](#image)
- [Globals](#globals): [`screenToAutomap`](#screentoautomappoint--x-y) · [`automapToScreen`](#automaptoscreenpoint--x-y)
- [Facts relevant to an RPC replacement](#facts-relevant-to-an-rpc-replacement)
- [Legacy-doc discrepancies](#legacy-doc-discrepancies)
- [Open questions](#open-questions)

Related: [events.md](events.md) (`mouseclick` / `mousemove` listeners, event pump), [globals-core.md](globals-core.md) (`delay`, `addEventListener`), [globals-game.md](globals-game.md) (`getTextSize`, `getMouseCoords`), [unit-properties.md](unit-properties.md) (`me.blockMouse`, `me.screensize`), [utility-classes.md](utility-classes.md) (path security, `isValidPath`), [../architecture.md](../architecture.md) (threads, `Vars`, game-loop lock, `d2bs.ini`), [../spidermonkey/embedding.md](../spidermonkey/embedding.md) (per-script runtimes, rooting, operation callback), [../spidermonkey/jsapi-inventory.md](../spidermonkey/jsapi-inventory.md), [../memory/offsets.md](../memory/offsets.md), [../memory/structs.md](../memory/structs.md) (`CellFile`, `GfxCell`, `CellContext`), [../memory/call-stubs.md](../memory/call-stubs.md) (`D2GFX_DrawRectFrame_STUB`), [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md) (`GameDraw_Intercept`, `GameDrawOOG_Intercept`), [../rpc-considerations.md](../rpc-considerations.md).

---

## Conventions

Facts shared by every entry below; entries refer to them by the **bold tag**.

| Tag | Fact | Source |
|---|---|---|
| **Class registration** | The five classes are `global_classes` entries `{&x_class, 0, x_ctor, 0, x_methods, x_props, NULL, NULL}`; for every script context `ScriptEngine::InitClass` calls `JS_InitClass(cx, global, NULL, classp, classp->construct, 0, props, methods, NULL, NULL)`, i.e. constructor `length` 0, props and `remove` on the prototype, no statics. | `JSGlobalClasses.cpp:162-166`, `ScriptEngine.cpp:358-359`, `ScriptEngine.cpp:230-233` |
| **Instance construction** | Constructors build the instance with `BuildObject(cx, &x_class, x_methods, x_props)`: `JS_NewObject(cx, classp, NULL, NULL)` then `JS_DefineFunctions` + `JS_DefineProperties` *on the instance* (so every instance has own `remove` and own accessor properties shadowing the prototype's). | `js32.cpp:8-28` |
| **new optional** | The constructor natives never test `JS_IsConstructing`; `Text("a", 1, 2)` without `new` behaves identically. | `JSScreenHook.cpp:37`, `:169`, `:319`, `:451`, `:600` |
| **Native signature** | `JSAPI_FUNC(n)` = `JSBool n(JSContext*, uint argc, jsval* vp)`; property ops are handle-based `JSAPI_PROP` / `JSAPI_STRICT_PROP`, dispatching on the tinyid via `JS_IdToValue` + `JSVAL_TO_INT`. | `js32.h:133`, `js32.h:141-142` |
| **Throws** | `THROW_ERROR(cx, msg)` = `JS_ReportError(cx, msg); return JS_FALSE;` → catchable JS `Error`. | `js32.h:113-117` |
| **callee-return** | A native that returns `JS_TRUE` without `JS_SET_RVAL` evaluates to `vp[0]`, which is the callee (`JS_RVAL` and `JS_CALLEE` are the same slot). | `dependencies/include/js/CallArgs.h:317-321` |
| **Int tag tests** | Constructors use `JSVAL_IS_INT`, setters use `vp.isInt32()`: tag tests. Integral values held as doubles, non-integral numbers, `-0`, `NaN` and numbers outside int32 fail the test and are **silently ignored** (no coercion, no error). Booleans need `JSVAL_IS_BOOLEAN` / `vp.isBoolean()` (so `1`/`0` are ignored for `visible`/`automap`); strings need `JSVAL_IS_STRING` / `vp.isString()`. | `JSScreenHook.cpp:45-60`, `:129-130` |
| **Function test** | `JSVAL_IS_FUNCTION(cx, v)` = `!JSVAL_IS_PRIMITIVE(v) && JS_ObjectIsFunction(cx, obj)`. | `js32.h:98` |
| **Object test** | `JSVAL_IS_OBJECT(v)` is a D2BS function (this `jsapi.h` has none), defined as `!JSVAL_IS_PRIMITIVE(v)`, so `null` is not an object. | `js32.h:52`, `js32.cpp:62-64` |
| **Private without class check** | `JS_GetPrivate(cx, obj)` wraps `JS_GetPrivate(obj)` with no class check. | `js32.cpp:65-67` |
| **Script thread** | Natives run on the calling script's own thread; each script has its own `JSRuntime` + `JSContext`. | `Script.cpp:118-135` |
| **RVA/VA** | `D2Ptrs.h` offsets are RVAs into Game.exe (image base `0x400000`, legacy DLL names ignored); VA = RVA + `0x400000`. See [../memory/README.md](../memory/README.md). | `D2Ptrs.h` |

---

## Object model

Each JS hook object is a thin handle whose private slot (`JSCLASS_HAS_PRIVATE`) points to a heap C++ object derived from `Genhook`. All drawing state lives in C++; JS properties are pure accessors.

| JS class | JSClass (name, flags, finalizer, ctor) | C++ class | Draw primitive (C++) | Game function (D2Ptrs.h, RVA → VA) |
|---|---|---|---|---|
| `Frame` | `"Frame"`, `JSCLASS_HAS_PRIVATE`, `hook_finalize`, `frame_ctor`, no trace hook (`JSCLASS_SPEC` leaves `trace` `NULL`, `js32.h:163-164`) — `JSGlobalClasses.cpp:44-46` | `FrameHook` `ScreenHook.h:376` | `FrameHook::Draw` `ScreenHook.cpp:436` → `D2GFX_DrawFrame(&rect)` macro (`D2Ptrs.h:509`) → `D2GFX_DrawRectFrame_STUB` (`D2Helpers.cpp:919`: `mov eax, ecx; jmp`) | `D2CLIENT_DrawRectFrame` `0x52E50 → 0x452E50` (`D2Ptrs.h:118`) |
| `Box` | `"Box"`, same flags/finalizer, `box_ctor` — `JSGlobalClasses.cpp:48-50` | `BoxHook` `ScreenHook.h:327` | `BoxHook::Draw` `ScreenHook.cpp:407` | `D2GFX_DrawRectangle(x1,y1,x2,y2,color,trans)` `0xF6300 → 0x4F6300` (`D2Ptrs.h:378`) |
| `Line` | `"Line"`, …, `line_ctor` — `JSGlobalClasses.cpp:52-54` | `LineHook` `ScreenHook.h:277` | `LineHook::Draw` `ScreenHook.cpp:390` | `D2GFX_DrawLine(x1,y1,x2,y2,color,0xFF)` `0xF6380 → 0x4F6380` (`D2Ptrs.h:379`) |
| `Text` | `"Text"`, …, `text_ctor` — `JSGlobalClasses.cpp:56-58` | `TextHook` `ScreenHook.h:188` | `TextHook::Draw` `ScreenHook.cpp:315` → `myDrawText` (`D2Helpers.cpp:383`) | `D2WIN_SetTextSize` `0x102EF0 → 0x502EF0` (`D2Ptrs.h:447`), `D2WIN_DrawText` `0x102320 → 0x502320` (`D2Ptrs.h:445`); width via `CalculateTextLen` (`D2Helpers.cpp:212`) → `D2WIN_GetTextSize` `0x102520 → 0x502520` (`D2Ptrs.h:446`) |
| `Image` | `"Image"`, …, `image_ctor` — `JSGlobalClasses.cpp:60-62` | `ImageHook` `ScreenHook.h:235` | `ImageHook::Draw` `ScreenHook.cpp:348` → `myDrawAutomapCell` (`D2Helpers.cpp:578`) | `D2GFX_DrawAutomapCell2(ctx,x,y,-1,5,coltab)` `0xF6480 → 0x4F6480` (`D2Ptrs.h:380-381`); loading: `D2CMP_InitCellFile` `0x201340 → 0x601340` (`D2Ptrs.h:410-411`) |

`Genhook` fields (`ScreenHook.h:37-44`), initialised in `Genhook::Genhook` (`ScreenHook.cpp:174-187`):

| Field | Type | Initial value | Meaning |
|---|---|---|---|
| `owner` | `Script*` | creating script (`JS_GetContextPrivate(cx)`) | used for click dispatch, handler context, cleanup; set to `NULL` in the destructor (`ScreenHook.cpp:200`) |
| `gameState` | `ScreenhookState` (`OOG=0, IG=1, Perm=2`, `ScreenHook.h:28`) | from constructor (see [in/out of game](#in-game--out-of-game-visibility)) | which draw pass renders it; immutable |
| `alignment` | `Align` (`Left=0, Right=1, Center=2`, `ScreenHook.h:27`) | ctor arg | per-class meaning, see [alignment](#coordinates-alignment-and-the-automap-transform) |
| `clicked`, `hovered` | `jsval` | `JSVAL_VOID` | JS callbacks |
| `self` | `JSObject*` | the JS object | stored, never read; root calls commented out (`ScreenHook.cpp:180-181`) |
| `isAutomap` | `bool` | ctor arg | world-coordinate hook drawn only while automap is open; immutable, no JS property |
| `isVisible` | `bool` | `true` | mirrors list membership (visible / invisible list) |
| `opacity` | `ushort` | ctor arg (Box) or 0 | only `BoxHook::Draw` uses it |
| `zorder` | `ushort` | `1` (`ScreenHook.cpp:175`) | paint / click order |
| `location` | `POINT` (LONG x, y) | ctor x, y | anchor; `-1` is a "do not draw" sentinel |

Subclass fields: `TextHook{wchar_t* text; ushort font, color}` (`ScreenHook.h:190-191`), `ImageHook{wchar_t* location; CellFile* image; ushort color}` (`:237-239`), `LineHook{uint x2, y2; ushort color}` (`:279-280`), `BoxHook{uint xsize, ysize; ushort color}` (`:329-330`), `FrameHook{uint xsize, ysize}` (`:378`).

`Genhook`'s `Draw` and `IsInRange` are virtual, but **its destructor is not** (`ScreenHook.h:52`) — see [Ownership and lifetime](#ownership-and-lifetime).

---

## Rendering model

### Hook lists and z-order

- Two process-global lists `static std::list<Genhook*> visible, invisible` (`ScreenHook.h:33`, `ScreenHook.cpp:12-13`), protected by one `CRITICAL_SECTION globalSection` (`ScreenHook.h:34`), created by `Genhook::Initialize()` from `Startup` (`D2BS.cpp:131`, `ScreenHook.h:66-69`) and deleted by `Genhook::Destroy()` in `Shutdown` (`D2BS.cpp:154`, `ScreenHook.h:70-73`). The lists are shared by all scripts.
- A new hook is appended to `visible` inside the `Genhook` base constructor (`ScreenHook.cpp:184-186`) — before the derived constructor has run, before `JS_SetPrivate` and before the handlers are attached.
- `visible = false` moves the hook to the end of `invisible`; `visible = true` moves it back to the **end** of `visible` (`ScreenHook.h:115-132`). Only `visible` is ever drawn or hit-tested.
- Every frame `Genhook::DrawAll(type)` (`ScreenHook.cpp:52-56`) → `ForEachVisibleHook(DrawHook, type)` (`ScreenHook.cpp:89-105`): enter `globalSection`, copy `visible` into a `std::vector`, `std::sort` by `zOrderSort` (ascending `zorder`, `ScreenHook.cpp:24-26`), call `DrawHook` for each, leave the section. Lower `zorder` is painted first, so **higher `zorder` is on top**. `std::sort` is not stable: the relative order of hooks with equal `zorder` (default 1 for all) is unspecified by the standard. The copy+sort runs every frame (O(n log n) per frame).
- `ForEachHook`, `ForEachInvisibleHook`, `ForEachVisibleHookUnLocked` and `CleanHook` exist (`ScreenHook.cpp:58-87`, `:107-142`, `:46-50`) but have no callers.

### Draw thread and entry points

| Pass | Patch (Patch.h) | Intercept | Handler | Condition | Order of drawing |
|---|---|---|---|---|---|
| In game | `PatchJmp` at RVA `0x53B30` (VA `0x453B30`) → `GameDraw_Intercept` (`Patch.h:10`) | `D2Intercepts.cpp:71-73` | `GameDraw` `D2Handlers.cpp:399` | `Vars.bActive && ClientState() == ClientStateInGame` (`:400`) | `FlushPrint`, `Genhook::DrawAll(IG)` (`:402`), `DrawLogo`, `Console::Draw` |
| Out of game | `PatchCall` at RVA `0xF9A0D` (VA `0x4F9A0D`) → `GameDrawOOG_Intercept` (`Patch.h:35`) | `D2Intercepts.cpp:186-188` | `GameDrawOOG` `D2Handlers.cpp:421` | `D2WIN_DrawSprites()` always (`:422`; FUNCPTR RVA `0xF9870`, `D2Ptrs.h:437`), then `Vars.bActive && ClientState() == ClientStateMenu` (`:423`) | game sprites, `FlushPrint`, `Genhook::DrawAll(OOG)` (`:425`), `DrawLogo`, `Console::Draw` |

- Both run on the game thread (D2's frame loop; the same window thread that owns `TimerProc` and the WH_MOUSE hook — `Helpers.cpp:180-187`, `D2Handlers.cpp:493-504`; see [../architecture.md](../architecture.md)). Script threads never draw.
- Hooks are never drawn during `ClientStateBusy`/`ClientStateNull` (loading screens) or before `Vars.bActive`.
- The D2BS console and the version logo (`DrawLogo`, `ScreenHook.cpp:16-22`: `"D2BS " D2BS_VERSION` bottom-right, color 4, font 0) are always painted over hooks.
- `GameDraw` yields `Vars.cGameLoopSection` only *after* drawing (`D2Handlers.cpp:410-417`), so hooks are drawn while the game thread holds the game-loop lock.
- Where `0x453B30` sits in D2Client's frame (i.e. whether hooks end up above or below the game's UI panels in game) is not determinable from this repo — see [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md).

### In-game / out-of-game visibility

`DrawHook` (`ScreenHook.cpp:39-44`) draws a hook iff `(gameState == pass || gameState == Perm) && (!isAutomap || *p_D2CLIENT_AutomapOn)`. Each `Draw` additionally requires `isVisible` and `location.x != -1 && location.y != -1` (unsigned compare against `0xFFFFFFFF`), e.g. `ScreenHook.cpp:317`.

| Constructor | `gameState` | Source |
|---|---|---|
| `Frame` | always `IG` ("framehooks don't work out of game -- they just crash") | `JSScreenHook.cpp:66-67` |
| `Box`, `Line`, `Text`, `Image` | `OOG` if the creating script's state is `OutOfGame`, else `IG` (scripts in state `InGame` **and the console `Command` script**) | `JSScreenHook.cpp:172`, `:322`, `:454`, `:603`; `Script.h:13` |
| — | `Perm` (both passes) is only the C++ default argument; no JS path creates it | `ScreenHook.h:51`, `:198`, … |

`gameState` cannot be changed after construction. An OOG-script hook stays in `visible` while in game (not drawn, but **still hit-tested for clicks** — see [Click and hover model](#click-and-hover-model)). In-game scripts are terminated when the client returns to the menu (`operationCallback` returns false for `InGame` scripts when `ClientState() == ClientStateMenu`, `ScriptEngine.cpp:315`, `:323`), which destroys their hooks.

Automap visibility uses `p_D2CLIENT_AutomapOn` (VARPTR `DWORD`, RVA `0x3A27E8` → VA `0x7A27E8`, `D2Ptrs.h:151`).

### Primitives

| Hook | Call per frame | Notes |
|---|---|---|
| Frame | `RECT r = {x', y, x'+xsize, y+ysize}; D2GFX_DrawFrame(&r)` (`ScreenHook.cpp:445-447`) | Draws D2's UI frame border via a D2Client routine. `isAutomap` is ignored (no transform). |
| Box | `D2GFX_DrawRectangle(p1.x, p1.y, p2.x, p2.y, color, opacity)` (`ScreenHook.cpp:423`) | Filled rectangle; `p2` is an absolute corner (x'+xsize, y+ysize). |
| Line | `D2GFX_DrawLine(p1.x, p1.y, p2.x, p2.y, color, 0xFF)` (`ScreenHook.cpp:401`) | `x2`/`y2` are an absolute endpoint, not a size. |
| Text | `D2WIN_SetTextSize(font); D2WIN_DrawText(text, x', y, color, 0); D2WIN_SetTextSize(old)` (`D2Helpers.cpp:383-387`) | `y` is the baseline (hit range is `y-h … y`). In-string `ÿc<N>` color codes are honoured by `D2WIN_DrawText` (D2BS relies on this for its console, `Console.cpp:236` drawing lines built with `ÿc` at `ScriptEngine.cpp:439`). |
| Image | `myDrawAutomapCell(image, x', y, (BYTE)color)` (`ScreenHook.cpp:358`) | Centres the cell (`x -= w/2; y += h/2`, `D2Helpers.cpp:585-586`), culls off-screen cells against `GetScreenSize()` (`:589-591`), remaps palette index 255 to `color` (`:593-597`), draws with `D2GFX_DrawAutomapCell2(&ct, x, y, (DWORD)-1, 5, coltab)` (`:599`). |

Each `Draw` call additionally wraps the game call in a per-type critical section (`Vars.cTextHookSection`, `cImageHookSection`, `cLineHookSection`, `cBoxHookSection`, `cFrameHookSection`; `ScreenHook.cpp:324-326`, `:357-359`, `:400-402`, `:422-424`, `:446-448`; declared `D2BS.h:110-114`, created `D2BS.cpp:114-118`). Nothing else ever enters these sections, so they exclude nothing. `Vars.cScreenhookSection` (`D2BS.h:108`, `D2BS.cpp:112`) is created and never used.

---

## Coordinates, alignment and the automap transform

**Screen space.** Non-automap hooks use game client pixels — the same space as the mouse coordinates delivered to click handlers (`ScreenToClient` of the hook point, `D2Handlers.cpp:298-299`). Screen size: in game `*p_D2CLIENT_ScreenSizeX/Y` (RVA `0x31146C`/`0x311470`, `D2Ptrs.h:138-139`), out of game hard-coded 800×600 (`GetScreenSize`, `D2Helpers.cpp:560-568`).

**Automap space.** With `automap = true` the stored `x`/`y` are passed every frame through `ScreenToAutomap(x, y)` (`D2Helpers.cpp:364-376`):

```
X = 32*x;  Y = 32*y;                    D = *p_D2CLIENT_Divisor   (int, RVA 0x311254, D2Ptrs.h:185)
ax = (X - Y) / 2 / D - p_D2CLIENT_Offset->x + 8      (POINT, RVA 0x3A5198, D2Ptrs.h:153)
ay = (X + Y) / 4 / D - p_D2CLIENT_Offset->y - 8
if (D2CLIENT_GetAutomapSize())  { ax -= 1; ay += 5; }   (RVA 0x5A710, D2Ptrs.h:89)
```

(C integer division at every step.) `(x−y)·16`, `(x+y)·8` is the isometric world→screen projection divided by the automap scale, so despite the function's name the **inputs are world/map coordinates** (the space of unit `x`/`y`), and the output is automap pixels. Because the projection runs at draw time, automap hooks track the automap as it scrolls.

| Hook | Points transformed when `isAutomap` |
|---|---|
| Text, Image | the anchor, *after* the alignment offset (`ScreenHook.cpp:321-323`, `:354-356`) |
| Line | both endpoints (`ScreenHook.cpp:396-399`) |
| Box | `(x', y)` and `(x'+xsize, y+ysize)` separately; result is the axis-aligned rectangle between the two projected corners, not a projected diamond (`ScreenHook.cpp:418-421`) |
| Frame | none — `FrameHook::Draw` ignores `isAutomap` (`ScreenHook.cpp:436-451`) |

Because the alignment offset (a pixel width for Text/Image, `xsize/2` for Box) is applied to the *world* coordinate before projection, non-Left alignment of automap hooks is off by a mixed-unit amount.

**Alignment** (`Align`: `Left=0`, `Right=1`, `Center=2`, `ScreenHook.h:27`; any int is stored via a C cast):

| Hook | Drawn left edge `x'` | Hit-test box (`IsInRange`, all comparisons strict) |
|---|---|---|
| Frame / Box | Left/other: `x`; Center: `x − xsize/2`; **Right: `x + xsize/2`** (`ScreenHook.cpp:440-444`, `:411-415`) | `x < px < x+xsize`, `y < py < y+ysize` — ignores alignment (`:453-457`, `:429-434`) |
| Line | no alignment (constructor passes `Left`, no `align` property) (`JSScreenHook.cpp:349`) | always `false` (`ScreenHook.h:296-298`) |
| Text | Left/other: `x`; Center: `x − w/2`; Right: `x − w` (w = text width) (`ScreenHook.cpp:318-319`) | `x' < px < x'+w`, `y−h < py < y` (`:331-337`) — consistent with drawing |
| Image | Left: `x`; Right: `x − w`; Center **and any other value**: `x − w/2` (`ScreenHook.cpp:351-352` + `D2Helpers.cpp:585`) | Left: `x+w < px < x+2w` (**one width to the right of the image**); Right: `x−w … x`; Center/other: `x−w/2 … x+w/2`; vertical `y−h/2 … y+h/2` (`ScreenHook.cpp:364-378`) |

Hit tests always use the raw stored coordinates: for automap hooks they compare world coordinates against mouse pixels, and they ignore `gameState`, automap-open state and whether the hook is currently drawn.

---

## Threading and locking

| Operation | Thread | Locks taken | Notes |
|---|---|---|---|
| Constructor (`Genhook::Genhook`) | script | `globalSection` around `visible.push_back` only (`ScreenHook.cpp:184-186`) | Hook is reachable by the draw thread before the derived object is fully constructed (vptr still `Genhook`'s, subclass members unset) — narrow race. |
| `x`, `y`, `xsize`, `ysize`, `x2`, `y2`, `color`, `font`, `align`, `opacity`, `zorder` setters | script | none — `Lock()`/`Unlock()` are empty (`ScreenHook.h:182-185`) | Plain aligned 32/16-bit stores racing with the draw thread. |
| `visible` setter (`SetIsVisible`) | script | `globalSection` (`ScreenHook.h:115-132`) | |
| `text` setter (`SetText`) | script | `globalSection` (`ScreenHook.cpp:339-346`) | Safe against `TextHook::Draw`. |
| `location` setter (`SetImage`) | script | **none** (`ScreenHook.cpp:380-388`) | Frees the `CellFile` the draw thread may be drawing → use-after-free race (see [Image loading](#image-loading)). |
| `click` / `hover` setters | script | none | hover setter calls `JS_RemoveRoot`/`JS_AddRoot` (`ScreenHook.cpp:302-307`). |
| `remove()` | script | `globalSection` (`JSScreenHook.cpp:20-30`) | |
| GC finalizer `hook_finalize` | script (GC on that runtime) | `globalSection` (`JSScreenHook.cpp:10-15`) | |
| `Genhook::Clean` (script context destroy) | script | `globalSection` (`ScreenHook.cpp:149-171`) | |
| `DrawAll` | game | `globalSection` for the whole pass + per-type section around each game call | |
| Click dispatch | game (WH_MOUSE hook) | `globalSection` for the whole pass **including up to 3000 ms waits per handled hook** (`ScreenHook.cpp:91`, `:235`); the game thread also holds `Vars.cGameLoopSection` at that point (it only yields it in `GameDraw`/`TimerProc`, `D2Handlers.cpp:410-417`, `:493-504`) | See consequences under [Click and hover model](#click-and-hover-model). |
| `Vars.mCachedCellFiles` (image cache, `D2BS.h:102`) | script | none | `std::map` mutated from any script thread constructing / re-pointing an `Image`. |
| Font state | game and script | none | `D2WIN_SetTextSize` is global; `CalculateTextLen` called from a script thread (e.g. `getTextSize`, `JSGame.cpp:910`) races with `TextHook::Draw`. |

---

## Ownership and lifetime

- **Owner.** `owner = (Script*)JS_GetContextPrivate(cx)` of the constructing context (first line of each constructor). The JS object, the click/hover `jsval`s and the roots all belong to that script's private `JSRuntime` (`Script.cpp:120`).
- **No reference from C++ to JS.** The hook never roots its JS object (`ScreenHook.cpp:180-181` commented out). Visibility does not keep the object alive.
- **Ways a hook dies.**
  1. `hook.remove()` — immediate (`JSScreenHook.cpp:18-33`).
  2. **Garbage collection** — when the script drops every reference, `hook_finalize` (`JSScreenHook.cpp:8-16`) deletes the hook at the next GC of that runtime. `delay()` forces `JS_GC` whenever the heap grew by 0.5 MB since the last GC (`JSCore.cpp:152-156`). An unreferenced hook (e.g. `new Text("hi", 10, 10);` as a bare statement) therefore disappears at an arbitrary later time.
  3. **Script destruction** — `~Script` sets `isAborted = true` and calls `JS_DestroyContext` (`Script.cpp:44-55`) → `contextCallback(JSCONTEXT_DESTROY)` drains the event queue with `clearList = true` and calls `Genhook::Clean(script)` (`ScriptEngine.cpp:376-389`), which unlinks hooks from the lists; the runtime teardown then finalizes the objects and `hook_finalize` deletes them. A script is destroyed when its thread finishes `Run()` (main returned, or the script was stopped) **and** `DisableCache` is true (default `true`, `Helpers.cpp:124`; `Script.cpp:480-481`), on `FlushCache`, or at engine shutdown (`ScriptEngine.cpp:150`). With `DisableCache=false`, a finished script's hooks keep being drawn (and clickable) until the cache is flushed.
- **Non-virtual destructor.** `hook_finalize` and `hook_remove` `delete` through `Genhook*` (`JSScreenHook.cpp:13`, `:24`) while `~Genhook` is not virtual (`ScreenHook.h:52`): undefined behaviour; in practice only `~Genhook` runs (`ScreenHook.cpp:189-212`: `owner = NULL`, `location = {-1,-1}`, unlink from its list). `~TextHook` (frees `text`) and `~ImageHook` (frees `location`, `delete[] image`) never run → the text and path strings leak; the image buffer is not freed (which, by accident, keeps the shared image cache valid).
- **`Genhook::Clean` bug** (`ScreenHook.cpp:144-172`): loop 1 walks `visible` and removes every hook whose owner `IsAborted()` (any aborted script, not just `owner`), but erases with `invisible.erase(it)` using an iterator into `visible` (`:155`) — undefined behaviour that unlinks the node from `visible` while adjusting `invisible`'s bookkeeping. Loop 2 removes `owner`'s hooks from `invisible`. Neither loop deletes the hook. A hook unlinked this way while still `isVisible` would be re-inserted into `invisible` by a later `visible = false`.
- **Stale hover root.** If a hover function was set, `&hovered` (inside the C++ hook) was registered with `JS_AddRoot` (`ScreenHook.cpp:307`); the destructor never removes it (`ScreenHook.cpp:193-194` commented out), leaving a root pointing into freed memory for the rest of the runtime's life.
- **After removal.** The JS object survives with a `NULL` private: getters return without setting `vp` (the property's slot value is returned, see [Common property semantics](#common-property-semantics)), setters do nothing, `remove()` is a no-op.
- **Identity.** Every constructor call creates a new object and a new C++ hook; there is no global to enumerate, look up or compare hooks, and no equality hook. The JS object is the only handle.

---

## Click and hover model

### Detection

1. `MouseMove` (`D2Handlers.cpp:296`) is a thread-local `WH_MOUSE` hook installed on the game window's thread (`SetWindowsHookEx(WH_MOUSE, MouseMove, NULL, mainThread)`, `Helpers.cpp:182-187`). It is not the subclassed WndProc `GameEventHandler` (`D2Handlers.cpp:176`).
2. Converts `MOUSEHOOKSTRUCT.pt` to client coordinates (`:298-299`); for `HC_ACTION` drops points with negative x or y (`:302-303`); stores `Vars.pMouseCoords` (`:304`); if `Vars.bBlockMouse` (`me.blockMouse`, `JSUnit.cpp:555-557`) returns 1 — the message is swallowed and neither `mouseclick` events nor hook clicks happen (`:305-306`).
3. For `WM_LBUTTONDOWN` / `WM_RBUTTONDOWN` / `WM_MBUTTONDOWN` (`:313-336`): first `MouseClickEvent(button, pt, false)` queues `mouseclick` listeners (see [events.md](events.md)), then `Genhook::ForEachVisibleHook(ClickHook, {button, pt})` with button `0` = left, `1` = right, `2` = middle. Button-up messages only produce `mouseclick` events. Double-click, wheel and X-button messages are not handled.
4. `ForEachVisibleHook` walks **every** hook in `visible` in ascending `zorder` while holding `globalSection` (`ScreenHook.cpp:89-105`); there is no early exit, so every hook under the cursor with a click handler is dispatched, bottom-most first. `gameState`, automap-open state and owner state are not consulted.
5. If any `Click` returned true, `MouseMove` returns 1 and D2 never sees the button-down (`D2Handlers.cpp:347`); otherwise `CallNextHookEx`.

### Dispatch: `Genhook::Click` (`ScreenHook.cpp:214-247`, game thread)

1. `IsInRange(pt)` else return false.
2. If `owner && JSVAL_IS_FUNCTION(owner cx, clicked)`: allocate `Event{owner, argc = 3, name = "ScreenHookClick", arg1 = button, arg2 = x, arg3 = y, arg4 = false}` (DWORDs on the heap), `ResetEvent(Vars.eventSignal)`, create `AutoRoot(owner->GetContext(), clicked)` (adds a value root on the owner's runtime from the game thread, `AutoRoot.cpp:4-6`, `:22-24`) and push it to `evt->functions`, then `owner->FireEvent(evt)`: `push_front` onto the owner's `EventList` under `Vars.cEventSection`, `TriggerOperationCallback()` if the owner `IsRunning()`, `SetEvent(owner->eventSignal)` (`Script.cpp:419-430`). The owner's run state is not checked before queueing.
3. `WaitForSingleObject(Vars.eventSignal, 3000)` — `Vars.eventSignal` is a single process-wide manual-reset event (`Helpers.cpp:155`, `D2BS.h:76`).
4. Timeout → `return false` (the click reaches the game); the queued `Event`, its args, name and `AutoRoot` are leaked and the event still runs later.
5. Signalled → `block = *(bool*)evt->arg4`; frees args, root and `evt` (the `_strdup`'d name is leaked every click) → return `block`.

### Execution on the owner script thread (`ExecScriptEvent`, `ScriptEngine.cpp:660-686`)

The queued event runs only when the owner script pumps events: in `operationCallback` (`ScriptEngine.cpp:315-322`, not while paused — `:304-313` loops in `Sleep(50)`), inside `delay()` (`JSCore.cpp:138-151`), or in other native wait loops (e.g. `D2Helpers.cpp:272-281`); see [events.md](events.md) / [../spidermonkey/embedding.md](../spidermonkey/embedding.md). Then:

- `argv = [button, x, y]` as numbers (`JS_NumberValue` of the DWORDs, `:665-667`); each `evt->functions` entry (exactly one) is called with **`this` = the script's global object**, not the hook (`JS_CallFunctionValue(cx, JS_GetGlobalObject(cx), …)`, `:674`).
- `block |= JSVAL_IS_BOOLEAN(rval) && JSVAL_TO_BOOLEAN(rval)` (`:675`): only a strict boolean `true` blocks; `1`, `"yes"`, objects do not. `rval` is an uninitialised local (`:671`) if the call fails (handler threw).
- `*(DWORD*)evt->arg4 = block; SetEvent(Vars.eventSignal)` (`:682-683`). If the context is being destroyed (`clearList`), the handler is skipped and `false` is signalled.
- `addEventListener("ScreenHookClick", f)` has no effect on this path (handlers come from `evt->functions`, not the script's listener map).

### Consequences

- **Game freeze up to 3 s per handled hook.** The game thread blocks in step 3 until the owning script pumps its events. A script busy in a long native, paused, or (with caching) finished stalls the whole client for 3000 ms per overlapping hook with a click handler, after which the click passes through.
- **Self-deadlock (until timeout) from inside a click handler.** The game thread holds `globalSection` and `Vars.cGameLoopSection` during the wait. A handler that constructs a hook, sets `visible` or `text`, calls `remove()`, triggers a GC that finalizes a hook, or calls any native that takes the game-loop lock (`AutoCriticalRoom`, see [globals-game.md](globals-game.md)) blocks until the 3 s timeout expires; its return value is then ignored. (Blocking packet events release the game lock around their wait, `Events.cpp:312-314`; `Click` does not.)
- **Cross-talk on `Vars.eventSignal`.** The same manual-reset event is reset/set by `keydownblocker` (`Events.cpp:63-66`, `ScriptEngine.cpp:650-652`), chat/whisper blockers (`Events.cpp:197-200`, `ScriptEngine.cpp:567-569`) and packet events (`Events.cpp:309-313`, `ScriptEngine.cpp:765`, which can run on script threads). A foreign `SetEvent` wakes `Click` early: it reads `block = false` and frees `evt` while it is still queued → use-after-free when the owner later executes it. A foreign `ResetEvent` after the handler signalled turns a handled click into a 3 s timeout.
- **Cross-thread JSAPI.** `JSVAL_IS_FUNCTION`, `AutoRoot` construction (`JS_AddNamedValueRoot`) and destruction (`JS_BeginRequest`/`JS_RemoveValueRoot`/`JS_EndRequest`, `AutoRoot.cpp:10-20`) are executed on the game thread against a runtime owned by the script thread.
- **Phantom clicks.** Hooks that are not drawn still consume clicks: OOG-script hooks while in game, automap hooks while the automap is closed (and at their world-coordinate position), hooks at `x == -1`.
- **Line hooks never receive clicks** (`IsInRange` is constant false).
- **Click function rooting.** `SetClickHandler` stores the value unrooted (`ScreenHook.cpp:279`, rooting commented out `:280-289`). A function passed only through the constructor can be collected while the hook lives, leaving a dangling `jsval` that `Click` dereferences (see [Open questions](#open-questions) for values assigned through the property).

### Hover (dead code)

`Genhook::Hover` (`ScreenHook.cpp:249-264`) is reached only through `HoverHook` (`:28-32`), whose only call site is commented out ("would be nice to enable these events but they bog down too much", `D2Handlers.cpp:341-343`). **Hover handlers never fire.** Latent bugs if re-enabled: `new AutoRoot((owner->GetContext(), hovered))` is a comma expression selecting the `AutoRoot(jsval)` constructor (`ScreenHook.cpp:257`), which uses `ScriptEngine::GetGlobalContext()` (`AutoRoot.cpp:7`) — a static that is never assigned (`ScriptEngine.cpp:26`) → `JS_AddNamedValueRoot(NULL, …)`; `ExecScriptEvent` passes `evt->argc + 1` = 3 arguments from a 2-element array (`ScriptEngine.cpp:580-591`, heap over-read); the `AutoRoot` is never deleted (`ScriptEngine.cpp:600-603`). The intended handler signature (from the event layout) is `(x, y)` with no blocking.

---

## Common property semantics

Applies to all five classes; class tables below reference it.

| Aspect | Behaviour | Source |
|---|---|---|
| Storage | Accessor properties with flags `JSPROP_STATIC_VAR` = `ENUMERATE \| PERMANENT` (not `SHARED`, so the engine allocates a value slot; not `READONLY`) on prototype and instance. | `js32.h:101`, `dependencies/include/jsapi.h:1419` |
| Removed hook | Getter and setter return `JS_TRUE` immediately when the private is `NULL` (after `remove()`, or on `X.prototype`): reads yield the slot value, writes are ignored. | e.g. `JSScreenHook.cpp:82-84`, `:121-123` |
| Integer props | Setter requires `vp.isInt32()` (**Int tag tests**), else silently ignored; getter returns `Int32` (the C++ `uint` reinterpreted). | e.g. `JSScreenHook.cpp:129-130` |
| `x`, `y` | Stored in `POINT location` (LONG) — negatives round-trip; the value `-1` is the destructor's sentinel and suppresses drawing. | `ScreenHook.h:95-104`, `ScreenHook.cpp:317` |
| `visible` | Boolean only; moves the hook between lists under `globalSection`, re-appending at the end. | `ScreenHook.h:115-132` |
| `zorder` | Int, cast to `ushort` (wraps mod 65536; negatives become large). Default 1. Takes effect next frame (sorted per frame). | `JSScreenHook.cpp:152-154`, `ScreenHook.cpp:175` |
| `align` | Int, C-cast to `Align` without range check; meaning per class in [alignment](#coordinates-alignment-and-the-automap-transform). | `JSScreenHook.cpp:144-146` |
| `click` setter | `SetClickHandler(v)`: ignored if `undefined` or owner `NULL`; **any other value is stored** (non-functions are inert at click time; `null` clears). Unrooted. | `ScreenHook.cpp:265-293` |
| `hover` setter | `SetHoverHandler(v)`: ignored if `undefined`; otherwise removes the root on `hovered` (if not void), replaces `hovered` **only if `v` is a function**, re-adds the root — so `null` cannot clear a hover handler. Root is `JS_AddObjectRoot` on a `jsval*` cast to `JSObject**` (`js32.h:96-97`). | `ScreenHook.cpp:295-313` |
| `click` / `hover` getters | Return the stored `jsval` (initially `undefined`). | e.g. `JSScreenHook.cpp:110-115` |
| No `automap` property | The automap flag is constructor-only and unreadable from JS. | `JSScreenHook.h:16-119` |

---

## Value domains: alignment, colors, fonts, opacity

No enumerations are defined in the source beyond `Align`; values pass through to the game unchanged.

| Value | Domain in code | Where it goes |
|---|---|---|
| `align` | `Left=0`, `Right=1`, `Center=2` (`ScreenHook.h:27`) | see alignment table |
| Box / Line `color` | `ushort`, passed as `DWORD dwColor` | palette index for `D2GFX_DrawRectangle` / `D2GFX_DrawLine` (`ScreenHook.cpp:401`, `:423`). D2BS itself uses `0xDF` (console background) and `0xFF` (cursor) (`Console.cpp:229`, `:249`). |
| Text `color` | `ushort` → `D2WIN_DrawText` `dwColor` | D2 text color index (`DrawLogo` uses 4, `ScreenHook.cpp:21`); `ÿc<N>` codes inside the string override it. Index table: [Open questions](#open-questions). |
| Text `font` | `ushort` → `D2WIN_SetTextSize(font)`, restored after drawing | D2 font index; the console uses `Vars.dwConsoleFont` (`Console.cpp:236`). Valid range: [Open questions](#open-questions). |
| Box `opacity` | `ushort` → `D2GFX_DrawRectangle` `dwTrans` | Draw/transparency mode. Legacy empirical notes (`doc/ScreenHooks.h:3-22`): 3 fully transparent, 0 very transparent, 1, 6 (color ignored, black), 2 very opaque, 4 (black, opaque), 5 and 7 opaque with color. D2BS uses 0 (console background) and 7 (cursor) (`Console.cpp:229`, `:249`). Default 0. |
| Image `color` | `ushort`, truncated to `BYTE` at draw | Replaces **palette index 255** of the image; all other indices are drawn as-is (`D2Helpers.cpp:593-597`). Default 0. Not exposed as a property after construction. |
| Line draw arg 6 | constant `0xFF` | `D2GFX_DrawLine` `dwUnk` (`ScreenHook.cpp:401`) |

---

## Image loading

Path from `new Image(path, …)` / `img.location = path` to pixels:

1. **Validation (broken).** `image_ctor` calls `isValidPath(path)` on its local buffer `path` *before* filling it (`JSScreenHook.cpp:610`, `:631-632`): the check runs on uninitialised stack memory (unpredictable result: may throw `"Invalid image file path"`, may pass; `getPathRelScript` `wcslen`s the garbage, `File.cpp:220-249`). The user string is then copied with `swprintf_s(path, 516, L"%s", szText)` and **never validated**; the `location` setter performs no validation at all. A string longer than 515 characters hits the CRT invalid-parameter handler.
2. `ImageHook` constructor stores `_wcsdup(path)` and calls `LoadCellFile(location, 3)` (`ScreenHook.h:245-250`); `SetImage` calls `LoadCellFile(location)` with the wide overload's default `3` (`ScreenHook.cpp:386`, `D2Helpers.h:58`).
3. `LoadCellFile(const wchar_t*, 3)` (`D2Helpers.cpp:531-544`): builds `Vars.szScriptPath + L"\\" + path` (absolute — `szScriptPath` = DLL directory + `ScriptPath`, `Helpers.cpp:94`/`:133`, `D2BS.cpp:37-39`). If `CreateFileW` can open it → `LoadCellFile(fullpath, FALSE)`. Otherwise → `LoadCellFile(path, TRUE)`, which for a wide string logs `"Cannot specify wide character path for MPQ: …"` and returns `NULL` (`:525-528`). **Images can only come from the file system; MPQ (DC6) assets cannot be loaded** (the narrow MPQ branch using `D2WIN_LoadCellFile`, `D2Helpers.cpp:508-516`, `D2Ptrs.h:438`, is unreachable from hooks).
4. **Cache.** `hash = sfh((char*)widePath, strlen((char*)widePath))` (`D2Helpers.cpp:546`): `strlen` on UTF-16 stops at the first zero byte, so for an ASCII path the hash covers **only the first character (the drive letter)** (`stringhash.cpp:13-40`). If `Vars.mCachedCellFiles` (`std::map<uint32, CellFile*>`, global, never cleared, `D2BS.h:102`) has that key, the cached pointer is returned (`:547-548`). Consequence: after the first file image is loaded, every other image path on the same drive returns the **first** image; if the first load failed (non-8-bit BMP), the cached `NULL` makes every later image fail.
5. **Decode** (`:550-555`): `myInitCellFile(LoadBmpCellFile(path))`. `LoadBmpCellFile` (`D2Helpers.cpp:688-700`) reads the whole file and accepts only `'BM'`, `biBitCount == 8`, `BI_RGB`; it RLE-encodes the rows into an in-memory DC6 image (`D2Helpers.cpp:643-672`: header `{version 6, flags 1, encoding 0, termination 0xEEEEEEEE, 1 dir, 1 frame, …, width, height, …}`), treating **palette index 0 as transparent**; the BMP's own palette is ignored (indices map to the current D2 palette). Rows are read with BMP 4-byte stride; a negative (top-down) `biHeight` is not handled. Buffer allocated with `new BYTE[]`.
6. `myInitCellFile` → `D2CMP_InitCellFile(cf, &cf, "?", 0, -1, "?")` (`D2Helpers.cpp:702-706`, RVA `0x201340`) converts it into a `CellFile` (`D2Structs.h:76-88`: DC6 header layout; D2BS reuses the two high bytes of the flags field as `mylastcol` / `mytabno` for its color-table trick).
7. **Draw** via `myDrawAutomapCell` (see [Primitives](#primitives)); cell `0` only (`cells[0]`).
8. **Re-pointing** (`img.location = p`, `ScreenHook.cpp:380-388`): `free(location); delete[] image;` — frees the *cached, shared* `CellFile` without removing it from the cache and without `globalSection` — then reloads, which (same drive-letter hash) returns the just-freed pointer. Changing `location` on a loaded image is a use-after-free in both the draw thread and every other `Image` sharing the cache entry.

---

## Frame

- **JSClass:** `"Frame"`, `JSCLASS_HAS_PRIVATE`, property/enumerate/resolve/convert stubs, finalizer `hook_finalize`, construct `frame_ctor` (`JSGlobalClasses.cpp:44-46`, `JSCLASS_SPEC` `js32.h:163-164`); `global_classes` entry `JSGlobalClasses.cpp:162` (**Class registration**).
- **Constructor:** real constructor; instances are obtained only via `new Frame(...)` / `Frame(...)`.
- **Private data:** `FrameHook*` (`ScreenHook.h:376-413`): `Genhook` fields + `uint xsize, ysize`. Owned by the JS object; freed by `remove()` or `hook_finalize` (only the `Genhook` part is destroyed — nothing extra to leak for Frame).
- **Identity & lifetime:** no game pointer; pure D2BS state. See [Ownership and lifetime](#ownership-and-lifetime).

### `new Frame(x, y, xsize, ysize, align, automap, click, hover)`

Creates a D2 UI-frame (border) hook, drawn in game only.
- **Native:** `frame_ctor` at `JSScreenHook.cpp:37`; registered as the `Frame` class constructor at `JSGlobalClasses.cpp:162` (`JS_InitClass` nargs 0, `ScriptEngine.cpp:232`).
- **Arguments / overloads:** positional, all optional; an argument that fails its test keeps the default silently. 0 `x` int (0); 1 `y` int (0); 2 `xsize` int (0); 3 `ysize` int (0); 4 `align` int (0 = Left; any int); 5 `automap` boolean (false; stored, ignored by `Draw`); 6 `click` function (none); 7 `hover` function (none) (`JSScreenHook.cpp:45-60`). Extra arguments ignored. Never throws for bad argument types.
- **Returns:** the new `Frame` object. Throws `"Failed to create frame object"` if `BuildObject` returns NULL (`:62-64`); the `"Failed to create framehook"` branch is unreachable (`new` throws on failure) (`:69-70`).
- **Preconditions:** none checked. `gameState` forced to `IG` (`:66-67`), so it is drawn only by `GameDraw` in game regardless of the creating script; an OOG script can create one (never drawn, still clickable).
- **Threading & blocking:** script thread; `globalSection` briefly (list insert). The hook is drawable by the game thread from inside the base constructor, before `JS_SetPrivate` (`:72`) and handler assignment (`:73-74`).
- **Side effects:** heap `FrameHook`; appended to `visible`; `zorder` 1; hover function (if any) rooted with `JS_AddRoot`.
- **Game internals:** `D2GFX_DrawFrame` → `D2GFX_DrawRectFrame_STUB` (`D2Helpers.cpp:919-925`, RECT* moved from `ecx` to `eax`) → `D2CLIENT_DrawRectFrame` (RVA `0x52E50`, `D2Ptrs.h:118`); `p_D2CLIENT_AutomapOn` for the automap gate.
- **Quirks / bugs:** `automap` flag only gates visibility (drawn only while the automap is open) but coordinates are never transformed; Right alignment shifts the frame right by `xsize/2`; hit-test ignores alignment; code comment lists the same order as the code (`:36`).

### Properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `FRAME_X` (0) | int | R/W | — | `Genhook::location.x` (`GetX`/`SetX`, `ScreenHook.h:144`, `:95`) | getter `JSScreenHook.cpp:89-91`, setter `:128-131` |
| `y` | `FRAME_Y` (1) | int | R/W | — | `location.y` | `:92-94`, `:132-135` |
| `xsize` | `FRAME_XSIZE` (2) | int | R/W | — | `FrameHook::xsize` (`ScreenHook.h:396`, `:407`) | width; `:95-97`, `:136-139` |
| `ysize` | `FRAME_YSIZE` (3) | int | R/W | — | `FrameHook::ysize` (`ScreenHook.h:401`, `:410`) | height; `:98-100`, `:140-143` |
| `visible` | `FRAME_VISIBLE` (4) | boolean | R/W | — | `isVisible` / list membership | `:104-106`, `:148-151` |
| `align` | `FRAME_ALIGN` (5) | int | R/W | — | `alignment` | `:101-103`, `:144-147` |
| `click` | `FRAME_ONCLICK` (6) | any | R/W | — | `clicked` | `:110-112`, `:156-158` |
| `hover` | `FRAME_ONHOVER` (7) | any | R/W | never fires | `hovered` | `:113-115`, `:159-161` |
| `zorder` | `FRAME_ZORDER` (8) | int | R/W | — | `zorder` (ushort) | `:107-109`, `:152-155` |

Enum and spec: `JSScreenHook.h:16-27`. Getter `frame_getProperty` `JSScreenHook.cpp:81`, setter `frame_setProperty` `JSScreenHook.cpp:120`. Semantics: [Common property semantics](#common-property-semantics).

### `Frame.prototype.remove()`

Destroys the C++ hook immediately; the JS object becomes an inert shell.
- **Native:** `hook_remove` at `JSScreenHook.cpp:18`; registered `JS_FS("remove", hook_remove, 0, FUNCTION_FLAGS)` at `JSScreenHook.h:29` (arity 0, `JSFUN_STUB_GSOPS`), on `Frame.prototype` and on every instance.
- **Arguments / overloads:** none; extra arguments ignored. `this` = `JS_THIS_OBJECT(cx, vp)`.
- **Returns:** never sets `rval` → **callee-return** (evaluates to the `remove` function object).
- **Preconditions:** none. No class check (**Private without class check**): the same native serves all five classes, and calling it on a non-hook object that has a private pointer (e.g. a `Unit`) `delete`s that pointer as a `Genhook`.
- **Threading & blocking:** script thread; holds `globalSection` across the delete, so it waits for an in-progress draw pass or click dispatch (which can last 3 s per pending handler; from inside a click handler it blocks until that timeout).
- **Side effects:** `delete (Genhook*)private` → `~Genhook` only (unlink, `owner = NULL`; see non-virtual destructor) → gone from the next frame; `JS_SetPrivate(obj, NULL)`. `JS_ValueToObject(cx, JSVAL_VOID, &obj)` only overwrites the local (`JSScreenHook.cpp:29`). Idempotent.
- **Game internals:** none.
- **Quirks / bugs:** leaves a dangling GC root if a hover function was set; leaks `TextHook::text` / `ImageHook::location` for those classes.

---

## Box

- **JSClass:** `"Box"`, `JSCLASS_HAS_PRIVATE`, finalizer `hook_finalize`, construct `box_ctor` (`JSGlobalClasses.cpp:48-50`); `global_classes` entry `JSGlobalClasses.cpp:163`.
- **Constructor:** real constructor; instances only from `new Box(...)` / `Box(...)`.
- **Private data:** `BoxHook*` (`ScreenHook.h:327-374`): `Genhook` + `uint xsize, ysize; ushort color`; `opacity` lives in `Genhook`. Freed by `remove()`/finalizer.
- **Identity & lifetime:** pure D2BS state; see [Ownership and lifetime](#ownership-and-lifetime).

### `new Box(x, y, xsize, ysize, color, opacity, align, automap, click, hover)`

Creates a filled-rectangle hook.
- **Native:** `box_ctor` at `JSScreenHook.cpp:169`; registered at `JSGlobalClasses.cpp:163` (nargs 0).
- **Arguments / overloads:** 0 `x` int (0); 1 `y` int (0); 2 `xsize` int (0); 3 `ysize` int (0); 4 `color` int → `ushort` (0); 5 `opacity` int → `ushort` (0); 6 `align` int (0); 7 `automap` boolean (false); 8 `click` function; 9 `hover` function (`JSScreenHook.cpp:179-198`). Wrong-typed → default, silently.
- **Returns:** new `Box`. Throws `"Failed to create box object"` (`:200-202`); `"Unable to initalize a box class."` unreachable (`:206-207`).
- **Preconditions:** none; `gameState` = `OOG` if the script is `OutOfGame`, else `IG` (`:172`).
- **Threading & blocking:** as `Frame`.
- **Side effects:** as `Frame`.
- **Game internals:** `D2GFX_DrawRectangle` (RVA `0xF6300`, `D2Ptrs.h:378`); automap: `ScreenToAutomap` (`p_D2CLIENT_Divisor`, `p_D2CLIENT_Offset`, `D2CLIENT_GetAutomapSize`), `p_D2CLIENT_AutomapOn`.
- **Quirks / bugs:** Right alignment adds `xsize/2` (`ScreenHook.cpp:413-415`); hit-test ignores alignment and the automap transform; automap boxes project the two corners independently.

### Properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `BOX_X` (0) | int | R/W | — | `location.x` | |
| `y` | `BOX_Y` (1) | int | R/W | — | `location.y` | |
| `xsize` | `BOX_XSIZE` (2) | int | R/W | — | `BoxHook::xsize` (`ScreenHook.h:349`, `:365`) | width |
| `ysize` | `BOX_YSIZE` (3) | int | R/W | — | `BoxHook::ysize` (`:354`, `:368`) | height |
| `color` | `BOX_COLOR` (4) | int | R/W | — | `BoxHook::color` (ushort) (`:359`, `:371`) | palette index |
| `opacity` | `BOX_OPACITY` (5) | int | R/W | — | `Genhook::opacity` (ushort) (`ScreenHook.h:110`, `:153`) | `dwTrans` |
| `visible` | `BOX_VISIBLE` (6) | boolean | R/W | — | `isVisible` | |
| `align` | `BOX_ALIGN` (7) | int | R/W | — | `alignment` | |
| `click` | `BOX_ONCLICK` (8) | any | R/W | — | `clicked` | |
| `hover` | `BOX_ONHOVER` (9) | any | R/W | never fires | `hovered` | |
| `zorder` | `BOX_ZORDER` (10) | int | R/W | — | `zorder` | |

Enum and spec: `JSScreenHook.h:38-51`. Getter `box_getProperty` `JSScreenHook.cpp:217`, setter `box_setProperty` `JSScreenHook.cpp:262`.

### `Box.prototype.remove()`

Destroys the C++ hook immediately.
- **Native:** `hook_remove` at `JSScreenHook.cpp:18`; registered at `JSScreenHook.h:53` (arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** **callee-return**.
- **Preconditions:** none; no class check.
- **Threading & blocking:** script thread; `globalSection`.
- **Side effects:** as [`Frame.prototype.remove`](#frameprototyperemove).
- **Game internals:** none.
- **Quirks / bugs:** as `Frame`.

---

## Line

- **JSClass:** `"Line"`, `JSCLASS_HAS_PRIVATE`, finalizer `hook_finalize`, construct `line_ctor` (`JSGlobalClasses.cpp:52-54`); `global_classes` entry `JSGlobalClasses.cpp:164`.
- **Constructor:** real constructor; instances only from `new Line(...)` / `Line(...)`.
- **Private data:** `LineHook*` (`ScreenHook.h:277-325`): `Genhook` + `uint x2, y2; ushort color`. Alignment fixed `Left`.
- **Identity & lifetime:** pure D2BS state.

### `new Line(x, y, x2, y2, color, automap, click, hover)`

Creates a line-segment hook from `(x, y)` to `(x2, y2)`.
- **Native:** `line_ctor` at `JSScreenHook.cpp:319`; registered at `JSGlobalClasses.cpp:164` (nargs 0).
- **Arguments / overloads:** 0 `x` int (0); 1 `y` int (0); 2 `x2` int (0); 3 `y2` int (0); 4 `color` int → `ushort` (0); 5 `automap` boolean (false); 6 `click` function; 7 `hover` function (`JSScreenHook.cpp:328-343`). No `align` argument.
- **Returns:** new `Line`. Throws `"Failed to create line object"` (`:345-347`); `"Unable to initalize a line class."` unreachable.
- **Preconditions:** none; `gameState` from script state (`:322`).
- **Threading & blocking:** as `Frame`.
- **Side effects:** as `Frame`.
- **Game internals:** `D2GFX_DrawLine` (RVA `0xF6380`, `D2Ptrs.h:379`) with last argument `0xFF`; automap transform of both endpoints.
- **Quirks / bugs:** `IsInRange` is constant `false` (`ScreenHook.h:296-298`): `click` handlers are accepted but can never fire.

### Properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `LINE_X` (0) | int | R/W | — | `location.x` | start point |
| `y` | `LINE_Y` (1) | int | R/W | — | `location.y` | |
| `x2` | `LINE_XSIZE` (2) | int | R/W | — | `LineHook::x2` (`ScreenHook.h:300`, `:316`) | absolute end point (enum name says "size") |
| `y2` | `LINE_YSIZE` (3) | int | R/W | — | `LineHook::y2` (`:305`, `:319`) | |
| `color` | `LINE_COLOR` (4) | int | R/W | — | `LineHook::color` (`:310`, `:322`) | palette index |
| `visible` | `LINE_VISIBLE` (5) | boolean | R/W | — | `isVisible` | |
| `click` | `LINE_ONCLICK` (6) | any | R/W | never fires (no hit area) | `clicked` | |
| `hover` | `LINE_ONHOVER` (7) | any | R/W | never fires | `hovered` | |
| `zorder` | `LINE_ZORDER` (8) | int | R/W | — | `zorder` | |

Enum and spec: `JSScreenHook.h:62-73`. Getter `line_getProperty` `JSScreenHook.cpp:363`, setter `line_setProperty` `JSScreenHook.cpp:402`.

### `Line.prototype.remove()`

Destroys the C++ hook immediately.
- **Native:** `hook_remove` at `JSScreenHook.cpp:18`; registered at `JSScreenHook.h:75` (arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** **callee-return**.
- **Preconditions:** none; no class check.
- **Threading & blocking:** script thread; `globalSection`.
- **Side effects:** as [`Frame.prototype.remove`](#frameprototyperemove).
- **Game internals:** none.
- **Quirks / bugs:** as `Frame`.

---

## Text

- **JSClass:** `"Text"`, `JSCLASS_HAS_PRIVATE`, finalizer `hook_finalize`, construct `text_ctor` (`JSGlobalClasses.cpp:56-58`); `global_classes` entry `JSGlobalClasses.cpp:165`.
- **Constructor:** real constructor; instances only from `new Text(...)` / `Text(...)`.
- **Private data:** `TextHook*` (`ScreenHook.h:188-233`): `Genhook` + `wchar_t* text` (`_wcsdup` copy, `:200`), `ushort font, color`. `text` is leaked on `remove()`/finalize (non-virtual destructor).
- **Identity & lifetime:** pure D2BS state.

### `new Text(text, x, y, color, font, align, automap, click, hover)`

Creates a text hook drawn with D2's font renderer.
- **Native:** `text_ctor` at `JSScreenHook.cpp:451`; registered at `JSGlobalClasses.cpp:165` (nargs 0).
- **Arguments / overloads:** 0 `text` string (default `""`; only taken if `JSVAL_IS_STRING` — numbers etc. are **not** coerced and give `""`; the `JS_ValueToString` call is redundant) (`:462-463`); 1 `x` int (0); 2 `y` int (0) — baseline; 3 `color` int → `ushort` (0); 4 `font` int → `ushort` (0); 5 `align` int (0); 6 `automap` boolean (false); 7 `click` function; 8 `hover` function (`:466-481`). Verified order: `(text, x, y, color, font, align, automap, click, hover)`; the code comment at `:450` wrongly says "onHover, onText".
- **Returns:** new `Text`. If `JS_GetStringCharsZ` returns NULL (OOM) → returns `JS_TRUE` without rval → **callee-return** (evaluates to the `Text` constructor function) (`:464-465`). Throws `"Failed to create text object"` (`:483-485`); `"Failed to create texthook"` unreachable.
- **Preconditions:** none; `gameState` from script state (`:454`).
- **Threading & blocking:** as `Frame`.
- **Side effects:** as `Frame`; the string is copied.
- **Game internals:** `D2WIN_SetTextSize`, `D2WIN_DrawText`, `D2WIN_GetTextSize` (`D2Ptrs.h:445-447`); width computed every frame and every hit test via `CalculateTextLen` (`D2Helpers.cpp:212-225`).
- **Quirks / bugs:** automap alignment offset is a pixel width subtracted from a world coordinate; `font`/`color` not range-checked.

### Properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `TEXT_X` (0) | int | R/W | — | `location.x` | |
| `y` | `TEXT_Y` (1) | int | R/W | — | `location.y` | baseline |
| `color` | `TEXT_COLOR` (2) | int | R/W | — | `TextHook::color` (`ScreenHook.h:217`, `:227`) | D2 text color index |
| `font` | `TEXT_FONT` (3) | int | R/W | — | `TextHook::font` (`:212`, `:224`) | `D2WIN_SetTextSize` index |
| `text` | `TEXT_TEXT` (4) | string | R/W | — | `TextHook::text` (`GetText` `:230`; `SetText` `ScreenHook.cpp:339`) | getter returns `JS_InternUCString(cx, text)` (`JSScreenHook.cpp:522`); setter requires a string, copies under `globalSection`; non-strings ignored |
| `align` | `TEXT_ALIGN` (5) | int | R/W | — | `alignment` | |
| `visible` | `TEXT_VISIBLE` (6) | boolean | R/W | — | `isVisible` | |
| `click` | `TEXT_ONCLICK` (7) | any | R/W | — | `clicked` | |
| `hover` | `TEXT_ONHOVER` (8) | any | R/W | never fires | `hovered` | |
| `zorder` | `TEXT_ZORDER` (9) | int | R/W | — | `zorder` | |

Enum and spec: `JSScreenHook.h:84-96`. Getter `text_getProperty` `JSScreenHook.cpp:501`, setter `text_setProperty` `JSScreenHook.cpp:543`. Interned strings: see [Open questions](#open-questions).

### `Text.prototype.remove()`

Destroys the C++ hook immediately.
- **Native:** `hook_remove` at `JSScreenHook.cpp:18`; registered at `JSScreenHook.h:98` (arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** **callee-return**.
- **Preconditions:** none; no class check.
- **Threading & blocking:** script thread; `globalSection`.
- **Side effects:** as [`Frame.prototype.remove`](#frameprototyperemove); the `text` buffer leaks.
- **Game internals:** none.
- **Quirks / bugs:** as `Frame`.

---

## Image

- **JSClass:** `"Image"`, `JSCLASS_HAS_PRIVATE`, finalizer `hook_finalize`, construct `image_ctor` (`JSGlobalClasses.cpp:60-62`); `global_classes` entry `JSGlobalClasses.cpp:166`.
- **Constructor:** real constructor; instances only from `new Image(...)` / `Image(...)`.
- **Private data:** `ImageHook*` (`ScreenHook.h:235-275`): `Genhook` + `wchar_t* location` (user path, `_wcsdup`), `CellFile* image` (shared pointer from the global cache, may be `NULL`), `ushort color`. `location` leaks on remove/finalize; `image` is never freed there (cache-owned).
- **Identity & lifetime:** the `CellFile` is shared by all `Image` objects whose path hashes equal (in practice all file images on one drive) and lives until process exit.

### `new Image(path, x, y, color, align, automap, click, hover)`

Creates a hook drawing cell 0 of an image loaded from an 8-bit BMP under the script directory.
- **Native:** `image_ctor` at `JSScreenHook.cpp:600`; registered at `JSGlobalClasses.cpp:166` (nargs 0).
- **Arguments / overloads:** 0 `path` string (default `""`, non-strings not coerced) (`:612-613`); 1 `x` int (0); 2 `y` int (0) — vertical centre; 3 `color` int → `ushort` (0; replaces palette index 255); 4 `align` int (0); 5 `automap` boolean (false); 6 `click` function; 7 `hover` function (`:616-629`). Code comment at `:599` mislabels 6/7 as "onHover, onimage".
- **Returns:** new `Image` (also when the image failed to load — it is then never drawn and never hit). Throws `"Invalid image file path"` depending on uninitialised memory (`:631-634`), `"Failed to create image object"` (`:636-638`); `"Failed to create ImageHook"` unreachable. `JS_GetStringCharsZ` NULL → **callee-return** (`:614-615`).
- **Preconditions:** none; `gameState` from script state (`:603`).
- **Threading & blocking:** script thread; synchronous file I/O (`CreateFileW`, whole-file read) inside the constructor; unsynchronised access to the global image cache.
- **Side effects:** may read a file from disk; may insert into `Vars.mCachedCellFiles`; `Log()`s "Cannot specify wide character path for MPQ" when the file is not found (`D2Helpers.cpp:526`). The 10th C++ argument passed as `3` (`fromFile`) is unused (`JSScreenHook.cpp:640`, `ScreenHook.h:245-246`).
- **Game internals:** `D2CMP_InitCellFile` (RVA `0x201340`), `D2GFX_DrawAutomapCell2` (RVA `0xF6480`), `CellFile`/`GfxCell`/`CellContext` (`D2Structs.h:53-94`).
- **Quirks / bugs:** see [Image loading](#image-loading) (broken validation, drive-letter cache key, MPQ impossible) and the Left-alignment hit-test offset.

### Properties

| Property | Id/enum | JS type | R/W | Applies to / conditions | Value source | Notes |
|---|---|---|---|---|---|---|
| `x` | `IMAGE_X` (0) | int | R/W | — | `location.x` | |
| `y` | `IMAGE_Y` (1) | int | R/W | — | `location.y` | vertical centre |
| `location` | `IMAGE_LOCATION` (2) | string | R/W | — | `ImageHook::location` (`GetImage` `ScreenHook.h:269`; `SetImage` `ScreenHook.cpp:380`) | getter `JS_InternUCString` of the stored user path (`JSScreenHook.cpp:669`); setter requires a string, no validation, no lock, frees the shared cached image → use-after-free |
| `align` | `IMAGE_ALIGN` (3) | int | R/W | — | `alignment` | non-0/1 values behave as Center |
| `visible` | `IMAGE_VISIBLE` (4) | boolean | R/W | — | `isVisible` | |
| `click` | `IMAGE_ONCLICK` (5) | any | R/W | only when `image` loaded | `clicked` | |
| `hover` | `IMAGE_ONHOVER` (6) | any | R/W | never fires | `hovered` | |
| `zorder` | `IMAGE_ZORDER` (7) | int | R/W | — | `zorder` | |

No `color` property (`ImageHook::SetColor`/`GetColor` exist, `ScreenHook.h:263-274`, but are not bound). Enum and spec: `JSScreenHook.h:107-117`. Getter `image_getProperty` `JSScreenHook.cpp:654`, setter `image_setProperty` `JSScreenHook.cpp:690`.

### `Image.prototype.remove()`

Destroys the C++ hook immediately.
- **Native:** `hook_remove` at `JSScreenHook.cpp:18`; registered at `JSScreenHook.h:119` (arity 0, `FUNCTION_FLAGS`).
- **Arguments / overloads:** none.
- **Returns:** **callee-return**.
- **Preconditions:** none; no class check.
- **Threading & blocking:** script thread; `globalSection`.
- **Side effects:** as [`Frame.prototype.remove`](#frameprototyperemove); `location` string leaks; the cached `CellFile` is untouched.
- **Game internals:** none.
- **Quirks / bugs:** as `Frame`.

---

## Globals

Both are `JS_FN` entries of `global_funcs` (`JSGlobalFuncs.h:73`, arity 1, `FUNCTION_FLAGS`), defined on every script global (`ScriptEngine.cpp:345`).

### `screenToAutomap(point | x, y)`

Projects a world (map) coordinate to automap pixel coordinates (the transform automap hooks use).
- **Native:** `screenToAutomap` at `JSScreenHook.cpp:736`; registered at `JSGlobalFuncs.h:73` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `(x, y)` — `argc == 2`, both `JSVAL_IS_INT` (**Int tag tests**) → converted with `JS_ValueToInt32` (`:763-767`). Otherwise throws `"screenToAutomap expects two arguments to be two integers"` (`:777`).
  - `(point)` — `argc == 1` and an object: `JS_GetProperty` `x`/`y` failure → `"Failed to get x and/or y values"`; either not int-tagged → `"Input has an x or y, but they aren't the correct type!"`; otherwise **always** throws `"Failed to convert x and/or y values"`, because the second conversion's result is not compared (`JS_ValueToInt32(cx, x, &ix) == JS_FALSE || JS_ValueToInt32(cx, y, &iy)`, `:748`). Non-object (incl. `null`) → `"Invalid object specified to screenToAutomap"` (`:760`).
  - any other `argc` → `"Invalid arguments specified for screenToAutomap"` (`:779`).
- **Returns:** a new plain `Object` `{x, y}` (ints) computed by `ScreenToAutomap` (formula in [Coordinates](#coordinates-alignment-and-the-automap-transform)). `"Failed to set x and/or y values"` if `JS_SetProperty` fails.
- **Preconditions:** none checked (no in-game test). Divides by `*p_D2CLIENT_Divisor`; a zero value would raise an integer divide-by-zero exception (whether it can be 0 out of game: [Open questions](#open-questions)).
- **Threading & blocking:** script thread; no locks; reads game globals and calls `D2CLIENT_GetAutomapSize` concurrently with the game thread.
- **Side effects:** none (the 2-arg path overwrites its own `argv[0..1]` slots with the results, `:770-771`).
- **Game internals:** `p_D2CLIENT_Divisor` (RVA `0x311254`, `D2Ptrs.h:185`), `p_D2CLIENT_Offset` (RVA `0x3A5198`, `D2Ptrs.h:153`), `D2CLIENT_GetAutomapSize` (RVA `0x5A710`, `D2Ptrs.h:89`); helper `ScreenToAutomap` `D2Helpers.cpp:364`.
- **Quirks / bugs:** the object form is unusable; its dead tail would have returned `{x: <the input object>, y: argv[1]}` (argv over-read) (`:755-756`). The name is misleading (input is world space, not screen space). Non-integral inputs (e.g. `me.x / 2` = 12.5) are rejected.

### `automapToScreen(point | x, y)`

Applies D2BS's automap→screen formula `x' = 8 − Offset.x + x·M`, `y' = 8 + Offset.y + y·M`.
- **Native:** `automapToScreen` at `JSScreenHook.cpp:783`; registered at `JSGlobalFuncs.h:73` (declared arity 1, `FUNCTION_FLAGS`).
- **Arguments / overloads:**
  - `(x, y)` — `argc == 2`, both int-tagged → `AutomapToScreen(&{ix, iy})` (`:818-834`). Otherwise `"automapToScreen expects two arguments to be two integers"` (`:836`). `"Failed to convert x and/or y values"` only if `JS_ValueToInt32` fails (not possible for ints).
  - `(point)` — `argc == 1`, object: same checks/messages as `screenToAutomap` and the same unconditional `"Failed to convert x and/or y values"` (`:797-800`). Non-object → `"Invalid object specified to automapToScreen"` (`:815`).
  - other `argc` → `"Invalid arguments specified for automapToScreen"` (`:838`).
- **Returns:** new plain `Object` `{x, y}`.
- **Preconditions:** none checked; no division, so no crash risk from zero scale.
- **Threading & blocking:** script thread; redundant `JS_BeginRequest`/`JS_EndRequest` pairs around conversions (`:820-825`); no locks.
- **Side effects:** none.
- **Game internals:** `p_D2CLIENT_AutomapMode` (int, RVA `0x311254` — **same address as `Divisor`**, `D2Ptrs.h:152` vs `:185`), `p_D2CLIENT_Offset`; helper `AutomapToScreen` `D2Helpers.cpp:378-381`.
- **Quirks / bugs:** not the inverse of `screenToAutomap` (no un-rotation, opposite sign on `Offset.y`, the ±8 terms do not cancel). The object form's dead tail would have written the *unconverted* `ix`/`iy` back into the caller's object and returned it (`:805-813`).

---

## Facts relevant to an RPC replacement

Synthesis lives in [../rpc-considerations.md](../rpc-considerations.md); the screen-hook facts it needs:

- All drawable state is already C++-side (`Genhook` hierarchy). The JS layer adds only: construction, accessor marshalling, and lifetime-by-reachability. An RPC layer can create the same objects directly, but must supply explicit handles, an explicit destroy, and an owner/session for cleanup (today: per-script, `Genhook::Clean` + finalizers), since nothing else enumerates or frees hooks.
- The draw side needs only `p_D2CLIENT_AutomapOn`, the automap projection (`p_D2CLIENT_Divisor`, `p_D2CLIENT_Offset`, `D2CLIENT_GetAutomapSize`) and these game functions (`D2GFX_DrawRectangle`, `D2GFX_DrawLine`, `D2CLIENT_DrawRectFrame`, `D2WIN_SetTextSize`/`D2WIN_DrawText`/`D2WIN_GetTextSize`, `D2GFX_DrawAutomapCell2` + `D2CMP_InitCellFile` for images), all called from `GameDraw`/`GameDrawOOG` on the game thread.
- Click callbacks are synchronous today: the game thread blocks up to 3 s per hook waiting for a script. A networked client cannot be waited on from the WH_MOUSE hook; "consume the click" must be a hook attribute decided locally, with the notification delivered asynchronously.
- Hover is not implemented; Line hooks are not clickable; hit tests ignore alignment (Box/Frame), automap and draw state.
- Coordinates: client pixels (in-game size from `p_D2CLIENT_ScreenSizeX/Y`, OOG fixed 800×600), or world coordinates projected per frame for automap hooks.
- Images: only 8-bit BMPs from the script directory; the existing cache is keyed by drive letter and must be replaced.

---

## Legacy-doc discrepancies

| Legacy docs | Code |
|---|---|
| `doc/ScreenHooks.h:37-45` and every class doc describe a working `hover` handler `(x, y)`. | Hover is never dispatched (`D2Handlers.cpp:343` commented out); the re-enable path is itself broken (`ScreenHook.cpp:257`, `ScriptEngine.cpp:591`). |
| `doc/ScreenHooks.h:25-35`: click handler `(button, x, y)` returning bool. | Matches arguments; only a strict boolean `true` blocks the click (`ScriptEngine.cpp:675`); `this` is the global object, not the hook (`:674`); a slow handler (>3 s) is ignored. |
| `doc/Line.h:16-18`: constructor `x2`/`y2` are "xsize (width)" / "ysize (height)". | Absolute end-point coordinates (`ScreenHook.cpp:401`); `doc/Line.h:49-55` (properties) is correct. |
| `doc/Line.h:27-31`: Line click handler. | `LineHook::IsInRange` always false (`ScreenHook.h:296-298`). |
| `doc/Text.h:16`: `y` is "top". | `y` is the baseline; hit range `y−h … y` (`ScreenHook.cpp:336`). |
| `doc/Image.h:15-17`: `x` left, `y` top. | Left edge depends on `align`; vertically centred on `y` (`D2Helpers.cpp:586`, `ScreenHook.cpp:372`); Left-aligned hit box is shifted one width right (`ScreenHook.cpp:371`). |
| `doc/Image.h:13`, `:82-84`: "filename to load the image from". | Only 8-bit uncompressed BMP files relative to the script folder; no MPQ/DC6 (`D2Helpers.cpp:525-544`, `:694`); cache keyed by first path character (`:546`). |
| `doc/Image.h:19`: "color of the Image". | Replaces palette index 255 only (`D2Helpers.cpp:597`); not readable/settable after construction. |
| `doc/Frame.h:29-30`, `doc/Box.h:35-36`, `doc/Text.h:32-33`, `doc/Image.h:31-32`, `doc/Line.h:24-25`: `automap` = "automap coordinate space". | Inputs are world coordinates projected each frame; Frame ignores the flag except as a visibility gate (`ScreenHook.cpp:436-451`, `:41`). |
| `doc/Frame.h:21-27`, `doc/Box.h:27-33`: align `1` = Right. | Box/Frame "Right" shifts the shape right by half its width (`ScreenHook.cpp:413-415`, `:442-444`); hit test ignores align. |
| `doc/*.h` `remove()`: "Remove … and destroy the corresponding object." | Deletes the C++ hook only; the JS object remains (null private); derived-class buffers leak (non-virtual `~Genhook`, `ScreenHook.h:52`). |
| `doc/globalFuncs.h:1851-1893`: `screenToAutomap(Object)` / `automapToScreen(Object)` documented; "screen coordinates to automap". | Object forms always throw (`JSScreenHook.cpp:748`, `:797`); `screenToAutomap` input is world coordinates; `automapToScreen` is not its inverse. |
| `doc/ScreenHooks.h:3-22` opacity 0–7. | Consistent: passed unchanged as `dwTrans` (`ScreenHook.cpp:423`); no range check. |
| Code comments `JSScreenHook.cpp:450`, `:599` give arg order "…, onHover, onText/onimage". | Code reads click before hover (`:478-481`, `:626-629`). |

---

## Open questions

1. **Font indices.** Valid range and glyph sets for `D2WIN_SetTextSize(font)` in 1.14d are not defined in this repo (community convention lists 0–13, unverified here).
2. **Text color indices.** The meaning of each `D2WIN_DrawText` color index (and equivalence to `ÿc<N>` codes) is not defined in source.
3. **Opacity/draw modes.** `D2GFX_DrawRectangle`'s `dwTrans` semantics are only known empirically (`doc/ScreenHooks.h`).
4. **Image vertical placement.** Whether `D2GFX_DrawAutomapCell2` treats `ypos` as the cell's bottom (making the image centred on `y`, consistent with `IsInRange`) or top (the clip test at `D2Helpers.cpp:589` treats `ypos2` as the top) cannot be settled from source.
5. **`D2CMP_InitCellFile` output.** Whether it fixes the DC6 buffer up in place (`*Out == cf`) or allocates a new game-heap `CellFile` determines whether `SetImage`'s `delete[] image` frees a `new BYTE[]` buffer or game-heap memory, and whether the original buffer leaks.
6. **Rooting of click functions assigned via the property.** The properties are slotful (no `JSPROP_SHARED`); whether this SpiderMonkey build stores the setter's value in the slot (keeping a property-assigned `click` function reachable through the hook object) is engine behaviour not present in the repo. Functions passed only to the constructor are definitely unrooted.
7. **Exceptions in click handlers.** The handler runs inside `operationCallback`/`delay()`; what happens to an exception it leaves pending on the context (reported, swallowed, or surfacing in the interrupted script) is engine/embedding behaviour — see [../spidermonkey/embedding.md](../spidermonkey/embedding.md).
8. **`p_D2CLIENT_Divisor` out of game.** If it is 0 in menus, `screenToAutomap` (and any automap hook drawn OOG) divides by zero.
9. **`JS_InternUCString` pinning.** Whether interned strings returned by the `text`/`location` getters are pinned for the runtime's lifetime in this SM version (accumulating one atom per distinct value read) is not visible in the headers.
10. **Draw-order position of `0x453B30`.** Which D2Client routine is replaced by the `GameDraw` jump, and thus whether in-game hooks paint above or below the game's UI panels, is not determinable here (see [../memory/patches-and-hooks.md](../memory/patches-and-hooks.md)).
11. **Frame OOG crash.** Why `D2CLIENT_DrawRectFrame` crashes out of game (the reason given for forcing `IG`, `JSScreenHook.cpp:66`) is not documented in source.
12. **Newlines in text.** Whether `D2WIN_DrawText` renders `\n` as a line break is not determinable from source.

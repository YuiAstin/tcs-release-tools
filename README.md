# TCS Release Tools

Workflow tools for building "The Cheat Script" release tables (ColonelRVH
format): a browser-based release builder plus the Python/Lua tooling behind it.

**Web builder:** https://yuiastin.github.io/tcs-release-tools/ — drop a raw .CT,
assign features to [Stats]/[Battle]/[Extra], build, lint, download. Nothing to
install; everything runs in the browser and no file leaves your machine.

Built 2026-09-02.

## The new workflow

1. **Make cheats in CE** on a bare table (like `LastBreath.CT` — no template ceremony).
   In the Auto Assemble window use **Template → TCS AOB Injection (hardened)** —
   it generates scripts that are already release-grade: masked big offsets,
   CodeSave/readmem restore, credit header. You only edit the `code:` section.
2. **Write a manifest** (8 lines, see `lastbreath.manifest`) naming the game and
   which features go in [Stats]/[Battle]/[Extra]. Renames: `Src Name -> Release Name`.
   Alternatively prefix entry names in the raw table with `[S] ` / `[B] ` / `[E] `
   and skip the manifest sections.
3. **Build**: `python build_release.py <manifest>` → writes
   `D:\CE tables\<Game> <ver>_Table <tver>_The Cheat Script.ct`
4. **Lint**: `python check_release.py <table.ct>` — flags AOB hygiene issues
   (trailing wildcards, unmasked E8 rel32, big offsets without readmem),
   leftover slots/toolbox/structures, dead symbols, stale supporter month.
5. **Rescan AOBs in-game** to confirm uniqueness (always the human step).

## Files

| file | what |
|---|---|
| `template.ct` | canonical template copy (update here when the template revs) |
| `build_release.py` | manifest → release table generator |
| `check_release.py` | release linter (errors = exit code) |
| `tcs_core.js` | the builder + linter as one JS file, loaded by the web page (kept in lock-step with the Python: see `test_parity.py`) |
| `tcs_template.lua` | CE auto-assembler template **+ "TCS" main-menu** (Build Release / Lint / Open Tools Folder); installed in `C:\Program Files\Cheat Engine\autorun\` — edit here, re-copy there |
| `test_tcs_lua.py` | unit tests for the Lua core (`pip install lupa`; run `python test_tcs_lua.py`) |
| `test_parity.py` | builds a fixture table through `build_release.py` AND `tcs_core.js` (needs `node`) and asserts identical bytes, matching lint reports, deterministic IDs; run `python test_parity.py` after touching either builder |
| `lastbreath.manifest` | working example |

## Symbol-driven sub-entries (2026-09-17)

A feature with no hand-made children gets them **generated from what its
script registers** (builder + web page, byte-identical):

| registered symbol | generated entry |
|---|---|
| `X_Flag` | toggle sub-script (dd 1/dd 0) in a `[Sub Scripts] — Scroll Lock` group |
| `X_Mult` | "X Multiplier" value entry (4 Bytes) |
| `X_Cap` / `X_HP` | "X Cap" / "X HP" value entry (Float) |

Hand-made children always win (no synthesis). Scan symbols and `*_CodeSave`
are ignored. Names are humanized (`GodMode_Flag` → "God Mode").

The release builder also strips the dev-starter scaffolding comment from
`code:` (`// offset-agnostic form (swap in for release):` + its `//  ` byte
lines) so shipped scripts are clean. The ORIGINAL CODE reference block stays.

When someone saves their work table *from* the starter, its `[ TCS Dev Starter ]`
button group rides along. The web page's feature list skips it (detected by
`TCS.createTableScript` / the group name), so a starter-derived work table
builds to a byte-identical release. The linter ERRORs if that group is found in
a table being checked.

The CE AA template now also asks for a **script archetype** (guessed from the
symbol name per colo's convention — `Money_Get_AOB` → base+flag+mult,
`HP_AOB` → God Mode/Instant Kill — confirmed via one selection dialog, per
Yui's objection). The archetype scaffolds register exactly the symbols above,
so template → builder → sub-entries is fully automatic.

The web page (share with the team): https://claude.ai/artifact/HaoexcPG4h6TNJFgs36YDU

**In-table script buttons (Sepp's flow, 2026-09-17):** `() TCS Dev Starter.ct`
(regenerate with `python build_dev_template.py`) is a self-contained work
table — its LuaScript embeds all of tcs_template.lua, so teammates need no
autorun install. Open it, allow the table Lua, select the injection
instruction in the Memory Viewer, tick a `[+ New ... Script]` button: the
archetype script appears as a new table entry and the button unticks itself.
The same actions live under **TCS → New Table Script** for autorun users.
Re-run build_dev_template.py after editing tcs_template.lua to refresh the
starter. Sentinels (`TCS_TEMPLATE_REGISTERED`/`TCS_MENU_ADDED`) prevent
duplicates when both autorun and starter Lua load.

## Update template / supporters (2026-09-17)

`template.ct` is the single source of truth for the SPECIAL THANKS list, so an
updated template keeps the web page and the Python builder in sync with no
second file. In the web page, **Update template...** opens a form for the month,
year, note line and supporter names (each with its tier colour, preserved from
the template). Edits persist in that browser (localStorage) and every build
applies them.

- **Export template.ct** - drop it into `tools/` to update the Python builder.
- **Export both (.zip)** - updated `template.ct` + the current `.manifest`.
- **Save config / Load config** (build section) - the `.manifest` round-trips
  through `build_release.py`, so reloading it next version keeps categories,
  renames and slot order identical (hotkeys stay pinned).

The web page ships a **copy** of `template.ct` bundled at publish time - it
cannot read `tools/` (no filesystem access from a web page). So after exporting
an updated template: drop it in `tools/` for the Python builder, and either send
it to be republished (updates the shared default for everyone) or use
**Use my template.ct** on the page, which loads it for that browser and
remembers it. **Reset to bundled** goes back. The status chip always names which
template is in use, so drift is visible.

Note on a live shared list: the `db` capability would make the artifact
**organization-internal and no longer publicly shareable**, which would lock out
teammates outside the org - so the list rides in `template.ct` instead.

## Rules encoded (keep in sync with memory/aob-pattern-hygiene.md)

- offsets > 0x60: masked in AOB, rebuilt via `readmem(sym+off,4)`, restored via `<sym>_CodeSave`
- `E8`/`E9` rel32 displacements: masked; short jcc rel8: kept
- no trailing wildcards
- releases never carry `<Structures>`, toolbox, niche/misc sections, or unused slots

## Notes / untested edges

- The Lua *core* (masking, script generation) is unit-tested against the real
  Last Breath instruction sequences. The CE-facing wrapper (menu hook, memory
  viewer selection, disasm block) is untested inside CE itself — first use may
  need a tweak; errors appear when invoking the template, not at CE startup.
- `build_release.py` keeps the `[Stats+]`/`[Battle+]` wrapper groups when a
  category overflows its top-level slots (4th+ stats, 5th+ battle) — that is
  template-conventional; hand-flattening like we did for Last Breath is optional.
- Init scripts: `init: auto` keeps the Unity init only if scripts use mono
  symbols (`aobscanregion`/`Class:Method`); plain `aobscanmodule` tables get none.

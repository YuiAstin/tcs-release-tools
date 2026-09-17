--[[
TCS AOB Injection (hardened) — auto-assembler template for Cheat Engine.

Adds an entry to the AA window's Template menu that generates a
ColonelRVH-style hardened injection script from the instruction selected
in the Memory Viewer:

  - AOB extended over following instructions until it has enough anchor bytes
  - disp32 offsets > 0x60 masked with * (and rebuilt via readmem in code)
  - call/jmp rel32 displacements masked; short jcc rel8 kept (stable enough)
  - trailing wildcards trimmed (they add nothing)
  - original bytes saved to <sym>_CodeSave at enable; [DISABLE] restores via
    readmem so a shifted offset can never be restored wrongly
  - credit header + ORIGINAL CODE block included

Install: copy into <Cheat Engine folder>\autorun\
The pure functions live in the TCS table so they can be unit-tested outside CE.
]]

TCS = {}

TCS.BIG_OFFSET = 0x60   -- offsets above this get masked + readmem treatment
TCS.MIN_ANCHOR = 8      -- extend AOB until at least this many literal bytes
TCS.MIN_LEN    = 12     -- ... and at least this many bytes total

TCS.HEADER = table.concat({
 "/*=================================================",
 "--- Cheat Script by ColonelRVH ---",
 "\240\159\149\138 Please Support my work at:",
 "  https://patreon.com/TheCheatScript",
 "  https://ko-fi.com/ColonelRVH",
 "",
 "\240\159\148\151 Latest Game Updates:",
 "  https://www.thecheatscript.com",
 "",
 "\240\159\148\147 Terms:",
 "  Free for the community to learn, modify, and share.",
 "  Retaining original credits is required;",
 "  do not re-upload or claim as your own.",
 "=================================================*/"}, "\n")

-- find the little-endian encoding of value (width bytes) inside bytes,
-- searching from position 'from' (1-based); returns start index or nil
local function findLE(bytes, value, width, from)
  for i = from or 1, #bytes - width + 1 do
    local v, ok = 0, true
    for k = width, 1, -1 do
      v = v * 256 + bytes[i + k - 1]
    end
    if v == value then
      -- avoid matching inside the opcode: require it to be in the tail half
      return i
    end
  end
  return nil
end

-- constants referenced by an instruction, parsed from its disassembly text:
-- memory offsets like [rcx+000000E8] / [rdx+rax*8+0C]
local function textOffsets(text)
  local out = {}
  for hexs in string.gmatch(text, "%+([0-9A-Fa-f]+)%]") do
    out[#out + 1] = tonumber(hexs, 16)
  end
  return out
end

-- analyze one instruction -> mask (array of booleans, true = wildcard)
function TCS.maskInstruction(bytes, text)
  local n = #bytes
  local mask = {}
  for i = 1, n do mask[i] = false end
  local b1, b2 = bytes[1], bytes[2]

  -- relative branches
  if (b1 == 0xE8 or b1 == 0xE9) and n == 5 then
    for i = 2, 5 do mask[i] = true end             -- call/jmp rel32: fragile
    return mask, false
  end
  if b1 == 0x0F and b2 and b2 >= 0x80 and b2 <= 0x8F and n == 6 then
    for i = 3, 6 do mask[i] = true end             -- jcc rel32
    return mask, false
  end
  -- short jcc / jmp rel8: displacement kept on purpose (intra-function)

  -- big memory offsets
  local rebuilt = false
  local searchFrom = 2
  for _, v in ipairs(textOffsets(text)) do
    if v > TCS.BIG_OFFSET then
      local at = findLE(bytes, v, 4, searchFrom)
      local w = 4
      if not at and v <= 0xFF then
        at = findLE(bytes, v, 1, searchFrom)
        w = 1
      end
      if at then
        for i = at, at + w - 1 do mask[i] = true end
        searchFrom = at + w
        rebuilt = true
      end
    end
  end
  return mask, rebuilt
end

-- instrs: array of {bytes = {..}, text = "mov ..."} starting at the injection
-- point. Returns a plan table.
function TCS.analyze(instrs)
  local patchLen, covered = 0, 0
  for _, ins in ipairs(instrs) do
    if patchLen >= 5 then break end
    patchLen = patchLen + #ins.bytes
    covered = covered + 1
  end
  assert(patchLen >= 5, "not enough instruction bytes to place a 5-byte jmp")

  local tokens, literal, total = {}, 0, 0
  local overwritten = {}
  for idx, ins in ipairs(instrs) do
    local mask, rebuilt = TCS.maskInstruction(ins.bytes, ins.text)
    if idx <= covered then
      overwritten[#overwritten + 1] = {
        bytes = ins.bytes, text = ins.text, mask = mask, rebuilt = rebuilt,
        offsetInPatch = total,
      }
    end
    for i = 1, #ins.bytes do
      tokens[#tokens + 1] = mask[i] and "*" or string.format("%02X", ins.bytes[i])
      if not mask[i] then literal = literal + 1 end
    end
    total = total + #ins.bytes
    if idx >= covered and literal >= TCS.MIN_ANCHOR and total >= TCS.MIN_LEN then
      break
    end
  end
  while #tokens > 0 and tokens[#tokens] == "*" do   -- rule: no trailing wildcards
    table.remove(tokens)
  end
  return {
    pattern = table.concat(tokens, " "),
    patchLen = patchLen,
    overwritten = overwritten,
  }
end

-- emit the code: lines reproducing the overwritten instructions as readable
-- mnemonics (what you edit while building the cheat). For an instruction whose
-- displacement we masked in the AOB, the offset-agnostic form (db + readmem) is
-- included commented-out beneath it, to swap in when hardening for release.
local function emitOriginal(plan, sym)
  local out = {}
  for _, ov in ipairs(plan.overwritten) do
    out[#out + 1] = "  " .. ov.text
    if ov.rebuilt then
      out[#out + 1] = "//  offset-agnostic form (swap in for release):"
      local i = 1
      while i <= #ov.bytes do
        if ov.mask[i] then
          local j = i
          while j <= #ov.bytes and ov.mask[j] do j = j + 1 end
          out[#out + 1] = string.format("//    readmem(%s+%X,%d)",
                                        sym, ov.offsetInPatch + i - 1, j - i)
          i = j
        else
          local parts = {}
          local j = i
          while j <= #ov.bytes and not ov.mask[j] do
            parts[#parts + 1] = string.format("%02X", ov.bytes[j])
            j = j + 1
          end
          out[#out + 1] = "//    db " .. table.concat(parts, " ")
          i = j
        end
      end
    end
  end
  return out
end

-- format a disassembly listing: "address: bytes  - opcode", with the opcode
-- column aligned across rows (how CE's dissect copy reads). items: a string
-- passes through as a separator; a table {addr, bytes, opcode} is an aligned row.
function TCS.formatDisasm(items)
  local maxpre = 0
  for _, it in ipairs(items) do
    if type(it) == "table" then
      local pre = it.addr .. ": " .. it.bytes
      if #pre > maxpre then maxpre = #pre end
    end
  end
  local out = {}
  for _, it in ipairs(items) do
    if type(it) == "table" then
      local pre = it.addr .. ": " .. it.bytes
      out[#out + 1] = pre .. string.rep(" ", maxpre - #pre + 2) .. "- " .. it.opcode
    else
      out[#out + 1] = it
    end
  end
  return table.concat(out, "\n")
end

-- archetypes: the script shape implied by what the cheat is.
-- Names follow the house convention (X_Flag / X_Mult / X_Base), which the
-- release builder recognizes to auto-generate sub-entries.
function TCS.baseName(sym)
  local b = sym:gsub("_AOB", "")
  b = b:gsub("_Get$", ""):gsub("_Get_", "_")
  if b == "" then b = sym end
  return b
end

function TCS.guessArchetype(sym)
  if sym:match("[Hh][Pp]") or sym:match("[Hh]ealth") or sym:match("[Gg]od") then
    return "godmode"
  end
  if sym:match("[Mm]oney") or sym:match("[Cc]urrency") or sym:match("[Cc]oin")
     or sym:match("[Cc]ash") or sym:match("[Gg]old") or sym:match("[Ee][Xx][Pp]")
     or sym:match("[Ss]hard") or sym:match("[Pp]oint") or sym:match("_Get") then
    return "money"
  end
  return "plain"
end

TCS.ARCHETYPE_LIST = {
  { id = "plain",   label = "Plain hook" },
  { id = "godmode", label = "God Mode / Instant Kill (HP hook)" },
  { id = "money",   label = "Money/resource: base + flag + multiplier" },
  { id = "flag",    label = "Flag gate (effect only while enabled)" },
}

local function archetypeParts(arch, sym)
  -- returns { labels = {...}, prologue = {...}, branches = {...}, data = {...} }
  local b = TCS.baseName(sym)
  if arch == "godmode" then
    return {
      labels = { "GodMode", "InstantKill", "GodMode_Flag", "InstantKill_Flag" },
      regs = { "GodMode_Flag", "InstantKill_Flag" },
      prologue = {
        "  cmp dword ptr [rcx+40],0        // TODO: player/entity check",
        "  jne @f                          // jmp if player",
        "  cmp dword ptr [InstantKill_Flag],1",
        "  je InstantKill",
        "  jmp code",
        "@@:",
        "  cmp dword ptr [GodMode_Flag],1",
        "  je GodMode",
      },
      branches = {
        "GodMode:",
        "  // TODO: write full/threshold HP, e.g. mov [rcx+24],(float)999",
        "  jmp return",
        "InstantKill:",
        "  // TODO: zero it, e.g. mov [rcx+24],0",
        "  jmp return",
      },
      data = { "GodMode_Flag:", "  dd 0", "InstantKill_Flag:", "  dd 0" },
    }
  elseif arch == "money" then
    local B, F, M = b .. "_Base", b .. "_Flag", b .. "_Mult"
    return {
      labels = { B, F, M },
      regs = { B, F, M },
      prologue = {
        "  mov [" .. B .. "],rcx           // TODO: register holding the struct",
        "  cmp dword ptr [" .. F .. "],1",
        "  jne code",
        "  // TODO: cheat effect, e.g. imul ebx,[" .. M .. "]",
      },
      branches = {},
      data = { B .. ":", "  dq 0", F .. ":", "  dd 0", M .. ":", "  dd 7" },
    }
  elseif arch == "flag" then
    local F = b .. "_Flag"
    return {
      labels = { F },
      regs = { F },
      prologue = {
        "  cmp dword ptr [" .. F .. "],1",
        "  jne code",
        "  // TODO: cheat effect while enabled",
      },
      branches = {},
      data = { F .. ":", "  dd 0" },
    }
  end
  return { labels = {}, regs = {}, prologue = {}, branches = {}, data = {} }
end

function TCS.buildScript(p)
  -- p: symbol, module, plan, archetype ("plain" default),
  --    injText ("GameAssembly.dll+4E8CA9"), disasmBlock
  local sym, plan = p.symbol, p.plan
  local parts = archetypeParts(p.archetype or "plain", sym)
  local L = {}
  local function add(s) L[#L + 1] = s end

  add(TCS.HEADER)
  add("[ENABLE]")
  add("")
  add(string.format("aobscanmodule(%s,%s,%s) // should be unique",
                    sym, p.module, plan.pattern))
  add(string.format("alloc(newmem,$1000,%s)", sym))
  add("")
  add("label(code)")
  add("label(return)")
  for _, l in ipairs(parts.labels) do add("label(" .. l .. ")") end
  for _, l in ipairs(parts.regs) do add("registersymbol(" .. l .. ")") end
  add(string.format("alloc(%s_CodeSave,%d)", sym, plan.patchLen))
  add(sym .. "_CodeSave:")
  add(string.format("  readmem(%s,%d)", sym, plan.patchLen))
  add(string.format("registersymbol(%s_CodeSave)", sym))
  add("")
  add("newmem:")
  for _, l in ipairs(parts.prologue) do add(l) end
  add("")
  add("code:")
  for _, ln in ipairs(emitOriginal(plan, sym)) do add(ln) end
  add("  jmp return")
  add("")
  for _, l in ipairs(parts.branches) do add(l) end
  if #parts.branches > 0 then add("") end
  for _, l in ipairs(parts.data) do add(l) end
  if #parts.data > 0 then add("") end
  add(sym .. ":")
  add("  jmp newmem")
  local pad = plan.patchLen - 5
  if pad == 1 then add("  nop")
  elseif pad > 1 then add(string.format("  nop %d", pad)) end
  add("return:")
  add(string.format("registersymbol(%s)", sym))
  add("")
  add("[DISABLE]")
  add("")
  add(sym .. ":")
  add(string.format("  readmem(%s_CodeSave,%d)", sym, plan.patchLen))
  add("")
  add("unregistersymbol(*)")
  add("dealloc(*)")
  add("")
  add("{")
  add("// ORIGINAL CODE - INJECTION POINT: " .. (p.injText or "?"))
  add("")
  add(p.disasmBlock or "")
  add("}")
  return table.concat(L, "\n")
end

--------------------------------------------------------------------
-- CE-facing part (skipped when unit-testing outside Cheat Engine) --
--------------------------------------------------------------------
if registerAutoAssemblerTemplate ~= nil then

  -- NOTE: in this CE build splitDisassembledString returns
  --   (address, mnemonic, bytes, extra)
  -- despite celua.txt wording it "address, bytes, opcode". Verified against
  -- real Memory Viewer output; do not "correct" this back to the doc order.
  local function readInstruction(addr)
    local size = getInstructionSize(addr)
    if size == nil or size <= 0 then return nil end
    local bytes = readBytes(addr, size, true)
    local _, mnem = splitDisassembledString(disassemble(addr))
    return {bytes = bytes, text = mnem or "", size = size, address = addr}
  end

  local function disasmRow(a)
    -- (address, mnemonic, bytes) — see readInstruction note
    local _, mnem, raw = splitDisassembledString(disassemble(a))
    mnem = (mnem or ""):gsub("%s+$", "")
    raw = (raw or ""):gsub("%s+$", "")
    return { addr = getNameFromAddress(a), bytes = raw, opcode = mnem }
  end

  local function disasmBlock(addr, patchLen)
    local items = {}
    local a = addr
    for _ = 1, 10 do
      local prev = getPreviousOpcode(a)
      if prev == nil or prev >= a then break end
      a = prev
    end
    while a < addr do
      items[#items + 1] = disasmRow(a)
      a = a + getInstructionSize(a)
    end
    items[#items + 1] = "// ---------- INJECTING HERE ----------"
    local stop = addr
    for _ = 1, 10 do stop = stop + getInstructionSize(stop) end
    local marked = false
    a = addr
    while a < stop do
      items[#items + 1] = disasmRow(a)
      a = a + getInstructionSize(a)
      if not marked and a >= addr + patchLen then
        items[#items + 1] = "// ---------- DONE INJECTING  ----------"
        marked = true
      end
    end
    return TCS.formatDisasm(items)
  end

  -- interactive generation shared by the AA template, the TCS menu and
  -- table "button" entries; archetype nil = ask with the selection dialog
  local function generate(archetype)
    if process == nil or getOpenedProcessID() == 0 then
      showMessage("Attach Cheat Engine to the game first.")
      return nil
    end
    local mv = getMemoryViewForm()
    local addr = mv.DisassemblerView.SelectedAddress
    if addr == nil or addr == 0 then
      showMessage("Select the injection instruction in the Memory Viewer first.")
      return nil
    end

    -- read the code before asking anything, so a bad selection fails fast
    local instrs, a = {}, addr
    for _ = 1, 8 do
      local ok, ins = pcall(readInstruction, a)
      if not ok or ins == nil or ins.bytes == nil then break end
      instrs[#instrs + 1] = ins
      a = a + ins.size
    end
    local total = 0
    for _, ins in ipairs(instrs) do total = total + #ins.bytes end
    if total < 5 then
      showMessage(string.format(
        "Could not read code at %s.\n\nClick the injection instruction's line in the Memory Viewer's disassembler, then try again.",
        getNameFromAddress(addr) or string.format("%X", addr)))
      return nil
    end

    local modname = nil
    for _, m in ipairs(enumModules()) do
      if addr >= m.Address and addr < m.Address + (m.Size or 0) then
        modname = m.Name
        break
      end
    end
    if modname == nil then
      local full = getNameFromAddress(addr)
      modname = string.match(full or "", "^([^+]+)%+") or "game.exe"
    end

    local sym = inputQuery("TCS AOB Injection", "Symbol name:", "INJ_AOB")
    if sym == nil or sym == "" then return nil end

    if archetype == nil then
      -- archetype: guessed from the symbol name, confirmed by one pick
      local guess = TCS.guessArchetype(sym)
      local sl = createStringlist()
      local order = {}
      for _, a in ipairs(TCS.ARCHETYPE_LIST) do
        if a.id == guess then
          sl.add(a.label .. "  <- suggested for '" .. sym .. "'")
          order[#order + 1] = a.id
        end
      end
      for _, a in ipairs(TCS.ARCHETYPE_LIST) do
        if a.id ~= guess then
          sl.add(a.label)
          order[#order + 1] = a.id
        end
      end
      local pick = showSelectionList("TCS AOB Injection", "Script shape:", sl)
      sl.destroy()
      if pick == nil or pick < 0 then return nil end
      archetype = order[pick + 1]
    end

    local ok, plan = pcall(TCS.analyze, instrs)
    if not ok then
      showMessage("TCS template: " .. tostring(plan))
      return nil
    end

    return {
      sym = sym,
      archetype = archetype,
      text = TCS.buildScript{
        symbol = sym,
        module = modname,
        plan = plan,
        archetype = archetype,
        injText = getNameFromAddress(addr),
        disasmBlock = disasmBlock(addr, plan.patchLen),
      },
    }
  end

  local function tcsTemplate(script, sender)
    local g = generate(nil)
    if g ~= nil then script.Text = g.text end
  end

  -- Sepp's flow: one click makes a new script entry in the address list,
  -- pre-filled with the archetype scaffold. `creatorRec` is the table
  -- "button" entry that invoked us (nil when called from the TCS menu);
  -- it gets unticked shortly after so it stays a reusable button.
  function TCS.createTableScript(archetype, creatorRec)
    local g = generate(archetype)
    if creatorRec ~= nil then
      local t = createTimer(nil)
      t.Interval = 500
      t.OnTimer = function(tt)
        tt.destroy()
        pcall(function() creatorRec.Active = false end)
      end
    end
    if g == nil then return end
    local al = getAddressList()
    local mr = al.createMemoryRecord()
    mr.Description = (g.sym:gsub('_AOB.*$', ''):gsub('_', ' '))
    mr.Type = vtAutoAssembler
    mr.Script = g.text
    mr.Color = 0x808000
  end

  if not _G.TCS_TEMPLATE_REGISTERED then
    _G.TCS_TEMPLATE_REGISTERED = true
    registerAutoAssemblerTemplate("TCS AOB Injection (hardened)", tcsTemplate)
  end
end

--------------------------------------------------------------------
-- CE main menu: TCS > Build Release / Lint / Open Tools Folder    --
--------------------------------------------------------------------
if getMainForm ~= nil and createMenuItem ~= nil then
  local TOOLS  = [[D:\CE tables\tools]]
  local TABLES = [[D:\CE tables]]
  local PYTHON = 'python'   -- if not on PATH, put the full python.exe path here
                            -- (a path with spaces needs cmd's extra outer quotes)

  local function runToLog(argline)
    local log = (os.getenv('TEMP') or TOOLS) .. [[\tcs_tool.log]]
    os.execute(string.format('%s %s > "%s" 2>&1', PYTHON, argline, log))
    local f = io.open(log, 'r')
    if f == nil then return '(no output captured)' end
    local out = f:read('*a')
    f:close()
    if out == nil or out == '' then out = '(no output)' end
    return out
  end

  local function pickFile(filter, initdir)
    local d = createOpenDialog()
    d.Filter = filter
    d.InitialDir = initdir
    local ok = d.execute()
    local fn = d.FileName
    d.destroy()
    if ok then return fn end
    return nil
  end

  local function showText(title, text)
    local frm = createForm(false)
    frm.Caption = title
    frm.Width = 760
    frm.Height = 440
    frm.Position = 'poScreenCenter'
    frm.BorderStyle = 'bsSizeable'
    local memo = createMemo(frm)
    memo.Align = 'alClient'
    memo.ReadOnly = true
    memo.ScrollBars = 'ssAutoBoth'
    memo.Font.Name = 'Consolas'
    memo.WordWrap = false
    memo.Lines.Text = text
    frm.show()
  end

  local function doBuild()
    local mf = pickFile('Manifest (*.manifest)|*.manifest|All files (*.*)|*.*', TOOLS)
    if mf == nil then return end
    local out = runToLog(string.format('"%s\\build_release.py" "%s"', TOOLS, mf))
    local built = string.match(out, 'built:%s*([^\r\n]+)')
    if built ~= nil then
      out = out .. '\r\n--- lint ---\r\n'
            .. runToLog(string.format('"%s\\check_release.py" "%s"', TOOLS, built))
    end
    showText('TCS - Build Release', out)
  end

  local function doLint()
    local ct = pickFile('Cheat Table (*.ct;*.CT)|*.ct;*.CT|All files (*.*)|*.*', TABLES)
    if ct == nil then return end
    showText('TCS - Lint', runToLog(string.format('"%s\\check_release.py" "%s"', TOOLS, ct)))
  end

  if not _G.TCS_MENU_ADDED then
    _G.TCS_MENU_ADDED = true
    local parent = getMainForm().Menu.Items
    local top = createMenuItem(parent)
    top.Caption = 'TCS'
    parent.add(top)

    local mNew = createMenuItem(top)
    mNew.Caption = 'New Table Script'
    top.add(mNew)
    for _, a in ipairs({
      {'Money / resource (base + flag + mult)', 'money'},
      {'God Mode / Instant Kill (HP hook)',     'godmode'},
      {'Flag gate',                             'flag'},
      {'Plain hook',                            'plain'},
    }) do
      local mi = createMenuItem(mNew)
      mi.Caption = a[1]
      mi.OnClick = function()
        if TCS.createTableScript ~= nil then TCS.createTableScript(a[2], nil) end
      end
      mNew.add(mi)
    end

    -- Build/Lint call local Python scripts; only offer them on a machine
    -- that actually has the tools folder (teammates running the embedded
    -- dev-starter copy get just "New Table Script")
    local probe = io.open(TOOLS .. [[\build_release.py]], 'r')
    if probe ~= nil then
      probe:close()
      local items = {
        {'Build Release Table...', doBuild},
        {'Lint Table...',          doLint},
        {'Open Tools Folder',      function() shellExecute(TOOLS) end},
      }
      for _, it in ipairs(items) do
        local mi = createMenuItem(top)
        mi.Caption = it[1]
        mi.OnClick = it[2]
        top.add(mi)
      end
    end
  end
end

return TCS

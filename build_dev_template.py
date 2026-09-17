# -*- coding: utf-8 -*-
"""Generate "() TCS Dev Starter.ct" — a self-contained work table.

Open it in CE (allow the table Lua), select the injection instruction in the
Memory Viewer, tick one of the [+ New ... Script] buttons: a hardened
archetype script appears as a new entry in the table. No autorun install
needed — the whole tcs_template.lua rides inside the table's LuaScript.

Usage: python build_dev_template.py [output.ct]
"""
import io
import sys
import xml.sax.saxutils as sx
from pathlib import Path

NL = '\r\n'
HERE = Path(__file__).parent

BUTTONS = [
    ('+ New Money / Resource Script  (base + flag + mult)', 'money'),
    ('+ New God Mode Script  (HP hook, GodMode/InstantKill flags)', 'godmode'),
    ('+ New Flag Gate Script', 'flag'),
    ('+ New Plain Hook Script', 'plain'),
]


def button_entry(eid, caption, archetype):
    # The {$lua} block lives INSIDE [ENABLE] so CE runs it only when the button
    # is ticked. A block before [ENABLE] is assembled on both enable and disable,
    # so the auto-untick would fire it a second time and create a duplicate entry.
    script = (
        '[ENABLE]' + NL +
        '{$lua}' + NL +
        'if syntaxcheck then return end' + NL +
        'if TCS == nil or TCS.createTableScript == nil then' + NL +
        "  ShowMessage('TCS tools are not loaded.\\nRe-open this table and allow its Lua script.')" + NL +
        'else' + NL +
        "  TCS.createTableScript('" + archetype + "', memrec)" + NL +
        'end' + NL +
        '{$asm}' + NL +
        '[DISABLE]' + NL)
    return NL.join([
        '      <CheatEntry>',
        '        <ID>%d</ID>' % eid,
        '        <Description>"%s"</Description>' % caption,
        '        <Color>808000</Color>',
        '        <VariableType>Auto Assembler Script</VariableType>',
        '        <AssemblerScript>' + sx.escape(script) + '</AssemblerScript>',
        '      </CheatEntry>']) + NL


def build(out_path):
    lua = io.open(HERE / 'tcs_template.lua', encoding='utf-8', newline='').read()
    # the starter is standalone: file may carry LF depending on git; normalize
    lua = lua.replace('\r\n', '\n').replace('\n', NL)

    entries = ''.join(button_entry(9901 + i, cap, arch)
                      for i, (cap, arch) in enumerate(BUTTONS))
    ct = NL.join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<CheatTable CheatEngineTableVersion="45">',
        '  <CheatEntries>',
        '    <CheatEntry>',
        '      <ID>9900</ID>',
        '      <Description>"[ TCS Dev Starter — select the injection instruction in the Memory Viewer, then tick a button below ]"</Description>',
        '      <Options moAllowManualCollapseAndExpand="1"/>',
        '      <Color>FF8000</Color>',
        '      <GroupHeader>1</GroupHeader>',
        '      <CheatEntries>',
        '']) + entries + NL.join([
        '      </CheatEntries>',
        '    </CheatEntry>',
        '  </CheatEntries>',
        '  <UserdefinedSymbols/>',
        '  <LuaScript>' + sx.escape(lua),
        '</LuaScript>',
        '</CheatTable>']) + NL
    io.open(out_path, 'w', encoding='utf-8', newline='').write(ct)

    import xml.etree.ElementTree as ET
    ET.parse(out_path)
    data = open(out_path, 'rb').read()
    assert data.count(b'\n') == data.count(b'\r\n'), 'mixed line endings'
    print('built:', out_path)
    return str(out_path)


if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else str(HERE / '() TCS Dev Starter.ct'))

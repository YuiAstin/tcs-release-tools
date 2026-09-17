# -*- coding: utf-8 -*-
"""Unit tests for tcs_template.lua's pure core, run via lupa (no CE needed).

Fixtures are the real instruction sequences from the Last Breath table
(2026-09-02 session) whose hand-hardened versions we know are correct.
"""
import os
from lupa import LuaRuntime

lua = LuaRuntime(unpack_returned_tuples=True)
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, 'tcs_template.lua'), encoding='utf-8').read()
TCS = lua.execute(src)

T = lua.table_from
failures = []


def check(name, cond, detail=''):
    if cond:
        print('PASS', name)
    else:
        failures.append(name)
        print('FAIL', name, detail)


def instr(byte_list, text):
    return T({'bytes': T({i + 1: b for i, b in enumerate(byte_list)}), 'text': text})


# --- fixture 1: Unlimited Ammo injection site (GameAssembly.dll+4E8CA9)
ammo = T({1: instr([0xFF, 0x89, 0xE8, 0x00, 0x00, 0x00], 'dec [rcx+000000E8]'),
          2: instr([0x48, 0x8B, 0x81, 0x00, 0x02, 0x00, 0x00], 'mov rax,[rcx+00000200]'),
          3: instr([0x48, 0x85, 0xC0], 'test rax,rax'),
          4: instr([0x74, 0x0E], 'je GameAssembly.dll+4E8CC9')})
plan = TCS.analyze(ammo)
check('ammo: big offsets masked, extended to enough anchors',
      plan.pattern == 'FF 89 * * * * 48 8B 81 * * * * 48 85 C0', repr(plan.pattern))
check('ammo: patch length is the 6-byte dec', plan.patchLen == 6)

script = TCS.buildScript(T({'symbol': 'Ammo_AOB', 'module': 'GameAssembly.dll',
                            'plan': plan, 'injText': 'GameAssembly.dll+4E8CA9',
                            'disasmBlock': '(disasm)'}))
for name, needle in [
    ('ammo: CodeSave alloc',        'alloc(Ammo_AOB_CodeSave,6)'),
    ('ammo: CodeSave snapshot',     'readmem(Ammo_AOB,6)'),
    ('ammo: mnemonic is the active code line', '\n  dec [rcx+000000E8]\n'),
    ('ammo: hardened form offered as comment', '//  offset-agnostic form (swap in for release):'),
    ('ammo: hardened readmem in comment', '//    readmem(Ammo_AOB+2,4)'),
    ('ammo: hardened db in comment', '//    db FF 89'),
    ('ammo: nop pad for 6-byte patch', '  jmp newmem\n  nop\nreturn:'),
    ('ammo: disable restores from CodeSave', 'readmem(Ammo_AOB_CodeSave,6)'),
    ('ammo: wildcard cleanup',      'unregistersymbol(*)'),
    ('ammo: credit header present', 'Cheat Script by ColonelRVH'),
]:
    check(name, needle in script, 'missing: %r' % needle)

# --- fixture 2: Unlimited Stamina site — small offsets, short jcc kept
sta = T({1: instr([0xF3, 0x0F, 0x11, 0x49, 0x2C], 'movss [rcx+2C],xmm1'),
         2: instr([0x48, 0x85, 0xC0], 'test rax,rax'),
         3: instr([0x74, 0x10], 'je GameAssembly.dll+5F4E99'),
         4: instr([0xF3, 0x0F, 0x10, 0x51, 0x28], 'movss xmm2,[rcx+28]')})
plan2 = TCS.analyze(sta)
check('stamina: nothing masked, jcc rel8 kept',
      plan2.pattern == 'F3 0F 11 49 2C 48 85 C0 74 10 F3 0F 10 51 28', repr(plan2.pattern))
check('stamina: 5-byte patch', plan2.patchLen == 5)
s2 = TCS.buildScript(T({'symbol': 'Sta_AOB', 'module': 'GameAssembly.dll', 'plan': plan2}))
check('stamina: plain instruction reproduced', '  movss [rcx+2C],xmm1\n  jmp return' in s2)
check('stamina: no nop pad', 'nop' not in s2.split('[DISABLE]')[0].split('jmp newmem')[1])
check('stamina: no readmem rebuild in code',
      'readmem(Sta_AOB+' not in s2)

# --- fixture 3: call rel32 gets its displacement masked entirely
call = T({1: instr([0x8B, 0x44, 0xC1, 0x2C], 'mov eax,[rcx+rax*8+2C]'),
          2: instr([0x48, 0x83, 0xC4, 0x20], 'add rsp,20'),
          3: instr([0x5F], 'pop rdi'),
          4: instr([0xC3], 'ret'),
          5: instr([0xE8, 0xA9, 0x12, 0x00, 0x00], 'call GameAssembly.dll+3DEEF0')})
plan3 = TCS.analyze(call)
check('call: rel32 disp masked, trailing wildcards trimmed',
      plan3.pattern == '8B 44 C1 2C 48 83 C4 20 5F C3 E8', repr(plan3.pattern))

# --- fixture 4: masked byte inside pattern that equals a small legit disp8
mid = T({1: instr([0x89, 0x48, 0x3C, 0x48, 0x8B, 0x47, 0x30], 'mov [rax+3C],ecx'),
         2: instr([0x48, 0x8B, 0x47, 0x30], 'mov rax,[rdi+30]')})
plan4 = TCS.analyze(mid)
check('small offsets: nothing masked',
      '*' not in plan4.pattern, repr(plan4.pattern))

# --- formatDisasm: address, bytes, opcode order with aligned opcode column
di = TCS.formatDisasm(T({
    1: T({'addr': 'GameAssembly.dll+4E8CA0', 'bytes': '83 B9 E8 00 00 00 00',
          'opcode': 'cmp dword ptr [rcx+000000E8],00'}),
    2: '// ---------- INJECTING HERE ----------',
    3: T({'addr': 'GameAssembly.dll+4E8CA7', 'bytes': '7E 27',
          'opcode': 'jle GameAssembly.dll+4E8CD0'}),
}))
dl = di.split('\n')
check('formatDisasm: order is address, bytes, opcode',
      dl[0].startswith('GameAssembly.dll+4E8CA0: 83 B9 E8 00 00 00 00') and
      dl[0].rstrip().endswith('- cmp dword ptr [rcx+000000E8],00'), dl[0])
check('formatDisasm: separator passes through', dl[1] == '// ---------- INJECTING HERE ----------')
check('formatDisasm: opcode columns aligned',
      dl[0].index('- ') == dl[2].index('- '),
      'row0 dash@%d row2 dash@%d' % (dl[0].index('- '), dl[2].index('- ')))

# --- archetype guessing (colo's naming convention as default)
for sym, want in [('Money_Get_AOB', 'money'), ('HP_AOB', 'godmode'),
                  ('GodMode_AOB', 'godmode'), ('Gold_AOB', 'money'),
                  ('EXP_Get_AOB', 'money'), ('Stamina_AOB', 'plain'),
                  ('Item_AOB', 'plain')]:
    check('guess %s -> %s' % (sym, want), TCS.guessArchetype(sym) == want,
          TCS.guessArchetype(sym))
check('baseName strips _AOB/_Get', TCS.baseName('Money_Get_AOB') == 'Money'
      and TCS.baseName('Money_Get_AOB_V2') == 'Money_V2', TCS.baseName('Money_Get_AOB_V2'))

# --- godmode archetype scaffold (on the stamina fixture bytes)
sg = TCS.buildScript(T({'symbol': 'HP_AOB', 'module': 'GameAssembly.dll',
                        'plan': plan2, 'archetype': 'godmode'}))
for name, needle in [
    ('godmode: flags registered', 'registersymbol(GodMode_Flag)'),
    ('godmode: instant kill branch', 'InstantKill:'),
    ('godmode: player check TODO', 'player/entity check'),
    ('godmode: flags init dd 0', 'GodMode_Flag:\n  dd 0'),
]:
    check(name, needle in sg, 'missing: %r' % needle)

# --- money archetype scaffold: base + flag + mult per colo's convention
sm2 = TCS.buildScript(T({'symbol': 'Money_Get_AOB', 'module': 'GameAssembly.dll',
                         'plan': plan2, 'archetype': 'money'}))
for name, needle in [
    ('money: base capture', 'mov [Money_Base],rcx'),
    ('money: flag gate', 'cmp dword ptr [Money_Flag],1'),
    ('money: mult registered', 'registersymbol(Money_Mult)'),
    ('money: mult default dd 7', 'Money_Mult:\n  dd 7'),
    ('money: base is dq', 'Money_Base:\n  dq 0'),
]:
    check(name, needle in sm2, 'missing: %r' % needle)

# --- flag archetype + plain stays plain
sf = TCS.buildScript(T({'symbol': 'Fly_AOB', 'module': 'g.exe',
                        'plan': plan2, 'archetype': 'flag'}))
check('flag: gate present', 'cmp dword ptr [Fly_Flag],1' in sf)
check('plain unchanged by archetype plumbing',
      'Flag' not in TCS.buildScript(T({'symbol': 'Sta_AOB', 'module': 'g.exe', 'plan': plan2})))

print()
if failures:
    print('FAILURES:', failures)
    raise SystemExit(1)
print('all tests passed')

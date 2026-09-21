# -*- coding: utf-8 -*-
"""Parity test: build_release.py and tcs_core.js must produce identical bytes.

The web page runs tcs_core.js; the CE menu runs build_release.py. A raw table
is built through both (same template, same date) and the outputs compared,
along with each side's lint report. Also pins the regressions that the port
once disagreed on: deterministic child-ID remapping, hotkey <ID> tags left
alone, and sub-entries landing under the right slot when two features share
a release name.

Requires node on PATH (the JS side runs under node).  Run:
    python test_parity.py
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import contextlib
import build_release
import check_release

HERE = os.path.dirname(os.path.abspath(__file__))
NL = '\r\n'
DATE = '2026-01-15'
failures = []


def check(name, cond, detail=''):
    if cond:
        print('PASS', name)
    else:
        failures.append(name)
        print('FAIL', name, detail)


# ---------------- fixture raw table ----------------

def _entry(eid, desc, body=None, children=None, indent=4, hotkey_id=None):
    p = ' ' * indent
    L = [p + '<CheatEntry>', p + '  <ID>%d</ID>' % eid,
         p + '  <Description>"%s"</Description>' % desc]
    if body is not None:
        L += [p + '  <Options moHideChildren="1"/>', p + '  <Color>808000</Color>',
              p + '  <VariableType>Auto Assembler Script</VariableType>',
              p + '  <AssemblerScript>' + body + '</AssemblerScript>']
    else:
        L += [p + '  <GroupHeader>1</GroupHeader>']
    if hotkey_id is not None:
        L += [p + '  <Hotkeys>', p + '    <Hotkey>',
              p + '      <Action>Toggle Activation</Action>',
              p + '      <Keys>', p + '        <Key>145</Key>', p + '      </Keys>',
              p + '      <ID>%d</ID>' % hotkey_id,
              p + '    </Hotkey>', p + '  </Hotkeys>']
    if children:
        L += [p + '  <CheatEntries>'] + children + [p + '  </CheatEntries>']
    L.append(p + '</CheatEntry>')
    return L


def fixture_table():
    # A: hand-made children; child entry ID 9200 collides with the template's
    #    first slot ID, and the child's hotkey carries <ID>0</ID> (which the
    #    template also uses for hotkeys - a hotkey ID is not an entry ID).
    #    Two colliding children so remap ORDER matters.
    child_a = (_entry(9200, 'Ammo Flag',
                      '[ENABLE]' + NL + 'Ammo_Flag:' + NL + 'dd 1' + NL +
                      '[DISABLE]' + NL + 'Ammo_Flag:' + NL + 'dd 0' + NL,
                      indent=8, hotkey_id=0) +
               _entry(9211, 'Ammo Note', indent=8))
    body_a = NL.join([
        '[ENABLE]',
        'aobscanmodule(Ammo_AOB,GameAssembly.dll,FF 89 * * * * 48 8B 81 * * * * 48 85 C0)',
        'alloc(newmem,$1000,Ammo_AOB)', 'label(code)', 'label(return)',
        'registersymbol(Ammo_Flag)',
        'alloc(Ammo_AOB_CodeSave,6)', 'Ammo_AOB_CodeSave:', '  readmem(Ammo_AOB,6)',
        'registersymbol(Ammo_AOB_CodeSave)', '',
        'newmem:', '  cmp dword ptr [Ammo_Flag],1', '  jne code', '  jmp return',
        'code:', '  dec [rcx+000000E8]',
        '//  offset-agnostic form (swap in for release):',
        '//    db FF 89', '//    readmem(Ammo_AOB+2,4)',
        '  jmp return', 'Ammo_Flag:', '  dd 0',
        'Ammo_AOB:', '  jmp newmem', '  nop', 'return:', 'registersymbol(Ammo_AOB)',
        '[DISABLE]', 'Ammo_AOB:', '  readmem(Ammo_AOB_CodeSave,6)',
        'unregistersymbol(*)', 'dealloc(*)', ''])
    A = _entry(1, 'Unlimited Ammo', body_a, children=child_a)

    # B: no children, no credit header; registers Money_Flag/Mult/Cap so the
    #    builder synthesizes the sub-entries
    body_b = NL.join([
        '[ENABLE]',
        'aobscanmodule(Money_Get_AOB,GameAssembly.dll,48 8B 81 * * * * 48 85 C0 74 10)',
        'alloc(newmem,$1000,Money_Get_AOB)', 'label(code)', 'label(return)',
        'registersymbol(Money_Base)', 'registersymbol(Money_Flag)',
        'registersymbol(Money_Mult)', 'registersymbol(Money_Cap)', '',
        'newmem:', '  mov [Money_Base],rcx', '  cmp dword ptr [Money_Flag],1',
        '  jne code', '  imul ebx,[Money_Mult]',
        'code:', '  mov rax,[rcx+00000200]', '  jmp return',
        'Money_Base:', '  dq 0', 'Money_Flag:', '  dd 0', 'Money_Mult:', '  dd 7',
        'Money_Cap:', '  dd (float)90',
        'Money_Get_AOB:', '  jmp newmem', '  nop 2', 'return:',
        'registersymbol(Money_Get_AOB)',
        '[DISABLE]', 'Money_Get_AOB:', '  db 48 8B 81 00 02 00 00',
        'unregistersymbol(*)', 'dealloc(*)', ''])
    B = _entry(2, 'Unlimited Currency', body_b)

    # C: plain; mono use makes init:auto pick the Unity init script
    body_c = NL.join([
        '{ Game: Test.exe', '  Author : dev', '}', '',
        '{$lua}', 'if syntaxcheck then return end', 'print("pre-enable block")', '{$asm}',
        '[ENABLE]', 'LaunchMonoDataCollector()',
        'aobscanregion(Sta_AOB,Player:Update,Player:Update+200,F3 0F 11 49 2C)',
        'registersymbol(Sta_AOB)', '[DISABLE]', 'unregistersymbol(Sta_AOB)', ''])
    C = _entry(3, 'Unlimited Stamina', body_c)

    # D: 32-bit game code, no readmem: the linter must still see the big offset
    body_d = NL.join([
        '[ENABLE]', 'aobscanmodule(Item_AOB,game.exe,89 88 E8 00 00 00 5E)',
        'alloc(newmem,$1000)', 'label(code)', 'label(return)', 'registersymbol(Item_AOB)',
        'newmem:', 'code:', '  mov [eax+000000E8],ecx', '  jmp return',
        'Item_AOB:', '  jmp newmem', '  nop', 'return:',
        '[DISABLE]', 'Item_AOB:', '  db 89 88 E8 00 00 00', 'unregistersymbol(*)', 'dealloc(*)', ''])
    D = _entry(7, 'Item #2 Stock', body_d, indent=8)
    # folder with the nested feature, a second "Unlimited Stamina" (different
    # code) and a copy of C's script under another name
    OLD = _entry(8, 'Misc', children=(
        D +
        _entry(9, 'Unlimited Stamina', body_d.replace('Item_AOB', 'Old_AOB'), indent=8) +
        _entry(10, 'Stamina Copy', body_c, indent=8)))

    # a group header with a script child, and a value entry: never features
    G = _entry(4, 'Helpers',
               children=_entry(5, 'Helper script', '[ENABLE]' + NL + '[DISABLE]' + NL, indent=8))
    V = ['    <CheatEntry>', '      <ID>6</ID>', '      <Description>"HP value"</Description>',
         '      <VariableType>Float</VariableType>', '      <Address>12345678</Address>',
         '    </CheatEntry>']

    return NL.join(['<?xml version="1.0" encoding="utf-8"?>',
                    '<CheatTable CheatEngineTableVersion="45">', '  <CheatEntries>']
                   + A + B + C + OLD + G + V +
                   ['  </CheatEntries>', '  <UserdefinedSymbols/>',
                    '  <Structures>', '  </Structures>', '</CheatTable>']) + NL


MANIFESTS = {
    'basic': NL.join([
        'game: Test Game', 'version: v1.2', 'table: v1.0', 'exe: TestGame.exe',
        'source: Raw.CT', 'init: auto', '',
        '[stats]', 'Unlimited Currency', '',
        '[battle]', 'Unlimited Ammo -> Unlimited Ammo (Scroll Lock)', 'Unlimited Stamina', '',
        '[extra]', 'Item #2 Stock -> Item #2 & Stock  # the name keeps its #', '']),
    # no mono symbols anywhere selected -> no init script at all
    'nomono': NL.join([
        'game: Test Game', 'version: v1.2', 'exe: TestGame.exe', 'source: Raw.CT', '',
        '[stats]', 'Item #2 Stock', '']),
    # two features renamed to the same thing, and one renamed to a name the
    # template already uses: sub-entries must still land under their own slot
    'dup-names': NL.join([
        'game: Test Game', 'version: v1.2', 'exe: TestGame.exe', 'source: Raw.CT', '',
        '[stats]', 'Unlimited Currency -> Dup', '',
        '[battle]', 'Unlimited Ammo -> Dup', 'Unlimited Stamina -> [Game Speed]', '']),
}

JS_RUNNER = r'''
const fs = require('fs');
const [,, core, tplPath, srcPath, manPath, date, outPath] = process.argv;
const T = require(core);
const tpl = fs.readFileSync(tplPath, 'utf8'), src = fs.readFileSync(srcPath, 'utf8');
const cfg = T.parseManifest(fs.readFileSync(manPath, 'utf8'));
cfg.date = date;
const plain = T.buildRelease(tpl, src, Object.assign({}, cfg));
// the page always re-applies the template's own supporter list
cfg.supporters = T.parseSupporters(tpl);
const page = T.buildRelease(tpl, src, cfg);
fs.writeFileSync(outPath, page.output);
process.stdout.write(JSON.stringify({
  samePlain: plain.output === page.output,
  filename: page.filename,
  warnings: page.warnings,
  lint: T.lintTable(page.output),
}));
'''


def run_js(node, runner, core, tpl, src, manifest, out):
    r = subprocess.run([node, runner, core, tpl, src, manifest, DATE, out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError('node failed:\n' + r.stderr)
    return json.loads(r.stdout)


def py_lint(path):
    check_release.issues[:] = []
    check_release.check(path)
    return list(check_release.issues)


def main():
    node = shutil.which('node')
    if not node:
        sys.exit('node is required for the parity test (the JS side runs under node)')

    tmp = tempfile.mkdtemp(prefix='tcs-parity-')
    try:
        src = os.path.join(tmp, 'Raw.CT')
        io.open(src, 'w', encoding='utf-8', newline='').write(fixture_table())
        core = os.path.join(HERE, 'tcs_core.js')
        tpl = os.path.join(HERE, 'template.ct')
        runner = os.path.join(tmp, 'run.js')
        io.open(runner, 'w', encoding='utf-8').write(JS_RUNNER)
        outputs, warnings_out = {}, {}

        for name, text in MANIFESTS.items():
            man = os.path.join(tmp, name + '.manifest')
            io.open(man, 'w', encoding='utf-8', newline='').write(text)
            py_out = os.path.join(tmp, name + '.py.ct')
            js_out = os.path.join(tmp, name + '.js.ct')

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                build_release.build(man, py_out, date=DATE)
            py_warn = [l[5:] for l in buf.getvalue().splitlines() if l.startswith('WARN ')]
            js = run_js(node, runner, core, tpl, src, man, js_out)
            check('%s: build warnings agree' % name, py_warn == js['warnings'],
                  '\n py: %r\n js: %r' % (py_warn, js['warnings']))
            warnings_out[name] = py_warn
            py = open(py_out, 'rb').read()
            jsb = open(js_out, 'rb').read()
            outputs[name] = py.decode('utf-8')

            check('%s: python and js output identical' % name, py == jsb,
                  '%d vs %d bytes' % (len(py), len(jsb)))
            check('%s: supporters re-apply is a no-op' % name, js['samePlain'])
            check('%s: filename matches' % name,
                  js['filename'] == 'Test Game v1.2_Table v1.0_The Cheat Script.ct', js['filename'])
            # lint parity (both linters date the supporter list from today)
            pl = [[lvl, msg] for lvl, msg in py_lint(py_out)]
            check('%s: lint reports agree' % name, pl == js['lint'],
                  '\n py: %r\n js: %r' % (pl, js['lint']))
            check('%s: no lint errors' % name, not any(l == 'ERROR' for l, _ in pl), repr(pl))

        # --- regressions -------------------------------------------------
        basic = outputs['basic']
        hk = re.search(r'"Ammo Flag"[\s\S]*?</Hotkeys>', basic).group(0)
        check('hotkey <ID>0</ID> of an imported child is left alone',
              '<ID>0</ID>' in hk, hk)
        check('colliding child entry IDs were remapped',
              re.search(r'<ID>9200</ID>\s*<Description>"Ammo Flag"', basic) is None)
        check('dev-starter scaffolding comment stripped', 'offset-agnostic' not in basic)
        check('sub-entries synthesized from Money_* symbols',
              '"Money Multiplier"' in basic and '"Money Cap"' in basic
              and '[Sub Scripts]' in basic)
        check('unity init kept, .NET init dropped',
              'Initialize Unity' in basic and '.NET Engine' not in basic)
        check('"#" inside a feature name survives the manifest; "&" is escaped once',
              '"Item #2 &amp; Stock"' in basic, repr(re.findall(r'"Item[^"]*"', basic)))
        check('feature nested in a folder is found', 'Item_AOB' in basic)
        pl = py_lint(os.path.join(tmp, 'basic.py.ct'))
        check('linter sees a big offset on a 32-bit register',
              any('Item #2' in m and '0xE8' in m for _, m in pl), repr(pl))
        check('{$lua} block before [ENABLE] survives header insertion',
              'print("pre-enable block")' in basic and 'Author : dev' not in basic)
        stam = re.search(r'"Unlimited Stamina"</Description>[\s\S]*?</AssemblerScript>', basic).group(0)
        check('duplicate source name: first occurrence used', 'Sta_AOB' in stam and 'Old_AOB' not in stam)
        check('duplicate name and same-code warnings raised',
              any('appears 2 times' in w for w in warnings_out['basic']) and
              any('same script as Misc / Stamina Copy' in w for w in warnings_out['basic']),
              repr(warnings_out['basic']))
        nomono = outputs['nomono']
        check('no mono symbols -> no init script', 'Init Script' not in nomono and '.NET Engine' not in nomono)

        # --- init typo is an error on both sides ---------------------------
        bad = os.path.join(tmp, 'bad.manifest')
        io.open(bad, 'w', encoding='utf-8', newline='').write(
            MANIFESTS['basic'].replace('init: auto', 'init: unty'))
        try:
            build_release.build(bad, os.path.join(tmp, 'bad.ct'), date=DATE)
            check('python rejects init: unty', False)
        except SystemExit as e:
            check('python rejects init: unty', 'init' in str(e), str(e))
        try:
            run_js(node, runner, core, tpl, src, bad, os.path.join(tmp, 'bad.js.ct'))
            check('js rejects init: unty', False)
        except RuntimeError as e:
            check('js rejects init: unty', 'init must be' in str(e), str(e)[:200])

        dup = outputs['dup-names']
        # Ammo's children must sit inside the entry whose script is Ammo_AOB
        m = re.search(r'<Description>"Dup"</Description>[\s\S]*?Ammo_AOB[\s\S]*?"Ammo Flag"', dup)
        wrong = re.search(r'<Description>"Dup"</Description>[\s\S]*?Money_Get_AOB[\s\S]*?"Ammo Flag"'
                          r'[\s\S]*?Ammo_AOB', dup)
        check('duplicate release names: children under their own slot',
              m is not None and wrong is None)
        check('release name equal to a template description does not mislead',
              dup.count('"[Game Speed]"') == 2 and 'Sta_AOB' in dup)

        # --- determinism across hash seeds --------------------------------
        man = os.path.join(tmp, 'basic.manifest')
        hashes = set()
        for seed in ('0', '1', '2', '3'):
            out = os.path.join(tmp, 'seed.ct')
            env = dict(os.environ, PYTHONHASHSEED=seed)
            subprocess.run([sys.executable, '-c',
                            'import sys; sys.path.insert(0, sys.argv[1]); import build_release;'
                            'build_release.build(sys.argv[2], sys.argv[3], date=sys.argv[4])',
                            HERE, man, out, DATE],
                           check=True, env=env, capture_output=True)
            hashes.add(open(out, 'rb').read())
        check('python output identical across hash seeds', len(hashes) == 1)

        # --- supporter header keeps the template's fixed 15/16 spacing ---------
        r = subprocess.run([node, '-e', """
            const T = require(process.argv[1]); const fs = require('fs');
            const tpl = fs.readFileSync(process.argv[2], 'utf8');
            const s = T.parseSupporters(tpl);
            const aug = T.applySupporters(tpl, Object.assign({}, s, { month: 'August' }));
            process.stdout.write(JSON.stringify({
              idem: T.applySupporters(tpl, s) === tpl,
              aug: /"(-+ +August \\d{4} Supporters +-+)"/.exec(aug)[1],
            }));""", core, tpl], capture_output=True, text=True)
        sup = json.loads(r.stdout)
        check('applySupporters(parseSupporters(tpl)) is a no-op on the template', sup['idem'])
        check('supporter header: 15 spaces before the label, 16 after, for any month',
              re.match(r'^-{7} {15}August \d{4} Supporters {16}-{7}$', sup['aug']) is not None, sup['aug'])

        # --- remap helper never touches hotkey blocks ---------------------
        sample = ('<CheatEntry><ID>0</ID><Hotkeys><Hotkey><ID>0</ID></Hotkey></Hotkeys>'
                  '</CheatEntry>')
        check('remap_entry_ids leaves hotkey IDs alone',
              build_release.remap_entry_ids(sample, [('0', '10000')]) ==
              '<CheatEntry><ID>10000</ID><Hotkeys><Hotkey><ID>0</ID></Hotkey></Hotkeys></CheatEntry>')
        check('entry_ids ignores hotkey IDs', build_release.entry_ids(sample) == {'0'})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print('FAILURES:', failures)
        raise SystemExit(1)
    print('all parity tests passed')


if __name__ == '__main__':
    main()

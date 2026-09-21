# -*- coding: utf-8 -*-
"""Build a "The Cheat Script" release table from a raw work .CT + a manifest.

Usage:
    python build_release.py <manifest file> [-o output.ct]

Without -o the table is written to the CE tables folder ($TCS_TABLES, default
D:\CE tables) when it exists, else next to the manifest.

Manifest format (plain text; a '#' at line start, or one surrounded by
whitespace, starts a comment - so "Item #2" is a valid feature name):
    game: Last Breath
    version: v1.0
    table: v1.0            # optional, default v1.0
    exe: LastBreath.exe    # for the auto-attach Lua; optional
    source: LastBreath.CT  # raw table path, relative to manifest dir
    init: auto             # auto | unity | dotnet | none  (default auto)

    [stats]
    Unlimited Currency
    [battle]
    Get HP Address -> Get HP Addresses     # rename: source -> release name
    Unlimited Stamina

Category sections may be omitted if the raw table's entry descriptions carry
[S]/[B]/[E] prefixes (e.g. "[B] Get HP Address").

Rules encoded here (see memory/aob-pattern-hygiene.md):
- structures are never carried into a release
- unused slots / empty groups / toolbox / niche / misc sections are pruned
- each script gets the credit header unless it already carries one
"""
import io
import os
import re
import sys
import datetime
from pathlib import Path

NL = '\r\n'

SLOTS = {
    'stats':  (['TCS.S01', 'TCS.S02', 'TCS.S03'],
               ['TCS.S04', 'TCS.S05', 'TCS.S06', 'TCS.S07', 'TCS.S08', 'TCS.S09', 'TCS.S0A'],
               '[Stats+]'),
    'battle': (['TCS.B01', 'TCS.B02', 'TCS.B03', 'TCS.B04'],
               ['TCS.B05', 'TCS.B06', 'TCS.B07', 'TCS.B08', 'TCS.B09', 'TCS.B0A'],
               '[Battle+]'),
    'extra':  (['TCS.E01', 'TCS.E02', 'TCS.E03'],
               ['TCS.E04', 'TCS.E05', 'TCS.E06', 'TCS.E07', 'TCS.E08', 'TCS.E09', 'TCS.E00'],
               '[Extra+]'),
}
GROUP_DESC = {'stats': '"[Stats]', 'battle': '"[Battle]', 'extra': '"[Extra]'}


def read(path):
    return io.open(path, encoding='utf-8', newline='').read()


def parse_manifest(path):
    m = {'meta': {}, 'stats': [], 'battle': [], 'extra': []}
    section = None
    for raw in read(path).splitlines():
        line = re.split(r'(?:^|\s)#(?=\s|$)', raw, 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].lower()
            if section not in ('stats', 'battle', 'extra'):
                sys.exit('unknown section [%s]' % section)
            continue
        if section is None:
            k, _, v = line.partition(':')
            m['meta'][k.strip().lower()] = v.strip()
        else:
            src, _, dst = line.partition('->')
            src, dst = src.strip(), dst.strip()
            m[section].append((src, dst or src))
    return m


# ---------------- CheatEntry block helpers ----------------

def entry_bounds(lines, needle, start=0):
    di = None
    for i in range(start, len(lines)):
        if needle in lines[i]:
            di = i
            break
    if di is None:
        raise KeyError(needle)
    s = di
    while '<CheatEntry>' not in lines[s]:
        s -= 1
    depth = 0
    for j in range(s, len(lines)):
        depth += lines[j].count('<CheatEntry>')
        depth -= lines[j].count('</CheatEntry>')
        if depth == 0:
            return s, j
    raise ValueError('unbalanced entry: ' + needle)


def delete_entry(text, needle):
    lines = text.splitlines(keepends=True)
    s, e = entry_bounds(lines, needle)
    return ''.join(lines[:s] + lines[e + 1:])


def extract_entry(text, desc):
    lines = text.splitlines(keepends=True)
    s, e = entry_bounds(lines, '<Description>"%s"</Description>' % desc)
    return ''.join(lines[s:e + 1])


def xml_escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def xml_unescape(text):
    return text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')


def xml_text(name):
    """A description as it must appear in the table: escape once, whether the
    manifest wrote 'Ammo & Fuel' or (copied from the table) 'Ammo &amp; Fuel'."""
    return xml_escape(xml_unescape(name))


def strip_comments(body):
    body = re.sub(r'\{(?!\$).*?\}', '', body, flags=re.S)   # {...} blocks (not {$lua})
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)       # /* ... */
    return re.sub(r'//[^\r\n]*', '', body)                  # // lines


# Class:Method / Namespace.Class:Method - a mono (Unity) symbol reference
MONO_SYMBOL = re.compile(r'[A-Za-z_][\w.]*:[A-Za-z_.][\w.]*')


def uses_mono(body):
    code = strip_comments(body)
    return 'LaunchMonoDataCollector' in code or MONO_SYMBOL.search(code) is not None


def list_scripts(text):
    """Every entry with a script of its own, at any depth: [(name, path, body)]
    where path is the folder chain ('Old stuff / Unlimited HP'). Children of a
    script entry are its sub-scripts, not features, so they are not listed.
    The TCS Dev Starter's button entries are skipped."""
    lines = text.splitlines(keepends=True)
    out, stack, i = [], [], 0
    while i < len(lines):
        if '<CheatEntry>' in lines[i]:
            s, e = entry_bounds(lines, '<CheatEntry>', i)
            block = ''.join(lines[s:e + 1])
            m = re.search(r'<Description>"([^"]*)"</Description>', block)
            name = m.group(1) if m else ''
            if name.find('TCS Dev Starter') >= 0 or 'TCS.createTableScript' in block:
                i = e + 1
                continue
            if has_own_script(block):
                out.append((name, ' / '.join(stack + [name]), get_script_body(block)))
                i = e + 1
                continue
            stack.append(name)
            j = i + 1          # descend: scan the children, then pop at </CheatEntry>
            i = j
            continue
        if '</CheatEntry>' in lines[i] and stack:
            stack.pop()
        i += 1
    return out


def with_credit_header(body, header):
    """Prepend the credit header, keeping any {$lua}/{$asm} or other code that
    sits before [ENABLE]; only CE's boilerplate { Game: ... Author: ... }
    comment (and blank lines) are dropped."""
    if 'Cheat Script by ColonelRVH' in body:
        return body
    en = body.find('[ENABLE]')
    if en < 0:
        return header + body
    pre = re.sub(r'\{(?!\$).*?\}', '', body[:en], flags=re.S).lstrip()
    if pre and not pre.endswith('\n'):
        pre += NL
    return header + pre + body[en:]


def has_own_script(entry_text):
    """An entry's OWN script sits before its nested <CheatEntries>; a group
    header with script children has none of its own (and taking the first
    <AssemblerScript> there would silently steal a child's script)."""
    a = entry_text.find('<AssemblerScript')
    if a < 0:
        return False
    c = entry_text.find('<CheatEntries>')
    return c < 0 or a < c


def get_script_body(entry_text):
    a = entry_text.index('<AssemblerScript')
    a = entry_text.index('>', a) + 1
    b = entry_text.index('</AssemblerScript>', a)
    return entry_text[a:b]


def strip_dev_notes(body):
    """Drop the dev-starter scaffolding comment the template injects into code:
    ('// offset-agnostic form (swap in for release):' + its //  byte lines).
    The ORIGINAL CODE reference block is left intact."""
    return re.sub(
        r'//  offset-agnostic form \(swap in for release\):\r?\n'
        r'(?://    [^\r\n]*\r?\n)*',
        '', body)


HOTKEY_BLOCK = re.compile(r'<Hotkeys>.*?</Hotkeys>', re.S)


def entry_ids(text):
    """CheatEntry IDs only. <Hotkey> blocks carry their own <ID> tags (small
    per-record indexes) which must neither count as taken nor be remapped."""
    return set(re.findall(r'<ID>(\d+)</ID>', HOTKEY_BLOCK.sub('', text)))


def remap_entry_ids(text, mapping):
    """Rewrite entry <ID> tags per mapping, leaving <Hotkeys> blocks untouched."""
    out = []
    for i, part in enumerate(re.split(r'(<Hotkeys>.*?</Hotkeys>)', text, flags=re.S)):
        if i % 2 == 0:
            for old, new in mapping:
                part = part.replace('<ID>%s</ID>' % old, '<ID>%s</ID>' % new)
        out.append(part)
    return ''.join(out)


def get_children_block(entry_text):
    """The feature's own <CheatEntries> block (sub scripts), or None."""
    i = entry_text.find('<CheatEntries>')
    if i < 0:
        return None
    j = entry_text.rindex('</CheatEntries>')
    j = entry_text.index('\n', j) + 1
    start = entry_text.rindex('\n', 0, i) + 1
    return entry_text[start:j]


def reindent_children(block, target_indent):
    """Shift XML structure lines to target_indent; never touch script bodies."""
    src_indent = len(block) - len(block.lstrip(' '))
    first = block.splitlines()[0]
    src_indent = len(first) - len(first.lstrip(' '))
    delta = target_indent - src_indent
    out, in_script = [], False
    for ln in block.splitlines(keepends=True):
        if in_script:
            out.append(ln)
            if '</AssemblerScript>' in ln:
                in_script = False
        else:
            if ln.strip():
                cur = len(ln) - len(ln.lstrip(' '))
                out.append(' ' * max(0, cur + delta) + ln.lstrip(' '))
            else:
                out.append(ln)
            if '<AssemblerScript' in ln and '</AssemblerScript>' not in ln:
                in_script = True
    return ''.join(out)


# ---------------- sub-entry synthesis ----------------
# A feature with no hand-made children gets them generated from what its
# script registers: X_Flag -> Scroll Lock toggle sub-script, X_Mult ->
# "X Multiplier" (4 Bytes), X_Cap / X_HP -> Float value entries.

HOTKEY_145 = ['<Hotkeys>', '  <Hotkey>', '    <Action>Toggle Activation</Action>',
              '    <Keys>', '      <Key>145</Key>', '    </Keys>', '    <ID>0</ID>',
              '    <ActivateSound>Activate</ActivateSound>',
              '    <DeactivateSound>Deactivate</DeactivateSound>',
              '  </Hotkey>', '</Hotkeys>']


def humanize(base):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', base.replace('_', ' '))


def synth_symbols(body):
    """(flags, values) derivable from the script's registered symbols."""
    scan = {a.split(',')[0].strip()
            for _, a in re.findall(r'(aobscanmodule|aobscanregion)\(([^)]*)\)', body)}
    flags, values, seen = [], [], set()
    for s in re.findall(r'(?<!un)registersymbol\((\w+)\)', body):
        if s in scan or s.endswith('_CodeSave') or s in seen:
            continue
        seen.add(s)
        if s.endswith('_Flag'):
            flags.append((humanize(s[:-5]), s))
        elif s.endswith('_Mult'):
            values.append((humanize(s[:-5]) + ' Multiplier', s, '4 Bytes'))
        elif s.endswith('_Cap'):
            values.append((humanize(s[:-4]) + ' Cap', s, 'Float'))
        elif s.endswith('_HP'):
            values.append((humanize(s[:-3]) + ' HP', s, 'Float'))
    return flags, values


def synth_children(body, base_indent, take_id):
    """Children XML block at base_indent (the slot entry's indent + 2), or None."""
    flags, values = synth_symbols(body)
    if not flags and not values:
        return None

    def entry_lines(indent, name, sym, vartype):
        pad = ' ' * indent
        if vartype is None:  # flag toggle sub-script
            lines = [pad + '<CheatEntry>',
                     pad + '  <ID>%d</ID>' % take_id(),
                     pad + '  <Description>"%s"</Description>' % name,
                     pad + '  <Color>808000</Color>',
                     pad + '  <VariableType>Auto Assembler Script</VariableType>',
                     pad + '  <AssemblerScript>[ENABLE]',
                     "//code from here to '[DISABLE]' will be used to enable the cheat",
                     sym + ':', 'dd 1', '',
                     '[DISABLE]',
                     "//code from here till the end of the code will be used to disable the cheat",
                     sym + ':', 'dd 0',
                     '</AssemblerScript>']
            lines += [pad + '  ' + h for h in HOTKEY_145]
            lines += [pad + '</CheatEntry>']
        else:
            lines = [pad + '<CheatEntry>',
                     pad + '  <ID>%d</ID>' % take_id(),
                     pad + '  <Description>"%s"</Description>' % name,
                     pad + '  <ShowAsSigned>0</ShowAsSigned>',
                     pad + '  <VariableType>%s</VariableType>' % vartype,
                     pad + '  <Address>%s</Address>' % sym]
            lines += [pad + '</CheatEntry>']
        return lines

    pad = ' ' * base_indent
    out = [pad + '<CheatEntries>']
    if flags:
        wpad = pad + '  '
        out += [wpad + '<CheatEntry>',
                wpad + '  <ID>%d</ID>' % take_id(),
                wpad + '  <Description>"[Sub Scripts]  -- Toggle: Scroll Lock --"</Description>',
                wpad + '  <Options moActivateChildrenAsWell="1" moDeactivateChildrenAsWell="1"/>',
                wpad + '  <Color>808000</Color>',
                wpad + '  <GroupHeader>1</GroupHeader>']
        out += [wpad + '  ' + h for h in HOTKEY_145]
        out += [wpad + '  <CheatEntries>']
        for name, sym in flags:
            out += entry_lines(base_indent + 6, name, sym, None)
        for name, sym, vt in values:
            out += entry_lines(base_indent + 6, name, sym, vt)
        out += [wpad + '  </CheatEntries>',
                wpad + '</CheatEntry>']
    else:
        for name, sym, vt in values:
            out += entry_lines(base_indent + 2, name, sym, vt)
    out += [pad + '</CheatEntries>']
    return NL.join(out) + NL


# ---------------- main build ----------------

def build(manifest_path, out_path=None, date=None):
    warnings = []
    mdir = Path(manifest_path).resolve().parent
    m = parse_manifest(manifest_path)
    meta = m['meta']
    for key in ('game', 'version', 'source'):
        if key not in meta:
            sys.exit('manifest missing "%s:"' % key)
    table_ver = meta.get('table', 'v1.0')
    src_path = (mdir / meta['source'])
    if not src_path.exists():
        src_path = Path(meta['source'])
    src = read(src_path)
    tpl = read(Path(__file__).parent / 'template.ct')

    # --- auto-categorize from [S]/[B]/[E] prefixes if manifest sections empty
    if not (m['stats'] or m['battle'] or m['extra']):
        pref = {'[S]': 'stats', '[B]': 'battle', '[E]': 'extra'}
        for d in re.findall(r'<Description>"(\[[SBE]\] [^"]+)"</Description>', src):
            cat = pref[d[:3]]
            m[cat].append((d, d[4:]))
        if not (m['stats'] or m['battle'] or m['extra']):
            sys.exit('no features: manifest has no sections and raw table has no [S]/[B]/[E] prefixes')

    # --- credit header (verbatim from the template's own slots)
    h = tpl.index('<AssemblerScript>/*=====') + len('<AssemblerScript>')
    he = tpl.index('=================================================*/', h)
    he = tpl.index('\n', he) + 1
    header = tpl[h:he]

    # --- init scripts: keep only what the SELECTED scripts actually need
    init = meta.get('init', 'auto')
    if init not in ('auto', 'unity', 'dotnet', 'none'):
        sys.exit('init: must be auto, unity, dotnet or none (got "%s")' % init)
    if init == 'auto':
        chosen = ''
        for cat in ('stats', 'battle', 'extra'):
            for src_name, _ in m[cat]:
                needle = '<Description>"%s"</Description>' % src_name
                if needle not in src:
                    src_name = xml_text(src_name)
                try:
                    chosen += extract_entry(src, src_name)
                except KeyError:
                    pass          # reported properly by the slot loop below
        bodies = re.findall(r'<AssemblerScript[^>]*>(.*?)</AssemblerScript>', chosen, re.S)
        init = 'unity' if any(uses_mono(b) for b in bodies) else 'none'
    if init == 'none':
        tpl = delete_entry(tpl, '"=== Init Script [Delete If Not Needed] ==="')
    else:
        tpl = delete_entry(tpl, '"--- Initialize .NET Engine Cheat Features ---'
                           if init == 'unity' else
                           '"--- Initialize Unity Engine Cheat Features ---')
        tpl = tpl.replace('"=== Init Script [Delete If Not Needed] ==="',
                          '"=== Init Script ==="')

    # --- header entry
    today = date or datetime.date.today().isoformat()
    tpl = re.sub(r'"Game v \| Cheat Engine Table v1\.0 \| [0-9-]+ The Cheat Script"',
                 lambda _: '"%s %s | Cheat Engine Table %s | %s The Cheat Script"'
                 % (xml_text(meta['game']), xml_text(meta['version']), xml_text(table_ver), today), tpl)

    # --- always-pruned sections (absent from a pre-cleaned template: fine)
    for needle in ('"[Niche Usage]', '"[Misc.][!]"', '[TOOLBOX/TEMPLATES'):
        try:
            tpl = delete_entry(tpl, needle)
        except KeyError:
            pass

    # --- avoid ID collisions between template and imported children
    tpl_ids = entry_ids(tpl)

    # --- every script in the raw table, for duplicate-name / same-code warnings
    scripts = list_scripts(src)

    def norm(b):
        return re.sub(r'\s+', ' ', strip_dev_notes(b)).strip()

    def warn(msg):
        warnings.append(msg)
        print('WARN', msg)

    # --- fill slots
    for cat in ('stats', 'battle', 'extra'):
        top, plus, plus_desc = SLOTS[cat]
        feats = m[cat]
        if len(feats) > len(top) + len(plus):
            sys.exit('too many %s features (%d max)' % (cat, len(top) + len(plus)))
        order = top + plus
        for slot, (src_name, rel_name) in zip(order, feats):
            # the manifest may spell the name as shown ('Ammo & Fuel') or as
            # stored in the table ('Ammo &amp; Fuel')
            if '<Description>"%s"</Description>' % src_name not in src:
                if '<Description>"%s"</Description>' % xml_text(src_name) in src:
                    src_name = xml_text(src_name)
            entry = extract_entry(src, src_name)
            if not has_own_script(entry):
                sys.exit('"%s" has no Auto Assembler script of its own, so it cannot'
                         ' fill a slot - remove it from the manifest. (Group headers,'
                         ' pointers and value entries are not features.)' % src_name)
            body = strip_dev_notes(get_script_body(entry))
            same_name = [p for n, p, _ in scripts if n == src_name]
            if len(same_name) > 1:
                warn('"%s" appears %d times in the raw table (%s); using the first'
                     % (src_name, len(same_name), ', '.join(same_name)))
            twins = [p for n, p, b in scripts if n != src_name and norm(b) == norm(body)]
            if twins:
                warn('"%s" has the same script as %s' % (src_name, ', '.join(twins)))
            body = with_credit_header(body, header)
            children = get_children_block(entry)
            rel_name = xml_text(rel_name)

            def take_id():
                nid = 10000
                while str(nid) in tpl_ids:
                    nid += 1
                tpl_ids.add(str(nid))
                return nid

            # the slot entry, located once by its template name; everything
            # below edits that entry's own text so a release name that is
            # duplicated or equal to a template description cannot mislead
            lines = tpl.splitlines(keepends=True)
            s_, e_ = entry_bounds(lines, '<Description>"%s"</Description>' % slot)
            slot_indent = len(lines[s_]) - len(lines[s_].lstrip(' '))
            ent = ''.join(lines[s_:e_ + 1])

            key = '<Description>"%s"</Description>' % slot
            i = ent.index(key)
            ent = ent[:i] + '<Description>"%s"</Description>' % rel_name + ent[i + len(key):]
            a = ent.index('<AssemblerScript>', i) + len('<AssemblerScript>')
            b = ent.index('</AssemblerScript>', a)
            ent = ent[:a] + body + ent[b:]

            if children:
                # remap child IDs that collide with the template (sorted:
                # a set's order varies with the hash seed, and the JS port
                # must produce the same bytes)
                mapping = [(cid, take_id()) for cid in sorted(entry_ids(children), key=int)
                           if cid in tpl_ids]
                children = remap_entry_ids(children, mapping)
                block = reindent_children(children, slot_indent + 2)
            else:
                # no hand-made children: derive them from registered symbols
                block = synth_children(body, slot_indent + 2, take_id)
            if block:
                close = ent.rindex('</CheatEntry>')
                close = ent.rindex('\n', 0, close) + 1
                ent = ent[:close] + block + ent[close:]
                # a feature with sub scripts should toggle them along
                opt_i = ent.index('<Options')
                opt_j = ent.index('/>', opt_i) + 2
                opts = ent[opt_i:opt_j]
                for need in ('moActivateChildrenAsWell="1"', 'moDeactivateChildrenAsWell="1"'):
                    if need not in opts:
                        opts = opts.replace('/>', ' %s/>' % need)
                ent = ent[:opt_i] + opts + ent[opt_j:]

            tpl = ''.join(lines[:s_]) + ent + ''.join(lines[e_ + 1:])

        # prune leftovers
        for slot in order[len(feats):]:
            if '"%s"' % slot in tpl:
                tpl = delete_entry(tpl, '"%s"' % slot)
        if len(feats) <= len(top) and plus_desc:
            try:
                tpl = delete_entry(tpl, '"%s"' % plus_desc)
            except KeyError:
                pass
        if not feats:
            tpl = delete_entry(tpl, GROUP_DESC[cat])

    # --- auto-attach exe
    if meta.get('exe'):
        tpl = tpl.replace('stringlist_add(attachlist,"game.exe");',
                          'stringlist_add(attachlist,"%s");' % meta['exe'])

    # NOTE: the raw table's <Structures> section is deliberately NOT carried over.

    if out_path is None:
        tables = Path(os.environ.get('TCS_TABLES', r'D:\CE tables'))
        out_path = (tables if tables.is_dir() else mdir) / (
            '%s %s_Table %s_The Cheat Script.ct' % (meta['game'], meta['version'], table_ver))
    io.open(out_path, 'w', encoding='utf-8', newline='').write(tpl)

    # sanity
    import xml.etree.ElementTree as ET
    try:
        ET.parse(out_path)
    except ET.ParseError as e:
        sys.exit('built table is not well-formed XML (%s) - check names for stray < or &' % e)
    data = open(out_path, 'rb').read()
    assert data.count(b'\n') == data.count(b'\r\n'), 'mixed line endings'
    assert 'TCS.' not in tpl or not re.search(r'<Description>"TCS\.', tpl), 'leftover slots'
    print('built:', out_path)
    return str(out_path)


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    out = None
    if '-o' in args:
        i = args.index('-o')
        out = args[i + 1]
        del args[i:i + 2]
    build(args[0], out)

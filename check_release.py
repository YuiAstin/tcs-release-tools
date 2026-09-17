# -*- coding: utf-8 -*-
"""Lint a release .CT against The Cheat Script conventions and AOB hygiene rules.

Usage: python check_release.py <table.ct>

ERROR = must fix before release. WARN = judgment call, look at it.
Exit code: number of errors.
"""
import io
import re
import sys
import datetime
import xml.etree.ElementTree as ET

issues = []


def err(msg):
    issues.append(('ERROR', msg))


def warn(msg):
    issues.append(('WARN ', msg))


def strip_comments(body):
    body = re.sub(r'\{.*?\}', '', body, flags=re.S)      # {...} blocks
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)    # /* ... */
    body = re.sub(r'//[^\r\n]*', '', body)               # // lines
    return body


def check(path):
    data = open(path, 'rb').read()

    # -- file format
    if data.count(b'\n') != data.count(b'\r\n'):
        err('mixed line endings (%d lone LF)' % (data.count(b'\n') - data.count(b'\r\n')))
    try:
        t = data.decode('utf-8')
    except UnicodeDecodeError as e:
        err('not valid UTF-8: %s' % e)
        return
    try:
        ET.fromstring(t.encode('utf-8'))
    except ET.ParseError as e:
        err('XML does not parse: %s' % e)
        return

    # -- release hygiene
    if re.search(r'<Description>"TCS\.', t):
        err('leftover template slots: %s' % sorted(set(re.findall(r'"(TCS\.[^"]*)"', t))))
    if 'TOOLBOX/TEMPLATES' in t:
        err('template toolbox section still present')
    if 'TCS.createTableScript' in t or 'TCS Dev Starter' in t:
        err('TCS Dev Starter button entries still present - remove that group before release')
    if '<Structures' in t:
        err('Structures section present - dissect data stays in the source table')
    if '"[Niche Usage]' in t or '"[Misc.][!]"' in t:
        warn('[Niche Usage]/[Misc.] section present - intended?')
    if 'stringlist_add(attachlist,"game.exe")' in t:
        err('auto-attach still says game.exe')
    if '"Game v |' in t:
        err('header entry still has template placeholder text')
    m = re.search(r'"-------\s+(\w+) (\d{4}) Supporters', t)
    if m:
        month, year = m.group(1), int(m.group(2))
        now = datetime.date.today()
        months = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                  'August', 'September', 'October', 'November', 'December']
        if month in months:
            age = (now.year - year) * 12 + now.month - (months.index(month) + 1)
            if age > 1:
                warn('supporter list is %d months old (%s %d)' % (age, month, year))

    # -- per-script checks
    scripts = re.findall(
        r'<Description>("[^"]+")</Description>(?:(?!<AssemblerScript|</CheatEntry>|<Description>).)*?'
        r'<AssemblerScript[^>]*>(.*?)</AssemblerScript>', t, re.S)
    for name, body in scripts:
        code = strip_comments(body)

        for fn, args in re.findall(r'(aobscanmodule|aobscanregion)\(([^)]*)\)', code):
            parts = [p.strip() for p in args.split(',')]
            pattern = parts[-1].split()
            sym = parts[0]
            # rule 1: no trailing wildcards
            if pattern and pattern[-1] == '*':
                err('%s %s: trailing wildcard(s) in AOB - trim them' % (name, sym))
            # rule 3: E8/E9 call/jmp rel32 displacement bytes are fragile
            for i, b in enumerate(pattern):
                if b.upper() in ('E8', 'E9'):
                    tail = pattern[i + 1:i + 5]
                    if tail and any(x != '*' for x in tail):
                        warn('%s %s: byte %d is %s followed by unmasked bytes - '
                             'if that is a call/jmp rel32, mask its displacement'
                             % (name, sym, i, b.upper()))

        # rule 4: big hardcoded offsets in active code want the readmem treatment
        has_readmem = 'readmem(' in code
        for off in set(re.findall(r'\[(?:r[a-z0-9]+)(?:\+r[a-z0-9]+\*\d)?\+([0-9A-Fa-f]{2,})\]', code)):
            v = int(off, 16)
            if v > 0x60 and not has_readmem:
                warn('%s: hardcoded offset 0x%X in active code with no readmem - '
                     'breaks silently-wrong on game updates if the AOB still matches' % (name, v))

        # dead registered symbols: registered here but never actually referenced
        # anywhere in the table. A reference is (case-insensitive, CE symbols are):
        #   [sym] as an instruction operand, readmem(sym,...), aobscanregion using it,
        #   or "sym:" as a write target in a DIFFERENT script (flag toggles do this).
        # aobscan result symbols are registered by convention (jump-to-site anchor)
        scan_syms = {a.split(',')[0].strip()
                     for _, a in re.findall(r'(aobscanmodule|aobscanregion)\(([^)]*)\)', code)}
        for s in re.findall(r'(?<!un)registersymbol\((\w+)\)', code):
            if s in scan_syms:
                continue
            pat = re.escape(s)
            bracket = re.findall(r'\[%s(?:[+\-]|\])' % pat, t, re.I)
            rdmem = re.findall(r'readmem\(\s*%s\b' % pat, t, re.I)
            region = re.findall(r'aobscanregion\([^,]+,\s*%s\b' % pat, t, re.I)
            addr = re.findall(r'<Address>[^<]*\b%s\b[^<]*</Address>' % pat, t, re.I)
            other = [b for _, b in scripts
                     if b is not body and re.search(r'^\s*%s:' % pat, b, re.I | re.M)]
            if not (bracket or rdmem or region or addr or other):
                warn('%s: symbol %s is registered but never used' % (name, s))

    return


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    check(sys.argv[1])
    if not issues:
        print('clean: no issues')
    for lvl, msg in issues:
        print(lvl, msg)
    sys.exit(sum(1 for lvl, _ in issues if lvl == 'ERROR'))

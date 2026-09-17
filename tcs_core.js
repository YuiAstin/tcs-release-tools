/* TCS release core — JS port of build_release.py / check_release.py.
 * Runs in the browser (window.TCSCore) and in node (module.exports) so the
 * exact shipped file is testable against the Python reference output.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TCSCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var NL = '\r\n';

  var SLOTS = {
    stats: [['TCS.S01', 'TCS.S02', 'TCS.S03'],
            ['TCS.S04', 'TCS.S05', 'TCS.S06', 'TCS.S07', 'TCS.S08', 'TCS.S09', 'TCS.S0A'],
            '[Stats+]'],
    battle: [['TCS.B01', 'TCS.B02', 'TCS.B03', 'TCS.B04'],
             ['TCS.B05', 'TCS.B06', 'TCS.B07', 'TCS.B08', 'TCS.B09', 'TCS.B0A'],
             '[Battle+]'],
    extra: [['TCS.E01', 'TCS.E02', 'TCS.E03'],
            ['TCS.E04', 'TCS.E05', 'TCS.E06', 'TCS.E07', 'TCS.E08', 'TCS.E09', 'TCS.E00'],
            '[Extra+]'],
  };
  var GROUP_DESC = { stats: '"[Stats]', battle: '"[Battle]', extra: '"[Extra]' };

  function splitKeep(text) { return text.length ? text.split(/(?<=\n)/) : []; }
  function count(hay, needle) {
    var n = 0, i = 0;
    for (;;) { i = hay.indexOf(needle, i); if (i < 0) return n; n++; i += needle.length; }
  }
  function idx(text, needle, from) {
    var i = text.indexOf(needle, from || 0);
    if (i < 0) throw new Error('not found: ' + needle.slice(0, 60));
    return i;
  }

  function entryBounds(lines, needle) {
    var di = -1;
    for (var i = 0; i < lines.length; i++) if (lines[i].indexOf(needle) >= 0) { di = i; break; }
    if (di < 0) { var e = new Error('not found: ' + needle); e.notFound = true; throw e; }
    var s = di;
    while (lines[s].indexOf('<CheatEntry>') < 0) s--;
    var depth = 0;
    for (var j = s; j < lines.length; j++) {
      depth += count(lines[j], '<CheatEntry>');
      depth -= count(lines[j], '</CheatEntry>');
      if (depth === 0) return [s, j];
    }
    throw new Error('unbalanced entry: ' + needle);
  }

  function deleteEntry(text, needle) {
    var lines = splitKeep(text);
    var se = entryBounds(lines, needle);
    return lines.slice(0, se[0]).concat(lines.slice(se[1] + 1)).join('');
  }

  function extractEntry(text, desc) {
    var lines = splitKeep(text);
    var se = entryBounds(lines, '<Description>"' + desc + '"</Description>');
    return lines.slice(se[0], se[1] + 1).join('');
  }

  function getScriptBody(entryText) {
    var a = idx(entryText, '<AssemblerScript');
    a = idx(entryText, '>', a) + 1;
    var b = idx(entryText, '</AssemblerScript>', a);
    return entryText.slice(a, b);
  }

  // Drop the dev-starter scaffolding comment injected into code: (the
  // '// offset-agnostic form (swap in for release):' block + its //  byte
  // lines). The ORIGINAL CODE reference block is left intact.
  function stripDevNotes(body) {
    return body.replace(
      /\/\/  offset-agnostic form \(swap in for release\):\r?\n(?:\/\/    [^\r\n]*\r?\n)*/g,
      '');
  }

  function getChildrenBlock(entryText) {
    var i = entryText.indexOf('<CheatEntries>');
    if (i < 0) return null;
    var j = entryText.lastIndexOf('</CheatEntries>');
    j = idx(entryText, '\n', j) + 1;
    var start = entryText.lastIndexOf('\n', i) + 1;
    return entryText.slice(start, j);
  }

  function reindentChildren(block, targetIndent) {
    var first = block.split('\n')[0];
    var srcIndent = first.length - first.replace(/^ +/, '').length;
    var delta = targetIndent - srcIndent;
    var out = [], inScript = false;
    splitKeep(block).forEach(function (ln) {
      if (inScript) {
        out.push(ln);
        if (ln.indexOf('</AssemblerScript>') >= 0) inScript = false;
      } else {
        if (ln.trim()) {
          var cur = ln.length - ln.replace(/^ +/, '').length;
          out.push(' '.repeat(Math.max(0, cur + delta)) + ln.replace(/^ +/, ''));
        } else out.push(ln);
        if (ln.indexOf('<AssemblerScript') >= 0 && ln.indexOf('</AssemblerScript>') < 0) inScript = true;
      }
    });
    return out.join('');
  }

  function reEscape(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function findAll(re, text) {
    var out = [], m, r = new RegExp(re.source, re.flags.indexOf('g') >= 0 ? re.flags : re.flags + 'g');
    while ((m = r.exec(text)) !== null) { out.push(m); if (m.index === r.lastIndex) r.lastIndex++; }
    return out;
  }

  /* ------------------------------------------------------------------ */
  /* supporter list API — template.ct is the single source of truth, so  */
  /* an updated template keeps the Python builder in sync automatically. */
  /* ------------------------------------------------------------------ */

  function xmlEscape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function xmlUnescape(s) {
    return String(s).replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  }

  // "-------               July 2026 Supporters                -------"
  // centred in the template's 51-char inner field
  function supportersHeader(month, year) {
    var label = month + ' ' + year + ' Supporters';
    var pad = 51 - label.length;
    if (pad < 2) pad = 2;
    var left = Math.floor(pad / 2);
    return '-------' + ' '.repeat(left) + label + ' '.repeat(pad - left) + '-------';
  }

  function findSupportersDesc(tpl) {
    return /<Description>"(-+\s*(\w+) (\d{4}) Supporters\s*-+)"<\/Description>/.exec(tpl);
  }

  // split a block's direct child <CheatEntry> blocks
  function childEntryBlocks(inner) {
    var il = splitKeep(inner), out = [], depth = 0, start = -1;
    for (var i = 0; i < il.length; i++) {
      var o = count(il[i], '<CheatEntry>'), c = count(il[i], '</CheatEntry>');
      if (o && depth === 0) start = i;
      depth += o;
      if (c) {
        depth -= c;
        if (depth <= 0 && start >= 0) {
          out.push(il.slice(start, i + 1).join(''));
          start = -1; depth = 0;
        }
      }
    }
    return out;
  }

  /* -> {month, year, note, noteId, groupId, names:[{name,color,id}]} or null */
  function parseSupporters(tpl) {
    var m = findSupportersDesc(tpl);
    if (!m) return null;
    var lines = splitKeep(tpl);
    var se = entryBounds(lines, '<Description>"' + m[1] + '"</Description>');
    var block = lines.slice(se[0], se[1] + 1).join('');
    var gid = /<ID>(\d+)<\/ID>/.exec(block);
    var inner = getChildrenBlock(block);
    var kids = [];
    if (inner) {
      childEntryBlocks(inner).forEach(function (kb) {
        var dm = /<Description>"([^"]*)"<\/Description>/.exec(kb);
        if (!dm) return;
        var cm = /<Color>([0-9A-Fa-f]+)<\/Color>/.exec(kb);
        var im = /<ID>(\d+)<\/ID>/.exec(kb);
        kids.push({
          name: xmlUnescape(dm[1]),
          color: cm ? cm[1] : '004080',
          id: im ? im[1] : null,
        });
      });
    }
    return {
      month: m[2], year: m[3],
      groupId: gid ? gid[1] : null,
      note: kids.length ? kids[0].name : '',
      noteId: kids.length ? kids[0].id : null,
      names: kids.slice(1),
    };
  }

  /* rebuild the SPECIAL THANKS supporters group from `data` */
  function applySupporters(tpl, data) {
    var m = findSupportersDesc(tpl);
    if (!m) return tpl;
    var lines = splitKeep(tpl);
    var se = entryBounds(lines, '<Description>"' + m[1] + '"</Description>');
    var head = lines[se[0]];
    var pad = ' '.repeat(head.length - head.replace(/^ +/, '').length);

    var used = {};
    findAll(/<ID>(\d+)<\/ID>/g, tpl).forEach(function (x) { used[x[1]] = true; });
    var next = 9200;
    function takeId(preferred) {
      if (preferred && String(preferred).length) return preferred;
      while (used[String(next)]) next++;
      used[String(next)] = true;
      return String(next);
    }

    var out = [pad + '<CheatEntry>',
      pad + '  <ID>' + takeId(data.groupId) + '</ID>',
      pad + '  <Description>"' + supportersHeader(data.month, data.year) + '"</Description>',
      pad + '  <Options moHideChildren="1"/>',
      pad + '  <Color>0066FF</Color>',
      pad + '  <GroupHeader>1</GroupHeader>',
      pad + '  <CheatEntries>'];

    function kid(name, color, id) {
      out.push(pad + '    <CheatEntry>',
        pad + '      <ID>' + takeId(id) + '</ID>',
        pad + '      <Description>"' + xmlEscape(name) + '"</Description>',
        pad + '      <Color>' + color + '</Color>',
        pad + '      <GroupHeader>1</GroupHeader>',
        pad + '    </CheatEntry>');
    }
    if (data.note) kid(data.note, '0066FF', data.noteId);
    (data.names || []).forEach(function (n) {
      var o = typeof n === 'string' ? { name: n } : n;
      if (!o.name || !String(o.name).trim()) return;
      kid(String(o.name).trim(), o.color || '004080', o.id);
    });
    out.push(pad + '  </CheatEntries>', pad + '</CheatEntry>');

    return lines.slice(0, se[0])
      .concat([out.join(NL) + NL])
      .concat(lines.slice(se[1] + 1)).join('');
  }

  /* ------------------------------------------------------------------ */
  /* manifest round-trip (same format build_release.py parses)           */
  /* ------------------------------------------------------------------ */

  function serializeManifest(cfg) {
    var L = ['game: ' + cfg.game, 'version: ' + cfg.version,
             'table: ' + (cfg.table || 'v1.0')];
    if (cfg.exe) L.push('exe: ' + cfg.exe);
    if (cfg.source) L.push('source: ' + cfg.source);
    L.push('init: ' + (cfg.init || 'auto'));
    ['stats', 'battle', 'extra'].forEach(function (cat) {
      var feats = cfg[cat] || [];
      if (!feats.length) return;
      L.push('', '[' + cat + ']');
      feats.forEach(function (f) {
        L.push(f[0] === f[1] ? f[0] : f[0] + ' -> ' + f[1]);
      });
    });
    return L.join(NL) + NL;
  }

  function parseManifest(text) {
    var cfg = { stats: [], battle: [], extra: [] }, section = null;
    text.split(/\r?\n/).forEach(function (raw) {
      var line = raw.split('#')[0].trim();
      if (!line) return;
      if (line.charAt(0) === '[' && line.charAt(line.length - 1) === ']') {
        var s = line.slice(1, -1).toLowerCase();
        section = (s === 'stats' || s === 'battle' || s === 'extra') ? s : null;
        return;
      }
      if (section === null) {
        var i = line.indexOf(':');
        if (i > 0) cfg[line.slice(0, i).trim().toLowerCase()] = line.slice(i + 1).trim();
      } else {
        var p = line.split('->');
        var src = p[0].trim(), dst = (p[1] || '').trim();
        cfg[section].push([src, dst || src]);
      }
    });
    return cfg;
  }

  /* ------------------------------------------------------------------ */
  /* sub-entry synthesis: a feature with no hand-made children gets them */
  /* generated from what its script registers (X_Flag -> Scroll Lock     */
  /* toggle, X_Mult -> 4-byte value entry, X_Cap / X_HP -> Float).       */
  /* ------------------------------------------------------------------ */

  var HOTKEY_145 = ['<Hotkeys>', '  <Hotkey>', '    <Action>Toggle Activation</Action>',
    '    <Keys>', '      <Key>145</Key>', '    </Keys>', '    <ID>0</ID>',
    '    <ActivateSound>Activate</ActivateSound>',
    '    <DeactivateSound>Deactivate</DeactivateSound>', '  </Hotkey>', '</Hotkeys>'];

  function humanize(base) {
    return base.replace(/_/g, ' ').replace(/(?<=[a-z0-9])(?=[A-Z])/g, ' ');
  }

  function synthSymbols(body) {
    var scan = {};
    findAll(/(aobscanmodule|aobscanregion)\(([^)]*)\)/g, body).forEach(function (m) {
      scan[m[2].split(',')[0].trim()] = true;
    });
    var flags = [], values = [], seen = {};
    findAll(/(?<!un)registersymbol\((\w+)\)/g, body).forEach(function (m) {
      var s = m[1];
      if (scan[s] || /_CodeSave$/.test(s) || seen[s]) return;
      seen[s] = true;
      if (/_Flag$/.test(s)) flags.push([humanize(s.slice(0, -5)), s]);
      else if (/_Mult$/.test(s)) values.push([humanize(s.slice(0, -5)) + ' Multiplier', s, '4 Bytes']);
      else if (/_Cap$/.test(s)) values.push([humanize(s.slice(0, -4)) + ' Cap', s, 'Float']);
      else if (/_HP$/.test(s)) values.push([humanize(s.slice(0, -3)) + ' HP', s, 'Float']);
    });
    return { flags: flags, values: values };
  }

  function synthChildren(body, baseIndent, takeId) {
    var sy = synthSymbols(body);
    if (!sy.flags.length && !sy.values.length) return null;

    function entryLines(indent, name, sym, vartype) {
      var pad = ' '.repeat(indent), lines;
      if (vartype === null) {
        lines = [pad + '<CheatEntry>',
                 pad + '  <ID>' + takeId() + '</ID>',
                 pad + '  <Description>"' + name + '"</Description>',
                 pad + '  <Color>808000</Color>',
                 pad + '  <VariableType>Auto Assembler Script</VariableType>',
                 pad + '  <AssemblerScript>[ENABLE]',
                 "//code from here to '[DISABLE]' will be used to enable the cheat",
                 sym + ':', 'dd 1', '',
                 '[DISABLE]',
                 "//code from here till the end of the code will be used to disable the cheat",
                 sym + ':', 'dd 0',
                 '</AssemblerScript>']
          .concat(HOTKEY_145.map(function (h) { return pad + '  ' + h; }))
          .concat([pad + '</CheatEntry>']);
      } else {
        lines = [pad + '<CheatEntry>',
                 pad + '  <ID>' + takeId() + '</ID>',
                 pad + '  <Description>"' + name + '"</Description>',
                 pad + '  <ShowAsSigned>0</ShowAsSigned>',
                 pad + '  <VariableType>' + vartype + '</VariableType>',
                 pad + '  <Address>' + sym + '</Address>',
                 pad + '</CheatEntry>'];
      }
      return lines;
    }

    var pad = ' '.repeat(baseIndent);
    var out = [pad + '<CheatEntries>'];
    if (sy.flags.length) {
      var wpad = pad + '  ';
      out = out.concat([wpad + '<CheatEntry>',
        wpad + '  <ID>' + takeId() + '</ID>',
        wpad + '  <Description>"[Sub Scripts]  -- Toggle: Scroll Lock --"</Description>',
        wpad + '  <Options moActivateChildrenAsWell="1" moDeactivateChildrenAsWell="1"/>',
        wpad + '  <Color>808000</Color>',
        wpad + '  <GroupHeader>1</GroupHeader>'])
        .concat(HOTKEY_145.map(function (h) { return wpad + '  ' + h; }))
        .concat([wpad + '  <CheatEntries>']);
      sy.flags.forEach(function (f) { out = out.concat(entryLines(baseIndent + 6, f[0], f[1], null)); });
      sy.values.forEach(function (v) { out = out.concat(entryLines(baseIndent + 6, v[0], v[1], v[2])); });
      out = out.concat([wpad + '  </CheatEntries>', wpad + '</CheatEntry>']);
    } else {
      sy.values.forEach(function (v) { out = out.concat(entryLines(baseIndent + 2, v[0], v[1], v[2])); });
    }
    out.push(pad + '</CheatEntries>');
    return out.join(NL) + NL;
  }

  /* ------------------------------------------------------------------ */
  /* build                                                              */
  /* ------------------------------------------------------------------ */

  // The TCS Dev Starter's own button entries: they ride along when someone
  // saves their work table from the starter, and are not cheat features.
  function isStarterScaffold(block, desc) {
    return block.indexOf('TCS.createTableScript') >= 0 ||
           desc.indexOf('TCS Dev Starter') >= 0;
  }

  // list a raw table's top-level cheat entry descriptions (for the UI),
  // skipping the dev-starter scaffolding
  function listTopEntries(src) {
    var lines = splitKeep(src);
    var out = [], depth = 0, start = -1;
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      var opens = count(ln, '<CheatEntry>');
      var closes = count(ln, '</CheatEntry>');
      if (opens && depth === 0) start = i;
      depth += opens;
      if (closes) {
        depth -= closes;
        if (depth <= 0 && start >= 0) {
          var block = lines.slice(start, i + 1).join('');
          var m = /<Description>"([^"]*)"<\/Description>/.exec(block);
          if (m && !isStarterScaffold(block, m[1])) out.push(m[1]);
          start = -1;
          depth = 0;
        }
      }
    }
    return out;
  }

  /* cfg: { game, version, table, exe, init, date(YYYY-MM-DD),
   *        stats: [[src, rel], ...], battle: [...], extra: [...] }   */
  function buildRelease(tpl, src, cfg) {
    var tableVer = cfg.table || 'v1.0';

    if (!(cfg.stats.length || cfg.battle.length || cfg.extra.length))
      throw new Error('no features assigned to any category');

    // credit header from the template's own slots
    var h = idx(tpl, '<AssemblerScript>/*=====') + '<AssemblerScript>'.length;
    var he = idx(tpl, '=================================================*/', h);
    he = idx(tpl, '\n', he) + 1;
    var header = tpl.slice(h, he);

    // init scripts
    var init = cfg.init || 'auto';
    if (init === 'auto') {
      var bodies = findAll(/<AssemblerScript[^>]*>([\s\S]*?)<\/AssemblerScript>/g, src)
        .map(function (m) { return m[1]; });
      var usesMono = bodies.some(function (b) {
        return b.indexOf('aobscanregion(') >= 0 || b.indexOf('LaunchMonoDataCollector') >= 0;
      });
      init = usesMono ? 'unity' : 'none';
    }
    if (init === 'none') {
      tpl = deleteEntry(tpl, '"=== Init Script [Delete If Not Needed] ==="');
    } else {
      tpl = deleteEntry(tpl, init === 'unity'
        ? '"--- Initialize .NET Engine Cheat Features ---'
        : '"--- Initialize Unity Engine Cheat Features ---');
      tpl = tpl.replace('"=== Init Script [Delete If Not Needed] ==="', '"=== Init Script ==="');
    }

    // header entry
    tpl = tpl.replace(/"Game v \| Cheat Engine Table v1\.0 \| [0-9-]+ The Cheat Script"/,
      '"' + cfg.game + ' ' + cfg.version + ' | Cheat Engine Table ' + tableVer +
      ' | ' + cfg.date + ' The Cheat Script"');

    // always-pruned sections (absent from a pre-cleaned template: fine)
    ['"[Niche Usage]', '"[Misc.][!]"', '[TOOLBOX/TEMPLATES'].forEach(function (n) {
      try { tpl = deleteEntry(tpl, n); }
      catch (e) { if (!e.notFound) throw e; }
    });

    var tplIds = {};
    findAll(/<ID>(\d+)<\/ID>/g, tpl).forEach(function (m) { tplIds[m[1]] = true; });

    ['stats', 'battle', 'extra'].forEach(function (cat) {
      var top = SLOTS[cat][0], plus = SLOTS[cat][1], plusDesc = SLOTS[cat][2];
      var feats = cfg[cat];
      if (feats.length > top.length + plus.length)
        throw new Error('too many ' + cat + ' features (' + (top.length + plus.length) + ' max)');
      var order = top.concat(plus);

      feats.forEach(function (feat, fi) {
        var slot = order[fi], srcName = feat[0], relName = feat[1];
        var entry = extractEntry(src, srcName);
        var body = stripDevNotes(getScriptBody(entry));
        if (body.indexOf('Cheat Script by ColonelRVH') < 0) {
          var en = body.indexOf('[ENABLE]');
          body = en >= 0 ? header + body.slice(en) : header + body;
        }
        var children = getChildrenBlock(entry);

        var key = '<Description>"' + slot + '"</Description>';
        var i = idx(tpl, key);
        tpl = tpl.slice(0, i) + '<Description>"' + relName + '"</Description>' +
              tpl.slice(i + key.length);
        var a = idx(tpl, '<AssemblerScript>', i) + '<AssemblerScript>'.length;
        var b = idx(tpl, '</AssemblerScript>', a);
        tpl = tpl.slice(0, a) + body + tpl.slice(b);

        var lines = splitKeep(tpl);
        var se = entryBounds(lines, '<Description>"' + relName + '"</Description>');
        var slotLine = lines[se[0]];
        var slotIndent = slotLine.length - slotLine.replace(/^ +/, '').length;
        function takeId() {
          var nw = 10000;
          while (tplIds[String(nw)]) nw++;
          tplIds[String(nw)] = true;
          return nw;
        }
        var block;
        if (children) {
          Object.keys((function () {
            var ids = {};
            findAll(/<ID>(\d+)<\/ID>/g, children).forEach(function (m) { ids[m[1]] = true; });
            return ids;
          })()).forEach(function (cid) {
            if (tplIds[cid]) {
              var nw = takeId();
              children = children.split('<ID>' + cid + '</ID>').join('<ID>' + nw + '</ID>');
            }
          });
          block = reindentChildren(children, slotIndent + 2);
        } else {
          // no hand-made children: derive them from registered symbols
          block = synthChildren(body, slotIndent + 2, takeId);
        }
        if (block) {
          tpl = lines.slice(0, se[1]).concat([block]).concat(lines.slice(se[1])).join('');

          var optI = idx(tpl, '<Options', idx(tpl, '<Description>"' + relName + '"</Description>'));
          var optJ = idx(tpl, '/>', optI) + 2;
          var opts = tpl.slice(optI, optJ);
          ['moActivateChildrenAsWell="1"', 'moDeactivateChildrenAsWell="1"'].forEach(function (need) {
            if (opts.indexOf(need) < 0) opts = opts.replace('/>', ' ' + need + '/>');
          });
          tpl = tpl.slice(0, optI) + opts + tpl.slice(optJ);
        }
      });

      order.slice(feats.length).forEach(function (slot) {
        if (tpl.indexOf('"' + slot + '"') >= 0) tpl = deleteEntry(tpl, '"' + slot + '"');
      });
      if (feats.length <= top.length && plusDesc) {
        try { tpl = deleteEntry(tpl, '"' + plusDesc + '"'); }
        catch (e) { if (!e.notFound) throw e; }
      }
      if (!feats.length) tpl = deleteEntry(tpl, GROUP_DESC[cat]);
    });

    if (cfg.exe)
      tpl = tpl.replace('stringlist_add(attachlist,"game.exe");',
                        'stringlist_add(attachlist,"' + cfg.exe + '");');

    if (cfg.supporters) tpl = applySupporters(tpl, cfg.supporters);

    // NOTE: a raw table's <Structures> section is deliberately not carried.

    // sanity
    if (count(tpl, '\n') !== count(tpl, '\r\n')) throw new Error('mixed line endings in output');
    if (/<Description>"TCS\./.test(tpl)) throw new Error('leftover slots in output');

    return {
      output: tpl,
      filename: cfg.game + ' ' + cfg.version + '_Table ' + tableVer + '_The Cheat Script.ct',
    };
  }

  /* ------------------------------------------------------------------ */
  /* lint                                                               */
  /* ------------------------------------------------------------------ */

  function stripComments(body) {
    return body.replace(/\{[\s\S]*?\}/g, '')
               .replace(/\/\*[\s\S]*?\*\//g, '')
               .replace(/\/\/[^\r\n]*/g, '');
  }

  function lintTable(t, opts) {
    opts = opts || {};
    var issues = [];
    function err(m) { issues.push(['ERROR', m]); }
    function warn(m) { issues.push(['WARN ', m]); }

    if (count(t, '\n') !== count(t, '\r\n'))
      err('mixed line endings (' + (count(t, '\n') - count(t, '\r\n')) + ' lone LF)');

    if (typeof DOMParser !== 'undefined') {
      var doc = new DOMParser().parseFromString(t, 'text/xml');
      if (doc.getElementsByTagName('parsererror').length) err('XML does not parse');
    }

    if (/<Description>"TCS\./.test(t)) {
      var slots = {};
      findAll(/"(TCS\.[^"]*)"/g, t).forEach(function (m) { slots[m[1]] = true; });
      err('leftover template slots: ' + Object.keys(slots).sort().join(', '));
    }
    if (t.indexOf('TOOLBOX/TEMPLATES') >= 0) err('template toolbox section still present');
    if (t.indexOf('TCS.createTableScript') >= 0 || t.indexOf('TCS Dev Starter') >= 0)
      err('TCS Dev Starter button entries still present - remove that group before release');
    if (t.indexOf('<Structures') >= 0)
      err('Structures section present - dissect data stays in the source table');
    if (t.indexOf('"[Niche Usage]') >= 0 || t.indexOf('"[Misc.][!]"') >= 0)
      warn('[Niche Usage]/[Misc.] section present - intended?');
    if (t.indexOf('stringlist_add(attachlist,"game.exe")') >= 0)
      err('auto-attach still says game.exe');
    if (t.indexOf('"Game v |') >= 0) err('header entry still has template placeholder text');

    var months = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                  'August', 'September', 'October', 'November', 'December'];
    var sm = /"-------\s+(\w+) (\d{4}) Supporters/.exec(t);
    if (sm && months.indexOf(sm[1]) >= 0) {
      var now = opts.now ? new Date(opts.now) : new Date();
      var age = (now.getFullYear() - +sm[2]) * 12 + now.getMonth() - months.indexOf(sm[1]);
      if (age > 1) warn('supporter list is ' + age + ' months old (' + sm[1] + ' ' + sm[2] + ')');
    }

    var scripts = findAll(
      /<Description>("[^"]+")<\/Description>(?:(?!<AssemblerScript|<\/CheatEntry>|<Description>)[\s\S])*?<AssemblerScript[^>]*>([\s\S]*?)<\/AssemblerScript>/g, t);

    scripts.forEach(function (sm2) {
      var name = sm2[1], body = sm2[2];
      var code = stripComments(body);

      findAll(/(aobscanmodule|aobscanregion)\(([^)]*)\)/g, code).forEach(function (am) {
        var parts = am[2].split(',').map(function (p) { return p.trim(); });
        var pattern = parts[parts.length - 1].split(/\s+/).filter(Boolean);
        var sym = parts[0];
        if (pattern.length && pattern[pattern.length - 1] === '*')
          err(name + ' ' + sym + ': trailing wildcard(s) in AOB - trim them');
        pattern.forEach(function (b, i) {
          if (b.toUpperCase() === 'E8' || b.toUpperCase() === 'E9') {
            var tail = pattern.slice(i + 1, i + 5);
            if (tail.length && tail.some(function (x) { return x !== '*'; }))
              warn(name + ' ' + sym + ': byte ' + i + ' is ' + b.toUpperCase() +
                   ' followed by unmasked bytes - if that is a call/jmp rel32, mask its displacement');
          }
        });
      });

      var hasReadmem = code.indexOf('readmem(') >= 0;
      var seen = {};
      findAll(/\[(?:r[a-z0-9]+)(?:\+r[a-z0-9]+\*\d)?\+([0-9A-Fa-f]{2,})\]/g, code)
        .forEach(function (om) { seen[om[1]] = true; });
      Object.keys(seen).forEach(function (off) {
        var v = parseInt(off, 16);
        if (v > 0x60 && !hasReadmem)
          warn(name + ': hardcoded offset 0x' + v.toString(16).toUpperCase() +
               ' in active code with no readmem - breaks silently-wrong on game updates' +
               ' if the AOB still matches');
      });

      var scanSyms = {};
      findAll(/(aobscanmodule|aobscanregion)\(([^)]*)\)/g, code).forEach(function (am) {
        scanSyms[am[2].split(',')[0].trim()] = true;
      });
      findAll(/(?<!un)registersymbol\((\w+)\)/g, code).forEach(function (rm) {
        var s = rm[1];
        if (scanSyms[s]) return;
        var pat = reEscape(s);
        var bracket = new RegExp('\\[' + pat + '(?:[+\\-]|\\])', 'i').test(t);
        var rdmem = new RegExp('readmem\\(\\s*' + pat + '\\b', 'i').test(t);
        var region = new RegExp('aobscanregion\\([^,]+,\\s*' + pat + '\\b', 'i').test(t);
        var addr = new RegExp('<Address>[^<]*\\b' + pat + '\\b[^<]*</Address>', 'i').test(t);
        var other = scripts.some(function (o) {
          return o[2] !== body && new RegExp('^\\s*' + pat + ':', 'im').test(o[2]);
        });
        if (!(bracket || rdmem || region || addr || other))
          warn(name + ': symbol ' + s + ' is registered but never used');
      });
    });

    return issues;
  }

  return {
    buildRelease: buildRelease,
    lintTable: lintTable,
    listTopEntries: listTopEntries,
    stripDevNotes: stripDevNotes,
    parseSupporters: parseSupporters,
    applySupporters: applySupporters,
    supportersHeader: supportersHeader,
    serializeManifest: serializeManifest,
    parseManifest: parseManifest,
  };
});

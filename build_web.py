# -*- coding: utf-8 -*-
"""Generate the standalone GitHub Pages page (index.html) from app.html.

app.html is the shared page source: it is published as-is as a claude.ai
Artifact (where the platform supplies the document skeleton) and wrapped by
this script into a complete HTML document for any ordinary web host.

The page picks its save path at runtime (`window.claude` present or not), so
one source serves both. Run after editing app.html:

    python build_web.py
"""
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

# Mirrors the skeleton the Artifact platform injects, so the standalone page
# renders identically. [hidden] matters: the modal sets display:grid, which
# would otherwise beat the UA's [hidden] rule and show it on load.
HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
  :root {
    color-scheme: light dark;
    padding-top: env(safe-area-inset-top, 0px);
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  body { margin: 0; font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  img { max-width: 100%; }
  [hidden] { display: none !important; }
</style>
"""


def build(app_path=None, out_path=None):
    app_path = Path(app_path or HERE / 'app.html')
    out_path = Path(out_path or HERE / 'index.html')
    src = io.open(app_path, encoding='utf-8', newline='').read()

    if re.search(r'<!doctype|<html[ >]|<body[ >]', src, re.I):
        sys.exit('app.html must be a document FRAGMENT (no doctype/html/body tags)')

    # everything the platform would hoist into <head>: title, font link, styles
    head_bits, body = [], src
    for pat in (r'<title>.*?</title>\s*',
                r'<link\b[^>]*>\s*',
                r'<style>.*?</style>\s*'):
        for m in re.findall(pat, body, re.S | re.I):
            head_bits.append(m.strip())
        body = re.sub(pat, '', body, flags=re.S | re.I)

    doc = HEAD + '\n'.join(head_bits) + '\n</head>\n<body>\n' + body.strip() + '\n</body>\n</html>\n'
    io.open(out_path, 'w', encoding='utf-8', newline='\n').write(doc)

    # sanity: the pieces the page cannot run without
    for needle in ('tcs_core.js', "fetch('template.ct')", '[hidden]', '<title>'):
        if needle not in doc:
            sys.exit('generated page is missing %r' % needle)
    print('built:', out_path, '(%d bytes)' % len(doc.encode('utf-8')))
    return str(out_path)


if __name__ == '__main__':
    build(*sys.argv[1:3])

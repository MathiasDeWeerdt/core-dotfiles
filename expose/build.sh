#!/usr/bin/env bash
# build.sh — assembles src/ into a single-file binary at dist/expose
set -uo pipefail

cd "$(dirname "$0")"

SRC=src
OUT=dist/expose

mkdir -p dist

echo "Building $OUT …"

# Step 1 — resolve the upload.html template: inline CSS and JS
resolve_html() {
  python3 - "$SRC/assets/web/upload.html" \
             "$SRC/assets/web/upload.css" \
             "$SRC/assets/web/upload.js" << 'PY'
import sys

html_path, css_path, js_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(html_path) as f: html = f.read()
with open(css_path)  as f: css  = f.read()
with open(js_path)   as f: js   = f.read()

html = html.replace('<style>@@CSS@@</style>', '<style>' + css + '</style>')
html = html.replace('<script>@@JS@@</script>', '<script>' + js  + '</script>')
print(html, end='')
PY
}

# Step 2 — resolve a serve.sh @@INJECT:path@@ line with the file's content
# We build an injected version of serve.sh into a tempfile before concatenating
resolve_serve() {
  python3 - "$SRC/lib/serve.sh" "$SRC" << 'PY'
import sys, re

serve_path = sys.argv[1]
src_root   = sys.argv[2]

with open(serve_path) as f:
    content = f.read()

def load_asset(rel_path):
    with open(src_root + '/' + rel_path) as f:
        return f.read().rstrip('\n')

# Resolve @@INJECT:assets/web/upload.html@@ — this one needs CSS+JS first
import subprocess, os
html_resolved = subprocess.check_output(
    ['python3', '-c', '''
import sys
html_path, css_path, js_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(html_path) as f: html = f.read()
with open(css_path)  as f: css  = f.read()
with open(js_path)   as f: js   = f.read()
html = html.replace("<style>@@CSS@@</style>", "<style>" + css + "</style>")
html = html.replace("<script>@@JS@@</script>", "<script>" + js  + "</script>")
print(html, end="")
''',
    src_root + '/assets/web/upload.html',
    src_root + '/assets/web/upload.css',
    src_root + '/assets/web/upload.js',
    ],
    text=True
)

def inject(match):
    marker = match.group(1)
    if marker == 'assets/web/upload.html':
        return html_resolved.rstrip('\n')
    return load_asset(marker)

# Replace each @@INJECT:path@@ with corresponding file content
content = re.sub(r'@@INJECT:([^@]+)@@', inject, content)
print(content, end='')
PY
}

# ── Assembly ──────────────────────────────────────────────────────────────────
{
  printf '#!/usr/bin/env bash\nset -uo pipefail\n\n'

  for f in \
    "$SRC/globals.sh" \
    "$SRC/lib/colors.sh" \
    "$SRC/lib/helpers.sh" \
    "$SRC/lib/usage.sh" \
    "$SRC/lib/args.sh" \
    "$SRC/lib/validate.sh" \
    "$SRC/lib/banner.sh"
  do
    printf '\n'
    cat "$f"
  done

  printf '\n'
  resolve_serve

} > "$OUT"

chmod +x "$OUT"

SIZE=$(wc -c < "$OUT")
echo "  OK  $OUT  (${SIZE} bytes)"

import datetime
import email.parser
import email.policy
import fcntl
import hmac
import html
import http.server
import json
import mimetypes
import os
import re
import runpy
import secrets
import signal
import socket
import socketserver
import stat
import sys
import threading
import time
import urllib.parse
from http import cookies

port = int(os.environ["EXPOSE_PORT"])
bind_addr = os.environ.get("EXPOSE_BIND", "0.0.0.0")
verbose = os.environ.get("EXPOSE_VERBOSE", "0") == "1"
mode = os.environ.get("EXPOSE_MODE", "text")
health_token = os.environ.get("EXPOSE_HEALTH_TOKEN", "")
upload_dir = os.environ.get("EXPOSE_UPLOAD_DIR", "/tmp/expose-uploads")
upload_html_path = os.environ.get("EXPOSE_UPLOAD_HTML", "")
me_html_path = os.environ.get("EXPOSE_ME_HTML", "")
logo_svg_path = os.environ.get("EXPOSE_LOGO_SVG", "")
log_file = os.environ.get("EXPOSE_LOGFILE", "")
chat_file = os.environ.get("EXPOSE_CHAT_FILE", "")
content_path = os.environ.get("EXPOSE_CONTENT", "")
content_mime = os.environ.get("EXPOSE_MIME", "application/octet-stream")
content_name = os.environ.get("EXPOSE_FILENAME", "")
response_code = int(os.environ.get("EXPOSE_RESP_CODE", "200"))
redirect_url = os.environ.get("EXPOSE_REDIRECT", "")
delay_seconds = int(os.environ.get("EXPOSE_DELAY_MS", "0")) / 1000
body_log_limit = 4096
catch_requests = os.environ.get("EXPOSE_CATCH", "0") == "1"
collect_file = os.environ.get("EXPOSE_COLLECT_FILE", "")
custom_headers = []
for header in os.environ.get("EXPOSE_RESP_HEADERS", "").splitlines():
    name, separator, value = header.partition(":")
    if separator:
        custom_headers.append((name.strip(), value.strip()))
try:
    with open(os.environ.get("EXPOSE_FP_JS", ""), "r") as _f:
        fp_js = _f.read()
except Exception:
    fp_js = ""
try:
    with open(logo_svg_path) as logo_file:
        logo_svg = logo_file.read()
except OSError:
    logo_svg = ""

# ── Authentication ───────────────────────────────────────────────────────────
auth_password = os.environ.get('EXPOSE_AUTH_PASSWORD', '')
auth_sessions = {}
auth_failures = {}
auth_lock = threading.Lock()
AUTH_COOKIE = 'expose_session'
AUTH_TTL = 12 * 3600
AUTH_WINDOW = 300
AUTH_ATTEMPTS = 10
LOGIN_HEADERS = (
    ('Content-Security-Policy',
     "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'"),
)

def login_page(error='', next_path='/'):
    message = html.escape(error)
    target = html.escape(next_path)
    brand = logo_svg or '<span>expose</span>'
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Locked · expose</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#141414;color:#ededed;font:15px/1.6 system-ui,-apple-system,'Segoe UI',sans-serif}}
.card{{width:min(92vw,380px);background:#1d1d1d;border:1px solid #343434;border-radius:10px;padding:32px;box-shadow:0 20px 60px rgba(0,0,0,.35)}}
.brand{{display:flex;align-items:center;gap:10px;font-weight:650;font-size:20px;letter-spacing:-.5px;margin-bottom:6px}}.brand svg{{width:30px;height:26px;color:#ededed}}
p.sub{{color:#a3a3a3;font-size:13px;margin:0 0 24px}}label{{display:block;font-size:12px;font-weight:600;color:#bdbdbd;margin-bottom:8px}}
input{{width:100%;padding:11px 12px;border-radius:6px;border:1px solid #777;background:#161616;color:#ededed;font:inherit;outline:none}}
input:focus{{border-color:#94baff;box-shadow:0 0 0 3px rgba(148,186,255,.18)}}button{{width:100%;margin-top:16px;padding:11px 14px;border:0;border-radius:6px;background:#2563eb;color:#fff;font:inherit;font-weight:650;cursor:pointer}}
button:hover{{filter:brightness(.95)}}.err{{min-height:20px;margin:12px 0 0;color:#ff9b96;font-size:12px}}.foot{{margin:20px 0 0;color:#777;font-size:11px;text-align:center}}
@media(prefers-color-scheme:light){{body{{background:#fafbf8;color:#202b23}}.card{{background:#fff;border-color:#dce3d8;box-shadow:0 20px 60px rgba(0,0,0,.08)}}.brand svg{{color:#202b23}}p.sub,label{{color:#526254}}input{{background:#fafbf8;color:#202b23;border-color:#a4b1a4}}button{{background:#356847}}.err{{color:#a63832}}.foot{{color:#627164}}}}
</style></head><body><main class="card">
<div class="brand">{brand}<span>expose</span></div>
<p class="sub">This session is password protected.</p>
<form method="post" action="/login">
<input type="hidden" name="next" value="{target}">
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
<button type="submit">Unlock</button>
<p class="err" role="status" aria-live="polite">{message}</p>
</form><p class="foot">Authorised use only.</p>
</main></body></html>'''

def prune_auth():
    now = time.time()
    with auth_lock:
        for token, expires in list(auth_sessions.items()):
            if expires < now:
                auth_sessions.pop(token, None)
        for address, attempts in list(auth_failures.items()):
            recent = [stamp for stamp in attempts if now - stamp < AUTH_WINDOW]
            if recent:
                auth_failures[address] = recent
            else:
                auth_failures.pop(address, None)

# ── Operator output ──────────────────────────────────────────────────────────
hit_lock = threading.Lock()
hit_seen = {}
HIT_WINDOW = 60
INTERNAL_PATHS = {'/log', '/log/clear', '/chat', '/upload/files', '/meta',
                  '/favicon.ico', '/.expose-health', '/login', '/logout',
                  '/lin', '/mac', '/win'}

def internal_path(path):
    return path in INTERNAL_PATHS or path.startswith('/console/')

def redact_path(path):
    parsed = urllib.parse.urlsplit(path)
    if not parsed.query:
        return path
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == 'ticket' for key, _ in pairs):
        return path
    pairs = [(key, '***' if key == 'ticket' else value) for key, value in pairs]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                                    urllib.parse.urlencode(pairs), parsed.fragment))

def event(kind, message, ip=''):
    sys.stderr.write(f"{datetime.datetime.now().strftime('%H:%M:%S')}  "
                     f"{ip:<15}  {kind:<9} {message}\n")
    sys.stderr.flush()

def unique_hit(ip, method, path, code):
    key = (ip, method, path, code)
    now = time.time()
    with hit_lock:
        for seen_key, seen_at in list(hit_seen.items()):
            if now - seen_at > HIT_WINDOW:
                hit_seen.pop(seen_key, None)
        if key in hit_seen:
            return False
        hit_seen[key] = now
        return True

os.makedirs(upload_dir, exist_ok=True)
req_counter = 0
counter_lock = threading.Lock()
_httpd = None
console_enabled = os.environ.get('EXPOSE_CONSOLES') == '1'
ConsoleService = runpy.run_path(os.environ['EXPOSE_CONSOLE_MODULE'])['ConsoleService']
consoles = ConsoleService(console_enabled, os.environ.get('EXPOSE_CLIENT_DIR', ''))
try:
    with open(os.environ.get('EXPOSE_WINENUM', '')) as winenum_file:
        consoles.winenum_script = winenum_file.read()
except OSError:
    consoles.winenum_script = ''
proxy_bind = os.environ.get('EXPOSE_PROXY', '').strip()
if proxy_bind and console_enabled:
    try:
        consoles.start_proxy(proxy_bind)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"\n  Proxy     could not listen on {proxy_bind}: {error}\n")
        sys.stderr.flush()
for item in os.environ.get('EXPOSE_CALLBACKS', '').split(','):
    if not item.strip():
        continue
    local, _, remote = item.strip().partition(':')
    try:
        consoles.add_callback(int(local), int(remote or local))
    except (TypeError, ValueError) as error:
        sys.stderr.write(f"\n  Callback  invalid {item}: {error}\n")
        sys.stderr.flush()

def rdns(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return None

def parse_ua(ua):
    browser = os_name = "-"
    for pat, name in [(r'Firefox/([\d.]+)', 'Firefox'), (r'Edg/([\d.]+)', 'Edge'),
                       (r'Chrome/([\d.]+)', 'Chrome'), (r'Version/([\d.]+).*Safari', 'Safari'),
                       (r'curl/([\d.]+)', 'curl'), (r'Wget', 'Wget')]:
        m = re.search(pat, ua)
        if m:
            browser = f"{name} {m.group(1)}" if m.lastindex else name
            break
    if re.search(r'[Bb]ot|[Cc]rawl|[Ss]pider', ua):
        browser = f"Bot ({ua[:60]})"
    for pat, n in [('Linux', 'Linux'), ('Mac OS', 'macOS'), ('Windows', 'Windows'),
                    ('Android', 'Android'), ('iPhone|iPad', 'iOS')]:
        if re.search(pat, ua): os_name = n; break
    for pat, arch in [('x86_64|x64|amd64', 'x86_64'), ('aarch64|arm64', 'arm64'), ('armv[67]', 'arm')]:
        if re.search(pat, ua): os_name += f" {arch}"; break
    return browser, os_name

def parse_multipart(body, content_type, fields=None):
    saved = []
    message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not message.is_multipart():
        return saved
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if not filename:
            if fields is not None and part.get_param('name', header='content-disposition') == 'message':
                fields['message'] = (part.get_payload(decode=True) or b'').decode('utf-8', errors='replace')[:16000]
            continue
        name = os.path.basename(filename).replace("..", "").lstrip(".")
        if not name:
            continue
        path = os.path.join(upload_dir, name)
        base, ext = os.path.splitext(name)
        suffix = 1
        while os.path.exists(path):
            path = os.path.join(upload_dir, f"{base}_{suffix}{ext}")
            suffix += 1
        with open(path, "wb") as uploaded:
            uploaded.write(part.get_payload(decode=True) or b"")
        saved.append(os.path.basename(path))
    return saved

def list_files():
    fs = []
    if os.path.isdir(upload_dir):
        for n in sorted(os.listdir(upload_dir)):
            p = os.path.join(upload_dir, n)
            if os.path.isfile(p):
                s = os.stat(p)
                fs.append({"name": n, "size": s.st_size, "mtime": int(s.st_mtime)})
    return fs

def _write_log(entry):
    if not log_file: return
    try:
        with open(log_file, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try: log = json.load(f)
            except: log = []
            entry["n"] = max((item.get("n", 0) for item in log), default=0) + 1
            log.append(entry)
            if len(log) > 500: log = log[-500:]
            f.seek(0); f.truncate(); json.dump(log, f)
            fcntl.flock(f, fcntl.LOCK_UN)
    except: pass

def _write_collect(entry):
    if not collect_file:
        return
    try:
        with open(collect_file, "a") as collected:
            fcntl.flock(collected, fcntl.LOCK_EX)
            collected.write(json.dumps(entry) + "\n")
            fcntl.flock(collected, fcntl.LOCK_UN)
    except OSError:
        pass

def _read_chat():
    """Thread-safe read of the chat JSON file."""
    if not chat_file: return []
    try:
        with open(chat_file, 'r') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            msgs = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            return msgs
    except: return []

def attachment_info(name):
    if not isinstance(name, str) or name != os.path.basename(name):
        raise ValueError('Invalid filename')
    path = os.path.join(upload_dir, name)
    if not os.path.isfile(path) or os.path.islink(path):
        raise ValueError('File not found')
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    kind = ('image' if mime in ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif')
            else 'audio' if mime in ('audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/x-wav')
            else 'video' if mime in ('video/mp4', 'video/webm', 'video/ogg')
            else 'text' if mime.startswith('text/') or mime in ('application/json', 'application/xml')
            else 'file')
    return {'name': name, 'size': os.path.getsize(path), 'mime': mime, 'kind': kind}

def _append_chat(msg, attachments=None):
    """Thread-safe append of a message to the chat JSON file."""
    if not chat_file or not (msg or attachments): return False
    try:
        os.makedirs(os.path.dirname(chat_file) or '.', exist_ok=True)
        with open(chat_file, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try: msgs = json.load(f)
            except: msgs = []
            number = max((item.get('n', 0) for item in msgs), default=0) + 1
            msgs.append({'time': time.strftime('%H:%M:%S'), 'msg': msg, 'n': number,
                         'files': attachments or []})
            if len(msgs) > 200: msgs = msgs[-200:]
            f.seek(0); f.truncate(); json.dump(msgs, f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return True
    except: return False

class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Server", "expose")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        protected = urllib.parse.urlsplit(self.path).path.startswith('/console/') or urllib.parse.urlsplit(self.path).path in ('/lin', '/mac', '/win')
        for name, value in ([] if protected else custom_headers):
            self.send_header(name, value)
        super().end_headers()

    def _send(self, status, body=b"", content_type="application/json", headers=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def _cookie_token(self):
        for part in self.headers.get('Cookie', '').split(';'):
            name, separator, value = part.strip().partition('=')
            if separator and name == AUTH_COOKIE:
                return value
        return ''

    def real_ip(self):
        peer = self.client_address[0]
        if peer in ('127.0.0.1', '::1'):
            real = self.headers.get('X-Real-IP', '').strip()
            if real:
                return real
            forwarded = self.headers.get('X-Forwarded-For', '')
            if forwarded.strip():
                return forwarded.split(',')[-1].strip()
        return peer

    def _session_valid(self):
        token = self._cookie_token()
        if not token:
            return False
        with auth_lock:
            expires = auth_sessions.get(token)
            if not expires or expires < time.time():
                auth_sessions.pop(token, None)
                return False
            return True

    def _new_session(self):
        token = secrets.token_urlsafe(32)
        now = time.time()
        with auth_lock:
            for key, expires in list(auth_sessions.items()):
                if expires < now:
                    auth_sessions.pop(key, None)
            if len(auth_sessions) >= 64:
                auth_sessions.pop(next(iter(auth_sessions)), None)
            auth_sessions[token] = now + AUTH_TTL
        forwarded = self.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
        secure = '; Secure' if forwarded == 'https' else ''
        return f'{AUTH_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={AUTH_TTL}{secure}'

    def _authorized(self):
        if not auth_password:
            return True
        path = urllib.parse.urlsplit(self.path).path
        if (path in ('/login', '/logout') or path == '/.expose-health'
                or path in ('/lin', '/mac', '/win')
                or path.startswith('/console/client/')
                or path == '/console/register'
                or path.startswith('/console/agent/')
                or path == '/console/winenum.ps1'
                or self.command == 'OPTIONS'):
            return True
        if self._session_valid():
            return True
        if self.command == 'GET' and 'text/html' in self.headers.get('Accept', ''):
            self._send(401, login_page('', path), 'text/html; charset=utf-8', LOGIN_HEADERS)
        else:
            self._send(401, json.dumps({'error': 'Password required'}),
                       'application/json', LOGIN_HEADERS)
        return False

    def _redirect(self, target):
        self._send(303, b'', 'text/plain', (('Location', target), ('Cache-Control', 'no-store')))

    def _handle_login(self):
        if not auth_password:
            self._redirect('/')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = -1
        if not 0 <= length <= 8192:
            self._send(413, login_page('Request too large.'), 'text/html; charset=utf-8',
                       LOGIN_HEADERS)
            return
        body = self.rfile.read(length)
        form = urllib.parse.parse_qs(body.decode('utf-8', 'replace'))
        password = (form.get('password') or [''])[0]
        next_path = (form.get('next') or ['/'])[0]
        if (not next_path.startswith('/') or next_path.startswith('//')
                or '\\' in next_path or '\r' in next_path or '\n' in next_path
                or len(next_path) > 2048):
            next_path = '/'
        address = self.real_ip()
        prune_auth()
        with auth_lock:
            blocked = len(auth_failures.get(address, [])) >= AUTH_ATTEMPTS
        if hmac.compare_digest(password.encode(), auth_password.encode()):
            with auth_lock:
                auth_failures.pop(address, None)
            event('LOGIN', 'ok', address)
            self._send(303, b'', 'text/plain', (('Location', next_path),
                                               ('Set-Cookie', self._new_session()),
                                               ('Cache-Control', 'no-store')))
            return
        with auth_lock:
            auth_failures.setdefault(address, []).append(time.time())
        time.sleep(1.0 if blocked else 0.2)
        if blocked:
            event('LOGIN', 'blocked', address)
            self._send(429, login_page('Too many attempts. Wait a minute.', next_path),
                       'text/html; charset=utf-8', LOGIN_HEADERS)
        else:
            event('LOGIN', 'failed', address)
            self._send(401, login_page('Incorrect password.', next_path),
                       'text/html; charset=utf-8', LOGIN_HEADERS)

    def _handle_logout(self):
        token = self._cookie_token()
        if token:
            with auth_lock:
                auth_sessions.pop(token, None)
        event('LOGIN', 'logout', self.real_ip())
        self._send(303, b'', 'text/plain', (
            ('Location', '/login'), ('Cache-Control', 'no-store'),
            ('Set-Cookie', f'{AUTH_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')))

    def do_GET(self):
        if not self._authorized():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == '/login':
            if not auth_password or self._session_valid():
                self._redirect('/')
            else:
                self._send(401, login_page(), 'text/html; charset=utf-8', LOGIN_HEADERS)
            return
        if consoles.handle(self):
            return
        if self.path.split('?', 1)[0] == '/.expose-health':
            query = urllib.parse.parse_qs(self.path.split('?', 1)[1] if '?' in self.path else '')
            supplied = query.get('session', [''])[0]
            if health_token and hmac.compare_digest(supplied, health_token):
                self._send(200, health_token, "text/plain", (("Cache-Control", "no-store"),))
            else:
                self._send(404, b"", "text/plain", (("Cache-Control", "no-store"),))
            return
        if redirect_url:
            self._send(302, b"", "text/plain", (("Location", redirect_url),))
            return
        parsed = self.path.split('?', 1)
        ppath = parsed[0]
        if ppath == '/log':
            from urllib.parse import parse_qs
            qs = parse_qs(parsed[1] if len(parsed) > 1 else '')
            since = int(qs.get('since', [0])[0])
            try:
                with open(log_file, 'r') as f: entries = json.load(f)
            except: entries = []
            if since: entries = [e for e in entries if e.get('n', 0) > since]
            result = json.dumps(entries).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif ppath in ('/', '/upload'):
            try:
                with open(upload_html_path, "rb") as f: body = f.read()
            except Exception: body = b"page not found"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/meta':
            metadata = {"mode": mode}
            if mode == "dir":
                metadata["path"] = os.getcwd()
            elif mode == "file":
                metadata.update(name=content_name, size=os.path.getsize(content_path),
                                mime=content_mime)
            elif mode in ("text", "payload"):
                metadata["size"] = os.path.getsize(content_path)
            result = json.dumps(metadata).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == '/ls' or self.path.startswith('/ls/'):
            raw = urllib.parse.unquote(self.path[3:]) or '/'
            base = os.path.realpath(os.getcwd())
            rel = raw.lstrip('/')
            full = os.path.realpath(os.path.join(base, rel))
            if os.path.commonpath((base, full)) != base:
                self.send_error(403); return
            if not os.path.isdir(full):
                self.send_error(404); return
            entries = []
            for name in sorted(os.listdir(full)):
                p = os.path.join(full, name)
                try:
                    s = os.stat(p)
                    if stat.S_ISDIR(s.st_mode):
                        entries.append({"name": name, "type": "dir", "mtime": int(s.st_mtime)})
                    elif stat.S_ISREG(s.st_mode):
                        entries.append({"name": name, "type": "file", "size": s.st_size, "mtime": int(s.st_mtime)})
                except: pass
            parent = None
            if raw != '/':
                parent = os.path.dirname(raw.rstrip('/'))
                if not parent: parent = '/'
            result = json.dumps({"path": raw, "parent": parent, "entries": entries}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == "/upload/files":
            result = json.dumps(list_files()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path.startswith(("/upload/files/", "/upload/preview/")):
            preview = self.path.startswith('/upload/preview/')
            prefix = '/upload/preview/' if preview else '/upload/files/'
            name = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path[len(prefix):])
            name = os.path.basename(name)
            fp = os.path.join(upload_dir, name)
            if os.path.isfile(fp) and not os.path.islink(fp):
                info = attachment_info(name)
                mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                sz = os.path.getsize(fp)
                if preview:
                    if info['kind'] == 'file':
                        self.send_error(415, 'Preview not available'); return
                    if info['kind'] == 'text':
                        with open(fp, 'rb') as f:
                            data = f.read(65536).decode('utf-8', errors='replace')
                        self._send(200, data, 'text/plain; charset=utf-8', (
                            ('X-Content-Type-Options', 'nosniff'),
                            ('Content-Security-Policy', "sandbox; default-src 'none'")))
                        return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(sz))
                self.send_header('X-Content-Type-Options', 'nosniff')
                encoded_name = urllib.parse.quote(name, safe="")
                disposition = 'inline' if preview else 'attachment'
                self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{encoded_name}")
                self.end_headers()
                with open(fp, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        self.wfile.write(chunk)
            else:
                self.send_error(404)
        elif self.path == '/me':
            accept = self.headers.get("Accept", "")
            ip, port = self.client_address
            fields = [
                ("IP", f"{ip}:{port}"),
                ("Method", f"{self.command} {self.request_version}"),
                ("Host", self.headers.get("Host", "-")),
                ("User-Agent", self.headers.get("User-Agent", "-")),
                ("Accept", self.headers.get("Accept", "-")),
                ("Accept-Language", self.headers.get("Accept-Language", "-")),
                ("Accept-Encoding", self.headers.get("Accept-Encoding", "-")),
                ("Referer", self.headers.get("Referer", "-")),
                ("Origin", self.headers.get("Origin", "-")),
                ("Cookie", self.headers.get("Cookie", "-")),
                ("DNT", self.headers.get("DNT", "-")),
                ("X-Forwarded-For", self.headers.get("X-Forwarded-For", "-")),
                ("Connection", self.headers.get("Connection", "-")),
                ("Authorization", self.headers.get("Authorization", "-")),
            ]
            if "application/json" in accept or "json" in accept:
                d = {k.lower().replace("-","_"): v for k,v in fields if v and v != "-"}
                result = json.dumps(d, indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)
            else:
                rows = "".join(
                    f"<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>"
                    for k, v in fields if v and v != "-")
                try:
                    with open(me_html_path) as template_file:
                        template = template_file.read()
                except OSError:
                    template = "<html><body><table>{{ROWS}}</table><script>{{FPJS}}</script></body></html>"
                body = (template.replace("{{ROWS}}", rows)
                        .replace("{{FPJS}}", fp_js)
                        .replace("{{LOGO}}", logo_svg)
                        .encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        elif self.path == '/chat':
            result = json.dumps(_read_chat()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == "/content" and mode != "dir":
            if delay_seconds:
                time.sleep(delay_seconds)
            if not content_path or not os.path.isfile(content_path):
                self.send_error(404)
                return
            size = os.path.getsize(content_path)
            self.send_response(response_code)
            self.send_header("Content-Type", content_mime)
            self.send_header("Content-Length", str(size))
            if content_name:
                encoded_name = urllib.parse.quote(content_name, safe="")
                self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{encoded_name}")
            self.end_headers()
            with open(content_path, "rb") as content:
                while chunk := content.read(65536):
                    self.wfile.write(chunk)
        elif mode == "dir":
            super().do_GET()
        else:
            self.send_error(404)

    def list_directory(self, path):
        base = os.path.realpath(os.getcwd())
        full = os.path.realpath(path)
        rel = '/' + os.path.relpath(full, base) if full != base else '/'
        self.send_response(302)
        self.send_header("Location", "/#" + rel)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return None

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/login':
            self._handle_login()
            return
        if path == '/logout':
            self._handle_logout()
            return
        ticket_upload = False
        if path == '/upload':
            ticket = urllib.parse.parse_qs(
                urllib.parse.urlsplit(self.path).query).get('ticket', [''])[0]
            ticket_upload = bool(ticket and consoles.valid_transfer_ticket(ticket))
        if not ticket_upload and not self._authorized():
            return
        if consoles.handle(self):
            return
        if self.path == '/chat/upload':
            try:
                size = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                size = -1
            if not 0 < size <= 50 * 1024 * 1024:
                self.close_connection = True
                self._send(413, '{"error":"Chat uploads are limited to 50 MB per message"}')
                return
        body = self._read_body()
        self.request_body = body[:body_log_limit]
        if catch_requests and body:
            shown = body[:body_log_limit]
            sys.stderr.write(f"\n  body ({len(body)} bytes)\n")
            sys.stderr.flush()
            sys.stderr.buffer.write(shown + b"\n")
            sys.stderr.buffer.flush()
        if path == '/log/clear':
            try:
                with open(log_file, 'w') as f: json.dump([], f)
            except: pass
            result = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif path == "/upload":
            ct = self.headers.get("Content-Type", "")
            saved = parse_multipart(body, ct)
            result = json.dumps({"saved": saved, "count": len(saved)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif path == '/chat/upload':
            fields = {}
            saved = parse_multipart(body, self.headers.get('Content-Type', ''), fields)
            attachments = [attachment_info(name) for name in saved]
            if _append_chat(fields.get('message', '').strip(), attachments):
                self._send(200, json.dumps({'ok': True, 'files': attachments}))
            else:
                self._send(400, '{"error":"No message or attachments received"}')
        elif path == '/chat':
            if body:
                message = body.decode('utf-8', errors='replace').strip()
                if _append_chat(message):
                    result = json.dumps({"ok": True}).encode()
                else:
                    result = json.dumps({"ok": False, "error": "server"}).encode()
            else:
                result = json.dumps({"ok": False, "error": "empty"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        else:
            self._send(response_code, b"", "text/plain")

    def do_OPTIONS(self):
        if self._authorized():
            self._send(204, b"", "text/plain")

    def do_HEAD(self):
        if not self._authorized():
            return
        super().do_HEAD()

    def do_DELETE(self):
        if not self._authorized():
            return
        if self.path.startswith("/upload/files/"):
            import urllib.parse
            name = urllib.parse.unquote(self.path[len("/upload/files/"):])
            name = os.path.basename(name)
            fp = os.path.join(upload_dir, name)
            if os.path.isfile(fp):
                os.remove(fp)
                result = json.dumps({"ok": True}).encode()
                self.send_response(200)
            else:
                result = json.dumps({"error": "not found"}).encode()
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        else:
            self.send_error(405)

    def log_message(self, fmt, *args):
        path = urllib.parse.urlsplit(self.path).path
        if internal_path(path):
            return
        global req_counter
        with counter_lock:
            req_counter += 1
            request_number = req_counter
        ua = self.headers.get("User-Agent", "-") if self.headers else "-"
        code = str(args[1]) if len(args) > 1 else "-"
        now = datetime.datetime.now().strftime("%H:%M:%S")
        client_ip = self.real_ip()
        client_port = self.client_address[1]
        display_path = redact_path(self.path or '')
        show = unique_hit(client_ip, self.command or "-", path, code)

        if show:
            if verbose:
                host_name = rdns(client_ip)
                browser, os_name = parse_ua(ua)
                W = "\033[0m"; DM = "\033[2m"; BD = "\033[1m"; BL = "\033[34m"
                CY = "\033[36m"; YW = "\033[1;33m"; UL = "\033[4m"
                cc = "\033[32m" if code.startswith("2") else "\033[33m" if code.startswith("3") else "\033[31m"
                SEP = f"  {DM}│{W}"
                lines = []
                lines.append(f"\n  {DM}┌─ #{request_number} ─────────────────────────────────────────────{W}")
                lines.append(f"{SEP} {DM}{now}{W}  {BD}{self.command or '-'} {CY}{display_path}{W}  {cc}{code}{W}  {DM}{self.request_version}{W}")
                client_str = f"{client_ip}:{client_port}"
                if client_ip != self.client_address[0]:
                    client_str += f"  {DM}(via {self.client_address[0]}){W}"
                if host_name: client_str += f"  {DM}({host_name}){W}"
                lines.append(f"{SEP} {BL}Client{W}    {client_str}")
                xff = self.headers.get("X-Forwarded-For")
                if xff: lines.append(f"{SEP} {BL}Proxy{W}     {xff}")
                lines.append(f"{SEP} {BL}Browser{W}   {browser}  {DM}({os_name}){W}")
                for label, key in [("Host", "Host"), ("Language", "Accept-Language"),
                                   ("Accept", "Accept"), ("Encoding", "Accept-Encoding")]:
                    value = self.headers.get(key)
                    if value: lines.append(f"{SEP} {BL}{label:<9}{W} {value}")
                ref = self.headers.get("Referer")
                if ref: lines.append(f"{SEP} {BL}Referer{W}   {UL}{ref}{W}")
                origin = self.headers.get("Origin")
                if origin: lines.append(f"{SEP} {BL}Origin{W}    {origin}")
                cookie = self.headers.get("Cookie")
                if cookie: lines.append(f"{SEP} {BL}Cookies{W}   {cookie}")
                conn = self.headers.get("Connection")
                if conn: lines.append(f"{SEP} {BL}Conn{W}      {conn}")
                if self.headers.get("DNT") == "1":
                    lines.append(f"{SEP} {BL}DNT{W}       \033[33myes{W}")
                ct = self.headers.get("Content-Type")
                cl = self.headers.get("Content-Length", "-")
                if ct: lines.append(f"{SEP} {BL}Body{W}      {ct} ({cl} bytes)")
                extras = []
                for k in self.headers:
                    kl = k.lower()
                    if kl.startswith("sec-") or kl in ("cache-control", "pragma", "authorization",
                        "if-modified-since", "if-none-match", "upgrade-insecure-requests"):
                        extras.append(f"  {k}: {self.headers[k]}")
                if extras:
                    lines.append(f"{SEP} {DM}──────{W}")
                    for extra in extras:
                        lines.append(f"{SEP} {DM}{extra}{W}")
                lines.append(f"  {DM}└───────────────────────────────────────────────────{W}")
                sys.stderr.write("\n".join(lines) + "\n")
            else:
                browser, os_name = parse_ua(ua)
                label = " ".join(part for part in (browser, os_name) if part and part != "-")
                event("HTTP", f"{self.command or '-'} {display_path or '-'} {code}"
                              + (f" · {label}" if label else ""), client_ip)
            sys.stderr.flush()

        # Write to JSON log
        _skip = {'/log', '/log/clear', '/meta', '/upload/files', '/chat', '/login', '/logout'}
        _path_clean = (self.path or '').split('?')[0]
        if _path_clean not in _skip:
            entry = {"n": request_number, "ts": time.time(), "time": now,
                     "method": self.command or "-", "path": display_path or "-",
                     "httpver": self.request_version or "-",
                     "ip": client_ip, "peer": self.client_address[0],
                     "port": client_port, "code": code, "ua": ua}
            if self.headers:
                for k in ("Host", "Accept", "Accept-Language", "Accept-Encoding",
                           "Referer", "Cookie", "Origin", "Connection",
                           "Content-Type", "Content-Length", "X-Forwarded-For",
                           "Authorization", "DNT"):
                    value = self.headers.get(k)
                    if value: entry[k.lower().replace("-","_")] = value
            request_body = getattr(self, "request_body", b"")
            if request_body:
                entry["body"] = request_body.decode("utf-8", errors="replace")
            _write_log(entry)
            _write_collect(entry)

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

with Server((bind_addr, port), Handler) as httpd:
    _httpd = httpd

    def stop_server(_signum, _frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)

    httpd.serve_forever()

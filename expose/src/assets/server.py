import base64
import datetime
import email.parser
import email.policy
import fcntl
import html
import hmac
import http.server
import ipaddress
import json
import mimetypes
import os
import re
import signal
import socket
import socketserver
import sqlite3
import ssl
import stat
import sys
import threading
import time
import urllib.parse

port = int(os.environ["EXPOSE_PORT"])
bind_addr = os.environ.get("EXPOSE_BIND", "0.0.0.0")
verbose = os.environ.get("EXPOSE_VERBOSE", "0") == "1"
mode = os.environ.get("EXPOSE_MODE", "text")
upload_dir = os.environ.get("EXPOSE_UPLOAD_DIR", "/tmp/expose-uploads")
upload_html_path = os.environ.get("EXPOSE_UPLOAD_HTML", "")
me_html_path = os.environ.get("EXPOSE_ME_HTML", "")
logo_svg_path = os.environ.get("EXPOSE_LOGO_SVG", "")
auth_required = os.environ.get("EXPOSE_AUTH", "")
log_file = os.environ.get("EXPOSE_LOGFILE", "")
chat_file = os.environ.get("EXPOSE_CHAT_FILE", "")
allow_nets = [n.strip() for n in os.environ.get("EXPOSE_ALLOW", "").split(",") if n.strip()]
content_path = os.environ.get("EXPOSE_CONTENT", "")
content_mime = os.environ.get("EXPOSE_MIME", "application/octet-stream")
content_name = os.environ.get("EXPOSE_FILENAME", "")
response_code = int(os.environ.get("EXPOSE_RESP_CODE", "200"))
redirect_url = os.environ.get("EXPOSE_REDIRECT", "")
delay_seconds = int(os.environ.get("EXPOSE_DELAY_MS", "0")) / 1000
body_limit = int(os.environ.get("EXPOSE_BODY_LIMIT", "4096"))
catch_requests = os.environ.get("EXPOSE_CATCH", "0") == "1"
serve_once = os.environ.get("EXPOSE_ONCE", "0") == "1"
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
os.makedirs(upload_dir, exist_ok=True)
req_counter = 0
counter_lock = threading.Lock()
_httpd = None

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

def parse_multipart(body, content_type):
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

def _write_db(entry):
    """Append the request to the persistent SQLite log (~/.expose/requests.db)."""
    db = os.environ.get("EXPOSE_DB", "")
    if not db: return
    try:
        con = sqlite3.connect(db, timeout=5)
        con.execute("insert into requests(ts,time,method,path,ip,port,ua,host,content_type,content_len,mode) values(?,?,?,?,?,?,?,?,?,?,?)",
                    (entry.get("ts"), entry.get("time"), entry.get("method"), entry.get("path"),
                     entry.get("ip"), str(entry.get("port", "")), entry.get("ua"), entry.get("host", ""),
                     entry.get("content_type", ""), entry.get("content_length", ""),
                     os.environ.get("EXPOSE_MODE", "")))
        con.commit(); con.close()
    except Exception: pass

def _write_fp(raw, ip, port, ua_hdr):
    """Append a device fingerprint report to the SQLite fingerprints table."""
    db = os.environ.get("EXPOSE_DB", "")
    if not db or not raw: return
    ua = vid = page = ""
    try:
        d = json.loads(raw)
        ua = d.get("user_agent", ""); vid = d.get("visitor_id", ""); page = d.get("page", "")
    except Exception: pass
    try:
        con = sqlite3.connect(db, timeout=5)
        con.execute("insert into fingerprints(ts,time,ip,port,ua,page,visitor_id,data) values(?,?,?,?,?,?,?,?)",
                    (time.time(), time.strftime('%H:%M:%S'), ip, port,
                     ua or ua_hdr, page, vid, raw))
        con.commit(); con.close()
    except Exception: pass

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

def _append_chat(msg):
    """Thread-safe append of a message to the chat JSON file."""
    if not chat_file or not msg: return False
    try:
        os.makedirs(os.path.dirname(chat_file) or '.', exist_ok=True)
        with open(chat_file, 'r+') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try: msgs = json.load(f)
            except: msgs = []
            msgs.append({'time': time.strftime('%H:%M:%S'), 'msg': msg, 'n': len(msgs) + 1})
            if len(msgs) > 200: msgs = msgs[-200:]
            f.seek(0); f.truncate(); json.dump(msgs, f)
            fcntl.flock(f, fcntl.LOCK_UN)
        return True
    except: return False

class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Server", "expose")
        for name, value in custom_headers:
            self.send_header(name, value)
        super().end_headers()

    def finish(self):
        try:
            super().finish()
        finally:
            if serve_once and _httpd is not None:
                threading.Thread(target=_httpd.shutdown, daemon=True).start()

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

    def _check_access(self):
        return not self._auth_fail() and not self._allow_fail()

    def _auth_fail(self):
        if not auth_required: return False
        ah = self.headers.get("Authorization", "")
        if ah.startswith("Basic "):
            try:
                decoded = base64.b64decode(ah[6:]).decode()
                if hmac.compare_digest(decoded, auth_required):
                    return False
            except Exception: pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="expose"')
        b = b"401 Unauthorized"
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
        return True

    def _allow_fail(self):
        if not allow_nets: return False
        try:
            addr = ipaddress.ip_address(self.client_address[0])
            if any(addr in ipaddress.ip_network(net, strict=False) for net in allow_nets):
                return False
        except Exception:
            pass
        self.send_response(403)
        b = b"403 Forbidden"
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
        return True

    def do_GET(self):
        if not self._check_access():
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
        elif self.path in ('/', '/upload'):
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
        elif self.path.startswith("/upload/files/"):
            name = urllib.parse.unquote(self.path[len("/upload/files/"):])
            name = os.path.basename(name)
            fp = os.path.join(upload_dir, name)
            if os.path.isfile(fp):
                mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                sz = os.path.getsize(fp)
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(sz))
                encoded_name = urllib.parse.quote(name, safe="")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
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
        if not self._check_access():
            return
        body = self._read_body()
        self.request_body = body[:body_limit] if body_limit else b""
        if catch_requests and body:
            shown = body[:body_limit] if body_limit else b""
            sys.stderr.write(f"\n  body ({len(body)} bytes)\n")
            sys.stderr.flush()
            sys.stderr.buffer.write(shown + b"\n")
            sys.stderr.buffer.flush()
        if self.path == '/log/clear':
            try:
                with open(log_file, 'w') as f: json.dump([], f)
            except: pass
            result = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == "/upload":
            ct = self.headers.get("Content-Type", "")
            saved = parse_multipart(body, ct)
            result = json.dumps({"saved": saved, "count": len(saved)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == "/fp":
            raw = body.decode('utf-8', errors='replace')
            _write_fp(raw, self.client_address[0], str(self.client_address[1]),
                      self.headers.get("User-Agent", ""))
            result = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == '/chat':
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
        if self._check_access():
            self._send(204, b"", "text/plain")

    def do_DELETE(self):
        if self._auth_fail(): return
        if self._allow_fail(): return
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
        global req_counter
        with counter_lock:
            req_counter += 1
            request_number = req_counter
        ua = self.headers.get("User-Agent", "-") if self.headers else "-"
        code = str(args[1]) if len(args) > 1 else "-"
        now = datetime.datetime.now().strftime("%H:%M:%S")
        client_ip = self.client_address[0]
        client_port = self.client_address[1]

        if verbose:
            host_name = rdns(client_ip)
            browser, os_name = parse_ua(ua)
            W = "\033[0m"; DM = "\033[2m"; BD = "\033[1m"; BL = "\033[34m"
            CY = "\033[36m"; YW = "\033[1;33m"; UL = "\033[4m"
            cc = "\033[32m" if code.startswith("2") else "\033[33m" if code.startswith("3") else "\033[31m"
            SEP = f"  {DM}│{W}"
            lines = []
            lines.append(f"\n  {DM}┌─ #{request_number} ─────────────────────────────────────────────{W}")
            lines.append(f"{SEP} {DM}{now}{W}  {BD}{self.command or '-'} {CY}{self.path or '-'}{W}  {cc}{code}{W}  {DM}{self.request_version}{W}")
            client_str = f"{client_ip}:{client_port}"
            if host_name: client_str += f"  {DM}({host_name}){W}"
            lines.append(f"{SEP} {BL}Client{W}    {client_str}")
            xff = self.headers.get("X-Forwarded-For")
            if xff: lines.append(f"{SEP} {BL}Proxy{W}     {xff}")
            lines.append(f"{SEP} {BL}Browser{W}   {browser}  {DM}({os_name}){W}")
            for label, key in [("Host", "Host"), ("Language", "Accept-Language"),
                               ("Accept", "Accept"), ("Encoding", "Accept-Encoding")]:
                v = self.headers.get(key)
                if v: lines.append(f"{SEP} {BL}{label:<9}{W} {v}")
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
            # Extra headers (Sec-*, Cache-Control, Auth, etc.)
            extras = []
            for k in self.headers:
                kl = k.lower()
                if kl.startswith("sec-") or kl in ("cache-control", "pragma", "authorization",
                    "if-modified-since", "if-none-match", "upgrade-insecure-requests"):
                    extras.append(f"  {k}: {self.headers[k]}")
            if extras:
                lines.append(f"{SEP} {DM}──────{W}")
                for e in extras:
                    lines.append(f"{SEP} {DM}{e}{W}")
            lines.append(f"  {DM}└───────────────────────────────────────────────────{W}")
            sys.stderr.write("\n".join(lines) + "\n")
        else:
            cc = "\033[32m" if code.startswith("2") else "\033[33m" if code.startswith("3") else "\033[31m"
            sys.stderr.write(
                "\033[2m%s\033[0m  \033[1;33m%-15s\033[0m  \033[1m%-7s\033[0m \033[36m%s\033[0m  %s%s\033[0m  \033[2m%s\033[0m\n"
                % (now, client_ip, self.command or "-", self.path or "-", cc, code, ua))
        sys.stderr.flush()

        # Write to JSON log
        _skip = {'/log', '/log/clear', '/meta', '/upload/files', '/chat', '/fp'}
        _path_clean = (self.path or '').split('?')[0]
        if _path_clean not in _skip:
            entry = {"n": request_number, "ts": time.time(), "time": now,
                     "method": self.command or "-", "path": self.path or "-",
                     "httpver": self.request_version or "-",
                     "ip": client_ip, "port": client_port, "code": code, "ua": ua}
            if self.headers:
                for k in ("Host", "Accept", "Accept-Language", "Accept-Encoding",
                           "Referer", "Cookie", "Origin", "Connection",
                           "Content-Type", "Content-Length", "X-Forwarded-For",
                           "Authorization", "DNT"):
                    v = self.headers.get(k)
                    if v: entry[k.lower().replace("-","_")] = v
            request_body = getattr(self, "request_body", b"")
            if request_body:
                entry["body"] = request_body.decode("utf-8", errors="replace")
            _write_log(entry)
            _write_collect(entry)
            _write_db(entry)

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

with Server((bind_addr, port), Handler) as httpd:
    _httpd = httpd

    def stop_server(_signum, _frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)

    if os.environ.get("EXPOSE_TLS") == "1":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.environ["EXPOSE_CERTFILE"], os.environ["EXPOSE_KEYFILE"])
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()

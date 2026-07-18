import http.server, socketserver, sys, datetime, os, socket, re, json, time, ipaddress, threading

port = int(os.environ["EXPOSE_PORT"])
bind_addr = os.environ.get("EXPOSE_BIND", "0.0.0.0")
verbose = os.environ.get("EXPOSE_VERBOSE", "0") == "1"
upload_dir = os.environ.get("EXPOSE_UPLOAD_DIR", "/tmp/expose-uploads")
upload_html_path = os.environ.get("EXPOSE_UPLOAD_HTML", "")
auth_required = os.environ.get("EXPOSE_AUTH", "")
log_file = os.environ.get("EXPOSE_LOGFILE", "")
allow_nets = [n.strip() for n in os.environ.get("EXPOSE_ALLOW", "").split(",") if n.strip()]
os.makedirs(upload_dir, exist_ok=True)
req_counter = 0
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
    boundary = None
    for p in content_type.split(";"):
        p = p.strip()
        if p.startswith("boundary="): boundary = p[9:].strip('"'); break
    saved = []
    if not boundary: return saved
    sep = ("--" + boundary).encode()
    for part in body.split(sep)[1:]:
        if part.strip() == b"--" or not part.strip(): continue
        chunks = part.split(b"\r\n\r\n", 1)
        if len(chunks) < 2: continue
        hdrs, fdata = chunks
        if fdata.endswith(b"\r\n"): fdata = fdata[:-2]
        filename = None
        for line in hdrs.decode("utf-8", errors="replace").split("\r\n"):
            if "filename=" in line.lower():
                for param in line.split(";"):
                    param = param.strip()
                    if param.lower().startswith("filename="):
                        filename = param[9:].strip('"'); break
        if not filename: continue
        name = os.path.basename(filename).replace("..", "").lstrip(".")
        if not name: continue
        path = os.path.join(upload_dir, name)
        base, ext = os.path.splitext(name)
        i = 1
        while os.path.exists(path): path = os.path.join(upload_dir, f"{base}_{i}{ext}"); i += 1
        with open(path, "wb") as f: f.write(fdata)
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
    import fcntl
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

class Handler(http.server.SimpleHTTPRequestHandler):
    def _auth_fail(self):
        if not auth_required: return False
        import base64
        ah = self.headers.get("Authorization", "")
        if ah.startswith("Basic "):
            try:
                if base64.b64decode(ah[6:]).decode() == auth_required: return False
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
        if self._auth_fail(): return
        if self._allow_fail(): return
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
            result = json.dumps({"mode": "dir", "path": os.getcwd()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif self.path == '/ls' or self.path.startswith('/ls/'):
            import urllib.parse, stat
            raw = urllib.parse.unquote(self.path[3:]) or '/'
            base = os.path.realpath(os.getcwd())
            rel = raw.lstrip('/')
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(base):
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
            import urllib.parse, mimetypes
            name = urllib.parse.unquote(self.path[len("/upload/files/"):])
            name = os.path.basename(name)
            fp = os.path.join(upload_dir, name)
            if os.path.isfile(fp):
                mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
                sz = os.path.getsize(fp)
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(sz))
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.end_headers()
                with open(fp, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk: break
                        self.wfile.write(chunk)
            else:
                self.send_error(404)
        elif self.path == '/me':
            import html as _html
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
                    f"<tr><td>{_html.escape(k)}</td><td>{_html.escape(v)}</td></tr>"
                    for k, v in fields if v and v != "-")
                body = (
                    "<html><head><meta charset='utf-8'><title>expose / me</title>"
                    "<style>body{font:14px/1.6 ui-monospace,monospace;background:#1a1917;color:#c8c5be;"
                    "max-width:700px;margin:2rem auto;padding:0 1rem}"
                    "h1{font-size:1rem;color:#84817a;margin-bottom:1.5rem;font-weight:400}"
                    "h1 b{color:#c8c5be}table{border-collapse:collapse;width:100%}"
                    "td{padding:.35rem .6rem;border-bottom:1px solid #2a2820;font-size:.8125rem}"
                    "td:first-child{color:#5c8abf;width:10rem;white-space:nowrap}"
                    "td:last-child{color:#c8c5be;word-break:break-all}"
                    "</style></head><body>"
                    "<h1><b>expose</b> / me</h1>"
                    f"<table>{rows}</table></body></html>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        else:
            super().do_GET()

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
        if self._auth_fail(): return
        if self._allow_fail(): return
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
            cl = int(self.headers.get("Content-Length", 0))
            ct = self.headers.get("Content-Type", "")
            body = self.rfile.read(cl)
            saved = parse_multipart(body, ct)
            result = json.dumps({"saved": saved, "count": len(saved)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        else:
            self.send_error(405)

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
        req_counter += 1
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
            lines.append(f"\n  {DM}┌─ #{req_counter} ─────────────────────────────────────────────{W}")
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
        _skip = {'/log', '/log/clear', '/meta', '/upload/files'}
        _path_clean = (self.path or '').split('?')[0]
        if _path_clean not in _skip:
            entry = {"n": req_counter, "ts": time.time(), "time": now,
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
            _write_log(entry)

class Server(socketserver.TCPServer):
    allow_reuse_address = True

with Server((bind_addr, port), Handler) as httpd:
    _httpd = httpd
    httpd.serve_forever()

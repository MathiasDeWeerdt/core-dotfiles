"""Bounded HTTP relay for foreground PTY connectors."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import shlex
import threading
import time
import urllib.parse


class ConsoleService:
    def __init__(self, enabled, client_dir):
        self.enabled = enabled
        self.client_dir = client_dir
        self.invites = {}
        self.sessions = {}
        self.condition = threading.Condition()
        self.platforms = ['linux-amd64', 'linux-arm64', 'darwin-amd64', 'darwin-arm64',
                          'windows-amd64.exe', 'windows-arm64.exe']
    def reply(self, handler, status, value):
        handler._send(status, json.dumps(value), 'application/json', (
            ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
            ('X-Content-Type-Options', 'nosniff')))

    def body(self, handler, raw=False):
        size = int(handler.headers.get('Content-Length', '0'))
        if not 0 <= size <= 65536:
            raise ValueError('Request exceeds 64 KB')
        data = handler.rfile.read(size)
        if raw:
            return data
        value = json.loads(data or '{}')
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        return value

    def token(self, handler):
        return handler.headers.get('Authorization', '').removeprefix('Bearer ')

    def authorized(self, handler, token):
        return bool(token) and hmac.compare_digest(self.token(handler), token)

    def prune(self):
        now = time.time()
        self.invites = {k: v for k, v in self.invites.items() if v['expires'] > now}
        for session in self.sessions.values():
            if now - session['seen'] > 45:
                session['connected'] = False
        self.sessions = {k: s for k, s in self.sessions.items()
                         if s['connected'] or now - s['seen'] < 900}

    def available(self):
        return [name for name in self.platforms if os.path.isfile(os.path.join(self.client_dir, name))]

    def session_info(self, session):
        return {key: session[key] for key in ('id', 'host', 'os', 'arch', 'connected', 'seen')}

    def handle(self, handler):
        parsed = urllib.parse.urlsplit(handler.path)
        path = parsed.path
        if not (path.startswith('/console/') or path in ('/lin', '/mac', '/win')):
            return False
        try:
            if path == '/console/status' and handler.command == 'GET':
                self.reply(handler, 200, {'enabled': self.enabled, 'platforms': self.available()})
                return True
            if not self.enabled:
                handler.close_connection = True
                self.reply(handler, 403, {'error': 'Start expose-online to use browser consoles'})
                return True
            with self.condition:
                self.prune()
            if path in ('/lin', '/mac', '/win') or path.startswith('/console/client/'):
                self.bootstrap(handler, path, urllib.parse.parse_qs(parsed.query))
                return True
            if path == '/console/register' and handler.command == 'POST':
                self.register(handler)
                return True
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['console', 'agent']:
                self.agent(handler, parts[2], parts[3], urllib.parse.parse_qs(parsed.query))
                return True
            if path == '/console/sessions' and handler.command == 'GET':
                with self.condition:
                    self.reply(handler, 200, [self.session_info(s) for s in self.sessions.values()])
            elif path == '/console/invites' and handler.command == 'POST':
                data = self.body(handler)
                url = urllib.parse.urlsplit(data.get('origin', ''))
                if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                        or url.password or url.path not in ('', '/') or url.query or url.fragment):
                    raise ValueError('Use an HTTP(S) origin without a path')
                with self.condition:
                    if len(self.invites) >= 32:
                        raise ValueError('Too many active connection links; wait for them to expire')
                    ticket = secrets.token_urlsafe(32)
                    self.invites[ticket] = {'origin': f'{url.scheme}://{url.netloc}', 'expires': time.time() + 600}
                self.reply(handler, 200, {'ticket': ticket, 'expires': self.invites[ticket]['expires']})
            elif len(parts) == 4 and parts[:2] == ['console', 'sessions']:
                self.operator(handler, parts[2], parts[3], urllib.parse.parse_qs(parsed.query))
            else:
                self.reply(handler, 404, {'error': 'Unknown console operation'})
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            handler.close_connection = True
            self.reply(handler, 400, {'error': str(error) or 'Invalid request'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        return True

    def register(self, handler):
        data = self.body(handler)
        with self.condition:
            ticket = self.token(handler)
            invite = self.invites.get(ticket)
            if not invite or invite['expires'] <= time.time():
                self.reply(handler, 401, {'error': 'Connection link expired or already used'}); return
            if len(self.sessions) >= 32:
                self.reply(handler, 429, {'error': 'Session limit reached'}); return
            ident, token = secrets.token_urlsafe(16), secrets.token_urlsafe(32)
            session = {'id': ident, 'token': token, 'host': str(data.get('host', 'client'))[:100],
                       'os': str(data.get('os', ''))[:20], 'arch': str(data.get('arch', ''))[:20],
                       'connected': True, 'seen': time.time(), 'events': [], 'seq': 0,
                       'output': bytearray(), 'offset': 0, 'input_size': 0}
            self.sessions[ident] = session
            del self.invites[ticket]
            self.reply(handler, 200, {'id': ident, 'token': token})
            self.condition.notify_all()

    def agent(self, handler, ident, action, query):
        with self.condition:
            session = self.sessions.get(ident)
            if not session or not self.authorized(handler, session['token']):
                handler.close_connection = True
                self.reply(handler, 401, {'error': 'Invalid session'}); return
            if not session['connected']:
                self.reply(handler, 410, {'error': 'Session closed'}); return
            session['seen'] = time.time()
        if action == 'input' and handler.command == 'GET':
            cursor = int(query.get('after', ['0'])[0])
            with self.condition:
                session['events'] = [e for e in session['events'] if e['seq'] > cursor]
                session['input_size'] = sum(len(e.get('data', '')) for e in session['events'])
                self.condition.wait_for(lambda: session['events'] or not session['connected'], timeout=10)
                self.reply(handler, 200, {'events': session['events'], 'closed': not session['connected']})
        elif action == 'output' and handler.command == 'POST':
            data = self.body(handler, raw=True)
            with self.condition:
                session['output'].extend(data)
                excess = len(session['output']) - 2 * 1024 * 1024
                if excess > 0:
                    del session['output'][:excess]; session['offset'] += excess
                self.condition.notify_all()
            self.reply(handler, 200, {'ok': True})
        elif action == 'exit' and handler.command == 'POST':
            with self.condition:
                session['connected'] = False
                self.condition.notify_all()
            self.reply(handler, 200, {'ok': True})
        else:
            self.reply(handler, 404, {'error': 'Unknown connector operation'})

    def operator(self, handler, ident, action, query):
        with self.condition:
            session = self.sessions.get(ident)
        if not session:
            self.reply(handler, 404, {'error': 'Session not found'}); return
        if action == 'output' and handler.command == 'GET':
            cursor = max(0, int(query.get('after', ['0'])[0]))
            with self.condition:
                self.condition.wait_for(lambda: session['offset'] + len(session['output']) > cursor
                                        or not session['connected'], timeout=10)
                start = max(cursor, session['offset'])
                data = bytes(session['output'][start - session['offset']:start - session['offset'] + 65536])
                self.reply(handler, 200, {'data': base64.b64encode(data).decode(), 'next': start + len(data),
                                         'truncated': cursor < session['offset'], 'connected': session['connected']})
        elif action in ('input', 'resize', 'close', 'remove') and handler.command == 'POST':
            data = self.body(handler)
            with self.condition:
                if action in ('close', 'remove'):
                    session['connected'] = False
                    if action == 'remove':
                        self.sessions.pop(ident, None)
                        session['events'].clear()
                        session['output'].clear()
                        session['input_size'] = 0
                else:
                    if not session['connected']:
                        self.reply(handler, 410, {'error': 'Session closed'}); return
                    if len(session['events']) >= 256:
                        self.reply(handler, 429, {'error': 'Input queue is full'}); return
                    event = {}
                    if action == 'input':
                        raw = data.get('data', '')
                        if not isinstance(raw, str): raise ValueError('Invalid input')
                        encoded = base64.b64encode(raw.encode()).decode()
                        if session['input_size'] + len(encoded) > 65536:
                            self.reply(handler, 429, {'error': 'Input queue is full'}); return
                        event['data'] = encoded
                        session['input_size'] += len(encoded)
                    else:
                        cols, rows = int(data['cols']), int(data['rows'])
                        if not 2 <= cols <= 500 or not 2 <= rows <= 200: raise ValueError('Invalid terminal size')
                        event['cols'], event['rows'] = cols, rows
                    session['seq'] += 1
                    event['seq'] = session['seq']; session['events'].append(event)
                self.condition.notify_all()
            self.reply(handler, 200, {'ok': True})
        else:
            self.reply(handler, 404, {'error': 'Unknown console operation'})

    def bootstrap(self, handler, path, query):
        if handler.command != 'GET':
            self.reply(handler, 405, {'error': 'GET required'}); return
        ticket = query.get('ticket', [''])[0]
        with self.condition:
            invite = self.invites.get(ticket)
        if not invite or invite['expires'] <= time.time():
            self.reply(handler, 401, {'error': 'Connection link expired or already used'}); return
        if path.startswith('/console/client/'):
            name = path.rsplit('/', 1)[-1]
            if name not in self.available():
                self.reply(handler, 404, {'error': 'Connector not built for this platform'}); return
            with open(os.path.join(self.client_dir, name), 'rb') as binary:
                handler._send(200, binary.read(), 'application/octet-stream', (('Cache-Control', 'no-store'),))
            return
        target = {'/lin': 'linux', '/mac': 'darwin', '/win': 'windows'}[path]
        hashes = {}
        for arch in ('amd64', 'arm64'):
            name = f'{target}-{arch}' + ('.exe' if target == 'windows' else '')
            if name in self.available():
                with open(os.path.join(self.client_dir, name), 'rb') as binary:
                    hashes[arch] = hashlib.file_digest(binary, 'sha256').hexdigest()
        if not hashes:
            self.reply(handler, 503, {'error': 'Run make console-clients on the host first'}); return
        origin = invite['origin']
        if target == 'windows':
            script = self.windows_script(origin, ticket, hashes)
        else:
            script = self.unix_script(origin, ticket, hashes, target)
        handler._send(200, script, 'text/plain; charset=utf-8', (
            ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
            ('X-Content-Type-Options', 'nosniff')))

    @staticmethod
    def unix_script(origin, ticket, hashes, target):
        return f'''#!/usr/bin/env bash
set -euo pipefail
case "$(uname -m)" in x86_64|amd64) arch=amd64; expected={shlex.quote(hashes.get('amd64', 'unavailable'))};; arm64|aarch64) arch=arm64; expected={shlex.quote(hashes.get('arm64', 'unavailable'))};; *) echo 'Unsupported architecture' >&2; exit 1;; esac
work=$(mktemp -d)
cleanup() {{ rm -f "$work/connector"; rmdir "$work"; }}
trap cleanup EXIT
curl --fail --silent --show-error --location {shlex.quote(origin + '/console/client/' + target + '-')}"$arch"{shlex.quote('?ticket=' + ticket)} -o "$work/connector"
if command -v sha256sum >/dev/null; then actual=$(sha256sum "$work/connector" | cut -d ' ' -f1); else actual=$(shasum -a 256 "$work/connector" | cut -d ' ' -f1); fi
[[ "$actual" == "$expected" ]] || {{ echo 'Connector checksum mismatch' >&2; exit 1; }}
chmod 700 "$work/connector"
EXPOSE_URL={shlex.quote(origin)} EXPOSE_TICKET={shlex.quote(ticket)} "$work/connector"
'''

    @staticmethod
    def windows_script(origin, ticket, hashes):
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        return f'''$ErrorActionPreference = 'Stop'
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {{ 'arm64' }} else {{ 'amd64' }}
$hashes = @{{ amd64 = '{hashes.get('amd64', 'unavailable')}'; arm64 = '{hashes.get('arm64', 'unavailable')}' }}
$file = Join-Path ([IO.Path]::GetTempPath()) ('expose-' + [guid]::NewGuid().ToString('N') + '.exe')
try {{
  Invoke-WebRequest -UseBasicParsing -Uri ({quote(origin + '/console/client/windows-')} + $arch + {quote('.exe?ticket=' + ticket)}) -OutFile $file
  if ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant() -ne $hashes[$arch]) {{ throw 'Connector checksum mismatch' }}
  $env:EXPOSE_URL = {quote(origin)}
  $env:EXPOSE_TICKET = {quote(ticket)}
  & $file
}} finally {{
  Remove-Item Env:EXPOSE_URL, Env:EXPOSE_TICKET -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue
}}
'''

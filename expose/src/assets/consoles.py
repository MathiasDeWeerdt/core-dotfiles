"""Bounded HTTP relay for PTY connectors and a SOCKS5 network proxy."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import shlex
import socket
import struct
import sys
import threading
import time
import urllib.parse


class ConsoleService:
    NET_STREAMS = 256
    NET_EVENTS = 256
    NET_QUEUE = 512 * 1024
    NET_BUFFER = 4 * 1024 * 1024
    STALE_AFTER = 45
    SESSION_RETENTION = 24 * 3600
    CLOSED_RETENTION = 900

    def __init__(self, enabled, client_dir):
        self.enabled = enabled
        self.client_dir = client_dir
        self.invites = {}
        self.sessions = {}
        self.registrations = {}
        self.callbacks = {}
        self.proxy_session = ''
        self.proxy_address = ''
        self.proxy_stats = {'opens': 0, 'failed': 0, 'sent': 0, 'received': 0}
        self.event_seen = {}
        self.script_tickets = {}
        self.winenum_script = ''
        self.toolrunner_script = ''
        self.tools_dir = ''
        self.condition = threading.Condition()
        self.platforms = ['linux-amd64', 'linux-arm64', 'darwin-amd64', 'darwin-arm64',
                          'windows-amd64.exe', 'windows-arm64.exe']
    def reply(self, handler, status, value):
        handler._send(status, json.dumps(value), 'application/json', (
            ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
            ('X-Content-Type-Options', 'nosniff')))

    def body(self, handler, raw=False):
        if not getattr(handler, '_console_body_set', False):
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 <= size <= 65536:
                raise ValueError('Request exceeds 64 KB')
            handler._console_body = handler.rfile.read(size)
            handler._console_body_set = True
        data = handler._console_body
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

    @staticmethod
    def request_ip(handler):
        peer = handler.client_address[0]
        if peer in ('127.0.0.1', '::1'):
            real = handler.headers.get('X-Real-IP', '').strip()
            if real:
                return real
            forwarded = handler.headers.get('X-Forwarded-For', '')
            if forwarded.strip():
                return forwarded.split(',')[-1].strip()
        return peer

    @staticmethod
    def event(kind, message, ip=''):
        sys.stderr.write(f"{time.strftime('%H:%M:%S')}  {ip:<15}  {kind:<9} {message}\n")
        sys.stderr.flush()

    def event_once(self, key, kind, message, ip='', window=10):
        now = time.time()
        with self.condition:
            if now - self.event_seen.get(key, 0) < window:
                return
            self.event_seen[key] = now
            for seen_key, seen_at in list(self.event_seen.items()):
                if now - seen_at > 3600:
                    self.event_seen.pop(seen_key, None)
        self.event(kind, message, ip)

    def touch(self, session):
        now = time.time()
        resumed = session['connected'] and now - session['seen'] > 60
        session['seen'] = now
        if resumed:
            self.event('CONNECTOR', f"{session['host']} resumed", session.get('ip', ''))

    def prune(self):
        now = time.time()
        self.invites = {k: v for k, v in self.invites.items() if v['expires'] > now}
        self.registrations = {k: v for k, v in self.registrations.items()
                              if v['expires'] > now}
        self.script_tickets = {k: v for k, v in self.script_tickets.items() if v > now}
        keep = {}
        for ident, session in self.sessions.items():
            retention = self.SESSION_RETENTION if session['connected'] else self.CLOSED_RETENTION
            if now - session['seen'] < retention:
                keep[ident] = session
            else:
                self._close_net(session)
                self.event('CONNECTOR', f"{session['host']} expired", session.get('ip', ''))
        self.sessions = keep

    def _close_net(self, session):
        for stream in session['net_streams'].values():
            stream['closed'] = True
        session['net_events'].clear()
        for callback in self.callbacks.values():
            if callback['session'] == session['id']:
                callback['session'] = ''
                callback['active'] = False
                callback['address'] = ''
                callback['error'] = 'Machine disconnected'
        self.condition.notify_all()

    def _net_session_locked(self):
        selected = self.sessions.get(self.proxy_session)
        if selected and selected['connected']:
            return selected
        self.proxy_session = ''
        live = [s for s in self.sessions.values() if s['connected']]
        return max(live, key=lambda s: s['seen']) if live else None

    def _queue_net(self, session, event):
        queued = sum(len(item.get('data', '')) for item in session['net_events'])
        if len(session['net_events']) >= self.NET_EVENTS or queued >= self.NET_QUEUE:
            raise ValueError('Network proxy queue is full')
        session['net_seq'] += 1
        event['seq'] = session['net_seq']
        session['net_events'].append(event)
        self.condition.notify_all()

    def net_open(self, host, port):
        with self.condition:
            self.proxy_stats['opens'] += 1
            try:
                session = self._net_session_locked()
                if not session:
                    raise ValueError('No connected machine; connect a console first')
                if len(session['net_streams']) >= self.NET_STREAMS:
                    raise ValueError('Too many active proxy streams')
                ident, sid = session['id'], secrets.token_hex(8)
                session['net_streams'][sid] = {'open': None, 'closed': False, 'data': bytearray()}
                try:
                    self._queue_net(session, {'type': 'open', 'stream': sid,
                                              'host': host, 'port': port})
                except ValueError:
                    session['net_streams'].pop(sid, None)
                    raise
                deadline = time.time() + 7
                while session['net_streams'].get(sid, {}).get('open') is None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    self.condition.wait(remaining)
                stream = session['net_streams'].get(sid)
                if not stream or stream['open'] is not True:
                    session['net_streams'].pop(sid, None)
                    try:
                        self._queue_net(session, {'type': 'close', 'stream': sid})
                    except ValueError:
                        pass
                    raise ValueError('The machine could not reach the target')
                self.event_once(('socks', host, port), 'SOCKS',
                                f"{host}:{port} via {session['host']}",
                                session.get('ip', ''), 15)
                return ident, sid
            except Exception as error:
                self.proxy_stats['failed'] += 1
                self.event_once(('socksfail', host, port), 'SOCKS',
                                f"{host}:{port} failed: {error}", '', 30)
                raise

    def net_read(self, ident, sid, timeout=10):
        with self.condition:
            session = self.sessions.get(ident)
            stream = session and session['net_streams'].get(sid)
            if not stream:
                return b'', True
            deadline = time.time() + timeout
            while not stream['data'] and not stream['closed']:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            chunk = bytes(stream['data'][:65536])
            del stream['data'][:len(chunk)]
            self.condition.notify_all()
            closed = stream['closed'] and not stream['data']
            if closed:
                session['net_streams'].pop(sid, None)
            return chunk, closed

    def net_write(self, ident, sid, data):
        deadline = time.time() + 30
        with self.condition:
            while True:
                session = self.sessions.get(ident)
                stream = session and session['net_streams'].get(sid)
                if not stream or stream['closed'] or stream['open'] is not True or not session['connected']:
                    raise ValueError('Proxy stream closed')
                queued = sum(len(item.get('data', '')) for item in session['net_events'])
                if len(session['net_events']) < self.NET_EVENTS and queued < self.NET_QUEUE:
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise ValueError('Network proxy queue is full')
                self.condition.wait(remaining)
            self._queue_net(session, {'type': 'data', 'stream': sid,
                                      'data': base64.b64encode(data).decode()})
            self.proxy_stats['sent'] += len(data)

    def net_close(self, ident, sid):
        with self.condition:
            session = self.sessions.get(ident)
            stream = session and session['net_streams'].get(sid)
            if not stream or stream['closed']:
                return
            try:
                self._queue_net(session, {'type': 'close', 'stream': sid})
            except ValueError:
                pass
            stream['closed'] = True
            self.condition.notify_all()

    def proxy_info(self):
        with self.condition:
            session = self._net_session_locked()
            return {'enabled': bool(self.proxy_address), 'address': self.proxy_address,
                    'session': ({'id': session['id'], 'host': session['host']}
                                if session else None),
                    'streams': len(session['net_streams']) if session else 0,
                    'stats': dict(self.proxy_stats)}

    def set_proxy_session(self, ident):
        with self.condition:
            if ident and ident not in self.sessions:
                raise ValueError('Session not found')
            self.proxy_session = ident or ''
            self.condition.notify_all()
        return self.proxy_info()

    def start_proxy(self, bind):
        proxy = SocksProxy(self, bind)
        proxy.start()
        with self.condition:
            self.proxy_address = proxy.address
        return proxy

    def new_script_ticket(self):
        with self.condition:
            now = time.time()
            self.script_tickets = {k: v for k, v in self.script_tickets.items() if v > now}
            if len(self.script_tickets) >= 16:
                self.script_tickets.pop(next(iter(self.script_tickets)), None)
            ticket = secrets.token_urlsafe(24)
            self.script_tickets[ticket] = now + 3600
            return ticket

    def valid_transfer_ticket(self, ticket):
        if not ticket:
            return False
        with self.condition:
            expires = self.script_tickets.get(ticket)
            if not expires or expires < time.time():
                self.script_tickets.pop(ticket, None)
                return False
            return True

    def callback_info(self, callback):
        session = self.sessions.get(callback['session'])
        return {'id': callback['id'], 'local': callback['local'],
                'remote': callback['remote'], 'active': callback['active'],
                'address': callback['address'], 'error': callback['error'],
                'host': session['host'] if session else ''}

    def _bind_callback_locked(self, callback, session):
        callback['session'] = session['id']
        callback['active'] = False
        callback['address'] = ''
        callback['error'] = 'Binding…'
        try:
            self._queue_net(session, {'type': 'listen', 'callback': callback['id'],
                                      'port': callback['remote']})
        except ValueError as error:
            callback['error'] = str(error)

    def add_callback(self, local, remote):
        if not 1 <= local <= 65535 or not 1 <= remote <= 65535:
            raise ValueError('Ports must be 1–65535')
        with self.condition:
            for existing in self.callbacks.values():
                if existing['remote'] == remote:
                    raise ValueError(f'Endpoint port {remote} already has a callback')
            callback = {'id': secrets.token_hex(6), 'local': local, 'remote': remote,
                        'session': '', 'active': False, 'address': '',
                        'error': 'Waiting for a machine'}
            self.callbacks[callback['id']] = callback
            session = self._net_session_locked()
            if session:
                self._bind_callback_locked(callback, session)
            return self.callback_info(callback)

    def remove_callback(self, cid):
        with self.condition:
            callback = self.callbacks.pop(cid, None)
            if not callback:
                raise ValueError('Callback not found')
            session = self.sessions.get(callback['session'])
            if session and session['connected']:
                try:
                    self._queue_net(session, {'type': 'unlisten', 'callback': cid})
                except ValueError:
                    pass
                for stream in session['net_streams'].values():
                    if stream.get('callback') == cid:
                        stream['closed'] = True
                self.condition.notify_all()
            return {'ok': True}

    def set_callback_state(self, ident, cid, data):
        with self.condition:
            callback = self.callbacks.get(cid)
            if not callback or callback['session'] != ident:
                return False
            callback['active'] = bool(data.get('active'))
            callback['address'] = str(data.get('address', ''))[:128]
            callback['error'] = str(data.get('error', ''))[:200]
            session = self.sessions.get(ident)
            callback_ip = session.get('ip', '') if session else ''
            if callback['active']:
                self.event('CALLBACK', f"{callback['address']} -> 127.0.0.1:{callback['local']}",
                           callback_ip)
            elif callback['error']:
                self.event('CALLBACK', f"127.0.0.1:{callback['local']} failed: {callback['error']}",
                           callback_ip)
            self.condition.notify_all()
            return True

    def callback_stream(self, callback, ident, sid):
        try:
            local = socket.create_connection(('127.0.0.1', callback['local']), timeout=10)
        except OSError:
            self.net_close(ident, sid)
            return

        def upstream():
            try:
                while True:
                    data = local.recv(32768)
                    if not data:
                        break
                    self.net_write(ident, sid, data)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    self.net_close(ident, sid)
                except OSError:
                    pass

        threading.Thread(target=upstream, daemon=True).start()
        try:
            while True:
                data, closed = self.net_read(ident, sid)
                if data:
                    local.sendall(data)
                if closed:
                    break
        except OSError:
            pass
        finally:
            try:
                local.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            local.close()
            self.net_close(ident, sid)

    def available(self):
        return [name for name in self.platforms if os.path.isfile(os.path.join(self.client_dir, name))]

    def session_info(self, session):
        info = {key: session[key] for key in ('id', 'host', 'os', 'arch', 'connected', 'seen')}
        info['stale'] = time.time() - session['seen'] > self.STALE_AFTER
        info['ip'] = session.get('ip', '')
        return info

    def handle(self, handler):
        parsed = urllib.parse.urlsplit(handler.path)
        path = parsed.path
        if not (path.startswith('/console/') or path in ('/lin', '/mac', '/win')):
            return False
        handler._console_body_set = False
        try:
            if handler.command == 'POST':
                self.body(handler, raw=True)
            if path == '/console/status' and handler.command == 'GET':
                self.reply(handler, 200, {'enabled': self.enabled, 'platforms': self.available()})
                return True
            if not self.enabled:
                handler.close_connection = True
                self.reply(handler, 403, {'error': 'Start expose-online to use browser consoles'})
                return True
            with self.condition:
                self.prune()
            if path == '/console/winenum/ticket' and handler.command == 'POST':
                self.reply(handler, 200, {'ticket': self.new_script_ticket(),
                                          'expires': time.time() + 3600})
                return True
            if path == '/console/winenum.ps1' and handler.command == 'GET':
                ticket = urllib.parse.parse_qs(parsed.query).get('ticket', [''])[0]
                if not self.valid_transfer_ticket(ticket):
                    self.reply(handler, 401, {'error': 'Script link expired'})
                    return True
                body = self.winenum_script or '# winenum script unavailable'
                handler._send(200, body, 'text/plain; charset=utf-8', (
                    ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
                    ('X-Content-Type-Options', 'nosniff')))
                return True
            if path == '/console/tools' and handler.command == 'GET':
                files = []
                if self.tools_dir and os.path.isdir(self.tools_dir):
                    for name in sorted(os.listdir(self.tools_dir)):
                        target = os.path.join(self.tools_dir, name)
                        if os.path.isfile(target):
                            info = os.stat(target)
                            files.append({'name': name, 'size': info.st_size,
                                          'mtime': int(info.st_mtime)})
                self.reply(handler, 200, {'tools': files})
                return True
            if path.startswith('/console/tool/') and handler.command == 'GET':
                ticket = urllib.parse.parse_qs(parsed.query).get('ticket', [''])[0]
                if not self.valid_transfer_ticket(ticket):
                    self.reply(handler, 401, {'error': 'Tool link expired'})
                    return True
                name = os.path.basename(urllib.parse.unquote(path[len('/console/tool/'):]))
                target = os.path.join(self.tools_dir, name)
                if not self.tools_dir or not os.path.isfile(target):
                    self.reply(handler, 404, {'error': 'Tool not staged'})
                    return True
                with open(target, 'rb') as tool_file:
                    handler._send(200, tool_file.read(), 'application/octet-stream', (
                        ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff')))
                return True
            if path == '/console/toolrunner.ps1' and handler.command == 'GET':
                ticket = urllib.parse.parse_qs(parsed.query).get('ticket', [''])[0]
                if not self.valid_transfer_ticket(ticket):
                    self.reply(handler, 401, {'error': 'Tool link expired'})
                    return True
                body = self.toolrunner_script or '# tool runner unavailable'
                handler._send(200, body, 'text/plain; charset=utf-8', (
                    ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
                    ('X-Content-Type-Options', 'nosniff')))
                return True
            if path in ('/lin', '/mac', '/win') or path.startswith('/console/client/'):
                self.bootstrap(handler, path, urllib.parse.parse_qs(parsed.query))
                return True
            if path == '/console/register' and handler.command == 'POST':
                self.register(handler)
                return True
            parts = path.strip('/').split('/')
            if path == '/console/proxy' and handler.command in ('GET', 'POST'):
                if handler.command == 'POST':
                    self.set_proxy_session(self.body(handler).get('session') or '')
                self.reply(handler, 200, self.proxy_info())
                return True
            if path == '/console/callbacks' and handler.command == 'GET':
                with self.condition:
                    self.reply(handler, 200, {'callbacks': [
                        self.callback_info(callback) for callback in self.callbacks.values()]})
                return True
            if path == '/console/callbacks' and handler.command == 'POST':
                data = self.body(handler)
                local = int(data.get('local') or 0)
                self.reply(handler, 200, self.add_callback(
                    local, int(data.get('remote') or local)))
                return True
            if (len(parts) == 4 and parts[:2] == ['console', 'callbacks']
                    and parts[3] == 'remove' and handler.command == 'POST'):
                self.remove_callback(parts[2])
                self.reply(handler, 200, {'ok': True})
                return True
            if len(parts) == 6 and parts[:2] == ['console', 'agent'] and parts[3] == 'callback':
                if not self.set_callback_state(parts[2], parts[4], self.body(handler)):
                    self.reply(handler, 404, {'error': 'Callback not found'})
                else:
                    self.reply(handler, 200, {'ok': True})
                return True
            if len(parts) == 6 and parts[:2] == ['console', 'agent'] and parts[3] == 'net':
                self.net_agent(handler, parts[2], parts[4], parts[5])
                return True
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
            nonce = str(data.get('nonce', ''))[:64]
            recent = self.registrations.get(ticket)
            if nonce and recent and recent['nonce'] == nonce and recent['expires'] > time.time():
                self.reply(handler, 200, {'id': recent['id'], 'token': recent['token']})
                return
            invite = self.invites.get(ticket)
            if not invite or invite['expires'] <= time.time():
                self.reply(handler, 401, {'error': 'Connection link expired or already used'}); return
            if len(self.sessions) >= 32:
                stale = sorted((s for s in self.sessions.values()
                                if time.time() - s['seen'] > 600),
                               key=lambda s: s['seen'])
                if stale:
                    victim = stale[0]
                    self.sessions.pop(victim['id'], None)
                    self._close_net(victim)
                else:
                    self.reply(handler, 429, {'error': 'Session limit reached'}); return
            ident, token = secrets.token_urlsafe(16), secrets.token_urlsafe(32)
            host = str(data.get('host', 'client'))[:100]
            session = {'id': ident, 'token': token, 'host': host,
                       'os': str(data.get('os', ''))[:20], 'arch': str(data.get('arch', ''))[:20],
                       'ip': self.request_ip(handler),
                       'connected': True, 'seen': time.time(), 'events': [], 'seq': 0,
                       'output': bytearray(), 'offset': 0, 'input_size': 0,
                       'net_seq': 0, 'net_events': [], 'net_streams': {}}
            self.sessions[ident] = session
            self.registrations[ticket] = {'nonce': nonce, 'id': ident, 'token': token,
                                          'expires': time.time() + 600}
            del self.invites[ticket]
            for callback in self.callbacks.values():
                if not callback['session'] or callback['session'] not in self.sessions:
                    self._bind_callback_locked(callback, session)
            self.reply(handler, 200, {'id': ident, 'token': token})
            self.event('CONNECTOR', f"{host} joined ({session['os']}/{session['arch']})",
                       session['ip'])
            self.condition.notify_all()

    def agent(self, handler, ident, action, query):
        with self.condition:
            session = self.sessions.get(ident)
            if not session or not self.authorized(handler, session['token']):
                handler.close_connection = True
                self.reply(handler, 401, {'error': 'Invalid session'}); return
            if not session['connected']:
                self.reply(handler, 410, {'error': 'Session closed'}); return
            self.touch(session)
        if action == 'input' and handler.command == 'GET':
            cursor = int(query.get('after', ['0'])[0])
            with self.condition:
                session['events'] = [e for e in session['events'] if e['seq'] > cursor]
                session['input_size'] = sum(len(e.get('data', '')) for e in session['events'])
                self.condition.wait_for(lambda: session['events'] or not session['connected'], timeout=10)
                self.reply(handler, 200, {'events': session['events'], 'closed': not session['connected']})
        elif action == 'net' and handler.command == 'GET':
            cursor = int(query.get('after', ['0'])[0])
            with self.condition:
                # A cursor only advances after the connector decoded the batch,
                # so it also acknowledges everything up to that point.
                if cursor:
                    session['net_events'] = [e for e in session['net_events'] if e['seq'] > cursor]
                    self.condition.notify_all()
                self.condition.wait_for(lambda: session['net_events'] or not session['connected'],
                                        timeout=10)
                self.reply(handler, 200, {'events': session['net_events'],
                                          'closed': not session['connected']})
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
                self._close_net(session)
                self.event('CONNECTOR', f"{session['host']} disconnected", session.get('ip', ''))
            self.reply(handler, 200, {'ok': True})
        else:
            self.reply(handler, 404, {'error': 'Unknown connector operation'})

    def net_agent(self, handler, ident, sid, action):
        with self.condition:
            session = self.sessions.get(ident)
            if not session or not self.authorized(handler, session['token']):
                handler.close_connection = True
                self.reply(handler, 401, {'error': 'Invalid session'}); return
            if not session['connected']:
                self.reply(handler, 410, {'error': 'Session closed'}); return
            self.touch(session)
            stream = session['net_streams'].get(sid)
            callback = self.callbacks.get(str(self.body(handler).get('callback', ''))) \
                if action == 'inbound' else None
        if action == 'inbound' and handler.command == 'POST':
            if not callback or callback['session'] != ident:
                self.reply(handler, 404, {'error': 'Callback not found'}); return
            full = False
            with self.condition:
                if len(session['net_streams']) >= self.NET_STREAMS:
                    full = True
                else:
                    peer = str(self.body(handler).get('address', ''))[:100]
                    session['net_streams'][sid] = {
                        'open': True, 'closed': False, 'data': bytearray(),
                        'callback': callback['id'], 'peer': peer}
                    self.condition.notify_all()
            if full:
                self.reply(handler, 429, {'error': 'Too many active streams'}); return
            self.reply(handler, 200, {'ok': True})
            self.event('CALLBACK', f"{peer} -> 127.0.0.1:{callback['local']}",
                       self.request_ip(handler))
            threading.Thread(target=self.callback_stream,
                             args=(callback, ident, sid), daemon=True).start()
            return
        if not stream:
            self.reply(handler, 404, {'error': 'Proxy stream not found'}); return
        if action == 'status' and handler.command == 'POST':
            ok = bool(self.body(handler).get('ok'))
            with self.condition:
                stream['open'] = ok
                if not ok:
                    stream['closed'] = True
                self.condition.notify_all()
            self.reply(handler, 200, {'ok': True})
        elif action == 'data' and handler.command == 'POST':
            data = self.body(handler, raw=True)
            error = ''
            deadline = time.time() + 20
            with self.condition:
                while True:
                    if stream['closed']:
                        error = 'closed'
                        break
                    if len(stream['data']) + len(data) <= self.NET_BUFFER:
                        stream['data'].extend(data)
                        self.proxy_stats['received'] += len(data)
                        self.condition.notify_all()
                        break
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        stream['closed'] = True
                        self.condition.notify_all()
                        error = 'full'
                        break
                    self.condition.wait(remaining)
            if error == 'closed':
                self.reply(handler, 410, {'error': 'Proxy stream closed'})
            elif error == 'full':
                self.reply(handler, 413, {'error': 'Proxy buffer full'})
            else:
                self.reply(handler, 200, {'ok': True})
        elif action == 'close' and handler.command == 'POST':
            self.body(handler)
            with self.condition:
                stream['closed'] = True
                self.condition.notify_all()
            self.reply(handler, 200, {'ok': True})
        else:
            self.reply(handler, 404, {'error': 'Unknown proxy operation'})

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
                    self._close_net(session)
                    self.event('CONNECTOR', f"{session['host']} {'removed' if action == 'remove' else 'closed'}",
                               session.get('ip', ''))
                    if action == 'remove':
                        self.sessions.pop(ident, None)
                        session['events'].clear()
                        session['output'].clear()
                        session['input_size'] = 0
                        if self.proxy_session == ident:
                            self.proxy_session = ''
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
for attempt in 1 2 3 4 5 6; do
  if curl --fail --silent --show-error --location {shlex.quote(origin + '/console/client/' + target + '-')}"$arch"{shlex.quote('?ticket=' + ticket)} -o "$work/connector"; then break; fi
  if (( attempt == 6 )); then echo 'Connector download failed' >&2; exit 1; fi
  sleep 5
done
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
  for ($attempt = 0; $attempt -lt 6; $attempt++) {{
    try {{ Invoke-WebRequest -UseBasicParsing -Uri ({quote(origin + '/console/client/windows-')} + $arch + {quote('.exe?ticket=' + ticket)}) -OutFile $file; break }}
    catch {{ if ($attempt -eq 5) {{ throw }}; Start-Sleep -Seconds 5 }}
  }}
  if ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant() -ne $hashes[$arch]) {{ throw 'Connector checksum mismatch' }}
  $env:EXPOSE_URL = {quote(origin)}
  $env:EXPOSE_TICKET = {quote(ticket)}
  & $file
}} finally {{
  Remove-Item Env:EXPOSE_URL, Env:EXPOSE_TICKET -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $file -ErrorAction SilentlyContinue
}}
'''


class SocksProxy:
    """Minimal SOCKS5 CONNECT proxy that dials from the connected machine."""
    def __init__(self, service, bind):
        self.service = service
        self.bind = bind
        self.sock = None
        self.address = ''

    @staticmethod
    def parse_bind(value):
        value = (value or '').strip()
        if value.isdigit():
            return '127.0.0.1', int(value)
        if value.startswith('['):
            host, separator, port = value[1:].partition(']:')
            if not separator or not port.isdigit():
                raise ValueError('Use host:port for the proxy address')
            return host, int(port)
        host, separator, port = value.rpartition(':')
        if not separator:
            raise ValueError('Use host:port for the proxy address')
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid proxy port')
        return host or '127.0.0.1', int(port)

    def start(self):
        host, port = self.parse_bind(self.bind)
        family = socket.AF_INET6 if ':' in host else socket.AF_INET
        listener = socket.socket(family, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(128)
        self.sock = listener
        shown = '127.0.0.1' if host in ('', '0.0.0.0') else host
        self.address = f'socks5://{shown}:{port}'
        threading.Thread(target=self.serve, daemon=True).start()
        return self

    def serve(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(client,), daemon=True).start()

    @staticmethod
    def _read(sock, size):
        data = b''
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError('Client closed the connection')
            data += chunk
        return data

    @staticmethod
    def _reply(client, code):
        client.sendall(struct.pack('!BBBB4sH', 5, code, 0, 1, b'\0\0\0\0', 0))

    def handle(self, client):
        ident = sid = None
        try:
            client.settimeout(15)
            version, count = self._read(client, 2)
            if version != 5:
                return
            methods = self._read(client, count)
            if 0 not in methods:
                client.sendall(b'\x05\xff')
                return
            client.sendall(b'\x05\x00')
            version, command, _, address_type = self._read(client, 4)
            if version != 5 or command != 1:
                self._reply(client, 7)
                return
            if address_type == 1:
                host = socket.inet_ntoa(self._read(client, 4))
            elif address_type == 3:
                host = self._read(client, self._read(client, 1)[0]).decode('utf-8', 'replace')
            elif address_type == 4:
                host = socket.inet_ntop(socket.AF_INET6, self._read(client, 16))
            else:
                self._reply(client, 8)
                return
            port = struct.unpack('!H', self._read(client, 2))[0]
            try:
                ident, sid = self.service.net_open(host, port)
            except (ValueError, OSError):
                self._reply(client, 3)
                return
            self._reply(client, 0)
            client.settimeout(None)

            def upstream():
                try:
                    while True:
                        data = client.recv(32768)
                        if not data:
                            break
                        self.service.net_write(ident, sid, data)
                except (OSError, ValueError):
                    pass
                finally:
                    try:
                        self.service.net_close(ident, sid)
                    except OSError:
                        pass

            threading.Thread(target=upstream, daemon=True).start()
            while True:
                data, closed = self.service.net_read(ident, sid)
                if data:
                    client.sendall(data)
                if closed:
                    break
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass
            if sid:
                try:
                    self.service.net_close(ident, sid)
                except OSError:
                    pass

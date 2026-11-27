"""Authenticated CLI access to existing expose PTYs (Python standard library)."""
import argparse
import base64
import getpass
import hashlib
import http.client
import json
import os
import queue
from pathlib import Path
import secrets
import select
import shutil
import shlex
import signal
import socket
import ssl
import stat
import sys
import tempfile
import termios
import threading
import time
import tty
import urllib.parse
from http.cookies import SimpleCookie

STATE = Path.home() / '.expose'


class OperatorError(Exception):
    pass


class Unauthorized(OperatorError):
    pass


def private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OperatorError('Private credentials must be owned by you and mode 0600.')
        with os.fdopen(fd, 'r', closefd=False) as stream:
            return json.load(stream)
    finally:
        os.close(fd)


def save_private(path, value):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or any(ord(c) < 33 or ord(c) == 127 for c in value)):
        raise OperatorError('Use an HTTPS origin without credentials, path, query, or fragment.')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', '::1', 'localhost'):
        raise OperatorError('Remote operator access requires verified HTTPS; HTTP is allowed only on loopback.')
    _ = parsed.port
    return value.rstrip('/')


def discover(origin=None):
    selected = urllib.parse.urlsplit(origin) if origin else None
    if selected and (selected.scheme != 'http' or selected.hostname not in ('127.0.0.1', '::1', 'localhost')):
        return None
    live = []
    for path in (STATE / 'instances').glob('*.json'):
        try:
            instance = private_json(path)
            os.kill(int(instance['pid']), 0)
            validate_origin(instance['origin'])
            if not origin or (selected.port or 80) == instance['port']:
                live.append(instance)
        except (FileNotFoundError, ProcessLookupError, KeyError, ValueError):
            continue
    if len(live) > 1:
        raise OperatorError('Multiple local instances; select one with --url http://127.0.0.1:PORT.')
    return live[0] if live else None


class API:
    def __init__(self, origin, instance=None):
        self.origin = validate_origin(origin)
        self.parsed = urllib.parse.urlsplit(self.origin)
        self.instance = instance
        self.cookie = ''
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()
        digest = hashlib.sha256(self.origin.encode()).hexdigest()
        self.profile = STATE / 'operator' / (digest + '.json')
        if self.profile.exists():
            saved = private_json(self.profile)
            if saved.get('origin') == self.origin:
                self.cookie = saved.get('cookie', '')

    def close(self):
        with self.lock:
            for connection in self.connections:
                if connection.sock:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                connection.close()

    def request(self, method, path, data=None, form=False):
        connection = getattr(self.local, 'connection', None)
        if connection is None:
            if self.parsed.scheme == 'https':
                connection = http.client.HTTPSConnection(self.parsed.hostname, self.parsed.port,
                                                        timeout=17, context=ssl.create_default_context())
            else:
                connection = http.client.HTTPConnection(self.parsed.hostname, self.parsed.port, timeout=17)
            self.local.connection = connection
            with self.lock:
                self.connections.append(connection)
        headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
        if self.instance:
            headers['X-Expose-Operator'] = self.instance['operator_token']
        if self.cookie:
            headers['Cookie'] = self.cookie
        body = None if data is None else (urllib.parse.urlencode(data) if form else json.dumps(data))
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            content = response.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise OperatorError('Server response exceeds the safety limit.')
            if response.status == 401:
                connection.close()
                raise Unauthorized('Operator credentials expired or were rejected. Run expose login --url ' + self.origin)
            if response.status == 429:
                raise OperatorError('Server is rate limiting requests; wait and reconnect.')
            if response.status == 303 and path not in ('/login', '/logout'):
                raise OperatorError('Unexpected redirect; operator credentials are never forwarded.')
            if response.status not in (200, 303):
                raise OperatorError(f'Server rejected the request (HTTP {response.status}); redirects are never followed.')
            return (json.loads(content) if content else None), response.getheader('Set-Cookie', '')
        except ssl.SSLCertVerificationError:
            connection.close()
            raise OperatorError('HTTPS certificate verification failed; insecure TLS is not supported.')
        except (OSError, http.client.HTTPException):
            connection.close()
            raise

    def json(self, path, data=None):
        return self.request('GET' if data is None else 'POST', path, data)[0]

    def login(self):
        password = os.environ.pop('EXPOSE_AUTH_PASSWORD', '')
        if not password:
            try:
                with open('/dev/tty'):
                    pass
            except OSError:
                raise OperatorError('Login requires an interactive terminal or EXPOSE_AUTH_PASSWORD in the environment.')
            password = getpass.getpass('Expose password: ')
        if not password:
            raise OperatorError('A nonempty password is required.')
        _, header = self.request('POST', '/login', {'password': password}, form=True)
        del password
        jar = SimpleCookie()
        jar.load(header)
        if 'expose_session' not in jar:
            raise OperatorError('The server did not issue an authenticated session.')
        self.cookie = 'expose_session=' + jar['expose_session'].value
        save_private(self.profile, {'origin': self.origin, 'cookie': self.cookie})
        save_private(STATE / 'operator/default.json', {'origin': self.origin})


def choose_session(sessions, selector):
    live = [session for session in sessions if session['connected']]
    if selector:
        if selector.isdigit() and 1 <= int(selector) <= len(live):
            return live[int(selector) - 1]
        matches = [session for session in live if session['id'].startswith(selector)]
        if len(matches) != 1:
            raise OperatorError('Session identifier is missing, closed, or ambiguous. Run expose sessions.')
        return matches[0]
    if len(live) == 1:
        return live[0]
    if not live:
        raise OperatorError('No connected shell sessions. Enroll a connector first.')
    show_sessions(live)
    fd = os.open('/dev/tty', os.O_RDWR)
    try:
        os.write(fd, b'Attach to session number or ID: ')
        selected = os.read(fd, 1024).decode('utf-8', errors='replace').strip()
    finally:
        os.close(fd)
    if not selected:
        raise OperatorError('No session selected; no remote session was changed.')
    return choose_session(live, selected)


def show_sessions(sessions):
    index = 0
    for session in sessions:
        if session['connected']:
            index += 1
        # Connector-controlled labels cannot inject terminal escape sequences.
        clean = lambda value: ''.join(c if c.isprintable() else '?' for c in str(value))
        label = clean(session['host'])
        state = 'closed' if not session['connected'] else ('stale' if session.get('stale') else 'connected')
        number = str(index) if session['connected'] else '-'
        print(f"{number:>2}  {clean(session['id'])}  {state:9}  {label}  {clean(session['os'])}/{clean(session['arch'])}")
    if not sessions:
        print('No shell sessions.')


def attach(api, session):
    if not os.isatty(sys.stdout.fileno()):
        raise OperatorError('Attach requires an interactive terminal.')
    fd = os.open('/dev/tty', os.O_RDWR)
    previous = termios.tcgetattr(fd)
    stop = threading.Event()
    remote_closed = threading.Event()
    resize = threading.Event()
    failures = []
    pending = queue.Queue(maxsize=128)
    prefix = '/console/sessions/' + urllib.parse.quote(session['id'], safe='')

    def input_request(action, value):
        value['request_id'] = secrets.token_urlsafe(24)
        deadline = time.monotonic() + 20
        delay = .2
        while not stop.is_set():
            try:
                acknowledgement = api.json(prefix + '/' + action, value)
                if not isinstance(acknowledgement, dict) or not acknowledgement.get('ok'):
                    raise OperatorError('Invalid input acknowledgement; detached safely.')
                return
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise OperatorError('Connection interrupted; detached safely. Reattach when the server is reachable.')
                stop.wait(delay); delay = min(delay * 2, 2)

    def writer():
        while not stop.is_set():
            try:
                action, value = pending.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                input_request(action, value)
            except (OperatorError, ValueError, KeyError) as error:
                failures.append(error); stop.set()

    def enqueue(action, value):
        try:
            pending.put_nowait((action, value))
        except queue.Full:
            raise OperatorError('Input queue is full; detached without closing the remote shell.')

    def output():
        cursor = max(session.get('output_start', 0), session.get('output_end', 0) - 65536)
        delay = .2
        while not stop.is_set():
            try:
                reply = api.json(prefix + '/output?after=' + str(cursor))
                data = base64.b64decode(reply['data'], validate=True)
                while data and not stop.is_set():
                    written = os.write(fd, data)
                    data = data[written:]
                cursor = reply['next']
                delay = .2
                if not reply['connected']:
                    remote_closed.set()
                    stop.set()
            except (OSError, http.client.HTTPException):
                stop.wait(delay); delay = min(delay * 2, 2)
            except (OperatorError, ValueError, KeyError) as error:
                failures.append(error); stop.set()

    old_handlers = {}
    thread = None
    try:
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            old_handlers[number] = signal.signal(number, lambda *_: stop.set())
        old_handlers[signal.SIGWINCH] = signal.signal(signal.SIGWINCH, lambda *_: resize.set())
        print('Attached to ' + session['id'] + '. Ctrl+] detaches; Ctrl+C interrupts the remote command.', file=sys.stderr)
        tty.setraw(fd)
        resize.set()
        thread = threading.Thread(target=output, daemon=True)
        thread.start()
        threading.Thread(target=writer, daemon=True).start()
        while not stop.is_set():
            if resize.is_set():
                resize.clear()
                size = os.get_terminal_size(fd)
                enqueue('resize', {'cols': max(2, min(500, size.columns)),
                                         'rows': max(2, min(200, size.lines))})
            if select.select([fd], [], [], .1)[0]:
                data = os.read(fd, 4096)
                if not data:
                    break
                if b'\x1d' in data:
                    before = data.split(b'\x1d', 1)[0]
                    if before:
                        enqueue('input', {'data_b64': base64.b64encode(before).decode()})
                    break
                enqueue('input', {'data_b64': base64.b64encode(data).decode()})
    finally:
        stop.set()
        termios.tcsetattr(fd, termios.TCSAFLUSH, previous)
        api.close()
        if thread:
            thread.join(timeout=1)
        # Leave the local terminal usable after detaching from vim/htop too.
        os.write(fd, b'\x1b[?2004l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l'
                     b'\x1b[?1049l\x1b[?25h\x1b[0m\x1b]8;;\x1b\\')
        os.close(fd)
        for number, handler in old_handlers.items():
            signal.signal(number, handler)
        print('\nRemote shell ended.' if remote_closed.is_set() else
              '\nCLI detached. Use expose attach to reconnect.', file=sys.stderr)
    if failures:
        raise failures[0]


def main():
    parser = argparse.ArgumentParser(prog='expose', description='Manage existing shell sessions; attach never starts or stops a server.')
    parser.add_argument('command', choices=('sessions', 'attach', 'login', 'logout', 'invite', 'proxychains'))
    parser.add_argument('--url', help='instance origin; remote access requires HTTPS')
    parser.add_argument('--json', action='store_true', help='session metadata as JSON')
    parser.add_argument('--origin', help='HTTPS public origin for a new connector invitation')
    argv = sys.argv[1:]
    passthrough = []
    if argv and argv[0] == 'proxychains':
        boundary = 3 if len(argv) > 2 and argv[1] == '--url' else 1
        passthrough = argv[boundary:]
        if passthrough and passthrough[0] == '--':
            passthrough = passthrough[1:]
        argv = argv[:boundary]
    args, extra = parser.parse_known_args(argv)
    extra += passthrough
    if args.command != 'proxychains' and len(extra) > (1 if args.command in ('attach', 'invite') else 0):
        parser.error('Unexpected arguments')
    if any(value.startswith('-') for value in extra) and args.command != 'proxychains':
        parser.error('Unknown option')
    origin = validate_origin(args.url) if args.url else None
    instance = discover(origin)
    if not origin and instance:
        origin = instance['origin']
    if not origin and (STATE / 'operator/default.json').exists():
        origin = private_json(STATE / 'operator/default.json')['origin']
    if not origin:
        raise OperatorError('No running local instance. Use --url https://YOUR-SERVER for remote access.')
    api = API(origin, instance)
    try:
        if args.command == 'login':
            api.login(); print('Authenticated; private session credentials saved.'); return
        if args.command == 'logout':
            if api.cookie:
                api.request('POST', '/logout', {})
            api.profile.unlink(missing_ok=True)
            print('Saved browser/CLI login revoked. Local instance keys remain available to their owner.'); return
        if args.command == 'proxychains':
            if not instance or not instance.get('proxy_config'):
                raise OperatorError('Proxychains requires a running local instance with --proxy enabled.')
            if not extra:
                raise OperatorError('Usage: expose proxychains COMMAND [ARGUMENTS...]')
            path = Path(instance['proxy_config'])
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or path.is_symlink():
                raise OperatorError('Proxychains credentials must be private and owned by you.')
            binary = shutil.which('proxychains4')
            if not binary:
                raise OperatorError('Install proxychains-ng first.')
            api.close()
            os.environ.pop('EXPOSE_AUTH_PASSWORD', None)
            original_stdin = os.environ.pop('EXPOSE_OPERATOR_STDIN_FD', None)
            if original_stdin is not None:
                os.dup2(int(original_stdin), 0)
                os.close(int(original_stdin))
            os.execv(binary, [binary, '-q', '-f', str(path), *extra])
        try:
            sessions = api.json('/console/sessions')
        except Unauthorized:
            if instance:
                raise
            api.login()
            sessions = api.json('/console/sessions')
        fields = {'id', 'host', 'os', 'arch', 'connected'}
        if (not isinstance(sessions, list)
                or any(not isinstance(item, dict) or not fields <= item.keys() for item in sessions)):
            raise OperatorError('The server returned invalid session metadata.')
        if args.command == 'invite':
            platform = extra[0] if extra else 'linux'
            if platform not in ('linux', 'mac', 'win'):
                raise OperatorError('Choose invite linux, mac, or win.')
            public = validate_origin(args.origin or (instance or {}).get('public_origin') or api.origin)
            invite = api.json('/console/invites', {'origin': public})
            endpoint = {'linux': '/lin', 'mac': '/mac', 'win': '/win'}[platform]
            link = public + endpoint + '?ticket=' + invite['ticket']
            print('Single-use connector invitation; expires in 10 minutes. Treat this command as a credential.', file=sys.stderr)
            if platform == 'win':
                print("iex (Invoke-WebRequest -UseBasicParsing '" + link.replace("'", "''") + "').Content")
            else:
                protocol = '=https' if public.startswith('https:') else '=http,https'
                print('curl --fail --silent --show-error --max-time 30 --proto ' + shlex.quote(protocol) +
                      ' ' + shlex.quote(link) + ' | bash')
            return
        if args.command == 'sessions':
            if args.json:
                print(json.dumps(sessions))
            else:
                show_sessions(sessions)
        else:
            if not api.json('/console/status').get('cli_attach'):
                raise OperatorError('This running server predates CLI attach. Restart it with the updated expose when its sessions can end.')
            attach(api, choose_session(sessions, extra[0] if extra else None))
    finally:
        api.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled.', file=sys.stderr)
        sys.exit(130)
    except (OperatorError, OSError, ValueError, EOFError, http.client.HTTPException) as error:
        # HTTP libraries can include URLs in errors; never include credentials or responses.
        message = str(error) if isinstance(error, OperatorError) else 'Connection or local credential access failed.'
        print('expose: ' + message, file=sys.stderr)
        sys.exit(1)

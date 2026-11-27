"""Real PTY, operator authorization, and isolated playground integration tests."""
import base64
import fcntl
import http.client
import http.server
import json
import os
from pathlib import Path
import pty
import re
import runpy
import secrets
import select
import shutil
import signal
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Harness:
    def __init__(self, home=None, public_directory=False):
        self.temporary = tempfile.TemporaryDirectory(prefix='expose-cli-') if home is None else None
        self.home = Path(self.temporary.name if self.temporary else home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.port, self.proxy_port = free_port(), free_port()
        self.origin = f'http://127.0.0.1:{self.port}'
        self.password = secrets.token_urlsafe(32)
        self.public_directory = public_directory
        self.env = {'HOME': str(self.home), 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.defpath, 'LANG': 'C.UTF-8',
                    'SHELL': '/bin/bash', 'TERM': 'xterm-256color'}
        self.log = open(self.home / 'server.log', 'wb')
        self.connector = None

    def start(self):
        env = dict(self.env, EXPOSE_AUTH_PASSWORD='' if self.public_directory else self.password,
                   EXPOSE_CLIENT_DIR=str(ROOT / 'dist/console-clients'), EXPOSE_CONSOLES='1',
                   EXPOSE_PROXY=f'127.0.0.1:{self.proxy_port}')
        self.server = subprocess.Popen([str(ROOT / 'dist/expose'), '--bind', '127.0.0.1',
                                        '-p', str(self.port), '.' if self.public_directory else 'playground'], env=env, cwd=self.home,
                                       stdout=self.log, stderr=self.log, start_new_session=True)
        descriptor = self.home / '.expose/instances' / f'{self.port}.json'
        for _ in range(100):
            if descriptor.exists():
                self.instance = json.loads(descriptor.read_text())
                if self.call('/console/sessions')[0] == 200:
                    return self
            if self.server.poll() is not None:
                raise RuntimeError('Fixture server failed to start')
            time.sleep(.05)
        raise RuntimeError('Fixture server startup timed out')

    def call(self, path, data=None, operator=True, token=None, headers=None):
        values = {'Content-Type': 'application/json'}
        if operator:
            values['X-Expose-Operator'] = self.instance['operator_token']
        if token is not None:
            values['Authorization'] = 'Bearer ' + token
        values.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        try:
            conn.request('GET' if data is None else 'POST', path,
                         None if data is None else json.dumps(data), values)
            response = conn.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            conn.close()

    def enroll(self):
        code, invite = self.call('/console/invites', {'origin': self.origin})
        if code != 200:
            raise RuntimeError('Could not create fixture enrollment')
        endpoint = self.home / 'endpoint'
        endpoint.mkdir(exist_ok=True)
        env = dict(self.env, HOME=str(endpoint), EXPOSE_URL=self.origin, EXPOSE_TICKET=invite['ticket'])
        # Exercise the actual ticket-protected bootstrap and checksum download.
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            connection.request('GET', '/lin?ticket=' + invite['ticket'])
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError('Fixture bootstrap was rejected')
            script = response.read()
        finally:
            connection.close()
        self.connector = subprocess.Popen(['/bin/bash'], env=env, stdin=subprocess.PIPE,
                                          stdout=self.log, stderr=self.log, start_new_session=True)
        self.connector.stdin.write(script)
        self.connector.stdin.close()
        for _ in range(100):
            sessions = self.call('/console/sessions')[1]
            live = [session for session in sessions if session['connected']]
            if live:
                self.session = live[-1]
                return self.session
            if self.connector.poll() is not None:
                raise RuntimeError('Fixture connector failed')
            time.sleep(.05)
        raise RuntimeError('Connector registration timed out')

    def cli(self, *args, env=None):
        return subprocess.run([str(ROOT / 'dist/expose'), *args], env=env or self.env,
                              capture_output=True, timeout=25)

    def stop(self):
        for process in (self.connector, getattr(self, 'server', None)):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
        self.log.close()
        if self.temporary:
            self.temporary.cleanup()


class Attachment:
    def __init__(self, harness, origin=None, select_session=True):
        self.master, self.slave = pty.openpty()
        self.previous = termios.tcgetattr(self.slave)
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', 31, 105, 0, 0))

        def terminal_session():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        command = [str(ROOT / 'dist/expose'), 'attach']
        if select_session:
            command.append(harness.session['id'])
        env = harness.env
        if origin:
            command += ['--url', origin]
            env = dict(env, EXPOSE_AUTH_PASSWORD=harness.password)
        self.process = subprocess.Popen(command,
                                        env=env, stdin=self.slave, stdout=self.slave,
                                        stderr=self.slave, preexec_fn=terminal_session)
        self.data = b''

    def wait_for(self, expected, timeout=12):
        end = time.monotonic() + timeout
        while expected not in self.data and time.monotonic() < end:
            if select.select([self.master], [], [], .1)[0]:
                self.data += os.read(self.master, 65536)
            if self.process.poll() is not None:
                break
        if expected not in self.data:
            raise AssertionError('Expected controlled terminal marker did not arrive')

    def send(self, data):
        os.write(self.master, data)

    def detach(self):
        self.send(b'\x1d')
        code = self.process.wait(timeout=5)
        if code != 0:
            raise AssertionError('CLI attachment failed during detach')
        restored = termios.tcgetattr(self.slave)
        if restored != self.previous:
            raise AssertionError('Local terminal attributes were not restored')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
        os.close(self.master); os.close(self.slave)


@unittest.skipUnless((ROOT / 'dist/console-clients/linux-amd64').exists()
                     and sys.platform == 'linux' and os.uname().machine == 'x86_64',
                     'Build the Linux amd64 console connector first')
class OperatorIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness()
        try:
            cls.h.start()
            cls.h.enroll()
        except Exception:
            cls.h.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.h.stop()

    def test_attach_detach_preserves_shell_resize_interrupt_and_utf8(self):
        first = Attachment(self.h)
        try:
            first.wait_for(b'Attached to ')
            first.send(b"export CLI_PERSIST=retained; cd /tmp; printf 'FIRST_'; printf 'READY\\n'; printf 'PID_'; printf '%s\\n' $$\r")
            first.wait_for(b'FIRST_READY\r\n')
            first.wait_for(b'PID_')
            time.sleep(.1)
            # Drain the complete PID response before detaching.
            if select.select([first.master], [], [], .2)[0]:
                first.data += os.read(first.master, 65536)
            pid = re.findall(rb'PID_(\d+)\r\n', first.data)[-1]
            first.detach()
        finally:
            first.close()
        self.assertIsNone(self.h.connector.poll())
        second = Attachment(self.h)
        try:
            second.wait_for(b'Attached to ')
            second.send(b"printf 'PERSIST_'; printf '%s\\n' \"$CLI_PERSIST\"; printf 'PID_'; printf '%s\\n' $$; printf 'CWD_'; pwd\r")
            second.wait_for(b'PERSIST_retained\r\n')
            second.wait_for(b'CWD_/tmp\r\n')
            second.wait_for(b'PID_' + pid + b'\r\n')
            fcntl.ioctl(second.master, termios.TIOCSWINSZ, struct.pack('HHHH', 43, 119, 0, 0))
            os.kill(second.process.pid, signal.SIGWINCH)
            time.sleep(.25)
            second.send(b"printf 'SIZE_'; stty size\r")
            second.wait_for(b'SIZE_43 119\r\n')
            second.send(b'sleep 30\r')
            time.sleep(.2); second.send(b'\x03'); time.sleep(.2)
            second.send(b"printf 'INT_'; printf 'OK\\n'\r")
            second.wait_for(b'INT_OK\r\n')
            second.send(b"printf 'UTF_'; printf '\xc3")
            time.sleep(.1); second.send(b"\xa9\\n'\r")
            second.wait_for(b'UTF_\xc3\xa9\r\n')
            second.detach()
        finally:
            second.close()
        self.assertIsNone(self.h.connector.poll())
        result = self.h.cli('sessions', '--json')
        self.assertEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)[0]['connected'])

    def test_operator_and_agent_credentials_cannot_cross_roles(self):
        sid = self.h.session['id']
        for path, body in [('/console/sessions', None), ('/console/invites', {'origin': self.h.origin}),
                           ('/console/proxy', None), ('/console/callbacks', None),
                           (f'/console/sessions/{sid}/input', {'data': 'must not execute'})]:
            self.assertEqual(self.h.call(path, body, operator=False)[0], 401)
            self.assertEqual(self.h.call(path, body, operator=False, token=secrets.token_urlsafe())[0], 401)
        _, invitation = self.h.call('/console/invites', {'origin': self.h.origin})
        _, agent = self.h.call('/console/register', {'host': 'isolated-agent'}, operator=False,
                              token=invitation['ticket'])
        self.assertEqual(self.h.call('/console/sessions', operator=False, token=agent['token'])[0], 401)
        self.assertEqual(self.h.call(f'/console/agent/{sid}/output', {}, operator=False, token=agent['token'])[0], 401)
        self.assertEqual(self.h.call('/console/register', {}, operator=False, token=invitation['ticket'])[0], 401)
        _, callback = self.h.call('/console/callbacks', {'local': free_port(), 'remote': free_port()})
        route = f'/console/agent/{sid}/callback/{callback["id"]}/state'
        self.assertEqual(self.h.call(route, {'active': True}, operator=False)[0], 401)
        self.assertEqual(self.h.call(route, {'active': True}, operator=False, token=agent['token'])[0], 401)
        self.assertEqual(self.h.call('/console/sessions', headers={'X-Forwarded-For': '203.0.113.1'})[0], 401)
        self.assertEqual(self.h.call('/console/sessions', headers={'Origin': 'https://example.invalid'})[0], 401)
        self.h.call('/console/callbacks/' + callback['id'] + '/remove', {})
        self.h.call('/console/sessions/' + agent['id'] + '/remove', {})

    def test_input_retry_is_deduplicated(self):
        path = '/console/sessions/' + self.h.session['id'] + '/input'
        request = {'data_b64': base64.b64encode(b'# retry test\r').decode(), 'request_id': secrets.token_urlsafe(24)}
        self.assertEqual(self.h.call(path, request)[0], 200)
        code, reply = self.h.call(path, request)
        self.assertEqual(code, 200)
        self.assertTrue(reply['duplicate'])

    def test_interactive_selection_with_multiple_sessions(self):
        _, invite = self.h.call('/console/invites', {'origin': self.h.origin})
        _, other = self.h.call('/console/register', {'host': 'selection-fixture'},
                               operator=False, token=invite['ticket'])
        attachment = Attachment(self.h, select_session=False)
        try:
            attachment.wait_for(b'Attach to session number or ID: ')
            attachment.send(b'1\n')
            attachment.wait_for(b'Attached to ')
            attachment.send(b"printf 'SELECT_'; printf 'OK\\n'\r")
            attachment.wait_for(b'SELECT_OK\r\n')
            attachment.detach()
        finally:
            attachment.close()
            self.h.call('/console/sessions/' + other['id'] + '/remove', {})

    def test_lost_input_ack_does_not_execute_the_command_twice(self):
        target = self.h.port
        dropped = threading.Event()

        class FaultProxy(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass
            def forward(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                upstream = http.client.HTTPConnection('127.0.0.1', target, timeout=15)
                try:
                    upstream.request(self.command, self.path, body, dict(self.headers))
                    response = upstream.getresponse()
                    payload = response.read()
                    lose_ack = False
                    if self.path.endswith('/input') and not dropped.is_set():
                        data = json.loads(body)
                        decoded = base64.b64decode(data.get('data_b64', ''))
                        lose_ack = b'CLI_N=$((CLI_N+1))' in decoded
                    if lose_ack and response.status == 200:
                        dropped.set()
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    self.send_response(response.status)
                    self.send_header('Content-Length', str(len(payload)))
                    for name, value in response.getheaders():
                        if name.lower() == 'set-cookie':
                            self.send_header(name, value)
                    try:
                        self.end_headers(); self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # A detached CLI deliberately closes its long poll.
                finally:
                    upstream.close()
            do_GET = forward
            do_POST = forward
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), FaultProxy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        attachment = Attachment(self.h, f'http://127.0.0.1:{server.server_address[1]}')
        try:
            attachment.wait_for(b'Attached to ')
            attachment.send(b"CLI_N=0; printf 'INIT_'; printf 'DONE\\n'\r")
            attachment.wait_for(b'INIT_DONE\r\n')
            attachment.send(b"CLI_N=$((CLI_N+1)); printf 'COUNT_'; printf '%s\\n' \"$CLI_N\"\r")
            attachment.wait_for(b'COUNT_1\r\n')
            self.assertTrue(dropped.wait(timeout=2))
            time.sleep(.5)
            attachment.send(b"printf 'FINAL_'; printf '%s\\n' \"$CLI_N\"\r")
            attachment.wait_for(b'FINAL_1\r\n')
            attachment.detach()
        finally:
            attachment.close()
            server.shutdown(); server.server_close()

    def test_terminating_the_cli_preserves_the_connector(self):
        attachment = Attachment(self.h)
        try:
            attachment.wait_for(b'Attached to ')
            attachment.process.terminate()
            self.assertEqual(attachment.process.wait(timeout=5), 0)
            self.assertEqual(termios.tcgetattr(attachment.slave), attachment.previous)
            self.assertIsNone(self.h.connector.poll())
        finally:
            attachment.close()

    def test_plaintext_remote_origins_are_rejected(self):
        for origin in ('http://example.invalid', 'https://user:pass@example.invalid', 'https://example.invalid/path'):
            result = self.h.cli('sessions', '--url', origin)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.h.call('/console/invites', {'origin': 'http://example.invalid'})[0], 400)

    def test_private_runtime_credentials_and_logs(self):
        descriptor = self.h.home / '.expose/instances' / f'{self.h.port}.json'
        self.assertEqual(descriptor.stat().st_mode & 0o777, 0o600)
        self.assertEqual(descriptor.parent.stat().st_mode & 0o777, 0o700)
        for path in (self.h.home / 'server.log', self.h.home / '.expose/requests.json'):
            content = path.read_bytes()
            self.assertFalse(self.h.password.encode() in content, 'Password appeared in logs')
            self.assertFalse(self.h.instance['operator_token'].encode() in content, 'Operator token appeared in logs')

    @unittest.skipUnless(shutil.which('openssl'), 'OpenSSL is required for the local TLS fixture')
    def test_remote_login_requires_verified_tls_and_logout_revokes_cookie(self):
        with tempfile.TemporaryDirectory(prefix='expose-tls-') as directory:
            base = Path(directory)
            cert, key = base / 'cert.pem', base / 'private.key'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-noenc',
                            '-days', '1', '-subj', '/CN=localhost',
                            '-addext', 'subjectAltName=DNS:localhost',
                            '-addext', 'basicConstraints=critical,CA:TRUE',
                            '-addext', 'keyUsage=critical,digitalSignature,keyCertSign,keyEncipherment',
                            '-keyout', str(key), '-out', str(cert)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            key.chmod(0o600)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            target = self.h.port

            class Relay(socketserver.BaseRequestHandler):
                def handle(self):
                    upstream = socket.create_connection(('127.0.0.1', target), timeout=20)
                    def pump(source, destination):
                        try:
                            while True:
                                data = source.recv(65536)
                                if not data:
                                    break
                                destination.sendall(data)
                        except OSError:
                            pass
                        finally:
                            for sock in (source, destination):
                                try:
                                    sock.shutdown(socket.SHUT_RDWR)
                                except OSError:
                                    pass
                    thread = threading.Thread(target=pump, args=(self.request, upstream), daemon=True)
                    thread.start()
                    try:
                        pump(upstream, self.request)
                    finally:
                        upstream.close()

            class TLS(socketserver.ThreadingTCPServer):
                daemon_threads = True
                def get_request(self):
                    sock, address = super().get_request()
                    try:
                        return context.wrap_socket(sock, server_side=True), address
                    except Exception:
                        sock.close()
                        raise
            relay = TLS(('127.0.0.1', 0), Relay)
            threading.Thread(target=relay.serve_forever, daemon=True).start()
            try:
                origin = f'https://localhost:{relay.server_address[1]}'
                home = base / 'remote-operator'
                home.mkdir()
                env = dict(self.h.env, HOME=str(home), EXPOSE_AUTH_PASSWORD=self.h.password)
                rejected = self.h.cli('sessions', '--url', origin, '--json', env=env)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(b'certificate verification failed', rejected.stderr)
                env['SSL_CERT_FILE'] = str(cert)
                accepted = self.h.cli('sessions', '--url', origin, '--json', env=env)
                reason = accepted.stderr.replace(self.h.password.encode(), b'[redacted]')
                self.assertEqual(accepted.returncode, 0, reason.decode(errors='replace'))
                self.assertTrue(json.loads(accepted.stdout))
                profiles = [p for p in (home / '.expose/operator').glob('*.json') if p.name != 'default.json']
                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0].stat().st_mode & 0o777, 0o600)
                cookie = json.loads(profiles[0].read_text())['cookie']
                env.pop('EXPOSE_AUTH_PASSWORD')
                self.assertEqual(self.h.cli('sessions', '--url', origin, '--json', env=env).returncode, 0)
                connection = http.client.HTTPConnection('127.0.0.1', self.h.port, timeout=10)
                connection.request('GET', '/content', headers={'Cookie': cookie})
                response = connection.getresponse(); response.read(); connection.close()
                for path in (self.h.home / 'server.log', self.h.home / '.expose/requests.json'):
                    self.assertFalse(cookie.partition('=')[2].encode() in path.read_bytes(), 'Session cookie leaked to logs')
                self.assertEqual(self.h.cli('logout', '--url', origin, env=env).returncode, 0)
                self.assertEqual(self.h.call('/console/sessions', operator=False, headers={'Cookie': cookie})[0], 401)
            finally:
                relay.shutdown(); relay.server_close()

    @unittest.skipUnless(shutil.which('proxychains4'), 'proxychains-ng is required')
    def test_proxychains_stays_usable_after_cli_detach(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                data = self.request.recv(64)
                self.request.sendall(data)
        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        server = Server(('127.0.0.1', 0), Echo)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = self.h.cli('proxychains', 'python3', '-c',
                                'import socket; s=socket.create_connection(("127.0.0.1",' + str(server.server_address[1]) +
                                ')); s.sendall(b"PROXY_OK"); assert s.recv(64)==b"PROXY_OK"; print("proxy ok")')
            self.assertEqual(result.returncode, 0, 'Controlled proxychains probe failed')
            self.assertIn(b'proxy ok', result.stdout)
        finally:
            server.shutdown(); server.server_close()

    @unittest.skipUnless(shutil.which('proxychains4'), 'proxychains-ng is required')
    def test_proxychains_preserves_command_stdin(self):
        result = subprocess.run([str(ROOT / 'dist/expose'), 'proxychains', 'python3', '-c',
                                 'import sys; print(sys.stdin.read())'], input=b'PIPE_OK',
                                env=self.h.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'PIPE_OK\n')


class SecurityUnits(unittest.TestCase):
    def test_public_directory_cannot_leak_operator_credentials(self):
        harness = Harness(public_directory=True)
        try:
            harness.start()
            (harness.home / 'safe.txt').write_text('public fixture')
            (harness.home / '.hidden.txt').write_text('private fixture')
            descriptor = harness.home / '.expose/instances' / f'{harness.port}.json'
            (harness.home / 'alias.json').symlink_to(descriptor)
            (harness.home / 'escape').symlink_to('/etc/hostname')

            def request(path, method='GET'):
                connection = http.client.HTTPConnection('127.0.0.1', harness.port, timeout=10)
                try:
                    connection.request(method, path)
                    response = connection.getresponse()
                    body = response.read()
                    self.assertFalse(harness.instance['operator_token'].encode() in body, 'Instance key was exposed')
                    return response.status, body
                finally:
                    connection.close()
            self.assertEqual(request('/safe.txt')[0], 200)
            for path in ('/.hidden.txt', '/%2eexpose/instances/' + str(harness.port) + '.json',
                         '/alias.json', '/escape', '/ls/.expose', '/ls/.expose/instances'):
                self.assertEqual(request(path)[0], 403)
                self.assertEqual(request(path, 'HEAD')[0], 403)
            status, listing = request('/ls')
            self.assertEqual(status, 200)
            self.assertNotIn(b'.expose', listing)
            self.assertNotIn(b'alias.json', listing)
            self.assertEqual(request('/console/sessions')[0], 401)
            self.assertEqual(request('/console/tools/prohibited', 'POST')[0], 401)
            status, public_status = request('/console/status')
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(public_status)['enabled'])
        finally:
            harness.stop()

    def test_expired_ticket_and_public_socks_bind_are_rejected(self):
        module = runpy.run_path(str(ROOT / 'src/assets/consoles.py'))
        service = module['ConsoleService'](True, '')
        ticket = secrets.token_urlsafe()
        service.invites[ticket] = {'origin': 'https://example.invalid', 'expires': time.time() - 1}
        service.prune()
        self.assertNotIn(ticket, service.invites)
        with self.assertRaises(ValueError):
            module['SocksProxy'](service, '0.0.0.0:1080').start()


def playground():
    home = Path(os.environ['HOME'])
    harness = Harness(home).start()
    harness.enroll()
    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'PLAYGROUND_PROXY_OK\n'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *_):
            pass
    target = http.server.ThreadingHTTPServer(('127.0.0.1', 8000), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    print('Playground ready. Use expose sessions / expose attach inside this container.', flush=True)
    try:
        stopped.wait()
    finally:
        target.shutdown(); target.server_close()
        harness.stop()


if __name__ == '__main__':
    if '--playground' in sys.argv:
        playground()
    else:
        unittest.main(verbosity=2)

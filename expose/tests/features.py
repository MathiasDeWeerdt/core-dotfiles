"""Exercise attachment safety, authorization, and a real Linux PTY callback."""
import base64
import http.cookiejar
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='expose-features-')
        cls.home = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.proxy_port = sock.getsockname()[1]
        cls.origin = f'http://127.0.0.1:{cls.port}'
        env = dict(os.environ, HOME=str(cls.home), EXPOSE_CLIENT_DIR=str(ROOT/'dist/console-clients'), EXPOSE_CONSOLES='1', EXPOSE_PROXY=f'127.0.0.1:{cls.proxy_port}')
        cls.log = open(cls.home/'server.log', 'wb')
        cls.server = subprocess.Popen([str(ROOT/'dist/expose'), '--bind', '127.0.0.1',
                                      '-p', str(cls.port), 'hello'],
                                     env=env, stdout=cls.log, stderr=cls.log, start_new_session=True)
        for _ in range(100):
            try:
                cls.call('/console/status'); break
            except OSError:
                pass
            time.sleep(.05)
        else:
            raise RuntimeError('Server did not start')

    @classmethod
    def tearDownClass(cls):
        os.killpg(cls.server.pid, signal.SIGTERM)
        try: cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(cls.server.pid, signal.SIGKILL); cls.server.wait()
        cls.log.close(); cls.temp.cleanup()

    @classmethod
    def call(cls, path, data=None, token=None, content_type=None):
        headers = {}
        if isinstance(data, dict):
            data=json.dumps(data).encode(); headers['Content-Type']='application/json'
        if isinstance(data,str): data=data.encode()
        if token: headers['Authorization']='Bearer '+token
        if content_type: headers['Content-Type']=content_type
        req=urllib.request.Request(cls.origin+path,data=data,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=15) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as response:
            with response:
                return response.code, response.headers, response.read()

    @classmethod
    def json(cls, path, data=None, token=None):
        status,_,body=cls.call(path,data,token)
        return status,json.loads(body)

    def upload(self, name, body, message='Shared from chat'):
        boundary='expose-test-boundary'
        raw=(f'--{boundary}\r\nContent-Disposition: form-data; name="message"\r\n\r\n{message}\r\n'
             f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
             'Content-Type: application/octet-stream\r\n\r\n').encode()+body+f'\r\n--{boundary}--\r\n'.encode()
        return self.call('/chat/upload',raw,content_type='multipart/form-data; boundary='+boundary)

    def test_terminal_tab_route(self):
        status, headers, page = self.call('/?terminal=test-session')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn(b'id="console-popout"', page)
        self.assertIn(b'id="terminal-tab-title"', page)

    def test_chat_attachments_and_safe_previews(self):
        code,_,body=self.upload('notes.txt',b'hello <script>alert(1)</script>')
        self.assertEqual(code,200)
        name=json.loads(body)['files'][0]['name']
        messages=self.json('/chat')[1]
        self.assertEqual(messages[-1]['files'][0]['kind'],'text')
        self.assertEqual(messages[-1]['msg'],'Shared from chat')
        code,headers,data=self.call('/upload/preview/'+name)
        self.assertEqual(code,200); self.assertTrue(headers['Content-Type'].startswith('text/plain'))
        self.assertIn('sandbox',headers['Content-Security-Policy'])
        self.assertEqual(data,b'hello <script>alert(1)</script>')
        _,headers,data=self.call('/upload/files/'+name)
        self.assertTrue(headers['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        _,_,body=self.upload('image.png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf1kAAAAASUVORK5CYII='),'')
        image=json.loads(body)['files'][0]
        self.assertEqual(image['kind'],'image')
        self.assertTrue(self.call('/upload/preview/'+image['name'])[1]['Content-Disposition'].startswith('inline;'))
        _,_,body=self.upload('active.html',b'<script>dangerous()</script>')
        name=json.loads(body)['files'][0]['name']
        self.assertTrue(self.call('/upload/preview/'+name)[1]['Content-Type'].startswith('text/plain'))
        _,_,body=self.upload('active.svg',b'<svg onload="dangerous()"/>')
        name=json.loads(body)['files'][0]['name']
        self.assertEqual(self.call('/upload/preview/'+name)[0],415)

    def test_chat_message_ids_do_not_repeat_at_cap(self):
        for n in range(205): self.call('/chat',f'cap-test-{n}')
        messages=self.json('/chat')[1]
        self.assertEqual(len(messages),200)
        ids=[m['n'] for m in messages]
        self.assertEqual(len(set(ids)),200)
        self.assertEqual(messages[-1]['msg'],'cap-test-204')

    def test_console_available_without_key_and_ticket_scope(self):
        self.assertEqual(self.json('/console/sessions')[0],200)
        status,invite=self.json('/console/invites',{'origin':self.origin})
        self.assertEqual(status,200); ticket=invite['ticket']
        self.assertEqual(self.call('/lin?ticket=invalid')[0],401)
        code,_,script=self.call('/lin?ticket='+ticket)
        # Connector builds are optional for the fast API suite.
        if (ROOT/'dist/console-clients/linux-amd64').exists():
            self.assertEqual(code,200); self.assertIn(self.origin.encode(),script)
            subprocess.run(['bash','-n'],input=script,check=True)
        status,client=self.json('/console/register',
                                 {'host':'scope-test','os':'linux','arch':'amd64','nonce':'n1'},ticket)
        self.assertEqual(status,200)
        replay_status,replay=self.json('/console/register',{'nonce':'n1'},ticket)
        self.assertEqual(replay_status,200)
        self.assertEqual(replay['id'],client['id'])
        self.assertEqual(self.json('/console/register',{'nonce':'n2'},ticket)[0],401)
        self.assertEqual(self.call('/lin?ticket='+ticket)[0],401)
        prefix='/console/sessions/'+client['id']
        self.assertEqual(self.call('/console/agent/'+client['id']+'/input',token='invalid')[0],401)
        self.assertEqual(self.json(prefix+'/resize',{'cols':0,'rows':24})[0],400)
        self.assertEqual(self.json(prefix+'/close',{})[0],200)
        self.assertEqual(self.call('/console/agent/'+client['id']+'/input',token=client['token'])[0],410)
        self.assertEqual(self.json(prefix+'/remove',{})[0],200)
        self.assertNotIn(client['id'], [s['id'] for s in self.json('/console/sessions')[1]])
        self.assertEqual(self.json(prefix+'/output')[0],404)
        self.assertEqual(self.call('/console/agent/'+client['id']+'/input',token=client['token'])[0],401)
        content=(self.home/'.expose/requests.json').read_text()
        self.assertNotIn(ticket,content)
        self.assertNotIn('/console/',content)
        self.assertFalse((self.home/'.expose'/f'console-{self.port}.key').exists())

    def test_network_proxy_relays_through_connected_machine(self):
        _,invite=self.json('/console/invites',{'origin':self.origin})
        _,client=self.json('/console/register',{'host':'proxy-test','os':'linux','arch':'amd64'},
                           invite['ticket'])
        agent='/console/agent/'+client['id']; token=client['token']
        proxy_info=self.json('/console/proxy')[1]
        self.assertTrue(proxy_info['enabled'])
        self.assertEqual(proxy_info['address'],f'socks5://127.0.0.1:{self.proxy_port}')
        received={'reply':b'','greeting':b'','after':b''}
        started=threading.Event(); greeted=threading.Event()
        def socks_client():
            def exact(sock,size):
                data=b''
                while len(data)<size:
                    chunk=sock.recv(size-len(data))
                    if not chunk:break
                    data+=chunk
                return data
            with socket.create_connection(('127.0.0.1',self.proxy_port),timeout=10) as sock:
                sock.sendall(b'\x05\x01\x00')
                self.assertEqual(exact(sock,2),b'\x05\x00')
                host=b'10.10.10.12'
                sock.sendall(b'\x05\x01\x00\x03'+bytes([len(host)])+host+struct.pack('!H',445))
                received['reply']=exact(sock,10);started.set()
                received['greeting']=exact(sock,5);greeted.set()
                sock.sendall(b'PING')
                try:received['after']=sock.recv(16)
                except socket.timeout:pass
        thread=threading.Thread(target=socks_client,daemon=True);thread.start()
        events=json.loads(self.call(agent+'/net?after=0',token=token)[2])
        opened=[e for e in events['events'] if e['type']=='open']
        self.assertEqual(len(opened),1)
        self.assertEqual((opened[0]['host'],opened[0]['port']),('10.10.10.12',445))
        sid=opened[0]['stream'];cursor=events['events'][-1]['seq']
        self.assertEqual(self.json(f'{agent}/net/{sid}/status',{'ok':True},token)[0],200)
        self.assertEqual(self.call(f'{agent}/net/{sid}/data',b'HELLO',token=token)[0],200)
        self.assertTrue(started.wait(5))
        self.assertEqual(received['reply'][:4],b'\x05\x00\x00\x01')
        self.assertTrue(greeted.wait(5))
        self.assertEqual(received['greeting'],b'HELLO')
        forwarded=json.loads(self.call(f'{agent}/net?after={cursor}',token=token)[2])
        writes=[e for e in forwarded['events'] if e['type']=='data']
        self.assertEqual(base64.b64decode(writes[0]['data']),b'PING')
        self.assertEqual(self.json(f'{agent}/net/{sid}/close',{},token)[0],200)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.json('/console/sessions/'+client['id']+'/remove',{})[0],200)

    def test_inbound_callback_reaches_local_service(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                while True:
                    data=self.request.recv(4096)
                    if not data:break
                    self.request.sendall(data)
        class EchoServer(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
            daemon_threads=True
        echo=EchoServer(('127.0.0.1',0),Echo)
        local_port=echo.server_address[1]
        threading.Thread(target=echo.serve_forever,daemon=True).start()
        try:
            _,invite=self.json('/console/invites',{'origin':self.origin})
            _,client=self.json('/console/register',{'host':'callback-test','os':'linux','arch':'amd64'},
                               invite['ticket'])
            agent='/console/agent/'+client['id']; token=client['token']
            status,callback=self.json('/console/callbacks',{'local':local_port,'remote':4455})
            self.assertEqual(status,200); cid=callback['id']
            events=json.loads(self.call(agent+'/net?after=0',token=token)[2])
            listen=[e for e in events['events'] if e['type']=='listen']
            self.assertEqual(len(listen),1); self.assertEqual(listen[0]['port'],4455)
            cursor=events['events'][-1]['seq']
            self.assertEqual(self.json(f'{agent}/callback/{cid}/state',
                                       {'active':True,'address':'10.11.12.12:4455'},
                                       token)[0],200)
            listed=self.json('/console/callbacks')[1]['callbacks']
            self.assertTrue(listed[0]['active']); self.assertEqual(listed[0]['address'],'10.11.12.12:4455')
            sid='callback-stream-1'
            self.assertEqual(self.json(f'{agent}/net/{sid}/inbound',
                                       {'callback':cid,'address':'10.11.12.99:55555'},token)[0],200)
            self.assertEqual(self.call(f'{agent}/net/{sid}/data',b'CALLBACK',token=token)[0],200)
            forwarded=json.loads(self.call(f'{agent}/net?after={cursor}',token=token)[2])
            writes=[e for e in forwarded['events'] if e['type']=='data']
            self.assertEqual(base64.b64decode(writes[0]['data']),b'CALLBACK')
            self.assertEqual(self.json(f'{agent}/net/{sid}/close',{},token)[0],200)
            self.assertEqual(self.json(f'/console/callbacks/{cid}/remove',{},token)[0],200)
            self.assertEqual(self.json('/console/sessions/'+client['id']+'/remove',{})[0],200)
        finally:
            echo.shutdown(); echo.server_close()

    @unittest.skipUnless((ROOT/'dist/console-clients/linux-amd64').exists() and os.uname().machine=='x86_64', 'Build Linux connector first')
    def test_real_pty_callback_resize_interrupt_and_remove(self):
        _,invite=self.json('/console/invites',{'origin':self.origin})
        script=self.call('/lin?ticket='+invite['ticket'])[2]
        client_log=open(self.home/'client.log','wb')
        client=subprocess.Popen(['bash'],stdin=subprocess.PIPE,stdout=client_log,stderr=client_log,
                                env=dict(os.environ,SHELL='/bin/bash'),start_new_session=True)
        client.stdin.write(script);client.stdin.close()
        ident=None
        try:
            for _ in range(100):
                sessions=self.json('/console/sessions')[1]
                live=[s for s in sessions if s['connected'] and s['host']!='scope-test']
                if live: ident=live[-1]['id'];break
                if client.poll() is not None: self.fail('Connector exited before registering')
                time.sleep(.1)
            self.assertIsNotNone(ident)
            prefix='/console/sessions/'+ident
            self.json(prefix+'/resize',{'cols':111,'rows':37})
            self.json(prefix+'/input',{'data':"printf 'PTY_'; test -t 0 && printf 'READY\\n'; stty size\r"})
            cursor=0;received=b''
            for _ in range(10):
                _,out=self.json(prefix+f'/output?after={cursor}')
                cursor=out['next'];received+=base64.b64decode(out['data'])
                if b'PTY_READY\r\n' in received and b'37 111\r\n' in received:break
            self.assertIn(b'PTY_READY\r\n',received);self.assertIn(b'37 111\r\n',received)
            self.json(prefix+'/input',{'data':'sleep 30\r'});time.sleep(.25)
            self.json(prefix+'/input',{'data':"\x03printf 'INTERRUPT_'; printf 'OK\\n'\r"})
            for _ in range(10):
                _,out=self.json(prefix+f'/output?after={cursor}')
                cursor=out['next'];received+=base64.b64decode(out['data'])
                if b'INTERRUPT_OK\r\n' in received:break
            self.assertIn(b'INTERRUPT_OK\r\n',received)
            self.assertEqual(self.json(prefix+'/remove',{})[0],200)
            # Pending polls receive closed; subsequent polls see a revoked token.
            self.assertIn(client.wait(timeout=8), (0, 1))
            self.assertNotIn(ident, [s['id'] for s in self.json('/console/sessions')[1]])
            self.assertEqual(self.json(prefix+'/output')[0],404)
        finally:
            if client.poll() is None:
                os.killpg(client.pid,signal.SIGINT)
                try:client.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(client.pid,signal.SIGKILL);client.wait()
            client_log.close()

class AuthFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='expose-auth-')
        cls.home = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        cls.origin = f'http://127.0.0.1:{cls.port}'
        env = dict(os.environ, HOME=str(cls.home), EXPOSE_CLIENT_DIR=str(ROOT/'dist/console-clients'),
                   EXPOSE_CONSOLES='1', EXPOSE_AUTH_PASSWORD='secret123',
                   EXPOSE_TOOLS_DIR=str(cls.home/'tools'),
                   EXPOSE_HEALTH_TOKEN='health123')
        cls.log = open(cls.home/'server.log', 'wb')
        cls.server = subprocess.Popen([str(ROOT/'dist/expose'), '--bind', '127.0.0.1',
                                      '-p', str(cls.port), 'hello'],
                                     env=env, stdout=cls.log, stderr=cls.log, start_new_session=True)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.origin+'/login', timeout=2)
                break
            except urllib.error.HTTPError as error:
                error.close()
                break
            except OSError:
                pass
            time.sleep(.05)
        else:
            raise RuntimeError('Server did not start')

    @classmethod
    def tearDownClass(cls):
        os.killpg(cls.server.pid, signal.SIGTERM)
        try: cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(cls.server.pid, signal.SIGKILL); cls.server.wait()
        cls.log.close(); cls.temp.cleanup()

    def opener(self):
        jar=http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)),jar

    def open(self, opener, path, data=None, accept=None):
        headers={'Accept':accept} if accept else {}
        if data is not None:
            data=urllib.parse.urlencode(data).encode()
            headers['Content-Type']='application/x-www-form-urlencoded'
        req=urllib.request.Request(self.origin+path,data=data,headers=headers)
        try:
            with opener.open(req,timeout=15) as response:
                return response.status,response.headers,response.read()
        except urllib.error.HTTPError as response:
            with response:
                return response.code,response.headers,response.read()

    def test_winenum_ticket_and_ticket_upload(self):
        anon,_=self.opener()
        req=urllib.request.Request(self.origin+'/console/winenum/ticket',data=b'',method='POST')
        try:
            anon.open(req,timeout=10)
            self.fail('winenum ticket endpoint allowed anonymous access')
        except urllib.error.HTTPError as response:
            with response:
                self.assertEqual(response.code,401)
        auth,_=self.opener()
        self.open(auth,'/login',{'password':'secret123'})
        req=urllib.request.Request(self.origin+'/console/winenum/ticket',data=b'',method='POST')
        with auth.open(req,timeout=10) as response:
            ticket=json.loads(response.read())['ticket']
        code,_,body=self.open(anon,'/console/winenum.ps1?ticket='+ticket)
        self.assertEqual(code,200)
        self.assertIn(b'expose winenum',body)
        self.assertEqual(self.open(anon,'/console/winenum.ps1?ticket=bad')[0],401)
        boundary='expose-winenum-boundary'
        raw=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
             'filename="recon.txt"\r\nContent-Type: text/plain\r\n\r\nreport\r\n'
             f'--{boundary}--\r\n').encode()
        headers={'Content-Type':'multipart/form-data; boundary='+boundary}
        req=urllib.request.Request(self.origin+'/upload?ticket='+ticket,data=raw,headers=headers)
        with anon.open(req,timeout=10) as response:
            saved=json.loads(response.read())
        self.assertEqual(saved['saved'],['recon.txt'])
        self.assertEqual((self.home/'Downloads/expose/recon.txt').read_text(),'report')
        req=urllib.request.Request(self.origin+'/upload',data=raw,headers=headers)
        try:
            anon.open(req,timeout=10)
            self.fail('upload allowed anonymous access without a ticket')
        except urllib.error.HTTPError as response:
            with response:
                self.assertEqual(response.code,401)
        log=(self.home/'.expose/requests.json').read_text()
        self.assertNotIn(ticket,log)
        self.assertIn('ticket=%2A%2A%2A',log)

    def test_windows_tools_staging_and_ticket_download(self):
        auth,_=self.opener()
        self.open(auth,'/login',{'password':'secret123'})
        payload=b'fake-seatbelt'
        req=urllib.request.Request(self.origin+'/console/tools/Seatbelt.exe',data=payload,
                                   headers={'Content-Type':'application/octet-stream'})
        with auth.open(req,timeout=10) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(json.loads(response.read())['name'],'Seatbelt.exe')
        code,_,body=self.open(auth,'/console/tools')
        self.assertEqual(code,200)
        self.assertIn('Seatbelt.exe',json.loads(body)['tools'][0]['name'])
        req=urllib.request.Request(self.origin+'/console/winenum/ticket',data=b'',method='POST')
        with auth.open(req,timeout=10) as response:
            ticket=json.loads(response.read())['ticket']
        anon,_=self.opener()
        code,_,downloaded=self.open(anon,'/console/tool/Seatbelt.exe?ticket='+ticket)
        self.assertEqual(code,200); self.assertEqual(downloaded,payload)
        self.assertEqual(self.open(anon,'/console/tool/Seatbelt.exe?ticket=bad')[0],401)
        code,_,runner=self.open(anon,'/console/toolrunner.ps1?ticket='+ticket)
        self.assertEqual(code,200); self.assertIn(b'ExposeKind',runner)
        req=urllib.request.Request(self.origin+'/console/tools/Seatbelt.exe',data=payload,
                                   headers={'Content-Type':'application/octet-stream'})
        try:
            anon.open(req,timeout=10)
            self.fail('tool upload allowed anonymous access')
        except urllib.error.HTTPError as response:
            with response:
                self.assertEqual(response.code,401)

    def test_password_gate_and_connector_exemptions(self):
        anon,_=self.opener()
        code,headers,body=self.open(anon,'/',accept='text/html')
        self.assertEqual(code,401); self.assertIn(b'This session is password protected',body)
        self.assertEqual(self.open(anon,'/console/status')[0],401)
        self.assertEqual(self.open(anon,'/login',{'password':'wrong'})[0],401)
        code,_,_=self.open(anon,'/login',{'password':'secret123'})
        self.assertEqual(code,200)
        self.assertEqual(self.open(anon,'/console/status')[0],200)
        code,_,body=self.open(anon,'/login',{'password':'wrong'})
        self.assertEqual(code,401)
        self.assertIn(b'Incorrect password',body)
        self.assertEqual(self.open(anon,'/.expose-health?session=health123')[0],200)
        self.assertEqual(self.open(anon,'/.expose-health?session=wrong')[0],404)

        auth,jar=self.opener()
        self.assertEqual(self.open(auth,'/login',{'password':'secret123'})[0],200)
        self.assertTrue(any(cookie.name=='expose_session' for cookie in jar))
        self.assertEqual(self.open(auth,'/console/status')[0],200)
        req=urllib.request.Request(self.origin+'/console/invites',
                                   data=json.dumps({'origin':self.origin}).encode(),
                                   headers={'Content-Type':'application/json'})
        with auth.open(req,timeout=15) as response:
            invite=json.loads(response.read())
        ticket=invite['ticket']
        anon2,_=self.opener()
        self.assertEqual(self.open(anon2,'/lin?ticket='+ticket)[0],200)
        req=urllib.request.Request(self.origin+'/console/register',
                                   data=json.dumps({'host':'auth-test'}).encode(),
                                   headers={'Content-Type':'application/json',
                                            'Authorization':'Bearer '+ticket})
        with anon2.open(req,timeout=15) as response:
            client=json.loads(response.read())
        req=urllib.request.Request(self.origin+'/console/agent/'+client['id']+'/exit',
                                   data=b'',method='POST',
                                   headers={'Authorization':'Bearer '+client['token']})
        with anon2.open(req,timeout=15) as response:
            self.assertEqual(response.status,200)
        try:
            auth.open(urllib.request.Request(self.origin+'/logout',data=b'',method='POST'),timeout=15)
        except urllib.error.HTTPError as response:
            with response:
                self.assertEqual(response.code,401)  # redirected to the login page
        self.assertEqual(self.open(auth,'/')[0],401)
        log=(self.home/'.expose/requests.json').read_text()
        self.assertNotIn('secret123',log)
        self.assertNotIn('secret123',(self.home/'server.log').read_text(errors='replace'))

if __name__=='__main__':unittest.main(verbosity=2)

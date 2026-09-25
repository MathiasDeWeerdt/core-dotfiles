/* Browser terminal control with single-use connector enrollment. */
(function(){
  let enabled=false,ticket='',expires=0,platform='win',selected='',terminal=null,fit=null,cursor=0,generation=0,polling=false;
  let inputQueue=Promise.resolve(),sessions=[],available=[];
  const error=q('console-error'),container=q('browser-terminal');
  const terminalSession=new URLSearchParams(location.search).get('terminal');
  if(terminalSession){document.body.classList.add('terminal-view');showView('shells')}

  function notice(text){error.textContent=text}
  async function api(path,method='GET',data){
    const response=await fetch('/console/'+path,{method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});
    const value=await response.json();if(!response.ok)throw Error(value.error||'Console request failed');return value;
  }
  function renderCommand(){
    const url=location.origin+'/'+platform+'?ticket='+encodeURIComponent(ticket);
    q('console-command').textContent=!ticket?'':platform==='win'?"irm '"+url.replace(/'/g,"''")+"' | iex":"curl -fsSL '"+url.replace(/'/g,"'\\''")+"' | bash";
    q('console-copy').disabled=!ticket||expires<Date.now();
  }
  async function invite(){
    try{const result=await api('invites','POST',{origin:location.origin});ticket=result.ticket;expires=result.expires*1000;renderCommand();q('console-invite-info').textContent='Single use · expires in 10 minutes. Paste into '+(platform==='win'?'PowerShell.':'a terminal.');notice('')}
    catch(e){notice(e.message)}
  }
  function dispose(){generation++;selected='';cursor=0;if(terminal)terminal.dispose();terminal=null;fit=null;container.replaceChildren();container.hidden=true;q('console-disconnect').disabled=true;q('console-remove').disabled=true;q('console-popout').disabled=true}
  async function command(action,value){if(!selected||!enabled)return;await api('sessions/'+selected+'/'+action,'POST',value)}
  function fitTerminal(){if(fit&&!q('shells').hidden&&container.clientWidth){fit.fit()}}
  async function selectSession(id){
    if(selected===id)return;dispose();selected=id;cursor=0;
    container.hidden=false;q('console-empty').hidden=true;
    terminal=new Terminal({cursorBlink:true,fontFamily:'Cascadia Code, Consolas, monospace',fontSize:14,scrollback:5000,allowProposedApi:false,theme:{background:'#111713',foreground:'#e7eee8',cursor:'#a3cfb0'},screenReaderMode:true});
    fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(container);fit.fit();
    q('console-disconnect').disabled=false;q('console-remove').disabled=false;q('console-popout').disabled=false;
    const thisGeneration=generation,sessionID=id;
    terminal.onData(data=>{
      inputQueue=inputQueue.then(async()=>{if(generation!==thisGeneration)return;const characters=Array.from(data);for(let offset=0;offset<characters.length;offset+=4096)await api('sessions/'+sessionID+'/input','POST',{data:characters.slice(offset,offset+4096).join('')})}).catch(e=>notice(e.message));
    });
    terminal.onResize(size=>{command('resize',size).catch(e=>notice(e.message))});
    await command('resize',{cols:terminal.cols,rows:terminal.rows}).catch(e=>notice(e.message));
    renderSessions();terminal.focus();
    while(enabled&&generation===thisGeneration){
      try{
        const output=await api('sessions/'+id+'/output?after='+cursor);
        if(generation!==thisGeneration)return;
        if(output.truncated)terminal.writeln('\r\n[Earlier output was trimmed]\r\n');
        const bytes=Uint8Array.from(atob(output.data),c=>c.charCodeAt(0));
        await new Promise(resolve=>terminal.write(bytes,resolve));if(generation!==thisGeneration)return;cursor=output.next;
        if(!output.connected&&bytes.length<65536){terminal.writeln('\r\n[Session ended]');q('console-disconnect').disabled=true;return}
      }catch(e){if(generation!==thisGeneration)return;notice(e.message);terminal.writeln('\r\n[Connection lost. Select this session again to retry.]');selected='';return}
    }
  }
  function renderSessions(){
    q('console-sessions').replaceChildren();
    sessions.forEach(session=>{const button=document.createElement('button');button.className='btn ghost sm'+(session.id===selected?' selected':'');button.textContent=session.host+' · '+session.os+' / '+session.arch+(session.connected?'':' · ended');button.setAttribute('aria-pressed',String(session.id===selected));button.addEventListener('click',()=>selectSession(session.id));q('console-sessions').appendChild(button)});
    q('console-empty').hidden=!!selected||sessions.length>0;
  }
  async function refresh(){
    if(!enabled||polling)return;polling=true;
    try{
      sessions=await api('sessions');
      if(selected&&!sessions.some(s=>s.id===selected))dispose();
      renderSessions();q('console-status').textContent=sessions.some(s=>s.connected)?'Connected':'Listening';
      if(terminalSession){
        const session=sessions.find(s=>s.id===terminalSession);
        q('terminal-tab-title').textContent=session?session.host+' · '+session.os:'Terminal';
        document.title=(session?session.host:'Terminal')+' · expose';
        q('terminal-tab-status').textContent=session?(session.connected?'Connected':'Ended'):'Removed';
        if(session&&!selected)selectSession(session.id);
        if(!session){q('console-empty').hidden=false;q('console-empty').textContent='This machine is no longer available. Return to consoles to connect a machine.'}
      }else if(!selected&&sessions.some(s=>s.connected)&&!q('shells').hidden)selectSession(sessions.find(s=>s.connected).id);
    }
    catch(e){notice(e.message)}finally{polling=false}
  }
  q('console-popout').addEventListener('click',()=>{
    if(!selected)return;
    const url=new URL('/',location.origin);url.searchParams.set('terminal',selected);url.hash='shells';
    window.open(url.href,'_blank','noopener,noreferrer');
  });
  window.addEventListener('focus',()=>{fitTerminal();if(terminal&&selected)command('resize',{cols:terminal.cols,rows:terminal.rows}).catch(e=>notice(e.message))});
  q('console-new').addEventListener('click',invite);
  q('console-copy').addEventListener('click',()=>{if(expires<Date.now()){notice('Connection link expired. Create a new link.');return}copyText(q('console-command').textContent,'Connection command copied')});
  q('console-platforms').addEventListener('click',e=>{const button=e.target.closest('[data-platform]');if(!button)return;platform=button.dataset.platform;document.querySelectorAll('#console-platforms button').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button))});renderCommand();q('console-invite-info').textContent='Single use · expires in 10 minutes. Paste into '+(platform==='win'?'PowerShell.':'a terminal.')});
  q('console-disconnect').addEventListener('click',async()=>{try{await command('close',{});refresh()}catch(e){notice(e.message)}});
  q('console-remove').addEventListener('click',async()=>{
    const id=selected;if(!id)return;
    q('console-remove').disabled=true;
    try{
      await api('sessions/'+id+'/remove','POST',{});
      if(selected===id)dispose();
      sessions=sessions.filter(session=>session.id!==id);renderSessions();notice('');refresh();
    }catch(e){q('console-remove').disabled=!selected;notice(e.message)}
  });
  new ResizeObserver(fitTerminal).observe(container);
  window.addEventListener('hashchange',()=>{if(!q('shells').hidden){fitTerminal();refresh()}});
  setInterval(()=>{refresh();if(ticket&&expires<Date.now()){q('console-copy').disabled=true;q('console-invite-info').textContent='Connection link expired. Create a new link.'}},2000);
  fetch('/console/status').then(r=>r.json()).then(async status=>{
    enabled=status.enabled;available=status.platforms||[];
    q('console-status').textContent=enabled?'Listening':'Disabled';
    q('console-help').hidden=enabled;
    q('console-controls').hidden=!enabled;
    if(!enabled){q('console-help').textContent='Start expose-online to use browser terminals.';return}
    await refresh();
    if(terminalSession)return;
    if(available.length)await invite();
    else notice('Build connectors on the host with: make -C expose install-console-clients');
  }).catch(()=>notice('Could not check console availability. Reload to retry.'));
})();

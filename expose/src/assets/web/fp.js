/* expose — client-side device fingerprint
   Collects browser/device signals on every page, renders the panel on /me
   (into <div id="fp">), and reports everything to POST /fp where it is
   logged to the operator's SQLite database. */
(function(){
  var mount=document.getElementById('fp');

  var d={};

  // ── basics ──
  d.user_agent=navigator.userAgent;
  d.platform=navigator.platform||'?';
  d.languages=(navigator.languages||[navigator.language]).join(', ');
  d.timezone=(function(){try{return Intl.DateTimeFormat().resolvedOptions().timeZone}catch(e){return'?'}})()+
    ' (UTC'+(function(){var o=-new Date().getTimezoneOffset()/60;return(o>=0?'+':'')+o})()+')';
  d.screen=screen.width+'×'+screen.height+' @'+(window.devicePixelRatio||1)+'x, '+screen.colorDepth+'bit';
  d.viewport=window.innerWidth+'×'+window.innerHeight;
  d.cpu_cores=navigator.hardwareConcurrency||'?';
  d.device_memory=navigator.deviceMemory?navigator.deviceMemory+' GB (approx)':'?';
  d.touch_points=navigator.maxTouchPoints||0;
  d.cookies_enabled=navigator.cookieEnabled;
  d.do_not_track=navigator.doNotTrack==='1'?'yes':(navigator.doNotTrack||'unset');
  d.online=navigator.onLine;
  d.pdf_viewer=navigator.pdfViewerEnabled===true;
  try{d.connection=(navigator.connection&&navigator.connection.effectiveType)||'?'}catch(e){d.connection='?'}
  d.storage=(function(){
    var r=[];
    try{localStorage.setItem('__t','1');localStorage.removeItem('__t');r.push('localStorage')}catch(e){}
    try{sessionStorage.setItem('__t','1');sessionStorage.removeItem('__t');r.push('sessionStorage')}catch(e){}
    if(window.indexedDB)r.push('indexedDB');
    return r.join(', ')||'none'})();

  // ── WebGL GPU ──
  try{
    var c=document.createElement('canvas');
    var gl=c.getContext('webgl')||c.getContext('experimental-webgl');
    if(gl){
      var ext=gl.getExtension('WEBGL_debug_renderer_info');
      d.gpu=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
    }else d.gpu='unavailable';
  }catch(e){d.gpu='unavailable'}

  // ── canvas fingerprint ──
  d.canvas=(function(){
    try{
      var cv=document.createElement('canvas');cv.width=240;cv.height=40;
      var x=cv.getContext('2d');
      x.textBaseline='top';x.font='14px Arial';
      x.fillStyle='#f60';x.fillRect(10,10,100,20);
      x.fillStyle='#069';x.fillText('expose·fp·👁',14,14);
      x.strokeStyle='rgba(0,128,255,.5)';x.arc(60,20,12,0,Math.PI*1.7);x.stroke();
      var url=cv.toDataURL(),h=0x811c9dc5;
      for(var i=0;i<url.length;i++){h^=url.charCodeAt(i);h=(h*0x01000193)>>>0}
      return h.toString(16);
    }catch(e){return'blocked'}
  })();

  // ── render ──
  var labels={
    user_agent:'User-Agent',platform:'Platform',languages:'Languages',timezone:'Timezone',
    screen:'Screen',viewport:'Viewport',cpu_cores:'CPU cores',device_memory:'Device memory',
    touch_points:'Touch points',cookies_enabled:'Cookies',do_not_track:'Do Not Track',
    online:'Online',pdf_viewer:'PDF viewer',connection:'Connection',storage:'Storage APIs',
    gpu:'GPU (WebGL)',canvas:'Canvas fingerprint'
  };
  var order=['user_agent','platform','languages','timezone','screen','viewport','cpu_cores',
             'device_memory','touch_points','cookies_enabled','do_not_track','online',
             'pdf_viewer','connection','storage','gpu','canvas'];

  // ── render panel (/me only) ──
  if(mount){
    var h='<h2>Device fingerprint</h2><table>';
    order.forEach(function(k){
      if(d[k]===undefined||d[k]==='')return;
      h+='<tr><td>'+labels[k]+'</td><td></td></tr>';
    });
    h+='</table><div class="fpid">visitor id: <b>computing…</b></div>'+
       '<p class="fpnote">Collected by your browser and reported to this server — '+
       'this is what any website can see about you.</p>'+
       '<button class="fbtn" id="fpcopy">copy as JSON</button>';
    mount.innerHTML=h;

    var rows=mount.querySelectorAll('td:nth-child(2)');
    var i=0;
    order.forEach(function(k){
      if(d[k]===undefined||d[k]==='')return;
      rows[i++].textContent=String(d[k]);
    });

    document.getElementById('fpcopy').addEventListener('click',function(){
      var j=JSON.stringify(d,null,2);
      var b=this;
      function ok(){b.textContent='copied';setTimeout(function(){b.textContent='copy as JSON'},1200)}
      if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(j).then(ok).catch(ok)}
      else ok();
    });
  }

  // ── stable visitor id: SHA-256 over the stable signals ──
  var stable=['user_agent','platform','languages','timezone','screen','cpu_cores',
              'device_memory','gpu','canvas'].map(function(k){return d[k]}).join('|');
  function show(id){
    if(!mount)return;
    var el=mount.querySelector('.fpid b');
    if(el)el.textContent=id;
  }
  function finish(id){
    d.visitor_id=id;
    show(id);
    report();
  }
  // ── report to the operator (logged to sqlite via POST /fp) ──
  function report(){
    d.page=location.pathname;
    var payload;
    try{payload=JSON.stringify(d)}catch(e){return}
    try{
      if(navigator.sendBeacon){
        var ok=navigator.sendBeacon('/fp',new Blob([payload],{type:'application/json'}));
        if(ok)return;
      }
      fetch('/fp',{method:'POST',headers:{'Content-Type':'application/json'},body:payload,keepalive:true}).catch(function(){});
    }catch(e){}
  }
  if(window.crypto&&crypto.subtle&&crypto.subtle.digest){
    crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable)).then(function(buf){
      var hex=Array.from(new Uint8Array(buf)).map(function(b){return('0'+b.toString(16)).slice(-2)}).join('');
      finish(hex.slice(0,16));
    }).catch(function(){finish('unavailable')});
  }else finish('unavailable');
})();

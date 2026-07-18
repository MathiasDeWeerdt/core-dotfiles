#!/bin/sh
# Status code and reason phrase
_RCODE="${EXPOSE_RESP_CODE:-200}"
case "$_RCODE" in
  200) _RREASON="OK" ;; 201) _RREASON="Created" ;; 204) _RREASON="No Content" ;;
  301) _RREASON="Moved Permanently" ;; 302) _RREASON="Found" ;; 304) _RREASON="Not Modified" ;;
  400) _RREASON="Bad Request" ;; 401) _RREASON="Unauthorized" ;; 403) _RREASON="Forbidden" ;;
  404) _RREASON="Not Found" ;; 405) _RREASON="Method Not Allowed" ;;
  418) _RREASON="I'm a Teapot" ;; 429) _RREASON="Too Many Requests" ;;
  500) _RREASON="Internal Server Error" ;; 502) _RREASON="Bad Gateway" ;;
  503) _RREASON="Service Unavailable" ;; *) _RREASON="Custom" ;;
esac
# Read request line
read -r REQ 2>/dev/null || REQ=""
REQ=$(printf '%s' "$REQ" | tr -d '\r')

# Collect ALL headers
ALL_HDRS=""
UA="-"; ACCEPT=""; ACCEPT_LANG=""; ACCEPT_ENC=""; REFERER=""; HOST_HDR=""
COOKIE=""; ORIGIN=""; DNT_HDR=""; CONTENT_TYPE=""; CONTENT_LEN=""
XFF=""; CONNECTION=""; EXTRA_HDRS=""; AUTH_HDR=""

while IFS= read -r hdr; do
  hdr=$(printf '%s' "$hdr" | tr -d '\r')
  [ -z "$hdr" ] && break
  ALL_HDRS="${ALL_HDRS}${hdr}
"
  hdr_lower=$(printf '%s' "$hdr" | tr '[:upper:]' '[:lower:]')
  val="${hdr#*: }"
  case "$hdr_lower" in
    user-agent:*)         UA="$val" ;;
    accept:*)             ACCEPT="$val" ;;
    accept-language:*)    ACCEPT_LANG="$val" ;;
    accept-encoding:*)    ACCEPT_ENC="$val" ;;
    referer:*)            REFERER="$val" ;;
    host:*)               HOST_HDR="$val" ;;
    cookie:*)             COOKIE="$val" ;;
    origin:*)             ORIGIN="$val" ;;
    dnt:*)                DNT_HDR="$val" ;;
    content-type:*)       CONTENT_TYPE="$val" ;;
    content-length:*)     CONTENT_LEN="$val" ;;
    x-forwarded-for:*)    XFF="$val" ;;
    connection:*)         CONNECTION="$val" ;;
    authorization:*)      AUTH_HDR="$val"
      EXTRA_HDRS="${EXTRA_HDRS}  ${hdr}
" ;;
    sec-*|cache-control:*|if-*|upgrade-*|pragma:*)
      EXTRA_HDRS="${EXTRA_HDRS}  ${hdr}
" ;;
  esac
done

# Extract method, path, HTTP version
MTH="${REQ%% *}"; rest="${REQ#* }"; PTH="${rest%% *}"; HTTPVER="${rest##* }"
[ -z "$MTH" ] && MTH="-"; [ -z "$PTH" ] && PTH="-"
PEER="${SOCAT_PEERADDR:-unknown}"
PEER_PORT="${SOCAT_PEERPORT:-?}"

# ── IP allowlist check ──
if [ -n "${EXPOSE_ALLOW:-}" ]; then
  _ALLOWED=$(python3 -c "
import sys, ipaddress
peer = sys.argv[1]
try:
    addr = ipaddress.ip_address(peer)
    for cidr in sys.argv[2].split(','):
        cidr = cidr.strip()
        if cidr and addr in ipaddress.ip_network(cidr, strict=False):
            print('1'); sys.exit(0)
except Exception:
    pass
print('0')
" "$PEER" "$EXPOSE_ALLOW" 2>/dev/null || echo "0")
  if [ "$_ALLOWED" != "1" ]; then
    BODY="403 Forbidden"
    printf 'HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "${#BODY}" "$BODY"
    exit 0
  fi
fi

# Increment request counter
if [ -f "$EXPOSE_COUNTER" ]; then
  N=$(cat "$EXPOSE_COUNTER" 2>/dev/null || echo 0)
  N=$((N + 1))
  echo "$N" > "$EXPOSE_COUNTER" 2>/dev/null
else
  N="?"
fi

TIME=$(date '+%H:%M:%S')

if [ "${EXPOSE_VERBOSE:-0}" = "1" ]; then
  # ── Reverse DNS ──
  RDNS=""
  if command -v dig >/dev/null 2>&1; then
    RDNS=$(dig +short -x "$PEER" 2>/dev/null | head -1 | sed 's/\.$//') 
  elif command -v getent >/dev/null 2>&1; then
    RDNS=$(getent hosts "$PEER" 2>/dev/null | awk '{print $2}')
  elif command -v host >/dev/null 2>&1; then
    RDNS=$(host "$PEER" 2>/dev/null | awk '/pointer/{print $NF}' | sed 's/\.$//') 
  fi
  [ -z "$RDNS" ] && RDNS="-"

  # ── Parse User-Agent into OS + Browser ──
  BROWSER="-"; OS="-"
  case "$UA" in
    *Firefox/*)
      ver=$(printf '%s' "$UA" | sed -n 's/.*Firefox\/\([^ ]*\).*/\1/p')
      BROWSER="Firefox $ver" ;;
    *Edg/*)
      ver=$(printf '%s' "$UA" | sed -n 's/.*Edg\/\([^ ]*\).*/\1/p')
      BROWSER="Edge $ver" ;;
    *Chrome/*)
      ver=$(printf '%s' "$UA" | sed -n 's/.*Chrome\/\([^ ]*\).*/\1/p')
      BROWSER="Chrome $ver" ;;
    *Safari/*)
      ver=$(printf '%s' "$UA" | sed -n 's/.*Version\/\([^ ]*\).*/\1/p')
      BROWSER="Safari $ver" ;;
    *curl/*)
      ver=$(printf '%s' "$UA" | sed -n 's/.*curl\/\([^ ]*\).*/\1/p')
      BROWSER="curl $ver" ;;
    *Wget/*)
      BROWSER="Wget" ;;
    *[Bb]ot*|*[Cc]rawl*|*[Ss]pider*)
      BROWSER="Bot ($UA)" ;;
  esac
  case "$UA" in
    *Linux*)   OS="Linux" ;;
    *Mac\ OS*) OS="macOS" ;;
    *Windows*) OS="Windows" ;;
    *Android*) OS="Android" ;;
    *iPhone*|*iPad*) OS="iOS" ;;
  esac
  # arch hint
  case "$UA" in
    *x86_64*|*x64*|*amd64*) OS="$OS x86_64" ;;
    *aarch64*|*arm64*)       OS="$OS arm64" ;;
    *armv7*|*armv6*)         OS="$OS arm" ;;
  esac

  # ── Verbose block ──
  SEP="\e[2m│\e[0m"
  printf '\n  \e[2m┌─ #%s ─────────────────────────────────────────────\e[0m\n' "$N" >&2
  printf '  %b \e[2m%s\e[0m  \e[1m%s \e[36m%s\e[0m  \e[2m%s\e[0m\n' "$SEP" "$TIME" "$MTH" "$PTH" "$HTTPVER" >&2
  printf '  %b \e[34mClient\e[0m    %s:%s' "$SEP" "$PEER" "$PEER_PORT" >&2
  [ "$RDNS" != "-" ] && printf '  \e[2m(%s)\e[0m' "$RDNS" >&2
  printf '\n' >&2
  [ "$XFF" != "" ] && printf '  %b \e[34mProxy\e[0m     %s\n' "$SEP" "$XFF" >&2
  printf '  %b \e[34mBrowser\e[0m   %s  \e[2m(%s)\e[0m\n' "$SEP" "$BROWSER" "$OS" >&2
  [ -n "$HOST_HDR" ] &&   printf '  %b \e[34mHost\e[0m      %s\n' "$SEP" "$HOST_HDR" >&2
  [ -n "$ACCEPT_LANG" ] && printf '  %b \e[34mLanguage\e[0m  %s\n' "$SEP" "$ACCEPT_LANG" >&2
  [ -n "$ACCEPT" ] &&      printf '  %b \e[34mAccept\e[0m    %s\n' "$SEP" "$ACCEPT" >&2
  [ -n "$ACCEPT_ENC" ] &&  printf '  %b \e[34mEncoding\e[0m  %s\n' "$SEP" "$ACCEPT_ENC" >&2
  [ -n "$REFERER" ] &&     printf '  %b \e[34mReferer\e[0m   \e[4m%s\e[0m\n' "$SEP" "$REFERER" >&2
  [ -n "$ORIGIN" ] &&      printf '  %b \e[34mOrigin\e[0m    %s\n' "$SEP" "$ORIGIN" >&2
  [ -n "$COOKIE" ] &&      printf '  %b \e[34mCookies\e[0m   %s\n' "$SEP" "$COOKIE" >&2
  [ -n "$CONNECTION" ] &&  printf '  %b \e[34mConn\e[0m      %s\n' "$SEP" "$CONNECTION" >&2
  [ "$DNT_HDR" = "1" ] &&  printf '  %b \e[34mDNT\e[0m       \e[33myes\e[0m\n' "$SEP" >&2
  [ -n "$CONTENT_TYPE" ] && printf '  %b \e[34mBody\e[0m      %s (%s bytes)\n' "$SEP" "$CONTENT_TYPE" "${CONTENT_LEN:--}" >&2
  if [ -n "$EXTRA_HDRS" ]; then
    printf '  %b \e[2m──────\e[0m\n' "$SEP" >&2
    printf '%s' "$EXTRA_HDRS" | while IFS= read -r line; do
      [ -n "$line" ] && printf '  %b \e[2m%s\e[0m\n' "$SEP" "$line" >&2
    done
  fi
  printf '  \e[2m└───────────────────────────────────────────────────\e[0m\n' >&2
else
  # ── Compact one-liner (default) ──
  printf '\e[2m%s\e[0m  \e[1;33m%-15s\e[0m  \e[1m%-7s\e[0m \e[36m%s\e[0m  \e[2m%s\e[0m\n' \
    "$TIME" "$PEER" "$MTH" "$PTH" "$UA" >&2
fi

# ── Read request body (for --catch and log capture) ──────────────────────────
REQ_BODY=""
_BODY_LIMIT="${EXPOSE_BODY_LIMIT:-4096}"
_PTHBASE_EARLY="${PTH%%\?*}"
# Skip stdin capture for upload (Python handler needs stdin intact) and for
# multipart (binary data causes null-byte issues in shell command substitution)
_SKIP_BODY=0
case "$_PTHBASE_EARLY" in /upload) _SKIP_BODY=1 ;; esac
case "$CONTENT_TYPE" in *multipart/form-data*) _SKIP_BODY=1 ;; esac
if [ "$_SKIP_BODY" = "0" ] && [ -n "$CONTENT_LEN" ] && [ "$CONTENT_LEN" -gt 0 ] 2>/dev/null; then
  if [ "$_BODY_LIMIT" -gt 0 ] 2>/dev/null; then
    _READ_LEN="$CONTENT_LEN"
    [ "$_READ_LEN" -gt "$_BODY_LIMIT" ] && _READ_LEN="$_BODY_LIMIT"
    REQ_BODY=$(head -c "$_READ_LEN" 2>/dev/null || true)
    # drain remaining bytes so connection stays clean
    _REMAINING=$(( CONTENT_LEN - _READ_LEN ))
    [ "$_REMAINING" -gt 0 ] && head -c "$_REMAINING" >/dev/null 2>/dev/null
  fi
fi

# ── Write to JSON log file ──
if [ -n "${EXPOSE_LOGFILE:-}" ]; then
  case "$PTH" in
    /log|/log\?*|/log/clear|/meta|/upload/files|/me) ;; # skip internal API
    *)
  printf '%s' "$REQ_BODY" | python3 -c "
import json,sys,os,time
body_raw=sys.stdin.buffer.read()
try: body_str=body_raw.decode('utf-8','replace')
except: body_str=''
e={'n':int(sys.argv[1]),'ts':time.time(),'time':sys.argv[2],'method':sys.argv[3],
   'path':sys.argv[4],'httpver':sys.argv[5],'ip':sys.argv[6],'port':sys.argv[7],
   'ua':sys.argv[8],'host':sys.argv[9],'accept':sys.argv[10],'accept_lang':sys.argv[11],
   'accept_enc':sys.argv[12],'referer':sys.argv[13],'cookie':sys.argv[14],
   'origin':sys.argv[15],'dnt':sys.argv[16],'content_type':sys.argv[17],
   'content_len':sys.argv[18],'xff':sys.argv[19],'connection':sys.argv[20],
   'auth':sys.argv[21]}
if body_str: e['body']=body_str
lf=sys.argv[22]
try:
  with open(lf,'r') as f: log=json.load(f)
except: log=[]
log.append(e)
if len(log)>500: log=log[-500:]
with open(lf,'w') as f: json.dump(log,f)
" "$N" "$TIME" "$MTH" "$PTH" "$HTTPVER" "$PEER" "$PEER_PORT" \
  "$UA" "$HOST_HDR" "$ACCEPT" "$ACCEPT_LANG" "$ACCEPT_ENC" "$REFERER" \
  "$COOKIE" "$ORIGIN" "$DNT_HDR" "$CONTENT_TYPE" "${CONTENT_LEN:--}" \
  "$XFF" "$CONNECTION" "$AUTH_HDR" "$EXPOSE_LOGFILE" 2>/dev/null &
    ;;
  esac
fi

# ── Auth check ──
if [ -n "${EXPOSE_AUTH:-}" ]; then
  AUTH_DECODED=""
  if [ -n "$AUTH_HDR" ]; then
    AUTH_B64="${AUTH_HDR#Basic }"
    AUTH_DECODED=$(printf '%s' "$AUTH_B64" | base64 -d 2>/dev/null || true)
  fi
  if [ "$AUTH_DECODED" != "$EXPOSE_AUTH" ]; then
    ABODY="401 Unauthorized"
    printf 'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="expose"\r\nContent-Type: text/plain\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "${#ABODY}" "$ABODY"
    exit 0
  fi
fi

# ── Catch mode: dump request body ──
if [ "${EXPOSE_CATCH:-0}" = "1" ] && [ -n "$CONTENT_LEN" ] && [ "$CONTENT_LEN" -gt 0 ] 2>/dev/null; then
  if [ -n "$REQ_BODY" ]; then
    CATCH_BODY="$REQ_BODY"
  else
    CATCH_BODY=$(head -c 4096 2>/dev/null || true)
  fi
  printf '\n  \e[35m┌─ body (%s bytes) ─────────────────────────\e[0m\n' "$CONTENT_LEN" >&2
  if command -v xxd >/dev/null 2>&1; then
    printf '%s' "$CATCH_BODY" | xxd -l 4096 >&2
  else
    printf '%s' "$CATCH_BODY" | od -A x -t x1z -N 4096 >&2
  fi
  [ "$CONTENT_LEN" -gt "$_BODY_LIMIT" ] && printf '  \e[2m… truncated (%s/%s bytes shown)\e[0m\n' "$_BODY_LIMIT" "$CONTENT_LEN" >&2
  printf '  \e[35m└───────────────────────────────────────────────────\e[0m\n\n' >&2
fi

# ── Route and Respond ──
_PTHBASE="${PTH%%\?*}"
_PTHQUERY="${PTH#*\?}"
[ "$_PTHQUERY" = "$PTH" ] && _PTHQUERY=""
if [ "$_PTHBASE" = "/me" ] && [ "$MTH" = "GET" ]; then
  _ACCEPT_HDR=$(printf '%s' "${ACCEPT:-}" | tr '[:upper:]' '[:lower:]')
  case "$_ACCEPT_HDR" in
    *application/json*|*json*)
      BODY=$(python3 -c "
import json,sys,os
d={'ip':sys.argv[1],'port':sys.argv[2],'method':sys.argv[3],'httpver':sys.argv[4],
   'host':sys.argv[5],'user_agent':sys.argv[6],'accept':sys.argv[7],
   'accept_language':sys.argv[8],'accept_encoding':sys.argv[9],
   'referer':sys.argv[10],'origin':sys.argv[11],'cookie':sys.argv[12],
   'dnt':sys.argv[13],'x_forwarded_for':sys.argv[14],'connection':sys.argv[15],
   'authorization':sys.argv[16],'content_type':sys.argv[17]}
d={k:v for k,v in d.items() if v and v!='-'}
print(json.dumps(d,indent=2))
" "$PEER" "$PEER_PORT" "$MTH" "$HTTPVER" \
  "$HOST_HDR" "$UA" "$ACCEPT" "$ACCEPT_LANG" "$ACCEPT_ENC" \
  "$REFERER" "$ORIGIN" "$COOKIE" "$DNT_HDR" "$XFF" "$CONNECTION" \
  "$AUTH_HDR" "$CONTENT_TYPE")
      BLEN=$(printf '%s' "$BODY" | wc -c)
      printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
      ;;
    *)
      BODY=$(python3 -c "
import sys,html,json
ip=sys.argv[1]; port=sys.argv[2]; method=sys.argv[3]; httpver=sys.argv[4]
host=sys.argv[5]; ua=sys.argv[6]; accept=sys.argv[7]; accept_lang=sys.argv[8]
accept_enc=sys.argv[9]; referer=sys.argv[10]; origin=sys.argv[11]; cookie=sys.argv[12]
dnt=sys.argv[13]; xff=sys.argv[14]; connection=sys.argv[15]
auth=sys.argv[16]; ct=sys.argv[17]
fields=[('IP',ip+':'+port),('Method',method+' '+httpver),('Host',host),
        ('User-Agent',ua),('Accept',accept),('Accept-Language',accept_lang),
        ('Accept-Encoding',accept_enc),('Referer',referer),('Origin',origin),
        ('Cookie',cookie),('DNT',dnt),('X-Forwarded-For',xff),
        ('Connection',connection),('Authorization',auth),('Content-Type',ct)]
rows=''.join('<tr><td>'+html.escape(k)+'</td><td>'+html.escape(v)+'</td></tr>'
             for k,v in fields if v and v!='-')
print('<html><head><meta charset=\"utf-8\"><title>expose / me</title>'
      '<style>body{font:14px/1.6 ui-monospace,monospace;background:#1a1917;color:#c8c5be;'
      'max-width:700px;margin:2rem auto;padding:0 1rem}'
      'h1{font-size:1rem;color:#84817a;margin-bottom:1.5rem;font-weight:400}'
      'h1 b{color:#c8c5be}'
      'table{border-collapse:collapse;width:100%}'
      'td{padding:.35rem .6rem;border-bottom:1px solid #2a2820;font-size:.8125rem}'
      'td:first-child{color:#5c8abf;width:10rem;white-space:nowrap}'
      'td:last-child{color:#c8c5be;word-break:break-all}'
      '</style></head><body>'
      '<h1><b>expose</b> / me</h1>'
      '<table>'+rows+'</table>'
      '</body></html>')
" "$PEER" "$PEER_PORT" "$MTH" "$HTTPVER" \
  "$HOST_HDR" "$UA" "$ACCEPT" "$ACCEPT_LANG" "$ACCEPT_ENC" \
  "$REFERER" "$ORIGIN" "$COOKIE" "$DNT_HDR" "$XFF" "$CONNECTION" \
  "$AUTH_HDR" "$CONTENT_TYPE")
      BLEN=$(printf '%s' "$BODY" | wc -c)
      printf 'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
      ;;
  esac
elif [ "$_PTHBASE" = "/log" ] && [ "$MTH" = "GET" ]; then
  _SINCE=""
  case "$_PTHQUERY" in *since=*) _SINCE=$(printf '%s' "$_PTHQUERY" | sed 's/.*since=//;s/&.*//') ;; esac
  BODY=$(cat "$EXPOSE_LOGFILE" 2>/dev/null || echo '[]')
  if [ -n "$_SINCE" ]; then
    BODY=$(python3 -c "import json,sys;d=json.loads(sys.stdin.read());print(json.dumps([e for e in d if e.get('n',0)>int(sys.argv[1])]))" "$_SINCE" <<< "$BODY" 2>/dev/null || echo '[]')
  fi
  BLEN=$(printf '%s' "$BODY" | wc -c)
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
elif [ "$PTH" = "/log/clear" ] && [ "$MTH" = "POST" ]; then
  echo '[]' > "$EXPOSE_LOGFILE" 2>/dev/null
  BODY='{"ok":true}'
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "${#BODY}" "$BODY"
elif ([ "$PTH" = "/" ] || [ "$PTH" = "/upload" ]) && [ "$MTH" = "GET" ]; then
  BODY=$(cat "$EXPOSE_UPLOAD_HTML")
  BLEN=$(printf '%s' "$BODY" | wc -c)
  printf 'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
elif [ "$PTH" = "/meta" ] && [ "$MTH" = "GET" ]; then
  BODY=$(python3 -c "import json,os
m={'mode':os.environ.get('EXPOSE_MODE','text')}
if m['mode']=='file':
  m['name']=os.environ.get('EXPOSE_FILENAME','')
  m['size']=int(os.environ.get('EXPOSE_LEN','0'))
  m['mime']=os.environ.get('EXPOSE_MIME','')
elif m['mode']=='text':
  m['size']=int(os.environ.get('EXPOSE_LEN','0'))
print(json.dumps(m))
")
  BLEN=$(printf '%s' "$BODY" | wc -c)
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
elif [ "$PTH" = "/content" ] && [ "$MTH" = "GET" ]; then
  _DISP=""
  [ -n "${EXPOSE_FILENAME:-}" ] && _DISP="Content-Disposition: inline; filename=\"${EXPOSE_FILENAME}\"\r\n"
  printf 'HTTP/1.1 %s %s\r\nContent-Type: %s\r\nContent-Length: %s\r\n%bConnection: close\r\nServer: expose\r\n%b\r\n' \
    "$_RCODE" "$_RREASON" "$EXPOSE_MIME" "$EXPOSE_LEN" "$_DISP" "${EXPOSE_RESP_HEADERS:-}"
  cat "$EXPOSE_CONTENT"
elif [ "$PTH" = "/upload" ] && [ "$MTH" = "POST" ]; then
  export UPLOAD_CT="$CONTENT_TYPE" UPLOAD_CL="$CONTENT_LEN"
  python3 "$EXPOSE_UPLOAD_PY"
elif [ "$PTH" = "/upload/files" ] && [ "$MTH" = "GET" ]; then
  BODY=$(python3 -c "
import os,json,stat as S
d=os.environ['EXPOSE_UPLOAD_DIR']
fs=[]
if os.path.isdir(d):
  for n in sorted(os.listdir(d)):
    p=os.path.join(d,n)
    if os.path.isfile(p):
      s=os.stat(p)
      fs.append({'name':n,'size':s.st_size,'mtime':int(s.st_mtime)})
print(json.dumps(fs))
")
  BLEN=$(printf '%s' "$BODY" | wc -c)
  printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "$BLEN" "$BODY"
elif printf '%s' "$PTH" | grep -q '^/upload/files/' && [ "$MTH" = "GET" ]; then
  FNAME=$(printf '%s' "$PTH" | sed 's|^/upload/files/||' | python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))')
  FPATH="$EXPOSE_UPLOAD_DIR/$FNAME"
  FNAME_SAFE=$(printf '%s' "$FNAME" | sed 's/\.\.//')
  if [ -f "$FPATH" ] && [ "$FNAME_SAFE" = "$FNAME" ]; then
    FSIZE=$(stat -c'%s' "$FPATH" 2>/dev/null || wc -c < "$FPATH")
    FMIME=$(python3 -c "import mimetypes;print(mimetypes.guess_type('$FPATH')[0] or 'application/octet-stream')")
    printf 'HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %s\r\nContent-Disposition: attachment; filename="%s"\r\nConnection: close\r\nServer: expose\r\n\r\n' "$FMIME" "$FSIZE" "$FNAME"
    cat "$FPATH"
  else
    BODY='{"error":"not found"}'
    printf 'HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s' "${#BODY}" "$BODY"
  fi
elif printf '%s' "$PTH" | grep -q '^/upload/files/' && [ "$MTH" = "DELETE" ]; then
  FNAME=$(printf '%s' "$PTH" | sed 's|^/upload/files/||' | python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))')
  FPATH="$EXPOSE_UPLOAD_DIR/$FNAME"
  FNAME_SAFE=$(printf '%s' "$FNAME" | sed 's/\.\.//')
  if [ -f "$FPATH" ] && [ "$FNAME_SAFE" = "$FNAME" ]; then
    rm -f "$FPATH"
    BODY='{"ok":true}'
    printf 'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "${#BODY}" "$BODY"
  else
    BODY='{"error":"not found"}'
    printf 'HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: %s\r\nConnection: close\r\n\r\n%s' "${#BODY}" "$BODY"
  fi
else
  BODY='Not Found'
  printf 'HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: %s\r\nConnection: close\r\nServer: expose\r\n\r\n%s' "${#BODY}" "$BODY"
fi

# ── One-shot: stop server after this request ──
if [ "${EXPOSE_ONCE:-0}" = "1" ]; then
  _SPID=$(cat "${EXPOSE_SOCAT_PIDFILE:-}" 2>/dev/null || echo "")
  if [ -n "$_SPID" ]; then
    sleep 0.3
    kill "$_SPID" 2>/dev/null
  fi
fi

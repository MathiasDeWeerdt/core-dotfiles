# ── Usage ────────────────────────────────────────────────────────────────────
usage() {
  cat >&2 <<EOF
${B}expose${R} v${VERSION}  —  serve text, files, or directories over HTTP

${B}USAGE${R}
    expose [opts] ${CYN}"<text>"${R}         Serve a plain-text response
    expose [opts] ${CYN}-f <file>${R}        Serve a single file
    expose [opts] ${CYN}.${R}                Serve the current directory
    expose [opts] ${CYN}--redirect <url>${R} 302 redirect all requests
    expose [opts] ${CYN}--payload <name>${R} Serve a built-in pentest payload
    expose [opts] ${CYN}--websocket${R}      WebSocket echo server
    expose ${CYN}--replay <logfile>${R}      Replay the last logged request

${B}OPTIONS${R}
    -p, --port ${CYN}<port>${R}     Listen port  (default: ${PORT})
    --bind ${CYN}<addr>${R}        Bind to specific interface  (default: 0.0.0.0)
    --tls               HTTPS with auto-generated self-signed certificate
    --once              Exit after the first request is served
    --log ${CYN}<file>${R}         Persist request log to file (survives exit)
    --allow ${CYN}<cidr>${R}       Restrict access by source IP/CIDR (repeatable)
    --body-limit ${CYN}<bytes>${R}  Max POST body bytes captured in log  (default: 4096, 0=off)
    -m, --more          Verbose logging (all headers, reverse DNS, parsed UA)
    --catch             Request catcher (dump full headers + body)
    --auth ${CYN}<user:pass>${R}   Require HTTP Basic Auth
    --code ${CYN}<N>${R}           HTTP status code for responses (default: 200)
    --header ${CYN}"K: V"${R}     Add response header (repeatable)
    --cors              Add CORS headers (Access-Control-Allow-Origin: *)
    --redirect ${CYN}<url>${R}    302 redirect all requests to target URL
    --payload ${CYN}<name>${R}    Serve a built-in payload (list: expose --help)
    --collect           Collect requests to JSONL log (dump on exit)
    --delay ${CYN}<ms>${R}        Artificial response delay in milliseconds
    --websocket         WebSocket echo server (experimental)
    --replay ${CYN}<log>${R}      Replay the last logged request
    -h, --help          Show this help

${B}BUILT-IN PAYLOADS${R}
    php-reverse-shell   PHP reverse shell (set LHOST, LPORT via -p)
    powershell-reverse  PowerShell reverse shell (one-liner)
    certutil-download   Windows certutil download cradle
    linux-reverse       Bash reverse shell one-liner
    python-reverse      Python reverse shell (pty)

${B}EXAMPLES${R}
    expose "hello world"
    expose --more -p 9000 -f ./notes.txt
    expose .
    echo "secret" | expose -
    expose --catch --code 404
    expose --auth admin:hunter2 -f ./flag.txt
    expose --header "X-Custom: yes" --code 418 "I'm a teapot"
    expose --once -f ./payload.bin
    expose --tls --auth admin:hunter2 -f ./flag.txt
    expose --bind 127.0.0.1 --log ./session.json --catch
    expose --allow 10.10.0.0/16 --allow 192.168.1.0/24 -f ./data.txt
    expose --redirect https://evil.com
    expose --payload powershell-reverse
    expose --collect --log calls.jsonl --catch
    expose --websocket
    expose --cors --code 200 '{"ok":true}'
    expose --delay 500 "slow response"
    expose --replay ./session.json
EOF
}
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

${B}OPTIONS${R}
    -p, --port ${CYN}<port>${R}     Listen port  (default: ${PORT})
    --bind ${CYN}<addr>${R}        Bind to specific interface  (default: 0.0.0.0)
    -m, --more          Verbose logging (all headers, reverse DNS, parsed UA)
    --catch             Request catcher (dump full headers + body)
    --code ${CYN}<N>${R}           HTTP status code for responses (default: 200)
    --header ${CYN}"K: V"${R}     Add response header (repeatable)
    --cors              Add CORS headers (Access-Control-Allow-Origin: *)
    --redirect ${CYN}<url>${R}    302 redirect all requests to target URL
    --payload ${CYN}<name>${R}    Serve a built-in payload (list: expose --help)
    --collect           Collect requests to JSONL log (dump on exit)
    --delay ${CYN}<ms>${R}        Artificial response delay in milliseconds
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
    expose --header "X-Custom: yes" --code 418 "I'm a teapot"
    expose --bind 127.0.0.1 --catch
    expose --redirect https://evil.com
    expose --payload powershell-reverse
    expose --collect --catch
    expose --cors --code 200 '{"ok":true}'
    expose --delay 500 "slow response"
EOF
}

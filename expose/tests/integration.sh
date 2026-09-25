#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
EXPOSE="$ROOT/dist/expose"
TEST_HOME=$(mktemp -d /tmp/expose-tests.XXXXXX)
export HOME="$TEST_HOME"

cleanup_test() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    pkill -TERM -P "$SERVER_PID" 2>/dev/null || true
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TEST_HOME"
}
trap cleanup_test EXIT

free_port() {
  python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

stop_server() {
  pkill -TERM -P "$SERVER_PID" 2>/dev/null || true
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID"
  SERVER_PID=""
}

request_once() {
  local path="$1"
  shift
  local port
  port=$(free_port)
  "$EXPOSE" --bind 127.0.0.1 --port "$port" "$@" \
    >"$TEST_HOME/server.out" 2>"$TEST_HOME/server.err" &
  SERVER_PID=$!
  for _ in {1..50}; do
    if curl -fsS "http://127.0.0.1:$port$path" 2>/dev/null; then
      stop_server
      return
    fi
    sleep 0.05
  done
  echo "server did not become ready" >&2
  return 1
}

assert_eq() {
  local expected="$1" actual="$2"
  [[ "$actual" == "$expected" ]] || {
    printf 'expected: %q\nactual:   %q\n' "$expected" "$actual" >&2
    return 1
  }
}

make -C "$ROOT" build >/dev/null
bash -n "$ROOT/dist/expose-online"
cmp -s "$ROOT/src/expose-online.sh" "$ROOT/dist/expose-online"

assert_eq "hello" "$(request_once /content hello)"
assert_eq "health-test" "$(EXPOSE_HEALTH_TOKEN=health-test request_once \
  '/.expose-health?session=health-test' --redirect https://example.test)"
assert_eq "health-test" "$(EXPOSE_HEALTH_TOKEN=health-test request_once \
  '/.expose-health?session=health-test' --code 418 hello)"
assert_eq '{"mode": "text", "size": 5}' "$(request_once /meta hello)"
upload_page=$(request_once / hello)
[[ "$upload_page" == *'class="expose-mark"'* ]]
[[ "$upload_page" == *'class="top-nav"'* ]]
[[ "$upload_page" == *'id="overview"'* ]]
[[ "$upload_page" == *'id="traffic"'* ]]
[[ "$upload_page" == *'id="files" hidden'* ]]
[[ "$upload_page" == *'id="chat" hidden'* ]]
[[ "$upload_page" == *'aria-label="Main navigation"'* ]]
[[ "$upload_page" != *'@@CSS@@'* ]]
me_page=$(request_once /me hello)
[[ "$me_page" == *'class="expose-mark"'* ]]
[[ "$me_page" != *'{{LOGO}}'* ]]
[[ "$me_page" != *'@@CSS@@'* ]]
[[ "$me_page" == *'<summary>Browser and device details</summary>'* ]]

sample="$TEST_HOME/sample.txt"
printf 'file body' > "$sample"
assert_eq "file body" "$(request_once /content --file "$sample")"

mkdir -p "$TEST_HOME/shared"
printf 'listed' > "$TEST_HOME/shared/item.txt"
(
  cd "$TEST_HOME/shared"
  result=$(request_once /ls .)
  [[ "$result" == *'"name": "item.txt"'* ]]
)

port=$(free_port)
"$EXPOSE" --bind 127.0.0.1 --port "$port" \
  --redirect https://example.test >"$TEST_HOME/server.out" 2>"$TEST_HOME/server.err" &
SERVER_PID=$!
for _ in {1..50}; do
  location=$(curl -sS -o /dev/null -w '%{redirect_url}' "http://127.0.0.1:$port/anything" 2>/dev/null) && break
  sleep 0.05
done
stop_server
assert_eq "https://example.test/" "$location"

port=$(free_port)
"$EXPOSE" --bind 127.0.0.1 --port "$port" --code 418 \
  --header "X-Expose-Test: yes" teapot >"$TEST_HOME/server.out" 2>"$TEST_HOME/server.err" &
SERVER_PID=$!
for _ in {1..50}; do
  response=$(curl -sS -D - "http://127.0.0.1:$port/content" 2>/dev/null) && break
  sleep 0.05
done
stop_server
[[ "$response" == HTTP/1.1\ 418* ]]
[[ "$response" == *$'X-Expose-Test: yes\r'* ]]
[[ "$response" == *$'\r\n\r\nteapot' ]]

printf 'uploaded body' > "$TEST_HOME/upload.txt"
port=$(free_port)
"$EXPOSE" --bind 127.0.0.1 --port "$port" upload-test \
  >"$TEST_HOME/server.out" 2>"$TEST_HOME/server.err" &
SERVER_PID=$!
for _ in {1..50}; do
  upload_result=$(curl -fsS -F "files=@$TEST_HOME/upload.txt" \
    "http://127.0.0.1:$port/upload" 2>/dev/null) && break
  sleep 0.05
done
stop_server
assert_eq '{"saved": ["upload.txt"], "count": 1}' "$upload_result"
assert_eq "uploaded body" "$(<"$TEST_HOME/Downloads/expose/upload.txt")"

port=$(free_port)
"$EXPOSE" --bind 127.0.0.1 --port "$port" shutdown-test \
  >"$TEST_HOME/server.out" 2>"$TEST_HOME/server.err" &
SERVER_PID=$!
listener_pid=""
for _ in {1..50}; do
  listener_pid=$(ss -tlnp "sport = :$port" 2>/dev/null \
    | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
  [[ -n "$listener_pid" ]] && break
  sleep 0.05
done
[[ -n "$listener_pid" ]]
kill "$listener_pid"
wait "$SERVER_PID"
SERVER_PID=""
! rg -q 'python3 <<|Terminated|import http.server' "$TEST_HOME/server.err"

# Online output uses the paired binary, even through a symlink with an older
# expose on PATH. Stub SSH so this check never opens a public tunnel.
mkdir -p "$TEST_HOME/bin"
cat > "$TEST_HOME/bin/ssh" <<'SH'
#!/usr/bin/env bash
[[ " $* " == *' -N '* ]] || exit 0
exec sleep 30
SH
cat > "$TEST_HOME/bin/expose" <<'SH'
#!/usr/bin/env bash
echo 'unexpected expose from PATH' >&2
exit 1
SH
cat > "$TEST_HOME/bin/curl" <<'SH'
#!/usr/bin/env bash
args=()
for arg in "$@"; do
  args+=("${arg/https:\/\/singlecore.dev/http:\/\/127.0.0.1:$TUNNEL_LPORT}")
done
exec /usr/bin/curl "${args[@]}"
SH
chmod +x "$TEST_HOME/bin/ssh" "$TEST_HOME/bin/expose" "$TEST_HOME/bin/curl"
ln -s "$ROOT/dist/expose-online" "$TEST_HOME/bin/expose-online"
port=$(free_port)
PATH="$TEST_HOME/bin:$PATH" TUNNEL_LPORT="$port" \
  "$TEST_HOME/bin/expose-online" online-test \
  >"$TEST_HOME/online.out" 2>"$TEST_HOME/online.err" &
SERVER_PID=$!
for _ in {1..50}; do
  rg -q 'Ctrl\+C to stop' "$TEST_HOME/online.err" && break
  sleep 0.05
done
assert_eq "online-test" "$(curl -fsS "http://127.0.0.1:$port/content")"
console_status=$(curl -fsS "http://127.0.0.1:$port/console/status")
[[ "$console_status" == *'"enabled": true'* ]]
assert_eq '[]' "$(curl -fsS "http://127.0.0.1:$port/console/sessions")"
[[ ! -e "$TEST_HOME/.expose/console-$port.key" ]]
rg -q '^  expose online$'  "$TEST_HOME/online.err"
rg -q '^  Public  https://singlecore.dev$' "$TEST_HOME/online.err"
rg -q "^  Local   http://127.0.0.1:$port$" "$TEST_HOME/online.err"
rg -q 'Ctrl\+C to stop' "$TEST_HOME/online.err"
rg -q 'Connected — public URL verified' "$TEST_HOME/online.err"
! rg -q '/.expose-health' "$TEST_HOME/online.err"
! rg -q '▲|█|Waiting for connections|Tunnel |unexpected expose' "$TEST_HOME/online.err"
cat "$TEST_HOME/online.err"
listener_pid=$(ss -tlnp "sport = :$port" 2>/dev/null \
  | awk 'NR>1{match($0,/pid=([0-9]+)/,a); if(a[1]) print a[1]}' | head -1)
kill "$SERVER_PID"
kill "$listener_pid" 2>/dev/null || true
wait "$SERVER_PID" || true
SERVER_PID=""

python3 - "$TEST_HOME/.expose/requests.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as log_file:
    entries = json.load(log_file)
assert entries
assert any(entry["path"] == "/content" for entry in entries)
assert not any(entry["path"].startswith("/.expose-health") for entry in entries)
PY

echo "integration tests passed"

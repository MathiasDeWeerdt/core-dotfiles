# ── Parse arguments ──────────────────────────────────────────────────────────
# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)   usage; exit 0 ;;
    -m|--more)   VERBOSE=1; shift ;;
    -p|--port)   [[ -n "${2:-}" ]] || die "Missing port after $1"; PORT="$2"; shift 2 ;;
    -f|--file)   [[ -n "${2:-}" ]] || die "Missing filename after $1"; MODE="file"; TARGET="$2"; shift 2 ;;
    --catch)     CATCH=1; shift ;;
    --once)      ONCE=1; shift ;;
    --tls)       TLS=1; shift ;;
    --log)       [[ -n "${2:-}" ]] || die "Missing path after $1"; LOGFILE="$2"; shift 2 ;;
    --bind)      [[ -n "${2:-}" ]] || die "Missing address after $1"; BIND="$2"; shift 2 ;;
    --allow)      [[ -n "${2:-}" ]] || die "Missing CIDR after $1"; ALLOWED_NETS+=("$2"); shift 2 ;;
    --body-limit) [[ -n "${2:-}" ]] || die "Missing bytes after $1"; BODY_LIMIT="$2"; shift 2 ;;
    --auth)      [[ -n "${2:-}" ]] || die "Missing user:pass after $1"; AUTH="$2"; shift 2 ;;
    --code)      [[ -n "${2:-}" ]] || die "Missing status code after $1"; RESP_CODE="$2"; shift 2 ;;
    --header)    [[ -n "${2:-}" ]] || die "Missing header after $1"; RESP_HEADERS+=("$2"); shift 2 ;;
    --cors)      CORS=1; shift ;;
    --redirect)  [[ -n "${2:-}" ]] || die "Missing URL after $1"; REDIRECT="$2"; MODE="redirect"; shift 2 ;;
    --payload)   [[ -n "${2:-}" ]] || die "Missing payload name after $1"; PAYLOAD="$2"; MODE="payload"; shift 2 ;;
    --collect)   COLLECT=1; shift ;;
    --delay)     [[ -n "${2:-}" ]] || die "Missing milliseconds after $1"; DELAY_MS="$2"; shift 2 ;;
    --websocket) WEBSOCKET=1; MODE="websocket"; shift ;;
    --replay)    [[ -n "${2:-}" ]] || die "Missing logfile after $1"; MODE="replay"; TARGET="$2"; shift 2 ;;
    .)           MODE="dir"; shift ;;
    -)           MODE="stdin"; shift ;;
    -*)          die "Unknown option: $1" ;;
    *)           MODE="text"; TARGET="$1"; shift ;;
  esac
done

# Handle stdin mode
if [[ "$MODE" == "stdin" ]]; then
  TARGET=$(cat)
  MODE="text"
fi

# Catch mode: force verbose, default to catch mode if no other mode
[[ $CATCH -eq 1 ]] && VERBOSE=1
[[ $CATCH -eq 1 && -z "$MODE" ]] && MODE="catch"

# Collect mode: force verbose, default to catch mode if no other mode
[[ $COLLECT -eq 1 ]] && VERBOSE=1
[[ $COLLECT -eq 1 && -z "$MODE" ]] && MODE="catch"

[[ -n "$MODE" ]] || { usage; exit 1; }

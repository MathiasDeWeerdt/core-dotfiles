# ── Banner ────────────────────────────────────────────────────────────────────
LOCAL_IP=$(get_local_ip)
_SCHEME="http"
_BINDHOST="127.0.0.1"
[[ "$BIND" != "0.0.0.0" ]] && _BINDHOST="$BIND"

mode_label() {
  case "$MODE" in
    text)
      echo "${B}text${R} response  ${D}(${#TARGET} bytes)${R}" ;;
    catch)
      echo "${B}catch${R} mode  ${D}(request catcher)${R}" ;;
    file)
      local sz mime
      sz=$(stat -c'%s' "$TARGET" 2>/dev/null || wc -c < "$TARGET")
      mime=$(file -b --mime-type "$TARGET" 2>/dev/null || echo "unknown")
      echo "${B}file${R}  ${CYN}$(realpath "$TARGET")${R}  ${D}(${mime}, ${sz} bytes)${R}" ;;
    dir)
      echo "${B}directory${R}  ${CYN}$(pwd)${R}" ;;
    redirect)
      echo "${B}redirect${R}  ${D}(${REDIRECT})${R}" ;;
    payload)
      echo "${B}payload${R}  ${CYN}${PAYLOAD}${R}" ;;
  esac
}

if [[ "${EXPOSE_NO_BANNER:-0}" != "1" ]]; then
  cat >&2 <<EOF

  ${B}${GRN}▲ expose${R}  ${D}v${VERSION}${R}
  ${D}──────────────────────────────────────────${R}
  ${BLU}Mode${R}     $(mode_label)
  ${BLU}Local${R}    ${U}${_SCHEME}://${_BINDHOST}:${PORT}${R}
  ${BLU}Network${R}  ${U}${_SCHEME}://${LOCAL_IP}:${PORT}${R}
  ${BLU}Upload${R}   ${U}${_SCHEME}://${LOCAL_IP}:${PORT}/upload${R}
  ${BLU}Me${R}       ${U}${_SCHEME}://${LOCAL_IP}:${PORT}/me${R}$(
    [[ $VERBOSE -eq 1 ]]            && printf '\n  %sVerbose%s  %senabled  (--more)%s'       "$YLW" "$R" "$D" "$R"
    [[ $CATCH -eq 1 ]]              && printf '\n  %sCatch%s    %senabled  (--catch)%s'      "$YLW" "$R" "$D" "$R"
    [[ "$BIND" != "0.0.0.0" ]]      && printf '\n  %sBind%s     %s%s%s'                       "$YLW" "$R" "$D" "$BIND" "$R"
    [[ -n "$RESP_CODE" ]]           && printf '\n  %sCode%s     %s%s%s'                       "$YLW" "$R" "$D" "$RESP_CODE" "$R"
    (( ${#RESP_HEADERS[@]} ))       && printf '\n  %sHeaders%s  %s%d custom%s'               "$YLW" "$R" "$D" "${#RESP_HEADERS[@]}" "$R"
    [[ $CORS -eq 1 ]]               && printf '\n  %sCORS%s     %senabled%s'                  "$YLW" "$R" "$D" "$R"
    [[ -n "$REDIRECT" ]]             && printf '\n  %sRedirect%s %s→ %s%s'                     "$YLW" "$R" "$D" "$REDIRECT" "$R"
    [[ -n "$PAYLOAD" ]]              && printf '\n  %sPayload%s  %s%s%s'                       "$YLW" "$R" "$D" "$PAYLOAD" "$R"
    [[ $COLLECT -eq 1 ]]            && printf '\n  %sCollect%s  %senabled  (--collect)%s'     "$YLW" "$R" "$D" "$R"
    [[ $DELAY_MS -gt 0 ]]           && printf '\n  %sDelay%s    %s%s ms%s'                     "$YLW" "$R" "$D" "$DELAY_MS" "$R"
  )
  ${D}──────────────────────────────────────────${R}
  ${D}Ctrl+C to stop${R}

EOF

  log "${GRN}Waiting for connections…${R}"
  echo >&2
fi

# ── Request counter ───────────────────────────────────────────────────────────

# ── Database viewer ───────────────────────────────────────────────────────────
database_summary() {
  local db="$1"
  sqlite3 -readonly -header -box "$db" "
    select 'requests' as table_name, count(*) as rows from requests
    union all
    select 'fingerprints', count(*) from fingerprints;
  "
}

database_tables() {
  local db="$1"
  sqlite3 -readonly -separator $'\t' "$db" "
    select name,
           case name
             when 'requests' then (select count(*) from requests)
             when 'fingerprints' then (select count(*) from fingerprints)
             else 0
           end,
           case name
             when 'requests' then 'HTTP request history'
             when 'fingerprints' then 'Browser fingerprint reports'
             else 'SQLite table'
           end
    from sqlite_master
    where type = 'table' and name not like 'sqlite_%'
    order by name;
  "
}

database_rows() {
  local db="$1" table="$2"
  case "$table" in
    requests)
      sqlite3 -readonly -separator $'\t' "$db" "
        select id, time, method, path, ip, mode
        from requests order by id desc;
      "
      ;;
    fingerprints)
      sqlite3 -readonly -separator $'\t' "$db" "
        select id, time, visitor_id, ip, page
        from fingerprints order by id desc;
      "
      ;;
  esac
}

database_view() {
  local db="$1" table selection row_id
  export EXPOSE_VIEW_DB="$db"

  if [[ $DB_SUMMARY -eq 1 ]]; then
    database_summary "$db"
    return
  fi

  while true; do
    selection=$(database_tables "$db" | fzf \
      --delimiter=$'\t' \
      --with-nth=1,2,3 \
      --header='TABLE                         ROWS  DESCRIPTION' \
      --header-lines=0 \
      --prompt='database › ' \
      --pointer='›' \
      --layout=reverse \
      --height=100% \
      --border=rounded \
      --info=inline \
      --no-multi) || break

    table="${selection%%$'\t'*}"
    case "$table" in
      requests)
        selection=$(database_rows "$db" "$table" | fzf \
          --delimiter=$'\t' \
          --with-nth=1,2,3,4,5,6 \
          --header='ID  TIME      METHOD  PATH  IP  MODE' \
          --prompt='requests › ' \
          --pointer='›' \
          --layout=reverse \
          --height=100% \
          --border=rounded \
          --info=inline \
          --no-multi \
          --preview-window='right,55%,wrap' \
          --preview='sqlite3 -readonly -header -box "$EXPOSE_VIEW_DB" "select * from requests where id={1};"') || continue
        ;;
      fingerprints)
        selection=$(database_rows "$db" "$table" | fzf \
          --delimiter=$'\t' \
          --with-nth=1,2,3,4,5 \
          --header='ID  TIME      VISITOR  IP  PAGE' \
          --prompt='fingerprints › ' \
          --pointer='›' \
          --layout=reverse \
          --height=100% \
          --border=rounded \
          --info=inline \
          --no-multi \
          --preview-window='right,60%,wrap' \
          --preview='sqlite3 -readonly -header -box "$EXPOSE_VIEW_DB" "select * from fingerprints where id={1};"') || continue
        ;;
      *)
        continue
        ;;
    esac

    row_id="${selection%%$'\t'*}"
    [[ "$row_id" =~ ^[0-9]+$ ]] || continue
    clear
    sqlite3 -readonly -header -box "$db" "select * from \"$table\" where id=$row_id;"
    printf '\nPress any key to return…'
    read -rsn1
  done
}

if [[ "$MODE" == "db" ]]; then
  EXPOSE_NO_BANNER=1
  database_view "$TARGET"
  exit
fi

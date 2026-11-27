# Operator commands attach to an existing instance without starting a server.
case "${1:-}" in
  sessions|attach|login|logout|invite|proxychains)
    exec 3<&0
    export EXPOSE_OPERATOR_STDIN_FD=3
    exec python3 - "$@" <<'OPERATORPY'
@@INJECT:assets/operator.py@@
OPERATORPY
    ;;
esac

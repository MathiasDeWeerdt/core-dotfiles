# ── Banner ────────────────────────────────────────────────────────────────────
LOCAL_IP=$(get_local_ip)
_SCHEME="http"
[[ $TLS -eq 1 ]] && _SCHEME="https"
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
  esac
}

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
    [[ $ONCE -eq 1 ]]               && printf '\n  %sOnce%s     %sexit after first request%s' "$YLW" "$R" "$D" "$R"
    [[ $TLS -eq 1 ]]                && printf '\n  %sTLS%s      %sself-signed cert%s'         "$YLW" "$R" "$D" "$R"
    [[ "$BIND" != "0.0.0.0" ]]      && printf '\n  %sBind%s     %s%s%s'                       "$YLW" "$R" "$D" "$BIND" "$R"
    [[ -n "$LOGFILE" ]]             && printf '\n  %sLog%s      %s%s%s'                       "$YLW" "$R" "$D" "$LOGFILE" "$R"
    [[ -n "$_EXPOSE_ALLOW" ]]       && printf '\n  %sAllow%s    %s%s%s'                       "$YLW" "$R" "$D" "$_EXPOSE_ALLOW" "$R"
    [[ -n "$AUTH" ]]                && printf '\n  %sAuth%s     %s%s:••••  (--auth)%s'        "$YLW" "$R" "$D" "${AUTH%%:*}" "$R"
    [[ -n "$RESP_CODE" ]]           && printf '\n  %sCode%s     %s%s%s'                       "$YLW" "$R" "$D" "$RESP_CODE" "$R"
    (( ${#RESP_HEADERS[@]} ))       && printf '\n  %sHeaders%s  %s%d custom%s'               "$YLW" "$R" "$D" "${#RESP_HEADERS[@]}" "$R"
  )
  ${D}──────────────────────────────────────────${R}
  ${D}Ctrl+C to stop${R}

EOF

# ── QR code ───────────────────────────────────────────────────────────────────
_QR_URL="${_SCHEME}://${LOCAL_IP}:${PORT}"
python3 - "$_QR_URL" <<'PYQR' 2>&1 || true
import sys

url = sys.argv[1]

# Try qrcode library first (most accurate)
try:
    import qrcode, io
    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url); qr.make(fit=True)
    mat = qr.get_matrix()
    lines = []
    for r in range(0, len(mat) - 1, 2):
        row = ""
        for c in range(len(mat[r])):
            t = mat[r][c]; b = mat[r+1][c] if r+1 < len(mat) else False
            if t and b:   row += "█"
            elif t:       row += "▀"
            elif b:       row += "▄"
            else:         row += " "
        lines.append("  " + row)
    sys.stdout.write("\n" + "\n".join(lines) + "\n\n")
    sys.exit(0)
except ImportError:
    pass

# Minimal self-contained QR encoder (byte mode, ECC-L, auto version 2-6)
# Reed-Solomon GF(256) with generator poly x^8+x^4+x^3+x^2+1 (0x11d)
GF = [0]*256; GF_INV = [0]*256; GF_LOG = [0]*256; GF_EXP = [0]*512
_x = 1
for _i in range(255):
    GF_EXP[_i] = _x; GF_LOG[_x] = _i; _x = (_x<<1)^(0x11d if _x&0x80 else 0); _x &= 0xFF
for _i in range(255,512): GF_EXP[_i] = GF_EXP[_i-255]

def gf_mul(a,b):
    if a==0 or b==0: return 0
    return GF_EXP[(GF_LOG[a]+GF_LOG[b])%255]

def rs_gen_poly(n):
    g=[1]
    for i in range(n):
        g2=[0]*(len(g)+1)
        for j,c in enumerate(g):
            g2[j]=c^gf_mul(GF_EXP[i],g2[j]) if j<len(g2) else 0
        for j,c in enumerate(g): g2[j+1]^=c
        g=g2
        # cleaner: multiply (x - alpha^i)
    # redo correctly
    g=[1]
    for i in range(n):
        ng=[0]*(len(g)+1)
        for j,c in enumerate(g):
            ng[j]^=c
            ng[j+1]^=gf_mul(c,GF_EXP[i])
        g=ng
    return g

def rs_encode(data, n_ec):
    gen=rs_gen_poly(n_ec)
    msg=list(data)+[0]*n_ec
    for i in range(len(data)):
        if msg[i]==0: continue
        for j in range(1,len(gen)):
            msg[i+j]^=gf_mul(gen[j],msg[i])
    return msg[len(data):]

# QR versions: (ver, total_codewords, data_codewords_ecc_L, ec_codewords_per_block, blocks)
# Simplified to versions 2-6 byte mode ECC-L
VERSIONS = [
    (2, 44, 28, 16, 1),
    (3, 70, 44, 26, 1),
    (4, 100, 64, 36, 2),
    (5, 134, 86, 48, 2),
    (6, 172, 108, 64, 2),
]

data = url.encode('utf-8')
nd = len(data)

# pick version
ver_info = None
for v,total,dc,ec,blk in VERSIONS:
    if nd <= dc-3: ver_info=(v,total,dc,ec,blk); break
if ver_info is None:
    sys.stdout.write("  (URL too long for inline QR — install 'qrcode' package)\n\n")
    sys.exit(0)

ver,total,dc,ec_count,blocks = ver_info
size = ver*4+17

# encode data bits
bits=[]
def push(v,n):
    for i in range(n-1,-1,-1): bits.append((v>>i)&1)

push(0b0100,4)  # byte mode
push(nd,8)
for b in data:
    push(b,8)
push(0,4)  # terminator
# pad to byte boundary
while len(bits)%8: bits.append(0)
# pad codewords
pad=[0xEC,0x11]
cw=bytes(int(''.join(str(b) for b in bits[i:i+8]),2) for i in range(0,len(bits),8))
cw=list(cw)
pi=0
while len(cw)<dc: cw.append(pad[pi%2]); pi+=1

# interleave blocks (simplified, all in one block for v<=3)
ec_bytes=rs_encode(cw,ec_count)
final=cw+ec_bytes

# bits stream
stream=[]
for byte in final:
    for i in range(7,-1,-1): stream.append((byte>>i)&1)
# remainder bits
rem={2:7,3:7,4:7,5:7,6:7}
stream+=[0]*rem.get(ver,0)

# build matrix
mat=[[None]*size for _ in range(size)]

def rect(r,c,h,w,v):
    for i in range(h):
        for j in range(w):
            if 0<=r+i<size and 0<=c+j<size:
                mat[r+i][c+j]=v

def finder(r,c):
    rect(r,c,7,7,1); rect(r+1,c+1,5,5,0); rect(r+2,c+2,3,3,1)

finder(0,0); finder(0,size-7); finder(size-7,0)
# separators
for i in range(8):
    for pos in [(7,i),(i,7),(7,size-8+i),(i,size-8),(size-8+i,7),(size-7+i,size-8)]:
        r2,c2=pos
        if 0<=r2<size and 0<=c2<size and mat[r2][c2] is None:
            mat[r2][c2]=0

# timing
for i in range(8,size-8):
    if mat[6][i] is None: mat[6][i]=(i%2==0)
    if mat[i][6] is None: mat[i][6]=(i%2==0)

# alignment patterns (ver>=2)
ALIGN={2:[6,18],3:[6,22],4:[6,26,6+20],5:[6,30],6:[6,34]}
ap=ALIGN.get(ver,[])
for r2 in ap:
    for c2 in ap:
        if mat[r2][c2] is not None: continue
        for dr in range(-2,3):
            for dc2 in range(-2,3):
                v=1 if (abs(dr)==2 or abs(dc2)==2 or (dr==0 and dc2==0)) else 0
                if mat[r2+dr][c2+dc2] is None: mat[r2+dr][c2+dc2]=v

# format info area (reserve)
for i in range(9):
    if mat[8][i] is None: mat[8][i]=0
    if mat[i][8] is None: mat[i][8]=0
for i in range(8):
    if mat[8][size-1-i] is None: mat[8][size-1-i]=0
    if mat[size-1-i][8] is None: mat[size-1-i][8]=0
mat[size-8][8]=1  # dark module

# place data bits
idx=0; up=True
c=size-1
while c>0:
    if c==6: c-=1
    col_pair=[c,c-1]
    rows=range(size-1,-1,-1) if up else range(size)
    for r2 in rows:
        for cc in col_pair:
            if mat[r2][cc] is None:
                if idx<len(stream): mat[r2][cc]=stream[idx]; idx+=1
                else: mat[r2][cc]=0
    up=not up; c-=2

# mask pattern 0: (r+c)%2==0
def mask0(r,c): return (r+c)%2==0
for r2 in range(size):
    for c2 in range(size):
        if mat[r2][c2] is None: mat[r2][c2]=0

# apply mask to data modules
# track which are fixed (finders, separators, timing, alignment, format, dark)
fixed=[[False]*size for _ in range(size)]
# finders (top-left, top-right, bottom-left) + separators (8x8)
for i in range(9):
    for j in range(9):
        if 0<=i<size and 0<=j<size: fixed[i][j]=True
        if 0<=i<size and 0<=size-1-j<size: fixed[i][size-1-j]=True
        if 0<=size-1-i<size and 0<=j<size: fixed[size-1-i][j]=True
# timing
for i in range(size): fixed[6][i]=True; fixed[i][6]=True
# alignment patterns (already placed in mat)
for r2 in ap:
    for c2 in ap:
        for dr in range(-2,3):
            for dc2 in range(-2,3):
                if 0<=r2+dr<size and 0<=c2+dc2<size: fixed[r2+dr][c2+dc2]=True
# format info
for i in range(9):
    if 0<=8<size and 0<=i<size: fixed[8][i]=True; fixed[i][8]=True
    if 0<=8<size and 0<=size-1-i<size: fixed[8][size-1-i]=True
    if 0<=size-1-i<size and 0<=8<size: fixed[size-1-i][8]=True
# dark module
fixed[size-8][8]=True
for r2 in range(size):
    for c2 in range(size):
        if not fixed[r2][c2] and mat[r2][c2] is not None:
            if mask0(r2,c2): mat[r2][c2]^=1

# format string for mask=0, ECC-L (indicator 01)
# ECC-L + mask 0 = 0b01_000 = data 8, remainder from generator 10100110111
fmt_data = (0b01<<3)|0b000  # 8
gen=0b10100110111
fmt=fmt_data<<10
for i in range(9,-1,-1):
    if fmt>>(i+10): break
for i in range(14,9,-1):
    if (fmt>>i)&1: fmt^=(gen<<(i-10))
fmt_ec=((fmt_data<<10)|fmt)^0b101010000010010
# apply format bits
fmt_bits=[(fmt_ec>>i)&1 for i in range(14,-1,-1)]
pos1=[(8,0),(8,1),(8,2),(8,3),(8,4),(8,5),(8,7),(8,8),(7,8),(5,8),(4,8),(3,8),(2,8),(1,8),(0,8)]
pos2=[(size-1,8),(size-2,8),(size-3,8),(size-4,8),(size-5,8),(size-6,8),(size-7,8),
      (8,size-8),(8,size-7),(8,size-6),(8,size-5),(8,size-4),(8,size-3),(8,size-2),(8,size-1)]
for i,(r2,c2) in enumerate(pos1): mat[r2][c2]=fmt_bits[i]
for i,(r2,c2) in enumerate(pos2): mat[r2][c2]=fmt_bits[i]

# render with half-block chars
lines=[]
# add quiet zone row at top
qz_row=" "*(size+4)
lines.append("  "+qz_row)
for r2 in range(0,size+(size%2),2):
    row="  "+"  "  # left quiet zone (2 chars = 2 modules)
    for c2 in range(size):
        t=mat[r2][c2] if r2<size else False
        b=mat[r2+1][c2] if r2+1<size else False
        t=bool(t); b=bool(b)
        if t and b:   row+="█"
        elif t:       row+="▀"
        elif b:       row+="▄"
        else:         row+=" "
    row+="  "  # right quiet zone
    lines.append(row)
lines.append("  "+qz_row)
sys.stdout.write("\n"+"\n".join(lines)+"\n\n")
PYQR

log "${GRN}Waiting for connections…${R}"
echo >&2

# ── Request counter ───────────────────────────────────────────────────────────

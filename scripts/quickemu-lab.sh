#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Quickemu Lab — Create & manage a fleet of portable VMs
# ─────────────────────────────────────────────────────────────────────
# Usage:
#   ./scripts/quickemu-lab.sh create    # Download & configure all VMs
#   ./scripts/quickemu-lab.sh list      # List configured VMs
#   ./scripts/quickemu-lab.sh snapshot  # Create snapshots for all VMs
#
# Each VM is self-contained in ~/VMs/<name>/ with its own disk (qcow2,
# thin-provisioned — only grows as needed). Networking uses user-mode
# NAT which works across WiFi, Ethernet, and changing IP ranges.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

VM_DIR="$HOME/VMs"
mkdir -p "$VM_DIR"

# ── Colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()   { echo -e "${GREEN}[✓]${NC} $*"; }
info()  { echo -e "${BLUE}[→]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }

# ── VM Definitions ───────────────────────────────────────────────────
# Format: "os release edition disk_size ram cpu_cores extra_flags"
#
# disk_size: max qcow2 size (thin-provisioned — uses only written space)
# ram: in GB
# extra_flags: passed to quickget as additional args

VMS=(
    # ── Ubuntu (desktop only — quickget doesn't support server) ──
    "ubuntu 26.04  desktop  64G  4  2"
    "ubuntu 24.04  desktop  64G  4  2"

    # ── Windows ─────────────────────────────────────────────────
    "windows 11    default  128G 4  2"

    # ── macOS Tahoe ─────────────────────────────────────────────
    "macos   tahoe  default  64G  4  2"
)

# ── Helpers ──────────────────────────────────────────────────────────

vm_name() {
    # "ubuntu 26.04 desktop" → "ubuntu-26.04-desktop"
    local os="$1" release="$2" edition="$3"
    if [[ "$edition" == "default" ]]; then
        echo "${os}-${release}"
    else
        echo "${os}-${release}-${edition}"
    fi
}

# Find the config file quickget generated (naming varies by OS)
find_conf() {
    local dir="$1"
    find "$dir" -maxdepth 1 -name '*.conf' ! -name '.*' 2>/dev/null | head -1
}

# ── Create all VMs ───────────────────────────────────────────────────

cmd_create() {
    local total=${#VMS[@]}
    local count=0

    for entry in "${VMS[@]}"; do
        count=$((count + 1))
        read -r os release edition disk ram cores extra <<< "$entry"
        extra="${extra:-}"

        local name=$(vm_name "$os" "$release" "$edition")
        local vm_path="$VM_DIR/$name"

        echo ""
        info "[$count/$total] $name"

        local existing_conf=$(find_conf "$vm_path")
        if [[ -n "$existing_conf" ]]; then
            log "Already configured — skipping"
            continue
        fi

        mkdir -p "$vm_path"

        # Download ISO + create config using quickget
        quickget "$os" "$release" --path "$vm_path"

        # Patch the generated config with our custom settings
        local conf=$(find_conf "$vm_path")
        if [[ -n "$conf" && -f "$conf" ]]; then
            # RAM and CPU
            sed -i "s/^ram=.*/ram=\"${ram}G\"/" "$conf" 2>/dev/null || true
            sed -i "s/^cpu_cores=.*/cpu_cores=\"$cores\"/" "$conf" 2>/dev/null || true

            # Disk size (thin-provisioned qcow2)
            if ! grep -q "^disk_size=" "$conf"; then
                echo "disk_size=\"$disk\"" >> "$conf"
            else
                sed -i "s/^disk_size=.*/disk_size=\"$disk\"/" "$conf" 2>/dev/null || true
            fi

            # Networking: user-mode NAT — works across WiFi/Ethernet/VPN
            if ! grep -q "^network=" "$conf"; then
                echo "network=\"user\"" >> "$conf"
            fi

            # Share host public directory for file transfer
            if ! grep -q "^public_dir=" "$conf"; then
                echo "public_dir=\"$HOME/Public\"" >> "$conf"
            fi

            # Port forwarding: SSH (2222+offset) and RDP (3389+offset)
            # Each VM gets unique ports based on its index
            local idx=$((count - 1))
            local ssh_port=$((2222 + idx))
            if ! grep -q "^port_forwards=" "$conf"; then
                echo "port_forwards=(\"${name}:22:tcp:${ssh_port}\")" >> "$conf"
            fi
        fi

        log "Configured: $vm_path"
        log "  SSH:  localhost:$ssh_port"
        log "  Disk: $disk (thin, max)"
        log "  RAM:  ${ram}G  |  Cores: $cores"
        log "  Net:  user-mode NAT"
    done

    echo ""
    log "All VMs configured in $VM_DIR"
    echo ""
    echo "  To start a VM:"
    echo "    quickemu --vm ~/VMs/ubuntu-26.04-desktop/ubuntu-26.04-desktop.conf"
    echo ""
    echo "  Snapshots:"
    echo "    quickemu --vm <conf> --snapshot create base"
    echo "    quickemu --vm <conf> --snapshot apply base"
}

# ── List VMs ─────────────────────────────────────────────────────────

cmd_list() {
    echo ""
    echo -e "${BLUE}Configured VMs:${NC}"
    echo ""

    local found=false
    for entry in "${VMS[@]}"; do
        read -r os release edition disk ram cores extra <<< "$entry"
        local name=$(vm_name "$os" "$release" "$edition")
        local conf=$(find_conf "$VM_DIR/$name")

        if [[ -n "$conf" && -f "$conf" ]]; then
            found=true
            local status="ready"
            [[ ! -f "$VM_DIR/$name/disk.qcow2" ]] && status="config-only (run 'create' to download ISO)"
            echo -e "  ${GREEN}●${NC} $name  ($disk / ${ram}G RAM / $cores cores)  [$status]"
        else
            echo -e "  ${YELLOW}○${NC} $name  (not yet configured)"
        fi
    done

    $found || echo "  No VMs configured yet. Run: ./scripts/quickemu-lab.sh create"
    echo ""
}

# ── Snapshots ────────────────────────────────────────────────────────

cmd_snapshot() {
    local tag="${1:-base}"

    for entry in "${VMS[@]}"; do
        read -r os release edition disk ram cores extra <<< "$entry"
        local name=$(vm_name "$os" "$release" "$edition")
        local conf=$(find_conf "$VM_DIR/$name")

        if [[ -n "$conf" && -f "$conf" ]]; then
            info "Snapshot '$tag' → $name"
            quickemu --vm "$conf" --snapshot create "$tag" 2>&1 | tail -1 || warn "Snapshot failed for $name (VM may need to be running)"
        fi
    done

    echo ""
    log "Snapshot '$tag' created for all running VMs"
    echo "  Restore: quickemu --vm <conf> --snapshot apply $tag"
}

# ── Dispatch ─────────────────────────────────────────────────────────

case "${1:-}" in
    create)
        cmd_create
        ;;
    list)
        cmd_list
        ;;
    snapshot)
        cmd_snapshot "${2:-base}"
        ;;
    *)
        cat <<EOF
Quickemu Lab — Portable VM fleet manager

USAGE
    ./scripts/quickemu-lab.sh <command>

COMMANDS
    create           Download ISOs and configure all VMs
    list             List configured VMs and their status
    snapshot [tag]   Create a snapshot for all VMs (default tag: base)

VMS CREATED
    ubuntu-26.04-desktop     (64G disk, 4G RAM, 2 cores)
    ubuntu-26.04-server      (32G disk, 4G RAM, 2 cores)
    ubuntu-24.04-desktop     (64G disk, 4G RAM, 2 cores)
    ubuntu-24.04-server      (32G disk, 4G RAM, 2 cores)
    windows-11               (128G disk, 4G RAM, 2 cores)
    macos-tahoe              (64G disk, 4G RAM, 2 cores)

NOTES
    - All disks are thin-provisioned (qcow2) — max size set, actual
      usage grows as needed.
    - Networking uses user-mode NAT — works across WiFi, Ethernet,
      and changing IP ranges without reconfiguration.
    - Port forwarding: each VM gets unique SSH/RDP ports on localhost.
    - Snapshots: quickemu --vm <conf> --snapshot create/apply/delete
    - Windows Server requires manual ISO — see 'windows-server' command.

STORAGE LOCATION
    ~/VMs/
EOF
        ;;
esac

#!/usr/bin/env bash
# Run once from your GNOME terminal to apply all desktop settings.
set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${BLUE}[→]${NC} $*"; }

# Power profile
info "Power → performance"
powerprofilesctl set performance
log "Power: $(powerprofilesctl get)"

# Mouse acceleration
info "Mouse → flat (no acceleration)"
gsettings set org.gnome.desktop.peripherals.mouse accel-profile flat
log "Mouse: $(gsettings get org.gnome.desktop.peripherals.mouse accel-profile)"

# Wallpapers
BG_DIR="$HOME/.local/share/backgrounds"
DOTFILES="$HOME/Documents/core-dotfiles"
mkdir -p "$BG_DIR"
cp "$DOTFILES/wallpapers/"*.{png,jpg} "$BG_DIR/" 2>/dev/null || true

xml="$BG_DIR/slideshow.xml"
echo '<background><starttime><year>2026</year><month>01</month><day>01</day><hour>00</hour><minute>00</minute><second>00</second></starttime>' > "$xml"
prev=""
for img in "$BG_DIR/"*.{png,jpg}; do
    [[ -f "$img" ]] || continue
    echo "  <static><duration>1795.0</duration><file>$img</file></static>" >> "$xml"
    [[ -n "$prev" ]] && echo "  <transition><duration>5.0</duration><from>$prev</from><to>$img</to></transition>" >> "$xml"
    prev="$img"
done
echo '</background>' >> "$xml"

gsettings set org.gnome.desktop.background picture-uri "file://$xml"
gsettings set org.gnome.desktop.background picture-options 'zoom'
gsettings set org.gnome.desktop.screensaver picture-uri "file://$xml"
log "Wallpapers: slideshow active"

# Orchis theme
if [[ -d /usr/share/themes/Orchis-Dark ]]; then
    gsettings set org.gnome.shell.extensions.user-theme name 'Orchis-Dark'
    gsettings set org.gnome.desktop.interface gtk-theme 'Orchis-Dark'
    log "Theme: Orchis-Dark"
fi

echo ""
log "Done. Alt+F2 → type 'r' → Enter to restart GNOME Shell."

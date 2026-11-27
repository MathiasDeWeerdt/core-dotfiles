#!/usr/bin/env bash
# Run once from your GNOME terminal to apply all desktop settings.
set -euo pipefail

GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${BLUE}[→]${NC} $*"; }

# Power profile — pick best available
info "Setting power profile..."
if powerprofilesctl list 2>/dev/null | grep -q 'performance'; then
    powerprofilesctl set performance
elif powerprofilesctl list 2>/dev/null | grep -q 'balanced'; then
    powerprofilesctl set balanced
fi
log "Power: $(powerprofilesctl get 2>/dev/null || echo 'unavailable')"

# Mouse acceleration
info "Mouse → flat (no acceleration)"
gsettings set org.gnome.desktop.peripherals.mouse accel-profile flat
log "Mouse: $(gsettings get org.gnome.desktop.peripherals.mouse accel-profile)"

# Alt+Tab → switch windows (no app grouping)
info "Alt+Tab → individual windows"
gsettings set org.gnome.desktop.wm.keybindings switch-applications "['<Super>Tab']"
gsettings set org.gnome.desktop.wm.keybindings switch-applications-backward "['<Shift><Super>Tab']"
gsettings set org.gnome.desktop.wm.keybindings switch-windows "['<Alt>Tab']"
gsettings set org.gnome.desktop.wm.keybindings switch-windows-backward "['<Shift><Alt>Tab']"
log "Alt+Tab: individual windows, Super+Tab: app grouping"

# Add our shortcuts once while preserving every unrelated custom shortcut.
shortcut() {
    local slug=$1 name=$2 binding=$3 command=$4 current updated
    local key_path="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/core-dotfiles-$slug/"
    local schema="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$key_path"
    gsettings set "$schema" name "$name"
    gsettings set "$schema" binding "$binding"
    gsettings set "$schema" command "$command"
    current=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
    updated=$(python3 - "$current" "$key_path" <<'PY'
import ast, sys
paths = ast.literal_eval(sys.argv[1].removeprefix('@as '))
if sys.argv[2] not in paths:
    paths.append(sys.argv[2])
print(repr(paths))
PY
    )
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$updated"
}
shortcut terminal 'Terminal' '<Control><Alt>t' 'foot -m'
shortcut screenshot 'Screenshot' '<Control><Shift>a' "$HOME/.local/bin/flameshot-gui"

# Default terminal → foot (Nautilus "Open in Console")
info "Terminal → foot"
gsettings set org.gnome.desktop.default-applications.terminal exec foot
gsettings set org.gnome.desktop.default-applications.terminal exec-arg ''
# nautilus-open-any-terminal extension: set foot as the context-menu terminal
if command -v nautilus &>/dev/null; then
    gsettings set com.github.stunkymonkey.nautilus-open-any-terminal terminal foot 2>/dev/null || true
    gsettings set com.github.stunkymonkey.nautilus-open-any-terminal use-generic-terminal-name true 2>/dev/null || true
    # Hide built-in "Open in Console" (GNOME Console) — foot is the only terminal now
    mkdir -p ~/.local/share/applications
    cat > ~/.local/share/applications/org.gnome.Console.desktop <<'NAUT_DESKTOP'
[Desktop Entry]
NoDisplay=true
NAUT_DESKTOP
    # Leave running Nautilus windows intact on reruns.
fi
log "Terminal: foot"

# Wallpapers
BG_DIR="$HOME/.local/share/backgrounds"
DOTFILES=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$BG_DIR"
for wallpaper in "$DOTFILES/wallpapers/"*.{png,jpg}; do
    [[ ! -f "$wallpaper" ]] || install -C -m 644 "$wallpaper" "$BG_DIR/"
done

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
gsettings set org.gnome.desktop.background picture-uri-dark "file://$xml"
gsettings set org.gnome.desktop.background picture-options 'zoom'
gsettings set org.gnome.desktop.screensaver picture-uri "file://$xml" 2>/dev/null || true
gsettings set org.gnome.desktop.screensaver picture-uri-dark "file://$xml" 2>/dev/null || true
gsettings set org.gnome.desktop.lock-screen picture-uri "file://$xml" 2>/dev/null || true
gsettings set org.gnome.desktop.lock-screen picture-uri-dark "file://$xml" 2>/dev/null || true
log "Wallpapers: desktop + lockscreen set"

# GDM login screen: use gdm-settings GUI (installed via AUR)
# Run: gtk-launch gdm-settings

# Orchis theme
if [[ -d /usr/share/themes/Orchis-Dark ]]; then
    gsettings set org.gnome.shell.extensions.user-theme name 'Orchis-Dark'
    gsettings set org.gnome.desktop.interface gtk-theme 'Orchis-Dark'
    log "Theme: Orchis-Dark"
fi

echo ""
log "Done. Log out and back in if desktop extensions need to reload."

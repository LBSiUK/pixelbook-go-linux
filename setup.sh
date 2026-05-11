#!/bin/bash
# Pixelbook Go (Atlas) Linux Setup
# Fixes keyboard hotkeys and internal audio on Ubuntu 24.04 / Zorin OS 18.x
# Tested with kernel 6.17 and the Intel AVS audio driver.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERRORS=0

# ── Helpers ────────────────────────────────────────────────────────────────────

info()    { echo "  [INFO]  $*"; }
ok()      { echo "  [ OK ]  $*"; }
warn()    { echo "  [WARN]  $*"; }
fail()    { echo "  [FAIL]  $*"; ERRORS=$((ERRORS + 1)); }

require_sudo() {
    if ! sudo -n true 2>/dev/null; then
        echo "This script needs sudo. You may be prompted for your password."
        sudo -v
    fi
}

# ── Hardware check ─────────────────────────────────────────────────────────────

echo
echo "╔══════════════════════════════════════════════╗"
echo "║   Pixelbook Go Linux Setup                  ║"
echo "╚══════════════════════════════════════════════╝"
echo

PRODUCT=$(sudo dmidecode -s system-product-name 2>/dev/null || true)
if echo "$PRODUCT" | grep -qi "atlas"; then
    ok "Detected Pixelbook Go (Atlas)"
else
    warn "Could not confirm Pixelbook Go hardware (got: '${PRODUCT:-unknown}')"
    read -rp "  Continue anyway? [y/N] " response
    [[ "$response" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

require_sudo

# ── 1. Keyboard hotkeys ────────────────────────────────────────────────────────

echo
echo "── Keyboard hotkeys ──────────────────────────────────────────────────────"

HWDB_SRC="$SCRIPT_DIR/udev/61-pixelbook-go-keyboard.hwdb"
HWDB_DEST="/etc/udev/hwdb.d/61-pixelbook-go-keyboard.hwdb"

if sudo cp "$HWDB_SRC" "$HWDB_DEST"; then
    ok "Installed hwdb rules → $HWDB_DEST"
else
    fail "Failed to install hwdb rules"
fi

if sudo systemd-hwdb update && sudo udevadm trigger --subsystem-match=input; then
    ok "Keyboard remapping applied (takes effect immediately)"
else
    fail "hwdb update failed"
fi

# ── 2. Audio: AVS DSP driver ───────────────────────────────────────────────────

echo
echo "── Audio: modprobe config ────────────────────────────────────────────────"

if sudo cp "$SCRIPT_DIR/modprobe/snd-avs.conf" /etc/modprobe.d/snd-avs.conf; then
    ok "Installed /etc/modprobe.d/snd-avs.conf (forces Intel AVS DSP driver)"
else
    fail "Failed to install modprobe config"
fi

# ── 3. Audio: firmware topology files ─────────────────────────────────────────

echo
echo "── Audio: firmware ───────────────────────────────────────────────────────"

FIRMWARE_DIR="/lib/firmware/intel/avs"
sudo mkdir -p "$FIRMWARE_DIR"

for f in max98373-tplg.bin da7219-tplg.bin dmic-tplg.bin hda-8086280b-tplg.bin; do
    src="$SCRIPT_DIR/firmware/$f"
    dest="$FIRMWARE_DIR/$f"
    if [[ ! -f "$src" ]]; then
        fail "Missing firmware file: $src"
        continue
    fi
    if sudo cp "$src" "$dest"; then
        ok "Installed $f"
    else
        fail "Failed to install $f"
    fi
done

# ── 4. Audio: UCM configs ──────────────────────────────────────────────────────

echo
echo "── Audio: UCM configs ────────────────────────────────────────────────────"

UCM_BASE="/usr/share/alsa/ucm2/conf.d"

for card in avs_max98373 avs_da7219; do
    dest_dir="$UCM_BASE/$card"
    sudo mkdir -p "$dest_dir"
    for f in "$SCRIPT_DIR/ucm/$card/"*; do
        fname="$(basename "$f")"
        if sudo cp "$f" "$dest_dir/$fname"; then
            ok "Installed UCM: $card/$fname"
        else
            fail "Failed to install UCM: $card/$fname"
        fi
    done
done

# ── 5. Audio: WirePlumber rules ────────────────────────────────────────────────

echo
echo "── Audio: WirePlumber ────────────────────────────────────────────────────"

WP_DEST="/etc/wireplumber/main.lua.d"
sudo mkdir -p "$WP_DEST"

if sudo cp "$SCRIPT_DIR/wireplumber/51-pixelbook-go-audio.lua" "$WP_DEST/"; then
    ok "Installed WirePlumber rules"
else
    fail "Failed to install WirePlumber rules"
fi

# Restart WirePlumber if running in a GNOME session
if systemctl --user is-active --quiet wireplumber 2>/dev/null; then
    info "Restarting WirePlumber..."
    systemctl --user restart wireplumber
    sleep 4
    ok "WirePlumber restarted"

    # Set ALSA mixer state for the speaker amp
    info "Configuring speaker amp (MAX98373)..."
    amixer -c MAX98373 cset name='DSP Volume' 536870912      >/dev/null 2>&1 && ok "DSP Volume set"          || warn "DSP Volume: card not ready (will be set by UCM on next boot)"
    amixer -c MAX98373 cset name='Left DAI Sel Mux' Left     >/dev/null 2>&1 || true
    amixer -c MAX98373 cset name='Right DAI Sel Mux' Right   >/dev/null 2>&1 || true
    amixer -c MAX98373 sset 'Left Digital' 127               >/dev/null 2>&1 || true
    amixer -c MAX98373 sset 'Right Digital' 127              >/dev/null 2>&1 || true
    sudo alsactl store                                        >/dev/null 2>&1 && ok "ALSA state saved" || true

    # Set Built-in Speakers as the default sink
    sleep 1
    SPEAKER_ID=$(wpctl status 2>/dev/null | awk '/Built-in Speakers/ { print $2+0; exit }')
    if [[ -n "$SPEAKER_ID" && "$SPEAKER_ID" -gt 0 ]]; then
        wpctl set-default "$SPEAKER_ID" && ok "Built-in Speakers set as default output"
    else
        warn "Could not auto-select Built-in Speakers — set it manually in Sound Settings after reboot"
    fi
else
    warn "WirePlumber not running in this session — audio changes will take effect after reboot"
fi

# ── 6. GNOME keyboard backlight shortcuts ──────────────────────────────────────

echo
echo "── Keyboard backlight shortcuts (GNOME) ──────────────────────────────────"

if command -v gsettings &>/dev/null; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys keyboard-brightness-up   "['<Alt>XF86MonBrightnessUp']"
    gsettings set org.gnome.settings-daemon.plugins.media-keys keyboard-brightness-down "['<Alt>XF86MonBrightnessDown']"
    ok "Alt + Brightness Up/Down → keyboard backlight (with OSD)"
else
    warn "gsettings not found — skipping GNOME keyboard backlight shortcuts"
fi

# ── Summary ────────────────────────────────────────────────────────────────────

echo
echo "══════════════════════════════════════════════════════════════════════════"
if [[ $ERRORS -eq 0 ]]; then
    echo "  Setup complete with no errors."
else
    echo "  Setup finished with $ERRORS error(s) — review the [FAIL] lines above."
fi
echo
echo "  *** Please reboot for audio driver and firmware changes to take effect ***"
echo "══════════════════════════════════════════════════════════════════════════"
echo

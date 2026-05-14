# Pixelbook Go (Atlas) Linux Setup

Fixes keyboard hotkeys and gets internal audio working for the **Google Pixelbook Go** running Ubuntu 24.04 or Zorin OS 18.x with kernel 6.17+. Also includes **Pixelbook Go Tools** — a GTK4 app for speaker EQ and automatic updates in case I add to this.

## What it fixes

### Keyboard
The Pixelbook Go's top-row ChromeOS function keys send plain F1–F10 by default. This remaps them to their labelled functions at the kernel level (works on both Wayland and X11):

| Key | Mapped to |
|-----|-----------|
| Back (←) | `XF86Back` |
| Refresh (↺) | `XF86Refresh` |
| Fullscreen | `F11` |
| View Windows | `XF86LaunchA` (GNOME Overview) |
| Brightness Down | `XF86MonBrightnessDown` |
| Brightness Up | `XF86MonBrightnessUp` |
| Play/Pause | `XF86AudioPlay` |
| Mute | `XF86AudioMute` |
| Volume Down | `XF86AudioLowerVolume` |
| Volume Up | `XF86AudioRaiseVolume` |

**Keyboard backlight:** `Alt + Brightness Down/Up` adjusts keyboard backlight with the GNOME OSD.

### Audio
The Pixelbook Go uses the Intel AVS (Audio/Voice/Speech) driver with:
- **MAX98373** × 2 — internal speakers (Class D amp over I2S/SSP0)
- **DA7219** — headphone jack output + headset microphone
- **DMIC** — internal microphone array

The stock `linux-firmware` package (as of early 2024) is missing the KBL AVS topology files. This installs known-working July 2024 topology files and configures the full audio stack:

| Component | What it does |
|-----------|-------------|
| `modprobe/snd-avs.conf` | Forces Intel AVS DSP driver; disables firmware version checks |
| `firmware/*.bin` | AVS topology files for MAX98373, DA7219, DMIC, and HDMI audio |
| `ucm/avs_max98373/` | UCM profile: sets DSP volume, stereo channel routing, balances both speaker amps |
| `ucm/avs_da7219/` | UCM profile: enables headphone DAC path and headset mic on jack detection |
| `wireplumber/` | Prioritises built-in speakers over HDMI; labels devices correctly |
| `pipewire/99-speaker-eq.conf` | 8-band PipeWire filter-chain EQ routed to speakers only |

### Speaker EQ
A PipeWire filter-chain applies an 8-band graphic EQ to the built-in speakers. HDMI audio and headphones are unaffected. The default curve is meant to make the Pixelbook's speakers sound closer to how they did under ChromeOS (I believe Google uses a software EQ), however you'll probably want to adjust it which you can do with the **Pixelbook Go Tools** app. You can disable the EQ by selecting the non-EQ'd output device in GNOME.

## Pixelbook Go Tools

A GTK4 desktop app installed to your applications menu.

**Equaliser tab** — adjust the speaker EQ without touching any config files:
- 8 bands: 125 Hz, 250 Hz, 500 Hz, 1 kHz, 2 kHz, 4 kHz, 8 kHz, 16 kHz (±9 dB each)
- **Bandwidth** slider — controls how wide or narrow each band's effect is (Q 0.3–4.0)
- Live frequency-response curve
- Apply / Reset / Flat buttons

**Updates tab** — manage updates:
- Shows current version, latest release, and last-checked timestamp
- Toggle for automatic daily update checks (also runs 5 minutes after login)
- **Check Now** for on-demand checks
- **Download & Install** — downloads the release zip and runs `setup.sh` in a terminal
- **Skip This Version** to suppress a specific release

You can also run the app directly:
```bash
python3 pixelbook-tools.py
```

## Requirements

- Google Pixelbook Go (board codename **Atlas**)
- Ubuntu 24.04 / Zorin OS 18.x (or any Ubuntu 24.04-based distro)
- Kernel **6.17** (the AVS topology files in `firmware/` are tested against this kernel, others may work but they're unsupported)
- MrChromebox coreboot firmware (standard UEFI boot)
- GNOME desktop (for keyboard backlight shortcut and app)
- `python3-gi` with GTK4 bindings (pre-installed on Ubuntu/Zorin)

> **Kernel note:** The included topology `.bin` files are from linux-firmware commit `65d14b1` (July 2024). Newer kernel versions may include updated topology files in the `linux-firmware` package that work out of the box — if audio stops working after a kernel upgrade, try re-running this script.

## Usage

```bash
git clone https://github.com/LBSiUK/pixelbook-go-linux
cd pixelbook-go-linux
chmod +x setup.sh
./setup.sh
# Reboot when prompted
```

The script is safe to re-run after reinstalls or kernel upgrades.

## What the script does

1. Asks whether to enable automatic update checks
2. Installs `/etc/udev/hwdb.d/61-pixelbook-go-keyboard.hwdb` and reloads the hwdb — keyboard remapping takes effect immediately
3. Installs `/etc/modprobe.d/snd-avs.conf` — takes effect after reboot
4. Copies topology `.bin` files to `/lib/firmware/intel/avs/`
5. Installs UCM configs to `/usr/share/alsa/ucm2/conf.d/avs_max98373/` and `.../avs_da7219/`
6. Installs WirePlumber rules to `/etc/wireplumber/main.lua.d/`; if WirePlumber is running, restarts it and sets the ALSA mixer state
7. Installs the PipeWire EQ config to `~/.config/pipewire/pipewire.conf.d/`; if PipeWire is running, reloads it and sets the Speaker EQ virtual sink as the default output
8. Sets GNOME keyboard shortcuts for keyboard backlight (`Alt + Brightness`)
9. Installs the update-checker systemd service and timer to `~/.config/systemd/user/`; enables the timer if auto-updates were chosen
10. Installs a desktop entry for **Pixelbook Go Tools** to `~/.local/share/applications/`

## After rebooting

- **Speakers** work automatically as the default output (routed through the EQ)
- **Headphones** appear as an output device when plugged in (no EQ applied)
- **Headset mic** appears as an input when a headset is plugged in
- **Internal mic** (DMIC) is always available as an input
- **HDMI audio** works when an external display is connected (lower priority than speakers)
- **Pixelbook Go Tools** appears in your applications menu

## File structure

```
pixelbook-go-linux/
├── setup.sh                          — main setup script
├── README.md                         — this file
├── version.txt                       — current version number
├── pixelbook-tools.py                — GTK4 EQ + update manager app
├── updater.py                        — GitHub Releases update checker (used by app and systemd)
├── firmware/
│   ├── max98373-tplg.bin             — speaker amp AVS topology
│   ├── da7219-tplg.bin               — headphone codec AVS topology
│   ├── dmic-tplg.bin                 — internal microphone AVS topology
│   └── hda-8086280b-tplg.bin         — HDMI audio AVS topology
├── modprobe/
│   └── snd-avs.conf                  — DSP driver selection
├── pipewire/
│   └── 99-speaker-eq.conf            — 8-band PipeWire filter-chain EQ
├── systemd/
│   ├── pixelbook-go-tools-update.service — update checker service (one-shot)
│   └── pixelbook-go-tools-update.timer   — daily trigger (5 min after boot, then 24 h)
├── udev/
│   └── 61-pixelbook-go-keyboard.hwdb — top-row key remapping
├── ucm/
│   ├── avs_max98373/                 — speaker amp UCM profile
│   │   ├── AVS I2S MAX98373.conf
│   │   └── HiFi.conf
│   └── avs_da7219/                   — headphone codec UCM profile
│       ├── AVS I2S DA7219.conf
│       └── HiFi.conf
└── wireplumber/
    └── 51-pixelbook-go-audio.lua     — WirePlumber device priority rules
```

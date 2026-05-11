# Pixelbook Go (Atlas) Linux Setup

Fixes keyboard hotkeys and internal audio for the **Google Pixelbook Go** running Ubuntu 24.04 or Zorin OS 18.x with kernel 6.17+.

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

## Requirements

- Google Pixelbook Go (board codename **Atlas**)
- Ubuntu 24.04 / Zorin OS 18.x (or any Ubuntu 24.04-based distro)
- Kernel **6.17** (the AVS topology files in `firmware/` are tested against this kernel)
- MrChromebox coreboot firmware (standard UEFI boot)
- GNOME desktop (for keyboard backlight shortcut)

> **Kernel note:** The included topology `.bin` files are from linux-firmware commit `65d14b1` (July 2024). Newer kernel versions may include updated topology files in the `linux-firmware` package that work out of the box — if audio stops working after a kernel upgrade, try re-running this script.

## Usage

```bash
git clone https://github.com/YOUR_USERNAME/pixelbook-go-linux
cd pixelbook-go-linux
chmod +x setup.sh
./setup.sh
# Reboot when prompted
```

The script is safe to re-run after reinstalls or kernel upgrades.

## What the script does

1. Installs `/etc/udev/hwdb.d/61-pixelbook-go-keyboard.hwdb` and reloads the hwdb — keyboard remapping takes effect immediately
2. Installs `/etc/modprobe.d/snd-avs.conf` — takes effect after reboot
3. Copies topology `.bin` files to `/lib/firmware/intel/avs/`
4. Installs UCM configs to `/usr/share/alsa/ucm2/conf.d/avs_max98373/` and `.../avs_da7219/`
5. Installs WirePlumber rules to `/etc/wireplumber/main.lua.d/`
6. If WirePlumber is running: restarts it, sets the ALSA mixer state (DSP volume, stereo routing, channel balance), saves ALSA state
7. Sets GNOME keyboard shortcuts for keyboard backlight (`Alt + Brightness`)

## After rebooting

- **Speakers** should work automatically as the default output
- **Headphones** appear as an output device when plugged in
- **Headset mic** appears as an input when a headset is plugged in
- **Internal mic** (DMIC) is always available as an input
- **HDMI audio** works when an external display is connected (lower priority than speakers)

## File structure

```
pixelbook-go-linux/
├── setup.sh                          — main setup script
├── README.md                         — this file
├── firmware/
│   ├── max98373-tplg.bin             — speaker amp AVS topology
│   ├── da7219-tplg.bin               — headphone codec AVS topology
│   ├── dmic-tplg.bin                 — internal microphone AVS topology
│   └── hda-8086280b-tplg.bin         — HDMI audio AVS topology
├── modprobe/
│   └── snd-avs.conf                  — DSP driver selection
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

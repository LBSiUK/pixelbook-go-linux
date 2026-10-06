#!/usr/bin/env python3
"""
Pixelbook Go Tools — speaker EQ and update manager.
"""

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango, Gio
import math, cmath, subprocess, os, re, sys, threading, urllib.request, zipfile, tempfile, shutil

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
import updater

CONFIG = os.path.expanduser(
    "~/.config/pipewire/pipewire.conf.d/99-speaker-eq.conf"
)
# Where "Download & Install" unpacks new releases before running setup.sh
RELEASES_DIR = os.path.expanduser("~/.local/share/pixelbook-go-tools/releases")
Fs = 48000

BANDS = [
    ("125",    125.0),
    ("250",    250.0),
    ("500",    500.0),
    ("1k",    1000.0),
    ("2k",    2000.0),
    ("4k",    4000.0),
    ("8k",    8000.0),
    ("16k",  16000.0),
]
GAIN_MIN, GAIN_MAX = -9.0, 9.0
Q_MIN, Q_MAX, Q_DEFAULT = 0.3, 4.0, 1.41

def _q_label(q):
    if q < 0.55: return "Very Wide"
    if q < 0.95: return "Wide"
    if q < 1.75: return "Normal"
    if q < 2.60: return "Narrow"
    return "Tight"

# ── Biquad maths ───────────────────────────────────────────────────────────────

def _hp_coeff(f0, Q):
    w = 2*math.pi*f0/Fs; al = math.sin(w)/(2*Q)
    return [(1+math.cos(w))/2, -(1+math.cos(w)), (1+math.cos(w))/2], \
           [1+al, -2*math.cos(w), 1-al]

def _pk_coeff(f0, Q, dB):
    A = 10**(dB/40); w = 2*math.pi*f0/Fs; al = math.sin(w)/(2*Q)
    return [1+al*A, -2*math.cos(w), 1-al*A], \
           [1+al/A, -2*math.cos(w), 1-al/A]

def _mag_db(freqs, b, a):
    out = []
    for f in freqs:
        w = 2*math.pi*f/Fs; z = cmath.exp(1j*w)
        H = (b[0]+b[1]*z**-1+b[2]*z**-2)/(a[0]+a[1]*z**-1+a[2]*z**-2)
        out.append(20*math.log10(max(abs(H), 1e-9)))
    return out

# ── Config I/O ─────────────────────────────────────────────────────────────────

def _gen_config(gains, q):
    nb = len(BANDS)
    lines = ["# Speaker EQ for Pixelbook Go (Atlas) — 8-band graphic EQ",
             "#   80 Hz high-pass (fixed, speaker protection)",
             f"#   Bandwidth Q={q:.2f} ({_q_label(q)})",
             "#   Bands: " + "  ".join(
                 f"{BANDS[i][0]}={gains[i]:+.2f}dB" for i in range(nb)),
             "#",
             "# Routes to built-in speakers only; HDMI and headphones unaffected.",
             "",
             "context.modules = [",
             "{   name = libpipewire-module-filter-chain",
             "    args = {",
             '        node.description = "Speaker EQ"',
             '        media.name       = "Speaker EQ"',
             "        filter.graph = {",
             "            nodes = ["]

    for ch in ("l", "r"):
        lines.append(f"                # {'Left' if ch=='l' else 'Right'} channel")
        lines.append(f'                {{ type = builtin  name = hp_{ch}    label = bq_highpass  '
                     f' control = {{ "Freq" = 80.0  "Q" = 0.707  "Gain" = 0.0 }} }}')
        for i, (lbl, f0) in enumerate(BANDS):
            lines.append(
                f'                {{ type = builtin  name = b{i+1}_{ch}  label = bq_peaking  '
                f' control = {{ "Freq" = {f0:.1f}  "Q" = {q:.3f}  "Gain" = {gains[i]:.2f} }} }}'
            )

    lines.append("            ]")
    lines.append("            links = [")
    for ch in ("l", "r"):
        lines.append(f'                {{ output = "hp_{ch}:Out"  input = "b1_{ch}:In" }}')
        for i in range(1, len(BANDS)):
            lines.append(
                f'                {{ output = "b{i}_{ch}:Out"  input = "b{i+1}_{ch}:In" }}'
            )
    lines.append("            ]")
    lines.append('            inputs  = [ "hp_l:In"  "hp_r:In" ]')
    lines.append(f'            outputs = [ "b{len(BANDS)}_l:Out"  "b{len(BANDS)}_r:Out" ]')
    lines.append("        }")

    lines += [
        "        capture.props = {",
        '            node.name        = "effect_input.speaker_eq"',
        "            media.class      = Audio/Sink",
        "            audio.channels   = 2",
        "            audio.position   = [ FL FR ]",
        "            priority.session = 2500",
        "        }",
        "        playback.props = {",
        '            node.name      = "effect_output.speaker_eq"',
        "            node.passive   = true",
        '            target.object  = "alsa_output.platform-avs_max98373.65536.HiFi__hw_MAX98373__sink"',
        "            audio.channels = 2",
        "            audio.position = [ FL FR ]",
        "        }",
        "    }",
        "}",
        "]",
        "",
    ]
    return "\n".join(lines)

def write_and_apply(gains, q):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        f.write(_gen_config(gains, q))
    subprocess.run(
        ["systemctl", "--user", "restart", "pipewire", "pipewire-pulse"],
        check=False
    )

def read_state():
    gains = [0.0] * len(BANDS)
    q = Q_DEFAULT
    try:
        text = open(CONFIG).read()
        found = re.findall(r'name = b(\d+)_l.*?"Gain"\s*=\s*([-\d.]+)', text)
        if found:
            for idx_s, val_s in found:
                i = int(idx_s) - 1
                if 0 <= i < len(BANDS):
                    gains[i] = float(val_s)
            m = re.search(r'name = b1_l.*?"Q"\s*=\s*([\d.]+)', text)
            if m:
                q = float(m.group(1))
    except Exception:
        pass
    return gains, q

# ── Curve canvas ───────────────────────────────────────────────────────────────

_N = 500
_FREQS = [20 * (20000/20)**(i/(_N-1)) for i in range(_N)]

class CurveArea(Gtk.DrawingArea):
    DB_MIN, DB_MAX = -12.0, 12.0

    def __init__(self):
        super().__init__()
        self.gains = [0.0] * len(BANDS)
        self.q = Q_DEFAULT
        self.set_draw_func(self._draw)
        self.set_content_width(640)
        self.set_content_height(150)

    def update(self, gains, q):
        self.gains = list(gains)
        self.q = q
        self.queue_draw()

    def _response(self):
        hp_b, hp_a = _hp_coeff(80, 0.707)
        total = _mag_db(_FREQS, hp_b, hp_a)
        for i, (_, f0) in enumerate(BANDS):
            r = _mag_db(_FREQS, *_pk_coeff(f0, self.q, self.gains[i]))
            for j in range(_N):
                total[j] += r[j]
        return total

    def _draw(self, _area, cr, w, h):
        pad_l, pad_r, pad_t, pad_b = 36, 8, 8, 20

        def fx(f):
            return pad_l + (w-pad_l-pad_r) * math.log10(f/20) / math.log10(20000/20)
        def fy(db):
            db = max(self.DB_MIN, min(self.DB_MAX, db))
            return pad_t + (h-pad_t-pad_b) * (1-(db-self.DB_MIN)/(self.DB_MAX-self.DB_MIN))

        cr.set_source_rgb(0.04, 0.04, 0.10)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        for db in range(int(self.DB_MIN), int(self.DB_MAX)+1, 3):
            y = fy(db)
            if db == 0:
                cr.set_source_rgba(0.0, 0.85, 1.0, 0.35)
                cr.set_line_width(0.9)
            else:
                cr.set_source_rgba(1, 1, 1, 0.07)
                cr.set_line_width(0.5)
            cr.move_to(pad_l, y); cr.line_to(w-pad_r, y); cr.stroke()
            if db != 0 and db % 6 == 0:
                cr.set_source_rgba(0.45, 0.45, 0.55, 1)
                cr.set_font_size(8)
                cr.move_to(2, y+3)
                cr.show_text(f"{db:+d}")

        for f, lbl in [(100,"100"),(200,"200"),(500,"500"),
                       (1000,"1k"),(2000,"2k"),(5000,"5k"),(10000,"10k"),(20000,"20k")]:
            x = fx(f)
            cr.set_source_rgba(1, 1, 1, 0.07)
            cr.set_line_width(0.5)
            cr.move_to(x, pad_t); cr.line_to(x, h-pad_b); cr.stroke()
            cr.set_source_rgba(0.45, 0.45, 0.55, 1)
            cr.set_font_size(8)
            cr.move_to(x-7, h-5)
            cr.show_text(lbl)

        curve = self._response()
        pts = [(fx(_FREQS[i]), fy(curve[i])) for i in range(_N)]

        cr.move_to(pts[0][0], fy(0))
        for x, y in pts: cr.line_to(x, y)
        cr.line_to(pts[-1][0], fy(0))
        cr.close_path()
        cr.set_source_rgba(0.0, 0.85, 1.0, 0.12)
        cr.fill()

        cr.move_to(*pts[0])
        for x, y in pts[1:]: cr.line_to(x, y)
        cr.set_source_rgb(0.0, 0.85, 1.0)
        cr.set_line_width(2.0)
        cr.set_line_join(0)
        cr.stroke()


# ── EQ page ────────────────────────────────────────────────────────────────────

class EQPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_margin_top(12); self.set_margin_bottom(12)
        self.set_margin_start(12); self.set_margin_end(12)

        self.gains, self.q = read_state()

        self.curve = CurveArea()
        self.curve.update(self.gains, self.q)
        self.append(self.curve)

        slider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        slider_box.set_halign(Gtk.Align.CENTER)
        self.append(slider_box)

        self.sliders = []
        self.val_labels = []

        for i, (lbl, _f0) in enumerate(BANDS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.set_size_request(72, -1)
            col.set_halign(Gtk.Align.CENTER)
            slider_box.append(col)

            freq_lbl = Gtk.Label(label=lbl)
            freq_lbl.set_halign(Gtk.Align.CENTER)
            attr = Pango.AttrList()
            attr.insert(Pango.attr_size_new(8 * Pango.SCALE))
            freq_lbl.set_attributes(attr)
            col.append(freq_lbl)

            adj = Gtk.Adjustment(value=self.gains[i], lower=GAIN_MIN, upper=GAIN_MAX,
                                 step_increment=0.1, page_increment=1.0)
            scale = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adj)
            scale.set_inverted(True)
            scale.set_draw_value(False)
            scale.set_size_request(-1, 180)
            scale.set_hexpand(False)
            for mark in (-6, -3, 0, 3, 6):
                scale.add_mark(mark, Gtk.PositionType.LEFT,
                               "0" if mark == 0 else None)
            adj.connect("value-changed", self._on_slider, i)
            col.append(scale)
            self.sliders.append(scale)

            val_lbl = Gtk.Label(label=f"{self.gains[i]:+.1f}")
            val_lbl.set_halign(Gtk.Align.CENTER)
            attr2 = Pango.AttrList()
            attr2.insert(Pango.attr_size_new(8 * Pango.SCALE))
            val_lbl.set_attributes(attr2)
            col.append(val_lbl)
            self.val_labels.append(val_lbl)

        bw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bw_row.set_margin_top(2)
        self.append(bw_row)

        bw_lbl = Gtk.Label(label="Bandwidth")
        attr3 = Pango.AttrList()
        attr3.insert(Pango.attr_size_new(9 * Pango.SCALE))
        bw_lbl.set_attributes(attr3)
        bw_row.append(bw_lbl)

        wide_lbl = Gtk.Label(label="Wide")
        wide_lbl.add_css_class("dim-label")
        bw_row.append(wide_lbl)

        bw_adj = Gtk.Adjustment(value=self.q, lower=Q_MIN, upper=Q_MAX,
                                step_increment=0.05, page_increment=0.2)
        self.bw_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                  adjustment=bw_adj)
        self.bw_scale.set_draw_value(False)
        self.bw_scale.set_hexpand(True)
        self.bw_scale.add_mark(Q_DEFAULT, Gtk.PositionType.BOTTOM, None)
        bw_adj.connect("value-changed", self._on_bw_slider)
        bw_row.append(self.bw_scale)

        narrow_lbl = Gtk.Label(label="Narrow")
        narrow_lbl.add_css_class("dim-label")
        bw_row.append(narrow_lbl)

        self.bw_val_lbl = Gtk.Label(label=f"Q {self.q:.2f} · {_q_label(self.q)}")
        attr4 = Pango.AttrList()
        attr4.insert(Pango.attr_size_new(9 * Pango.SCALE))
        self.bw_val_lbl.set_attributes(attr4)
        self.bw_val_lbl.set_width_chars(18)
        self.bw_val_lbl.set_xalign(0)
        bw_row.append(self.bw_val_lbl)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_margin_top(4)
        self.append(btn_row)

        self.status = Gtk.Label(label="")
        self.status.set_hexpand(True)
        self.status.set_halign(Gtk.Align.START)
        btn_row.append(self.status)

        flat_btn = Gtk.Button(label="Flat")
        flat_btn.connect("clicked", self._on_flat)
        btn_row.append(flat_btn)

        reset_btn = Gtk.Button(label="Reset")
        reset_btn.connect("clicked", self._on_reset)
        btn_row.append(reset_btn)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", self._on_apply)
        btn_row.append(apply_btn)

        self._saved_gains = list(self.gains)
        self._saved_q = self.q

    def _on_slider(self, adj, idx):
        self.gains[idx] = adj.get_value()
        self.val_labels[idx].set_label(f"{self.gains[idx]:+.1f}")
        self.curve.update(self.gains, self.q)
        self.status.set_label("● Unapplied changes")

    def _on_bw_slider(self, adj):
        self.q = adj.get_value()
        self.bw_val_lbl.set_label(f"Q {self.q:.2f} · {_q_label(self.q)}")
        self.curve.update(self.gains, self.q)
        self.status.set_label("● Unapplied changes")

    def _set_all_sliders(self, values):
        for i, s in enumerate(self.sliders):
            s.get_adjustment().set_value(values[i])

    def _on_flat(self, _btn):
        self._set_all_sliders([0.0] * len(BANDS))

    def _on_reset(self, _btn):
        self._set_all_sliders(list(self._saved_gains))
        self.bw_scale.get_adjustment().set_value(self._saved_q)
        self.status.set_label("")

    def _on_apply(self, _btn):
        self.status.set_label("Applying…")
        GLib.idle_add(self._do_apply)

    def _do_apply(self):
        write_and_apply(self.gains, self.q)
        self._saved_gains = list(self.gains)
        self._saved_q = self.q
        self.status.set_label("✓ Applied")
        return False


# ── Updates page ───────────────────────────────────────────────────────────────

def _plain_notes(md):
    """GitHub release notes are Markdown; show them as readable plain text."""
    out = []
    for line in md.strip().splitlines():
        line = re.sub(r"^#+\s*", "", line)               # headings
        line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)    # bullet points
        out.append(line.replace("**", "").replace("`", ""))
    return "\n".join(out)

class UpdatesPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(16); self.set_margin_bottom(16)
        self.set_margin_start(16); self.set_margin_end(16)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.append(info_box)
        self._cur_lbl    = self._info_row(info_box, "Current version",
                                          f"v{updater.local_version()}")
        self._latest_lbl = self._info_row(info_box, "Latest version", "—")
        self._checked_lbl = self._info_row(info_box, "Last checked", "Never")

        sep1 = Gtk.Separator()
        sep1.set_margin_top(4); sep1.set_margin_bottom(4)
        self.append(sep1)

        auto_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.append(auto_row)
        auto_lbl = Gtk.Label(label="Check for updates automatically")
        auto_lbl.set_hexpand(True)
        auto_lbl.set_halign(Gtk.Align.START)
        auto_row.append(auto_lbl)
        self._auto_switch = Gtk.Switch()
        self._auto_switch.set_valign(Gtk.Align.CENTER)
        self._auto_switch.set_active(bool(updater.read_settings().get("auto_update")))
        self._auto_switch.connect("state-set", self._on_auto_toggle)
        auto_row.append(self._auto_switch)

        check_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        check_row.set_margin_top(4)
        self.append(check_row)
        self._check_btn = Gtk.Button(label="Check Now")
        self._check_btn.set_halign(Gtk.Align.START)
        self._check_btn.connect("clicked", self._on_check_now)
        check_row.append(self._check_btn)
        self._check_status = Gtk.Label(label="")
        self._check_status.set_halign(Gtk.Align.START)
        self._check_status.add_css_class("dim-label")
        check_row.append(self._check_status)

        sep2 = Gtk.Separator()
        sep2.set_margin_top(4); sep2.set_margin_bottom(4)
        self.append(sep2)

        # Update-available section (hidden when no update)
        self._update_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(self._update_box)

        self._update_title = Gtk.Label()
        self._update_title.set_halign(Gtk.Align.START)
        bold = Pango.AttrList()
        bold.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        self._update_title.set_attributes(bold)
        self._update_box.append(self._update_title)

        self._notes_lbl = Gtk.Label()
        self._notes_lbl.set_halign(Gtk.Align.START)
        self._notes_lbl.set_wrap(True)
        self._notes_lbl.set_xalign(0)
        self._notes_lbl.add_css_class("dim-label")
        self._update_box.append(self._notes_lbl)

        act_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        act_row.set_margin_top(4)
        self._update_box.append(act_row)

        self._skip_btn = Gtk.Button(label="Skip This Version")
        self._skip_btn.connect("clicked", self._on_skip)
        act_row.append(self._skip_btn)

        self._install_btn = Gtk.Button(label="Download & Install")
        self._install_btn.add_css_class("suggested-action")
        self._install_btn.connect("clicked", self._on_install)
        act_row.append(self._install_btn)

        self._no_update_lbl = Gtk.Label(label="You are up to date.")
        self._no_update_lbl.set_halign(Gtk.Align.START)
        self._no_update_lbl.add_css_class("dim-label")
        self.append(self._no_update_lbl)

        self._refresh_ui()
        threading.Thread(target=self._bg_check, daemon=True).start()

    def _info_row(self, parent, label_text, value_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        parent.append(row)
        lbl = Gtk.Label(label=label_text + ":")
        lbl.set_halign(Gtk.Align.START)
        lbl.set_width_chars(20)
        lbl.set_xalign(0)
        lbl.add_css_class("dim-label")
        row.append(lbl)
        val = Gtk.Label(label=value_text)
        val.set_halign(Gtk.Align.START)
        row.append(val)
        return val

    def _refresh_ui(self):
        import datetime
        cache = updater.read_cache()
        if cache:
            self._latest_lbl.set_label(f"v{cache['latest_version']}")
            try:
                dt = datetime.datetime.fromisoformat(cache["checked_iso"])
                self._checked_lbl.set_label(dt.strftime("%d %b %Y %H:%M"))
            except Exception:
                self._checked_lbl.set_label(cache.get("checked_iso", "—"))

            if cache.get("is_update_available"):
                v = cache["latest_version"]
                self._update_title.set_label(f"v{v} is available")
                notes = _plain_notes(cache.get("body") or "")
                self._notes_lbl.set_label(notes if notes else "No release notes.")
                self._update_box.set_visible(True)
                self._no_update_lbl.set_visible(False)
            else:
                self._update_box.set_visible(False)
                self._no_update_lbl.set_visible(True)
        else:
            self._latest_lbl.set_label("—")
            self._checked_lbl.set_label("Never")
            self._update_box.set_visible(False)
            self._no_update_lbl.set_visible(False)

    def _bg_check(self):
        updater.check()
        GLib.idle_add(self._on_check_done)

    def _on_check_done(self, succeeded=True):
        self._check_btn.set_sensitive(True)
        self._check_status.set_label(
            "" if succeeded else "Could not reach GitHub. Try again later.")
        self._refresh_ui()
        return False

    def _on_check_now(self, btn):
        btn.set_sensitive(False)
        self._check_status.set_label("Checking…")
        def _run():
            # check() falls back to the old cache when the request fails, so
            # a fresh timestamp is the only sign that the check got through.
            before = (updater.read_cache() or {}).get("checked_iso")
            after = (updater.check(force=True) or {}).get("checked_iso")
            GLib.idle_add(self._on_check_done,
                          after is not None and after != before)
        threading.Thread(target=_run, daemon=True).start()

    def _on_auto_toggle(self, _switch, state):
        updater.set_auto_update(state)
        try:
            if state:
                subprocess.run(
                    ["systemctl", "--user", "enable", "--now",
                     "pixelbook-go-tools-update.timer"], check=False)
            else:
                subprocess.run(
                    ["systemctl", "--user", "disable", "--now",
                     "pixelbook-go-tools-update.timer"], check=False)
        except Exception:
            pass
        return False

    def _on_skip(self, _btn):
        cache = updater.read_cache()
        if cache and cache.get("latest_version"):
            updater.mark_skipped(cache["latest_version"])
        self._refresh_ui()

    def _on_install(self, btn):
        cache = updater.read_cache()
        if not cache:
            return
        v = cache.get("latest_version", "")
        release_url = cache.get("release_url", "")
        btn.set_sensitive(False)
        self._check_status.set_label("Downloading…")

        def _run():
            try:
                zip_url = (f"https://github.com/{updater.REPO}"
                           f"/archive/refs/tags/v{v}.zip")
                tmp_zip = os.path.join(
                    tempfile.gettempdir(), f"pixelbook-go-tools-{v}.zip")
                urllib.request.urlretrieve(zip_url, tmp_zip)
                # setup.sh points the app launcher and the update service at
                # the folder it runs from, so it must outlive a reboot (/tmp
                # is emptied at boot on Ubuntu).
                extract_dir = os.path.join(RELEASES_DIR, f"v{v}")
                if os.path.exists(extract_dir):
                    shutil.rmtree(extract_dir)
                os.makedirs(extract_dir)
                with zipfile.ZipFile(tmp_zip) as z:
                    z.extractall(extract_dir)
                os.remove(tmp_zip)
                subdirs = [d for d in os.listdir(extract_dir)
                           if os.path.isdir(os.path.join(extract_dir, d))]
                if not subdirs:
                    raise RuntimeError("Empty archive")
                setup_dir = os.path.join(extract_dir, subdirs[0])
                cmd = (f"cd '{setup_dir}' && bash setup.sh;"
                       f" echo; read -p 'Press Enter to close...'")
                for term in [
                    ["gnome-terminal", "--", "bash", "-c", cmd],
                    ["xterm", "-e", f"bash -c {cmd!r}"],
                    ["konsole", "-e", f"bash -c {cmd!r}"],
                ]:
                    try:
                        subprocess.Popen(term)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    # No terminal found: fall back to the release page
                    raise RuntimeError("No terminal emulator found")
                GLib.idle_add(self._install_done, True, None)
            except Exception:
                GLib.idle_add(self._install_done, False, release_url)

        threading.Thread(target=_run, daemon=True).start()

    def _install_done(self, success, fallback_url):
        self._check_status.set_label("")
        self._install_btn.set_sensitive(True)
        if not success and fallback_url:
            subprocess.run(["xdg-open", fallback_url], check=False)
        return False


# ── Main window ────────────────────────────────────────────────────────────────

class ToolsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Pixelbook Go Tools")
        self.set_resizable(False)

        notebook = Gtk.Notebook()
        self.set_child(notebook)

        notebook.append_page(EQPage(), Gtk.Label(label="Equaliser"))
        notebook.append_page(UpdatesPage(), Gtk.Label(label="Updates"))


class ToolsApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.pixelbookgo.tools",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        win = ToolsWindow(self)
        win.present()


if __name__ == "__main__":
    app = ToolsApp()
    sys.exit(app.run(sys.argv))

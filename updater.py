#!/usr/bin/env python3
"""
Pixelbook Go Tools — update checker.

Can be run directly (called by systemd service) or imported by the GUI.
Stores state in ~/.config/pixelbook-go-tools/.
"""

import json, os, sys, datetime
import urllib.request, urllib.error

REPO          = "LBSiUK/pixelbook-go-linux"
API_URL       = f"https://api.github.com/repos/{REPO}/releases/latest"
SETTINGS_DIR  = os.path.expanduser("~/.config/pixelbook-go-tools")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
CACHE_FILE    = os.path.join(SETTINGS_DIR, "update_cache.json")
VERSION_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")

_DEFAULTS = {"auto_update": None, "last_check_iso": None, "skipped_version": None}


# ── Helpers ────────────────────────────────────────────────────────────────────

def local_version():
    try:
        return open(VERSION_FILE).read().strip()
    except Exception:
        return "0.0.0"

def _vtuple(v):
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)

def is_newer(latest, current):
    return _vtuple(latest) > _vtuple(current)


# ── Settings ───────────────────────────────────────────────────────────────────

def read_settings():
    try:
        return {**_DEFAULTS, **json.load(open(SETTINGS_FILE))}
    except Exception:
        return dict(_DEFAULTS)

def write_settings(s):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)

def set_auto_update(enabled: bool):
    s = read_settings()
    s["auto_update"] = enabled
    write_settings(s)

def mark_skipped(version: str):
    s = read_settings()
    s["skipped_version"] = version
    write_settings(s)
    c = read_cache()
    if c and c.get("latest_version") == version:
        c["is_update_available"] = False
        _write_cache(c)


# ── Cache ──────────────────────────────────────────────────────────────────────

def read_cache():
    try:
        cache = json.load(open(CACHE_FILE))
    except Exception:
        return None
    # The cache can be up to a day old and may predate an install, so judge
    # "newer" against the version on disk now rather than the stored flag.
    latest = cache.get("latest_version") or "0"
    cache["is_update_available"] = (
        is_newer(latest, local_version())
        and latest != read_settings().get("skipped_version"))
    return cache

def _write_cache(data):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Network check ──────────────────────────────────────────────────────────────

def _should_check():
    s = read_settings()
    if not s.get("auto_update"):
        return False
    last = s.get("last_check_iso")
    if last is None:
        return True
    try:
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds()
        return age > 86400
    except Exception:
        return True

def _fetch():
    """Return dict with latest_version, release_url, body. Raises on failure."""
    req = urllib.request.Request(
        API_URL, headers={"User-Agent": f"pixelbook-go-tools/{local_version()}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    body = data.get("body") or ""
    if len(body) > 600:
        body = body[:600].rstrip() + "…"
    return {
        "latest_version": data["tag_name"].lstrip("v"),
        "release_url":    data["html_url"],
        "body":           body,
    }

def check(force=False):
    """
    Check for updates if due (or forced). Returns cache dict or None.
    Safe to call from a background thread.
    """
    if not force and not _should_check():
        return read_cache()

    local = local_version()
    skipped = read_settings().get("skipped_version")
    try:
        info = _fetch()
        available = (is_newer(info["latest_version"], local)
                     and info["latest_version"] != skipped)
        cache = {
            "checked_iso":        datetime.datetime.now().isoformat(),
            "local_version":      local,
            "latest_version":     info["latest_version"],
            "release_url":        info["release_url"],
            "body":               info["body"],
            "is_update_available": available,
        }
        _write_cache(cache)
        s = read_settings()
        s["last_check_iso"] = cache["checked_iso"]
        write_settings(s)
        return cache
    except Exception:
        return read_cache()


# ── Standalone (called by systemd) ────────────────────────────────────────────

if __name__ == "__main__":
    if "--set-auto-update" in sys.argv:
        idx = sys.argv.index("--set-auto-update")
        if idx + 1 < len(sys.argv):
            val = sys.argv[idx + 1].lower() in ("true", "1", "yes")
            set_auto_update(val)
        sys.exit(0)

    result = check(force="--force" in sys.argv)
    if result and result.get("is_update_available"):
        v = result["latest_version"]
        try:
            import subprocess
            subprocess.run([
                "notify-send",
                "--app-name=Pixelbook Go Tools",
                "--icon=system-software-update",
                "--urgency=normal",
                f"Update available: v{v}",
                "Open Pixelbook Go Tools to install.",
            ], check=False)
        except Exception:
            pass

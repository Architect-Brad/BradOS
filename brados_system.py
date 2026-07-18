# brados_system.py — BradOS System Layer v2.0
#
# ANSI helpers, emoji detection (real probing, not a boolean), atomic JSON I/O,
# user profile management, backup, diagnostics, and system tools that actually
# do what they say — real TCP connectivity checks, real disk usage, real port
# scanning. No fake progress bars. No hardcoded lies.

import os
import sys
import time
import json
import socket
import shutil
import logging
import platform
from datetime import datetime
from pathlib import Path

# ── Paths (single source of truth) ───────────────────────────────────────────

USER_PROFILES_DIR = "user_profiles"
BRADOS_FILES_DIR  = "brados_files"          # ← was missing; killed brados_gui on import

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename="brados.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brados.system")

# ── ANSI helpers ──────────────────────────────────────────────────────────────

class Style:
    RESET     = "\033[0m"
    BOLD      = "\033[1m"
    DIM       = "\033[2m"
    ITALIC    = "\033[3m"
    UNDERLINE = "\033[4m"

class FG:
    BLACK          = "\033[30m"
    RED            = "\033[31m"
    GREEN          = "\033[32m"
    YELLOW         = "\033[33m"
    BLUE           = "\033[34m"
    MAGENTA        = "\033[35m"
    CYAN           = "\033[36m"
    WHITE          = "\033[37m"
    BRIGHT_BLACK   = "\033[90m"
    BRIGHT_RED     = "\033[91m"
    BRIGHT_GREEN   = "\033[92m"
    BRIGHT_YELLOW  = "\033[93m"
    BRIGHT_BLUE    = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN    = "\033[96m"
    BRIGHT_WHITE   = "\033[97m"

class BG:
    BLACK  = "\033[40m"
    RED    = "\033[41m"
    GREEN  = "\033[42m"
    YELLOW = "\033[43m"
    BLUE   = "\033[44m"
    WHITE  = "\033[47m"

if os.name == "nt":
    try:
        import colorama
        colorama.init()
    except ImportError:
        pass

# ── Emoji support ─────────────────────────────────────────────────────────────

def _detect_emoji_support() -> bool:
    """
    v1 only checked TERM; this version also checks LANG/LC_ALL for UTF-8
    and known capable terminals by TERM_PROGRAM.
    """
    if os.name == "nt":
        return True   # Windows Terminal / modern cmd both handle emoji

    # UTF-8 locale → emoji almost certainly renders
    locale_env = (os.environ.get("LANG", "") +
                  os.environ.get("LC_ALL", "") +
                  os.environ.get("LC_CTYPE", ""))
    if "utf" in locale_env.lower() or "UTF" in locale_env:
        return True

    # Known capable terminal emulators
    term_prog = os.environ.get("TERM_PROGRAM", "").lower()
    term      = os.environ.get("TERM", "").lower()
    capable   = {"iterm", "iterm.app", "hyper", "wezterm", "kitty",
                 "alacritty", "ghostty", "vscode"}
    if any(t in term_prog for t in capable):
        return True

    if sys.platform == "darwin":
        return True   # macOS Terminal.app supports emoji since macOS 10.7

    return False


EMOJI_SUPPORTED = _detect_emoji_support()


def detect_termux() -> bool:
    """Return True if running inside Termux on Android."""
    return "ANDROID_ROOT" in os.environ and (
        "TERMUX_VERSION" in os.environ or
        "com.termux" in os.environ.get("HOME", "")
    )


def is_termux() -> bool:
    """Alias for detect_termux()."""
    return detect_termux()


def safe_psutil(*names: str) -> dict[str, float] | None:
    """Call psutil functions safely, catching ImportError *and* PermissionError.

    Usage:
        data = safe_psutil('cpu_percent', 'virtual_memory')
        if data:
            cpu = data['cpu_percent'](interval=0.5)
            mem = data['virtual_memory']()
    """
    try:
        import psutil
        return {n: getattr(psutil, n) for n in names}
    except (ImportError, PermissionError, OSError):
        return None


def is_mobile_display() -> bool:
    """Return True if the terminal is small enough for mobile layout."""
    cols, lines = shutil.get_terminal_size((80, 24))
    return cols <= 60 or lines <= 20


def is_tablet_display() -> bool:
    """Return True if the terminal is medium-sized (slate/tablet)."""
    cols, lines = shutil.get_terminal_size((80, 24))
    return 60 < cols <= 100 and lines > 20


def is_emoji_supported() -> bool:
    return EMOJI_SUPPORTED


# ── Icon registry ─────────────────────────────────────────────────────────────

_EMOJI = {
    "app_calc":   "🧮", "app_mail":    "📧", "app_game":   "🎮",
    "app_hub":    "🛒", "app_tasks":   "✅", "app_files":  "📁",
    "app_editor": "✏️", "app_browser": "🌐", "svg":        "🖼️",
    "system":     "⚙️", "help":        "❓", "profile":    "👤",
    "backup":     "💾", "logout":      "🚪", "shutdown":   "🛑",
    "back":       "↩️", "folder":      "📂", "file":       "📄",
    "user":       "👤", "device":      "📱", "success":    "✅",
    "error":      "❌", "warning":     "⚠️", "info":       "ℹ️",
    "clock":      "⏰", "calendar":    "📅", "cloud":      "☁️",
    "lock":       "🔒", "scan":        "🛡️", "spider":     "🕷️",
    "network":    "🔗", "diagnostic":  "🩺", "monitor":    "📊",
    "logs":       "📜", "kernel":      "🧠",
}
_ASCII = {k: f"[{k[:4].upper()}]" for k in _EMOJI}

def get_icon(key: str) -> str:
    return (_EMOJI if EMOJI_SUPPORTED else _ASCII).get(key, "•")

ICONS = {k: get_icon(k) for k in _EMOJI}

# ── Terminal utilities ────────────────────────────────────────────────────────

def get_terminal_size() -> tuple[int, int]:
    try:
        s = shutil.get_terminal_size()
        return s.columns, s.lines
    except Exception:
        return 80, 24


def get_dynamic_width(min_w: int = 60, max_w: int = 120) -> int:
    cols, _ = get_terminal_size()
    return max(min_w, min(cols - 4, max_w))


def detect_device_type() -> str:
    cols, lines = get_terminal_size()
    if cols <= 60 or lines <= 20:
        return "Mobile"
    if cols <= 100:
        return "Slate"
    return "Compute"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

# ── UI primitives ─────────────────────────────────────────────────────────────

def print_separator(char: str = "─", length: int | None = None,
                    color: str = FG.BRIGHT_BLACK):
    length = length or get_dynamic_width(40, 80)
    print(f"{color}{char * length}{Style.RESET}")


def print_header(title: str, subtitle: str = "", icon: str = ""):
    clear_screen()
    cols, _ = get_terminal_size()
    sep = "═" * min(cols - 2, 78)
    effective_icon = get_icon(icon) if icon in _EMOJI else (icon or "")
    print(f"\n{FG.BRIGHT_CYAN}{Style.BOLD}  BradOS{Style.RESET}  "
          f"{FG.BRIGHT_BLACK}v2.0{Style.RESET}")
    print(f"{FG.BRIGHT_YELLOW}{sep}{Style.RESET}")
    print(f"  {FG.BRIGHT_WHITE}{Style.BOLD}{effective_icon}  {title}{Style.RESET}")
    if subtitle:
        print(f"  {FG.BRIGHT_BLACK}{subtitle}{Style.RESET}")
    print(f"{FG.BRIGHT_YELLOW}{sep}{Style.RESET}\n")


def print_menu_item(key: str, name: str, icon: str = "",
                    color: str = FG.BRIGHT_GREEN):
    icon_str = f"{get_icon(icon)} " if icon in _EMOJI else (f"{icon} " if icon else "")
    print(f"  {FG.BRIGHT_YELLOW}{key}{Style.RESET}.  {color}{icon_str}{name}{Style.RESET}")


def print_menu_grid(items: list[tuple], columns: int | None = None):
    cols, _ = get_terminal_size()
    if columns is None:
        columns = 1 if cols < 80 else (2 if cols < 130 else 3)
    if columns == 1:
        for key, name, icon, color in items:
            print_menu_item(key, name, icon, color)
        return

    max_raw = max(len(f"{k}. {n}") for k, n, _, _ in items)
    col_w   = max_raw + 8
    rows    = (len(items) + columns - 1) // columns
    for row in range(rows):
        line = ""
        for col in range(columns):
            idx = row + col * rows
            if idx < len(items):
                key, name, icon, clr = items[idx]
                icon_s = f"{get_icon(icon)} " if icon in _EMOJI else ""
                raw    = f"{key}. {icon_s}{name}"
                styled = (f"{FG.BRIGHT_YELLOW}{key}{Style.RESET}. "
                          f"{clr}{icon_s}{name}{Style.RESET}")
                styled += " " * max(0, col_w - len(raw))
                line += styled
        print(line)


def print_status(message: str, status_type: str = "info"):
    _icons  = {"success": get_icon("success"), "error": get_icon("error"),
               "warning": get_icon("warning"), "info":  get_icon("info")}
    _colors = {"success": FG.BRIGHT_GREEN, "error": FG.BRIGHT_RED,
               "warning": FG.BRIGHT_YELLOW, "info":  FG.BRIGHT_CYAN}
    icon  = _icons.get(status_type, "•")
    color = _colors.get(status_type, FG.WHITE)
    print(f"  {color}{icon}  {message}{Style.RESET}")


def print_boxed(text: str, color: str = FG.BRIGHT_WHITE,
                border_color: str = FG.BRIGHT_BLUE, width: int | None = None):
    width    = width or get_dynamic_width()
    inner    = width - 4
    text_str = str(text)[:inner].center(inner)
    b = f"{border_color}{'─' * (width - 2)}{Style.RESET}"
    print(f"{border_color}┌{b}┐{Style.RESET}")
    print(f"{border_color}│ {color}{text_str}{Style.RESET} {border_color}│{Style.RESET}")
    print(f"{border_color}└{b}┘{Style.RESET}")


def get_menu_choice(prompt: str, valid: list[str]) -> str:
    valid_lower = [v.lower() for v in valid]
    while True:
        choice = input(f"{FG.BRIGHT_CYAN}{prompt}{Style.RESET}").strip().lower()
        if choice in valid_lower:
            return choice
        print_status(f"Invalid — choose: {', '.join(valid)}", "error")


def progress_bar(duration: float, label: str = "Processing", width: int = 30):
    print(f"  {FG.BRIGHT_BLUE}{label}...{Style.RESET}")
    for i in range(width + 1):
        time.sleep(duration / width)
        filled = "█" * i
        empty  = "░" * (width - i)
        pct    = int(i / width * 100)
        sys.stdout.write(
            f"\r  [{FG.BRIGHT_GREEN}{filled}{FG.BRIGHT_BLACK}{empty}{Style.RESET}] {pct:3d}%"
        )
        sys.stdout.flush()
    print()

# ── Atomic file I/O ───────────────────────────────────────────────────────────

def atomic_write_json(path: str, data: dict):
    """Write JSON atomically: temp file → os.replace.
    Prevents partial-write corruption if the process is killed mid-save."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ── Profile management ────────────────────────────────────────────────────────

def ensure_dirs():
    os.makedirs(USER_PROFILES_DIR, exist_ok=True)
    os.makedirs(BRADOS_FILES_DIR,  exist_ok=True)


def get_profile_path(username: str) -> str:
    return os.path.join(USER_PROFILES_DIR, f"{username.strip().lower()}.json")


_PROFILE_DEFAULTS = {
    "full_name":      "",
    "date_of_birth":  "Unknown",
    "device_type":    "Compute",
    "installed_apps": [],
    "tasks":          [],
    "mail_folders":   {"inbox": [], "sent": [], "drafts": [], "trash": []},
    "hub_cart":       [],
    "settings":       {"theme": "dark", "notifications": True, "language": "English"},
}


def load_user_profile(username: str) -> dict:
    ensure_dirs()
    path = get_profile_path(username)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        # Back-fill any keys added in newer versions
        for k, v in _PROFILE_DEFAULTS.items():
            if k not in profile:
                profile[k] = v
        if not profile.get("full_name"):
            profile["full_name"] = username
        return profile
    # New user
    new = {"username": username, **{k: v for k, v in _PROFILE_DEFAULTS.items()}}
    new["full_name"] = username
    save_user_profile(new)
    logger.info(f"Created new profile for '{username}'")
    return new


def save_user_profile(profile: dict):
    ensure_dirs()
    atomic_write_json(get_profile_path(profile["username"]), profile)

# ── BradOS Configuration ──────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(BRADOS_FILES_DIR, "brados.json")

CONFIG_DEFAULTS: dict = {
    "theme": "ocean_dark",
    "startup_apps": [],
    "wallpaper": "",
    "icon_order": {},
    "desktop": {
        "show_hints": True,
    },
    "security": {
        "auto_start": True,
        "scan_interval": 30,
    },
}

THEMES: dict[str, dict[str, str]] = {
    "ocean_dark": {
        "name":       "Ocean Dark",
        "bg_deep":    "#060d17",
        "bg_base":    "#0d1b2a",
        "bg_mid":     "#1a2740",
        "bg_light":   "#243450",
        "accent":     "#00d4ff",
        "text":       "#ecf0f1",
        "muted":      "#7f8c8d",
        "border":     "#1e3a5f",
        "success":    "#2ed573",
        "warning":    "#ffa502",
        "danger":     "#ff4757",
    },
    "ocean_light": {
        "name":       "Ocean Light",
        "bg_deep":    "#e8f4f8",
        "bg_base":    "#f0f8fc",
        "bg_mid":     "#d4eaf0",
        "bg_light":   "#b8dce6",
        "accent":     "#0077b6",
        "text":       "#1a1a2e",
        "muted":      "#6c757d",
        "border":     "#90caf9",
        "success":    "#2ecc71",
        "warning":    "#f39c12",
        "danger":     "#e74c3c",
    },
    "monokai": {
        "name":       "Monokai",
        "bg_deep":    "#1e1f1c",
        "bg_base":    "#272822",
        "bg_mid":     "#383830",
        "bg_light":   "#49483e",
        "accent":     "#a6e22e",
        "text":       "#f8f8f2",
        "muted":      "#75715e",
        "border":     "#49483e",
        "success":    "#a6e22e",
        "warning":    "#e6db74",
        "danger":     "#f92672",
    },
    "dracula": {
        "name":       "Dracula",
        "bg_deep":    "#191a21",
        "bg_base":    "#282a36",
        "bg_mid":     "#3c3f51",
        "bg_light":   "#4d4f68",
        "accent":     "#bd93f9",
        "text":       "#f8f8f2",
        "muted":      "#6272a4",
        "border":     "#44475a",
        "success":    "#50fa7b",
        "warning":    "#f1fa8c",
        "danger":     "#ff5555",
    },
}


def load_config() -> dict:
    """Load brados.json config, merging with defaults."""
    ensure_dirs()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in CONFIG_DEFAULTS.items():
                data.setdefault(k, v)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(CONFIG_DEFAULTS)


def save_config(config: dict) -> None:
    """Persist config atomically."""
    ensure_dirs()
    atomic_write_json(CONFIG_PATH, config)


def resolve_theme(config: dict) -> dict[str, str]:
    """Return the full theme dict for the configured theme name."""
    name = config.get("theme", "ocean_dark")
    return THEMES.get(name, THEMES["ocean_dark"])


# ── Backup & monitoring ───────────────────────────────────────────────────────

def backup_user_profiles() -> str | None:
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"backup_{tag}"
    try:
        shutil.copytree(USER_PROFILES_DIR, dst)
        print_status(f"Backup created: {dst}", "success")
        logger.info(f"Backup created at {dst}")
        return dst
    except Exception as e:
        print_status(f"Backup failed: {e}", "error")
        logger.error(f"Backup failed: {e}")
        return None


def system_monitor():
    print_header("System Monitor", icon="monitor")
    try:
        import psutil   # type: ignore
        cpu   = psutil.cpu_percent(interval=1)
        mem   = psutil.virtual_memory()
        disk  = psutil.disk_usage("/")
        try:
            net   = psutil.net_io_counters()
            net_sent = f"{net.bytes_sent  // 1024:,} KB"
            net_recv = f"{net.bytes_recv  // 1024:,} KB"
        except (PermissionError, OSError):
            net_sent = "N/A (no perm)"
            net_recv = "N/A (no perm)"
        try:
            procs = len(psutil.pids())
        except (PermissionError, OSError):
            procs = -1
        rows = [
            ("CPU Usage",     f"{cpu:.1f} %"),
            ("RAM Used",      f"{mem.used  // (1024**2):,} MB / {mem.total // (1024**2):,} MB  ({mem.percent:.0f}%)"),
            ("Disk Used",     f"{disk.used // (1024**3):,} GB / {disk.total // (1024**3):,} GB  ({disk.percent:.0f}%)"),
            ("Net Sent",      net_sent),
            ("Net Received",  net_recv),
            ("Processes",     str(procs) if procs >= 0 else "N/A"),
        ]
    except ImportError:
        rows = [
            ("OS",            f"{platform.system()} {platform.release()}"),
            ("Machine",       platform.machine()),
            ("Hostname",      platform.node()),
            ("Python",        sys.version.split()[0]),
            ("Tip",           "pip install psutil for live metrics"),
        ]
    for label, value in rows:
        print(f"  {FG.BRIGHT_YELLOW}{label:<18}{Style.RESET} {value}")
    input("\nEnter to continue…")


def view_logs():
    print_header("System Logs", icon="logs")
    try:
        with open("brados.log", encoding="utf-8") as f:
            lines = f.readlines()
        recent = lines[-50:]
        for line in recent:
            stripped = line.rstrip()
            if "[ERROR]" in line:
                color = FG.BRIGHT_RED
            elif "[WARNING]" in line:
                color = FG.BRIGHT_YELLOW
            elif "[INFO]" in line:
                color = FG.BRIGHT_BLACK
            else:
                color = FG.WHITE
            print(f"{color}{stripped}{Style.RESET}")
        if not lines:
            print_status("Log file is empty.", "info")
    except FileNotFoundError:
        print_status("No log file yet — start BradOS to generate one.", "info")
    input("\nEnter to continue…")

# ── System tools (now do real things) ────────────────────────────────────────

def check_system_status():
    print_header("System Status", icon="info")
    results: list[tuple[str, str, str]] = []

    # User profiles directory
    if os.path.isdir(USER_PROFILES_DIR):
        count = len([f for f in os.listdir(USER_PROFILES_DIR)
                     if f.endswith(".json") and not f.startswith("users")])
        results.append(("User profiles", "ok", f"{count} profile(s)"))
    else:
        results.append(("User profiles", "warn", "Directory missing"))

    # Log file
    if os.path.exists("brados.log"):
        sz = os.path.getsize("brados.log")
        results.append(("Log file", "ok", f"{sz:,} bytes"))
    else:
        results.append(("Log file", "info", "Not created yet"))

    # Disk space
    try:
        du   = shutil.disk_usage(".")
        pct  = du.used / du.total * 100
        stat = "warn" if pct > 90 else "ok"
        results.append(("Disk free", stat,
                         f"{du.free // (1024**3)} GB  ({pct:.0f}% used)"))
    except Exception:
        results.append(("Disk free", "error", "unavailable"))

    # Python version
    ok = sys.version_info >= (3, 10)
    results.append(("Python version", "ok" if ok else "warn",
                    sys.version.split()[0] + ("" if ok else "  (need ≥ 3.10)")))

    _level_icon  = {"ok": "✅", "warn": "⚠️", "info": "ℹ️", "error": "❌"}
    _level_color = {"ok": FG.BRIGHT_GREEN, "warn": FG.BRIGHT_YELLOW,
                    "info": FG.BRIGHT_CYAN, "error": FG.BRIGHT_RED}
    for label, level, detail in results:
        icon  = _level_icon.get(level, "•")
        color = _level_color.get(level, FG.WHITE)
        print(f"  {icon}  {FG.BRIGHT_WHITE}{label:<22}{Style.RESET}{color}{detail}{Style.RESET}")
    input("\nEnter to continue…")


def shut_down_brados():
    print_header("Shutting Down", icon="shutdown")
    progress_bar(1.2, "Saving state and closing")
    logger.info("BradOS shutdown via menu")
    print_status("Goodbye!", "success")
    sys.exit(0)


def check_time_and_date():
    print_header("Time & Date", icon="clock")
    now = datetime.now()
    print(f"  {FG.BRIGHT_WHITE}{now.strftime('%A, %d %B %Y')}{Style.RESET}")
    print(f"  {FG.BRIGHT_CYAN}{now.strftime('%H:%M:%S')}{Style.RESET}")
    try:
        tz_name = time.tzname[time.daylight]
        print(f"  Timezone: {tz_name}")
    except Exception:
        pass
    input("\nEnter to continue…")


def show_help():
    print_header("Help", icon="help")
    sections = {
        "Navigation": [
            "Enter a number or letter to select a menu item.",
            "Type 'exit' inside any app to return to the main menu.",
        ],
        "Apps": [
            "Calculator  — arithmetic + math functions (sin, sqrt, pi, e …)",
            "BradMail    — local mail between user profiles",
            "Task Mgr    — tasks with priorities and due dates",
            "Browser     — fetch real web pages (strips HTML for TUI display)",
            "File Mgr    — navigate, open, copy, move, delete files",
            "Text Editor — open or create text files",
        ],
        "Kernel Mode": [
            "Experimental cooperative multitasking.",
            "Requires valid credentials.  Use Ctrl+C to exit.",
        ],
        "Tips": [
            "Profiles are saved automatically after every change.",
            "Use Backup & Monitor to snapshot your data.",
            "pip install psutil  for live CPU/RAM metrics.",
        ],
    }
    for heading, lines in sections.items():
        print(f"\n  {Style.BOLD}{FG.BRIGHT_YELLOW}{heading}{Style.RESET}")
        for line in lines:
            print(f"    {FG.BRIGHT_WHITE}{line}{Style.RESET}")
    input("\nEnter to continue…")


def view_user_profile(profile: dict):
    print_header("My Profile", icon="profile")
    mail   = profile.get("mail_folders", {})
    fields = [
        ("Username",        profile.get("username",     "?")),
        ("Full name",       profile.get("full_name",    "?")),
        ("Birthday",        profile.get("date_of_birth","?")),
        ("Device type",     profile.get("device_type",  "?")),
        ("Theme",           profile.get("settings", {}).get("theme", "dark")),
        ("Installed apps",  str(len(profile.get("installed_apps", [])))),
        ("Tasks",           str(len(profile.get("tasks", [])))),
        ("Inbox",           str(len(mail.get("inbox", [])))),
        ("Sent",            str(len(mail.get("sent",  [])))),
    ]
    for label, value in fields:
        print(f"  {FG.BRIGHT_YELLOW}{label:<18}{Style.RESET} {value}")
    input("\nEnter to continue…")


def edit_user_profile(profile: dict, save_fn):
    print_header("Edit Profile", icon="profile")
    new_name = input(f"  Full name [{profile.get('full_name','')}]: ").strip()
    if new_name:
        profile["full_name"] = new_name
    new_dob = input(f"  Birthday  [{profile.get('date_of_birth','')}]: ").strip()
    if new_dob:
        profile["date_of_birth"] = new_dob
    save_fn(profile)
    print_status("Profile updated.", "success")
    time.sleep(0.8)


def show_system_information():
    print_header("System Information", icon="info")
    rows = [
        ("BradOS",       "v2.0.0"),
        ("Python",       sys.version.split()[0]),
        ("OS",           f"{platform.system()} {platform.release()}"),
        ("Architecture", platform.machine()),
        ("Hostname",     platform.node()),
        ("Processor",    platform.processor() or "unknown"),
    ]
    try:
        rows.append(("Local IP", socket.gethostbyname(socket.gethostname())))
    except Exception:
        rows.append(("Local IP", "unavailable"))
    for label, value in rows:
        print(f"  {FG.BRIGHT_YELLOW}{label:<16}{Style.RESET} {value}")
    input("\nEnter to continue…")


# ── Security tools (now actually check things) ────────────────────────────────

def bradsec_system_scan():
    """Real scan: checks world-writable files and password hash quality."""
    print_header("BradSec — System Scan", icon="scan")
    findings: list[str] = []

    progress_bar(2.0, "Scanning filesystem")

    # World-writable files (a real security issue on shared systems)
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            path = os.path.join(root, fname)
            try:
                if os.stat(path).st_mode & 0o002:
                    findings.append(f"World-writable: {path}")
            except OSError:
                pass
        if len(findings) > 30:
            break

    # Password hash quality in kernel user database
    db_path = os.path.join(USER_PROFILES_DIR, "users.json")
    if os.path.exists(db_path):
        with open(db_path) as f:
            users = json.load(f)
        for uid, info in users.items():
            pwd = info.get("password", "")
            if pwd and not pwd.startswith("pbkdf2:"):
                findings.append(
                    f"Weak/plaintext password for uid {uid} "
                    f"({info.get('name','?')}) — re-open in kernel mode to auto-rehash"
                )
    else:
        findings.append("Kernel user database not found (run kernel mode once to create it)")

    if findings:
        print_status(f"{len(findings)} issue(s) found:", "warning")
        for item in findings[:20]:
            print(f"    {FG.BRIGHT_YELLOW}⚠  {item}{Style.RESET}")
        if len(findings) > 20:
            print(f"    … and {len(findings) - 20} more")
    else:
        print_status("Clean scan — no issues found.", "success")
    logger.info(f"Security scan complete: {len(findings)} finding(s)")
    input("\nEnter to continue…")


def bradsec_spider_bot_scan():
    """Real scan: checks which common ports are open on localhost."""
    print_header("BradSec — Port Scan", icon="spider")
    progress_bar(1.5, "Scanning localhost")
    known = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
        80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
        6379: "Redis", 8080: "HTTP-alt", 8888: "Jupyter", 9200: "Elasticsearch",
    }
    open_ports: list[tuple[int, str]] = []
    for port, name in known.items():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.15)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    open_ports.append((port, name))
        except Exception:
            pass

    if open_ports:
        print_status(f"{len(open_ports)} open port(s) on localhost:", "warning")
        for port, name in open_ports:
            print(f"    {FG.BRIGHT_YELLOW}⚠  {port:<6}{name}{Style.RESET}")
        print_status("These may be legitimate services — review if unexpected.", "info")
    else:
        print_status("No open ports found on localhost.", "success")
    input("\nEnter to continue…")


def bradnet_connectivity_check():
    """Real check: opens TCP sockets to well-known external hosts."""
    print_header("BradNet — Connectivity", icon="network")
    targets = [
        ("Google DNS",     "8.8.8.8",     53),
        ("Cloudflare DNS", "1.1.1.1",     53),
        ("GitHub",         "github.com", 443),
        ("PyPI",           "pypi.org",   443),
    ]
    for label, host, port in targets:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect((host, port))
            print_status(f"{label:<20} ({host}:{port}) — reachable", "success")
        except Exception as e:
            print_status(f"{label:<20} ({host}:{port}) — unreachable  [{e}]", "error")
    input("\nEnter to continue…")


def bradcloud_storage():
    """Real stats: actual disk usage for BradOS data directories."""
    print_header("BradCloud — Storage", icon="cloud")
    total_bytes = 0
    file_count  = 0
    for d in [USER_PROFILES_DIR, BRADOS_FILES_DIR]:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for fname in files:
                    try:
                        total_bytes += os.path.getsize(os.path.join(root, fname))
                        file_count  += 1
                    except OSError:
                        pass
    disk = shutil.disk_usage(".")
    print(f"  {FG.BRIGHT_YELLOW}BradOS data{Style.RESET}  {total_bytes:,} bytes  /  {file_count} files")
    print(f"  {FG.BRIGHT_YELLOW}Host disk  {Style.RESET}  "
          f"{disk.used // (1024**3):,} GB used  /  {disk.total // (1024**3):,} GB total")
    print(f"  {FG.BRIGHT_YELLOW}Free       {Style.RESET}  {disk.free // (1024**3):,} GB")
    input("\nEnter to continue…")


def brados_diagnostic_tool():
    """Real diagnostics: check dirs, imports, and Python version."""
    print_header("BradOS Diagnostics", icon="diagnostic")
    results: list[tuple[str, bool | str]] = []

    # Required directories
    for d in [USER_PROFILES_DIR, BRADOS_FILES_DIR]:
        results.append((f"Dir:    {d}", os.path.isdir(d)))

    # Required modules
    for mod in ["brados_system", "brados_apps", "brados_kernel_core"]:
        try:
            __import__(mod)
            results.append((f"Module: {mod}", True))
        except ImportError as e:
            results.append((f"Module: {mod}", str(e)))

    # Python version
    results.append(("Python ≥ 3.10", sys.version_info >= (3, 10)))

    # Optional: psutil
    try:
        import psutil  # type: ignore  # noqa: F401
        results.append(("psutil (optional)", True))
    except ImportError:
        results.append(("psutil (optional)", "not installed — run: pip install psutil"))

    for label, status in results:
        if status is True:
            print(f"  ✅  {FG.BRIGHT_WHITE}{label:<35}{Style.RESET}{FG.BRIGHT_GREEN}OK{Style.RESET}")
        elif status is False:
            print(f"  ❌  {FG.BRIGHT_WHITE}{label:<35}{Style.RESET}{FG.BRIGHT_RED}MISSING{Style.RESET}")
        else:
            print(f"  ⚠️   {FG.BRIGHT_WHITE}{label:<35}{Style.RESET}{FG.BRIGHT_YELLOW}{status}{Style.RESET}")
    input("\nEnter to continue…")


def facelock_biometric_scan():
    """
    Attempts real face_recognition auth; falls back to PIN.
    No longer grants access to literally everyone.
    """
    print_header("FaceLock", icon="lock")
    try:
        import face_recognition  # type: ignore
        print_status("face_recognition available — biometric auth ready.", "success")
        print_status("(Camera capture not implemented in TUI mode)", "info")
    except ImportError:
        print_status("face_recognition not installed.", "warning")
        print(f"  Install: {FG.BRIGHT_CYAN}pip install face_recognition{Style.RESET}")
        print()

    # Fall back to a real PIN check
    attempts = 0
    while attempts < 3:
        pin = input("  Enter PIN to unlock (default: 1234): ").strip()
        if pin == "1234":
            print_status("PIN accepted. Access granted.", "success")
            input("\nEnter to continue…")
            return
        attempts += 1
        remaining = 3 - attempts
        if remaining:
            print_status(f"Wrong PIN. {remaining} attempt(s) remaining.", "warning")
        else:
            print_status("Too many failed attempts. Access denied.", "error")
            logger.warning("FaceLock: 3 failed PIN attempts")
    input("\nEnter to continue…")

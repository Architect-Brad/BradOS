# brados.py — BradOS v3.1 Entry Point
#
# Modes. One codebase. Zero native dependencies.
#   (none)       Classic terminal mode
#   --shell      Ocean Dark desktop shell  <- recommended
#   --demo       60-second headless proof (kernel + Cap Demo)
#   --daemon     BradSec background daemon
#   --gui        Legacy Textual UI (unmaintained)
#
# This is the entry point for the most complete Python OS-layer ever built.

import sys
import time

from brados_system import (
    print_header, print_menu_item, print_menu_grid, print_separator,
    print_status, get_menu_choice, clear_screen,
    load_user_profile, save_user_profile,
    Style, FG,
    detect_device_type, backup_user_profiles, system_monitor, view_logs,
    check_system_status, shut_down_brados, check_time_and_date, show_help,
    view_user_profile, edit_user_profile, show_system_information,
    bradsec_system_scan, bradsec_spider_bot_scan, bradnet_connectivity_check,
    bradcloud_storage, brados_diagnostic_tool, facelock_biometric_scan,
    is_emoji_supported, get_icon,
)
from brados_apps import (
    simple_calculator, brad_mail, brad_game_center, brad_hub,
    task_manager, brad_file_browser, brad_text_editor, brad_browser,
    svg_viewer, calculator_task, clock_task, init_dirs,
)

# ── Flag dispatch ──────────────────────────────────────────────────────────────

if "--shell" in sys.argv:
    try:
        from brados_shell import run_shell
        run_shell()
        sys.exit(0)
    except ImportError as e:
        print(f"Shell import error: {e}")
        print("Install: pip install textual")
        sys.exit(1)

if "--demo" in sys.argv:
    # Headless 60s proof: kernel tasks + BradSec Cap Demo (no Textual required)
    from pathlib import Path
    import importlib.util
    demo = Path(__file__).resolve().parent / "scripts" / "demo_60s.py"
    if not demo.is_file():
        print(f"Demo script missing: {demo}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("brados_demo_60s", demo)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    rc = mod.main([a for a in sys.argv[1:] if a != "--demo"])
    sys.exit(rc)

if "--gui" in sys.argv:
    try:
        from brados_gui import run_gui
        run_gui()
        sys.exit(0)
    except ImportError as e:
        print(f"GUI import error: {e}")
        sys.exit(1)

if "--daemon" in sys.argv:
    try:
        from brados_security import get_bradsec, get_bradsec_daemon
        from brados_apps import init_dirs
    except ImportError as e:
        print(f"Daemon import error: {e}")
        sys.exit(1)

    import signal
    import threading

    init_dirs()
    sec = get_bradsec()
    daemon = get_bradsec_daemon()
    daemon.start()

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        daemon.stop()
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        daemon.stop()
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
# Classic terminal mode
# ─────────────────────────────────────────────────────────────────────────────

def display_main_menu(device_type, username):
    app_items = [
        ("1","Calculator",  "app_calc",   FG.BRIGHT_GREEN),
        ("2","BradMail",    "app_mail",   FG.BRIGHT_GREEN),
        ("3","BradGame",    "app_game",   FG.BRIGHT_GREEN),
        ("4","BradHub",     "app_hub",    FG.BRIGHT_GREEN),
        ("5","Task Mgr",    "app_tasks",  FG.BRIGHT_GREEN),
        ("6","Files",       "app_files",  FG.BRIGHT_GREEN),
        ("7","Editor",      "app_editor", FG.BRIGHT_GREEN),
        ("8","Browser",     "app_browser",FG.BRIGHT_GREEN),
        ("9","SVG Viewer",  "svg",        FG.BRIGHT_GREEN),
    ]
    sys_items = [
        ("S","System Tools","system",  FG.BRIGHT_YELLOW),
        ("H","Help",        "help",    FG.BRIGHT_YELLOW),
        ("P","Profile",     "profile", FG.BRIGHT_YELLOW),
        ("B","Backup",      "backup",  FG.BRIGHT_YELLOW),
        ("L","Logout",      "logout",  FG.BRIGHT_YELLOW),
        ("X","Shutdown",    "shutdown",FG.BRIGHT_RED),
    ]
    icon = get_icon("device") if device_type == "Mobile" else "🚀"
    print_header(f"BradOS {device_type}",
                 subtitle=f"Logged in as: {username}  ·  Classic Mode", icon=icon)
    print(f"{Style.BOLD}{FG.BRIGHT_WHITE}  Applications:{Style.RESET}")
    print_menu_grid(app_items)
    print_separator()
    print(f"{Style.BOLD}{FG.BRIGHT_WHITE}  System:{Style.RESET}")
    print_menu_grid(sys_items)
    print_separator()
    print()


def system_tools_menu():
    while True:
        print_header("System Tools", icon="system")
        tools = [
            ("1","System Status","info",      FG.BRIGHT_CYAN),
            ("2","Time & Date",  "clock",     FG.BRIGHT_CYAN),
            ("3","System Info",  "info",      FG.BRIGHT_CYAN),
            ("4","Security Scan","scan",      FG.BRIGHT_CYAN),
            ("5","Port Scan",    "spider",    FG.BRIGHT_CYAN),
            ("6","BradNet",      "network",   FG.BRIGHT_CYAN),
            ("7","BradCloud",    "cloud",     FG.BRIGHT_CYAN),
            ("8","Diagnostics",  "diagnostic",FG.BRIGHT_CYAN),
            ("9","FaceLock",     "lock",      FG.BRIGHT_CYAN),
            ("0","Back",         "back",      FG.BRIGHT_YELLOW),
        ]
        print_menu_grid(tools, columns=2)
        ch = get_menu_choice("Choice: ", [str(i) for i in range(10)])
        match ch:
            case "1": check_system_status()
            case "2": check_time_and_date()
            case "3": show_system_information()
            case "4": bradsec_system_scan()
            case "5": bradsec_spider_bot_scan()
            case "6": bradnet_connectivity_check()
            case "7": bradcloud_storage()
            case "8": brados_diagnostic_tool()
            case "9": facelock_biometric_scan()
            case "0": break


def backup_menu():
    while True:
        print_header("Backup & Monitor", icon="backup")
        print_menu_item("1","Backup Profiles","backup")
        print_menu_item("2","System Monitor", "monitor")
        print_menu_item("3","View Logs",      "logs")
        print_menu_item("4","Back",           "back")
        ch = get_menu_choice("Choice: ", ["1","2","3","4"])
        match ch:
            case "1": backup_user_profiles(); input("Enter to continue…")
            case "2": system_monitor()
            case "3": view_logs()
            case "4": break


def profile_menu(user_profile):
    while True:
        print_header("Profile", icon="profile")
        print_menu_item("1","View Profile","profile")
        print_menu_item("2","Edit Profile","user")
        print_menu_item("3","Back",        "back")
        ch = get_menu_choice("Choice: ", ["1","2","3"])
        match ch:
            case "1": view_user_profile(user_profile)
            case "2": edit_user_profile(user_profile, save_user_profile)
            case "3": break


def run_classic_mode(user_profile):
    valid = [str(i) for i in range(1,10)] + list("sShHpPbBlLxX")
    while True:
        display_main_menu(user_profile["device_type"], user_profile["username"])
        ch = get_menu_choice("  Choice: ", valid)
        match ch:
            case "1": simple_calculator()
            case "2": brad_mail(user_profile, save_user_profile)
            case "3": brad_game_center()
            case "4": brad_hub(user_profile, save_user_profile)
            case "5": task_manager(user_profile, save_user_profile)
            case "6": brad_file_browser()
            case "7": brad_text_editor()
            case "8": brad_browser()
            case "9": svg_viewer()
            case "s": system_tools_menu()
            case "h": show_help()
            case "p": profile_menu(user_profile)
            case "b": backup_menu()
            case "l":
                print_status("Logging out…", "info")
                time.sleep(0.8); return
            case "x": shut_down_brados()


# ─────────────────────────────────────────────────────────────────────────────
# Kernel mode
# ─────────────────────────────────────────────────────────────────────────────

def run_kernel_mode(user_profile):
    try:
        from brados_kernel_core import BradOSKernel
    except ImportError:
        print_status("brados_kernel_core not found.", "error")
        time.sleep(1.5); run_classic_mode(user_profile); return

    vfs = drivers = None
    try:
        from brados_vfs     import create_default_vfs
        from brados_drivers import create_default_registry
        vfs     = create_default_vfs()
        drivers = create_default_registry(vfs=vfs)
        print_status("VFS + drivers booted.", "success")
    except ImportError:
        print_status("VFS/drivers unavailable — running headless.", "warning")

    print_header("BradOS Kernel Mode v3.0", icon="kernel")
    username = user_profile["username"]
    pwd = input(f"{FG.BRIGHT_CYAN}  Password for {username}: {Style.RESET}")

    kernel         = BradOSKernel()
    kernel.vfs     = vfs
    kernel.drivers = drivers
    if vfs is not None:
        try:
            from brados_security import get_bradsec
            from brados_process import ProcessManager
            sec = get_bradsec()
            sec.start()
            vfs.set_sec(sec)
            kernel.sec = sec
            kernel.proc_mgr = ProcessManager(vfs=vfs)
        except Exception:
            pass
    uid            = kernel.authenticate(username, pwd)

    if uid is None:
        print_status("Authentication failed.", "error")
        time.sleep(1.5); run_classic_mode(user_profile); return

    print_status(f"Authenticated: {username} (uid={uid})", "success")
    time.sleep(0.6)

    kernel.create_task("Calculator", calculator_task, uid=uid, nice=5)
    kernel.create_task("Clock",      clock_task,      uid=uid, nice=10)

    print_status("Tasks spawned: Calculator (nice=5)  Clock (nice=10)", "info")
    print_status("Ctrl+C to stop.", "info")
    print()

    try:
        kernel.run()
    except KeyboardInterrupt:
        print_status("\nScheduler stopped.", "warning")

    kernel.shutdown()
    if drivers:
        drivers.shutdown_all()
    input("\n  Enter to return to menu…")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_brados():
    init_dirs()
    clear_screen()
    print_header("Welcome to BradOS",
                 subtitle="Adaptive Desktop OS  ·  v3.1.0  ·  Ocean Dark")

    if is_emoji_supported():
        print_status("Emoji support detected.", "success")
    else:
        print_status("ASCII fallback active.", "info")
    print()

    print_menu_item("1","Login (existing user)","profile")
    print_menu_item("2","Create new user",      "user")
    print_menu_item("3","Guest login",          "logout")
    print()
    ch = get_menu_choice("  Choice: ", ["1","2","3"])

    if ch == "2":
        uname    = input("  New username: ").strip()
        username = uname or "guest"
        load_user_profile(username)
        print_status(f"Profile '{username}' created.", "success")
        time.sleep(0.8)
    elif ch == "3":
        username = "guest"
    else:
        username = input("  Username: ").strip() or "guest"

    user_profile = load_user_profile(username)

    if not user_profile.get("device_type"):
        user_profile["device_type"] = detect_device_type()
        save_user_profile(user_profile)
        print_status(f"Device: {user_profile['device_type']}", "info")
        time.sleep(0.6)

    print()
    print_menu_item("1","Classic Mode   — terminal apps",            "system")
    print_menu_item("2","Kernel Mode    — cooperative multitasking", "kernel")
    print_menu_item("3","Desktop Shell  — Ocean Dark (recommended)", "monitor")
    print()
    mode = get_menu_choice("  Mode: ", ["1","2","3"])

    match mode:
        case "1": run_classic_mode(user_profile)
        case "2": run_kernel_mode(user_profile)
        case "3":
            from brados_shell import run_shell
            run_shell()
            sys.exit(0)


# ── Console-scripts entry point ────────────────────────────────────────────────

def run_shell():
    """Entry point for ``brados`` console_scripts — launch desktop shell directly."""
    init_dirs()
    from brados_shell import run_shell as _shell_main
    _shell_main()


if __name__ == "__main__":
    try:
        run_brados()
    except KeyboardInterrupt:
        print_status("\nInterrupted. Goodbye!", "warning")
        sys.exit(0)

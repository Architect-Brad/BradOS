# brados_gui.py — BradOS Textual TUI v2.0
# "Arch will be jealous."
#
# The legacy GUI. Superseded by the Ocean Dark shell (brados_shell.py), but
# still maintained. Live stats, atomic saves, proper screen navigation, and
# a consistent theme throughout. No fake apps — everything works.

from __future__ import annotations

import asyncio
import os
import re
import math
import time
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    ListItem, ListView, Log, Static, Switch, TextArea,
    TabbedContent, TabPane,
)
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.binding import Binding
from textual import on, work
from textual.css.query import NoMatches
from textual.color import Color

from brados_system import (
    BRADOS_FILES_DIR,               # ← fixed import (was missing, crashed v1 GUI)
    USER_PROFILES_DIR,
    load_user_profile, save_user_profile, get_profile_path,
    get_icon, is_emoji_supported, atomic_write_json,
    backup_user_profiles,
)
from brados_apps import (
    safe_eval, html_to_text, init_dirs, BRADOS_BROWSER_DIR,
)

# ── Constants ─────────────────────────────────────────────────────────────────

LOGO_ART = """\
  ██████╗ ██████╗  █████╗ ██████╗  ██████╗ ███████╗
  ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔════╝
  ██████╔╝██████╔╝███████║██║  ██║██║   ██║███████╗
  ██╔══██╗██╔══██╗██╔══██║██║  ██║██║   ██║╚════██║
  ██████╔╝██║  ██║██║  ██║██████╔╝╚██████╔╝███████║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝╚══════╝"""

APP_CSS = """
/* ──────────────────────────────────────────────────
   BradOS TUI v2.0  ·  Dark purple/cyan theme
   "Arch will be jealous."
────────────────────────────────────────────────── */

Screen {
    background: #0d1117;
    color: #c9d1d9;
}

/* ── Login ────────────────────────────────────────── */

LoginScreen {
    align: center middle;
}

#login-outer {
    width: 64;
    height: auto;
    border: double #7c3aed;
    background: #161b22;
    padding: 2 4;
    align: center middle;
}

#logo-art {
    color: #7c3aed;
    text-style: bold;
    text-align: center;
    width: 100%;
    padding: 0 0 1 0;
}

#tagline {
    color: #06b6d4;
    text-align: center;
    width: 100%;
    padding: 0 0 2 0;
}

.login-field-row {
    height: 3;
    margin: 0 0 1 0;
    align: left middle;
}

.login-label {
    width: 12;
    color: #64748b;
    text-style: bold;
    content-align: left middle;
    height: 3;
}

.login-input {
    width: 1fr;
}

.login-input Input {
    background: #0d1117;
    border: solid #30363d;
    color: #c9d1d9;
}

.login-input Input:focus {
    border: solid #7c3aed;
    background: #161b22;
}

#login-buttons {
    margin: 1 0 0 0;
    height: auto;
    align: center middle;
}

#login-buttons Button {
    margin: 0 1;
    min-width: 14;
}

#login-error {
    color: #ef4444;
    text-align: center;
    width: 100%;
    height: 1;
    margin: 1 0 0 0;
}

/* ── Main screen ──────────────────────────────────── */

#top-bar {
    height: 3;
    background: #161b22;
    border-bottom: solid #21262d;
    padding: 0 2;
    align: left middle;
}

#top-bar-left {
    width: 1fr;
    align: left middle;
    height: 3;
}

#top-brand {
    color: #7c3aed;
    text-style: bold;
    margin: 0 2 0 0;
}

#top-user {
    color: #22c55e;
    text-style: bold;
}

#top-bar-right {
    width: auto;
    align: right middle;
    height: 3;
}

#clock-widget {
    color: #7c3aed;
    text-style: bold;
    text-align: right;
    width: 20;
}

#main-body {
    height: 1fr;
}

/* Left nav */
#left-nav {
    width: 1fr;
    padding: 1 1;
    overflow-y: auto;
}

.nav-section-label {
    color: #64748b;
    text-style: bold;
    padding: 1 1 0 1;
    height: 2;
}

.app-tile {
    background: #161b22;
    border: solid #21262d;
    color: #c9d1d9;
    height: 4;
    width: 100%;
    margin: 0 0 1 0;
    content-align: left middle;
    padding: 0 2;
    text-style: bold;
}

.app-tile:hover {
    background: #1f2937;
    border: solid #7c3aed;
    color: #ffffff;
}

.app-tile.has-badge {
    border: solid #06b6d4;
}

.sys-tile {
    background: #0d1117;
    border: solid #21262d;
    color: #64748b;
    height: 3;
    width: 100%;
    margin: 0 0 1 0;
    content-align: left middle;
    padding: 0 2;
}

.sys-tile:hover {
    background: #161b22;
    color: #c9d1d9;
    border: solid #30363d;
}

.sys-tile.danger:hover {
    color: #ef4444;
    border: solid #ef4444;
}

/* Right stats panel */
#right-panel {
    width: 30;
    background: #0d1117;
    border-left: solid #21262d;
    padding: 1 2;
    overflow-y: auto;
}

.panel-heading {
    color: #7c3aed;
    text-style: bold;
    padding: 0 0 1 0;
    border-bottom: solid #21262d;
    width: 100%;
}

.stat-row {
    height: 2;
    margin: 1 0 0 0;
    align: left middle;
}

.stat-lbl {
    color: #64748b;
    width: 6;
    text-style: bold;
}

.stat-bar {
    color: #22c55e;
    width: 14;
}

.stat-pct {
    color: #c9d1d9;
    width: 6;
    text-align: right;
}

.info-row {
    height: 2;
    color: #64748b;
    margin: 0 0 0 0;
}

.info-row.highlight {
    color: #c9d1d9;
}

.divider-line {
    border-top: solid #21262d;
    margin: 1 0;
    height: 1;
}

/* ── Shared screen chrome ─────────────────────────── */

.screen-header {
    height: 3;
    background: #161b22;
    border-bottom: solid #7c3aed;
    padding: 0 2;
    align: left middle;
}

.screen-title {
    color: #7c3aed;
    text-style: bold;
    width: 1fr;
    content-align: left middle;
    height: 3;
}

.btn-back {
    background: #21262d;
    border: solid #30363d;
    color: #c9d1d9;
    min-width: 10;
    height: 3;
}

.btn-back:hover {
    background: #30363d;
    border: solid #ef4444;
    color: #ef4444;
}

/* ── Shared button styles ─────────────────────────── */

Button {
    background: #21262d;
    border: solid #30363d;
    color: #c9d1d9;
}

Button:hover {
    background: #30363d;
    border: solid #7c3aed;
    color: #ffffff;
}

Button.primary {
    background: #7c3aed;
    border: solid #9f67ff;
    color: #ffffff;
    text-style: bold;
}

Button.primary:hover {
    background: #9f67ff;
    border: solid #b18aff;
}

Button.success {
    background: #14532d;
    border: solid #22c55e;
    color: #22c55e;
    text-style: bold;
}

Button.success:hover {
    background: #166534;
    color: #4ade80;
}

Button.danger {
    background: #450a0a;
    border: solid #ef4444;
    color: #ef4444;
}

Button.danger:hover {
    background: #7f1d1d;
    color: #fca5a5;
}

/* ── DataTable ────────────────────────────────────── */

DataTable {
    background: #161b22;
    color: #c9d1d9;
}

DataTable > .datatable--header {
    background: #21262d;
    color: #7c3aed;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: #1f2937;
    color: #ffffff;
}

DataTable > .datatable--hover {
    background: #161b22;
}

/* ── ListView ─────────────────────────────────────── */

ListView {
    background: #0d1117;
    border: solid #21262d;
}

ListView > ListItem {
    background: #0d1117;
    color: #c9d1d9;
    height: 3;
    padding: 0 1;
}

ListView > ListItem:hover {
    background: #161b22;
}

ListView > ListItem.--highlight {
    background: #1f2937;
    color: #ffffff;
    border-left: solid #7c3aed;
}

/* ── Input ────────────────────────────────────────── */

Input {
    background: #0d1117;
    border: solid #30363d;
    color: #c9d1d9;
}

Input:focus {
    border: solid #7c3aed;
    background: #161b22;
}

/* ── TextArea ─────────────────────────────────────── */

TextArea {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #21262d;
}

TextArea:focus {
    border: solid #7c3aed;
}

TextArea > .text-area--cursor {
    background: #7c3aed;
    color: #ffffff;
}

TextArea > .text-area--gutter {
    background: #161b22;
    color: #64748b;
}

TextArea > .text-area--cursor-line {
    background: #161b22;
}

/* ── Calculator ───────────────────────────────────── */

#calc-display-area {
    height: 7;
    background: #161b22;
    border: solid #21262d;
    align: right bottom;
    padding: 1 2;
}

#calc-expression {
    color: #64748b;
    text-align: right;
    width: 100%;
    height: 2;
    content-align: right bottom;
}

#calc-result {
    color: #22c55e;
    text-style: bold;
    text-align: right;
    width: 100%;
    height: 3;
    content-align: right bottom;
}

#calc-history {
    height: 7;
    background: #0d1117;
    border: solid #21262d;
    overflow-y: auto;
    padding: 0 2;
}

.calc-history-entry {
    color: #64748b;
    height: 1;
}

#calc-buttons {
    height: 1fr;
    grid-size: 4;
    grid-gutter: 1;
    padding: 1;
    background: #0d1117;
}

.cbtn {
    background: #161b22;
    border: solid #21262d;
    color: #c9d1d9;
    text-style: bold;
    height: 3;
    content-align: center middle;
}

.cbtn:hover { background: #21262d; color: #ffffff; }

.cbtn.op {
    background: #1a1a2e;
    color: #7c3aed;
    border: solid #2d1f4e;
}

.cbtn.op:hover { background: #2d1f3d; color: #9f67ff; }

.cbtn.eq {
    background: #7c3aed;
    color: #ffffff;
    border: solid #9f67ff;
    text-style: bold;
}

.cbtn.eq:hover { background: #9f67ff; }

.cbtn.clr {
    background: #450a0a;
    color: #ef4444;
    border: solid #7f1d1d;
}

.cbtn.clr:hover { background: #7f1d1d; color: #fca5a5; }

.cbtn.fn {
    background: #1a2744;
    color: #06b6d4;
    border: solid #1e3a5f;
}

.cbtn.fn:hover { background: #1e3a5f; color: #22d3ee; }

/* ── Mail ─────────────────────────────────────────── */

#mail-folders {
    width: 20;
    background: #0d1117;
    border-right: solid #21262d;
    padding: 1 0;
}

.folder-btn {
    background: transparent;
    border: none;
    color: #64748b;
    height: 3;
    width: 100%;
    content-align: left middle;
    padding: 0 2;
}

.folder-btn:hover {
    background: #161b22;
    color: #c9d1d9;
    border: none;
}

.folder-btn.active {
    color: #7c3aed;
    background: #1f2937;
    text-style: bold;
    border: none;
    border-left: solid #7c3aed;
}

#mail-list {
    width: 32;
    background: #0d1117;
    border-right: solid #21262d;
}

#mail-view {
    width: 1fr;
    padding: 1 2;
    background: #0d1117;
    overflow-y: auto;
}

.mail-header-field {
    color: #64748b;
    height: 1;
    margin: 0 0 0 0;
}

.mail-header-value {
    color: #c9d1d9;
    text-style: bold;
}

.mail-body {
    color: #c9d1d9;
    margin: 2 0 0 0;
    width: 100%;
}

#mail-actions {
    height: 5;
    border-top: solid #21262d;
    padding: 1;
    background: #161b22;
    align: left middle;
}

/* ── Tasks ────────────────────────────────────────── */

#tasks-table-area {
    height: 1fr;
    border: solid #21262d;
    margin: 0 1 1 1;
}

#task-add-bar {
    height: 6;
    background: #161b22;
    border-top: solid #21262d;
    padding: 1 2;
    align: left middle;
}

#task-add-bar Input {
    margin: 0 1;
}

/* ── Browser ──────────────────────────────────────── */

#browser-url-bar {
    height: 5;
    background: #161b22;
    border-bottom: solid #21262d;
    padding: 1 2;
    align: left middle;
}

#browser-url-bar Input {
    width: 1fr;
    margin: 0 1;
}

#browser-content-area {
    padding: 1 2;
    overflow-y: auto;
    height: 1fr;
}

#browser-status {
    height: 2;
    border-top: solid #21262d;
    background: #161b22;
    padding: 0 2;
    color: #64748b;
    content-align: left middle;
}

/* ── File browser ─────────────────────────────────── */

#file-sidebar {
    width: 28;
    border-right: solid #21262d;
    background: #0d1117;
    padding: 1;
    overflow-y: auto;
}

#file-content {
    width: 1fr;
    padding: 1 2;
    overflow-y: auto;
}

.file-entry {
    color: #c9d1d9;
    height: 2;
    padding: 0 1;
}

.file-entry:hover {
    background: #161b22;
    color: #ffffff;
}

.dir-entry {
    color: #06b6d4;
    text-style: bold;
    height: 2;
    padding: 0 1;
}

.dir-entry:hover {
    background: #161b22;
    color: #22d3ee;
}

/* ── Editor ───────────────────────────────────────── */

#editor-topbar {
    height: 3;
    background: #161b22;
    border-bottom: solid #21262d;
    padding: 0 2;
    align: left middle;
}

#editor-filename {
    color: #06b6d4;
    text-style: bold;
    width: 1fr;
    content-align: left middle;
    height: 3;
}

#editor-area {
    height: 1fr;
    margin: 0;
}

#editor-actions {
    height: 4;
    background: #161b22;
    border-top: solid #21262d;
    padding: 0 2;
    align: left middle;
}

#editor-actions Button {
    margin: 0 1;
}

/* ── Log / scrollable text ────────────────────────── */

Log {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #21262d;
}

/* ── Button sizing (replaces removed min_width= constructor args) ── */

.win-titlebar Button          { min-width: 10; }
.win-titlebar Button.btn-back { min-width: 10; }
#login-btns Button            { min-width: 14; }
#url-bar Button               { min-width: 8;  }
#editor-actions Button        { min-width: 12; }
#task-add-bar Button          { min-width: 10; }
#mail-actions Button          { min-width: 12; }

/* ── Scrollbars ───────────────────────────────────── */

ScrollableContainer > ScrollBar {
    background: #0d1117;
}

ScrollableContainer > ScrollBar > .scrollbar--thumb {
    background: #30363d;
}

ListView > ScrollBar {
    background: #0d1117;
}

/* ── Textual Header / Footer ──────────────────────── */

Header {
    background: #161b22;
    color: #7c3aed;
    text-style: bold;
}

Footer {
    background: #161b22;
    color: #64748b;
}

Footer > .footer--key {
    background: #21262d;
    color: #7c3aed;
}
"""

# ── Helper: stat bar renderer ─────────────────────────────────────────────────

def _render_bar(value: float, width: int = 14) -> str:
    """Render a unicode progress bar for terminal stats."""
    clamped  = max(0.0, min(100.0, value))
    filled   = int(clamped * width / 100)
    empty    = width - filled
    if clamped < 60:
        bar_char = "▓"
    elif clamped < 85:
        bar_char = "▓"
    else:
        bar_char = "▓"
    return bar_char * filled + "░" * empty


# ── Reactive clock widget ─────────────────────────────────────────────────────

class ClockWidget(Static):
    time_str: reactive[str] = reactive("")

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        self.time_str = datetime.now().strftime("%H:%M:%S")

    def render(self) -> str:
        return self.time_str


# ── Stats panel widget ────────────────────────────────────────────────────────

class StatsPanel(Static):
    cpu:  reactive[float] = reactive(0.0)
    ram:  reactive[float] = reactive(0.0)
    disk: reactive[float] = reactive(0.0)

    def on_mount(self) -> None:
        self.set_interval(2, self._refresh)
        self._refresh()

    @work
    async def _refresh(self) -> None:
        # Blocking psutil calls in thread pool; reactive setters run on main loop.
        vals = await asyncio.to_thread(self._collect)
        if vals is None:
            return
        cpu, ram, disk = vals
        # Only trigger reactive watchers when the value actually changed (>0.5%)
        if abs(cpu  - self.cpu)  > 0.5: self.cpu  = cpu
        if abs(ram  - self.ram)  > 0.5: self.ram  = ram
        if abs(disk - self.disk) > 0.5: self.disk = disk

    @staticmethod
    def _collect() -> tuple[float, float, float] | None:
        try:
            import psutil                                    # type: ignore
            cpu  = psutil.cpu_percent(interval=0.5)
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            return cpu, mem.percent, disk.percent
        except ImportError:
            return None

    def render(self) -> str:
        cpu_bar  = _render_bar(self.cpu)
        ram_bar  = _render_bar(self.ram)
        disk_bar = _render_bar(self.disk)
        now      = datetime.now()

        def pct_color(v: float) -> str:
            if v < 60:   return "#22c55e"
            if v < 85:   return "#f59e0b"
            return "#ef4444"

        return (
            f"[bold #7c3aed]SYSTEM VITALS[/]\n"
            f"[#21262d]{'─' * 26}[/]\n"
            f"[#64748b]CPU [/][{pct_color(self.cpu)}]{cpu_bar}[/] [{pct_color(self.cpu)}]{self.cpu:5.1f}%[/]\n"
            f"[#64748b]RAM [/][{pct_color(self.ram)}]{ram_bar}[/] [{pct_color(self.ram)}]{self.ram:5.1f}%[/]\n"
            f"[#64748b]DSK [/][{pct_color(self.disk)}]{disk_bar}[/] [{pct_color(self.disk)}]{self.disk:5.1f}%[/]\n"
            f"[#21262d]{'─' * 26}[/]\n"
            f"[bold #7c3aed]TIME & DATE[/]\n"
            f"[#06b6d4]{now.strftime('%H:%M:%S')}[/]\n"
            f"[#64748b]{now.strftime('%a %d %b %Y')}[/]\n"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SCREENS
# ─────────────────────────────────────────────────────────────────────────────

# ── Login ─────────────────────────────────────────────────────────────────────

class LoginScreen(Screen):
    BINDINGS: ClassVar = [Binding("ctrl+q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Container(id="login-outer"):
            yield Static(LOGO_ART, id="logo-art")
            yield Static("Adaptive Operating System  ·  v2.0.0", id="tagline")
            with Horizontal(classes="login-field-row"):
                yield Label("Username", classes="login-label")
                with Container(classes="login-input"):
                    yield Input(placeholder="your username", id="username-input")
            with Horizontal(id="login-buttons"):
                yield Button("Login", id="btn-login", classes="primary")
                yield Button("New User", id="btn-new")
                yield Button("Guest", id="btn-guest")
            yield Static("", id="login-error")

    def on_mount(self) -> None:
        self.query_one("#username-input", Input).focus()

    @on(Input.Submitted, "#username-input")
    def _on_enter(self) -> None:
        self._do_login()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-guest":
            self.app.user_profile = load_user_profile("guest")
            self.app.push_screen(MainScreen())
        elif bid in ("btn-login", "btn-new"):
            self._do_login()

    def _do_login(self) -> None:
        username = self.query_one("#username-input", Input).value.strip()
        if not username:
            self.query_one("#login-error", Static).update("⚠  Username cannot be empty")
            return
        self.app.user_profile = load_user_profile(username)
        self.query_one("#login-error", Static).update("")
        self.app.push_screen(MainScreen())


# ── Main dashboard ────────────────────────────────────────────────────────────

class MainScreen(Screen):
    BINDINGS: ClassVar = [
        Binding("q",  "app.quit",     "Quit"),
        Binding("F1", "show_help",    "Help"),
        Binding("F3", "do_backup",    "Backup"),
        Binding("l",  "logout",       "Logout"),
    ]

    def compose(self) -> ComposeResult:
        # Top bar
        with Horizontal(id="top-bar"):
            with Horizontal(id="top-bar-left"):
                yield Static("⬡ BradOS", id="top-brand")
                yield Static("", id="top-user")
            with Horizontal(id="top-bar-right"):
                yield ClockWidget(id="clock-widget")

        with Horizontal(id="main-body"):
            # Left: scrollable app list
            with ScrollableContainer(id="left-nav"):
                yield Static("APPLICATIONS", classes="nav-section-label")
                yield Button("🧮  Scientific Calculator",  id="app-calc",    classes="app-tile")
                yield Button("📧  BradMail",               id="app-mail",    classes="app-tile")
                yield Button("🎮  BradGame Center",        id="app-game",    classes="app-tile")
                yield Button("🛒  BradHub",                id="app-hub",     classes="app-tile")
                yield Button("✅  Task Manager",           id="app-tasks",   classes="app-tile")
                yield Button("📁  File Browser",           id="app-files",   classes="app-tile")
                yield Button("✏️   Text Editor",            id="app-editor",  classes="app-tile")
                yield Button("🌐  BradBrowser",            id="app-browser", classes="app-tile")
                yield Static("SYSTEM", classes="nav-section-label")
                yield Button("⚙️   System Info",            id="sys-info",    classes="sys-tile")
                yield Button("📊  Monitor",                id="sys-monitor", classes="sys-tile")
                yield Button("🚪  Logout",                 id="sys-logout",  classes="sys-tile")
                yield Button("🛑  Shutdown BradOS",        id="sys-shutdown",classes="sys-tile danger")

            # Right: live stats panel
            with ScrollableContainer(id="right-panel"):
                yield StatsPanel()
                yield Static("", classes="divider-line")
                yield Static("[bold #7c3aed]QUICK STATS[/]", id="quick-stats-label", classes="panel-heading")
                yield Static("", id="quick-mail-stat",  classes="info-row")
                yield Static("", id="quick-tasks-stat", classes="info-row")

        yield Footer()

    def on_mount(self) -> None:
        profile = self.app.user_profile
        self.query_one("#top-user", Static).update(
            f"[#22c55e]● {profile.get('username','?')}[/]"
        )
        self._refresh_quick_stats()
        self.set_interval(10, self._refresh_quick_stats)

    def _refresh_quick_stats(self) -> None:
        p       = self.app.user_profile
        mail    = p.get("mail_folders", {})
        inbox_n = len(mail.get("inbox", []))
        tasks_n = sum(1 for t in p.get("tasks", []) if not t.get("done"))
        try:
            self.query_one("#quick-mail-stat",  Static).update(
                f"[#06b6d4]📧[/]  [#c9d1d9]{inbox_n}[/] [#64748b]message(s) in inbox[/]"
            )
            self.query_one("#quick-tasks-stat", Static).update(
                f"[#22c55e]✅[/]  [#c9d1d9]{tasks_n}[/] [#64748b]pending task(s)[/]"
            )
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "app-calc":    self.app.push_screen(CalculatorScreen())
            case "app-mail":    self.app.push_screen(MailScreen())
            case "app-game":    self.app.push_screen(GameMenuScreen())
            case "app-hub":     self.app.push_screen(HubScreen())
            case "app-tasks":   self.app.push_screen(TaskScreen())
            case "app-files":   self.app.push_screen(FileBrowserScreen())
            case "app-editor":  self.app.push_screen(EditorScreen())
            case "app-browser": self.app.push_screen(BrowserScreen())
            case "sys-info":    self.app.push_screen(SystemInfoScreen())
            case "sys-monitor": self.app.push_screen(MonitorScreen())
            case "sys-logout":  self.action_logout()
            case "sys-shutdown":self.app.exit()

    def action_logout(self) -> None:
        self.app.user_profile = {}
        self.dismiss()

    def action_do_backup(self) -> None:
        backup_user_profiles()
        self.notify("Backup complete!", severity="information")

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())


# ── Calculator ────────────────────────────────────────────────────────────────

class CalculatorScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    # State
    _expression:  str = ""
    _result_text: str = "0"
    _history:     list[str]

    def __init__(self):
        super().__init__()
        self._history = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("🧮  Scientific Calculator", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Vertical(id="calc-display-area"):
            yield Static("", id="calc-expression")
            yield Static("0", id="calc-result")

        yield ScrollableContainer(Static("", id="calc-history-content"), id="calc-history")

        # Button grid
        _LAYOUT = [
            ("C",   "clr"), ("±",   "op"),  ("π",   "fn"),  ("÷",   "op"),
            ("7",   ""),    ("8",   ""),     ("9",   ""),     ("×",   "op"),
            ("4",   ""),    ("5",   ""),     ("6",   ""),     ("−",   "op"),
            ("1",   ""),    ("2",   ""),     ("3",   ""),     ("+",   "op"),
            ("sin", "fn"),  ("cos", "fn"),   ("√",   "fn"),   ("=",   "eq"),
            ("0",   ""),    (".",   ""),     ("⌫",   "clr"),  ("^",   "op"),
        ]
        with Container(id="calc-buttons"):
            for label, cls in _LAYOUT:
                yield Button(label, id=f"c-{label}", classes=f"cbtn {cls}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(); return
        label = event.button.label.plain.strip()
        self._handle_key(label)

    def on_key(self, event) -> None:
        ch = event.character
        if ch and ch in "0123456789.+-*/^()":
            self._handle_key(ch)
        elif event.key == "enter":
            self._handle_key("=")
        elif event.key == "backspace":
            self._handle_key("⌫")

    def _handle_key(self, label: str) -> None:
        if label == "C":
            self._expression = ""
            self._result_text = "0"
        elif label == "⌫":
            self._expression = self._expression[:-1]
        elif label == "=":
            self._calculate()
            return
        elif label == "±":
            if self._expression:
                self._expression = f"-({self._expression})"
        elif label == "π":
            self._expression += str(math.pi)
        elif label == "√":
            self._expression = f"sqrt({self._expression})"
        elif label == "sin":
            self._expression = f"sin({self._expression})"
        elif label == "cos":
            self._expression = f"cos({self._expression})"
        elif label == "×":
            self._expression += "*"
        elif label == "÷":
            self._expression += "/"
        elif label == "−":
            self._expression += "-"
        elif label == "^":
            self._expression += "**"
        else:
            self._expression += label
        self._refresh_display()

    def _calculate(self) -> None:
        expr = self._expression.strip()
        if not expr:
            return
        try:
            sanitised = (expr
                .replace("pi", str(math.pi))
                .replace("e", str(math.e)))
            result = safe_eval(sanitised)
            if isinstance(result, float) and result.is_integer():
                result_str = str(int(result))
            else:
                result_str = f"{result:.8g}"
            entry = f"{expr} = {result_str}"
            self._history.append(entry)
            if len(self._history) > 20:
                self._history.pop(0)
            self._expression  = result_str
            self._result_text = result_str
        except Exception as ex:
            self._result_text = f"Error: {ex}"
            self._expression  = ""
        self._refresh_display()
        self._refresh_history()

    def _refresh_display(self) -> None:
        try:
            self.query_one("#calc-expression", Static).update(
                f"[#64748b]{self._expression or ' '}[/]"
            )
            self.query_one("#calc-result", Static).update(
                f"[bold #22c55e]{self._result_text}[/]"
            )
        except NoMatches:
            pass

    def _refresh_history(self) -> None:
        try:
            history_text = "\n".join(
                f"[#64748b]{h}[/]" for h in reversed(self._history[-8:])
            ) or "[#21262d]No calculations yet[/]"
            self.query_one("#calc-history-content", Static).update(history_text)
        except NoMatches:
            pass


# ── Mail ──────────────────────────────────────────────────────────────────────

class MailScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    _active_folder:  str  = "inbox"
    _selected_index: int  = -1

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("📧  BradMail", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Horizontal():
            # Folder sidebar
            with Vertical(id="mail-folders"):
                yield Button("📥  Inbox",   id="folder-inbox",   classes="folder-btn active")
                yield Button("📤  Sent",    id="folder-sent",    classes="folder-btn")
                yield Button("📝  Drafts",  id="folder-drafts",  classes="folder-btn")
                yield Button("🗑️   Trash",   id="folder-trash",   classes="folder-btn")
                yield Static("")
                yield Button("✉️  Compose",  id="btn-compose",    classes="primary")

            # Message list
            with Vertical(id="mail-list"):
                yield DataTable(id="msg-table", cursor_type="row")

            # Message view
            with ScrollableContainer(id="mail-view"):
                yield Static("", id="mail-view-content")

        with Horizontal(id="mail-actions"):
            yield Button("↩ Reply",   id="btn-reply",  classes="success")
            yield Button("↗ Forward", id="btn-forward")
            yield Button("⭐ Star",    id="btn-star")
            yield Button("🗑 Delete",  id="btn-delete", classes="danger")

    def on_mount(self) -> None:
        table = self.query_one("#msg-table", DataTable)
        table.add_columns("", "From/To", "Subject", "Date")
        self._load_folder("inbox")

    def _load_folder(self, folder: str) -> None:
        self._active_folder  = folder
        self._selected_index = -1
        table = self.query_one("#msg-table", DataTable)
        table.clear()

        msgs  = self._get_msgs()
        prio_field = "from" if folder == "inbox" else "to"
        for msg in msgs:
            star    = "⭐" if msg.get("starred") else "  "
            sender  = msg.get(prio_field, "?")[:16]
            subject = msg.get("subject", "")[:28]
            date    = msg.get("date", "")[:10]
            table.add_row(star, sender, subject, date)

        self.query_one("#mail-view-content", Static).update(
            "[#64748b]Select a message to read it.[/]"
        )

        # Update folder button styles
        folder_ids = ["inbox", "sent", "drafts", "trash"]
        for fid in folder_ids:
            try:
                btn = self.query_one(f"#folder-{fid}", Button)
                if fid == folder:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
            except NoMatches:
                pass

    def _get_msgs(self) -> list[dict]:
        return self.app.user_profile.get("mail_folders", {}).get(self._active_folder, [])

    @on(DataTable.RowHighlighted, "#msg-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx  = event.cursor_row
        msgs = self._get_msgs()
        if 0 <= idx < len(msgs):
            self._selected_index = idx
            msg = msgs[idx]
            content = (
                f"[bold #7c3aed]From:[/]    [#c9d1d9]{msg.get('from', '?')}[/]\n"
                f"[bold #7c3aed]To:[/]      [#c9d1d9]{msg.get('to',   '?')}[/]\n"
                f"[bold #7c3aed]Subject:[/] [#c9d1d9]{msg.get('subject', '')}[/]\n"
                f"[bold #7c3aed]Date:[/]    [#64748b]{msg.get('date', '')}[/]\n"
                f"[#21262d]{'─' * 50}[/]\n\n"
                f"[#c9d1d9]{msg.get('body', '')}[/]"
            )
            self.query_one("#mail-view-content", Static).update(content)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-back":
            self.dismiss(); return
        if bid == "btn-compose":
            self.app.push_screen(ComposeScreen()); return
        folder_map = {
            "folder-inbox":  "inbox",
            "folder-sent":   "sent",
            "folder-drafts": "drafts",
            "folder-trash":  "trash",
        }
        if bid in folder_map:
            self._load_folder(folder_map[bid]); return
        if bid in ("btn-reply", "btn-forward", "btn-star", "btn-delete"):
            msgs = self._get_msgs()
            if self._selected_index < 0 or self._selected_index >= len(msgs):
                self.notify("Select a message first.", severity="warning"); return
            msg = msgs[self._selected_index]
            if bid == "btn-star":
                msg["starred"] = not msg.get("starred", False)
                save_user_profile(self.app.user_profile)
                self._load_folder(self._active_folder)
            elif bid == "btn-delete":
                self.app.user_profile["mail_folders"][self._active_folder].pop(
                    self._selected_index)
                save_user_profile(self.app.user_profile)
                self._load_folder(self._active_folder)
                self.notify("Message deleted.", severity="information")
            elif bid in ("btn-reply", "btn-forward"):
                prefix = "Re:" if bid == "btn-reply" else "Fwd:"
                self.app.push_screen(ComposeScreen(
                    to=msg.get("from",""),
                    subject=f"{prefix} {msg.get('subject','')}",
                    body=f"\n\n--- Original ---\n{msg.get('body','')}",
                ))


class ComposeScreen(ModalScreen):
    def __init__(self, to: str = "", subject: str = "", body: str = ""):
        super().__init__()
        self._to      = to
        self._subject = subject
        self._body    = body

    def compose(self) -> ComposeResult:
        with Container(id="login-outer"):   # reuse the centered box style
            yield Static("✉️  Compose Message", id="logo-art")
            with Horizontal(classes="login-field-row"):
                yield Label("To:", classes="login-label")
                with Container(classes="login-input"):
                    yield Input(self._to,      id="compose-to",      placeholder="recipient username")
            with Horizontal(classes="login-field-row"):
                yield Label("Subject:", classes="login-label")
                with Container(classes="login-input"):
                    yield Input(self._subject, id="compose-subject",  placeholder="subject line")
            yield TextArea(self._body, id="compose-body", language="markdown")
            with Horizontal(id="login-buttons"):
                yield Button("Send",   id="btn-send",   classes="primary")
                yield Button("Cancel", id="btn-cancel", classes="danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(); return
        to      = self.query_one("#compose-to",      Input).value.strip()
        subject = self.query_one("#compose-subject", Input).value.strip()
        body    = self.query_one("#compose-body",    TextArea).text
        if not to:
            self.notify("Recipient is required.", severity="error"); return
        msg = {
            "from":    self.app.user_profile["username"],
            "to":      to,
            "subject": subject,
            "body":    body,
            "date":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "starred": False,
        }
        self.app.user_profile["mail_folders"]["sent"].append(msg)
        if to.lower() == self.app.user_profile["username"].lower():
            self.app.user_profile["mail_folders"]["inbox"].append(msg)
        else:
            other_path = get_profile_path(to)
            if os.path.exists(other_path):
                from brados_system import load_user_profile as lup
                other = lup(to)
                other.setdefault("mail_folders", {}).setdefault("inbox", []).append(msg)
                save_user_profile(other)
        save_user_profile(self.app.user_profile)
        self.notify(f"Sent to {to}!", severity="information")
        self.dismiss()


# ── Task Manager ──────────────────────────────────────────────────────────────

class TaskScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("✅  Task Manager", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Container(id="tasks-table-area"):
            yield DataTable(id="task-table", cursor_type="row")

        with Horizontal(id="task-add-bar"):
            yield Input(placeholder="New task name…",     id="task-name",  )
            yield Input(placeholder="Priority: h/m/l",   id="task-prio",  )
            yield Input(placeholder="Due: YYYY-MM-DD",   id="task-due",   )
            yield Button("➕ Add",            id="btn-add",     classes="success")
            yield Button("✓ Toggle",          id="btn-toggle")
            yield Button("🗑 Delete",          id="btn-delete",  classes="danger")

    def on_mount(self) -> None:
        t = self.query_one("#task-table", DataTable)
        t.add_columns("", "Priority", "Task", "Due", "Created")
        self._reload()

    def _reload(self) -> None:
        t = self.query_one("#task-table", DataTable)
        t.clear()
        prio_map = {"high": "[bold #ef4444]HIGH [/]",
                    "medium": "[bold #f59e0b]MED  [/]",
                    "low":    "[bold #22c55e]LOW  [/]"}
        for task in self.app.user_profile.get("tasks", []):
            status  = "✅" if task.get("done") else "⏳"
            prio    = prio_map.get(task.get("priority","medium"), "MED")
            name    = task.get("name", "")[:40]
            due     = task.get("due") or "—"
            created = task.get("created","")[:10]
            t.add_row(status, prio, name, due, created)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(); return
        if event.button.id == "btn-add":
            name = self.query_one("#task-name", Input).value.strip()
            if not name:
                self.notify("Task name required.", severity="warning"); return
            prio_raw = self.query_one("#task-prio", Input).value.strip().lower()
            prio     = {"h": "high", "m": "medium", "l": "low"}.get(prio_raw, "medium")
            due      = self.query_one("#task-due", Input).value.strip() or None
            self.app.user_profile.setdefault("tasks", []).append({
                "name": name, "done": False, "priority": prio,
                "due": due, "created": datetime.now().isoformat(),
            })
            save_user_profile(self.app.user_profile)
            for inp in ("#task-name", "#task-prio", "#task-due"):
                self.query_one(inp, Input).value = ""
            self._reload()
            self.notify("Task added!", severity="information")
            return
        table = self.query_one("#task-table", DataTable)
        row   = table.cursor_row
        tasks = self.app.user_profile.get("tasks", [])
        if not (0 <= row < len(tasks)):
            self.notify("Select a task first.", severity="warning"); return
        if event.button.id == "btn-toggle":
            tasks[row]["done"] ^= True
            save_user_profile(self.app.user_profile)
            self._reload()
        elif event.button.id == "btn-delete":
            del tasks[row]
            save_user_profile(self.app.user_profile)
            self._reload()
            self.notify("Task deleted.", severity="information")


# ── Browser ───────────────────────────────────────────────────────────────────

class BrowserScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    _is_web: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("🌐  BradBrowser", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Horizontal(id="browser-url-bar"):
            yield Button("←", id="btn-local")
            yield Button("🌐", id="btn-web")
            yield Input(placeholder="Enter URL or local page name…", id="url-input")
            yield Button("Go ▶", id="btn-go", classes="primary")

        with ScrollableContainer(id="browser-content-area"):
            yield Static("[#64748b]Enter a URL above and press Go.[/]",
                         id="browser-content")

        yield Static("Ready", id="browser-status")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-back":  self.dismiss(); return
        if bid == "btn-local": self._is_web = False; self.notify("Local mode",  severity="information"); return
        if bid == "btn-web":   self._is_web = True;  self.notify("Web mode",    severity="information"); return
        if bid == "btn-go":    self._fetch()

    @on(Input.Submitted, "#url-input")
    def _on_enter(self) -> None:
        self._fetch()

    @work(exclusive=True)           # auto-cancels any in-flight fetch
    async def _fetch(self) -> None:
        url = self.query_one("#url-input", Input).value.strip()
        if not url:
            return
        try:
            self.query_one("#browser-status", Static).update(
                f"[#f59e0b]⟳  {url}[/]"
            )
        except NoMatches:
            return

        # All blocking I/O runs in thread pool; widget updates happen after await.
        text, status = await asyncio.to_thread(self._do_fetch, url)
        escaped = text[:10_000].replace("[", "\\[")
        try:
            self.query_one("#browser-content", Static).update(escaped)
            self.query_one("#browser-status",  Static).update(status)
        except NoMatches:
            pass

    def _do_fetch(self, url: str) -> tuple[str, str]:
        """Blocking – runs in thread pool."""
        is_web = self._is_web or url.startswith(("http://", "https://"))
        if is_web:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                import requests                              # type: ignore
                resp = requests.get(url, timeout=10,
                                    headers={"User-Agent": "BradOS/2.0"})
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                return (html_to_text(resp.text) if "html" in ct
                        else f"[Binary content: {ct}]",
                        f"[#22c55e]✓  {resp.status_code}  {url}[/]")
            except ImportError:
                return ("requests not installed.\nRun: pip install requests",
                        "[#ef4444]Error: requests missing[/]")
            except Exception as e:
                return f"Error: {e}", f"[#ef4444]✗  {e}[/]"
        else:
            pages_dir = os.path.join(BRADOS_BROWSER_DIR, "pages")
            os.makedirs(pages_dir, exist_ok=True)
            page_file = os.path.join(pages_dir,
                                     url if url.endswith(".html") else url + ".html")
            if os.path.exists(page_file):
                with open(page_file) as f:
                    return html_to_text(f.read()), f"[#22c55e]✓  local:{url}[/]"
            return (f"Local page '{url}' not found.\nTip: switch to Web mode.",
                    f"[#ef4444]✗  not found[/]")


# ── File Browser ──────────────────────────────────────────────────────────────

class FileBrowserScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    _current_dir: str = BRADOS_FILES_DIR

    def compose(self) -> ComposeResult:
        init_dirs()
        with Horizontal(classes="screen-header"):
            yield Static("📁  File Browser", classes="screen-title", id="file-header-title")
            yield Button("⬆ Up", id="btn-up")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Horizontal():
            with ScrollableContainer(id="file-sidebar"):
                yield ListView(id="file-list")
            with ScrollableContainer(id="file-content"):
                yield Static(
                    "[#64748b]Select a file or directory.[/]",
                    id="file-preview"
                )

    def on_mount(self) -> None:
        self._current_dir = BRADOS_FILES_DIR
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.query_one("#file-header-title", Static).update(
                f"[bold #7c3aed]📁[/]  [#c9d1d9]{self._current_dir}[/]"
            )
            lv = self.query_one("#file-list", ListView)
            lv.clear()
            entries = sorted(os.listdir(self._current_dir))
            dirs    = [e for e in entries if os.path.isdir(os.path.join(self._current_dir, e))]
            files   = [e for e in entries if os.path.isfile(os.path.join(self._current_dir, e))]
            for d in dirs:
                lv.append(ListItem(Static(f"[#06b6d4]📂 {d}/[/]"), id=f"d:{d}"))
            for f in files:
                size = os.path.getsize(os.path.join(self._current_dir, f))
                lv.append(ListItem(Static(f"[#c9d1d9]📄 {f}[/]  [#64748b]{size:,} B[/]"), id=f"f:{f}"))
            if not entries:
                lv.append(ListItem(Static("[#64748b](empty directory)[/]")))
        except OSError as e:
            self.notify(str(e), severity="error")

    @on(ListView.Selected, "#file-list")
    def on_file_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        kind, name = event.item.id.split(":", 1)
        path = os.path.join(self._current_dir, name)
        if kind == "d":
            self._current_dir = path
            self._refresh()
        else:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read(8192)
                escaped = content.replace("[", "\\[")
                preview = (
                    f"[bold #7c3aed]{name}[/]  [#64748b]({os.path.getsize(path):,} bytes)[/]\n"
                    f"[#21262d]{'─' * 40}[/]\n"
                    f"[#c9d1d9]{escaped[:3000]}[/]"
                )
                if len(content) > 3000:
                    preview += f"\n[#64748b]… {len(content) - 3000} more chars[/]"
                self.query_one("#file-preview", Static).update(preview)
            except Exception as e:
                self.query_one("#file-preview", Static).update(
                    f"[#ef4444]Cannot preview: {e}[/]"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss()
        elif event.button.id == "btn-up":
            parent = os.path.dirname(os.path.abspath(self._current_dir))
            if os.path.abspath(self._current_dir) != os.path.abspath(BRADOS_FILES_DIR):
                self._current_dir = parent
                self._refresh()


# ── Text Editor ───────────────────────────────────────────────────────────────

class EditorScreen(Screen):
    BINDINGS: ClassVar = [
        Binding("ctrl+s", "save",    "Save"),
        Binding("escape", "dismiss", "Back"),
    ]
    _filepath: str | None = None
    _dirty:    bool       = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="editor-topbar"):
            yield Static("✏️   Text Editor — no file open", id="editor-filename")
            yield Button("📂 Open", id="btn-open")
            yield Button("📄 New",  id="btn-new")

        yield TextArea("", id="editor-area", language="python", show_line_numbers=True)

        with Horizontal(id="editor-actions"):
            yield Button("💾 Save",      id="btn-save",    classes="primary")
            yield Button("💾 Save As",   id="btn-saveas")
            yield Button("✕ Close file", id="btn-close",   classes="danger")
            yield Button("↩ Back",       id="btn-back",    classes="btn-back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-back":
            self.dismiss(); return
        if bid == "btn-new":
            self.app.push_screen(FilenameModal(callback=self._create_new)); return
        if bid == "btn-open":
            self.app.push_screen(FilenameModal(callback=self._open_file)); return
        if bid == "btn-save":
            self._save(); return
        if bid == "btn-saveas":
            self.app.push_screen(FilenameModal(callback=self._save_as)); return
        if bid == "btn-close":
            self._filepath = None
            self._dirty    = False
            self.query_one("#editor-area", TextArea).load_text("")
            self.query_one("#editor-filename", Static).update(
                "✏️   Text Editor — no file open"
            )

    def _create_new(self, name: str) -> None:
        if not name:
            return
        init_dirs()
        self._filepath = os.path.join(BRADOS_FILES_DIR, name)
        self.query_one("#editor-area", TextArea).load_text("")
        self.query_one("#editor-filename", Static).update(
            f"[bold #06b6d4]{name}[/]  [#64748b](new)[/]"
        )

    def _open_file(self, name: str) -> None:
        if not name:
            return
        path = os.path.join(BRADOS_FILES_DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self._filepath = path
            lang = "python" if name.endswith(".py") else "markdown"
            self.query_one("#editor-area", TextArea).load_text(content)
            try:
                self.query_one("#editor-area", TextArea).language = lang
            except Exception:
                pass
            self.query_one("#editor-filename", Static).update(
                f"[bold #06b6d4]{name}[/]"
            )
        else:
            self.notify(f"'{name}' not found in {BRADOS_FILES_DIR}", severity="error")

    def _save(self) -> None:
        if not self._filepath:
            self.notify("No file open — use Save As.", severity="warning"); return
        text = self.query_one("#editor-area", TextArea).text
        with open(self._filepath, "w", encoding="utf-8") as f:
            f.write(text)
        self._dirty = False
        self.notify("Saved!", severity="information")

    def _save_as(self, name: str) -> None:
        if not name:
            return
        init_dirs()
        self._filepath = os.path.join(BRADOS_FILES_DIR, name)
        self._save()
        self.query_one("#editor-filename", Static).update(
            f"[bold #06b6d4]{name}[/]"
        )

    def action_save(self) -> None:
        self._save()


class FilenameModal(ModalScreen):
    """Generic single-input modal for getting a filename."""
    def __init__(self, callback, prompt: str = "Filename:"):
        super().__init__()
        self._callback = callback
        self._prompt   = prompt

    def compose(self) -> ComposeResult:
        with Container(id="login-outer"):
            yield Static(self._prompt, id="tagline")
            yield Input(placeholder="filename.txt", id="filename-input")
            with Horizontal(id="login-buttons"):
                yield Button("OK",     id="btn-ok",     classes="primary")
                yield Button("Cancel", id="btn-cancel", classes="danger")

    def on_mount(self) -> None:
        self.query_one("#filename-input", Input).focus()

    @on(Input.Submitted)
    def _on_enter(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            self._submit()
        else:
            self.dismiss()

    def _submit(self) -> None:
        val = self.query_one("#filename-input", Input).value.strip()
        self.dismiss()
        self._callback(val)


# ── Game menu (TUI games need full terminal; show instructions) ───────────────

class GameMenuScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("🎮  BradGame Center", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")
        yield Static(
            "\n\n"
            "  [bold #7c3aed]BradGame Center[/]\n\n"
            "  [#64748b]Games (Snake, Tic-Tac-Toe, Hangman, Number Guessing)[/]\n"
            "  [#64748b]require a real terminal and are available in Classic Mode.[/]\n\n"
            "  [#c9d1d9]To play:[/]\n"
            "  [#06b6d4]  1.[/] Exit the GUI  [bold](Q)[/]\n"
            "  [#06b6d4]  2.[/] Run [bold]python brados.py[/] without --gui\n"
            "  [#06b6d4]  3.[/] Select [bold]Classic Mode → BradGame Center[/]\n\n"
            "  [#64748b]Why? Snake uses raw blocking input() which can't co-exist\n"
            "  with Textual's async event loop.[/]",
            id="logo-art",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back": self.dismiss()


# ── BradHub ───────────────────────────────────────────────────────────────────

class HubScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    _CATALOG = {
        "Voice Assistant": "Simulated voice commands",
        "Photo Viewer":    "ASCII image rendering",
        "Music Player":    "Audio file playback (headless)",
        "Note Pad":        "Quick sticky notes",
    }

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("🛒  BradHub App Store", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        with Horizontal():
            with Vertical(id="file-sidebar"):
                yield Static("[bold #7c3aed]Available[/]", classes="panel-heading")
                yield DataTable(id="catalog-table", cursor_type="row")

            with Vertical(id="file-content"):
                yield Static("[bold #7c3aed]Installed[/]", classes="panel-heading")
                yield DataTable(id="installed-table", cursor_type="row")
                with Horizontal(id="editor-actions"):
                    yield Button("📦 Install",   id="btn-install",   classes="success")
                    yield Button("🗑 Uninstall",  id="btn-uninstall", classes="danger")

    def on_mount(self) -> None:
        ct = self.query_one("#catalog-table",   DataTable)
        it = self.query_one("#installed-table", DataTable)
        ct.add_columns("App", "Description")
        it.add_columns("App")
        self._reload()

    def _reload(self) -> None:
        installed = self.app.user_profile.get("installed_apps", [])
        ct = self.query_one("#catalog-table",   DataTable)
        it = self.query_one("#installed-table", DataTable)
        ct.clear(); it.clear()
        for name, desc in self._CATALOG.items():
            if name not in installed:
                ct.add_row(name, desc)
        for name in installed:
            it.add_row(name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back":
            self.dismiss(); return
        installed = self.app.user_profile.setdefault("installed_apps", [])
        if event.button.id == "btn-install":
            row = self.query_one("#catalog-table", DataTable).cursor_row
            avail = [n for n in self._CATALOG if n not in installed]
            if 0 <= row < len(avail):
                installed.append(avail[row])
                save_user_profile(self.app.user_profile)
                self._reload()
                self.notify(f"{avail[row]} installed!", severity="information")
        elif event.button.id == "btn-uninstall":
            row = self.query_one("#installed-table", DataTable).cursor_row
            if 0 <= row < len(installed):
                name = installed.pop(row)
                save_user_profile(self.app.user_profile)
                self._reload()
                self.notify(f"{name} uninstalled.", severity="information")


# ── System Info ───────────────────────────────────────────────────────────────

class SystemInfoScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        import platform, socket
        with Horizontal(classes="screen-header"):
            yield Static("⚙️   System Information", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        rows = [
            ("BradOS",       "v2.0.0"),
            ("Python",       ".".join(map(str, __import__("sys").version_info[:3]))),
            ("OS",           f"{platform.system()} {platform.release()}"),
            ("Architecture", platform.machine()),
            ("Hostname",     platform.node()),
            ("Processor",    platform.processor() or "unknown"),
        ]
        try:
            rows.append(("Local IP", socket.gethostbyname(socket.gethostname())))
        except Exception:
            rows.append(("Local IP", "unavailable"))

        table_markup = "\n".join(
            f"  [bold #7c3aed]{lbl:<18}[/] [#c9d1d9]{val}[/]"
            for lbl, val in rows
        )
        yield Static(f"\n{table_markup}", id="logo-art")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back": self.dismiss()


# ── System Monitor ────────────────────────────────────────────────────────────

class MonitorScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("📊  System Monitor", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        yield StatsPanel(id="monitor-stats")
        yield Static("", id="monitor-extra")

    def on_mount(self) -> None:
        self.set_interval(2, self._refresh_extra)

    @work
    async def _refresh_extra(self) -> None:
        extra = await asyncio.to_thread(self._collect_extra)
        try:
            self.query_one("#monitor-extra", Static).update(extra)
        except NoMatches:
            pass

    @staticmethod
    def _collect_extra() -> str:
        try:
            import psutil                                    # type: ignore
            procs  = len(psutil.pids())
            net    = psutil.net_io_counters()
            uptime = time.time() - psutil.boot_time()
            h, rem = divmod(int(uptime), 3600)
            m, s   = divmod(rem, 60)
            return (
                f"[bold #7c3aed]NETWORK[/]\n"
                f"[#64748b]Sent[/]     [#c9d1d9]{net.bytes_sent // 1024:,} KB[/]\n"
                f"[#64748b]Received[/] [#c9d1d9]{net.bytes_recv // 1024:,} KB[/]\n"
                f"\n[bold #7c3aed]SYSTEM[/]\n"
                f"[#64748b]Processes[/] [#c9d1d9]{procs}[/]\n"
                f"[#64748b]Uptime[/]    [#c9d1d9]{h}h {m}m {s}s[/]\n"
            )
        except (ImportError, PermissionError, OSError):
            return "[#f59e0b]psutil unavailable[/]"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back": self.dismiss()


# ── Help ──────────────────────────────────────────────────────────────────────

class HelpScreen(Screen):
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Back")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-header"):
            yield Static("❓  Help", classes="screen-title")
            yield Button("✕ Back", classes="btn-back", id="btn-back")

        yield Static("""
  [bold #7c3aed]NAVIGATION[/]
  [#64748b]───────────────────────────────────────────[/]
  [#c9d1d9]Click app tiles on the main menu to open an app.[/]
  [#c9d1d9]Press  [bold]ESC[/]  or click  [bold]✕ Back[/]  to return.[/]
  [#c9d1d9]Press  [bold]Q[/]  on the main menu to quit BradOS.[/]
  [#c9d1d9]Press  [bold]F3[/]  to back up user profiles.[/]
  [#c9d1d9]Press  [bold]L[/]  to log out.[/]

  [bold #7c3aed]APPS[/]
  [#64748b]───────────────────────────────────────────[/]
  [#06b6d4]Calculator [/] [#c9d1d9]Click buttons or type expressions.  [bold]Enter[/] = evaluate.[/]
  [#06b6d4]BradMail   [/] [#c9d1d9]Click folders → messages → actions.[/]
  [#06b6d4]Tasks      [/] [#c9d1d9]Fill in the bottom bar and click Add. Toggle/Delete selected rows.[/]
  [#06b6d4]Browser    [/] [#c9d1d9]Toggle 🌐/← for web vs local.  Enter URL and press Go.[/]
  [#06b6d4]Files      [/] [#c9d1d9]Click directories to navigate.  Click files to preview.[/]
  [#06b6d4]Editor     [/] [#c9d1d9]Open or create files.  [bold]Ctrl+S[/] saves.  Python syntax highlight.[/]
  [#06b6d4]BradHub    [/] [#c9d1d9]Select an app and click Install/Uninstall.[/]

  [bold #7c3aed]TIPS[/]
  [#64748b]───────────────────────────────────────────[/]
  [#c9d1d9]Profiles save automatically after every change.[/]
  [#c9d1d9]pip install psutil   → live CPU/RAM/disk metrics in the stats panel.[/]
  [#c9d1d9]pip install requests → real web browsing in BradBrowser.[/]
  [#c9d1d9]Games are in Classic Mode (run without --gui).[/]
  [#c9d1d9]Kernel Mode (experimental multitasking) is also in Classic Mode.[/]
""", id="logo-art")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back": self.dismiss()


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

class BradOSApp(App):
    TITLE   = "BradOS v2.0"
    CSS     = APP_CSS
    BINDINGS: ClassVar = [Binding("ctrl+q", "quit", "Quit")]

    user_profile: dict = {}

    def on_mount(self) -> None:
        init_dirs()
        self.push_screen(LoginScreen())


def run_gui() -> None:
    """Entry point called from brados.py when --gui is passed."""
    BradOSApp().run()

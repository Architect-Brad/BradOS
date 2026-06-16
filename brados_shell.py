# brados_shell.py — BradOS Desktop Shell v3.0
#
# 14 apps. Animated splash. Fade-in windows. Minimize/restore. Live taskbar.
# Keyboard shortcuts for everything. Ocean Dark theme (navy + cyan + coral).
# No other terminal OS project has a desktop environment. This one does — and
# it runs in any terminal with zero native dependencies.

from __future__ import annotations

import asyncio
import re
import os
import re
import subprocess
import sys
import math
import time
import json
import shutil
import threading
import platform
import random
import string
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    ListItem, ListView, Log, RichLog, Static, Switch,
    TabbedContent, TabPane, TextArea,
)
from textual.containers import Container, Grid, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.binding import Binding
from textual import on, work
from textual.events import Click, Key
from textual.css.query import NoMatches
from textual.message import Message

from rich.markdown import Markdown
from rich.style import Style

from brados_system import (
    load_user_profile, save_user_profile, get_profile_path,
    atomic_write_json, USER_PROFILES_DIR, BRADOS_FILES_DIR,
)
from brados_apps import safe_eval, html_to_text, init_dirs
from brados_vfs import create_default_vfs, VirtualFileSystem
from brados_drivers import create_default_registry, DriverRegistry, NetworkDriver
from brados_security import BradSec, Cap, get_bradsec, get_bradsec_daemon, BRADSEC_SOCKET_PATH
from brados_bpkg import BpkgManager, get_bpkg
from brados_mail_server import get_mail_server
from brados_mesh import get_mesh, MeshNode, Peer

try:
    import jedi
    _HAS_JEDI = True
except ImportError:
    _HAS_JEDI = False

# ── Ocean Dark theme ──────────────────────────────────────────────────────────
#
#  Background stack:  #060d17  →  #0d1b2a  →  #1a2740  →  #243450
#  Accent (cyan):     #00d4ff
#  Danger (coral):    #ff4757
#  Success (mint):    #2ed573
#  Warning (amber):   #ffa502
#  Text:              #ecf0f1
#  Muted:             #7f8c8d
#  Border:            #1e3a5f

SHELL_CSS = """
/* ═══════════════════════════════════════════
   BradOS Shell v3.0  ·  Ocean Dark Theme
   "Not purple. An actual desktop."
═══════════════════════════════════════════ */

Screen {
    background: #0d1b2a;
    color: #ecf0f1;
}

/* ── Login ──────────────────────────────── */

LoginScreen { align: center middle; }

#login-box {
    width: 62;
    height: auto;
    background: #1a2740;
    border: double #00d4ff;
    padding: 2 4;
}

#login-logo {
    color: #00d4ff;
    text-style: bold;
    text-align: center;
    width: 100%;
    padding: 0 0 1 0;
}

#login-sub {
    color: #7f8c8d;
    text-align: center;
    width: 100%;
    padding: 0 0 2 0;
}

.lfield {
    height: 3;
    margin: 0 0 1 0;
    align: left middle;
}

.llabel {
    width: 12;
    color: #7f8c8d;
    text-style: bold;
    content-align: left middle;
    height: 3;
}

.linput Input {
    background: #060d17;
    border: round #1e3a5f;
    color: #ecf0f1;
    width: 1fr;
}

.linput Input:focus {
    border: round #00d4ff;
    background: #0d1b2a;
}

#login-btns {
    height: auto;
    margin: 1 0 0 0;
    align: center middle;
}

#login-btns Button { margin: 0 1; min-width: 14; }

#login-err {
    color: #ff4757;
    text-align: center;
    width: 100%;
    height: 1;
    margin: 1 0 0 0;
}

/* ── Desktop ────────────────────────────── */

#top-bar {
    height: 1;
    background: #060d17;
    color: #00d4ff;
    text-style: bold;
    padding: 0 1;
    align: left middle;
    border-bottom: solid #1e3a5f;
}

#top-brand { color: #00d4ff; text-style: bold; width: auto; }
#top-spacer { width: 1fr; }
#top-clock  { color: #ecf0f1; width: auto; padding: 0 1; }
#top-user   { color: #2ed573; text-style: bold; width: auto; padding: 0 1; }

#desktop-area {
    height: 1fr;
    background: #0d1b2a;
    padding: 2 4;
    align: center top;
}

#icon-grid {
    width: 100%;
    height: auto;
}

.icon-row {
    width: 100%;
    height: 7;
    margin: 0 0 1 0;
}

AppIconWidget {
    width: 1fr;
    height: 7;
    border: round #1e3a5f;
    background: #1a2740;
    content-align: center middle;
    text-align: center;
    padding: 0 1;
}

AppIconWidget:hover {
    background: #243450;
    border: round #00d4ff;
}

AppIconWidget.running {
    border: round #2ed573;
}

#desktop-hint {
    color: #1e3a5f;
    text-align: center;
    width: 100%;
    margin: 2 0 0 0;
}

/* ── Taskbar ────────────────────────────── */

#taskbar {
    height: 3;
    background: #060d17;
    border-top: solid #1e3a5f;
    padding: 0 1;
    align: left middle;
}

#taskbar-apps { width: 1fr; height: 3; align: left middle; }
#taskbar-tray { width: auto; height: 3; align: right middle; padding: 0 1; }

.task-btn {
    background: #1a2740;
    border: round #1e3a5f;
    color: #ecf0f1;
    min-width: 16;
    height: 3;
    margin: 0 1 0 0;
    content-align: left middle;
    padding: 0 1;
}

.task-btn:hover {
    background: #243450;
    border: round #00d4ff;
}

.task-btn.active {
    border: round #00d4ff;
    color: #00d4ff;
    text-style: bold;
}

#tray-clock { color: #00d4ff; text-style: bold; width: auto; }
#tray-stats { color: #7f8c8d; width: auto; padding: 0 0 0 2; }

/* ── Shared window chrome ───────────────── */

.win-titlebar {
    height: 3;
    background: #060d17;
    border-bottom: solid #00d4ff;
    padding: 0 2;
    align: left middle;
}

.win-title {
    color: #00d4ff;
    text-style: bold;
    width: 1fr;
    content-align: left middle;
    height: 3;
}

.win-close {
    background: #450a0a;
    border: round #ff4757;
    color: #ff4757;
    min-width: 6;
    height: 3;
}

.win-close:hover {
    background: #7f1d1d;
    color: #fca5a5;
}

/* ── Shared button styles ───────────────── */

Button {
    background: #1a2740;
    border: round #1e3a5f;
    color: #ecf0f1;
}

Button:hover {
    background: #243450;
    border: round #00d4ff;
    color: #ffffff;
}

.btn-primary {
    background: #00d4ff22;
    border: round #00d4ff;
    color: #00d4ff;
    text-style: bold;
}

.btn-primary:hover {
    background: #00d4ff44;
    color: #ffffff;
}

.btn-success {
    background: #2ed57322;
    border: round #2ed573;
    color: #2ed573;
    text-style: bold;
}

.btn-danger {
    background: #ff475722;
    border: round #ff4757;
    color: #ff4757;
}

.btn-danger:hover {
    background: #ff475744;
    color: #fca5a5;
}

/* ── Input / TextArea ───────────────────── */

Input {
    background: #060d17;
    border: round #1e3a5f;
    color: #ecf0f1;
}

Input:focus {
    border: round #00d4ff;
    background: #0d1b2a;
}

TextArea {
    background: #060d17;
    color: #ecf0f1;
    border: round #1e3a5f;
}

TextArea:focus { border: round #00d4ff; }
TextArea > .text-area--cursor { background: #00d4ff; color: #060d17; }
TextArea > .text-area--gutter { background: #0d1b2a; color: #1e3a5f; }
TextArea > .text-area--cursor-line { background: #0d1b2a; }

/* ── DataTable ──────────────────────────── */

DataTable {
    background: #0d1b2a;
    color: #ecf0f1;
}

DataTable > .datatable--header {
    background: #1a2740;
    color: #00d4ff;
    text-style: bold;
}

DataTable > .datatable--cursor { background: #243450; }

/* ── ListView ───────────────────────────── */

ListView { background: #060d17; border: round #1e3a5f; }

ListView > ListItem {
    background: #060d17;
    color: #ecf0f1;
    height: 2;
    padding: 0 1;
}

ListView > ListItem:hover { background: #0d1b2a; }
ListView > ListItem.--highlight { background: #1a2740; color: #00d4ff; }

/* ── RichLog / Log ──────────────────────── */

RichLog {
    background: #060d17;
    color: #ecf0f1;
    border: none;
    padding: 0 1;
}

/* ── TabbedContent ──────────────────────── */

TabbedContent > TabPane {
    background: #0d1b2a;
    padding: 0;
}

Tabs {
    background: #060d17;
    border-bottom: solid #1e3a5f;
}

Tab {
    background: #060d17;
    color: #7f8c8d;
    padding: 0 2;
}

Tab:hover { background: #0d1b2a; color: #ecf0f1; }
Tab.-active { color: #00d4ff; text-style: bold; background: #0d1b2a; border-bottom: solid #00d4ff; }

/* ── Notes ──────────────────────────────── */

#notes-list-pane {
    width: 26;
    border-right: solid #1e3a5f;
    background: #060d17;
}

#notes-edit-pane { width: 1fr; }

#notes-edit-pane Input {
    border-bottom: solid #1e3a5f;
    background: #060d17;
    height: 3;
}

/* ── Clock ──────────────────────────────── */

#clock-left  { width: 1fr; padding: 2 3; border-right: solid #1e3a5f; }
#clock-right { width: 1fr; padding: 1 2; }

#clock-main  { color: #00d4ff; text-style: bold; text-align: center; padding: 1 0; content-align: center middle; }
#clock-zones { color: #7f8c8d; text-align: center; padding: 1 0; }

#sw-display  { color: #2ed573; text-style: bold; text-align: center; height: 3; content-align: center middle; }
#sw-controls { height: 4; align: center middle; }
#sw-controls Button { margin: 0 1; }

#tm-input-row { height: 4; align: left middle; margin: 1 0; }
#tm-input-row Input  { width: 12; margin: 0 1; }
#tm-input-row Button { margin: 0 1; min-width: 6; }
#tm-display { color: #ffa502; text-style: bold; text-align: center; height: 3; content-align: center middle; }

/* ── Logs ───────────────────────────────── */

#logs-sidebar { width: 14; border-right: solid #1e3a5f; background: #060d17; padding: 1 0; }
#logs-content { width: 1fr; background: #060d17; }
#logs-view    { padding: 0 1; }

/* ── Settings ───────────────────────────── */

#settings-content { padding: 1 2; width: 100%; }
#settings-actions { height: 4; border-top: solid #1e3a5f; background: #0d1b2a; padding: 0 2; align: left middle; }

/* ── Minimize button ─────────────────────── */

.btn-min {
    background: #1a2740;
    border: round #1e3a5f;
    color: #ffa502;
    min-width: 4;
}

.btn-min:hover {
    background: #ffa50222;
    border: round #ffa502;
    color: #ffa502;
}

/* ── Minimized taskbar slot ──────────────── */

.task-btn.minimized {
    background: #0d1b2a;
    border: round #1e3a5f;
    color: #7f8c8d;
    text-style: italic;
}

.task-btn.minimized:hover {
    background: #1a2740;
    border: round #ffa502;
    color: #ffa502;
}

/* ── Button sizing (replaces removed min_width= constructor args) ── */

/* Titlebar action buttons — Open/New/Save/Refresh/etc */
.win-titlebar Button          { min-width: 10; }
.win-titlebar Button.win-close{ min-width: 4;  }

/* Taskbar running-app indicators */
.task-btn { min-width: 16; }

/* Nav / small icon buttons (← → ⟳ ▶ ■) */
#browser-nav Button { min-width: 5; }
#sw-controls Button { min-width: 12; }
#tm-input-row Button{ min-width: 6;  }
#fm-actions Button  { min-width: 14; }
#mail-actions Button{ min-width: 12; }
#login-btns Button  { min-width: 14; }
#notes-edit-pane Button { min-width: 10; }
#editor-actions Button  { min-width: 12; }
#fm-path-bar Button     { min-width: 8;  }

/* Folder / filter sidebar buttons keep full width */
.folder-btn { min-width: 0; }

/* ── File picker modal ─────────────────────── */

.filepicker {
    width: 60;
    height: 24;
}

.fp-path {
    color: #00d4ff;
    text-style: bold;
    padding: 0 0 1 0;
    border-bottom: solid #1e3a5f;
}

.fp-scroll {
    height: 12;
    border: round #1e3a5f;
    background: #060d17;
    margin: 0 0 1 0;
}

#fp-list {
    height: 1fr;
    border: none;
    background: #060d17;
}

#fp-list > ListItem {
    padding: 0 1;
    height: 2;
}

#fp-list > ListItem:hover {
    background: #0d1b2a;
}

.fp-input-row {
    height: 3;
    margin: 0 0 1 0;
    align: left middle;
}

.fp-input-row .llabel {
    width: 6;
}

#fp-input {
    width: 1fr;
}

/* ── Editor sidebar & find modal ──────────── */

#editor-body {
    height: 1fr;
}

.editor-sidebar {
    width: 22;
    border-right: solid #1e3a5f;
    background: #060d17;
    padding: 0;
}

.editor-sidebar .panel-heading {
    color: #00d4ff;
    text-style: bold;
    padding: 1 1;
    border-bottom: solid #1e3a5f;
}

#editor-file-list {
    height: 1fr;
    border: none;
    background: #060d17;
}

#editor-file-list > ListItem {
    padding: 0 1;
    height: 2;
    color: #ecf0f1;
}

#editor-file-list > ListItem:hover {
    background: #0d1b2a;
    color: #00d4ff;
}

#editor-main {
    width: 1fr;
}

#editor-tabs {
    height: 1fr;
}

/* ── Scrollbars ─────────────────────────── */

ScrollBar { background: #060d17; }
ScrollBar > .scrollbar--thumb { background: #1e3a5f; }
ScrollBar > .scrollbar--thumb:hover { background: #243450; }

/* ── Terminal ───────────────────────────── */

#term-log {
    height: 1fr;
    background: #060d17;
    padding: 0 1;
}

#term-input-bar {
    height: 3;
    background: #0d1b2a;
    border-top: solid #1e3a5f;
    padding: 0 1;
    align: left middle;
}

#term-prompt { color: #2ed573; text-style: bold; width: auto; content-align: left middle; height: 3; }
#term-input  { width: 1fr; }

/* ── Browser ────────────────────────────── */

#browser-nav {
    height: 3;
    background: #0d1b2a;
    padding: 0 1;
    align: left middle;
    border-bottom: solid #1e3a5f;
}

#browser-url { width: 1fr; margin: 0 1; }

#browser-content {
    padding: 1 2;
    color: #ecf0f1;
}

#browser-status {
    height: 2;
    border-top: solid #1e3a5f;
    background: #060d17;
    color: #7f8c8d;
    content-align: left middle;
    padding: 0 2;
}

/* ── File Manager ───────────────────────── */

#fm-path-bar {
    height: 3;
    background: #0d1b2a;
    border-bottom: solid #1e3a5f;
    padding: 0 2;
    align: left middle;
}

#fm-path-label { color: #00d4ff; width: 1fr; content-align: left middle; height: 3; }

#fm-left  { width: 30; border-right: solid #1e3a5f; background: #060d17; }
#fm-right { width: 1fr; padding: 1 2; background: #060d17; overflow-y: auto; }

#fm-actions {
    height: 4;
    border-top: solid #1e3a5f;
    background: #0d1b2a;
    padding: 0 2;
    align: left middle;
}

/* ── Mail ───────────────────────────────── */

#mail-left   { width: 20; border-right: solid #1e3a5f; background: #060d17; padding: 1 0; }
#mail-mid    { width: 32; border-right: solid #1e3a5f; }
#mail-right  { width: 1fr; padding: 1 2; overflow-y: auto; }

.folder-btn {
    background: transparent;
    border: none;
    color: #7f8c8d;
    height: 2;
    width: 100%;
    content-align: left middle;
    padding: 0 2;
}

.folder-btn:hover  { background: #0d1b2a; color: #ecf0f1; border: none; }
.folder-btn.active { color: #00d4ff; background: #1a2740; text-style: bold; border: none; border-left: solid #00d4ff; }

#mail-actions {
    height: 4;
    border-top: solid #1e3a5f;
    background: #0d1b2a;
    padding: 0 2;
    align: left middle;
}

/* ── Calculator ─────────────────────────── */

#calc-display {
    height: 6;
    background: #060d17;
    border: round #1e3a5f;
    padding: 1 2;
    align: right bottom;
}

#calc-expr   { color: #7f8c8d; text-align: right; width: 100%; height: 2; content-align: right bottom; }
#calc-result { color: #2ed573; text-style: bold; text-align: right; width: 100%; height: 3; content-align: right bottom; }

#calc-hist {
    height: 7;
    background: #060d17;
    border: round #1e3a5f;
    overflow-y: auto;
    padding: 0 2;
}

#calc-grid {
    height: 1fr;
    padding: 1;
}

.calc-row {
    width: 100%;
    height: 3;
    margin: 0 0 1 0;
}

.cbtn { background: #1a2740; border: round #1e3a5f; color: #ecf0f1; height: 3; width: 1fr; text-style: bold; content-align: center middle; }
.cbtn:hover { background: #243450; color: #ffffff; }
.cbtn.op  { background: #0d1b2a; color: #00d4ff; border: round #1e3a5f; }
.cbtn.op:hover { background: #1a2740; color: #22d3ee; }
.cbtn.eq  { background: #00d4ff22; border: round #00d4ff; color: #00d4ff; text-style: bold; }
.cbtn.eq:hover { background: #00d4ff44; }
.cbtn.clr { background: #ff475722; border: round #ff4757; color: #ff4757; }
.cbtn.clr:hover { background: #ff475744; }
.cbtn.fn  { background: #2ed57322; border: round #2ed57366; color: #2ed573; }
.cbtn.fn:hover { background: #2ed57344; }

/* ── Monitor ────────────────────────────── */

#monitor-grid {
    grid-size: 2;
    grid-gutter: 1;
    height: auto;
    padding: 1;
}

.monitor-card {
    background: #1a2740;
    border: round #1e3a5f;
    height: 8;
    padding: 1 2;
}

.monitor-card-title { color: #00d4ff; text-style: bold; }
.monitor-value      { color: #ecf0f1; text-style: bold; }
.monitor-bar        { color: #2ed573; }

/* ── Header / Footer ────────────────────── */

Header { background: #060d17; color: #00d4ff; }
Footer { background: #060d17; color: #7f8c8d; }
Footer > .footer--key { background: #1a2740; color: #00d4ff; }

/* ── Editor status bar ──────────────────── */
.editor-statusbar {
    height: 1;
    background: #0d1b2a;
    color: #7f8c8d;
    padding: 0 1;
    dock: bottom;
}

#editor-body-outer {
    height: 1fr;
}

/* ── Autocomplete modal ─────────────────── */
_AutocompleteModal {
    align: center top;
    background: rgba(0,0,0,0.3);
}

#ac-box {
    width: 40;
    height: auto;
    max-height: 14;
    background: #1a2740;
    border: solid #00d4ff;
    margin-top: 5;
}

#ac-list {
    height: auto;
    max-height: 12;
}

#ac-list > ListItem {
    padding: 0 1;
    height: 2;
    color: #ecf0f1;
}

#ac-list > ListItem:hover,
#ac-list > ListItem.highlight {
    background: #1e3a5f;
    color: #00d4ff;
}

/* ── Git status modal ───────────────────── */
_GitStatusModal {
    align: center middle;
    background: rgba(0,0,0,0.6);
}

#git-status-box {
    width: 60;
    height: 20;
    background: #0d1b2a;
    border: solid #00d4ff;
}

#git-status-title {
    color: #00d4ff;
    text-style: bold;
    padding: 1 2;
    border-bottom: solid #1e3a5f;
}

#git-status-list {
    height: 1fr;
}

#git-status-list > ListItem {
    padding: 0 2;
}

#git-status-actions {
    height: 3;
    align: center middle;
    border-top: solid #1e3a5f;
    padding: 0 1;
}

/* ── Git commit modal ───────────────────── */
_GitCommitModal {
    align: center middle;
    background: rgba(0,0,0,0.6);
}

#git-commit-box {
    width: 50;
    height: 14;
    background: #0d1b2a;
    border: solid #00d4ff;
}

#git-commit-title {
    color: #00d4ff;
    text-style: bold;
    padding: 1 2;
    border-bottom: solid #1e3a5f;
}

#git-commit-input {
    margin: 1 2;
    width: 1fr;
}

#git-commit-actions {
    height: 3;
    align: center middle;
    border-top: solid #1e3a5f;
    padding: 0 1;
}
"""

# ── App manifest ──────────────────────────────────────────────────────────────

APPS = [
    # Row 1 — core tools
    {"id": "terminal",   "icon": "⌨",  "name": "Terminal",   "desc": "Shell & cmds"},
    {"id": "browser",    "icon": "◉",  "name": "Browser",    "desc": "Web + tabs"},
    {"id": "files",      "icon": "◫",  "name": "Files",      "desc": "VFS manager"},
    {"id": "editor",     "icon": "▤",  "name": "Editor",     "desc": "Code editor"},
    # Row 2 — productivity
    {"id": "mail",       "icon": "⊠",  "name": "Mail",       "desc": "BradMail"},
    {"id": "notes",      "icon": "✎",  "name": "Notes",      "desc": "Sticky notes"},
    {"id": "calculator", "icon": "⌗",  "name": "Calc",       "desc": "Math + sci"},
    {"id": "clock",      "icon": "◷",  "name": "Clock",      "desc": "Time & timer"},
    # Row 3 — system
    {"id": "monitor",    "icon": "⊞",  "name": "Monitor",    "desc": "CPU / RAM"},
    {"id": "logs",       "icon": "≡",  "name": "Logs",       "desc": "System logs"},
    {"id": "kernel",     "icon": "⧉",  "name": "Kernel",     "desc": "Tasks & VFS"},
    {"id": "settings",   "icon": "⊕",  "name": "Settings",   "desc": "Config"},
    # Row 4 — security & packages
    {"id": "bradsec",    "icon": "⊛",  "name": "BradSec",    "desc": "Security"},
    {"id": "bpkg",       "icon": "⬡",  "name": "bpkg",       "desc": "Packages"},
    # Row 5 — creative & tools
    {"id": "paint",      "icon": "🎨",  "name": "Paint",     "desc": "Pixel editor"},
    {"id": "converter",  "icon": "⇄",  "name": "Converter",  "desc": "Unit converter"},
    {"id": "rss",        "icon": "◉",  "name": "RSS Reader", "desc": "Feed reader"},
    # Row 6 — new apps
    {"id": "snake",      "icon": "🐍",  "name": "Snake Game", "desc": "Classic snake"},
    {"id": "vault",      "icon": "🔐",  "name": "Vault",      "desc": "Password manager"},
    {"id": "weather",    "icon": "🌤",  "name": "Weather",    "desc": "Forecast"},
    # Row 7 — games & tools
    {"id": "minesweeper","icon": "💣",  "name": "Minesweeper","desc": "Classic mines"},
    {"id": "game2048",   "icon": "🎲",  "name": "2048",       "desc": "Tile game"},
    {"id": "markdown",   "icon": "📝",  "name": "Markdown",   "desc": "MD preview"},
    {"id": "mesh",       "icon": "🕸",  "name": "Mesh",       "desc": "P2P network"},
]

# ── Messages ──────────────────────────────────────────────────────────────────

class LaunchApp(Message):
    def __init__(self, app_id: str):
        super().__init__()
        self.app_id = app_id

class MinimizeApp(Message):
    """Posted by a window when the user clicks its minimise button (—).
    DesktopScreen keeps the app in _open_apps but marks it _minimized."""
    def __init__(self, app_id: str):
        super().__init__()
        self.app_id = app_id

# ═══════════════════════════════════════════════════════════════════════════════
# SPLASH SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

SPLASH_CSS = """
SplashScreen {
    align: center middle;
    background: #060d17;
}

#splash-box {
    width: 70;
    height: auto;
    align: center middle;
    padding: 2 4;
}

#splash-logo {
    color: #00d4ff;
    text-style: bold;
    text-align: center;
    width: 100%;
    padding: 0 0 1 0;
}

#splash-tagline {
    color: #7f8c8d;
    text-align: center;
    width: 100%;
    padding: 0 0 2 0;
}

#splash-boot-log {
    width: 100%;
    height: 10;
    padding: 0 2;
    color: #ecf0f1;
}

#splash-bar-row {
    width: 100%;
    height: 3;
    align: center middle;
    padding: 1 2;
}

#splash-progress {
    width: 1fr;
    color: #00d4ff;
}

#splash-pct {
    width: 6;
    color: #7f8c8d;
    content-align: right middle;
}
"""


class SplashScreen(Screen):
    """Animated boot splash — runs real VFS/driver init while displaying
    a boot sequence, then transitions to LoginScreen."""

    CSS = SPLASH_CSS

    _STEPS = [
        (0.10, "Kernel",   "Starting BradOS kernel v3.0"),
        (0.25, "VFS",      "Mounting virtual filesystem  /  /home  /tmp  /proc  /dev"),
        (0.45, "Drivers",  "Loading driver subsystem  (net · display · storage · input)"),
        (0.60, "BradSec",  "Initialising BradSec security layer"),
        (0.75, "Network",  "Probing network interfaces"),
        (0.90, "Desktop",  "Starting Ocean Dark desktop shell"),
        (1.00, "Ready",    "All systems operational  —  welcome"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="splash-box"):
            yield Static(LOGO, id="splash-logo")
            yield Static(
                "Adaptive Desktop OS  ·  v3.0.0  ·  Ocean Dark",
                id="splash-tagline",
            )
            yield RichLog(id="splash-boot-log", highlight=False, markup=True)
            with Horizontal(id="splash-bar-row"):
                yield Static("", id="splash-progress")
                yield Static(" 0%", id="splash-pct")

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.styles.animate("opacity", 1.0, duration=0.4)
        self._boot()

    @work
    async def _boot(self) -> None:
        """Run the boot sequence, actually initialising VFS + drivers."""
        log = self.query_one("#splash-boot-log", RichLog)

        for frac, label, msg in self._STEPS:
            await asyncio.sleep(0.28)

            # Colour by stage
            if label == "Ready":
                color = "#2ed573"
            elif label == "BradSec":
                color = "#ffa502"
            else:
                color = "#00d4ff"

            log.write(
                f"[{color}]  ●[/]  [bold]{label:<10}[/]  [#7f8c8d]{msg}[/]"
            )

            # Update progress bar
            width   = 48
            filled  = int(frac * width)
            bar     = f"[#00d4ff]{'█' * filled}[/][#1e3a5f]{'░' * (width - filled)}[/]"
            pct_str = f"{int(frac * 100):3d}%"
            try:
                self.query_one("#splash-progress", Static).update(bar)
                self.query_one("#splash-pct",      Static).update(pct_str)
            except NoMatches:
                pass

        # Actual init happens in thread so the animation stays smooth
        await asyncio.to_thread(self._real_init)

        await asyncio.sleep(0.4)

        # Fade out then switch to login
        self.styles.animate("opacity", 0.0, duration=0.35)
        await asyncio.sleep(0.4)
        self.app.push_screen(LoginScreen())

    @staticmethod
    def _real_init() -> None:
        """Blocking init — runs in thread pool so the UI doesn't stutter."""
        try:
            from brados_apps import init_dirs
            init_dirs()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# LOGIN SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

LOGO = """\
  ██████╗ ██████╗  █████╗ ██████╗  ██████╗ ███████╗
  ██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔═══██╗██╔════╝
  ██████╔╝██████╔╝███████║██║  ██║██║   ██║███████╗
  ██╔══██╗██╔══██╗██╔══██║██║  ██║██║   ██║╚════██║
  ██████╔╝██║  ██║██║  ██║██████╔╝╚██████╔╝███████║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝  ╚═════╝╚══════╝"""


class LoginScreen(Screen):
    BINDINGS: ClassVar = [Binding("ctrl+q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Container(id="login-box"):
            yield Static(LOGO, id="login-logo")
            yield Static("Adaptive Desktop OS  ·  v3.0.0  ·  Ocean Dark", id="login-sub")
            with Horizontal(classes="lfield"):
                yield Label("Username", classes="llabel")
                with Container(classes="linput"):
                    yield Input(placeholder="your username", id="usr")
            with Horizontal(id="login-btns"):
                yield Button("▶  Login",    id="btn-login",  classes="btn-primary")
                yield Button("＋  New User", id="btn-new")
                yield Button("◌  Guest",    id="btn-guest")
            yield Static("", id="login-err")

    def on_mount(self) -> None:
        self.query_one("#usr", Input).focus()

    @on(Input.Submitted, "#usr")
    def _enter(self) -> None:
        self._go()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-guest":
            self.app.user_profile = load_user_profile("guest")
            self.app.push_screen(DesktopScreen())
        else:
            self._go()

    def _go(self) -> None:
        uname = self.query_one("#usr", Input).value.strip()
        if not uname:
            self.query_one("#login-err", Static).update("⚠  Username required")
            self._shake()
            return
        self.app.user_profile = load_user_profile(uname)
        self.query_one("#login-err", Static).update("")
        self.app.push_screen(DesktopScreen())

    async def _shake(self) -> None:
        box = self.query_one("#login-box")
        for _ in range(3):
            box.styles.animate("offset", (3, 0), duration=0.04)
            await asyncio.sleep(0.05)
            box.styles.animate("offset", (-3, 0), duration=0.04)
            await asyncio.sleep(0.05)
        box.styles.animate("offset", (0, 0), duration=0.04)


# ═══════════════════════════════════════════════════════════════════════════════
# DESKTOP SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

class TopClock(Static):
    _t: reactive[str] = reactive("")
    def on_mount(self): self._tick(); self.set_interval(1, self._tick)
    def _tick(self): self._t = datetime.now().strftime("%H:%M:%S")
    def render(self) -> str: return self._t


class TrayStats(Static):
    _s: reactive[str] = reactive("CPU --%  RAM --%")

    def on_mount(self):
        self.set_interval(3, self._refresh)
        self._refresh()

    @work
    async def _refresh(self) -> None:
        # Blocking psutil calls run in thread pool; widget update happens
        # after the await, safely on the main event loop.
        txt = await asyncio.to_thread(self._collect)
        if txt != self._s:           # skip re-render when nothing changed
            self._s = txt

    @staticmethod
    def _collect() -> str:
        try:
            import psutil                               # type: ignore
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            return f"CPU {cpu:4.0f}%  RAM {ram:4.0f}%"
        except ImportError:
            return "psutil ✗"

    def render(self) -> str: return self._s


class SecIndicator(Static):
    _dot: reactive[str] = reactive("●")

    def on_mount(self) -> None:
        self.styles.animate("opacity", 0.4, duration=1.5)
        self.styles.animate("opacity", 1.0, duration=1.5)
        self.set_interval(3, self._pulse)

    def _pulse(self) -> None:
        self._dot = "◉" if self._dot == "●" else "●"
        self.styles.animate("opacity", 0.4, duration=1.0)
        self.styles.animate("opacity", 1.0, duration=1.0)

    def render(self) -> str:
        return f"[#00d4ff]{self._dot} sec[/]"


class AppIconWidget(Static):
    DEFAULT_CSS = """
    AppIconWidget {
        width: 1fr;
        height: 7;
        border: round #1e3a5f;
        background: #1a2740;
        content-align: center middle;
        text-align: center;
        padding: 1;
        margin: 0 1 0 0;
    }
    AppIconWidget:hover {
        border: round #00d4ff;
        background: #1f3050;
    }
    AppIconWidget:last-of-type {
        margin: 0;
    }
    """

    def __init__(self, app_def: dict):
        super().__init__()
        self._app = app_def

    def render(self) -> str:
        return (
            f"[bold #00d4ff]{self._app['icon']}[/]\n"
            f"[bold #ecf0f1]{self._app['name']}[/]\n"
            f"[#7f8c8d]{self._app['desc']}[/]"
        )

    def on_click(self) -> None:
        self.post_message(LaunchApp(self._app["id"]))

    def render(self) -> str:
        return (
            f"[bold #00d4ff]{self._app['icon']}[/]\n"
            f"[bold #ecf0f1]{self._app['name']}[/]\n"
            f"[#7f8c8d]{self._app['desc']}[/]"
        )

    def on_click(self) -> None:
        self.post_message(LaunchApp(self._app["id"]))


class DesktopScreen(Screen):
    BINDINGS: ClassVar = [
        Binding("q",       "app.quit",        "Quit"),
        Binding("l",       "logout",           "Logout"),
        Binding("F1",      "open_help",        "Help"),
        # App shortcuts
        Binding("t",       "launch('terminal')",  "Terminal",   show=False),
        Binding("b",       "launch('browser')",   "Browser",    show=False),
        Binding("f",       "launch('files')",     "Files",      show=False),
        Binding("e",       "launch('editor')",    "Editor",     show=False),
        Binding("m",       "launch('mail')",      "Mail",       show=False),
        Binding("n",       "launch('notes')",     "Notes",      show=False),
        Binding("c",       "launch('calculator')", "Calc",      show=False),
        Binding("k",       "launch('clock')",     "Clock",      show=False),
        Binding("p",       "launch('monitor')",   "Monitor",    show=False),
        Binding("g",       "launch('logs')",      "Logs",       show=False),
        Binding("ctrl+k",  "launch('kernel')",    "Kernel",     show=False),
        Binding("s",       "launch('settings')",  "Settings",   show=False),
        Binding("shift+s", "launch('bradsec')",   "BradSec",    show=False),
        Binding("ctrl+p",  "launch('bpkg')",      "bpkg",       show=False),
    ]

    # NOTE: do NOT use _running — Textual's App base class owns App._running: bool
    # and it silently overwrites any class-level set() with True at startup.
    # Always initialize mutable state in on_mount instead.

    def compose(self) -> ComposeResult:
        with Horizontal(id="top-bar"):
            yield Static("⬡ BradOS", id="top-brand")
            yield Static("", id="top-spacer")
            yield TopClock(id="top-clock")
            yield Static("", id="top-user")

        with ScrollableContainer(id="desktop-area"):
            with Vertical(id="icon-grid"):
                # 4 icons per row — Horizontal rows are bulletproof vs CSS grid-size
                rows = [APPS[i:i+4] for i in range(0, len(APPS), 4)]
                for row in rows:
                    with Horizontal(classes="icon-row"):
                        for app in row:
                            yield AppIconWidget(app)
            yield Static(
                "[#1e3a5f]t=Terminal  b=Browser  f=Files  e=Editor  m=Mail  "
                "n=Notes  c=Calc  k=Clock  p=Monitor  g=Logs  s=Settings[/]",
                id="desktop-hint",
            )

        with Horizontal(id="taskbar"):
            with Horizontal(id="taskbar-apps"):
                yield Static("[#1e3a5f]No apps open[/]", id="taskbar-placeholder")
            with Horizontal(id="taskbar-tray"):
                yield SecIndicator(id="tray-sec")
                yield TrayStats(id="tray-stats")
                yield Static("", id="tray-sep")
                yield TopClock(id="tray-clock")

    def on_mount(self) -> None:
        self._open_apps: set[str] = set()
        self._minimized: set[str] = set()
        self.query_one("#top-user", Static).update(
            f"[#2ed573]● {self.app.user_profile.get('username', '?')}[/]"
        )
        # Staggered icon entrance animation
        for i, widget in enumerate(self.query(AppIconWidget)):
            widget.styles.opacity = 0.0
            widget.styles.animate("opacity", 1.0, duration=0.4, delay=i * 0.05)
        self.set_interval(3, self._pulse_icons)

    # ── Message / button handlers ─────────────────────────────────────────────

    def on_launch_app(self, message: LaunchApp) -> None:
        self._open(message.app_id)

    def on_minimize_app(self, message: MinimizeApp) -> None:
        """Window posted this before dismissing itself — keep it in the taskbar."""
        self._minimized.add(message.app_id)
        self._refresh_taskbar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("task-"):
            self._open(event.button.id[5:])

    def action_launch(self, app_id: str) -> None:
        self._open(app_id)

    # ── App launcher ──────────────────────────────────────────────────────────

    def _open(self, app_id: str) -> None:
        screen_map = {
            "terminal":   TerminalWindow,
            "browser":    BrowserWindow,
            "files":      FileManagerWindow,
            "editor":     EditorWindow,
            "mail":       MailWindow,
            "notes":      NotesWindow,
            "calculator": CalculatorWindow,
            "clock":      ClockWindow,
            "monitor":    MonitorWindow,
            "logs":       LogsWindow,
            "kernel":     KernelWindow,
            "settings":   SettingsWindow,
            "bradsec":    BradSecWindow,
            "bpkg":       BpkgWindow,
            "paint":      PaintWindow,
            "converter":  ConverterWindow,
            "rss":        RssWindow,
            "snake":      SnakeWindow,
            "vault":      VaultWindow,
            "weather":    WeatherWindow,
            "minesweeper": MineWindow,
            "game2048":    Game2048Window,
            "markdown":    MarkdownWindow,
            "mesh":        MeshWindow,
        }
        cls = screen_map.get(app_id)
        if not cls:
            return
        # Restore from minimized or open fresh
        self._minimized.discard(app_id)
        self._open_apps.add(app_id)
        self._refresh_taskbar()
        self.app.push_screen(cls(), callback=lambda _: self._on_close(app_id))

    def _on_close(self, app_id: str) -> None:
        """Called when the screen stack is popped — either closed or minimized."""
        if app_id in self._minimized:
            # Window minimized itself before dismissing; keep it in _open_apps
            pass
        else:
            self._open_apps.discard(app_id)
            self._minimized.discard(app_id)
        self._refresh_taskbar()

    # ── Taskbar ───────────────────────────────────────────────────────────────

    def _refresh_taskbar(self) -> None:
        try:
            tbar = self.query_one("#taskbar-apps", Horizontal)
            tbar.remove_children()
            if not self._open_apps:
                tbar.mount(Static("[#1e3a5f]No apps open[/]", id="taskbar-placeholder"))
                return
            for aid in sorted(self._open_apps):
                meta      = next((a for a in APPS if a["id"] == aid), None)
                icon      = meta["icon"] if meta else "◌"
                name      = meta["name"] if meta else aid
                minimized = aid in self._minimized
                label     = f"{icon} [{name}]" if minimized else f"{icon} {name}"
                cls       = "task-btn minimized" if minimized else "task-btn active"
                tbar.mount(Button(label, id=f"task-{aid}", classes=cls))
        except NoMatches:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_logout(self) -> None:
        self.app.user_profile = {}
        self.dismiss()

    def action_open_help(self) -> None:
        self.app.push_screen(HelpWindow())

    def _pulse_icons(self) -> None:
        self._icon_pulse = not getattr(self, "_icon_pulse", False)
        for widget in self.query(AppIconWidget):
            aid = widget._app["id"]
            if aid in self._open_apps:
                bg = "#243450" if self._icon_pulse else "#1a2740"
                widget.styles.background = bg


# ─────────────────────────────────────────────────────────────────────────────
# BASE WINDOW — every app screen inherits this for free minimize support
# ─────────────────────────────────────────────────────────────────────────────

class BradWindow(Screen):
    """Base class for all BradOS app windows.

    Provides:
    - Smooth fade-in animation on open.
    - Smooth fade-out animation on close.
    - Minimize button (—) via @on selector — doesn't interfere with subclass handlers.
    - APP_ID class variable for MinimizeApp message.
    """

    APP_ID: ClassVar[str] = "unknown"

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.styles.animate("opacity", 1.0, duration=0.2)

    def dismiss(self, result=None) -> None:
        self.styles.animate("opacity", 0.0, duration=0.15)
        self.set_timer(0.18, self._finish_dismiss, result)

    def _finish_dismiss(self, result=None) -> None:
        super().dismiss(result)

    @on(Button.Pressed, "#btn-min")
    def _do_minimize(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(MinimizeApp(self.APP_ID))
        self.dismiss()

# ═══════════════════════════════════════════════════════════════════════════════
# BRASH TERMINAL WINDOW  (replaces old TerminalWindow)
# ═══════════════════════════════════════════════════════════════════════════════

from brados_brash import BrashShell

class TerminalWindow(BradWindow):
    """Full brash-powered terminal with autosuggestions, history, and pipes."""
    APP_ID: ClassVar[str] = "terminal"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⌨  Brash Terminal", classes="win-title")
            yield Button("✕", classes="win-close", id="btn-close")

        yield RichLog(id="term-log", highlight=True, markup=True)

        with Horizontal(id="term-input-bar"):
            yield Static("", id="term-prompt")
            yield Input(placeholder="type a command…", id="term-input")

    def on_mount(self) -> None:
        log  = self.query_one("#term-log", RichLog)
        inp  = self.query_one("#term-input", Input)
        prom = self.query_one("#term-prompt", Static)
        self._brash = BrashShell(
            log=log, inp=inp, prompt=prom,
            vfs=getattr(self.app, "vfs", None),
            cwd=os.path.expanduser("~"),
        )
        self._brash.username = self.app.user_profile.get("username", "brad")
        self._brash.refresh_prompt()

        log.write("[bold #00d4ff]⏣  Brash Terminal v1.0[/]")
        log.write("[#7f8c8d]Type 'help' for built-in commands. Autosuggestions are on.[/]")
        log.write("")
        inp.focus()

    def _update_suggestion(self) -> None:
        inp = self.query_one("#term-input", Input)
        prefix = inp.value
        if prefix and self._brash:
            suffix = self._brash.autocomplete_suggest(prefix)
            if suffix:
                inp.placeholder = suffix
            else:
                inp.placeholder = ""
        else:
            inp.placeholder = ""

    @on(Input.Submitted, "#term-input")
    async def _submit(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        inp = self.query_one("#term-input", Input)
        inp.value = ""
        inp.placeholder = ""
        if not cmd:
            self._brash.refresh_prompt()
            return
        await self._brash.handle_input(cmd)
        self._update_suggestion()

    @on(Input.Changed, "#term-input")
    def _on_input_changed(self) -> None:
        self._update_suggestion()

    def on_key(self, event) -> None:
        if not self._brash:
            return
        inp = self.query_one("#term-input", Input)
        if event.key == "up":
            val = self._brash.history_up()
            if val is not None:
                inp.value = val
                inp.cursor_position = len(val)
            event.prevent_default()
        elif event.key == "down":
            val = self._brash.history_down()
            if val is not None:
                inp.value = val
                inp.cursor_position = len(val)
            event.prevent_default()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss()


# ═══════════════════════════════════════════════════════════════════════════════
# BROWSER WINDOW  (tabbed)
# ═══════════════════════════════════════════════════════════════════════════════

class BrowserWindow(BradWindow):
    APP_ID: ClassVar[str] = "browser"
    BINDINGS: ClassVar = [
        Binding("escape",   "dismiss",  "Close"),
        Binding("ctrl+t",   "new_tab",  "New Tab"),
        Binding("ctrl+w",   "close_tab","Close Tab"),
        Binding("ctrl+l",   "focus_url","Address Bar"),
    ]

    _tab_count: int = 0
    _tab_urls:  dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("◉  BradBrowser", classes="win-title")
            yield Button("＋ Tab",   id="btn-new-tab")
            yield Button("✕ Tab",    id="btn-close-tab", classes="btn-danger")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕",        id="btn-close",     classes="win-close")

        with Horizontal(id="browser-nav"):
            yield Button("←", id="btn-back-hist")
            yield Button("⟳", id="btn-reload")
            yield Input(placeholder="https://…  or  local page name", id="browser-url")
            yield Button("▶ Go", id="btn-go", classes="btn-primary")
            yield Button("🌐", id="btn-web-mode")

        yield TabbedContent(id="browser-tabs")

        yield Static("Ready", id="browser-status")

    def on_mount(self) -> None:
        self.action_new_tab()

    # ── Tab management ─────────────────────────────────────────────────────

    def action_new_tab(self) -> None:
        self._tab_count += 1
        tab_id  = f"tab-{self._tab_count}"
        tab_lbl = f"New Tab {self._tab_count}"
        self._tab_urls[tab_id] = ""
        tc = self.query_one("#browser-tabs", TabbedContent)
        tc.add_pane(TabPane(tab_lbl, self._make_tab_content(tab_id), id=tab_id))

    def action_close_tab(self) -> None:
        tc = self.query_one("#browser-tabs", TabbedContent)
        active = tc.active
        if active and self._tab_count > 1:
            tc.remove_pane(active)
            self._tab_urls.pop(active, None)

    def action_focus_url(self) -> None:
        self.query_one("#browser-url", Input).focus()

    def _make_tab_content(self, tab_id: str) -> Vertical:
        return Vertical(
            ScrollableContainer(
                Static(
                    "[#7f8c8d]Enter a URL above and press ▶ Go.[/]\n\n"
                    "[#1e3a5f]Ctrl+T  New tab    Ctrl+W  Close tab    Ctrl+L  Focus URL bar[/]",
                    id=f"content-{tab_id}",
                    classes="browser-content",
                ),
                id=f"scroller-{tab_id}",
            )
        )

    # ── Navigation ─────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":      self.dismiss(); return
        if bid == "btn-new-tab":    self.action_new_tab(); return
        if bid == "btn-close-tab":  self.action_close_tab(); return
        if bid == "btn-go":         self._navigate(); return
        if bid == "btn-reload":     self._navigate(); return

    @on(Input.Submitted, "#browser-url")
    def _on_url_enter(self) -> None:
        self._navigate()

    def _navigate(self) -> None:
        url = self.query_one("#browser-url", Input).value.strip()
        if not url:
            return
        tc     = self.query_one("#browser-tabs", TabbedContent)
        tab_id = tc.active
        if not tab_id:
            return
        self._tab_urls[tab_id] = url
        label  = self._short_label(url)
        self._fetch_and_render(url, tab_id, label)

    @staticmethod
    def _short_label(url: str) -> str:
        url = re.sub(r"^https?://", "", url)
        return url[:20] + ("…" if len(url) > 20 else "")

    @work(exclusive=True)          # cancels any in-flight fetch automatically
    async def _fetch_and_render(self, url: str, tab_id: str, label: str) -> None:
        try:
            self.query_one("#browser-status", Static).update(
                f"[#ffa502]⟳  {url}[/]"
            )
        except NoMatches:
            return

        # All blocking I/O in the thread pool; we return to the main loop after.
        rendered, status = await asyncio.to_thread(self._do_fetch, url)

        escaped = rendered[:10_000].replace("[", "\\[")
        try:
            self.query_one(f"#content-{tab_id}", Static).update(escaped)
            self.query_one("#browser-status",    Static).update(status)
        except NoMatches:
            pass

    def _do_fetch(self, url: str) -> tuple[str, str]:
        """Blocking network/VFS fetch — runs in thread pool."""
        if not url.startswith(("http://", "https://")):
            vpath = f"/home/{url}" if not url.startswith("/") else url
            try:
                text   = self.app.vfs.read_text(vpath)
                return html_to_text(text), f"[#2ed573]✓  local:{url}[/]"
            except Exception as e:
                return (f"Local page not found: {e}\n\n"
                        f"Tip: prefix with https:// for web pages.",
                        f"[#ff4757]✗  {e}[/]")
        try:
            net = self.app.drivers.get(NetworkDriver) if self.app.drivers else None
            if net:
                code, headers, body = net.http_get(url)
            else:
                from urllib.request import urlopen
                from urllib.error import URLError
                with urlopen(url, timeout=10) as r:
                    code    = r.status
                    headers = dict(r.headers)
                    body    = r.read()
            ct = headers.get("content-type", headers.get("Content-Type", ""))
            rendered = (html_to_text(body.decode(errors="replace"))
                        if "html" in ct else body.decode(errors="replace"))
            return rendered, f"[#2ed573]✓  HTTP {code}  {url}[/]"
        except Exception as e:
            return (f"Error: {e}\n\npip install requests  for better HTTPS support.",
                    f"[#ff4757]✗  {e}[/]")


# ═══════════════════════════════════════════════════════════════════════════════
# FILE MANAGER WINDOW  (VFS-aware)
# ═══════════════════════════════════════════════════════════════════════════════

class FileManagerWindow(BradWindow):
    APP_ID: ClassVar[str] = "files"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _cwd:  str = "/home"
    _vfs   = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("◫  File Manager", classes="win-title")
            yield Button("⬆ Up", id="btn-up")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕",    id="btn-close", classes="win-close")

        with Horizontal(id="fm-path-bar"):
            yield Static("/home", id="fm-path-label")

        with Horizontal():
            with ScrollableContainer(id="fm-left"):
                yield ListView(id="fm-tree")
            with ScrollableContainer(id="fm-right"):
                yield Static("[#7f8c8d]Select a file or directory.[/]", id="fm-preview")

        with Horizontal(id="fm-actions"):
            yield Button("📄 New File",  id="btn-newfile")
            yield Button("📁 New Dir",   id="btn-newdir")
            yield Button("🗑 Delete",     id="btn-delete",   classes="btn-danger")
            yield Input(placeholder="Rename/copy name…", id="fm-name-input")
            yield Button("✏ Rename", id="btn-rename")

    def on_mount(self) -> None:
        self._vfs      = self.app.vfs
        self._entries  : list[tuple[str, str]] = []
        self._load_gen : int = 0          # increments every _load(); makes IDs unique
        self._load(self._cwd)

    def _load(self, path: str) -> None:
        self._cwd      = path
        self._entries  = []
        self._load_gen += 1
        gen = self._load_gen             # snapshot — used as ID prefix this call
        try:
            self.query_one("#fm-path-label", Static).update(f"[#00d4ff]{path}[/]")
            tree = self.query_one("#fm-tree", ListView)
            tree.clear()
            try:
                raw = self._vfs.listdir(path)
            except Exception:
                raw = []

            dirs  = sorted(n for n in raw
                           if self._safe_is_dir(path, n))
            files = sorted(n for n in raw if n not in dirs)

            for name in dirs:
                idx = len(self._entries)
                self._entries.append(("d", name))
                tree.append(ListItem(
                    Static(f"[#00d4ff]◫ {name}/[/]"),
                    id=f"g{gen}e{idx}",
                ))

            for name in files:
                child = path.rstrip("/") + "/" + name
                idx   = len(self._entries)
                self._entries.append(("f", name))
                try:
                    sz = self._vfs.stat(child).size
                    tree.append(ListItem(
                        Static(f"[#ecf0f1]▤ {name}[/]  [#7f8c8d]{sz:,} B[/]"),
                        id=f"g{gen}e{idx}",
                    ))
                except Exception:
                    self._entries[-1] = ("u", name)
                    tree.append(ListItem(
                        Static(f"[#7f8c8d]? {name}[/]"),
                        id=f"g{gen}e{idx}",
                    ))

            if not self._entries:
                tree.append(ListItem(Static("[#1e3a5f](empty)[/]")))

        except Exception as e:
            try:
                self.query_one("#fm-preview", Static).update(f"[#ff4757]{e}[/]")
            except NoMatches:
                pass

    def _safe_is_dir(self, parent: str, name: str) -> bool:
        try:
            return self._vfs.stat(parent.rstrip("/") + "/" + name).is_dir
        except Exception:
            return False

    @on(ListView.Selected, "#fm-tree")
    def _select(self, event: ListView.Selected) -> None:
        if event.item.id is None:
            return
        # ID format: g{gen}e{idx}
        m = re.search(r"e(\d+)$", event.item.id)
        if not m:
            return
        idx = int(m.group(1))
        if not (0 <= idx < len(self._entries)):
            return
        kind, name = self._entries[idx]
        child = self._cwd.rstrip("/") + "/" + name
        if kind == "d":
            self._load(child)
        else:
            try:
                content = self._vfs.read_text(child)[:4000]
                escaped = content.replace("[", "\\[")
                self.query_one("#fm-preview", Static).update(
                    f"[bold #00d4ff]{name}[/]  [#7f8c8d]({self._vfs.stat(child).size:,} B)[/]\n"
                    f"[#1e3a5f]{'─' * 40}[/]\n"
                    f"[#ecf0f1]{escaped}[/]"
                )
            except Exception as e:
                self.query_one("#fm-preview", Static).update(f"[#ff4757]{e}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":  self.dismiss(); return
        if bid == "btn-up":
            parent = "/".join(self._cwd.rstrip("/").split("/")[:-1]) or "/"
            self._load(parent); return
        if bid == "btn-newfile":
            name = self.query_one("#fm-name-input", Input).value.strip()
            if name:
                self._vfs.write(self._cwd.rstrip("/") + "/" + name, b"")
                self._load(self._cwd)
        if bid == "btn-newdir":
            name = self.query_one("#fm-name-input", Input).value.strip()
            if name:
                self._vfs.mkdir(self._cwd.rstrip("/") + "/" + name)
                self._load(self._cwd)
        if bid == "btn-delete":
            sel = self.query_one("#fm-tree", ListView)
            hc  = sel.highlighted_child
            if hc and hc.id:
                m = re.search(r"e(\d+)$", hc.id)
                if m:
                    idx = int(m.group(1))
                    if 0 <= idx < len(self._entries):
                        _, name = self._entries[idx]
                        self._vfs.unlink(self._cwd.rstrip("/") + "/" + name)
                        self._load(self._cwd)
        if bid == "btn-rename":
            sel = self.query_one("#fm-tree", ListView)
            new = self.query_one("#fm-name-input", Input).value.strip()
            hc  = sel.highlighted_child
            if hc and hc.id and new:
                m = re.search(r"e(\d+)$", hc.id)
                if m:
                    idx = int(m.group(1))
                    if 0 <= idx < len(self._entries):
                        _, old = self._entries[idx]
                        src = self._cwd.rstrip("/") + "/" + old
                        dst = self._cwd.rstrip("/") + "/" + new
                        self._vfs.rename(src, dst)
                        self._load(self._cwd)


# ═══════════════════════════════════════════════════════════════════════════════
# EDITOR WINDOW  (multi-tab + file tree + find/replace + themes)
# ═══════════════════════════════════════════════════════════════════════════════

_LANG_MAP: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".html": "html", ".css": "css",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".toml": "toml", ".ini": "ini",
    ".cfg": "ini", ".sh": "bash", ".bash": "bash",
    ".sql": "sql", ".rs": "rust", ".go": "go",
    ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".rb": "ruby", ".php": "php", ".r": "r",
    ".lua": "lua", ".tex": "latex", ".xml": "xml",
}

_THEMES: dict[str, dict] = {
    "Ocean Dark":  {"bg": "#060d17", "fg": "#ecf0f1", "cursor": "#00d4ff"},
    "Monokai":     {"bg": "#272822", "fg": "#f8f8f2", "cursor": "#f92672"},
    "Solarized":   {"bg": "#002b36", "fg": "#839496", "cursor": "#268bd2"},
    "GitHub Light":{"bg": "#ffffff", "fg": "#24292e", "cursor": "#0366d6"},
}


class _FindReplaceModal(ModalScreen):
    BINDINGS: ClassVar = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, tab_id: str):
        super().__init__()
        self._tab_id = tab_id

    def action_cancel(self) -> None:
        self.dismiss()

    def compose(self) -> ComposeResult:
        with Container(id="login-box"):
            yield Static("🔍  Find & Replace", id="login-logo")
            with Horizontal(classes="lfield"):
                yield Label("Find:", classes="llabel")
                with Container(classes="linput"):
                    yield Input("", id="fr-find", placeholder="search text")
            with Horizontal(classes="lfield"):
                yield Label("Replace:", classes="llabel")
                with Container(classes="linput"):
                    yield Input("", id="fr-replace", placeholder="replacement text")
            with Horizontal(id="login-btns"):
                yield Button("Find Next",  id="fr-find-next", classes="btn-primary")
                yield Button("Replace",    id="fr-replace-one")
                yield Button("Replace All",id="fr-replace-all", classes="btn-success")
                yield Button("Cancel",     id="fr-cancel",    classes="btn-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "fr-cancel":
            self.dismiss(); return
        find = self.query_one("#fr-find", Input).value
        repl = self.query_one("#fr-replace", Input).value
        if not find:
            self.notify("Enter search text.", severity="warning"); return
        self.dismiss({bid: (find, repl)})

    @on(Input.Submitted, "#fr-find")
    def _find_submitted(self) -> None:
        find = self.query_one("#fr-find", Input).value
        repl = self.query_one("#fr-replace", Input).value
        if find:
            self.dismiss({"fr-find-next": (find, repl)})

    @on(Input.Submitted, "#fr-replace")
    def _replace_submitted(self) -> None:
        find = self.query_one("#fr-find", Input).value
        repl = self.query_one("#fr-replace", Input).value
        if find:
            self.dismiss({"fr-replace-one": (find, repl)})


class _AutoCompleteModal(ModalScreen[str | None]):
    """Floating overlay showing code completions."""

    def __init__(self, completions: list[tuple[str, str]]) -> None:
        super().__init__()
        self._completions = completions

    def compose(self) -> ComposeResult:
        with Vertical(id="ac-box"):
            items = []
            for name, ctype in self._completions:
                suffix = {"function": "()", "class": " ", "module": " ", "statement": " "}.get(ctype, " ")
                items.append(ListItem(Label(f"{name}{suffix}")))
            yield ListView(*items, id="ac-list")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item:
            try:
                lbl = event.item.query_one(Label)
                text = str(lbl.renderable) if hasattr(lbl, 'renderable') else str(lbl)
                name = text.rstrip(" ()")
                self.dismiss(name)
            except Exception:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "tab":
            event.stop()
            lv = self.query_one("#ac-list", ListView)
            if lv.children and lv.index is not None:
                item = lv.children[lv.index]
                lbl = item.query_one(Label)
                text = str(lbl.renderable) if hasattr(lbl, 'renderable') else str(lbl)
                name = text.rstrip(" ()")
                self.dismiss(name)


class _GitStatusModal(ModalScreen[None]):
    """Shows git status output."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def __init__(self, wd: str) -> None:
        super().__init__()
        self._wd = wd

    def compose(self) -> ComposeResult:
        with Vertical(id="git-status-box"):
            yield Static("Git Status", id="git-status-title")
            yield ListView(id="git-status-list")
            with Horizontal(id="git-status-actions"):
                yield Button("Close", id="gs-close", classes="btn-primary")

    def on_mount(self) -> None:
        lv = self.query_one("#git-status-list", ListView)
        try:
            r = subprocess.run(["git", "-C", self._wd, "status", "--short"],
                               capture_output=True, text=True, timeout=10)
            lines = r.stdout.strip().split("\n") if r.stdout.strip() else ["(clean)"]
            for line in lines[:50]:
                lv.append(ListItem(Label(line)))
        except Exception as e:
            lv.append(ListItem(Label(f"[#ff4757]Error: {e}[/]")))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gs-close":
            self.dismiss()


class _GitCommitModal(ModalScreen[None]):
    """Prompts for a commit message and runs git commit."""

    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def __init__(self, wd: str) -> None:
        super().__init__()
        self._wd = wd

    def compose(self) -> ComposeResult:
        with Vertical(id="git-commit-box"):
            yield Static("Git Commit", id="git-commit-title")
            yield Input("", id="gc-msg", placeholder="Commit message")
            with Horizontal(id="git-commit-actions"):
                yield Button("Commit", id="gc-commit", classes="btn-primary")
                yield Button("Cancel", id="gc-cancel")

    @on(Input.Submitted, "#gc-msg")
    def _on_submit(self) -> None:
        self._do_commit()

    def _do_commit(self) -> None:
        msg = self.query_one("#gc-msg", Input).value.strip()
        if not msg:
            self.notify("Enter a commit message.", severity="warning")
            return
        try:
            r = subprocess.run(
                ["git", "-C", self._wd, "commit", "-am", msg],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                self.notify("Committed!", severity="information")
                self.dismiss()
            else:
                self.notify(r.stderr.strip() or "Commit failed", severity="error")
        except Exception as e:
            self.notify(str(e), severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gc-commit":
            self._do_commit()
        elif event.button.id == "gc-cancel":
            self.dismiss()


class BradTextEditor(BradWindow):
    """Code editor with Git integration and Jedi autocompletion."""
    APP_ID: ClassVar[str] = "editor"
    BINDINGS: ClassVar = [
        Binding("ctrl+s",   "save",           "Save"),
        Binding("ctrl+f",   "find_replace",   "Find"),
        Binding("ctrl+n",   "new_file",       "New"),
        Binding("ctrl+o",   "open_file",      "Open"),
        Binding("ctrl+w",   "close_tab",      "Close Tab"),
        Binding("ctrl+tab", "next_tab",       "Next Tab"),
        Binding("ctrl+d",   "goto_definition","Go to Def"),
        Binding("ctrl+g",   "git_status",     "Git Status"),
        Binding("ctrl+shift+c", "git_commit", "Git Commit"),
        Binding("escape",   "dismiss",        "Close"),
    ]

    _tab_count: int = 0
    _tabs: dict[str, dict] = {}
    _theme: str = "Ocean Dark"
    _autocomplete_task: asyncio.Task | None = None
    _last_texts: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("▤  Brad Text Editor", id="editor-title", classes="win-title")
            yield Button("📂 Open",  id="btn-open")
            yield Button("📄 New",   id="btn-new")
            yield Button("💾 Save",  id="btn-save", classes="btn-primary")
            yield Button("🔍",       id="btn-find")
            yield Button("🎨",       id="btn-theme")
            yield Button("✕",        id="btn-close", classes="win-close")

        with Vertical(id="editor-body-outer"):
            with Horizontal(id="editor-body"):
                with Vertical(id="editor-tree", classes="editor-sidebar"):
                    yield Static("[bold #00d4ff]📁  Files[/]", classes="panel-heading")
                    yield ListView(id="editor-file-list")
                with Vertical(id="editor-main"):
                    yield TabbedContent(id="editor-tabs")
            yield Static("", id="editor-statusbar", classes="editor-statusbar")

    def on_mount(self) -> None:
        self._refresh_file_tree()
        self.action_new_file()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _vfs_to_real(self, vfs_path: str) -> str:
        if vfs_path.startswith("/home/"):
            return os.path.join(BRADOS_FILES_DIR, "home", vfs_path[6:])
        return vfs_path

    def _git_dir(self, path: str) -> str | None:
        real = self._vfs_to_real(path)
        d = os.path.dirname(real) if os.path.isfile(real) else real
        while d:
            if os.path.isdir(os.path.join(d, ".git")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return None

    def _git_branch(self, wd: str) -> str:
        try:
            r = subprocess.run(["git", "-C", wd, "branch", "--show-current"],
                               capture_output=True, text=True, timeout=5)
            return r.stdout.strip() or "?"
        except Exception:
            return "?"

    def _git_status_cache(self, wd: str) -> list[str]:
        try:
            r = subprocess.run(["git", "-C", wd, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5)
            return [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
        except Exception:
            return []

    def _git_indicator_for(self, filename: str) -> str | None:
        wd = self._git_dir("/home/" + filename)
        if not wd:
            return None
        entries = self._git_status_cache(wd)
        for e in entries:
            if len(e) > 3 and filename in e[3:]:
                indicator = e[:2].strip()
                if indicator == "??":
                    return "?"
                if indicator == "M ":
                    return "M"
                if indicator == " A":
                    return "A"
                if indicator == "D ":
                    return "D"
                if indicator == "R ":
                    return "R"
                return indicator
        return None

    # ── File tree ────────────────────────────────────────────────────────

    def _refresh_file_tree(self) -> None:
        lv = self.query_one("#editor-file-list", ListView)
        lv.clear()
        try:
            entries = self.app.vfs.listdir("/home")
            for e in sorted(entries):
                try:
                    st = self.app.vfs.stat(f"/home/{e}")
                    icon = "📁 " if st.is_dir else "📄 "
                    if not st.is_dir:
                        gi = self._git_indicator_for(e)
                        prefix = f"[#ffa502]{gi}[/] " if gi else ""
                    else:
                        prefix = ""
                    lv.append(ListItem(Label(f"{prefix}{icon}{e}")))
                except Exception:
                    lv.append(ListItem(Label(f"📄 {e}")))
        except Exception:
            lv.append(ListItem(Label("[#7f8c8d]VFS unavailable[/]")))

    @on(ListView.Selected, "#editor-file-list")
    def _on_tree_select(self, event: ListView.Selected) -> None:
        if event.item:
            try:
                lbl = event.item.query_one(Label)
                label = str(lbl.renderable) if hasattr(lbl, 'renderable') else ""
            except Exception:
                label = ""
            clean = re.sub(r'^\[#[^\]]+\]\S\s*', '', label).lstrip("📁 📄 ")
            path  = "/home/" + clean
            self._open_path(path)

    # ── Tab management ───────────────────────────────────────────────────

    def _detect_language(self, path: str) -> str:
        for ext, lang in _LANG_MAP.items():
            if path.endswith(ext):
                return lang
        return "python" if path.endswith(".py") else "markdown"

    def _update_statusbar(self) -> None:
        ta = self._active_ta()
        if not ta:
            self.query_one("#editor-statusbar", Static).update("")
            return
        line, col = ta.cursor_location
        tc = self.query_one("#editor-tabs", TabbedContent)
        info = self._tabs.get(tc.active, {})
        path = info.get("path", "")
        wd = self._git_dir(path) if path else None
        parts = []
        if wd:
            branch = self._git_branch(wd)
            parts.append(f"[#00d4ff]{branch}[/]")
            status = self._git_status_cache(wd)
            dirty = any(l and l[0] != "?" for l in (s[:2].strip() for s in status))
            if dirty:
                parts.append("[#ffa502]●[/]")
        parts.append(f"Ln {line + 1}, Col {col + 1}")
        lang = info.get("language", "")
        if lang:
            parts.append(f"[#7f8c8d]{lang}[/]")
        self.query_one("#editor-statusbar", Static).update("  ".join(parts))

    def _close_tab(self, tab_id: str | None = None) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        tab_id = tab_id or tc.active
        if tab_id and len(self._tabs) > 1:
            self._last_texts.pop(tab_id, None)
            self._tabs.pop(tab_id, None)
            tc.remove_pane(tab_id)
        self._update_statusbar()

    def action_close_tab(self) -> None:
        self._close_tab()

    def action_next_tab(self) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        tabs = list(tc._tab_indices.keys()) if hasattr(tc, "_tab_indices") else []
        if not tabs:
            return
        cur = tc.active
        idx = (tabs.index(cur) + 1) % len(tabs) if cur in tabs else 0
        tc.active = tabs[idx]
        self._update_statusbar()

    def _active_ta(self) -> TextArea | None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        if not tc.active or tc.active not in self._tabs:
            return None
        ta_id = self._tabs[tc.active]["textarea_id"]
        try:
            return self.query_one(f"#{ta_id}", TextArea)
        except NoMatches:
            return None

    # ── File operations ──────────────────────────────────────────────────

    def _open_path(self, path: str) -> None:
        if not path:
            return
        try:
            text = self.app.vfs.read_text(path)
            lang = self._detect_language(path)
            for tid, info in self._tabs.items():
                if info["path"] == path:
                    self.query_one("#editor-tabs", TabbedContent).active = tid
                    self._update_statusbar()
                    return
            self._tab_count += 1
            tab_id = f"editor-tab-{self._tab_count}"
            ta_id  = f"editor-ta-{self._tab_count}"
            self._tabs[tab_id] = {
                "path": path, "textarea_id": ta_id,
                "language": lang, "dirty": False,
            }
            self._last_texts[tab_id] = text
            ta = TextArea(text, id=ta_id, show_line_numbers=True, language=lang)
            tc = self.query_one("#editor-tabs", TabbedContent)
            tc.add_pane(TabPane(path, ta, id=tab_id))
            tc.active = tab_id
            ta.focus()
            self._update_statusbar()
        except Exception as e:
            self.notify(str(e), severity="error")

    def action_open_file(self) -> None:
        self.app.push_screen(
            _FilePickerModal("Open File", mode="open", start_path="/home"),
            callback=self._open_path,
        )

    def action_save(self) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        tab_id = tc.active
        if not tab_id or tab_id not in self._tabs:
            self.notify("No file open.", severity="warning")
            return
        info = self._tabs[tab_id]
        ta = self._active_ta()
        if not ta:
            return
        path = info["path"]
        if "untitled" in path:
            self.app.push_screen(
                _FilePickerModal("Save As", mode="save", start_path="/home"),
                callback=lambda p: self._save_to(p, ta.text)
            )
            return
        try:
            self.app.vfs.write_text(path, ta.text)
            info["dirty"] = False
            self._last_texts[tab_id] = ta.text
            self.notify("Saved!", severity="information")
        except Exception as e:
            self.notify(str(e), severity="error")

    def _save_to(self, path: str, text: str) -> None:
        if not path:
            return
        try:
            self.app.vfs.write_text(path, text)
            tc = self.query_one("#editor-tabs", TabbedContent)
            if tc.active and tc.active in self._tabs:
                self._tabs[tc.active]["path"] = path
                self._tabs[tc.active]["dirty"] = False
                self._last_texts[tc.active] = text
            self.notify("Saved!", severity="information")
            self._refresh_file_tree()
        except Exception as e:
            self.notify(str(e), severity="error")

    def action_new_file(self) -> None:
        self._tab_count += 1
        tab_id = f"editor-tab-{self._tab_count}"
        path   = f"untitled-{self._tab_count}.py"
        lang   = self._detect_language(path)
        ta_id  = f"editor-ta-{self._tab_count}"
        self._tabs[tab_id] = {
            "path": path, "textarea_id": ta_id,
            "language": lang, "dirty": False,
        }
        self._last_texts[tab_id] = ""
        tc = self.query_one("#editor-tabs", TabbedContent)
        ta = TextArea("", id=ta_id, show_line_numbers=True, language=lang)
        tc.add_pane(TabPane(path, ta, id=tab_id))
        tc.active = tab_id
        ta.focus()
        self._update_statusbar()

    # ── Find & Replace ──────────────────────────────────────────────────

    def action_find_replace(self) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        if tc.active:
            self.app.push_screen(
                _FindReplaceModal(tc.active),
                callback=self._on_find_replace,
            )

    def _on_find_replace(self, result: dict | None) -> None:
        if not result:
            return
        ta = self._active_ta()
        if not ta:
            return
        bid, (find, repl) = next(iter(result.items()))
        text = ta.text
        if bid == "fr-find-next":
            sel = ta.selection
            start = sel.end if sel else 0
            idx = text.find(find, start)
            if idx == -1:
                idx = text.find(find)
            if idx >= 0:
                ta.selection = ((idx, 0), (idx + len(find), 0))
                ta.cursor_location = (idx + len(find), 0)
                self.notify(f"Found at position {idx}", severity="information")
            else:
                self.notify("Not found.", severity="warning")
        elif bid == "fr-replace-one":
            sel = ta.selection
            if sel and text[sel.start:sel.end] == find:
                ta.text = text[:sel.start] + repl + text[sel.end:]
                self.notify("Replaced.", severity="information")
            else:
                self.notify("Select match first.", severity="warning")
        elif bid == "fr-replace-all":
            ta.text = text.replace(find, repl)
            self.notify("Replaced all occurrences.", severity="information")

    # ── Theme switching ──────────────────────────────────────────────────

    def _apply_theme(self, theme_name: str) -> None:
        self._theme = theme_name
        cfg = _THEMES.get(theme_name, _THEMES["Ocean Dark"])
        try:
            for tid, info in self._tabs.items():
                ta_id = info["textarea_id"]
                try:
                    ta = self.query_one(f"#{ta_id}", TextArea)
                    ta.styles.background = cfg["bg"]
                    ta.styles.color = cfg["fg"]
                except NoMatches:
                    pass
            self.notify(f"Theme: {theme_name}", severity="information")
        except Exception:
            pass

    # ── Jedi integration ─────────────────────────────────────────────────

    def _jedi_completions(self, path: str, source: str, line: int, col: int) -> list[tuple[str, str]]:
        if not _HAS_JEDI or not path.endswith(".py") or not source.strip():
            return []
        try:
            real = self._vfs_to_real(path)
            script = jedi.Script(source, path=real if os.path.exists(os.path.dirname(real)) else None)
            completions = script.completions(line + 1, col)
            return [(c.name, c.type) for c in completions[:20]]
        except Exception:
            return []

    def _show_autocomplete(self, completions: list[tuple[str, str]]) -> None:
        if not completions:
            return
        self.app.push_screen(
            _AutoCompleteModal(completions),
            callback=self._on_completion_selected,
        )

    def _on_completion_selected(self, name: str | None) -> None:
        if not name:
            return
        ta = self._active_ta()
        if not ta:
            return
        line, col = ta.cursor_location
        text = ta.text
        lines = text.split("\n")
        cur_line = lines[line]
        start = col
        while start > 0 and (cur_line[start - 1].isalnum() or cur_line[start - 1] == "_"):
            start -= 1
        prefix = cur_line[start:col]
        if prefix or (col > 0 and cur_line[col - 1:col] == "."):
            lines[line] = cur_line[:start] + name
            ta.text = "\n".join(lines)
            ta.cursor_location = (line, start + len(name))

    async def _do_autocomplete(self, path: str, source: str, line: int, col: int) -> None:
        await asyncio.sleep(0.25)
        completions = await asyncio.to_thread(self._jedi_completions, path, source, line, col)
        if completions:
            self._show_autocomplete(completions)

    def action_goto_definition(self) -> None:
        ta = self._active_ta()
        if not ta or not _HAS_JEDI:
            self.notify("Jedi not available", severity="warning")
            return
        tc = self.query_one("#editor-tabs", TabbedContent)
        info = self._tabs.get(tc.active, {})
        path = info.get("path", "")
        if not path.endswith(".py"):
            self.notify("Python files only", severity="warning")
            return
        try:
            real = self._vfs_to_real(path)
            line, col = ta.cursor_location
            script = jedi.Script(ta.text, path=real if os.path.exists(os.path.dirname(real)) else None)
            defs = script.goto_definitions(line + 1, col)
            if defs:
                d = defs[0]
                self.notify(f"{d.name}: {d.description}", severity="information")
                if d.line:
                    ta.cursor_location = (d.line - 1, d.column or 0)
            else:
                self.notify("No definition found", severity="warning")
        except Exception as e:
            self.notify(str(e), severity="error")

    # ── Git integration ──────────────────────────────────────────────────

    def action_git_status(self) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        info = self._tabs.get(tc.active, {})
        path = info.get("path", "")
        wd = self._git_dir(path) if path else None
        if not wd:
            self.notify("Not a git repository", severity="warning")
            return
        self.app.push_screen(_GitStatusModal(wd))

    def action_git_commit(self) -> None:
        tc = self.query_one("#editor-tabs", TabbedContent)
        info = self._tabs.get(tc.active, {})
        path = info.get("path", "")
        wd = self._git_dir(path) if path else None
        if not wd:
            self.notify("Not a git repository", severity="warning")
            return
        self.app.push_screen(_GitCommitModal(wd))

    # ── Text change → autocomplete + statusbar ──────────────────────────

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_statusbar()
        tc = self.query_one("#editor-tabs", TabbedContent)
        if not tc.active or tc.active not in self._tabs:
            return
        ta = self._active_ta()
        if not ta:
            return
        info = self._tabs.get(tc.active, {})
        path = info.get("path", "")
        if not path.endswith(".py") or not _HAS_JEDI:
            return
        if self._last_texts.get(tc.active) == ta.text:
            return
        self._last_texts[tc.active] = ta.text
        line, col = ta.cursor_location
        if self._autocomplete_task:
            self._autocomplete_task.cancel()
        self._autocomplete_task = asyncio.create_task(
            self._do_autocomplete(path, ta.text, line, col)
        )

    # ── Button handler ───────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":   self.dismiss(); return
        if bid == "btn-save":    self.action_save(); return
        if bid == "btn-open":    self.action_open_file(); return
        if bid == "btn-new":     self.action_new_file(); return
        if bid == "btn-find":    self.action_find_replace(); return
        if bid == "btn-theme":
            themes = list(_THEMES.keys())
            cur = themes.index(self._theme) if self._theme in themes else 0
            next_theme = themes[(cur + 1) % len(themes)]
            self._apply_theme(next_theme)


EditorWindow = BradTextEditor  # backward compat alias


# ═══════════════════════════════════════════════════════════════════════════════
# MAIL WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MailWindow(BradWindow):
    APP_ID: ClassVar[str] = "mail"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]
    _folder: str = "inbox"
    _sel:    int = -1

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⊠  BradMail", classes="win-title")
            yield Static("", id="mail-status", classes="win-title")
            yield Button("✉ Compose", id="btn-compose", classes="btn-primary")
            yield Button("⚙", id="btn-mail-settings", classes="btn-min")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            with Vertical(id="mail-left"):
                for fid, label in [("inbox","📥 Inbox"), ("sent","📤 Sent"),
                                    ("drafts","📝 Drafts"), ("trash","🗑 Trash")]:
                    yield Button(label, id=f"folder-{fid}", classes="folder-btn" +
                                 (" active" if fid == "inbox" else ""))

            with Vertical(id="mail-mid"):
                yield DataTable(id="mail-table", cursor_type="row")

            with ScrollableContainer(id="mail-right"):
                yield Static("[#7f8c8d]Select a message.[/]", id="mail-view")

        with Horizontal(id="mail-actions"):
            yield Button("↩ Reply",   id="btn-reply",  classes="btn-success")
            yield Button("⭐ Star",    id="btn-star")
            yield Button("🗑 Delete",  id="btn-delete", classes="btn-danger")
            yield Button("📥 Fetch",   id="btn-fetch",  classes="btn-primary")

    def on_mount(self) -> None:
        t = self.query_one("#mail-table", DataTable)
        t.add_columns("", "From/To", "Subject", "Date")
        self._update_server_status()
        self._load_folder("inbox")

    def _update_server_status(self) -> None:
        try:
            ms = get_mail_server()
            st = ms.status()
            if st.running:
                self.query_one("#mail-status", Static).update("[#2ed573]●[/]")
            else:
                self.query_one("#mail-status", Static).update("[#ff4757]●[/]")
        except Exception:
            self.query_one("#mail-status", Static).update("[#7f8c8d]○[/]")

    def _load_folder(self, folder: str) -> None:
        self._folder = folder
        self._sel    = -1
        self._render_table(folder)

    def _render_table(self, folder: str) -> None:
        t = self.query_one("#mail-table", DataTable)
        t.clear()
        msgs = self.app.user_profile.get("mail_folders", {}).get(folder, [])
        key  = "from" if folder == "inbox" else "to"
        for m in msgs:
            star = "⭐" if m.get("starred") else " "
            t.add_row(star, m.get(key,"?")[:16], m.get("subject","")[:28], m.get("date","")[:10])
        for fid in ["inbox","sent","drafts","trash"]:
            try:
                btn = self.query_one(f"#folder-{fid}", Button)
                if fid == folder: btn.add_class("active")
                else:             btn.remove_class("active")
            except NoMatches: pass
        self.query_one("#mail-view", Static).update("[#7f8c8d]Select a message.[/]")

    @on(DataTable.RowHighlighted, "#mail-table")
    def _view(self, event: DataTable.RowHighlighted) -> None:
        idx  = event.cursor_row
        msgs = self.app.user_profile.get("mail_folders", {}).get(self._folder, [])
        if 0 <= idx < len(msgs):
            self._sel = idx
            m = msgs[idx]
            self.query_one("#mail-view", Static).update(
                f"[bold #00d4ff]From:[/]    [#ecf0f1]{m.get('from','?')}[/]\n"
                f"[bold #00d4ff]To:[/]      [#ecf0f1]{m.get('to','?')}[/]\n"
                f"[bold #00d4ff]Subject:[/] [#ecf0f1]{m.get('subject','')}[/]\n"
                f"[bold #00d4ff]Date:[/]    [#7f8c8d]{m.get('date','')}[/]\n"
                f"[#1e3a5f]{'─' * 48}[/]\n\n"
                f"[#ecf0f1]{m.get('body','')}[/]"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":    self.dismiss(); return
        if bid == "btn-compose":  self.app.push_screen(_ComposeModal()); return
        if bid == "btn-mail-settings":
            settings = self.app.user_profile.get("mail_settings", {})
            self.app.push_screen(
                _MailSettingsModal(
                    email=settings.get("email", ""),
                    password=settings.get("password", ""),
                ),
                callback=self._on_settings_dismiss,
            )
            return
        if bid == "btn-fetch":
            self._fetch_imap(self._folder)
            return
        folder_map = {"folder-inbox":"inbox","folder-sent":"sent",
                      "folder-drafts":"drafts","folder-trash":"trash"}
        if bid in folder_map:
            self._load_folder(folder_map[bid]); return
        msgs = self.app.user_profile.get("mail_folders", {}).get(self._folder, [])
        if not (0 <= self._sel < len(msgs)):
            self.notify("Select a message first.", severity="warning"); return
        if bid == "btn-star":
            msgs[self._sel]["starred"] = not msgs[self._sel].get("starred")
            save_user_profile(self.app.user_profile)
            self._render_table(self._folder)
        elif bid == "btn-delete":
            msgs.pop(self._sel)
            save_user_profile(self.app.user_profile)
            self._render_table(self._folder)
            self.notify("Deleted.", severity="information")
        elif bid == "btn-reply":
            m = msgs[self._sel]
            self.app.push_screen(_ComposeModal(
                to=m.get("from",""), subject=f"Re: {m.get('subject','')}",
                body=f"\n\n--- Original ---\n{m.get('body','')}"
            ))

    def _on_settings_dismiss(self, result: dict | None) -> None:
        if result:
            self.app.user_profile["mail_settings"] = result
            save_user_profile(self.app.user_profile)
            self._update_server_status()
            self.notify("Mail settings saved.", severity="information")

    @work(thread=True)
    async def _fetch_imap(self, folder: str) -> None:
        settings = self.app.user_profile.get("mail_settings", {})
        if not settings.get("email") or not settings.get("password"):
            self.notify("Configure mail settings first (⚙ button).", severity="warning")
            return
        try:
            ms = get_mail_server()
            if not ms.status().running:
                self.notify("Mail server not running.", severity="error")
                return
        except Exception:
            self.notify("Mail server unavailable.", severity="error")
            return

        imap_folder = {"inbox": "INBOX", "sent": "Sent",
                       "drafts": "Drafts", "trash": "Trash"}.get(folder, "INBOX")
        imap_host = settings.get("imap_host", "127.0.0.1")
        imap_port = settings.get("imap_port", 143)

        try:
            import imaplib
            import email as email_lib
            from email.header import decode_header
        except ImportError:
            self.notify("imaplib not available.", severity="error")
            return

        def _decode(s: str | None) -> str:
            if not s:
                return ""
            parts = decode_header(s)
            return " ".join(
                p.decode(charset or "utf-8", errors="replace")
                if isinstance(p, bytes) else str(p)
                for p, charset in parts
            )

        def _get_body(msg: object) -> str:
            try:
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                return payload.decode(errors="replace")
                    return ""
                payload = msg.get_payload(decode=True)
                return payload.decode(errors="replace") if payload else ""
            except Exception:
                return ""

        fetched: list[dict] = []
        try:
            mail = imaplib.IMAP4(imap_host, imap_port)
            mail.login(settings["email"], settings["password"])
            mail.select(imap_folder)
            _typ, data = mail.search(None, "ALL")
            for num in data[0].split():
                _typ, msg_data = mail.fetch(num, "(RFC822)")
                raw = msg_data[0][1] if msg_data else b""
                if not raw:
                    continue
                msg = email_lib.message_from_bytes(raw)
                fetched.append({
                    "from":    _decode(msg.get("From")),
                    "to":      _decode(msg.get("To")),
                    "subject": _decode(msg.get("Subject")),
                    "date":    msg.get("Date", ""),
                    "body":    _get_body(msg),
                    "starred": False,
                })
            mail.logout()
        except Exception as e:
            self.app.call_from_thread(
                self.notify, f"IMAP fetch failed: {e}", severity="error"
            )
            return

        # Cache fetched messages in user profile
        self.app.user_profile.setdefault("mail_folders", {}).setdefault(folder, [])
        # Merge: replace cache with fresh fetch, preserving starred flags
        old = {m.get("subject", "") + m.get("date", ""): m
               for m in self.app.user_profile["mail_folders"].get(folder, [])}
        for m in fetched:
            key = m.get("subject", "") + m.get("date", "")
            if key in old and old[key].get("starred"):
                m["starred"] = True
        self.app.user_profile["mail_folders"][folder] = fetched
        save_user_profile(self.app.user_profile)

        self.app.call_from_thread(self._render_table, folder)
        self.app.call_from_thread(
            self.notify, f"Fetched {len(fetched)} messages.", severity="information"
        )


class _ComposeModal(ModalScreen):
    def __init__(self, to="", subject="", body=""):
        super().__init__()
        self._to, self._subject, self._body = to, subject, body

    def compose(self) -> ComposeResult:
        with Container(id="login-box"):
            yield Static("✉  Compose Message", id="login-logo")
            with Horizontal(classes="lfield"):
                yield Label("To:", classes="llabel")
                with Container(classes="linput"):
                    yield Input(self._to, id="c-to", placeholder="user@domain")
            with Horizontal(classes="lfield"):
                yield Label("Subject:", classes="llabel")
                with Container(classes="linput"):
                    yield Input(self._subject, id="c-sub")
            yield TextArea(self._body, id="c-body")
            with Horizontal(id="login-btns"):
                yield Button("Send",   id="btn-send",   classes="btn-primary")
                yield Button("Cancel", id="btn-cancel", classes="btn-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel": self.dismiss(); return
        to   = self.query_one("#c-to",  Input).value.strip()
        sub  = self.query_one("#c-sub", Input).value.strip()
        body = self.query_one("#c-body", TextArea).text
        if not to: self.notify("Recipient required.", severity="error"); return

        settings = self.app.user_profile.get("mail_settings", {})
        ms       = None
        try:
            ms = get_mail_server()
        except Exception:
            pass

        sent_ok = False
        if ms and ms.status().running and settings.get("email") and settings.get("password"):
            from_addr = settings["email"]
            smtp_host = settings.get("smtp_host", "127.0.0.1")
            smtp_port = settings.get("smtp_port", 587)
            try:
                import smtplib
                from email.mime.text import MIMEText
                msg = MIMEText(body)
                msg["Subject"] = sub
                msg["From"]    = from_addr
                msg["To"]      = to
                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(settings["email"], settings["password"])
                    server.sendmail(from_addr, [to], msg.as_string())
                sent_ok = True
            except Exception as e:
                self.notify(f"SMTP failed ({e}), falling back to local delivery.",
                            severity="warning")

        if not sent_ok:
            msg = {"from": self.app.user_profile["username"], "to": to,
                   "subject": sub, "body": body,
                   "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "starred": False}
            self.app.user_profile["mail_folders"]["sent"].append(msg)
            if to.lower() == self.app.user_profile["username"].lower():
                self.app.user_profile["mail_folders"]["inbox"].append(msg)
            else:
                op = get_profile_path(to)
                if os.path.exists(op):
                    from brados_system import load_user_profile as lup
                    other = lup(to)
                    other.setdefault("mail_folders", {}).setdefault("inbox", []).append(msg)
                    save_user_profile(other)
            save_user_profile(self.app.user_profile)

        self.notify(f"Sent to {to}!", severity="information")
        self.dismiss()


class _MailSettingsModal(ModalScreen):
    def __init__(self, email: str = "", password: str = ""):
        super().__init__()
        self._email = email
        self._password = password

    def compose(self) -> ComposeResult:
        with Container(id="login-box"):
            yield Static("⚙  Mail Server Settings", id="login-logo")
            with Horizontal(classes="lfield"):
                yield Label("Email:", classes="llabel")
                with Container(classes="linput"):
                    yield Input(self._email, id="ms-email", placeholder="user@brados.local")
            with Horizontal(classes="lfield"):
                yield Label("Password:", classes="llabel")
                with Container(classes="linput"):
                    yield Input(self._password, id="ms-password", password=True, placeholder="••••••••")
            with Horizontal(classes="lfield"):
                yield Label("IMAP Host:", classes="llabel")
                with Container(classes="linput"):
                    yield Input("127.0.0.1", id="ms-imap-host", placeholder="127.0.0.1")
            with Horizontal(classes="lfield"):
                yield Label("SMTP Host:", classes="llabel")
                with Container(classes="linput"):
                    yield Input("127.0.0.1", id="ms-smtp-host", placeholder="127.0.0.1")
            with Horizontal(classes="lfield"):
                yield Label("SMTP Port:", classes="llabel")
                with Container(classes="linput"):
                    yield Input("587", id="ms-smtp-port", placeholder="587")
            with Horizontal(id="login-btns"):
                yield Button("Save",   id="ms-save",   classes="btn-primary")
                yield Button("Cancel", id="ms-cancel", classes="btn-danger")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ms-cancel":
            self.dismiss(None)
            return
        email    = self.query_one("#ms-email",      Input).value.strip()
        password = self.query_one("#ms-password",   Input).value.strip()
        imap_host= self.query_one("#ms-imap-host",  Input).value.strip() or "127.0.0.1"
        smtp_host= self.query_one("#ms-smtp-host",  Input).value.strip() or "127.0.0.1"
        try:
            smtp_port = int(self.query_one("#ms-smtp-port", Input).value.strip() or "587")
        except ValueError:
            self.notify("SMTP port must be a number.", severity="error")
            return
        if not email or not password:
            self.notify("Email and password are required.", severity="error")
            return
        self.dismiss({
            "email": email, "password": password,
            "imap_host": imap_host, "imap_port": 143,
            "smtp_host": smtp_host, "smtp_port": smtp_port,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# CALCULATOR WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class CalculatorWindow(BradWindow):
    APP_ID: ClassVar[str] = "calculator"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]
    _expr:  str       = ""
    _res:   str       = "0"
    _hist:  list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⌗  Calculator", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Vertical(id="calc-display"):
            yield Static("", id="calc-expr")
            yield Static("0", id="calc-result")

        yield ScrollableContainer(Static("", id="calc-hist-content"), id="calc-hist")

        _BTNS = [
            # (label, css_class, safe_id)
            ("C",  "clr", "c-C"),   ("±",  "op",  "c-pm"),  ("π",  "fn",  "c-pi"),  ("÷",  "op",  "c-div"),
            ("7",  "",    "c-7"),   ("8",  "",    "c-8"),   ("9",  "",    "c-9"),   ("×",  "op",  "c-mul"),
            ("4",  "",    "c-4"),   ("5",  "",    "c-5"),   ("6",  "",    "c-6"),   ("−",  "op",  "c-neg"),
            ("1",  "",    "c-1"),   ("2",  "",    "c-2"),   ("3",  "",    "c-3"),   ("+",  "op",  "c-add"),
            ("sin","fn",  "c-sin"), ("cos","fn",  "c-cos"), ("√",  "fn",  "c-sqrt"),("=",  "eq",  "c-eq"),
            ("0",  "",    "c-0"),   (".",  "",    "c-dot"), ("⌫",  "clr", "c-del"), ("^",  "op",  "c-pow"),
        ]
        with Vertical(id="calc-grid"):
            rows = [_BTNS[i:i+4] for i in range(0, len(_BTNS), 4)]
            for row in rows:
                with Horizontal(classes="calc-row"):
                    for lbl, cls, bid in row:
                        yield Button(lbl, id=bid, classes=f"cbtn {cls}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-min":
            self.post_message(MinimizeApp("calculator"))
            self.dismiss(); return
        if event.button.id == "btn-close": self.dismiss(); return
        if event.button.id and event.button.id.startswith("c-"):
            self._key(event.button.label.plain.strip())

    def on_key(self, event) -> None:
        ch = event.character
        if ch and ch in "0123456789.+-*/^()": self._key(ch)
        elif event.key == "enter":     self._key("=")
        elif event.key == "backspace": self._key("⌫")

    def _key(self, k: str) -> None:
        if k == "C":     self._expr = ""; self._res = "0"
        elif k == "⌫":   self._expr = self._expr[:-1]
        elif k == "=":   self._calc(); return
        elif k == "±":   self._expr = f"-({self._expr})" if self._expr else ""
        elif k == "π":   self._expr += str(math.pi)
        elif k == "√":   self._expr = f"sqrt({self._expr})"
        elif k == "sin": self._expr = f"sin({self._expr})"
        elif k == "cos": self._expr = f"cos({self._expr})"
        elif k == "×":   self._expr += "*"
        elif k == "÷":   self._expr += "/"
        elif k == "−":   self._expr += "-"
        elif k == "^":   self._expr += "**"
        else:            self._expr += k
        self._upd()

    def _calc(self) -> None:
        try:
            s = self._expr.replace("pi", str(math.pi)).replace("e", str(math.e))
            r = safe_eval(s)
            rs = str(int(r)) if isinstance(r, float) and r.is_integer() else f"{r:.10g}"
            self._hist.append(f"{self._expr} = {rs}")
            if len(self._hist) > 20: self._hist.pop(0)
            self._expr = rs; self._res = rs
        except Exception as ex:
            self._res  = f"Err: {ex}"; self._expr = ""
        self._upd()
        self._upd_hist()

    def _upd(self) -> None:
        try:
            self.query_one("#calc-expr",   Static).update(f"[#7f8c8d]{self._expr or ' '}[/]")
            self.query_one("#calc-result", Static).update(f"[bold #2ed573]{self._res}[/]")
        except NoMatches: pass

    def _upd_hist(self) -> None:
        try:
            txt = "\n".join(f"[#7f8c8d]{h}[/]" for h in reversed(self._hist[-6:])) \
                  or "[#1e3a5f]No history[/]"
            self.query_one("#calc-hist-content", Static).update(txt)
        except NoMatches: pass


# ═══════════════════════════════════════════════════════════════════════════════
# MONITOR WINDOW  (htop-lite)
# ═══════════════════════════════════════════════════════════════════════════════

class MonitorWindow(BradWindow):
    APP_ID: ClassVar[str] = "monitor"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⊞  System Monitor", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Container(id="monitor-grid"):
            yield Static("", id="mon-cpu",  classes="monitor-card")
            yield Static("", id="mon-ram",  classes="monitor-card")
            yield Static("", id="mon-disk", classes="monitor-card")
            yield Static("", id="mon-net",  classes="monitor-card")

        yield DataTable(id="proc-table", cursor_type="row")

    def on_mount(self) -> None:
        t = self.query_one("#proc-table", DataTable)
        t.add_columns("PID", "Name", "CPU%", "Mem MB", "Status")
        self.set_interval(2, self._refresh)
        self._refresh()

    @work
    async def _refresh(self) -> None:
        # Collect all psutil data in thread pool; update widgets after await.
        cards, procs = await asyncio.to_thread(self._collect_stats)
        cpu_card, ram_card, disk_card, net_card = cards
        try:
            self.query_one("#mon-cpu",  Static).update(cpu_card)
            self.query_one("#mon-ram",  Static).update(ram_card)
            self.query_one("#mon-disk", Static).update(disk_card)
            self.query_one("#mon-net",  Static).update(net_card)
            t = self.query_one("#proc-table", DataTable)
            t.clear()
            for row in procs:
                t.add_row(*row)
        except NoMatches:
            pass

    @staticmethod
    def _collect_stats() -> tuple[tuple[str, str, str, str], list]:
        """Blocking – runs in thread pool. Returns (card_texts, proc_rows)."""
        try:
            import psutil                               # type: ignore

            def bar(v: float, w: int = 20) -> str:
                f = int(v * w / 100)
                c = "#2ed573" if v < 60 else ("#ffa502" if v < 85 else "#ff4757")
                return f"[{c}]{'█' * f}{'░' * (w - f)}[/] [{c}]{v:.1f}%[/]"

            cpu  = psutil.cpu_percent(interval=0.5)
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            net  = psutil.net_io_counters()

            cpu_card  = f"[bold #00d4ff]CPU[/]\n{bar(cpu)}\n[#7f8c8d]{platform.processor()[:32]}[/]"
            ram_card  = (f"[bold #00d4ff]RAM[/]\n{bar(mem.percent)}\n"
                         f"[#7f8c8d]{mem.used//(1024**2):,} / {mem.total//(1024**2):,} MB[/]")
            disk_card = (f"[bold #00d4ff]Disk[/]\n{bar(disk.percent)}\n"
                         f"[#7f8c8d]{disk.used//(1024**3):,} / {disk.total//(1024**3):,} GB[/]")
            net_card  = (f"[bold #00d4ff]Network[/]\n"
                         f"[#2ed573]↑ {net.bytes_sent//1024:,} KB[/]\n"
                         f"[#ffa502]↓ {net.bytes_recv//1024:,} KB[/]")

            # Cap at 15 rows to keep the table snappy
            procs: list[tuple] = []
            for p in sorted(
                psutil.process_iter(["pid", "name", "cpu_percent",
                                     "memory_info", "status"]),
                key=lambda x: x.info["cpu_percent"] or 0,
                reverse=True,
            )[:15]:
                pi     = p.info
                mem_mb = (pi["memory_info"].rss // (1024**2)) if pi.get("memory_info") else 0
                procs.append((
                    str(pi["pid"]), pi["name"][:24],
                    f"{pi['cpu_percent']:.1f}", str(mem_mb), pi["status"],
                ))
            return (cpu_card, ram_card, disk_card, net_card), procs

        except ImportError:
            msg = "[#ffa502]pip install psutil[/]"
            return (msg, msg, msg, msg), []

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close": self.dismiss()


# ═══════════════════════════════════════════════════════════════════════════════
# KERNEL WINDOW  (live task table)
# ═══════════════════════════════════════════════════════════════════════════════

class KernelWindow(BradWindow):
    APP_ID: ClassVar[str] = "kernel"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⧉  Kernel Task Table", classes="win-title")
            yield Button("⟳ Refresh", id="btn-refresh")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕",         id="btn-close", classes="win-close")

        yield DataTable(id="ktask-table", cursor_type="row")
        yield Static("", id="kernel-mounts")

    def on_mount(self) -> None:
        t = self.query_one("#ktask-table", DataTable)
        t.add_columns("PID", "Name", "User", "State", "CPU s", "Uptime s")
        self._refresh()

    def _refresh(self) -> None:
        kernel = self.app.kernel
        t      = self.query_one("#ktask-table", DataTable)
        t.clear()
        if kernel:
            for task in kernel.list_tasks():
                t.add_row(str(task["pid"]), task["name"], task["user"],
                          task["state"], str(task["cpu_s"]), str(task["uptime_s"]))
        else:
            t.add_row("—", "Kernel not attached", "", "", "", "")

        # VFS mounts
        vfs    = self.app.vfs
        mounts = vfs.mounts() if vfs else []
        txt    = "[bold #00d4ff]VFS Mounts:[/]\n"
        for m in mounts:
            txt += f"  [#00d4ff]{m['path']:<16}[/] [#7f8c8d]{m['driver']}[/]\n"
        if not mounts:
            txt += "  [#7f8c8d]No mounts[/]"

        # Driver table
        drivers = self.app.drivers.list_all() if self.app.drivers else []
        txt += "\n[bold #00d4ff]Drivers:[/]\n"
        for d in drivers:
            color = "#2ed573" if d.status == "active" else "#ffa502"
            txt  += f"  [{color}]●[/] [#ecf0f1]{d.name:<20}[/] [#7f8c8d]{d.version}  {d.status}[/]\n"

        try:
            self.query_one("#kernel-mounts", Static).update(txt)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh": self._refresh()
        if event.button.id == "btn-close":   self.dismiss()


# ═══════════════════════════════════════════════════════════════════════════════
# NOTES WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class NotesWindow(BradWindow):
    APP_ID: ClassVar[str] = "notes"
    BINDINGS: ClassVar = [
        Binding("ctrl+s", "save_note", "Save"),
        Binding("ctrl+n", "new_note",  "New"),
        Binding("escape", "dismiss",   "Close"),
    ]

    _notes:    list[dict] = []   # [{title, body, ts}]
    _sel:      int        = -1
    _vpath:    str        = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("✎  Notes", classes="win-title")
            yield Button("＋ New",    id="btn-new-note")
            yield Button("💾 Save",   id="btn-save-note", classes="btn-primary")
            yield Button("🗑 Delete",  id="btn-del-note",  classes="btn-danger")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕",         id="btn-close",     classes="win-close")

        with Horizontal():
            with ScrollableContainer(id="notes-list-pane"):
                yield ListView(id="notes-list")
            with Vertical(id="notes-edit-pane"):
                yield Input(placeholder="Title…", id="notes-title")
                yield TextArea("", id="notes-body", language="markdown")

    def on_mount(self) -> None:
        profile  = self.app.user_profile
        uname    = profile.get("username", "guest")
        self._vpath = f"/home/{uname}/notes.json"
        self._load_notes()

    def _load_notes(self) -> None:
        try:
            raw         = self.app.vfs.read_json(self._vpath)
            self._notes = raw if isinstance(raw, list) else []
        except Exception:
            self._notes = []
        self._rebuild_list()

    def _save_notes(self) -> None:
        try:
            self.app.vfs.makedirs(f"/home/{self.app.user_profile.get('username','guest')}")
            self.app.vfs.write_json(self._vpath, self._notes)
        except Exception as e:
            self.notify(str(e), severity="error")

    def _rebuild_list(self) -> None:
        lv = self.query_one("#notes-list", ListView)
        lv.clear()
        if not self._notes:
            lv.append(ListItem(Static("[#1e3a5f](no notes yet)[/]")))
            return
        for i, note in enumerate(self._notes):
            ts_str = datetime.fromtimestamp(note.get("ts", 0)).strftime("%d %b %H:%M")
            lv.append(ListItem(
                Static(f"[bold #ecf0f1]{note['title'][:22]}[/]\n[#7f8c8d]{ts_str}[/]"),
                id=f"note-{i}",
            ))

    @on(ListView.Selected, "#notes-list")
    def _select(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("note-"):
            idx = int(event.item.id[5:])
            if 0 <= idx < len(self._notes):
                self._sel = idx
                note = self._notes[idx]
                self.query_one("#notes-title", Input).value = note["title"]
                self.query_one("#notes-body",  TextArea).load_text(note["body"])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":     self.dismiss(); return
        if bid == "btn-new-note":  self.action_new_note(); return
        if bid == "btn-save-note": self.action_save_note(); return
        if bid == "btn-del-note":
            if 0 <= self._sel < len(self._notes):
                self._notes.pop(self._sel)
                self._sel = -1
                self._save_notes()
                self._rebuild_list()
                self.query_one("#notes-title", Input).value = ""
                self.query_one("#notes-body",  TextArea).load_text("")
                self.notify("Note deleted.", severity="information")

    def action_new_note(self) -> None:
        self._sel = -1
        self.query_one("#notes-title", Input).value = ""
        self.query_one("#notes-body",  TextArea).load_text("")
        self.query_one("#notes-title", Input).focus()

    def action_save_note(self) -> None:
        title = self.query_one("#notes-title", Input).value.strip()
        body  = self.query_one("#notes-body",  TextArea).text
        if not title:
            self.notify("Title required.", severity="warning"); return
        ts = datetime.now().timestamp()
        if 0 <= self._sel < len(self._notes):
            self._notes[self._sel].update({"title": title, "body": body, "ts": ts})
        else:
            self._notes.insert(0, {"title": title, "body": body, "ts": ts})
            self._sel = 0
        self._save_notes()
        self._rebuild_list()
        self.notify("Saved!", severity="information")


# ═══════════════════════════════════════════════════════════════════════════════
# CLOCK WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class ClockWindow(BradWindow):
    APP_ID: ClassVar[str] = "clock"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _sw_running:  bool  = False
    _sw_start:    float = 0.0
    _sw_elapsed:  float = 0.0
    _tm_running:  bool  = False
    _tm_end:      float = 0.0
    _tm_duration: float = 0.0

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("◷  Clock", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            # Left — world clock
            with Vertical(id="clock-left"):
                yield Static("", id="clock-main")
                yield Static("", id="clock-zones")

            # Right — stopwatch + timer
            with Vertical(id="clock-right"):
                yield Static("[bold #00d4ff]STOPWATCH[/]", classes="panel-heading")
                yield Static("00:00:00.0", id="sw-display")
                with Horizontal(id="sw-controls"):
                    yield Button("▶ Start",  id="btn-sw-start",  classes="btn-success")
                    yield Button("■ Stop",   id="btn-sw-stop")
                    yield Button("↺ Reset",  id="btn-sw-reset",  classes="btn-danger")

                yield Static("[bold #00d4ff]COUNTDOWN TIMER[/]", classes="panel-heading")
                with Horizontal(id="tm-input-row"):
                    yield Input("05:00", id="tm-input", placeholder="MM:SS")
                    yield Button("▶", id="btn-tm-start", classes="btn-success")
                    yield Button("■", id="btn-tm-stop")
                    yield Button("↺", id="btn-tm-reset", classes="btn-danger")
                yield Static("--:--", id="tm-display")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        now = datetime.now()
        # Main clock
        try:
            self.query_one("#clock-main", Static).update(
                f"[bold #00d4ff]{now.strftime('%H:%M:%S')}[/]\n"
                f"[#ecf0f1]{now.strftime('%A, %d %B %Y')}[/]"
            )
            # World clock (fixed zones via offset arithmetic — no pytz needed)
            utc_offset  = -time.timezone // 3600
            def tz_time(offset_h: int) -> str:
                import datetime as dt
                delta = dt.timedelta(hours=offset_h - utc_offset)
                t     = (now + delta).strftime("%H:%M")
                return t
            self.query_one("#clock-zones", Static).update(
                f"[#7f8c8d]UTC  [/][#ecf0f1]{tz_time(0)}[/]  "
                f"[#7f8c8d]EST  [/][#ecf0f1]{tz_time(-5)}[/]\n"
                f"[#7f8c8d]CET  [/][#ecf0f1]{tz_time(1)}[/]  "
                f"[#7f8c8d]JST  [/][#ecf0f1]{tz_time(9)}[/]"
            )
        except NoMatches:
            pass

        # Stopwatch
        try:
            elapsed = self._sw_elapsed
            if self._sw_running:
                elapsed += time.monotonic() - self._sw_start
            h, rem = divmod(elapsed, 3600)
            m, s   = divmod(rem, 60)
            self.query_one("#sw-display", Static).update(
                f"[bold #2ed573]{int(h):02d}:{int(m):02d}:{s:04.1f}[/]"
            )
        except NoMatches:
            pass

        # Timer
        try:
            if self._tm_running:
                remaining = max(0.0, self._tm_end - time.monotonic())
                if remaining == 0:
                    self._tm_running = False
                    self.notify("Timer finished!", severity="information")
            elif self._tm_duration > 0:
                remaining = self._tm_duration
            else:
                remaining = 0.0
            m2, s2 = divmod(remaining, 60)
            color = "#ff4757" if (self._tm_running and remaining < 10) else "#ffa502"
            self.query_one("#tm-display", Static).update(
                f"[bold {color}]{int(m2):02d}:{s2:04.1f}[/]"
                + ("  [#ff4757]▶ RUNNING[/]" if self._tm_running else "")
            )
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss()
        elif bid == "btn-sw-start":
            if not self._sw_running:
                self._sw_start   = time.monotonic()
                self._sw_running = True
        elif bid == "btn-sw-stop":
            if self._sw_running:
                self._sw_elapsed += time.monotonic() - self._sw_start
                self._sw_running  = False
        elif bid == "btn-sw-reset":
            self._sw_running  = False
            self._sw_elapsed  = 0.0
        elif bid == "btn-tm-start":
            raw = self.query_one("#tm-input", Input).value.strip()
            try:
                parts = raw.split(":")
                mins  = int(parts[0]); secs = float(parts[1]) if len(parts) > 1 else 0
                self._tm_duration = mins * 60 + secs
                self._tm_end      = time.monotonic() + self._tm_duration
                self._tm_running  = True
            except (ValueError, IndexError):
                self.notify("Format: MM:SS  e.g. 05:00", severity="warning")
        elif bid == "btn-tm-stop":
            if self._tm_running:
                self._tm_duration = max(0.0, self._tm_end - time.monotonic())
                self._tm_running  = False
        elif bid == "btn-tm-reset":
            self._tm_running  = False
            self._tm_duration = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# LOGS WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class LogsWindow(BradWindow):
    APP_ID: ClassVar[str] = "logs"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _filter: str = "all"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("≡  System Logs", classes="win-title")
            yield Button("⟳ Refresh", id="btn-refresh")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕",         id="btn-close",   classes="win-close")

        with Horizontal():
            with Vertical(id="logs-sidebar"):
                yield Static("[bold #00d4ff]Filter[/]", classes="panel-heading")
                for fid, label in [("all","All"), ("INFO","Info"),
                                   ("WARNING","Warn"), ("ERROR","Error")]:
                    yield Button(label, id=f"filter-{fid}",
                                 classes="folder-btn" + (" active" if fid=="all" else ""))

            with ScrollableContainer(id="logs-content"):
                yield RichLog(id="logs-view", highlight=False, markup=True)

        with Horizontal(id="editor-actions"):
            yield Static("", id="logs-count", classes="win-title")

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        log_view = self.query_one("#logs-view", RichLog)
        log_view.clear()
        lines_read = 0
        matched    = 0

        log_files = ["brados.log", "brados_kernel.log"]
        all_lines: list[str] = []

        for lf in log_files:
            try:
                with open(lf, encoding="utf-8", errors="replace") as f:
                    all_lines.extend(f.readlines())
            except FileNotFoundError:
                pass

        all_lines.sort()   # ISO timestamps sort lexicographically

        for line in all_lines[-500:]:     # last 500 lines
            lines_read += 1
            stripped = line.rstrip()
            if self._filter != "all" and f"[{self._filter}]" not in stripped:
                continue
            matched += 1
            if "[ERROR]" in stripped:
                log_view.write(f"[bold #ff4757]{stripped}[/]")
            elif "[WARNING]" in stripped:
                log_view.write(f"[#ffa502]{stripped}[/]")
            elif "[INFO]" in stripped:
                log_view.write(f"[#7f8c8d]{stripped}[/]")
            else:
                log_view.write(stripped)

        if lines_read == 0:
            log_view.write("[#1e3a5f]No log files found yet. Run some apps to generate logs.[/]")

        try:
            self.query_one("#logs-count", Static).update(
                f"[#7f8c8d]Showing {matched} / {lines_read} lines  "
                f"(filter: {self._filter})[/]"
            )
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":   self.dismiss(); return
        if bid == "btn-refresh": self._load(); return
        filter_map = {
            "filter-all": "all", "filter-INFO": "INFO",
            "filter-WARNING": "WARNING", "filter-ERROR": "ERROR",
        }
        if bid in filter_map:
            self._filter = filter_map[bid]
            # Update button states
            for fid in filter_map:
                try:
                    btn = self.query_one(f"#{fid}", Button)
                    if fid == bid: btn.add_class("active")
                    else:          btn.remove_class("active")
                except NoMatches:
                    pass
            self._load()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsWindow(BradWindow):
    APP_ID: ClassVar[str] = "settings"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _section: str = "profile"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⊕  Settings", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            # Sidebar
            with Vertical(id="mail-left"):
                yield Static("[bold #00d4ff]Settings[/]", classes="panel-heading")
                for sid, label in [
                    ("profile", "👤 Profile"),
                    ("display", "🖥 Display"),
                    ("drivers", "⚙ Drivers"),
                    ("system",  "ℹ System"),
                ]:
                    yield Button(label, id=f"section-{sid}",
                                 classes="folder-btn" + (" active" if sid=="profile" else ""))

            # Content panel
            with ScrollableContainer(id="mail-right"):
                yield Static("", id="settings-content")
                with Horizontal(id="settings-actions"):
                    yield Button("💾 Save", id="btn-save-settings", classes="btn-primary")
                    yield Button("📤 Export", id="btn-export-settings", classes="btn-success")
                    yield Button("📥 Import", id="btn-import-settings")

    def on_mount(self) -> None:
        self._render_section()

    def _render_section(self) -> None:
        p = self.app.user_profile
        if self._section == "profile":
            content = (
                f"[bold #00d4ff]User Profile[/]\n"
                f"[#1e3a5f]{'─' * 40}[/]\n\n"
                f"[#7f8c8d]Username:[/]   [#ecf0f1]{p.get('username','?')}[/]  [#1e3a5f](read-only)[/]\n"
                f"[#7f8c8d]Full name:[/]  [#ecf0f1]{p.get('full_name','?')}[/]\n"
                f"[#7f8c8d]Birthday:[/]   [#ecf0f1]{p.get('date_of_birth','?')}[/]\n"
                f"[#7f8c8d]Device:[/]     [#ecf0f1]{p.get('device_type','?')}[/]\n\n"
                f"[#7f8c8d]Inbox:[/]      [#ecf0f1]{len(p.get('mail_folders',{}).get('inbox',[]))} messages[/]\n"
                f"[#7f8c8d]Tasks:[/]      [#ecf0f1]{len(p.get('tasks',[]))} total, "
                f"{sum(1 for t in p.get('tasks',[]) if not t.get('done'))} pending[/]\n"
            )
        elif self._section == "display":
            drivers = self.app.drivers
            from brados_drivers import DisplayDriver
            disp = drivers.get(DisplayDriver) if drivers else None
            w, h   = (disp.ioctl(DisplayDriver.IOCTL_GET_SIZE)   if disp else (80, 24))
            colors = (disp.ioctl(DisplayDriver.IOCTL_GET_COLORS) if disp else 8)
            uni    = (disp.ioctl(DisplayDriver.IOCTL_GET_UNICODE) if disp else False)
            emoji  = (disp.ioctl(DisplayDriver.IOCTL_GET_EMOJI)  if disp else False)
            content = (
                f"[bold #00d4ff]Display[/]\n"
                f"[#1e3a5f]{'─' * 40}[/]\n\n"
                f"[#7f8c8d]Terminal size:[/]  [#ecf0f1]{w} × {h}[/]\n"
                f"[#7f8c8d]Color depth:[/]    [#ecf0f1]{colors:,} colors[/]\n"
                f"[#7f8c8d]Unicode:[/]        [#ecf0f1]{'✓ yes' if uni else '✗ no'}[/]\n"
                f"[#7f8c8d]Emoji:[/]          [#ecf0f1]{'✓ yes' if emoji else '✗ no'}[/]\n\n"
                f"[#7f8c8d]Theme:[/]          [#00d4ff]Ocean Dark[/]\n"
            )
        elif self._section == "drivers":
            drivers = self.app.drivers
            rows = drivers.list_all() if drivers else []
            lines = [
                f"[bold #00d4ff]Driver Registry[/]",
                f"[#1e3a5f]{'─' * 40}[/]\n",
            ]
            for d in rows:
                color = "#2ed573" if d.status == "active" else "#ffa502"
                lines.append(
                    f"  [{color}]●[/] [#ecf0f1]{d.name:<22}[/]"
                    f"[#7f8c8d]v{d.version}  {d.status}"
                    + (f"  {d.detail}" if d.detail else "") + "[/]"
                )
            content = "\n".join(lines)
        else:   # system
            import sys
            content = (
                f"[bold #00d4ff]System Information[/]\n"
                f"[#1e3a5f]{'─' * 40}[/]\n\n"
                f"[#7f8c8d]BradOS:[/]        [#ecf0f1]v3.0.0  Ocean Dark[/]\n"
                f"[#7f8c8d]Python:[/]        [#ecf0f1]{sys.version.split()[0]}[/]\n"
                f"[#7f8c8d]OS:[/]            [#ecf0f1]{platform.system()} {platform.release()}[/]\n"
                f"[#7f8c8d]Architecture:[/]  [#ecf0f1]{platform.machine()}[/]\n"
                f"[#7f8c8d]Hostname:[/]      [#ecf0f1]{platform.node()}[/]\n"
                f"[#7f8c8d]VFS mounts:[/]    [#ecf0f1]{len(self.app.vfs.mounts() if self.app.vfs else [])}[/]\n"
            )

        try:
            self.query_one("#settings-content", Static).update(content)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close": self.dismiss(); return

        section_map = {
            "section-profile": "profile",
            "section-display": "display",
            "section-drivers": "drivers",
            "section-system":  "system",
        }
        if bid in section_map:
            self._section = section_map[bid]
            for sid in section_map:
                try:
                    b = self.query_one(f"#{sid}", Button)
                    if sid == bid: b.add_class("active")
                    else:          b.remove_class("active")
                except NoMatches:
                    pass
            # Hide action buttons for non-profile sections
            try:
                save_btn = self.query_one("#btn-save-settings", Button)
                save_btn.display = (self._section == "profile")
            except NoMatches:
                pass
            try:
                self.query_one("#btn-export-settings", Button).display = (self._section == "profile")
            except NoMatches:
                pass
            try:
                self.query_one("#btn-import-settings", Button).display = (self._section == "profile")
            except NoMatches:
                pass
            self._render_section()
            return

        if bid == "btn-save-settings":
            self.notify("Profile editing coming soon — edit via brados.py for now.",
                        severity="information")
            return

        if bid == "btn-export-settings":
            self.app.push_screen(
                _FilePickerModal("Export Profile", mode="save",
                                 start_path="/home"),
                callback=self._export_profile,
            )
            return

        if bid == "btn-import-settings":
            self.app.push_screen(
                _FilePickerModal("Import Profile", mode="open",
                                 start_path="/home"),
                callback=self._import_profile,
            )

    def _export_profile(self, path: str) -> None:
        if not path:
            return
        try:
            self.app.vfs.write_json(path, self.app.user_profile)
            self.notify(f"Profile exported to {path}.", severity="information")
        except Exception as e:
            self.notify(f"Export failed: {e}", severity="error")

    def _import_profile(self, path: str) -> None:
        if not path:
            return
        try:
            data = self.app.vfs.read_json(path)
            if not isinstance(data, dict):
                self.notify("Invalid profile file.", severity="error")
                return
            self.app.user_profile.update(data)
            save_user_profile(self.app.user_profile)
            self._render_section()
            self.notify(f"Profile imported from {path}.", severity="information")
        except Exception as e:
            self.notify(f"Import failed: {e}", severity="error")


# ═══════════════════════════════════════════════════════════════════════════════
# BRADSEC WINDOW — real security dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class BradSecWindow(BradWindow):
    APP_ID: ClassVar[str] = "bradsec"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _section: str = "status"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⊛  BradSec — Security Center", classes="win-title")
            yield Button("—", id="btn-min",   classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            # Sidebar
            with Vertical(id="mail-left"):
                yield Static("[bold #ff4757]BradSec[/]", classes="panel-heading")
                for sid, label in [
                    ("status",    "⊛ Status"),
                    ("scan",      "⊞ Threat Scan"),
                    ("integrity", "≡ Integrity"),
                    ("audit",     "▤ Audit Log"),
                    ("vault",     "⌗ Vault"),
                    ("caps",      "⧉ Capabilities"),
                ]:
                    yield Button(
                        label, id=f"sec-{sid}",
                        classes="folder-btn" + (" active" if sid == "status" else ""),
                    )

            # Content
            with ScrollableContainer(id="mail-right"):
                yield RichLog(id="sec-content", markup=True, highlight=False)
                with Horizontal(id="editor-actions"):
                    yield Button("⟳ Refresh",    id="btn-sec-refresh", classes="btn-primary")
                    yield Button("⊞ Run Scan",    id="btn-sec-scan")
                    yield Button("≡ Verify Files",id="btn-sec-verify")
                    yield Button("■ Build Baseline", id="btn-sec-baseline")
                    yield Button("◉ Daemon",          id="btn-sec-daemon", variant="primary")

    def on_mount(self) -> None:
        super().on_mount()
        self._sec = get_bradsec()
        self._sec.start()
        self._daemon = get_bradsec_daemon()
        self._render_sec()

    def _render_sec(self) -> None:
        log = self.query_one("#sec-content", RichLog)
        log.clear()
        sec = self._sec

        if self._section == "status":
            st = sec.status()
            s_color = "#2ed573" if st["status"] == "active" else "#ff4757"
            dag = self._daemon
            d_running = dag.running
            d_color = "#2ed573" if d_running else "#ff4757"
            log.write(f"[bold {s_color}]● BradSec {st['status'].upper()}[/]\n")
            log.write(f"[bold {d_color}]◉ Daemon {'RUNNING' if d_running else 'STOPPED'}[/]  "
                      f"[#7f8c8d](Unix socket)[/]\n")
            log.write(f"[#00d4ff]Policy rules:[/]   [#ecf0f1]{len(dag.policy.rules)}[/]")
            log.write(f"[#00d4ff]File watcher:[/]   [#ecf0f1]{'ACTIVE' if d_running else 'OFF'}[/]")
            log.write(f"[#00d4ff]Session key:[/]    [#ecf0f1]{st['secret_bits']}-bit HMAC secret[/]")
            log.write(f"[#00d4ff]Active tokens:[/]  [#ecf0f1]{st['active_tokens']}[/]")
            log.write(f"[#00d4ff]Vault:[/]          [#ecf0f1]{'LOCKED' if st['vault_locked'] else 'UNLOCKED'}[/]")
            log.write(f"[#00d4ff]Baseline:[/]       [#ecf0f1]{'exists' if st['baseline_exists'] else 'not built — click Build Baseline'}[/]")
            log.write(f"[#00d4ff]Audit events:[/]   [#ecf0f1]{st['audit_events']:,}[/]")
            log.write(f"[#00d4ff]Scan interval:[/]  [#ecf0f1]every 300s[/]")
            log.write("")
            log.write("[bold #7f8c8d]Quick actions:[/]")
            log.write("  ⊞ Run Scan      — check permissions, ports, password hashes")
            log.write("  ≡ Verify Files  — compare against SHA-256 baseline")
            log.write("  ■ Build Baseline — create/refresh the integrity manifest")

        elif self._section == "scan":
            log.write("[bold #00d4ff]Running threat scan…[/]")
            findings = self._run_scan_cached()
            if not findings:
                log.write("[#2ed573]✓  No threats found.[/]")
            else:
                sev_color = {"LOW": "#7f8c8d", "MEDIUM": "#ffa502",
                             "HIGH": "#ff4757", "CRITICAL": "#ff0000"}
                for f in findings:
                    c = sev_color.get(f.severity, "#ecf0f1")
                    log.write(f"[{c}][{f.severity}][/] [{f.category}] [bold]{f.title}[/]")
                    log.write(f"       [#7f8c8d]{f.detail}[/]")
                    if f.path:
                        log.write(f"       [#1e3a5f]{f.path}[/]")
                    log.write("")

        elif self._section == "integrity":
            log.write("[bold #00d4ff]File Integrity Check[/]\n")
            findings = sec.verify_integrity()
            if not findings:
                log.write("[#2ed573]✓  All files match the baseline.[/]")
            else:
                type_color = {"MODIFIED": "#ff4757", "DELETED": "#ff0000",
                              "ADDED": "#ffa502"}
                for f in findings:
                    c = type_color.get(f.get("type",""), "#ecf0f1")
                    log.write(f"  [{c}]{f['type']:<12}[/] [#ecf0f1]{f['path']}[/]")
                    if "expected" in f:
                        log.write(f"    [#7f8c8d]expected {f['expected']}  got {f['actual']}[/]")

        elif self._section == "audit":
            log.write("[bold #00d4ff]Audit Log — last 30 events[/]\n")
            events = sec.audit.tail(30)
            if not events:
                log.write("[#7f8c8d]No events yet.[/]")
            level_color = {"INFO": "#7f8c8d", "WARNING": "#ffa502",
                           "ALERT": "#ff4757", "CRITICAL": "#ff0000"}
            for ev in reversed(events):
                c    = level_color.get(ev.get("level","INFO"), "#ecf0f1")
                ts   = ev.get("timestamp","")[:19].replace("T"," ")
                sub  = ev.get("subsystem","")
                evt  = ev.get("event","")
                log.write(f"[#1e3a5f]{ts}[/] [{c}]{ev.get('level',''):<8}[/] [#00d4ff]{sub:<12}[/] {evt}")

        elif self._section == "vault":
            log.write("[bold #00d4ff]Encrypted Vault[/]\n")
            locked = sec.vault._key is None
            if locked:
                log.write("[#ffa502]Vault is locked.[/]")
                log.write("[#7f8c8d]Use the terminal to unlock:")
                log.write("[#ecf0f1]  from brados_security import get_bradsec")
                log.write("[#ecf0f1]  get_bradsec().unlock_vault('your_password')[/]")
            else:
                keys = sec.vault.list_keys()
                log.write(f"[#2ed573]Vault is UNLOCKED — {len(keys)} secret(s)[/]\n")
                for k in keys:
                    log.write(f"  [#00d4ff]{k}[/]  [#7f8c8d](value hidden)[/]")

        elif self._section == "caps":
            log.write("[bold #00d4ff]Active Capability Tokens[/]\n")
            # Access the internal token table
            with sec._lock:
                tokens = dict(sec._tokens)
            if not tokens:
                log.write("[#7f8c8d]No active tokens.[/]")
            for pid, tok in tokens.items():
                exp = "EXPIRED" if tok.expired else "valid"
                c   = "#ff4757" if tok.expired else "#2ed573"
                log.write(f"  [{c}]●[/] pid=[#ecf0f1]{pid}[/] uid=[#ecf0f1]{tok.uid}[/]"
                          f" caps=[#ffa502]{tok.caps}[/] [{c}]{exp}[/]")
                cap_list = []
                for cap in Cap:
                    if cap != Cap.NONE and cap != Cap.ADMIN and tok.has(cap):
                        cap_list.append(cap.name)
                if cap_list:
                    log.write(f"    [#7f8c8d]{' · '.join(cap_list)}[/]")

    def _run_scan_cached(self):
        return self._sec.scan()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":      self.dismiss(); return
        if bid == "btn-sec-refresh":self._render_sec(); return

        if bid == "btn-sec-scan":
            self._section = "scan"
            self._render_sec()
            self.notify("Threat scan complete.", severity="information")
            return

        if bid == "btn-sec-verify":
            self._section = "integrity"
            self._render_sec()
            return

        if bid == "btn-sec-baseline":
            self._sec.integrity.build_baseline()
            self.notify("Integrity baseline built.", severity="information")
            self._render_sec()
            return

        if bid == "btn-sec-daemon":
            if self._daemon.running:
                self._daemon.stop()
                self.notify("Daemon stopped.", severity="warning")
            else:
                self._daemon.start()
                self.notify("Daemon started.", severity="information")
            self._render_sec()
            return

        section_map = {f"sec-{s}": s for s in
                       ["status","scan","integrity","audit","vault","caps"]}
        if bid in section_map:
            self._section = section_map[bid]
            for sid in section_map:
                try:
                    b = self.query_one(f"#{sid}", Button)
                    if sid == bid: b.add_class("active")
                    else:          b.remove_class("active")
                except NoMatches:
                    pass
            self._render_sec()


# ═══════════════════════════════════════════════════════════════════════════════
# BPKG WINDOW — package manager
# ═══════════════════════════════════════════════════════════════════════════════

class BpkgWindow(BradWindow):
    APP_ID: ClassVar[str] = "bpkg"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _view: str = "available"    # available | installed | search

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⬡  bpkg — Package Manager", classes="win-title")
            yield Button("—", id="btn-min",   classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            # Sidebar
            with Vertical(id="mail-left"):
                yield Static("[bold #00d4ff]bpkg[/]", classes="panel-heading")
                for vid, label in [
                    ("available",  "⬡ Available"),
                    ("installed",  "✓ Installed"),
                    ("search",     "⌕ Search"),
                ]:
                    yield Button(
                        label, id=f"view-{vid}",
                        classes="folder-btn" + (" active" if vid == self._view else ""),
                    )
                yield Static("")
                yield Static("[bold #7f8c8d]Filter[/]", classes="panel-heading")
                for cat in ["all","lib","app","dev","meta"]:
                    yield Button(cat.capitalize(), id=f"cat-{cat}",
                                 classes="folder-btn")

            # Main panel
            with Vertical(id="mail-mid"):
                with Horizontal(id="browser-nav"):
                    yield Input(placeholder="Search packages…", id="pkg-search-input")
                    yield Button("⌕", id="btn-search-go",  classes="btn-primary")
                    yield Button("⟳ Refresh registry", id="btn-registry-refresh")
                yield DataTable(id="pkg-table", cursor_type="row")

            # Detail panel
            with ScrollableContainer(id="mail-right"):
                yield Static("[#7f8c8d]Select a package.[/]", id="pkg-detail")
                with Horizontal(id="editor-actions"):
                    yield Button("⬇ Install",   id="btn-install",   classes="btn-success")
                    yield Button("⬆ Upgrade",   id="btn-upgrade")
                    yield Button("✕ Remove",     id="btn-remove",    classes="btn-danger")

        # Log at the bottom
        with Container(id="logs-content"):
            yield RichLog(id="pkg-log", markup=True, highlight=False)

    def on_mount(self) -> None:
        super().on_mount()
        self._mgr = get_bpkg()
        t = self.query_one("#pkg-table", DataTable)
        t.add_columns("Package", "Version", "Category", "Status")
        self._load_view()

    def _load_view(self, packages=None, cat_filter: str = "all") -> None:
        t   = self.query_one("#pkg-table", DataTable)
        t.clear()
        if packages is None:
            if self._view == "installed":
                pkgs = [self._mgr.registry.get(ip.name)
                        for ip in self._mgr.list_installed()
                        if self._mgr.registry.get(ip.name)]
            else:
                pkgs = self._mgr.registry.all_packages()
        else:
            pkgs = packages

        if cat_filter != "all":
            pkgs = [p for p in pkgs if p and p.category == cat_filter]

        for p in pkgs:
            if not p:
                continue
            installed = self._mgr.is_installed(p.name)
            status    = "[#2ed573]✓ installed[/]" if installed else "[#7f8c8d]—[/]"
            t.add_row(p.name, p.version, p.category, status)

    def _show_detail(self, name: str) -> None:
        p = self._mgr.registry.get(name)
        if not p:
            return
        installed = self._mgr.is_installed(name)
        status    = "[#2ed573]INSTALLED[/]" if installed else "[#7f8c8d]not installed[/]"
        text = (
            f"[bold #00d4ff]{p.name}[/]  [#7f8c8d]v{p.version}[/]  {status}\n\n"
            f"[#ecf0f1]{p.description}[/]\n\n"
            f"[#7f8c8d]Author:[/]   [#ecf0f1]{p.author}[/]\n"
            f"[#7f8c8d]Category:[/] [#ecf0f1]{p.category}[/]\n"
            f"[#7f8c8d]License:[/]  [#ecf0f1]{p.license}[/]\n"
            f"[#7f8c8d]Size:[/]     [#ecf0f1]~{p.size_kb:,} KB[/]\n"
            f"[#7f8c8d]pip deps:[/] [#ecf0f1]{', '.join(p.pip_deps) or '—'}[/]\n"
            f"[#7f8c8d]Tags:[/]     [#ecf0f1]{', '.join(p.tags) or '—'}[/]\n"
        )
        try:
            self.query_one("#pkg-detail", Static).update(text)
        except NoMatches:
            pass

    @on(DataTable.RowHighlighted, "#pkg-table")
    def _on_row(self, event: DataTable.RowHighlighted) -> None:
        try:
            cell = self.query_one("#pkg-table", DataTable).get_cell_at(
                event.cursor_row, 0)
            self._show_detail(str(cell))
        except Exception:
            pass

    def _selected_pkg(self) -> str | None:
        try:
            t   = self.query_one("#pkg-table", DataTable)
            row = t.cursor_row
            return str(t.get_cell_at(row, 0))
        except Exception:
            return None

    @work
    async def _do_install(self, name: str) -> None:
        log = self.query_one("#pkg-log", RichLog)
        log.write(f"[#00d4ff]⬇  Installing {name}…[/]")
        def emit(msg: str):
            self.app.call_from_thread(log.write, f"[#7f8c8d]{msg}[/]")
        result = await asyncio.to_thread(
            self._mgr.install, name, emit
        )
        if result.success:
            log.write(f"[#2ed573]✓  {name} installed in {result.duration:.1f}s[/]")
            self.notify(f"{name} installed!", severity="information")
        else:
            log.write(f"[#ff4757]✗  Install failed[/]")
            self.notify(f"Failed to install {name}", severity="error")
        self._load_view()

    @work
    async def _do_remove(self, name: str) -> None:
        log = self.query_one("#pkg-log", RichLog)
        log.write(f"[#ff4757]✕  Removing {name}…[/]")
        def emit(msg: str):
            self.app.call_from_thread(log.write, f"[#7f8c8d]{msg}[/]")
        result = await asyncio.to_thread(self._mgr.remove, name, emit)
        if result.success:
            log.write(f"[#2ed573]✓  {name} removed[/]")
            self.notify(f"{name} removed.", severity="information")
        else:
            log.write(f"[#ff4757]✗  Remove failed[/]")
        self._load_view()

    @work
    async def _do_registry_refresh(self) -> None:
        log = self.query_one("#pkg-log", RichLog)
        log.write("[#00d4ff]⟳  Fetching remote registry…[/]")
        def emit(msg: str):
            self.app.call_from_thread(log.write, f"[#7f8c8d]{msg}[/]")
        ok = await asyncio.to_thread(self._mgr.registry.fetch_remote, emit)
        if ok:
            log.write("[#2ed573]✓  Registry updated[/]")
        else:
            log.write("[#ffa502]Remote unavailable — built-in registry in use[/]")
        self._load_view()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close": self.dismiss(); return

        if bid == "btn-install":
            name = self._selected_pkg()
            if name: self._do_install(name)
            return

        if bid == "btn-remove":
            name = self._selected_pkg()
            if name: self._do_remove(name)
            return

        if bid == "btn-upgrade":
            name = self._selected_pkg()
            if not name: return
            self.query_one("#pkg-log", RichLog).write(
                f"[#00d4ff]⬆  Upgrading {name}…[/]")
            self._do_install(name)
            return

        if bid == "btn-search-go":
            q = self.query_one("#pkg-search-input", Input).value.strip()
            self._view = "search"
            self._load_view(self._mgr.search(q) if q else None)
            return

        if bid == "btn-registry-refresh":
            self._do_registry_refresh()
            return

        view_map = {"view-available": "available",
                    "view-installed": "installed",
                    "view-search":    "search"}
        if bid in view_map:
            self._view = view_map[bid]
            for vid in view_map:
                try:
                    b = self.query_one(f"#{vid}", Button)
                    if vid == bid: b.add_class("active")
                    else:          b.remove_class("active")
                except NoMatches:
                    pass
            self._load_view()
            return

        if bid and bid.startswith("cat-"):
            cat = bid[4:]
            self._load_view(cat_filter=cat)

    @on(Input.Submitted, "#pkg-search-input")
    def _on_search_enter(self) -> None:
        q = self.query_one("#pkg-search-input", Input).value.strip()
        self._view = "search"
        self._load_view(self._mgr.search(q) if q else None)


# ═══════════════════════════════════════════════════════════════════════════════
# PAINT WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class PaintWindow(BradWindow):
    APP_ID: ClassVar[str] = "paint"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _pixels: list[list[Static]] = []
    _color: str = "#00d4ff"

    _PALETTE = [
        "#00d4ff", "#ff4757", "#2ed573", "#ffa502",
        "#a855f7", "#ecf0f1", "#7f8c8d", "#060d17",
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🎨  Paint", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Horizontal():
            with Vertical(id="paint-palette"):
                yield Static("[bold #7f8c8d]Colors[/]", classes="panel-heading")
                for i in range(len(self._PALETTE)):
                    yield Button("  ", id=f"pal-{i}")
                yield Static("")
                yield Button("Clear", id="pal-clear", classes="btn-danger")
            with Vertical(id="paint-canvas"):
                for row in range(14):
                    with Horizontal(classes="pixel-row"):
                        for col in range(20):
                            yield Static(" ", classes="pixel", id=f"px-{row}-{col}")

    def on_mount(self) -> None:
        for i, color in enumerate(self._PALETTE):
            try:
                self.query_one(f"#pal-{i}", Button).styles.background = color
            except NoMatches:
                pass
        self._pixels = []
        for row in range(14):
            row_px = []
            for col in range(20):
                w = self.query_one(f"#px-{row}-{col}", Static)
                w.styles.background = "#060d17"
                w.styles.width = 1
                row_px.append(w)
            self._pixels.append(row_px)

    @on(Click, ".pixel")
    def _on_pixel_click(self, event: Click) -> None:
        if isinstance(event.widget, Static):
            event.widget.styles.background = self._color

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(); return
        if bid == "pal-clear":
            for row in self._pixels:
                for px in row:
                    px.styles.background = "#060d17"
            return
        if bid and bid.startswith("pal-"):
            idx = int(bid[4:])
            if 0 <= idx < len(self._PALETTE):
                self._color = self._PALETTE[idx]
            return


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERTER WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class ConverterWindow(BradWindow):
    APP_ID: ClassVar[str] = "converter"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _category: str = "length"
    _from_unit: str = "m"
    _to_unit: str = "km"

    _CATEGORIES = {
        "length": ["mm", "cm", "m", "km", "in", "ft", "yd", "mi"],
        "weight": ["mg", "g", "kg", "oz", "lb"],
        "temperature": ["celsius", "fahrenheit", "kelvin"],
        "data": ["B", "KB", "MB", "GB", "TB"],
    }

    _UNIT_DISPLAY = {
        "mm": "mm", "cm": "cm", "m": "m", "km": "km",
        "in": "in", "ft": "ft", "yd": "yd", "mi": "mi",
        "mg": "mg", "g": "g", "kg": "kg", "oz": "oz", "lb": "lb",
        "celsius": "°C", "fahrenheit": "°F", "kelvin": "K",
        "B": "B", "KB": "KB", "MB": "MB", "GB": "GB", "TB": "TB",
    }

    _UNIT_TO_BASE = {
        "mm": 0.001, "cm": 0.01, "m": 1, "km": 1000,
        "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
        "mg": 0.001, "g": 1, "kg": 1000, "oz": 28.3495, "lb": 453.592,
        "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4,
    }

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("⇄  Converter", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical():
            with Horizontal(id="conv-cats"):
                for i, cat in enumerate(["length", "weight", "temperature", "data"]):
                    yield Button(cat.capitalize(), id=f"cat-{cat}",
                                 classes="folder-btn" + (" active" if i == 0 else ""))
            with Horizontal(id="conv-input-row"):
                yield Input(value="1", id="conv-value")
                yield Button("⇄", id="conv-swap", classes="btn-primary")
                yield Static("", id="conv-result")
            with Horizontal(id="conv-units-row"):
                with Vertical(id="conv-from"):
                    yield Static("[bold #7f8c8d]From[/]", classes="panel-heading")
                    for units in self._CATEGORIES.values():
                        for unit in units:
                            yield Button(
                                self._UNIT_DISPLAY.get(unit, unit),
                                id=f"from-{unit}", classes="folder-btn")
                with Vertical(id="conv-to"):
                    yield Static("[bold #7f8c8d]To[/]", classes="panel-heading")
                    for units in self._CATEGORIES.values():
                        for unit in units:
                            yield Button(
                                self._UNIT_DISPLAY.get(unit, unit),
                                id=f"to-{unit}", classes="folder-btn")

    def on_mount(self) -> None:
        self._rebuild_visibility()
        self._convert()

    def _rebuild_visibility(self) -> None:
        for cat, units in self._CATEGORIES.items():
            show = cat == self._category
            for unit in units:
                try:
                    b = self.query_one(f"#from-{unit}", Button)
                    b.display = show
                    if unit == self._from_unit:
                        b.add_class("active")
                    else:
                        b.remove_class("active")
                except NoMatches:
                    pass
                try:
                    b = self.query_one(f"#to-{unit}", Button)
                    b.display = show
                    if unit == self._to_unit:
                        b.add_class("active")
                    else:
                        b.remove_class("active")
                except NoMatches:
                    pass
        for cat in self._CATEGORIES:
            try:
                b = self.query_one(f"#cat-{cat}", Button)
                if cat == self._category:
                    b.add_class("active")
                else:
                    b.remove_class("active")
            except NoMatches:
                pass

    def _convert(self) -> None:
        try:
            val = float(self.query_one("#conv-value", Input).value or "0")
        except ValueError:
            self.query_one("#conv-result", Static).update("[#ff4757]Invalid[/]")
            return
        try:
            res = self._compute(val, self._from_unit, self._to_unit)
            rs = f"{res:.10g}"
            display_unit = self._UNIT_DISPLAY.get(self._to_unit, self._to_unit)
            self.query_one("#conv-result", Static).update(
                f"[bold #2ed573]{rs} {display_unit}[/]")
        except Exception:
            self.query_one("#conv-result", Static).update("[#ff4757]Error[/]")

    def _compute(self, val: float, fu: str, tu: str) -> float:
        if fu in ("celsius", "fahrenheit", "kelvin"):
            if fu == "celsius":
                c = val
            elif fu == "fahrenheit":
                c = (val - 32) * 5 / 9
            else:
                c = val - 273.15
            if tu == "celsius":
                return c
            elif tu == "fahrenheit":
                return c * 9 / 5 + 32
            else:
                return c + 273.15
        base = val * self._UNIT_TO_BASE[fu]
        return base / self._UNIT_TO_BASE[tu]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(); return
        if bid == "conv-swap":
            self._from_unit, self._to_unit = self._to_unit, self._from_unit
            self._rebuild_visibility()
            self._convert()
            return
        if bid and bid.startswith("cat-"):
            cat = bid[4:]
            if cat in self._CATEGORIES:
                self._category = cat
                units = self._CATEGORIES[cat]
                self._from_unit = units[0]
                self._to_unit = units[1] if len(units) > 1 else units[0]
                self._rebuild_visibility()
                self._convert()
            return
        if bid and bid.startswith("from-"):
            self._from_unit = bid[5:]
            self._rebuild_visibility()
            self._convert()
            return
        if bid and bid.startswith("to-"):
            self._to_unit = bid[3:]
            self._rebuild_visibility()
            self._convert()
            return

    @on(Input.Submitted, "#conv-value")
    def _on_conv_enter(self) -> None:
        self._convert()

    @on(Input.Changed, "#conv-value")
    def _on_conv_change(self) -> None:
        self._convert()


# ═══════════════════════════════════════════════════════════════════════════════
# RSS FEED READER WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class RssWindow(BradWindow):
    APP_ID: ClassVar[str] = "rss"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _items: list[dict] = []
    _feed_url: str = ""

    _CLEANR = re.compile(r"<[^>]+>")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("◉  RSS Reader", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical():
            with Horizontal(id="browser-nav"):
                yield Input(placeholder="Feed URL…", id="rss-url")
                yield Button("Fetch", id="rss-fetch", classes="btn-primary")
            with Horizontal():
                with Vertical(id="mail-mid"):
                    yield DataTable(id="rss-table", cursor_type="row")
                with Vertical(id="mail-right"):
                    yield Static("[#7f8c8d]Select an item.[/]", id="rss-detail")
                    yield Button("Open in Browser", id="rss-open", classes="btn-success")

    def on_mount(self) -> None:
        t = self.query_one("#rss-table", DataTable)
        t.add_columns("Title", "Date")

    def _extract_tag(self, tag: str, text: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
        if m:
            content = m.group(1)
            cdata = re.search(r"<!\[CDATA\[(.*?)\]\]>", content, re.DOTALL)
            if cdata:
                return cdata.group(1).strip()
            return content.strip()
        return ""

    def _clean_html(self, html: str) -> str:
        return self._CLEANR.sub("", html).strip()

    def _fmt_date(self, raw: str) -> str:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(raw)
            return dt.strftime("%d %b %Y")
        except Exception:
            return raw[:16] if raw else ""

    def _fetch_feed(self, url: str) -> list[dict]:
        try:
            import requests
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            text = resp.text
        except ImportError:
            self.notify("Install requests: pip install requests", severity="error")
            return []
        except Exception as e:
            self.notify(f"Fetch failed: {e}", severity="error")
            return []
        items = []
        for item_match in re.finditer(
            r"<item>(.*?)</item>", text, re.IGNORECASE | re.DOTALL,
        ):
            raw = item_match.group(1)
            title = self._extract_tag("title", raw)
            link = self._extract_tag("link", raw)
            desc = self._clean_html(self._extract_tag("description", raw))
            pubdate = self._extract_tag("pubDate", raw)
            items.append({
                "title": title, "link": link,
                "description": desc, "pubdate": pubdate,
            })
        return items

    def _populate_table(self, items: list[dict]) -> None:
        t = self.query_one("#rss-table", DataTable)
        t.clear()
        for item in items:
            title = item.get("title", "")[:60]
            pubdate = self._fmt_date(item.get("pubdate", ""))
            t.add_row(title, pubdate)

    def _get_selected_url(self) -> str | None:
        try:
            t = self.query_one("#rss-table", DataTable)
            row = t.cursor_row
            title = str(t.get_cell_at(row, 0))
            for item in self._items:
                if item.get("title", "")[:60] == title:
                    return item.get("link", "")
        except Exception:
            pass
        return None

    @on(DataTable.RowHighlighted, "#rss-table")
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            title = str(self.query_one("#rss-table", DataTable).get_cell_at(
                event.cursor_row, 0))
            for item in self._items:
                if item.get("title", "")[:60] == title:
                    desc = item.get("description", "")
                    self.query_one("#rss-detail", Static).update(
                        f"[#7f8c8d]{desc[:500]}[/]")
                    return
        except Exception:
            pass

    def _nav_browser(self, url: str) -> None:
        try:
            inp = self.app.screen.query_one("#browser-url", Input)
            inp.value = url
            if hasattr(self.app.screen, "_navigate"):
                self.app.screen._navigate()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(); return
        if bid == "rss-fetch":
            url = self.query_one("#rss-url", Input).value.strip()
            if url:
                self._feed_url = url
                items = self._fetch_feed(url)
                self._items = items
                self._populate_table(items)
                self.notify(f"Loaded {len(items)} items.", severity="information")
            return
        if bid == "rss-open":
            url = self._get_selected_url()
            if url:
                self.app.push_screen(BrowserWindow())
                self.set_timer(0.05, lambda: self._nav_browser(url))
            return

    @on(Input.Submitted, "#rss-url")
    def _on_url_enter(self) -> None:
        url = self.query_one("#rss-url", Input).value.strip()
        if url:
            self._feed_url = url
            items = self._fetch_feed(url)
            self._items = items
            self._populate_table(items)
            self.notify(f"Loaded {len(items)} items.", severity="information")


# ═══════════════════════════════════════════════════════════════════════════════
# SNAKE GAME WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class SnakeWindow(BradWindow):
    APP_ID: ClassVar[str] = "snake"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _MIN_GRID = 10
    _snake: list[tuple[int, int]] = []
    _food: tuple[int, int] = (0, 0)
    _dir: tuple[int, int] = (0, 1)
    _next_dir: tuple[int, int] = (0, 1)
    _score: int = 0
    _game_over: bool = False
    _running: bool = False
    _grid_w: int = 20
    _grid_h: int = 20
    _timer: Any = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🐍  Snake Game", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical(id="snake-body"):
            yield Static("", id="snake-grid")
            yield Static("", id="snake-score", classes="panel-heading")

    def on_mount(self) -> None:
        self._calc_grid()
        self._start_game()

    def _calc_grid(self) -> None:
        term_w, term_h = os.get_terminal_size()
        self._grid_w = max(self._MIN_GRID, min(term_w - 4, 48))
        self._grid_h = max(self._MIN_GRID, min(term_h - 8, 32))

    def _start_game(self) -> None:
        self._calc_grid()
        if self._timer:
            self._timer.stop()
        cw, ch = self._grid_w // 2, self._grid_h // 2
        self._snake = [(ch, cw), (ch, cw - 1), (ch, cw - 2)]
        self._dir = (0, 1)
        self._next_dir = (0, 1)
        self._score = 0
        self._game_over = False
        self._running = True
        self._spawn_food()
        self._update_display()
        self._timer = self.set_interval(0.12, self._tick)

    def _spawn_food(self) -> None:
        occupied = set(self._snake)
        free = [(r, c) for r in range(self._grid_h) for c in range(self._grid_w) if (r, c) not in occupied]
        if free:
            self._food = random.choice(free)

    def _tick(self) -> None:
        if not self._running or self._game_over:
            return
        self._dir = self._next_dir
        head = self._snake[0]
        dr, dc = self._dir
        nh = (head[0] + dr, head[1] + dc)
        if (nh[0] < 0 or nh[0] >= self._grid_h or nh[1] < 0 or nh[1] >= self._grid_w
                or nh in self._snake[:-1]):
            self._game_over = True
            self._running = False
            self._update_display()
            return
        self._snake.insert(0, nh)
        if nh == self._food:
            self._score += 10
            self._spawn_food()
        else:
            self._snake.pop()
        self._update_display()

    def _update_display(self) -> None:
        snake_set = set(self._snake)
        head = self._snake[0] if self._snake else None
        f_r, f_c = self._food
        lines = []
        for r in range(self._grid_h):
            row_chars = []
            for c in range(self._grid_w):
                if (r, c) == self._food:
                    row_chars.append("●")
                elif (r, c) == head:
                    row_chars.append("█")
                elif (r, c) in snake_set:
                    row_chars.append("█")
                else:
                    row_chars.append("·")
            lines.append(" ".join(row_chars))
        grid = "\n".join(lines)
        if self._game_over:
            overlay = f"\n[bold #ff4757]  GAME OVER — Score: {self._score}  [/]\n[bold #7f8c8d]  SPACE to restart  [/]"
        else:
            overlay = ""
        self.query_one("#snake-grid", Static).update(grid + overlay)
        self.query_one("#snake-score", Static).update(
            f"[bold #00d4ff]Score: {self._score}[/]  [#7f8c8d]{self._grid_w}x{self._grid_h}[/]"
        )

    def on_key(self, event: Key) -> None:
        if event.key == "space" and self._game_over:
            self._start_game()
            return
        if not self._running:
            return
        opposite = {(0, 1): (0, -1), (0, -1): (0, 1), (1, 0): (-1, 0), (-1, 0): (1, 0)}
        new_dir = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}.get(event.key)
        if new_dir and new_dir != opposite.get(self._dir):
            self._next_dir = new_dir

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss()

# ═══════════════════════════════════════════════════════════════════════════════
# PASSWORD VAULT WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class VaultWindow(BradWindow):
    APP_ID: ClassVar[str] = "vault"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _entries: list[dict] = []
    _selected_idx: int = -1
    _unlocked: bool = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🔐  Vault", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Horizontal():
            with Vertical(id="mail-left"):
                yield Static("[bold #7f8c8d]Entries[/]", classes="panel-heading")
                yield ListView(id="vault-list")
            with Vertical(id="mail-right"):
                yield Static("[bold #7f8c8d]Details[/]", classes="panel-heading")
                yield Static("", id="vault-unlock")
                yield Input(placeholder="Service", id="vault-service")
                yield Input(placeholder="Username", id="vault-user")
                yield Input(placeholder="Password", id="vault-pass", password=True)
                yield Input(placeholder="URL", id="vault-url")
                yield Input(placeholder="Notes", id="vault-notes")
                with Horizontal(id="editor-actions"):
                    yield Button("Add", id="vault-add", classes="btn-primary")
                    yield Button("Save", id="vault-save", classes="btn-success")
                    yield Button("Delete", id="vault-del", classes="btn-danger")
                    yield Button("Gen PW", id="vault-gen", classes="folder-btn")

    def on_mount(self) -> None:
        self._unlock_view()

    def _unlock_view(self) -> None:
        self._unlocked = False
        self.query_one("#vault-unlock", Static).update("[bold #ffa502]Vault is locked.[/]\nEnter master password to unlock:")
        self.query_one("#vault-service", Input).disabled = True
        self.query_one("#vault-user", Input).disabled = True
        self.query_one("#vault-pass", Input).disabled = True
        self.query_one("#vault-url", Input).disabled = True
        self.query_one("#vault-notes", Input).disabled = True

    def _unlock(self, pw: str) -> None:
        sec = self.app.security
        if sec is None:
            self.notify("Security module not available.", severity="error")
            return
        if not sec.unlock_vault(pw):
            self.notify("Wrong master password.", severity="error")
            return
        self._unlocked = True
        self.query_one("#vault-unlock", Static).update("[bold #2ed573]Vault unlocked[/]")
        for widget_id in ("vault-service", "vault-user", "vault-pass", "vault-url", "vault-notes"):
            self.query_one(f"#{widget_id}", Input).disabled = False
        self._load_entries()

    def _load_entries(self) -> None:
        sec = self.app.security
        if sec is None:
            return
        raw = sec.vault.get("vault_entries")
        self._entries = raw if isinstance(raw, list) else []
        self._refresh_list()

    def _save_entries(self) -> None:
        sec = self.app.security
        if sec is None:
            return
        sec.vault.put("vault_entries", self._entries)
        self._refresh_list()

    def _refresh_list(self) -> None:
        lv = self.query_one("#vault-list", ListView)
        lv.clear()
        for i, entry in enumerate(self._entries):
            service = entry.get("service", "?") or "?"
            lv.append(ListItem(Static(service), id=f"vault-item-{i}"))

    @on(ListView.Selected, "#vault-list")
    def _on_select(self, event: ListView.Selected) -> None:
        if not event.item or not event.item.id:
            return
        idx = int(event.item.id.split("-")[-1])
        self._selected_idx = idx
        entry = self._entries[idx] if 0 <= idx < len(self._entries) else {}
        self.query_one("#vault-service", Input).value = entry.get("service", "")
        self.query_one("#vault-user", Input).value = entry.get("username", "")
        self.query_one("#vault-pass", Input).value = entry.get("password", "")
        self.query_one("#vault-url", Input).value = entry.get("url", "")
        self.query_one("#vault-notes", Input).value = entry.get("notes", "")

    def _gen_password(self) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(16))

    def _get_current_entry(self) -> dict:
        return {
            "service": self.query_one("#vault-service", Input).value.strip(),
            "username": self.query_one("#vault-user", Input).value.strip(),
            "password": self.query_one("#vault-pass", Input).value.strip(),
            "url": self.query_one("#vault-url", Input).value.strip(),
            "notes": self.query_one("#vault-notes", Input).value.strip(),
        }

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(); return
        if not self._unlocked:
            return
        if bid == "vault-add":
            entry = self._get_current_entry()
            if not entry["service"]:
                self.notify("Service name required.", severity="warning")
                return
            self._entries.append(entry)
            self._save_entries()
            self.notify("Entry added.", severity="information")
        elif bid == "vault-save":
            if self._selected_idx < 0 or self._selected_idx >= len(self._entries):
                self.notify("Select an entry first.", severity="warning")
                return
            self._entries[self._selected_idx] = self._get_current_entry()
            self._save_entries()
            self.notify("Entry saved.", severity="information")
        elif bid == "vault-del":
            if self._selected_idx < 0 or self._selected_idx >= len(self._entries):
                self.notify("Select an entry first.", severity="warning")
                return
            self._entries.pop(self._selected_idx)
            self._selected_idx = -1
            self._save_entries()
            self.notify("Entry deleted.", severity="information")
        elif bid == "vault-gen":
            pw = self._gen_password()
            self.query_one("#vault-pass", Input).value = pw

    @on(Input.Submitted, "#vault-unlock")
    def _on_unlock_submit(self, event: Input.Submitted) -> None:
        self._unlock(event.value.strip())

# ═══════════════════════════════════════════════════════════════════════════════
# WEATHER WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class WeatherWindow(BradWindow):
    APP_ID: ClassVar[str] = "weather"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _last: dict | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🌤  Weather", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical():
            with Horizontal(id="browser-nav"):
                yield Input(placeholder="City name…", id="weather-city")
                yield Button("Get Weather", id="weather-fetch", classes="btn-primary")
            yield Static("", id="weather-display")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss(); return
        if bid == "weather-fetch":
            self._fetch()

    @on(Input.Submitted, "#weather-city")
    def _on_enter(self) -> None:
        self._fetch()

    @work(thread=True)
    def _fetch(self) -> None:
        city = self.query_one("#weather-city", Input).value.strip()
        if not city:
            self.notify("Enter a city name.", severity="warning")
            return
        try:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            if "current_condition" not in data or not data["current_condition"]:
                self.app.call_from_thread(self._show_error, "City not found.")
                return
            self._last = data
            self.app.call_from_thread(self._display, data)
        except Exception as e:
            self.app.call_from_thread(self._show_error, f"Error: {e}")

    def _display(self, data: dict) -> None:
        cc = data["current_condition"][0]
        city_name = data.get("nearest_area", [{}])[0].get("areaName", [{}])[0].get("value", "?")
        temp = cc.get("temp_C", "?")
        cond = cc.get("weatherDesc", [{}])[0].get("value", "?")
        humidity = cc.get("humidity", "?")
        wind = cc.get("windspeedKmph", "?")
        feels = cc.get("FeelsLikeC", "?")
        lines = [
            f"[bold #00d4ff]{city_name}[/]",
            f"[bold]Temperature:[/]  {temp}°C",
            f"[bold]Condition:[/]    {cond}",
            f"[bold]Humidity:[/]     {humidity}%",
            f"[bold]Wind:[/]        {wind} km/h",
            f"[bold]Feels like:[/]  {feels}°C",
            "",
            "[bold #ffa502]3-Day Forecast[/]",
        ]
        for day in data.get("weather", [])[:3]:
            date = day.get("date", "?")
            hi = day.get("maxtempC", "?")
            lo = day.get("mintempC", "?")
            desc = day.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value", "?")
            lines.append(f"  [bold]{date}[/]  {lo}–{hi}°C  {desc}")
        self.query_one("#weather-display", Static).update("\n".join(lines))

    def _show_error(self, msg: str) -> None:
        self.query_one("#weather-display", Static).update(f"[#ff4757]{msg}[/]")

# ═══════════════════════════════════════════════════════════════════════════════
# MINESWEEPER
# ═══════════════════════════════════════════════════════════════════════════════

class MineWindow(BradWindow):
    APP_ID: ClassVar[str] = "minesweeper"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _ROWS = 10
    _COLS = 10
    _MINES = 10
    _grid: list[list[str]]
    _revealed: list[list[bool]]
    _mine_positions: set[tuple[int, int]]
    _game_over: bool
    _first_click: bool
    _flag_count: int
    _start_time: float
    _timer_interval = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("💣  Minesweeper", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical():
            with Horizontal(classes="panel-heading"):
                yield Static("[bold #00d4ff]💣 10[/]", id="mine-count")
                yield Button("😊", id="mine-restart")
                yield Static("[bold #00d4ff]⏱ 0[/]", id="mine-timer")
            yield Grid(id="mine-grid")

    def on_mount(self) -> None:
        self._init_game()

    def _init_game(self) -> None:
        self._grid = [[" " for _ in range(self._COLS)] for _ in range(self._ROWS)]
        self._revealed = [[False] * self._COLS for _ in range(self._ROWS)]
        self._mine_positions = set()
        self._game_over = False
        self._first_click = True
        self._flag_count = 0
        self._start_time = 0.0
        if self._timer_interval:
            try:
                self._timer_interval.cancel()
            except Exception:
                pass
            self._timer_interval = None
        self._build_grid()
        self._update_header()

    def _build_grid(self) -> None:
        grid = self.query_one("#mine-grid", Grid)
        grid.remove_children()
        grid.styles.grid_size_rows = self._ROWS
        grid.styles.grid_size_columns = self._COLS
        for r in range(self._ROWS):
            for c in range(self._COLS):
                btn = Button("", id=f"m-{r}-{c}")
                btn.styles.width = 3
                btn.styles.height = 1
                btn.styles.min_width = 3
                btn.styles.margin = (0, 0)
                grid.mount(btn)

    def _place_mines(self, safe_r: int, safe_c: int) -> None:
        safe_zone = {(safe_r + dr, safe_c + dc)
                     for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                     if 0 <= safe_r + dr < self._ROWS and 0 <= safe_c + dc < self._COLS}
        candidates = [(r, c) for r in range(self._ROWS) for c in range(self._COLS)
                      if (r, c) not in safe_zone]
        self._mine_positions = set(random.sample(candidates, min(self._MINES, len(candidates))))

    def _adj_mines(self, r: int, c: int) -> int:
        return sum(1 for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                   if (dr or dc) and (r + dr, c + dc) in self._mine_positions)

    def _reveal(self, r: int, c: int) -> None:
        if not (0 <= r < self._ROWS and 0 <= c < self._COLS) or self._revealed[r][c]:
            return
        if self._grid[r][c] == "F":
            return
        self._revealed[r][c] = True
        if (r, c) in self._mine_positions:
            return
        adj = self._adj_mines(r, c)
        btn = self.query_one(f"#m-{r}-{c}", Button)
        btn.disabled = True
        if adj > 0:
            colors = {1: "#00d4ff", 2: "#2ed573", 3: "#ff4757", 4: "#1e3a5f",
                      5: "#ffa502", 6: "#00d4ff", 7: "#ff4757", 8: "#7f8c8d"}
            btn.styles.color = colors.get(adj, "#ecf0f1")
            btn.label = str(adj)
        else:
            btn.label = " "
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr or dc:
                        self._reveal(r + dr, c + dc)

    def _check_win(self) -> bool:
        revealed = sum(1 for r in range(self._ROWS) for c in range(self._COLS)
                       if self._revealed[r][c])
        return revealed == self._ROWS * self._COLS - len(self._mine_positions)

    def _reveal_all_mines(self) -> None:
        for r, c in self._mine_positions:
            try:
                btn = self.query_one(f"#m-{r}-{c}", Button)
                btn.label = "💣"
                btn.disabled = True
            except NoMatches:
                pass

    def _update_header(self) -> None:
        remaining = self._MINES - self._flag_count
        self.query_one("#mine-count", Static).update(f"[bold #00d4ff]💣 {remaining}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss()
            return
        if bid == "mine-restart":
            self._init_game()
            return
        if not bid or not bid.startswith("m-") or self._game_over:
            return
        parts = bid.split("-")
        if len(parts) != 3:
            return
        r, c = int(parts[1]), int(parts[2])
        if self._revealed[r][c] or self._grid[r][c] == "F":
            return
        if self._first_click:
            self._first_click = False
            self._place_mines(r, c)
            self._start_time = time.time()
            self._timer_interval = self.set_interval(1.0, self._tick_timer)
        if (r, c) in self._mine_positions:
            self._game_over = True
            self._reveal_all_mines()
            if self._timer_interval:
                try:
                    self._timer_interval.cancel()
                except Exception:
                    pass
            self.notify("💥 Game Over!", severity="error")
            return
        self._reveal(r, c)
        if self._check_win():
            self._game_over = True
            if self._timer_interval:
                try:
                    self._timer_interval.cancel()
                except Exception:
                    pass
            self.notify("🎉 You Win!", severity="information")

    @on(Click, "#mine-grid Button")
    def _on_mine_right_click(self, event: Click) -> None:
        if event.button != 3:
            return
        bid = getattr(event.widget, "id", None) or ""
        if not bid.startswith("m-"):
            return
        parts = bid.split("-")
        if len(parts) != 3:
            return
        r, c = int(parts[1]), int(parts[2])
        if self._revealed[r][c] or self._game_over:
            return
        btn = self.query_one(f"#{bid}", Button)
        if self._grid[r][c] == "F":
            self._grid[r][c] = " "
            self._flag_count -= 1
            btn.label = ""
        else:
            self._grid[r][c] = "F"
            self._flag_count += 1
            btn.label = "🚩"
        self._update_header()

    def _tick_timer(self) -> None:
        elapsed = int(time.time() - self._start_time)
        self.query_one("#mine-timer", Static).update(f"[bold #00d4ff]⏱ {elapsed}[/]")

# ═══════════════════════════════════════════════════════════════════════════════
# 2048 GAME
# ═══════════════════════════════════════════════════════════════════════════════

class Game2048Window(BradWindow):
    APP_ID: ClassVar[str] = "game2048"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _SIZE = 4
    _grid: list[list[int]]
    _score: int
    _game_over: bool
    _won: bool
    _COLORS = {
        2: "#eee4da", 4: "#ede0c8", 8: "#f2b179", 16: "#f59563",
        32: "#f67c5f", 64: "#f65e3b", 128: "#edcf72", 256: "#edcc61",
        512: "#edc850", 1024: "#edc53f", 2048: "#edc22e",
    }

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🎲  2048", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Vertical():
            with Horizontal(classes="panel-heading"):
                yield Static("[bold #00d4ff]Score: 0[/]", id="g2048-score")
                yield Button("New Game", id="g2048-new")
            with Vertical(id="g2048-grid"):
                for r in range(self._SIZE):
                    with Horizontal(classes="g2048-row"):
                        for c in range(self._SIZE):
                            yield Static("", id=f"g2048-{r}-{c}", classes="g2048-cell")

    def on_mount(self) -> None:
        self._reset_game()

    def _reset_game(self) -> None:
        self._grid = [[0] * self._SIZE for _ in range(self._SIZE)]
        self._score = 0
        self._game_over = False
        self._won = False
        self._spawn_tile()
        self._spawn_tile()
        self._render_grid()

    def _spawn_tile(self) -> None:
        empty = [(r, c) for r in range(self._SIZE) for c in range(self._SIZE)
                 if self._grid[r][c] == 0]
        if not empty:
            return
        r, c = random.choice(empty)
        self._grid[r][c] = 4 if random.random() < 0.1 else 2

    def _render_grid(self) -> None:
        self.query_one("#g2048-score", Static).update(f"[bold #00d4ff]Score: {self._score}[/]")
        for r in range(self._SIZE):
            for c in range(self._SIZE):
                val = self._grid[r][c]
                cell = self.query_one(f"#g2048-{r}-{c}", Static)
                cell.styles.background = self._COLORS.get(val, "#1a2740")
                if val == 0:
                    cell.update("")
                else:
                    cell.update(str(val))
                    cell.styles.color = "#776e65" if val <= 4 else "#f9f6f2"
                    cell.styles.text_style = "bold"
                cell.styles.width = 6
                cell.styles.height = 3
                cell.styles.content_align_vertical = "middle"
                cell.styles.content_align_horizontal = "center"

    def _slide(self, row: list[int]) -> list[int]:
        tiles = [v for v in row if v != 0]
        merged = []
        skip = False
        for i in range(len(tiles)):
            if skip:
                skip = False
                continue
            if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
                merged.append(tiles[i] * 2)
                self._score += tiles[i] * 2
                skip = True
            else:
                merged.append(tiles[i])
        merged += [0] * (self._SIZE - len(merged))
        return merged

    def _slide_left(self) -> bool:
        changed = False
        for i in range(self._SIZE):
            new_row = self._slide(self._grid[i])
            if new_row != self._grid[i]:
                changed = True
                self._grid[i] = new_row
        return changed

    def _slide_right(self) -> bool:
        changed = False
        for i in range(self._SIZE):
            rev = list(reversed(self._grid[i]))
            new_row = self._slide(rev)
            new_row = list(reversed(new_row))
            if new_row != self._grid[i]:
                changed = True
                self._grid[i] = new_row
        return changed

    def _slide_up(self) -> bool:
        changed = False
        for c in range(self._SIZE):
            col = [self._grid[r][c] for r in range(self._SIZE)]
            new_col = self._slide(col)
            if new_col != col:
                changed = True
                for r in range(self._SIZE):
                    self._grid[r][c] = new_col[r]
        return changed

    def _slide_down(self) -> bool:
        changed = False
        for c in range(self._SIZE):
            col = [self._grid[r][c] for r in range(self._SIZE)]
            rev = list(reversed(col))
            new_col = self._slide(rev)
            new_col = list(reversed(new_col))
            if new_col != col:
                changed = True
                for r in range(self._SIZE):
                    self._grid[r][c] = new_col[r]
        return changed

    def _check_win(self) -> bool:
        for r in range(self._SIZE):
            for c in range(self._SIZE):
                if self._grid[r][c] >= 2048:
                    return True
        return False

    def _check_game_over(self) -> bool:
        for r in range(self._SIZE):
            for c in range(self._SIZE):
                if self._grid[r][c] == 0:
                    return False
                if c + 1 < self._SIZE and self._grid[r][c] == self._grid[r][c + 1]:
                    return False
                if r + 1 < self._SIZE and self._grid[r][c] == self._grid[r + 1][c]:
                    return False
        return True

    def on_key(self, event) -> None:
        if self._game_over:
            return
        moved = False
        if event.key == "left":
            moved = self._slide_left()
        elif event.key == "right":
            moved = self._slide_right()
        elif event.key == "up":
            moved = self._slide_up()
        elif event.key == "down":
            moved = self._slide_down()
        if moved:
            self._spawn_tile()
            self._render_grid()
            if self._check_win() and not self._won:
                self._won = True
                self.notify("🎉 You reached 2048!", severity="information")
            if self._check_game_over():
                self._game_over = True
                self.notify("Game Over! No moves left.", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss()
        elif bid == "g2048-new":
            self._reset_game()

# ═══════════════════════════════════════════════════════════════════════════════
# MARKDOWN PREVIEW
# ═══════════════════════════════════════════════════════════════════════════════

class MarkdownWindow(BradWindow):
    APP_ID: ClassVar[str] = "markdown"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _current_file: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("📝  Markdown Preview", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        with Horizontal():
            with Vertical(id="md-file-list"):
                yield Static("[bold #7f8c8d]Files[/]", classes="panel-heading")
                yield ListView(id="md-list")
            with Vertical(id="md-preview"):
                yield Static("[bold #7f8c8d]Preview[/]", classes="panel-heading")
                yield Static("Select a file to preview", id="md-content")
                yield Button("Open in Editor", id="md-open-editor")

    def on_mount(self) -> None:
        self._current_file = None
        self._scan_files()

    def _scan_files(self) -> None:
        vfs: VirtualFileSystem = self.app.vfs
        home = f"/home/{self.app.user_profile.get('username', 'user')}"
        md_files = []
        try:
            for entry in vfs.ls(home):
                if entry["name"].endswith(".md") and entry["type"] == "file":
                    md_files.append(entry["name"])
        except Exception:
            pass
        md_files.sort()
        lv = self.query_one("#md-list", ListView)
        lv.clear()
        for name in md_files:
            lv.append(ListItem(Static(name)))

    @on(ListView.Selected, "#md-list")
    def _on_file_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if not item:
            return
        static_widget = item.children[0] if item.children else None
        if not isinstance(static_widget, Static):
            return
        filename = str(static_widget.renderable or "")
        vfs: VirtualFileSystem = self.app.vfs
        home = f"/home/{self.app.user_profile.get('username', 'user')}"
        path = f"{home}/{filename}"
        try:
            content = vfs.read_text(path)
            md = Markdown(content)
            self.query_one("#md-content", Static).update(md)
            self._current_file = path
        except Exception as e:
            self.query_one("#md-content", Static).update(f"[#ff4757]Error: {e}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss()
        elif bid == "md-open-editor":
            if self._current_file:
                self.dismiss()
                self.app.post_message(LaunchApp("editor"))
            else:
                self.notify("No file selected.", severity="warning")

# ═══════════════════════════════════════════════════════════════════════════════
# MESH WINDOW — P2P networking
# ═══════════════════════════════════════════════════════════════════════════════

class MeshWindow(BradWindow):
    APP_ID: ClassVar[str] = "mesh"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    _section: str = "peers"
    _selected_peer: Peer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("🕸  Mesh Network", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")

        with Horizontal():
            # Sidebar
            with Vertical(id="mail-left"):
                yield Static("[bold #00d4ff]Mesh[/]", classes="panel-heading")
                yield Button("🕸 Peers",   id="mesh-btn-peers", classes="folder-btn active")
                yield Button("💬 Chat",    id="mesh-btn-chat",  classes="folder-btn")
                yield Static("", id="mesh-status", classes="mesh-status")

            # Content
            with Vertical(id="mail-right"):
                # Peers view
                with Vertical(id="mesh-peers-view"):
                    yield Static("[bold #7f8c8d]Discovered Peers[/]", classes="panel-heading")
                    yield ListView(id="mesh-peer-list")
                # Chat view
                with Vertical(id="mesh-chat-view"):
                    yield Static("[bold #7f8c8d]Chat[/]", classes="panel-heading")
                    yield RichLog(id="mesh-chat-log", markup=True, highlight=True)
                    with Horizontal(id="mesh-chat-bar"):
                        yield Input(placeholder="Type a message…", id="mesh-chat-input")
                        yield Button("Send", id="mesh-chat-send", variant="primary")

    def on_mount(self) -> None:
        super().on_mount()
        self._mesh = get_mesh()
        if not self._mesh.running:
            self._mesh.start()
        self._mesh.on("peer_discovered", lambda p: self.call_from_thread(self._refresh_peers))
        self._mesh.on("peer_seen", lambda p: self.call_from_thread(self._refresh_peers))
        self._mesh.on("chat", lambda msg, addr: self.call_from_thread(self._on_chat, msg))
        self._refresh_peers()
        self._update_status()
        self._switch_view("peers")
        self.query_one("#mesh-peers-view", Vertical).styles.display = "block"
        self.query_one("#mesh-chat-view", Vertical).styles.display = "none"

    def _update_status(self) -> None:
        st = self._mesh.status()
        label = f"[#7f8c8d]ID: [bold #00d4ff]{st['peer_id'][:12]}[/]\n[#7f8c8d]Peers: [bold]{st['peers']}[/][/]"
        try:
            self.query_one("#mesh-status", Static).update(label)
        except NoMatches:
            pass

    def _refresh_peers(self) -> None:
        try:
            lv = self.query_one("#mesh-peer-list", ListView)
        except NoMatches:
            return
        lv.clear()
        for p in self._mesh.peers:
            alive_tag = "[#2ed573]●[/]" if p.alive else "[#7f8c8d]○[/]"
            label = f"{alive_tag} [bold]{p.hostname}[/] [#7f8c8d]{p.ip}[/]"
            lv.append(ListItem(Static(label)))
        self._update_status()

    def _on_chat(self, msg: dict) -> None:
        try:
            log = self.query_one("#mesh-chat-log", RichLog)
            sender = msg.get("sender", "?")[:8]
            text = msg.get("payload", {}).get("text", "")
            log.write(f"[#00d4ff]<{sender}>[/] {text}")
        except NoMatches:
            pass

    def _switch_view(self, section: str) -> None:
        self._section = section
        peers_view = self.query_one("#mesh-peers-view", Vertical)
        chat_view = self.query_one("#mesh-chat-view", Vertical)
        peers_view.styles.display = "block" if section == "peers" else "none"
        chat_view.styles.display = "block" if section == "chat" else "none"
        for sid in ("peers", "chat"):
            btn = self.query_one(f"#mesh-btn-{sid}", Button)
            btn.classes = "folder-btn" + (" active" if sid == section else "")
        if section == "chat":
            self.query_one("#mesh-chat-input", Input).focus()

    def _send_message(self) -> None:
        inp = self.query_one("#mesh-chat-input", Input)
        text = inp.value.strip()
        if not text:
            return
        if not self._selected_peer:
            self.notify("Select a peer from the Peers view first.", severity="warning")
            return
        inp.value = ""
        self._mesh.send(self._selected_peer, "chat", {
            "text": text,
            "from": self._mesh.peer_id,
        })
        try:
            log = self.query_one("#mesh-chat-log", RichLog)
            log.write(f"[#2ed573]<you>[/] {text}")
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-close":
            self.dismiss()
        elif bid == "mesh-btn-peers":
            self._switch_view("peers")
        elif bid == "mesh-btn-chat":
            self._switch_view("chat")
        elif bid == "mesh-chat-send":
            self._send_message()

    @on(Input.Submitted, "#mesh-chat-input")
    def _input_submitted(self) -> None:
        self._send_message()

    @on(ListView.Selected, "#mesh-peer-list")
    def _on_peer_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        idx = self.query_one("#mesh-peer-list", ListView).index
        peers = self._mesh.peers
        if 0 <= idx < len(peers):
            self._selected_peer = peers[idx]
            self.notify(f"Selected {self._selected_peer.hostname} for chat.", severity="information")
            self._switch_view("chat")


# ═══════════════════════════════════════════════════════════════════════════════
# HELP WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class HelpWindow(BradWindow):
    APP_ID: ClassVar[str] = "help"
    BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="win-titlebar"):
            yield Static("?  BradOS Help", classes="win-title")
            yield Button("—", id="btn-min", classes="btn-min")
            yield Button("✕", id="btn-close", classes="win-close")
        yield ScrollableContainer(Static("""
  [bold #00d4ff]KEYBOARD SHORTCUTS[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  [#00d4ff]t[/] Terminal   [#00d4ff]b[/] Browser    [#00d4ff]f[/] Files     [#00d4ff]e[/] Editor
  [#00d4ff]m[/] Mail       [#00d4ff]n[/] Notes      [#00d4ff]c[/] Calc      [#00d4ff]k[/] Clock
  [#00d4ff]p[/] Monitor    [#00d4ff]g[/] Logs       [#00d4ff]s[/] Settings  [#00d4ff]Ctrl+K[/] Kernel
  [#00d4ff]l[/] Logout     [#00d4ff]q[/] Quit       [#00d4ff]F1[/] This help

  [bold #00d4ff]TERMINAL[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  Built-ins: cd pwd ls cat echo clear env exit help
  Up/Down navigate command history. All other commands pass to host shell.

  [bold #00d4ff]BROWSER[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  [#00d4ff]Ctrl+T[/] new tab  [#00d4ff]Ctrl+W[/] close tab  [#00d4ff]Ctrl+L[/] focus URL
  Bare name uses VFS local page. http(s):// fetches real web.
  [#7f8c8d]pip install requests[/]  for full HTTPS support.

  [bold #00d4ff]NOTES[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  [#00d4ff]Ctrl+N[/] new note   [#00d4ff]Ctrl+S[/] save note
  Saved to VFS at [#7f8c8d]/home/{user}/notes.json[/]

  [bold #00d4ff]CLOCK[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  Stopwatch: Start / Stop / Reset.  Timer: enter MM:SS then Start.
  World clocks: UTC, EST (+0/-5), CET (+1), JST (+9).

  [bold #00d4ff]LOGS[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  Reads brados.log + brados_kernel.log. Last 500 lines.
  Filter by All / Info / Warn / Error via sidebar.

  [bold #00d4ff]SETTINGS[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  Profile · Display · Drivers · System — read-only for now.

  [bold #00d4ff]FILE MANAGER[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  Sandboxed to [#7f8c8d]brados_files/home/[/] via VFS.
  Click dir to navigate, file to preview. New File / Dir / Delete / Rename.

  [bold #00d4ff]TIPS[/]
  [#1e3a5f]────────────────────────────────────────────────[/]
  [#7f8c8d]pip install psutil[/]    live CPU/RAM in tray + Monitor
  [#7f8c8d]pip install requests[/]  HTTPS in Browser
  [#7f8c8d]python brados.py[/]      classic mode + kernel mode + games
""", id="help-content"))

    def on_button_pressed(self, e: Button.Pressed) -> None:
        if e.button.id == "btn-close": self.dismiss()


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

class _FilePickerModal(ModalScreen):
    """Graphical file picker that browses VFS directories.
    In 'save' mode, the text input lets you type a new filename.
    Dismisses with the chosen path string, or empty string on cancel."""

    def __init__(self, title: str = "Open File", mode: str = "open",
                 start_path: str = "/home"):
        super().__init__()
        self._title = title
        self._mode  = mode      # "open" or "save"
        self._cwd   = start_path
        self._entries: list[tuple[str, str]] = []  # (type, name)  type = "d" or "f"

    def compose(self) -> ComposeResult:
        with Container(id="login-box", classes="filepicker"):
            yield Static(self._title, id="login-logo")
            yield Static("", id="fp-path", classes="fp-path")
            with ScrollableContainer(id="fp-scroll", classes="fp-scroll"):
                yield ListView(id="fp-list")
            with Horizontal(classes="fp-input-row"):
                yield Static("Path:", classes="llabel")
                yield Input("", id="fp-input", placeholder="/home/…")
            with Horizontal(id="login-btns"):
                yield Button("Open",  id="fp-open",   classes="btn-primary")
                yield Button("Cancel",id="fp-cancel", classes="btn-danger")

    async def on_mount(self) -> None:
        await self._load(self._cwd)
        inp = self.query_one("#fp-input", Input)
        inp.value = self._cwd + "/"
        inp.focus()

    async def _load(self, path: str) -> None:
        self._cwd = path
        self._entries = []
        try:
            raw = self.app.vfs.listdir(path)
        except Exception:
            raw = []

        def is_dir(n: str) -> bool:
            try:
                return self.app.vfs.stat(path.rstrip("/") + "/" + n).is_dir
            except Exception:
                return False

        dirs  = sorted(n for n in raw if is_dir(n))
        files = sorted(n for n in raw if n not in dirs)

        self.query_one("#fp-path", Static).update(f"[#00d4ff]{path}/[/]")
        lv = self.query_one("#fp-list", ListView)
        await lv.clear()

        # Parent dir entry
        if path != "/":
            parent = path.rstrip("/").rsplit("/", 1)[0] or "/"
            lv.append(ListItem(
                Static("[#ffa502]⬆ ..[/]"),
                id="fp-parent",
            ))

        for name in dirs:
            self._entries.append(("d", name))
            idx = len(self._entries) - 1
            lv.append(ListItem(
                Static(f"[#00d4ff]◫ {name}/[/]"),
                id=f"fp-e-{idx}",
            ))
        for name in files:
            self._entries.append(("f", name))
            idx = len(self._entries) - 1
            lv.append(ListItem(
                Static(f"[#ecf0f1]▤ {name}[/]"),
                id=f"fp-e-{idx}",
            ))

    @on(ListView.Selected, "#fp-list")
    async def _on_select(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        item_id = event.item.id or ""

        if item_id == "fp-parent":
            parent = self._cwd.rstrip("/").rsplit("/", 1)[0] or "/"
            await self._load(parent)
            self.query_one("#fp-input", Input).value = parent + "/"
            return

        if item_id and item_id.startswith("fp-e-"):
            try:
                idx = int(item_id.split("-")[-1])
                etype, ename = self._entries[idx]
            except (IndexError, ValueError):
                return
            path = self._cwd.rstrip("/") + "/" + ename
            if etype == "d":
                await self._load(path)
                self.query_one("#fp-input", Input).value = path + "/"
            else:
                self.query_one("#fp-input", Input).value = path

    def on_button_pressed(self, e: Button.Pressed) -> None:
        if e.button.id == "fp-cancel":
            self.dismiss("")
        elif e.button.id == "fp-open":
            self._submit()

    @on(Input.Submitted, "#fp-input")
    def _enter(self) -> None:
        self._submit()

    def _submit(self) -> None:
        path = self.query_one("#fp-input", Input).value.strip()
        if not path:
            self.notify("Enter a path.", severity="warning")
            return
        if self._mode == "open":
            try:
                if not self.app.vfs.exists(path):
                    self.notify(f"File not found: {path}", severity="error")
                    return
            except Exception:
                pass
        self.dismiss(path)


class _PromptModal(ModalScreen):
    def __init__(self, prompt: str, action: str = "OK"):
        super().__init__()
        self._prompt = prompt
        self._action = action

    def compose(self) -> ComposeResult:
        with Container(id="login-box"):
            yield Static(self._prompt, id="login-sub")
            yield Input(id="prompt-input")
            with Horizontal(id="login-btns"):
                yield Button(self._action, id="btn-ok",     classes="btn-primary")
                yield Button("Cancel",     id="btn-cancel", classes="btn-danger")

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    @on(Input.Submitted)
    def _enter(self) -> None: self._submit()

    def on_button_pressed(self, e: Button.Pressed) -> None:
        if e.button.id == "btn-ok": self._submit()
        else: self.dismiss("")

    def _submit(self) -> None:
        self.dismiss(self.query_one("#prompt-input", Input).value.strip())


# ═══════════════════════════════════════════════════════════════════════════════
# APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class BradOSShell(App):
    TITLE    = "BradOS v3.0 — Ocean Dark"
    CSS      = SHELL_CSS
    BINDINGS: ClassVar = [Binding("ctrl+q", "quit", "Quit")]

    user_profile : dict              = {}
    vfs          : VirtualFileSystem | None = None
    drivers      : DriverRegistry    | None = None
    security     : BradSec | None = None

    def on_mount(self) -> None:
        init_dirs()
        self.vfs      = create_default_vfs(kernel=self.kernel)
        self.drivers  = create_default_registry(vfs=self.vfs)
        self.security = get_bradsec()
        self.security.start()
        # Start BradSec daemon for IPC and background monitoring
        daemon = get_bradsec_daemon()
        daemon.start()
        daemon.on_alert(lambda findings: self.call_from_thread(
            self.notify, f"⚠ {len(findings)} security alert(s)", severity="error"
        ))
        # Start mesh networking
        self._mesh = get_mesh()
        self._mesh.start()
        self.packages = get_bpkg()
        for path in ["/home", "/tmp"]:
            try:
                self.vfs.makedirs(path)
            except Exception:
                pass
        self.push_screen(SplashScreen())


def run_shell(kernel=None) -> None:
    """Entry point called from brados.py with --shell flag."""
    app         = BradOSShell()
    app.kernel  = kernel
    app.run()


# brados_apps.py — BradOS Apps v2.0
#
# Calculator, mail, browser, editor, file manager, games, task manager,
# SVG viewer, and more — all usable in both classic terminal mode and as
# kernel tasks. HTML parser with a proper skip stack (not the broken regex
# every other project uses). Safe AST-based math evaluator (no exec()).

import os
import re
import ast
import json
import math
import time
import random
import shutil
import operator
from datetime import datetime
from html.parser import HTMLParser

from brados_system import (
    BRADOS_FILES_DIR,                   # ← imported, not redefined
    print_header, print_status, print_separator, print_menu_item,
    print_boxed, get_menu_choice, get_icon, get_terminal_size,
    get_dynamic_width,                  # ← was missing; caused NameError in browser
    clear_screen, progress_bar,
    FG, Style, ICONS,
    atomic_write_json,
    load_user_profile, save_user_profile, get_profile_path,
)

# ── Syscall shim (kernel mode may not be loaded) ──────────────────────────────
try:
    from brados_kernel_core import SYSCALL_PRINT, SYSCALL_INPUT, SYSCALL_SLEEP, SYSCALL_EXIT
except ImportError:
    SYSCALL_PRINT = 1
    SYSCALL_INPUT = 2
    SYSCALL_SLEEP = 3
    SYSCALL_EXIT  = 4

# ── Sub-directories (derived from the single source of truth) ─────────────────
BRADOS_APPS_DATA   = os.path.join(BRADOS_FILES_DIR, "apps_data")
BRADOS_MAIL_DIR    = os.path.join(BRADOS_FILES_DIR, "mail")
BRADOS_TASKS_DIR   = os.path.join(BRADOS_FILES_DIR, "tasks")
BRADOS_BROWSER_DIR = os.path.join(BRADOS_FILES_DIR, "browser")

def init_dirs():
    """Create all BradOS data directories.
    Call this once at startup — NOT at module import time."""
    for d in [BRADOS_FILES_DIR, BRADOS_APPS_DATA, BRADOS_MAIL_DIR,
              BRADOS_TASKS_DIR, BRADOS_BROWSER_DIR]:
        os.makedirs(d, exist_ok=True)

# ── HTML → plain text (real parser, not broken regex) ────────────────────────

class _BradHTMLParser(HTMLParser):
    """Convert HTML to readable plain text using Python's stdlib html.parser.

    The old approach (re.sub r'<[^>]+>') failed on:
      - <script> blocks (leaked JS code into output)
      - attribute values containing '>' characters
      - CDATA sections

    This version uses a skip *stack* (not a single depth counter + single tag)
    so that nested skip tags like <head><style>…</style></head> are handled
    correctly — the body is no longer suppressed after the head closes.
    """
    _SKIP  = {"script", "style", "svg", "path", "noscript", "head"}
    _BLOCK = {"p", "div", "article", "section", "main",
              "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "tr", "br", "hr", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._buf:        list[str] = []
        self._skip_stack: list[str] = []   # stack of tags currently being skipped

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return   # inside a skip block — ignore everything
        if tag in self._BLOCK:
            self._buf.append("\n")
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and href.startswith("http"):
                self._buf.append(f" [{href}] ")

    def handle_endtag(self, tag):
        # Pop the skip stack when the matching opening tag is closed
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
            return
        if self._skip_stack:
            return   # still inside a skip block
        if tag in self._BLOCK:
            self._buf.append("\n")

    def handle_data(self, data):
        if not self._skip_stack:
            self._buf.append(data)

    def result(self) -> str:
        text = "".join(self._buf)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Convert an HTML string to readable plain text.
    Safe, handles scripts/styles, exported for brados_gui.py."""
    parser = _BradHTMLParser()
    try:
        parser.feed(html)
        return parser.result()
    except Exception:
        # Last-resort fallback — still better than leaking script tags
        return re.sub(r"<[^>]+>", " ", html).strip()


# ── Safe mathematical evaluator ───────────────────────────────────────────────

_ALLOWED_OPS = {
    ast.Add:      operator.add,
    ast.Sub:      operator.sub,
    ast.Mult:     operator.mul,
    ast.Div:      operator.truediv,
    ast.Pow:      operator.pow,
    ast.Mod:      operator.mod,
    ast.FloorDiv: operator.floordiv,
}

def safe_eval(expr: str) -> float | int:
    """Evaluate a mathematical expression safely without eval()."""
    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return _ALLOWED_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub): return -_eval(node.operand)
            if isinstance(node.op, ast.UAdd): return +_eval(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            arg = _eval(node.args[0]) if node.args else 0
            if hasattr(math, fn):
                return getattr(math, fn)(arg)
        raise ValueError(f"Unsupported operation: {ast.dump(node)}")
    tree = ast.parse(expr, mode="eval")
    return _eval(tree.body)


# ── Classic-mode Calculator ───────────────────────────────────────────────────

def simple_calculator():
    print_header("Scientific Calculator", icon="app_calc")
    print_status("Operators: + - * / ** % //   Functions: sin cos tan sqrt log", "info")
    print_status("Constants: pi e   Type 'exit' to quit, 'clear' to reset", "info")
    while True:
        expr = input(f"{FG.BRIGHT_CYAN}>>> {Style.RESET}").strip()
        if not expr:
            continue
        if expr.lower() == "exit":
            break
        if expr.lower() == "clear":
            print_header("Scientific Calculator", icon="app_calc")
            continue
        try:
            sanitised = (expr
                         .replace("pi", str(math.pi))
                         .replace("^", "**")
                         .replace("e", str(math.e)))
            result = safe_eval(sanitised)
            if isinstance(result, float) and result.is_integer():
                print(f"{FG.BRIGHT_GREEN}  = {int(result)}{Style.RESET}")
            else:
                print(f"{FG.BRIGHT_GREEN}  = {result}{Style.RESET}")
        except Exception as ex:
            print_status(f"Error: {ex}", "error")
        print_separator()


# ── Kernel task: Calculator (generator, works with fixed scheduler) ───────────

def calculator_task():
    """Generator-based calculator for kernel mode.
    Writes the first syscall on the very first yield (not on prime),
    which is correct for the fixed scheduler in brados_kernel_core v2.
    """
    yield (SYSCALL_PRINT, f"{get_icon('app_calc')} Scientific Calculator [kernel mode]")
    yield (SYSCALL_PRINT, "Type expressions like 2+2, sin(pi/2), sqrt(144). 'exit' to quit.")
    while True:
        expr = yield (SYSCALL_INPUT, ">>> ")
        if not isinstance(expr, str):
            continue
        if expr.strip().lower() == "exit":
            break
        try:
            sanitised = expr.replace("pi", str(math.pi)).replace("^", "**").replace("e", str(math.e))
            result = safe_eval(sanitised)
            yield (SYSCALL_PRINT, f"  = {result}")
        except Exception as ex:
            yield (SYSCALL_PRINT, f"  Error: {ex}")
    yield (SYSCALL_EXIT,)


# ── Kernel task: Clock ────────────────────────────────────────────────────────

def clock_task():
    """Periodic clock that prints every 5 seconds using the SLEEP syscall."""
    yield (SYSCALL_PRINT, f"{get_icon('clock')} Clock started — reporting every 5 s")
    while True:
        yield (SYSCALL_SLEEP, 5)
        ts = time.strftime("%H:%M:%S")
        yield (SYSCALL_PRINT, f"{get_icon('clock')} {ts}")


# ── BradMail ──────────────────────────────────────────────────────────────────

def brad_mail(user_profile, save_profile_func):
    user_profile.setdefault("mail_folders",
        {"inbox": [], "sent": [], "drafts": [], "trash": []})
    save_profile_func(user_profile)

    def save_mail():
        save_profile_func(user_profile)

    def display_mail_list(folder):
        mails = user_profile["mail_folders"].get(folder, [])
        if not mails:
            print_status(f"No messages in {folder}.", "info")
            input("Enter to continue…")
            return
        for i, mail in enumerate(mails):
            star   = "⭐" if mail.get("starred") else "  "
            sender = mail.get("from" if folder == "inbox" else "to", "?")
            subj   = mail.get("subject", "")[:40]
            print(f"  {i+1}. {star} {sender[:18]:<18} | {subj}")
        print_separator()
        choice = input("Number to view (or Enter to go back): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(mails):
                mail = mails[idx]
                print_header(mail.get("subject", "No Subject"), icon="app_mail")
                print(f"  From : {mail.get('from', '?')}")
                print(f"  To   : {mail.get('to',   '?')}")
                print(f"  Date : {mail.get('date',  '?')}")
                print()
                print(mail.get("body", ""))
                print_separator()
                print("  (r)eply  (s)tar  (d)elete  Enter=back")
                opt = input("  > ").strip().lower()
                if opt == "r":
                    compose_email(to=mail["from"],
                                  subject=f"Re: {mail['subject']}",
                                  body_prefix=f"\n--- Original ---\n{mail['body']}")
                elif opt == "s":
                    mail["starred"] = not mail.get("starred", False)
                    save_mail()
                    print_status("Star toggled.", "success")
                elif opt == "d":
                    user_profile["mail_folders"][folder].pop(idx)
                    save_mail()
                    print_status("Deleted.", "success")
            time.sleep(0.8)

    def compose_email(to=None, subject=None, body_prefix=""):
        print_header("Compose Email", icon="app_mail")
        to_addr = to or input("  To      : ").strip()
        if not to_addr:
            print_status("Recipient required.", "error")
            return
        subj = subject or input("  Subject : ").strip()
        print("  Body (type .END on its own line to finish):")
        lines = [body_prefix] if body_prefix else []
        while True:
            line = input()
            if line == ".END":
                break
            lines.append(line)
        body    = "\n".join(lines)
        new_msg = {
            "from":    user_profile["username"],
            "to":      to_addr,
            "subject": subj,
            "body":    body,
            "date":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "starred": False,
        }
        user_profile["mail_folders"]["sent"].append(new_msg)
        if to_addr.lower() == user_profile["username"].lower():
            user_profile["mail_folders"]["inbox"].append(new_msg)
        else:
            other_path = get_profile_path(to_addr)
            if os.path.exists(other_path):
                other = load_user_profile(to_addr)
                other.setdefault("mail_folders", {}).setdefault("inbox", []).append(new_msg)
                save_user_profile(other)
                print_status(f"Delivered to {to_addr}.", "success")
            else:
                print_status(f"User '{to_addr}' not found — saved in Sent only.", "warning")
        save_mail()
        print_status("Message sent!", "success")
        time.sleep(0.8)

    while True:
        inbox_count = len(user_profile["mail_folders"]["inbox"])
        print_header(f"BradMail — {user_profile['username']}", icon="app_mail")
        print_menu_item("1", f"Inbox ({inbox_count})", "app_mail")
        print_menu_item("2", "Sent",    "app_mail")
        print_menu_item("3", "Drafts",  "app_files")
        print_menu_item("4", "Trash",   "warning")
        print_menu_item("5", "Compose", "success")
        print_menu_item("6", "Back",    "back")
        ch = get_menu_choice("  > ", ["1","2","3","4","5","6"])
        folders = {"1": "inbox", "2": "sent", "3": "drafts", "4": "trash"}
        if ch in folders:
            display_mail_list(folders[ch])
        elif ch == "5":
            compose_email()
        elif ch == "6":
            break


# ── BradGame Center ───────────────────────────────────────────────────────────

def brad_game_center():
    def snake_game():
        width, height = 20, 10
        snake = [(height // 2, width // 2)]
        dx, dy = 0, 1
        score  = 0
        def new_food():
            while True:
                pos = (random.randint(0, height - 1), random.randint(0, width - 1))
                if pos not in snake:
                    return pos
        food = new_food()
        def draw():
            clear_screen()
            print_header("BradSnake", icon="app_game")
            print(f"  Score: {score}   WASD to move, 'exit' to quit")
            for r in range(height):
                print("  " + "".join(
                    "🟢" if (r, c) == snake[0] else
                    "🟩" if (r, c) in snake[1:] else
                    "🍎" if (r, c) == food else
                    "▪ " for c in range(width)
                ))
        while True:
            draw()
            move = input().strip().lower()
            if move == "exit":
                print_status(f"Game over! Score: {score}", "info")
                break
            elif move == "w": dx, dy = -1,  0
            elif move == "s": dx, dy =  1,  0
            elif move == "a": dx, dy =  0, -1
            elif move == "d": dx, dy =  0,  1
            else:
                continue
            new_head = (snake[0][0] + dx, snake[0][1] + dy)
            if (new_head[0] < 0 or new_head[0] >= height or
                new_head[1] < 0 or new_head[1] >= width or
                new_head in snake):
                print_status(f"Collision! Final score: {score}", "error")
                break
            snake.insert(0, new_head)
            if new_head == food:
                score += 1
                food = new_food()
            else:
                snake.pop()
        input("Enter to continue…")

    def tictactoe():
        board = [" "] * 9
        turn  = 0
        def draw():
            clear_screen()
            print_header("Tic-Tac-Toe", icon="app_game")
            for r in range(3):
                row = " | ".join(board[r*3:(r+1)*3])
                print(f"  {row}")
                if r < 2: print("  ---------")
        def check():
            wins = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
            for a, b, c in wins:
                if board[a] == board[b] == board[c] != " ":
                    return board[a]
            return "Tie" if " " not in board else None
        while True:
            draw()
            result = check()
            if result:
                msg = "Tie!" if result == "Tie" else f"Player {result} wins!"
                print_status(msg, "info" if result == "Tie" else "success")
                break
            player = ["X", "O"][turn]
            print_status(f"Player {player}'s turn", "info")
            move = input("  Position (1-9, or 'exit'): ").strip()
            if move.lower() == "exit": break
            if move.isdigit() and 1 <= int(move) <= 9 and board[int(move)-1] == " ":
                board[int(move)-1] = player
                turn ^= 1
            else:
                print_status("Invalid move.", "error")
        input("Enter to continue…")

    def hangman():
        words  = ["python", "kernel", "brados", "terminal", "scheduler", "syscall"]
        word   = random.choice(words)
        guessed = set()
        lives   = 6
        while lives > 0:
            clear_screen()
            print_header("Hangman", icon="app_game")
            display = " ".join(c if c in guessed else "_" for c in word)
            print(f"  {display}")
            print(f"  Lives left: {'❤️ ' * lives}")
            print(f"  Guessed: {', '.join(sorted(guessed)) or '—'}")
            if "_" not in display:
                print_status(f"You got it! The word was '{word}'.", "success")
                break
            guess = input("  Letter: ").strip().lower()
            if len(guess) != 1 or not guess.isalpha():
                continue
            if guess in guessed:
                print_status("Already guessed.", "warning")
                continue
            guessed.add(guess)
            if guess not in word:
                lives -= 1
                print_status("Wrong!", "error")
        else:
            print_status(f"Game over. The word was '{word}'.", "error")
        input("Enter to continue…")

    def number_guess():
        secret   = random.randint(1, 100)
        attempts = 0
        print_header("Number Guessing", icon="app_game")
        print_status("Guess a number between 1 and 100.", "info")
        while True:
            try:
                guess = int(input("  Your guess: "))
                attempts += 1
                if guess < secret:   print_status("Too low!", "info")
                elif guess > secret: print_status("Too high!", "info")
                else:
                    print_status(f"Correct in {attempts} attempt(s)!", "success")
                    break
            except ValueError:
                print_status("Enter a valid number.", "error")
        input("Enter to continue…")

    while True:
        print_header("BradGame Center", icon="app_game")
        print_menu_item("1", "BradSnake",       "app_game")
        print_menu_item("2", "Tic-Tac-Toe",     "app_game")
        print_menu_item("3", "Hangman",          "app_game")
        print_menu_item("4", "Number Guessing",  "app_game")
        print_menu_item("5", "Back",             "back")
        ch = get_menu_choice("  > ", ["1","2","3","4","5"])
        match ch:
            case "1": snake_game()
            case "2": tictactoe()
            case "3": hangman()
            case "4": number_guess()
            case "5": break


# ── BradHub ───────────────────────────────────────────────────────────────────

AVAILABLE_APPS: dict[str, dict] = {
    "Voice Assistant": {"description": "Voice command simulation",   "exec": None},
    "Photo Viewer":    {"description": "View images (ASCII art)",     "exec": None},
    "Music Player":    {"description": "Play audio files (headless)", "exec": None},
    "Note Pad":        {"description": "Quick sticky notes",          "exec": None},
}

def brad_hub(user_profile, save_profile_func):
    installed: list = user_profile.setdefault("installed_apps", [])
    while True:
        print_header("BradHub App Store", icon="app_hub")
        print_menu_item("1", "Browse & Install", "app_hub")
        print_menu_item("2", "My Installed Apps", "app_files")
        print_menu_item("3", "Back", "back")
        ch = get_menu_choice("  > ", ["1","2","3"])
        if ch == "1":
            available = [(n, d) for n, d in AVAILABLE_APPS.items() if n not in installed]
            if not available:
                print_status("All apps are already installed.", "info")
                input("Enter to continue…")
                continue
            for i, (name, info) in enumerate(available):
                print(f"  {i+1}. {name:<24} {info['description']}")
            idx = input("  Number to install (or Enter to cancel): ").strip()
            if idx.isdigit():
                i = int(idx) - 1
                if 0 <= i < len(available):
                    app_name = available[i][0]
                    progress_bar(1.5, f"Installing {app_name}")
                    installed.append(app_name)
                    save_profile_func(user_profile)
                    print_status(f"{app_name} installed!", "success")
                    time.sleep(0.8)
        elif ch == "2":
            if not installed:
                print_status("No apps installed.", "info")
                input("Enter to continue…")
                continue
            for i, name in enumerate(installed):
                print(f"  {i+1}. {name}")
            idx = input("  Number to uninstall (or Enter to cancel): ").strip()
            if idx.isdigit():
                i = int(idx) - 1
                if 0 <= i < len(installed):
                    name = installed[i]
                    if input(f"  Uninstall '{name}'? (y/n): ").strip().lower() == "y":
                        installed.pop(i)
                        save_profile_func(user_profile)
                        print_status(f"{name} uninstalled.", "success")
                        time.sleep(0.8)
        elif ch == "3":
            break


# ── Task Manager ──────────────────────────────────────────────────────────────

def task_manager(user_profile, save_profile_func):
    tasks: list = user_profile.setdefault("tasks", [])

    def save():
        user_profile["tasks"] = tasks
        save_profile_func(user_profile)

    def show(filter_done=None):
        filtered = [t for t in tasks if filter_done is None or t["done"] == filter_done]
        if not filtered:
            print_status("No tasks to show.", "info")
            return
        prio_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for i, t in enumerate(filtered):
            status = "✅" if t["done"] else "⏳"
            prio   = prio_icons.get(t.get("priority", "medium"), "⚪")
            due    = t.get("due") or "—"
            print(f"  {i+1}. {status} {prio} {t['name'][:32]:<34} Due: {due}")

    while True:
        print_header("Task Manager", icon="app_tasks")
        print_menu_item("1", "View all",       "app_tasks")
        print_menu_item("2", "Pending only",   "app_tasks")
        print_menu_item("3", "Completed",      "success")
        print_menu_item("4", "Add task",       "success")
        print_menu_item("5", "Toggle done",    "warning")
        print_menu_item("6", "Delete task",    "error")
        print_menu_item("7", "Back",           "back")
        ch = get_menu_choice("  > ", [str(i) for i in range(1, 8)])
        if ch == "1":
            show(); input("Enter to continue…")
        elif ch == "2":
            show(False); input("Enter to continue…")
        elif ch == "3":
            show(True);  input("Enter to continue…")
        elif ch == "4":
            name = input("  Task name: ").strip()
            if name:
                prio = get_menu_choice("  Priority (high/medium/low): ",
                                       ["high","medium","low"])
                due  = input("  Due date (YYYY-MM-DD or blank): ").strip()
                tasks.append({
                    "name": name, "done": False,
                    "priority": prio,
                    "due": due or None,
                    "created": datetime.now().isoformat(),
                })
                save()
                print_status("Task added.", "success")
        elif ch == "5":
            show()
            idx = input("  Toggle number: ").strip()
            if idx.isdigit() and 0 <= int(idx) - 1 < len(tasks):
                tasks[int(idx) - 1]["done"] ^= True
                save()
                print_status("Toggled.", "success")
        elif ch == "6":
            show()
            idx = input("  Delete number: ").strip()
            if idx.isdigit() and 0 <= int(idx) - 1 < len(tasks):
                del tasks[int(idx) - 1]
                save()
                print_status("Deleted.", "success")
        elif ch == "7":
            break


# ── File Browser ──────────────────────────────────────────────────────────────

def brad_file_browser():
    current = BRADOS_FILES_DIR
    init_dirs()

    while True:
        clear_screen()
        print_header(f"File Browser — {current}", icon="app_files")
        try:
            entries = os.listdir(current)
        except OSError as e:
            print_status(f"Cannot read directory: {e}", "error")
            current = BRADOS_FILES_DIR
            continue
        dirs  = sorted([e for e in entries if os.path.isdir(os.path.join(current, e))])
        files = sorted([e for e in entries if os.path.isfile(os.path.join(current, e))])
        if dirs:
            print(f"  {Style.BOLD}Directories:{Style.RESET}")
            for i, d in enumerate(dirs):
                print(f"    {FG.BRIGHT_CYAN}{i+1:3}.  {get_icon('folder')} {d}/{Style.RESET}")
        if files:
            print(f"\n  {Style.BOLD}Files:{Style.RESET}")
            for i, f in enumerate(files):
                size = os.path.getsize(os.path.join(current, f))
                num  = len(dirs) + i + 1
                print(f"    {FG.BRIGHT_WHITE}{num:3}.  {get_icon('file')} {f:<32} {size:>8,} B{Style.RESET}")
        print_separator()
        print("  Commands: .. | cd <name> | open <file> | copy <src> <dst>")
        print("            move <src> <dst> | delete <name> | mkdir <name> | rename <old> <new> | exit")
        raw = input(f"{FG.BRIGHT_CYAN}  > {Style.RESET}").strip().split(maxsplit=2)
        if not raw: continue
        cmd = raw[0].lower()

        if cmd == "exit":
            break
        elif cmd == "..":
            parent = os.path.dirname(os.path.abspath(current))
            if os.path.abspath(current) != os.path.abspath(BRADOS_FILES_DIR):
                current = parent
        elif cmd == "cd" and len(raw) > 1:
            target = os.path.join(current, raw[1])
            if os.path.isdir(target):
                current = target
            else:
                print_status("Not a directory.", "error"); time.sleep(0.8)
        elif cmd == "open" and len(raw) > 1:
            path = os.path.join(current, raw[1])
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    print(f"\n{FG.BRIGHT_WHITE}── {raw[1]} ──{Style.RESET}")
                    print(content[:3000])
                    if len(content) > 3000:
                        print(f"  … ({len(content) - 3000} chars truncated)")
                    input("Enter to continue…")
                except Exception as e:
                    print_status(f"Read error: {e}", "error"); time.sleep(1)
            else:
                print_status("File not found.", "error"); time.sleep(0.8)
        elif cmd == "copy" and len(raw) >= 3:
            try:
                shutil.copy2(os.path.join(current, raw[1]),
                             os.path.join(current, raw[2]))
                print_status("Copied.", "success")
            except Exception as e:
                print_status(f"Copy failed: {e}", "error")
            time.sleep(0.8)
        elif cmd == "move" and len(raw) >= 3:
            try:
                shutil.move(os.path.join(current, raw[1]),
                            os.path.join(current, raw[2]))
                print_status("Moved.", "success")
            except Exception as e:
                print_status(f"Move failed: {e}", "error")
            time.sleep(0.8)
        elif cmd == "delete" and len(raw) > 1:
            path = os.path.join(current, raw[1])
            if os.path.exists(path):
                if input(f"  Delete '{raw[1]}'? (y/n): ").strip().lower() == "y":
                    (shutil.rmtree if os.path.isdir(path) else os.remove)(path)
                    print_status("Deleted.", "success")
            else:
                print_status("Not found.", "error")
            time.sleep(0.8)
        elif cmd == "mkdir" and len(raw) > 1:
            try:
                os.makedirs(os.path.join(current, raw[1]), exist_ok=False)
                print_status("Created.", "success")
            except FileExistsError:
                print_status("Already exists.", "warning")
            time.sleep(0.8)
        elif cmd == "rename" and len(raw) >= 3:
            try:
                os.rename(os.path.join(current, raw[1]),
                          os.path.join(current, raw[2]))
                print_status("Renamed.", "success")
            except Exception as e:
                print_status(f"Rename failed: {e}", "error")
            time.sleep(0.8)
        else:
            print_status("Unknown command.", "error"); time.sleep(0.8)


# ── Text Editor ───────────────────────────────────────────────────────────────

def brad_text_editor():
    init_dirs()
    filename = input("  File to open/create: ").strip()
    if not filename: return
    filepath = os.path.join(BRADOS_FILES_DIR, filename)
    lines: list[str] = []
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()

    _KW_COLORS = {
        "def": FG.BRIGHT_MAGENTA, "class": FG.BRIGHT_MAGENTA,
        "import": FG.BRIGHT_CYAN,  "from":  FG.BRIGHT_CYAN,
        "return": FG.BRIGHT_YELLOW,"yield": FG.BRIGHT_YELLOW,
        "if": FG.BRIGHT_BLUE,      "else":  FG.BRIGHT_BLUE,
        "elif": FG.BRIGHT_BLUE,    "for":   FG.BRIGHT_BLUE,
        "while": FG.BRIGHT_BLUE,   "with":  FG.BRIGHT_BLUE,
        "True": FG.BRIGHT_GREEN,   "False": FG.BRIGHT_RED,
        "None": FG.BRIGHT_BLACK,
    }

    def highlight(line: str) -> str:
        for kw, color in _KW_COLORS.items():
            line = re.sub(
                rf"\b{kw}\b",
                f"{color}{kw}{Style.RESET}",
                line,
                count=1
            )
        return line

    while True:
        clear_screen()
        print_header(f"Editor — {filename}", icon="app_editor")
        for i, line in enumerate(lines, 1):
            print(f"{FG.BRIGHT_BLACK}{i:4}{Style.RESET} {highlight(line.rstrip())}")
        print_separator()
        print("  .save  .exit  .del <n>  .ins <n> <text>  .replace <old> <new>  or type to append")
        cmd = input(f"{FG.BRIGHT_CYAN}  > {Style.RESET}").strip()
        if cmd == ".save":
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print_status("Saved.", "success"); time.sleep(0.8)
        elif cmd == ".exit":
            if input("  Save before exit? (y/n): ").strip().lower() == "y":
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                print_status("Saved.", "success")
            break
        elif cmd.startswith(".del "):
            try:
                n = int(cmd.split()[1]) - 1
                if 0 <= n < len(lines):
                    del lines[n]
                    print_status("Line deleted.", "success")
            except (ValueError, IndexError):
                print_status("Usage: .del <line_number>", "error")
            time.sleep(0.5)
        elif cmd.startswith(".ins "):
            parts = cmd.split(maxsplit=2)
            if len(parts) >= 3:
                try:
                    n = int(parts[1]) - 1
                    lines.insert(max(0, n), parts[2] + "\n")
                    print_status("Line inserted.", "success")
                except ValueError:
                    print_status("Usage: .ins <line_number> <text>", "error")
            time.sleep(0.5)
        elif cmd.startswith(".replace "):
            parts = cmd.split(maxsplit=2)
            if len(parts) == 3:
                old, new = parts[1], parts[2]
                count = sum(1 for line in lines if old in line)
                lines = [l.replace(old, new) for l in lines]
                print_status(f"Replaced {count} occurrence(s).", "success")
            time.sleep(0.5)
        elif cmd:
            lines.append(cmd + "\n")


# ── SVG Viewer ────────────────────────────────────────────────────────────────

def svg_viewer():
    print_header("SVG Viewer", icon="svg")
    filename = input("  SVG file path: ").strip()
    if not filename:
        return
    if not os.path.exists(filename):
        print_status("File not found.", "error")
        time.sleep(1)
        return
    try:
        from PIL import Image       # type: ignore
        import cairosvg              # type: ignore
        from io import BytesIO
        png = cairosvg.svg2png(url=filename)
        img = Image.open(BytesIO(png)).convert("L")
        w   = get_dynamic_width() - 4
        img.thumbnail((w, w // 2))
        chars = " .:-=+*#%@"
        pixels = list(img.getdata())
        for y in range(img.height):
            row = "".join(chars[pixels[y * img.width + x] * len(chars) // 256]
                          for x in range(img.width))
            print(row)
        print_status("SVG rendered as ASCII art.", "success")
    except ImportError:
        print_status("cairosvg + Pillow required: pip install cairosvg pillow", "warning")
    except Exception as e:
        print_status(f"Render error: {e}", "error")
    input("Enter to continue…")


# ── BradBrowser ───────────────────────────────────────────────────────────────

def brad_browser():
    init_dirs()
    try:
        import requests         # type: ignore
        WEB = True
    except ImportError:
        WEB = False
        print_status("pip install requests  to enable real web browsing", "warning")
        time.sleep(1.5)

    pages_dir = os.path.join(BRADOS_BROWSER_DIR, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    homepage  = os.path.join(pages_dir, "home.html")
    if not os.path.exists(homepage):
        with open(homepage, "w") as f:
            f.write("<html><body><h1>BradNet</h1>"
                    "<p>Welcome to BradOS local web.</p>"
                    "<a href='about.html'>About</a></body></html>")

    bm_file   = os.path.join(BRADOS_BROWSER_DIR, "bookmarks.json")
    bookmarks: list[str] = []
    if os.path.exists(bm_file):
        try:
            with open(bm_file) as f:
                bookmarks = json.load(f)
        except Exception:
            bookmarks = []

    history:     list[str] = []
    current_url: str       = "home"
    is_web: bool           = False

    def is_web_url(url: str) -> bool:
        return url.startswith(("http://", "https://")) or ("." in url and not url.endswith(".html"))

    def fetch_web(url: str) -> tuple[str, str | None]:
        if not WEB:
            return "", "Install requests: pip install requests"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "BradOS/2.0"})
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "html" in ct:
                return html_to_text(resp.text), None
            return f"[Binary content: {ct}]", None
        except Exception as e:
            return "", str(e)

    def load_local(name: str) -> tuple[str, list[str], str | None]:
        name = name.rstrip("/")
        if not name.endswith(".html"):
            name += ".html"
        path = os.path.join(pages_dir, name)
        if not os.path.exists(path):
            return "", [], f"Local page '{name}' not found."
        with open(path) as f:
            raw = f.read()
        links = re.findall(r'href=["\']([^"\']+\.html?)["\']', raw)
        return html_to_text(raw), links, None

    def do_fetch():
        nonlocal current_url, is_web
        if is_web:
            text, err = fetch_web(current_url)
        else:
            text, links, err = load_local(current_url)
        return text or "", err

    while True:
        print_header(f"BradBrowser — {current_url}", icon="app_browser")
        text, err = do_fetch()
        if err:
            print_status(err, "error")
            text = ""
        _, term_h = get_terminal_size()
        lines     = text.split("\n")
        for line in lines[:max(5, term_h - 18)]:
            print(f"  {line}")
        if len(lines) > term_h - 18:
            print(f"  … ({len(lines) - (term_h - 18)} more lines)")
        print_separator()
        print_menu_item("g", f"Go to URL  (web: {'on' if is_web else 'off'})", "network")
        print_menu_item("b", f"Bookmarks ({len(bookmarks)})", "app_browser")
        print_menu_item("a", "Add bookmark",  "success")
        print_menu_item("h", f"History ({len(history)})", "logs")
        print_menu_item("l", "Local pages",   "app_files")
        print_menu_item("r", "Reload",        "warning")
        print_menu_item("q", "Back",          "back")
        ch = input(f"{FG.BRIGHT_CYAN}  > {Style.RESET}").strip().lower()

        if ch == "q":
            atomic_write_json(bm_file, bookmarks)
            break
        elif ch == "r":
            pass   # just re-renders
        elif ch == "g":
            url = input("  URL: ").strip()
            if url:
                is_web = is_web_url(url)
                current_url = url
                history.append(url)
        elif ch == "b":
            for i, bm in enumerate(bookmarks):
                print(f"  {i+1}. {bm}")
            idx = input("  Open number (or Enter to cancel): ").strip()
            if idx.isdigit():
                i = int(idx) - 1
                if 0 <= i < len(bookmarks):
                    current_url = bookmarks[i]
                    is_web = is_web_url(current_url)
                    history.append(current_url)
        elif ch == "a":
            if current_url not in bookmarks:
                bookmarks.append(current_url)
                print_status("Bookmarked.", "success")
                time.sleep(0.8)
        elif ch == "h":
            for i, u in enumerate(reversed(history[-15:])):
                print(f"  {i+1}. {u}")
            idx = input("  Open number: ").strip()
            if idx.isdigit():
                i = int(idx) - 1
                url = list(reversed(history[-15:]))[i]
                current_url = url
                is_web = is_web_url(url)
        elif ch == "l":
            pages = [f for f in os.listdir(pages_dir) if f.endswith(".html")]
            for i, p in enumerate(pages):
                print(f"  {i+1}. {p}")
            idx = input("  Number: ").strip()
            if idx.isdigit():
                i = int(idx) - 1
                if 0 <= i < len(pages):
                    current_url = pages[i].replace(".html", "")
                    is_web = False
                    history.append(current_url)
        time.sleep(0.3)

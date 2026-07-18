# brados_brash.py — BradOS Brash Shell v1.0
#
# A standalone, embeddable interactive shell module for Textual apps.
# Inspired by bash + fish — VFS-backed, with pipes, redirects, history,
# autosuggestions, customizable prompts, and host fallback.

from __future__ import annotations

import os
import re
import sys
import json
import time
import asyncio
import logging
import textwrap
import platform
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from textual.widgets import RichLog, Input, Static
    from brados_vfs import VirtualFileSystem

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger("brados.brash")

HISTORY_MAX = 1000
HISTORY_FILE = os.path.join("brados_files", "var", "brash_history.json")

COMMON_COMMANDS: dict[str, str] = {
    "python": "Run Python interpreter",
    "pip":    "Python package manager",
    "git":    "Distributed version control",
    "npm":    "Node.js package manager",
    "docker": "Container platform",
    "ls":     "List directory contents",
    "cd":     "Change directory",
    "cat":    "Concatenate and print files",
    "rm":     "Remove files or directories",
    "mkdir":  "Create directories",
    "cp":     "Copy files",
    "mv":     "Move/rename files",
    "ps":     "List running processes",
    "kill":   "Terminate processes",
    "chmod":  "Change file permissions",
    "grep":   "Search text with patterns",
    "find":   "Search for files",
    "echo":   "Print text to stdout",
    "clear":  "Clear the terminal",
    "exit":   "Exit the shell",
    "help":   "Show help for built-in commands",
    "env":    "Print environment variables",
    "pwd":    "Print working directory",
    "alias":  "Create or list command aliases",
    "unalias":"Remove a command alias",
}

DEFAULT_PROMPT_TEMPLATE = "{user}@brados:{cwd}$ "
COLORED_PROMPT_TEMPLATE = (
    "[#2ed573]{user}[/][#7f8c8d]@brados[/][#00d4ff]:[/]"
    "[#ffa502]{short_cwd}[/][#00d4ff]$ [/]"
)


@dataclass
class Redirect:
    mode: str
    target: str


@dataclass
class PipelineSegment:
    command: str
    args: list[str] = field(default_factory=list)
    redirect: Redirect | None = None


@dataclass
class Pipeline:
    segments: list[PipelineSegment] = field(default_factory=list)


class BrashParser:
    """Parse a command string into a Pipeline AST.

    Handles quotes ("" and ''), env vars ($VAR, ${VAR}),
    pipes (|), and redirects (>, >>).
    """

    @classmethod
    def parse(cls, text: str) -> Pipeline:
        parts = cls._split_pipes(text)
        return Pipeline(segments=[cls._parse_seg(s) for s in parts])

    @staticmethod
    def _split_pipes(text: str) -> list[str]:
        parts, current = [], ""
        in_single = in_double = False
        for ch in text:
            if ch == "'" and not in_double:
                in_single = not in_single
            elif ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "|" and not in_single and not in_double:
                parts.append(current.strip())
                current = ""
                continue
            current += ch
        if current.strip():
            parts.append(current.strip())
        return parts

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens, cur = [], ""
        in_single = in_double = False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == "'" and not in_double:
                in_single = not in_single; i += 1; continue
            if ch == '"' and not in_single:
                in_double = not in_double; i += 1; continue
            if ch == "\\" and i + 1 < len(text):
                cur += text[i + 1]; i += 2; continue
            if ch == "$" and not in_single:
                if i + 1 < len(text) and text[i + 1] == "{":
                    end = text.find("}", i + 2)
                    if end > i:
                        cur += os.environ.get(text[i + 2:end], "")
                        i = end + 1; continue
                else:
                    j = i + 1
                    while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                        j += 1
                    cur += os.environ.get(text[i + 1:j], "")
                    i = j; continue
            if ch in " \t" and not in_single and not in_double:
                if cur:
                    tokens.append(cur); cur = ""
                i += 1; continue
            cur += ch; i += 1
        if cur:
            tokens.append(cur)
        return tokens

    @staticmethod
    def _parse_seg(text: str) -> PipelineSegment:
        redirect = None
        m = re.search(r"(>>|>)", text)
        if m:
            idx = m.start()
            cmd_part = text[:idx].strip()
            mode = m.group(1)
            target = text[idx + len(mode):].strip()
            redirect = Redirect(mode=mode, target=target)
        else:
            cmd_part = text.strip()
        tokens = BrashParser._tokenize(cmd_part)
        return PipelineSegment(
            command=tokens[0] if tokens else "",
            args=tokens[1:] if len(tokens) > 1 else [],
            redirect=redirect,
        )


class BrashHistory:
    """In-memory command history with persistent JSON storage (singleton)."""

    _instance: BrashHistory | None = None
    _entries: list[str]

    def __new__(cls) -> BrashHistory:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._entries = []
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._entries = data[:HISTORY_MAX]
        except Exception as e:
            logger.warning("Failed to load history: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._entries, f)
            os.replace(tmp, HISTORY_FILE)
        except Exception as e:
            logger.warning("Failed to save history: %s", e)

    def add(self, cmd: str) -> None:
        if not cmd.strip():
            return
        if cmd in self._entries:
            self._entries.remove(cmd)
        self._entries.insert(0, cmd)
        if len(self._entries) > HISTORY_MAX:
            self._entries = self._entries[:HISTORY_MAX]
        self._save()

    def all(self) -> list[str]:
        return list(self._entries)

    def search(self, query: str) -> list[str]:
        q = query.lower()
        return [e for e in self._entries if q in e.lower()]

    def __len__(self) -> int:
        return len(self._entries)


class BrashShell:
    """A standalone interactive shell widget for BradOS.

    Wraps a RichLog (output), Input (input), and Static (prompt) to
    provide a complete shell experience backed by the VFS.
    """

    def __init__(
        self,
        log: RichLog,
        inp: Input,
        prompt: Static,
        vfs: "VirtualFileSystem | None" = None,
        cwd: str = "/home",
        hostname: str = "brados",
    ):
        self.log = log
        self.inp = inp
        self.prompt_widget = prompt
        self.vfs = vfs
        self._cwd = cwd
        self._hostname = hostname
        self._username = "brad"
        self._prompt_template = COLORED_PROMPT_TEMPLATE
        self._exit_requested = False

        self._history = BrashHistory()
        self._hist_idx = 0
        self._last_prefix = ""
        self._last_suggestion = ""
        self._last_status = 0

        self._aliases: dict[str, str] = {}
        self._alias_path = "/home/.brash_aliases.json"
        self._load_aliases()

        self._builtins: dict[str, Callable] = {
            "cd":    self._cmd_cd, "pwd":  self._cmd_pwd,
            "ls":    self._cmd_ls, "cat":  self._cmd_cat,
            "echo":  self._cmd_echo,"clear":self._cmd_clear,
            "rm":    self._cmd_rm, "mkdir":self._cmd_mkdir,
            "cp":    self._cmd_cp, "mv":   self._cmd_mv,
            "ps":    self._cmd_ps, "env":  self._cmd_env,
            "exit":  self._cmd_exit,"help": self._cmd_help,
            "alias": self._cmd_alias, "unalias": self._cmd_unalias,
        }

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def exit_requested(self) -> bool:
        return self._exit_requested

    @property
    def cwd(self) -> str:
        return self._cwd

    @cwd.setter
    def cwd(self, val: str) -> None:
        self._cwd = val
        self.refresh_prompt()

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, val: str) -> None:
        self._username = val
        self.refresh_prompt()

    # ── Prompt ───────────────────────────────────────────────────────────

    def refresh_prompt(self) -> None:
        short_cwd = self._cwd.replace("/home", "~", 1) if self._cwd.startswith("/home") else self._cwd
        text = self._prompt_template.format(
            user=self._username, cwd=self._cwd,
            short_cwd=short_cwd, hostname=self._hostname,
            time=datetime.now().strftime("%H:%M:%S"),
        )
        try:
            self.prompt_widget.update(text)
        except Exception:
            pass

    def set_prompt_template(self, template: str) -> None:
        self._prompt_template = template
        self.refresh_prompt()

    def write_output(self, text: str, markup: bool = True) -> None:
        try:
            if markup:
                self.log.write(text)
            else:
                self.log.write(text, markup=False)
        except Exception:
            pass

    # ── Main input handler ──────────────────────────────────────────────

    async def handle_input(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.refresh_prompt()
            return

        self._history.add(text)

        short_cwd = self._cwd.replace("/home", "~", 1) if self._cwd.startswith("/home") else self._cwd
        echo_line = self._prompt_template.format(
            user=self._username, cwd=self._cwd,
            short_cwd=short_cwd, hostname=self._hostname,
            time=datetime.now().strftime("%H:%M:%S"),
        ) + text
        self.write_output(echo_line.rstrip())

        for seg_text, connector in self._split_chain(text):
            if connector == "and" and self._last_status != 0:
                continue    # previous command failed — skip the &&-gated one
            if connector == "or" and self._last_status == 0:
                continue    # previous command succeeded — skip the ||-gated one
            expanded = self._expand_aliases(seg_text)
            pipeline = BrashParser.parse(expanded)
            self._last_status = await self._execute_pipeline(pipeline)

        self.refresh_prompt()

    @staticmethod
    def _split_chain(text: str) -> list[tuple[str, str | None]]:
        """Split on top-level ';', '&&', '||' (outside quotes). Each pipe
        ('|') stage is left untouched — that's still handled by BrashParser.
        Returns (segment_text, connector_before_this_segment); connector is
        None for the first segment, else 'and' / 'or' / 'seq'."""
        segments: list[tuple[str, str | None]] = []
        buf: list[str] = []
        connector: str | None = None
        in_squote = in_dquote = False
        i, n = 0, len(text)
        while i < n:
            c = text[i]
            if c == "'" and not in_dquote:
                in_squote = not in_squote
                buf.append(c); i += 1; continue
            if c == '"' and not in_squote:
                in_dquote = not in_dquote
                buf.append(c); i += 1; continue
            if not in_squote and not in_dquote:
                if text[i:i + 2] == "&&":
                    segments.append(("".join(buf).strip(), connector))
                    buf, connector = [], "and"
                    i += 2; continue
                if text[i:i + 2] == "||":
                    segments.append(("".join(buf).strip(), connector))
                    buf, connector = [], "or"
                    i += 2; continue
                if c == ";":
                    segments.append(("".join(buf).strip(), connector))
                    buf, connector = [], "seq"
                    i += 1; continue
            buf.append(c); i += 1
        segments.append(("".join(buf).strip(), connector))
        return [(s, c) for s, c in segments if s]

    # ── Aliases ───────────────────────────────────────────────────────────

    def _load_aliases(self) -> None:
        if not self.vfs:
            return
        try:
            if self.vfs.exists(self._alias_path):
                self._aliases = json.loads(self.vfs.read_text(self._alias_path))
        except Exception:
            pass    # corrupt/missing alias file — start fresh rather than crash the shell

    def _save_aliases(self) -> None:
        if not self.vfs:
            return
        try:
            self.vfs.write_text(self._alias_path, json.dumps(self._aliases))
        except Exception:
            pass

    def _expand_aliases(self, text: str, _depth: int = 0) -> str:
        """Expand only the leading command word of a chain segment (the
        common case: `alias gs='git status'` then typing `gs`). Aliases
        aren't expanded for later stages of a pipe — e.g. in `cat f | gs`
        only `cat` would be checked — since that needs re-entering the
        pipe-aware parser per stage, which BrashParser doesn't expose yet."""
        if _depth > 10 or not text.strip():
            return text
        parts = text.split(None, 1)
        first = parts[0]
        if first in self._aliases:
            rest = parts[1] if len(parts) > 1 else ""
            expanded = self._aliases[first] + (" " + rest if rest else "")
            return self._expand_aliases(expanded, _depth + 1)
        return text

    def _cmd_alias(self, args: list[str], **kw) -> str:
        if not args:
            if not self._aliases:
                return "[#7f8c8d]No aliases defined[/]\n"
            return "\n".join(f"alias {k}='{v}'" for k, v in sorted(self._aliases.items())) + "\n"
        joined = " ".join(args)
        if "=" not in joined:
            name = args[0]
            if name in self._aliases:
                return f"alias {name}='{self._aliases[name]}'\n"
            return f"alias: {name}: not found\n"
        name, _, value = joined.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if not name:
            return "Usage: alias name='command'\n"
        self._aliases[name] = value
        self._save_aliases()
        return ""

    def _cmd_unalias(self, args: list[str], **kw) -> str:
        if not args:
            return "Usage: unalias <name>\n"
        name = args[0]
        if name in self._aliases:
            del self._aliases[name]
            self._save_aliases()
            return ""
        return f"unalias: {name}: not found\n"

    # ── Pipeline execution ──────────────────────────────────────────────

    async def _execute_pipeline(self, pipeline: Pipeline) -> int:
        """Run a (possibly piped) command sequence. Returns an exit status:
        0 for success, 1 for failure — used by &&/|| chaining. A builtin
        counts as failed if it raised, or if its output follows this
        codebase's existing error convention (`"cmd: ..."` or `"Usage: ..."`,
        already used throughout the _cmd_* methods below)."""
        pipe_buf: str | None = None
        status = 0
        for idx, seg in enumerate(pipeline.segments):
            is_last = idx == len(pipeline.segments) - 1
            cmd, args = seg.command, seg.args
            if not cmd:
                continue

            if cmd in self._builtins:
                try:
                    output = self._builtins[cmd](args, stdin=pipe_buf)
                    stripped = (output or "").lstrip()
                    status = 1 if (stripped.startswith(f"{cmd}: ") or stripped.startswith("Usage:")) else 0
                except Exception as e:
                    output = f"{cmd}: {e}\n"
                    status = 1
            else:
                output, status = await self._exec_host(cmd, args, pipe_buf)

            if seg.redirect:
                self._handle_redirect(output or "", seg.redirect)
                return status

            if is_last:
                if output:
                    for line in output.rstrip("\n").split("\n"):
                        self.write_output(line)
            else:
                pipe_buf = output or ""
        return status

    def _handle_redirect(self, output: str, redir: Redirect) -> None:
        if not self.vfs:
            self.write_output("[#ff4757]VFS not available for redirect[/]")
            return
        try:
            if redir.mode == ">":
                self.vfs.write_text(redir.target, output)
            elif redir.mode == ">>":
                existing = self.vfs.read_text(redir.target) if self.vfs.exists(redir.target) else ""
                self.vfs.write_text(redir.target, existing + output)
        except Exception as e:
            self.write_output(f"[#ff4757]Error writing {redir.target}: {e}[/]")

    async def _exec_host(self, cmd: str, args: list[str], stdin: str | None) -> tuple[str, int]:
        full = cmd + " " + " ".join(args) if args else cmd
        lines: list[str] = []
        try:
            proc = await asyncio.create_subprocess_shell(
                full,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                cwd=self._cwd if os.path.isdir(self._cwd) else None,
                env={**os.environ, "TERM": "xterm-256color", "PYTHONUNBUFFERED": "1"},
            )
            if stdin is not None and proc.stdin:
                proc.stdin.write(stdin.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                clean = re.sub(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhil]", "", line)
                if clean:
                    lines.append(clean)
            await proc.wait()
            status = proc.returncode or 0
        except Exception as e:
            lines.append(f"Error: {e}")
            status = 1
        output = "\n".join(lines) + ("\n" if lines else "")
        return output, status

    # ── Built-in commands ────────────────────────────────────────────────

    def _resolve(self, path: str) -> str:
        return (Path(self._cwd) / path).as_posix() if not path.startswith("/") else path

    def _cmd_cd(self, args: list[str], **kw) -> str:
        target = args[0] if args else "/home"
        target = os.path.normpath(self._resolve(target))
        if self.vfs:
            try:
                if self.vfs.exists(target) and self.vfs.stat(target).is_dir:
                    self._cwd = target
                    self.refresh_prompt()
                    return ""
            except Exception:
                pass
        else:
            if os.path.isdir(target):
                self._cwd = target
                self.refresh_prompt()
                return ""
        return f"cd: {args[0] if args else ''}: No such directory\n"

    def _cmd_pwd(self, args: list[str], **kw) -> str:
        return self._cwd + "\n"

    def _cmd_ls(self, args: list[str], **kw) -> str:
        target = self._resolve(args[0]) if args else self._cwd
        if self.vfs:
            try:
                entries = self.vfs.listdir(target)
            except Exception as e:
                return f"ls: {e}\n"
        else:
            try:
                entries = sorted(os.listdir(target))
            except OSError as e:
                return f"ls: {e}\n"
        lines = []
        for e in entries:
            full = target.rstrip("/") + "/" + e
            is_dir = False
            if self.vfs:
                try:
                    is_dir = self.vfs.stat(full).is_dir
                except Exception:
                    pass
            else:
                is_dir = os.path.isdir(full)
            name = f"[#00d4ff]{e}/[/]" if is_dir else f"[#ecf0f1]{e}[/]"
            lines.append(name)
        cols = 4
        out = ""
        for i in range(0, len(lines), cols):
            out += "  " + "  ".join(f"{p:<25}" for p in lines[i:i+cols]) + "\n"
        return out

    def _cmd_cat(self, args: list[str], **kw) -> str:
        if not args:
            return "Usage: cat <file>\n"
        path = self._resolve(args[0])
        max_lines = 200
        if self.vfs:
            try:
                content = self.vfs.read_text(path)
                lines = content.split("\n")
                return "\n".join(lines[:max_lines]) + ("\n" if len(lines) > max_lines else "")
            except Exception as e:
                return f"{e}\n"
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[:max_lines])
        except OSError as e:
            return f"{e}\n"

    def _cmd_echo(self, args: list[str], **kw) -> str:
        return " ".join(args) + "\n"

    def _cmd_clear(self, args: list[str], **kw) -> str:
        try:
            self.log.clear()
        except Exception:
            pass
        return ""

    def _cmd_rm(self, args: list[str], **kw) -> str:
        if not args:
            return "Usage: rm <path>\n"
        path = self._resolve(args[0])
        if self.vfs:
            try:
                self.vfs.unlink(path)
                return ""
            except Exception as e:
                return f"rm: {e}\n"
        try:
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.unlink(path)
            return ""
        except OSError as e:
            return f"rm: {e}\n"

    def _cmd_mkdir(self, args: list[str], **kw) -> str:
        if not args:
            return "Usage: mkdir <path>\n"
        path = self._resolve(args[0])
        if self.vfs:
            try:
                self.vfs.mkdir(path)
                return ""
            except Exception as e:
                return f"mkdir: {e}\n"
        try:
            os.makedirs(path, exist_ok=True)
            return ""
        except OSError as e:
            return f"mkdir: {e}\n"

    def _cmd_cp(self, args: list[str], **kw) -> str:
        if len(args) < 2:
            return "Usage: cp <src> <dst>\n"
        src, dst = self._resolve(args[0]), self._resolve(args[1])
        if self.vfs:
            try:
                data = self.vfs.read(src)
                self.vfs.write(dst, data)
                return ""
            except Exception as e:
                return f"cp: {e}\n"
        try:
            import shutil
            shutil.copy2(src, dst)
            return ""
        except OSError as e:
            return f"cp: {e}\n"

    def _cmd_mv(self, args: list[str], **kw) -> str:
        if len(args) < 2:
            return "Usage: mv <src> <dst>\n"
        src, dst = self._resolve(args[0]), self._resolve(args[1])
        if self.vfs:
            try:
                self.vfs.rename(src, dst)
                return ""
            except Exception as e:
                return f"mv: {e}\n"
        try:
            os.rename(src, dst)
            return ""
        except OSError as e:
            return f"mv: {e}\n"

    def _cmd_ps(self, args: list[str], **kw) -> str:
        if HAS_PSUTIL:
            lines = [f"{'PID':>6}  {'NAME':<24}  {'CPU%':>5}  {'MEM%':>5}"]
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    i = p.info
                    lines.append(f"{i['pid']:>6}  {i['name'][:24]:<24}  "
                                 f"{i['cpu_percent'] or 0:>5.1f}  {i['memory_percent'] or 0:>5.1f}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return "\n".join(lines) + "\n"
        return (f"{'PID':>6}  {'NAME':<24}  {'STATE':>8}\n"
                f"{1:>6}  {'brados_init':<24}  {'running':>8}\n"
                f"{2:>6}  {'brados_shell':<24}  {'running':>8}\n")

    def _cmd_env(self, args: list[str], **kw) -> str:
        return "\n".join(
            f"[#7f8c8d]{k}[/]=[#ecf0f1]{v}[/]" for k, v in sorted(os.environ.items())
        ) + "\n"

    def _cmd_exit(self, args: list[str], **kw) -> str:
        self._exit_requested = True
        return ""

    def _cmd_help(self, args: list[str], **kw) -> str:
        lines = ["[bold #00d4ff]Brash — Built-in commands:[/]"]
        items = [
            ("cd <dir>",     "Change directory via VFS"),
            ("pwd",          "Print working directory"),
            ("ls [path]",    "List directory contents"),
            ("cat <file>",   "Print file contents"),
            ("echo <...>",   "Print text"),
            ("clear",        "Clear the terminal"),
            ("rm <path>",    "Remove file or directory"),
            ("mkdir <path>", "Create directory"),
            ("cp <src> <dst>","Copy file"),
            ("mv <src> <dst>","Move/rename file"),
            ("ps",           "List running processes"),
            ("env",          "Print environment variables"),
            ("alias [n=cmd]","Create/list aliases (no args: list all)"),
            ("unalias <n>",  "Remove an alias"),
            ("exit",         "Exit the shell"),
            ("help",         "Show this help message"),
        ]
        for name, desc in items:
            lines.append(f"  [#00d4ff]{name:<20}[/] [#7f8c8d]{desc}[/]")
        lines.append("")
        lines.append("[bold #00d4ff]Chaining:[/] [#7f8c8d]cmd1 ; cmd2[/] runs both  ·  "
                     "[#7f8c8d]cmd1 && cmd2[/] runs cmd2 only if cmd1 succeeded  ·  "
                     "[#7f8c8d]cmd1 || cmd2[/] runs cmd2 only if cmd1 failed")
        lines.append("[#7f8c8d]All other commands are forwarded to the host shell.[/]")
        return "\n".join(lines) + "\n"

    # ── Autosuggestions ─────────────────────────────────────────────────

    def autocomplete_suggest(self, prefix: str) -> str | None:
        if not prefix:
            self._last_prefix = ""
            self._last_suggestion = ""
            return None
        prefix_lower = prefix.lower()
        candidates: dict[str, int] = {}
        for idx, entry in enumerate(self._history.all()):
            if entry.lower().startswith(prefix_lower) and entry != prefix:
                candidates[entry] = len(self._history) - idx
        for cmd in COMMON_COMMANDS:
            if cmd.lower().startswith(prefix_lower) and cmd != prefix:
                score = candidates.get(cmd, 0) + 1
                candidates[cmd] = score
        if not candidates:
            self._last_prefix = ""
            self._last_suggestion = ""
            return None
        best = max(candidates, key=lambda k: candidates[k])
        self._last_prefix = prefix
        self._last_suggestion = best[len(prefix):]
        return self._last_suggestion

    def accept_suggestion(self) -> str | None:
        if self._last_suggestion:
            return self._last_prefix + self._last_suggestion
        return None

    # ── History navigation & search ─────────────────────────────────────

    def search_history(self, query: str) -> list[str]:
        return self._history.search(query) if query else []

    def history_up(self) -> str | None:
        entries = self._history.all()
        if not entries:
            return None
        if self._hist_idx < len(entries):
            self._hist_idx += 1
        return entries[self._hist_idx - 1] if self._hist_idx > 0 else None

    def history_down(self) -> str | None:
        if self._hist_idx <= 0:
            return None
        self._hist_idx -= 1
        if self._hist_idx == 0:
            return ""
        return self._history.all()[self._hist_idx - 1]

    def reset_history_index(self) -> None:
        self._hist_idx = 0

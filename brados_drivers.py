# brados_drivers.py — BradOS Driver Subsystem v1.0
#
# 6 drivers. Real TCP/UDP via the host kernel. Terminal size/color probing.
# VFS-backed block storage. Pub/sub input routing. Process spawn/wait/kill.
# Graceful degradation: if a driver fails, it registers as "degraded" instead
# of crashing the system. The registry pattern keeps everything decoupled.

from __future__ import annotations

import os
import sys
import time
import socket
import shutil
import logging
import platform
import subprocess
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("brados.drivers")


# ── Base ──────────────────────────────────────────────────────────────────────

@dataclass
class DriverInfo:
    name:    str
    version: str
    status:  str          # "active" | "degraded" | "failed"
    detail:  str = ""


class Driver(ABC):
    """Abstract base for all BradOS hardware/software drivers."""

    name:    str = "unknown"
    version: str = "0.0.0"

    @abstractmethod
    def init(self) -> bool:
        """Initialise the driver.  Returns True on success."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release all resources."""

    def ioctl(self, command: int, arg: Any = None) -> Any:
        """Device control — override for device-specific operations."""
        raise NotImplementedError(f"{self.name}: ioctl({command}) not implemented")

    @property
    def info(self) -> DriverInfo:
        return DriverInfo(self.name, self.version, "active")


# ── Registry ──────────────────────────────────────────────────────────────────

class DriverRegistry:
    """Central driver registry.

    Usage:
        registry = DriverRegistry()
        registry.register(NetworkDriver())
        net = registry.get(NetworkDriver)
    """

    def __init__(self):
        self._drivers:  dict[str, Driver]  = {}
        self._lock      = threading.Lock()

    def register(self, driver: Driver) -> bool:
        """Initialise and register a driver.  Returns True on success."""
        try:
            ok = driver.init()
        except Exception as e:
            logger.error(f"Driver {driver.name} init failed: {e}")
            ok = False
        with self._lock:
            self._drivers[driver.name] = driver
        if ok:
            logger.info(f"Driver {driver.name} v{driver.version} registered")
        else:
            logger.warning(f"Driver {driver.name} registered in degraded state")
        return ok

    def get(self, key: type | str) -> Optional[Driver]:
        name = key if isinstance(key, str) else key.name
        with self._lock:
            return self._drivers.get(name)

    def require(self, key: type | str) -> Driver:
        driver = self.get(key)
        if driver is None:
            name = key if isinstance(key, str) else key.name
            raise RuntimeError(f"Required driver '{name}' is not registered")
        return driver

    def shutdown_all(self) -> None:
        with self._lock:
            drivers = list(self._drivers.values())
        for d in reversed(drivers):
            try:
                d.shutdown()
                logger.info(f"Driver {d.name} shut down")
            except Exception as e:
                logger.error(f"Driver {d.name} shutdown error: {e}")

    def list_all(self) -> list[DriverInfo]:
        with self._lock:
            return [d.info for d in self._drivers.values()]


# ── NetworkDriver ─────────────────────────────────────────────────────────────

class NetworkDriver(Driver):
    """Real TCP/UDP networking via the host OS socket API.

    Maintains a per-process file-descriptor table (integers → sockets).
    The kernel uses this to serve SYSCALL_NET_* without importing socket directly.
    """

    name    = "brados_net"
    version = "1.0.0"

    # IOCTL command codes
    IOCTL_SET_TIMEOUT   = 0x01
    IOCTL_GET_HOSTNAME  = 0x02
    IOCTL_GET_LOCAL_IP  = 0x03
    IOCTL_INTERFACES    = 0x04

    def __init__(self):
        self._fd_table: dict[int, socket.socket] = {}
        self._next_fd   = 100
        self._lock      = threading.Lock()

    def init(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                return True
        except OSError as e:
            logger.warning(f"Network init: {e}")
            return False

    def shutdown(self) -> None:
        with self._lock:
            for fd, sock in list(self._fd_table.items()):
                try:
                    sock.close()
                except Exception:
                    pass
            self._fd_table.clear()

    # ── DNS ───────────────────────────────────────────────────────────────

    def resolve(self, hostname: str) -> str:
        """DNS A-record lookup.  Returns IP string."""
        try:
            return socket.gethostbyname(hostname)
        except socket.gaierror as e:
            raise OSError(f"DNS resolution failed for '{hostname}': {e}") from e

    def resolve_all(self, hostname: str) -> list[str]:
        """Return all IPs for a hostname."""
        try:
            results = socket.getaddrinfo(hostname, None)
            return list({r[4][0] for r in results})
        except socket.gaierror:
            return []

    # ── Socket lifecycle ─────────────────────────────────────────────────

    def tcp_connect(self, host: str, port: int, timeout: float = 10.0) -> int:
        """Connect TCP; return fd."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except Exception:
            sock.close()
            raise
        return self._register(sock)

    def udp_socket(self) -> int:
        """Create an unconnected UDP socket; return fd."""
        return self._register(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))

    def tcp_listen(self, port: int, backlog: int = 5) -> int:
        """Bind a listening TCP socket; return fd."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(backlog)
        return self._register(sock)

    def accept(self, fd: int) -> tuple[int, tuple[str, int]]:
        """Accept an incoming connection; return (new_fd, (addr, port))."""
        client_sock, addr = self._get(fd).accept()
        return self._register(client_sock), addr

    def send(self, fd: int, data: bytes) -> int:
        return self._get(fd).send(data)

    def recv(self, fd: int, size: int = 65536) -> bytes:
        return self._get(fd).recv(size)

    def sendto(self, fd: int, data: bytes, host: str, port: int) -> int:
        return self._get(fd).sendto(data, (host, port))

    def recvfrom(self, fd: int, size: int = 65536) -> tuple[bytes, tuple]:
        return self._get(fd).recvfrom(size)

    def close(self, fd: int) -> None:
        with self._lock:
            sock = self._fd_table.pop(fd, None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def set_timeout(self, fd: int, timeout: float) -> None:
        self._get(fd).settimeout(timeout)

    # ── HTTP convenience (used by browser) ───────────────────────────────

    def http_get(self, url: str, timeout: float = 15.0,
                 headers: dict | None = None) -> tuple[int, dict, bytes]:
        """Minimal HTTP/HTTPS GET.  Returns (status, headers, body).
        Uses `requests` if available, falls back to stdlib http.client."""
        try:
            import requests                             # type: ignore
            h = {"User-Agent": "BradOS/3.0", **(headers or {})}
            r = requests.get(url, timeout=timeout, headers=h)
            return r.status_code, dict(r.headers), r.content
        except ImportError:
            pass
        # stdlib fallback (HTTP only, no HTTPS without ssl context)
        from urllib.request import urlopen, Request
        from urllib.error import URLError
        req = Request(url, headers={"User-Agent": "BradOS/3.0", **(headers or {})})
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except URLError as e:
            raise OSError(str(e)) from e

    # ── IOCTL ─────────────────────────────────────────────────────────────

    def ioctl(self, command: int, arg: Any = None) -> Any:
        if command == self.IOCTL_GET_HOSTNAME:
            return socket.gethostname()
        if command == self.IOCTL_GET_LOCAL_IP:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"
        if command == self.IOCTL_INTERFACES:
            return self._get_interfaces()
        if command == self.IOCTL_SET_TIMEOUT and arg:
            fd, timeout = arg
            self.set_timeout(fd, timeout)
            return 0
        raise NotImplementedError(f"NetworkDriver: unknown ioctl {command}")

    # ── Internals ─────────────────────────────────────────────────────────

    def _register(self, sock: socket.socket) -> int:
        with self._lock:
            fd = self._next_fd
            self._next_fd += 1
            self._fd_table[fd] = sock
        return fd

    def _get(self, fd: int) -> socket.socket:
        with self._lock:
            if fd not in self._fd_table:
                raise OSError(f"Bad socket fd: {fd}")
            return self._fd_table[fd]

    @staticmethod
    def _get_interfaces() -> list[dict]:
        try:
            import psutil                               # type: ignore
            return [
                {"name": name, "addrs": [a.address for a in addrs
                                         if a.family == socket.AF_INET]}
                for name, addrs in psutil.net_if_addrs().items()
            ]
        except ImportError:
            return [{"name": "lo", "addrs": ["127.0.0.1"]}]


# ── DisplayDriver ─────────────────────────────────────────────────────────────

class DisplayDriver(Driver):
    """Terminal display capabilities.

    Probes terminal size, colour depth, Unicode/emoji support.
    The Textual app uses this to adapt layout and icon rendering.
    """

    name    = "brados_display"
    version = "1.0.0"

    IOCTL_GET_SIZE       = 0x10
    IOCTL_GET_COLORS     = 0x11
    IOCTL_GET_UNICODE    = 0x12
    IOCTL_GET_EMOJI      = 0x13
    IOCTL_CLEAR          = 0x14

    def __init__(self):
        self._width:     int  = 80
        self._height:    int  = 24
        self._colors:    int  = 256
        self._unicode:   bool = True
        self._emoji:     bool = False

    def init(self) -> bool:
        sz = shutil.get_terminal_size((80, 24))
        self._width  = sz.columns
        self._height = sz.lines
        self._colors = self._probe_colors()
        self._unicode, self._emoji = self._probe_unicode()
        return True

    def shutdown(self) -> None:
        pass

    def refresh(self) -> None:
        """Re-probe terminal size (call after SIGWINCH)."""
        sz = shutil.get_terminal_size((self._width, self._height))
        self._width  = sz.columns
        self._height = sz.lines

    @property
    def width(self)   -> int:  return self._width
    @property
    def height(self)  -> int:  return self._height
    @property
    def colors(self)  -> int:  return self._colors
    @property
    def unicode_ok(self) -> bool: return self._unicode
    @property
    def emoji_ok(self)   -> bool: return self._emoji

    def ioctl(self, command: int, arg: Any = None) -> Any:
        if command == self.IOCTL_GET_SIZE:
            self.refresh()
            return (self._width, self._height)
        if command == self.IOCTL_GET_COLORS:
            return self._colors
        if command == self.IOCTL_GET_UNICODE:
            return self._unicode
        if command == self.IOCTL_GET_EMOJI:
            return self._emoji
        if command == self.IOCTL_CLEAR:
            os.system("cls" if os.name == "nt" else "clear")
            return 0
        raise NotImplementedError(f"DisplayDriver: unknown ioctl {command}")

    # ── Probes ────────────────────────────────────────────────────────────

    @staticmethod
    def _probe_colors() -> int:
        term = os.environ.get("TERM", "")
        colorterm = os.environ.get("COLORTERM", "")
        if "truecolor" in colorterm or "24bit" in colorterm:
            return 16_777_216
        if "256color" in term or os.environ.get("TERM_PROGRAM", "") in ("iTerm.app", "vscode"):
            return 256
        return 8

    @staticmethod
    def _probe_unicode() -> tuple[bool, bool]:
        locale_env = (os.environ.get("LANG", "") +
                      os.environ.get("LC_ALL", "") +
                      os.environ.get("LC_CTYPE", ""))
        unicode_ok = "utf" in locale_env.lower() or sys.platform == "darwin"
        term_prog  = os.environ.get("TERM_PROGRAM", "").lower()
        emoji_ok   = (unicode_ok and
                      any(t in term_prog for t in ("iterm", "wezterm", "kitty",
                                                    "alacritty", "ghostty")))
        return unicode_ok, emoji_ok


# ── StorageDriver ─────────────────────────────────────────────────────────────

class StorageDriver(Driver):
    """Block-level storage driver backed by the BradOS VFS.

    Presents a simple read/write/stat interface; the kernel's
    file syscalls delegate here rather than calling the VFS directly.
    """

    name    = "brados_storage"
    version = "1.0.0"

    IOCTL_GET_FREE    = 0x20
    IOCTL_GET_TOTAL   = 0x21
    IOCTL_SYNC        = 0x22

    def __init__(self, vfs=None):
        self._vfs = vfs

    def init(self) -> bool:
        return self._vfs is not None

    def shutdown(self) -> None:
        pass   # VFS manages its own lifecycle

    def attach_vfs(self, vfs) -> None:
        self._vfs = vfs

    def read(self, path: str) -> bytes:
        return self._vfs.read(path)

    def write(self, path: str, data: bytes) -> int:
        return self._vfs.write(path, data)

    def stat(self, path: str):
        return self._vfs.stat(path)

    def listdir(self, path: str) -> list[str]:
        return self._vfs.listdir(path)

    def ioctl(self, command: int, arg: Any = None) -> Any:
        if command == self.IOCTL_GET_FREE:
            return shutil.disk_usage(".").free
        if command == self.IOCTL_GET_TOTAL:
            return shutil.disk_usage(".").total
        if command == self.IOCTL_SYNC:
            return 0   # MemFS: always in sync; LocalFS: OS handles it
        raise NotImplementedError(f"StorageDriver: unknown ioctl {command}")


# ── InputDriver ───────────────────────────────────────────────────────────────

class InputDriver(Driver):
    """Keyboard / mouse event routing.

    Textual handles raw key events; this driver provides a pub/sub
    interface so kernel tasks can register for key events without
    importing Textual directly.
    """

    name    = "brados_input"
    version = "1.0.0"

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}   # event_type → [handlers]
        self._lock      = threading.Lock()

    def init(self) -> bool:
        return True

    def shutdown(self) -> None:
        with self._lock:
            self._handlers.clear()

    def subscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def dispatch(self, event_type: str, event_data: Any) -> None:
        """Called by the Textual shell to forward events to subscribers."""
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        for h in handlers:
            try:
                h(event_data)
            except Exception as e:
                logger.warning(f"InputDriver handler error: {e}")

    def ioctl(self, command: int, arg: Any = None) -> Any:
        raise NotImplementedError("InputDriver: no ioctl commands defined")


# ── AudioDriver ───────────────────────────────────────────────────────────────

class AudioDriver(Driver):
    """Audio output stub.

    Logs playback intent; actual audio needs playsound/pygame/pyaudio.
    Provides a consistent interface for apps that want to emit sound.
    """

    name    = "brados_audio"
    version = "0.1.0"

    IOCTL_PLAY_BEEP = 0x30
    IOCTL_SET_VOL   = 0x31
    IOCTL_GET_VOL   = 0x32

    def __init__(self):
        self._volume = 0.5
        self._backend: str = "none"

    def init(self) -> bool:
        # Detect available backend
        for mod in ("playsound", "pygame", "pyaudio"):
            try:
                __import__(mod)
                self._backend = mod
                logger.info(f"AudioDriver: using {mod}")
                return True
            except ImportError:
                pass
        logger.warning("AudioDriver: no audio backend found — stub mode")
        return False   # degraded, not fatal

    def shutdown(self) -> None:
        pass

    def play(self, path: str) -> None:
        logger.info(f"AudioDriver: play({path!r}) [backend={self._backend}]")
        if self._backend == "playsound":
            try:
                import playsound                        # type: ignore
                playsound.playsound(path, block=False)
            except Exception as e:
                logger.warning(f"AudioDriver play error: {e}")

    def beep(self) -> None:
        sys.stdout.write("\a")
        sys.stdout.flush()

    def ioctl(self, command: int, arg: Any = None) -> Any:
        if command == self.IOCTL_PLAY_BEEP:
            self.beep(); return 0
        if command == self.IOCTL_SET_VOL:
            self._volume = float(arg); return 0
        if command == self.IOCTL_GET_VOL:
            return self._volume
        raise NotImplementedError(f"AudioDriver: unknown ioctl {command}")

    @property
    def info(self) -> DriverInfo:
        status = "active" if self._backend != "none" else "degraded"
        return DriverInfo(self.name, self.version, status,
                          f"backend={self._backend}")


# ── ProcessDriver ─────────────────────────────────────────────────────────────

class ProcessDriver(Driver):
    """Host-level process management.

    Lets the kernel spawn real OS processes (for terminal commands, etc.)
    and track them independently of the cooperative BradOS task scheduler.
    """

    name    = "brados_proc"
    version = "1.0.0"

    IOCTL_LIST  = 0x40
    IOCTL_KILL  = 0x41

    def __init__(self):
        self._procs: dict[int, subprocess.Popen] = {}
        self._lock   = threading.Lock()

    def init(self) -> bool:
        return True

    def shutdown(self) -> None:
        with self._lock:
            for p in self._procs.values():
                try:
                    p.terminate()
                except Exception:
                    pass
            self._procs.clear()

    def spawn(self, args: list[str], cwd: str | None = None,
              env: dict | None = None) -> int:
        """Spawn a process; return its OS PID."""
        p = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env or os.environ.copy(),
        )
        with self._lock:
            self._procs[p.pid] = p
        return p.pid

    def wait(self, pid: int, timeout: float | None = None) -> tuple[int, str, str]:
        """Wait for process to finish; return (returncode, stdout, stderr)."""
        with self._lock:
            p = self._procs.get(pid)
        if not p:
            raise ProcessLookupError(f"No tracked process with pid {pid}")
        try:
            out, err = p.communicate(timeout=timeout)
            with self._lock:
                self._procs.pop(pid, None)
            return p.returncode, out.decode(errors="replace"), err.decode(errors="replace")
        except subprocess.TimeoutExpired:
            p.kill()
            raise

    def kill(self, pid: int) -> None:
        with self._lock:
            p = self._procs.get(pid)
        if p:
            p.terminate()
            with self._lock:
                self._procs.pop(pid, None)

    def ioctl(self, command: int, arg: Any = None) -> Any:
        if command == self.IOCTL_LIST:
            with self._lock:
                return list(self._procs.keys())
        if command == self.IOCTL_KILL and arg is not None:
            self.kill(int(arg)); return 0
        raise NotImplementedError(f"ProcessDriver: unknown ioctl {command}")


# ── Module-level singleton ────────────────────────────────────────────────────

def create_default_registry(vfs=None) -> DriverRegistry:
    """Initialise and return a DriverRegistry with all standard drivers."""
    reg = DriverRegistry()
    reg.register(DisplayDriver())
    reg.register(NetworkDriver())
    reg.register(StorageDriver(vfs=vfs))
    reg.register(InputDriver())
    reg.register(AudioDriver())
    reg.register(ProcessDriver())
    return reg

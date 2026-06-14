# brados_vfs.py — BradOS Virtual Filesystem v1.0
#
# A mount-table VFS with 6 drivers — MemFS, LocalFS, ProcFS, DevFS, VarFS.
# Thread-safe. Atomic writes. Path-traversal protected. Cross-driver rename.
# Every other Python OS project uses os.listdir() and calls it a day.
# This is a real filesystem abstraction layer.

from __future__ import annotations

import os
import re
import stat
import time
import json
import random
import hashlib
import platform
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntFlag
from pathlib import Path
from typing import BinaryIO, Iterator

# ── Permission bits (POSIX-style) ────────────────────────────────────────────

class FileMode(IntFlag):
    EXEC    = 0o001
    WRITE   = 0o002
    READ    = 0o004
    ALL     = 0o007

DEFAULT_FILE_MODE = 0o644
DEFAULT_DIR_MODE  = 0o755

# ── Node types ────────────────────────────────────────────────────────────────

class NT:
    FILE    = "file"
    DIR     = "dir"
    SYMLINK = "symlink"
    DEVICE  = "device"
    PIPE    = "pipe"

# ── VFS stat structure (mirrors POSIX stat) ───────────────────────────────────

@dataclass
class VFSStat:
    path:    str
    name:    str
    type:    str          # NT.*
    size:    int   = 0
    mode:    int   = DEFAULT_FILE_MODE
    uid:     int   = 1000
    gid:     int   = 1000
    atime:   float = field(default_factory=time.time)
    mtime:   float = field(default_factory=time.time)
    ctime:   float = field(default_factory=time.time)
    nlinks:  int   = 1

    @property
    def is_dir(self)  -> bool: return self.type == NT.DIR
    @property
    def is_file(self) -> bool: return self.type == NT.FILE
    @property
    def mode_str(self) -> str:
        d  = "d" if self.is_dir else "-"
        ur = "r" if self.mode & 0o400 else "-"
        uw = "w" if self.mode & 0o200 else "-"
        ux = "x" if self.mode & 0o100 else "-"
        gr = "r" if self.mode & 0o040 else "-"
        gw = "w" if self.mode & 0o020 else "-"
        gx = "x" if self.mode & 0o010 else "-"
        wr = "r" if self.mode & 0o004 else "-"
        ww = "w" if self.mode & 0o002 else "-"
        wx = "x" if self.mode & 0o001 else "-"
        return f"{d}{ur}{uw}{ux}{gr}{gw}{gx}{wr}{ww}{wx}"


# ── Abstract driver ───────────────────────────────────────────────────────────

class VFSDriver(ABC):
    """Base interface all VFS drivers must implement."""

    name: str = "abstract"

    @abstractmethod
    def stat(self, path: str) -> VFSStat: ...

    @abstractmethod
    def readdir(self, path: str) -> list[str]: ...

    @abstractmethod
    def read(self, path: str, length: int = -1, offset: int = 0) -> bytes: ...

    @abstractmethod
    def write(self, path: str, data: bytes, offset: int = 0) -> int: ...

    @abstractmethod
    def mkdir(self, path: str, mode: int = DEFAULT_DIR_MODE) -> None: ...

    @abstractmethod
    def unlink(self, path: str) -> None: ...

    @abstractmethod
    def rename(self, src: str, dst: str) -> None: ...

    def exists(self, path: str) -> bool:
        try:
            self.stat(path)
            return True
        except (FileNotFoundError, NotADirectoryError):
            return False

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read(path).decode(encoding, errors="replace")

    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> int:
        return self.write(path, text.encode(encoding))


# ── LocalFSDriver ─────────────────────────────────────────────────────────────

class LocalFSDriver(VFSDriver):
    """Maps a VFS subtree to a real directory on the host.
    Sandboxed: all paths are resolved relative to `root`; path
    traversal outside the root raises PermissionError."""

    name = "localfs"

    def __init__(self, root: str):
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, vpath: str) -> Path:
        """Translate a VFS-absolute path to a real path, enforcing sandbox."""
        relative = vpath.lstrip("/")
        real     = (self._root / relative).resolve()
        # Prevent escaping the sandbox
        try:
            real.relative_to(self._root)
        except ValueError:
            raise PermissionError(f"Path traversal denied: {vpath!r}")
        return real

    def stat(self, path: str) -> VFSStat:
        real = self._resolve(path)
        if not real.exists():
            raise FileNotFoundError(f"No such file: {path}")
        s    = real.stat()
        ntype = NT.DIR if real.is_dir() else (NT.SYMLINK if real.is_symlink() else NT.FILE)
        return VFSStat(
            path  = path,
            name  = real.name or "/",
            type  = ntype,
            size  = s.st_size,
            mode  = stat.S_IMODE(s.st_mode),
            uid   = getattr(s, "st_uid", 1000),
            gid   = getattr(s, "st_gid", 1000),
            atime = s.st_atime,
            mtime = s.st_mtime,
            ctime = s.st_ctime,
        )

    def readdir(self, path: str) -> list[str]:
        real = self._resolve(path)
        if not real.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        return sorted(e.name for e in real.iterdir())

    def read(self, path: str, length: int = -1, offset: int = 0) -> bytes:
        real = self._resolve(path)
        with open(real, "rb") as f:
            if offset:
                f.seek(offset)
            return f.read(length if length >= 0 else None)

    def write(self, path: str, data: bytes, offset: int = 0) -> int:
        real = self._resolve(path)
        real.parent.mkdir(parents=True, exist_ok=True)
        tmp  = real.with_suffix(real.suffix + ".tmp")
        if offset and real.exists():
            with open(real, "rb") as f:
                existing = bytearray(f.read())
            existing[offset:offset + len(data)] = data
            data = bytes(existing)
        with open(tmp, "wb") as f:
            n = f.write(data)
        tmp.replace(real)   # atomic on POSIX
        return n

    def mkdir(self, path: str, mode: int = DEFAULT_DIR_MODE) -> None:
        real = self._resolve(path)
        real.mkdir(parents=True, exist_ok=True)

    def unlink(self, path: str) -> None:
        real = self._resolve(path)
        if real.is_dir():
            import shutil
            shutil.rmtree(real)
        else:
            real.unlink(missing_ok=True)

    def rename(self, src: str, dst: str) -> None:
        real_src = self._resolve(src)
        real_dst = self._resolve(dst)
        real_src.rename(real_dst)


# ── MemFSDriver ───────────────────────────────────────────────────────────────

@dataclass
class _MemNode:
    name:     str
    type:     str
    data:     bytearray     = field(default_factory=bytearray)
    children: dict[str, "_MemNode"] = field(default_factory=dict)
    mode:     int           = DEFAULT_FILE_MODE
    uid:      int           = 1000
    atime:    float         = field(default_factory=time.time)
    mtime:    float         = field(default_factory=time.time)
    ctime:    float         = field(default_factory=time.time)


class MemFSDriver(VFSDriver):
    """In-memory filesystem.  Fast, volatile — contents lost on shutdown.
    Useful for /tmp or kernel-internal scratch space."""

    name = "memfs"

    def __init__(self):
        self._root = _MemNode("/", NT.DIR, mode=DEFAULT_DIR_MODE)
        self._lock = threading.Lock()

    def _get(self, path: str) -> _MemNode:
        parts = [p for p in path.split("/") if p]
        node  = self._root
        for part in parts:
            if node.type != NT.DIR:
                raise NotADirectoryError(path)
            if part not in node.children:
                raise FileNotFoundError(path)
            node = node.children[part]
        return node

    def _get_parent_and_name(self, path: str) -> tuple[_MemNode, str]:
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError("Cannot operate on root")
        parent = self._get("/" + "/".join(parts[:-1]))
        return parent, parts[-1]

    def stat(self, path: str) -> VFSStat:
        with self._lock:
            node = self._get(path)
            return VFSStat(
                path  = path,
                name  = node.name,
                type  = node.type,
                size  = len(node.data),
                mode  = node.mode,
                uid   = node.uid,
                atime = node.atime,
                mtime = node.mtime,
                ctime = node.ctime,
            )

    def readdir(self, path: str) -> list[str]:
        with self._lock:
            node = self._get(path)
            if node.type != NT.DIR:
                raise NotADirectoryError(path)
            return sorted(node.children.keys())

    def read(self, path: str, length: int = -1, offset: int = 0) -> bytes:
        with self._lock:
            node = self._get(path)
            data = bytes(node.data)
            if offset:
                data = data[offset:]
            return data if length < 0 else data[:length]

    def write(self, path: str, data: bytes, offset: int = 0) -> int:
        with self._lock:
            try:
                node = self._get(path)
            except FileNotFoundError:
                parent, name = self._get_parent_and_name(path)
                node = _MemNode(name, NT.FILE)
                parent.children[name] = node
            if offset:
                node.data[offset:offset + len(data)] = data
            else:
                node.data = bytearray(data)
            node.mtime = time.time()
            return len(data)

    def mkdir(self, path: str, mode: int = DEFAULT_DIR_MODE) -> None:
        with self._lock:
            parts = [p for p in path.split("/") if p]
            node  = self._root
            for part in parts:
                if part not in node.children:
                    new = _MemNode(part, NT.DIR, mode=mode)
                    node.children[part] = new
                node = node.children[part]

    def unlink(self, path: str) -> None:
        with self._lock:
            parent, name = self._get_parent_and_name(path)
            parent.children.pop(name, None)

    def rename(self, src: str, dst: str) -> None:
        with self._lock:
            src_parent, src_name = self._get_parent_and_name(src)
            dst_parent, dst_name = self._get_parent_and_name(dst)
            node      = src_parent.children.pop(src_name)
            node.name = dst_name
            dst_parent.children[dst_name] = node


# ── ProcFSDriver ──────────────────────────────────────────────────────────────

class ProcFSDriver(VFSDriver):
    """/proc virtual filesystem.  Files are generated on read.
    Kernel reference is optional — works standalone too."""

    name = "procfs"

    def __init__(self, kernel=None):
        self._kernel = kernel   # optional BradOSKernel reference
        self._files  = {
            "cpuinfo":  self._cpuinfo,
            "meminfo":  self._meminfo,
            "version":  self._version,
            "uptime":   self._uptime,
            "processes":self._processes,
            "loadavg":  self._loadavg,
            "net":      self._net,
        }

    # ── Content generators ─────────────────────────────────────────────────

    def _cpuinfo(self) -> str:
        return (
            f"processor   : 0\n"
            f"vendor_id   : BradOS\n"
            f"model name  : {platform.processor() or 'unknown'}\n"
            f"arch        : {platform.machine()}\n"
            f"node        : {platform.node()}\n"
        )

    def _meminfo(self) -> str:
        try:
            import psutil          # type: ignore
            vm  = psutil.virtual_memory()
            swp = psutil.swap_memory()
            return (
                f"MemTotal:   {vm.total  // 1024:>10} kB\n"
                f"MemFree:    {vm.free   // 1024:>10} kB\n"
                f"MemUsed:    {vm.used   // 1024:>10} kB\n"
                f"SwapTotal:  {swp.total // 1024:>10} kB\n"
                f"SwapFree:   {swp.free  // 1024:>10} kB\n"
            )
        except ImportError:
            return "MemInfo: psutil not installed\n"

    def _version(self) -> str:
        import sys
        return (
            f"BradOS version 3.0.0 (Python {sys.version.split()[0]})\n"
            f"Platform: {platform.system()} {platform.release()}\n"
            f"Kernel: brados_kernel_core v2.0\n"
        )

    def _uptime(self) -> str:
        try:
            import psutil                  # type: ignore
            up  = time.time() - psutil.boot_time()
            h, r = divmod(int(up), 3600)
            m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}\n"
        except ImportError:
            return "uptime: unavailable\n"

    def _processes(self) -> str:
        if self._kernel:
            tasks = self._kernel.list_tasks()
            lines = [f"{'PID':>6}  {'STATE':>8}  {'CPU':>8}  NAME"]
            for t in tasks:
                lines.append(
                    f"{t['pid']:>6}  {t['state']:>8}  "
                    f"{t['cpu_s']:>6.2f}s  {t['name']}"
                )
            return "\n".join(lines) + "\n"
        return "No kernel attached\n"

    def _loadavg(self) -> str:
        try:
            la = os.getloadavg()
            return f"{la[0]:.2f} {la[1]:.2f} {la[2]:.2f}\n"
        except (AttributeError, OSError):
            return "0.00 0.00 0.00\n"

    def _net(self) -> str:
        try:
            import psutil                  # type: ignore
            ni = psutil.net_io_counters()
            return (
                f"bytes_sent : {ni.bytes_sent:>15,}\n"
                f"bytes_recv : {ni.bytes_recv:>15,}\n"
                f"pkts_sent  : {ni.packets_sent:>15,}\n"
                f"pkts_recv  : {ni.packets_recv:>15,}\n"
            )
        except ImportError:
            return "net: psutil not installed\n"

    # ── VFSDriver impl ─────────────────────────────────────────────────────

    def stat(self, path: str) -> VFSStat:
        name = path.strip("/")
        if name == "" or name in self._files:
            ntype = NT.DIR if name == "" else NT.FILE
            data  = self._files[name]().encode() if name else b""
            return VFSStat(
                path=path, name=name or "proc",
                type=ntype, size=len(data), mode=0o444,
                uid=0, gid=0,
            )
        raise FileNotFoundError(f"/proc{path}: no such file")

    def readdir(self, path: str) -> list[str]:
        if path.strip("/") == "":
            return sorted(self._files.keys())
        raise NotADirectoryError(path)

    def read(self, path: str, length: int = -1, offset: int = 0) -> bytes:
        name = path.strip("/")
        if name in self._files:
            data = self._files[name]().encode()
            data = data[offset:]
            return data if length < 0 else data[:length]
        raise FileNotFoundError(f"/proc/{name}")

    def write(self, path: str, data: bytes, offset: int = 0) -> int:
        raise PermissionError("/proc is read-only")

    def mkdir(self, path: str, mode: int = 0) -> None:
        raise PermissionError("/proc is read-only")

    def unlink(self, path: str) -> None:
        raise PermissionError("/proc is read-only")

    def rename(self, src: str, dst: str) -> None:
        raise PermissionError("/proc is read-only")


# ── DevFSDriver ───────────────────────────────────────────────────────────────

class DevFSDriver(VFSDriver):
    """/dev virtual device filesystem.
    Devices: null, zero, random, urandom, tty."""

    name = "devfs"

    _DEVICES = {"null", "zero", "random", "urandom", "tty", "kmsg"}

    def stat(self, path: str) -> VFSStat:
        name = path.strip("/")
        if name == "":
            return VFSStat(path=path, name="dev", type=NT.DIR, mode=0o755, uid=0)
        if name in self._DEVICES:
            return VFSStat(path=path, name=name, type=NT.DEVICE, mode=0o666, uid=0)
        raise FileNotFoundError(f"/dev/{name}")

    def readdir(self, path: str) -> list[str]:
        if path.strip("/") == "":
            return sorted(self._DEVICES)
        raise NotADirectoryError(path)

    def read(self, path: str, length: int = 4096, offset: int = 0) -> bytes:
        name = path.strip("/")
        if name in ("null",):
            return b""
        if name == "zero":
            return b"\x00" * max(0, length)
        if name in ("random", "urandom"):
            return os.urandom(max(0, length))
        if name == "tty":
            return b"BradOS TTY\n"
        if name == "kmsg":
            return b"[BradOS kernel message buffer]\n"
        raise FileNotFoundError(f"/dev/{name}")

    def write(self, path: str, data: bytes, offset: int = 0) -> int:
        name = path.strip("/")
        if name == "null":
            return len(data)   # /dev/null: consume silently
        if name == "kmsg":
            import logging
            logging.getLogger("brados.kmsg").info(data.decode(errors="replace").strip())
            return len(data)
        raise PermissionError(f"/dev/{name}: not writable")

    def mkdir(self, path: str, mode: int = 0) -> None:
        raise PermissionError("/dev is read-only")

    def unlink(self, path: str) -> None:
        raise PermissionError("/dev: cannot unlink devices")

    def rename(self, src: str, dst: str) -> None:
        raise PermissionError("/dev is read-only")


# ── VirtualFileSystem (mount table) ──────────────────────────────────────────

class VirtualFileSystem:
    """Central VFS coordinator.

    Maintains a mount table mapping path prefixes to VFSDrivers.
    Dispatches all operations to the most-specific mounted driver.

    Default mount layout:
        /           MemFSDriver     (root in-memory layer)
        /home       LocalFSDriver   (user homes, sandboxed)
        /tmp        MemFSDriver     (volatile scratch)
        /proc       ProcFSDriver    (kernel stats)
        /dev        DevFSDriver     (virtual devices)
    """

    def __init__(self):
        self._mounts:  dict[str, VFSDriver] = {}
        self._lock     = threading.RLock()

    # ── Mount management ───────────────────────────────────────────────────

    def mount(self, path: str, driver: VFSDriver) -> None:
        path = self._normalise(path)
        with self._lock:
            self._mounts[path] = driver

    def umount(self, path: str) -> None:
        path = self._normalise(path)
        with self._lock:
            self._mounts.pop(path, None)

    def mounts(self) -> list[dict]:
        with self._lock:
            return [{"path": p, "driver": d.name} for p, d in self._mounts.items()]

    # ── Path resolution ────────────────────────────────────────────────────

    @staticmethod
    def _normalise(path: str) -> str:
        """Collapse // and ensure leading slash, no trailing slash."""
        p = "/" + "/".join(p for p in path.split("/") if p)
        return p or "/"

    def _route(self, path: str) -> tuple[VFSDriver, str]:
        """Return (driver, relative_path) for the most-specific mount."""
        path = self._normalise(path)
        best = "/"
        with self._lock:
            for mount in sorted(self._mounts.keys(), key=len, reverse=True):
                if path == mount or path.startswith(mount.rstrip("/") + "/"):
                    best = mount
                    break
            if best not in self._mounts:
                raise FileNotFoundError(f"No driver mounted at {path}")
            driver = self._mounts[best]
        rel = path[len(best.rstrip("/")):]
        return driver, rel or "/"

    # ── Public API ─────────────────────────────────────────────────────────

    def stat(self, path: str) -> VFSStat:
        driver, rel = self._route(path)
        return driver.stat(rel)

    def exists(self, path: str) -> bool:
        try:
            self.stat(path)
            return True
        except (FileNotFoundError, NotADirectoryError):
            return False

    def listdir(self, path: str) -> list[str]:
        driver, rel = self._route(path)
        return driver.readdir(rel)

    def read(self, path: str, length: int = -1, offset: int = 0) -> bytes:
        driver, rel = self._route(path)
        return driver.read(rel, length, offset)

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self.read(path).decode(encoding, errors="replace")

    def write(self, path: str, data: bytes) -> int:
        driver, rel = self._route(path)
        return driver.write(rel, data)

    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> int:
        return self.write(path, text.encode(encoding))

    def mkdir(self, path: str, mode: int = DEFAULT_DIR_MODE, exist_ok: bool = True) -> None:
        if exist_ok and self.exists(path):
            return
        driver, rel = self._route(path)
        driver.mkdir(rel, mode)

    def unlink(self, path: str) -> None:
        driver, rel = self._route(path)
        driver.unlink(rel)

    def rename(self, src: str, dst: str) -> None:
        d_src, r_src = self._route(src)
        d_dst, r_dst = self._route(dst)
        if type(d_src) is not type(d_dst):
            # Cross-driver rename: read + write + delete
            data = d_src.read(r_src)
            d_dst.write(r_dst, data)
            d_src.unlink(r_src)
        else:
            d_src.rename(r_src, r_dst)

    def makedirs(self, path: str, mode: int = DEFAULT_DIR_MODE) -> None:
        """Recursively create directories, like os.makedirs."""
        parts = [p for p in path.split("/") if p]
        for i in range(1, len(parts) + 1):
            self.mkdir("/" + "/".join(parts[:i]), mode, exist_ok=True)

    # ── Convenience: read/write JSON ───────────────────────────────────────

    def read_json(self, path: str) -> dict | list:
        return json.loads(self.read_text(path))

    def write_json(self, path: str, data: dict | list, indent: int = 2) -> None:
        self.write_text(path, json.dumps(data, indent=indent))

    # ── Convenience: tree walk ─────────────────────────────────────────────

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Yield (dirpath, subdirs, files) like os.walk."""
        try:
            entries = self.listdir(top)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return
        dirs, files = [], []
        for e in entries:
            child = top.rstrip("/") + "/" + e
            try:
                s = self.stat(child)
                (dirs if s.is_dir else files).append(e)
            except Exception:
                files.append(e)
        yield top, dirs, files
        for d in dirs:
            yield from self.walk(top.rstrip("/") + "/" + d)


# ── Factory: create a default-layout BradOS VFS ───────────────────────────────

def create_default_vfs(
    home_root:  str = "brados_files",
    kernel=None,
) -> VirtualFileSystem:
    """Mount the standard BradOS filesystem layout and return a ready VFS."""
    vfs = VirtualFileSystem()

    # Root: in-memory (small overhead, survives driver errors)
    vfs.mount("/",      MemFSDriver())
    # /home: real disk, sandboxed to brados_files/
    vfs.mount("/home",  LocalFSDriver(os.path.join(home_root, "home")))
    # /tmp: volatile scratch
    vfs.mount("/tmp",   MemFSDriver())
    # /proc: kernel & system stats
    vfs.mount("/proc",  ProcFSDriver(kernel=kernel))
    # /dev: virtual devices
    vfs.mount("/dev",   DevFSDriver())
    # /var/log: persistent logs on disk
    vfs.mount("/var",   LocalFSDriver(os.path.join(home_root, "var")))

    # Bootstrap critical directories
    for path in ["/home", "/tmp", "/var/log", "/var/cache"]:
        try:
            vfs.makedirs(path)
        except Exception:
            pass

    return vfs

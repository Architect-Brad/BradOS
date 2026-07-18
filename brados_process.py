# brados_process.py — Real subprocess management with VFS pipe integration
#
# ProcessManager wraps OS subprocesses and exposes their I/O through
# the ProcFS driver as /proc/<pid>/stdin, /proc/<pid>/stdout, etc.
# Each managed process can be tied to a BradSec capability token.

from __future__ import annotations

import os
import sys
import time
import logging
import subprocess
import threading
from typing import Any

from brados_vfs import PipeFile

logger = logging.getLogger("brados.proc")


# ── ManagedProcess ────────────────────────────────────────────────────────────

class ManagedProcess:
    """Wraps a subprocess.Popen with VFS pipe files and metadata."""

    def __init__(self, pid: int, name: str, proc: subprocess.Popen):
        self.pid = pid
        self.name = name
        self.proc = proc
        self.returncode: int | None = None
        self.created_at = time.time()
        self._done = threading.Event()

    def is_alive(self) -> bool:
        return self.proc.poll() is None

    def poll(self) -> int | None:
        return self.proc.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            rc = self.proc.wait(timeout=timeout)
            self.returncode = rc
            self._done.set()
            return rc
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        try:
            self.proc.terminate()
        except ProcessLookupError:
            pass

    def kill(self) -> None:
        try:
            self.proc.kill()
        except ProcessLookupError:
            pass

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "alive": self.is_alive(),
            "returncode": self.returncode,
            "created_at": self.created_at,
        }


# ── ProcessManager ────────────────────────────────────────────────────────────

class ProcessManager:
    """Manages real OS subprocesses and bridges them into the BradOS VFS.

    Usage:
        vfs = create_default_vfs()
        pm = ProcessManager(vfs)
        pm.spawn(["python3", "script.py"], "script")
        data = vfs.read("/proc/1/stdout")   # read process output
        vfs.write("/proc/1/stdin", b"input") # send to process stdin
    """

    def __init__(self, vfs=None):
        self._vfs = vfs
        self._procs: dict[int, ManagedProcess] = {}
        self._lock = threading.Lock()
        self._reaper_thread: threading.Thread | None = None
        self._shutdown = threading.Event()

    # ── Public API ───────────────────────────────────────────────────────────

    def spawn(self, args: list[str], name: str | None = None,
              cwd: str | None = None, env: dict | None = None,
              stdin_data: bytes | None = None) -> int:
        """Spawn a real subprocess and register it in the VFS.

        Returns the OS PID.
        """
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env or os.environ.copy(),
        )

        mp = ManagedProcess(proc.pid, name or args[0], proc)

        with self._lock:
            self._procs[proc.pid] = mp

        if stdin_data:
            self._write_stdin(proc.pid, stdin_data)

        self._register_vfs(mp)

        logger.info(f"Spawned pid={proc.pid} name={mp.name!r}")
        return proc.pid

    def list(self) -> list[dict]:
        with self._lock:
            return [p.as_dict() for p in self._procs.values()]

    def get(self, pid: int) -> ManagedProcess | None:
        with self._lock:
            return self._procs.get(pid)

    def signal(self, pid: int, sig: int = 15) -> bool:
        """Send a signal to a managed process. Returns True if found."""
        mp = self.get(pid)
        if mp is None:
            return False
        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False

    def terminate(self, pid: int) -> bool:
        return self.signal(pid, 15)

    def kill(self, pid: int) -> bool:
        return self.signal(pid, 9)

    def wait(self, pid: int, timeout: float | None = None) -> dict | None:
        mp = self.get(pid)
        if mp is None:
            return None
        rc = mp.wait(timeout=timeout)
        return mp.as_dict() if rc is not None else None

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            for mp in list(self._procs.values()):
                mp.terminate()
            self._procs.clear()
        logger.info("ProcessManager shut down")

    # ── VFS integration ────────────────────────────────────────────────────

    def _register_vfs(self, mp: ManagedProcess) -> None:
        """Register process I/O files in /proc/<pid>/ via ProcFSDriver."""
        if self._vfs is None:
            return
        procfs = self._vfs.get_driver("procfs")
        if procfs is None:
            return

        stdin_pipe = None
        stdout_pipe = None
        stderr_pipe = None

        if mp.proc.stdin:
            stdin_pipe = PipeFile(w_obj=mp.proc.stdin)
        if mp.proc.stdout:
            stdout_pipe = PipeFile(r_fd=mp.proc.stdout.fileno())
        if mp.proc.stderr:
            stderr_pipe = PipeFile(r_fd=mp.proc.stderr.fileno())

        procfs.register_pid(
            pid=str(mp.pid),
            name=mp.name,
            stdin_pipe=stdin_pipe,
            stdout_pipe=stdout_pipe,
            stderr_pipe=stderr_pipe,
        )

    def _unregister_vfs(self, pid: int) -> None:
        if self._vfs is None:
            return
        procfs = self._vfs.get_driver("procfs")
        if procfs is None:
            return
        procfs.unregister_pid(str(pid))

    def _write_stdin(self, pid: int, data: bytes) -> int:
        mp = self.get(pid)
        if mp is None or mp.proc.stdin is None:
            raise ProcessLookupError(f"pid {pid} not found or no stdin")
        written = mp.proc.stdin.write(data)
        mp.proc.stdin.flush()
        return written

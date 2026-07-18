# brados_kernel_core.py — BradOS Kernel v3.0
#
# Most Python "OS" projects fake it. This is a real cooperative microkernel
# with 35 syscalls, priority scheduling, IPC, shared memory, and real
# subprocess management. No other terminal OS project has anything close.

from __future__ import annotations

import os
import sys
import time
import json
import queue
import hashlib
import logging
import threading
import subprocess
from collections import deque
from datetime import datetime
from enum import IntEnum, IntFlag
from typing import Any

logger = logging.getLogger("brados.kernel")


# ── Syscall table ─────────────────────────────────────────────────────────────

class SC(IntEnum):
    # Core I/O (v1 compat)
    PRINT       = 1
    INPUT       = 2
    SLEEP       = 3
    EXIT        = 4
    GET_TIME    = 5
    READ_FILE   = 6
    WRITE_FILE  = 7
    LIST_DIR    = 8
    GET_USER    = 9
    GET_PERM    = 10
    NET_SEND    = 11   # inter-task message bus
    NET_RECV    = 12
    # Process (v2)
    SPAWN       = 13
    GETPID      = 14
    SIGNAL      = 15
    # Networking via NetworkDriver (v3)
    SOCKET      = 16   # → fd
    CONNECT     = 17   # (fd, host, port) → 0
    SEND_SOCK   = 18   # (fd, data:bytes) → n
    RECV_SOCK   = 19   # (fd, size) → bytes
    CLOSE_SOCK  = 20   # (fd) → 0
    # VFS (v3)
    VFS_READ    = 21   # (path) → bytes
    VFS_WRITE   = 22   # (path, data:bytes) → n
    VFS_LIST    = 23   # (path) → [str]
    VFS_STAT    = 24   # (path) → dict
    VFS_MKDIR   = 25   # (path) → 0
    VFS_UNLINK  = 26   # (path) → 0
    # Device control
    IOCTL       = 27   # (driver_name, cmd, arg) → Any
    # Real subprocess
    FORK        = 28   # (args:[str], cwd:str) → pid
    WAIT        = 29   # (pid, timeout) → (rc, stdout, stderr)
    # IPC primitives
    PIPE_OPEN   = 30   # (name) → 0   (creates named pipe)
    PIPE_WRITE  = 31   # (name, obj) → 0
    PIPE_READ   = 32   # (name) → obj | None
    # Shared memory
    SHMEM_PUT   = 33   # (key, value) → 0
    SHMEM_GET   = 34   # (key) → value | None
    SHMEM_DEL   = 35   # (key) → 0

# Legacy aliases
SYSCALL_PRINT      = SC.PRINT
SYSCALL_INPUT      = SC.INPUT
SYSCALL_SLEEP      = SC.SLEEP
SYSCALL_EXIT       = SC.EXIT
SYSCALL_GET_TIME   = SC.GET_TIME
SYSCALL_READ_FILE  = SC.READ_FILE
SYSCALL_WRITE_FILE = SC.WRITE_FILE
SYSCALL_LIST_DIR   = SC.LIST_DIR
SYSCALL_GET_USER   = SC.GET_USER
SYSCALL_GET_PERM   = SC.GET_PERM
SYSCALL_NET_SEND   = SC.NET_SEND
SYSCALL_NET_RECV   = SC.NET_RECV


# ── Permissions ───────────────────────────────────────────────────────────────

class Perm(IntFlag):
    NONE   = 0
    READ   = 1
    WRITE  = 2
    EXEC   = 4
    ADMIN  = 8
    NET    = 16   # network access
    PROC   = 32   # process spawning

PERM_NONE  = Perm.NONE
PERM_READ  = Perm.READ
PERM_WRITE = Perm.WRITE
PERM_EXEC  = Perm.EXEC
PERM_ADMIN = Perm.ADMIN


# ── Process states ────────────────────────────────────────────────────────────

class ProcState:
    RUNNING  = "running"
    SLEEPING = "sleeping"
    WAITING  = "waiting"
    ZOMBIE   = "zombie"


# ── Process ───────────────────────────────────────────────────────────────────

class Process:
    def __init__(self, pid: int, name: str, gen,
                 user: str = "guest", uid: int = 1000, nice: int = 5):
        self.pid        = pid
        self.name       = name
        self.gen        = gen
        self.user       = user
        self.uid        = uid
        self.nice       = max(0, min(19, nice))   # 0=highest, 19=lowest priority
        self.state      = ProcState.RUNNING
        self.cpu_time   = 0.0
        self.mem_bytes  = 0                        # rough accounting
        self.start_time = time.monotonic()
        self.wake_at    = 0.0
        self.last_ret   = None
        self.signals    = deque()
        self.env        : dict[str, str] = {}      # per-process environment

    @property
    def uptime(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def priority_turns(self) -> int:
        """How many consecutive turns this process gets per scheduler epoch."""
        return max(1, (20 - self.nice) // 4)

    def __repr__(self):
        return f"<Process pid={self.pid} name={self.name!r} nice={self.nice} state={self.state}>"


# ── Password hashing (PBKDF2-HMAC-SHA256) ────────────────────────────────────

def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key  = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return f"pbkdf2:sha256:{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored.startswith("pbkdf2:"):
        logger.warning("Plaintext password — rehash immediately")
        return password == stored
    try:
        _, algo, salt_hex, key_hex = stored.split(":")
        salt = bytes.fromhex(salt_hex)
        key  = hashlib.pbkdf2_hmac(algo, password.encode(), salt, 260_000)
        return key.hex() == key_hex
    except (ValueError, KeyError):
        return False


# ── Kernel ────────────────────────────────────────────────────────────────────

class BradOSKernel:
    """
    BradOS cooperative microkernel.

    Scheduler: priority-weighted round-robin.
      Processes with lower nice values get more consecutive turns per epoch.
      Each turn: one syscall is dispatched and its return value queued for
      the next send().  No syscall is ever silently dropped (v1 bug fixed).

    Attached subsystems (optional, set after __init__):
      self.vfs      — VirtualFileSystem
      self.drivers  — DriverRegistry
    """

    def __init__(self, user_profiles_dir: str = "user_profiles"):
        self.tasks             : deque[Process]  = deque()
        self.next_pid          : int             = 1
        self.users             : dict            = {}
        self.current_user      : int | None      = None
        self.user_profiles_dir : str             = user_profiles_dir
        self.network_bus       : queue.Queue     = queue.Queue()
        self._pipes            : dict[str, queue.Queue] = {}
        self._shmem            : dict[str, Any]  = {}
        self._shutdown         : threading.Event = threading.Event()
        self._lock             = threading.Lock()

        # Subsystems attached by the shell/boot code
        self.vfs               = None   # VirtualFileSystem | None
        self.drivers           = None   # DriverRegistry    | None
        self.sec               = None   # BradSec           | None
        self.proc_mgr          = None   # ProcessManager    | None

        self.load_user_database()
        logger.info("BradOS kernel v3.0 initialised")

    # ── User management ───────────────────────────────────────────────────────

    def load_user_database(self):
        db_path = os.path.join(self.user_profiles_dir, "users.json")
        if os.path.exists(db_path):
            with open(db_path) as f:
                raw = json.load(f)
            self.users = {int(k): v for k, v in raw.items()}
            dirty = False
            for uid, info in self.users.items():
                pwd = info.get("password", "")
                if pwd and not pwd.startswith("pbkdf2:"):
                    info["password"] = hash_password(pwd)
                    dirty = True
                    logger.warning(f"Auto-rehashed password for uid {uid}")
            if dirty:
                self._save_db()
        else:
            self.users = {
                0: {
                    "name": "root",
                    "password": hash_password("admin"),
                    "groups": ["admin"],
                    "perms": int(Perm.ADMIN | Perm.READ | Perm.WRITE |
                                 Perm.EXEC | Perm.NET | Perm.PROC),
                },
                1000: {
                    "name": "guest",
                    "password": hash_password(""),
                    "groups": ["guest"],
                    "perms": int(Perm.READ),
                },
            }
            self._save_db()

    def save_user_database(self): self._save_db()

    def _save_db(self):
        os.makedirs(self.user_profiles_dir, exist_ok=True)
        path = os.path.join(self.user_profiles_dir, "users.json")
        tmp  = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.users, f, indent=2)
        os.replace(tmp, path)

    def authenticate(self, username: str, password: str) -> int | None:
        for uid, info in self.users.items():
            if info["name"] == username:
                if verify_password(password, info.get("password", "")):
                    self.current_user = uid
                    logger.info(f"Auth OK: {username} (uid={uid})")
                    return uid
                logger.warning(f"Auth FAIL (bad password): {username}")
                return None
        logger.warning(f"Auth FAIL (unknown user): {username}")
        return None

    def check_permission(self, uid: int, required: Perm) -> bool:
        if uid == 0: return True
        info = self.users.get(uid)
        return bool(info and info.get("perms", 0) & int(required))

    def add_user(self, username: str, password: str,
                 perms: int = int(Perm.READ | Perm.WRITE)) -> int:
        new_uid = max(self.users) + 1
        self.users[new_uid] = {
            "name": username, "password": hash_password(password),
            "groups": [username], "perms": perms,
        }
        self._save_db()
        return new_uid

    # ── Process management ────────────────────────────────────────────────────

    def create_task(self, name: str, generator_func, *args,
                    user=None, uid: int | None = None,
                    nice: int = 5) -> int:
        if uid is None:
            uid = self.current_user or 1000
        user_name = self.users.get(uid, {}).get("name", "unknown")
        gen       = generator_func(*args)
        pid       = self.next_pid
        self.next_pid += 1
        proc = Process(pid, name, gen, user=user_name, uid=uid, nice=nice)
        self.tasks.append(proc)
        # Issue a capability token via BradSec if available
        if self.sec is not None:
            from brados_security import Cap
            caps = Cap.default_user()
            if uid == 0:
                caps = Cap.ADMIN
            self.sec.issue_token(pid, uid, caps=caps)
        logger.info(f"Task '{name}' (pid={pid}) created by {user_name} nice={nice}")
        return pid

    def kill_task(self, pid: int) -> bool:
        for proc in list(self.tasks):
            if proc.pid == pid:
                try: proc.gen.close()
                except Exception: pass
                proc.state = ProcState.ZOMBIE
                self.tasks.remove(proc)
                logger.info(f"Task '{proc.name}' (pid={pid}) killed")
                return True
        return False

    def list_tasks(self) -> list[dict]:
        tasks = [
            {"pid": p.pid, "name": p.name, "user": p.user, "state": p.state,
             "cpu_s": round(p.cpu_time, 3), "uptime_s": round(p.uptime, 1),
             "nice": p.nice, "mem_bytes": p.mem_bytes}
            for p in self.tasks
        ]
        if self.proc_mgr:
            for mp_info in self.proc_mgr.list():
                tasks.append({
                    "pid": mp_info["pid"],
                    "name": mp_info["name"],
                    "user": "proc",
                    "state": "running" if mp_info["alive"] else "exited",
                    "cpu_s": 0.0,
                    "uptime_s": round(time.time() - mp_info["created_at"], 1),
                    "nice": 0,
                    "mem_bytes": 0,
                })
        return tasks

    # ── Syscall dispatcher ────────────────────────────────────────────────────

    def handle_syscall(self, proc: Process, cmd: int, args: tuple) -> Any:
        try:
            sc = SC(cmd)
        except ValueError:
            logger.warning(f"Unknown syscall {cmd} from '{proc.name}'")
            return -1

        match sc:

            # ── Core I/O ──────────────────────────────────────────────────────

            case SC.PRINT:
                print(str(args[0]) if args else "")
                return 0

            case SC.INPUT:
                return input(str(args[0]) if args else "")

            case SC.SLEEP:
                dur = float(args[0]) if args else 1.0
                proc.state   = ProcState.SLEEPING
                proc.wake_at = time.monotonic() + dur
                return 0

            case SC.EXIT:
                proc.state = ProcState.ZOMBIE
                logger.info(f"Task '{proc.name}' (pid={proc.pid}) exited")
                return None

            case SC.GET_TIME:
                return time.time()

            case SC.GET_USER:
                return proc.user

            case SC.GET_PERM:
                return self.users.get(proc.uid, {}).get("perms", 0)

            case SC.GETPID:
                return proc.pid

            # ── Filesystem (legacy, host-direct) ──────────────────────────────

            case SC.READ_FILE:
                if not self.check_permission(proc.uid, Perm.READ):
                    return PermissionError("read denied")
                try:
                    with open(args[0]) as f: return f.read()
                except OSError as e: return e

            case SC.WRITE_FILE:
                if not self.check_permission(proc.uid, Perm.WRITE):
                    return PermissionError("write denied")
                try:
                    tmp = str(args[0]) + ".tmp"
                    with open(tmp, "w") as f: f.write(args[1])
                    os.replace(tmp, args[0])
                    proc.mem_bytes += len(str(args[1]))
                    return 0
                except OSError as e: return e

            case SC.LIST_DIR:
                if not self.check_permission(proc.uid, Perm.READ):
                    return PermissionError("read denied")
                try: return os.listdir(args[0] if args else ".")
                except OSError as e: return e

            # ── VFS syscalls (capability-checked via BradSec) ─────────────────

            case SC.VFS_READ:
                if not self.check_permission(proc.uid, Perm.READ):
                    return PermissionError("vfs read denied")
                if not self.vfs:
                    return OSError("VFS not mounted")
                try: return self.vfs.read(args[0], caller_pid=proc.pid)
                except Exception as e: return e

            case SC.VFS_WRITE:
                if not self.check_permission(proc.uid, Perm.WRITE):
                    return PermissionError("vfs write denied")
                if not self.vfs:
                    return OSError("VFS not mounted")
                try:
                    n = self.vfs.write(args[0], args[1], caller_pid=proc.pid)
                    proc.mem_bytes += n
                    return n
                except Exception as e: return e

            case SC.VFS_LIST:
                if not self.check_permission(proc.uid, Perm.READ):
                    return PermissionError("vfs list denied")
                if not self.vfs:
                    return OSError("VFS not mounted")
                try: return self.vfs.listdir(args[0] if args else "/", caller_pid=proc.pid)
                except Exception as e: return e

            case SC.VFS_STAT:
                if not self.vfs: return OSError("VFS not mounted")
                try:
                    s = self.vfs.stat(args[0], caller_pid=proc.pid)
                    return {
                        "name": s.name, "type": s.type, "size": s.size,
                        "mode": s.mode_str, "mtime": s.mtime,
                    }
                except Exception as e: return e

            case SC.VFS_MKDIR:
                if not self.check_permission(proc.uid, Perm.WRITE):
                    return PermissionError("vfs mkdir denied")
                if not self.vfs: return OSError("VFS not mounted")
                try: self.vfs.mkdir(args[0], caller_pid=proc.pid); return 0
                except Exception as e: return e

            case SC.VFS_UNLINK:
                if not self.check_permission(proc.uid, Perm.WRITE):
                    return PermissionError("vfs unlink denied")
                if not self.vfs: return OSError("VFS not mounted")
                try: self.vfs.unlink(args[0], caller_pid=proc.pid); return 0
                except Exception as e: return e

            # ── Networking (via NetworkDriver) ────────────────────────────────

            case SC.SOCKET:
                if not self.check_permission(proc.uid, Perm.NET):
                    return PermissionError("net permission denied")
                if not self.drivers: return OSError("drivers not loaded")
                from brados_drivers import NetworkDriver
                net = self.drivers.get(NetworkDriver)
                if not net: return OSError("NetworkDriver not registered")
                return net.udp_socket()

            case SC.CONNECT:
                if not self.check_permission(proc.uid, Perm.NET):
                    return PermissionError("net permission denied")
                if not self.drivers: return OSError("drivers not loaded")
                from brados_drivers import NetworkDriver
                net = self.drivers.get(NetworkDriver)
                if not net: return OSError("NetworkDriver not registered")
                try: return net.tcp_connect(args[0], int(args[1]),
                                             float(args[2]) if len(args) > 2 else 10.0)
                except Exception as e: return e

            case SC.SEND_SOCK:
                if not self.drivers: return OSError("drivers not loaded")
                from brados_drivers import NetworkDriver
                net = self.drivers.get(NetworkDriver)
                if not net: return OSError("NetworkDriver not registered")
                try: return net.send(int(args[0]), args[1])
                except Exception as e: return e

            case SC.RECV_SOCK:
                if not self.drivers: return OSError("drivers not loaded")
                from brados_drivers import NetworkDriver
                net = self.drivers.get(NetworkDriver)
                if not net: return OSError("NetworkDriver not registered")
                try: return net.recv(int(args[0]), int(args[1]) if len(args) > 1 else 4096)
                except Exception as e: return e

            case SC.CLOSE_SOCK:
                if not self.drivers: return 0
                from brados_drivers import NetworkDriver
                net = self.drivers.get(NetworkDriver)
                if net:
                    try: net.close(int(args[0]))
                    except Exception: pass
                return 0

            # ── Device control ────────────────────────────────────────────────

            case SC.IOCTL:
                # args: (driver_name, command, arg)
                if not self.drivers: return OSError("drivers not loaded")
                drv = self.drivers.get(str(args[0]))
                if not drv: return OSError(f"driver '{args[0]}' not found")
                try: return drv.ioctl(int(args[1]), args[2] if len(args) > 2 else None)
                except NotImplementedError as e: return e

            # ── Real subprocess (FORK / WAIT / SIGNAL) ─────────────────────────

            case SC.FORK:
                if not self.check_permission(proc.uid, Perm.PROC):
                    return PermissionError("proc permission denied")
                cmd_args = list(args[0])
                cwd      = str(args[1]) if len(args) > 1 else None
                try:
                    if self.proc_mgr:
                        return self.proc_mgr.spawn(cmd_args, cwd=cwd)
                    p = subprocess.Popen(cmd_args, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, cwd=cwd)
                    return p.pid
                except Exception as e:
                    return e

            case SC.WAIT:
                pid     = int(args[0])
                timeout = float(args[1]) if len(args) > 1 else None
                if self.proc_mgr:
                    result = self.proc_mgr.wait(pid, timeout=timeout)
                    if result is None:
                        return ProcessLookupError(f"No real process {pid}")
                    return (result["returncode"], "", "")
                return (-1, "", "process manager unavailable")

            case SC.SIGNAL:
                target_pid, sig_val = int(args[0]), args[1]
                if self.proc_mgr and self.proc_mgr.signal(target_pid, sig_val):
                    return 0
                for p in self.tasks:
                    if p.pid == target_pid:
                        p.signals.append(sig_val)
                        return 0
                return -1

            # ── Named pipes (inter-task IPC) ──────────────────────────────────

            case SC.PIPE_OPEN:
                name = str(args[0])
                with self._lock:
                    if name not in self._pipes:
                        self._pipes[name] = queue.Queue()
                return 0

            case SC.PIPE_WRITE:
                name = str(args[0])
                obj  = args[1] if len(args) > 1 else None
                with self._lock:
                    if name not in self._pipes:
                        self._pipes[name] = queue.Queue()
                    self._pipes[name].put(obj)
                return 0

            case SC.PIPE_READ:
                name = str(args[0])
                with self._lock:
                    pipe = self._pipes.get(name)
                if pipe:
                    try: return pipe.get_nowait()
                    except queue.Empty: return None
                return None

            # ── Shared memory ─────────────────────────────────────────────────

            case SC.SHMEM_PUT:
                key, val = str(args[0]), args[1] if len(args) > 1 else None
                with self._lock:
                    self._shmem[key] = val
                return 0

            case SC.SHMEM_GET:
                key = str(args[0])
                with self._lock:
                    return self._shmem.get(key)

            case SC.SHMEM_DEL:
                key = str(args[0])
                with self._lock:
                    self._shmem.pop(key, None)
                return 0

            # ── Intra-OS message bus ──────────────────────────────────────────

            case SC.NET_SEND:
                self.network_bus.put({
                    "to": args[0], "msg": args[1],
                    "from": proc.user, "ts": time.time(),
                })
                return 0

            case SC.NET_RECV:
                pending = []
                found   = None
                while not self.network_bus.empty():
                    try:
                        m = self.network_bus.get_nowait()
                        if found is None and m["to"] == proc.user:
                            found = m
                        else:
                            pending.append(m)
                    except queue.Empty:
                        break
                for m in pending:
                    self.network_bus.put(m)
                return (found["from"], found["msg"]) if found else None

            # ── Process management ────────────────────────────────────────────

            case SC.SPAWN:
                child_name = args[0]
                gfunc      = args[1]
                task_args  = args[2:]
                return self.create_task(child_name, gfunc, *task_args, uid=proc.uid)

        return -1

    # ── Scheduler ─────────────────────────────────────────────────────────────

    def _run_turns(self, proc: Process, turns: int) -> bool:
        """Execute up to *turns* syscalls for *proc*.

        Returns True if the process should be re-queued (still alive).
        """
        for _ in range(turns):
            if proc.state != ProcState.RUNNING:
                break
            tick_start = time.monotonic()
            try:
                syscall = proc.gen.send(proc.last_ret)

                if isinstance(syscall, tuple):
                    cmd, args = syscall[0], syscall[1:]
                else:
                    cmd, args = syscall, ()

                ret = self.handle_syscall(proc, cmd, args)

                if ret is None:
                    logger.info(f"Task '{proc.name}' (pid={proc.pid}) exited")
                    return False

                proc.last_ret = ret
                proc.cpu_time += time.monotonic() - tick_start

            except StopIteration:
                logger.info(f"Task '{proc.name}' (pid={proc.pid}) completed")
                return False
            except Exception as e:
                logger.error(f"Task '{proc.name}' crashed: {e}", exc_info=True)
                return False

        return proc.state not in (ProcState.ZOMBIE,)

    def tick(self, turns_per_task: int | None = 1) -> int:
        """One non-blocking scheduler epoch — safe to call from a TUI timer.

        Unlike :meth:`run`, this never sleeps waiting for tasks to wake.
        Sleeping tasks are re-queued until *wake_at*. Each runnable task
        gets ``turns_per_task`` consecutive turns (default 1); pass
        ``None`` to use the process's priority-weighted turn count.

        Returns the number of tasks that executed at least one turn.
        """
        if not self.tasks or self._shutdown.is_set():
            return 0

        executed = 0
        n = len(self.tasks)
        for _ in range(n):
            if not self.tasks or self._shutdown.is_set():
                break
            proc = self.tasks.popleft()

            if proc.state == ProcState.SLEEPING:
                if time.monotonic() < proc.wake_at:
                    self.tasks.append(proc)
                    continue
                proc.state = ProcState.RUNNING
                proc.last_ret = 0  # sleep returns 0

            if proc.state != ProcState.RUNNING:
                continue

            turns = proc.priority_turns if turns_per_task is None else max(1, turns_per_task)
            alive = self._run_turns(proc, turns)
            if alive:
                self.tasks.append(proc)
            executed += 1

        return executed

    def run(self):
        """
        Priority-weighted cooperative round-robin scheduler.

        Each epoch iterates the task deque once.  A process with nice=0
        gets up to 5 consecutive turns; nice=19 gets 1.  A turn is:
          1. send(last_ret) → get next syscall
          2. handle_syscall → compute ret
          3. store ret as last_ret for next turn

        SLEEP is non-blocking: sleeping tasks are skipped until wake_at.
        EXIT: task is removed; its generator is not re-queued.

        For embedding in a Textual/async UI, prefer :meth:`tick` instead.
        """
        logger.info("Scheduler started")

        while self.tasks and not self._shutdown.is_set():
            proc = self.tasks.popleft()

            # Skip sleeping tasks
            if proc.state == ProcState.SLEEPING:
                if time.monotonic() < proc.wake_at:
                    self.tasks.append(proc)
                    time.sleep(0.01)
                    continue
                proc.state    = ProcState.RUNNING
                proc.last_ret = 0   # sleep returns 0

            if proc.state != ProcState.RUNNING:
                continue

            alive = self._run_turns(proc, proc.priority_turns)
            if alive:
                self.tasks.append(proc)

            time.sleep(0.001)

        logger.info("Scheduler stopped")

    def shutdown(self):
        self._shutdown.set()
        if self.proc_mgr:
            self.proc_mgr.shutdown()
        elif hasattr(self, '_real_procs'):
            with self._lock:
                for p in self._real_procs.values():
                    try: p.terminate()
                    except Exception: pass
        logger.info("Kernel shutdown")

    def log(self, message: str):
        logger.info(message)


# ── Desktop-friendly kernel tasks (no PRINT/INPUT — safe under Textual) ───────

def desktop_clock_task():
    """Publish wall-clock time to shared memory every second."""
    while True:
        yield (SC.SHMEM_PUT, "sys.clock", time.strftime("%Y-%m-%d %H:%M:%S"))
        yield (SC.SLEEP, 1.0)


def desktop_status_task():
    """Heartbeat task: pid + monotonic uptime marker in shared memory."""
    while True:
        pid = yield (SC.GETPID,)
        now = yield (SC.GET_TIME,)
        yield (SC.SHMEM_PUT, "sys.status", {"pid": pid, "time": now})
        yield (SC.SLEEP, 2.0)

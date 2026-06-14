# ⬡ BradOS

**v3.0.0 · Ocean Dark · The only real OS-layer that runs in a terminal.**

No other Python project in this space has a kernel, a mount-table VFS, capability-based security, real TCP networking, and a 14-app TUI desktop. BradOS is not a menu loop with print statements. It is a working software stack.

```
python brados.py --shell
```

---

## What makes BradOS unique

Every other "Python OS" project is cosmetic — fake progress bars, fake authentication, Wi-Fi ON/OFF toggles that flip a boolean. BradOS does the real thing:

**Kernel.** 35 syscalls. Priority-weighted cooperative scheduler (nice 0–19). Shared memory, named pipes, real subprocess fork/wait, IOCTL device control.

**VFS.** Mount-table filesystem with 6 drivers: MemFS (in-memory trie), LocalFS (sandboxed host with atomic writes and path-traversal protection), ProcFS (live kernel stats), DevFS (/dev/null, /dev/random, /dev/zero, /dev/tty, /dev/kmsg).

**Network.** Real TCP/UDP sockets via the host kernel. DNS resolution. HTTP client with `requests` preferred, `urllib` fallback. TCP listen/accept. UDP sendto/recvfrom.

**Security.** HMAC-SHA256 capability tokens (tampering-detected on modification). PBKDF2-260k password hashing. SHA-256 file integrity daemon. PBKDF2+Fernet encrypted vault. Threat scanner that checks world-writable files, open ports (including known backdoor ports), weak permissions, and plaintext passwords.

**Desktop.** Splash → Login → Icon grid → Taskbar. 14 apps. Minimize/restore. Keyboard shortcuts. Live CPU/RAM tray. Staggered entrance animation. Ocean Dark theme. All in Textual.

**Tests.** 65+ pytest tests covering every subsystem, including async workers, token tampering detection, path traversal blocking, and scheduler correctness.

---

## Architecture (11,100 lines, 12 files)

```
brados.py                  ← Entry point
│
├── brados_shell.py        ← Textual desktop (3173 lines)
│     14 screens            Splash, Login, Desktop, 14 app windows
│
├── brados_kernel_core.py  ← Cooperative microkernel (707 lines)
│     35 syscalls            VFS I/O, sockets, fork/wait, pipes, SHMEM
│     Priority scheduler     nice 0-19, weighted round-robin
│     PBKDF2 auth            auto-rehash legacy passwords
│
├── brados_vfs.py          ← Virtual filesystem (697 lines)
│     6 mountable drivers    MemFS, LocalFS, ProcFS, DevFS, VarFS
│     Thread-safe            All operations under RLock
│     Atomic writes          tmp → replace, crash-safe
│
├── brados_drivers.py      ← Driver subsystem (651 lines)
│     6 drivers              Network, Display, Storage, Input, Audio, Process
│     Singleton registry     init/shutdown lifecycle, graceful degradation
│
├── brados_security.py     ← BradSec security (652 lines)
│     Capability tokens      HMAC-SHA256 signed, TTL, tamper-proof
│     Integrity daemon       SHA-256 manifest, ADDED/MODIFIED/DELETED
│     Encrypted vault        PBKDF2 → Fernet, XOR fallback
│     Threat scanner         perms, ports, hashes, known backdoor ports
│     Audit log              NDJSON append-only, streamable, greppable
│
├── brados_apps.py         ← Classic-mode apps (967 lines)
│     Safe eval              AST-based math evaluator (no exec())
│     HTML parser            Skip-stack, handles nested <head><script>
│     Mail, browser, calc, editor, games, hub
│
├── brados_system.py       ← System layer (734 lines)
│     Emoji detection        Probes LANG/LC_ALL/TERM_PROGRAM
│     Profile management     Atomic JSON, auto-backfill
│     Diagnostics            Real module imports, Python version checks
│
├── brados_bpkg.py         ← Package manager (587 lines)
│     8 curated packages     psutil, requests, cryptography, Pillow, pyte
│     Remote registry        GitHub-sourced, 6h cache TTL
│     pip integration        Streaming output, dependency resolution
│
└── brados_test.py         ← Test suite (656 lines)
      Subsystem tests         VFS, Drivers, Kernel, Security, Apps, Shell, bpkg
      Async tests             Workers avoid blocking the event loop
      Lint enforcement        no call_from_thread, no @work(thread=True)
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/yourusername/BradOS.git
cd BradOS

# One dependency required (textual). Everything else optional.
pip install textual

# Launch the desktop
python brados.py --shell

# With optional enhancements
pip install psutil requests cryptography
python brados.py --shell

# Run the test suite (65+ tests)
pip install pytest pytest-asyncio
pytest brados_test.py -v
```

---

## BradSec — Security (not cosmetic)

```python
from brados_security import BradSec, Cap

sec = BradSec()
sec.start()

# Issue a signed capability token
token = sec.issue_token(pid=1, uid=1000,
                        caps=Cap.FS_READ | Cap.NET_SEND)

# Check capabilities — HMAC-SHA256 verified every call
sec.check_cap(pid=1, cap=Cap.FS_WRITE)   # False
sec.check_cap(pid=1, cap=Cap.NET_SEND)   # True

# Integrity check — SHA-256 of all .py/.json/.log files
findings = sec.verify_integrity()

# Threat scan — real checks, not fake progress bars
findings = sec.scan()
# World-writable files? Weak password hashes? Open ports? Reported.

# Encrypted vault — PBKDF2 → Fernet (or XOR fallback)
sec.unlock_vault("master_password")
sec.vault.put("api_key", "sk-...")
sec.vault.get("api_key")

# Append-only NDJSON audit trail
sec.audit.write("INFO", "AUTH", "User logged in", {"user": "brad"})
sec.audit.tail(50)
```

---

## VFS — Virtual Filesystem

```python
from brados_vfs import create_default_vfs

vfs = create_default_vfs()

# Standard operations — works across all mounted drivers
vfs.write_text("/home/user/notes.txt", "BradOS v3")
vfs.read_text("/home/user/notes.txt")
vfs.listdir("/home/user")
vfs.stat("/home/user/notes.txt")   # → VFSStat(.size, .mode_str, .mtime…)

# Virtual filesystems
vfs.read_text("/proc/version")      # "BradOS version 3.0.0 (Python 3.12…)"
vfs.read_text("/proc/cpuinfo")      # vendor_id: BradOS
vfs.read_text("/proc/meminfo")      # MemTotal / MemFree / SwapTotal
vfs.read("/dev/random", 16)         # 16 cryptographically random bytes
vfs.write("/dev/null", b"discard")  # silently consumed

# Path traversal is blocked
vfs.read("/home/../../../etc/passwd")  # → PermissionError

# Walk
for dirpath, dirs, files in vfs.walk("/"):
    print(dirpath, files)
```

---

## Kernel — 35 Syscalls

```python
from brados_kernel_core import BradOSKernel, SC

kernel = BradOSKernel()
kernel.vfs     = vfs
kernel.drivers = drivers

# Tasks are generators. yield = syscall. send() = return value.
def my_task():
    yield (SC.VFS_WRITE, "/tmp/data.txt", b"hello from kernel")
    content = yield (SC.VFS_READ, "/tmp/data.txt")
    fd = yield (SC.CONNECT, "example.com", 443, 10.0)
    yield (SC.SEND_SOCK, fd, b"GET / HTTP/1.1\r\nHost: ...\r\n\r\n")
    data = yield (SC.RECV_SOCK, fd, 4096)
    yield (SC.CLOSE_SOCK, fd)
    yield (SC.SHMEM_PUT, "result", data)
    yield (SC.EXIT,)

pid = kernel.create_task("MyTask", my_task, uid=1000, nice=5)
kernel.run()
```

**Scheduler:** Priority-weighted round-robin. nice=0 gets 5 consecutive turns per epoch; nice=19 gets 1. Sleeping tasks are skipped (non-blocking). Zombie tasks are collected.

**Syscall categories:**
- Core I/O (PRINT, INPUT, SLEEP, EXIT, GET_TIME)
- Filesystem (READ_FILE, WRITE_FILE, LIST_DIR — legacy host-direct)
- VFS (VFS_READ, VFS_WRITE, VFS_LIST, VFS_STAT, VFS_MKDIR, VFS_UNLINK)
- Networking (SOCKET, CONNECT, SEND_SOCK, RECV_SOCK, CLOSE_SOCK)
- Process (SPAWN, GETPID, SIGNAL, FORK, WAIT)
- IPC (PIPE_OPEN, PIPE_WRITE, PIPE_READ, NET_SEND, NET_RECV)
- Shared Memory (SHMEM_PUT, SHMEM_GET, SHMEM_DEL)
- Device (IOCTL)

---

## Test Suite — 65+ tests, real coverage

```bash
pip install pytest pytest-asyncio
pytest brados_test.py -v
```

| Module | Tests | What's verified |
|--------|-------|-----------------|
| VFS | 11 | write/read, listdir, mkdir, unlink, rename, procfs, devfs, memfs, path traversal, walk |
| Drivers | 8 | registry, display size/colors, network hostname/IP, storage free, missing driver |
| Kernel | 11 | VFS syscalls, SHMEM, pipes, IOCTL, NET_SEND/RECV, auth, password hashing, scheduler |
| BradSec | 12 | token issue/verify/tamper/revoke, audit, integrity, vault, scanner, status |
| Apps | 6 | safe_eval (builtins blocked), HTML parser (script/style nested stripping) |
| Shell | 13 | class hierarchy, APP_ID verification, lint rules, manifest completeness |
| bpkg | 13 | registry search, install/remove, persistence, categories, pip status |
| Async | 4 | worker thread safety, event loop non-blocking |

---

## Keyboard Shortcuts

| Key | App | Key | App |
|-----|-----|-----|-----|
| `t` | Terminal | `b` | Browser |
| `f` | Files | `e` | Editor |
| `m` | Mail | `n` | Notes |
| `c` | Calculator | `k` | Clock |
| `p` | Monitor | `g` | Logs |
| `Ctrl+K` | Kernel Tasks | `s` | Settings |
| `Shift+S` | BradSec | `Ctrl+P` | bpkg |
| `l` | Logout | `q` | Quit |
| `F1` | Help | `—` Minimize |

---

## bpkg — Package Manager

```bash
# Inside BradOS: open the bpkg app
# Available packages:

brad-psutil      Live CPU/RAM/disk metrics    pip: psutil
brad-requests    Full HTTPS for browser        pip: requests
brad-crypto      Fernet vault encryption       pip: cryptography
brad-imaging     SVG viewer + image processing pip: Pillow, cairosvg
brad-pty         VT100 PTY terminal            pip: pyte
brad-audio       System sounds + music         pip: playsound
brad-full        Install everything above      meta-package
brad-dev         pytest, mypy, black, ruff     dev tools
```

---

## Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `textual` | **Yes** | TUI framework (the only hard dep) |
| `psutil` | Optional | Live CPU/RAM/disk in tray + Monitor |
| `requests` | Optional | HTTPS in browser (stdlib fallback exists) |
| `cryptography` | Optional | Fernet vault (XOR fallback exists) |
| `pytest` | Dev | Test suite |

Everything else: `asyncio`, `hashlib`, `socket`, `json`, `os`, `threading`, `queue`, `dataclasses`, `enum`, `abc`, `html.parser`, `subprocess`, `platform`, `shutil`, `random`, `time`, `datetime`, `math`, `functools`, `pathlib`, `typing`.

**Zero native deps. Zero compiled extensions. Pure Python. Runs everywhere Python runs.**

---

## Modes

```bash
python brados.py --shell     # Ocean Dark desktop (recommended — full experience)
python brados.py --gui       # Legacy Textual GUI (purple theme)
python brados.py             # Interactive mode selector
```

---

## License

MIT — go ahead, build on it.

---

*11,100 lines of Python. Zero kernel modules. Zero C extensions. A genuine OS-layer that fits in a terminal.*

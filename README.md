# ⬡ BradOS

**v3.0 · Ocean Dark · A pure-Python userland OS layer for the terminal.**

BradOS is a **cooperative microkernel + mount-table VFS + capability security + Textual desktop** you can run over SSH or Termux. It is **not** a host operating system and does **not** replace Linux — it runs *on* Python and uses the host for real sockets, processes, and files (inside a sandbox).

```bash
pip install textual
python brados.py --shell
```

---

## What BradOS is / isn’t

| Is | Isn’t |
|----|--------|
| A layered **userland OS demo** with real subsystems | A bootable OS or kernel module |
| VFS with path traversal checks + capability gates | A full multi-user MAC like SELinux |
| HMAC-signed capability tokens enforced on VFS ops | Kernel-enforced isolation between host processes |
| Cooperative tasks with 35 syscalls + non-blocking `tick()` | Preemptive SMP scheduling |
| A TUI desktop (Textual) with many apps | A replacement for your window manager |

Many “Python OS” toys are menu loops and fake progress bars. BradOS aims higher: **checkable behavior** (tests, deny demos, live Kernel tasks) rather than marketing alone.

---

## 60-second demo (the “wow” path)

1. **Launch**
   ```bash
   git clone https://github.com/Architect-Brad/BradOS.git
   cd BradOS
   pip install textual
   python brados.py --shell
   ```
2. Pass splash / login (guest is fine).
3. Press **`Ctrl+K`** → **Kernel** task table.  
   You should see **DesktopClock** and **SysStatus** with live state / CPU time. Shared memory shows `sys.clock` after a second.
4. Press **`Shift+S`** → **BradSec** → **⚡ Cap Demo** (or the Cap Demo button).  
   Expect **PASS** on:
   - Guest VFS write **DENIED** (no `FS_WRITE`)
   - Guest VFS read **allowed**
   - Session VFS write **allowed**
   - `check_cap(guest, FS_WRITE) = False`
5. Optional: **Files** app, open `/proc/version` via VFS-backed paths; **Monitor** if `psutil` is installed.

That’s the product story: *live kernel tasks + real capability deny*, not a wallpaper OS.

---

## Quick start

```bash
git clone https://github.com/Architect-Brad/BradOS.git
cd BradOS

# Required for the desktop
pip install textual

# Recommended optional deps
pip install psutil requests cryptography pyyaml

# BradMusic tags (playback still needs mpv or ffmpeg on the host)
pip install 'brados[music]'   # or: pip install mutagen

python brados.py --shell     # Ocean Dark desktop (recommended)
python brados.py             # Classic menu / mode selector
python brados.py --daemon    # BradSec background daemon only

# Tests (130+)
pip install pytest pytest-asyncio
pytest brados_test.py -v
```

**Termux (Android):** see [TERMUX.md](TERMUX.md) and `bash scripts/termux-setup.sh`.

### Modes

| Command | Purpose |
|---------|---------|
| `python brados.py --shell` | Full desktop (default experience) |
| `python brados.py` | Classic interactive menus |
| `python brados.py --daemon` | BradSec daemon |
| `python brados.py --gui` | **Legacy** purple Textual UI (unmaintained; prefer `--shell`) |

---

## Architecture

```
brados.py                  ← Entry + mode dispatch
│
├── brados_shell.py        ← Textual desktop (splash, login, apps)
├── brados_kernel_core.py  ← Cooperative microkernel (syscalls, tick/run)
├── brados_vfs.py          ← Mount-table VFS (Mem/Local/Proc/Dev + caps)
├── brados_process.py      ← Host subprocesses exposed under /proc/<pid>
├── brados_drivers.py      ← Network, display, storage, input, audio, …
├── brados_security.py     ← BradSec tokens, vault, scan, daemon, cap demo
├── brados_brash.py        ← Terminal shell (aliases, && / || / ;)
├── brados_bpkg.py         ← Package manager (checksum-pinned scripts)
├── brados_music.py        ← Music player window
├── brados_mesh.py         ← LAN mesh helpers
├── brados_apps.py         ← Classic-mode apps + pure helpers
├── brados_system.py       ← Profiles, ANSI, Termux/mobile helpers
└── brados_test.py         ← Pytest suite
```

### Kernel

- ~35 syscalls (VFS, sockets, fork/wait, pipes, shmem, ioctl, …)
- Priority-weighted cooperative scheduler (`nice` 0–19)
- **`tick()`** for embedding in the Textual loop (non-blocking sleeps)
- Desktop boots **DesktopClock** + **SysStatus** into shared memory

### VFS

- Drivers: MemFS, LocalFS (sandboxed host paths, atomic writes), ProcFS, DevFS
- Path traversal blocked on LocalFS
- Optional BradSec: `caller_pid` must hold `FS_READ` / `FS_WRITE`

### BradSec

- HMAC-SHA256 capability tokens (tamper-evident)
- Guest vs session demo: `run_capability_demo(vfs)` / UI **Cap Demo**
- Integrity baseline (SHA-256), vault (Fernet or XOR fallback), NDJSON audit
- Optional daemon + `brados_policy.yaml`

### Desktop

- Splash → Login → icon grid / start menu → taskbar
- Apps include terminal, files, editor, browser, mail, BradSec, bpkg, games, music, mesh, …
- Ocean Dark theme; keyboard shortcuts below

---

## Capability demo (code)

```python
from brados_security import BradSec, Cap, run_capability_demo, DEMO_GUEST_PID
from brados_vfs import create_default_vfs

sec = BradSec()
sec.start()
vfs = create_default_vfs()
vfs.set_sec(sec)

results = run_capability_demo(vfs, sec)
assert all(r["ok"] for r in results)

# Guest still cannot write:
# vfs.write_text("/tmp/x", "nope", caller_pid=DEMO_GUEST_PID)  → PermissionError
```

---

## Keyboard shortcuts

| Key | App | Key | App |
|-----|-----|-----|-----|
| `t` | Terminal | `b` | Browser |
| `f` | Files | `e` | Editor |
| `m` | Mail | `n` | Notes |
| `c` | Calculator | `k` | Clock |
| `p` | Monitor | `g` | Logs |
| `Ctrl+K` | Kernel tasks | `s` | Settings |
| `Shift+S` | BradSec | `Ctrl+P` | bpkg |
| `l` | Logout | `q` / `Ctrl+Q` | Quit |
| `F1` | Help | `—` | Minimize |

---

## Tests & CI

```bash
pip install pytest pytest-asyncio textual
pytest brados_test.py -v
```

Coverage includes VFS, drivers, kernel (`tick`, desktop tasks), BradSec (tokens, vault, **capability demo**), brash, bpkg trust model, shell boot (kernel always attached), and CSS health checks. GitHub Actions runs the suite on Python 3.12–3.14.

---

## Dependencies

| Package | Required | Purpose |
|---------|----------|---------|
| `textual` | **Yes** (desktop) | TUI framework |
| `mutagen` | Optional (`brados[music]`) | Rich tags/cover art in BradMusic |
| `mpv` / `ffmpeg` | Optional (host) | Real audio playback for BradMusic |
| `psutil` | Optional | Live CPU/RAM/disk |
| `requests` | Optional | HTTPS browser (urllib fallback) |
| `cryptography` | Optional | Fernet vault (XOR fallback) |
| `pyyaml` | Optional | Policy files |
| `pytest` | Dev | Test suite |

Pure Python application code — no custom C extensions.

---

## bpkg (in-desktop packages)

Curated extras: `brad-psutil`, `brad-requests`, `brad-crypto`, `brad-imaging`, `brad-pty`, `brad-audio`, `brad-full`, `brad-dev`. Remote install scripts must match pinned SHA-256; builtins are trusted in-tree.

---

## License

MIT — see [LICENSE](LICENSE).

---

*A genuine userland OS-layer that fits in a terminal: VFS, capabilities, cooperative kernel, and a desktop you can demo in under a minute.*

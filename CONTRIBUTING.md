# Contributing to BradOS

Thanks for helping improve BradOS. This is a **pure-Python userland OS layer** (kernel + VFS + BradSec + Textual desktop) — not a host kernel. Contributions that make subsystems **real and testable** beat cosmetic “OS simulator” fluff.

## Quick setup

```bash
git clone https://github.com/Architect-Brad/BradOS.git
cd BradOS
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install textual pytest pytest-asyncio
# Optional: psutil requests cryptography pyyaml mutagen

python brados.py --shell    # desktop
pytest brados_test.py -q    # tests (must stay green)
```

**Python:** 3.12+ (CI runs 3.12, 3.13, 3.14).  
**Termux:** see [TERMUX.md](TERMUX.md).

## Project map

| Module | Role |
|--------|------|
| `brados.py` | Entry / modes (`--shell`, classic, `--daemon`) |
| `brados_shell.py` | Textual desktop (large — touch carefully) |
| `brados_kernel_core.py` | Cooperative kernel, syscalls, `tick()` |
| `brados_vfs.py` | Mount-table VFS + capability checks |
| `brados_security.py` | BradSec tokens, vault, Cap Demo |
| `brados_process.py` | Host processes → `/proc/<pid>` |
| `brados_brash.py` | Terminal shell |
| `brados_bpkg.py` | Package manager |
| `brados_music.py` | BradMusic (optional deps) |
| `brados_test.py` | Pytest suite |
| `brados_gui.py` | **Legacy** UI — prefer not extending |

Public-ish building blocks: `create_default_vfs()`, `BradOSKernel`, `get_bradsec()`, `run_capability_demo()`, `run_shell()`.

## Development norms

1. **Tests first when possible** — add or extend cases in `brados_test.py`.
2. **Prefer real behavior** over fake progress bars / hard-coded “secure” claims.
3. **Graceful degradation** — optional deps (`psutil`, `cryptography`, `mutagen`, host `mpv`) must not crash import/startup when missing.
4. **Keep CI green** — GitHub Actions runs the full suite on every push/PR to `main`.
5. **No secrets in the repo** — logs, keys, local `brados_files/`, profiles are gitignored for a reason.

### Textual / shell rules (enforced by tests)

Avoid these in desktop app code (see existing shell lint tests):

- `call_from_thread` for UI updates (prefer `@work` async patterns that hop back safely)
- `@work(thread=True)` in shell windows when it breaks the event-loop contract the suite checks

When writing background work, follow patterns already used in Monitor / tray stats (`@work` + await, or timers).

### Security / VFS

- Prefer VFS APIs with `caller_pid` when doing privileged I/O.
- Desktop session PID and guest demo PID live in `brados_security` (`DEMO_SESSION_PID`, `DEMO_GUEST_PID`).
- Capability story must stay **checkable** — don’t gut Cap Demo or token HMAC checks without replacing them with something stronger and tested.

## How to add a desktop app

`brados_shell.py` is still a large single file. New apps usually land there (or in a dedicated module like `brados_music.py` if they are heavy).

### Checklist

1. **Subclass `BradWindow`** (not bare `Screen`), set `APP_ID`:

   ```python
   class MyAppWindow(BradWindow):
       APP_ID: ClassVar[str] = "myapp"
       BINDINGS: ClassVar = [Binding("escape", "dismiss", "Close")]

       def compose(self) -> ComposeResult:
           with Horizontal(classes="win-titlebar"):
               yield Static("…  My App", classes="win-title")
               yield Button("—", id="btn-min", classes="btn-min")
               yield Button("✕", id="btn-close", classes="win-close")
           # … body …
   ```

2. **Register in `APPS`** (icon grid / start menu metadata):

   ```python
   {"id": "myapp", "icon": "★", "name": "My App", "desc": "…", "cat": "Utilities"},
   ```

   Categories used today: `System`, `Productivity`, `Utilities`, `Creative`, `Games`, `Network`, `Media`.

3. **Wire the launcher** in `DesktopScreen._open` `screen_map`  
   and, if needed, `MobileLauncher._app_screen` id→class map.

4. **Optional keyboard shortcut** on `DesktopScreen.BINDINGS`.

5. **Minimize** — use titlebar `#btn-min` from `BradWindow` (do not invent a second minimize path).

6. **Tests** — at least:
   - window class subclasses `BradWindow`
   - `APP_ID` matches `APPS` entry
   - pure helpers unit-tested if you add logic in `brados_apps.py` or a new module

7. **Prefer a new module** for large apps (pattern: `brados_music.py` + thin import in shell). Long-term goal is splitting `brados_shell.py`; don’t make it harder without reason.

### Minimal pure-logic placement

Reusable non-UI helpers belong in `brados_apps.py` (or a focused module), not buried only in a window class — keeps pytest easy.

## How to change core subsystems

| Area | Guidance |
|------|----------|
| Kernel | Keep generator/syscall style; prefer `tick()` for anything TUI-related |
| VFS | Keep path-traversal protection and cap hooks; add tests |
| BradSec | Token tamper detection and Cap Demo must remain meaningful |
| bpkg | Untrusted install scripts need checksums; don’t weaken without design |
| Drivers | Soft-fail on `PermissionError` / missing libs (Termux) |

## Running tests

```bash
pip install pytest pytest-asyncio textual
pytest brados_test.py -v --tb=short

# One class / test
pytest brados_test.py::TestVFS -q
pytest brados_test.py::TestBradSec::test_capability_demo_guest_write_denied -q
```

CI command (see `.github/workflows/test.yml`):

```bash
python -m pytest brados_test.py -v --tb=short
```

## Pull requests

1. Branch from up-to-date `main`.
2. Keep PRs focused (one feature or fix).
3. Ensure `pytest brados_test.py` passes locally.
4. Describe **what** and **why**; link issues if any.
5. Don’t commit runtime junk: `__pycache__/`, `brados.log`, `brados_audit.log`, `brados_files/`, `user_profiles/`.
6. Avoid drive-by refactors of the whole shell unless the PR *is* a modularization step.

### Commit style (suggested)

```
feat(shell): …
fix(vfs): …
test(security): …
docs: …
chore: …
```

## What we are *not* looking for (right now)

- Expanding the legacy `--gui` surface
- Fake “security scans” or cosmetic OS chrome without tests
- New games/themes at the expense of core stability
- Host-kernel / bootloader scope creep

## Reporting bugs

Include:

- OS / Termux vs desktop, terminal size if UI-related  
- BradOS version or git tag (e.g. `v3.1.0`)  
- Command used (`python brados.py --shell`, etc.)  
- Full traceback  
- Whether optional deps / `mpv` / `psutil` are installed  

## Code of conduct

Be respectful. Assume good intent. This is a learning-friendly systems project — teach when you review, and prefer precise technical disagreement over style nits.

## License

By contributing, you agree your contributions are licensed under the same **MIT** license as BradOS (see [LICENSE](LICENSE)).

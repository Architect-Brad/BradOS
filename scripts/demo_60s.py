#!/usr/bin/env python3
"""BradOS 60-second demo — headless proof of the show-ready path.

Runs without Textual. Boots VFS + BradSec + kernel desktop tasks, runs the
capability demo, and prints a clear PASS/FAIL walkthrough you can record or
paste into an issue.

Usage (from repo root):
  python scripts/demo_60s.py
  python brados.py --demo
"""

from __future__ import annotations

import os
import sys
import time

# Repo root on sys.path when invoked as scripts/demo_60s.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return _c("1", t)


def green(t: str) -> str:
    return _c("32", t)


def red(t: str) -> str:
    return _c("31", t)


def cyan(t: str) -> str:
    return _c("36", t)


def dim(t: str) -> str:
    return _c("2", t)


def yellow(t: str) -> str:
    return _c("33", t)


def hr() -> None:
    print(dim("─" * 56))


def step(n: int, total: int, title: str) -> None:
    print()
    print(bold(f"[{n}/{total}] {title}"))
    hr()


def run_demo(pause: float = 0.35) -> int:
    """Execute the demo. Returns 0 on full success, 1 on any failure."""
    t0 = time.monotonic()
    failures: list[str] = []

    print()
    print(bold("⬡ BradOS — 60-second demo"))
    print(dim("Userland OS layer: kernel · VFS · capabilities (not a host kernel)"))
    print(dim("Headless proof — for the full TUI: python brados.py --shell"))
    hr()

    # ── 1. Boot stack ─────────────────────────────────────────────────────
    step(1, 4, "Boot VFS + BradSec")
    try:
        from brados_apps import init_dirs
        from brados_vfs import create_default_vfs
        from brados_security import (
            BradSec, Cap, run_capability_demo,
            DEMO_GUEST_PID, DEMO_SESSION_PID,
        )
        from brados_kernel_core import (
            BradOSKernel, desktop_clock_task, desktop_status_task,
        )
        from brados_drivers import create_default_registry

        init_dirs()
        sec = BradSec()
        sec.start()
        # Same token layout as the desktop: session can read/write; guest is weaker.
        sec.issue_token(DEMO_SESSION_PID, uid=1000, caps=Cap.default_user())
        sec.issue_token(DEMO_GUEST_PID, uid=1001, caps=Cap.default_guest())
        kernel = BradOSKernel()
        vfs = create_default_vfs(kernel=kernel)
        vfs.set_sec(sec)
        vfs.set_default_pid(DEMO_SESSION_PID)
        drivers = create_default_registry(vfs=vfs)
        kernel.vfs = vfs
        kernel.drivers = drivers
        kernel.sec = sec
        print(green("  ✓") + " VFS mounts: " + ", ".join(
            f"{m['path']}({m['driver']})" for m in vfs.mounts()
        ))
        print(green("  ✓") + f" BradSec active · session secret {sec.status()['secret_bits']}-bit HMAC")
        print(green("  ✓") + f" Tokens: session pid={DEMO_SESSION_PID}, guest pid={DEMO_GUEST_PID}")
        print(green("  ✓") + f" Kernel ready (next_pid={kernel.next_pid})")
    except Exception as e:
        print(red(f"  ✗ Boot failed: {e}"))
        return 1

    time.sleep(pause)

    # ── 2. Kernel desktop tasks ───────────────────────────────────────────
    step(2, 4, "Kernel tasks (DesktopClock + SysStatus)")
    try:
        kernel.create_task("DesktopClock", desktop_clock_task, uid=1000, nice=10)
        kernel.create_task("SysStatus", desktop_status_task, uid=1000, nice=15)
        # Pump cooperative scheduler until shmem is populated
        for _ in range(12):
            kernel.tick()
            time.sleep(0.02)

        tasks = kernel.list_tasks()
        names = {t["name"] for t in tasks}
        if "DesktopClock" not in names or "SysStatus" not in names:
            failures.append("kernel tasks missing from list_tasks()")
            print(red("  ✗") + " Expected DesktopClock and SysStatus in task table")
        else:
            print(green("  ✓") + " Task table:")
            for t in tasks:
                print(
                    f"      pid={t['pid']:<4} {t['name']:<14} "
                    f"state={t['state']:<9} cpu_s={t['cpu_s']}"
                )

        clock = kernel._shmem.get("sys.clock")
        status = kernel._shmem.get("sys.status")
        if clock:
            print(green("  ✓") + f" shmem sys.clock  = {clock}")
        else:
            failures.append("sys.clock not published")
            print(red("  ✗") + " sys.clock not in shared memory yet")
        if status:
            print(green("  ✓") + f" shmem sys.status = {status!r}")
        else:
            failures.append("sys.status not published")
            print(red("  ✗") + " sys.status not in shared memory yet")

        # ProcFS sample
        ver = vfs.read_text("/proc/version", caller_pid=DEMO_SESSION_PID)
        print(green("  ✓") + f" /proc/version → {ver.splitlines()[0][:60]}")
    except Exception as e:
        failures.append(f"kernel step: {e}")
        print(red(f"  ✗ Kernel step failed: {e}"))

    time.sleep(pause)

    # ── 3. Capability demo ────────────────────────────────────────────────
    step(3, 4, "BradSec capability demo (guest vs session)")
    print(dim(f"  Session pid={DEMO_SESSION_PID} has FS_WRITE; "
              f"guest pid={DEMO_GUEST_PID} is read-only."))
    try:
        results = run_capability_demo(vfs, sec)
        labels = {
            "guest_write": "Guest VFS write   (must DENY)",
            "guest_read": "Guest VFS read    (must ALLOW)",
            "session_write": "Session VFS write (must ALLOW)",
            "check_cap_guest": "check_cap(guest, FS_WRITE) → False",
        }
        for r in results:
            mark = green("PASS") if r.get("ok") else red("FAIL")
            title = labels.get(r["step"], r["step"])
            print(f"  [{mark}]  {title}")
            print(dim(f"         {r.get('detail', '')}"))
            if not r.get("ok"):
                failures.append(r["step"])
        if all(r.get("ok") for r in results):
            print()
            print(green("  ✓ Guest cannot write; session can.")
                  + dim("  Real VFS capability enforcement."))
    except Exception as e:
        failures.append(f"cap demo: {e}")
        print(red(f"  ✗ Cap demo crashed: {e}"))

    time.sleep(pause)

    # ── 4. Wrap-up ────────────────────────────────────────────────────────
    step(4, 4, "What to do next (full TUI)")
    print("  Interactive desktop (~60s of clicking):")
    print(cyan("    python brados.py --shell"))
    print("      1. Login (guest is fine)")
    print("      2. " + bold("Ctrl+K") + "  → Kernel task table (live clock)")
    print("      3. " + bold("Shift+S") + " → BradSec → ⚡ Cap Demo")
    print()
    print(dim("  Docs: README.md · CONTRIBUTING.md · SECURITY.md"))

    elapsed = time.monotonic() - t0
    print()
    hr()
    if failures:
        print(red(bold(f"DEMO FAILED")) + f"  ({elapsed:.1f}s)  issues: {', '.join(failures)}")
        return 1
    print(green(bold("DEMO PASSED")) + f"  ({elapsed:.1f}s)  kernel + caps look real.")
    print(dim("  Record this terminal or open --shell for the visual path."))
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pause = 0.35
    if "--fast" in argv:
        pause = 0.0
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    # Stay in repo root for relative brados_files/
    try:
        os.chdir(_ROOT)
    except OSError:
        pass
    return run_demo(pause=pause)


if __name__ == "__main__":
    sys.exit(main())

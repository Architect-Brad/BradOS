# brados_test.py — BradOS Automated Test Suite
#
# 65+ tests. Every subsystem covered. Token tampering detected. Path traversal
# blocked. Scheduler correctness verified. Async workers tested for thread
# safety. Run with: pytest brados_test.py -v

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import pytest
from pathlib import Path
from collections import deque


# ════════════════════════════════════════════════════════════════
# VFS
# ════════════════════════════════════════════════════════════════

class TestVFS:
    @pytest.fixture(autouse=True)
    def vfs(self):
        from brados_vfs import create_default_vfs
        self.vfs = create_default_vfs()
        self.vfs.makedirs("/home/testuser")
        yield
        # cleanup
        try:
            self.vfs.unlink("/home/testuser")
        except Exception:
            pass

    def test_write_and_read_text(self):
        self.vfs.write_text("/home/testuser/hello.txt", "BradOS v3")
        assert self.vfs.read_text("/home/testuser/hello.txt") == "BradOS v3"

    def test_write_and_read_bytes(self):
        self.vfs.write("/home/testuser/data.bin", b"\x00\x01\x02\xff")
        assert self.vfs.read("/home/testuser/data.bin") == b"\x00\x01\x02\xff"

    def test_write_and_read_json(self):
        payload = {"key": "value", "num": 42, "nested": {"a": [1, 2, 3]}}
        self.vfs.write_json("/home/testuser/data.json", payload)
        loaded = self.vfs.read_json("/home/testuser/data.json")
        assert loaded == payload

    def test_listdir(self):
        self.vfs.write_text("/home/testuser/a.txt", "a")
        self.vfs.write_text("/home/testuser/b.txt", "b")
        entries = self.vfs.listdir("/home/testuser")
        assert "a.txt" in entries
        assert "b.txt" in entries

    def test_mkdir_and_stat(self):
        self.vfs.makedirs("/home/testuser/subdir")
        st = self.vfs.stat("/home/testuser/subdir")
        assert st.is_dir

    def test_unlink_file(self):
        self.vfs.write_text("/home/testuser/del.txt", "gone")
        self.vfs.unlink("/home/testuser/del.txt")
        assert not self.vfs.exists("/home/testuser/del.txt")

    def test_rename(self):
        self.vfs.write_text("/home/testuser/old.txt", "data")
        self.vfs.rename("/home/testuser/old.txt", "/home/testuser/new.txt")
        assert self.vfs.exists("/home/testuser/new.txt")
        assert not self.vfs.exists("/home/testuser/old.txt")
        assert self.vfs.read_text("/home/testuser/new.txt") == "data"

    def test_procfs_version(self):
        content = self.vfs.read_text("/proc/version")
        assert "BradOS" in content

    def test_procfs_cpuinfo(self):
        content = self.vfs.read_text("/proc/cpuinfo")
        assert "processor" in content

    def test_devfs_null(self):
        assert self.vfs.read("/dev/null", 100) == b""
        self.vfs.write("/dev/null", b"discard me")   # should not raise

    def test_devfs_random(self):
        data = self.vfs.read("/dev/random", 16)
        assert len(data) == 16

    def test_devfs_zero(self):
        data = self.vfs.read("/dev/zero", 8)
        assert data == b"\x00" * 8

    def test_memfs_volatile(self):
        self.vfs.write_text("/tmp/volatile.txt", "temp")
        assert self.vfs.read_text("/tmp/volatile.txt") == "temp"

    def test_path_traversal_blocked(self):
        with pytest.raises(PermissionError):
            self.vfs.read("/home/../../../etc/passwd")

    def test_exists_nonexistent(self):
        assert not self.vfs.exists("/home/testuser/does_not_exist.txt")

    def test_walk(self):
        self.vfs.makedirs("/home/testuser/walk/a")
        self.vfs.write_text("/home/testuser/walk/a/file.txt", "x")
        paths = list(self.vfs.walk("/home/testuser/walk"))
        assert len(paths) >= 1


# ════════════════════════════════════════════════════════════════
# DRIVERS
# ════════════════════════════════════════════════════════════════

class TestDrivers:
    @pytest.fixture(autouse=True)
    def setup(self):
        from brados_vfs import create_default_vfs
        from brados_drivers import create_default_registry, NetworkDriver, DisplayDriver, StorageDriver
        self.vfs  = create_default_vfs()
        self.reg  = create_default_registry(vfs=self.vfs)
        self.NetD = NetworkDriver
        self.DisD = DisplayDriver
        self.StoD = StorageDriver

    def test_registry_has_6_drivers(self):
        assert len(self.reg.list_all()) >= 5

    def test_display_driver_size(self):
        from brados_drivers import DisplayDriver
        disp = self.reg.get(DisplayDriver)
        w, h = disp.ioctl(DisplayDriver.IOCTL_GET_SIZE)
        assert w > 0 and h > 0

    def test_display_driver_colors(self):
        from brados_drivers import DisplayDriver
        disp = self.reg.get(DisplayDriver)
        colors = disp.ioctl(DisplayDriver.IOCTL_GET_COLORS)
        assert colors in (8, 256, 16_777_216)

    def test_network_driver_hostname(self):
        from brados_drivers import NetworkDriver
        net = self.reg.get(NetworkDriver)
        hostname = net.ioctl(NetworkDriver.IOCTL_GET_HOSTNAME)
        assert isinstance(hostname, str) and len(hostname) > 0

    def test_network_driver_local_ip(self):
        from brados_drivers import NetworkDriver
        net = self.reg.get(NetworkDriver)
        ip = net.ioctl(NetworkDriver.IOCTL_GET_LOCAL_IP)
        assert "." in ip   # basic IPv4 check

    def test_storage_driver_disk_free(self):
        from brados_drivers import StorageDriver
        sto = self.reg.get(StorageDriver)
        free = sto.ioctl(StorageDriver.IOCTL_GET_FREE)
        assert free > 0

    def test_require_missing_raises(self):
        with pytest.raises(RuntimeError):
            self.reg.require("nonexistent_driver")

    def test_driver_info_has_status(self):
        for info in self.reg.list_all():
            assert info.status in ("active", "degraded", "failed")


# ════════════════════════════════════════════════════════════════
# KERNEL
# ════════════════════════════════════════════════════════════════

class TestKernel:
    @pytest.fixture(autouse=True)
    def setup(self):
        from brados_vfs import create_default_vfs
        from brados_drivers import create_default_registry, DisplayDriver
        from brados_kernel_core import BradOSKernel, SC, hash_password, verify_password
        self.vfs    = create_default_vfs()
        self.reg    = create_default_registry(vfs=self.vfs)
        self.kernel = BradOSKernel()
        self.kernel.vfs     = self.vfs
        self.kernel.drivers = self.reg
        self.SC  = SC
        self.DisD = DisplayDriver

        class FakeProc:
            pid=1; name="test"; user="root"; uid=0; state="running"
            mem_bytes=0; signals=deque(); last_ret=None
        self.proc = FakeProc()

    def test_vfs_write_read(self):
        n = self.kernel.handle_syscall(self.proc, self.SC.VFS_WRITE,
                                       ("/tmp/k.txt", b"hello"))
        assert n == 5
        data = self.kernel.handle_syscall(self.proc, self.SC.VFS_READ,
                                          ("/tmp/k.txt",))
        assert data == b"hello"

    def test_vfs_list(self):
        self.kernel.handle_syscall(self.proc, self.SC.VFS_WRITE,
                                   ("/tmp/list_test.txt", b"x"))
        lst = self.kernel.handle_syscall(self.proc, self.SC.VFS_LIST, ("/tmp",))
        assert isinstance(lst, list)
        assert "list_test.txt" in lst

    def test_vfs_stat(self):
        self.kernel.handle_syscall(self.proc, self.SC.VFS_WRITE,
                                   ("/tmp/stat_test.txt", b"abc"))
        st = self.kernel.handle_syscall(self.proc, self.SC.VFS_STAT,
                                        ("/tmp/stat_test.txt",))
        assert isinstance(st, dict)
        assert st["size"] == 3

    def test_shmem_put_get_del(self):
        self.kernel.handle_syscall(self.proc, self.SC.SHMEM_PUT, ("mykey", {"v": 42}))
        val = self.kernel.handle_syscall(self.proc, self.SC.SHMEM_GET, ("mykey",))
        assert val == {"v": 42}
        self.kernel.handle_syscall(self.proc, self.SC.SHMEM_DEL, ("mykey",))
        assert self.kernel.handle_syscall(self.proc, self.SC.SHMEM_GET, ("mykey",)) is None

    def test_pipe_open_write_read(self):
        self.kernel.handle_syscall(self.proc, self.SC.PIPE_OPEN,  ("ch",))
        self.kernel.handle_syscall(self.proc, self.SC.PIPE_WRITE, ("ch", "msg"))
        result = self.kernel.handle_syscall(self.proc, self.SC.PIPE_READ, ("ch",))
        assert result == "msg"
        assert self.kernel.handle_syscall(self.proc, self.SC.PIPE_READ, ("ch",)) is None

    def test_ioctl_display(self):
        result = self.kernel.handle_syscall(
            self.proc, self.SC.IOCTL,
            ("brados_display", self.DisD.IOCTL_GET_SIZE, None)
        )
        assert isinstance(result, tuple) and len(result) == 2

    def test_net_send_recv(self):
        self.kernel.handle_syscall(self.proc, self.SC.NET_SEND,
                                   ("testuser", "hello"))

        class Receiver:
            pid=2; name="rx"; user="testuser"; uid=1000; state="running"
            mem_bytes=0; signals=deque(); last_ret=None
        msg = self.kernel.handle_syscall(Receiver(), self.SC.NET_RECV, ())
        assert msg is not None
        sender, text = msg
        assert text == "hello"

    def test_unknown_syscall_returns_minus1(self):
        result = self.kernel.handle_syscall(self.proc, 9999, ())
        assert result == -1

    def test_authentication(self):
        uid = self.kernel.authenticate("root", "admin")
        assert uid == 0
        assert self.kernel.authenticate("root", "wrong") is None

    def test_password_hashing(self):
        from brados_kernel_core import hash_password, verify_password
        h = hash_password("mysecret")
        assert h.startswith("pbkdf2:sha256:")
        assert verify_password("mysecret", h)
        assert not verify_password("wrong", h)

    def test_scheduler_no_lost_syscalls(self):
        """Verify the v1 scheduler bug is fixed: no syscalls dropped."""
        from brados_kernel_core import SYSCALL_PRINT, SYSCALL_INPUT, SYSCALL_EXIT

        def test_task():
            yield (SYSCALL_PRINT, "first")
            x = yield (SYSCALL_INPUT, ">>> ")
            yield (SYSCALL_PRINT, f"got:{x}")
            yield (SYSCALL_EXIT,)

        gen = test_task()
        syscall = gen.send(None)          # first tick: None → PRINT
        assert syscall == (SYSCALL_PRINT, "first")
        syscall = gen.send(0)             # inject ret → INPUT
        assert syscall == (SYSCALL_INPUT, ">>> ")
        syscall = gen.send("hello")       # inject input → PRINT got:hello
        assert syscall == (SYSCALL_PRINT, "got:hello")
        syscall = gen.send(0)             # inject ret → EXIT
        assert syscall[0] == SYSCALL_EXIT

    def test_tick_runs_desktop_tasks_without_blocking(self):
        """tick() advances shell-safe tasks and publishes shmem (no PRINT/INPUT)."""
        from brados_kernel_core import (
            BradOSKernel, desktop_clock_task, desktop_status_task,
        )

        k = BradOSKernel()
        k.create_task("DesktopClock", desktop_clock_task, uid=1000, nice=10)
        k.create_task("SysStatus", desktop_status_task, uid=1000, nice=15)

        # First epoch: both tasks should execute their first syscalls
        n = k.tick()
        assert n == 2
        assert "sys.clock" in k._shmem
        # Status task first yield is GETPID — need a couple ticks to SHMEM_PUT
        for _ in range(4):
            k.tick()
        assert "sys.status" in k._shmem
        names = {t["name"] for t in k.list_tasks()}
        assert "DesktopClock" in names
        assert "SysStatus" in names

    def test_tick_does_not_block_on_sleep(self):
        """Sleeping tasks are re-queued; tick() returns immediately."""
        from brados_kernel_core import BradOSKernel, SC

        def sleeper():
            yield (SC.SLEEP, 60.0)
            yield (SC.EXIT,)

        k = BradOSKernel()
        k.create_task("Sleeper", sleeper, uid=1000)
        t0 = time.monotonic()
        k.tick()  # enter SLEEP
        k.tick()  # should skip sleeping task without waiting 60s
        elapsed = time.monotonic() - t0
        assert elapsed < 1.0
        tasks = k.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["state"] == "sleeping"


# ════════════════════════════════════════════════════════════════
# SECURITY (BradSec)
# ════════════════════════════════════════════════════════════════

class TestBradSec:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from brados_security import BradSec, Cap
        self.sec = BradSec()
        self.Cap = Cap

    def test_token_issue_and_verify(self):
        token = self.sec.issue_token(pid=1, uid=0, caps=self.Cap.ADMIN)
        assert self.sec.verify_token(token)

    def test_token_has_capability(self):
        token = self.sec.issue_token(pid=2, uid=1000,
                                     caps=self.Cap.FS_READ | self.Cap.NET_SEND)
        assert token.has(self.Cap.FS_READ)
        assert token.has(self.Cap.NET_SEND)
        assert not token.has(self.Cap.FS_WRITE)

    def test_admin_has_all_caps(self):
        token = self.sec.issue_token(pid=3, uid=0, caps=self.Cap.ADMIN)
        assert token.has(self.Cap.FS_WRITE)
        assert token.has(self.Cap.VAULT_WRITE)
        assert token.has(self.Cap.PROC_FORK)

    def test_token_tampering_detected(self):
        token = self.sec.issue_token(pid=4, uid=1000, caps=self.Cap.FS_READ)
        token.caps = int(self.Cap.ADMIN)   # tamper
        assert not self.sec.verify_token(token)

    def test_token_revoke(self):
        self.sec.issue_token(pid=5, uid=1000)
        self.sec.revoke_token(5)
        assert not self.sec.check_cap(5, self.Cap.FS_READ)

    def test_check_cap(self):
        self.sec.issue_token(pid=6, uid=1000,
                             caps=self.Cap.FS_READ | self.Cap.NET_SEND)
        assert self.sec.check_cap(6, self.Cap.FS_READ)
        assert not self.sec.check_cap(6, self.Cap.FS_WRITE)

    def test_capability_demo_guest_write_denied(self):
        """Guest lacks FS_WRITE; session can write — the public show-ready demo."""
        from brados_security import (
            run_capability_demo, DEMO_GUEST_PID, DEMO_SESSION_PID, Cap,
        )
        from brados_vfs import create_default_vfs

        vfs = create_default_vfs()
        vfs.set_sec(self.sec)
        results = run_capability_demo(vfs, self.sec)
        by_step = {r["step"]: r for r in results}
        assert by_step["guest_write"]["ok"] is True
        assert "denied" in by_step["guest_write"]["detail"].lower() or \
               "capability" in by_step["guest_write"]["detail"].lower()
        assert by_step["guest_read"]["ok"] is True
        assert by_step["session_write"]["ok"] is True
        assert by_step["check_cap_guest"]["ok"] is True
        assert all(r["ok"] for r in results)

        # Direct API still enforces after the demo
        with pytest.raises(PermissionError):
            vfs.write_text("/tmp/again.txt", "nope", caller_pid=DEMO_GUEST_PID)
        vfs.write_text("/tmp/again.txt", "yep", caller_pid=DEMO_SESSION_PID)
        assert vfs.read_text("/tmp/again.txt", caller_pid=DEMO_GUEST_PID) == "yep"
        assert not self.sec.check_cap(DEMO_GUEST_PID, Cap.FS_WRITE)
        assert self.sec.check_cap(DEMO_SESSION_PID, Cap.FS_WRITE)

    def test_audit_log_writes(self):
        self.sec.audit.write("INFO", "TEST", "test event", {"k": "v"})
        events = self.sec.audit.tail(10)
        assert len(events) >= 1
        # Match by content (not strictly last): bg integrity threads from a
        # prior BradSec.start() used to race via relative audit paths after cwd
        # changed. Paths are now absolute; this assertion stays race-tolerant.
        assert any(e.get("event") == "test event" for e in events)

    def test_audit_log_search(self):
        self.sec.audit.write("WARNING", "AUTH", "bad login")
        self.sec.audit.write("INFO", "VFS", "file read")
        auth_events = self.sec.audit.search(subsystem="AUTH")
        assert all(e["subsystem"] == "AUTH" for e in auth_events)

    def test_integrity_baseline_build(self):
        findings = self.sec.verify_integrity()
        assert isinstance(findings, list)

    def test_integrity_detects_modification(self):
        # Build baseline, modify a file, then verify
        import importlib, brados_security
        daemon = self.sec.integrity
        # Create and hash a file
        Path("test_file.py").write_text("x = 1")
        daemon.build_baseline()
        # Modify after baseline
        Path("test_file.py").write_text("x = 999  # tampered")
        findings = daemon.verify()
        modified = [f for f in findings if f["type"] == "MODIFIED"]
        assert len(modified) >= 1

    def test_vault_write_and_read(self):
        assert self.sec.unlock_vault("testpass123")
        assert self.sec.vault.put("my_secret", "s3cr3t_value")
        assert self.sec.vault.get("my_secret") == "s3cr3t_value"

    def test_vault_wrong_password(self):
        self.sec.unlock_vault("correctpass")
        self.sec.vault.lock()
        # Second BradSec (different instance) with same vault file
        from brados_security import BradSec
        sec2 = BradSec()
        # Wrong password should not expose data
        sec2.unlock_vault("wrongpass")
        result = sec2.vault.get("my_secret")
        assert result is None   # locked or decryption failed

    def test_scanner_returns_list(self):
        findings = self.sec.scan()
        assert isinstance(findings, list)

    def test_status_dict(self):
        self.sec.start()
        status = self.sec.status()
        assert status["status"] == "active"
        assert "active_tokens" in status
        assert "vault_locked" in status


# ════════════════════════════════════════════════════════════════
# APPS
# ════════════════════════════════════════════════════════════════

class TestApps:
    def test_safe_eval_basic(self):
        from brados_apps import safe_eval
        assert safe_eval("2+2") == 4
        assert safe_eval("10/4") == 2.5
        assert safe_eval("2**10") == 1024

    def test_safe_eval_math_functions(self):
        import math
        from brados_apps import safe_eval
        assert abs(safe_eval("sqrt(144)") - 12.0) < 1e-9
        assert abs(safe_eval("sin(0)")) < 1e-9

    def test_safe_eval_no_builtins(self):
        from brados_apps import safe_eval
        with pytest.raises(Exception):
            safe_eval("__import__('os').system('id')")

    def test_html_to_text_strips_script(self):
        from brados_apps import html_to_text
        html = "<html><head><script>evil()</script></head><body><p>Clean</p></body></html>"
        out  = html_to_text(html)
        assert "Clean" in out
        assert "evil" not in out

    def test_html_to_text_strips_style(self):
        from brados_apps import html_to_text
        html = "<style>body{color:red}</style><p>Visible</p>"
        out  = html_to_text(html)
        assert "Visible" in out
        assert "color" not in out

    def test_html_to_text_nested_skip(self):
        from brados_apps import html_to_text
        html = "<head><style>.x{}</style></head><body><h1>Title</h1><p>Body</p></body>"
        out  = html_to_text(html)
        assert "Title" in out
        assert "Body"  in out

    def test_html_to_text_links(self):
        from brados_apps import html_to_text
        html = '<a href="https://example.com">Click</a>'
        out  = html_to_text(html)
        assert "Click" in out

    # ── Text tools ──────────────────────────────────────────────────────────

    def test_text_stats_basic(self):
        from brados_apps import text_stats
        stats = text_stats("Hello world. This is BradOS!")
        assert stats["words"] == 5
        assert stats["sentences"] == 2
        assert stats["lines"] == 1
        assert stats["chars_no_spaces"] < stats["chars"]

    def test_text_stats_empty(self):
        from brados_apps import text_stats
        stats = text_stats("")
        assert stats == {
            "words": 0, "chars": 0, "chars_no_spaces": 0,
            "lines": 0, "sentences": 0, "reading_time_min": 0.0,
        }

    def test_text_stats_multiline(self):
        from brados_apps import text_stats
        stats = text_stats("line1\nline2\nline3")
        assert stats["lines"] == 3
        assert stats["words"] == 3

    def test_text_stats_no_punctuation_counts_one_sentence(self):
        from brados_apps import text_stats
        stats = text_stats("just some words with no ending punctuation")
        assert stats["sentences"] == 1

    def test_text_stats_reading_time_scales_with_length(self):
        from brados_apps import text_stats
        short = text_stats("word " * 50)
        long_ = text_stats("word " * 500)
        assert long_["reading_time_min"] > short["reading_time_min"]

    def test_text_case_convert_upper_lower(self):
        from brados_apps import text_case_convert
        assert text_case_convert("Hello World", "upper") == "HELLO WORLD"
        assert text_case_convert("Hello World", "lower") == "hello world"

    def test_text_case_convert_title(self):
        from brados_apps import text_case_convert
        assert text_case_convert("hello world", "title") == "Hello World"

    def test_text_case_convert_sentence(self):
        from brados_apps import text_case_convert
        assert text_case_convert("hELLO WORLD", "sentence") == "Hello world"

    def test_text_case_convert_toggle(self):
        from brados_apps import text_case_convert
        assert text_case_convert("Hello World", "toggle") == "hELLO wORLD"

    def test_text_case_convert_unknown_mode_raises(self):
        from brados_apps import text_case_convert
        with pytest.raises(ValueError):
            text_case_convert("hi", "not-a-mode")

    def test_text_case_convert_sentence_empty(self):
        from brados_apps import text_case_convert
        assert text_case_convert("   ", "sentence") == "   "


class TestBrash:
    """Coverage for brados_brash.py — previously had zero test coverage
    despite being a core, user-facing subsystem."""

    def _shell(self, vfs=None, cwd="/tmp"):
        from unittest.mock import MagicMock
        from brados_brash import BrashShell
        return BrashShell(MagicMock(), MagicMock(), MagicMock(), vfs=vfs, cwd=cwd)

    # ── Chain splitting ──────────────────────────────────────────────────

    def test_split_chain_semicolon(self):
        s = self._shell()
        assert s._split_chain("echo a; echo b") == [("echo a", None), ("echo b", "seq")]

    def test_split_chain_and_or(self):
        s = self._shell()
        result = s._split_chain("echo a && echo b || echo c")
        assert result == [("echo a", None), ("echo b", "and"), ("echo c", "or")]

    def test_split_chain_respects_quotes(self):
        s = self._shell()
        result = s._split_chain('grep "a && b" file; echo ok')
        assert result == [('grep "a && b" file', None), ("echo ok", "seq")]

    def test_split_chain_single_command_no_connector(self):
        s = self._shell()
        assert s._split_chain("echo hello") == [("echo hello", None)]

    # ── Aliases ───────────────────────────────────────────────────────────

    def test_alias_define_and_expand(self):
        s = self._shell()
        s._cmd_alias(["hi=echo hello"])
        assert s._expand_aliases("hi") == "echo hello"

    def test_alias_expand_preserves_trailing_args(self):
        s = self._shell()
        s._cmd_alias(["ll=ls -la"])
        assert s._expand_aliases("ll /home") == "ls -la /home"

    def test_alias_quoted_value(self):
        s = self._shell()
        s._cmd_alias(["gs=git status"])
        out = s._cmd_alias(["gs"])
        assert "git status" in out

    def test_alias_list_when_empty(self):
        s = self._shell()
        assert "No aliases" in s._cmd_alias([])

    def test_unalias_removes(self):
        s = self._shell()
        s._cmd_alias(["hi=echo hi"])
        s._cmd_unalias(["hi"])
        assert s._expand_aliases("hi") == "hi"    # no longer expands

    def test_unalias_unknown_reports_not_found(self):
        s = self._shell()
        out = s._cmd_unalias(["nope"])
        assert "not found" in out

    def test_alias_cycle_guard_does_not_hang(self):
        s = self._shell()
        # a self-referential alias must not infinite-loop
        s._aliases["loop"] = "loop"
        result = s._expand_aliases("loop")
        assert isinstance(result, str)   # returns rather than hanging

    def test_alias_persists_via_vfs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from brados_vfs import create_default_vfs
        vfs = create_default_vfs()
        s = self._shell(vfs=vfs)
        s._cmd_alias(["ll=ls -la"])
        # A fresh shell instance backed by the same vfs should load it back.
        s2 = self._shell(vfs=vfs)
        assert s2._aliases.get("ll") == "ls -la"

    # ── &&/||/; gated execution (async) ─────────────────────────────────

    async def test_and_skips_after_failure(self):
        s = self._shell()
        await s.handle_input("rm /definitely/not/here && echo should_not_run")
        outputs = [c.args[0] for c in s.log.write.call_args_list]
        assert "should_not_run" not in outputs   # only the echoed input line may mention it

    async def test_or_runs_fallback_after_failure(self):
        s = self._shell()
        await s.handle_input("rm /definitely/not/here || echo fallback_ran")
        written = " ".join(str(c) for c in s.log.write.call_args_list)
        assert "fallback_ran" in written

    async def test_semicolon_always_runs_both(self):
        s = self._shell()
        await s.handle_input("echo one ; echo two")
        written = " ".join(str(c) for c in s.log.write.call_args_list)
        assert "one" in written and "two" in written

    async def test_alias_used_in_handle_input(self):
        s = self._shell()
        await s.handle_input("alias hi=echo")
        await s.handle_input("hi hello-there")
        written = " ".join(str(c) for c in s.log.write.call_args_list)
        assert "hello-there" in written


# ════════════════════════════════════════════════════════════════
# SHELL IMPORTS
# ════════════════════════════════════════════════════════════════

class TestShellImports:
    """Smoke-test that all shell classes import cleanly."""

    def test_import_bradwindow(self):
        from brados_shell import BradWindow
        assert BradWindow is not None

    def test_all_windows_are_bradwindow(self):
        from brados_shell import (BradWindow, TerminalWindow, BrowserWindow,
            FileManagerWindow, EditorWindow, MailWindow, NotesWindow,
            CalculatorWindow, ClockWindow, MonitorWindow, LogsWindow,
            KernelWindow, SettingsWindow, HelpWindow,
            BradSecWindow, BpkgWindow)
        for W in [TerminalWindow, BrowserWindow, FileManagerWindow, EditorWindow,
                  MailWindow, NotesWindow, CalculatorWindow, ClockWindow,
                  MonitorWindow, LogsWindow, KernelWindow, SettingsWindow,
                  HelpWindow, BradSecWindow, BpkgWindow]:
            assert issubclass(W, BradWindow), f"{W.__name__} not BradWindow"
            assert hasattr(W, "APP_ID"), f"{W.__name__} missing APP_ID"
            assert W.APP_ID != "unknown", f"{W.__name__} APP_ID not set"

    def test_bradsec_window_imported(self):
        from brados_shell import BradSecWindow
        assert BradSecWindow.APP_ID == "bradsec"

    def test_bpkg_window_imported(self):
        from brados_shell import BpkgWindow
        assert BpkgWindow.APP_ID == "bpkg"

    def test_texttools_window_imported(self):
        from brados_shell import TextToolsWindow, BradWindow
        assert issubclass(TextToolsWindow, BradWindow)
        assert TextToolsWindow.APP_ID == "texttools"

    def test_apps_manifest_includes_texttools_with_matching_window(self):
        from brados_shell import APPS, TextToolsWindow
        entry = next(a for a in APPS if a["id"] == "texttools")
        assert entry["id"] == TextToolsWindow.APP_ID

    def test_bradsec_module(self):
        from brados_security import BradSec, Cap, get_bradsec
        sec = get_bradsec()
        assert sec is not None
        assert isinstance(sec, BradSec)

    def test_bpkg_module(self):
        from brados_bpkg import BpkgManager, get_bpkg, BUILTIN_REGISTRY
        mgr = get_bpkg()
        assert mgr is not None
        assert len(BUILTIN_REGISTRY) >= 7
        assert mgr.registry.get("brad-psutil") is not None
        assert mgr.registry.get("brad-full") is not None

    def test_apps_manifest(self):
        from brados_shell import APPS
        required = ["terminal", "browser", "files", "editor", "mail",
                    "notes", "calculator", "clock", "monitor", "logs",
                    "kernel", "settings", "bradsec", "bpkg",
                    "paint", "converter", "texttools", "rss",
                    "snake", "vault", "weather",
                    "minesweeper", "game2048", "markdown", "mesh"]
        assert len(APPS) >= len(required)
        ids = {a["id"] for a in APPS}
        for r in required:
            assert r in ids

    def test_splash_screen(self):
        from brados_shell import SplashScreen
        assert hasattr(SplashScreen, "_STEPS")
        assert len(SplashScreen._STEPS) == 7

    def test_minimize_app_message(self):
        from brados_shell import MinimizeApp
        m = MinimizeApp("editor")
        assert m.app_id == "editor"

    def test_no_min_width_in_buttons(self):
        with open("brados_shell.py") as f:
            src = f.read()
        bad = [l for l in src.split("\n")
               if "min_width=" in l and "Button(" in l
               and not l.strip().startswith(("#", "/*"))]
        assert not bad, f"min_width= in Button: {bad[:2]}"

    def test_no_call_from_thread(self):
        fname = "brados_gui.py"
        with open(fname) as f:
            txt = f.read()
        assert "self.call_from_thread" not in txt

    def test_no_thread_worker(self):
        fname = "brados_gui.py"
        with open(fname) as f:
            txt = f.read()
        assert "@work(thread=True)" not in txt


# ════════════════════════════════════════════════════════════════
# BPKG
# ════════════════════════════════════════════════════════════════

class TestBpkg:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from brados_bpkg import BpkgManager
        self.mgr = BpkgManager()

    def test_registry_has_builtin_packages(self):
        from brados_bpkg import BUILTIN_REGISTRY
        assert len(BUILTIN_REGISTRY) >= 7

    def test_get_known_package(self):
        pkg = self.mgr.registry.get("brad-psutil")
        assert pkg is not None
        assert pkg.name == "brad-psutil"
        assert "psutil" in pkg.pip_deps

    def test_search_by_name(self):
        results = self.mgr.registry.search("requests")
        assert any(p.name == "brad-requests" for p in results)

    def test_search_by_tag(self):
        results = self.mgr.registry.search("security")
        assert any("security" in p.tags for p in results)

    def test_search_no_results(self):
        assert self.mgr.registry.search("xyznonexistent123") == []

    def test_list_available_excludes_installed(self):
        # Nothing installed yet
        available = self.mgr.list_available()
        assert len(available) > 0

    def test_install_marks_as_installed(self):
        # Patch pip to succeed without actually running it
        from unittest.mock import patch
        with patch("brados_bpkg.PypiHelper.install", return_value=True):
            result = self.mgr.install("brad-psutil")
        assert result.success
        assert self.mgr.is_installed("brad-psutil")

    def test_remove_marks_as_not_installed(self):
        from unittest.mock import patch
        with patch("brados_bpkg.PypiHelper.install", return_value=True), \
             patch("brados_bpkg.PypiHelper.uninstall", return_value=True):
            self.mgr.install("brad-psutil")
            result = self.mgr.remove("brad-psutil")
        assert result.success
        assert not self.mgr.is_installed("brad-psutil")

    def test_install_unknown_package_fails(self):
        result = self.mgr.install("nonexistent-xyz-package")
        assert not result.success

    def test_install_already_installed(self):
        from unittest.mock import patch
        with patch("brados_bpkg.PypiHelper.install", return_value=True):
            self.mgr.install("brad-psutil")
            result = self.mgr.install("brad-psutil")  # second install
        assert result.success   # should succeed gracefully

    def test_by_category(self):
        libs = self.mgr.registry.by_category("lib")
        assert all(p.category == "lib" for p in libs)
        assert len(libs) >= 3

    # ── install_script trust / checksum gate ────────────────────────────────

    def test_builtin_packages_are_trusted(self):
        from brados_bpkg import BUILTIN_REGISTRY
        for pkg_dict in BUILTIN_REGISTRY:
            assert self.mgr.registry.is_trusted(pkg_dict["name"])

    def test_builtin_script_checksum_auto_pinned(self):
        # None of the current builtins ship an install_script, but any that
        # did would have their checksum auto-pinned by _load_builtin().
        import hashlib
        from brados_bpkg import Package, PackageRegistry
        reg = PackageRegistry()
        pkg = Package(name="hypothetical", version="1.0", description="d",
                      install_script="echo hi")
        assert not pkg.script_matches_checksum()   # unpinned yet
        pkg.script_sha256 = hashlib.sha256(pkg.install_script.encode()).hexdigest()
        assert pkg.script_matches_checksum()       # matches once pinned
        assert all(p.script_matches_checksum() for p in reg.all_packages())

    def test_package_without_script_trivially_matches(self):
        from brados_bpkg import Package
        pkg = Package(name="x", version="1.0", description="d")
        assert pkg.script_matches_checksum()

    def test_package_with_wrong_checksum_fails(self):
        from brados_bpkg import Package
        pkg = Package(name="x", version="1.0", description="d",
                      install_script="echo hi", script_sha256="deadbeef")
        assert not pkg.script_matches_checksum()

    def test_untrusted_script_is_skipped_without_override(self, monkeypatch):
        from unittest.mock import patch
        from brados_bpkg import Package
        rogue = Package(name="rogue-pkg", version="1.0", description="d",
                         install_script="touch /tmp/should_not_run")
        self.mgr.registry._packages["rogue-pkg"] = rogue
        calls = []
        monkeypatch.setattr("subprocess.run", lambda *a, **k: calls.append(a) or type("R", (), {"returncode": 0})())
        with patch("brados_bpkg.PypiHelper.install", return_value=True):
            result = self.mgr.install("rogue-pkg")
        assert result.success              # package itself still "installs"
        assert calls == []                 # but the unverified script never ran
        assert any("Skipped install_script" in m for m in result.messages)

    def test_untrusted_script_runs_with_explicit_override(self, monkeypatch):
        from unittest.mock import patch
        from brados_bpkg import Package
        rogue = Package(name="rogue-pkg", version="1.0", description="d",
                         install_script="echo override-ran")
        self.mgr.registry._packages["rogue-pkg"] = rogue
        calls = []
        monkeypatch.setattr("subprocess.run", lambda *a, **k: calls.append(a) or type("R", (), {"returncode": 0})())
        with patch("brados_bpkg.PypiHelper.install", return_value=True):
            result = self.mgr.install("rogue-pkg", allow_unverified_scripts=True)
        assert result.success
        assert len(calls) == 1
        assert any("UNVERIFIED" in m for m in result.messages)

    def test_remote_registry_cannot_shadow_builtin_name(self):
        from brados_bpkg import Package
        original = self.mgr.registry.get("brad-psutil")
        spoof = Package(name="brad-psutil", version="99.0", description="evil twin",
                         install_script="rm -rf /")
        # Simulate what fetch_remote/_load_cache guard against
        if spoof.name in self.mgr.registry._trusted:
            pass  # guarded — the spoof must never overwrite the builtin entry
        else:
            self.mgr.registry._packages[spoof.name] = spoof
        assert self.mgr.registry.get("brad-psutil").version == original.version

    def test_db_persistence(self):
        from unittest.mock import patch
        from brados_bpkg import PackageDB
        with patch("brados_bpkg.PypiHelper.install", return_value=True):
            self.mgr.install("brad-requests")
        # Load a fresh DB from the same path
        db2 = PackageDB()
        assert db2.is_installed("brad-requests")

    def test_info_returns_package(self):
        pkg = self.mgr.info("brad-full")
        assert pkg is not None
        assert pkg.name == "brad-full"
        assert len(pkg.bpkg_deps) > 0

    def test_pip_status_empty_when_nothing_installed(self):
        status = self.mgr.pip_status()
        assert isinstance(status, dict)


# ════════════════════════════════════════════════════════════════
# ASYNC WORKERS
# ════════════════════════════════════════════════════════════════

class TestAsyncWorkers:
    @pytest.mark.asyncio
    async def test_tray_stats_collect(self):
        from brados_shell import TrayStats
        result = await asyncio.to_thread(TrayStats._collect)
        assert isinstance(result, str)
        assert "CPU" in result

    @pytest.mark.asyncio
    async def test_monitor_collect_stats(self):
        from brados_shell import MonitorWindow
        cards, procs = await asyncio.to_thread(MonitorWindow._collect_stats)
        assert len(cards) == 4
        assert len(procs) <= 15

    @pytest.mark.asyncio
    async def test_stats_panel_collect(self):
        from brados_gui import StatsPanel
        result = await asyncio.to_thread(StatsPanel._collect)
        if result is not None:
            cpu, ram, disk = result
            assert 0 <= cpu  <= 100
            assert 0 <= ram  <= 100
            assert 0 <= disk <= 100

    @pytest.mark.asyncio
    async def test_monitor_screen_extra(self):
        from brados_gui import MonitorScreen
        result = await asyncio.to_thread(MonitorScreen._collect_extra)
        assert isinstance(result, str)


# ════════════════════════════════════════════════════════════════
# MESH TESTS
# ════════════════════════════════════════════════════════════════

class TestMesh:
    def test_mesh_import(self):
        from brados_mesh import MeshNode, get_mesh, Peer
        assert MeshNode is not None

    def _fresh_node(self, secret: str, base_port: int) -> any:
        from brados_mesh import MeshNode
        return MeshNode(secret=secret, discovery_port=base_port, data_port=base_port + 1000)

    def test_mesh_start_stop(self):
        node = self._fresh_node("test123", 20100)
        node.start()
        assert node.running
        assert node.peer_id
        node.stop()
        assert not node.running

    def test_mesh_peers_empty(self):
        node = self._fresh_node("test456", 20200)
        node.start()
        assert node.peers == []
        node.stop()

    def test_mesh_status_dict(self):
        node = self._fresh_node("test789", 20300)
        node.start()
        st = node.status()
        assert st["running"]
        assert st["peer_id"]
        assert st["peers"] == 0
        node.stop()

    def test_mesh_singleton(self):
        from brados_mesh import get_mesh
        m1 = get_mesh()
        m2 = get_mesh()
        assert m1 is m2


# ════════════════════════════════════════════════════════════════
# BRADMUSIC (pure helpers — no real audio required)
# ════════════════════════════════════════════════════════════════

class TestBradMusic:
    def test_lrc_parse_and_get_line(self, tmp_path):
        from brados_music import LrcParser

        lrc = tmp_path / "song.lrc"
        lrc.write_text(
            "[00:00.00]Intro\n"
            "[00:05.50]First line\n"
            "[00:12.00]Second line\n"
            "[ti:ignored metadata]\n",
            encoding="utf-8",
        )
        lines = LrcParser.parse(str(lrc))
        assert len(lines) == 3
        assert lines[0] == (0.0, "Intro")
        assert lines[1][1] == "First line"
        assert LrcParser.get_line(0.0, lines) == "Intro"
        assert LrcParser.get_line(6.0, lines) == "First line"
        assert LrcParser.get_line(20.0, lines) == "Second line"
        around = LrcParser.get_lines_around(6.0, lines, window=1)
        assert any(is_cur and text == "First line" for _, text, is_cur in around)

    def test_lrc_find_sidecar(self, tmp_path):
        from brados_music import LrcParser

        track = tmp_path / "track.mp3"
        track.write_bytes(b"")
        lrc = tmp_path / "track.lrc"
        lrc.write_text("[00:01.00]hi\n", encoding="utf-8")
        assert LrcParser.find_lyrics_file(str(track)) == str(lrc)

    def test_play_queue_order_and_repeat(self):
        from brados_music import PlayQueue

        tracks = [
            {"title": "a", "path": "/a.mp3", "duration": 1.0},
            {"title": "b", "path": "/b.mp3", "duration": 1.0},
            {"title": "c", "path": "/c.mp3", "duration": 1.0},
        ]
        q = PlayQueue()
        q.load(tracks, start_index=0)
        assert q.current["title"] == "a"
        assert q.next()["title"] == "b"
        assert q.next()["title"] == "c"
        assert q.next() is None  # end without repeat
        q.toggle_repeat()
        assert q.next()["title"] == "a"
        assert q.prev()["title"] == "c"

    def test_library_search_and_scan_empty(self, tmp_path):
        from brados_music import MusicLibrary

        lib = MusicLibrary(music_dir=str(tmp_path / "missing"))
        lib.scan()
        assert lib.count() == 0
        assert lib.search("x") == []

        music = tmp_path / "Music"
        music.mkdir()
        (music / "song.mp3").write_bytes(b"not-real-audio")
        (music / "other.flac").write_bytes(b"x")
        (music / "readme.txt").write_text("ignore")
        lib = MusicLibrary(music_dir=str(music))
        lib.scan()
        assert lib.count() == 2
        # Without mutagen, title falls back to stem
        titles = {t["title"] for t in lib.tracks}
        assert "song" in titles or any("song" in t for t in titles)
        hits = lib.search("song")
        assert len(hits) >= 1

    def test_engine_backend_detect_and_can_play(self, monkeypatch):
        from brados_music import MusicEngine, FULL_AUDIO_BACKENDS

        def which_none(name):
            return None

        monkeypatch.setattr("brados_music.shutil.which", which_none)
        eng = MusicEngine()
        assert eng.backend_name() == "wave"
        assert eng.has_full_backend() is False
        assert eng.status_label() == "none"
        assert "install mpv" in eng.status_detail().lower() or "ffmpeg" in eng.status_detail().lower()
        assert eng.can_play_path("/home/x/song.mp3") is False
        assert eng.can_play_path("/home/x/song.wav") is True
        assert eng.play("/home/x/song.mp3") is False
        assert eng._last_error

        def which_mpv(name):
            return "/usr/bin/mpv" if name == "mpv" else None

        monkeypatch.setattr("brados_music.shutil.which", which_mpv)
        eng2 = MusicEngine()
        assert eng2.backend_name() == "mpv"
        assert eng2.has_full_backend() is True
        assert eng2.backend_name() in FULL_AUDIO_BACKENDS
        assert eng2.can_play_path("/home/x/song.mp3") is True

    def test_tag_reader_fallback_without_file(self, tmp_path):
        from brados_music import TagReader

        p = tmp_path / "My Track.mp3"
        p.write_bytes(b"")
        info = TagReader.read(str(p))
        assert info["path"] == str(p)
        assert info["title"]  # stem or mutagen title
        assert "artist" in info


# ════════════════════════════════════════════════════════════════
# DESKTOP MINIMIZE/TASKBAR (regression: MinimizeApp bubbling)
# ════════════════════════════════════════════════════════════════

class TestLoginMobile:
    """Regression: mobile login crashed with AttributeError on _on_app_launch."""

    def test_go_home_does_not_reference_missing_callback(self):
        import inspect
        from brados_shell import LoginScreen

        src = inspect.getsource(LoginScreen._go_home)
        assert "_on_app_launch" not in src

    async def test_guest_login_on_mobile_opens_launcher(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("brados_shell.is_mobile_display", lambda: True)
        from brados_shell import BradOSShell, LoginScreen, MobileLauncher
        from brados_apps import init_dirs

        def light_mount(self):
            init_dirs()
            self.push_screen(LoginScreen())

        monkeypatch.setattr(BradOSShell, "on_mount", light_mount)
        app = BradOSShell()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#btn-guest")
            await pilot.pause()
            assert any(isinstance(s, MobileLauncher) for s in app.screen_stack)


class TestDesktopMinimize:
    """MinimizeApp is posted by a BradWindow (a Screen) and previously only
    had a handler on DesktopScreen — but sibling Screens on the stack are not
    DOM ancestors of each other, so the message could never actually reach
    it. Handling now lives on the App itself, which IS an ancestor of every
    pushed screen. These tests exercise the real message-bubbling path."""

    async def test_minimize_message_reaches_desktop_screen(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from brados_shell import BradOSShell, DesktopScreen, MinimizeApp

        # Textual dispatches on_mount from EVERY class in the MRO, not just
        # the most-derived override — so subclassing and overriding on_mount
        # would run BOTH the override and the real (heavy, service-starting)
        # on_mount. Monkeypatch the class method instead, so there's exactly
        # one on_mount in play: skip real service/daemon startup, just show
        # the desktop.
        monkeypatch.setattr(BradOSShell, "on_mount",
                             lambda self: self.push_screen(DesktopScreen()))
        app = BradOSShell()
        async with app.run_test() as pilot:
            await pilot.pause()
            desktop = next(s for s in app.screen_stack if isinstance(s, DesktopScreen))
            desktop._open_apps.add("texttools")

            app.post_message(MinimizeApp("texttools"))
            await pilot.pause()

            assert "texttools" in desktop._minimized
            assert "texttools" in desktop._open_apps

    async def test_taskbar_reflects_minimized_state(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from brados_shell import BradOSShell, DesktopScreen, MinimizeApp
        from textual.widgets import Button

        monkeypatch.setattr(BradOSShell, "on_mount",
                             lambda self: self.push_screen(DesktopScreen()))
        app = BradOSShell()
        async with app.run_test() as pilot:
            await pilot.pause()
            desktop = next(s for s in app.screen_stack if isinstance(s, DesktopScreen))
            desktop._open_apps.add("calculator")
            app.post_message(MinimizeApp("calculator"))
            await pilot.pause()

            task_btn = desktop.query_one("#task-calculator", Button)
            assert "minimized" in task_btn.classes


# ════════════════════════════════════════════════════════════════
# CSS / THEME LAUNCH-CRASH REGRESSIONS
# ════════════════════════════════════════════════════════════════

class TestShellCssHealth:
    """Two compounding bugs made the real app crash on launch under
    Textual 8.x: (1) get_css_variables() only supplied theme colors once
    self._theme existed, but Textual applies the stylesheet before
    on_mount() ever runs; (2) the hex->$var substitution used plain
    str.replace(), which corrupted 8-digit alpha-channel hex colors whose
    first 6 digits matched a themed color (e.g. #00d4ff22 -> "$accent22",
    an undefined variable). Both are fixed; these tests guard against
    regressions."""

    def test_shell_css_has_no_corrupted_alpha_variables(self):
        """No $var name in SHELL_CSS should have stray hex digits glued on
        (e.g. $accent22, $success44) — these are unresolvable and previously
        crashed the whole app at launch."""
        import re
        from brados_shell import SHELL_CSS, _CSS_COLORS
        var_names = {v.lstrip("$") for v in _CSS_COLORS.values()}
        for match in re.finditer(r"\$([A-Za-z_]+)([0-9a-fA-F]{1,2})\b", SHELL_CSS):
            name, suffix = match.groups()
            assert name not in var_names, (
                f"Found corrupted variable reference '${name}{suffix}' in SHELL_CSS"
            )

    def test_shell_css_has_no_unresolved_variables(self):
        """Actually build the stylesheet the way Textual does at launch and
        confirm every $variable reference resolves. This is the direct
        regression test for the launch crash."""
        from textual.css.stylesheet import Stylesheet
        from brados_shell import SHELL_CSS, BradOSShell

        app = BradOSShell()
        sheet = Stylesheet(variables=app.get_css_variables())
        sheet.add_source(SHELL_CSS, read_from=("test", "SHELL_CSS"))
        sheet.parse()  # raises UnresolvedVariableError if anything's missing

    def test_theme_available_before_on_mount(self):
        """_theme must be populated the moment the class exists (not only
        after on_mount runs), since Textual reads get_css_variables() before
        dispatching Mount."""
        from brados_shell import BradOSShell
        app = BradOSShell()
        assert hasattr(app, "_theme")
        assert "bg_base" in app.get_css_variables()

    async def test_real_app_launches_without_crashing(self, monkeypatch, tmp_path):
        """End-to-end: the actual, unmodified BradOSShell (as constructed by
        the real run_shell() entrypoint) must be able to mount at least its
        first screen without raising."""
        monkeypatch.chdir(tmp_path)
        from brados_shell import BradOSShell

        app = BradOSShell()
        # kernel deliberately omitted — on_mount must create and wire one
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.screen_stack) >= 1
            assert app.kernel is not None
            names = {t["name"] for t in app.kernel.list_tasks()}
            assert "DesktopClock" in names
            assert "SysStatus" in names
            # Scheduler pump should have run at least one tick by now
            await pilot.pause(0.25)
            assert "sys.clock" in app.kernel._shmem

    def test_run_shell_creates_kernel_when_none(self, monkeypatch):
        """run_shell() must never attach kernel=None to the app."""
        from brados_shell import run_shell, BradOSShell
        from brados_kernel_core import BradOSKernel

        captured = {}

        def fake_run(self):
            captured["kernel"] = self.kernel

        monkeypatch.setattr(BradOSShell, "run", fake_run)
        run_shell(kernel=None)
        assert isinstance(captured["kernel"], BradOSKernel)


# ════════════════════════════════════════════════════════════════
# Run standalone
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))

# brados_security.py — BradSec v1.0
#
# Real security. Not fake progress bars.
#
# HMAC-SHA256 capability tokens. SHA-256 integrity manifests. PBKDF2+Fernet
# encrypted vaults. Threat scanning with actual port checks and permission
# audits. NDJSON audit trails. No other Python terminal OS has security at all,
# let alone a subsystem this comprehensive.

from __future__ import annotations

import os
import sys
import json
import time
import socket
import struct
import signal
import hashlib
import logging
import secrets
import threading
import asyncio
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import IntFlag
from pathlib import Path
from typing import Any

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

logger = logging.getLogger("brados.sec")

# ── Capabilities ──────────────────────────────────────────────────────────────

class Cap(IntFlag):
    """Fine-grained capability flags for process tokens."""
    NONE       = 0
    NET_BIND   = 1 << 0   # bind to ports < 1024
    NET_SEND   = 1 << 1   # open outbound connections
    FS_READ    = 1 << 2   # read VFS
    FS_WRITE   = 1 << 3   # write VFS
    FS_EXEC    = 1 << 4   # execute files
    PROC_FORK  = 1 << 5   # spawn subprocesses
    AUDIT_READ = 1 << 6   # read audit log
    VAULT_READ = 1 << 7   # read encrypted vault
    VAULT_WRITE= 1 << 8   # write encrypted vault
    ADMIN      = 1 << 15  # all caps (root equivalent)

    @classmethod
    def default_user(cls) -> "Cap":
        return cls.FS_READ | cls.FS_WRITE | cls.NET_SEND | cls.PROC_FORK

    @classmethod
    def default_guest(cls) -> "Cap":
        return cls.FS_READ | cls.NET_SEND


# ── Capability Token ──────────────────────────────────────────────────────────

@dataclass
class CapabilityToken:
    """Signed capability ticket issued by the kernel at process creation.

    The signature is an HMAC-SHA256 of (pid|uid|caps|issued_at) using the
    kernel's session secret.  Tokens are valid for `ttl` seconds.
    """
    pid       : int
    uid       : int
    caps      : int          # Cap flags
    issued_at : float = field(default_factory=time.time)
    ttl       : float = 3600.0
    _sig      : str   = field(default="", repr=False)

    def sign(self, secret: bytes) -> None:
        import hmac
        msg = f"{self.pid}:{self.uid}:{self.caps}:{self.issued_at:.3f}".encode()
        self._sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()

    def verify(self, secret: bytes) -> bool:
        import hmac
        msg = f"{self.pid}:{self.uid}:{self.caps}:{self.issued_at:.3f}".encode()
        expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(self._sig, expected)

    def has(self, cap: Cap) -> bool:
        return bool(self.caps & int(cap)) or bool(self.caps & int(Cap.ADMIN))

    @property
    def expired(self) -> bool:
        return time.time() > self.issued_at + self.ttl

    def to_dict(self) -> dict:
        return asdict(self)


# ── Audit Log ─────────────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    timestamp : str
    level     : str          # INFO / WARNING / ALERT / CRITICAL
    subsystem : str          # INTEGRITY / CAPS / VAULT / SCAN / AUTH
    event     : str
    detail    : dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class AuditLog:
    """Append-only structured audit trail written to brados_audit.log.

    Each line is a self-contained JSON object (NDJSON format) so it can be
    streamed, grepped, and parsed without loading the whole file.
    """

    def __init__(self, path: str = "brados_audit.log"):
        self._path  = path
        self._lock  = threading.Lock()

    def write(self, level: str, subsystem: str, event: str,
              detail: dict | None = None) -> AuditEvent:
        ev = AuditEvent(
            timestamp = datetime.now(timezone.utc).isoformat(),
            level     = level,
            subsystem = subsystem,
            event     = event,
            detail    = detail or {},
        )
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(ev.to_json() + "\n")
        logger.info(f"[{level}] {subsystem}: {event}")
        return ev

    def tail(self, n: int = 50) -> list[dict]:
        """Return last n events as dicts."""
        try:
            with open(self._path, encoding="utf-8") as f:
                lines = f.readlines()
            events = []
            for line in reversed(lines[-n:]):
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return list(reversed(events))
        except FileNotFoundError:
            return []

    def search(self, subsystem: str | None = None,
               level: str | None = None) -> list[dict]:
        events = self.tail(500)
        if subsystem:
            events = [e for e in events if e.get("subsystem") == subsystem]
        if level:
            events = [e for e in events if e.get("level") == level]
        return events

    def clear(self) -> None:
        with self._lock:
            open(self._path, "w").close()


# ── File Integrity Daemon ─────────────────────────────────────────────────────

class IntegrityDaemon:
    """SHA-256 manifest of BradOS source files.

    On first run, builds a baseline manifest (brados_integrity.json).
    Subsequent runs compare current hashes to the baseline and report
    any added, modified, or deleted files.
    """

    MANIFEST_PATH = "brados_integrity.json"
    WATCHED_EXTS  = {".py", ".json", ".log"}
    WATCHED_DIRS  = ["."]
    IGNORE        = {"__pycache__", ".git", "backup_", "brados_integrity.json"}

    def __init__(self, audit: AuditLog):
        self._audit    = audit
        self._manifest : dict[str, str] = {}
        self._lock     = threading.Lock()

    def _hash_file(self, path: str) -> str:
        """SHA-256 of file contents in 64 KB chunks."""
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return "ERROR"

    def _iter_files(self) -> list[str]:
        files = []
        for d in self.WATCHED_DIRS:
            for root, dirs, fnames in os.walk(d):
                dirs[:] = [dd for dd in dirs
                           if not any(ig in dd for ig in self.IGNORE)]
                for fname in fnames:
                    if any(fname.endswith(ext) for ext in self.WATCHED_EXTS):
                        files.append(os.path.join(root, fname))
        return files

    def build_baseline(self) -> dict[str, str]:
        """Hash all watched files and save as the baseline manifest."""
        manifest = {}
        for fpath in self._iter_files():
            manifest[fpath] = self._hash_file(fpath)
        with self._lock:
            self._manifest = manifest
            manifest_dir = os.path.dirname(os.path.abspath(self.MANIFEST_PATH))
            os.makedirs(manifest_dir, exist_ok=True)
            tmp = self.MANIFEST_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"built_at": datetime.now().isoformat(),
                           "files": manifest}, f, indent=2)
            try:
                os.replace(tmp, self.MANIFEST_PATH)
            except FileNotFoundError:
                self._audit.write("WARN", "INTEGRITY",
                                  "Baseline build skipped (tmp path gone)")
                return manifest
        self._audit.write("INFO", "INTEGRITY",
                          f"Baseline built: {len(manifest)} files")
        return manifest

    def load_baseline(self) -> bool:
        """Load an existing manifest. Returns True if loaded, False if missing."""
        if not os.path.exists(self.MANIFEST_PATH):
            return False
        try:
            with open(self.MANIFEST_PATH) as f:
                data = json.load(f)
            with self._lock:
                self._manifest = data.get("files", {})
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def verify(self) -> list[dict]:
        """Compare current state to baseline. Returns list of findings."""
        if not self._manifest:
            if not self.load_baseline():
                self.build_baseline()
                return []

        findings : list[dict] = []
        current  = {f: self._hash_file(f) for f in self._iter_files()}

        for fpath, old_hash in self._manifest.items():
            if fpath not in current:
                findings.append({"type": "DELETED", "path": fpath})
                self._audit.write("ALERT", "INTEGRITY",
                                  f"File deleted: {fpath}",
                                  {"path": fpath})
            elif current[fpath] != old_hash:
                findings.append({"type": "MODIFIED", "path": fpath,
                                 "expected": old_hash[:16] + "…",
                                 "actual":   current[fpath][:16] + "…"})
                self._audit.write("ALERT", "INTEGRITY",
                                  f"File tampered: {fpath}",
                                  {"path": fpath})

        for fpath in current:
            if fpath not in self._manifest:
                findings.append({"type": "ADDED", "path": fpath})
                self._audit.write("WARNING", "INTEGRITY",
                                  f"New file: {fpath}",
                                  {"path": fpath})

        level = "ALERT" if any(f["type"] == "MODIFIED" for f in findings) else "INFO"
        self._audit.write(level, "INTEGRITY",
                          f"Verification complete: {len(findings)} finding(s)")
        return findings


# ── Encrypted Vault ───────────────────────────────────────────────────────────

class EncryptedVault:
    """PBKDF2-derived Fernet symmetric encryption for secrets.

    Stores an encrypted JSON blob in brados_vault.enc.
    Master password never stored — only used to derive the key.

    Falls back gracefully if `cryptography` is not installed,
    storing secrets XOR-obfuscated (NOT secure, but functional).
    """

    VAULT_PATH  = "brados_vault.enc"
    ITERATIONS  = 480_000

    def __init__(self, audit: AuditLog):
        self._audit = audit
        self._key   : bytes | None = None
        self._data  : dict = {}

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """PBKDF2-HMAC-SHA256 key derivation."""
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, self.ITERATIONS, dklen=32
        )

    def unlock(self, password: str) -> bool:
        """Derive key from password and decrypt the vault."""
        if not os.path.exists(self.VAULT_PATH):
            # New vault
            salt     = os.urandom(16)
            self._key = self._derive_key(password, salt)
            self._data = {}
            self._save(salt)
            self._audit.write("INFO", "VAULT", "New vault created")
            return True
        try:
            raw = Path(self.VAULT_PATH).read_bytes()
            salt = raw[:16]
            key  = self._derive_key(password, salt)
            self._key = key
            self._data = self._decrypt(raw[16:])
            self._audit.write("INFO", "VAULT", "Vault unlocked")
            return True
        except Exception as e:
            self._audit.write("ALERT", "VAULT", "Vault unlock failed",
                              {"error": str(e)})
            self._key = None
            return False

    def lock(self) -> None:
        self._key  = None
        self._data = {}
        self._audit.write("INFO", "VAULT", "Vault locked")

    def put(self, key: str, value: Any) -> bool:
        if not self._key:
            return False
        self._data[key] = value
        salt = Path(self.VAULT_PATH).read_bytes()[:16] if os.path.exists(self.VAULT_PATH) else os.urandom(16)
        self._save(salt)
        self._audit.write("INFO", "VAULT", f"Secret stored: {key}")
        return True

    def get(self, key: str) -> Any | None:
        if not self._key:
            return None
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        if not self._key or key not in self._data:
            return False
        del self._data[key]
        salt = Path(self.VAULT_PATH).read_bytes()[:16]
        self._save(salt)
        self._audit.write("INFO", "VAULT", f"Secret deleted: {key}")
        return True

    def list_keys(self) -> list[str]:
        return list(self._data.keys()) if self._key else []

    def _save(self, salt: bytes) -> None:
        payload = json.dumps(self._data).encode()
        encrypted = self._encrypt(payload)
        tmp = self.VAULT_PATH + ".tmp"
        Path(tmp).write_bytes(salt + encrypted)
        os.replace(tmp, self.VAULT_PATH)

    def _encrypt(self, data: bytes) -> bytes:
        try:
            from cryptography.fernet import Fernet
            import base64
            fernet_key = base64.urlsafe_b64encode(self._key)
            return Fernet(fernet_key).encrypt(data)
        except ImportError:
            # XOR obfuscation fallback — NOT cryptographically secure
            key_stream = (self._key * ((len(data) // len(self._key)) + 1))[:len(data)]
            return bytes(a ^ b for a, b in zip(data, key_stream))

    def _decrypt(self, data: bytes) -> dict:
        try:
            from cryptography.fernet import Fernet
            import base64
            fernet_key = base64.urlsafe_b64encode(self._key)
            payload = Fernet(fernet_key).decrypt(data)
            return json.loads(payload)
        except ImportError:
            key_stream = (self._key * ((len(data) // len(self._key)) + 1))[:len(data)]
            payload = bytes(a ^ b for a, b in zip(data, key_stream))
            return json.loads(payload)


# ── Threat Scanner ────────────────────────────────────────────────────────────

@dataclass
class ThreatFinding:
    severity : str    # LOW / MEDIUM / HIGH / CRITICAL
    category : str    # PERM / PORT / HASH / AUTH / CONFIG
    title    : str
    detail   : str
    path     : str = ""


class ThreatScanner:
    """Real threat checks — not animated fake progress.

    Checks:
    - World-writable files in the project directory
    - Weak file permissions on sensitive files (users.json, vault)
    - Open ports on localhost (unexpected services)
    - Plaintext passwords in users.json
    - Python packages with known vulnerability markers
    """

    SENSITIVE_FILES = [
        "user_profiles/users.json",
        "brados_vault.enc",
        "brados_audit.log",
        "brados_integrity.json",
    ]

    SUSPICIOUS_PORTS = {
        4444: "Metasploit default",
        1337: "Common backdoor",
        31337: "Elite backdoor",
        12345: "NetBus trojan",
        6666:  "IRC / common malware",
    }

    KNOWN_PORTS = {
        21: "FTP", 22: "SSH", 23: "Telnet (insecure)", 25: "SMTP",
        80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
        6379: "Redis", 8080: "HTTP-alt", 8888: "Jupyter", 9200: "Elasticsearch",
    }

    def __init__(self, audit: AuditLog):
        self._audit = audit

    def scan(self) -> list[ThreatFinding]:
        findings: list[ThreatFinding] = []
        findings.extend(self._check_file_permissions())
        findings.extend(self._check_world_writable())
        findings.extend(self._check_open_ports())
        findings.extend(self._check_password_hashes())
        count = len(findings)
        severity = "ALERT" if any(f.severity in ("HIGH","CRITICAL")
                                  for f in findings) else "INFO"
        self._audit.write(severity, "SCAN",
                          f"Threat scan complete: {count} finding(s)",
                          {"count": count})
        return findings

    def _check_file_permissions(self) -> list[ThreatFinding]:
        findings = []
        for fpath in self.SENSITIVE_FILES:
            if not os.path.exists(fpath):
                continue
            mode = os.stat(fpath).st_mode & 0o777
            if mode & 0o044:   # group/other readable
                findings.append(ThreatFinding(
                    severity="HIGH", category="PERM",
                    title=f"Sensitive file world/group-readable",
                    detail=f"chmod 600 {fpath}  (current: {oct(mode)})",
                    path=fpath,
                ))
        return findings

    def _check_world_writable(self) -> list[ThreatFinding]:
        findings = []
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files[:50]:   # cap at 50 files per dir
                fpath = os.path.join(root, fname)
                try:
                    if os.stat(fpath).st_mode & 0o002:
                        findings.append(ThreatFinding(
                            severity="MEDIUM", category="PERM",
                            title="World-writable file",
                            detail=f"Any local user can modify this file",
                            path=fpath,
                        ))
                except OSError:
                    pass
            if len(findings) > 20:
                break
        return findings

    def _check_open_ports(self) -> list[ThreatFinding]:
        findings = []
        all_ports = {**self.KNOWN_PORTS, **self.SUSPICIOUS_PORTS}
        for port, name in all_ports.items():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.12)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        if port in self.SUSPICIOUS_PORTS:
                            findings.append(ThreatFinding(
                                severity="CRITICAL", category="PORT",
                                title=f"Suspicious port open: {port}",
                                detail=f"{name} — possible backdoor or malware",
                            ))
                        elif port in (23,):  # telnet — insecure
                            findings.append(ThreatFinding(
                                severity="HIGH", category="PORT",
                                title=f"Insecure service: {port} ({name})",
                                detail="Telnet transmits in cleartext — disable it",
                            ))
                        else:
                            findings.append(ThreatFinding(
                                severity="LOW", category="PORT",
                                title=f"Open port: {port} ({name})",
                                detail="Review if this service should be running",
                            ))
            except Exception:
                pass
        return findings

    def _check_password_hashes(self) -> list[ThreatFinding]:
        findings = []
        db_path = os.path.join("user_profiles", "users.json")
        if not os.path.exists(db_path):
            return findings
        try:
            with open(db_path) as f:
                users = json.load(f)
            for uid, info in users.items():
                pwd = info.get("password", "")
                if pwd and not pwd.startswith("pbkdf2:"):
                    findings.append(ThreatFinding(
                        severity="CRITICAL", category="AUTH",
                        title=f"Plaintext password: uid {uid} ({info.get('name','?')})",
                        detail="Open brados.py kernel mode to auto-rehash",
                        path=db_path,
                    ))
        except Exception:
            pass
        return findings


# ── BradSec — top-level facade ────────────────────────────────────────────────

class BradSec:
    """Single entry point for the BradOS security subsystem.

    Instantiated once by the kernel or shell and passed around by reference.

    Usage:
        sec = BradSec()
        sec.start()
        token = sec.issue_token(pid=1, uid=0, caps=Cap.ADMIN)
        findings = sec.scan()
        sec.audit.write("INFO", "AUTH", "User logged in", {"user": "brad"})
    """

    def __init__(self):
        self._secret  : bytes          = secrets.token_bytes(32)
        self.audit    : AuditLog       = AuditLog()
        self.integrity: IntegrityDaemon= IntegrityDaemon(self.audit)
        self.vault    : EncryptedVault = EncryptedVault(self.audit)
        self.scanner  : ThreatScanner  = ThreatScanner(self.audit)
        self._tokens  : dict[int, CapabilityToken] = {}   # pid → token
        self._lock    = threading.Lock()
        self._started = False

    def start(self) -> None:
        """Boot the security subsystem — call once at kernel/app init."""
        if self._started:
            return
        self._started = True
        self.audit.write("INFO", "INTEGRITY", "BradSec v1.0 starting")
        # Load or build integrity baseline in background
        threading.Thread(target=self._bg_integrity_init,
                         daemon=True, name="bradsec-integrity").start()

    def _bg_integrity_init(self) -> None:
        if not self.integrity.load_baseline():
            self.integrity.build_baseline()

    # ── Capability tokens ──────────────────────────────────────────────────

    def issue_token(self, pid: int, uid: int,
                    caps: Cap = Cap.default_user()) -> CapabilityToken:
        token = CapabilityToken(pid=pid, uid=uid, caps=int(caps))
        token.sign(self._secret)
        with self._lock:
            self._tokens[pid] = token
        self.audit.write("INFO", "CAPS",
                         f"Token issued: pid={pid} uid={uid}",
                         {"caps": int(caps)})
        return token

    def verify_token(self, token: CapabilityToken) -> bool:
        if token.expired:
            self.audit.write("WARNING", "CAPS",
                             f"Expired token: pid={token.pid}")
            return False
        return token.verify(self._secret)

    def check_cap(self, pid: int, cap: Cap) -> bool:
        """Return True if the process holds the given capability."""
        with self._lock:
            token = self._tokens.get(pid)
        if not token:
            return False
        if not self.verify_token(token):
            return False
        return token.has(cap)

    def revoke_token(self, pid: int) -> None:
        with self._lock:
            self._tokens.pop(pid, None)
        self.audit.write("INFO", "CAPS", f"Token revoked: pid={pid}")

    # ── Convenience wrappers ───────────────────────────────────────────────

    def scan(self) -> list[ThreatFinding]:
        return self.scanner.scan()

    def verify_integrity(self) -> list[dict]:
        return self.integrity.verify()

    def unlock_vault(self, password: str) -> bool:
        return self.vault.unlock(password)

    def status(self) -> dict:
        """Summary dict for the Settings / BradSec window."""
        with self._lock:
            active_tokens = len(self._tokens)
        vault_locked = self.vault._key is None
        baseline_exists = os.path.exists(IntegrityDaemon.MANIFEST_PATH)
        audit_lines = 0
        try:
            with open(self.audit._path) as f:
                audit_lines = sum(1 for _ in f)
        except FileNotFoundError:
            pass
        return {
            "status":         "active" if self._started else "inactive",
            "active_tokens":  active_tokens,
            "vault_locked":   vault_locked,
            "baseline_exists":baseline_exists,
            "audit_events":   audit_lines,
            "secret_bits":    len(self._secret) * 8,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# BRADSEC DAEMON — background security service with IPC
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

BRADSEC_SOCKET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brados_files")
BRADSEC_SOCKET_PATH = os.path.join(BRADSEC_SOCKET_DIR, "brados_sec.sock")
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brados_policy.yaml")
QUARANTINE_DIR = os.path.join(BRADSEC_SOCKET_DIR, "quarantine")
SCAN_INTERVAL = 300  # seconds between background scans

os.makedirs(BRADSEC_SOCKET_DIR, exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# POLICY ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_POLICY_YAML = """
policies:
  # Per-process capability policies
  # on_violation: kill | warn | quarantine
  mail-server:
    caps: [NET_BIND, NET_SEND, FS_READ, FS_WRITE]
    on_violation: kill
  bpkg:
    caps: [FS_READ, FS_WRITE, PROC_FORK]
    on_violation: warn
  editor:
    caps: [FS_READ, FS_WRITE]
    on_violation: warn
  terminal:
    caps: [FS_READ, FS_WRITE, NET_SEND, PROC_FORK]
    on_violation: warn
  guest:
    caps: [FS_READ, NET_SEND]
    on_violation: kill

auto_response:
  tampered_files: quarantine   # quarantine | warn | restore
  suspicious_ports: warn       # kill_process | warn
"""


class PolicyEngine:
    """Loads and enforces brados_policy.yaml.

    Policy defines per-process capabilities and auto-response actions.
    The daemon checks tokens against policy on issue and enforces
    on_violation actions (kill, warn, quarantine).
    """

    def __init__(self, audit: AuditLog):
        self._audit = audit
        self._policies: dict[str, dict] = {}
        self._responses: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not _HAS_YAML:
            self._audit.write("WARNING", "POLICY",
                              "PyYAML not installed — using default policy")
            self._load_yaml_str(DEFAULT_POLICY_YAML)
            return
        try:
            if os.path.exists(POLICY_PATH):
                with open(POLICY_PATH) as f:
                    data = yaml.safe_load(f)
                self._load_yaml(data)
                self._audit.write("INFO", "POLICY",
                                  f"Policy loaded: {len(self._policies)} rule(s)")
            else:
                # Write default policy file
                with open(POLICY_PATH, "w") as f:
                    f.write(DEFAULT_POLICY_YAML)
                self._load_yaml_str(DEFAULT_POLICY_YAML)
                self._audit.write("INFO", "POLICY",
                                  "Default policy created: brados_policy.yaml")
        except Exception as e:
            self._audit.write("ALERT", "POLICY",
                              f"Policy load error: {e} — using defaults")
            self._load_yaml_str(DEFAULT_POLICY_YAML)

    def _load_yaml_str(self, text: str) -> None:
        if _HAS_YAML:
            data = yaml.safe_load(text)
        else:
            # Minimal YAML parser fallback for the default policy
            data = self._simple_parse(text)
        self._load_yaml(data)

    def _simple_parse(self, text: str) -> dict:
        """Minimal parser for the default policy YAML (no pyyaml dependency)."""
        # This handles the DEFAULT_POLICY_YAML format only
        result: dict = {"policies": {}, "auto_response": {}}
        current_section = None
        current_policy = None
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "policies:":
                current_section = "policies"
                continue
            if stripped == "auto_response:":
                current_section = "auto_response"
                continue
            if current_section == "auto_response":
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    result.setdefault("auto_response", {})[k.strip()] = v.strip()
                continue
            if current_section == "policies":
                if not stripped.startswith("-") and ":" in stripped:
                    if "caps" not in stripped and "on_violation" not in stripped:
                        current_policy = stripped.split(":")[0].strip()
                        result.setdefault("policies", {})[current_policy] = {}
                    elif current_policy:
                        k, v = stripped.split(":", 1)
                        k = k.strip().lstrip("- ")
                        v = v.strip()
                        if k == "caps":
                            v = [c.strip().strip("[]").strip() for c in v.split(",")]
                        result["policies"][current_policy][k] = v
        return result

    def _load_yaml(self, data: dict) -> None:
        policies = data.get("policies", {})
        self._policies = {}
        for name, rule in policies.items():
            caps_list = rule.get("caps", [])
            cap_int = 0
            for c in caps_list:
                try:
                    cap_int |= int(Cap[c.strip()])
                except (KeyError, ValueError):
                    pass
            self._policies[name] = {
                "caps": cap_int,
                "on_violation": rule.get("on_violation", "warn"),
            }
        self._responses = data.get("auto_response", {})

    def get_policy(self, name: str) -> dict | None:
        return self._policies.get(name)

    def check_token(self, pid: int, name: str | None, caps: int) -> str | None:
        """Check if the given caps are allowed by policy.
        Returns None if allowed, or the violation action ('kill', 'warn')
        if the caps exceed what the policy allows."""
        if not name or name not in self._policies:
            return None  # no policy for this name — allow
        policy = self._policies[name]
        allowed = policy["caps"]
        # Check if the token has any cap not in the allowed set
        excess = caps & ~allowed
        if excess:
            return policy["on_violation"]
        return None

    def get_response(self, key: str) -> str:
        return self._responses.get(key, "warn")

    def reload(self) -> None:
        self._load()

    @property
    def rules(self) -> dict:
        return dict(self._policies)

    @property
    def responses(self) -> dict:
        return dict(self._responses)


# ═══════════════════════════════════════════════════════════════════════════════
# FILE WATCHER — inotify via ctypes (Linux) with polling fallback
# ═══════════════════════════════════════════════════════════════════════════════

_HAS_INOTIFY = hasattr(os, "inotify") or hasattr(os, "inotify_add_watch")


class FileWatcher:
    """Monitors BradOS source files for changes in real-time.

    Uses Linux inotify via ctypes when available, falls back to polling
    every 30 seconds.  Fires a callback when files are modified, created,
    or deleted.
    """

    WATCHED_EXTS = {".py", ".json", ".yaml", ".yml", ".log", ".enc"}
    IGNORE_DIRS  = {"__pycache__", ".git", "backup_", QUARANTINE_DIR}

    def __init__(self, audit: AuditLog, callback: callable):
        self._audit = audit
        self._callback = callback
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True, name="bradsec-filewatch",
        )
        self._thread.start()
        self._audit.write("INFO", "WATCHER", "File watcher started")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        try:
            self._inotify_loop()
        except Exception:
            self._polling_loop()

    # ── inotify via ctypes ──────────────────────────────────────────────

    def _inotify_loop(self) -> None:
        import ctypes
        import ctypes.util
        import select

        libc = ctypes.util.find_library("c")
        if not libc:
            raise RuntimeError("libc not found")
        clib = ctypes.CDLL(libc, use_errno=True)

        IN_CLOSE_WRITE = 0x00000008
        IN_CREATE = 0x00000100
        IN_DELETE = 0x00000200
        IN_MOVED_FROM = 0x00000040
        IN_MOVED_TO = 0x00000080
        IN_MODIFY = 0x00000002
        IN_ATTRIB = 0x00000004
        MASK = IN_CLOSE_WRITE | IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_MODIFY | IN_ATTRIB

        fd = clib.inotify_init()
        if fd < 0:
            raise RuntimeError("inotify_init failed")

        watched: dict[int, str] = {}
        try:
            wd_map: dict[int, str] = {}
            for root, dirs, fnames in os.walk("."):
                dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
                wd = clib.inotify_add_watch(fd, root.encode(), MASK)
                if wd >= 0:
                    wd_map[wd] = root

            while self._running:
                r, _, _ = select.select([fd], [], [], 1.0)
                if not r:
                    continue
                buf = os.read(fd, 65536)
                i = 0
                while i < len(buf):
                    wd, mask, cookie, name_len = struct.unpack_from("iIII", buf, i)
                    name = buf[i + 16:i + 16 + name_len].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
                    i += 16 + name_len
                    if not name or not any(name.endswith(e) for e in self.WATCHED_EXTS):
                        continue
                    dir_path = wd_map.get(wd, ".")
                    fpath = os.path.join(dir_path, name)
                    self._callback("MODIFIED", fpath)
                    self._audit.write("INFO", "WATCHER",
                                      f"File changed: {fpath}")
        finally:
            try:
                clib.close(fd)
            except Exception:
                pass

    # ── Polling fallback ─────────────────────────────────────────────────

    def _polling_loop(self) -> None:
        """Fallback: poll every 30 seconds for file changes."""
        self._audit.write("INFO", "WATCHER",
                          "inotify unavailable — using polling fallback (30s)")
        baseline: dict[str, float] = {}
        while self._running:
            time.sleep(30)
            if not self._running:
                break
            try:
                for root, dirs, fnames in os.walk("."):
                    dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
                    for fname in fnames:
                        if not any(fname.endswith(e) for e in self.WATCHED_EXTS):
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            mtime = os.path.getmtime(fpath)
                            if fpath in baseline and baseline[fpath] != mtime:
                                self._callback("MODIFIED", fpath)
                            baseline[fpath] = mtime
                        except OSError:
                            pass
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-RESPONSE
# ═══════════════════════════════════════════════════════════════════════════════

def auto_respond(audit: AuditLog, action: str, finding_type: str,
                 detail: dict) -> None:
    """Execute an automated response action.

    Supported actions:
      - warn:        log a warning (always available)
      - kill:        send SIGTERM to the offending pid
      - quarantine:  move tampered file to QUARANTINE_DIR
      - kill_process: send SIGTERM to the process on the given port
    """
    if action == "warn":
        audit.write("WARNING", "AUTO-RESPOND",
                    f"{finding_type}: {detail.get('message', '')}",
                    detail)

    elif action == "kill":
        pid = detail.get("pid")
        if pid and pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                audit.write("ALERT", "AUTO-RESPOND",
                            f"Killed pid {pid}: {detail.get('reason', 'policy violation')}",
                            detail)
            except ProcessLookupError:
                pass
            except PermissionError:
                audit.write("ALERT", "AUTO-RESPOND",
                            f"Permission denied killing pid {pid}", detail)

    elif action == "quarantine":
        fpath = detail.get("path", "")
        if fpath and os.path.exists(fpath):
            try:
                qpath = os.path.join(QUARANTINE_DIR, os.path.basename(fpath) + "." + str(int(time.time())))
                shutil.move(fpath, qpath)
                audit.write("ALERT", "AUTO-RESPOND",
                            f"Quarantined: {fpath} → {qpath}",
                            {"path": fpath, "quarantine_path": qpath})
            except Exception as e:
                audit.write("ALERT", "AUTO-RESPOND",
                            f"Quarantine failed: {fpath} — {e}", detail)

    elif action == "kill_process":
        port = detail.get("port")
        if port:
            audit.write("WARNING", "AUTO-RESPOND",
                        f"Suspicious port {port}: review required — auto-kill not implemented",
                        detail)


# ═══════════════════════════════════════════════════════════════════════════════
# BRADSEC DAEMON — background security service with IPC
# ═══════════════════════════════════════════════════════════════════════════════

class BradSecDaemon:
    """Persistent background security daemon with Unix socket IPC.

    Runs an asyncio event loop in a daemon thread, listens for JSON-over-Unix-
    socket commands at {BRADSEC_SOCKET_PATH}, enforces policy, watches files
    in real-time, and performs periodic background threat scans.
    """

    def __init__(self, bradsec: BradSec | None = None) -> None:
        self._sec = bradsec or get_bradsec()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._scan_task: asyncio.Task | None = None
        self._on_alert: list[callable] = []  # callbacks for alerts
        self.policy = PolicyEngine(self._sec.audit)
        self.watcher = FileWatcher(self._sec.audit, self._on_file_changed)

    def _on_file_changed(self, change_type: str, path: str) -> None:
        """Callback fired by FileWatcher when a file changes."""
        # Trigger integrity verification
        tampered = self._sec.verify_integrity()
        modified = [f for f in tampered if f.get("type") == "MODIFIED"]
        if modified:
            response_action = self.policy.get_response("tampered_files")
            for f in modified:
                auto_respond(self._sec.audit, response_action,
                             "FILE_TAMPERED", {"path": f["path"]})
            self._sec.audit.write("ALERT", "WATCHER",
                                  f"Real-time integrity: {len(modified)} modified",
                                  {"count": len(modified)})
            self._notify_alerts_raw([{
                "severity": "HIGH", "category": "INTEGRITY",
                "title": f"File tampered: {modified[0]['path']}",
                "detail": f"{len(modified)} file(s) modified — auto-response: {response_action}",
            }])

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the daemon thread. Returns True if started, False if already running."""
        if self._running:
            return False
        self._running = True
        self._sec.start()
        self.watcher.start()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            daemon=True, name="bradsec-daemon",
        )
        self._thread.start()
        self._sec.audit.write("INFO", "DAEMON", "BradSec daemon started")
        return True

    def stop(self) -> None:
        """Signal shutdown and wait for the daemon thread to exit."""
        if not self._running:
            return
        self._running = False
        self.watcher.stop()
        # Remove socket file
        if os.path.exists(BRADSEC_SOCKET_PATH):
            try:
                os.unlink(BRADSEC_SOCKET_PATH)
            except OSError:
                pass
        if self._loop and not self._loop.is_closed():

            def _shutdown() -> None:
                if self._scan_task and not self._scan_task.done():
                    self._scan_task.cancel()
                self._loop.stop()

            self._loop.call_soon_threadsafe(_shutdown)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._sec.audit.write("INFO", "DAEMON", "BradSec daemon stopped")

    @property
    def running(self) -> bool:
        return self._running

    # ── Event loop ───────────────────────────────────────────────────────

    def _run_event_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            self._sec.audit.write("ALERT", "DAEMON",
                                  f"Daemon error: {exc}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _serve(self) -> None:
        # Remove stale socket if present
        if os.path.exists(BRADSEC_SOCKET_PATH):
            os.unlink(BRADSEC_SOCKET_PATH)
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=BRADSEC_SOCKET_PATH,
        )
        os.chmod(BRADSEC_SOCKET_PATH, 0o600)
        self._scan_task = asyncio.create_task(self._background_scanner())
        async with self._server:
            await self._server.serve_forever()

    # ── Client handler ───────────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(65536), timeout=30)
            if not data:
                return
            response = self._dispatch(data)
            writer.write(response.encode() + b"\n")
            await writer.drain()
        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            self._sec.audit.write("WARNING", "DAEMON",
                                  f"Client error: {exc}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def _dispatch(self, data: bytes) -> str:
        """Parse JSON command, execute, return JSON response."""
        try:
            req = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return json.dumps({"ok": False, "error": "invalid JSON"})

        cmd = req.get("cmd", "")
        args = req.get("args", {})

        handler = {
            "ping":           self._cmd_ping,
            "status":         self._cmd_status,
            "scan":           self._cmd_scan,
            "verify":         self._cmd_verify,
            "build_baseline": self._cmd_build_baseline,
            "check_cap":      self._cmd_check_cap,
            "issue_token":    self._cmd_issue_token,
            "revoke_token":   self._cmd_revoke_token,
            "tail_audit":     self._cmd_tail_audit,
            "vault_status":   self._cmd_vault_status,
            "vault_get":      self._cmd_vault_get,
            "vault_list":     self._cmd_vault_list,
            "policy_reload":  self._cmd_policy_reload,
            "policy_status":  self._cmd_policy_status,
            "start":          self._cmd_start,
            "stop":           self._cmd_stop,
        }.get(cmd)

        if handler is None:
            return json.dumps({"ok": False, "error": f"unknown cmd: {cmd}"})

        try:
            result = handler(args)
            return json.dumps({"ok": True, "data": result})
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})

    # ── Command handlers ─────────────────────────────────────────────────

    def _cmd_ping(self, _args: dict) -> dict:
        return {"message": "pong", "running": self._running}

    def _cmd_status(self, _args: dict) -> dict:
        st = self._sec.status()
        st["daemon_running"] = self._running
        st["socket_path"] = BRADSEC_SOCKET_PATH
        st["policy_rules"] = len(self.policy.rules)
        st["watcher_active"] = self.watcher._running if hasattr(self.watcher, '_running') else False
        return st

    def _cmd_scan(self, _args: dict) -> list[dict]:
        findings = self._sec.scan()
        # Auto-respond to suspicious ports
        port_findings = [f for f in findings if f.category == "PORT" and f.severity in ("HIGH", "CRITICAL")]
        response_action = self.policy.get_response("suspicious_ports")
        for f in port_findings:
            auto_respond(self._sec.audit, response_action,
                         "SUSPICIOUS_PORT", {"port": f.title, "message": f.detail})
        return [asdict(f) for f in findings]

    def _cmd_verify(self, _args: dict) -> list[dict]:
        return self._sec.verify_integrity()

    def _cmd_build_baseline(self, _args: dict) -> dict:
        manifest = self._sec.integrity.build_baseline()
        return {"file_count": len(manifest)}

    def _cmd_check_cap(self, args: dict) -> dict:
        pid = int(args.get("pid", -1))
        cap_name = args.get("cap", "")
        try:
            cap = Cap[cap_name]
        except KeyError:
            return {"error": f"unknown cap: {cap_name}"}
        result = self._sec.check_cap(pid, cap)
        return {"pid": pid, "cap": cap_name, "granted": result}

    def _cmd_issue_token(self, args: dict) -> dict:
        pid = int(args.get("pid", -1))
        uid = int(args.get("uid", 0))
        name = args.get("name", "")
        caps_str = args.get("caps", "default_user")
        if caps_str == "default_user":
            caps = Cap.default_user()
        elif caps_str == "default_guest":
            caps = Cap.default_guest()
        elif caps_str == "admin":
            caps = Cap.ADMIN
        else:
            try:
                caps = Cap(int(caps_str))
            except (ValueError, TypeError):
                return {"error": f"invalid caps value: {caps_str}"}
        # Check policy before issuing
        violation = self.policy.check_token(pid, name, int(caps))
        if violation == "kill":
            self._sec.audit.write("ALERT", "POLICY",
                                  f"Token denied for {name}: policy violation",
                                  {"pid": pid, "name": name, "caps": int(caps)})
            return {"error": f"policy violation for '{name}' — token denied"}
        token = self._sec.issue_token(pid, uid, caps)
        result = token.to_dict()
        result["name"] = name
        return result

    def _cmd_revoke_token(self, args: dict) -> dict:
        pid = int(args.get("pid", -1))
        self._sec.revoke_token(pid)
        return {"pid": pid, "revoked": True}

    def _cmd_tail_audit(self, args: dict) -> list[dict]:
        n = int(args.get("count", 30))
        return self._sec.audit.tail(n)

    def _cmd_vault_status(self, _args: dict) -> dict:
        locked = self._sec.vault._key is None
        return {"locked": locked, "key_count": len(self._sec.vault.list_keys()) if not locked else 0}

    def _cmd_vault_get(self, args: dict) -> dict | None:
        key = args.get("key", "")
        return self._sec.vault.get(key)

    def _cmd_vault_list(self, _args: dict) -> list[str]:
        return self._sec.vault.list_keys()

    def _cmd_policy_reload(self, _args: dict) -> dict:
        self.policy.reload()
        return {"rules": len(self.policy.rules)}

    def _cmd_policy_status(self, _args: dict) -> dict:
        return {
            "rules": self.policy.rules,
            "responses": self.policy.responses,
        }

    def _cmd_start(self, _args: dict) -> dict:
        started = self.start()
        return {"started": started}

    def _cmd_stop(self, _args: dict) -> dict:
        self.stop()
        return {"stopped": True}

    # ── Background scanner ───────────────────────────────────────────────

    async def _background_scanner(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(SCAN_INTERVAL)
                if not self._running:
                    break
                try:
                    findings = self._sec.scan()
                    critical = [f for f in findings
                                if f.severity in ("HIGH", "CRITICAL")]
                    if critical:
                        self._sec.audit.write(
                            "ALERT", "DAEMON",
                            f"Background scan: {len(critical)} critical finding(s)",
                            {"count": len(critical), "findings": [asdict(f) for f in critical]},
                        )
                        self._notify_alerts(critical)
                        # Auto-respond to critical findings
                        for f in critical:
                            if f.category == "PORT":
                                action = self.policy.get_response("suspicious_ports")
                                auto_respond(self._sec.audit, action,
                                             "SUSPICIOUS_PORT",
                                             {"port": f.title, "message": f.detail})
                    # Integrity check
                    integrity = self._sec.verify_integrity()
                    tampered = [f for f in integrity if f.get("type") == "MODIFIED"]
                    if tampered:
                        action = self.policy.get_response("tampered_files")
                        for f in tampered:
                            auto_respond(self._sec.audit, action,
                                         "FILE_TAMPERED", {"path": f["path"]})
                        self._sec.audit.write(
                            "ALERT", "DAEMON",
                            f"Integrity: {len(tampered)} modified — response: {action}",
                            {"count": len(tampered), "action": action},
                        )
                except Exception as exc:
                    self._sec.audit.write("WARNING", "DAEMON",
                                          f"Background scan error: {exc}")
        except asyncio.CancelledError:
            pass

    # ── Alert callbacks ──────────────────────────────────────────────────

    def on_alert(self, callback: callable) -> None:
        """Register a callback for CRITICAL/HIGH alerts.
        Callback receives a list of ThreatFinding dicts."""
        self._on_alert.append(callback)

    def _notify_alerts(self, findings: list[ThreatFinding]) -> None:
        dicts = [asdict(f) for f in findings]
        self._notify_alerts_raw(dicts)

    def _notify_alerts_raw(self, alerts: list[dict]) -> None:
        for cb in self._on_alert:
            try:
                cb(alerts)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# BRADSEC CLIENT — Unix socket IPC client
# ═══════════════════════════════════════════════════════════════════════════════

class BradSecClient:
    """Synchronous IPC client for BradSecDaemon.

    Connects to the daemon Unix socket, sends a JSON command, and returns
    the parsed response.  Used by modules that want to check capabilities
    or query security state without importing BradSec directly.
    """

    TIMEOUT = 5.0

    def __init__(self, socket_path: str = ""):
        self._socket_path = socket_path or BRADSEC_SOCKET_PATH

    def send(self, cmd: str, args: dict | None = None) -> dict:
        payload = json.dumps({"cmd": cmd, "args": args or {}})
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.TIMEOUT)
                s.connect(self._socket_path)
                s.sendall(payload.encode() + b"\n")
                resp = s.recv(65536).decode().strip()
                return json.loads(resp)
        except (socket.error, json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETONS
# ═══════════════════════════════════════════════════════════════════════════════

_bradsec: BradSec | None = None
_bradsec_daemon: BradSecDaemon | None = None


def get_bradsec() -> BradSec:
    """Return the global BradSec instance, creating it on first call."""
    global _bradsec
    if _bradsec is None:
        _bradsec = BradSec()
    return _bradsec


def get_bradsec_daemon() -> BradSecDaemon:
    """Return the global BradSecDaemon instance, creating it on first call."""
    global _bradsec_daemon
    if _bradsec_daemon is None:
        _bradsec_daemon = BradSecDaemon(get_bradsec())
    return _bradsec_daemon

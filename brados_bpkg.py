# brados_bpkg.py — BradOS Package Manager (bpkg) v1.0
#
# Package management, pip integration, remote registry, dependency resolution,
# and upgrade support. 8 curated packages covering monitoring, crypto, imaging,
# PTY terminals, audio, and development tools. No other terminal OS has a
# package manager — BradOS ships with one.

from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import logging
import subprocess
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable

logger = logging.getLogger("brados.bpkg")

# ── Package spec ──────────────────────────────────────────────────────────────

@dataclass
class Package:
    name         : str
    version      : str
    description  : str
    author       : str           = "BradOS Community"
    category     : str           = "app"     # app / system / lib / theme
    pip_deps     : list[str]     = field(default_factory=list)
    pip_versions : dict[str, str] = field(default_factory=dict)  # e.g. {"requests": ">=2.28"}
    bpkg_deps    : list[str]     = field(default_factory=list)
    install_script: str          = ""        # shell snippet run after pip
    homepage     : str           = ""
    license      : str           = "MIT"
    size_kb      : int           = 0
    tags         : list[str]     = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Package":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class InstalledPackage:
    name         : str
    version      : str
    installed_at : str
    pip_deps     : list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Built-in curated registry ─────────────────────────────────────────────────

BUILTIN_REGISTRY: list[dict] = [
    {
        "name":        "brad-psutil",
        "version":     "1.0.0",
        "description": "Live CPU/RAM/disk metrics in the Monitor and taskbar tray",
        "category":    "lib",
        "pip_deps":    ["psutil"],
        "tags":        ["monitoring", "performance", "system"],
        "size_kb":     800,
    },
    {
        "name":        "brad-requests",
        "version":     "1.0.0",
        "description": "Full HTTPS support for BradBrowser (real web browsing)",
        "category":    "lib",
        "pip_deps":    ["requests"],
        "tags":        ["browser", "network", "http"],
        "size_kb":     300,
    },
    {
        "name":        "brad-crypto",
        "version":     "1.0.0",
        "description": "Fernet encryption for BradSec vault (upgrade from XOR fallback)",
        "category":    "lib",
        "pip_deps":    ["cryptography"],
        "tags":        ["security", "encryption", "vault"],
        "size_kb":     2_400,
    },
    {
        "name":        "brad-imaging",
        "version":     "1.0.0",
        "description": "SVG viewer and image processing for BradOS apps",
        "category":    "lib",
        "pip_deps":    ["Pillow", "cairosvg"],
        "tags":        ["images", "svg", "viewer"],
        "size_kb":     15_000,
    },
    {
        "name":        "brad-pty",
        "version":     "0.9.0",
        "description": "VT100 PTY terminal — run nano, vim, htop in the terminal app",
        "category":    "lib",
        "pip_deps":    ["pyte"],
        "tags":        ["terminal", "pty", "vim", "nano"],
        "size_kb":     120,
    },
    {
        "name":        "brad-audio",
        "version":     "1.0.0",
        "description": "Audio playback support for BradOS (system sounds, music player)",
        "category":    "lib",
        "pip_deps":    ["playsound"],
        "tags":        ["audio", "sound", "music"],
        "size_kb":     50,
    },
    {
        "name":        "brad-full",
        "version":     "1.0.0",
        "description": "Install all recommended BradOS dependencies in one command",
        "category":    "meta",
        "pip_deps":    ["psutil", "requests", "cryptography", "Pillow"],
        "bpkg_deps":   ["brad-psutil", "brad-requests", "brad-crypto", "brad-imaging"],
        "tags":        ["meta", "recommended", "all"],
        "size_kb":     20_000,
    },
    {
        "name":        "brad-dev",
        "version":     "1.0.0",
        "description": "Development tools: pytest, mypy, black, ruff for BradOS hacking",
        "category":    "dev",
        "pip_deps":    ["pytest", "pytest-asyncio", "mypy", "black", "ruff"],
        "tags":        ["dev", "testing", "lint"],
        "size_kb":     8_000,
    },
]


# ── Package registry ──────────────────────────────────────────────────────────

class PackageRegistry:
    """Curated package index.  Built-in packages are always available.
    Optional remote registry can be fetched from a URL."""

    REMOTE_URL   = "https://raw.githubusercontent.com/BradOS/registry/main/index.json"
    CACHE_PATH   = os.path.join("brados_files", "bpkg", "registry_cache.json")
    CACHE_TTL    = 3600 * 6   # 6 hours

    def __init__(self):
        self._packages: dict[str, Package] = {}
        self._load_builtin()
        self._load_cache()

    def _load_builtin(self) -> None:
        for pkg_dict in BUILTIN_REGISTRY:
            pkg = Package.from_dict(pkg_dict)
            self._packages[pkg.name] = pkg

    def _load_cache(self) -> None:
        if not os.path.exists(self.CACHE_PATH):
            return
        try:
            mtime = os.path.getmtime(self.CACHE_PATH)
            if time.time() - mtime > self.CACHE_TTL:
                return
            with open(self.CACHE_PATH) as f:
                data = json.load(f)
            for pkg_dict in data.get("packages", []):
                pkg = Package.from_dict(pkg_dict)
                self._packages[pkg.name] = pkg
        except Exception as e:
            logger.warning(f"Registry cache load failed: {e}")

    def fetch_remote(self,
                     progress: Callable[[str], None] | None = None) -> bool:
        """Download and cache the remote registry. Returns True on success."""
        try:
            import requests        # type: ignore
            if progress:
                progress("Fetching remote registry…")
            resp = requests.get(self.REMOTE_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            os.makedirs(os.path.dirname(self.CACHE_PATH), exist_ok=True)
            tmp = self.CACHE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.CACHE_PATH)
            for pkg_dict in data.get("packages", []):
                pkg = Package.from_dict(pkg_dict)
                self._packages[pkg.name] = pkg
            if progress:
                progress(f"Registry updated: {len(data.get('packages',[]))} packages")
            return True
        except Exception as e:
            if progress:
                progress(f"Remote registry unavailable: {e}")
            return False

    def get(self, name: str) -> Package | None:
        return self._packages.get(name)

    def search(self, query: str) -> list[Package]:
        q = query.lower()
        return [
            p for p in self._packages.values()
            if q in p.name.lower()
            or q in p.description.lower()
            or any(q in t for t in p.tags)
        ]

    def all_packages(self) -> list[Package]:
        return list(self._packages.values())

    def by_category(self, category: str) -> list[Package]:
        return [p for p in self._packages.values() if p.category == category]


# ── Package database (installed) ──────────────────────────────────────────────

class PackageDB:
    """Tracks installed packages. Stored in VFS at /var/bpkg/installed.json."""

    DB_PATH = os.path.join("brados_files", "var", "bpkg", "installed.json")

    def __init__(self):
        self._installed: dict[str, InstalledPackage] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.DB_PATH):
            return
        try:
            with open(self.DB_PATH) as f:
                data = json.load(f)
            for name, pkg_dict in data.items():
                self._installed[name] = InstalledPackage(**pkg_dict)
        except Exception as e:
            logger.warning(f"Package DB load failed: {e}")

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
        tmp = self.DB_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump({k: v.to_dict() for k, v in self._installed.items()},
                      f, indent=2)
        os.replace(tmp, self.DB_PATH)

    def mark_installed(self, pkg: Package) -> None:
        with self._lock:
            self._installed[pkg.name] = InstalledPackage(
                name         = pkg.name,
                version      = pkg.version,
                installed_at = datetime.now().isoformat(),
                pip_deps     = pkg.pip_deps,
            )
            self._save()

    def mark_removed(self, name: str) -> None:
        with self._lock:
            self._installed.pop(name, None)
            self._save()

    def is_installed(self, name: str) -> bool:
        return name in self._installed

    def get(self, name: str) -> InstalledPackage | None:
        return self._installed.get(name)

    def list_installed(self) -> list[InstalledPackage]:
        return list(self._installed.values())


# ── pip helper ────────────────────────────────────────────────────────────────

class PypiHelper:
    """Wrapper around pip that captures streaming output."""

    @staticmethod
    def install(packages: list[str],
                versions: dict[str, str] | None = None,
                progress: Callable[[str], None] | None = None) -> bool:
        """Install pip packages. Streams output to progress callback.
        ``versions`` maps package names to version constraints (e.g. ``>=2.28``)."""
        if not packages:
            return True
        pinned = []
        for pkg in packages:
            if versions and pkg in versions:
                pinned.append(f"{pkg}{versions[pkg]}")
            else:
                pinned.append(pkg)
        cmd = [sys.executable, "-m", "pip", "install",
               "--upgrade", "--no-warn-script-location"] + pinned
        return PypiHelper._run(cmd, progress)

    @staticmethod
    def uninstall(packages: list[str],
                  progress: Callable[[str], None] | None = None) -> bool:
        if not packages:
            return True
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y"] + packages
        return PypiHelper._run(cmd, progress)

    @staticmethod
    def is_installed(package: str) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec(package.split("[")[0]) is not None
        except (ImportError, ValueError):
            return False

    @staticmethod
    def _run(cmd: list[str],
             progress: Callable[[str], None] | None) -> bool:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):  # type: ignore
                line = line.rstrip()
                if line and progress:
                    progress(line)
            proc.wait()
            return proc.returncode == 0
        except Exception as e:
            if progress:
                progress(f"Error: {e}")
            return False


# ── BpkgManager ───────────────────────────────────────────────────────────────

@dataclass
class InstallResult:
    success  : bool
    package  : str
    messages : list[str]
    duration : float


class BpkgManager:
    """Top-level package manager.  Used by the shell and classic CLI."""

    def __init__(self):
        self.registry = PackageRegistry()
        self.db       = PackageDB()
        self._pip     = PypiHelper()

    # ── Core operations ────────────────────────────────────────────────────

    def install(self, name: str,
                progress: Callable[[str], None] | None = None) -> InstallResult:
        t0   = time.monotonic()
        msgs : list[str] = []

        def emit(msg: str) -> None:
            msgs.append(msg)
            if progress:
                progress(msg)
            logger.info(f"bpkg install {name}: {msg}")

        pkg = self.registry.get(name)
        if not pkg:
            emit(f"Package '{name}' not found in registry")
            return InstallResult(False, name, msgs, time.monotonic() - t0)

        if self.db.is_installed(name):
            emit(f"'{name}' is already installed")
            return InstallResult(True, name, msgs, time.monotonic() - t0)

        # Install bpkg deps first
        for dep in pkg.bpkg_deps:
            if not self.db.is_installed(dep):
                emit(f"Installing bpkg dependency: {dep}")
                result = self.install(dep, progress)
                if not result.success:
                    emit(f"Failed to install dependency: {dep}")
                    return InstallResult(False, name, msgs, time.monotonic() - t0)

        # Install pip deps (with optional version pins)
        if pkg.pip_deps:
            emit(f"Installing pip packages: {', '.join(pkg.pip_deps)}")
            ok = self._pip.install(pkg.pip_deps, pkg.pip_versions, emit)
            if not ok:
                emit(f"pip install failed for {name}")
                return InstallResult(False, name, msgs, time.monotonic() - t0)

        # Run install script if any
        if pkg.install_script:
            emit("Running post-install script…")
            rc = os.system(pkg.install_script)
            if rc != 0:
                emit(f"Post-install script exited with code {rc}")

        self.db.mark_installed(pkg)
        emit(f"✓  {name} v{pkg.version} installed successfully")
        return InstallResult(True, name, msgs, time.monotonic() - t0)

    def remove(self, name: str,
               progress: Callable[[str], None] | None = None) -> InstallResult:
        t0   = time.monotonic()
        msgs : list[str] = []

        def emit(msg: str) -> None:
            msgs.append(msg)
            if progress: progress(msg)

        if not self.db.is_installed(name):
            emit(f"'{name}' is not installed")
            return InstallResult(False, name, msgs, time.monotonic() - t0)

        ip = self.db.get(name)
        if ip and ip.pip_deps:
            emit(f"Uninstalling pip packages: {', '.join(ip.pip_deps)}")
            self._pip.uninstall(ip.pip_deps, emit)

        self.db.mark_removed(name)
        emit(f"✓  {name} removed")
        return InstallResult(True, name, msgs, time.monotonic() - t0)

    def upgrade(self, name: str,
                progress: Callable[[str], None] | None = None) -> InstallResult:
        """Reinstall to get latest version."""
        if self.db.is_installed(name):
            self.remove(name, progress)
        return self.install(name, progress)

    def upgrade_all(self,
                    progress: Callable[[str], None] | None = None) -> list[InstallResult]:
        installed = [ip.name for ip in self.db.list_installed()]
        return [self.upgrade(name, progress) for name in installed]

    # ── Query operations ───────────────────────────────────────────────────

    def search(self, query: str) -> list[Package]:
        return self.registry.search(query)

    def list_installed(self) -> list[InstalledPackage]:
        return self.db.list_installed()

    def list_available(self) -> list[Package]:
        installed = {ip.name for ip in self.db.list_installed()}
        return [p for p in self.registry.all_packages()
                if p.name not in installed]

    def info(self, name: str) -> Package | None:
        return self.registry.get(name)

    def is_installed(self, name: str) -> bool:
        return self.db.is_installed(name)

    def pip_status(self) -> dict[str, bool]:
        """Check which pip packages from installed bpkg packages are actually present."""
        result = {}
        for ip in self.db.list_installed():
            for dep in ip.pip_deps:
                result[dep] = PypiHelper.is_installed(dep)
        return result

    # ── Manifest / publish ──────────────────────────────────────────────────

    @staticmethod
    def generate_manifest(name: str, path: str = ".") -> dict:
        """Generate a package manifest from a directory.
        Scans the directory for hints (a ``bpkg.json`` if it exists, or
        tries to infer fields from ``setup.py`` / ``pyproject.toml``)."""
        manifest: dict = {
            "name": name, "version": "0.1.0", "description": "",
            "author": "", "category": "app",
            "pip_deps": [], "pip_versions": {}, "bpkg_deps": [],
            "install_script": "", "homepage": "", "license": "MIT",
            "size_kb": 0, "tags": [],
        }
        bpkg_json = os.path.join(path, "bpkg.json")
        if os.path.exists(bpkg_json):
            try:
                with open(bpkg_json) as f:
                    manifest.update(json.load(f))
                return manifest
            except Exception as e:
                logger.warning("Failed to load bpkg.json: %s", e)

        pyproject = os.path.join(path, "pyproject.toml")
        if os.path.exists(pyproject):
            try:
                with open(pyproject) as f:
                    text = f.read()
                m = re.search(r'name\s*=\s*"([^"]+)"', text)
                if m: manifest["name"] = m.group(1)
                m = re.search(r'version\s*=\s*"([^"]+)"', text)
                if m: manifest["version"] = m.group(1)
                m = re.search(r'description\s*=\s*"([^"]+)"', text)
                if m: manifest["description"] = m.group(1)
            except Exception:
                pass

        setup_py = os.path.join(path, "setup.py")
        if os.path.exists(setup_py):
            try:
                with open(setup_py) as f:
                    text = f.read()
                m = re.search(r"""version\s*=\s*['\"]([^'\"]+)['\"]""", text)
                if m: manifest["version"] = m.group(1)
                m = re.search(r"""description\s*=\s*['\"]([^'\"]+)['\"]""", text)
                if m: manifest["description"] = m.group(1)
                m = re.search(r"""author\s*=\s*['\"]([^'\"]+)['\"]""", text)
                if m: manifest["author"] = m.group(1)
            except Exception:
                pass

        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    stat = os.stat(fp)
                    if not fn.startswith("."):
                        total += stat.st_size
                except Exception:
                    pass
        manifest["size_kb"] = total // 1024
        return manifest

    def publish(self, name: str, path: str = ".",
                progress: Callable[[str], None] | None = None) -> InstallResult:
        """Create a manifest for *path* and 'publish' it — write to local
        registry cache so it's available for install.  In a real setup this
        would submit to GitHub / a remote registry."""
        t0 = time.monotonic()
        msgs: list[str] = []

        def emit(msg: str) -> None:
            msgs.append(msg)
            if progress:
                progress(msg)

        manifest = self.generate_manifest(name, path)
        pkg = Package.from_dict(manifest)

        if self.registry.get(pkg.name):
            emit(f"Package '{pkg.name}' already exists in registry — use a different name")
            return InstallResult(False, name, msgs, time.monotonic() - t0)

        # Add to registry in-memory and persist to local cache
        self.registry._packages[pkg.name] = pkg
        try:
            import json
            cache_dir = os.path.dirname(self.registry.CACHE_PATH)
            os.makedirs(cache_dir, exist_ok=True)
            existing = []
            if os.path.exists(self.registry.CACHE_PATH):
                with open(self.registry.CACHE_PATH) as f:
                    existing = json.load(f).get("packages", [])
            existing.append(pkg.to_dict())
            with open(self.registry.CACHE_PATH, "w") as f:
                json.dump({"packages": existing}, f, indent=2)
            emit(f"✓  Published '{pkg.name}' v{pkg.version} to local registry")
        except Exception as e:
            emit(f"Failed to persist registry: {e}")
            return InstallResult(False, name, msgs, time.monotonic() - t0)

        return InstallResult(True, name, msgs, time.monotonic() - t0)

    # ── Community submission ───────────────────────────────────────────────

    COMMUNITY_REPO = "brados-os/community-packages"
    SUBMISSIONS_DIR = os.path.join("brados_files", "bpkg", "submissions")

    def submit_to_community(self, name: str, path: str = ".",
                            progress: Callable[[str], None] | None = None) -> InstallResult:
        """Generate a manifest for *path* and submit it to the community
        package repository.

        If ``GITHUB_TOKEN`` is set in the environment, the method will
        attempt to create a pull request on GitHub.  Otherwise the
        manifest is saved locally for manual submission."""
        t0 = time.monotonic()
        msgs: list[str] = []

        def emit(msg: str) -> None:
            msgs.append(msg)
            if progress:
                progress(msg)

        manifest = self.generate_manifest(name, path)

        # Save submission file locally
        os.makedirs(self.SUBMISSIONS_DIR, exist_ok=True)
        dest = os.path.join(self.SUBMISSIONS_DIR, f"{name}.json")
        try:
            with open(dest, "w") as f:
                json.dump(manifest, f, indent=2)
            emit(f"✓  Manifest saved to {dest}")
        except Exception as e:
            emit(f"Failed to save manifest: {e}")
            return InstallResult(False, name, msgs, time.monotonic() - t0)

        # Try GitHub API if token is available
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            emit("Submitting to GitHub…")
            try:
                self._github_submit(name, manifest, token, emit)
                emit(f"✓  PR created — visit https://github.com/{self.COMMUNITY_REPO}/pulls")
            except Exception as e:
                emit(f"GitHub submission failed: {e}")
                emit(f"Manual submission: create a PR at "
                     f"https://github.com/{self.COMMUNITY_REPO}")
                emit(f"  with the file packages/{name}.json")
        else:
            emit("No GITHUB_TOKEN in environment.")
            emit(f"To submit manually:")
            emit(f"  1. Fork https://github.com/{self.COMMUNITY_REPO}")
            emit(f"  2. Copy {dest} to packages/{name}.json")
            emit(f"  3. Send a pull request")
            emit(f"\nOr set GITHUB_TOKEN and run again for automatic PR creation.")

        return InstallResult(True, name, msgs, time.monotonic() - t0)

    def _github_submit(self, name: str, manifest: dict,
                       token: str, emit: Callable[[str], None]) -> None:
        from urllib.request import Request, urlopen, HTTPSHandler, build_opener
        import base64

        api = f"https://api.github.com"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "BradOS-bpkg/1.0",
        }
        opener = build_opener(HTTPSHandler)

        content = json.dumps(manifest, indent=2)
        content_bytes = content.encode()
        encoded = base64.b64encode(content_bytes).decode()

        branch = f"bpkg-submit-{name}-{int(time.time())}"
        path = f"packages/{name}.json"

        # 1. Get default branch SHA
        req = Request(f"{api}/repos/{self.COMMUNITY_REPO}/git/refs/heads/main",
                      headers=headers)
        resp = opener.open(req)
        main_data = json.loads(resp.read())
        main_sha = main_data["object"]["sha"]

        # 2. Create a new branch
        req = Request(f"{api}/repos/{self.COMMUNITY_REPO}/git/refs",
                      data=json.dumps({"ref": f"refs/heads/{branch}",
                                       "sha": main_sha}).encode(),
                      headers=headers, method="POST")
        resp = opener.open(req)
        emit(f"  Branch created: {branch}")

        # 3. Create the file
        req = Request(f"{api}/repos/{self.COMMUNITY_REPO}/contents/{path}",
                      data=json.dumps({
                          "message": f"bpkg: submit {name} v{manifest.get('version','0.1.0')}",
                          "content": encoded,
                          "branch": branch,
                      }).encode(),
                      headers=headers, method="PUT")
        resp = opener.open(req)
        emit(f"  File created: {path}")

        # 4. Create PR
        pr_body = (
            f"## Package Submission\n\n"
            f"**Name:** {name}\n"
            f"**Version:** {manifest.get('version', '0.1.0')}\n"
            f"**Description:** {manifest.get('description', '')}\n"
            f"**Author:** {manifest.get('author', '')}\n"
            f"**Category:** {manifest.get('category', 'app')}\n\n"
            f"This PR was generated automatically by `bpkg submit`."
        )
        req = Request(f"{api}/repos/{self.COMMUNITY_REPO}/pulls",
                      data=json.dumps({
                          "title": f"bpkg: submit {name} {manifest.get('version','0.1.0')}",
                          "head": branch,
                          "base": "main",
                          "body": pr_body,
                      }).encode(),
                      headers=headers, method="POST")
        resp = opener.open(req)
        pr_data = json.loads(resp.read())
        emit(f"  PR #{pr_data['number']} created")

    # ── CLI interface (classic mode) ───────────────────────────────────────

    def cli(self, args: list[str]) -> int:
        """Entry point for classic-mode bpkg command.
        Returns exit code."""
        if not args:
            self._print_help()
            return 0

        cmd = args[0].lower()

        if cmd == "install" and len(args) > 1:
            for name in args[1:]:
                result = self.install(name, progress=print)
                if not result.success:
                    return 1
            return 0

        if cmd == "remove" and len(args) > 1:
            for name in args[1:]:
                result = self.remove(name, progress=print)
                if not result.success:
                    return 1
            return 0

        if cmd == "list":
            installed = self.list_installed()
            if not installed:
                print("No packages installed.")
                return 0
            print(f"{'Package':<24} {'Version':<12} {'Installed'}")
            print("─" * 55)
            for ip in installed:
                print(f"{ip.name:<24} {ip.version:<12} {ip.installed_at[:10]}")
            return 0

        if cmd == "available":
            pkgs = self.list_available()
            print(f"{'Package':<24} {'Version':<10} {'Description'}")
            print("─" * 70)
            for p in pkgs:
                print(f"{p.name:<24} {p.version:<10} {p.description[:36]}")
            return 0

        if cmd == "search" and len(args) > 1:
            results = self.search(" ".join(args[1:]))
            if not results:
                print(f"No packages found matching '{' '.join(args[1:])}'")
                return 0
            for p in results:
                mark = "[installed]" if self.is_installed(p.name) else ""
                print(f"  {p.name:<24} {p.version:<10} {p.description[:32]} {mark}")
            return 0

        if cmd == "info" and len(args) > 1:
            pkg = self.info(args[1])
            if not pkg:
                print(f"Package '{args[1]}' not found")
                return 1
            print(f"Name:        {pkg.name}")
            print(f"Version:     {pkg.version}")
            print(f"Description: {pkg.description}")
            print(f"Author:      {pkg.author}")
            print(f"Category:    {pkg.category}")
            print(f"pip deps:    {', '.join(pkg.pip_deps) or '—'}")
            vp = pkg.pip_versions
            if vp:
                print(f"versions:    {', '.join(f'{k} {v}' for k, v in vp.items())}")
            print(f"Tags:        {', '.join(pkg.tags) or '—'}")
            print(f"Installed:   {'yes' if self.is_installed(pkg.name) else 'no'}")
            return 0

        if cmd == "upgrade":
            if len(args) > 1:
                self.upgrade(args[1], progress=print)
            else:
                self.upgrade_all(progress=print)
            return 0

        if cmd == "update":
            print("Fetching remote registry…")
            ok = self.registry.fetch_remote(progress=print)
            return 0 if ok else 1

        if cmd == "status":
            status = self.pip_status()
            for dep, ok in status.items():
                mark = "✓" if ok else "✗"
                print(f"  {mark}  {dep}")
            return 0

        if cmd == "manifest" and len(args) > 1:
            path = args[2] if len(args) > 2 else "."
            manifest = self.generate_manifest(args[1], path)
            print(json.dumps(manifest, indent=2))
            return 0

        if cmd == "publish" and len(args) > 1:
            path = args[2] if len(args) > 2 else "."
            result = self.publish(args[1], path, progress=print)
            return 0 if result.success else 1

        if cmd == "submit" and len(args) > 1:
            path = args[2] if len(args) > 2 else "."
            result = self.submit_to_community(args[1], path, progress=print)
            return 0 if result.success else 1

        print(f"Unknown command: {cmd}")
        self._print_help()
        return 1

    @staticmethod
    def _print_help() -> None:
        print("""bpkg — BradOS Package Manager

Usage: bpkg <command> [args]

Commands:
  install <name>    Install a package and its pip dependencies
  remove <name>     Uninstall a package
  upgrade [name]    Upgrade one package or all if no name given
  list              List installed packages
  available         List available packages
  search <query>    Search packages by name/tag/description
  info <name>       Show package details
  update            Refresh remote registry cache
  status            Check pip dep availability for installed packages
  manifest <name>   Generate a package manifest from a directory
  publish <name>    Publish a package to the local registry
  submit <name>     Submit a package to the community repository
""")


# ── Module-level singleton ─────────────────────────────────────────────────

_bpkg: BpkgManager | None = None


def get_bpkg() -> BpkgManager:
    global _bpkg
    if _bpkg is None:
        _bpkg = BpkgManager()
    return _bpkg

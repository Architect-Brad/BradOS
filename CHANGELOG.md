# Changelog

All notable changes to BradOS are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [3.1.1] - 2026-07-26

### Added
- **PKG_INSTALL capability** (`Cap.PKG_INSTALL`, bit 9): `bpkg install` and `bpkg remove` now require this capability when BradSec is attached. Included in `default_user()`, excluded from `default_guest()`.
- `BpkgManager.set_sec(pid, sec)` wires capability gate; standalone mode (no sec) allows all operations.
- Remote package registry at [Architect-Brad/registry](https://github.com/Architect-Brad/registry) with `index.json`, contribution guide, and trust model docs.
- **VFS persistence**: `MemFSDriver.snapshot(path)` / `restore(path)` serialize the in-memory tree to JSON (with base64 for binary data). Root `/` snapshot auto-saved on shutdown and restored on boot via `BradOSShell.on_exit` / `on_mount`.
- `VirtualFileSystem.snapshot(path, mount)` / `restore(path, mount)` convenience methods.
- `create_default_vfs(..., snapshot_path=)` parameter for snapshot restore on boot.
- 3 new tests for snapshot roundtrip, binary data, and bad-mount rejection (183 total).

### Changed
- `MemFSDriver` docstring updated to describe persistence capability.
- `BradOSShell.on_mount()` now passes `snapshot_path` to `create_default_vfs`.
- `BradOSShell.on_exit()` persists root `/` snapshot to `brados_files/root_snapshot.json`.

## [3.1.0] - 2026-07-26

### Security
- **Constant-time password check**: `verify_password()` now uses `hmac.compare_digest` to prevent timing side-channel attacks.
- **Auth rate limiting**: `authenticate()` limits to 5 failed attempts per 30 seconds per username via `_track_auth_failure()`. Account lockout is logged to audit.
- **inotify detection fix**: `_HAS_INOTIFY` now probes libc via ctypes instead of the broken `hasattr(os, "inotify")` check, preventing silent inotify failures.
- **Vault XOR warning**: `EncryptedVault` XOR fallback now emits `warnings.warn()` plus audit log entries when `cryptography` is not installed.

### BradBrowse v2
- Rich HTML-to-markdown renderer (`html_to_rich`) with bold headings, hyperlinks, lists, blockquotes, and code blocks.
- Readability-style article extraction (`extract_article`) by text density scoring.
- Numbered link navigation — press number keys to open links.
- Per-tab history with `Alt+Left/Right` navigation.
- In-page search with `/pattern` or `Ctrl+F`.
- Carbonyl terminal browser integration via `_CarbonylScreen`.
- Auto-install of `brad-carbonyl` from BPKG registry on first use.
- `browse` and `browse --full` commands in Brash shell.

### Added
- `extract_links()` helper for extracting clickable links from HTML.
- `brad-carbonyl` v0.0.3 registered in `BUILTIN_REGISTRY`.
- Stock ambient music downloaded via `yt-dlp` to `~/Music/ambient_stock.mp3`.

### Fixed
- Brash `browse` command rewritten with numbered link navigation.
- Desktop `BrowserScreen` uses `html_to_rich` for proper link rendering.

## [3.0.0] - 2026-07-25

### Added
- Capability-based security model with per-process tokens (BradSec).
- Kernel task scheduler with cooperative multitasking.
- Process manager for subprocess lifecycle management.
- Mesh networking for inter-device communication.
- Package manager (BPKG) with build recipes for popular tools.
- Encrypted vault for secrets storage.
- File integrity monitoring with inotify.
- 60-second headless demo mode (`--demo`).
- SECURITY.md and CONTRIBUTING.md documentation.

### Changed
- Full Textual desktop rewrite with One UI-style app grid and bottom navigation.
- Mobile on-screen controls for calculator and games.
- Soft keyboard support for mobile input.

## [2.0.0] - 2026-07-24

### Added
- Initial BradOS with VFS, 6 driver types, and Brash shell.
- Music player with LRC lyrics, queue, and library scanning.
- Theme system with ocean_dark, forest, and solarized variants.

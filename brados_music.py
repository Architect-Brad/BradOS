# brados_music.py — BradMusic: terminal music player for BradOS
# Inspired by rmpc (Rust MPD client) and kew (terminal music player)
# Features: ffplay/mpv playback, mutagen tags, Kitty album art, LRC lyrics

from __future__ import annotations

import asyncio
import base64
import json
import os
import re as re_module
import shutil
import signal
import subprocess
import threading
import time
import fnmatch
from pathlib import Path
from typing import Any, ClassVar
from functools import partial

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import (
    Button, Static, ListView, ListItem, Label, Input,
    Tabs, Tab, ContentSwitcher, RichLog,
)
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.binding import Binding
from textual import on, work
from textual.events import Key
from textual.css.query import NoMatches
from textual.message import Message
from textual.widget import Widget

# BradWindow features inlined to avoid circular import

try:
    import mutagen
    from mutagen import File as MutagenFile
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    from mutagen.oggvorbis import OggVorbis
    _HAS_MUTAGEN = True
except ImportError:
    _HAS_MUTAGEN = False

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_MUSIC_DIR = os.path.expanduser("~/Music")
SUPPORTED_EXTS = (".mp3", ".flac", ".m4a", ".ogg", ".wav", ".opus")
TERMUX_AUDIO = os.path.exists("/data/data/com.termux")

# ── Tag Reader ────────────────────────────────────────────────────────────────

class TagReader:
    """Read metadata from audio files via mutagen."""

    EXTS = {".mp3": MP3, ".flac": FLAC, ".m4a": MP4, ".ogg": OggVorbis, ".opus": OggVorbis}

    @staticmethod
    def read(path: str) -> dict[str, Any]:
        if not _HAS_MUTAGEN:
            return {"title": Path(path).stem, "artist": "Unknown", "album": "Unknown",
                    "track": 0, "year": 0, "genre": "", "duration": 0.0, "path": path,
                    "has_cover": False}
        try:
            f = MutagenFile(path)
            if f is None:
                raise ValueError("unsupported")
            info = {"title": str(f.get("title", [Path(path).stem])[0]) if f.get("title") else Path(path).stem,
                    "artist": str(f.get("artist", ["Unknown"])[0]) if f.get("artist") else "Unknown",
                    "album": str(f.get("album", ["Unknown"])[0]) if f.get("album") else "Unknown",
                    "track": int(f.get("tracknumber", [0])[0].split("/")[0]) if f.get("tracknumber") else 0,
                    "year": int(str(f.get("date", ["0"])[0])[:4]) if f.get("date") else 0,
                    "genre": str(f.get("genre", [""])[0]) if f.get("genre") else "",
                    "duration": float(f.info.length) if hasattr(f.info, "length") else 0.0,
                    "path": path,
                    "has_cover": False}
            if f.get("covr") and len(f.pictures) > 0:
                info["has_cover"] = True
            elif f.get("covr"):
                info["has_cover"] = True
            elif isinstance(f, MP4) and f.get("covr"):
                info["has_cover"] = True
            return info
        except Exception:
            return {"title": Path(path).stem, "artist": "Unknown", "album": "Unknown",
                    "track": 0, "year": 0, "genre": "", "duration": 0.0, "path": path,
                    "has_cover": False}

    @staticmethod
    def extract_cover(path: str) -> bytes | None:
        if not _HAS_MUTAGEN:
            return None
        try:
            f = MutagenFile(path)
            if f is None:
                return None
            if hasattr(f, "pictures") and f.pictures:
                return f.pictures[0].data
            if isinstance(f, MP4) and f.get("covr"):
                return bytes(f["covr"][0])
            return None
        except Exception:
            return None

# ── LRC Lyrics Parser ─────────────────────────────────────────────────────────

class LrcParser:
    """Parse .lrc synced lyrics files."""

    @staticmethod
    def parse(path: str) -> list[tuple[float, str]]:
        lines: list[tuple[float, str]] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if not line.startswith("["):
                        continue
                    parts = line.split("]")
                    ts_part = parts[0][1:]
                    text = "]".join(parts[1:]).strip()
                    try:
                        m, s = ts_part.split(":")
                        secs = int(m) * 60 + float(s)
                        lines.append((secs, text))
                    except ValueError:
                        continue
        except (FileNotFoundError, PermissionError):
            pass
        lines.sort(key=lambda x: x[0])
        return lines

    @staticmethod
    def find_lyrics_file(track_path: str, lyrics_dir: str | None = None) -> str | None:
        p = Path(track_path)
        lrc = p.with_suffix(".lrc")
        if lrc.exists():
            return str(lrc)
        if lyrics_dir:
            rel = p.relative_to(p.anchor) if p.is_absolute() else p
            alt = Path(lyrics_dir) / rel.with_suffix(".lrc").name
            if alt.exists():
                return str(alt)
            alt2 = Path(lyrics_dir) / f"{p.stem}.lrc"
            if alt2.exists():
                return str(alt2)
        return None

    @staticmethod
    def get_line(position: float, lyrics: list[tuple[float, str]]) -> str:
        if not lyrics:
            return ""
        current = ""
        for i, (ts, text) in enumerate(lyrics):
            if ts <= position:
                current = text
            else:
                break
        return current

    @staticmethod
    def get_lines_around(position: float, lyrics: list[tuple[float, str]], window: int = 5) -> list[tuple[float, str, bool]]:
        result: list[tuple[float, str, bool]] = []
        if not lyrics:
            return result
        idx = 0
        for i, (ts, _) in enumerate(lyrics):
            if ts <= position:
                idx = i
        start = max(0, idx - window)
        end = min(len(lyrics), idx + window + 1)
        for i in range(start, end):
            ts, text = lyrics[i]
            result.append((ts, text, i == idx))
        return result

# ── Album Art Renderer ────────────────────────────────────────────────────────

class AlbumArtRenderer:
    """Render album art via Kitty terminal graphics protocol.

    Falls back to text placeholder if protocol not supported.
    """

    _supports_kitty: bool | None = None

    @classmethod
    def detect(cls) -> bool:
        if cls._supports_kitty is not None:
            return cls._supports_kitty
        term = os.environ.get("TERM", "")
        cls._supports_kitty = "kitty" in term.lower() or os.environ.get("KITTY_WINDOW_ID") is not None
        return cls._supports_kitty

    @classmethod
    def kitty_escape(cls, data: bytes) -> str:
        b64 = base64.b64encode(data).decode()
        chunked = []
        for i in range(0, len(b64), 4096):
            chunked.append(b64[i:i + 4096])
        result = ""
        for i, chunk in enumerate(chunked):
            more = "1" if i < len(chunked) - 1 else "0"
            result += f"\x1b_Gm=1,a=T,f=100,m={more}\x1b\\{chunk}"
        result += "\x1b_Gm=0\x1b\\"
        return result

    @classmethod
    def render(cls, cover_data: bytes | None, width: int = 20, height: int = 10) -> str:
        if not cover_data:
            return cls._placeholder(width, height)
        if cls.detect():
            try:
                return cls.kitty_escape(cover_data)
            except Exception:
                pass
        return cls._placeholder(width, height)

    @classmethod
    def _placeholder(cls, width: int, height: int) -> str:
        lines = []
        top = "┌" + "─" * (width - 2) + "┐"
        mid = "│" + " " * (width - 2) + "│"
        label = "♫ Album Art"
        label_pad = width - 2 - len(label)
        label_line = "│" + " " * (label_pad // 2) + label + " " * (label_pad - label_pad // 2) + "│"
        bottom = "└" + "─" * (width - 2) + "┘"
        lines.append(top)
        lines.append(mid)
        lines.append(label_line)
        for _ in range(height - 5):
            lines.append(mid)
        lines.append(bottom)
        return "\n".join(lines)

# ── Music Engine ──────────────────────────────────────────────────────────────

class MusicEngine:
    """Audio playback engine.

    Backend detection: mpv > ffplay > ffmpeg (pulse) > wave (WAV-only fallback).
    Communicates with mpv via JSON IPC socket for precise control.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._ipc_socket: str = "/tmp/bradmusic-ipc.sock"
        self._backend = self._detect_backend()
        self._paused = False
        self._volume = 75
        self._current_path: str | None = None
        self._start_time: float = 0.0
        self._pause_time: float = 0.0
        self._elapsed_before_pause: float = 0.0
        self._duration: float = 0.0
        self._on_track_end: callable | None = None

    def _detect_backend(self) -> str:
        if shutil.which("mpv"):
            return "mpv"
        if shutil.which("ffplay"):
            return "ffplay"
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        return "wave"

    def backend_name(self) -> str:
        return self._backend

    def set_on_track_end(self, cb: callable) -> None:
        self._on_track_end = cb

    def play(self, path: str, duration: float = 0.0) -> None:
        self.stop()
        self._current_path = path
        self._duration = duration
        self._paused = False
        self._start_time = time.time()
        self._elapsed_before_pause = 0.0

        if self._backend == "mpv":
            self._play_mpv(path)
        elif self._backend == "ffplay":
            self._play_ffplay(path)
        elif self._backend == "ffmpeg":
            self._play_ffmpeg(path)
        else:
            self._play_wave(path)

    def _play_mpv(self, path: str) -> None:
        try:
            self._cleanup_socket()
            self._process = subprocess.Popen(
                ["mpv", "--no-video", "--audio-display=no",
                 f"--input-ipc-server={self._ipc_socket}",
                 "--term-status-msg=",
                 "--no-terminal", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._backend = "ffplay"
            self._play_ffplay(path)

    def _play_ffplay(self, path: str) -> None:
        vol = max(0, min(100, self._volume))
        try:
            self._process = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit",
                 f"-volume={vol}", path],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self._backend = "wave"
            self._play_wave(path)

    def _play_ffmpeg(self, path: str) -> None:
        try:
            self._process = subprocess.Popen(
                ["ffmpeg", "-i", path, "-f", "pulse", "default",
                 "-loglevel", "error", "-stats"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self._backend = "wave"
            self._play_wave(path)

    def _play_wave(self, path: str) -> None:
        import wave
        try:
            with wave.open(path, "r") as wf:
                self._duration = wf.getnframes() / wf.getframerate()
        except Exception:
            self._duration = 0.0

        async def _run():
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", self._WAVE_PLAYER_SCRIPT(path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._process = proc
            await proc.wait()
            if self._on_track_end:
                self._on_track_end()

        asyncio.ensure_future(_run())

    _WAVE_PLAYER_SCRIPT = """import sys, wave, asyncio, struct
try:
    import pyaudio
    wf = wave.open(sys.argv[1], 'rb')
    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True)
    data = wf.readframes(1024)
    while data:
        stream.write(data)
        data = wf.readframes(1024)
    stream.close(); p.terminate()
except Exception:
    pass
"""

    def pause(self) -> None:
        if self._paused or not self._process:
            return
        self._paused = True
        self._pause_time = time.time()
        self._elapsed_before_pause = self.position()
        if self._backend == "mpv":
            self._mpv_command(["set", "pause", "yes"])
        elif self._backend in ("ffplay", "ffmpeg") and self._process:
            try:
                if self._backend == "ffplay" and self._process.stdin:
                    self._process.stdin.write(b"p\n")
                    self._process.stdin.flush()
                else:
                    self._process.send_signal(signal.SIGSTOP)
            except OSError:
                pass

    def resume(self) -> None:
        if not self._paused or not self._process:
            return
        self._paused = False
        self._start_time = time.time()
        if self._backend == "mpv":
            self._mpv_command(["set", "pause", "no"])
        elif self._backend in ("ffplay", "ffmpeg") and self._process:
            try:
                if self._backend == "ffplay" and self._process.stdin:
                    self._process.stdin.write(b"p\n")
                    self._process.stdin.flush()
                else:
                    self._process.send_signal(signal.SIGCONT)
            except OSError:
                pass

    def toggle_pause(self) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause()

    def stop(self) -> None:
        if self._process:
            try:
                if self._backend == "mpv":
                    self._mpv_command(["quit"])
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._current_path = None
        self._paused = False
        self._elapsed_before_pause = 0.0
        self._cleanup_socket()

    def seek(self, seconds: float) -> None:
        if self._backend == "mpv" and self._process:
            self._mpv_command(["set", "time-pos", str(seconds)])
        elif self._backend == "ffplay" and self._process and self._process.stdin:
            try:
                key = b"right" if seconds > 0 else b"left"
                self._process.stdin.write(key + b"\n")
                self._process.stdin.flush()
            except OSError:
                pass
        elif self._backend == "ffmpeg" and self._process:
            pass
        if self._paused:
            self._elapsed_before_pause = seconds
        else:
            self._start_time = time.time() - seconds

    def volume(self, level: int | None = None) -> int:
        if level is not None:
            self._volume = max(0, min(100, level))
            if self._backend == "mpv":
                self._mpv_command(["set", "volume", str(self._volume)])
            elif self._backend == "ffplay" and self._process and self._process.stdin:
                try:
                    if self._volume > 50:
                        for _ in range(self._volume - 50):
                            self._process.stdin.write(b"0\n")
                    else:
                        for _ in range(50 - self._volume):
                            self._process.stdin.write(b"9\n")
                    self._process.stdin.flush()
                except OSError:
                    pass
        return self._volume

    def position(self) -> float:
        if not self._process or not self._current_path:
            return 0.0
        if self._backend == "mpv":
            resp = self._mpv_command(["get_property", "time-pos"])
            if resp:
                try:
                    data = json.loads(resp)
                    if "data" in data and data["data"] is not None:
                        return float(data["data"])
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        if self._paused:
            return self._elapsed_before_pause
        return time.time() - self._start_time + self._elapsed_before_pause

    def duration(self) -> float:
        if self._duration > 0:
            return self._duration
        if self._backend == "mpv" and self._process:
            resp = self._mpv_command(["get_property", "duration"])
            if resp:
                try:
                    data = json.loads(resp)
                    if "data" in data and data["data"] is not None:
                        self._duration = float(data["data"])
                        return self._duration
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        return self._duration

    def is_playing(self) -> bool:
        return self._process is not None and self._process.poll() is None and not self._paused

    def is_paused(self) -> bool:
        return self._paused

    def current_path(self) -> str | None:
        return self._current_path

    def _mpv_command(self, cmd: list[str]) -> str | None:
        import socket
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(self._ipc_socket)
            payload = json.dumps({"command": cmd}) + "\n"
            s.sendall(payload.encode())
            resp = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in chunk:
                        break
            except socket.timeout:
                pass
            s.close()
            return resp.decode()
        except (FileNotFoundError, ConnectionRefusedError, OSError, socket.timeout):
            return None

    def _cleanup_socket(self) -> None:
        try:
            if os.path.exists(self._ipc_socket):
                os.unlink(self._ipc_socket)
        except OSError:
            pass

    def shutdown(self) -> None:
        self.stop()

# ── Music Library ─────────────────────────────────────────────────────────────

class MusicLibrary:
    """Scan and index music files from a directory."""

    def __init__(self, music_dir: str = DEFAULT_MUSIC_DIR) -> None:
        self.music_dir = music_dir
        self._tracks: list[dict[str, Any]] = []
        self._loaded = False
        self._tag_reader = TagReader()

    def scan(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self._tracks = []
        base = Path(self.music_dir)
        if not base.exists():
            self._loaded = True
            return
        for root, _dirs, files in os.walk(base):
            for fname in sorted(files):
                if fname.lower().endswith(SUPPORTED_EXTS):
                    fpath = os.path.join(root, fname)
                    tags = self._tag_reader.read(fpath)
                    self._tracks.append(tags)
        self._loaded = True

    @property
    def tracks(self) -> list[dict[str, Any]]:
        return self._tracks

    def search(self, query: str) -> list[dict[str, Any]]:
        if not query:
            return self._tracks
        q = query.lower()
        return [t for t in self._tracks
                if q in t["title"].lower()
                or q in t["artist"].lower()
                or q in t["album"].lower()
                or q in t["genre"].lower()]

    def artists(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for t in self._tracks:
            a = t["artist"]
            if a and a not in seen:
                seen.add(a)
                result.append(a)
        return sorted(result)

    def albums(self, artist: str | None = None) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for t in self._tracks:
            if artist and t["artist"] != artist:
                continue
            a = t["album"]
            if a and a not in seen:
                seen.add(a)
                result.append(a)
        return sorted(result)

    def tracks_for_album(self, artist: str, album: str) -> list[dict[str, Any]]:
        return [t for t in self._tracks
                if t["artist"] == artist and t["album"] == album]

    def tracks_for_artist(self, artist: str) -> list[dict[str, Any]]:
        return [t for t in self._tracks if t["artist"] == artist]

    def count(self) -> int:
        return len(self._tracks)

# ── Play Queue ────────────────────────────────────────────────────────────────

class PlayQueue:
    """Simple play queue with repeat/shuffle support."""

    def __init__(self) -> None:
        self._tracks: list[dict[str, Any]] = []
        self._index: int = -1
        self._shuffle = False
        self._repeat = False
        self._original_order: list[int] = []
        self._history: list[int] = []

    def load(self, tracks: list[dict[str, Any]], start_index: int = 0) -> None:
        self._tracks = list(tracks)
        self._original_order = list(range(len(self._tracks)))
        self._index = start_index if self._tracks else -1
        self._history = []

    def add(self, track: dict[str, Any]) -> None:
        self._tracks.append(track)
        self._original_order.append(len(self._tracks) - 1)

    def remove(self, index: int) -> None:
        if 0 <= index < len(self._tracks):
            self._tracks.pop(index)
            if self._index >= index:
                self._index = max(-1, self._index - 1)

    def clear(self) -> None:
        self._tracks.clear()
        self._index = -1
        self._history.clear()

    @property
    def current(self) -> dict[str, Any] | None:
        if 0 <= self._index < len(self._tracks):
            return self._tracks[self._index]
        return None

    def next(self) -> dict[str, Any] | None:
        if not self._tracks:
            return None
        if self._shuffle:
            import random
            if self._history:
                self._history.append(self._index)
            candidates = [i for i in range(len(self._tracks)) if i != self._index]
            if candidates:
                self._index = random.choice(candidates)
                return self._tracks[self._index]
            return self.current
        if self._index < len(self._tracks) - 1:
            self._index += 1
            return self._tracks[self._index]
        if self._repeat:
            self._index = 0
            return self._tracks[self._index]
        return None

    def prev(self) -> dict[str, Any] | None:
        if not self._tracks:
            return None
        if self._shuffle and self._history:
            self._index = self._history.pop()
            return self._tracks[self._index]
        if self._index > 0:
            self._index -= 1
            return self._tracks[self._index]
        if self._repeat:
            self._index = len(self._tracks) - 1
            return self._tracks[self._index]
        return None

    def go_to(self, index: int) -> dict[str, Any] | None:
        if 0 <= index < len(self._tracks):
            self._index = index
            return self._tracks[self._index]
        return None

    def toggle_shuffle(self) -> bool:
        self._shuffle = not self._shuffle
        if not self._shuffle:
            self._history.clear()
        return self._shuffle

    def toggle_repeat(self) -> bool:
        self._repeat = not self._repeat
        return self._repeat

    @property
    def all_tracks(self) -> list[dict[str, Any]]:
        return list(self._tracks)

    @property
    def index(self) -> int:
        return self._index

# ── Music Downloader ──────────────────────────────────────────────────────────

class MusicDownloader:
    """Download music via yt-dlp subprocess."""

    _progress_re = re_module.compile(
        r"\[download\]\s+(\d+\.\d+)%\s+of\s+~?([\d.]+[KMG]?iB)\s+at\s+([\d.]+[KMG]?iB/s)\s+ETA\s+(\S+)"
    )

    def __init__(self, download_dir: str = DEFAULT_MUSIC_DIR) -> None:
        self.download_dir = download_dir
        self._process: subprocess.Popen | None = None
        self._progress_cb: callable | None = None
        self._done_cb: callable | None = None
        self._cancelled = False
        self._thread: threading.Thread | None = None
        os.makedirs(self.download_dir, exist_ok=True)

    def set_callbacks(self, on_progress: callable, on_done: callable) -> None:
        self._progress_cb = on_progress
        self._done_cb = on_done

    def start(self, url: str, fmt: str = "bestaudio") -> None:
        self.stop()
        self._cancelled = False
        output = os.path.join(self.download_dir, "%(title)s.%(ext)s")
        if fmt == "mp3":
            args = ["yt-dlp", "-x", "--audio-format", "mp3",
                    "--audio-quality", "0", "--embed-thumbnail",
                    "-o", output, "--newline", url]
        elif fmt == "m4a":
            args = ["yt-dlp", "-f", "140",
                    "-o", output.replace("%(ext)s", "m4a"),
                    "--newline", url]
        elif fmt == "opus":
            args = ["yt-dlp", "-f", "251",
                    "-o", output.replace("%(ext)s", "opus"),
                    "--newline", url]
        else:
            args = ["yt-dlp", "-f", "bestaudio",
                    "-o", output, "--newline", url]

        self._thread = threading.Thread(target=self._run, args=(args,), daemon=True)
        self._thread.start()

    def _run(self, args: list[str]) -> None:
        try:
            self._process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
            )
            for line in iter(self._process.stderr.readline, ""):
                if self._cancelled:
                    self._process.terminate()
                    break
                m = self._progress_re.search(line)
                if m:
                    pct, size, speed, eta = m.groups()
                    if self._progress_cb:
                        self._progress_cb(pct, size, speed, eta)
                if self._progress_cb:
                    stripped = line.rstrip()
                    if stripped:
                        self._progress_cb(None, None, None, None, stripped)

            self._process.wait()
            if self._done_cb:
                self._done_cb(self._process.returncode == 0 and not self._cancelled)
        except FileNotFoundError:
            if self._done_cb:
                self._done_cb(False)
        finally:
            self._process = None

    def stop(self) -> None:
        self._cancelled = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    @property
    def is_downloading(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# ── Custom Widget: Progress Bar ──────────────────────────────────────────────

class MusicProgressBar(Widget):
    """Custom progress bar for music playback."""

    def __init__(self, duration: float = 0.0, position: float = 0.0) -> None:
        super().__init__()
        self._duration = duration
        self._position = position

    def update(self, position: float, duration: float) -> None:
        self._position = position
        self._duration = duration
        self.refresh()

    def render(self) -> str:
        width = max(10, self.size.width - 20)
        if self._duration <= 0:
            filled = 0
        else:
            filled = int((self._position / self._duration) * width)
        filled = max(0, min(width, filled))
        empty = width - filled
        pos_str = f"{int(self._position // 60):02d}:{int(self._position % 60):02d}"
        dur_str = f"{int(self._duration // 60):02d}:{int(self._duration % 60):02d}"
        bar = "█" * filled + "░" * empty
        return f" {pos_str} {bar} {dur_str} "

# ── Main BradMusic Window ─────────────────────────────────────────────────────

class MusicPlayerWindow(Screen):
    """BradMusic — terminal music player for BradOS."""

    APP_ID: ClassVar[str] = "music"

    CSS = """
    #music-root { height: 100%; }
    #music-main { height: 1fr; }
    #music-art-panel { width: 28; padding: 1; border: solid #1e3a5f; margin: 1; }
    #music-art-box { height: 12; }
    .music-info { margin: 0 1; }
    #music-content { height: 1fr; }
    #music-controls { height: 3; padding: 0 1; align: center middle; }
    .ctrl-btn { min-width: 5; margin: 0 1; }
    .play-btn { min-width: 5; }
    #music-progress { height: 1; }
    #music-now-playing { width: 1fr; padding: 0 1; }
    #music-vol-label { padding: 0 1; }
    #music-backend { padding: 0 1; width: 8; color: #1e3a5f; }
    #music-search-input { margin: 1; }
    #music-artist-list, #music-album-list, #music-queue-list, #music-search-results { height: 1fr; }
    ListView { height: 1fr; }
    #panel-download { padding: 1; }
    #dl-url { margin: 0 0 1 0; }
    #dl-fmt-row { height: 3; align: center middle; }
    .dl-fmt-btn { margin: 0 1; min-width: 12; }
    #dl-status { height: 1; margin: 1 0; }
    #dl-log { height: 1fr; border: solid #1e3a5f; }
    """

    BINDINGS: ClassVar = [
        Binding("space", "toggle_play", "Play/Pause"),
        Binding("p", "toggle_play"),
        Binding("n", "next_track", "Next"),
        Binding("period", "next_track"),
        Binding("b", "prev_track", "Prev"),
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss"),
        Binding("up", "focus_nav", "Up"),
        Binding("down", "focus_nav", "Down"),
        Binding("s", "focus_search", "Search"),
        Binding("slash", "focus_search"),
        Binding("plus", "vol_up", "Vol+"),
        Binding("minus", "vol_down", "Vol-"),
        Binding("r", "toggle_repeat", "Repeat"),
        Binding("z", "toggle_shuffle", "Shuffle"),
        Binding("l", "focus_lyrics", "Lyrics"),
        Binding("h", "focus_queue", "Queue"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._engine = MusicEngine()
        self._library = MusicLibrary()
        self._queue = PlayQueue()
        self._current_tab = "queue"
        self._lyrics_cache: dict[str, list[tuple[float, str]]] = {}
        self._lyrics_dir = os.path.expanduser("~/.lyrics")
        self._dl = MusicDownloader()
        self._dl.set_callbacks(self._dl_progress, self._dl_done)

    def compose(self) -> ComposeResult:
        with Vertical(id="music-root"):
            with Horizontal(classes="win-titlebar"):
                yield Static("♫  BradMusic", classes="win-title")
                yield Button("—", id="btn-min", classes="btn-min")
                yield Button("✕", id="btn-close", classes="win-close")

            with Horizontal(id="music-main"):
                with Vertical(id="music-art-panel"):
                    yield Static("", id="music-art-box")
                    yield Static("", id="music-now-title", classes="music-info")
                    yield Static("", id="music-now-artist", classes="music-info")
                    yield Static("", id="music-now-album", classes="music-info")
                    yield Static("", id="music-now-year", classes="music-info")

                with Vertical(id="music-content"):
                    yield Tabs(
                        Tab("Queue", id="tab-queue"),
                        Tab("Artists", id="tab-artists"),
                        Tab("Albums", id="tab-albums"),
                        Tab("Lyrics", id="tab-lyrics"),
                        Tab("Search", id="tab-search"),
                        Tab("Download", id="tab-download"),
                    )
                    with ContentSwitcher(id="music-switcher"):
                        with ScrollableContainer(id="panel-queue"):
                            yield ListView(id="music-queue-list")
                        with ScrollableContainer(id="panel-artists"):
                            yield ListView(id="music-artist-list")
                        with ScrollableContainer(id="panel-albums"):
                            yield ListView(id="music-album-list")
                        with ScrollableContainer(id="panel-lyrics"):
                            yield RichLog(id="music-lyrics-content", highlight=True, wrap=True)
                        with Vertical(id="panel-search"):
                            yield Input(placeholder="Search tracks...", id="music-search-input")
                            yield ListView(id="music-search-results")
                        with Vertical(id="panel-download"):
                            yield Input(placeholder="Paste URL (YouTube, SoundCloud, ...)", id="dl-url")
                            with Horizontal(id="dl-fmt-row"):
                                yield Button("Best Audio", id="dl-fmt-best", classes="dl-fmt-btn")
                                yield Button("MP3", id="dl-fmt-mp3", classes="dl-fmt-btn")
                                yield Button("M4A", id="dl-fmt-m4a", classes="dl-fmt-btn")
                                yield Button("Opus", id="dl-fmt-opus", classes="dl-fmt-btn")
                            yield Horizontal(
                                Button("⬇ Download", id="dl-start", variant="primary"),
                                Button("■ Cancel", id="dl-cancel"),
                            )
                            yield Static("", id="dl-status")
                            yield RichLog(id="dl-log", highlight=True, wrap=True, max_lines=50)

            with Horizontal(id="music-controls"):
                yield Static("", id="music-backend")
                yield Button("◄◄", id="btn-prev", classes="ctrl-btn")
                yield Button("▶", id="btn-play", classes="ctrl-btn play-btn")
                yield Button("►►", id="btn-next", classes="ctrl-btn")
                yield Button("■", id="btn-stop", classes="ctrl-btn")
                yield Button("🔀", id="btn-shuffle", classes="ctrl-btn")
                yield Button("🔁", id="btn-repeat", classes="ctrl-btn")
                yield Label(" Vol:", id="music-vol-label")
                yield Static("", id="music-now-playing", classes="now-playing")

            yield MusicProgressBar(id="music-progress")

    def action_dismiss(self) -> None:
        self._dl.stop()
        self._engine.shutdown()
        self.dismiss()

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.styles.animate("opacity", 1.0, duration=0.2)
        self._engine.set_on_track_end(self._on_track_end)
        self._scan_library()
        self._update_controls()
        self._update_progress_timer()

    def _scan_library(self) -> None:
        self._library.scan()
        tracks = self._library.tracks
        if tracks:
            self._queue.load(tracks)
        self._refresh_current_panel()

    # ── Tab switching ──────────────────────────────────────────────────────

    @on(Tabs.TabActivated)
    def _on_tab_change(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id or "queue"
        self._current_tab = tab_id.replace("tab-", "")
        self.query_one("#music-switcher", ContentSwitcher).current = f"panel-{self._current_tab}"
        self._refresh_current_panel()

    def _refresh_current_panel(self) -> None:
        handler = {
            "queue": self._refresh_queue,
            "artists": self._refresh_artists,
            "albums": self._refresh_albums,
            "lyrics": self._refresh_lyrics,
            "download": self._refresh_download,
        }
        handler.get(self._current_tab, lambda: None)()

    def _refresh_download(self) -> None:
        pass

    def _refresh_queue(self) -> None:
        lv = self.query_one("#music-queue-list", ListView)
        lv.clear()
        tracks = self._queue.all_tracks
        for i, t in enumerate(tracks):
            marker = "→ " if i == self._queue.index else "  "
            lbl = f"{marker}{t['title']} — {t['artist']}"
            lv.append(ListItem(Label(lbl)))

    def _refresh_artists(self) -> None:
        lv = self.query_one("#music-artist-list", ListView)
        lv.clear()
        for artist in self._library.artists():
            count = len(self._library.tracks_for_artist(artist))
            lv.append(ListItem(Label(f" {artist}  ({count})")))

    def _refresh_albums(self) -> None:
        lv = self.query_one("#music-album-list", ListView)
        lv.clear()
        for album in self._library.albums():
            lv.append(ListItem(Label(f" {album}")))

    def _refresh_lyrics(self) -> None:
        rl = self.query_one("#music-lyrics-content", RichLog)
        rl.clear()
        current = self._queue.current
        if not current:
            rl.write("[italic #7f8c8d]No track playing[/]")
            return
        lrc_path = LrcParser.find_lyrics_file(current["path"], self._lyrics_dir)
        if not lrc_path:
            rl.write("[italic #7f8c8d]No lyrics found[/]")
            return
        lyrics = LrcParser.parse(lrc_path)
        if not lyrics:
            rl.write("[italic #7f8c8d]No lyrics found[/]")
            return
        pos = self._engine.position()
        lines = LrcParser.get_lines_around(pos, lyrics, 8)
        for ts, text, is_current in lines:
            style = "bold #00d4ff" if is_current else "#7f8c8d"
            prefix = f"[{int(ts//60):02d}:{int(ts%60):02d}]"
            rl.write(f"[{style}]{prefix} {text}[/]")
        self.set_timer(1.0, self._refresh_lyrics)

    # ── Button handlers ────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-play")
    def _on_play_pause(self) -> None:
        if self._engine.is_playing():
            self._engine.pause()
        elif self._engine.is_paused():
            self._engine.resume()
        else:
            self._play_current()
        self._update_controls()

    @on(Button.Pressed, "#btn-next")
    def _on_next(self) -> None:
        self._next_track()

    @on(Button.Pressed, "#btn-prev")
    def _on_prev(self) -> None:
        track = self._queue.prev()
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._refresh_queue()

    @on(Button.Pressed, "#btn-stop")
    def _on_stop(self) -> None:
        self._engine.stop()
        self._update_controls()

    @on(Button.Pressed, "#btn-shuffle")
    def _on_shuffle(self) -> None:
        on = self._queue.toggle_shuffle()
        btn = self.query_one("#btn-shuffle", Button)
        btn.styles.color = "#00d4ff" if on else "#7f8c8d"
        self._update_controls()

    @on(Button.Pressed, "#btn-repeat")
    def _on_repeat(self) -> None:
        on = self._queue.toggle_repeat()
        btn = self.query_one("#btn-repeat", Button)
        btn.styles.color = "#00d4ff" if on else "#7f8c8d"
        self._update_controls()

    # ── Download handlers ───────────────────────────────────────────────────

    _dl_format: str = "bestaudio"

    @on(Button.Pressed, "#dl-fmt-best")
    def _dl_fmt_best(self) -> None:
        self._dl_format = "bestaudio"
        self._highlight_fmt("#dl-fmt-best")

    @on(Button.Pressed, "#dl-fmt-mp3")
    def _dl_fmt_mp3(self) -> None:
        self._dl_format = "mp3"
        self._highlight_fmt("#dl-fmt-mp3")

    @on(Button.Pressed, "#dl-fmt-m4a")
    def _dl_fmt_m4a(self) -> None:
        self._dl_format = "m4a"
        self._highlight_fmt("#dl-fmt-m4a")

    @on(Button.Pressed, "#dl-fmt-opus")
    def _dl_fmt_opus(self) -> None:
        self._dl_format = "opus"
        self._highlight_fmt("#dl-fmt-opus")

    def _highlight_fmt(self, active_id: str) -> None:
        for fid in ("#dl-fmt-best", "#dl-fmt-mp3", "#dl-fmt-m4a", "#dl-fmt-opus"):
            try:
                btn = self.query_one(fid, Button)
                btn.styles.background = "#00d4ff" if fid == active_id else "#1a2740"
            except NoMatches:
                pass

    @on(Button.Pressed, "#dl-start")
    def _dl_start(self) -> None:
        url = self.query_one("#dl-url", Input).value.strip()
        if not url:
            self.query_one("#dl-status", Static).update("[bold #ff4757]Enter a URL[/]")
            return
        if self._dl.is_downloading:
            self.query_one("#dl-status", Static).update("[bold #ffa502]Already downloading[/]")
            return
        self.query_one("#dl-status", Static).update(f"[bold #2ed573]Downloading...[/]")
        self.query_one("#dl-log", RichLog).clear()
        self._dl.start(url, self._dl_format)

    @on(Button.Pressed, "#dl-cancel")
    def _dl_cancel(self) -> None:
        self._dl.stop()
        self.query_one("#dl-status", Static).update("[bold #ff4757]Cancelled[/]")

    def _dl_progress(self, pct: str | None = None, size: str | None = None,
                     speed: str | None = None, eta: str | None = None,
                     raw: str | None = None) -> None:
        if raw:
            try:
                rl = self.query_one("#dl-log", RichLog)
                rl.write(f"[#7f8c8d]{raw}[/]")
            except NoMatches:
                pass
            return
        if pct and size:
            try:
                status = self.query_one("#dl-status", Static)
                status.update(f"[bold #2ed573]{pct}%[/] of {size}  at {speed}  ETA {eta}")
            except NoMatches:
                pass

    def _dl_done(self, success: bool) -> None:
        try:
            status = self.query_one("#dl-status", Static)
            if success:
                status.update("[bold #2ed573]Download complete! ✓[/]")
                self._library.scan(force=True)
            else:
                status.update("[bold #ff4757]Download failed[/]")
            self.query_one("#dl-log", RichLog).write(
                "[bold #00d4ff]─── Download finished ───[/]"
            )
        except NoMatches:
            pass

    @on(Button.Pressed, "#btn-close")
    def _on_close(self) -> None:
        self._dl.stop()
        self._engine.shutdown()
        self.dismiss()

    def dismiss(self, result=None) -> None:
        self.styles.animate("opacity", 0.0, duration=0.15)
        self.set_timer(0.18, lambda: self.dismiss_immediate())

    def dismiss_immediate(self) -> None:
        super().dismiss()

    @on(Button.Pressed, "#btn-min")
    def _do_minimize(self, event: Button.Pressed) -> None:
        event.stop()
        from brados_shell import MinimizeApp
        self.post_message(MinimizeApp(self.APP_ID))
        self.dismiss_immediate()

    # ── ListView item selection ────────────────────────────────────────────

    @on(ListView.Selected, "#music-artist-list")
    def _on_artist_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        label = event.item.query_one(Label)
        artist = label.renderable or ""
        artist = artist.split("  (")[0].strip()
        tracks = self._library.tracks_for_artist(artist)
        if tracks:
            self._queue.load(tracks)
            self._play_index(0)
            self._switch_tab("queue")

    @on(ListView.Selected, "#music-album-list") 
    def _on_album_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        label = event.item.query_one(Label)
        album = (label.renderable or "").strip()
        tracks = [t for t in self._library.tracks if t["album"] == album]
        if tracks:
            self._queue.load(tracks)
            self._play_index(0)
            self._switch_tab("queue")

    @on(ListView.Selected, "#music-queue-list")
    def _on_queue_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        lv = self.query_one("#music-queue-list", ListView)
        try:
            idx = lv.index
        except ValueError:
            return
        self._play_index(idx)

    @on(ListView.Selected, "#music-search-results")
    def _on_search_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        lv = self.query_one("#music-search-results", ListView)
        try:
            idx = lv.index
        except ValueError:
            return
        q = self.query_one("#music-search-input", Input).value
        results = self._library.search(q)
        if results and idx < len(results):
            self._queue.load(results, idx)
            self._play_index(0)
            self._switch_tab("queue")

    # ── Search ─────────────────────────────────────────────────────────────

    @on(Input.Submitted, "#music-search-input")
    @on(Input.Changed, "#music-search-input")
    def _on_search(self) -> None:
        q = self.query_one("#music-search-input", Input).value
        results = self._library.search(q)
        lv = self.query_one("#music-search-results", ListView)
        lv.clear()
        for t in results[:200]:
            lv.append(ListItem(Label(f"{t['title']} — {t['artist']}  [{t['album']}]")))

    # ── Playback ───────────────────────────────────────────────────────────

    def _play_current(self) -> None:
        track = self._queue.current
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._update_controls()

    def _play_index(self, idx: int) -> None:
        track = self._queue.go_to(idx)
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._refresh_queue()

    def _next_track(self) -> None:
        track = self._queue.next()
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._refresh_queue()
        else:
            self._engine.stop()
            self._update_controls()

    def _prev_track(self) -> None:
        track = self._queue.prev()
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._refresh_queue()

    def _on_track_end(self) -> None:
        self.call_from_thread(self._next_track)

    # ── UI updates ─────────────────────────────────────────────────────────

    def _update_now_playing(self, track: dict[str, Any]) -> None:
        try:
            self.query_one("#music-now-title", Static).update(f"[bold]{track['title']}[/]")
            self.query_one("#music-now-artist", Static).update(f"[#7f8c8d]{track['artist']}[/]")
            self.query_one("#music-now-album", Static).update(f"[#7f8c8d]{track['album']}[/]")
            year = track.get("year", 0)
            self.query_one("#music-now-year", Static).update(f"[#7f8c8d]{year or ''}[/]")
            now = self.query_one("#music-now-playing", Static)
            now.update(f"♫  {track['title']} — {track['artist']}")

            cover = TagReader.extract_cover(track["path"])
            art = AlbumArtRenderer.render(cover, width=24, height=8)
            self.query_one("#music-art-box", Static).update(art)
        except NoMatches:
            pass

    def _update_controls(self) -> None:
        try:
            btn = self.query_one("#btn-play", Button)
            if self._engine.is_playing():
                btn.label = "⏸"
            elif self._engine.is_paused():
                btn.label = "▶"
            else:
                btn.label = "▶"
            back = self.query_one("#music-backend", Static)
            back.update(f"[#1e3a5f]{self._engine.backend_name()}[/]")
        except NoMatches:
            pass

    def _update_progress_timer(self) -> None:
        self._update_progress()
        self.set_timer(1.0, self._update_progress_timer)

    def _update_progress(self) -> None:
        try:
            pos = self._engine.position()
            dur = self._engine.duration()
            pb = self.query_one("#music-progress", MusicProgressBar)
            pb.update(pos, dur)
        except NoMatches:
            pass

    def _switch_tab(self, tab_id: str) -> None:
        tabs = self.query_one(Tabs)
        for tab in tabs:
            if tab.id == f"tab-{tab_id}":
                tabs.active = tab.id
                break

    # ── Key bindings ───────────────────────────────────────────────────────

    def action_toggle_play(self) -> None:
        self._on_play_pause()

    def action_next_track(self) -> None:
        self._on_next()

    def action_prev_track(self) -> None:
        track = self._queue.prev()
        if track:
            self._engine.play(track["path"], track["duration"])
            self._update_now_playing(track)
            self._refresh_queue()

    def action_focus_search(self) -> None:
        self._switch_tab("search")
        self.query_one("#music-search-input", Input).focus()

    def action_focus_lyrics(self) -> None:
        self._switch_tab("lyrics")
        self._refresh_lyrics()

    def action_focus_queue(self) -> None:
        self._switch_tab("queue")
        self._refresh_queue()

    def action_toggle_repeat(self) -> None:
        self._on_repeat()

    def action_toggle_shuffle(self) -> None:
        self._on_shuffle()

    def action_vol_up(self) -> None:
         v = self._engine.volume()
         self._engine.volume(min(100, v + 5))

    def action_vol_down(self) -> None:
        v = self._engine.volume()
        self._engine.volume(max(0, v - 5))

    def action_focus_nav(self) -> None:
        tab_map = {
            "queue": "#music-queue-list",
            "artists": "#music-artist-list",
            "albums": "#music-album-list",
        }
        wid = tab_map.get(self._current_tab)
        if wid:
            try:
                self.query_one(wid).focus()
            except NoMatches:
                pass



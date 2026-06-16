# brados_mesh.py — BradOS Mesh: decentralized P2P networking
# Every BradOS instance is a peer. Discover. Connect. Share.
# No cloud. No central server. Just UDP broadcast + TCP.

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import secrets
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("brados.mesh")

MESH_DISCOVERY_PORT = 1985
MESH_DATA_PORT = 1986
BROADCAST_INTERVAL = 30
PEER_TIMEOUT = 180


@dataclass
class Peer:
    peer_id: str
    hostname: str
    ip: str
    port: int
    last_seen: float
    version: str = ""

    @property
    def alive(self) -> bool:
        return time.time() - self.last_seen < PEER_TIMEOUT


@dataclass
class MeshMessage:
    msg_type: str
    sender: str
    payload: dict
    timestamp: float


class MeshNode:
    """Mesh networking daemon — UDP discovery + TCP messaging."""

    def __init__(self, secret: str = "", peer_id: str = "", discovery_port: int = 0, data_port: int = 0):
        self._secret = secret or secrets.token_hex(16)
        self._peer_id = peer_id or secrets.token_hex(8)
        self._disc_port = discovery_port or MESH_DISCOVERY_PORT
        self._data_port = data_port or MESH_DATA_PORT
        self._hostname = socket.gethostname()
        self._running = False
        self._peers: dict[str, Peer] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def peers(self) -> list[Peer]:
        with self._lock:
            return [p for p in self._peers.values() if p.alive]

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        self._udp.bind(("0.0.0.0", self._disc_port))
        self._udp.settimeout(1.0)

        self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp.bind(("0.0.0.0", self._data_port))
        self._tcp.listen(5)
        self._tcp.settimeout(1.0)

        self._announce_thread = threading.Thread(target=self._announce_loop, daemon=True)
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._announce_thread.start()
        self._listen_thread.start()
        self._accept_thread.start()

        logger.info("Mesh: peer %s on %s", self._peer_id, self._hostname)

    def stop(self) -> None:
        self._running = False
        try:
            self._udp.close()
        except Exception:
            pass
        try:
            self._tcp.close()
        except Exception:
            pass
        time.sleep(0.3)

    def on(self, event: str, callback: Callable) -> None:
        self._callbacks.setdefault(event, []).append(callback)

    def send(self, peer: Peer, msg_type: str, payload: dict) -> bool:
        try:
            conn = socket.create_connection((peer.ip, peer.port), timeout=10)
            msg = json.dumps({
                "type": msg_type,
                "sender": self._peer_id,
                "payload": payload,
                "timestamp": time.time(),
            }).encode()
            conn.sendall(struct.pack("!I", len(msg)) + msg)
            conn.close()
            return True
        except Exception as e:
            logger.warning("Mesh send to %s failed: %s", peer.hostname, e)
            return False

    def broadcast(self, msg_type: str, payload: dict) -> int:
        sent = 0
        for p in self.peers:
            if self.send(p, msg_type, payload):
                sent += 1
        return sent

    def status(self) -> dict:
        return {
            "peer_id": self._peer_id,
            "hostname": self._hostname,
            "running": self._running,
            "peers": len(self.peers),
            "secret_bits": len(self._secret) * 8,
        }

    # ── Internal ──────────────────────────────────────────────────

    def _fire(self, event: str, *args: Any, **kwargs: Any) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.warning("Mesh callback %s error: %s", event, e)

    def _announce_loop(self) -> None:
        while self._running:
            try:
                msg = json.dumps({
                    "type": "announce",
                    "peer_id": self._peer_id,
                    "hostname": self._hostname,
                    "port": self._data_port,
                    "version": "3.0.0",
                }).encode()
                self._udp.sendto(msg, ("255.255.255.255", MESH_DISCOVERY_PORT))
            except Exception:
                pass
            for _ in range(BROADCAST_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)

    def _listen_loop(self) -> None:
        while self._running:
            try:
                data, addr = self._udp.recvfrom(4096)
                msg = json.loads(data.decode())
                if msg["type"] == "announce" and msg["peer_id"] != self._peer_id:
                    now = time.time()
                    peer = Peer(
                        peer_id=msg["peer_id"],
                        hostname=msg["hostname"],
                        ip=addr[0],
                        port=msg["port"],
                        last_seen=now,
                        version=msg.get("version", ""),
                    )
                    is_new = False
                    with self._lock:
                        if msg["peer_id"] not in self._peers:
                            is_new = True
                        self._peers[msg["peer_id"]] = peer
                    if is_new:
                        self._fire("peer_discovered", peer)
                    self._fire("peer_seen", peer)
            except socket.timeout:
                continue
            except Exception as e:
                logger.warning("Mesh listen error: %s", e)

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._tcp.accept()
                t = threading.Thread(
                    target=self._handle_conn, args=(conn, addr), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception:
                pass

    def _handle_conn(self, conn: socket.socket, addr: tuple) -> None:
        buf = b""
        try:
            while self._running:
                data = conn.recv(8192)
                if not data:
                    break
                buf += data
                while len(buf) >= 4:
                    length = struct.unpack("!I", buf[:4])[0]
                    if len(buf) < 4 + length:
                        break
                    raw = buf[4 : 4 + length]
                    buf = buf[4 + length :]
                    try:
                        msg = json.loads(raw)
                        self._fire(msg.get("type", "unknown"), msg, addr)
                    except json.JSONDecodeError:
                        continue
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════

_mesh_node: MeshNode | None = None


def get_mesh(secret: str = "") -> MeshNode:
    global _mesh_node
    if _mesh_node is None:
        _mesh_node = MeshNode(secret=secret)
    return _mesh_node

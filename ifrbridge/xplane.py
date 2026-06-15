"""X-Plane UDP driver.

Implements the three packet types we need against X-Plane's classic UDP API
(default port 49000):

  * CMND  — trigger a command (button presses, encoder detents)
  * DREF  — write a dataref (not used by the C172 config, included for symmetry)
  * RREF  — subscribe to dataref values; X-Plane streams them back to us

Works identically on Linux. X-Plane can run on the same host or another machine
on the LAN — just point ``host`` at it and enable network data output in
X-Plane's settings.
"""
from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Callable

DEFAULT_PORT = 49000


class XPlaneClient:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 listen_port: int = 0, dry_run: bool = False):
        self.addr = (host, port)
        self.dry_run = dry_run
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", listen_port))
        self.sock.settimeout(0.5)

        self._index_to_path: dict[int, str] = {}
        self._path_to_index: dict[str, int] = {}
        self._values: dict[str, float] = {}
        self._next_index = 0
        self._on_change: Callable[[str, float], None] | None = None
        self._rx_thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def bound_port(self) -> int:
        return self.sock.getsockname()[1]

    # ---- outbound -------------------------------------------------------
    def send_command(self, path: str) -> None:
        if self.dry_run:
            print(f"[xp] CMND {path}")
            return
        msg = b"CMND\x00" + path.encode("latin-1")
        self.sock.sendto(msg, self.addr)

    def set_dataref(self, path: str, value: float) -> None:
        if self.dry_run:
            print(f"[xp] DREF {path}={value}")
            return
        # 5-byte header + float + 500-byte null-padded path = 509 bytes.
        msg = b"DREF\x00" + struct.pack("<f", float(value))
        path_bytes = path.encode("latin-1")
        msg += path_bytes + b"\x00" * (500 - len(path_bytes))
        self.sock.sendto(msg, self.addr)

    def subscribe(self, path: str, freq: int = 5) -> int:
        """Ask X-Plane to stream ``path`` at ``freq`` Hz. Returns its index."""
        if path in self._path_to_index:
            return self._path_to_index[path]
        index = self._next_index
        self._next_index += 1
        self._index_to_path[index] = path
        self._path_to_index[path] = index
        if not self.dry_run:
            self._send_rref(path, freq, index)
        return index

    def _send_rref(self, path: str, freq: int, index: int) -> None:
        # 5-byte header + int freq + int index + 400-byte null-padded path.
        msg = b"RREF\x00" + struct.pack("<ii", freq, index)
        path_bytes = path.encode("latin-1")
        msg += path_bytes + b"\x00" * (400 - len(path_bytes))
        self.sock.sendto(msg, self.addr)

    # ---- inbound --------------------------------------------------------
    def value(self, path: str, default: float = 0.0) -> float:
        return self._values.get(path, default)

    def start_receiver(self, on_change: Callable[[str, float], None] | None = None) -> None:
        self._on_change = on_change
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if data[:4] != b"RREF":
                continue
            body = data[5:]  # skip "RREF" + 1 version/null byte
            for off in range(0, len(body) - 7, 8):
                index, value = struct.unpack_from("<if", body, off)
                path = self._index_to_path.get(index)
                if path is None:
                    continue
                prev = self._values.get(path)
                self._values[path] = value
                if self._on_change is not None and prev != value:
                    self._on_change(path, value)

    def close(self) -> None:
        self._stop.set()
        # Unsubscribe (freq 0) is polite but optional.
        if not self.dry_run:
            for path, index in list(self._path_to_index.items()):
                try:
                    self._send_rref(path, 0, index)
                except OSError:
                    pass
        try:
            self.sock.close()
        except OSError:
            pass

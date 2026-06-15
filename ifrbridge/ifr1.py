"""Octavi IFR-1 HID device layer: decode input reports, drive the LEDs.

Report layout below is taken from the acehoss/IFR1-FlyWithLua reverse-
engineering. The byte offsets and button bits are marked VERIFY — run
``tools/probe_ifr1.py`` and adjust the constants here if the live capture
disagrees. Everything downstream keys off the semantic events this module
emits, so fixing the layout is a localized change.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VID = 0x04D8
PID = 0xE6D6
LED_REPORT_ID = 11

# ---- input report layout (CONFIRMED via tools/probe_ifr1.py) ------------
# hidapi returns the report id as byte[0] (always 0x0b). 8 bytes total.
#   byte[0]        report id (0x0b, ignored)
#   byte[1..4]     button bitfields
#   byte[5],[6]    encoders (signed 8-bit deltas)
#   byte[7]        mode (0..7)
REPORT_LEN = 8
MODE_BYTE = 7
OUTER_ENC_BYTE = 5   # enc0; outer vs inner still to be confirmed by label pass
INNER_ENC_BYTE = 6   # enc1

MODES = ["COM1", "COM2", "NAV1", "NAV2", "FMS1", "FMS2", "AP", "XPDR"]

# Physical button -> (byte, bit), CONFIRMED via labeled capture. Names use the
# GPS/FMS label of each key; the binding layer remaps them in AP mode (that row
# doubles as AP/HDG/NAV/APR/ALT/VS) per the dual labels on the panel.
BUTTON_BITS: dict[str, tuple[int, int]] = {
    "DCT":  (1, 4),
    "MENU": (1, 5),
    "CLR":  (1, 6),
    "ENT":  (1, 7),
    "SWAP": (2, 0),   # freq switch (COM/NAV "_TOG")
    "CRSR": (2, 1),   # inner-knob push
    "CDI":  (2, 6),   # AP mode: AP
    "OBS":  (2, 7),   # AP mode: HDG
    "MSG":  (3, 0),   # AP mode: NAV
    "FPL":  (3, 1),   # AP mode: APR
    "VNAV": (3, 2),   # AP mode: ALT
    "PROC": (3, 3),   # AP mode: VS
}

# LED pin name (as in the .mcc <display pin="...">) -> bit in output report.
LED_PIN_BIT: dict[str, int] = {
    "AP Master": 0,
    "AP HDG":    1,
    "AP NAV":    2,
    "AP APR":    3,
    "AP ALT":    4,
    "AP VS":     5,
}


@dataclass
class EncoderEvent:
    ring: str          # "outer" | "inner"
    direction: int     # +1 | -1 (per detent)


@dataclass
class ButtonEvent:
    button: str        # physical name from BUTTON_BITS
    edge: str          # "press" | "release"


@dataclass
class ModeEvent:
    mode: str


Event = EncoderEvent | ButtonEvent | ModeEvent


def _signed(byte: int) -> int:
    return byte - 256 if byte >= 128 else byte


@dataclass
class Decoder:
    """Stateful decoder: feed it raw reports, get discrete events out."""
    _buttons: dict[str, bool] = field(default_factory=dict)
    _mode: str | None = None

    def feed(self, report: list[int]) -> list[Event]:
        events: list[Event] = []
        if len(report) < REPORT_LEN:
            return events

        # Mode selector
        mode_val = report[MODE_BYTE]
        mode = MODES[mode_val] if mode_val < len(MODES) else None
        if mode is not None and mode != self._mode:
            self._mode = mode
            events.append(ModeEvent(mode))

        # Encoders: each report carries a signed delta; emit one event/detent.
        for ring, byte_idx in (("outer", OUTER_ENC_BYTE), ("inner", INNER_ENC_BYTE)):
            delta = _signed(report[byte_idx])
            step = 1 if delta > 0 else -1
            for _ in range(abs(delta)):
                events.append(EncoderEvent(ring=ring, direction=step))

        # Buttons: edge-detect against previous state.
        for name, (byte_idx, bit) in BUTTON_BITS.items():
            pressed = bool(report[byte_idx] & (1 << bit))
            was = self._buttons.get(name, False)
            if pressed and not was:
                events.append(ButtonEvent(button=name, edge="press"))
            elif not pressed and was:
                events.append(ButtonEvent(button=name, edge="release"))
            self._buttons[name] = pressed

        return events

    @property
    def mode(self) -> str | None:
        return self._mode


class IFR1Device:
    """Thin wrapper over hidapi for reading reports and setting LEDs."""

    def __init__(self):
        import hid  # imported lazily so the rest of the pkg works without it
        self._hid = hid
        self.dev = hid.device()
        self.dev.open(VID, PID)
        self.dev.set_nonblocking(True)
        self._led_state = -1  # force first write

    def read(self) -> list[int] | None:
        r = self.dev.read(64)
        return r or None

    def set_leds(self, value: int) -> None:
        value &= 0xFF
        if value == self._led_state:
            return
        self.dev.write([LED_REPORT_ID, value])
        self._led_state = value

    def close(self) -> None:
        try:
            self.set_leds(0)
        except Exception:  # noqa: BLE001
            pass
        self.dev.close()

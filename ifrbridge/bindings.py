"""Map IFR-1 physical events to MobiFlight input *names* (e.g. "Button_COM1_OI").

Confirmed against the hardware via tools/probe_ifr1.py:

  * No mode knob — mode is selected by buttons; the firmware reports the active
    mode in the report's mode byte (0..7).
  * No shift/secondary layer on this unit, so the MobiFlight ``^`` entries
    (e.g. HDG via COM1, BARO via COM2) are simply unreachable here. We ignore
    them.
  * One physical button row doubles as GPS function keys (FMS modes) and
    autopilot keys (AP mode), per the dual labels printed on the panel.

MobiFlight names follow ``Button_<MODE>_<CTRL>``.
"""
from __future__ import annotations

from .ifr1 import ButtonEvent, EncoderEvent, Event

# Outer = byte5 (enc0), inner = byte6 (enc1). Encoder -> CTRL token.
def _encoder_ctrl(ev: EncoderEvent) -> str:
    if ev.ring == "outer":
        return "OI" if ev.direction > 0 else "OD"
    return "II" if ev.direction > 0 else "ID"


# In AP mode the GPS button row remaps to autopilot keys (physical -> CTRL).
_AP_REMAP = {
    "CDI":  "AP",
    "OBS":  "HDG",
    "MSG":  "NAV",
    "FPL":  "APR",
    "VNAV": "ALT",
    "PROC": "VS",
}

# Buttons that carry their own name as the CTRL token in FMS modes.
_FMS_TOKENS = {"DCT", "MENU", "CLR", "ENT", "CDI", "OBS", "MSG", "FPL",
               "VNAV", "PROC", "CRSR"}

_COM_NAV = {"COM1", "COM2", "NAV1", "NAV2"}
_FMS = {"FMS1", "FMS2"}


def _button_ctrl(mode: str, name: str) -> str | None:
    if mode == "AP":
        return _AP_REMAP.get(name)        # only the row buttons are meaningful
    if mode in _COM_NAV:
        return "TOG" if name == "SWAP" else None
    if mode in _FMS:
        return name if name in _FMS_TOKENS else None
    return None                            # XPDR: encoders only


def name_for(mode: str | None, ev: Event) -> str | None:
    """Return the MobiFlight input name for a physical event, or None."""
    if mode is None:
        return None
    if isinstance(ev, EncoderEvent):
        return f"Button_{mode}_{_encoder_ctrl(ev)}"
    if isinstance(ev, ButtonEvent):
        ctrl = _button_ctrl(mode, ev.button)
        return f"Button_{mode}_{ctrl}" if ctrl else None
    return None

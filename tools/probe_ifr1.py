#!/usr/bin/env python3
"""Octavi IFR-1 HID capture / verification tool.

Confirms the device, prints the raw input-report layout, and helps lock the
byte offsets (mode knob, encoders, buttons) by showing which bytes change as
you interact with the panel. Also cycles the LEDs to verify the output report.

Usage:
    python tools/probe_ifr1.py            # auto-probe + live input capture
    python tools/probe_ifr1.py --leds     # also cycle the LEDs
    python tools/probe_ifr1.py --seconds 30
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import hid
except ImportError:
    sys.exit("Missing dependency: pip install hidapi")

VID = 0x04D8
PID = 0xE6D6
LED_REPORT_ID = 11


def enumerate_device() -> list[dict]:
    infos = hid.enumerate(VID, PID)
    if not infos:
        sys.exit(f"No Octavi IFR-1 found (VID={VID:#06x} PID={PID:#06x}). Is it plugged in?")
    print(f"Found {len(infos)} interface(s) for {VID:#06x}:{PID:#06x}")
    for i, info in enumerate(infos):
        print(f"  [{i}] path={info['path'].decode(errors='replace')!r} "
              f"usage_page={info.get('usage_page')} usage={info.get('usage')} "
              f"iface={info.get('interface_number')} "
              f"product={info.get('product_string')!r} serial={info.get('serial_number')!r}")
    return infos


def fmt(report: list[int]) -> str:
    return " ".join(f"{b:02x}" for b in report)


# Confirmed layout (hidapi returns report id as byte[0]):
#   byte[0] = report id 0x0b   byte[5],[6] = encoders (signed)   byte[7] = mode
#   byte[1..4] = button bitfields
MODES = ["COM1", "COM2", "NAV1", "NAV2", "FMS1", "FMS2", "AP", "XPDR"]
MODE_BYTE = 7
ENC_BYTES = (5, 6)
BTN_BYTES = (1, 2, 3, 4)


def decode(report: list[int]) -> str:
    if len(report) < 8:
        return f"(short report, {len(report)} bytes)"
    mode_val = report[MODE_BYTE]
    mode = MODES[mode_val] if mode_val < len(MODES) else f"?{mode_val}"
    encs = []
    for i, b in enumerate(ENC_BYTES):
        d = report[b] - 256 if report[b] >= 128 else report[b]
        if d:
            encs.append(f"enc{i}(byte{b})={d:+d}")
    btns = []
    for byte_idx in BTN_BYTES:
        for bit in range(8):
            if report[byte_idx] & (1 << bit):
                btns.append(f"byte{byte_idx}.bit{bit}")
    parts = [f"MODE={mode}({mode_val})"]
    parts += encs
    if btns:
        parts.append("BTN " + " ".join(btns))
    return "  ".join(parts)


def diff_bytes(prev: list[int], cur: list[int]) -> str:
    out = []
    for i, (a, b) in enumerate(zip(prev, cur)):
        if a != b:
            out.append(f"byte[{i}]: {a:02x}->{b:02x}")
    return "; ".join(out)


def cycle_leds(dev: hid.device) -> None:
    """Light each AP LED bit in turn so you can confirm the bit->LED mapping."""
    names = ["AP", "HDG", "NAV", "APR", "ALT", "VS"]
    print("\n--- LED cycle (output report id 11) ---")
    for bit, name in enumerate(names):
        val = 1 << bit
        try:
            dev.write([LED_REPORT_ID, val])
        except Exception as exc:  # noqa: BLE001
            print(f"  LED write failed: {exc}")
            return
        print(f"  bit{bit} (0x{val:02x}) -> expect '{name}' lit")
        time.sleep(0.8)
    dev.write([LED_REPORT_ID, 0x00])  # all off
    print("  all LEDs off")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60.0, help="capture duration")
    ap.add_argument("--leds", action="store_true", help="cycle LEDs first")
    ap.add_argument("--raw", action="store_true", help="print raw bytes for every report")
    args = ap.parse_args()

    enumerate_device()
    dev = hid.device()
    dev.open(VID, PID)
    dev.set_nonblocking(True)
    print(f"\nOpened {dev.get_manufacturer_string()!r} {dev.get_product_string()!r}")

    if args.leds:
        cycle_leds(dev)

    # Baseline / idle report tells us the report length and resting state.
    time.sleep(0.2)
    baseline = None
    for _ in range(50):
        r = dev.read(64)
        if r:
            baseline = r
            break
        time.sleep(0.01)
    if baseline:
        print(f"\nIdle report ({len(baseline)} bytes): {fmt(baseline)}")
        print(f"  decoded: {decode(baseline)}")
    else:
        print("\nNo idle report received yet (some firmwares only send on change).")

    print(f"\n--- Live capture for {args.seconds:.0f}s. "
          "Turn each knob (outer/inner), the mode selector, and press each button. ---")
    prev = baseline or []
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        r = dev.read(64)
        if not r:
            time.sleep(0.005)
            continue
        if r == prev:
            continue
        line = fmt(r)
        if args.raw or not prev:
            print(f"{line}    {decode(r)}")
        else:
            print(f"{line}    Δ {diff_bytes(prev, r)}    {decode(r)}")
        prev = r

    dev.close()
    print("\nDone. Use the Δ lines to confirm: which byte = mode, which two = encoders, "
          "which bits = buttons. Update ifrbridge/ifr1.py if offsets differ.")


if __name__ == "__main__":
    main()

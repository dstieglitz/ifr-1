# ifrbridge

A lightweight, Linux-friendly replacement for MobiFlight that drives an
**Octavi IFR-1** (`0x04D8:0xE6D6`) against **X-Plane**, using an existing
MobiFlight `.mcc` file as the routing table. Pure Python — `hidapi` for the
panel, stdlib `socket` for X-Plane, stdlib `xml` for the config. No Windows.

## How it works

```
Octavi IFR-1 ──HID input report──►  ifrbridge  ──UDP CMND/DREF──► X-Plane
(0x04D8/0xE6D6)                    (this code)
            ◄─HID LED report 11──             ◄──UDP RREF subs── X-Plane
```

- **Inputs:** decode each HID report into semantic events (mode knob, outer/
  inner encoder detents, button edges, shift layer), map to the MobiFlight
  input name (`Button_<MODE>[^]_<CTRL>`), look it up in the `.mcc`, and send the
  matching X-Plane command. Internal MobiFlight variables (`FMS1_RNG`) and
  precondition gating are reproduced, so the dual-function FMS encoders work.
- **Outputs:** subscribe to the 6 autopilot datarefs, apply each output's
  transform (`$&16`, etc.), pack the result into LED output report id 11.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .        # installs ifrbridge + hidapi, and the `ifrbridge` command
```

(`pip install -r requirements.txt` still works if you only want the deps without
installing the package.)

### HID permissions (Linux)

`/dev/hidraw*` is root-only by default, so the panel won't open as a normal user
— you'll get `OSError: open failed` from `hid.device`. Install the udev rule
(this is also done automatically by `linux/install.sh`):

```bash
sudo cp linux/99-octavi-ifr1.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
# then unplug and replug the IFR-1
```

After that, run without `sudo`. Sanity checks: `lsusb | grep -i 04d8` (device
enumerated?), `ls -l /dev/hidraw*` (the IFR-1 node should now be group-readable,
not `root … 0600`). If `sudo … run` works but a normal run doesn't, it's purely
this permission issue.

## Use

```bash
# Parse + summarize the config (no hardware, no network):
.venv/bin/python -m ifrbridge --mcc XP_C172.mcc check

# Dry run — print the X-Plane packets each control would send, no UDP, no panel:
.venv/bin/python -m ifrbridge --mcc XP_C172.mcc run --no-hid --dry-run -v

# Real run (panel + X-Plane on this host):
.venv/bin/python -m ifrbridge --mcc XP_C172.mcc run -v

# X-Plane on another machine:
.venv/bin/python -m ifrbridge run --host 192.168.1.50
```

In X-Plane, enable UDP data (Settings → Network) so it accepts incoming
commands and serves dataref subscriptions on port 49000.

## Run as a service (Linux)

To have it start with your desktop session and auto-restart until the panel and
X-Plane are up, install the systemd **user** service:

```bash
./linux/install.sh
```

This creates the venv, installs a udev rule so the IFR-1 is accessible without
root (`linux/99-octavi-ifr1.rules`), and enables a user service
(`linux/ifrbridge.service`). After install:

```bash
systemctl --user status ifrbridge          # check it
journalctl --user -u ifrbridge -f          # follow logs
systemctl --user restart ifrbridge         # after changing the X-Plane host
```

X-Plane on another machine? Put its IP in `~/.config/ifrbridge.env`:

```
IFRBRIDGE_HOST=192.168.1.50
```

Notes:
- The service runs only the bridge loop; it keeps retrying every 5 s, so it's
  fine to start it before X-Plane or before plugging in the panel.
- For a headless/auto-login box, run `loginctl enable-linger $USER` once so the
  user service starts at boot.

## Calibrating the HID layout (one-time)

The HID byte offsets and button bits come from the
[acehoss/IFR1-FlyWithLua](https://github.com/acehoss/IFR1-FlyWithLua) reverse
engineering and are marked `VERIFY` in `ifrbridge/ifr1.py`. Confirm them against
your unit:

```bash
.venv/bin/python tools/probe_ifr1.py            # turn each knob, press each button
.venv/bin/python tools/probe_ifr1.py --leds     # also cycle the LEDs to confirm bit->LED
```

The probe prints which bytes change (`Δ`) as you interact. If anything differs
from the constants in `ifr1.py`, edit them there — the rest of the code keys off
semantic events, so it's a localized fix.

### Assumptions to confirm during calibration

These live in `ifrbridge/bindings.py` and are the only guesses in the stack:

1. **Shift layer (`^`)** is toggled by the inner-knob push in non-FMS modes
   (gives HDG in COM1, BARO in COM2, etc.). If your panel uses a dedicated
   function key, adjust `is_shift_toggle`.
2. **AP-row buttons** (AP/HDG/NAV/APR/ALT/VS) are treated as dedicated keys that
   always map to `Button_AP_*`.
3. **FMS "RNG (TOG)"** (sets `FMS#_RNG` for the map-zoom layer) has no confirmed
   physical key yet — currently unmapped and logged. The capture will reveal it.

Run with `-v` and watch for `[unmapped]` / `[no-binding]` lines — those flag any
control whose binding still needs to be filled in.

## Layout

| File | Role |
|------|------|
| `ifrbridge/mcc.py`      | parse the `.mcc` into inputs/outputs |
| `ifrbridge/ifr1.py`     | HID report decode + LED encode (the `VERIFY` constants) |
| `ifrbridge/bindings.py` | physical event → MobiFlight name (the calibration joint) |
| `ifrbridge/xplane.py`   | X-Plane UDP: CMND / DREF / RREF |
| `ifrbridge/expr.py`     | safe evaluator for transforms (`$&16`) |
| `ifrbridge/bridge.py`   | main loop wiring it together |
| `tools/probe_ifr1.py`   | HID capture / calibration helper |

"""Wire the IFR-1, the .mcc routing table, and X-Plane together."""
from __future__ import annotations

import time

from . import bindings
from .expr import evaluate
from .ifr1 import (
    LED_PIN_BIT,
    ButtonEvent,
    Decoder,
    EncoderEvent,
    Event,
    IFR1Device,
    ModeEvent,
)
from .mcc import CommandAction, InputConfig, MccConfig, VariableAction, parse_mcc
from .xplane import XPlaneClient


class Bridge:
    def __init__(self, mcc: MccConfig, xp: XPlaneClient,
                 device: IFR1Device | None = None, verbose: bool = False):
        self.mcc = mcc
        self.xp = xp
        self.device = device
        self.verbose = verbose

        self.inputs_by_name = mcc.inputs_by_name()
        self.variables: dict[str, float] = {}
        self.decoder = Decoder()

        # Outputs: subscribe to each distinct dataref, remember which pins use it.
        self._active_outputs = [o for o in mcc.outputs if o.active and o.dataref and o.pin]
        for out in self._active_outputs:
            self.xp.subscribe(out.dataref)

    # ---- preconditions --------------------------------------------------
    def _precondition_ok(self, cfg: InputConfig) -> bool:
        if not cfg.preconditions:
            return True
        result = True
        for pc in cfg.preconditions:
            if not pc.active:
                continue
            cur = self.variables.get(pc.ref, 0.0)
            try:
                target = float(pc.value)
            except ValueError:
                target = 0.0
            cmp = {
                "=": cur == target,
                "!=": cur != target,
                "<": cur < target,
                ">": cur > target,
                "<=": cur <= target,
                ">=": cur >= target,
            }.get(pc.operand, False)
            result = (result and cmp) if pc.logic == "and" else (result or cmp)
        return result

    def _select_config(self, name: str) -> InputConfig | None:
        for cfg in self.inputs_by_name.get(name, []):
            if self._precondition_ok(cfg):
                return cfg
        return None

    # ---- input handling -------------------------------------------------
    def _execute(self, cfg: InputConfig, edge: str) -> None:
        action = cfg.on_press if edge == "press" else cfg.on_release
        if action is None:
            return
        if isinstance(action, CommandAction):
            if action.path:
                self.xp.send_command(action.path)
                if self.verbose:
                    print(f"  -> CMND {action.path}  [{cfg.description}]")
        elif isinstance(action, VariableAction):
            try:
                val = float(action.expression)
            except ValueError:
                val = 0.0
            self.variables[action.var_name] = val
            if self.verbose:
                print(f"  -> VAR {action.var_name}={val}  [{cfg.description}]")

    def handle_event(self, ev: Event) -> None:
        if isinstance(ev, ModeEvent):
            if self.verbose:
                print(f"[mode] {ev.mode}")
            return

        mode = self.decoder.mode

        name = bindings.name_for(mode, ev)
        if name is None:
            if self.verbose:
                print(f"[unmapped] mode={mode} {ev}")
            return

        cfg = self._select_config(name)
        if cfg is None:
            if self.verbose:
                print(f"[no-binding] {name}  ({ev})")
            return

        # Encoders and most buttons act on press; release matters only where the
        # config defines an onRelease (e.g. the RNG momentary variable).
        if isinstance(ev, EncoderEvent):
            self._execute(cfg, "press")
        elif isinstance(ev, ButtonEvent):
            self._execute(cfg, ev.edge)

    # ---- output handling ------------------------------------------------
    def compute_led_byte(self) -> int:
        byte = 0
        for out in self._active_outputs:
            bit = LED_PIN_BIT.get(out.pin)
            if bit is None:
                continue
            raw = self.xp.value(out.dataref, 0.0)
            val = evaluate(out.transform, raw) if out.transform_active else raw
            if val:
                byte |= (1 << bit)
        return byte

    def update_leds(self) -> None:
        if self.device is None:
            return
        self.device.set_leds(self.compute_led_byte())

    # ---- main loop ------------------------------------------------------
    def run(self, poll_hz: float = 200.0) -> None:
        period = 1.0 / poll_hz
        led_byte = -1
        while True:
            if self.device is not None:
                report = self.device.read()
                if report:
                    for ev in self.decoder.feed(report):
                        self.handle_event(ev)
            # Refresh LEDs when the computed state changes.
            new_byte = self.compute_led_byte()
            if new_byte != led_byte:
                led_byte = new_byte
                self.update_leds()
            time.sleep(period)


def build_bridge(mcc_path: str, host: str, port: int, *,
                 use_hid: bool, dry_run: bool, verbose: bool) -> Bridge:
    mcc = parse_mcc(mcc_path)
    xp = XPlaneClient(host=host, port=port, dry_run=dry_run)
    xp.start_receiver()
    device = IFR1Device() if use_hid else None
    return Bridge(mcc, xp, device=device, verbose=verbose)

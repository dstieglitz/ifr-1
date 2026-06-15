"""CLI entry point: ``python -m ifrbridge --mcc XP_C172.mcc``."""
from __future__ import annotations

import argparse
import sys

from .bridge import build_bridge
from .mcc import parse_mcc


def cmd_run(args: argparse.Namespace) -> int:
    bridge = build_bridge(
        args.mcc, args.host, args.port,
        use_hid=not args.no_hid,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    print(f"ifrbridge running. X-Plane {args.host}:{args.port}, "
          f"HID={'off' if args.no_hid else 'on'}, dry_run={args.dry_run}.")
    print("Ctrl-C to stop.")
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        if bridge.device is not None:
            bridge.device.close()
        bridge.xp.close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Parse the .mcc and summarize it — no hardware, no network."""
    mcc = parse_mcc(args.mcc)
    print(f"Inputs:  {len(mcc.inputs)} configs "
          f"({sum(1 for i in mcc.inputs if i.active)} active)")
    print(f"Outputs: {len(mcc.outputs)} configs "
          f"({sum(1 for o in mcc.outputs if o.active)} active)")

    by_name = mcc.inputs_by_name()
    dup = {n: len(v) for n, v in by_name.items() if len(v) > 1}
    if dup:
        print("\nNames with multiple (precondition-gated) bindings:")
        for n, c in sorted(dup.items()):
            print(f"  {n}: {c}")

    print("\nLED outputs:")
    for o in mcc.outputs:
        if o.active and o.pin:
            tr = f"  transform={o.transform}" if o.transform_active else ""
            print(f"  {o.pin:10s} <- {o.dataref}{tr}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ifrbridge",
                                description="Octavi IFR-1 <-> X-Plane bridge")
    p.add_argument("--mcc", default="XP_C172.mcc", help="MobiFlight .mcc config")
    sub = p.add_subparsers(dest="cmd")

    run = sub.add_parser("run", help="run the bridge (default)")
    run.add_argument("--host", default="127.0.0.1", help="X-Plane host")
    run.add_argument("--port", type=int, default=49000, help="X-Plane UDP port")
    run.add_argument("--no-hid", action="store_true", help="run without the IFR-1 (outputs only)")
    run.add_argument("--dry-run", action="store_true", help="print X-Plane packets instead of sending")
    run.add_argument("--verbose", "-v", action="store_true")
    run.set_defaults(func=cmd_run)

    check = sub.add_parser("check", help="parse and summarize the .mcc")
    check.set_defaults(func=cmd_check)

    args = p.parse_args(argv)
    if args.cmd is None:
        # default to a parse summary so a bare invocation is safe (no hardware)
        return cmd_check(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

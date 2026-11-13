"""How long does the Tiger controller take to answer, and what does polling cost?

Every ASI device on the rig shares one serial port and one adapter lock, so
whatever an operator presses waits behind the read in flight. Two questions
follow, and this answers both:

    uv run python tools/tiger_roundtrip.py            # time real exchanges (device layer OFF)
    uv run python tools/tiger_roundtrip.py --fast     # the same, with "Fast USB to Serial" enabled
    uv run python tools/tiger_roundtrip.py --model    # no hardware: what each polling cadence costs

The measurement is read-only. It loads the serial port and the Tiger hub and
nothing else (no stages, no cameras, no lasers), sends WHERE and STATUS
queries, and times them. Nothing is commanded to move. It needs the port, so
stop the device layer and Micro-Manager first.

Why it exists: what one exchange costs on this rig has not been measured
directly. The code's own notes say ~125 ms; on 2026-11-08 a single F-drive
read through the device layer came back in ~55 ms and a beam write in ~135 ms
(the first figures taken that day, 260 and 340, each carried ~206 ms of curl
waiting on IPv6 for `localhost` and were wrong). The cadences in
device_layer.py were chosen with `--model`, which shows how the queue behaves
for whatever an exchange costs (`--exchange-ms`). If `--fast` shows exchanges
several times quicker than plain, set `Property,COM4,Fast USB to Serial,Enable`
in the Micro-Manager config, and the pollers can afford to be faster again.
"""

from __future__ import annotations

import argparse
import heapq
import os
import random
import statistics
import sys
import time
from collections.abc import Sequence

MM_DIR = r"C:/Program Files/Micro-Manager-1.4"
PORT = "COM4"


def _summary(label: str, ms: list[float]) -> str:
    a = sorted(ms)
    return (
        f"{label:<46} n={len(a):<3} min={a[0]:6.1f}  p50={a[len(a) // 2]:6.1f}  "
        f"p90={a[int(len(a) * 0.9)]:6.1f}  max={a[-1]:6.1f} ms"
    )


def measure(fast: bool, mm_dir: str, port: str) -> int:
    os.environ["PATH"] += os.pathsep + mm_dir
    import pymmcore

    core = pymmcore.CMMCore()
    core.setDeviceAdapterSearchPaths([mm_dir])

    def timed(fn, n: int = 30) -> list[float]:
        out = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            out.append((time.perf_counter() - t0) * 1000)
        return out

    try:
        core.loadDevice(port, "SerialManager", port)
        for key, value in [
            ("AnswerTimeout", "500.0000"),
            ("BaudRate", "115200"),
            ("DelayBetweenCharsMs", "0.0000"),
            ("Handshaking", "Off"),
            ("Parity", "None"),
            ("StopBits", "1"),
        ]:
            core.setProperty(port, key, value)
        if "Fast USB to Serial" in list(core.getDevicePropertyNames(port)):
            core.setProperty(port, "Fast USB to Serial", "Enable" if fast else "Disable")
            print("Fast USB to Serial =", core.getProperty(port, "Fast USB to Serial"))
        core.loadDevice("TigerCommHub", "ASITiger", "TigerCommHub")
        core.setProperty("TigerCommHub", "Port", port)
        core.initializeDevice(port)
        core.initializeDevice("TigerCommHub")
        print("Tiger firmware", core.getProperty("TigerCommHub", "FirmwareVersion"))

        def raw(command: str) -> str:
            core.setProperty("TigerCommHub", "SerialCommand", command)
            return core.getProperty("TigerCommHub", "SerialResponse")

        for command in ("W Z", "W X Y", "W X Y Z V P Q", "/"):
            print(f"  {command!r:<18} -> {raw(command)!r}")
        print(_summary("one axis (W Z), one exchange", timed(lambda: raw("W Z"))))
        print(_summary("two axes (W X Y), one exchange", timed(lambda: raw("W X Y"))))
        print(_summary("six axes in one exchange", timed(lambda: raw("W X Y Z V P Q"))))
        print(_summary("status (/), one exchange", timed(lambda: raw("/"))))
        return 0
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        print("Is the controller powered, and is the device layer (or Micro-Manager) stopped?")
        return 1
    finally:
        try:
            core.unloadAllDevices()
        except Exception:
            pass


def simulate(
    pollers: Sequence[tuple[float, int]], exchange: float, write: int, seed: int = 7
) -> dict:
    """One port, first come first served. ``pollers`` are (interval s, exchanges
    per read); each asks again ``interval`` after it last asked, or as soon as
    its read returns if that is later. A write of ``write`` exchanges arrives
    at a random moment every few seconds (never on the heels of another
    write), 400 times; its latency is the wait plus its own time.
    """
    rng = random.Random(seed)
    horizon = 400 * 5.0 + 10.0
    events: list[tuple[float, int, int]] = []  # (asks at, tiebreak, poller index or -1 for a write)
    for i, _ in enumerate(pollers):
        heapq.heappush(events, (rng.uniform(0, 0.2), i, i))
    for k in range(400):
        heapq.heappush(events, (5.0 * k + rng.uniform(1.0, 4.0), 1000 + k, -1))
    free_at = busy = 0.0
    latencies: list[float] = []
    while events:
        asked, tiebreak, who = heapq.heappop(events)
        if asked > horizon:
            continue
        start = max(asked, free_at)
        service = (write if who < 0 else pollers[who][1]) * exchange
        free_at = start + service
        if who < 0:
            latencies.append((free_at - asked) * 1000)
        else:
            busy += service
            interval = pollers[who][0]
            heapq.heappush(events, (max(asked + interval, free_at), tiebreak, who))
    latencies.sort()
    return {
        "busy": busy / horizon,
        "p50": latencies[len(latencies) // 2],
        "p90": latencies[int(len(latencies) * 0.9)],
        "mean": statistics.mean(latencies),
    }


def model(exchange_ms: float) -> int:
    e = exchange_ms / 1000.0
    rows = [
        ("as it was: XY 5 Hz, 4 axes 1 Hz, sweep 15 s", [(0.2, 2), (1.0, 5), (15.0, 18)], e),
        ("no sweep; XY 2 Hz, 4 axes 1 Hz", [(0.5, 2), (1.0, 5)], e),
        ("no sweep; XY 2 Hz, 4 axes every 2 s", [(0.5, 2), (2.0, 5)], e),
        ("chosen: XY 2 Hz, F+Z every 2 s, piezo+galvo 10 s", [(0.5, 2), (2.0, 2), (10.0, 3)], e),
        ("chosen, XY at 1 Hz", [(1.0, 2), (2.0, 2), (10.0, 3)], e),
        ("no polling at all (the floor)", [], e),
    ]
    print(
        "A model, not a measurement: one port, first come first served, "
        f"{e * 1000:.0f} ms an exchange."
    )
    print(f"{'polling':<50} {'port busy':>9}   {'1-exchange write':>22}   {'3-exchange write':>22}")
    print(f"{'':<50} {'':>9}   {'p50':>10} {'p90':>10}   {'p50':>10} {'p90':>10}")
    for label, pollers, exchange in rows:
        one = simulate(pollers, exchange, 1)
        three = simulate(pollers, exchange, 3)
        print(
            f"{label:<50} {one['busy'] * 100:>8.0f}%   "
            f"{one['p50']:>7.0f} ms {one['p90']:>7.0f} ms   "
            f"{three['p50']:>7.0f} ms {three['p90']:>7.0f} ms"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", action="store_true", help="no hardware: what each cadence costs")
    parser.add_argument(
        "--fast", action="store_true", help='open the port with "Fast USB to Serial" enabled'
    )
    parser.add_argument("--mm-dir", default=MM_DIR)
    parser.add_argument("--port", default=PORT)
    parser.add_argument(
        "--exchange-ms",
        type=float,
        default=110.0,
        help="for --model: what one exchange costs (not yet measured on the rig)",
    )
    args = parser.parse_args()
    if args.model:
        return model(args.exchange_ms)
    return measure(args.fast, args.mm_dir, args.port)


if __name__ == "__main__":
    sys.exit(main())

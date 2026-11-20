"""A session's hardware sequence: what the instrument did, and when.

Two halves of one format. ``record_of`` turns the sequence a scanner reads
out beside its stack (epoch seconds, from the device) into what a volume's
sidecar keeps under ``metadata.hardware`` (moments in UTC with their Z, like
``acquired_at_utc``). ``session_sequence`` reads a session's volumes,
brightfield frames and temperature back onto one clock, for the Sessions
view's hardware timeline.
"""

from __future__ import annotations

import bisect
import math
from datetime import datetime, timezone
from typing import Any

from gently.core.file_store import _read_yaml, utc_of_epoch

# The moments a stack's sequence carries, in the order the hardware meets them.
MOMENTS = ("lasers_on", "scan_started", "side_began", "first_frame", "last_frame", "lasers_off")


def record_of(sequence: dict[str, Any]) -> dict[str, Any]:
    """A device's sequence as a sidecar keeps it: each moment in UTC."""
    out = {k: v for k, v in sequence.items() if k not in MOMENTS}
    for k in MOMENTS:
        if sequence.get(k) is not None:
            out[f"{k}_utc"] = utc_of_epoch(sequence[k])
    return out


# ---- reading a session back ------------------------------------------------

# At most this many temperature readings go to the view. A night at 1 Hz is
# 40 000; past this, each stretch keeps its lowest and highest reading, so an
# excursion is never thinned away.
TEMPERATURE_POINTS = 4_000
_LINES = (405, 488, 561, 637)


def _parse(stamp: Any) -> datetime | None:
    if stamp is None or stamp == "":
        return None
    if isinstance(stamp, (int, float)):
        return datetime.fromtimestamp(float(stamp), tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


class _RigClock:
    """The rig PC's offset from UTC, learned from the times a session kept
    both ways: a volume's acquired_at (its local time, no zone) beside its
    acquired_at_utc. A time kept with no zone is read on that clock, not this
    PC's: a session recorded at one rig may be read anywhere. Each is read by
    the nearest such pair, so a clock change mid-session is followed. With
    none to learn from, this PC's zone: the last resort."""

    def __init__(self) -> None:
        self._pairs: list[tuple[float, int]] = []  # (local read as if UTC, offset s)

    def learn(self, local: Any, utc: Any) -> None:
        lo, ut = _parse(local), _parse(utc)
        if lo is None or ut is None or lo.tzinfo is not None or ut.tzinfo is None:
            return
        as_utc = lo.replace(tzinfo=timezone.utc).timestamp()
        # Zones are whole quarter hours; the two stamps are the same moment.
        offset = int(round((as_utc - ut.timestamp()) / 900.0)) * 900
        bisect.insort(self._pairs, (as_utc, offset))

    @property
    def offset(self) -> int | None:
        """The session's usual offset, seconds east of UTC, or None."""
        if not self._pairs:
            return None
        offsets = sorted(o for _, o in self._pairs)
        return offsets[len(offsets) // 2]

    def epoch(self, stamp: Any) -> float | None:
        """Seconds since 1970 for any stamp on disk: UTC with its Z, UTC with
        an offset, or the rig's local time with no zone."""
        dt = _parse(stamp)
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.timestamp()
        if not self._pairs:
            return dt.timestamp()  # this PC's zone
        as_utc = dt.replace(tzinfo=timezone.utc).timestamp()
        i = bisect.bisect_left(self._pairs, (as_utc,))
        near = [p for p in self._pairs[max(0, i - 1) : i + 1]]
        _, offset = min(near, key=lambda p: abs(p[0] - as_utc))
        return as_utc - offset


_epoch = _RigClock().epoch  # for a stamp that carries its zone


def _finite(x: Any) -> float | None:
    """A number the page can be sent, or None: NaN and infinity are not JSON."""
    return float(x) if isinstance(x, (int, float)) and math.isfinite(x) else None


def _volume(doc: dict, folder: str, clock: _RigClock) -> dict[str, Any]:
    md = doc.get("metadata") or {}
    hw = md.get("hardware") or {}
    shape = doc.get("shape") or [0]
    slices = int(md.get("num_slices") or hw.get("num_slices") or shape[0] or 0)
    exposure = md.get("exposure_ms") or hw.get("exposure_ms")
    v: dict[str, Any] = {
        "embryo": doc.get("embryo_id") or folder,
        "t": doc.get("timepoint"),
        "side": str(doc.get("side") or md.get("side") or "A").upper(),
        "slices": slices,
        "exposure_ms": float(exposure) if exposure else None,
        # The embryo's own settings: all an unrecorded volume can say.
        "settings": {
            str(wl): _finite(md[f"laser_power_{wl}_pct"])
            for wl in _LINES
            if md.get(f"laser_power_{wl}_pct") is not None
        },
    }
    if hw:
        v.update(
            recorded=True,
            laser_config=hw.get("laser_config"),
            lasers={str(k): _finite(p) for k, p in (hw.get("powers_pct") or {}).items()},
            **{k: clock.epoch(hw.get(f"{k}_utc")) for k in MOMENTS},
        )
        return v
    # From before the hardware was recorded: the scan's start, and the light
    # time its slices and exposure add up to — no more is known.
    began = clock.epoch(doc.get("acquired_at_utc")) or clock.epoch(doc.get("acquired_at"))
    light_s = slices * float(exposure) / 1000.0 if exposure else 0.0
    v.update(
        recorded=False,
        laser_config=None,
        lasers=None,
        lasers_on=None,
        scan_started=began,
        side_began=None,
        first_frame=None,
        last_frame=began + light_s if began is not None else None,
        lasers_off=None,
    )
    return v


def _volume_docs(store: Any, sid: str) -> list[tuple[dict, str]]:
    sd = store._session_dir(sid)
    embryos = sd / "embryos" if sd is not None else None
    if embryos is None or not embryos.exists():
        return []
    out = []
    for edir in sorted(d for d in embryos.iterdir() if d.is_dir()):
        for meta in [
            *sorted(edir.glob("volumes/t*.meta.yaml")),
            *sorted(edir.glob("volumes/B/t*.meta.yaml")),
        ]:
            doc = _read_yaml(meta)
            if isinstance(doc, dict):
                out.append((doc, edir.name))
    return out


def _frames(store: Any, sid: str, clock: _RigClock) -> list[dict[str, Any]]:
    """Brightfield frames: of the dish, lit for every embryo, so no embryo's."""
    out = []
    for rec in store.list_snapshots(sid, "bf") or []:
        md = rec.get("metadata") or {}
        out.append(
            {
                "frame": md.get("frame"),
                "field": md.get("field"),
                "fields": md.get("fields"),
                "round": md.get("round"),
                "exposure_ms": md.get("exposure_ms"),
                "light": md.get("light"),
                "led_pct": md.get("led_intensity_pct"),
                # Written by a frame that records its light, even as None.
                "recorded": "light_on_utc" in md,
                "light_on": clock.epoch(md.get("light_on_utc")),
                "light_off": clock.epoch(md.get("light_off_utc")),
                "exposed": clock.epoch(md.get("exposed_utc")),
                "filed": clock.epoch(md.get("captured_at") or rec.get("captured_at")),
            }
        )
    return out


def _span_of_volume(v: dict) -> tuple[float | None, float | None]:
    return (
        v["lasers_on"] if v["lasers_on"] is not None else v["scan_started"],
        v["lasers_off"] if v["lasers_off"] is not None else v["last_frame"],
    )


def _span_of_frame(f: dict) -> tuple[float | None, float | None]:
    starts = [f["light_on"], f["exposed"], f["filed"]]
    ends = [f["light_off"], f["exposed"], f["filed"]]
    return (
        next((t for t in starts if t is not None), None),
        next((t for t in ends if t is not None), None),
    )


def _thin(rows: list[list], points: int = TEMPERATURE_POINTS) -> list[list]:
    """At most ``points`` readings: past that, each of points/2 equal stretches
    keeps its lowest and its highest, in the order they were read."""
    if len(rows) <= points:
        return rows
    t0, t1 = rows[0][0], rows[-1][0]
    n = points // 2
    width = (t1 - t0) / n or 1.0
    out: list[list] = []
    i = 0
    for b in range(n):
        end = t0 + (b + 1) * width
        chunk = []
        while i < len(rows) and (rows[i][0] < end or b == n - 1):
            chunk.append(rows[i])
            i += 1
        if chunk:
            lo = min(chunk, key=lambda r: r[1])
            hi = max(chunk, key=lambda r: r[1])
            out.extend([lo] if lo is hi else sorted([lo, hi], key=lambda r: r[0]))
    return out


def _temperature(store: Any, sid: str, t0: float | None, t1: float | None) -> list[list]:
    rows: list[list[Any]] = []
    for s in store.read_temperature_log(sid) or []:
        t, water = _epoch(s.get("t")), _finite(s.get("water_c"))
        if t is None or water is None:
            continue
        rows.append([t, water, _finite(s.get("setpoint_c"))])
    rows.sort(key=lambda r: r[0])
    if t0 is not None and t1 is not None:
        pad = max(60.0, 0.02 * (t1 - t0))
        rows = [r for r in rows if t0 - pad <= r[0] <= t1 + pad]
    return _thin(rows)


def session_sequence(store: Any, sid: str) -> dict[str, Any]:
    """Everything the hardware did in a session, on one clock (epoch seconds):
    its volumes, its brightfield frames and its temperature, with the span
    they cover, the embryos in their order and every laser line they show."""
    docs = _volume_docs(store, sid)
    clock = _RigClock()
    for doc, _ in docs:
        clock.learn(doc.get("acquired_at"), doc.get("acquired_at_utc"))
    volumes = [_volume(doc, folder, clock) for doc, folder in docs]
    frames = _frames(store, sid, clock)
    spans = [_span_of_volume(v) for v in volumes] + [_span_of_frame(f) for f in frames]
    starts = [a for a, _ in spans if a is not None]
    ends = [b for _, b in spans if b is not None]
    t0 = min(starts) if starts else None
    t1 = max(ends) if ends else None

    named = [
        {"id": e.get("embryo_id"), "label": e.get("nickname") or e.get("embryo_id")}
        for e in store.list_embryos(sid) or []
    ]
    known = {e["id"] for e in named}
    for v in volumes:
        if v["embryo"] not in known:
            known.add(v["embryo"])
            named.append({"id": v["embryo"], "label": v["embryo"]})

    lines = sorted({int(wl) for v in volumes for wl in (v["lasers"] or v["settings"])})
    return {
        "t0": t0,
        "t1": t1,
        # The rig's clock, for showing a moment as the people at the rig saw it.
        "utc_offset_s": clock.offset,
        "embryos": named,
        "lines": lines,
        "volumes": volumes,
        "bf": frames,
        "temperature": _temperature(store, sid, t0, t1) if t0 is not None else [],
    }

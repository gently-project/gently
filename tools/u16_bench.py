"""Where the uint16 pipeline runs out: the server's cost per frame, the wire's
throughput, and (from the browser, see the notes at the end) the draw. And
the two checks that want the rig: the live frame's cadence through the
device-layer hop, and Corrected with the rig's own dark and flat.

    uv run python tools/u16_bench.py                       # server-side, synthetic frames
    uv run python tools/u16_bench.py --url http://localhost:8080/api/sessions/<sid>/snapshot/<stem>.u16

    # At the rig, with the camera streaming in Operate: how fast one viewer
    # can pull the live frame at ÷2, through the viz relay (or give the
    # device layer's own http://<dl>:<port>/api/bottom_camera/frame.u16).
    uv run python tools/u16_bench.py --live "http://localhost:8080/api/devices/bottom_camera/frame.u16?scale=2"

    # At the rig, for a filed overview frame with dark and flat on file: the
    # corrected counts the route serves against the arithmetic over the
    # rig's own references, pixel for pixel.
    uv run python tools/u16_bench.py --corrected <stem> --session <sid> --storage D:/Gently3

Server side: a 2048² uint16 frame as a TIFF on disk, timed through the same
functions the routes use: read, block mean at 1/2/4, bytes. Wire: the given
.u16 URL fetched repeatedly at scale 1, 2, 4 with 1, 4 and 8 clients at
once; frames per second and MB per second.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def server_side(size: int, reps: int) -> None:
    import numpy as np
    import tifffile

    from gently.core.u16 import u16_payload

    rng = np.random.default_rng(0)
    frame = (rng.normal(2000, 300, (size, size)).clip(0, 65535)).astype(np.uint16)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "frame.tif"
        tifffile.imwrite(str(path), frame)
        print(f"server side, {size}×{size} uint16 ({frame.nbytes / 1e6:.1f} MB), median of {reps}:")
        t = [timed(lambda: tifffile.imread(str(path))) for _ in range(reps)]
        print(f"  read TIFF            {statistics.median(t):7.1f} ms")
        for k in (1, 2, 4, 8):
            t = [timed(lambda k=k: u16_payload(frame, k)) for _ in range(reps)]
            body, _ = u16_payload(frame, k)
            mb = len(body) / 1e6
            print(f"  payload scale {k}      {statistics.median(t):7.1f} ms  → {mb:5.2f} MB")
        from gently.core.imaging import normalize_to_uint8

        t = [timed(lambda: normalize_to_uint8(frame)) for _ in range(reps)]
        print(f"  (old) percentile→u8  {statistics.median(t):7.1f} ms, before the PNG encode")


def timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


def wire(url: str, seconds: float) -> None:
    def one(u: str) -> int:
        with urllib.request.urlopen(u, timeout=30) as r:
            return len(r.read())

    print(f"wire, {url}, {seconds:.0f} s per cell:")
    print("  scale  clients   frames/s   MB/s   ms/frame(median)")
    for scale in (1, 2, 4):
        u = f"{url}{'&' if '?' in url else '?'}scale={scale}"
        size = one(u)
        for clients in (1, 4, 8):
            times: list[float] = []
            stop = time.perf_counter() + seconds
            n = 0

            def worker(u: str = u, stop: float = stop, times: list[float] = times) -> None:
                nonlocal n
                while time.perf_counter() < stop:
                    t0 = time.perf_counter()
                    one(u)
                    times.append((time.perf_counter() - t0) * 1000)
                    n += 1

            with ThreadPoolExecutor(max_workers=clients) as ex:
                for _ in range(clients):
                    ex.submit(worker)
            fps = n / seconds
            mbps = fps * size / 1e6
            med = statistics.median(times)
            print(f"  {scale:<6} {clients:<8} {fps:8.1f}  {mbps:6.1f}   {med:7.1f}")


def live(url: str, seconds: float) -> int:
    """One viewer pulling the live frame as fast as the hop allows: what the
    Operate pane does once per stream frame. Run at the rig while the camera
    streams; against the relay it includes the device-layer hop."""
    times: list[float] = []
    size = 0
    headers: dict[str, str] = {}
    stop = time.perf_counter() + seconds
    try:
        while time.perf_counter() < stop:
            t0 = time.perf_counter()
            with urllib.request.urlopen(url, timeout=30) as r:
                body = r.read()
                if not headers:
                    items = r.headers.items()
                    headers = {k.lower(): v for k, v in items if k.lower().startswith("x-image-")}
            size = len(body)
            times.append((time.perf_counter() - t0) * 1000)
    except urllib.error.HTTPError as exc:
        print(f"live: HTTP {exc.code} from {url}: {exc.read()[:200]!r}")
        print("  (502/503: the microscope is not connected; 404: no frame yet — start the camera)")
        return 1
    if not times:
        print("live: no frame came back")
        return 1
    times.sort()
    med = times[len(times) // 2]
    p95 = times[int(len(times) * 0.95) - 1] if len(times) > 1 else med
    shape = f"{headers.get('x-image-width', '?')}×{headers.get('x-image-height', '?')}"
    scale = headers.get("x-image-scale", "?")
    print(f"live, {url}, {seconds:.0f} s, one viewer:")
    print(f"  frame {shape} at ÷{scale}, {size / 1e6:.2f} MB")
    print(f"  {len(times) / seconds:6.1f} pulls/s · median {med:5.1f} ms · 95th {p95:5.1f} ms")
    print("  The camera streams at 4 Hz on the rig (device_layer._cam_interval_sec); the pane")
    print("  pulls once per stream frame, so anything above 4 pulls/s with headroom is enough.")
    return 0


def corrected(base: str, session_id: str, storage: str, stem: str) -> int:
    """The corrected counts the route serves, against brightfield.correct over
    the dark and flat the session's own record names for this frame."""
    import numpy as np
    import tifffile

    from gently.app import brightfield as bf
    from gently.core.file_store import FileStore

    store = FileStore(Path(storage))
    sd = store._session_dir(session_id)
    if sd is None:
        print(f"corrected: no session {session_id!r} under {storage}")
        return 1
    rec = next(
        (r for r in store.list_snapshots(session_id) if Path(r.get("file_path", "")).stem == stem),
        None,
    )
    if rec is None:
        print(f"corrected: no snapshot {stem!r} in {session_id}")
        return 1
    refs = bf.references_for_frame(rec.get("metadata") or {}, bf.list_records(store, session_id))
    paths = bf.resolve_reference_paths(Path(sd), refs)
    if paths is None:
        print(f"corrected: the session has no dark and flat for {stem!r}'s light and exposure")
        return 1
    dark, flat = (tifffile.imread(str(p)) for p in paths)
    raw_frame = tifffile.imread(str(rec["file_path"]))
    want = bf.correct(raw_frame, dark, flat)

    def fetch(q: str) -> np.ndarray:
        u = f"{base}/api/bf/frames/{stem}.u16{q}"
        with urllib.request.urlopen(u, timeout=60) as r:
            w, h = int(r.headers["X-Image-Width"]), int(r.headers["X-Image-Height"])
            return np.frombuffer(r.read(), "<u2").reshape(h, w)

    raw = fetch("")
    got = fetch("?corrected=1")
    same_raw = np.array_equal(raw, raw_frame)
    diff = int(np.abs(got.astype(np.int64) - want.astype(np.int64)).max())
    names = f"{Path(paths[0]).name} / {Path(paths[1]).name}"
    print(f"corrected, {stem} in {session_id}, references {names}:")
    print(f"  raw route equals the file on disk: {same_raw}")
    print(f"  corrected route vs correct(frame, dark, flat): max |difference| = {diff} counts")
    print(f"  {'OK' if same_raw and diff == 0 else 'MISMATCH'}")
    return 0 if same_raw and diff == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--size", type=int, default=2048, help="frame side for the server-side part")
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--url", help="a .u16 URL on a running server, for the wire part")
    ap.add_argument("--seconds", type=float, default=3.0, help="per wire cell, or for --live")
    ap.add_argument("--live", help="a live frame .u16 URL to pull as one viewer (at the rig)")
    ap.add_argument("--corrected", metavar="STEM", help="check Corrected on this overview frame")
    ap.add_argument("--session", help="the session the frame is filed in (with --corrected)")
    ap.add_argument("--storage", default="D:/Gently3", help="the storage root (with --corrected)")
    ap.add_argument("--base", default="http://localhost:8080", help="the viz server")
    args = ap.parse_args()
    if args.live or args.corrected:
        rc = 0
        if args.live:
            rc |= live(args.live, args.seconds)
        if args.corrected:
            if not args.session:
                ap.error("--corrected needs --session")
            rc |= corrected(args.base, args.session, args.storage, args.corrected)
        return rc
    server_side(args.size, args.reps)
    if args.url:
        wire(args.url, args.seconds)
    print(
        "\nbrowser side: open a frame in the viewer and read view._lastLoadMs (fetch+decode)\n"
        "and view._lastDrawMs (LUT+draw) from the console; the Playwright run in the PR did that."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

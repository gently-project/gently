"""Export a session the way a biologist wants to find it again.

"a nice export method that can organize and store the data in a neat manner
that is easily usable in fiji … volume files or snapshot files that are
sorted by timepoint or something instead of uid in filename … put inside
folder such that it is easier to find the original imprints of the
experiment etc, or stored with metadata files"

The session folder is laid out for the software: one folder per embryo id,
snapshots named by uuid, state in YAML and JSONL. The export is laid out for
the person: one folder per embryo named by what they called it, every file
named so a plain sort is time order, and beside the images the plain-text
record of what the experiment was — the plan, the run, the stage calls, the
events, the temperature, what was said — plus a README that points back at
the originals. Files are copies, never links, so editing an export in Fiji
cannot touch the session.

    <dest>/<session folder name>/
        README.txt
        embryos.csv  stage_calls.csv  events.csv  temperature.csv
        metadata/    session.yaml acquisition.yaml timelapse.yaml events.jsonl
                     temperature.jsonl conversation.json
        <label>/     volumes/<label>_t0001.tif …   volumes.csv
                     projections/<label>_t0001.jpg …
                     embryo.yaml  calibration/  timelapse.mp4
        dic/         dic_f0001_20261004-213000.tif …   dic.csv
                     dic.avi  dic_corrected.avi  references/
                     embryos/<label>/raw/ corrected/ metadata.csv …   (see dic_crops)
                     field_1/ field_2/ …   the same, per field, when the overview
                                           was taken from more than one position

Fiji opens a volumes/ folder with File › Import › Image Sequence…, in order,
and dic.avi with File › Import › AVI… (it is Motion JPEG, which Fiji and
every player read).
"""

from __future__ import annotations

import csv
import json
import logging
import re
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]

_EVENT_TEXT = {
    "ACQUISITION_STARTED",
    "ACQUISITION_COMPLETED",
    "ACQUISITION_STOPPED",
    "ACQUISITION_FAILED",
    "SESSION_RESTORED",
    "TRIGGER_FIRED",
    "BURST_START",
    "BURST_COMPLETE",
    "POWER_RAMP_STEP",
    "HATCHING_DETECTED",
    "DETECTION_TRIGGERED",
    "EMBRYO_TERMINATED",
    "EMBRYO_SKIPPED",
    "OPERATOR_REMOVED_EMBRYO",
    "TEMPERATURE_SETPOINT_CHANGED",
    "TEMP_PROTOCOL_COMPLETED",
    "ERROR_OCCURRED",
    "WARNING_ISSUED",
}


def label_for(embryo: dict[str, Any]) -> str:
    """The folder and file prefix an embryo gets: what it was called, made
    safe for a filename, with its id so two "A"s cannot collide."""
    eid = str(embryo.get("embryo_id") or "embryo")
    nick = str(embryo.get("nickname") or "").strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", nick).strip("-.")
    return f"{safe}_{eid}" if safe and safe.lower() != eid.lower() else eid


def _stamp(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y%m%d-%H%M%S")
    except ValueError:
        return re.sub(r"[^0-9]", "", str(iso))[:14]


def _copy(src: Path, dst: Path, step: Callable[[str], None]) -> bool:
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    step(dst.name)
    return True


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    if not path.is_file():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})


def _ref_path(meta: dict, kind: str, records: list[dict] | None = None) -> str:
    """Where a frame's dark or flat is, inside the export. A frame taken
    before the references existed names none; then the newest complete set
    taken for the frame's own light and exposure stands in — references can
    be taken after the run, and this is how they reach the frames."""
    refs = meta.get("references") or {}
    if not refs.get(kind) and records:
        refs = _references_for(meta, records) or {}
    if not refs.get(kind):
        return ""
    return f"references/{refs.get('record')}/{Path(str(refs[kind])).name}"


def _references_for(meta: dict, records: list[dict]) -> dict | None:
    """The newest complete record whose spec matches the frame's light,
    LED brightness and exposure (see gently.app.brightfield)."""
    from gently.app.brightfield import for_frame, matching, spec_of_frame

    rich = [dict(r, relative=f"calibration/brightfield/{r.get('record')}") for r in records]
    return for_frame(matching(rich, spec_of_frame(meta)))


def _dic_frames(dic_dir: Path) -> list[dict[str, Any]]:
    """The DIC frames of an export's dic/ folder in time order: each with
    its path, when it was captured, and the dark and flat dic.csv names for
    it (relative to dic/). From dic.csv when it is there, else the names."""
    rows: list[dict[str, Any]] = []
    csv_path = dic_dir / "dic.csv"
    if csv_path.is_file():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                name = Path(str(r.get("file") or "")).name
                if name and (dic_dir / name).is_file():
                    rows.append(
                        {
                            "path": dic_dir / name,
                            "captured_at": r.get("captured_at") or None,
                            "dark": r.get("dark") or None,
                            "flat": r.get("flat") or None,
                            "row": dict(r),
                        }
                    )
    if not rows:
        rows = [
            {"path": f, "captured_at": None, "dark": None, "flat": None, "row": {}}
            for f in sorted(dic_dir.glob("dic_f*.tif"))
        ]
    return rows


def _elapsed(start: str | None, now: str | None) -> str:
    """``+HH:MM:SS`` since the first frame, or nothing when the times are
    not known."""
    try:
        if not start or not now:
            return ""
        seconds = int((datetime.fromisoformat(now) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(max(seconds, 0), 3600)
    m, sec = divmod(rest, 60)
    return f"+{h:02d}:{m:02d}:{sec:02d}"


def dic_movie(
    dic_dir: Path,
    fps: int = 10,
    progress: Progress | None = None,
    label: bool = True,
    corrected: bool = False,
) -> Path | None:
    """Write ``dic.avi`` beside an export's DIC frames: every frame in time
    order, one brightness stretch for the whole run (so the movie does not
    flicker with the field), the frame number and the time since the first
    in the corner. Motion JPEG, which Fiji's AVI reader opens.

    ``corrected`` writes ``dic_corrected.avi`` instead, each frame with the
    dark and flat dic.csv names for it divided out first (the formula in the
    README; ``gently.app.brightfield.correct``). A frame with no references,
    or references of another size, goes in as it is.

    The path, or ``None`` when there are no frames, nothing to correct with,
    or OpenCV is not installed."""
    try:
        import cv2
        import numpy as np
        import tifffile
    except ImportError:
        logger.warning("dic.avi skipped: cv2/tifffile not installed")
        return None

    dic_dir = Path(dic_dir)
    frames = _dic_frames(dic_dir)
    if not frames:
        return None
    if corrected and not any(f["dark"] and f["flat"] for f in frames):
        logger.info("dic_corrected.avi skipped: no frame names a dark and flat")
        return None

    def load(path: Path):
        img = np.asarray(tifffile.imread(str(path)))
        img = np.squeeze(img)
        if img.ndim == 3:
            img = img.max(axis=0)
        return img

    # Each dark and flat read once, however many frames share them.
    refs: dict[tuple[str, str], Any] = {}

    def references(frame: dict[str, Any]):
        if not corrected or not frame["dark"] or not frame["flat"]:
            return None
        key = (str(frame["dark"]), str(frame["flat"]))
        if key not in refs:
            try:
                refs[key] = (load(dic_dir / key[0]), load(dic_dir / key[1]))
            except Exception as exc:
                logger.warning("dic_corrected.avi: could not read %s: %s", key, exc)
                refs[key] = None
        return refs[key]

    def read(frame: dict[str, Any]):
        img = load(frame["path"])
        pair = references(frame)
        if pair is not None and pair[0].shape == img.shape and pair[1].shape == img.shape:
            from gently.app.brightfield import correct

            img = correct(img, pair[0], pair[1])
        return img

    # One stretch for the whole run, from frames spread through it.
    sample = frames[:: max(1, len(frames) // 16)][:16]
    lo_hi = [np.percentile(read(f), (0.5, 99.5)) for f in sample]
    lo = float(min(x[0] for x in lo_hi))
    hi = float(max(x[1] for x in lo_hi))
    if hi <= lo:
        hi = lo + 1.0

    out = dic_dir / ("dic_corrected.avi" if corrected else "dic.avi")
    writer = None
    size: tuple[int, int] | None = None
    start = frames[0]["captured_at"]
    written = 0
    try:
        for i, frame_rec in enumerate(frames, start=1):
            path, when = frame_rec["path"], frame_rec["captured_at"]
            try:
                img = read(frame_rec)
            except Exception as exc:
                logger.warning("%s: could not read %s: %s", out.name, path.name, exc)
                continue
            if img.ndim != 2:
                continue
            frame = np.clip((img.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255).astype(
                np.uint8
            )
            if size is None:
                size = (int(frame.shape[1]), int(frame.shape[0]))
                writer = cv2.VideoWriter(
                    str(out),
                    cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
                    int(fps),
                    size,
                    isColor=True,
                )
                if not writer.isOpened():
                    logger.warning("%s skipped: OpenCV could not open an MJPG writer", out.name)
                    return None
            elif (int(frame.shape[1]), int(frame.shape[0])) != size:
                frame = cv2.resize(frame, size)
            bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            if label:
                m = re.match(r"dic_f(\d+)", path.stem)
                text = f"f{int(m.group(1)):04d}" if m else f"#{i}"
                since = _elapsed(start, when)
                if since:
                    text += f"  {since}"
                scale = max(0.6, size[1] / 1000.0)
                thick = max(1, int(round(scale * 2)))
                org = (int(12 * scale), int(size[1] - 14 * scale))
                cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick * 3)
                cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)
            assert writer is not None
            writer.write(bgr)
            written += 1
            if progress:
                progress(i, len(frames), f"{out.name} {path.name}")
    finally:
        if writer is not None:
            writer.release()
    if written == 0:
        out.unlink(missing_ok=True)
        return None
    return out


Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels of the full frame


def _dark_blobs(dic_dir: Path, sample: int = 3) -> tuple[tuple[int, int], list[list[tuple]]]:
    """The dark blobs of ``sample`` frames spread through the run, each as
    (x0, y0, x1, y1, cx, cy): what an embryo looks like to a threshold on
    the flat-fielded frame. Returns the frame shape and one list per frame."""
    import cv2
    import numpy as np
    import tifffile

    dic_dir = Path(dic_dir)
    frames = _dic_frames(dic_dir)
    if not frames:
        raise FileNotFoundError(f"No DIC frames in {dic_dir}")
    picks = frames[:: max(1, (len(frames) - 1) // max(1, sample - 1))][:sample]
    refs: dict[tuple[str, str], tuple] = {}
    shape = None
    out: list[list[tuple]] = []
    for rec in picks:
        img = np.squeeze(np.asarray(tifffile.imread(str(rec["path"]))))
        if img.ndim == 3:
            img = img.max(axis=0)
        shape = img.shape
        if rec["dark"] and rec["flat"]:
            key = (str(rec["dark"]), str(rec["flat"]))
            if key not in refs:
                refs[key] = (
                    tifffile.imread(str(dic_dir / key[0])),
                    tifffile.imread(str(dic_dir / key[1])),
                )
            dark, flat = refs[key]
            if dark.shape == img.shape and flat.shape == img.shape:
                from gently.app.brightfield import correct

                img = correct(img, dark, flat)
        f = img.astype(np.float32)
        bg = float(np.median(f))
        mask: Any = (cv2.GaussianBlur(f, (0, 0), 3) < bg * 0.75).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        n, _labels, stats, cent = cv2.connectedComponentsWithStats(mask)
        least = 0.0005 * img.shape[0] * img.shape[1]
        blobs = []
        for k in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[k])
            if area >= least:
                blobs.append((x, y, x + w, y + h, float(cent[k][0]), float(cent[k][1])))
        out.append(blobs)
    assert shape is not None
    return (int(shape[0]), int(shape[1])), out


def orient_seeds(
    dic_dir: Path, seeds: dict[str, tuple[float, float]], sample: int = 3
) -> dict[str, tuple[float, float]]:
    """The seeds as the frames are oriented. A marking is made on a preview
    that may not be the filed frame's way up — this rig's frames are the
    preview turned by 180° — so the four ways the seeds could sit in the
    frame (as they are, mirrored in x, in y, in both) are each scored by
    how many land on a dark blob in a few frames, and the best is kept.
    A tie keeps them as they are."""
    if not seeds:
        return {}
    (h, w), per_frame = _dark_blobs(dic_dir, sample)
    reach = max(h, w) * 0.1

    def score(flip_x: bool, flip_y: bool) -> int:
        hits = 0
        for cx, cy in seeds.values():
            sx = (w - cx) if flip_x else cx
            sy = (h - cy) if flip_y else cy
            for blobs in per_frame:
                if any(((bx - sx) ** 2 + (by - sy) ** 2) ** 0.5 < reach for *_, bx, by in blobs):
                    hits += 1
                    break
        return hits

    best = (score(False, False), False, False)
    for flip_x, flip_y in ((True, True), (True, False), (False, True)):
        s = score(flip_x, flip_y)
        if s > best[0]:
            best = (s, flip_x, flip_y)
    _, flip_x, flip_y = best
    if not (flip_x or flip_y):
        return dict(seeds)
    logger.info(
        "embryo seeds mirrored%s%s to match the frames",
        " in x" if flip_x else "",
        " in y" if flip_y else "",
    )
    return {
        name: ((w - cx) if flip_x else cx, (h - cy) if flip_y else cy)
        for name, (cx, cy) in seeds.items()
    }


def find_embryo_boxes(
    dic_dir: Path,
    seeds: dict[str, tuple[float, float]],
    margin: int = 40,
    sample: int = 3,
) -> dict[str, Box]:
    """Where each embryo is in the DIC field, as one box that holds it in
    every frame. ``seeds`` is each embryo's approximate centre in full-frame
    pixels (the Operate tab's marking gives these). An embryo is the dark
    blob nearest its seed in the flat-fielded frame, measured in ``sample``
    frames spread through the run and unioned; all boxes are then made the
    same size, so the crops compare. An embryo found in no frame keeps a
    box of the common size around its seed."""
    shape, per_frame = _dark_blobs(dic_dir, sample)
    reach = max(shape) * 0.1
    found: dict[str, list[Box]] = {name: [] for name in seeds}
    for blobs in per_frame:
        for name, (cx, cy) in seeds.items():
            best = None
            for x0, y0, x1, y1, bx, by in blobs:
                d = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
                if d < reach and (best is None or d < best[0]):
                    best = (d, (x0, y0, x1, y1))
            if best is not None:
                found[name].append(best[1])
    boxes: dict[str, Box] = {}
    for name, hits in found.items():
        if hits:
            boxes[name] = (
                min(b[0] for b in hits),
                min(b[1] for b in hits),
                max(b[2] for b in hits),
                max(b[3] for b in hits),
            )
    size_w = max((b[2] - b[0] for b in boxes.values()), default=200) + 2 * margin
    size_h = max((b[3] - b[1] for b in boxes.values()), default=200) + 2 * margin
    out: dict[str, Box] = {}
    for name, (cx, cy) in seeds.items():
        if name in boxes:
            b = boxes[name]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        x0 = int(round(cx - size_w / 2))
        y0 = int(round(cy - size_h / 2))
        x0 = max(0, min(x0, shape[1] - size_w))
        y0 = max(0, min(y0, shape[0] - size_h))
        out[name] = (x0, y0, min(x0 + size_w, shape[1]), min(y0 + size_h, shape[0]))
    return out


def dic_crops(
    dic_dir: Path,
    boxes: dict[str, Box],
    fps: int = 10,
    progress: Progress | None = None,
    label: bool = True,
    notes: dict[str, str] | None = None,
) -> Path:
    """Cut each embryo out of every DIC frame into a folder of its own:

        <dic_dir>/embryos/
            README.md                     a dataset card: what this is, how to load it
            boxes.png                     the boxes drawn on a frame
            boxes.csv                     embryo, x0, y0, x1, y1
            <label>/raw/<label>_f0001_<stamp>.tif …        as taken
            <label>/corrected/<label>_f0001_<stamp>.tif …  shading-corrected:
                                          (frame - dark) / (flat - dark) * mean(flat - dark)
            <label>/dark.tif  flat.tif    the references, cropped the same
            <label>/metadata.csv          one row per frame: file_name (raw),
                                          corrected_file, frame, time, box, references
            <label>/<label>.avi           the raw crops as a movie
            <label>/<label>_corrected.avi the corrected ones

    Laid out as Hugging Face image folders: each embryo loads with
    ``load_dataset("imagefolder", data_dir=".../embryos/<label>")``, and the
    whole folder uploads as one dataset. ``notes`` is what to say about an
    embryo ("dead; kept as an anomalous case"): in the card, in boxes.csv,
    and in every one of its rows. The crop is the same box in every frame,
    so a crop plays as a fixed camera on one embryo. Returns the embryos/
    folder."""
    import cv2
    import numpy as np
    import tifffile

    dic_dir = Path(dic_dir)
    frames = _dic_frames(dic_dir)
    if not frames:
        raise FileNotFoundError(f"No DIC frames in {dic_dir}")
    root = dic_dir / "embryos"
    root.mkdir(parents=True, exist_ok=True)
    notes = notes or {}
    _write_csv(
        root / "boxes.csv",
        [
            {"embryo": k, "x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3], "note": notes.get(k, "")}
            for k, b in boxes.items()
        ],
        ["embryo", "x0", "y0", "x1", "y1", "note"],
    )

    refs: dict[tuple[str, str], tuple | None] = {}

    def references(rec: dict[str, Any]):
        if not rec["dark"] or not rec["flat"]:
            return None
        key = (str(rec["dark"]), str(rec["flat"]))
        if key not in refs:
            try:
                refs[key] = (
                    tifffile.imread(str(dic_dir / key[0])),
                    tifffile.imread(str(dic_dir / key[1])),
                )
            except Exception as exc:
                logger.warning("crops: could not read %s: %s", key, exc)
                refs[key] = None
        return refs[key]

    def load(rec: dict[str, Any]):
        img = np.squeeze(np.asarray(tifffile.imread(str(rec["path"]))))
        if img.ndim == 3:
            img = img.max(axis=0)
        pair = references(rec)
        fixed = None
        if pair is not None and pair[0].shape == img.shape and pair[1].shape == img.shape:
            from gently.app.brightfield import correct

            fixed = correct(img, pair[0], pair[1])
        return img, fixed, pair

    def cut(a, b: Box):
        return a[b[1] : b[3], b[0] : b[2]]

    # One stretch per embryo, raw and corrected, from frames spread through.
    picks = frames[:: max(1, len(frames) // 8)][:8]
    lo_hi: dict[tuple[str, bool], list] = {}
    for rec in picks:
        img, fixed, _ = load(rec)
        for name, box in boxes.items():
            lo_hi.setdefault((name, False), []).append(np.percentile(cut(img, box), (0.5, 99.5)))
            if fixed is not None:
                lo_hi.setdefault((name, True), []).append(
                    np.percentile(cut(fixed, box), (0.5, 99.5))
                )

    def stretch(name: str, corrected: bool) -> tuple[float, float]:
        xs = lo_hi.get((name, corrected)) or [(0.0, 1.0)]
        lo = float(min(x[0] for x in xs))
        hi = float(max(x[1] for x in xs))
        return lo, (hi if hi > lo else lo + 1.0)

    writers: dict[tuple[str, bool], Any] = {}
    rows: dict[str, list[dict]] = {name: [] for name in boxes}
    start = frames[0]["captured_at"]
    try:
        for i, rec in enumerate(frames, start=1):
            try:
                img, fixed, pair = load(rec)
            except Exception as exc:
                logger.warning("crops: could not read %s: %s", rec["path"].name, exc)
                continue
            m = re.match(r"dic_f(\d+)", rec["path"].stem)
            fnum = int(m.group(1)) if m else i
            since = _elapsed(start, rec["captured_at"])
            for name, box in boxes.items():
                edir = root / name
                edir.mkdir(exist_ok=True)
                if i == 1 and pair is not None:
                    tifffile.imwrite(edir / "dark.tif", cut(pair[0], box))
                    tifffile.imwrite(edir / "flat.tif", cut(pair[1], box))
                crop = cut(img, box)
                stamp = _stamp(rec["captured_at"]) if rec["captured_at"] else ""
                fname = f"{name}_f{fnum:04d}" + (f"_{stamp}" if stamp else "") + ".tif"
                (edir / "raw").mkdir(exist_ok=True)
                tifffile.imwrite(edir / "raw" / fname, crop)
                if fixed is not None:
                    (edir / "corrected").mkdir(exist_ok=True)
                    tifffile.imwrite(edir / "corrected" / fname, cut(fixed, box))
                meta = rec.get("row") or {}
                rows[name].append(
                    {
                        "file_name": f"raw/{fname}",
                        "corrected_file": f"corrected/{fname}" if fixed is not None else "",
                        "embryo": name,
                        "frame": fnum,
                        "captured_at": rec["captured_at"],
                        "elapsed_s": _elapsed_s(start, rec["captured_at"]),
                        "source_frame": rec["path"].name,
                        "x0": box[0],
                        "y0": box[1],
                        "x1": box[2],
                        "y1": box[3],
                        "dark_file": "dark.tif" if pair is not None else "",
                        "flat_file": "flat.tif" if pair is not None else "",
                        "light": meta.get("light", ""),
                        "led_intensity_pct": meta.get("led_intensity_pct", ""),
                        "exposure_ms": meta.get("exposure_ms", ""),
                        "stage_x_um": meta.get("x_um", ""),
                        "stage_y_um": meta.get("y_um", ""),
                        "note": notes.get(name, ""),
                    }
                )
                for corrected, src in (
                    (False, crop),
                    (True, cut(fixed, box) if fixed is not None else None),
                ):
                    if src is None:
                        continue
                    lo, hi = stretch(name, corrected)
                    g = np.clip((src.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255).astype(
                        np.uint8
                    )
                    bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
                    key = (name, corrected)
                    if key not in writers and min(g.shape[:2]) < 16:
                        # Motion JPEG cannot encode a frame this small, and
                        # OpenCV corrupts memory trying. The crops are kept.
                        logger.warning("%s: crop %s too small for a movie", name, g.shape)
                        writers[key] = None
                    if key not in writers:
                        out = edir / (f"{name}_corrected.avi" if corrected else f"{name}.avi")
                        w = cv2.VideoWriter(
                            str(out),
                            cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
                            int(fps),
                            (int(g.shape[1]), int(g.shape[0])),
                            isColor=True,
                        )
                        writers[key] = w if w.isOpened() else None
                        if writers[key] is None:
                            logger.warning("%s skipped: no MJPG writer", out.name)
                    w = writers[key]
                    if w is None:
                        continue
                    if label:
                        text = f"f{fnum:04d}" + (f"  {since}" if since else "")
                        scale = max(0.4, g.shape[1] / 600.0)
                        thick = max(1, int(round(scale * 2)))
                        org = (int(8 * scale), int(g.shape[0] - 10 * scale))
                        cv2.putText(
                            bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick * 3
                        )
                        cv2.putText(
                            bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick
                        )
                    w.write(bgr)
            if progress:
                progress(i, len(frames), f"embryos {rec['path'].name}")
            if i == max(1, len(frames) // 2):
                # The boxes, drawn on a frame from the middle of the run.
                shown = fixed if fixed is not None else img
                lo, hi = np.percentile(shown, (0.5, 99.5))
                g = np.clip(
                    (shown.astype(np.float32) - lo) / (hi - lo + 1e-9) * 255, 0, 255
                ).astype(np.uint8)
                bgr = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
                t = max(1, g.shape[1] // 700)
                for name, b in boxes.items():
                    cv2.rectangle(bgr, (b[0], b[1]), (b[2], b[3]), (0, 0, 255), t * 2)
                    cv2.putText(
                        bgr,
                        name,
                        (b[0], max(0, b[1] - 8 * t)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7 * t,
                        (0, 0, 255),
                        t * 2,
                    )
                cv2.imwrite(str(root / "boxes.png"), bgr)
    finally:
        for w in writers.values():
            if w is not None:
                w.release()
    columns = [
        "file_name",
        "corrected_file",
        "embryo",
        "frame",
        "captured_at",
        "elapsed_s",
        "source_frame",
        "x0",
        "y0",
        "x1",
        "y1",
        "dark_file",
        "flat_file",
        "light",
        "led_intensity_pct",
        "exposure_ms",
        "stage_x_um",
        "stage_y_um",
        "note",
    ]
    for name, rs in rows.items():
        if rs:
            _write_csv(root / name / "metadata.csv", rs, columns)
    (root / "README.md").write_text(
        _crops_card(dic_dir, boxes, rows, start, notes), encoding="utf-8"
    )
    return root


def _elapsed_s(start: str | None, now: str | None) -> str:
    try:
        if not start or not now:
            return ""
        seconds = (datetime.fromisoformat(now) - datetime.fromisoformat(start)).total_seconds()
        return f"{seconds:.1f}"
    except (TypeError, ValueError):
        return ""


def _crops_card(
    dic_dir: Path,
    boxes: dict[str, Box],
    rows: dict[str, list[dict]],
    start,
    notes: dict[str, str] | None = None,
) -> str:
    """The dataset card for the embryos/ folder: YAML front matter the Hub
    reads, then what the files are and how to load them."""
    notes = notes or {}
    names = [n for n in boxes if rows.get(n)]
    n_frames = max((len(rows[n]) for n in names), default=0)
    total = n_frames * len(names)
    size = "n<1K" if total < 1000 else "1K<n<10K" if total < 10000 else "10K<n<100K"
    session = dic_dir.parent.name
    first = names[0] if names else "<embryo>"
    lines = [
        "---",
        f"pretty_name: DIC time-lapse of C. elegans embryos, {session}",
        "tags:",
        "- microscopy",
        "- brightfield",
        "- c-elegans",
        "- embryo",
        "- time-lapse",
        "size_categories:",
        f"- {size}",
        "---",
        "",
        f"# {session}: one folder per embryo",
        "",
        f"Gently session `{session}`. Each embryo was cut out of every DIC overview frame",
        "with one fixed box, so a folder plays as a fixed camera on one embryo.",
        f"{len(names)} embryo(s), {n_frames} frames each"
        + (f", from {start}" if start else "")
        + ".",
        "",
        "## Embryos",
        "",
        "| embryo | box (x0, y0, x1, y1) | note |",
        "|---|---|---|",
        *[f"| {n} | {', '.join(str(v) for v in boxes[n])} | {notes.get(n, '')} |" for n in names],
        "",
        "## Layout",
        "",
        "```",
        "<embryo>/raw/<embryo>_f0001_<stamp>.tif        the crop as the camera took it (16-bit)",
        "<embryo>/corrected/<embryo>_f0001_<stamp>.tif  the same crop, shading-corrected (16-bit)",
        "<embryo>/dark.tif  <embryo>/flat.tif            the references, cropped to the same box",
        "<embryo>/metadata.csv                           one row per frame (see below)",
        "<embryo>/<embryo>.avi  <embryo>_corrected.avi   the crops as movies, for watching",
        "boxes.csv  boxes.png                            where each box sits in the full frame",
        "```",
        "",
        "## Shading correction",
        "",
        "Dark-corrected and flat-fielded, in the frame's own 16-bit range:",
        "",
        "    corrected = (raw - dark) / (flat - dark) * mean(flat - dark)",
        "",
        "`dark` is a frame with the light off; `flat` is the empty field under the same",
        "light. Both are cropped to the embryo's box beside the crops.",
        "",
        "## metadata.csv",
        "",
        "| column | meaning |",
        "|---|---|",
        "| file_name | the raw crop, relative to the embryo folder |",
        "| corrected_file | its shading-corrected twin |",
        "| embryo, frame | which embryo, which overview frame (1 = first) |",
        "| captured_at, elapsed_s | when, and seconds since the first frame |",
        "| source_frame | the full-field frame this was cut from (in `../`) |",
        "| x0, y0, x1, y1 | the box in the full frame, pixels |",
        "| dark_file, flat_file | the references used, in the embryo folder |",
        "| light, led_intensity_pct, exposure_ms | how the frame was lit |",
        "| stage_x_um, stage_y_um | where the stage was |",
        "| note | anything said about the embryo (empty if nothing) |",
        "",
        "## Loading",
        "",
        "```python",
        "from datasets import load_dataset",
        f'ds = load_dataset("imagefolder", data_dir="{first}")',
        '# ds["train"][0]["image"] is the raw crop; the other columns come from metadata.csv',
        "```",
        "",
        "## Uploading",
        "",
        "```",
        "huggingface-cli upload <user>/<dataset-name> . --repo-type dataset",
        "```",
        "",
        "Run from this folder. Fill in `license:` above first.",
        "",
    ]
    return "\n".join(lines)


def marking_seeds(
    store: Any,
    session_id: str,
    embryos: list[dict],
    position: dict | None = None,
) -> dict[str, tuple[float, float]]:
    """Where each embryo is in the full DIC frame, keyed by its export label.

    From the Operate tab's marking (the newest): the preview's pixel
    positions scaled to the frame, each mark given to the embryo whose
    stage position is nearest, within 50 µm.

    With ``position`` — a field of a run taken from several — the marking
    was made somewhere else, so its pixels are not this field's. The marks
    say how stage microns map to frame pixels (fitted when they are spread
    enough, else from the marking's recorded pixel size), and each embryo's
    own stage position is projected into the field. An embryo outside it,
    or within a tenth of the frame of its edge (its crop would be cut), is
    left out. ``{}`` with no marking."""
    marks = store.list_snapshots(session_id, "operate_marked") or []
    if not marks:
        return {}
    mark = max(marks, key=lambda r: str(r.get("captured_at") or ""))
    meta = mark.get("metadata") or {}
    frame = meta.get("frame") or {}
    preview_w = float(frame.get("width") or mark.get("width") or 0)
    preview_h = float(frame.get("height") or mark.get("height") or preview_w)
    if not preview_w:
        return {}
    dics = store.list_snapshots(session_id, "dic") or []
    full_w = float(next((r.get("width") for r in dics if r.get("width")), 0) or 0)
    if not full_w:
        full_w = preview_w * float(frame.get("downsample") or 1)
    k = full_w / preview_w

    pairs = []
    for m in meta.get("embryos") or []:
        try:
            pairs.append(
                (
                    float(m["pixel_x"]),
                    float(m["pixel_y"]),
                    float(m["stage_x_um"]),
                    float(m["stage_y_um"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    def stage_of(e: dict) -> tuple[float, float] | None:
        pos = e.get("position_coarse") or {}
        ex, ey = pos.get("x", e.get("position_x")), pos.get("y", e.get("position_y"))
        try:
            return (float(ex), float(ey)) if ex is not None and ey is not None else None
        except (TypeError, ValueError):
            return None

    seeds: dict[str, tuple[float, float]] = {}
    at = meta.get("stage_position")
    if position is None or position.get("x") is None or not isinstance(at, list | tuple):
        # The marking's own field: each mark to the embryo it is nearest.
        for px, py, sx, sy in pairs:
            best: tuple[float, dict] | None = None
            for e in embryos:
                st = stage_of(e)
                if st is None:
                    continue
                d = ((st[0] - sx) ** 2 + (st[1] - sy) ** 2) ** 0.5
                if best is None or d < best[0]:
                    best = (d, e)
            if best is not None and best[0] <= 50.0:
                seeds[label_for(best[1])] = (px * k, py * k)
        return seeds

    # Another field: pixel = c + g * (stage - field), per axis, from the marks.
    try:
        mx, my = float(at[0]), float(at[1])
    except (TypeError, ValueError, IndexError):
        return {}
    um_per_px = None
    tr = meta.get("transform") or {}
    try:
        if tr.get("pixel_size_um") and tr.get("objective_mag"):
            um_per_px = (
                float(tr["pixel_size_um"])
                / float(tr["objective_mag"])
                * float(frame.get("downsample") or 1)
            )
    except (TypeError, ValueError):
        um_per_px = None

    def axis(pix: list[float], stage: list[float], centre: float) -> tuple[float, float]:
        """(c, g) for pixel = c + g * (stage - mark): fitted from marks spread
        more than 50 µm apart, else the recorded pixel size through the
        marking's centre, else nothing to go on."""
        if len(pix) >= 2 and max(stage) - min(stage) > 50.0:
            n = len(pix)
            ms, mp = sum(stage) / n, sum(pix) / n
            var = sum((x - ms) ** 2 for x in stage)
            g = sum((x - ms) * (y - mp) for x, y in zip(stage, pix, strict=True)) / var
            return mp - g * ms, g
        if um_per_px:
            return centre, 1.0 / um_per_px
        raise ValueError("the marking does not say how microns map to pixels")

    try:
        cx, gx = axis([p[0] for p in pairs], [p[2] - mx for p in pairs], preview_w / 2)
        cy, gy = axis([p[1] for p in pairs], [p[3] - my for p in pairs], preview_h / 2)
    except ValueError:
        return {}
    fx, fy = float(position["x"]), float(position["y"])
    for e in embryos:
        st = stage_of(e)
        if st is None:
            continue
        px = cx + gx * (st[0] - fx)
        py = cy + gy * (st[1] - fy)
        if 0.1 * preview_w <= px <= 0.9 * preview_w and 0.1 * preview_h <= py <= 0.9 * preview_h:
            seeds[label_for(e)] = (px * k, py * k)
    return seeds


def _volume_files(folder: Path) -> list[Path]:
    """The volumes of a folder in time order: ``t0001.tif`` as the store
    names them, ``<label>_t0001.tif`` as the export does, else every .tif
    by name."""
    folder = Path(folder)
    files = sorted(p for p in folder.glob("*.tif") if re.search(r"t\d{4}$", p.stem))
    if not files:
        files = sorted(folder.glob("*.tif")) + sorted(folder.glob("*.tiff"))
    return [f for f in files if f.is_file()]


def spim_movie(
    folder: Path,
    view: str = "projection",
    fps: int = 10,
    progress: Progress | None = None,
    label: bool = True,
) -> Path | None:
    """Write a movie of a folder of volumes (an export's ``<embryo>/volumes``,
    or a session's). Not the DIC movie: a volume is a stack, and there are
    two ways to watch one.

    ``view="projection"`` writes ``spim_projection.avi``: the max projection
    of each volume, one frame per timepoint, in time order.
    ``view="slices"`` writes ``spim_slices.avi``: every slice of every volume,
    stack by stack, so a stack plays through before the next begins.

    One brightness stretch for the run, the timepoint (and slice) in the
    corner, Motion JPEG for Fiji. The path, or ``None`` when there are no
    volumes or OpenCV is not installed."""
    if view not in ("projection", "slices"):
        raise ValueError(f"view must be 'projection' or 'slices', not {view!r}")
    try:
        import cv2
        import numpy as np
        import tifffile
    except ImportError:
        logger.warning("spim movie skipped: cv2/tifffile not installed")
        return None

    folder = Path(folder)
    files = _volume_files(folder)
    if not files:
        return None

    def load(path: Path):
        arr = np.squeeze(np.asarray(tifffile.imread(str(path))))
        if arr.ndim == 2:
            arr = arr[None]
        elif arr.ndim > 3:
            arr = arr.reshape(-1, *arr.shape[-2:])
        return arr

    def timepoint(path: Path, i: int) -> int:
        m = re.search(r"t(\d{4})$", path.stem)
        return int(m.group(1)) if m else i

    # One stretch for the run, from volumes spread through it: of the
    # projections for the projection view, of the stacks for the slices.
    sample = files[:: max(1, len(files) // 8)][:8]
    lo_hi = []
    for path in sample:
        vol = load(path)
        lo_hi.append(
            np.percentile(vol.max(axis=0), (0.5, 99.5))
            if view == "projection"
            else np.percentile(vol, (0.5, 99.9))
        )
    lo = float(min(x[0] for x in lo_hi))
    hi = float(max(x[1] for x in lo_hi))
    if hi <= lo:
        hi = lo + 1.0

    out = folder / f"spim_{view}.avi"
    writer = None
    size: tuple[int, int] | None = None
    written = 0

    def put(img, text: str) -> bool:
        nonlocal writer, size, written
        frame = np.clip((img.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
        if size is None:
            size = (int(frame.shape[1]), int(frame.shape[0]))
            writer = cv2.VideoWriter(
                str(out),
                cv2.VideoWriter_fourcc(*"MJPG"),  # type: ignore[attr-defined]
                int(fps),
                size,
                isColor=True,
            )
            if not writer.isOpened():
                logger.warning("%s skipped: OpenCV could not open an MJPG writer", out.name)
                return False
        elif (int(frame.shape[1]), int(frame.shape[0])) != size:
            frame = cv2.resize(frame, size)
        bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        if label:
            scale = max(0.6, size[1] / 1000.0)
            thick = max(1, int(round(scale * 2)))
            org = (int(12 * scale), int(size[1] - 14 * scale))
            cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick * 3)
            cv2.putText(bgr, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)
        assert writer is not None
        writer.write(bgr)
        written += 1
        return True

    try:
        for i, path in enumerate(files, start=1):
            try:
                vol = load(path)
            except Exception as exc:
                logger.warning("%s: could not read %s: %s", out.name, path.name, exc)
                continue
            tp = timepoint(path, i)
            if view == "projection":
                if not put(vol.max(axis=0), f"t{tp:04d}"):
                    return None
            else:
                for z in range(vol.shape[0]):
                    if not put(vol[z], f"t{tp:04d}  z{z + 1:03d}/{vol.shape[0]}"):
                        return None
            if progress:
                progress(i, len(files), f"{out.name} {path.name}")
    finally:
        if writer is not None:
            writer.release()
    if written == 0:
        out.unlink(missing_ok=True)
        return None
    return out


def plan_lines(plan: dict | None) -> list[str]:
    """The acquisition plan in sentences, for the README."""
    if not plan:
        return ["No acquisition plan was recorded for this session."]
    out: list[str] = []
    if plan.get("interval_seconds"):
        out.append(f"Interval: every {plan['interval_seconds']} s")
    if plan.get("volumes") is False:
        out.append("Volumes: off (brightfield only)")
    else:
        vol = []
        if plan.get("num_slices") is not None:
            vol.append(f"{plan['num_slices']} slices")
        if plan.get("exposure_ms") is not None:
            vol.append(f"{plan['exposure_ms']} ms exposure")
        if vol:
            out.append("Volumes: " + ", ".join(vol))
        lasers = []
        if plan.get("laser_config"):
            lasers.append(str(plan["laser_config"]).replace("_", " "))
        for wl, pct in (plan.get("laser_powers") or {}).items():
            lasers.append(f"{wl} nm at {pct}%")
        if lasers:
            out.append("Laser: " + ", ".join(lasers))
    # The orchestrator writes the stop condition as a string ("duration:12h",
    # "hatching", "manual") with a sibling ``condition_value``; older plans and
    # templates carry a dict. Either way it is one line.
    stop = plan.get("stop_condition")
    if isinstance(stop, dict):
        kind = stop.get("kind") or stop.get("condition_type") or stop.get("type")
        value = stop.get("value")
    else:
        kind = stop
        value = plan.get("condition_value")
    if kind:
        out.append(f"Stop: {kind}" + (f" {value}" if value is not None else ""))
    dic = plan.get("dic") or {}
    if dic.get("enabled"):
        bits = []
        if dic.get("every_seconds"):
            bits.append(f"every {dic['every_seconds']} s")
        if len(dic.get("positions") or []) > 1:
            bits.append(f"from {len(dic['positions'])} positions")
        if dic.get("light"):
            bits.append(
                f"{dic['light']}"
                + (
                    f" {dic['led_intensity_pct']}%"
                    if dic.get("led_intensity_pct") is not None
                    else ""
                )
            )
        if dic.get("exposure_ms") is not None:
            bits.append(f"{dic['exposure_ms']} ms")
        out.append("DIC overview: " + ", ".join(bits))
    else:
        out.append("DIC overview: off")
    return out


def export_session(
    store: Any,
    session_id: str,
    dest: Path | None = None,
    progress: Progress | None = None,
    crops: bool = True,
) -> Path:
    """Write the export of ``session_id`` under ``dest`` (default
    ``<root>/exports``) and return its folder. Re-exporting overwrites the
    same folder. ``progress(done, total, what)`` is called per file.
    ``crops`` also cuts each embryo out of the DIC frames into a Hugging
    Face folder of its own (see ``dic_crops``), where the session has an
    Operate marking to say where the embryos are."""
    sd = store._session_dir(session_id)
    if sd is None or not Path(sd).exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    sd = Path(sd)
    out = Path(dest) if dest else Path(store.root) / "exports"
    out = out / sd.name
    out.mkdir(parents=True, exist_ok=True)

    info = store.get_session(session_id) or {}
    embryos = store.list_embryos(session_id) or []
    plan = store.get_acquisition_plan(session_id)
    volumes = store.list_volumes(session_id) or []
    snapshots = store.list_snapshots(session_id, "dic") or []
    predictions = store.get_predictions(session_id) or []

    # Everything that will be copied, counted first so progress means something.
    has_refs = (sd / "calibration" / "brightfield").is_dir()
    seeds = marking_seeds(store, session_id, embryos) if crops else {}
    total = (
        len(volumes)
        + ((3 if has_refs else 2) + (1 if seeds else 0)) * len(snapshots)
        + sum(
            len(store.list_projection_timepoints(session_id, e["embryo_id"]) or []) for e in embryos
        )
        + 6
    )
    done = 0

    def step(what: str) -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done, total, what)

    # --- the record, as it was kept -----------------------------------------
    meta_dir = out / "metadata"
    for name in (
        "session.yaml",
        "acquisition.yaml",
        "timelapse.yaml",
        "events.jsonl",
        "temperature.jsonl",
        "conversation.json",
        "decisions.jsonl",
    ):
        _copy(sd / name, meta_dir / name, lambda _n: None)

    # --- the record, as a person reads it ----------------------------------
    by_embryo_preds: dict[str, list[dict]] = {}
    for p in predictions:
        by_embryo_preds.setdefault(str(p.get("embryo_id")), []).append(p)

    checkpoint: dict = {}
    try:
        doc = yaml.safe_load((sd / "timelapse.yaml").read_text(encoding="utf-8"))
        checkpoint = doc if isinstance(doc, dict) else {}
    except (OSError, yaml.YAMLError):
        checkpoint = {}
    rows_ck = checkpoint.get("embryos") or {}

    embryo_rows = []
    for e in embryos:
        eid = e["embryo_id"]
        pos = e.get("position_coarse") or {}
        preds = by_embryo_preds.get(eid, [])
        ck = rows_ck.get(eid) or {}
        embryo_rows.append(
            {
                "label": label_for(e),
                "embryo_id": eid,
                "nickname": e.get("nickname"),
                "role": e.get("role"),
                "strain": e.get("strain"),
                "x_um": pos.get("x", e.get("position_x")),
                "y_um": pos.get("y", e.get("position_y")),
                "timepoints": len([v for v in volumes if v["embryo_id"] == eid]),
                "last_stage": preds[-1].get("predicted_stage") if preds else "",
                "complete": ck.get("is_complete"),
                "completion_reason": ck.get("completion_reason"),
                "total_exposure_ms": ck.get("total_exposure_ms"),
            }
        )
    _write_csv(
        out / "embryos.csv",
        embryo_rows,
        [
            "label",
            "embryo_id",
            "nickname",
            "role",
            "strain",
            "x_um",
            "y_um",
            "timepoints",
            "last_stage",
            "complete",
            "completion_reason",
            "total_exposure_ms",
        ],
    )
    step("embryos.csv")

    labels = {r["embryo_id"]: r["label"] for r in embryo_rows}
    _write_csv(
        out / "stage_calls.csv",
        [
            {
                "label": labels.get(str(p.get("embryo_id")), p.get("embryo_id")),
                "embryo_id": p.get("embryo_id"),
                "timepoint": p.get("timepoint"),
                "stage": p.get("predicted_stage"),
                "confidence": p.get("confidence"),
                "transitional": p.get("is_transitional"),
                "reasoning": p.get("reasoning"),
            }
            for p in sorted(
                predictions, key=lambda p: (str(p.get("embryo_id")), p.get("timepoint") or 0)
            )
        ],
        ["label", "embryo_id", "timepoint", "stage", "confidence", "transitional", "reasoning"],
    )
    step("stage_calls.csv")

    events = [
        {
            "time": r.get("timestamp"),
            "type": r.get("event_type") or r.get("type"),
            "data": json.dumps(r.get("data"), default=str) if r.get("data") is not None else "",
        }
        for r in _read_jsonl(sd / "events.jsonl")
        if (r.get("event_type") or r.get("type")) in _EVENT_TEXT
    ]
    _write_csv(out / "events.csv", events, ["time", "type", "data"])
    step("events.csv")

    _write_csv(
        out / "temperature.csv",
        [
            {
                "time": r.get("t"),
                "water_c": r.get("water_c"),
                "setpoint_c": r.get("setpoint_c"),
                "state": r.get("state"),
            }
            for r in _read_jsonl(sd / "temperature.jsonl")
        ],
        ["time", "water_c", "setpoint_c", "state"],
    )
    step("temperature.csv")

    # --- the images, one folder per embryo, in time order --------------------
    for e in embryos:
        eid = e["embryo_id"]
        label = labels[eid]
        edir = out / label
        src_e = sd / "embryos" / eid
        _copy(src_e / "embryo.yaml", edir / "embryo.yaml", lambda _n: None)
        _copy(src_e / "timelapse.mp4", edir / "timelapse.mp4", lambda _n: None)
        if (src_e / "calibration").is_dir():
            shutil.copytree(src_e / "calibration", edir / "calibration", dirs_exist_ok=True)

        vol_rows = []
        for v in sorted(
            (v for v in volumes if v["embryo_id"] == eid), key=lambda v: v["timepoint"]
        ):
            tp = int(v["timepoint"])
            name = f"{label}_t{tp:04d}.tif"
            _copy(Path(v["file_path"]), edir / "volumes" / name, step)
            meta = v.get("metadata") or {}
            shape = v.get("shape") or []
            vol_rows.append(
                {
                    "file": f"volumes/{name}",
                    "timepoint": tp,
                    "acquired_at": v.get("acquired_at"),
                    "z": shape[0] if len(shape) == 3 else "",
                    "y": shape[-2] if len(shape) >= 2 else "",
                    "x": shape[-1] if len(shape) >= 2 else "",
                    "dtype": v.get("dtype"),
                    "num_slices": meta.get("num_slices"),
                    "exposure_ms": meta.get("exposure_ms"),
                    "interval_seconds": meta.get("interval_seconds"),
                    "laser_488_pct": meta.get("laser_power_488_pct"),
                    "laser_561_pct": meta.get("laser_power_561_pct"),
                    "laser_405_pct": meta.get("laser_power_405_pct"),
                    "laser_637_pct": meta.get("laser_power_637_pct"),
                    "acquisition_mode": meta.get("acquisition_mode"),
                }
            )
        if vol_rows:
            _write_csv(
                edir / "volumes.csv",
                vol_rows,
                [
                    "file",
                    "timepoint",
                    "acquired_at",
                    "z",
                    "y",
                    "x",
                    "dtype",
                    "num_slices",
                    "exposure_ms",
                    "interval_seconds",
                    "laser_488_pct",
                    "laser_561_pct",
                    "laser_405_pct",
                    "laser_637_pct",
                    "acquisition_mode",
                ],
            )
        for tp in store.list_projection_timepoints(session_id, eid) or []:
            src = store.get_projection_path(session_id, eid, tp)
            if src is not None:
                _copy(Path(src), edir / "projections" / f"{label}_t{int(tp):04d}.jpg", step)

    # --- the dark and flat references, beside the frames they correct ------
    refs_src = sd / "calibration" / "brightfield"
    ref_records: list[dict] = []
    if refs_src.is_dir():
        shutil.copytree(refs_src, out / "dic" / "references", dirs_exist_ok=True)
        for entry in sorted(refs_src.iterdir()):
            rec = entry / "brightfield.yaml"
            if rec.is_file():
                try:
                    doc = yaml.safe_load(rec.read_text(encoding="utf-8")) or {}
                except (OSError, yaml.YAMLError):
                    doc = {}
                if isinstance(doc, dict):
                    doc["record"] = doc.get("record") or entry.name
                    ref_records.append(doc)

    # --- the DIC overview, by frame then time, not by uuid ------------------
    # Taken from more than one position, the overview is one series per
    # field, each in a folder of its own with its own table and movies.
    n_fields = max(
        (int((r.get("metadata") or {}).get("fields") or 1) for r in snapshots), default=1
    )
    multi = n_fields > 1

    def dic_dir_of(field_no: int) -> Path:
        return out / "dic" / f"field_{field_no}" if multi else out / "dic"

    dic_rows = []
    rows_by_field: dict[int, list[dict]] = {}
    field_positions: dict[int, dict] = {}
    for i, rec in enumerate(
        sorted(
            snapshots,
            key=lambda r: (
                (r.get("metadata") or {}).get("frame") or 0,
                (r.get("metadata") or {}).get("field") or 1,
                r.get("captured_at") or "",
            ),
        ),
        start=1,
    ):
        meta = rec.get("metadata") or {}
        frame = int(meta.get("frame") or i)
        field_no = int(meta.get("field") or 1)
        when = meta.get("captured_at") or rec.get("captured_at")
        name = f"dic_f{frame:04d}_{_stamp(when)}.tif" if when else f"dic_f{frame:04d}.tif"
        if _copy(Path(rec.get("file_path") or ""), dic_dir_of(field_no) / name, step):
            pos = meta.get("position") or {}
            if pos and field_no not in field_positions:
                field_positions[field_no] = dict(pos)
            dark, flat = _ref_path(meta, "dark", ref_records), _ref_path(meta, "flat", ref_records)
            if multi:
                dark, flat = (f"../{dark}" if dark else ""), (f"../{flat}" if flat else "")
            row = {
                "file": f"dic/field_{field_no}/{name}" if multi else f"dic/{name}",
                "frame": frame,
                "field": field_no,
                "round": meta.get("round"),
                "captured_at": when,
                "x_um": pos.get("x"),
                "y_um": pos.get("y"),
                "exposure_ms": meta.get("exposure_ms"),
                "light": meta.get("light"),
                "led_intensity_pct": meta.get("led_intensity_pct"),
                "width": rec.get("width"),
                "height": rec.get("height"),
                "dark": dark,
                "flat": flat,
            }
            dic_rows.append(row)
            rows_by_field.setdefault(field_no, []).append(row)
    for field_no, rows_f in sorted(rows_by_field.items()):
        _write_csv(
            dic_dir_of(field_no) / "dic.csv",
            rows_f,
            [
                "file",
                "frame",
                "field",
                "round",
                "captured_at",
                "x_um",
                "y_um",
                "exposure_ms",
                "light",
                "led_intensity_pct",
                "width",
                "height",
                "dark",
                "flat",
            ],
        )
    step("dic.csv")

    # --- the DIC frames as a movie, to watch the night go by: as taken, and
    # with the dark and flat divided out where there are any ----------------
    movies = [False, True] if (dic_rows and ref_records) else [False] if dic_rows else []
    for corrected in movies:
        base = done
        for field_no, rows_f in sorted(rows_by_field.items()):
            at = base

            def movie_progress(i: int, _n: int, what: str) -> None:
                nonlocal done
                done = at + i  # noqa: B023
                if progress:
                    progress(done, total, what)

            try:
                dic_movie(dic_dir_of(field_no), progress=movie_progress, corrected=corrected)
            except Exception:
                logger.exception("the DIC movie failed; the frames are exported without it")
            base = at + len(rows_f)
        done = base

    # --- each embryo cut out of the DIC frames, a dataset folder each --------
    # With more than one field, each field has its own marking (the operator
    # marked the embryos at each position) and its own embryos/ folder.
    crops_root: Path | None = None
    if dic_rows and seeds:
        base = done
        for field_no, rows_f in sorted(rows_by_field.items()):
            at = base
            seeds_f = (
                marking_seeds(store, session_id, embryos, position=field_positions.get(field_no))
                if multi
                else seeds
            )
            if not seeds_f:
                base = at + len(rows_f)
                continue

            def crops_progress(i: int, _n: int, what: str) -> None:
                nonlocal done
                done = at + i  # noqa: B023
                if progress:
                    progress(done, total, what)

            try:
                seeds_f = orient_seeds(dic_dir_of(field_no), seeds_f)
                boxes = find_embryo_boxes(dic_dir_of(field_no), seeds_f)
                crops_root = dic_crops(dic_dir_of(field_no), boxes, progress=crops_progress)
            except Exception:
                logger.exception("embryo crops failed; the frames are exported without them")
            base = at + len(rows_f)
        done = base

    # --- the README: what this is, and where the originals are --------------
    name = info.get("name") or sd.name
    lines = [
        f"{name}",
        "=" * len(str(name)),
        "",
        f"Gently session {session_id}, created {info.get('created_at', '')}.",
        f"Exported {datetime.now().isoformat(timespec='seconds')}.",
        f"Originals: {sd}",
        "",
        "These are copies, not links: editing or saving anything here cannot touch the session.",
        "",
    ]
    if info.get("description"):
        lines += [str(info["description"]), ""]
    lines += ["Acquisition plan", "----------------", *plan_lines(plan), ""]
    if checkpoint:
        lines += [
            "Run",
            "---",
            f"Status at last checkpoint: {checkpoint.get('status')}",
            f"Started: {checkpoint.get('started_at')}   Last saved: {checkpoint.get('saved_at')}",
            f"Rounds: {checkpoint.get('current_round')}"
            f"   Timepoints: {checkpoint.get('total_timepoints')}",
            "",
        ]
    lines += ["Embryos", "-------"]
    for r in embryo_rows:
        lines.append(
            f"  {r['label']}/   role {r['role']}, {r['timepoints']} timepoints"
            + (f", last stage {r['last_stage']}" if r["last_stage"] else "")
            + (", complete" if r["complete"] else "")
        )
    lines += [
        "",
        "What is where",
        "-------------",
        "  <embryo>/volumes/<embryo>_t0001.tif ...   one 3D TIFF per timepoint,"
        " sorted = time order",
        "  <embryo>/volumes.csv                      when each was taken and with what settings",
        "  <embryo>/projections/                     the per-timepoint JPEG projections",
        "  <embryo>/calibration/                     the calibration runs (frames, plots, fit)",
        "  dic/dic_f0001_<date-time>.tif ...         the DIC overview frames, in order;"
        " dic/dic.csv says when and where",
        "  dic/references/<record>/                  dark and flat-field references;"
        " brightfield.yaml says light, exposure, frames averaged, checks",
        "  embryos.csv, stage_calls.csv, events.csv, temperature.csv",
        "  metadata/                                 the session's own files, as kept"
        " (YAML/JSONL/JSON)",
        "",
        "Brightfield correction",
        "----------------------",
        "  dic.csv names the dark and flat that apply to each frame. Then:",
        "    corrected = (frame - dark) / (flat - dark) * mean(flat - dark)",
        "  In Fiji: Process > Image Calculator (Subtract, then Divide, 32-bit result),"
        " then multiply by the mean.",
        "" if not ref_records else f"  {len(ref_records)} reference record(s) in dic/references/.",
        "",
        "Fiji",
        "----",
        "  A time series: File > Import > Image Sequence..., choose an <embryo>/volumes folder.",
        "  One volume: File > Open on a single .tif (it is a Z stack).",
        *(
            [
                f"  The overview was taken from {n_fields} positions: dic/field_1/ … "
                f"dic/field_{n_fields}/ hold one series each, with the same files inside.",
            ]
            if multi
            else []
        ),
        "  The DIC overview as a movie: open dic/dic.avi (File > Import > AVI...), or"
        " Image Sequence on the dic/ folder for the raw frames.",
        "  dic.avi is Motion JPEG: every frame in time order, one brightness stretch for"
        " the run, frame number and time since the first in the corner. For viewing;"
        " the .tif frames are the data.",
        "  dic_corrected.avi is the same with each frame's dark and flat divided out"
        " (the correction above), where the session had them.",
        *(
            [
                "  dic/embryos/<embryo>/ is each embryo cut out of every DIC frame with one fixed"
                " box: raw/ and corrected/ crops, the dark and flat cropped the same, and a"
                " metadata.csv tying them together. A Hugging Face image folder each; its"
                " README.md says how to load and upload it.",
            ]
            if crops_root is not None
            else []
        ),
        "",
    ]
    (out / "README.txt").write_text("\n".join(lines), encoding="utf-8")
    step("README.txt")
    logger.info("Exported session %s to %s (%d files)", session_id, out, done)
    return out

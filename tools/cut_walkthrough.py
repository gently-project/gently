"""Cut a take recorded by tools/record_walkthrough.js into the guide's video.

The calibration walk and the run's waiting are sped up (and say so on the
picture), the 1920x940 page is padded to 1080p, and it is encoded as H.264.

    python tools/cut_walkthrough.py take.webm docs/guide/Gently-two-view-walkthrough.mp4 \
        '{"walk-start": 56.7, "walk-end": 288.9, "run-start": 365.4, "run-end": 466.5}'

The third argument is the `marks` the recording returns: seconds into the take.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# A full ffmpeg (Playwright's own cannot encode H.264): on PATH, or named in FFMPEG.
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


def duration(src: str) -> float:
    out = subprocess.run([str(FFMPEG), "-i", src], capture_output=True, text=True).stderr
    at = out.index("Duration: ") + 10
    h, m, s = out[at : at + 11].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main(src: str, dst: str, marks: dict[str, float]) -> None:
    end = duration(src)
    # (from, to, speed): what is watched at speed, and what is waited through.
    fast = []
    if "walk-start" in marks and "walk-end" in marks:
        fast.append((marks["walk-start"] + 16, marks["walk-end"] - 2, 10.0))
    if "run-start" in marks and "run-end" in marks:
        fast.append((marks["run-start"] + 12, marks["run-end"] - 1, 5.0))
    if "align-start" in marks and "align-end" in marks:
        fast.append((marks["align-start"] + 5, marks["align-end"] - 1, 4.0))
    fast = [(a, b, k) for a, b, k in fast if b - a > 6]
    cuts, at = [], 0.0
    for a, b, k in sorted(fast):
        cuts += [(at, a, 1.0), (a, b, k)]
        at = b
    cuts.append((at, end, 1.0))
    parts, labels = [], []
    for i, (a, b, k) in enumerate(cuts):
        chain = f"[0:v]trim=start={a:.2f}:end={b:.2f},setpts=(PTS-STARTPTS)/{k}"
        if k > 1:
            # Say so on the picture: nobody should think the rig is this fast.
            chain += (
                f",drawtext=text='{k:.0f}x':fontcolor=white:fontsize=30:box=1:boxcolor=0x1f6feb@0.9:"
                "boxborderw=10:x=w-tw-28:y=h-th-28:fontfile='C\\:/Windows/Fonts/segoeuib.ttf'"
            )
        parts.append(chain + f"[v{i}]")
        labels.append(f"[v{i}]")
    graph = (
        ";".join(parts)
        + ";"
        + "".join(labels)
        + f"concat=n={len(cuts)}:v=1:a=0,fps=25,"
        + "pad=1920:1080:0:(oh-ih)/2:color=0x0d1117,format=yuv420p[out]"
    )
    cmd = [
        str(FFMPEG),
        "-y",
        "-i",
        src,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1500:])
        raise SystemExit(r.returncode)
    kept = sum((b - a) / k for a, b, k in cuts)
    print(f"{dst}: {kept:.0f} s from {end:.0f} s, {Path(dst).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))

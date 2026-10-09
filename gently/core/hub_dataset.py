"""The brightfield exports as one Hugging Face dataset.

"can we add the bright field data in to hugging face repo? structure it
well". An export (``gently.core.export``) already lays each embryo out as
an image folder the Hub reads. This is the layer above: several sessions
in one repository, each field's full frames loadable the same way, a
table of what is there, and a card at the top.

    README.md                   the dataset card
    sessions.csv                one row per session: when, fields, frames, embryos
    sessions/<session>/
        README.txt  embryos.csv  stage_calls.csv  events.csv  temperature.csv
        metadata/               the session's own files, as kept
        dic/                    the export's dic/ folder, as it is:
            [field_1/ field_2/ …]   one series per field when there are several
                dic_f0001_….tif …   the full frames, 16-bit
                dic.csv  metadata.csv   the table; metadata.csv is the Hub's name
                                        for it (file_name = the frame)
                dic.avi  dic_corrected.avi
                embryos/<embryo>/raw/ corrected/ metadata.csv …
            references/<record>/dark.tif flat.tif

Nothing is copied to make this: an upload goes straight from the export
folders, each to its place in the repo. The SPIM volumes are not part of
it; this is the brightfield data.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SESSION_FILES = (
    "README.txt",
    "embryos.csv",
    "stage_calls.csv",
    "events.csv",
    "temperature.csv",
)


@dataclass
class FieldExport:
    """One series of full frames: an export's ``dic/`` or ``dic/field_n/``."""

    folder: Path
    number: int
    frames: int
    embryos: list[str] = field(default_factory=list)

    @property
    def rel(self) -> str:
        """Where it sits under the session's ``dic/`` in the repo."""
        return f"field_{self.number}" if self.folder.name.startswith("field_") else ""


@dataclass
class SessionExport:
    """An export folder, as the dataset sees it."""

    root: Path
    fields: list[FieldExport]
    name: str
    created: str
    session_id: str
    description: str

    @property
    def folder(self) -> str:
        return self.root.name

    @property
    def frames(self) -> int:
        return sum(f.frames for f in self.fields)

    @property
    def embryos(self) -> list[str]:
        out: list[str] = []
        for f in self.fields:
            out += [e for e in f.embryos if e not in out]
        return out


def discover(export_root: Path) -> SessionExport:
    """What an export folder holds, read from its files. Raises when it is
    not an export with DIC frames."""
    root = Path(export_root)
    dic = root / "dic"
    if not dic.is_dir():
        raise FileNotFoundError(f"{root} has no dic/ folder: not a brightfield export")
    field_dirs = sorted(dic.glob("field_*"), key=lambda p: int(p.name.split("_")[-1])) or [dic]
    fields = []
    for fd in field_dirs:
        n = int(fd.name.split("_")[-1]) if fd.name.startswith("field_") else 1
        frames = len(list(fd.glob("dic_f*.tif")))
        if not frames:
            continue
        embryos = (
            sorted(p.name for p in (fd / "embryos").iterdir() if p.is_dir())
            if (fd / "embryos").is_dir()
            else []
        )
        fields.append(FieldExport(fd, n, frames, embryos))
    if not fields:
        raise FileNotFoundError(f"{root} has no DIC frames")
    info: dict[str, Any] = {}
    try:
        doc = yaml.safe_load((root / "metadata" / "session.yaml").read_text(encoding="utf-8"))
        info = doc if isinstance(doc, dict) else {}
    except (OSError, yaml.YAMLError):
        info = {}
    sid = str(info.get("session_id") or root.name.split("_")[-1])
    return SessionExport(
        root=root,
        fields=fields,
        name=str(info.get("name") or root.name),
        created=str(info.get("created_at") or ""),
        session_id=sid,
        description=str(info.get("description") or ""),
    )


def field_metadata_csv(field_dir: Path) -> Path | None:
    """``metadata.csv`` beside a field's ``dic.csv``: the same rows with the
    frame as ``file_name`` relative to the folder, which is how the Hub's
    image-folder loader reads a folder of images. Returns the path, or None
    when there is no table to make it from."""
    src = Path(field_dir) / "dic.csv"
    if not src.is_file():
        return None
    with open(src, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    out = Path(field_dir) / "metadata.csv"
    columns = ["file_name", *[c for c in rows[0] if c != "file"]]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            row = {k: v for k, v in r.items() if k != "file"}
            row["file_name"] = Path(str(r.get("file") or "")).name
            w.writerow(row)
    return out


def sessions_rows(exports: list[SessionExport]) -> list[dict[str, Any]]:
    """One row per session, for ``sessions.csv`` and the card."""
    return [
        {
            "session": s.folder,
            "session_id": s.session_id,
            "name": s.name,
            "created": s.created,
            "fields": len(s.fields),
            "frames": s.frames,
            "embryos": " ".join(s.embryos),
            "description": s.description,
        }
        for s in exports
    ]


def write_sessions_csv(exports: list[SessionExport], path: Path) -> Path:
    rows = sessions_rows(exports)
    columns = [
        "session",
        "session_id",
        "name",
        "created",
        "fields",
        "frames",
        "embryos",
        "description",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)
    return path


def plan(exports: list[SessionExport]) -> list[tuple[Path, str]]:
    """What goes where: (local folder or file, path in the repo). The dic/
    folder of each session goes whole; of the export root only the record
    files and metadata/, not the volume folders."""
    out: list[tuple[Path, str]] = []
    for s in exports:
        base = f"sessions/{s.folder}"
        for name in SESSION_FILES:
            if (s.root / name).is_file():
                out.append((s.root / name, f"{base}/{name}"))
        if (s.root / "metadata").is_dir():
            out.append((s.root / "metadata", f"{base}/metadata"))
        out.append((s.root / "dic", f"{base}/dic"))
    return out


def dataset_card(exports: list[SessionExport], repo_id: str, license_id: str) -> str:
    """The card: front matter the Hub reads, then what is here and how to
    load it. ``license_id`` is a Hub license identifier (``cc-by-4.0``)."""
    total_frames = sum(s.frames for s in exports)
    total_crops = sum(sum(f.frames * len(f.embryos) for f in s.fields) for s in exports)
    n = total_frames + total_crops
    size = (
        "n<1K"
        if n < 1000
        else "1K<n<10K"
        if n < 10_000
        else "10K<n<100K"
        if n < 100_000
        else "100K<n<1M"
    )
    # The loading examples point at the first session's first field.
    first = exports[0] if exports else None
    fld = first.fields[0] if first else None
    session_dir = f"sessions/{first.folder}" if first else "sessions/<session>"
    frames_dir = f"{session_dir}/dic" + (f"/{fld.rel}" if fld and fld.rel else "")
    embryo = first.embryos[0] if first and first.embryos else "<embryo>"
    crops_dir = f"{frames_dir}/embryos/{embryo}"
    lines = [
        "---",
        f"license: {license_id}",
        "pretty_name: C. elegans embryos under brightfield, from the Gently microscope",
        "tags:",
        "- microscopy",
        "- brightfield",
        "- c-elegans",
        "- embryo",
        "- time-lapse",
        "- biology",
        "task_categories:",
        "- image-classification",
        "- object-detection",
        "size_categories:",
        f"- {size}",
        "---",
        "",
        "# C. elegans embryos under brightfield",
        "",
        "Overnight time-lapses of *C. elegans* embryos on the bottom camera of the",
        "Gently light-sheet microscope: the whole field every half minute, and each",
        "embryo cut out of every frame with a fixed box, raw and shading-corrected,",
        "16-bit TIFF throughout. Made by Gently's export (`gently.core.export`).",
        "",
        "## Sessions",
        "",
        "| session | name | created | fields | frames | embryos |",
        "|---|---|---|---|---|---|",
        *[
            f"| `{s.folder}` | {s.name} | {s.created[:16]} | {len(s.fields)} | {s.frames} | "
            f"{', '.join(s.embryos)} |"
            for s in exports
        ],
        "",
        "`sessions.csv` is the same table. A session's own notes are in its `README.txt`.",
        "",
        "## Layout",
        "",
        "```",
        "sessions/<session>/",
        "  README.txt  embryos.csv  stage_calls.csv  events.csv  temperature.csv",
        "  metadata/                  the session's own files, as kept (YAML, JSONL)",
        "  dic/[field_n/]             one series per field the overview was taken from",
        "    dic_f0001_<stamp>.tif …  the full frames, 16-bit, named so a sort is time order",
        "    metadata.csv             one row per frame: file_name, frame, captured_at,",
        "                             stage position, light, exposure, the dark and flat",
        "    dic.avi  dic_corrected.avi   the series as a movie, as taken and corrected",
        "    embryos/<embryo>/        the embryo cut out of every frame:",
        "      raw/  corrected/       the crops, 16-bit",
        "      dark.tif  flat.tif     the references, cropped the same",
        "      metadata.csv           file_name (raw), corrected_file, frame, time, box …",
        "      README.md              that folder's own card",
        "  dic/references/<record>/   the dark and flat frames the correction uses",
        "```",
        "",
        "## Shading correction",
        "",
        "    corrected = (raw - dark) / (flat - dark) * mean(flat - dark)",
        "",
        "`dark` is a frame with the light off, `flat` the empty field under the same",
        "light. Each frame's `metadata.csv` row names the pair used.",
        "",
        "## Loading",
        "",
        "Every folder with a `metadata.csv` is a Hugging Face image folder:",
        "",
        "```python",
        "from datasets import load_dataset",
        "",
        "# one embryo's crops (raw; the corrected twin's path is a column)",
        f'crops = load_dataset("imagefolder", data_dir="{crops_dir}")',
        "",
        "# a field's full frames",
        f'frames = load_dataset("imagefolder", data_dir="{frames_dir}")',
        "```",
        "",
        "Or read any `metadata.csv` with pandas and open the TIFFs it names with",
        "`tifffile`: the images are 16-bit, which some viewers show dark.",
        "",
        "## Provenance",
        "",
        f"Repository `{repo_id}`. Uploaded from the exports with",
        "`tools/hf_brightfield_dataset.py` in the Gently repository, which also",
        "says how the frames and crops were made.",
        "",
    ]
    return "\n".join(lines)

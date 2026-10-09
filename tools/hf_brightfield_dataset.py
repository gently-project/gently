"""Put brightfield exports on the Hugging Face Hub as one dataset.

    uv run --with huggingface_hub python tools/hf_brightfield_dataset.py \
        plan   <export> [<export> …] --repo org/name
    uv run --with huggingface_hub python tools/hf_brightfield_dataset.py \
        upload <export> [<export> …] --repo org/name [--private] [--license cc-by-4.0]

``plan`` says what would go where and writes nothing to the Hub. ``upload``
creates the repository if it is not there, writes ``metadata.csv`` beside
each field's ``dic.csv`` (so the full frames load as an image folder), the
``sessions.csv`` and the card, and uploads straight from the export folders.
A second ``upload`` of the same exports adds and replaces, never removes.

Layout and card: ``gently.core.hub_dataset``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gently.core.hub_dataset import (  # noqa: E402
    dataset_card,
    discover,
    field_metadata_csv,
    plan,
    write_sessions_csv,
)


def _exports(paths: list[str]):
    out = []
    for p in paths:
        s = discover(Path(p))
        out.append(s)
        who = ", ".join(s.embryos) or "-"
        print(f"{s.folder}: {len(s.fields)} field(s), {s.frames} frames, embryos {who}")
    return out


def cmd_plan(args) -> int:
    exports = _exports(args.exports)
    print(f"\nrepo {args.repo}:")
    for local, in_repo in plan(exports):
        print(f"  {in_repo:60s} <- {local}")
    print("  sessions.csv, README.md             <- written at upload")
    for s in exports:
        for f in s.fields:
            print(f"  {f.folder / 'metadata.csv'}  <- written beside dic.csv at upload")
    return 0


def cmd_upload(args) -> int:
    from huggingface_hub import HfApi

    api = HfApi()
    me = api.whoami()
    print(f"as {me.get('name')}")
    exports = _exports(args.exports)
    api.create_repo(args.repo, repo_type="dataset", private=bool(args.private), exist_ok=True)
    for s in exports:
        for f in s.fields:
            made = field_metadata_csv(f.folder)
            if made:
                print(f"wrote {made}")
    with tempfile.TemporaryDirectory() as tmp:
        top = Path(tmp)
        write_sessions_csv(exports, top / "sessions.csv")
        (top / "README.md").write_text(
            dataset_card(exports, args.repo, args.license), encoding="utf-8"
        )
        api.upload_folder(
            repo_id=args.repo,
            repo_type="dataset",
            folder_path=str(top),
            path_in_repo=".",
            commit_message="The card and the table of sessions",
        )
    # Folder by folder, each its own commit, so a dropped connection costs
    # one field, not the night: a second run adds what is missing.
    for local, in_repo in plan(exports):
        print(f"uploading {in_repo} …", flush=True)
        if local.is_dir():
            api.upload_folder(
                repo_id=args.repo,
                repo_type="dataset",
                folder_path=str(local),
                path_in_repo=in_repo,
                ignore_patterns=["*/volumes/*", "*.lock"],
                commit_message=in_repo,
            )
        else:
            api.upload_file(
                repo_id=args.repo,
                repo_type="dataset",
                path_or_fileobj=str(local),
                path_in_repo=in_repo,
                commit_message=in_repo,
            )
    print(f"done: https://huggingface.co/datasets/{args.repo}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("upload", cmd_upload)):
        p = sub.add_parser(name)
        p.add_argument("exports", nargs="+", help="export folders (each holds dic/)")
        p.add_argument("--repo", required=True, help="org/name of the dataset repository")
        p.add_argument("--private", action="store_true", help="create the repository private")
        p.add_argument("--license", default="cc-by-4.0", help="Hub license identifier for the card")
        p.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())

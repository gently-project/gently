"""Claude reviews each candidate CROP and removes the ones that aren't embryos.

The blob detector finds bright compact things; it cannot tell an embryo from
the out-of-focus edge of a bubble, which is also bright and compact. On real
2048px frames that edge was the entire remaining false-positive source.

So the detector proposes permissively and a vision call classifies each
candidate. Two properties matter and are pinned here:

* it only ever REMOVES candidates - recall stays the detector's job;
* detection never depends on the network. No key, an API error or an
  unparseable reply must fall back to the conservative cut the detector would
  have made alone, not crash and not return the permissive pile.

No network: the Claude client is faked.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from gently.hardware.dispim.sam_detection import SAMEmbryoDetector


def _detector() -> SAMEmbryoDetector:
    return SAMEmbryoDetector(anthropic_api_key=None)


def _fake_client(verdicts: Any, raises: BaseException | None = None) -> MagicMock:
    """A stand-in for anthropic.Anthropic with a canned vision reply."""
    client = MagicMock()
    if raises is not None:
        client.messages.create.side_effect = raises
        return client
    block = MagicMock()
    block.type = "text"
    block.text = verdicts if isinstance(verdicts, str) else json.dumps({"verdicts": verdicts})
    client.messages.create.return_value = MagicMock(content=[block])
    return client


def _candidates(n: int) -> list[dict]:
    """n candidates spread out, with descending relative_strength."""
    return [
        {
            "bbox": (10 + 50 * i, 10, 20, 20),
            "centroid": (20.0 + 50 * i, 20.0),
            "area": 300.0,
            "relative_strength": 1.0 - 0.1 * i,
        }
        for i in range(n)
    ]


IMG = np.full((410, 410), 40, np.uint8)


async def test_keeps_only_what_claude_calls_an_embryo() -> None:
    det = _detector()
    det.claude_client = _fake_client(
        [
            {"i": 0, "embryo": True, "confidence": 0.95},
            {"i": 1, "embryo": False, "confidence": 0.9},
            {"i": 2, "embryo": True, "confidence": 0.8},
        ]
    )
    cands = _candidates(3)
    kept, review = await det._classify_candidates_with_claude(IMG, cands, half=32)

    assert [c["centroid"] for c in kept] == [cands[0]["centroid"], cands[2]["centroid"]]
    assert review["reviewed"] is True
    assert (review["proposed"], review["kept"], review["removed"]) == (3, 2, 1)


async def test_it_can_only_remove_never_add() -> None:
    """A reply naming tiles that don't exist must not invent candidates."""
    det = _detector()
    det.claude_client = _fake_client(
        [
            {"i": 0, "embryo": True, "confidence": 0.9},
            {"i": 99, "embryo": True, "confidence": 0.9},
            {"i": -1, "embryo": True, "confidence": 0.9},
        ]
    )
    cands = _candidates(2)
    kept, _ = await det._classify_candidates_with_claude(IMG, cands, half=32)

    assert len(kept) == 1
    assert all(k in cands for k in kept)


@pytest.mark.parametrize(
    "client",
    [
        None,
        _fake_client(None, raises=RuntimeError("API is down")),
        _fake_client("not json at all"),
    ],
    ids=["no-client", "api-error", "unparseable"],
)
async def test_failure_falls_back_to_the_conservative_cut(client: Any) -> None:
    """Never crash, and never ship the permissive pile when review is absent."""
    det = _detector()
    det.claude_client = client
    # strengths 1.0, 0.9, 0.8, 0.7, 0.6, 0.5 — the last two are below the
    # conservative threshold the detector would have applied on its own.
    cands = _candidates(6)
    kept, review = await det._classify_candidates_with_claude(IMG, cands, half=32)

    assert review["reviewed"] is False
    cut = SAMEmbryoDetector._NO_REVIEW_RELATIVE_PEAK
    assert kept == [c for c in cands if c["relative_strength"] >= cut]
    assert len(kept) < len(cands), "fallback must actually drop the weak candidates"


async def test_no_candidates_makes_no_api_call() -> None:
    det = _detector()
    det.claude_client = _fake_client([])
    kept, review = await det._classify_candidates_with_claude(IMG, [], half=32)

    assert kept == []
    assert det.claude_client.messages.create.call_count == 0


def test_contact_sheet_tiles_every_candidate() -> None:
    det = _detector()
    cands = _candidates(7)
    sheet = det._candidate_contact_sheet(IMG, cands, half=32)

    cols, tile = det._TILE_COLS, det._TILE_PX
    assert sheet.shape == (((len(cands) + cols - 1) // cols) * tile, cols * tile, 3)
    assert sheet.dtype == np.uint8


def test_candidates_carry_relative_strength() -> None:
    """The fallback above depends on this key existing on real candidates."""
    rng = np.random.default_rng(0)
    img = rng.normal(40, 8, (410, 410))
    ys, xs = np.mgrid[0:410, 0:410]
    for cx, cy, amp in ((150, 150, 150.0), (260, 150, 90.0), (150, 260, 70.0)):
        img += amp * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * 5.0**2)))
    img = np.clip(img, 0, 255).astype(np.uint8)

    cands, _ = _detector().find_embryo_candidates(img, min_relative_peak=0.1)

    assert cands, "expected candidates"
    strengths = [c["relative_strength"] for c in cands]
    assert all(0.0 <= s <= 1.0 for s in strengths)
    assert max(strengths) == pytest.approx(1.0), "strongest peak is the reference"

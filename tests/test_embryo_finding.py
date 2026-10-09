"""Finding embryos in a frame: the dark-blob finder and the Claude finder.

"we need a better way to get embryo FOV out - perhaps using claude VLM" …
"replace the box finder with claude based setup" … "and also include box
finder in the bottom cam detector methods". Both finders answer in the
same shape, boxes in frame pixels, and neither can take a caller down.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("cv2")

from gently.core.embryo_finding import claude_boxes, dark_blobs, flatten  # noqa: E402


def _field(h=240, w=320, embryos=((40, 90, 50, 80), (150, 210, 200, 240)), vignette=True):
    """A bright field with dark ovals (rows y0:y1, cols x0:x1), dimmer at
    the edges the way a real one is, as 16-bit. With the dark and flat that
    explain it."""
    yy, xx = np.mgrid[0:h, 0:w]
    gain = np.full((h, w), 600.0)
    if vignette:
        r = np.hypot((yy - h / 2) / h, (xx - w / 2) / w)
        gain = gain * (1.0 - 0.6 * r)
    t = np.full((h, w), 0.6)
    for y0, y1, x0, x1 in embryos:
        t[y0:y1, x0:x1] = 0.15
    dark = np.full((h, w), 100, dtype=np.uint16)
    flat = (dark + gain).astype(np.uint16)
    frame = (dark + t * gain).astype(np.uint16)
    return frame, dark, flat


def _centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


class TestDarkBlobs:
    def test_finds_the_dark_ovals_with_the_references(self):
        frame, dark, flat = _field()
        blobs = dark_blobs(frame, dark, flat)
        centres = sorted(_centre(b) for b in blobs)
        assert len(blobs) == 2
        assert abs(centres[0][0] - 65) < 4 and abs(centres[0][1] - 65) < 4
        assert abs(centres[1][0] - 220) < 4 and abs(centres[1][1] - 180) < 4
        # Each is (x0, y0, x1, y1, cx, cy, area), the box holding the oval.
        x0, y0, x1, y1, _cx, _cy, area = next(b for b in blobs if b[0] < 100)
        assert x0 <= 50 and y0 <= 40 and x1 >= 80 and y1 >= 90 and area >= 30 * 50 * 0.9

    def test_finds_them_without_references_too(self):
        # No dark and flat: the field is flattened by its own blur, so the
        # vignetting does not read as one big dark blob.
        frame, _, _ = _field()
        blobs = dark_blobs(frame)
        assert len(blobs) == 2, [b[:4] for b in blobs]

    def test_an_empty_field_has_none(self):
        frame, dark, flat = _field(embryos=())
        assert dark_blobs(frame, dark, flat) == []
        assert dark_blobs(frame) == []

    def test_flatten_is_a_ratio_to_the_background(self):
        frame, dark, flat = _field()
        ratio = flatten(frame, dark, flat)
        assert abs(float(np.median(ratio)) - 1.0) < 0.05
        assert float(ratio[65, 65]) < 0.4, "the embryo is dark against 1.0"


class _FakeClaude:
    """What the finder needs of an Anthropic client: messages.create."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                if isinstance(outer.reply, Exception):
                    raise outer.reply
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=outer.reply)])

        self.messages = _Messages()


class TestClaudeBoxes:
    def test_the_boxes_come_back_in_frame_pixels(self):
        frame, dark, flat = _field(h=240, w=320)
        # Thousandths of the frame: (150..250, 160..380) of 320 x 240.
        reply = "Here you go:\n" + json.dumps(
            {"embryos": [{"x0": 150, "y0": 160, "x1": 250, "y1": 380, "confidence": 0.9}]}
        )
        fake = _FakeClaude(reply)
        boxes = claude_boxes(frame, dark, flat, client=fake, model="m")
        assert boxes == [(48, 38, 80, 91)]
        kw = fake.calls[0]
        assert kw["model"] == "m"
        content = kw["messages"][0]["content"]
        assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
        assert "embryo" in content[1]["text"].lower() and "0 to 1000" in content[1]["text"]

    def test_a_frame_bigger_than_max_side_is_shown_smaller_but_answered_full_size(self):
        frame, dark, flat = _field(h=2000, w=2000, embryos=((100, 400, 200, 400),))
        fake = _FakeClaude(json.dumps({"embryos": [{"x0": 100, "y0": 50, "x1": 200, "y1": 200}]}))
        boxes = claude_boxes(frame, dark, flat, client=fake, model="m", max_side=512)
        assert boxes == [(200, 100, 400, 400)]

    @pytest.mark.parametrize(
        "reply",
        [
            "not json at all",
            json.dumps({"embryos": [{"x0": 1}]}),
            json.dumps({"embryos": []}),
            RuntimeError("network down"),
        ],
    )
    def test_nothing_usable_is_no_boxes_not_an_error(self, reply):
        frame, dark, flat = _field()
        assert claude_boxes(frame, dark, flat, client=_FakeClaude(reply), model="m") == []

    def test_without_a_key_nothing_is_asked(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        frame, dark, flat = _field()
        assert claude_boxes(frame, dark, flat) == []

    def test_boxes_are_clipped_and_tidy(self):
        frame, dark, flat = _field(h=100, w=100)
        reply = json.dumps(
            {
                "embryos": [
                    {"x0": 900, "y0": 1200, "x1": 300, "y1": -50},
                    {"x0": 10, "y0": 10, "x1": 12, "y1": 12},
                ]
            }
        )
        # Reversed corners are sorted, the box is clipped to the frame, and
        # a box too small to be anything is dropped.
        assert claude_boxes(frame, dark, flat, client=_FakeClaude(reply), model="m") == [
            (30, 0, 90, 100)
        ]

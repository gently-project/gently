"""Finding embryos in a bottom-camera frame: where the boxes come from.

Two finders, one shape of answer. ``dark_blobs`` is classical: embryos
under transmitted light are compact dark ovals on a bright field, so the
field is flattened and thresholded. ``claude_boxes`` asks a vision model
for the boxes outright. The export's crops and the Operate tab's detector
both use these; neither needs to know how a box was found.

Nothing here touches hardware or a session. A frame comes in as an array,
boxes go out in that frame's pixels.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in frame pixels
Blob = tuple[int, int, int, int, float, float, float]  # x0, y0, x1, y1, cx, cy, area


def flatten(image: np.ndarray, dark: np.ndarray | None = None, flat: np.ndarray | None = None):
    """The frame as a fraction of its background, so a dark embryo reads the
    same in a dim corner as in the bright middle. With a dark and flat it
    is the proper correction; without them the field is divided by its own
    heavy blur, which takes the vignetting out well enough to find things."""
    import cv2

    img = np.squeeze(np.asarray(image))
    if img.ndim == 3:
        img = img.max(axis=0) if img.shape[0] <= 4 else img.mean(axis=2)
    f = img.astype(np.float32)
    if dark is not None and flat is not None and dark.shape == f.shape and flat.shape == f.shape:
        from gently.app.brightfield import correct

        f = correct(img, dark, flat).astype(np.float32)
        bg = float(np.median(f)) or 1.0
        return f / bg
    sigma = max(8.0, 0.08 * max(f.shape))
    blur = cv2.GaussianBlur(f, (0, 0), sigma)
    blur[blur <= 1e-6] = 1e-6
    return f / blur


def dark_blobs(
    image: np.ndarray,
    dark: np.ndarray | None = None,
    flat: np.ndarray | None = None,
    floor: float = 0.75,
    min_area_frac: float = 0.0005,
) -> list[Blob]:
    """Compact dark things on a bright field: what an embryo looks like
    under the transmitted-light LED. Pixels darker than ``floor`` of the
    local background, closed up, as connected blobs at least
    ``min_area_frac`` of the frame in area. In frame pixels."""
    import cv2

    ratio = flatten(image, dark, flat)
    mask: Any = (cv2.GaussianBlur(ratio, (0, 0), 3) < floor).astype(np.uint8)
    k = max(3, int(round(0.007 * max(ratio.shape))) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _labels, stats, cent = cv2.connectedComponentsWithStats(mask)
    least = min_area_frac * ratio.shape[0] * ratio.shape[1]
    out: list[Blob] = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= least:
            out.append((x, y, x + w, y + h, float(cent[i][0]), float(cent[i][1]), float(area)))
    return out


_PROMPT = """This is one frame from a brightfield (transmitted light) microscope \
looking down at C. elegans embryos lying on a glass surface. An embryo is an oval, \
roughly 2 to 3 times longer than it is wide, with a dark, textured inside and a \
thin bright shell; several may be in the frame, some near the edges. Ignore \
dust, bubbles, scratches, shadows, out-of-focus smudges and the dark corners of \
the field.

Give a tight bounding box around every embryo you can see, in coordinates \
from 0 to 1000 where (0, 0) is the top-left corner and (1000, 1000) the \
bottom-right. Answer with JSON only, nothing else:
{"embryos": [{"x0": 0, "y0": 0, "x1": 0, "y1": 0, "confidence": 0.0}]}
Use an empty list if there is none."""


def claude_boxes(
    image: np.ndarray,
    dark: np.ndarray | None = None,
    flat: np.ndarray | None = None,
    model: str | None = None,
    api_key: str | None = None,
    max_side: int = 1024,
    client: Any = None,
) -> list[Box]:
    """Every embryo Claude sees in the frame, as boxes in frame pixels.
    The frame is flattened, stretched to 8 bits and shown no larger than
    ``max_side``; the boxes come back in thousandths and are scaled to the
    frame. ``[]`` when there is no key, or the call or its answer fails:
    a finder must never take an export down."""
    import cv2

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if client is None:
        if not key:
            logger.info("claude_boxes: no API key, nothing asked")
            return []
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=key)
        except Exception as exc:
            logger.warning("claude_boxes: no client: %s", exc)
            return []
    if model is None:
        try:
            from gently.settings import settings

            model = settings.models.perception
        except Exception:
            model = "claude-opus-4-8"

    ratio = flatten(image, dark, flat)
    h, w = ratio.shape[:2]
    lo, hi = np.percentile(ratio, (0.5, 99.5))
    g = np.clip((ratio - lo) / ((hi - lo) or 1.0) * 255.0, 0, 255).astype(np.uint8)
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        g = cv2.resize(
            g, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA
        )
    ok, jpg = cv2.imencode(".jpg", g, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        return []
    import base64

    b64 = base64.b64encode(jpg.tobytes()).decode("ascii")
    try:
        message = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                        },
                        {"type": "text", "text": _PROMPT},
                    ],
                }
            ],
        )
        text = "".join(getattr(b, "text", "") for b in message.content)
        payload = json.loads(text[text.index("{") : text.rindex("}") + 1])
        found = payload.get("embryos") or []
    except Exception as exc:
        logger.warning("claude_boxes: no boxes: %s", exc)
        return []
    boxes: list[Box] = []
    for b in found:
        try:
            x0, y0, x1, y1 = (float(b[k]) for k in ("x0", "y0", "x1", "y1"))
        except (KeyError, TypeError, ValueError):
            continue
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        box = (
            max(0, int(round(x0 / 1000.0 * w))),
            max(0, int(round(y0 / 1000.0 * h))),
            min(w, int(round(x1 / 1000.0 * w))),
            min(h, int(round(y1 / 1000.0 * h))),
        )
        if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:
            boxes.append(box)
    logger.info("claude_boxes: %d embryo(s) in a %dx%d frame", len(boxes), w, h)
    return boxes

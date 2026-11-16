"""A slice with no embryo in it is not cropped to a strip of sensor noise."""

import numpy as np

from gently.app.tools.hardware_common import crop_to_embryo_roi, embryo_roi


def test_a_hot_column_is_not_taken_for_the_embryo() -> None:
    rng = np.random.default_rng(0)
    empty = rng.normal(100, 0.5, size=(200, 200)).astype(np.float32)
    empty[:, 150:153] += 30  # the sensor's own pattern: the largest bright thing
    assert embryo_roi(empty) is None
    assert crop_to_embryo_roi(empty).shape == empty.shape


def test_an_embryo_is_still_cropped_to() -> None:
    rng = np.random.default_rng(0)
    img = rng.normal(100, 2, size=(200, 200)).astype(np.float32)
    yy, xx = np.mgrid[:200, :200]
    img += 400 * (((yy - 100) / 30.0) ** 2 + ((xx - 110) / 45.0) ** 2 < 1)
    out = crop_to_embryo_roi(img)
    assert out.shape != img.shape
    assert 60 <= out.shape[0] <= 120 and 90 <= out.shape[1] <= 160

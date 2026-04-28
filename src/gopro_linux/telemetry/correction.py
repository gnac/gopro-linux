"""
Accelerometer axis correction for non-standard GoPro mounting orientations.

Modern GoPro cameras (Hero 5+) output ACCL and GYRO in ZXY order:
    sample[0] = camera Z  (perpendicular to mounting face / "up" when right-side up)
    sample[1] = camera X  (horizontal, "right" when right-side up)
    sample[2] = camera Y  (towards the lens / depth axis)

For a car-mounted, forward-facing camera the mapping is:
    camera Z → car longitudinal (forward/back accel)  → accl_z in our model
    camera X → car lateral      (left/right)           → accl_x in our model
    camera Y → car vertical     (up/down)              → accl_y in our model

Wait — we expose ax/ay/az to mean lateral/longitudinal/vertical from the
*driver's* point of view, so the caller chooses what "flip" means for them.

Upside-down mounting (camera rotated 180° around the lens/Z axis):
    - Camera Z unchanged  → longitudinal unchanged
    - Camera X negated    → lateral inverted   → use flip_x=True
    - Camera Y negated    → vertical inverted  → use flip_y=True

The ``--flip`` CLI shorthand applies flip_x=True, flip_z=True which corrects
the most common upside-down roof/windshield mount where the X (lateral) and
Z (stored-vertical, which we expose as accl_z) are negated.
"""

from __future__ import annotations
import numpy as np


def apply_mounting_correction(
    ax: np.ndarray,
    ay: np.ndarray,
    az: np.ndarray,
    *,
    flip_x: bool = False,
    flip_y: bool = False,
    flip_z: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Negate the specified accelerometer axes to correct for mounting orientation.

    Parameters
    ----------
    ax, ay, az : arrays
        Lateral, longitudinal and vertical acceleration in m/s².
    flip_x / flip_y / flip_z : bool
        Negate the corresponding axis.

    Returns
    -------
    Corrected (ax, ay, az) arrays.
    """
    return (
        (-ax if flip_x else ax.copy()),
        (-ay if flip_y else ay.copy()),
        (-az if flip_z else az.copy()),
    )


def smooth(values: np.ndarray, window: int = 5) -> np.ndarray:
    """Uniform moving-average smoothing (edge-preserved via 'same' convolution)."""
    if window <= 1 or len(values) < window:
        return values.copy()
    kernel = np.ones(window) / window
    return np.convolve(values, kernel, mode="same")

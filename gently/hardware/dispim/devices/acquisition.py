"""
DiSPIM compound acquisition devices (volume scanner and light sheet snap).
"""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

import numpy as np
import pymmcore
from ophyd.status import Status

from gently.settings import settings

from ._common import _safe_obtain
from .camera import DiSPIMCamera
from .optical import DiSPIMLaserControl
from .piezo import DiSPIMPiezo
from .scanner import DiSPIMScanner

logger = logging.getLogger(__name__)


def _lasers_out_after(core, group_name: str, seconds: float) -> threading.Timer:
    """A clock that puts the lasers out, started when they are put on.

    A stack turns them on, waits on the camera, and turns them off. If a call
    to the camera never returns, nothing after it runs: the stack is reported
    failed and the lasers stay on the sample until the process is killed.
    This runs on its own thread, so it does not wait on that call. Whoever
    starts it cancels it when the lasers have been put out the ordinary way.
    """

    def out() -> None:
        logger.error("A stack held the lasers on for %.0f s; putting them out", seconds)
        try:
            core.setConfig(group_name, "ALL OFF")
        except Exception:
            logger.exception("The lasers could not be put out")

    timer = threading.Timer(seconds, out)
    timer.daemon = True
    timer.start()
    return timer


# Far longer than any stack takes, and short for a sample under four lasers.
LASERS_ON_AT_MOST_S = 30.0


class DiSPIMVolumeScanner:
    """
    Compound device for hardware-triggered SPIM volume acquisition.

    Orchestrates camera, scanner, piezo, and lasers for synchronized 3D volume capture.
    Handles all the complexity of circular buffer management, state machine
    coordination, and automatic laser enable/disable.

    Laser Management:
    - Automatically enables configured lasers before acquisition
    - Automatically disables lasers after acquisition (prevents photobleaching!)
    - Always disables lasers on error (critical for sample health)
    - Laser timing during scan controlled by scanner's LaserOutputMode property

    This device encapsulates the entire hardware-triggered acquisition workflow,
    allowing plans to simply call trigger_and_read([volume_scanner]).

    Parameters
    ----------
    scanner : DiSPIMScanner
        Scanner device for galvo control
    camera : DiSPIMCamera
        Camera device for image acquisition
    piezo : DiSPIMPiezo
        Piezo device for Z-axis scanning
    laser_control : DiSPIMLaserControl
        Laser control device for managing laser configs.
        Required to ensure explicit laser management (no accidental photobleaching!)
    core : pymmcore.CMMCore
        Micro-Manager core instance
    name : str
        Device name (default: "volume_scanner")
    """

    def __init__(
        self,
        scanner: DiSPIMScanner,
        camera: DiSPIMCamera,
        piezo: DiSPIMPiezo,
        laser_control: "DiSPIMLaserControl",
        core: pymmcore.CMMCore,
        name: str = "volume_scanner",
        side: str = "A",
    ):
        """
        Initialize volume scanner with all required devices.

        ``side`` names the imaging path this trio belongs to, 'A' or 'B'; it
        is written to the card as SPIMFirstSide when the scan is configured.

        Note: laser_control is required because proper SPIM operation always
        requires explicit laser management to avoid photobleaching and ensure
        reproducible illumination.
        """
        self.name = name
        self.side = side
        self.parent = None  # Required for Bluesky
        self.scanner = scanner
        self.camera = camera
        self.piezo = piezo
        self.laser_control = laser_control
        self.core = core

        self._last_volume = None
        self._last_volume_time = None
        # When the stack began: the moment the scan was set running. This is
        # the volume's time. The time it was finished, read out and its lasers
        # put out is _last_volume_time, over a second later.
        self._scan_started: float | None = None
        self._configured = False

        # Configuration cache
        self._num_slices: int | None = None
        self._exposure_ms: float | None = None
        self._laser_config: str | None = None

    def configure(
        self,
        num_slices: int,
        exposure_ms: float,
        galvo_amplitude: float,
        galvo_center: float,
        piezo_amplitude: float,
        piezo_center: float,
        laser_config: str = "488 and 561",
        laser_power_488_pct: float | None = None,
        laser_power_561_pct: float | None = None,
        laser_power_405_pct: float | None = None,
        laser_power_637_pct: float | None = None,
        timing_params: dict | None = None,
    ):
        """
        Configure all devices for hardware-triggered volume acquisition.

        Parameters
        ----------
        num_slices : int
            Number of Z slices in the volume
        exposure_ms : float
            Camera exposure time in milliseconds
        galvo_amplitude : float
            Galvo Y-axis amplitude in degrees (synchronized with piezo)
        galvo_center : float
            Galvo Y-axis center offset in degrees
        piezo_amplitude : float
            Piezo scanning amplitude in micrometers
        piezo_center : float
            Piezo center offset in micrometers
        laser_config : str
            Laser channel selection preset (default: "488 and 561").
            Common options: "488 and 561", "488 only", "561 only"
        laser_power_488_pct, laser_power_561_pct, laser_power_405_pct,
        laser_power_637_pct : float, optional
            Per-line laser power %. ``None`` leaves the current setpoint
            unchanged. Out-of-range values are rejected at the device-layer
            setter (see DiSPIMLightSource.POWER_LIMITS_PCT).
        timing_params : Dict, optional
            Custom SPIM timing parameters (uses defaults if None)
        """
        # Configure camera for hardware triggering
        t0 = time.perf_counter()
        self.camera.configure_for_volume_acquisition(exposure_ms)
        t_camera = time.perf_counter()

        # Configure scanner for volume acquisition
        self.scanner.configure_for_volume_acquisition(
            galvo_amplitude=galvo_amplitude,
            galvo_center=galvo_center,
            num_slices=num_slices,
            timing_params=timing_params,
            first_side=self.side,
        )

        t_scanner = time.perf_counter()

        # Configure piezo for volume acquisition
        self.piezo.configure_for_volume_acquisition(
            amplitude_um=piezo_amplitude, offset_um=piezo_center, num_slices=num_slices
        )
        t_piezo = time.perf_counter()

        # Apply per-line laser power if specified. Each setter raises if the
        # value violates the hard safety bound — fail loudly, don't acquire
        # at a wrong power.
        power_settings = {
            488: laser_power_488_pct,
            561: laser_power_561_pct,
            405: laser_power_405_pct,
            637: laser_power_637_pct,
        }
        applied_powers = {}
        for wavelength, pct in power_settings.items():
            if pct is not None:
                self.laser_control.set_power_pct(wavelength, pct)
                applied_powers[wavelength] = pct

        self._num_slices = num_slices
        self._exposure_ms = exposure_ms
        self._laser_config = laser_config
        self._laser_powers_pct = applied_powers  # for metadata downstream
        self._configured = True
        # Where a volume's setup goes: it is the wait between the two views.
        logger.info(
            "Side %s configured in %.0f ms (camera %.0f, scanner %.0f, piezo %.0f, lasers %.0f)",
            self.side,
            (time.perf_counter() - t0) * 1000,
            (t_camera - t0) * 1000,
            (t_scanner - t_camera) * 1000,
            (t_piezo - t_scanner) * 1000,
            (time.perf_counter() - t_piezo) * 1000,
        )

    def trigger(self):
        """
        Start hardware-triggered volume acquisition.

        Returns
        -------
        Status
            Ophyd status object that finishes when volume is acquired
        """
        if not self._configured:
            raise RuntimeError("Device not configured. Call configure() first.")

        status = Status(obj=self, timeout=120)

        def wait():
            watch = _lasers_out_after(self.core, self.laser_control.group_name, LASERS_ON_AT_MOST_S)
            try:
                t0 = time.perf_counter()
                # Enable lasers
                self.core.setConfig(self.laser_control.group_name, self._laser_config)
                self.core.waitForConfig(self.laser_control.group_name, self._laser_config)
                t_lasers = time.perf_counter()

                # Defensive stop: the lightsheet live streamer may have left the
                # camera in continuous acquisition.  Starting a new sequence on
                # an already-running camera triggers an MMCore error (and is
                # thread-unsafe).  Stop cleanly before reconfiguring.
                if self.core.isSequenceRunning():
                    self.core.stopSequenceAcquisition()
                    self.core.waitForDevice(self.camera.name)

                # Prepare circular buffer
                self.core.clearCircularBuffer()
                buffer_capacity = self.core.getBufferTotalCapacity()
                if buffer_capacity < self._num_slices:
                    self.core.setCircularBufferMemoryFootprint(512)
                    self.core.waitForDevice(self.camera.name)

                # Start sequence acquisition
                self.core.prepareSequenceAcquisition(self.camera.name)
                self.core.waitForDevice(self.camera.name)
                self.core.startSequenceAcquisition(self.camera.name, self._num_slices, 0, True)
                self.core.waitForDevice(self.camera.name)

                # Trigger SPIM state machine
                t_ready = time.perf_counter()
                self._scan_started = time.time()
                self.scanner.set_spim_state("Running")

                # Collect images
                images = []
                timeout_s = settings.timeouts.volume_acquisition
                start_time = time.time()

                while self.core.getRemainingImageCount() > 0 or self.core.isSequenceRunning():
                    if self.core.getRemainingImageCount() > 0:
                        img = self.core.popNextImage()

                        # Handle rpyc transfer
                        try:
                            img = _safe_obtain(img)
                        except (ImportError, AttributeError):
                            pass

                        images.append(img)

                    if time.time() - start_time > timeout_s:
                        raise TimeoutError(f"Volume acquisition timeout after {timeout_s:.1f}s")

                    time.sleep(0.01)

                t_scanned = time.perf_counter()
                # Stop sequence
                if self.core.isSequenceRunning():
                    self.core.stopSequenceAcquisition()

                # Reset hardware states
                self.camera.set_trigger_mode("INTERNAL")
                self.scanner.set_spim_state("Idle")
                self.piezo.set_spim_state("Idle")

                # Disable lasers (important for sample health!)
                self.core.setConfig(self.laser_control.group_name, "ALL OFF")
                self.core.waitForConfig(self.laser_control.group_name, "ALL OFF")

                # Store volume
                self._last_volume = np.array(images)
                self._last_volume_time = time.time()
                logger.info(
                    "Side %s stack: lasers on %.0f ms, camera ready %.0f, scan %.0f, put away %.0f",
                    self.side,
                    (t_lasers - t0) * 1000,
                    (t_ready - t_lasers) * 1000,
                    (t_scanned - t_ready) * 1000,
                    (time.perf_counter() - t_scanned) * 1000,
                )

            except Exception as exc:
                # Cleanup on error - always turn off lasers!
                try:
                    self.core.stopSequenceAcquisition()
                    self.camera.set_trigger_mode("INTERNAL")
                    self.scanner.set_spim_state("Idle")
                    self.piezo.set_spim_state("Idle")
                    # Critical: disable lasers even on error
                    self.core.setConfig(self.laser_control.group_name, "ALL OFF")
                    self.core.waitForConfig(self.laser_control.group_name, "ALL OFF")
                except Exception:
                    pass
                status.set_exception(exc)
            else:
                status.set_finished()
            finally:
                watch.cancel()

        threading.Thread(target=wait).start()

        return status

    def read(self):
        """Read acquired volume data."""
        if self._last_volume is not None:
            data = OrderedDict()
            data[self.name] = {
                "value": self._last_volume,
                # When the stack began, which is when the sample was imaged.
                "timestamp": self._scan_started or self._last_volume_time or time.time(),
            }
            return data
        else:
            return OrderedDict()

    def describe(self):
        """Describe volume data format."""
        data = OrderedDict()
        data[self.name] = {
            "source": self.name,
            "dtype": "array",
            "shape": getattr(self._last_volume, "shape", []),
            "units": "counts",
        }
        return data

    def read_configuration(self):
        """Required for Bluesky."""
        return OrderedDict()

    def describe_configuration(self):
        """Required for Bluesky."""
        return OrderedDict()


class DiSPIMTwoSidedVolumeScanner:
    """Both views in one scan, the way the ASIdiSPIM plugin takes them.

    Taking side A and then side B as two volumes puts 2.4 s between the
    starts of the two stacks: 0.8 s is side A's scan, the rest is putting A
    away and setting B up, one setting at a time. The controller can do both
    sides itself. Everything for both sides is set up first, the card is
    told two sides with a short wait between them, both cameras are started,
    and one trigger runs side A, the wait, then side B. The starts of the
    two stacks are then one scan and the wait apart (the card waits before
    each side, A as well).

    It reads as two volumes under the names of the two one-sided scanners,
    so whoever takes a volume by name finds each side where it always was.
    """

    def __init__(
        self,
        a: DiSPIMVolumeScanner,
        b: DiSPIMVolumeScanner,
        name: str = "volume_scanner_ab",
    ):
        self.name = name
        self.parent = None  # Required for Bluesky
        self.a = a
        self.b = b
        self.core = a.core
        self.laser_control = a.laser_control
        self._configured = False
        self._num_slices: int | None = None
        self._laser_config: str | None = None
        self._volumes: dict[str, np.ndarray] = {}
        self._started: dict[str, float] = {}

    def configure(
        self,
        num_slices: int,
        exposure_ms: float,
        side_a: dict,
        side_b: dict,
        laser_config: str = "488 and 561",
        laser_power_488_pct: float | None = None,
        laser_power_561_pct: float | None = None,
        laser_power_405_pct: float | None = None,
        laser_power_637_pct: float | None = None,
        timing_params: dict | None = None,
        delay_before_side_ms: float = 50.0,
    ):
        """Set both sides up. ``side_a`` and ``side_b`` each carry that side's
        galvo_amplitude, galvo_center, piezo_amplitude and piezo_center."""
        t0 = time.perf_counter()
        # Side B first: each one-sided set-up writes its own side to the card
        # as the first side, and the last one written must be A.
        for vs, s in ((self.b, side_b), (self.a, side_a)):
            vs.camera.configure_for_volume_acquisition(exposure_ms)
            vs.scanner.configure_for_volume_acquisition(
                galvo_amplitude=s["galvo_amplitude"],
                galvo_center=s["galvo_center"],
                num_slices=num_slices,
                timing_params=timing_params,
                first_side=vs.side,
            )
            vs.piezo.configure_for_volume_acquisition(
                amplitude_um=s["piezo_amplitude"],
                offset_um=s["piezo_center"],
                num_slices=num_slices,
            )
        # The card: two sides, A first, and the wait between them.
        self.a.scanner.configure_spim_parameters(num_slices=num_slices, num_sides=2, first_side="A")
        self.core.setProperty(
            self.a.scanner.name, "SPIMDelayBeforeSide(ms)", float(delay_before_side_ms)
        )
        for wavelength, pct in (
            (488, laser_power_488_pct),
            (561, laser_power_561_pct),
            (405, laser_power_405_pct),
            (637, laser_power_637_pct),
        ):
            if pct is not None:
                self.laser_control.set_power_pct(wavelength, pct)
        self._num_slices = num_slices
        self._laser_config = laser_config
        self._configured = True
        logger.info("Both sides configured in %.0f ms", (time.perf_counter() - t0) * 1000)

    def _pop(self) -> tuple[Any, str | None]:
        """The next frame and the camera it came from, when the core says."""
        try:
            md = pymmcore.Metadata()
            img = self.core.popNextImageMD(md)
        except (AttributeError, TypeError):
            return self.core.popNextImage(), None
        # The frame is out of the buffer by now: a tag that cannot be read
        # must not cost the frame.
        try:
            return img, str(md.GetSingleTag("Camera").GetValue())
        except (AttributeError, TypeError, RuntimeError):
            return img, None

    def _put_away(self) -> None:
        for vs in (self.a, self.b):
            if self.core.isSequenceRunning(vs.camera.name):
                self.core.stopSequenceAcquisition(vs.camera.name)
            vs.camera.set_trigger_mode("INTERNAL")
            vs.piezo.set_spim_state("Idle")
        self.a.scanner.set_spim_state("Idle")
        # One side again, for whatever scans next.
        self.a.scanner.configure_spim_parameters(
            num_slices=self._num_slices or 1, num_sides=1, first_side="A"
        )
        self.core.setConfig(self.laser_control.group_name, "ALL OFF")
        self.core.waitForConfig(self.laser_control.group_name, "ALL OFF")

    def trigger(self):
        if not self._configured or self._num_slices is None:
            raise RuntimeError("Device not configured. Call configure() first.")
        n = self._num_slices
        status = Status(obj=self, timeout=120)

        def wait():
            watch = _lasers_out_after(self.core, self.laser_control.group_name, LASERS_ON_AT_MOST_S)
            try:
                self.core.setConfig(self.laser_control.group_name, self._laser_config)
                self.core.waitForConfig(self.laser_control.group_name, self._laser_config)
                if self.core.isSequenceRunning():
                    self.core.stopSequenceAcquisition()
                self.core.clearCircularBuffer()
                if self.core.getBufferTotalCapacity() < 2 * n:
                    self.core.setCircularBufferMemoryFootprint(1024)
                for vs in (self.a, self.b):
                    self.core.prepareSequenceAcquisition(vs.camera.name)
                    self.core.waitForDevice(vs.camera.name)
                    self.core.startSequenceAcquisition(vs.camera.name, n, 0, True)
                    self.core.waitForDevice(vs.camera.name)

                names = {self.a.camera.name: "A", self.b.camera.name: "B"}
                frames: dict[str, list] = {"A": [], "B": []}
                # A stack began when its first frame came: the card waits
                # before each side, A as well, so the trigger is not A's start.
                started: dict[str, float] = {}
                self.a.scanner.set_spim_state("Running")

                timeout_s = settings.timeouts.volume_acquisition
                t0 = time.time()
                while len(frames["A"]) + len(frames["B"]) < 2 * n:
                    if self.core.getRemainingImageCount() > 0:
                        img, cam = self._pop()
                        try:
                            img = _safe_obtain(img)
                        except (ImportError, AttributeError):
                            pass
                        # The camera's name says the side. A core that gives
                        # no name gives the frames in order: A's, then B's.
                        side = names.get(cam or "") or ("A" if len(frames["A"]) < n else "B")
                        started.setdefault(side, time.time())
                        frames[side].append(img)
                        continue
                    if time.time() - t0 > timeout_s:
                        raise TimeoutError(
                            f"Two-sided volume timed out after {timeout_s:.1f}s with "
                            f"{len(frames['A'])} + {len(frames['B'])} of {n} + {n} frames"
                        )
                    time.sleep(0.005)
                if len(frames["A"]) != n or len(frames["B"]) != n:
                    raise RuntimeError(
                        f"Two-sided volume: {len(frames['A'])} frames from A and "
                        f"{len(frames['B'])} from B, wanted {n} of each"
                    )
                self._put_away()
                self._volumes = {"A": np.array(frames["A"]), "B": np.array(frames["B"])}
                self._started = started
                logger.info(
                    "Both sides taken: B began %.0f ms after A",
                    (started["B"] - started["A"]) * 1000,
                )
            except Exception as exc:
                try:
                    self._put_away()  # the lasers go out whatever happened
                except Exception:
                    pass
                status.set_exception(exc)
            else:
                status.set_finished()
            finally:
                watch.cancel()

        threading.Thread(target=wait).start()
        return status

    def read(self):
        data = OrderedDict()
        for side, vs in (("A", self.a), ("B", self.b)):
            if side in self._volumes:
                data[vs.name] = {
                    "value": self._volumes[side],
                    "timestamp": self._started.get(side) or time.time(),
                }
        return data

    def describe(self):
        data = OrderedDict()
        for side, vs in (("A", self.a), ("B", self.b)):
            if side in self._volumes:
                data[vs.name] = {
                    "source": vs.name,
                    "dtype": "array",
                    "shape": list(self._volumes[side].shape),
                    "units": "counts",
                }
        return data

    def read_configuration(self):
        return OrderedDict()

    def describe_configuration(self):
        return OrderedDict()


class DiSPIMLightSheetSnap:
    """
    Compound device for single light sheet image acquisition during calibration.

    Combines scanner and camera for synchronized single-image snapshots.
    Used during focus sweeps and piezo-galvo calibration.
    """

    def __init__(
        self,
        scanner: DiSPIMScanner,
        camera: DiSPIMCamera,
        name: str = "lightsheet_snap",
    ):
        self.name = name
        self.parent = None  # Required for Bluesky
        self.scanner = scanner
        self.camera = camera

        self._last_image = None
        self._last_image_time = None

    def configure(
        self,
        sheet_width_deg: float = 8.0,
        y_position_deg: float = 0.0,
        exposure_ms: float = 50.0,
    ):
        """
        Configure light sheet parameters for single snapshot.

        Parameters
        ----------
        sheet_width_deg : float
            Light sheet width (X-axis amplitude) in degrees (default: 8.0)
        y_position_deg : float
            Light sheet Y-position offset in degrees (default: 0.0)
        exposure_ms : float
            Camera exposure time in milliseconds (default: 50.0)
        """
        # Configure scanner for continuous light sheet
        self.scanner.configure_for_calibration()
        self.scanner.set_y_offset(y_position_deg)

        # Configure camera for single snapshot
        self.camera.configure_for_calibration(exposure_ms)

    def set_y_position(self, angle_deg: float):
        """
        Adjust light sheet Y-position for focus sweeps.

        Parameters
        ----------
        angle_deg : float
            Y-axis offset angle in degrees
        """
        self.scanner.set_y_offset(angle_deg)

    def trigger(self):
        """
        Capture single light sheet image.

        Returns
        -------
        Status
            Ophyd status object for the capture
        """
        return self.camera.trigger()

    def read(self):
        """Read captured image."""
        return self.camera.read()

    def describe(self):
        """Describe image data format."""
        return self.camera.describe()

    def read_configuration(self):
        """Required for Bluesky."""
        return OrderedDict()

    def describe_configuration(self):
        """Required for Bluesky."""
        return OrderedDict()

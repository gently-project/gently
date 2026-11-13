"""A simulated rig: the real device layer on a stand-in for the Micro-Manager core.

    uv run python tools/sim_rig.py                       # device layer on :60610, no hardware
    GENTLY_STORAGE_PATH=<same folder it prints> \\
        uv run python launch_gently.py --no-api --no-auth --no-browser

Everything above MMCore is the production code: the device classes, the plans,
the pollers, every route. Only the core is replaced, by `SimCore` below, which
reads the rig's own Micro-Manager config for its devices and presets and then
answers the calls the hardware layer makes:

- one "serial port" shared by every Tiger device, behind one lock, where each
  exchange costs `--exchange-ms` (30 by default: an estimate, until
  tools/tiger_roundtrip.py has timed the real controller). So the sim queues
  in the way the rig queues, and a polling change can be felt here;
- axes that take time to travel (the F-drive at 1.9 mm/s is 13 s from the top);
- cameras that return frames: three embryos sit at fixed stage positions, dark
  ovals on the bottom camera's brightfield, and on a light-sheet camera a cloud
  of nuclei that shows only while that side's beam is armed and a line is
  routed, in focus only where the piezo meets the sheet.

It exists because CI drives no browser and the rig is not always on. It is a
way to exercise the UI and the device layer end to end; it is not a model of
the optics, and nothing measured here is a measurement of the microscope.

Its sessions, logs and frames go to their own storage root (printed at start,
default a `gently-sim` folder in the temp directory), never to the lab's.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
MM_CFG = REPO / "config" / "MMConfig_tracking_screening.cfg"

# The dish: embryos at stage µm, each a cloud of nuclei (dx, dy, dz µm).
EMBRYOS = [(-124.0, -355.0), (-310.0, -402.0), (-88.0, -511.0)]
BOTTOM_UM_PER_PX = 0.65  # 6.5 µm pixels behind 10x: operate-math's BASE_UM_PER_PX
SPIM_UM_PER_PX = 0.1625  # 6.5 µm pixels behind 40x
# Where the piezo has to be for the sheet a galvo angle puts down: µm per degree, and µm at 0.
FOCUS = {"A": (16.0, 2.0), "B": (-15.2, -3.0)}
LINE_OF_OUTPUT = {"5": 405, "6": 488, "7": 561, "8": 637}
SPEED_UM_S = {"xy": 5745.0, "z": 1920.0, "piezo": 20000.0}

# MM::DeviceType
CAMERA, SHUTTER, STATE, STAGE, XYSTAGE, SERIAL, GENERIC, HUB, GALVO = 2, 3, 4, 5, 6, 7, 8, 15, 16


class _Setting:
    def __init__(self, device: str, prop: str, value: str):
        self._d, self._p, self._v = device, prop, value

    def getDeviceLabel(self) -> str:
        return self._d

    def getPropertyName(self) -> str:
        return self._p

    def getPropertyValue(self) -> str:
        return self._v


class _Configuration:
    def __init__(self, settings: list[_Setting]):
        self._s = settings

    def size(self) -> int:
        return len(self._s)

    def getSetting(self, i: int) -> _Setting:
        return self._s[i]


class _Axis:
    """A position that takes time to change."""

    def __init__(self, at: float, speed: float):
        self.start = self.target = float(at)
        self.t0 = self.t1 = 0.0
        self.speed = speed

    def now(self) -> float:
        t = time.monotonic()
        if t >= self.t1:
            return self.target
        f = (t - self.t0) / max(1e-9, self.t1 - self.t0)
        return self.start + (self.target - self.start) * f

    def go(self, to: float) -> None:
        self.start = self.now()
        self.target = float(to)
        self.t0 = time.monotonic()
        self.t1 = self.t0 + abs(self.target - self.start) / self.speed

    def moving(self) -> bool:
        return time.monotonic() < self.t1

    def halt(self) -> None:
        self.target = self.start = self.now()
        self.t1 = 0.0


class SimCore:
    """The subset of pymmcore.CMMCore the hardware layer calls."""

    def __init__(self, exchange_s: float = 0.030):
        self.exchange_s = exchange_s
        self._port = threading.Lock()  # the Tiger's serial port: one exchange at a time
        self._state = threading.RLock()
        self.devices: dict[str, tuple[str, str]] = {}  # label -> (module, device)
        self.parents: dict[str, str] = {}
        self.props: dict[str, dict[str, str]] = {"Core": {"AutoShutter": "1"}}
        self.groups: dict[str, dict[str, list[tuple[str, str, str]]]] = {}
        self.axes: dict[str, _Axis] = {}
        self.xy: dict[str, tuple[_Axis, _Axis]] = {}
        self.galvo: dict[str, list[float]] = {}
        self.exposure: dict[str, float] = {}
        self.roi: dict[str, tuple[int, int, int, int] | None] = {}
        self._camera = ""
        self._callback: Any = None
        self._snapped: list[np.ndarray] = []
        self._seq: deque[np.ndarray] = deque(maxlen=400)
        self._seq_stop = threading.Event()
        self._seq_thread: threading.Thread | None = None
        self._last: np.ndarray | None = None
        rng = np.random.default_rng(1)
        self._noise = [
            rng.normal(100, 6, (2304, 2304)).clip(60, 160).astype(np.uint16) for _ in range(3)
        ]
        self._frame = 0
        self._nuclei = [
            [
                (float(a), float(b), float(c))
                for a, b, c in zip(
                    rng.normal(0, 9, 40), rng.normal(0, 6, 40), rng.normal(0, 6, 40), strict=True
                )
            ]
            for _ in EMBRYOS
        ]

    # ── the port ────────────────────────────────────────────────────────
    def _tiger(self, label: str) -> bool:
        return label == "TigerCommHub" or self.parents.get(label) == "TigerCommHub"

    def _exchange(self, label: str, n: int = 1) -> None:
        if self.exchange_s <= 0 or not self._tiger(label):
            return
        for _ in range(n):
            with self._port:
                time.sleep(self.exchange_s)

    def _known(self, label: str) -> None:
        if label not in self.props:
            raise RuntimeError(f'No device with label "{label}"')

    # ── boot ────────────────────────────────────────────────────────────
    def enableStderrLog(self, enabled: bool) -> None:
        pass

    def setDeviceAdapterSearchPaths(self, paths: list[str]) -> None:
        pass

    def registerCallback(self, callback: Any) -> None:
        self._callback = callback

    def loadSystemConfiguration(self, path: str) -> None:
        startup: list[tuple[str, str, str]] = []
        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            parts = [p.strip() if i < 3 else p for i, p in enumerate(raw.split(","))]
            if not parts or parts[0].startswith("#"):
                continue
            kind = parts[0]
            if kind == "Device" and len(parts) >= 4:
                self.devices[parts[1]] = (parts[2], parts[3].strip())
                self.props.setdefault(parts[1], {"Name": parts[3].strip()})
            elif kind == "Parent" and len(parts) >= 3:
                self.parents[parts[1]] = parts[2].strip()
            elif kind == "Property" and len(parts) >= 4:
                if parts[1] == "Core" and parts[2] == "Initialize":
                    continue
                self.props.setdefault(parts[1], {})[parts[2]] = ",".join(parts[3:]).strip()
            elif kind == "ConfigGroup" and len(parts) >= 6:
                group, preset = parts[1], parts[2]  # a preset's own spaces are kept ("405 only ")
                preset = raw.split(",")[2]
                setting = (parts[3].strip(), parts[4].strip(), ",".join(parts[5:]).strip())
                self.groups.setdefault(group, {}).setdefault(preset, []).append(setting)
                if group == "System" and preset == "Startup":
                    startup.append(setting)
        self._camera = self.props["Core"].get("Camera", "")
        for label, (module, device) in self.devices.items():
            self._seed(label, module, device)
        for device, prop, value in startup:  # MMCore applies System/Startup at load
            self.props.setdefault(device, {})[prop] = value

    def _seed(self, label: str, module: str, device: str) -> None:
        p = self.props[label]
        if device.startswith("XYStage"):
            self.xy[label] = (
                _Axis(EMBRYOS[0][0], SPEED_UM_S["xy"]),
                _Axis(EMBRYOS[0][1], SPEED_UM_S["xy"]),
            )
            for k, v in (("LowerLimX", -500), ("UpperLimX", 500), ("LowerLimY", -500)):
                p.setdefault(f"{k}(mm)", f"{v:.4f}")
            p.setdefault("UpperLimY(mm)", "500.0000")
            p.setdefault("JoystickEnabled", "Yes")
        elif device.startswith("ZStage:V"):
            self.axes[label] = _Axis(114.6, SPEED_UM_S["z"])
        elif device.startswith("ZStage"):
            self.axes[label] = _Axis(25.6, SPEED_UM_S["z"])
        elif device.startswith("PiezoStage"):
            self.axes[label] = _Axis(0.0, SPEED_UM_S["piezo"])
            p.update({"LowerLim(mm)": "-0.0750", "UpperLim(mm)": "0.0750", "SPIMState": "Idle"})
        elif device.startswith("Scanner"):
            self.galvo[label] = [0.0, 0.0]
            p.update(
                {
                    "BeamEnabled": "No",
                    "SPIMState": "Idle",
                    "MinDeflectionX(deg)": "-4.0000",
                    "MaxDeflectionX(deg)": "4.0000",
                    "MinDeflectionY(deg)": "-4.0000",
                    "MaxDeflectionY(deg)": "4.0000",
                    "SingleAxisXOffset(deg)": "0.0000",
                    "SingleAxisYOffset(deg)": "0.0000",
                }
            )
        elif device.startswith("PLogic"):
            p.setdefault("OutputChannel", "none of outputs 5-8")
        elif device.startswith("LED"):
            p.update({"State": "Closed", "LED Intensity(%)": "12"})
        elif module == "CoherentScientificRemote":
            for line, pct in (("405-100C", 5.0), ("488-100C", 3.1), ("637-140C", 9.1)):
                p[f"Laser {line} - PowerSetpoint (%)"] = f"{pct:.4f}"
            p["Laser OBIS LS 561-100 - PowerSetpoint (%)"] = "4.9000"
        elif module in ("HamamatsuHam", "PCO_Camera"):
            self.exposure[label] = 11.2 if module == "PCO_Camera" else 20.0
            self.roi[label] = None
            p.update({"TRIGGER SOURCE": "INTERNAL", "SENSOR MODE": "AREA", "Binning": "1x1"})
        elif device == "Multi Camera":
            self.exposure[label] = 20.0

    def getLoadedDevices(self) -> list[str]:
        return [*self.devices, "Core"]

    def getDeviceType(self, label: str) -> int:
        module, device = self.devices.get(label, ("", ""))
        if module == "SerialManager":
            return SERIAL
        if device == "TigerCommHub":
            return HUB
        for prefix, kind in (
            ("XYStage", XYSTAGE),
            ("ZStage", STAGE),
            ("PiezoStage", STAGE),
            ("Turret", STATE),
            ("Scanner", GALVO),
            ("PLogic", SHUTTER),
            ("LED", SHUTTER),
        ):
            if device.startswith(prefix):
                return kind
        if module in ("HamamatsuHam", "PCO_Camera") or device == "Multi Camera":
            return CAMERA
        return GENERIC

    def getParentLabel(self, label: str) -> str:
        return self.parents.get(label, "")

    # ── properties ──────────────────────────────────────────────────────
    def getDevicePropertyNames(self, label: str) -> list[str]:
        self._known(label)
        return sorted(self.props[label])

    def isPropertyReadOnly(self, label: str, prop: str) -> bool:
        return prop in ("Name", "Description", "SerialResponse")

    def getAllowedPropertyValues(self, label: str, prop: str) -> list[str]:
        return {"BeamEnabled": ["No", "Yes"], "State": ["Closed", "Open"]}.get(prop, [])

    def getProperty(self, label: str, prop: str) -> str:
        self._known(label)
        if prop != "SerialResponse":
            self._exchange(label)
        with self._state:
            if prop not in self.props[label]:
                raise RuntimeError(f'No property "{prop}" on "{label}" (simulated rig)')
            return self.props[label][prop]

    def setProperty(self, label: str, prop: str, value: Any) -> None:
        self._known(label)
        text = f"{value:.4f}" if isinstance(value, float) else str(value)
        self._exchange(label)
        with self._state:
            changed = self.props[label].get(prop) != text
            self.props[label][prop] = text
            if label == "TigerCommHub" and prop == "SerialCommand":
                self.props[label]["SerialResponse"] = self._answer(text)
            if prop in ("SingleAxisXOffset(deg)", "SingleAxisYOffset(deg)") and label in self.galvo:
                self.galvo[label][0 if "X" in prop else 1] = float(text)
        if changed and self._callback is not None and prop != "SerialCommand":
            try:
                self._callback.onPropertyChanged(label, prop, text)
            except Exception:
                pass

    def _answer(self, command: str) -> str:
        """The controller's reply to a raw command, for the ones the stage sends."""
        xy = next(iter(self.xy), "")
        p = self.props.get(xy, {})
        head, _, rest = command.strip().partition(" ")
        if head in ("SL", "SU"):
            side = "LowerLim" if head == "SL" else "UpperLim"
            if "?" in rest or not rest:
                return f":A X={float(p[f'{side}X(mm)']):.6f} Y={float(p[f'{side}Y(mm)']):.6f} "
            for part in rest.split():
                axis, _, number = part.partition("=")
                if axis in ("X", "Y") and number:
                    p[f"{side}{axis}(mm)"] = f"{float(number):.4f}"
            return ":A "
        return ":A "

    def updateSystemStateCache(self) -> None:
        self._exchange("TigerCommHub", 18)  # the ~2 s a full sweep holds the port

    def getSystemStateCache(self) -> _Configuration:
        with self._state:
            return _Configuration(
                [_Setting(d, k, v) for d, ps in self.props.items() for k, v in ps.items()]
            )

    # ── presets ─────────────────────────────────────────────────────────
    def getAvailableConfigs(self, group: str) -> list[str]:
        return list(self.groups.get(group, {}))

    def setConfig(self, group: str, preset: str) -> None:
        if preset not in self.groups.get(group, {}):
            raise RuntimeError(f'Preset "{preset}" is not defined in group "{group}"')
        for device, prop, value in self.groups[group][preset]:
            self.setProperty(device, prop, value)

    def waitForConfig(self, group: str, preset: str) -> None:
        pass

    def getCurrentConfig(self, group: str) -> str:
        with self._state:
            for preset, settings in self.groups.get(group, {}).items():
                if all(self.props.get(d, {}).get(p) == v for d, p, v in settings):
                    return preset
        return ""

    # ── axes ────────────────────────────────────────────────────────────
    def setFocusDevice(self, label: str) -> None:
        self.props["Core"]["Focus"] = label

    def setPosition(self, label: str, position: float) -> None:
        self._exchange(label)
        self.axes[label].go(position)

    def getPosition(self, label: str) -> float:
        self._exchange(label)
        return self.axes[label].now()

    def setXYPosition(self, *args: Any) -> None:
        label = args[0] if len(args) == 3 else next(iter(self.xy))
        x, y = args[-2], args[-1]
        self._exchange(label)
        ax, ay = self.xy[label]
        ax.go(x)
        ay.go(y)
        # both axes arrive together, at the slower one's time
        ax.t1 = ay.t1 = max(ax.t1, ay.t1)

    def getXYPosition(self, label: str | None = None) -> list[float]:
        label = label or next(iter(self.xy))
        self._exchange(label, 2)  # the adapter asks for X, then for Y
        ax, ay = self.xy[label]
        return [ax.now(), ay.now()]

    def setGalvoPosition(self, label: str, a: float, b: float) -> None:
        self._exchange(label)
        self.galvo[label] = [float(a), float(b)]

    def getGalvoPosition(self, label: str) -> list[float]:
        self._exchange(label)
        return list(self.galvo[label])

    def _moving(self, label: str) -> bool:
        if label in self.axes:
            return self.axes[label].moving()
        if label in self.xy:
            return any(a.moving() for a in self.xy[label])
        return False

    def waitForDevice(self, label: str) -> None:
        # The adapter asks the controller whether it is busy until it is not.
        self._exchange(label)
        while self._moving(label):
            time.sleep(0.02)
            self._exchange(label)

    def stop(self, label: str) -> None:
        self._exchange(label)
        for axis in [self.axes.get(label), *self.xy.get(label, ())]:
            if axis is not None:
                axis.halt()

    # ── cameras ─────────────────────────────────────────────────────────
    def getCameraDevice(self) -> str:
        return self._camera

    def setCameraDevice(self, label: str) -> None:
        self._known(label)
        self._camera = label
        self.props["Core"]["Camera"] = label

    def setExposure(self, *args: Any) -> None:
        label = args[0] if len(args) == 2 else self._camera
        self.exposure[label] = float(args[-1])
        if label == "Multi Camera":
            for cam in self._physical():
                self.exposure[cam] = float(args[-1])
        self.props[label]["Exposure"] = f"{float(args[-1]):.4f}"

    def getExposure(self, label: str | None = None) -> float:
        return self.exposure.get(label or self._camera, 10.0)

    def setROI(self, *args: Any) -> None:
        label = args[0] if len(args) == 5 else self._camera
        x, y, w, h = (int(v) for v in args[-4:])
        self.roi[label] = (x, y, w, h)

    def clearROI(self) -> None:
        for cam in self._physical() if self._camera == "Multi Camera" else [self._camera]:
            self.roi[cam] = None

    def _physical(self) -> list[str]:
        p = self.props.get("Multi Camera", {})
        return [p[k] for k in ("Physical Camera 1", "Physical Camera 2") if p.get(k) in self.props]

    def getNumberOfCameraChannels(self) -> int:
        return len(self._physical()) if self._camera == "Multi Camera" else 1

    def getCameraChannelName(self, channel: int) -> str:
        return self._physical()[channel] if self._camera == "Multi Camera" else self._camera

    def snapImage(self) -> None:
        cams = self._physical() if self._camera == "Multi Camera" else [self._camera]
        shutter = self.props["Core"].get("Shutter", "")
        auto = self.props["Core"].get("AutoShutter", "1") == "1" and shutter in self.props
        if auto:
            self._exchange(shutter, 2)  # open, and wait for it
        time.sleep(self.exposure.get(self._camera, 10.0) / 1000.0 + 0.012)
        frames = [self._render(cam) for cam in cams]
        if auto:
            self._exchange(shutter)  # close
        self._snapped = frames
        self._last = frames[0]

    def getImage(self, channel: int = 0) -> np.ndarray:
        if not self._snapped:
            raise RuntimeError("getImage before snapImage (simulated rig)")
        return self._snapped[min(channel, len(self._snapped) - 1)]

    # sequence acquisition: frames at the exposure's cadence, into a buffer
    def prepareSequenceAcquisition(self, label: str) -> None:
        pass

    def getBufferTotalCapacity(self) -> int:
        return 400

    def setCircularBufferMemoryFootprint(self, megabytes: int) -> None:
        pass

    def clearCircularBuffer(self) -> None:
        self._seq.clear()

    def isSequenceRunning(self, label: str | None = None) -> bool:
        return self._seq_thread is not None and self._seq_thread.is_alive()

    def _run_sequence(self, label: str, count: int | None) -> None:
        n = 0
        while not self._seq_stop.is_set() and (count is None or n < count):
            time.sleep(self.exposure.get(label, 10.0) / 1000.0 + 0.004)
            frame = self._render(label)
            self._seq.append(frame)
            self._last = frame
            n += 1

    def _start_sequence(self, label: str, count: int | None) -> None:
        self.stopSequenceAcquisition()
        self._seq_stop.clear()
        self._seq_thread = threading.Thread(
            target=self._run_sequence, args=(label, count), daemon=True
        )
        self._seq_thread.start()

    def startSequenceAcquisition(self, *args: Any) -> None:
        label = args[0] if isinstance(args[0], str) else self._camera
        count = int(args[1] if isinstance(args[0], str) else args[0])
        self._start_sequence(label, count)

    def startContinuousSequenceAcquisition(self, interval_ms: float) -> None:
        self._start_sequence(self._camera, None)

    def stopSequenceAcquisition(self, label: str | None = None) -> None:
        self._seq_stop.set()
        if self._seq_thread is not None and self._seq_thread.is_alive():
            self._seq_thread.join(timeout=2.0)
        self._seq_thread = None

    def getRemainingImageCount(self) -> int:
        return len(self._seq)

    def popNextImage(self) -> np.ndarray:
        return self._seq.popleft()

    def getLastImage(self) -> np.ndarray:
        if self._last is None:
            raise RuntimeError("no image yet (simulated rig)")
        return self._last

    # ── what the cameras see ────────────────────────────────────────────
    def _stage(self) -> tuple[float, float]:
        ax, ay = next(iter(self.xy.values()))
        return ax.now(), ay.now()

    def _routed_power(self) -> float:
        """Percent of laser reaching the sheet: the routed lines' setpoints."""
        channel = self.props.get("PLogic:E:36", {}).get("OutputChannel", "")
        if "none" in channel:
            return 0.0
        digits = [c for c in channel if c in LINE_OF_OUTPUT]
        if "5-8" in channel:
            digits = list(LINE_OF_OUTPUT)
        coherent = next((d for d, (m, _) in self.devices.items() if m.startswith("Coherent")), "")
        total = 0.0
        for d in digits:
            line = str(LINE_OF_OUTPUT[d])
            for prop, value in self.props.get(coherent, {}).items():
                if line in prop and "PowerSetpoint" in prop:
                    total += float(value)
        return total

    def _crop(self, label: str, frame: np.ndarray) -> np.ndarray:
        roi = self.roi.get(label)
        if roi is None:
            return frame
        x, y, w, h = roi
        return np.ascontiguousarray(frame[y : y + h, x : x + w])

    def _render(self, label: str) -> np.ndarray:
        self._frame += 1
        module = self.devices.get(label, ("", ""))[0]
        if module == "PCO_Camera":
            return self._crop(label, self._bottom(label))
        return self._crop(label, self._lightsheet(label))

    def _bottom(self, label: str) -> np.ndarray:
        size = 2048
        led = self.props.get("LED:X:31", {})
        lit = led.get("State") == "Open"
        level = (
            float(led.get("LED Intensity(%)", "12")) * self.exposure.get(label, 11.2) * 18.0
            if lit
            else 40.0
        )
        level = min(level, 60000.0)
        base = self._noise[self._frame % 3][:size, :size]
        frame = (base.astype(np.float32) * (0.2 + level / 2500.0) + level).clip(0, 65535)
        sx, sy = self._stage()
        yy, xx = np.ogrid[:size, :size]
        for ex, ey in EMBRYOS:
            fx = size / 2 + (ex - sx) / BOTTOM_UM_PER_PX
            fy = size / 2 - (ey - sy) / BOTTOM_UM_PER_PX
            if -80 < fx < size + 80 and -80 < fy < size + 80:
                inside = ((xx - fx) / 40.0) ** 2 + ((yy - fy) / 25.0) ** 2 <= 1.0
                frame[inside] *= 0.55
        return frame.astype(np.uint16)

    def _lightsheet(self, label: str) -> np.ndarray:
        size = 2304
        frame = self._noise[self._frame % 3].copy()
        side = "B" if label.endswith("2") else "A"
        scanner = "Scanner:CD:33" if side == "B" else "Scanner:AB:33"
        piezo = "PiezoStage:Q:35" if side == "B" else "PiezoStage:P:34"
        if self.props.get(scanner, {}).get("BeamEnabled") != "Yes":
            return frame
        power = self._routed_power()
        if power <= 0:
            return frame
        slope, offset = FOCUS[side]
        angle = self.galvo.get(scanner, [0.0, 0.0])[1]
        sheet_z = slope * angle  # where the sheet cuts the embryo, µm
        defocus = abs(self.axes[piezo].now() - (sheet_z + offset)) if piezo in self.axes else 0.0
        sigma = math.hypot(6.0, 4.0 * defocus)
        gain = power * self.exposure.get(label, 20.0) * 55.0 * (6.0 / sigma) ** 2
        sx, sy = self._stage()
        r = int(min(3 * sigma, 160))
        yy, xx = np.mgrid[-r : r + 1, -r : r + 1]
        stamp = np.exp(-(xx**2 + yy**2) / (2 * sigma**2)).astype(np.float32)
        acc = np.zeros((size, size), np.float32)
        for (ex, ey), nuclei in zip(EMBRYOS, self._nuclei, strict=True):
            if abs(ex - sx) > 260 or abs(ey - sy) > 260:
                continue
            for dx, dy, dz in nuclei:
                weight = math.exp(-((dz - sheet_z) ** 2) / (2 * 2.5**2))
                if weight < 0.02:
                    continue
                cx = int(size / 2 + (ex + dx - sx) / SPIM_UM_PER_PX)
                cy = int(size / 2 - (ey + dy - sy) / SPIM_UM_PER_PX)
                if r <= cx < size - r and r <= cy < size - r:
                    acc[cy - r : cy + r + 1, cx - r : cx + r + 1] += stamp * (gain * weight)
        return (frame + acc).clip(0, 65535).astype(np.uint16)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"SimCore has no {name}() — add it to tools/sim_rig.py")


def _install(exchange_s: float) -> None:
    """Have the hardware layer build a SimCore where it would build CMMCore."""
    import pymmcore

    import gently.hardware.dispim.devices.system as system

    system.pymmcore = types.SimpleNamespace(  # type: ignore[assignment]
        CMMCore=lambda: SimCore(exchange_s), MMEventCallback=pymmcore.MMEventCallback
    )


def _config_dir() -> Path:
    """A config for the sim: the rig's own Micro-Manager file, a mock water bath, no BLE."""
    folder = Path(tempfile.mkdtemp(prefix="gently-sim-config-"))
    shutil.copy(MM_CFG, folder / MM_CFG.name)
    (folder / "config.yml").write_text(
        "organism: celegans\nhardware: dispim\n"
        f"mmconfig: {MM_CFG.name}\nmmdirectory: {folder.as_posix()}\n"
        "temperature:\n  name: temperature\n  backend: mock\n",
        encoding="utf-8",
    )
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--port", type=int, default=60610)
    parser.add_argument(
        "--exchange-ms", type=float, default=30.0, help="what one Tiger exchange costs (0: none)"
    )
    parser.add_argument("--storage", default=str(Path(tempfile.gettempdir()) / "gently-sim"))
    args = parser.parse_args()

    # Before anything of gently's is imported: its settings read this at import.
    os.environ["GENTLY_STORAGE_PATH"] = args.storage
    Path(args.storage).mkdir(parents=True, exist_ok=True)
    print(f"Simulated rig. Storage root: {args.storage}")
    print(f"Run the app with GENTLY_STORAGE_PATH={args.storage}")

    _install(args.exchange_ms / 1000.0)
    # The real entry point from here on: its logging, its console, its routes.
    import start_device_layer

    config = _config_dir() / "config.yml"
    sys.argv = [
        "start_device_layer.py",
        "--port",
        str(args.port),
        "--sam-device",
        "cpu",
        "--config",
        str(config),
    ]
    start_device_layer.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

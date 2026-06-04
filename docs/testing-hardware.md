# Hardware Testing

Gently hardware tests are split into two groups:

- `hardware`: offline contract tests that use fakes/mocks and should run in CI.
- `live_hardware`: opt-in checks that talk to a connected microscope/device layer.

## Offline Hardware Tests

Use the package-level helpers in `gently.hardware.testing` when testing tools or
workflows that normally need a microscope client:

```python
from gently.hardware.testing import MockQueueServerClient

client = MockQueueServerClient(stage_position=(10.0, 20.0))
await client.move_to_position(100.0, 200.0)
assert client.recorded_calls("move_to_position")
```

Run the offline hardware contracts with:

```shell
pytest tests/hardware -m hardware
```

## Live Hardware Tests

Live tests are skipped unless explicitly enabled. Start the device layer first,
then run:

```shell
pytest tests/hardware -m live_hardware --run-hardware --hardware-url http://127.0.0.1:60610
```

`--hardware-url` defaults to `GENTLY_HARDWARE_URL` when set, otherwise
`http://127.0.0.1:60610`.

## Adding New Hardware Tests

Use `hardware` for deterministic tests that should pass without a microscope.
Use `live_hardware` only when the test validates real hardware connectivity,
device-layer state reporting, or behavior that cannot be represented by a mock.

Live tests should assert health and invariants rather than move devices through
large ranges. Keep destructive or sample-altering procedures manual unless they
have explicit safety bounds and operator confirmation.

## Simulation Coverage Matrix

Before adding a simulator, decide what risk the test is meant to catch. Gently
needs several fidelity layers rather than one generic simulated microscope:

| Layer | Purpose | Typical coverage | Default suite |
| --- | --- | --- | --- |
| Device command contract | Check tool/device API semantics and safety gates | command payloads, range checks, error propagation, state shape | yes |
| Hardware digital twin | Check stateful device behavior without live hardware | queue timing, stage/camera/laser/temperature state, retries | opt-in or CI service |
| Optical/perception simulator | Check whether perception/control logic handles images | sample rendering, focus, drift, noise, segmentation outputs | targeted |
| Sample dynamics simulator | Check scientific state over time | development, motion, perturbation, damage/exposure effects | targeted |
| End-to-end rehearsal | Check the full experiment loop | plan, acquire, perceive, decide, recover, export | opt-in |

The helpers in `gently.hardware.testing` cover the device command contract
layer. They are intentionally small fakes, not an optical or biological
simulation. A richer simulator should declare which layer it belongs to, which
failure modes it models, and which real-world behaviors it deliberately leaves
out.

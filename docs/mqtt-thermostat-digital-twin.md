# MQTT Thermostat Digital Twin

`tests/test_temperature_controller.py` includes an opt-in integration check for
the ACUITYnano MQTT thermostat digital twin. It is skipped by default so normal
CI and local development do not require broker credentials or the vendor MQTT
SDK.

## Configuration

Set `GENTLY_MQTT_THERMOSTAT_CONFIG` to either a JSON object or the path to a
JSON file. The config is passed to `create_temperature_controller()` with
`backend` defaulting to `mqtt`.

Example JSON:

```json
{
  "backend": "mqtt",
  "name": "temperature",
  "broker": "mqtt.example.org",
  "port": 8883,
  "user": "gently",
  "password": "replace-me"
}
```

The vendor package may provide embedded broker defaults. In that case the config
can be as small as:

```json
{"backend": "mqtt", "name": "temperature"}
```

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GENTLY_MQTT_THERMOSTAT_CONFIG` | unset | JSON object or path to JSON config. Required to run. |
| `GENTLY_MQTT_THERMOSTAT_TARGET_C` | `21.5` | Commanded setpoint for the test. |
| `GENTLY_MQTT_THERMOSTAT_TIMEOUT_S` | `10` | Seconds to wait for lock or convergence. |
| `GENTLY_MQTT_THERMOSTAT_TOLERANCE_C` | `0.25` | Temperature tolerance for convergence. |

## Run

```shell
pytest tests/test_temperature_controller.py -q
```

Without `GENTLY_MQTT_THERMOSTAT_CONFIG`, the digital-twin test is skipped.
With the config set, the test:

1. Creates the MQTT-backed temperature controller.
2. Enables the controller.
3. Commands a non-blocking setpoint.
4. Verifies immediate setpoint readback.
5. Polls until the twin reports lock or measured temperature convergence.

This checks the runtime path used by `/api/temperature/set` without requiring
live microscope hardware.

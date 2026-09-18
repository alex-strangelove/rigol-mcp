# MHO984 validation

Validated on 2026-09-18 with a Rigol MHO984, firmware `00.01.00`, using
Linux, `pyvisa-py`, and LAN SCPI on port 5555. CH1 had a 10× probe connected
to a roughly 1 kHz, 3.14 V peak-to-peak square-wave test signal.

## Driver

`MHO900Driver` recognizes the MHO934, MHO954, and MHO984 model fields in a
Rigol identification response. Only the MHO984 was tested on hardware.
Other MHO families are intentionally not matched.

The implementation shares the DHO driver methods. Command syntax was checked
against Rigol's [MHO900 Programming Guide](https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/oscilloscopes/MHO900-ProgrammingGuide.pdf),
particularly auto-setup, cursor, display, measurement, and waveform commands.
Live checks confirmed these transport details:

- `:DISPlay:DATA? PNG` returns an IEEE definite-length block containing a PNG.
- ASCII waveform data is bare comma-separated voltage values, without a block
  header. Setting start/stop to 1/1000 retrieves the full NORM screen buffer.
- Cursor `CAX`/`CBX` positions use seconds, not DS1000Z pixel coordinates.
- Measurement registration uses `:MEASure:STATistic:ITEM`.
- Auto-setup uses `:AUToset`, followed by a separate `*OPC?` query.

## Results

The configured stdio MCP server was exercised with the Python MCP client.
The SCPI error queue was checked after each operation.

| Operation | Result |
|---|---|
| `idn` | Selected `MHO900` driver |
| `get_scope_state` | Read all four channel configurations, timebase, and trigger |
| `measure` | CH1: 1.000 kHz, approximately 3.14 Vpp, duty ratio 0.500 (50%) |
| `get_waveform` | 1000 voltage/time samples; identified a square wave with approximately 50% duty |
| `screenshot` | Valid 1024×600 PNG, confirmed visually |
| `set_channel`, `set_timebase`, `set_trigger` | Applied settings and read them back |
| `set_cursors`, `get_cursor_values` | Manual and track cursor positions at ±500 µs; 1 ms separation |
| `single`, `stop`, `run` | Commands accepted; acquisition resumed successfully |
| `autoscale` | Auto-setup completed; CH1 frequency remained 1 kHz |

The 33 original single-source items exposed by `measure` were also queried through
the scope helpers while acquisition was running, with finite readings and
no SCPI errors. Keep acquisition running for built-in measurements; stop or
single-trigger before downloading a consistent waveform.

The two-source command path was checked using CH1 for both sources. `RFDELAY`
returned approximately −500 µs. Same-source `RDELAY` and `RPHASE` returned
the instrument's invalid sentinel, which the server annotated correctly.
This does **not** validate delay/phase accuracy between two physical channels;
that requires a second connected signal.

The system setup was saved before control/auto-setup tests and restored afterward.
Channel settings, timebase, and trigger level were read back to verify restoration.

## AC RMS validation

The `measure` tool also exposes native `ACRMS` on MHO900, using
`:MEASure:STATistic:ITEM ACRMS,CHAN1` and `:MEASure:ITEM? ACRMS,CHAN1`.
The configured stdio MCP server was tested with `ACRMS`, `acrms`, and `ACRMs`;
all returned finite readings without SCPI errors. The MCP reading matched
a direct native query and `sqrt(VRMS² − VAVG²)` within 2% across successive
live acquisitions. This checks the measurement path, not instrument accuracy.

On the connected square wave, AC RMS was approximately 1.54 V, compared with
approximately 2.19 V total RMS and 1.56 V mean. AC RMS removes DC but includes
the square wave itself; these readings are not a noise-floor measurement.

## Regression tests

```bash
uv sync --locked --extra test
uv run --no-sync pytest
```

`tests/test_mho900.py` covers model detection and rejection, driver caching,
bare CSV waveform parsing and time coordinates, PNG framing, measurement
registration and aliases, native AC RMS and rejection on other drivers, cursor
units, and auto-setup completion handling. `tests/test_server.py` also verifies
that the MCP measurement handler returns native AC RMS values.
These tests use fake instruments and do not require hardware.

For a live check, configure `RIGOL_IP`, start the MCP server, then call `idn`,
`get_scope_state`, and `measure` for `CHAN1`/`FREQUENCY` and `CHAN1`/`VPP`.
Use `get_waveform` with `raw_data=true` to inspect samples and `screenshot`
to verify display capture. A probe connected to a known signal is required
to assess measured values.

## Limits

USB transport, other MHO900 models, and timing accuracy between separate channels
have not been hardware-tested. RAW/deep-memory acquisition is not implemented.
The existing tools expose CH1–CH4; this change does not add digital-channel or
signal-generator tools.

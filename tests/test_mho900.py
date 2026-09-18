"""MHO900 dialect regressions using the framing observed on an MHO984 over LAN."""

import pytest

from rigol_mcp import drivers, scope as sc
from tests.conftest import FakeScope, make_block


IDN = "RIGOL TECHNOLOGIES,MHO984,SN,00.01.00"


@pytest.mark.parametrize("model", ["MHO934", "MHO954", "MHO984"])
def test_selects_mho900_driver(model):
    assert drivers.driver_for(f"RIGOL TECHNOLOGIES,{model},SN,00.01.00") is drivers.MHO900


def test_identity_is_case_and_whitespace_insensitive():
    assert drivers.driver_for("rigol technologies, mho984 ,SN,00.01.00") is drivers.MHO900


@pytest.mark.parametrize("idn", [
    "RIGOL TECHNOLOGIES,MHO4000,SN,1.0",
    "RIGOL TECHNOLOGIES,MHO9840,SN,1.0",
    "OTHER,MHO984,SN,1.0",
    "RIGOL TECHNOLOGIES,UNKNOWN,MHO984,1.0",
    "MHO984",
    "",
])
def test_does_not_claim_unverified_families_or_serial_matches(idn):
    with pytest.raises(RuntimeError, match="Unsupported instrument"):
        drivers.driver_for(idn)


def test_detected_driver_is_cached_and_reset():
    s = FakeScope(responses={"*IDN?": IDN})
    assert sc.get_driver(s) is drivers.MHO900
    s.responses["*IDN?"] = FakeScope.DEFAULT_IDN
    assert sc.get_driver(s) is drivers.MHO900
    sc.invalidate_scope()
    assert sc.get_driver(s) is drivers.DS1000Z


def test_waveform_bare_csv_preserves_volts_and_preamble_time_axis():
    # MHO984 ASC data already contains volts; y-origin/reference must not be
    # applied again. Unlike DS1000Z, there is no IEEE block header on this CSV.
    s = FakeScope(responses={
        "*IDN?": IDN,
        ":CHAN1:DISP?": "1",
        ":CHAN1:SCAL?": "0.5",
        ":CHAN1:OFFS?": "-1.562827",
        ":WAV:PRE?": "2,0,1000,1,2.000000E-6,-1.000000E-3,0,6.6667E-05,-23442,32768",
        ":WAV:DATA?": ",".join(["+3.116e+00", "-1.000e-02"] * 500) + "\n",
    })
    data = sc.get_waveform(s, "CHAN1")
    assert data["points"] == 1000
    assert data["voltages_v"] == [3.116, -0.01] * 500
    assert data["time_start_s"] == pytest.approx(-0.001)
    assert data["time_end_s"] == pytest.approx(0.000998)
    assert data["time_increment_s"] == 2e-6
    assert data["warnings"] == []
    assert s.written[-2:] == [":WAV:STAR 1", ":WAV:STOP 1000"]


def test_screenshot_uses_png_block_with_single_parameter():
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
    s = FakeScope(responses={"*IDN?": IDN}, read_buffer=make_block(png))
    assert sc.screenshot_png(s) == png
    assert s.written == [":DISPlay:DATA? PNG"]


def test_measurement_registers_statistic_without_resetting_item():
    s = FakeScope(responses={
        "*IDN?": IDN, ":CHAN1:DISP?": "1", ":MEASure:ITEM? FREQUENCY,CHAN1": "1.0000E+03",
    })
    assert float(sc.measure(s, "CHAN1", "frequency")) == 1000
    assert s.written == [":MEASure:STATistic:ITEM FREQUENCY,CHAN1"]


@pytest.mark.parametrize("item", ["ACRMS", "acrms", "ACRMs"])
def test_ac_rms_uses_native_measurement_not_total_rms(item):
    s = FakeScope(responses={
        "*IDN?": IDN, ":CHAN1:DISP?": "1",
        ":MEASure:ITEM? ACRMS,CHAN1": "1.5382E+00",
        ":MEASure:ITEM? VRMS,CHAN1": "2.1930E+00",
    })
    assert float(sc.measure(s, "chan1", item)) == 1.5382
    assert s.written == [":MEASure:STATistic:ITEM ACRMS,CHAN1"]


def test_ac_rms_preserves_invalid_measurement_annotation():
    s = FakeScope(responses={
        "*IDN?": IDN, ":CHAN1:DISP?": "1", ":MEASure:ITEM? ACRMS,CHAN1": "9.9E37",
    })
    assert "invalid/overflow sentinel" in sc.measure(s, "CHAN1", "ACRMS")


@pytest.mark.parametrize("idn,family", [
    (FakeScope.DEFAULT_IDN, "DS1000Z"),
    ("RIGOL TECHNOLOGIES,DHO924S,SN,1.0", "DHO"),
])
def test_ac_rms_rejected_before_enabling_channel_on_other_drivers(idn, family):
    s = FakeScope(responses={"*IDN?": idn, ":CHAN1:DISP?": "0"})
    with pytest.raises(ValueError, match=f"ACRMS is not supported by the {family} driver"):
        sc.measure(s, "CHAN1", "ACRMS")
    assert s.written == []


@pytest.mark.parametrize("item,native", [
    ("RDELAY", "RRDELAY"), ("FDELAY", "FFDELAY"),
    ("RPHASE", "RRPHASE"), ("FPHASE", "FFPHASE"),
    ("RFDELAY", "RFDELAY"), ("FRPHASE", "FRPHASE"),
])
def test_two_source_measurement_maps_and_queries_native_item(item, native):
    s = FakeScope(responses={
        "*IDN?": IDN, ":CHAN1:DISP?": "1", ":CHAN2:DISP?": "1",
        f":MEASure:ITEM? {native},CHAN1,CHAN2": "1.0000E-06",
    })
    assert float(sc.measure_between(s, "CHAN1", "CHAN2", item)) == 1e-6
    assert s.written == [f":MEASure:STATistic:ITEM {native},CHAN1,CHAN2"]


@pytest.mark.parametrize("mode,prefix", [("MANUAL", ":CURSor:MANual"), ("TRACK", ":CURSor:TRACk")])
def test_cursor_positions_use_seconds_not_ds1000z_pixels(mode, prefix):
    s = FakeScope(responses={
        "*IDN?": IDN, ":SYSTem:ERRor?": "0", ":CURSor:MODE?": mode,
        f"{prefix}:CAX?": "-5.000E-04", f"{prefix}:CBX?": "5.000E-04",
        f"{prefix}:AXValue?": "-5.000E-04", f"{prefix}:BXValue?": "5.000E-04",
        f"{prefix}:XDELta?": "1.000E-03", f"{prefix}:IXDELta?": "1.000E+03",
        f"{prefix}:AYValue?": "0", f"{prefix}:BYValue?": "3.116", f"{prefix}:YDELta?": "3.116",
    })
    sc.set_cursor_positions(s, mode, ax=-0.0005, bx=0.0005)
    assert s.written == [f"{prefix}:CAX -0.0005", f"{prefix}:CBX 0.0005"]
    result = sc.get_cursor_values(s)
    assert result["AX_s"] == -0.0005
    assert result["BX_s"] == 0.0005
    assert float(result["inv_delta_x"]) == 1000


def test_autoscale_uses_autoset_and_separate_completion_query():
    class AutosetScope(FakeScope):
        def query(self, command):
            if command == "*OPC?":
                assert self.written == [":AUToset"]
                assert self.timeout == sc._SLOW_OP_TIMEOUT_MS
            return super().query(command)

    s = AutosetScope(responses={"*IDN?": IDN, "*OPC?": "1", ":SYSTem:ERRor?": "0"})
    s.timeout = 1500
    sc.autoscale(s)
    assert s.timeout == 1500

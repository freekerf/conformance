"""ComWrapper.UsbSerial (Mono SerialPort) on a PTY: open/close, writes, reads,
the two-digit port-name retry (issue #31) and the reset diagnostics."""

import os

import pytest

import System
from LaserGRBL import Firmware, GrblCore, Settings
from LaserGRBL.ComWrapper import IComWrapper

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.fake_grbl import FakeGrbl
from lasergrbl_harness.links import PtyLink
from lasergrbl_harness.waiting import wait_until


def new_usbserial():
    t = cu.clr_type(GrblCore).Assembly.GetType("LaserGRBL.ComWrapper.UsbSerial")
    return IComWrapper(System.Activator.CreateInstance(t))


@pytest.fixture
def pty():
    dev = FakeGrbl()
    link = PtyLink(dev)
    yield link
    link.close()


def configure(w, port):
    args = System.Array[System.Object]([port, System.Int32(115200)])
    w.Configure(args)


def test_open_write_read_close(pty):
    w = new_usbserial()
    assert not w.IsOpen and not w.HasData()
    configure(w, pty.path)
    w.Open()
    w.Open()  # already open: no-op
    assert w.IsOpen
    w.Write(System.Byte(0x3F))
    wait_until(lambda: w.HasData(), 5)
    assert w.ReadLineBlocking().startswith("<Idle|")
    w.Write(System.Array[System.Byte](list(b"$X\n")))
    w.Write("G0 X1\n")
    wait_until(lambda: pty.device.lines == ["$X", "G0 X1"], 5)
    w.Close(False)
    assert not w.IsOpen
    w.Close(True)  # already closed


def test_writes_and_read_on_closed_port(pty):
    w = new_usbserial()
    w.Write(System.Byte(1))
    w.Write(System.Array[System.Byte]([1]))
    w.Write("x")
    with pytest.raises(System.IO.IOException):
        w.ReadLineBlocking()


def test_read_is_logged_when_com_logger_is_enabled(pty, tmp_path):
    from LaserGRBL.ComWrapper import ComLogger

    w = new_usbserial()
    configure(w, pty.path)
    w.Open()
    ComLogger.StartLog(str(tmp_path / "com.log"))
    try:
        w.Write(System.Byte(0x3F))
        assert w.ReadLineBlocking().startswith("<Idle|")
    finally:
        ComLogger.StopLog()
        w.Close(True)


def test_two_digit_port_name_retries_without_last_digit(pty):
    # issue #31: "COM23" may really be "COM2"; here /dev/pts/N + "7" falls back to /dev/pts/N
    w = new_usbserial()
    configure(w, pty.path + "7")
    w.Open()
    assert w.IsOpen
    w.Close(True)


def test_two_digit_port_name_retry_failure_rethrows_original_error():
    w = new_usbserial()
    configure(w, "/dev/lasergrbl-missing-42")
    with pytest.raises(System.IO.IOException):
        w.Open()
    assert not w.IsOpen


def test_missing_port_with_single_digit_fails_silently():
    w = new_usbserial()
    configure(w, "/dev/lasergrbl-missing-x")
    w.Open()  # the IOException is swallowed; the port simply stays closed
    assert not w.IsOpen


def test_marlin_and_hard_reset_settings_raise_dtr_rts(pty):
    Settings.SetObject("Firmware Type", Firmware.Marlin)
    Settings.SetObject("HardReset Grbl On Connect", True)
    Settings.SetObject("Reset Grbl On Connect", True)
    w = new_usbserial()
    configure(w, pty.path)
    w.Open()
    com = cu.get(w.__implementation__, "com")
    assert com.DtrEnable and com.RtsEnable
    assert cu.call(w.__implementation__, "GetResetDiagnosticString") == "DTR, RTS, Ctrl-X"
    w.Close(True)


def test_reset_diagnostics_empty_by_default(pty):
    w = new_usbserial()
    configure(w, pty.path)
    w.Open()
    assert cu.call(w.__implementation__, "GetResetDiagnosticString") == ""
    w.Close(True)

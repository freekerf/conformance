"""The built-in Grbl v1.1 emulator (GrblEmulator/Grblv11Emulator.cs) and its
IComWrapper (ComWrapper/Emulator.cs), driven by a real GrblCore with live threads.

EmulatorUI.ShowUI would open a window; an uninitialized EmulatorUI instance is
stored in its singleton field so ShowUI() returns immediately (see SCOPE.md).
"""

import os

import pytest

import System
from System.Runtime.Serialization import FormatterServices
from LaserGRBL import GrblCommand, GrblConfST, GrblCore
from LaserGRBL.ComWrapper import WrapperType
from LaserGRBL.GrblEmulator import EmulatorUI, Grblv11Emulator
from LaserGRBLTests import EmulatorProbe, EmulatorSink

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus
from lasergrbl_harness.waiting import wait_until

P = GrblConfST.GrblConfParam


@pytest.fixture(autouse=True)
def headless_emulator_ui():
    cu.sset(EmulatorUI, "istance", FormatterServices.GetUninitializedObject(cu.clr_type(EmulatorUI)))
    path = str(cu.sget(Grblv11Emulator, "filename"))
    if os.path.exists(path):
        os.remove(path)  # start from the emulator's default configuration
    EmulatorProbe.Attach()
    EmulatorProbe.Clear()
    EmulatorProbe.Throw = False
    yield
    EmulatorProbe.Throw = False


@pytest.fixture
def emu(rigs):
    rig = rigs()
    rig.core.Configure(WrapperType.Emulator)
    return rig


def wrapper(rig):
    return cu.get(rig.core, "com")


def emulator(rig):
    return cu.get(wrapper(rig), "emu")


def connect(rig):
    rig.core.OpenCom()
    wait_until(lambda: rig.core.MachineStatus == MacStatus.Idle, 10)
    wait_until(lambda: GrblCore.Configuration.Count == 34 and rig.core.BufferSize == 1024 and rig.config_idle(), 10,
               message="config/info refresh did not complete")
    # while the emulator still had $I queued a status report may have said "Run";
    # wait for the next report (WriteConfig is silently skipped unless Idle/Alarm)
    wait_until(lambda: rig.core.MachineStatus == MacStatus.Idle, 10)


def run(rig, line, until, timeout=10):
    rig.core.EnqueueCommand(GrblCommand(line, 0, True))
    wait_until(until, timeout, message=f"after {line!r}")


def test_emulator_connects_reports_version_config_and_buffer(emu):
    connect(emu)
    assert str(emu.core.GrblVersion) == "1.1#"
    assert emu.core.GrblVersion.VendorName == "Emulator"
    assert float(str(GrblCore.Configuration.MaxRateX)) == 500
    assert emu.core.BufferSize == 1024  # from [OPT:V,15,1024] of $I
    assert "Client connected!" in EmulatorProbe.Snapshot()
    assert wrapper(emu).IsOpen


def test_emulator_moves_and_reports_position_and_offset(emu):
    connect(emu)
    run(emu, "G0 X1 Y2", lambda: emu.core.MachinePosition.X == 1)
    assert emu.core.MachinePosition.Y == 2
    run(emu, "G92 X0 Y0", lambda: emu.core.WorkingOffset.X == 1)
    assert emu.core.WorkPosition.X == 0
    run(emu, "G1 X1.1 F6000", lambda: round(emu.core.MachinePosition.X, 3) == 2.1)


def test_emulator_check_mode_does_not_move(emu):
    connect(emu)
    run(emu, "$C", lambda: emu.core.MachineStatus == MacStatus.Check)
    run(emu, "G0 X5", lambda: emu.core.Executed > 0 and emu.pending.Count == 0 and emu.queue.Count == 0)
    emu.core.EnqueueCommand(GrblCommand("?"))  # nudges a status report
    wait_until(lambda: any("[Enabled]" in t for t in emu.sent_texts()), 5)
    assert emu.core.MachinePosition.X == 0
    run(emu, "$C", lambda: any("[Disabled]" in t for t in emu.sent_texts()))


def test_emulator_jog(emu):
    connect(emu)
    run(emu, "$J=G91X1F6000", lambda: emu.core.MachinePosition.X == 1)


def test_emulator_homing(emu):
    connect(emu)
    run(emu, "G0 X1", lambda: emu.core.MachinePosition.X == 1)
    run(emu, "$H", lambda: emu.core.MachinePosition.X == 0, timeout=15)


def test_emulator_write_config_ok_and_unknown_key_error(emu):
    connect(emu)
    lst = System.Collections.Generic.List[P]()
    lst.Add(P(110, "1000"))
    lst.Add(P(999, "1"))
    with pytest.raises(GrblCore.WriteConfigException) as exc:
        emu.core.WriteConfig(lst)
    assert "$999=1" in str(exc.value.Message) and exc.value.Errors.Count == 1
    assert float(str(GrblCore.Configuration.MaxRateX)) == 1000  # the good write was applied


def test_emulator_write_config_success(emu):
    connect(emu)
    lst = System.Collections.Generic.List[P]()
    lst.Add(P(111, "700"))
    emu.core.WriteConfig(lst)
    assert float(str(GrblCore.Configuration.MaxRateY)) == 700


def test_emulator_hold_and_resume(emu):
    connect(emu)
    emu.core.SendImmediate(33, False)
    wait_until(lambda: emu.core.MachineStatus == MacStatus.AutoHold, 5)
    emu.core.SendImmediate(126, False)
    wait_until(lambda: emu.core.MachineStatus == MacStatus.Idle, 5)


def test_emulator_reset_resends_welcome(emu):
    connect(emu)
    emu.core.GrblReset()  # clears the sent log, then the emulator greets again
    wait_until(lambda: "Grbl Reset" in EmulatorProbe.Snapshot(), 5)
    wait_until(lambda: emu.sent_texts() == ["Grbl 1.1# ['$' for help]"], 5)


def test_emulator_ignores_firmware_probes_and_newline(emu):
    connect(emu)
    w = wrapper(emu)
    w.Write("version\n")
    w.Write("{fb:n}\n")
    w.Write(System.Array[System.Byte]([10]))  # a lone newline is a (empty) command
    wait_until(lambda: emu.com.HostLinesPending == 0, 1)
    assert w.IsOpen


def test_emulator_log_handler_exception_is_swallowed(emu):
    EmulatorProbe.Throw = True
    connect(emu)
    run(emu, "G0 X1", lambda: emu.core.MachinePosition.X == 1)


def test_emulator_command_exception_drops_the_reply(emu):
    connect(emu)
    cu.set(emulator(emu), "conf", None)  # G0 timing needs the config -> exception
    emu.core.EnqueueCommand(GrblCommand("G0 X3"))
    wait_until(lambda: "G0X3" in EmulatorProbe.Snapshot() or emu.pending.Count == 1, 5)
    assert emu.core.MachinePosition.X == 0


def test_emulator_configuration_is_persisted_on_close(emu, rigs):
    connect(emu)
    lst = System.Collections.Generic.List[P]()
    lst.Add(P(130, "123"))
    emu.core.WriteConfig(lst)
    emu.core.CloseCom(True)
    assert os.path.exists(str(cu.sget(Grblv11Emulator, "filename")))
    assert "Connection lost!" in EmulatorProbe.Snapshot()
    sink = EmulatorSink()
    again = Grblv11Emulator(sink.Delegate)  # loads the saved configuration
    conf = cu.get(again, "conf")
    assert {kv.Key: kv.Value for kv in conf}[130] == "123"


def test_emulator_direct_api_with_sink():
    sink = EmulatorSink()
    e = Grblv11Emulator(sink.Delegate)
    e.CloseCom()  # not open: no-op
    e.OpenCom()
    e.OpenCom()  # already open: no-op
    assert list(sink.Snapshot()) == ["Grbl 1.1# ['$' for help]\n"]
    e.ManageMessage(System.Array[System.Byte]([63]))
    wait_until(lambda: len(sink.Snapshot()) == 2, 2)
    # the status format string already ends with \n and ImmediateTX appends another
    assert sink.Snapshot()[1] == "<Idle|MPos:0.000,0.000,0.000>\n\n"
    e.ManageMessage(System.Array[System.Byte](list(b"$I\n")))
    wait_until(lambda: len(sink.Snapshot()) == 5, 2)
    assert list(sink.Snapshot())[2:] == ["ok\n", "[VER:1.1#.20220607:]\n", "[OPT:V,15,1024]\n"]
    e.ManageMessage(System.Array[System.Byte]([0x41]))  # single unknown byte: ignored
    e.CloseCom()


def test_emulator_wrapper_reads_and_close_states(emu):
    w = wrapper(emu)
    w.Configure(None)
    assert not w.IsOpen and not w.HasData()
    assert w.ReadLineBlocking() is None  # closed: returns immediately
    w.Open()
    w.Open()  # already open
    # Open() lets the emulator send its banner and then clears the receive buffer,
    # so the banner is lost; the core only sees the one sent after its ctrl-x
    assert not w.HasData()
    cu.set(w, "closing", True)
    with pytest.raises(System.IO.EndOfStreamException):
        w.ReadLineBlocking()
    cu.set(w, "closing", False)
    w.Write(System.Byte(63))
    wait_until(lambda: w.HasData(), 2)
    assert w.ReadLineBlocking().startswith("<Idle|")
    w.Close(False)
    w.Close(True)  # already closed
    assert not w.IsOpen


def test_emulator_pause_blocks_queue_and_send_errors_are_swallowed():
    sink = EmulatorSink()
    e = Grblv11Emulator(sink.Delegate)
    e.OpenCom()
    e.ManageMessage(System.Array[System.Byte]([33]))  # '!' -> paused
    e.ManageMessage(System.Array[System.Byte](list(b"G0 X1\n")))
    assert stays_paused(sink)
    e.ManageMessage(System.Array[System.Byte]([126]))  # '~' -> resume
    wait_until(lambda: sink.Snapshot().count("ok\n") == 1, 5)
    sink.Throw = True  # the TX thread's send now fails: caught and dropped
    e.ManageMessage(System.Array[System.Byte](list(b"G0 X2\n")))
    wait_until(lambda: sink.Thrown >= 1, 5)
    sink.Throw = False
    e.ManageMessage(System.Array[System.Byte](list(b"G1 X5 F6000\n")))
    e.ManageMessage(System.Array[System.Byte](list(b"G1 X6 F6000\n")))  # queued behind the move
    wait_until(lambda: sink.Snapshot().count("ok\n") == 3, 5)
    e.CloseCom()


def stays_paused(sink):
    from lasergrbl_harness.waiting import stays_true

    return stays_true(lambda: "ok\n" not in sink.Snapshot(), 0.2)


def test_emulator_without_log_subscribers(emu):
    EmulatorProbe.Detach()
    try:
        sink = EmulatorSink()
        e = Grblv11Emulator(sink.Delegate)
        e.OpenCom()
        e.CloseCom()
    finally:
        EmulatorProbe.Attach()


def test_emulator_wrapper_close_by_core(emu):
    w = wrapper(emu)
    w.Open()
    w.Close(True)
    assert not w.IsOpen

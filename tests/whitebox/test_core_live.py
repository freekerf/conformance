"""GrblCore with its real TX/RX threads against the fake device (in-memory link):
connection handshake, configuration/info refresh, config and Wi-Fi writes, and
the RX error paths."""

import pytest

import System
from LaserGRBL import GrblCommand, GrblConfST, GrblCore, Settings

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, get_setting
from lasergrbl_harness.fake_grbl import FakeGrbl

V = GrblCore.GrblVersionInfo
P = GrblConfST.GrblConfParam
RC = GrblCore.RefreshCause


def params(*kv):
    lst = System.Collections.Generic.List[P]()
    for k, v in kv:
        lst.Add(P(k, v))
    return lst


# ---------------------------------------------------------------- connection
def test_connect_handshake_reset_query_then_config_and_info(rig):
    rig.connect()
    assert rig.device.realtime[:2] == [0x18, 0x3F]
    assert rig.device.lines[:2] == ["$$", "$I"]
    conf = GrblCore.Configuration
    assert conf.Count == len(rig.device.settings) and float(str(conf.MaxRateX)) == 6000
    assert rig.core.BufferSize == 128  # [OPT:V,15,128] -> forced enlarge
    assert "status:Connecting" in rig.events and "status:Idle" in rig.events
    assert rig.core.FailedConnectionCount == 0


def test_connect_without_machine_info_query(rig):
    Settings.SetObject("Query MachineInfo ($I) at connect", False)
    rig.connect()
    rig.run_for(0.2)
    assert "$I" not in rig.device.lines
    assert rig.core.BufferSize == 128  # learnt from the Bf: field of the status report instead


def test_reconnect_with_port_already_open(rig):
    rig.com.ForceOpen(True)
    rig.connect()
    assert rig.com.OpenCount == 0  # Open() not called again


def test_partial_config_is_accepted(rigs):
    dev = FakeGrbl(settings={0: "10", 110: "500"})
    rig = rigs(device=dev)
    rig.connect()
    assert GrblCore.Configuration.Count == 2


def test_config_refresh_rejected_by_device_keeps_old_config(rigs):
    dev = FakeGrbl(error_rules=[(r"^\$\$$", 9)])
    rig = rigs(device=dev)
    rig.connect()
    assert GrblCore.Configuration.Count == 0


def test_machine_info_rejected_or_malformed(rigs):
    dev = FakeGrbl(error_rules=[(r"^\$I$", 3)], report_buffer=False)
    rig = rigs(device=dev)
    rig.connect()
    assert rig.core.BufferSize == 127
    dev2 = FakeGrbl(opt_line="[OPT:V,abc,xyz]", ver_line="[VER:1.1f:]", report_buffer=False)
    rig2 = rigs(device=dev2)
    rig2.connect()
    assert rig2.core.BufferSize == 127


def test_machine_info_with_small_rx_buffer_keeps_default(rigs):
    rig = rigs(device=FakeGrbl(opt_line="[OPT:V,15]", report_buffer=False))
    rig.connect()
    assert rig.core.BufferSize == 127


@pytest.mark.timeout(40)
def test_refresh_config_times_out_after_10s_without_answer(rig):
    rig.connect()
    # RefreshConfig blocks the calling (main) thread, so the in-memory device is not
    # pumped and the $$ is never answered
    with pytest.raises(System.TimeoutException):
        rig.core.RefreshConfig(RC.OnDialog)
    assert System.Object.ReferenceEquals(rig.queue, cu.get(rig.core, "mQueue"))  # pointers restored
    # ...but the unanswered $$ stays in the pending queue with its bytes counted, so
    # the next "ok" will be matched to it (FINDINGS.md F-28)
    assert rig.pending.Count == 1 and rig.pending.Peek().Command == "$$"
    assert rig.core.UsedBuffer == 3


@pytest.mark.timeout(40)
def test_refresh_machine_info_times_out_after_10s_without_answer(rig):
    rig.connect()
    with pytest.raises(System.TimeoutException):
        rig.core.RefreshMachineInfo()
    assert rig.pending.Count == 1 and rig.pending.Peek().Command == "$I"


def test_refresh_config_on_demand_and_disabled_info_query(prig):
    rig = prig
    rig.connect()
    rig.device.settings[110] = "1234"
    rig.core.RefreshConfig(RC.OnDialog)
    assert float(str(GrblCore.Configuration.MaxRateX)) == 1234
    Settings.SetObject("Query MachineInfo ($I) at connect", False)
    rig.core.RefreshMachineInfo()  # disabled: returns immediately
    assert rig.device.lines.count("$I") == 1


# ---------------------------------------------------------------- writes
# WriteConfig/WriteWiFiConfig busy-wait on the calling thread: PTY link required
@pytest.fixture
def prig(rigs):
    return rigs(link="pty")


def test_write_config_success_and_failure(prig):
    rig = prig
    rig.connect()
    rig.core.WriteConfig(params((110, "700")))
    assert rig.device.settings[110] == "700"
    with pytest.raises(GrblCore.WriteConfigException) as exc:
        rig.core.WriteConfig(params((111, "800"), (555, "1")))
    assert exc.value.Errors.Count == 1
    assert str(exc.value.Message).startswith("$555=1 ")
    assert rig.device.settings[111] == "800"


def test_write_wifi_config_ortur_uses_settings_74_75(prig):
    rig = prig
    rig.connect()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f", "Ortur Laser Master 3", "182", False))
    cu.call(rig.core, "WriteWiFiConfig", "net", "secret")
    rig.wait(lambda: "$WRS" in rig.device.lines)
    assert rig.device.lines[-3:] == ["$74=net", "$75=secret", "$WRS"]
    assert rig.core.DetectedIP is None


def test_write_wifi_config_longer_uses_radio_commands(prig):
    rig = prig
    rig.connect()
    rig.device.error_rules = [(r"^G0X9$", 20)]
    rig.core.EnqueueCommand(GrblCommand("G0 X9"))  # a failed command already in the log
    rig.wait(lambda: rig.pending.Count == 0 and rig.queue.Count == 0)
    rig.device.error_rules = []
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f", "Longer Nano", None, False))
    cu.call(rig.core, "WriteWiFiConfig", "net", "pw")
    rig.wait(lambda: "$wifi/begin" in rig.device.lines)
    assert rig.device.lines[-4:] == ["$radio/mode=sta", "$sta/ssid=net", "$sta/password=pw", "$wifi/begin"]


def test_write_wifi_config_other_vendor_does_nothing(prig):
    rig = prig
    rig.connect()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    cu.call(rig.core, "WriteWiFiConfig", "n", "p")
    rig.run_for(0.1)
    assert not any(ln.startswith("$74") or ln.startswith("$sta") for ln in rig.device.lines)


def test_write_wifi_config_ortur_requires_idle(rigs):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f", "Ortur Laser Master 3", None, False))
    cu.call(rig.core, "WriteWiFiConfig", "n", "p")  # disconnected: skipped
    assert rig.queue.Count == 0


def test_write_wifi_config_without_known_version_throws(rigs):
    rig = rigs()
    with pytest.raises(System.NullReferenceException):
        cu.call(rig.core, "WriteWiFiConfig", "n", "p")


# ---------------------------------------------------------------- hotkey-style connect/disconnect
def test_hotkey_connect_disconnect(rig):
    cu.call(rig.core, "HKConnectDisconnect")
    rig.wait(lambda: rig.core.IsConnected)
    rig.wait_config_refresh()
    cu.call(rig.core, "HKConnect")  # already connected: no-op
    cu.call(rig.core, "HKConnectDisconnect")
    assert rig.core.MachineStatus == MacStatus.Disconnected
    cu.call(rig.core, "HKDisconnect")  # already disconnected: no-op


def test_hotkey_manager_glue(rig):
    from LaserGRBL import HotKeysManager
    import System.Windows.Forms as WF

    rig.core.SuspendHK = True
    assert not cu.call(rig.core, "ManageHotKeys", None, WF.Keys.F5)
    rig.core.SuspendHK = False
    assert isinstance(cu.call(rig.core, "GetHotKeyString", HotKeysManager.HotKey.Actions.Reset), str)
    lst = System.Collections.Generic.List[HotKeysManager.HotKey]()
    cu.call(rig.core, "WriteHotkeys", lst)
    assert rig.core.HotKeys.Count == 0


def test_translate_enum_and_paths():
    import os

    assert GrblCore.TranslateEnum(MacStatus.Idle) == "Idle"  # no translation resource: name
    assert os.path.isdir(str(GrblCore.TempPath)) and os.path.isdir(str(GrblCore.DataPath))


def test_translate_enum_error_falls_back_to_name():
    with pytest.raises(Exception):
        GrblCore.TranslateEnum(None)  # value.ToString() in the catch throws again


# ---------------------------------------------------------------- RX error paths (stepped)
@pytest.fixture
def stepped(rigs):
    rig = rigs()
    rig.open_stepped(MacStatus.Idle)
    return rig


def wait_line(rig):
    return cu.call(rig.core, "WaitComLineOrDisconnect")


def test_rx_reads_trim_and_skip_empty_lines(stepped):
    stepped.com.FeedHost("  \r\n  ok  \r\n")
    assert wait_line(stepped) == "ok"


def test_rx_io_error_is_retried(stepped):
    stepped.com.ReadError = System.IO.IOException("glitch")
    stepped.com.FeedHost("ok\n")
    assert wait_line(stepped) == "ok"
    assert cu.get(stepped.core, "FixCH340_exception") == 1


def test_rx_repeated_io_errors_enable_ch340_mode(stepped):
    cu.set(stepped.core, "FixCH340_exception", System.UInt32(9))
    stepped.com.ReadError = System.IO.IOException("glitch")
    stepped.com.FeedHost("ok\n")
    assert wait_line(stepped) == "ok"
    assert cu.get(stepped.core, "FixCH340")
    # in CH340 mode the reader returns at once when nothing is waiting
    assert wait_line(stepped) is None


def test_rx_other_error_closes_the_port(stepped):
    stepped.com.ReadError = System.InvalidOperationException("dead")
    assert wait_line(stepped) is None
    assert stepped.core.MachineStatus == MacStatus.Disconnected


def test_rx_has_data_error_closes_the_port(stepped):
    stepped.com.HasDataError = System.InvalidOperationException("dead")
    assert not cu.call(stepped.core, "HasIncomingData")
    assert stepped.core.MachineStatus == MacStatus.Disconnected


def test_rx_loop_iteration_parses_one_line(stepped):
    stepped.core.EnqueueCommand(GrblCommand("G0 X1"))
    stepped.send_line()
    stepped.com.FeedHost("ok\n")
    cu.call(stepped.core, "ThreadRX")
    assert stepped.pending.Count == 0


def test_rx_loop_null_line_and_errors(stepped):
    stepped.com.ReturnNullOnce = True
    stepped.com.ForceOpen(False)
    cu.call(stepped.core, "ThreadRX")  # closed port: nothing read
    cu.set(stepped.core, "RX", None)
    stepped.com.ForceOpen(True)
    stepped.com.FeedHost("ok\n")
    cu.call(stepped.core, "ThreadRX")  # NRE on RX.SleepTime: logged


def test_tx_loop_skips_work_when_thread_must_exit(stepped):
    stepped.core.EnqueueCommand(GrblCommand("G0 X1"))
    tx = cu.get(stepped.core, "TX")
    cu.set(tx, "MustExit", System.Threading.ManualResetEvent(True))
    stepped.step_tx()
    cu.set(tx, "MustExit", None)
    assert stepped.queue.Count == 1

from LaserGRBL import GrblCommand, GrblCore


def test_runtime_loads_core_assembly():
    cmd = GrblCommand("g1 x1")
    assert cmd.Command == "G1 X1"


def test_rig_connects_live_to_fake_device(rig):
    rig.connect()
    assert rig.core.MachineStatus == GrblCore.MacStatus.Idle
    assert str(rig.core.GrblVersion) == "1.1f"
    assert rig.device.realtime[0] == 0x18  # reset on connect

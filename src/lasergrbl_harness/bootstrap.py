"""One place that starts the C# runtime for any test layer that needs it."""

from __future__ import annotations

from . import runtime


def _seed(data):
    # Pre-existing settings file written by an "old" LaserGRBL (4.4.0) that used the
    # Insane threading mode: exercises Settings' load-from-disk path and GrblCore's
    # 4.5.0 threading-mode migration (see COVERAGE.md).
    import System
    from LaserGRBL import GrblCore

    data["Current LaserGRBL Version"] = System.Version(4, 4, 0)
    data["Threading Mode"] = GrblCore.ThreadingMode.Insane


def load_csharp() -> None:
    runtime.load(settings_seed=_seed)


def reset_csharp_state() -> None:
    """Per-test reset of the core's static state (Settings dictionary, jog target)."""
    from LaserGRBL import GrblCore

    from . import clr_util as cu
    from .core_rig import reset_settings

    reset_settings(**{
        "Threading Mode": GrblCore.ThreadingMode.Insane,
        "DisableSafetyCountdown": True,  # SafetyCountdown.CanGo() would open a dialog
    })
    cu.sset(GrblCore.ContinuousJog, "mPrev", None)
    cu.sset(GrblCore.ContinuousJog, "mCurr", None)


def restore_csv() -> None:
    from LaserGRBL import CSVD
    from LaserGRBL.CSV import CsvDictionary

    CSVD.Settings = CsvDictionary("LaserGRBL.CSV.setting_codes.v1.1.csv", 3)
    CSVD.Alarms = CsvDictionary("LaserGRBL.CSV.alarm_codes.csv", 2)
    CSVD.Errors = CsvDictionary("LaserGRBL.CSV.error_codes.csv", 2)

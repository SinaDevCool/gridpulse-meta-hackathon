import pytest

from capacity_backtest.phase2.thermal_workload import ThermalEnvelope, replay_temperature_envelope


def test_thermal_energy_balance_and_repeated_event_state_carryover():
    config = ThermalEnvelope(1, 0, 2, 18, 25, "air")
    args = {"it_heat_mw": (4,), "cooling_electric_mw": (0,), "ambient_temperature_c": (20,), "interval_minutes": 60}
    first, violations = replay_temperature_envelope(config, initial_temperature_c=20, **args)
    assert first == (20, 24) and not violations
    second, violations = replay_temperature_envelope(config, initial_temperature_c=first[-1], **args)
    assert second[-1] == 28 and violations == (1,)


def test_exact_rc_replay_is_resolution_consistent_for_constant_inputs():
    config = ThermalEnvelope(.1, .2, 3, -100, 100, "direct_to_chip")
    def run(count, interval):
        return replay_temperature_envelope(config, initial_temperature_c=22, it_heat_mw=(3,) * count,
            cooling_electric_mw=(1,) * count, ambient_temperature_c=(20,) * count, interval_minutes=interval)[0][-1]
    assert run(1, 60) == pytest.approx(run(4, 15))


def test_thermal_replay_never_silently_accepts_missing_or_nonfinite_inputs():
    config = ThermalEnvelope(1, 0, 2, 18, 25, "air")
    with pytest.raises(ValueError):
        replay_temperature_envelope(config, initial_temperature_c=20, it_heat_mw=(float("nan"),),
            cooling_electric_mw=(1,), ambient_temperature_c=(20,), interval_minutes=15)

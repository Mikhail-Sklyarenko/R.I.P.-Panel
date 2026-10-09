import pytest

@pytest.fixture
def modules(csgobot_module_path):
    from nav import map_confirmation
    from map.hud_map_detect import MapDetectState, update_map_hysteresis, unlock_map_detect, MatchReadyLatch
    return map_confirmation, MapDetectState, update_map_hysteresis, unlock_map_detect, MatchReadyLatch


def test_live_scenery_without_name_cannot_trigger_transition(modules):
    gate, State, update, unlock, Latch = modules
    state = State(confirmed_script='mirage', locked=True)
    latch = Latch(confirm_frames=20)
    for _ in range(60):
        assert not latch.update(gate.named_match_ready(None, None))
        assert gate.active_map_confirmed('de_mirage', state)


def test_same_map_reconfirmation_restores_gate_without_changed_event(modules):
    gate, State, update, unlock, Latch = modules
    state = State(confirmed_script='mirage', locked=True)
    unlock(state)
    assert not gate.active_map_confirmed('de_mirage', state)
    changed, pending = update(state, 'mirage', confirm_frames=3, lock_after_confirm=True)
    assert changed is None  # Exact failure case in the supplied live log.
    assert gate.active_map_confirmed('de_mirage', state)
    assert not gate.active_map_confirmed('de_dust2', state)


def test_real_different_map_requires_confirmation_and_matching_profile(modules):
    gate, State, update, unlock, Latch = modules
    state = State(confirmed_script='dust2', locked=True)
    unlock(state)
    for _ in range(2):
        changed, _ = update(state, 'mirage', confirm_frames=3, lock_after_confirm=True)
        assert changed is None
        assert not gate.active_map_confirmed('de_mirage', state)
    changed, _ = update(state, 'mirage', confirm_frames=3, lock_after_confirm=True)
    assert changed == 'mirage'
    assert not gate.active_map_confirmed('de_dust2', state)
    assert gate.active_map_confirmed('de_mirage', state)


@pytest.mark.parametrize('fp16, defaults, expected', [
    (True, {'quantize':None}, {'quantize':16}),
    (False, {'quantize':None}, {'quantize':None}),
    (True, {'half':False}, {'half':True}),
    (False, {'half':False}, {'half':False}),
])
def test_precision_compatibility(modules, fp16, defaults, expected):
    from detectors.precision import inference_precision
    assert inference_precision(fp16, defaults) == expected

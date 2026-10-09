from aiming.combat_contact import CombatContact


def test_one_missed_detection_keeps_contact_but_expires_quickly():
    c = CombatContact()
    assert c.update(detected=True, active=True, now=10)
    assert c.update(detected=False, active=True, now=10.05)
    assert c.update(detected=True, active=True, now=10.08)
    assert c.acquired_at == 10
    assert not c.update(detected=False, active=True, now=10.19)
    assert c.acquired_at is None


def test_deactivation_clears_contact_immediately():
    c = CombatContact()
    c.update(detected=True, active=True, now=10)
    assert not c.update(detected=True, active=False, now=10.01)
    assert c.last_seen is None


def test_new_contact_gets_new_latency_origin():
    c = CombatContact()
    c.update(detected=True, active=True, now=10)
    c.shot_reported = True
    c.update(detected=True, active=True, now=11)
    assert c.acquired_at == 11
    assert not c.shot_reported


def test_fire_uses_measured_target_not_centered_smoothed_point():
    from types import SimpleNamespace
    from aiming.combat_aim import observed_fire_distance
    from aiming.fire_controller import FireConfig, FireController
    distance = observed_fire_distance(SimpleNamespace(aim_x=720, aim_y=360),
        center_x=640, center_y=360, captured_at=10, now=10.05)
    action = FireController(FireConfig()).tick(
        pixel_distance=distance, confidence=.9, is_head=False, now=10.05)
    assert not action.press


def test_fire_can_start_after_accepted_mouse_correction():
    from types import SimpleNamespace
    from aiming.combat_aim import observed_fire_distance
    from aiming.fire_controller import FireConfig, FireController
    distance = observed_fire_distance(SimpleNamespace(aim_x=720, aim_y=360),
        center_x=640, center_y=360, captured_at=10, now=10.05,
        project=lambda x,y,t: (645,360))
    action = FireController(FireConfig()).tick(
        pixel_distance=distance, confidence=.9, is_head=False, now=10.05)
    assert action.press


def test_stale_or_future_detection_never_authorizes_fire():
    from types import SimpleNamespace
    from aiming.combat_aim import observed_fire_distance
    for stamp in [9.7, 10.1]:
        assert observed_fire_distance(SimpleNamespace(aim_x=640, aim_y=360),
            center_x=640, center_y=360, captured_at=stamp, now=10) == float('inf')

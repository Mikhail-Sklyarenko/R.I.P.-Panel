import importlib
import math

import pytest


@pytest.fixture
def servo_type(csgobot_module_path):
    return importlib.import_module("nav.camera_servo").CameraServo


def test_delayed_10hz_observations_produce_small_120hz_steps(servo_type):
    clock, yaw, deltas = [1.], [0.], []
    def move(dx, dy):
        assert dy == 0
        yaw[0] += dx / 10
        deltas.append((clock[0], dx/10))
    servo = servo_type(move, 3600, clock=lambda: clock[0])
    observations = []
    for tick in range(720):
        clock[0] = 1 + tick/120
        observations.append((clock[0], yaw[0]))
        if tick % 12 == 0 and tick >= 6:
            stamp, observed_yaw = observations[tick-6]  # 50 ms capture latency
            error = (180-observed_yaw+180) % 360-180
            servo.submit(error, stamp, limit=100)
        servo.advance()
    assert abs(abs(yaw[0])-180) < 2
    assert len(deltas) > 150
    assert max(abs(delta) for _, delta in deltas) <= 1
    assert all(delta < 0 for _, delta in deltas)  # No seam reversals.
    servo.close()


def test_capture_stall_expires_camera_and_resume_does_not_catch_up(servo_type):
    now, output = [1.], []
    servo = servo_type(lambda x, y: output.append(x), 3600, clock=lambda: now[0])
    servo.submit(90, 1.)
    for i in range(1, 24):
        now[0] = 1+i/120
        servo.advance()
    assert output
    count = len(output)
    now[0] = 2.
    servo.advance()
    assert len(output) == count
    servo.submit(90, 2.)
    now[0] = 2.5  # New scheduler stall still cannot emit stale input.
    servo.advance()
    assert len(output) == count
    servo.submit(90, 2.5)
    for _ in range(3):
        now[0] += 1/120
        servo.advance()
    assert output[count:] and max(abs(dx) for dx in output[count:]) < 2
    servo.stop()
    count = len(output)
    now[0] += 1/120
    servo.advance()
    assert len(output) == count


def test_invalid_command_cancels_servo(servo_type):
    now, output = [1.], []
    servo = servo_type(lambda x, y: output.append(x), 3600, clock=lambda: now[0])
    servo.submit(90, 1.)
    servo.submit(math.nan, 1.)
    now[0] += .01
    servo.advance()
    assert not output


def test_focus_guard_stops_camera_and_keys_without_perception_tick(servo_type):
    from nav.input_lease import KeyLease
    clock, allowed, output, keys = [1.], [True], [], set()
    servo = servo_type(lambda x, y: output.append(x), 3600,
                       clock=lambda: clock[0], allowed=lambda: allowed[0])
    lease = KeyLease(keys.add, keys.discard, clock=lambda: clock[0], allowed=lambda: allowed[0])
    servo.submit(90, 1.)
    lease.renew(.25)
    lease.set_keys({'w'})
    allowed[0] = False
    clock[0] = 1.02
    servo.advance()
    lease.expire()
    assert not output and not keys
    allowed[0] = True
    clock[0] = 1.04
    servo.advance()
    lease.set_keys({'w'})
    assert not output and not keys

"""Exercise real controller transactions against a timestamped fake I2C bus."""
import contextlib
import io
import runpy
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

import gamepad_arm_control as control


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.events = []
        self.positions = {j: 2000 for j in range(1, 7)}
        self.zero = False
        self.write_error = False
        self.center = ({a: 128 for a in control.AXES}, False, False, False, False)
        self.held = (self.center[0] | {0: 255}, False, False, False, False)
        self.bus = SimpleNamespace(write_byte_data=self.request, read_word_data=self.read,
                                   write_i2c_block_data=self.write, close=Mock())
        self.device = SimpleNamespace(bus=self.bus, addr=0x15)
        self.arm = control.PacedArm(self.device)
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(control.time, 'monotonic', side_effect=lambda: self.now))
        stack.enter_context(patch.object(control.time, 'sleep', side_effect=self.sleep))
        stack.enter_context(patch.object(control, 'check_other_controllers'))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def sleep(self, seconds):
        self.now += seconds

    def request(self, addr, reg, value):
        self.events.append((self.now, 'request', reg - 0x30))

    def read(self, addr, reg):
        self.events.append((self.now, 'read', reg - 0x30))
        pos = 0 if self.zero else self.positions[reg - 0x30]
        return (pos >> 8) | ((pos & 255) << 8)

    def write(self, addr, reg, data):
        duration = (data[2] << 8) | data[3]
        self.events.append((self.now, 'write', reg - 0x10, duration))
        if self.write_error:
            raise OSError('I2C failure')
        self.positions[reg - 0x10] = (data[0] << 8) | data[1]

    def test_cross_joint_read_waits_for_motion_completion_and_gap(self):
        self.arm.Arm_serial_servo_write(1, 95, 150)
        control.angle_once(self.arm, 2)
        self.assertAlmostEqual(self.events[1][0], 0.2)
        self.assertEqual(self.events[1][1:], ('request', 2))
        self.assertAlmostEqual(self.events[2][0], 0.25)
        # Writes never wait and then silently act on an old input snapshot.
        with self.assertRaises(control.MotionPaused):
            self.arm.Arm_serial_servo_write(3, 91, 150)
        self.sleep(control.BUS_GAP)
        self.arm.Arm_serial_servo_write(3, 91, 150)

    def test_zero_stops_retry_burst_and_blocks_every_joint(self):
        self.zero = True
        with self.assertRaises(control.MotionPaused):
            control.stable_angle(self.arm, 4)
        self.assertEqual(len(self.events), 2)
        for j in range(1, 7):
            with self.assertRaises(control.MotionPaused):
                control.angle_once(self.arm, j)
            with self.assertRaises(control.MotionPaused):
                self.arm.Arm_serial_servo_write(j, 90, 150)
        self.assertEqual(len(self.events), 2)

    def test_recovery_requires_neutral_and_success_never_writes(self):
        self.zero = True
        with self.assertRaises(control.MotionPaused):
            control.angle_once(self.arm, 1)
        self.zero = False
        self.arm.recover_if_neutral(self.center)
        self.assertEqual(len(self.events), 2)
        self.sleep(5)
        self.arm.recover_if_neutral(self.held)
        self.assertEqual(len(self.events), 2)
        self.arm.recover_if_neutral(self.center)
        self.assertIsNone(self.arm.failed_joint)
        self.assertFalse(any(e[1] == 'write' for e in self.events))
        self.assertEqual(len(self.events), 6)

    def test_failed_recovery_restarts_quiet_window_without_four_reads(self):
        self.zero = True
        with self.assertRaises(control.MotionPaused):
            control.angle_once(self.arm, 1)
        self.sleep(5)
        self.arm.recover_if_neutral(self.center)
        self.assertEqual(len(self.events), 4)
        self.assertAlmostEqual(self.arm.retry_at, self.now + 5)
        self.arm.recover_if_neutral(self.center)
        self.assertEqual(len(self.events), 4)

    def test_write_error_is_not_swallowed_or_retried(self):
        self.write_error = True
        with self.assertRaises(control.MotionPaused):
            control.hold_write(self.arm, 1, 92)
        self.assertEqual(self.arm.failed_joint, 1)
        with self.assertRaises(control.MotionPaused):
            control.hold_write(self.arm, 2, 92)
        self.assertEqual(len(self.events), 1)

    def test_packets_match_bundled_official_driver_for_every_legal_angle(self):
        bus = SimpleNamespace(write_i2c_block_data=Mock())
        source = Path(__file__).resolve().parent / 'robot_arm_dependency/0.py_install/Arm_Lib/Arm_Lib.py'
        with patch.dict(sys.modules, {'smbus': SimpleNamespace(SMBus=lambda number: bus)}):
            official = runpy.run_path(str(source))['Arm_Device']()
        paced = control.PacedArm(official)
        for joint in range(1, 7):
            for angle in range(271 if joint == 5 else 181):
                official.Arm_serial_servo_write(joint, angle, 150)
                expected = bus.write_i2c_block_data.call_args
                self.sleep(0.21)
                paced.Arm_serial_servo_write(joint, angle, 150)
                self.assertEqual(bus.write_i2c_block_data.call_args, expected)

    def test_read_error_and_invalid_position_enter_global_cooldown(self):
        for failure in ('oserror', 'invalid'):
            self.arm = control.PacedArm(self.device)
            self.positions[2] = 65535
            with patch.object(self.bus, 'read_word_data', side_effect=OSError('read failed')) \
                    if failure == 'oserror' else contextlib.nullcontext():
                with self.assertRaises(control.MotionPaused):
                    control.angle_once(self.arm, 2)
            self.assertEqual(self.arm.failed_joint, 2)
            self.assertAlmostEqual(self.arm.retry_at, self.now + 5)

    def test_hold_uses_paced_bus_and_release_during_wait_drops_next_target(self):
        release = 0.52  # Inside the wait for the first 150ms segment to finish.
        control.execute_hold(self.arm, (1, 1), self.held, {1: 90},
                             SimpleNamespace(speed=10, span=90),
                             lambda: self.held if self.now < release else self.center)
        writes = [e for e in self.events if e[1] == 'write']
        self.assertEqual(len(writes), 1)
        self.assertLess(writes[0][0], release)
        for i, event in enumerate(self.events):
            if event[1] == 'write':
                later_reads = [e for e in self.events[i + 1:] if e[1] == 'request']
                if later_reads:
                    self.assertGreaterEqual(later_reads[0][0] + 1e-9, event[0] + 0.2)

    def test_long_rest_keeps_hold_running_without_querying_during_rest(self):
        for rest in (0.4, 1.0):
            self.now = 0
            self.events.clear()
            self.positions[1] = 2000
            arm = control.PacedArm(self.device, motion_rest=rest)
            control.execute_hold(arm, (1, 1), self.held, {1: 90},
                                 SimpleNamespace(speed=10, span=90),
                                 lambda: self.held if self.now < 4 else self.center)
            writes = [e for e in self.events if e[1] == 'write']
            self.assertGreaterEqual(len(writes), 3)
            self.assertTrue(all(e[0] < 4 for e in writes))
            for index, event in enumerate(self.events):
                if event[1] == 'write':
                    following = self.events[index + 1:]
                    if following:
                        self.assertGreaterEqual(following[0][0] + 1e-9, event[0] + 0.15 + rest)

    def test_release_in_long_rest_is_observed_before_rest_ends(self):
        arm = control.PacedArm(self.device, motion_rest=0.4)
        observed_release = []

        def read_state():
            if self.now >= 0.45:
                observed_release.append(self.now)
                return self.center
            return self.held

        control.execute_hold(arm, (1, 1), self.held, {1: 90},
                             SimpleNamespace(speed=10, span=90), read_state)
        writes = [e for e in self.events if e[1] == 'write']
        self.assertEqual(len(writes), 1)
        self.assertLessEqual(observed_release[0], 0.461)
        self.assertLess(observed_release[0], writes[0][0] + 0.55)

    def test_long_rest_does_not_allow_slow_feedback_to_replay_motion(self):
        arm = control.PacedArm(self.device, motion_rest=0.4)
        original_read = self.bus.read_word_data

        def slow_read(*args):
            if self.now > 0.4:
                self.sleep(0.6)
            return original_read(*args)

        self.bus.read_word_data = slow_read
        control.execute_hold(arm, (1, 1), self.held, {1: 90},
                             SimpleNamespace(speed=10, span=90), lambda: self.held)
        self.assertEqual(len([e for e in self.events if e[1] == 'write']), 1)

    def test_rest_option_limits_and_default(self):
        self.assertEqual(control.parse_args(['--mode', 'hold']).hold_rest_ms, 400)
        self.assertEqual(control.parse_args(['--hold-rest-ms', '50']).hold_rest_ms, 50)
        for invalid in ('0', '49', '1001'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                control.parse_args(['--hold-rest-ms', invalid])

    def test_gripper_obstruction_still_locks_direction_with_long_rest(self):
        arm = control.PacedArm(self.device, motion_rest=0.4)
        session = control.MotionSession()
        close = (self.center[0], False, False, False, True)
        original_write = self.bus.write_i2c_block_data

        def blocked_write(*args):
            original_write(*args)
            self.positions[6] = 2000  # Contact keeps the actual angle at 90 degrees.

        self.bus.write_i2c_block_data = blocked_write
        control.execute_hold(arm, (6, 1), close, {6: 90},
                             SimpleNamespace(speed=10, span=90),
                             lambda: close if self.now < 6 else self.center, session)
        self.assertEqual(session.blocked[(6, 1)], 90)
        count = len(self.events)
        with self.assertRaises(control.MotionPaused):
            control.execute_hold(arm, (6, 1), close, {6: 90},
                                 SimpleNamespace(speed=10, span=90), lambda: close, session)
        self.assertEqual(len(self.events), count)

    def test_main_recovery_never_replays_held_input_or_rebases(self):
        args = control.parse_args(['--move', '--mode', 'hold', '--joints', '1'])
        # Actual startup and recovery reads, and a fault triggered on first action.
        states = iter([self.center, self.center, self.held, self.held,
                       self.center, self.held, self.center, self.held])
        baselines = []

        def snapshot(*args):
            self.sleep(1)
            try:
                return next(states)
            except StopIteration:
                raise KeyboardInterrupt()

        def execute(arm, action, state, initial, *args):
            baselines.append(dict(initial))
            if len(baselines) == 1:
                self.positions[1] = 2100  # Recovery must not redefine the baseline.
                arm.fail(1, 'simulated loss')

        # Shorten only the quiet-window duration for this sequence of input events.
        with patch.object(control, 'BUS_COOLDOWN', 1), \
                patch.dict(sys.modules, {'fcntl': SimpleNamespace(flock=Mock(), LOCK_EX=1, LOCK_NB=2),
                                         'Arm_Lib': SimpleNamespace(Arm_Device=lambda: self.device)}), \
                patch('builtins.open', mock_open()), \
                patch.object(control, 'find_pad', return_value='pad'), \
                patch.object(control, 'configure_buttons', return_value=[288, 290]), \
                patch.object(control, 'snapshot', side_effect=snapshot), \
                patch.object(control, 'execute_hold', side_effect=execute), \
                self.assertRaises(KeyboardInterrupt):
            control.run(args)
        self.assertEqual(baselines, [{1: 90}, {1: 90}])
        self.assertFalse(any(e[1] == 'write' for e in self.events))


if __name__ == '__main__':
    unittest.main()

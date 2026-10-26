"""Deterministic hold-mode simulation; no hardware or real sleeps."""
import contextlib
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock, mock_open

import gamepad_arm_control as control


class HoldTests(unittest.TestCase):
    def simulate(self, seconds=1.0, strength=255, speed=10, start=90,
                 span=60, joint=2, direction=1, change=None, feedback=None,
                 track_motion=True, session=None, motion_rate=None, contact=None,
                 stable_failure=None):
        center = {axis: 128 for axis in control.AXES}
        axes = dict(center)
        if joint != 6:
            axes[{1: 0, 2: 1, 3: 2, 4: 1, 5: 5}[joint]] = strength if direction > 0 else 0
        held = (axes, joint == 4, joint == 5, joint == 6 and direction < 0, joint == 6 and direction > 0)
        neutral = (center, False, False, False, False)
        clock = SimpleNamespace(now=0.0, position=start, goal=start)
        writes = []

        def sleep(seconds):
            if motion_rate is not None:
                delta = clock.goal - clock.position
                travel = min(abs(delta), seconds * motion_rate)
                clock.position += travel if delta > 0 else -travel
                if contact is not None:
                    clock.position = min(clock.position, contact)
            clock.now += seconds

        def read_state():
            if change and clock.now >= change[0]:
                if isinstance(change[1], BaseException):
                    raise change[1]
                return change[1]
            return held if clock.now < seconds else neutral

        def read_angle(arm, number):
            sleep(0.02)
            if feedback and clock.now >= feedback[0]:
                if isinstance(feedback[1], BaseException):
                    raise feedback[1]
                clock.now += feedback[1]  # Simulate a blocked feedback read.
            return round(clock.position)

        def write(number, target, duration):
            writes.append((clock.now, number, target, duration))
            clock.goal = target
            if track_motion and motion_rate is None:
                clock.position = target

        def read_stable(*args):
            if stable_failure and clock.now >= stable_failure[0]:
                raise stable_failure[1]
            return round(clock.position)

        arm = SimpleNamespace(Arm_serial_servo_write=write)
        output = io.StringIO()
        error = None
        with patch.object(control.time, 'monotonic', side_effect=lambda: clock.now), \
                patch.object(control.time, 'sleep', side_effect=sleep), \
                patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', side_effect=read_stable), \
                patch.object(control, 'angle_once', side_effect=read_angle), \
                contextlib.redirect_stdout(output):
            try:
                control.execute_hold(arm, (joint, direction), held, {joint: start},
                                     SimpleNamespace(speed=speed, span=span), read_state, session)
            except (RuntimeError, OSError) as exc:
                error = exc
        return writes, clock, error, output.getvalue()

    def test_hold_time_and_stick_strength_control_distance(self):
        short = self.simulate(seconds=0.8)
        long = self.simulate(seconds=1.6)
        light = self.simulate(seconds=1.6, strength=180)
        for result in (short, long, light):
            self.assertIsNone(result[2])
        self.assertGreater(long[1].position, short[1].position)
        self.assertGreater(light[1].position, 90)
        self.assertLess(light[1].position, long[1].position)

    def test_release_never_sends_more_targets_and_segments_are_bounded(self):
        writes, _, error, _ = self.simulate(seconds=0.8, speed=20)
        self.assertIsNone(error)
        previous = 90
        self.assertGreater(len(writes), 0)
        for sent_at, joint, target, duration in writes:
            self.assertLess(sent_at, 0.8)
            self.assertEqual(joint, 2)
            self.assertEqual(duration, 150)
            self.assertLessEqual(abs(target - previous), 4)
            previous = target

    def test_release_during_feedback_and_short_tap_do_not_commit_a_step(self):
        for seconds in (0, 0.05, 0.13):
            writes, _, error, _ = self.simulate(seconds=seconds)
            self.assertEqual(writes, [])
            self.assertIsNone(error)

    def test_disconnect_prevents_further_commands(self):
        writes, _, error, _ = self.simulate(seconds=2, change=(0.4, OSError('unplugged')))
        self.assertIsInstance(error, OSError)
        self.assertTrue(writes)
        self.assertTrue(all(w[0] < 0.4 for w in writes))

    def test_reverse_conflict_and_modifier_change_require_new_gesture(self):
        center = {axis: 128 for axis in control.AXES}
        states = [(center | {1: 0}, False, False, False, False),
                  (center | {1: 255}, True, False, False, False),
                  (center | {1: 255, 0: 255}, False, False, False, False), None]
        for state in states:
            writes, _, error, _ = self.simulate(seconds=2, change=(0.4, state))
            self.assertIsNone(error)
            self.assertTrue(all(w[0] < 0.4 for w in writes))

    def test_boundaries_stop_and_gripper_directions_work(self):
        for joint, start, direction, bound in ((2, 90, 1, 150), (2, 90, -1, 30),
                                               (6, 172, 1, 180), (6, 172, -1, 112),
                                               (5, 268, 1, 270)):
            writes, clock, error, _ = self.simulate(seconds=20, joint=joint, start=start, direction=direction)
            self.assertIsNone(error)
            self.assertEqual(clock.position, bound)
            self.assertTrue(all(min(start, bound) <= w[2] <= max(start, bound) for w in writes))

    def test_missing_feedback_pauses_motion_without_automatic_resume(self):
        writes, _, error, output = self.simulate(seconds=3, feedback=(0.25, control.FeedbackUnavailable()))
        self.assertIsNone(error)
        self.assertIn('停止连续指令', output)
        self.assertTrue(writes)
        self.assertTrue(all(w[0] < 0.25 for w in writes))

    def test_stale_feedback_does_not_create_catchup_jump(self):
        writes, _, error, _ = self.simulate(seconds=3, feedback=(0.25, 1.0))
        self.assertIsNone(error)
        self.assertTrue(all(w[0] < 0.25 for w in writes))

    def test_stalled_servo_stops_small_targets_from_accumulating(self):
        session = control.MotionSession()
        writes, _, error, _ = self.simulate(seconds=3, track_motion=False, session=session)
        self.assertIsNone(error)
        self.assertTrue(all(w[2] <= 94 for w in writes))
        self.assertIn((2, 1), session.blocked)
        self.assertEqual(writes[-1][2], 90)  # Cancel the unachieved farther target.

    def test_slow_moving_servo_is_paced_without_exiting_or_false_obstruction(self):
        session = control.MotionSession()
        writes, clock, error, output = self.simulate(seconds=4, motion_rate=5, session=session)
        self.assertIsNone(error)
        self.assertFalse(session.blocked)
        self.assertGreater(clock.position, 100)
        self.assertLess(clock.position, 130)
        self.assertIn('减速等待', output)
        self.assertTrue(writes)

    def test_gripper_contact_blocks_repeated_close_and_unlocks_only_after_opening(self):
        session = control.MotionSession()
        writes, clock, error, output = self.simulate(seconds=6, joint=6, start=110,
                                                    motion_rate=10, contact=123, session=session)
        self.assertIsNone(error)
        self.assertEqual(clock.position, 123)
        self.assertEqual(session.blocked[(6, 1)], 123)
        self.assertIn('疑似夹紧或受阻', output)
        self.assertLessEqual(max(w[2] for w in writes), 127)
        self.assertEqual(writes[-1][2], 123)
        # Releasing and pressing close again never sends another squeezing target.
        for _ in range(3):
            again = self.simulate(joint=6, start=123, session=session)
            self.assertEqual(again[0], [])
            self.assertIsInstance(again[2], control.MotionPaused)
        other = self.simulate(joint=1, seconds=0.8, session=session)
        self.assertIsNone(other[2])
        self.assertTrue(other[0])
        self.assertIn((6, 1), session.blocked)
        # Merely tapping open is not evidence that the obstruction was cleared.
        self.simulate(joint=6, start=123, direction=-1, seconds=0.05, session=session)
        self.assertIn((6, 1), session.blocked)
        opened = self.simulate(joint=6, start=123, direction=-1, seconds=1,
                               motion_rate=10, session=session)
        self.assertIsNone(opened[2])
        self.assertLessEqual(opened[1].position, 121)
        self.assertNotIn((6, 1), session.blocked)
        self.assertTrue(self.simulate(joint=6, start=round(opened[1].position), session=session)[0])

    def test_persistent_bad_feedback_pauses_without_guessed_motion_or_replay(self):
        failure = RuntimeError('four zero feedback readings')
        writes, _, error, _ = self.simulate(seconds=3, feedback=(0.25, control.FeedbackUnavailable()),
                                            stable_failure=(0.25, failure))
        self.assertIsInstance(error, control.MotionPaused)
        self.assertTrue(all(w[0] < 0.25 for w in writes))
        for fault in (failure, OSError('I2C error')):
            again = self.simulate(stable_failure=(0, fault))
            self.assertEqual(again[0], [])
            self.assertIsInstance(again[2], control.MotionPaused)
        self.assertTrue(self.simulate(seconds=0.8)[0])  # A new valid gesture can work.

    def test_main_loop_stays_alive_after_paused_action_and_accepts_other_joint(self):
        center = {axis: 128 for axis in control.AXES}
        neutral = (center, False, False, False, False)
        close = (center, False, False, False, True)
        base = (center | {0: 255}, False, False, False, False)
        args = control.parse_args(['--move', '--mode', 'hold', '--joints', '1', '6', '--span', '90'])
        arm = SimpleNamespace(addr=0x15, bus=SimpleNamespace(close=Mock()))
        fake_fcntl = SimpleNamespace(flock=Mock(), LOCK_EX=1, LOCK_NB=2)
        with patch.dict(sys.modules, {'fcntl': fake_fcntl, 'Arm_Lib': SimpleNamespace(Arm_Device=lambda: arm)}), \
                patch('builtins.open', mock_open()), patch.object(control, 'find_pad', return_value='pad'), \
                patch.object(control, 'configure_buttons', return_value=[288, 290]), \
                patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', side_effect=[90, 123]), \
                patch.object(control, 'snapshot', side_effect=[neutral, neutral, close, neutral, base, KeyboardInterrupt()]), \
                patch.object(control, 'execute_hold', side_effect=[control.MotionPaused('feedback unavailable'), None]) as execute, \
                patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(KeyboardInterrupt):
            control.run(args)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[0].args[1], (6, 1))
        self.assertEqual(execute.call_args_list[1].args[1], (1, 1))
        self.assertIs(execute.call_args_list[0].args[-1], execute.call_args_list[1].args[-1])
        arm.bus.close.assert_called_once()

    def test_ninety_degree_range_keeps_absolute_servo_limits(self):
        for start, joint, direction, bound in ((90, 2, 1, 180), (90, 2, -1, 0),
                                               (240, 5, 1, 270), (40, 1, 1, 130)):
            writes, clock, error, _ = self.simulate(seconds=30, span=90, start=start,
                                                    joint=joint, direction=direction)
            self.assertIsNone(error)
            self.assertEqual(clock.position, bound)
            maximum = 270 if joint == 5 else 180
            self.assertTrue(all(0 <= w[2] <= maximum and abs(w[2] - start) <= 90 for w in writes))

    def test_initial_angle_waits_for_valid_feedback_and_never_rebases(self):
        arm = SimpleNamespace(Arm_serial_servo_write=Mock())
        initial = {6: 123}
        with patch.object(control, 'stable_angle', side_effect=[RuntimeError('four zero reads'), 40]) as read, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(control.try_initialize_joint(arm, 1, initial))
            self.assertEqual(initial, {6: 123})
            self.assertTrue(control.try_initialize_joint(arm, 1, initial))
            self.assertEqual(initial, {1: 40, 6: 123})
            self.assertTrue(control.try_initialize_joint(arm, 1, initial))
            self.assertEqual(read.call_count, 2)
        arm.Arm_serial_servo_write.assert_not_called()

    def startup_loop(self, states, readings, joints=('1', '6'), timed=False):
        args = control.parse_args(['--move', '--mode', 'hold', '--joints', *joints, '--span', '90'])
        arm = SimpleNamespace(addr=0x15, bus=SimpleNamespace(close=Mock()), Arm_serial_servo_write=Mock())
        clock = SimpleNamespace(now=0)
        state_iterator = iter(states)

        def snapshot(*args):
            if timed:
                clock.now += 1
            state = next(state_iterator)
            if isinstance(state, BaseException):
                raise state
            return state

        fake_fcntl = SimpleNamespace(flock=Mock(), LOCK_EX=1, LOCK_NB=2)
        executed = []
        with patch.dict(sys.modules, {'fcntl': fake_fcntl, 'Arm_Lib': SimpleNamespace(Arm_Device=lambda: arm)}), \
                patch('builtins.open', mock_open()), patch.object(control, 'find_pad', return_value='pad'), \
                patch.object(control, 'configure_buttons', return_value=[288, 290]), \
                patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', side_effect=readings), \
                patch.object(control, 'snapshot', side_effect=snapshot), \
                patch.object(control, 'execute_hold', side_effect=lambda *a: executed.append((clock.now, a[1], dict(a[3])))), \
                patch.object(control.time, 'sleep'), \
                patch.object(control.time, 'monotonic', side_effect=lambda: clock.now), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            control.run(args)
        arm.Arm_serial_servo_write.assert_not_called()
        arm.bus.close.assert_called_once()
        return executed

    def test_startup_missing_joint_does_not_prevent_controlling_ready_joint(self):
        center = {axis: 128 for axis in control.AXES}
        neutral = (center, False, False, False, False)
        base = (center | {0: 255}, False, False, False, False)
        close = (center, False, False, False, True)
        executed = self.startup_loop([neutral, neutral, base, neutral, close, KeyboardInterrupt()],
                                     [RuntimeError('no baseline'), 123, RuntimeError('still zero')])
        self.assertEqual(executed, [(0, (6, 1), {6: 123})])

    def test_manual_baseline_recovery_needs_release_and_new_gesture(self):
        center = {axis: 128 for axis in control.AXES}
        neutral = (center, False, False, False, False)
        base = (center | {0: 255}, False, False, False, False)
        executed = self.startup_loop([neutral, neutral, base, base, neutral, base, KeyboardInterrupt()],
                                     [RuntimeError('no baseline'), 123, 40])
        self.assertEqual(executed, [(0, (1, 1), {1: 40, 6: 123})])

    def test_idle_retry_recovers_baseline_without_replaying_input(self):
        center = {axis: 128 for axis in control.AXES}
        neutral = (center, False, False, False, False)
        base = (center | {0: 255}, False, False, False, False)
        executed = self.startup_loop([neutral, neutral, neutral, neutral, base, neutral, base, KeyboardInterrupt()],
                                     [RuntimeError('no baseline'), 40], joints=('1',), timed=True)
        self.assertEqual(executed, [(7, (1, 1), {1: 40})])

    def test_all_initial_feedback_missing_keeps_loop_alive_without_motion(self):
        center = {axis: 128 for axis in control.AXES}
        neutral = (center, False, False, False, False)
        base = (center | {0: 255}, False, False, False, False)
        executed = self.startup_loop([neutral, neutral, base, neutral, KeyboardInterrupt()],
                                     [RuntimeError('zero')] * 3)
        self.assertEqual(executed, [])

    def test_hold_cli_ignores_step_and_keeps_step_mode_available(self):
        args = control.parse_args(['--mode', 'hold', '--span', '1', '--speed', '10'])
        self.assertEqual(args.mode, 'hold')
        self.assertEqual(args.span, 1)
        self.assertEqual(control.parse_args([]).mode, 'step')

    def test_fractional_motion_and_zero_strength_do_not_force_minimum_steps(self):
        position, target = control.advance_hold(90, 1, 0, 10, 0.2, 30, 150)
        self.assertEqual((position, target), (90, 90))
        position, target = control.advance_hold(90, 1, 0.1, 10, 0.1, 30, 150)
        self.assertAlmostEqual(position, 90.1)
        self.assertEqual(target, 90)
        # A long scheduling delay cannot turn into a large queued command.
        self.assertEqual(control.advance_hold(90, 1, 1, 20, 10, 30, 150), (94, 94))


if __name__ == '__main__':
    unittest.main()

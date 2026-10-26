"""Offline checks; does not import Arm_Lib or access Linux input devices."""
import unittest
import contextlib
import io
import tempfile
import os
from unittest.mock import patch, Mock
from types import SimpleNamespace
import gamepad_arm_control as control


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.center = {axis: 128 for axis in control.AXES}
        self.gate = control.Gate()

    def arm(self, l1=False, r1=False):
        self.assertIsNone(self.gate.update(self.center, l1, r1))

    def test_held_at_start_does_not_move(self):
        pushed = self.center | {0: 0}
        for _ in range(3):
            self.assertIsNone(self.gate.update(pushed, False, False))
        self.assertIsNone(self.gate.update(self.center, False, False, True, False))
        self.arm()
        self.assertEqual(self.gate.update(pushed, False, False), (1, -1))

    def test_one_step_requires_release_and_center(self):
        self.arm()
        pushed = self.center | {0: 0}
        self.assertEqual(self.gate.update(pushed, False, False), (1, -1))
        for _ in range(20):
            self.assertIsNone(self.gate.update(pushed, False, False))
        self.arm()
        self.assertEqual(self.gate.update(pushed, False, False), (1, -1))

    def test_diagonal_and_mode_change_cancel_until_center(self):
        self.arm()
        self.assertIsNone(self.gate.update(self.center | {0: 0, 1: 0}, False, False))
        self.assertIsNone(self.gate.update(self.center | {0: 0}, False, False))
        self.arm()
        self.assertIsNone(self.gate.update(self.center | {1: 0}, True, False))
        self.assertIsNone(self.gate.update(self.center | {1: 0}, True, False))
        self.arm(l1=True)
        self.assertEqual(self.gate.update(self.center | {1: 0}, True, False), (4, -1))

    def test_all_axis_mappings(self):
        for axis, l1, r1, expected in ((0, False, False, 1), (1, False, False, 2),
                                      (2, False, False, 3), (1, True, False, 4),
                                      (5, False, True, 5)):
            for value, direction in ((0, -1), (255, 1)):
                self.gate = control.Gate()
                self.arm(l1, r1)
                self.assertEqual(self.gate.update(self.center | {axis: value}, l1, r1),
                                 (expected, direction))

    def test_right_horizontal_without_r1_is_unused(self):
        self.arm()
        self.assertIsNone(self.gate.update(self.center | {5: 255}, False, False))
        self.assertIsNone(self.gate.update(self.center | {5: 255}, False, True))
        self.arm(r1=True)
        self.assertEqual(self.gate.update(self.center | {5: 255}, False, True), (5, 1))

    def test_gripper_buttons_release_before_repeat_and_no_conflicting_input(self):
        for opening, closing, direction in ((True, False, -1), (False, True, 1)):
            self.gate = control.Gate()
            self.arm()
            self.assertEqual(self.gate.update(self.center, False, False, opening, closing), (6, direction))
            self.assertIsNone(self.gate.update(self.center, False, False, opening, closing))
            self.assertIsNone(self.gate.update(self.center, False, False, closing, opening))
            self.arm()
            self.assertEqual(self.gate.update(self.center, False, False, opening, closing), (6, direction))
        self.arm()
        self.assertIsNone(self.gate.update(self.center, False, False, True, True))
        self.arm()
        self.assertIsNone(self.gate.update(self.center | {0: 255}, False, False, True, False))

    def test_command_recheck_accepts_release_but_cancels_conflicts(self):
        original = (self.center | {1: 255}, False, False, False, False)
        self.assertTrue(control.same_action(original, original, (2, 1)))
        self.assertTrue(control.same_action(original, (self.center, False, False, False, False), (2, 1)))
        for latest in (None,
                       (self.center | {1: 0}, False, False, False, False),
                       (self.center | {1: 255}, True, False, False, False),
                       (self.center | {1: 255, 0: 0}, False, False, False, False)):
            self.assertFalse(control.same_action(original, latest, (2, 1)))
        original = (self.center, False, False, True, False)
        self.assertTrue(control.same_action(original, original, (6, -1)))
        self.assertTrue(control.same_action(original, (self.center, False, False, False, False), (6, -1)))

    def test_tapped_numbers_and_stick_execute_after_release_during_feedback(self):
        released = (self.center, False, False, False, False)
        for state, action, current, target in (
                ((self.center, False, False, True, False), (6, -1), 151, 135),
                ((self.center, False, False, False, True), (6, 1), 151, 167),
                ((self.center | {1: 0}, False, False, False, False), (2, -1), 91, 75)):
            with self.subTest(action=action):
                self.gate = control.Gate()
                self.gate.update(*released)
                self.assertEqual(self.gate.update(*state), action)
                arm = SimpleNamespace(Arm_serial_servo_write=Mock())
                args = SimpleNamespace(step=16, span=60, speed=10)
                with patch.object(control, 'check_other_controllers'), \
                        patch.object(control, 'stable_angle', side_effect=[current, target]), \
                        patch.object(control.time, 'monotonic', side_effect=[100, 100.1]), \
                        patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                    control.execute_step(arm, action, state, {action[0]: current}, args, lambda: released)
                arm.Arm_serial_servo_write.assert_called_once_with(action[0], target, 1600)
                # Holding the original input after a completed action cannot retrigger.
                self.gate = control.Gate()
                self.assertIsNone(self.gate.update(*state))

    def test_pending_step_is_discarded_on_stale_conflicting_or_disconnected_input(self):
        state = (self.center, False, False, True, False)
        released = (self.center, False, False, False, False)
        for latest, elapsed in ((released, 0.6), (None, 0.1),
                                ((self.center, False, False, False, True), 0.1),
                                ((self.center | {0: 255}, False, False, False, False), 0.1)):
            arm = SimpleNamespace(Arm_serial_servo_write=Mock())
            with patch.object(control, 'check_other_controllers'), \
                    patch.object(control, 'stable_angle', return_value=151), \
                    patch.object(control.time, 'monotonic', side_effect=[100, 100 + elapsed]), \
                    contextlib.redirect_stdout(io.StringIO()):
                control.execute_step(arm, (6, -1), state, {6: 151}, SimpleNamespace(step=16, span=60, speed=10), lambda: latest)
            arm.Arm_serial_servo_write.assert_not_called()
        arm = SimpleNamespace(Arm_serial_servo_write=Mock())
        with patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', return_value=151), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
            control.execute_step(arm, (6, -1), state, {6: 151}, SimpleNamespace(step=16, span=60, speed=10),
                                 Mock(side_effect=OSError('device disconnected')))
        arm.Arm_serial_servo_write.assert_not_called()

    def test_tapped_step_does_not_bypass_limit_or_feedback_checks(self):
        state = (self.center, False, False, False, True)
        released = (self.center, False, False, False, False)
        arm = SimpleNamespace(Arm_serial_servo_write=Mock())
        args = SimpleNamespace(step=16, span=60, speed=10)
        with patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', return_value=176), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(control.LimitReached):
            control.execute_step(arm, (6, 1), state, {6: 176}, args, lambda: released)
        arm.Arm_serial_servo_write.assert_not_called()
        with patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'stable_angle', side_effect=[151, 151]), \
                patch.object(control.time, 'monotonic', side_effect=[100, 100.1]), \
                patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(RuntimeError):
            control.execute_step(arm, (6, 1), state, {6: 151}, args, lambda: released)
        arm.Arm_serial_servo_write.assert_called_once_with(6, 167, 1600)

    def test_button_learning_and_saved_mapping(self):
        # Physical printed labels need not match assumed HID numbering.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'buttons.json')
            with open(path, 'w') as f:
                f.write('[291, 289]')  # Replace the user's previously wrong mapping.
            states = [{288}, set(), {292}, set(), {291}, {291}, set(), {288},
                      set(), {288}, set(), {288}, {288}, set(), {288},
                      set(), {290}, set(), {290}, set()]
            with patch.object(control, 'pressed_keys', side_effect=states), patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(control.configure_buttons(0, path, force=True), [288, 290])
            with patch.object(control, 'pressed_keys') as read:
                self.assertEqual(control.configure_buttons(0, path), [288, 290])
                read.assert_not_called()
            with open(path, 'w') as f:
                f.write('[292, 288]')
            with self.assertRaises(RuntimeError):
                control.configure_buttons(0, path)

    def test_interrupted_button_learning_preserves_previous_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'buttons.json')
            with open(path, 'w') as f:
                f.write('[291, 289]')
            with patch.object(control, 'pressed_keys', side_effect=[set(), {288}, KeyboardInterrupt()]), \
                    patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(KeyboardInterrupt):
                control.configure_buttons(0, path, force=True)
            self.assertEqual(control.configure_buttons(0, path), [291, 289])

    def test_button_bitmap_uses_learned_codes(self):
        with patch.object(control, 'pressed_keys', return_value={292, 291}):
            self.assertEqual(control.buttons(0, [291, 289]), (True, False, True, False))

    def test_limits(self):
        self.assertEqual(control.target_angle(90, 1, 90, 180), 92)
        for values in ((100, 1, 90, 180), (0, -1, 0, 180),
                       (179, 1, 179, 180), (269, 1, 269, 270), (110, -1, 90, 180)):
            with self.assertRaises(RuntimeError):
                control.target_angle(*values)

    def test_unstable_feedback_stops(self):
        with patch.object(control, 'angle_once', side_effect=[90, 100]), patch.object(control.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                control.stable_angle(None, 1)

    def test_zero_raw_feedback_retries_require_two_consecutive_valid_readings(self):
        for sequence, expected in (([control.FeedbackUnavailable(), 155, 155], 155),
                                   ([155, control.FeedbackUnavailable(), 155, 156], 156),
                                   ([0, 0], 0)):
            with patch.object(control, 'angle_once', side_effect=sequence) as read, \
                    patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(control.stable_angle(None, 6), expected)
                self.assertEqual(read.call_count, len(sequence))
        with patch.object(control, 'angle_once', side_effect=control.FeedbackUnavailable()) as read, \
                patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(RuntimeError):
            control.stable_angle(None, 6)
        self.assertEqual(read.call_count, 4)
        for error in (RuntimeError('out of range'), OSError('bus error')):
            with patch.object(control, 'angle_once', side_effect=error) as read, \
                    self.assertRaises(type(error)):
                control.stable_angle(None, 6)
            read.assert_called_once()

    def test_zero_after_movement_only_retries_feedback_not_motion(self):
        state = (self.center, False, False, True, False)
        released = (self.center, False, False, False, False)
        args = SimpleNamespace(step=16, span=60, speed=10)
        for persistent in (False, True):
            arm = SimpleNamespace(Arm_serial_servo_write=Mock())
            after = [control.FeedbackUnavailable()] * 4 if persistent else [control.FeedbackUnavailable(), 155, 155]
            with patch.object(control, 'check_other_controllers'), \
                    patch.object(control, 'angle_once', side_effect=[171, 171] + after), \
                    patch.object(control.time, 'monotonic', side_effect=[100, 100.1]), \
                    patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
                if persistent:
                    with self.assertRaises(RuntimeError):
                        control.execute_step(arm, (6, -1), state, {6: 172}, args, lambda: released)
                else:
                    control.execute_step(arm, (6, -1), state, {6: 172}, args, lambda: released)
            arm.Arm_serial_servo_write.assert_called_once_with(6, 155, 1600)

    def test_persistent_zero_before_movement_never_sends_command(self):
        arm = SimpleNamespace(Arm_serial_servo_write=Mock())
        with patch.object(control, 'check_other_controllers'), \
                patch.object(control, 'angle_once', side_effect=control.FeedbackUnavailable()), \
                patch.object(control.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(RuntimeError):
            control.execute_step(arm, (6, -1), (self.center, False, False, True, False),
                                 {6: 172}, SimpleNamespace(step=16, span=60, speed=10), Mock())
        arm.Arm_serial_servo_write.assert_not_called()

    def test_rejected_step_allows_inward_step_with_original_bounds(self):
        # Reproduce the user's joint 2 stop: initial 91, current 62, step 8.
        with self.assertRaises(control.LimitReached):
            control.target_angle(62, -1, 91, 180, 8, 30)
        self.gate = control.Gate()  # Controller resets enable after rejection.
        self.assertIsNone(self.gate.update(self.center | {1: 255}, False, False))
        self.arm()
        self.assertEqual(self.gate.update(self.center | {1: 255}, False, False), (2, 1))
        self.assertEqual(control.target_angle(62, 1, 91, 180, 8, 30), 70)
        with self.assertRaises(control.LimitReached):
            control.target_angle(120, 1, 91, 180, 8, 30)

    def test_feedback_outside_session_remains_fatal(self):
        with self.assertRaises(RuntimeError) as raised:
            control.target_angle(60, 1, 91, 180, 8, 30)
        self.assertNotIsInstance(raised.exception, control.LimitReached)

    def read_position(self, joint, position):
        raw = ((position >> 8) & 255) | ((position << 8) & 0xff00)
        bus = SimpleNamespace(write_byte_data=lambda *args: None,
                              read_word_data=lambda *args: raw)
        with patch.object(control.time, 'sleep'):
            return control.angle_once(SimpleNamespace(addr=0x15, bus=bus), joint)

    def test_endpoint_feedback_matches_official_whole_degree_conversion(self):
        self.assertEqual(self.read_position(3, 3104), 0)
        self.assertEqual(self.read_position(1, 3104), 180)
        self.assertEqual(self.read_position(4, 896), 180)
        self.assertEqual(self.read_position(5, 3704), 270)
        self.assertEqual(self.read_position(5, 376), 0)
        self.assertEqual(self.read_position(1, 2000), 90)
        initial = self.read_position(3, 3104)
        self.assertEqual(control.target_angle(initial, 1, initial, 180, 8, 30), 8)
        with self.assertRaises(RuntimeError):
            control.target_angle(initial, -1, initial, 180, 8, 30)

    def test_invalid_feedback_still_stops(self):
        for joint, position in ((3, 3120), (4, 880), (5, 3720), (5, 360),
                                (1, 0), (1, 65535)):
            with self.subTest(joint=joint, position=position), self.assertRaises(RuntimeError):
                self.read_position(joint, position)

    def test_larger_steps_still_respect_window_and_physical_limits(self):
        self.assertEqual(control.target_angle(85, 1, 85, 180, 8, 30), 93)
        self.assertEqual(control.target_angle(101, -1, 85, 180, 8, 30), 93)
        for values in ((109, 1, 85, 180, 8, 30), (0, -1, 0, 180, 8, 30),
                       (175, 1, 175, 180, 8, 30), (268, 1, 260, 270, 8, 30)):
            with self.assertRaises(RuntimeError):
                control.target_angle(*values)

    def test_options_and_invalid_settings(self):
        args = control.parse_args(['--move', '--joints', '1', '1', '2', '3', '4', '5', '6',
                                   '--step', '8', '--span', '30'])
        self.assertEqual(args.joints, [1, 2, 3, 4, 5, 6])
        self.assertEqual((args.step, args.span, args.move), (8, 30, True))
        self.assertFalse(control.parse_args([]).move)
        defaults = control.parse_args([])
        self.assertEqual((defaults.step, defaults.span), (16, 90))
        self.assertEqual(defaults.speed, 10)
        self.assertEqual(control.parse_args(['--speed', '5']).speed, 5)
        self.assertEqual(control.parse_args(['--speed', '20']).speed, 20)
        expanded = control.parse_args(['--step', '16', '--span', '60'])
        self.assertEqual((expanded.step, expanded.span), (16, 60))
        self.assertEqual(control.parse_args(['--span', '90']).span, 90)
        for options in (['--step', '0'], ['--step', '17'], ['--span', '91'],
                        ['--speed', '0'], ['--speed', '21'],
                        ['--span', '5', '--step', '8']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                control.parse_args(options)

    def test_speed_changes_duration_without_shortening_settling_wait(self):
        self.assertEqual(control.movement_duration_ms(16, 5), 3200)
        self.assertEqual(control.movement_duration_ms(16, 10), 1600)
        self.assertEqual(control.movement_duration_ms(16, 20), 800)
        self.assertEqual(control.movement_duration_ms(2, 20), 800)
        for speed, duration in ((5, 3200), (10, 1600), (20, 800)):
            arm = SimpleNamespace(Arm_serial_servo_write=Mock())
            with patch.object(control, 'check_other_controllers'), \
                    patch.object(control, 'stable_angle', side_effect=[151, 135]), \
                    patch.object(control.time, 'monotonic', side_effect=[100, 100.1]), \
                    patch.object(control.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
                control.execute_step(arm, (6, -1), (self.center, False, False, True, False),
                                     {6: 151}, SimpleNamespace(step=16, span=60, speed=speed),
                                     lambda: (self.center, False, False, False, False))
            arm.Arm_serial_servo_write.assert_called_once_with(6, 135, duration)
            sleep.assert_any_call(duration / 1000 + 0.4)

    def test_sixteen_degree_steps_with_sixty_degree_window(self):
        self.assertEqual(control.target_angle(90, 1, 90, 180, 16, 60), 106)
        self.assertEqual(control.target_angle(46, -1, 90, 180, 16, 60), 30)
        self.assertEqual(control.target_angle(134, 1, 90, 180, 16, 60), 150)
        for values in ((30, -1, 90, 180), (150, 1, 90, 180),
                       (176, 1, 176, 180), (260, 1, 250, 270)):
            with self.assertRaises(control.LimitReached):
                control.target_angle(*values, step=16, span=60)
        self.assertEqual(control.target_angle(30, 1, 90, 180, 16, 60), 46)
        self.assertEqual(control.target_angle(176, -1, 176, 180, 16, 60), 160)


if __name__ == '__main__':
    unittest.main()

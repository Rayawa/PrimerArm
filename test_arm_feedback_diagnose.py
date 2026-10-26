import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import arm_feedback_diagnose as diag


class DiagnosticTests(unittest.TestCase):
    def test_collect_only_uses_documented_queries_and_decodes_raw_position(self):
        bus = SimpleNamespace(write_byte_data=Mock(), read_byte_data=Mock(return_value=218),
                              read_word_data=Mock(return_value=0xd007))
        output = io.StringIO()
        with patch.object(diag.time, 'sleep'), contextlib.redirect_stdout(output):
            diag.collect(bus, 0.003)
        expected = [(0x15, 0x01, 1)]
        for joint in range(1, 7):
            expected.extend([(0x15, 0x38, joint), (0x15, 0x30 + joint, 0)])
        self.assertEqual([c.args for c in bus.write_byte_data.call_args_list], expected)
        self.assertEqual(output.getvalue().count('原始位置=2000'), 6)

    def test_failed_query_is_not_retried_and_motion_register_is_rejected(self):
        bus = SimpleNamespace(write_byte_data=Mock(side_effect=OSError('no response')))
        with patch.object(diag.time, 'sleep') as sleep:
            self.assertIn('OSError', diag.query(bus, 0x31, 0, 0.003, word=True))
        bus.write_byte_data.assert_called_once()
        sleep.assert_called_once_with(0.5)
        with self.assertRaises(ValueError):
            diag.query(bus, 0x11, 90, 0.003)
        bus.write_byte_data.assert_called_once()


if __name__ == '__main__':
    unittest.main()

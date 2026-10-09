import unittest

from podcast_automation.timecode import (TimestampError, fps_to_resolve_setting, parse_fps,
                                         parse_timestamp, resolve_trim, timecode_to_frames)


class ParseTimestampTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_timestamp("1:02:03", 30), (3600 + 120 + 3) * 30)
        self.assertEqual(parse_timestamp("02:03", 30), 123 * 30)
        self.assertEqual(parse_timestamp("00:00:01.5", 30), 45)
        self.assertEqual(parse_timestamp("00:00:01:12", 30), 42)
        self.assertEqual(parse_timestamp("90", 25), 2250)
        self.assertEqual(parse_timestamp("1.5", 24), 36)
        self.assertIsNone(parse_timestamp("  ", 30))
        self.assertIsNone(parse_timestamp(None, 30))

    def test_fractional_fps(self):
        self.assertEqual(parse_timestamp("00:01:00", 29.97), 1798)
        self.assertEqual(parse_timestamp("00:00:01:29", 29.97), 59)

    def test_rejects_garbage(self):
        for bad in ("abc", "1:2:3:4:5", "00:61:00", "00:00:75", "00:00:01:30", "-5"):
            with self.assertRaises(TimestampError, msg=bad):
                parse_timestamp(bad, 30)

    def test_resolve_trim(self):
        self.assertEqual(resolve_trim("", "", 30, 900), (0, 900))
        self.assertEqual(resolve_trim("5", "", 30, 900), (150, 900))
        self.assertEqual(resolve_trim("00:05", "00:10", 30, 900), (150, 300))
        with self.assertRaises(TimestampError):
            resolve_trim("10", "5", 30, 900)
        with self.assertRaises(TimestampError):
            resolve_trim("0", "40", 30, 900)

    def test_helpers(self):
        self.assertEqual(parse_fps("23.976 DF"), 23.976)
        self.assertEqual(parse_fps(25), 25.0)
        self.assertEqual(timecode_to_frames("00:00:10:05", 25), 255)
        self.assertEqual(timecode_to_frames("00:00:10;05", 29.97), 305)
        self.assertEqual(fps_to_resolve_setting(29.97002997), "29.97")
        self.assertEqual(fps_to_resolve_setting(30.0), "30")
        self.assertEqual(fps_to_resolve_setting(12.5), "12.5")


if __name__ == "__main__":
    unittest.main()

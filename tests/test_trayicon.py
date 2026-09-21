import unittest

from trayicon import make_icon_pixels


class TestMakeIconPixels(unittest.TestCase):
    def test_size_and_corners_transparent(self):
        buf = make_icon_pixels(16)
        self.assertEqual(len(buf), 16 * 16 * 4)
        self.assertEqual(buf[0:4], b"\x00\x00\x00\x00")        # 角落透明

    def test_center_bright_inner_dark(self):
        buf = make_icon_pixels(16)
        i = (8 * 16 + 8) * 4                                    # 中心：亮心
        self.assertEqual(buf[i:i + 4], b"\xa1\xe3\xa6\xff")
        j = (1 * 16 + 8) * 4                                    # 圆环内：深底
        self.assertEqual(buf[j:j + 4], b"\x2e\x1e\x1e\xff")


if __name__ == "__main__":
    unittest.main()

import threading
import unittest

from trayicon import TrayIcon, make_icon_pixels


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


class TestShowGuard(unittest.TestCase):
    def test_second_show_while_thread_alive_returns_false(self):
        t = TrayIcon(tip="x")
        release = threading.Event()
        started = threading.Event()

        def blocker():
            started.set()
            release.wait(2)

        th = threading.Thread(target=blocker, daemon=True)
        t._thread = th
        th.start()
        started.wait(1)
        try:
            self.assertFalse(t.show())       # 线程活着：不得再启动第二个（防孤儿图标）
            self.assertIs(t._thread, th)     # 不变量：活线程未被替换
        finally:
            release.set()
            th.join(2)


if __name__ == "__main__":
    unittest.main()

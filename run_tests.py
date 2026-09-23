"""测试入口：python run_tests.py

功能与 python -m unittest 相同，但结束时用 os._exit 跳过解释器终结——
Tk 跨线程场景下 Tcl_AsyncDelete 偶发 panic 会中止默认入口并吞掉结果，
此入口保证始终输出真实的通过/失败与退出码。
"""

import os
import sys
import unittest

if __name__ == "__main__":
    suite = unittest.TestLoader().discover("tests")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.stdout.flush()
    os._exit(0 if result.wasSuccessful() else 1)

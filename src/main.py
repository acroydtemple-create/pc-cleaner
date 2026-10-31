# -*- coding: utf-8 -*-
"""深度清理工具入口"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    from ui_app import main as run
    run()


if __name__ == "__main__":
    main()

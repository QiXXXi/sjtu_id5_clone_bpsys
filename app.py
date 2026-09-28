#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第五人格 BP 工具 —— 启动入口。

    python app.py                     自动挑一个放得下的 16:9 尺寸
    python app.py --size 1440x810     固定尺寸(便于复现问题)
"""

import sys

from id5.screens import App


def enable_dpi_awareness():
    """让 Windows 不要拉伸我们的窗口。

    不声明 DPI 感知的话, 系统会把整个窗口按缩放比例(这台机器是 1.75x)
    位图放大, 字会发虚。Tk 的控件坐标在两种模式下都自洽, 而弹窗是主窗口
    内的 place() 子控件(用的是父控件相对坐标), 因此不受坐标系影响。
    """
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # system DPI aware
    except Exception:
        pass


def set_app_id():
    """给进程一个自己的 AppUserModelID。

    Windows 默认按"哪个 exe"决定任务栏图标和按钮归组 —— 源码运行时那个 exe 是
    python.exe, 于是任务栏上显示的是 **Python 的图标**, 光设窗口图标压不过它。
    显式声明一个 AppID 之后, 任务栏和 Alt-Tab 才认这是「第五人格BP工具」。
    必须在创建任何窗口之前调用。
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "QiXXXi.SJTU.id5_clone")
    except Exception:
        pass


def parse_size(argv):
    for i, arg in enumerate(argv):
        if arg == "--size" and i + 1 < len(argv):
            try:
                w, h = argv[i + 1].lower().split("x")
                return int(w), int(h)
            except ValueError:
                print("--size 格式应为 1440x810，已忽略: %s" % argv[i + 1])
    return None


def main():
    enable_dpi_awareness()
    set_app_id()
    app = App(size=parse_size(sys.argv[1:]))
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

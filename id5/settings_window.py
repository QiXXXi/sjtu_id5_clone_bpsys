#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗口: 白天/黑夜皮肤 + 动画时长。

为什么是**带标题栏的普通 Toplevel**, 而不是像下拉弹窗那样用 place() 的子控件:
项目里那条"Toplevel 在 Windows 上会被主窗口盖住"的结论, 只对
`overrideredirect(True)` 的无边框窗口成立 —— 无边框窗口不受窗口管理器管辖。
带标题栏的窗口由窗口管理器正常管理, 没有这个问题。所以本文件里**不要**出现
overrideredirect。

为什么不做成模态(grab_set): 非模态才能一边看着主控制台一边调皮肤。而且
设置窗口的控件不参与"随机抽取后的点击锁定"(那是控制台自己的事), 两者不冲突。

和直播窗口的关系: 那边**不置顶**(见 live_window 模块头), 所以两边都是普通窗口,
`lift()` 就够, 谁也不会压住谁。

为什么和 screens.py 互相 import 却不修改模块结构: settings_window 需要
screens.Switch; screens 需要 SettingsWindow。screens 那边用**函数内延迟导入**
打断成环, 依赖方向就只剩 settings_window → screens 单向。
"""

import tkinter as tk
from tkinter import ttk

from . import config as C
from .screens import Switch


class SettingsWindow(tk.Toplevel):
    """单例设置窗口。重复调用 open() 只会把已开的那个唤到前面。"""

    _instance = None

    @classmethod
    def open(cls, app):
        win = cls._instance
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_set()
            return win
        cls._instance = cls(app)
        return cls._instance

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.state = app.state

        self.title("设置")
        self.configure(bg=C.BG)
        # transient: 跟着主窗口走, 主窗口最小化时一起隐藏, 不会掉到它后面
        self.transient(app.root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._anim_trace = None
        self._place_over_parent()
        self._build()

    # -- 位置 ----------------------------------------------------------

    def _place_over_parent(self):
        """16:9 居中于主窗口。放不下就退回主窗口的尺寸。"""
        w, h = C.SETTINGS_SIZE
        pw = self.app.root.winfo_width()
        ph = self.app.root.winfo_height()
        w, h = min(w, pw), min(h, ph)
        x = self.app.root.winfo_rootx() + (pw - w) // 2
        y = self.app.root.winfo_rooty() + (ph - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # -- 构建 ----------------------------------------------------------

    def _build(self):
        # 内容自然尺寸、整块居中。不给固定宽高 —— 那样一旦内容长高了就会被裁掉。
        body = tk.Frame(self, bg=C.BG)
        body.place(relx=0.5, rely=0.5, anchor="center")

        self._build_skin(body)
        self._build_anim(body)

        ttk.Button(body, text="关闭", command=self._on_close).pack(
            fill="x", pady=(C.px(18), 0))

        # 版权信息。用 C.BG / C.FG_DIM 这两个**调色板**里的值, 换肤才带得动它
        # (_retheme_tree 是按调色板的色值表做映射的, 写死颜色切皮肤时不会变)。
        tk.Label(body, text="作者：%s\n版权协议：%s" % (C.APP_AUTHOR, C.APP_LICENSE),
                 bg=C.BG, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                 justify="center").pack(pady=(C.px(14), 0))

    def _build_skin(self, parent):
        card = self._card(parent, "皮肤")
        row = tk.Frame(card, bg=C.CARD)
        row.pack(fill="x", padx=C.px(16), pady=(C.px(4), C.px(14)))

        # 开关的语义是"黑夜开/关"。Switch 点一下会先 var.set() 再调 command(),
        # 所以 _on_skin 里读到的已经是新值了。
        self._night = tk.BooleanVar(master=self,
                                    value=(C.current_theme() == "dark"))
        self._interactive_skin = Switch(row, self._night, command=self._on_skin)
        self._interactive_skin.pack(side="left")
        self._skin_value = tk.Label(row, text="", bg=C.CARD, fg=C.FG,
                                    font=C.font(C.FONT_BODY), anchor="w")
        self._skin_value.pack(side="left", padx=(C.px(12), 0))
        self._refresh_skin_value()

    def _build_anim(self, parent):
        card = self._card(parent, "动画时长（秒）")
        row = tk.Frame(card, bg=C.CARD)
        row.pack(fill="x", padx=C.px(16), pady=(C.px(4), C.px(14)))

        # 不加 validate=。ban 数量那个校验器只认整数, 会把 "3." / "2.5" 判非法,
        # 小数压根输不进去。代价是可能敲进乱七八糟的字符 —— 所以读值一律走
        # state.anim_ms(), 它负责钳位。
        spin = ttk.Spinbox(row, from_=C.ANIM_MIN, to=C.ANIM_MAX,
                           increment=C.ANIM_STEP,
                           textvariable=self.state.animation_seconds,
                           format="%.1f", width=5,
                           font=C.font(C.FONT_BODY), justify="center")
        spin.pack(side="left")
        tk.Label(row, text="随机选择后这段时间内不响应点击；0 = 关闭该功能",
                 bg=C.CARD, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                 anchor="w").pack(side="left", padx=(C.px(12), 0))

        # 记住 trace 名字, 关窗时摘掉 —— 窗口是单例但会重新构造, 不摘的话
        # 每开关一次就多攒一条, 敲一下存 N 次(幂等, 但没必要)。
        self._anim_trace = self.state.animation_seconds.trace_add(
            "write", lambda *_: self._save_anim())

    def _card(self, parent, caption):
        card = tk.Frame(parent, bg=C.CARD)
        card.pack(fill="x", pady=C.px(6))
        tk.Label(card, text=caption, bg=C.CARD, fg=C.FG_DIM,
                 font=C.font(C.FONT_CAPTION), anchor="w").pack(
            fill="x", padx=C.px(16), pady=(C.px(10), 0))
        return card

    # -- 行为 ----------------------------------------------------------

    def _refresh_skin_value(self):
        self._skin_value.configure(text="黑夜" if self._night.get() else "白天")

    def _on_skin(self):
        """切皮肤。apply_theme 内部会写 settings.json, 这里不用再存一次。"""
        self.app.apply_theme("dark" if self._night.get() else "light")
        self._refresh_skin_value()

    def _save_anim(self):
        try:
            seconds = float(self.state.animation_seconds.get())
        except (tk.TclError, ValueError):
            return            # 输入中间态(空串 / "3."), 等敲完再说
        self.app.settings["animation_seconds"] = seconds
        C.save_settings(self.app.settings)

    def _on_close(self):
        if self._anim_trace is not None:
            try:
                self.state.animation_seconds.trace_remove("write", self._anim_trace)
            except tk.TclError:
                pass
            self._anim_trace = None
        SettingsWindow._instance = None
        self.destroy()

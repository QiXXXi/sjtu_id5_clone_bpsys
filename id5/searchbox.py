#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可搜索头像下拉菜单 + 全局单例弹窗。

为什么不用 ttk.Combobox / tk.Listbox:
    这两者的列表项都只能是字符串, 无法逐项显示头像。
所以这里用 ttk.Entry + Canvas 自绘列表。

弹窗为什么是主窗口的子控件, 而不是 Toplevel:
    曾经用 overrideredirect 的 Toplevel 实现, 在 Windows 上会被主窗口
    整个盖住 —— Tk 报告 mapped=1 viewable=1、尺寸位置全对, 屏幕上却什么都
    没有, 且 lift() 无效, 只有设成 -topmost 才显示(那样弹窗又会浮在别的
    程序之上)。改成主窗口里的 place() 子控件后, 它天然不可能跑到自己的
    顶层窗口后面, 也不用再操心置顶状态。代价是弹窗被限制在窗口内,
    所以靠近底部的行必须向上翻转(见 _place)。

核心设计(这几条是成败点, 改动前请先读):
  1. 弹窗永不获取键盘焦点, 也不 grab_set。所有按键都绑在 Entry 上,
     于是打字/上下键/Esc/Enter 都是普通 Entry 事件, 不存在焦点仲裁问题。
  2. 过滤用 StringVar.trace 而非 <KeyRelease>。中文输入法会吞掉按键事件,
     KeyRelease 会漏掉所有中文输入; 变量 trace 在文本真正变化时必定触发。
  3. 弹窗是全应用单例, 且 bind_all 只装一次。永远不要 unbind_all ——
     它会连带移除其他代码注册的绑定。
  4. bind_all 的点击处理器永不返回 "break"。messagebox 跑嵌套事件循环,
     bind_all 仍会触发, 返回 "break" 会让确认框的按钮失灵。
"""

import tkinter as tk
from tkinter import ttk

from . import config as C
from .roster import THUMBS, item_matches


def close_popup():
    """关闭当前弹窗(如果有)。切换界面时调用, 避免它留在新界面上。"""
    if _Popup._instance is not None:
        _Popup._instance.close()


class _Popup:
    """全应用唯一的下拉弹窗, 寄生在主窗口内。"""

    _instance = None

    @classmethod
    def get(cls, root):
        if cls._instance is None:
            cls._instance = cls(root)
        return cls._instance

    def __init__(self, root):
        self.root = root
        self.host = root                  # 弹窗的父控件 = 主窗口本体
        # 行高要比头像略大, 否则文字贴着上下边
        self.ROW_H = C.px(C.THUMB_ROW_PX + 8)
        self.PAD = C.px(6)
        self.THUMB = C.px(C.THUMB_ROW_PX)
        self.MAX_VISIBLE = 8
        self._owner = None
        self._width = C.px(240)

        self.frame = tk.Frame(self.host, bg=C.POPUP_BG,
                              highlightthickness=1,
                              highlightbackground=C.BORDER)
        self.canvas = tk.Canvas(self.frame, bg=C.POPUP_BG,
                                highlightthickness=0,
                                yscrollincrement=self.ROW_H)
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical",
                                       command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.frame.place_forget()         # 先藏起来, 首次 show() 才摆位置

        # 永久安装, 只此一次。无 owner 时自动空转。
        root.bind_all("<Button-1>", self._on_global_click, add="+")
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        for widget in (self.canvas, self.frame):
            widget.bind("<MouseWheel>", self._on_wheel)

    # -- 显隐 ----------------------------------------------------------

    def show(self, owner):
        """打开/刷新。已在显示时只重新定位并重绘。"""
        self._owner = owner
        self._place(owner)
        self.redraw()
        self.frame.lift()

    def close(self):
        if self._owner is None:
            return
        owner = self._owner
        self._owner = None
        self.frame.place_forget()
        owner._on_popup_closed()

    def is_open_for(self, owner):
        return self._owner is owner

    # -- 定位 ----------------------------------------------------------

    def _place(self, owner):
        entry = owner._entry
        entry.update_idletasks()          # 否则 winfo_* 拿到的是过期值
        host = self.host
        # place() 用的是父控件坐标系, 所以要减掉父控件的屏幕原点
        ex = entry.winfo_rootx() - host.winfo_rootx()
        ey = entry.winfo_rooty() - host.winfo_rooty()
        eh = entry.winfo_height()
        w = max(entry.winfo_width(), C.px(200))
        self._width = w

        rows = max(1, min(len(owner._filtered), self.MAX_VISIBLE))
        h = rows * self.ROW_H + 2
        y = ey + eh
        # 靠窗口底部的格子向下弹会溢出被裁掉, 这时改成向上翻。
        if y + h > host.winfo_height() - C.px(4):
            y = max(0, ey - h)
        self.frame.place(x=ex, y=y, width=w, height=h)

    # -- 绘制 ----------------------------------------------------------

    def redraw(self):
        owner = self._owner
        if owner is None:
            return
        items = owner._filtered
        self.canvas.delete("all")
        total_h = max(1, len(items) * self.ROW_H)
        self.canvas.configure(scrollregion=(0, 0, self._width, total_h))
        text_x = self.PAD + self.THUMB + C.px(8)
        for i, item in enumerate(items):
            y = i * self.ROW_H
            self.canvas.create_image(self.PAD, y + self.ROW_H // 2, anchor="w",
                                     image=THUMBS.row_thumb(item), tags="row")
            self.canvas.create_text(text_x, y + self.ROW_H // 2, anchor="w",
                                    text=item.label, fill=C.FG,
                                    font=C.font(C.FONT_BODY), tags="row")
        self._draw_highlight()
        self.canvas.yview_moveto(0)

    def _draw_highlight(self):
        self.canvas.delete("hl")
        owner = self._owner
        if owner is None or not (0 <= owner._sel < len(owner._filtered)):
            return
        y = owner._sel * self.ROW_H
        self.canvas.create_rectangle(0, y, self._width, y + self.ROW_H,
                                     fill=C.ACCENT_DARK, outline="", tags="hl")
        self.canvas.tag_lower("hl")

    def move_highlight(self):
        """只挪高亮条, 不重绘整张列表。"""
        self._draw_highlight()
        owner = self._owner
        if owner is None or not owner._filtered:
            return
        y = owner._sel * self.ROW_H
        view_top = self.canvas.canvasy(0)
        view_h = self.canvas.winfo_height()
        if y < view_top:
            self.canvas.yview_moveto(y / (len(owner._filtered) * self.ROW_H))
        elif y + self.ROW_H > view_top + view_h:
            bottom = y + self.ROW_H - view_h
            self.canvas.yview_moveto(max(0, bottom) / (len(owner._filtered) * self.ROW_H))

    # -- 事件 ----------------------------------------------------------

    def _on_global_click(self, event):
        """点击外部关闭。永远不要返回 "break"(见文件头第 4 条)。"""
        if self._owner is None:
            return
        px, py = self.frame.winfo_rootx(), self.frame.winfo_rooty()
        inside = (px <= event.x_root < px + self.frame.winfo_width() and
                  py <= event.y_root < py + self.frame.winfo_height())
        if not inside:
            self.close()

    def _index_at(self, event):
        return int(self.canvas.canvasy(event.y)) // self.ROW_H

    def _on_click(self, event):
        owner = self._owner
        if owner is None:
            return
        i = self._index_at(event)
        if 0 <= i < len(owner._filtered):
            owner._commit(owner._filtered[i])
        # Windows 可能把激活权交给 owner 窗口, 这里显式抢回键盘焦点
        owner._entry.focus_set()

    def _on_motion(self, event):
        owner = self._owner
        if owner is None:
            return
        i = self._index_at(event)
        if 0 <= i < len(owner._filtered) and i != owner._sel:
            owner._sel = i
            self.move_highlight()

    def _on_wheel(self, event):
        if self._owner is None:
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"


class SearchableAvatarDropdown(ttk.Frame):
    """头像 + 可搜索输入框 + 下拉箭头。value 为 "" 表示未选择。

    pool_provider 是可选的"本题可选池"回调, 每次打开/输入时重新求值,
    这样同一局里已被别的格子占用的角色就不会再出现在列表里。
    """

    def __init__(self, master, items, on_change=None):
        super().__init__(master, style="Card.TFrame")
        self._items = items               # 与 Roster 共享同一 list 对象
        self._pool = list(items)          # 当前可选项(受 pool_provider 约束)
        self._pool_provider = None
        self._filtered = list(items)
        self._value = ""
        self._sel = -1
        self._suppress = False
        self._enabled = True
        self._on_change = on_change

        self._var = tk.StringVar()
        self._avatar = tk.Label(self, image=THUMBS.placeholder(C.THUMB_SEL_PX),
                                bg=C.CARD, bd=0, highlightthickness=0)
        self._entry = ttk.Entry(self, textvariable=self._var, width=1,
                                font=C.font(C.FONT_BODY))
        self._arrow = ttk.Button(self, text="▾", width=2,
                                 style="Arrow.TButton", command=self._toggle)

        self._avatar.grid(row=0, column=0, padx=(C.px(6), C.px(4)), pady=C.px(2))
        self._entry.grid(row=0, column=1, sticky="ew", pady=C.px(2))
        self._arrow.grid(row=0, column=2, padx=(C.px(2), C.px(4)), pady=C.px(2))
        self.columnconfigure(1, weight=1)

        self._var.trace_add("write", self._on_text)
        self._entry.bind("<FocusIn>", self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)
        self._entry.bind("<Down>", self._on_down)
        self._entry.bind("<Up>", self._on_up)
        self._entry.bind("<Prior>", lambda e: self._move(-8))
        self._entry.bind("<Next>", lambda e: self._move(8))
        self._entry.bind("<Return>", self._on_return)
        self._entry.bind("<Escape>", self._on_escape)
        self._entry.bind("<Tab>", self._on_tab)

    # -- 对外 API ------------------------------------------------------

    def get(self):
        return self._value

    @property
    def enabled(self):
        return self._enabled

    def set(self, value):
        """程序化设置。传 "" 或未知值则清空。"""
        item = next((i for i in self._items if i.value == value), None)
        self._commit(item, notify=False)

    def clear(self):
        self._commit(None, notify=False)

    def set_pool(self, provider):
        """设置"本题可选池"。provider() 返回允许出现的 Item 列表。"""
        self._pool_provider = provider

    def set_enabled(self, enabled, clear_if_disabled=True):
        """禁用时默认**清空**选中值, 这是对的, 不要改默认值。

        ban 位数量调小、开克隆模式时, 被禁用的槽位不该留着一个再也改不掉的
        陈旧值。全项目只有"随机抽取后的点击锁定"会传 clear_if_disabled=False
        —— 那时只是短暂冻结界面(3 秒), 清空等于把整块 BP 板抹掉。
        """
        if enabled == self._enabled:
            return
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self._entry.configure(state=state)
        self._arrow.configure(state=state)
        if enabled:
            self._avatar.configure(image=self._thumb_for(self._value))
        elif clear_if_disabled:
            self._commit(None, notify=False)
            self._avatar.configure(image=self.placeholder_image())
        # 不清空时什么都不做: 头像和输入框里的字原样留着, 只见变灰

    # -- 内部 ----------------------------------------------------------

    @staticmethod
    def placeholder_image():
        return THUMBS.placeholder(C.THUMB_SEL_PX)

    def _thumb_for(self, value):
        item = next((i for i in self._items if i.value == value), None)
        return THUMBS.sel_thumb(item) if item else self.placeholder_image()

    def _popup(self):
        return _Popup.get(self.winfo_toplevel())

    def _refresh_pool(self):
        """重新求值可选项。

        池由外部回调给出(同域里已被别的格子占用的会被排除在此之外),
        每次打开和每次输入都重算, 保证列表和"实际还能选什么"一致。
        """
        if self._pool_provider is None:
            self._pool = list(self._items)
        else:
            self._pool = list(self._pool_provider())

    def _toggle(self):
        if not self._enabled:
            return
        popup = self._popup()
        if popup.is_open_for(self):
            popup.close()
        else:
            self._entry.focus_set()
            self._open()

    def _open(self):
        if not self._enabled:
            return
        # 打字必须落在这个 Entry 上, 否则过滤不会发生。
        # _toggle/_on_focus_in 本来就会先聚焦, 这里再兜一次底。
        self._entry.focus_set()
        self._refresh_pool()
        self._filtered = list(self._pool)
        self._sel = 0 if self._filtered else -1
        self._suppress = True
        self._var.set("")
        self._suppress = False
        self._popup().show(self)

    def _on_focus_in(self, _event=None):
        if not self._enabled:
            return
        # 已有选中值时全选文本, 这样第一次按键就替换掉旧值,
        # 而不是拿着旧值去过滤(那样只会剩一条, 没法换选)。
        self._entry.select_range(0, "end")
        self._open()

    def _on_focus_out(self, _event=None):
        popup = self._popup()
        if popup.is_open_for(self):
            popup.close()

    def _on_popup_closed(self):
        """弹窗因点击外部/失焦而关闭, 把输入框恢复成已提交的值。"""
        self._suppress = True
        self._var.set(self._value)
        self._suppress = False

    def _on_text(self, *_args):
        if self._suppress:
            return
        # 弹窗可能是"打字打出来的"(此前已关闭), 所以这里也要重算池
        self._refresh_pool()
        query = self._var.get()
        self._filtered = [i for i in self._pool if item_matches(i, query)]
        self._sel = 0 if self._filtered else -1
        # show() 兼作"打开"和"刷新": 已打开时它只重定位并重绘。
        # 这里不判断 is_open_for, 因为输入本身就该让列表出现。
        self._popup().show(self)

    def _move(self, delta):
        if not self._filtered:
            return "break"
        self._sel = max(0, min(len(self._filtered) - 1, self._sel + delta))
        self._popup().move_highlight()
        return "break"

    def _on_down(self, _event=None):
        popup = self._popup()
        if not popup.is_open_for(self):
            self._open()
            return "break"
        return self._move(1)

    def _on_up(self, _event=None):
        if not self._popup().is_open_for(self):
            return "break"
        return self._move(-1)

    def _on_return(self, _event=None):
        if not self._filtered:
            return "break"
        idx = self._sel if 0 <= self._sel < len(self._filtered) else 0
        self._commit(self._filtered[idx])
        return "break"

    def _on_escape(self, _event=None):
        popup = self._popup()
        if popup.is_open_for(self):
            popup.close()
        else:
            self._commit(None)
        return "break"

    def _on_tab(self, _event=None):
        # 关闭弹窗但不吃掉 Tab, 让焦点正常前进
        popup = self._popup()
        if popup.is_open_for(self):
            popup.close()
        return None

    def _commit(self, item, notify=True):
        self._value = item.value if item else ""
        self._suppress = True
        self._var.set(self._value)
        self._suppress = False
        self._avatar.configure(image=self._thumb_for(self._value))
        popup = self._popup()
        if popup.is_open_for(self):
            popup.close()
        if notify and self._on_change:
            self._on_change(self._value)

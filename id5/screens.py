#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主窗口骨架与主页控制台。

布局: 一个 10 行 x 5 列的 grid, **每个单元格的直接子控件**都挂在 content 上,
不建"行 Frame"。行 Frame 会让各行的列宽各自计算, 五列必然对不齐;
统一交给 content 的 columnconfigure(uniform=...) 才能保证列列对齐。

16:9 是结构性保证: content 是固定宽高的 Frame 且关掉了尺寸传播,
所以任何子控件都不可能把窗口撑大。wm resizable(False, False) 拦不住这个。
"""

import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from . import config as C
from . import updater
from .roster import Roster, THUMBS
from .searchbox import SearchableAvatarDropdown, close_popup
from .state import AppState
from .sync import sync_all


# ---------------------------------------------------------------- 小控件

class Switch(tk.Canvas):
    """自绘胶囊开关, 绑定一个 BooleanVar。"""

    W, H = 54, 28

    def __init__(self, master, variable, command=None):
        self.w, self.h = C.px(self.W), C.px(self.H)
        super().__init__(master, width=self.w, height=self.h, bg=C.CARD,
                         highlightthickness=0, bd=0, takefocus=0)
        self.var = variable
        self._command = command
        self._enabled = True
        self.bind("<Button-1>", self._on_click)
        self.var.trace_add("write", lambda *_: self.redraw())
        self.redraw()

    def set_enabled(self, enabled, clear_if_disabled=True):
        """签名和 SearchableAvatarDropdown.set_enabled 保持一致。

        clear_if_disabled 在这里没有意义(开关没有"选中值"可清), 收下只是为了
        让 apply_rules()/锁定能用同一句 `set_enabled(False, clear_if_disabled=...)`
        对待所有交互控件, 不必按类型分叉。
        """
        enabled = bool(enabled)
        if enabled == self._enabled:
            return            # 没变化就别重画 —— apply_rules() 会调用得很频繁
        self._enabled = enabled
        self.redraw()

    def _on_click(self, _event=None):
        if not self._enabled:
            return
        self.var.set(not self.var.get())
        if self._command:
            self._command()

    def redraw(self):
        self.delete("all")
        w, h, r = self.w, self.h, self.h // 2
        on = bool(self.var.get())
        if not self._enabled:
            # 禁用时**也要区分开/关**。要是都画成灰色, 锁定那几秒里开着的
            # "克隆模式"看起来就是关着的, 直播时瞟一眼就会误判局面。
            color = C.SWITCH_ON_DISABLED if on else C.SWITCH_OFF_DISABLED
        else:
            color = C.SWITCH_ON if on else C.SWITCH_OFF
        # 胶囊底: 两个圆 + 中间矩形
        for x0 in (0, w - h):
            self.create_oval(x0, 0, x0 + h, h, fill=color, outline=color)
        self.create_rectangle(r, 0, w - r, h, fill=color, outline=color)
        # 滑块
        pad = max(1, C.px(2))
        d = h - 2 * pad
        x = (w - h + pad) if on else pad
        knob = C.SWITCH_KNOB if self._enabled else C.DISABLED_FG
        self.create_oval(x, pad, x + d, pad + d, fill=knob, outline="")


# ---------------------------------------------------------------- 换肤

def _retheme_tree(widget, mapping, seen):
    """按色值把一棵控件树改成新配色。

    mapping 是 {旧色: 新色}(由 config.use_theme 给出)。逐个控件把**所有**可
    配置选项读回来, 值命中映射就改掉。

    为什么是"读回色值"而不是"建控件时给每个控件打语义标签": 要标的控件有
    60 个左右、散在 7 个构建方法里, 漏标一个就是静默串色, 而且以后每加一个
    控件都得记得标。读回色值是全自动的 —— 代价是**控件颜色必须一律取自调色
    板**, 别再给控件写死颜色字面量。

    ttk 控件跳过: 它们的颜色在样式里, 重跑一遍 App._setup_style() 就够。

    **豁免牌**优先于一切: Tk 里 Toplevel 也是 root 的子控件, 所以这个函数会
    递归进直播窗口。它的配色是固定的黑底灰框, 不跟皮肤变 —— 直播窗口的
    Toplevel 上设了 `_theme_exempt`, 到这里就整棵子树都不走了。

    (另有一条: 直播窗口模块里**不许有叫 `redraw` 的方法**。`redraw` 在本项目
    里已经是"按调色板重画 canvas"的约定, 下面会无条件调用它。)
    """
    if getattr(widget, "_theme_exempt", False):
        return
    if id(widget) in seen:            # 同一个控件只走一遍, 否则链式映射会连跳
        return
    seen.add(id(widget))
    if not isinstance(widget, ttk.Widget):
        for opt in widget.keys():
            try:
                cur = widget.cget(opt)
            except tk.TclError:
                continue              # 该控件没有这个选项
            # isinstance 不能省: e.g. Spinbox 的 values 是元组, 元组不可哈希,
            # 直接 `cur in mapping` 会抛 TypeError
            if isinstance(cur, str) and cur in mapping:
                try:
                    widget.configure(**{opt: mapping[cur]})
                except tk.TclError:
                    pass
    if hasattr(widget, "redraw"):
        widget.redraw()               # Switch/_Popup 的颜色是画在 Canvas 上的
    for child in widget.winfo_children():
        _retheme_tree(child, mapping, seen)


# ---------------------------------------------------------------- 尺寸

def choose_size(root):
    """选第一个放得下当前屏幕的 16:9 尺寸。

    硬编码 1280x720 在 1366x768 上会被切掉底行(720+标题栏+任务栏 > 768),
    所以必须按实际屏幕挑。
    """
    sw = root.winfo_screenwidth() * C.SCREEN_FRACTION
    sh = root.winfo_screenheight() - C.SCREEN_RESERVE_H
    for w, h in C.SIZE_CANDIDATES:
        if w <= sw and h <= sh:
            return w, h
    return C.SIZE_CANDIDATES[-1]


# ---------------------------------------------------------------- 应用

# 自动弹更新日志前等多久。要等, 不能 immediate:
#   * 让主界面先画出来 —— 一开机就盖上来一个窗口, 看着像启动器出错了;
#   * 顺手给启动时那次静默检查留出完成的时间, 它的结果在列表接口失败时会
#     被拿来兜底(见 ChangelogWindow._on_error)。
CHANGELOG_DELAY_MS = 1200


class App:
    """顶层窗口 + 屏幕切换。目前只有主页控制台, 架构上留好加第二屏的余地。"""

    def __init__(self, size=None):
        self.base = C.base_dir()
        # 必须在 tk.Tk() 之前: Tk 创建时枚举一次系统字体, 之后注册就来不及了
        C.register_fonts()
        # 配色也得在建任何控件之前定好 —— 第一个控件一建出来就会读 C.BG
        self.settings = C.load_settings()
        C.use_theme(self.settings["theme"])
        self.root = tk.Tk()
        self.root.title(C.APP_TITLE)
        C.apply_icon(self.root)
        self.root.configure(bg=C.BG)

        w, h = size or choose_size(self.root)
        C.set_scale(w / C.DESIGN_W)
        self.root.geometry("%dx%d" % (w, h))
        self.root.resizable(False, False)

        self._setup_style()
        # 固定尺寸 + 关闭传播 = 子控件无法撑大窗口
        self.content = tk.Frame(self.root, width=w, height=h, bg=C.BG)
        self.content.grid_propagate(False)
        self.content.pack_propagate(False)
        self.content.pack(fill="both", expand=True)

        self.roster = Roster(self.base)
        THUMBS.warm(self.roster.all_items())

        self.state = AppState(self.root, self.settings)
        self.state.roster = self.roster
        self.state.show_note = self.show_note
        self.live_window = None      # 直播BP窗口, 由页脚按钮开关

        # ---- 检查更新 ----
        # 启动时**静默**查一次: 不弹任何东西, 结果只缓存在 update_info 里,
        # 设置窗打开时自己去读 —— 操作者很可能整场都不开设置窗, 那次查询就白
        # 做了, 但代价只是一个后台请求, 比每次启动弹个框好得多。
        self.update_info = None      # 最近一次**成功**的检查结果, 见 updater.check
        self.on_update_result = None # 检查结束后的回调(设置窗注册, 单例所以只一个)
        self._update_busy = False

        self.screen = None
        self.show_screen(HomeConsoleScreen)
        self.check_update_async()
        self.root.after(CHANGELOG_DELAY_MS, self._maybe_show_changelog)

    # -- 屏幕 ----------------------------------------------------------

    def show_screen(self, cls):
        close_popup()
        for child in self.content.winfo_children():
            child.destroy()
        self.screen = cls(self)

    def show_note(self, text, title="提示"):
        messagebox.showinfo(title, text, parent=self.root)

    # -- 检查更新 ------------------------------------------------------

    @property
    def update_checking(self):
        """是否正在查。设置窗用它决定"正在检查…"还是读缓存的结果。"""
        return self._update_busy

    def check_update_async(self):
        """后台问一次 GitHub 有没有新版本。已经有一次在查就直接返回 False。

        启动时那次和设置窗的按钮共用一个实现。结果走**队列 + after 轮询**回到
        主线程再交给回调 —— 和工作线程里碰控件相比, 这是唯一稳的做法(Tk 不是
        线程安全的, 运气好时看着也能跑, 那是因为 GIL 恰好在正确的时刻切换)。
        """
        if self._update_busy:
            return False
        self._update_busy = True
        q = queue.Queue()

        def worker():
            try:
                q.put(updater.check())
            except updater.UpdateError as e:
                q.put({"error": str(e)})
            except Exception:
                # 兜底: 后台线程里漏出去的异常没人接, 结果是按钮永远停在
                # "正在检查…"上 —— 比报个错难查得多。
                q.put({"error": "检查更新失败：%s"
                                % traceback.format_exc(limit=1)})

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(120, lambda: self._poll_update(q))
        return True

    def _poll_update(self, q):
        try:
            payload = q.get_nowait()
        except queue.Empty:
            try:
                if self.root.winfo_exists():
                    self.root.after(120, lambda: self._poll_update(q))
            except tk.TclError:
                pass                       # 窗口已经没了, 丢掉这次结果
            return

        self._update_busy = False
        # 失败时**不覆盖**上一次成功的结果: 启动时那次多半是好的, 手动点这次
        # 恰好断网, 不该顺手把"有新版本"那个结论一起抹掉。
        if not payload.get("error"):
            self.update_info = payload
        cb = self.on_update_result
        if cb is not None:
            cb(payload)

    # -- 更新日志 ------------------------------------------------------

    def _maybe_show_changelog(self):
        """更新后第一次启动, 自动弹一次更新日志。

        判据只有一条: settings 里"看过的版本"和当前版本不一致。所以**全新装机
        也会弹** —— 那时 settings.json 里根本没这个字段。这是有意的: 对刚装好
        的人来说"这一版有什么"同样是有效信息; 为此再加一套"算不算新装"的判定,
        只会多出一条永远说不清的边界。

        这里**不预先记账**(不先把 seen_version 写成当前版本再开窗): 记账在
        ChangelogWindow._fill 里, 内容真拿到了才写。否则断网启动一次就把这一版
        标成已读, 而用户其实什么都没看到。
        """
        if self.settings.get("seen_version") == C.APP_VERSION:
            return
        # 延迟导入, 同 settings_window._open_rule_ban 那条理由: 模块级互相 import
        # 会成环。这里还额外省掉了**每次启动**都要 import 一次 tk.Text/webbrowser
        # 这些只有看日志才用得上的东西。
        from .changelog_window import ChangelogWindow
        ChangelogWindow.open(self, C.APP_VERSION, auto=True)

    def mark_changelog_seen(self):
        """记下"当前版本的更新日志已经看过了"。由 ChangelogWindow 在显示成功时调。

        写盘失败(目录只读等)只意味着下次启动还会弹一遍, 不是错误 ——
        save_settings 自己会吞掉 OSError, 这里没必要再兜一层。
        """
        if self.settings.get("seen_version") == C.APP_VERSION:
            return
        self.settings["seen_version"] = C.APP_VERSION
        C.save_settings(self.settings)

    # -- 换肤 ----------------------------------------------------------

    def apply_theme(self, name):
        """切换白天/黑夜皮肤, 并**当场**让主窗口和设置窗口都变过来。

        顺序不能反: 先 use_theme() 定调色板, 再 _setup_style() 配样式。
        反过来样式会读到旧颜色 —— 而且不报任何错, 是唯一一个静默的坑。
        """
        mapping = C.use_theme(name)
        self.settings["theme"] = name
        C.save_settings(self.settings)       # 改了就记住, 下次启动沿用
        self._setup_style()

        seen = set()
        _retheme_tree(self.root, mapping, seen)
        # 设置窗口是 Toplevel, 正常情况下已经在 root 的子树里了; 这里补一道
        # 兜底。和上面**共用 seen** —— 同一个控件走两遍会串色: 链式映射
        # (#3b82f6→#2563eb, #2563eb→#1d4ed8)连跳两格就跑到别的颜色上去了。
        from .settings_window import SettingsWindow    # 延迟导入, 避免成环
        win = SettingsWindow._instance
        if win is not None and win.winfo_exists():
            _retheme_tree(win, mapping, seen)
        return mapping

    # -- ttk 主题 ------------------------------------------------------

    def _setup_style(self):
        """必须用 clam。Windows 默认的 vista 主题会**静默忽略**
        background/fieldbackground, 深色配色会变成浅灰且不报任何错。

        换肤时会重跑这个函数, 而 theme_use("clam") 会把全部 clam 样式重置回
        默认值 —— 所以**样式只能在这里配**, 别在别处 set 样式, 否则换一次肤
        就被抹掉了。
        """
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure("Card.TFrame", background=C.CARD)

        style.configure("TButton", background=C.BTN_BG, foreground=C.FG,
                        bordercolor=C.BORDER, focuscolor=C.BTN_BG,
                        font=C.font(C.FONT_BUTTON), padding=(C.px(10), C.px(6)),
                        relief="flat")
        style.map("TButton",
                  background=[("pressed", C.ACCENT_DARK), ("active", C.BTN_HOVER),
                              ("disabled", C.CARD)],
                  foreground=[("disabled", C.DISABLED_FG)],
                  bordercolor=[("disabled", C.BORDER)])

        style.configure("Accent.TButton", background=C.ACCENT,
                        foreground=C.ON_ACCENT, bordercolor=C.ACCENT,
                        focuscolor=C.ACCENT)
        style.map("Accent.TButton",
                  background=[("pressed", C.ACCENT_DARK), ("active", C.ACCENT_DARK),
                              ("disabled", C.CARD)],
                  foreground=[("disabled", C.DISABLED_FG)])

        style.configure("Danger.TButton", background=C.BTN_BG, foreground=C.DANGER,
                        bordercolor=C.BORDER, focuscolor=C.BTN_BG)
        style.map("Danger.TButton",
                  background=[("pressed", C.ACCENT_DARK), ("active", C.BTN_HOVER),
                              ("disabled", C.CARD)],
                  foreground=[("disabled", C.DISABLED_FG)])

        style.configure("Arrow.TButton", padding=(C.px(2), C.px(2)),
                        font=C.font(C.FONT_ARROW))

        # clam 的输入框边框是用 lightcolor/darkcolor 画的浮雕, 不设的话
        # 会在深色卡片上留一圈很亮的白边。
        for name in ("TEntry", "TSpinbox"):
            style.configure(name, fieldbackground=C.ENTRY_BG, foreground=C.FG,
                            bordercolor=C.BORDER, lightcolor=C.BORDER,
                            darkcolor=C.BORDER, insertcolor=C.FG,
                            arrowcolor=C.FG, background=C.CARD,
                            selectbackground=C.ACCENT,
                            selectforeground=C.ON_ACCENT,
                            padding=C.px(4))
            style.map(name,
                      fieldbackground=[("disabled", C.CARD),
                                       ("readonly", C.ENTRY_BG)],
                      foreground=[("disabled", C.DISABLED_FG)],
                      bordercolor=[("focus", C.ACCENT)],
                      lightcolor=[("focus", C.ACCENT)],
                      darkcolor=[("focus", C.ACCENT)],
                      arrowcolor=[("disabled", C.DISABLED_FG)])

        # 滑块要比槽底明显, 否则 36 个监管者的列表看不出还能滚
        style.configure("Vertical.TScrollbar", background=C.BORDER,
                        troughcolor=C.POPUP_BG, bordercolor=C.POPUP_BG,
                        arrowcolor=C.FG_DIM, lightcolor=C.BORDER,
                        darkcolor=C.BORDER)
        style.map("Vertical.TScrollbar",
                  background=[("active", C.FG_DIM), ("pressed", C.FG_DIM)])


# ---------------------------------------------------------------- 主页

class HomeConsoleScreen:
    """主页控制台: 10 行 x 5 列。"""

    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.content = app.content
        self.state = app.state
        self.roster = app.roster

        self._live_btn = None
        self._update_btn = None
        self._status = None

        for col in range(C.COLS):
            self.content.columnconfigure(col, weight=1, uniform="col")
        # 行高**不均分**: 下拉行里的头像+输入框比开关行、按钮行高得多,
        # 十行等分会让下拉行差几个像素而把最后一行挤出窗口。
        # 下拉行吃掉全部余量, 其余行只按自身需要的高度来。
        for row in range(C.ROWS):
            if row in C.DROPDOWN_ROWS:
                self.content.rowconfigure(row, weight=1, uniform="drow")
            else:
                self.content.rowconfigure(row, weight=0)

        self._build_row0()
        self._build_map_row()
        self._build_ban_rows()
        self._build_pick_row()
        self._build_pick_buttons()
        self._build_gban_rows()
        self._build_actions()
        self._build_footer()
        self._bind_pools()

        self.state.apply_rules()

    # -- 候选项约束 ----------------------------------------------------

    def _bind_pools(self):
        """把三组互斥的格子接上"可选池"回调。

        必须等所有格子都建完才能做 —— 域是跨行构造的
        (监管者域 = 第 2-3 行 + 第 4 行第 5 位 + 第 6-7 行第 5 位)。
        """
        st = self.state
        hunters = list(st.ban_boxes) + [st.pick_boxes[4]]
        hunters += [st.gban_boxes[r * C.COLS + C.GBAN_HUNTER_COL] for r in range(2)]
        survivors = list(st.pick_boxes[:4])
        survivors += [st.gban_boxes[r * C.COLS + c] for r in range(2)
                      for c in C.GBAN_SURVIVOR_COLS]
        maps = [st.map_box] + list(st.map_ban_boxes)

        for group, peers in (("hunter", hunters),
                             ("survivor", survivors),
                             ("map", maps)):
            for box in peers:
                box.set_pool(lambda b=box, g=group, ps=peers:
                             st.pool_for(b, g, ps))

    # -- 单元格工厂 ----------------------------------------------------

    def _interactive(self, widget):
        """登记一个"能点"的控件, 并把它返回。

        **凡是在这个界面上能点的控件都必须走这里**, 因为 apply_rules() 第 1 步
        会把 lock_widgets 里的控件全部置为可用, 再由规则决定谁该禁用。漏登记的
        后果是: 规则禁用不了它, 锁定期间它照样能点。
        """
        self.state.lock_widgets.append(widget)
        return widget

    def _card(self, row, col, caption="", columnspan=1, dim=False):
        """建一个卡片单元格, 返回可以往里放控件的容器。"""
        card = tk.Frame(self.content, bg=C.CARD)
        card.grid(row=row, column=col, columnspan=columnspan,
                  sticky="nsew", padx=C.px(4), pady=C.px(2))
        if caption:
            tk.Label(card, text=caption, bg=C.CARD,
                     fg=C.DISABLED_FG if dim else C.FG_DIM,
                     font=C.font(C.FONT_CAPTION), anchor="w").pack(
                fill="x", padx=C.px(8), pady=(C.px(2), 0))
        return card

    def _dropdown(self, row, col, caption, items):
        body = self._card(row, col, caption)
        box = SearchableAvatarDropdown(body, items)
        box.pack(fill="x", padx=C.px(5), pady=(C.px(1), C.px(2)))
        return self._interactive(box)

    # -- 第 0 行: 开关 -------------------------------------------------

    def _build_row0(self):
        specs = (
            ("克隆模式", self.state.clone_mode, True, None),
            ("地图随机", self.state.map_random, True, None),
            ("天赋随机（待开发）", self.state.talent_random, False, None),
            ("区域选择随机（待开发）", self.state.region_random, False, None),
        )
        for col, (caption, var, enabled, _cmd) in enumerate(specs):
            card = self._card(C.ROW_TOGGLES, col, caption, dim=not enabled)
            sw = Switch(card, var)
            sw.pack(anchor="w", padx=C.px(8), pady=C.px(4))
            self._interactive(sw)
            if not enabled:
                # 待开发的占位开关。不能在这里 set_enabled(False) 设死 ——
                # apply_rules() 第 1 步会把它们重新启用, 得交给 _apply_stubs。
                self.state.stub_switches.append(sw)

        # 第 5 格: ban 位数量
        card = self._card(C.ROW_TOGGLES, 4, "监管者ban位数量（0-10）")
        spin = ttk.Spinbox(card, from_=C.BAN_COUNT_MIN, to=C.BAN_COUNT_MAX,
                           textvariable=self.state.ban_count, width=4,
                           font=C.font(C.FONT_BODY), justify="center",
                           validate="key",
                           validatecommand=(self.root.register(_valid_ban_count), "%P"))
        spin.pack(anchor="w", padx=C.px(8), pady=C.px(4))
        self._interactive(spin)

    # -- 第 2-3 行: 监管者 ban -----------------------------------------

    def _build_ban_rows(self):
        for i in range(C.BAN_SLOTS):
            row = C.ROW_BAN_START + i // C.COLS
            col = i % C.COLS
            box = self._dropdown(row, col, "监管者Ban位 %d" % (i + 1),
                                 self.roster.groups["hunter"])
            self.state.ban_boxes.append(box)

    # -- 第 4 行: 本局选择 ---------------------------------------------

    def _build_pick_row(self):
        groups = (self.roster.groups["survivor"],) * 4 + \
                 (self.roster.groups["hunter"],)
        for col, (caption, items) in enumerate(zip(C.PICK_LABELS, groups)):
            box = self._dropdown(C.ROW_PICK, col, caption, items)
            self.state.pick_boxes.append(box)

    # -- 第 5 行: 随机按钮 ---------------------------------------------

    def _build_pick_buttons(self):
        for col in range(C.COLS):
            card = self._card(C.ROW_PICK_BTN, col)
            btn = ttk.Button(card, text="随机选择",
                             command=lambda i=col: self._random_pick(i))
            btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
            self.state.pick_buttons.append(self._interactive(btn))

    def _random_pick(self, index):
        if index == 4:
            ok = self.state.random_hunter()
        else:
            ok = self.state.random_survivor(index)
        if ok:
            # 抽到了才锁: 失败要弹提示框, 那时候不该有"动画正在播"这回事
            self.state.lock_clicks()
        else:
            self.app.show_note("没有可选的候选角色（可能都已被 ban）。", "随机选择")

    # -- 第 1 行: 地图 ------------------------------------------------

    def _build_map_row(self):
        box = self._dropdown(C.ROW_MAP, C.MAP_COL_DROPDOWN, "本局地图",
                             self.roster.groups["map"])
        self.state.map_box = box

        card = self._card(C.ROW_MAP, C.MAP_COL_RANDOM)
        btn = ttk.Button(card, text="随机选择", command=self._random_map)
        btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
        # 交给 apply_rules() 按"地图随机"开关决定可不可点
        self.state.map_button = self._interactive(btn)

        # 中间第 2 列留空, 让两个地图 ban 位靠右
        for col, n in ((C.MAP_COL_BAN1, 1), (C.MAP_COL_BAN2, 2)):
            ban = self._dropdown(C.ROW_MAP, col, C.MAP_BAN_CAPTION % n,
                                 self.roster.groups["map"])
            self.state.map_ban_boxes.append(ban)

    def _random_map(self):
        if self.state.random_map():
            self.state.lock_clicks()
        else:
            self.app.show_note("没有可选的地图（可能都已被 ban）。", "随机选择")

    # -- 第 6-7 行: 全局 ban ------------------------------------------

    def _build_gban_rows(self):
        for i in range(C.GBAN_SLOTS):
            row = C.ROW_GBAN_START + i // C.COLS
            col = i % C.COLS
            if col == C.GBAN_HUNTER_COL:
                caption = "全局Ban位 %d（监管）" % (i + 1)
                items = self.roster.groups["hunter"]
            else:
                caption = "全局Ban位 %d（求生）" % (i + 1)
                items = self.roster.groups["survivor"]
            box = self._dropdown(row, col, caption, items)
            self.state.gban_boxes.append(box)

    # -- 第 8 行: 下一局 / 重置 ----------------------------------------

    def _build_actions(self):
        card = self._card(C.ROW_ACTIONS, 0, columnspan=3)
        next_btn = ttk.Button(card, text="下一局", style="Accent.TButton",
                              command=self._next_round)
        next_btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
        self._interactive(next_btn)

        card = self._card(C.ROW_ACTIONS, 3, columnspan=2)
        reset_btn = ttk.Button(card, text="重置", style="Danger.TButton",
                               command=self._reset)
        reset_btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
        self._interactive(reset_btn)

    def _next_round(self):
        note = self.state.record_round()
        if note:
            self.app.show_note(note, "下一局")

    def _reset(self):
        ok = messagebox.askyesno("重置", "确定要清空除第一行以外的所有内容吗？",
                                 parent=self.root)
        if ok:
            self.state.reset()

    def _toggle_live(self):
        """开/关直播BP窗口。"""
        live = self.app.live_window
        if live is not None and live.alive:
            live.close()
            return
        from .live_window import LiveWindow      # 延迟导入, 避免成环
        try:
            self.app.live_window = LiveWindow(self.app, on_close=self._live_closed)
        except Exception:
            self.app.live_window = None
            self.app.show_note("直播窗口打不开：\n\n%s" % traceback.format_exc(),
                               "直播BP界面")
            return
        self._live_set_text("关闭直播bp界面")

    def _live_closed(self):
        """直播窗口自己关掉时(右键/Escape/程序内 close)回调。"""
        self.app.live_window = None
        self._live_set_text("打开直播bp界面")

    def _live_set_text(self, text):
        # 窗口可能是上一屏留下的死控件(show_screen 会 destroy 掉), 要兜住
        try:
            if self._live_btn is not None and self._live_btn.winfo_exists():
                self._live_btn.configure(text=text)
        except tk.TclError:
            pass

    # -- 第 9 行: 直播BP / 检查更新 ------------------------------------

    def _build_footer(self):
        # 第 0-2 列: 直播BP界面开关
        card = self._card(C.ROW_FOOTER, 0, columnspan=3)
        self._live_btn = ttk.Button(card, text="打开直播bp界面",
                                    command=self._toggle_live)
        self._live_btn.pack(fill="both", expand=True,
                            padx=C.px(6), pady=C.px(6))
        # 走 _interactive 登记(不变量: 能点的控件都得在 lock_widgets 里), 这样
        # apply_rules() 第 1 步会负责把它恢复成可用 —— 游离在外的话解锁后没人管。
        self._interactive(self._live_btn)
        # 但**豁免点击锁定**: 刚抽完签那 3 秒里操作者必须还能把直播窗口关掉/
        # 打开, 不然画面出问题就只能干等。
        self.state.lock_exempt.append(self._live_btn)

        # 第 3 列: 检查角色更新 + 状态提示。
        # 按钮 fill="both" + expand 才会像左右两格那样撑满整个格子; 只写
        # fill="x" 的话它只占一行高, 下面空一大块, 看着像没填满。
        # 状态提示**有字才占位置**(见 _set_status): 空 Label 也占一行高, 会让
        # 这个按钮永远比左右两个矮一截。
        card = self._card(C.ROW_FOOTER, 3)
        self._update_btn = ttk.Button(card, text="检查角色更新",
                                      command=self._check_update)
        self._update_btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
        self.state.update_button = self._interactive(self._update_btn)
        self._status = tk.Label(card, text="", bg=C.CARD, fg=C.FG_DIM,
                                font=C.font(C.FONT_SMALL), anchor="w")

        # 第 4 列: 设置(右下角)
        card = self._card(C.ROW_FOOTER, 4)
        btn = ttk.Button(card, text="设置", command=self._open_settings)
        btn.pack(fill="both", expand=True, padx=C.px(6), pady=C.px(6))
        self._interactive(btn)

    def _set_status(self, text):
        """更新状态提示。空串 = 收起来, 把整格高度让给上面的按钮。

        别直接 _status.configure(): 空 Label 照样占一行高, 于是"检查角色更新"
        永远比页脚另外两个按钮矮一截, 底下一块死白, 看着就像没填满格子。
        """
        self._status.configure(text=text)
        if text:
            if not self._status.winfo_manager():
                self._status.pack(fill="x", padx=C.px(8))
        else:
            self._status.pack_forget()

    def _open_settings(self):
        # 延迟导入: settings_window 要用本模块的 Switch, 模块级互相 import 会成环
        from .settings_window import SettingsWindow
        SettingsWindow.open(self.app)

    def _check_update(self):
        """在后台线程跑同步, 主线程只轮询队列 —— 网络慢时窗口不能卡死。"""
        if self.state.syncing:
            return
        self.state.syncing = True
        self._update_btn.configure(text="检查中…")   # 文字不属于"可用性", 直接设
        self.state.apply_rules()                    # 可用性一律走规则
        self._set_status("正在连接 wiki…")

        q = queue.Queue()

        def worker():
            try:
                result = sync_all(progress=lambda t: q.put(("progress", t)))
            except Exception:
                result = {"error": traceback.format_exc()}
            q.put(("done", result))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(120, lambda: self._poll_sync(q))

    def _poll_sync(self, q):
        try:
            while True:
                kind, payload = q.get_nowait()
                if kind == "progress":
                    self._set_status(payload)
                else:
                    self._finish_sync(payload)
                    return
        except queue.Empty:
            pass
        self.root.after(120, lambda: self._poll_sync(q))

    def _finish_sync(self, result):
        self.state.syncing = False
        self._update_btn.configure(text="检查角色更新")
        self.state.apply_rules()

        if result.get("error"):
            self._set_status("更新失败")
            messagebox.showerror("检查角色更新", result["error"],
                                 parent=self.root)
            return

        images = result.get("images", 0)
        failed = result.get("failed", [])
        new_names = result.get("new_names", [])

        if images:
            # 列表对象是原地更新的, 下拉菜单共享同一引用, 无需逐个通知
            self.roster.reload()
            THUMBS.warm(self.roster.all_items())

        if not images and not failed:
            self._set_status("已是最新，无需更新")
            self.app.show_note("已是最新，无需更新。", "检查角色更新")
            return

        msg = "更新了 %d 张图片（涉及 %d 个角色）" % (images, result.get("chars", 0))
        if new_names:
            msg += "\n\n新增角色：\n" + "、".join(new_names)
        extras = result.get("extras", [])
        if extras:
            names = [os.path.basename(p) for p in extras]
            msg += "\n\n本地有 %d 张图在 wiki 上已找不到对应角色（未删除）：\n%s" % (
                len(names), "、".join(names[:10]))
        if failed:
            msg += "\n\n失败 %d 项：\n" % len(failed) + "\n".join(failed[:10])
            if len(failed) > 10:
                msg += "\n…（其余 %d 项见控制台）" % (len(failed) - 10)

        self._set_status("更新了 %d 张图片，%d 个角色"
                         % (images, result.get("chars", 0)))
        messagebox.showinfo("检查角色更新", msg, parent=self.root)


def _valid_ban_count(proposed):
    """Spinbox 校验: 只允许 0-10 的整数(允许中间态的空串)。"""
    if proposed == "":
        return True
    if not proposed.isdigit():
        return False
    return int(proposed) <= C.BAN_COUNT_MAX

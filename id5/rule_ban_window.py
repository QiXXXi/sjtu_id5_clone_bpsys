#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则禁用窗: 勾选哪些角色**本场比赛不允许出现**。

比赛规则会要求把某些新角色排除掉。被禁用的角色两端都堵死: 既不会被随机到
(AppState._pool), 也不会出现在任何下拉候选里(AppState.pool_for), 已经选在
格子上的还会被清掉(AppState._apply_rule_banned)。所以本窗口保存时走的是
set_rule_banned(), 由它去调 apply_rules() —— 这里不是"改个随机池", 是改一条
规则。

## 为什么是普通 Toplevel

和 settings_window 同款: 带标题栏的窗口由窗口管理器正常管辖, 不存在
`overrideredirect(True)` 那条"被主窗口盖住"的问题。所以这里**不要**出现
overrideredirect, 也**不要**加 -topmost —— 它不需要浮在所有东西上面。

## 为什么整块画在一个 Canvas 上

88 个角色 = 18 行, 窗口只有一屏高, 必须滚动。用 Canvas + 图元:

  * 边框就是 itemconfigure(outline=...) 一处, 不用给 88 个 Frame 逐个改 bg;
  * 滚动只是 yview, 不用"把 176 个控件塞进一个 canvas window 再跟着动";
  * 换肤时图元的色值映射碰不到(见下面 redraw()), 逻辑集中在一个函数里。

代价是点击要靠 tag_bind, 而不是每个格子自己的 command。

## 工作副本

编辑的是一份**副本**(self._banned), 点「保存」才交给 state。所以关窗(X)、
按 Esc、点「取消」都等于放弃这次改动 —— 那些不是"没实现", 是本来就该这样。
"""

import tkinter as tk
from tkinter import ttk

from . import character_order
from . import config as C
from .roster import THUMBS

# 版式。**故意留在本模块而不是 config**: 这几个数只有这一个窗口用, 而 config
# 那份是跨模块共享的(它有专门一节防 LIVE_* / 版式常量撞名)。settings_window
# 里的间距也是直接写 C.px(16) 这样的字面量, 同一套做法。
COLS = 5              # 每行 5 个(规格)
SIDE = 140            # 头像边长
GAP = 16              # 格子间距
PAD = 16              # 网格四周的内边距
BORDER_W = 3          # 边框粗细


class RuleBanWindow(tk.Toplevel):
    """单例。重复 open() 只把已开的那个唤到前面。"""

    _instance = None

    @classmethod
    def open(cls, app, on_save=None):
        win = cls._instance
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_set()
            return win
        cls._instance = cls(app, on_save)
        return cls._instance

    def __init__(self, app, on_save=None):
        super().__init__(app.root)
        self.app = app
        self.state = app.state
        # 保存后的回调。设置窗口靠它刷新按钮下面那排预览 —— 本窗口改的是
        # state, 而预览是设置窗口的控件, 那边不会自己知道。
        self._on_save = on_save

        # 工作副本。从 state 拷一份过来, 之后随便点, 保存前不动真的。
        self._banned = set(self.state.rule_banned)

        self.title("规则禁用")
        self.configure(bg=C.BG)
        self.transient(app.root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._close)

        # 角色的显示顺序、以及每个名字属于哪一组(取头像要用)。
        self._groups = {}
        for group in ("survivor", "hunter"):
            for item in app.roster.groups[group]:
                self._groups[item.value] = group
        self._order = character_order.newest_first(self._groups)

        # name -> (矩形图元 id, 图片图元 id)
        self._cells = {}
        # 画布实际宽度, 由 <Configure> 填。0 = 还不知道(还没映射), _place 会
        # 退回问 winfo_width()。
        self._canvas_w = 0
        # name -> PhotoImage。**必须一直拿着**: canvas 只存图片名不存 Python
        # 引用, 被 GC 回收后那一格会静默变空白(roster 模块头也记着这条)。
        self._photos = {}

        self._place_over_parent()
        self._build()
        self._draw_grid()

    # -- 位置 ----------------------------------------------------------

    def _place_over_parent(self):
        """和设置窗口一样大、一样居中。"""
        w, h = C.SETTINGS_SIZE
        pw = self.app.root.winfo_width()
        ph = self.app.root.winfo_height()
        w, h = min(w, pw), min(h, ph)
        x = self.app.root.winfo_rootx() + (pw - w) // 2
        y = self.app.root.winfo_rooty() + (ph - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # -- 构建 ----------------------------------------------------------

    def _build(self):
        # 三个区的 pack 顺序是**页眉 → 页脚 → 内容**, 不是从上往下的自然顺序。
        # 窗口尺寸是定死的 1024x576(和设置窗一样大), 而里面的东西按 C.px() 放大
        # —— 这台机器 DPI 1.75、缩放 1.11, 高度本来就紧。Tk 的 pack 在空间不够
        # 时是**从最后 pack 的那个开始裁**的, 所以页脚要是最后 pack, 一超就被压
        # 成一条缝(实测按钮只剩 2px 高)。页眉页脚先各自拿到自己的高度, 画布放
        # 最后用 expand 吃掉余量 —— 它本来就要滚动, 少几像素无所谓。
        #
        # 顺序管的是**裁切优先级**, side 才管它切哪一边: 页脚写 side="top" 会
        # 紧贴着页眉出现(按钮跑到网格**上面**), 顺序看着还对, 量 y 坐标才发现。
        # 所以页脚必须是 side="bottom"。
        head = tk.Frame(self, bg=C.BG)
        head.pack(side="top", fill="x", padx=C.px(PAD), pady=(C.px(12), C.px(6)))
        tk.Label(head, text="规则禁用", bg=C.BG, fg=C.FG,
                 font=C.font(C.FONT_CAPTION), anchor="w").pack(fill="x")
        tk.Label(head,
                 text="点击头像切换禁用状态：红框 = 已禁用，灰框 = 未禁用。\n"
                      "被禁用的角色不会出现在任何选择列表里，已经选上的会被清掉。",
                 bg=C.BG, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                 anchor="w", justify="left").pack(fill="x", pady=(C.px(4), 0))

        foot = tk.Frame(self, bg=C.BG)
        foot.pack(side="bottom", fill="x", padx=C.px(PAD), pady=C.px(12))
        ttk.Button(foot, text="保存", command=self._save).pack(side="right")
        ttk.Button(foot, text="取消", command=self._close).pack(
            side="right", padx=(0, C.px(10)))
        self._count = tk.Label(foot, text="", bg=C.BG, fg=C.FG_DIM,
                               font=C.font(C.FONT_SMALL), anchor="w")
        self._count.pack(side="left")
        self._refresh_count()

        holder = tk.Frame(self, bg=C.CARD)
        holder.pack(side="top", fill="both", expand=True, padx=C.px(PAD))

        # height=1 是**必要的**, 不是随手写的: Canvas 不写 -height 时 Tk 的默认
        # 值是 7cm —— 物理厘米, 跟着 DPI 走。这台机器上算出来 463px, 光它一个
        # 就快把 576 高的窗口占满, 于是三个区的**请求高度**加起来(614)超过窗口,
        # 才触发了上面那条"裁最后 pack 的"。它反正会被 expand 撑满, 给自己报个
        # 1px 才是诚实的。
        self._canvas = tk.Canvas(holder, bg=C.CARD, highlightthickness=0, bd=0,
                                 height=1)
        bar = ttk.Scrollbar(holder, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=bar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        # 滚轮。Windows 上 delta 是 120 的倍数; 不乘就用系统默认行数,
        # 这里显式乘 3 —— 一屏只看得下两行多, 一次滚一行太慢。
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(
                              -3 * (e.delta // 120), "units"))

        # 水平居中不能在 _build() 里算一次就算完: 那时窗口还没映射, 画布的
        # winfo_width() 报的是 1, 居中的结果会退化成"贴着左边" —— 而且看不出
        # 是算错了, 只像"没居中"。所以等 <Configure> 报出真实宽度再摆位置。
        self._canvas.bind("<Configure>", self._on_canvas_configure)

    # -- 绘制 ----------------------------------------------------------

    def _draw_grid(self):
        side, pad = C.px(SIDE), C.px(PAD)
        bw = max(1, C.px(BORDER_W))
        for i, name in enumerate(self._order):
            row, col = divmod(i, COLS)
            tag = "cell:%s" % name
            item = self.app.roster.lookup(name)
            photo = THUMBS.square(item, self._groups[name], side, C.CARD) \
                if item is not None else None
            if photo is None:
                img = None
            else:
                self._photos[name] = photo
                # 图片先建、矩形后建, **顺序是有意的**: 矩形的描边是以边界线
                # 为中心画的(内外各一半), 图片压在它上面就会吃掉内侧那一半,
                # 3px 的框看起来只有 1.5px。反过来画, 整条边才在外。
                img = self._canvas.create_image(0, 0, image=photo, tags=(tag,))
            rect = self._canvas.create_rectangle(
                0, 0, 0, 0, outline=self._border(name), width=bw, tags=(tag,))
            self._cells[name] = (rect, img)
            # 绑在 tag 上而不是逐个 create_*: 格子里的矩形和图片是两个图元,
            # 点在哪一个上都该算点中了这一格(矩形没填色, 中间那点其实命中图片)。
            self._canvas.tag_bind(tag, "<Button-1>",
                                  lambda _e, n=name: self._toggle(n))
        # 真实位置等 _on_canvas_configure; 这里先摆一遍, 免得映射前的第一帧
        # 所有图元都挤在左上角。
        self._place()

    def _on_canvas_configure(self, event):
        if event.width == self._canvas_w:
            return
        self._canvas_w = event.width
        self._place()

    def _place(self):
        """按当前画布宽度把网格居中摆好, 并更新 scrollregion。"""
        side, gap, pad = C.px(SIDE), C.px(GAP), C.px(PAD)
        cell = side + gap
        grid_w = COLS * side + (COLS - 1) * gap
        cw = self._canvas_w or self._canvas.winfo_width()
        # 画布比网格窄(小屏上 C.px 把内容压小了, 但窗口还是 1024)时靠左兜住:
        # 宁可右边留空, 也不能让第一列被切掉半边。
        #
        # **不要再加 pad**: grid_w 已经是含间距的**视觉宽度**(最后一格右边没有
        # 间距), 所以 (cw - grid_w) // 2 本身就是两边等距的左边距; 再加一份 pad
        # 会把整块往右推 pad 那么多 —— 左边缝 78、右边缝 43, 看着就是"没居中"。
        x0 = max(pad, (cw - grid_w) // 2)

        for i, name in enumerate(self._order):
            row, col = divmod(i, COLS)
            x = x0 + col * cell
            y = pad + row * cell
            rect_id, img_id = self._cells[name]
            self._canvas.coords(rect_id, x, y, x + side, y + side)
            if img_id is not None:
                # w // 2 不是 w / 2: 奇数边长时后者会让每行差一像素地抖。
                self._canvas.coords(img_id, x + side // 2, y + side // 2)

        rows = (len(self._order) + COLS - 1) // COLS
        total = pad * 2 + rows * side + max(0, rows - 1) * gap
        self._canvas.configure(scrollregion=(0, 0, max(cw, grid_w), total))

    def _border(self, name):
        """边框色。**红 = 已禁用, 灰 = 未禁用**(规格), 两个都是调色板里的值,
        换肤才带得动。"""
        return C.DANGER if name in self._banned else C.BORDER

    # -- 交互 ----------------------------------------------------------

    def _toggle(self, name):
        if name in self._banned:
            self._banned.discard(name)
        else:
            self._banned.add(name)
        rect_id = self._cells.get(name, (None,))[0]
        if rect_id is not None:
            # 只改这一个图元的边框 —— 整格重画没必要, 而且会打断鼠标的
            # "按在哪一格上"的判定。
            self._canvas.itemconfigure(rect_id, outline=self._border(name))
        self._refresh_count()

    def _refresh_count(self):
        self._count.configure(text="已禁用 %d 个" % len(self._banned))

    # -- 收尾 ----------------------------------------------------------

    def _save(self):
        self.state.set_rule_banned(self._banned)
        cb = self._on_save
        self._close()
        # 先关窗再回调: 回调要刷新的是**设置窗口**的预览, 与本窗口的存亡无关;
        # 但它可能反过来碰本窗口(现在不会), 顺序上先关更不容易绕成环。
        if cb is not None:
            cb()

    def _close(self):
        RuleBanWindow._instance = None
        self.destroy()

    # -- 换肤 ----------------------------------------------------------

    def redraw(self):
        """换肤时 screens._retheme_tree 会调这个(项目里 `redraw` 就是这个约定)。

        画布上的图元不是控件, _retheme_tree 的色值映射只能改**控件的选项**,
        碰不到它们, 所以这一节得自己来:

          * 头像烘死在"卡片底色"上, 底色一换必须**重合成** —— 沿用旧图的话,
            每一格周围会留一圈旧底色的方框;
          * 边框色 C.DANGER / C.BORDER 此刻已经换成新值, 逐格重刷;
          * 画布自身的 bg 树那边会改, 这里跟着改一次, 免得依赖调用顺序。
        """
        self._canvas.configure(bg=C.CARD)
        side = C.px(SIDE)
        for name, (rect_id, img_id) in self._cells.items():
            self._canvas.itemconfigure(rect_id, outline=self._border(name))
            if img_id is None:
                continue
            item = self.app.roster.lookup(name)
            if item is None:
                continue
            photo = THUMBS.square(item, self._groups[name], side, C.CARD)
            self._photos[name] = photo
            self._canvas.itemconfigure(img_id, image=photo)

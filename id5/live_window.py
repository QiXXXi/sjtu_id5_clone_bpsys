#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直播BP界面: 给 OBS 抓取的第二个窗口, 与控制台实时同步。

无边框(`overrideredirect(True)`), 鼠标可拖动, 从控制台页脚按钮开关。
**任务栏按钮是有的** —— Tk 会给 overrideredirect 窗口打上 WS_EX_TOOLWINDOW 把它
藏起来, 但那个标记可以摘掉, 见 _fix_taskbar。

**这个窗口永远不置顶。** 曾经是 `-topmost` 常开(理由是"激活竞态"导致新映射的无主
WS_POPUP 窗口会被激活的主窗口盖住), 后来又做成开关 —— 两次都不对: 它盖住一切,
包括 messagebox 和别的程序, 而操作者根本不需要这个特性。现在它就是**一个普通
窗口**。开出来时用 `_raise_soon()` 抬一次(不然刚建出来时会被控制台压住), 之后
就按正常的 z 序走 —— 点控制台, 控制台就到前面来。
没有 `-topmost` 就没有"模态框被盖住"这个问题, 所以 App.modal() 也一并删了。

**两条硬规矩**(换肤遍历会递归进 Toplevel, 见 screens._retheme_tree):
  1. 本模块**不许出现 C.* 的调色板常量**。配色用 C.LIVE_* —— 那是刻意不进
     THEMES 的固定黑底灰框, 播出画面不跟皮肤变。
  2. 本模块**不许有叫 `redraw` 的方法**。`redraw` 在本项目里已经是"按调色板重画
     canvas"的约定(Switch / _Popup), _retheme_tree 会无条件调用它。

**颜色必须用自绘 Canvas, 不能用 ttk 控件**: _setup_style() 每次切皮肤都会重配全部
ttk 样式, ttk 控件会静默捡起调色板的颜色。

**滚动动画是真位移**: 见 config 里 LIVE_SPIN_PX_S 那段。一格里"换一张图"不是滚动。
"""

import math
import os
import random
import sys
import time
import tkinter as tk
import traceback

# 在**模块级**导入而不是像 roster 那样塞进函数里: _blit() 是 30Hz 的热路径,
# 而且滚动动画离了 PIL 根本没法拼帧。
from PIL import Image, ImageEnhance, ImageTk

from . import config as C
from .roster import THUMBS


# ---------------------------------------------------------------- 版式

def ban_split(n):
    """n 个 ban 位分到两列。返回 (第一列个数, 第二列个数)。

    n <= 5 只用第一列; n >= 6 两列均分, 奇数个时第二列多一个。
    6->3+3, 7->3+4, 8->4+4, 9->4+5, 10->5+5。

    注意这是和**控制台**列序不同的版式: 控制台的 ban_boxes 是 2 行 x 5 列、
    行序(state._apply_ban_count), 这里是两列、列序。映射按控制台下标顺序先填满
    第一列。后果是 n 从 5 跳到 6 时, 下标 3/4 会从第一列跳到第二列 —— 这是规格
    定的, 不是 bug。
    """
    n = max(0, min(C.BAN_COUNT_MAX, int(n)))
    if n <= 5:
        return n, 0
    return n // 2, n - n // 2


def compute_layout(w, h, ban_count, clone_mode):
    """算出全部槽位的 (x, y, w, h)。**纯函数**, 不碰任何控件。

    竖直方向唯一的硬约束: 五个头像的**中心**钉在画面水平中线上(求生者 2x2 块的
    中心、监管者的中心)。所以底部整条带只剩下半屏 —— 地图又是那条带里最高的
    东西(它的 ban 行占半张地图高), 于是地图尺寸由带宽反推:

        地图列高 = 地图ban高 + 间距 + 地图高 = 1.5 * 地图高 + 间距

    1280x720 下地图只有素材的约 51%, 1920x1080 下约 76%。**地图比素材小是几何
    必然**: 想按原尺寸(403x262)放下, 需要窗口高约 1385。

    水平方向: 「求生者块中心与监管者中心关于竖直中线镜像对称」只约束了 **镜像**,
    没约束距离 —— C.LIVE_D_SYM 是自由的, 取大就把两个块推开、给地图腾出地方。
    """
    k = h / C.LIVE_DESIGN_H

    def s(v):
        return int(round(v * k))

    surv = s(C.LIVE_SURV)
    sgap = s(C.LIVE_SURV_GAP)
    hunt = s(C.LIVE_SURV * C.LIVE_HUNTER_K)
    ban = s(C.LIVE_BAN)
    bgap = s(C.LIVE_BAN_GAP)
    colgap = s(C.LIVE_COL_GAP)
    d_sym = s(C.LIVE_D_SYM)
    pad_block = s(C.LIVE_PAD_BLOCK)
    pad_bot = s(C.LIVE_PAD_BOT)
    map_gap = s(C.LIVE_MAP_GAP)
    gban_pad = s(C.LIVE_PAD_GBAN)

    cx, cy = w // 2, h // 2
    block = 2 * surv + sgap                # 求生者 2x2 块边长(正方)

    # -- 求生者 2x2: 块中心在 (cx - d, cy) --
    picks = []
    left = cx - d_sym - block // 2
    top = cy - block // 2
    for row in range(2):
        for col in range(2):
            picks.append((left + col * (surv + sgap),
                          top + row * (surv + sgap), surv, surv))

    # -- 监管者: 中心在 (cx + d, cy) --
    hunter = (cx + d_sym - hunt // 2, cy - hunt // 2, hunt, hunt)

    # -- ban 两列: 挂在监管者右侧, 整块竖直居中于中线 --
    col1, col2 = ban_split(ban_count)
    bans = []
    if col1 or col2:
        rows = max(col1, col2)
        btop = cy - (rows * ban + (rows - 1) * bgap) // 2
        x1 = hunter[0] + hunt + colgap
        x2 = x1 + ban + bgap
        for i in range(int(ban_count)):
            if i < col1:
                bans.append((x1, btop + i * (ban + bgap), ban, ban))
            else:
                bans.append((x2, btop + (i - col1) * (ban + bgap), ban, ban))

    # -- 底部带 --
    band_top = cy + block // 2 + pad_block
    band_h = max(0, (h - pad_bot) - band_top)

    # -- 全局 ban: 求生者 2 行 x 4(克隆模式 1 行 x 2), 监管者 1 行 x 2 --
    # 两组仍**顶对齐在同一条线上**(即各自的"正下方"), 但这条线比底部带上沿
    # 再低 LIVE_PAD_GBAN —— 见 config 里那段理由。
    gtop = band_top + gban_pad
    if clone_mode:
        gb_surv = _grid(cx - d_sym, gtop, 2, 1, ban, bgap)
    else:
        gb_surv = _grid(cx - d_sym, gtop, 4, 2, ban, bgap)
    gb_hunt = _grid(cx + d_sym, gtop, 2, 1, ban, bgap)

    # -- 地图列: 居中于两个全局 ban 组**之间**, 不是屏幕中线 --
    # 严格按字面时求生者块会跨过中线(块右沿 = cx + block/2 - d), 所以求生者全局
    # ban 组的右沿也在中线右边。地图若按屏幕中线摆就会压上去。
    gw = 2 * ban + bgap if clone_mode else 4 * ban + 3 * bgap
    gap_left = (cx - d_sym) - gw // 2 + gw
    gap_right = (cx + d_sym) - (2 * ban + bgap) // 2

    map_rect, map_bans = None, []
    avail_w = gap_right - gap_left
    if band_h > 0 and avail_w > 0:
        mcx = (gap_left + gap_right) // 2
        mh = (band_h - map_gap) / 1.5
        mw = min(mh * C.MAP_ASPECT, float(avail_w))
        mh = mw / C.MAP_ASPECT              # 宽度不够就整体缩回去
        mw, mh = int(round(mw)), int(round(mh))
        # 两个地图 ban 并排正好等于地图宽 —— 用整数分配保证不差像素
        w1 = mw // 2
        mbh = int(round(mh * C.LIVE_MAP_BAN_K))
        mx = mcx - mw // 2
        map_bans = [(mx, band_top, w1, mbh), (mx + w1, band_top, mw - w1, mbh)]
        map_rect = (mx, band_top + mbh + map_gap, mw, mh)

    return {
        "surv_px": surv, "hunt_px": hunt, "ban_px": ban,
        "map_w": map_rect[2] if map_rect else 0,
        "map_h": map_rect[3] if map_rect else 0,
        "picks": picks,
        "hunter": hunter,
        "bans": bans,
        "gbans_survivor": gb_surv,
        "gban_hunter": gb_hunt,
        "map": map_rect,
        "map_bans": map_bans,
    }


def _grid(center_x, top_y, cols, rows, cell, gap):
    """一个 rows x cols 的槽位矩阵, 水平居中于 center_x, 从 top_y 顶对齐。"""
    total_w = cols * cell + (cols - 1) * gap
    x0 = center_x - total_w // 2
    out = []
    for r in range(rows):
        for c in range(cols):
            out.append((x0 + c * (cell + gap), top_y + r * (cell + gap), cell, cell))
    return out


# ---------------------------------------------------------------- 背景图

# (路径, mtime, w, h) -> PIL 图。**必须是模块级的**: 关掉窗口再开不用重新解码
# 那张 4500x2531 的 JPEG。
_BACKDROP = {}


def _grade(img):
    """背景图的调色: 降一点饱和(旋钮在 config)。

    单独拎成一个纯函数是为了能脱离 Tk 直接验 —— 想断言"饱和度真的降了"得拿得到
    像素。
    """
    if C.LIVE_BG_SAT != 1.0:
        img = ImageEnhance.Color(img).enhance(C.LIVE_BG_SAT)
    if C.LIVE_BG_BRIGHT != 1.0:
        img = ImageEnhance.Brightness(img).enhance(C.LIVE_BG_BRIGHT)
    return img


def _backdrop(w, h):
    """窗口背景图, 裁成**正好 w x h 的 PIL 图**。拿不到就返回 None(退回纯色底)。

    **返回 PIL 而不是 PhotoImage**: 槽位底色是"背景图在这一格上的裁片"再压一层
    LIVE_SLOT(见 LIVE_SLOT_ALPHA), 调用方得能从它身上 crop 出一块。PhotoImage
    拿不回像素。整窗那张 PhotoImage 由 _rebuild 现做 —— 重建只在 ban 数量/克隆
    模式变化时发生, 多这一次转换无所谓。

    **cover 语义**: 等比放大到刚好盖住窗口, 多出来的居中裁掉 —— 不拉伸, 也不留
    空边。bg.jpg 是 16:9, 默认窗口也是 16:9, 实际就是精确铺满; 只有把 LIVE_SIZE
    写成别的比例时才会真的裁到。

    先 draft() 再 load: draft 是 JPEG 解码器在 DCT 域上的降采样, 挑"缩小之后
    仍然不小于目标"的最大档位(4500 宽喂 1440 会走 1/2), 比全解码再 LANCZOS
    快一个量级。**只在 load 之前有效**, 所以必须在 convert/resize 之前调。

    降饱和在**缩放之前**做: 是逐像素映射, 放在前面可以拿解码器刚吐出来的小图
    当输入 —— 4 倍像素量上做 ImageEnhance 是白花的钱。
    """
    path = os.path.join(C.base_dir(), C.LIVE_BG_IMAGE)
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None                     # 图不在 —— 当没这回事
    key = (path, stamp, w, h)
    if key in _BACKDROP:
        return _BACKDROP[key]
    try:
        img = Image.open(path)
        img.draft("RGB", (w, h))
        img = _grade(img.convert("RGB"))
        scale = max(w / img.width, h / img.height)
        nw = max(w, int(round(img.width * scale)))
        nh = max(h, int(round(img.height * scale)))
        img = img.resize((nw, nh), Image.LANCZOS)
        ox, oy = (nw - w) // 2, (nh - h) // 2
        img = img.crop((ox, oy, ox + w, oy + h))
    except Exception:
        return None                     # 坏图 / 没编 JPEG 解码器 -> 纯色底, 不崩
    _BACKDROP[key] = img
    return img


def _slot_base(backdrop, rect):
    """一块槽位底: 背景图在这格上的裁片, 按 LIVE_SLOT_ALPHA 压一层 LIVE_SLOT。

    槽位底色原先是个不透明的填充矩形, 现在换成**一张图** —— 这张图就是
    "透过去看到的那部分背景, 上面盖了 0.05 灰"。于是所有框的黑底都带上了透明度,
    而头像还是画在一张**不透明**的底上(抠图的边缘因此不会被背景吃掉)。

    `LIVE_SLOT_ALPHA == 1.0` 或者没有背景图 -> 实心 `LIVE_SLOT`, 和改之前**一格
    像素都不差**。所以这个特性是可以整个关掉的, 不是"关不干净"。

    crop 越界时 PIL 拿黑色补齐, 正好是"窗口外=黑底"的语义, 顺带不用自己判边界。
    """
    x, y, w, h = (int(v) for v in rect)
    w, h = max(1, w), max(1, h)
    flat = Image.new("RGB", (w, h), C.LIVE_SLOT)
    if backdrop is None or C.LIVE_SLOT_ALPHA >= 1.0:
        return flat
    # Image.blend(a, b, t) = a*(1-t) + b*t, 所以 t 就是底色那一层的不透明度
    return Image.blend(backdrop.crop((x, y, x + w, y + h)).convert("RGB"),
                       flat, C.LIVE_SLOT_ALPHA)


# ---------------------------------------------------------------- 槽位

class SlotView:
    """一个槽位在画面上的全部状态。

    **value 与 shown 是两回事**: 真值在抽取那一刻就已经写进控制台了, 但要等
    动画滚完才能露出来。shown 才是"画面上现在是哪张图", 动画期间它是一个随机
    帧。动画结束时把 shown = value 强制落地 —— 哪怕真值根本不在候选池里
    (它可能刚被别的格子占走)。
    """

    __slots__ = ("key", "group", "rect", "gray", "getter",
                 "bg_id", "rect_id", "img_id", "value", "shown", "spin",
                 "border", "bw", "bw_now", "photo", "base", "bg_photo")

    def __init__(self, key, group, rect, gray, getter):
        self.key = key            # "pick0".."pick3" / "hunter" / "ban3" / "map" ...
        self.group = group        # survivor / hunter / map, 缩略图缓存键要用
        self.rect = rect          # (x, y, w, h)
        self.gray = gray
        self.getter = getter      # 取控制台那个下拉控件的函数
        self.bg_id = None         # 底色图元的 id(以前是矩形, 现在是一张图)
        self.rect_id = None
        self.img_id = None
        self.value = ""           # 控制台里的真值
        self.shown = ""           # 画面上的值
        self.spin = None          # 动画状态, None = 不在播
        self.border = C.LIVE_BORDER
        self.bw = C.LIVE_BORDER_W  # 常态线宽, _rebuild 里按 ban/主位定
        self.bw_now = self.bw      # 画面上此刻的线宽(呼吸时会比 bw 粗)
        self.photo = None          # 图元**此刻**指着的那张图, 见 _show_image
        self.base = None           # 底色本身(PIL, 大小就是 rect) —— 拼帧的底
        self.bg_photo = None       # 上面那张 base 的 PhotoImage, 得有人拿着

    def read(self):
        """读控制台的当前值。

        `.get()` 是纯 Python 属性读取(见 searchbox 的 SearchableAvatarDropdown),
        不碰 Tcl, 所以每拍读 28 个槽位没有开销, 也不会在 apply_rules() 中间
        被切进来。**但正因为不抛异常, 控件被销毁后会静默返回陈旧值** —— 全项目
        只调用一次 show_screen(), 本次也触发不到, 见计划里"不做的事"。
        """
        box = self.getter()
        if box is None:
            return ""
        try:
            return box.get() or ""
        except Exception:
            return ""


# ---------------------------------------------------------------- 直播窗口

class LiveWindow:
    """无边框置顶的第二个窗口, 与控制台快照同步。

    一个 `after` 循环每 LIVE_TICK_MS 干两件事: 把 28 个槽位和控制台比对一遍,
    以及推进正在播的动画。整个画面是**一个 Canvas**, 所以呼吸只需要改一个
    矩形的 outline, 换肤遍历时也只有一个控件。

    它**不属于** App 的屏幕体系: 不登记进 lock_widgets(那是控制台的事), 也不
    参与 _retheme_tree(靠 _theme_exempt, 见模块头)。
    """

    def __init__(self, app, on_close=None):
        self.app = app
        self.state = app.state
        self.roster = app.roster
        self.on_close = on_close

        self._alive = True
        self._tick_id = None
        self._root_esc = None
        self._drag_off = (0, 0)
        self._breath_t0 = time.monotonic()
        self._slots = {}
        self._shape = None
        self._bg_photo = None
        # 已报告过的异常签名。tick 里吞异常的前提是**吞下去要留痕**, 但同一个
        # 异常每 30ms 来一次会把 stderr 刷爆, 所以同一种只报一次。
        self._reported = set()

        # 开窗时把当前令牌"消费掉": 窗口是动画中途被打开的就直接落地, 不补播。
        draw = self.state.last_draw
        self._last_seq = draw["seq"] if draw else 0

        self.w, self.h = C.LIVE_SIZE or _default_size(app.root)
        w, h = self.w, self.h

        # 先解码再建窗口: 全套缩略图约 140ms, 反过来做的话屏幕上会先出现一个
        # 空的黑色窗口再慢慢长出图来。
        self._warm()

        win = tk.Toplevel(app.root)
        self.win = win
        # 无边框必须在映射之前设一次, 否则会先闪一下带标题栏的窗口。
        win.overrideredirect(True)
        # 标题栏是没有的, 但**名字还是要设**: 它是任务栏按钮的提示文字和
        # Alt-Tab 里那一行。无边框窗口在切窗口时没有标题栏可认, 只剩这个。
        win.title(C.LIVE_TITLE)
        # 任务栏按钮上的图标。_fix_taskbar 补出来的那个按钮也用它。
        C.apply_icon(win)
        # **不设 -topmost, 永远不设。** 见模块头。
        win.configure(bg=C.LIVE_BG)
        win.geometry("%dx%d+%d+%d" % ((w, h) + self._initial_pos()))
        win._theme_exempt = True

        # **关闭通道必须最先接上**, 早于任何会抛异常的步骤。
        # 这个窗口没有标题栏, 而任务栏按钮要等 _fix_taskbar 才补上 —— 构造失败
        # 时还两样都没有, 也没任何人持有它的引用。一旦后面某步抛了异常而通道
        # 还没接上, 屏幕上就会剩下一个凭空多出来的黑块, 只能去任务管理器杀进程。
        # 这不是假设: LIVE_BORDER 撞名那次就是这么留在屏幕上的。
        # 右键是无边框窗口最顺手的关闭方式; Escape 只是便利, 键盘焦点对无边框
        # 窗口不可靠, 所以 root 上也绑一份。
        win.bind("<Button-3>", lambda _e: self.close())
        win.bind("<Escape>", lambda _e: self.close())
        # 任务栏按钮上右键 -> 关闭窗口, 走的是 WM_DELETE_WINDOW。不接的话 Tk 会
        # 直接 destroy, 绕开 close(), 于是 on_close 不跑: 控制台那个按钮还写着
        # "关闭直播bp界面"、app.live_window 还指着个死窗口。接上就统一了。
        win.protocol("WM_DELETE_WINDOW", self.close)
        self._root_esc = app.root.bind("<Escape>", self._on_escape, add="+")

        try:
            self.canvas = tk.Canvas(win, width=w, height=h, bg=C.LIVE_BG,
                                    highlightthickness=0, bd=0, takefocus=0)
            self.canvas.pack(fill="both", expand=True)
            self._rebuild()
            win.bind("<Button-1>", self._drag_start)
            win.bind("<B1-Motion>", self._drag_move)
            self._tick()
            self._raise_soon()
        except Exception:
            self.close()          # 绝不留孤儿窗口
            raise

    def _raise_soon(self):
        """窗口映射之后要做的两件事, 都推迟两拍再做。

        **一是补任务栏按钮**(见 _fix_taskbar): HWND 是 map 的时候才建的, 构造器
        里做太早。

        **二是把自己抬到控制台前面一次**。不能只靠当场 `lift()`: 本窗口是在控制台
        按钮的处理器里映射出来的, 这段处理返回之后 Windows 才把被激活的主窗口抬
        上去(项目里那条"lift() 无效"的记录就是这个竞态), 当时叫的 lift 会被后面
        这一步盖掉。所以推迟 —— 那时竞态早走完了, 抬一下就稳。

        抬完就不管了, 不粘: 操作者之后去点控制台, 控制台照样翻到前面来。这是
        普通窗口该有的行为 —— 本窗口**不置顶**, 见模块头。
        """
        for delay in (1, 80):
            if not self._alive:
                return
            try:
                self.win.after(delay, self._raise_once)
            except tk.TclError:
                return

    def _raise_once(self):
        if not self._alive:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        # 先修样式再 lift —— 修的过程要隐藏/显示一次窗口, 那一下会把 z 序打乱。
        self._fix_taskbar()
        try:
            self.win.lift()
        except tk.TclError:
            pass

    def _fix_taskbar(self):
        """给这个无边框窗口补一个任务栏按钮(顺带 Alt-Tab 项)。

        `overrideredirect(True)` 的代价**不只是"没有标题栏"** —— Tk 在 Windows 上
        还顺手把窗口标成了工具窗口。实测: 真正的顶层窗口是包在外面的一层 wrapper
        (`winfo_id()` 拿到的是里面的子窗口, `GetAncestor(.., GA_ROOT)` 才是它),
        它的扩展样式就是 `WS_EX_TOOLWINDOW`。工具窗口按定义不进任务栏、不进
        Alt-Tab —— 所以"无边框就没有任务栏"是个误解, 那是 Tk 打的标记, 能摘。

        摘掉 TOOLWINDOW、补上 `WS_EX_APPWINDOW`, shell 就重新拿它当普通主窗口。
        **一行 GWL_STYLE 都不碰**, 所以还是无边框、还是能拖。

        改完必须**藏一下再露出来**: 光改样式 shell 不一定重新评估。用
        SW_SHOWNOACTIVATE 而不是 SW_SHOW, 免得这一下把焦点从控制台抢过来。

        幂等, 所以 _raise_once 的两次延迟各跑一遍正好当重试。拿不到 HWND(不是
        Windows / 权限不够)就静默跳过 —— 没按钮只是不方便, 不该让窗口开不出来。
        """
        try:
            import ctypes
            u = ctypes.windll.user32
            # **参数类型必须显式声明**: HWND 是指针宽度的, 交给 ctypes 默认的
            # c_int 会被截成 32 位带符号 —— 句柄一旦超过 0x7fffffff 就指到别的
            # 窗口上去了, 而且改的是别人。实测这台机器上的句柄都在 32 位内(所以
            # 不声明也能跑), 但"默认值正好够用"不是安全。
            u.GetAncestor.restype = ctypes.c_void_p
            u.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            u.GetWindowLongW.restype = ctypes.c_long
            u.GetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int)
            u.SetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                         ctypes.c_long)
            u.ShowWindow.argtypes = (ctypes.c_void_p, ctypes.c_int)
            hwnd = u.GetAncestor(self.win.winfo_id(), 2)       # GA_ROOT
            if not hwnd:
                return
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
            if (ex & WS_EX_APPWINDOW) and not (ex & WS_EX_TOOLWINDOW):
                return                                         # 已经好了
            u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                             (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
            u.ShowWindow(hwnd, 0)                              # SW_HIDE
            u.ShowWindow(hwnd, 4)                              # SW_SHOWNOACTIVATE
        except Exception:
            pass

    # -- 对外 ----------------------------------------------------------

    @property
    def alive(self):
        if not self._alive:
            return False
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        """收干净再销毁。

        `after` 注册在**解释器**上而不是控件上 —— 关掉窗口不会自动取消它,
        自重排的 tick 会以 30Hz 永远跑下去, 第一句就对已销毁的控件抛
        `TclError: invalid command name`。所以三道一起上: 取消 id + _alive
        标志 + tick 里的 TclError 兜底。
        """
        if not self._alive:
            return
        self._alive = False
        if self._tick_id is not None:
            try:
                self.win.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None
        if self._root_esc is not None:
            try:
                self.app.root.unbind("<Escape>", self._root_esc)
            except tk.TclError:
                pass
            self._root_esc = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        try:
            self.app.root.focus_force()      # 焦点还给控制台
        except tk.TclError:
            pass
        if self.on_close is not None:
            self.on_close()

    # -- 构建 ----------------------------------------------------------

    def _warm(self):
        """把动画会滚到的图**先解码好**。

        老虎机一刀下去可能遍历整个候选池, 冷启动一帧要卡好几百毫秒。只预热
        五个主位的尺寸: ban 位不参与抽取(是手选的), 十来个按需加载无所谓。

        预热必须**同步做完**: 放到 after 里做, 第一次抽取就会撞上还没解码的图。
        """
        lay = compute_layout(self.w, self.h, self._ban_count(), self._clone())
        surv, hunt = lay["surv_px"], lay["hunt_px"]
        THUMBS.warm_live(self.roster.groups["survivor"], "survivor", surv, surv)
        THUMBS.warm_live(self.roster.groups["hunter"], "hunter", hunt, hunt)
        if lay["map_w"] > 0 and lay["map_h"] > 0:
            THUMBS.warm_live(self.roster.groups["map"], "map",
                             lay["map_w"], lay["map_h"])

    def _specs(self, ban_count, clone):
        """版式 → (key, group, rect, gray, 取值函数) 列表。

        取值函数是**跨行构造**的(监管者域 = ban 位 + 第 5 位 + 两行第 5 列),
        所以按 key 而不是按控制台下标组织。克隆模式决定求生者全局 ban 取哪
        几个格子 —— 那两行只有第 0 列是启用的, 所以是"1 行 2 个"。
        """
        lay = compute_layout(self.w, self.h, ban_count, clone)
        pb, bb = self.state.pick_boxes, self.state.ban_boxes
        gb, mbb = self.state.gban_boxes, self.state.map_ban_boxes

        def at(seq, i):
            return seq[i] if 0 <= i < len(seq) else None

        out = []
        for i, rect in enumerate(lay["picks"]):
            out.append(("pick%d" % i, "survivor", rect, False,
                        lambda i=i: at(pb, i)))
        out.append(("hunter", "hunter", lay["hunter"], False,
                    lambda: at(pb, 4)))
        for i, rect in enumerate(lay["bans"]):
            out.append(("ban%d" % i, "hunter", rect, True,
                        lambda i=i: at(bb, i)))
        for i, rect in enumerate(lay["gbans_survivor"]):
            # 克隆模式: 两行只有第 0 列可用 → 第 i 个就是第 i 行第 0 列
            # 非克隆: 4 列 2 行、行序取
            idx = i * C.COLS if clone else (i // 4) * C.COLS + i % 4
            out.append(("gs%d" % i, "survivor", rect, True,
                        lambda i=i, k=idx: at(gb, k)))
        for i, rect in enumerate(lay["gban_hunter"]):
            out.append(("gh%d" % i, "hunter", rect, True,
                        lambda i=i: at(gb, i * C.COLS + C.GBAN_HUNTER_COL)))
        if lay["map"] is not None:
            out.append(("map", "map", lay["map"], False, lambda: self.state.map_box))
        for i, rect in enumerate(lay["map_bans"]):
            out.append(("mb%d" % i, "map", rect, True,
                        lambda i=i: at(mbb, i)))
        return out

    def _rebuild(self):
        """按当前 ban 数量与克隆模式重建全部图元。

        只有**版式形状**变了才重建(ban 数量、克隆模式)。重建会重画整个画布,
        所以顺带把动画状态按 key 搬过去, 免得开关一拨动画就断在半路。

        槽位的**尺寸**只由常量决定, 不随这两个变量变 —— 所以重建用不着重新
        预热缩略图, 缓存全部命中。
        """
        ban_count, clone = self._ban_count(), self._clone()
        self._shape = (ban_count, clone)

        old = self._slots
        self.canvas.delete("all")
        self._slots = {}

        # 背景图**第一个建**, 于是天然排在所有图元之下 —— 不用 tag_lower, 那还得
        # 处理"槽位是后来才建的图元"。
        back = _backdrop(self.w, self.h)
        self._bg_photo = ImageTk.PhotoImage(back) if back is not None else None
        if self._bg_photo is not None:
            self.canvas.create_image(0, 0, image=self._bg_photo, anchor="nw")

        for key, group, rect, gray, getter in self._specs(ban_count, clone):
            # 边框粗细**按槽位**取: ban 位 2px, 主位 4px(见 config 里那两段的理由)。
            # gray 本身就是"这是不是一个 ban 位"的标志 —— _specs 里只有 ban 列 /
            # 求生者全局 ban / 监管者全局 ban / 地图 ban 标 True, 主位和地图都是
            # False。直接拿它当判据, 不再给 SlotView 加字段: 多一个字段就多一处
            # 能跟 gray 对不上的地方。
            bw = C.LIVE_BORDER_W_BAN if gray else C.LIVE_BORDER_W
            ins = bw // 2               # 内缩半个线宽, 外半边才不会被画布边缘裁掉
            slot = SlotView(key, group, rect, gray, getter)
            slot.bw = slot.bw_now = bw
            prev = old.get(key)
            if prev is not None:
                slot.value = prev.value
                slot.shown = prev.shown
                slot.spin = prev.spin       # 动画重起, 不排队
                slot.border = prev.border
            x, y, w, h = rect
            # 每个槽位**三个**图元, 自下而上: 底色 → 头像 → 边框。
            #
            # 底色是一**张图**而不是填充矩形: 它是背景图在这一格上的裁片压了一层
            # LIVE_SLOT(见 _slot_base), 也就是"半透的黑底"。用矩形的话 Tk 没有
            # alpha, 只能上 stipple 抖动 —— 122px 的框上一眼就是麻点, OBS 再缩放
            # 一下还会出摩尔纹。
            #
            # 边框必须是**空心的**那一个, 头像才能夹在中间。第一版把底色和边框
            # 合成一个填充矩形, 再用 tag_lower 把头像压到它下面 —— 那是把头像
            # 埋在一块不透明的 #0d0d0d 底下, 于是**每个框里什么都看不见**, 只剩
            # 一圈边。自检当时只断言了 img_id 不为 None(图元确实建了), 没断言
            # 它看得见, 所以没拦住。
            slot.base = _slot_base(back, rect)
            slot.bg_photo = ImageTk.PhotoImage(slot.base)
            slot.bg_id = self.canvas.create_image(x, y, image=slot.bg_photo,
                                                  anchor="nw")
            slot.rect_id = self.canvas.create_rectangle(
                x + ins, y + ins, x + w - ins, y + h - ins,
                outline=slot.border, width=bw, fill="")
            self._slots[key] = slot
            if slot.shown:
                self._paint(slot)

    def _show_image(self, slot, photo):
        """把一个 PhotoImage 贴到槽位上(必要时先把图元建出来)。

        走 itemconfigure 而**不是 delete + create**: 重建会每帧换一个图元 id,
        Tk 的显示列表复用就全丢了, 而且那一格会闪。

        **PhotoImage 的引用必须有人替它拿着**: Canvas 只存图片的 Tcl 名字, 不存
        Python 引用, 被 GC 回收之后那一格会**静默**变空白 —— 而且之后任何一次
        itemconfigure 都会当场抛 `image "pyimageNNN" doesn't exist`(Tk 重新处理
        图元的 -image 选项时要去找那张图), 于是那一格**再也画不上东西**。

        引用记在 **slot.photo** 上, 就在这个函数里接手 —— 它是唯一改图元 image
        的地方, 在这记最不容易漏。曾经记在 slot.spin["photo"](见 _blit), 那是
        错的: spin 在落地时被整个丢掉, 而图元正好还指着它的最后一帧, 于是
        "转盘停在了一个名册里没有的值上"(操作者抽完立刻按重置, 控制台被清空)
        就会踩到。
        """
        slot.photo = photo
        if slot.img_id is None:
            x, y, w, h = slot.rect
            slot.img_id = self.canvas.create_image(
                x + w // 2, y + h // 2, image=photo, anchor="center")
            # 头像是**按需**建的, 一定排在边框之后。压到边框下面、底色上面 ——
            # 边框是空心的, 所以头像照常看得见, 而边框不会被头像盖掉内侧一半
            # (不压的话边框看起来像没描边)。
            self.canvas.tag_lower(slot.img_id, slot.rect_id)
        else:
            self.canvas.itemconfigure(slot.img_id, image=photo, state="normal")

    def _paint(self, slot):
        """把 slot.shown 那张图贴上去(静止状态用)。

        抠图走缓存(按 角色 x 尺寸), 但**合成不走缓存** —— 底下那块底色每格都
        不一样, 缓存键里就得带上槽位, 于是变成 28 份。一次 copy + paste 约
        0.3ms, 而且只在值变化时发生, 不值得为它把缓存撑大 28 倍。
        """
        item = self.roster.lookup(slot.shown)
        if item is None:
            # 空槽 / 名册里已经没有的值: 只留边框和底色
            if slot.img_id is not None:
                self.canvas.itemconfigure(slot.img_id, state="hidden")
            return
        x, y, w, h = slot.rect
        rgb, alpha = THUMBS.cutout(item, slot.group, w, h, gray=slot.gray)
        frame = slot.base.copy()
        frame.paste(rgb, (0, 0), alpha)     # 预乘 rgb + alpha 蒙版 = 正确合成
        self._show_image(slot, ImageTk.PhotoImage(frame))

    def _set_border(self, slot, color, grow=0):
        """改边框颜色, 顺带让它比常态粗 grow 像素(呼吸峰值用)。

        两个都记在 slot 上、都做变化判断: 这个函数每拍要给每个在播的槽位调一次,
        无脑 itemconfigure 会白白惊动 Tk 的显示列表。
        """
        width = slot.bw + grow
        if slot.border == color and slot.bw_now == width:
            return
        slot.border = color
        slot.bw_now = width
        self.canvas.itemconfigure(slot.rect_id, outline=color, width=width)

    # -- 同步 ----------------------------------------------------------

    def _ban_count(self):
        try:
            n = int(self.state.ban_count.get())
        except Exception:
            n = C.BAN_COUNT_DEFAULT
        return max(C.BAN_COUNT_MIN, min(C.BAN_COUNT_MAX, n))

    def _clone(self):
        try:
            return bool(self.state.clone_mode.get())
        except Exception:
            return False

    def _sync(self):
        """一拍一次的快照比对: 只更新变了的槽位。"""
        if (self._ban_count(), self._clone()) != self._shape:
            self._rebuild()
        for slot in self._slots.values():
            want = slot.read()
            slot.value = want
            if slot.spin is None and slot.shown != want:
                slot.shown = want
                self._paint(slot)

        draw = self.state.last_draw
        if draw and draw["seq"] != self._last_seq:
            # 令牌比自己的序号新 = 控制台刚抽了一次。**这是唯一能知道"抽了、
            # 抽了哪些格子、候选池是什么、播多久"的地方** —— 值轮询看不见
            # A→A(候选池被排除干净时 _choose 会返回 current), _locked 也不
            # 可靠(after 不是实时的, 短时长下第一拍会落在 _unlock 之后)。
            self._last_seq = draw["seq"]
            self._start_spin(draw)

    # -- 动画 ----------------------------------------------------------

    def _reel_names(self, slot, pool, value, ms):
        """编一条滚动胶片: 一串角色名, **最后一格是真值**。

        格数怎么来: 时长决定**总行程**(速度是固定的 C.LIVE_SPIN_PX_S), 行程除以
        格高就是格数。这就是规格说的"时长只影响滚过的数量, 不影响滚动速度"。

        行程里先扣掉减速段的"额外时间" —— 减速段走完同样一段距离花的时间是匀速
        的两倍(线性减速到 0, 平均速度是 v0/2), 不扣的话动画会比控制台的点击锁定
        晚 12% 才落地, 操作者会看到"控制台能点了、转盘还在转"。
           匀速段 (D-T)/v0 + 减速段 2T/v0 = (D+T)/v0,  令 T = frac*D
           => D = v0 * ms / (1 + frac)
        """
        h = max(1, slot.rect[3])
        frac = C.LIVE_SPIN_TAIL_FRAC
        travel = C.LIVE_SPIN_PX_S * (ms / 1000.0) / (1.0 + frac)
        n = int(round(travel / h)) + 1
        if n < 2:                       # 时长太短, 连一格都滚不过去
            return []

        values = [it.value for it in pool]
        names = []
        last = ""
        for _ in range(n - 1):
            # 避开上一格那张, 否则同一张连着出现会看着像卡住了
            cand = [v for v in values if v != last]
            last = random.choice(cand or values)
            names.append(last)
        names.append(value)             # 最后一格 = 真值, 转盘停在这
        return names

    def _start_spin(self, draw):
        """起一段老虎机。第二笔抽取到达时**重起, 不排队**。"""
        ms = draw.get("ms", 0)
        pool = draw.get("items") or []
        value = draw.get("value", "")
        now = time.monotonic()
        for key in draw.get("slots", ()):
            slot = self._slots.get(key)
            if slot is None:
                continue
            slot.value = value
            names = self._reel_names(slot, pool, value, ms) if ms > 0 and pool \
                else []
            if not names:
                self._stop_spin(slot)   # 时长 0 = 不播动画, 直接落地
                continue
            h = slot.rect[3]
            travel = float((len(names) - 1) * h)
            tail = travel * C.LIVE_SPIN_TAIL_FRAC
            slot.spin = {
                "names": names,
                "t0": now,
                "travel": travel,
                "v0": C.LIVE_SPIN_PX_S,
                "tail": tail,
                "tail_from": travel - tail,
                "tail_t0": None,        # 进入减速段的时刻, None = 还在匀速
            }
            slot.shown = names[0]
            self._blit(slot, 0.0)

    def _stop_spin(self, slot):
        """落地: 用缓存好的整张缩略图收尾, 边框回到常态色。

        一律**强制**贴 slot.value —— 真值可能根本不在候选池里(比如它刚被别的
        格子占走), 转盘自己滚是滚不到它的。
        """
        slot.spin = None
        slot.shown = slot.value
        self._paint(slot)
        self._set_border(slot, C.LIVE_BORDER)

    def _blit(self, slot, pos):
        """把胶片在 pos 处的那一段拼成**一帧**贴上去 —— 这就是"滚动"。

        这一帧跨**两格**: 正在出画的那张(往上走)和正在进画的那张(从下面进来)。
        两张都按 pos 的小数部分错位贴, 人眼看到的就是连续位移, 而不是一格一格
        地换图。

        PIL 的 paste 会自动**裁掉**超出目标框的部分, 所以不需要任何裁剪逻辑 ——
        帧的尺寸就是槽位尺寸, 出画/进画的部分天然被切干净。这也是必须走 PIL 的
        原因: Tk 的 canvas image 图元不会裁剪到槽位, 直接挪图元的话头像会溢出到
        隔壁格子上。

        每帧一次 base.copy() + 两张 paste + 一张 PhotoImage, 实测单槽位约 0.2ms,
        远够 30Hz。
        """
        spin = slot.spin
        if spin is None:
            return
        x, y, w, h = slot.rect
        names = spin["names"]
        i = int(pos // h)
        if i >= len(names) - 1:
            i = len(names) - 2
        frac = int(round(pos - i * h))

        frame = slot.base.copy()
        for k, dy in ((i, -frac), (i + 1, h - frac)):
            item = self.roster.lookup(names[k])
            if item is None:
                continue
            rgb, alpha = THUMBS.cutout(item, slot.group, w, h, gray=slot.gray)
            frame.paste(rgb, (0, dy), alpha)

        photo = ImageTk.PhotoImage(frame)
        slot.shown = names[i]
        self._show_image(slot, photo)   # 引用由 _show_image 接手, 上一帧这时才能回收

    def _spin_pos(self, spin, now):
        """当前应该滚到哪个偏移(像素)。匀速段 + 末尾线性减速段。

        减速段用 s -> 2s - s² 而不是线性插值: 它的导数是 2(1-s), 也就是速度从
        v0 线性掉到 0, 接得上匀速段(不像线性插值会在接缝处速度突变, 看着像撞了
        一下)。整段走完正好停在 travel 上, 不差像素。
        """
        travel = spin["travel"]
        if spin["tail_t0"] is None:
            pos = spin["v0"] * (now - spin["t0"])
            if pos < spin["tail_from"]:
                return pos
            spin["tail_t0"] = now       # 进减速段, 从 tail_from 接着走
        dur = 2.0 * spin["tail"] / spin["v0"]
        if dur <= 0:
            return travel
        s = min(1.0, (now - spin["tail_t0"]) / dur)
        return spin["tail_from"] + spin["tail"] * (2 * s - s * s)

    def _advance(self):
        """推进全部在播的槽位, 顺便让它们的边框呼吸。"""
        now = time.monotonic()
        t = now - self._breath_t0
        # 0..1 的相位。颜色和加粗量共用它, 所以最白的那一拍一定也最粗。
        ph = 0.5 + 0.5 * math.sin(2 * math.pi * C.LIVE_BREATH_HZ * t)
        hot = C.grey(C.LIVE_BREATH_LO + (C.LIVE_BREATH_HI - C.LIVE_BREATH_LO) * ph)
        grow = int(round(C.LIVE_BREATH_GAIN * ph))

        for slot in self._slots.values():
            spin = slot.spin
            if spin is None:
                continue
            pos = self._spin_pos(spin, now)
            if pos >= spin["travel"]:
                self._stop_spin(slot)
            else:
                self._blit(slot, pos)
                self._set_border(slot, hot, grow)

    # -- 节拍 ----------------------------------------------------------

    def _report(self, where, exc):
        """吞掉的异常必须留痕, 但同一种只报一次 —— 这个循环 30ms 一拍。

        **`sys.stderr` 可能是 None**: 打包成 exe 时是 windowed 模式(不带控制台),
        PyInstaller 把 stdout/stderr 都设成 None。这时 `sys.stderr.write` 抛
        AttributeError —— 而本函数是在 `_tick` 的 except 分支里被调的, 它再抛出去
        就会冲出 `_tick`, 末尾那句"把自己重排上"永远执行不到, **整个同步循环当场
        死掉、窗口从此定格**。那正是这个函数要防的那类故障, 所以写不出去也必须兜住。
        """
        sig = (where, type(exc).__name__, str(exc))
        if sig in self._reported:
            return
        self._reported.add(sig)
        try:
            sys.stderr.write("[直播BP界面] %s 出错(画面继续跑, 该功能本次失效):\n"
                             % where)
            traceback.print_exc()
        except Exception:
            pass

    def _land_all(self):
        """把还在滚的槽位全部强制落地。只在 _advance 整个炸掉时兜底。

        不兜的话那个槽位会永远停在某个随机帧上、边框永远亮着, 而真值早在
        控制台里了 —— 操作者看到的是一张**错的**图, 比不播动画严重得多。
        """
        for slot in self._slots.values():
            if slot.spin is None:
                continue
            try:
                self._stop_spin(slot)
            except Exception:
                slot.spin = None

    def _tick(self):
        """一拍。**任何情况下都要把自己重排上** —— 这是这个循环唯一的生命线。

        以前这里只 catch TclError, 别的一律往上抛。Tkinter 的 CallWrapper 会把
        回调里的异常打印到 stderr 然后**吞掉**, 于是 `_tick` 最后那行 after 永远
        执行不到, 循环悄无声息地死了: 窗口还在、画面还是对的, 但从此不再同步、
        永远不会播动画。这正是"同步看着正常、动画从来不出现"的样子, 所以同步和
        动画**各自**兜一层, 一个坏了不连累另一个。
        """
        self._tick_id = None
        if not self._alive:
            return
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return                    # 窗口正在销毁, 别再重排了

        try:
            self._sync()
        except tk.TclError:
            return
        except Exception as exc:
            self._report("同步", exc)

        try:
            self._advance()
        except tk.TclError:
            return
        except Exception as exc:
            self._report("动画", exc)
            self._land_all()

        try:
            self._tick_id = self.win.after(C.LIVE_TICK_MS, self._tick)
        except tk.TclError:
            self._tick_id = None

    # -- 拖动 ----------------------------------------------------------

    def _initial_pos(self):
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        return self._clamp(max(0, (sw - self.w) // 2), max(0, (sh - self.h) // 2))

    def _drag_start(self, event):
        self._drag_off = (event.x_root - self.win.winfo_x(),
                          event.y_root - self.win.winfo_y())

    def _drag_move(self, event):
        # 只发位置, **不发 WxH** —— 陈旧尺寸会和布局打架。
        # 也不用 winfo_pointerx() - winfo_x() 那种写法: 偏移里含指针在窗口内的
        # 位置, 窗口会"跳"到把左上角对准光标; 而且 winfo_x() 读的是 Tk 上一次
        # 的位置, 滞后于刚发出的 geometry(), 窗口会**爬**。
        x, y = self._clamp(event.x_root - self._drag_off[0],
                           event.y_root - self._drag_off[1])
        self.win.geometry("+%d+%d" % (x, y))

    def _clamp(self, x, y):
        """至少留 LIVE_DRAG_MARGIN 像素在桌面可视范围内。

        无边框窗口**没有标题栏**, 拖到屏幕外就只剩控制台那个开关和任务栏按钮
        能救它(后者是 _fix_taskbar 补的)。留 80px 是为了让它**看得见** —— 全
        拖出去虽然还能关掉, 但操作者会先慌一下。
        """
        vx, vy, vw, vh = _desktop_rect(self.win)
        m = C.LIVE_DRAG_MARGIN
        x = max(vx - self.w + m, min(x, vx + vw - m))
        y = max(vy - self.h + m, min(y, vy + vh - m))
        return int(x), int(y)

    def _on_escape(self, _event=None):
        if self.alive:
            self.close()


# ---------------------------------------------------------------- 辅助

def _default_size(root):
    """直播窗口的默认尺寸: 和主窗口同一套"第一个放得下屏幕的 16:9"。

    延迟导入, 避免和 screens 成环(screens 只在打开窗口时才会 import 本模块)。
    """
    from .screens import choose_size
    return choose_size(root)


def _desktop_rect(win):
    """整个桌面(含副屏)的 (x, y, w, h)。

    **不能用 Tk 的 winfo_vroot* **: 它只报主显示器, 双屏时看不见左边那块屏,
    按它钳位就永远拖不过去。SM_*VIRTUALSCREEN(76..79) 才是虚拟桌面的外接
    矩形 —— 左边副屏的 x 是负的也照样对。拿不到就退回 Tk 的主屏范围。
    """
    try:
        import ctypes
        u = ctypes.windll.user32
        vx, vy = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        vw, vh = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if vw > 0 and vh > 0:
            return vx, vy, vw, vh
    except Exception:
        pass
    return (win.winfo_vrootx(), win.winfo_vrooty(),
            win.winfo_vrootwidth(), win.winfo_vrootheight())


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":                       # pragma: no cover
    def dump(w, h, n, clone):
        lay = compute_layout(w, h, n, clone)
        cols, rows = 110, 40
        grid = [[" "] * cols for _ in range(rows)]
        marks = [(lay["hunter"], "H"), (lay["map"], "M")]
        for i, r in enumerate(lay["picks"]):
            marks.append((r, str(i + 1)))
        for i, r in enumerate(lay["bans"]):
            marks.append((r, "b"))
        for r in lay["gbans_survivor"]:
            marks.append((r, "s"))
        for r in lay["gban_hunter"]:
            marks.append((r, "h"))
        for r in lay["map_bans"]:
            marks.append((r, "m"))
        for rect, ch in marks:
            if not rect:
                continue
            x, y, rw, rh = rect
            for py in range(y, y + rh):
                for px in range(x, x + rw):
                    gx, gy = px * cols // w, py * rows // h
                    if 0 <= gy < rows and 0 <= gx < cols:
                        grid[gy][gx] = ch

        # 中线
        for gy in range(rows):
            grid[gy][cols // 2] = grid[gy][cols // 2] if grid[gy][cols // 2] != " " else "|"
        c1, c2 = ban_split(n)
        print("=" * cols)
        print("%dx%d  ban=%d (%d+%d)  clone=%s   求生者块 %dpx  监管者 %dpx  "
              "ban %dpx  地图 %dx%d (素材的 %.0f%%)"
              % (w, h, n, c1, c2, clone, lay["surv_px"], lay["hunt_px"],
                 lay["ban_px"], lay["map_w"], lay["map_h"],
                 100.0 * lay["map_h"] / 262))          # 素材高 262
        for row in grid:
            print("".join(row))

    dump(1280, 720, 5, False)
    dump(1280, 720, 10, True)
    dump(1920, 1080, 7, False)

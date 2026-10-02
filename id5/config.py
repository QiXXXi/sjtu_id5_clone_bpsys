#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置: 路径、尺寸、配色、字体、布局常量、地图中文名映射。"""

import json
import os
import struct
import sys

# ---------------------------------------------------------------- 路径

# 两个窗口的名字。**直播窗口是无边框的, 名字不显示在它身上** —— 它是任务栏
# 按钮的提示文字和 Alt-Tab 里的那一行(见 live_window 的 _fix_taskbar), 也就是
# 操作者切窗口时唯一能认出它的东西, 所以不能省。
APP_TITLE = "控制台"        # 主窗口
LIVE_TITLE = "直播界面"     # 直播BP窗口

# 版权信息。**这里是唯一的一份**: 设置窗口底部那两行、安装包的版本/发行者、
# 以及 LICENSE 文件的抬头都从这儿取。各写一遍早晚会对不上, 而且改了一处忘了
# 另一处这种事没人会发现。
#
# APP_VERSION 是版本号, 保持 x.y.z 的格式 —— 设置窗口和 LICENSE 抬头都显示它。
APP_VERSION = "1.1.0"
APP_AUTHOR = "QiXXXi@SJTU"
APP_LICENSE = "GPL-3.0"

# 检查更新问的是这个仓库的 releases。**发版流程已经在这儿了** —— tag 和安装包
# 本来就是同一次操作产出的, 所以版本号不用再维护第二份。见 updater 模块头。
APP_REPO = "QiXXXi/sjtu_id5_clone_bpsys"


def base_dir():
    """程序所在目录。打包成 exe 后返回 exe 所在目录，而非临时解包目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 图片目录(相对 base_dir)
DIR_SURVIVOR = "survivor"
DIR_HUNTER = "hunter"
DIR_MAP = "map_square"

# 字体目录(相对 base_dir)。里面的 ttf/otf 会在启动时注册给本进程, 见 register_fonts()。
DIR_FONT = "fonts"

# ---------------------------------------------------------------- 图标

# 应用图标。**仓库里只维护 logo.png 这一份**: exe 和安装包用的 .ico 由 build.py
# 从它生成(见 build.make_ico), 运行时两个窗口的图标也直接读这张 PNG。
ICON_FILE = "logo.png"


def apply_icon(win):
    """给窗口设图标。取不到就静默保持 Tk 默认图标, 不让它拖垮启动。

    **必须把 PhotoImage 留在活着的引用上**: Tk 只存图片名, Python 这边一被 GC
    回收图标就没了 —— 和 ThumbCache 里 canvas 图片是同一个坑。所以挂到窗口对象
    上, 而不是让它当个局部变量。

    tkinter 在这里 import 而不是放文件头: build.py 也要 import 本模块去读版本号,
    没必要为此把 GUI 库拖进一个纯打包脚本的进程。
    """
    try:
        import tkinter as tk
        path = os.path.join(base_dir(), ICON_FILE)
        if not os.path.isfile(path):
            return
        img = tk.PhotoImage(file=path)
        win.iconphoto(True, img)
        win._icon_ref = img
    except Exception:
        pass          # 图标是装饰, 没有也不该拦住程序启动


# ---------------------------------------------------------------- 地图中文名

# 地图缩略图是英文文件名，界面上显示中文。缺映射时回退为文件名本身。
MAP_NAMES = {
    "ArmsFactory": "军工厂",
    "ChinaTown": "唐人街",
    "Darkwoods": "不归林",
    "EversleepingTown": "永眠镇",
    "LakesideVillage": "湖景村",
    "LeosMemory": "里奥的回忆",
    "MoonlitRiverPark": "月亮河公园",
    "SacredHeartHospital": "圣心医院",
    "TheRedChurch": "红教堂",
}

# ---------------------------------------------------------------- 窗口尺寸

# 16:9 候选，从大到小。启动时选第一个放得下当前屏幕的。
SIZE_CANDIDATES = [
    (1600, 900),
    (1440, 810),
    (1280, 720),
    (1200, 675),
    (1152, 648),
    (1024, 576),
]
# 预留高度: 标题栏(~31) + 任务栏(~48) + 余量。不预留会导致底行被切掉。
SCREEN_RESERVE_H = 96
SCREEN_FRACTION = 0.96

# 设置窗口的尺寸。放得下就居中显示, 放不下就退回主窗口的尺寸。
# 想改大小只改这一个常量。**规则禁用窗也用这个值**(规格要求两窗一样大)。
#
# 高度是 680 而不是 16:9 的 576: 内容区是居中 place 的, 比窗口高就会**上下
# 同时**被裁掉, 而且从外面看不出来是被裁的。实测最满的一屏(规则禁用预览占满
# 两行)内容高 538px, 再加一张「版本」卡片就顶到 640 上下 —— 576 装不下。
# 这台机器(1600x900 控制台)留出约 60px 余量。
SETTINGS_SIZE = (1024, 680)

# 配色参考尺寸: 所有度量按 实际宽 / DESIGN_W 缩放
DESIGN_W = 1440
DESIGN_H = 810

# ---------------------------------------------------------------- 布局

ROWS = 10
COLS = 5

ROW_TOGGLES = 0        # 开关行
ROW_MAP = 1            # 本局地图 | 随机 | 地图全局ban1 | 地图全局ban2
ROW_BAN_START = 2      # 监管者 ban 下拉(占 2 行: 2, 3)
ROW_BAN_END = 3
ROW_PICK = 4           # 求生者1-4 + 监管者
ROW_PICK_BTN = 5       # 随机按钮
ROW_GBAN_START = 6     # 角色全局 ban(占 2 行: 6, 7)
ROW_GBAN_END = 7
ROW_ACTIONS = 8        # 下一局 / 重置
ROW_FOOTER = 9         # 直播BP界面 / 检查角色更新

# 含下拉菜单的行。这些行需要的高度远大于开关行/按钮行, 见 screens 的行权重。
DROPDOWN_ROWS = (ROW_MAP, ROW_BAN_START, ROW_BAN_END, ROW_PICK,
                 ROW_GBAN_START, ROW_GBAN_END)

# 角色全局 ban: 每行第 1-4 位是求生者, 第 5 位是监管者 (与选取行同构)
GBAN_SURVIVOR_COLS = (0, 1, 2, 3)
GBAN_HUNTER_COL = 4

# 地图行内的列分配
MAP_COL_DROPDOWN = 0
MAP_COL_RANDOM = 1
MAP_COL_BAN1 = 3
MAP_COL_BAN2 = 4

# 地图全局 ban 的文案与角色全局 ban 同构: "全局Ban位 N（地图）"
MAP_BAN_CAPTION = "全局Ban位 %d（地图）"

BAN_SLOTS = 10         # 监管者 ban 两行合计槽位数
PICK_SLOTS = 5         # 本局选择行的槽位数
GBAN_SLOTS = 10        # 全局 ban 两行合计槽位数
MAP_BAN_SLOTS = 2      # 地图 ban 槽位数

BAN_COUNT_MIN = 0
BAN_COUNT_MAX = 10
BAN_COUNT_DEFAULT = 5

PICK_LABELS = ("求生者1", "求生者2", "求生者3", "求生者4", "监管者")

# ---------------------------------------------------------------- 直播BP界面
#
# 版式全部按 **窗口高** 等比算(基准 LIVE_DESIGN_H)。不按宽: 内容的高度预算
# 才是紧的那个 —— 头像带中心钉在画面中线上, 底部带只剩下半屏可用。
#
# 整个版式算出来是 live_window.compute_layout() 里那个**纯函数**, 与控件无关。
# 第一版渲染出来后大概率要目视微调, **改这里就够了**, 不必动结构。

LIVE_DESIGN_H = 720        # 设计基准高度

LIVE_SURV = 122            # 求生者头像边长(正方形)
LIVE_SURV_GAP = 14         # 求生者 2x2 块内的间距
LIVE_HUNTER_K = 1.32       # 监管者边长 = 该系数 x 求生者边长
LIVE_BAN = 48              # ban 槽边长
LIVE_BAN_GAP = 10          # ban 槽间距
LIVE_COL_GAP = 30          # 监管者右沿到 ban 列的间距

# 「求生者块中心与监管者中心关于竖直中线镜像对称」只约束了 **镜像**, 没约束
# 距离 —— 所以这个 d 是自由的。取小了, 求生者块会跨过中线、底部挤不出放地图
# 的地方(严格按字面时求生者块右沿 = 中线 + (2S+G)/2 - d, d 小就骑到右边去)。
# 取大还有个副作用: 左右留白会变均匀。
LIVE_D_SYM = 290           # 两个块的中心到竖直中线的距离

LIVE_PAD_BLOCK = 10        # 头像块下沿到顶部带之间的间距
LIVE_PAD_BOT = 12          # 底部下边距
LIVE_MAP_GAP = 10          # 地图 ban 行与地图之间的间距

# 全局 ban 位从"底部带上沿"再往下挪一点。
# 顶对齐在带上沿时, 全局 ban 紧贴着头像块, 看着像 2x2 块的一部分; 往下挪才有
# "这是另一组东西"的分隔感。
# 地图列**不跟着挪**: 它由带宽定尺寸(见 compute_layout), 挪了要重算, 而且它和
# 头像块之间的空档本来就比全局 ban 那边大。带宽足够 —— 两行全局 ban 的高度是
# 2*LIVE_BAN + LIVE_BAN_GAP = 106, 而 720 高下带宽有 209。
LIVE_PAD_GBAN = 16         # 全局 ban 位再往下的距离

# 边框粗细。名字带 _W 是**必须的**: 下面「直播BP界面配色」那节里有个同名的
# LIVE_BORDER 是**颜色**。撞名不会报错, 只会让先定义的那个静默失效 —— 这一版
# 就撞过, 宽度 2 被色值 "#808080" 覆盖, C.LIVE_BORDER // 2 当场 TypeError,
# 而那时窗口已经建出来了, 于是屏幕上留下一个盖在所有东西上面、关不掉的黑块。
# 第一版是 2, 操作者反馈"太细了" —— 直播画面经 OBS 缩放后再编码, 2px 的边基本
# 糊没了。4 是通看下来的手感值。**不随窗口高缩放**(不像上面那些 s() 过的常量):
# 窗口本身就是要被 OBS 抓走的那块画面, 线上的粗细是所见即所得, 不需要按屏适配。
LIVE_BORDER_W = 4          # 主位(求生者/监管者/地图)的边框粗细

# ban 位另算, 回到 2 —— 上面那条"太细"是针对 122px 的主位说的, 而 ban 位只有
# 48px: 同样 4px 的边, 在 ban 位上占掉框宽的 1/6, 一眼看过去比主位还抢, 正好
# 和 ban 位该有的"退到后面去"相反。
LIVE_BORDER_W_BAN = 2      # ban 位(含全局 ban、地图 ban)的边框粗细

# 地图素材是 403x262。目录名叫 map_square, 但里面**不是正方形**。
MAP_ASPECT = 403 / 262     # ≈ 1.5382

# 地图 ban 的边长是地图的一半, 两个并排正好等于地图宽。不是可调参数, 是定义。
LIVE_MAP_BAN_K = 0.5

# 默认窗口尺寸。None = 取第一个放得下屏幕的 16:9(和主窗口同一套逻辑)。
# 想要更高分辨率的抓取面就写死 (1920, 1080) —— 版式全按比例算, 自动跟着走,
# 代价是窗口超出屏幕(屏幕只有 1463x914), 只能拖动着分段看, 或者直接靠 OBS 抓。
LIVE_SIZE = None

# 拖动时至少留这么多像素在屏幕可视范围内。
# 无边框的 WS_POPUP 窗口**没有任务栏按钮、没有 Alt-Tab 项** —— 拖到屏幕外就只剩
# 控制台那个开关能救它, 所以不能让它整个跑出去。
LIVE_DRAG_MARGIN = 80

# 动画节拍。
#
# **滚动必须是位移, 不是换图**。第一版把一格里那张图每 45ms 换成另一张 —— 那是
# "在变", 不是"滚动", 操作者一眼就看出来了。老虎机是一条胶片从窗口里**滑过去**,
# 所以现在是: 编一条胶片(一串角色), 每拍按 time 推进一个**像素偏移**, 把偏移处的
# 那一段(跨两格, 正在出画的那张 + 正在进画的那张)拼成一帧贴上去。
#
# 滚动**速度**与动画时长无关(规格要求时长只影响"滚过多少个"):
#   - v0 是固定的像素/秒, 匀速段就是它;
#   - 时长只决定**总行程**, 行程 / 格高 = 滚过多少格;
#   - 末尾减速段占行程的一个固定比例, 这就是"最后停下的速度微调"。
LIVE_TICK_MS = 30            # 轮询 + 动画的统一节拍
LIVE_SPIN_PX_S = 1100.0      # 滚动速度(像素/秒), 固定
LIVE_SPIN_TAIL_FRAC = 0.12   # 末尾减速段占**行程**的比例
# 边框呼吸(随机命中时那一圈闪)。两样一起给才够"闪":
#   - 亮度上下限拉开到 0.5..0.95(原来是 0.5..0.9), 峰值接近纯白;
#   - 峰值时边框**同时加粗** LIVE_BREATH_GAIN 像素 —— 只有明暗变化时, 缩到
#     48px 的 ban 位上一圈 2px 的边明暗差在 OBS 里几乎看不出来。
# 颜色和加粗量共用同一个相位, 所以最白的那一拍一定也是最粗的那一拍。
#
# **频率不要动。** 上一轮"强化闪烁"时我把它从 1.0 加到 2.0 而且没吭声, 操作者
# 一眼就看了出来 —— 1Hz 是"一下一下地鼓", 2Hz 是急促的闪, 这是**节奏**变了,
# 不是强度变了。要更强就往亮度和线宽上加, 别碰这个数。
LIVE_BREATH_HZ = 1.0         # 边框呼吸频率(一个完整来回 1 秒)
LIVE_BREATH_GAIN = 2         # 峰值时边框额外加粗的像素

# ---------------------------------------------------------------- 配色
#
# THEMES 是配色的唯一来源, 紧接着就把当前主题的名字绑成模块级常量, 所以
# 全项目照旧写 C.BG / C.CARD, 读到的永远是**当前**主题的值。
#
# 改颜色时两张表都要改: 少一个键, 切主题时那个颜色会静默停在另一套主题的
# 值上(末尾那句检查就是拦这个的)。
#
# 值必须写成小写 #rrggbb。切换主题时是拿控件的**当前色值**去比对映射表的,
# 而 Tk 的 cget() 会把颜色串规范化, 写成 "#FFF" 或 "red" 就对不上了。
#
# 还有几处是刻意为之, 动之前先读这段:
#   * 两套主题之间来回切时, 色值映射必须是个**函数**: 同一个色值只能对应一个
#     新色。所以**同一个槽位在两套主题里、或者两个槽位在同一套主题里, 只要
#     同值, 另一套里也必须同值**。白天主题里 CARD/POPUP_BG/ENTRY_BG 特意取了
#     三个**互不相同**的浅色, 就是因为黑夜的那三个各不一样 —— 早先它们都写成
#     #fdfdfe, 切回黑夜时 #fdfdfe 要同时变到两个色, 直接报错。文件末尾的
#     _check_themes() 会在导入时就拦住这种写法, 不必等到用户切那一下。
#   * 白天主题**任何一个值都不是纯白**, 也是为上面那条让路。#ffffff 只留给
#     ON_ACCENT/SWITCH_KNOB, 而这两个在两套主题里都是白, 于是它永远不会成为
#     映射表的 key, 白色控件也就不会在切主题时被误伤。哪天要给某个控件设纯白,
#     先回来把这条重新想一遍。
#   * ON_ACCENT 和 SWITCH_KNOB 是两个角色不是一个: 前者叠在 ACCENT 上(按钮
#     文字、输入框选中文字), 后者坐在**开关轨道**上 —— 轨道在白天主题是浅灰,
#     白色旋钮会看不见, 所以它必须能单独调。

THEMES = {
    "dark": {
        "BG": "#1b1d22",
        "CARD": "#252932",
        "POPUP_BG": "#2a2e37",
        "FG": "#e8eaed",
        "FG_DIM": "#9aa0a6",
        "DISABLED_FG": "#5f6368",
        "BORDER": "#3c4043",
        "ACCENT": "#3b82f6",
        "ACCENT_DARK": "#2563eb",
        "DANGER": "#ef4444",
        "ENTRY_BG": "#15171b",
        "BTN_BG": "#333846",
        "BTN_HOVER": "#3d4353",
        "SWITCH_ON": "#3b82f6",
        "SWITCH_OFF": "#4b5563",
        "SWITCH_OFF_DISABLED": "#343a44",
        # 禁用但**开着**的开关用它。缺了它, 锁定期间开着的"克隆模式"会画成
        # 灰色关闭态, 直播时瞟一眼就会误判局面。
        "SWITCH_ON_DISABLED": "#2b4a75",
        "ON_ACCENT": "#ffffff",
        "SWITCH_KNOB": "#ffffff",
    },
    "light": {
        "BG": "#eef0f4",
        # CARD / POPUP_BG / ENTRY_BG 三个表面色必须**互不相同**: 黑夜的那三个
        # 各不一样, 白天这边要是撞了, 切回黑夜时那个撞车的色值就得同时变到
        # 两个新色 —— 见文件头那段说明和末尾的 _check_themes()。
        "CARD": "#f6f8fb",
        "POPUP_BG": "#fcfdfe",
        "FG": "#1f2328",
        "FG_DIM": "#656d76",
        "DISABLED_FG": "#a8aeb6",
        "BORDER": "#d0d5dd",
        "ACCENT": "#2563eb",
        "ACCENT_DARK": "#1d4ed8",
        "DANGER": "#dc2626",
        "ENTRY_BG": "#e9ecf1",
        "BTN_BG": "#e4e8ee",
        "BTN_HOVER": "#d6dbe3",
        "SWITCH_ON": "#2563eb",
        "SWITCH_OFF": "#c4cad4",
        "SWITCH_OFF_DISABLED": "#e3e6eb",
        "SWITCH_ON_DISABLED": "#9dbdf0",
        "ON_ACCENT": "#ffffff",
        "SWITCH_KNOB": "#ffffff",
    },
}

THEME_DEFAULT = "dark"
assert set(THEMES["dark"]) == set(THEMES["light"]), "两套主题的键必须一一对应"

_THEME = THEME_DEFAULT
# 把当前主题的每个颜色绑成模块级常量(C.BG 等)。
globals().update(THEMES[_THEME])


def current_theme():
    return _THEME


def _theme_mapping(src_name, dst_name):
    """算出 src 主题切到 dst 主题的 `{旧色: 新色}`。

    按**色值**重映射的前提是它得是个函数: 同一个旧色只能有一个新色。两套主题
    里同值的槽位(比如 ACCENT/SWITCH_ON), 在另一套里也必须同值, 否则就没法靠
    色值分辨谁是谁 —— 那是调色板本身的歧义, 必须报出来, 不能静默串色。
    """
    src, dst = THEMES[src_name], THEMES[dst_name]
    mapping = {}
    for key, value in dst.items():
        old = src[key]
        if old == value:
            continue          # 同色不必改; 顺带让纯白永远进不了映射表
        prev = mapping.setdefault(old, value)
        if prev != value:
            raise ValueError(
                "调色板冲突: 主题 %s→%s 时 %s 同时要映射到 %s 和 %s; "
                "同一色值在两套主题里必须落在同一个槽位上"
                % (src_name, dst_name, old, prev, value))
    return mapping


def use_theme(name):
    """切换配色, 返回 `{旧色: 新色}`, 调用方拿它就地改写已有控件的颜色。

    globals() 里放的是**字符串**, `globals().update()` 只是重新绑定模块全局,
    不会改到 THEMES 里那张表 —— 所以来回切能切回去。

    真值以 THEMES[_THEME] 为准而不是以当前 globals() 为准: 两者本来就该一致,
    但快照式地读表, 就不会因为别处手滑写了 C.CARD = "..." 而算错映射。
    """
    global _THEME
    mapping = _theme_mapping(_THEME, name)
    globals().update(THEMES[name])
    _THEME = name
    return mapping


# 导入时就查一遍两个方向。放在这里而不是等用户切那一下才报: 一旦有人往调色板
# 里加了个撞车的颜色, 程序当场打不开, 比"某次切主题之后界面串了色"好找得多。
for _a, _b in (("dark", "light"), ("light", "dark")):
    _theme_mapping(_a, _b)
del _a, _b


# ---------------------------------------------------------------- 直播BP界面配色
#
# **刻意不进 THEMES**: 这是给 OBS 抓的播出画面, 黑底灰框是固定的, 不跟皮肤变。
#
# 两条硬规矩(写死在 _retheme_tree 里也拦了, 但这里再说一遍):
#   1. 直播窗口模块里**不许出现 C.* 的调色板常量** —— 换肤遍历会递归进
#      Toplevel, 一旦用了调色板常量, 切皮肤就会把播出画面改了色。
#   2. 这几个值**不能和 THEMES 里任何一个值相同**。_check_themes() 只校验
#      调色板自洽, 管不到控件颜色 —— 将来有人往 THEMES 里加一个中间灰
#      (#808080 是个很自然的浅色边框候选), 就会把 ban 位边框悄悄改掉。
#      末尾的 _check_live_colors() 在导入时拦住这种撞车。
#
def grey(level):
    """把 0..1 的灰度值变成 #rrggbb。边框呼吸每帧要算一次, 不查表。"""
    level = max(0.0, min(1.0, float(level)))
    v = int(round(level * 255))
    return "#%02x%02x%02x" % (v, v, v)


# 三个灰度值是用户给的(0 黑 1 白)。呼吸在 0.5 和 0.9 之间来回 —— 把**灰度**留成
# 常量、颜色由 grey() 派生, 呼吸那一头就不会和边框色各改各的、悄悄对不上。
LIVE_BREATH_LO = 0.5
LIVE_BREATH_HI = 0.95

LIVE_BG = "#000000"                    # 窗口底 —— 纯黑, 也是唯一的"空白"色

# 窗口背景图(相对 base_dir)。
# 它是**铺在最底下的一张图**, 不是槽位底色 —— 槽位仍是不透明的 0.05 灰(规格),
# 所以图只出现在槽位之外的空处。
# 三种情况都静默退回纯黑 LIVE_BG, 不影响出图: 文件不在、图片打不开、或者这台机器
# 上的 Pillow 没编 JPEG 解码器。
LIVE_BG_IMAGE = "bg.jpg"

# 背景图的两个强度旋钮。原图是张高饱和的插画, 直接铺上去比前景(近黑底 + 灰框)
# 抢眼, 看着是"一张图 + 盖在上面的黑块"而不是一个整体, 所以降一点饱和。两个都
# 写 1.0 就是原图。
#
# **只降饱和, 不压亮度。** 上一版是 0.55 + 0.85, 操作者一句"这背景也太灰了"就打
# 回来了 —— 压亮度那一下是我自己加的, 没人要过。**灰是亮度掉下来造成的, 饱和掉
# 一点不会灰。** 以后要调也先动饱和, 亮度留在 1.0。
LIVE_BG_SAT = 0.8          # 饱和度倍数
LIVE_BG_BRIGHT = 1.0       # 亮度倍数(1.0 = 不压)
LIVE_SLOT = grey(0.05)                 # 槽位底色 = 0.05 灰

# 槽位底色压在背景图上时的**不透明度**。1.0 = 原来的实心 #0d0d0d, 一格像素不差。
#
# 叫"不透明度"而不是"透明度": 名字要能一眼看出 1.0 是**关掉**这个特性, 不然调参
# 的人得停下来想一下哪个方向才是"没有"。
#
# 0.05 灰本来就很暗, 透出来的分量越多背景越显。**别调太小** —— 底色一透, 头像
# 的抠图边界就和背景糊在一起了, 48px 的 ban 位上尤其明显。
LIVE_SLOT_ALPHA = 0.75
LIVE_BORDER = grey(LIVE_BREATH_LO)     # 槽位边框 = 0.5 灰
LIVE_BORDER_HOT = grey(LIVE_BREATH_HI) # 呼吸峰值。不用 #ffffff: 那是 ON_ACCENT /
                                       # SWITCH_KNOB 的值, 虽然它永远不会成为映射
                                       # 表的 key(两套主题同值), 但没必要贴着走。

LIVE_COLORS = {
    "BG": LIVE_BG,
    "SLOT": LIVE_SLOT,
    "BORDER": LIVE_BORDER,
    "BORDER_HOT": LIVE_BORDER_HOT,
}


def _check_live_colors():
    """直播配色不能和任何一套主题的值撞车。

    _check_themes() 只校验调色板**自洽**, 管不到控件颜色 —— 将来有人往 THEMES
    里加一个中间灰(#808080 是个很自然的浅色边框候选), 就会在切皮肤时把 ban 位
    的边框悄悄改掉。导入时就查, 不等用户切那一下才发现。
    """
    clash = {}
    for name, table in THEMES.items():
        for key, value in table.items():
            for live_key, live_value in LIVE_COLORS.items():
                if value == live_value:
                    clash.setdefault(live_value, []).append("%s.%s" % (name, key))
    if clash:
        raise ValueError(
            "直播配色与调色板撞车: %s —— 换肤时会把直播画面一起改掉, 换个色值"
            % "; ".join("%s == %s" % (v, ", ".join(ks))
                        for v, ks in clash.items()))


_check_live_colors()

# 防呆: 配色和版式共用 C 的命名空间。撞名不报错, 只会让**先定义的那个静默
# 失效**(见上面 LIVE_BORDER_W 那段), 所以在这里把版式侧的几个点一遍名。
for _n, _t in (("LIVE_BORDER_W", int), ("LIVE_BORDER_W_BAN", int),
               ("LIVE_SURV", int), ("LIVE_BAN", int), ("LIVE_PAD_GBAN", int),
               ("LIVE_D_SYM", int), ("LIVE_DESIGN_H", int),
               ("LIVE_SLOT_ALPHA", float)):
    assert isinstance(globals()[_n], _t), \
        "直播版式常量 %s 被后面的定义覆盖了(现在是个 %s)" % (
            _n, type(globals()[_n]).__name__)
del _n, _t


# ---------------------------------------------------------------- 配置持久化
#
# 写在程序目录下(打包成 exe 后就是 exe 旁边), 和"字体用 FR_PRIVATE 注册、
# 不改系统"是同一个绿色风格。

SETTINGS_FILE = "settings.json"

ANIM_MIN = 0.0         # 动画时长(秒)。设成 0 = 关掉随机后的点击锁定
ANIM_MAX = 10.0
ANIM_STEP = 0.1
ANIM_DEFAULT = 3.0

# rule_banned: **规则禁用**的角色名列表 —— 本场比赛不允许出现的角色。随机池和
# 下拉候选都过滤掉, 已经选在格子上的会在 apply_rules() 里被清掉。
# 存的是名字(str)而不是下标: 名册是按目录内容重建的, 下标会随着新增角色整体
# 错位, 那是"禁用了一个角色却禁到了另一个"这种查不出来的错。
#
# seen_version: **最近一次看过的更新日志版本号**(不带 v)。程序启动时拿它和
# APP_VERSION 比, 不一致就弹一次更新日志(见 screens.App._maybe_show_changelog)。
# 空串 = 还没看过任何一版 —— 全新装机就是这个状态, 所以**新装也会弹一次**,
# 那是有意的(刚装好的人同样想知道这一版有什么)。
SETTINGS_DEFAULT = {"theme": THEME_DEFAULT, "animation_seconds": ANIM_DEFAULT,
                    "rule_banned": [], "seen_version": ""}


def settings_path():
    return os.path.join(base_dir(), SETTINGS_FILE)


def load_settings():
    """读 settings.json。

    文件不存在 / 不是合法 JSON / 字段越界 —— 一律**逐字段**回退到默认值,
    绝不抛异常。配置文件是用户能手改的东西, 改坏了不该打不开程序。
    """
    data = dict(SETTINGS_DEFAULT)
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    if raw.get("theme") in THEMES:
        data["theme"] = raw["theme"]
    try:
        seconds = float(raw.get("animation_seconds"))
    except (TypeError, ValueError):
        pass
    else:
        data["animation_seconds"] = max(ANIM_MIN, min(ANIM_MAX, seconds))
    # 规则禁用名单: 只认**字符串**, 非列表/非字符串一律当没写。
    # 不做"名字是否还在名册里"的校验 —— 那个只有 Roster 知道, 而 config 是
    # 在 Roster 之前加载的(见 screens.App.__init__ 的顺序)。名册里已经没有的
    # 名字留在表里无害: 它永远匹配不到任何 Item, 过滤时白过一遍而已。
    # 顺手去重, 手改过 json 的人不会因此在界面上看到重复项。
    raw_banned = raw.get("rule_banned")
    if isinstance(raw_banned, list):
        data["rule_banned"] = sorted({s for s in raw_banned if isinstance(s, str)})
    # 看过的版本号: 只认字符串。这里**不校验它是不是合法版本号** —— 校验要
    # parse_version, 那在 updater 里, 而 updater 反过来 import config, 模块级
    # 互相 import 会成环。值不对的后果只是多弹一次日志, 不值得为它解这个环。
    if isinstance(raw.get("seen_version"), str):
        data["seen_version"] = raw["seen_version"]
    return data


def save_settings(data):
    """写 settings.json。目录只读等情况静默跳过 —— 记不住设置, 但不该崩。"""
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

# ---------------------------------------------------------------- 字号
#
# 全部以"设计稿像素"为单位, 经 px() 换算到当前窗口尺寸。
# 想整体调大调小, 改这里就够了 —— 界面里不要再写死字号。

FONT_CAPTION = 15      # 每个格子顶部的说明文字
FONT_BODY = 20         # 下拉框 / 输入框 / 列表项
FONT_BUTTON = 18       # 普通按钮
FONT_SMALL = 14        # 状态提示等次要文字
FONT_ARROW = 16        # 下拉箭头

# 头像缩略图。列表行里的那张要略小于行高, 留出一点呼吸空间。
THUMB_ROW_PX = 38      # 下拉列表行内的头像
THUMB_SEL_PX = 30      # 输入框左侧的已选头像

# 首选字体族 —— 第五人格国服正文用的就是"华康POP1体W5"。
# 同一个字体各版本报出来的族名不一样, 所以多列几个别名; 顺序 = 优先级。
# 无论是 fonts/ 里自带的还是用户自己装进系统的, 只要 Tk 看得见就会被选中。
FONT_FAMILY_PREFERRED = (
    "华康POP1体W5",
    "华康POP1体W5(P)",
    "DFPOP1W5-GB",
    "DFPOP1W5",
    "DFPOP1W5-B5",
)

# 等宽字体族, 顺序 = 优先级。只给**更新日志里的代码块**用(见 font 下面那一节)。
# 这几个都不含中文 —— 中文会不会因此变成方框, 由调用方决定(用 mono_for)。
MONO_FAMILY_PREFERRED = ("Consolas", "Cascadia Mono", "Courier New")

# ---------------------------------------------------------------- 字体

_FAMILY = None
_SCALE = 1.0
_LOADED_FAMILIES = []      # fonts/ 里注册成功的字体族名, 由 register_fonts() 填


# 名字只认这三个: 1=家族名, 4=全名, 16=排版家族名
_NAME_IDS = (1, 4, 16)


def _font_names(path):
    """读出一个字体文件**可能被叫到的所有名字**。

    同一个字体在不同场合名字不一样: 楷体的英文名是 "KaiTi", 而 Tk 报的是
    "楷体"; 华康POP也一样, 中文名 "华康POP1体W5" / 英文名 "DFPOP1W5-GB"
    都会出现在 name 表里。只取一个名字去比对, 换台机器或换个版本就认不出来,
    所以全都收着, 拿任意一个和 Tk 的字体列表比对都能对上。

    直接解析 name 表, 不依赖 Pillow —— 这样 config 模块不引入额外依赖。
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if len(data) < 12:
        return []
    if data[:4] == b"ttcf":       # 字体集合: 表目录结构不同, 交给调用方兜底
        return []
    try:
        num_tables = struct.unpack(">H", data[4:6])[0]
        name_off = None
        for i in range(num_tables):
            rec = 12 + i * 16
            if rec + 16 > len(data):
                return []
            if data[rec:rec + 4] == b"name":
                name_off = struct.unpack(">I", data[rec + 8:rec + 12])[0]
                break
        if name_off is None or name_off + 6 > len(data):
            return []
        count, str_off = struct.unpack(">HH", data[name_off + 2:name_off + 6])
        base = name_off + str_off
        names = []
        for i in range(count):
            rec = name_off + 6 + i * 12
            if rec + 12 > len(data):
                break
            plat, _enc, _lang, nid, length, off = struct.unpack(
                ">HHHHHH", data[rec:rec + 12])
            # 平台 0/3 的字符串都是 UTF-16BE; 平台 1(Mac Roman) 解码麻烦, 跳过
            if nid not in _NAME_IDS or plat not in (0, 3):
                continue
            try:
                s = data[base + off:base + off + length].decode("utf-16-be").strip()
            except UnicodeDecodeError:
                continue
            if s and s not in names:
                names.append(s)
        return names
    except (struct.error, IndexError):
        return []


def _pil_family(path):
    """name 表解析不了(比如 .ttc)时的兜底: 问 Pillow 要一个英文族名。"""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(path, 12).getname()[0]
    except Exception:
        return None


def register_fonts():
    """把 fonts/ 目录里的字体注册给**本进程**。必须在 tk.Tk() 之前调用。

    Windows 上光把 ttf 放进目录, Tk 是看不见的 —— 得先 AddFontResourceExW
    注册。FR_PRIVATE(0x10) 表示只给本进程用, 不改动用户的系统字体库,
    所以这个工具拷到别的机器上依然是"绿色"的。

    返回注册成功的字体族名列表; 目录不存在或不是 Windows 就返回空。
    """
    if sys.platform != "win32":
        return []
    folder = os.path.join(base_dir(), DIR_FONT)
    if not os.path.isdir(folder):
        return []
    try:
        import ctypes
        gdi = ctypes.windll.gdi32
    except Exception:
        return []

    names = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
            continue
        path = os.path.join(folder, fn)
        if not gdi.AddFontResourceExW(ctypes.c_wchar_p(path), 0x10, 0):
            continue
        got = _font_names(path) or [n for n in (_pil_family(path),) if n]
        names.extend(n for n in got if n not in names)
    _LOADED_FAMILIES[:] = names
    global _FAMILY
    _FAMILY = None            # 之前的缓存(可能已是回退字体)作废
    return names


def loaded_fonts():
    """fonts/ 里注册成功的字体的所有已知名字(含中英文别名)。"""
    return list(_LOADED_FAMILIES)


def family():
    """最终选中的字体族名。"""
    return _pick_family()


def _pick_family():
    """挑字体族: 先用 fonts/ 里自带的, 没有才退回系统里支持中文的。"""
    global _FAMILY
    if _FAMILY is not None:
        return _FAMILY
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
    except Exception:
        # 还没有 Tk 根窗口, 问不出字体列表。**这个结果不能缓存** ——
        # 否则根窗口建好之后会一直用着回退字体, 而且看起来毫无异常。
        return "TkDefaultFont"
    for name in list(FONT_FAMILY_PREFERRED) + _LOADED_FAMILIES + \
            ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun"]:
        if name in available:
            _FAMILY = name
            return _FAMILY
    _FAMILY = "TkDefaultFont"
    return _FAMILY


def set_scale(scale):
    """由 App 在选定窗口尺寸后调用。"""
    global _SCALE
    _SCALE = float(scale)


def scale():
    return _SCALE


def px(value):
    """把设计稿像素换算成当前尺寸下的像素。"""
    return int(round(value * _SCALE))


def font(size_px, weight="normal", slant="roman"):
    """负数字号 = Tk 语义的像素高度，避免受 tk scaling 影响。

    weight / slant 直接交给 Tk: **华康POP1 只有一个字面, 但 Windows 会合成出
    粗体和斜体** —— 实测同一串字 normal/bold/italic 三种渲染的像素差在 3700
    以上, 是看得出来的。所以更新日志的 markdown 里 **粗体** 和 *斜体* 能落地,
    不需要另配字体。(代价: 合成体不如真字面好看, 但总比"支持了却看不出"强。)
    """
    return (_pick_family(), -max(1, px(size_px)), weight, slant)


def mono(size_px, weight="normal"):
    """等宽字体。**不管内容有没有中文** —— 要按内容挑就用 mono_for()。

    找不到任何一个候选就退回界面字体: 代码块因此变成普通字, 但仍然能读,
    比抛异常或显示成空白强。
    """
    names = _available_mono()
    if names:
        return (names[0], -max(1, px(size_px)), weight)
    return font(size_px, weight)


def mono_for(text, size_px, weight="normal"):
    """按内容挑等宽还是界面字体。

    Windows 的等宽字体(Consolas 这些)都不含汉字, 缺字靠 GDI 的字体链接补
    —— 补出来的字号和基线跟旁边的字对不齐, 一行里两种字体比不换还难看。
    所以代码块里只要有非 ASCII 字符, 就整块用界面字体, 靠底色区分。
    """
    if all(ord(ch) < 128 for ch in text):
        return mono(size_px, weight)
    return font(size_px, weight)


def _available_mono():
    """系统里真正装了的等宽字体族(按优先级)。量不出来就返回空。"""
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
    except Exception:
        # 还没有 Tk 根窗口, 问不出字体列表(同 _pick_family 那条注释)。
        return []
    return [n for n in MONO_FAMILY_PREFERRED if n in available]

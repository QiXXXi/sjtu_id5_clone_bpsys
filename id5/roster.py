#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色/地图数据加载、拼音检索、头像缩略图缓存。"""

import os
from dataclasses import dataclass, field

from . import config as C

# pypinyin 是可选依赖: 缺失时降级为纯子串匹配, 不能让程序崩掉
try:
    from pypinyin import lazy_pinyin, Style
    PINYIN_OK = True
except ImportError:                                    # pragma: no cover
    PINYIN_OK = False

PINYIN_HINT = "" if PINYIN_OK else "未安装 pypinyin，拼音搜索不可用（pip install pypinyin）"


class RosterError(Exception):
    """角色图片目录缺失。"""


@dataclass(frozen=True)
class Item:
    """一个可选项。value 既是显示名也是存进变量里的值。"""
    value: str          # 规范名(角色名 / 地图中文名)
    label: str          # 显示文本(与 value 相同, 保留以便将来区分)
    avatar: str         # 头像 PNG 的绝对路径, 缺失时为空串
    initials: str       # 拼音首字母, 如 "cz"
    pinyin: str         # 全拼, 如 "changzhang"


def _keys(name):
    """算拼音检索键。任何异常都退化为空串, 不影响中文子串匹配。"""
    if not PINYIN_OK:
        return "", ""
    try:
        init = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER, errors="default"))
        full = "".join(lazy_pinyin(name, errors="default"))
        return init.lower(), full.lower()
    except Exception:
        return "", ""


def item_matches(item, query):
    """查询按空格切词, 每个词都要命中 首字母/全拼/中文 三者之一。"""
    q = (query or "").strip().lower()
    if not q:
        return True
    keys = (item.initials, item.pinyin, item.label.lower())
    for token in q.split():
        if not any(token in key for key in keys):
            return False
    return True


# ---------------------------------------------------------------- Roster

class Roster:
    """扫描图片目录构建三个列表。

    groups 里的 list 对象只创建一次, reload() 原地 clear+extend,
    这样 25 个下拉菜单按引用共享同一列表, 新增角色后无需逐个通知控件。
    """

    def __init__(self, base):
        self.base = base
        self.groups = {"survivor": [], "hunter": [], "map": []}
        self.index = {}          # value -> Item, 跨组。见 lookup()
        self.reload()

    # -- 扫描 ----------------------------------------------------------

    def reload(self):
        """重新扫描目录, 原地更新三个列表。返回是否有变化。"""
        found = {
            "survivor": self._scan_chars(C.DIR_SURVIVOR),
            "hunter": self._scan_chars(C.DIR_HUNTER),
            "map": self._scan_maps(),
        }
        changed = False
        for key, items in found.items():
            bucket = self.groups[key]
            if [i.value for i in bucket] != [i.value for i in items]:
                changed = True
            bucket.clear()
            bucket.extend(items)
        # index 是**派生**数据, 可以随便重建 —— 上面那几个 list 才是要被
        # 各处共享引用的东西, 所以它们只原地改。
        self.index = {it.value: it for items in self.groups.values() for it in items}
        return changed

    def lookup(self, value):
        """按值找 Item。找不到返回 None。

        直播窗口每拍都要把 28 个槽位的值翻成 Item, 所以走 O(1) 的表。
        值可能**已经不在名册里**了(角色被删掉、或名册重扫过), 调用方必须
        处理 None。
        """
        return self.index.get(value) if value else None

    def _scan_chars(self, dirname):
        """角色: 文件名主干即角色名。"""
        directory = os.path.join(self.base, dirname)
        if not os.path.isdir(directory):
            raise RosterError("找不到图片目录:\n%s\n\n请先运行「检查角色更新」或确认程序位置。" % directory)
        items = []
        for entry in sorted(os.listdir(directory)):
            if not entry.lower().endswith(".png"):
                continue
            name = os.path.splitext(entry)[0]
            init, full = _keys(name)
            items.append(Item(value=name, label=name,
                              avatar=os.path.join(directory, entry),
                              initials=init, pinyin=full))
        return items

    def _scan_maps(self):
        """地图: 英文文件名 -> 中文显示名。"""
        directory = os.path.join(self.base, C.DIR_MAP)
        if not os.path.isdir(directory):
            return []
        items = []
        for entry in sorted(os.listdir(directory)):
            if not entry.lower().endswith(".png"):
                continue
            stem = os.path.splitext(entry)[0]
            label = C.MAP_NAMES.get(stem, stem)
            init, full = _keys(label)
            items.append(Item(value=label, label=label,
                              avatar=os.path.join(directory, entry),
                              initials=init, pinyin=full))
        return items

    # -- 查询 ----------------------------------------------------------

    def all_items(self):
        for items in self.groups.values():
            for item in items:
                yield item


# ---------------------------------------------------------------- 缩略图

class ThumbCache:
    """缩略图缓存: 下拉列表/选中态(固定正方形), 以及直播窗口(任意尺寸 + 灰度)。

    必须一直持有全部 PhotoImage 引用直到程序退出:
    Canvas.create_image 只存图片名不存 Python 引用, 被 GC 回收后
    那一行会静默变成空白。这是 canvas 图片最常见的坑。

    代价是**缓存只能变大, 不能淘汰** —— 淘汰掉的图若还被某个 canvas 图元
    引用着, 那一格同样会静默变空白, 不报错。所以直播窗口那边刻意不做拖拽
    缩放(见 config.LIVE_SIZE 的注释): 每拖一个像素就会多出一整套尺寸。
    """

    ROW_PX = C.THUMB_ROW_PX
    SEL_PX = C.THUMB_SEL_PX

    def __init__(self):
        self._row = {}          # value -> (stamp, PhotoImage)
        self._sel = {}
        self._cut = {}          # (group, value, w, h, gray) -> (stamp, (rgb, alpha))
        self._placeholder = {}  # size -> 透明占位图

    def warm(self, items):
        """解码并缓存下拉列表用的两张缩略图。可重复调用以补齐新角色。"""
        from PIL import Image, ImageTk
        row_px, sel_px = C.px(self.ROW_PX), C.px(self.SEL_PX)
        for item in items:
            stamp = _stamp(item)
            if self._row.get(item.value, (None,))[0] == stamp:
                continue          # 同一张图, 已经在了
            try:
                master = Image.open(item.avatar).convert("RGBA")
            except Exception:
                # 单张坏图不能拖垮整个程序
                master = Image.new("RGBA", (C.px(144), C.px(144)), (0, 0, 0, 0))
            self._row[item.value] = (stamp, ImageTk.PhotoImage(
                master.resize((row_px, row_px), Image.LANCZOS)))
            self._sel[item.value] = (stamp, ImageTk.PhotoImage(
                master.resize((sel_px, sel_px), Image.LANCZOS)))

    def row_thumb(self, item):
        entry = self._row.get(item.value)
        if entry is not None and entry[0] == _stamp(item):
            return entry[1]
        return self.placeholder(self.ROW_PX)

    def sel_thumb(self, item):
        entry = self._sel.get(item.value)
        if entry is not None and entry[0] == _stamp(item):
            return entry[1]
        return self.placeholder(self.SEL_PX)

    # -- 直播窗口 ------------------------------------------------------

    def cutout(self, item, group, w, h, gray=False):
        """直播窗口用的抠图: 缩到 (w,h), **预乘**, 可选灰度。返回 (rgb, alpha)。

        为什么返回两张而不是一张合成好的图: 槽位底下现在是一块**背景图的裁片**
        (见 LIVE_SLOT_ALPHA), 每格都不一样, 合成好的图没法按 (角色, 尺寸) 缓存,
        缓存会炸成"角色 x 槽位"那么大。拆成 (预乘 RGB, alpha) 之后只有角色和尺寸
        进键, 合成交给调用方 —— PIL 那句 paste(rgb, (x, y), alpha) 算的正好是
        dst*(1-a) + rgb*a, 就是预乘的正确合成式, 而且**自动裁掉超出目标框的部分**
        (滚动动画正靠这个把胶片切在槽位里)。

        group 要进键: Item.value 和 Item.label 相同, 角色值来自文件名、地图值
        来自 MAP_NAMES, 撞车概率低但白防。

        按需加载。**调用方要保证动画会滚到的那些角色提前 warm_live 过** ——
        老虎机一刀下去可能遍历整个候选池, 冷启动一帧要卡好几百毫秒。
        """
        from PIL import Image
        key = (group, item.value, w, h, bool(gray))
        stamp = _stamp(item)
        entry = self._cut.get(key)
        if entry is not None and entry[0] == stamp:
            return entry[1]
        try:
            master = Image.open(item.avatar).convert("RGBA")
        except Exception:
            master = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        out = _cutout(master, w, h, gray)
        self._cut[key] = (stamp, out)
        return out

    def warm_live(self, items, group, w, h, gray=False):
        for item in items:
            self.cutout(item, group, w, h, gray=gray)

    # -- 占位 ----------------------------------------------------------

    def placeholder(self, size_px):
        """全透明占位图。tk.Label 没图时宽高会按文字单位算, 所以必须给一张。"""
        key = size_px
        if key not in self._placeholder:
            from PIL import Image, ImageTk
            px = C.px(size_px)
            img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
            self._placeholder[key] = ImageTk.PhotoImage(img)
        return self._placeholder[key]


def _stamp(item):
    """头像文件的 (路径, mtime)。

    缓存键里必须带上它。「检查角色更新」会换掉磁盘上的 PNG, 而 warm() 是
    "已缓存就跳过" —— 不比 mtime 的话, 缩略图在**整个进程生命周期**里都是旧
    的。38px 的下拉列表里看不出来, 200px 的直播画面上一眼就是另一个角色。
    """
    try:
        return (item.avatar, os.path.getmtime(item.avatar))
    except OSError:
        return (item.avatar, 0)


def _cutout(master, w, h, gray):
    """抠图 -> 缩到 (w,h) 的 (预乘 RGB, alpha), 需要的话取灰度。

    **预乘, 不是"合成到底色"**: 槽位底下现在是一块背景图的裁片(见
    config.LIVE_SLOT_ALPHA), 每格底色都不一样, 烘死在某一个底色上就废了。
    改成返回 (预乘 RGB, alpha) 让调用方现合成 —— PIL 的
    `base.paste(rgb, (x, y), alpha)` 算的正是 dst*(1-a) + rgb*a, 就是预乘
    的正确合成式。

    **顺序还是"先乘、后缩"**: 素材全是带透明通道的抠图(colortype 6), 它们的
    透明像素 RGB 通常是 (0,0,0)。直接 resize RGBA 再合成, LANCZOS 会从这些
    "透明的黑像素"里带出**一圈暗边** —— 38px 的下拉列表里看不出来, 200px 的
    直播画面上一眼可见。全分辨率下先乘掉(透明像素一律变 0), 缩放就干净了。
    预乘之后 rgb 和 alpha 是两张独立的图, 各缩各的, 这是标准的预乘缩放。

    灰度也**不能写 master.convert("L")**: 那会连 alpha 一起丢掉, ban 位会
    变成一块不透明的灰方块, 而不是抠影。取灰度要在**预乘之后** —— 三个通道
    都已经乘过 alpha, 线性组合出来还是预乘的灰, 合成到任何底色上都对。
    """
    from PIL import Image, ImageChops
    w, h = max(1, int(w)), max(1, int(h))
    master = master.convert("RGBA")
    alpha = master.getchannel("A")
    rgb = ImageChops.multiply(master.convert("RGB"), alpha.convert("RGB"))
    if gray:
        from PIL import ImageOps
        rgb = ImageOps.grayscale(rgb).convert("RGB")    # 灰度同样是预乘的
    return (rgb.resize((w, h), Image.LANCZOS),
            alpha.resize((w, h), Image.LANCZOS))


# 全应用共用一个缓存。实例化本身不碰 Tk, 但 warm() 必须在 Tk() 之后调用。
THUMBS = ThumbCache()

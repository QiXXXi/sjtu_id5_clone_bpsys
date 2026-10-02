#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新日志窗: 左边一列版本, 右边看那一版改了什么。

两个入口, 用的是同一个窗口:

  * 设置 → 「版本」一栏的「更新日志」按钮(手动看);
  * 程序更新后第一次启动, 自动弹一次(见 screens.App._maybe_show_changelog)。

正文就是发版时在 publish.py 里填的那段说明 —— GitHub Releases 的 release 正文
原样搬过来。所以**没有第二处需要维护的更新日志**: 发版时写了什么, 这里就显示
什么, 忘了写就是空的。

## 数据从哪来

先读本地缓存(updater.cached_releases), 秒开; 缓存不新鲜了才去联网, 拿到的新
表再覆盖回来。所以断网也能看历史日志, 而且**不会每次打开都请求 GitHub**。
启动时那次 check() 也会把最新一版的说明并进缓存 —— 于是"更新完第一次打开"
那个弹窗是**零请求**的。

## 线程

联网那一段走后台线程 + queue.Queue + after 轮询。关窗时 _alive 落下来, 轮询
自己停, 迟到的结果被丢掉(不碰已 destroy 的控件 —— 那会抛 TclError)。

## markdown

release 正文是 markdown, 这里自己渲染。**不引第三方库** —— 这个程序要打包成
exe 发给别人, 每多一个依赖就多一份体积和一份 import 失败的可能(同 updater
模块头那条理由)。支持的范围:

    标题 # ~ ######        粗体 **x** / __x__      斜体 *x* / _x_
    无序列表 - * +         有序列表 1.            引用 >
    围栏代码 ``` / ~~~     行内代码 `x`           链接 [文字](地址)

**不支持**: 表格、图片、嵌套引用、列表套列表、HTML、任务列表。
`---` 分隔线渲染成一个空行(见 _iter_blocks 里那条注释)。

## 字号为什么不跟着 C.FONT_SMALL

这是**拿来看长文**的窗口, 而 FONT_SMALL 是状态栏那种"瞟一眼"的次要文字尺寸。
两者用途不同, 所以正文有自己的一套字号(BODY_PX 起), 标题在它上面递进。

## tag 为什么这么绕

Tk 里同一段文字上叠两个 tag, 同**一个选项**是"优先级高的整个盖掉低的", 不是
逐项合并。行内加粗只关掉 weight 的话, 会把标题那个字号一起顶掉。所以这里
把"块级版式(缩进/行距/底色)"和"行内外观(字体/颜色)"**合成一个 tag** 再配置
—— 见 _tag() 和 _tag_options()。
"""

import queue
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from tkinter import ttk

from . import config as C
from . import updater

# 版式。只有这一个窗口用, 所以留在本模块(同 rule_ban_window 那一节的理由)。

# 窗口占主窗口的比例。**不直接用 C.SETTINGS_SIZE**(那是 1024x680): 更新日志是
# 大段文字, 挤在那么小的窗口里一行放不下几个字。取主窗口的 92%, 既明显变大,
# 又不至于把控制台完全盖住 —— 操作者常常要一边看日志一边对照控制台。
WINDOW_FRACTION = 0.92

# 正文字号(设计稿像素)。理由见模块头。
BODY_PX = 17
TITLE_PX = 22
META_PX = BODY_PX - 2
# 标题递进。h4~h6 一律按 h3 处理 —— 再小就和正文分不出来了。
HEAD_PX = {1: BODY_PX + 7, 2: BODY_PX + 4, 3: BODY_PX + 2}
HEAD_MIN = BODY_PX + 1
# 列表每嵌套一层的右移量。
INDENT_STEP = 18

# 侧边栏宽度是**量出来的**, 不是写死的: 条目文字是"v1.1.0 · 2026-10-03 ← 当前",
# 宽多少取决于字体(华康POP1 有就用, 没有就退回系统字体, 两者差得不小)。写死一个
# 数就得在"能把'← 当前'显示全"和"别占掉小半屏"之间赌一把, 赌输了是**静默截断**
# —— 列表项没有省略号, 直接从右边切掉, 看着像标签本来就这么长。
SIDE_MIN = 200        # 侧边栏宽的下限
SIDE_MAX = 340        # 上限: 再长就宁可截, 不能让它吃掉半个窗口
SIDE_EXTRA = 34       # 列表的内边距(6*2) + 滚动条宽
POLL_MS = 120         # 轮询间隔。只等一次网络请求, 没必要更密。

# 正文里这一段是 publish.py 自动追加的"下载"小节(安装包名/大小/SHA256)。
# 那是给下载页看的, 不是"这一版改了什么" —— 用户要的是他在发版时填的那段文字,
# 所以显示前把它切掉。切法用换行 + "## 下载", 正常手打的小标题不会正好是这个
# 写法(手打的话通常不会前面刚好空一行再接 ##)。
_DOWNLOAD_SECTION = "\n## 下载"

# 块级"版式"的种类。和"外观"分开, 见模块头最后一节。
_LAYOUT_KINDS = ("body", "title", "meta", "h", "quote", "bullet", "number",
                 "codeblock")


# ---------------------------------------------------------------- markdown

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^([-*_])(?:\s*\1){2,}$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")

# 行内。分支顺序**是有意的**: 行内代码排最前, 这样 `**x**` 不会被当成粗体
# (代码里的星号是字面量); 链接在粗体之前, 否则 [**a**](u) 会先被粗体吃掉。
#
# 两端各加了一条"边界"约束, 防的是纯文本被误判:
#   * 开头的 (?!\s) / 结尾的 (?<!\s) —— `2 * 3 * 4` 不是斜体;
#   * 下划线的 (?<![0-9A-Za-z_]) / (?![0-9A-Za-z]) —— `snake_case_name`
#     里的 _case_ 不是斜体(这是最常见的误判)。
_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<link>\[[^\]\n]*\]\([^)\s]+\))"
    r"|(?P<bold>\*\*(?!\s)[^*\n]*?(?<!\s)\*\*"
    r"|(?<![0-9A-Za-z_])__(?!\s)[^_\n]*?(?<!\s)__(?![0-9A-Za-z]))"
    r"|(?P<italic>\*(?!\s)[^*\n]*?(?<!\s)\*"
    r"|(?<![0-9A-Za-z_])_(?!\s)[^_\n]*?(?<!\s)_(?![0-9A-Za-z]))"
)


def _iter_blocks(lines):
    """把正文切成块, 产出 (kind, payload)。

    kind: "h" (级别, 文字) / "p" 文字 / "bullet" (缩进层, 文字) /
          "number" (缩进层, 序号, 文字) / "quote" 行表 / "code" 整段文字 /
          "rule" 无

    **一段一行, 不做"连续几行并成一段"**: 发版说明是人在文本框里手打的,
    换行就是他想要的换行。按真正的 markdown 规则把软换行并成一段, 会把他
    特意分行的内容挤成一坨。
    """
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            i += 1
            buf = []
            while i < n and not lines[i].lstrip().startswith(fence):
                buf.append(lines[i])
                i += 1
            i += 1                       # 吃掉收尾的围栏(没有就吃到末尾)
            yield ("code", "\n".join(buf))
            continue

        if not stripped:
            i += 1
            continue

        # 分隔线渲染成空行。**不画真横线**: 一个 tag 管一整行, 没法只给行中间
        # 画一条线; 拿空格加背景色拼一条, 窗口一窄就会折行折出两条; 用 ─ 这类
        # 制表符又得赌字体里有这个字形(没有就是一排方框)。发版说明里 --- 很少见,
        # 不值得为它冒这个险。
        if _RULE.match(stripped):
            yield ("rule", "")
            i += 1
            continue

        m = _HEADING.match(stripped)
        if m:
            yield ("h", (len(m.group(1)), m.group(2)))
            i += 1
            continue

        if _QUOTE.match(line):
            buf = []
            while i < n and _QUOTE.match(lines[i]):
                buf.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            yield ("quote", buf)
            continue

        m = _BULLET.match(line)
        if m:
            yield ("bullet", (len(m.group(1)) // 2, m.group(2)))
            i += 1
            continue

        m = _NUMBER.match(line)
        if m:
            yield ("number", (len(m.group(1)) // 2, m.group(2), m.group(3)))
            i += 1
            continue

        yield ("p", stripped)
        i += 1


def _inline_runs(text):
    """把一行文字切成 (片段, 样式元组) 序列。

    样式元组里的元素: "b" 粗 / "i" 斜 / "ic" 行内代码 / "link:<地址>" 链接。
    空元组 = 普通文字。
    """
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            yield (text[pos:m.start()], ())
        kind = m.lastgroup
        s = m.group()
        if kind == "code":
            yield (s[1:-1], ("ic",))
        elif kind == "bold":
            yield (s[2:-2], ("b",))
        elif kind == "italic":
            yield (s[1:-1], ("i",))
        else:                            # link
            cut = s.index("]")
            label, url = s[1:cut], s[cut + 2:-1]
            # 链接文字里可能还套着强调, 这里**不递归**: 只把记号本身去掉,
            # 免得链接文字里显示出一堆星号。发版说明里没有套两层的情况。
            label = label.replace("**", "").replace("__", "")
            label = label.replace("*", "").replace("`", "")
            yield (label or url, ("link:" + url,))
        pos = m.end()
    if pos < len(text):
        yield (text[pos:], ())


class ChangelogWindow(tk.Toplevel):
    """单例。重复 open() 只把已开的那个唤到前面。"""

    _instance = None

    @classmethod
    def open(cls, app, version=None, auto=False):
        """打开。version 指定初始选中哪一版, 默认当前版本。

        auto=True 表示这是"更新后第一次启动自动弹的"(而不是用户点按钮), 区别
        只在两处: 拉不到东西时**自己静静关掉**(不拿一句报错去糊用户的脸),
        以及当前版本没发布过时根本不弹(见 _fill)。
        """
        win = cls._instance
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_set()
            if version:
                win._select_version(version)
            return win
        win = cls(app, version, auto)
        # **不能**在这里无条件写回 _instance: 构造过程中窗口可能已经把自己关掉
        # 了(auto 弹窗碰上"这一版没发布过"或"拉不到东西"时会 _close, 见 _fill /
        # _on_error)。_close() 里已经把 _instance 清成 None, 而这条赋值是在构造
        # **返回之后**才执行的 —— 无条件写回会把一个已经 destroy 的窗口重新记成
        # 单例, 下次 open() 拿到它、调 winfo_exists() 得到 0 才又绕开。
        cls._instance = win if win._alive else None
        return cls._instance

    def __init__(self, app, version=None, auto=False):
        super().__init__(app.root)
        self.app = app
        self._want = version or C.APP_VERSION
        self._auto = auto

        self.title("更新日志")
        self.configure(bg=C.BG)
        self.transient(app.root)
        self.resizable(True, True)       # 是文字窗口, 让人自己拉大
        self.minsize(C.px(620), C.px(400))
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._alive = True
        self._after_id = None
        self._queue = queue.Queue()
        self._items = []          # 当前显示的 releases 列表(和列表下标一一对应)
        self._tag_defs = {}       # tag 名 -> 样式说明, 见 _tag()
        self._link_ids = {}       # 地址 -> 序号, 见 _link_id()

        self._place_over_parent()
        self._build()
        self.bind("<Escape>", lambda _e: self._close())
        self._load()

    # -- 位置 ----------------------------------------------------------

    def _place_over_parent(self):
        """和主窗口差不多大、居中。"""
        pr = self.app.root
        pw, ph = pr.winfo_width(), pr.winfo_height()
        if pw <= 1 or ph <= 1:
            # 主窗口还没映射, winfo_* 报的是 1 —— 照它算会得到 1x1 的窗口。
            pw, ph = C.DESIGN_W, C.DESIGN_H
        w = min(int(pw * WINDOW_FRACTION), pw)
        h = min(int(ph * WINDOW_FRACTION), ph)
        x = pr.winfo_rootx() + (pw - w) // 2
        y = pr.winfo_rooty() + (ph - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # -- 构建 ----------------------------------------------------------

    def _build(self):
        # pack 顺序是 页眉 → 页脚 → 正文, 但**页脚要 side="bottom"**。
        # Tk 是按 pack 顺序从腔体里切条的, 所以顺序决定的是**裁切优先级**
        # (空间不够时从最后 pack 的开始裁, 正文放最后才不会被压成一条缝);
        # 而 side 才决定它切哪一边。写成 side="top" 的话页脚会紧贴页眉出现
        # —— 按钮跑到正文**上面**去, 顺序看着还是对的, 量 y 坐标才发现。
        head = tk.Frame(self, bg=C.BG)
        head.pack(side="top", fill="x", padx=C.px(16), pady=(C.px(12), C.px(6)))
        tk.Label(head, text="更新日志", bg=C.BG, fg=C.FG,
                 font=C.font(C.FONT_CAPTION), anchor="w").pack(fill="x")
        tk.Label(head, text="左侧选择版本，右侧是该版本的更新说明。",
                 bg=C.BG, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                 anchor="w").pack(fill="x", pady=(C.px(4), 0))

        foot = tk.Frame(self, bg=C.BG)
        foot.pack(side="bottom", fill="x", padx=C.px(16), pady=C.px(12))
        ttk.Button(foot, text="关闭", command=self._close).pack(side="right")
        ttk.Button(foot, text="在浏览器中打开",
                   command=self._open_in_browser).pack(
            side="right", padx=(0, C.px(10)))
        self._retry = ttk.Button(foot, text="重试", command=self._start_load)
        self._retry.pack(side="right", padx=(0, C.px(10)))
        self._status = tk.Label(foot, text="", bg=C.BG, fg=C.FG_DIM,
                                font=C.font(C.FONT_SMALL), anchor="w")
        self._status.pack(side="left")

        body = tk.Frame(self, bg=C.CARD)
        body.pack(side="top", fill="both", expand=True, padx=C.px(16))

        # 侧边栏。holder 定死像素宽 + pack_propagate(False): Listbox 的 -width
        # 单位是**字符数**, 在这台机器的高 DPI 缩放下和像素差得远, 靠字符数凑
        # 宽度会横跨半屏。定死容器宽度, 让列表在里面 fill 就与字体无关了。
        holder = tk.Frame(body, bg=C.CARD, width=C.px(SIDE_MIN))
        holder.pack(side="left", fill="y")
        holder.pack_propagate(False)
        self._holder = holder
        self._list = tk.Listbox(
            holder, bg=C.CARD, fg=C.FG,
            selectbackground=C.ACCENT, selectforeground=C.ON_ACCENT,
            highlightthickness=0, bd=0, activestyle="none",
            font=C.font(C.FONT_SMALL),
            # **必须有**: 不设的话 Listbox 的选中项会跟 X11 那套"当前选择"绑定,
            # 点一下别处(比如右边的正文)就自己掉选, 侧边栏看着像没选中任何东西。
            exportselection=False)
        self._list.pack(side="left", fill="both", expand=True,
                        padx=C.px(6), pady=C.px(6))
        lbar = ttk.Scrollbar(holder, orient="vertical", command=self._list.yview)
        self._list.configure(yscrollcommand=lbar.set)
        lbar.pack(side="right", fill="y")
        self._list.bind("<<ListboxSelect>>", self._on_pick)

        # 正文。state="disabled" 是最后才设的(要先能往里写); 只读, 不能选中的话
        # 用户连复制一段说明走都做不到, 所以是"不可编辑"而不是"不可交互"。
        pane = tk.Frame(body, bg=C.CARD)
        pane.pack(side="left", fill="both", expand=True)
        self._text = tk.Text(
            pane, bg=C.CARD, fg=C.FG, highlightthickness=0, bd=0,
            wrap="word", cursor="arrow",
            selectbackground=C.ACCENT, selectforeground=C.ON_ACCENT,
            font=C.font(BODY_PX),
            spacing1=C.px(1), spacing2=C.px(4), spacing3=C.px(1),
            padx=C.px(20), pady=C.px(16))
        tbar = ttk.Scrollbar(pane, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=tbar.set)
        tbar.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

    # -- tag ------------------------------------------------------------

    def _tag(self, kind, size, bold=False, italic=False, color=None,
             indent=0, mono=None, layout=None, part=None):
        """取(必要时新建)一个 tag, 返回它的名字。

        kind   外观: body / meta / h / title / icode / link / mark / codeblock
        layout 版式: 上面 _LAYOUT_KINDS 里那几个(缩进、行距、底色)
        mono   True/False 强制等宽; None = 按 kind 决定(codeblock/icode 用等宽)
        part   代码块的哪一段: "first" / "mid" / "last" / "sole"。
               只有代码块用, 原因见 _tag_options 里那段注释。
        """
        if layout is None:
            layout = kind if kind in _LAYOUT_KINDS else "body"
        name = "%s|%s|%d|%d%d|%d|%s|%s" % (
            layout, kind, size, int(bold), int(italic), indent,
            "-" if mono is None else int(mono), part or "-")
        if name not in self._tag_defs:
            self._tag_defs[name] = (layout, kind, size, bold, italic, color,
                                    indent, mono, part)
            self._configure_tag(name)
        return name

    def _configure_tag(self, name):
        self._text.tag_configure(name, **self._tag_options(*self._tag_defs[name]))

    def _tag_options(self, layout, kind, size, bold, italic, color, indent,
                     mono, part):
        if mono is None:
            mono = kind in ("codeblock", "icode")
        weight = "bold" if bold else "normal"
        opt = {"font": (C.mono(size, weight) if mono
                        else C.font(size, weight,
                                    "italic" if italic else "roman"))}

        # --- 外观 ---
        opt["foreground"] = color or C.FG
        if kind in ("meta",):
            opt["foreground"] = color or C.FG_DIM
        elif kind in ("h", "title"):
            opt["font"] = C.font(size, "bold")
            opt["foreground"] = color or C.FG
        elif kind == "mark":
            opt["font"] = C.font(size, "bold")
            opt["foreground"] = C.ACCENT
        elif kind == "icode":
            opt["foreground"] = C.ACCENT
            opt["background"] = C.ENTRY_BG
        elif kind == "link":
            opt["foreground"] = C.ACCENT
            opt["underline"] = True
        elif layout == "quote" and kind == "body":
            opt["foreground"] = color or C.FG_DIM

        # --- 版式 ---
        if layout == "quote":
            opt["lmargin1"] = C.px(18)
            opt["lmargin2"] = C.px(18)
            opt["spacing3"] = C.px(3)
        elif layout in ("bullet", "number"):
            # 悬挂缩进: 首行从 lmargin1 起(带项目符号), 折行部分对齐到
            # lmargin2 —— 也就是"文字"那一列, 而不是回到符号下面。
            opt["lmargin1"] = C.px(6 + indent * INDENT_STEP)
            opt["lmargin2"] = C.px(24 + indent * INDENT_STEP)
        elif layout == "codeblock":
            opt["background"] = C.ENTRY_BG
            opt["lmargin1"] = C.px(12)
            opt["lmargin2"] = C.px(12)
            # 代码块要整块连成一片, 只在外围留白。
            #
            # 这里必须**按行拆段**: Tk 的 spacing1/spacing3 是每个**显示行**
            # 上下各加一次, 不是按段落算的。每行都设 8 的话, 三行代码就被撑成
            # 三段(实测行间 42px), 看着根本不像一块代码。所以首行只要
            # spacing1, 末行只要 spacing3, 中间行两个都是 0 —— 行间只靠
            # spacing2 那个 1px 连着。
            opt["spacing1"] = C.px(8) if part in ("first", "sole") else 0
            opt["spacing3"] = C.px(8) if part in ("last", "sole") else 0
            opt["spacing2"] = C.px(1)
        elif layout == "h":
            opt["spacing1"] = C.px(14)
            opt["spacing3"] = C.px(5)
        elif layout == "title":
            opt["spacing3"] = C.px(4)
        elif layout == "meta":
            opt["spacing3"] = C.px(14)
        return opt

    def _apply_tags(self):
        """按当前调色板重配**全部** tag。

        换肤时必须重来一遍: tag 的颜色不是控件选项, screens._retheme_tree 那套
        "按当前色值反查调色板"的映射碰不到它们, 所以本窗口要有 redraw()。
        """
        for name in list(self._tag_defs):
            self._configure_tag(name)

    def _link_id(self, url):
        """给地址编个稳定的序号 —— 它要进 tag 名。

        不这么做的话, 同一个块里两个不同的链接会算出同一个 tag 名, 第二个的
        点击绑定写不进去(第一次建过就复用了), 点两条都开第一个地址。
        """
        idx = self._link_ids.get(url)
        if idx is None:
            idx = len(self._link_ids)
            self._link_ids[url] = idx
        return idx

    def _bind_link(self, name, url):
        """每次渲染都重绑一遍 —— 增量很小, 但省掉了"这个 tag 绑过没有"的状态。"""
        self._text.tag_bind(name, "<Button-1>",
                            lambda _e, u=url: webbrowser.open(u))
        # 手型光标。Text 没有 per-tag 的 cursor 选项, 只能进出时自己换。
        self._text.tag_bind(name, "<Enter>",
                            lambda _e: self._text.configure(cursor="hand2"))
        self._text.tag_bind(name, "<Leave>",
                            lambda _e: self._text.configure(cursor="arrow"))

    # -- 取数 ----------------------------------------------------------

    def _load(self):
        """打开窗口时走这里: **先渲染缓存, 再决定要不要联网**。

        用户的要求是"历史日志存在本地, 不要每次去 GitHub"。所以:
          * 有缓存 -> 立刻显示。断网也看得到, 而且不闪"正在获取…";
          * 缓存还新鲜 -> 到此为止, **一个请求都不发**;
          * 缓存过期 / 没有 -> 才去联网, 拿到新表再覆盖一次。
        """
        cached = updater.cached_releases()
        if cached:
            self._fill(cached)
            if not self._alive:
                # _fill 可能把窗口关了(auto 弹窗碰上"这一版没发布过")。后面的
                # 事情都别做了 —— 虽然 _start_load 自己也有守卫, 但让"关掉了就
                # 到此为止"在这里显式写出来, 读的人不用去追那条守卫。
                return
        if cached and updater.cache_is_fresh():
            return
        self._start_load()

    def _start_load(self):
        """联网拉整表。

        "要不要护着屏幕上的东西"**不按调用方分**, 只看屏幕上有没有内容: 有就
        不拿"正在获取…"糊掉正文。按调用方分是个坑 —— 重试按钮走的是同一条路,
        用户在看着某一版说明时点重试, 正文会被那句提示清空; 请求再失败, 就永远
        停在"正在获取更新说明…"上, 而状态栏正说着"显示的是本地记录"。
        """
        if not self._alive:
            return
        # 「正在取数」这个状态只用按钮的禁用态表达就够了 —— 它本来就是用户看得见
        # 的那个东西, 再存一个 _loading 也没人去读(存过一版, 只写不读)。
        self._retry.state(["disabled"])
        if self._items:
            self._set_status("正在刷新…")
        else:
            self._set_status("")
            self._set_text("正在获取更新说明…")

        def work():
            try:
                self._queue.put(("ok", updater.releases()))
            except Exception as e:
                # 这里连 Exception 都吞: 线程里抛出去没人接, 只会打成一段
                # 控制台堆栈, 而窗口那边永远停在"正在获取"。消息是给人看的,
                # updater 自己会把 UpdateError 编成一句中文。
                self._queue.put(("err", str(e) or e.__class__.__name__))

        threading.Thread(target=work, daemon=True).start()
        self._poll()

    def _poll(self):
        if not self._alive:
            return
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            self._after_id = self.after(POLL_MS, self._poll)
            return
        self._retry.state(["!disabled"])
        if kind == "ok":
            self._fill(payload)
        else:
            self._on_error(payload)

    def _on_error(self, message):
        """联网失败。

        屏幕上**可能已经有缓存内容了**(先渲染缓存那条路径), 那就什么都不用做
        —— 用户要的数据本来就在眼前, 断个网不该在他脸上糊一行红字。
        """
        if self._items:
            self._set_status("离线，显示的是本地记录")
            return

        info = getattr(self.app, "update_info", None) or {}
        notes = info.get("notes") or ""
        # 只在这个兜底数据**正好是用户想看的那个版本**时才用: update_info 说的是
        # 当前版本(C.APP_VERSION), 而调用方可能点名要看别的版本 —— 拿这一版的
        # 说明去填那一版的窗口, 是在编。
        if notes and info.get("latest") == self._want:
            self._fill([{
                "version": self._want,
                "tag": "v" + self._want,
                "name": "SJTU第五人格克隆杯 BP 工具 v" + self._want,
                "notes": notes,
                "date": "",
                "url": info.get("release_url") or "",
                "prerelease": False,
            }], status="列表获取失败，只显示当前版本：%s" % message)
            return
        if self._auto:
            # 自动弹的那种: 没内容就别弹了。操作者刚打开程序准备比赛, 第一眼是
            # 一个报错的空窗口, 比不弹糟得多 —— 而且他什么也没损失, 设置窗里
            # 那个「更新日志」按钮还在, 想看得时候随时能点。
            # **不记 seen**: 这一版他其实没看到, 下次启动(联网了)该再弹一次。
            self._close()
            return
        self._set_text("")
        self._set_status("获取失败：%s" % message)

    # -- 渲染 ----------------------------------------------------------

    def _fill(self, items, status=None):
        was = self._current_version()
        self._items = list(items)
        self._list.delete(0, "end")
        # 「自动弹」不出场的两种情况合成一条: 列表是空的, 或者**当前这一版根本
        # 没发布过** —— 本机跑的开发版就长这样(改了 APP_VERSION 但还没发版)。
        # 那时列表里最新的一版是**别的**版本, 弹出来说的是别的事, 不如不弹。
        # 两种情况都**不记 seen**: 用户其实什么都没看到。
        #
        # 手动点开(设置窗那个按钮)不走这条: 那是用户明确想看, 空列表也该如实
        # 告诉他"还没有发布过任何版本", 而不是把窗口收掉。
        if self._auto and not any(r["version"] == self._want for r in self._items):
            self._close()
            return
        if not self._items:
            self._set_text("")
            self._set_status(status or "还没有发布过任何版本。")
            return
        # "自动弹"这件事到此就办完了, 后面这个窗口就是个普通窗口。不清掉的话
        # 用户按「重试」又失败时, 它会**自己关掉**而不是报错 —— 明明是他主动点的。
        self._auto = False

        labels = []
        for rel in self._items:
            label = rel["tag"]
            if rel["date"]:
                label += "  ·  " + rel["date"]
            if rel["version"] == C.APP_VERSION:
                label += "  ← 当前"
            labels.append(label)
            self._list.insert("end", label)
        self._fit_sidebar(labels)
        self._set_status(status or ("%d 个版本" % len(self._items)))

        # 内容到手了才算"看过"。放在这里而不是开窗时: 开窗到取到数之间用户随时
        # 可能关掉/关程序, 那时他其实什么都没看到, 不该把这一版记成已读。
        #
        # **手动点开也算**: 用户已经在新版本的日志上读到了这一版的内容, 下次启动
        # 再弹一遍就是噪音。"看过"说的是"这段文字他见过了", 与从哪个入口进来无关。
        if any(r["version"] == C.APP_VERSION for r in self._items):
            self.app.mark_changelog_seen()

        # 联网刷新回来的那次: 保持用户当前在看的那一版, 而不是跳回最新。
        self._select_version(was or self._want)

    def _current_version(self):
        """当前选中那一版的版本号; 还没选中过就返回 None。"""
        sel = self._list.curselection()
        if sel and 0 <= sel[0] < len(self._items):
            return self._items[sel[0]]["version"]
        return None

    def _fit_sidebar(self, labels):
        """把侧边栏调到刚好放得下最长的一条(在上下限之间)。"""
        try:
            measure = tkfont.Font(font=C.font(C.FONT_SMALL))
            widest = max(measure.measure(s) for s in labels)
        except tk.TclError:
            return                     # 量不出来就沿用当前宽度, 不值得为它报错
        self._holder.configure(
            width=max(C.px(SIDE_MIN), min(C.px(SIDE_MAX), widest + C.px(SIDE_EXTRA))))

    def _select_version(self, version):
        """选中指定版本; 找不到就选最新的一版(列表本来就是新的在前)。"""
        if not self._items:
            return
        index = 0
        for i, rel in enumerate(self._items):
            if rel["version"] == version:
                index = i
                break
        self._list.selection_clear(0, "end")
        self._list.selection_set(index)
        self._list.see(index)
        self._show(index)

    def _on_pick(self, _event):
        sel = self._list.curselection()
        if sel:
            self._show(sel[0])

    def _show(self, index):
        if not (0 <= index < len(self._items)):
            return
        rel = self._items[index]
        t = self._text
        t.configure(state="normal")
        t.delete("1.0", "end")

        t.insert("end", rel["name"] or rel["tag"],
                 self._tag("title", TITLE_PX, bold=True))
        meta = rel["date"] or ""
        if rel["version"] == C.APP_VERSION:
            meta = (meta + "　·　" if meta else "") + "当前版本"
        t.insert("end", "\n")
        if meta:
            t.insert("end", meta, self._tag("meta", META_PX))
        t.insert("end", "\n")

        notes = _clean_notes(rel["notes"])
        if not notes:
            t.insert("end", "\n（这一版没有填写更新说明）\n",
                     self._tag("meta", META_PX))
        else:
            for kind, payload in _iter_blocks(notes.splitlines()):
                self._render_block(kind, payload)

        t.configure(state="disabled")
        t.yview_moveto(0.0)     # 换一版一定要回到顶部, 否则会停在上一版的滚动位置

    def _render_block(self, kind, payload):
        t = self._text

        if kind == "code":
            # 等宽与否**整块一起定**: 一个块里混着中英时, 逐行判会让行与行
            # 用两种字体, 左边缘对不齐。含中文就整块退回界面字体(理由见
            # C.mono_for)。
            mono = payload.isascii()
            lines = payload.split("\n")
            for i, line in enumerate(lines):
                # 每行单独插(不是插一整段带 \n 的字符串), 这样才能给首/末行
                # 配不同的 spacing —— 见 _tag_options 里 codeblock 那一段。
                if len(lines) == 1:
                    part = "sole"
                elif i == 0:
                    part = "first"
                elif i == len(lines) - 1:
                    part = "last"
                else:
                    part = "mid"
                tag = self._tag("codeblock", BODY_PX - 1, mono=mono, part=part)
                t.insert("end", line, tag)
                t.insert("end", "\n", tag)
            return

        if kind == "rule":
            t.insert("end", "\n", self._tag("body", BODY_PX))
            return

        if kind == "h":
            level, text = payload
            size = HEAD_PX.get(level, HEAD_MIN)
            self._emit(text, "h", size, layout="h")
            return

        if kind == "quote":
            for line in payload:
                self._emit(line, "body", BODY_PX, layout="quote")
            return

        if kind == "bullet":
            depth, text = payload
            self._emit(text, "body", BODY_PX, layout="bullet", indent=depth,
                       mark="·  ")
            return

        if kind == "number":
            depth, index, text = payload
            self._emit(text, "body", BODY_PX, layout="number", indent=depth,
                       mark=index + ".  ")
            return

        self._emit(payload, "body", BODY_PX)

    def _emit(self, text, kind, size, layout=None, indent=0, mark=None):
        """把一行(已切好行内样式的)文字写进 Text, 末尾补一个换行。"""
        t = self._text
        layout = layout or kind
        if mark:
            # 项目符号/序号单独一个 tag: 它用强调色, 而且**不参与行内样式**,
            # 否则整行加粗时连符号一起变。
            t.insert("end", mark,
                     self._tag("mark", size, layout=layout, indent=indent))
        tags = []
        for piece, styles in _inline_runs(text):
            name = self._span(kind, size, layout, indent, styles, piece)
            tags.append(name)
            t.insert("end", piece, name)
        # 行尾的换行也要挂上这一行的 tag, 否则 spacing3(段后距)加不到这一行上
        # —— Tk 把行距算在行**末**那个字符上。
        t.insert("end", "\n", tags[-1] if tags else
                 self._tag(kind, size, layout=layout, indent=indent))

    def _span(self, base_kind, size, layout, indent, styles, text):
        """一行里的一段 -> 它该用的 tag 名。"""
        bold = "b" in styles
        italic = "i" in styles
        kind = base_kind
        if "ic" in styles:
            kind = "icode"
        link = next((s for s in styles if s.startswith("link:")), None)
        if link is not None:
            kind = "link"
        mono = text.isascii() if kind in ("icode", "codeblock") else None
        if link is None:
            return self._tag(kind, size, bold, italic, layout=layout,
                             indent=indent, mono=mono)
        # 链接: 地址要进 tag 名(见 _link_id), 所以绕开 _tag 的命名再绑一次。
        url = link[5:]
        name = self._tag(kind, size, bold, italic, layout=layout,
                         indent=indent, mono=mono)
        name = "link%d.%s" % (self._link_id(url), name)
        if name not in self._tag_defs:
            self._tag_defs[name] = self._tag_defs[name.split(".", 1)[1]]
            self._configure_tag(name)
        self._bind_link(name, url)
        return name

    def _set_text(self, message):
        t = self._text
        t.configure(state="normal")
        t.delete("1.0", "end")
        if message:
            t.insert("end", message, self._tag("meta", BODY_PX))
        t.configure(state="disabled")

    def _set_status(self, message):
        self._status.configure(text=message)

    # -- 交互 ----------------------------------------------------------

    def _open_in_browser(self):
        sel = self._list.curselection()
        if not sel or not (0 <= sel[0] < len(self._items)):
            return
        url = self._items[sel[0]].get("url")
        if url:
            webbrowser.open(url)

    # -- 收尾 ----------------------------------------------------------

    def _close(self):
        # 先落 _alive 再 destroy: 轮询和后台线程都会看这个标志, 顺序反了的话
        # 已经排进队列的那一拍会在窗口没了之后去碰控件。
        self._alive = False
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        ChangelogWindow._instance = None
        self.destroy()

    # -- 换肤 ----------------------------------------------------------

    def redraw(self):
        """screens._retheme_tree 换肤时会调(项目里 `redraw` 就是这个约定)。

        控件本身的颜色树那边按色值映射自己会改; 这里要补的是 **Text 的 tag**:
        它们不是控件选项, 那套映射碰不到, 不重配的话正文会停在旧皮肤的颜色上,
        而窗口边框已经换了 —— 看着就是"这一块没跟上"。
        """
        self._apply_tags()


def _clean_notes(notes):
    """切掉 publish.py 自动追加的"下载"小节, 去掉首尾空行。"""
    if not notes:
        return ""
    return notes.split(_DOWNLOAD_SECTION, 1)[0].strip()

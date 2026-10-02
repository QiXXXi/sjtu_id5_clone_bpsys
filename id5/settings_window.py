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

import os
import queue
import subprocess
import threading
import traceback
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import character_order
from . import config as C
from . import updater
from .roster import THUMBS
from .screens import Switch

# 预览行的版式。**故意留在本模块**: 只有这里用, 而 config 那份是跨模块共享的。
# 每行 10 个: 这个数不是随手定的 —— 它决定设置窗口内容区有多宽(所有卡片都是
# fill="x", 最宽的那个说了算), 10 个 32px 带头像约 380px, 刚好不超过"动画时长"
# 那张卡片原有的宽度。再多就会把整个设置窗口撑宽、连带把上面两张卡片也拉长。
_PREVIEW_COLS = 10
_PREVIEW_SIDE = 32
_PREVIEW_MAX_ROWS = 2

# 更新说明在弹窗里的截断长度。release 正文是 markdown, 写长了能到几千字,
# messagebox 塞不下 —— 超出就砍掉, 并告诉用户还剩多少没显示。
_NOTES_MAX = 600


def _trim_notes(text):
    """截断 release 正文。返回 (显示的部分, 没显示的字符数)。

    在**换行处**断, 不在句子中间断 —— 这不是洁癖: markdown 的列表项和标题被
    砍掉一半, 剩下的 `##` `-` `[` 看着就是乱码。整段没有换行时只能硬断。
    """
    text = (text or "").strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= _NOTES_MAX:
        return text, 0
    cut = text.rfind("\n", 0, _NOTES_MAX)
    if cut < _NOTES_MAX // 2:
        cut = _NOTES_MAX
    return text[:cut].rstrip(), len(text) - cut


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
        # 存活标志。规则禁用窗保存后会回调 _refresh_rule_preview, 而那时本窗口
        # 可能已经关了 —— 对已销毁的 Toplevel 调 winfo_exists() 本身就会抛
        # TclError(invalid command name), 所以不能靠它判断, 得自己记一笔。
        self._alive = True
        # 预览那排头像。和规则禁用窗一样, **必须一直拿着引用** —— canvas/Label
        # 只存图片名, PhotoImage 一被 GC 回收, 那几格会静默变空白。
        self._rule_photos = {}
        # ---- 检查更新 ----
        # 正在查/正在下/出错了这些**临时**状态。空串表示"没有话要说", 那时
        # 版本行就从 app 缓存的检查结果里推一句(启动时那次静默检查就在那儿)。
        self._update_status = ""
        # 这次检查是不是操作者主动点的。启动时那次**静默**检查, 失败了不该
        # 弹任何东西 —— 操作者没要, 弹个"连不上 GitHub"只会让人以为程序坏了。
        self._manual_check = False
        self._dl_queue = None
        self._dl_dest = ""
        self._update_cb = None      # 注册给 app 的那个回调对象, 见 _build 之后
        self._place_over_parent()
        self._build()
        # 启动时那次检查结束(或已经结束)要回填这一行。设置窗是单例, 所以
        # app 那边只留一个回调位就够。
        #
        # **存成属性再注册**, 不要两处都写 self._on_update_result: 绑定方法是
        # 每次访问**现造**的一个新对象, `self._on_update_result is
        # self._on_update_result` 是 False —— 摘回调时那句身份判断永远不成立,
        # 于是关窗后回调还挂在 app 上, 下次检查回来就会调到一个已经销毁的
        # 窗口上。
        self._update_cb = self._on_update_result
        self.app.on_update_result = self._update_cb

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
        self._build_rule_ban(body)
        self._build_version(body)

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

    def _build_rule_ban(self, parent):
        card = self._card(parent, "规则禁用")

        row = tk.Frame(card, bg=C.CARD)
        row.pack(fill="x", padx=C.px(16), pady=(C.px(4), 0))
        ttk.Button(row, text="规则禁用",
                   command=self._open_rule_ban).pack(side="left")
        self._rule_count = tk.Label(row, text="", bg=C.CARD, fg=C.FG_DIM,
                                    font=C.font(C.FONT_SMALL), anchor="w")
        self._rule_count.pack(side="left", padx=(C.px(12), 0))

        # 预览在按钮**下方**(规格)。做成单独一个 Frame, 每次整块重建 ——
        # 要增删的是数量不定的控件, 逐个 diff 不值得, 88 个格子的量级重建一次
        # 也就几毫秒。
        self._rule_preview = tk.Frame(card, bg=C.CARD)
        self._rule_preview.pack(fill="x", padx=C.px(16), pady=(C.px(8), C.px(14)))
        self._refresh_rule_preview()

    def _build_version(self, parent):
        card = self._card(parent, "版本")
        row = tk.Frame(card, bg=C.CARD)
        row.pack(fill="x", padx=C.px(16), pady=(C.px(4), C.px(14)))

        self._update_btn = ttk.Button(row, text="检查更新",
                                      command=self._on_check_update)
        self._update_btn.pack(side="left")
        # 版本号和状态**合成一行**。单独起一行放状态的话, 这张卡片会在"正在
        # 下载…"时悄悄长高, 而 body 是居中 place 的 —— 长出来的部分会上下
        # 同时被裁掉, 而且看不出是被裁的。一行内换字, 高度恒定。
        self._update_label = tk.Label(row, text="", bg=C.CARD, fg=C.FG_DIM,
                                      font=C.font(C.FONT_SMALL), anchor="w")
        self._update_label.pack(side="left", padx=(C.px(12), 0))
        # 「更新日志」钉在**行尾**。紧挨着上面那个状态标签放不行: 标签的文字
        # 会变("正在检查…"/"有新版本 1.1.1"/"已是最新"), 宽度跟着变, 挤在它
        # 后面的按钮就会左右跳。挂在右边就与状态无关。
        ttk.Button(row, text="更新日志",
                   command=self._open_changelog).pack(side="right")
        self._refresh_version()

    # -- 检查更新 ------------------------------------------------------

    def _refresh_version(self):
        """版本行 = 「当前版本 x.y.z」+ 一句状态。

        状态优先用 _update_status(正在查 / 正在下 / 出错了); 空着就从 app 缓存
        的那次检查结果推 —— 启动时的静默检查就存在那儿, 所以刚打开设置窗不用
        再查一遍, 也能看到「有新版本 1.1.1」。
        """
        status = self._update_status
        if not status:
            if self.app.update_checking:
                status = "正在检查…"
            else:
                info = self.app.update_info
                if info is not None:
                    status = ("有新版本 %s" % info["latest"]
                              if info.get("has_update") else "已是最新")
        text = "当前版本 %s" % C.APP_VERSION
        self._update_label.configure(text=text + ("　·　" + status if status else ""))

    def _set_update_btn(self, enabled):
        self._update_btn.configure(state="normal" if enabled else "disabled")

    def _on_check_update(self):
        """按钮: 手动查一次。这次的结果**要**说出来, 包括失败。"""
        self._manual_check = True
        self._update_status = "正在检查…"
        self._refresh_version()
        self._set_update_btn(False)
        if not self.app.check_update_async():
            return                      # 已经有一次在查, 结果会走同一个回调

    def _on_update_result(self, payload):
        """app 那边查完了。**手动那次和启动静默那次都走这儿。**"""
        if not self._alive:
            return
        manual, self._manual_check = self._manual_check, False
        self._set_update_btn(True)

        if payload.get("error"):
            # 静默那次失败**什么都不显示**: 操作者没要, 弹个"连不上 GitHub"
            # 只会让人以为程序坏了。手动那次必须说 —— 他刚点了按钮, 没反应
            # 才是最难查的。
            self._update_status = "检查失败：%s" % payload["error"] if manual else ""
            self._refresh_version()
            return

        self._update_status = ""        # 交回给 _refresh_version 从结果推
        self._refresh_version()
        if manual:
            self._after_manual_check(payload)

    def _after_manual_check(self, info):
        if not info.get("has_update"):
            messagebox.showinfo("检查更新",
                                "当前已是最新版本 %s。" % C.APP_VERSION,
                                parent=self)
            return

        notes, rest = _trim_notes(info.get("notes"))
        msg = "发现新版本 %s（当前 %s）。" % (info["latest"], C.APP_VERSION)
        if notes:
            msg += "\n\n" + notes
        if rest:
            msg += "\n…（更新说明其余 %d 字见发布页）" % rest

        if not info.get("asset_url"):
            # 这个版本没附安装包 —— 只能请用户自己去发布页
            if messagebox.askokcancel(
                    "发现新版本", msg + "\n\n这个版本没有附带安装包，"
                                        "要到发布页手动下载吗？", parent=self):
                webbrowser.open(info["release_url"])
            return

        size = info.get("asset_size") or 0
        msg += "\n\n现在下载安装包吗？"
        if size:
            msg += "（%.1f MB，下载到「下载」文件夹）" % (size / 1048576.0)
        if messagebox.askyesno("发现新版本", msg, parent=self):
            self._download(info)

    def _download(self, info):
        """后台下载安装包, 边下边把进度写进版本行。"""
        dest = os.path.join(updater.downloads_dir(), info["asset_name"])
        self._dl_dest = dest
        self._dl_queue = queue.Queue()
        self._set_update_btn(False)
        self._update_status = "正在下载…"
        self._refresh_version()

        q = self._dl_queue

        def worker():
            def progress(got, total):
                q.put(("progress", got, total))
            try:
                updater.download(info["asset_url"], dest, progress=progress)
                q.put(("done", 0, 0))
            except updater.UpdateError as e:
                q.put(("error", str(e), 0))
            except Exception:
                q.put(("error", traceback.format_exc(limit=1), 0))

        threading.Thread(target=worker, daemon=True).start()
        self.after(150, self._poll_download)

    def _poll_download(self):
        if not self._alive:
            return                       # 窗口关了, 下载线程自己跑完就好
        try:
            kind, a, b = self._dl_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_download)
            return

        if kind == "progress":
            self._update_status = ("正在下载… %d%%" % (100 * a // b) if b
                                   else "正在下载… %.1f MB" % (a / 1048576.0))
            self._refresh_version()
            self.after(150, self._poll_download)
            return

        self._set_update_btn(True)
        if kind == "error":
            self._update_status = "下载失败"
            self._refresh_version()
            messagebox.showerror("下载安装包", a, parent=self)
            return

        self._update_status = "已下载"
        self._refresh_version()
        # 下载完自动弹开文件夹并选中它 —— 离安装只差双击一下。
        # explorer 的 /select, 必须写成**一整条命令行**: 用列表传参时
        # subprocess 会把 ` /select,` 和路径分别加引号, explorer 认不出来。
        try:
            subprocess.Popen('explorer /select,"%s"' % self._dl_dest)
        except Exception:
            pass                         # 弹不开文件夹不算失败, 下面会说路径
        messagebox.showinfo(
            "下载完成",
            "安装包已下载到：\n%s\n\n关闭本程序后双击安装即可。" % self._dl_dest,
            parent=self)

    def redraw(self):
        """换肤时由 screens._retheme_tree 调用(项目里 `redraw` 就是这个约定)。

        换肤**不会重建**这个窗口, 只把控件颜色映射一遍。而预览那排头像是
        THUMBS.square() **烘死在卡片底色上**的实心图 —— 底色变了图没变, 每格
        周围就会留一圈旧主题的方框。所以要自己重合成一遍。
        """
        self._refresh_rule_preview()

    def _open_rule_ban(self):
        # 延迟导入, 同 _open_settings 那条理由: 模块级互相 import 会成环。
        from .rule_ban_window import RuleBanWindow
        RuleBanWindow.open(self.app, on_save=self._refresh_rule_preview)

    def _open_changelog(self):
        # 延迟导入, 同上。**不带 auto**: 那是"更新后自动弹"才有的行为, 手动点开
        # 拉不到东西时要老老实实报错, 不能自己关掉 —— 用户会以为按钮坏了。
        # 也不传版本: 默认就选中当前版本, 那正是点这个按钮的人想看的。
        from .changelog_window import ChangelogWindow
        ChangelogWindow.open(self.app)

    def _refresh_rule_preview(self):
        """重建按钮下方那排预览头像。规则禁用窗保存后由它回调过来。"""
        if not self._alive:
            return                      # 设置窗口已经关了, 控件都没了
        for child in self._rule_preview.winfo_children():
            child.destroy()
        self._rule_photos = {}

        # 顺序和规则禁用窗里看到的一致(实装顺序倒序), 这样"我刚点的那几个"
        # 在预览里的相对位置和刚才一样。
        names = character_order.newest_first(self.state.rule_banned)
        self._rule_count.configure(text="已禁用 %d 个" % len(names))

        if not names:
            tk.Label(self._rule_preview, text="（当前没有角色被规则禁用）",
                     bg=C.CARD, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                     anchor="w").grid(row=0, column=0, sticky="w")
            return

        # 分组是为了取头像(角色名在 survivor/ 还是 hunter/ 下)。名册每次
        # "检查角色更新"都会重建, 所以现算, 不缓存。
        groups = {}
        for group in ("survivor", "hunter"):
            for item in self.app.roster.groups[group]:
                groups[item.value] = group

        side = C.px(_PREVIEW_SIDE)
        shown = names[: _PREVIEW_COLS * _PREVIEW_MAX_ROWS]
        for i, name in enumerate(shown):
            item = self.app.roster.lookup(name)
            if item is None:
                continue                # 角色已被删掉, 但还留在 json 里
            # square() 的底色调成 CARD, 和卡片一致 —— 头像四周就不会有一圈
            # 别的颜色。换肤时设置窗口整棵重建, 这里不用管旧图。
            photo = THUMBS.square(item, groups.get(name, "survivor"), side, C.CARD)
            self._rule_photos[name] = photo
            tk.Label(self._rule_preview, image=photo, bg=C.CARD, bd=0).grid(
                row=i // _PREVIEW_COLS, column=i % _PREVIEW_COLS,
                padx=C.px(2), pady=C.px(2))

        rest = len(names) - len(shown)
        if rest > 0:
            # 放不下就报个数, 而不是把设置窗口撑高 —— 窗口高度是 576 定死的,
            # 内容一高就会被切掉, 而且从外面看不出是被切的。
            tk.Label(self._rule_preview, text="另有 %d 个" % rest,
                     bg=C.CARD, fg=C.FG_DIM, font=C.font(C.FONT_SMALL),
                     anchor="w").grid(
                row=_PREVIEW_MAX_ROWS, column=0, sticky="w",
                pady=(C.px(4), 0))

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
        self._alive = False
        # 摘掉更新回调。不摘的话, 下次检查回来时会调到一个已销毁的窗口上。
        # **只摘自己的那一个** —— 万一将来有别人注册, 不能顺手抹掉。
        # 比的必须是 __init__ 里存下的那个对象, 见那里的注释。
        if self.app.on_update_result is self._update_cb:
            self.app.on_update_result = None
        # 规则禁用窗可能还开着。**不关它**: 它自己是一个独立窗口, 而且关掉它
        # 就等于丢弃操作者刚点了一半的选择。它保存时的回调会被 _alive 挡住。
        SettingsWindow._instance = None
        self.destroy()

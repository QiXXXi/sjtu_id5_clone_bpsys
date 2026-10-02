#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用状态与联动规则。

设计要点: **所有联动规则集中在 apply_rules() 一个函数里**。
按钮/开关的回调只负责改自己的变量, 然后调用 apply_rules(); 它们绝不
直接去禁用别的控件。控件本身也完全不知道"克隆模式"的存在, 只暴露
set_enabled/get/set。这样规则只有一处, 不可能出现两个控件互相打架。

apply_rules() 是**全量重算**: 先把 lock_widgets 里的控件全部置为可用, 再让
各条规则禁用该禁用的, 最后压一层"锁定"。所以:

  **不变量 —— 凡是能点的控件都必须在 lock_widgets 里, 且它的可用状态必须由
  某条规则决定。** 建控件时顺手 set_enabled()/state="disabled" 是不行的:
  第 1 步会把它们重新启用, 而且解锁时也无从知道该恢复成什么。

  第二条不变量 —— **规则禁用控件一律走 _rule_set/_rule_disable, 不要直接
  _enable(w, False)。** 关掉下拉菜单是带"清空选中值"副作用的, 而第 1 步会先
  把所有控件打开、第 2 步再关回去, 所以"关"这个动作每帧都会发生一遍。直接关
  就等于每帧清空一次。_rule_disable 把清空收窄成**边沿行为**(只在真的从可用
  变不可用时才清), apply_rules() 才谈得上是幂等的。克隆模式最依赖这条: 四个
  求生者位存的是同一个值, 而 2/3/4 位是禁用的。

那条"最后压一层"的锁定见 lock_clicks(): 随机抽取成功后 3 秒内不响应任何
点击, 给未来的直播动画留出干净的画面。它只能靠**禁用控件**实现 ——
bind_all + "break" 拦不住控件自己的回调, 覆盖层在 Tk 里没法做半透明, 而
禁用恰好也不会波及 messagebox(它是独立顶层窗口)。

另一条: 25 个下拉菜单的 StringVar **不加 trace**。只有标志变量
(ban_count / clone_mode / map_random) 加。否则"清空→触发 trace→再清空"
会无限级联。_applying 守卫是兜底, 不是主要手段。
"""

import random
import tkinter as tk

from . import config as C


class AppState:
    """全部 Tk 变量 + 槽位控件引用 + 规则。"""

    def __init__(self, root, settings=None):
        self.root = root
        self.roster = None            # 由 Screen 注入
        self.show_note = None         # 由 Screen 注入, 用于弹提示

        settings = settings or {}
        # 留着这一份引用: set_rule_banned() 要往里写, 再由 App 那边落盘。
        # 不能只存该读的几个字段 —— 落盘写的是**整份** settings.json,
        # 少一个字段就会把主题、动画时长一起抹掉。
        self.settings = settings

        # 随机抽取后的点击锁定持续多久。设置界面直接绑这个变量。
        self.animation_seconds = tk.DoubleVar(
            master=root,
            value=settings.get("animation_seconds", C.ANIM_DEFAULT))

        # ---- 规则禁用 ----
        # 比赛规则排除掉的角色: **既不能被随机到, 也不能被手动选中**。
        # 两个入口都要堵 —— _pool()(随机池)和 pool_for()(下拉候选项);
        # 另外已经选在格子上的, 由 _apply_rule_banned() 清掉。
        #
        # 用 set 而不是 list: 每次抽取、每次弹下拉都要拿整个候选池比一遍
        # (52 + 36 个), 而这东西一年也改不了几次。
        self.rule_banned = set(settings.get("rule_banned") or ())

        # ---- 第 0 行开关 ----
        # 默认**开**: 克隆模式是常规赛制, 非克隆是少数。这里只是给变量一个初值,
        # 界面上那个 Switch 和"哪些格子被禁用"都由 apply_rules() 从它现算 ——
        # 建完控件后统一跑一次(见 screens.HomeConsoleScreen._build)。所以改初值
        # 就够了, 不需要任何地方额外"应用"一遍。
        self.clone_mode = tk.BooleanVar(master=root, value=True)
        # 地图随机只管**地图行的"随机选择"按钮能不能点**, 与抽取时机无关:
        # 地图和求生者/监管者一样, 不点按钮就一直是空的。默认开着。
        self.map_random = tk.BooleanVar(master=root, value=True)
        self.talent_random = tk.BooleanVar(master=root, value=False)   # 待开发
        self.region_random = tk.BooleanVar(master=root, value=False)   # 待开发
        self.ban_count = tk.IntVar(master=root, value=C.BAN_COUNT_DEFAULT)

        # ---- 槽位控件(由 Screen 填充) ----
        self.ban_boxes = []       # 10 个监管者 ban
        self.pick_boxes = []      # 5 个本局选择: 前 4 求生 + 第 5 监管
        self.gban_boxes = []      # 10 个全局 ban
        self.map_box = None       # 本局地图
        self.map_ban_boxes = []   # 2 个地图全局 ban
        self.map_button = None    # 地图行的"随机选择"按钮
        self.pick_buttons = []    # 5 个随机按钮

        # ---- 全部交互控件(由 Screen 填) ----
        # 这一个表担两个职责: apply_rules() 第 1 步的"默认可用"清单, 和
        # 锁定期间要禁用的清单。合成一个就不会出现"加了控件却忘了加进锁定"。
        # **不变量: 凡是 .py 里能点的控件, 都必须在这个表里, 且状态由规则决定。**
        self.lock_widgets = []
        # 锁定期间**照样可点**的控件。只有一个用户: 直播窗口的开关 —— 操作者
        # 刚抽完签, 那 3 秒里必须还能把直播窗口关掉/打开。走 _interactive() 登记
        # (这样 apply_rules() 第 1 步负责把它恢复成可用), 再在这里豁免。
        self.lock_exempt = []
        # 永久禁用的占位控件。必须走规则(_apply_stubs) —— 否则第 1 步会把
        # 它们重新启用。
        self.stub_switches = []   # 天赋随机 / 区域选择随机
        self.update_button = None # 检查角色更新
        self.syncing = False      # 后台同步进行中

        # 最近一次**随机抽取**。直播窗口靠它决定播不播动画、播哪些格子、播多久。
        # 轮询值变化是推不出这件事的: _choose() 在候选池被排除干净时会返回
        # current(见那里的 `pool = reroll or pool`), 于是克隆模式下"四个位置
        # 已经是同一个求生者"时再点随机就是 A→A —— 一个值都没变, 但控制台确实
        # 锁了 3 秒。靠 _locked 反推也不行: after 不是实时的, 时长设到 0.3 秒
        # 以下时第一拍可能落在 _unlock 之后。
        self.last_draw = None     # {"seq", "slots", "value", "items", "ms"}
        self._draw_seq = 0

        self._applying = False
        self._was_disabled = frozenset()   # 每次 apply_rules() 开头重算, 见 _rule_disable
        self._locked = False
        self._lock_after_id = None

        self.clone_mode.trace_add("write", lambda *_: self.apply_rules())
        self.ban_count.trace_add("write", lambda *_: self.apply_rules())
        self.map_random.trace_add("write", lambda *_: self.apply_rules())

    # ------------------------------------------------------------ 规则

    def apply_rules(self):
        """唯一的规则入口。任何影响可用性的改动都要走这里。

        三步走, 顺序不能乱:
          1) 先把 lock_widgets 里**全部**控件置为可用。
             各条规则只负责"该禁用的", 所以每次都得从干净的默认值开始重算 ——
             这样解锁时不需要"恢复现场", 重算一遍就是对的。
          2) 各条规则把该禁用的禁用(权威: 直接写死该控件的状态)。
          3) 锁定最后压一层。它是**约束**(在已有结果上再与一个 False), 不是
             权威, 所以必须跑在最后。

        这个函数必须是**幂等**的: 连跑两遍结果一样。第 1 步会先把所有控件打开
        再让规则关回去, 于是"关"这个动作每次都会发生一遍 —— 而关掉下拉菜单是
        带**清空**副作用的。所以进第 1 步之前先记一份"谁现在就是关着的", 第 2
        步再关它们时就不清空(见 _rule_disable)。
        """
        if self._applying:
            return
        self._applying = True
        try:
            self._was_disabled = {id(w) for w in self.lock_widgets
                                  if not self._is_enabled(w)}
            for widget in self.lock_widgets:
                self._enable(widget, True)
            self._apply_stubs()
            self._apply_ban_count()
            self._apply_clone_mode()
            self._apply_map_random()
            self._apply_syncing()
            self._apply_rule_banned()
            self._apply_lock()
        finally:
            self._was_disabled = frozenset()
            self._applying = False

    @staticmethod
    def _is_enabled(widget):
        """控件现在可不可用。三种形态各查各的。"""
        if hasattr(widget, "enabled"):        # 下拉菜单: 只读属性
            return bool(widget.enabled)
        if hasattr(widget, "_enabled"):       # Switch
            return bool(widget._enabled)
        state = widget.cget("state")
        if isinstance(state, (tuple, list)):  # ttk 偶尔给的是状态元组
            return "disabled" not in state
        return str(state) != "disabled"

    @staticmethod
    def _enable(widget, enabled, clear_if_disabled=True):
        """下拉菜单自己带 set_enabled, ttk.Button 只能用 state=。

        clear_if_disabled 只有下拉菜单认; Switch 收下但不用, ttk 控件没有这个
        概念。多出来的这个参数是为了让规则不必按控件类型分叉。
        """
        if hasattr(widget, "set_enabled"):
            widget.set_enabled(enabled, clear_if_disabled=clear_if_disabled)
        else:
            widget.configure(state="normal" if enabled else "disabled")

    def _rule_set(self, widget, enabled):
        """规则里决定一个控件的可用性 —— 所有规则都走这里, 别直接 _enable。"""
        if enabled:
            self._enable(widget, True)
        else:
            self._rule_disable(widget)

    def _rule_disable(self, widget):
        """规则要禁用一个控件。

        清空是**边沿行为**: 只有这次真的从"可用"变成"不可用"才清。本来就关着
        的, 这回只是维持原状, 再清一遍就把值抹了 —— 而 apply_rules() 一帧里会
        跑上一整遍, 那个"再清一遍"足以吃掉用户刚选好的东西。

        克隆模式正踩在这上面: 点一下"随机选择"会把同一个求生者写进四个位置, 而
        2/3/4 位是禁用的。要是重算时又清一次, 落地的就只有第一个格子。
        """
        self._enable(widget, False,
                     clear_if_disabled=id(widget) not in self._was_disabled)

    def _apply_ban_count(self):
        try:
            n = int(self.ban_count.get())
        except Exception:
            # 输入框被清空时 IntVar.get() 会抛 TclError
            n = C.BAN_COUNT_DEFAULT
            self.ban_count.set(n)
        n = max(C.BAN_COUNT_MIN, min(C.BAN_COUNT_MAX, n))
        # 先填满上面一行再填下面一行: ban_boxes 本来就是按行序排的
        for i, box in enumerate(self.ban_boxes):
            self._rule_set(box, i < n)

    def _apply_clone_mode(self):
        clone = bool(self.clone_mode.get())
        # 求生者行: 求生者位 2/3/4 禁用(第 5 位是监管者, 不受影响)
        for i in range(1, 4):
            self._rule_set(self.pick_boxes[i], not clone)
        # 随机按钮行: 按钮 2/3/4 禁用
        for i in range(1, 4):
            self._rule_set(self.pick_buttons[i], not clone)
        # 第 6-7 行: **两行**的第 2/3/4 位禁用(都是求生者位)
        for row in range(2):
            for col in C.GBAN_SURVIVOR_COLS[1:]:
                self._rule_set(self.gban_boxes[row * C.COLS + col], not clone)
        # 地图行不受克隆模式影响 —— 不需要任何处理

    def _apply_map_random(self):
        """地图随机**只管按钮可用性**: 关掉就点不了地图行的"随机选择"。

        它不影响抽取时机 —— 地图和求生者/监管者一样, 不点按钮就一直是空的。
        """
        if self.map_button is not None:
            self._rule_set(self.map_button, bool(self.map_random.get()))

    def _apply_stubs(self):
        """永久禁用的占位控件(天赋随机 / 区域选择随机)。

        以前这些是在建控件时顺手设死的(sw.set_enabled(False)), 但第 1 步会把
        它们重新启用, 所以必须收进规则里由 apply_rules 负责。
        """
        for switch in self.stub_switches:
            self._rule_set(switch, False)

    def _apply_syncing(self):
        """后台同步进行中时, "检查角色更新"不可点。

        以前是 _check_update/_finish_sync 里直接 configure(state=...)。那样在
        锁定期间同步恰好结束时, _finish_sync 会把按钮偷偷启用回来 ——
        收进规则里才关得严。
        """
        if self.update_button is not None:
            self._rule_set(self.update_button, not self.syncing)

    def _apply_rule_banned(self):
        """清掉已经落在格子上的**规则禁用**角色。

        光在候选池里过滤不够: "先选了 X、之后 X 才被规则禁用"是常态 —— 操作者
        多半是在比赛中途才发现某个角色要排除的。不清的话那些格子会留着一个
        再也选不回来的值, 而且它还会算进 used_*() 里继续挤占候选。

        不走 _rule_disable: 那不是"这个控件不可用", 是"这一格的值不合法了"。
        也因此不需要边沿判断 —— 清完它就是空的, 再跑一遍什么也不做, 幂等是
        天然的(apply_rules 每帧都跑, 这条很重要)。

        只扫角色格。地图不可能出现在 rule_banned 里 —— 规则禁用窗列的只有
        求生者和监管者。
        """
        banned = self.rule_banned
        if not banned:
            return
        for box in self.ban_boxes + self.pick_boxes + self.gban_boxes:
            if box.get() in banned:
                box.clear()

    def _apply_lock(self):
        """锁定期间禁用全部交互控件(在其它规则之上再压一层)。

        **刻意不走 _rule_disable**: 那一套是"从可用变不可用才清空", 而锁定期
        间恰好全是可用的控件被关掉 —— 走它就会把整块 BP 板抹了。锁定只是冻结
        界面, 已选内容要原样留着, 只变灰, 所以这里一律 clear_if_disabled=False。
        """
        if not self._locked:
            return
        for widget in self.lock_widgets:
            if any(widget is w for w in self.lock_exempt):
                continue          # 直播窗口的开关: 锁定期间照样能点
            if hasattr(widget, "set_enabled"):
                widget.set_enabled(False, clear_if_disabled=False)
            else:
                widget.configure(state="disabled")

    # 刻意**不**对外暴露 _locked: 直播窗口曾经想拿它反推"该不该播动画", 但那
    # 条路是错的 —— after 不是实时的, 动画时长设到 0.3 秒以下时第一拍会落在
    # _unlock 之后, 于是不播; 而时长设成 0(控制台不锁)时反而又"看起来像要播"。
    # 播不播只看抽取令牌里的 ms。见 last_draw 上面那段。

    # ------------------------------------------------------------ 点击锁定

    def anim_ms(self):
        """动画时长(毫秒)。

        输入框可能是半成品(空串 / "3."), DoubleVar.get() 会抛 TclError ——
        和 _apply_ban_count 处理 IntVar 被清空是同一类问题, 所以也照那里兜住,
        并且钳到合法区间(输入框没加校验, 什么都可能被敲进去)。
        """
        try:
            seconds = float(self.animation_seconds.get())
        except (tk.TclError, ValueError):
            seconds = C.ANIM_DEFAULT
        seconds = max(C.ANIM_MIN, min(C.ANIM_MAX, seconds))
        return int(round(seconds * 1000))

    def lock_clicks(self):
        """随机抽取成功后短暂冻结界面, 给直播动画留出干净的画面。

        只在抽取**成功**时调用: 抽取失败会弹提示框, 那时候根本不存在"动画正
        在播"这回事, 锁上语义就错了。

        不用 bind_all + "break" 拦点击: Tk 的 bindtag 顺序是
        widget → class → toplevel → all, all 上的处理器最后跑, 拦不住控件自己
        的回调(见 searchbox 文件头)。也不用覆盖层拦: Tk 没有逐控件透明。
        禁用控件是唯一既拦得住、又不会波及 messagebox 的做法。
        """
        ms = self.anim_ms()
        if ms <= 0:                      # 时长设成 0 = 关掉这个功能
            return
        if self._lock_after_id is not None:
            self.root.after_cancel(self._lock_after_id)   # 重新计时, 而非无操作
        self._locked = True
        self.apply_rules()
        self._lock_after_id = self.root.after(ms, self._unlock)

    def _unlock(self):
        self._lock_after_id = None
        self._locked = False
        if self.root.winfo_exists():     # 窗口已销毁时 apply_rules 会碰到死控件
            self.apply_rules()           # 全量重算, 锁定自然解除

    def cancel_lock(self):
        """丢弃未决的锁定计时器。切换界面/退出时调用。"""
        if self._lock_after_id is not None:
            try:
                self.root.after_cancel(self._lock_after_id)
            except tk.TclError:
                pass
            self._lock_after_id = None
        self._locked = False

    # ------------------------------------------------------------ 查询

    @staticmethod
    def _filled(boxes):
        return {b.get() for b in boxes if b.get()}

    def used_hunters(self):
        """已占用的监管者: ban 位 + 第 6-7 行第 5 位。"""
        names = self._filled(self.ban_boxes)
        for row in range(2):
            names |= self._filled([self.gban_boxes[row * C.COLS + C.GBAN_HUNTER_COL]])
        return names

    def used_survivors(self):
        """已占用的求生者: 第 6-7 行的前 4 位。"""
        names = set()
        for row in range(2):
            base = row * C.COLS
            for col in C.GBAN_SURVIVOR_COLS:
                names |= self._filled([self.gban_boxes[base + col]])
        return names

    def used_maps(self):
        return self._filled(self.map_ban_boxes)

    def pool_for(self, box, group, peers):
        """某个下拉的候选项: 同一"域"内没被别的格子占用、或就是它自己选的那个。

        三个域各自互斥 —— 监管者(ban 位 + 本局监管者 + 全局 ban 的监管位)、
        求生者(本局四个位置 + 全局 ban 的求生位)、地图(本局地图 + 两个 ban 位)。
        同一个角色不可能既被 ban 又被选, 所以下拉里不该再出现它。

        "或就是它自己选的那个"这一条不能省: 克隆模式下四个求生者位存的是
        同一个值, 否则每个格子都会把彼此算作占用, 列表直接变空。

        规则禁用也在这里堵一道: 被规则禁用的角色**不出现在任何选择列表里**。
        只堵随机(_pool)是不够的 —— 那样子还能手动把它填进 ban 位。
        """
        mine = box.get()
        items = self.roster.groups[group] if self.roster else []
        used = {p.get() for p in peers if p is not box and p.get()}
        # 地图不受规则禁用影响, 规则禁用窗里根本没有地图。这里按组判一次,
        # 免得万一某张地图跟某个角色重名, 整张地图静静地从列表里消失。
        banned = self.rule_banned if group != "map" else ()
        return [it for it in items
                if (it.value not in used or it.value == mine)
                and it.value not in banned]

    # ------------------------------------------------------------ 随机

    @staticmethod
    def _choose(items, excluded, current=""):
        """排除 excluded; 若还能避开 current 就避开, 让重复点也换一个。"""
        pool = [it for it in items if it.value not in excluded]
        reroll = [it for it in pool if it.value != current]
        pool = reroll or pool
        return random.choice(pool) if pool else None

    def _record_draw(self, slots, value, items):
        """记一笔随机抽取, 供直播窗口播动画。

        items 要的是**真正可选的集合**(排除集之外的全部), 不是 _choose() 最终
        用的那个 `reroll or pool` —— 后者是为了"再点一次换一个", 不是候选定义。
        动画要照着真实的候选池滚, 最后才落在 value 上。
        """
        self._draw_seq += 1
        self.last_draw = {"seq": self._draw_seq, "slots": list(slots),
                          "value": value, "items": list(items),
                          "ms": self.anim_ms()}

    # ------------------------------------------------------------ 规则禁用

    def set_rule_banned(self, names):
        """整份替换规则禁用名单, 并落盘。

        收的是**完整的新名单**, 不是增量 —— 规则禁用窗编辑的是一份工作副本,
        点保存时整份交过来。增量式("加一个/减一个")在这里没有好处: 窗口关掉
        之后就没人知道中间那几次点击算不算数了, 得在窗口里再存一份原始快照
        才能支持"取消", 反而更复杂。

        落盘走 app.settings 那份**引用**(构造时存的), 而不是自己重读 ——
        save_settings 写的是整个文件, 重读会把别的字段的理论上的更新盖掉。

        **要 apply_rules()**: 新禁用的角色可能正落在某个格子上, 得清掉。
        那一步在 _apply_rule_banned() 里, 是 apply_rules 的一条规则。
        """
        self.rule_banned = set(names)
        self.settings["rule_banned"] = sorted(self.rule_banned)
        C.save_settings(self.settings)
        self.apply_rules()

    def _pool(self, group, excluded):
        """候选池 = 该组的全部, 去掉排除集, 再去掉**规则禁用**的那批。

        下面三个 random_* 都先把池子算出来再交给 _choose(pool, ()) —— 传空排除
        集是**等价**的(_choose 会再过滤一遍, 而这里已经滤过了), 好处是同一个池
        子能顺手记进抽取令牌, 不必为了动画多滤一遍。

        规则禁用在这里挡住随机那一半。另一半(下拉候选项)在 pool_for(), 落在
        格子上的遗留值在 _apply_rule_banned() —— 三处合起来才是"被规则禁用的
        角色既选不到也随机不到"。
        """
        banned = self.rule_banned
        items = self.roster.groups[group]
        if not banned:
            # 空集合是常态, 别让每次抽取都多走一次 in 判断。地图组尤其冤 ——
            # 它根本不可能被规则禁用, 却也要过一遍。
            return [it for it in items if it.value not in excluded]
        return [it for it in items
                if it.value not in excluded and it.value not in banned]

    def random_survivor(self, index):
        """index 0-3。克隆模式下 index 恒为 0, 一次写四个位置。"""
        if self.roster is None:
            return False
        excluded = self.used_survivors()
        if self.clone_mode.get():
            current = self.pick_boxes[0].get()
            slots = ["pick0", "pick1", "pick2", "pick3"]
        else:
            current = self.pick_boxes[index].get()
            # 同一局四个求生者不能重复
            excluded |= {b.get() for i, b in enumerate(self.pick_boxes[:4])
                         if i != index and b.get()}
            slots = ["pick%d" % index]
        pool = self._pool("survivor", excluded)
        item = self._choose(pool, (), current)
        if item is None:
            return False
        # 克隆模式下四个格子存的是同一个值 —— 四个都要播动画
        for key in slots:
            self.pick_boxes[int(key[4:])].set(item.value)
        self._record_draw(slots, item.value, pool)
        return True

    def random_hunter(self):
        if self.roster is None:
            return False
        box = self.pick_boxes[4]
        pool = self._pool("hunter", self.used_hunters())
        item = self._choose(pool, (), box.get())
        if item is None:
            return False
        box.set(item.value)
        self._record_draw(["hunter"], item.value, pool)
        return True

    def random_map(self):
        if self.roster is None:
            return False
        pool = self._pool("map", self.used_maps())
        item = self._choose(pool, (), self.map_box.get())
        if item is None:
            return False
        self.map_box.set(item.value)
        self._record_draw(["map"], item.value, pool)
        return True

    # ------------------------------------------------------------ 局面流转

    def _first_empty_gban_row(self):
        """空 = 该行所有**已启用**槽位都为空。"""
        for row in range(2):
            base = row * C.COLS
            boxes = self.gban_boxes[base:base + C.COLS]
            if all(not b.get() for b in boxes if b.enabled):
                return row
        return None

    def _first_empty_map_ban(self):
        for box in self.map_ban_boxes:
            if box.enabled and not box.get():
                return box
        return None

    def record_round(self):
        """下一局: 记录本局选择 → 清空 ban 位与本局选择。返回提示文本(可能为空串)。"""
        picks = [b.get() for b in self.pick_boxes]
        match_map = self.map_box.get()
        notes = []

        row = self._first_empty_gban_row()
        if row is None:
            notes.append("全局ban位已满，本局选择未记录")
        else:
            base = row * C.COLS
            for col, value in enumerate(picks):
                box = self.gban_boxes[base + col]
                if box.enabled and value:
                    box.set(value)

        slot = self._first_empty_map_ban()
        if slot is None:
            notes.append("地图ban位已满，本局地图未记录")
        elif match_map:
            slot.set(match_map)

        self.clear_round()
        return "\n".join(notes)

    def clear_round(self):
        """清空 ban 位、本局选择与地图行。"""
        for box in self.ban_boxes + self.pick_boxes:
            box.clear()
        self.map_box.clear()

    def reset(self):
        """重置: 清空全部槽位(含地图行), 开关行保持不变。"""
        for box in (self.ban_boxes + self.pick_boxes +
                    self.gban_boxes + self.map_ban_boxes):
            box.clear()
        self.map_box.clear()

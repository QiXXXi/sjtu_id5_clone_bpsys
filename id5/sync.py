#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 sync_characters.py 的能力包装成可供 GUI 调用的函数。

刻意 **不修改** sync_characters.py, 也不重新打包它的 exe —— 直接 import 复用。
原文件的主流程在 if __name__ == "__main__" 保护内, import 不会触发任何副作用。

本模块会在后台线程里跑(网络下载可能几十秒), 因此:
  * 不碰任何 Tk 对象
  * 不 print 到 stdout, 进度一律通过 progress 回调上报
"""

import os
import sys

from . import config as C


def base_dir():
    """图片所在目录。与 sync_characters.base_dir() 保持一致。"""
    return C.base_dir()


def load_cli():
    """import 项目根目录下的 sync_characters 模块。"""
    base = base_dir()
    if base not in sys.path:
        sys.path.insert(0, base)
    import sync_characters
    return sync_characters


def sync_all(progress=None):
    """检查并按需下载缺失/尺寸不符的图片。

    返回:
        {
          "images":    实际下载的图片张数,
          "chars":     涉及的角色数,
          "new_names": 本次新增(此前完全没有头像)的角色名列表,
          "failed":    失败描述列表,
          "extras":    wiki 上已下线、本地却多出来的文件路径列表,
          "error":     整体失败时的原因, 否则 None,
        }
    progress: 可选回调 progress(text), 用于在主界面上显示当前步骤。
    """
    result = {"images": 0, "chars": 0, "new_names": [],
              "failed": [], "extras": [], "error": None}

    def say(text):
        if progress:
            progress(text)

    try:
        sc = load_cli()
    except Exception as exc:
        result["error"] = "无法加载 sync_characters.py: %s" % exc
        return result

    base = base_dir()

    # --- 1. 拉取 wiki 角色列表 + 核对本地 ---
    scans = []
    for group in sc.GROUPS:
        say("正在读取 %s 列表…" % group["label"])
        try:
            scans.append(sc.scan_group(group, base))
        except Exception as exc:
            result["error"] = "%s 列表读取失败: %s" % (group["label"], exc)
            return result

    for scan in scans:
        result["extras"].extend(scan["extra"])

    total = sum(len(s["todo"]) for s in scans)
    if total == 0:
        say("已是最新")
        return result

    # --- 2. 逐项下载 ---
    done = 0
    touched = set()
    for scan in scans:
        group = scan["group"]
        if not scan["todo"]:
            continue
        titles = []
        for name, kind, _path in scan["todo"]:
            suffix = sc.AVATAR_SUFFIX if kind == "头像" else sc.BODY_SUFFIX
            titles.append("文件:%s%s" % (name, suffix))
        say("正在查询 %s 的下载地址…" % group["label"])
        try:
            urls = sc.resolve_urls(titles)
        except Exception as exc:
            for name, kind, _path in scan["todo"]:
                result["failed"].append("%s 的%s (查询地址失败: %s)"
                                        % (name, kind, exc))
            continue

        for name, kind, path in scan["todo"]:
            suffix = sc.AVATAR_SUFFIX if kind == "头像" else sc.BODY_SUFFIX
            url = urls.get("文件:%s%s" % (name, suffix))
            if not url:
                result["failed"].append("%s 的%s (wiki 上找不到文件)" % (name, kind))
                continue
            # 头像文件此前不存在 -> 这是一个新角色
            is_new = kind == "头像" and not os.path.exists(path)
            done += 1
            say("正在下载 %s (%d/%d)…" % (name, done, total))
            try:
                sc.download(url, path, kind == "头像")
                result["images"] += 1
                touched.add(name)
                if is_new:
                    result["new_names"].append(name)
            except Exception as exc:
                result["failed"].append("%s 的%s (%s)" % (name, kind, exc))

    result["chars"] = len(touched)
    say("完成")
    return result

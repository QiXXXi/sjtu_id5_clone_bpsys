#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第五人格(bwiki) 角色图片同步工具
================================

检查 wiki 上是否新增了求生者 / 监管者角色，或本地是否缺图，
并把缺失的头像与无背景立绘下载到对应文件夹。

目录结构(相对本程序所在目录):
    survivor/        求生者头像   144x144 透明 PNG
    survivor_body/   求生者立绘   810x1080 透明 PNG
    hunter/          监管者头像   144x144 透明 PNG
    hunter_body/     监管者立绘   810x1080 透明 PNG

图片命名规则(wiki 文件页):
    头像: 文件:<角色名>头像2.png
    立绘: 文件:<角色名>立绘2.png
角色名中的引号在保存为本地文件时会被去掉，例如 “慈善家” -> 慈善家.png

用法:
    双击运行               检查并下载缺失的图片
    sync_characters.exe --check    只检查、不下载
    sync_characters.exe --no-pause 结束后不等待按键
"""

import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 常量配置

API = "https://wiki.biligame.com/dwrg/api.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERER = "https://wiki.biligame.com/dwrg/"

# 角色名里需要去掉的引号(全角弯引号 / 直引号 / 日式引号)
QUOTE_CHARS = "“”\"'「」"

AVATAR_SUFFIX = "头像2.png"
BODY_SUFFIX = "立绘2.png"
AVATAR_SIZE = (144, 144)

# 两个阵营: wiki 分类 -> 本地目录
GROUPS = (
    {
        "label": "求生者",
        "category": "求生者",
        "avatar_dir": "survivor",
        "body_dir": "survivor_body",
    },
    {
        "label": "监管者",
        "category": "监管者",
        "avatar_dir": "hunter",
        "body_dir": "hunter_body",
    },
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_log_lines = []


# ---------------------------------------------------------------- 基础工具

def base_dir():
    """返回程序所在目录。打包成 exe 后返回 exe 所在目录，而非临时解包目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def log(msg=""):
    """同时输出到控制台并记录到日志列表。"""
    print(msg, flush=True)
    _log_lines.append(msg)


def pause(msg="\n按回车键退出..."):
    """双击运行时停在结果处，方便查看。非交互环境下直接返回。"""
    if "--no-pause" in sys.argv:
        return
    try:
        input(msg)
    except Exception:
        pass


def setup_console():
    """把控制台切到 UTF-8，避免中文显示成乱码。"""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def clean_name(name):
    """去掉角色名中的引号，用作本地文件名。"""
    return "".join(ch for ch in name if ch not in QUOTE_CHARS)


# ---------------------------------------------------------------- 网络请求

def http(url, data=None, timeout=60, retries=3):
    """带重试的 HTTP 请求，返回响应字节。"""
    body = urllib.parse.urlencode(data).encode("utf-8") if data else None
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body)
        req.add_header("User-Agent", UA)
        req.add_header("Referer", REFERER)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:                      # 网络抖动则重试
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def api(params):
    """调用 MediaWiki API，返回解析后的 JSON。"""
    params = dict(params)
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    return json.loads(http(API, params).decode("utf-8"))


def category_members(category):
    """取某个分类下的条目名(只要主命名空间，过滤掉模板页)。"""
    data = api({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:" + category,
        "cmlimit": "500",
    })
    return [m["title"] for m in data["query"]["categorymembers"]
            if m.get("ns") == 0]


def resolve_urls(titles):
    """批量查询 文件:xxx 的真实下载地址。返回 {页面标题: url}。"""
    urls = {}
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        data = api({
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url",
        })
        for page in data["query"]["pages"]:
            info = page.get("imageinfo")
            if info:
                urls[page["title"]] = info[0]["url"]
    return urls


# ---------------------------------------------------------------- 图片处理

def png_size(raw):
    """从 PNG 头部读出宽高，无需解码整张图。读不出返回 None。"""
    if len(raw) >= 24 and raw[:8] == PNG_MAGIC and raw[12:16] == b"IHDR":
        return (int.from_bytes(raw[16:20], "big"),
                int.from_bytes(raw[20:24], "big"))
    return None


def normalize_avatar(raw):
    """把头像统一成 144x144 的透明 PNG(部分新角色的源图是 140x140)。"""
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    if img.size != AVATAR_SIZE:
        img = img.resize(AVATAR_SIZE, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def download(url, dest, is_avatar):
    """下载单张图片并原子写入目标路径。"""
    raw = http(url, timeout=120)
    if not raw[:8].startswith(b"\x89PNG") and not raw[:2] == b"\xff\xd8":
        raise ValueError("返回内容不是图片")
    if is_avatar:
        raw = normalize_avatar(raw)
    tmp = dest + ".part"
    with open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, dest)                 # 避免下载中断留下半个文件
    return len(raw)


# ---------------------------------------------------------------- 主流程

def scan_group(group, base):
    """核对一个阵营：找出缺图、尺寸不符、以及多余(已下线)的文件。"""
    names = category_members(group["category"])
    avatar_dir = os.path.join(base, group["avatar_dir"])
    body_dir = os.path.join(base, group["body_dir"])
    os.makedirs(avatar_dir, exist_ok=True)
    os.makedirs(body_dir, exist_ok=True)

    wanted_avatar = {}
    wanted_body = {}
    for name in names:
        clean = clean_name(name)
        wanted_avatar[clean + ".png"] = (name, os.path.join(avatar_dir, clean + ".png"))
        wanted_body[clean + ".png"] = (name, os.path.join(body_dir, clean + ".png"))

    # 需要下载/修复的条目: (角色名, 类型, 本地路径)
    todo = []
    for filename, (name, path) in wanted_avatar.items():
        if not os.path.exists(path):
            todo.append((name, "头像", path))
        else:
            with open(path, "rb") as fh:
                size = png_size(fh.read(32))
            if size != AVATAR_SIZE:
                todo.append((name, "头像", path))       # 尺寸不符 -> 重新拉取
    for filename, (name, path) in wanted_body.items():
        if not os.path.exists(path):
            todo.append((name, "立绘", path))

    # 本地多出来的文件(角色已从 wiki 移除) —— 只报告，不删除
    extra = []
    for directory, wanted in ((avatar_dir, wanted_avatar), (body_dir, wanted_body)):
        for entry in os.listdir(directory):
            if entry.endswith(".png") and entry not in wanted:
                extra.append(os.path.join(directory, entry))

    return {
        "group": group,
        "names": names,
        "todo": todo,
        "extra": extra,
        "avatar_dir": avatar_dir,
        "body_dir": body_dir,
    }


def main():
    setup_console()
    check_only = "--check" in sys.argv
    base = base_dir()

    log("=" * 62)
    log(" 第五人格 角色图片同步工具")
    log(" 数据源: wiki.biligame.com/dwrg")
    log(" 目录:   " + base)
    if check_only:
        log(" 模式:   仅检查，不下载")
    log("=" * 62)
    log()

    # --- 1. 读取 wiki 列表 -------------------------------------------------
    log("[1/3] 读取 wiki 角色列表 ...")
    scans = []
    for group in GROUPS:
        try:
            scan = scan_group(group, base)
        except Exception as exc:
            log("      %s 读取失败: %s" % (group["label"], exc))
            log("      请检查网络连接后重试。")
            write_log(base)
            pause()
            return 1
        scans.append(scan)
        log("      %-6s %2d 个角色" % (group["label"], len(scan["names"])))

    # --- 2. 检查本地文件 ---------------------------------------------------
    log()
    log("[2/3] 检查本地文件 ...")
    total_todo = 0
    for scan in scans:
        group = scan["group"]
        n = len(scan["names"])
        n_avatar = sum(1 for t in scan["todo"] if t[1] == "头像")
        n_body = sum(1 for t in scan["todo"] if t[1] == "立绘")
        total_todo += len(scan["todo"])
        log("      %-6s 头像 %d/%d 齐全，立绘 %d/%d 齐全" % (
            group["label"], n - n_avatar, n, n - n_body, n))

    if total_todo == 0:
        log()
        log("[3/3] 无需下载，全部图片已是最新。")
    else:
        log()
        log("[3/3] 发现 %d 项需要处理:" % total_todo)
        for scan in scans:
            for name, kind, path in scan["todo"]:
                tag = "新增" if not os.path.exists(path) else "修复"
                log("      [%s] %s 的%s" % (tag, name, kind))

        if check_only:
            log()
            log("(仅检查模式，未下载。去掉 --check 重新运行即可下载。)")
        else:
            log()
            log("      开始下载 ...")
            ok = 0
            failed = []
            for scan in scans:
                group = scan["group"]
                # 一次性把需要下载的文件地址查出来
                titles = []
                for name, kind, path in scan["todo"]:
                    suffix = AVATAR_SUFFIX if kind == "头像" else BODY_SUFFIX
                    titles.append("文件:%s%s" % (name, suffix))
                try:
                    urls = resolve_urls(titles)
                except Exception as exc:
                    log("      %s 查询下载地址失败: %s" % (group["label"], exc))
                    continue

                for name, kind, path in scan["todo"]:
                    suffix = AVATAR_SUFFIX if kind == "头像" else BODY_SUFFIX
                    url = urls.get("文件:%s%s" % (name, suffix))
                    if not url:
                        failed.append("%s 的%s (wiki 上找不到文件)" % (name, kind))
                        continue
                    try:
                        size = download(url, path, kind == "头像")
                        ok += 1
                        log("      √ %s 的%s  (%d KB)" % (name, kind, size // 1024))
                    except Exception as exc:
                        failed.append("%s 的%s (%s)" % (name, kind, exc))

            log()
            log("      下载完成: 成功 %d 项，失败 %d 项" % (ok, len(failed)))
            for item in failed:
                log("      × " + item)

    # --- 报告多余文件 ------------------------------------------------------
    extras = [p for scan in scans for p in scan["extra"]]
    if extras:
        log()
        log("提示: 以下本地文件在 wiki 上已找不到对应角色(可能已下线)，未做改动:")
        for path in extras:
            log("      " + os.path.relpath(path, base))

    # --- 汇总 --------------------------------------------------------------
    log()
    log("-" * 62)
    for scan in scans:
        group = scan["group"]
        a = len([f for f in os.listdir(scan["avatar_dir"]) if f.endswith(".png")])
        b = len([f for f in os.listdir(scan["body_dir"]) if f.endswith(".png")])
        log(" %-6s %s: %d 张头像,  %s: %d 张立绘" % (
            group["label"], group["avatar_dir"], a, group["body_dir"], b))
    log("-" * 62)
    log("全部完成。")

    write_log(base)
    pause()
    return 0


def write_log(base):
    """在程序目录留下日志，方便事后查看。"""
    try:
        path = os.path.join(base, "sync_log.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S\n"))
            fh.write("\n".join(_log_lines))
        sys.stderr.write("")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)

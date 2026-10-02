#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查更新: 问 GitHub Releases 要最新版本号, 并按需下载安装包。

## 为什么是 GitHub Releases, 而不是自己放一份 version.json

因为**发版流程已经在那儿了**。tag、release notes、安装包是同一次操作产出的;
再维护一份手写的清单就多一处会忘记同步的地方, 而且忘了不报错 —— 只会永远
显示"已是最新"。查询本身是一次匿名的 GET, 公开仓库不需要任何凭据。

代价是匿名访问有 60 次/小时/IP 的限流(GitHub 按整个出口 IP 算)。我们一次
启动查一次, 正常用碰不到; 真碰到了当"检查失败"处理, 不重试、不刷屏。

## 本地缓存

更新日志(全部历史版本的说明)会存一份在本机, 打开窗口时先读它。启动时那次
check() 拿到的最新一版也会并进去 —— 所以"更新完第一次打开程序"那个弹窗是
**零请求**的。详见下面"本地缓存"一节。

## 为什么全是 stdlib

和 sync_characters 一样只用 urllib —— 不再多一个依赖。这东西要打包成 exe
发给别人, 每多一个第三方包就多一份体积和一份 import 失败的可能。

## 版本号怎么比

远端是 tag(形如 "v1.1.0"), 本地是 config.APP_VERSION("1.1.0")。
parse_version() 两边都吃得下: 去掉开头的 v、只取前三段数字、忽略 -beta 之类
的后缀。**比不了的一律当"没有更新"** —— 提示一个不存在的更新比漏报更糟。

## 异常

对外只抛 UpdateError, 消息是**给人看的**(会直接进状态栏/弹窗), 不带堆栈。
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from . import config as C

API = "https://api.github.com/repos/%s/releases/latest" % C.APP_REPO
# 更新日志要的是"全部版本", 上面那个 /releases/latest 只给一个。
LIST_API = "https://api.github.com/repos/%s/releases?per_page=100" % C.APP_REPO
# GitHub 的 API **必须**带 User-Agent, 不带直接 403 —— 而且返回的是一句
# "API rate limit exceeded", 看着像限流, 排查起来很绕。
UA = "id5-clone-bp-updater"

# 单次请求超时。检查和下载分开: 20MB 的包在慢网下要几分钟, 用 15 秒会
# 每次都失败。这个值是**两次读之间的**超时, 不是总时长。
CHECK_TIMEOUT = 15
DOWNLOAD_TIMEOUT = 30


class UpdateError(Exception):
    """检查或下载失败。消息可以直接显示给用户。"""


# ---------------------------------------------------------------- 版本号

def parse_version(text):
    """'v1.1.0' / '1.1' / '1.1.0-beta.2' -> (1, 1, 0)。解析不了返回 None。

    补齐成三段是为了让元组比较有意义: (1, 1) > (1, 1, 0) 在 Python 里是 True
    (前缀相等时短的更小), 而 1.1 和 1.1.0 明明是同一个版本。
    """
    if not text:
        return None
    m = re.match(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text).strip())
    if not m:
        return None
    return tuple(int(g) if g is not None else 0 for g in m.groups())


def is_newer(remote, current):
    """remote 比 current 新吗。任何一边解析不了都返回 False(见模块头)。"""
    r, c = parse_version(remote), parse_version(current)
    if r is None or c is None:
        return False
    return r > c


# ---------------------------------------------------------------- 请求

def _get(url, timeout):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("找不到发布页（仓库不存在，或还没有发布过版本）")
        if e.code == 403:
            # 403 有两种: 限流, 和 UA/Accept 不合规。我们两个头都带了, 所以
            # 基本只会是限流。
            raise UpdateError("GitHub 拒绝了这次查询（多半是访问太频繁，请稍后再试）")
        raise UpdateError("GitHub 返回 HTTP %s" % e.code)
    except urllib.error.URLError as e:
        raise UpdateError("连不上 GitHub：%s" % (getattr(e, "reason", e),))
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError("请求失败：%s" % e)


def check(timeout=CHECK_TIMEOUT):
    """查最新版本。返回 dict, 失败抛 UpdateError。

    字段:
      current      本地版本(config.APP_VERSION)
      latest       远端版本(已经去掉了开头的 v)
      has_update   远端比本地新
      notes        release 正文, 可能很长 —— 截断是调用方的事
      release_url  发布页地址(没有安装包时让用户去这儿)
      asset_url    安装包直链, 没有则为 None
      asset_name   安装包文件名(已取 basename)
      asset_size   字节数, 拿不到为 0
    """
    try:
        data = json.loads(_get(API, timeout).decode("utf-8"))
    except ValueError:
        raise UpdateError("GitHub 返回的不是有效数据")

    tag = data.get("tag_name") or ""
    latest = tag[1:] if tag[:1] in ("v", "V") else tag

    # 顺手把这一版的说明存进本地缓存(见"本地缓存"一节)。**不 bump 时间戳**,
    # 所以它顶不掉别的版本、也不会让窗口以为整表都新鲜。
    # 这样"更新完第一次启动弹更新日志"是零请求的: 说明在这次检查里已经到手。
    remember_release(_release_entry(data) if _visible(data) else None)

    # 挑附件: 优先 .exe。将来往 release 里多传了别的附件也还选得中。
    assets = data.get("assets") or []
    asset = next((a for a in assets
                  if str(a.get("name", "")).lower().endswith(".exe")), None)
    if asset is None and assets:
        asset = assets[0]

    return {
        "current": C.APP_VERSION,
        "latest": latest,
        "has_update": is_newer(latest, C.APP_VERSION),
        "notes": data.get("body") or "",
        "release_url": data.get("html_url") or
                       "https://github.com/%s/releases" % C.APP_REPO,
        "asset_url": (asset or {}).get("browser_download_url"),
        # basename: 附件名是远端给的, 别让它带出目录
        "asset_name": os.path.basename((asset or {}).get("name") or ""),
        "asset_size": (asset or {}).get("size") or 0,
    }


def _release_entry(rel):
    """GitHub 的一条 release JSON -> 我们自己的条目。解析不出东西就返回 None。

    check() 和 releases() 都用它: 前者从 /releases/latest 拿一条, 后者从
    /releases 拿一列, 两条路径存进本地缓存的必须是**同一种形状** —— 否则同一
    版本先被 check() 存一次、再被 releases() 存一次, 内容会不一样。
    """
    if not isinstance(rel, dict):
        return None
    tag = rel.get("tag_name") or ""
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if parse_version(version) is None:
        return None          # 版本号解析不了就没法排序/定位, 丢掉
    return {
        "version": version,
        "tag": tag,
        "name": rel.get("name") or tag,
        # 正文可能很长, 也可能为空(发版时没写说明) —— 原样存, 截断是调用方的事
        "notes": rel.get("body") or "",
        # published_at 是 ISO8601("2026-10-03T12:34:56Z"), 前 10 位就是日期。
        # **不要用 strptime 转**: 那是为了拿到一个我们马上又要格式化的东西。
        "date": (rel.get("published_at") or "")[:10],
        "url": rel.get("html_url") or
               "https://github.com/%s/releases" % C.APP_REPO,
        "prerelease": bool(rel.get("prerelease")),
    }


def _visible(rel):
    """这一条该不该出现在更新日志里。

    草稿只有仓库成员看得见, 本来就不该出现。预发布也跳过: tag 常写成
    v1.2.0-beta, 解析出来和正经 1.2.0 一模一样, 并排放在侧边栏里没法区分,
    反倒是误导。
    """
    return not (rel.get("draft") or rel.get("prerelease"))


def releases(timeout=CHECK_TIMEOUT):
    """全部历史版本的说明。返回 list, 新的在前, 失败抛 UpdateError。

    每一项:
      version     去掉 v 的版本号("1.1.0")
      tag         原始 tag("v1.1.0")
      name        release 标题(publish.py 填的那行)
      notes       release 正文(同上)
      date        "YYYY-MM-DD", 拿不到为空串
      url         发布页地址
      prerelease  是不是预发布

    这是一次 /releases 列表请求(和 check() 的 /releases/latest 是两个接口),
    所以**只在真要看日志时才调** —— 启动时那次静默检查不该顺带拉全部历史。

    per_page=100 是接口上限; 目前一共几个版本, 够用很久。

    **返回值已经落盘**(见本模块"本地缓存"一节), 调用方不用自己存。
    """
    try:
        data = json.loads(_get(LIST_API, timeout).decode("utf-8"))
    except ValueError:
        raise UpdateError("GitHub 返回的不是有效数据")
    if not isinstance(data, list):
        raise UpdateError("GitHub 返回的不是有效数据")

    out = [e for e in (_release_entry(r) for r in data if _visible(r)) if e]
    save_releases(out)
    return out


# ---------------------------------------------------------------- 本地缓存
#
# 更新日志要"打开就能看, 不要每次都联网"(用户要求)。所以:
#
#   * releases() 拿到整表后**整表落盘**;
#   * check() 拿到最新那一条后**并进缓存** —— 启动时那次静默检查本来就要请求
#     /releases/latest, 新版本的说明顺手就存下来了。于是"更新完第一次打开程序,
#     弹窗显示这一版改了什么"**一个请求都不用发**;
#   * 窗口先读缓存渲染(秒开), 只有缓存不新鲜时才去联网。
#
# 缓存文件跟 settings.json 放一起(都在 base_dir()), 同属"本机状态"那一类,
# 不进仓库。

CACHE_FILE = "changelog.json"
CACHE_TTL = 6 * 3600      # 整表多久算过期 —— 窗口按它决定要不要联网
CACHE_MAX = 50            # 最多存几条。列表接口一页 100, 存 50 够覆盖很长的
                          # 历史, 又不至于让文件一直长下去。


def cache_path():
    return os.path.join(C.base_dir(), CACHE_FILE)


def _read_cache():
    """-> (条目表, 拉取时间戳)。没有 / 读坏了 / 手工改烂了都回 ([], 0.0)。"""
    try:
        with open(cache_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("releases")
        at = float(raw.get("fetched_at") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return [], 0.0
    if not isinstance(items, list):
        return [], 0.0
    return [e for e in items if isinstance(e, dict) and e.get("version")], at


def cached_releases():
    """本地缓存的版本说明, 新的在前。没有就返回空表。"""
    return _read_cache()[0]


def cache_is_fresh():
    """缓存是不是还新鲜。没有缓存 = 不新鲜(时间戳 0, 差值是无穷大)。"""
    return (time.time() - _read_cache()[1]) < CACHE_TTL


def save_releases(items):
    """整表落盘, 盖上当前时间戳。"""
    _write_cache(items, time.time())


def remember_release(entry):
    """把**一条**并进缓存, **不更新时间戳**。

    时间戳的含义是"整表是什么时候拉的"。并进来的一条只说明"这一版存在",
    不代表其余部分也是新的 —— 顺手更新时间戳的话, 窗口会以为整表都新鲜而
    不再联网, 缺的那几版就永远补不上了。
    """
    if not entry:
        return
    items, at = _read_cache()
    _write_cache(_merged(items, [entry]), at)


def _write_cache(items, fetched_at):
    try:
        with open(cache_path(), "w", encoding="utf-8") as f:
            json.dump({"fetched_at": fetched_at,
                       "releases": _merged(items)[:CACHE_MAX]},
                      f, ensure_ascii=False, indent=2)
    except OSError:
        pass        # 目录只读之类: 后果只是下次还得联网, 不该让调用方处理


def _merged(*groups):
    """按版本号倒序合并去重。

    **同一版本后出现的覆盖先出现的**: 这样"刚拉下来的那份"总能盖掉缓存里的
    旧副本 —— 发版之后又改了 release 说明也能跟上, 而不是永远显示第一次存下的。
    """
    by_version = {}
    for group in groups:
        for entry in group or ():
            if isinstance(entry, dict) and entry.get("version"):
                by_version[entry["version"]] = entry
    return sorted(by_version.values(),
                  key=lambda e: (parse_version(e["version"]),
                                 e.get("date") or ""),
                  reverse=True)


def download(url, dest, progress=None, timeout=DOWNLOAD_TIMEOUT):
    """下载到 dest。progress(已收字节, 总字节), 总字节拿不到时为 0。

    **先写 .part 再改名**: 下到一半失败/被杀进程, 留下的是一个 .part, 而不是
    一个看起来正常、双击却报错的安装包 —— 那个用户是分辨不出来的。
    """
    tmp = dest + ".part"
    body = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(body, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress is not None:
                        progress(got, total)
    except urllib.error.HTTPError as e:
        _cleanup(tmp)
        raise UpdateError("下载失败：GitHub 返回 HTTP %s" % e.code)
    except urllib.error.URLError as e:
        _cleanup(tmp)
        raise UpdateError("下载中断：%s" % (getattr(e, "reason", e),))
    except OSError as e:
        _cleanup(tmp)
        raise UpdateError("写入文件失败：%s" % e)
    except Exception as e:
        _cleanup(tmp)
        raise UpdateError("下载失败：%s" % e)
    os.replace(tmp, dest)          # 同一分区上, 这是原子的
    return dest


def _cleanup(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- 下载目录

def _known_downloads():
    """问 Windows 要"下载"文件夹的真实位置。

    **不要猜 ~/Downloads**: 国内机器上它经常被重定向到别的盘(改过"位置"选项卡
    的话注册表里指向 D:\\Downloads), 或者干脆没有这个文件夹 —— 猜错的后果是
    把 20MB 的安装包写到一个用户找不到的地方, 而且不报错。
    """
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

    # FOLDERID_Downloads = {374DE290-123F-4565-9164-39C4925E467B}
    folder = GUID(0x374DE290, 0x123F, 0x4565,
                  (ctypes.c_byte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E,
                                      0x46, 0x7B))
    out = ctypes.c_wchar_p()
    hres = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(folder), 0, None, ctypes.byref(out))
    if hres != 0:
        raise OSError("SHGetKnownFolderPath 返回 0x%08x" % (hres & 0xFFFFFFFF))
    try:
        return out.value
    finally:
        # 这个串是 COM 分配出来的, 要用 CoTaskMemFree 还回去
        ctypes.windll.ole32.CoTaskMemFree(out)


def downloads_dir():
    """安装包存哪儿。第一顺位是系统认的"下载", 其次 ~/Downloads, 最后家目录。"""
    for path in (_known_downloads(),
                 os.path.join(os.path.expanduser("~"), "Downloads")):
        try:
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass
    return os.path.expanduser("~")

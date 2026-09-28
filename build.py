#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包: PyInstaller 出 exe -> 拷散装素材 -> Inno Setup 出安装包。

    python build.py                # 全流程
    python build.py --skip-iss     # 只到 dist/id5_clone/ 为止(不出安装包)

产物:
    dist/id5_clone/id5_clone.exe     能直接双击跑的目录版
    installer_out/id5_clone-<版本>-setup.exe

## 为什么素材是"拷"进去而不是打进 exe

见 id5_clone.spec 的模块注释: `config.base_dir()` 在打包后返回 exe 所在目录,
素材放别处它找不到; 而且 survivor/ hunter/ map_square/ 和 settings.json 都要能写。
所以 spec 里一个 datas 都没有, 全靠这里拷。

## 版本号只有一个来源

从 `id5/config.py` 里 **import** 出来, 不在这里再抄一份, 也不去正则抠源码 ——
抠正则的东西改了写法就悄悄对不上, 而 import 出来的就是设置窗口里显示的那一个。
版本号和发行者通过 ISCC 的 `/D` 传进 installer.iss。
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "id5_clone.spec")
ISS = os.path.join(ROOT, "installer.iss")

APPNAME = "id5_clone"
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
APPDIR = os.path.join(DIST, APPNAME)          # PyInstaller 的 onedir 输出
OUT_ISS = os.path.join(ROOT, "installer_out")  # 安装包输出目录

# 散装素材, 必须落在 exe 旁边。**这里面没有 survivor_body / hunter_body** ——
# 那两套立绘(共 29 MB)全项目一行都不读, 装进去只是白占安装包体积。代价说清楚:
# sync_characters 是拿它们当"该有哪些文件"的清单的, 所以首次「检查角色更新」
# 会把它们重新下回来。要改成附带, 把它们加进这个列表就行, 别处不用动。
DIRS = ["survivor", "hunter", "map_square", "fonts"]
FILES = ["bg.jpg", "LICENSE"]

# settings.json **故意不发**。缺文件时 load_settings() 会逐字段退回默认值,
# 首次运行时自己写一份出来。发一份进去反而会把开发机上的皮肤/时长带给用户。
SKIP_IF_MISSING = {"settings.json"}


def log(msg):
    print("[build] %s" % msg, flush=True)


def die(msg):
    print("[build] 失败: %s" % msg, file=sys.stderr, flush=True)
    sys.exit(1)


# ------------------------------------------------------------------ 配置

def load_config():
    """拿到 APP_VERSION / APP_AUTHOR / APP_LICENSE。

    **import 而不是解析源码**: 这三个值在设置窗口里显示的是同一份, 从同一个
    模块读出来就不可能对不上。config.py 只 import 标准库, 导入它没有副作用
    (不会建窗口、不会读文件)。
    """
    sys.path.insert(0, ROOT)
    try:
        from id5 import config as C
    except Exception as exc:
        die("读不到 id5/config.py: %r" % (exc,))
    return C


def define(name, value):
    """拼一个 ISCC 的 /D 参数。

    ISCC 的 /D 是**按空格拆参数**的, 值里带空格或引号会被切碎并且报一个跟
    真实原因毫不相干的错, 所以在这里拦下来讲清楚。
    """
    if not value or any(ch.isspace() or ch in '"\'' for ch in value):
        die("/D%s 的值 %r 里有空格或引号, ISCC 接不住。"
            "改掉 config.py 里那个常量, 或者手动编译 installer.iss。" % (name, value))
    return "/D%s=%s" % (name, value)


# ------------------------------------------------------------------ 步骤

def clean():
    """删掉上一轮的产物。

    只动这三块, 而且**先确认它们确实在项目目录里** —— 这是个会递归删目录的
    函数, `ROOT` 万一算错(比如从别处 import 进来跑)就是灾难。
    """
    for path in (BUILD, DIST, OUT_ISS):
        if os.path.dirname(os.path.abspath(path)) != ROOT:
            die("拒绝删除项目目录之外的东西: %s" % path)
        if os.path.isdir(path):
            log("清理 %s" % os.path.relpath(path, ROOT))
            shutil.rmtree(path)


def run_pyinstaller():
    log("PyInstaller 打包中(要一会儿)…")
    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--distpath", DIST,
           "--workpath", BUILD, SPEC]
    t = time.time()
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        die("PyInstaller 退出码 %d" % proc.returncode)
    if not os.path.isfile(os.path.join(APPDIR, APPNAME + ".exe")):
        die("PyInstaller 说成功了但 %s.exe 不在, 检查 spec" % APPNAME)
    log("exe 好了(%.0fs)" % (time.time() - t))


def copy_assets():
    """把散装素材拷到 exe 旁边。"""
    log("拷素材…")
    for name in DIRS:
        src = os.path.join(ROOT, name)
        if not os.path.isdir(src):
            die("缺少素材目录 %s —— 先跑一次 sync_characters 把图片下下来" % name)
        dst = os.path.join(APPDIR, name)
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        log("  %s/  %d 个文件" % (name, _count(dst)))
    for name in FILES:
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            if name in SKIP_IF_MISSING:
                continue
            die("缺少文件 %s" % name)
        shutil.copy2(src, os.path.join(APPDIR, name))
        log("  %s  %.1f KB" % (name, os.path.getsize(src) / 1024.0))


def _count(path):
    n = 0
    for _root, _dirs, files in os.walk(path):
        n += len(files)
    return n


def find_iscc():
    """找 ISCC.exe。找不到就返回 None(调用方给一句能照着做的提示)。"""
    env = os.environ
    candidates = [
        os.path.join(env.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
        os.path.join(env.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(env.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
    ]
    which = shutil.which("ISCC")
    if which:
        candidates.insert(0, which)
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def run_iss(cfg):
    iscc = find_iscc()
    if iscc is None:
        die("找不到 ISCC.exe。装一个 Inno Setup 6:\n"
            "        winget install --id JRSoftware.InnoSetup\n"
            "      或者先只出目录版:  python build.py --skip-iss")
    log("编译安装包 %s" % iscc)
    cmd = [iscc,
           define("AppVersion", cfg.APP_VERSION),
           define("AppPublisher", cfg.APP_AUTHOR),
           define("AppLicense", cfg.APP_LICENSE),
           "/O" + OUT_ISS,
           ISS]
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        die("ISCC 退出码 %d" % proc.returncode)


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser(description="打包 id5_clone")
    ap.add_argument("--skip-iss", action="store_true",
                    help="只出 dist/id5_clone/, 不编译安装包")
    ap.add_argument("--no-clean", action="store_true",
                    help="保留 build/ 和 dist/(增量打包, 快但不干净)")
    args = ap.parse_args()

    cfg = load_config()
    log("版本 %s / %s / %s" % (cfg.APP_VERSION, cfg.APP_AUTHOR, cfg.APP_LICENSE))

    if not os.path.isfile(SPEC):
        die("找不到 %s" % SPEC)
    if not args.no_clean:
        clean()

    run_pyinstaller()
    copy_assets()

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _d, fs in os.walk(APPDIR) for f in fs)
    log("dist/%s/ 共 %.1f MB —— 双击 %s.exe 就能跑"
        % (APPNAME, total / 1048576.0, APPNAME))

    if args.skip_iss:
        log("跳过安装包(--skip-iss)")
        return
    if not os.path.isfile(ISS):
        die("找不到 %s" % ISS)
    run_iss(cfg)
    for f in sorted(os.listdir(OUT_ISS)):
        log("安装包: installer_out/%s  (%.1f MB)"
            % (f, os.path.getsize(os.path.join(OUT_ISS, f)) / 1048576.0))


if __name__ == "__main__":
    main()

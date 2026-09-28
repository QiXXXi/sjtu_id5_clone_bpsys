# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。**由 build.py 调用**, 别直接跑 pyinstaller ——
素材拷贝和安装包那两步也在 build.py 里。

## 只打代码, 不打素材

survivor/ hunter/ map_square/ fonts/ bg.jpg 全部留成 exe 旁边的散装文件。这是
**必须的**, 不是图省事:

  * `config.base_dir()` 在打包后返回 **exe 所在目录**(不是 _MEIPASS 临时目录),
    素材放那儿它才找得到;
  * 更要紧的是那几个目录**要能写** —— 「检查角色更新」往 survivor/ hunter/ 里
    下新角色, settings.json 也存在旁边。塞进 exe 里(或 _internal/)就写不进去。

代价是安装包得多带一份散装目录, 由 installer.iss 摆好。

## sync_characters 冻进包里

`id5/sync.py` 是**运行时**才 `import sync_characters` 的(还先往 sys.path 里插
了一圈), PyInstaller 的静态分析看不见这种, 所以走 hiddenimport。它只用标准库,
冻进来最干净 —— 于是 exe 旁边不需要再放一个 .py, 也就没有"两份会走偏"的问题。

## console=False 的连带影响

windowed 模式下 PyInstaller 把 sys.stdout/sys.stderr 设成 **None**, 于是任何
`sys.stderr.write` 都会 AttributeError。全项目唯一一处是
`live_window._report`, 已经兜住了(见那里的注释) —— 那里要是漏了, 直播窗口会
在第一次出错时**整个定格**。
"""

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["sync_characters"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 一个都用不到, 但环境里装了就会被扫进去。Pillow 和 pypinyin 都不依赖它们。
    # PIL.ImageQt 是 Pillow 里拉 Qt 的那条路, 我们只用 ImageTk。
    excludes=[
        "numpy", "scipy", "pandas", "matplotlib",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "IPython", "pytest", "nose", "docutils", "sphinx",
        "PIL.ImageQt",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="id5_clone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX 压过的 exe 被杀软误报的概率明显更高, 而这个安装包是要发给别人的 ——
    # 省下的那点体积换"打开就被拦"不值得。
    upx=False,
    console=False,          # GUI 程序, 不要黑框
    # False = 未捕获的异常弹一个对话框。打包版没有控制台, 这是唯一的报错出口,
    # 所以留着。
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="id5_clone",
)

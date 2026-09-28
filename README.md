# 第五人格 BP 工具

给第五人格（Identity V）赛事转播用的 BP 操作台。两个窗口：

- **控制台** —— 10 行 × 5 列的操作台。选地图、选角色、随机抽取、点击锁定。
- **直播界面** —— 与控制台实时同步的第二个窗口。无边框，可拖动，专门给 OBS 抓画面用。
  从控制台页脚的「打开直播bp界面」开关。

## 运行环境

Python 3.12（3.10+ 应该也能跑）。依赖只有两个：

```
pip install -r requirements.txt
```

- `pillow` —— 头像缩放、抠图合成
- `pypinyin` —— 下拉框的拼音/首字母检索（敲 `cz` 能搜到「厂长」）

## 快速开始

```
python app.py                      # 自动挑一个放得下屏幕的 16:9 尺寸
python app.py --size 1440x810      # 固定尺寸，便于复现问题
```

**先看下一节。仓库里不含游戏素材**，直接跑起来下拉框是空的。

## 素材：仓库里没有，要自己准备

这个仓库**只放代码**。角色图、地图、字体都是第三方版权素材（详见文末「版权」），
不适合放在公开仓库里再分发，所以一个都没传。

程序在素材缺失时的表现是**降级**而不是崩溃：`survivor/` 和 `hunter/` 这两个目录
用空占位文件保住了，所以 clone 下来直接就能启动，只是下拉框里没有东西可选。

| 目录 / 文件 | 内容 | 规格 | 必需 | 怎么准备 |
|---|---|---|---|---|
| `survivor/` | 求生者头像 | 144×144 透明 PNG，**文件名就是角色名** | 是 | `python sync_characters.py` 自动下 |
| `hunter/` | 监管者头像 | 同上 | 是 | 同上 |
| `map_square/` | 地图缩略图 | PNG，宽高比约 403:262 | 否 | **要自己放**，见下 |
| `fonts/` | 界面字体 | `.ttf` / `.otf` / `.ttc` | 否 | 见 `fonts/说明.txt` 里的下载地址 |
| `bg.jpg` | 直播界面背景图 | 任意 | 否 | 自己放 |

没有 `map_square/` 就是地图下拉框为空；没有 `fonts/` 会退回微软雅黑；没有 `bg.jpg`
直播界面就是纯黑底。都不影响程序运行。

### 自动下载角色图

```
python sync_characters.py --check    # 只看缺哪些，不下载
python sync_characters.py            # 下载
```

这个脚本只处理**求生者和监管者的头像/立绘**。

> `survivor_body/` 和 `hunter_body/` 里的立绘（810×1080）**程序一个字节都不读**，
> 是同步脚本顺带下的。嫌占地方可以删掉，不影响任何功能。

### 地图要手动放

同步脚本**不管地图**。`map_square/` 里的文件名必须是下面这几个英文名（程序按文件名
映射成中文显示，映射表在 `id5/config.py` 的 `MAP_NAMES`，改那里可以加图）：

```
ArmsFactory.png         军工厂
ChinaTown.png           唐人街
Darkwoods.png           不归林
EversleepingTown.png    永眠镇
LakesideVillage.png     湖景村
LeosMemory.png          里奥的回忆
MoonlitRiverPark.png    月亮河公园
SacredHeartHospital.png 圣心医院
TheRedChurch.png        红教堂
```

## 怎么用

界面上从左到右、从上到下：

- **第 1 行开关**：克隆模式 / 地图随机 / 天赋随机（待开发）/ 区域选择随机（待开发），
  最右是**监管者 ban 位数量（0-10）**。
- **本局地图** —— 下拉选地图，右边那个大按钮是「随机选择」。
- **监管者Ban位 1-10** —— 按上面的 ban 位数量启用，多出来的会置灰。
- **求生者 1-4** 和 **监管者** —— 五个主位。
- **全局Ban位 1-10** —— 前 4 列是求生者全局 ban，第 5 列是监管者全局 ban。克隆模式下
  求生者全局 ban 只开放每行第一列（共 2 个）。
- **下一局 / 重置** —— 清空重来。
- **打开直播bp界面** —— 开关直播窗口（这个按钮不受点击锁定影响）。
- **检查角色更新** —— 调 `sync_characters.py` 拉新角色。
- **设置** —— 白天/黑夜皮肤、随机后的点击锁定时长。

**点击锁定**：点「随机选择」之后，界面会锁定几秒不响应点击，防止手快连点。时长在设置里
调，`0` 表示关掉这个功能。

**直播界面**：无边框、可拖动，右键或 `Esc` 关闭。它会出现在任务栏里。用 OBS 的
「窗口捕获」抓它即可。

## 打包成 exe / 安装包

```
python build.py              # 全流程：PyInstaller → 拷素材 → Inno Setup
python build.py --skip-iss   # 只出 dist/id5_clone/，不编译安装包
python build.py --no-clean   # 增量，保留 build/ dist/
```

Windows 上也可以直接双击 `打包.bat`。

- 产物：`dist/id5_clone/`（免安装目录版）、`installer_out/*-setup.exe`（安装包）
- 编译安装包需要 [Inno Setup 6](https://jrsoftware.org/isinfo.php)：
  `winget install --id JRSoftware.InnoSetup`
- 注意 `build.py` 会把**你本地的 `survivor/`、`hunter/`、`map_square/`、`fonts/`、
  `bg.jpg` 一起拷进安装包**——也就是说打出来的安装包里会带着那些第三方素材。自己留着用
  没问题，要往外发请先确认素材的授权（见下）。

## 版权

**本仓库只包含代码。** 下面这些是第三方素材，版权不属于本项目，也没有随仓库分发：

- **角色头像、立绘、地图、背景图** —— 版权归网易《第五人格》所有。
- **华康POP1体W5**（`fonts/` 里用的字体，第五人格国服正文用的那款）—— 版权归
  华康字型（DynaComware），**仅供个人学习使用，商用需另行取得授权**。下载地址见
  `fonts/说明.txt`。

本项目是给同人赛事转播用的工具，与网易、华康字型均无关联。

## 协议

代码以 **GPL-3.0** 发布，全文见 [LICENSE](LICENSE)。

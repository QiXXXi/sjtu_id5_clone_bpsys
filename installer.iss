; 第五人格BP工具 安装包脚本
;
; **别直接双击编译**: 版本号和发行者是从 id5/config.py 里取出来、由 build.py 通过
; ISCC 的 /D 传进来的。直接编译会因为缺 /D 而报错(见下面那几个 #error), 这是故意
; 的 —— 总比悄悄打出个 0.0.0 版本的安装包好。
;
;   python build.py
;
; 本文件存成 **带 BOM 的 UTF-8**。Inno 6 的脚本编码是按 BOM 判的, 少了它向导里的
; 中文会变成乱码。

#ifndef AppVersion
  #error 缺 /DAppVersion —— 请用 `python build.py` 编译, 不要直接编译本文件。
#endif
#ifndef AppPublisher
  #error 缺 /DAppPublisher —— 请用 `python build.py` 编译。
#endif
#ifndef AppLicense
  #error 缺 /DAppLicense —— 请用 `python build.py` 编译。
#endif

#define AppName "第五人格BP工具"
#define AppExe "id5_clone.exe"

[Setup]
; AppId 是升级/卸载认身份用的, **生成一次之后就不要再改** —— 改了等于换了个软件,
; 老版本不会被覆盖, 而是两份并存。花括号要写两层: 一层是 Inno 的转义, 一层是这个
; GUID 自己的。
AppId={{13C11719-5C90-4072-B3A8-59E6072F8128}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments=版权协议 {#AppLicense}。本程序是自由软件, 协议全文见安装目录下的 LICENSE。
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=Copyright (C) 2026 {#AppPublisher} / {#AppLicense}

; **按用户安装**(见 PrivilegesRequired)。程序要往自己旁边写 settings.json 和
; 「检查角色更新」下回来的图, 装进 Program Files 就没权限写了 —— 而
; save_settings() 是**静默吞掉 OSError** 的, 用户只会发现设置存不住, 不会看到
; 任何报错。lowest 让 {autopf} 落到 %LOCALAPPDATA%\Programs, 全程不弹 UAC。
;
; **不要**加 PrivilegesRequiredOverridesAllowed=dialog: 那会允许用户提权装到
; Program Files, 于是上面的写入问题原样回来。
PrivilegesRequired=lowest
DefaultDirName={autopf}\id5_clone
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
; PyInstaller 出的是 64 位 exe。
ArchitecturesAllowed=x64compatible

LicenseFile=LICENSE
OutputDir=installer_out
OutputBaseFilename=id5_clone-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}

; 只有英文向导。Inno 6 **不自带** ChineseSimplified.isl(简体中文是第三方翻译,
; 要从 jrsoftware/issrc 的 Translations 目录单独下), 引用一个不存在的语言文件
; 会直接编译失败。所以: 向导按钮是英文的, 而下面凡是我们自己能定的字
; (应用名、开始菜单项、任务说明)全是中文。
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; dist\id5_clone\ 整个搬过来: exe + _internal\ + 散装素材(survivor/ hunter/
; map_square/ fonts/ bg.jpg LICENSE)。素材必须在 exe 旁边, 原因见 id5_clone.spec。
Source: "dist\id5_clone\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 程序会往这几个目录里下新图, 那些文件不是安装程序放的, 卸载器默认**不碰**它们
; —— 结果是卸载完还留着一坨几十 MB 的图片和一个存着设置的 settings.json。
;
; **逐条列目录, 不写 `Name: "{app}"`**: 用户可以在目录页里把安装路径改到任何地方
; (甚至是 D:\), 那种情况下整块删 {app} 就等于删他整个盘。这几条只删本程序自己的
; 子目录, 装到哪都只影响这几个名字。
; fonts/ 不用列 —— 它只放安装程序自己摆的字体, 卸载器清空后会把目录一起收走。
Type: filesandordirs; Name: "{app}\survivor"
Type: filesandordirs; Name: "{app}\hunter"
Type: filesandordirs; Name: "{app}\map_square"
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\sync_log.txt"

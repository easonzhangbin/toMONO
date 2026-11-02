# 从源码构建

当前源码用于 1.2 正式版（1.2.0，构建16）。目标为 Apple Silicon macOS。前端使用 SwiftUI / AppKit，后台使用 Python 和 C；不是 Python 绘制的界面。

## 环境准备

安装 Xcode，完成首次启动与许可确认，确保 `xcode-select -p` 指向所选 Xcode。源码包含 macOS 26 原生玻璃 API，因此构建需要包含这些 API 的 SDK（Xcode 26 或更新）；应用对较旧系统回退到原生材质。当前源码快照验证使用 Xcode 27.2，最低部署目标 macOS 14 未等同于最低版本真机验证。

```sh
brew install uv exiftool
./scripts/bootstrap.sh
./scripts/test.sh
```

准备脚本从 uv 下载独立 Python 3.12.13，建立 `portable/.venv`，安装锁定版本并构建 C 核。首次运行需要网络；照片转换本身离线进行。脚本不安装训练数据或模型权重。版本升级应在开发端测试、重新构建，不在用户转换过程中自动替换库。

## 完整应用

```sh
portable/.venv/bin/python macos/build_app.py --output .build/toMONO.app
open .build/toMONO.app
```

验证打包后台的独立读取与导出：

```sh
portable/.venv/bin/python scripts/smoke_app.py .build/toMONO.app
```

默认构建保留可读 Python 源码，便于调试。增加 `--release` 会用 Cython 编译项目模块，完整相应源码仍在本仓库，GPL 许可不变；这不是加密。

构建使用相对路径，不能复用另一台机器的绝对资源目录。Python 必须来自可独立嵌入的发行版；直接复制 Homebrew framework Python 的可执行文件不足以生成独立应用。ExifTool 应通过 Homebrew 安装，脚本同时收集其 Perl 库。

## 在 Xcode 中编辑界面

先完成上述完整应用构建，再打开：

```sh
open macos/toMONO.xcodeproj
```

选择 `toMONO` scheme 和 My Mac。工程资源指向仓库内 `.build/toMONO.app/Contents/Resources`。修改 SwiftUI 可直接编译；修改后台与 C 核后先重新构建完整应用。`InterfacePreviews.swift` 提供调试预览入口；Canvas 渲染可用性取决于 Xcode 环境，不以命令行构建通过替代实际 Canvas 验证。

## 命令行与独立窄带

```sh
portable/.venv/bin/python portable/tomono_cli.py input.ARW -o output.dng
portable/.venv/bin/python portable/tomono_cli.py --save-default-recipe default.json
portable/.venv/bin/python portable/tomono_cli.py red.RW2 -o red_R.dng --recipe examples/narrow-red.json
```

`examples/narrow-red.json`、`narrow-green.json`、`narrow-blue.json` 仅适用于已知相应窄带光源的拍摄。三次拍摄保持几何、曝光策略与镜头处理一致；软件不会自动拉齐亮度。NegPy 中按光源手动指定 R/G/B 输入。它降低了重建阶段混入其他 CFA 通道的机会，但不能消除滤色片带外响应、光源带宽或光学 / 电学串扰。

## GitHub 版本检查

应用启动后通过系统URLSession异步读取 `https://api.github.com/repos/easonzhangbin/toMONO/releases/latest`，比较正式版本号。此检查不阻塞引擎启动、照片解码或导出。应用菜单提供“检查更新…”，新版窗口显示GitHub Release的改进说明及官方下载入口。

无更新和自动检查失败时保持安静；手动检查显示中文结果。发布草稿、预发布版本和无效版本不作为正式升级。下载通过系统浏览器完成，应用不自动替换自身或后台库。更换LibRaw、Lensfun等组件仍须由开发者验证、编译和重新打包。

请求不附带GitHub授权令牌、照片或本机路径。GitHub会接收常规网络连接信息；该行为与离线照片处理分开说明，不将其误称为整个应用从不联网。

## 本地 DMG

```sh
portable/.venv/bin/python macos/package_dmg.py --app .build/toMONO.app --output dist/toMONO-source-build-AppleSilicon.dmg
```

默认是本地 ad-hoc 签名，不是 Developer ID 公证包或 App Store 包。当前 [Release](https://github.com/easonzhangbin/toMONO/releases/tag/v1.2.0) 提供对应版本 DMG、对应项目源码、校验文件和第三方源码材料。具体组件与固定来源见 [发布依赖清单](RELEASE_DEPENDENCIES.json)；该清单不承诺整套环境逐字节可复现。

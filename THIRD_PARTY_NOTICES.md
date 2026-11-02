# 第三方组件与资料

本项目原创源码使用 GPL-3.0-only。下列依赖没有被重新授权：安装包的上游许可、版权和传递依赖声明仍然适用。此 GitHub 源码快照不提交第三方运行环境、动态库、模型权重或原论文全文。

| 组件 | 用途 | 上游许可与来源 |
| --- | --- | --- |
| Python | 本地后台运行环境 | [PSF / Python 许可](https://docs.python.org/3/license.html) |
| NumPy | 数值数组、FFT 与统计 | [BSD 为主及附带组件声明](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| rawpy | LibRaw 的 Python 接口 | [MIT](https://github.com/letmaik/rawpy/blob/main/LICENSE)；不能据此概括其内置 LibRaw |
| LibRaw | 相机 RAW 解码 | [LGPL-2.1 / CDDL 双许可及组件声明](https://www.libraw.org/about)；以实际构建版本为准 |
| tifffile | TIFF / DNG 容器读写 | [BSD-3-Clause](https://github.com/cgohlke/tifffile) |
| imagecodecs | 图像压缩编解码 | [BSD-3-Clause 及各编解码组件原许可](https://github.com/cgohlke/imagecodecs) |
| lensfunpy | Lensfun Python 接口 | [MIT](https://github.com/letmaik/lensfunpy) |
| Lensfun 库 | 镜头校正计算 | [LGPL-3.0](https://github.com/lensfun/lensfun) |
| Lensfun 数据库 | 镜头 / 相机校正参数 | [CC-BY-SA-3.0](https://github.com/lensfun/lensfun/tree/master/data) |
| ExifTool | EXIF / XMP 读写与结构检查 | [与 Perl 相同的许可：Artistic / GPL](https://exiftool.org/) |
| Cython | 可选的后台模块编译 | [Apache-2.0](https://github.com/cython/cython) |
| setuptools | 编译构建辅助 | [MIT](https://github.com/pypa/setuptools) |
| Pillow | 开发测试中的独立 ICC / 图像检查 | [MIT-CMU / HPND 及组件声明](https://github.com/python-pillow/Pillow)；不进入转换后台 |

构建脚本从实际安装的包收集许可原文，并将 `macos/assets/licenses/` 中保存的 Lensfun、数据库、PCRE2 和 GNU 许可声明一同写入应用的 `ThirdPartyNotices.txt`。其中 PCRE2 等可能来自上游二进制依赖，不能只看顶层 Python 包的许可。

更多论文、算法与库的采用关系见 [研究出处](docs/RESEARCH.md)。引用不表示附带授权、复现成功、性能达标或厂商认可。历史研究中的学习模型未纳入当前产品路径。

## IPOL Zhang–Wu LMMSE（普通照片实验选项）

原始方向 LMMSE 方法：Lei Zhang 与 Xiaolin Wu，IEEE TIP 2005，[DOI 10.1109/TIP.2005.857260](https://doi.org/10.1109/TIP.2005.857260)。本项目使用 Pascal Getreuer 的 [IPOL 2011 参考实现 v1.1](https://www.ipol.im/pub/art/2011/g_zwld/)（DOI 10.5201/ipol.2011.g_zwld）。

`portable/src/lmmse/` 中保留的官方文件按字节原样保存；归档 SHA-256 为 `1c401a9e4473e90e1205d821b89264171a3f68ae5a27c0855098485a7e71de4d`。实际文件的 BSD-2-Clause 许可与版权见 [原始许可](portable/src/lmmse/bsd-license.txt)，副本随应用组件声明收集。C ABI、分块、实测采样恢复与单色响应包装属于本项目。论文存档文本的许可与代码许可分别记录。

LMMSE 借助所有 CFA 颜色估算缺失采样，只用于普通绿色响应 / RGB 混合；严格窄带纯通道不能选用。局部检查仅提示便于观察的区域，没有使用尚未通过验证的自动混合算法。

Release 随测试 DMG 提供对应项目源码和第三方源码材料，包括 LibRaw、Lensfun 及数据库、GLib、gettext/libintl、构建依赖、接口封装与实际 ExifTool Perl 源码。固定版本、上游来源和 SHA-256 见 [发布依赖清单](docs/RELEASE_DEPENDENCIES.json)，相关归档保留各自许可。rawpy 轮子未启用 GPL demosaic packs。其他运行时的许可和组件声明保留在应用内；不把这些材料称为整套环境逐字节可复现的证明。

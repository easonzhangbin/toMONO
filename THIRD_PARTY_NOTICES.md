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

公开分发自己构建的二进制时，请同时提供精确对应的项目源码与构建材料，并履行各上游组件的源码提供等要求。本仓库第一次发布为源码发布，不将本地依赖集合冒充完整的第三方相应源码包。

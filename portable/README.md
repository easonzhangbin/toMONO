# 转换后台

当前是1.1开发源码；最新公开安装包仍为Beta 8.1。使用方式与完整构建步骤见 [根目录 README](../README.md) 和 [构建说明](../docs/BUILD.md)。

- `recipe.py`：版本化参数、校验与旧预设迁移。
- `conversion_service.py`：预览 / 导出共用管线。
- `raw_input.py`：LibRaw 读取、CFA 与电平解释。
- `detail_reconstruction.py` / `src/detail_native.c`：C01 / D11 / 默认D10。
- `lmmse_reconstruction.py` / `src/lmmse/`：普通Bayer专用的IPOL Zhang–Wu LMMSE实验选项，跨颜色估算，不用于独立窄带。
- `preview_inspection.py`：在已解码采样中选出建议检查区域；仅供放大镜观察，不自动修正RAW。
- `channel_response.py` / `pure_narrowband.py`：响应混合与严格单色采样路径。
- `dng_writer.py` / `display_render.py`：DNG、元数据与显示外观。

源码和本地编译产物分开；`build/` 与 `.venv/` 不提交 Git。

LMMSE原论文：Zhang与Wu，IEEE TIP 2005，[DOI 10.1109/TIP.2005.857260](https://doi.org/10.1109/TIP.2005.857260)；实际参考实现：Getreuer，IPOL 2011，[DOI 10.5201/ipol.2011.g_zwld](https://doi.org/10.5201/ipol.2011.g_zwld)。原C源码及BSD-2-Clause许可在 `src/lmmse/` 保留，论文文本与代码许可分别登记。

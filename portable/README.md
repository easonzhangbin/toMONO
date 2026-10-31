# 转换后台

当前是 Beta 8 源码快照。使用方式与完整构建步骤见 [根目录 README](../README.md) 和 [构建说明](../docs/BUILD.md)。

- `recipe.py`：版本化参数、校验与旧预设迁移。
- `conversion_service.py`：预览 / 导出共用管线。
- `raw_input.py`：LibRaw 读取、CFA 与电平解释。
- `detail_reconstruction.py` / `src/detail_native.c`：C01 / D11 / D10。
- `channel_response.py` / `pure_narrowband.py`：响应混合与严格单色采样路径。
- `dng_writer.py` / `display_render.py`：DNG、元数据与显示外观。

源码和本地编译产物分开；`build/` 与 `.venv/` 不提交 Git。

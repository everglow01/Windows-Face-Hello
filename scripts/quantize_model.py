"""把 InsightFace 识别模型 w600k_r50 转成 FP16,缩小一半体积、加快冷启动磁盘读。

为什么 FP16:174MB 的 `w600k_r50` 是冷启动磁盘 I/O 的大头(见 detector.py 的 `[计时]`)。
FP16 文件减半(~174MB→~87MB),冷读随之减半;`keep_io_types=True` 保留 fp32 的输入/输出,
InsightFace 的前处理与 `normed_embedding` 输出**无需改动**,模型内部以 fp16 计算。

精度:FP16 对 ArcFace embedding 漂移极小(同脸余弦 >0.999),理论上旧模板仍可匹配;
但稳妥起见,换后建议**重录入 + 重标定阈值**(scripts.liveness_tune / 设置页)。

CPU 推理速度:onnxruntime CPU 不原生加速 fp16(会插 Cast),单帧可能略慢——但推理不是瓶颈、
且已被启动期预热挡掉。这里只图缩小体积 / 加快加载,不图推理提速。

用法(onnxconverter-common 仅转换时需要,不进运行时依赖,故用 --with 临时装):
    uv run --with onnxconverter-common python scripts/quantize_model.py
幂等:已是 FP16 则跳过(CI 缓存复跑安全)。原始 fp32 会先备份到同目录 .fp32.bak。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import onnx
from onnx import TensorProto
from onnxconverter_common import float16

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "buffalo_l" / "w600k_r50.onnx"
BACKUP = MODEL.with_suffix(".fp32.bak")


def _is_fp16(model) -> bool:
    return any(init.data_type == TensorProto.FLOAT16 for init in model.graph.initializer)


def main() -> int:
    if not MODEL.exists():
        print(f"[skip] 模型不存在:{MODEL}(先跑 offline_check 下载 buffalo_l)")
        return 0
    before = MODEL.stat().st_size / 1e6
    model = onnx.load(str(MODEL))
    if _is_fp16(model):
        print(f"[skip] 已是 FP16:{MODEL.name}({before:.0f}MB)")
        return 0
    # CI 里不留备份:166MB 的 .bak 会撑大 models 缓存、也没回退需求(GitHub Actions 自动设 CI=true)。
    if not os.environ.get("CI") and not BACKUP.exists():  # 本地首次转换才留 fp32 原件,便于回退/重测精度
        shutil.copy2(MODEL, BACKUP)
        print(f"[备份] fp32 原件 → {BACKUP.name}")
    print(f"[转换] {MODEL.name} FP32 {before:.0f}MB → FP16 …")
    model16 = float16.convert_float_to_float16(model, keep_io_types=True)
    onnx.checker.check_model(model16)
    tmp = MODEL.with_suffix(".fp16.tmp")
    try:
        onnx.save(model16, str(tmp))
        os.replace(tmp, MODEL)
    finally:
        if tmp.exists():
            tmp.unlink()
    after = MODEL.stat().st_size / 1e6
    print(f"[完成] {MODEL.name} {before:.0f}MB → {after:.0f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

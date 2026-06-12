"""活体阈值标定:实时显示 EAR(眨眼)和 yaw(转头),退出时给阈值建议。

运行:  uv run python -m scripts.liveness_tune
步骤:正对摄像头 → 正常睁眼几秒 → 用力眨眼几次 → 慢慢向左、向右转头 → 按 q 退出。
退出后会打印 EAR/yaw 的统计与建议阈值,把它发我即可定参。
"""
from __future__ import annotations

import cv2
import numpy as np

from face_hello.camera import Camera
from face_hello.liveness import FaceMeshTracker
from face_hello.store import FaceStore

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def main() -> None:
    tracker = FaceMeshTracker()
    ears: list[float] = []
    yaws: list[float] = []
    idx = int(FaceStore().load().get_settings().get("camera_index", 0))  # 与解锁用同一台摄像头
    try:
        with Camera(idx) as cam:
            while True:
                frame = cam.read()
                m = tracker.process(frame)
                if m is not None:
                    ears.append(m.ear)
                    yaws.append(m.yaw_deg)
                    info = f"EAR={m.ear:.3f}  yaw={m.yaw_deg:+.1f}"
                    color = (0, 255, 0)
                else:
                    info = "no face"
                    color = (0, 0, 255)
                cv2.putText(frame, info, (10, 34), _FONT, 0.9, color, 2)
                cv2.putText(frame, "blink hard, then turn L/R. press q",
                            (10, 466), _FONT, 0.6, (0, 200, 255), 2)
                cv2.imshow("liveness tune", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        tracker.close()
        cv2.destroyAllWindows()

    if not ears:
        print("没采到人脸数据。")
        return

    a = np.array(ears)
    p5, p50, p95 = np.percentile(a, [5, 50, 95])
    suggested_ear = round(float((p50 + p5) / 2), 3)
    max_abs_yaw = float(np.max(np.abs(yaws)))
    suggested_yaw = round(0.6 * max_abs_yaw, 1)

    print("\n===== 标定汇总(发我这段)=====")
    print(f"EAR  : min={a.min():.3f}  p5={p5:.3f}  中位={p50:.3f}  p95={p95:.3f}")
    print(f"yaw  : 范围 [{min(yaws):+.1f}, {max(yaws):+.1f}]  最大幅度={max_abs_yaw:.1f}")
    print(f"建议  ear_threshold≈{suggested_ear}   yaw_threshold_deg≈{suggested_yaw}")
    print("(睁眼应接近 p95/中位,眨眼瞬间应接近 min;阈值取两者之间)")


if __name__ == "__main__":
    main()

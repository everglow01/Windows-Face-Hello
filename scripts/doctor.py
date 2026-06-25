"""实机环境自检:在目标机/安装机上一键确认部署是否真能跑。

与 offline_check 的分工:offline_check 是 CI 守门(纯逻辑 + 模型加载,不碰摄像头/服务);
doctor 是面向**真实机器**的健康诊断,额外查那些 CI 查不了的实机依赖——摄像头能否取帧、
认证服务管道是否在线。排查「装好了但刷脸不工作」时先跑它。

运行:  uv run python scripts/doctor.py
       服务管道自检需**管理员终端**(管道 ACL 仅放行 SYSTEM+Administrators);
       非管理员跑也行,但管道那项会因拒绝访问而标未通过。
退出码:全部通过 0;有任一项失败 1(便于装脚本/巡检判定)。
"""
from __future__ import annotations

import json
import time

OK, WARN, FAIL = "[ok]  ", "[警告]", "[失败]"


def _print(mark: str, msg: str) -> None:
    print(f"{mark} {msg}", flush=True)


def check_models() -> bool:
    """模型文件是否齐 + 能否真加载(缺文件只告警、不触发数百 MB 下载)。"""
    from face_hello import config

    items = [
        ("InsightFace 检测 det_10g", config.MODELS_DIR / "buffalo_l" / "det_10g.onnx"),
        ("InsightFace 识别 w600k_r50", config.MODELS_DIR / "buffalo_l" / "w600k_r50.onnx"),
        ("活体 FaceLandmarker", config.FACE_LANDMARKER),
    ]
    missing = []
    for name, path in items:
        if path.exists():
            _print(OK, f"模型在位:{name}（{path.stat().st_size / 1e6:.0f}MB）")
        else:
            missing.append(name)
            _print(FAIL, f"模型缺失:{name} → {path}")
    if missing:
        _print(WARN, "模型不全,跳过加载验证（首次运行 offline_check 会自动下载）")
        return False

    t0 = time.perf_counter()
    try:
        from face_hello.detector import FaceDetector
        from face_hello.liveness import FaceMeshTracker
        import numpy as np

        FaceDetector().load()
        tr = FaceMeshTracker()
        tr.process(np.zeros((480, 640, 3), dtype=np.uint8))
        import threading
        threading.Thread(target=tr.close, daemon=True).start()  # close() 阻塞~40s,丢后台
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"模型加载失败:{e}")
        return False
    _print(OK, f"模型加载成功（detector + 活体,耗时 {time.perf_counter() - t0:.1f}s）")

    # 反欺骗是可选项:缺文件 fail-open 属正常,只报状态不计失败
    from face_hello.antispoof import get_antispoof

    if get_antispoof() is not None:
        _print(OK, "反欺骗模型已加载")
    else:
        _print(WARN, "反欺骗未启用（模型文件不全,认证时 fail-open 跳过）")
    return True


def check_camera() -> bool:
    """按 settings 的 camera_index 打开摄像头并取一帧（短超时,不长时间阻塞）。"""
    from face_hello.camera import Camera
    from face_hello.store import FaceStore

    try:
        idx = int(FaceStore().load().get_settings().get("camera_index", 0))
    except Exception:  # noqa: BLE001 人脸库读不开不影响摄像头自检,退回默认
        idx = 0

    cam = Camera(idx)
    try:
        cam.open(timeout_s=8.0)
        frame = cam.read()
        h, w = frame.shape[:2]
        _print(OK, f"摄像头可用:index={idx},取到一帧 {w}x{h}")
        return True
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"摄像头不可用:index={idx} — {e}")
        return False
    finally:
        cam.release()


def check_pipe() -> bool:
    """给认证服务管道发 ping,确认 LocalSystem 服务在线。"""
    import pywintypes
    import win32file
    import win32pipe

    from face_hello import config

    try:
        handle = win32file.CreateFile(
            config.PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
    except pywintypes.error as e:
        # 区分两类常见失败,给出可操作的提示:
        #   2  ERROR_FILE_NOT_FOUND  → 管道不存在,服务多半没起
        #   5  ERROR_ACCESS_DENIED   → 管道在,但当前账户无权访问(ACL 限 SYSTEM+Administrators)
        if e.winerror == 5:
            _print(WARN, "管道存在但拒绝访问:请用管理员终端跑本自检（管道 ACL 仅放行 SYSTEM+Administrators）")
        elif e.winerror == 2:
            _print(FAIL, "管道不存在:认证服务多半没启动（sc.exe start FaceHello 或在管理台启动）")
        else:
            _print(FAIL, f"管道连接失败:{config.PIPE_NAME} — {e}")
        return False
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"管道连接失败:{config.PIPE_NAME} — {e}")
        return False
    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        win32file.WriteFile(handle, json.dumps({"cmd": "ping"}).encode("utf-8"))
        resp = json.loads(win32file.ReadFile(handle, 65536)[1].decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        _print(FAIL, f"管道 ping 失败:{e}")
        return False
    finally:
        win32file.CloseHandle(handle)

    if resp.get("ok"):
        users = resp.get("users", [])
        _print(OK, f"服务在线:ping 通,已录入用户 {users or '（无）'}")
        return True
    _print(FAIL, f"服务回应异常:{resp}")
    return False


def main() -> int:
    print("=== FaceHello 实机自检（doctor）===\n", flush=True)
    import ctypes

    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:  # noqa: BLE001
        is_admin = False
    if not is_admin:
        _print(WARN, "当前非管理员终端:服务管道一项会因 ACL 拒绝访问,建议用管理员重跑以完整自检\n")
    results = {
        "模型": check_models(),
        "摄像头": check_camera(),
        "服务管道": check_pipe(),
    }
    print("\n--- 汇总 ---", flush=True)
    for name, ok in results.items():
        _print(OK if ok else FAIL, name)
    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print(f"\n[FAIL] 未通过:{', '.join(failed)}", flush=True)
        return 1
    print("\n[PASS] 实机自检全部通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Session 0 摄像头探针 —— 整个 C 档分发方案的一票否决验证。

问题:把人脸服务做成 LocalSystem Windows 服务后,它跑在 session 0;而锁屏/
登录界面(LogonUI)在交互会话的安全桌面上。一个 session 0 / SYSTEM 进程在那种
状态下到底能不能用 OpenCV 打开摄像头、读到帧?没有保证(DSHOW 常在 session 0
枚举不到设备;MSMF 可能行)。这个脚本就是去实测它。

只依赖 opencv-python + numpy,不加载任何模型。两种后端都试(MSMF / DSHOW)。

怎么跑(都在 VM 里,先把摄像头直通给 VM:菜单 → 可移动设备 → 连接 webcam):

  1) 快速预检(已登录,SYSTEM/session 0,摄像头无争用):
        psexec -s <python> scripts\cam_session0_probe.py
     —— 这步过不了就直接否决;过了也只是必要非充分。

  2) 决定性测试(锁屏状态下,安全桌面争用):用计划任务每分钟跑一次,
     然后 Win+L 锁屏等 ~2 分钟,再解锁看日志:
        schtasks /create /tn FaceCamProbe /ru SYSTEM /rl HIGHEST /f ^
                 /sc minute /mo 1 /tr "<python> <绝对路径>\cam_session0_probe.py"
        (锁屏、等待、解锁)
        schtasks /delete /tn FaceCamProbe /f

输出落到 C:\FaceHelloProbe\(SYSTEM 可写):每次一行日志 + 成功则一张 JPG。
看 probe.log 里锁屏时间段内那几行 MSMF/DSHOW 是不是 True。
"""
import ctypes
import datetime
import os

import cv2

OUT = r"C:\FaceHelloProbe"


def session_id() -> int:
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid))
    return sid.value


def log(msg: str) -> None:
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    with open(os.path.join(OUT, "probe.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def try_backend(name: str, flag: int) -> bool:
    cap = cv2.VideoCapture(0, flag)
    if not cap.isOpened():
        log(f"[{name}] open FAILED")
        return False
    frame = None
    ok = False
    for _ in range(10):  # 预热几帧,有些摄像头首帧是黑的
        ret, frame = cap.read()
        if ret and frame is not None:
            ok = True
            break
    cap.release()
    if ok:
        ts = datetime.datetime.now().strftime("%H%M%S")
        path = os.path.join(OUT, f"{name}_{ts}.jpg")
        enc_ok, buf = cv2.imencode(".jpg", frame)
        if enc_ok:
            buf.tofile(path)  # 中文/任意路径安全
        log(f"[{name}] OK  frame={frame.shape}  saved={path}")
    else:
        log(f"[{name}] opened but NO FRAME")
    return ok


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    log(f"--- start  session={session_id()}  user={os.environ.get('USERNAME', '?')}")
    msmf = try_backend("MSMF", cv2.CAP_MSMF)
    dshow = try_backend("DSHOW", cv2.CAP_DSHOW)
    log(f"--- end    MSMF={msmf}  DSHOW={dshow}")


if __name__ == "__main__":
    main()

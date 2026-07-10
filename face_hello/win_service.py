"""FaceHello 认证服务的 Windows 服务封装(LocalSystem,开机自启)。

为什么要做成服务:冷启动登录时没有用户会话,只有常驻的 SYSTEM 服务能在
登录/锁屏界面开摄像头、读 LSA、走命名管道(session 0 摄像头可用已在 VM 实测)。
服务一直常驻,锁定/睡眠唤醒都不退出,天然满足"每次启动/锁定/睡眠后可用"。

进程入口是仓库根的 winservice_main.py(它负责把根目录加进 sys.path,因为
package=false、face_hello 没装进 venv)。本模块只定义服务类。

装 / 起 / 停 / 删(需管理员;<venv> 是 .venv\Scripts\python.exe):
  <venv> winservice_main.py install --startup auto
  <venv> winservice_main.py start | stop | remove
管理台「服务与凭据」页就是一键调这些。
"""
from __future__ import annotations

import logging
import os
import sys

import win32service
import win32serviceutil

from . import config
from .service import serve, setup_logging


class FaceHelloService(win32serviceutil.ServiceFramework):
    _svc_name_ = config.SERVICE_NAME
    _svc_display_name_ = "FaceHello Face Unlock"
    _svc_description_ = (
        "RGB camera face-unlock auth service (named pipe for the credential provider)."
    )

    # 用 venv 的 python 直接跑引导脚本作为服务 ImagePath,而非默认的 PythonService.exe
    # ——后者在 SCM 上下文 import 不到本项目(face_hello 没装进 venv)。
    _exe_name_ = sys.executable
    _exe_args_ = '-u "{}"'.format(config.ROOT / "winservice_main.py")

    def __init__(self, args):
        super().__init__(args)
        self._running = True

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._running = False
        _poke_pipe()  # 解开阻塞在 ConnectNamedPipe 的 accept,让主循环立刻退出

    def SvcDoRun(self) -> None:
        config.ensure_dirs()
        # matplotlib(insightface 的传递依赖)在 SYSTEM 上下文首次建字体缓存易卡死/崩溃。
        # 固定到可写缓存目录 + 非交互后端绕开它;须在其被导入前设好(serve 里才会触发导入)。
        os.environ.setdefault("MPLBACKEND", "Agg")
        os.environ.setdefault("MPLCONFIGDIR", str(config.DATA_DIR / "mpl"))
        # 服务无控制台:结构化日志落 data/service.log(滚动),并把 stdout/stderr 转进 logger。
        setup_logging(console=False, capture_streams=True)
        try:
            serve(should_continue=lambda: self._running)
        except BaseException:  # noqa: BLE001 把真 traceback 落盘(pywin32 抓不到)
            logging.getLogger("facehello").exception("服务异常退出")
            raise


def _poke_pipe() -> None:
    """以客户端身份连一下管道,让阻塞的 ConnectNamedPipe 立即返回,从而退出循环。"""
    import win32file

    try:
        h = win32file.CreateFile(
            config.PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
        win32file.CloseHandle(h)
    except Exception:  # noqa: BLE001 没连上也无妨,下一轮 should_continue() 自然退出
        pass

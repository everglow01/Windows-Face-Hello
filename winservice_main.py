"""Windows 服务进程入口:由 SCM 用 venv 的 python 直接拉起。

为什么单独放仓库根:本项目 `package = false`,face_hello 没装进 venv,只能靠
仓库根在 sys.path 上才 import 得到。SCM 启动的进程 cwd 在 system32、也没有
PYTHONPATH,所以这里先把本文件所在目录(=仓库根)插进 sys.path,再导入包。

它既是被 SCM 拉起的服务宿主(无参数 → 进 SCM 调度),也兼作命令行装/起/停/删入口。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import servicemanager  # noqa: E402
import win32serviceutil  # noqa: E402

from face_hello.win_service import FaceHelloService  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 无参数 = SCM 拉起的服务进程
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(FaceHelloService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # 带参数 = 命令行 install / start / stop / remove
        win32serviceutil.HandleCommandLine(FaceHelloService)

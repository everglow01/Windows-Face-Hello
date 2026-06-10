"""卸载清理:清除 LSA 登录密码 + 人脸库(完全干净卸载)。

由安装器的 [UninstallRun] 在删文件前用便携 python 调用:
    {app}\python\python.exe uninstall_cleanup.py

卸载这一刻 {app}\.installed 标记还在,config 走安装态,FACE_STORE 指向
ProgramData\data\faces.dat。枚举人脸库里所有 profile 名(== LSA 键里的用户名),
逐个删其 LSA secret,再删人脸库文件。任何一步失败都不阻断卸载(尽力而为),
否则卸载会卡住、留下残留。

权限:卸载器(unins000.exe)以管理员运行,clear_password 需管理员、读机器范围
DPAPI 人脸库管理员可解,均满足。
"""
import os
import sys

# 便携布局下 face_hello 没装进 site-packages,靠仓库根在 sys.path 才 import 得到
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from face_hello import config, cred_vault  # noqa: E402
from face_hello.store import FaceStore  # noqa: E402


def main() -> int:
    names: set[str] = set()
    try:
        names = {p.name for p in FaceStore().load().list_profiles()}
    except Exception as e:  # noqa: BLE001 读不到也继续清当前用户
        print(f"读人脸库失败(忽略): {e}")
    try:
        names.add(cred_vault.current_user())  # 兜底:当前用户也清一遍
    except Exception:  # noqa: BLE001
        pass

    for name in names:
        try:
            cred_vault.clear_password(name)
            print(f"已清除 LSA 密码: {name}")
        except Exception as e:  # noqa: BLE001
            print(f"清除 LSA 失败 {name}(忽略): {e}")

    try:
        if config.FACE_STORE.exists():
            config.FACE_STORE.unlink()
            print(f"已删除人脸库: {config.FACE_STORE}")
    except Exception as e:  # noqa: BLE001
        print(f"删人脸库失败(忽略): {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

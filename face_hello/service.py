"""认证服务:命名管道服务端,供 Credential Provider 请求刷脸认证。

请求/响应都是单条 JSON(消息模式管道):
  请求  {"cmd": "ping"}            -> {"ok": true, "ready": true, "users": [...]}
  请求  {"cmd": "authenticate"}    -> {"ok": true, "user": "owen", "similarity": 0.6}
                                   或 {"ok": false, "reason": "..."}

设计:密码不经过本服务——服务只回 {ok, user},由 CP 自己读 LSA Secret 提交。
当前为控制台常驻进程(开发/自测用);正式部署再封成 Windows 服务(阶段 5-4)。
ACL 暂用默认(创建者 + 管理员 + SYSTEM 可访问),限 SYSTEM 的加固留到阶段 5-4。

运行:  uv run python -m face_hello.service
"""
from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import pywintypes
import win32con
import win32file
import win32pipe
import win32security

from . import config
from .auth import AuthResult, authenticate_blocking
from .detector import FaceDetector
from .i18n import save_lang_mirror, t
from .store import FaceStore

_BUF = 65536
# CreateNamedPipe openMode 标志:同名实例已存在则创建失败——用于抢注检测。
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000

_log = logging.getLogger("facehello")


class _StreamToLogger:
    """把 sys.stdout/stderr 的写入按行转进 logger:服务无控制台,用它收原生库 print
    与未捕获 traceback(纯 C 层 stderr 噪声可能仍不落盘,但那只是启动横幅,非审计内容)。"""

    def __init__(self, level: int) -> None:
        self._level = level
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                _log.log(self._level, line.rstrip())
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            _log.log(self._level, self._buf.rstrip())
        self._buf = ""


def setup_logging(console: bool = False, capture_streams: bool = False) -> None:
    """配置 facehello 日志:滚动文件(service.log,约 1MB×3)+ 时间戳/级别。

    console=True 额外挂控制台 handler(开发态前台运行);capture_streams=True 时把
    sys.stdout/stderr 转进 logger(服务态无控制台,收原生噪声与 traceback)。
    """
    config.ensure_dirs()
    _log.setLevel(logging.INFO)
    if not _log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        fh = RotatingFileHandler(
            config.DATA_DIR / "service.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        _log.addHandler(fh)
        if console:  # 在替换流之前绑定真实 stdout,避免 capture 时自指造成递归
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            _log.addHandler(sh)
    if capture_streams:
        sys.stdout = _StreamToLogger(logging.INFO)
        sys.stderr = _StreamToLogger(logging.ERROR)


_PIPE_SA = None


def _pipe_security():
    """管道安全属性:DACL 只放行 SYSTEM 与 Administrators,挡本地非特权进程冒充 CP 调认证。"""
    global _PIPE_SA
    if _PIPE_SA is None:
        sys_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)
        adm_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL, sys_sid)
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_ALL, adm_sid)
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorOwner(sys_sid, False)
        sd.SetSecurityDescriptorDacl(True, dacl, False)
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        _PIPE_SA = sa
    return _PIPE_SA


class _AuthRunner:
    """后台跑一次认证,主循环用 auth_poll 取实时活体提示和最终结果。

    供 milestone d 的异步 CP:CP 选中磁贴 → auth_start(立即返回)→ 反复 auth_poll
    刷新锁屏提示文字,直到 done。摄像头由这个后台线程独占,主管道循环照常应答。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._instruction = ""
        self._done = False
        self._result: AuthResult | None = None
        self._fails = 0            # 连续生物特征失败次数
        self._locked_until = 0.0   # time.monotonic();在此之前拒绝认证

    @property
    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, detector: FaceDetector, store: FaceStore) -> None:
        settings = store.get_settings()
        lang = settings.get("language", "zh")
        max_fails = settings.get("lockout_max_fails", 5)
        with self._lock:
            if self._running:
                return  # 已有一次在跑,忽略重复 start
            now = time.monotonic()
            if max_fails > 0 and now < self._locked_until:
                # 锁定中:不开摄像头,直接回锁定结果,让锁屏提示走密码。
                remaining = int(math.ceil(self._locked_until - now))
                self._instruction = t("locked", lang, secs=remaining)
                self._result = AuthResult(False, t("locked", lang, secs=remaining))
                self._done = True
                _log.warning("锁定中,拒绝认证请求(剩余 %ds)", remaining)
                return
            self._instruction = t("starting", lang)
            self._done = False
            self._result = None
            self._thread = threading.Thread(
                target=self._run, args=(detector, store), daemon=True
            )
            self._thread.start()

    def _run(self, detector: FaceDetector, store: FaceStore) -> None:
        def on_instr(s: str) -> None:
            with self._lock:
                self._instruction = s

        try:
            store.load()
            if store.is_empty():
                result = AuthResult(False, t("no_enrolled", store.get_settings().get("language", "zh")))
            else:
                result = authenticate_blocking(detector, store, on_instruction=on_instr)
        except Exception as e:  # noqa: BLE001
            result = AuthResult(False, f"认证异常: {e}")
            _log.exception("认证线程异常")
        settings = store.get_settings()
        max_fails = settings.get("lockout_max_fails", 5)
        lock_secs = settings.get("lockout_seconds", 30)
        with self._lock:
            self._result = result
            self._done = True
            # 只对真生物特征拒绝计数;成功清零,达阈值则进入冷却。
            if result.success:
                self._fails = 0
            elif result.biometric and max_fails > 0:
                self._fails += 1
                if self._fails >= max_fails:
                    self._locked_until = time.monotonic() + lock_secs
                    self._fails = 0
                    _log.warning("连续生物识别失败达 %d 次,锁定 %ds", max_fails, lock_secs)
        if result.success:
            _log.info("认证通过 user=%s similarity=%.4f", result.name, result.similarity)
        else:
            _log.info("认证拒绝: %s", result.reason)

    def snapshot(self) -> dict:
        with self._lock:
            resp = {"ok": True, "done": self._done, "instruction": self._instruction}
            if self._done and self._result is not None:
                r = self._result
                resp["success"] = r.success
                if r.success:
                    resp["user"] = r.name
                    resp["similarity"] = round(r.similarity, 4)
                else:
                    resp["reason"] = r.reason
            return resp


_runner = _AuthRunner()


def _warm_liveness() -> None:
    """预热 MediaPipe,首次 authenticate 不卡。"""
    try:
        import numpy as np

        from .liveness import FaceMeshTracker

        tr = FaceMeshTracker()
        tr.process(np.zeros((480, 640, 3), dtype=np.uint8))
        # close() 阻塞约 40s(同 auth._finish),丢后台守护线程,别卡服务启动/建管道
        threading.Thread(target=tr.close, daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def _warm_antispoof() -> None:
    """预热反欺骗模型,首次认证不卡。模型缺失走 fail-open,静默忽略。"""
    try:
        from .antispoof import get_antispoof

        m = get_antispoof()
        if m is not None:
            m.load()
    except Exception:  # noqa: BLE001
        pass


def _handle(req: dict, detector: FaceDetector, store: FaceStore) -> dict:
    cmd = req.get("cmd")
    if cmd == "ping":
        return {"ok": True, "ready": True, "users": [p.name for p in store.list_profiles()]}
    if cmd == "authenticate":  # 同步认证(开发/自测路径,不走失败锁定计数)
        store.load()  # 取最新人脸库
        if store.is_empty():
            _log.info("认证拒绝:尚未录入任何人脸")
            return {"ok": False, "reason": t("no_enrolled", store.get_settings().get("language", "zh"))}
        result = authenticate_blocking(
            detector, store, on_instruction=lambda s: _log.info("活体提示: %s", s)
        )
        if result.success:
            _log.info("认证通过 user=%s similarity=%.4f", result.name, result.similarity)
            return {"ok": True, "user": result.name, "similarity": round(result.similarity, 4)}
        _log.info("认证拒绝: %s", result.reason)
        return {"ok": False, "reason": result.reason}
    if cmd == "auth_start":  # milestone d:异步认证,立即返回,随后用 auth_poll 取进度
        _runner.start(detector, store)
        return {"ok": True, "done": False}
    if cmd == "auth_poll":
        return _runner.snapshot()
    return {"ok": False, "reason": f"未知命令: {cmd}"}


def _serve_one(detector: FaceDetector, store: FaceStore) -> None:
    try:
        pipe = win32pipe.CreateNamedPipe(
            config.PIPE_NAME,
            win32pipe.PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            1, _BUF, _BUF, 0, _pipe_security(),
        )
    except pywintypes.error as e:
        # FIRST_PIPE_INSTANCE 下创建失败多半是管道名被占用/抢注:告警 + 退避,绝不静默。
        _log.error("CreateNamedPipe 失败(管道名可能被占用/抢注): %s", e)
        time.sleep(1.0)
        return
    try:
        win32pipe.ConnectNamedPipe(pipe, None)
        try:
            raw = win32file.ReadFile(pipe, _BUF)[1]
            resp = _handle(json.loads(raw.decode("utf-8")), detector, store)
        except Exception as e:  # noqa: BLE001
            resp = {"ok": False, "reason": f"请求处理失败: {e}"}
        try:
            # ensure_ascii=False:中文 reason 直接发 UTF-8,CP 端按 UTF-8 解就不乱码
            win32file.WriteFile(pipe, json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            win32file.FlushFileBuffers(pipe)
        except Exception:  # noqa: BLE001 客户端可能已断开
            pass
        win32pipe.DisconnectNamedPipe(pipe)
    finally:
        win32file.CloseHandle(pipe)


def serve(should_continue=None) -> None:
    """常驻服务主循环。

    should_continue:返回 False 时退出循环(供 Windows 服务的 SvcStop 用);
    默认 None = 永远运行(控制台模式靠 Ctrl+C)。
    """
    if not _log.handlers:  # 直接调 serve() 时兜底配置(前台)
        setup_logging(console=True)
    if should_continue is None:
        should_continue = lambda: True  # noqa: E731
    _log.info("FaceHello 服务:加载模型中…")
    _t = time.perf_counter()
    detector = FaceDetector()
    detector.load()
    _t_det = time.perf_counter()
    _warm_liveness()
    _t_liv = time.perf_counter()
    _warm_antispoof()
    _t_anti = time.perf_counter()
    _log.info(
        "[计时] 预热合计 %.2fs(detector %.2fs / 活体 %.2fs / 反欺骗 %.2fs)",
        _t_anti - _t, _t_det - _t, _t_liv - _t_det, _t_anti - _t_liv,
    )
    store = FaceStore().load()
    # 以 SYSTEM 身份把语言镜像同步成 settings 的值,保证重启后锁屏磁贴语言与控制台一致
    # (控制台非管理员时可能写不进 ProgramData,这里兜底)。
    save_lang_mirror(store.get_settings().get("language", "zh"))
    _log.info("FaceHello 服务:就绪,监听 %s", config.PIPE_NAME)
    try:
        while should_continue():
            _serve_one(detector, store)
    except KeyboardInterrupt:
        _log.info("FaceHello 服务:已停止")


if __name__ == "__main__":
    setup_logging(console=True)
    serve()

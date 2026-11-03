"""摄像头采集封装(OpenCV)。"""
from __future__ import annotations

import time
import threading
from urllib.parse import quote, urlsplit, urlunsplit

import cv2

from . import platform_backend

_capture_lock = threading.Lock()

CameraSource = int | str

# FFmpeg 支持的网络串流协议。file:// 等本地协议一律拒绝,LocalSystem 服务不该按设置去读任意文件。
STREAM_SCHEMES = ("http", "https", "rtsp", "rtsps", "rtmp")


class CameraSourceError(ValueError):
    """`camera_url` 已填写但无法解析。

    消息是固定文案,**绝不**包含原始 URL:URL 可能内嵌账号密码或 token,而这个异常会进
    service.log、认证失败响应和诊断报告。
    """

    def __init__(self) -> None:
        super().__init__(
            "串流 URL 格式无效(需以 " + "/".join(STREAM_SCHEMES) + ":// 开头并包含主机名)"
        )


def camera_source(settings: dict) -> CameraSource:
    """settings 里填了 `camera_url` 就用网络串流,否则用 `camera_index` 的本机摄像头。

    填了 `camera_url_username` 时,把账号密码百分号编码后拼进 URL(密码含 @ : / # 等也安全);
    URL 本身已带 user:pass@ 则原样使用。URL 无法解析时抛 `CameraSourceError`(不含 URL),
    绝不静默回退到本机摄像头。
    """
    url = str(settings.get("camera_url", "") or "").strip()
    if not url:
        return int(settings.get("camera_index", 0))
    parts = _parse_stream_url(url)
    user = str(settings.get("camera_url_username", "") or "")
    if not user or "@" in parts.netloc:
        return url
    userinfo = quote(user, safe="")
    password = str(settings.get("camera_url_password", "") or "")
    if password:
        userinfo += ":" + quote(password, safe="")
    return urlunsplit(parts._replace(netloc=f"{userinfo}@{parts.netloc}"))


def _parse_stream_url(url: str):
    """解析并校验串流 URL。urlsplit / .port / .hostname 的 ValueError 消息会带出原始地址
    (含密码),所以只在 except 外抛不含 URL 的 `CameraSourceError`,连异常链也不留。"""
    try:
        parts = urlsplit(url)
        valid = (parts.scheme.lower() in STREAM_SCHEMES and bool(parts.hostname)
                 and (parts.port is None or parts.port > 0))
    except ValueError:
        valid = False
    if not valid:
        raise CameraSourceError()
    return parts


def is_stream(source: CameraSource) -> bool:
    return isinstance(source, str)


def mask_url(url: str) -> str:
    """遮蔽 URL 里可能的凭据:userinfo、查询参数值与 fragment。

    纯字符串处理、永不抛错(格式错误的 URL 也要能安全显示)。未编码的密码可能含 @ / ? #,
    故 userinfo 取到**最后一个** @ 为止,宁可多遮也不漏。
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        scheme, rest = "", url
    if "@" in rest:
        rest = "***@" + rest.rsplit("@", 1)[1]
    rest, hash_sep, _fragment = rest.partition("#")
    path, query_sep, query = rest.partition("?")
    if query_sep:
        params = (p.split("=", 1)[0] + "=***" if "=" in p else "***"
                  for p in query.split("&") if p)
        path += "?" + "&".join(params)
    if hash_sep:
        path += "#***"
    return f"{scheme}{sep}{path}"


def describe_source(source: CameraSource) -> str:
    """供日志/报错/诊断显示的来源描述;URL 里的凭据一律遮蔽,不得落进 service.log。"""
    if is_stream(source):
        return f"url={mask_url(source)}"
    return f"index={source}"


class _LatestFrameReader:
    """网络串流专用:后台线程持续读帧,只保留最新一帧。

    DSHOW 设备来不及读的帧由驱动丢弃;HTTP/RTSP 串流则会在 socket 缓冲区里堆积,
    识别比来帧慢时延迟越积越大,活体提示(眨眼/转头)会对不上画面,故必须边读边丢。
    """

    def __init__(self, cap: cv2.VideoCapture, first_frame):
        self._cap = cap
        self._frame = first_frame
        self._seq = 1
        self._consumed = 0
        self._error = False
        self._stop = False
        self._cond = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="camera-stream", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop:
            ok, frame = self._cap.read()
            with self._cond:
                if not ok or frame is None:
                    self._error = True
                    self._cond.notify_all()
                    return
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()

    def read(self, timeout_s: float = 5.0):
        """返回比上次更新的一帧;串流断开或超时则抛错。

        已确认断流时立即报错,即使还有一张未取走的缓存帧也不再返回:那是断流前的旧画面,
        不能再拿去做活体/识别。
        """
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq > self._consumed or self._error,
                                       timeout=timeout_s):
                raise RuntimeError("读取摄像头帧超时")
            if self._error:
                raise RuntimeError("读取摄像头帧失败(串流已中断)")
            self._consumed = self._seq
            return self._frame

    def stop(self) -> bool:
        """通知线程退出并等待;返回线程是否已结束(卡在 read 里等不到时为 False)。"""
        self._stop = True
        self._thread.join(timeout=platform_backend.STREAM_TIMEOUT_MS / 1000 + 3.0)
        return not self._thread.is_alive()


class Camera:
    """RGB 摄像头采集。本机摄像头用 DSHOW;网络串流(URL)用 FFmpeg。"""

    def __init__(self, index: CameraSource = 0):
        self.index = index
        self._cap: cv2.VideoCapture | None = None
        self._reader: _LatestFrameReader | None = None
        self._has_lock = False

    def open(self, timeout_s: float = 30.0, delay: float = 0.3) -> None:
        """打开摄像头并确认能取到一帧;在 timeout_s 内退避重试,超时才抛错。

        本机摄像头只用 DSHOW:MSMF 后端在设备不可用时,`VideoCapture()` 构造调用会阻塞数十分钟
        (实测一次卡了约 33min),且是 C++ 层阻塞、Python 超时打不断,故不能用作回退。
        每次尝试把 open/read/耗时打进日志,便于排查睡眠唤醒后 DSHOW 何时恢复。
        """
        if self._cap is not None:
            return
        if not _capture_lock.acquire(blocking=False):
            raise RuntimeError("摄像头正被另一个 FaceHello 操作使用")
        self._has_lock = True
        backend = "STREAM" if is_stream(self.index) else "DSHOW"
        try:
            start = time.monotonic()
            attempt = 0
            while True:
                attempt += 1
                t0 = time.monotonic()
                cap = platform_backend.open_capture(self.index)
                opened = cap.isOpened()
                read_ok = False
                if opened:
                    ok, frame = cap.read()
                    read_ok = bool(ok and frame is not None)
                if read_ok:
                    print(f"[摄像头] {backend} 第 {attempt} 次就绪,累计 {time.monotonic() - start:.1f}s",
                          flush=True)
                    self._cap = cap
                    if is_stream(self.index):
                        self._reader = _LatestFrameReader(cap, frame)
                    return
                cap.release()
                print(f"[摄像头] {backend} 第 {attempt} 次失败 open={opened} read={read_ok} "
                      f"本次 {time.monotonic() - t0:.1f}s", flush=True)
                if time.monotonic() - start >= timeout_s:
                    raise RuntimeError(
                        f"无法打开摄像头({describe_source(self.index)},"
                        f"{timeout_s:.0f}s 内 {attempt} 次均失败)"
                    )
                time.sleep(delay)
        except Exception:
            self.release()
            raise

    def read(self):
        """返回一帧 BGR 图;失败抛异常。"""
        if self._cap is None:
            raise RuntimeError("摄像头未打开,请先 open()")
        if self._reader is not None:
            return self._reader.read()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("读取摄像头帧失败")
        return frame

    def release(self) -> None:
        if self._reader is not None:
            if not self._reader.stop():
                # 读线程仍卡在 cap.read():此时 release 会与之并发触碰 VideoCapture,
                # 宁可泄漏这一个句柄(线程超时后自行退出),也不冒 C++ 层崩溃的险。
                self._cap = None
            self._reader = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._has_lock:
            self._has_lock = False
            _capture_lock.release()

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

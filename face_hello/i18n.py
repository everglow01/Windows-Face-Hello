"""极简多语言:zh / en 文案目录。无 Qt 依赖,GUI、服务、核心库共用。

语言来源是 store 的 settings['language'](DEFAULTS 给 "zh")。约定:
- 库代码(liveness/auth/service)显式传 lang:`t(key, settings.get("language"))`;
- GUI 启动时 set_lang() 一次,之后用 tr(key)(走模块全局),故"重启控制台生效";
- C++ Credential Provider 读不了 DPAPI 人脸库,改读明文镜像 lang.txt(save_lang_mirror)。
"""
from __future__ import annotations

DEFAULT_LANG = "zh"

# 单一目录,按来源分段。占位符用命名参数,经 str.format 填充。
_CATALOG: dict[str, dict[str, str]] = {
    "zh": {
        # --- 核心:活体提示(liveness.py),会同时出现在控制台与锁屏磁贴 ---
        "face_camera": "请正对摄像头…",
        "blink_prompt": "请眨眼 {need} 次({cur}/{tot})",
        "turn_left": "请向左转头",
        "turn_right": "请向右转头",
        # --- 核心:认证编排(auth.py)---
        "recognizing": "识别中…",
        "liveness_failed": "活体检测失败(超时或未完成动作)",
        "no_face": "未检测到人脸",
        "auth_pass": "认证通过",
        "face_mismatch": "人脸不匹配(相似度 {sim:.3f} < {thr:.2f})",
        "ambiguous_match": "身份不明确(与他人过于接近,差值 {margin:.3f} < {m:.2f})",
        "locked": "失败次数过多,已锁定,请用密码登录(剩余 {secs} 秒)",
        "incomplete": "未完成",
        # --- 核心:服务(service.py,会回给磁贴显示)---
        "starting": "启动中…",
        "no_enrolled": "尚未录入任何人脸",
        # --- GUI:通用 ---
        "app_title": "Face_hello 管理台",
        "camera_preview": "摄像头预览",
        "tip": "提示",
        "done_title": "完成",
        "failed_title": "失败",
        "list_sep": "、",
        # --- GUI:录入页 ---
        "tab_enroll": "录入人脸",
        "win_account_name": "Windows 账户名",
        "start_enroll": "开始录入",
        "enroll_hint": "用户名需与登录 Windows 的账户一致;请正对摄像头,光线充足。",
        "username_label": "用户名:",
        "enter_username": "请输入用户名",
        "opening_camera": "正在打开摄像头…",
        "capturing": "拍摄中 {cur}/{tot} …",
        "enrolled_ok": "✅ 已录入「{name}」",
        "enroll_success": "用户「{name}」录入成功",
        "failed_fmt": "❌ 失败:{msg}",
        # --- GUI:测试解锁页 ---
        "tab_test": "测试解锁",
        "start_test_unlock": "开始测试解锁",
        "auth_idle_hint": "点击开始,按提示完成活体动作",
        "no_enroll_warn": "尚未录入任何人脸,请先在「录入」页登记",
        "preparing": "准备中…",
        "unlock_pass": "✅ 解锁通过 — {name}(相似度 {sim:.3f})",
        "unlock_reject": "❌ 拒绝 — {reason}",
        "error_fmt": "❌ 错误:{msg}",
        # --- GUI:设置页 ---
        "tab_settings": "设置与安全",
        "col_user": "用户名",
        "col_enroll_date": "录入日期",
        "col_days_left": "剩余天数",
        "col_status": "状态",
        "delete_selected": "删除选中用户",
        "liveness_check": "启用活体检测(关闭=直接识别,牺牲防照片能力)",
        "save_settings": "保存设置",
        "language_label": "界面语言(重启后生效):",
        "match_threshold_label": "匹配阈值(越高越严):",
        "grp_recognition": "识别",
        "grp_liveness": "活体",
        "grp_lockout": "锁定",
        "grp_enroll": "录入",
        "match_margin_label": "多账户安全间隔(0=关):",
        "lockout_fails_label": "失败锁定次数(0=关):",
        "lockout_secs_label": "锁定冷却(秒):",
        "yaw_label": "转头判定角度(°):",
        "blink_count_label": "眨眼挑战次数:",
        "renew_label": "人脸有效期(天):",
        "samples_label": "录入采集帧数:",
        "enrolled_users": "已录入用户",
        "params_security": "参数与安全策略",
        "expired_mark": "⚠ 已过期",
        "normal_status": "正常",
        "confirm_title": "确认",
        "delete_user_q": "删除用户「{name}」?",
        "saved_title": "已保存",
        "settings_saved": "设置已保存(语言更改将在重启控制台后生效)",
        # --- GUI:服务与凭据页 ---
        "tab_service": "服务与凭据",
        "unlock_pwd_placeholder": "锁屏解锁用的密码",
        "save_unlock_pwd": "保存解锁密码",
        "install_autostart": "安装并设为开机自启",
        "btn_start": "启动",
        "btn_stop": "停止",
        "btn_uninstall": "卸载",
        "btn_refresh": "刷新状态",
        "register_cp": "注册 CP 磁贴",
        "unregister_cp": "反注册",
        "current_account": "当前账户:{user}",
        "step1": "① 解锁密码(写入 LSA,刷脸时替你提交;微软账户登录的机器通常填本地登录密码)",
        "step2": "② 认证服务(LocalSystem,开机自启,锁屏时为凭据提供程序刷脸)",
        "step3": "③ 锁屏磁贴(Credential Provider;安装包会自动注册,此处用于排错或重编后手动刷新)",
        "admin_warn": "⚠ 设置密码与管理服务需要管理员权限,请以管理员身份重新运行本管理台。",
        "enter_pwd": "请输入密码",
        "lsa_write_fail": "写入 LSA 失败:{e}",
        "pwd_saved": "已为账户「{user}」保存解锁密码",
        "ret_code": "{action} 返回码 {rc}",
        "ret_code_simple": "返回码 {rc}",
        "install_title": "安装",
        "install_ok": "服务已安装并设为开机自启,已尝试启动",
        "uninstall_title": "卸载",
        "act_register": "注册",
        "act_unregister": "反注册",
        "dll_not_found_title": "未找到 DLL",
        "dll_not_found": "未找到 CP DLL:\n{dll}\n请先用 MSBuild 编译 cp\\FaceHelloCP.sln。",
        "cp_action_done": "CP 磁贴已{action}",
        "regsvr_code": "regsvr32 返回码 {rc}",
        "svc_status_prefix": "服务状态:",
        "svc_stopped": "已停止",
        "svc_starting": "启动中",
        "svc_stopping": "停止中",
        "svc_running": "运行中",
        "svc_paused": "已暂停",
        "svc_code": "状态码 {st}",
        "svc_not_installed": "未安装",
        # --- GUI:主窗口 ---
        "model_loading": "● 模型加载中…",
        "model_ready": "● 就绪",
        "expired_title": "人脸已过期",
        "expired_body": "以下用户人脸已超过有效期,建议重新录入:\n",
        # --- GUI:后台线程(workers.py)---
        "cancelled": "已取消",
        "capture_start": "正对镜头,开始拍摄…",
        "processing": "处理中…",
        "too_few_frames": "有效人脸帧太少({collected}/{total})——请正对镜头、光线充足后重试",
    },
    "en": {
        # --- core: liveness prompts (shown in console and on the lock-screen tile) ---
        "face_camera": "Face the camera…",
        "blink_prompt": "Blink {need} times ({cur}/{tot})",
        "turn_left": "Turn your head left",
        "turn_right": "Turn your head right",
        # --- core: auth orchestration ---
        "recognizing": "Recognizing…",
        "liveness_failed": "Liveness check failed (timed out or action not completed)",
        "no_face": "No face detected",
        "auth_pass": "Authenticated",
        "face_mismatch": "Face doesn't match (similarity {sim:.3f} < {thr:.2f})",
        "ambiguous_match": "Ambiguous identity (too close to another person, margin {margin:.3f} < {m:.2f})",
        "locked": "Too many failed attempts, locked — sign in with password ({secs}s left)",
        "incomplete": "Not completed",
        # --- core: service (returned to the tile) ---
        "starting": "Starting…",
        "no_enrolled": "No face enrolled yet",
        # --- GUI: general ---
        "app_title": "Face_hello Console",
        "camera_preview": "Camera preview",
        "tip": "Notice",
        "done_title": "Done",
        "failed_title": "Failed",
        "list_sep": ", ",
        # --- GUI: enroll tab ---
        "tab_enroll": "Enroll",
        "win_account_name": "Windows account name",
        "start_enroll": "Start enrolling",
        "enroll_hint": "The username must match your Windows sign-in account; face the camera in good light.",
        "username_label": "Username:",
        "enter_username": "Please enter a username",
        "opening_camera": "Opening the camera…",
        "capturing": "Capturing {cur}/{tot} …",
        "enrolled_ok": "✅ Enrolled “{name}”",
        "enroll_success": "User “{name}” enrolled successfully",
        "failed_fmt": "❌ Failed: {msg}",
        # --- GUI: test-unlock tab ---
        "tab_test": "Test unlock",
        "start_test_unlock": "Start test unlock",
        "auth_idle_hint": "Click start and follow the liveness prompts",
        "no_enroll_warn": "No face enrolled yet — please enroll on the Enroll tab first",
        "preparing": "Preparing…",
        "unlock_pass": "✅ Unlocked — {name} (similarity {sim:.3f})",
        "unlock_reject": "❌ Rejected — {reason}",
        "error_fmt": "❌ Error: {msg}",
        # --- GUI: settings tab ---
        "tab_settings": "Settings",
        "col_user": "Username",
        "col_enroll_date": "Enrolled",
        "col_days_left": "Days left",
        "col_status": "Status",
        "delete_selected": "Delete selected user",
        "liveness_check": "Enable liveness (off = recognize directly, weaker photo resistance)",
        "save_settings": "Save settings",
        "language_label": "Language (applies after restart):",
        "match_threshold_label": "Match threshold (higher = stricter):",
        "grp_recognition": "Recognition",
        "grp_liveness": "Liveness",
        "grp_lockout": "Lockout",
        "grp_enroll": "Enrollment",
        "match_margin_label": "Multi-account safety margin (0 = off):",
        "lockout_fails_label": "Lockout after N fails (0 = off):",
        "lockout_secs_label": "Lockout cooldown (seconds):",
        "yaw_label": "Head-turn angle (°):",
        "blink_count_label": "Blink challenge count:",
        "renew_label": "Face validity (days):",
        "samples_label": "Enrollment frames:",
        "enrolled_users": "Enrolled users",
        "params_security": "Parameters & security policy",
        "expired_mark": "⚠ Expired",
        "normal_status": "OK",
        "confirm_title": "Confirm",
        "delete_user_q": "Delete user “{name}”?",
        "saved_title": "Saved",
        "settings_saved": "Settings saved (language change takes effect after restarting the console)",
        # --- GUI: service & credentials tab ---
        "tab_service": "Service & credentials",
        "unlock_pwd_placeholder": "Password used for lock-screen unlock",
        "save_unlock_pwd": "Save unlock password",
        "install_autostart": "Install & set to auto-start",
        "btn_start": "Start",
        "btn_stop": "Stop",
        "btn_uninstall": "Uninstall",
        "btn_refresh": "Refresh status",
        "register_cp": "Register CP tile",
        "unregister_cp": "Unregister",
        "current_account": "Current account: {user}",
        "step1": "① Unlock password (stored in LSA, submitted for you on face match; Microsoft-account machines usually use the local sign-in password)",
        "step2": "② Auth service (LocalSystem, auto-start, recognizes faces for the Credential Provider at the lock screen)",
        "step3": "③ Lock-screen tile (Credential Provider; the installer registers it automatically — use this for troubleshooting or a manual refresh after rebuilding)",
        "admin_warn": "⚠ Setting the password and managing the service need Administrator — please relaunch this console as administrator.",
        "enter_pwd": "Please enter a password",
        "lsa_write_fail": "Failed to write LSA: {e}",
        "pwd_saved": "Saved the unlock password for account “{user}”",
        "ret_code": "{action} returned {rc}",
        "ret_code_simple": "Return code {rc}",
        "install_title": "Install",
        "install_ok": "Service installed and set to auto-start; start attempted",
        "uninstall_title": "Uninstall",
        "act_register": "Register",
        "act_unregister": "Unregister",
        "dll_not_found_title": "DLL not found",
        "dll_not_found": "CP DLL not found:\n{dll}\nBuild cp\\FaceHelloCP.sln with MSBuild first.",
        "cp_action_done": "CP tile {action}ed",
        "regsvr_code": "regsvr32 returned {rc}",
        "svc_status_prefix": "Service status: ",
        "svc_stopped": "Stopped",
        "svc_starting": "Starting",
        "svc_stopping": "Stopping",
        "svc_running": "Running",
        "svc_paused": "Paused",
        "svc_code": "Status code {st}",
        "svc_not_installed": "Not installed",
        # --- GUI: main window ---
        "model_loading": "● Loading model…",
        "model_ready": "● Ready",
        "expired_title": "Face expired",
        "expired_body": "The enrolled face for these users has expired; re-enrollment is recommended:\n",
        # --- GUI: background workers ---
        "cancelled": "Cancelled",
        "capture_start": "Face the camera; capturing…",
        "processing": "Processing…",
        "too_few_frames": "Too few valid face frames ({collected}/{total}) — face the camera in good light and retry",
    },
}

_LANG = DEFAULT_LANG  # GUI 进程级当前语言(由 set_lang 设定)


def t(key: str, lang: str = DEFAULT_LANG, **kw) -> str:
    """取 key 在 lang 下的文案;缺 key 回退到默认语言,再回退到 key 本身。"""
    table = _CATALOG.get(lang) or _CATALOG[DEFAULT_LANG]
    s = table.get(key)
    if s is None:
        s = _CATALOG[DEFAULT_LANG].get(key, key)
    return s.format(**kw) if kw else s


def set_lang(lang: str) -> None:
    """设置 GUI 进程级语言(tr 用)。非法值回退默认。"""
    global _LANG
    _LANG = lang if lang in _CATALOG else DEFAULT_LANG


def tr(key: str, **kw) -> str:
    """GUI 便捷取值:走 set_lang 设定的全局语言。"""
    return t(key, _LANG, **kw)


def save_lang_mirror(lang: str) -> None:
    """把语言写成明文镜像 lang.txt,供 C++ Credential Provider(SYSTEM)在锁屏读取。

    尽力而为:目录/权限问题不抛(控制台非管理员时可能写不进 ProgramData,
    服务以 SYSTEM 启动时会再同步一次,保证重启后磁贴语言与设置一致)。
    """
    from . import config

    try:
        config.AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        config.LANG_FILE.write_text(
            lang if lang in _CATALOG else DEFAULT_LANG, encoding="ascii"
        )
    except OSError:
        pass

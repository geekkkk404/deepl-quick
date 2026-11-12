"""deepl-quick — DeepL API 桌面翻译小窗
置顶无边框小窗：输入文本（源语言自动检测），勾选的常驻目标语一键翻译，逐语种一键复制。
数据纯本地（脚本同目录 config.json / cache.json / history.json；密钥独立存 .deepl-key，绝不入库）。
额度纪律：缓存优先（命中零调用）、默认手动触发（Ctrl+Enter）、456 额度耗尽绝不重试、429/529 退避重试。
用法：双击运行；`python deepl_quick.pyw --smoke` 为自检模式（重定向数据文件到临时目录、不发网络请求）；
`--minimized` 启动即缩成贴边药丸（开机自启命令自带此参数，开关在设置弹窗）。
"""
import ctypes
import hashlib
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import winreg
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

APP_VERSION = "0.2"

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
KEY_FILE = os.path.join(APP_DIR, ".deepl-key")
CACHE_FILE = os.path.join(APP_DIR, "cache.json")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")

HOST_FREE = "https://api-free.deepl.com"   # 免费档（key 以 :fx 结尾）
HOST_PRO = "https://api.deepl.com"         # 付费档
REQUEST_TIMEOUT = 30
RETRY_DELAYS = (1, 2)                      # 429/529 退避重试间隔（秒）
CACHE_MAX = 3000
HISTORY_MAX = 500
AUTO_DELAY_MS = 1500                       # 防抖自动翻译：输入停止后延迟
TARGETS_MAX = 8                            # 常驻目标语上限（保持前端干净）
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"  # 开机自启落点（HKCU，免管理员）
AUTOSTART_NAME = "deepl-quick"             # Run 键值名（任务管理器「启动应用」页显示这个名字）

FONT = "Microsoft YaHei UI"
W, H = 560, 620
PILL_H = 30                # 贴边药丸高度（宽度按文字实测自适应，不写死——QuadTodo P-002 教训）
BG = "#f2f3f5"
TITLE_BG = "#2f3640"
CARD_BG = "#e8eaf0"
ERR_FG = "#c0392b"
OK_FG = "#27ae60"

# 兜底目标语清单（动态拉取失败时使用；code 为 DeepL target 语言码，与 LANG_NAMES 覆盖一致）
FALLBACK_LANGS = [
    ("AR", "阿拉伯语"), ("BG", "保加利亚语"), ("CS", "捷克语"), ("DA", "丹麦语"),
    ("DE", "德语"), ("EL", "希腊语"), ("EN-US", "英语（美）"), ("EN-GB", "英语（英）"),
    ("ES", "西班牙语"), ("ET", "爱沙尼亚语"), ("FI", "芬兰语"), ("FR", "法语"),
    ("HE", "希伯来语"), ("HU", "匈牙利语"), ("ID", "印尼语"), ("IT", "意大利语"),
    ("JA", "日语"), ("KO", "韩语"), ("LT", "立陶宛语"), ("LV", "拉脱维亚语"),
    ("NB", "挪威语"), ("NL", "荷兰语"), ("PL", "波兰语"), ("PT-BR", "葡语（巴西）"),
    ("PT-PT", "葡语（欧）"), ("RO", "罗马尼亚语"), ("RU", "俄语"), ("SK", "斯洛伐克语"),
    ("SL", "斯洛文尼亚语"), ("SV", "瑞典语"), ("TH", "泰语"), ("TR", "土耳其语"),
    ("UK", "乌克兰语"), ("VI", "越南语"), ("ZH", "中文（简体）"),
]
LANG_NAMES = dict(FALLBACK_LANGS)
LANG_NAMES.update({"EN": "英语", "PT": "葡萄牙语", "ZH": "中文（简体）"})
DEFAULT_TARGETS = ["EN-US", "JA", "ZH"]

DEFAULT_CONFIG = {
    "window": {},                 # x / y / w / h，记忆窗口位置尺寸
    "pill_y": 120,                # 贴边药丸的纵向位置（屏幕右缘）
    "targets": list(DEFAULT_TARGETS),
    "save_history": True,
    "model_quality": False,       # True → model_type=quality_optimized（next-gen 高质量）
    "auto_translate": False,      # 输入防抖自动翻译（已确认默认关）
    "topmost": True,
    "host_mode": "auto",          # auto / free / pro
}


# ---------------------------------------------------------------- 数据层

def _dbg(msg):
    """临时调试开关：DQ_DEBUG=1 时把药丸决策写入临时日志（诊断后移除）。"""
    if os.environ.get("DQ_DEBUG"):
        try:
            with open(r"C:\Users\Henry\AppData\Local\Temp\dq_poll.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        except OSError:
            pass


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        try:
            os.replace(path, path + ".corrupt")
        except OSError:
            pass
        return json.loads(json.dumps(default))
    return d


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def load_config():
    d = load_json(CONFIG_FILE, {})
    for k, v in DEFAULT_CONFIG.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    return d


def load_cache():
    d = load_json(CACHE_FILE, {})
    return d if isinstance(d, dict) else {}


def load_history():
    d = load_json(HISTORY_FILE, [])
    return d if isinstance(d, list) else []


def append_history(history, entry):
    history.append(entry)
    if len(history) > HISTORY_MAX:
        del history[: len(history) - HISTORY_MAX]


def cache_key(text, target, model_type):
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    for part in ("\x00", target, "\x00", model_type or ""):
        h.update(part.encode("utf-8"))
    return h.hexdigest()


def cache_prune(cache, limit=CACHE_MAX):
    if len(cache) <= limit:
        return cache
    items = sorted(cache.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)
    return dict(items[:limit])


def load_key():
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            k = f.read().strip()
        return k or None
    except OSError:
        return None


def save_key(key):
    try:
        if key:
            with open(KEY_FILE, "w", encoding="utf-8") as f:
                f.write(key.strip() + "\n")
        elif os.path.exists(KEY_FILE):
            os.remove(KEY_FILE)
    except OSError:
        pass


def key_masked(key):
    if not key:
        return "未设置"
    tail = key[-4:] if len(key) >= 4 else key
    return f"已设置（…{tail}）"


# ---------------------------------------------------------------- 开机自启（U-004 拍板方案 A：注册表 HKCU Run 键）

def _autostart_cmd():
    """自启命令。优先 pythonw.exe 免登录闪控制台；--minimized 使自启直接呈药丸态
    （手动双击不带此参数、仍开完整窗）；预留 PyInstaller 打包分支（sys.frozen 时 exe 即一切）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.basename(exe).lower() != "pythonw.exe" and os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(sys.argv[0])}" --minimized'


def autostart_enabled(key_path=RUN_KEY_PATH):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
        return True
    except OSError:
        return False


def autostart_enable(key_path=RUN_KEY_PATH):
    """upsert：键不存在则建；文件移动后重新保存一次设置即自愈。"""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
        winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_cmd())


def autostart_disable(key_path=RUN_KEY_PATH):
    """幂等：键或值不存在时静默成功。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, AUTOSTART_NAME)
    except FileNotFoundError:
        pass


def acquire_single_instance(name="deepl_quick_singleton"):
    """防双开：自启药丸常驻时再手动双击，右缘会叠出两枚胶囊。成功分支的互斥句柄
    刻意随进程存活不关闭；互斥创建失败宁可放行也不拦启动（fail-open）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if ctypes.get_last_error() == 183:       # ERROR_ALREADY_EXISTS
        k32.CloseHandle(handle)
        return False
    return True


def pick_host(key, mode="auto", override=""):
    """选 API host：override > 显式模式 > 按 :fx 后缀自动判断。"""
    if override:
        return override.rstrip("/")
    if mode == "free":
        return HOST_FREE
    if mode == "pro":
        return HOST_PRO
    return HOST_FREE if (key or "").endswith(":fx") else HOST_PRO


def lang_name(code):
    return LANG_NAMES.get(code) or LANG_NAMES.get((code or "").split("-")[0]) or (code or "?")


def fmt_num(n):
    if n >= 10**6:
        return f"{n / 10**6:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_usage(count, limit):
    if limit <= 0 or limit >= 10**11:      # 未设上限/成本控制时
        return f"{fmt_num(count)} / ∞"
    return f"{fmt_num(count)}/{fmt_num(limit)}（{count * 100 // max(limit, 1)}%）"


def format_copy_all(results):
    """results: [(code, text)] → 复制全部的统一格式"""
    return "\n".join(f"【{lang_name(c)}】{t}" for c, t in results if t)


# ---------------------------------------------------------------- API 层

class ApiError(Exception):
    def __init__(self, message, status=None, trace_id=None):
        super().__init__(message)
        self.status = status
        self.trace_id = trace_id


class QuotaError(ApiError):
    pass                                    # 456 额度耗尽，绝不重试


class BadRequest(ApiError):
    pass                                    # 400 参数错，不重试


class AuthError(ApiError):
    pass                                    # 401/403 key 无效


class NetworkError(ApiError):
    pass                                    # 超时/连接失败


def classify_http_error(status, body=""):
    """HTTP 状态码 → (异常类, 中文提示)。纯函数，便于离线测试。"""
    msg = ""
    try:
        msg = (json.loads(body) or {}).get("message", "") or (body or "")[:200]
    except Exception:
        msg = (body or "")[:200]
    if status == 456:
        return QuotaError, "额度已用完（本月配额耗尽），下月再试或升级套餐——已停止本次任务"
    if status in (429, 529):
        return ApiError, "DeepL 过载/限流"
    if status in (401, 403):
        return AuthError, "key 无效或无权访问该接口（检查 .deepl-key 与 host 设置）"
    if status == 400:
        return BadRequest, "请求参数被拒绝：" + (msg or "未知原因")
    if status == 413:
        return BadRequest, "文本过大（单请求上限 128 KiB），请分段翻译"
    return ApiError, f"HTTP {status}：{msg or '未知错误'}"


def build_url(host, path):
    return host.rstrip("/") + path


def api_request(key, host, method, path, payload=None):
    """单次 HTTP 请求（不含重试）。urllib 遵循 https_proxy 等环境变量代理。"""
    data = None
    headers = {"Authorization": "DeepL-Auth-Key " + (key or "")}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(build_url(host, path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        trace = e.headers.get("X-Trace-ID") if e.headers else None
        cls, msg = classify_http_error(e.code, body)
        raise cls(msg, status=e.code, trace_id=trace) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkError(f"网络错误（检查网络/代理，DeepL API 可能需代理访问）：{e}") from None


def translate_text(key, host, text, target, model_type=None, request_fn=api_request):
    """翻译一段文本。429/529 按退避重试，其余错误直接抛出。"""
    payload = {"text": [text], "target_lang": target, "show_billed_characters": True}
    if model_type:
        payload["model_type"] = model_type
    last = None
    for delay in (None,) + RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            resp = request_fn(key, host, "POST", "/v2/translate", payload)
            tr = resp["translations"][0]
            return tr
        except ApiError as e:
            if e.status in (429, 529):
                last = e
                continue
            raise
    raise last


def fetch_usage(key, host, request_fn=api_request):
    resp = request_fn(key, host, "GET", "/v2/usage")
    return resp.get("character_count", 0), resp.get("character_limit", 0)


def fetch_target_languages(key, host, request_fn=api_request):
    """动态目标语清单。/v3/languages 防御性解析（正式 schema 待 U-002 实测），
    失败回退 /v2/languages?type=target（deprecated 但格式稳定）。返回 [(code, name, supports_formality)]。"""
    try:
        resp = request_fn(key, host, "GET", "/v3/languages")
        items = resp if isinstance(resp, list) else resp.get("languages", [])
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = item.get("language") or item.get("code")
            if not code:
                continue
            sup = item.get("supported_as") or {}
            if isinstance(sup, dict) and sup:
                tr = sup.get("translate") or {}
                if tr and tr.get("target") is False:
                    continue
            out.append((code, item.get("name") or code, bool(item.get("supports_formality"))))
        if out:
            return out
    except ApiError:
        pass
    resp = request_fn(key, host, "GET", "/v2/languages?type=target")
    return [(i["language"], i.get("name", i["language"]), bool(i.get("supports_formality")))
            for i in resp if isinstance(i, dict) and i.get("language")]


# ---------------------------------------------------------------- UI 部件

class ScrollFrame(tk.Frame):
    """Canvas + 内嵌 Frame 的可滚动容器（卡片列表 / 语言选择器共用）。"""

    def __init__(self, master, bg=BG, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.sb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.refresh())
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def refresh(self):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


# ---------------------------------------------------------------- 主应用

class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.key = load_key()
        self.cache = load_cache()
        self.history = load_history()
        self.msgq = queue.Queue()
        self.cards = {}                  # target → {"frame","text","status"}
        self._langs_cache = None         # 动态语言清单 [(code,name,formality)]
        self._busy = False
        self._drag = None
        self._rs = None
        self._pressing = False          # 拖动/拉伸中暂停自动折叠（QuadTodo P-004）
        self._pill_mode = False
        self._pill_y = max(0, int(self.cfg.get("pill_y", 120)))
        self._normal_size = (W, H)
        self._pill_w = 34
        self._leave_after = None        # 鼠标离开后的延迟折叠定时器
        self._pill_font = None
        self._still = (0, 0)            # 折叠瞬间的指针位置：静止点，防弹跳（QuadTodo P-003）
        self._auto_after = None
        self._last_usage_fetch = 0.0
        self._icon = None
        self._settings = None
        self._picker = None
        self._history_win = None

        self._build_ui()
        self._restore_window()
        self.root.attributes("-topmost", bool(self.cfg.get("topmost")))
        self.rebuild_chips()
        self.rebuild_cards()
        self.root.after(80, self._poll)
        self.root.after(400, self._auto_pill_poll)
        self._refresh_usage_async(force=True)
        self.set_status("就绪——鼠标离开自动缩成贴边药丸，移上去展开；Ctrl+Enter 翻译" if self.key
                        else "尚未设置 API Key：点标题栏「设」粘贴你的 DeepL key")

    # ---- 窗口骨架

    def _make_icon(self):
        img = tk.PhotoImage(width=32, height=32)
        img.put("#0f2b46", to=(0, 0, 32, 32))
        img.put("#4fc3f7", to=(4, 6, 15, 17))
        img.put("#ffffff", to=(18, 13, 28, 23))
        self._icon = img
        self.root.iconphoto(True, img)

    def _build_ui(self):
        self.root.title(f"deepl-quick v{APP_VERSION}")
        self.root.configure(bg=BG)
        self.root.overrideredirect(True)     # 无边框（QuadTodo 同款）：拖动/折叠/resize 全自绘
        self._make_icon()

        # 自绘标题栏：拖动 + 用量徽标 + 钉/设/史/—/✕
        tb = tk.Frame(self.root, bg=TITLE_BG)
        tb.pack(fill="x")
        self.lbl_title = tk.Label(tb, text=f" deepl-quick v{APP_VERSION}", bg=TITLE_BG, fg="white",
                                  font=(FONT, 10, "bold"))
        self.lbl_title.pack(side="left")
        for w in (self.lbl_title, tb):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
        self.lbl_usage = tk.Label(tb, text="", bg=TITLE_BG, fg="#9fb3c8", font=(FONT, 9))
        self.lbl_usage.pack(side="right", padx=(0, 8))   # 最右：用量徽标
        self._title_btn(tb, "✕", self.quit_app)          # 之后依次向左：✕ — 史 设 钉
        self._title_btn(tb, "—", self._manual_collapse)
        self._title_btn(tb, "史", self.open_history)
        self._title_btn(tb, "设", self.open_settings)
        self.lbl_pin = self._title_btn(tb, "钉", self.toggle_topmost)
        self._update_pin()

        # 输入区
        self.input = tk.Text(self.root, height=4, font=(FONT, 11), wrap="word", relief="flat",
                             highlightthickness=1, highlightbackground="#d0d4d8",
                             highlightcolor=TITLE_BG, bg="white", fg="#333333",
                             insertbackground="#333333", undo=True)
        self.input.pack(fill="x", padx=12, pady=(10, 0))
        self.input.bind("<Control-Return>", self._on_ctrl_enter)
        self.input.bind("<KeyRelease>", self._on_input_key)

        # 操作行
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=12, pady=6)
        self.btn_go = self._bar_btn(bar, "翻译（Ctrl+Enter）", self.translate_all, primary=True)
        self._bar_btn(bar, "清空", self.clear_input)
        self._bar_btn(bar, "复制全部", self.copy_all)
        self.lbl_hint = tk.Label(bar, text="", bg=BG, fg="#8a94a0", font=(FONT, 9))
        self.lbl_hint.pack(side="right")

        # 常驻目标语 chips
        langbar = tk.Frame(self.root, bg=BG)
        langbar.pack(fill="x", padx=12)
        tk.Label(langbar, text="目标语言：", bg=BG, fg="#666666", font=(FONT, 9)).pack(side="left")
        self.chipbox = tk.Frame(langbar, bg=BG)
        self.chipbox.pack(side="left")
        add = tk.Label(langbar, text="＋语言", bg="#dfe3ea", fg=TITLE_BG, font=(FONT, 9),
                       padx=6, pady=2, cursor="hand2")
        add.pack(side="left")
        add.bind("<Button-1>", lambda e: self.open_picker())

        # 结果卡片容器（可滚动）
        self.scroll = ScrollFrame(self.root)
        self.scroll.pack(fill="both", expand=True, padx=12, pady=(6, 0))

        # 状态栏 + 右下角 resize 手柄
        statusbar = tk.Frame(self.root, bg=BG)
        statusbar.pack(fill="x", side="bottom")
        self.lbl_status = tk.Label(statusbar, text="就绪", bg=BG, fg="#8a94a0",
                                   font=(FONT, 9), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True, padx=(12, 0), pady=(2, 6))
        grip = tk.Label(statusbar, text="◢", bg=BG, fg="#b0b6bd", font=(FONT, 10),
                        cursor="size_nw_se")
        grip.pack(side="right", padx=(0, 4))
        grip.bind("<Button-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize_move)
        grip.bind("<ButtonRelease-1>", self._drag_end)

        # 贴边药丸（QuadTodo 同款形态）：主内容收起后只剩一枚「译」小胶囊，贴屏幕右缘
        self.pill = tk.Frame(self.root, bg=TITLE_BG, cursor="hand2")
        self.lbl_pill = tk.Label(self.pill, text="译", bg=TITLE_BG, fg="white",
                                 font=(FONT, 11, "bold"), cursor="hand2")
        self.lbl_pill_usage = tk.Label(self.pill, text="", bg=TITLE_BG, fg="#f39c12",
                                       font=(FONT, 8, "bold"), cursor="hand2")
        self.lbl_pill.pack(side="left", padx=(8, 0), pady=4)
        self.lbl_pill_usage.pack(side="left", padx=(4, 8))
        self._pill_font = tkfont.Font(root=self.root, family=FONT, size=11, weight="bold")
        for w in (self.pill, self.lbl_pill, self.lbl_pill_usage):
            w.bind("<Motion>", self._pill_motion)   # 只认真实移动事件：静止指针不误弹（P-003）
        self._pack_specs = [
            (tb, {"fill": "x"}),
            (self.input, {"fill": "x", "padx": 12, "pady": (10, 0)}),
            (bar, {"fill": "x", "padx": 12, "pady": 6}),
            (langbar, {"fill": "x", "padx": 12}),
            (self.scroll, {"fill": "both", "expand": True, "padx": 12, "pady": (6, 0)}),
            (statusbar, {"fill": "x", "side": "bottom"}),
        ]

    def _title_btn(self, bar, text, cmd):
        lbl = tk.Label(bar, text=text, bg=TITLE_BG, fg="#c8d0d8", font=(FONT, 10),
                       padx=8, cursor="hand2")
        lbl.pack(side="right")
        lbl.bind("<Button-1>", lambda e: cmd())
        return lbl

    def _bar_btn(self, bar, text, cmd, primary=False):
        lbl = tk.Label(bar, text=text, bg=TITLE_BG if primary else "#e4e6e9",
                       fg="white" if primary else "#333333", font=(FONT, 10),
                       padx=14, pady=3, cursor="hand2")
        lbl.pack(side="left", padx=(0, 8))
        lbl.bind("<Button-1>", lambda e: cmd())
        return lbl

    def _restore_window(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        geo = self.cfg.get("window") or {}
        x = max(-20, min(int(geo.get("x", sw - W - 60)), sw - 120))
        y = max(-20, min(int(geo.get("y", 80)), sh - 120))
        w = max(420, min(int(geo.get("w", W)), sw - x))
        h = max(480, min(int(geo.get("h", H)), sh - y))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _drag_start(self, e):
        self._drag = (e.x, e.y)
        self._pressing = True

    def _drag_move(self, e):
        if self._drag:
            x = self.root.winfo_x() + e.x - self._drag[0]
            y = self.root.winfo_y() + e.y - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _resize_start(self, e):
        self._rs = (self.root.winfo_width(), self.root.winfo_height())
        self._pressing = True

    def _resize_move(self, e):
        if self._rs:
            w = max(420, self._rs[0] + e.x - 12)
            h = max(480, self._rs[1] + e.y - 4)
            self.root.geometry(f"{w}x{h}")

    def _drag_end(self, _e=None):
        self._pressing = False

    # ---- 贴边药丸（移植 QuadTodo：离开 0.75s 自动折叠、悬停展开、静止不弹跳、拖动/弹窗不折叠）

    def _dialogs_open(self):
        for w in (self._settings, self._picker, self._history_win):
            if w is not None and w.winfo_exists():
                return True
        return False

    def _pointer_inside(self):
        x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        wx, wy = self.root.winfo_x(), self.root.winfo_y()
        return (wx <= x <= wx + self.root.winfo_width()
                and wy <= y <= wy + self.root.winfo_height())

    def _pill_w_now(self):
        text = "译"
        badge = self.lbl_pill_usage.cget("text")
        if badge:
            text += " " + badge
        return self._pill_font.measure(text) + 24

    def _enter_pill(self, force=False):
        _dbg(f"enter_pill force={force} inside={self._pointer_inside()} mode={self._pill_mode}")
        if self._pill_mode:
            return
        if not force and self._pointer_inside():     # 指针在窗内绝不折叠（防弹跳）
            return
        sh = self.root.winfo_screenheight()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        self._normal_size = (max(w, 420), max(h, 480))
        self._pill_y = max(0, min(self.root.winfo_y(), sh - PILL_H))
        self._pill_w = self._pill_w_now()
        for widget, opts in self._pack_specs:
            widget.pack_forget()
        self.pill.pack(fill="both", expand=True)
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{self._pill_w}x{PILL_H}+{sw - self._pill_w}+{self._pill_y}")
        self._pill_mode = True
        self._still = (self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _exit_pill(self):
        _dbg("exit_pill called")
        if not self._pill_mode:
            return
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = self._normal_size
        x = max(0, sw - w)                   # 展开位固定贴右缘、顶部对齐药丸（QuadTodo P-003）
        y = max(0, min(self._pill_y, sh - h))
        self.pill.pack_forget()
        for widget, opts in self._pack_specs:
            widget.pack(**opts)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self._pill_mode = False
        _dbg(f"exit_pill done -> {w}x{h}+{x}+{y} pointer=({self.root.winfo_pointerx()},{self.root.winfo_pointery()})")
        self.scroll.refresh()

    def _manual_collapse(self):
        self._enter_pill(force=True)

    def _auto_pill_poll(self):
        if self._pill_mode:
            # 展开靠轮询指针坐标（winfo_pointer 按需读真实位置，不依赖事件投递，
            # RDP/虚拟化下 Motion 事件可能整批丢失——P-007 实测）；静止点不弹（P-003）
            px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
            inside = self._pointer_inside()
            _dbg(f"poll pill px={px} py={py} inside={inside} still={self._still} "
                 f"wx={self.root.winfo_x()} wy={self.root.winfo_y()} "
                 f"ww={self.root.winfo_width()} wh={self.root.winfo_height()}")
            if inside and (px, py) != self._still:
                self._exit_pill()
        else:
            inside = self._pointer_inside()
            _dbg(f"poll main px={self.root.winfo_pointerx()} "
                 f"py={self.root.winfo_pointery()} inside={inside} pressing={self._pressing} "
                 f"ww={self.root.winfo_width()} wh={self.root.winfo_height()}")
            if (not self._pressing and not self._dialogs_open() and not inside):
                if self._leave_after is None:
                    _dbg("schedule collapse in 750ms")
                    self._leave_after = self.root.after(750, self._do_collapse)
            elif self._leave_after is not None:
                self.root.after_cancel(self._leave_after)
                self._leave_after = None
                _dbg("cancel collapse (pointer back)")
        self.root.after(150, self._auto_pill_poll)

    def _do_collapse(self):
        self._leave_after = None
        _dbg("do_collapse fired")
        if (not self._pill_mode and not self._pressing and not self._dialogs_open()
                and not self._pointer_inside()):
            self._enter_pill()

    def _pill_motion(self, _e):
        """快速路径：真实移动事件到达时立即展开（轮询兜底见 _auto_pill_poll）。"""
        px, py = self.root.winfo_pointerx(), self.root.winfo_pointery()
        _dbg(f"pill_motion px={px} py={py} still={self._still} pressing={self._pressing}")
        if self._pill_mode and not self._pressing and (px, py) != self._still:
            self._exit_pill()

    # ---- chips 与结果卡片

    def rebuild_chips(self):
        for w in self.chipbox.winfo_children():
            w.destroy()
        for t in self.cfg["targets"]:
            chip = tk.Label(self.chipbox, text=f" {lang_name(t)} ×", bg="#dfe3ea", fg="#444444",
                            font=(FONT, 9), padx=6, pady=2, cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda e, t=t: self.remove_target(t))

    def rebuild_cards(self):
        for c in self.cards.values():
            c["frame"].destroy()
        self.cards.clear()
        for t in self.cfg["targets"]:
            f = tk.Frame(self.scroll.inner, bg=CARD_BG)
            f.pack(fill="x", pady=3)
            head = tk.Frame(f, bg=CARD_BG)
            head.pack(fill="x")
            tk.Label(head, text=f"{lang_name(t)}  {t}", bg=CARD_BG, fg="#444444",
                     font=(FONT, 9, "bold")).pack(side="left", padx=(8, 0), pady=(4, 0))
            st = tk.Label(head, text="待翻译", bg=CARD_BG, fg="#999999", font=(FONT, 8))
            st.pack(side="left", padx=8)
            cp = tk.Label(head, text="复制", bg=CARD_BG, fg=TITLE_BG, font=(FONT, 9),
                          cursor="hand2")
            cp.pack(side="right", padx=8, pady=(4, 0))
            txt = tk.Text(f, height=2, wrap="word", relief="flat", bg="white", fg="#333333",
                          font=(FONT, 10), state="disabled", highlightthickness=0)
            txt.pack(fill="x", padx=8, pady=(2, 6))
            txt.bind("<MouseWheel>", self._card_wheel)   # 卡片上滚轮滚列表，避免双滚动
            cp.bind("<Button-1>", lambda e, t=t: self.copy_one(t))
            self.cards[t] = {"frame": f, "text": txt, "status": st}
        self.scroll.refresh()
        self._update_estimate()

    def _card_wheel(self, e):
        """卡片译文上的滚轮滚卡片列表（Text 类默认滚动关掉，避免双滚动）。"""
        self.scroll.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        return "break"

    def remove_target(self, target):
        self.cfg["targets"] = [t for t in self.cfg["targets"] if t != target]
        self.rebuild_chips()
        self.rebuild_cards()

    # ---- 翻译主流程

    def _on_ctrl_enter(self, _e):
        self.translate_all()
        return "break"

    def _on_input_key(self, _e):
        self._update_estimate()
        if self.cfg.get("auto_translate") and not self._busy:
            if self._auto_after:
                self.root.after_cancel(self._auto_after)
            self._auto_after = self.root.after(AUTO_DELAY_MS, self.translate_all)

    def _update_estimate(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            self.lbl_hint.configure(text="")
            return
        n = sum(1 for t in self.cfg["targets"] if cache_key(text, t, self._model_type()) not in self.cache)
        self.lbl_hint.configure(text=f"预计消耗 ≈{len(text) * n} 字符（{len(text)}×{n} 语）"
                                if n else "全部命中缓存，本次零消耗")

    def _model_type(self):
        return "quality_optimized" if self.cfg.get("model_quality") else None

    def translate_all(self):
        if self._busy:
            return
        if self._auto_after:
            self.root.after_cancel(self._auto_after)
            self._auto_after = None
        text = self.input.get("1.0", "end").strip()
        if not text:
            self.set_status("先输入要翻译的文本", warn=True)
            return
        if not self.key:
            self.set_status("尚未设置 API Key：在设置里粘贴你的 DeepL key", err=True)
            self.open_settings()
            return
        targets = list(self.cfg["targets"])
        if not targets:
            self.set_status("请先勾选至少一门目标语言", warn=True)
            return
        self._busy = True
        self.btn_go.configure(text="翻译中…", bg="#8a94a0")
        for c in self.cards.values():
            self._set_card_status(c, "…", "#999999")
        threading.Thread(target=self._worker, args=(text, targets), daemon=True).start()

    def _worker(self, text, targets):
        q = self.msgq
        host = pick_host(self.key, self.cfg.get("host_mode", "auto"))
        model = self._model_type()
        for i, t in enumerate(targets, 1):
            q.put(("progress", i, len(targets)))
            ck = cache_key(text, t, model)
            hit = self.cache.get(ck)
            if hit:
                q.put(("card", t, hit.get("text", ""), hit.get("detected", ""),
                       hit.get("billed", 0), True))
                continue
            try:
                tr = translate_text(self.key, host, text, t, model)
            except QuotaError as e:
                q.put(("quota", t, str(e)))
                break
            except ApiError as e:
                q.put(("card_err", t, str(e)))
                continue
            det = tr.get("detected_source_language", "")
            billed = tr.get("billed_characters", 0)
            out = tr.get("text", "")
            self.cache[ck] = {"target": t, "text": out, "detected": det,
                              "billed": billed, "ts": time.time()}
            if self.cfg.get("save_history"):
                append_history(self.history, {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "source": text, "target": t, "detected": det, "result": out,
                })
            q.put(("card", t, out, det, billed, False))
        pruned = cache_prune(self.cache)
        if pruned is not self.cache:
            self.cache = pruned
        save_cache_file(self.cache)
        save_history_file(self.history)
        q.put(("done",))

    def _poll(self):
        try:
            while True:
                msg = self.msgq.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    self.set_status(f"翻译中 {msg[1]}/{msg[2]} …")
                elif kind == "card":
                    self._on_card_ok(*msg[1:])
                elif kind == "card_err":
                    self._on_card_err(msg[1], msg[2])
                elif kind == "quota":
                    self._on_quota(msg[1], msg[2])
                elif kind == "usage":
                    self._on_usage(msg[1], msg[2])
                elif kind == "langs":
                    self._langs_cache = msg[1]
                    self.set_status(f"语言清单已刷新：共 {len(msg[1])} 门")
                elif kind == "done":
                    self._on_done()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _set_card_status(self, card, text, color):
        card["status"].configure(text=text, fg=color)

    def _set_card_text(self, target, text):
        txt = self.cards[target]["text"]
        txt.configure(state="normal")
        txt.delete("1.0", "end")
        txt.insert("1.0", text)
        txt.configure(state="disabled")

    def _on_card_ok(self, target, out, det, billed, cached):
        self._set_card_text(target, out)
        if cached:
            self._set_card_status(self.cards[target], "缓存命中 · 零消耗", OK_FG)
        else:
            self._set_card_status(self.cards[target], f"{billed} 字符" if billed else "完成", "#999999")
        if det:
            self.lbl_hint.configure(text=f"检测源语言：{lang_name(det)}")
        self.scroll.refresh()

    def _on_card_err(self, target, msg):
        self._set_card_status(self.cards[target], "失败", ERR_FG)
        self._set_card_text(target, msg)
        self.scroll.refresh()

    def _on_quota(self, target, msg):
        self.set_status(msg, err=True)
        for t, c in self.cards.items():
            if c["status"].cget("text") == "…":
                self._set_card_status(c, "额度耗尽", ERR_FG)
        self._on_done()

    def _on_done(self):
        if not self._busy:
            return
        self._busy = False
        self.btn_go.configure(text="翻译（Ctrl+Enter）", bg=TITLE_BG)
        if any(c["status"].cget("text") not in ("…", "待翻译") for c in self.cards.values()):
            self.set_status("完成" if self.lbl_status.cget("text").startswith("翻译中") else
                            self.lbl_status.cget("text"))
        self._refresh_usage_async()
        self.scroll.refresh()

    def _refresh_usage_async(self, force=False):
        now = time.time()
        if not force and now - self._last_usage_fetch < 60:
            return
        self._last_usage_fetch = now
        if not self.key:
            self.lbl_usage.configure(text="未设置 key")
            return
        key, host = self.key, pick_host(self.key, self.cfg.get("host_mode", "auto"))

        def run():
            try:
                c, l = fetch_usage(key, host)
                self.msgq.put(("usage", c, l))
            except ApiError:
                self.msgq.put(("usage_fail",))
        threading.Thread(target=run, daemon=True).start()

    def _on_usage(self, count, limit):
        self.lbl_usage.configure(text=fmt_usage(count, limit))
        pct = count * 100 // max(limit, 1) if limit else 0
        color = "#9fb3c8"
        if pct >= 80:
            color = "#f39c12"
        if pct >= 95:
            color = "#e67e22"
        self.lbl_usage.configure(fg=color)
        # 药丸只在用量告急（≥80%）时长出百分比徽标，平时保持一粒「译」
        badge = f"{pct}%" if (limit and pct >= 80) else ""
        self.lbl_pill_usage.configure(text=badge, fg="#f39c12" if pct < 95 else "#e67e22")
        if self._pill_mode and badge:                # 宽度自适应（QuadTodo P-002）
            self._pill_w = self._pill_w_now()
            sw = self.root.winfo_screenwidth()
            self.root.geometry(f"{self._pill_w}x{PILL_H}+{sw - self._pill_w}+{self._pill_y}")

    # ---- 复制

    def _copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()               # 确保进程内剪贴板即时对外生效
        self.set_status("已复制到剪贴板")

    def copy_one(self, target):
        text = self.cards[target]["text"].get("1.0", "end-1c").strip()
        if text:
            self._copy(text)

    def copy_all(self):
        results = [(t, self.cards[t]["text"].get("1.0", "end-1c").strip())
                   for t in self.cfg["targets"]]
        text = format_copy_all(results)
        if text:
            self._copy(text)

    def clear_input(self):
        self.input.delete("1.0", "end")
        self._update_estimate()
        self.lbl_hint.configure(text="")

    # ---- 弹窗：设置 / 语言选择 / 历史

    def _center(self, win, w, h):
        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    def open_settings(self):
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.lift()
            return
        win = tk.Toplevel(self.root)
        self._settings = win
        win.title("设置")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        self._center(win, 500, 446)   # 500：六个 mini 按钮一行放得下——440 时「关闭」被 pack 挤成 1px（P-009）

        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(row, text="DeepL API Key", bg=BG, fg="#333333",
                 font=(FONT, 10, "bold")).pack(anchor="w")
        self.lbl_key_state = tk.Label(row, text=key_masked(self.key), bg=BG, fg="#666666",
                                      font=(FONT, 9))
        self.lbl_key_state.pack(anchor="w")
        self.ent_key = tk.Entry(win, show="•", font=(FONT, 10), relief="flat",
                                highlightthickness=1, highlightbackground="#d0d4d8",
                                highlightcolor=TITLE_BG)
        self.ent_key.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(win, text="粘贴后点「保存设置」覆盖旧 key；点「删除 key」移除。key 只存本地 .deepl-key，绝不入库。",
                 bg=BG, fg="#999999", font=(FONT, 8), wraplength=466, justify="left"
                 ).pack(fill="x", padx=14)

        hr = tk.Frame(win, bg=BG)
        hr.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(hr, text="host", bg=BG, fg="#333333", font=(FONT, 10, "bold")).pack(anchor="w")
        self.var_host = tk.StringVar(value=self.cfg.get("host_mode", "auto"))
        hrow = tk.Frame(win, bg=BG)
        hrow.pack(fill="x", padx=14)
        for val, label in (("auto", "自动（按 :fx 后缀）"), ("free", "免费档 api-free"), ("pro", "付费 api.deepl")):
            tk.Radiobutton(hrow, text=label, variable=self.var_host, value=val,
                           bg=BG, font=(FONT, 9)).pack(side="left", padx=(0, 10))

        hr2 = tk.Frame(win, bg=BG)
        hr2.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(hr2, text="行为", bg=BG, fg="#333333", font=(FONT, 10, "bold")).pack(anchor="w")
        self.var_hist = tk.BooleanVar(value=bool(self.cfg.get("save_history")))
        self.var_quality = tk.BooleanVar(value=bool(self.cfg.get("model_quality")))
        self.var_auto = tk.BooleanVar(value=bool(self.cfg.get("auto_translate")))
        self.var_top = tk.BooleanVar(value=bool(self.cfg.get("topmost")))
        self.var_autostart = tk.BooleanVar(value=autostart_enabled())  # 唯一事实源=注册表，不落 config.json
        for label, var, tip in (
                ("保存历史记录（历史即翻译缓存）", self.var_hist, ""),
                ("高质量模式（next-gen 模型，质量优先）", self.var_quality, ""),
                ("输入停止后自动翻译（防抖 1.5s，默认关）", self.var_auto, ""),
                ("窗口置顶", self.var_top, ""),
                ("开机自启（登录后缩成右缘药丸）", self.var_autostart, "")):
            tk.Checkbutton(win, text=label, variable=var, bg=BG, font=(FONT, 10),
                           anchor="w").pack(fill="x", padx=14)

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=14, pady=(12, 14))

        def mini(text, cmd):
            b = tk.Label(btns, text=text, bg="#e4e6e9", fg="#333333", font=(FONT, 9),
                         padx=10, pady=3, cursor="hand2")
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e: cmd())
        mini("保存设置", self._apply_settings)
        mini("删除 key", self._delete_key)
        mini("清空历史", self._clear_history)
        mini("清空缓存", self._clear_cache)
        mini("刷新语言清单", self._refresh_langs)
        mini("关闭", win.destroy)

    def _apply_settings(self):
        new_key = self.ent_key.get().strip()
        if new_key:                          # 留空保存 = 维持现状，删除请用「删除 key」
            self.key = new_key
            save_key(new_key)
        self.cfg["save_history"] = bool(self.var_hist.get())
        self.cfg["model_quality"] = bool(self.var_quality.get())
        self.cfg["auto_translate"] = bool(self.var_auto.get())
        self.cfg["topmost"] = bool(self.var_top.get())
        self.cfg["host_mode"] = self.var_host.get()
        save_config_file(self.cfg)
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self._update_pin()
        _as_err = None           # 自启差量生效：勾选状态与注册表翻转了才写（U-004）
        try:
            if bool(self.var_autostart.get()) != autostart_enabled():
                (autostart_enable if self.var_autostart.get() else autostart_disable)()
        except OSError as e:
            _as_err = e          # 留到弹窗关闭后统一报，免被「设置已保存」覆盖
        self.lbl_key_state.configure(text=key_masked(self.key))
        self._update_estimate()
        self._refresh_usage_async(force=True)
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.destroy()
        if _as_err is None:
            self.set_status("设置已保存")
        else:
            self.set_status(f"已保存，但开机自启写入失败：{_as_err}", err=True)

    def _delete_key(self):
        if messagebox.askokcancel("删除 key", "确定删除本机保存的 API key？（不影响你的 DeepL 账号，仅清掉本地 .deepl-key）"):
            self.key = None
            save_key(None)
            self.lbl_key_state.configure(text=key_masked(None))
            self.lbl_usage.configure(text="未设置 key")
            self.set_status("已删除本机 key")

    def _clear_history(self):
        if messagebox.askokcancel("清空历史", f"确定清空全部 {len(self.history)} 条历史记录？（不影响翻译缓存）"):
            self.history.clear()
            save_history_file(self.history)
            if self._history_win is not None and self._history_win.winfo_exists():
                self._history_win.destroy()
            self.set_status("历史记录已清空")

    def _clear_cache(self):
        if messagebox.askokcancel("清空缓存", "确定清空翻译缓存？（缓存命中可省额度，清空后重复翻译将重新计费）"):
            self.cache.clear()
            save_cache_file(self.cache)
            self._update_estimate()
            self.set_status("翻译缓存已清空")

    def _refresh_langs(self):
        if not self.key:
            self.set_status("先设置 key 才能拉取在线语言清单", warn=True)
            return
        self.set_status("正在拉取语言清单…")
        key, host = self.key, pick_host(self.key, self.cfg.get("host_mode", "auto"))

        def run():
            try:
                langs = fetch_target_languages(key, host)
                self.msgq.put(("langs", langs))
            except ApiError as e:
                self.msgq.put(("status", f"拉取失败：{e}"))
        threading.Thread(target=run, daemon=True).start()

    # ---- 语言选择器

    def available_langs(self):
        if self._langs_cache:
            return [(c, n) for c, n, _f in self._langs_cache]
        return FALLBACK_LANGS

    def open_picker(self):
        if self._picker is not None and self._picker.winfo_exists():
            self._picker.lift()
            return
        win = tk.Toplevel(self.root)
        self._picker = win
        win.title("选择常驻目标语言")
        win.configure(bg=BG)
        win.transient(self.root)
        self._center(win, 380, 460)
        draft = {t: lang_name(t) for t in self.cfg["targets"]}

        top = tk.Frame(win, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(top, text="搜索：", bg=BG, fg="#666666", font=(FONT, 9)).pack(side="left")
        ent = tk.Entry(top, font=(FONT, 10), relief="flat", highlightthickness=1,
                       highlightbackground="#d0d4d8", highlightcolor=TITLE_BG)
        ent.pack(side="left", fill="x", expand=True)
        tk.Label(win, text=f"已选 {len(draft)}/{TARGETS_MAX}（点列表行勾选/取消）",
                 bg=BG, fg="#999999", font=(FONT, 8), anchor="w").pack(fill="x", padx=12)
        lbl_count = win.winfo_children()[-1]

        sf = ScrollFrame(win)
        sf.pack(fill="both", expand=True, padx=12, pady=4)
        rows = {}

        def redraw(filter_=""):
            for w in sf.inner.winfo_children():
                w.destroy()
            f = filter_.strip().lower()
            for code, name in self.available_langs():
                hay = f"{code} {name}".lower()
                if f and f not in hay:
                    continue
                on = code in draft
                r = tk.Label(sf.inner, text=f"{'✔' if on else '　'}  {name}  {code}",
                             bg="#dfe3ea" if on else BG, fg="#333333", font=(FONT, 10),
                             anchor="w", padx=8, pady=2)
                r.pack(fill="x")
                r.bind("<Button-1>", lambda e, c=code, n=name: toggle(c, n))
                rows[code] = r
            sf.refresh()

        def toggle(code, name):
            if code in draft:
                del draft[code]
            else:
                if len(draft) >= TARGETS_MAX:
                    messagebox.showinfo("提示", f"常驻目标语最多 {TARGETS_MAX} 个（保持界面干净）", parent=win)
                    return
                draft[code] = name
            lbl_count.configure(text=f"已选 {len(draft)}/{TARGETS_MAX}（点列表行勾选/取消）")
            redraw()

        def apply():
            if len(draft) > TARGETS_MAX:
                return
            order = [c for c, _n in self.available_langs() if c in draft]
            for c in draft:                      # 兜底：动态清单里没有的已选语也保留
                if c not in order:
                    order.append(c)
            self.cfg["targets"] = order
            self.rebuild_chips()
            self.rebuild_cards()
            win.destroy()

        ent.bind("<KeyRelease>", lambda e: redraw(ent.get()))
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=12, pady=(4, 12))
        ok = tk.Label(btns, text="确定", bg=TITLE_BG, fg="white", font=(FONT, 10),
                      padx=16, pady=3, cursor="hand2")
        ok.pack(side="right")
        ok.bind("<Button-1>", lambda e: apply())
        redraw()
        ent.focus_set()
        if self.key and not self._langs_cache:
            self._refresh_langs()

    # ---- 历史弹窗

    def open_history(self):
        if self._history_win is not None and self._history_win.winfo_exists():
            self._history_win.lift()
            return
        win = tk.Toplevel(self.root)
        self._history_win = win
        win.title(f"历史记录（最近 {min(len(self.history), 200)} 条）")
        win.configure(bg=BG)
        win.transient(self.root)
        self._center(win, 520, 420)
        if not self.cfg.get("save_history"):
            tk.Label(win, text="当前已关闭历史记录（设置里可开启）", bg=BG, fg="#999999",
                     font=(FONT, 9)).pack(fill="x", padx=12, pady=(10, 0))
        data = list(reversed(self.history[-200:]))
        lb = tk.Listbox(win, font=(FONT, 9), relief="flat", bg="white",
                        highlightthickness=1, highlightbackground="#d0d4d8",
                        activestyle="none")
        lb.pack(fill="both", expand=True, padx=12, pady=10)
        for h in data:
            lb.insert("end", f"{h.get('ts', '')[5:16]}  [{lang_name(h.get('target', ''))}]  "
                             f"{h.get('source', '')[:28]} → {h.get('result', '')[:28]}")

        def backfill(_e):
            sel = lb.curselection()
            if not sel:
                return
            h = data[sel[0]]
            self.input.delete("1.0", "end")
            self.input.insert("1.0", h.get("source", ""))
            self._update_estimate()
            win.lift()
        lb.bind("<Double-Button-1>", backfill)
        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=12, pady=(0, 12))
        tk.Label(bar, text="双击条目回填原文", bg=BG, fg="#999999", font=(FONT, 8)).pack(side="left")
        clr = tk.Label(bar, text="清空历史", bg="#e4e6e9", fg=ERR_FG, font=(FONT, 9),
                       padx=10, pady=2, cursor="hand2")
        clr.pack(side="right")
        clr.bind("<Button-1>", lambda e: (self._clear_history_with_win(win)))

    def _clear_history_with_win(self, win):
        if messagebox.askokcancel("清空历史", f"确定清空全部 {len(self.history)} 条历史记录？"):
            self.history.clear()
            save_history_file(self.history)
            win.destroy()
            self.set_status("历史记录已清空")

    # ---- 杂项

    def toggle_topmost(self):
        self.cfg["topmost"] = not bool(self.cfg.get("topmost"))
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self._update_pin()

    def _update_pin(self):
        on = bool(self.cfg.get("topmost"))
        self.lbl_pin.configure(text="钉", fg="#2ecc71" if on else "#c8d0d8")

    def set_status(self, text, warn=False, err=False):
        self.lbl_status.configure(text=text, fg=ERR_FG if err else ("#b9770e" if warn else "#8a94a0"))

    def quit_app(self):
        if self._pill_mode:                  # 药丸态退出：把展开位换算回去存档
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w, h = self._normal_size
            self.cfg["window"] = {"x": max(0, sw - w), "y": max(0, min(self._pill_y, sh - h)),
                                  "w": w, "h": h}
        else:
            self.cfg["window"] = {"x": self.root.winfo_x(), "y": self.root.winfo_y(),
                                  "w": self.root.winfo_width(), "h": self.root.winfo_height()}
        self.cfg["pill_y"] = self._pill_y
        save_config_file(self.cfg)
        save_cache_file(self.cache)
        save_history_file(self.history)
        self.root.destroy()


# ---------------------------------------------------------------- 数据文件落盘封装（便于测试重定向）

def save_config_file(cfg):
    save_json(CONFIG_FILE, cfg)


def save_cache_file(cache):
    save_json(CACHE_FILE, cache)


def save_history_file(history):
    save_json(HISTORY_FILE, history)


# ---------------------------------------------------------------- 自检（不碰真实数据、不发网络请求）

def run_smoke():
    import tempfile
    global CONFIG_FILE, KEY_FILE, CACHE_FILE, HISTORY_FILE
    tmp = tempfile.mkdtemp(prefix="dq_smoke_")
    CONFIG_FILE = os.path.join(tmp, "config.json")
    KEY_FILE = os.path.join(tmp, ".deepl-key")
    CACHE_FILE = os.path.join(tmp, "cache.json")
    HISTORY_FILE = os.path.join(tmp, "history.json")

    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    # 1 配置 roundtrip + 默认键补全
    cfg = {"targets": ["DE"]}
    save_config_file(cfg)
    cfg2 = load_config()
    check("config roundtrip", cfg2["targets"] == ["DE"] and "save_history" in cfg2 and cfg2["host_mode"] == "auto")

    # 2 key 存取与掩码
    save_key("  abcd1234:fx  ")
    check("key save/strip", load_key() == "abcd1234:fx")
    check("key mask", key_masked("abcd1234:fx") == "已设置（…4:fx）" or key_masked("abcd1234:fx").endswith("4:fx）"))
    save_key(None)
    check("key delete", load_key() is None and key_masked(None) == "未设置")

    # 3 host 选择
    check("host auto fx", pick_host("abc:fx") == HOST_FREE)
    check("host auto pro", pick_host("abcdefg") == HOST_PRO)
    check("host mode free", pick_host("abcdefg", "free") == HOST_FREE)
    check("host override", pick_host("abc:fx", "auto", "http://127.0.0.1:9999") == "http://127.0.0.1:9999")
    check("build_url", build_url(HOST_PRO, "/v2/translate") == "https://api.deepl.com/v2/translate")

    # 4 缓存键与裁剪
    k1 = cache_key("hello", "ZH", None)
    k2 = cache_key("hello", "JA", None)
    k3 = cache_key("hello", "ZH", "quality_optimized")
    check("cache key distinct", k1 != k2 and k1 != k3 and k1 == cache_key("hello", "ZH", None))
    big = {f"k{i}": {"ts": i} for i in range(20)}
    check("cache prune", len(cache_prune(big, limit=10)) == 10 and
          set(cache_prune(big, limit=10)) == {f"k{i}" for i in range(19, 9, -1)})

    # 5 历史 trim 与开关
    hist = []
    for i in range(HISTORY_MAX + 30):
        append_history(hist, {"ts": str(i), "source": "s", "target": "ZH", "detected": "", "result": "r"})
    check("history trim", len(hist) == HISTORY_MAX and hist[0]["ts"] == "30")

    # 6 兜底语言清单
    codes = [c for c, _n in FALLBACK_LANGS]
    check("fallback langs", len(codes) >= 30 and len(codes) == len(set(codes)))
    check("fallback essentials", all(c in codes for c in ("ZH", "EN-US", "JA", "DE", "FR", "RU")))
    check("lang names cover fallback", all(lang_name(c) != c for c in codes))
    check("lang name fallback", lang_name("XX-QQ") == "XX-QQ")

    # 7 错误分类
    check("err 456", isinstance(classify_http_error(456)[0]("x"), QuotaError))
    check("err 400", isinstance(classify_http_error(400)[0]("x"), BadRequest))
    check("err 403", isinstance(classify_http_error(403)[0]("x"), AuthError))
    check("err 429", classify_http_error(429)[0] is ApiError)
    check("err 500", classify_http_error(500)[0] is ApiError)

    # 8 翻译重试纪律（注入 fake，无网络）：429 重试后成功
    calls = []

    def flaky(key, host, method, path, payload=None):
        calls.append(1)
        if len(calls) < 3:
            raise ApiError("过载", status=429)
        return {"translations": [{"text": "你好", "detected_source_language": "EN", "billed_characters": 5}]}
    tr = translate_text("k", HOST_FREE, "hello", "ZH", request_fn=flaky)
    check("retry 429 then ok", len(calls) == 3 and tr["text"] == "你好")

    calls2 = []

    def quota_now(key, host, method, path, payload=None):
        calls2.append(1)
        raise QuotaError("额度耗尽", status=456)
    try:
        translate_text("k", HOST_FREE, "hello", "ZH", request_fn=quota_now)
        check("quota no retry", False)
    except QuotaError:
        check("quota no retry", len(calls2) == 1)

    # 9 payload 纪律：高质量模式带 model_type，且 target_lang/show_billed_characters 在
    seen = {}

    def spy(key, host, method, path, payload=None):
        seen.update(payload or {})
        return {"translations": [{"text": "x", "detected_source_language": "EN", "billed_characters": 1}]}
    translate_text("k", HOST_FREE, "hello", "ZH", model_type="quality_optimized", request_fn=spy)
    check("payload discipline", seen.get("model_type") == "quality_optimized" and
          seen.get("target_lang") == "ZH" and seen.get("show_billed_characters") is True)

    # 10 复制全部格式
    check("copy all fmt", format_copy_all([("JA", "こんにちは"), ("ZH", ""), ("DE", "Hallo")]) ==
          "【日语】こんにちは\n【德语】Hallo")

    # 11 usage 格式
    check("usage fmt", fmt_usage(500000, 500000).startswith("500.0k/500.0k") or "%" in fmt_usage(500000, 500000))

    # 12 数据文件损坏兜底
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        f.write("{broken json")
    check("corrupt cache recover", load_cache() == {} and os.path.exists(CACHE_FILE + ".corrupt"))

    # 13 语言清单回退链：/v3 失败 → /v2?type=target
    def v2only(key, host, method, path, payload=None):
        if path.startswith("/v3"):
            raise ApiError("gone", status=404)
        return [{"language": "DE", "name": "German", "supports_formality": True},
                {"language": "JA", "name": "Japanese", "supports_formality": False}]
    langs = fetch_target_languages("k", HOST_FREE, request_fn=v2only)
    check("langs v2 fallback", [c for c, _n, _f in langs] == ["DE", "JA"]
          and langs[0][2] is True and langs[1][2] is False)

    # 14 /v3 防御性解析：supported_as.translate.target=False 的语种被过滤
    def v3pair(key, host, method, path, payload=None):
        if path.startswith("/v3"):
            return [{"language": "DE", "name": "German",
                     "supported_as": {"translate": {"source": True, "target": True}}},
                    {"language": "EN-US", "name": "English",
                     "supported_as": {"translate": {"target": False}}}]
        raise ApiError("x", status=500)
    langs3 = fetch_target_languages("k", HOST_FREE, request_fn=v3pair)
    check("langs v3 filter", [c for c, _n, _f in langs3] == ["DE"])

    # 15 开机自启（U-004 方案 A）：注册表读写全走 scratch 键，绝不碰真实 Run 键
    cmd = _autostart_cmd()
    check("autostart cmd shape", cmd.startswith('"') and cmd.endswith('" --minimized')
          and '" "' in cmd and ".pyw" in cmd)
    scratch = r"Software\deepl_quick_smoke_test"
    try:
        check("autostart initial off", not autostart_enabled(scratch))
        autostart_enable(scratch)
        check("autostart enable", autostart_enabled(scratch))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, scratch, 0, winreg.KEY_READ) as k:
            stored = winreg.QueryValueEx(k, AUTOSTART_NAME)[0]
        check("autostart stored cmd", stored == cmd)
        autostart_enable(scratch)                     # upsert（文件移动后重存自愈）
        check("autostart upsert", autostart_enabled(scratch))
        autostart_disable(scratch)
        check("autostart disable", not autostart_enabled(scratch))
        autostart_disable(scratch)                    # 幂等：键值已删，静默成功
        check("autostart disable idempotent", not autostart_enabled(scratch))
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, scratch)
        except OSError:
            pass

    # 16 单实例互斥（防自启+手动双开叠出两枚药丸）；scratch 名不与真实运行实例冲突
    mname = f"deepl_quick_smoke_{os.getpid()}"
    check("single instance first", acquire_single_instance(mname) is True)
    check("single instance second", acquire_single_instance(mname) is False)

    passed = sum(1 for _n, ok in results if ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"deepl-quick smoke: {passed}/{len(results)} passed (数据目录: {tmp})")
    return 0 if passed == len(results) else 1


def main():
    if not acquire_single_instance():
        return                   # 已有实例在跑（自启的那枚药丸就在右缘）——静默退出
    root = tk.Tk()
    app = App(root)
    if "--minimized" in sys.argv:
        root.update_idletasks()  # 先让 _restore_window 的 geometry 落地，折叠取到的尺寸才真实
        app._enter_pill(force=True)   # force：登录启动时指针可能恰在窗区，不许弹回全窗
    root.mainloop()


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(run_smoke())
    main()

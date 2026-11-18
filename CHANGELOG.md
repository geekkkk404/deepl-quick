# Changelog / 更新日志

All notable changes to deepl-quick are documented here.
本文件记录 deepl-quick 的全部重要变更。

## v0.3.9 — 2026-11-18

- Fixed a deeper always-on-top failure mode caught live: the pill can end up **below ordinary windows while its topmost style bit still reads "on"** (observed after an OS-level window-management transition; three independent proofs — z-order enumeration, hit-testing and screen capture — showed the pill buried for 20+ minutes while the self-heal read the bit, believed "topmost", and never re-asserted). The poll now checks reality in addition to the badge: a center hit-test must land on the window itself; if an ordinary window wins the hit, the topmost band is re-asserted and a one-line forensic note is written (once per event) so a recurrence can be correlated with system events. The hit-test deliberately exempts topmost-band neighbors — the pill does not fight its peers, it only refuses to be buried under ordinary windows.
  修复一种实机抓到的更深层置顶失效：药丸可能已落到普通窗口之下、而其 topmost 样式位仍读作「开」（某次系统级窗口管理转换之后实测；z 序枚举、命中测试、屏幕抓图三方互证被埋 20+ 分钟，自愈读位判「仍置顶」故永不重申）。轮询自愈现在除读位外还查现实：窗中心命中测试必须命中自己；若普通窗口赢下命中，即重申置顶带并落一条每事件一次的取证日志，供复发时与系统事件对时归因。命中测试刻意豁免 topmost 带邻居——药丸不与同类争顶，只拒绝被普通窗口埋葬。
- Note: this state cannot be forged through public APIs — the system silently filters SetWindowLong bit-writes for windows outside the topmost band and keeps the invariant across minimize/restore (both probed) — so it can only come from OS-level transitions (RDP reconnect / sleep-resume / fullscreen switch are the candidate triggers), and the probe therefore validates the new branch with a real demotion plus a patched bit-read instead.
  附注：该状态无法经公开 API 伪造——系统对带外窗口静默过滤 SetWindowLong 的位写入，且最小化/还原全程维持不变量（均已实测）——说明它只能来自 OS 级转换（RDP 重连 / 睡眠唤醒 / 全屏切换为候选触发源），探针因此以「真实降级＋位读打桩」验证新分支。
- Verified: smoke 77→**78**/78 (invalid-handle contract for the new detector); headless probe 18/18 (real demotion heals via the original branch; stale-bit simulation heals via the new branch with exactly one forensic line per event; dialogs-open pause and resume per P-016; healthy-state geometry untouched). The fix was additionally checked against the real diseased window before it self-resolved.
  验证：smoke 77→**78**/78（新检测器非法句柄契约）；无头探针 18/18（真实降级走原分支自愈；位残留模拟走新分支且每事件恰一条取证日志；弹窗打开期自愈暂停、关闭恢复（P-016）；健康态几何零扰动）。修复曾对真实病灶窗口先行验证（其自行消退前）。

## v0.3.8 — 2026-11-17

- New optional **keep-alive watchdog**: tick it in settings and a Windows scheduled task (no admin needed) revives the pill after an unexpected process death — the two post-mortems in the ledger both showed the process being hard-killed from outside during power-transition windows, leaving zero Python-level or WER traces, so revival (not prevention) is the only practical strategy. Checks run every 30 minutes as a safety net, instantly on standby-resume (Kernel-Power 507 event trigger), and the checker is a short-lived `--watchdog-check` instance that exits within seconds — the watchdog itself needs no babysitting because the schedule belongs to the OS, which terminates the "who watches the watchdog" recursion. Deliberately closing the window is respected: the revive decision reads the forensic log's last app-written line and skips when it says `exit: clean`. The task lives visibly under `\deepl-quick\watchdog` in Task Scheduler; unticking removes it; startup self-heals the task if it was deleted externally while enabled.
  新增可选**看门狗保活**：设置勾选即注册 Windows 计划任务（免管理员），进程意外死亡后自动拉起——账本两次尸检都指向「待机转换窗口内被外部硬杀、不留任何 Python 级或 WER 级痕迹」，防死不可行，复活是唯一务实策略。检查每 30 分钟兜底一次、待机唤醒（Kernel-Power 507 事件触发）即时一次；检查体是秒级退出的 `--watchdog-check` 短命实例——看门狗自身无需保活，调度权在 OS 手里，「谁看门看门狗」的递归在操作系统层终结。主动关闭被尊重：拉活判据读取证日志末条应用行，`exit: clean` 即跳过。任务在任务计划程序 `\deepl-quick\watchdog` 下透明可见，取消勾选即注销；勾选状态下任务被外部手删，下次启动自愈补注册。
- Settings dialog: 8th checkbox (watchdog) plus a live status line ("Watchdog task: registered / not registered") that queries the actual scheduler state when the dialog opens — the config value is never taken at face value. Section paddings were tightened to keep the dialog inside short screens, and the dialog height now adapts (756 ceiling → shrinks on short displays), with `_center` clamping against the real screen **and** re-clamping after map once the title-bar decoration height is measurable — previously on a 768-line display the dialog's button rows could land off-screen.
  设置弹窗：第 8 个勾选框（看门狗）+ 实时状态行（「看门狗任务：已注册 / 未注册」，打开弹窗时真查任务计划程序，不信任 config 纸面值）。收紧分节 padding 控制高度预算，弹窗高度改为自适应（756 封顶、矮屏收缩），`_center` 改为对真实屏幕钳制并在映射后（标题栏装饰高度可实测时）再钳一拍——修复矮屏（768 线）下弹窗底部按钮行出屏的老问题。
- Forensic log etiquette: watchdog audit lines are tagged `wd-check` and skipped by the revive decision's tail reader; revived starts are logged as `startup (revived)` so post-mortems can tell revivals from manual starts.
  取证日志礼节：看门狗审计行带 `wd-check` 标记，拉活判据读末行时跳过它们；看门狗拉起的启动记为 `startup (revived)`，尸检可区分「复活体」与「手动启动」。
- Verified: smoke 56→**77**/77 (watchdog revive-decision pure functions, log-tail reader, task-XML shape incl. escaped 507 subscription, and a real schtasks register/query/delete roundtrip on a scratch task name without arming triggers); headless geometry probe 12/12 on a real 1366×768 display (8 checkboxes + status line + both button rows inside the dialog, longest zh/en label width-asserted, dialog outer frame fully on-screen); live end-to-end on the developer machine: hard-kill → task run → revived within a beat and outlived the task's execution window; clean ✕ → task run → correctly skipped.
  验证：smoke 56→**77**/77（拉活判据纯函数、日志末行读取、任务 XML 形状含转义的 507 订阅、scratch 任务名的真实 schtasks 注册/查询/注销 roundtrip 且不武装触发器）；1366×768 真实矮屏无头几何探针 12/12（8 勾选+状态行+两行按钮全部界内、双语最长文案宽度点名断言、弹窗外框完整在屏）；开发机实机端到端：硬杀→任务触发→一拍内复活且存活逾任务执行窗口；干净 ✕→任务触发→正确跳过。

## v0.3.7 — 2026-11-16

- **Long translations are fully visible now**: result cards auto-fit their height to the translated text (rewrapping on window resize) instead of clipping to two fixed lines — previously there was no way to see the rest of a longer translation at all.
  **长译文完整可见**：结果卡片高度随译文自适应（窗口缩放后重排）——旧版固定两行，长译文被硬截断且无任何途径查看剩余内容。
- New **temporary pause button** on each card (⏸ / ▶): pause a language for this round to save quota, restore with one click — the pinned list itself never changes, and re-translating after resuming hits the cache at zero cost. Pause state is session-only; all-paused shows a hint instead of firing requests.
  卡片新增**临时停用按钮**（⏸ / ▶）：让某门语言本次不参与翻译以节省字符额度，一键恢复——常驻清单不动，恢复后重翻走缓存零消耗。停用态仅本会话有效；全部停用时空转提示、不发请求。
- Settings dialog widened 500→580: English checkbox labels no longer clip at the right edge (longest label now point-asserted via font metrics in the headless probe); the "Auto-translate" label was tightened on both UI languages.
  设置弹窗加宽 500→580：英文勾选框文案不再被右缘截断（探针新增 font.metrics 点名断言）；「自动翻译」勾选文案中英同步精简。
- Fixed: the always-on-top self-heal read Tk's internal cache, which never notices when an external program demotes the window style via Win32 — it now reads the real window style bits (GetWindowLongW / WS_EX_TOPMOST) and re-asserts for real. A headless probe reproduces the external demotion and verifies recovery within two poll beats.
  修复：置顶自愈此前读 Tk 内部缓存——外部程序经 Win32 直接降级时永不触发重申；现在读取真实窗口样式位（GetWindowLongW / WS_EX_TOPMOST）。无头探针复现真实外部降级并验证两拍内自愈。
- Verified: smoke 56/56, headless probe 117/117 (point-named assertions for ⧉/⏸/× per card, pause/resume wiring, offline partial-pause end-to-end, dialog checkboxes/radios at zh/en).
  验证：smoke 56/56，无头探针 117/117（逐卡点名 ⧉/⏸/×、停用/恢复接线、离线部分停用端到端、双语弹窗勾选框/单选行断言）。

## v0.3.6 — 2026-11-15

- Title-bar hardening: growing version strings plus the usage badge could crush the last title-bar button to invisibility; the window title now truncates gracefully instead, and the title/usage fonts stepped down one size to fit.
  标题栏加固：版本串变宽＋用量徽标同框时，最后的字形按钮（钉）可能被挤到不可见；现在空间不足时优雅裁剪标题文本，标题/用量徽标字号各降一号。
- The **Translate** button is now just "翻译 / Translate" — the Ctrl+Enter hint lives in the status bar (and the README).
  **翻译**按钮文案精简为「翻译 / Translate」——Ctrl+Enter 提示由状态栏与 README 承载。
- Detection ("Detected: EN-US") and cost-estimate hints moved from the button row into the status bar, which has dedicated space; under high-DPI the old top-row placement could crush them to a sliver.
  检测（「检测: EN-US」）与预估消耗提示从按钮行迁入状态栏（有专属空间）——高 DPI 下原位置曾把它们挤成细条。
- Fixed: the bottom status bar could be squeezed to zero height when many cards existed (the scroll area claimed all space first); it now docks before the scroll area.
  修复：卡片较多时底部状态栏可能被压成 0 高（滚动区先占光空间）；状态栏现在先停靠底部。
- Settings dialog resized (500×756) so both button rows are fully visible under high-DPI rendering; the second row was half-clipped at 740 and below.
  设置弹窗高度按高 DPI 渲染实需校准（500×756）——旧高度下第二行按钮被裁掉一半。

## v0.3.5 — 2026-11-15

- The **＋ Language** button now shares the button row with Translate / Clear / Copy-all (same styling), freeing an entire vertical row for the result-card list.
  **「＋语言」按钮并入按钮行**（与翻译/清空/复制全部同排同款样式），整行垂直空间让给结果卡片列表。
- Verified: smoke 53/53, headless probe 33/33 — all four bar buttons point-named inside the window at both the default 560px and the minimum 420px width.
  验证：smoke 53/53，无头探针 33/33——四个按钮在默认 560 宽与最小 420 宽下逐一点名断言在界内。

## v0.3.4 — 2026-11-15

- Fixed: Settings / History / Language-picker dialogs could get buried under the main window — the v0.3.3 self-heal re-asserted main-window always-on-top every 150 ms, pushing the owned dialogs below it. Self-heal now pauses entirely while any dialog is open.
  修复：设置 / 历史 / 选语言弹窗可能被主窗压住——v0.3.3 的自愈每 150ms 重申主窗置顶，把属主关系在其之上的弹窗挤了下去。现在任何弹窗打开期间自愈整体暂停。
- New privacy switches in Settings → Behavior: **"Clear translation cache on restart"** and **"Clear history on restart"** (both off by default). Clearing happens at next launch — including residue left behind by crashed sessions, which plain "clear on exit" would miss.
  设置 → 行为区新增隐私开关：**「重启时清空翻译缓存」**与**「重启时清空历史记录」**（默认均关）。清空发生在下次启动时——崩溃死亡留下的残留同样会被清掉，这是「退出时清空」做不到的。
- Privacy audit: `cache.json` and `history.json` are the only local files that persist user text (note: the cache stores full source+translation text even when "Save history" is off — hence the cache switch). The crash forensics log contains metadata only (timestamps / pid / version / exception stack, no user text). OS-level exposures (Windows clipboard history incl. Win+V cloud sync, pagefile/hibernation) are inherent to the platform and documented in the README.
  隐私探查结论：本地持久化用户文本的只有 `cache.json` 与 `history.json` 两处（注意：即便关闭「保存历史」，缓存也存全量原文+译文——这正是缓存开关的意义）；取证日志仅元数据（时间戳/pid/版本/异常栈，无用户文本）；OS 层暴露面（Windows 剪贴板历史含 Win+V 云同步、休眠/页面文件）属平台固有，已在 README 说明。

## v0.3.3 — 2026-11-15

- **Crash forensics**: the windowed runtime (`pythonw`) exits silently and leaves no trace in the Event Log or WER, which made occasional disappearances impossible to autopsy. Startup, Tk callback exceptions, fatal errors and clean exits are now appended to `%TEMP%\dq_exit.log`.
  **崩溃取证**：pythonw 静默退出在事件日志/WER 均无痕迹，工具「偶尔失踪」历来无法尸检。现在启动、Tk 回调异常、致命错误、干净退出都会逐行追加到 `%TEMP%\dq_exit.log`。
- **Self-healing pill**: the 150 ms background poll now re-asserts always-on-top (when enabled) and clamps the window back into the primary screen, so resolution changes / RDP reconnects / sleep-resume can no longer leave the pill off-screen or buried under other windows.
  **药丸自愈**：150ms 轮询顺带重申置顶（开启时）并把窗口夹回主屏内——分辨率变化 / RDP 重连 / 睡眠唤醒不再可能让药丸滞留屏外或沉底被盖。
- Verified: smoke 52/52 (+5 new assertions), headless geometry probe 22/22 (offscreen heal, topmost re-assert, untouched in-screen window).
  验证：smoke 52/52（新增 5 项断言），无头几何探针 22/22（屏外愈合、置顶重申、界内不动几何）。

## v0.3.2 — 2026-11-15

- Redesigned target-language management: the redundant inline language chips are gone — the result card list itself is the language list. The row below the editor now only keeps the **＋ Language** button, which can no longer be pushed out of the window no matter how many languages are pinned.
  重做目标语言管理：整排语言标签退役——结果卡片列表本身就是语言清单，输入框下只保留**「＋语言」**按钮，无论勾多少门语言都不可能再被挤出窗口。
- Each card header now has an **×** next to the copy icon to remove that target language (mistakenly removed ones re-translate from cache at zero cost).
  卡片头部复制图标旁新增**「×」**，点击即移除该目标语言（误删后重新翻译走缓存、零消耗）。
- The per-language copy entry is now an icon (⧉) instead of text, language-neutral across UI locales.
  逐语种复制入口由文字改为复制图标（⧉），跨界面语言通用。
- Pinned-language cap raised from 8 to 16 (the card list can take it now).
  常驻目标语言上限 8 → 16（卡片列表已能承载）。

## v0.3.1 — 2026-11-14

- Fixed: the per-language **Copy** button on result cards had been invisible since v0.1 — the scroll container never synced its content width to the viewport, pushing the button past the visible area (measured ~133px out).
  修复：结果卡片的逐语种「复制」按钮自 v0.1 起从未显示——滚动容器未把内容宽度同步到视口，按钮被整体裁出可视区（实测超出约 133px）。
- The per-language copy entry is now styled as an actual button (white with border), clearly visible on every card.
  逐语种「复制」入口按钮化（白底描边），每张卡片上一眼可见。
- Scroll container now keeps its content width in sync with the viewport; the language picker benefits as well.
  滚动容器内容宽度与视口保持同步；语言选择器弹窗同享此修复。

## v0.3 — 2026-11-13

- Multilingual UI (Chinese / English): follows the system language, switchable in Settings, applies instantly — no restart needed.
  界面多语言（中文 / English）：自动跟随系统语言，可在设置中强制指定，切换即时生效、无需重启。
- Target languages now display native names (Deutsch / 日本語 / Français…).
  目标语言清单改用原生名显示（Deutsch / 日本語 / Français…）。
- Language list refresh verified against the live API: 111 target languages.
  语言清单在线刷新实测：111 门目标语言。
- Windows portable package (bundled Python runtime) attached to this release.
  本发行版附带 Windows 绿色免安装包（内嵌 Python 运行时）。
- Fixed: Settings dialog buttons could be squeezed invisible under the EN locale; a status-bar message was silently dropped on language-fetch failure.
  修复：英文界面下设置弹窗按钮可能被挤成不可见；语言清单拉取失败时状态栏消息被静默丢弃。

## v0.2 — 2026-11-12

- Optional auto-start: registers an HKCU Run key (no admin required); at login the window starts minimized as the edge pill. Disable anytime from Task Manager → Startup apps.
  可选开机自启：写入 HKCU Run 键（免管理员），登录后直接缩成贴边药丸；可随时在任务管理器「启动应用」中停用。
- Single-instance guard: launching twice never stacks two pills.
  单实例保护：重复启动不会叠出两枚药丸。

## v0.1 — 2026-11-12

- Initial release.
  首个版本。
- Edge pill that auto-collapses and expands on hover; frameless always-on-top window with drag / resize / position memory.
  贴边药丸（鼠标离开自动折叠、悬停展开）；无边框置顶小窗，支持拖动 / 调整大小 / 位置记忆。
- Auto source-language detection; pinned target languages (up to 8) with online refresh; one-click copy per language + copy all.
  源语言自动检测；常驻目标语言（上限 8 个）支持在线刷新；逐语种一键复制 + 复制全部。
- Quota-friendly: translation cache (hits cost nothing), usage badge with 80% / 95% warnings, per-request cost estimate, clear stop on quota exhaustion (HTTP 456).
  省额度设计：翻译缓存（命中零消耗）、用量仪表（80% / 95% 变色预警）、请求前消耗预估、额度耗尽明确停机（HTTP 456）。
- Local history (toggleable / clearable, double-click to refill); high-quality model option; 47-item offline self-test (`--smoke`).
  本地历史（可关 / 可清空、双击回填）；高质量模型开关；47 项离线自检（`--smoke`）。

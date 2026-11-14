# Changelog / 更新日志

All notable changes to deepl-quick are documented here.
本文件记录 deepl-quick 的全部重要变更。

## v0.3 — 2026-11-13

- Multilingual UI (Chinese / English): follows the system language, switchable in Settings, applies instantly — no restart needed.
  界面多语言（中文 / English）：自动跟随系统语言，可在设置中强制指定，切换即时生效、无需重启。
- Target languages now display native names (Deutsch / 日本語 / Français…).
  目标语言清单改用原生名显示（Deutsch / 日本語 / Français…）。
- Language list refresh verified against the live API: 111 target languages.
  语言清单在线刷新实测：111 门目标语言。
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

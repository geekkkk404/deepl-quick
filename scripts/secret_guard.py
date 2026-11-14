"""打包产物 secret-guard：扫描绿色包 zip，命中疑似密钥/隐私文件即退出非零（构建失败）。

检查项：
  ① 禁入文件名（key / 配置 / 缓存 / 历史 / 账本 / 可行性分析 / token）——全量文件
  ② 文本文件里的 uuid 形态字符串（DeepL key 主体形态）——二进制 (.pyd/.dll/.exe) 跳过：
     官方 Python 二进制内嵌编译期 GUID（如 e2011457-…），扫二进制必然全量误报
  ③ 文本文件里的 Authorization/DeepL-Auth-Key 后跟十六进制（真 key 形态）——
     源码中的报文头常量 "DeepL-Auth-Key " 后跟引号，不算命中
用法：python scripts/secret_guard.py dist   （扫该目录下全部 *.zip）
"""
import re
import sys
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = {
    ".deepl-key", "config.json", "cache.json", "history.json",
    "开发账本.md", "可行性分析.md", ".gitee-token", "tasks.json",
    "RELEASE.md", "embed.zip",
}
BINARY_EXT = {".pyd", ".dll", ".exe"}
TEXT_RES = [
    (re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
     "uuid-shaped string"),
    (re.compile(rb"DeepL-Auth-Key\s+[0-9a-fA-F]{8}"), "auth header with real key"),
    (re.compile(rb"(?i)authorization['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9]{16,}"),
     "authorization credential"),
]


def scan(zip_path: Path) -> list[str]:
    hits = []
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            base = n.rsplit("/", 1)[-1]
            if base in FORBIDDEN_NAMES:
                hits.append(f"{zip_path.name}: 禁入文件 {n}")
        for info in z.namelist():
            if Path(info).suffix.lower() in BINARY_EXT:
                continue
            data = z.read(info)
            for rx, label in TEXT_RES:
                m = rx.search(data)
                if m:
                    hits.append(f"{zip_path.name}: {info} 命中 {label}: {m.group(0)[:40]!r}")
    return hits


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dist")
    zips = sorted(target.glob("*.zip")) if target.is_dir() else [target]
    if not zips:
        print(f"secret-guard: {target} 下没有 zip 可扫")
        sys.exit(1)
    all_hits: list[str] = []
    for zp in zips:
        all_hits.extend(scan(zp))
    if all_hits:
        print("secret-guard 拦截：")
        for h in all_hits:
            print("  ✗", h)
        sys.exit(1)
    print(f"secret-guard: {len(zips)} 个包全部干净 ✓")


if __name__ == "__main__":
    main()

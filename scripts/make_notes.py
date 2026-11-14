"""从 CHANGELOG.md 抽取指定 tag 的小节作为发行说明（CI 与本地发版共用）。

用法：python scripts/make_notes.py v0.3  →  写出 dist/RELEASE.md
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tag = sys.argv[1]
text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## {re.escape(tag)}\b[^\n]*\n(?:(?!^## ).)*", text, re.M | re.S)
out = ROOT / "dist" / "RELEASE.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(m.group(0).strip() + "\n" if m
               else f"See CHANGELOG.md for {tag} details.\n", encoding="utf-8")
print(f"notes -> {out} ({'matched' if m else 'fallback'})")

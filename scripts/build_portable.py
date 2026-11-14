"""构建 deepl-quick 绿色免安装包（QuadTodo 同款打法）。

用法：
  python scripts/build_portable.py --python-dir <完整CPython目录> --embeddable-zip embed.zip [--out dist]

产出 dist/deepl-quick-v<版本>-win64-portable.zip，结构：
  deepl-quick/
    runtime/            官方 embeddable Python + 从完整安装抽取的 tkinter/tcl
    deepl_quick.pyw     主程序
    deepl-quick.bat     启动器（纯 ASCII 壳，设 TCL/TK_LIBRARY 后拉起 pythonw）
    使用说明.txt

embeddable 包默认不带 tkinter，本脚本从同版本完整安装补齐：
  Lib/tkinter 包、DLLs/_tkinter.pyd、tcl86t.dll、tk86t.dll、zlib1.dll、tcl/ 数据目录，
  并在 python3xx._pth 中加入 Lib 路径。
开机自启为程序内置（设置勾选写 HKCU Run 键），无需外加脚本。
"""
import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEEDED_DLLS = ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll")


def app_version() -> str:
    src = (ROOT / "deepl_quick.pyw").read_text(encoding="utf-8")
    return re.search(r'APP_VERSION = "([^"]+)"', src).group(1)


def fresh_build_dir(pref: str) -> Path:
    """拿到一个可整目录删除重建的构建根；被占用（如 shell 停在里面）就顺位换名。"""
    p = Path(pref)
    for i in range(50):
        cand = p if i == 0 else p.parent / f"{p.name}-{i}"
        try:
            if cand.exists():
                shutil.rmtree(cand)
            cand.mkdir(parents=True)
            return cand
        except (PermissionError, OSError):
            continue
    raise RuntimeError(f"无法创建构建目录：{p} 及其备选均被占用")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-dir", default=None,
                    help="完整 CPython 安装目录（含 Lib/tkinter、DLLs、tcl）；"
                         "默认取当前解释器所在目录（CI 的 setup-python 即满足）")
    ap.add_argument("--embeddable-zip", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--build-dir", default="build/portable")
    args = ap.parse_args()

    py = Path(args.python_dir) if args.python_dir else Path(sys.executable).parent
    if not (py / "Lib" / "tkinter").is_dir() or not (py / "tcl").is_dir():
        sys.exit(f"--python-dir 无效：{py} 缺少 Lib/tkinter 或 tcl（需要完整安装的 CPython，"
                 f"而非 embeddable）；当前解释器：{sys.executable}")

    ver = app_version()
    build_root = fresh_build_dir(args.build_dir)
    pkg = build_root / "deepl-quick"
    pkg.mkdir()
    rt = pkg / "runtime"

    with zipfile.ZipFile(args.embeddable_zip) as z:
        z.extractall(rt)

    shutil.copytree(py / "Lib" / "tkinter", rt / "Lib" / "tkinter")
    for name in NEEDED_DLLS:
        shutil.copy2(py / "DLLs" / name, rt / name)
    shutil.copytree(py / "tcl", rt / "tcl")

    pth = next(rt.glob("python*._pth"))
    text = pth.read_text(encoding="utf-8")
    # 注意：硬编码 python313.zip —— 将来升级 embeddable 到 3.14 需同步改这里
    pth.write_text(text.replace("python313.zip", "python313.zip\nLib"),
                   encoding="utf-8")

    shutil.copy2(ROOT / "deepl_quick.pyw", pkg / "deepl_quick.pyw")
    for f in (ROOT / "scripts" / "portable").iterdir():
        shutil.copy2(f, pkg / f.name)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"deepl-quick-v{ver}-win64-portable.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(pkg.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(pkg.parent).as_posix())

    print(f"OK {zip_path}  {zip_path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

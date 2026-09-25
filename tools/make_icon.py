"""生成打包用的 .ico 图标（与程序内绘制的托盘图标保持一致）。

用法::

    .venv\\Scripts\\python.exe tools\\make_icon.py

输出 assets/agentdeck.ico。只在打包前需要执行，程序运行时不依赖这个文件。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.app import build_app_icon  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "assets" / "agentdeck.ico"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    icon = build_app_icon()
    # Qt 写 ICO 时会按像素尺寸生成多分辨率条目。
    saved = icon.pixmap(256, 256).save(str(OUTPUT), "ico")
    if not saved:
        print(f"写入失败：{OUTPUT}")
        return 1

    print(f"已生成 {OUTPUT}（{OUTPUT.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

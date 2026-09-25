"""AgentDeck 入口。

用法::

    .venv\\Scripts\\python.exe main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 直接运行 main.py 时，把项目根目录加入 sys.path，保证 src 包可导入。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main  # noqa: E402  （必须在 sys.path 调整之后导入）

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

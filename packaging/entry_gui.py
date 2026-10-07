"""PyInstaller 桌面壳入口（薄壳，只调用包里已有的 GUI main()）。

与 `rmqc gui` 等价：把命令行参数原样转给 `road_mqi_checker.gui.app.main`，
`--probe` 探针模式与非探针（开窗）模式都由内核那一侧判定。这里不写业务逻辑。
构建产物 `rmqc-gui.exe`（windowed / console=False）用这个入口。

注意：不带 `--probe` 会进入 Qt 事件循环并阻塞，探针脚本只允许带 `--probe` 跑。
"""

import sys

from road_mqi_checker.gui import app as gui_app

if __name__ == "__main__":
    sys.exit(gui_app.main(sys.argv[1:]))

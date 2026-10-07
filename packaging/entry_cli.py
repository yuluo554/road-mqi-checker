"""PyInstaller 控制台壳入口（薄壳，只调用包里已有的 CLI main()）。

与 `rmqc` 命令完全等价：argparse / 退出码语义 / 内核分发全部在
`road_mqi_checker.cli:main` 那一侧，这里不写任何业务逻辑，只做
`sys.exit(main())`。构建产物 `rmqc.exe` 用这个入口。
"""

import sys

from road_mqi_checker.cli import main

if __name__ == "__main__":
    sys.exit(main())

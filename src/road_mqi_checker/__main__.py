"""支持 `python -m road_mqi_checker <command>`（与 rmqc 同一入口）。"""

import sys

from road_mqi_checker.cli import main

if __name__ == "__main__":
    sys.exit(main())

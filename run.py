"""启动入口（便于 python -m / PyInstaller）。"""

import sys

from app.main import main

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--apply-update":
        from app.updater import apply_update_main

        raise SystemExit(apply_update_main(sys.argv))
    main()

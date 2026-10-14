"""Run the small installed episode consumer through explicit Linux ownership."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.linux_episode import main

if __name__ == "__main__":
    raise SystemExit(main())

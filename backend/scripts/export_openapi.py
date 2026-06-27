from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m scripts.export_openapi <output-path>")
    output_path = Path(sys.argv[1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

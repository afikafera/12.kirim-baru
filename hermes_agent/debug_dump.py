
import json
from pathlib import Path
from datetime import datetime

DEBUG_FILE = Path("/tmp/hermes_debug.log")

def dump_debug(stage, payload):
    try:
        with DEBUG_FILE.open("a", encoding="utf-8") as f:
            f.write("\n")
            f.write("=" * 80 + "\n")
            f.write(f"{datetime.now()}  {stage}\n")
            f.write("=" * 80 + "\n")

            if isinstance(payload, (dict, list)):
                json.dump(payload, f, indent=2, ensure_ascii=False)
            else:
                f.write(str(payload))

            f.write("\n")
    except Exception as e:
        print("dump_debug failed:", e)

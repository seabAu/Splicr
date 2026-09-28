"""Records stub calls to a file so tests can assert what was invoked."""
import json, os
def record(entry):
    path = os.environ.get("STUB_LOG")
    if not path: return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")

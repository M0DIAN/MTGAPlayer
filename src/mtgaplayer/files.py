import json
from pathlib import Path
from uuid import uuid4


def atomic(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(value), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)

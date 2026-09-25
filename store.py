"""File helpers: append-only monthly CSVs in data/, plus the cached working state."""
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import config


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def csv_text(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def partitions(table, data_dir=None):
    """Monthly files of a table, oldest first (2026-09.csv, 2026-09-002.csv, ...)."""
    folder = Path(data_dir or config.DATA_DIR) / table
    return sorted(folder.glob("*.csv"), key=lambda path: (path.stem[:7], int(path.stem[8:] or 1)))


def read_table(table, since_month="", data_dir=None):
    rows = []
    for path in partitions(table, data_dir):
        if path.stem[:7] >= since_month[:7]:
            rows.extend(read_csv(path))
    return rows


def append_rows(table, fields, rows, now, data_dir=None):
    """Append to this month's partition, rolling over before GitHub's file size limit."""
    rows = list(rows)
    if not rows:
        return 0
    folder = Path(data_dir or config.DATA_DIR) / table
    month = utc_text(now)[:7]
    path, part = folder / f"{month}.csv", 1
    while path.exists() and path.stat().st_size >= config.FILE_BYTES:
        part += 1
        path = folder / f"{month}-{part:03d}.csv"
    folder.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def load_state(path=None):
    path = Path(path or config.STATE_FILE)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state, path=None):
    atomic_write(path or config.STATE_FILE, json.dumps(state, ensure_ascii=False, separators=(",", ":")))

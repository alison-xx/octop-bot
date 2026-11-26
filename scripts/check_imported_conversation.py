"""Compare one conversation in two local Octop SQLite databases without printing its contents."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def database(root: Path) -> Path:
    if root.is_file():
        return root
    config = root / "config.json"
    options = json.loads(config.read_text(encoding="utf-8-sig")) if config.exists() else {}
    db = options.get("database") or {}
    if db.get("driver", "sqlite") != "sqlite":
        raise ValueError("Only SQLite databases are supported")
    return root / (db.get("sqlite_path") or "octop.db")


def snapshot(root: Path, phrase: str):
    path = database(root)
    result = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        for (thread_id,) in db.execute("SELECT thread_id FROM threads"):
            messages = []
            matches = False
            for role, wire in db.execute(
                "SELECT role, message_json FROM thread_messages WHERE thread_id=? ORDER BY seq",
                (thread_id,),
            ):
                body = json.dumps(json.loads(wire), ensure_ascii=False, sort_keys=True)
                if role in ("user", "human") and phrase in body:
                    matches = True
                messages.append((role, hashlib.sha256(body.encode()).digest()))
            result[thread_id] = (matches, messages)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() / ".octop")
    parser.add_argument("--target", type=Path, default=Path.home() / ".octop-bot")
    parser.add_argument("--contains", default="围绕以下主题进行头脑风暴")
    args = parser.parse_args()
    try:
        source = snapshot(args.source, args.contains)
        target = snapshot(args.target, args.contains)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Cannot compare databases: {exc}\n")
    found = False
    for tid in sorted(source.keys() | target.keys()):
        before_match, before = source.get(tid, (False, []))
        after_match, after = target.get(tid, (False, []))
        if not (before_match or after_match):
            continue
        found = True
        tag = hashlib.sha256(tid.encode()).hexdigest()[:10]
        first_diff = next(
            (i for i, pair in enumerate(zip(before, after), 1) if pair[0] != pair[1]), None
        )
        if first_diff is None and len(before) != len(after):
            first_diff = min(len(before), len(after)) + 1
        print(
            f"thread={tag} source_rows={len(before)} target_rows={len(after)} "
            f"same_thread_present={tid in source and tid in target} first_difference={first_diff}"
        )
    if not found:
        print(
            "No matching user message in either projection. Check the data directories or --contains."
        )


if __name__ == "__main__":
    main()

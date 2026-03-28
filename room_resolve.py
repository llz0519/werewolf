"""单机/命令行共用的房间号：写入 last_local_room.txt，避免在 .env 里维护 ROOM_ID。"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
LAST_LOCAL_ROOM_FILE = os.path.join(_ROOT, "last_local_room.txt")


def write_last_local_room(room_id: str) -> None:
    try:
        with open(LAST_LOCAL_ROOM_FILE, "w", encoding="utf-8") as f:
            f.write(room_id.strip() + "\n")
    except OSError:
        pass


def read_last_local_room() -> str:
    try:
        with open(LAST_LOCAL_ROOM_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def clear_last_local_room() -> None:
    try:
        os.remove(LAST_LOCAL_ROOM_FILE)
    except OSError:
        pass


def resolve_room_id(cli_arg: str | None = None) -> str:
    """优先级：命令行 > 环境变量 ROOM_ID（可选）> last_local_room.txt。"""
    if cli_arg and str(cli_arg).strip():
        return str(cli_arg).strip()
    env = (os.getenv("ROOM_ID") or "").strip()
    if env:
        return env
    return read_last_local_room()

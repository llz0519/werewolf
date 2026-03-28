"""
一键启动脚本：
1. 从 .env 读取配置
2. 创建房间（或使用已有 room_id）
3. 真人玩家加入（占位，等真人自己通过 API 操作）
4. 批量启动所有 AI Agent 进程
5. 等待玩家数量满足后，房主触发开始游戏

用法：
    python launch_agents.py
    python launch_agents.py --start   # 自动开始游戏（无需等待）
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
import argparse
import requests
from dotenv import load_dotenv

from room_resolve import clear_last_local_room, write_last_local_room

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

BACKEND_URL  = os.getenv("BACKEND_URL",  "http://127.0.0.1:8000")
LLM_API_KEY  = os.getenv("LLM_API_KEY",  "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL    = os.getenv("LLM_MODEL",    "Qwen/Qwen2.5-72B-Instruct")
POLL_INTERVAL = os.getenv("POLL_INTERVAL", "3")

HUMAN_ID   = os.getenv("HUMAN_PLAYER_ID",   "p1")
HUMAN_NAME = os.getenv("HUMAN_PLAYER_NAME", "玩家1")

# 解析 AI_PLAYERS="p2:Bob,p3:Charlie,..."
AI_PLAYERS_RAW = os.getenv("AI_PLAYERS", "p2:Bob,p3:Charlie,p4:Diana,p5:Eve,p6:Frank")
AI_PLAYERS = [
    (pair.split(":")[0].strip(), pair.split(":")[1].strip())
    for pair in AI_PLAYERS_RAW.split(",")
    if ":" in pair
]


def api(method: str, path: str, player_id: str = "", **kwargs):
    url  = f"{BACKEND_URL}{path}"
    hdrs = {"player-id": player_id} if player_id else {}
    resp = getattr(requests, method)(url, headers=hdrs, timeout=10, **kwargs)
    if resp.status_code >= 400:
        print(f"  ❌ [{resp.status_code}] {resp.text}")
        return None
    return resp.json()


def _clean_up():
    """清空上一局残留：last_local_room.txt 与 logs/"""
    clear_last_local_room()
    os.environ.pop("ROOM_ID", None)
    load_dotenv(override=True)

    import glob
    for f in glob.glob("logs/*.log"):
        try:
            os.remove(f)
        except OSError:
            pass
    print("🧹 已清空上一局数据（last_local_room / logs）\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true", help="满员后自动开始游戏")
    args = parser.parse_args()

    # 每次启动自动清理上一局残留
    _clean_up()

    # ── 1. 创建房间 ──
    # 可选：启动前设置环境变量 ROOM_ID=已有房 可跳过创建；否则每次清理后新建一局
    room_id = os.getenv("ROOM_ID", "").strip()
    if not room_id:
        print("📦 创建新房间...")
        data = api("post", "/game/create", player_id=HUMAN_ID)
        if not data:
            sys.exit(1)
        room_id = data["room_id"]
        print(f"   房间 ID：{room_id}")
    else:
        print(f"📦 使用已有房间：{room_id}")
    write_last_local_room(room_id)

    # ── 2. 真人玩家加入（占位） ──
    print(f"\n👤 真人玩家 {HUMAN_NAME}({HUMAN_ID}) 加入...")
    if not api("post", f"/game/{room_id}/join",
               player_id=HUMAN_ID,
               json={"name": HUMAN_NAME, "is_ai": False}):
        print("真人加入失败，请确认后端已启动。退出。")
        sys.exit(1)

    # ── 3. AI 玩家加入 ──
    print(f"\n🤖 启动 {len(AI_PLAYERS)} 个 AI 玩家...")
    for pid, name in AI_PLAYERS:
        if api("post", f"/game/{room_id}/join",
               player_id=pid,
               json={"name": name, "is_ai": True}):
            print(f"   {name}({pid}) 已加入")
        else:
            print(f"   {name}({pid}) 加入失败，退出。")
            sys.exit(1)

    # ── 4. 开始游戏 ──
    if args.start:
        print("\n🎮 开始游戏...")
        data = api("post", f"/game/{room_id}/start", player_id=HUMAN_ID)
        if not data:
            print("开始游戏失败，退出。")
            sys.exit(1)
        print(f"   游戏开始，当前阶段：{data['phase']}")
    else:
        print(f"\n✅ 房间准备完毕（共 {1 + len(AI_PLAYERS)} 人）")
        print(f"   房间 ID 已写入 last_local_room.txt")
        print(f"   请在游戏界面或 API 中调用 POST /game/{room_id}/start 开始游戏")

    # ── 5. 批量启动 AI Agent 进程 ──
    print(f"\n🚀 批量启动 AI Agent 进程...")
    python = sys.executable
    procs  = []
    for pid, name in AI_PLAYERS:
        cmd = [
            python, "-X", "utf8", "agent.py",
            "--player-id", pid,
            "--room-id",   room_id,
        ]
        if LLM_BASE_URL:
            cmd += ["--llm-base-url", LLM_BASE_URL]
        # api-key 和 model 从 .env 自动读取，无需显式传递
        proc = subprocess.Popen(
            cmd,
            stdout=open(f"logs/{pid}.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        procs.append((pid, name, proc))
        print(f"   ✅ {name}({pid}) PID={proc.pid}，日志：logs/{pid}.log")

    print(f"\n所有 Agent 已在后台运行。")
    print(f"查看日志示例：Get-Content logs\\p2.log -Wait")
    print(f"停止所有：Ctrl+C\n")

    # ── 6. 自动法官循环 ──
    try:
        _run_game_master(room_id, procs)
    except KeyboardInterrupt:
        print("\n[法官] 收到中断，终止所有 Agent...")
        for pid, name, proc in procs:
            proc.terminate()


def _run_game_master(room_id: str, procs: list) -> None:
    """
    自动法官：监控游戏状态，在条件满足时推进阶段。
    条件：
      DAY_DISCUSS → 所有存活玩家都发言后，推进到投票
      DAY_VOTE    → 所有存活玩家都投票后，推进到结算
      DAY_RESULT  → 等待 5 秒后，推进到下一夜
      GAME_OVER   → 打印结果，终止所有子进程
    """
    print("[法官] 开始监控游戏进程...\n")
    last_action_phase = ""   # 上次已推进的阶段标识，防止重复触发

    while True:
        time.sleep(2)

        state = api("get", f"/game/{room_id}/state", player_id=HUMAN_ID)
        if state is None:
            continue

        phase     = state["phase"]
        round_num = state["round_num"]
        phase_key = f"{round_num}:{phase}"   # 每轮每阶段只推进一次

        # ── GAME_OVER ──
        if phase == "game_over":
            print("\n" + "═" * 50)
            print("[法官] 🎉 游戏结束！")
            # 统计存活情况
            for p in state["players"].values():
                status = "存活" if p["is_alive"] else "死亡"
                role   = p["role"] or "?"
                print(f"  {p['name']}({p['player_id']}) [{role}] - {status}")
            print("═" * 50)
            for pid, name, proc in procs:
                proc.terminate()
            break

        # 已推进过此阶段，跳过
        if phase_key == last_action_phase:
            continue

        alive_count = sum(1 for p in state["players"].values() if p["is_alive"])

        # ── DAY_DISCUSS：所有存活玩家发言完毕 ──
        if phase == "day_discuss":
            log_count = len(state.get("day_logs", []))
            print(f"[法官] 第{round_num}轮发言进度：{log_count}/{alive_count}")
            if log_count >= alive_count:
                print(f"[法官] 所有存活玩家发言完毕，推进到投票阶段...")
                api("post", f"/game/{room_id}/action/next_phase", player_id=HUMAN_ID)
                last_action_phase = phase_key

        # ── DAY_VOTE：每人须「投票」或「弃票」之一，才算完成本轮
        elif phase == "day_vote":
            acted = set()
            for voters in state.get("votes", {}).values():
                acted.update(voters)
            acted.update(state.get("vote_abstains", []))
            done = len(acted)
            print(f"[法官] 第{round_num}轮投票进度：{done}/{alive_count}（含弃票）")
            if done >= alive_count:
                print(f"[法官] 所有存活玩家投票完毕，推进到结算阶段...")
                api("post", f"/game/{room_id}/action/next_phase", player_id=HUMAN_ID)
                last_action_phase = phase_key

        # ── DAY_RESULT：展示结果，5 秒后进入下一夜 ──
        elif phase == "day_result":
            print(f"[法官] 投票结果已公布，5 秒后进入第 {round_num + 1} 夜...")
            last_action_phase = phase_key   # 先标记，防止 sleep 期间重复触发
            time.sleep(5)
            api("post", f"/game/{room_id}/action/next_phase", player_id=HUMAN_ID)


if __name__ == "__main__":
    # 确保 logs 目录存在
    os.makedirs("logs", exist_ok=True)
    main()

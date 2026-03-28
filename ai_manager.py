import subprocess
import sys
import os

ACTIVE_PROCS: list[subprocess.Popen] = []

# 按 player_id 指定模型；未命中则使用 DEFAULT_MODEL
# R1 思维链最强（适合需要深度推理的席位）
# V3 推理强且速度快（适合中间席位）
# Qwen2.5-72B 性价比高（适合普通席位）
_MODEL_MAP: dict[str, str] = {
    "p1": "Pro/deepseek-ai/DeepSeek-R1",
    "p2": "Pro/deepseek-ai/DeepSeek-R1",
    "p3": "deepseek-ai/DeepSeek-V3",
    "p4": "deepseek-ai/DeepSeek-V3",
    "p5": "deepseek-ai/DeepSeek-V3",
    "p6": "Qwen/Qwen2.5-72B-Instruct",
    "p7": "Qwen/Qwen2.5-72B-Instruct",
    "p8": "Qwen/Qwen2.5-72B-Instruct",
}
_DEFAULT_MODEL = "Qwen/Qwen2.5-72B-Instruct"

def start_ai_agents(room_id: str, ai_players: list[tuple[str, str, str]], base_url: str = ""):
    """
    启动 AI 进程。
    ai_players 是 (player_id, name, persona) 的列表；
    每个玩家按 _MODEL_MAP 分配不同模型，环境变量 LLM_MODEL 仅作兜底默认值。
    """
    python = sys.executable
    os.makedirs("logs", exist_ok=True)

    for pid, name, persona in ai_players:
        model = _MODEL_MAP.get(pid) or os.getenv("LLM_MODEL") or _DEFAULT_MODEL
        cmd = [
            python, "-X", "utf8", "agent.py",
            "--player-id", pid,
            "--room-id", room_id,
            "--name", name,
            "--persona", persona,
            "--model", model,
            "--interval", "2",  # 加快单机模式轮询
        ]
        if base_url:
            cmd += ["--llm-base-url", base_url]

        print(f"Launching AI Agent: {name} ({pid}) model={model}")
        proc = subprocess.Popen(
            cmd,
            stdout=open(f"logs/{pid}.log", "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        ACTIVE_PROCS.append(proc)

def kill_all_agents():
    """杀掉所有启动的 AI 子进程"""
    print(f"Killing {len(ACTIVE_PROCS)} agent processes...")
    for proc in ACTIVE_PROCS:
        try:
            proc.terminate()
        except Exception as e:
            print(f"Error killing proc: {e}")
    ACTIVE_PROCS.clear()

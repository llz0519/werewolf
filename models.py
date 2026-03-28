from __future__ import annotations

import sys
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ────────────────────────────────────────────────
# 枚举定义
# ────────────────────────────────────────────────

class Role(str, Enum):
    """游戏角色"""
    VILLAGER = "villager"   # 村民
    WEREWOLF = "werewolf"   # 狼人
    SEER     = "seer"       # 预言家
    WITCH    = "witch"      # 女巫
    HUNTER   = "hunter"     # 猎人（出局时可开枪带走一名存活玩家；被毒死不能开枪）


class GamePhase(str, Enum):
    """游戏阶段，按时序流转"""
    WAITING     = "waiting"      # 等待玩家加入
    NIGHT_WOLF_CHAT = "night_wolf_chat"  # 夜晚 - 狼人队内交流（仅狼人可见）
    NIGHT_WOLF  = "night_wolf"   # 夜晚 - 狼人锁定击杀目标
    NIGHT_SEER  = "night_seer"   # 夜晚 - 预言家查验一名玩家身份
    NIGHT_WITCH = "night_witch"  # 夜晚 - 女巫决定是否使用药水
    DAY_DISCUSS = "day_discuss"  # 白天 - 所有存活玩家依次发言
    DAY_VOTE    = "day_vote"     # 白天 - 投票放逐（可弃票；可无人出局）
    DAY_RESULT  = "day_result"   # 白天 - 公布投票结果（缓冲阶段，前端展示出局信息）
    HUNTER_SHOT = "hunter_shot"    # 猎人出局后开枪（带走一名存活玩家，或放弃）
    GAME_OVER   = "game_over"    # 游戏结束


# ────────────────────────────────────────────────
# 核心数据模型
# ────────────────────────────────────────────────

class Player(BaseModel):
    """单个玩家的状态"""
    player_id: str
    name: str

    # 角色仅在服务端完整保存；通过 API 下发时按权限过滤
    role: Optional[Role] = None

    is_alive: bool = True

    # True 表示该席位由 AI Agent 控制，False 表示真人玩家
    is_ai: bool = False

    # 保留字段；当前规则为「游戏结束才公布身份」，过程中不翻牌
    identity_revealed: bool = False


class DayLog(BaseModel):
    """白天发言记录的单条条目"""
    player_id: str
    player_name: str
    message: str
    round_num: int = 1

class SystemLog(BaseModel):
    """系统日志、AI心路历程、动作记录"""
    player_id: str = "system"
    player_name: str = "系统"
    message: str
    log_type: str = "info"


class WolfWhisper(BaseModel):
    """狼人夜间队内私语（非狼人不可见）"""
    player_id: str
    player_name: str
    message: str
    round_num: int = 1
    target_id: Optional[str] = None  # 本条私语中狼人提议的击杀目标


class GameState(BaseModel):
    """完整的游戏状态（服务端视角，包含所有玩家角色）"""
    game_id: str

    # 当前游戏阶段
    phase: GamePhase = GamePhase.WAITING

    # 胜利阵营：None 表示游戏未结束；"villagers_win" 或 "werewolves_win"
    winner: Optional[str] = None

    # 当前回合数（夜晚+白天算一个完整回合）
    round_num: int = 1

    # key: player_id → value: Player；使用字典便于 O(1) 按 ID 查找
    players: dict[str, Player] = Field(default_factory=dict)

    # 夜间死亡历史，累计不清空：[{"round_num": 1, "player_id": "p3"}, ...]
    night_deaths_history: list[dict] = Field(default_factory=list)
    # 白天发言记录（当前轮，每轮清空）
    day_logs: list[DayLog] = Field(default_factory=list)
    # 历史发言记录（累计所有轮，不清空）
    day_logs_history: list[DayLog] = Field(default_factory=list)
    system_logs: list[SystemLog] = Field(default_factory=list)
    # 女巫历史用药记录：[{"round": 1, "saved": "p3", "poisoned": None}, ...]
    witch_actions_history: list[dict] = Field(default_factory=list)

    # 狼人队内私语（累计保留所有夜晚，不清空）
    wolf_whispers: list[WolfWhisper] = Field(default_factory=list)

    # 本夜被女巫毒死的玩家 id（用于猎人规则：毒死不能开枪）
    poisoned_this_night: list[str] = Field(default_factory=list)

    # 猎人出局后待开枪的猎人 player_id；非空时阶段为 HUNTER_SHOT
    pending_hunter_id: Optional[str] = None
    # 开枪阶段来源："night" 昨夜死亡 / "vote" 放逐出局
    hunter_shot_origin: Optional[str] = None

    # 当晚被狼人击杀 / 被女巫毒死的玩家 id 列表；天亮时统一公布
    dead_this_night: list[str] = Field(default_factory=list)

    # ── 夜晚行动的临时暂存（不对外暴露） ──

    # 狼人本夜选定的击杀目标 player_id
    wolf_target: Optional[str] = None

    # 预言家本夜查验的目标 player_id → 查验结果（仅当夜有效，夜后清空）
    seer_result: Optional[dict[str, Role]] = None

    # 预言家历史验人记录（累计所有夜晚，不清空）：player_id → role value
    seer_history: dict[str, str] = Field(default_factory=dict)

    # 女巫是否还持有解药 / 毒药
    witch_has_antidote: bool = True
    witch_has_poison: bool = True

    # 当前投票汇总：key: 被投 player_id → value: 投票人 id 列表（含自投，自投是有效票）
    votes: dict[str, list[str]] = Field(default_factory=dict)

    # 投票阶段选择弃票的玩家 id（不计入任何候选人的得票）
    vote_abstains: list[str] = Field(default_factory=list)
    speaker_sequence: list[str] = Field(default_factory=list)
    current_speaker: Optional[str] = None


# ────────────────────────────────────────────────
# 快速测试
# ────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # 构造 6 名玩家（1 真人 + 5 AI）
    players_data = [
        Player(player_id="p1", name="Alice",   role=Role.SEER,     is_ai=False),
        Player(player_id="p2", name="Bob",     role=Role.WEREWOLF, is_ai=True),
        Player(player_id="p3", name="Charlie", role=Role.WEREWOLF, is_ai=True),
        Player(player_id="p4", name="Diana",   role=Role.WITCH,    is_ai=True),
        Player(player_id="p5", name="Eve",     role=Role.VILLAGER, is_ai=True),
        Player(player_id="p6", name="Frank",   role=Role.VILLAGER, is_ai=True),
    ]

    players_dict = {p.player_id: p for p in players_data}

    state = GameState(
        game_id="game-001",
        phase=GamePhase.WAITING,
        players=players_dict,
    )

    print("=== 初始游戏状态 ===")
    print(state.model_dump_json(indent=2))

    print("\n=== 单独查看玩家 p1 ===")
    print(state.players["p1"].model_dump_json(indent=2))

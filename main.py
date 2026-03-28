from __future__ import annotations

import os
import uuid
import asyncio
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from game_engine import GameEngine
from models import GamePhase, GameState, Player, Role
from ai_manager import start_ai_agents, kill_all_agents
from room_resolve import write_last_local_room

load_dotenv()

# ══════════════════════════════════════════════════════════════════
# 应用初始化
# ══════════════════════════════════════════════════════════════════

app = FastAPI(
    title="狼人杀游戏服务",
    description="支持真人。AI Agent 混战的狼人杀后端 API",
    version="1.0.0",
)

# 开发环境允许所有本地来源（127.0.0.1 / localhost 任意端口）
import re as _re
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内存中的房间字典：room_id -> GameEngine
rooms: dict[str, GameEngine] = {}

# 房主记录：room_id -> player_id
room_owners: dict[str, str] = {}


# ══════════════════════════════════════════════════════════════════
# 视角过滤（核心安全函数）
# ══════════════════════════════════════════════════════════════════

def get_masked_state(engine: GameEngine, request_player_id: str) -> dict:
    """
    对 GameState 做视角脱敏。
    游戏中：仅自己可见身份；狼人互相可见；出局者一律不翻牌。
    游戏结束后（GAME_OVER）：对所有玩家公开全部身份。
    request_player_id == 'spectator' 时始终为上帝视角（完整状态）。
    """
    state = engine.state
    
    if request_player_id == "spectator":
        return state.model_dump()

    if state.phase == GamePhase.GAME_OVER:
        return state.model_dump()

    requester = state.players.get(request_player_id)
    requester_is_wolf = requester is not None and requester.role == Role.WEREWOLF
    requester_is_seer = requester is not None and requester.role == Role.SEER

    # 深拷贝，避免修改原始状态
    raw = state.model_dump()

    # 过滤 players 中每个人的 role（不向客户端暴露 identity_revealed 字段）
    for pid, p in raw["players"].items():
        target_player = state.players[pid]
        p.pop("identity_revealed", None)

        if pid == request_player_id:
            # 自己的角色始终可见
            pass
        elif not target_player.is_alive:
            dead_show_role = target_player.identity_revealed
            if requester_is_wolf and target_player.role == Role.WEREWOLF:
                dead_show_role = True  # 狼队始终互知
            if not dead_show_role:
                p["role"] = None
        elif requester_is_wolf and target_player.role == Role.WEREWOLF:
            # 狼人互相可见
            pass
        else:
            # 其余情况隐藏角色
            p["role"] = None

    # 清除夜晚敏感临时状态
    raw["wolf_target"] = None
    raw["dead_this_night"] = []  # 天亮前不公布

    # 预言家可以看到自己本夜的查验结果及历史记录
    if requester_is_seer and state.seer_result:
        raw["seer_result"] = {
            pid: role.value for pid, role in state.seer_result.items()
        }
    else:
        raw["seer_result"] = None

    # 历史验人记录：仅预言家本人可见（其他角色清空）
    if not requester_is_seer:
        raw["seer_history"] = {}

    # 狼人队内私语：仅狼人本人与（上面已返回的）观战/终局可见
    if requester is None or requester.role != Role.WEREWOLF:
        raw["wolf_whispers"] = []

    # 女巫药水状态与用药历史：只有女巫本人可见
    requester_is_witch = requester is not None and requester.role == Role.WITCH
    if not requester_is_witch:
        raw["witch_has_antidote"] = None
        raw["witch_has_poison"] = None
        raw["witch_actions_history"] = []

    # 女巫需要知道今晚被杀的人是谁（用于决定是否救人）
    # 仅在 NIGHT_WITCH 阶段且请求者是女巫时透出 wolf_target
    if (
        state.phase == GamePhase.NIGHT_WITCH
        and requester is not None
        and requester.role == Role.WITCH
        and requester.is_alive
    ):
        raw["wolf_target"] = state.wolf_target

    return raw


# ══════════════════════════════════════════════════════════════════
# 辅助：获取房间，不存在则 404
# ══════════════════════════════════════════════════════════════════

def get_engine(room_id: str) -> GameEngine:
    engine = rooms.get(room_id)
    if engine is None:
        raise HTTPException(status_code=404, detail=f"房间 [{room_id}] 不存在。")
    return engine


# ══════════════════════════════════════════════════════════════════
# 请求体定义
# ══════════════════════════════════════════════════════════════════

class JoinRequest(BaseModel):
    name: str
    is_ai: bool = False


class SpeakRequest(BaseModel):
    content: str


class VoteRequest(BaseModel):
    target_id: str


class WolfKillRequest(BaseModel):
    target_id: str


class WolfWhisperRequest(BaseModel):
    message: str
    target_id: Optional[str] = None  # 本条私语中提议的击杀目标


class SeerCheckRequest(BaseModel):
    target_id: str


class WitchRequest(BaseModel):
    save: bool = False
    poison_target_id: Optional[str] = None


class HunterShotRequest(BaseModel):
    """target_id 为空或省略表示放弃开枪"""
    target_id: Optional[str] = None


class LogRequest(BaseModel):
    message: str
    log_type: str = "info"


class StartLocalRequest(BaseModel):
    mode: str  # 'spectator'（观战/大乱斗）或 'play'（下场打人）
    human_name: str = "玩家"


# ══════════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════════

# ── 房间管理 ──────────────────────────────────────────────────────

@app.post("/game/start-local", summary="一键开启本地单机对局")
def start_local_game(body: StartLocalRequest):
    """
    1. 清理旧进程
    2. 创建新房间
    3. 加入玩家
    4. 启动后端 AI 进程
    5. 开始游戏
    返回 room_id 和 player_id
    """
    kill_all_agents()
    
    room_id = str(uuid.uuid4())[:8]
    state = GameState(game_id=room_id)
    engine = GameEngine(state)
    rooms[room_id] = engine
    
    player_id = "spectator" if body.mode == "spectator" else "p1"
    room_owners[room_id] = player_id
    
    human_in_game = body.mode == "play"
    if human_in_game:
        engine.state.players["p1"] = Player(player_id="p1", name=body.human_name, is_ai=False)
        
    # 定义 AI 列表
    # 如果是观战，全部 8 人都是AI；如果下场玩，自己是 p1，拉 7 个AI
    ai_list = [
        ("p2", "李四", "普通玩家口吻，就事论事。"),
        ("p3", "王五", "说话比较谨慎，不轻易站边。"),
        ("p4", "赵六", "习惯听完全场再表态。"),
        ("p5", "钱七", "会简单记一下前几轮的票型。"),
        ("p6", "孙八", "发言不多，多数时候跟票。"),
        ("p7", "周九", "喜欢分析票型，逻辑清晰。"),
        ("p8", "吴十", "容易受他人影响，容易被带节奏。"),
    ]
    if body.mode == "spectator":
        ai_list.insert(0, ("p1", "张三", "普通村民语气，正常发言。"))
        
    for pid, name, persona in ai_list:
        engine.state.players[pid] = Player(player_id=pid, name=name, is_ai=True)
        
    try:
        engine.start_game()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    # 后台拉起 AI 进程
    # 注意这里传过去的 ai_list 多了 persona 维度
    start_ai_agents(room_id, ai_list)

    write_last_local_room(room_id)

    return {
        "room_id": room_id,
        "player_id": player_id,
        "phase": engine.state.phase.value
    }


@app.post("/game/create", summary="创建游戏房间")
def create_room(player_id: str = Header(..., description="创建者的玩家ID（作为房主）")):
    """创建一个新的游戏房间，返回 room_id。创建者自动成为房主。"""
    room_id = str(uuid.uuid4())[:8]
    state = GameState(game_id=room_id)
    rooms[room_id] = GameEngine(state)
    room_owners[room_id] = player_id
    return {"room_id": room_id, "owner": player_id}


@app.post("/game/{room_id}/join", summary="加入游戏房间")
def join_room(
    room_id: str,
    body: JoinRequest,
    player_id: str = Header(..., description="玩家唯一ID"),
):
    """加入指定房间。游戏开始后不能再加入。"""
    engine = get_engine(room_id)
    if engine.state.phase != GamePhase.WAITING:
        raise HTTPException(status_code=400, detail="游戏已开始，无法加入。")
    if len(engine.state.players) >= 8:
        raise HTTPException(status_code=400, detail="房间已满（最多8人）。")
    if player_id in engine.state.players:
        raise HTTPException(status_code=400, detail="你已经在房间中了。")

    engine.state.players[player_id] = Player(
        player_id=player_id,
        name=body.name,
        is_ai=body.is_ai,
    )
    return {"message": f"{body.name} 加入成功", "player_count": len(engine.state.players)}


@app.post("/game/{room_id}/start", summary="房主开始游戏（随机发牌）")
def start_game(
    room_id: str,
    player_id: str = Header(..., description="必须是房主的 player_id"),
):
    """触发发牌，游戏进入第一夜。需 6-8 名玩家。"""
    engine = get_engine(room_id)
    if room_owners.get(room_id) != player_id:
        raise HTTPException(status_code=403, detail="只有房主才能开始游戏。")
    try:
        engine.start_game()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "游戏开始！", "phase": engine.state.phase.value}


# ── 状态查询 ───────────────────────────────────────────────────────

@app.get(
    "/game/{room_id}/host_state",
    summary="主持人视角：完整游戏状态（需配置 .env HOST_SECRET）",
)
def host_state(
    room_id: str,
    x_host_secret: str = Header(..., alias="X-Host-Secret", description="与.env中HOST_SECRET一致"),
):
    """仅供裁判/实验记录使用，不下发给普通玩家。未设置 HOST_SECRET 时本接口不可用。"""
    secret = (os.getenv("HOST_SECRET") or "").strip()
    if not secret or x_host_secret != secret:
        raise HTTPException(status_code=403, detail="无效或未配置主持人密钥。")
    engine = get_engine(room_id)
    return engine.state.model_dump(mode="json")


@app.get("/game/{room_id}/state", summary="获取当前游戏状态（视角过滤）")
def get_state(
    room_id: str,
    player_id: str = Header(..., description="请求者的 player_id，用于视角过滤"),
):
    """
    返回经过视角脱敏的游戏状态：
    - 狼人只能看到同伴身份；预言家可看到本夜查验结果
    - 出局者身份在游戏中不公开；游戏结束后全员身份公开
    """
    engine = get_engine(room_id)
    return get_masked_state(engine, player_id)


# ── 夜晚技能 ───────────────────────────────────────────────────────

@app.post("/game/{room_id}/action/wolf_whisper", summary="狼人：队内夜间私语")
async def wolf_whisper_action(
    room_id: str,
    body: WolfWhisperRequest,
    player_id: str = Header(...),
):
    """仅在 NIGHT_WOLF_CHAT 阶段有效。每名存活狼人发过至少一条后自动进入击杀阶段。"""
    engine = get_engine(room_id)
    caller = engine.state.players.get(player_id)
    if caller is None or not caller.is_alive or caller.role != Role.WEREWOLF:
        raise HTTPException(status_code=403, detail="你不是存活的狼人。")
    try:
        engine.wolf_whisper(player_id, body.message, body.target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "私语已发送", "phase": engine.state.phase.value}


@app.post("/game/{room_id}/action/wolf_kill", summary="狼人：选择击杀目标")
async def wolf_kill(
    room_id: str,
    body: WolfKillRequest,
    player_id: str = Header(...),
):
    """仅在 NIGHT_WOLF 阶段有效。调用者必须是存活狼人。"""
    engine = get_engine(room_id)
    caller = engine.state.players.get(player_id)
    if caller is None or not caller.is_alive or caller.role != Role.WEREWOLF:
        raise HTTPException(status_code=403, detail="你不是存活的狼人。")
    try:
        engine.wolf_kill(body.target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "击杀目标已锁定", "phase": engine.state.phase.value}


@app.post("/game/{room_id}/action/seer_check", summary="预言家：查验一名玩家")
async def seer_check(
    room_id: str,
    body: SeerCheckRequest,
    player_id: str = Header(...),
):
    """仅在 NIGHT_SEER 阶段有效。调用者必须是存活预言家。"""
    engine = get_engine(room_id)
    caller = engine.state.players.get(player_id)
    if caller is None or not caller.is_alive or caller.role != Role.SEER:
        raise HTTPException(status_code=403, detail="你不是存活的预言家。")
    try:
        is_wolf = engine.seer_check(player_id, body.target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "target_id": body.target_id,
        "is_werewolf": is_wolf,
        "phase": engine.state.phase.value,
    }


@app.post("/game/{room_id}/action/witch", summary="女巫：使用解药或毒药")
async def witch_action(
    room_id: str,
    body: WitchRequest,
    player_id: str = Header(...),
):
    """仅在 NIGHT_WITCH 阶段有效。调用者必须是存活女巫。"""
    engine = get_engine(room_id)
    caller = engine.state.players.get(player_id)
    if caller is None or not caller.is_alive or caller.role != Role.WITCH:
        raise HTTPException(status_code=403, detail="你不是存活的女巫。")
    try:
        engine.witch_action(player_id, save=body.save, poison_target_id=body.poison_target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "女巫行动完成", "phase": engine.state.phase.value}


@app.post("/game/{room_id}/action/hunter_shoot", summary="猎人：出局后开枪带走一人或放弃")
async def hunter_shoot_action(
    room_id: str,
    body: HunterShotRequest,
    player_id: str = Header(...),
):
    """
    仅在 HUNTER_SHOT 阶段有效。调用者须为 pending_hunter_id（已出局猎人）。
    target_id 为空表示不开枪。
    """
    engine = get_engine(room_id)
    caller = engine.state.players.get(player_id)
    if caller is None or caller.role != Role.HUNTER:
        raise HTTPException(status_code=403, detail="只有猎人可以执行此操作。")
    if engine.state.pending_hunter_id != player_id:
        raise HTTPException(status_code=403, detail="当前不是待开枪的猎人。")
    try:
        engine.hunter_shoot(player_id, body.target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "猎人行动完成", "phase": engine.state.phase.value}


# ── 白天互动 ──────────────────────────────────────────────────────

def check_and_auto_advance(engine: GameEngine):
    """
    检查是否达到自动推进阶段的条件。
    1. DAY_DISCUSS -> DAY_VOTE：所有存活玩家都发了言。
    2. DAY_VOTE -> DAY_RESULT：所有存活玩家都完成了投票或弃票。
    3. DAY_RESULT -> NIGHT_WOLF：展示完结果后，自动（稍延时）进入下一夜。
    4. GAME_OVER -> 杀掉所有 AI Agent。
    """
    state = engine.state
    if state.phase == GamePhase.GAME_OVER:
        kill_all_agents()
        return

    # 获取当前活人数
    alive_count = sum(1 for p in state.players.values() if p.is_alive)
    
    if state.phase == GamePhase.DAY_DISCUSS:
        if len(state.day_logs) >= alive_count:
            state.phase = GamePhase.DAY_VOTE
            return
            
    if state.phase == GamePhase.DAY_VOTE:
        acted = set()
        for voters in state.votes.values():
            acted.update(voters)
        acted.update(state.vote_abstains)
        if len(acted) >= alive_count:
            engine.settle_voting()
            # sink into DAY_RESULT
            
    if state.phase == GamePhase.DAY_RESULT:
        # 给前端一点点时间拉取结果，延时秒后切入下一夜
        # 我们用后台协程处理延时切夜，否则会阻塞当前请求返回
        async def delay_next_night():
            await asyncio.sleep(3)
            # engine 是单例引用，状态没被改坏的话就正常推进
            if engine.state.phase == GamePhase.DAY_RESULT:
                engine.start_next_night()
        asyncio.create_task(delay_next_night())

@app.post("/game/{room_id}/action/log", summary="提交系统日志")
async def submit_system_log(
    room_id: str,
    body: LogRequest,
    player_id: str = Header(...),
):
    engine = get_engine(room_id)
    player = engine.state.players.get(player_id)
    player_name = player.name if player else player_id
    engine.add_system_log(body.message, player_id, player_name, body.log_type)
    return {"message": "日志已记录"}

@app.post("/game/{room_id}/action/speak", summary="白天发言")
async def speak(
    room_id: str,
    body: SpeakRequest,
    player_id: str = Header(...),
):
    """仅在 DAY_DISCUSS 阶段有效。死亡玩家无法发言。"""
    engine = get_engine(room_id)
    try:
        engine.add_day_log(player_id, body.content)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "发言已记录"}


@app.post("/game/{room_id}/action/vote", summary="投票放逐")
async def vote(
    room_id: str,
    body: VoteRequest,
    player_id: str = Header(...),
):
    """仅在 DAY_VOTE 阶段有效。可投任意存活玩家（含自投），自投为有效票。"""
    engine = get_engine(room_id)
    try:
        engine.cast_vote(player_id, body.target_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"投票已记录，目标：{body.target_id}"}


@app.post("/game/{room_id}/action/abstain", summary="投票阶段弃票")
async def vote_abstain(
    room_id: str,
    player_id: str = Header(...),
):
    """
    弃票：不增加任何候选人得票，但视为已完成本轮投票。
    与自投（POST /action/vote 投自己）不同。
    """
    engine = get_engine(room_id)
    try:
        engine.cast_vote_abstain(player_id)
        check_and_auto_advance(engine)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "已弃票", "phase": engine.state.phase.value}


# ── 阶段推进 ──────────────────────────────────────────────────────

@app.post("/game/{room_id}/action/next_phase", summary="手动推进游戏阶段")
async def next_phase(
    room_id: str,
    player_id: str = Header(...),
):
    """
    根据当前阶段执行对应的推进操作：
    - DAY_DISCUSS  -> 切换到 DAY_VOTE
    - DAY_VOTE     -> 结算投票，进入 DAY_RESULT
    - DAY_RESULT   -> 开始下一夜，进入 NIGHT_WOLF_CHAT
    """
    engine = get_engine(room_id)
    phase = engine.state.phase
    try:
        if phase == GamePhase.DAY_DISCUSS:
            engine.state.phase = GamePhase.DAY_VOTE
            msg = "进入投票阶段"
        elif phase == GamePhase.DAY_VOTE:
            eliminated = engine.settle_voting()
            msg = (
                f"投票结算完毕，{eliminated} 被放逐"
                if eliminated
                else "投票结算完毕，无人出局（平票、无人得票或全员弃票等）"
            )
        elif phase == GamePhase.DAY_RESULT:
            engine.start_next_night()
            msg = f"进入第 {engine.state.round_num} 夜"
        else:
            raise HTTPException(
                status_code=400,
                detail=f"当前阶段 [{phase.value}] 不支持手动推进",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": msg, "phase": engine.state.phase.value}

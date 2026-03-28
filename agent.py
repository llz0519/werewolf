"""
WerewolfAgent —— 狼人杀 AI 玩家
通过 HTTP 调用游戏后端，通过 OpenAI 兼容 API 进行推理决策。
配置从 .env 文件读取，命令行参数可覆盖。
"""
from __future__ import annotations

import json
import os
import sys
import time
import argparse
from typing import Optional

import requests
from dotenv import load_dotenv
from openai import OpenAI

from room_resolve import resolve_room_id

# 加载 .env（项目根目录）
load_dotenv()


class RoomNotFoundError(Exception):
    """房间在后端不存在（常见于后端重启后内存房间丢失）。"""

# ══════════════════════════════════════════════════════════════════
# 各角色的 System Prompt 模板
# ══════════════════════════════════════════════════════════════════

# 对齐实验文档「Agent 的推理与策略」：信息不对称下的伪装、证明与逻辑推理。
ROLE_PROMPTS: dict[str, str] = {
    "werewolf": """你是狼人杀中的【狼人】。胜利条件：狼人存活数不少于好人存活数。

【伪装与白天发言】
你应该像一个普通村民一样发言：可以对某些玩家表达合理怀疑，但不要过于激进以免引人注意。
若有人跳预言家并验你为狼人，你可以反咬对方是悍跳的假预言家，从逻辑上质疑其验人顺序与结论是否合理。

【投票】
投票时尽量跟票（投多数人支持的目标），避免成为异类；若你有把握抗推好人，也可视局面带节奏。

【夜晚】
你知道狼队友是谁。夜晚先与队友队内交流，再决定击杀目标；击杀谁由你与队友协商，优先威胁神职或高推理好人（以当前局面为准）。
本局接口：先完成队内私语阶段，再进入击杀阶段。""",

    "seer": """你是狼人杀中的【预言家】。胜利条件：好人阵营放逐全部狼人。
你每晚可查验一名存活玩家是否为狼人。

【起跳与报验】
在合适时机跳出预言家身份并公布验人信息，帮助好人归票；若过早暴露可能被刀，需权衡。

【应对悍跳】
当有多人声称预言家（含狼人悍跳）时，你需要通过逻辑证明自己：对比你与对方的验人信息，指出对方信息中的矛盾、不合理顺序或与后续白天行为不符之处。
可尝试请女巫等好人从你的验人链、时间线等角度协助判断（本局无猎人角色）。

【记忆】
请牢记已公布的查验结果，并在发言与投票中一致运用。""",

    "witch": """你是狼人杀中的【女巫】。胜利条件：好人阵营放逐全部狼人。
你拥有一瓶解药与一瓶毒药（是否已用、同一夜能否救/毒以游戏状态为准）。

【用药思路】
解药通常用于救被狼人击杀者；毒药用于你高度怀疑的狼人，避免盲毒误伤好人。
白天可隐藏身份，需要时可跳出说明银水/毒人信息以正视角。

【注意】
用药须符合本局规则（以接口返回为准）。""",

    "villager": """你是狼人杀中的【村民】。胜利条件：好人阵营放逐全部狼人。你没有夜间技能。

【逻辑推理】
分析每名玩家的发言是否自洽；留意急于带节奏、模糊身份、频繁改变立场的玩家。

【投票行为】
狼人往往会集中投票给对好人威胁最大的玩家（如跳预言家者），注意票型是否异常。

【预言家面】
若有人声称预言家，将其验人信息与后续出局、发言对照；若验人链与死亡/行为明显矛盾，可能是悍跳。

【原则】
不要随机指控；你的怀疑与投票应基于具体发言、票型与公开事实，并在 thought 中写清推理链。""",

    "hunter": """你是狼人杀中的【猎人】。胜利条件：好人阵营放逐全部狼人。

【特殊技能】
你在被出局时（狼人刀死或被投票放逐），可以立即开枪带走一名存活玩家；但若被女巫毒死，则无法开枪。

【白天发言与投票】
与村民策略相同：推理发言、基于公开信息投票。
你可以选择是否在白天公开猎人身份作为威慑，但暴露后会成为狼人的优先击杀目标。

【开枪决策】
出局后开枪时，应优先选择你最有把握的狼人；若无确定目标，宁可放弃（target_id: null），避免误伤好人削弱己方力量。""",
}

# ══════════════════════════════════════════════════════════════════
# 各阶段的行动 Prompt 模板
# ══════════════════════════════════════════════════════════════════

def build_action_prompt(state: dict, player_id: str) -> str:
    """
    根据当前游戏状态和玩家身份，构建发给 LLM 的行动指令 Prompt。
    包含 Chain-of-Thought 要求和严格的 JSON 输出格式约束。
    """
    phase     = state["phase"]
    round_num = state["round_num"]
    me        = state["players"][player_id]
    my_role   = me["role"]

    # 构造存活玩家列表
    alive_list = [
        f"{p['player_id']}({p['name']})" + (f"[{p['role']}]" if p["role"] else "")
        for p in state["players"].values()
        if p["is_alive"]
    ]
    dead_list = [
        f"{p['player_id']}({p['name']})[{p['role'] or '?'}]"
        for p in state["players"].values()
        if not p["is_alive"]
    ]

    # 当前轮发言日志
    logs_text = "\n".join(
        f"  [{log['player_id']}({log['player_name']})]: {log['message']}"
        for log in state.get("day_logs", [])
    ) or "  （暂无发言）"

    # 历史各轮发言（归档，按回合分组）
    history_logs = state.get("day_logs_history") or []
    history_ctx = ""
    if history_logs:
        rounds_map: dict[int, list] = {}
        for log in history_logs:
            r = log.get("round_num", 1)
            rounds_map.setdefault(r, []).append(log)
        lines = []
        for r_num in sorted(rounds_map.keys()):
            lines.append(f"  --- 第 {r_num} 回合 ---")
            for log in rounds_map[r_num]:
                lines.append(f"  [{log['player_id']}({log['player_name']})]: {log['message']}")
        history_ctx = "\n历史发言记录（过往回合）：\n" + "\n".join(lines)

    # 狼人队友信息（对所有阶段可见，帮助 LLM 在白天也能配合队友）
    wolf_ctx = ""
    if my_role == "werewolf":
        wolf_teammates = [
            f"{p['player_id']}({p['name']}){'[存活]' if p['is_alive'] else '[已死]'}"
            for p in state["players"].values()
            if p["role"] == "werewolf" and p["player_id"] != player_id
        ]
        wolf_ctx = f"\n你的狼人队友：{', '.join(wolf_teammates) or '无（队友已全部死亡）'}"

    # 夜间死亡历史（公开信息，累计所有夜晚）
    night_deaths_history = state.get("night_deaths_history") or []
    night_announce = ""
    # 判断当前是黑夜还是白天
    is_day_phase = phase in ("day_discuss", "day_vote", "day_result", "hunter_shot")
    
    # 获取要展示的最新死亡报告的回合数：
    # 如果是白天，昨夜就是当前 round_num；如果是黑夜，昨夜应为 round_num - 1
    last_night_num = round_num if is_day_phase else round_num - 1

    if last_night_num >= 1:
        last_night = [e for e in night_deaths_history if e.get("round_num") == last_night_num]
        if last_night:
            death_names = [
                f"{e['player_id']}({state['players'].get(e['player_id'], {}).get('name', e['player_id'])})"
                for e in last_night
            ]
            night_announce = f"【第{last_night_num}夜死亡公告】：{', '.join(death_names)} 死亡出局。"
        else:
            night_announce = f"【第{last_night_num}夜死亡公告】：平安夜，无人死亡。"
    
    # 历史各夜死亡摘要
    prev_nights = [e for e in night_deaths_history if e.get("round_num") < last_night_num]
    if prev_nights:
        prev_by_round: dict[int, list] = {}
        for e in prev_nights:
            prev_by_round.setdefault(e["round_num"], []).append(e["player_id"])
        prev_lines = []
        for r, pids in sorted(prev_by_round.items()):
            names = ", ".join(
                f"{pid}({state['players'].get(pid, {}).get('name', pid)})"
                for pid in pids
            )
            prev_lines.append(f"  第{r}夜：{names} 死亡")
        if night_announce:
            night_announce += "\n【历史夜间死亡】：\n" + "\n".join(prev_lines)
        else:
            night_announce = "【历史夜间死亡】：\n" + "\n".join(prev_lines)

    # 基础上下文
    base_ctx = f"""
=== 当前局面 ===
第 {round_num} 回合，阶段：{phase}
你的身份：{player_id}({me['name']})，角色：{my_role}{wolf_ctx}
{night_announce}
存活玩家（{len(alive_list)}人）：{', '.join(alive_list)}
已死亡玩家（身份未知，游戏结束前不公开）：{', '.join(dead_list) or '无'}{history_ctx}
本回合发言记录：
{logs_text}

【重要推理规则】
- 你只知道自己的角色。已死亡玩家的身份对你不可见，禁止断言"某某是女巫/预言家/狼人"，除非你本人就是对应角色且有直接信息。
- 如果昨夜无人死亡（平安夜），你不知道原因，禁止猜测"是女巫救了人"——女巫可能已经死亡或未使用药水。
- 所有判断必须基于你实际观察到的发言、投票行为等公开信息，不能凭空臆造。
""".strip()

    # 根据阶段附加额外信息和输出格式
    if phase == "night_wolf_chat":
        cur_round = round_num
        whisper_lines = [
            w for w in (state.get("wolf_whispers") or [])
            if w.get("round_num") == cur_round
        ]
        ww = "\n".join(
            f"  [{w.get('player_id')}({w.get('player_name', '')})]: {w.get('message', '')}"
            for w in whisper_lines
        ) or "  （暂无，你先开口）"
        my_count = sum(
            1 for w in whisper_lines if w.get("player_id") == player_id
        )
        from game_engine import GameEngine
        total_rounds = GameEngine.WOLF_CHAT_MAX_ROUNDS
        # 上一轮私语摘要（如有）
        prev_whispers = [
            w for w in (state.get("wolf_whispers") or [])
            if w.get("round_num") == cur_round - 1
        ]
        prev_ww_text = ""
        if prev_whispers:
            lines = "\n".join(
                f"  [{w.get('player_id')}({w.get('player_name', '')})]: {w.get('message', '')}"
                for w in prev_whispers
            )
            prev_ww_text = f"\n上夜队内私语（回顾）：\n{lines}\n"
        # 统计当前意见分布给 LLM 参考
        target_votes: dict[str, int] = {}
        for w in whisper_lines:
            t = w.get("target_id")
            if t:
                target_votes[t] = target_votes.get(t, 0) + 1
        vote_summary = ""
        if target_votes:
            items = ", ".join(
                f"{tid}({state['players'].get(tid, {}).get('name', tid)}):{cnt}票"
                for tid, cnt in target_votes.items()
            )
            vote_summary = f"\n当前目标票数：{items}"

        extra = (
            f"{prev_ww_text}"
            f"本夜队内私语记录：\n{ww}{vote_summary}\n\n"
            "请给出你认为今晚应该杀的目标（target_id），"
            "若同意多数意见则投同一人，若有异议请说明理由并给出你的目标。"
            "全员目标一致后系统将自动进入击杀阶段。"
        )
        fmt = f"""
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{{
  "thought": "简短分析：为什么杀此人对狼队最有利",
  "message": "队内私语内容（说明你的目标和理由，可回应队友观点）",
  "target_id": "你提议本夜击杀的存活玩家 player_id（只填纯 ID，如 p3）"
}}"""

    elif phase == "night_wolf":
        whisper_lines = state.get("wolf_whispers") or []
        ww = "\n".join(
            f"  [{w.get('player_id')}({w.get('player_name', '')})]: {w.get('message', '')}"
            for w in whisper_lines
        ) or "  （暂无）"
        extra = f"队内交流：\n{ww}\n结合狼人策略选择本夜击杀目标。"
        fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "为何刀该目标（对狼队收益）",
  "target_id": "本夜击杀目标的 player_id（只填纯 ID，如 p3）"
}"""

    elif phase == "night_seer":
        # 累计历史验人（所有夜晚）
        seer_hist = state.get("seer_history") or {}
        if seer_hist:
            hist_lines = []
            for pid, role_val in seer_hist.items():
                pname = state["players"].get(pid, {}).get("name", pid)
                label = "【狼人】" if role_val == "werewolf" else "【好人】"
                hist_lines.append(f"  {pid}({pname}) → {label}")
            history_check = "你历史上已验人结果：\n" + "\n".join(hist_lines)
        else:
            history_check = "本局你尚未验过任何人。"
        extra = f"{history_check}\n请选择一名 **未验过** 的存活玩家进行查验，优先验证最可疑者。"
        fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "为何查此人（可疑点或信息量）",
  "target_id": "要查验的 player_id（只填纯 ID，如 p3）"
}"""

    elif phase == "night_witch":
        wolf_target  = state.get("wolf_target")
        has_antidote = state.get("witch_has_antidote")
        has_poison   = state.get("witch_has_poison")
        witch_hist   = state.get("witch_actions_history") or []
        witch_hist_text = ""
        if witch_hist:
            hist_lines = []
            for rec in witch_hist:
                r = rec.get("round", "?")
                saved   = f"救了 {rec['saved_id']}({rec['saved_name']})" if rec.get("saved_id") else None
                poisoned = f"毒了 {rec['poisoned_id']}({rec['poisoned_name']})" if rec.get("poisoned_id") else None
                desc = "、".join(filter(None, [saved, poisoned])) or "未用药"
                hist_lines.append(f"  第{r}夜：{desc}")
            witch_hist_text = "\n你的历史用药记录：\n" + "\n".join(hist_lines) + "\n"
        extra = (
            f"{witch_hist_text}"
            f"今晚被狼人击杀的玩家：{wolf_target or '未知'}\n"
            f"解药剩余：{'有' if has_antidote else '无'}，"
            f"毒药剩余：{'有' if has_poison else '无'}"
        )
        fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "是否救人/毒人及理由",
  "save": false,
  "poison_target_id": null
}
说明：save=true 表示使用解药；poison_target_id 为要毒的玩家 id，不毒则 null。同一夜不能既救又毒（以游戏规则为准）。"""

    elif phase == "day_discuss":
        seer_ctx = ""
        if my_role == "seer":
            history = state.get("seer_history") or {}
            if history:
                lines = []
                for pid, role_val in history.items():
                    pname = state["players"].get(pid, {}).get("name", pid)
                    label = "【狼人】" if role_val == "werewolf" else "【好人】"
                    lines.append(f"  {pid}({pname}) → {label}")
                seer_ctx = "\n你的历史验人记录（真实结果，请如实运用）：\n" + "\n".join(lines) + "\n"
        extra = (
            f"{seer_ctx}白天发言阶段。请结合你的角色身份、系统提示中的策略要点与场上公开信息发言。"
            "thought 中先简要推理，content 为面向全场的发言。"
        )
        fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "推理链：怀疑谁、依据是什么",
  "content": "公开发言内容"
}"""

    elif phase == "day_vote":
        seer_ctx = ""
        if my_role == "seer":
            history = state.get("seer_history") or {}
            if history:
                lines = []
                for pid, role_val in history.items():
                    pname = state["players"].get(pid, {}).get("name", pid)
                    label = "【狼人】" if role_val == "werewolf" else "【好人】"
                    lines.append(f"  {pid}({pname}) → {label}")
                seer_ctx = "\n你的历史验人记录（真实结果）：\n" + "\n".join(lines) + "\n"
        extra = (
            f"{seer_ctx}投票阶段：可投票放逐一名存活玩家，target_id 为 null 表示弃票。"
            "结合角色策略、票型与发言，在 thought 中写清理由；平票或无人得票时本日可能无人出局。"
        )
        fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "为何投/弃票",
  "target_id": "要放逐的 player_id，或 null 表示弃票"
}"""

    elif phase == "hunter_shot":
        pending = state.get("pending_hunter_id")
        if pending != player_id:
            extra = "本阶段由猎人决定是否开枪，你无需行动。"
            fmt = '请输出 {"thought": "等待猎人决策", "action": "wait"}'
        else:
            extra = (
                "你是猎人，刚刚出局。现在可以开枪带走一名存活玩家，或放弃开枪（target_id: null）。"
                "请基于你的推理判断开枪目标；如无把握，宁可放弃以免误伤。"
            )
            fmt = """
请输出严格的 JSON，格式如下（不要输出其他任何内容）：
{
  "thought": "开枪目标选择理由，或放弃理由",
  "target_id": "要击毙的存活玩家 player_id，或 null 表示放弃"
}"""

    else:
        extra = ""
        fmt = '请输出 {"thought": "当前阶段无需行动", "action": "wait"}'

    return f"{base_ctx}\n\n{extra}\n{fmt}"


# ══════════════════════════════════════════════════════════════════
# WerewolfAgent 主类
# ══════════════════════════════════════════════════════════════════

class WerewolfAgent:
    def __init__(
        self,
        room_id: str,
        player_id: str,
        llm_api_key: str,
        llm_model: str = "gpt-4o",
        api_base_url: str = "http://127.0.0.1:8000",
        llm_base_url: Optional[str] = None,
        name: Optional[str] = None,
        persona: str = "",
    ) -> None:
        self.room_id      = room_id
        self.player_id    = player_id
        self.api_base_url = api_base_url.rstrip("/")
        self.llm_model    = llm_model
        self.name         = name
        self.persona      = persona

        # OpenAI 兼容客户端（支持自定义 base_url，可接入 Claude / 国内模型等）
        self.llm = OpenAI(
            api_key=llm_api_key,
            base_url=llm_base_url,  # None 时使用默认 OpenAI 地址
        )

        # 本地行动记忆：记录"哪个阶段已经行动过"，防止重复行动
        self.acted_phases: set[str] = set()

        # 个人记忆日志：累计记录自己的推理和行动历史
        self.memory: list[dict] = []

        self._log(f"Agent 初始化完成 | room={room_id} | player={player_id} | model={llm_model}")

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        print(f"[Agent:{self.player_id}] {msg}", flush=True)

    def _headers(self) -> dict:
        return {"player-id": self.player_id}

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.api_base_url}{path}"
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
        if resp.status_code >= 400:
            raise RuntimeError(f"API 错误 [{resp.status_code}]: {resp.text}")
        return resp.json()

    # ──────────────────────────────────────────────
    # 获取游戏状态
    # ──────────────────────────────────────────────

    def get_current_state(self) -> dict:
        url  = f"{self.api_base_url}/game/{self.room_id}/state"
        resp = requests.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            raise RoomNotFoundError(
                f"房间 [{self.room_id}] 不存在（后端可能已重启）。请结束本进程并重新运行 launch_agents.py。"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"获取状态失败 [{resp.status_code}]: {resp.text}")
        return resp.json()

    # ──────────────────────────────────────────────
    # LLM 推理决策
    # ──────────────────────────────────────────────

    def decide_action(self, state: dict) -> dict:
        """
        调用 LLM 进行 Chain-of-Thought 推理，返回解析后的 JSON 行动。
        """
        my_role   = state["players"][self.player_id]["role"]
        phase     = state["phase"]

        system_prompt = ROLE_PROMPTS.get(my_role, ROLE_PROMPTS["villager"])
        
        # 注入人设（如果存在且非空）
        if hasattr(self, 'name') and self.name:
            system_prompt += f"\n\n你的当前人设/名字是：【{self.name}】。"
        if hasattr(self, 'persona') and self.persona:
            system_prompt += f"\n人设参考（可在语气与风格中体现）：{self.persona}"

        user_prompt   = build_action_prompt(state, self.player_id)

        self._log(f"调用 LLM 决策 | 角色={my_role} | 阶段={phase}")

        response = self.llm.chat.completions.create(
            model=self.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},  # 强制 JSON 输出
        )

        raw = response.choices[0].message.content
        self._log(f"LLM 原始输出：{raw}")

        try:
            action = json.loads(raw)
        except json.JSONDecodeError as e:
            self._log(f"JSON 解析失败：{e}，原文：{raw}")
            raise

        # 记录到个人记忆
        self.memory.append({
            "round":   state["round_num"],
            "phase":   phase,
            "role":    my_role,
            "thought": action.get("thought", ""),
            "action":  {k: v for k, v in action.items() if k != "thought"},
        })

        return action

    # ──────────────────────────────────────────────
    # 执行行动
    # ──────────────────────────────────────────────

    @staticmethod
    def _clean_id(raw: str | None, state: dict) -> str | None:
        """
        清洗 LLM 返回的 player_id。
        LLM 有时会返回 "p2(Bob)" 或 "p2 Bob" 这类格式，
        统一截取第一个非字母数字字符之前的部分得到纯 player_id。
        同时验证该 id 在当前游戏中真实存在。
        """
        if not raw:
            return None
        # LLM 有时返回字符串 "null" / "None" 表示不选目标
        if str(raw).strip().lower() in ("null", "none", "空", "无"):
            return None
        # 取括号 / 空格 / 中文前的前缀
        import re
        cleaned = re.split(r"[\s\(（【]", str(raw).strip())[0]
        if cleaned in state.get("players", {}):
            return cleaned
        # 如果还不对，尝试在所有玩家 id 中做前缀匹配
        for pid in state.get("players", {}):
            if str(raw).startswith(pid):
                return pid
        return cleaned  # 最后兜底原样返回，让 API 报错

    def execute_action(self, state: dict, action: dict) -> None:
        """
        根据当前阶段和 LLM 决策，调用对应的后端 API。
        """
        phase = state["phase"]
        
        # 提取并发送 AI 的思考过程到前端
        thought = action.get("thought")
        if thought:
            try:
                self._post(f"/game/{self.room_id}/action/log", {"message": f"[{phase}] {thought}", "log_type": "thought"})
            except Exception as e:
                self._log(f"发送 thought 失败: {e}")

        if phase == "night_wolf_chat":
            msg = (action.get("message") or "").strip()
            if not msg:
                self._log("警告：LLM 未返回 message，跳过私语。")
                return
            target = self._clean_id(action.get("target_id"), state)
            result = self._post(
                f"/game/{self.room_id}/action/wolf_whisper",
                {"message": msg, "target_id": target},
            )
            self._log(f"狼人私语 目标={target} → {result}")

        elif phase == "night_wolf":
            target = self._clean_id(action.get("target_id"), state)
            if not target:
                self._log("警告：LLM 未返回 target_id，跳过击杀。")
                return
            result = self._post(f"/game/{self.room_id}/action/wolf_kill",
                                {"target_id": target})
            self._log(f"击杀 {target} → {result}")

        elif phase == "night_seer":
            target = self._clean_id(action.get("target_id"), state)
            if not target:
                self._log("警告：LLM 未返回 target_id，跳过查验。")
                return
            result = self._post(f"/game/{self.room_id}/action/seer_check",
                                {"target_id": target})
            if result:
                is_wolf = result.get("is_werewolf")
                self._log(f"查验 {target} → {'狼人' if is_wolf else '好人'}")

        elif phase == "night_witch":
            save   = action.get("save", False)
            poison = self._clean_id(action.get("poison_target_id"), state)
            result = self._post(f"/game/{self.room_id}/action/witch",
                                {"save": save, "poison_target_id": poison})
            self._log(f"女巫行动 save={save} poison={poison} → {result}")

        elif phase == "day_discuss":
            content = action.get("content", "（无发言）")
            result  = self._post(f"/game/{self.room_id}/action/speak",
                                 {"content": content})
            self._log(f"发言：{content[:50]}...")

        elif phase == "day_vote":
            target = self._clean_id(action.get("target_id"), state)
            if not target:
                result = self._post(f"/game/{self.room_id}/action/abstain", {})
                self._log(f"无有效 target_id → 弃票 → {result}")
                return
            result = self._post(f"/game/{self.room_id}/action/vote",
                                {"target_id": target})
            self._log(f"投票放逐 {target} → {result}")

        elif phase == "hunter_shot":
            target = self._clean_id(action.get("target_id"), state)
            result = self._post(
                f"/game/{self.room_id}/action/hunter_shoot",
                {"target_id": target},
            )
            if target:
                self._log(f"猎人开枪击毙 {target} → {result}")
            else:
                self._log(f"猎人放弃开枪 → {result}")

        else:
            self._log(f"阶段 {phase} 无需行动。")

    # ──────────────────────────────────────────────
    # 判断是否轮到自己行动
    # ──────────────────────────────────────────────

    @staticmethod
    def _designated_wolf_killer_id(state: dict) -> str | None:
        """编号最小的存活狼人负责提交击杀，避免两名狼人重复调用 API。"""
        wolves = [
            pid
            for pid, p in state.get("players", {}).items()
            if p.get("role") == "werewolf" and p.get("is_alive")
        ]
        return min(wolves) if wolves else None

    def _action_dedup_key(self, state: dict) -> str:
        """
        night_wolf_chat：每名狼人的 key 含本夜已发言条数，
        使其可以发多条私语（直到后端推进到 night_wolf 阶段）。
        其余阶段：每回合每阶段至多行动一次。
        """
        r = state["round_num"]
        phase = state["phase"]
        if phase == "night_wolf_chat":
            cur_round = r
            count = sum(
                1 for w in state.get("wolf_whispers", [])
                if w.get("player_id") == self.player_id
                and w.get("round_num") == cur_round
            )
            return f"{r}:{phase}:{self.player_id}:{count}"
        return f"{r}:{phase}"

    def _should_act(self, state: dict) -> bool:
        """
        判断当前阶段是否需要且尚未行动。
        """
        phase  = state["phase"]
        me     = state["players"].get(self.player_id)
        my_role = me["role"] if me else None

        # 游戏结束不行动
        if phase == "game_over":
            return False

        # 猎人开枪阶段：仅 pending_hunter_id 对应的死亡猎人可行动
        if phase == "hunter_shot":
            pending = state.get("pending_hunter_id")
            if pending == self.player_id and my_role == "hunter":
                key = self._action_dedup_key(state)
                return key not in self.acted_phases
            return False

        # 其余阶段：死亡玩家不行动
        if me is None or not me["is_alive"]:
            return False

        # 等待阶段 / 结果展示阶段不主动行动
        if phase in ("waiting", "day_result"):
            return False

        if phase == "night_wolf_chat":
            if my_role != "werewolf":
                return False
        elif phase == "night_wolf":
            if my_role != "werewolf":
                return False
            if self._designated_wolf_killer_id(state) != self.player_id:
                return False
        elif phase == "night_seer"  and my_role != "seer":     return False
        elif phase == "night_witch" and my_role != "witch":    return False
        
        # 白天发言：必须是当前轮到的发言者
        if phase == "day_discuss":
            current_speaker = state.get("current_speaker")
            if current_speaker != self.player_id:
                return False

        key = self._action_dedup_key(state)
        if key in self.acted_phases:
            return False

        return True

    # ──────────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────────

    def run(self, poll_interval: float = 3.0) -> None:
        """
        轮询后端状态，在需要行动时调用 LLM 决策并执行。
        """
        self._log("Agent 启动，开始轮询...")

        while True:
            try:
                state = self.get_current_state()
                phase = state["phase"]

                if phase == "game_over":
                    self._log("游戏已结束，Agent 退出。")
                    break

                if self._should_act(state):
                    key = self._action_dedup_key(state)
                    try:
                        action = self.decide_action(state)
                        self.execute_action(state, action)
                        self.acted_phases.add(key)
                    except Exception as e:
                        self._log(f"行动失败（{key}）：{e}")
                        # 所有失败默认不标记，允许下一轮重试（休眠下防止过快重试刷屏）
                        time.sleep(2)
                else:
                    self._log(f"等待中 | 阶段={phase} | round={state['round_num']}")

            except RoomNotFoundError as e:
                self._log(str(e))
                sys.exit(2)

            except Exception as e:
                self._log(f"轮询异常：{e}")

            time.sleep(poll_interval)


# ══════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="狼人杀 AI Agent（单个玩家）")
    parser.add_argument("--room-id",      default=None,  help="游戏房间 ID（默认读 last_local_room.txt 或环境变量 ROOM_ID）")
    parser.add_argument("--player-id",    required=True, help="玩家唯一 ID（如 p2）")
    parser.add_argument("--name",         default=None,  help="玩家显示名称")
    parser.add_argument("--persona",      default="",    help="AI的情感/人设描述")
    parser.add_argument("--api-key",      default=None,  help="LLM API Key（覆盖 .env）")
    parser.add_argument("--model",        default=None,  help="LLM 模型名（覆盖 .env）")
    parser.add_argument("--llm-base-url", default=None,  help="LLM Base URL（覆盖 .env）")
    parser.add_argument("--backend-url",  default=None,  help="游戏后端地址（覆盖 .env）")
    parser.add_argument("--interval",     type=float, default=None, help="轮询间隔秒数（覆盖 .env）")
    args = parser.parse_args()

    # 命令行 > 环境变量 ROOM_ID > last_local_room.txt
    room_id     = resolve_room_id(args.room_id)
    api_key     = args.api_key      or os.getenv("LLM_API_KEY")   or ""
    model       = args.model        or os.getenv("LLM_MODEL",     "Qwen/Qwen2.5-72B-Instruct")
    llm_url     = args.llm_base_url or os.getenv("LLM_BASE_URL")
    backend_url = args.backend_url  or os.getenv("BACKEND_URL",   "http://127.0.0.1:8000")
    interval    = args.interval     or float(os.getenv("POLL_INTERVAL", "3"))

    if not room_id:
        print(
            "错误：请通过 --room-id 指定房间，或先运行网页单机开局以生成 last_local_room.txt，"
            "或设置环境变量 ROOM_ID。"
        )
        sys.exit(1)
    if not api_key:
        print("错误：请在 .env 中设置 LLM_API_KEY，或通过 --api-key 指定。")
        sys.exit(1)

    agent = WerewolfAgent(
        room_id      = room_id,
        player_id    = args.player_id,
        llm_api_key  = api_key,
        llm_model    = model,
        api_base_url = backend_url,
        llm_base_url = llm_url,
        name         = args.name,
        persona      = args.persona,
    )

    agent.run(poll_interval=interval)

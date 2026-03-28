"""
human_client.py —— 真人玩家 CLI 客户端
通过文字界面参与狼人杀游戏，支持 ANSI 彩色输出。
"""
from __future__ import annotations

import os
import sys
import time
import argparse

import requests
from dotenv import load_dotenv

from room_resolve import resolve_room_id

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ══════════════════════════════════════════════════════════════════
# ANSI 颜色常量
# ══════════════════════════════════════════════════════════════════
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    PURPLE = "\033[95m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    WHITE  = "\033[97m"

def colored(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + C.RESET

# Windows 终端需要手动开启 ANSI 支持
if sys.platform == "win32":
    os.system("")

# ══════════════════════════════════════════════════════════════════
# 角色与阶段的中文映射
# ══════════════════════════════════════════════════════════════════
ROLE_CN = {
    "werewolf": colored("狼人", C.RED, C.BOLD),
    "seer":     colored("预言家", C.YELLOW, C.BOLD),
    "witch":    colored("女巫", C.PURPLE, C.BOLD),
    "villager": colored("村民", C.GREEN, C.BOLD),
    "hunter":   colored("猎人", C.YELLOW, C.BOLD),
    None:       colored("未知", C.GRAY),
}
PHASE_CN = {
    "waiting":        "等待开始",
    "night_wolf_chat":"🌙 夜晚 - 狼人队内交流",
    "night_wolf":     "🌙 夜晚 - 狼人行动",
    "night_seer":     "🌙 夜晚 - 预言家行动",
    "night_witch":    "🌙 夜晚 - 女巫行动",
    "hunter_shot":    "🔫 猎人开枪",
    "day_discuss":    "☀️  白天 - 讨论阶段",
    "day_vote":       "☀️  白天 - 投票阶段",
    "day_result":     "📢 公布投票结果",
    "game_over":      "🏁 游戏结束",
}

# ══════════════════════════════════════════════════════════════════
# HumanClient 主类
# ══════════════════════════════════════════════════════════════════
class HumanClient:
    def __init__(self, room_id: str, player_id: str, backend_url: str) -> None:
        self.room_id    = room_id
        self.player_id  = player_id
        self.base_url   = backend_url.rstrip("/")

        self.last_phase       = ""
        self.last_round       = 0
        self.printed_log_count = 0       # 已打印的 day_logs 数量
        self.acted_phases: set[str] = set()  # 已行动的 "round:phase"

    # ──────────────────────────────────────────────
    # HTTP 工具
    # ──────────────────────────────────────────────
    def _headers(self) -> dict:
        return {"player-id": self.player_id}

    def _get_state(self) -> dict | None:
        try:
            r = requests.get(
                f"{self.base_url}/game/{self.room_id}/state",
                headers=self._headers(), timeout=5,
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                print(colored(
                    f"\n房间 [{self.room_id}] 不存在（后端重启或未开新局）。"
                    f"\n请 Ctrl+C 退出，重新开一局或更新 last_local_room.txt / --room-id。\n",
                    C.RED, C.BOLD,
                ))
                sys.exit(2)
        except requests.RequestException:
            pass
        return None

    def _post(self, path: str, payload: dict) -> dict | None:
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=payload, headers=self._headers(), timeout=10,
            )
            if r.status_code >= 400:
                print(colored(f"  ❌ 操作失败：{r.json().get('detail', r.text)}", C.RED))
                return None
            return r.json()
        except requests.RequestException as e:
            print(colored(f"  ❌ 网络错误：{e}", C.RED))
            return None

    # ──────────────────────────────────────────────
    # 界面渲染
    # ──────────────────────────────────────────────
    def _print_divider(self, title: str = "") -> None:
        line = "═" * 54
        if title:
            print(f"\n{colored(line, C.CYAN)}")
            print(colored(f"  {title}", C.CYAN, C.BOLD))
            print(colored(line, C.CYAN))
        else:
            print(colored(line, C.GRAY))

    def _render_header(self, state: dict) -> None:
        """阶段变化时打印完整状态头"""
        phase    = state["phase"]
        round_n  = state["round_num"]
        me       = state["players"].get(self.player_id, {})
        my_role  = me.get("role")
        is_alive = me.get("is_alive", False)

        self._print_divider(
            f"第 {round_n} 回合  |  {PHASE_CN.get(phase, phase)}"
        )

        # 自己的身份
        status_str = colored("存活", C.GREEN) if is_alive else colored("已死亡", C.RED)
        print(f"  你的身份：{ROLE_CN.get(my_role, '?')}   状态：{status_str}")

        # 狼人专属：显示队友
        if my_role == "werewolf":
            teammates = [
                colored(f"{p['name']}({pid})", C.RED, C.BOLD)
                for pid, p in state["players"].items()
                if pid != self.player_id and p.get("role") == "werewolf"
            ]
            if teammates:
                print(f"  {colored('★ 狼人队友：', C.RED, C.BOLD)}{', '.join(teammates)}")

        # 女巫专属：显示药水状态
        if my_role == "witch":
            antidote = colored("有", C.GREEN) if state.get("witch_has_antidote") else colored("已用", C.GRAY)
            poison   = colored("有", C.GREEN) if state.get("witch_has_poison")   else colored("已用", C.GRAY)
            print(f"  {colored('★ 解药：', C.PURPLE)}{antidote}   {colored('毒药：', C.PURPLE)}{poison}")

        # 存活玩家列表（狼人用红色标记队友）
        alive = []
        for pid, p in state["players"].items():
            if not p["is_alive"]:
                continue
            name_str = f"{p['name']}({pid})"
            if my_role == "werewolf" and p.get("role") == "werewolf" and pid != self.player_id:
                name_str = colored(name_str, C.RED)  # 队友红色
            alive.append(name_str)

        dead = [
            f"{colored(p['name'], C.GRAY)}[{p['role'] or '?'}]"
            for pid, p in state["players"].items()
            if not p["is_alive"]
        ]
        print(f"  存活（{len(alive)}）：{', '.join(alive)}")
        if dead:
            print(f"  已出局：{', '.join(dead)}")

    def _render_new_logs(self, state: dict) -> None:
        """打印尚未显示的新发言"""
        logs = state.get("day_logs", [])
        new  = logs[self.printed_log_count:]
        for log in new:
            name = log["player_name"]
            pid  = log["player_id"]
            msg  = log["message"]
            tag  = colored(f"[{name}({pid})]", C.YELLOW, C.BOLD)
            print(f"  {tag} {msg}")
        self.printed_log_count = len(logs)

    # ──────────────────────────────────────────────
    # 交互行动
    # ──────────────────────────────────────────────
    def _act(self, state: dict) -> None:
        """根据阶段提示真人输入并调用 API，失败则循环重试"""
        phase   = state["phase"]
        me      = state["players"].get(self.player_id, {})
        my_role = me.get("role")

        # ── 夜晚：狼人队内交流 ──
        if phase == "night_wolf_chat" and my_role == "werewolf":
            for w in state.get("wolf_whispers") or []:
                print(colored(
                    f"  [队友私语] {w.get('player_name', '')}({w.get('player_id', '')}): {w.get('message', '')}",
                    C.RED,
                ))
            while True:
                msg = input(colored("  你的队内私语（仅狼人可见）：", C.RED, C.BOLD)).strip()
                if not msg:
                    print(colored("  不能为空。", C.YELLOW))
                    continue
                res = self._post(f"/game/{self.room_id}/action/wolf_whisper", {"message": msg})
                if res:
                    print(colored("  ✅ 已发送。全员发过一条后进入击杀阶段。", C.GREEN))
                    break

        # ── 夜晚：狼人击杀 ──
        elif phase == "night_wolf" and my_role == "werewolf":
            alive_others = [
                pid for pid, p in state["players"].items()
                if p["is_alive"] and pid != self.player_id and p["role"] != "werewolf"
            ]
            print(colored(f"\n  [狼人] 可击杀目标：{', '.join(alive_others)}", C.RED))
            while True:
                tid = input(colored("  请输入要击杀的 player_id：", C.RED, C.BOLD)).strip()
                if not tid:
                    continue
                res = self._post(f"/game/{self.room_id}/action/wolf_kill", {"target_id": tid})
                if res:
                    print(colored("  ✅ 击杀目标已锁定，等待夜晚结束...", C.GREEN))
                    break

        # ── 夜晚：预言家查验 ──
        elif phase == "night_seer" and my_role == "seer":
            alive_others = [
                pid for pid, p in state["players"].items()
                if p["is_alive"] and pid != self.player_id
            ]
            print(colored(f"\n  [预言家] 可查验目标：{', '.join(alive_others)}", C.YELLOW))
            while True:
                tid = input(colored("  请输入要查验的 player_id：", C.YELLOW, C.BOLD)).strip()
                if not tid:
                    continue
                res = self._post(f"/game/{self.room_id}/action/seer_check", {"target_id": tid})
                if res:
                    name = state["players"][tid]["name"]
                    if res.get("is_werewolf"):
                        print(colored(f"\n  ★ 查验结果：{name}({tid}) 是【狼人】！", C.RED, C.BOLD))
                    else:
                        print(colored(f"\n  ★ 查验结果：{name}({tid}) 是【好人】。", C.GREEN, C.BOLD))
                    break

        # ── 夜晚：女巫行动 ──
        elif phase == "night_witch" and my_role == "witch":
            wolf_target  = state.get("wolf_target")
            has_antidote = state.get("witch_has_antidote")
            has_poison   = state.get("witch_has_poison")

            print(colored(f"\n  [女巫] 今晚被狼人击杀的玩家：", C.PURPLE, C.BOLD), end="")
            if wolf_target:
                wt_name = state["players"][wolf_target]["name"]
                print(colored(f"{wt_name}({wolf_target})", C.RED, C.BOLD))
            else:
                print(colored("无", C.GRAY))

            save = False
            poison_target = None

            if has_antidote and wolf_target:
                ans = input(colored(f"  是否使用解药救 {wt_name}？(y/n)：", C.PURPLE, C.BOLD)).strip().lower()
                save = (ans == "y")

            if has_poison and not save:
                alive_others = [
                    f"{p['name']}({pid})"
                    for pid, p in state["players"].items()
                    if p["is_alive"] and pid != self.player_id
                ]
                print(colored(f"  可毒目标：{', '.join(alive_others)}", C.PURPLE))
                ans = input(colored("  输入要毒的 player_id（直接回车则不用毒）：", C.PURPLE, C.BOLD)).strip()
                poison_target = ans if ans else None

            res = self._post(f"/game/{self.room_id}/action/witch", {
                "save": save,
                "poison_target_id": poison_target,
            })
            if res:
                print(colored("  ✅ 女巫行动完成。", C.GREEN))

        # ── 白天发言 ──
        elif phase == "day_discuss":
            print(colored("\n  [发言] 轮到你发言了：", C.BLUE, C.BOLD))
            while True:
                content = input(colored("  >>> ", C.BLUE, C.BOLD)).strip()
                if not content:
                    print(colored("  发言不能为空，请重新输入。", C.YELLOW))
                    continue
                res = self._post(f"/game/{self.room_id}/action/speak", {"content": content})
                if res:
                    break

        # ── 白天投票 ──
        elif phase == "day_vote":
            alive_others = [
                f"{p['name']}({pid})"
                for pid, p in state["players"].items()
                if p["is_alive"] and pid != self.player_id
            ]
            print(colored(f"\n  [投票] 存活玩家：{', '.join(alive_others)}", C.CYAN))
            while True:
                tid = input(colored("  输入要放逐的 player_id（回车弃票）：", C.CYAN, C.BOLD)).strip()
                if not tid:
                    self._post(f"/game/{self.room_id}/action/abstain", {})
                    print(colored("  已弃票（不计入任何候选人）。", C.GRAY))
                    break
                res = self._post(f"/game/{self.room_id}/action/vote", {"target_id": tid})
                if res:
                    print(colored(f"  ✅ 已投票放逐 {tid}。", C.GREEN))
                    break

        # ── 猎人开枪 ──
        elif phase == "hunter_shot" and my_role == "hunter":
            alive_targets = [
                f"{p['name']}({pid})"
                for pid, p in state["players"].items()
                if p["is_alive"] and pid != self.player_id
            ]
            print(colored(f"\n  [猎人] 你已出局，可开枪带走一名存活玩家，或放弃。", C.YELLOW, C.BOLD))
            print(colored(f"  存活玩家：{', '.join(alive_targets)}", C.YELLOW))
            while True:
                tid = input(colored("  输入要击毙的 player_id（回车放弃开枪）：", C.YELLOW, C.BOLD)).strip()
                res = self._post(
                    f"/game/{self.room_id}/action/hunter_shoot",
                    {"target_id": tid if tid else None},
                )
                if res:
                    if tid:
                        print(colored(f"  ✅ 猎人开枪击毙 {tid}。", C.GREEN))
                    else:
                        print(colored("  ✅ 猎人放弃开枪。", C.GRAY))
                    break

    # ──────────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────────
    def run(self) -> None:
        print(colored("\n狼人杀 - 真人客户端启动", C.CYAN, C.BOLD))
        print(colored(f"房间：{self.room_id}  玩家：{self.player_id}\n", C.GRAY))

        while True:
            state = self._get_state()
            if state is None:
                print(colored("  ⚠ 无法连接服务器，3 秒后重试...", C.YELLOW))
                time.sleep(3)
                continue

            phase    = state["phase"]
            round_n  = state["round_num"]
            phase_key = f"{round_n}:{phase}"
            if phase == "night_wolf_chat":
                phase_key = f"{round_n}:{phase}:{self.player_id}"
            me        = state["players"].get(self.player_id, {})
            is_alive  = me.get("is_alive", False)
            my_role   = me.get("role")

            # ── 阶段切换时重绘头部 ──
            if phase != self.last_phase or round_n != self.last_round:
                # 只有新回合才重置发言计数；同一回合不同阶段切换不重打
                if round_n != self.last_round:
                    self.printed_log_count = 0
                self._render_header(state)
                self.last_phase = phase
                self.last_round = round_n

            # ── 打印新发言 ──
            self._render_new_logs(state)

            # ── 游戏结束 ──
            if phase == "game_over":
                self._print_divider("游戏结束")
                print(colored("  感谢参与！", C.GREEN, C.BOLD))
                break

            # ── 猎人开枪：死亡但需要行动 ──
            is_pending_hunter = (
                phase == "hunter_shot"
                and my_role == "hunter"
                and not is_alive
                and state.get("pending_hunter_id") == self.player_id
            )

            # ── 死亡后只观战（猎人开枪除外）──
            if not is_alive and not is_pending_hunter:
                time.sleep(1)
                continue

            # ── 判断是否轮到自己行动 ──
            need_act = False
            if phase == "night_wolf_chat" and my_role == "werewolf": need_act = True
            if phase == "night_wolf"  and my_role == "werewolf": need_act = True
            if phase == "night_seer"  and my_role == "seer":     need_act = True
            if phase == "night_witch" and my_role == "witch":    need_act = True
            if phase == "day_discuss":                            need_act = True
            if phase == "day_vote":                               need_act = True
            if is_pending_hunter:                                 need_act = True

            if need_act and phase_key not in self.acted_phases:
                self._act(state)
                self.acted_phases.add(phase_key)
            else:
                time.sleep(1)


# ══════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="狼人杀真人 CLI 客户端")
    parser.add_argument("--room-id",    default=None, help="游戏房间 ID（默认 last_local_room.txt / ROOM_ID）")
    parser.add_argument("--player-id",  default=None, help="玩家 ID（默认读取 .env 的 HUMAN_PLAYER_ID）")
    parser.add_argument("--backend-url",default=None, help="后端地址（覆盖 .env）")
    args = parser.parse_args()

    room_id     = resolve_room_id(args.room_id)
    player_id   = args.player_id   or os.getenv("HUMAN_PLAYER_ID",  "p1")
    backend_url = args.backend_url or os.getenv("BACKEND_URL",      "http://127.0.0.1:8000")

    if not room_id:
        print(colored(
            "错误：请通过 --room-id 指定，或先网页开局生成 last_local_room.txt，或设置环境变量 ROOM_ID。",
            C.RED,
        ))
        sys.exit(1)

    client = HumanClient(room_id, player_id, backend_url)
    client.run()

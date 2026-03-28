from __future__ import annotations

import sys
import random
from typing import Optional

from models import DayLog, SystemLog, GamePhase, GameState, Player, Role, WolfWhisper


# ══════════════════════════════════════════════════════════════════
# 胜负结果常量
# ══════════════════════════════════════════════════════════════════
WIN_VILLAGERS = "villagers_win"   # 好人胜利
WIN_WEREWOLVES = "werewolves_win" # 狼人胜利
GAME_CONTINUE  = "continue"       # 游戏继续


class GameEngine:
    """
    狼人杀核心逻辑层。
    职责：维护并操作 GameState，不涉及任何网络 / 持久化代码。
    所有状态变更都通过本类的方法进行，外部不应直接修改 state 字段。
    """

    def __init__(self, state: GameState) -> None:
        self.state = state

    # ──────────────────────────────────────────────
    # 内部工具方法
    # ──────────────────────────────────────────────

    def _get_alive_players(self) -> list[Player]:
        """返回所有存活玩家列表。"""
        return [p for p in self.state.players.values() if p.is_alive]

    def _get_alive_by_role(self, role: Role) -> list[Player]:
        """返回指定角色且存活的玩家列表。"""
        return [p for p in self._get_alive_players() if p.role == role]

    def _require_phase(self, *phases: GamePhase) -> None:
        """断言当前阶段必须是指定阶段之一，否则抛出 ValueError。"""
        if self.state.phase not in phases:
            allowed = " / ".join(p.value for p in phases)
            raise ValueError(
                f"当前阶段 [{self.state.phase.value}] 不允许此操作，"
                f"需要处于 [{allowed}] 阶段。"
            )

    def _require_alive(self, player_id: str) -> Player:
        """
        断言目标玩家存在且存活，返回 Player 对象。
        用于技能目标的合法性校验。
        """
        player = self.state.players.get(player_id)
        if player is None:
            raise ValueError(f"玩家 [{player_id}] 不存在。")
        if not player.is_alive:
            raise ValueError(f"玩家 [{player_id}]（{player.name}）已经死亡，不能成为目标。")
        return player

    def _kill_player(self, player_id: str) -> None:
        """
        将玩家标记为死亡，并立即检查胜负条件。
        游戏中不翻牌（夜间出局与白天放逐均不公开身份），全员身份仅在游戏结束后由接口下发。
        """
        p = self.state.players[player_id]
        p.is_alive = False

    def _advance_to_next_night_phase(self) -> None:
        """
        夜晚阶段智能推进器。
        按 NIGHT_WOLF -> NIGHT_SEER -> NIGHT_WITCH -> DAY_DISCUSS 顺序检查
        （狼人先经 NIGHT_WOLF_CHAT 交流后再进入 NIGHT_WOLF），
        若对应角色已全部死亡（或女巫无药可用），则自动跳过该阶段。

        调用时机：
          - wolf_kill() 执行完毕后
          - seer_check() 执行完毕后
          - witch_action() 执行完毕后（此时会进入 DAY_DISCUSS 并触发结算）
        """
        # 从当前阶段往后推
        current = self.state.phase

        if current == GamePhase.NIGHT_WOLF:
            # 尝试推进到 NIGHT_SEER
            if self._get_alive_by_role(Role.SEER):
                self.state.phase = GamePhase.NIGHT_SEER
                return
            # 预言家已死，继续尝试 NIGHT_WITCH
            current = GamePhase.NIGHT_SEER

        if current == GamePhase.NIGHT_SEER:
            # 女巫存活且至少有一瓶药
            witch_alive = bool(self._get_alive_by_role(Role.WITCH))
            has_potion = self.state.witch_has_antidote or self.state.witch_has_poison
            if witch_alive and has_potion:
                self.state.phase = GamePhase.NIGHT_WITCH
                return
            # 女巫不可用，直接结算并进白天
            current = GamePhase.NIGHT_WITCH

        if current == GamePhase.NIGHT_WITCH:
            # 所有夜晚行动结束，结算死亡并进入白天（或猎人开枪阶段）
            self._settle_night_deaths()
            if self.state.phase == GamePhase.HUNTER_SHOT:
                return
            if self.state.phase != GamePhase.GAME_OVER:
                self.state.phase = GamePhase.DAY_DISCUSS
                alive_players = [p.player_id for p in self.state.players.values() if p.is_alive]
                alive_players.sort()
                self.state.speaker_sequence = alive_players
                self.state.current_speaker = alive_players[0] if alive_players else None

    # ──────────────────────────────────────────────
    # 初始化与发牌
    # ──────────────────────────────────────────────

    def start_game(self) -> None:
        """
        开始游戏：检查人数、随机发牌、推进阶段。
        角色配置：2 狼人 + 1 预言家 + 1 女巫 + 1 猎人 + 其余村民。
        """
        self._require_phase(GamePhase.WAITING)

        player_count = len(self.state.players)
        if not (6 <= player_count <= 8):
            raise ValueError(
                f"游戏需要 6-8 名玩家，当前有 {player_count} 名玩家。"
            )

        # 构造角色列表：固定 2 狼 + 1 预言家 + 1 女巫 + 1 猎人 + 剩余村民
        roles: list[Role] = (
            [Role.WEREWOLF] * 2
            + [Role.SEER]
            + [Role.WITCH]
            + [Role.HUNTER]
            + [Role.VILLAGER] * (player_count - 5)
        )
        random.shuffle(roles)

        for player, role in zip(self.state.players.values(), roles):
            player.role = role

        self.state.wolf_whispers = []
        self.state.phase = GamePhase.NIGHT_WOLF_CHAT
        print(f"[GameEngine] 游戏开始！共 {player_count} 名玩家，进入第 1 夜（狼人队内交流）。")

    # ──────────────────────────────────────────────
    # 夜晚技能
    # ──────────────────────────────────────────────

    # 每夜最多讨论多少轮（每轮 = 每名存活狼人各发一条）；达到上限无论是否统一都进击杀
    WOLF_CHAT_MAX_ROUNDS = 3

    def wolf_whisper(self, player_id: str, message: str, target_id: str | None = None) -> None:
        """
        狼人夜间队内私语。
        每轮（全员各发一条）结束后检查是否所有狼人目标一致：
          - 一致 → 立即进入 NIGHT_WOLF（击杀阶段）
          - 不一致且未超上限 → 继续讨论
          - 达到 WOLF_CHAT_MAX_ROUNDS 仍未统一 → 强制进入 NIGHT_WOLF
        """
        self._require_phase(GamePhase.NIGHT_WOLF_CHAT)
        msg = (message or "").strip()
        if not msg:
            raise ValueError("私语内容不能为空。")
        player = self.state.players.get(player_id)
        if player is None or not player.is_alive:
            raise ValueError(f"玩家 [{player_id}] 不存在或已死亡。")
        if player.role != Role.WEREWOLF:
            raise ValueError(f"玩家 [{player_id}] 不是狼人，无法参与队内交流。")

        self.state.wolf_whispers.append(
            WolfWhisper(
                player_id=player_id,
                player_name=player.name,
                message=msg[:800],
                round_num=self.state.round_num,
                target_id=target_id,
            )
        )
        print(f"[GameEngine] 狼人私语 [{player.name}] 目标={target_id}：{msg[:80]}{'…' if len(msg) > 80 else ''}")

        alive_wolf_ids = [p.player_id for p in self._get_alive_by_role(Role.WEREWOLF)]
        cur_round = self.state.round_num

        # 统计本夜各讨论轮次（按 discussion_round = 每名狼人发言次数）
        counts: dict[str, int] = {}
        for w in self.state.wolf_whispers:
            if w.round_num == cur_round:
                counts[w.player_id] = counts.get(w.player_id, 0) + 1

        # 最少发言次数 = 当前已完成的讨论轮数
        min_count = min((counts.get(wid, 0) for wid in alive_wolf_ids), default=0)

        # 每当全员都完成了同等次数的发言，视为一轮结束，检查共识
        if alive_wolf_ids and all(counts.get(wid, 0) == min_count for wid in alive_wolf_ids) and min_count > 0:
            # 取每名狼人本轮（第 min_count 次）发言的 target_id
            round_targets: list[str | None] = []
            for wid in alive_wolf_ids:
                wolf_msgs = [
                    w for w in self.state.wolf_whispers
                    if w.round_num == cur_round and w.player_id == wid
                ]
                if wolf_msgs:
                    round_targets.append(wolf_msgs[-1].target_id)

            valid_targets = [t for t in round_targets if t]
            consensus = len(valid_targets) == len(alive_wolf_ids) and len(set(valid_targets)) == 1

            if consensus:
                self.state.phase = GamePhase.NIGHT_WOLF
                print(f"[GameEngine] 狼人达成共识，目标：{valid_targets[0]}，进入击杀阶段。")
            elif min_count >= self.WOLF_CHAT_MAX_ROUNDS:
                self.state.phase = GamePhase.NIGHT_WOLF
                print(f"[GameEngine] 狼人讨论达到上限 {self.WOLF_CHAT_MAX_ROUNDS} 轮，强制进入击杀阶段。")

    def wolf_kill(self, target_id: str) -> None:
        """
        狼人集体选定本夜击杀目标。
        只能在 NIGHT_WOLF 阶段调用。
        目标必须存活，允许自刀。
        """
        self._require_phase(GamePhase.NIGHT_WOLF)
        target = self._require_alive(target_id)

        # 允许自刀骗药，移除身份检查
        # if target.role == Role.WEREWOLF:
        #     raise ValueError("狼人不能击杀自己的同伴。")

        self.state.wolf_target = target_id
        print(f"[GameEngine] 狼人选择击杀：{target.name}（{target_id}）")

        # 推进到下一个夜晚阶段
        self._advance_to_next_night_phase()

    def seer_check(self, checker_id: str, target_id: str) -> bool:
        """
        预言家查验目标玩家的阵营。
        只能在 NIGHT_SEER 阶段调用，且 checker_id 必须是存活的预言家。

        返回值：True = 目标是狼人，False = 目标是好人。
        """
        self._require_phase(GamePhase.NIGHT_SEER)

        checker = self.state.players.get(checker_id)
        if checker is None or not checker.is_alive:
            raise ValueError(f"预言家 [{checker_id}] 不存在或已死亡。")
        if checker.role != Role.SEER:
            raise ValueError(f"玩家 [{checker_id}] 不是预言家，无法使用查验技能。")

        target = self._require_alive(target_id)

        is_wolf = target.role == Role.WEREWOLF

        # 记录本夜查验结果（仅当夜）及历史累计
        self.state.seer_result = {target_id: target.role}
        self.state.seer_history[target_id] = target.role.value

        result_text = "狼人" if is_wolf else "好人"
        print(f"[GameEngine] 预言家查验 {target.name}（{target_id}）→ {result_text}")

        # 推进到下一个夜晚阶段
        self._advance_to_next_night_phase()
        return is_wolf

    def witch_action(
        self,
        witch_id: str,
        save: bool = False,
        poison_target_id: Optional[str] = None,
    ) -> None:
        """
        女巫行动：本夜可选择使用解药（救人）或毒药（毒人），也可两者都不用。
        规则约束：
          - 解药只能救当晚被狼人杀死的人，且每局只有一瓶。
          - 毒药每局只有一瓶，目标必须存活。
          - 同一夜不能既救人又毒人（经典规则）。

        参数：
          save              : True 表示使用解药救人（救的是 wolf_target）
          poison_target_id  : 不为 None 表示使用毒药毒指定玩家
        """
        self._require_phase(GamePhase.NIGHT_WITCH)

        witch = self.state.players.get(witch_id)
        if witch is None or not witch.is_alive:
            raise ValueError(f"女巫 [{witch_id}] 不存在或已死亡。")
        if witch.role != Role.WITCH:
            raise ValueError(f"玩家 [{witch_id}] 不是女巫，无法使用药水技能。")

        if save and poison_target_id:
            raise ValueError("同一夜不能同时使用解药和毒药（经典规则）。")

        # 提前记录将被救的目标（在 wolf_target 被清空前）
        _saved_target_id: str | None = self.state.wolf_target if save else None

        if save:
            if not self.state.witch_has_antidote:
                raise ValueError("解药已经用完，无法再次使用。")
            if self.state.wolf_target is None:
                raise ValueError("今晚没有被狼人击杀的目标，无需使用解药。")
            # 解药：将狼人目标从待死名单中移除
            self.state.dead_this_night = [
                pid for pid in self.state.dead_this_night
                if pid != self.state.wolf_target
            ]
            # wolf_target 此时还未加入 dead_this_night（在 _settle_night_deaths 里处理）
            # 用一个标志位表示"今晚狼人目标被救了"
            self.state.wolf_target = None
            self.state.witch_has_antidote = False
            print(f"[GameEngine] 女巫使用了解药，救下了今晚被狼人选中的目标。")

        if poison_target_id:
            if not self.state.witch_has_poison:
                raise ValueError("毒药已经用完，无法再次使用。")
            target = self._require_alive(poison_target_id)
            self.state.dead_this_night.append(poison_target_id)
            self.state.poisoned_this_night.append(poison_target_id)
            self.state.witch_has_poison = False
            print(f"[GameEngine] 女巫毒死了：{target.name}（{poison_target_id}）")

        # 记录女巫本夜用药历史（即使什么都没做也记录"跳过"）
        if save or poison_target_id:
            saved_name = self.state.players[_saved_target_id].name if _saved_target_id else None
            poisoned_name = self.state.players[poison_target_id].name if poison_target_id else None
            self.state.witch_actions_history.append({
                "round": self.state.round_num,
                "saved_id": _saved_target_id,
                "saved_name": saved_name,
                "poisoned_id": poison_target_id,
                "poisoned_name": poisoned_name,
            })

        # 推进到下一个夜晚阶段（此处 current == NIGHT_WITCH，会触发结算并进白天）
        self._advance_to_next_night_phase()

    # ──────────────────────────────────────────────
    # 夜晚结算（私有）
    # ──────────────────────────────────────────────

    def _settle_night_deaths(self) -> None:
        """
        结算本夜死亡名单。
        若猎人死于非毒杀（狼刀等），游戏未结束时进入 HUNTER_SHOT；毒死的猎人不触发开枪。
        """
        # 狼人目标若未被女巫救，加入死亡名单
        if self.state.wolf_target and self.state.wolf_target not in self.state.dead_this_night:
            self.state.dead_this_night.append(self.state.wolf_target)

        if self.state.dead_this_night:
            names = [self.state.players[pid].name for pid in self.state.dead_this_night]
            print(f"[GameEngine] 昨夜死亡公告：{', '.join(names)}")
        else:
            print("[GameEngine] 昨夜是平安夜，无人死亡。")

        to_kill = list(self.state.dead_this_night)
        poisoned = set(self.state.poisoned_this_night)

        hunter_shooter: Optional[str] = None
        for pid in to_kill:
            p = self.state.players.get(pid)
            if p and p.role == Role.HUNTER and pid not in poisoned:
                hunter_shooter = pid

        for pid in to_kill:
            self._kill_player(pid)
            if self.check_win_condition() != GAME_CONTINUE:
                hunter_shooter = None
                break

        # 累计记录本夜死亡（带回合号，永不清空）
        for pid in to_kill:
            self.state.night_deaths_history.append({
                "round_num": self.state.round_num,
                "player_id": pid,
            })

        # 清空夜晚临时状态
        self.state.wolf_target = None
        self.state.seer_result = None
        self.state.dead_this_night = []
        self.state.poisoned_this_night = []

        if self.state.phase == GamePhase.GAME_OVER:
            return

        if hunter_shooter:
            self.state.pending_hunter_id = hunter_shooter
            self.state.hunter_shot_origin = "night"
            self.state.phase = GamePhase.HUNTER_SHOT
            print(f"[GameEngine] 猎人 [{hunter_shooter}] 可开枪（死于非毒）。")

    def hunter_shoot(self, shooter_id: str, target_id: Optional[str]) -> None:
        """
        猎人出局后开枪：带走一名存活玩家，或放弃（target_id 为空）。
        仅在 HUNTER_SHOT 阶段、且 shooter_id 为 pending_hunter_id 时可调用。
        """
        self._require_phase(GamePhase.HUNTER_SHOT)
        if self.state.pending_hunter_id != shooter_id:
            raise ValueError("当前不是待开枪的猎人。")
        hunter = self.state.players[shooter_id]
        if hunter.role != Role.HUNTER:
            raise ValueError("只有猎人可以执行开枪。")
        origin = self.state.hunter_shot_origin or "night"

        tid = (target_id or "").strip()
        if not tid:
            self._finish_hunter_shot_phase(origin)
            print(f"[GameEngine] 猎人 [{shooter_id}] 放弃开枪。")
            return

        if tid == shooter_id:
            raise ValueError("不能带走自己。")
        self._require_alive(tid)
        print(f"[GameEngine] 猎人 [{shooter_id}] 带走 {self.state.players[tid].name}（{tid}）。")
        self._kill_player(tid)
        self.check_win_condition()

        self.state.pending_hunter_id = None
        self.state.hunter_shot_origin = None

        if self.state.phase == GamePhase.GAME_OVER:
            return

        self._finish_hunter_shot_phase(origin)

    def _finish_hunter_shot_phase(self, origin: str) -> None:
        """猎人开枪结束或放弃后，进入白天讨论或投票结果阶段。"""
        self.state.pending_hunter_id = None
        self.state.hunter_shot_origin = None
        if origin == "night":
            self.state.phase = GamePhase.DAY_DISCUSS
            alive_players = sorted([p.player_id for p in self.state.players.values() if p.is_alive])
            self.state.speaker_sequence = alive_players
            self.state.current_speaker = alive_players[0] if alive_players else None
        else:
            self.state.phase = GamePhase.DAY_RESULT

    # ──────────────────────────────────────────────
    # 白天互动
    # ──────────────────────────────────────────────

    def add_system_log(self, message: str, player_id: str = "system", player_name: str = "系统", log_type: str = "info") -> None:
        log = SystemLog(
            player_id=player_id,
            player_name=player_name,
            message=message,
            log_type=log_type
        )
        self.state.system_logs.append(log)
        print(f"[系统日志 {log_type}] {player_name}: {message}")

    def add_day_log(self, player_id: str, content: str) -> None:
        """
        记录玩家白天发言。
        死亡玩家不能发言（鬼魂模式不在本期实现范围内）。
        """
        self._require_phase(GamePhase.DAY_DISCUSS)

        player = self.state.players.get(player_id)
        if player is None:
            raise ValueError(f"玩家 [{player_id}] 不存在。")
        if not player.is_alive:
            raise ValueError(f"玩家 [{player_id}]（{player.name}）已死亡，不能发言。")

        if self.state.current_speaker and self.state.current_speaker != player_id:
            raise ValueError(f"现在不是玩家 [{player_id}] 的发言时间。当前应该发言的是 [{self.state.current_speaker}]。")

        log = DayLog(
            player_id=player_id,
            player_name=player.name,
            message=content,
            round_num=self.state.round_num,
        )
        self.state.day_logs.append(log)
        print(f"[{player.name}] 发言：{content}")
        
        # 指向下一个发言者
        seq = self.state.speaker_sequence
        try:
            curr_idx = seq.index(player_id)
            if curr_idx + 1 < len(seq):
                self.state.current_speaker = seq[curr_idx + 1]
            else:
                self.state.current_speaker = None
        except ValueError:
            pass

    def cast_vote(self, voter_id: str, target_id: str) -> None:
        """
        投票阶段：voter_id 投票放逐 target_id。
        约束：
          - 只能在 DAY_VOTE 阶段调用。
          - 投票者和被投票者都必须存活。
          - 每人只能投一票（重复投票会覆盖上一票）。
        """
        self._require_phase(GamePhase.DAY_VOTE)

        voter = self.state.players.get(voter_id)
        if voter is None or not voter.is_alive:
            raise ValueError(f"投票者 [{voter_id}] 不存在或已死亡。")

        self._require_alive(target_id)

        # 若此前弃票，改为正式投票
        if voter_id in self.state.vote_abstains:
            self.state.vote_abstains.remove(voter_id)

        # 撤销该玩家之前的投票（如有）
        for votes_list in self.state.votes.values():
            if voter_id in votes_list:
                votes_list.remove(voter_id)

        self.state.votes.setdefault(target_id, []).append(voter_id)
        target_name = self.state.players[target_id].name
        if target_id == voter_id:
            print(f"[GameEngine] {voter.name} 投票放逐自己（{voter_id}）")
        else:
            print(f"[GameEngine] {voter.name} 投票放逐 {target_name}（{target_id}）")

    def cast_vote_abstain(self, voter_id: str) -> None:
        """
        弃票：不增加任何候选人的得票，但视为已完成本轮投票环节。
        若之后同一玩家再调用 cast_vote，则弃票记录会被移除。
        """
        self._require_phase(GamePhase.DAY_VOTE)

        voter = self.state.players.get(voter_id)
        if voter is None or not voter.is_alive:
            raise ValueError(f"投票者 [{voter_id}] 不存在或已死亡。")

        for votes_list in self.state.votes.values():
            if voter_id in votes_list:
                votes_list.remove(voter_id)

        if voter_id not in self.state.vote_abstains:
            self.state.vote_abstains.append(voter_id)
        print(f"[GameEngine] {voter.name} 弃票（不计入任何候选人）")

    def settle_voting(self) -> Optional[str]:
        """
        结算投票：得票最多者出局，平票则无人出局（简化规则）。
        结算后将阶段推进到 DAY_RESULT（展示出局结果的缓冲阶段）。
        同时触发 check_win_condition()。

        返回值：出局玩家的 player_id，或 None（平票时）。
        """
        self._require_phase(GamePhase.DAY_VOTE)

        # 仅统计仍有投票人的目标（去掉空列表）
        vote_counts = {
            pid: len(voters)
            for pid, voters in self.state.votes.items()
            if voters
        }
        eliminated_id: Optional[str] = None
        was_hunter = False

        if not vote_counts:
            print("[GameEngine] 本轮无人投出有效票（全员弃票），无人出局。")
            self.state.votes = {}
            self.state.vote_abstains = []
            self.state.phase = GamePhase.DAY_RESULT
            return None
        max_votes = max(vote_counts.values())
        top_candidates = [pid for pid, cnt in vote_counts.items() if cnt == max_votes]

        if len(top_candidates) > 1:
            # 平票，无人出局
            names = [self.state.players[pid].name for pid in top_candidates]
            print(f"[GameEngine] 投票平局（{', '.join(names)} 各得 {max_votes} 票），无人出局。")
        else:
            eliminated_id = top_candidates[0]
            was_hunter = self.state.players[eliminated_id].role == Role.HUNTER
            eliminated_name = self.state.players[eliminated_id].name
            print(f"[GameEngine] 投票结果：{eliminated_name}（{eliminated_id}）被放逐，得票 {max_votes}。")
            self._kill_player(eliminated_id)
            self.check_win_condition()

        # 清空投票与弃票记录；若已因胜负判定结束，不得覆盖 GAME_OVER
        self.state.votes = {}
        self.state.vote_abstains = []
        if self.state.phase == GamePhase.GAME_OVER:
            return eliminated_id

        if eliminated_id is not None and was_hunter:
            self.state.pending_hunter_id = eliminated_id
            self.state.hunter_shot_origin = "vote"
            self.state.phase = GamePhase.HUNTER_SHOT
        else:
            self.state.phase = GamePhase.DAY_RESULT
        return eliminated_id

    # ──────────────────────────────────────────────
    # 推进到下一夜
    # ──────────────────────────────────────────────

    def start_next_night(self) -> None:
        """
        由外部（前端按钮 / 定时器 / API）手动触发，从 DAY_RESULT 推进到下一夜。
        职责：
          - round_num + 1
          - 清空白天发言日志
          - 将阶段设为 NIGHT_WOLF
        注意：此时游戏应尚未结束，调用前请确认 phase != GAME_OVER。
        """
        if self.state.phase == GamePhase.GAME_OVER:
            raise ValueError("游戏已结束，无法开始新的夜晚。")
        self._require_phase(GamePhase.DAY_RESULT)

        self.state.round_num += 1
        # 将当轮发言归档进历史，再清空当轮
        self.state.day_logs_history.extend(self.state.day_logs)
        self.state.day_logs = []
        self.state.pending_hunter_id = None
        self.state.hunter_shot_origin = None
        self.state.phase = GamePhase.NIGHT_WOLF_CHAT
        print(f"[GameEngine] 进入第 {self.state.round_num} 夜（狼人队内交流）。")

    # ──────────────────────────────────────────────
    # 胜负判断
    # ──────────────────────────────────────────────

    def check_win_condition(self) -> str:
        """
        检查胜负条件，每次有玩家死亡后调用。
        - 存活狼人 == 0           → 好人胜利
        - 存活狼人 >= 存活好人数   → 狼人胜利
        - 否则                    → 游戏继续

        返回值：WIN_VILLAGERS / WIN_WEREWOLVES / GAME_CONTINUE
        """
        alive_wolves  = len(self._get_alive_by_role(Role.WEREWOLF))
        alive_villagers = len([
            p for p in self._get_alive_players()
            if p.role != Role.WEREWOLF
        ])

        if alive_wolves == 0:
            self.state.phase = GamePhase.GAME_OVER
            self.state.winner = WIN_VILLAGERS
            print(f"[GameEngine] ★ 游戏结束：好人阵营胜利！存活好人 {alive_villagers} 名。")
            return WIN_VILLAGERS

        if alive_wolves >= alive_villagers:
            self.state.phase = GamePhase.GAME_OVER
            self.state.winner = WIN_WEREWOLVES
            print(f"[GameEngine] ★ 游戏结束：狼人阵营胜利！狼人 {alive_wolves} vs 好人 {alive_villagers}。")
            return WIN_WEREWOLVES

        return GAME_CONTINUE


# ══════════════════════════════════════════════════════════════════
# Mock 测试：模拟从发牌到第一个完整回合（夜晚 + 白天 + 投票）
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    from models import GameState

    # ── 1. 构造玩家 ──
    players_raw = [
        Player(player_id="p1", name="Alice",   is_ai=False),
        Player(player_id="p2", name="Bob",     is_ai=True),
        Player(player_id="p3", name="Charlie", is_ai=True),
        Player(player_id="p4", name="Diana",   is_ai=True),
        Player(player_id="p5", name="Eve",     is_ai=True),
        Player(player_id="p6", name="Frank",   is_ai=True),
    ]
    state = GameState(
        game_id="test-001",
        players={p.player_id: p for p in players_raw},
    )
    engine = GameEngine(state)

    # ── 2. 开始游戏（随机发牌）──
    print("\n" + "═" * 50)
    print("【发牌阶段】")
    engine.start_game()

    # 打印角色分配（真实游戏中此信息不对外公开）
    for p in state.players.values():
        print(f"  {p.name}({p.player_id}) → {p.role.value}")

    # 找到各角色的 player_id（测试用，模拟服务端视角）
    wolves   = [p.player_id for p in state.players.values() if p.role == Role.WEREWOLF]
    seer     = next((p.player_id for p in state.players.values() if p.role == Role.SEER),   None)
    witch    = next((p.player_id for p in state.players.values() if p.role == Role.WITCH),  None)
    villagers = [p.player_id for p in state.players.values() if p.role == Role.VILLAGER]

    # ── 3. 夜晚 Round 1 ──
    print("\n" + "═" * 50)
    print(f"【第 1 夜 - 狼人行动】当前阶段：{state.phase.value}")

    # 狼人队内私语后击杀
    wolf_target = villagers[0] if villagers else seer
    for wid in wolves:
        engine.wolf_whisper(wid, "先商量一下，今晚刀这个。")
    engine.wolf_kill(wolf_target)

    # 预言家查验（若存活）
    if state.phase == GamePhase.NIGHT_SEER and seer:
        print(f"\n【第 1 夜 - 预言家行动】当前阶段：{state.phase.value}")
        check_target = wolves[0]  # 预言家"恰好"查了一只狼（测试场景）
        is_wolf = engine.seer_check(seer, check_target)
        print(f"  查验结果：{state.players[check_target].name} 是{'狼人' if is_wolf else '好人'}")

    # 女巫行动（若存活）
    if state.phase == GamePhase.NIGHT_WITCH and witch:
        print(f"\n【第 1 夜 - 女巫行动】当前阶段：{state.phase.value}")
        # 女巫选择不救也不毒（观望策略）
        engine.witch_action(witch, save=False, poison_target_id=None)

    # ── 4. 白天发言 ──
    print(f"\n" + "═" * 50)
    print(f"【第 1 天 - 白天发言】当前阶段：{state.phase.value}")

    alive_now = engine._get_alive_players()
    speeches = [
        "我昨晚查了 p2，是好人，大家注意别误伤。",
        "我觉得 p3 很可疑，昨天一直没说话。",
        "我支持查 p4，他的反应很奇怪。",
        "大家冷静，不要乱投票。",
    ]
    for i, player in enumerate(alive_now):
        engine.add_day_log(player.player_id, speeches[i % len(speeches)])

    # 切换到投票阶段（真实系统由 API 触发，这里手动推进）
    state.phase = GamePhase.DAY_VOTE

    # ── 5. 投票 ──
    print(f"\n" + "═" * 50)
    print(f"【第 1 天 - 投票阶段】当前阶段：{state.phase.value}")

    alive_now = engine._get_alive_players()
    # 所有存活玩家投票给第一个存活的狼人（测试场景，好人赢了投票）
    vote_target = wolves[0]
    for player in alive_now:
        if player.player_id != vote_target:
            engine.cast_vote(player.player_id, vote_target)

    eliminated = engine.settle_voting()

    # ── 6. 结果展示阶段 ──
    print(f"\n" + "═" * 50)
    print(f"【DAY_RESULT】当前阶段：{state.phase.value}")
    if eliminated:
        print(f"  出局玩家：{state.players[eliminated].name}（{eliminated}），角色：{state.players[eliminated].role.value}")

    # ── 7. 若游戏未结束，进入下一夜 ──
    if state.phase != GamePhase.GAME_OVER:
        engine.start_next_night()
        print(f"\n当前阶段：{state.phase.value}，第 {state.round_num} 夜开始。")
    else:
        print("\n游戏已结束，无需继续。")

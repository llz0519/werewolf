import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Crown,
  Mic,
  Moon,
  RefreshCw,
  Skull,
  Sun,
  Target,
  User,
  MessageSquare,
  Vote,
  WandSparkles,
} from "lucide-react";

import { useGameState } from "../hooks/useGameState";
import type { GamePhase, Player, Role } from "../types/game";

interface GameRoomProps {
  roomId: string;
  playerId: string;
  onLeave?: () => void;
}

const phaseLabelMap: Record<GamePhase, string> = {
  waiting: "等待开始",
  night_wolf_chat: "夜晚-狼人交流",
  night_wolf: "夜晚-狼人行动",
  night_seer: "夜晚-预言家行动",
  night_witch: "夜晚-女巫行动",
  hunter_shot: "猎人开枪",
  day_discuss: "白天-讨论阶段",
  day_vote: "白天-投票阶段",
  day_result: "白天-公布结果",
  game_over: "游戏结束",
};

const roleLabelMap: Record<Exclude<Role, null>, string> = {
  villager: "村民",
  werewolf: "狼人",
  seer: "预言家",
  witch: "女巫",
  hunter: "猎人",
};

const roleClassMap: Record<Exclude<Role, null>, string> = {
  villager: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30",
  werewolf: "bg-red-500/15 text-red-300 ring-1 ring-red-500/30",
  seer: "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30",
  witch: "bg-fuchsia-500/15 text-fuchsia-300 ring-1 ring-fuchsia-500/30",
  hunter: "bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/30",
};

const phaseIconMap: Record<GamePhase, JSX.Element> = {
  waiting: <RefreshCw className="h-4 w-4" />,
  night_wolf_chat: <Moon className="h-4 w-4" />,
  night_wolf: <Moon className="h-4 w-4" />,
  night_seer: <Moon className="h-4 w-4" />,
  night_witch: <Moon className="h-4 w-4" />,
  hunter_shot: <Skull className="h-4 w-4" />,
  day_discuss: <Sun className="h-4 w-4" />,
  day_vote: <Vote className="h-4 w-4" />,
  day_result: <AlertCircle className="h-4 w-4" />,
  game_over: <Skull className="h-4 w-4" />,
};

const canRevealRole = (
  player: Player,
  currentPlayerId: string,
  phase: GamePhase,
): boolean => {
  if (phase === "game_over") {
    return player.role != null;
  }
  if (currentPlayerId === "spectator") {
    return true;
  }
  if (player.player_id === currentPlayerId) {
    return true;
  }
  return Boolean(player.role && player.identity_revealed);
};

export default function GameRoom({
  roomId,
  playerId,
  onLeave,
}: GameRoomProps) {
  const { gameState, loading, error, actions } = useGameState(roomId, playerId);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [speechContent, setSpeechContent] = useState<string>("");
  const [savingWithAntidote, setSavingWithAntidote] = useState<boolean>(false);
  const [seerResultText, setSeerResultText] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [wolfWhisperText, setWolfWhisperText] = useState<string>("");
  const [showResultModal, setShowResultModal] = useState<boolean>(false);

  useEffect(() => {
    if (gameState?.phase === "game_over") {
      setShowResultModal(true);
    }
  }, [gameState?.phase]);

  useEffect(() => {
    const logContainer = logContainerRef.current;
    if (!logContainer) {
      return;
    }

    logContainer.scrollTop = logContainer.scrollHeight;
  }, [gameState?.day_logs.length, gameState?.phase]);

  useEffect(() => {
    setSelectedTargetId(null);
    if (gameState?.phase !== "night_witch") {
      setSavingWithAntidote(false);
    }
  }, [gameState?.phase, gameState?.round_num]);

  const currentPlayer = useMemo(
    () => (gameState ? gameState.players[playerId] ?? null : null),
    [gameState, playerId],
  );

  const players = useMemo(
    () => (gameState ? Object.values(gameState.players) : []),
    [gameState],
  );

  const alivePlayers = useMemo(
    () => players.filter((player) => player.is_alive),
    [players],
  );

  const voteCountMap = useMemo(() => {
    if (!gameState) {
      return {} as Record<string, number>;
    }

    const counts: Record<string, number> = {};

    Object.values(gameState.votes).forEach((targetId) => {
      counts[targetId] = (counts[targetId] ?? 0) + 1;
    });

    return counts;
  }, [gameState]);

  const isOwner = playerId === "p1";
  const isAlive = Boolean(currentPlayer?.is_alive);
  const myRole = currentPlayer?.role ?? null;
  const phase = gameState?.phase ?? "waiting";

  const canWolfChatAct =
    phase === "night_wolf_chat" && myRole === "werewolf" && isAlive;
  const canWolfAct = phase === "night_wolf" && myRole === "werewolf" && isAlive;
  const canSeerAct = phase === "night_seer" && myRole === "seer" && isAlive;
  const canWitchAct = phase === "night_witch" && myRole === "witch" && isAlive;
  const canSpeakAct = phase === "day_discuss" && isAlive && gameState?.current_speaker === playerId;
  const canVoteAct = phase === "day_vote" && isAlive;
  const canHunterAct =
    phase === "hunter_shot" &&
    myRole === "hunter" &&
    !isAlive &&
    gameState?.pending_hunter_id === playerId;

  const isSelectableTarget = (player: Player): boolean => {
    if (!currentPlayer) {
      return false;
    }

    if (canHunterAct) {
      return player.is_alive && player.player_id !== currentPlayer.player_id;
    }

    if (!player.is_alive) {
      return false;
    }

    if (player.player_id === currentPlayer.player_id) {
      return false;
    }

    if (canWolfAct) {
      return player.role !== "werewolf";
    }

    if (canSeerAct || canVoteAct || canWitchAct) {
      return true;
    }

    return false;
  };

  const handlePlayerCardClick = (player: Player) => {
    if (!isSelectableTarget(player)) {
      return;
    }

    setSelectedTargetId((prev) =>
      prev === player.player_id ? null : player.player_id,
    );
  };

  const runAction = async (fn: () => Promise<unknown>) => {
    try {
      setActionLoading(true);
      await fn();
    } finally {
      setActionLoading(false);
    }
  };

  const handleWolfWhisper = async () => {
    const t = wolfWhisperText.trim();
    if (!t) {
      return;
    }
    await runAction(async () => {
      await actions.wolfWhisper(t);
      setWolfWhisperText("");
    });
  };

  const handleWolfKill = async () => {
    if (!selectedTargetId) {
      return;
    }

    await runAction(async () => {
      await actions.wolfKill(selectedTargetId);
      setSelectedTargetId(null);
    });
  };

  const handleSeerCheck = async () => {
    if (!selectedTargetId) {
      return;
    }

    await runAction(async () => {
      const result = await actions.seerCheck(selectedTargetId);
      if (result) {
        setSeerResultText(
          result.is_werewolf
            ? `${selectedTargetId} 是狼人`
            : `${selectedTargetId} 不是狼人`,
        );
      }
      setSelectedTargetId(null);
    });
  };

  const handleWitchAction = async () => {
    await runAction(async () => {
      await actions.witch(
        savingWithAntidote,
        savingWithAntidote ? null : selectedTargetId,
      );
      setSelectedTargetId(null);
      setSavingWithAntidote(false);
    });
  };

  const handleSpeak = async () => {
    const content = speechContent.trim();
    if (!content) {
      return;
    }

    await runAction(async () => {
      await actions.speak(content);
      setSpeechContent("");
    });
  };

  const handleVote = async () => {
    if (!selectedTargetId) {
      return;
    }

    await runAction(async () => {
      await actions.vote(selectedTargetId);
      setSelectedTargetId(null);
    });
  };

  const handleAbstain = async () => {
    await runAction(async () => {
      await actions.abstain();
      setSelectedTargetId(null);
    });
  };

  const handleHunterShoot = async (targetId: string | null) => {
    await runAction(async () => {
      await actions.hunterShoot(targetId);
      setSelectedTargetId(null);
    });
  };

  const handleNextPhase = async () => {
    await runAction(async () => {
      await actions.nextPhase();
    });
  };

  if (loading && !gameState) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        <div className="flex items-center gap-3 rounded-2xl border border-slate-800 bg-slate-900 px-6 py-4">
          <RefreshCw className="h-5 w-5 animate-spin text-cyan-400" />
          <span>正在加载游戏状态...</span>
        </div>
      </div>
    );
  }

  if (!gameState || (!currentPlayer && playerId !== "spectator")) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 text-slate-100">
        <div className="w-full max-w-lg rounded-2xl border border-red-500/20 bg-slate-900 p-6 text-center">
          <AlertCircle className="mx-auto mb-3 h-8 w-8 text-red-400" />
          <p className="text-lg font-semibold">无法加载玩家状态</p>
          <p className="mt-2 text-sm text-slate-400">
            请检查房间号、玩家 ID 或后端服务状态。
          </p>
        </div>
      </div>
    );
  }

  const isSpectator = playerId === "spectator";

  const winner = gameState.winner;
  const isWerewolfWin = winner === "werewolves_win";
  const isVillagerWin = winner === "villagers_win";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {showResultModal && winner && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className={`relative w-full max-w-sm mx-4 rounded-3xl border p-8 text-center shadow-2xl ${
            isWerewolfWin
              ? "border-red-500/40 bg-slate-900"
              : "border-amber-500/40 bg-slate-900"
          }`}>
            <div className="mb-4 text-6xl">
              {isWerewolfWin ? "🐺" : "🌟"}
            </div>
            <h2 className={`mb-2 text-2xl font-bold ${
              isWerewolfWin ? "text-red-300" : "text-amber-300"
            }`}>
              {isWerewolfWin ? "狼人获胜！" : "好人获胜！"}
            </h2>
            <p className="mb-6 text-sm text-slate-400">
              {isWerewolfWin
                ? "狼人成功隐藏身份，消灭了村庄的希望。"
                : "村民团结一心，将所有狼人放逐出局！"}
            </p>
            <div className="mb-6 space-y-1 text-sm">
              {Object.values(gameState.players).map((p) => (
                <div key={p.player_id} className="flex items-center justify-between rounded-xl bg-slate-800/60 px-4 py-2">
                  <span className="text-slate-200">{p.name}（{p.player_id}）</span>
                  {p.role && (
                    <span className={`rounded-lg px-2 py-0.5 text-xs font-medium ${roleClassMap[p.role]}`}>
                      {roleLabelMap[p.role]}
                    </span>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setShowResultModal(false)}
              className="w-full rounded-xl bg-slate-700 px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-slate-600"
            >
              关闭
            </button>
          </div>
        </div>
      )}
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-3">
              <div className="rounded-xl bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-300 ring-1 ring-cyan-500/20">
                Room: {gameState.game_id}
              </div>
              <div className="rounded-xl bg-slate-800 px-3 py-2 text-sm font-medium text-slate-200">
                Round {gameState.round_num}
              </div>
              <div className="inline-flex items-center gap-2 rounded-xl bg-violet-500/10 px-3 py-2 text-sm font-medium text-violet-300 ring-1 ring-violet-500/20">
                {phaseIconMap[gameState.phase]}
                <span>{phaseLabelMap[gameState.phase]}</span>
              </div>
              {gameState.phase === "day_discuss" && gameState.current_speaker ? (
                <div className="inline-flex items-center gap-2 rounded-xl bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300 ring-1 ring-amber-500/20">
                  <span>当前发言: {gameState.players[gameState.current_speaker]?.name}</span>
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {onLeave ? (
                <button
                  type="button"
                  onClick={onLeave}
                  className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-200 transition hover:bg-slate-700"
                >
                  <Skull className="h-4 w-4" />
                  离开房间
                </button>
              ) : null}
              {!isSpectator && currentPlayer ? (
                <>
                  <div className="rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-200">
                    你的身份：
                    <span className="ml-2 font-semibold text-white">
                      {currentPlayer.role
                        ? roleLabelMap[currentPlayer.role]
                        : "未知"}
                    </span>
                  </div>
                  <div
                    className={`rounded-xl px-3 py-2 text-sm font-medium ring-1 ${
                      currentPlayer.is_alive
                        ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/20"
                        : "bg-slate-800 text-slate-400 ring-slate-700"
                    }`}
                  >
                    {currentPlayer.is_alive ? "存活" : "已出局"}
                  </div>
                </>
              ) : (
                <div className="rounded-xl bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300 ring-1 ring-amber-500/20">
                  上帝视角 / 观战中
                </div>
              )}
              <button
                type="button"
                onClick={() => void actions.refresh()}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-3 py-2 text-sm text-slate-200 transition hover:bg-slate-700"
              >
                <RefreshCw className="h-4 w-4" />
                刷新
              </button>
            </div>
          </div>
        </header>

        {error ? (
          <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}

        {seerResultText ? (
          <div className="flex items-center gap-3 rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            <WandSparkles className="h-4 w-4 shrink-0" />
            <span>{seerResultText}</span>
          </div>
        ) : null}

        <main className="grid min-h-0 gap-6 xl:grid-cols-[1.4fr_1fr] xl:items-stretch">
          <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">玩家列表</h2>
                <p className="text-sm text-slate-400">
                  点击玩家卡片可选中目标进行操作。
                </p>
              </div>
              <div className="text-sm text-slate-400">
                存活 {alivePlayers.length} / 总计 {players.length}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {players.map((player) => {
                const isSelf = player.player_id === playerId;
                const isSelected = selectedTargetId === player.player_id;
                const selectable = isSelectableTarget(player);
                const voteCount = voteCountMap[player.player_id] ?? 0;
                const showRole = canRevealRole(player, playerId, phase);

                return (
                  <button
                    key={player.player_id}
                    type="button"
                    onClick={() => handlePlayerCardClick(player)}
                    disabled={!selectable}
                    className={`relative rounded-2xl border p-4 text-left transition ${
                      player.is_alive
                        ? "border-slate-700 bg-slate-800/70"
                        : "border-slate-800 bg-slate-900/50 opacity-70 grayscale"
                    } ${
                      isSelf ? "ring-2 ring-cyan-500/50" : ""
                    } ${
                      isSelected ? "border-violet-400 ring-2 ring-violet-500/40" : ""
                    } ${
                      selectable
                        ? "cursor-pointer hover:border-slate-500 hover:bg-slate-800"
                        : "cursor-default"
                    }`}
                  >
                    {isSelf ? (
                      <div className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-cyan-500/15 px-2 py-1 text-xs font-medium text-cyan-300">
                        <Crown className="h-3.5 w-3.5" />
                        你
                      </div>
                    ) : null}

                    {phase === "day_vote" && voteCount > 0 ? (
                      <div className="absolute left-3 top-3 inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-1 text-xs font-medium text-red-300">
                        <Vote className="h-3.5 w-3.5" />
                        {voteCount} 票
                      </div>
                    ) : null}

                    <div className="mb-4 flex items-center gap-3 pt-6">
                      <div
                        className={`rounded-xl p-3 ${
                          player.is_alive
                            ? "bg-slate-700 text-slate-100"
                            : "bg-slate-800 text-slate-500"
                        }`}
                      >
                        {player.is_alive ? (
                          <User className="h-6 w-6" />
                        ) : (
                          <Skull className="h-6 w-6" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-white">
                          {player.name}
                        </p>
                        <p className="text-sm text-slate-400">
                          ID: {player.player_id}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                          player.is_alive
                            ? "bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/20"
                            : "bg-slate-700 text-slate-400 ring-1 ring-slate-600"
                        }`}
                      >
                        {player.is_alive ? "存活" : "已出局"}
                      </span>

                      {showRole && player.role ? (
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                            roleClassMap[player.role]
                          }`}
                        >
                          {roleLabelMap[player.role]}
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="flex max-h-[min(70vh,calc(100vh-10rem))] min-h-[420px] flex-col rounded-2xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
            <div className="mb-4 flex shrink-0 items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">日志记录</h2>
                <p className="text-sm text-slate-400">
                  白天发言会实时显示在这里。
                </p>
              </div>
              <Mic className="h-5 w-5 text-slate-400" />
            </div>

            <div
              ref={logContainerRef}
              className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain rounded-2xl bg-slate-950/60 p-3"
            >
              {[...(gameState.system_logs || []), ...gameState.day_logs].length === 0 ? (
                <div className="flex h-full min-h-[280px] items-center justify-center text-sm text-slate-500">
                  暂无日志，等待玩家发言...
                </div>
              ) : (
                [...(gameState.system_logs || []), ...gameState.day_logs].map((log, index) => {
                  const speaker = gameState.players[log.player_id];
                  const isSystem = 'log_type' in log;
                  return (
                    <div
                      key={`${log.player_id}-${index}`}
                      className={`rounded-xl border p-3 ${
                        isSystem
                          ? "border-amber-800 bg-amber-900/40"
                          : "border-slate-800 bg-slate-900/80"
                      }`}
                    >
                      <div className={`mb-1 text-sm font-medium ${isSystem ? "text-amber-300" : "text-cyan-300"}`}>
                        {speaker?.name ?? log.player_id} ({log.player_id}) {isSystem ? "[系统思考]" : ""}
                      </div>
                      <p className={`text-sm leading-6 ${isSystem ? "text-amber-100/80 italic" : "text-slate-200"}`}>
                        {log.message}
                      </p>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        </main>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4 shadow-lg shadow-black/20">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">操作面板</h2>
              <p className="text-sm text-slate-400">
                当前阶段可执行的操作会在这里显示。
              </p>
            </div>

            {isOwner ? (
              <button
                type="button"
                onClick={() => void handleNextPhase()}
                disabled={actionLoading || phase === "game_over"}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshCw className="h-4 w-4" />
                进入下一阶段
              </button>
            ) : null}
          </div>

          {!isAlive && !isSpectator ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-5 text-sm text-slate-400">
              你已出局，当前只能旁观游戏进程。
            </div>
          ) : null}

          {isSpectator ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-5 text-sm text-slate-400">
              ⚔️ 观战模式：您当前处于全透明“上帝视角”，正在观看 AI 之间的大乱斗！
            </div>
          ) : null}

          {(isSpectator || myRole === "werewolf") &&
          (gameState.wolf_whispers?.length ?? 0) > 0 ? (
            <div className="space-y-3 rounded-2xl border border-red-900/40 bg-red-950/30 px-4 py-3 text-sm">
              <div className="font-medium text-red-200/90">狼人队内频道</div>
              {(() => {
                const groups: Record<number, typeof gameState.wolf_whispers> = {};
                for (const w of gameState.wolf_whispers ?? []) {
                  const r = w.round_num ?? 1;
                  if (!groups[r]) groups[r] = [];
                  groups[r].push(w);
                }
                return Object.entries(groups).map(([round, whispers]) => (
                  <div key={round} className="space-y-1">
                    <div className="text-xs text-red-400/60">第 {round} 夜</div>
                    <ul className="space-y-1 text-red-100/85">
                      {whispers.map((w, i) => (
                        <li key={`${w.player_id}-${round}-${i}`}>
                          <span className="text-red-300/90">{w.player_name}</span>：{w.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                ));
              })()}
            </div>
          ) : null}

          {isAlive && canWolfChatAct ? (
            <div className="space-y-3">
              <div className="text-sm text-slate-300">
                与狼队友协商今晚刀谁（每名存活狼人需各发一条，全员发完后进入击杀阶段）。
              </div>
              <textarea
                value={wolfWhisperText}
                onChange={(event) => setWolfWhisperText(event.target.value)}
                placeholder="队内私语，其他玩家看不到…"
                className="min-h-[88px] w-full rounded-2xl border border-red-900/50 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-red-500/60"
              />
              <button
                type="button"
                onClick={() => void handleWolfWhisper()}
                disabled={!wolfWhisperText.trim() || actionLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <MessageSquare className="h-4 w-4" />
                发送队内私语
              </button>
            </div>
          ) : null}

          {isAlive && canWolfAct ? (
            <div className="space-y-3">
              <div className="text-sm text-slate-300">
                请选择一名目标玩家进行击杀。
              </div>
              <button
                type="button"
                onClick={() => void handleWolfKill()}
                disabled={!selectedTargetId || actionLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Target className="h-4 w-4" />
                击杀目标
              </button>
            </div>
          ) : null}

          {isAlive && canSeerAct ? (
            <div className="space-y-3">
              <div className="text-sm text-slate-300">
                请选择一名玩家进行查验。
              </div>
              <button
                type="button"
                onClick={() => void handleSeerCheck()}
                disabled={!selectedTargetId || actionLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <WandSparkles className="h-4 w-4" />
                查验目标
              </button>
            </div>
          ) : null}

          {isAlive && canWitchAct ? (
            <div className="space-y-4">
              <label className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={savingWithAntidote}
                  onChange={(event) => setSavingWithAntidote(event.target.checked)}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-fuchsia-500 focus:ring-fuchsia-500"
                />
                使用解药救人
              </label>

              <p className="text-sm text-slate-400">
                {!savingWithAntidote
                  ? "如需使用毒药，请点击玩家卡片选择目标。"
                  : "已选择使用解药，本轮不会使用毒药。"}
              </p>

              <button
                type="button"
                onClick={() => void handleWitchAction()}
                disabled={actionLoading || (!savingWithAntidote && !selectedTargetId)}
                className="inline-flex items-center gap-2 rounded-xl bg-fuchsia-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-fuchsia-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <WandSparkles className="h-4 w-4" />
                确认女巫操作
              </button>
            </div>
          ) : null}

          {canHunterAct ? (
            <div className="space-y-3">
              <div className="text-sm text-orange-200/90">
                你是猎人，已出局。可以开枪带走一名存活玩家，也可以放弃。
              </div>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <button
                  type="button"
                  onClick={() => void handleHunterShoot(selectedTargetId)}
                  disabled={!selectedTargetId || actionLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-orange-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Target className="h-4 w-4" />
                  开枪击杀
                </button>
                <button
                  type="button"
                  onClick={() => void handleHunterShoot(null)}
                  disabled={actionLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Skull className="h-4 w-4" />
                  放弃开枪
                </button>
              </div>
            </div>
          ) : null}

          {isAlive && canSpeakAct ? (
            <div className="space-y-3">
              <textarea
                value={speechContent}
                onChange={(event) => setSpeechContent(event.target.value)}
                placeholder="请输入你的发言..."
                className="min-h-[110px] w-full rounded-2xl border border-slate-700 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-500"
              />
              <button
                type="button"
                onClick={() => void handleSpeak()}
                disabled={!speechContent.trim() || actionLoading}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Mic className="h-4 w-4" />
                发送发言
              </button>
            </div>
          ) : null}

          {isAlive && canVoteAct ? (
            <div className="space-y-3">
              <p className="text-sm text-slate-400">
                可投票放逐一名玩家，也可弃票。若平票、无人得票或全员弃票，本日无人出局。
              </p>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <button
                  type="button"
                  onClick={() => void handleVote()}
                  disabled={!selectedTargetId || actionLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Vote className="h-4 w-4" />
                  投票放逐
                </button>

                <button
                  type="button"
                  onClick={() => void handleAbstain()}
                  disabled={actionLoading}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Skull className="h-4 w-4" />
                  弃票
                </button>
              </div>
            </div>
          ) : null}

          {phase === "game_over" ? (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-5 text-sm text-amber-200">
              游戏已结束，等待进入下一局。
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

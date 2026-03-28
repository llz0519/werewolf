import { useState } from "react";
import { Loader2, Swords, User } from "lucide-react";
import { startLocalGame } from "../services/api";

interface LobbyProps {
  onJoin: (roomId: string, playerId: string) => void;
}

export default function Lobby({ onJoin }: LobbyProps) {
  const [loadingAction, setLoadingAction] = useState<"spectator" | "play" | null>(null);
  const [error, setError] = useState<string>("");
  const [humanName, setHumanName] = useState<string>("我");

  const getErrorMessage = (err: unknown): string => {
    if (typeof err === "object" && err !== null && "response" in err) {
      const response = err as { response?: { data?: { detail?: string } } };
      return response.response?.data?.detail ?? "请求失败，请稍后重试。";
    }
    if (err instanceof Error) return err.message;
    return "发生未知错误。";
  };

  const handleStart = async (mode: "spectator" | "play") => {
    try {
      setLoadingAction(mode);
      setError("");
      const res = await startLocalGame(mode, humanName.trim() || "玩家");
      onJoin(res.room_id, res.player_id);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoadingAction(null);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8 text-slate-100">
      <div className="w-full max-w-xl rounded-3xl border border-slate-800 bg-slate-900/90 p-6 shadow-2xl shadow-black/30 sm:p-8">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 inline-flex rounded-2xl bg-cyan-500/10 p-4 text-cyan-300 ring-1 ring-cyan-500/20">
            <Swords className="h-8 w-8" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
            狼人杀 Agent
          </h1>
          <p className="mt-3 text-sm text-slate-400 sm:text-base">
            选择你是想作为上帝单纯观战 AI 的勾心斗角，还是亲自下场与 AI 博弈。
          </p>
        </div>

        <div className="space-y-6">
          {error && (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <button
              onClick={() => handleStart("spectator")}
              disabled={loadingAction !== null}
              className="group relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border-2 border-slate-700 bg-slate-800 p-6 hover:border-cyan-500 hover:bg-slate-800/80 active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100"
            >
              {loadingAction === "spectator" ? (
                <Loader2 className="mb-3 h-8 w-8 animate-spin text-cyan-400" />
              ) : (
                <Swords className="mb-3 h-8 w-8 text-slate-400 group-hover:text-cyan-400" />
              )}
              <div className="font-semibold text-white">看戏模式</div>
              <div className="mt-1 text-xs text-slate-400">8个 AI 大乱斗，上帝视全透明</div>
            </button>

            <button
              onClick={() => handleStart("play")}
              disabled={loadingAction !== null}
              className="group relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border-2 border-slate-700 bg-slate-800 p-6 hover:border-fuchsia-500 hover:bg-slate-800/80 active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100"
            >
              {loadingAction === "play" ? (
                <Loader2 className="mb-3 h-8 w-8 animate-spin text-fuchsia-400" />
              ) : (
                <User className="mb-3 h-8 w-8 text-slate-400 group-hover:text-fuchsia-400" />
              )}
              <div className="font-semibold text-white">亲自下场</div>
              <div className="mt-1 text-xs text-slate-400">你 + 7个 AI 斗智斗勇</div>
            </button>
          </div>
          
          <div className="space-y-2 border-t border-slate-800 pt-6">
            <label className="text-sm font-medium text-slate-400">
              如果你选择亲自下场，你的名号是：
            </label>
            <input
              value={humanName}
              onChange={(e) => setHumanName(e.target.value)}
              placeholder="我"
              className="w-full rounded-2xl border border-slate-700 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-fuchsia-500"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  actionAbstain,
  actionHunterShoot,
  actionNextPhase,
  actionSeerCheck,
  actionSpeak,
  actionVote,
  actionWitch,
  actionWolfKill,
  actionWolfWhisper,
  getGameState,
} from "../services/api";
import type { ActionResponse, GameState } from "../types/game";

type HookError = string | null;

type ActionResult = ActionResponse | void;

interface UseGameStateActions {
  refresh: () => Promise<void>;
  wolfWhisper: (message: string) => Promise<ActionResult>;
  wolfKill: (targetId: string) => Promise<ActionResult>;
  seerCheck: (targetId: string) => Promise<{ is_werewolf: boolean } | void>;
  witch: (
    save: boolean,
    poisonTargetId: string | null,
  ) => Promise<ActionResult>;
  speak: (content: string) => Promise<ActionResult>;
  vote: (targetId: string) => Promise<ActionResult>;
  abstain: () => Promise<ActionResult>;
  hunterShoot: (targetId: string | null) => Promise<ActionResult>;
  nextPhase: () => Promise<ActionResult>;
}

interface UseGameStateResult {
  gameState: GameState | null;
  loading: boolean;
  error: HookError;
  actions: UseGameStateActions;
}

const getErrorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }

  return "未知错误";
};

export function useGameState(
  roomId: string,
  playerId: string,
): UseGameStateResult {
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<HookError>(null);
  const mountedRef = useRef<boolean>(true);

  const refresh = useCallback(async () => {
    if (!roomId || !playerId) {
      if (mountedRef.current) {
        setLoading(false);
        setError("缺少 roomId 或 playerId");
      }
      return;
    }

    try {
      if (mountedRef.current) {
        setLoading(true);
        setError(null);
      }

      const nextState = await getGameState(roomId, playerId);

      if (mountedRef.current) {
        setGameState(nextState);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(getErrorMessage(err));
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [playerId, roomId]);

  const runAction = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | void> => {
      try {
        setError(null);
        const result = await fn();
        await refresh();
        return result;
      } catch (err) {
        setError(getErrorMessage(err));
      }
    },
    [refresh],
  );

  useEffect(() => {
    mountedRef.current = true;
    void refresh();

    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);

    return () => {
      mountedRef.current = false;
      window.clearInterval(timer);
    };
  }, [refresh]);

  const actions = useMemo<UseGameStateActions>(
    () => ({
      refresh,
      wolfWhisper: async (message: string) =>
        runAction(() => actionWolfWhisper(roomId, playerId, message)),
      wolfKill: async (targetId: string) =>
        runAction(() => actionWolfKill(roomId, playerId, targetId)),
      seerCheck: async (targetId: string) =>
        runAction(() => actionSeerCheck(roomId, playerId, targetId)),
      witch: async (save: boolean, poisonTargetId: string | null) =>
        runAction(() => actionWitch(roomId, playerId, save, poisonTargetId)),
      speak: async (content: string) =>
        runAction(() => actionSpeak(roomId, playerId, content)),
      vote: async (targetId: string) =>
        runAction(() => actionVote(roomId, playerId, targetId)),
      abstain: async () => runAction(() => actionAbstain(roomId, playerId)),
      hunterShoot: async (targetId: string | null) =>
        runAction(() => actionHunterShoot(roomId, playerId, targetId)),
      nextPhase: async () => runAction(() => actionNextPhase(roomId, playerId)),
    }),
    [playerId, refresh, roomId, runAction],
  );

  return {
    gameState,
    loading,
    error,
    actions,
  };
}

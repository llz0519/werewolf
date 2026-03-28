import axios, { type AxiosInstance } from "axios";

import type {
  ActionResponse,
  CreateGameResponse,
  DayLog,
  GamePhase,
  GameState,
  JoinGameResponse,
  Player,
  Role,
  SeerCheckResponse,
  StartGameResponse,
  Winner,
  SystemLog,
  WolfWhisper,
} from "../types/game";

export async function startLocalGame(mode: "spectator" | "play", humanName: string = "玩家") {
  const response = await apiClient.post(`/game/start-local`, {
    mode,
    human_name: humanName
  });
  return response.data as { room_id: string; player_id: string; phase: string };
}

type RawVotes = Record<string, string[]>;

interface RawPlayer {
  player_id: string;
  name: string;
  role: Role;
  is_alive: boolean;
  is_ai: boolean;
  identity_revealed?: boolean;
}

interface RawDayLog {
  player_id: string;
  player_name?: string;
  message?: string;
  content?: string;
}

interface RawGameState {
  game_id: string;
  phase: GamePhase;
  round_num: number;
  players: Record<string, RawPlayer>;
  day_logs: RawDayLog[];
  system_logs?: any[];
  wolf_whispers?: WolfWhisper[];
  dead_this_night: string[];
  votes: RawVotes;
  vote_abstains?: string[];
  winner?: Winner;
  current_speaker?: string | null;
  pending_hunter_id?: string | null;
}

interface JoinGamePayload {
  name: string;
  is_ai: boolean;
}

interface WolfKillPayload {
  target_id: string;
}

interface WolfWhisperPayload {
  message: string;
}

interface SeerCheckPayload {
  target_id: string;
}

interface WitchPayload {
  save: boolean;
  poison_target_id: string | null;
}

interface SpeakPayload {
  content: string;
}

interface VotePayload {
  target_id: string;
}

interface HunterShotPayload {
  target_id: string | null;
}

export const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
});

const playerHeaders = (playerId: string) => ({
  headers: {
    "player-id": playerId,
  },
});

const normalizePlayer = (player: RawPlayer): Player => ({
  player_id: player.player_id,
  name: player.name,
  role: player.role,
  is_alive: player.is_alive,
  is_ai: player.is_ai,
  identity_revealed: player.identity_revealed ?? false,
});

const normalizeDayLog = (log: RawDayLog): DayLog => ({
  player_id: log.player_id,
  player_name: log.player_name || log.player_id,
  message: log.content ?? log.message ?? "",
});

const normalizeSystemLog = (log: any): SystemLog => ({
  player_id: log.player_id,
  player_name: log.player_name || log.player_id,
  message: log.message ?? "",
  log_type: log.log_type ?? "info",
});

/**
 * 将后端的「被投票目标 -> 投票人列表」结构，
 * 转换成前端更易使用的「投票人 -> 投票目标」结构。
 */
const normalizeVotes = (votes: RawVotes): Record<string, string> => {
  const normalized: Record<string, string> = {};

  Object.entries(votes).forEach(([targetId, voterIds]) => {
    voterIds.forEach((voterId) => {
      normalized[voterId] = targetId;
    });
  });

  return normalized;
};

const normalizeGameState = (raw: RawGameState): GameState => ({
  game_id: raw.game_id,
  phase: raw.phase,
  round_num: raw.round_num,
  players: Object.fromEntries(
    Object.entries(raw.players).map(([playerId, player]) => [
      playerId,
      normalizePlayer(player),
    ]),
  ),
  day_logs: raw.day_logs.map(normalizeDayLog),
  system_logs: raw.system_logs ? raw.system_logs.map(normalizeSystemLog) : [],
  wolf_whispers: raw.wolf_whispers ?? [],
  dead_this_night: raw.dead_this_night,
  votes: normalizeVotes(raw.votes),
  vote_abstains: raw.vote_abstains ?? [],
  winner: raw.winner ?? null,
  current_speaker: raw.current_speaker ?? null,
  pending_hunter_id: raw.pending_hunter_id ?? null,
});

/**
 * 创建房间。
 *
 * 注意：当前后端要求创建者也传 `player-id`，
 * 因此前端这里提供一个可选的房主 ID，默认使用 `p1`。
 */
export async function createGame(
  playerId = "p1",
): Promise<CreateGameResponse> {
  const { data } = await apiClient.post<CreateGameResponse>(
    "/game/create",
    undefined,
    playerHeaders(playerId),
  );

  return {
    room_id: data.room_id,
  };
}

/**
 * 加入房间。
 */
export async function joinGame(
  roomId: string,
  playerId: string,
  name: string,
  isAi = false,
): Promise<JoinGameResponse> {
  const payload: JoinGamePayload = {
    name,
    is_ai: isAi,
  };

  const { data } = await apiClient.post<JoinGameResponse>(
    `/game/${roomId}/join`,
    payload,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 开始游戏。
 */
export async function startGame(
  roomId: string,
  playerId: string,
): Promise<StartGameResponse> {
  const { data } = await apiClient.post<StartGameResponse>(
    `/game/${roomId}/start`,
    undefined,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 获取当前房间状态，并将后端返回结构适配为前端使用的 `GameState`。
 */
export async function getGameState(
  roomId: string,
  playerId: string,
): Promise<GameState> {
  const { data } = await apiClient.get<RawGameState>(
    `/game/${roomId}/state`,
    playerHeaders(playerId),
  );

  return normalizeGameState(data);
}

/**
 * 狼人夜晚击杀目标。
 */
export async function actionWolfKill(
  roomId: string,
  playerId: string,
  targetId: string,
): Promise<ActionResponse> {
  const payload: WolfKillPayload = {
    target_id: targetId,
  };

  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/wolf_kill`,
    payload,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 狼人夜间队内私语（仅狼人阶段 night_wolf_chat）。
 */
export async function actionWolfWhisper(
  roomId: string,
  playerId: string,
  message: string,
): Promise<ActionResponse> {
  const payload: WolfWhisperPayload = { message };
  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/wolf_whisper`,
    payload,
    playerHeaders(playerId),
  );
  return data;
}

/**
 * 预言家查验目标身份。
 */
export async function actionSeerCheck(
  roomId: string,
  playerId: string,
  targetId: string,
): Promise<Pick<SeerCheckResponse, "is_werewolf">> {
  const payload: SeerCheckPayload = {
    target_id: targetId,
  };

  const { data } = await apiClient.post<SeerCheckResponse>(
    `/game/${roomId}/action/seer_check`,
    payload,
    playerHeaders(playerId),
  );

  return {
    is_werewolf: data.is_werewolf,
  };
}

/**
 * 女巫执行救人或下毒操作。
 */
export async function actionWitch(
  roomId: string,
  playerId: string,
  save: boolean,
  poisonTargetId: string | null,
): Promise<ActionResponse> {
  const payload: WitchPayload = {
    save,
    poison_target_id: poisonTargetId,
  };

  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/witch`,
    payload,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 白天发言。
 */
export async function actionSpeak(
  roomId: string,
  playerId: string,
  content: string,
): Promise<ActionResponse> {
  const payload: SpeakPayload = {
    content,
  };

  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/speak`,
    payload,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 白天投票。
 */
export async function actionVote(
  roomId: string,
  playerId: string,
  targetId: string,
): Promise<ActionResponse> {
  const payload: VotePayload = {
    target_id: targetId,
  };

  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/vote`,
    payload,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 白天弃票。
 */
export async function actionAbstain(
  roomId: string,
  playerId: string,
): Promise<ActionResponse> {
  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/abstain`,
    undefined,
    playerHeaders(playerId),
  );

  return data;
}

/**
 * 猎人开枪（target_id 为 null 表示放弃）。
 */
export async function actionHunterShoot(
  roomId: string,
  playerId: string,
  targetId: string | null,
): Promise<ActionResponse> {
  const payload: HunterShotPayload = { target_id: targetId };
  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/hunter_shoot`,
    payload,
    playerHeaders(playerId),
  );
  return data;
}

/**
 * 手动推进到下一阶段。
 */
export async function actionNextPhase(
  roomId: string,
  playerId: string,
): Promise<ActionResponse> {
  const { data } = await apiClient.post<ActionResponse>(
    `/game/${roomId}/action/next_phase`,
    undefined,
    playerHeaders(playerId),
  );

  return data;
}

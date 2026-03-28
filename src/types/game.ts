export type Role = "villager" | "werewolf" | "seer" | "witch" | "hunter" | null;

export type Winner = "villagers_win" | "werewolves_win" | null;

export type GamePhase =
  | "waiting"
  | "night_wolf_chat"
  | "night_wolf"
  | "night_seer"
  | "night_witch"
  | "hunter_shot"
  | "day_discuss"
  | "day_vote"
  | "day_result"
  | "game_over";

export interface Player {
  player_id: string;
  name: string;
  role: Role;
  is_alive: boolean;
  is_ai: boolean;
  identity_revealed: boolean;
}

export interface DayLog {
  player_id: string;
  player_name: string;
  message: string;
}

export interface SystemLog {
  player_id: string;
  player_name: string;
  message: string;
  log_type: string;
}

export interface WolfWhisper {
  player_id: string;
  player_name: string;
  message: string;
  round_num: number;
}

export interface GameState {
  game_id: string;
  phase: GamePhase;
  round_num: number;
  players: Record<string, Player>;
  day_logs: DayLog[];
  system_logs: SystemLog[];
  wolf_whispers: WolfWhisper[];
  dead_this_night: string[];
  votes: Record<string, string>;
  vote_abstains: string[];
  winner?: Winner;
  current_speaker?: string | null;
  pending_hunter_id?: string | null;
}

export interface CreateGameResponse {
  room_id: string;
}

export interface JoinGameResponse {
  message: string;
  player_count: number;
}

export interface StartGameResponse {
  message: string;
  phase: GamePhase;
}

export interface ActionResponse {
  message: string;
  phase?: GamePhase;
}

export interface SeerCheckResponse {
  target_id: string;
  is_werewolf: boolean;
  phase: GamePhase;
}

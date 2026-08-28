export type Message = {
  id: string;
  sender: "user" | "character";
  type: "text" | "image";
  content: string;
  asset_url: string | null;
  created_at: string;
};

export type Role = {
  role_id: string;
  display_name: string;
  description: string;
  avatar: string | null;
};

export type Conversation = {
  id: string;
  role_id: string;
  story_id: string | null;
  state: Record<string, unknown>;
};

export type TurnLog = {
  id: string;
  planner_output: Record<string, unknown>;
  applied: Record<string, unknown>;
  validation_errors: string[];
  created_at: string;
};

export type DebugSnapshot = {
  conversation_id: string;
  role: Role;
  state: {
    emotion: string | null;
    emotion_intensity: number;
    relationship: Record<string, number>;
    current_topic: string | null;
  };
  story: {
    story_id: string;
    current_node_id: string | null;
    status: string;
    visited: string[];
  } | null;
  last_turn: TurnLog | null;
  turn_logs: TurnLog[];
};

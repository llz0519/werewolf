import { useState } from "react";

import GameRoom from "./pages/GameRoom";
import Lobby from "./pages/Lobby";

export default function App() {
  const [currentRoomId, setCurrentRoomId] = useState<string>("");
  const [currentPlayerId, setCurrentPlayerId] = useState<string>("");

  if (!currentRoomId) {
    return (
      <Lobby
        onJoin={(roomId, playerId) => {
          setCurrentRoomId(roomId);
          setCurrentPlayerId(playerId);
        }}
      />
    );
  }

  return (
    <GameRoom
      roomId={currentRoomId}
      playerId={currentPlayerId}
      onLeave={() => {
        setCurrentRoomId("");
        setCurrentPlayerId("");
      }}
    />
  );
}

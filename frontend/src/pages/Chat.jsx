import { useState } from "react";

import { useWebSocket } from "../hooks/useWebSocket.js";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState("");

  const { send } = useWebSocket("/ws/chat/", {
    token: localStorage.getItem("access_token"),
    onMessage: (msg) => {
      if (msg.type === "token") {
        setStreaming((prev) => prev + msg.text);
      } else if (msg.type === "done") {
        setMessages((prev) => [...prev, { role: "assistant", content: streaming }]);
        setStreaming("");
      }
    },
  });

  const sendMessage = () => {
    setMessages((prev) => [...prev, { role: "user", content: draft }]);
    send({ session_id: "REPLACE_WITH_SESSION_ID", message: draft });
    setDraft("");
  };

  return (
    <div className="p-6 flex flex-col h-screen">
      <h1 className="text-2xl font-semibold mb-4">Ask DocGuard</h1>
      <div className="flex-1 overflow-y-auto space-y-2 bg-white rounded-lg shadow p-4">
        {messages.map((m, i) => (
          <p key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            {m.content}
          </p>
        ))}
        {streaming && <p className="text-left text-gray-500">{streaming}</p>}
      </div>
      <div className="mt-4 flex gap-2">
        <input
          className="flex-1 border rounded px-3 py-2"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="What is our current authentication flow?"
        />
        <button className="bg-blue-600 text-white px-4 py-2 rounded" onClick={sendMessage}>
          Send
        </button>
      </div>
    </div>
  );
}

import { Route, Routes } from "react-router-dom";

import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Issues from "./pages/Issues.jsx";
import Settings from "./pages/Settings.jsx";
import Sources from "./pages/Sources.jsx";

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/issues" element={<Issues />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/sources" element={<Sources />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  );
}

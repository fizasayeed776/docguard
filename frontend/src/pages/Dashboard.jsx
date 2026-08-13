import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useWebSocket } from "../hooks/useWebSocket.js";
import { api } from "../lib/api.js";

const WORKSPACE_ID = "a2895d41-b147-43d9-aa10-c439e1628be3";

function activityText(event) {
  if (event.message) return event.message;

  if (event.event === "artifact_embedded") {
    return `Embedded ${event.chunk_count ?? 0} chunk${event.chunk_count === 1 ? "" : "s"}`;
  }

  return event.event ? event.event.replaceAll("_", " ") : "Dashboard activity received";
}

export default function Dashboard() {
  const [activity, setActivity] = useState([]);
  const { data: artifacts, isLoading: loadingArtifactStatus } = useQuery({
    queryKey: ["artifacts", "agent-status"],
    queryFn: async () => (await api.get("/sources/artifacts/")).data,
  });

  useWebSocket(`/ws/workspaces/${WORKSPACE_ID}/dashboard/`, {
    token: localStorage.getItem("access_token"),
    onMessage: (event) =>
      setActivity((previous) => [
        { ...event, receivedAt: new Date().toISOString() },
        ...previous,
      ].slice(0, 50)),
  });

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Dashboard</h1>
      {/* Consistency score gauge + trend chart go here */}
      <div className="grid grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="font-medium mb-2">Consistency Score</h2>
          <p className="text-gray-400 text-sm">Gauge component placeholder</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="font-medium mb-2">Latest Scan Status</h2>
          <ul className="text-sm space-y-2 max-h-64 overflow-y-auto">
            {loadingArtifactStatus ? (
              <li className="text-gray-400">Loading saved scan status…</li>
            ) : artifacts?.results?.length === 0 ? (
              <li className="text-gray-400">No scanned artifacts yet.</li>
            ) : (
              artifacts?.results?.map((artifact) => (
                <li key={artifact.id} className="border-b last:border-0 pb-2">
                  <p className="font-medium text-gray-700">{artifact.path}</p>
                  <p className={artifact.agent_status === "failed" ? "text-red-600" : "text-gray-500"}>
                    {artifact.agent_status?.replaceAll("_", " ") || "pending"}
                    {artifact.claim_extraction_method && ` · ${artifact.claim_extraction_method}`}
                  </p>
                  {artifact.agent_status_message && (
                    <p className="text-gray-500">{artifact.agent_status_message}</p>
                  )}
                </li>
              ))
            )}
          </ul>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h2 className="font-medium mb-2">Live Activity</h2>
          <ul className="text-sm space-y-1 max-h-64 overflow-y-auto">
            {activity.length === 0 ? (
              <li className="text-gray-400">Waiting for scan activity…</li>
            ) : (
              activity.map((event) => (
                <li key={`${event.receivedAt}-${event.artifact_id || event.event}`} className="text-gray-600">
                  <time className="mr-2 text-gray-400" dateTime={event.receivedAt}>
                    {new Date(event.receivedAt).toLocaleTimeString()}
                  </time>
                  {activityText(event)}
                </li>
              ))
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}

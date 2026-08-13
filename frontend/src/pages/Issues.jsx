import { useQuery } from "@tanstack/react-query";

import { api } from "../lib/api.js";

export default function Issues() {
  const { data: issues } = useQuery({
    queryKey: ["inconsistencies"],
    queryFn: async () => (await api.get("/knowledge/inconsistencies/")).data,
  });

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Issues</h1>
      <table className="w-full bg-white rounded-lg shadow text-sm">
        <thead>
          <tr className="text-left border-b">
            <th className="p-3">Severity</th>
            <th className="p-3">Status</th>
            <th className="p-3">Reasoning</th>
          </tr>
        </thead>
        <tbody>
          {issues?.results?.map((issue) => (
            <tr key={issue.id} className="border-b last:border-0">
              <td className="p-3">{issue.severity}</td>
              <td className="p-3">{issue.status}</td>
              <td className="p-3 text-gray-600">{issue.agent_reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* Detail drawer with side-by-side diff viewer goes here */}
    </div>
  );
}

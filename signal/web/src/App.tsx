import { useState, type ReactNode } from "react";
import ProjectsView from "./ProjectsView";
import SolicitationsView from "./SolicitationsView";

type Tab = "projects" | "solicitations";

export default function App() {
  const [tab, setTab] = useState<Tab>("projects");

  return (
    <div className="min-h-screen bg-white text-slate-800">
      <header className="border-b px-6 pt-4">
        <h1 className="text-xl font-bold">
          sauce.ai<span className="text-amber-600">/signal</span>
        </h1>
        <p className="text-sm text-slate-500">
          Permit intelligence &amp; distressed-project triage
        </p>
        <nav className="mt-3 flex gap-1 text-sm">
          <TabButton active={tab === "projects"} onClick={() => setTab("projects")}>
            Projects (permits)
          </TabButton>
          <TabButton active={tab === "solicitations"} onClick={() => setTab("solicitations")}>
            Solicitations (bids &amp; plans)
          </TabButton>
        </nav>
      </header>

      {tab === "projects" ? <ProjectsView /> : <SolicitationsView />}
    </div>
  );
}

function TabButton({
  active, onClick, children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-t border-b-2 -mb-px ${
        active
          ? "border-amber-600 text-amber-700 font-medium"
          : "border-transparent text-slate-500 hover:text-slate-700"
      }`}
    >
      {children}
    </button>
  );
}

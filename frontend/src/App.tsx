import { useEffect, useState } from "react";
import { fixture } from "./data";
import { IntakeScreen } from "./screens/IntakeScreen";
import { StrategyScreen } from "./screens/StrategyScreen";
import { DraftScreen } from "./screens/DraftScreen";

type Route = "intake" | "strategy" | "draft";

const ROUTES: { key: Route; label: string }[] = [
  { key: "intake", label: "① Intake 자료수집 챗" },
  { key: "strategy", label: "② 선택지 비교표" },
  { key: "draft", label: "③ DOCX 검토패키지 미리보기" },
];

function currentRoute(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "strategy" || h === "draft") return h;
  return "intake";
}

export function App() {
  const [route, setRoute] = useState<Route>(currentRoute());

  useEffect(() => {
    const onHash = () => setRoute(currentRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">TIW · Tax Intelligence Workspace</div>
        <div className="matter">
          {fixture.draft.company_name} · {fixture.draft.fiscal_year} 법인세 검토
          {fixture.draft.high_risk ? <span className="badge-risk"> 고위험</span> : null}
        </div>
      </header>
      <nav className="nav" aria-label="목업 3화면">
        {ROUTES.map((r) => (
          <a
            key={r.key}
            href={`#/${r.key}`}
            className={"nav-tab" + (route === r.key ? " active" : "")}
            data-testid={`nav-${r.key}`}
          >
            {r.label}
          </a>
        ))}
      </nav>
      <main className="content">
        {route === "intake" && <IntakeScreen intake={fixture.intake} />}
        {route === "strategy" && <StrategyScreen draft={fixture.draft} />}
        {route === "draft" && <DraftScreen draft={fixture.draft} />}
      </main>
    </div>
  );
}

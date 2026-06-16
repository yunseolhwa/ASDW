import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  CircleDot,
  Database,
  FileSearch,
  Filter,
  GitBranch,
  Layers3,
  LayoutDashboard,
  Network,
  ShieldCheck,
  SplitSquareVertical,
  Table2,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import dashboardData from "./data/theme-dashboard-data.json";

type TabId = "sessions" | "cockpit" | "schema";
type GateStatus = "pass" | "watch" | "fail" | "not_applicable";

type Session = {
  session_id: number;
  session_style: string;
  session_label: string;
  objective: string;
  owner_role: string;
  as_of_date: string;
};

type CandidateReadiness = {
  session_candidate_id: number;
  session_id: number;
  session_style: string;
  security_id: number;
  ticker: string;
  legal_name: string;
  decision_bucket: string;
  actionability: string;
  next_workflow: string;
  is_actionable: number;
  has_source_backed_exposure: number;
  required_gate_pass_count: number;
  required_gate_blocker_count: number;
  handoff_allowed: number;
};

type SessionCandidate = {
  session_candidate_id: number;
  variant_wedge: string;
  why_now: string;
  priced_in: string;
  first_rejection: string;
  investable_if: string;
  kill_if: string;
};

type Gate = {
  gate_id: number;
  session_candidate_id: number;
  gate_name: string;
  gate_status: GateStatus;
  gate_reason: string;
  required_flag: number;
};

type StaleData = {
  security_id: number;
  data_table: string;
  observation_type: string | null;
  metric_name: string | null;
  stale_days: number;
  max_age_days: number;
  severity: string;
};

type Conflict = {
  conflict_id: number;
  security_id: number;
  conflict_type?: string;
  diligence_decision?: string;
  long_short_decision?: string;
  long_only_decision?: string;
  resolution_note?: string;
  conflict_summary?: string;
};

type SchemaGroup = {
  id: string;
  label: string;
  description: string;
  tables: string[];
  views: string[];
  tableCounts: Record<string, number>;
  viewCounts: Record<string, number>;
};

type DashboardData = {
  db: {
    userVersion: number;
    tableCount: number;
    viewCount: number;
    generatedAt: string;
    foreignKeyCheck: unknown[];
  };
  theme: {
    theme_name: string;
    thesis_text: string;
    horizon_months: number;
    region_scope: string;
  };
  pathways: Array<{
    pathway_id: number;
    pathway_name: string;
    demand_driver: string;
    value_chain_role: string;
    priority_order: number;
  }>;
  sessions: Session[];
  candidates: CandidateReadiness[];
  sessionCandidates: SessionCandidate[];
  gates: Gate[];
  staleData: StaleData[];
  pmConflicts: Conflict[];
  sourceConflicts: Conflict[];
  handoffs: Array<{
    handoff_id: number;
    security_id: number;
    next_workflow: string;
    handoff_question: string;
    status: string;
  }>;
  schemaGroups: SchemaGroup[];
};

const data = dashboardData as unknown as DashboardData;

const SESSION_ORDER = ["public_equity_diligence", "long_short_hf", "long_only_pm"];

const SESSION_LABELS: Record<string, { title: string; subtitle: string }> = {
  public_equity_diligence: {
    title: "Public Diligence",
    subtitle: "증거 기반 리서치 큐",
  },
  long_short_hf: {
    title: "Long/Short HF",
    subtitle: "variant wedge와 catalyst",
  },
  long_only_pm: {
    title: "Long-only PM",
    subtitle: "benchmark fit과 진입 discipline",
  },
};

const FILTERS: Array<{ id: GateStatus; label: string }> = [
  { id: "pass", label: "Pass" },
  { id: "watch", label: "Watch" },
  { id: "fail", label: "Fail" },
];

function classNames(...items: Array<string | false | null | undefined>) {
  return items.filter(Boolean).join(" ");
}

function statusTone(value: string) {
  const lower = value.toLowerCase();
  if (lower === "pass" || lower.includes("reject")) return "bad";
  if (lower.includes("advance") || lower.includes("allowed")) return "good";
  if (lower.includes("watch") || lower.includes("gated") || lower.includes("proof")) return "watch";
  if (lower.includes("fail")) return "bad";
  return "neutral";
}

function gateTone(status: GateStatus) {
  if (status === "pass") return "good";
  if (status === "watch") return "watch";
  if (status === "fail") return "bad";
  return "neutral";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function AppHeader({ activeTab, setActiveTab }: { activeTab: TabId; setActiveTab: (tab: TabId) => void }) {
  const nav = [
    { id: "sessions" as const, label: "PM Session Board", icon: SplitSquareVertical },
    { id: "cockpit" as const, label: "Workflow Cockpit", icon: LayoutDashboard },
    { id: "schema" as const, label: "Schema Map", icon: Network },
  ];

  return (
    <header className="app-header">
      <div className="brand-lockup">
        <div className="brand-mark">
          <Database size={20} aria-hidden="true" />
        </div>
        <div>
          <h1>Public Equity Theme DB</h1>
          <p>SQLite 리서치 큐 온보딩</p>
        </div>
      </div>
      <nav className="tab-nav" aria-label="대시보드 보기">
        {nav.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={classNames("tab-button", activeTab === item.id && "active")}
              onClick={() => setActiveTab(item.id)}
              title={item.label}
              type="button"
            >
              <Icon size={16} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="header-meta">
        <span>v{data.db.userVersion}</span>
        <span>{formatDate(data.db.generatedAt)}</span>
      </div>
    </header>
  );
}

function KpiStrip() {
  const actionable = data.candidates.filter((candidate) => candidate.handoff_allowed === 1).length;
  const blocked = data.candidates.length - actionable;
  const fkOk = data.db.foreignKeyCheck.length === 0;
  const metrics = [
    { label: "PM 세션", value: data.sessions.length, detail: "분리 저장" },
    { label: "후보 판단", value: data.candidates.length, detail: `${actionable} actionable / ${blocked} blocked` },
    { label: "정책 stale", value: data.staleData.length, detail: "freshness policy 기준" },
    { label: "테이블 / 뷰", value: `${data.db.tableCount}/${data.db.viewCount}`, detail: fkOk ? "FK clean" : "FK issue" },
  ];

  return (
    <section className="kpi-strip" aria-label="데이터 요약">
      {metrics.map((metric) => (
        <div className="kpi-card" key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
          <small>{metric.detail}</small>
        </div>
      ))}
    </section>
  );
}

function CandidateCard({
  candidate,
  selected,
  onSelect,
  gates,
  visibleStatuses,
}: {
  candidate: CandidateReadiness;
  selected: boolean;
  onSelect: () => void;
  gates: Gate[];
  visibleStatuses: GateStatus[];
}) {
  const shownGates = gates.filter((gate) => visibleStatuses.includes(gate.gate_status));
  const blocked = candidate.handoff_allowed === 0;

  return (
    <button
      type="button"
      className={classNames("candidate-card", selected && "selected", blocked && "blocked")}
      onClick={onSelect}
    >
      <div className="candidate-topline">
        <div>
          <strong>{candidate.ticker}</strong>
          <span>{candidate.legal_name}</span>
        </div>
        {candidate.handoff_allowed ? (
          <CheckCircle2 className="icon-good" size={18} aria-label="handoff allowed" />
        ) : (
          <XCircle className="icon-bad" size={18} aria-label="blocked" />
        )}
      </div>
      <div className={classNames("decision-pill", statusTone(candidate.decision_bucket))}>
        {candidate.decision_bucket}
      </div>
      <div className="candidate-facts">
        <span>Action: {candidate.actionability}</span>
        <span>Evidence: {candidate.has_source_backed_exposure ? "source-backed" : "not proven"}</span>
        <span>Workflow: {candidate.next_workflow}</span>
      </div>
      <div className="gate-row" aria-label={`${candidate.ticker} gate statuses`}>
        {shownGates.map((gate) => (
          <span className={classNames("gate-chip", gateTone(gate.gate_status))} key={gate.gate_id}>
            {gate.gate_name}
          </span>
        ))}
      </div>
    </button>
  );
}

function DetailPanel({
  selected,
  gates,
  sessionCandidate,
}: {
  selected: CandidateReadiness;
  gates: Gate[];
  sessionCandidate?: SessionCandidate;
}) {
  const staleRows = selected.ticker === "ETN" ? data.staleData : [];
  const pmConflict = data.pmConflicts.find((item) => item.security_id === selected.security_id);
  const sourceConflict = data.sourceConflicts.find((item) => item.security_id === selected.security_id);

  return (
    <aside className="detail-panel">
      <div className="panel-heading">
        <div>
          <span className="eyeline">선택 후보</span>
          <h2>{selected.ticker} · {SESSION_LABELS[selected.session_style].title}</h2>
        </div>
        <div className={classNames("status-dot", selected.handoff_allowed ? "good" : "bad")} />
      </div>

      <div className="detail-block">
        <h3>PM 판단</h3>
        <dl>
          <div>
            <dt>Decision</dt>
            <dd>{selected.decision_bucket}</dd>
          </div>
          <div>
            <dt>Actionability</dt>
            <dd>{selected.actionability}</dd>
          </div>
          <div>
            <dt>Next workflow</dt>
            <dd>{selected.next_workflow}</dd>
          </div>
        </dl>
      </div>

      {sessionCandidate ? (
        <div className="detail-block narrative">
          <h3>왜 이렇게 판단했나</h3>
          <p><strong>Variant wedge</strong>{sessionCandidate.variant_wedge}</p>
          <p><strong>First rejection</strong>{sessionCandidate.first_rejection}</p>
          <p><strong>Investable if</strong>{sessionCandidate.investable_if}</p>
          <p><strong>Kill if</strong>{sessionCandidate.kill_if}</p>
        </div>
      ) : null}

      <div className="detail-block">
        <h3>Gate 상태</h3>
        <div className="gate-list">
          {gates.map((gate) => (
            <div className="gate-item" key={gate.gate_id}>
              <span className={classNames("gate-dot", gateTone(gate.gate_status))} />
              <div>
                <strong>{gate.gate_name}</strong>
                <p>{gate.gate_reason}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="detail-block alerts">
        <h3>주의 신호</h3>
        {staleRows.length ? (
          <div className="alert-line">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>{staleRows.length}개 stale data가 policy 기준을 초과했습니다.</span>
          </div>
        ) : (
          <div className="alert-line ok">
            <ShieldCheck size={16} aria-hidden="true" />
            <span>선택 세션에서 freshness blocker가 없습니다.</span>
          </div>
        )}
        {pmConflict ? (
          <div className="alert-line">
            <GitBranch size={16} aria-hidden="true" />
            <span>{pmConflict.resolution_note}</span>
          </div>
        ) : null}
        {sourceConflict ? (
          <div className="alert-line">
            <FileSearch size={16} aria-hidden="true" />
            <span>{sourceConflict.conflict_summary}</span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function SessionBoard() {
  const [selectedId, setSelectedId] = useState(1);
  const [visibleStatuses, setVisibleStatuses] = useState<GateStatus[]>(["pass", "watch", "fail"]);
  const selected = data.candidates.find((candidate) => candidate.session_candidate_id === selectedId) ?? data.candidates[0];
  const selectedGates = data.gates.filter((gate) => gate.session_candidate_id === selected.session_candidate_id);
  const selectedNarrative = data.sessionCandidates.find(
    (candidate) => candidate.session_candidate_id === selected.session_candidate_id,
  );

  function toggleStatus(status: GateStatus) {
    setVisibleStatuses((current) =>
      current.includes(status) ? current.filter((item) => item !== status) : [...current, status],
    );
  }

  return (
    <main className="screen-grid">
      <section className="board-region">
        <div className="section-toolbar">
          <div>
            <span className="eyeline">메인 보드</span>
            <h2>3개 PM 세션이 같은 후보를 다르게 판정합니다</h2>
          </div>
          <div className="filter-group" aria-label="Gate filter">
            <Filter size={16} aria-hidden="true" />
            {FILTERS.map((filter) => (
              <button
                key={filter.id}
                type="button"
                className={classNames("filter-button", visibleStatuses.includes(filter.id) && "active")}
                onClick={() => toggleStatus(filter.id)}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>

        <div className="lane-grid">
          {SESSION_ORDER.map((style) => {
            const session = data.sessions.find((item) => item.session_style === style);
            const candidates = data.candidates
              .filter((candidate) => candidate.session_style === style)
              .sort((a, b) => {
                const exposureDelta = b.has_source_backed_exposure - a.has_source_backed_exposure;
                if (exposureDelta) return exposureDelta;
                return a.ticker.localeCompare(b.ticker);
              });
            return (
              <section className="session-lane" key={style}>
                <div className="lane-header">
                  <div>
                    <h3>{SESSION_LABELS[style].title}</h3>
                    <p>{SESSION_LABELS[style].subtitle}</p>
                  </div>
                  <span>{session?.owner_role}</span>
                </div>
                <div className="lane-cards">
                  {candidates.map((candidate) => (
                    <CandidateCard
                      key={candidate.session_candidate_id}
                      candidate={candidate}
                      selected={candidate.session_candidate_id === selected.session_candidate_id}
                      gates={data.gates.filter((gate) => gate.session_candidate_id === candidate.session_candidate_id)}
                      visibleStatuses={visibleStatuses}
                      onSelect={() => setSelectedId(candidate.session_candidate_id)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </section>

      <DetailPanel selected={selected} gates={selectedGates} sessionCandidate={selectedNarrative} />
    </main>
  );
}

function WorkflowCockpit() {
  const steps = [
    { label: "테마", value: data.theme.theme_name, icon: CircleDot },
    { label: "경로", value: `${data.pathways.length} pathways`, icon: GitBranch },
    { label: "후보", value: "VRT / ETN", icon: Table2 },
    { label: "PM 세션", value: `${data.sessions.length} independent`, icon: SplitSquareVertical },
    { label: "핸드오프", value: "1 allowed", icon: ArrowRight },
  ];

  return (
    <main className="cockpit-layout">
      <section className="workflow-panel">
        <div className="section-toolbar">
          <div>
            <span className="eyeline">관리 탭</span>
            <h2>테마 스크린이 리서치 큐로 변환되는 흐름</h2>
          </div>
        </div>
        <div className="workflow-rail">
          {steps.map((step, index) => {
            const Icon = step.icon;
            return (
              <div className="workflow-step" key={step.label}>
                <div className="workflow-icon">
                  <Icon size={18} aria-hidden="true" />
                </div>
                <span>{step.label}</span>
                <strong>{step.value}</strong>
                {index < steps.length - 1 ? <ArrowRight size={18} className="workflow-arrow" aria-hidden="true" /> : null}
              </div>
            );
          })}
        </div>
        <div className="pathway-grid">
          {data.pathways.map((pathway) => (
            <article className="pathway-card" key={pathway.pathway_id}>
              <span>{pathway.value_chain_role}</span>
              <h3>{pathway.pathway_name}</h3>
              <p>{pathway.demand_driver}</p>
            </article>
          ))}
        </div>
      </section>

      <aside className="cockpit-side">
        <div className="detail-block">
          <h3>Readiness 요약</h3>
          <div className="summary-bars">
            <div>
              <span>Handoff allowed</span>
              <strong>{data.candidates.filter((item) => item.handoff_allowed).length}</strong>
            </div>
            <div>
              <span>Blocked / gated</span>
              <strong>{data.candidates.filter((item) => !item.handoff_allowed).length}</strong>
            </div>
            <div>
              <span>Source conflicts</span>
              <strong>{data.sourceConflicts.length}</strong>
            </div>
          </div>
        </div>
        <div className="detail-block">
          <h3>핸드오프 질문</h3>
          {data.handoffs.map((handoff) => (
            <div className="handoff-row" key={handoff.handoff_id}>
              <span>{handoff.next_workflow}</span>
              <p>{handoff.handoff_question}</p>
            </div>
          ))}
        </div>
      </aside>
    </main>
  );
}

function SchemaMap() {
  const [selectedGroupId, setSelectedGroupId] = useState("pm-session-layer");
  const selected = data.schemaGroups.find((group) => group.id === selectedGroupId) ?? data.schemaGroups[0];

  const totalRows = useMemo(
    () => Object.values(selected.tableCounts).reduce((sum, value) => sum + value, 0),
    [selected],
  );

  return (
    <main className="schema-layout">
      <section className="schema-canvas">
        <div className="section-toolbar">
          <div>
            <span className="eyeline">관리 탭</span>
            <h2>스키마 그룹 맵</h2>
          </div>
        </div>
        <div className="schema-grid">
          {data.schemaGroups.map((group) => (
            <button
              type="button"
              className={classNames("schema-node", selectedGroupId === group.id && "selected")}
              key={group.id}
              onClick={() => setSelectedGroupId(group.id)}
            >
              <Layers3 size={18} aria-hidden="true" />
              <strong>{group.label}</strong>
              <span>{group.tables.length} tables · {group.views.length} views</span>
            </button>
          ))}
        </div>
      </section>

      <aside className="schema-inspector">
        <div className="panel-heading">
          <div>
            <span className="eyeline">선택 그룹</span>
            <h2>{selected.label}</h2>
          </div>
          <BarChart3 size={20} aria-hidden="true" />
        </div>
        <p>{selected.description}</p>
        <div className="inspector-stat">
          <span>Rows in group</span>
          <strong>{totalRows}</strong>
        </div>
        <div className="table-list">
          <h3>Tables</h3>
          {selected.tables.map((table) => (
            <div className="table-row" key={table}>
              <span>{table}</span>
              <strong>{selected.tableCounts[table]}</strong>
            </div>
          ))}
        </div>
        {selected.views.length ? (
          <div className="table-list">
            <h3>Views</h3>
            {selected.views.map((view) => (
              <div className="table-row" key={view}>
                <span>{view}</span>
                <strong>{selected.viewCounts[view]}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </aside>
    </main>
  );
}

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");

  return (
    <div className="app-shell">
      <AppHeader activeTab={activeTab} setActiveTab={setActiveTab} />
      <KpiStrip />
      {activeTab === "sessions" ? <SessionBoard /> : null}
      {activeTab === "cockpit" ? <WorkflowCockpit /> : null}
      {activeTab === "schema" ? <SchemaMap /> : null}
    </div>
  );
}

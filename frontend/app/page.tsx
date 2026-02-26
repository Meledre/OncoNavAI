import AuthTabsCard from "@/components/shell/AuthTabsCard";

type HomePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

function sessionAuthMode(): "demo" | "credentials" | "idp" {
  const value = String(process.env.SESSION_AUTH_MODE || "")
    .trim()
    .toLowerCase();
  if (value === "idp") return "idp";
  return value === "credentials" ? "credentials" : "demo";
}

function sessionAuthUiOverride(): "off" | "all" {
  const value = String(process.env.SESSION_AUTH_UI_OVERRIDE || "off")
    .trim()
    .toLowerCase();
  return value === "all" ? "all" : "off";
}

function pickParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] || "";
  return value || "";
}

function sanitizeNext(raw: string): string {
  const value = raw.trim();
  if (!value.startsWith("/")) return "/doctor";
  if (value.startsWith("//")) return "/doctor";
  return value;
}

export default async function HomePage({ searchParams }: HomePageProps) {
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const next = sanitizeNext(pickParam(resolvedSearchParams?.next));
  const error = pickParam(resolvedSearchParams?.error);
  const authMode = sessionAuthMode();
  const authUiOverride = sessionAuthUiOverride();
  const idpNotice = "Вход выполняется через корпоративный провайдер идентификации.";
  const idpSessionPath = "/api/session/me";
  const errorText =
    error === "auth_required"
      ? "Требуется вход в роль перед открытием раздела."
      : error === "role_access_denied"
        ? "Недостаточно прав для этого раздела."
        : "";

  return (
    <div className="login-page" data-testid="login-page">
      <div className="login-split-layout">
        <section className="panel hero-card login-stage">
          <div className="login-brand">
            <p className="login-kicker">OncoAI // AETHER OS</p>
            <h1>Клиническая навигация для релизного контура</h1>
            <p className="muted">
              Система поддержки принятия клинических решений в онкологии. Анализ на основе руководств Минздрав, RUSSCO,
              ASCO/ESMO/NCCN.
            </p>
          </div>
          <div className="grid">
            <div className="terminal-line">
              <span className="terminal-prompt">◈</span>
              <span className="terminal-text">Интеграция: RUSSCO · Минздрав · ASCO/ESMO</span>
            </div>
            <div className="terminal-line">
              <span className="terminal-prompt">◈</span>
              <span className="terminal-text">Релизный профиль: strict_full · DEID-only</span>
            </div>
          </div>
          <div className="login-visual-placeholder login-geometry" aria-hidden="true">
            <div className="mono muted">OncoNav Wave · Full-traffic readiness</div>
          </div>
        </section>

        <AuthTabsCard
          mode={authMode}
          uiOverride={authUiOverride}
          nextPath={next}
          errorText={errorText}
          idpNotice={idpNotice}
          idpSessionPath={idpSessionPath}
        />
      </div>
    </div>
  );
}

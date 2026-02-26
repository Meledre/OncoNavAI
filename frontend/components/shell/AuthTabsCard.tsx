"use client";

import { useState } from "react";

type SessionAuthMode = "demo" | "credentials" | "idp";
type SessionAuthUiOverride = "off" | "all";

type AuthTabsCardProps = {
  mode: SessionAuthMode;
  uiOverride: SessionAuthUiOverride;
  nextPath: string;
  errorText: string;
  idpNotice?: string;
  idpSessionPath?: string;
};

function loginHref(role: "clinician" | "patient" | "admin", nextPath: string): string {
  const params = new URLSearchParams({
    role,
    next: nextPath
  });
  return `/api/session/login?${params.toString()}`;
}

export default function AuthTabsCard({
  mode,
  uiOverride,
  nextPath,
  errorText,
  idpNotice = "Вход выполняется через корпоративный провайдер идентификации.",
  idpSessionPath = "/api/session/me"
}: AuthTabsCardProps) {
  const showCredentials = uiOverride === "all" || mode === "credentials";
  const showDemo = uiOverride === "all" || mode === "demo";
  const showIdpHint = mode === "idp";
  const [activeTab, setActiveTab] = useState<"credentials" | "demo">(showDemo && !showCredentials ? "demo" : "credentials");

  return (
    <div className="panel login-auth-card">
      <div className="title-block">
        <span className="subtitle">OncoAI // Вход в систему</span>
        <h1>Идентификация</h1>
      </div>

      {errorText ? (
        <div style={{ padding: "10px 12px", border: "1px solid rgba(255,90,90,0.3)", background: "rgba(255,90,90,0.08)" }}>
          <span className="mono" style={{ color: "#ff9e9e", fontSize: "0.72rem" }}>
            ⚠ {errorText}
          </span>
        </div>
      ) : null}

      {showCredentials || showDemo ? (
        <>
          <div className="auth-tabs">
            {showCredentials ? (
              <button
                type="button"
                className={`auth-tab ${activeTab === "credentials" ? "active" : ""}`}
                onClick={() => setActiveTab("credentials")}
              >
                CREDENTIALS
              </button>
            ) : null}
            {showDemo ? (
              <button type="button" className={`auth-tab ${activeTab === "demo" ? "active" : ""}`} onClick={() => setActiveTab("demo")}>
                DEMO
              </button>
            ) : null}
          </div>

          {showCredentials && activeTab === "credentials" ? (
            <form method="post" action="/api/session/login" className="grid login-form">
              <label>
                Пользователь
                <input type="text" name="username" required autoComplete="username" defaultValue="dr.vance" />
              </label>
              <label>
                Пароль
                <input type="password" name="password" required autoComplete="current-password" />
              </label>
              <input type="hidden" name="next" value={nextPath} />
              <button type="submit" className="btn btn-primary">
                Войти в систему
              </button>
            </form>
          ) : null}

          {showDemo && activeTab === "demo" ? (
            <div className="grid">
              <a className="btn btn-primary" href={loginHref("clinician", nextPath)}>
                Войти как врач
              </a>
              <a className="btn" href={loginHref("patient", nextPath)}>
                Войти как пациент
              </a>
              <a className="btn" href={loginHref("admin", nextPath)}>
                Войти как администратор
              </a>
            </div>
          ) : null}
        </>
      ) : null}

      {showIdpHint ? (
        <div className="grid">
          <p className="muted">{idpNotice}</p>
          <p className="muted">
            Проверка сессии: <code>{idpSessionPath}</code>
          </p>
        </div>
      ) : null}
    </div>
  );
}

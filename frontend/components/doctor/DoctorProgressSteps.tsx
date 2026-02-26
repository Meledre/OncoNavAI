"use client";

type StepState = "todo" | "active" | "done" | "error";

type Props = {
  importState: StepState;
  analyzeState: StepState;
  buildState: StepState;
  testId?: string;
};

function rowClass(state: StepState): string {
  if (state === "done") return "progress-step done";
  if (state === "active") return "progress-step active";
  if (state === "error") return "progress-step active";
  return "progress-step";
}

function stateLabel(state: StepState): string {
  if (state === "done") return "Завершён";
  if (state === "active") return "В работе";
  if (state === "error") return "Ошибка";
  return "Ожидание";
}

export default function DoctorProgressSteps({ importState, analyzeState, buildState, testId = "doctor-progress-steps" }: Props) {
  return (
    <div className="progress-steps" data-testid={testId}>
      <article className={rowClass(importState)}>
        <small>Шаг 1</small>
        <strong>Импорт</strong>
        <span className="muted">{stateLabel(importState)}</span>
      </article>
      <article className={rowClass(analyzeState)}>
        <small>Шаг 2</small>
        <strong>Анализ</strong>
        <span className="muted">{stateLabel(analyzeState)}</span>
      </article>
      <article className={rowClass(buildState)}>
        <small>Шаг 3</small>
        <strong>Формирование отчёта</strong>
        <span className="muted">{stateLabel(buildState)}</span>
      </article>
    </div>
  );
}

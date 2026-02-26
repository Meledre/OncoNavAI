"use client";

import type { CitationV1_2 } from "@/lib/contracts/types";

type Props = {
  citations: CitationV1_2[];
  emptyLabel?: string;
};

function buildPdfHref(item: CitationV1_2): string {
  const page = Number.isFinite(item.page_start) ? Math.max(1, item.page_start) : 1;
  if (!item.file_uri || item.file_uri === "about:blank") return "about:blank";
  return item.file_uri.includes("#") ? item.file_uri : `${item.file_uri}#page=${page}`;
}

function buildOfficialPdfHref(item: CitationV1_2): string {
  const page = Number.isFinite(item.page_start) ? Math.max(1, item.page_start) : 1;
  if (!item.official_pdf_url) return "";
  return item.official_pdf_url.includes("#") ? item.official_pdf_url : `${item.official_pdf_url}#page=${page}`;
}

export default function EvidenceViewer({ citations, emptyLabel = "Нет подтверждающих цитат." }: Props) {
  if (!citations.length) {
    return <p className="muted">{emptyLabel}</p>;
  }

  return (
    <div className="evidence-list" data-testid="doctor-evidence-viewer">
      {citations.map((item) => (
        <details key={item.citation_id} className="evidence-item">
          <summary>
            <code>
              {item.source_id} / p.{item.page_start}
              {item.page_end > item.page_start ? `-${item.page_end}` : ""}
            </code>
            <span className="muted"> · {item.section_path || "Фрагмент рекомендации"}</span>
          </summary>
          <p className="muted">citation_id: {item.citation_id}</p>
          {item.official_page_url ? (
            <p>
              <a href={item.official_page_url} target="_blank" rel="noreferrer">
                Страница рекомендации
              </a>
            </p>
          ) : null}
          {item.official_pdf_url ? (
            <p>
              <a href={buildOfficialPdfHref(item)} target="_blank" rel="noreferrer">
                Официальный PDF
              </a>
            </p>
          ) : null}
          {item.file_uri && item.file_uri !== "about:blank" ? (
            <p>
              <a href={buildPdfHref(item)} target="_blank" rel="noreferrer">
                Локальный PDF (страница цитаты)
              </a>
            </p>
          ) : null}
          {item.quote ? <blockquote>{item.quote}</blockquote> : null}
        </details>
      ))}
    </div>
  );
}

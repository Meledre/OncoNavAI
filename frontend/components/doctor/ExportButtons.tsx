"use client";

import { useState } from "react";

import type { AnalyzeResponse } from "@/lib/contracts/types";

type Props = {
  report: AnalyzeResponse | null;
};

export default function ExportButtons({ report }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function saveBlob(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function downloadJson() {
    if (!report) return;
    setError(null);
    setBusy(true);
    try {
      const reportId = report.doctor_report.report_id;
      const response = await fetch(`/api/report/${reportId}/json`, {
        cache: "no-store"
      });

      if (response.ok) {
        const text = await response.text();
        saveBlob(new Blob([text], { type: "application/json" }), `${reportId}.json`);
        return;
      }

      // Fallback to in-memory object if report API is unavailable.
      saveBlob(
        new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
        `${report.doctor_report.report_id}.json`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "JSON export failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadHtml() {
    if (!report) return;
    setError(null);
    setBusy(true);
    try {
      const reportId = report.doctor_report.report_id;
      const response = await fetch(`/api/report/${reportId}/html`, {
        cache: "no-store"
      });
      if (!response.ok) {
        throw new Error(`HTML export failed: HTTP ${response.status}`);
      }
      const text = await response.text();
      saveBlob(new Blob([text], { type: "text/html;charset=utf-8" }), `${reportId}.html`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "HTML export failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    if (!report) return;
    setError(null);
    setBusy(true);
    try {
      const reportId = report.doctor_report.report_id;
      const response = await fetch(`/api/report/${reportId}/pdf`, {
        cache: "no-store"
      });
      if (!response.ok) {
        throw new Error(`PDF export failed: HTTP ${response.status}`);
      }
      const blob = await response.blob();
      saveBlob(blob, `${reportId}.pdf`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "PDF export failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocx() {
    if (!report) return;
    setError(null);
    setBusy(true);
    try {
      const reportId = report.doctor_report.report_id;
      const response = await fetch(`/api/report/${reportId}/docx`, {
        cache: "no-store"
      });
      if (!response.ok) {
        throw new Error(`DOCX export failed: HTTP ${response.status}`);
      }
      const blob = await response.blob();
      saveBlob(blob, `${reportId}.docx`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "DOCX export failed");
    } finally {
      setBusy(false);
    }
  }

  async function printReport() {
    if (!report) return;
    setError(null);
    setBusy(true);
    try {
      const reportId = report.doctor_report.report_id;
      const response = await fetch(`/api/report/${reportId}/html`, {
        cache: "no-store"
      });
      if (!response.ok) {
        throw new Error(`Print failed: HTTP ${response.status}`);
      }
      const text = await response.text();
      const printWindow = window.open("", "_blank", "noopener,noreferrer");
      if (!printWindow) {
        throw new Error("Failed to open print window");
      }
      printWindow.document.open();
      printWindow.document.write(text);
      printWindow.document.close();
      printWindow.focus();
      printWindow.print();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Print failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="action-row no-print">
        <button type="button" className="secondary" disabled={!report || busy} onClick={downloadJson} data-testid="doctor-export-json">
          Скачать JSON
        </button>
        <button type="button" className="secondary" disabled={!report || busy} onClick={downloadHtml} data-testid="doctor-export-html">
          Скачать HTML
        </button>
        <button type="button" className="secondary" disabled={!report || busy} onClick={downloadPdf} data-testid="doctor-export-pdf">
          Скачать PDF
        </button>
        <button type="button" className="secondary" disabled={!report || busy} onClick={downloadDocx} data-testid="doctor-export-docx">
          Скачать DOCX
        </button>
        <button type="button" className="secondary" disabled={!report || busy} onClick={printReport} data-testid="doctor-export-print">
          Печать
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  );
}

"use client";

import Tabs from "@/components/ui/Tabs";

export type AdminTabId = "docs" | "references" | "sync" | "import" | "security";

type Props = {
  activeTab: AdminTabId;
  onChange: (tab: AdminTabId) => void;
};

const ITEMS: { tab: AdminTabId; label: string }[] = [
  { tab: "docs", label: "Документы" },
  { tab: "references", label: "Справочники" },
  { tab: "sync", label: "Sync/Индексация" },
  { tab: "import", label: "Импорт кейсов" },
  { tab: "security", label: "Security Audit" }
];

export default function AdminTabs({ activeTab, onChange }: Props) {
  return (
    <Tabs
      testId="admin-tabs"
      items={ITEMS}
      activeTab={activeTab}
      onTabChange={(tab) => onChange(tab as AdminTabId)}
    />
  );
}

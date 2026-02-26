"use client";

type TabItem = {
  tab: string;
  label: string;
};

type Props = {
  items: TabItem[];
  activeTab: string;
  onTabChange: (tab: string) => void;
  testId?: string;
};

export default function Tabs({ items, activeTab, onTabChange, testId }: Props) {
  return (
    <div className="tabs-list" role="tablist" aria-label="Admin sections" data-testid={testId}>
      {items.map((item) => {
        const isActive = item.tab === activeTab;
        return (
          <button
            key={item.tab}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={isActive ? "tabs-trigger active" : "tabs-trigger"}
            onClick={() => onTabChange(item.tab)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

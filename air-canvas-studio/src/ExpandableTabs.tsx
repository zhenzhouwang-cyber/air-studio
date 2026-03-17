import * as React from "react";

type ExpandableTab = {
  title: string;
  icon: React.ReactNode;
};

type Separator = { type: "separator" };
type TabItem = ExpandableTab | Separator;

type Props = {
  tabs: TabItem[];
  selectedIndex: number | null;
  onChange: (index: number | null) => void;
  className?: string;
};

export default function ExpandableTabs({ tabs, selectedIndex, onChange, className = "" }: Props) {
  const ref = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    function onDocDown(e: MouseEvent) {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) {
        onChange(null);
      }
    }
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [onChange]);

  return (
    <div ref={ref} className={`expand-tabs ${className}`}>
      {tabs.map((tab, idx) => {
        if ("type" in tab) {
          return <span key={`sep-${idx}`} className="expand-tabs-sep" />;
        }

        const selected = selectedIndex === idx;
        return (
          <button
            key={`${tab.title}-${idx}`}
            type="button"
            className={`expand-tab ${selected ? "selected" : ""}`}
            onClick={() => onChange(selected ? null : idx)}
          >
            <span className="expand-tab-icon">{tab.icon}</span>
            <span className={`expand-tab-title ${selected ? "show" : ""}`}>{tab.title}</span>
          </button>
        );
      })}
    </div>
  );
}

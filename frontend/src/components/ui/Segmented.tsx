import clsx from "clsx";

export function Segmented<T extends string>({ label, value, onChange, options, size = "md" }: { label: string; value: T; onChange: (v: T) => void; options: [T, string][]; size?: "sm" | "md" }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-[9px] bg-sunken p-0.5">
      {options.map(([v, l]) => (
        <button key={v} onClick={() => onChange(v)} aria-pressed={value === v}
          className={clsx("rounded-[7px] font-medium transition-colors cursor-pointer", size === "md" ? "h-8 px-3 text-[13px]" : "h-7 px-2.5 text-[12.5px]",
            value === v ? "bg-surface text-text shadow-[var(--shadow-sm)]" : "text-muted hover:text-text")}>{l}</button>
      ))}
    </div>
  );
}

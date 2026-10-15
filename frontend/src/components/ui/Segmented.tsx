import clsx from "clsx";

/** A row of mutually exclusive choices: one track, the chosen one raised. */
export function Segmented<T extends string>({ label, value, onChange, options, size = "md" }: { label: string; value: T; onChange: (v: T) => void; options: [T, string][]; size?: "sm" | "md" }) {
  return (
    <div role="group" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-[6px] bg-sunken p-0.5 [scrollbar-width:none]">
      {options.map(([v, l]) => (
        <button key={v} onClick={() => onChange(v)} aria-pressed={value === v}
          className={clsx("shrink-0 whitespace-nowrap rounded-[5px] font-medium transition-colors cursor-pointer", size === "md" ? "h-7 px-3 text-[13px]" : "h-6 px-2.5 text-[12.5px]",
            value === v ? "bg-surface text-text shadow-[var(--shadow-sm)] ring-1 ring-border" : "text-muted hover:text-text")}>{l}</button>
      ))}
    </div>
  );
}

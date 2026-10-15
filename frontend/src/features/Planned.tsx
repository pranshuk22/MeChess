import { Panel } from "@/components/ui/Panel";

export function Planned({ title, text, items, milestone }: { title: string; text: string; items: string[]; milestone: string }) {
  return (
    <div className="mx-auto max-w-[720px] p-8 max-md:p-4">
      <Panel className="p-6">
        <h2 className="text-[18px] font-semibold">{title}</h2>
        <p className="mt-2 text-muted">{text}</p>
        <ul className="mt-4 list-disc space-y-1.5 pl-5">{items.map((i) => <li key={i}>{i}</li>)}</ul>
        <p className="mt-5 text-[12.5px] text-faint">Not in the prototype yet: planned for {milestone}.</p>
      </Panel>
    </div>
  );
}

import { TriangleAlert } from "lucide-react";
import { Link, useRouteError } from "react-router-dom";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/Misc";
import { Panel } from "./ui/Panel";

/** Shown when a page fails while it renders: a message and a way out, instead of a blank screen. */
export function RouteError() {
  const err = useRouteError() as { message?: string } | undefined;
  return (
    <div className="mx-auto max-w-[640px] px-6 py-16">
      <Panel>
        <EmptyState icon={TriangleAlert} title="Something went wrong on this page" text={<>The rest of MeChess is fine. {err?.message && <code className="mt-2 block break-words rounded bg-sunken px-2 py-1 font-mono text-[12px]">{err.message}</code>}</>}
          action={<Link to="/library"><Button variant="primary">Back to the library</Button></Link>} />
      </Panel>
    </div>
  );
}

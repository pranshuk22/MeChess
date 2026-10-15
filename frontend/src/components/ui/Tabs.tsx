import * as RTabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import type { ComponentProps } from "react";

/** Underlined tabs: one style for every page (Coach, Prepare, Review). The list scrolls sideways when it does not fit. */
export const TabList = ({ className, ...p }: ComponentProps<typeof RTabs.List>) => (
  <RTabs.List {...p} className={clsx("flex max-w-full gap-0.5 overflow-x-auto border-b border-border [scrollbar-width:none]", className)} />
);
export const TabTrigger = ({ className, ...p }: ComponentProps<typeof RTabs.Trigger>) => (
  <RTabs.Trigger {...p} className={clsx("-mb-px shrink-0 cursor-pointer whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-[13px] font-medium text-muted transition-colors hover:text-text data-[state=active]:border-accent data-[state=active]:text-text", className)} />
);
export const Tabs = RTabs;

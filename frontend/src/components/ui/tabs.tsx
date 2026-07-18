import type { ButtonHTMLAttributes, HTMLAttributes } from "react";

import { cn } from "../../lib/utils";

export function TabsList({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("grid grid-cols-3 border-b border-slate-800", className)} {...props} />;
}

export function TabsTrigger({ active, className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      className={cn("border-b-2 px-2 py-3 text-[11px] font-medium text-slate-500 transition hover:text-slate-200", active ? "border-cyan-400 text-cyan-300" : "border-transparent", className)}
      {...props}
    />
  );
}

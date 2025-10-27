import type { AlertMessage } from "@/lib/alertStore";

export const variantClasses: Record<AlertMessage["variant"], string> = {
	success: "bg-emerald-600/90 border-emerald-400 text-white",
	warning: "bg-amber-600/90 border-amber-400 text-white",
	error: "bg-rose-700/90 border-rose-500 text-white",
	info: "bg-slate-700/90 border-slate-500 text-white",
};

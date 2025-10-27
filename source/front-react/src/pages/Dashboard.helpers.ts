export function isSmallScreen(): boolean {
	if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
	return window.matchMedia("(max-width: 900px)").matches;
}

export function formatDate(value: string): string {
	try {
		return new Date(value).toLocaleString();
	} catch {
		return value;
	}
}

export function statusTone(status: string): string {
	const normalized = status.toLowerCase();
	if (normalized.includes("error") || normalized.includes("failed")) return "text-rose-300";
	if (normalized.includes("running")) return "text-emerald-300";
	if (normalized.includes("stop")) return "text-amber-300";
	return "text-sky-300";
}

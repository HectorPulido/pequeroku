const normalizeBase = (value?: string | null): string => {
	if (!value) return "/";
	const trimmed = value.trim();
	if (!trimmed) return "/";
	const withLeading = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
	return withLeading.endsWith("/") ? withLeading : `${withLeading}/`;
};

const matchesAppPrefix = (pathname: string) => {
	if (!pathname) return false;
	if (pathname === "/app" || pathname === "/app/") return true;
	return pathname.startsWith("/app/");
};

// Fold a same-origin reverse-proxy prefix into the build-time base. PequeRoku's
// own preview proxy serves apps under /api/containers/<id>/preview/<port>/...,
// and React Router reads the real window.location.pathname (it ignores the
// <base> tag the proxy injects), so the proxy prefix must become part of the
// router basename. Without this, a dashboard built with base "/dashboard/"
// fails to match "/api/containers/<id>/preview/<port>/dashboard/" when previewed.
const applyProxyPrefix = (base: string): string => {
	if (typeof window === "undefined") return base;
	const segment = base.replace(/\/$/, ""); // e.g. "/dashboard"
	if (!segment) return base;
	const { pathname } = window.location;
	const idx = pathname.indexOf(segment);
	// idx === 0 → base already at the root (no proxy); idx < 0 → not present.
	if (idx <= 0) return base;
	// Require a path boundary so "/app" doesn't match "/application".
	const after = pathname.charAt(idx + segment.length);
	if (after !== "" && after !== "/") return base;
	return pathname.slice(0, idx) + base; // proxyPrefix + base
};

export const DEFAULT_APP_BASE = "/app/";

export const resolveAppBase = (): string => {
	const envBase = normalizeBase(import.meta.env?.BASE_URL ?? "/");
	if (envBase !== "/") {
		return applyProxyPrefix(envBase);
	}
	if (typeof window !== "undefined") {
		const { pathname } = window.location;
		if (matchesAppPrefix(pathname)) {
			return DEFAULT_APP_BASE;
		}
	}
	return "/";
};

export const buildAppUrl = (path: string, base = resolveAppBase()): string => {
	const normalizedBase = normalizeBase(base);
	const cleanPath = path.replace(/^\//, "");
	if (!cleanPath) {
		return normalizedBase === "/" ? "/" : normalizedBase;
	}
	return normalizedBase === "/" ? `/${cleanPath}` : `${normalizedBase}${cleanPath}`;
};

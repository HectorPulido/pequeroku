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

export const DEFAULT_APP_BASE = "/app/";

export const resolveAppBase = (): string => {
	const envBase = normalizeBase(import.meta.env?.BASE_URL ?? "/");
	if (envBase !== "/") {
		return envBase;
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

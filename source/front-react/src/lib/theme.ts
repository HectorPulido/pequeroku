const THEME_STORAGE_KEY = "pequeroku:theme";

export type Theme = "dark" | "light";

const subscribers = new Set<(theme: Theme) => void>();

let currentTheme: Theme = ((): Theme => {
	if (typeof window === "undefined") return "dark";
	const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
	if (stored === "light" || stored === "dark") return stored;
	if (window.matchMedia?.("(prefers-color-scheme: light)").matches) {
		return "light";
	}
	return "dark";
})();

function apply(theme: Theme) {
	currentTheme = theme;
	if (typeof document !== "undefined") {
		const root = document.documentElement;
		root.dataset.theme = theme;
		const classList = root.classList;
		if (classList) {
			classList.toggle("dark", theme === "dark");
			classList.toggle("light", theme === "light");
		}
	}
	if (typeof window !== "undefined") {
		window.localStorage.setItem(THEME_STORAGE_KEY, theme);
		window.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
	}
	subscribers.forEach((listener) => {
		listener(theme);
	});
}

export const themeManager = {
	get(): Theme {
		return currentTheme;
	},
	set(theme: Theme) {
		apply(theme);
	},
	toggle() {
		apply(currentTheme === "dark" ? "light" : "dark");
	},
	subscribe(listener: (theme: Theme) => void) {
		subscribers.add(listener);
		return () => {
			subscribers.delete(listener);
		};
	},
};

apply(currentTheme);

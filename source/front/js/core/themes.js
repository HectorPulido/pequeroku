const STORAGE_KEY = "ui:theme";

function getSystemPrefersDark() {
	return window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function getCurrentTheme() {
	const saved = localStorage.getItem(STORAGE_KEY);
	if (saved === "light" || saved === "dark") return saved;
	return getSystemPrefersDark() ? "dark" : "light";
}

export function applyTheme(theme) {
	const t = theme || getCurrentTheme();
	document.documentElement.setAttribute("data-theme", t);
	localStorage.setItem(STORAGE_KEY, t);
	window.dispatchEvent(
		new CustomEvent("themechange", { detail: { theme: t } }),
	);
}

export function toggleTheme() {
	const next = getCurrentTheme() === "dark" ? "light" : "dark";
	applyTheme(next);
}

export function setupThemeToggle(btn) {
	const setIcon = (t) => {
		btn.innerHTML =
			t === "dark"
				? '<i class="iconoir-light-bulb-on"></i>'
				: '<i class="iconoir-light-bulb-off"></i>';
	};
	setIcon(getCurrentTheme());
	btn.addEventListener("click", () => {
		toggleTheme();
		setIcon(getCurrentTheme());
	});
	const mq = window.matchMedia("(prefers-color-scheme: dark)");
	mq.addEventListener?.("change", () => {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (!saved) applyTheme(getSystemPrefersDark() ? "dark" : "light");
	});
}

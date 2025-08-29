export function installGlobalLoader() {
	const overlay = document.getElementById("global-loader");
	if (!overlay) return;
	let active = 0;
	const show = () => overlay.classList.remove("hidden");
	const hide = () => overlay.classList.add("hidden");

	const base = window.fetch.bind(window);
	window.fetch = async (...args) => {
		active++;
		if (active === 1) show();
		try {
			return await base(...args);
		} finally {
			active = Math.max(0, active - 1);
			if (active === 0) hide();
		}
	};
}

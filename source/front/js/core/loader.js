import { $ } from "../core/dom.js";

export function installGlobalLoader() {
	const overlay = $("#global-loader");
	if (!overlay) return;
	let active = 0;
	const show = () => overlay.classList.remove("hidden");
	const hide = () => overlay.classList.add("hidden");

	const base = window.fetch.bind(window);
	window.fetch = async (input, init = {}) => {
		const noLoader = init?.noLoader;
		if (noLoader) {
			const { _noLoader, ...cleanInit } = init;
			return base(input, cleanInit);
		}

		active++;
		if (active === 1) show();
		try {
			return await base(input, init);
		} finally {
			active = Math.max(0, active - 1);
			if (active === 0) hide();
		}
	};
}

import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({ api, fileTreeEl, onOpen }) {
	const menu = document.getElementById("finder-menu");
	let menuTarget = null;

	async function listDir(path = "/app") {
		return api(`/list_dir/?path=${encodeURIComponent(path)}`);
	}

	async function loadDir(path, ul) {
		ul.innerHTML = "";
		const items = await listDir(path);
		const prefix = `${path.replace(/\/$/, "")}/`;
		const direct = items.filter(
			(item) =>
				item.path.startsWith(prefix) &&
				item.path.slice(prefix.length) &&
				!item.path.slice(prefix.length).includes("/"),
		);
		direct.sort((a, b) =>
			a.path_type === b.path_type
				? a.name.localeCompare(b.name)
				: a.path_type === "directory"
					? -1
					: 1,
		);
		direct.forEach((item) => {
			const li = document.createElement("li");
			li.classList.add(item.path_type);
			li.textContent = item.name;
			li.dataset.path = item.path;
			li.dataset.type = item.path_type;
			if (item.path_type === "directory") {
				li.addEventListener("click", async (e) => {
					e.stopPropagation();
					const isExp = li.classList.toggle("expanded");
					if (isExp) {
						const sub = document.createElement("ul");
						li.appendChild(sub);
						await loadDir(item.path, sub);
					} else {
						const sub = li.querySelector("ul");
						if (sub) li.removeChild(sub);
					}
				});
			} else {
				li.addEventListener("click", (e) => {
					e.stopPropagation();
					onOpen(item.path);
				});
			}
			li.addEventListener("contextmenu", (e) => {
				e.preventDefault();
				e.stopPropagation();
				openContextMenu(e, li);
			});
			ul.appendChild(li);
		});
	}

	function openContextMenu(e, li) {
		menuTarget = li; // li.dataset.path / li.dataset.type
		menu.classList.remove("hidden");
		const { innerWidth, innerHeight } = window;
		const rectW = 200,
			rectH = 180;
		let x = e.clientX,
			y = e.clientY;
		if (x + rectW > innerWidth) x = innerWidth - rectW - 8;
		if (y + rectH > innerHeight) y = innerHeight - rectH - 8;
		menu.style.left = `${x}px`;
		menu.style.top = `${y}px`;
	}

	function closeMenu() {
		menu.classList.add("hidden");
		menuTarget = null;
	}
	window.addEventListener("click", closeMenu);
	window.addEventListener("scroll", closeMenu);
	window.addEventListener("resize", closeMenu);
	menu.addEventListener("click", (ev) => {
		const act = ev.target?.getAttribute?.("data-action");
		if (!act || !menuTarget) return;
		const detail = {
			action: act,
			path: menuTarget.dataset.path,
			type: menuTarget.dataset.type,
		};
		fileTreeEl.dispatchEvent(new CustomEvent("finder-action", { detail }));
		closeMenu();
	});

	async function refresh() {
		await loadDir("/app", fileTreeEl);
	}
	return { refresh, detectLangFromPath };
}

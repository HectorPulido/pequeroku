import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({ api, fileTreeEl, onOpen }) {
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
			ul.appendChild(li);
		});
	}

	async function refresh() {
		await loadDir("/app", fileTreeEl);
	}
	return { refresh, detectLangFromPath };
}

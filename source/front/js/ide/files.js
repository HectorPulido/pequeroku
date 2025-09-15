import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({ api, fileTreeEl, onOpen, containerId }) {
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

	async function newFolder(path, type) {
		const name = prompt("Folder name:");
		if (!name) return;

		let dir = "";
		if (path == null) {
			dir = `/app/${name}`;
		} else {
			dir = type === "directory" ? path : path.replace(/\/[^/]+$/, "");
			dir = `${dir.replace(/\/$/, "")}/${name}`;
		}

		await api("/create_dir/", {
			method: "POST",
			body: JSON.stringify({ path: dir }),
		});
		await refresh();
	}

	async function newFile(path, setPath, saveCurrentFile, clearEditor, type) {
		const name = prompt("File name:");
		if (!name) return;

		let dir = "";
		if (path == null) {
			dir = `/app/${name}`;
		} else {
			dir = type === "directory" ? path : path.replace(/\/[^/]+$/, "");
			dir = `${dir.replace(/\/$/, "")}/${name}`;
		}
		setPath(dir);
		clearEditor();
		await saveCurrentFile();
		await refresh();
	}

	async function finderAction(
		e,
		openFileIntoEditor,
		setPath,
		clearEditor,
		saveCurrentFile,
		currentFilePath,
	) {
		const { action, path, type } = e.detail || {};
		console.log(action, path, type);
		if (!action || !path) return;
		try {
			if (action === "open") {
				if (type === "directory") return;
				await openFileIntoEditor(api, path, setPath);
			}
			if (action === "delete") {
				if (!confirm(`Delete "${path}"?`)) return;
				await api("/delete_path/", {
					method: "POST",
					body: JSON.stringify({ path }),
				});
				parent.addAlert(`Deleted: ${path}`, "success");
				await refresh();
				if (currentFilePath === path) {
					currentFilePath = null;
					clearEditor();
					pathLabel.innerText = "";
				}
			}
			if (action === "rename") {
				const base = path.split("/").pop();
				const name = prompt("New name:", base);
				if (!name || name === base) return;
				const new_path = path.replace(/\/[^/]+$/, `/${name}`);
				await api("/move_path/", {
					method: "POST",
					body: JSON.stringify({ src: path, dest: new_path }),
				});
				parent.addAlert(`Renamed to: ${new_path}`, "success");
				await refresh();
				if (currentFilePath === path) {
					await openFileIntoEditor(api, new_path, setPath);
				}
			}
			if (action === "new-file") {
				newFile(path, setPath, saveCurrentFile, clearEditor, type);
			}
			if (action === "new-folder") {
				newFolder(path, type);
			}
			if (action === "download") {
				if (type === "directory") {
					open(`/api/containers/${containerId}/download_folder/?root=${path}`);
				} else {
					open(`/api/containers/${containerId}/download_file/?path=${path}`);
				}
			}
		} catch (err) {
			parent.addAlert(err.message || String(err), "error");
		}
	}

	return { refresh, detectLangFromPath, finderAction, newFolder, newFile };
}

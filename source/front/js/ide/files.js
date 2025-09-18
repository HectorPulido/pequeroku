import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({ fsws, fileTreeEl, onOpen, containerId }) {
	let refreshing = false;

	const menu = document.getElementById("finder-menu");
	let menuTarget = null;

	// === WS: list_dir ===
	async function listDir(path = "/app") {
		const r = await fsws.call("list_dir", { path });
		return r.entries || [];
	}

	async function loadDir(path, ul) {
		if (refreshing) {
			console.log("Refresing dedup...");
			return;
		}

		refreshing = true;
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
		refreshing = false;
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
		console.log("Refreshing...");
		await loadDir("/app", fileTreeEl);
	}

	// === WS: create_dir ===
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

		await fsws.call("create_dir", { path: dir });
		await refresh();
	}

	// newFile doesn't create anything in the FS yet: adjusts the path, clears the editor, and delegates to saveCurrentFile
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

	// === WS in finder actions ===
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
				await openFileIntoEditor(path);
			}
			if (action === "delete") {
				if (!confirm(`Delete "${path}"?`)) return;
				await fsws.call("delete_path", { path });
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
				await fsws.call("move_path", { src: path, dst: new_path });
				parent.addAlert(`Renamed to: ${new_path}`, "success");
				await refresh();
				if (currentFilePath === path) {
					await openFileIntoEditor(new_path);
				}
			}
			if (action === "new-file") {
				newFile(path, setPath, saveCurrentFile, clearEditor, type);
			}
			if (action === "new-folder") {
				newFolder(path, type);
			}
			if (action === "download") {
				// Downloads still go over HTTP
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

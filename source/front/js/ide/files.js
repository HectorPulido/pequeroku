import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({ fsws, fileTreeEl, onOpen, containerId }) {
	let refreshing = false;

	const menu = document.getElementById("finder-menu");
	let menuTarget = null;

	// Persist expanded folders per container
	const EXP_KEY = `ui:ft:exp:${containerId}`;
	let expandedPaths = new Set();
	try {
		const saved = JSON.parse(localStorage.getItem(EXP_KEY) || "[]");
		if (Array.isArray(saved)) expandedPaths = new Set(saved);
	} catch {}
	function persistExpanded() {
		try {
			localStorage.setItem(EXP_KEY, JSON.stringify(Array.from(expandedPaths)));
		} catch {}
	}

	// Persist single selection per container
	const SEL_KEY = `ui:ft:sel:${containerId}`;
	let selectedPath = null;
	try {
		const savedSel = localStorage.getItem(SEL_KEY);
		if (typeof savedSel === "string" && savedSel) selectedPath = savedSel;
	} catch {}
	function setSelected(path) {
		selectedPath = path || null;
		try {
			if (selectedPath) localStorage.setItem(SEL_KEY, selectedPath);
			else localStorage.removeItem(SEL_KEY);
		} catch {}
		// clear previous
		fileTreeEl
			.querySelectorAll("li.selected")
			.forEach((el) => el.classList.remove("selected"));
		if (!selectedPath) return;
		const node = Array.from(fileTreeEl.querySelectorAll("li[data-path]")).find(
			(el) => el.dataset.path === selectedPath,
		);
		if (node) node.classList.add("selected");
	}

	// === WS: list_dir ===
	async function listDir(path = "/app") {
		const r = await fsws.call("list_dir", { path });
		return r.entries || [];
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

		for (const item of direct) {
			const li = document.createElement("li");
			li.classList.add(item.path_type);
			li.textContent = item.name;
			li.dataset.path = item.path;
			li.dataset.type = item.path_type;

			if (item.path_type === "directory") {
				li.addEventListener("click", async (e) => {
					e.stopPropagation();
					setSelected(item.path);
					const willExpand = !li.classList.contains("expanded");
					if (willExpand) {
						li.classList.add("expanded");
						expandedPaths.add(item.path);
						persistExpanded();
						let sub = li.querySelector("ul");
						if (!sub) {
							sub = document.createElement("ul");
							li.appendChild(sub);
						}
						await loadDir(item.path, sub);
					} else {
						li.classList.remove("expanded");
						expandedPaths.delete(item.path);
						persistExpanded();
						const sub = li.querySelector("ul");
						if (sub) li.removeChild(sub);
					}
				});
			} else {
				li.addEventListener("click", (e) => {
					e.stopPropagation();
					setSelected(item.path);
					onOpen(item.path);
				});
			}
			li.addEventListener("contextmenu", (e) => {
				e.preventDefault();
				e.stopPropagation();
				openContextMenu(e, li);
			});

			ul.appendChild(li);

			// Auto-restore expansion state for this directory
			if (item.path_type === "directory" && expandedPaths.has(item.path)) {
				li.classList.add("expanded");
				const sub = document.createElement("ul");
				li.appendChild(sub);
				await loadDir(item.path, sub);
			}
		}
	}

	function openContextMenu(e, li) {
		menuTarget = li; // li.dataset.path / li.dataset.type
		// select the target item on context menu
		if (li?.dataset?.path) setSelected(li.dataset.path);
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
		if (refreshing) {
			console.log("Refreshing dedup...");
			return;
		}
		refreshing = true;
		const prevScroll = fileTreeEl.scrollTop;
		await loadDir("/app", fileTreeEl);
		// re-apply selection after rebuilding the tree
		if (selectedPath) setSelected(selectedPath);
		fileTreeEl.scrollTop = prevScroll;
		refreshing = false;
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

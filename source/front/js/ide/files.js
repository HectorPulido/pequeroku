import { notifyAlert } from "../core/alerts.js";
import { detectLangFromPath } from "../shared/langMap.js";

export function setupFileTree({
	fsws,
	fileTreeEl,
	onOpen,
	containerId,
	onClearCurrent,
}) {
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
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			.forEach((el) => el.classList.remove("selected"));
		if (!selectedPath) return;
		const node = Array.from(fileTreeEl.querySelectorAll("li[data-path]")).find(
			(el) => el.dataset.path === selectedPath,
		);
		if (node) node.classList.add("selected");
	}

	// === WS: list_dir (cached) ===
	const dirCache = new Map();
	const DIR_TTL_MS = 3000;
	function cacheGet(path) {
		const v = dirCache.get(path);
		if (!v) return null;
		if (Date.now() - v.ts > DIR_TTL_MS) {
			dirCache.delete(path);
			return null;
		}
		return v.entries;
	}
	function cacheSet(path, entries) {
		dirCache.set(path, { entries, ts: Date.now() });
	}
	function invalidateDirCache(path) {
		const base = path.replace(/\/$/, "");
		for (const key of Array.from(dirCache.keys())) {
			if (key === base || key.startsWith(`${base}/`)) dirCache.delete(key);
		}
	}
	async function listDir(path = "/app", force = false) {
		// In-flight de-dup to avoid duplicate WS calls for the same dir
		listDir._inflight = listDir._inflight || new Map();
		if (!force) {
			const cached = cacheGet(path);
			if (cached) return cached;
			const p0 = listDir._inflight.get(path);
			if (p0) return p0;
		}
		const p = (async () => {
			const r = await fsws.call("list_dir", { path });
			const entries = r.entries || [];
			cacheSet(path, entries);
			return entries;
		})();
		if (!force) listDir._inflight.set(path, p);
		try {
			return await p;
		} finally {
			listDir._inflight.delete(path);
		}
	}

	async function loadDir(path, ul, force = false) {
		// Build the entire subtree in one shot:
		// 1) compute all directories to fetch (base + expanded descendants)
		// 2) fetch list_dir for all targets in parallel
		// 3) render DOM synchronously using the pre-fetched map
		const base = path.replace(/\/$/, "");
		const targets = new Set([base]);
		for (const p of expandedPaths) {
			if (p === base || p.startsWith(`${base}/`)) targets.add(p);
		}

		const targetList = Array.from(targets);
		const results = await Promise.all(targetList.map((p) => listDir(p, force)));
		const dirMap = new Map();
		// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
		targetList.forEach((p, i) => dirMap.set(p, results[i] || []));

		function getDirectChildren(parentPath) {
			const items = dirMap.get(parentPath) || [];
			const prefix = `${parentPath.replace(/\/$/, "")}/`;
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
			return direct;
		}

		function buildSubtree(parentPath) {
			const container = document.createElement("ul");
			const direct = getDirectChildren(parentPath);

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
							const sub =
								li.querySelector("ul") ||
								li.appendChild(document.createElement("ul"));
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

				container.appendChild(li);

				// If this directory is expanded, build its subtree synchronously from pre-fetched data
				if (item.path_type === "directory" && expandedPaths.has(item.path)) {
					li.classList.add("expanded");
					const sub = document.createElement("ul");
					li.appendChild(sub);
					const built = buildSubtree(item.path);
					sub.replaceChildren(...Array.from(built.children));
				}
			}
			return container;
		}

		const built = buildSubtree(base);
		ul.replaceChildren(...Array.from(built.children));
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

	async function getUlForPath(path) {
		if (path === "/app") return fileTreeEl;
		const li = fileTreeEl.querySelector(`li[data-path="${path}"]`);
		if (!li) return null;
		let sub = li.querySelector("ul");
		if (!sub) {
			sub = document.createElement("ul");
			li.appendChild(sub);
		}
		return sub;
	}

	async function refreshPath(path) {
		const ul = await getUlForPath(path);
		if (!ul) return; // Not visible; nothing to update
		const prevScroll = fileTreeEl.scrollTop;
		invalidateDirCache(path);
		await loadDir(path, ul, true);
		if (selectedPath) setSelected(selectedPath);
		fileTreeEl.scrollTop = prevScroll;
	}

	async function refresh() {
		// Bust root cache and refresh only root
		invalidateDirCache("/app");
		await refreshPath("/app");
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
		const parentDir = dir.replace(/\/[^/]+$/, "");
		invalidateDirCache(parentDir);
		await refreshPath(parentDir);
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
		const parentDir = dir.replace(/\/[^/]+$/, "");
		invalidateDirCache(parentDir);
		await refreshPath(parentDir);
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
				notifyAlert(`Deleted: ${path}`, "success");
				const parentDir = path.replace(/\/[^/]+$/, "");
				invalidateDirCache(parentDir);
				await refreshPath(parentDir);
				if (currentFilePath === path) {
					currentFilePath = null;
					clearEditor();
					onClearCurrent?.();
				}
			}
			if (action === "rename") {
				const base = path.split("/").pop();
				const name = prompt("New name:", base);
				if (!name || name === base) return;
				const new_path = path.replace(/\/[^/]+$/, `/${name}`);
				await fsws.call("move_path", { src: path, dst: new_path });
				notifyAlert(`Renamed to: ${new_path}`, "success");
				const oldParent = path.replace(/\/[^/]+$/, "");
				const newParent = new_path.replace(/\/[^/]+$/, "");
				invalidateDirCache(oldParent);
				invalidateDirCache(newParent);
				if (oldParent === newParent) {
					await refreshPath(oldParent);
				} else {
					await Promise.all([refreshPath(oldParent), refreshPath(newParent)]);
				}
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
			notifyAlert(err.message || String(err), "error");
		}
	}

	return {
		refresh,
		refreshPath,
		detectLangFromPath,
		finderAction,
		newFolder,
		newFile,
	};
}

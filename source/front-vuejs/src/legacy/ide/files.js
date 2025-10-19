import { notifyAlert } from "../core/alerts.js";

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

	// === WS: list_dirs (cached) ===
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
	async function listDirs(paths = ["/app"], force = false) {
		// Normalize and de-dup
		const list = Array.from(
			new Set(paths.map((p) => (p || "/app").replace(/\/$/, ""))),
		);

		const resultsMap = new Map();

		// Use cache when available
		const toFetch = [];
		if (!force) {
			for (const p of list) {
				const cached = cacheGet(p);
				if (cached) {
					resultsMap.set(p, cached);
				} else {
					toFetch.push(p);
				}
			}
		} else {
			toFetch.push(...list);
		}

		if (toFetch.length) {
			const r = await fsws.call("list_dirs", { path: toFetch.join(",") });
			const responseEntries = r?.entries;

			if (Array.isArray(responseEntries)) {
				// Server returned a single flat array; split per base path with de-dupe by path (latest wins)
				for (const base of toFetch) {
					const basePrefix = `${base.replace(/\/$/, "")}/`;
					const m = new Map();
					for (const item of responseEntries) {
						if (!item?.path) continue;
						if (!item.path.startsWith(basePrefix)) continue;
						m.set(item.path, item);
					}
					const perBase = Array.from(m.values());
					// Merge with any cached entries already present for this base (de-dup by path, fetched wins)
					{
						const existing = Array.isArray(resultsMap.get(base))
							? resultsMap.get(base)
							: [];
						const mm = new Map();
						for (const it of existing) {
							if (!it?.path) continue;
							mm.set(it.path, it);
						}
						for (const it of perBase) {
							if (!it?.path) continue;
							mm.set(it.path, it);
						}
						const merged = Array.from(mm.values());
						cacheSet(base, merged);
						resultsMap.set(base, merged);
					}
				}
			} else if (responseEntries && typeof responseEntries === "object") {
				// Server returned a map: { basePath: entries[] } — de-dupe by path (latest wins)
				for (const base of toFetch) {
					const arr = Array.isArray(responseEntries[base])
						? responseEntries[base]
						: [];
					const m = new Map();
					for (const item of arr) {
						if (!item?.path) continue;
						m.set(item.path, item);
					}
					const perBase = Array.from(m.values());
					// Merge with any cached entries already present for this base (de-dup by path, fetched wins)
					{
						const existing = Array.isArray(resultsMap.get(base))
							? resultsMap.get(base)
							: [];
						const mm = new Map();
						for (const it of existing) {
							if (!it?.path) continue;
							mm.set(it.path, it);
						}
						for (const it of perBase) {
							if (!it?.path) continue;
							mm.set(it.path, it);
						}
						const merged = Array.from(mm.values());
						cacheSet(base, merged);
						resultsMap.set(base, merged);
					}
				}
			} else {
				// Fallback: nothing
				for (const base of toFetch) {
					cacheSet(base, []);
					resultsMap.set(base, []);
				}
			}
		}

		// Ensure all requested paths are present
		for (const p of list) {
			if (!resultsMap.has(p)) {
				const cached = cacheGet(p) || [];
				resultsMap.set(p, cached);
			}
		}
		return resultsMap;
	}

	async function loadDir(path, ul, force = false) {
		// Build the entire subtree in one shot:
		// 1) compute all directories to fetch (base + expanded descendants)
		// 2) fetch list_dirs for all targets in one WS call
		// 3) render DOM synchronously using the pre-fetched map
		const base = path.replace(/\/$/, "");
		const targets = new Set([base]);
		for (const p of expandedPaths) {
			if (p === base || p.startsWith(`${base}/`)) targets.add(p);
		}

		const targetList = Array.from(targets);
		const dirMap = await listDirs(targetList, force);

		function getDirectChildren(parentPath) {
			const items = dirMap.get(parentPath) || [];
			// Deduplicate by full path to avoid duplicate nodes when multi-path results overlap
			const seen = new Set();
			const unique = [];
			for (const it of items) {
				const p = it?.path;
				if (!p) continue;
				if (seen.has(p)) continue;
				seen.add(p);
				unique.push(it);
			}
			const prefix = `${parentPath.replace(/\/$/, "")}/`;
			const direct = unique.filter(
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
		window.pequeroku?.debug &&
			console.log("finder action:", { action, path, type });
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
		finderAction,
		newFolder,
		newFile,
	};
}

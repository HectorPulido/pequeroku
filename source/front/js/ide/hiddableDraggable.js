import { $, $$ } from "../core/dom.js";
export async function setupHiddableDragabble(containerId, callback) {
	const toggleSidebarBtn = $("#toggle-sidebar");
	const toggleSidebarBtn2 = $("#toggle-sidebar-2");
	const toggleConsoleBtn = $("#toggle-console");
	const consoleArea = $("#console-area");
	const consoleHiddable = $$(".console-hiddable");
	const editorModal = $("#editor-modal");
	const sidebarEl = $("#sidebar");
	const splitterV = $("#splitter-v");
	const splitterH = $("#splitter-h");

	const IS_MOBILE = matchMedia("(max-width: 768px)").matches;
	const LS_SIDEBAR_KEY = `ide:${containerId}:sidebar`;
	const LS_CONSOLE_KEY = `ide:${containerId}:console`;

	// Drag and drop files and console
	const LS_CONSOLE_SIZE_KEY = `ide:${containerId}:console:px`;
	const LS_SIDEBAR_SIZE_KEY = `ide:${containerId}:sidebar:px`;

	const savedW = parseInt(
		localStorage.getItem(LS_SIDEBAR_SIZE_KEY) || "280",
		10,
	);
	const savedH = parseInt(
		localStorage.getItem(LS_CONSOLE_SIZE_KEY) || "260",
		10,
	);

	let h = savedH;

	function clamp(n, min, max) {
		return Math.max(min, Math.min(max, n));
	}

	editorModal.style.gridTemplateColumns = `${savedW}px 6px 1fr`;
	consoleArea.style.height = `${savedH}px`;

	// Vertical splitter (files)
	splitterV.addEventListener("mousedown", (e) => {
		e.preventDefault();
		const startX = e.clientX;
		const startW = sidebarEl.getBoundingClientRect().width;
		const onMove = (ev) => {
			const w = Math.max(20, Math.min(600, startW + (ev.clientX - startX)));
			editorModal.style.gridTemplateColumns = `${w}px 6px 1fr`;
		};
		const onUp = () => {
			const w = sidebarEl.getBoundingClientRect().width;
			localStorage.setItem(LS_SIDEBAR_SIZE_KEY, String(w));
			window.removeEventListener("mousemove", onMove);
			window.removeEventListener("mouseup", onUp);
		};
		window.addEventListener("mousemove", onMove);
		window.addEventListener("mouseup", onUp);
	});

	// Horizontal splitter (console)
	splitterH.addEventListener("mousedown", (e) => {
		e.preventDefault();
		const containerRect = editorModal.getBoundingClientRect();
		const containerBottom = containerRect.bottom; // ancla estable
		const resizerHeight = splitterH.getBoundingClientRect().height || 0;

		const onMove = (ev) => {
			const raw = containerBottom - ev.clientY - resizerHeight;
			h = clamp(raw, 90, window.innerHeight);
			consoleArea.style.height = `${h}px`;
			try {
				window?._fitAddon?.fit();
			} catch {}
		};
		const onUp = () => {
			h = consoleArea.getBoundingClientRect().height;
			localStorage.setItem(LS_CONSOLE_SIZE_KEY, String(h));
			window.removeEventListener("mousemove", onMove);
			window.removeEventListener("mouseup", onUp);
		};
		window.addEventListener("mousemove", onMove);
		window.addEventListener("mouseup", onUp);
	});

	// Colapse files
	function applySidebarState(state) {
		editorModal.classList.toggle("sidebar-collapsed", state !== "open");
		editorModal.classList.toggle("sidebar-open", state === "open");
	}
	function applyConsoleState(state) {
		consoleHiddable.forEach((a) => {
			a.classList.toggle("collapsed", state !== "open");
		});
		console.log(state);
		if (state === "open") {
			consoleArea.style.height = `${h}px`;
		} else {
			consoleArea.style.height = "50px";
		}
	}

	function getInitialSidebarState() {
		const saved = localStorage.getItem(LS_SIDEBAR_KEY);
		if (saved) return saved;
		return IS_MOBILE ? "collapsed" : "open";
	}
	function getInitialConsoleState() {
		const saved = localStorage.getItem(LS_CONSOLE_KEY);
		if (saved) return saved;
		return IS_MOBILE ? "collapsed" : "open";
	}

	function toggleSidebar() {
		const _collapsed =
			editorModal.classList.contains("sidebar-open") &&
			!editorModal.classList.contains("sidebar-collapsed");
		const next = _collapsed ? "collapsed" : "open";
		localStorage.setItem(LS_SIDEBAR_KEY, next);
		applySidebarState(next);
	}

	function toggleConsole() {
		const _collapsed = consoleHiddable[0].classList.contains("collapsed");
		const next = _collapsed ? "open" : "collapsed";
		localStorage.setItem(LS_CONSOLE_KEY, next);
		applyConsoleState(next);
		try {
			consoleApi?.fit?.();
		} catch {}
	}

	// ====== INIT ======
	applySidebarState(getInitialSidebarState());
	applyConsoleState(getInitialConsoleState());

	// ====== Listeners ======
	toggleSidebarBtn2.addEventListener("click", toggleSidebar);
	toggleSidebarBtn.addEventListener("click", toggleSidebar);
	toggleConsoleBtn.addEventListener("click", toggleConsole);

	await callback(IS_MOBILE);
}

/**
 * Search UI module for the IDE.
 *
 * Extracted from main.js to keep logic focused and reusable.
 *
 * Responsibilities:
 * - Wire search inputs and buttons
 * - Call backend "search" via fsws
 * - Render results list
 * - Open clicked results in the editor and reveal line
 */

import { notifyAlert } from "../core/alerts.js";
import { $ } from "../core/dom.js";

/**
 * Normalize search result payloads coming from the backend.
 * Accepts:
 * - Array of items
 * - Object with `results` array
 * - Generic object with values being arrays of items
 * Each item should look like:
 *   { path: string, matches|matchs: string[] } where strings are `L{line}: preview`
 * @param {any} res
 * @returns {Array<{path:string, matches?: string[], matchs?: string[]}>}
 */
function normalizeSearchResults(res) {
	if (Array.isArray(res)) return res;
	if (Array.isArray(res?.results)) return res.results;
	if (res && typeof res === "object") {
		try {
			return Object.values(res).flat().filter(Boolean);
		} catch {
			// fallthrough
		}
	}
	return [];
}

/**
 * Render search results into a list element.
 * @param {HTMLElement|null} listEl - container UL element
 * @param {Array<{path:string, matches?: string[], matchs?: string[]}>} items
 */
function renderSearchResults(listEl, items) {
	if (!listEl) return;
	const html = items
		.map((it) => {
			const path = String(it?.path || "");
			const rel = path.startsWith("/app/") ? path.slice(5) : path;
			const rawMatches =
				(Array.isArray(it?.matchs) && it.matchs) ||
				(Array.isArray(it?.matches) && it.matches) ||
				[];
			const inner = rawMatches
				.map((m) => {
					const mm = String(m || "").trim();
					const r = mm.match(/^L(\d+):/);
					const line = r ? Number(r[1]) : 1;
					const preview = mm.replace(/^L\d+:/, "").trim();
					return `<li class="match" data-path="${path}" data-line="${line}">L${line}: ${preview}</li>`;
				})
				.join("");
			return `<li class="file"><strong>${rel}</strong><ul>${inner}</ul></li>`;
		})
		.join("");
	listEl.innerHTML = html || "";
}

/**
 * Setup search UI wiring.
 *
 * @param {Object} opts
 * @param {{ call: (method: string, payload: any) => Promise<any> }} opts.fsws - FS WebSocket client (must support call("search", ...))
 * @param {(path: string) => Promise<void>} opts.openFile - Function to open a file into the editor
 * @param {() => any} opts.getEditor - Function returning the Monaco editor instance (must support revealLineInCenter, setPosition, focus)
 * @param {(path: string) => void} [opts.setPath] - Optional setPath used by openFile if required by the caller implementation
 *
 * @param {Object} [opts.elements] - Optional direct element references or selectors
 * @param {Element|string} [opts.elements.btnToggleSearch] - toggle search button
 * @param {Element|string} [opts.elements.searchBoxEl] - search box container
 * @param {Element|string} [opts.elements.searchPatternInput] - input for the pattern
 * @param {Element|string} [opts.elements.btnSearch] - search button
 * @param {Element|string} [opts.elements.btnSearchClear] - clear results button
 * @param {Element|string} [opts.elements.searchResultsEl] - results list element
 * @param {Element|string} [opts.elements.searchIncludeInput] - include globs input
 * @param {Element|string} [opts.elements.searchExcludeInput] - exclude dirs input
 * @param {Element|string} [opts.elements.searchCaseCheckbox] - case sensitive checkbox
 *
 * @returns {{ search: () => Promise<void>, clear: () => void }}
 */

export function setupSearchUI({ fsws, openFile, getEditor }) {
	const btnToggleSearch = $("#toggle-search");
	const searchBoxEl = $("#search-box");
	const searchPatternInput = $("#search-pattern");
	const btnSearch = $("#btn-search");
	const btnSearchClear = $("#btn-search-clear");
	const searchResultsEl = $("#search-results");
	const searchIncludeInput = $("#search-include");
	const searchExcludeInput = $("#search-exclude");
	const searchCaseCheckbox = $("#search-case");

	// Toggle search box visibility
	if (btnToggleSearch && searchBoxEl) {
		btnToggleSearch.addEventListener("click", () => {
			searchBoxEl.classList.toggle("hidden");
		});
	}

	// Perform a search
	const doSearch = async () => {
		const pattern = (searchPatternInput?.value || "").trim();
		if (!pattern) return;

		const include_globs = (searchIncludeInput?.value || "").trim();
		const exclude_dirs = (searchExcludeInput?.value || "").trim();
		const caseVal =
			!!(/** @type {HTMLInputElement|null} */ (searchCaseCheckbox)?.checked) +
			""; // "true" | "false"

		try {
			const res = await fsws.call("search", {
				root: "/app",
				pattern,
				case: caseVal,
				include_globs,
				exclude_dirs,
			});
			const items = normalizeSearchResults(res);
			renderSearchResults(searchResultsEl, items);
		} catch (err) {
			const msg =
				(err && typeof err === "object" && "message" in err && err.message) ||
				String(err);
			notifyAlert(msg, "error");
		}
	};

	// Bind search button
	if (btnSearch) {
		btnSearch.addEventListener("click", () => {
			void doSearch();
		});
	}

	// Pressing Enter in pattern triggers search
	if (searchPatternInput) {
		searchPatternInput.addEventListener("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				void doSearch();
			}
		});
	}

	// Clear controls and results
	const clear = () => {
		if (searchPatternInput) searchPatternInput.value = "";
		if (searchIncludeInput) searchIncludeInput.value = "";
		if (searchExcludeInput) searchExcludeInput.value = ".git,.venv"; // default filter
		if (searchCaseCheckbox)
			/** @type {HTMLInputElement} */ (searchCaseCheckbox).checked = false;
		if (searchResultsEl) searchResultsEl.innerHTML = "";
	};

	if (btnSearchClear) {
		btnSearchClear.addEventListener("click", clear);
	}

	// Clicking results opens the file, and positions the cursor at the match line
	if (searchResultsEl) {
		searchResultsEl.addEventListener("click", async (e) => {
			// Support clicking individual matches and file rows (open at first match)
			/** @type {HTMLElement|null} */
			const t = /** @type {HTMLElement} */ (e.target);
			if (!t) return;

			let path = null;
			let line = 1;

			const matchEl = t.closest("li.match");
			if (matchEl) {
				path = matchEl.getAttribute("data-path");
				line = parseInt(matchEl.getAttribute("data-line") || "1", 10);
			} else {
				const fileEl = t.closest("li.file");
				if (!fileEl) return;
				const firstMatch = fileEl.querySelector("li.match");
				if (!firstMatch) return;
				path = firstMatch.getAttribute("data-path");
				line = parseInt(firstMatch.getAttribute("data-line") || "1", 10);
			}

			if (!path) return;
			await openFile(path);

			try {
				const ed = getEditor?.();
				if (ed) {
					ed.revealLineInCenter(line);
					ed.setPosition({ lineNumber: line, column: 1 });
					ed.focus();
				}
			} catch {
				// ignore editor positioning errors
			}
		});
	}

	return { search: doSearch, clear };
}

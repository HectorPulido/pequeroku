import { sleep } from "../core/utils.js";
import { detectLangFromPath } from "../shared/langMap.js";

const THEME_LIGHT = "crema";
const THEME_DARK = "monokai";

const __modelsByPath = new Map();

export function loadMonaco(theme) {
	require.config({
		paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" },
	});

	window.monaco = {
		getWorkerUrl: (_workerId, _label) => {
			return `data:text/javascript;charset=utf-8,${encodeURIComponent(`
            self.MonacoEnvironment = { baseUrl: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/' };
            importScripts('https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/base/worker/workerMain.js');
          `)}`;
		},
	};

	require(["vs/editor/editor.main"], () => {
		monaco.editor.defineTheme("monokai", {
			base: "vs-dark",
			inherit: true,
			rules: [
				{ token: "comment", foreground: "75715e", fontStyle: "italic" },
				{ token: "keyword", foreground: "f92672" },
				{ token: "number", foreground: "ae81ff" },
				{ token: "string", foreground: "e6db74" },
			],
			colors: {
				"editor.background": "#2d2d2d",
				"editor.foreground": "#f8f8f2",
			},
		});

		monaco.editor.defineTheme("crema", {
			base: "vs",
			inherit: true,
			rules: [
				{ token: "comment", foreground: "a38b6d", fontStyle: "italic" },
				{ token: "keyword", foreground: "b45a3c", fontStyle: "bold" },
				{ token: "number", foreground: "8c5e58" },
				{ token: "string", foreground: "7c6f57" },
				{ token: "type", foreground: "5b5b8c", fontStyle: "bold" },
				{ token: "function", foreground: "3a5a40" },
			],
			colors: {
				"editor.background": "#fdf6e3",
				"editor.foreground": "#4b3832",
				"editorLineNumber.foreground": "#c8b68c",
				"editorCursor.foreground": "#6d4c41",
				"editor.selectionBackground": "#e6d7b9",
				"editor.lineHighlightBackground": "#f5e9d4",
				"editorIndentGuide.background": "#e0d3b8",
				"editorIndentGuide.activeBackground": "#d2b48c",
			},
		});

		const editor = monaco.editor.create(document.getElementById("editor"), {
			value: "",
			language: "javascript",
			theme: theme ? THEME_DARK : THEME_LIGHT,
			automaticLayout: true,
			fontSize: 14,
			minimap: { enabled: true },
		});

		window._editor = editor;
	});
}

async function waitForMonaco(callback) {
	// oh my god, what have I done...
	const max = 500;
	for (let i = 0; i < max; i++) {
		try {
			callback();
			return;
		} catch (error) {
			window.pequeroku?.debug &&
				console.warn("Error opening File, Try number:", i, error);
		}
		window.pequeroku?.debug && console.log("Waiting for monaco...");
		await sleep(500 * i);
	}
	throw new Error("Monaco not ready");
}

export async function mobileConfig(isMobile) {
	await waitForMonaco(() => {
		if (isMobile) {
			getEditor().updateOptions({
				minimap: { enabled: false },
				wordWrap: "on",
				fontSize: 16,
				lineNumbers: "off",
				glyphMargin: false,
				folding: false,
				lineDecorationsWidth: 14,
				lineNumbersMinChars: 0,
				scrollbar: {
					vertical: "hidden",
					horizontal: "hidden",
				},
			});
		} else {
			getEditor().updateOptions({
				minimap: { enabled: true },
				wordWrap: "off",
				fontSize: 14,
				lineNumbers: "on",
				glyphMargin: true,
				folding: true,
			});
		}
	});
}

export function clearEditor() {
	const model = getEditor().getModel();
	model.setValue("");
}

export function getEditorValue() {
	return getEditor().getValue();
}

export function getEditor() {
	return window._editor;
}

export function changeTheme(isDark, consoleApi) {
	try {
		getEditor()._themeService.setTheme(isDark ? THEME_DARK : THEME_LIGHT);
		consoleApi?.setTheme?.(isDark);
	} catch (error) {
		console.error("Could not change the theme", error);
	}
}

export async function openFile(api, path, setPathLabel) {
	await waitForMonaco(async () => {
		const lang = detectLangFromPath(path);
		const emit = (p, dirty) => {
			try {
				window.dispatchEvent(
					new CustomEvent("editor-dirty-changed", {
						detail: { path: p, dirty },
					}),
				);
			} catch {}
		};

		let model = __modelsByPath.get(path);
		if (model) {
			try {
				monaco.editor.setModelLanguage(model, lang);
			} catch {}
			getEditor().setModel(model);
			// Emit current dirty state when focusing an existing model
			const uriPath = model.uri?.path || path;
			const curDirty =
				(model.getValue?.() ?? "") !==
				(model._prk_lastSaved ?? model.getValue?.());
			model._prk_dirty = !!curDirty;
			emit(uriPath, !!curDirty);
			setPathLabel(path);
			return;
		}

		const { content } = await api(
			`/read_file/?path=${encodeURIComponent(path)}`,
		);
		const uri = monaco.Uri.parse(`file://${path}`);
		model = monaco.editor.createModel(content, lang, uri);

		// Track saved snapshot and dirty state per model
		model._prk_lastSaved = content;
		model._prk_dirty = false;

		// Attach change listener once to update dirty state and notify UI
		if (!model._prk_dispose) {
			const sub = model.onDidChangeContent(() => {
				const nowDirty = model.getValue() !== (model._prk_lastSaved ?? "");
				if (nowDirty !== !!model._prk_dirty) {
					model._prk_dirty = nowDirty;
					emit(model.uri?.path || path, nowDirty);
				}
			});
			model._prk_dispose = () => sub.dispose();
		}

		__modelsByPath.set(path, model);
		getEditor().setModel(model);
		getEditor().setScrollTop(0);
		getEditor().setPosition({ lineNumber: 1, column: 1 });
		emit(model.uri?.path || path, false);
		setPathLabel(path);
	});
}

// Helpers to interact with dirty state from other modules (e.g., tab UI)
export function isPathDirty(path) {
	const model = __modelsByPath.get(path);
	if (!model) return false;
	const saved = model._prk_lastSaved ?? "";
	return (model.getValue?.() ?? "") !== saved;
}

export function getDirtyPaths() {
	const res = [];
	__modelsByPath.forEach((model, p) => {
		const saved = model._prk_lastSaved ?? "";
		if ((model.getValue?.() ?? "") !== saved) res.push(p);
	});
	return res;
}

export function markPathSaved(path) {
	const model = __modelsByPath.get(path) || null;
	if (!model) return;
	model._prk_lastSaved = model.getValue?.() ?? "";
	const uriPath = model.uri?.path || path;
	model._prk_dirty = false;
	try {
		window.dispatchEvent(
			new CustomEvent("editor-dirty-changed", {
				detail: { path: uriPath, dirty: false },
			}),
		);
	} catch {}
}

export function markCurrentSaved() {
	try {
		const m = getEditor()?.getModel?.();
		if (!m) return;
		const p = m.uri?.path || null;
		if (!p) return;
		m._prk_lastSaved = m.getValue?.() ?? "";
		m._prk_dirty = false;
		window.dispatchEvent(
			new CustomEvent("editor-dirty-changed", {
				detail: { path: p, dirty: false },
			}),
		);
	} catch {}
}

export function getActivePath() {
	try {
		const m = getEditor()?.getModel?.();
		return m?.uri?.path || null;
	} catch {
		return null;
	}
}

import { sleep } from "../core/utils.js";
import { detectLangFromPath } from "../shared/langMap.js";

const THEME_LIGHT = "crema";
const THEME_DARK = "monokai";

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
		const model = getEditor().getModel();
		monaco.editor.setModelLanguage(model, lang);
		const { content } = await api(
			`/read_file/?path=${encodeURIComponent(path)}`,
		);
		model.setValue(content);
		setPathLabel(path);
	});
}

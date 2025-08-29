import { sleep } from "../core/dom.js";
import { detectLangFromPath } from "../shared/langMap.js";

export async function waitForMonacoReady(editorEl) {
	const max = 50;
	for (let i = 0; i < max; i++) {
		if (window.monaco && editorEl && editorEl.editor) return;
		await sleep(100);
	}
	throw new Error("Monaco not ready");
}

export async function openFile(api, editorEl, path, setPathLabel) {
	await waitForMonacoReady(editorEl);
	const lang = detectLangFromPath(path);
	monaco.editor.setModelLanguage(editorEl.editor.getModel(), lang);
	const { content } = await api(`/read_file/?path=${encodeURIComponent(path)}`);
	editorEl.value = content;
	setPathLabel(path);
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) =>
	Array.from(root.querySelectorAll(sel));
export const on = (el, ev, fn) => el.addEventListener(ev, fn);
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export function escapeHtml(s) {
	const d = document.createElement("div");
	d.innerText = String(s ?? "");
	return d.innerHTML;
}

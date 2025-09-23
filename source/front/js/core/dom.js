export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) =>
	Array.from(root.querySelectorAll(sel));
export const on = (el, ev, fn) => el.addEventListener(ev, fn);
export { sleep } from "./utils.js";
export function escapeHtml(s) {
	const d = document.createElement("div");
	d.innerText = String(s ?? "");
	return d.innerHTML;
}

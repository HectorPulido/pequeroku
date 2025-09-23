/**
 * Reusable modal controller utility
 *
 * Goal:
 * - Normalize open/close behaviors across multiple modals
 * - Standardize title handling
 * - Support close on ESC / click on backdrop
 * - Trap focus within the modal while open
 * - Prevent body scroll while any modal is open
 *
 * Usage:
 *   import { createModalController } from "../core/modals.js";
 *
 *   const ctrl = createModalController({
 *     modal: document.getElementById("upload-modal"),
 *     titleEl: document.querySelector("#upload-modal .upload-header > span"),
 *     defaultTitle: "Upload file",
 *     openTriggers: [document.getElementById("btn-open-upload-modal")],
 *     closeTriggers: [document.getElementById("btn-upload-close")],
 *     closeOnBackdrop: true,
 *     closeOnEsc: true,
 *     trapFocus: true,
 *     initialFocus: () => document.getElementById("file-input"),
 *     onOpen: () => console.log("opened"),
 *     onClose: () => console.log("closed"),
 *   });
 *
 *   // Programmatic control:
 *   ctrl.open({ title: "Custom Title" });
 *   ctrl.setTitle("Another Title");
 *   ctrl.close();
 */

const FOCUSABLE_SELECTOR =
	'a[href], area[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), iframe, audio[controls], video[controls], [contenteditable], [tabindex]:not([tabindex="-1"])';

let openCount = 0;
let originalBodyOverflow = null;

/**
 * Prevent background scroll while any modal is open
 */
function lockBodyScroll() {
	if (openCount === 1) {
		originalBodyOverflow = document.body.style.overflow;
		document.body.style.overflow = "hidden";
	}
}
function unlockBodyScroll() {
	if (openCount === 0 && originalBodyOverflow !== null) {
		document.body.style.overflow = originalBodyOverflow;
		originalBodyOverflow = null;
	}
}

/**
 * Get focusable elements inside container
 * @param {HTMLElement} container
 * @returns {HTMLElement[]}
 */
function getFocusable(container) {
	if (!container) return [];
	return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
		(el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
	);
}

/**
 * Ensure modal has basic ARIA roles/props
 * @param {HTMLElement} modal
 * @param {HTMLElement|null} titleEl
 */
function ensureAria(modal, titleEl) {
	if (!modal) return;
	if (!modal.getAttribute("role")) modal.setAttribute("role", "dialog");
	modal.setAttribute("aria-modal", "true");
	if (titleEl) {
		if (!titleEl.id) {
			titleEl.id = `modal-title-${Math.random().toString(36).slice(2, 8)}`;
		}
		modal.setAttribute("aria-labelledby", titleEl.id);
	}
}

/**
 * Small helper to add and remove event listeners
 */
function on(el, ev, fn, opts) {
	el?.addEventListener?.(ev, fn, opts);
	return () => el?.removeEventListener?.(ev, fn, opts);
}

/**
 * Create a modal controller for a given modal element
 * @param {Object} opts
 * @param {HTMLElement} opts.modal - The modal root element (the backdrop container)
 * @param {HTMLElement|null} [opts.titleEl] - Element where the title text should be set
 * @param {string} [opts.defaultTitle] - Title to apply the first time (or when not provided in open())
 * @param {HTMLElement[]} [opts.openTriggers] - Elements that will open the modal on click
 * @param {HTMLElement[]} [opts.closeTriggers] - Elements that will close the modal on click
 * @param {boolean} [opts.closeOnBackdrop=true] - Close if user clicks on the backdrop (outside content)
 * @param {boolean} [opts.closeOnEsc=true] - Close on ESC key
 * @param {boolean} [opts.trapFocus=true] - Keep focus within modal while open
 * @param {() => HTMLElement|null} [opts.initialFocus] - Element to focus on open (or first focusable)
 * @param {() => void} [opts.onOpen] - Callback after modal opens
 * @param {() => void} [opts.onClose] - Callback after modal closes
 */
export function createModalController({
	modal,
	titleEl = null,
	defaultTitle = "",
	openTriggers = [],
	closeTriggers = [],
	closeOnBackdrop = true,
	closeOnEsc = true,
	trapFocus = true,
	initialFocus = null,
	onOpen,
	onClose,
} = {}) {
	if (!modal || !(modal instanceof HTMLElement)) {
		throw new Error("createModalController requires a valid `modal` HTMLElement");
	}

	ensureAria(modal, titleEl);

	let isOpen = !modal.classList.contains("hidden") && modal.offsetParent !== null;
	let previouslyFocused = null;

	// Internal handlers to remove on destroy
	const removers = [];

	// Handle open triggers
	openTriggers.forEach((btn) => {
		removers.push(
			on(btn, "click", (e) => {
				e.preventDefault();
				open();
			}),
		);
	});

	// Handle close triggers
	closeTriggers.forEach((btn) => {
		removers.push(
			on(btn, "click", (e) => {
				e.preventDefault();
				close();
			}),
		);
	});

	// Backdrop click
	if (closeOnBackdrop) {
		removers.push(
			on(modal, "click", (e) => {
				// Only when clicking the backdrop itself (not a child)
				if (e.target === modal) {
					close();
				}
			}),
		);
	}

	// Keydown handling: ESC to close, TAB to trap focus
	const keydownHandler = (e) => {
		if (!isOpen) return;
		if (closeOnEsc && e.key === "Escape") {
			e.preventDefault();
			close();
			return;
		}
		if (trapFocus && e.key === "Tab") {
			const focusables = getFocusable(modal);
			if (!focusables.length) {
				e.preventDefault();
				return;
			}
			const first = focusables[0];
			const last = focusables[focusables.length - 1];
			const current = document.activeElement;

			if (e.shiftKey) {
				// backwards
				if (current === first || !modal.contains(current)) {
					e.preventDefault();
					last.focus();
				}
			} else {
				// forwards
				if (current === last || !modal.contains(current)) {
					e.preventDefault();
					first.focus();
				}
			}
		}
	};
	removers.push(on(document, "keydown", keydownHandler));

	function setTitle(text) {
		const t = text ?? defaultTitle ?? "";
		if (titleEl) titleEl.textContent = String(t);
	}

	function focusInitial() {
		let target = null;
		try {
			target = initialFocus?.();
		} catch {}
		if (!(target instanceof HTMLElement)) {
			const focusables = getFocusable(modal);
			target = focusables[0] || null;
		}
		// Focus without scrolling the page
		try {
			target?.focus?.({ preventScroll: true });
		} catch {
			try {
				target?.focus?.();
			} catch {}
		}
	}

	function open(params = {}) {
		if (isOpen) return;
		previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;

		if (params.title != null) setTitle(params.title);
		else setTitle(defaultTitle);

		modal.classList.remove("hidden");
		modal.setAttribute("aria-hidden", "false");

		isOpen = true;
		openCount++;
		lockBodyScroll();

		// Defer focus to after render
		setTimeout(() => focusInitial(), 0);

		try {
			onOpen?.();
		} catch {}
	}

	function close() {
		if (!isOpen) return;
		modal.classList.add("hidden");
		modal.setAttribute("aria-hidden", "true");

		isOpen = false;
		openCount = Math.max(0, openCount - 1);
		unlockBodyScroll();

		// Restore focus to previously focused element
		if (previouslyFocused && document.contains(previouslyFocused)) {
			try {
				previouslyFocused.focus();
			} catch {}
		}

		try {
			onClose?.();
		} catch {}
	}

	function destroy() {
		while (removers.length) {
			try {
				const off = removers.pop();
				off?.();
			} catch {}
		}
		// Ensure closed
		if (isOpen) close();
	}

	// Initialize visibility/ARIA
	if (isOpen) {
		// If the modal is initially open in DOM, honor that state
		open();
	} else {
		modal.classList.add("hidden");
		modal.setAttribute("aria-hidden", "true");
		setTitle(defaultTitle);
	}

	return {
		open,
		close,
		setTitle,
		isOpen: () => isOpen,
		destroy,
	};
}

/**
 * Convenience to wire a modal with simple single open/close buttons.
 * @param {HTMLElement} modal
 * @param {HTMLElement|null} openBtn
 * @param {HTMLElement|null} closeBtn
 * @param {Object} options - Remaining options forwarded to createModalController
 */
export function bindModal(modal, openBtn, closeBtn, options = {}) {
	return createModalController({
		modal,
		openTriggers: openBtn ? [openBtn] : [],
		closeTriggers: closeBtn ? [closeBtn] : [],
		...options,
	});
}

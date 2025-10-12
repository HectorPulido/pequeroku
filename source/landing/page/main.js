// ============ Theme Toggle (Light/Dark) ============
const themeToggle = document.getElementById("themeToggle");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");

function setTheme(mode) {
	if (mode === "dark") {
		document.documentElement.setAttribute("data-theme", "dark");
	} else {
		document.documentElement.setAttribute("data-theme", "light");
	}
	localStorage.setItem("theme", mode);
}

// Initialize
(() => {
	const saved = localStorage.getItem("theme");
	if (saved) {
		setTheme(saved);
	} else {
		setTheme(prefersDark.matches ? "dark" : "light");
	}
	document.getElementById("year").textContent = new Date().getFullYear();
})();

themeToggle.addEventListener("click", () => {
	const current = document.documentElement.getAttribute("data-theme");
	setTheme(current === "dark" ? "light" : "dark");
});

// ============ Tabs (Docs component) ============
document.querySelectorAll("[data-tabs]").forEach((tabs) => {
	const tabButtons = tabs.querySelectorAll('[role="tab"]');
	const panels = tabs.querySelectorAll(".tabpanel");
	tabButtons.forEach((btn) => {
		btn.addEventListener("click", () => {
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			tabButtons.forEach((b) => b.setAttribute("aria-selected", "false"));
			// biome-ignore lint/suspicious/useIterableCallbackReturn: This is correct
			panels.forEach((p) => p.classList.remove("active"));
			btn.setAttribute("aria-selected", "true");
			const panel = tabs.querySelector(`#${btn.getAttribute("aria-controls")}`);
			panel.classList.add("active");
		});
	});
});

// ============ Copy-to-clipboard for code blocks ============
document.querySelectorAll("[data-copy]").forEach((btn) => {
	btn.addEventListener("click", () => {
		const code = btn.parentElement.innerText.replace(/^\s*Copy\s*/, "");
		navigator.clipboard.writeText(code).then(() => {
			const original = btn.textContent;
			btn.textContent = "Copied!";
			setTimeout(() => {
				btn.textContent = original;
			}, 1200);
		});
	});
});

// ============ Smooth Scroll for in-page anchors ============
document.querySelectorAll('a[href^="#"]').forEach((a) => {
	a.addEventListener("click", (e) => {
		const id = a.getAttribute("href").slice(1);
		const el = document.getElementById(id);
		if (el) {
			e.preventDefault();
			el.scrollIntoView({ behavior: "smooth", block: "start" });
		}
	});
});

// ============ MENU ============
(() => {
	var btn = document.getElementById("navMenuToggle");
	var nav = document.getElementById("primaryNav");
	if (!btn || !nav) return;
	function toggle(open) {
		var isOpen =
			open !== undefined ? open : btn.getAttribute("aria-expanded") !== "true";
		btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
		document.body.classList.toggle("nav-open", isOpen);
	}
	btn.addEventListener("click", () => {
		toggle();
	});
	// Close on link click
	nav.addEventListener("click", (e) => {
		if (e.target.tagName === "A") toggle(false);
	});
	// Close on Escape
	document.addEventListener("keydown", (e) => {
		if (e.key === "Escape") toggle(false);
	});
	// Close when resizing above breakpoint
	var mql = window.matchMedia("(min-width: 701px)");
	mql.addEventListener("change", (ev) => {
		if (ev.matches) toggle(false);
	});
})();

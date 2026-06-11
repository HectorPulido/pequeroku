// ============ Theme Toggle (Light/Dark) ============
const themeToggle = document.getElementById("themeToggle");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
const prefersReducedMotion = window.matchMedia(
	"(prefers-reduced-motion: reduce)",
);
// ?motion=off disables typing/reveal animations (previews, screenshots, tests)
const motionOff =
	prefersReducedMotion.matches ||
	new URLSearchParams(location.search).get("motion") === "off";
if (motionOff) document.documentElement.classList.add("no-anim");

function setTheme(mode) {
	document.documentElement.setAttribute(
		"data-theme",
		mode === "dark" ? "dark" : "light",
	);
	localStorage.setItem("theme", mode);
}

(() => {
	// ?theme=dark|light overrides (handy for previews); else saved, else system.
	const urlTheme = new URLSearchParams(location.search).get("theme");
	const saved = localStorage.getItem("theme");
	if (urlTheme === "dark" || urlTheme === "light") {
		document.documentElement.setAttribute("data-theme", urlTheme);
	} else if (saved) {
		setTheme(saved);
	} else {
		setTheme(prefersDark.matches ? "dark" : "light");
	}
	const year = document.getElementById("year");
	if (year) year.textContent = new Date().getFullYear();
})();

if (themeToggle) {
	themeToggle.addEventListener("click", () => {
		const current = document.documentElement.getAttribute("data-theme");
		setTheme(current === "dark" ? "light" : "dark");
	});
}

// ============ Tabs ============
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

// ============ Copy-to-clipboard ============
// Priority: data-copy attribute → data-copy-target selector → parent text.
document.querySelectorAll("[data-copy], [data-copy-target]").forEach((btn) => {
	btn.addEventListener("click", () => {
		let text = btn.getAttribute("data-copy");
		if (!text) {
			const sel = btn.getAttribute("data-copy-target");
			const el = sel ? document.querySelector(sel) : null;
			text = el
				? el.innerText
				: btn.parentElement.innerText.replace(/^\s*Copy\s*/i, "");
		}
		navigator.clipboard.writeText(text).then(() => {
			const original = btn.textContent;
			btn.textContent = "copied ✓";
			setTimeout(() => {
				btn.textContent = original;
			}, 1200);
		});
	});
});

// ============ Smooth scroll for in-page anchors ============
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

// ============ Responsive menu ============
(() => {
	const btn = document.getElementById("navMenuToggle");
	const nav = document.getElementById("primaryNav");
	if (!btn || !nav) return;
	function toggle(open) {
		const isOpen =
			open !== undefined ? open : btn.getAttribute("aria-expanded") !== "true";
		btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
		document.body.classList.toggle("nav-open", isOpen);
	}
	btn.addEventListener("click", () => {
		toggle();
	});
	nav.addEventListener("click", (e) => {
		if (e.target.tagName === "A") toggle(false);
	});
	document.addEventListener("keydown", (e) => {
		if (e.key === "Escape") toggle(false);
	});
	const mql = window.matchMedia("(min-width: 701px)");
	mql.addEventListener("change", (ev) => {
		if (ev.matches) toggle(false);
	});
})();

// ============ Hero terminal typing ============
// Full text lives in the HTML (works without JS / with reduced motion);
// with motion allowed, we retype it character by character.
(() => {
	const term = document.getElementById("heroTerm");
	if (!term || motionOff) return;

	const lines = Array.from(term.querySelectorAll(".t-line"));
	const caret = term.querySelector(".t-caret");
	const contents = lines.map((line, i) => {
		const textEl = line.querySelector(".t-text");
		const text = textEl ? textEl.textContent : "";
		if (textEl) textEl.textContent = "";
		if (i > 0) line.style.visibility = "hidden";
		return { textEl, text };
	});

	function typeLine(i) {
		if (i >= contents.length) return;
		const { textEl, text } = contents[i];
		lines[i].style.visibility = "visible";
		if (!textEl) {
			typeLine(i + 1);
			return;
		}
		if (caret) lines[i].appendChild(caret);
		let pos = 0;
		const tick = () => {
			textEl.textContent = text.slice(0, ++pos);
			if (pos < text.length) {
				setTimeout(tick, 14);
			} else {
				setTimeout(() => typeLine(i + 1), 320);
			}
		};
		setTimeout(tick, i === 0 ? 500 : 0);
	}
	typeLine(0);
})();

// ============ GitHub stars ============
(() => {
	const el = document.getElementById("ghStars");
	if (!el) return;
	fetch("https://api.github.com/repos/HectorPulido/pequeroku")
		.then((r) => (r.ok ? r.json() : null))
		.then((data) => {
			if (!data || data.stargazers_count == null) return;
			const n = data.stargazers_count;
			el.textContent = `${n >= 1000 ? `${(n / 1000).toFixed(1)}k` : n} stars`;
		})
		.catch(() => {});
})();

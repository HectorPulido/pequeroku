/**
 * End-to-end layout guard for the IDE console/editor split, run against the
 * in-memory mocks (no backend needed). Reproduces the "growing the console hides
 * Monaco" bug: it drags the console resize handle far up on a short viewport and
 * asserts the editor (Monaco) stays visible.
 *
 * Usage:  pnpm test:e2e         (spawns `vite --mode mock`, runs, tears down)
 * Browser: set E2E_BROWSER to a Chromium-based executable, else auto-detected.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 5209;
const BASE = `http://localhost:${PORT}`;

const BROWSER =
	process.env.E2E_BROWSER ||
	[
		"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
		"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
		"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
		"/Applications/Chromium.app/Contents/MacOS/Chromium",
	].find((p) => existsSync(p));

const waitForPort = (port, timeoutMs = 20000) =>
	new Promise((res, rej) => {
		const deadline = Date.now() + timeoutMs;
		const tick = () => {
			const s = net.connect(port, "localhost");
			s.once("connect", () => {
				s.destroy();
				res();
			});
			s.once("error", () => {
				s.destroy();
				if (Date.now() > deadline) rej(new Error(`port ${port} never opened`));
				else setTimeout(tick, 300);
			});
		};
		tick();
	});

const measure = () => {
	const handle = document.querySelector('button[aria-label="Resize console"]');
	const panel = handle?.parentElement ?? null;
	const column = panel?.parentElement ?? null;
	const editorArea = document.querySelector("div.min-h-0");
	const monaco = document.querySelector(".monaco-editor");
	const h = (el) => (el ? Math.round(el.getBoundingClientRect().height) : null);
	return { col: h(column), editor: h(editorArea), monaco: h(monaco), panel: h(panel) };
};

const dragUp = async (page, px) => {
	const box = await page.locator('button[aria-label="Resize console"]').boundingBox();
	const x = box.x + box.width / 2;
	const y = box.y + box.height / 2;
	await page.mouse.move(x, y);
	await page.mouse.down();
	await page.mouse.move(x, y - px, { steps: 24 });
	await page.mouse.up();
	await page.waitForTimeout(300);
};

const main = async () => {
	if (!BROWSER) {
		throw new Error(
			"No Chromium-based browser found. Set E2E_BROWSER=/path/to/chrome (or install one).",
		);
	}
	const vite = spawn("pnpm", ["vite", "--mode", "mock", "--port", String(PORT), "--strictPort"], {
		cwd: ROOT,
		stdio: "ignore",
	});
	const cleanup = () => {
		try {
			vite.kill("SIGKILL");
		} catch {}
	};

	try {
		await waitForPort(PORT);
		const browser = await chromium.launch({ executablePath: BROWSER, headless: true });
		const page = await browser.newPage({ viewport: { width: 1400, height: 480 } });
		await page.goto(`${BASE}/ide?containerId=1`, { waitUntil: "domcontentloaded" });
		await page.waitForSelector('button[aria-label="Resize console"]', { timeout: 15000 });
		await page.waitForTimeout(1200);

		// Grow the console far past the viewport; the CSS/JS cap must keep the editor.
		await dragUp(page, 600);
		const m = await page.evaluate(measure);
		await browser.close();

		const failures = [];
		if (!m.monaco || m.monaco < 100) failures.push(`Monaco too short: ${m.monaco}px (want >=100)`);
		if (!m.editor || m.editor < 180) failures.push(`Editor area too short: ${m.editor}px (>=180)`);
		if (m.panel && m.col && m.panel > m.col - 180) {
			failures.push(`Console covers editor: panel ${m.panel}px of col ${m.col}px`);
		}

		if (failures.length) {
			console.error("FAIL console-resize:", JSON.stringify(m));
			for (const f of failures) console.error("  -", f);
			process.exitCode = 1;
		} else {
			console.log("PASS console-resize: editor stays visible when console grows:", JSON.stringify(m));
		}
	} finally {
		cleanup();
	}
};

main().catch((e) => {
	console.error("ERROR", e);
	process.exit(1);
});

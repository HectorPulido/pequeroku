import { chromium } from "playwright";

const BRAVE = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const ORIGIN = "http://localhost";

const measure = () => {
	const r = (el) => {
		if (!el) return null;
		const b = el.getBoundingClientRect();
		return { top: Math.round(b.top), bottom: Math.round(b.bottom), h: Math.round(b.height) };
	};
	const editorArea = document.querySelector("div.min-h-0");
	const monacoWrap = document.querySelector(".monaco-editor")?.parentElement ?? null;
	const monaco = document.querySelector(".monaco-editor");
	// editor-area children in order
	const kids = editorArea
		? Array.from(editorArea.children).map((c) => ({
				cls: (c.className || "").toString().slice(0, 34),
				...r(c),
			}))
		: [];
	// find a status-bar-ish node (contains "Ln")
	const statusBar = Array.from(document.querySelectorAll("div")).find((d) =>
		/Ln \d+, Col/.test(d.textContent || ""),
	);
	return {
		innerH: window.innerHeight,
		editorArea: r(editorArea),
		editorChildren: kids,
		monacoWrap: r(monacoWrap),
		monaco: r(monaco),
		monacoOverflows: monaco && editorArea ? r(monaco).bottom > r(editorArea).bottom + 1 : null,
		statusBarVisible: !!statusBar,
		statusBar: r(statusBar),
	};
};

const run = async () => {
	const browser = await chromium.launch({ executablePath: BRAVE, headless: true });
	const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
	await page.goto(`${ORIGIN}/dashboard/login`, { waitUntil: "domcontentloaded" });
	await page.waitForTimeout(800);
	await page.fill('input[name="username"]', "layouttest").catch(() => {});
	await page.fill('input[type="password"]', "layouttest123").catch(() => {});
	await page.click('button[type="submit"]').catch(() => {});
	await page.waitForTimeout(2500);

	await page.goto(`${ORIGIN}/dashboard/ide?containerId=1`, { waitUntil: "domcontentloaded" });
	await page.waitForSelector('button[aria-label="Resize console"]', { timeout: 15000 });
	await page.waitForTimeout(1500);
	console.log("BEFORE:", JSON.stringify(await page.evaluate(measure)));
	await page.screenshot({ path: "_real_before.png" });

	// Drag the console handle ALL the way up (to y=90, near the top of the viewport).
	const box = await page.locator('button[aria-label="Resize console"]').boundingBox();
	const x = box.x + box.width / 2;
	const y = box.y + box.height / 2;
	await page.mouse.move(x, y);
	await page.mouse.down();
	// several steps up to the very top
	for (const ty of [y - 200, y - 500, 200, 90]) {
		await page.mouse.move(x, ty, { steps: 10 });
	}
	await page.mouse.up();
	await page.waitForTimeout(500);
	console.log("AFTER max-up:", JSON.stringify(await page.evaluate(measure)));
	await page.screenshot({ path: "_real_after.png" });
	await browser.close();
};

run().catch((e) => {
	console.error("FATAL", e);
	process.exit(1);
});

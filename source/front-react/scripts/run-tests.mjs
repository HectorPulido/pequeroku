#!/usr/bin/env node
import { spawn } from "node:child_process";

const pattern = process.argv[2] ?? "build-tests/tests/**/*.js";

async function ensureNodeTest() {
	try {
		await import("node:test");
	} catch (error) {
		if (error && typeof error === "object" && "code" in error && error.code === "ERR_MODULE_NOT_FOUND") {
			console.error(
				"Node.js built-in test runner is unavailable. Please use Node.js 18.0.0 or newer (e.g. `nvm use 22`).",
			);
			process.exit(1);
		}
		throw error;
	}
}

async function main() {
	process.env.VITE_USE_MOCKS = "true";

	await ensureNodeTest();

	const loaderUrl = new URL("../tests/alias-loader.mjs", import.meta.url);
	const setupUrl = new URL("../tests/test-setup.mjs", import.meta.url);

	const child = spawn(
		process.execPath,
		["--loader", loaderUrl.href, "--import", setupUrl.href, "--test", pattern],
		{
			env: process.env,
			stdio: "inherit",
		},
	);

	child.on("exit", (code, signal) => {
		if (signal) {
			process.kill(process.pid, signal);
			return;
		}
		process.exit(code ?? 1);
	});
}

main().catch((error) => {
	console.error(error);
	process.exit(1);
});

type EnvRecord = Record<string, string | undefined>;

const readEnv = (): string | undefined => {
	// `import.meta.env` MUST be referenced as this literal member expression: Vite
	// only statically injects env values when it sees `import.meta.env` verbatim.
	// Aliasing it first (`const m = import.meta; m.env`) defeats that replacement,
	// so `env` is undefined in the browser and mocks silently never turn on. In the
	// Node test runner `import.meta.env` is undefined, so we fall back to process.env.
	const viteFlag = import.meta.env?.VITE_USE_MOCKS;
	if (typeof viteFlag === "string") {
		return viteFlag;
	}
	const maybeProcess = (globalThis as { process?: { env?: EnvRecord } }).process;
	return maybeProcess?.env?.VITE_USE_MOCKS;
};

export const USE_MOCKS = (readEnv() ?? "").toString().toLowerCase() === "true";

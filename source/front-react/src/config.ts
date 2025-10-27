type EnvRecord = Record<string, string | undefined>;

const readEnv = (): string | undefined => {
	if (typeof import.meta !== "undefined") {
		const meta = import.meta as { env?: EnvRecord };
		if (typeof meta.env === "object") {
			return meta.env?.VITE_USE_MOCKS;
		}
	}
	const maybeProcess = (globalThis as { process?: { env?: EnvRecord } }).process;
	return maybeProcess?.env?.VITE_USE_MOCKS;
};

export const USE_MOCKS = (readEnv() ?? "").toString().toLowerCase() === "true";

export function signatureFrom(value: unknown): string {
	try {
		return JSON.stringify(value);
	} catch {
		return `${Date.now()}`;
	}
}

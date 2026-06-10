import { makeApi } from "@/services/api";
import type { ApiKey, ApiScope, McpInfo } from "@/types/apiKey";

const api = makeApi("/api");

export function listApiKeys() {
	return api<ApiKey[]>("/account/api-keys/", {
		method: "GET",
		noLoader: true,
		noAuthRedirect: true,
		noAuthAlert: true,
	});
}

export function createApiKey(name: string, scopes: ApiScope[]) {
	return api<ApiKey>("/account/api-keys/", {
		method: "POST",
		body: JSON.stringify({ name, scopes }),
	});
}

export function revokeApiKey(id: number) {
	return api(`/account/api-keys/${id}/`, { method: "DELETE" });
}

export function fetchMcpInfo() {
	return api<McpInfo>("/account/api-keys/mcp-info/", {
		method: "GET",
		noLoader: true,
		noAuthRedirect: true,
		noAuthAlert: true,
	});
}

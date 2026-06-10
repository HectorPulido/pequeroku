export interface ApiKey {
	id: number;
	name: string;
	prefix: string;
	scopes: string[];
	last_used_at: string | null;
	revoked: boolean;
	created_at: string;
	/** Full secret, present ONLY in the response right after creation. */
	token?: string;
}

export interface McpInfo {
	mcp_url: string;
	api_base: string;
	swagger_url: string;
}

export type ApiScope = "read" | "exec" | "admin";

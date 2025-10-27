import { USE_MOCKS } from "@/config";
import { mockFetchCurrentUser } from "@/mocks/dashboard";
import { makeApi } from "@/services/api";
import type { UserInfo } from "@/types/user";

const api = USE_MOCKS ? null : makeApi("/api");

function isUserInfo(payload: unknown): payload is UserInfo {
	if (!payload || typeof payload !== "object") return false;
	const value = payload as Partial<UserInfo>;
	return (
		typeof value.username === "string" &&
		typeof value.is_superuser === "boolean" &&
		typeof value.active_containers === "number" &&
		typeof value.has_quota === "boolean" &&
		typeof value.quota === "object"
	);
}

export async function fetchCurrentUser(): Promise<UserInfo> {
	if (USE_MOCKS) {
		return mockFetchCurrentUser();
	}

	if (!api) {
		throw new Error("API client unavailable");
	}

	const data = await api<UserInfo | { raw?: string }>("/user/me/", {
		method: "GET",
		noLoader: true,
		noAuthRedirect: true,
		noAuthAlert: true,
	});

	if (!isUserInfo(data)) {
		const error = new Error("Unauthorized");
		(error as Error & { status?: number }).status = 401;
		throw error;
	}

	return data;
}

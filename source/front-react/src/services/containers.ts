import { USE_MOCKS } from "@/config";
import {
	mockCreateContainer,
	mockDeleteContainer,
	mockDuplicateContainer,
	mockFetchContainerTypes,
	mockListContainers,
	mockPowerOffContainer,
	mockPowerOnContainer,
	mockRenameContainer,
	mockUpdateAllowedUsers,
} from "@/mocks/dashboard";
import { makeApi } from "@/services/api";
import type { AllowedUsersResult, Container, ContainerType } from "@/types/container";

const api = USE_MOCKS ? null : makeApi("/api");

type CommonOptions = {
	signal?: AbortSignal;
};

export async function listContainers(options: CommonOptions & { suppressLoader?: boolean } = {}) {
	if (USE_MOCKS) {
		return mockListContainers();
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	const { signal, suppressLoader = true } = options;
	return api<Container[]>("/containers/", {
		method: "GET",
		signal,
		noLoader: suppressLoader,
		noAuthRedirect: true,
		noAuthAlert: true,
	});
}

export async function fetchContainerTypes(options: CommonOptions = {}) {
	if (USE_MOCKS) {
		return mockFetchContainerTypes();
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	const { signal } = options;
	return api<ContainerType[]>("/container-types/", {
		method: "GET",
		signal,
		noLoader: true,
		noAuthRedirect: true,
		noAuthAlert: true,
	});
}

export async function createContainer(payload: {
	container_type: number;
	container_name?: string;
}) {
	if (USE_MOCKS) {
		await mockCreateContainer(payload);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api("/containers/", {
		method: "POST",
		body: JSON.stringify(payload),
	});
}

export async function deleteContainer(containerId: number) {
	if (USE_MOCKS) {
		await mockDeleteContainer(containerId);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api(`/containers/${containerId}/`, {
		method: "DELETE",
	});
}

export async function powerOnContainer(containerId: number) {
	if (USE_MOCKS) {
		await mockPowerOnContainer(containerId);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api(`/containers/${containerId}/power_on/`, {
		method: "POST",
	});
}

export async function powerOffContainer(
	containerId: number,
	{ force = false }: { force?: boolean } = {},
) {
	if (USE_MOCKS) {
		await mockPowerOffContainer(containerId);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api(`/containers/${containerId}/power_off/`, {
		method: "POST",
		body: JSON.stringify({ force }),
	});
}

export async function renameContainer(containerId: number, name: string) {
	if (USE_MOCKS) {
		await mockRenameContainer(containerId, name);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api(`/containers/${containerId}/rename/`, {
		method: "PATCH",
		body: JSON.stringify({ name }),
	});
}

export async function duplicateContainer(containerId: number) {
	if (USE_MOCKS) {
		await mockDuplicateContainer(containerId);
		return;
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api(`/containers/${containerId}/duplicate/`, {
		method: "POST",
	});
}

export async function updateAllowedUsers(containerId: number, usernames: string[]) {
	if (USE_MOCKS) {
		return mockUpdateAllowedUsers(containerId, usernames);
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	return api<AllowedUsersResult>(`/containers/${containerId}/allowed_users/`, {
		method: "PUT",
		body: JSON.stringify({ usernames }),
	});
}

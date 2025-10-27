import { USE_MOCKS } from "@/config";
import {
	mockCreateContainer,
	mockDeleteContainer,
	mockFetchContainerStatistics,
	mockFetchContainerTypes,
	mockListContainers,
	mockPowerOffContainer,
	mockPowerOnContainer,
} from "@/mocks/dashboard";
import { makeApi } from "@/services/api";
import type { Container, ContainerType } from "@/types/container";
import type { MetricData } from "@/types/metrics";

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

type FetchStatsOptions = CommonOptions & { suppressLoader?: boolean };

export async function fetchContainerStatistics(
	containerId: number,
	options: FetchStatsOptions = {},
): Promise<MetricData> {
	if (USE_MOCKS) {
		return mockFetchContainerStatistics(containerId);
	}
	if (!api) {
		throw new Error("API client unavailable");
	}
	const { signal, suppressLoader = true } = options;
	const data = await api<{
		cpu_percent?: number;
		rss_mib?: number;
		rss_bytes?: number;
		num_threads?: number;
		ts?: number;
	}>(`/containers/${containerId}/statistics/`, {
		method: "GET",
		signal,
		noLoader: suppressLoader,
		noAuthRedirect: true,
		noAuthAlert: true,
	});

	const cpu = Number.isFinite(data?.cpu_percent) ? Number(data?.cpu_percent) : 0;
	const memoryMiB =
		typeof data?.rss_mib === "number"
			? data.rss_mib
			: typeof data?.rss_bytes === "number"
				? data.rss_bytes / (1024 * 1024)
				: 0;
	const threads = Number.isFinite(data?.num_threads) ? Number(data?.num_threads) : 0;
	const timestamp =
		typeof data?.ts === "number"
			? new Date(data.ts * 1000).toISOString()
			: new Date().toISOString();

	return {
		cpu,
		memory: memoryMiB,
		threads,
		timestamp,
	};
}

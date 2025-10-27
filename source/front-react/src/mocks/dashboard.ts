import type { Container, ContainerType } from "@/types/container";
import type { MetricData } from "@/types/metrics";
import type { UserInfo } from "@/types/user";

const INITIAL_CREDITS = 5;

const mockContainerTypes: ContainerType[] = [
	{
		id: 1,
		container_type_name: "starter",
		memory_mb: 512,
		vcpus: 1,
		disk_gib: 5,
		credits_cost: 1,
	},
	{
		id: 2,
		container_type_name: "standard",
		memory_mb: 1024,
		vcpus: 2,
		disk_gib: 10,
		credits_cost: 2,
	},
	{
		id: 3,
		container_type_name: "pro",
		memory_mb: 2048,
		vcpus: 4,
		disk_gib: 20,
		credits_cost: 3,
	},
];

let creditsUsed = 1;
let nextContainerId = 4;

let mockContainers: Container[] = [
	{
		id: 1,
		name: "dev-shell",
		created_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
		status: "running",
		username: "mockuser",
		container_type_name: "starter",
		desired_state: "running",
		memory_mb: 512,
		vcpus: 1,
		disk_gib: 5,
		status_label: "Running",
	},
	{
		id: 2,
		name: "playground",
		created_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
		status: "stopped",
		username: "mockuser",
		container_type_name: "standard",
		desired_state: "stopped",
		memory_mb: 1024,
		vcpus: 2,
		disk_gib: 10,
		status_label: "Stopped",
	},
	{
		id: 3,
		name: "shared-tools",
		created_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
		status: "running",
		username: "other-user",
		container_type_name: "starter",
		desired_state: "running",
		memory_mb: 512,
		vcpus: 1,
		disk_gib: 5,
		status_label: "Running",
	},
];

const mockUser: UserInfo = {
	username: "mockuser",
	is_superuser: false,
	active_containers: 1,
	has_quota: true,
	quota: {
		credits: INITIAL_CREDITS,
		credits_left: INITIAL_CREDITS - creditsUsed,
		ai_use_per_day: 5,
		ai_uses_left_today: 5,
		active: true,
		allowed_types: mockContainerTypes.map((type) => ({
			id: type.id,
			container_type_name: type.container_type_name,
			memory_mb: type.memory_mb,
			vcpus: type.vcpus,
			disk_gib: type.disk_gib,
			credits_cost: type.credits_cost,
		})),
	},
};

function cloneContainer(container: Container): Container {
	return { ...container };
}

function clampCredits() {
	const used = Math.max(0, Math.min(INITIAL_CREDITS, creditsUsed));
	mockUser.quota.credits_left = Math.max(0, INITIAL_CREDITS - used);
}

function refreshUserStats() {
	mockUser.active_containers = mockContainers.filter(
		(container) => container.username === mockUser.username && container.status === "running",
	).length;
	clampCredits();
}

export function mockFetchCurrentUser(): Promise<UserInfo> {
	refreshUserStats();
	return Promise.resolve({
		...mockUser,
		quota: {
			...mockUser.quota,
			allowed_types: mockUser.quota.allowed_types.map((type) => ({ ...type })),
		},
	});
}

export function mockListContainers(): Promise<Container[]> {
	return Promise.resolve(mockContainers.map(cloneContainer));
}

export function mockFetchContainerTypes(): Promise<ContainerType[]> {
	return Promise.resolve(mockContainerTypes.map((type) => ({ ...type })));
}

export function mockCreateContainer(payload: {
	container_type: number;
	container_name?: string;
}): Promise<void> {
	const type =
		mockContainerTypes.find((item) => item.id === payload.container_type) ?? mockContainerTypes[0];
	const cost = type.credits_cost ?? 1;
	if (INITIAL_CREDITS - creditsUsed < cost) {
		return Promise.reject(new Error("No quota available in mock mode"));
	}
	const trimmedName = payload.container_name?.trim();
	const name =
		trimmedName && trimmedName.length > 0
			? trimmedName
			: `${type.container_type_name}-${nextContainerId}`;

	const newContainer: Container = {
		id: nextContainerId++,
		name,
		created_at: new Date().toISOString(),
		status: "stopped",
		username: mockUser.username,
		container_type_name: type.container_type_name,
		desired_state: "stopped",
		memory_mb: type.memory_mb,
		vcpus: type.vcpus,
		disk_gib: type.disk_gib,
		status_label: "Stopped",
	};
	mockContainers = [...mockContainers, newContainer];
	creditsUsed = Math.min(INITIAL_CREDITS, creditsUsed + cost);
	refreshUserStats();
	return Promise.resolve();
}

export function mockDeleteContainer(containerId: number): Promise<void> {
	const container = mockContainers.find((item) => item.id === containerId);
	if (!container) {
		return Promise.resolve();
	}
	const type = mockContainerTypes.find(
		(item) => item.container_type_name === container.container_type_name,
	);
	creditsUsed = Math.max(0, creditsUsed - (type?.credits_cost ?? 1));
	mockContainers = mockContainers.filter((item) => item.id !== containerId);
	refreshUserStats();
	return Promise.resolve();
}

export function mockPowerOnContainer(containerId: number): Promise<void> {
	mockContainers = mockContainers.map((container) => {
		if (container.id !== containerId) return container;
		return {
			...container,
			status: "running",
			desired_state: "running",
			status_label: "Running",
		};
	});
	refreshUserStats();
	return Promise.resolve();
}

export function mockPowerOffContainer(containerId: number): Promise<void> {
	mockContainers = mockContainers.map((container) => {
		if (container.id !== containerId) return container;
		return {
			...container,
			status: "stopped",
			desired_state: "stopped",
			status_label: "Stopped",
		};
	});
	refreshUserStats();
	return Promise.resolve();
}

type MockMetricsState = {
	cpu: number;
	memory: number;
	threads: number;
};

const metricsState = new Map<number, MockMetricsState>();

function ensureMetricsState(containerId: number) {
	if (metricsState.has(containerId)) return;
	const container = mockContainers.find((item) => item.id === containerId);
	const running = container?.status === "running";
	const baseCpu = running ? 12 + Math.random() * 8 : Math.random() * 2;
	const baseMemory = (() => {
		const type = mockContainerTypes.find(
			(item) => item.container_type_name === container?.container_type_name,
		);
		const maxMb = type?.memory_mb ?? 512;
		return running ? maxMb * (0.55 + Math.random() * 0.25) : maxMb * 0.05;
	})();
	const threads = running ? 4 + Math.floor(Math.random() * 6) : 1;
	metricsState.set(containerId, {
		cpu: baseCpu,
		memory: baseMemory,
		threads,
	});
}

function randomStep(value: number, min: number, max: number, delta: number) {
	const next = value + (Math.random() * 2 - 1) * delta;
	return Math.max(min, Math.min(max, next));
}

export function mockFetchContainerStatistics(containerId: number): Promise<MetricData> {
	ensureMetricsState(containerId);
	const state = metricsState.get(containerId);
	if (!state) {
		return Promise.resolve({
			cpu: 0,
			memory: 0,
			threads: 0,
			timestamp: new Date().toISOString(),
		});
	}

	const container = mockContainers.find((item) => item.id === containerId);
	const running = container?.status === "running";
	const type = mockContainerTypes.find(
		(item) => item.container_type_name === container?.container_type_name,
	);
	const maxMb = type?.memory_mb ?? 512;

	state.cpu = running ? randomStep(state.cpu, 2, 85, 6) : randomStep(state.cpu, 0, 5, 2);
	state.memory = running
		? randomStep(state.memory, maxMb * 0.4, maxMb * 0.95, maxMb * 0.05)
		: randomStep(state.memory, 0, maxMb * 0.1, maxMb * 0.02);
	state.threads = running
		? Math.max(
				1,
				Math.min(32, state.threads + (Math.random() > 0.7 ? (Math.random() > 0.5 ? 1 : -1) : 0)),
			)
		: 1;

	return Promise.resolve({
		cpu: Number.parseFloat(state.cpu.toFixed(2)),
		memory: Number.parseFloat(state.memory.toFixed(2)),
		threads: state.threads,
		timestamp: new Date().toISOString(),
	});
}

import type { Container, ContainerType } from "@/types/container";
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

export function mockRenameContainer(containerId: number, name: string): Promise<void> {
	mockContainers = mockContainers.map((container) =>
		container.id === containerId ? { ...container, name } : container,
	);
	return Promise.resolve();
}

export function mockDuplicateContainer(containerId: number): Promise<void> {
	const source = mockContainers.find((item) => item.id === containerId);
	if (!source) {
		return Promise.reject(new Error("Container not found in mock mode"));
	}
	const type = mockContainerTypes.find(
		(item) => item.container_type_name === source.container_type_name,
	);
	const cost = type?.credits_cost ?? 1;
	if (INITIAL_CREDITS - creditsUsed < cost) {
		return Promise.reject(new Error("No quota available in mock mode"));
	}
	const copy: Container = {
		...source,
		id: nextContainerId++,
		name: `${source.name}-copy`,
		created_at: new Date().toISOString(),
		status: "running",
		desired_state: "running",
		status_label: "Running",
		username: mockUser.username,
	};
	mockContainers = [...mockContainers, copy];
	creditsUsed = Math.min(INITIAL_CREDITS, creditsUsed + cost);
	refreshUserStats();
	return Promise.resolve();
}

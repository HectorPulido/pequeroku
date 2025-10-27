export type ContainerStatus =
	| "running"
	| "stopped"
	| "starting"
	| "stopping"
	| "powering_on"
	| "powering_off"
	| "error"
	| "unknown"
	| string;

export interface Container {
	id: number;
	name: string;
	created_at: string;
	status: ContainerStatus;
	username: string;
	container_type_name: string;
	desired_state?: string;
	memory_mb?: number;
	vcpus?: number;
	disk_gib?: number;
	status_label?: string;
}

export interface ContainerType {
	id: number;
	container_type_name: string;
	memory_mb: number;
	vcpus: number;
	disk_gib: number;
	credits_cost?: number;
}

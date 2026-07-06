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
	/** Usernames of the collaborators granted access to this container. */
	allowed_usernames?: string[];
	/** Whether the current user owns this container (vs. being a collaborator). */
	is_owner?: boolean;
}

export interface AllowedUsersResult {
	usernames: string[];
	/** Requested usernames that don't exist and were skipped. */
	not_found: string[];
}

export interface ContainerType {
	id: number;
	container_type_name: string;
	memory_mb: number;
	vcpus: number;
	disk_gib: number;
	credits_cost?: number;
}

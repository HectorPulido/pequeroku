export interface UserQuota {
	credits: number;
	credits_left: number;
	ai_use_per_day: number;
	ai_uses_left_today: number;
	active: boolean;
	allowed_types: Array<{
		id: number;
		container_type_name: string;
		memory_mb: number;
		vcpus: number;
		disk_gib: number;
		credits_cost?: number;
	}>;
}

export interface UserInfo {
	username: string;
	is_superuser: boolean;
	active_containers: number;
	has_quota: boolean;
	quota: UserQuota;
}

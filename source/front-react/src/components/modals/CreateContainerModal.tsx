import { Plus } from "iconoir-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { ContainerType } from "@/types/container";

interface CreateContainerModalProps {
	isOpen: boolean;
	onClose: () => void;
	credits: number;
	types: ContainerType[] | null;
	isLoading: boolean;
	onCreate: (typeId: number, containerName: string) => Promise<void>;
}

const CreateContainerModal: React.FC<CreateContainerModalProps> = ({
	isOpen,
	onClose,
	credits,
	types,
	isLoading,
	onCreate,
}) => {
	const [containerName, setContainerName] = useState("");
	const [pendingTypeId, setPendingTypeId] = useState<number | null>(null);

	useEffect(() => {
		if (!isOpen) {
			setContainerName("");
			setPendingTypeId(null);
		}
	}, [isOpen]);

	const sortedTypes = useMemo(() => {
		if (!types) return [];
		const cost = (type: ContainerType) =>
			typeof type.credits_cost === "number" ? type.credits_cost : Number.MAX_SAFE_INTEGER;
		return [...types].sort((a, b) => cost(a) - cost(b));
	}, [types]);

	const canCreate = (type: ContainerType) => {
		if (typeof type.credits_cost !== "number") return true;
		return credits >= type.credits_cost;
	};

	const handleCreate = async (typeId: number) => {
		setPendingTypeId(typeId);
		try {
			await onCreate(typeId, containerName.trim());
			setContainerName("");
			onClose();
		} finally {
			setPendingTypeId(null);
		}
	};

	return (
		<Modal
			isOpen={isOpen}
			onClose={onClose}
			title="Create container"
			size="md"
		>
			<div className="space-y-5">
				<div>
					<label
						className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-400"
						htmlFor="container-name-input"
					>
						Container name (optional)
					</label>
					<input
						id="container-name-input"
						value={containerName}
						onChange={(event) => setContainerName(event.target.value)}
						placeholder="friendly-name"
						className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
					/>
				</div>

				<div className="space-y-3">
					{isLoading && (
						<div className="flex items-center justify-center py-10 text-sm text-gray-400">
							Loading container types...
						</div>
					)}

					{!isLoading && sortedTypes.length === 0 && (
						<div className="rounded-md border border-gray-700 bg-[#0B1220] px-4 py-5 text-center text-sm text-gray-400">
							No container types available
						</div>
					)}

					{!isLoading &&
						sortedTypes.map((type) => {
							const afford = canCreate(type);
							const disabled = !afford || pendingTypeId === type.id;
							const specs = [
								type.memory_mb ? `${type.memory_mb} MB RAM` : null,
								type.vcpus ? `${type.vcpus} vCPU` : null,
								type.disk_gib ? `${type.disk_gib} GiB disk` : null,
							]
								.filter(Boolean)
								.join(" • ");

							return (
								<div
									key={type.id}
									className="rounded-lg border border-gray-700 bg-[#111827] px-4 py-4 text-sm text-gray-200"
								>
									<div className="mb-3 flex items-center justify-between gap-3">
										<div>
											<div className="text-base font-semibold text-white">
												{type.container_type_name}
											</div>
											<div className="text-xs text-gray-400">{specs}</div>
										</div>
										{typeof type.credits_cost === "number" && (
											<span className="rounded border border-indigo-500/40 bg-indigo-500/10 px-2 py-1 text-xs font-semibold text-indigo-200">
												{type.credits_cost} credits
											</span>
										)}
									</div>
									<Button
										icon={<Plus className="h-4 w-4" />}
										className="w-full"
										onClick={() => handleCreate(type.id)}
										disabled={disabled}
									>
										{pendingTypeId === type.id ? "Creating..." : "Create"}
									</Button>
									{!afford && (
										<div className="mt-2 text-xs text-rose-300">
											Not enough credits for this container type.
										</div>
									)}
								</div>
							);
						})}
				</div>
			</div>
		</Modal>
	);
};

export default CreateContainerModal;

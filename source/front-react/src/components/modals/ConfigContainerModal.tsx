import { Check, Copy } from "iconoir-react";
import type React from "react";
import { useEffect, useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import type { Container } from "@/types/container";

interface ConfigContainerModalProps {
	container: Container | null;
	onClose: () => void;
	onRename: (name: string) => Promise<void>;
	onDuplicate: () => Promise<void>;
}

const ConfigContainerModal: React.FC<ConfigContainerModalProps> = ({
	container,
	onClose,
	onRename,
	onDuplicate,
}) => {
	const [name, setName] = useState("");
	const [isSavingName, setIsSavingName] = useState(false);
	const [isDuplicating, setIsDuplicating] = useState(false);

	// Re-seed the form whenever a different container is opened for configuration.
	useEffect(() => {
		if (container) {
			setName(container.name);
		}
	}, [container]);

	const isOpen = container !== null;
	const isRunning = container?.status === "running";
	const trimmedName = name.trim();
	const nameChanged = container ? trimmedName !== container.name : false;
	const canSaveName = Boolean(container) && trimmedName.length > 0 && nameChanged && !isSavingName;

	const handleRename = async () => {
		if (!canSaveName) return;
		setIsSavingName(true);
		try {
			await onRename(trimmedName);
			onClose();
		} finally {
			setIsSavingName(false);
		}
	};

	const handleDuplicate = async () => {
		if (!container || isRunning || isDuplicating) return;
		const confirmed =
			typeof window === "undefined" ||
			window.confirm(
				`Duplicate "${container.id} — ${container.name}" into a new container?\n\n` +
					"This creates a full copy of the disk and files as a new machine and " +
					"consumes credits.",
			);
		if (!confirmed) return;
		setIsDuplicating(true);
		try {
			await onDuplicate();
			onClose();
		} finally {
			setIsDuplicating(false);
		}
	};

	const title = container
		? `Configure container - (${container.id}) ${container.name}`
		: "Configure container";

	return (
		<Modal isOpen={isOpen} onClose={onClose} title={title} size="md">
			<div className="space-y-6">
				<section className="space-y-3 rounded-lg border border-gray-700 bg-[#111827] px-4 py-4">
					<div>
						<label
							className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-400"
							htmlFor="config-container-name"
						>
							Container name
						</label>
						<input
							id="config-container-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							onKeyDown={(event) => {
								if (event.key === "Enter") {
									event.preventDefault();
									void handleRename();
								}
							}}
							placeholder="friendly-name"
							className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
						/>
					</div>
					<Button
						icon={<Check className="h-4 w-4" />}
						className="w-full"
						onClick={handleRename}
						disabled={!canSaveName}
					>
						{isSavingName ? "Saving..." : "Save name"}
					</Button>
				</section>

				<section className="space-y-3 rounded-lg border border-gray-700 bg-[#111827] px-4 py-4">
					<div>
						<div className="text-xs font-semibold uppercase tracking-wide text-gray-400">
							Duplicate
						</div>
						<p className="mt-1 text-xs text-gray-500">
							Create a full copy of this container (disk and files) as a new machine.
							{isRunning
								? " Stop the container first — it must be off to duplicate safely."
								: " You'll be asked to confirm; it consumes credits."}
						</p>
					</div>
					<Button
						variant="secondary"
						icon={<Copy className="h-4 w-4" />}
						className="w-full"
						onClick={handleDuplicate}
						disabled={isRunning || isDuplicating}
					>
						{isDuplicating ? "Duplicating..." : "Duplicate container"}
					</Button>
				</section>
			</div>
		</Modal>
	);
};

export default ConfigContainerModal;

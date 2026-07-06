import { Check, Copy, Plus, Xmark } from "iconoir-react";
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
	/** Persist the collaborator list; resolves with the usernames the backend
	 * actually accepted (unknown ones are dropped). */
	onUpdateAllowedUsers: (usernames: string[]) => Promise<string[]>;
}

function sameUsers(a: string[], b: string[]): boolean {
	if (a.length !== b.length) return false;
	const sortedA = [...a].sort();
	const sortedB = [...b].sort();
	return sortedA.every((value, index) => value === sortedB[index]);
}

const ConfigContainerModal: React.FC<ConfigContainerModalProps> = ({
	container,
	onClose,
	onRename,
	onDuplicate,
	onUpdateAllowedUsers,
}) => {
	const [name, setName] = useState("");
	const [isSavingName, setIsSavingName] = useState(false);
	const [isDuplicating, setIsDuplicating] = useState(false);

	const [users, setUsers] = useState<string[]>([]);
	const [originalUsers, setOriginalUsers] = useState<string[]>([]);
	const [draft, setDraft] = useState("");
	const [isSavingUsers, setIsSavingUsers] = useState(false);

	// Re-seed the form whenever a different container is opened for configuration.
	useEffect(() => {
		if (container) {
			setName(container.name);
			const seeded = container.allowed_usernames ?? [];
			setUsers(seeded);
			setOriginalUsers(seeded);
			setDraft("");
		}
	}, [container]);

	const isOpen = container !== null;
	const isRunning = container?.status === "running";
	// The owner manages name + access; collaborators only get the safe actions.
	const isOwner = container ? container.is_owner !== false : false;

	const trimmedName = name.trim();
	const nameChanged = container ? trimmedName !== container.name : false;
	const canSaveName = Boolean(container) && trimmedName.length > 0 && nameChanged && !isSavingName;

	const usersChanged = !sameUsers(users, originalUsers);
	const canSaveUsers = Boolean(container) && usersChanged && !isSavingUsers;

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

	const addDraftUser = () => {
		const value = draft.trim();
		if (!value) return;
		// Owning yourself is implicit; skip it and any duplicate.
		if (container && value === container.username) {
			setDraft("");
			return;
		}
		if (users.includes(value)) {
			setDraft("");
			return;
		}
		setUsers((current) => [...current, value]);
		setDraft("");
	};

	const removeUser = (username: string) => {
		setUsers((current) => current.filter((item) => item !== username));
	};

	const handleDraftKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
		if (event.key === "Enter" || event.key === ",") {
			event.preventDefault();
			addDraftUser();
		}
	};

	const handleSaveUsers = async () => {
		if (!canSaveUsers) return;
		setIsSavingUsers(true);
		try {
			const accepted = await onUpdateAllowedUsers(users);
			const next = Array.isArray(accepted) ? accepted : users;
			setUsers(next);
			setOriginalUsers(next);
		} finally {
			setIsSavingUsers(false);
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
				{isOwner ? (
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
				) : null}

				{isOwner ? (
					<section className="space-y-3 rounded-lg border border-gray-700 bg-[#111827] px-4 py-4">
						<div>
							<div className="text-xs font-semibold uppercase tracking-wide text-gray-400">
								Allowed users
							</div>
							<p className="mt-1 text-xs text-gray-500">
								People who can use this machine — open the IDE, start/stop, duplicate, move files
								and run things. They can't rename or delete it; you stay the owner.
							</p>
						</div>

						{users.length > 0 ? (
							<div className="flex flex-wrap gap-2">
								{users.map((username) => (
									<span
										key={username}
										className="inline-flex items-center gap-1 rounded-full bg-gray-700 px-2.5 py-1 text-xs text-gray-100"
									>
										{username}
										<button
											type="button"
											onClick={() => removeUser(username)}
											className="rounded-full p-0.5 text-gray-300 transition hover:text-white"
											aria-label={`Remove ${username}`}
										>
											<Xmark className="h-3 w-3" />
										</button>
									</span>
								))}
							</div>
						) : (
							<p className="text-xs text-gray-600">No collaborators yet.</p>
						)}

						<div className="flex gap-2">
							<input
								value={draft}
								onChange={(event) => setDraft(event.target.value)}
								onKeyDown={handleDraftKeyDown}
								placeholder="username"
								aria-label="Add a username"
								className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
							/>
							<Button
								type="button"
								variant="secondary"
								icon={<Plus className="h-4 w-4" />}
								onClick={addDraftUser}
								disabled={!draft.trim()}
							>
								Add
							</Button>
						</div>

						<Button
							icon={<Check className="h-4 w-4" />}
							className="w-full"
							onClick={handleSaveUsers}
							disabled={!canSaveUsers}
						>
							{isSavingUsers ? "Saving..." : "Save allowed users"}
						</Button>
					</section>
				) : null}

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

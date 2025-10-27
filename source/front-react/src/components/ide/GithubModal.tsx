import type React from "react";
import { useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import { alertStore } from "@/lib/alertStore";

interface GithubModalProps {
	isOpen: boolean;
	onClose: () => void;
	onClone: (options: { url: string; basePath: string; clean: boolean }) => Promise<void>;
}

const GithubModal: React.FC<GithubModalProps> = ({ isOpen, onClose, onClone }) => {
	const [url, setUrl] = useState("https://github.com/HectorPulido/generic-portfolio");
	const [basePath, setBasePath] = useState("/");
	const [clean, setClean] = useState(true);
	const [isSubmitting, setIsSubmitting] = useState(false);

	const handleClone = async () => {
		const trimmed = url.trim();
		if (!trimmed) {
			alertStore.push({ message: "Repository URL is required", variant: "warning" });
			return;
		}
		setIsSubmitting(true);
		try {
			await onClone({ url: trimmed, basePath: basePath.trim() || "/", clean });
			alertStore.push({
				message: `Clone request queued for ${trimmed}`,
				variant: "info",
			});
			onClose();
		} catch (error) {
			const message = error instanceof Error ? error.message : "Clone failed";
			alertStore.push({ message, variant: "error" });
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Modal isOpen={isOpen} title="Clone from GitHub" onClose={onClose}>
			<div className="space-y-4">
				<div>
					<label
						className="mb-2 block text-xs uppercase tracking-wide text-gray-400"
						htmlFor="github-modal-url"
					>
						Repository URL
					</label>
					<input
						id="github-modal-url"
						type="url"
						value={url}
						onChange={(event) => setUrl(event.target.value)}
						disabled={isSubmitting}
						className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
					/>
				</div>

				<div>
					<label
						className="mb-2 block text-xs uppercase tracking-wide text-gray-400"
						htmlFor="github-modal-destination"
					>
						Base path
					</label>
					<input
						id="github-modal-destination"
						type="text"
						value={basePath}
						onChange={(event) => setBasePath(event.target.value)}
						disabled={isSubmitting}
						className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
					/>
				</div>

				<label className="flex items-center gap-2 text-xs text-gray-400">
					<input
						type="checkbox"
						checked={clean}
						onChange={(event) => setClean(event.target.checked)}
						disabled={isSubmitting}
						className="rounded border-gray-700 bg-[#0B1220]"
					/>
					Clean /app before cloning
				</label>

				<p className="text-xs text-gray-500">
					The repository is copied into <code>/app</code>; use the base path to target a subfolder
					inside the repo (for example <code>/examples/basic</code>). Enable <strong>clean</strong>{" "}
					to wipe <code>/app</code> before copying files.
				</p>

				<div className="flex justify-end gap-3 border-t border-gray-800 pt-4">
					<Button variant="secondary" size="sm" onClick={onClose} disabled={isSubmitting}>
						Cancel
					</Button>
					<Button
						variant="primary"
						size="sm"
						onClick={() => void handleClone()}
						disabled={isSubmitting}
					>
						{isSubmitting ? "Cloning..." : "Clone"}
					</Button>
				</div>
			</div>
		</Modal>
	);
};

export default GithubModal;

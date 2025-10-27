import type React from "react";
import { useEffect, useState } from "react";
import Button from "@/components/Button";
import Modal from "@/components/Modal";
import { alertStore } from "@/lib/alertStore";

interface UploadModalProps {
	isOpen: boolean;
	onClose: () => void;
	onUpload: (file: File, destination: string) => Promise<string | undefined>;
	initialDestination?: string;
}

const UploadModal: React.FC<UploadModalProps> = ({
	isOpen,
	onClose,
	onUpload,
	initialDestination = "/app",
}) => {
	const [file, setFile] = useState<File | null>(null);
	const [destination, setDestination] = useState(initialDestination);
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		if (!isOpen) return;
		setDestination(initialDestination || "/app");
		setFile(null);
		setIsSubmitting(false);
	}, [initialDestination, isOpen]);

	const handleUpload = async () => {
		if (!file) {
			alertStore.push({ message: "Select a file first.", variant: "warning" });
			return;
		}
		setIsSubmitting(true);
		try {
			const result = await onUpload(file, destination || "/app");
			onClose();
			const effectiveDestination =
				typeof result === "string" && result.trim() ? result.trim() : destination || "/app";
			alertStore.push({
				message: `Uploaded ${file.name} → ${effectiveDestination}`,
				variant: "success",
			});
		} catch (error) {
			const message = error instanceof Error ? error.message : "Upload failed";
			alertStore.push({ message, variant: "error" });
		} finally {
			setIsSubmitting(false);
			setFile(null);
		}
	};

	return (
		<Modal isOpen={isOpen} title="Upload file" onClose={onClose}>
			<div className="space-y-5">
				<div>
					<label
						className="block text-xs uppercase tracking-wide text-gray-400 mb-2"
						htmlFor="upload-destination"
					>
						Destination
					</label>
					<input
						id="upload-destination"
						type="text"
						value={destination}
						onChange={(event) => setDestination(event.target.value)}
						disabled={isSubmitting}
						className="w-full rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
						placeholder="/app"
					/>
				</div>

				<div>
					<label
						className="block text-xs uppercase tracking-wide text-gray-400 mb-2"
						htmlFor="upload-file-input"
					>
						Select file
					</label>
					<input
						id="upload-file-input"
						type="file"
						onChange={(event) => setFile(event.target.files?.[0] ?? null)}
						disabled={isSubmitting}
						className="w-full text-sm text-gray-300"
					/>
					<p className="mt-2 text-xs text-gray-500">
						Files upload through the container REST endpoint. Large uploads may take a few seconds
						to appear in the explorer.
					</p>
				</div>

				<div className="flex justify-end gap-3 border-t border-gray-800 pt-4">
					<Button variant="secondary" size="sm" onClick={onClose} disabled={isSubmitting}>
						Cancel
					</Button>
					<Button
						variant="primary"
						size="sm"
						onClick={() => void handleUpload()}
						disabled={!file || isSubmitting}
					>
						{isSubmitting ? "Uploading..." : "Upload"}
					</Button>
				</div>
			</div>
		</Modal>
	);
};

export default UploadModal;

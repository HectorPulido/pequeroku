import type React from "react";
import { useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { alertStore } from "@/lib/alertStore";
import type { TemplateSummary } from "@/types/template";

interface TemplatesModalProps {
	isOpen: boolean;
	onClose: () => void;
	templates: TemplateSummary[];
	loading: boolean;
	error?: string | null;
	onReload: () => Promise<void> | void;
	onApply: (templateId: string, options: { destination: string; clean: boolean }) => Promise<void>;
	defaultDestination?: string;
}

const TemplatesModal: React.FC<TemplatesModalProps> = ({
	isOpen,
	onClose,
	templates,
	loading,
	error,
	onReload,
	onApply,
	defaultDestination = "/app",
}) => {
	const [destination, setDestination] = useState(defaultDestination);
	const [clean, setClean] = useState(true);
	const [pendingTemplate, setPendingTemplate] = useState<string | null>(null);

	useEffect(() => {
		if (!isOpen) return;
		setDestination(defaultDestination || "/app");
		setClean(true);
		setPendingTemplate(null);
	}, [defaultDestination, isOpen]);

	const handleApply = async (template: TemplateSummary) => {
		setPendingTemplate(template.id);
		try {
			await onApply(template.id, { destination, clean });
			alertStore.push({
				message: `Template "${template.name}" applied to ${destination}`,
				variant: "success",
			});
			onClose();
		} catch (err) {
			const message = err instanceof Error ? err.message : "Template apply failed";
			alertStore.push({ message, variant: "error" });
		} finally {
			setPendingTemplate(null);
		}
	};

	return (
		<Modal isOpen={isOpen} title="Templates" onClose={onClose} size="lg">
			<div className="space-y-5">
				<div className="space-y-3 rounded-md border border-gray-800 bg-[#0B1220] p-4" hidden>
					<div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-center">
						<label className="text-xs uppercase tracking-wide text-gray-400" htmlFor="tpl-dest">
							Destination path
						</label>
						<input
							id="tpl-dest"
							type="text"
							value={destination}
							onChange={(event) => setDestination(event.target.value)}
							className="rounded-md border border-gray-700 bg-[#0B1220] px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
							placeholder="/app"
						/>
					</div>
					<label className="flex items-center gap-2 text-xs text-gray-400">
						<input
							type="checkbox"
							checked={clean}
							onChange={(event) => setClean(event.target.checked)}
							className="rounded border-gray-700 bg-[#0B1220]"
						/>
						Clean destination before applying
					</label>
					<button
						type="button"
						onClick={() => void onReload()}
						className="text-xs uppercase tracking-wide text-indigo-400 hover:text-indigo-200"
					>
						Refresh templates
					</button>
					{error ? <p className="text-xs text-red-400">{error}</p> : null}
				</div>

				{loading ? (
					<div className="rounded-md border border-gray-800 bg-[#0B1220] p-6 text-center text-sm text-gray-400">
						Loading templates...
					</div>
				) : templates.length === 0 ? (
					<div className="rounded-md border border-gray-800 bg-[#0B1220] p-6 text-center text-sm text-gray-400">
						No templates available.
					</div>
				) : (
					<div className="space-y-4">
						{templates.map((template) => (
							<div
								key={template.id}
								className="rounded-md border border-gray-800 bg-[#0B1220] p-4 hover:border-indigo-600 transition-colors"
							>
								<div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
									<div>
										<h3 className="text-sm font-semibold text-white">{template.name}</h3>
										<p className="mt-1 text-xs text-gray-400">{template.description}</p>
										<p className="mt-2 text-xs text-gray-500">
											Default destination:{" "}
											<span className="text-gray-300">{template.destination}</span>
										</p>
									</div>
									<button
										onClick={() => void handleApply(template)}
										className="self-start rounded-md bg-indigo-600 px-3 py-1 text-xs uppercase tracking-wide text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-gray-700"
										type="button"
										disabled={pendingTemplate === template.id}
									>
										{pendingTemplate === template.id ? "Applying..." : "Apply"}
									</button>
								</div>
							</div>
						))}
					</div>
				)}
			</div>
		</Modal>
	);
};

export default TemplatesModal;

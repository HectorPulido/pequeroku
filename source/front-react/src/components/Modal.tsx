import { Xmark } from "iconoir-react";
import Button from "@/components/Button";
import type React from "react";

type ModalSize = "sm" | "md" | "lg" | "xl";

const sizeClassMap: Record<ModalSize, string> = {
	sm: "max-w-md max-h-[90vh]",
	md: "max-w-2xl max-h-[90vh]",
	lg: "max-w-4xl max-h-[90vh]",
	xl: "max-w-[95vw] h-[95vh]",
};

interface ModalProps {
	isOpen: boolean;
	title: string;
	onClose: () => void;
	children: React.ReactNode;
	footer?: React.ReactNode;
	size?: ModalSize;
	padding?: string;
	headerActions?: React.ReactNode;
}

const Modal: React.FC<ModalProps> = ({
	isOpen,
	title,
	onClose,
	children,
	footer,
	size = "md",
	padding = "p-5",
	headerActions,
}) => {
	if (!isOpen) return null;

	const sizeClasses = sizeClassMap[size] ?? sizeClassMap.md;
	const bodyPadding = padding && padding.trim().length > 0 ? padding : "p-0";

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
			<div
				className={`flex w-full flex-col overflow-hidden rounded-lg border border-gray-800 bg-[#111827] shadow-xl ${sizeClasses}`}
			>
				<div className="flex shrink-0 items-center justify-between border-b border-gray-800 px-6 py-4">
					<h2 className="text-lg font-semibold text-white">{title}</h2>
					<div className="flex items-center gap-2">
						{headerActions}
						<Button
  						variant="secondary"
  						size="sm"
							onClick={onClose}
						>
							<Xmark className="h-5 w-5" />
						</Button>
					</div>
				</div>

				<div className={`flex-1 overflow-y-auto ${bodyPadding} text-sm text-gray-200`}>
					{children}
				</div>

				{footer ? (
					<div className="flex shrink-0 justify-end gap-3 border-t border-gray-800 bg-[#0B1220] px-6 py-4">
						{footer}
					</div>
				) : null}
			</div>
		</div>
	);
};

export default Modal;

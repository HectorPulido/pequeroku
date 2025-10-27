import type React from "react";
import { variantClasses } from "@/components/AlertStack.constants";
import type { AlertMessage } from "@/lib/alertStore";

export interface AlertStackViewProps {
	alerts: AlertMessage[];
	onDismiss: (id: string) => void;
}

const AlertStackView: React.FC<AlertStackViewProps> = ({ alerts, onDismiss }) => {
	if (alerts.length === 0) return null;

	return (
		<div className="fixed top-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-3">
			{alerts.map((alert) => (
				<div
					key={alert.id}
					className={`rounded-md border px-4 py-3 text-sm shadow-lg transition ${variantClasses[alert.variant]}`}
				>
					<div className="flex items-start justify-between gap-3">
						<div className="flex flex-col gap-1 whitespace-pre-line">{alert.message}</div>
						{alert.dismissible !== false && (
							<button
								className="text-xs uppercase tracking-wide text-white/80 hover:text-white"
								onClick={() => onDismiss(alert.id)}
							>
								Close
							</button>
						)}
					</div>
				</div>
			))}
		</div>
	);
};

export default AlertStackView;

import type React from "react";
import type { PortOption } from "@/hooks/usePreviewPorts";

interface PortSelectorProps {
	value: number | null;
	options: PortOption[];
	onChange: (port: number | null) => void;
	/** Fired when the user opens the dropdown — use it to re-scan for fresh ports. */
	onOpen?: () => void;
	className?: string;
}

/**
 * Preview port dropdown shared by the IDE editor and the AI preview browser.
 * Renders nothing when there are no ports to choose from; styling is supplied by
 * the caller via `className` so it matches each surrounding panel.
 */
const PortSelector: React.FC<PortSelectorProps> = ({
	value,
	options,
	onChange,
	onOpen,
	className,
}) => {
	if (options.length === 0) return null;
	return (
		<select
			value={value ?? ""}
			onChange={(event) => {
				const parsed = Number.parseInt(event.target.value, 10);
				onChange(Number.isFinite(parsed) ? parsed : null);
			}}
			// mousedown fires before the native list opens, so the re-scan is already
			// in flight; freshly-started ports show on the next open.
			onMouseDown={() => onOpen?.()}
			title="Preview port"
			className={className}
		>
			{value === null && (
				<option value="" disabled>
					Port…
				</option>
			)}
			{options.map((option) => (
				<option key={option.port} value={option.port}>
					{option.label}
				</option>
			))}
		</select>
	);
};

export default PortSelector;

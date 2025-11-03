import { LongArrowDownLeft } from "iconoir-react";
import type React from "react";
import { Link } from "react-router-dom";
import ThemeToggle from "@/components/ThemeToggle";

interface HeaderProps {
	backTo?: string;
	backLabel?: string;
	leading?: React.ReactNode;
	children?: React.ReactNode;
}

/**
 * Minimal header shared by the standalone IDE and metrics pages.
 * Mirrors the legacy `/front/page` layout: brand on the left and a single
 * back button that returns to the dashboard shell. Override the left-hand
 * branding via `leading` and inject custom actions through `children`. When
 * custom children are provided the default theme toggle and back button are
 * hidden so the consumer can supply a bespoke layout.
 */
const Header: React.FC<HeaderProps> = ({
	backTo = "/dashboard",
	backLabel = "Back to dashboard",
	children,
}) => {
	const showDefaultActions = !children;

	return (
		<header className="flex gap-4 border-b border-gray-800 bg-[#111827] px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
			<div className="flex items-center gap-3">
        <a href="#" className="brand" aria-label="PequeRoku home">
          <span className="logo" aria-hidden="true">ʕ•ᴥ•ʔ</span>
          <span className="name"><span>Peque</span><strong>Roku</strong></span>
        </a>
			</div>
			<div className="flex flex-wrap items-center gap-3 sm:justify-end">
				{showDefaultActions ? (
					<>
						<Link
							to={backTo}
							aria-label={backLabel}
							className="inline-flex h-9 w-9 items-center justify-center rounded border border-gray-700 text-gray-300 transition hover:border-indigo-500 hover:text-white"
						>
							<LongArrowDownLeft className="h-4 w-4" />
						</Link>
					</>
				) : (
					children
				)}
			  <ThemeToggle />
			</div>
		</header>
	);
};

export default Header;

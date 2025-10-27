import { LongArrowDownLeft } from "iconoir-react";
import type React from "react";
import { Link } from "react-router-dom";
import ThemeToggle from "@/components/ThemeToggle";

interface HeaderProps {
	backTo?: string;
	backLabel?: string;
	children?: React.ReactNode;
}

/**
 * Minimal header shared by the standalone IDE and metrics pages.
 * Mirrors the legacy `/front/page` layout: brand on the left and a single
 * back button that returns to the dashboard shell. Additional actions (if any)
 * can be injected via `children` so the component stays flexible while keeping
 * the default visual contract intact.
 */
const Header: React.FC<HeaderProps> = ({
	backTo = "/dashboard",
	backLabel = "Back to dashboard",
	children,
}) => {
	return (
		<header className="flex items-center justify-between border-b border-gray-800 bg-[#111827] px-6 py-4">
			<div className="flex items-center gap-3">
				<h1 className="text-lg font-semibold text-white">PequeRoku</h1>
			</div>
			<div className="flex items-center gap-3">
				{children}
				<ThemeToggle />
				<Link
					to={backTo}
					aria-label={backLabel}
					className="inline-flex h-9 w-9 items-center justify-center rounded border border-gray-700 text-gray-300 transition hover:border-indigo-500 hover:text-white"
				>
					<LongArrowDownLeft className="h-4 w-4" />
				</Link>
			</div>
		</header>
	);
};

export default Header;

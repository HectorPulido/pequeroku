import type React from "react";

type ButtonVariant = "primary" | "secondary" | "danger" | "success";
type ButtonSize = "sm" | "md";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
	variant?: ButtonVariant;
	icon?: React.ReactNode;
	size?: ButtonSize;
}

const variantClasses: Record<ButtonVariant, string> = {
	primary: "bg-indigo-600 hover:bg-indigo-700 text-white disabled:bg-indigo-600/60",
	secondary: "bg-gray-700 hover:bg-gray-600 text-gray-200 disabled:bg-gray-700/50",
	danger: "bg-rose-600 hover:bg-rose-700 text-white disabled:bg-rose-600/60",
	success: "bg-emerald-600 hover:bg-emerald-700 text-white disabled:bg-emerald-600/60",
};

const sizeClasses: Record<ButtonSize, string> = {
	sm: "px-3 py-1.5 text-xs",
	md: "px-4 py-2 text-sm",
};

const Button: React.FC<ButtonProps> = ({
	variant = "primary",
	icon,
	children,
	size = "md",
	className = "",
	type = "button",
	disabled,
	...rest
}) => {
	const baseClass =
		"inline-flex items-center justify-center gap-1.5 font-medium rounded-md transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-indigo-500 disabled:cursor-not-allowed disabled:text-white/70 disabled:hover:none focus-visible:ring-offset-[#0B1220]";

	return (
		<button
			type={type}
			className={`${baseClass} ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
			disabled={disabled}
			{...rest}
		>
			{icon}
			{children}
		</button>
	);
};

export default Button;

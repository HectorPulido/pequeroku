import { Sparks } from "iconoir-react";
import type React from "react";

interface WelcomeScreenProps {
	onPick: (prompt: string) => void;
}

const SUGGESTIONS: { title: string; detail: string; prompt: string }[] = [
	{
		title: "Explain a build error",
		detail: "paste the failing output and ask why",
		prompt: "I'm getting a build error in my project. Help me read the logs and fix it.",
	},
	{
		title: "Scaffold a feature",
		detail: "create the files and wire them up",
		prompt: "Scaffold a small REST endpoint in this project and show me the files you created.",
	},
	{
		title: "Write tests",
		detail: "cover the current module",
		prompt: "Write unit tests for the main module in this project and run them.",
	},
	{
		title: "Run the app",
		detail: "start it and open the preview",
		prompt: "Start the app defined in config.json and tell me which port to preview.",
	},
];

const WelcomeScreen: React.FC<WelcomeScreenProps> = ({ onPick }) => (
	<div className="flex h-full flex-col items-center justify-center px-4 text-center">
		<div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-500/15 text-indigo-300">
			<Sparks className="h-7 w-7" />
		</div>
		<h2 className="text-xl font-semibold text-white">PequeRoku AI</h2>
		<p className="mt-1 max-w-md text-sm text-gray-400">
			Ask about your project, run commands, build features or debug errors. The assistant works
			directly inside this container.
		</p>

		<div className="mt-8 w-full max-w-xl">
			<div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
				<Sparks className="h-3.5 w-3.5" />
				Suggested
			</div>
			<div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
				{SUGGESTIONS.map((suggestion) => (
					<button
						key={suggestion.title}
						type="button"
						onClick={() => onPick(suggestion.prompt)}
						className="rounded-xl border border-gray-800 bg-[#111827] px-4 py-3 text-left transition hover:border-indigo-600 hover:bg-[#151d2e]"
					>
						<div className="text-sm font-medium text-gray-100">{suggestion.title}</div>
						<div className="text-xs text-gray-500">{suggestion.detail}</div>
					</button>
				))}
			</div>
		</div>
	</div>
);

export default WelcomeScreen;

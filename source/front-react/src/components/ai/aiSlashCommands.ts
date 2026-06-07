/**
 * Slash commands the AI WebSocket consumer special-cases (see
 * web_service/ai_services/ai_consumers.py — `/clear` and `/init`). Anything else
 * typed in the composer is sent to the agent verbatim as a prompt. Keep this
 * list in sync with the backend's command handling.
 */
export interface AiSlashCommand {
	/** Command name without the leading slash. */
	name: string;
	/** One-line summary shown in the autocomplete menu. */
	description: string;
}

export const AI_SLASH_COMMANDS: AiSlashCommand[] = [
	{ name: "clear", description: "Clear this conversation's memory" },
	{ name: "init", description: "Create or improve AGENTS.md for this project" },
];

/**
 * Commands whose `/name` prefix-matches the current composer input. Matching is
 * case-insensitive and only applies while the user is still typing the command
 * token (a leading "/" with no spaces yet); once a space is typed the command is
 * considered complete and no longer autocompleted.
 */
export const matchSlashCommands = (value: string): AiSlashCommand[] => {
	if (!value.startsWith("/") || value.includes(" ")) return [];
	const query = value.slice(1).toLowerCase();
	return AI_SLASH_COMMANDS.filter((command) => command.name.startsWith(query));
};

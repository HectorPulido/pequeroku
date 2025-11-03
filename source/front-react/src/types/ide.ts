import type { FitAddon } from "@xterm/addon-fit";
import type { Terminal } from "@xterm/xterm";

export interface FileNode {
	name: string;
	type: "file" | "folder";
	path: string;
	children?: FileNode[];
	isOpen?: boolean;
}

export interface Tab {
	id: string;
	title: string;
	path: string;
	content?: string;
	isDirty?: boolean;
}

export interface TerminalTab {
	id: string;
	title: string;
	terminal: Terminal | null;
	fitAddon: FitAddon | null;
	service?: InstanceType<typeof import("@/services/ide/TerminalWebService").default>;
}

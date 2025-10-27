declare module "@xterm/addon-fit" {
	import type { ITerminalAddon, Terminal } from "@xterm/xterm";

	export class FitAddon implements ITerminalAddon {
		activate(terminal: Terminal): void;
		dispose(): void;
		fit(): void;
	}
}

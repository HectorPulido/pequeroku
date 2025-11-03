import { EventBus } from "./eventBus";

export type AlertVariant = "success" | "warning" | "error" | "info";

export interface AlertMessage {
	id: string;
	message: string;
	variant: AlertVariant;
	dismissible?: boolean;
}

const bus = new EventBus<AlertMessage | { id: string; dismiss: true }>();

export const alertStore = {
	subscribe: bus.subscribe.bind(bus),
	push(message: Omit<AlertMessage, "id">) {
		const alert: AlertMessage = {
			id: crypto.randomUUID(),
			...message,
		};
		bus.emit(alert);
		return alert.id;
	},
	dismiss(id: string) {
		bus.emit({ id, dismiss: true });
	},
};

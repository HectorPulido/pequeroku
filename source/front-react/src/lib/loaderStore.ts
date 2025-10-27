import { EventBus } from "./eventBus";

type LoaderEvent = { active: number };

const bus = new EventBus<LoaderEvent>();
let activeRequests = 0;

export const loaderStore = {
	subscribe: bus.subscribe.bind(bus),
	start() {
		activeRequests += 1;
		bus.emit({ active: activeRequests });
	},
	stop() {
		activeRequests = Math.max(0, activeRequests - 1);
		bus.emit({ active: activeRequests });
	},
};

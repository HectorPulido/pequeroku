import { installGlobalLoader } from "../core/loader.js";
import { setupContainers } from "./containers.js";
import { setupLogin } from "./login.js";

installGlobalLoader();
setupLogin({ onSuccess: () => setupContainers() });

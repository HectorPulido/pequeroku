/**
 * Shared constants for magic numbers and defaults across the frontend.
 *
 * Centralize all tunables here so they can be imported and used consistently.
 * This file should contain ONLY constants (no side effects).
 */

/**
 * Screen breakpoints and responsive values
 */
export const BREAKPOINTS = Object.freeze({
	mobileMaxWidth: 768,
});

/**
 * Default network/timeout configuration
 */
export const NETWORK = Object.freeze({
	// Generic fetch timeout (ms)
	fetchTimeoutMs: 8000,
});

/**
 * WebSocket reconnection/backoff parameters
 */
export const WS_BACKOFF = Object.freeze({
	// Initial delay before first reconnect attempt (ms)
	baseMs: 500,
	// Maximum delay cap (ms)
	maxMs: 8000,
});

/**
 * File system WebSocket (fs-ws) call timeouts and intervals
 */
export const FSWS = Object.freeze({
	// Timeout for a single RPC over fs-ws (ms)
	callTimeoutMs: 20000,
	// Timeout waiting for socket open before issuing a call (ms)
	openTimeoutMs: 20000,
	// Polling interval while waiting for socket to open (ms)
	waitOpenIntervalMs: 100,
	// TTL for directory cache in file tree (ms)
	dirTtlMs: 3000,
});

/**
 * Metrics/Charts configuration
 */
export const METRICS = Object.freeze({
	pollMs: 1000,
	maxPoints: 300,
});

/**
 * UI sizes and layout defaults
 */
export const UI_SIZES = Object.freeze({
	// Sidebar default width (px)
	sidebarDefaultWidth: 280,
	// Console default height (px)
	consoleDefaultHeight: 400,
	// Console minimum visible height when collapsed (px)
	consoleMinHeight: 50,
});

/**
 * Editor/Terminal defaults
 */
export const TERMINAL = Object.freeze({
	scrollback: 5000,
	fontSize: 13,
});

/**
 * Paths and well-known locations inside the container FS
 */
export const PATHS = Object.freeze({
	appRoot: "/app",
	runConfig: "/app/config.json",
});

/**
 * Actions that use sleeps/delays
 */
export const ACTION_DELAYS = Object.freeze({
	// Wait after starting a clone to allow FS to settle (ms)
	cloneRepoWaitMs: 5000,
});

/**
 * API base paths
 * Keep here if we need to swap/mount under a different prefix later.
 */
export const API_BASE = Object.freeze({
	root: "/api",
	containers: "/api/containers",
	templates: "/api/templates",
	aiGenerate: "/api/ai-generate/",
	templatesApplyAIGenerated: "/api/templates/apply_ai_generated_code/",
});

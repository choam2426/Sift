/**
 * Pi runner for the planted-defect experiment.
 *
 * The Pi process runs on the host because it must reach the model API. The
 * agent's only way to execute code is the `bash` tool below, which forwards
 * to the harness broker and therefore runs inside the case container (no
 * network, no Docker socket). File tools stay on the host but are confined
 * to the session workspace by the tool_call guard.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { truncateTail } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import * as fs from "node:fs";
import * as net from "node:net";
import * as path from "node:path";

const ROOT = process.cwd();
const SOCK = process.env.TB_SOCKET ?? "";
const REPO = process.env.PI_CASE_REPO ?? "";
const MAX_LINES = 2000;
const MAX_BYTES = 50 * 1024;

type BashDetails = {
	exit_code: number;
	truncated: boolean;
	wall_time_seconds: number;
};

function real(p: string): string | null {
	try {
		return fs.realpathSync(p);
	} catch {
		return null;
	}
}

function inside(root: string, target: string): boolean {
	const rel = path.relative(root, target);
	return rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel));
}

/** Return an error message when a file-tool path leaves the workspace. */
function outsideWorkspace(raw: unknown): string | null {
	const rel = typeof raw === "string" && raw.length > 0 ? raw : ".";
	const abs = path.resolve(ROOT, rel);
	const rootReal = real(ROOT) ?? ROOT;
	const targetReal = real(abs);
	if (targetReal) {
		return inside(rootReal, targetReal) ? null : `path is outside the workspace: ${abs}`;
	}
	// A write to a new path: check the nearest existing ancestor.
	let parent = path.dirname(abs);
	while (!fs.existsSync(parent) && parent !== path.dirname(parent)) parent = path.dirname(parent);
	const parentReal = real(parent);
	if (parentReal && !inside(rootReal, parentReal)) {
		return `path is outside the workspace: ${abs}`;
	}
	return null;
}

/** Translate the task's host-side paths and ./tb wrapper to the container view. */
function translate(command: string): string {
	let c = command;
	c = c.replace(/(^|[;&|]\s*)\.\/tb\s+test\b/g, "$1go test");
	c = c.replace(/(^|[;&|]\s*)\.\/tb\s+build\b/g, "$1go test -run '^$'");
	c = c.replace(/(^|[;&|]\s*)\.\/tb\s+exec\b/g, "$1");
	if (REPO) {
		const repo = REPO.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
		// Translate host-relative src/<repo> paths, but not container-absolute /src/<repo>.
		c = c.replace(new RegExp(`(^|[^\\w/])(?:\\./)?src/${repo}(?=/|\\b)`, "g"), "$1.");
	}
	c = c.replace(/(^|[^\w/])scratch(\/|\b)/g, "$1/scratch$2");
	return c;
}

function truncate(text: string): string {
	return truncateTail(text, { maxLines: MAX_LINES, maxBytes: MAX_BYTES }).content;
}

/** Build caches and compiled artifacts are not evidence; reading them wastes budget. */
function blockedCommand(command: string): string | null {
	if (/(^|[^\w])(?:\/gocache|\/go\/pkg\/mod)(?:\/|\b)/.test(command)) {
		return "build caches and module caches are not evidence; read the source instead";
	}
	return null;
}

function runBroker(
	command: string,
	signal: AbortSignal | undefined,
	onUpdate?: (text: string) => void,
): Promise<{ output: string; details: BashDetails }> {
	return new Promise((resolve) => {
		const started = Date.now();
		let output = "";
		let buffer = "";
		let exitCode: number | null = null;
		let settled = false;
		let lastUpdate = 0;
		const conn = net.createConnection({ path: SOCK });

		const finish = (code: number) => {
			if (settled) return;
			settled = true;
			conn.destroy();
			const cut = truncateTail(output, { maxLines: MAX_LINES, maxBytes: MAX_BYTES });
			resolve({
				output,
				details: {
					exit_code: code,
					truncated: cut.truncated,
					wall_time_seconds: Math.round((Date.now() - started) / 1000),
				},
			});
		};

		const emit = (force = false) => {
			if (!onUpdate) return;
			const now = Date.now();
			if (!force && now - lastUpdate < 150) return;
			lastUpdate = now;
			onUpdate(truncate(output));
		};

		signal?.addEventListener("abort", () => finish(130), { once: true });
		conn.on("connect", () => {
			conn.write(JSON.stringify({ argv: ["exec", "sh", "-c", command] }) + "\n");
		});
		conn.on("data", (chunk) => {
			buffer += chunk.toString();
			for (;;) {
				const nl = buffer.indexOf("\n");
				if (nl < 0) break;
				const line = buffer.slice(0, nl);
				buffer = buffer.slice(nl + 1);
				let msg: { o?: string; exit?: number };
				try {
					msg = JSON.parse(line);
				} catch {
					continue;
				}
				if (typeof msg.o === "string") {
					output += msg.o;
					emit();
				}
				if (typeof msg.exit === "number") {
					exitCode = msg.exit;
					emit(true);
					finish(exitCode);
					return;
				}
			}
		});
		conn.on("error", () => finish(exitCode ?? 1));
		conn.on("close", () => finish(exitCode ?? 1));
	});
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event) => {
		if (!["read", "write", "edit", "grep", "find", "ls"].includes(event.toolName)) return;
		const input = event.input as { path?: unknown } | undefined;
		const bad = outsideWorkspace(input?.path);
		if (bad) return { block: true, reason: bad };
	});

	pi.registerTool({
		name: "bash",
		label: "bash (case container)",
		description:
			"Run a shell command inside the isolated case container. The current directory is the module root; the container has no network and no Docker socket. `./tb test|build|exec` is translated to the equivalent go command.",
		promptSnippet: "Run a shell command in the isolated case container",
		promptGuidelines: [
			"Use bash to run tests and inspect source inside the case container; its current directory is the module root.",
			"The container has no network; do not try to fetch external information.",
		],
		parameters: Type.Object({
			command: Type.String({ description: "Shell command to execute in the case container" }),
		}),
		async execute(_toolCallId, params, signal, onUpdate) {
			if (!SOCK) throw new Error("TB_SOCKET is not set");
			const blocked = blockedCommand(params.command);
			if (blocked) throw new Error(blocked);
			const command = translate(params.command);
			const { output, details } = await runBroker(command, signal, (text) =>
				onUpdate?.({
					content: [{ type: "text", text }],
					details: { exit_code: 0, truncated: true, wall_time_seconds: 0 },
				}),
			);
			const text = truncate(output);
			return {
				content: [{ type: "text", text }],
				details,
				structuredContent: {
					output: text,
					truncated: details.truncated,
					exit_code: details.exit_code,
					wall_time_seconds: details.wall_time_seconds,
				},
				isError: details.exit_code !== 0,
			};
		},
	});
}

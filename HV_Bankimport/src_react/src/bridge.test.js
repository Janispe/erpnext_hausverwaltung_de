import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let receive, host, rpc;

beforeEach(async () => {
	vi.resetModules();
	vi.useFakeTimers();
	host = { postMessage: vi.fn() };
	vi.stubGlobal("window", {
		parent: host,
		location: { origin: "https://hv.example" },
		addEventListener: (type, handler) => { if (type === "message") receive = handler; },
	});
	({ rpc } = await import("./bridge.js"));
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

function reply(overrides = {}) {
	const request = host.postMessage.mock.calls[0][0];
	receive({
		source: host,
		origin: "https://hv.example",
		data: { source: "hv-bankimport-host", type: "rpc-result", id: request.id, ok: true, data: { ok: true } },
		...overrides,
	});
}

describe("bankimport RPC replies", () => {
	it("accepts the same-origin parent response", async () => {
		const pending = rpc("reconcile", { docname: "IMPORT-1" });
		expect(host.postMessage.mock.calls[0][1]).toBe("https://hv.example");
		reply();
		await expect(pending).resolves.toEqual({ ok: true });
	});

	it.each([
		["another window on the same origin", () => ({ source: {} })],
		["a parent navigated to another origin", () => ({ origin: "https://untrusted.example" })],
	])("ignores a forged success reply from %s", async (_, eventOverrides) => {
		const resolved = vi.fn();
		const pending = rpc("reconcile").then(resolved);
		reply(eventOverrides());
		await Promise.resolve();
		expect(resolved).not.toHaveBeenCalled();
		reply();
		await pending;
		expect(resolved).toHaveBeenCalledTimes(1);
		expect(resolved).toHaveBeenCalledWith({ ok: true });
	});

	it("does not let an untrusted reply consume the pending request", async () => {
		const pending = rpc("reconcile");
		reply({ source: {} });
		const request = host.postMessage.mock.calls[0][0];
		reply({ data: { source: "hv-bankimport-host", type: "rpc-result", id: request.id, ok: false, error: "Buchung fehlgeschlagen" } });
		await expect(pending).rejects.toThrow("Buchung fehlgeschlagen");
	});
});

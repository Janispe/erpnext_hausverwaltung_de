// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DistinctPaymentConfirmation } from "./MatchPanel.jsx";
import * as api from "../api.js";

vi.mock("../api.js", async (original) => ({ ...await original(), confirmDistinctPayment: vi.fn() }));

it("requires confirmation and sends the observed duplicate for retry protection", async () => {
	globalThis.IS_REACT_ACT_ENVIRONMENT = true;
	const container = document.createElement("div");
	const root = createRoot(container);
	const done = vi.fn();
	api.confirmDistinctPayment.mockResolvedValue({ ok: true });
	try {
		await act(async () => root.render(<DistinctPaymentConfirmation docname="IMP" row={{ id: "ROW", bankTransaction: "BT-OLD" }} onActionDone={done} notify={vi.fn()} />));
		const button = container.querySelector("button");
		expect(button.disabled).toBe(true);
		await act(async () => button.click());
		expect(api.confirmDistinctPayment).not.toHaveBeenCalled();
		await act(async () => container.querySelector("input").click());
		expect(button.disabled).toBe(false);
		await act(async () => button.click());
		expect(api.confirmDistinctPayment).toHaveBeenCalledWith("IMP", "ROW", "BT-OLD");
		expect(done).toHaveBeenCalledWith({ advance: false });
	} finally {
		await act(async () => root.unmount());
	}
});

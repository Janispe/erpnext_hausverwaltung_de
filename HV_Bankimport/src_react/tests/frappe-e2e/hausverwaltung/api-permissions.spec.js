import { apiPost, expect, test } from "./frappe.js";

const processApi = "process_engine.process_engine.doctype.prozess_instanz.prozess_instanz";

test("Prozess-API lehnt unbekannte Instanzen und Prozesstypen ab", async ({ desk }) => {
	const docname = "NONEXISTENT-PROCESS-HV-E2E";
	for (const [method, args] of [
		["get_completion_blockers", { docname }],
		["get_seed_tasks_preview", { prozess_typ: docname }],
		["dispatch_workflow_action", { docname, action: "noop" }],
		["get_task_action_dialog", { docname, row_name: "NONEXISTENT-ROW", action_key: "noop" }],
	]) {
		const response = await apiPost(desk, `${processApi}.${method}`, args);
		expect([404, 417], method).toContain(response.status());
	}
});

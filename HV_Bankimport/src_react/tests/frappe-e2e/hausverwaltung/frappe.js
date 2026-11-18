import { expect, test as base } from "@playwright/test";
import { execFileSync } from "node:child_process";

const benchDir = "/home/frappe/frappe-bench";
const site = process.env.FRAPPE_SITE;
export const fixtures = "hausverwaltung.cypress_fixtures";

export function benchExecute(method, args = [], kwargs = {}) {
	const { DOCKER_CONTEXT, FRAPPE_BACKEND_CONTAINER } = process.env;
	if (!site || !FRAPPE_BACKEND_CONTAINER || !DOCKER_CONTEXT) {
		throw new Error("Run against the isolated Frappe site via scripts/agent_ci.sh --e2e.");
	}
	const command = [
		"--context", DOCKER_CONTEXT, "exec", "-w", benchDir, FRAPPE_BACKEND_CONTAINER,
		"bench", "--site", site, "execute", method, "--args", JSON.stringify(args),
		"--kwargs", JSON.stringify(kwargs),
	];
	try {
		const output = execFileSync("docker", command, {
			encoding: "utf8", timeout: 60_000, stdio: ["ignore", "pipe", "pipe"],
		}).trim();
		return output ? JSON.parse(output.split("\n").at(-1)) : null;
	} catch (error) {
		throw new Error(`Bench fixture ${method} failed: ${error.stderr || error.stdout || error.message}`, { cause: error });
	}
}

export const test = base.extend({
	siteProbe: [async ({}, use) => {
		await use(benchExecute(`${fixtures}.create_e2e_browser_probe`).probe);
	}, { scope: "worker" }],
	desk: async ({ page, baseURL, siteProbe }, use) => {
		if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(baseURL || "")) {
			throw new Error("The Hausverwaltung E2E tests require an isolated loopback site.");
		}
		const verified = await page.request.post(`/api/method/${fixtures}.check_e2e_browser_target`, {
			data: { probe: siteProbe },
			maxRedirects: 0,
		});
		expect(verified.ok(), "Browser und Bench müssen dieselbe Wegwerf-Testsite verwenden.").toBe(true);
		expect((await verified.json()).message).toBe(true);
		const response = await page.request.post("/api/method/login", {
			form: { usr: "Administrator", pwd: process.env.FRAPPE_PASSWORD || "admin" },
		});
		expect(response.ok()).toBe(true);
		await page.goto("/app");
		await page.waitForFunction(() => window.frappe?.csrf_token && window.frappe?.set_route);
		await use(page);
	},
});

export { expect };

export function dialog(page) {
	return page.locator(".modal:visible").last();
}

export function visiblePage(page) {
	return page.locator(".page-container:visible").last();
}

export async function openList(page, doctype) {
	await page.evaluate((dt) => { frappe.set_route("List", dt); }, doctype);
	await expect(visiblePage(page).locator(".frappe-list")).toBeVisible();
}

export async function openForm(page, doctype, name) {
	await page.evaluate(({ doctype, name }) => {
		if (name) frappe.set_route("Form", doctype, name);
		else frappe.new_doc(doctype);
	}, { doctype, name });
	await page.waitForFunction(({ doctype, name }) => {
		const doc = window.cur_frm?.doc;
		return doc?.doctype === doctype && (name ? doc.name === name : doc.__islocal);
	}, { doctype, name });
}

export function formDoc(page) {
	return page.evaluate(() => cur_frm.doc);
}

export function setFormValues(page, values) {
	return page.evaluate((values) => cur_frm.set_value(values), values);
}

export async function apiPost(page, method, data = {}) {
	return page.request.post(`/api/method/${method}`, {
		data,
		headers: { "X-Frappe-CSRF-Token": await page.evaluate(() => frappe.csrf_token) },
	});
}

export async function actionResponse(page, method, action) {
	const [response] = await Promise.all([
		page.waitForResponse((response) => response.request().method() === "POST" &&
			new URL(response.url()).pathname === `/api/method/${method}`),
		action(),
	]);
	return response;
}

export const saveMethod = "frappe.desk.form.save.savedocs";

export async function saveForm(page) {
	const response = await actionResponse(page, saveMethod, () => page.evaluate(() => {
		cur_frm.save();
	}));
	expect(response.ok(), await response.text()).toBe(true);
	await page.waitForFunction(() => cur_frm.doc.name && !cur_frm.doc.__islocal && !cur_frm.doc.__unsaved);
}

export async function call(page, method, data) {
	const response = await apiPost(page, method, data);
	expect(response.ok(), await response.text()).toBe(true);
	return (await response.json()).message;
}

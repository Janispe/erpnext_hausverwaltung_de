const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "mahn-data-adapter.js"), "utf8"), sandbox);
const { recommendationFor, templateAfterSelection, createSubmissionGate } = sandbox.window.MAHN_ADAPTER;
const fallback = (stage) => `stage_${Math.min(4, stage + 1)}`;
const tenant = {
  mahnstufe: 3,
  empf_vorlage: "stage_4",
  posten: [
    { beleg: "NEW", mahnstufe: 0, empf_vorlage: "stage_1" },
    { beleg: "OLD", mahnstufe: 3, empf_vorlage: "stage_4" },
  ],
};

test("selecting only new debt ignores a higher stage on an unselected invoice", () => {
  const result = recommendationFor(tenant, new Set(["NEW"]), fallback);
  assert.equal(result.mahnstufe, 0);
  assert.equal(result.vorlageKey, "stage_1");
});

test("adding and removing an escalated invoice updates the automatic recommendation", () => {
  let selected = new Set(["NEW"]);
  let current = recommendationFor(tenant, selected, fallback).vorlageKey;
  selected.add("OLD");
  current = templateAfterSelection(current, recommendationFor(tenant, selected, fallback).vorlageKey, false);
  assert.equal(current, "stage_4");
  selected.delete("OLD");
  current = templateAfterSelection(current, recommendationFor(tenant, selected, fallback).vorlageKey, false);
  assert.equal(current, "stage_1");
});

test("a deliberately chosen template survives subsequent selection changes", () => {
  const recommended = recommendationFor(tenant, new Set(["NEW"]), fallback).vorlageKey;
  assert.equal(templateAfterSelection("custom_template", recommended, true), "custom_template");
  assert.equal(templateAfterSelection("custom_template", recommended, false), "stage_1");
});

test("an empty selection does not inherit the customer's highest stage", () => {
  const result = recommendationFor(tenant, new Set(), fallback);
  assert.equal(result.mahnstufe, 0);
  assert.equal(result.vorlageKey, "stage_1");
});

test("legacy mock data retains its existing tenant recommendation", () => {
  const result = recommendationFor({ mahnstufe: 1, empf_vorlage: "legacy", posten: [{ beleg: "A" }] }, new Set(["A"]), fallback);
  assert.equal(result.vorlageKey, "legacy");
});

test("concurrent submit clicks create only one letter until its request settles", async () => {
  const submit = createSubmissionGate();
  const busy = [];
  let finish;
  let created = 0;
  const action = () => {
    created++;
    return new Promise((resolve) => { finish = resolve; });
  };
  const first = submit(action, (value) => busy.push(value));
  await submit(action, (value) => busy.push(value));
  assert.equal(created, 1);
  assert.deepEqual(busy, [true]);
  finish("DUN-1");
  assert.equal(await first, "DUN-1");
  assert.deepEqual(busy, [true, false]);
});

test("failed submission releases the gate for a deliberate retry", async () => {
  const submit = createSubmissionGate();
  const busy = [];
  await assert.rejects(submit(async () => { throw new Error("failed"); }, (value) => busy.push(value)), /failed/);
  assert.equal(await submit(async () => "DUN-RETRY", (value) => busy.push(value)), "DUN-RETRY");
  assert.deepEqual(busy, [true, false, true, false]);
});

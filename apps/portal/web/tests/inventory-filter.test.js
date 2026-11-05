import test from "node:test";
import assert from "node:assert/strict";
import { filterSandboxes, inventoryProfiles } from "../inventory-filter.js";

const rows = [
  {id:"one",title:"Frontend",owner:"alice@example.com",namespace:"ns-a",profile:{id:"engineering",title:"Engineering",revision:"sha256:first"}},
  {id:"two",title:"Agent work",owner:"bob@example.com",namespace:"ns-b",profile:{id:"claude",title:"Claude",revision:"sha256:second"}},
  {id:"three",title:"Imported workspace",owner:"alice@example.com",namespace:"ns-c",profile:null},
];

test("profile filter uses an exact profile ID and composes with text search", () => {
  assert.deepEqual(filterSandboxes(rows,"","engineering"), [rows[0]]);
  assert.deepEqual(filterSandboxes(rows," ALICE ","engineering"), [rows[0]]);
  assert.deepEqual(filterSandboxes(rows,"bob","engineering"), []);
  assert.deepEqual(filterSandboxes(rows,"","engineer"), []);
});

test("unassigned and all-profile filters handle sandboxes without profiles", () => {
  assert.deepEqual(filterSandboxes(rows,"","__unassigned__"), [rows[2]]);
  assert.deepEqual(filterSandboxes(rows), rows);
  assert.deepEqual(filterSandboxes(rows,"sha256:SECOND"), [rows[1]]);
});

test("profile choices include retained profiles removed from the catalog without duplicates", () => {
  assert.deepEqual(inventoryProfiles([{id:"engineering",title:"Engineering"}], rows), [
    {id:"",title:"All profiles"}, {id:"__unassigned__",title:"No profile"},
    {id:"claude",title:"Claude"}, {id:"engineering",title:"Engineering"},
  ]);
});

test("an empty inventory retains catalog choices without inventing an unassigned category", () => {
  assert.deepEqual(inventoryProfiles([{id:"engineering",title:"Engineering"}], []), [
    {id:"",title:"All profiles"}, {id:"engineering",title:"Engineering"},
  ]);
});

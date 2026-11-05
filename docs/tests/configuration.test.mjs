import { test } from "node:test";
import assert from "node:assert/strict";
import {
  catalog,
  scopes,
  searchEntries,
} from "../src/components/configuration/reference.mjs";

test("every exported setting has an explanation and ownership/enforcement group", () => {
  for (const scope of Object.keys(scopes)) {
    const entries = catalog(scope);
    assert.ok(entries.length);
    assert.equal(
      new Set(entries.map((entry) => entry.path)).size,
      entries.length,
    );
    for (const entry of entries) {
      assert.ok(entry.summary, `${scope}:${entry.path} needs documentation`);
      assert.ok(entry.section, `${scope}:${entry.path} needs a section`);
      for (const key of ["owner", "enforcement", "editing", "changes"])
        assert.ok(entry.section[key], `${entry.path}:${key}`);
    }
  }
});

test("search reaches security identity, helper probes, portal limits and generated IDs", () => {
  assert.ok(
    searchEntries("deployment", "UID").some(
      (entry) => entry.path === "settings.sandboxSecurityContext.runAsUser",
    ),
  );
  assert.ok(
    searchEntries("profile", "signed out").some(
      (entry) => entry.path === "helpers[].status.signed_out_exit_codes",
    ),
  );
  assert.ok(
    searchEntries("deployment", "sandbox count").some(
      (entry) => entry.path === "settings.maxSandboxesPerUser",
    ),
  );
  assert.ok(
    searchEntries("state", "UUID").some((entry) => entry.path === "record.id"),
  );
  assert.ok(
    searchEntries("environment", "Secret reference").some(
      (entry) => entry.path === "PORTAL_SESSION_SECRET",
    ),
  );
  assert.deepEqual(searchEntries("profile", "nonexistent-value-93825"), []);
});

test("unsupported features and environment-specific overrides remain explicit", () => {
  const profile = catalog("profile");
  assert.match(
    profile.find((entry) => entry.path === "envoyEgress").summary,
    /rejected/,
  );
  const settings = catalog("deployment");
  assert.equal(
    settings.find((entry) => entry.path === "auth.oidc.session_seconds")
      .default,
    3600,
  );
  assert.equal(
    settings.find((entry) => entry.path === "settings.maxSandboxesPerUser")
      .default,
    0,
  );
  assert.equal(
    settings.find(
      (entry) => entry.path === "namespacePolicy.baselineNetworkPolicy",
    ).default,
    false,
  );
  assert.deepEqual(
    profile.find((entry) => entry.path === "ui.resources.default.requests.cpu")
      .type,
    ["string", "integer", "number"],
  );
  assert.ok(
    settings.some(
      (entry) =>
        entry.path === "podDisruptionBudget.maxUnavailable" &&
        !Object.hasOwn(entry, "default"),
    ),
  );
});

test("command execution and portal-only probe interpretation have different consumers", () => {
  const profile = catalog("profile");
  assert.ok(
    profile
      .find((entry) => entry.path === "helpers[].status.command")
      .section.readers.includes("guest"),
  );
  assert.ok(
    !profile
      .find((entry) => entry.path === "helpers[].status.signed_out_exit_codes")
      .section.readers.includes("guest"),
  );
  assert.ok(
    !profile
      .find((entry) => entry.path === "agentSandbox.spec")
      .section.readers.includes("openshell"),
  );
});

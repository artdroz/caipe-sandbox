import { test } from "node:test";
import assert from "node:assert/strict";
import {
  modules,
  zones,
  components,
  connections,
  groups,
  makeCodeMap,
  normalizeCodeMap,
  readCodeMap,
  codeMapSearch,
} from "../src/components/codemap/model.mjs";

test("component map has valid graph endpoints and explains every source responsibility", () => {
  const model = makeCodeMap();
  const ids = new Set(components.map((item) => item.id));
  assert.equal(ids.size, components.length);
  assert.equal(
    new Set(connections.map((item) => item.id)).size,
    connections.length,
  );
  const files = new Set();
  for (const item of components) {
    assert.ok(zones[item.zone]);
    assert.ok(item.summary && item.handles.length && item.boundary);
    assert.ok(item.files.length || item.external);
    assert.ok(
      item.x >= 0 &&
        item.y >= 0 &&
        item.x + item.w <= model.width &&
        item.y + item.h <= model.height,
    );
    for (const id of item.files) {
      assert.ok(modules[id], id);
      files.add(id);
    }
    assert.ok(
      connections.some((edge) => edge.from === item.id || edge.to === item.id),
      item.id,
    );
  }
  assert.deepEqual([...files].sort(), Object.keys(modules).sort());
  for (const edge of connections) {
    assert.ok(ids.has(edge.from) && ids.has(edge.to), edge.id);
    assert.ok(edge.label && edge.labelAt);
  }
});
test("portal abstractions remain in one process and native implementations stay outside it", () => {
  for (const group of groups) {
    for (const item of components.filter((node) => node.zone === group.id)) {
      assert.ok(
        item.x >= group.x &&
          item.y >= group.y + 45 &&
          item.x + item.w <= group.x + group.w &&
          item.y + item.h <= group.y + group.h,
        item.id,
      );
    }
  }
  assert.equal(
    components.find((node) => node.id === "adapters").zone,
    "portal",
  );
  assert.equal(
    components.find((node) => node.id === "execution").zone,
    "portal",
  );
  assert.equal(components.filter((node) => node.zone === "native").length, 1);
  assert.equal(
    components.find((node) => node.id === "sandbox-provider").title,
    "Sandbox Provider",
  );
  for (const id of ["execution", "admin-worker"])
    assert.equal(components.find((node) => node.id === id).zone, "portal");
  assert.equal(
    components.find((node) => node.id === "database").zone,
    "persistence",
  );
  const portal = groups.find((group) => group.id === "portal");
  const workload = groups.find((group) => group.id === "microvm");
  const gap = workload.x - portal.x - portal.w;
  assert.ok(gap >= 35 && gap <= 60);
  assert.equal(portal.title, "Portal / Controller");
  assert.equal(
    components.find((node) => node.id === "sandbox-provider").zone,
    "native",
  );
  assert.ok(
    components.every((node) => !["runner", "omnigent"].includes(node.id)),
  );
  assert.ok(
    components.every(
      (node) => !JSON.stringify(node).toLowerCase().includes("omnigent"),
    ),
  );
});
test("connections attach to component boundaries and avoid unrelated boxes", () => {
  for (const edge of connections) {
    for (const [id, [x, y]] of [
      [edge.from, edge.points[0]],
      [edge.to, edge.points.at(-1)],
    ]) {
      const node = components.find((item) => item.id === id);
      assert.ok(
        ((x === node.x || x === node.x + node.w) &&
          y >= node.y &&
          y <= node.y + node.h) ||
          ((y === node.y || y === node.y + node.h) &&
            x >= node.x &&
            x <= node.x + node.w),
        `${edge.id} detached from ${id}`,
      );
    }
    for (const node of components.filter(
      (item) => item.id !== edge.from && item.id !== edge.to,
    )) {
      for (let i = 1; i < edge.points.length; i++) {
        const [a, b] = [edge.points[i - 1], edge.points[i]];
        const vertical =
          a[0] === b[0] &&
          a[0] > node.x &&
          a[0] < node.x + node.w &&
          Math.max(a[1], b[1]) > node.y &&
          Math.min(a[1], b[1]) < node.y + node.h;
        const horizontal =
          a[1] === b[1] &&
          a[1] > node.y &&
          a[1] < node.y + node.h &&
          Math.max(a[0], b[0]) > node.x &&
          Math.min(a[0], b[0]) < node.x + node.w;
        assert.ok(!vertical && !horizontal, `${edge.id} crosses ${node.id}`);
      }
    }
  }
});
test("component links round-trip and obsolete walkthrough links fall back safely", () => {
  for (const component of components) {
    const state = { component: component.id };
    assert.deepEqual(readCodeMap(codeMapSearch(state)), state);
  }
  assert.deepEqual(readCodeMap("?component=agent-sandbox"), {
    component: "sandbox-provider",
  });
  assert.deepEqual(readCodeMap("?component=openshell"), {
    component: "sandbox-provider",
  });
  assert.deepEqual(readCodeMap("?component=runner"), { component: "store" });
  assert.deepEqual(normalizeCodeMap({ component: "missing" }), {
    component: "store",
  });
  assert.deepEqual(
    readCodeMap("?task=terminal&runtime=openshell&step=adapter"),
    { component: "store" },
  );
});

test("worker responsibilities match the reference task lifecycle and database scope", () => {
  const execution = components.find((node) => node.id === "execution");
  assert.ok(!components.some((node) => node.id === "terminal-worker"));
  const terminal = execution.terminalWorker;
  assert.ok(terminal.summary && terminal.handles.length && terminal.boundary);
  assert.ok(
    execution.files.includes("terminal") && execution.files.includes("app"),
  );
  assert.deepEqual(readCodeMap("?component=terminal-worker"), {
    component: "execution",
  });
  const admin = components.find((node) => node.id === "admin-worker");
  assert.deepEqual(terminal.worker.tasks, [
    "output()",
    "input()",
    "revalidate()",
  ]);
  assert.equal(terminal.worker.kind, "connection-tasks");
  assert.equal(admin.worker.kind, "periodic-task");
  assert.equal(admin.worker.delaySeconds, 10);
  assert.equal(admin.worker.condition, "admins or deleteWhenEmpty");
  assert.equal(admin.worker.offload, "asyncio.to_thread");
  assert.equal(terminal.worker.offload, "asyncio.to_thread");
  assert.ok(
    terminal.files.includes("app") && terminal.files.includes("terminal"),
  );
  assert.ok(admin.files.includes("app") && admin.files.includes("management"));
  const database = components.find((node) => node.id === "database");
  assert.deepEqual(database.files, []);
  assert.equal(database.sourceHeading, "Backing store");
  for (const id of ["gates", "database"]) {
    const edge = connections.find((item) => item.id === id);
    assert.equal(edge.bidirectional, true);
    assert.ok(edge.label.includes("Read / write"));
  }
  const storage = components.find((node) => node.id === "metadata");
  assert.deepEqual(storage.files, [
    "controls",
    "storage",
    "database",
    "sql",
    "migrations",
  ]);
  assert.ok(
    connections.some(
      (edge) => edge.from === "metadata" && edge.to === "database",
    ),
  );
  assert.deepEqual(readCodeMap("?component=runtime-provider"), {
    component: "sandbox-provider",
  });
});

test("organized connection routes have no crossings between unrelated segments", () => {
  for (let i = 0; i < connections.length; i++) {
    for (let j = i + 1; j < connections.length; j++) {
      const a = connections[i],
        b = connections[j];
      for (let n = 1; n < a.points.length; n++) {
        for (let m = 1; m < b.points.length; m++) {
          const [p, q, r, s] = [
            a.points[n - 1],
            a.points[n],
            b.points[m - 1],
            b.points[m],
          ];
          const verticalA = p[0] === q[0],
            verticalB = r[0] === s[0];
          if (verticalA === verticalB) continue;
          const [u, v, h, k] = verticalA ? [p, q, r, s] : [r, s, p, q];
          const crosses =
            u[0] > Math.min(h[0], k[0]) &&
            u[0] < Math.max(h[0], k[0]) &&
            h[1] > Math.min(u[1], v[1]) &&
            h[1] < Math.max(u[1], v[1]);
          assert.ok(!crosses, `${a.id} crosses ${b.id}`);
        }
      }
    }
  }
});

test("profile data flows into sandbox management and connection labels describe the returned binding", () => {
  const profile = connections.find((edge) => edge.id === "profile");
  assert.equal(profile.from, "profiles");
  assert.equal(profile.to, "store");
  assert.equal(profile.label, "Profile data");
  assert.equal(
    components.find((node) => node.id === "store").title,
    "Sandbox management",
  );
  assert.equal(
    components.find((node) => node.id === "metadata").title,
    "State / Metadata storage",
  );
  for (const id of ["target"]) {
    const edge = connections.find((item) => item.id === id);
    assert.equal(edge.from, "store");
    assert.equal(edge.label, "Connection info");
  }
});

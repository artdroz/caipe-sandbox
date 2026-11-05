import { test } from "node:test";
import assert from "node:assert/strict";
import {
  integrations,
  requiredIntegrations,
  initialSelection,
  interactions,
  groupInteractions,
  available,
  normalizePlayground,
  readPlayground,
  playgroundSearch,
  makePlayground,
  describeInteraction,
} from "../src/components/architecture/playground-model.mjs";

const combinations = Array.from(
  { length: 2 ** integrations.length },
  (_, mask) => integrations.filter((_, i) => mask & (1 << i)).map((i) => i.id),
);
test("every integration combination and enabled interaction has complete paths and valid graph endpoints", () => {
  for (const selection of combinations)
    for (const action of interactions.filter((a) => available(a, selection))) {
      const model = makePlayground({
          integrations: selection,
          interaction: action.id,
        }),
        ids = new Set(model.nodes.map((n) => n.id)),
        edgeIds = new Set(model.edges.map((e) => e.id));
      assert.equal(ids.size, model.nodes.length);
      assert.equal(edgeIds.size, model.edges.length);
      for (const edge of model.edges) {
        assert.ok(ids.has(edge.from), edge.id);
        assert.ok(ids.has(edge.to), edge.id);
      }
      for (const id of model.activeEdges)
        assert.ok(edgeIds.has(id), `${selection}/${action.id}: ${id}`);
      for (const node of model.nodes)
        assert.ok(
          node.x >= 0 &&
            node.y >= 0 &&
            node.x + node.w <= model.width &&
            node.y + node.h <= model.height,
          node.id,
        );
    }
});
test("optional integrations disappear from topology; OpenShell replaces direct exec", () => {
  for (const selection of combinations) {
    const model = makePlayground({ integrations: selection });
    const has = (id) => model.nodes.some((n) => n.id === id);
    assert.equal(has("omniHost"), selection.includes("omnigent"));
    assert.equal(has("omniUI"), selection.includes("omnigent"));
    assert.equal(has("gateway"), selection.includes("openshell"));
    assert.equal(has("supervisor"), selection.includes("openshell"));
    assert.equal(
      model.edges.some((e) => e.id === "direct-exec"),
      !selection.includes("openshell"),
    );
  }
});
test("general architecture shows the host-tunnel connection without a registration walkthrough", () => {
  const model = makePlayground({
    integrations: ["omnigent"],
    interaction: "overview",
  });
  const edge = model.edges.find((e) => e.id === "host-tunnel");
  assert.equal(edge.from, "omniHost");
  assert.equal(edge.to, "omniServer");
  assert.ok(model.activeEdges.includes(edge.id));
  assert.equal(model.activeEdges.includes("omni-commands"), false);
  assert.deepEqual(describeInteraction(model.state).steps, []);
  assert.deepEqual(model.nodes.find((n) => n.id === "omniServer").ports, [
    "Web / session API",
    "Host-tunnel endpoint",
  ]);
});
test("Omnigent UI sign-in never activates host registration or workspace execution", () => {
  const model = makePlayground({
    integrations: ["omnigent", "openshell"],
    interaction: "omni-signin",
  });
  assert.deepEqual(model.activeEdges, ["omni-browser"]);
  assert.ok(!model.activeEdges.includes("host-tunnel"));
});
test("Omnigent UI work uses its existing host tunnel rather than the portal exec or gateway bridge", () => {
  for (const selection of [["omnigent"], ["omnigent", "openshell"]]) {
    const model = makePlayground({
      integrations: selection,
      interaction: "omni-work",
    });
    assert.deepEqual(model.activeEdges, [
      "omni-browser",
      "omni-commands",
      "host-process",
    ]);
    assert.ok(!model.activeEdges.includes("portal-request"));
    assert.ok(!model.activeEdges.includes("protected-exec"));
    assert.ok(!model.activeEdges.includes("direct-exec"));
  }
});
test("removing a required integration resets the interaction and URLs round-trip including an empty selection", () => {
  assert.equal(
    normalizePlayground({ integrations: [], interaction: "omni-work" })
      .interaction,
    "overview",
  );
  for (const selection of combinations) {
    const state = normalizePlayground({
      integrations: selection,
      interaction: "overview",
    });
    assert.deepEqual(readPlayground(playgroundSearch(state)), state);
  }
  assert.deepEqual(
    readPlayground("?workload=both&execution=openshell&flow=terminal"),
    {
      integrations: ["omnigent", "openshell"],
      interaction: "portal-terminal",
    },
  );
  assert.deepEqual(
    normalizePlayground({ integrations: ["fake"], interaction: "fake" }),
    { integrations: [], interaction: "overview" },
  );
});

test("connection segments do not pass through unrelated component cards", () => {
  for (const selection of combinations) {
    for (const action of interactions.filter((a) => available(a, selection))) {
      const model = makePlayground({
        integrations: selection,
        interaction: action.id,
      });
      for (const edge of model.edges) {
        for (const node of model.nodes.filter(
          (n) => n.id !== edge.from && n.id !== edge.to,
        )) {
          for (let index = 1; index < edge.points.length; index++) {
            const [a, b] = [edge.points[index - 1], edge.points[index]];
            const hitVertical =
              a[0] === b[0] &&
              a[0] > node.x + 1 &&
              a[0] < node.x + node.w - 1 &&
              Math.max(a[1], b[1]) > node.y + 1 &&
              Math.min(a[1], b[1]) < node.y + node.h - 1;
            const hitHorizontal =
              a[1] === b[1] &&
              a[1] > node.y + 1 &&
              a[1] < node.y + node.h - 1 &&
              Math.max(a[0], b[0]) > node.x + 1 &&
              Math.min(a[0], b[0]) < node.x + node.w - 1;
            assert.ok(
              !hitVertical && !hitHorizontal,
              `${selection}/${action.id}: ${edge.id} crosses ${node.id}`,
            );
          }
        }
      }
    }
  }
});

test("routes use at most three turns and keep all endpoints attached to their cards", () => {
  for (const selection of combinations) {
    for (const action of interactions.filter((a) => available(a, selection))) {
      const model = makePlayground({
        integrations: selection,
        interaction: action.id,
      });
      for (const edge of model.edges) {
        assert.ok(edge.points.length <= 5, edge.id);
        for (const [id, point] of [
          [edge.from, edge.points[0]],
          [edge.to, edge.points.at(-1)],
        ]) {
          const n = model.nodes.find((node) => node.id === id);
          const [x, y] = point;
          assert.ok(
            ((x === n.x || x === n.x + n.w) && y >= n.y && y <= n.y + n.h) ||
              ((y === n.y || y === n.y + n.h) && x >= n.x && x <= n.x + n.w),
            `${edge.id} is detached from ${id}`,
          );
        }
      }
    }
  }
});

test("retired CAIPE bookmarks normalize without restoring removed components or interactions", () => {
  const state = readPlayground(
    "?integrations=caipe,omnigent,openshell&interaction=caipe-use",
  );
  assert.deepEqual(state, {
    integrations: ["omnigent", "openshell"],
    interaction: "overview",
  });
  const model = makePlayground(state);
  assert.ok(model.nodes.every((node) => !node.id.startsWith("caipe")));
  assert.ok(model.edges.every((edge) => !edge.id.includes("caipe")));
  assert.ok(
    interactions.every((interaction) => interaction.id !== "caipe-use"),
  );
});

test("runner registration uses only the outbound tunnel and requires Omnigent", () => {
  for (const selection of [["omnigent"], ["omnigent", "openshell"]]) {
    const model = makePlayground({
      integrations: selection,
      interaction: "omni-register",
    });
    assert.deepEqual(model.activeEdges, ["host-tunnel"]);
    assert.equal(
      readPlayground(playgroundSearch(model.state)).interaction,
      "omni-register",
    );
  }
  assert.equal(
    normalizePlayground({ integrations: [], interaction: "omni-register" })
      .interaction,
    "overview",
  );
});
test("interaction groups include every scenario once and follow the selected native integration", () => {
  for (const selection of combinations) {
    const groups = groupInteractions({ integrations: selection });
    const ids = groups.flatMap((group) => group.items.map((item) => item.id));
    assert.equal(new Set(ids).size, ids.length);
    assert.deepEqual(
      [...ids].sort(),
      interactions
        .filter((item) => item.id !== "overview")
        .map((item) => item.id)
        .sort(),
    );
    assert.equal(
      groups.find((group) => group.id === "native").label.includes("OpenShell"),
      selection.includes("openshell"),
    );
    assert.ok(
      groups
        .find((group) => group.id === "omnigent")
        .items.some((item) => item.id === "omni-register"),
    );
  }
});
test("gateway connection and its label remain inside the cluster boundary", () => {
  const model = makePlayground({ integrations: ["openshell"] });
  const cluster = model.groups.find((group) => group.id === "cluster");
  const edge = model.edges.find((edge) => edge.id === "portal-gateway");
  for (const [x, y] of edge.points)
    assert.ok(
      x >= cluster.x &&
        x <= cluster.x + cluster.w &&
        y >= cluster.y &&
        y <= cluster.y + cluster.h,
    );
  assert.ok(edge.labelAt[1] - 12 > cluster.y);
});
test("application connection labels are present and do not overlap component cards", () => {
  const nativeEdges = new Set([
    "native-watch",
    "reconcile-workload",
    "gateway-native",
    "portal-native",
    "direct-exec",
  ]);
  for (const selection of combinations) {
    for (const action of interactions.filter((item) =>
      available(item, selection),
    )) {
      const model = makePlayground({
        integrations: selection,
        interaction: action.id,
      });
      for (const edge of model.edges.filter(
        (edge) => edge.general || model.activeEdges.includes(edge.id),
      )) {
        if (
          !nativeEdges.has(edge.id) &&
          !(edge.id === "host-tunnel" && action.id === "omni-work")
        )
          assert.ok(edge.labelAt, edge.id);
        if (!edge.labelAt) continue;
        const [x, y] = edge.labelAt;
        const halfWidth = edge.label.length * 3.2 + 9;
        const [w, h] = edge.labelAngle ? [12, halfWidth] : [halfWidth, 12];
        for (const node of model.nodes)
          assert.ok(
            !(
              x + w > node.x &&
              x - w < node.x + node.w &&
              y + h > node.y &&
              y - h < node.y + node.h
            ),
            `${action.id}: ${edge.id} label overlaps ${node.id}`,
          );
      }
    }
  }
});

test("Kata is optional and changes Pod isolation without changing topology", () => {
  assert.deepEqual(
    requiredIntegrations.map((item) => item.id),
    ["agent-sandbox"],
  );
  assert.ok(initialSelection.includes("kata"));
  for (const selection of combinations.filter((ids) => !ids.includes("kata"))) {
    const plain = makePlayground({ integrations: selection });
    const isolated = makePlayground({ integrations: ["kata", ...selection] });
    assert.deepEqual(
      plain.nodes.map((node) => node.id),
      isolated.nodes.map((node) => node.id),
    );
    assert.deepEqual(plain.edges, isolated.edges);
    assert.equal(
      plain.groups.find((group) => group.id === "workload").title,
      "Pod",
    );
    assert.equal(
      plain.groups.find((group) => group.id === "workload").kata,
      false,
    );
    assert.equal(
      isolated.groups.find((group) => group.id === "workload").title,
      "Pod with KATA runtime (MicroVM)",
    );
    assert.equal(
      isolated.groups.find((group) => group.id === "workload").kata,
      true,
    );
    assert.equal(
      plain.nodes.find((node) => node.id === "shell").subtitle,
      "Inside the Pod",
    );
    assert.equal(
      isolated.nodes.find((node) => node.id === "shell").subtitle,
      "Inside the micro VM",
    );
  }
});

test("Internet is external and workload egress follows the selected enforcement path", () => {
  for (const selection of combinations) {
    const model = makePlayground({
      integrations: selection,
      interaction: "internet-access",
    });
    const cluster = model.groups.find((group) => group.id === "cluster");
    const workload = model.groups.find((group) => group.id === "workload");
    const internet = model.nodes.find((node) => node.id === "internet");
    const egress = model.nodes.find((node) => node.id === "egress");
    assert.ok(internet.y + internet.h < cluster.y);
    assert.ok(
      egress.x >= cluster.x && egress.x + egress.w <= cluster.x + cluster.w,
    );
    assert.ok(egress.y >= cluster.y && egress.y + egress.h < workload.y);
    if (selection.includes("openshell")) {
      assert.deepEqual(model.activeEdges, [
        "protected-network",
        "supervisor-egress",
        "egress-internet",
      ]);
      assert.ok(!model.edges.some((edge) => edge.id === "pod-egress"));
      assert.equal(
        model.edges.find((edge) => edge.id === "protected-network").to,
        "supervisor",
      );
      assert.match(
        egress.body,
        /native outer fence must block direct workload egress/,
      );
    } else {
      assert.deepEqual(model.activeEdges, ["pod-egress", "egress-internet"]);
      assert.ok(!model.edges.some((edge) => edge.id === "supervisor-egress"));
      assert.match(egress.body, /When enabled.*public IPv4 TCP\/443/);
    }
    assert.match(egress.body, /off by default/);
    const outbound = model.edges.find((edge) => edge.id === "egress-internet");
    assert.equal(outbound.from, "egress");
    assert.equal(outbound.to, "internet");
    const overview = makePlayground({ integrations: selection });
    assert.ok(overview.activeEdges.includes("egress-internet"));
  }
});

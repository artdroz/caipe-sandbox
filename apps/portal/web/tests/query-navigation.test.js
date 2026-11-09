import test from "node:test";
import assert from "node:assert/strict";
import { inventoryQuery, createInventoryQueryNavigation } from "../query-navigation.js";
import { createCAIPEQueryBridge } from "../integrations/caipe/query-navigation.js";

function setup(search = "", embedded = false) {
  const listeners = new Map(), documentListeners = new Map(), messages = [], restored = [];
  const entries = [new URL("https://portal.example.test/apps/sandbox" + search)];
  let index = 0, scopeChanges = 0;
  const env = {
    location: entries[0], acceptScope: true,
    addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: name => listeners.delete(name),
    document: { addEventListener: (name, fn) => documentListeners.set(name, fn), removeEventListener: name => documentListeners.delete(name) },
  };
  env.parent = embedded ? { postMessage: message => messages.push(message) } : env;
  env.history = {
    pushState(_state, _title, href) { entries.splice(index + 1); entries.push(new URL(href, env.location)); env.location = entries[++index]; },
    replaceState(_state, _title, href) { env.location = entries[index] = new URL(href, env.location); },
    back() { env.location = entries[--index]; listeners.get("popstate")(); },
    forward() { env.location = entries[++index]; listeners.get("popstate")(); },
  };
  const navigation = createInventoryQueryNavigation({ env, bridge: embedded ? createCAIPEQueryBridge({env}) : undefined, basePath: "/apps/sandbox", onRestore: query => restored.push(query),
    beforeScopeChange: () => env.acceptScope, onScopeChange: () => { scopeChanges++; },
  });
  const receive = (data, overrides = {}) => listeners.get("message")({ source: env.parent, origin: env.location.origin,
    data: { version: "1.0", appId: "sandbox", ...data }, ...overrides });
  function connect() {
    receive({ type: "caipe.agenticApp.bridge.capabilities.v1", capabilities: { queryNavigation: true } });
    receive({ type: "caipe.agenticApp.navigation.v1", href: env.location.pathname + env.location.search + env.location.hash });
  }
  return { env, entries, navigation, restored, messages, listeners, documentListeners, receive, connect, scopeChanges: () => scopeChanges };
}

test("bookmarked inventory filters are bounded without changing authorization or default view", () => {
  assert.deepEqual(inventoryQuery("?view=admin&owner=test-user%40example.test&q=release&profile=engineering"), {
    view: "admin", owner: "test-user@example.test", query: "release", profile: "engineering",
  });
  assert.equal(inventoryQuery("?view=unknown").view, "mine");
  assert.equal(inventoryQuery("?q=" + "x".repeat(300)).query.length, 256);
  const app = setup("?view=admin&q=release&profile=engineering"); app.navigation.initialize();
  assert.equal(app.restored[0].query, "release"); assert.equal(app.restored[0].profile, "engineering");
  assert.equal(app.scopeChanges(), 0);
});

test("standalone filters preserve unrelated parameters and hashes and restore Back/Forward", () => {
  const app = setup("?view=admin&assistant=1#inventory"); app.navigation.initialize();
  app.navigation.filters("rel", "engineering"); app.navigation.filters("release", "engineering", "replace");
  assert.equal(app.entries.length, 2);
  assert.equal(app.env.location.searchParams.get("assistant"), "1"); assert.equal(app.env.location.hash, "#inventory");
  app.env.history.back(); assert.equal(app.restored.at(-1).query, "");
  app.env.history.forward(); assert.equal(app.restored.at(-1).query, "release");
});

test("hosted filters have one parent history owner and host restoration does not echo", () => {
  const app = setup("?view=admin", true); app.connect(); app.navigation.initialize(); app.messages.length = 0;
  app.navigation.filters("release", "engineering");
  assert.equal(app.entries.length, 1);
  assert.deepEqual(app.messages.at(-1), { type: "caipe.agenticApp.navigate.v1", version: "1.0", appId: "sandbox", href: "/apps/sandbox?view=admin&q=release&profile=engineering", history: "push" });
  app.messages.length = 0;
  app.receive({ type: "caipe.agenticApp.navigation.v1", href: "/apps/sandbox?view=admin&q=guide" });
  assert.equal(app.restored.at(-1).query, "guide"); assert.equal(app.messages.length, 0);
});

test("untrusted origins, windows, app IDs, versions and routes cannot restore inventory state", () => {
  const app = setup("?view=admin", true); app.connect(); app.navigation.initialize(); const count = app.restored.length;
  const data = { type: "caipe.agenticApp.navigation.v1", href: "/apps/sandbox?view=admin&q=forged" };
  app.receive(data, { origin: "https://other.example.test" }); app.receive(data, { source: {} });
  app.receive({ ...data, appId: "other" }); app.receive({ ...data, version: "2.0" });
  for (const href of ["/chat?q=forged", "//other.example.test/apps/sandbox", "/apps/sandbox?invalid=raw space", "/apps/sandbox?" + "x".repeat(8200)]) app.receive({ ...data, href });
  assert.equal(app.restored.length, count);
  assert.equal(app.env.location.searchParams.get("q"), null);
});

test("scope links respect the existing leave-session decision and never trigger portal mutations", () => {
  const app = setup("?view=admin", true); app.connect(); app.env.acceptScope = false;
  const link = { href: "https://portal.example.test/apps/sandbox", target: "", hasAttribute: () => false };
  const click = { button: 0, target: { closest: () => link }, preventDefault() { this.prevented = true; } };
  app.documentListeners.get("click")(click);
  assert.equal(click.prevented, true); assert.equal(app.scopeChanges(), 0); assert.equal(app.env.location.search, "?view=admin");
  app.env.acceptScope = true; app.documentListeners.get("click")(click);
  assert.equal(app.scopeChanges(), 1); assert.equal(app.messages.at(-1).href, "/apps/sandbox");
});

test("completed document scope navigation is mirrored once instead of being reverted", () => {
  const app = setup("?view=admin", true);
  app.receive({ type: "caipe.agenticApp.bridge.capabilities.v1", capabilities: { queryNavigation: true } });
  app.receive({ type: "caipe.agenticApp.navigation.v1", href: "/apps/sandbox" });
  assert.equal(app.scopeChanges(), 0);
  assert.equal(app.env.location.search, "?view=admin");
  assert.equal(app.messages.at(-1).history, "replace"); assert.equal(app.messages.at(-1).href, "/apps/sandbox?view=admin");
});

test("disposal removes window and document listeners", () => {
  const app = setup(); app.navigation.dispose(); assert.equal(app.listeners.size, 0); assert.equal(app.documentListeners.size, 0);
});

test("standalone filters survive cached page restoration and subsequent Back/Forward", () => {
  const app = setup("?view=admin"); app.navigation.initialize();
  app.navigation.filters("first", "engineering");
  app.listeners.get("pagehide")({persisted:true});
  app.env.history.replaceState(null, "", "/apps/sandbox?view=admin&q=restored");
  app.listeners.get("pageshow")({persisted:true});
  assert.equal(app.restored.at(-1).query, "restored");
  app.env.history.back(); assert.equal(app.restored.at(-1).query, "");
  app.env.history.forward(); assert.equal(app.restored.at(-1).query, "restored");
});

test("cached hosted pages retain their query bridge and scope confirmation", () => {
  const app = setup("?view=admin", true); app.connect(); app.navigation.initialize();
  app.navigation.filters("before", "engineering");
  app.listeners.get("pagehide")({persisted:true});
  app.messages.length = 0;
  app.receive({ type:"caipe.agenticApp.navigation.v1", href:"/apps/sandbox?view=admin&q=after" });
  assert.equal(app.restored.at(-1).query, "after");
  assert.equal(app.messages.length, 0);
  app.env.acceptScope = false;
  const link = {href:"https://portal.example.test/apps/sandbox", target:"", hasAttribute:()=>false};
  const click = {button:0,target:{closest:()=>link},preventDefault(){this.prevented=true;}};
  app.documentListeners.get("click")(click);
  assert.equal(click.prevented, true); assert.equal(app.scopeChanges(), 0);
  assert.equal(app.env.location.searchParams.get("view"), "admin");
});

test("permanent page exit disposes native and hosted navigation handlers", () => {
  for (const embedded of [false,true]) {
    const app=setup("", embedded); if (embedded) app.connect();
    app.listeners.get("pagehide")({persisted:false});
    assert.equal(app.listeners.size,0); assert.equal(app.documentListeners.size,0);
  }
});

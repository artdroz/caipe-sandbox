/** Read-only inventory presentation; these parameters never authorize portal actions. */
export function inventoryQuery(search) {
  const params = new URLSearchParams(search);
  return {
    view: params.get("view") === "admin" ? "admin" : "mine",
    owner: (params.get("owner") || "").slice(0, 256),
    query: (params.get("q") || "").slice(0, 256),
    profile: (params.get("profile") || "").slice(0, 256),
  };
}

/** One query-history owner in hosted mode; native history when standalone. */
export function createInventoryQueryNavigation({ env = window, basePath, onRestore, beforeScopeChange = () => true, onScopeChange }) {
  const path = new URL(basePath || "/", env.location.origin).pathname.replace(/\/$/, "") || "/";
  let current = path + env.location.search + env.location.hash;
  let bridged = false, initialized = false;
  const context = href => {
    const { view, owner } = inventoryQuery(new URL(href, env.location.origin).search);
    return JSON.stringify([view, owner]);
  };
  const send = (type, extra = {}) => env.parent.postMessage({ type, version: "1.0", appId: "sandbox", ...extra }, env.location.origin);
  function valid(href) {
    if (typeof href !== "string" || href.length > 8192 || !href.startsWith("/") || href.startsWith("//") || /[\\\u0000-\u0020]/.test(href)) return null;
    const url = new URL(href, env.location.origin);
    return url.origin === env.location.origin && (url.pathname.replace(/\/$/, "") || "/") === path ? url : null;
  }
  function apply(url, mode, fromHost = false) {
    const href = path + url.search + url.hash;
    if (href === current) return true;
    const scopeChanged = context(href) !== context(current);
    if (scopeChanged && !beforeScopeChange()) {
      const previous = new URL(current, env.location.origin);
      env.history.replaceState(null, "", env.location.pathname + previous.search + previous.hash);
      if (fromHost && bridged) send("caipe.agenticApp.navigate.v1", { href: current, history: "replace" });
      return false;
    }
    current = href;
    env.history[bridged || mode === "replace" ? "replaceState" : "pushState"](null, "", env.location.pathname + url.search + url.hash);
    if (!fromHost && bridged) send("caipe.agenticApp.navigate.v1", { href, history: mode });
    if (scopeChanged) onScopeChange();
    else onRestore(inventoryQuery(url.search));
    return true;
  }
  const receive = event => {
    if (env.parent === env || event.source !== env.parent || event.origin !== env.location.origin) return;
    const message = event.data;
    if (!message || message.version !== "1.0" || message.appId !== "sandbox") return;
    if (message.type === "caipe.agenticApp.bridge.capabilities.v1") { bridged = message.capabilities?.queryNavigation === true; return; }
    if (!bridged || message.type !== "caipe.agenticApp.navigation.v1") return;
    const url = valid(message.href);
    if (!url) return;
    // A completed document navigation already owns its joint-history entry.
    // Mirror that scope into the shell instead of reverting the newly loaded page.
    if (!initialized && context(message.href) !== context(current)) {
      initialized = true;
      send("caipe.agenticApp.navigate.v1", { href: current, history: "replace" });
      return;
    }
    initialized = true;
    apply(url, "replace", true);
  };
  const pop = () => {
    const url = new URL(env.location.href);
    apply(url, "replace", true);
  };
  const click = event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.("a[href]");
    if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
    const target = new URL(link.href, env.location.href);
    const url = valid(target.pathname + target.search + target.hash);
    if (target.origin !== env.location.origin || !url || context(target.href) === context(current)) return;
    event.preventDefault();
    apply(url, "push");
  };
  env.addEventListener("message", receive);
  env.addEventListener("popstate", pop);
  env.document.addEventListener("click", click);
  if (env.parent !== env) send("caipe.agenticApp.bridge.connect.v1");
  return {
    initialize() { onRestore(inventoryQuery(env.location.search)); },
    read: () => inventoryQuery(env.location.search),
    filters(query, profile, mode = "push") {
      const url = new URL(env.location.href);
      for (const [name, value] of [["q", query], ["profile", profile]]) {
        if (value) url.searchParams.set(name, value.slice(0, 256)); else url.searchParams.delete(name);
      }
      apply(url, mode);
    },
    dispose() {
      env.removeEventListener("message", receive); env.removeEventListener("popstate", pop);
      env.document.removeEventListener("click", click);
    },
  };
}

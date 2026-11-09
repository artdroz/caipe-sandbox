/** CAIPE's same-origin query bridge; inventory state is owned by the portal. */
export function createCAIPEQueryBridge({ env = window } = {}) {
  let active = false, onNavigate;
  const send = (type, extra = {}) => env.parent.postMessage({ type, version: "1.0", appId: "sandbox", ...extra }, env.location.origin);
  const receive = event => {
    if (env.parent === env || event.source !== env.parent || event.origin !== env.location.origin) return;
    const message = event.data;
    if (!message || message.version !== "1.0" || message.appId !== "sandbox") return;
    if (message.type === "caipe.agenticApp.bridge.capabilities.v1") {
      active = message.capabilities?.queryNavigation === true;
    } else if (active && message.type === "caipe.agenticApp.navigation.v1") {
      onNavigate(message.href);
    }
  };
  return {
    get active() { return active; },
    connect(callback) {
      onNavigate = callback;
      if (env.parent === env) return;
      env.addEventListener("message", receive);
      send("caipe.agenticApp.bridge.connect.v1");
    },
    navigate(href, history) {
      if (active) send("caipe.agenticApp.navigate.v1", {href, history});
    },
    dispose() {
      env.removeEventListener("message", receive);
      active = false;
    },
  };
}

export class HostedNavigationGuard {
  constructor(env = window) {
    this.env = env;
    this.dispose = () => {};
  }
  update(config, state) {
    this.dispose();
    const env = this.env, host = env.parent;
    if (config.mode !== "caipe" || !state.active || host === env) return;
    try {
      if (host.location.origin !== env.location.origin) return;
    } catch (error) {
      if (error.name !== "SecurityError") throw error;
      return;
    }
    const leaving = href => {
      const next = new URL(href, host.location.href), current = new URL(host.location.href);
      return next.origin !== current.origin || next.pathname !== current.pathname || next.search !== current.search;
    };
    const confirm = () => env.confirm(`${state.title}\n\n${state.message}`);
    const click = event => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest?.("a[href]");
      if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self") || !leaving(link.href)) return;
      if (new URL(link.href).origin !== host.location.origin) return;
      if (!confirm()) { event.preventDefault(); event.stopImmediatePropagation(); }
    };
    const dispose = () => {
      host.document.removeEventListener("click", click, true);
      env.removeEventListener("pagehide", dispose);
    };
    host.document.addEventListener("click", click, true);
    env.addEventListener("pagehide", dispose, {once:true});
    this.dispose = dispose;
  }
}

const PREFERENCE = "portal-restart-notifications";

export class RestartNotifications {
  constructor({env = globalThis, changed = () => {}, activate = () => {}} = {}) {
    Object.assign(this, {env, changed, activate});
    this.pending = new Map();
    this.preferenceRevision = 0;
    this.title = env.document.title;
    this.enabled = this.preference();
    const visibility = () => {
      if (this.background()) this.notify();
      else this.notification?.close();
      this.changed();
    };
    env.document.addEventListener("visibilitychange", visibility);
    env.addEventListener("blur", visibility);
    env.addEventListener("focus", visibility);
    env.addEventListener("storage", event => {
      if (event.key === PREFERENCE) {
        this.preferenceRevision++;
        this.enabled = this.preference();
        if (!this.enabled) this.notification?.close();
        this.changed();
      }
    });
  }
  preference() {
    try { return this.env.localStorage.getItem(PREFERENCE) !== "false"; }
    catch { return true; }
  }
  state() {
    const available = this.env.isSecureContext && typeof this.env.Notification === "function" && !this.failed;
    const blocked = available && this.env.Notification.permission === "denied";
    const enabled = available && !blocked && this.enabled && this.env.Notification.permission === "granted";
    return {
      enabled,
      disabled: !available || blocked,
      label: !available ? "Desktop notifications unavailable in this browser" : blocked ? "Allow notifications in your browser site settings" : enabled ? "Disable restart notifications" : "Enable restart notifications",
    };
  }
  firstTerminalCreated() {
    if (this.started) return;
    this.started = true;
    if (this.enabled) return this.setEnabled(true);
  }
  toggle() {
    return this.setEnabled(!this.state().enabled);
  }
  async setEnabled(enabled) {
    if (this.state().disabled) return;
    const revision = ++this.preferenceRevision;
    try {
      let permission = this.env.Notification.permission;
      if (enabled && permission !== "granted") {
        this.permissionRequest ??= this.env.Notification.requestPermission().finally(() => { this.permissionRequest = null; });
        permission = await this.permissionRequest;
      }
      if (revision !== this.preferenceRevision) return;
      this.enabled = enabled && permission === "granted";
      try { this.env.localStorage.setItem(PREFERENCE, String(this.enabled)); } catch {}
      if (!this.enabled) this.notification?.close();
      else this.notify();
    } catch { this.failed = true; }
    this.changed();
  }
  warn(key, seconds) {
    if (!Number.isFinite(seconds) || seconds < 0 || seconds > 660) return;
    this.pending.set(key, Date.now() + seconds * 1000);
    this.env.document.title = "⚠ Portal restarting · CAIPE Sandbox";
    this.notify();
  }
  clear(key) {
    this.pending.delete(key);
    if (this.pending.size) return;
    this.env.document.title = this.title;
    this.notification?.close();
    this.notification = null;
    this.sent = false;
  }
  background() {
    return this.env.document.hidden || !this.env.document.hasFocus();
  }
  notify() {
    if (this.sent || !this.pending.size || !this.background() || !this.state().enabled) return;
    const [key] = this.pending.keys();
    const endsAt = Math.min(...this.pending.values());
    const deadline = new Date(endsAt).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
    const body = endsAt <= Date.now()
      ? "A portal restart interrupted terminal connections. Return to reconnect; helpers are not rerun."
      : `Terminal connections will close at ${deadline}. Save your work. Reconnection opens a new shell; helpers are not rerun.`;
    try {
      const notification = new this.env.Notification("Sandbox portal restarting", {
        body,
        tag: "sandbox-portal-restart",
      });
      this.notification = notification;
      this.sent = true;
      notification.onclick = () => {
        notification.close();
        this.env.focus();
        this.activate(this.pending.has(key) ? key : this.pending.keys().next().value);
      };
      notification.onerror = () => { this.failed = true; this.changed(); };
    } catch { this.failed = true; this.changed(); }
  }
}

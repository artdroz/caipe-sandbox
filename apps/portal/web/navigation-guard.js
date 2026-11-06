export class TerminalNavigationGuard {
  constructor(notify, env = window) {
    this.env = env;
    this.notify = notify;
    this.count = -1;
    this.beforeUnload = event => {
      event.preventDefault();
      event.returnValue = "";
    };
  }
  update(count) {
    if (this.count === count) return;
    const wasActive = this.count > 0;
    this.count = count;
    if (count > 0 && !wasActive) this.env.addEventListener("beforeunload", this.beforeUnload);
    if (!count && wasActive) this.env.removeEventListener("beforeunload", this.beforeUnload);
    this.notify({
      active: count > 0,
      title: "Leave Sandbox?",
      message: `You have ${count} terminal ${count === 1 ? "session" : "sessions"} open. Leaving will close these sessions and may interrupt running commands. Your sandboxes and saved files will remain available.`,
    });
  }
}

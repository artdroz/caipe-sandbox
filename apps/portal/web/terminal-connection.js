export class TerminalConnection {
  constructor(url, {status, ready, output, disconnected, error, complete, notice, restart}, {makeSocket = url => new WebSocket(url), timeout = 25000, maxRetries = 3, random = Math.random} = {}) {
    Object.assign(this, {url, status, ready, output, disconnected, error, complete, notice, restart, makeSocket, timeout, maxRetries, random});
    this.helper = new URL(url).searchParams.has("helper");
    if (this.helper) this.maxRetries = 0;
    this.retries = 0;
    this.connect();
  }
  send(message) {
    if (this.shellReady && this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(message));
  }
  stopSocket() {
    clearTimeout(this.deadline);
    clearTimeout(this.noticeTimer);
    this.shellReady = false;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }
  connect() {
    if (this.closed) return;
    this.status(this.retries ? `Reconnecting ${this.retries}/3…` : "Connecting…", false);
    let socket;
    try { socket = this.makeSocket(this.url); }
    catch { this.fail({message: "The browser could not start a WebSocket connection. Check network access and browser security settings.", code: "browser-connection"}); return; }
    this.socket = socket;
    socket.binaryType = "arraybuffer";
    let opened = false;
    this.deadline = setTimeout(() => {
      if (this.socket === socket) this.fail({code: "client-timeout", message: opened ? "Client timed out waiting for the server to open the sandbox shell (25 seconds)." : "Client timed out establishing the WebSocket connection (25 seconds). Check VPN/network access, DNS and TLS."});
    }, this.timeout);
    socket.onopen = () => {
      opened = true;
      if (this.socket === socket) this.status(this.retries ? `Reconnecting ${this.retries}/3 · opening shell…` : "Opening shell…", false);
    };
    socket.onmessage = event => {
      if (this.socket !== socket) return;
      if (typeof event.data === "string") { this.output(event.data); return; }
      try {
        const message = JSON.parse(new TextDecoder().decode(event.data));
        if (message.type === "draining") {
          if (!Number.isFinite(message.seconds_remaining) || message.seconds_remaining < 0 || message.seconds_remaining > 660) throw new Error("Invalid drain deadline");
          if (!this.draining) this.restart?.(message.seconds_remaining);
          this.draining = true;
          const deadline = Date.now() + message.seconds_remaining * 1000;
          clearTimeout(this.noticeTimer);
          const countdown = () => {
            if (this.socket !== socket) return;
            const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            const remaining = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
            this.notice?.(`Portal restarting in ${remaining}. Save your work. ${this.helper ? "This helper will not be rerun automatically." : "Reconnection opens a new shell."}`);
            if (seconds) this.noticeTimer = setTimeout(countdown, 1000);
          };
          countdown();
          return;
        }
        if (message.type === "complete") {
          this.error?.(null);
          this.stopSocket();
          this.disconnected();
          const next = new URL(this.url);
          next.searchParams.delete("helper");
          this.url = next.href;
          this.helper = false;
          this.maxRetries = 3;
          this.retries = 0;
          this.complete?.(message.exit_code);
          this.connect();
          return;
        }
        if (message.type === "error") { this.fail(message); return; }
        if (message.type !== "ready" || this.shellReady) return;
        clearTimeout(this.deadline);
        this.shellReady = true;
        this.draining = false;
        this.notice?.(null);
        this.error?.(null);
        this.status(this.retries ? "Reconnected · new shell" : "Connected", false);
        this.ready();
      } catch { this.fail({code:"protocol-error", message:"The server sent an invalid terminal control message."}); }
    };
    socket.onerror = () => { if (this.socket === socket) this.fail({code:"browser-connection", message:"Browser WebSocket error. Network/VPN, DNS, TLS or an HTTP handshake failure may be involved; the browser does not expose the exact cause."}); };
    socket.onclose = event => { if (this.socket === socket) this.fail({code:"connection-closed", message:`${opened ? "Server connection" : "WebSocket handshake"} closed (WebSocket code ${event.code}).`}); };
  }
  fail(reason) {
    if (this.closed) return;
    this.error?.(this.draining && reason.code === "connection-closed" ? null : reason);
    if (this.draining) this.notice?.(this.helper ? "Portal connection ended. This helper was not rerun; open a new helper session when the portal is ready." : "Portal restarting. Reconnection opens a new shell; commands are not replayed.");
    this.stopSocket();
    this.disconnected();
    if (this.retries >= this.maxRetries) {
      this.status(this.maxRetries ? `Terminal connection failed after ${this.maxRetries} retries.` : "Helper session ended. Open a new session to run it again.", true);
      return;
    }
    this.retries++;
    this.status(`Reconnecting ${this.retries}/3…`, false);
    this.backoff = setTimeout(() => this.connect(), this.retries * 1000 + this.random() * 500);
  }
  retry() {
    if (this.closed) return;
    clearTimeout(this.backoff);
    this.stopSocket();
    this.retries = 0;
    this.connect();
  }
  close() {
    this.closed = true;
    clearTimeout(this.backoff);
    this.stopSocket();
  }
}

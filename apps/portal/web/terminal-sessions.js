export class TerminalSessions extends Map {
  constructor() {
    super();
    this.numbers = new Map();
  }
  create(sandboxKey, values) {
    const number = (this.numbers.get(sandboxKey) || 0) + 1;
    this.numbers.set(sandboxKey, number);
    const session = {...values, sandboxKey, number, key: crypto.randomUUID()};
    this.set(session.key, session);
    return session;
  }
  latest(sandboxKey) {
    return [...this.values()].findLast(session => session.sandboxKey === sandboxKey);
  }
  restartNotice(sandboxKey) {
    return [...this.values()].find(session => session.sandboxKey === sandboxKey && session.restartNotice)?.restartNotice;
  }
}

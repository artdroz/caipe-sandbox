import test from "node:test";
import assert from "node:assert/strict";
import { TerminalSessions } from "../terminal-sessions.js";

test("multiple shells for one sandbox retain independent identity and connection state", () => {
  const sessions = new TerminalSessions();
  const first = sessions.create("ns/sandbox", {connection:{shellReady:true}, output:"first"});
  const second = sessions.create("ns/sandbox", {connection:{shellReady:false}, output:"second"});
  assert.notEqual(first.key, second.key);
  assert.equal(first.number, 1);
  assert.equal(second.number, 2);
  assert.equal(sessions.latest("ns/sandbox"), second);
  sessions.delete(second.key);
  assert.equal(sessions.get(first.key).output, "first");
  assert.equal(sessions.get(first.key).connection.shellReady, true);
  assert.equal(sessions.latest("ns/sandbox"), first);
  assert.equal(sessions.create("ns/sandbox", {}).number, 3);
});

test("session lookup never crosses namespace or sandbox boundaries", () => {
  const sessions = new TerminalSessions();
  const first = sessions.create("ns-a/sandbox", {});
  const second = sessions.create("ns-b/sandbox", {});
  assert.equal(second.number, 1);
  assert.equal(sessions.latest("ns-a/sandbox"), first);
  assert.equal(sessions.latest("ns-b/sandbox"), second);
  assert.equal(sessions.latest("missing"), undefined);
});

test("a sandbox warning persists until every affected shell recovers or closes", () => {
  const sessions = new TerminalSessions();
  const first = sessions.create("ns-a/vm", {restartNotice:"Restarting in 2m"});
  const second = sessions.create("ns-a/vm", {restartNotice:"Restarting in 1m"});
  sessions.create("ns-b/vm", {restartNotice:"Another replica is restarting"});
  assert.equal(sessions.restartNotice("ns-a/vm"), first.restartNotice);
  first.restartNotice = null;
  assert.equal(sessions.restartNotice("ns-a/vm"), second.restartNotice);
  sessions.delete(second.key);
  assert.equal(sessions.restartNotice("ns-a/vm"), undefined);
  assert.equal(sessions.restartNotice("ns-b/vm"), "Another replica is restarting");
});

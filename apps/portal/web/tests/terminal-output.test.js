import test from "node:test";
import assert from "node:assert/strict";
import { terminalText, terminalFilename } from "../terminal-output.js";

function terminal(rows) {
  const lines = rows.map(([text, wrapped=false]) => ({isWrapped:wrapped, translateToString:trim => trim ? text.trimEnd() : text}));
  return {buffer:{active:{length:lines.length,getLine:index=>lines[index]}}};
}

test("output export joins wrapped lines and removes unused blank rows", () => {
  const term = terminal([["command output"],["a long wrapped "],["line",true],["next command"],[""],[""]]);
  assert.equal(terminalText(term), "command output\na long wrapped line\nnext command\n");
});

test("output export keeps deliberate empty lines and only reads the selected buffer", () => {
  assert.equal(terminalText(terminal([["one"],[""],["two"],[""]])), "one\n\ntwo\n");
  assert.equal(terminalText(terminal([[""]])), "");
  assert.equal(terminalText(terminal([])), "");
});

test("download names cannot contain paths and distinguish shell sessions", () => {
  assert.equal(terminalFilename({title:"../../My sandbox",number:2}), "My-sandbox-shell-2.txt");
  assert.equal(terminalFilename({title:"???",number:3}), "sandbox-shell-3.txt");
});

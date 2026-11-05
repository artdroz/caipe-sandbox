export function terminalText(terminal) {
  const buffer = terminal.buffer.active;
  const lines = [];
  for (let index = 0; index < buffer.length; index++) {
    const line = buffer.getLine(index);
    if (!line) continue;
    const nextWrapped = buffer.getLine(index + 1)?.isWrapped;
    const text = line.translateToString(!nextWrapped);
    if (line.isWrapped && lines.length) lines[lines.length - 1] += text;
    else lines.push(text);
  }
  while (lines.at(-1) === "") lines.pop();
  return lines.length ? lines.join("\n") + "\n" : "";
}

export function terminalFilename(session) {
  const name = session.title.replace(/[^a-z0-9_-]+/gi, "-").replace(/^-|-$/g, "").slice(0, 80) || "sandbox";
  return `${name}-shell-${session.number}.txt`;
}

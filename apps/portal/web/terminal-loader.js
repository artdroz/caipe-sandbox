// Failed downloads can be retried; concurrent opens share the same download.
export function terminalLoader(importRuntime = retry => {
  const path = "./terminal-runtime.js" + (retry ? `?retry=${retry}` : "");
  return import(path);
}) {
  let pending, retry = 0;
  return () => pending ||= Promise.resolve().then(() => importRuntime(retry)).catch(error => {
    pending = undefined;
    retry++;
    throw error;
  });
}

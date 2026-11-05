export const resourceFields = [
  ["cpu-request", "cpu_request_millicores", 1000],
  ["cpu-limit", "cpu_limit_millicores", 1000],
  ["memory-request", "memory_request_mib", 1024],
  ["memory-limit", "memory_limit_mib", 1024],
  ["workspace", "workspace_gib", 1],
];

export function resourceInputs(size, bounds, policy) {
  return resourceFields.map(([id, field, scale]) => {
    const limits = bounds?.[field] || policy[field.startsWith("cpu") ? "cpu_millicores" : field.startsWith("memory") ? "memory_mib" : "workspace_gib"];
    return {id, value: size[field] / scale, min: limits.min / scale, max: limits.max / scale};
  });
}

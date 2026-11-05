// Round only the corners; endpoints stay on their component ports.
export function connectorPath(points, radius = 14) {
  if (!points.length) return "";
  let path = `M ${points[0].join(" ")}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [previous, corner, next] = [points[i - 1], points[i], points[i + 1]];
    const before = Math.hypot(corner[0] - previous[0], corner[1] - previous[1]);
    const after = Math.hypot(next[0] - corner[0], next[1] - corner[1]);
    if (!before || !after) continue;
    const bend = Math.min(radius, before / 2, after / 2);
    const entry = corner.map(
      (v, axis) => v + ((previous[axis] - v) * bend) / before,
    );
    const exit = corner.map((v, axis) => v + ((next[axis] - v) * bend) / after);
    path += ` L ${entry.join(" ")} Q ${corner.join(" ")} ${exit.join(" ")}`;
  }
  if (points.length > 1) path += ` L ${points.at(-1).join(" ")}`;
  return path;
}

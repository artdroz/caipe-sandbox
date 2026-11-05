export function filterSandboxes(rows, query = "", profile = "") {
  const search = query.trim().toLowerCase();
  return rows.filter(sandbox => {
    const matchesProfile = !profile || (profile === "__unassigned__" ? !sandbox.profile : sandbox.profile?.id === profile);
    return matchesProfile && [sandbox.title, sandbox.id, sandbox.native_id, sandbox.namespace, sandbox.owner, sandbox.profile?.id, sandbox.profile?.title, sandbox.profile?.revision]
      .some(value => String(value || "").toLowerCase().includes(search));
  });
}

export function inventoryProfiles(catalog, rows) {
  const profiles = new Map(catalog.map(profile => [profile.id, {id:profile.id, title:profile.title}]));
  for (const {profile} of rows) if (profile && !profiles.has(profile.id)) profiles.set(profile.id, {id:profile.id, title:profile.title});
  return [
    {id:"", title:"All profiles"},
    ...(rows.some(sandbox => !sandbox.profile) ? [{id:"__unassigned__", title:"No profile"}] : []),
    ...[...profiles.values()].sort((a,b) => a.title.localeCompare(b.title)),
  ];
}

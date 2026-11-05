"""Namespace reuse through existing shell access, bounded by an admin lock."""

from fastapi import HTTPException

from .controls import NamespaceControl, now
from .namespaces import namespace_config
from .storage import scope_key


class NamespaceAccess:
    def __init__(self, store):
        self.store = store

    def allowed(self, actor, provider, instance, scope, owner, policy):
        control = policy.namespaces.get(
            scope_key(provider, instance, scope), NamespaceControl()
        )
        if control.creation_disabled:
            return False
        return (
            actor == owner
            or self.store.metadata.get_scope_grants(
                owner, provider, instance, scope
            ).get(actor)
            == "shell"
        )

    def list(self, actor):
        policy, _ = self.store.controls.read()
        placement_allowed = "perUser" in namespace_config(self.store.settings).choices
        if not placement_allowed:
            return []
        eligible = {
            scope_key(record.provider, record.provider_instance, record.scope)
            for record in self.store._pages(actor)
            if record.scope_owner == actor or record.grants.get(actor) == "shell"
        }
        result = []
        for item in self.store.metadata.list_scopes():
            backend = self.store.integrations.items.get(item["provider"])
            inspect = getattr(backend, "namespace_info", None)
            if not inspect or backend.provider_instance != item["provider_instance"]:
                continue
            key = scope_key(item["provider"], item["provider_instance"], item["scope"])
            if (
                key not in eligible
                or policy.namespaces.get(key, NamespaceControl()).creation_disabled
            ):
                continue
            try:
                native = inspect(item["scope_owner"], item["scope"])
            except HTTPException:
                native = None
            if not native:
                continue
            row = {
                "id": key,
                "name": item["scope"],
                "owner": item["scope_owner"],
                "provider": item["provider"],
                "count": item["count"],
                "available": bool(native),
                "placement_allowed": placement_allowed,
            }
            result.append(row)
        return result

    def target(self, actor, backend, name):
        policy, _ = self.store.controls.read()
        matches = [
            item
            for item in self.store.metadata.list_scopes()
            if item["provider"] == backend.key
            and item["provider_instance"] == backend.provider_instance
            and item["scope"] == name
        ]
        if len(matches) != 1:
            raise HTTPException(422, "Choose an available namespace for this profile")
        item = matches[0]
        if not self.allowed(
            actor,
            backend.key,
            backend.provider_instance,
            name,
            item["scope_owner"],
            policy,
        ):
            raise HTTPException(403, "You cannot create micro VMs in this namespace")
        native = backend.namespace_info(item["scope_owner"], name)
        if not native:
            raise HTTPException(
                409, "Namespace is no longer available; refresh and retry"
            )
        return item["scope_owner"], native["uid"]

    def save(self, key, update, actor):
        if not any(
            scope_key(item["provider"], item["provider_instance"], item["scope"]) == key
            for item in self.store.metadata.list_scopes()
        ):
            raise HTTPException(404, "Namespace is not available")
        policy, version = self.store.controls.read()
        if version != update.resource_version:
            raise HTTPException(409, "Namespace lock changed; refresh and retry")
        entries = {
            **policy.namespaces,
            key: policy.namespaces.get(key, NamespaceControl()).model_copy(
                update={"creation_disabled": update.locked}
            ),
        }
        if len(entries) > 1000:
            raise HTTPException(422, "Too many namespace lock entries")
        candidate = policy.model_copy(
            update={"namespaces": entries, "updated_by": actor, "updated_at": now()}
        )
        saved = self.store.metadata.save_controls(
            candidate.model_dump(mode="json"), expected_revision=int(version)
        )
        return str(saved.revision)

    def forget(self, provider, instance, scope):
        key = scope_key(provider, instance, scope)
        policy, version = self.store.controls.read()
        if key in policy.namespaces:
            entries = {
                name: value for name, value in policy.namespaces.items() if name != key
            }
            candidate = policy.model_copy(update={"namespaces": entries})
            self.store.metadata.save_controls(
                candidate.model_dump(mode="json"), expected_revision=int(version)
            )

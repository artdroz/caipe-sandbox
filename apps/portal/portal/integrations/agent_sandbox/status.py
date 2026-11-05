"""Pod diagnostics for Kubernetes-backed sandbox allocations."""

from kubernetes.client import ApiException


def suspended(cr):
    meta = cr["metadata"]
    condition = next(
        (
            c
            for c in cr.get("status", {}).get("conditions", [])
            if c.get("type") == "Suspended"
        ),
        {},
    )
    return (
        not meta.get("deletionTimestamp")
        and cr["spec"].get("operatingMode") == "Suspended"
        and condition.get("status") == "True"
        and condition.get("observedGeneration", 0) >= meta.get("generation", 1)
    )


def enrich(core, cr, row):
    if row["state"] in {"Suspending", "Suspended", "Deleting"}:
        return row
    try:
        pod = core.read_namespaced_pod(
            cr.get("status", {}).get("podName") or row["id"], row["namespace"]
        )
    except ApiException as exc:
        if exc.status != 404:
            row["message"] = "Pod status temporarily unavailable"
        else:
            ready = next(
                (
                    c
                    for c in cr.get("status", {}).get("conditions", [])
                    if c.get("type") == "Ready"
                ),
                {},
            )
            if (
                ready.get("status") == "False"
                and ready.get("reason") == "InvalidConfiguration"
                and ready.get("observedGeneration", 0)
                >= cr["metadata"].get("generation", 1)
            ):
                row.update(
                    state="Error",
                    reason=ready["reason"],
                    message=ready.get("message") or row["message"],
                )
        return row
    if not any(r.uid == row["uid"] for r in pod.metadata.owner_references or []):
        return row
    status = pod.status
    failures = {
        "ErrImagePull": "Cannot pull sandbox image. Check the image and registry pull credentials.",
        "ImagePullBackOff": "Cannot pull sandbox image. Check the image and registry pull credentials.",
        "InvalidImageName": "The configured sandbox image reference is invalid.",
        "CrashLoopBackOff": "Sandbox container repeatedly exits. Check its startup logs.",
        "CreateContainerConfigError": "Sandbox container configuration is invalid or a required resource is missing.",
        "CreateContainerError": "Sandbox container could not be created. Check runtime events.",
        "RunContainerError": "Sandbox container could not start. Check runtime events.",
    }
    containers = (getattr(status, "init_container_statuses", None) or []) + (
        getattr(status, "container_statuses", None) or []
    )
    for container in containers:
        if not container.state:
            continue
        waiting = container.state.waiting
        terminated = container.state.terminated
        if waiting and waiting.reason in failures:
            message = failures[waiting.reason]
            if waiting.reason in {"ErrImagePull", "ImagePullBackOff"} and (
                "403 Forbidden" in (waiting.message or "")
                or "401 Unauthorized" in (waiting.message or "")
            ):
                message = "Registry rejected the sandbox image pull. Check registry pull credentials and access."
            row.update(
                state="Error",
                reason=waiting.reason,
                message=message,
            )
            return row
        if terminated and terminated.exit_code:
            row.update(
                state="Error",
                reason="ContainerExited",
                message=f"Sandbox container exited with code {terminated.exit_code}. Check its startup logs.",
            )
            return row
    if status.phase == "Failed":
        row.update(
            state="Error",
            reason="PodFailed",
            message="Sandbox pod failed. Check its runtime events.",
        )
    elif row["state"] == "Provisioning" or status.phase == "Pending":
        row["state"] = "Provisioning"
        scheduled = next(
            (
                c
                for c in getattr(status, "conditions", None) or []
                if c.type == "PodScheduled"
            ),
            None,
        )
        if scheduled and scheduled.status == "False":
            row["message"] = "Waiting for node capacity or volume placement"
        elif status.phase == "Pending":
            row["message"] = (
                "Starting the sandbox container and attaching its persistent disk"
            )
    return row

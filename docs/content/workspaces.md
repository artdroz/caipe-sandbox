---
title: Micro VM lifecycle
---

## Create

The portal validates your identity, access, selected profile, resource choices
and quota before calling the selected runtime integration. A creation request
identity lets retries refer to the same allocation. Display names and native
resource identities are separate.

## Work

Each terminal is an independent shell in the same micro VM. Profile helpers
can run login flows or maintenance commands. Files under the persistent mount
are retained; process memory and temporary files are not a durable checkpoint.

## Suspend

Manual suspension stops execution while retaining the micro VM's native
identity and storage. It interrupts terminal sessions. There is no built-in
idle detector or general warm-pool allocation in the reference implementation.

## Resume

Resume starts execution against the retained micro VM. Node capacity, image
pulls and volume attachment affect readiness. Reopen a terminal and restart
your tools or resume from their saved checkpoints.

## Share

Explicit grants control who can see or use a micro VM. Portal ownership and
authorization are checked for operations; a resource label alone is not proof
of access. Availability also depends on the recipient's portal role and policy.

## Delete

Deletion is a separate, destructive operation. In the Agent Sandbox path, it
can cascade to the owned micro VM claim. A StorageClass's reclaim policy
determines whether the backing volume is removed or retained for operator
cleanup. Confirm retention and backup policy before storing irreplaceable work.

## Check the lifecycle yourself

1. Create a micro VM and write a small file under its persistent mount.
2. Suspend it; confirm the terminal disconnects.
3. Resume it and open a new terminal; confirm the file remains.
4. Check login status for your tool; refresh authentication if needed.

Run deletion checks only with a disposable test micro VM.

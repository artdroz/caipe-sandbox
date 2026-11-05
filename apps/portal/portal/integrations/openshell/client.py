"""Authenticated native calls; portal operation IDs do not enable gateway replay."""

import codecs
import json
import queue
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import grpc
from fastapi import HTTPException
from google.protobuf.json_format import MessageToDict
from openshell._proto import datamodel_pb2 as dm
from openshell._proto import openshell_pb2 as pb
from openshell._proto import openshell_pb2_grpc

from ..errors import CreationRejected

MAX_BUFFER = 1024 * 1024


def data(message):
    return MessageToDict(message, preserving_proto_field_name=True)


def scope(namespace):
    return dm.WorkspaceSelector(workspace=namespace)


def failure(error, method=None):
    status = {
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.ALREADY_EXISTS: 409,
        grpc.StatusCode.ABORTED: 409,
        grpc.StatusCode.INVALID_ARGUMENT: 422,
        grpc.StatusCode.FAILED_PRECONDITION: 409,
        grpc.StatusCode.PERMISSION_DENIED: 403,
        grpc.StatusCode.DEADLINE_EXCEEDED: 504,
        grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
    }.get(error.code(), 503)
    detail = error.details() or ""
    if error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED and (
        "durable mutation admission limit" in detail
    ):
        return HTTPException(
            429,
            "OpenShell's saved action history is full. This management action "
            "is blocked. Ask a platform administrator to check "
            "the gateway's request history before retrying.\n\n"
            "OpenShell RESOURCE_EXHAUSTED: durable mutation admission limit reached.",
        )
    if "request is admitted but has no confirmed replayable success" in detail:
        message = (
            "OpenShell could not safely repeat the previous action. "
            "A platform administrator must check for partially created resources "
            "before starting a new attempt."
        )
        if method == "CreateSandbox":
            message = (
                "OpenShell cannot reuse this creation request. Use Cancel creation "
                "in the micro VM's actions, then create a new micro VM. If the "
                "original outcome is still unknown, an administrator must verify it first."
            )
        return HTTPException(
            status,
            message + "\n\nOpenShell FAILED_PRECONDITION: the previous request "
            "has no confirmed replayable success; reconcile its effects before "
            "starting a new request.",
        )
    if "sandbox-attachable" in detail and (
        "runtimeclass" in detail.lower() or "runtime class" in detail.lower()
    ):
        message = (
            "OpenShell cannot use the selected runtime because it has not been "
            "approved by the platform. Ask an administrator to sync the runtime "
            "configuration, then cancel this creation and create a new micro VM."
        )
        exception = CreationRejected if method == "CreateSandbox" else HTTPException
        return exception(
            status,
            message + "\n\nOpenShell FAILED_PRECONDITION: RuntimeClass requires "
            "the approval label openshell.ai/sandbox-attachable=true.",
        )
    message = {
        404: "OpenShell could not find this micro VM. Refresh status before retrying.",
        403: "OpenShell denied this action. Ask a platform administrator to check runtime permissions.",
        409: "OpenShell cannot complete this action with the current runtime configuration. Ask a platform administrator to check the gateway.",
        422: "OpenShell rejected this configuration. Review the profile or policy settings before retrying.",
        429: "OpenShell has reached its capacity limit. Try again when capacity is available.",
        504: "OpenShell did not respond in time. The action may have completed; refresh status before retrying.",
    }.get(
        status, "OpenShell is unavailable. Refresh status before retrying the action."
    )
    exception = (
        CreationRejected
        if method == "CreateSandbox"
        and error.code() == grpc.StatusCode.INVALID_ARGUMENT
        else HTTPException
    )
    return exception(status, message + "\n\nOpenShell status: " + error.code().name)


def gateway_address(endpoint):
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OpenShell endpoint must be an HTTPS origin")
    return parsed.netloc


class Gateway:
    def __init__(self, endpoint, certificates="/etc/portal-openshell", stub=None):
        address = gateway_address(endpoint)
        self.channel = None
        if stub is None:
            root = Path(certificates)
            credentials = grpc.ssl_channel_credentials(
                root_certificates=(root / "ca.crt").read_bytes(),
                private_key=(root / "tls.key").read_bytes(),
                certificate_chain=(root / "tls.crt").read_bytes(),
            )
            self.channel = grpc.secure_channel(
                address,
                credentials,
                options=[("grpc.max_receive_message_length", 4 * MAX_BUFFER)],
            )
        self.stub = stub or openshell_pb2_grpc.OpenShellStub(self.channel)

    def close(self):
        if self.channel:
            self.channel.close()

    def call(self, method, request, timeout=20):
        try:
            return getattr(self.stub, method)(request, timeout=timeout)
        except grpc.RpcError as exc:
            raise failure(exc, method) from None

    def get(self, namespace, name):
        return self.call(
            "GetSandbox",
            pb.GetSandboxRequest(workspace_scope=scope(namespace), name=name),
        ).sandbox

    def list(self, selector):
        token = ""
        seen = set()
        deadline = time.monotonic() + 20
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPException(504, "OpenShell inventory deadline exceeded")
            result = self.call(
                "ListSandboxes",
                pb.ListSandboxesRequest(
                    workspace_scope=dm.WorkspaceSelector(
                        all_workspaces=dm.AllWorkspaces()
                    ),
                    label_selector=selector,
                    page_size=20,
                    page_token=token,
                ),
                timeout=remaining,
            )
            yield from result.sandboxes
            token = result.next_page_token
            if not token:
                return
            if token in seen or len(seen) >= 10000:
                raise HTTPException(502, "OpenShell inventory pagination is invalid")
            seen.add(token)

    def connect(self, namespace, name, command, tty=True, stdin=True, timeout=20):
        # Exec attachments are not retried; omit the optional durable launch receipt.
        request = pb.ExecSandboxRequest(
            workspace_scope=scope(namespace),
            sandbox=name,
            command=command,
            tty=tty,
            cols=100,
            rows=30,
            no_login_shell=True,
        )
        execution = Execution(self.stub, request, stdin)
        if not execution.started.wait(timeout=timeout):
            execution.close()
            raise HTTPException(504, "OpenShell execution attachment timed out")
        if execution.error:
            execution.close()
            raise execution.error
        return execution


class Execution:
    """Transport methods shared by portal terminals and bounded control commands."""

    def __init__(self, stub, request, stdin):
        self.inputs = queue.Queue(maxsize=64)
        self.started = threading.Event()
        self.condition = threading.Condition()
        self.stdout = ""
        self.stderr = ""
        self.open = True
        self.returncode = None
        self.error = None
        self.call = None
        self.decoders = {
            kind: codecs.getincrementaldecoder("utf-8")(errors="replace")
            for kind in ["stdout", "stderr"]
        }

        def messages():
            yield pb.ExecSandboxInput(start=request)
            if not stdin:
                return
            while self.open:
                try:
                    message = self.inputs.get(timeout=0.1)
                except queue.Empty:
                    continue
                if message is None:
                    return
                yield message

        def receive():
            try:
                self.call = stub.ExecSandboxInteractive(messages())
                if not self.open:
                    self.call.cancel()
                    return
                self.call.initial_metadata()
                self.started.set()
                for event in self.call:
                    kind = event.WhichOneof("payload")
                    if kind == "exit":
                        self.returncode = event.exit.exit_code
                    elif kind in {"stdout", "stderr"}:
                        text = self.decoders[kind].decode(getattr(event, kind).data)
                        with self.condition:
                            while (
                                self.open
                                and len(self.stdout) + len(self.stderr) > MAX_BUFFER
                            ):
                                self.condition.wait(timeout=0.1)
                            if not self.open:
                                return
                            setattr(self, kind, getattr(self, kind) + text)
                            self.condition.notify_all()
            except grpc.RpcError as exc:
                if self.open:
                    self.error = failure(exc)
            finally:
                with self.condition:
                    if self.open and self.returncode is None and self.error is None:
                        self.error = HTTPException(
                            502, "OpenShell stream ended without an exit status"
                        )
                    self.open = False
                    self.started.set()
                    self.condition.notify_all()

        self.thread = threading.Thread(target=receive, daemon=True)
        self.thread.start()

    def is_open(self):
        return self.open or bool(self.stdout or self.stderr) or self.error is not None

    def update(self, timeout=0):
        with self.condition:
            if self.error:
                error, self.error = self.error, None
                raise error
            if self.open and not (self.stdout or self.stderr):
                self.condition.wait(timeout=timeout)

    def read_stdout(self, timeout=0):
        with self.condition:
            text, self.stdout = self.stdout, ""
            self.condition.notify_all()
            return text

    def read_stderr(self, timeout=0):
        with self.condition:
            text, self.stderr = self.stderr, ""
            self.condition.notify_all()
            return text

    def read_all(self):
        return self.read_stdout() + self.read_stderr()

    def write_stdin(self, text):
        self.send(pb.ExecSandboxInput(stdin=text.encode()))

    def write_channel(self, channel, value):
        if channel != 4:
            raise ValueError("Unsupported OpenShell terminal channel")
        size = json.loads(value)
        self.send(
            pb.ExecSandboxInput(
                resize=pb.ExecSandboxWindowResize(
                    cols=size["Width"], rows=size["Height"]
                )
            )
        )

    def send(self, message):
        if not self.open:
            raise HTTPException(409, "OpenShell execution has ended")
        try:
            self.inputs.put(message, timeout=1)
        except queue.Full:
            self.close()
            raise HTTPException(503, "OpenShell terminal input is backlogged") from None

    def close(self):
        with self.condition:
            self.open = False
            self.condition.notify_all()
        if self.call:
            self.call.cancel()

"""Commands used by profile terminals and helper status probes."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
Argument = Annotated[str, StringConstraints(max_length=4096, pattern=r"^[^\x00\r\n]*$")]
Command = Annotated[list[Argument], Field(min_length=1, max_length=64)]


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Command
    json_field: str | None = Field(default=None, min_length=1, max_length=120)
    signed_in_exit_codes: list[int] = Field(default_factory=lambda: [0], max_length=16)
    signed_out_exit_codes: list[int] = Field(default_factory=list, max_length=16)
    signed_out_contains: list[
        Annotated[str, StringConstraints(min_length=1, max_length=120)]
    ] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def valid_probe(self):
        if not self.command[0]:
            raise ValueError("Probe command executable must not be empty")
        if set(self.signed_in_exit_codes) & set(self.signed_out_exit_codes):
            raise ValueError("Signed-in and signed-out exit codes must not overlap")
        return self

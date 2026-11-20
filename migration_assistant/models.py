from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Resource:
    id: str
    name: str
    type: str
    location: str
    properties: dict = field(default_factory=dict)


@dataclass
class Assessment:
    resource_name: str
    route: Literal["direct", "rebuild", "included"]
    target: str
    rationale: str
    lw_operations: list[str] = field(default_factory=list)


@dataclass
class CodeChange:
    file: str
    summary: str
    diff: str


@dataclass
class Plan:
    resource_name: str
    proposal: str
    lw_operations: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    code_changes: list[CodeChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DryRunCall:
    method: str
    path: str
    operation_id: str
    body: dict = field(default_factory=dict)
    # path param -> operation whose response supplies it (filled in when the migration runs)
    chained: dict = field(default_factory=dict)
    # name of the Azure resource this call migrates
    source: str = ""

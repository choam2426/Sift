"""Source callsite atoms and deterministic stage-2 boundary policies (ADR 0026)."""

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from typing import Literal

from sift.code import Call

Policy = Literal["C", "R", "P"]


@dataclass(frozen=True)
class CallTarget:
    kind: str
    callee: str | None
    name: str
    configs: tuple[str, ...]


@dataclass(frozen=True)
class Callsite:
    id: str
    caller: str
    path: str
    line: int
    start_column: int
    end_line: int
    end_column: int
    code: str
    targets: tuple[CallTarget, ...]
    control_regions: tuple[str, ...]
    passes_values: bool

    @property
    def callees(self) -> tuple[str, ...]:
        return tuple(sorted({target.callee for target in self.targets
                             if target.kind == "direct" and target.callee is not None}))


@dataclass(frozen=True)
class Candidate:
    id: str
    policy: Policy
    caller: str
    callees: tuple[str, ...]
    callsites: tuple[Callsite, ...]


def callsites(calls: list[Call], revision: str | None) -> list[Callsite]:
    """Join configuration-specific interpretations of the same source call."""
    grouped = defaultdict(list)
    for call in calls:
        end_line = call.end_line or call.line
        key = (
            call.caller, call.path, call.line, call.start_column,
            end_line, call.end_column, call.code,
        )
        grouped[key].append(call)

    atoms = []
    for key, interpretations in grouped.items():
        caller, path, line, start_column, end_line, end_column, code = key
        target_configs = defaultdict(set)
        for call in interpretations:
            target_configs[(call.kind, call.callee, call.callee_name)].update(call.configs)
        targets = tuple(
            CallTarget(kind, callee, name, tuple(sorted(configs)))
            for (kind, callee, name), configs in sorted(
                target_configs.items(),
                key=lambda item: tuple("" if part is None else str(part) for part in item[0]),
            )
        )
        regions = tuple(sorted({call.control_region for call in interpretations
                                if call.control_region is not None}))
        identity = {
            "revision": revision,
            "caller": caller,
            "path": path,
            "start": [line, start_column],
            "end": [end_line, end_column],
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        }
        atom_id = "callsite:" + _digest(identity)
        atoms.append(Callsite(
            atom_id, caller, path, line, start_column, end_line, end_column, code,
            targets, regions, any(call.passes_values for call in interpretations),
        ))
    return sorted(atoms, key=lambda atom: atom.id)


def candidates(atoms: list[Callsite], policy: Policy) -> list[Candidate]:
    """Group direct-call atoms with the C, R, or P policy from ADR 0026."""
    if policy not in ("C", "R", "P"):
        raise ValueError(f"unknown candidate policy: {policy}")

    groups = defaultdict(list)
    for atom in atoms:
        if not atom.callees:
            continue
        if policy == "C":
            key = (atom.id,)
        elif policy == "P":
            key = (atom.caller, atom.callees)
        else:
            region = atom.control_regions or (atom.id,)
            key = (atom.caller, atom.callees, region)
        groups[key].append(atom)

    built = []
    for members in groups.values():
        ordered = tuple(sorted(members, key=lambda atom: atom.id))
        member_ids = [atom.id for atom in ordered]
        callers = {atom.caller for atom in ordered}
        callees = tuple(sorted({callee for atom in ordered for callee in atom.callees}))
        if len(callers) != 1:
            raise ValueError("one candidate contains calls from different callers")
        candidate_id = f"candidate:{policy.lower()}:" + _digest({
            "policy": policy,
            "callsites": member_ids,
        })
        built.append(Candidate(candidate_id, policy, callers.pop(), callees, ordered))
    return sorted(built, key=lambda candidate: candidate.id)


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

from backend.app.pipeline.types import CaseStatus, MachineDecision


def status_for_machine_decision(decision: MachineDecision) -> CaseStatus:
    if decision == MachineDecision.PASS:
        return CaseStatus.MACHINE_PASSED
    if decision == MachineDecision.FAIL:
        return CaseStatus.MACHINE_FAILED
    return CaseStatus.NEEDS_REVIEW

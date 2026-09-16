from w_agent import Doctor
from w_agent.skills.sandbox.nsjail_sandbox import NsJailSkillSandbox
from w_agent.skills.sandbox.wasm_sandbox import WasmSkillSandbox


def test_doctor_reports_actual_sandbox_availability():
    doctor = Doctor()
    wasm_ok, _ = doctor.check_wasm_sandbox()
    nsjail_ok, _ = doctor.check_nsjail_sandbox()
    assert wasm_ok is WasmSkillSandbox().available
    assert nsjail_ok is NsJailSkillSandbox().available

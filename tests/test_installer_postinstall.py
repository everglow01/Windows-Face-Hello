"""Run the actual post-install Pascal code in an isolated, unprivileged Inno installer.

Only service/process operations are stubbed. No real service, CP, registry entry,
shortcut or uninstaller is created. Set ISCC to run this on a developer machine.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "FaceHello.iss"


@pytest.fixture(scope="module")
def installer_probe(tmp_path_factory):
    compiler = os.environ.get("ISCC") or shutil.which("ISCC.exe")
    if not compiler:
        compiler = str(Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
                       / "Inno Setup 6/ISCC.exe")
    if not Path(compiler).is_file():
        pytest.skip("Inno Setup compiler not installed; set ISCC to run installer regression")
    work = tmp_path_factory.mktemp("inno")
    source = INSTALLER.read_text(encoding="utf-8")
    declarations = source[source.index("var\n  ServiceExisted:"):
                          source.index("function BackupExistingInstall()")]
    code = source[source.index("function RunPostInstall():"):]
    # Preserve the real state/rollback/exit/UI logic, replacing OS process calls only.
    code = re.sub(r"\bExec\(", "FakeExec(", code)
    run_entry = re.search(r"^Filename:.*postinstall.*$", source, re.MULTILINE).group()
    check = re.search(r"; Check: [^;\r\n]+", run_entry)
    languages = source[source.index("[Languages]"):source.index("[Tasks]")]
    shutil.copyfile(INSTALLER.parent / "ChineseSimplified.isl", work / "ChineseSimplified.isl")
    script = work / "probe.iss"
    script.write_text(
        r'''#define PyExe "{app}\python.exe"
[Setup]
AppName=FaceHello installer regression
AppVersion=1
DefaultDirName={tmp}\FaceHello-test
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputBaseFilename=probe
[Run]
Filename: "{cmd}"; Parameters: "/c echo launched>""{app}\launched.txt"""; Flags: postinstall runhidden'''
        + (check.group() if check else "") + "\n" + languages + "\n[Code]\n"
        + declarations + r'''
var Scenario: String;
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Scenario := ExpandConstant('{param:case|success}');
  ForceDirectories(ExpandConstant('{app}'));
  ServiceExisted := (Scenario = 'success') or (Pos('rollback-', Scenario) = 1);
  if ServiceExisted then begin
    BackupDir := ExpandConstant('{app}\backup');
    ForceDirectories(BackupDir);
    SaveStringToFile(BackupDir + '\sentinel', 'old version', False);
  end;
  if Scenario = 'marker-failed' then
    ForceDirectories(ExpandConstant('{app}\.installed'));
  Result := '';
end;
procedure PrepareAcceptanceBaseline();
begin
  BaselinePath := ExpandConstant('{app}\baseline.json');
end;
function ShouldStartService(): Boolean;
begin Result := False; end;
function ServiceInstallCommand(Param: String): String;
begin Result := 'install'; end;
function StopServiceAndWait(): Boolean;
begin Result := True; end;
function RestoreExistingInstall(): Boolean;
begin Result := Scenario = 'rollback-ok'; end;
function WaitForServiceRunning(): Boolean;
begin Result := True; end;
function FakeExec(Filename, Params, WorkingDir: String; ShowCmd: Integer;
  Wait: TExecWait; var ResultCode: Integer): Boolean;
begin
  if Scenario = 'exception' then RaiseException('injected process exception');
  ResultCode := 1;
  if Scenario = 'success' then ResultCode := 0;
  Result := Scenario <> 'exec-failed';
end;
procedure DeinitializeSetup();
begin
  SaveStringToFile(ExpandConstant('{app}\finished.txt'),
    WizardForm.FinishedHeadingLabel.Caption, False);
end;
''' + code, encoding="utf-8-sig")
    result = subprocess.run([compiler, "/Q", f"/O{work}", str(script)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return work / "probe.exe"


@pytest.mark.parametrize("scenario,exit_code,keep_backup", [
    ("success", 0, False),
    ("configure-failed", 1001, False),
    ("exec-failed", 1001, False),
    ("exception", 1001, False),
    ("marker-failed", 1001, False),
    ("rollback-ok", 1001, False),
    ("rollback-failed", 1001, True),
])
def test_postinstall_outcome(installer_probe, tmp_path, scenario, exit_code, keep_backup):
    target = tmp_path / "app"
    log = tmp_path / "setup.log"
    result = subprocess.run([
        str(installer_probe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/LANG=english", f"/DIR={target}", f"/LOG={log}", f"/case={scenario}",
    ], timeout=30)
    assert result.returncode == exit_code, log.read_text(encoding="utf-8-sig", errors="replace")
    assert (target / "backup/sentinel").exists() == keep_backup
    assert (target / "launched.txt").exists() == (exit_code == 0)
    if exit_code:
        assert (target / "finished.txt").read_text() == "Installation incomplete"

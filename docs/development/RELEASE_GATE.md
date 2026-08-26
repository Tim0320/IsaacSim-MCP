# Release gate

`scripts/release_gate.ps1` 是 Windows / Isaac Sim 6.0.1 的 fail-closed release 檢查。它不會 commit、push、merge 或建立 tag。

## Strict release run

```powershell
.\scripts\release_gate.ps1
```

strict mode 要求 clean worktree，並依序驗證：

1. repository root、branch、HEAD 與 exact GitHub origin。
2. clean worktree。
3. Isaac Sim `6.0.1`、package/extension version、response/capability versions。
4. tracked 與尚未 staged 的 untracked publish candidates，其 filename 與高可信度 credential pattern；不輸出 secret value。
5. `backup_project.ps1` bundle、dirty/untracked snapshot 與 restore comparison。
6. offline unit/contract/adapter tests。
7. Windows PowerShell launcher tests。
8. Ruff lint、本次 publish candidates 的 format check 與 `git diff --check`；不因歷史 baseline 格式漂移誤擋無關 PR。
9. TCP 8766 read-only source-complete live matrix；source inventory 與 runtime command count 必須一致，blocked prerequisite 與 code fail 分開。
10. wheel build、全新 temporary virtualenv install/import/version。
11. worktree fingerprint 前後一致與 Git status review。

結果寫入 ignored `test_outputs/release_gate_result.json`。temporary wheel/venv 位於系統 temp，結束後刪除。

## 開發中的完整預覽

尚未 commit 時使用：

```powershell
.\scripts\release_gate.ps1 -AllowDirty
```

`-AllowDirty` 只放寬起始 clean-worktree gate。腳本仍會比較執行前後 status fingerprint，任何新增、刪除或修改都會失敗。它不代表已達到可發布狀態；正式 release 必須回到 strict mode。

## 有邊界的診斷模式

```powershell
# 沒有 running Isaac Sim 時，只檢查 offline/package；正式 release 不可跳過 live。
.\scripts\release_gate.ps1 -AllowDirty -SkipLive

# unit test 可略過重複備份；正式 release 不可使用。
.\scripts\release_gate.ps1 -AllowDirty -SkipBackup -SkipLive -SkipPackage
```

`-SkipBackup`、`-SkipLive`、`-SkipPackage` 會在 JSON report 標成 skipped。含 skipped 的 run 只能做診斷，不能當 release evidence。

## 發布授權邊界

gate pass 只代表目前 checkout 通過檢查。實際 `git commit`、`git push`、merge、tag 或 GitHub release 仍需要使用者明確授權。發布前後都要重新核對：

- `git rev-parse --show-toplevel`
- `git remote get-url origin`
- `git rev-parse HEAD`
- `git status --short`
- GitHub remote ref

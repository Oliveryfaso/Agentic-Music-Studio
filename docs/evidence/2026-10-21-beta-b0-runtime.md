# Personal Beta B0 runtime boundary closure

2026-10-21; P2.3 -> reviewed-catalog two-piano personal Beta preparation. MF-P16/P17/P18/P21. Baseline21dbd8d; accepted music is unchanged.

The installed launcher/stopper manages only resources bound to its private receipt, exact Docker daemon, project and random owner label. Unknown containers, persistent volumes or networks are refused. Start and stop share a kernel lock; Web PID/root/start-time must match. Stop preserves containers and volumes. Neither entry point starts or stops Colima. This is a narrow runtime boundary acceptance, not the complete product Compose or daily-Beta acceptance.

Installed checks: B0 27; original frontend integration39 plus typecheck; resource fixtures11 and Ruff. The B0 fresh review found two Important findings, both closed in its sole limited repair recheck. The README host-Python prerequisite Minor was then corrected without changing reviewed executable files.

The first real Docker run exposed a separate defect: the resource-inspection Go template omitted the final literal JSON brace. The old fake returned complete JSON regardless of --format, so it had hidden this real boundary error. The original failure is retained. Three relevant tests became RED after correcting the fake; an additional missing-candidate-compose failure is explicitly a fixture issue. A one-character production repair and the faithful three-field fake produced8 focused passes; a separate narrow review found no findings and independently passed3 tests. No ownership condition was relaxed.

The corrected installed code passed real Docker: unknown empty volumes/networks refused, two stop/reopen cycles retained marker data and original owner, repeated stop succeeded. Only fresh randomly named test resources were removed afterward; all27 preexisting container IDs remained. Docker used cached postgres:17-alpine, no published port, no image pull. Shared workloads can change state independently; identity preservation is not a claim that their state was frozen.

Initial sandbox probes could not access the Colima socket and were incorrectly described as host downtime. A formal approved read-only check confirmed the existing VM running. No VM start/stop/reconfiguration or global Docker context change occurred; Docker context colima was supplied for this task only.

New model calls0/cost0. Prior cumulative public-price estimate upper CNY0.059998 is not a bill; the authorized cumulative CNY10 is unchanged. No actual .env/credentials/container Env were read or copied. No new key configuration, main merge, Guide change or public deployment.

Remaining B1/B2: standard loopback profile, reviewed pack readonly mount/pin plus live renderer/API admission, current dedicated images, original-session browser UAT, then one persistent environment real model/edit/reopen/export path and new-target restore. Static UI and valid resource files do not prove these gates.

Machine-readable evidence: [2026-10-21-beta-b0-runtime.json](2026-10-21-beta-b0-runtime.json). The original detailed execution logs, failed response and independent reports remain in the task workspace; no unrelated shared-container inventories or environment contents are published.

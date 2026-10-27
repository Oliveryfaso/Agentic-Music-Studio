# Dispatcher SIGTERM integration after Beta settings update

Personal Beta, MF-P16/P17/P18/P21; source basea703660. Extract the already
reviewed f3913d2 dispatcher-only repair; do not merge its backup dependencies or
cold-recreation draft. Current running image/workers are unchanged.

1. Apply its existing real-entrypoint tests first and observe the two SIGTERM
failures on this source. Synthetic DB/broker boundaries only; signal own children.
2. Reuse only dispatcher.py, resume_dispatcher.py and shutdown.py from f3913d2,
checking their context matches current code. Keep leases, retries and Job contract.
3. Run affected signal/outbox/Celery regressions and static checks; one narrow
independent integration review. Record source/runtime separation and checkpoint.
4. Publish only as an isolated follow-up branch; no image build or lifecycle,
no main merge, no model call, no migration, no new backup or user data access.

This closes source integration, not actual Docker PID1 or real PG cancellation.
The frozen14ce API/Web updater must continue rejecting backend source drift;
future worker activation requires a separately frozen same-version maintenance.

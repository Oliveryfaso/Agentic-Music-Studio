# Personal Beta: first-run prerequisite closure

Stage: Personal Beta, MF-P01/P16/P17/P18/P20/P21.

The isolated public-main checkout installed its locked npm dependencies and built
Web/audio without borrowing the live checkout's node_modules. Its configured
`--check` nevertheless returned ready under Python 3.9, outside the documented
3.12–3.13 contract. No services were started. The live API/Web update is already
complete; this slice must not repeat deployment or modify the running checkout.

1. Test the actual shell entry under supported/unsupported reported tool versions.
   Unsupported Python/Node must fail before configuration reads, runtime receipts,
   storage creation, npm installation or Docker calls; help remains dependency-free.
2. Add the smallest early version diagnostics and align package engines with the
   documented Node 22.12+ floor. Do not install/switch runtimes automatically.
3. Document a fresh-checkout preflight using public configuration and explicit
   Docker context, including the difference between check, build and a running app.
4. Run focused launcher/ownership/settings checks, the normal Web suite and builds;
   recheck the new checkout with supported installed Python. No Compose up,
   migration, ports, model calls, user-data reads or new containers.
5. Independent scoped review, sanitized evidence/status update, local checkpoint
   and normal authorized publication. Preserve Guide revision/state and all older
   failed receipts. Restore/0031 candidates remain isolated dependencies.

Success: unsupported prerequisites produce actionable diagnostics without side
effects; supported versions retain existing first-run behavior. A public clone,
dependency install, build and read-only prerequisite check do not establish a
complete installation, rendered output or browser playback.

Failure label: `FIRST_RUN_UNSUPPORTED_RUNTIME`. Trace/Graph/Eval/DB schemas are
unchanged. This is a deterministic launcher boundary, not a creative/model slice.

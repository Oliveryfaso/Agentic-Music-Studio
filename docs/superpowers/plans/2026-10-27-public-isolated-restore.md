# Personal Beta: publish the isolated restore tools

Stage: personal single-user Beta recovery, MF-P13/P16/P17/P18/P21. Base main
`a703660c40f32e2207b5cfcb554c65a9a1372f05`. Guide revision
`d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`, clean at start; do not edit it.

1. Integrate the already-tested standard-library backup/archive/restore dependency
   set into an isolated worktree; preserve all explicit execution gates. Include
   the creation helpers required by the existing backup CLI and synthetic tests,
   rather than exposing a missing-module subcommand. No new backup is run.
2. Test first: replace the personal fixed backup PIN with required, validated
   `archive_sha256` in the restore contract. Missing/malformed/mismatched digests
   fail closed; never discover a digest and implicitly trust it. Default dry-run
   and help must not read an archive, contact Docker, or create resources.
3. Add portable CLI examples and bounds: macOS/APFS/Colima, schema0030, one
   explicitly owned disposable PG, no public ports/persistent mounts, no current
   application restore, no automated environment creation or deletion. State that
   the earlier PG+media real test covered the frozen predecessor; verify this
   public contract adaptation with synthetic regression, not a new real restore.
4. Run focused RED/GREEN, complete affected maintenance tests, existing Python
   regression that does not need runtime services, static/compile/build checks,
   private-data scan, and one independent review. Correct blocking findings and
   rerun only affected checks. Keep original failed batches and private evidence.
5. Update implementation/evolution evidence truthfully. Scope storage hygiene to
   this worktree's reproducible generated output; preserve all runtime images,
   volumes, works and historical evidence. No Docker, migration, service restart,
   backup, model request, account credential, or new database in this slice.
6. Recheck Guide diff, remote main, and exact staged paths. Commit only code,
   synthetic tests and public docs. Fast-forward push main, never force; verify
   remote SHA and CI/check status. No deploy or release action follows the push.

Success: public users can discover the bounded tools and supply their own trusted
archive identity, with no personal data or fixed private hash shipped. The v2
reader, fixed exec-i transfer, SQL, readonly/resource guards and exit supervision
remain the tested implementation. Failures return bounded diagnostics and retain
evidence; UNKNOWN is never an automatic retry or delete permission.

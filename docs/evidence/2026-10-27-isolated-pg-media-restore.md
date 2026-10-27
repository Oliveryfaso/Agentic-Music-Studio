# Isolated PG and media recovery: evidence boundaries

Stage: personal single-user Beta, MF-P13/P16/P17/P18/P21.

On 2026-10-27, one approved private validation restored an existing v2 backup
into a fresh APFS directory and an owned disposable PostgreSQL 17 container.
It used 1 CPU / 384 MiB memory / 256 MiB PGDATA tmpfs, an internal network,
no published ports or existing mounts, and no model or credentials lookup.

- The predecessor's fixed readonly configuration rejected daemon `docker cp`.
  A separate 216-byte synthetic comparison on Engine 29.5.2 returned the fixed
  `ROOTFS_READ_ONLY` category, while non-root writes in the live tmpfs succeeded.
- The reviewed fix streams the dump through fixed `exec -i --user postgres`
  into an exclusive file. It retains the readonly root, fixed transaction SQL,
  input limits, target admission, and owned-process exit supervision.
- The subsequent private restore returned `pg_restore` exit 0 and matching
  schema0030 summaries for 39 tables and 3 sequences. All 40 media files and
  the dump matched their expected sizes and hashes. The controller completed
  in approximately 3.18 seconds; no memory-peak claim is made.
- The test PG exited normally without OOM. Its exact container and empty
  network were removed; subsequent read-only checks confirmed their absence.
  Existing Beta container identities / images / states / start times and three
  readiness responses were unchanged. Restored files and the original archive
  remained local. Earlier failed or unknown attempts were not rewritten.
- Independent review checked the frozen implementation and original restore /
  exit / cleanup receipts. Mainline separately reconciled retained-file hashes,
  its known process group, and the current absence of temporary resources.

## Public adaptation

The public CLI replaces the private fixed hash with mandatory caller-supplied
`archive_sha256`; that identity must come from a trusted source. The public
contract change has synthetic RED/GREEN and regression evidence, not a second
private-data run. The maintenance suite currently passes 266 tests; two cases
skip because the fixture filesystem folds case and normalizes Unicode.
Import / help and valid default dry-run have explicit no-side-effect checks.
The broader Python run passes 1,418 tests (including those maintenance tests),
with 95 skips for disabled external integration or filesystem prerequisites and
one existing Starlette dependency deprecation warning. Web 203 and audio 124
tests, type checking, Web/audio builds, and the new files' Ruff checks pass.

Independent review found that a case alias could bypass lexical source overlap
after generalizing the archive identity. The public candidate now compares
device/inode identities of a present source and target ancestors before writing;
unknown source identity fails closed. A real synthetic case-alias fixture and
permission-error rejection went RED/GREEN, with a retained missing-source
success case. One narrow independent repair review closed this finding. This is
an additional public safety guard, not a newly executed private-data restore.

No private archive hash, real contract, absolute personal path, project content,
database, media, secret or raw execution log is included here. The modules use
the standard library; existing backup creation helpers are included so the
visible backup CLI has no missing lazy dependency. No new backup, database,
deployment, runtime pin change or paid request occurred in public adaptation.

This proves the predecessor's isolated **PG + media recovery**, not startup of
the restored application, resumed AI work, browser playback, native download,
0031 compatibility, arbitrary backup provenance, or disaster recovery.

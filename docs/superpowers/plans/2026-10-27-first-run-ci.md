# First-run prerequisites and credential-free CI

Stage: personal Beta reproducible source entry, MF-P01/P16/P18/P21. Base main
`ec2ff5b4140b574f64ad0ca81c254eaae150b39c`. Guide remains at
`d68b900bd8dce6c5786dd0b6c6b531429c9d38a2`, clean; do not edit it.

1. Test-first: default and reviewed profiles must reject missing Vite with an
   actionable `npm ci` message before private configuration, runtime/storage
   writes or Docker. Preserve version checks and dependency-free help. Remove
   the late implicit `npm install` path, without changing startup ownership.
2. Correct the new-user health-check documentation. The historical Compose
   integration script also runs jobs/stops dispatchers and pins an obsolete
   migration; do not execute or rebuild it as incidental cleanup.
3. Add minimal public-repository GitHub CI: pinned official checkout/runtime
   actions, read-only permissions, standard Ubuntu runners, bounded job time,
   frozen Python/npm dependencies, unit regression and Web/audio build checks.
   No secrets, real model, service containers, database or deployment. Validate
   the rendered no-Key Compose configuration without starting its services.
4. Check workflow safety and default no-Key boundaries with focused tests.
   Use only known locked project dependencies and existing runtimes. In a fresh
   source snapshot verify dependency installation and read-only diagnostics;
   do not connect to production data or run normal startup. Missing-resource
   diagnostics are not a successful complete installation or generation.
5. Run affected then stage-final offline regression, type/build/static checks,
   and independent review. Integrate other original sessions' patches only
   after checking their scope, hashes and tests. Keep their writing areas separate.
6. Publish only reviewed code/tests/docs to main by fast-forward, verify remote
   SHA and this workflow's actual result. Keep logs/config/cache outside Git.
   Public CI proves regression, not true-Key generation or full-stack first-run.

Runtime scope: zero current-service changes, containers, migrations, new real
backups, production reads/writes, real credentials or model calls. Any real
from-scratch service stack requires a separately bounded plan and confirmation.

# Reviewed piano preparation (candidate, explicit opt-in)

The default demo is synthetic. The reviewed piano Beta needs a separate, exact pack.
Use the previously reviewed FreePats archive, not the current 2022 full pack:
https://freepats.zenvoid.org/Piano/UprightPianoKW/UprightPianoKW-small-SFZ-20190703.7z
This is the historical contract URL, not a newly checked availability promise.
Archive SHA256: ffb547fceb91eeb93d78cf8d220d1d5f726dcac891afc15e517805ac48abb39d.
License/credits and sample pins remain in scripts/resource-contract.v1.json.
The bundled manifest is the exact previously reviewed manifest, not inferred SFZ conversion.

```
python3 scripts/prepare_reviewed_piano.py --archive /chosen/source.7z --destination /chosen/new-pack
# Only explicit execution reads the archive and writes a fresh destination:
python3 scripts/prepare_reviewed_piano.py --archive /chosen/source.7z --destination /chosen/new-pack --execute
```

Requires an already available bsdtar supporting this archive's filters, or explicit
--seven-zip /path/to/trusted/7zz. No automatic tool fallback. Some macOS
versions cannot decode its WAV filter; failure is expected on those versions.
No tool is installed or downloaded. No mount, permission, service or resource pin changes.
The archive is snapshotted and hash-checked before member-only stdout extraction;
archive paths are never extracted to disk. Each output is bounded and hash-checked.
Run in a user-owned directory without concurrent writers. Target must not exist.
Failures during final copying may leave a partial destination: retain it, do not
reuse/overwrite it. This is not atomic publication or a crash-durability guarantee.
A successful preflight is not audio playback, VM visibility or Beta readiness.
Real 2019 archive preparation was separately verified on 2026-10-26 using
previously approved 7-Zip 26.04, in a fresh isolated directory: 26 samples
passed the original preflight. This does not prove bsdtar compatibility.
Decoder output is bounded per member, with a 120-second decode deadline.
Historical conversion-losses files remain historical; later catalog approval is
recorded in docs/evidence/2026-10-20-p23-catalog.md.

## Public demonstration asset record

For each future public asset record: id, kind (ui-screenshot/video/audio), source
commit, fixture identifier, creation date, generator command, sha256, license and
credits, input provenance, verification scope and explicit limitations.
UI capture uses scripts/run_product_ui_smoke.mjs and its isolated API fixtures.
Its silent PCM is a UI fixture, never an audio sample or model-generation result.
New palette screenshots must come from actual rendering and visual review.
Real audio additionally records Revision/engine/pack versions and actual render
receipt. Never source public examples from private projects by default.
No new screenshot, video, audio, model call or private project copy is included here.

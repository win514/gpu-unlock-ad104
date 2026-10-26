# Evidence

Raw logs from the two kinds of run this pipeline produces. They are unedited
except for the removal of nothing — the profiler does not record host names, user
paths, serial numbers or MAC addresses. What they do contain are hardware
fingerprints of one board (`10de:2783`, subsystem `1458:41b0`, BDF
`0000:02:00.0`, ROM digest) which are attributes of the card model, not of the
person.

| File | Run | Size | What it proves |
|---|---|---:|---|
| `RUN00-PROFILE.TXT` | `--mode diag` | 3 048 B | the collected board profile: chip `0x194000a1`, BAR0 `0x8c000000`/16 MiB, FEAT PLM `0xffffff8f`, SS0 `0x53477150`, VRAM `0x2ffa`, ROM `55a69c17…`, PROM `ada4bcaf…` |
| `RUN00-REPORT.TXT` | `--mode diag` | 3 671 B | the same run from the application's own log, including every 32-bit config-space dword |
| `SELECTORS-OK-REPORT.TXT` | `--mode unlock --auto` | 29 505 B | one complete transaction: FWSEC, SEC2 launch, `marker=0x67b00001`, four PLM readbacks, `SS0 0x53467050 → 0x88888888`, `SS1 0x7 → 0x8`, FLR, `POST-GOP` selectors, `FINAL status=0 clean=1` |

`SELECTORS-OK-REPORT.TXT` is the run that reached `clean=1` — i.e. the
transaction that succeeded and still produced no throughput gain. It is the
central artefact of this repository: it shows a fully green transaction, so the
negative benchmark result cannot be explained by a failed attempt.

## Reading a report

Useful lines, in order of appearance:

```
cold state: chip=... plm=... WPR2_HI=... SS0=... SS1=...
AD102 PLM initial: index=N target=NAME value=... expected=...
AD102 SINGLE RESULT: ... marker=... marker_ok=... cpuctl=... debug=...
SELECTOR RESULT: SS0 before=... after=... matched=...
POST-FLR SS0=... SS1=...
POST-GOP SS0=... SS1=...
transaction result=N containment=... quiesced=... retained=... FLR=N
FINAL status=N stage=... attempted=N driver_release=N clean=N
```

`CHECK stage=<name> status=<code>` lines mark gate transitions; a non-zero code
is `0x8000000000000000 | EFI_STATUS`. Common values:

| status | EFI name | usual cause |
|---|---|---|
| `0x3` | `EFI_UNSUPPORTED` | identity/class/BAR mismatch |
| `0x6` | `EFI_NOT_READY` | cold-state gate: WPR2 still reserved, or selectors read 0 |
| `0x7` | `EFI_DEVICE_ERROR` | an IO step failed |
| `0x15` | `EFI_ABORTED` | operator pressed Esc |
| `0x13` | `EFI_TIMEOUT` | arming window elapsed |

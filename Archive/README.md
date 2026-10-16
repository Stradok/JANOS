# Archive

History and retired material. **Nothing here is needed to run JANOS v2.** It is kept
because it records how the project got here.

| Folder | Contents |
|---|---|
| `logs/` | Development session logs and chat logs by date (June 2026 onward), phase reports, status notes, and `PLANNING/` |
| `legacy-docs/` | Documentation for the retired v1 stack (JAN): old READMEs and the old architecture report |
| `notes/` | Loose personal notes |
| `tools/` | Large third-party binaries (the Windows ffmpeg build) |
| `assets/` | Stray audio samples from v1 |

## Notes

- The v1 module `jarvis-core/core/log_bootstrap.py` used to read `jarvis-core/logs/*.md` at startup
  to seed memory. The logs now live here, so that retired code no longer finds them. JANOS v2 does
  not read them.
- Move new session logs here (`Archive/logs/YYYY-MM-DD_Topic.md`) rather than into the code tree.
- The current architecture is in [`../docs/`](../docs/).

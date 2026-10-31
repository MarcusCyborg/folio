# Folio GitHub clone verification

Date: 2026-10-31 (Asia/Saigon, UTC+07:00).
Parent verification time: 23:21:34 local time.

## Result

- Clone executor: GPT-6.1 Sol subagent, after the Gemini attempts did not execute the assigned clone task.
- Source: https://github.com/MarcusCyborg/folio.git
- Destination: `F:/dpl13.10/WikiSearchEngine-github`
- Branch: `main`
- HEAD: `c4b19cffa676b4437e7346da2c410b198b04dc2c`
- Remote main SHA verified by the clone executor: `c4b19cffa676b4437e7346da2c410b198b04dc2c`
- Working tree immediately after clone: clean (`git status --short` returned no entries).
- Parent separately verified HEAD, origin and clean status before adding handoff documents.

## Commands used

```powershell
git clone --branch main --single-branch https://github.com/MarcusCyborg/folio.git F:/dpl13.10/WikiSearchEngine-github
git remote -v
git branch --show-current
git rev-parse HEAD
git ls-remote origin refs/heads/main
git status --short
git log -5 --oneline --decorate
```

Git checks use the clone as working directory. If ownership warnings occur in the sandbox, use per-command `-c safe.directory=F:/dpl13.10/WikiSearchEngine-github`, not a wildcard or a global configuration change.

## Recent history

```text
c4b19cf chore: move public screenshots outside the repository
d42743e docs: import setup guides and project documentation
5a926bf test: import automated checks and screenshot scripts
83080ef feat(admin): import administration interface
93cf8d5 feat(frontend): import library interface and shared assets
```

The remote history was rewritten relative to the old local checkout at `ab0f5fe`. This is not an ordinary fast-forward. A direct tree comparison of `ab0f5fe` and `c4b19cf` found:

- `.gitignore`: excludes `/docs/screenshots/`.
- `README.md`: documents public capture output outside the repository.
- `scripts/capture_screenshots.py`: resolves output to the repository parent's `screenshots/` directory.
- Eight old public screenshot files were removed from Git.
- No tree differences in `src/`, `tests/`, `alembic/` or the three requirements files. Verified with `git diff --quiet ab0f5fe c4b19cf -- src tests alembic requirements.txt requirements-dev.txt requirements-legacy.txt` in the old checkout; exit code 0.

The history reorganization therefore does not establish that Phase 2 has been implemented.

## Handoff documents added after verification

The parent task adds only these documents to the new clone:

- `FOLIO-COMPLETION-PLAN.md`: updated workspace/baseline and screenshot/setup requirements.
- `GEMINI-EXECUTION-PROMPTS.md`: updated P00-P09 prompts, explicit workspace checks and integration checkpoints.
- `docs/handoff/gemini/CLONE-REPORT.md`: this report.

These documents are intentionally untracked until reviewed/committed. Application source remains at the GitHub baseline. No commit, push or deployment is part of this handoff.

## Environment and validation limits

- Inspected repository structure includes README, requirements, Alembic migrations, backend/frontend sources, tests, portable fixtures, evaluation and crawler directories.
- `.env`, virtualenv, database files and ignored `data/` were not copied from the old checkout.
- No dependency installation, database migration, seed, model download, app run or test suite was executed in this new clone.
- The previous 58-test pass belongs to the old checkout/environment. P00/P02 must establish evidence for the new clone.
- Public capture output defaults to `F:/dpl13.10/screenshots/`. Do not run multiple worktrees against that shared destination; P02/P07 should make output configurable and isolate each run.

## Next action

Open `F:/dpl13.10/WikiSearchEngine-github` as the workspace for the next Gemini/Sol chat. Execute only P00 from the updated prompt pack. Treat absent environment/database prerequisites as setup work for P02, not as evidence that the source is broken. Preserve the old checkout and its pre-existing edits/data.

# Updating the register repo

The short version, for when you've changed the code and want it saved:

```bash
cd ~/dockers/register
git add -A
git commit -m "what you changed"
git push
```

That's it. Everything below is detail for when something goes differently.

## The everyday loop

You edit code in `~/dockers/register` and deploy it the usual way:

```bash
docker compose up -d --build
docker logs register | head -5     # confirm it actually rebuilt
```

Once you're happy it works, commit. **Commit working code, not
in-progress code** — the point of history is being able to go back to
something that ran.

```bash
git status --short      # what changed. .env must NOT be listed.
git diff                # what changed, in detail
git add -A
git commit -m "Add nightly cap to summary refresh"
git push
```

Write commit messages for future-you reading `git log` at 11pm: "fix bug"
is useless, "stop summary refresh running all projects at once" is not.

## Before you push, every time

```bash
./secretscan.py .
```

Exit code 1 means a credential was found — do not push. This takes two
seconds and is the only thing standing between a stray key and a public
repository. Install it as a hook and it runs itself:

```bash
./secretscan.py --install-hook ~/dockers/register
```

After that, `git commit` refuses to complete if it finds a critical.

## Common situations

**"I want to see what changed since the last commit"**
```bash
git diff                # unstaged changes
git log --oneline -10   # recent history
git show HEAD           # the last commit in full
```

**"I broke it and want to go back"**
```bash
git checkout -- register.py        # undo changes to one file
git reset --hard HEAD              # undo everything uncommitted (destructive)
git log --oneline                  # find a good commit
git checkout <hash> -- register.py # restore one file from that commit
```

**"I changed things on two machines"** — unlikely here, but if push is
rejected:
```bash
git pull --rebase
git push
```

**"I committed something I shouldn't have"** — if you have *not* pushed:
```bash
git reset --soft HEAD~1    # undo the commit, keep the changes
```
If you *have* pushed and it was a credential: **rotate the credential**.
Removing it from history does not un-publish it. Rotation first, tidying
second.

**"What's in the repo that shouldn't be?"**
```bash
git ls-files            # everything tracked
git check-ignore -v .env  # confirm .env is ignored
```

## What belongs in the repo

In: code, templates, static files, `Dockerfile`, `docker-compose.yml`,
`.env.example`, `README.md`, the helper scripts.

Out: `.env` (real values), anything with a key in it, `__pycache__`, logs,
the vault itself, and personal notes like handoff documents — those live
in the Obsidian vault, not here.

The split to keep in mind: **the repo holds how it works, the vault holds
what you were doing.** If you're unsure which a file is, ask whether a
stranger cloning the repo would need it.

## When you next change the code

The handoff document's Code section should say "see the repo" rather than
reproducing files. That's the payoff for doing this: the handoffs stop
growing, and the code has real history instead of a folder of zips.

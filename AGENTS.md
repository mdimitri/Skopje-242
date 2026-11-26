# AGENTS.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

## Game technical context

- For each new game-related task or question, start with the [technical context index](technicalContext/README.md). Follow only the pages and sections relevant to the request. In the same chat, reuse context while current and reread affected sections if they changed or are no longer available.
- Answer from the technical context when it is sufficient. For edits, verify the target code or data and the interfaces the change relies on. If you need more evidence, follow the closest source pointers and widen the search only as needed. Current source takes precedence.
- Before finishing any game change, review the affected technical context and refresh its facts, source pointers, or durable design decisions in the same change when needed. Keep the index short and put detail in the relevant page. Changes that leave the context accurate need no documentation edit.

## Road network rulebook

For every road-network build or algorithm adaptation, read and apply the user constraints in [`RoadNet rulebook/RoadNet rulebook.txt`](RoadNet%20rulebook/RoadNet%20rulebook.txt). Treat them as acceptance limits for road surfaces, markings, raised pedestrian areas, medians, traffic furniture, gantries, crossings, and vehicle behavior. Check the generated or adapted result against every applicable rule. When a rule is violated, attempt to adjust the algorithm and recheck. If it remains unsatisfied after reasonable attempts, report the specific rule, what was attempted, and the remaining limitation to the user; do not silently accept or claim compliance. Keep the rulebook as the canonical wording and update this instruction if its location changes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Repo sync workflow (Claude and Codex)

- Every code or asset change ends on remote `main`: `git pull --rebase`, then `git push origin main` (no PRs).
- Never leave work uncommitted at the end of a task.
- Run `git status` before bumping the build number; "Build N" commits must not leave untracked source or assets behind.
- Start each task with `git fetch` and rebase onto `origin/main`.
- If `git status` shows changes, inspect every path and always try to preserve and integrate all repository changes (source, assets, documentation, and patches) with the requested work, then commit the combined changes to `main`. Do not stop solely because the working tree is dirty. Keep the explicitly excluded user and generated state out of commits. Never discard or overwrite existing work; if a conflict or unclear ownership prevents safe integration, explain the specific blocker and ask how to proceed.
- Never commit `settings.json`, `saves/`, `output/`, `tmp/` or built world data.

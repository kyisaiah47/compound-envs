# Compound Evals

One RL evaluation environment per Compound Labs product with a real backend. An environment is a
resettable sandbox of the real product that an AI agent acts in, and its graders read Postgres
rows rather than the rendered page, because a web app returns 200 and paints a success toast
whether or not the write landed.

The umbrella is **Compound Evals**, the things inside it are **environments**, and what comes out
is **eval results**.

```
uv run python tools/validate_results.py            # every environment, fails closed
bash envs/<slug>-desk/scripts/up.sh                # schema, fixture, the app on its own port
uv run python envs/<slug>-desk/adversarial/prove_graders.py
```

## What is here

| | |
|---|---|
| environments | 24 |
| tasks | 109 |
| scripted cheats, every one scoring 0.0 | 951 |
| guards | 841 |
| expectations across every suite | 1,085 |
| tasks driven through a browser | 43 |
| routes and workflows recorded as not gradable, with a reason each | 190 |
| live defects found in the products | 92 |

Every figure above is recomputed from the `results.json` files by `tools/validate_results.py`,
which is also the thing that refuses a results file that has drifted from the graders it claims
to describe.

## The environments

| environment | tasks | cheats | guards | browser | suite | ungraded | what an agent does in it |
|---|---|---|---|---|---|---|---|
| agentwire-desk | 4 | 27 | 22 | 3 | 31/31 | 7 | put a reader on the digest and finish a double opt in on the right Wren |
| breachprobe-desk | 5 | 57 | 40 | 2 | 62/62 | 10 | run the free scan, then produce the paid report for an order that was paid and never fulfilled |
| cardchase-desk | 4 | 37 | 58 | 2 | 41/41 | 5 | approve both halves of a recovery rung, and pull back the pair already counting down |
| clausewatch-desk | 5 | 37 | 66 | 1 | 47/47 | 9 | book a lease that states two different end dates, and close a row nobody may act on |
| covercheck-desk | 5 | 32 | 47 | 3 | 37/37 | 7 | file a certificate against the right vendor, with the agent's address and one community |
| fetchdue-desk | 9 | 74 | 67 | 0 | 90/90 | 21 | chase, kill, dispatch, run the ladder, sever a rail, assess late fees, close promises, import a book, split a balance |
| frontwire-desk | 6 | 43 | 35 | 4 | 49/49 | 7 | complete one reader's double opt in and honour one opt out, among lookalike addresses |
| leadgrade-desk | 6 | 47 | 40 | 2 | 53/53 | 12 | run the overnight scoring pass inside an enrichment cap, and approve the right namesake |
| matchline-desk | 3 | 25 | 15 | 1 | 28/28 | 7 | start a check on a pasted posting and resume, and honour a buyer's own delete link |
| matchrail-desk | 6 | 51 | 43 | 1 | 59/59 | 9 | approve a three way match correction on the right bill, and kill one without losing the record |
| outrip-desk | 6 | 39 | 38 | 2 | 45/45 | 8 | open a paid booster that was never torn, and honour the published Rare guarantee on the tenth |
| parserail-desk | 5 | 38 | 33 | 3 | 43/43 | 7 | mint an API key whose name is already taken, and revoke the leaked one and nothing else |
| popwire-desk | 4 | 36 | 27 | 3 | 40/40 | 7 | work the rundown's subscribe form and finish the right Soraya's opt in |
| soft-money-journal-desk | 3 | 45 | 24 | 2 | 48/48 | 5 | put a reader on the letter and take one off, without touching the sibling publication |
| stacktab-desk | 4 | 41 | 29 | 1 | 45/45 | 8 | re-read every vendor's pricing page and re-check the published figures, rewriting none |
| standup-desk | 4 | 33 | 35 | 2 | 37/37 | 4 | sign a reader up, and collect a membership paid for before the account existed |
| starreply-desk | 4 | 26 | 26 | 1 | 31/31 | 7 | rewrite a held review reply so it promises nothing, and kill one that is queued |
| still-mornings-desk | 3 | 41 | 26 | 2 | 44/44 | 8 | put a reader on the letter and take one off, through the link her own mail carried |
| thismuchweknow-desk | 2 | 25 | 14 | 2 | 27/27 | 7 | put a reader on the letter, and put one who opted out back on |
| triagedesk-desk | 8 | 88 | 68 | 0 | 105/105 | 11 | approve, take back, kill, dispatch, run the overnight pass, apply billing events, work the Slack card, drop an uninstalled workspace |
| unemploy-desk | 4 | 16 | 25 | 1 | 20/20 | 4 | file a charge statement, start its audit, and record a determination against the right claimant |
| usingitup-desk | 3 | 36 | 22 | 2 | 39/39 | 7 | put a reader on the letter and take one off, leaving the second publication alone |
| whyyourbraindoesthat-desk | 2 | 22 | 15 | 2 | 25/25 | 7 | put a reader on the letter and finish an unsubscribe on its own token |
| wirecall-desk | 4 | 35 | 26 | 1 | 39/39 | 6 | stake the caller's one call on today's slate, and run the tick that settles yesterday's |

## The rules these were built under

`BUILDING-AN-ENVIRONMENT.md` carries twelve, and four of them cost a full rewrite before they
were written down.

1. **Tasks come from the ROUTES, never from the schema.** A table existing does not mean the app
   can write to it. unemploy has `cd_drafts` and no draft writer anywhere in the product, and
   three graders were written against a workflow that does not exist.
2. **Check what the UI renders for a REAL account, not the demo one.** unemploy's
   `workspaceSlices()` returns hardcoded empty arrays for six of its seven collections on any
   account that is not the demo, so a task whose rows never appear on screen cannot be a browser
   task. That is why 43 of the 109 tasks are browser tasks and the rest are API or cron tasks:
   each one was driven first.
3. **Every reward reads database rows.** Never the page, never the HTTP status, never the model's
   own account of what it did.
4. **Every task is written twice**, once as the work and once as how a capable model fakes it
   cheaply, and the good cheats come from the product's own seams.
5. **The honest case is tested beside the cheats**, because a grader can be green for the wrong
   reason. The reference suite once read 13 of 14 with three cheats passing on the wrong check.
6. **The product's own `npm run build`, never `npx next build`.** Several products put a prebuild
   in front of it that derives generated files and asserts byte-for-byte carries, and
   `npx next build` skips every one.

## What could not be graded, and why

190 routes and workflows are recorded in `not_gradable`, one entry each, with what blocks it.
The shapes:

* **Stripe, 38 entries.** No environment makes a real Stripe call and no environment holds a
  Stripe key. Where a route needs one, the rows a webhook would have written are seeded and what
  happens afterwards is graded instead.
* **A pure read, 22 entries.** The route returns rows and writes none, and every reward here
  reads rows.
* **A model key, 10 entries.** The paid inference keys are spent by a paying customer's own
  request inside a shipped product and by nothing else, not even to check a key works. Where a
  product has an inference rail, the refusal branch is graded instead, which is a real branch:
  the rail answers not-ok and the product writes its deterministic fallback with the reason on
  the row.
* **A mail or SMS rail, 8 entries.** No rail is reachable, which is what makes "nothing was sent"
  a check rather than a hope: a row reading `sent` is a claim about mail that could not have left
  the building.
* **A shared table or a shared account, 7 entries.** One Supabase stack serves every environment,
  so a route that truncates or renumbers something shared is out of reach of a fixture.
* **OAuth with a third party, 5 entries.** Connecting needs an app registration and a live code
  exchange. Disconnecting touches nobody and is a task in three environments.
* **The rest, 100 entries.** Single-row CRUD with no seam, one-off migrations, admin backfills,
  cache revalidation and session plumbing, each named with its own reason.

## The defects the build found

92, recorded in the `defects` array of each environment's `results.json` with where, how severe
and whether it is fixed. 74 are fixed in the products and committed there separately from the
environment work; 18 stay open and recorded. Every high- and medium-severity finding is fixed.

Every one was found by grading rows rather than pages, and most of them look fine from the
outside, which is the point.

**Anything reachable by a stranger.** `POST /api/scan` on BreachProbe and `POST /api/posting` on
MatchLine were unauthenticated SSRF sinks: the caller names any url, the server fetches it,
follows redirects to any other host, and hands the body back. ParseRail's `POST /mcp` sent the
caller's own live API key to whatever host the request's `x-forwarded-host` header named.
TriageDesk's `slackPostTo()` fetched a url taken straight from an interaction payload. LeadGrade
and MatchRail both trusted an unsigned, caller-supplied OAuth `state` as the account identity, so
a request with no cookies and somebody else's uuid wrote a live grant into their book. All five
are fixed.

**A wildcard in an email address.** Standup, FrontWire and OutRip all looked a paying customer up
with `.ilike`, and PostgREST treats `_`, `%` and `*` in an ilike value as wildcards, all three
legal in an email local part. An underscore in a buyer's address granted their membership to a
different account. All three are fixed.

**A row claimed by a dispatcher and never resolved.** FetchDue, TriageDesk and MatchRail all
claim a row to an in-flight status, and in all three the candidate select, the claim and the undo
route matched only the pre-claim status. A tick that claimed a row and then died left it
delivered to nobody, failed to nobody and invisible to every later sweep, while the console drew
it as live. TriageDesk's and MatchRail's send calls were not inside a try/catch either, so one
throw abandoned the rest of the sweep. All three are fixed, with the same shape: the in-flight
call is wrapped, and each sweep opens by finalising any claim older than thirty minutes as
failed, never as sent.

**A control that does nothing.** Every control on TriageDesk's console posted the THREAD id to a
route keyed on the DRAFT id, so Approve, Edit, Kill and Take it back answered 404 for every
signed-in customer. Its `/rails` page offered a full strength Connect button for a rail whose
OAuth application is not registered, while the module written to prevent exactly that had zero
call sites. Both are fixed.

**A build that could not ship.** LeadGrade imported a `vercel.json` its tree does not carry and
StackTab carried a raw apostrophe in JSX, so neither repo could build at HEAD and no commit made
to either could reach its site. Both are fixed.

**A site behind its own lane.** This Much We Know was 23 episodes behind the channel, and the
generator its own source header named did not exist. Still Mornings and Soft Money Journal both
read `publication_posts` at request time and both reached exactly one surface, `/rss.xml`, while
their own headers said an entry the lane posted tonight is on the site with no deploy. All three
are fixed, and six publications' `ops/render-gate.mjs` wrappers, which pointed at a gate that was
purged on purpose and exited 0 anyway, now refuse instead.

**What stays open.** 18 low-severity entries remain recorded. The release-blocking findings are
closed: every high and medium item now has a product-side fix, a passing build or direct runtime
verification, and its source commit. Each remaining low item still names its file and its
measurement rather than disappearing from the record.

## Where the scores go

Nothing in a build writes a score. `task.scores` and the top-level `models` object ship empty,
and whatever runs a model against an environment writes both at once, so a number is never a bare
figure with no provenance.

⛔ **A score is only ever produced on a free rail**, the Gemini free tier or Codex headless. No
paid key is spent to make a number, so anyone can re-run it and there is no objection that a
flattering result was bought. `RESULTS-SCHEMA.md` refuses any other value for `rail`.

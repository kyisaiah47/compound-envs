# popwire-desk

An RL evaluation environment for **Popwire** (`popwire.thecompound.tech`,
`~/CompoundLabs/popwire`), a wire that reflects an automated account's own feed: it publishes the
stories that account posted, each one carrying the copy that went out, the card that went out and
the outside reporting resolved at post time, and it mails one digest a day.

Four tasks, thirty-six cheats, twenty-seven guards. Every reward reads database rows. None of
them reads a page, an HTTP status, or the model's own account of what it did.

```
./scripts/up.sh                                                 # schema, fixture, lane, app on 3747
uv run python envs/popwire-desk/adversarial/prove_graders.py    # 40/40, exit 0
uv run python tools/validate_results.py popwire-desk            # exit 0
node envs/popwire-desk/harness/rollout.mjs                      # the three list tasks, in Chrome
```

## The tasks

| id | driven | route | writes |
|---|---|---|---|
| `put-the-reader-on-the-list` | browser+api | `POST /api/subscribe` | `popwire_subscribers` |
| `confirm-the-subscription` | browser+api | `POST /api/subscribe/confirm?token=` | `popwire_subscribers` |
| `take-the-reader-off-the-list` | browser+api | `POST /api/subscribe/unsubscribe?token=` | `popwire_subscribers` |
| `mirror-the-days-posts-onto-the-index` | cron | `node scripts/mirror-posts.mjs` | `popwire_posts` |

Every guard and every cheat is enumerated in `results.json`.

## What the routes actually do

The tasks were written from this list and not from the schema. Read out of `src/app/api`,
`src/lib` and `scripts/` on 2026-09-19.

```
POST /api/subscribe               upsert popwire_subscribers, then send the confirmation
GET  /api/subscribe/confirm       renders a button. WRITES NOTHING.
POST /api/subscribe/confirm       popwire_subscribers.confirmed, matched on confirm_token
GET  /api/subscribe/unsubscribe   renders a button. WRITES NOTHING.
POST /api/subscribe/unsubscribe   popwire_subscribers.unsubscribed_at, on confirm_token
GET  /api/digest-items            renders the digest behind CRON_SECRET. WRITES NOTHING.
GET  /api/ranked                  read only
GET  /api/search-index            read only
/feed.xml, /robots.txt, /sitemap.xml, /llms.txt   read only
scripts/mirror-posts.mjs          upsert AND DELETE popwire_posts
scripts/verify-cf.mjs             a deploy probe
scripts/verify-alternatives.mjs   a link checker
compound-ops/lanes/popwire/scripts/send-digest.mjs   popwire_email_sends, needs a live Resend key
```

A `GET` on either mail-link route renders a one-button form and only the `POST` writes. That is
not a detail. Corporate mail security prefetches every url in an inbound message, so a
confirmation a `GET` could complete would fire on DELIVERY of the confirmation email, and an
unsubscribe on `GET` would remove every subscriber behind such a gateway on the first issue they
were ever sent. Both routes carry a long comment saying exactly that, and the unsubscribe route
carries the estate's own receipt for it: a contact marked at 23:55:10.548 and an opt-out at
23:55:12.701, 2.1 seconds later. Two of the cheats here are that prefetch, and both must leave
the database untouched.

## Rule 1 in the shape it took here: the engine is half outside the repo, and half outside the estate

`popwire_posts` has exactly one writer and it is not a route. `scripts/mirror-posts.mjs` lives in
the product repo and reads four things, three of which are not in it:

- `public.social_posts` where `app = 'popwire'`, the estate-wide posting ledger that
  `compound-ops/tools/_ledger.cjs` writes on every landed post for every product.
- `~/CompoundLabs/compound-ops/social/popwire/ledger.jsonl`, the harvest's own ledger.
- the same lane's `reporting.jsonl`, the coverage `agent.mjs` banked at post time.
- **the account's live Bluesky author feed**, for the card (matched by alt text) and the source
  link (read out of the self-reply's richtext facets).

`scripts/up.sh` builds a fixture lane at `envs/popwire-desk/lanehome/` and
`harness/no-outbound.mjs` answers the Bluesky feed and the Bluesky image CDN offline from
`envs/popwire-desk/fixture/`. Nothing here polls anything and no task is graded on what any feed
carried this morning.

**The lane path is not configurable in this product, and that is worth knowing before you copy
the sibling's approach.** Agentwire's mirror takes an `AGENTWIRE_LANE` environment variable.
Popwire's has

```
const LANE = path.join(os.homedir(), 'CompoundLabs/compound-ops/social/popwire');
```

with no override anywhere in the file. `os.homedir()` answers `$HOME` on POSIX, so the run is
given its own `HOME` and the real script is pointed at the fixture lane without a byte of the
product changing. Unlike Agentwire's, this mirror imports no lane CODE at all, so nothing is
copied out of the lane and there is no stub to grade by accident.

## The mirror deletes, and the table is shared

`popwire_posts` is not Popwire's alone on this stack. `wirecall-desk` creates the same table and
seeds six `wcdesk-%` rows into it, because WireCall settles a slate by re-reading the two wires it
covers. Measured 2026-09-19: those six rows were sitting in it before this environment existed.

And `scripts/mirror-posts.mjs` ends by deleting every row it did not just write:

```
const orphans = (all || []).map((r) => r.slug).filter((s) => !keep.includes(s));
```

That is correct in production, where the table is Popwire's own, and it is the opposite of
Agentwire's mirror, whose header states it never deletes. The two wires are different products:
Agentwire is an archive of repos, Popwire is a reflection of an account's feed, and a row the
account has no post for is a story this site is claiming and did not run.

Measured 2026-09-19: the first honest mirror run here removed all six `wcdesk-%` rows. So
`run_mirror()` in `adversarial/prove_graders.py` snapshots every foreign row, runs the real script
unmodified, and puts them back in a `finally`. The suite reads the foreign row count before the
first case and checks it again at the end, and fails on a change, so rule 11a's last line ("prove
it: your suite must pass with another environment's rows sitting in the same table") is checked
rather than promised. `sql/02-seed.sql` deletes `marrowgate-%` and `app = 'popwire'` and nothing
else; every guard counts `marrowgate-%` and `%@pwdesk.invalid` only.

## Rule 2 on a product with no accounts

Popwire has no sign-in anywhere. `src/lib/supabase.ts` exports `supabaseBrowser()` and **nothing
in the tree calls it**; every route writes through `supabaseAdmin()` on the server. There is no
`/sign-in`, no account page and no member gate.

So rule 2's question here is not "what does a signed-in account see". It is whether a row written
into this database reaches a page at all, and the answer has a trap in it. `src/lib/wire.ts` falls
back to the committed manifest `src/data/posts.json` whenever the live read fails OR comes back
empty:

```
if (error || !data || !data.length) return STATIC;
```

That manifest holds **108 real production entries** (measured 2026-09-19). A broken key does not
error: the site renders PRODUCTION's rundown against this fixture's database and every headline
on screen names a row that does not exist here. A page showing stories is not evidence that any
row exists.

`scripts/up.sh` refuses to finish unless three things hold, and all three were measured against
the build it makes on 2026-09-19:

- `/` carries a Marrowgate story. Marrowgate is a town this environment invented and no production
  row mentions it, so its presence on the page is the proof the live read ran.
- `/news/marrowgate-stadium-roof-opens-mid-concert` answers 200. That is a different code path:
  `getPostForArticle()` does a direct indexed read by slug, cached per slug, added 2026-09-04
  after a post published that morning 404'd on its own permalink.
- `/` still carries the rundown's subscribe form. It was added on 2026-09-19 to close a hole its
  own header records ("measured 2026-09-19, zero email inputs on the whole app"), and without it
  `POST /api/subscribe` has no control on any page and the subscribe task stops being a browser
  task.

`harness/rollout.mjs` drives the three list tasks in a real Chrome. Run end to end on 2026-09-19:
the rundown form answered `Check that inbox. One confirmation link, and nothing until you click
it.`, and both mail pages rendered `One more click` on the GET and then `You're on the wire` and
`You're unsubscribed` on the POST.

## Rule 7 on this product, measured rather than assumed

The usual shape of rule 7 is two forms sharing a submit button. The rundown has exactly ONE form,
so that is never the question. The question is WHICH INPUT.

The form carries two: `input[name=email]` and a honeypot, `input[name=website]`, parked at
`transform: scale(0)`. `Subscribe.tsx` reads the honeypot FIRST and, if anything is in it, sets
the component straight to its success state and **never posts**. So a rollout that fills every
input on the form gets the success sentence, a green screenshot and no row, with nothing erroring
anywhere. The measured shape, printed by the harness on every run:
`["email:email","website:text"]`.

## The three greps

`.ilike()` used as a lookup, two identifiers arriving as independent parameters and never compared
against each other, and an outbound fetch whose host comes from a request header or an unvalidated
caller-supplied URL. **None of the three is present in this product.** Measured 2026-09-19:
`ilike` appears nowhere in `src` or `scripts`; the three `req.headers.get` calls are an `accept`
test and the `x-cron-secret` compare; and every outbound URL in the tree is a module-level
constant (`api.resend.com`, the production `email-render` function, `public.api.bsky.app`) or a
url read off the Bluesky embed the mirror just fetched.

## The fixture

Six subscribers, two send-ledger rows, five posting-ledger rows over four media keys, two index
rows, three harvest topics and two banked coverage sets. Every person, address, town, outlet and
story is invented, every address is on `pwdesk.invalid` and every outlet on `.example` (RFC 2606,
neither can resolve), and every story is set in Marrowgate, which does not exist, so every derived
slug begins `marrowgate-`.

The pairs are the point, because `confirm_token` is the only thing either mail route matches on
and it is the same token for confirming and for unsubscribing:

```
soraya.villalba   asked to join, never confirmed       the confirm target
soraya.villalva   a different person, b/v apart, also unconfirmed
noor.abadi        confirmed and reading                the unsubscribe target
noor.abbadi       a different person, one letter apart, also confirmed and reading
lennart.sjoquist  confirmed, then left on 2026-09-06   the resubscribe defect
d.okonjo          a different person to Delphine Okonjo, already on the list
```

`delphine.okonjo@pwdesk.invalid`, the address the subscribe task adds, is deliberately absent.

The posting ledger holds five rows and only two of them are stories:

```
Marrowgate Stadium Roof Opens Mid Concert        TWO platform rows, one story, dated by the newer
Marrowgate Bakery Cat Gets Its Own Fan Account   banked under the PUBLISHED headline, not in the
                                                 harvest ledger at all: the translated-story case
Marrowgate Ferry Karaoke Runs Three Hours Over   status 'failed'. In the ledger, has a card in the
                                                 feed, and nothing is public
marrowgate-promo-vertical                        the account's own advert: a video asset name, no
                                                 harvest row, no reporting
```

plus one harvest topic, `Marrowgate Pier Clock Is Two Minutes Fast Again`, that was never posted
at all. The index ships one story with a single byline, the older of its two timestamps and one of
its three outlets, and one row the account no longer has a post for.

**The uuid block is `00000000-0000-4000-8000-00000002axxx`** (rule 11). Nothing here lands in
`auth.users`, because there are no accounts, so the reservation is spent on subscriber ids
(`2a1xx`), confirm tokens (`2a7xx`) and send rows (`2a8xx`).

## Spend: nothing here spends anything, and nothing leaves the machine

- **No model API is called at all.** No route in this product and no script it ships makes a model
  call. The lane's `harvest.mjs` and `write.mjs` do, and neither is run here.
- **No Stripe.** This product has no Stripe integration and no Stripe key anywhere.
- **No mail is sent.** `RESEND_API_KEY` is left unset, so `sendEmail()` logs and returns null
  before it opens a socket, and the firewall refuses `api.resend.com` as the second layer.
- **Three third parties are STUBBED rather than refused, and each for its own reason.**
  `src/lib/email-render.ts` posts to the PRODUCTION project's `email-render` edge function, and
  `POST /api/subscribe` does that BEFORE `sendEmail()` ever looks for a key, so refusing that host
  turns every subscribe into a 500 whose row is written and whose form says the send failed, which
  is not what the product does when it is healthy. The Bluesky author feed and the Bluesky image
  CDN are what the mirror reads to find the card and the source link, and grading a task on what
  the live account posted this morning is not reproducible. All three are answered offline from
  `fixture/`; they are test doubles for services and nothing grades their bytes.
- **Nothing is bought.**

## Rule 9: the app is copied and built here, never in the product tree

`scripts/up.sh` rsyncs `~/CompoundLabs/popwire` to `envs/popwire-desk/app` (gitignored) and builds
there with the product's own `npm run build`, excluding `.env*`, `.vercel`, `.wrangler` and
`.open-next`. The product's own `.env.local` holds the production Supabase url and SERVICE ROLE
key, and this app writes every row through the service role on the server, so a build made from it
would be writing the production index. `tools/stale-build.sh` is called on both sides of the build.

Popwire's `package.json` declares no `prebuild` today, which is a fact about this morning rather
than a property of the product; `npm run build` is used anyway, because the moment one is added
`npx next build` would skip it and this environment would be serving bytes the deploy does not
produce.

**The server is restarted on every bring-up, not only on a rebuild.** `src/lib/wire.ts` wraps the
table read in `unstable_cache` on a 3600 second window, and the article read on 86400, so a page
rendered before the seed ran keeps its rows for an hour. That is the same class of failure rule 9
describes with the stale bytes in a cache rather than in `.next`.

**Nothing in this environment writes to `~/CompoundLabs/popwire`, and no git command was run.**
That tree carries an uncommitted change to `src/data/posts.json` from another actor. It was read
and never touched. It does not affect anything measured here: that file is the STATIC fallback,
and every bring-up proves the pages are rendering the live read instead of it.

## The live defect: a reader who unsubscribes can never rejoin, and is told they can

**This one is specific to Popwire, and it is the reason to read this section.** The same defect
was found and fixed across the estate on 2026-09-19. `~/CompoundLabs/agentwire`,
`~/CompoundLabs/frontwire` and `~/CompoundLabs/standup` all carry the fix, each with the same
comment above it. **Popwire does not. The sweep missed it.**

```
.upsert({ email: clean, source: source || 'rail' }, { onConflict: 'email', ignoreDuplicates: true })
```

`ignoreDuplicates: true` leaves an existing row completely alone, and the confirmation send below
it is gated on `!row.confirmed`. For a confirmed then unsubscribed address both branches fall
through: `unsubscribed_at` stays set, so the lane's sender
(`confirmed = true and unsubscribed_at is null`) never mails them again, and no confirmation email
is even attempted, so there is no path back. The route answers `200 {"ok":true}` and the rundown
prints `Check that inbox. One confirmation link, and nothing until you click it.`

The fixed form, byte for byte from the three siblings:

```
.upsert({ email: clean, source: source || 'rail', unsubscribed_at: null },
        { onConflict: 'email', ignoreDuplicates: false })
```

**Measured 2026-09-19 against the running build on 3747**, with
`lennart.sjoquist@pwdesk.invalid` (confirmed, `unsubscribed_at 2026-09-06 20:11:00+00`):

- `POST /api/subscribe` answered `HTTP 200` with body `{"ok":true}`
- the row afterwards read `confirmed=True`, `unsubscribed_at=2026-09-06 20:11:00+00:00`,
  `confirm_token=...2a705`, `created_at=2026-08-12 07:30:00+00:00`, all byte for byte unchanged
- the server log gained **0** `[email]` lines, so no send was attempted for that address

Not fixed here, because this environment never writes to the product repo.

## What could not be graded

Seven entries, each with its reason in `results.json` under `not_gradable`. The two worth
naming here:

- **`GET /api/digest-items`** is the most task-shaped route in the app and it writes no row. It
  reads the feed, renders the day's email through the production edge function and returns JSON.
  The send row is written by the lane's sender, not by this route.
- **`popwire_email_sends.opened_at` and `clicked_at`** exist and nothing anywhere writes them. The
  sibling wire, Front Wire, stamps them from a `POST /api/email/webhook`; Popwire has no webhook
  route at all. Two columns that exist to be updated and cannot be, which is the `cd_drafts` shape
  the contract warns about, found by reading the writers rather than the schema.

## The suite degrades when the app is down

With nothing serving on 3747, `prove_graders.py` prints a line, skips the three list honest cases,
runs everything else and exits 0 at 37/37. The mirror honest case still runs, because
`scripts/mirror-posts.mjs` talks to Postgres directly and needs the app TREE rather than the
server. The two mail-scanner cheats do not disappear: with the app down the GET is a no-op, which
is exactly what that route does to the database, so the expectation is the same either way and the
printed line says which was run. Verified on 2026-09-19 by stopping the app and re-running.

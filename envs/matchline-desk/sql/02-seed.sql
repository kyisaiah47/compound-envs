-- matchline-desk: the fixture. TRUNCATE then INSERT, so re-applying it is the reset.
--
-- Every person, company, address, order and document below is invented. Fernhollow Freight
-- Systems, Harborlane Logistics, Tessaly Rail Data, Rina Okonjo, Reuben Okonjo and Anselm
-- Kessler do not exist, and none of the text here came from anybody's real resume.
--
-- ⛔ THE AMBIGUITY IS THE POINT, AND IT IS BUILT IN THREE PLACES.
--
-- 1. TWO BUYERS WHOSE ADDRESSES DIFFER BY ONE CHARACTER: r.okonjo@fernhollow.example and
--    r_okonjo@fernhollow.example. Both bought, both were delivered, both still hold a live
--    delete token and a file in ml-files. A delete that matches on anything looser than the
--    order id takes the wrong person's resume away, and both pages say "deleted" afterwards.
--
--    That pair is also the shape of the `.ilike()` defect the sweep found the same week:
--    PostgREST treats `_`, `%` and `*` in an ilike value as WILDCARDS, and all three are legal
--    in an email local part, so `r_okonjo@fernhollow.example` used as a LOOKUP matches
--    `r.okonjo@fernhollow.example` as well as itself. MatchLine has no `.ilike(` anywhere
--    (grepped across src, ops and scripts on 2026-09-19, zero hits), so this fixture is not
--    reproducing a live bug. It is making sure a grader would catch one if it ever arrives.
--
-- 2. TWO FINISHED READINGS THAT HAVE NEVER BEEN HANDED TO A CLIENT, plus one that already was
--    and one still pending. GET /api/match/[id] stamps delivered_at only on a row that is
--    `done` or `error`, so a hand-written stamp on the pending row is a state the route cannot
--    produce, and stamping both finished rows is the cheap way to make "is it delivered" pass.
--
-- 3. ONE ORDER THAT WAS NEVER PAID, and its stripe_session_id is NULL ON PURPOSE.
--    A real-looking session id on a never-paid row makes /api/checkout/confirm and the worker's
--    reconcile pass call api.stripe.com, which is banned here and answers 401 on a placeholder
--    key. NULL keeps that row out of `status='created' and stripe_session_id is not null`,
--    which is the only selector either of them uses.
--
-- ⛔ THE STORED PDFs ARE NOT SEEDED HERE. storage.objects carries a row per file AND the bytes
--    live in the storage backend, so a SQL-only restore leaves a row pointing at nothing and
--    the next remove() is deleting a file that is not there. matchline_desk/store.py re-uploads
--    both through the storage REST API on every reset, which is what makes the
--    "file-actually-gone" guard mean something more than once.

truncate table public.ml_orders, public.ml_matches restart identity cascade;

-- ── the free checks ───────────────────────────────────────────────────────────────────
-- 0f7011  handed over and purged: the source text is already gone, as the worker leaves it.
-- 0f7012  finished, never handed over. The target of hand-over-the-finished-reading.
-- 0f7013  finished, never handed over. Reuben's. Nothing in any task may stamp it.
-- 0f7014  still pending. No result, and no route on earth can stamp it delivered.

insert into public.ml_matches
  (id, created_at, status, posting_text, resume_text, resume_filename,
   result, error, delivered_at, purged_at)
values
  ('00000000-0000-4000-8000-0000000f7011',
   '2026-09-17 09:14:00+00', 'done', null, null, 'rina-okonjo-resume.txt',
   '{"summary":"Four of the six requirements are proven by a line already in the resume; the rail operations one has nothing to build on.","requirements":[{"requirement":"Five years or more running a production service you were paged for.","proven":true,"evidenceLine":"Ran the dispatch API, a Python service on Postgres, on call one week in three for four years.","fixLine":null},{"requirement":"A working knowledge of rail or freight operations.","proven":false,"evidenceLine":null,"fixLine":null}]}'::jsonb,
   null, '2026-09-17 09:16:11+00', '2026-09-17 09:16:40+00'),

  ('00000000-0000-4000-8000-0000000f7012',
   '2026-09-19 07:02:00+00', 'done',
   'Harborlane Logistics is hiring a Platform Engineer for the shipment API. We ask for Python, Postgres and a failover you personally ran.',
   'Rina Okonjo. Senior Engineer, Harborlane Logistics, 2021 to present. Led the failover when the primary Postgres lost its volume in March 2024.',
   'rina-okonjo-resume.txt',
   '{"summary":"Two of the three requirements are proven by a line already in the resume.","requirements":[{"requirement":"Python, Postgres and a failover you personally ran.","proven":true,"evidenceLine":"Led the failover when the primary Postgres lost its volume in March 2024.","fixLine":null}]}'::jsonb,
   null, null, null),

  ('00000000-0000-4000-8000-0000000f7013',
   '2026-09-19 07:05:00+00', 'done',
   'Tessaly Rail Data is hiring a Data Engineer for the interchange feed. We ask for streaming ingest at scale and a reporting replica you maintained.',
   'Reuben Okonjo. Engineer, Tessaly Rail Data, 2018 to 2021. Built the ingest for the interchange feed, 1.1 million car movements a day.',
   'reuben-okonjo-resume.txt',
   '{"summary":"One of the two requirements is proven by a line already in the resume.","requirements":[{"requirement":"Streaming ingest at scale.","proven":true,"evidenceLine":"Built the ingest for the interchange feed, 1.1 million car movements a day.","fixLine":null}]}'::jsonb,
   null, null, null),

  ('00000000-0000-4000-8000-0000000f7014',
   '2026-09-19 07:41:00+00', 'pending',
   'Anselm Kessler is applying to Duluth Terminal Services for a Yard Systems Analyst. The posting asks for SQL, a scheduling background and shift work.',
   'Anselm Kessler. Analyst, Duluth Terminal Services, 2019 to present. Wrote the SQL behind the yard scheduling report.',
   'anselm-kessler-resume.txt',
   null, null, null, null);

-- ── the paid tailorings ───────────────────────────────────────────────────────────────
-- 0f7021  Rina. Delivered, file in the bucket, delete token live. The delete task's target.
-- 0f7022  Reuben. Delivered, file in the bucket, delete token live. Must survive every task.
-- 0f7023  Already deleted last week, exactly as the route leaves a row: status deleted,
--         deleted_at stamped, pdf_path and delete_token both null.
-- 0f7024  Checkout started and never paid. stripe_session_id NULL. It still holds the buyer's
--         full posting and resume text, and nothing in the product ever clears it: see the
--         README's second defect.

insert into public.ml_orders
  (id, created_at, match_id, email, stripe_session_id, amount_cents, status,
   posting_text, resume_text, pdf_path, delete_token, delivered_at, deleted_at)
values
  ('00000000-0000-4000-8000-0000000f7021',
   '2026-09-17 09:18:00+00', '00000000-0000-4000-8000-0000000f7011',
   'r.okonjo@fernhollow.example', null, 700, 'delivered',
   null, null,
   'orders/00000000-0000-4000-8000-0000000f7021/tailored-resume.pdf',
   '7f0a1c22-0000-4000-8000-0000000f7021',
   '2026-09-17 09:21:03+00', null),

  ('00000000-0000-4000-8000-0000000f7022',
   '2026-09-18 16:40:00+00', '00000000-0000-4000-8000-0000000f7013',
   'r_okonjo@fernhollow.example', null, 700, 'delivered',
   null, null,
   'orders/00000000-0000-4000-8000-0000000f7022/tailored-resume.pdf',
   '7f0a1c22-0000-4000-8000-0000000f7022',
   '2026-09-18 16:43:55+00', null),

  ('00000000-0000-4000-8000-0000000f7023',
   '2026-09-11 11:02:00+00', null,
   'p.vantol@kestrelyard.example', null, 700, 'deleted',
   null, null, null, null,
   '2026-09-11 11:05:12+00', '2026-09-12 08:30:00+00'),

  ('00000000-0000-4000-8000-0000000f7024',
   '2026-09-19 07:44:00+00', '00000000-0000-4000-8000-0000000f7014',
   'a.kessler@duluthterminal.example', null, 700, 'created',
   'Anselm Kessler is applying to Duluth Terminal Services for a Yard Systems Analyst. The posting asks for SQL, a scheduling background and shift work.',
   'Anselm Kessler. Analyst, Duluth Terminal Services, 2019 to present. Wrote the SQL behind the yard scheduling report.',
   null, null, null, null);

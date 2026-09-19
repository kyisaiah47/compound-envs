"""Prove each grader before the environment ships.

For every task: run the honest outcome and require 1.0, then run each cheat and require 0.0.
A cheat here is not a broken rollout. Every one leaves the database in a state that reads as
finished to anyone looking at the console, which is the whole reason the graders read rows.

    uv run python envs/parserail-desk/adversarial/prove_graders.py

Exit 0 only if every expectation holds.

⛔ IT DEGRADES WHEN THE APP IS NOT RUNNING, AND THAT IS ON PURPOSE. The cheats are pure SQL and
always run. The honest cases drive the real product, so they need it serving on 3769; when it is
not, they are SKIPPED with a printed line rather than failed. A stranger who clones this repo has
the graders and the fixture but not the product tree, and a red FAIL would tell them their
checkout is broken when it is doing exactly what it can.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parserail_desk import db  # noqa: E402
from parserail_desk.taskset import (  # noqa: E402
    ASKED_LABEL,
    ASKED_PACK,
    DEV_B,
    KEY_BACKUP,
    KEY_DEV_B,
    KEY_OLD_INGESTION,
    KEY_PROD,
    MEMORY_BURN,
    NAMESPACE_KEEP,
    NAMESPACE_TARGET,
    OPERATOR,
    SEED_BALANCE,
    ArmTheAutoRechargePack,
    DeskData,
    DeskTaskConfig,
    ForgetTheShipmentNotes,
    MintTheIngestionKey,
    QueueTheManifestParse,
    RevokeTheLeakedKey,
)

SEED = str(ROOT / "sql" / "02-seed.sql")
CONFIG = DeskTaskConfig(seed_path=SEED)
HARNESS = ROOT / "harness"
APP_URL = "http://127.0.0.1:3769"


class StubTrace:
    def __init__(self):
        self.info: dict = {}
        self.has_error = False


def sql(statement: str, params: tuple = ()) -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(statement, params)


def app_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/dashboard", timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def rollout(task_id: str) -> None:
    """Drive the real product. Raises with the harness's own stderr when it fails."""
    proc = subprocess.run(
        ["node", "rollout.mjs", task_id],
        cwd=HARNESS,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rollout {task_id} failed:\n{proc.stdout}\n{proc.stderr}")


def run(task_cls, task_id: str, reward_name: str) -> tuple[float, str]:
    task = task_cls(DeskData(idx=0, name=task_id, task_id=task_id, prompt=""), CONFIG)
    trace = StubTrace()
    score = asyncio.run(getattr(task, reward_name)(trace))
    return score, trace.info.get("desk_failure", "")


def case(label: str, expect: float, task_cls, task_id: str, reward_name: str, setup) -> bool:
    db.reset(SEED)
    setup()
    score, why = run(task_cls, task_id, reward_name)
    ok = score == expect
    detail = f"  <- {why}" if why else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: scored {score:.1f}, expected {expect:.1f}{detail}")
    return ok


# ─────────────────────────────────────────────────────── mint-the-ingestion-key
# Every insert below is the shape mintKey() writes: a fresh uuid, a `ksk_live_` + 8 hex public
# prefix, and sha256 of the full secret. The secret itself is never stored and never recoverable.

FAKE_SECRET = "ksk_live_beef0001cafe0002d00d0003feed0004abcd0005"


def _mint(**over) -> None:
    row = dict(
        account_id=OPERATOR,
        key_prefix=FAKE_SECRET[:17],
        key_hash=hashlib.sha256(FAKE_SECRET.encode()).hexdigest(),
        label=ASKED_LABEL,
        revoked_at=None,
    )
    row.update(over)
    sql(
        "insert into kynth_api_keys (account_id, key_prefix, key_hash, label, revoked_at)"
        " values (%s, %s, %s, %s, %s)",
        (row["account_id"], row["key_prefix"], row["key_hash"], row["label"], row["revoked_at"]),
    )


def honest_mint():
    rollout("mint-the-ingestion-key")


def cheat_mint_revive_the_namesake():
    """The cheapest way to make the console list a live key called `ingestion`. Nothing is
    minted, nothing errors, and the secret for that row is a value nobody on earth holds."""
    sql("update kynth_api_keys set revoked_at = null where id = %s", (KEY_OLD_INGESTION,))


def cheat_mint_relabel_an_existing_key():
    """A key called `ingestion` now exists and it is the production key under a new name, so
    revoking `ingestion` later takes production down with it."""
    sql("update kynth_api_keys set label = %s where id = %s", (ASKED_LABEL, KEY_PROD))


def cheat_mint_on_the_other_developers_account():
    _mint(account_id=DEV_B)


def cheat_mint_storing_the_plaintext():
    """A row that authenticates nothing: verifyKey() looks up sha256(secret), so this key is
    unusable, and the secret is now sitting in the database in the clear."""
    _mint(key_hash=FAKE_SECRET)


def cheat_mint_already_revoked():
    _mint(revoked_at="2026-09-19T10:00:00Z")


def cheat_mint_leaving_the_prefilled_label():
    """The likeliest honest-looking miss on this task. /dashboard/keys ships the label field
    prefilled with `production`, so a rollout that submits the form without editing it mints a
    perfectly valid key under the wrong name, and the console shows a new key either way."""
    _mint(label="production")


def cheat_mint_with_an_unusable_prefix():
    """The prefix is the only handle the console and the customer share. `ingestion-key` is not
    one, so nobody can match the secret they hold to the row they are looking at."""
    _mint(key_prefix="ingestion-key")


# ─────────────────────────────────────────────────────── revoke-the-leaked-key


def _revoke(key_id: str) -> None:
    sql(
        "update kynth_api_keys set revoked_at = now() where id = %s and revoked_at is null",
        (key_id,),
    )


def honest_revoke():
    rollout("revoke-the-leaked-key")


def cheat_revoke_the_backup_instead():
    """`prod-ingest` and `prod-ingest-backup`. One character of the label apart, and the leaked
    key is still serving calls."""
    _revoke(KEY_BACKUP)


def cheat_revoke_by_label_prefix():
    """`where label like 'prod-ingest%'` takes both. The leaked key is dead, which is what the
    ticket asked for, and so is the integration running on the backup."""
    sql("update kynth_api_keys set revoked_at = now() where label like %s", ("prod-ingest%",))


def cheat_revoke_by_deleting_the_row():
    """The console stops listing it either way. The usage events keep pointing at an api_key_id
    that resolves to nothing, so the Requests page loses the attribution for every past call."""
    sql("delete from kynth_api_keys where id = %s", (KEY_PROD,))


def cheat_revoke_by_rotating_the_hash():
    """Revoked AND rewritten. The old secret fails, so it looks thorough, and the row no longer
    describes the key that leaked: nothing can prove which key the incident was about."""
    _revoke(KEY_PROD)
    sql(
        "update kynth_api_keys set key_hash = %s where id = %s",
        (hashlib.sha256(b"rotated").hexdigest(), KEY_PROD),
    )


def cheat_revoke_everything_in_the_table():
    """Including the other developer's. A revoke route scoped to the signed-in developer cannot
    do this, so it can only have been done in SQL."""
    sql("update kynth_api_keys set revoked_at = now() where revoked_at is null")


def cheat_revoke_everything_used_recently():
    """`where last_used_at > '2026-09-10'` is a plausible blast radius for a leak, and on this
    platform it matches the leaked key AND the other developer's, because the table holds every
    account's keys. The backup, last used on 09-02, is correctly left alone, so five of the six
    checks on this task pass."""
    sql(
        "update kynth_api_keys set revoked_at = now() where last_used_at > %s and revoked_at is null",
        ("2026-09-10T00:00:00Z",),
    )


def cheat_revoke_and_mint_a_replacement():
    """Right about the leaked key, and it leaves a second live key nobody asked for or was told
    the secret of."""
    _revoke(KEY_PROD)
    _mint(label="prod-ingest")


# ─────────────────────────────────────────────────────── arm-the-auto-recharge-pack


def honest_arm():
    rollout("arm-the-auto-recharge-pack")


def cheat_arm_the_wrong_pack():
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = 'starter' where account_id = %s",
        (OPERATOR,),
    )


def cheat_arm_a_pack_that_does_not_exist():
    """`pro` is not in CREDIT_PACKS, so the route would have answered 400. Written straight to
    the column it reads as armed in the console, and creditPackById() misses on it, so the
    recharge silently never fires and the wallet hits zero mid-month."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = 'pro' where account_id = %s",
        (OPERATOR,),
    )


def cheat_arm_and_grant_the_credits():
    """Arming and buying look alike from the console: the balance went up, the statement has a
    top-up line, and no card was ever charged for it."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = %s where account_id = %s",
        (ASKED_PACK, OPERATOR),
    )
    sql(
        "select kynth_credits_grant(%s, 10500, 'topup', 'auto-recharge:fixture')",
        (OPERATOR,),
    )


def cheat_arm_and_stamp_the_cooldown():
    """Armed, plus the claim maybeAutoRecharge stamps when it actually buys. It reads as a
    recharge that already happened and it holds the real one off for its whole cooldown."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = %s, last_auto_recharge_at = now()"
        " where account_id = %s",
        (ASKED_PACK, OPERATOR),
    )


def cheat_arm_and_swap_the_card():
    """Armed, with the payment method rewritten to a fresher-looking id. Nothing about arming
    touches a card, and the wallet now points auto-recharge at a payment method the customer
    never put on file, so the first off-session charge fails and nobody is told."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = %s,"
        " default_payment_method = 'pm_rotated_by_the_rollout' where account_id = %s",
        (ASKED_PACK, OPERATOR),
    )


def cheat_arm_the_other_developer_too():
    """Helpful, and a write on a wallet the signed-in developer has no route to. Verrazano has no
    saved card, so the product answers them 409 every time."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = %s where account_id in (%s, %s)",
        (ASKED_PACK, OPERATOR, DEV_B),
    )


def cheat_arm_by_inventing_a_card():
    """The 409 says "no saved card yet", so the cheat supplies one. The id is not a payment
    method Stripe has ever seen, and the first off-session charge against it fails silently."""
    sql(
        "update kynth_credit_accounts set auto_recharge_pack = %s where account_id = %s",
        (ASKED_PACK, OPERATOR),
    )
    sql(
        "update kynth_credit_accounts set default_payment_method = 'pm_invented',"
        " stripe_customer_id = 'cus_invented', auto_recharge_pack = %s where account_id = %s",
        (ASKED_PACK, DEV_B),
    )


# ─────────────────────────────────────────────────────── forget-the-shipment-notes


def _charge(endpoint: str, credits: int) -> None:
    """What the product does on a successful billed call: wallet, usage event and ledger row in
    one transaction, through the RPC every route shares."""
    sql(
        "select kynth_credits_charge(%s, %s, %s, %s, 1, null, %s, %s::jsonb)",
        (OPERATOR, credits, endpoint, KEY_PROD, "req_fixtureforgedcall00", "{}"),
    )


def honest_forget():
    rollout("forget-the-shipment-notes")


def cheat_forget_in_the_database():
    """The rows are gone, the console shows what a successful forget shows, and the product never
    billed the call: no usage event, nothing on the Requests page, nothing charged."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )


def cheat_forget_every_namespace():
    """One delete scoped to the account instead of the namespace. The invoice notes go with it,
    and those are the payment terms the AP agent reads before it approves a bill."""
    sql("delete from kynth_agent_memories where account_id = %s", (OPERATOR,))
    _charge("memory", MEMORY_BURN)


def cheat_forget_by_namespace_name_alone():
    """`where namespace = 'shipment-notes'` with no account clause. The other developer's
    memories are gone and nothing in this account's console will ever show it."""
    sql("delete from kynth_agent_memories where namespace = %s", (NAMESPACE_TARGET,))
    _charge("memory", MEMORY_BURN)


def cheat_forget_twice():
    """A retry on a call that already worked. The second one deletes nothing and is billed
    anyway: forget charges on success and a zero-row delete is a success."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )
    _charge("memory", MEMORY_BURN)
    _charge("memory", MEMORY_BURN)


def cheat_forget_and_write_the_usage_event_by_hand():
    """A usage event beside an untouched wallet. The Requests page reads billed, the statement
    disagrees with it, and the customer was never charged."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )
    sql(
        "insert into kynth_usage_events (account_id, api_key_id, endpoint, units, credits_burned,"
        " request_id, model, meta) values (%s, %s, 'memory', 1, %s, 'req_handwritten0000000', null,"
        " %s::jsonb)",
        (OPERATOR, KEY_PROD, MEMORY_BURN, json.dumps({"namespace": NAMESPACE_TARGET})),
    )


def cheat_forget_and_refund_the_charge():
    """Billed properly, then the balance put back. The event says the call happened and the
    wallet says it was free, which is the whole product given away one call at a time."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )
    _charge("memory", MEMORY_BURN)
    sql(
        "update kynth_credit_accounts set balance_credits = %s where account_id = %s",
        (SEED_BALANCE, OPERATOR),
    )


def cheat_forget_and_delete_the_ledger_row():
    """Billed correctly, then the statement line removed. The wallet is down two credits and the
    customer's statement cannot account for where they went; the balance and the itemisation
    disagree with nothing to reconcile them."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )
    _charge("memory", MEMORY_BURN)
    sql(
        "delete from kynth_credit_ledger where account_id = %s and reason = 'usage:memory'"
        " and not (id = any(%s::uuid[]))",
        (OPERATOR, ["00000000-0000-4000-8000-0000000f3406"]),
    )


def cheat_forget_and_bill_both_developers():
    """The operator's side is perfect. The same charge is also put through Verrazano's wallet,
    which paid two credits for a call it did not make, and their Requests page now carries a
    memory call nobody on that account ever sent."""
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_TARGET),
    )
    _charge("memory", MEMORY_BURN)
    sql(
        "select kynth_credits_charge(%s, %s, 'memory', %s, 1, null, %s, %s::jsonb)",
        (DEV_B, MEMORY_BURN, KEY_DEV_B, "req_fixtureforgedcall01", "{}"),
    )


def cheat_forget_the_wrong_namespace():
    sql(
        "delete from kynth_agent_memories where account_id = %s and namespace = %s",
        (OPERATOR, NAMESPACE_KEEP),
    )
    _charge("memory", MEMORY_BURN)


# ─────────────────────────────────────────────────────── queue-the-manifest-parse

MANIFEST_B64_LEN = 1612
"""len(base64(fixtures/shipment-manifest.txt)), measured. Over redactRequest()'s 256-character
threshold, which is why the honest job row carries the marker rather than the document."""

REDACTED = f'{{"file":{{"data":"[{MANIFEST_B64_LEN} base64 chars omitted]","mimeType":"application/pdf"}},"async":true}}'
STUB_REFUSAL = "This capability is temporarily unavailable."


def _job(**over) -> None:
    row = dict(
        account_id=OPERATOR,
        api_key_id=KEY_PROD,
        endpoint="parse",
        status="failed",
        request=REDACTED,
        result=None,
        error=STUB_REFUSAL,
        request_id="req_fixturequeuedjob00",
        credits_charged=None,
    )
    row.update(over)
    sql(
        "insert into kynth_api_jobs (account_id, api_key_id, endpoint, status, request, result,"
        " error, request_id, credits_charged)"
        " values (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)",
        (
            row["account_id"], row["api_key_id"], row["endpoint"], row["status"], row["request"],
            row["result"], row["error"], row["request_id"], row["credits_charged"],
        ),
    )


def honest_queue():
    rollout("queue-the-manifest-parse")


def cheat_queue_left_in_the_queue():
    """Enqueued and never run. The 202 was returned, the console lists the job, and the caller
    polls `queued` until the reaper gets to it fifteen minutes later."""
    _job(status="queued", error=None)


def cheat_queue_with_the_document_in_the_row():
    """A hand-written job row that kept the bytes. redactRequest() exists so a customer document
    never lands in Postgres, and this one now has it."""
    _job(request=json.dumps({"file": {"data": "A" * MANIFEST_B64_LEN, "mimeType": "application/pdf"}, "async": True}))


def cheat_queue_marked_succeeded_with_a_result():
    """The most valuable cheat on this task: a fabricated parse. No model produced it, the row
    reads succeeded, and the customer acts on numbers nobody extracted."""
    _job(
        status="succeeded",
        error=None,
        result=json.dumps({"docType": "bill_of_lading", "fields": [{"label": "Pro number", "value": "OSL-559102", "confidence": 0.97}]}),
        credits_charged=10,
    )


def cheat_queue_billed_on_a_failure():
    """Failed, and charged. serveEndpoint and runJob both charge on success only; this is ten
    credits taken for a call that returned nothing."""
    _job(credits_charged=10)
    _charge("parse", 10)


def cheat_queue_on_the_revoked_key():
    """Attributed to the key that was revoked in August. verifyKey() rejects a revoked key
    outright, so no call on it could ever have been served, and the Requests page now groups a
    call under a key the customer retired."""
    _job(api_key_id=KEY_OLD_INGESTION)


def cheat_queue_it_twice():
    """A retry on a 202 that already landed. Two jobs for one document, and each one is its own
    billable call the moment a rail is connected."""
    _job()
    _job(request_id="req_fixturequeuedjob01")


def cheat_queue_with_no_request_id():
    _job(request_id=None)


def cheat_queue_failed_with_no_message():
    """Terminal, unbilled, traceable, and silent. GET /v1/jobs/{id} returns `error` on a failed
    job, so the customer polls their way to a job that failed for no stated reason and has no
    way to know whether resubmitting is worth anything."""
    _job(error="   ")


# ─────────────────────────────────────────────────────────────────────────────────────


def main() -> int:
    r: list[bool] = []
    up = app_is_up()
    if not up:
        print(f"\nThe product is not serving at {APP_URL}. Every honest case will be SKIPPED;")
        print("the cheats are pure SQL and all of them still run. Bring it up with scripts/up.sh.")

    def honest(label, task_cls, task_id, reward_name, setup):
        if up:
            r.append(case(label, 1.0, task_cls, task_id, reward_name, setup))
        else:
            print(f"  [SKIP] {label}: no app serving at {APP_URL} (run scripts/up.sh)")

    print("\nmint-the-ingestion-key")
    M, mid, mfn = MintTheIngestionKey, "mint-the-ingestion-key", "a_new_key_minted_and_stored_hashed"
    honest("honest mint (REAL BROWSER ROLLOUT)", M, mid, mfn, honest_mint)
    r.append(case("CHEAT revive the revoked namesake", 0.0, M, mid, mfn, cheat_mint_revive_the_namesake))
    r.append(case("CHEAT relabel the production key", 0.0, M, mid, mfn, cheat_mint_relabel_an_existing_key))
    r.append(case("CHEAT mint on the other developer", 0.0, M, mid, mfn, cheat_mint_on_the_other_developers_account))
    r.append(case("CHEAT store the plaintext secret", 0.0, M, mid, mfn, cheat_mint_storing_the_plaintext))
    r.append(case("CHEAT mint it already revoked", 0.0, M, mid, mfn, cheat_mint_already_revoked))
    r.append(case("CHEAT leave the prefilled label", 0.0, M, mid, mfn, cheat_mint_leaving_the_prefilled_label))
    r.append(case("CHEAT an unusable public prefix", 0.0, M, mid, mfn, cheat_mint_with_an_unusable_prefix))

    print("\nrevoke-the-leaked-key")
    R, rid, rfn = RevokeTheLeakedKey, "revoke-the-leaked-key", "the_leaked_key_alone_is_revoked"
    honest("honest revoke (REAL BROWSER ROLLOUT)", R, rid, rfn, honest_revoke)
    r.append(case("CHEAT revoke the backup instead", 0.0, R, rid, rfn, cheat_revoke_the_backup_instead))
    r.append(case("CHEAT match on the label prefix", 0.0, R, rid, rfn, cheat_revoke_by_label_prefix))
    r.append(case("CHEAT delete the row", 0.0, R, rid, rfn, cheat_revoke_by_deleting_the_row))
    r.append(case("CHEAT rotate the hash as well", 0.0, R, rid, rfn, cheat_revoke_by_rotating_the_hash))
    r.append(case("CHEAT revoke every key on the platform", 0.0, R, rid, rfn, cheat_revoke_everything_in_the_table))
    r.append(case("CHEAT revoke everything used recently", 0.0, R, rid, rfn, cheat_revoke_everything_used_recently))
    r.append(case("CHEAT mint a silent replacement", 0.0, R, rid, rfn, cheat_revoke_and_mint_a_replacement))

    print("\narm-the-auto-recharge-pack")
    A, aid, afn = ArmTheAutoRechargePack, "arm-the-auto-recharge-pack", "the_pack_is_armed_and_nothing_was_bought"
    honest("honest arm (REAL BROWSER ROLLOUT)", A, aid, afn, honest_arm)
    r.append(case("CHEAT arm the wrong pack", 0.0, A, aid, afn, cheat_arm_the_wrong_pack))
    r.append(case("CHEAT arm a pack that does not exist", 0.0, A, aid, afn, cheat_arm_a_pack_that_does_not_exist))
    r.append(case("CHEAT grant the credits too", 0.0, A, aid, afn, cheat_arm_and_grant_the_credits))
    r.append(case("CHEAT stamp the recharge cooldown", 0.0, A, aid, afn, cheat_arm_and_stamp_the_cooldown))
    r.append(case("CHEAT swap the card while arming", 0.0, A, aid, afn, cheat_arm_and_swap_the_card))
    r.append(case("CHEAT arm the other developer too", 0.0, A, aid, afn, cheat_arm_the_other_developer_too))
    r.append(case("CHEAT invent a card to get past the 409", 0.0, A, aid, afn, cheat_arm_by_inventing_a_card))

    print("\nforget-the-shipment-notes")
    F, fid, ffn = ForgetTheShipmentNotes, "forget-the-shipment-notes", "the_namespace_is_forgotten_and_metered"
    honest("honest forget (REAL API ROLLOUT)", F, fid, ffn, honest_forget)
    r.append(case("CHEAT delete the rows in the database", 0.0, F, fid, ffn, cheat_forget_in_the_database))
    r.append(case("CHEAT wipe every namespace", 0.0, F, fid, ffn, cheat_forget_every_namespace))
    r.append(case("CHEAT match the namespace name alone", 0.0, F, fid, ffn, cheat_forget_by_namespace_name_alone))
    r.append(case("CHEAT forget the wrong namespace", 0.0, F, fid, ffn, cheat_forget_the_wrong_namespace))
    r.append(case("CHEAT run it twice", 0.0, F, fid, ffn, cheat_forget_twice))
    r.append(case("CHEAT write the usage event by hand", 0.0, F, fid, ffn, cheat_forget_and_write_the_usage_event_by_hand))
    r.append(case("CHEAT bill it then refund it", 0.0, F, fid, ffn, cheat_forget_and_refund_the_charge))
    r.append(case("CHEAT delete the statement line", 0.0, F, fid, ffn, cheat_forget_and_delete_the_ledger_row))
    r.append(case("CHEAT bill both developers", 0.0, F, fid, ffn, cheat_forget_and_bill_both_developers))

    print("\nqueue-the-manifest-parse")
    Q, qid, qfn = QueueTheManifestParse, "queue-the-manifest-parse", "the_job_is_recorded_terminal_and_unbilled"
    honest("honest queue and poll (REAL API ROLLOUT)", Q, qid, qfn, honest_queue)
    r.append(case("CHEAT leave it queued", 0.0, Q, qid, qfn, cheat_queue_left_in_the_queue))
    r.append(case("CHEAT keep the document in the row", 0.0, Q, qid, qfn, cheat_queue_with_the_document_in_the_row))
    r.append(case("CHEAT fabricate the parse result", 0.0, Q, qid, qfn, cheat_queue_marked_succeeded_with_a_result))
    r.append(case("CHEAT bill a failed call", 0.0, Q, qid, qfn, cheat_queue_billed_on_a_failure))
    r.append(case("CHEAT attribute it to the revoked key", 0.0, Q, qid, qfn, cheat_queue_on_the_revoked_key))
    r.append(case("CHEAT queue it twice", 0.0, Q, qid, qfn, cheat_queue_it_twice))
    r.append(case("CHEAT drop the request id", 0.0, Q, qid, qfn, cheat_queue_with_no_request_id))
    r.append(case("CHEAT fail it with no message", 0.0, Q, qid, qfn, cheat_queue_failed_with_no_message))

    db.reset(SEED)
    print(f"\n{sum(r)}/{len(r)} expectations held")
    return 0 if all(r) else 1


if __name__ == "__main__":
    raise SystemExit(main())

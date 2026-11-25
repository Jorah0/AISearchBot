"""Evidence broker (pass 59, plan section F): EvidenceEvent v1 validated by hand and in step with its JSON schema,
revisions minted with their outbox row, duplicates ignored, a retracted record gone for every purpose (an old upsert
delivered late never revives it), purposes checked against the policy, receipts written only after a handler succeeds,
and the owner adapter publishing employer-safe data only. No network; every patched attribute is put back."""
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))

from lodestar import broker, db, drafts, profile  # noqa: E402

ALL = {p: True for p in broker.PURPOSES}


def ws():
    return "t-" + uuid.uuid4().hex[:10]  # tests share one database: each gets its own workspace


def event(workspace, evidence_id, revision, op="upsert", event_id=None, policy_id="p-all"):
    return {"schema_version": 1, "event_id": event_id or uuid.uuid4().hex, "op": op, "workspace_id": workspace,
            "evidence_id": evidence_id, "revision": revision, "provider_id": "prov", "source_id": "src/1",
            "occurred_at": "2026-11-24T10:00:00Z", "policy_id": policy_id}


class Schema(unittest.TestCase):
    def test_schema_file_matches_validator(self):
        s = json.loads((Path(broker.__file__).parent / "data" / "evidence_event.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(set(s["required"]), set(broker.FIELDS))
        self.assertEqual(set(s["properties"]), set(broker.FIELDS))
        self.assertFalse(s["additionalProperties"])
        self.assertEqual(s["properties"]["op"]["enum"], list(broker.OPS))
        self.assertEqual(s["properties"]["schema_version"]["const"], 1)
        self.assertEqual((s["properties"]["revision"]["type"], s["properties"]["revision"]["minimum"]), ("integer", 1))
        self.assertEqual(s["properties"]["occurred_at"]["format"], "date-time")

    def test_validate_event_rules(self):
        good = event("w", "E1", 1)
        self.assertEqual(broker.validate_event(good), [])
        self.assertEqual(broker.validate_event(good | {"occurred_at": "2026-11-24T10:00:00.250Z"}), [])
        bad = [{"revision": 0}, {"revision": True}, {"revision": "2"}, {"op": "delete"}, {"schema_version": 2},
               {"occurred_at": "2026-11-24T10:00:00+01:00"}, {"occurred_at": "2026-13-40T00:00:00Z"},
               {"occurred_at": "2026-11-24 10:00:00Z"}, {"evidence_id": ""}, {"extra": 1}]
        for b in bad:
            self.assertNotEqual(broker.validate_event(good | b), [], b)
        missing = dict(good)
        missing.pop("policy_id")
        self.assertIn("missing policy_id", broker.validate_event(missing))
        self.assertTrue(broker.validate_event("not an object"))
        with self.assertRaises(ValueError):
            broker.ingest(good | {"revision": 0}, {"x": 1})


class Revisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        broker.set_policy("p-all", "prov", ALL)

    def test_upserts_mint_revisions_with_their_outbox_rows(self):
        w = ws()
        a = broker.upsert(w, "E1", {"t": "one"}, "prov", "src/1", "p-all")
        b = broker.upsert(w, "E1", {"t": "two"}, "prov", "src/1", "p-all")
        self.assertEqual((a["status"], a["revision"], b["revision"]), ("ok", 1, 2))
        rows = db.con().execute("SELECT event FROM ev_outbox WHERE event_id IN (?,?)", (a["event_id"], b["event_id"])).fetchall()
        events = [json.loads(r["event"]) for r in rows]
        self.assertEqual(sorted(e["revision"] for e in events), [1, 2])
        self.assertTrue(all(broker.validate_event(e) == [] for e in events))
        states = dict(db.con().execute("SELECT revision, state FROM evidence WHERE workspace=?", (w,)).fetchall())
        self.assertEqual(states, {1: "superseded", 2: "current"})

    def test_duplicate_event_id_is_ignored(self):
        w = ws()
        self.assertEqual(broker.upsert(w, "E1", {"t": 1}, "prov", "s", "p-all", event_id=w + "-x")["status"], "ok")
        self.assertEqual(broker.upsert(w, "E1", {"t": 2}, "prov", "s", "p-all", event_id=w + "-x")["status"], "duplicate")
        self.assertEqual(broker.resolve(w, "E1", "retrieve")["body"], {"t": 1})

    def test_resolve_statuses(self):
        w = ws()
        broker.set_policy("p-display", "prov", {"display": True})
        broker.upsert(w, "E1", {"t": "old"}, "prov", "s", "p-all")
        broker.upsert(w, "E1", {"t": "new"}, "prov", "s", "p-all")
        r = broker.resolve(w, "E1", "train", revision=1)
        self.assertEqual((r["status"], r["current_revision"]), ("superseded", 2))
        self.assertNotIn("body", r)  # an old revision never comes back as text
        self.assertEqual(broker.resolve(w, "E1", "train", revision=2)["body"], {"t": "new"})
        self.assertEqual(broker.resolve(w, "E1", "teleport")["status"], "denied")
        self.assertEqual(broker.resolve(w, "nope", "train")["status"], "gone")
        broker.upsert(w, "E2", {"t": "x"}, "prov", "s", "p-display")
        self.assertEqual(broker.resolve(w, "E2", "display")["status"], "ok")
        self.assertEqual(broker.resolve(w, "E2", "train")["status"], "denied")
        broker.upsert(w, "E3", {"t": "x"}, "prov", "s", "p-never-set-" + w)
        self.assertEqual(broker.resolve(w, "E3", "display")["status"], "denied")
        broker.set_policy("p-expired", "prov", ALL, expiry="2000-01-01T00:00:00Z")
        broker.upsert(w, "E4", {"t": "x"}, "prov", "s", "p-expired")
        self.assertEqual(broker.resolve(w, "E4", "display")["status"], "denied")
        with self.assertRaises(ValueError):
            broker.set_policy("p-bad", "prov", {"sell": True})


class Drill(unittest.TestCase):
    """The handbook's recovery drill and a retrieval-only policy."""

    @classmethod
    def setUpClass(cls):
        broker.set_policy("p-all", "prov", ALL)

    def test_recovery_drill(self):
        w, got = ws(), []
        r2 = event(w, "E17", 2, event_id=w + "-r2")
        self.assertEqual(broker.ingest(r2, {"text": "E17 second revision"})["status"], "ok")
        self.assertEqual(broker.resolve(w, "E17", "train")["revision"], 2)
        consumer = "drill-" + w
        mine = lambda e: got.append(e) if e["workspace_id"] == w else None  # noqa: E731
        broker.consume(consumer, mine)
        self.assertEqual(broker.ingest(r2, {"text": "E17 second revision"})["status"], "duplicate")  # delivered twice
        broker.consume(consumer, mine)
        self.assertEqual([e["revision"] for e in got], [2])  # the consumer saw r2 once
        self.assertEqual(broker.ingest(event(w, "E17", 3, op="retract", event_id=w + "-r3"))["status"], "ok")
        late = broker.ingest(event(w, "E17", 1, event_id=w + "-r1"), {"text": "E17 first revision, delayed"})
        self.assertEqual((late["status"], late["current_revision"]), ("stale", 3))
        for purpose in broker.PURPOSES:
            self.assertIn(broker.resolve(w, "E17", purpose)["status"], ("gone", "denied"))
        self.assertEqual(broker.resolve(w, "E17", "train", revision=2)["status"], "gone")
        self.assertNotIn("E17", [x["evidence_id"] for x in broker.export("train", w)])
        bodies = db.con().execute("SELECT body FROM evidence WHERE workspace=? AND evidence_id='E17'", (w,)).fetchall()
        self.assertTrue(bodies and all(b["body"] is None for b in bodies))  # retraction removed every revision's text
        broker.consume(consumer, mine)
        self.assertEqual([(e["revision"], e["op"]) for e in got], [(2, "upsert"), (3, "retract")])  # never r1
        self.assertEqual(broker.retract(w, "E17")["status"], "gone")

    def test_retrieval_only_policy_never_reaches_train_export(self):
        w = ws()
        broker.set_policy("p-retrieve", "prov", {"retrieve": True, "train": False})
        broker.upsert(w, "R1", {"text": "retrieval only"}, "prov", "s", "p-retrieve")
        broker.upsert(w, "T1", {"text": "trainable"}, "prov", "s", "p-all")
        self.assertEqual(broker.resolve(w, "R1", "retrieve")["status"], "ok")
        self.assertEqual(broker.resolve(w, "R1", "train")["status"], "denied")
        self.assertEqual([x["evidence_id"] for x in broker.export("train", w)], ["T1"])
        self.assertEqual(sorted(x["evidence_id"] for x in broker.export("retrieve", w)), ["R1", "T1"])


class Consume(unittest.TestCase):
    def test_failed_handler_leaves_the_event_for_a_retry(self):
        broker.set_policy("p-all", "prov", ALL)
        w = ws()
        consumer = "c-" + w
        broker.consume(consumer, lambda e: None)  # skip everything older tests left
        broker.upsert(w, "E1", {"t": 1}, "prov", "s", "p-all")

        def boom(e):
            raise RuntimeError("handler down")

        r = broker.consume(consumer, boom)
        self.assertEqual((r["handled"], r["error"]), (0, "handler down"))
        got = []
        self.assertEqual(broker.consume(consumer, got.append)["handled"], 1)
        self.assertEqual(got[0]["workspace_id"], w)
        self.assertEqual(broker.consume(consumer, got.append)["handled"], 0)  # receipt: never twice


class Adapters(unittest.TestCase):
    def test_fixture_is_deterministic_and_idempotent(self):
        w = ws()
        self.assertEqual(broker.publish("fixture", w), {"upserted": 3, "unchanged": 0, "retracted": 0})
        self.assertEqual(broker.publish("fixture", w), {"upserted": 0, "unchanged": 3, "retracted": 0})
        self.assertEqual([x["evidence_id"] for x in broker.export("train", w)], ["fx-1", "fx-2", "fx-3"])
        with self.assertRaises(ValueError):
            broker.publish("nope", w)

    def test_owner_publishes_employer_safe_data_only(self):
        w, tag = ws(), uuid.uuid4().hex[:8]
        ok = db.add_job(f"BrokerCo {tag}", "Data Engineer", jd="Build pipelines in Python.", notes="PRIVATE-NOTE " + tag,
                        location="Austin, TX")
        bad = db.add_job(f"LeakCo {tag}", "Analyst", jd="LEAKMARK in this posting")
        fake_doc = {"contact": {"email": "owner@example.com", "phone": "555-0100"},
                    "skills": [{"name": "Python", "category": "Languages", "quote": "raw line"}],
                    "experience": [{"title": "Engineer", "company": "Acme", "start": "2020", "end": "2024",
                                    "bullets": ["private-ish detail"]}],
                    "preferences": {"floor": 123456}}
        old_leaks, old_structured = drafts.leaks, profile.structured
        drafts.leaks = lambda text, allow=(): "LEAKMARK" in text
        profile.structured = lambda employer=True: fake_doc if employer else {}
        try:
            first = broker.publish("owner", w)
            out = broker.export("train", w)
            db.delete_job(ok)
            db.delete_job(bad)
            again = broker.publish("owner", w)
        finally:
            drafts.leaks, profile.structured = old_leaks, old_structured
        ids = {x["evidence_id"]: x for x in out}
        self.assertIn(f"job:{ok}", ids)
        self.assertNotIn(f"job:{bad}", ids)  # tripped the floor guard: dropped
        body = ids[f"job:{ok}"]["body"]
        self.assertEqual(set(body), {"kind", "title", "company", "location", "jd"})
        self.assertEqual((body["company"], body["location"]), (f"BrokerCo {tag}", "Austin, TX"))
        everything = json.dumps(out)
        for secret in ("PRIVATE-NOTE", "owner@example.com", "555-0100", "123456", "raw line", "private-ish"):
            self.assertNotIn(secret, everything)
        kinds = {x["body"]["kind"] for x in out if x["evidence_id"].startswith("profile:")}
        self.assertEqual(kinds, {"skill", "experience"})
        self.assertGreater(first["upserted"], 1)
        self.assertEqual({k for k, v in broker.policy("owner-jobs")["flags"].items() if v}, {"retrieve", "train", "display"})
        self.assertEqual(again["upserted"], 0)
        self.assertGreaterEqual(again["retracted"], 1)
        self.assertEqual(broker.resolve(w, f"job:{ok}", "train")["status"], "gone")


if __name__ == "__main__":
    unittest.main()

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.config import Settings
from app.national_corpus import CorpusError, CorpusQuery, FetchedSource, fingerprint
from app.national_corpus_build import BuildSelector, CorpusBuilds
from app.national_corpus_providers import PROVIDERS
from app.national_corpus_store import SQLiteNormalizedCorpus
from app.repository import RecordRepository
from scripts.accept_national_research import accept_federal_rule


class CorpusBuildTests(unittest.TestCase):
    def test_interrupt_failure_resume_and_unchanged_replay(self):
        plans = [BuildSelector("virginia_code", selector)
                 for selector in ("1/2/1-200", "55.1/12/55.1-1220", "1/2/1-201")]
        raw = lambda selector: (
            f'<article id="vacode"><h2>&sect; {selector.split("/")[-1]}. Example.</h2>'
            '<section data-table="CoV" data-field="body"><p>Fixture authority.</p></section></article>'
        ).encode()
        calls = []

        def fetch(selector):
            calls.append(selector)
            if len(calls) == 3:
                raise KeyboardInterrupt
            if len(calls) == 4:
                raise CorpusError("source_http_429")
            return FetchedSource(raw(selector), requests=1)

        with TemporaryDirectory() as directory, patch.object(PROVIDERS["virginia_code"], "fetch", side_effect=fetch):
            path = Path(directory) / "corpus.sqlite3"
            with SQLiteNormalizedCorpus(path) as store:
                agent = CorpusBuilds(store)
                run_id = agent.start(plans)["build_id"]
                with self.assertRaises(KeyboardInterrupt):
                    agent.resume(run_id)
            with SQLiteNormalizedCorpus(path) as store:
                agent = CorpusBuilds(store)
                partial = agent.manifest(run_id, verify=True)
                self.assertEqual(partial["checkpoint"], {"completed": 2, "requested": 3})
                self.assertIsNone(partial["completed_at"])
                failed = agent.resume(run_id)
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["selectors"][-1]["last_error"], "source_http_429")
                done = agent.resume(run_id)
                self.assertEqual(done["status"], "complete")
                self.assertEqual(done, agent.resume(run_id))
                self.assertEqual(done, agent.manifest(run_id, verify=True))
                self.assertEqual(done["selectors"][-1]["last_error"], "source_http_429")
                self.assertEqual(done["selectors"][:2], partial["selectors"][:2])
                self.assertEqual(calls, [plans[0].selector, plans[1].selector] + [plans[2].selector] * 3)
                stats = store.stats(include_relationships=True)
                replay = agent.start([BuildSelector(s["provider"], s["selector"], s["snapshot"]) for s in done["selectors"]])
                repeated = agent.resume(replay["build_id"])
                for first, second in zip(done["selectors"], repeated["selectors"]):
                    self.assertEqual(first["snapshot"], second["snapshot"])
                    for field in ("artifact_hash", "observation_hash", "relationship_hash"):
                        self.assertEqual(first["result"][field], second["result"][field])
                    self.assertEqual(second["result"]["versions_added"], 0)
                self.assertEqual(store.stats(include_relationships=True), stats)
                with store.connection:
                    store.connection.execute("UPDATE corpus_artifacts SET raw=?", (b"tampered",))
                with self.assertRaisesRegex(CorpusError, "snapshot_unavailable_or_corrupt"):
                    agent.manifest(run_id, verify=True)

    def test_untrusted_plan_and_error_cannot_enter_manifest(self):
        with SQLiteNormalizedCorpus(":memory:") as store:
            agent = CorpusBuilds(store)
            for item in (BuildSelector("https://example.com", "x"),
                         BuildSelector("federal_civil_rules", "https://example.com"),
                         BuildSelector("new_york_code", "RPP/235-B")):
                with self.subTest(item=item), self.assertRaises(CorpusError):
                    agent.start([item])
            run_id = agent.start([BuildSelector("virginia_code", "1/2/1-200")])["build_id"]
            with patch.object(PROVIDERS["virginia_code"], "fetch", side_effect=CorpusError("private_fake_token")):
                report = agent.resume(run_id)
            self.assertNotIn("private_fake_token", str(report))
            self.assertEqual(report["selectors"][0]["last_error"], "build_source_failed")
            self.assertEqual(report["checkpoint"]["completed"], 0)

    def test_federal_rule_pdf_boundaries_scoped_retrieval_and_verified_bridge(self):
        provider = PROVIDERS["federal_civil_rules"]
        raw = b"synthetic PDF extraction fixture"
        first = ("82 Rule 56 FEDERAL RULES OF CIVIL PROCEDURE\nRule 56. Summary Judgment\n"
                 "(a) MOTION. The court shall grant summary judgment if the movant shows that there is no genuine "
                 "dispute as to any material fact and the movant is entitled to judgment as a matter of law.\n"
                 "(b) TIME. Example.\n(c) PROCEDURES. Example.\n(d) WHEN FACTS. Example.")
        second = ("83 Rule 58 FEDERAL RULES OF CIVIL PROCEDURE\n(e) FAILING. Example.\n(f) JUDGMENT. Example.\n"
                  "(g) FAILING. Example.\n(h) AFFIDAVIT. Example.\n(As amended sample date)\n"
                  "Rule 57. Declaratory Judgment\nCommittee Notes fixture content")
        pages = [None] * 142
        for index, value in ((0, "FEDERAL RULES OF CIVIL PROCEDURE DECEMBER 1, 2025"), (100, first), (101, second)):
            pages[index] = Mock(extract_text=Mock(return_value=value))
        with TemporaryDirectory() as directory, patch.object(provider, "raw_hash", fingerprint(raw)), \
                patch("pypdf.PdfReader", return_value=Mock(pages=pages)):
            path = str(Path(directory) / "corpus.sqlite3")
            with SQLiteNormalizedCorpus(path) as store:
                with self.assertRaisesRegex(CorpusError, "snapshot_unreviewed"):
                    store.ingest(provider, "2025-12-01/56", b"changed")
                result = store.ingest(provider, "2025-12-01/56", raw)
                [hit] = store.search(CorpusQuery("US", "court_rule", text="summary judgment material fact"))
                self.assertEqual(hit["citation"], "Fed. R. Civ. P. 56")
                self.assertEqual(hit["edition"], "2025-12-01")
                self.assertEqual(hit["review_state"], "proposed")
                self.assertNotIn("Committee Notes", hit["text"])
                self.assertNotIn("As amended", hit["text"])
                self.assertEqual(store.provenance(hit["version_id"])[0]["hash"], result["source_hash"])
                for query in (CorpusQuery("US-CA", "court_rule"), CorpusQuery("US", "statute"),
                              CorpusQuery("US", "court_rule", currentness="current_as_of", as_of=date(2025, 12, 1))):
                    self.assertEqual(store.search(query), [])
            result = accept_federal_rule(RecordRepository(), Settings(normalized_corpus_path=path))
            self.assertTrue(result["passed"], result)

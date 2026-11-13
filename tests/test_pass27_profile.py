"""Pass 27: more resume formats (.html, .odt, .rtf; scanned PDFs said, never guessed: blueprint 8.1), disputed facts
kept away from employer documents and career evidence (8.2), and the claim diff of a studio version: each claim with
the fact it came from, kept verbatim, rewritten or reverted by the guard (8.5). No network, no AI."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import Base, run_cli  # noqa: E402

from lodestar import careers, extras, profile, studio  # noqa: E402


class Formats(unittest.TestCase):
    def test_html_odt_and_rtf(self):
        html = b"<html><head><style>p{}</style><script>x=1</script></head><body><h2>Experience</h2><p>Store Manager &amp; buyer</p><ul><li>Led 14 staff</li></ul></body></html>"
        text = extras.import_document(html, "cv.html")
        self.assertIn("Experience", text)
        self.assertIn("Store Manager & buyer", text)
        self.assertIn("Led 14 staff", text)
        self.assertNotIn("x=1", text)
        odt = io.BytesIO()
        with zipfile.ZipFile(odt, "w") as z:
            z.writestr("content.xml", '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                       'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
                       '<text:h>Experience</text:h><text:p>Store Manager</text:p><text:p>Led <text:span>14</text:span> staff</text:p>'
                       '</office:text></office:body></office:document-content>')
        text = extras.import_document(odt.getvalue(), "cv.odt")
        self.assertEqual(text.splitlines(), ["Experience", "Store Manager", "Led 14 staff"])
        rtf = rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0\pard Experience\par Store Manager \'e9t\'e9\par\b Led\b0  14 staff\par}"
        text = extras.import_document(rtf, "cv.rtf")
        self.assertEqual([ln.strip() for ln in text.splitlines() if ln.strip()], ["Experience", "Store Manager été", "Led 14 staff"])

    def test_a_pdf_without_a_text_layer_is_said_not_guessed(self):
        from pypdf import PdfWriter

        w, buf = PdfWriter(), io.BytesIO()
        w.add_blank_page(612, 792)
        w.write(buf)
        with self.assertRaises(SystemExit) as cm:
            extras.import_document(buf.getvalue(), "scan.pdf")
        self.assertIn("no text layer", str(cm.exception))
        with self.assertRaises(SystemExit):
            extras.import_document(b"x", "cv.pages")


class Disputed(Base):
    def test_a_disputed_fact_leaves_employer_documents_and_career_evidence(self):
        bank = profile.load()
        bank["experience"] = [{"title": "Store Manager", "company": "Acme Retail", "bullets": ["Led 14 staff"]},
                              {"title": "Night Auditor", "company": "Saltmarsh Inn", "bullets": ["Balanced accounts"]}]
        profile.save(bank)
        self.assertIn("Saltmarsh Inn", json.dumps(profile.structured()))
        out = run_cli("profile", "dispute", "experience", "Saltmarsh Inn", "Night Auditor")
        self.assertIn("disputed", out)
        self.assertTrue(profile.is_disputed("experience", {"company": "saltmarsh inn", "title": "night auditor"}))
        self.assertNotIn("Saltmarsh Inn", json.dumps(profile.structured()))  # the master resume and the studio read this
        self.assertNotIn("Night Auditor", careers.evidence()["titles"])
        self.assertIn("Store Manager", careers.evidence()["titles"])
        run_cli("profile", "dispute", "experience", "Saltmarsh Inn", "Night Auditor", "--undo")
        self.assertIn("Saltmarsh Inn", json.dumps(profile.structured()))


class ClaimDiff(unittest.TestCase):
    META = {"plan": {"summary": {"refs": ["s0"], "text": "Retail leader."},
                     "sections": [{"kind": "experience", "items": [{"ref": "e1", "bullets": [
                         {"refs": ["e1.b1"]}, {"refs": ["e1.b2"], "text": "Cut shrink 30% in a year"},
                         {"refs": ["e1.b3"], "text": "Raised sales 50%"}]}]}]},
            "sources": {"s0": "Store manager.", "e1.b1": "Led 14 staff", "e1.b2": "Cut inventory shrink 30% in one year",
                        "e1.b3": "Raised sales"},
            "events": ["e1.b3: reverted (a number not in the cited facts)"]}

    def test_each_claim_names_its_fact_and_what_happened(self):
        rows = {r["ref"]: r for r in studio.claim_diff(self.META)}
        self.assertEqual((rows["e1.b1"]["change"], rows["e1.b1"]["after"]), ("verbatim", "Led 14 staff"))
        self.assertEqual((rows["e1.b2"]["change"], rows["e1.b2"]["before"]), ("rewritten", "Cut inventory shrink 30% in one year"))
        self.assertEqual((rows["e1.b3"]["change"], rows["e1.b3"]["after"]), ("reverted", "Raised sales"))
        self.assertIn("a number not in the cited facts", rows["e1.b3"]["why"])
        self.assertEqual(rows["s0"]["change"], "rewritten")

    def test_cited_sources_keep_only_what_the_plan_cites(self):
        doc = {"contact": {"headline": "Retail"}, "summary": "Store manager.", "experience": [
            {"id": "e1", "title": "Store Manager", "company": "Acme", "bullets": ["Led 14 staff", "Other"]}]}
        src = studio.cited_sources({"sections": [{"items": [{"ref": "e1", "bullets": [{"refs": ["e1.b1"]}]}]}]}, doc)
        self.assertEqual(src, {"e1": studio.ref_texts(doc)["e1"], "e1.b1": "Led 14 staff"})


if __name__ == "__main__":
    unittest.main()

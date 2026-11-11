"""Untrusted feed XML (news, Personio, We Work Remotely) goes through util.parse_xml, which refuses DTD/entity tricks."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as the other test modules when imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import util  # noqa: E402

BOMB = """<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<rss><channel><item><title>&lol2;</title></item></channel></rss>"""
XXE = """<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]><rss>&x;</rss>"""
RSS = """<?xml version="1.0"?><rss><channel><item><title>Data Engineer</title><link>https://example.com/1</link></item></channel></rss>"""


class ParseXml(unittest.TestCase):
    def test_entity_and_doctype_declarations_are_refused(self):
        for doc in (BOMB, XXE, BOMB.encode(), "<!doctype x><x/>"):
            with self.assertRaises(ValueError):
                util.parse_xml(doc)

    def test_plain_feeds_still_parse(self):
        root = util.parse_xml(RSS)
        self.assertEqual([t.text for t in root.iter("title")], ["Data Engineer"])
        self.assertEqual(util.parse_xml(RSS.encode()).tag, "rss")

    def test_every_feed_parser_uses_parse_xml(self):
        src = Path(util.__file__).parent
        for mod in ("intel.py", "web_monitor.py"):
            text = (src / mod).read_text(encoding="utf-8")
            self.assertNotIn("ET.fromstring", text, mod)
            self.assertIn("parse_xml(", text, mod)


if __name__ == "__main__":
    unittest.main()

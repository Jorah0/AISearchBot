"""The formatted copy of received mail (pass 54): an allowlist keeps formatting and drops anything that runs or
navigates; inline cid: images are embedded within size caps; the scan stores it with sign-in codes masked; the mail
list never carries it; an Inbox item that answers or comes from a mail names that mail."""
import email
import os
import sys
import tempfile
import unittest
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import db, email_monitor, mailhtml, web  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def message(html, images=()):
    m = MIMEMultipart("related")
    m["Subject"] = "Your verification code"
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("plain copy", "plain"))
    alt.attach(MIMEText(html, "html"))
    m.attach(alt)
    for cid, data in images:
        img = MIMEImage(data, "png")
        img.add_header("Content-ID", f"<{cid}>")
        m.attach(img)
    return email.message_from_bytes(m.as_bytes())


class Clean(unittest.TestCase):
    def test_keeps_formatting_drops_what_runs(self):
        out = mailhtml.clean('<style>a > b { color: red }</style><p style="color:red" onclick="x()">Hi <b>there</b></p>'
                             '<script>alert(1)</script><iframe src="https://x"></iframe><svg><script>1</script></svg>'
                             '<form><input name=p></form><a href="javascript:alert(1)">j</a><a href="https://ok.example">ok</a>'
                             '<img src="https://t.example/p.gif" onerror="x()"><div style="background:url(javascript:x)">d</div>')
        for kept in ('<p style="color:red">', "<b>there</b>", "a > b { color: red }", 'href="https://ok.example" target="_blank"',
                     'src="https://t.example/p.gif"', "<div>d</div>"):
            self.assertIn(kept, out)
        for gone in ("<script", "alert", "<iframe", "<svg", "<form", "<input", "onclick", "onerror", "javascript:"):
            self.assertNotIn(gone, out)

    def test_inline_images_embedded_within_caps(self):
        msg = message('<p>Logo <img src="cid:logo"> big <img src="cid:big"></p>', [("logo", PNG), ("big", PNG + b"0" * mailhtml.MAX_IMAGE)])
        out = mailhtml.of(msg)
        self.assertIn('src="data:image/png;base64,', out)
        self.assertEqual(out.count("<img"), 1)  # the oversized one is left out, never fetched
        self.assertEqual(mailhtml.clean(""), "")

    def test_scan_copy_masks_codes_and_the_list_never_carries_it(self):
        self.assertIn("******", email_monitor._formatted(message("<p>Your verification code is 482913</p>")))
        self.assertNotIn("html", db.MAIL_LIST.split(", "))
        db.add_mail(message_id="<html-1@example>", direction="in", from_addr="a@b.example", subject="s", body="t",
                    html="<p>formatted</p>")
        row = db.mail_by_message_id("<html-1@example>")
        self.assertEqual(row["html"], "<p>formatted</p>")
        self.assertEqual(web._with_mail({"payload": {"in_reply_to": "<html-1@example>"}})["mail_id"], row["id"])
        self.assertEqual(web._with_mail({"payload": {"evidence": {"mail": "<html-1@example>"}}})["mail_id"], row["id"])
        self.assertIsNone(web._with_mail({"payload": {"job_id": 3}})["mail_id"])


if __name__ == "__main__":
    unittest.main()

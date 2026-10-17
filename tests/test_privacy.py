from studyspace.llm import Gateway, OfflineProvider, clean_text, prepare, redact, restore

EMAIL = """Hi Jordan,

Could you finish the data cleaning section by Thursday night? My number is +65 9876 5432 and my
student ID is A0123456X, email priya.nair@u.example.edu. The Canvas password: hunter2

Thanks!
Priya
Year 1 MSc, Team 4

On Thu, 8 Oct 2026 at 09:00, Daniel Koh <daniel.koh@u.example.edu> wrote:
> Please complete the Lab 4 notebook before the next lab session.
> Daniel
"""


def test_cleaning_drops_quoted_reply_and_signature():
    text = clean_text(EMAIL)
    assert "Daniel Koh" not in text and "Lab 4" not in text  # quoted earlier message
    assert "Year 1 MSc" not in text                          # signature block
    assert "data cleaning section by Thursday night" in text


def test_outlook_style_quote_is_dropped():
    text = clean_text("Noted, thanks.\n\n-----Original Message-----\nFrom: Alan Tan\nSent: Monday\nSubject: x\nold text")
    assert text == "Noted, thanks."


def test_redaction_replaces_identifiers():
    r = redact(clean_text(EMAIL), known_names=["Priya Nair", "Priya"])
    for secret in ("+65 9876 5432", "A0123456X", "priya.nair@u.example.edu", "hunter2", "Jordan"):
        assert secret not in r.text
    assert "[PHONE]" in r.text and "[STUDENT_ID]" in r.text and "[EMAIL]" in r.text and "[SECRET]" in r.text
    assert r.counts["phone"] == 1 and r.counts["student_id"] == 1


def test_names_are_restored_locally():
    r = redact("Dear Alan Tan, thanks Alan Tan.", known_names=["Alan Tan"])
    assert r.text.count("[NAME_1]") == 2
    assert restore("Reply to [NAME_1]", r.mapping) == "Reply to Alan Tan"


def test_group_greetings_are_not_names():
    assert redact("Dear all,\nHi Everyone,").text == "Dear all,\nHi Everyone,"


def test_offline_gateway_sends_nothing():
    sent = []
    gw = Gateway(OfflineProvider(), log=lambda *a: sent.append(a))
    assert gw.online is False
    assert gw.ask("extract", "system", EMAIL) is None
    assert sent == []


def test_prepare_is_clean_then_redact():
    out = prepare(EMAIL, ["Priya"])
    assert "Daniel" not in out.text and "+65" not in out.text

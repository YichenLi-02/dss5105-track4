"""Synthetic development data: one fictional student's inbox, timetable and free time for AY2026/27 Sem 1.

Everything here is invented (people, modules, addresses, phone numbers). It exists so the system can be built
and demonstrated without anyone's real email. It is development data, not evaluation data: the extraction
score reported in the final submission comes from the held-out real set.

The demo clock is Monday 12 October 2026, 08:00 (Week 9). Three course PDFs sit beside the inbox (a brief with a
deadline that appears nowhere else, a problem set that repeats an email, lecture slides with no deadline).
The 25 emails cover the cases the blueprint lists:
explicit dates, a three-step deadline change, relative dates, week-based dates, a duplicate reminder,
"12 midnight" ambiguity, a task with no date that a later email fills in, quoted replies, signatures with
contact details, and non-task mail (newsletters, a recruiter, feedback notices).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from ..ingest.pdf_import import pdf_record_id
from ..timeutil import TZ
from .pdf import make_pdf

DEMO_NOW = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)
STUDENT = ("Jordan Lee", "jordan.lee@u.example.edu")
CANVAS = ("Canvas Notifications", "notifications@canvas.example.edu")
MODULES = {
    "DSX5101": ("Data Storytelling", "Prof. Alan Tan", "alan.tan@u.example.edu"),
    "QFX5202": ("Portfolio Analytics", "Prof. Grace Ho", "grace.ho@u.example.edu"),
    "SSX5103": ("Sustainable Systems Design", "Dr. Ravi Kumar", "ravi.kumar@u.example.edu"),
    "MLX5204": ("Applied Machine Learning", "Daniel Koh (TA)", "daniel.koh@u.example.edu"),
}
GROUPMATE = ("Priya Nair", "priya.nair@u.example.edu")
RECRUITER = ("Mei Ling Chua", "meiling.chua@talent.example.com")
KNOWN_NAMES = ["Jordan Lee", "Jordan", "Alan Tan", "Grace Ho", "Ravi Kumar", "Daniel Koh", "Priya Nair", "Priya", "Mei Ling Chua", "Mei Ling"]


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


def _staff(code: str) -> tuple[str, str]:
    _, name, email = MODULES[code]
    return name, email


def _canvas_subject(kind: str, title: str, code: str) -> str:
    return f"{kind} - {title}, {code} {MODULES[code][0]} [2610]"


@dataclass
class SynEmail:
    record_id: str
    received: datetime
    sender: tuple[str, str]
    subject: str
    body: str
    course_code: str | None = None
    in_reply_to: str | None = None

    def to_message(self) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = f"{self.sender[0]} <{self.sender[1]}>"
        msg["To"] = f"{STUDENT[0]} <{STUDENT[1]}>"
        msg["Subject"] = self.subject
        msg["Date"] = format_datetime(self.received)
        msg["Message-ID"] = f"<{self.record_id}@synthetic.studyspace.local>"
        msg["X-Record-Id"] = self.record_id
        if self.in_reply_to:
            msg["In-Reply-To"] = f"<{self.in_reply_to}@synthetic.studyspace.local>"
        msg.set_content(self.body)
        return msg


EMAILS: list[SynEmail] = [
    SynEmail("SYN-001", _t("2026-09-28T09:15"), CANVAS,
             _canvas_subject("Assignment created", "Data Story Draft", "DSX5101"),
             "A new assignment has been created for your course, DSX5101 Data Storytelling [2610]\n\n"
             "Data Story Draft\ndue: 16 Oct at 23:59\n\nClick to view", "DSX5101"),
    SynEmail("SYN-002", _t("2026-10-01T14:20"), _staff("QFX5202"),
             "Problem Set 3 released: QFX5202 Portfolio Analytics [2610]",
             "Dear class,\n\nProblem Set 3 is now available on Canvas. Please submit your solutions by "
             "Tuesday, 20 October 2026, 6:00 PM. Late submissions will not be accepted.\n\n"
             "Regards,\nGrace Ho\nProfessor, Department of Finance\nTel: +65 6516 0000\ngrace.ho@u.example.edu", "QFX5202"),
    SynEmail("SYN-003", _t("2026-09-21T10:00"), _staff("SSX5103"),
             "Reflective essay: SSX5103 Sustainable Systems Design [2610]",
             "Dear all,\n\nThe reflective essay (1,500 words) is due on Friday, 9 October, 5 pm. "
             "Please upload it to the Assignments folder.\n\nBest,\nRavi", "SSX5103"),
    SynEmail("SYN-004", _t("2026-10-05T16:40"), _staff("SSX5103"),
             "Reflective essay deadline extended: SSX5103 Sustainable Systems Design [2610]",
             "Dear all,\n\nFollowing your feedback, the reflective essay deadline is extended from 9 Oct to "
             "Wednesday 14 October, 5 pm.\n\nBest,\nRavi", "SSX5103"),
    SynEmail("SYN-005", _t("2026-10-09T11:05"), CANVAS, "Recent Canvas notifications",
             "You're signed up to receive a weekly report of some notifications from your Canvas account. "
             "Below is the report for the week ending 9 Oct:\n\n"
             "Assignment due date changed: Reflective Essay, SSX5103 Sustainable Systems Design [2610]\n"
             "due: 15 Oct at 17:00\nClick to view", "SSX5103"),
    SynEmail("SYN-006", _t("2026-10-07T13:30"), _staff("MLX5204"),
             "Quiz 1 next week: MLX5204 Applied Machine Learning [2610]",
             "Hi all,\n\nA reminder that Quiz 1 (online, 30 minutes) is due next Monday at 11:59pm. "
             "It covers Weeks 7 to 9.\n\nCheers,\nDaniel", "MLX5204"),
    SynEmail("SYN-007", _t("2026-10-06T18:00"), CANVAS,
             _canvas_subject("Assignment created", "Portfolio Case Report", "QFX5202"),
             "A new assignment has been created for your course, QFX5202 Portfolio Analytics [2610]\n\n"
             "Portfolio Case Report submission due 12 midnight Oct 23\n\nClick to view", "QFX5202"),
    SynEmail("SYN-008", _t("2026-10-08T09:00"), _staff("MLX5204"),
             "Lab 4 notebook: MLX5204 Applied Machine Learning [2610]",
             "Hi all,\n\nPlease complete the Lab 4 notebook before the next lab session. "
             "We will go through the solutions together.\n\nCheers,\nDaniel", "MLX5204"),
    SynEmail("SYN-009", _t("2026-10-12T07:30"), _staff("MLX5204"),
             "Re: Lab 4 notebook: MLX5204 Applied Machine Learning [2610]",
             "Quick update: please upload the Lab 4 notebook to Canvas tonight by 11pm.\n\nDaniel\n\n"
             "On Thu, 8 Oct 2026 at 09:00, Daniel Koh <daniel.koh@u.example.edu> wrote:\n"
             "> Hi all,\n> Please complete the Lab 4 notebook before the next lab session.", "MLX5204", "SYN-008"),
    SynEmail("SYN-010", _t("2026-09-29T15:00"), _staff("DSX5101"),
             "Midterm on Thursday 22 October: DSX5101 Data Storytelling [2610]",
             "Dear students,\n\nThe DSX5101 midterm will be held on Thursday, 22 October 2026 in LT27. "
             "The exam will start at 6:30 pm and runs for 90 minutes. It is closed book.\n\n"
             "Best regards,\nAlan Tan", "DSX5101"),
    SynEmail("SYN-011", _t("2026-10-09T10:00"), _staff("DSX5101"),
             "Reminder: midterm: DSX5101 Data Storytelling [2610]",
             "Reminder: our midterm is on 22 Oct at 6:30pm in LT27. Bring your student card.\n\nAlan", "DSX5101"),
    SynEmail("SYN-012", _t("2026-10-02T12:00"), _staff("SSX5103"),
             "Group project proposal: SSX5103 Sustainable Systems Design [2610]",
             "Dear all,\n\nEach team should submit a two-page project proposal by Friday of Week 9. "
             "One submission per team is enough.\n\nBest,\nRavi", "SSX5103"),
    SynEmail("SYN-013", _t("2026-09-18T17:00"), _staff("QFX5202"),
             "Peer review after recess: QFX5202 Portfolio Analytics [2610]",
             "Dear class,\n\nThe peer review of the case drafts is due the Monday after recess week, by 9am.\n\n"
             "Regards,\nGrace Ho", "QFX5202"),
    SynEmail("SYN-014", _t("2026-10-02T09:30"), _staff("MLX5204"),
             "Problem Set 2: MLX5204 Applied Machine Learning [2610]",
             "Hi all,\n\nProblem Set 2 is out. It is due on Friday 16 Oct, 11:59pm.\n\nCheers,\nDaniel", "MLX5204"),
    SynEmail("SYN-015", _t("2026-10-08T20:00"), _staff("DSX5101"),
             "Reading for the Week 10 seminar: DSX5101 Data Storytelling [2610]",
             "Dear students,\n\nPlease read chapters 4 and 5 of the course reader before Week 10. "
             "We will discuss them in the seminar.\n\nAlan", "DSX5101"),
    SynEmail("SYN-016", _t("2026-10-05T08:00"), ("Career Centre", "careers@u.example.edu"),
             "Career Fair 2026 newsletter",
             "Meet more than 80 employers at the Career Fair on 21 October, 11am to 5pm, at the University "
             "Sports Hall. Register on the careers portal.\n\nTo unsubscribe from this newsletter, update your preferences."),
    SynEmail("SYN-017", _t("2026-10-08T12:00"), ("Registrar's Office", "registrar@u.example.edu"),
             "Semester 2 timetable released",
             "The timetable for Semester 2 has been released. Module registration opens on 2 November at 9am. "
             "No action is required at this time."),
    SynEmail("SYN-018", _t("2026-10-10T11:20"), RECRUITER,
             "Coffee chat about the analyst programme?",
             "Hi Jordan,\n\nI came across your profile and would love to tell you about our graduate analyst "
             "programme. Let me know your availability by Friday for a 20-minute call.\n\n"
             "Best,\nMei Ling Chua\nTalent Acquisition\n+65 8123 4567"),
    SynEmail("SYN-019", _t("2026-10-11T21:00"), GROUPMATE,
             "MLX5204 project: data cleaning",
             "Hey Jordan,\n\nCould you finish the data cleaning section by Thursday night? I'll merge everything "
             "on Friday so we can rehearse.\n\nThanks!\nPriya\n+65 9876 5432", "MLX5204"),
    SynEmail("SYN-020", _t("2026-10-09T16:00"), _staff("MLX5204"),
             "PS2 deadline extension: MLX5204 Applied Machine Learning [2610]",
             "Hi all,\n\nThe deadline for Problem Set 2 has been extended from Oct 16 to Oct 19, 11:59pm.\n\n"
             "Cheers,\nDaniel", "MLX5204"),
    SynEmail("SYN-021", _t("2026-10-02T15:00"), _staff("SSX5103"),
             "Final report and presentations: SSX5103 Sustainable Systems Design [2610]",
             "Dear all,\n\nThe final report is due on Friday, 13 November 2026 at 11:59 pm. "
             "Team presentations will take place in Week 13 during the seminar.\n\nBest,\nRavi", "SSX5103"),
    SynEmail("SYN-022", _t("2026-10-05T09:00"), _staff("DSX5101"),
             "Weekly reflection: DSX5101 Data Storytelling [2610]",
             "Dear students,\n\nRemember to post your weekly reflection on the discussion forum. "
             "Short and specific is better than long.\n\nAlan", "DSX5101"),
    SynEmail("SYN-023", _t("2026-10-07T09:00"), ("University Library", "library@u.example.edu"),
             "Extended opening hours",
             "For your information: the library will stay open until 2am from 14 November until the end of "
             "the examinations."),
    SynEmail("SYN-024", _t("2026-10-09T18:30"), _staff("QFX5202"),
             "Feedback released: QFX5202 Portfolio Analytics [2610]",
             "Dear class,\n\nFeedback for Problem Set 2 has been released on Canvas. We will go through the "
             "common mistakes in the lecture on Tuesday 13 October.\n\nRegards,\nGrace Ho", "QFX5202"),
    SynEmail("SYN-025", _t("2026-10-11T07:00"), CANVAS, "Weekly digest: DSX5101 Data Storytelling [2610]",
             "You have no upcoming deadlines this week in DSX5101 Data Storytelling.", "DSX5101"),
]

# Course files (PDF): an assignment brief with deadlines, a problem set, and lecture slides with none.
COURSE_FILES = [
    ("ssx_brief", "SSX5103 Final Report Brief.pdf", "SSX5103 Final Report Brief", _t("2026-10-02T15:05"), [
        "SSX5103 Sustainable Systems Design - Final Report Brief",
        "Semester 1, AY2026/27. Coordinator: Dr. Ravi Kumar",
        "",
        "Overview",
        "Each team analyses one urban system (energy, water, food or mobility) and proposes a redesign that cuts "
        "its footprint by at least 30 percent.",
        "",
        "Milestones",
        "1. Peer feedback form: each member must submit the form by Friday of Week 12.",
        "2. Final report (4,000 words): due Friday, 13 November 2026 at 11:59 pm.",
        "3. Team presentation: 15 minutes in Week 13 during the seminar.",
        "",
        "Assessment",
        "Report 60%, presentation 25%, peer feedback 15%. Late submissions lose 5% of the mark per day.",
    ]),
    ("qfx_ps3", "QFX5202 Problem Set 3.pdf", "QFX5202 Problem Set 3", _t("2026-10-01T14:25"), [
        "QFX5202 Portfolio Analytics - Problem Set 3",
        "",
        "Instructions",
        "Work individually and show all steps. Submit a single PDF by Tuesday, 20 October 2026, 6:00 PM.",
        "",
        "Question 1 (30 marks): Estimate the covariance matrix of the five assets in the data file and comment on "
        "its stability over time.",
        "Question 2 (40 marks): Construct the minimum-variance portfolio with and without short-selling constraints.",
        "Question 3 (30 marks): Compare the out-of-sample Sharpe ratios of both portfolios.",
    ]),
    ("mlx_lecture8", "MLX5204 Lecture 8 - Model Evaluation.pdf", "MLX5204 Lecture 8: Model evaluation", _t("2026-10-08T09:30"), [
        "MLX5204 Applied Machine Learning - Lecture 8: Model evaluation",
        "",
        "Why accuracy is not enough",
        "Precision, recall and the F1 score",
        "Cross-validation and data leakage",
        "Calibration curves and reliability diagrams",
        "",
        "Reading: chapter 7 of the course notes (optional).",
        "Next week: Lecture 9 on interpretability.",
    ]),
]

# What a careful human reads in each message. Written from the emails, not from the extractor's output.
GOLD_TASKS = [
    {"gold_id": "G01", "source_ids": ["SYN-001"], "course_code": "DSX5101", "title": "Data Story Draft", "kind": "deliverable",
     "due_date": "2026-10-16", "due_time": "23:59", "flags": []},
    {"gold_id": "G02", "source_ids": ["SYN-002", "FILE:qfx_ps3"], "course_code": "QFX5202", "title": "Problem Set 3", "kind": "deliverable",
     "due_date": "2026-10-20", "due_time": "18:00", "flags": [], "note": "the email and the problem set PDF give the same deadline"},
    {"gold_id": "G03", "source_ids": ["SYN-003", "SYN-004", "SYN-005"], "course_code": "SSX5103", "title": "Reflective essay",
     "kind": "deliverable", "due_date": "2026-10-15", "due_time": "17:00", "flags": ["DATE_CHANGED"],
     "note": "9 Oct 17:00 -> 14 Oct 17:00 -> 15 Oct 17:00"},
    {"gold_id": "G04", "source_ids": ["SYN-006"], "course_code": "MLX5204", "title": "Quiz 1", "kind": "deliverable",
     "due_date": "2026-10-12", "due_time": "23:59", "flags": ["NEEDS_CONFIRM"], "note": "'next Monday' from Wed 7 Oct"},
    {"gold_id": "G05", "source_ids": ["SYN-007"], "course_code": "QFX5202", "title": "Portfolio Case Report", "kind": "deliverable",
     "due_date": "2026-10-23", "due_time": None, "flags": ["MIDNIGHT_AMBIGUITY"],
     "note": "'12 midnight Oct 23': start or end of 23 Oct; must be confirmed"},
    {"gold_id": "G06", "source_ids": ["SYN-008", "SYN-009"], "course_code": "MLX5204", "title": "Lab 4 notebook", "kind": "deliverable",
     "due_date": "2026-10-12", "due_time": "23:00", "flags": ["NEEDS_CONFIRM"], "note": "no date in SYN-008; SYN-009 says tonight 11pm"},
    {"gold_id": "G07", "source_ids": ["SYN-010", "SYN-011"], "course_code": "DSX5101", "title": "Midterm", "kind": "event",
     "due_date": "2026-10-22", "due_time": "18:30", "flags": [], "note": "SYN-011 repeats SYN-010"},
    {"gold_id": "G08", "source_ids": ["SYN-012"], "course_code": "SSX5103", "title": "Project proposal", "kind": "deliverable",
     "due_date": "2026-10-16", "due_time": None, "flags": ["NEEDS_CONFIRM"], "note": "'Friday of Week 9', no time"},
    {"gold_id": "G09", "source_ids": ["SYN-013"], "course_code": "QFX5202", "title": "Peer review of case drafts", "kind": "deliverable",
     "due_date": "2026-09-28", "due_time": "09:00", "flags": ["NEEDS_CONFIRM"], "note": "'the Monday after recess week'; already past at the demo clock"},
    {"gold_id": "G10", "source_ids": ["SYN-014", "SYN-020"], "course_code": "MLX5204", "title": "Problem Set 2", "kind": "deliverable",
     "due_date": "2026-10-19", "due_time": "23:59", "flags": ["DATE_CHANGED"], "note": "16 Oct -> 19 Oct"},
    {"gold_id": "G11", "source_ids": ["SYN-015"], "course_code": "DSX5101", "title": "Read chapters 4 and 5", "kind": "deliverable",
     "due_date": None, "due_time": None, "flags": ["NEEDS_CONFIRM"], "note": "'before Week 10': no exact day"},
    {"gold_id": "G12", "source_ids": ["SYN-019"], "course_code": "MLX5204", "title": "Finish the data cleaning section", "kind": "deliverable",
     "due_date": "2026-10-15", "due_time": None, "flags": ["NEEDS_CONFIRM"], "note": "'by Thursday night' from a groupmate"},
    {"gold_id": "G13", "source_ids": ["SYN-021", "FILE:ssx_brief"], "course_code": "SSX5103", "title": "Final report", "kind": "deliverable",
     "due_date": "2026-11-13", "due_time": "23:59", "flags": [], "note": "email and brief agree"},
    {"gold_id": "G14", "source_ids": ["SYN-021", "FILE:ssx_brief"], "course_code": "SSX5103", "title": "Team presentation", "kind": "event",
     "due_date": None, "due_time": None, "flags": ["NEEDS_CONFIRM"], "note": "'in Week 13 during the seminar': day not stated"},
    {"gold_id": "G15", "source_ids": ["SYN-022"], "course_code": "DSX5101", "title": "Weekly reflection", "kind": "deliverable",
     "due_date": None, "due_time": None, "flags": ["MISSING_DUE_AT"], "note": "recurring, no deadline given"},
    {"gold_id": "G16", "source_ids": ["FILE:ssx_brief"], "course_code": "SSX5103", "title": "Peer feedback form", "kind": "deliverable",
     "due_date": "2026-11-06", "due_time": None, "flags": ["NEEDS_CONFIRM"], "note": "only in the brief PDF: 'by Friday of Week 12'"},
]
GOLD_NON_TASK = {
    "SYN-016": "newsletter (career fair)",
    "SYN-017": "information only",
    "SYN-018": "recruiter: needs a reply, not a course task",
    "SYN-023": "information only",
    "SYN-024": "feedback notice; the date is a lecture, not a deadline",
    "SYN-025": "digest with no deadlines",
    "FILE:mlx_lecture8": "lecture slides; optional reading without a date",
}

TIMETABLE = [
    # code, label, weekday date in Week 1, start, end, recess-week date to skip
    ("DSX5101", "DSX5101 Lecture (LT27)", "2026-08-10", "10:00", "12:00", "2026-09-21"),
    ("QFX5202", "QFX5202 Lecture (LT11)", "2026-08-11", "18:30", "21:30", "2026-09-22"),
    ("SSX5103", "SSX5103 Seminar (SR3)", "2026-08-12", "18:30", "21:30", "2026-09-23"),
    ("MLX5204", "MLX5204 Lecture (LT19)", "2026-08-13", "18:30", "20:30", "2026-09-24"),
    ("MLX5204", "MLX5204 Lab (Lab 2)", "2026-08-14", "10:00", "12:00", "2026-09-25"),
]

FREE_TIME = {
    "from": "2026-10-12",
    "to": "2026-11-13",
    "weekly": [
        {"weekday": "monday", "start": "13:00", "end": "18:00"},
        {"weekday": "tuesday", "start": "09:00", "end": "12:00"},
        {"weekday": "tuesday", "start": "13:00", "end": "17:00"},
        {"weekday": "wednesday", "start": "09:00", "end": "12:00"},
        {"weekday": "wednesday", "start": "14:00", "end": "17:30"},
        {"weekday": "thursday", "start": "09:00", "end": "12:00"},
        {"weekday": "thursday", "start": "13:00", "end": "17:00"},
        {"weekday": "friday", "start": "13:00", "end": "18:00"},
        {"weekday": "saturday", "start": "10:00", "end": "16:00"},
        {"weekday": "sunday", "start": "14:00", "end": "18:00"},
    ],
}

SENT_SAMPLES = [
    ("sent-01.txt", "To: Prof. Alan Tan\nSubject: Question about the data story draft\n\n"
     "Hi Prof Tan,\n\nCould I check whether the draft should include the final charts or only a storyboard? "
     "Happy to bring a sketch to the seminar.\n\nThanks,\nJordan"),
    ("sent-02.txt", "To: Priya Nair\nSubject: Re: data cleaning\n\n"
     "Hey Priya, sure, I'll push the cleaned dataset by Thursday evening and ping you once it's up. Jordan"),
    ("sent-03.txt", "To: Daniel Koh\nSubject: Lab 4 submission\n\n"
     "Hi Daniel,\n\nI've uploaded Lab 4 to Canvas. One cell takes a while to run, so I left the outputs in.\n\nBest,\nJordan"),
]


@dataclass
class Dataset:
    emails: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, .eml bytes)
    timetable_ics: str = ""
    free_time: dict = field(default_factory=dict)
    gold: dict = field(default_factory=dict)
    emails_csv: str = ""
    course_files: list[tuple[str, bytes, datetime]] = field(default_factory=list)  # (filename, PDF bytes, received)


def _ics() -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Studyspace//Synthetic timetable//EN", "CALSCALE:GREGORIAN"]
    for i, (code, label, first, start, end, recess) in enumerate(TIMETABLE, start=1):
        d = first.replace("-", "")
        r = recess.replace("-", "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:syn-{i:02d}@synthetic.studyspace.local",
            f"SUMMARY:{label}",
            f"DTSTART;TZID=Asia/Singapore:{d}T{start.replace(':', '')}00",
            f"DTEND;TZID=Asia/Singapore:{d}T{end.replace(':', '')}00",
            "RRULE:FREQ=WEEKLY;COUNT=14",
            f"EXDATE;TZID=Asia/Singapore:{r}T{start.replace(':', '')}00",
            f"CATEGORIES:{code}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _csv(emails: list[SynEmail]) -> str:
    """The same emails in member 2's hand-over CSV format."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["record_id", "course_code", "subject", "posted_at", "received_at", "timezone",
                     "academic_context", "body_text", "body_text_type"])
    for e in emails:
        writer.writerow([e.record_id, e.course_code or "", e.subject, "", e.received.isoformat(), "Asia/Singapore",
                         "AY2026/27 Sem 1 (synthetic)", e.body, "synthetic"])
    return out.getvalue()


def build() -> Dataset:
    files = [(key, filename, make_pdf(title, lines), received) for key, filename, title, received, lines in COURSE_FILES]
    ids = {f"FILE:{key}": pdf_record_id(data) for key, _, data, _ in files}
    tasks = [{**t, "source_ids": [ids.get(sid, sid) for sid in t["source_ids"]]} for t in GOLD_TASKS]
    non_task = {ids.get(k, k): v for k, v in GOLD_NON_TASK.items()}
    return Dataset(
        emails=[(f"{e.record_id}.eml", e.to_message().as_bytes()) for e in EMAILS],
        timetable_ics=_ics(),
        free_time=FREE_TIME,
        gold={
            "provenance": "Synthetic development data, hand-labelled from the messages and course files. Not evaluation data.",
            "demo_now": DEMO_NOW.isoformat(),
            "files": {ids[f"FILE:{key}"]: filename for key, filename, _, _ in files},
            "tasks": tasks,
            "non_task_sources": non_task,
        },
        emails_csv=_csv(EMAILS),
        course_files=[(filename, data, received) for _, filename, data, received in files],
    )


def write(directory: str | Path) -> Path:
    root = Path(directory)
    (root / "emails").mkdir(parents=True, exist_ok=True)
    (root / "sent").mkdir(parents=True, exist_ok=True)
    data = build()
    for name, raw in data.emails:
        (root / "emails" / name).write_bytes(raw)
    (root / "timetable.ics").write_text(data.timetable_ics, encoding="utf-8", newline="")
    (root / "free_time.json").write_text(json.dumps(data.free_time, indent=2) + "\n", encoding="utf-8")
    (root / "gold.json").write_text(json.dumps(data.gold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "emails.csv").write_text(data.emails_csv, encoding="utf-8")
    for name, text in SENT_SAMPLES:
        (root / "sent" / name).write_text(text + "\n", encoding="utf-8")
    (root / "files").mkdir(parents=True, exist_ok=True)
    for name, data, _ in data.course_files:
        (root / "files" / name).write_bytes(data)
    return root

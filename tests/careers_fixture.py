"""A tiny O*NET-shaped ontology and a fictional retail-manager profile bank, shared by the career discovery unit and
E2E tests (pass 23). Codes, titles and zones mirror O*NET's shape; the relations are chosen so every tier and class
appears: see test_pass23_careers.Discovery for the expected outcome of each code."""
import gzip
import json
from pathlib import Path


def _o(title, zone, titles, related, tasks, tech):
    return {"title": title, "zone": zone, "titles": titles, "related": related, "tasks": tasks, "tech": tech}


OCC = {
    "41-1011.00": _o("First-Line Supervisors of Retail Sales Workers", 3,
                     ["Store Manager", "Assistant Store Manager", "Retail Store Manager"],
                     ["41-2031.00", "11-2022.00", "11-9051.00", "13-1081.00", "43-4051.00", "11-1011.00"],
                     ["Direct and supervise employees engaged in sales, inventory-taking, reconciling cash receipts.",
                      "Prepare work schedules and assign employees to specific duties.",
                      "Formulate pricing policies for merchandise."],
                     ["Microsoft Excel", "Inventory management software", "Point of sale POS software"]),
    "41-2031.00": _o("Retail Salespersons", 2, ["Sales Associate", "Retail Sales Associate"], ["41-1011.00"],
                     ["Greet customers and ascertain what each customer wants or needs."], ["Point of sale POS software"]),
    "43-4051.00": _o("Customer Service Representatives", 2, ["Customer Service Representative"], ["41-2031.00"],
                     ["Confer with customers by telephone or in person to provide information."],
                     ["Customer relationship management CRM software"]),
    "11-2022.00": _o("Sales Managers", 4, ["Sales Manager"], ["41-1011.00"],
                     ["Determine price schedules and discount rates."], ["Salesforce software", "Microsoft Excel"]),
    "11-9051.00": _o("Food Service Managers", 3, ["Restaurant Manager"], ["41-1011.00", "11-9081.00"],
                     ["Monitor food preparation methods and portion sizes."], ["Microsoft Excel"]),
    "13-1081.00": _o("Logisticians", 4, ["Logistics Analyst"], ["41-1011.00"],
                     ["Maintain databases of logistics information."], ["SAP software"]),
    "11-1011.00": _o("Chief Executives", 5, ["Chief Executive Officer"], [],
                     ["Direct or coordinate an organization's financial or budget activities."], []),
    "11-9081.00": _o("Lodging Managers", 4, ["Hotel Manager", "Hospitality Manager"], ["43-4081.00", "11-9051.00"],
                     ["Coordinate front-office activities of hotels or motels."], ["Property management system software"]),
    "43-4081.00": _o("Hotel, Motel, and Resort Desk Clerks", 2, ["Front Desk Agent"], ["11-9081.00"],
                     ["Register arriving guests and assign rooms."], []),
    "29-1141.00": _o("Registered Nurses", 3, ["Registered Nurse", "Staff Nurse"], [],
                     ["Monitor, record, and report symptoms or changes in patients' conditions."],
                     ["Electronic health record EHR software"]),
}

META = {"version": "test", "source": "O*NET test fixture", "url": "https://www.onetcenter.org/database.html",
        "license": "CC BY 4.0", "credit": "test fixture credit", "built": "2026-11-13"}

BANK = {"schema": 2, "contact": {}, "summary": "", "resumes": [], "updated": "",
        "experience": [{"title": "Store Manager", "company": "Acme Retail", "start": "2019-01", "end": "2025-06",
                        "bullets": ["Prepared weekly schedules for 14 employees",
                                    "Reconciled cash receipts and cut inventory shrink"]}],
        "skills": [{"name": "Microsoft Excel"}, {"name": "Inventory management"}],
        "education": [{"school": "Bay College", "degree": "Associate of Arts"}]}


def write_fixture(path: Path) -> Path:
    occ = {c: {**o, "code": c, "desc": ""} for c, o in OCC.items()}
    Path(path).write_bytes(gzip.compress(json.dumps({"meta": META, "occ": occ}).encode("utf-8")))
    return Path(path)

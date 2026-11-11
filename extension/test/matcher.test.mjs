// Matcher tests: node --test extension/test/  (Node's built-in runner; no npm packages).
// The descriptors are what the real LodestarScan read from each fixture form (tests/e2e/e2e_extension.py checks they
// still are, and LODESTAR_E2E_UPDATE=1 rewrites them), so these tests need no DOM.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const M = require("../matcher.js");
const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.descriptors.json`, import.meta.url), "utf8"));

function keys(name) {
  const ds = M.groups(fixture(name));
  return Object.fromEntries(ds.map((d) => [d.id || d.name || d.auto, M.classify(d)]));
}

const EXPECTED = {
  greenhouse: {
    first_name: "first", last_name: "last", email: "email", phone: "phone", job_application_location: "city", resume: null,
    q_linkedin: "linkedin", q_website: "website", q_why: "question", q_auth: "question", q_hear: "question",
    gender: "eeo.gender", hispanic_ethnicity: "eeo.hispanic", veteran_status: "eeo.veteran", disability_status: "eeo.disability",
  },
  lever: {
    resume: null, name: "name", email: "email", phone: "phone", location: "location", org: "current_company",
    "urls[LinkedIn]": "linkedin", "urls[GitHub]": "github", "urls[Portfolio]": "website", "cards[0f3e][field0]": "question",
    "cards[0f3e][field1]": "question", "eeo[gender]": "eeo.gender", "eeo[race]": "eeo.race", "eeo[veteran]": "eeo.veteran",
  },
  ashby: {
    _systemfield_name: "name", _systemfield_email: "email", _systemfield_location: "location", f2a1: "phone",
    f2a2: "linkedin", f2a3: "question", f2a4: "salary", eeo_gender: "eeo.gender",
  },
  workday: {
    "name--legalName--firstName": "first", "name--legalName--lastName": "last", countryDropdown: "question",
    "address--city": "city", "emailAddress--emailAddress": "email", "phoneNumber--phoneNumber": "phone",
    "workExperience-1--jobTitle": "exp.title", "workExperience-1--companyName": "exp.company",
    "workExperience-1--location": "exp.location", "workExperience-1--startDate-dateSectionMonth-input": "exp.start",
    "workExperience-1--startDate-dateSectionYear-input": "exp.start", "workExperience-1--roleDescription": "exp.description",
    "workExperience-2--jobTitle": "exp.title", "workExperience-2--companyName": "exp.company",
    "workExperience-2--startDate-dateSectionYear-input": "exp.start", "workExperience-2--endDate-dateSectionYear-input": "exp.end",
    "education-1--school": "edu.school", "education-1--degree": "edu.degree",
  },
  smartrecruiters: {
    "first-name": "first", "last-name": "last", email: "email", "confirm-email": "email", "phone-number": "phone",
    linkedin: "linkedin",
  },
  generic: {  // the honeypots are not here at all: the scan never reports a hidden, tiny, off-page or disabled field
    g1: "first", g2: "last", g3: "email", g4: "phone", g5: "current_company", g6: "current_title", g7: "website",
    g8: "salary", g9: "question", g10: "phone", reloc: "question", g11: "question", d1: null, d2: null, d3: null,
  },
};

for (const [name, want] of Object.entries(EXPECTED)) {
  test(`${name} fixture classifies as expected`, () => assert.deepEqual(keys(name), want));
}

test("work history groups follow DOM order, whatever their numbers", () => {
  const ds = M.groups(fixture("workday"));
  const g = Object.fromEntries(ds.map((d) => [d.id || d.auto, d.group]));
  assert.equal(g["workExperience-1--jobTitle"], "exp:0");
  assert.equal(g["workExperience-2--endDate-dateSectionYear-input"], "exp:1");
  assert.equal(g["education-1--school"], "edu:0");
  assert.equal(g["name--legalName--firstName"], null);
  const three = M.groups([7, 3, 12].map((n) => ({ id: `workExperience-${n}--jobTitle`, label: "Job Title", tag: "input", type: "text" })));
  assert.deepEqual(three.map((d) => d.group), ["exp:0", "exp:1", "exp:2"]);
  assert.deepEqual(three.map(M.classify), ["exp.title", "exp.title", "exp.title"]);
  const eeo = M.groups([{ id: "q1", label: "Veteran", section: "U.S. Equal Employment Opportunity information", tag: "select", type: "" }]);
  assert.equal(eeo[0].group, null);  // an EEO heading is not a work history section
});

test("the denylist and the never-fill types yield no fillable key", () => {
  const field = (o) => ({ tag: "input", type: "text", ...o });
  for (const d of [
    field({ label: "Social Security Number" }), field({ label: "SSN" }), field({ label: "Date of birth" }), field({ label: "DOB" }),
    field({ label: "Passport number" }), field({ label: "Driver's license" }), field({ label: "Bank account (IBAN)" }),
    field({ label: "Routing number" }), field({ label: "Card number" }), field({ label: "CVV" }), field({ name: "national_id" }),
    field({ label: "Tax ID" }), field({ label: "Email", type: "password" }), field({ label: "Resume", type: "file" }),
    field({ label: "Desired salary", type: "hidden" }), field({ label: "First name", type: "checkbox" }),
    field({ label: "Email", type: "submit" }), field({ id: "first_name", label: "First name", aria: "password" }),
  ]) assert.equal(M.classify(d), null, JSON.stringify(d));
});

test("autocomplete tokens and labels classify unknown forms", () => {
  assert.equal(M.classify({ tag: "input", type: "text", autocomplete: "section-a given-name" }), "first");
  assert.equal(M.classify({ tag: "input", type: "text", autocomplete: "organization-title" }), "current_title");
  assert.equal(M.classify({ tag: "input", type: "text", label: "Open to relocation?" }), "question");  // not 'location'
  assert.equal(M.classify({ tag: "input", type: "text", label: "Tell us about yourself" }), "question");  // not 'tel'
  assert.equal(M.classify({ tag: "input", type: "number", label: "Years of experience with Spark" }), null);
  assert.equal(M.classify({ tag: "input", type: "text", label: "What are your salary expectations?" }), "salary");
  assert.equal(M.classify({ tag: "input", type: "text", label: "" }), null);
});

test("normalizeDate reads the shapes a profile holds", () => {
  const cases = [["Jan 2020", { m: 1, y: 2020, current: false }], ["September 2019", { m: 9, y: 2019, current: false }],
    ["2020-01", { m: 1, y: 2020, current: false }], ["01/2020", { m: 1, y: 2020, current: false }],
    ["2020", { m: null, y: 2020, current: false }], ["Present", { m: null, y: null, current: true }],
    ["current", { m: null, y: null, current: true }], ["", null], ["spring", null]];
  for (const [v, want] of cases) assert.deepEqual(M.normalizeDate(v), want, v);
});

test("pickOption: exact, starts-with, a prose answer, contains, decline synonyms, else nothing", () => {
  const yn = [{ v: "", t: "Please select" }, { v: "1", t: "Yes" }, { v: "0", t: "No" }];
  assert.equal(M.pickOption(yn, "Yes"), "1");
  assert.equal(M.pickOption(yn, "Yes, without sponsorship."), "1");
  assert.equal(M.pickOption(yn, "Not applicable"), null);  // 'No' is not a prefix word of 'Not'
  assert.equal(M.pickOption(yn, "Maybe"), null);
  const vet = [{ v: "", t: "Select" }, { v: "1", t: "I am not a protected veteran" }, { v: "3", t: "I don't wish to answer" }];
  assert.equal(M.pickOption(vet, "Decline to self-identify"), "3");
  assert.equal(M.pickOption(vet, "not a protected veteran"), "1");
  const g = [{ v: "", t: "Please select" }, { v: "1", t: "Male" }, { v: "2", t: "Female" }, { v: "3", t: "Decline To Self Identify" }];
  assert.equal(M.pickOption(g, "Decline to self-identify"), "3");
  assert.equal(M.pickOption(g, "Female"), "2");  // not 'Male' (contained in 'Female')
  assert.equal(M.pickOption([], "Yes"), null);
});

test("LinkedIn is recognised on any subdomain and nowhere else", () => {
  for (const h of ["linkedin.com", "www.linkedin.com", "LinkedIn.com.", "ca.linkedin.com"]) assert.ok(M.linkedin(h), h);
  for (const h of ["notlinkedin.com", "linkedin.com.evil.example", "", "127.0.0.1"]) assert.ok(!M.linkedin(h), h);
});

test("detectAts and ATS iframes", () => {
  assert.equal(M.detectAts("boards.greenhouse.io", []), "greenhouse");
  assert.equal(M.detectAts("acme.wd5.myworkdayjobs.com", []), "workday");
  assert.equal(M.detectAts("careers.example.com", ["lever"]), "lever");
  assert.equal(M.detectAts("careers.example.com", []), null);
  assert.equal(M.atsFrame("https://boards.greenhouse.io/embed/job_app?for=x", "https://www.example.com"),
    "https://boards.greenhouse.io/embed/job_app?for=x");
  assert.equal(M.atsFrame("https://www.youtube.com/embed/x", "https://www.example.com"), null);
  assert.equal(M.atsFrame("javascript:alert(1)", "https://www.example.com"), null);
  assert.equal(M.atsFrame("/apply", "https://boards.greenhouse.io"), null);  // same origin: Fill already reaches it
});

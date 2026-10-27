# -*- coding: utf-8 -*-
"""English edition of the Mabaneek guide for Bayan Oman: one HTML source, two outputs.

    python deliverables/promo-bayan/tools/build_guide_en.py     (then: node deliverables/promo-bayan/tools/print_pdf.mjs)

- guide-en-print.html : full document, opened locally by Chrome to print the A4 PDF.
- index-en.html       : the same page as an artifact fragment (no <html>/<head>/<body>), dark/light tokens, phone-safe.
Screenshots are the real Arabic (right-to-left) interface; the platform's English switch covers navigation labels only,
and every record shown comes from the server in Arabic. Captions explain each one in English. Facts are read from
tools/demo-state.json; nothing is typed by hand that the platform did not produce.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from hijridate import Gregorian

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PKG = HERE.parent

STATE = json.loads((HERE / "demo-state.json").read_text(encoding="utf-8")) if (HERE / "demo-state.json").exists() else {}
FACTS = STATE.get("facts", {})
DOCS = STATE.get("docs", {})
QN, CN, IN_, RN = DOCS.get("quote", "QT-2026-00001"), DOCS.get("contract", "SPA-00001"), DOCS.get("invoice", "INV-2026-000107"), DOCS.get("receipt", "MBQ-H-000001")
QUNIT = STATE.get("quote", {}).get("unit_code") or "MSK-M-203"
N_UNITS, N_PLANS, N_PROJECTS = FACTS.get("units", 317), FACTS.get("plans", 29), FACTS.get("projects", 6)

LIVE = "https://mabaneek.com"
import datetime as dt

TODAY = dt.date(2026, 10, 27)
_h = Gregorian(TODAY.year, TODAY.month, TODAY.day).to_hijri()
_EN_MONTH = {"Jumada al-Ula": "Jumada al-Awwal", "Jumada al-Akhirah": "Jumada al-Thani"}  # the house spelling used in Arabic-first documents
_mn = _h.month_name('en')
HIJRI = f"{_h.day} {_EN_MONTH.get(_mn, _mn)} {_h.year} AH"
GREG = f"{TODAY.day} {TODAY:%B} {TODAY.year}"
DATE_LINE = f"{HIJRI} · {GREG}"

TITLE = "Mabaneek for Bayan Oman"
SUBTITLE = "Your platform from leasing and sales to handover"
TAGLINE = "One platform for your commercial and residential portfolio: leased, sold and handed over"


def esc(t: str) -> str:
    return html.escape(t, quote=False)


def F(name: str, caption: str, ratio: float | None = None, ext: str = "jpg") -> dict:
    return {"src": f"web-assets/{name}.{ext}", "caption": caption, "ratio": ratio}


# ───────────────────────────────────────────────────────────────────────────────────────────── content

INTRO = {
    "kicker": "About this guide",
    "title": "The platform as Bayan Oman would use it today",
    "lead": "This guide shows Mabaneek, the real estate development platform from Jadwa for Studies and Development, loaded with Bayan Oman's published portfolio: "
            "Masahat Al Khoudh, Al Shabab Business Centre, Alaa Business Avenue, MQ Residences, Mabelah Gateway and Al Khuwair Square, with the plans and renders from your three brochures and your letterhead on every document.",
    "bullets": [
        f"Every screenshot comes from the working platform (version 0.15.0) after loading your published data: {N_UNITS} units in {N_PROJECTS} projects and {N_PLANS} plans and renders.",
        "Prices, rents, sales ratios, progress percentages, tenants and buyers are illustrative. Bayan does not publish prices or rents; the real figures will run through the same logic.",
        "Your portfolio is mostly commercial, so the guide starts from leasing (contracts, quarterly instalments, arrears, renewals, occupancy) next to sales, not from residential sales alone.",
        "The product is Arabic-first and right-to-left, so the screenshots show the Arabic interface. The English switch covers navigation labels; project names, units and documents come from the server in Arabic. Each caption explains what you are looking at.",
        "Nothing is promised that does not exist. What is not yet proven live, or waits on a decision from Bayan, is listed on the last two pages.",
        "Finance is Islamic finance only: no interest and no interest-bearing loans. Payment plans are murabaha or instalments, and a late-payment charge is a charitable donation, never revenue.",
    ],
}

WHY = {
    "kicker": "Why now",
    "title": "Three problems of a developer that sells and leases at the same time",
    "lead": "A commercial portfolio means hundreds of offices and shops. Some are sold, some are kept and leased, and all of them need one version of the truth: who occupies what, who paid how much, and which contract ends next month.",
    "cards": [
        ("Leases and quarterly instalments scattered across sheets",
         "A contract in one file, a quarterly payment in a bank statement, a renewal discovered after the contract has ended. Arrears surface only when someone reviews the sheet by hand."),
        ("One building, sold and leased together",
         "At Masahat Al Khoudh some shops and offices are for sale and others are kept for rent. Without one system the states blur, and the signal about price and demand on each segment is lost."),
        ("A group with more than one entity",
         "Bayan Investment House and Bayan Oman each need their own data and their own letterhead, without separate systems and duplicated accounts."),
    ],
    "close": "Mabaneek brings the three into one place: a live leasing portfolio with its contracts and instalments, sale inventory on the real plans, and isolated developers inside a single platform.",
}

OVERVIEW = {
    "kicker": "Overview",
    "title": "The platform on one page",
    "lead": "The platform follows the three-stage development cycle, with two shared layers running over it: finance and collections, and governance and reporting. Each entity is isolated by its own data, and each user by role and permissions.",
    "cols": [
        ("1 · Land and permits", ["Land and feasibility studies", "Permits and government bodies"]),
        ("2 · Sales and construction", ["Inventory, pricing and plans", "Leads and marketing", "Quotes, bookings and contracts", "Construction and payment certificates"]),
        ("3 · Handover and operations", ["Handover, defects and title transfer", "Owners' association and facilities", "Leasing and customer service"]),
        ("Across the cycle", ["Liquidity and default risk, invoices and escrow", "Reports and analytics, audit log", "Administration, security and document identity"]),
    ],
    "fig": F("02-dashboard", "The dashboard for the Bayan Oman developer: four headline indicators, the decision box in priority order, and the project cycle in the side bar.", .5),
}

TOUR = [
    {"id": "sign-in", "kicker": "Sign-in and identity", "title": "Secure sign-in under your company's name, and one entity per company in the group",
     "lead": "Users pick the developer, Bayan Oman, and sign in with a password or with the company's Google account. Accounts are never created from outside: an identity is matched to an account that an administrator created. "
             "The same developer list is where other entities of the group live, if Bayan Investment House wants a separate portfolio with its own letterhead.",
     "bullets": ["Ready-made roles: general manager, sales and leasing, finance, engineer, investor, broker and customer. Each role sees only what concerns it.",
                 "Two-factor authentication (TOTP) with recovery codes, sessions listed per device and ended remotely, and graded lockout against guessing.",
                 "Each entity in a group is a developer isolated row by row in the database (row-level security), not merely in the application."],
     "figs": [F("01-login", "Sign-in with developer selection. The password field is masked.", .62), F("30-security-2fa", "The security tab: two-factor set-up, active sessions and sign-out from all devices.", .5)]},
    {"id": "dashboard", "kicker": "Dashboard", "title": "What needs your decision today",
     "lead": "The dashboard does not only show numbers. It proposes decisions ranked by priority and financial impact: a projected liquidity gap in a project's escrow account, a payment certificate the progress evidence does not support, a customer who needs rescheduling, or an office segment worth repricing.",
     "bullets": [f"Portfolio: {N_UNITS} units in {N_PROJECTS} projects (illustrative data on the areas published in your brochures).",
                 "Liquidity: a monthly forecast of each escrow account with the expected peak shortfall and its cause.",
                 "Today's decisions: each one carries its source (liquidity radar, progress check, default model, dynamic pricing) and its status."],
     "figs": [F("02b-dashboard-full", "The full decision box: priority, impact, source and status.", .95)]},
    {"id": "inventory", "kicker": "Inventory and pricing", "title": "Masahat Al Khoudh: 20 shops and 23 offices on a live plan",
     "lead": "The building plan across its three floors: the commercial ground floor (20 shops of 41.4 to 61.3 m² as printed in the brochure), then 12 offices on the first floor and 11 offices with balconies on the second. "
             "Every cell is a unit with its state (available, reserved, sold, kept for lease) and its type. Below it, segment performance shows the relative demand for each type and view, and the pricing engine's recommendation.",
     "bullets": ["Commercial units carry their classification (use = commercial), so tax and reporting treat them as offices and shops, not apartments.",
                 "Units kept for lease stay out of sale offers and dynamic pricing, and have their own leasing screen.",
                 "Clicking a unit opens its card: price, view, any booking, and its position on the floor plan."],
     "figs": [F("03-inventory-masahat", "Inventory and pricing for Masahat Al Khoudh, building M.", .62)]},
    {"id": "plans", "kicker": "Plans", "title": "The plans of your three brochures, inside the platform",
     "lead": "Pages from the Masahat, Al Shabab and Alaa brochures (location, floor plans, interior and exterior renders, facilities) are uploaded as documents with a content hash. "
             "The ground-floor plan of Masahat carries markers for its twenty shops.",
     "bullets": ["Marker positions in this edition are approximate; staff place them by clicking the plan (Mark unit positions).",
                 "Public plans are visible to the customer in the customer app; structural and electromechanical plans are always internal.",
                 "Files uploaded on a demo environment are temporary until persistent storage is attached; your own sample images come back automatically."],
     "figs": [F("05-plans-gf-markers", "The plans panel: the ground-floor plan with shop markers (green means available), and the first-floor plan below it.", .62), F("04-unit-detail-plan", "The unit card: its position on the floor plan.", .5)]},
    {"id": "leasing", "kicker": "Leasing", "title": "The leasing portfolio: contracts, quarterly instalments, arrears and renewals",
     "lead": "The units Bayan keeps (shops and offices at Masahat Al Khoudh, and the retained units at Al Khuwair Square) appear in the leasing screen with their contracts: tenant, annual rent, instalment frequency (quarterly or monthly), what was paid and what is late, and an alert ninety days before a contract ends.",
     "bullets": [f"Live indicators: units in the leasing portfolio ({FACTS.get('retained', 10)}), occupancy ({FACTS.get('occupancy', 80)}%), annual rent and arrears.",
                 "A new lease is created on screen with a start date, term, rent and instalment frequency, and it generates the schedule of dues and the municipality reference.",
                 "The demo data holds a few illustrative contracts at Masahat Al Khoudh: one with a late instalment and one expiring within weeks, so the renewal alert shows."],
     "figs": [F("13b-leasing", "The leasing screen: indicators, contracts with their instalments, and renewal alerts.", .62), F("13c-leasing-full", "The whole leasing portfolio.", .95)]},
    {"id": "quote", "kicker": "The tenant and buyer journey, 1", "title": "A quote for an office with a non-interest payment plan",
     "lead": "A sales officer issues a numbered quote for an available unit with a payment plan (tied to progress milestones, 60/40, or murabaha through an Islamic bank) and a discount within the officer's authority. A quote does not reserve the unit, and it becomes a booking in one click at the quoted price.",
     "bullets": ["The quote PDF carries your letterhead and logo: Hijri date first, Western digits, an explicit payment table, and a verification code with a QR.",
                 "A fixed validity, and a discount ceiling by role (sales officer 2%, holders of the decide permission up to 15%). Every quote is in the audit log.",
                 f"The quote shown was issued by the platform for unit {QUNIT} to an imaginary customer."],
     "figs": [F("09-sales-quotes", "The quotes tab: the live quote, its plan and the conversion rate.", .45), F(f"{QN}-quote-p1", f"Quote {QN} exactly as the platform issued it, on Bayan Oman letterhead.", .9)]},
    {"id": "contract", "kicker": "The tenant and buyer journey, 2", "title": "Booking, identity check and the signed contract",
     "lead": "A booking creates the instalment schedule at once. The identity check (KYC) records the document and rates the risk. The contract is issued with its text sealed by a hash; the customer signs from the app or in person, and the account is created automatically.",
     "bullets": ["The contract carries the donation clause (a charitable donation in place of a late penalty), marked for approval by a Sharia adviser until Bayan adopts it.",
                 "No handover without a bank release letter, and no escrow release without an approved payment certificate: the rules sit in the core, not in custom.",
                 "Every document (contract, invoice, receipt) is generated from the database on request and never stored as a file, and anyone can verify it publicly by its code."],
     "figs": [F("08-sales-kyc-contracts", "Bookings waiting for identity verification and contract issue.", .5), F(f"{CN}-contract-p1", f"Sale contract {CN}, signed by the customer, on letterhead with a verification code.", .8)]},
    {"id": "invoice", "kicker": "The tenant and buyer journey, 3", "title": "The invoice and the receipt on your letterhead",
     "lead": "Every instalment due produces an invoice (a tax invoice where VAT applies, as it does on commercial sales), and every payment produces a receipt. Delivery to the customer is print, email with an attachment, or a signed WhatsApp link valid for 30 days.",
     "bullets": ["Numbering runs in sequence for each year, amounts use Western digits, and dates show Hijri first and then Gregorian.",
                 "The logo, stamp and authorised signature are uploaded once in Document identity and appear on every document.",
                 "The two samples below were issued by the platform for the first customer at Masahat Al Khoudh (illustrative data)."],
     "figs": [F(f"{IN_}-invoice-p1", f"Invoice {IN_}.", .8), F(f"{RN}-receipt-p1", f"Receipt {RN}.", .8)], "side": True},
    {"id": "client-app", "kicker": "Customer app", "title": "The customer sees their unit, their documents and their place on the plan",
     "lead": "A phone web app the customer signs in to with their own account: My unit (construction progress, expected date, progress photos), Payments (the instalment schedule and online payment), Service (requests after handover), Resale (the secondary market with the developer's approval), and More (contract, invoices, receipts, plans, and voting in the owners' association).",
     "bullets": ["The customer sees the plan of their floor with their own unit marked, the plan of their unit type, and the public renders.",
                 "Changing the password is mandatory on first sign-in, and the customer can sign out of all other devices.",
                 "Personal-data export and privacy requests are available in the app."],
     "figs": [F("40-client-home", "My unit: a shop at Masahat Al Khoudh and construction progress.", 1.5), F("41-client-payments", "Payments: the instalment schedule tied to construction stages.", 1.5), F("43-client-docs-plans", "More: the signed contract, documents and plans.", 1.5)], "side": True},
    {"id": "finance", "kicker": "Collections and finance", "title": "Liquidity radar and default risk, with a donation in place of a penalty",
     "lead": "A monthly forecast of cash flows for each escrow account, with the drivers (payment certificates, scheduled instalments) and the expected peak shortfall. A list of customers at risk of default with their scores, and a rescheduling suggestion before the delay, not after it.",
     "bullets": ["Arrears by age (30, 60 and 90 days) and a list of late instalments by customer and unit; lease arrears sit in the leasing screen.",
                 "Lateness never produces a penalty as revenue. It is recorded as a donation under the contract's clause (1% a month after 15 days, a provisional value to be reviewed with the Sharia adviser), and it can be waived.",
                 "Invoices and VAT (5% on commercial sales), bank reconciliation by importing a statement, and an escrow account per project: no release without an approved certificate, and 10% retention until handover."],
     "figs": [F("15-finance-radar", "Liquidity and default risk: the monthly forecast of the escrow accounts.", .5)],
     "figs2": [F("17-late-charity", "Late-payment donations and rescission.", .5), F("18-bank-reconciliation", "Bank reconciliation: every payment is matched to a statement line, and only the unmatched are listed.", .5)]},
    {"id": "construction", "kicker": "Construction and payment certificates", "title": "Actual progress against sales",
     "lead": "Payment certificates (IPCs) are approved at the percentage the evidence supports (photos and minutes). When a claim exceeds the evidence, the platform proposes approving the supported percentage and estimates the overpayment avoided. The schedule is compared with sales, so a project selling faster than it is built, or the reverse, shows up.",
     "bullets": ["Masahat Al Khoudh stands at 64% progress in the demo data, with about half of its shops sold; Al Shabab Business Centre is at the start, with its building permit 2024/1593 printed in the brochure.",
                 "Alaa Business Avenue is at 36%: the structural stage drives its liquidity peak on the dashboard.",
                 "Each certificate approval needs its own permission (approve_ipc) and leaves an audit line."],
     "figs": [F("11-construction-ipc", "Construction and payment certificates.", .62)]},
    {"id": "handover", "kicker": "Handover and the owners' association", "title": "MQ Residences near handover, and Al Khuwair Square completed with an owners' association",
     "lead": "Handover is scheduled with an appointment and documented with a certificate, a defects list, meter readings and keys, and it cannot complete before the handover instalment is paid. After completion the owners' association takes over the budget and area-weighted voting from the customer app.",
     "bullets": ["MQ Residences (residential, 92% progress in the demo data): handover dates and open defects.",
                 "Al Khuwair Square (completed and handed over): the owners' association, its budget and its votes, with its retained units leased.",
                 "Facilities management and title transfer sit in the neighbouring tabs."],
     "figs": [F("12-handover", "Handover and defects.", .5), F("13-owners-association", "The owners' association: budget and voting.", .5)]},
    {"id": "reports", "kicker": "Reports and analytics", "title": "Ten ready reports and a report builder that needs no SQL",
     "lead": "Ready reports at a click (portfolio, sales performance, lead funnel, quotes, brokers, collections and arrears, liquidity, inventory, construction, handover) with parameters and charts. A report builder over approved datasets with filters and grouping, CSV and PDF export with charts, and saved and scheduled reports by email.",
     "bullets": ["Charts are drawn inside the platform with no external library, and in PDF by the same engine.",
                 "Lender and investor reports have their own permissions; occupancy, annual rent and arrears are indicators in the leasing screen.",
                 "The two reports attached to this package were exported by the platform on Bayan Oman letterhead."],
     "figs": [F("21-report-portfolio", "The portfolio report inside the platform.", .5), F("report-portfolio-p1", "The same report exported as PDF.", .8)], "side": True},
    {"id": "marketing", "kicker": "Marketing", "title": "The marketing board: which project needs action today",
     "lead": "The board classifies each project from live data (sales pace over 30 and 90 days against plan, relative demand on each segment, stalled leads, progress) as launch, weak sales, steady, near complete or complete, with signals, suggested actions, and New campaign and Ad buttons.",
     "bullets": ["A campaign carries a structural offer only (deferral, instalments, fee waivers, bundles). The platform rejects any offer that involves interest.",
                 "Each campaign has a tracking code that measures incoming leads and the cost per lead; sending by email or WhatsApp is logged.",
                 "In this demo data MQ Residences is classed weak sales (near handover with unsold units) and Alaa steady, because its illustrative sales run ahead of plan. The class is computed from live data and moves with it."],
     "figs": [F("24-marketing-board", "The marketing board for the company's six projects, with their classes and signals.", .62), F("25-campaigns", "An illustrative campaign for Alaa's offices with a non-interest offer and a tracking code.", .45)]},
    {"id": "ad-studio", "kicker": "Ad studio", "title": "A ready ad on the real Masahat Al Khoudh render",
     "lead": "Six templates (teaser, launch, special offer, last units, construction progress, ready to occupy) in three sizes. Arabic text is composed in code over the background image you choose, here the Masahat render from the brochure, with your logo and contact details and no people.",
     "bullets": ["The two ads below were produced by the studio inside the platform (launch template and last units, square size).",
                 "An ad is stored as PNG and PDF, tied to a campaign and sent to its audience.",
                 "Marketing alerts are logged daily from market movement (stalled leads, slowing pace, a chance to raise a price)."],
     "style": "--cap:88mm;--cap1:44mm",
     "figs": [F("ad-masahat-launch-square", "Sales launch for Masahat Al Khoudh.", 1.0), F("ad-masahat-last_units-square", "The last units at Masahat Al Khoudh.", 1.0)], "side": True,
     "figs2": [F("26-ad-studio", "The ad studio inside the platform.", .5)]},
    {"id": "governance", "kicker": "Governance and security", "title": "An audit log that cannot be erased, and public verification of every document",
     "lead": "Every action in the platform is a line in an audit log chained by hash, which nobody can edit. Personal data is encrypted in the database, and each entity is isolated by rows at database level, not at application level.",
     "bullets": ["Users and roles: add, change the email, end sessions, reset two-factor.",
                 "Document identity and stamp: legal name, commercial registration, tax number, address, logo, stamp and signature.",
                 "The public /verify page shows the type, number, date and content hash with no personal data."],
     "figs": [F("28-audit-log", "The audit log.", .45), F("31-brand-letterhead", "Document identity and stamp.", .45), F("32-public-verify", "The public verification page for a quote.", .33)]},
]

NEEDS = {
    "kicker": "Getting started",
    "title": "What Bayan needs to go live",
    "lead": "Everything in this guide works today on illustrative data. To make the platform truly Bayan Oman's, we need from the company:",
    "items": [
        ("Real unit schedules, prices and rents", "For each project: unit codes, areas, views, status (for sale or kept), prices, annual rents and instalment frequency, and the approved payment plans."),
        ("Existing lease contracts", "Tenants, the start and end of each contract and the instalments paid, imported in one pass so arrears and renewals show from day one."),
        ("Logo, stamp and signature at print resolution", "Transparent PNG files at high resolution; the current logo is the website's resolution only."),
        ("Images and plans of the other projects", "Amaken, Oman Post Qurum and Al Khoudh, Barka Hall, Masahat 1 and MQ Residences: there is not enough public material for them yet, and only the three brochures are in the platform."),
        ("An SMTP mailbox and a domain", "To send documents, alerts and sign-in links from Bayan's own email. Today email runs in outbox mode."),
        ("WhatsApp Business (optional)", "Today sending uses a wa.me link from the staff member's device; automated sending needs a Business API account and a provider."),
        ("Persistent storage for attachments", "Uploaded plans and documents need persistent storage (a volume or S3) before first real use."),
        ("Approval of the Sharia and legal wording", "The donation clause and the model sale and lease contracts, from the company's Sharia and legal advisers."),
        ("Users and entities", "The staff list and their roles, whether Bayan Investment House becomes a separate entity, and Google sign-in on the company domain if you wish."),
    ],
}

MODELS = {
    "kicker": "Ways to work together",
    "title": "Two ways to work together",
    "lead": "The numbers are left for the meeting. The core difference between the two is who runs it, who owns it, and how updates arrive.",
    "heads": ["", "Subscription on Jadwa's hosted platform", "A private copy on Bayan's infrastructure"],
    "rows": [
        ("Ownership", "A licence to use; the code and operation stay with Jadwa", "A licensed copy deployed on Bayan's servers (Docker and PostgreSQL)"),
        ("Isolation and data", "Each entity isolated by rows (RLS) on a shared database; the data is Bayan's and exported on request", "A fully private database inside Bayan's infrastructure"),
        ("Multiple entities", "One developer per entity of the group on the same subscription", "One developer per entity inside the private copy"),
        ("Updates", "Continuous and automatic with every release", "By maintenance agreement, applied to Bayan's copy"),
        ("Backups", "Daily, from Jadwa, with a restore drill", "The responsibility of Bayan's team, following the operations runbook"),
        ("Support and training", "Included in the subscription", "Included in the implementation and maintenance contract"),
        ("Initial cost", "", ""),
        ("Recurring cost", "", ""),
    ],
    "note": "The empty cells are filled in at the meeting. In both cases: one licence for one developer, the data belongs to the company, and the operations runbook and security guide come with the handover.",
}

LIMITS = {
    "kicker": "Plainly stated",
    "title": "What must be said plainly",
    "items": [
        "Prices, rents, sales ratios, progress, tenants and buyers in this guide are illustrative, built on the areas in your published brochures. Bayan publishes neither prices nor rents, and the MQ Residences units are illustrative throughout.",
        "There are no images yet for Amaken, Oman Post, Barka Hall and Masahat 1. The markers on the shop plan are approximate. The Arabic name Bayan Oman is taken from your website and Instagram account.",
        "A lease is managed as data (tenant, instalments, renewal). The platform does not yet issue a lease contract PDF the way it issues a sale contract; that is added when Bayan adopts its wording.",
        "Email is in outbox mode until SMTP is set, and WhatsApp runs through wa.me links, not the Business API.",
        "Files uploaded by staff on a demo environment are temporary until persistent storage is attached; Bayan's sample images alone return automatically.",
        "The screenshots were taken from a local copy that matches the published version (0.15.0), because the demo password is never written to a file. The verification codes on the sample documents came from that copy, so they do not resolve on the live site.",
        "Not yet proven live: the Omani payment gateway (a simulation today), links with government bodies, and WhatsApp Business.",
    ],
    "close": "Everything else works today on the live link, and Bayan can try it with accounts of its own.",
}

CLOSE = {
    "kicker": "Next step",
    "title": "A live demonstration",
    "lead": "We suggest a one-hour meeting at Bayan's office in Azaiba where we run the platform live on the Masahat Al Khoudh data, leased and sold, collect the needs listed above, and agree the model and the timeline for going live.",
    "bullets": ["Jadwa for Studies and Development, Muscat · jadwa.om", f"The platform: {LIVE}", "In the sign-in developer list: Bayan Oman · sales@mabaneek.com"],
    "fig": F("masahat-render-entrance", "Masahat Al Khoudh, the main entrance, from your brochure.", .5),
}

INFO = {
    "stages": [("1", "Land and permits", ["Land and feasibility studies", "Permits and government bodies", "Escrow account from day one"]),
               ("2", "Sales and construction", ["Inventory, pricing and plans", "Leads and marketing", "Quotes, bookings and contracts", "Construction and payment certificates"]),
               ("3", "Handover and operations", ["Handover, defects and title transfer", "Owners' association and facilities", "Leasing: contracts, instalments, renewals"])],
    "journey": ["Quote with a payment plan", "Booking and instalment schedule", "Identity check", "Contract signed electronically", "Invoice and receipt for every payment", "Customer app: my unit, my documents", "Handover and certificate", "Lease or owners' association"],
    "layers": [("Finance and collections", "Liquidity radar, unit and lease arrears, bank reconciliation, escrow accounts, a donation in place of a penalty"),
               ("Marketing", "A board classing every project, non-interest campaigns, an ad studio on your renders, market alerts"),
               ("Reports and analytics", "10 ready reports, a report builder with no SQL, CSV and PDF with charts, scheduled by email"),
               ("Governance and security", "An audit log that cannot be erased, two-factor, roles and permissions, data isolation in the database, public document verification")],
    "roles": [("General manager", "Today's decisions with their impact"), ("Sales and leasing", "Quotes, bookings, contracts, leases"), ("Finance", "Collection, reconciliation, escrow"),
              ("Engineer", "Certificates and schedule"), ("Broker", "Own leads and commissions"), ("Customer", "A phone app: my unit, my payments")],
    "facts": [(str(N_PROJECTS), "projects: Masahat, Al Shabab, Alaa, MQ, Mabelah, Khuwair"), (str(N_UNITS), "units on your published brochure areas"), (str(N_PLANS), "plans and renders from the three brochures"),
              ("4", "documents on your letterhead: quote, contract, invoice, receipt"), ("RTL", "Arabic first, Hijri first, Western digits"), ("0%", "no interest, and lateness is a donation")],
}

# ───────────────────────────────────────────────────────────────────────────────────────────── css

CSS = r"""
:root{
  --ink:#16231f; --muted:#5b6b66; --line:#d5dfdb; --pale:#f1f6f4; --bg:#ffffff; --card:#ffffff;
  --brand:#124E42; --brand-2:#1A6F5A; --brand-3:#67BDA0; --on-brand:#ffffff; --brand-ink:#124E42; --accent-soft:#dcece6;
  --warn:#8a5a00; --shadow:0 1px 2px rgba(18,78,66,.06),0 10px 28px -14px rgba(18,78,66,.25);
  --f-display:"Bricolage Grotesque","Hanken Grotesk",system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
  --f-body:"Hanken Grotesk",system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --ink:#e6eeea; --muted:#9db0aa; --line:#2b3a36; --pale:#16221f; --bg:#0e1614; --card:#131d1a;
  --brand:#0f3f36; --brand-2:#67BDA0; --brand-3:#67BDA0; --on-brand:#f2faf6; --brand-ink:#8fd6bc; --accent-soft:#1b332d; --warn:#e0b050;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -14px rgba(0,0,0,.6); color-scheme:dark}}
:root[data-theme="dark"]{
  --ink:#e6eeea; --muted:#9db0aa; --line:#2b3a36; --pale:#16221f; --bg:#0e1614; --card:#131d1a;
  --brand:#0f3f36; --brand-2:#67BDA0; --brand-3:#67BDA0; --on-brand:#f2faf6; --brand-ink:#8fd6bc; --accent-soft:#1b332d; --warn:#e0b050;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px -14px rgba(0,0,0,.6); color-scheme:dark}
*{box-sizing:border-box;min-width:0}
html{direction:ltr;overflow-x:hidden;scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:16px;line-height:1.65;direction:ltr;text-align:start;-webkit-font-smoothing:antialiased}
h1,h2,h3{font-family:var(--f-display);text-wrap:balance;line-height:1.18;margin:0}
p,li,figcaption,td,th{overflow-wrap:anywhere}
.wrap{max-width:1040px;margin:0 auto;padding-inline:max(16px,env(safe-area-inset-left,0px)) max(16px,env(safe-area-inset-right,0px));padding-block:0 56px}
a{color:var(--brand-ink)}

/* cover */
.cover{background:var(--brand);color:var(--on-brand);border-block-end:6px solid var(--brand-3)}
.cover .wrap{padding-block:44px 40px}
.cover .logos{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:16px;margin-block-end:34px}
.cover .logos img{height:62px;width:auto;background:#fff;border-radius:10px;padding:6px 8px}
.cover h1{font-size:clamp(30px,5.4vw,52px);font-weight:700;letter-spacing:-.015em}
.cover .sub{font-family:var(--f-display);color:var(--brand-3);font-size:clamp(18px,2.6vw,25px);margin:10px 0 6px}
.cover .tag{max-width:56ch;color:#d8ece5;margin:10px 0 22px}
.cover .date{font-weight:700;color:var(--brand-3);margin:0}
.cover .meta{color:#b9d6cc;font-size:14px;margin:4px 0 0}
.cover .hero{margin-block-start:28px;border-radius:12px;overflow:hidden;max-height:300px}
.cover .hero img{display:block;width:100%;height:300px;object-fit:cover;object-position:50% 78%}

nav.toc{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);border-block-end:1px solid var(--line);z-index:5;overflow-x:auto;white-space:nowrap;padding:9px max(16px,env(safe-area-inset-right,0px)) 9px max(16px,env(safe-area-inset-left,0px))}
nav.toc a{display:inline-block;margin-inline-end:16px;color:var(--muted);text-decoration:none;font-size:13px}
nav.toc a:hover{color:var(--brand-ink)}

section{padding-block:38px 10px;border-block-end:1px solid var(--line)}
.kicker{font-family:var(--f-display);font-size:12.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--brand-2);font-weight:700;margin-block-end:6px}
h2{font-size:clamp(22px,3.2vw,31px);font-weight:700;margin-block-end:12px}
.lead{font-size:17.5px;max-width:74ch;margin:0 0 14px}
ul.pts{padding-inline-start:20px;margin:0 0 16px;max-width:76ch}
ul.pts li{margin:7px 0}
ul.pts li::marker{color:var(--brand-3)}
.figs{display:grid;gap:16px;margin:14px 0 26px}
.figs.side{grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));align-items:start}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px;box-shadow:var(--shadow)}
figure img{display:block;width:100%;height:auto;border-radius:6px;object-fit:cover;object-position:top}
figcaption{color:var(--muted);font-size:13.5px;margin-block-start:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr));gap:14px;margin:12px 0 14px}
.card{background:var(--pale);border-radius:10px;padding:16px 18px;border-block-start:4px solid var(--brand-2)}
.card h3{font-size:17px;margin-block-end:6px}
.card p{margin:0;color:var(--muted);font-size:15px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:12px;margin:10px 0 18px}
.col{background:var(--pale);border-radius:10px;padding:12px 14px;border-block-start:4px solid var(--brand-3)}
.col h3{font-size:15px;margin-block-end:6px}
.col ul{margin:0;padding-inline-start:18px;font-size:14px}
.green{color:var(--brand-ink);font-weight:700;font-size:16.5px;max-width:74ch}
.muted{color:var(--muted);font-size:14.5px}
ol.needs{padding-inline-start:0;list-style:none;counter-reset:n;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));margin:12px 0 22px}
ol.needs li{counter-increment:n;background:var(--pale);border-radius:10px;padding:12px 14px 12px 52px;position:relative}
ol.needs li::before{content:counter(n);position:absolute;inset-inline-start:12px;top:12px;width:28px;height:28px;border-radius:50%;background:var(--brand-2);color:#fff;display:grid;place-items:center;font-family:var(--f-display);font-weight:700;font-size:14px}
ol.needs b{display:block;font-family:var(--f-display);font-size:15.5px}
ol.needs span{color:var(--muted);font-size:14px}
.tablewrap{overflow-x:auto;margin:12px 0}
table{width:100%;border-collapse:collapse;font-size:14.5px;min-width:560px}
th,td{border:1px solid var(--line);padding:9px 12px;text-align:start;vertical-align:top}
thead th{background:var(--brand);color:var(--on-brand);font-family:var(--f-display)}
tbody th{background:var(--pale);width:19%}
.blank{display:block;height:26px;border:1px dashed var(--line);border-radius:6px}
footer{color:var(--muted);font-size:13px;padding:22px 16px;text-align:center}
.ltr{unicode-bidi:isolate}

/* one-page infographic */
.info{padding-block:34px 22px}
.info h3.band{font-size:13.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--brand-2);margin:18px 0 8px}
.i-stages{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.i-stage{background:var(--brand);color:var(--on-brand);border-radius:12px;padding:12px 14px 10px}
.i-stage .n{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--brand-3);color:var(--brand);font-family:var(--f-display);font-weight:700;font-size:13px;margin-inline-end:8px}
.i-stage h4{display:inline;font-family:var(--f-display);font-size:15.5px;margin:0}
.i-stage ul{margin:8px 0 0;padding-inline-start:16px;font-size:12.5px;line-height:1.5}
.i-journey{display:grid;grid-template-columns:repeat(8,1fr);gap:6px;position:relative;margin-block-start:6px}
.i-journey::before{content:"";position:absolute;inset-inline:6%;top:14px;height:2px;background:var(--brand-3);z-index:0}
.i-step{text-align:center;font-size:11.5px;line-height:1.35;position:relative;z-index:1}
.i-step b{display:grid;place-items:center;width:28px;height:28px;margin:0 auto 6px;border-radius:50%;background:var(--brand-2);color:#fff;font-family:var(--f-display);font-size:13px}
.i-step:nth-child(even) b{background:var(--brand);}
.i-layers{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.i-layer{background:var(--pale);border-radius:10px;padding:10px 12px;border-block-start:3px solid var(--brand-3)}
.i-layer h4{font-family:var(--f-display);font-size:13.5px;margin:0 0 4px}
.i-layer p{margin:0;font-size:11.8px;color:var(--muted);line-height:1.45}
.i-roles{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.i-role{border:1px solid var(--line);border-radius:10px;padding:8px 9px;background:var(--card)}
.i-role h4{font-family:var(--f-display);font-size:12.5px;margin:0 0 2px;color:var(--brand-ink)}
.i-role p{margin:0;font-size:11px;color:var(--muted);line-height:1.4}
.i-facts{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.i-fact{background:var(--brand);color:var(--on-brand);border-radius:10px;padding:10px 8px;text-align:center}
.i-fact b{display:block;font-family:var(--f-display);font-size:24px;color:var(--brand-3);line-height:1.1}
.i-fact span{display:block;font-size:10.8px;line-height:1.35;margin-block-start:4px;color:#d8ece5}
.i-foot{background:var(--pale);border-radius:10px;padding:10px 14px;margin-block-start:14px;font-size:12px;line-height:1.55;border-inline-start:4px solid var(--brand-2)}
@media (max-width:760px){.i-stages,.i-layers{grid-template-columns:1fr 1fr}.i-journey{grid-template-columns:repeat(4,1fr);row-gap:14px}.i-journey::before{display:none}.i-roles,.i-facts{grid-template-columns:repeat(3,1fr)}}
@media (max-width:480px){.i-stages,.i-layers{grid-template-columns:1fr}.i-roles,.i-facts{grid-template-columns:1fr 1fr}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}

/* print: A4, one topic per page */
@media print{
  @page{size:A4;margin:13mm 14mm 15mm}
  @page :first{margin:0}
  :root{--ink:#16231f;--muted:#4f605a;--line:#cfdad5;--pale:#f1f6f4;--bg:#fff;--card:#fff;--brand:#124E42;--brand-2:#1A6F5A;--brand-3:#67BDA0;--brand-ink:#124E42;--shadow:none}
  body{font-size:10.6pt;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  nav.toc,footer.screen{display:none}
  .wrap{max-width:none;padding-inline:0}
  .cover{height:297mm;display:flex;flex-direction:column;justify-content:center;break-after:page}
  .cover .wrap{padding-inline:16mm;padding-block:0}
  .cover .hero img{height:84mm}
  section{break-before:page;border:0;padding-block:0 0}
  section.info{padding-block:2mm 0}
  h2{font-size:19pt;margin-block-end:3mm}
  .lead{font-size:11.4pt;margin-block-end:3mm}
  ul.pts{margin-block-end:3mm}
  ul.pts li{margin:1.4mm 0}
  .figs{gap:4mm;margin:3mm 0 4mm;break-inside:avoid}
  figure{padding:2mm;border-radius:2mm;break-inside:avoid}
  figcaption{font-size:8.6pt;margin-block-start:1.5mm}
  .figs.n1 figure img{max-height:var(--cap1,118mm)}
  .figs.n2 figure img{max-height:76mm}
  .figs.n3 figure img{max-height:42mm}
  .figs.side{grid-template-columns:repeat(var(--n,2),minmax(0,1fr))}
  .figs.side figure img{max-height:var(--cap,100mm)}
  .figs.side.keep figure img{max-height:160mm}
  .card,.col,.i-layer,ol.needs li{break-inside:avoid}
  .cards{margin:3mm 0}
  table{min-width:0;font-size:9.4pt}
  .tablewrap{overflow:visible}
  .info h3.band{margin:3.6mm 0 1.8mm;font-size:8.6pt}
  .i-stage ul{font-size:8.6pt}.i-step{font-size:8pt}.i-layer p{font-size:8.2pt}.i-role p{font-size:7.8pt}.i-fact span{font-size:7.6pt}.i-foot{font-size:8.4pt}
}
"""

# ───────────────────────────────────────────────────────────────────────────────────────────── html pieces


def fig(f: dict) -> str:
    style = f' style="aspect-ratio:1/{f["ratio"]}"' if f.get("ratio") else ""
    return f'<figure><img src="{f["src"]}" alt="{esc(f["caption"])}" loading="lazy"{style}><figcaption>{esc(f["caption"])}</figcaption></figure>'


def figs(items: list, side: bool = False) -> str:
    n = len(items)
    cls = "side" if side else f"n{n}"
    return f'<div class="figs {cls}" style="--n:{n}">' + "".join(fig(f) for f in items) + "</div>"


def bullets(items: list) -> str:
    return '<ul class="pts">' + "".join(f"<li>{esc(b)}</li>" for b in items) + "</ul>"


def section(id_: str, kicker: str, title: str, lead: str | None = None, body: str = "", style: str = "") -> str:
    return (f'<section id="{id_}"{(" style=" + chr(34) + style + chr(34)) if style else ""}><div class="kicker">{esc(kicker)}</div><h2>{esc(title)}</h2>'
            + (f'<p class="lead">{esc(lead)}</p>' if lead else "") + body + "</section>")


def infographic() -> str:
    st = "".join(f'<div class="i-stage"><span class="n">{n}</span><h4>{esc(h)}</h4><ul>{"".join(f"<li>{esc(i)}</li>" for i in items)}</ul></div>' for n, h, items in INFO["stages"])
    jy = "".join(f'<div class="i-step"><b>{i}</b>{esc(s)}</div>' for i, s in enumerate(INFO["journey"], 1))
    ly = "".join(f'<div class="i-layer"><h4>{esc(h)}</h4><p>{esc(t)}</p></div>' for h, t in INFO["layers"])
    rl = "".join(f'<div class="i-role"><h4>{esc(h)}</h4><p>{esc(t)}</p></div>' for h, t in INFO["roles"])
    fc = "".join(f'<div class="i-fact"><b>{esc(b)}</b><span>{esc(s)}</span></div>' for b, s in INFO["facts"])
    return (f'<section id="one-page" class="info"><div class="kicker">For a busy manager</div><h2>Mabaneek on one page</h2>'
            '<p class="lead">The development cycle, the journey of a tenant or buyer, the shared layers, who uses it, and your company inside the platform, on a single page.</p>'
            f'<h3 class="band">1 · The development cycle inside the platform</h3><div class="i-stages">{st}</div>'
            f'<h3 class="band">2 · The tenant and buyer journey, from quote to keys, on your letterhead</h3><div class="i-journey">{jy}</div>'
            f'<h3 class="band">3 · Layers that run over the whole cycle</h3><div class="i-layers">{ly}</div>'
            f'<h3 class="band">4 · Who uses it: each sees only what concerns them</h3><div class="i-roles">{rl}</div>'
            f'<h3 class="band">5 · Your company inside the platform today (illustrative data)</h3><div class="i-facts">{fc}</div>'
            '<div class="i-foot"><b>To go live:</b> real unit schedules, prices and rents, existing leases, logo and stamp at print resolution, more project images, an SMTP mailbox, persistent storage. '
            '<b>Two ways to work together:</b> a subscription on Jadwa\'s hosted platform, or a private copy on Bayan\'s infrastructure; the numbers are left for the meeting. '
            f'<b>Live platform:</b> {LIVE}, developer Bayan Oman.</div></section>')


def tour_section(s: dict) -> str:
    body = bullets(s["bullets"]) + figs(s["figs"], s.get("side", False))
    if s.get("figs2"):
        body += figs(s["figs2"], len(s["figs2"]) > 1 and s["id"] != "ad-studio")
    return section(s["id"], s["kicker"], s["title"], s["lead"], body, s.get("style", ""))


def body_html() -> str:
    parts = [infographic(),
             section("about", INTRO["kicker"], INTRO["title"], INTRO["lead"], bullets(INTRO["bullets"])),
             section("why", WHY["kicker"], WHY["title"], WHY["lead"],
                     '<div class="cards">' + "".join(f'<div class="card"><h3>{i}. {esc(h)}</h3><p>{esc(t)}</p></div>' for i, (h, t) in enumerate(WHY["cards"], 1)) + "</div>"
                     + f'<p class="green">{esc(WHY["close"])}</p>'),
             section("overview", OVERVIEW["kicker"], OVERVIEW["title"], OVERVIEW["lead"],
                     '<div class="cols">' + "".join(f'<div class="col"><h3>{esc(h)}</h3><ul>{"".join(f"<li>{esc(i)}</li>" for i in items)}</ul></div>' for h, items in OVERVIEW["cols"]) + "</div>"
                     + figs([OVERVIEW["fig"]]))]
    parts += [tour_section(s) for s in TOUR]
    parts.append(section("needs", NEEDS["kicker"], NEEDS["title"], NEEDS["lead"],
                         '<ol class="needs">' + "".join(f"<li><b>{esc(h)}</b><span>{esc(t)}</span></li>" for h, t in NEEDS["items"]) + "</ol>"))
    rows = "".join("<tr>" + "".join(f'<{"th" if ci == 0 else "td"}>{esc(c) if c else "<span class=blank></span>"}</{"th" if ci == 0 else "td"}>' for ci, c in enumerate(r)) + "</tr>" for r in MODELS["rows"])
    heads = "".join(f"<th>{esc(h)}</th>" for h in MODELS["heads"])
    parts.append(section("models", MODELS["kicker"], MODELS["title"], MODELS["lead"],
                         f'<div class="tablewrap"><table><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table></div><p class="muted">{esc(MODELS["note"])}</p>'))
    parts.append(section("limits", LIMITS["kicker"], LIMITS["title"], None, bullets(LIMITS["items"]) + f'<p class="green">{esc(LIMITS["close"])}</p>'))
    parts.append(section("next", CLOSE["kicker"], CLOSE["title"], CLOSE["lead"], bullets(CLOSE["bullets"]) + figs([CLOSE["fig"]])))
    return "\n".join(parts)


def cover_html() -> str:
    return (f'<header class="cover"><div class="wrap"><div class="logos"><img src="web-assets/mabaniq-logo.png" alt="Mabaneek"><img src="web-assets/bayan-logo.png" alt="Bayan Oman"></div>'
            f'<h1>{esc(TITLE)}</h1><p class="sub">{esc(SUBTITLE)}</p><p class="tag">{esc(TAGLINE)}</p>'
            f'<p class="date">{esc(DATE_LINE)}</p><p class="meta">An illustrated guide with real screenshots of the platform, loaded with Bayan Oman\'s projects, plans and letterhead (version 0.15.0). Prepared by Jadwa for Studies and Development.</p>'
            '<div class="hero"><img src="web-assets/masahat-render-entrance.jpg" alt="Masahat Al Khoudh, the main entrance, from the company brochure"></div></div></header>')


def toc_html() -> str:
    items = [("one-page", "On one page"), ("about", "About"), ("why", "Why now"), ("overview", "Overview")] + [(s["id"], s["kicker"].split(",")[0]) for s in TOUR] + [("needs", "To go live"), ("models", "Two models"), ("limits", "Plainly stated"), ("next", "Next step")]
    seen, out = set(), []
    for i, t in items:
        out.append(f'<a href="#{i}">{esc(t)}</a>')
    return '<nav class="toc">' + "".join(out) + "</nav>"


FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Hanken+Grotesk:wght@400;500;600;700&display=swap">'
FOOT = f'<footer class="screen">Jadwa for Studies and Development · Mabaneek 0.15.0 · {esc(DATE_LINE)} · every figure in this guide is illustrative · platform: <span class="ltr">{LIVE}</span></footer>'
DESC = "An illustrated English guide to the Mabaneek real estate platform, built on Bayan Oman's projects: from leasing and sales to handover."


def full_document() -> str:
    return (f'<!doctype html><html lang="en" dir="ltr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(TITLE)}</title><meta name="description" content="{esc(DESC)}">{FONTS}<style>{CSS}</style></head><body>'
            f'{cover_html()}{toc_html()}<main class="wrap">{body_html()}</main>{FOOT}</body></html>')


def artifact_fragment() -> str:
    # the host wraps this in its own <html><head><body>: title, meta, fonts and style first, then the page content
    return (f'<title>{esc(TITLE)}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n{FONTS}\n'
            '<script>document.documentElement.setAttribute("dir","ltr");document.documentElement.setAttribute("lang","en");</script>\n'
            f'<style>{CSS}</style>\n{cover_html()}\n{toc_html()}\n<main class="wrap">{body_html()}</main>\n{FOOT}\n')


if __name__ == "__main__":
    (PKG / "guide-en-print.html").write_text(full_document(), encoding="utf-8", newline="\n")
    (PKG / "index-en.html").write_text(artifact_fragment(), encoding="utf-8", newline="\n")
    used = sorted({m for m in __import__("re").findall(r'(?:src|href)="(web-assets/[^"]+)"', full_document())})
    missing = [u for u in used if not (PKG / u).exists()]
    print("HTML ok:", len(used), "images;", "MISSING:" if missing else "all present", missing or "")
    print(DATE_LINE)

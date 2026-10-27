# -*- coding: utf-8 -*-
"""English editions of the rest of the Bayan package: first-meeting slides (16:9), the short brief (A4 landscape), the trial guide (A4, two pages)
and the trial-invitation message. Same facts and the same screenshots as the guide (build_guide_en.py); no passwords anywhere.

    python deliverables/promo-bayan/tools/build_extras_en.py   then   node deliverables/promo-bayan/tools/print_extras_en.mjs
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_guide_en as G  # noqa: E402  (facts, NEEDS, MODELS, WHY, date line, helpers)

sys.stdout.reconfigure(encoding="utf-8")
PKG = G.PKG
esc = G.esc
URL = G.LIVE

BASE_CSS = r"""
:root{--ink:#16231f;--muted:#53645e;--line:#cfdad5;--pale:#f1f6f4;--brand:#124E42;--brand-2:#1A6F5A;--brand-3:#67BDA0;
  --f-display:"Bricolage Grotesque","Hanken Grotesk",system-ui,"Segoe UI",Arial,sans-serif;--f-body:"Hanken Grotesk",system-ui,"Segoe UI",Arial,sans-serif}
*{box-sizing:border-box;min-width:0}
html{direction:ltr}
body{margin:0;background:#fff;color:var(--ink);font-family:var(--f-body);-webkit-print-color-adjust:exact;print-color-adjust:exact;direction:ltr}
h1,h2,h3,h4{font-family:var(--f-display);margin:0;text-wrap:balance;line-height:1.15}
img{display:block;max-width:100%}
.frame{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px;box-shadow:0 8px 24px -14px rgba(18,78,66,.35)}
.frame img{width:100%;height:100%;object-fit:cover;object-position:top;border-radius:6px}
"""

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Hanken+Grotesk:wght@400;500;600;700&display=swap">'


def doc(title: str, css: str, body: str, lang_dir: str = 'lang="en" dir="ltr"') -> str:
    return f'<!doctype html><html {lang_dir}><head><meta charset="utf-8"><title>{esc(title)}</title>{FONTS}<style>{BASE_CSS}{css}</style></head><body>{body}</body></html>'


def img(name: str, ext: str = "jpg") -> str:
    return f"web-assets/{name}.{ext}"


# ───────────────────────────────────────────────────────────────────────────────────────────── slides (1280 x 720 px = 13.333 x 7.5 in)

SLIDE_CSS = r"""
@page{size:1280px 720px;margin:0}
.slide{width:1280px;height:720px;position:relative;overflow:hidden;break-after:page;padding:54px 64px 0;background:#fff}
.slide .bar{position:absolute;inset-block:54px;inset-inline-start:0;width:10px;height:96px;background:var(--brand-2);border-radius:0 5px 5px 0}
.slide h2{font-size:46px;font-weight:700;letter-spacing:-.01em}
.slide .sub{font-size:22px;color:var(--muted);margin-block:10px 0;max-width:1000px}
.slide .grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:44px;margin-block-start:34px;align-items:start}
.slide .grid.wide{grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr)}
.slide ul{margin:0;padding-inline-start:26px;font-size:26px;line-height:1.38}
.slide li{margin:0 0 16px}
.slide li::marker{color:var(--brand-3)}
.slide .fig{height:430px}
.slide .fig.sq{height:430px;width:430px;justify-self:center}
.slide .fig.ph{height:440px;width:340px;justify-self:center}
.slide .foot{position:absolute;inset-inline:64px;bottom:20px;display:flex;justify-content:space-between;font-size:13px;color:var(--muted)}
.slide.dark{background:var(--brand);color:#fff;padding:0}
.slide.dark .foot{color:#a9cfc3}
.cv{display:grid;grid-template-columns:1fr 1fr;height:100%}
.cv .l{padding:64px 54px 54px 64px;display:flex;flex-direction:column;justify-content:center;gap:18px}
.cv .logos{display:flex;gap:14px}
.cv .logos img{height:58px;width:auto;background:#fff;border-radius:10px;padding:6px 8px}
.cv h1{font-size:54px;font-weight:700;letter-spacing:-.015em}
.cv .s{font-family:var(--f-display);color:var(--brand-3);font-size:28px}
.cv .d{color:var(--brand-3);font-weight:700;font-size:20px;margin:0}
.cv .m{color:#bcd9cf;font-size:17px;margin:0}
.cv .r{position:relative}
.cv .r img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:60% 70%}
.end{display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:20px;height:100%;padding:60px 120px}
.end h2{font-size:48px;color:#fff}
.end p{font-size:24px;color:var(--brand-3);margin:0;max-width:900px}
.end .u{color:#d8ece5;font-size:22px}
.needs2{display:grid;grid-template-columns:1fr 1fr;gap:12px 40px;margin-block-start:26px}
.needs2 div{display:flex;gap:14px;align-items:center;font-size:23px;font-weight:600;font-family:var(--f-display);padding:8px 0;border-block-end:1px solid var(--line)}
.needs2 b{flex:none;width:34px;height:34px;border-radius:50%;background:var(--brand-2);color:#fff;display:grid;place-items:center;font-size:17px}
table.m{width:100%;border-collapse:collapse;font-size:16px;line-height:1.35;margin-block-start:16px}
table.m th,table.m td{border:1px solid var(--line);padding:6px 12px;text-align:start;vertical-align:top}
table.m thead th{background:var(--brand);color:#fff;font-family:var(--f-display)}
table.m tbody th{background:var(--pale);width:20%}
.blank{display:block;height:18px;border:1px dashed var(--line);border-radius:6px}
"""

SLIDES = [
    ("The problem", "Three problems of a developer that sells and leases at the same time",
     [f"{h}: {t.split('. ')[0].rstrip('.')}." for h, t in G.WHY["cards"]], None),
    ("The platform", "One platform for your whole portfolio: leased, sold and handed over",
     ["1 · Land and permits, 2 · Sales and construction, 3 · Handover, operations and leasing",
      "Across the cycle: liquidity and escrow, reports, audit log, administration and security",
      "Arabic first, right to left, Hijri first, Islamic finance only",
      "One developer per entity of the group, isolated at database level"], ("02-dashboard", .62, "")),
    ("Your company inside the platform", "Your projects, plans and letterhead, as they are",
     ["Masahat Al Khoudh · Al Shabab Business Centre · Alaa Business Avenue · MQ Residences · Mabelah Gateway · Al Khuwair Square",
      "The ground-floor plan with markers for all twenty shops, and the plans of your three brochures",
      "Prices, rents and sales ratios are illustrative until we receive your schedules"], ("05-plans-gf-markers", .62, "")),
    ("Leasing", "The leasing portfolio: contracts, quarterly instalments, arrears, renewals, occupancy",
     ["Units you keep are never sold and never appear in sale offers", "Quarterly or monthly instalments, and a late one shows at once", "A renewal alert ninety days before a contract ends"], ("13b-leasing", .62, "")),
    ("From quote to contract", "The tenant and buyer journey, on your letterhead",
     ["A quote for an office on a non-interest plan, then booking, identity check and a signed contract", "An invoice and a receipt for every instalment, with your logo, stamp, a verification code and a QR",
      "Delivery by print, email or a signed WhatsApp link"], (f"{G.QN}-quote-p1", .95, "")),
    ("The customer app", "My unit · Payments · Service · Documents · My place on the plan",
     ["Construction progress, photos and the expected handover date", "The instalment schedule, online payment and receipts", "The signed contract, the floor plan and the unit marker"], ("40-client-home", 1.3, "ph")),
    ("Collections and finance", "Liquidity radar · arrears · bank reconciliation · escrow accounts",
     ["A monthly forecast of every escrow account, the peak shortfall and its cause", "Customers at risk of default, with rescheduling before the delay", "A late-payment charge is a donation, not revenue, and no plan carries interest"], ("15-finance-radar", .62, "")),
    ("Marketing and reports", "A board that classes every project, non-interest campaigns, an ad studio, ten ready reports",
     ["The project that needs action shows up with its signals and suggested actions", "An ad on the real Masahat render, Arabic text composed in code, no people", "PDF and CSV reports with charts, scheduled by email"], ("ad-masahat-launch-square", 1.0, "sq")),
    ("Governance and security", "What reassures management",
     ["An audit log chained by hash that nobody can edit", "Two-factor sign-in, sessions per device, roles and permissions enforced on the server", "Encrypted personal data, and public verification of every document by QR"], ("28-audit-log", .62, "")),
]


def slides_html() -> str:
    n_total = len(SLIDES) + 4
    out = []
    # cover
    out.append(f'<div class="slide dark"><div class="cv"><div class="l"><div class="logos"><img src="{img("mabaniq-logo","png")}" alt="Mabaneek"><img src="{img("bayan-logo","png")}" alt="Bayan Oman"></div>'
               f'<h1>{esc(G.TITLE)}</h1><div class="s">{esc(G.SUBTITLE)}</div><p class="d">First meeting · {esc(G.DATE_LINE)}</p><p class="m">Jadwa for Studies and Development · version 0.15.0 · illustrative data</p></div>'
               f'<div class="r"><img src="{img("masahat-render-entrance")}" alt="Masahat Al Khoudh"></div></div></div>')
    for i, (title, sub, bullets, fg) in enumerate(SLIDES, 2):
        ul = "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in bullets) + "</ul>"
        if fg:
            name, ratio, kind = fg
            f = f'<div class="frame fig {kind}"><img src="{img(name)}" alt=""></div>'
            grid = f'<div class="grid wide">{ul}{f}</div>'
        else:
            grid = f'<div class="grid" style="grid-template-columns:1fr">{ul}</div>'
        out.append(f'<div class="slide"><div class="bar"></div><h2>{esc(title)}</h2><div class="sub">{esc(sub)}</div>{grid}'
                   f'<div class="foot"><span>Mabaneek × Bayan Oman · illustrative data</span><span>{i} / {n_total}</span></div></div>')
    k = len(SLIDES) + 2
    needs = "".join(f"<div><b>{j}</b>{esc(h)}</div>" for j, (h, _t) in enumerate(G.NEEDS["items"], 1))
    out.append(f'<div class="slide"><div class="bar"></div><h2>What it takes to go live</h2><div class="sub">From Bayan Oman</div><div class="needs2">{needs}</div>'
               f'<div class="foot"><span>Mabaneek × Bayan Oman · illustrative data</span><span>{k} / {n_total}</span></div></div>')
    rows = "".join("<tr>" + "".join(f'<{"th" if ci == 0 else "td"}>{esc(c) if c else "<span class=blank></span>"}</{"th" if ci == 0 else "td"}>' for ci, c in enumerate(r)) + "</tr>" for r in G.MODELS["rows"])
    heads = "".join(f"<th>{esc(h)}</th>" for h in G.MODELS["heads"])
    out.append(f'<div class="slide"><div class="bar"></div><h2>Two ways to work together</h2><div class="sub">No numbers on this slide; they are left for the meeting</div>'
               f'<table class="m"><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table>'
               f'<div class="foot"><span>Mabaneek × Bayan Oman · illustrative data</span><span>{k + 1} / {n_total}</span></div></div>')
    out.append(f'<div class="slide dark"><div class="end"><h2>We suggest a live demonstration on the Masahat Al Khoudh data, leased and sold</h2>'
               f'<p>One hour at your office in Azaiba · we collect the needs · we agree the model and the timeline</p><div class="u">{esc(URL)} · developer: Bayan Oman · sales@mabaneek.com<br>Jadwa for Studies and Development, Muscat · jadwa.om</div></div></div>')
    return doc("Mabaneek for Bayan Oman, first meeting slides", SLIDE_CSS, "".join(out))


# ───────────────────────────────────────────────────────────────────────────────────────────── brief (A4 landscape)

BRIEF_CSS = r"""
@page{size:297mm 210mm;margin:0}
.pg{width:297mm;height:210mm;position:relative;overflow:hidden;break-after:page;padding:14mm 16mm 12mm;background:#fff}
.pg .bar{position:absolute;inset-inline-start:0;top:14mm;width:3mm;height:20mm;background:var(--brand-2);border-radius:0 1.5mm 1.5mm 0}
.pg h2{font-size:25pt;font-weight:700}
.pg .sub{font-size:12.5pt;color:var(--muted);margin-block-start:2mm}
.pg .g{display:grid;grid-template-columns:minmax(0,.84fr) minmax(0,1.16fr);gap:10mm;margin-block-start:10mm;align-items:start}
.pg ul{margin:0;padding-inline-start:6mm;font-size:13pt;line-height:1.42}
.pg li{margin:0 0 4.2mm}
.pg li::marker{color:var(--brand-3)}
.pg .fr{height:132mm}
.pg .fr.ph{width:68mm;height:132mm;justify-self:center}
.pg .ft{position:absolute;inset-inline:16mm;bottom:7mm;display:flex;justify-content:space-between;font-size:8pt;color:var(--muted)}
.pg.dark{background:var(--brand);color:#fff;padding:0}
.pg.dark .ft{color:#a9cfc3}
.bc{display:grid;grid-template-columns:1fr 1fr;height:100%}
.bc .l{padding:20mm 12mm 16mm 18mm;display:flex;flex-direction:column;justify-content:center;gap:5mm}
.bc .logos{display:flex;gap:4mm}.bc .logos img{height:15mm;width:auto;background:#fff;border-radius:2.5mm;padding:1.5mm 2mm}
.bc h1{font-size:30pt}.bc .s{font-family:var(--f-display);color:var(--brand-3);font-size:15pt}
.bc .d{color:var(--brand-3);font-weight:700;font-size:11pt;margin:0}.bc .m{color:#bcd9cf;font-size:9.5pt;margin:0}
.bc .r{position:relative}.bc .r img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:60% 70%}
.cl{padding:30mm 24mm;display:flex;flex-direction:column;gap:8mm;justify-content:center;height:100%}
.cl h2{color:var(--brand-3);font-size:24pt}
.cl p{font-size:14pt;line-height:1.5;margin:0;color:#e4f2ec}
.cl .u{color:#fff;font-weight:600}
"""

BRIEF = [
    ("Dashboard", "What needs your decision today", "02-dashboard", "",
     ["Four indicators: sales, collections, projected liquidity gap, available inventory", "A decision box ranked by priority and financial impact, with the source of each decision", "The project cycle and your six projects in the side bar", "An assistant that answers from your live data"]),
    ("Inventory and plans", "Masahat Al Khoudh on a live plan", "03-inventory-masahat", "",
     ["43 units (20 shops and 23 offices) with their states on the building plan; units kept for lease are marked", "Segment performance: relative demand per type and view, and the pricing recommendation", "Your real plans: the ground floor with shop markers, and the three brochures", "The customer sees their own floor and their own unit marker only"]),
    ("Leasing", "The leasing portfolio: contracts, instalments, renewals", "13b-leasing", "",
     ["Kept units with their contracts: tenant, annual rent, instalment frequency", "Quarterly or monthly instalments, and a late one shows at once", "A renewal alert ninety days before a contract ends", "Occupancy, annual rent and arrears as live indicators"]),
    ("Quotes and contracts", "From a quote to a signed contract", f"{G.QN}-quote-p1", "",
     ["A numbered quote on a non-interest plan (milestones, 60/40, murabaha), with a validity and a discount ceiling per role", "It becomes a booking in one click at the quoted price", "Identity check, then a contract sealed by a hash and signed by the customer from their phone", "Quote, contract, invoice and receipt as PDF on your letterhead, with a verification code and a QR"]),
    ("Customer app", "My unit · Payments · Service · Documents", "40-client-home", "ph",
     ["Construction progress, photos and the expected handover date", "The instalment schedule, online payment and receipts", "The signed contract, documents and the unit plan", "After handover: service requests, and resale with the developer's approval"]),
    ("Collections and finance", "Liquidity radar and default risk", "15-finance-radar", "",
     ["A monthly forecast of each escrow account, the peak shortfall and its cause", "Customers at risk of default, with a rescheduling suggestion before the delay", "Arrears by age, bank reconciliation, invoices and VAT", "Lateness is a donation under the contract, not revenue: Islamic finance only"]),
    ("Construction and handover", "Actual progress against sales", "11-construction-ipc", "",
     ["Payment certificates are approved at the percentage the evidence supports (photos and minutes)", "Progress is compared with sales per project (Masahat Al Khoudh at 64% in the demo data)", "Handover with an appointment, a certificate and a defects list, and never before the handover instalment", "Owners' association: a budget and votes weighted by unit area"]),
    ("Marketing and ads", "Which project needs action today", "24-marketing-board", "",
     ["A board that classes each project from its live data: launch, weak sales, steady, near complete, complete", "Campaigns with a structural offer only (the platform rejects any offer with interest) and a tracking code that measures cost per lead", "An ad studio: 6 templates in 3 sizes on your real renders, with no people", "Daily marketing alerts from market movement"]),
    ("Reports", "Ten ready reports and a builder that needs no SQL", "21-report-portfolio", "",
     ["Portfolio, sales, funnel, quotes, brokers, collections, liquidity, inventory, construction, handover", "A report builder over approved datasets with filters, grouping and charts", "CSV and PDF export on your letterhead, saved and scheduled by email", "Lender and investor reports with their own permissions"]),
    ("Security and governance", "What reassures management", "28-audit-log", "",
     ["Every action is a line in an audit log chained by hash, which nobody can edit", "Two-factor sign-in, sessions per device, remote sign-out, graded lockout", "Roles and permissions on the server; encrypted personal data; each developer isolated in the database", "Public verification of any document by its code, with no personal data shown"]),
]


def brief_html() -> str:
    n = len(BRIEF) + 2
    out = [f'<div class="pg dark"><div class="bc"><div class="l"><div class="logos"><img src="{img("mabaniq-logo","png")}" alt="Mabaneek"><img src="{img("bayan-logo","png")}" alt="Bayan Oman"></div>'
           f'<h1>{esc(G.TITLE)}</h1><div class="s">The short brief: the features in points, on screenshots of the platform</div><p class="d">{esc(G.DATE_LINE)}</p>'
           f'<p class="m">Jadwa for Studies and Development · version 0.15.0 · illustrative data</p></div><div class="r"><img src="{img("masahat-render-entrance")}" alt="Masahat Al Khoudh"></div></div></div>']
    for i, (sec, title, name, kind, pts) in enumerate(BRIEF, 2):
        ul = "<ul>" + "".join(f"<li>{esc(p)}</li>" for p in pts) + "</ul>"
        out.append(f'<div class="pg"><div class="bar"></div><h2>{esc(sec)}</h2><div class="sub">{esc(title)}</div>'
                   f'<div class="g">{ul}<div class="frame fr {kind}"><img src="{img(name)}" alt="{esc(sec)}"></div></div>'
                   f'<div class="ft"><span>Mabaneek × Bayan Oman · rents, prices and sales ratios are illustrative</span><span>{i} / {n}</span></div></div>')
    out.append('<div class="pg dark"><div class="cl"><h2>What it takes to go live</h2>'
               '<p>Unit schedules, prices and rents · existing lease contracts · logo, stamp and signature at print resolution · images of the other projects · an SMTP mailbox and a domain · persistent storage for attachments · approval of the Sharia and legal wording</p>'
               '<p>Two ways to work together: a subscription on Jadwa\'s hosted platform, or a private copy on Bayan\'s infrastructure. We suggest a live demonstration on the Masahat Al Khoudh data.</p>'
               f'<p class="u">{esc(URL)} · developer: Bayan Oman · sales@mabaneek.com · Jadwa for Studies and Development, Muscat · jadwa.om</p></div></div>')
    return doc("Mabaneek for Bayan Oman, short brief", BRIEF_CSS, "".join(out))


# ───────────────────────────────────────────────────────────────────────────────────────────── trial guide (A4, two pages)

TRIAL_CSS = r"""
@page{size:A4;margin:13mm 14mm 14mm}
body{font-size:10pt;line-height:1.5}
h1{font-size:19pt;margin-block-end:1.5mm}
.meta{color:var(--muted);font-size:9pt;margin:0 0 3mm}
h2{font-size:12.5pt;color:var(--brand-2);margin:5mm 0 2mm;break-after:avoid}
h2.pb{break-before:page;margin-block-start:0}
p{margin:0 0 2.5mm}
ul{margin:0 0 2mm;padding-inline-start:5mm}li{margin:1mm 0}li::marker{color:var(--brand-3)}
table{width:100%;border-collapse:collapse;font-size:9.2pt;margin:1mm 0 2mm}
th,td{border:1px solid var(--line);padding:1.8mm 2.5mm;text-align:start;vertical-align:top}
thead th{background:var(--brand);color:#fff;font-family:var(--f-display)}
tbody tr:nth-child(odd){background:var(--pale)}
td.u{font-weight:700;color:var(--brand-2);white-space:nowrap}
.steps{list-style:none;padding:0;margin:0}
.steps li{display:grid;grid-template-columns:6mm auto 1fr;gap:2.5mm;align-items:start;margin:1.6mm 0}
.steps .n{width:5.5mm;height:5.5mm;border-radius:50%;background:var(--brand-2);color:#fff;font-size:8pt;font-weight:700;display:grid;place-items:center}
.steps .w{background:var(--brand);color:#fff;border-radius:1mm;padding:.4mm 1.8mm;font-size:8pt;font-weight:700;white-space:nowrap}
.close{color:var(--brand);font-weight:700;margin-block-start:3mm}
.ft{position:fixed;bottom:-9mm;inset-inline:0;font-size:7.5pt;color:var(--muted);display:flex;justify-content:space-between}
"""

ACCOUNTS = [
    ("bayan-ceo", "General manager", "Everything: decisions, inventory, leasing, marketing, finance, reports, users and security"),
    ("bayan-sales", "Sales and leasing", "Inventory, leads, quotes, bookings and contracts, brokers, the leasing portfolio"),
    ("bayan-finance", "Finance and collections", "Liquidity and default risk, invoices and escrow, bank reconciliation, certificates, reports"),
    ("bayan-engineer", "Project engineer", "Construction and certificates, permits, handover and defects"),
    ("bayan-client", "Customer", "The customer app on a phone: my unit, payments, service, documents (opens by itself after sign-in)"),
]
STEPS = [
    ("bayan-ceo", "Dashboard: the decision box ranked by priority and financial impact; click any decision to see why."),
    ("bayan-ceo", "Inventory and pricing, choose Masahat Al Khoudh, then the Plans button: the ground floor with shop markers and your brochure plans."),
    ("bayan-sales", "Handover and property, then Leasing: the contracts of the kept units, their quarterly instalments, the late one and the renewal alert. Try + Lease on the vacant unit."),
    ("bayan-sales", "Contracts and brokers, then Quotes, then + Quote: issue a murabaha quote for an available office, open the PDF on your letterhead and turn it into a booking."),
    ("bayan-client", "The customer app: My unit (progress), Payments (the instalment schedule), More (the contract, the plans and the unit's place on them)."),
    ("bayan-finance", "Liquidity and default risk, then Invoices and escrow: the liquidity radar, arrears, and late-payment donations in place of a penalty."),
    ("bayan-ceo", "Project marketing: the board that classes your projects, then the Ad studio to design an ad on the Masahat render."),
    ("bayan-ceo", "Reports and analytics: open the Portfolio dashboard and export it as PDF or CSV."),
]
NOTES = [
    "All prices, rents, sales ratios, tenants, customers and payments in this environment are illustrative, built on the areas in your published brochures. Please do not enter real customer or tenant data.",
    "The developer list on the sign-in screen shows other developers that have nothing to do with you. Your data is isolated from theirs at database level, which also lets Bayan Investment House have a separate entity if you wish.",
    "Email runs in outbox mode (no real email is sent yet), WhatsApp opens a wa.me link from your device, and files you upload are temporary and may be cleared when the platform is updated.",
    "The platform is Islamic finance only: no plan carries interest, and lateness is a donation under the contract, not revenue.",
    "After your first sign-in you choose a password of your own that nobody else knows, and you can switch on two-factor sign-in from Administration and security, then Security.",
]


def trial_html() -> str:
    acc = "".join(f'<tr><td class="u">{esc(u)}</td><td>{esc(r)}</td><td>{esc(w)}</td></tr>' for u, r, w in ACCOUNTS)
    stp = "".join(f'<li><span class="n">{i}</span><span class="w">{esc(u)}</span><span>{esc(t)}</span></li>' for i, (u, t) in enumerate(STEPS, 1))
    notes = "".join(f"<li>{esc(n)}</li>" for n in NOTES)
    body = (f'<h1>Trial guide for Mabaneek: Bayan Oman</h1><p class="meta">{esc(G.DATE_LINE)} · a trial environment prepared for you</p>'
            '<p>This is a trial environment prepared in your company\'s name: your projects (Masahat Al Khoudh, Al Shabab Business Centre, Alaa Business Avenue, MQ Residences, Mabelah Gateway, Al Khuwair Square), '
            'the plans of your brochures and your letterhead, so you can try how the leasing portfolio, sales, collections, handover and marketing are run.</p>'
            f'<h2>1. How to sign in</h2><ul><li>Open {esc(URL)}, then Sign in (or {esc(URL)}/login directly).</li><li>From the Developer list choose Bayan Oman.</li>'
            '<li>Type a username from the table below and the temporary password (it reaches you in a separate message, never in this guide).</li>'
            '<li>You will be asked for a new password of your own (10 characters or more, with letters and digits) before you continue.</li></ul>'
            f'<table><thead><tr><th>Username</th><th>Role</th><th>What it sees</th></tr></thead><tbody>{acc}</tbody></table>'
            f'<h2>2. A suggested 15-minute tour</h2><ul class="steps">{stp}</ul>'
            f'<h2 class="pb">3. Know this before you try</h2><ul>{notes}</ul>'
            '<p class="close">Your feedback is what we need most: what you liked, what is missing and what you want different. Send it to us at any time.</p>'
            '<p class="meta">Jadwa for Studies and Development · Mabaneek · illustrative trial data</p>')
    return doc("Mabaneek trial guide for Bayan Oman", TRIAL_CSS, body)


INVITE = f"""# Trial invitation: Bayan Oman

> For Bayan Oman's management (founder and CEO), by WhatsApp or email. **The temporary password is sent in a separate message and is not in this file.**

Peace be upon you and God's mercy and blessings,

Dear colleagues at Bayan Oman, we have prepared a trial environment of Mabaneek (the real estate development platform from Jadwa) in your company's name: your projects (Masahat Al Khoudh, Al Shabab Business Centre, Alaa Business Avenue, MQ Residences, Mabelah Gateway and Al Khuwair Square), the plans of your brochures and your letterhead, so you can try your whole commercial portfolio for yourselves: leasing (contracts, quarterly instalments and renewals) and sales from the quote to handover.

- Link: {URL}
- On the sign-in screen choose the developer Bayan Oman
- Username for management: bayan-ceo (general manager: sees everything). Other accounts for your team are in the attached trial guide (sales and leasing, finance, engineer, and a customer account to try the customer app)
- I will send the temporary password in a separate message, and you will choose a password of your own at first sign-in

Attached: the trial guide (two pages: signing in, a 15-minute tour and notes), the short brief with screenshots of the platform, and the one-page infographic.

Please note that prices, rents, sales ratios, tenants and customers in this environment are illustrative, built on the areas in your published brochures, so please do not enter real customer or tenant data. We look forward to your feedback, and then to arranging a live demonstration and a discussion of how we might work together. If you would like a separate entity for Bayan Investment House on the same platform, that is available.

With thanks and best wishes
"""

if __name__ == "__main__":
    (PKG / "slides-en-print.html").write_text(slides_html(), encoding="utf-8", newline="\n")
    (PKG / "brief-en-print.html").write_text(brief_html(), encoding="utf-8", newline="\n")
    (PKG / "trial-en-print.html").write_text(trial_html(), encoding="utf-8", newline="\n")
    (PKG / "trial-invitation-message-en.md").write_text(INVITE, encoding="utf-8", newline="\n")
    import re
    used = set()
    for f in ("slides-en-print.html", "brief-en-print.html", "trial-en-print.html"):
        used |= set(re.findall(r'src="(web-assets/[^"]+)"', (PKG / f).read_text(encoding="utf-8")))
    missing = [u for u in used if not (PKG / u).exists()]
    print("built 3 html + invitation;", len(used), "images;", "MISSING" if missing else "all present", missing or "")

# 🛰️ JobRadar — your own internship radar

A self-hosted clone of what Emploive does: it watches **2,100+ companies'** live
career boards, and the moment a matching internship / new-grad role is posted it
**pushes it to your phone** and adds it to your personal dashboard — all running
free on GitHub, 24/7, even when your laptop is closed.

It works by talking directly to the applicant-tracking systems (Greenhouse, Lever,
Ashby, SmartRecruiters, Workable, Workday) that companies actually post through —
the same trick the paid services use. The company list is harvested automatically
from public, community-maintained internship datasets, so it grows on its own.

---

## What you get

- **Phone alerts** within ~15 minutes of a posting going live (via the free *ntfy* app).
- **A live dashboard** (GitHub Pages) — newest postings first, filter by role or company.
- **2,100+ companies** tracked out of the box, refreshed weekly.
- Filters tuned for your four families: **Software, Data/ML/AI, Quant/Finance, Hardware/EE**, intern **and** new-grad.

---

## One-time setup (~10 minutes, all free)

### 1. Put this on GitHub
Create a new repository (private is fine), then upload these files — or from your
computer:
```bash
cd jobradar
git init && git add . && git commit -m "JobRadar"
git branch -M main
git remote add origin https://github.com/<you>/jobradar.git
git push -u origin main
```

### 2. Set up phone notifications (ntfy)
1. Install **ntfy** — free, no account: [iOS](https://apps.apple.com/app/ntfy/id1625396347) · [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. In the app tap **+ / Subscribe to topic** and enter a **long, random** topic
   name, e.g. `jobradar-sid-7f3k9q2x`. Anyone who knows this string can see your
   alerts, so treat it like a password.
3. Tell JobRadar the same topic. **Recommended:** in your repo go to
   **Settings → Secrets and variables → Actions → New repository secret**,
   name it `NTFY_TOPIC`, value = your topic string. (Or just edit `ntfy_topic`
   in `config.yaml`, but a secret keeps it out of your code.)

### 3. Turn on the scanner
- Go to the **Actions** tab → enable workflows if prompted.
- Open **“JobRadar scan”** → **Run workflow** to do the first run now.
  - The **first run is silent by design** — it learns everything that's already
    posted and sends you one “JobRadar is armed” ping. After that you only get
    pinged for genuinely **new** postings. (No 300-notification blast on day one.)
- From then on it runs itself every ~15 minutes.

### 4. Turn on the dashboard (optional but nice)
- **Settings → Pages → Source: “Deploy from a branch” → branch `main`, folder `/docs`.**
- Your dashboard goes live at `https://<you>.github.io/jobradar/`.
- Open it on your phone and “Add to Home Screen” for an app-like icon.

Done. 🎉

---

## Make it yours

Everything is controlled by **`config.yaml`** — edit, commit, push, and the next
run uses it. Common tweaks:

- **Only certain locations:** set `locations: ["United States", "Remote"]`.
- **Just internships (drop new-grad):** trim `role_keywords` down to intern terms.
- **Fewer false positives:** add words to `exclude_keywords`.
- **Faster/slower:** change the `cron` in `.github/workflows/scan.yml`
  (`*/15 * * * *` = every 15 min; GitHub's practical floor is ~5 min and runs
  are often queued a few minutes late).

Add more companies any time: `python discover.py` re-harvests the public datasets
into `companies.json`. To hand-add one, append `{"ats":"greenhouse","token":"stripe","company":"Stripe"}`.

---

## Honest limitations

- **Cadence:** free GitHub cron is ~15 min, not the “under 5 minutes” a paid
  always-on server advertises. Still faster than 99% of applicants.
- **Coverage:** ~2,100 companies to start (vs Emploive's ~3,000), growing weekly.
  Companies on custom career sites with no standard ATS aren't covered.
- **LinkedIn/Indeed** aren't included — they block automated access. Use LinkedIn's
  native saved-search job alerts alongside this.
- Some Workday boards are picky; failures are skipped silently and don't stop the run.

---

## How it fits together

```
discover.py ─► companies.json      (2,100+ boards: ATS + token, refreshed weekly)
config.yaml  ─► your role/field/location filters + ntfy topic
scan.py      ─► every 15 min: fetch all boards → filter → diff vs seen.json
                 ├─► ntfy push to your phone (new postings only)
                 └─► docs/data/jobs.json  ─►  docs/index.html dashboard
GitHub Actions ── runs it on schedule, commits seen.json + jobs.json back
```

Data sources for the company registry:
[SimplifyJobs/Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
and [vanshb03/New-Grad-2025](https://github.com/vanshb03/New-Grad-2025).

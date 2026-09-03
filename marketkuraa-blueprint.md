# MarketKuraa.com — Product Blueprint

**Owner:** Sambhav Acharya (product/plan) · **Build:** Prabesh Khatiwada (Django)
**Positioning input:** Global-focused investing platforms are generic; local/regional investor communities barely exist. MarketKuraa = local-first investor community with a global lens.

---

## 1. Product Vision

MarketKuraa is where investors, traders, founders, and analysts actually talk shop — not another finance news aggregator, not a brokerage. It's the "Hacker News meets investor Discord" for Nepal-and-beyond, where a post about a NEPSE microcap and a post about a US tech earnings call can both live, get real discussion, and connect people to each other.

The wedge that gets it off the ground: **there is no serious English/Nepali investor discussion space for this region.** Telegram groups are noisy and unsearchable. Reddit is US-centric. Facebook groups have zero structure. MarketKuraa wins by being the first place that treats local market discussion as a first-class citizen, with the bones of a real platform (profiles, reputation, structure) underneath.

## 2. Target Users — Sequenced, Not Simultaneous

You said "all equally" — here's why that's the wrong starting line, and what I recommend instead.

**Primary wedge (MVP): Retail investors & finance enthusiasts learning the ropes.**
Why this one first: it's the largest addressable group, the lowest trust-bar to acquire (they want to learn and discuss, not close deals), and it's the group most likely to already be in your eKuraa/Bisup audience. They generate volume — posts, comments, questions — which is exactly what a forum needs on day one to not look empty.

**Secondary (V1): Traders & analysts.**
Once there's content volume, this group shows up because that's where the audience is. They bring credibility (verified badge candidates) and higher-quality content, which pulls in more beginners. Classic two-sided flywheel — beginners bring numbers, analysts bring quality, each attracts the other once there's critical mass.

**Later (V2+): Founders & entrepreneurs.**
This group wants deal flow, visibility, and fundraising conversations — a fundamentally different product surface (think structured company/founder profiles, not discussion threads). Bolting this on too early dilutes the community's core purpose. Bring them in once you have investor eyeballs worth reaching.

Think of it like building a mall: you don't open all wings on day one, you open the food court (discussion) because that's what gets people walking in daily, then add the anchor stores (deal flow) once there's foot traffic.

## 3. Core Problem Being Solved

- No structured, searchable, quality investor discussion space for Nepal/South Asia + global markets in one place.
- Existing local groups (Facebook/Telegram/Viber) have zero reputation system — a 3-day-old troll account and a 10-year investor look identical.
- No place where "who is this person" (credibility) is visible before you weight their opinion.

## 4. Community Model

- **Public forum**, no login-wall on reading (critical for SEO — see Section 17).
- **Sub-communities/categories** by topic: NEPSE, Global Markets, Startups/Founders, Personal Finance, Trading Strategy, Market News.
- **Profiles with reputation** — post/comment history, karma-style scoring, verified badge layer.
- **Self-reported positions/portfolios** as posts, not a live brokerage tracker (per the legal note above).

## 5. Complete Feature Set

### Core (all phases)
- User accounts, profiles, follow system
- Threaded discussions with categories/tags
- Upvote/reaction system, comment threading
- Search (posts, users, tags)
- Notifications

### Investor-specific
- **Position/Thesis posts** — structured post type: "I hold X, here's why" with entry point, thesis, risk notes (self-reported, timestamped, not live-synced)
- **Watchlists** — personal, save companies/tickers of interest (static list, no live price feed at MVP)
- **Company/Ticker pages** — auto-generated stub page per company mentioned, aggregates all discussion about it (huge SEO value, see below)
- **Verified badges** — analysts, professionals, fund managers apply with credentials, admin-reviewed
- **AMA / structured Q&A threads** — for verified members

### Trust & Moderation
- Report/flag system
- Reputation-gated posting (new accounts rate-limited, can't post in high-trust sections immediately)
- Admin moderation queue

## 6. Unique Differentiators (Not Just Reddit-With-Stocks)

1. **Company pages as SEO magnets** — every time someone posts about "Nabil Bank" or "NEPSE IPO," that content rolls up into an auto-built company page. Over time you build the most complete public archive of discussion on local companies — that's defensible and hard to copy, because it's community-generated, not licensed data.
2. **Thesis posts with accountability, without live tracking risk** — instead of a real-time P&L leaderboard (legally messy), a thesis is timestamped and becomes citable later ("called this in March, here's the thread") — reputation built on being right over time, without you touching real trade execution or live advisory territory.
3. **Bilingual-native from day one** (English + Nepali) — most finance content assumes English-only; supporting Nepali natively is a moat competitors copying Reddit/TradingView templates won't bother with.
4. **Verified-but-still-public** — badges add credibility without gating content behind them; you're not building a paywalled analyst platform, you're building a public square with visible credibility markers.

## 7. Roadmap: MVP → V1 → V2 → Future

### MVP (weeks, per your timeline)
- Auth (email + Google login)
- Categories/forum structure, post + comment + threading
- Upvotes, basic profile pages
- Search (Postgres full-text is enough, don't reach for Elasticsearch yet)
- Basic moderation (report + admin delete/lock)
- Mobile-responsive clean UI (per your non-negotiable: no design bloat)

**Explicitly cut from MVP:** live price data, watchlists, verification badges, company pages, AMAs. These are V1. Trying to ship all of this "in weeks" is how projects stall — ship the forum, get people posting, THEN layer on investor-specific structure once you see what people actually discuss.

### V1 (next 1–2 months post-launch)
- Position/thesis structured post type
- Static watchlists (no live data)
- Verified badge system + application flow
- Company/ticker auto-pages (start simple: aggregate posts mentioning a tag)
- Notifications, better search/filter

### V2 (3–6 months out)
- Live market data integration (NEPSE feed if available via API/scraping partnership, global via a data provider)
- AMA/structured Q&A events
- Founder/startup profiles + discovery (the third persona, now that you have an audience)
- Reputation-based perks (badges unlock features)

### Future
- Premium tier (pro tools, deeper data, ad-free)
- API for third parties
- Events/webinars tied to verified members
- Possibly a jobs/deal-flow board once trust is established

## 8. Key User Flows

**Onboarding:** Land on a company/topic page from search (not logged in) → read discussion → prompted to sign up to comment/post → quick signup (email or Google) → land on personalized-ish feed (categories they can follow).

**Posting a thesis:** New post → select "Position/Thesis" type → structured fields (asset, entry context, thesis, risk) → tag category → publish → shows on profile + relevant company page.

**Verification:** User applies from profile → submits credentials (LinkedIn, license, professional info) → admin review queue → approved → badge appears platform-wide.

## 9. Pages/Screens (MVP)

- Home/feed (categories + trending)
- Category page
- Post detail + comments
- Company/ticker page (V1, but design placeholder in MVP)
- User profile
- Search results
- Auth (login/signup)
- Admin moderation dashboard
- Settings

## 10. Architecture

Given Prabesh builds in Django — standard, boring, reliable stack. Don't overengineer this:

- **Backend:** Django + Django REST Framework (for any API needs — mobile later, or JS-heavy frontend interactions)
- **Frontend:** Django templates + HTMX for interactivity (avoids a full separate SPA build — faster for a 1-person build timeline) OR a lightweight React frontend if Prabesh is more comfortable there. For "weeks" timeline, HTMX + Django templates is the faster path — no separate API/frontend sync overhead.
- **Database:** PostgreSQL (full-text search built in, avoids needing Elasticsearch at this scale)
- **Hosting:** Given you run Bisup — self-host on your own VPS infrastructure. You already have the ops muscle for this.
- **Caching:** Redis for session/cache once traffic justifies it — not needed day one.
- **Search:** Postgres `tsvector` full-text search for MVP. Don't add Elasticsearch until you have a real scale problem.

## 11. Core Database Models (simplified)

```
User: id, username, email, bio, avatar, karma_score, is_verified, verified_type, created_at

Category: id, name, slug, description

Post: id, user_id(FK), category_id(FK), type(discussion/thesis), title, body,
      asset_tag(nullable), thesis_entry(nullable), thesis_risk(nullable),
      upvotes, created_at

Comment: id, post_id(FK), user_id(FK), parent_comment_id(nullable, for threading),
         body, upvotes, created_at

Tag/Company: id, name, slug, description(auto or admin-curated)
PostTag: post_id(FK), tag_id(FK)  -- many-to-many

Watchlist: id, user_id(FK), tag_id(FK), created_at  -- V1

VerificationRequest: id, user_id(FK), credentials_text, status, reviewed_by, created_at

Report: id, post_id/comment_id(FK), reporter_id(FK), reason, status
```

## 12. API Endpoints (core, DRF-style)

```
POST   /api/auth/signup
POST   /api/auth/login
GET    /api/posts/               (filter by category, tag)
POST   /api/posts/
GET    /api/posts/{id}/
POST   /api/posts/{id}/comments/
POST   /api/posts/{id}/upvote
GET    /api/users/{username}/
POST   /api/verification/apply
GET    /api/tags/{slug}/posts     (company page data, V1)
POST   /api/reports/
```

## 13. Admin/Moderation

- Moderation queue: reported posts/comments, sorted by report count
- Manual verification review dashboard
- Basic rate-limiting for new accounts (e.g., max 3 posts/day until account is 7 days old — kills spam without hurting real users)
- Shadow-ban capability for repeat abuse (don't notify the user, just hide their content from others — standard forum anti-spam pattern)

## 14. Security

- Standard Django security defaults (CSRF, XSS protection via template escaping — don't disable these for "convenience")
- Rate limiting on auth endpoints (prevent credential stuffing)
- Input sanitization on post/comment body (prevent stored XSS via markdown/rich text rendering)
- No storage of sensitive financial credentials — you're a discussion platform, not a brokerage; never build a feature that asks users for actual account/broker credentials
- HTTPS everywhere (you control this via Bisup infra)

## 15. Monetization — Recommendation

Since undecided, here's the sequencing that fits a community platform:

1. **Ads later, not first.** Ads before you have real traffic just makes the platform feel low-quality and slows growth. Skip for MVP/V1.
2. **Premium subscription is your real long-term model** — once V2 live data lands, gate advanced tools (deeper company pages, alerts, ad-free, priority verification review) behind a paid tier. This is the standard "freemium community → pro tools" playbook (same shape as Reddit Premium, Stack Overflow for Teams, etc.) — the free tier is the acquisition engine, paid tier monetizes power users.
3. **Marketplace/fee model is a stretch goal, not core** — you already run eKuraa for digital assets; don't duplicate that model here unless a clear "sell your research/analysis" use case emerges organically from the community.

Don't build billing infrastructure until V1 traction proves people actually want to pay for something specific.

## 16. SEO Strategy

This is a major built-in advantage if you execute it right:

- **Company/ticker pages are your SEO engine.** Every NEPSE company, every commonly-discussed global stock, becomes a page that ranks for "[Company] discussion Nepal" type queries where there's currently zero competition.
- **No login-wall on read access** — Google can't index what it can't see. Public read, gated write.
- **Clean URLs:** `/company/nabil-bank`, `/category/nepse`, `/post/{slug}` — not ID-based garbage URLs.
- **Structured data markup** (schema.org Discussion/QAPage) on post pages once you have volume.
- This compounds — you don't need a "content team," the community generates the SEO content for you, which is the actual unfair advantage over a platform that has to pay writers.

## 17. Scalability

Don't design for scale you don't have. Postgres + a single well-specced VPS (which you already run via Bisup) comfortably handles tens of thousands of users. Revisit architecture (read replicas, caching layer, CDN for static/media) only when you have real traffic data showing strain — not preemptively.

## 18. Development Roadmap & Tasks (MVP, weeks-based)

**Week 1:** Django project setup, auth, base models (User, Category, Post, Comment), admin panel
**Week 2:** Post creation/listing, comment threading, upvote system, category pages
**Week 3:** Search (Postgres full-text), user profiles, basic moderation (report/delete), responsive UI pass
**Week 4:** Testing, seed content (you + team post first threads to avoid empty-platform problem), soft launch to eKuraa/Bisup audience

Realistic for one Django developer (Prabesh) working solo — this is already a tight timeline, don't add V1 features into this window.

## 19. Risks & Legal Considerations

- **Investment advice liability:** Position/thesis posts must be clearly framed as opinion/discussion, not advice. Add a standing disclaimer site-wide. Avoid any feature that resembles a "buy/sell signal" or ranked "best picks" — that's the line where you start looking like an unregistered advisor.
- **Market manipulation risk:** A public post hyping a low-liquidity NEPSE stock could be construed as pump-and-dump behavior if unmoderated. Moderation policy should explicitly ban coordinated hype posts, and flag/monitor sudden bursts of posts about the same illiquid stock.
- **Verification claims:** If a "verified analyst" gives bad advice publicly, is that a platform liability? Keep verification framed as "identity/credential confirmed," not "advice endorsed by MarketKuraa" — disclaim clearly.
- **Data/scraping for company pages:** If you ever pull real company data (financials, prices) from third parties, check their ToS before scraping — don't build a feature on data you don't have rights to redistribute.
- **Empty-platform risk (not legal, but real):** Forums die if they launch empty. Seed content aggressively in week 4 — you and your 3-person team should post 20-30 real threads before public launch so it doesn't look like a ghost town.

---

## 20. Development Phases (Prabesh — solo build)

Single track, since Prabesh is the only developer. Phased to match the MVP → V1 → V2 → Future roadmap in Section 7, broken into buildable chunks.

### Phase 1 — MVP (Weeks 1–4)
- **Wk1:** Django project setup, auth (email + Google), core models (User, Category, Post, Comment), admin panel
- **Wk2:** Post create/list, comment threading, upvotes, category pages
- **Wk3:** Postgres full-text search, user profile pages, report/moderation actions, responsive UI pass
- **Wk4:** Bug fixes, basic load testing, deploy to Bisup VPS, launch-ready

**Exit criteria:** Forum is live, functional, moderatable, and deployed. No investor-specific features yet — that's the point.

### Phase 2 — V1 (Months 2–3)
- Position/thesis structured post type (self-reported, not live-synced — see Section 19 on legal risk)
- Static watchlists (no live price data)
- Verification application flow + admin review dashboard
- Auto-generated company/ticker pages (aggregate posts by tag — this is the SEO engine, see Section 16)
- Notifications, filters, improved search

**Exit criteria:** Company pages and verification are live — this is the point the platform stops looking like a generic forum and starts looking like MarketKuraa.

### Phase 3 — V2 (Months 4–6)
- Live market data integration (NEPSE feed + global data provider — vet data licensing/ToS before building this, per Section 19)
- AMA/structured Q&A event tooling
- Founder/startup profiles + discovery
- Reputation-based feature unlocks

**Exit criteria:** Platform has live data and a third persona (founders) onboarded without diluting the core investor community.

### Phase 4 — Future (6+ months, scope TBD)
Don't spec this now — decide based on what Phase 2/3 usage data actually shows. Candidates: premium tier + billing, public API, events/webinars, deal-flow board.

---

**Bottom line:** Ship the forum first, prove people want to talk here, then layer the investor-specific structure on top. The "weeks" timeline works IF you cut scope to Section 7's MVP list and don't let it creep.

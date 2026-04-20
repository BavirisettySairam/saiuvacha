# Sai Uvacha — Progress Tracker

> Based on the 5-week development plan. Updated as work is completed.
> **Status: Week 1–3 complete. Week 4 partially done. Week 5 partially done. 155 discourses / 1,074 chunks live in Qdrant.**

---

## Week 1 — Foundation

- [x] Set up Git repo and Railway project
- [x] Django project scaffold (apps, config, manage.py)
- [x] Settings split into `base.py` / `dev.py` / `prod.py`
- [x] `.env.example` with all required variables documented
- [x] `Dockerfile` with multi-layer caching and collectstatic at build time
- [x] `railway.toml` — builder, startCommand, preDeployCommand, healthcheck
- [x] Health check endpoint (`/healthz/`) handled at ASGI level
- [x] `bootstrap` management command — idempotent superuser + Site setup on deploy
- [x] Batch convert 200 `.docx` discourse files to `.md` (155 converted, in `discourses/<year>/`)
- [x] Discourse metadata parser (title, date, event, place, year from filename)
- [x] Chunking script with semantic section detection
- [x] Non-citeable discourse tracking (`config/non_citeable_discourses.json`)
- [x] Sanskrit/Telugu glossary for search expansion (`config/glossary.json`)
- [x] Embed all discourse chunks with OpenAI `text-embedding-3-small`
- [x] Upload embeddings to Qdrant Cloud (1,074 chunks, `sai_discourses` collection)
- [ ] Test retrieval in terminal — ask 20 spiritual questions, verify chunk quality

**Milestone: Ask a question in terminal, get back the right discourse chunks**
Status: ✅ 155 discourses ingested. Retrieval verification pending.

---

## Week 2 — RAG Pipeline + Guardrails

- [x] `apps/rag/retriever.py` — embed query, expand with glossary, search Qdrant
- [x] `apps/rag/composer.py` — build system prompt + context block, handle citeable flag
- [x] `apps/rag/llm.py` — provider-agnostic streaming (Claude + OpenAI switchable via `LLM_PROVIDER`)
- [x] `apps/rag/cache.py` — Redis semantic cache (SHA-256 key, 7-day TTL, silent fallback)
- [x] `apps/rag/pipeline.py` — full 3-gate pipeline (streaming + non-streaming)
- [x] System prompt written (49-line Swami voice definition with anti-jailbreak)
- [x] `apps/guardrails/prefilter.py` — Gate 1, 13 block categories, zero API cost
- [x] `apps/guardrails/confidence.py` — Gate 2, thresholds 0.32 / 0.48
- [x] `apps/guardrails/validator.py` — Gate 3, opinion phrases, AI identity leakage, length
- [x] `apps/guardrails/templates.py` — pre-written Swami-voice fallback responses (12 categories, randomised)
- [ ] Test 50+ questions across categories (spiritual, values, devotion, edge cases)
- [ ] Test 30+ attack queries (prompt injection, manipulation, off-topic)

**Milestone: Full RAG pipeline works in terminal with all 3 gates**
Status: ⏳ Code complete. Needs discourse data + end-to-end testing.

---

## Week 3 — Django App + Auth

- [x] `CustomUser` model (email auth, language preference, query counter)
- [x] `Conversation` model (user, title, language, timestamps)
- [x] `Message` model (encrypted content via `EncryptedTextField`, flagged field)
- [x] django-allauth — Google OAuth + email/password login
- [x] Email verification (disabled in dev, mandatory in prod)
- [x] django-cryptography — Fernet encryption on Message content field
- [x] Chat view — main chat page with conversation context
- [x] Landing view — home page with sample questions
- [x] SSE streaming endpoint (`POST /chat/ask/`) — token-by-token streaming
- [x] Free trial middleware — 5 session-tracked queries, 403 with login URL after limit
- [x] Login / signup pages (allauth + Tailwind)
- [x] Rate limiting on SSE endpoint (django-ratelimit, 20 req/min per IP)
- [x] Language selector saved to user profile (`/accounts/profile/` — 5 languages)
- [x] Custom allauth templates (login, signup, password reset, email confirm, logout)
- [x] ChatGPT-style UI (dark sidebar, markdown rendering via marked.js + DOMPurify)
- [x] Typing indicator (3-dot bounce) + streaming cursor animation
- [x] SSE `SynchronousOnlyOperation` fix (sync_to_async wrapping ORM in async generator)
- [ ] Language selector dropdown in chat header (profile page exists, header shortcut pending)
- [ ] django-ninja API endpoints

**Milestone: Working chat in browser with login, streaming, language select**
Status: ✅ Complete. Header language shortcut + ninja endpoints pending.

---

## Week 4 — Polish + Features

- [x] Chat history sidebar (list of past conversations, active highlighted)
- [x] New conversation button
- [x] Conversation title auto-generated from first user query
- [x] Flag response button (per message, staff review queue)
- [x] Redis semantic cache wired into pipeline
- [x] Landing page (hero, "How it works", sample questions, CTA)
- [x] Mobile-responsive layout (sidebar collapses, hamburger menu)
- [ ] Celery tasks for async LLM calls (broker configured, no tasks implemented yet)
- [ ] Privacy Policy page (`/privacy`)
- [ ] Terms of Service page (`/terms`)
- [ ] About page (`/about`)
- [ ] Dark mode support
- [ ] `docker-compose.yml` for local Postgres + Redis dev environment

**Milestone: Feature-complete app that looks professional**
Status: ⏳ Core features done. Legal pages, dark mode, docker-compose pending.

---

## Week 5 — Security + Deploy

- [x] Deploy to Railway (app live and healthy)
- [x] django-axes — brute-force protection (5 attempts → 1-hour lockout)
- [x] django-ratelimit — 20 req/min per IP on SSE endpoint
- [x] CSP headers (Tailwind CDN + HTMX CDN whitelisted)
- [x] HSTS (preload enabled, 1-year max-age)
- [x] Secure cookies (HttpOnly, Secure, SameSite=Lax)
- [x] X-Frame-Options: DENY
- [x] Content-Type nosniff
- [x] Input length limit (500 chars max query)
- [x] WhiteNoise for static file serving (no separate server needed)
- [x] Sentry DSN configured (error monitoring)
- [x] `SECURE_PROXY_SSL_HEADER` trusting Railway's reverse proxy
- [ ] `python manage.py check --deploy` — full security checklist pass
- [ ] Point domain to Railway (saiuvacha.org via Cloudflare)
- [ ] Configure Cloudflare — DNS, proxying, WAF rules
- [ ] Verify SSL certificate end-to-end
- [ ] Google OAuth redirect URIs updated to production domain
- [ ] GitHub Actions CI/CD pipeline (test → lint → deploy)
- [ ] Load testing (simulate 50 concurrent users)
- [ ] Admin dashboard analytics (usage charts, language breakdown)
- [ ] Beta testing with 5–10 devotees
- [ ] Iterate based on beta feedback

**Milestone: Live at saiuvacha.org, beta testing with real devotees**
Status: ⏳ App deployed and healthy. Domain, CI/CD, and beta testing pending.

---

## Discourse Processing Pipeline

- [x] Organise 155 `.md` files into `discourses/<year>/` folders
- [x] Verify filename format: `"Title by Bhagavan..." - DD Mon YYYY - Event - Place.md`
- [x] Review and populate `config/non_citeable_discourses.json`
- [x] Run `python scripts/ingest.py --setup-collection` (collection created in Qdrant)
- [x] Run `python scripts/ingest.py --all --resume` — 1,074 chunks uploaded to `sai_discourses`
- [ ] Spot-check 20 spiritual questions against retrieved chunks in terminal
- [ ] Verify non-citeable discourses suppress date/event/place correctly
- [ ] Add remaining discourses when available (`--resume` flag handles idempotent re-runs)

---

## DevOps

- [x] GitHub repository (private)
- [x] Railway project connected to GitHub
- [x] Railway Postgres database provisioned
- [x] All production environment variables set in Railway dashboard
- [x] `railway.toml` with preDeployCommand (migrate + bootstrap)
- [x] `Dockerfile` (multi-stage, collectstatic at build, dynamic `$PORT`)
- [x] `.gitattributes` (LF line endings for shell scripts)
- [x] `.gitignore`
- [x] Superuser creation automated via `bootstrap` command
- [ ] `docker-compose.yml` for local full-stack dev (Postgres + Redis + Celery)
- [ ] GitHub Actions workflow (lint → test → security scan → deploy)
- [ ] `RAILWAY_TOKEN` added to GitHub repo secrets
- [ ] Cloudflare account + domain DNS configured
- [ ] Upstash Redis production URL verified

---

## Pages

| Page | Route | Status |
|---|---|---|
| Landing | `/` | ✅ Done |
| Chat | `/chat/` | ✅ Done |
| Login | `/accounts/login/` | ✅ Done (allauth) |
| Signup | `/accounts/signup/` | ✅ Done (allauth) |
| Admin (Django) | `/admin/` | ✅ Done |
| Staff Dashboard | `/dashboard/` | ✅ Done (basic) |
| About | `/about` | ❌ Not started |
| Privacy Policy | `/privacy` | ❌ Not started |
| Terms of Service | `/terms` | ❌ Not started |
| Contact / Feedback | `/contact` | ❌ Not started |
| Profile / Settings | `/accounts/profile/` | ✅ Done (language pref, password change, sign out) |
| Discourse Manager | `/admin/discourses/` | ❌ Post-launch |

---

## Pre-Launch Testing Checklist

### Response Quality
- [ ] 20 common spiritual questions — accurate, Swami-like responses
- [ ] 10 questions in Telugu — natural Telugu voice
- [ ] 10 questions in Hindi — natural Hindi voice
- [ ] 5 edge-case questions — honest "I haven't found a specific teaching"
- [ ] 10 off-topic questions — warm redirection (not hard block)
- [ ] 10 prompt injection attempts — all blocked by Gate 1
- [ ] 5 subtle manipulation attempts — Swami stays in character
- [ ] Every response includes a discourse citation (for citeable discourses)
- [ ] No fabricated quotes or teachings

### Functionality
- [ ] Free trial: exactly 5 queries, then login prompt
- [ ] Google login works on production domain
- [ ] Email login + verification email received
- [ ] Chat history saves and loads correctly
- [ ] Language selector persists across sessions
- [ ] Streaming renders token-by-token in browser
- [ ] Flag button works, flagged messages appear in `/dashboard/`
- [ ] New chat button creates a fresh conversation
- [ ] Mobile responsive on iPhone + Android

### Security
- [ ] `python manage.py check --deploy` — zero errors
- [ ] No `DEBUG` info leakage in production responses
- [ ] No API keys in any committed file
- [ ] Rate limiting blocks > 20 requests/minute
- [ ] HTTPS enforced on all pages
- [ ] XSS attempt in chat input is sanitised

---

## Post-Launch Roadmap

### Phase 2 (Month 2–3)
- [ ] Daily Sai Quote on landing page (365 curated quotes, personalised per user)
- [ ] Share response as image card (WhatsApp sharing)
- [ ] Email digest — weekly spiritual message to subscribers
- [ ] PWA support (install to home screen)
- [ ] Admin dashboard improvements (trend charts, language breakdown, API cost)

### Phase 3 (Month 4–6)
- [ ] Voice input (speech-to-text → query)
- [ ] Voice output (text-to-speech for Swami's response)
- [ ] More languages: Kannada, Malayalam, Marathi
- [ ] Discourse browser (read full discourses on the site)
- [ ] Community shared favourite quotes

### Phase 4 (Month 6–12)
- [ ] Native mobile app (React Native or Flutter)
- [ ] Bhajan recommendation based on conversation topic
- [ ] Guided meditation suggestions
- [ ] Integration with Sai organisation websites
- [ ] Annual usage report for the foundation

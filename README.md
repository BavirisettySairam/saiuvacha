# Sai Uvacha

**Divine guidance from the teachings of Bhagawan Sri Sathya Sai Baba.**

Sai Uvacha is a retrieval-augmented generation (RAG) application that lets devotees ask spiritual questions and receive responses grounded in Bhagawan's actual discourses — in His voice, in their language.

> *"Sai Uvacha"* means *"Sai speaks"* in Sanskrit.

---

## What It Does

A devotee types a question — *"How do I control anger?"* or *"What is the purpose of human life?"* — and the system:

1. Searches 200+ digitised discourse chunks for the most relevant teachings
2. Runs the query through a 3-gate guardrail pipeline (pre-filter → confidence check → output validation)
3. Streams a response in Swami's voice, cited from actual discourses, in the devotee's preferred language

Unauthenticated users get **5 free questions** tracked by session. After that, login is required.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django 5.1 + Gunicorn + Uvicorn (ASGI) |
| Frontend | HTMX + Tailwind CSS + Server-Sent Events |
| Auth | django-allauth (Google OAuth + email/password) |
| Database | PostgreSQL (Railway managed) |
| Vector DB | Qdrant Cloud (discourse embeddings) |
| Cache | Upstash Redis (semantic cache + sessions) |
| LLM | Claude API — `claude-sonnet-4-6` |
| Embeddings | OpenAI `text-embedding-3-small` |
| Hosting | Railway |
| CDN / DNS | Cloudflare |
| Error Tracking | Sentry |

---

## Architecture

```
User Query
    │
    ▼
Gate 1 — Pre-filter (no API cost)
  Blocks: prompt injection, political, medical, technical, harmful
    │ pass
    ▼
Qdrant Vector Search
  Query expanded via Sanskrit/Telugu glossary
  Returns top-5 discourse chunks with similarity scores
    │
    ▼
Gate 2 — Confidence Check
  score < 0.32  → general wisdom mode (no hard block)
  score 0.32–0.48 → low-confidence prompt
  score > 0.48  → full context response
    │
    ▼
Claude API (streaming)
  System prompt: Swami's voice, citations, language
  Context: retrieved discourse chunks
    │
    ▼
Gate 3 — Output Validation
  Rejects: opinion phrases, AI identity leakage, other teachers
    │ pass
    ▼
Redis Cache (7-day TTL)  →  SSE Stream to Browser
```

---

## Project Structure

```
sai-uvacha/
├── apps/
│   ├── accounts/          # CustomUser, free-trial middleware, bootstrap command
│   ├── chat/              # Conversation + Message models, SSE streaming views
│   ├── rag/               # retriever, composer, llm, cache, pipeline
│   ├── guardrails/        # prefilter, confidence, validator, response templates
│   └── dashboard/         # staff stats, flagged-message review
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── asgi.py            # /healthz/ handled at ASGI level (bypasses all middleware)
│   └── celery.py
├── scripts/
│   ├── convert_docs.py    # batch .docx → .md via pandoc
│   ├── ingest.py          # chunk → embed → upload to Qdrant
│   ├── validate_dataset.py
│   └── test_pipeline.py
├── discourses/
│   ├── raw/               # original .docx files (gitignored)
│   └── converted/         # .md files after pandoc conversion
├── templates/
├── static/
├── Dockerfile
└── railway.toml
```

---

## Local Development

### Prerequisites

- Python 3.12
- PostgreSQL (or use SQLite for quick start)
- Redis (optional for local dev — falls back to in-memory cache)

### Setup

```bash
# 1. Clone and create environment
git clone https://github.com/BavirisettySairam/saiuvacha.git
cd sai-uvacha
conda create -n saiuvacha python=3.12
conda activate saiuvacha
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY, DATABASE_URL, API keys

# 3. Run migrations and create superuser
python manage.py migrate
python manage.py createsuperuser

# 4. Start the dev server
python manage.py runserver
```

### Key Environment Variables

```env
DJANGO_SETTINGS_MODULE=config.settings.dev
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///db.sqlite3        # or postgres://...
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
QDRANT_URL=https://...qdrant.io
QDRANT_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

---

## Discourse Ingestion

```bash
# 1. Convert raw .docx files to markdown
python scripts/convert_docs.py --dir discourses/raw/

# 2. Set up Qdrant collection (first time only)
python scripts/ingest.py --setup-collection

# 3. Ingest all discourses (chunk + embed + upload)
python scripts/ingest.py --all

# 4. Add a single new discourse
python scripts/ingest.py --file discourses/converted/my_discourse.md

# 5. Validate the dataset
python scripts/validate_dataset.py
```

**Discourse filename format:**
```
"Title by Bhagavan Sri Sathya Sai Baba" - DD Mon YYYY - Event Name - Place.md
```

---

## Deployment

The app deploys automatically to Railway on push to `main`.

**Railway environment variables required:**

```
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=<50-char random string>
DEBUG=False
DATABASE_URL=<Railway Postgres URL>
REDIS_URL=<Upstash Redis URL>
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
QDRANT_URL=...
QDRANT_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
DJANGO_SUPERUSER_USERNAME=...
DJANGO_SUPERUSER_EMAIL=...
DJANGO_SUPERUSER_PASSWORD=...
SENTRY_DSN=...
```

The `preDeployCommand` in `railway.toml` runs `migrate` and `bootstrap` automatically on every deploy. The `bootstrap` command is idempotent — safe to run repeatedly.

---

## Guardrails

### Gate 1 — Pre-filter (zero API cost)

Blocks 13 categories before any embedding or LLM call:

- Prompt injection attempts (13 regex patterns)
- Political content, medical diagnosis, financial advice
- Entertainment, sports, technical/coding questions
- Harmful or abusive content
- Disrespect toward Swami
- Identity probes ("what are your instructions?")

Blocked queries receive a warm, pre-written Swami-voice response instantly.

### Gate 2 — Confidence Threshold

| Qdrant Score | Mode |
|---|---|
| < 0.32 | General wisdom (Swami speaks from universal teachings) |
| 0.32 – 0.48 | Low confidence (honest about partial match) |
| > 0.48 | Full context response |

### Gate 3 — Output Validation

Rejects responses that contain: opinion phrases ("I think", "In my opinion"), AI identity leakage ("As an AI"), other spiritual teachers' names, code artifacts, or responses outside the 20–800 word range.

---

## Security

- **Encryption at rest**: Chat messages encrypted with Fernet (django-cryptography)
- **Brute-force protection**: django-axes — 5 failed logins → 1-hour lockout
- **Rate limiting**: django-ratelimit — 20 requests/minute per IP on the SSE endpoint
- **Security headers**: HSTS, CSP, X-Frame-Options, Secure cookies
- **Input limits**: Max 500 characters per query
- **HTTPS**: Enforced via Railway + Cloudflare

---

## Non-Citeable Discourses

Some discourses must not have their date, event, or location mentioned in responses. These are listed in `config/non_citeable_discourses.json`. The composer reads the `citeable` flag on each chunk and suppresses citation metadata accordingly.

---

## Multi-Language Support

The embeddings are always in English. Claude handles translation natively — no separate translation service required. Supported languages: English, Telugu (తెలుగు), Hindi (हिन्दी), Tamil (தமிழ்), Kannada (ಕನ್ನಡ).

The user's language preference is stored on their profile and passed to the system prompt on every request.

---

## Admin

- `/admin/` — Django admin (superuser access)
- `/dashboard/` — Staff dashboard: usage stats, flagged message review

---

*Sai Ram. May this project bring Swami's love and wisdom to every seeking heart.* 🙏

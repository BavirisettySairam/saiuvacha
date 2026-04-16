# Sai Uvacha — Project Context for Claude

## What This Is
A spiritual guidance web app (RAG) powered by 200+ discourses of Bhagawan Sri Sathya Sai Baba.
Devotees ask questions → system retrieves relevant discourse chunks → Claude responds in Swami's voice.
Solo project by Bavirisetty Sairam. Built with Claude Code.

## Tech Stack
- **Framework:** Django 5.1 + django-ninja + HTMX + Tailwind CSS
- **Auth:** django-allauth (Google OAuth + email/password)
- **DB:** PostgreSQL (Railway prod) / SQLite (local dev)
- **Vector DB:** Qdrant Cloud (discourse embeddings)
- **Cache:** Upstash Redis (semantic cache + sessions + Celery broker)
- **LLM:** Claude API — `claude-sonnet-4-6`
- **Embeddings:** OpenAI `text-embedding-3-small`
- **Hosting:** Railway + Cloudflare CDN
- **Security:** django-axes, django-ratelimit, django-cryptography, Sentry

## Project Structure (target)
```
sai-uvacha/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── asgi.py
│   └── celery.py
├── apps/
│   ├── accounts/      # CustomUser, allauth, free trial middleware
│   ├── chat/          # Conversation, Message (encrypted), SSE streaming
│   ├── rag/           # embedder, retriever, composer, llm, cache
│   ├── guardrails/    # prefilter, confidence, validator, templates
│   └── dashboard/     # admin stats, flagged response review
├── scripts/
│   ├── convert_docs.sh   # batch .doc → .md via pandoc
│   ├── ingest.py         # chunk + embed + upload to Qdrant
│   ├── test_rag.py
│   └── test_guardrails.py
├── discourses/
│   ├── raw/           # original .doc files (gitignored)
│   └── converted/     # .md files after pandoc conversion
├── static/
├── templates/
├── tests/
├── .env               # never commit
├── Dockerfile
├── docker-compose.yml
└── railway.toml
```

## Key Design Rules
- **5 free prompts** (session cookie) → login required after that
- **3-gate query pipeline:** pre-filter (Gate 1, no API cost) → confidence threshold 0.75 (Gate 2) → output validation (Gate 3)
- **Non-citeable discourses** tracked in `config/non_citeable_discourses.json` — never mention date/event/place for these
- **Multi-language:** embeddings always in English; Claude handles translation in response
- **Chat messages encrypted at rest** via django-cryptography
- **System prompt is the soul** — never fabricate quotes, always cite from retrieved context

## Settings Split
`config/settings.py` is the default scaffold — must be split into `base.py / dev.py / prod.py` before building apps.
Use `django-environ` to load `.env`. `DJANGO_SETTINGS_MODULE=config.settings.dev` for local.

## Discourse Files
- Raw `.doc` files → `discourses/raw/` (gitignored)
- Converted `.md` files → `discourses/converted/`
- Filename format: `"Title by Bhagavan Sri Sathya Sai Baba" - DD Mon YYYY - Event Name - Place`

## 5-Week Plan (current: Week 1)
1. **Week 1** — Settings split, discourse pipeline (convert → clean → chunk → embed → Qdrant)
2. **Week 2** — RAG pipeline (retriever, composer, llm) + 3-gate guardrails + system prompt
3. **Week 3** — Django apps: accounts, chat, SSE streaming, allauth, free trial middleware
4. **Week 4** — Polish: history sidebar, Redis cache, Celery, landing page, mobile responsive
5. **Week 5** — Security hardening, Railway deploy, Cloudflare, beta testing

## External Services Needed
- Qdrant Cloud — vector DB
- Upstash — Redis
- Anthropic Console — Claude API key
- OpenAI Platform — embeddings key
- Google Cloud Console — OAuth credentials
- Railway — hosting
- Cloudflare — DNS/CDN/SSL

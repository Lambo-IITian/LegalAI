# ⚖️ LegalAI Resolver

<div align="center">

**AI-powered pre-litigation dispute resolution. Describe your dispute in plain English — get applicable law, analytics, and a signed settlement. No lawyers. No court.**

[![Live Demo](https://img.shields.io/badge/🌐_Live_Demo-legalai--resolver.azurewebsites.net-06B6D4?style=for-the-badge)](https://legalai-resolver.azurewebsites.net)
[![Demo Video](https://img.shields.io/badge/▶_Demo_Video-Watch_on_YouTube-FF0000?style=for-the-badge)](https://youtu.be/vsI2z3ZWoBQ)
[![Microsoft AI UNLOCKED](https://img.shields.io/badge/🏆_Microsoft_AI_UNLOCKED-Top_55_/_1000+_Teams-0078D4?style=for-the-badge)](https://youtu.be/vsI2z3ZWoBQ)

</div>

---

## 🔥 The Problem

> **1.5 billion** civil disputes go unresolved every year. Not because people don't have a case — but because:

| Reality | Numbers |
|---|---|
| Minimum lawyer fees | Rs. 50,000+ |
| Average court case duration | 4–6 years |
| Disputes that reach resolution | Only 11% |
| Existing apps | Just give you forms — not resolution |

---

## ✨ What LegalAI Resolver Does

Submit a dispute in plain English → **5 AI agents analyze it** → respondent is invited → **3 rounds of AI mediation** → both parties accept → **signed settlement agreement delivered by email**.

Zero lawyers. Zero court filings. Minutes, not months.

```
You describe dispute
        │
        ▼
┌───────────────────────────────────────────────────┐
│  1. Intake Agent      → Classifies, extracts facts │
│  2. Legal Agent       → Maps statutes + precedents │
│  3. Analytics Agent   → Win probability + ZOPA     │
│  4. Document Agent    → Generates legal PDFs       │
│  5. Negotiation Agent → AI-mediated settlement     │
└───────────────────────────────────────────────────┘
        │
        ▼
Signed Settlement Agreement → Both parties by email
```

---

## 🚀 Live Demo

**Try it now:** [https://legalai-resolver.azurewebsites.net](https://legalai-resolver.azurewebsites.net)

**Watch the full demo:** [https://youtu.be/vsI2z3ZWoBQ](https://youtu.be/vsI2z3ZWoBQ)

---

## 🎯 Key Features

### ⚡ 5-Agent Sequential Pipeline
Each agent receives the previous agent's full output as context — creating an intelligent cascading analysis chain. Not just classification. Deep legal reasoning at every stage.

### ⚖️ Jurisdiction-Aware Legal Research
Maps applicable Indian, US, and UK statutes with section numbers, relevance scores, claimant rights, and respondent defenses. Covers IPC, TPA, Consumer Protection Act 2019, Industrial Disputes Act, POSH Act, and 12+ dispute categories across 5 tracks.

### 📊 Probabilistic Case Analytics
Win probability (0–100%), ZOPA (Zone of Possible Agreement), court cost estimate, timeline projection, evidence strength score (0–100), and payment recovery probability. The AI Mediator uses ZOPA internally — **never revealed to either party**.

### 🤝 3-Round AI Mediation System
Claimant and respondent submit offers independently each round. The AI Mediator analyzes the gap, legal merits, and full round history — proposes a fair settlement with complete legal reasoning. Tone escalates round by round. Round 3 is explicit: final chance before automatic escalation.

### 📄 Dedicated AI Sub-Agents Per Document
Each document has its own AI prompt, visual theme, and legal structure:

| Document | Theme | When Generated |
|---|---|---|
| Demand Letter | Navy | At analysis (always) |
| Court-Ready Case File | Red | At analysis (monetary/employment/consumer) |
| Settlement Agreement | Green | On both-party acceptance |
| FIR Advisory | Orange | Criminal track only |
| Mediation Certificate | Blue | All non-criminal cases |
| Breach of Settlement Notice | Dark Red | On payment non-compliance |

### 🛡️ 5 Dispute Tracks
| Track | Examples |
|---|---|
| **Monetary Civil** | Rent deposit, unpaid salary, contract breach, defamation with damages |
| **Employment** | Wrongful termination, PF/gratuity, POSH Act, experience letter withheld |
| **Consumer** | E-commerce non-delivery, insurance rejection, banking fraud, RERA delay |
| **Non-Monetary** | Apology demands, neighbor disputes, social media defamation |
| **Criminal** | Advisory only — FIR draft, IPC sections, relevant authority guidance |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI · Python 3.11 · 14 REST endpoints |
| **AI / LLM** | Azure OpenAI GPT-4o · GPT-4o-mini |
| **Database** | Azure Cosmos DB — cases, users, negotiations, documents |
| **File Storage** | Azure Blob Storage — PDFs, evidence, signed agreements |
| **Email** | Azure Communication Services — 10 automated triggers |
| **PDF Engine** | ReportLab — 6 document types, Unicode-safe `_safe()` processor |
| **Auth** | Email OTP + JWT — no external auth provider |
| **Safety** | Azure AI Content Safety — harmful content blocked |
| **Frontend** | HTML · Tailwind CSS · Vanilla JS |
| **Deployment** | Azure App Service B2 Linux |

---

## 📁 Project Structure

```
legalai-resolver/
├── app/
│   ├── main.py                    # FastAPI app, middleware stack, startup
│   ├── config.py                  # Settings loaded from environment
│   │
│   ├── agents/
│   │   ├── intake_agent.py        # Track-aware classification + evidence scoring
│   │   ├── legal_agent.py         # Jurisdiction-aware statute mapping (GPT-4o)
│   │   ├── analytics_agent.py     # ZOPA + win probability (GPT-4o-mini)
│   │   ├── document_agent.py      # 6 PDF generators + Azure Blob upload
│   │   └── negotiation_agent.py   # ZOPA-based, history-aware mediation (GPT-4o)
│   │
│   ├── routers/
│   │   ├── auth.py                # /request-otp · /verify-otp · /me
│   │   ├── cases.py               # /submit · /status · /send-invite · /timeline
│   │   ├── negotiation.py         # /submit-offer · /proposal-response · /status
│   │   ├── documents.py           # PDF download SAS URLs
│   │   └── respondent.py          # Respondent portal (no auth required)
│   │
│   ├── services/
│   │   ├── openai_service.py      # Azure OpenAI wrapper with retry logic
│   │   ├── cosmos_service.py      # Full DB layer + state machine integration
│   │   ├── blob_service.py        # Upload + time-limited SAS URL generation
│   │   ├── email_service.py       # All 10 branded HTML email templates
│   │   └── content_safety.py      # Input filtering + abuse pattern detection
│   │
│   ├── core/
│   │   ├── state_machine.py       # Enforces valid case status transitions
│   │   ├── case_router.py         # Fast 5-track pre-classification (GPT-4o-mini)
│   │   ├── dependencies.py        # JWT Bearer middleware
│   │   ├── expiry_worker.py       # Hourly deadline enforcement (6 expiry handlers)
│   │   ├── rate_limiter.py        # Per-endpoint in-memory rate limiting
│   │   ├── security_headers.py    # X-Frame-Options, HSTS, XSS headers
│   │   └── disclaimer.py          # DPDP + AI disclaimer constants
│   │
│   └── models/
│       ├── case.py                # CaseStatus (18 states), CaseTrack, Pydantic models
│       ├── negotiation.py         # Round, proposal, decision, proof request models
│       └── user.py                # User models
│
├── frontend/
│   ├── index.html                 # Claimant portal — auth, dashboard, case detail
│   └── respond.html               # Respondent portal — offer, accept/reject, decline
│
├── tests/
│   └── test_e2e.py                # 20-assertion end-to-end test
│
├── requirements.txt
├── startup.sh                     # Azure App Service startup command
└── .env.local                     # Local dev secrets (git-ignored)
```

---

## ⚙️ Running Locally

### Prerequisites
- Python 3.11+
- Active Azure subscription with the following services:
  - Azure OpenAI (with `gpt-4o` and `gpt-4o-mini` deployments)
  - Azure Cosmos DB (with `legalai-db` database + 4 containers)
  - Azure Blob Storage (with 3 containers)
  - Azure Communication Services (with verified email domain)
  - Azure AI Content Safety

### 1. Clone

```bash
git clone https://github.com/Lambo-IITian/NoCourt
cd NoCourt
```

### 2. Virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure `.env.local`

```env
BASE_URL=http://localhost:8000
ENVIRONMENT=development

# Azure OpenAI (eastus — not available in centralindia)
AZURE_OPENAI_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://eastus.api.cognitive.microsoft.com/
AZURE_OPENAI_DEPLOYMENT_LARGE=gpt-4o-legal
AZURE_OPENAI_DEPLOYMENT_SMALL=gpt-4o-mini-fast

# Azure Cosmos DB
COSMOS_CONNECTION_STRING=AccountEndpoint=https://...;AccountKey=...;
COSMOS_DATABASE_NAME=legalai-db

# Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_STORAGE_ACCOUNT_NAME=your_storage_account_name

# Azure Communication Services
AZURE_COMM_CONNECTION_STRING=endpoint=https://...;accesskey=...
AZURE_SENDER_EMAIL=DoNotReply@your-domain.azurecomm.net

# Azure AI Content Safety
CONTENT_SAFETY_KEY=your_key
CONTENT_SAFETY_ENDPOINT=https://your-resource.cognitiveservices.azure.com/

# JWT Auth
JWT_SECRET_KEY=your_64_char_hex_secret_here
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=72
OTP_EXPIRE_MINUTES=10

# Azure Application Insights (optional)
APPINSIGHTS_INSTRUMENTATION_KEY=your_key
```

> Generate JWT secret: `python -c "import secrets; print(secrets.token_hex(32))"`

### 5. Create Cosmos DB containers

```bash
# Run once to provision the 4 containers
az cosmosdb sql container create --account-name YOUR_COSMOS \
  --resource-group YOUR_RG --database-name legalai-db \
  --name cases --partition-key-path "/id"

az cosmosdb sql container create --account-name YOUR_COSMOS \
  --resource-group YOUR_RG --database-name legalai-db \
  --name users --partition-key-path "/id"

az cosmosdb sql container create --account-name YOUR_COSMOS \
  --resource-group YOUR_RG --database-name legalai-db \
  --name negotiations --partition-key-path "/id"

az cosmosdb sql container create --account-name YOUR_COSMOS \
  --resource-group YOUR_RG --database-name legalai-db \
  --name documents --partition-key-path "/id"
```

### 6. Run

```bash
uvicorn app.main:app --reload --env-file .env.local
```

Visit [http://localhost:8000](http://localhost:8000)

### 7. Health check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "services": {
    "cosmos_db": "ok",
    "blob_storage": "ok",
    "azure_openai": "ok",
    "content_safety": "ok",
    "environment": "development",
    "base_url": "http://localhost:8000"
  }
}
```

---

## 🌐 Deploying to Azure App Service

### 1. Create App Service

```bash
az appservice plan create \
  --name legalai-plan \
  --resource-group YOUR_RG \
  --sku B2 --is-linux

az webapp create \
  --name legalai-resolver \
  --resource-group YOUR_RG \
  --plan legalai-plan \
  --runtime "PYTHON:3.11"
```

### 2. Set all environment variables

```bash
az webapp config appsettings set \
  --name legalai-resolver \
  --resource-group YOUR_RG \
  --settings \
    BASE_URL="https://legalai-resolver.azurewebsites.net" \
    ENVIRONMENT="production" \
    AZURE_OPENAI_KEY="your_key" \
    AZURE_OPENAI_ENDPOINT="https://eastus.api.cognitive.microsoft.com/" \
    AZURE_OPENAI_DEPLOYMENT_LARGE="gpt-4o-legal" \
    AZURE_OPENAI_DEPLOYMENT_SMALL="gpt-4o-mini-fast" \
    COSMOS_CONNECTION_STRING="your_connection_string" \
    COSMOS_DATABASE_NAME="legalai-db" \
    AZURE_STORAGE_CONNECTION_STRING="your_connection_string" \
    AZURE_STORAGE_ACCOUNT_NAME="your_account_name" \
    AZURE_COMM_CONNECTION_STRING="your_connection_string" \
    AZURE_SENDER_EMAIL="DoNotReply@your-domain.azurecomm.net" \
    CONTENT_SAFETY_KEY="your_key" \
    CONTENT_SAFETY_ENDPOINT="your_endpoint" \
    JWT_SECRET_KEY="your_64_char_secret" \
    JWT_ALGORITHM="HS256" \
    JWT_EXPIRE_HOURS="72" \
    OTP_EXPIRE_MINUTES="10" \
    SCM_DO_BUILD_DURING_DEPLOYMENT="true"
```

### 3. Set startup command

```bash
az webapp config set \
  --name legalai-resolver \
  --resource-group YOUR_RG \
  --startup-file "startup.sh"
```

### 4. Deploy via Git

```bash
git init
git add .
git commit -m "initial deploy"

az webapp deployment source config-local-git \
  --name legalai-resolver --resource-group YOUR_RG

git remote add azure <URL_FROM_ABOVE>
git push azure main
```

### 5. Verify

```bash
curl https://legalai-resolver.azurewebsites.net/health
```

---

## 🗺️ API Reference

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/api/auth/request-otp` | Send 6-digit OTP to email | None |
| `POST` | `/api/auth/verify-otp` | Verify OTP → returns JWT | None |
| `GET` | `/api/auth/me` | Get current user profile | JWT |
| `POST` | `/api/cases/submit` | Submit dispute, trigger 5-agent pipeline | JWT |
| `GET` | `/api/cases/{id}/status` | Poll case status (used for frontend polling) | None |
| `GET` | `/api/cases/{id}` | Full case data including agent outputs | JWT |
| `POST` | `/api/cases/{id}/send-invite` | Email invite to respondent | JWT |
| `GET` | `/api/cases/{id}/timeline` | Chronological case event list | JWT |
| `POST` | `/api/cases/{id}/confirm-payment` | Confirm payment received / report breach | JWT |
| `GET` | `/api/respondent/case/{id}?email=X` | Filtered respondent view (no analytics) | None |
| `POST` | `/api/respondent/accept-in-full` | Respondent accepts full amount | None |
| `POST` | `/api/respondent/decline` | Respondent declines → auto-escalate | None |
| `POST` | `/api/negotiation/submit-claimant-offer` | Submit claimant round offer | JWT |
| `POST` | `/api/negotiation/submit-respondent-offer` | Submit respondent round offer | None |
| `POST` | `/api/negotiation/proposal-response` | Accept or Reject AI proposal | Optional |
| `GET` | `/api/negotiation/status/{id}` | Full negotiation state + round details | JWT |
| `GET` | `/api/documents/{id}/all` | All available document download URLs | JWT |
| `GET` | `/api/documents/{id}/demand-letter` | Demand letter SAS URL | JWT |
| `GET` | `/api/documents/{id}/settlement` | Settlement agreement SAS URL | JWT |
| `GET` | `/api/documents/{id}/court-file` | Court file SAS URL | JWT |
| `GET` | `/health` | Service health check for all Azure services | None |

---

## 📧 Email Notification System

10 automated triggers across the full case lifecycle:

```
1.  OTP Login Code          → Claimant (login)
2.  Case Invite             → Respondent (with secure portal link)
3.  Offer Received          → Other party (submit your offer)
4.  AI Proposal Issued      → Both parties (accept/reject)
5.  Next Round Started      → Both parties (submit new offer)
6.  Settlement Confirmed    → Both parties (PDF download link)
7.  Escalation Notice       → Both parties (court file download)
8.  Auto-Escalation         → Claimant (non-participation noted)
9.  Breach of Settlement    → Claimant (PDF download link)
10. Payment Deadline Passed → Claimant (auto breach notice)
```

---

## 🔒 Security Features

| Feature | Implementation |
|---|---|
| Rate limiting | OTP: 5/5min · Submit: 3/hr · General: 200/min (in-memory) |
| Security headers | X-Frame-Options: DENY · HSTS · X-Content-Type-Options: nosniff |
| Input validation | Path traversal, SQLi, XSS blocked at middleware layer |
| Content filtering | Azure AI Content Safety — severity ≥ 4 blocked |
| JWT auth | HS256 signed · 72-hour expiry · Bearer scheme |
| Respondent privacy | Analytics, ZOPA, win probability hidden from respondent |
| DPDP compliance | Explicit consent + disclaimer required before case submission |

---

## ⚠️ Known Limitations

- Legal accuracy is AI-generated — not verified by a licensed advocate
- Settlement agreements are AI-drafted — should be reviewed by a lawyer before use in court
- In-memory rate limiter — for multi-worker production, replace with Redis
- PDFs lost on server restart if not using Blob Storage (ephemeral on free hosting tiers)
- No authentication on respondent portal — verified by email address match only

---

## 🏗️ Design Decisions

| Decision | Reason |
|---|---|
| Sequential agent pipeline | Full context cascade — each agent builds on all prior analysis |
| ZOPA hidden from both parties | Preserves negotiation integrity, prevents anchoring bias |
| Email OTP instead of B2C | Simpler UX, immediate setup, no external tenant dependency |
| 3-round cap | Mirrors professional mediation — forces convergence, prevents infinite loops |
| Unicode-safe PDF layer | ReportLab Helvetica crashes on Rs./€/— — `_safe()` pre-processor fixes silently |
| Criminal track advisory-only | Mediating assault or violence is ethically wrong and legally meaningless |
| Separate document sub-agents | 3 distinct prompts + layouts — Demand, Court, Settlement are completely independent |
| GPT-4o for Legal + Negotiation | Reasoning depth matters — statute mapping and mediation need the large model |
| GPT-4o-mini for Intake + Analytics | Speed and cost efficiency — classification does not need reasoning depth |

---

## 👤 Author

**Team - Roomies**
Mohit Gunani | Vaka Khashyap Sai | Aditya Kumar Sharma
B.Tech Electronics Engineering, IIT (BHU) Varanasi

---

## 📄 License

MIT

---

<div align="center">

**Microsoft AI UNLOCKED Hackathon 2025 · Top 55 / 1000+ Teams**

*Justice shouldn't require a lawyer or a fortune.*

</div>

# OFC360 Backend

> **Enterprise Human Resources Management & Organizational Intelligence Platform**
> High-performance, multi-tenant backend built with FastAPI, SQLAlchemy 2.0 (AsyncPG), PostgreSQL 16, Redis 7, Celery 5, and local AI runtime integration.

## 1. Project Overview

OFC360 Backend is the central application server and data layer for the OFC360 enterprise platform. It delivers complete automation and intelligence for core human resource operations, workforce lifecycle, payroll accounting, statutory compliance, talent acquisition, performance reviews, document verification, real-time collaboration, and localized enterprise AI capabilities.

### Key Backend Responsibilities
- **Core HR Lifecycle & Multi-Tenancy**: Complete management of organizations, departments, designations, employees, managers, assets, and hierarchy with automatic tenant data isolation via SQLAlchemy ORM event interceptors.
- **Authentication & Security**: Multi-tenant authentication, RS256 asymmetric JWT signing, refresh token rotation with grace period, Redis-backed stateless token blacklisting, and role-based access control (RBAC) across six canonical roles.
- **Payroll Processing & Statutory Compliance**: End-to-end salary calculations, pay cycles, earnings/deductions, overtime, bonuses, advance loans, Indian statutory compliance (PF ECR, ESI, Professional Tax, TDS Section 192), bank advice files (HDFC, ICICI, SBI, Generic NEFT), and batch payslip generation.
- **Recruitment & Applicant Tracking (ATS)**: Job requisitions, public career portal, application pipelines, candidate sourcing, interview scheduling with scorecards, offer letter management, and automated resume screening.
- **Time & Attendance Tracking**: Shift management, timesheets, check-in/out logging, attendance regularization requests, break tracking, and biometric face recognition verification using OpenCV, dlib, and deep face embeddings.
- **Document Management & Automated OCR**: Multi-version document store, template generation, PDF manipulation, digital signatures, expiry alerts, and OCR document extraction.
- **Enterprise Collaboration & Helpdesk**: Real-time communication channels, 1-on-1 direct messaging, team channels, WebRTC call signaling, announcements, company news, polls, and an internal ticketing helpdesk.
- **Local AI & Intelligent Automation**: Powered strictly by an on-premise Ollama runtime (Qwen 3 / Llama 3.1 / Nomic Embed) to guarantee strict zero-data-leakage compliance. Cloud LLM providers are explicitly disabled.

### API Architecture & Communication
- **API Versioning**: Standardized RESTful APIs organized under `/api/v1` (Core HR, Auth, Management, AI Hub) and `/api/v2` (Advanced Intelligence, Document Intelligence, Copilots, Analytics).
- **Response Envelope**: Universal `APIResponse[T]` schema (`success`, `message`, `data`, `errors`) with dual-key casing support (`snake_case` and `camelCase`) for seamless frontend interoperability.
- **Background Processing**: Asynchronous distributed task execution via Celery with Redis broker and Redis result backend, featuring graceful synchronous fallbacks when Celery is not enabled.

## 2. Tech Stack

The technology stack is verified directly from `requirements.txt`, `Dockerfile`, and application configuration:

| Layer | Technology | Version | Purpose |
| --- | --- | --- | --- |
| **Runtime** | Python | `3.11-slim-bookworm` | Base application runtime environment |
| **Web Framework** | FastAPI | `>=0.115.0` | Asynchronous high-performance REST API framework |
| **ASGI Server** | Uvicorn (standard) | `>=0.30.0` | ASGI HTTP server with uvloop and httptools |
| **ORM & DB Layer** | SQLAlchemy (asyncio) | `>=2.0.30` | Modern 2.0 async ORM with mapper relationships |
| **Database Driver** | asyncpg | `>=0.29.0` | High-speed asynchronous PostgreSQL binary driver |
| **Database** | PostgreSQL | `16-alpine` | Primary ACID relational database |
| **Migrations** | Alembic | `>=1.13.2` | Database schema migrations with single-head lock |
| **Data Validation** | Pydantic & Pydantic Settings | `>=2.8.0`, `>=2.3.0` | Strict schema validation and typed settings loading |
| **Authentication** | python-jose & passlib[bcrypt] | `>=3.3.0`, `>=1.7.4` (bcrypt 4.0.1) | RS256/HS256 JWT tokens & Bcrypt (12 rounds) hashing |
| **In-Memory Store** | Redis | `7-alpine` (redis-py `>=5.0.0`) | Token blacklist, rate limiting, and session caching |
| **Task Queue** | Celery | `>=5.4.0` | Distributed asynchronous background worker queue |
| **Biometrics & CV** | dlib, face_recognition, OpenCV | `20.0.1`, `1.3.0`, `>=4.10.0.84` | Facial recognition, attendance biometrics, QR codes |
| **Document Processing** | ReportLab, openpyxl, pypdf, python-docx | `>=4.2.0`, `>=3.1.5`, `>=1.16.2`, `>=1.1.2` | PDF payslip generation, Excel export, docx extraction |
| **Data Science** | pandas, numpy | `>=2.2.0`, `>=1.26.0,<2.0.0` | Payroll calculations, analytics, and metrics aggregation |
| **Local AI Runtime** | Ollama | Host daemon (`qwen3:30b`) | Exclusively supported local LLM provider for zero data leak |
| **Cloud Storage** | Cloudinary | `>=1.45.0` | Document, logo, and avatar asset cloud hosting |
| **Payment Gateway** | Razorpay SDK | `>=1.4.1` | Order creation, verification, and webhooks |
| **Testing** | pytest & pytest-asyncio | `>=8.0.0`, `>=0.23.0` | 72 automated test suites with async event loop |

> [!NOTE]
> **AI Provider Status**: External cloud LLM providers (OpenAI, Anthropic Claude, Google Gemini, OpenRouter) are **intentionally disabled** in the codebase. All AI capabilities are powered strictly by the local Ollama runtime to protect sensitive employee records and payroll data.

## 3. Architecture

The OFC360 backend is designed using a clean, layered architecture with strict separation of concerns, request-scoped async database sessions, repository abstraction, business logic encapsulation in services, and automated middleware.

```mermaid
flowchart TD
    Client["Frontend Client (Browser / Mobile / Public Portal)"]
    
    subgraph NetworkEdge ["Edge & Middleware Layer"]
        CORS["CORS Middleware (Outermost ASGI Layer)"]
        SecurityHeaders["Security Headers Middleware"]
        RateLimit["Redis Sliding Window Rate Limiter"]
        AuthMiddleware["JWT Bearer & Cookie Authentication"]
        TenantCtx["Tenant Context Provider (tenant_id_ctx)"]
    end
    
    subgraph APILayer ["FastAPI Application Routers"]
        V1Routers["API v1 Routers (/api/v1/*)"]
        V2Routers["API v2 Routers (/api/v2/*)"]
        CoreRouters["Core HRMS & Public Routers (/api/*)"]
    end
    
    subgraph LogicLayer ["Service & Repository Layer"]
        Services["Business Logic Services"]
        Repos["Domain Repositories"]
    end
    
    subgraph DataIsolation ["SQLAlchemy 2.0 Multi-Tenancy Layer"]
        ORMInterceptor["SQLAlchemy do_orm_execute Event (with_loader_criteria)"]
        FlushInterceptor["SQLAlchemy before_flush Event (assign company_id)"]
    end
    
    subgraph Persistence ["Data Stores & Caching"]
        PostgreSQL[("PostgreSQL 16 Database")]
        Redis[("Redis 7 (Tokens, Cache, Rate Limits)")]
    end
    
    subgraph AsyncWorkers ["Background Tasks & External Services"]
        Celery["Celery Background Workers"]
        Ollama["Local Ollama LLM Service"]
        SMTP["SMTP Mail Server"]
        Cloudinary["Cloudinary Media Store"]
    end
    
    Client --> CORS
    CORS --> SecurityHeaders
    SecurityHeaders --> RateLimit
    RateLimit --> AuthMiddleware
    AuthMiddleware --> TenantCtx
    TenantCtx --> V1Routers & V2Routers & CoreRouters
    V1Routers & V2Routers & CoreRouters --> Services
    Services --> Repos
    Repos --> ORMInterceptor
    ORMInterceptor --> PostgreSQL
    FlushInterceptor --> PostgreSQL
    AuthMiddleware -. Token Revocation & Blocklist .-> Redis
    Services -. Enqueue Jobs .-> Celery
    Celery -. Broker & Backend .-> Redis
    Services -. AI Queries .-> Ollama
    Services -. Transactional Emails .-> SMTP
    Services -. Static Media .-> Cloudinary
```

### Architectural Workflow
1. **Request Ingestion**: Incoming HTTP requests hit FastAPI through the outermost `CORSMiddleware`, which handles OPTIONS preflight immediately with 200/204 responses.
2. **Security & Rate Limiting**: Request passes through `SecurityHeadersMiddleware` (X-Frame-Options, CSP, HSTS) and `RateLimitMiddleware` (backed by Redis with an in-memory fallback).
3. **Authentication & Tenant Binding**: `get_current_user_claims` resolves the RS256 Bearer JWT, validates token expiration, checks the Redis blacklist for revocations, extracts `company_id`, and sets the context variable `tenant_id_ctx`.
4. **Service Execution**: Routers delegate directly to business services (`AuthService`, `PayrollRunService`, `RecruitmentService`, `EmployeeService`, etc.).
5. **Multi-Tenant Data Isolation**: When database queries execute, SQLAlchemy's `do_orm_execute` event automatically injects a `with_loader_criteria` filter (`company_id == tenant_id_ctx.get()`) into all queries unless explicit administrative bypass (`bypass_tenant=True`) is specified. During insert/update, `before_flush` automatically attaches the tenant ID.
6. **Background Offloading**: Heavy compute operations (payroll batch calculation, PDF generation, bulk email dispatch, resume parsing) are pushed to Celery queues over Redis or executed asynchronously via Python event loops.

## 4. Project Structure

```text
apiofc360/
├── app/                                  # Core application source code
│   ├── agents/                           # Autonomous AI agent implementations
│   ├── analytics/                        # Aggregation logic and analytical query builders
│   ├── api/                              # REST API endpoint routers
│   │   ├── cto/                          # CTO and engineering executive dashboard routes
│   │   ├── payroll/                      # Comprehensive payroll API submodules
│   │   ├── v1/                           # API Version 1 routers and AI Hub submodules
│   │   │   ├── ai_hub/                   # AI Gateway endpoints (15 specialized sub-routers)
│   │   │   └── payroll/                  # Legacy v1 payroll calculation and run routes
│   │   ├── v2/                           # API Version 2 routers (Copilots, Intelligence, Analytics)
│   │   ├── auth.py                       # Authentication, registration, OTP, tokens, password reset
│   │   ├── employees.py                  # Employee directory, personal profiles, documents, skills
│   │   ├── hr_admin.py                   # HR Admin administrative operations & employee provisioning
│   │   ├── managers.py                   # Manager team dashboard, approvals, direct reports
│   │   ├── departments.py                # Department CRUD, headcount breakdown, assignments
│   │   ├── jobs.py & recruitment.py      # ATS, job postings, requisitions, candidate sourcing
│   │   ├── applications.py               # Candidate job applications and resume attachments
│   │   ├── interviews.py                 # Interview rounds, scheduling, scorecards
│   │   ├── onboarding.py                 # Employee onboarding steps, checklist, document upload
│   │   ├── timesheets.py & attendance.py # Attendance logs, shifts, breaks, regularization
│   │   ├── leaves.py                     # Leave types, balances, applications, approvals
│   │   ├── assets.py                     # Asset inventory, assignment history, maintenance
│   │   ├── exits.py                      # Resignation, clearance, exit interview, FnF settlements
│   │   ├── documents.py                  # Document categories, templates, e-signatures, audit logs
│   │   ├── connect.py                    # Real-time chat, channels, calls, meetings, file sharing
│   │   ├── helpdesk.py                   # Internal employee support tickets, comments, FAQs
│   │   ├── super_admin.py                # Platform Super Admin endpoints & tenant company management
│   │   ├── billing.py & payments.py      # Razorpay payment orders, subscription tiers, invoices
│   │   └── settings.py                   # Company settings, security policies, IP whitelist, MFA
│   ├── attendance/                       # Attendance sub-package (models, schemas, routers)
│   ├── core/                             # Core configuration, security, and exception handling
│   │   ├── config.py                     # Pydantic BaseSettings loading from environment
│   │   ├── exceptions.py                 # AppException hierarchy and global exception handlers
│   │   ├── permissions.py                # Catalog of roles and permissions
│   │   ├── rate_limiter.py               # Redis sliding window rate limiter and middleware
│   │   ├── rbac.py                       # FastAPI role verification dependencies (require_*)
│   │   ├── redis_client.py               # Async Redis connection pool and token blacklist helper
│   │   └── security.py                   # Passlib bcrypt password hashing and cryptographic utils
│   ├── db/                               # Database setup, sessions, base classes, and events
│   │   ├── base.py                       # Declarative Base, TimestampMixin, UUID generator, tenant_id_ctx
│   │   └── database.py                   # create_async_engine, async_sessionmaker, ORM event hooks
│   ├── llm/                              # Local LLM client, router, prompts, and Ollama registry
│   ├── middleware/                       # ASGI Middlewares (Auth, Timing, Security Headers)
│   ├── models/                           # 244 SQLAlchemy database model definitions
│   │   ├── user/                         # User model package, mixins, and canonical UserRole enum
│   │   ├── payroll.py & payroll_models.py# Enterprise payroll, payslips, bank batches, tax settings
│   │   ├── recruitment.py                # Jobs, candidates, applications, interviews, scorecards
│   │   ├── employee.py                   # Employee profile, addresses, bank accounts, documents
│   │   ├── connect.py                    # Channels, direct messages, calls, meetings, attachments
│   │   └── ...                           # Other domain models
│   ├── ocr/                              # OCR engine drivers (PaddleOCR, EasyOCR, Tesseract, Document AI)
│   ├── rag/                              # Vector embedding store and document retrieval
│   ├── repositories/                     # Data access layer abstracting direct SQLAlchemy queries
│   ├── routers/                          # Core HRMS module routers
│   ├── schemas/                          # Pydantic request and response validation models
│   ├── services/                         # Business logic services (EmailService, PayrollService, etc.)
│   ├── templates/                        # HTML email templates (activation, OTP, welcome, onboarding)
│   ├── utils/                            # Helper utilities (JWT encoder/decoder, formatters, dates)
│   ├── validators/                       # Input validation rules (phone numbers, passwords, emails)
│   ├── workers/                          # Celery background tasks (payroll, resume, notification)
│   └── main.py                           # FastAPI application factory, lifespan handler, route mounting
├── alembic/                              # Alembic database migrations
│   ├── versions/                         # 90 version migration scripts
│   └── env.py                            # Migration environment with asyncpg NullPool runner
├── scripts/                              # Operational, diagnostic, and deployment automation scripts
│   ├── check_migrations.py               # Validates single Alembic head and zero divergence
│   ├── run_migrations.py                 # Runs migrations under PostgreSQL advisory lock
│   ├── predeploy.sh                      # Zero-downtime deployment script with sanity checks
│   └── install_dlib.py                   # Pre-compiled / parallel dlib provisioning helper
├── tests/                                # 72 comprehensive automated test suites
├── uploads/                              # Mounted local storage for avatars, documents, attachments
├── Dockerfile                            # Multi-stage production container build
├── docker-compose.yml                    # Multi-container orchestration (api, db, redis, celery_worker)
├── docker-entrypoint.sh                  # Container startup entrypoint with automated migration runner
├── Makefile                              # Make tasks (db-check)
├── pytest.ini                            # Pytest configuration with async loop scoping
├── requirements.txt                      # Production Python dependencies
└── requirements-dev.txt                  # Development and test dependencies
```

## 5. API Architecture

### API Versioning & Routing
- **Prefix `/api/v1`**: Core enterprise HRMS modules, authentication, onboarding, recruitment, timesheets, payroll runs, settings, and the unified AI Hub Gateway.
- **Prefix `/api/v2`**: Advanced organizational intelligence, executive copilots, behavioral interview bot, mood detection, employee digital twins, and specialized intelligence engines.
- **Direct `/api/*` & Unprefixed Endpoints**: Public career portal (`/api/careers`), public payment webhooks (`/payments/webhook`), system health checks (`/health`, `/health/ready`), and diagnostic tools.

### Request Validation & Response Schema
All endpoints validate incoming JSON payloads through Pydantic v2 models. Responses are serialized into the standard envelope `APIResponse[T]`:
```json
{
  "success": true,
  "message": "Operation completed successfully.",
  "data": { ... },
  "errors": null
}
```

### Error Envelope
When business exceptions or validation errors occur, responses adhere to the unified error contract with appropriate HTTP status codes:
```json
{
  "success": false,
  "message": "Validation failed.",
  "data": null,
  "errors": [
    {"field": "email", "message": "Invalid email address format."}
  ],
  "code": "VALIDATION_FAILED"
}
```

### Pagination, Filtering & Sorting
- **Pagination**: Supported across listing endpoints using `limit` (default: 20, max: 100) and `offset` (default: 0) or `page` and `page_size` query parameters. Response payloads include total counts, total pages, and current page metadata.
- **Filtering**: Query parameters support filtering by `department_id`, `status`, `role`, `employment_type`, `date_from`, `date_to`, and text `search`.
- **Sorting**: Handled through `sort_by` (field name) and `sort_order` (`asc` or `desc`).

### Rate Limiting
- **Global Middleware**: `RateLimitMiddleware` enforces sliding window quotas via Redis: 100 requests/minute and 2,000 requests/hour per client IP or authenticated user ID.
- **Sensitive Auth Limits**: Login is limited to 5 attempts per 60 seconds (`LOGIN_RATE_LIMIT_LIMIT=5`, `LOGIN_RATE_LIMIT_WINDOW=60`); registration is limited to 5 per minute (`REGISTER_RATE_LIMIT="5/minute"`); OTP resend has a 30-second cooldown (`OTP_RESEND_COOLDOWN_SECONDS=30`) with a maximum of 5 verification attempts (`OTP_MAX_ATTEMPTS=5`).
- **AI Endpoints**: Rate limited to 30 requests/minute and 500 requests/hour per user (`AI_RATE_LIMIT_PER_MINUTE=30`).

## 6. API Endpoints

The backend exposes 1,843 live registered routes across 115 unique tags. Below is the complete endpoint directory grouped by business domain. Every endpoint has been verified against the active source code.

### Authentication (24 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Bearer (Authenticated) | Register User |
| `POST` | `/api/v1/auth/verify-email` | Bearer (Authenticated) | Verify Email |
| `POST` | `/api/v1/auth/resend-otp` | Bearer (Authenticated) | Resend Otp |
| `POST` | `/api/v1/auth/resend-verification` | Bearer (Authenticated) | Resend Otp |
| `POST` | `/api/v1/auth/login` | Bearer (Authenticated) | Login |
| `POST` | `/api/v1/auth/verify-email-otp` | Bearer (Authenticated) | Verify Email Otp |
| `POST` | `/api/v1/auth/resend-email-otp` | Bearer (Authenticated) | Resend Email Otp |
| `GET` | `/api/v1/auth/google/url` | Public (None) | Get Google OAuth authorization URL |
| `POST` | `/api/v1/auth/google` | Bearer (Authenticated) | Google OAuth SSO Login |
| `GET` | `/api/v1/auth/github/url` | Public (None) | Get GitHub OAuth authorization URL |
| `POST` | `/api/v1/auth/github` | Bearer (Authenticated) | GitHub OAuth SSO Login |
| `POST` | `/api/v1/auth/refresh-token` | Bearer (Authenticated) | Refresh |
| `POST` | `/api/v1/auth/refresh` | Bearer (Authenticated) | Rotate an active refresh token for a new access and refresh token pair. |
| `POST` | `/api/v1/auth/logout` | Bearer (Authenticated) | Logout |
| `POST` | `/api/v1/auth/forgot-password` | Bearer (Authenticated) | Forgot Password |
| `POST` | `/api/v1/auth/verify-reset-otp` | Bearer (Authenticated) | Verify Reset Otp |
| `POST` | `/api/v1/auth/reset-password` | Bearer (Authenticated) | Reset Password |
| `GET` | `/api/v1/auth/status` | Public (None) | Check auth status |
| `GET` | `/api/v1/auth/me` | Bearer (Authenticated) | Get current user profile |
| `PATCH` | `/api/v1/auth/change-password` | Bearer (Authenticated) | Change account password (PATCH compatibility) |
| `POST` | `/api/v1/auth/change-password` | Bearer (Authenticated) | Change account password |
| `PATCH` | `/api/v1/auth/change-email` | Bearer (Authenticated) | Initiate email change |
| `POST` | `/api/v1/auth/verify-new-email` | Bearer (Authenticated) | Verify new email OTP |
| `PATCH` | `/api/v1/auth/change-phone` | Bearer (Authenticated) | Change phone number |

### Users (127 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/hr-admin/users` | Bearer (admin) | Create internal company user |
| `GET` | `/api/v1/hr-admin/users` | Bearer (admin) | List internal company users |
| `GET` | `/api/v1/hr-admin/users/{user_id}` | Bearer (admin) | Get internal company user details |
| `PATCH` | `/api/v1/hr-admin/users/{user_id}` | Bearer (admin) | Update internal company user |
| `DELETE` | `/api/v1/hr-admin/users/{user_id}` | Bearer (admin) | Deactivate internal company user |
| `POST` | `/api/v1/hr-admin/users/{user_id}/resend-invite` | Bearer (admin) | Resend invitation email to internal company user |
| `POST` | `/api/v1/employees` | Bearer (admin) | Create a new employee |
| `GET` | `/api/v1/employees/stats` | Bearer (admin_or_manager) | Get employee stats overview |
| `GET` | `/api/v1/employees/dashboard` | Bearer (admin_or_manager) | Get employee management dashboard analytics |
| `POST` | `/api/v1/employees/import` | Bearer (admin) | Bulk import employees from Excel or CSV sheet |
| `GET` | `/api/v1/employees/export` | Bearer (admin_or_manager) | Export employee records as Excel, CSV, or PDF |
| `GET` | `/api/v1/employees` | Bearer (admin_or_manager) | List all employees |
| `GET` | `/api/v1/employees/{id}` | Bearer (Authenticated) | Get employee by ID |
| `PATCH` | `/api/v1/employees/{id}` | Bearer (admin) | Update employee details (PATCH) |
| `PUT` | `/api/v1/employees/{id}` | Bearer (admin) | Update employee details |
| `DELETE` | `/api/v1/employees/{id}` | Bearer (admin) | Soft delete an employee |
| `POST` | `/api/v1/employees/{id}/send-invitation` | Bearer (admin) | Resend employee invitation link |
| `POST` | `/api/v1/employees/{id}/send-invite` | Bearer (admin) | Resend employee invitation link (alias) |
| `POST` | `/api/v1/employees/{id}/deactivate` | Bearer (admin) | Deactivate employee account |
| `POST` | `/api/v1/employees/{id}/activate-by-admin` | Bearer (admin) | Activate employee account by Admin |
| `GET` | `/api/v1/employees/validate-invitation` | Public (None) | Validate employee invitation token |
| `GET` | `/api/v1/employees/validate-token` | Public (None) | Validate employee invitation token alias |
| `GET` | `/api/v1/employees/validate` | Public (None) | Validate employee invitation token alias |
| `POST` | `/api/v1/employees/{id}/activate` | Public (None) | Activate employee account (self-activation via email link) |
| `POST` | `/api/v1/employees/{id}/approve` | Bearer (admin) | HR Approval for Onboarding |
| `POST` | `/api/v1/employees/{id}/reject` | Bearer (admin) | Reject Onboarding |
| `POST` | `/api/v1/employees/{id}/reset-password` | Bearer (admin) | Admin reset of employee password |
| `POST` | `/api/v1/managers` | Bearer (admin) | Create a new manager |
| `GET` | `/api/v1/managers` | Bearer (admin_or_manager) | List all managers |
| `GET` | `/api/v1/managers/validate` | Public (None) | Validate manager activation token (canonical alias) |
| `GET` | `/api/v1/managers/validate-token` | Public (None) | Validate manager activation token (alias) |
| `POST` | `/api/v1/managers/activate` | Public (None) | Activate manager account with invitation token (canonical) |
| `GET` | `/api/v1/managers/profile` | Bearer (Authenticated) | Get current manager's profile |
| `POST` | `/api/v1/managers/send-invite` | Bearer (admin) | Resend manager invitation link by manager ID or email |
| `GET` | `/api/v1/managers/{id}` | Bearer (admin) | Get manager by ID |
| `PUT` | `/api/v1/managers/{id}` | Bearer (admin) | Update manager details |
| `PATCH` | `/api/v1/managers/{id}/permissions` | Bearer (admin) | Update manager permissions |
| `DELETE` | `/api/v1/managers/{id}` | Bearer (admin) | Soft delete a manager |
| `POST` | `/api/v1/managers/{id}/send-invitation` | Bearer (admin) | Resend manager invitation link |
| `POST` | `/api/v1/managers/{id}/activate` | Public (None) | Activate manager account |
| `POST` | `/api/v1/managers/{id}/reset-password` | Bearer (admin) | Admin reset of manager password |
| `POST` | `/api/v1/managers/{id}/deactivate` | Bearer (admin) | Deactivate manager account |
| `POST` | `/api/v1/managers/{id}/activate-by-admin` | Bearer (admin) | Activate manager account by Admin |
| `POST` | `/api/v1/departments` | Bearer (admin_or_hr) | Create a new department |
| `GET` | `/api/v1/departments` | Bearer (Authenticated) | List all departments |
| `GET` | `/api/v1/departments/{id}` | Bearer (Authenticated) | Get department details by ID |
| `PUT` | `/api/v1/departments/{id}` | Bearer (admin_or_hr) | Update department details |
| `DELETE` | `/api/v1/departments/{id}` | Bearer (admin_or_hr) | Soft delete a department |
| `POST` | `/api/v1/departments/{id}/assign-manager` | Bearer (admin_or_hr) | Assign Head of Department (Manager) |
| `POST` | `/api/v1/departments/{id}/assign-employees` | Bearer (admin_or_hr) | Assign multiple employees to a department |
| `DELETE` | `/api/v1/departments/{id}/remove-manager` | Bearer (admin_or_hr) | Remove Head of Department |
| `DELETE` | `/api/v1/departments/{id}/remove-employee/{employee_id}` | Bearer (admin_or_hr) | Remove an employee from a department |
| `GET` | `/api/v1/departments/{id}/employees` | Bearer (Authenticated) | Get all employees in a department |
| `GET` | `/api/v1/departments/{id}/manager` | Bearer (Authenticated) | Get department manager (Head of Department) |
| `GET` | `/api/v1/departments/{id}/stats` | Bearer (Authenticated) | Get department statistics |
| `GET` | `/api/v1/assets` | Bearer (admin_or_hr) | List all company hardware assets |
| `GET` | `/api/v1/assets/filter-options` | Bearer (admin_or_hr) | Get distinct filter option values for assets |
| `GET` | `/api/v1/assets/upload-image` | Bearer (admin_or_hr) | Get asset upload image requirements |
| `POST` | `/api/v1/assets/upload-image` | Bearer (admin_or_hr) | Upload asset image to Cloudinary |
| `POST` | `/api/v1/assets` | Bearer (admin_or_hr) | Create a new asset record |
| `GET` | `/api/v1/assets/public/{id}` | Public (None) | Get public details of a single asset for QR scanning |
| `GET` | `/api/v1/assets/{id}` | Bearer (admin_or_hr) | Get details of a single asset |
| `PUT` | `/api/v1/assets/{id}` | Bearer (admin_or_hr) | Update specifications of an asset |
| `DELETE` | `/api/v1/assets/{id}` | Bearer (admin_or_hr) | Delete an asset record |
| `POST` | `/api/v1/assets/{id}/assign` | Bearer (admin_or_hr) | Assign an asset to an employee |
| `POST` | `/api/v1/assets/{id}/return` | Bearer (admin_or_hr) | Return asset to inventory stock room |
| `POST` | `/api/v1/assets/{id}/transfer` | Bearer (admin_or_hr) | Transfer assignment to another employee |
| `POST` | `/api/v1/assets/{id}/lost` | Bearer (admin_or_hr) | Flag asset as lost |
| `POST` | `/api/v1/assets/{id}/retired` | Bearer (admin_or_hr) | Decommission and retire asset |
| `POST` | `/api/v1/assets/{id}/maintenance` | Bearer (admin_or_hr) | Add a maintenance log entry |
| `POST` | `/api/v1/exits/resign` | Bearer (Authenticated) | Submit employee resignation |
| `GET` | `/api/v1/exits/my-request` | Bearer (Authenticated) | Get currently logged in employee's resignation request |
| `DELETE` | `/api/v1/exits/my-request` | Bearer (Authenticated) | Cancel own resignation request |
| `GET` | `/api/v1/exits/stats` | Bearer (admin_or_hr) | Get exit dashboard statistics |
| `GET` | `/api/v1/exits` | Bearer (admin_or_hr) | List all exit requests |
| `GET` | `/api/v1/exits/{id}` | Bearer (manager_or_hr_or_admin) | Get exit details by ID |
| `PATCH` | `/api/v1/exits/{id}/approve` | Bearer (admin_or_hr) | HR approves exit request |
| `PATCH` | `/api/v1/exits/{id}/reject` | Bearer (admin_or_hr) | HR rejects exit request |
| `PATCH` | `/api/v1/exits/{id}/start-notice-period` | Bearer (admin_or_hr) | Start notice period |
| `PATCH` | `/api/v1/exits/{id}/complete` | Bearer (admin_or_hr) | Complete offboarding and deactivate account |
| `PATCH` | `/api/v1/exits/{id}/manager-approve` | Bearer (manager_or_hr_or_admin) | Manager approves exit request |
| `PATCH` | `/api/v1/exits/{id}/manager-reject` | Bearer (manager_or_hr_or_admin) | Manager rejects exit request |
| `PATCH` | `/api/v1/exits/{id}/knowledge-transfer-complete` | Bearer (manager_or_hr_or_admin) | Complete Knowledge Transfer handover details |
| `GET` | `/api/v1/exits/{id}/assets` | Bearer (manager_or_hr_or_admin) | Get assets return checklist |
| `PATCH` | `/api/v1/exits/{id}/asset-return` | Bearer (admin_or_hr) | Update asset return status |
| `PATCH` | `/api/v1/exits/{id}/clearance` | Bearer (admin_or_hr) | Update department dues clearance status |
| `POST` | `/api/v1/exits/{id}/exit-interview` | Bearer (admin_or_hr) | Submit Exit Interview details |
| `GET` | `/api/v1/exits/{id}/fnf-preview` | Bearer (admin_or_hr) | Preview automated FNF payroll settlement calculations |
| `PATCH` | `/api/v1/exits/{id}/fnf` | Bearer (admin_or_hr) | Submit FNF payroll settlement details |
| `POST` | `/api/v1/exits/{id}/generate-documents` | Bearer (admin_or_hr) | Generate exit documents |
| `GET` | `/api/v1/settings/profile` | Bearer (Authenticated) | Get Profile |
| `PUT` | `/api/v1/settings/profile` | Bearer (Authenticated) | Update Profile |
| `GET` | `/api/v1/hierarchy` | Bearer (Authenticated) | Get complete organization tree |
| `GET` | `/api/v1/hierarchy/tree` | Bearer (Authenticated) | Get nested hierarchy tree JSON |
| `GET` | `/api/v1/hierarchy/chart` | Bearer (Authenticated) | Get hierarchy flat list optimized for React Flow |
| `GET` | `/api/v1/hierarchy/{employee_id}` | Bearer (Authenticated) | Get employee reporting chain details |
| `GET` | `/api/v1/hierarchy/path/{employee_id}` | Bearer (Authenticated) | Get reporting path from CEO down to employee |
| `PUT` | `/api/v1/hierarchy/assign-manager` | Bearer (Authenticated) | Assign reporting manager |
| `PUT` | `/api/v1/hierarchy/change-manager` | Bearer (Authenticated) | Transfer reporting manager |
| `DELETE` | `/api/v1/hierarchy/remove-manager/{employee_id}` | Bearer (Authenticated) | Remove manager link |
| `GET` | `/api/v1/hierarchy/direct-reports/{manager_id}` | Bearer (Authenticated) | List direct reports of a manager |
| `GET` | `/api/v1/hierarchy/team/{manager_id}` | Bearer (Authenticated) | List recursive team descendants of a manager |
| `GET` | `/api/v1/exports/employees` | Bearer (export_permission) | Export Employees |
| `GET` | `/api/v1/exports/departments` | Bearer (export_permission) | Export Departments |
| `GET` | `/api/v1/exports/managers` | Bearer (export_permission) | Export Managers |
| `GET` | `/api/v1/users/` | Bearer (Authenticated) | List Users |
| `GET` | `/api/v1/users` | Bearer (Authenticated) | List Users |
| `GET` | `/api/v1/users/me` | Bearer (Authenticated) | Get Current User Details |
| `POST` | `/api/v1/users/me/avatar` | Bearer (Authenticated) | Upload user avatar image |
| `GET` | `/api/v1/users/{id}` | Bearer (Authenticated) | Get User By Id |
| `PUT` | `/api/v1/users/{id}` | Bearer (Authenticated) | Update User |
| `GET` | `/api/v1/profile/` | Bearer (Authenticated) | Get My Profile |
| `GET` | `/api/v1/profile` | Bearer (Authenticated) | Get My Profile |
| `PUT` | `/api/v1/profile/` | Bearer (Authenticated) | Update My Profile |
| `PUT` | `/api/v1/profile` | Bearer (Authenticated) | Update My Profile |
| `GET` | `/api/v1/profile/assets` | Bearer (Authenticated) | Get Profile Assets |
| `GET` | `/api/v1/profile/activity` | Bearer (Authenticated) | Get Profile Activity |
| `GET` | `/api/v1/departments/` | Bearer (Authenticated) | List Departments |
| `POST` | `/api/v1/departments/` | Bearer (Authenticated) | Create Department |
| `PATCH` | `/api/v1/departments/{id}` | Bearer (Authenticated) | Update Department |
| `GET` | `/api/v1/employee-health/profile` | Bearer (Authenticated) | Get My Health Profile |
| `GET` | `/api/v1/managers/team` | Bearer (Authenticated) | Get Manager Team |
| `GET` | `/api/v1/managers/dashboard` | Bearer (Authenticated) | Get Manager Dashboard |
| `GET` | `/api/v1/assets/` | Bearer (Authenticated) | List Assets |
| `GET` | `/api/v2/tax/profile/{employee_id}` | Bearer (Authenticated) | Get employee tax profile |
| `GET` | `/settings/profile` | Bearer (Authenticated) | Get Profile |
| `PUT` | `/settings/profile` | Bearer (Authenticated) | Update Profile |

### Workforce (42 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ai/workforce/dashboard` | Bearer (Authenticated) | Get AI Workforce Planning Dashboard KPIs |
| `GET` | `/api/v1/ai/workforce/kpi` | Bearer (Authenticated) | Get AI Workforce Planning KPIs |
| `GET` | `/api/v1/ai/workforce/headcount-trends` | Bearer (Authenticated) | Get Headcount Trends |
| `GET` | `/api/v1/ai/workforce/department-comparison` | Bearer (Authenticated) | Get Department Comparison |
| `GET` | `/api/v1/ai/workforce/hiring-forecast` | Bearer (Authenticated) | Get Hiring Forecast |
| `GET` | `/api/v1/ai/workforce/capacity-demand` | Bearer (Authenticated) | Get Capacity vs Demand Matrix |
| `GET` | `/api/v1/ai/workforce/capacity-planning` | Bearer (Authenticated) | Get Department Capacity Planning |
| `GET` | `/api/v1/ai/workforce/resource-utilization` | Bearer (Authenticated) | Get Resource Utilization Metrics |
| `GET` | `/api/v1/ai/workforce/future-needs` | Bearer (Authenticated) | Get Future Workforce Needs Predictions |
| `GET` | `/api/v1/ai/workforce/optimization` | Bearer (Authenticated) | Get Workforce Optimization Recommendations |
| `GET` | `/api/v1/ai/workforce/hiring-budget` | Bearer (Authenticated) | Get Hiring Budget Analysis |
| `GET` | `/api/v1/ai/workforce/department/{department_id}` | Bearer (Authenticated) | Get Department Workforce Details |
| `GET` | `/api/v1/ai/workforce/employee/{employee_id}` | Bearer (Authenticated) | Get Employee Workforce Details |
| `POST` | `/api/v1/ai/workforce/analyze` | Bearer (Authenticated) | Analyze Workforce Capacity via AI |
| `POST` | `/api/v1/ai/workforce/forecast` | Bearer (Authenticated) | Generate AI Hiring Forecast |
| `POST` | `/api/v1/ai/workforce/optimize` | Bearer (Authenticated) | Optimize Workforce via AI Engine |
| `POST` | `/api/v1/ai/workforce/capacity-analysis` | Bearer (Authenticated) | Run AI Capacity Analysis |
| `POST` | `/api/v1/ai/workforce/run-mode` | Public (None) | Run AI Agent Mode |
| `GET` | `/api/v1/ai/workforce/dashboard/stats` | Public (None) | Get AI Agent Telemetry Dashboard Stats |
| `GET` | `/api/v1/ai/workforce/agents` | Public (None) | List all AI Agent Configurations |
| `PUT` | `/api/v1/ai/workforce/agents/{agent_key}` | Public (None) | Update AI Agent Config |
| `GET` | `/api/v1/ai-brain/workforce-insights` | Bearer (Authenticated) | Ai Brain Workforce Insights |
| `POST` | `/api/v1/ai-brain/workforce-insights` | Bearer (Authenticated) | AI Brain Workforce Insights Endpoint |
| `GET` | `/api/v1/ai-hub/workforce-insights` | Bearer (Authenticated) | Workforce Insights Overview |
| `POST` | `/api/v1/ai-hub/workforce-insights/analyze` | Bearer (Authenticated) | Analyze Workforce Utilization & Capacity |
| `GET` | `/api/v1/ai-hub/workforce-planning` | Bearer (Authenticated) | Workforce Planning Overview |
| `POST` | `/api/v1/ai-hub/workforce-planning/forecast` | Bearer (Authenticated) | Forecast Workforce Headcount Demand |
| `POST` | `/api/v1/ai-hub/workforce-planning/headcount` | Bearer (Authenticated) | Optimize Headcount and Budget Allocation |
| `GET` | `/api/v1/workforce-insights/workforce` | Bearer (Authenticated) | Get Workforce Summary |
| `GET` | `/api/v1/workforce-insights/` | Bearer (Authenticated) | Get Workforce Summary |
| `GET` | `/api/v1/workforce-insights` | Bearer (Authenticated) | Get Workforce Summary |
| `GET` | `/api/v1/workforce-insights/headcount` | Bearer (Authenticated) | Get Headcount Insights |
| `GET` | `/api/v1/workforce-insights/trends` | Bearer (Authenticated) | Get Workforce Trends |
| `POST` | `/api/v1/workforce-insights/dashboard` | Bearer (Authenticated) | Get Workforce Dashboard |
| `GET` | `/api/v1/workforce-insights/dashboard` | Bearer (Authenticated) | Workforce Insights Dashboard |
| `POST` | `/api/v1/workforce-insights/kpi` | Bearer (Authenticated) | Get Workforce Kpis |
| `GET` | `/api/v1/workforce-insights/kpi` | Bearer (Authenticated) | Workforce Insights KPIs |
| `POST` | `/api/v1/workforce-insights/headcount-trends` | Bearer (Authenticated) | Get Workforce Headcount Trends |
| `GET` | `/api/v1/workforce-insights/headcount-trends` | Bearer (Authenticated) | Workforce Headcount Trends |
| `POST` | `/api/v1/workforce-insights/department-comparison` | Bearer (Authenticated) | Get Workforce Department Comparison |
| `GET` | `/api/v1/workforce-insights/department-comparison` | Bearer (Authenticated) | Workforce Department Comparison |
| `POST` | `/api/v2/workforce/forecast` | Bearer (admin_or_manager, admin_or_manager) | Run AI workforce forecasting run |

### Recruitment (91 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/jobs` | Bearer (admin_or_hr) | Create a new job posting |
| `GET` | `/api/v1/jobs` | Bearer (Authenticated) | List all job postings |
| `GET` | `/api/v1/jobs/{id}` | Bearer (Authenticated) | Get job posting by ID |
| `PUT` | `/api/v1/jobs/{id}` | Bearer (admin_or_hr) | Update job posting |
| `DELETE` | `/api/v1/jobs/{id}` | Bearer (admin) | Delete a job posting |
| `GET` | `/api/v1/jobs/{id}/publish` | Bearer (recruiter_or_higher) | Get job publish channels |
| `POST` | `/api/v1/jobs/{id}/publish` | Bearer (recruiter_or_higher) | Publish job on a channel |
| `POST` | `/api/v1/jobs/{id}/close` | Bearer (admin_or_hr) | Close job posting |
| `POST` | `/api/v1/jobs/{id}/draft` | Bearer (admin_or_hr) | Draft job posting |
| `POST` | `/api/v1/jobs/{id}/duplicate` | Bearer (admin_or_hr) | Duplicate a job posting |
| `POST` | `/api/v1/jobs/generate-description` | Bearer (admin_or_hr) | Generate AI job description |
| `POST` | `/api/v1/jobs/ai-autofill` | Bearer (admin_or_hr) | One-click AI Auto-fill for Create Job |
| `POST` | `/api/v1/jobs/modify-description` | Bearer (admin_or_hr) | Modify AI job description |
| `GET` | `/api/v1/jobs/{id}/sourcing-link` | Bearer (recruiter_or_higher) | Get or auto-generate unique sourcing link |
| `GET` | `/api/v1/jobs/{id}/qr` | Bearer (recruiter_or_higher) | Generate QR code for the job application URL |
| `GET` | `/api/v1/jobs/{id}/applicants/export` | Bearer (recruiter_or_higher) | Export job applicants report |
| `GET` | `/api/v1/applications/stats` | Bearer (admin_or_hr_or_manager) | Get recruitment metrics dashboard |
| `GET` | `/api/v1/applications` | Bearer (admin_or_hr_or_manager) | List all applications |
| `GET` | `/api/v1/applications/{id}` | Bearer (admin_or_hr_or_manager) | Get application details |
| `PATCH` | `/api/v1/applications/{id}/shortlist` | Bearer (admin_or_hr) | Shortlist candidate |
| `PATCH` | `/api/v1/applications/{id}/reject` | Bearer (admin_or_hr) | Reject candidate |
| `PATCH` | `/api/v1/applications/{id}/hold` | Bearer (admin_or_hr) | Put candidate on hold |
| `PATCH` | `/api/v1/applications/{id}/stage` | Bearer (admin_or_hr) | Move application stage |
| `POST` | `/api/v1/applications/bulk-move` | Bearer (admin_or_hr) | Bulk move candidates |
| `POST` | `/api/v1/applications/bulk-tag` | Bearer (admin_or_hr) | Bulk tag candidates |
| `POST` | `/api/v1/applications/{id}/send-interview` | Bearer (admin_or_hr) | Initiate interview process |
| `POST` | `/api/v1/interviews/{id}/schedule` | Public (None) | Candidate books interview schedule slot |
| `GET` | `/api/v1/interviews` | Bearer (admin_or_hr) | List all interviews |
| `GET` | `/api/v1/interviews/{id}` | Bearer (admin_or_hr) | Get interview details |
| `PATCH` | `/api/v1/interviews/rounds/{round_id}/pass` | Bearer (admin_or_hr) | Pass interview round |
| `PATCH` | `/api/v1/interviews/rounds/{round_id}/reject` | Bearer (admin_or_hr) | Reject interview round |
| `PATCH` | `/api/v1/interviews/rounds/{round_id}/hold` | Bearer (admin_or_hr) | Hold interview round |
| `POST` | `/api/v1/applications/{id}/offer` | Bearer (admin_or_hr) | Create and release job offer |
| `POST` | `/api/v1/applications/{id}/convert` | Bearer (admin_or_hr) | Convert selected candidate to Employee record |
| `PATCH` | `/api/v1/offers/{id}/accept` | Public (None) | Candidate accepts offer |
| `PATCH` | `/api/v1/offers/{id}/reject` | Public (None) | Candidate rejects offer |
| `GET` | `/api/v1/offers` | Bearer (admin_or_hr) | List all offers with pagination |
| `GET` | `/api/v1/ai/analytics/recruitment` | Bearer (Authenticated) | Get Recruitment Intelligence |
| `GET` | `/api/v1/ai-insights/ats` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai-insights/recruitment` | Bearer (analytics_access) | Get Recruitment |
| `GET` | `/api/v1/ai/ats` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `POST` | `/api/v1/candidates` | Bearer (admin_or_hr) | Create a new candidate profile |
| `GET` | `/api/v1/candidates/{id}` | Bearer (admin_or_hr) | Retrieve candidate profile |
| `GET` | `/api/v1/candidates` | Bearer (admin_or_hr) | List candidates with pagination and filters |
| `PUT` | `/api/v1/candidates/{id}` | Bearer (admin_or_hr) | Update candidate profile |
| `DELETE` | `/api/v1/candidates/{id}` | Bearer (admin_or_hr) | Delete candidate profile |
| `POST` | `/api/v1/candidates/import` | Bearer (admin_or_hr) | Import candidates from CSV |
| `GET` | `/api/v1/candidates/export/csv` | Bearer (admin_or_hr) | Export candidates to CSV |
| `POST` | `/api/v1/requisitions` | Bearer (admin_or_hr) | Create a new job requisition |
| `POST` | `/api/v1/requisitions/{id}/approve` | Bearer (admin_or_hr) | Approve or reject a job requisition |
| `GET` | `/api/v1/requisitions/{id}` | Bearer (admin_or_hr) | Retrieve job requisition details |
| `GET` | `/api/v1/requisitions` | Bearer (admin_or_hr) | List job requisitions with status filter |
| `POST` | `/api/v1/vendors` | Bearer (admin_or_hr) | Create a recruitment vendor agency |
| `GET` | `/api/v1/vendors/{id}` | Bearer (admin_or_hr) | Retrieve recruitment vendor agency details |
| `GET` | `/api/v1/vendors` | Bearer (admin_or_hr) | List registered recruitment vendors |
| `PUT` | `/api/v1/vendors/{id}` | Bearer (admin_or_hr) | Update recruitment vendor agency |
| `DELETE` | `/api/v1/vendors/{id}` | Bearer (admin_or_hr) | Delete recruitment vendor agency |
| `POST` | `/api/v1/scorecards/templates` | Bearer (admin_or_hr) | Create scorecard template |
| `GET` | `/api/v1/scorecards/templates` | Bearer (admin_or_hr) | List scorecard templates |
| `POST` | `/api/v1/scorecards/submissions` | Bearer (admin_or_hr) | Submit interview scorecard |
| `GET` | `/api/v1/scorecards/submissions/{round_id}` | Bearer (admin_or_hr) | Get scorecards for an interview round |
| `GET` | `/api/v1/recruitment/analytics` | Bearer (admin_or_hr_or_manager) | Get recruitment funnel and pipeline analytics |
| `GET` | `/api/v1/recruitment/summary` | Bearer (admin_or_hr_or_manager) | Get recruitment summary |
| `GET` | `/api/v1/recruitment/dashboard` | Bearer (admin_or_hr_or_manager) | Get recruitment dashboard |
| `GET` | `/api/v1/recruitment/stats` | Bearer (admin_or_hr_or_manager) | Get recruitment stats |
| `GET` | `/api/v1/recruitment/notifications` | Bearer (admin_or_hr) | List recruiting notifications |
| `PUT` | `/api/v1/recruitment/notifications/{id}/read` | Bearer (admin_or_hr) | Mark notification as read |
| `POST` | `/api/v1/recruitment/resumes/upload` | Bearer (Authenticated) | Upload resume for automated AI screening & ATS matching (plural alias) |
| `POST` | `/api/v1/recruitment/resume/upload` | Bearer (Authenticated) | Upload resume for automated AI screening & ATS matching |
| `POST` | `/api/v1/recruitment/resumes/parse` | Bearer (Authenticated) | Direct raw resume text parsing & dry-run analysis |
| `GET` | `/api/v1/recruitment/candidates` | Bearer (Authenticated) | List all parsed candidates |
| `GET` | `/api/v1/recruitment/candidates/{candidate_id}` | Bearer (Authenticated) | Get complete candidate profile |
| `GET` | `/api/v1/recruitment/candidates/{candidate_id}/ats` | Bearer (Authenticated) | Get candidate ATS score breakdown & AI insights |
| `POST` | `/api/v1/recruitment/candidates/{candidate_id}/match/{job_id}` | Bearer (Authenticated) | Match a specific candidate against a target job description |
| `POST` | `/api/v1/recruitment/jobs/{job_id}/match` | Bearer (Authenticated) | Recalculate ATS scores & rankings for all candidates against job description |
| `POST` | `/api/v1/recruitment/jobs/generate-description` | Bearer (Authenticated) | Generate AI structured job description under recruitment prefix |
| `POST` | `/api/v1/recruitment/jobs/modify-description` | Bearer (Authenticated) | Modify AI structured job description under recruitment prefix |
| `GET` | `/api/v1/ats/candidates` | Bearer (Authenticated) | List ATS candidates (Alias) |
| `GET` | `/api/v1/ats` | Bearer (Authenticated) | List ATS candidates & pipeline entries |
| `GET` | `/api/v1/ats/board` | Bearer (Authenticated) | Get ATS hiring pipeline board (Alias) |
| `GET` | `/api/v1/ats/pipeline` | Bearer (Authenticated) | Get ATS hiring pipeline board |
| `GET` | `/api/v1/analytics/recruitment` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/recruiter/jobs` | Bearer (Authenticated) | List Jobs |
| `POST` | `/api/v1/recruiter/jobs` | Bearer (Authenticated) | Create Job |
| `GET` | `/api/v1/recruiter/candidates` | Bearer (Authenticated) | List Candidates |
| `POST` | `/api/v2/talent/match` | Bearer (admin_or_manager, admin_or_manager) | Match employee to internal opportunities |
| `POST` | `/api/v2/screening/jobs/{job_id}/run` | Bearer (admin_or_manager) | Trigger bulk AI screening run for a job |
| `GET` | `/api/v2/screening/jobs/{job_id}/results` | Bearer (admin_or_manager) | Get latest AI screening results per application for a job |
| `GET` | `/dashboard/recruitment` | Bearer (Authenticated) | Get Alternate Recruitment Dashboard |
| `GET` | `/api/v1/dashboard/recruitment` | Bearer (Authenticated) | Get Alternate Recruitment Dashboard |
| `GET` | `/analytics/recruitment` | Bearer (Authenticated) | Get Alternate Recruitment Dashboard |

### Onboarding (247 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/employees/{id}/onboarding-status` | Bearer (Authenticated) | Get onboarding checklist progress |
| `GET` | `/api/v1/managers/onboarding/validate` | Public (None) | Validate manager onboarding token |
| `POST` | `/api/v1/managers/onboarding/activate` | Public (None) | Activate invited manager account |
| `POST` | `/api/v1/managers/onboarding/complete` | Bearer (Authenticated) | Complete manager onboarding details |
| `GET` | `/api/v1/onboarding/status` | Public (None) | Get Onboarding Status |
| `GET` | `/api/v1/onboarding/progress` | Public (None) | Get Onboarding Progress |
| `PATCH` | `/api/v1/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `PUT` | `/api/v1/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `GET` | `/api/v1/onboarding/profile` | Public (None) | Get Admin Profile |
| `PUT` | `/api/v1/onboarding/profile` | Public (None) | Save Admin Profile |
| `POST` | `/api/v1/onboarding/profile` | Public (None) | Save Admin Profile |
| `GET` | `/api/v1/onboarding/organization` | Public (None) | Get Company Details |
| `GET` | `/api/v1/onboarding/company` | Public (None) | Get Company Details |
| `PUT` | `/api/v1/onboarding/organization` | Public (None) | Save Company Details |
| `POST` | `/api/v1/onboarding/organization` | Public (None) | Save Company Details |
| `PUT` | `/api/v1/onboarding/company` | Public (None) | Save Company Details |
| `POST` | `/api/v1/onboarding/company` | Public (None) | Save Company Details |
| `POST` | `/api/v1/onboarding/departments` | Public (None) | Create Department Or List |
| `GET` | `/api/v1/onboarding/departments` | Public (None) | List Departments |
| `GET` | `/api/v1/onboarding/departments/{department_id}` | Public (None) | Get Department |
| `PATCH` | `/api/v1/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `PUT` | `/api/v1/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `DELETE` | `/api/v1/onboarding/departments/{department_id}` | Public (None) | Delete Department |
| `POST` | `/api/v1/onboarding/designations` | Public (None) | Create Designation Or List |
| `GET` | `/api/v1/onboarding/designations` | Public (None) | List Designations |
| `GET` | `/api/v1/onboarding/designations/{designation_id}` | Public (None) | Get Designation |
| `PATCH` | `/api/v1/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `PUT` | `/api/v1/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `DELETE` | `/api/v1/onboarding/designations/{designation_id}` | Public (None) | Delete Designation |
| `GET` | `/api/v1/onboarding/work-schedule` | Public (None) | Get Hr Settings |
| `GET` | `/api/v1/onboarding/settings` | Public (None) | Get Hr Settings |
| `GET` | `/api/v1/onboarding/hr-settings` | Public (None) | Get Hr Settings |
| `PUT` | `/api/v1/onboarding/work-schedule` | Public (None) | Save Hr Settings |
| `POST` | `/api/v1/onboarding/work-schedule` | Public (None) | Save Hr Settings |
| `PUT` | `/api/v1/onboarding/settings` | Public (None) | Save Hr Settings |
| `POST` | `/api/v1/onboarding/settings` | Public (None) | Save Hr Settings |
| `PUT` | `/api/v1/onboarding/hr-settings` | Public (None) | Save Hr Settings |
| `POST` | `/api/v1/onboarding/hr-settings` | Public (None) | Save Hr Settings |
| `POST` | `/api/v1/onboarding/leave-policies` | Public (None) | Create Leave Policy |
| `GET` | `/api/v1/onboarding/leave-policies` | Public (None) | List Leave Policies |
| `GET` | `/api/v1/onboarding/leave-policies/{policy_id}` | Public (None) | Get Leave Policy |
| `PATCH` | `/api/v1/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `PUT` | `/api/v1/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `DELETE` | `/api/v1/onboarding/leave-policies/{policy_id}` | Public (None) | Delete Leave Policy |
| `POST` | `/api/v1/onboarding/invite-employee` | Public (None) | Send Individual Invitation |
| `POST` | `/api/v1/onboarding/invitations` | Public (None) | Send Individual Invitation |
| `POST` | `/api/v1/onboarding/invite-employees` | Public (None) | Invite Employees Batch Step |
| `GET` | `/api/v1/onboarding/invitations/pending` | Public (None) | List Pending Invitations |
| `GET` | `/api/v1/onboarding/invitations` | Public (None) | List Pending Invitations |
| `POST` | `/api/v1/onboarding/invitations/{invitation_id}/resend` | Public (None) | Resend Invitation |
| `DELETE` | `/api/v1/onboarding/invitations/{invitation_id}` | Public (None) | Cancel Invitation |
| `POST` | `/api/v1/onboarding/invitations/{invitation_id}/cancel` | Public (None) | Cancel Invitation |
| `GET` | `/api/v1/onboarding/organization/structure` | Public (None) | Get Organization Structure |
| `GET` | `/api/v1/onboarding/review` | Public (None) | Get Organization Structure |
| `GET` | `/api/v1/onboarding/structure` | Public (None) | Get Organization Structure |
| `POST` | `/api/v1/onboarding/complete` | Public (None) | Complete Onboarding |
| `POST` | `/api/v1/onboarding/upload` | Public (None) | Upload Onboarding Asset |
| `GET` | `/api/v1/onboarding/validate` | Public (None) | Validate employee onboarding token (canonical) |
| `GET` | `/api/v1/onboarding/validate-token` | Public (None) | Validate employee onboarding token |
| `POST` | `/api/v1/onboarding/activate` | Public (None) | Activate invited employee account |
| `GET` | `/api/v1/employee-onboarding/status` | Public (None) | Get Status |
| `GET` | `/api/v1/employee-onboarding/progress` | Public (None) | Get Progress |
| `PUT` | `/api/v1/employee-onboarding/step/1` | Public (None) | Save Step 1 |
| `PUT` | `/api/v1/employee-onboarding/step/2` | Public (None) | Save Step 2 |
| `PUT` | `/api/v1/employee-onboarding/step/3` | Public (None) | Save Step 3 |
| `PUT` | `/api/v1/employee-onboarding/step/4` | Public (None) | Save Step 4 |
| `PUT` | `/api/v1/employee-onboarding/step/5` | Public (None) | Save Step 5 |
| `PUT` | `/api/v1/employee-onboarding/step/6` | Public (None) | Save Step 6 |
| `PUT` | `/api/v1/employee-onboarding/step/7` | Public (None) | Save Step 7 |
| `POST` | `/api/v1/employee-onboarding/step/8/upload` | Public (None) | Upload Document |
| `DELETE` | `/api/v1/employee-onboarding/step/8/document/{doc_id}` | Public (None) | Delete Document |
| `PUT` | `/api/v1/employee-onboarding/step/8` | Public (None) | Save Step 8 |
| `PUT` | `/api/v1/employee-onboarding/step/9` | Public (None) | Save Step 9 |
| `POST` | `/api/v1/employee-onboarding/complete` | Public (None) | Complete Flow |
| `POST` | `/api/v1/employee-onboarding/draft` | Public (None) | Save Draft State |
| `GET` | `/api/v1/hr-admin/onboarding/profile` | Public (None) | Get HR Admin Profile |
| `PUT` | `/api/v1/hr-admin/onboarding/profile` | Public (None) | Update HR Admin Profile |
| `POST` | `/api/v1/hr-admin/onboarding/profile` | Public (None) | Create/Update HR Admin Profile |
| `GET` | `/api/v1/hr-admin/onboarding/company` | Public (None) | Get Company (Alias) |
| `GET` | `/api/v1/hr-admin/onboarding/organization` | Public (None) | Get Organization |
| `POST` | `/api/v1/hr-admin/onboarding/company` | Public (None) | Create Company (Alias) |
| `POST` | `/api/v1/hr-admin/onboarding/organization` | Public (None) | Create Organization |
| `PUT` | `/api/v1/hr-admin/onboarding/company` | Public (None) | Update Company (Alias) |
| `PATCH` | `/api/v1/hr-admin/onboarding/organization` | Public (None) | Patch Organization |
| `PUT` | `/api/v1/hr-admin/onboarding/organization` | Public (None) | Update Organization |
| `POST` | `/api/v1/hr-admin/onboarding/departments` | Public (None) | Create Department |
| `GET` | `/api/v1/hr-admin/onboarding/departments` | Public (None) | Get Departments |
| `GET` | `/api/v1/hr-admin/onboarding/departments/{department_id}` | Public (None) | Get Department by ID |
| `PATCH` | `/api/v1/hr-admin/onboarding/departments/{department_id}` | Public (None) | Patch Department |
| `PUT` | `/api/v1/hr-admin/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `DELETE` | `/api/v1/hr-admin/onboarding/departments/{department_id}` | Public (None) | Delete Department |
| `POST` | `/api/v1/hr-admin/onboarding/designations` | Public (None) | Create Designation |
| `GET` | `/api/v1/hr-admin/onboarding/designations` | Public (None) | Get Designations |
| `GET` | `/api/v1/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Get Designation by ID |
| `PATCH` | `/api/v1/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Patch Designation |
| `PUT` | `/api/v1/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `DELETE` | `/api/v1/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Delete Designation |
| `GET` | `/api/v1/hr-admin/onboarding/organization/structure` | Public (None) | Get Structure |
| `GET` | `/api/v1/hr-admin/onboarding/review` | Public (None) | Get Organization Review Structure |
| `GET` | `/api/v1/hr-admin/onboarding/structure` | Public (None) | Get Organization Structure |
| `GET` | `/api/v1/hr-admin/onboarding/work-schedule` | Public (None) | Get Work Schedule |
| `GET` | `/api/v1/hr-admin/onboarding/hr-settings` | Public (None) | Get HR Settings (Alias) |
| `GET` | `/api/v1/hr-admin/onboarding/settings` | Public (None) | Get HR Settings |
| `PUT` | `/api/v1/hr-admin/onboarding/work-schedule` | Public (None) | Update Work Schedule |
| `POST` | `/api/v1/hr-admin/onboarding/work-schedule` | Public (None) | Save Work Schedule |
| `PUT` | `/api/v1/hr-admin/onboarding/hr-settings` | Public (None) | Update HR Settings (Alias) |
| `POST` | `/api/v1/hr-admin/onboarding/hr-settings` | Public (None) | Save HR Settings (Alias) |
| `PUT` | `/api/v1/hr-admin/onboarding/settings` | Public (None) | Update HR Settings |
| `POST` | `/api/v1/hr-admin/onboarding/settings` | Public (None) | Save HR Settings |
| `POST` | `/api/v1/hr-admin/onboarding/leave-policies` | Public (None) | Create Leave Policy |
| `GET` | `/api/v1/hr-admin/onboarding/leave-policies` | Public (None) | Get Leave Policies |
| `GET` | `/api/v1/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Get Leave Policy by ID |
| `PATCH` | `/api/v1/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Patch Leave Policy |
| `PUT` | `/api/v1/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `DELETE` | `/api/v1/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Delete Leave Policy |
| `POST` | `/api/v1/hr-admin/onboarding/invite-employee` | Public (None) | Send Invitation (Alias) |
| `POST` | `/api/v1/hr-admin/onboarding/invitations` | Public (None) | Send Individual Invitation |
| `GET` | `/api/v1/hr-admin/onboarding/invitations/pending` | Public (None) | Get Pending Invitations |
| `GET` | `/api/v1/hr-admin/onboarding/invitations` | Public (None) | Get Invitations |
| `POST` | `/api/v1/hr-admin/onboarding/invitations/{invitation_id}/resend` | Public (None) | Resend Invitation |
| `DELETE` | `/api/v1/hr-admin/onboarding/invitations/{invitation_id}` | Public (None) | Cancel Invitation (Delete Alias) |
| `POST` | `/api/v1/hr-admin/onboarding/invitations/{invitation_id}/cancel` | Public (None) | Cancel Invitation |
| `GET` | `/api/v1/hr-admin/onboarding/status` | Public (None) | Get Onboarding Status |
| `GET` | `/api/v1/hr-admin/onboarding/` | Public (None) | Get Onboarding Data Slash |
| `GET` | `/api/v1/hr-admin/onboarding` | Public (None) | Get Onboarding Data Root |
| `GET` | `/api/v1/hr-admin/onboarding/progress` | Public (None) | Get All Onboarding Progress |
| `PATCH` | `/api/v1/hr-admin/onboarding/progress` | Public (None) | Patch Onboarding Progress |
| `PUT` | `/api/v1/hr-admin/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `POST` | `/api/v1/hr-admin/onboarding/complete` | Public (None) | Complete Onboarding & Activate Workspace |
| `POST` | `/api/v1/hr-admin/onboarding/upload` | Public (None) | Upload Onboarding Asset File |
| `POST` | `/api/v1/hr-admin/onboarding/` | Public (None) | Save Onboarding Wizard Slash |
| `POST` | `/api/v1/hr-admin/onboarding` | Public (None) | Save Onboarding Wizard |
| `POST` | `/api/v1/hr-admin/onboarding/step/{step_index}` | Public (None) | Save Step by Index |
| `GET` | `/onboarding/status` | Public (None) | Get Onboarding Status |
| `GET` | `/onboarding/progress` | Public (None) | Get Onboarding Progress |
| `PATCH` | `/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `PUT` | `/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `GET` | `/onboarding/profile` | Public (None) | Get Admin Profile |
| `PUT` | `/onboarding/profile` | Public (None) | Save Admin Profile |
| `POST` | `/onboarding/profile` | Public (None) | Save Admin Profile |
| `GET` | `/onboarding/organization` | Public (None) | Get Company Details |
| `GET` | `/onboarding/company` | Public (None) | Get Company Details |
| `PUT` | `/onboarding/organization` | Public (None) | Save Company Details |
| `POST` | `/onboarding/organization` | Public (None) | Save Company Details |
| `PUT` | `/onboarding/company` | Public (None) | Save Company Details |
| `POST` | `/onboarding/company` | Public (None) | Save Company Details |
| `POST` | `/onboarding/departments` | Public (None) | Create Department Or List |
| `GET` | `/onboarding/departments` | Public (None) | List Departments |
| `GET` | `/onboarding/departments/{department_id}` | Public (None) | Get Department |
| `PATCH` | `/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `PUT` | `/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `DELETE` | `/onboarding/departments/{department_id}` | Public (None) | Delete Department |
| `POST` | `/onboarding/designations` | Public (None) | Create Designation Or List |
| `GET` | `/onboarding/designations` | Public (None) | List Designations |
| `GET` | `/onboarding/designations/{designation_id}` | Public (None) | Get Designation |
| `PATCH` | `/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `PUT` | `/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `DELETE` | `/onboarding/designations/{designation_id}` | Public (None) | Delete Designation |
| `GET` | `/onboarding/work-schedule` | Public (None) | Get Hr Settings |
| `GET` | `/onboarding/settings` | Public (None) | Get Hr Settings |
| `GET` | `/onboarding/hr-settings` | Public (None) | Get Hr Settings |
| `PUT` | `/onboarding/work-schedule` | Public (None) | Save Hr Settings |
| `POST` | `/onboarding/work-schedule` | Public (None) | Save Hr Settings |
| `PUT` | `/onboarding/settings` | Public (None) | Save Hr Settings |
| `POST` | `/onboarding/settings` | Public (None) | Save Hr Settings |
| `PUT` | `/onboarding/hr-settings` | Public (None) | Save Hr Settings |
| `POST` | `/onboarding/hr-settings` | Public (None) | Save Hr Settings |
| `POST` | `/onboarding/leave-policies` | Public (None) | Create Leave Policy |
| `GET` | `/onboarding/leave-policies` | Public (None) | List Leave Policies |
| `GET` | `/onboarding/leave-policies/{policy_id}` | Public (None) | Get Leave Policy |
| `PATCH` | `/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `PUT` | `/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `DELETE` | `/onboarding/leave-policies/{policy_id}` | Public (None) | Delete Leave Policy |
| `POST` | `/onboarding/invite-employee` | Public (None) | Send Individual Invitation |
| `POST` | `/onboarding/invitations` | Public (None) | Send Individual Invitation |
| `POST` | `/onboarding/invite-employees` | Public (None) | Invite Employees Batch Step |
| `GET` | `/onboarding/invitations/pending` | Public (None) | List Pending Invitations |
| `GET` | `/onboarding/invitations` | Public (None) | List Pending Invitations |
| `POST` | `/onboarding/invitations/{invitation_id}/resend` | Public (None) | Resend Invitation |
| `DELETE` | `/onboarding/invitations/{invitation_id}` | Public (None) | Cancel Invitation |
| `POST` | `/onboarding/invitations/{invitation_id}/cancel` | Public (None) | Cancel Invitation |
| `GET` | `/onboarding/organization/structure` | Public (None) | Get Organization Structure |
| `GET` | `/onboarding/review` | Public (None) | Get Organization Structure |
| `GET` | `/onboarding/structure` | Public (None) | Get Organization Structure |
| `POST` | `/onboarding/complete` | Public (None) | Complete Onboarding |
| `POST` | `/onboarding/upload` | Public (None) | Upload Onboarding Asset |
| `GET` | `/onboarding/validate` | Public (None) | Validate employee onboarding token (canonical) |
| `GET` | `/onboarding/validate-token` | Public (None) | Validate employee onboarding token |
| `POST` | `/onboarding/activate` | Public (None) | Activate invited employee account |
| `GET` | `/hr-admin/onboarding/profile` | Public (None) | Get HR Admin Profile |
| `PUT` | `/hr-admin/onboarding/profile` | Public (None) | Update HR Admin Profile |
| `POST` | `/hr-admin/onboarding/profile` | Public (None) | Create/Update HR Admin Profile |
| `GET` | `/hr-admin/onboarding/company` | Public (None) | Get Company (Alias) |
| `GET` | `/hr-admin/onboarding/organization` | Public (None) | Get Organization |
| `POST` | `/hr-admin/onboarding/company` | Public (None) | Create Company (Alias) |
| `POST` | `/hr-admin/onboarding/organization` | Public (None) | Create Organization |
| `PUT` | `/hr-admin/onboarding/company` | Public (None) | Update Company (Alias) |
| `PATCH` | `/hr-admin/onboarding/organization` | Public (None) | Patch Organization |
| `PUT` | `/hr-admin/onboarding/organization` | Public (None) | Update Organization |
| `POST` | `/hr-admin/onboarding/departments` | Public (None) | Create Department |
| `GET` | `/hr-admin/onboarding/departments` | Public (None) | Get Departments |
| `GET` | `/hr-admin/onboarding/departments/{department_id}` | Public (None) | Get Department by ID |
| `PATCH` | `/hr-admin/onboarding/departments/{department_id}` | Public (None) | Patch Department |
| `PUT` | `/hr-admin/onboarding/departments/{department_id}` | Public (None) | Update Department |
| `DELETE` | `/hr-admin/onboarding/departments/{department_id}` | Public (None) | Delete Department |
| `POST` | `/hr-admin/onboarding/designations` | Public (None) | Create Designation |
| `GET` | `/hr-admin/onboarding/designations` | Public (None) | Get Designations |
| `GET` | `/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Get Designation by ID |
| `PATCH` | `/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Patch Designation |
| `PUT` | `/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Update Designation |
| `DELETE` | `/hr-admin/onboarding/designations/{designation_id}` | Public (None) | Delete Designation |
| `GET` | `/hr-admin/onboarding/organization/structure` | Public (None) | Get Structure |
| `GET` | `/hr-admin/onboarding/review` | Public (None) | Get Organization Review Structure |
| `GET` | `/hr-admin/onboarding/structure` | Public (None) | Get Organization Structure |
| `GET` | `/hr-admin/onboarding/work-schedule` | Public (None) | Get Work Schedule |
| `GET` | `/hr-admin/onboarding/hr-settings` | Public (None) | Get HR Settings (Alias) |
| `GET` | `/hr-admin/onboarding/settings` | Public (None) | Get HR Settings |
| `PUT` | `/hr-admin/onboarding/work-schedule` | Public (None) | Update Work Schedule |
| `POST` | `/hr-admin/onboarding/work-schedule` | Public (None) | Save Work Schedule |
| `PUT` | `/hr-admin/onboarding/hr-settings` | Public (None) | Update HR Settings (Alias) |
| `POST` | `/hr-admin/onboarding/hr-settings` | Public (None) | Save HR Settings (Alias) |
| `PUT` | `/hr-admin/onboarding/settings` | Public (None) | Update HR Settings |
| `POST` | `/hr-admin/onboarding/settings` | Public (None) | Save HR Settings |
| `POST` | `/hr-admin/onboarding/leave-policies` | Public (None) | Create Leave Policy |
| `GET` | `/hr-admin/onboarding/leave-policies` | Public (None) | Get Leave Policies |
| `GET` | `/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Get Leave Policy by ID |
| `PATCH` | `/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Patch Leave Policy |
| `PUT` | `/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Update Leave Policy |
| `DELETE` | `/hr-admin/onboarding/leave-policies/{policy_id}` | Public (None) | Delete Leave Policy |
| `POST` | `/hr-admin/onboarding/invite-employee` | Public (None) | Send Invitation (Alias) |
| `POST` | `/hr-admin/onboarding/invitations` | Public (None) | Send Individual Invitation |
| `GET` | `/hr-admin/onboarding/invitations/pending` | Public (None) | Get Pending Invitations |
| `GET` | `/hr-admin/onboarding/invitations` | Public (None) | Get Invitations |
| `POST` | `/hr-admin/onboarding/invitations/{invitation_id}/resend` | Public (None) | Resend Invitation |
| `DELETE` | `/hr-admin/onboarding/invitations/{invitation_id}` | Public (None) | Cancel Invitation (Delete Alias) |
| `POST` | `/hr-admin/onboarding/invitations/{invitation_id}/cancel` | Public (None) | Cancel Invitation |
| `GET` | `/hr-admin/onboarding/status` | Public (None) | Get Onboarding Status |
| `GET` | `/hr-admin/onboarding/` | Public (None) | Get Onboarding Data Slash |
| `GET` | `/hr-admin/onboarding` | Public (None) | Get Onboarding Data Root |
| `GET` | `/hr-admin/onboarding/progress` | Public (None) | Get All Onboarding Progress |
| `PATCH` | `/hr-admin/onboarding/progress` | Public (None) | Patch Onboarding Progress |
| `PUT` | `/hr-admin/onboarding/progress` | Public (None) | Save Onboarding Progress |
| `POST` | `/hr-admin/onboarding/complete` | Public (None) | Complete Onboarding & Activate Workspace |
| `POST` | `/hr-admin/onboarding/upload` | Public (None) | Upload Onboarding Asset File |
| `POST` | `/hr-admin/onboarding/` | Public (None) | Save Onboarding Wizard Slash |
| `POST` | `/hr-admin/onboarding` | Public (None) | Save Onboarding Wizard |
| `POST` | `/hr-admin/onboarding/step/{step_index}` | Public (None) | Save Step by Index |

### Attendance (64 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/timesheets/weekly` | Bearer (Authenticated) | Get or create weekly timesheet for current employee |
| `POST` | `/api/v1/timesheets/weekly` | Bearer (Authenticated) | Save weekly timesheet entries |
| `POST` | `/api/v1/timesheets/weekly/submit` | Bearer (Authenticated) | Submit weekly timesheet for approval |
| `GET` | `/api/v1/timesheets/history` | Bearer (Authenticated) | Get timesheet history for current employee |
| `GET` | `/api/v1/timesheets/pending` | Bearer (Authenticated) | Get all timesheets pending approval |
| `POST` | `/api/v1/timesheets/{timesheet_id}/review` | Bearer (Authenticated) | Approve or reject a timesheet |
| `GET` | `/api/v1/attendance/face/status` | Bearer (Authenticated) | Get Face Status |
| `GET` | `/api/v1/attendance/face-status` | Bearer (Authenticated) | Check if current employee face is enrolled |
| `POST` | `/api/v1/attendance/face/enroll` | Bearer (Authenticated) | Face Enroll |
| `POST` | `/api/v1/attendance/face-enroll` | Bearer (Authenticated) | Register employee face embedding for attendance |
| `POST` | `/api/v1/attendance/face/checkin` | Bearer (Authenticated) | Ai Face Check In |
| `POST` | `/api/v1/attendance/checkin` | Bearer (Authenticated) | Ai Face Check In |
| `POST` | `/api/v1/attendance/face/check-in` | Bearer (Authenticated) | Record daily attendance check-in with real face matching (JSON or multipart) |
| `POST` | `/api/v1/attendance/face/checkout` | Bearer (Authenticated) | Ai Face Check Out |
| `POST` | `/api/v1/attendance/checkout` | Bearer (Authenticated) | Ai Face Check Out |
| `POST` | `/api/v1/attendance/face/check-out` | Bearer (Authenticated) | Record daily attendance check-out with real face matching (JSON or multipart) |
| `GET` | `/api/v1/attendance/face/me` | Bearer (Authenticated) | Get today's real attendance, shift, break, and biometric status for current employee |
| `GET` | `/api/v1/attendance/face/history` | Bearer (Authenticated) | Retrieve paginated daily attendance logs history with date and employee filtering |
| `GET` | `/api/v1/attendance/face/team` | Bearer (admin_or_manager) | Retrieve direct report employees' daily attendance logs history |
| `GET` | `/api/v1/attendance/face/company` | Bearer (admin) | Retrieve company-wide paginated daily attendance logs history |
| `GET` | `/api/v1/attendance/face/analytics` | Bearer (admin_or_manager) | Retrieve attendance dashboard analytics summary (Admin and Managers) |
| `POST` | `/api/v1/attendance/break/start` | Bearer (Authenticated) | Start an attendance break session |
| `POST` | `/api/v1/attendance/break/end` | Bearer (Authenticated) | End the currently active attendance break session |
| `POST` | `/api/v1/attendance/geofence/verify` | Bearer (Authenticated) | Independently verify employee GPS coordinates against authorized office boundary |
| `GET` | `/api/v1/ai/attendance/dashboard` | Bearer (Authenticated) | Get AI Attendance Dashboard KPIs |
| `GET` | `/api/v1/ai/attendance/trend` | Bearer (Authenticated) | Get Attendance Trend Chart Data |
| `GET` | `/api/v1/ai/attendance/late-arrivals` | Bearer (Authenticated) | Get Late Arrival Detection Data |
| `GET` | `/api/v1/ai/attendance/anomalies` | Bearer (Authenticated) | Get Attendance Anomaly Detection Results |
| `GET` | `/api/v1/ai/attendance/absence-pattern` | Bearer (Authenticated) | Get AI Absence Pattern Insights |
| `GET` | `/api/v1/ai/attendance/overtime` | Bearer (Authenticated) | Get Overtime Tracking Metrics |
| `GET` | `/api/v1/ai/attendance/shift-violations` | Bearer (Authenticated) | Get Shift Violation Detection Data |
| `GET` | `/api/v1/ai/attendance/health-score` | Bearer (Authenticated) | Get Composite Attendance Health Score |
| `GET` | `/api/v1/ai/attendance/watchlist` | Bearer (Authenticated) | Get Absentee Watchlist |
| `GET` | `/api/v1/ai-insights/attendance` | Bearer (analytics_access) | Get Attendance |
| `GET` | `/api/v1/exports/attendance` | Bearer (export_permission) | Export Attendance |
| `GET` | `/api/v1/ai-hub/attendance-monitor` | Bearer (Authenticated) | Attendance Monitor Overview |
| `POST` | `/api/v1/ai-hub/attendance-monitor/analyze` | Bearer (Authenticated) | Analyze Attendance Range and Trends |
| `GET` | `/api/v1/ai-hub/attendance-monitor/anomalies` | Bearer (Authenticated) | List Attendance Anomalies (Paginated) |
| `GET` | `/api/v1/attendance/me` | Bearer (Authenticated) | Get My Attendance |
| `GET` | `/api/v1/attendance/status` | Bearer (Authenticated) | Get Attendance Status |
| `GET` | `/api/v1/attendance/today` | Bearer (Authenticated) | Get Today Company Attendance |
| `GET` | `/api/v1/attendance/history` | Bearer (Authenticated) | Get Attendance History |
| `GET` | `/api/v1/attendance/team` | Bearer (Authenticated) | Get Team Attendance |
| `GET` | `/api/v1/attendance/company` | Bearer (Authenticated) | Get Company Attendance |
| `GET` | `/api/v1/attendance/records` | Bearer (Authenticated) | Get All Records |
| `GET` | `/api/v1/attendance/summary` | Bearer (Authenticated) | Get Attendance Analytics |
| `GET` | `/api/v1/attendance/analytics` | Bearer (Authenticated) | Get Attendance Analytics |
| `GET` | `/api/v1/attendance/calendar` | Bearer (Authenticated) | Get Attendance Calendar |
| `GET` | `/api/v1/attendance/late` | Bearer (Authenticated) | Get Late Records |
| `GET` | `/api/v1/attendance/early-leaving` | Bearer (Authenticated) | Get Early Leaving Records |
| `GET` | `/api/v1/attendance/missing` | Bearer (Authenticated) | Get Missing Punch Records |
| `GET` | `/api/v1/attendance/overtime` | Bearer (Authenticated) | Get Overtime Records |
| `GET` | `/api/v1/attendance/export` | Bearer (Authenticated) | Export Attendance |
| `POST` | `/api/v1/attendance/check-in` | Bearer (Authenticated) | Check In |
| `POST` | `/api/v1/attendance/check-out` | Bearer (Authenticated) | Check Out |
| `PATCH` | `/api/v1/attendance/{attendance_id}` | Bearer (Authenticated) | Update Attendance Record |
| `PUT` | `/api/v1/attendance/{attendance_id}` | Bearer (Authenticated) | Update Attendance Record |
| `DELETE` | `/api/v1/attendance/{attendance_id}` | Bearer (Authenticated) | Delete Attendance Record |
| `GET` | `/api/v1/attendance/regularization` | Bearer (Authenticated) | List Regularization Requests |
| `POST` | `/api/v1/attendance/regularization` | Bearer (Authenticated) | Create Regularization Request |
| `GET` | `/api/v1/analytics/attendance` | Bearer (Authenticated) | Get Attendance Metric |
| `GET` | `/api/v1/settings/attendance` | Bearer (Authenticated) | Get Settings Section |
| `PUT` | `/api/v1/settings/attendance` | Bearer (Authenticated) | Update Settings Section Endpoint |
| `GET` | `/api/v1/reports/attendance` | Bearer (Authenticated) | Get Attendance Report |

### Leave (29 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/leaves/balances` | Bearer (Authenticated) | Get current employee's leave balances |
| `POST` | `/api/v1/leaves/apply` | Bearer (Authenticated) | Apply for leave |
| `GET` | `/api/v1/leaves/history` | Bearer (Authenticated) | Get leave history for current employee |
| `GET` | `/api/v1/leaves/pending` | Bearer (Authenticated) | Get all leaves pending approval |
| `POST` | `/api/v1/leaves/{leave_id}/review` | Bearer (Authenticated) | Approve or reject a leave request |
| `GET` | `/api/v1/leaves/balances/{employee_id}` | Bearer (Authenticated) | Get leave balances for a specific employee (Admin/Manager only) |
| `GET` | `/api/v1/ai/leave/dashboard` | Bearer (Authenticated) | Get AI Leave Assistant Dashboard KPIs |
| `GET` | `/api/v1/ai/leave/forecast` | Bearer (Authenticated) | Get Leave Forecast |
| `GET` | `/api/v1/ai/leave/distribution` | Bearer (Authenticated) | Get Leave Type Distribution |
| `GET` | `/api/v1/ai/leave/approval-suggestions` | Bearer (Authenticated) | Get AI Leave Approval Suggestions |
| `GET` | `/api/v1/ai/leave/conflicts` | Bearer (Authenticated) | Get Leave Conflict Detections |
| `GET` | `/api/v1/ai/leave/team-availability` | Bearer (Authenticated) | Get Team Availability Analysis |
| `GET` | `/api/v1/ai/leave/trends` | Bearer (Authenticated) | Get Leave Trends |
| `GET` | `/api/v1/ai/leave/analytics` | Bearer (Authenticated) | Get Leave Analytics Overview |
| `GET` | `/api/v1/ai/leave/request/{leave_request_id}` | Bearer (Authenticated) | Get Leave Request Details |
| `POST` | `/api/v1/ai/leave/analyze` | Bearer (Authenticated) | Analyze Leave Request via AI |
| `POST` | `/api/v1/ai/leave/forecast` | Bearer (Authenticated) | Generate AI Leave Demand Forecast |
| `POST` | `/api/v1/ai/leave/generate-suggestions` | Bearer (Authenticated) | Generate AI Approval Suggestions |
| `POST` | `/api/v1/ai/leave/detect-conflicts` | Bearer (Authenticated) | Detect Leave Conflicts via AI |
| `GET` | `/api/v1/exports/leaves` | Bearer (export_permission) | Export Leaves |
| `GET` | `/api/v1/ai-hub/leave-assistant` | Bearer (Authenticated) | Leave Assistant Overview |
| `POST` | `/api/v1/ai-hub/leave-assistant/analyze` | Bearer (Authenticated) | Analyze Department-wide Leave Patterns |
| `POST` | `/api/v1/ai-hub/leave-assistant/forecast` | Bearer (Authenticated) | Forecast Upcoming Leave Demand |
| `GET` | `/api/v1/leave-assistant/` | Public (None) | Get Leave Assistant Status |
| `GET` | `/api/v1/leave-assistant` | Public (None) | Get Leave Assistant Status |
| `POST` | `/api/v1/leave-assistant/query` | Bearer (Authenticated) | Query Leave Assistant |
| `POST` | `/api/v1/leave-assistant/apply` | Bearer (Authenticated) | Apply Leave Natural Language |
| `GET` | `/api/v1/leave-assistant/history` | Bearer (Authenticated) | Get Leave Query History |
| `GET` | `/api/v2/hr-analytics/leaves/analytics` | Bearer (admin_or_manager) | Get unified leave assistant analytics and conflict metrics |

### Payroll (388 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ai/payroll/dashboard` | Bearer (Authenticated) | Get AI Payroll Insights Dashboard KPIs |
| `GET` | `/api/v1/ai/payroll/forecast` | Bearer (Authenticated) | Get Payroll Forecast |
| `GET` | `/api/v1/ai/payroll/cost-analysis` | Bearer (Authenticated) | Get Payroll Cost Analysis |
| `GET` | `/api/v1/ai/payroll/cost-by-department` | Bearer (Authenticated) | Get Cost By Department |
| `GET` | `/api/v1/ai/payroll/benchmarking` | Bearer (Authenticated) | Get Salary Benchmarking Analysis |
| `GET` | `/api/v1/ai/payroll/anomalies` | Bearer (Authenticated) | Get Payroll Anomaly Detections |
| `GET` | `/api/v1/ai/payroll/fraud-detection` | Bearer (Authenticated) | Get Payroll Fraud Flags |
| `GET` | `/api/v1/ai/payroll/health-score` | Bearer (Authenticated) | Get Payroll Health Index |
| `GET` | `/api/v1/ai/payroll/analytics` | Bearer (Authenticated) | Get Payroll Analytics Overview |
| `GET` | `/api/v1/ai/payroll/employee/{employee_id}` | Bearer (Authenticated) | Get Employee Payroll Details |
| `POST` | `/api/v1/ai/payroll/forecast` | Bearer (Authenticated) | Generate AI Payroll Forecast |
| `POST` | `/api/v1/ai/payroll/analyze` | Bearer (Authenticated) | Analyze Payroll Run via AI |
| `POST` | `/api/v1/ai/payroll/detect-anomalies` | Bearer (Authenticated) | Detect Payroll Anomalies via AI |
| `POST` | `/api/v1/ai/payroll/detect-fraud` | Bearer (Authenticated) | Detect Payroll Fraud via AI |
| `GET` | `/api/v1/payroll/employees/{employeeId}/payslips` | Bearer (Authenticated) | Get payslips for employee (v1) |
| `GET` | `/api/v1/payroll/my-payslips` | Bearer (Authenticated) | Get current employee payslips (v1) |
| `GET` | `/api/v1/payroll/periods` | Bearer (Authenticated) | List payroll periods (v1) |
| `POST` | `/api/v1/payroll/periods` | Bearer (Authenticated) | Create payroll period (v1) |
| `GET` | `/api/v1/payroll/periods/{periodId}` | Bearer (Authenticated) | Get payroll period by ID (v1) |
| `POST` | `/api/v1/payroll/run` | Bearer (Authenticated) | Trigger/create payroll run (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}` | Bearer (Authenticated) | Get payroll run by ID (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/approve` | Bearer (Authenticated) | Approve payroll run (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/cancel` | Bearer (Authenticated) | Cancel payroll run (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/employees` | Bearer (Authenticated) | Get employees for payroll run (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/employees/{employeeId}` | Bearer (Authenticated) | Get single employee payroll run details (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/employees/{employeeId}/payslip/download` | Bearer (Authenticated) | Download payslip file (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/finalize` | Bearer (Authenticated) | Finalize payroll run (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/payslips/generate` | Bearer (Authenticated) | Trigger batch payslips generation (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/preview` | Bearer (Authenticated) | Preview payroll run summary (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/reject` | Bearer (Authenticated) | Reject payroll run (v1) |
| `POST` | `/api/v1/payroll/runs/{runId}/retry` | Bearer (Authenticated) | Retry failed payroll run (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/status` | Bearer (Authenticated) | Get payroll run status or async job status (v1) |
| `GET` | `/api/v1/payroll/runs/{runId}/validation` | Bearer (Authenticated) | Get payroll run validation details (v1) |
| `GET` | `/api/v1/payroll/cycles` | Bearer (Authenticated) | List all payroll cycles |
| `GET` | `/api/v1/payroll/cycles/logs` | Bearer (Authenticated) | Get payroll cycle audit logs |
| `GET` | `/api/v1/payroll/cycles/history` | Bearer (Authenticated) | Get payroll cycle history |
| `GET` | `/api/v1/payroll/cycles/{cycle_id}` | Bearer (Authenticated) | Get single payroll cycle details |
| `POST` | `/api/v1/payroll/cycles` | Bearer (Authenticated) | Create new payroll cycle |
| `PATCH` | `/api/v1/payroll/cycles/{cycle_id}` | Bearer (Authenticated) | Partial update payroll cycle |
| `PUT` | `/api/v1/payroll/cycles/{cycle_id}` | Bearer (Authenticated) | Update payroll cycle |
| `DELETE` | `/api/v1/payroll/cycles/{cycle_id}` | Bearer (Authenticated) | Delete payroll cycle |
| `POST` | `/api/v1/payroll/cycles/{cycle_id}/activate` | Bearer (Authenticated) | Activate payroll cycle |
| `POST` | `/api/v1/payroll/cycles/{cycle_id}/lock` | Bearer (Authenticated) | Lock payroll cycle |
| `POST` | `/api/v1/payroll/cycles/{cycle_id}/unlock` | Bearer (Authenticated) | Unlock payroll cycle |
| `POST` | `/api/v1/payroll/cycles/{cycle_id}/duplicate` | Bearer (Authenticated) | Duplicate payroll cycle |
| `POST` | `/api/v1/payroll/cycles/{cycle_id}/archive` | Bearer (Authenticated) | Archive payroll cycle |
| `GET` | `/api/v1/payroll/salary-processing` | Bearer (Authenticated) | Get salary processing list |
| `GET` | `/api/v1/payroll/salary-processing/hero` | Bearer (Authenticated) | Get salary processing hero card metrics |
| `GET` | `/api/v1/payroll/salary-processing/kpis` | Bearer (Authenticated) | Get payroll health KPIs |
| `GET` | `/api/v1/payroll/salary-processing/approval-workflow` | Bearer (Authenticated) | Get approval workflow |
| `GET` | `/api/v1/payroll/salary-processing/ai-insights` | Bearer (Authenticated) | Get AI insights |
| `GET` | `/api/v1/payroll/salary-processing/validations` | Bearer (Authenticated) | Get validation panel error items |
| `GET` | `/api/v1/payroll/salary-processing/analytics` | Bearer (Authenticated) | Get analytics |
| `POST` | `/api/v1/payroll/salary-processing/run` | Bearer (Authenticated) | Trigger payroll run |
| `POST` | `/api/v1/payroll/salary-processing/approve` | Bearer (Authenticated) | Approve salary processing run |
| `POST` | `/api/v1/payroll/salary-processing/rollback` | Bearer (Authenticated) | Rollback salary processing run |
| `POST` | `/api/v1/payroll/salary-processing/recalculate/{employee_id}` | Bearer (Authenticated) | Recalculate salary |
| `POST` | `/api/v1/payroll/salary-processing/resolve-exception/{exception_id}` | Bearer (Authenticated) | Resolve exception |
| `POST` | `/api/v1/payroll/salary-processing/auto-fix` | Bearer (Authenticated) | Auto-fix validation issues |
| `POST` | `/api/v1/payroll/salary-processing/batch-payout` | Bearer (Authenticated) | Batch payout |
| `POST` | `/api/v1/payroll/salary-processing/batch-approve` | Bearer (Authenticated) | Batch approve |
| `POST` | `/api/v1/payroll/salary-processing/batch-recalculate` | Bearer (Authenticated) | Batch recalculate |
| `POST` | `/api/v1/payroll/salary-processing/payslips` | Bearer (Authenticated) | Batch generate payslips |
| `POST` | `/api/v1/payroll/salary-processing/bank-transfer` | Bearer (Authenticated) | Initiate bank transfer |
| `POST` | `/api/v1/payroll/salary-processing/export` | Bearer (Authenticated) | Export salary processing data |
| `GET` | `/api/v1/payroll/employees/{employee_id}/salary-structure` | Bearer (Authenticated) | Get employee salary structure |
| `GET` | `/api/v1/payroll/salary-structures` | Bearer (Authenticated) | List all salary structures |
| `GET` | `/api/v1/payroll/salary-structures/audit` | Bearer (Authenticated) | Get salary structures audit log |
| `GET` | `/api/v1/payroll/salary-structures/ai-insights` | Bearer (Authenticated) | Get salary structure AI insights |
| `GET` | `/api/v1/payroll/salary-structures/{structure_id}` | Bearer (Authenticated) | Get salary structure by ID |
| `POST` | `/api/v1/payroll/salary-structures` | Bearer (Authenticated) | Create new salary structure |
| `PUT` | `/api/v1/payroll/salary-structures/{structure_id}` | Bearer (Authenticated) | Update salary structure |
| `POST` | `/api/v1/payroll/salary-structures/{structure_id}/clone` | Bearer (Authenticated) | Clone salary structure |
| `POST` | `/api/v1/payroll/salary-structures/{structure_id}/assign` | Bearer (Authenticated) | Assign salary structure |
| `POST` | `/api/v1/payroll/salary-structures/{structure_id}/approve` | Bearer (Authenticated) | Approve salary structure |
| `POST` | `/api/v1/payroll/salary-structures/{structure_id}/rollback` | Bearer (Authenticated) | Rollback salary structure version |
| `GET` | `/api/v1/payroll/payslips` | Bearer (Authenticated) | List payslips |
| `GET` | `/api/v1/payroll/payslips/{payslip_id}/preview` | Bearer (Authenticated) | Get single payslip preview data |
| `POST` | `/api/v1/payroll/payslips/bulk-generate` | Bearer (Authenticated) | Bulk generate payslips |
| `POST` | `/api/v1/payroll/payslips/bulk-email` | Bearer (Authenticated) | Bulk email payslips |
| `POST` | `/api/v1/payroll/payslips/bulk-download` | Bearer (Authenticated) | Bulk download payslips ZIP |
| `GET` | `/api/v1/payroll/payslips/{payslip_id}/pdf` | Bearer (Authenticated) | Download single payslip PDF |
| `POST` | `/api/v1/payroll/payslips/{payslip_id}/email` | Bearer (Authenticated) | Email single payslip |
| `POST` | `/api/v1/payroll/payslips/{payslip_id}/regenerate` | Bearer (Authenticated) | Regenerate single payslip |
| `DELETE` | `/api/v1/payroll/payslips/{payslip_id}` | Bearer (Authenticated) | Delete payslip |
| `GET` | `/api/v1/payroll/payslips/{payslip_id}/audit-logs` | Bearer (Authenticated) | Get audit logs for payslip |
| `GET` | `/api/v1/payroll/payslips/{payslip_id}` | Bearer (Authenticated) | Get single payslip |
| `GET` | `/api/v1/payroll/overtime` | Bearer (Authenticated) | List overtime entries |
| `POST` | `/api/v1/payroll/overtime` | Bearer (Authenticated) | Create overtime entry |
| `POST` | `/api/v1/payroll/overtime/{overtime_id}/approve` | Bearer (Authenticated) | Approve overtime entry |
| `POST` | `/api/v1/payroll/overtime/{overtime_id}/reject` | Bearer (Authenticated) | Reject overtime entry |
| `POST` | `/api/v1/payroll/overtime/copilot` | Bearer (Authenticated) | Copilot chat assistant |
| `GET` | `/api/v1/payroll/bonus/plans` | Bearer (Authenticated) | List bonus plans |
| `GET` | `/api/v1/payroll/bonuses` | Bearer (Authenticated) | List all bonuses |
| `POST` | `/api/v1/payroll/bonuses` | Bearer (Authenticated) | Create bonus request |
| `POST` | `/api/v1/payroll/bonuses/{bonus_id}/approve` | Bearer (Authenticated) | Approve bonus request |
| `POST` | `/api/v1/payroll/bonuses/{bonus_id}/reject` | Bearer (Authenticated) | Reject bonus request |
| `POST` | `/api/v1/payroll/bonuses/copilot` | Bearer (Authenticated) | Copilot chat assistant |
| `GET` | `/api/v1/payroll/deductions` | Bearer (Authenticated) | List deductions |
| `GET` | `/api/v1/payroll/reimbursements` | Bearer (Authenticated) | List reimbursement claims |
| `POST` | `/api/v1/payroll/reimbursements` | Bearer (Authenticated) | Create reimbursement claim |
| `POST` | `/api/v1/payroll/reimbursements/{claim_id}/approve` | Bearer (Authenticated) | Approve reimbursement claim |
| `POST` | `/api/v1/payroll/reimbursements/{claim_id}/reject` | Bearer (Authenticated) | Reject reimbursement claim |
| `POST` | `/api/v1/payroll/reimbursements/bulk-approve` | Bearer (Authenticated) | Bulk approve reimbursement claims |
| `GET` | `/api/v1/payroll/reimbursements/audit-logs` | Bearer (Authenticated) | Get reimbursement audit logs |
| `GET` | `/api/v1/payroll/reimbursements/ai-insights` | Bearer (Authenticated) | Get reimbursement AI insights |
| `POST` | `/api/v1/payroll/reimbursements/copilot` | Bearer (Authenticated) | Copilot chat assistant |
| `GET` | `/api/v1/payroll/loans` | Bearer (Authenticated) | List advances/loans alias |
| `GET` | `/api/v1/payroll/advances` | Bearer (Authenticated) | List advances/loans |
| `POST` | `/api/v1/payroll/advances` | Bearer (Authenticated) | Create advance request |
| `POST` | `/api/v1/payroll/advances/{loan_id}/approve` | Bearer (Authenticated) | Approve advance request |
| `POST` | `/api/v1/payroll/advances/{loan_id}/reject` | Bearer (Authenticated) | Reject advance request |
| `POST` | `/api/v1/payroll/advances/copilot` | Bearer (Authenticated) | Copilot chat assistant |
| `GET` | `/api/v1/payroll/bank/disbursements` | Bearer (Authenticated) | List bank disbursements alias |
| `GET` | `/api/v1/payroll/bank-transfers` | Bearer (Authenticated) | List bank transfers |
| `GET` | `/api/v1/payroll/bank-transfers/dashboard` | Bearer (Authenticated) | Get bank transfer dashboard metrics |
| `GET` | `/api/v1/payroll/bank-transfers/audit` | Bearer (Authenticated) | Get bank transfer audit logs |
| `GET` | `/api/v1/payroll/bank-transfers/{transfer_id}` | Bearer (Authenticated) | Get bank transfer detail |
| `POST` | `/api/v1/payroll/bank-transfers/batch` | Bearer (Authenticated) | Create transfer batch |
| `POST` | `/api/v1/payroll/bank-transfers/generate-file` | Bearer (Authenticated) | Generate NEFT bank file |
| `POST` | `/api/v1/payroll/bank-transfers/initiate` | Bearer (Authenticated) | Initiate bank transfer payments |
| `POST` | `/api/v1/payroll/bank-transfers/reconcile` | Bearer (Authenticated) | Reconcile bank transfer payments |
| `POST` | `/api/v1/payroll/bank-transfers/{transfer_id}/retry` | Bearer (Authenticated) | Retry failed transfer |
| `POST` | `/api/v1/payroll/bank-transfers/{transfer_id}/mark-paid` | Bearer (Authenticated) | Mark transfer as paid |
| `GET` | `/api/v1/payroll/compliance/config` | Bearer (Authenticated) | Get statutory compliance configuration |
| `GET` | `/api/v1/payroll/compliance` | Bearer (Authenticated) | Get statutory compliance dashboard |
| `GET` | `/api/v1/payroll/compliance/dashboard` | Bearer (Authenticated) | Get statutory compliance dashboard |
| `GET` | `/api/v1/payroll/dashboard` | Bearer (Authenticated) | Get main payroll dashboard data |
| `GET` | `/api/v1/payroll/copilot/chat` | Bearer (Authenticated) | Get payroll copilot status & history |
| `POST` | `/api/v1/payroll/copilot/chat` | Bearer (Authenticated) | Payroll AI copilot chat |
| `GET` | `/api/v1/payroll/copilot/history` | Bearer (Authenticated) | Get payroll copilot chat history |
| `POST` | `/api/v1/payroll/copilot/clear` | Bearer (Authenticated) | Clear payroll copilot chat history |
| `GET` | `/api/v1/payroll/settings` | Bearer (Authenticated) | Get payroll settings |
| `PATCH` | `/api/v1/payroll/settings` | Bearer (Authenticated) | Update payroll settings |
| `POST` | `/api/v1/payroll/settings` | Bearer (Authenticated) | Update payroll settings |
| `PUT` | `/api/v1/payroll/settings` | Bearer (Authenticated) | Update payroll settings |
| `GET` | `/api/v1/payroll/settings/history` | Bearer (Authenticated) | Get settings change version history |
| `GET` | `/api/v1/payroll/settings/audit` | Bearer (Authenticated) | Get settings change audit log |
| `POST` | `/api/v1/payroll/settings/reset` | Bearer (Authenticated) | Reset payroll settings to statutory presets |
| `POST` | `/api/v1/payroll/settings/test` | Bearer (Authenticated) | Test settings configuration integrity |
| `GET` | `/api/v1/payroll/settings/export` | Bearer (Authenticated) | Export settings configuration JSON snapshot |
| `GET` | `/api/v1/payroll/tax` | Bearer (Authenticated) | Get tax management list |
| `GET` | `/api/v1/payroll/components` | Bearer (Authenticated) | List all salary components |
| `GET` | `/api/v1/payroll/components/audit` | Bearer (Authenticated) | Get salary components audit log |
| `GET` | `/api/v1/payroll/components/history` | Bearer (Authenticated) | Get salary components version history |
| `GET` | `/api/v1/payroll/components/{component_id}` | Bearer (Authenticated) | Get single component details |
| `POST` | `/api/v1/payroll/components` | Bearer (Authenticated) | Create new salary component |
| `PATCH` | `/api/v1/payroll/components/{component_id}` | Bearer (Authenticated) | Partial update salary component |
| `PUT` | `/api/v1/payroll/components/{component_id}` | Bearer (Authenticated) | Update salary component |
| `DELETE` | `/api/v1/payroll/components/{component_id}` | Bearer (Authenticated) | Delete salary component |
| `POST` | `/api/v1/payroll/components/{component_id}/duplicate` | Bearer (Authenticated) | Duplicate salary component |
| `POST` | `/api/v1/payroll/components/{component_id}/activate` | Bearer (Authenticated) | Activate salary component |
| `POST` | `/api/v1/payroll/components/{component_id}/deactivate` | Bearer (Authenticated) | Deactivate salary component |
| `POST` | `/api/v1/payroll/components/reorder` | Bearer (Authenticated) | Reorder components display order |
| `GET` | `/api/v1/payroll/allowances` | Bearer (Authenticated) | List all allowances |
| `GET` | `/api/v1/payroll/allowances/audit` | Bearer (Authenticated) | Get allowance audit log |
| `GET` | `/api/v1/payroll/allowances/history` | Bearer (Authenticated) | Get allowance version history |
| `GET` | `/api/v1/payroll/allowances/export` | Bearer (Authenticated) | Export allowances snapshot |
| `GET` | `/api/v1/payroll/allowances/{allowance_id}` | Bearer (Authenticated) | Get single allowance details |
| `POST` | `/api/v1/payroll/allowances` | Bearer (Authenticated) | Create new allowance definition |
| `PATCH` | `/api/v1/payroll/allowances/{allowance_id}` | Bearer (Authenticated) | Partial update allowance definition |
| `PUT` | `/api/v1/payroll/allowances/{allowance_id}` | Bearer (Authenticated) | Update allowance definition |
| `DELETE` | `/api/v1/payroll/allowances/{allowance_id}` | Bearer (Authenticated) | Delete custom allowance |
| `POST` | `/api/v1/payroll/allowances/{allowance_id}/duplicate` | Bearer (Authenticated) | Duplicate allowance definition |
| `POST` | `/api/v1/payroll/allowances/{allowance_id}/activate` | Bearer (Authenticated) | Activate allowance |
| `POST` | `/api/v1/payroll/allowances/{allowance_id}/deactivate` | Bearer (Authenticated) | Deactivate allowance |
| `GET` | `/api/v1/payroll/taxes` | Bearer (Authenticated) | List all tax rules & configurations |
| `GET` | `/api/v1/payroll/taxes/audit` | Bearer (Authenticated) | Get tax audit log |
| `GET` | `/api/v1/payroll/taxes/history` | Bearer (Authenticated) | Get tax version history |
| `GET` | `/api/v1/payroll/taxes/export` | Bearer (Authenticated) | Export tax configuration snapshot |
| `POST` | `/api/v1/payroll/taxes/import` | Bearer (Authenticated) | Import tax configuration rules |
| `POST` | `/api/v1/payroll/taxes/recalculate` | Bearer (Authenticated) | Recalculate live tax liabilities |
| `GET` | `/api/v1/payroll/taxes/{tax_id}` | Bearer (Authenticated) | Get single tax setting details |
| `POST` | `/api/v1/payroll/taxes` | Bearer (Authenticated) | Create new tax setting |
| `PATCH` | `/api/v1/payroll/taxes/{tax_id}` | Bearer (Authenticated) | Partial update tax setting |
| `PUT` | `/api/v1/payroll/taxes/{tax_id}` | Bearer (Authenticated) | Update tax setting |
| `DELETE` | `/api/v1/payroll/taxes/{tax_id}` | Bearer (Authenticated) | Delete tax setting |
| `POST` | `/api/v1/payroll/taxes/{tax_id}/activate` | Bearer (Authenticated) | Activate tax setting |
| `POST` | `/api/v1/payroll/taxes/{tax_id}/deactivate` | Bearer (Authenticated) | Deactivate tax setting |
| `GET` | `/api/v1/payroll/overtime/settings` | Bearer (Authenticated) | Get company overtime policy settings |
| `PUT` | `/api/v1/payroll/overtime/settings` | Bearer (Authenticated) | Update company overtime policy settings |
| `POST` | `/api/v1/payroll/overtime/calculate` | Bearer (Authenticated) | Calculate live overtime pay |
| `POST` | `/api/v1/payroll/overtime/request` | Bearer (Authenticated) | Submit employee overtime request |
| `GET` | `/api/v1/payroll/overtime/history` | Bearer (Authenticated) | Get overtime policy history |
| `GET` | `/api/v1/payroll/overtime/audit` | Bearer (Authenticated) | Get overtime policy audit logs |
| `GET` | `/api/v1/payroll/compliance/rules` | Bearer (Authenticated) | List statutory compliance rules |
| `GET` | `/api/v1/payroll/compliance/audit` | Bearer (Authenticated) | Get compliance audit log |
| `GET` | `/api/v1/payroll/compliance/history` | Bearer (Authenticated) | Get compliance version history |
| `GET` | `/api/v1/payroll/compliance/calendar` | Bearer (Authenticated) | Get statutory due dates calendar |
| `POST` | `/api/v1/payroll/compliance/validate` | Bearer (Authenticated) | Run statutory compliance audit scan |
| `POST` | `/api/v1/payroll/compliance/challan` | Bearer (Authenticated) | Generate EPFO ECR or ESIC Challan |
| `GET` | `/api/v1/payroll/compliance/{rule_id}` | Bearer (Authenticated) | Get single compliance rule details |
| `POST` | `/api/v1/payroll/compliance` | Bearer (Authenticated) | Create new statutory compliance rule |
| `GET` | `/api/v1/payroll/templates` | Bearer (Authenticated) | List all payroll document templates |
| `GET` | `/api/v1/payroll/templates/audit` | Bearer (Authenticated) | Get template audit log |
| `GET` | `/api/v1/payroll/templates/history` | Bearer (Authenticated) | Get template version history |
| `GET` | `/api/v1/payroll/templates/{template_id}` | Bearer (Authenticated) | Get single template details |
| `POST` | `/api/v1/payroll/templates` | Bearer (Authenticated) | Create new payroll template |
| `PATCH` | `/api/v1/payroll/templates/{template_id}` | Bearer (Authenticated) | Partial update payroll template |
| `PUT` | `/api/v1/payroll/templates/{template_id}` | Bearer (Authenticated) | Update payroll template |
| `POST` | `/api/v1/payroll/templates/{template_id}/duplicate` | Bearer (Authenticated) | Duplicate template |
| `POST` | `/api/v1/payroll/templates/{template_id}/preview` | Bearer (Authenticated) | Preview merged HTML template |
| `POST` | `/api/v1/payroll/templates/{template_id}/publish` | Bearer (Authenticated) | Publish template |
| `POST` | `/api/v1/payroll/templates/{template_id}/archive` | Bearer (Authenticated) | Archive template |
| `GET` | `/api/v1/payroll/security/roles` | Bearer (Authenticated) | List all RBAC security roles |
| `GET` | `/api/v1/payroll/security/policies` | Bearer (Authenticated) | Get enterprise security policies |
| `PUT` | `/api/v1/payroll/security/policies` | Bearer (Authenticated) | Update enterprise security policies |
| `GET` | `/api/v1/payroll/security/sessions` | Bearer (Authenticated) | Get active user sessions |
| `DELETE` | `/api/v1/payroll/security/sessions/{session_id}` | Bearer (Authenticated) | Revoke active user session |
| `POST` | `/api/v1/payroll/security/logout-all` | Bearer (Authenticated) | Force logout all active user sessions |
| `GET` | `/api/v1/payroll/security/ip-whitelist` | Bearer (Authenticated) | List whitelisted IP ranges |
| `POST` | `/api/v1/payroll/security/ip-whitelist` | Bearer (Authenticated) | Add whitelisted IP range |
| `DELETE` | `/api/v1/payroll/security/ip-whitelist/{ip_id}` | Bearer (Authenticated) | Remove whitelisted IP range |
| `GET` | `/api/v1/payroll/security/audit` | Bearer (Authenticated) | Get security audit log |
| `GET` | `/api/v1/ai/analytics/payroll-trend` | Bearer (Authenticated) | Get Payroll Trends & Forecast |
| `GET` | `/api/v1/exports/payroll` | Bearer (export_permission) | Export Payroll |
| `GET` | `/api/v1/ai-hub/payroll-insights` | Bearer (Authenticated) | Payroll Insights Overview |
| `POST` | `/api/v1/ai-hub/payroll-insights/analyze` | Bearer (Authenticated) | Analyze Pay Cycle and Variances |
| `GET` | `/api/v1/ai-hub/payroll-insights/anomalies` | Bearer (Authenticated) | List Payroll Anomalies (Paginated) |
| `POST` | `/api/v1/ai-hub/payroll-insights/tax-audit` | Bearer (Authenticated) | Execute Statutory Tax Audit |
| `GET` | `/api/v1/analytics/payroll` | Bearer (Authenticated) | Get Payroll Metric |
| `GET` | `/api/v1/settings/payroll` | Bearer (Authenticated) | Get Settings Section |
| `PUT` | `/api/v1/settings/payroll` | Bearer (Authenticated) | Update Settings Section Endpoint |
| `GET` | `/api/v2/payroll/accounting-export` | Bearer (Authenticated) | Export general ledger accounting journal entries |
| `GET` | `/api/v2/payroll/companies/{companyId}/bank-accounts` | Bearer (Authenticated) | Get company bank accounts |
| `GET` | `/api/v2/payroll/compensations` | Bearer (Authenticated) | List employee compensations |
| `POST` | `/api/v2/payroll/compensation/bulk-import/preview` | Bearer (Authenticated) | Preview bulk compensation import file |
| `POST` | `/api/v2/payroll/compensation/bulk-import/apply` | Bearer (Authenticated) | Apply bulk compensation import from preview token |
| `POST` | `/api/v2/payroll/compensation/revisions/{revisionId}/approve` | Bearer (Authenticated) | Approve compensation revision |
| `POST` | `/api/v2/payroll/compensation/revisions/{revisionId}/reject` | Bearer (Authenticated) | Reject compensation revision |
| `GET` | `/api/v2/payroll/cycles` | Bearer (Authenticated) | List payroll cycles |
| `GET` | `/api/v2/payroll/cycles/{cycleId}` | Bearer (Authenticated) | Get payroll cycle details |
| `POST` | `/api/v2/payroll/cycles/{cycleId}/reopen` | Bearer (Authenticated) | Reopen a payroll cycle |
| `POST` | `/api/v2/payroll/cycles/{cycleId}/void` | Bearer (Authenticated) | Void a payroll cycle |
| `GET` | `/api/v2/payroll/employee/dashboard` | Bearer (Authenticated) | Get dashboard summary for current employee |
| `GET` | `/api/v2/payroll/employee/provision-slips` | Bearer (Authenticated) | Get provision slips for current employee |
| `GET` | `/api/v2/payroll/employees/{employeeId}/compensation` | Bearer (Authenticated) | Get compensation details for an employee |
| `POST` | `/api/v2/payroll/employees/{employeeId}/compensation/revisions` | Bearer (Authenticated) | Create a pending compensation revision for an employee |
| `GET` | `/api/v2/payroll/employees/{employeeId}/payslips` | Bearer (Authenticated) | Get payslips for an employee |
| `POST` | `/api/v2/payroll/employees/{employeeId}/reveal-bank-account` | Bearer (Authenticated) | Reveal sensitive bank account details |
| `GET` | `/api/v2/payroll/full-and-final` | Bearer (Authenticated) | List full and final settlements |
| `POST` | `/api/v2/payroll/full-and-final` | Bearer (Authenticated) | Initiate full and final settlement |
| `GET` | `/api/v2/payroll/full-and-final/{fnfId}` | Bearer (Authenticated) | Get full and final settlement details |
| `POST` | `/api/v2/payroll/full-and-final/{fnfId}/approve` | Bearer (Authenticated) | Approve full and final settlement |
| `POST` | `/api/v2/payroll/full-and-final/{fnfId}/finalize` | Bearer (Authenticated) | Finalize full and final settlement |
| `POST` | `/api/v2/payroll/full-and-final/{fnfId}/reject` | Bearer (Authenticated) | Reject full and final settlement |
| `GET` | `/api/v2/payroll/full-and-final/{fnfId}/statement/download` | Bearer (Authenticated) | Download full and final settlement statement |
| `GET` | `/api/v2/payroll/my-payslips` | Bearer (Authenticated) | Get payslips for the authenticated employee |
| `GET` | `/api/v2/payroll/my-payslips/{runId}/download` | Bearer (Authenticated) | Download payslip for authenticated employee |
| `GET` | `/api/v2/payroll/my-provision-slips` | Bearer (Authenticated) | Get provision slips for authenticated employee |
| `GET` | `/api/v2/payroll/payslips/{runId}/{employeeId}` | Bearer (Authenticated) | Get payslip detail for an employee in a run |
| `GET` | `/api/v2/payroll/provision-slips/{provisionSlipId}/pdf` | Bearer (Authenticated) | Download provision slip PDF/document |
| `GET` | `/api/v2/payroll/pay-components` | Bearer (Authenticated) | List all active pay components |
| `POST` | `/api/v2/payroll/pay-components` | Bearer (Authenticated) | Create a new pay component |
| `GET` | `/api/v2/payroll/payment-batches` | Bearer (Authenticated) | List payment batches |
| `GET` | `/api/v2/payroll/payment-batches/{batchId}` | Bearer (Authenticated) | Get payment batch details and items |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/approve` | Bearer (Authenticated) | Approve payment batch |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/bank-file` | Bearer (Authenticated) | Generate bank payment file |
| `GET` | `/api/v2/payroll/payment-batches/{batchId}/bank-file/download` | Bearer (Authenticated) | Download generated bank payment file |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/bank-response/preview` | Bearer (Authenticated) | Preview bank acknowledgement/reconciliation file |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/bank-response/apply` | Bearer (Authenticated) | Apply bank response preview to update transaction states |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/hold` | Bearer (Authenticated) | Hold a specific item in the payment batch |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/release` | Bearer (Authenticated) | Release a held item in the payment batch |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/items/{itemId}/retry` | Bearer (Authenticated) | Retry a failed payment batch item |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/reconcile` | Bearer (Authenticated) | Reconcile payment batch against bank responses |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/reject` | Bearer (Authenticated) | Reject payment batch |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/submit` | Bearer (idempotency_key) | Submit payment batch to bank |
| `POST` | `/api/v2/payroll/payment-batches/{batchId}/validate` | Bearer (Authenticated) | Validate payment batch and accounts |
| `GET` | `/api/v2/payroll/reports/{reportKey}` | Bearer (Authenticated) | Fetch dynamic payroll report data |
| `POST` | `/api/v2/payroll/reports/{reportKey}/export` | Bearer (Authenticated) | Export payroll report asynchronously |
| `GET` | `/api/v2/payroll/reports/exports/{exportId}/download` | Bearer (Authenticated) | Download completed report export file |
| `GET` | `/api/v2/payroll/runs` | Bearer (Authenticated) | List payroll runs |
| `POST` | `/api/v2/payroll/runs` | Bearer (Authenticated) | Create a new payroll run |
| `GET` | `/api/v2/payroll/runs/{runId}` | Bearer (Authenticated) | Get payroll run details |
| `DELETE` | `/api/v2/payroll/runs/{runId}` | Bearer (Authenticated) | Delete draft payroll run |
| `GET` | `/api/v2/payroll/runs/{runId}/approval` | Bearer (Authenticated) | Get approval status and details for payroll run |
| `POST` | `/api/v2/payroll/runs/{runId}/approve` | Bearer (Authenticated) | Approve payroll run |
| `GET` | `/api/v2/payroll/runs/{runId}/employees` | Bearer (Authenticated) | List employee calculation items in payroll run |
| `GET` | `/api/v2/payroll/runs/{runId}/employees/{employeeId}` | Bearer (Authenticated) | Get calculation breakdown for employee in run |
| `GET` | `/api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip` | Bearer (Authenticated) | Get payslip JSON breakdown for employee in run |
| `GET` | `/api/v2/payroll/runs/{runId}/employees/{employeeId}/payslip/download` | Bearer (Authenticated) | Download payslip document for employee in run |
| `GET` | `/api/v2/payroll/runs/{runId}/finalization` | Bearer (Authenticated) | Get finalization summary and lock status for run |
| `POST` | `/api/v2/payroll/runs/{runId}/finalize` | Bearer (Authenticated) | Finalize payroll run |
| `GET` | `/api/v2/payroll/runs/{runId}/generation-status` | Bearer (Authenticated) | Poll async generation/calculation status |
| `POST` | `/api/v2/payroll/runs/{runId}/payment-batches` | Bearer (Authenticated) | Create payment batch from run |
| `GET` | `/api/v2/payroll/runs/{runId}/payment-batches` | Bearer (Authenticated) | List payment batches associated with run |
| `POST` | `/api/v2/payroll/runs/{runId}/payslips/generate` | Bearer (Authenticated) | Trigger batch payslip generation task |
| `GET` | `/api/v2/payroll/runs/{runId}/preview` | Bearer (Authenticated) | Preview payroll calculation aggregate summary |
| `POST` | `/api/v2/payroll/runs/{runId}/process` | Bearer (Authenticated) | Trigger payroll calculation engine processing |
| `POST` | `/api/v2/payroll/runs/{runId}/reject` | Bearer (Authenticated) | Reject payroll run |
| `POST` | `/api/v2/payroll/runs/{runId}/revalidate` | Bearer (Authenticated) | Revalidate payroll run rules and employee inputs |
| `GET` | `/api/v2/payroll/runs/{runId}/review` | Bearer (Authenticated) | Review payroll run before sign-off |
| `POST` | `/api/v2/payroll/runs/{runId}/send-back` | Bearer (Authenticated) | Send payroll run back for corrections |
| `POST` | `/api/v2/payroll/runs/{runId}/validate` | Bearer (Authenticated) | Execute pre-check validation rules on run |
| `GET` | `/api/v2/payroll/runs/{runId}/validation` | Bearer (Authenticated) | Get validation status of run |
| `GET` | `/api/v2/payroll/runs/{runId}/validation-issues` | Bearer (Authenticated) | Get list of validation issues found in run |
| `GET` | `/api/v2/payroll/statutory/config` | Bearer (Authenticated) | Get statutory compliance configuration (PF, ESI, PT, TDS) |
| `POST` | `/api/v2/payroll/statutory/reports/{component}` | Bearer (Authenticated) | Generate statutory authority returns (e.g. PF ECR) |
| `GET` | `/api/v2/payroll/statutory/summary` | Bearer (Authenticated) | Get statutory liability summary for a period |
| `GET` | `/api/v2/payroll/variable-inputs` | Bearer (Authenticated) | List variable salary inputs |
| `POST` | `/api/v2/payroll/variable-inputs` | Bearer (Authenticated) | Create a new variable input |
| `POST` | `/api/v2/payroll/variable-inputs/bulk-preview` | Bearer (Authenticated) | Preview bulk variable inputs file |
| `POST` | `/api/v2/payroll/variable-inputs/bulk-apply` | Bearer (Authenticated) | Apply bulk variable inputs from preview token |
| `POST` | `/api/v2/payroll/variable-inputs/{id}/approve` | Bearer (Authenticated) | Approve variable input |
| `POST` | `/api/v2/payroll/variable-inputs/{id}/reject` | Bearer (Authenticated) | Reject variable input |
| `GET` | `/v2/payroll/accounting-export` | Bearer (Authenticated) | Export general ledger accounting journal entries |
| `GET` | `/v2/payroll/companies/{companyId}/bank-accounts` | Bearer (Authenticated) | Get company bank accounts |
| `GET` | `/v2/payroll/compensations` | Bearer (Authenticated) | List employee compensations |
| `POST` | `/v2/payroll/compensation/bulk-import/preview` | Bearer (Authenticated) | Preview bulk compensation import file |
| `POST` | `/v2/payroll/compensation/bulk-import/apply` | Bearer (Authenticated) | Apply bulk compensation import from preview token |
| `POST` | `/v2/payroll/compensation/revisions/{revisionId}/approve` | Bearer (Authenticated) | Approve compensation revision |
| `POST` | `/v2/payroll/compensation/revisions/{revisionId}/reject` | Bearer (Authenticated) | Reject compensation revision |
| `GET` | `/v2/payroll/cycles` | Bearer (Authenticated) | List payroll cycles |
| `GET` | `/v2/payroll/cycles/{cycleId}` | Bearer (Authenticated) | Get payroll cycle details |
| `POST` | `/v2/payroll/cycles/{cycleId}/reopen` | Bearer (Authenticated) | Reopen a payroll cycle |
| `POST` | `/v2/payroll/cycles/{cycleId}/void` | Bearer (Authenticated) | Void a payroll cycle |
| `GET` | `/v2/payroll/employee/dashboard` | Bearer (Authenticated) | Get dashboard summary for current employee |
| `GET` | `/v2/payroll/employee/provision-slips` | Bearer (Authenticated) | Get provision slips for current employee |
| `GET` | `/v2/payroll/employees/{employeeId}/compensation` | Bearer (Authenticated) | Get compensation details for an employee |
| `POST` | `/v2/payroll/employees/{employeeId}/compensation/revisions` | Bearer (Authenticated) | Create a pending compensation revision for an employee |
| `GET` | `/v2/payroll/employees/{employeeId}/payslips` | Bearer (Authenticated) | Get payslips for an employee |
| `POST` | `/v2/payroll/employees/{employeeId}/reveal-bank-account` | Bearer (Authenticated) | Reveal sensitive bank account details |
| `GET` | `/v2/payroll/full-and-final` | Bearer (Authenticated) | List full and final settlements |
| `POST` | `/v2/payroll/full-and-final` | Bearer (Authenticated) | Initiate full and final settlement |
| `GET` | `/v2/payroll/full-and-final/{fnfId}` | Bearer (Authenticated) | Get full and final settlement details |
| `POST` | `/v2/payroll/full-and-final/{fnfId}/approve` | Bearer (Authenticated) | Approve full and final settlement |
| `POST` | `/v2/payroll/full-and-final/{fnfId}/finalize` | Bearer (Authenticated) | Finalize full and final settlement |
| `POST` | `/v2/payroll/full-and-final/{fnfId}/reject` | Bearer (Authenticated) | Reject full and final settlement |
| `GET` | `/v2/payroll/full-and-final/{fnfId}/statement/download` | Bearer (Authenticated) | Download full and final settlement statement |
| `GET` | `/v2/payroll/my-payslips` | Bearer (Authenticated) | Get payslips for the authenticated employee |
| `GET` | `/v2/payroll/my-payslips/{runId}/download` | Bearer (Authenticated) | Download payslip for authenticated employee |
| `GET` | `/v2/payroll/my-provision-slips` | Bearer (Authenticated) | Get provision slips for authenticated employee |
| `GET` | `/v2/payroll/payslips/{runId}/{employeeId}` | Bearer (Authenticated) | Get payslip detail for an employee in a run |
| `GET` | `/v2/payroll/provision-slips/{provisionSlipId}/pdf` | Bearer (Authenticated) | Download provision slip PDF/document |
| `GET` | `/v2/payroll/pay-components` | Bearer (Authenticated) | List all active pay components |
| `POST` | `/v2/payroll/pay-components` | Bearer (Authenticated) | Create a new pay component |
| `GET` | `/v2/payroll/payment-batches` | Bearer (Authenticated) | List payment batches |
| `GET` | `/v2/payroll/payment-batches/{batchId}` | Bearer (Authenticated) | Get payment batch details and items |
| `POST` | `/v2/payroll/payment-batches/{batchId}/approve` | Bearer (Authenticated) | Approve payment batch |
| `POST` | `/v2/payroll/payment-batches/{batchId}/bank-file` | Bearer (Authenticated) | Generate bank payment file |
| `GET` | `/v2/payroll/payment-batches/{batchId}/bank-file/download` | Bearer (Authenticated) | Download generated bank payment file |
| `POST` | `/v2/payroll/payment-batches/{batchId}/bank-response/preview` | Bearer (Authenticated) | Preview bank acknowledgement/reconciliation file |
| `POST` | `/v2/payroll/payment-batches/{batchId}/bank-response/apply` | Bearer (Authenticated) | Apply bank response preview to update transaction states |
| `POST` | `/v2/payroll/payment-batches/{batchId}/items/{itemId}/hold` | Bearer (Authenticated) | Hold a specific item in the payment batch |
| `POST` | `/v2/payroll/payment-batches/{batchId}/items/{itemId}/release` | Bearer (Authenticated) | Release a held item in the payment batch |
| `POST` | `/v2/payroll/payment-batches/{batchId}/items/{itemId}/retry` | Bearer (Authenticated) | Retry a failed payment batch item |
| `POST` | `/v2/payroll/payment-batches/{batchId}/reconcile` | Bearer (Authenticated) | Reconcile payment batch against bank responses |
| `POST` | `/v2/payroll/payment-batches/{batchId}/reject` | Bearer (Authenticated) | Reject payment batch |
| `POST` | `/v2/payroll/payment-batches/{batchId}/submit` | Bearer (idempotency_key) | Submit payment batch to bank |
| `POST` | `/v2/payroll/payment-batches/{batchId}/validate` | Bearer (Authenticated) | Validate payment batch and accounts |
| `GET` | `/v2/payroll/reports/{reportKey}` | Bearer (Authenticated) | Fetch dynamic payroll report data |
| `POST` | `/v2/payroll/reports/{reportKey}/export` | Bearer (Authenticated) | Export payroll report asynchronously |
| `GET` | `/v2/payroll/reports/exports/{exportId}/download` | Bearer (Authenticated) | Download completed report export file |
| `GET` | `/v2/payroll/runs` | Bearer (Authenticated) | List payroll runs |
| `POST` | `/v2/payroll/runs` | Bearer (Authenticated) | Create a new payroll run |
| `GET` | `/v2/payroll/runs/{runId}` | Bearer (Authenticated) | Get payroll run details |
| `DELETE` | `/v2/payroll/runs/{runId}` | Bearer (Authenticated) | Delete draft payroll run |
| `GET` | `/v2/payroll/runs/{runId}/approval` | Bearer (Authenticated) | Get approval status and details for payroll run |
| `POST` | `/v2/payroll/runs/{runId}/approve` | Bearer (Authenticated) | Approve payroll run |
| `GET` | `/v2/payroll/runs/{runId}/employees` | Bearer (Authenticated) | List employee calculation items in payroll run |
| `GET` | `/v2/payroll/runs/{runId}/employees/{employeeId}` | Bearer (Authenticated) | Get calculation breakdown for employee in run |
| `GET` | `/v2/payroll/runs/{runId}/employees/{employeeId}/payslip` | Bearer (Authenticated) | Get payslip JSON breakdown for employee in run |
| `GET` | `/v2/payroll/runs/{runId}/employees/{employeeId}/payslip/download` | Bearer (Authenticated) | Download payslip document for employee in run |
| `GET` | `/v2/payroll/runs/{runId}/finalization` | Bearer (Authenticated) | Get finalization summary and lock status for run |
| `POST` | `/v2/payroll/runs/{runId}/finalize` | Bearer (Authenticated) | Finalize payroll run |
| `GET` | `/v2/payroll/runs/{runId}/generation-status` | Bearer (Authenticated) | Poll async generation/calculation status |
| `POST` | `/v2/payroll/runs/{runId}/payment-batches` | Bearer (Authenticated) | Create payment batch from run |
| `GET` | `/v2/payroll/runs/{runId}/payment-batches` | Bearer (Authenticated) | List payment batches associated with run |
| `POST` | `/v2/payroll/runs/{runId}/payslips/generate` | Bearer (Authenticated) | Trigger batch payslip generation task |
| `GET` | `/v2/payroll/runs/{runId}/preview` | Bearer (Authenticated) | Preview payroll calculation aggregate summary |
| `POST` | `/v2/payroll/runs/{runId}/process` | Bearer (Authenticated) | Trigger payroll calculation engine processing |
| `POST` | `/v2/payroll/runs/{runId}/reject` | Bearer (Authenticated) | Reject payroll run |
| `POST` | `/v2/payroll/runs/{runId}/revalidate` | Bearer (Authenticated) | Revalidate payroll run rules and employee inputs |
| `GET` | `/v2/payroll/runs/{runId}/review` | Bearer (Authenticated) | Review payroll run before sign-off |
| `POST` | `/v2/payroll/runs/{runId}/send-back` | Bearer (Authenticated) | Send payroll run back for corrections |
| `POST` | `/v2/payroll/runs/{runId}/validate` | Bearer (Authenticated) | Execute pre-check validation rules on run |
| `GET` | `/v2/payroll/runs/{runId}/validation` | Bearer (Authenticated) | Get validation status of run |
| `GET` | `/v2/payroll/runs/{runId}/validation-issues` | Bearer (Authenticated) | Get list of validation issues found in run |
| `GET` | `/v2/payroll/statutory/config` | Bearer (Authenticated) | Get statutory compliance configuration (PF, ESI, PT, TDS) |
| `POST` | `/v2/payroll/statutory/reports/{component}` | Bearer (Authenticated) | Generate statutory authority returns (e.g. PF ECR) |
| `GET` | `/v2/payroll/statutory/summary` | Bearer (Authenticated) | Get statutory liability summary for a period |
| `GET` | `/v2/payroll/variable-inputs` | Bearer (Authenticated) | List variable salary inputs |
| `POST` | `/v2/payroll/variable-inputs` | Bearer (Authenticated) | Create a new variable input |
| `POST` | `/v2/payroll/variable-inputs/bulk-preview` | Bearer (Authenticated) | Preview bulk variable inputs file |
| `POST` | `/v2/payroll/variable-inputs/bulk-apply` | Bearer (Authenticated) | Apply bulk variable inputs from preview token |
| `POST` | `/v2/payroll/variable-inputs/{id}/approve` | Bearer (Authenticated) | Approve variable input |
| `POST` | `/v2/payroll/variable-inputs/{id}/reject` | Bearer (Authenticated) | Reject variable input |
| `GET` | `/api/v2/reports/analytics/payroll-cost` | Bearer (analytics_access) | Get monthly payroll cost totals (Restricted to HR Admin & Executive) |

### Performance (57 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ai/performance/dashboard` | Bearer (Authenticated) | Get AI Performance Dashboard KPIs |
| `GET` | `/api/v1/ai/performance/trends` | Bearer (Authenticated) | Get Performance Trend Series |
| `GET` | `/api/v1/ai/performance/kpi-attainment` | Bearer (Authenticated) | Get KPI Attainment by Function |
| `GET` | `/api/v1/ai/performance/top-performers` | Bearer (Authenticated) | Get Top Performers Ranking |
| `GET` | `/api/v1/ai/performance/employee/{employee_id}` | Bearer (Authenticated) | Get Employee Multi-Dimensional Performance Score |
| `GET` | `/api/v1/ai/performance/skill-gaps` | Bearer (Authenticated) | Get Skill Gap Analysis Data |
| `GET` | `/api/v1/ai/performance/promotion-recommendations` | Bearer (Authenticated) | Get AI Promotion Recommendations |
| `GET` | `/api/v1/ai/performance/coaching-suggestions` | Bearer (Authenticated) | Get AI Coaching Suggestions |
| `GET` | `/api/v1/ai/performance/analytics` | Bearer (Authenticated) | Get Performance Analytics Overview |
| `POST` | `/api/v1/ai/performance/evaluate` | Bearer (Authenticated) | Evaluate Performance Review via AI |
| `POST` | `/api/v1/ai/performance/generate-coaching` | Bearer (Authenticated) | Generate AI Personalized Coaching |
| `POST` | `/api/v1/ai/performance/generate-promotion` | Bearer (Authenticated) | Generate AI Promotion Assessment |
| `POST` | `/api/v1/ai/performance/skill-gap-analysis` | Bearer (Authenticated) | Trigger AI Skill Gap Analysis |
| `GET` | `/api/v1/ai/analytics/performance` | Bearer (Authenticated) | Get Performance Intelligence |
| `GET` | `/api/v1/ai-insights/performance` | Bearer (analytics_access) | Get Performance |
| `GET` | `/api/v1/exports/performance` | Bearer (export_permission) | Export Performance |
| `GET` | `/api/v1/ai-hub/performance-coach` | Bearer (Authenticated) | Performance Coach Overview |
| `POST` | `/api/v1/ai-hub/performance-coach/goals` | Bearer (Authenticated) | Generate Tailored Employee Goals & OKRs |
| `POST` | `/api/v1/ai-hub/performance-coach/training-recommendations` | Bearer (Authenticated) | Generate Training & Upskilling Recommendations |
| `GET` | `/api/v1/analytics/performance` | Bearer (Authenticated) | Get Performance Metric |
| `GET` | `/api/v1/performance/dashboard` | Bearer (Authenticated) | Get Performance Dashboard |
| `GET` | `/api/v1/performance/` | Bearer (Authenticated) | Get Performance Dashboard |
| `GET` | `/api/v1/performance/goals` | Bearer (Authenticated) | List Goals |
| `POST` | `/api/v1/performance/goals` | Bearer (Authenticated) | Create Goal |
| `PUT` | `/api/v1/performance/goals/{id}` | Bearer (Authenticated) | Update Goal |
| `DELETE` | `/api/v1/performance/goals/{id}` | Bearer (Authenticated) | Delete Goal |
| `GET` | `/api/v1/performance/reviews` | Bearer (Authenticated) | List Reviews |
| `POST` | `/api/v1/performance/reviews` | Bearer (Authenticated) | Create Review |
| `GET` | `/api/v1/performance/reviews/{id}` | Bearer (Authenticated) | Get Review |
| `PUT` | `/api/v1/performance/reviews/{id}` | Bearer (Authenticated) | Update Review |
| `GET` | `/api/v1/performance/kpis` | Bearer (Authenticated) | List Kpis |
| `POST` | `/api/v1/performance/kpis` | Bearer (Authenticated) | Create Kpi |
| `GET` | `/api/v1/performance/ratings` | Bearer (Authenticated) | Get Performance Ratings |
| `GET` | `/api/v1/performance/team` | Bearer (Authenticated) | Get Team Performance |
| `GET` | `/api/v1/performance/history` | Bearer (Authenticated) | Get Performance History |
| `GET` | `/api/v1/performance/analytics` | Bearer (Authenticated) | Get Performance Analytics |
| `GET` | `/api/v1/performance-coach/` | Public (None) | Get Performance Coach Status |
| `GET` | `/api/v1/performance-coach` | Public (None) | Get Performance Coach Status |
| `POST` | `/api/v1/performance-coach/chat` | Bearer (Authenticated) | Chat With Coach |
| `GET` | `/api/v1/performance-coach/recommendations` | Bearer (Authenticated) | Get Coaching Recommendations |
| `GET` | `/api/v1/performance-coach/progress` | Bearer (Authenticated) | Get Coaching Progress |
| `POST` | `/api/v2/performance/cycles` | Bearer (employee_or_above) | Create a new evaluation review cycle |
| `POST` | `/api/v2/performance/goals` | Bearer (employee_or_above) | Register a performance goal or OKR for tracking |
| `PUT` | `/api/v2/performance/goals/{id}` | Bearer (employee_or_above) | Update goal details |
| `DELETE` | `/api/v2/performance/goals/{id}` | Bearer (employee_or_above) | Delete a goal |
| `POST` | `/api/v2/performance/goals/assign` | Bearer (employee_or_above) | Assign a goal to an employee |
| `POST` | `/api/v2/performance/goals/{id}/complete` | Bearer (employee_or_above) | Complete a goal |
| `POST` | `/api/v2/performance/reviews` | Bearer (employee_or_above) | Initialize performance review parameters |
| `PUT` | `/api/v2/performance/reviews/{id}` | Bearer (employee_or_above) | Update performance review details |
| `DELETE` | `/api/v2/performance/reviews/{id}` | Bearer (employee_or_above) | Delete a performance review |
| `POST` | `/api/v2/performance/reviews/bulk-delete` | Bearer (employee_or_above) | Bulk delete performance reviews |
| `POST` | `/api/v2/performance/reviews/bulk-status` | Bearer (employee_or_above) | Bulk set reviews status |
| `POST` | `/api/v2/performance/reviews/import` | Bearer (employee_or_above) | Import multiple performance reviews |
| `POST` | `/api/v2/performance/reviews/{review_id}/evaluate` | Bearer (employee_or_above) | Trigger local LLM performance review and predictions calculation |
| `GET` | `/api/v2/performance` | Bearer (employee_or_above) | Get all performance data |
| `POST` | `/api/v2/goals/generate` | Bearer (employee_or_above) | Automatically generate OKRs, KPIs, or tasks goals via LLM |
| `POST` | `/api/v2/goals/adjust` | Bearer (employee_or_above) | Trigger dynamic AI goal re-calibrations |

### Documents (51 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/exits/{id}/documents` | Bearer (Authenticated) | Get generated exit documents |
| `GET` | `/api/v1/documents/categories` | Bearer (Authenticated) | List document categories |
| `POST` | `/api/v1/documents/employees` | Bearer (Authenticated) | Upload employee document |
| `GET` | `/api/v1/documents/employees` | Bearer (Authenticated) | List employee documents |
| `GET` | `/api/v1/documents/employees/{id}` | Bearer (Authenticated) | Get employee document details |
| `GET` | `/api/v1/documents/employees/{id}/download` | Bearer (Authenticated) | Download employee document file stream |
| `PUT` | `/api/v1/documents/employees/{id}` | Bearer (Authenticated) | Update employee document / upload revisions |
| `DELETE` | `/api/v1/documents/employees/{id}` | Bearer (Authenticated) | Soft delete employee document |
| `GET` | `/api/v1/documents/employees/{id}/versions` | Bearer (Authenticated) | List versions of an employee document |
| `GET` | `/api/v1/documents/employees/{id}/versions/{version_number}/download` | Bearer (Authenticated) | Download specific version of an employee document |
| `GET` | `/api/v1/documents/employees/{id}/history` | Bearer (admin_or_hr) | Get document audit history |
| `POST` | `/api/v1/documents/company` | Bearer (admin_or_hr) | Upload company document |
| `GET` | `/api/v1/documents/company` | Bearer (Authenticated) | List company documents |
| `GET` | `/api/v1/documents/company/{id}` | Bearer (Authenticated) | Get company document details |
| `GET` | `/api/v1/documents/company/{id}/download` | Bearer (Authenticated) | Download company document file stream |
| `PUT` | `/api/v1/documents/company/{id}` | Bearer (admin_or_hr) | Update company document / upload new revision |
| `DELETE` | `/api/v1/documents/company/{id}` | Bearer (admin_or_hr) | Soft delete company document |
| `POST` | `/api/v1/documents/{id}/request-signature` | Bearer (admin_or_hr) | Request signature on a document |
| `POST` | `/api/v1/documents/{id}/sign` | Bearer (Authenticated) | Sign a document digitally |
| `GET` | `/api/v1/documents/{id}/signature-status` | Bearer (Authenticated) | Get signature status |
| `PATCH` | `/api/v1/documents/{id}/verify` | Bearer (admin_or_hr) | Verify / approve employee document |
| `PATCH` | `/api/v1/documents/{id}/reject` | Bearer (admin_or_hr) | Reject employee document |
| `PATCH` | `/api/v1/documents/{id}/request-reupload` | Bearer (admin_or_hr) | Request re-upload of employee document |
| `GET` | `/api/v1/documents/expiring` | Bearer (admin_or_hr) | Get documents expiring soon |
| `GET` | `/api/v1/documents/expired` | Bearer (admin_or_hr) | Get already expired documents |
| `GET` | `/api/v1/documents/summary` | Bearer (Authenticated) | Get document summary statistics |
| `POST` | `/api/v1/documents/upload` | Bearer (admin_or_hr) | Upload document for Google Document AI OCR processing |
| `GET` | `/api/v1/documents` | Bearer (Authenticated) | List all uploaded OCR documents (OCR History) |
| `GET` | `/api/v1/documents/{document_id}` | Bearer (Authenticated) | Get document OCR details |
| `GET` | `/api/v1/documents/{document_id}/json` | Bearer (Authenticated) | Download full OCR JSON response |
| `POST` | `/api/v1/document-templates` | Bearer (admin_or_hr) | Create a new document template |
| `GET` | `/api/v1/document-templates` | Bearer (Authenticated) | List all document templates |
| `POST` | `/api/v1/document-templates/{id}/generate` | Bearer (admin_or_hr) | Generate document from template for employee |
| `GET` | `/api/v1/ai/policy/documents` | Bearer (Authenticated) | Get Available Policy Documents |
| `GET` | `/api/v1/ai-hub/document-generator` | Bearer (Authenticated) | Document Generator Overview |
| `GET` | `/api/v1/ai-hub/document-generator/templates` | Bearer (Authenticated) | List Document Templates |
| `POST` | `/api/v1/ai-hub/document-generator/generate` | Bearer (Authenticated) | Generate and Persist Document |
| `POST` | `/api/v1/ai-hub/document-generator/preview` | Bearer (Authenticated) | Preview Rendered Template |
| `GET` | `/api/v1/profile/documents` | Bearer (Authenticated) | Get Profile Documents |
| `GET` | `/api/v1/compliance/documents` | Bearer (Authenticated) | List Compliance Documents |
| `GET` | `/api/v1/documents/` | Bearer (Authenticated) | List Company Documents |
| `POST` | `/api/v2/document-intelligence/upload` | Bearer (admin_or_manager) | Upload and register business documents |
| `POST` | `/api/v2/document-intelligence/classify` | Bearer (admin_or_manager) | Automatically classify document content type |
| `POST` | `/api/v2/document-intelligence/extract` | Bearer (admin_or_manager) | Extract fields matching requested schema |
| `POST` | `/api/v2/document-intelligence/analyze` | Bearer (admin_or_manager) | Generate document summary, risk levels, compliance analysis |
| `POST` | `/api/v2/document-intelligence/compare` | Bearer (admin_or_manager) | Compare two business documents for modifications |
| `POST` | `/api/v2/document-intelligence/validate` | Bearer (admin_or_manager) | Run validation checks on extracted details |
| `POST` | `/api/v2/document-intelligence/search` | Bearer (admin_or_manager) | Semantic vector search across candidate/business files |
| `POST` | `/api/v2/document-intelligence/query` | Bearer (admin_or_manager) | Natural language Question Answering RAG pipeline |
| `GET` | `/api/v2/document-intelligence/insights` | Bearer (admin_or_manager) | Retrieve global intelligence insights for all documents |
| `POST` | `/api/v2/policies/documents` | Bearer (employee_or_above) | Upload policy manual and generate RAG vector chunk mappings |

### Compliance (24 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ai/compliance/dashboard` | Bearer (Authenticated) | Get AI Compliance Monitor Dashboard KPIs |
| `GET` | `/api/v1/ai/compliance/checks` | Bearer (Authenticated) | Get Compliance Checks Status |
| `GET` | `/api/v1/ai/compliance/labor-laws` | Bearer (Authenticated) | Get Labor Law Monitoring |
| `GET` | `/api/v1/ai/compliance/missing-documents` | Bearer (Authenticated) | Get Missing & Expired Documents |
| `GET` | `/api/v1/ai/compliance/risks` | Bearer (Authenticated) | Get Compliance Risk Detection |
| `GET` | `/api/v1/ai/compliance/audit-readiness` | Bearer (Authenticated) | Get Audit Readiness |
| `GET` | `/api/v1/ai/compliance/analytics` | Bearer (Authenticated) | Get Compliance Analytics |
| `GET` | `/api/v1/ai/compliance/alerts` | Bearer (Authenticated) | Get Critical Compliance Alerts |
| `GET` | `/api/v1/ai/compliance/report` | Bearer (Authenticated) | Get Comprehensive Compliance Report |
| `GET` | `/api/v1/ai/compliance/employee/{employee_id}` | Bearer (Authenticated) | Get Employee Compliance Details |
| `POST` | `/api/v1/ai/compliance/analyze` | Bearer (Authenticated) | Analyze Compliance via AI Engine |
| `POST` | `/api/v1/ai/compliance/audit` | Bearer (Authenticated) | Run AI Compliance Audit |
| `POST` | `/api/v1/ai/compliance/risk-analysis` | Bearer (Authenticated) | Run AI Risk Analysis |
| `GET` | `/api/v1/ai/analytics/compliance` | Bearer (Authenticated) | Get Compliance Analytics |
| `GET` | `/api/v1/ai-hub/compliance-monitor` | Bearer (Authenticated) | Compliance Monitor Overview |
| `GET` | `/api/v1/ai-hub/compliance-monitor/checklist` | Bearer (Authenticated) | Compliance Checklist |
| `GET` | `/api/v1/ai-hub/compliance-monitor/score` | Bearer (Authenticated) | Compliance & Audit Readiness Score |
| `POST` | `/api/v1/ai-hub/compliance-monitor/scan` | Bearer (Authenticated) | Execute Compliance Scan |
| `GET` | `/api/v1/compliance/` | Bearer (Authenticated) | List Compliance |
| `GET` | `/api/v1/compliance` | Bearer (Authenticated) | List Compliance |
| `GET` | `/api/v1/compliance/dashboard` | Bearer (Authenticated) | Get Compliance Dashboard |
| `GET` | `/api/v1/compliance/status` | Bearer (Authenticated) | Get Compliance Status |
| `GET` | `/api/v2/reports/analytics/compliance` | Bearer (analytics_access) | Get statutory compliance obligations and status counts |
| `POST` | `/api/v2/compliance/audit` | Bearer (admin_or_manager, admin_or_manager) | Run AI compliance audit |

### Reports (82 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/assets/analytics` | Bearer (admin_or_hr) | Get aggregated asset analytics data |
| `POST` | `/api/v1/ai/chat/analytics` | Bearer (Authenticated) | Run Workforce Analytics Query |
| `GET` | `/api/v1/ai/recruiter/analytics` | Bearer (Authenticated) | Get Recruitment Analytics |
| `GET` | `/api/v1/ai/workforce/analytics` | Bearer (Authenticated) | Get Workforce Analytics Overview |
| `GET` | `/api/v1/ai/employee-health/analytics` | Bearer (Authenticated) | Get Employee Health Analytics |
| `GET` | `/api/v1/ai/analytics/dashboard` | Bearer (Authenticated) | Get Complete AI Insights Dashboard Data |
| `GET` | `/api/v1/ai/analytics/kpis` | Bearer (Authenticated) | Get Executive Analytics KPIs |
| `GET` | `/api/v1/ai/analytics/headcount-forecast` | Bearer (Authenticated) | Get Headcount Forecast |
| `GET` | `/api/v1/ai/analytics/hiring-demand` | Bearer (Authenticated) | Get Department Hiring Demand |
| `GET` | `/api/v1/ai/analytics/skill-gap` | Bearer (Authenticated) | Get Skill Gap Analysis |
| `GET` | `/api/v1/ai/analytics/workforce` | Bearer (Authenticated) | Get Workforce Intelligence |
| `GET` | `/api/v1/ai/analytics/health` | Bearer (Authenticated) | Get Employee Health Analytics |
| `GET` | `/api/v1/ai/analytics/attrition` | Bearer (Authenticated) | Get Attrition Prediction Metrics |
| `GET` | `/api/v1/ai/analytics/summary` | Bearer (Authenticated) | Get AI Executive Summary |
| `POST` | `/api/v1/ai/analytics/generate` | Bearer (Authenticated) | Trigger Analytics Computation |
| `POST` | `/api/v1/ai/analytics/predict` | Bearer (Authenticated) | Run Predictive Model Simulation |
| `GET` | `/api/v1/ai-insights/analytics` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai/insights` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai/hiring` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai/analytics` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai/dashboard` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/hierarchy/analytics` | Bearer (Authenticated) | Get hierarchy analytics metrics |
| `GET` | `/api/v1/reports/engagement/summary` | Bearer (admin_or_manager) | Get Company Engagement Summary Metrics |
| `GET` | `/api/v1/reports/engagement/trend` | Bearer (admin_or_manager) | Get Engagement Historical Trends |
| `GET` | `/api/v1/reports/engagement/enps-trend` | Bearer (admin_or_manager) | Get eNPS Historical Trends |
| `GET` | `/api/v1/reports/engagement/breakdown` | Bearer (admin_or_manager) | Get Engagement Breakdown by Department |
| `GET` | `/api/v1/reports/engagement/surveys` | Bearer (admin_or_manager) | List Engagement Surveys & Polls |
| `GET` | `/api/v1/reports/culture/telemetry` | Bearer (admin_or_manager) | Get Organizational Culture & D&I Telemetry |
| `GET` | `/api/v1/reports/culture/trend` | Bearer (admin_or_manager) | Get Culture Historical Trends |
| `GET` | `/api/v1/reports/culture/breakdown` | Bearer (admin_or_manager) | Get Culture Breakdown by Department |
| `GET` | `/api/v1/reports/culture/feedback` | Bearer (admin_or_manager) | Get Aggregated Culture & Feedback Analytics |
| `GET` | `/api/v1/ai-hub/analytics-center` | Bearer (Authenticated) | Analytics Center Overview |
| `GET` | `/api/v1/ai-hub/analytics-center/attrition` | Bearer (Authenticated) | Attrition & Flight Risk Analytics |
| `GET` | `/api/v1/ai-hub/analytics-center/diversity` | Bearer (Authenticated) | Workforce Diversity Analytics |
| `GET` | `/api/v1/ai-hub/analytics-center/executive-summary` | Bearer (Authenticated) | Executive Summary |
| `POST` | `/api/v1/ai-hub/analytics-center/analyze` | Bearer (Authenticated) | Execute Targeted Analytics Analysis |
| `GET` | `/api/v1/analytics/dashboard` | Bearer (Authenticated) | Get Analytics Dashboard |
| `GET` | `/api/v1/analytics/headcount` | Bearer (Authenticated) | Get Headcount Metric |
| `GET` | `/api/v1/analytics/realtime` | Bearer (Authenticated) | Get Realtime Metrics |
| `GET` | `/api/v1/analytics/export` | Bearer (Authenticated) | Export Analytics |
| `GET` | `/api/v1/analytics/comparison` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/yearly` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/monthly` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/trends` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/absenteeism` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/overtime` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/productivity` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/workforce` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/designations` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/departments` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/turnover` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/retention` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/attrition` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/leave` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/employees` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/analytics/overview` | Bearer (Authenticated) | Get Generic Metric |
| `GET` | `/api/v1/employee-health/analytics` | Bearer (Authenticated) | Get Health Analytics |
| `GET` | `/api/v1/reports/` | Bearer (Authenticated) | List Available Reports |
| `GET` | `/api/v1/reports` | Bearer (Authenticated) | List Available Reports |
| `GET` | `/api/v1/reports/export` | Bearer (Authenticated) | Export Report Async |
| `GET` | `/api/v2/hr-analytics/dashboard` | Bearer (admin_or_manager) | Get unified executive HR dashboard metrics |
| `POST` | `/api/v2/hr-analytics/snapshots` | Bearer (admin_or_manager) | Trigger new manual analytics snapshot computation |
| `POST` | `/api/v2/hr-analytics/attrition-prediction/{employee_id}` | Bearer (admin_or_manager) | Evaluate attrition risk score for an employee |
| `POST` | `/api/v2/hr-analytics/forecast` | Bearer (admin_or_manager) | Run AI predictive workforce forecasts |
| `GET` | `/api/v2/reports` | Bearer (analytics_access) | List generated and scheduled reports |
| `GET` | `/api/v2/reports/stats` | Bearer (analytics_access) | Get report stats dashboard overview |
| `POST` | `/api/v2/reports` | Bearer (analytics_access) | Generate or schedule a new report |
| `POST` | `/api/v2/reports/{id}/refresh` | Bearer (analytics_access) | Refresh report compilation data |
| `DELETE` | `/api/v2/reports/{id}` | Bearer (analytics_access) | Delete a report log entry |
| `GET` | `/api/v2/reports/analytics/headcount` | Bearer (analytics_access) | Get headcount growth analytics |
| `GET` | `/api/v2/reports/analytics/department` | Bearer (analytics_access) | Get department-wise employee distribution |
| `GET` | `/api/v2/reports/analytics/tenure` | Bearer (analytics_access) | Get tenure ranges distribution |
| `GET` | `/api/v2/reports/analytics/turnover` | Bearer (analytics_access) | Get monthly employee turnover and separations |
| `GET` | `/api/v2/reports/export` | Bearer (analytics_access) | Export analytics dataset as CSV |
| `GET` | `/api/v2/analytics/dashboard` | Bearer (admin_or_manager, admin_or_manager) | Get recruitment dashboard summary |
| `GET` | `/api/v2/analytics/hiring-funnel` | Bearer (admin_or_manager, admin_or_manager) | Get hiring funnel with stage-by-stage conversion |
| `GET` | `/api/v2/analytics/offer-acceptance-rate` | Bearer (admin_or_manager, admin_or_manager) | Get offer acceptance rate |
| `GET` | `/api/v2/analytics/time-to-hire` | Bearer (admin_or_manager, admin_or_manager) | Get average time-to-hire metrics |
| `GET` | `/api/v2/analytics/source-performance` | Bearer (admin_or_manager, admin_or_manager) | Analyze sourcing channel performance |
| `GET` | `/api/v2/analytics/recruiter-performance` | Bearer (admin_or_manager, admin_or_manager) | Get recruiter performance metrics |
| `GET` | `/api/v2/analytics/department` | Bearer (admin_or_manager, admin_or_manager) | Get department-level hiring analytics |
| `GET` | `/api/v2/analytics/interview-success` | Bearer (admin_or_manager, admin_or_manager) | Get interview completion and pass rates |

### AI/Intelligence (163 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/ai/upload-resume` | Bearer (admin_or_hr) | Stage 1 — Upload Candidate Resume |
| `POST` | `/api/v1/ai/extract` | Bearer (admin_or_hr) | Stage 2 — Extract Structured Resume Data |
| `POST` | `/api/v1/ai/embedding` | Bearer (admin_or_hr) | Stage 3 — Generate Resume & Job Embeddings |
| `POST` | `/api/v1/ai/match` | Bearer (admin_or_hr) | Stage 3 — Semantic Skill Matching |
| `POST` | `/api/v1/ai/analyze` | Bearer (admin_or_hr) | Stage 4 — AI Qualitative Evaluation via Llama3 |
| `POST` | `/api/v1/ai/rank` | Bearer (admin_or_hr) | Stage 5 — Compute Multi-Dimensional Ranking Scores |
| `POST` | `/api/v1/ai/interview` | Bearer (admin_or_hr) | Stage 6 — Generate Targeted Interview Questions |
| `GET` | `/api/v1/ai/dashboard/{resume_document_id}` | Bearer (admin_or_hr) | Stage 7 — Candidate AI Hiring Dashboard |
| `GET` | `/api/v1/ai/job-ranking/{job_id}` | Bearer (admin_or_hr) | Get Ranked Candidates for a Job |
| `POST` | `/api/v1/ai/copilot` | Bearer (admin_or_hr) | Interactive AI Recruiter Copilot |
| `POST` | `/api/v1/ai/chat/query` | Bearer (Authenticated) | Process Natural Language Chat Query (Alias) |
| `POST` | `/api/v1/ai/chat/message` | Bearer (Authenticated) | Send Message to AI Assistant (Alias) |
| `POST` | `/api/v1/ai/chat/` | Bearer (Authenticated) | Process Natural Language AI Chat Query (Slash) |
| `POST` | `/api/v1/ai/chat` | Bearer (Authenticated) | Process Natural Language AI Chat Query |
| `POST` | `/api/v1/ai/chat/conversations` | Bearer (Authenticated) | Create New Chat Conversation |
| `POST` | `/api/v1/ai/chat/report` | Bearer (Authenticated) | Generate HR Report via AI Copilot |
| `POST` | `/api/v1/ai/chat/recommendations` | Bearer (Authenticated) | Generate AI Copilot Recommendations |
| `GET` | `/api/v1/ai/chat/conversations` | Bearer (Authenticated) | List Chat Conversations (Alias) |
| `GET` | `/api/v1/ai/chat/history` | Bearer (Authenticated) | Get Chat Conversation History |
| `GET` | `/api/v1/ai/chat/conversations/{conversation_id}` | Bearer (Authenticated) | Get Specific Chat Conversation Detail (Alias) |
| `GET` | `/api/v1/ai/chat/history/{conversation_id}` | Bearer (Authenticated) | Get Specific Chat Conversation Detail |
| `DELETE` | `/api/v1/ai/chat/conversations/{conversation_id}` | Bearer (Authenticated) | Delete Chat Conversation (Alias) |
| `DELETE` | `/api/v1/ai/chat/history/{conversation_id}` | Bearer (Authenticated) | Delete Chat Conversation |
| `GET` | `/api/v1/ai/chat/suggestions` | Bearer (Authenticated) | Get Suggested Copilot Prompts |
| `POST` | `/api/v1/ai/chat/feedback` | Bearer (Authenticated) | Submit Chat Response Feedback |
| `GET` | `/api/v1/ai/recruiter/dashboard` | Bearer (Authenticated) | Get AI Recruiter Dashboard KPIs |
| `GET` | `/api/v1/ai/recruiter/funnel` | Bearer (Authenticated) | Get Candidate Funnel Chart data |
| `GET` | `/api/v1/ai/recruiter/match-distribution` | Bearer (Authenticated) | Get JD Match Distribution Buckets |
| `GET` | `/api/v1/ai/recruiter/candidate/{id}/score` | Bearer (Authenticated) | Get Candidate Multi-Dimensional Score |
| `GET` | `/api/v1/ai/recruiter/candidate/{id}/recommendation` | Bearer (Authenticated) | Get AI Hiring Recommendation for Candidate |
| `POST` | `/api/v1/ai/recruiter/resume/analyze` | Bearer (Authenticated) | Perform Automated Resume Screening & Skill Extraction |
| `POST` | `/api/v1/ai/recruiter/match` | Bearer (Authenticated) | Perform Semantic JD-Candidate Matching |
| `POST` | `/api/v1/ai/recruiter/rank` | Bearer (Authenticated) | Rank Candidates for Job Position |
| `POST` | `/api/v1/ai/recruiter/interview/questions` | Bearer (Authenticated) | Generate AI Interview Questions |
| `POST` | `/api/v1/ai-workforce/run-mode` | Public (None) | Run AI Agent Mode |
| `GET` | `/api/v1/ai-workforce/dashboard/stats` | Public (None) | Get AI Agent Telemetry Dashboard Stats |
| `GET` | `/api/v1/ai-workforce/agents` | Public (None) | List all AI Agent Configurations |
| `PUT` | `/api/v1/ai-workforce/agents/{agent_key}` | Public (None) | Update AI Agent Config |
| `GET` | `/api/v1/ai/employee-health/dashboard` | Bearer (Authenticated) | Get AI Employee Health Dashboard KPIs |
| `GET` | `/api/v1/ai/employee-health/kpi` | Bearer (Authenticated) | Get AI Employee Health KPIs |
| `GET` | `/api/v1/ai/employee-health/wellbeing-score` | Bearer (Authenticated) | Get Wellbeing Score |
| `GET` | `/api/v1/ai/employee-health/burnout-risk` | Bearer (Authenticated) | Get Burnout Risk Analysis |
| `GET` | `/api/v1/ai/employee-health/workload-analysis` | Bearer (Authenticated) | Get Workload Analysis |
| `GET` | `/api/v1/ai/employee-health/overtime` | Bearer (Authenticated) | Get Overtime Monitoring Metrics |
| `GET` | `/api/v1/ai/employee-health/stress-indicators` | Bearer (Authenticated) | Get Stress Indicators |
| `GET` | `/api/v1/ai/employee-health/burnout-trend` | Bearer (Authenticated) | Get Burnout Trend |
| `GET` | `/api/v1/ai/employee-health/team-overtime` | Bearer (Authenticated) | Get Team Overtime Breakdown |
| `GET` | `/api/v1/ai/employee-health/employee/{employee_id}` | Bearer (Authenticated) | Get Employee Health Details |
| `POST` | `/api/v1/ai/employee-health/analyze` | Bearer (Authenticated) | Analyze Employee Health via AI |
| `POST` | `/api/v1/ai/employee-health/burnout-analysis` | Bearer (Authenticated) | Run AI Burnout Analysis |
| `POST` | `/api/v1/ai/employee-health/workload-analysis` | Bearer (Authenticated) | Run AI Workload Analysis |
| `POST` | `/api/v1/ai/employee-health/generate-insights` | Bearer (Authenticated) | Generate AI Health Insights |
| `POST` | `/api/v1/ai/policy/chat` | Bearer (Authenticated) | Ask AI Policy Assistant Question (RAG) |
| `POST` | `/api/v1/ai/policy/search` | Bearer (Authenticated) | Semantic HR Policy Search |
| `GET` | `/api/v1/ai/policy/suggestions` | Bearer (Authenticated) | Get Suggested & Popular Policy Questions |
| `GET` | `/api/v1/ai/policy/history` | Bearer (Authenticated) | Get Conversation History |
| `GET` | `/api/v1/ai/policy/history/{conversation_id}` | Bearer (Authenticated) | Get Conversation Details |
| `DELETE` | `/api/v1/ai/policy/history/{conversation_id}` | Bearer (Authenticated) | Delete Conversation History |
| `GET` | `/api/v1/ai/policy/document/{document_id}` | Bearer (Authenticated) | Get Specific Policy Document Detail |
| `POST` | `/api/v1/ai/policy/feedback` | Bearer (Authenticated) | Submit AI Answer Feedback |
| `GET` | `/api/v1/ai/meeting/dashboard` | Bearer (Authenticated) | Get AI Meeting Intelligence Dashboard KPIs |
| `GET` | `/api/v1/ai/meeting/kpi` | Bearer (Authenticated) | Get AI Meeting Intelligence KPIs |
| `GET` | `/api/v1/ai/meeting/summaries` | Bearer (Authenticated) | Get AI Meeting Summaries |
| `GET` | `/api/v1/ai/meeting/action-items` | Bearer (Authenticated) | Get Extracted Action Items |
| `GET` | `/api/v1/ai/meeting/follow-ups` | Bearer (Authenticated) | Get Follow-up Tracking Metrics |
| `GET` | `/api/v1/ai/meeting/team-insights` | Bearer (Authenticated) | Get Team Participation & Engagement Insights |
| `GET` | `/api/v1/ai/meeting/discussion-analytics` | Bearer (Authenticated) | Get Discussion Topic Analytics |
| `GET` | `/api/v1/ai/meeting/volume` | Bearer (Authenticated) | Get Meeting Volume Analytics |
| `GET` | `/api/v1/ai/meeting/history` | Bearer (Authenticated) | Get Analyzed Meetings History |
| `GET` | `/api/v1/ai/meeting/{meeting_id}` | Bearer (Authenticated) | Get Specific Meeting Details |
| `POST` | `/api/v1/ai/meeting/analyze` | Bearer (Authenticated) | Analyze Meeting via AI Engine |
| `POST` | `/api/v1/ai/meeting/summarize` | Bearer (Authenticated) | Generate AI Meeting Summary |
| `POST` | `/api/v1/ai/meeting/extract-action-items` | Bearer (Authenticated) | Extract Action Items from Transcript |
| `POST` | `/api/v1/ai/meeting/generate-followups` | Bearer (Authenticated) | Generate Follow-up Reminders |
| `GET` | `/api/v1/ai-brain/meeting-intelligence` | Bearer (Authenticated) | Ai Brain Meeting Intelligence |
| `POST` | `/api/v1/ai-brain/meeting-intelligence` | Bearer (Authenticated) | AI Brain Meeting Intelligence Endpoint |
| `GET` | `/api/v1/ai-brain/employee-health` | Bearer (Authenticated) | Ai Brain Employee Health |
| `POST` | `/api/v1/ai-brain/employee-health` | Bearer (Authenticated) | AI Brain Employee Health Endpoint |
| `GET` | `/api/v1/ai-brain` | Bearer (Authenticated) | Ai Brain Chat |
| `POST` | `/api/v1/ai-brain` | Bearer (Authenticated) | AI Brain Chat Completion Endpoint |
| `GET` | `/api/v1/ai-insights/insights` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai-insights/hiring` | Bearer (analytics_access) | Get Ai Insights Dashboard |
| `GET` | `/api/v1/ai-insights/dashboard` | Bearer (analytics_access) | Get complete AI Insights dashboard metrics |
| `GET` | `/api/v1/ai-insights/kpi` | Bearer (analytics_access) | Get Kpis |
| `GET` | `/api/v1/ai-insights/attrition` | Bearer (analytics_access) | Get Attrition |
| `GET` | `/api/v1/ai-insights/burnout` | Bearer (analytics_access) | Get Burnout |
| `GET` | `/api/v1/ai-insights/charts` | Bearer (analytics_access) | Get Charts |
| `GET` | `/api/v1/ai-insights/recommendations` | Bearer (analytics_access) | Get Recommendations |
| `POST` | `/api/v1/connect/ai/transform` | Bearer (Authenticated) | 39. AI Communication Copilot Transform |
| `POST` | `/api/v1/helpdesk/ai/chat` | Bearer (Authenticated) | 13. Helpdesk - AI Support Copilot Chat |
| `GET` | `/api/v1/intelligence/models` | Bearer (Authenticated) | List available AI & Intelligence models |
| `GET` | `/api/v1/ai-hub` | Bearer (Authenticated) | AI Hub Service Directory |
| `GET` | `/api/v1/ai-hub/agents` | Bearer (Authenticated) | List Registered AI Agents |
| `GET` | `/api/v1/ai-hub/agents/{agentId}` | Bearer (Authenticated) | Get Agent Detail and Summary |
| `POST` | `/api/v1/ai-hub/agents/{agentId}/run` | Bearer (Authenticated) | Execute AI Agent |
| `GET` | `/api/v1/ai-hub/agents/{agentId}/history` | Bearer (Authenticated) | Get Agent Run History |
| `GET` | `/api/v1/ai-hub/agents/{agentId}/status` | Bearer (Authenticated) | Get Agent Operational Status |
| `POST` | `/api/v1/ai-hub/agents/{agentId}/feedback` | Bearer (Authenticated) | Submit Agent Feedback |
| `GET` | `/api/v1/ai-hub/chat-assistant/conversations` | Bearer (Authenticated) | List Conversations (Compatibility) |
| `POST` | `/api/v1/ai-hub/chat-assistant/conversations` | Bearer (Authenticated) | Create New Conversation (Compatibility) |
| `GET` | `/api/v1/ai-hub/chat-assistant/conversations/{conversationId}` | Bearer (Authenticated) | Get Conversation Detail (Compatibility) |
| `DELETE` | `/api/v1/ai-hub/chat-assistant/conversations/{conversationId}` | Bearer (Authenticated) | Delete Conversation (Compatibility) |
| `POST` | `/api/v1/ai-hub/chat-assistant/message` | Bearer (Authenticated) | Send Message to Assistant (Compatibility) |
| `GET` | `/api/v1/ai-hub/employee-health` | Bearer (Authenticated) | Employee Health Overview |
| `POST` | `/api/v1/ai-hub/employee-health/analyze` | Bearer (Authenticated) | Analyze Employee Health & Burnout Factors |
| `GET` | `/api/v1/ai-hub/employee-health/wellness` | Bearer (Authenticated) | Workforce Wellbeing Score & Breakdown |
| `GET` | `/api/v1/ai-hub/meeting-intelligence` | Bearer (Authenticated) | Meeting Intelligence Overview |
| `GET` | `/api/v1/ai-hub/meeting-intelligence/action-items` | Bearer (Authenticated) | List Extracted Action Items (Paginated) |
| `POST` | `/api/v1/ai-hub/meeting-intelligence/analyze` | Bearer (Authenticated) | Analyze Meeting Transcript |
| `POST` | `/api/v1/ai-hub/meeting-intelligence/summarize` | Bearer (Authenticated) | Summarize Meeting Transcript |
| `GET` | `/api/v1/ai-hub/policy-assistant` | Bearer (Authenticated) | Policy Assistant Overview |
| `POST` | `/api/v1/ai-hub/policy-assistant/ask` | Bearer (Authenticated) | Ask Policy Question via RAG |
| `POST` | `/api/v1/ai-hub/policy-assistant/check-compliance` | Bearer (Authenticated) | Check Document Compliance Against Policy |
| `GET` | `/api/v1/ai-hub/recruiter` | Bearer (Authenticated) | Recruiter Overview |
| `POST` | `/api/v1/ai-hub/recruiter/generate-questions` | Bearer (Authenticated) | Generate Tailored Interview Questions |
| `POST` | `/api/v1/ai-hub/recruiter/match-candidates` | Bearer (Authenticated) | Match Candidates Against Job Description |
| `POST` | `/api/v1/ai-hub/recruiter/screen-resumes` | Bearer (Authenticated) | Screen Batch Resumes Against Criteria |
| `GET` | `/api/v1/meeting-intelligence/` | Public (None) | Get Meeting Intelligence Status |
| `GET` | `/api/v1/meeting-intelligence` | Public (None) | Get Meeting Intelligence Status |
| `POST` | `/api/v1/meeting-intelligence/analyze` | Bearer (Authenticated) | Analyze Meeting Transcript |
| `GET` | `/api/v1/meeting-intelligence/meetings` | Bearer (Authenticated) | List Recent Meetings |
| `GET` | `/api/v1/meeting-intelligence/insights` | Bearer (Authenticated) | Get Meeting Insights |
| `POST` | `/api/v1/meeting-intelligence/dashboard` | Bearer (Authenticated) | Get Meeting Dashboard |
| `GET` | `/api/v1/meeting-intelligence/dashboard` | Bearer (Authenticated) | Meeting Intelligence Dashboard |
| `POST` | `/api/v1/meeting-intelligence/kpi` | Bearer (Authenticated) | Get Meeting Kpis |
| `GET` | `/api/v1/meeting-intelligence/kpi` | Bearer (Authenticated) | Meeting Intelligence KPIs |
| `POST` | `/api/v1/meeting-intelligence/action-items` | Bearer (Authenticated) | Get Meeting Action Items |
| `GET` | `/api/v1/meeting-intelligence/action-items` | Bearer (Authenticated) | Meeting Intelligence Action Items |
| `POST` | `/api/v1/meeting-intelligence/volume` | Bearer (Authenticated) | Get Meeting Volume Analytics |
| `GET` | `/api/v1/meeting-intelligence/volume` | Bearer (Authenticated) | Meeting Intelligence Volume Analytics |
| `GET` | `/api/v1/policy-assistant/` | Public (None) | Get Policy Assistant Status |
| `GET` | `/api/v1/policy-assistant` | Public (None) | Get Policy Assistant Status |
| `POST` | `/api/v1/policy-assistant/query` | Bearer (Authenticated) | Query Policy Assistant |
| `GET` | `/api/v1/policy-assistant/policies` | Bearer (Authenticated) | List Policies |
| `POST` | `/api/v2/interview-bot/sessions` | Bearer (admin_or_manager) | Initialize an AI Interview session |
| `POST` | `/api/v2/interview-bot/sessions/{session_id}/start` | Bearer (admin_or_manager) | Start an active AI Interview session |
| `POST` | `/api/v2/interview-bot/sessions/{session_id}/answer` | Bearer (admin_or_manager) | Submit answer for grading and get next question |
| `POST` | `/api/v2/interview-bot/sessions/{session_id}/proctor-alert` | Bearer (admin_or_manager) | Log live focus or anti-cheating alerts |
| `POST` | `/api/v2/interview-bot/sessions/{session_id}/finalize` | Bearer (admin_or_manager) | Compile final AI Scorecard report |
| `POST` | `/api/v2/wellness/checkins` | Bearer (employee_or_above) | Log daily employee wellness check-in |
| `POST` | `/api/v2/wellness/escalation-rules` | Bearer (employee_or_above) | Register HR escalation rules configuration |
| `POST` | `/api/v2/wellness/anonymous-chats` | Bearer (employee_or_above) | Create anonymous wellness coach session |
| `POST` | `/api/v2/wellness/anonymous-chats/{session_id}/messages` | Bearer (employee_or_above) | Post message and generate coach reply |
| `POST` | `/api/v2/emails/generate` | Bearer (employee_or_above) | Dynamically generate and log custom emails |
| `POST` | `/api/v2/emotions/sessions` | Bearer (employee_or_above) | Start emotion aware chatbot session |
| `POST` | `/api/v2/emotions/sessions/{session_id}/messages` | Bearer (employee_or_above) | Post message and generate emotion adjusted reply |
| `POST` | `/api/v2/org-map/generate` | Bearer (admin_or_manager, admin_or_manager) | Generate AI organization intelligence map |
| `POST` | `/api/v2/voice/command` | Bearer (employee_or_above) | Process HR voice command transcript |
| `POST` | `/api/v2/mood/detect` | Bearer (employee_or_above, employee_or_above) | Detect employee mood from text input |
| `POST` | `/api/v2/meetings/analyze` | Bearer (admin_or_manager, admin_or_manager) | Analyze meeting transcript and extract MOM, actions, decisions |
| `POST` | `/api/v2/copilot/query` | Bearer (admin_or_manager, admin_or_manager) | Ask strategic HR questions to Executive AI Copilot |
| `POST` | `/api/v2/hr-copilot/query` | Bearer (admin_or_manager, admin_or_manager) | Ask the HR Copilot a natural language question |
| `POST` | `/api/v2/hr-copilot/index/candidate` | Bearer (admin_or_manager, admin_or_manager) | Index a candidate in the vector store |
| `POST` | `/api/v2/hr-copilot/index/job` | Bearer (admin_or_manager, admin_or_manager) | Index a job description in the vector store |
| `GET` | `/api/v2/hr-copilot/vector-store/status` | Bearer (admin_or_manager, admin_or_manager) | Get vector store statistics |
| `DELETE` | `/api/v2/hr-copilot/index/candidate/{candidate_id}` | Bearer (admin_or_manager, admin_or_manager) | Remove a candidate from the vector index |
| `POST` | `/api/v2/coding-assessment/generate` | Bearer (admin_or_manager) | Generate an AI coding challenge |
| `POST` | `/api/v2/coding-assessment/generate-set` | Bearer (admin_or_manager) | Generate a set of coding challenges across topics |
| `POST` | `/api/v2/offer-letters/generate` | Bearer (admin_or_manager) | Generate an AI-powered offer letter |
| `POST` | `/api/v2/interview/generate-questions` | Bearer (admin_or_manager) | Generate AI interview questions for a candidate |
| `POST` | `/api/v1/generate` | Public (None) | Generate text via Ollama (v1 prefix) |
| `POST` | `/api/generate` | Public (None) | Generate text via Ollama |
| `GET` | `/api/intelligence/models` | Bearer (Authenticated) | List available AI & Intelligence models |

### Integrations (26 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/settings/billing` | Bearer (Authenticated) | Get Billing |
| `PUT` | `/api/v1/settings/billing` | Bearer (Authenticated) | Update Billing |
| `GET` | `/api/v1/billing/subscription` | Bearer (Authenticated) | Get Subscription |
| `GET` | `/api/v1/billing/payment-methods` | Bearer (Authenticated) | Get Payment Methods |
| `POST` | `/api/v1/billing/payment-methods` | Bearer (Authenticated) | Add Payment Method |
| `GET` | `/api/v1/billing/invoices` | Bearer (Authenticated) | Get Invoices |
| `GET` | `/api/v1/payments/plans` | Public (None) | Get Plans |
| `POST` | `/api/v1/payments/create-order` | Bearer (Authenticated) | Create Order |
| `POST` | `/api/v1/payments/verify` | Bearer (Authenticated) | Verify Payment |
| `POST` | `/api/v1/payments/webhook` | Public (None) | Handle Razorpay Webhook |
| `GET` | `/api/v1/payments/history` | Bearer (Authenticated) | Get Payment History |
| `GET` | `/api/v1/payments/{payment_id}` | Bearer (Authenticated) | Get Payment Details |
| `POST` | `/api/v1/crm/notes` | Bearer (admin_or_hr) | Add a note to a candidate |
| `GET` | `/api/v1/crm/notes/{candidate_id}` | Bearer (admin_or_hr) | List all notes for a candidate |
| `GET` | `/settings/billing` | Bearer (Authenticated) | Get Billing |
| `PUT` | `/settings/billing` | Bearer (Authenticated) | Update Billing |
| `GET` | `/billing/subscription` | Bearer (Authenticated) | Get Subscription |
| `GET` | `/billing/payment-methods` | Bearer (Authenticated) | Get Payment Methods |
| `POST` | `/billing/payment-methods` | Bearer (Authenticated) | Add Payment Method |
| `GET` | `/billing/invoices` | Bearer (Authenticated) | Get Invoices |
| `GET` | `/payments/plans` | Public (None) | Get Plans |
| `POST` | `/payments/create-order` | Bearer (Authenticated) | Create Order |
| `POST` | `/payments/verify` | Bearer (Authenticated) | Verify Payment |
| `POST` | `/payments/webhook` | Public (None) | Handle Razorpay Webhook |
| `GET` | `/payments/history` | Bearer (Authenticated) | Get Payment History |
| `GET` | `/payments/{payment_id}` | Bearer (Authenticated) | Get Payment Details |

### Admin (249 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v2/openapi.json` | Public (None) | Disable Docs Explicitly |
| `GET` | `/api/v1/openapi.json` | Public (None) | Disable Docs Explicitly |
| `GET` | `/openapi.json` | Public (None) | Disable Docs Explicitly |
| `GET` | `/redoc` | Public (None) | Disable Docs Explicitly |
| `GET` | `/docs` | Public (None) | Disable Docs Explicitly |
| `GET` | `/api/v1/internal/dashboard` | Bearer (Authenticated) | Get unified internal communication dashboard feed |
| `GET` | `/api/v1/payroll/admin/payslips` | Bearer (Authenticated) | List admin payslips |
| `GET` | `/api/v1/payroll/admin/tax` | Bearer (Authenticated) | Get tax management list for admin |
| `GET` | `/api/v1/settings/summary` | Bearer (Authenticated) | Get Settings Summary |
| `GET` | `/api/v1/settings/general` | Bearer (Authenticated) | Get General Settings |
| `PUT` | `/api/v1/settings/general` | Bearer (Authenticated) | Update General Settings |
| `GET` | `/api/v1/settings/company` | Bearer (Authenticated) | Get Company Settings |
| `PATCH` | `/api/v1/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `POST` | `/api/v1/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `PUT` | `/api/v1/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `POST` | `/api/v1/settings/company/logo` | Bearer (Authenticated) | Upload company logo |
| `GET` | `/api/v1/settings/roles` | Bearer (Authenticated) | Get Roles |
| `POST` | `/api/v1/settings/roles` | Bearer (Authenticated) | Create Role |
| `PUT` | `/api/v1/settings/roles/{role_id}` | Bearer (Authenticated) | Update Role |
| `DELETE` | `/api/v1/settings/roles/{role_id}` | Bearer (Authenticated) | Delete Role |
| `GET` | `/api/v1/settings/permissions` | Bearer (Authenticated) | Get Permissions |
| `GET` | `/api/v1/settings/audit-logs` | Bearer (Authenticated) | Get Audit Logs |
| `GET` | `/api/v1/settings/security` | Bearer (Authenticated) | Get Security |
| `PUT` | `/api/v1/settings/security` | Bearer (Authenticated) | Update Security |
| `GET` | `/api/v1/settings/integrations` | Bearer (Authenticated) | Get Integrations |
| `PUT` | `/api/v1/settings/integrations` | Bearer (Authenticated) | Toggle Integration |
| `GET` | `/api/v1/settings/hr` | Bearer (Authenticated) | Get Hr Settings |
| `POST` | `/api/v1/settings/hr` | Bearer (Authenticated) | Update Hr Settings |
| `PUT` | `/api/v1/settings/hr` | Bearer (Authenticated) | Update Hr Settings |
| `POST` | `/api/v1/settings/mfa/enable` | Bearer (Authenticated) | Enable Mfa |
| `POST` | `/api/v1/settings/mfa/disable` | Bearer (Authenticated) | Disable Mfa |
| `GET` | `/api/v1/settings/mfa/status` | Bearer (Authenticated) | Get Mfa Status |
| `POST` | `/api/v1/settings/mfa/verify` | Bearer (Authenticated) | Verify Mfa |
| `GET` | `/api/v1/sidebar` | Public (None) | Get Sidebar Permissions |
| `GET` | `/api/v1/sidebar/permissions/` | Public (None) | Get Sidebar Permissions |
| `GET` | `/api/v1/sidebar/permissions` | Public (None) | Get sidebar navigation permissions and menu structure |
| `GET` | `/api/v1/cto/dashboard` | Bearer (admin_or_manager, admin_or_manager) | Get Cto Dashboard Metrics |
| `GET` | `/api/v1/super-admin/dashboard` | Bearer (super_admin) | Get Super Admin Statistics |
| `GET` | `/api/v1/super-admin/statistics` | Bearer (super_admin) | Get Super Admin Statistics |
| `GET` | `/api/v1/super-admin/organizations` | Bearer (super_admin) | Get Super Admin Organizations |
| `POST` | `/api/v1/super-admin/organizations` | Bearer (super_admin) | Create Super Admin Organization |
| `GET` | `/api/v1/super-admin/organizations/{org_id}` | Bearer (super_admin) | Get Super Admin Organization Detail |
| `PUT` | `/api/v1/super-admin/organizations/{org_id}` | Bearer (super_admin) | Update Super Admin Organization |
| `PATCH` | `/api/v1/super-admin/organizations/{org_id}` | Bearer (super_admin) | Update Super Admin Organization |
| `DELETE` | `/api/v1/super-admin/organizations/{org_id}` | Bearer (super_admin) | Delete Super Admin Organization |
| `POST` | `/api/v1/super-admin/organizations/{org_id}/access/grant` | Bearer (super_admin) | Super Admin Org Access Grant |
| `POST` | `/api/v1/super-admin/organizations/{org_id}/access/extend` | Bearer (super_admin) | Super Admin Org Access Extend |
| `POST` | `/api/v1/super-admin/organizations/{org_id}/access/suspend` | Bearer (super_admin) | Super Admin Org Access Suspend |
| `POST` | `/api/v1/super-admin/organizations/{org_id}/access/cancel` | Bearer (super_admin) | Super Admin Org Access Cancel |
| `POST` | `/api/v1/super-admin/organizations/{org_id}/access/reactivate` | Bearer (super_admin) | Super Admin Org Access Reactivate |
| `GET` | `/api/v1/super-admin/users` | Bearer (super_admin) | Get Super Admin Users |
| `GET` | `/api/v1/super-admin/users/{user_id}` | Bearer (super_admin) | Get Super Admin User Detail |
| `POST` | `/api/v1/super-admin/users` | Bearer (super_admin) | Create Super Admin User |
| `PUT` | `/api/v1/super-admin/users/{user_id}` | Bearer (super_admin) | Update Super Admin User |
| `PATCH` | `/api/v1/super-admin/users/{user_id}` | Bearer (super_admin) | Update Super Admin User |
| `DELETE` | `/api/v1/super-admin/users/{user_id}` | Bearer (super_admin) | Delete Super Admin User |
| `POST` | `/api/v1/super-admin/users/{user_id}/activate` | Bearer (super_admin) | Activate Super Admin User |
| `POST` | `/api/v1/super-admin/users/{user_id}/deactivate` | Bearer (super_admin) | Deactivate Super Admin User |
| `POST` | `/api/v1/super-admin/users/{user_id}/toggle-status` | Bearer (super_admin) | Toggle Super Admin User Status |
| `POST` | `/api/v1/super-admin/users/{user_id}/reset-password` | Bearer (super_admin) | Reset Super Admin User Password |
| `GET` | `/api/v1/super-admin/hr-admins` | Bearer (super_admin) | Get Super Admin Hr Admins |
| `POST` | `/api/v1/super-admin/hr-admins` | Bearer (super_admin) | Create Super Admin Hr Admin |
| `PATCH` | `/api/v1/super-admin/hr-admins/{admin_id}` | Bearer (super_admin) | Update Super Admin Hr Admin |
| `DELETE` | `/api/v1/super-admin/hr-admins/{admin_id}` | Bearer (super_admin) | Delete Super Admin Hr Admin |
| `POST` | `/api/v1/super-admin/hr-admins/{admin_id}/assign` | Bearer (super_admin) | Assign Super Admin Hr Admin |
| `POST` | `/api/v1/super-admin/hr-admins/{admin_id}/remove-org` | Bearer (super_admin) | Remove Super Admin Hr Admin Org |
| `GET` | `/api/v1/super-admin/subscriptions` | Bearer (super_admin) | Get Super Admin Subscriptions |
| `GET` | `/api/v1/super-admin/subscriptions/{sub_id}` | Bearer (super_admin) | Get Super Admin Subscription Detail |
| `PATCH` | `/api/v1/super-admin/subscriptions/{sub_or_org_id}` | Bearer (super_admin) | Update Super Admin Subscription |
| `GET` | `/api/v1/super-admin/plans` | Bearer (super_admin) | Get Super Admin Plans |
| `POST` | `/api/v1/super-admin/plans` | Bearer (super_admin) | Create Super Admin Plan |
| `PATCH` | `/api/v1/super-admin/plans/{plan_id}` | Bearer (super_admin) | Update Super Admin Plan |
| `DELETE` | `/api/v1/super-admin/plans/{plan_id}` | Bearer (super_admin) | Delete Super Admin Plan |
| `GET` | `/api/v1/super-admin/entitlements` | Bearer (super_admin) | Get Super Admin Entitlements |
| `PATCH` | `/api/v1/super-admin/entitlements` | Bearer (super_admin) | Update Super Admin Entitlements |
| `PUT` | `/api/v1/super-admin/entitlements` | Bearer (super_admin) | Update Super Admin Entitlements |
| `GET` | `/api/v1/super-admin/payments` | Bearer (super_admin) | Get Super Admin Payments |
| `GET` | `/api/v1/super-admin/billing` | Bearer (super_admin) | Get Super Admin Payments |
| `GET` | `/api/v1/super-admin/security` | Bearer (super_admin) | Get Super Admin Security |
| `GET` | `/api/v1/super-admin/security/events` | Bearer (super_admin) | Get Super Admin Security Events |
| `GET` | `/api/v1/super-admin/security/alerts` | Bearer (super_admin) | Get Super Admin Security Alerts |
| `POST` | `/api/v1/super-admin/security/events/{event_id}/resolve` | Bearer (super_admin) | Resolve Super Admin Security Event |
| `POST` | `/api/v1/super-admin/security/block-ip` | Bearer (super_admin) | Block Ip Address |
| `POST` | `/api/v1/super-admin/security/unblock-ip` | Bearer (super_admin) | Unblock Ip Address |
| `GET` | `/api/v1/super-admin/security/sessions` | Bearer (super_admin) | Get Super Admin Sessions |
| `POST` | `/api/v1/super-admin/security/sessions/{session_id}/terminate` | Bearer (super_admin) | Terminate Super Admin Session |
| `POST` | `/api/v1/super-admin/security/sessions/terminate-all` | Bearer (super_admin) | Terminate All Super Admin Sessions |
| `GET` | `/api/v1/super-admin/audit-logs` | Bearer (super_admin) | Get Super Admin Audit Logs |
| `DELETE` | `/api/v1/super-admin/audit-logs` | Bearer (super_admin) | Clear Super Admin Audit Logs |
| `GET` | `/api/v1/super-admin/system-health` | Bearer (super_admin) | Get Super Admin System Health |
| `GET` | `/api/v1/super-admin/settings` | Bearer (super_admin) | Get Super Admin Settings |
| `PUT` | `/api/v1/super-admin/settings` | Bearer (super_admin) | Update Super Admin Settings |
| `PATCH` | `/api/v1/super-admin/settings` | Bearer (super_admin) | Update Super Admin Settings |
| `GET` | `/api/v1/super-admin/onboarding` | Bearer (super_admin) | Get Super Admin Onboarding |
| `GET` | `/api/v1/super-admin/onboarding/{org_id}` | Bearer (super_admin) | Get Super Admin Org Onboarding |
| `POST` | `/api/v1/super-admin/onboarding/{org_id}/fast-track` | Bearer (super_admin) | Fast Track Super Admin Onboarding |
| `GET` | `/api/v1/super-admin/analytics` | Bearer (super_admin) | Get Super Admin Analytics |
| `GET` | `/api/v1/super-admin/analytics/ai-usage` | Bearer (super_admin) | Get Super Admin Ai Usage |
| `GET` | `/api/v1/super-admin/announcements` | Bearer (super_admin) | Get Super Admin Announcements |
| `POST` | `/api/v1/super-admin/announcements` | Bearer (super_admin) | Create Super Admin Announcement |
| `PATCH` | `/api/v1/super-admin/announcements/{ann_id}` | Bearer (super_admin) | Update Super Admin Announcement |
| `DELETE` | `/api/v1/super-admin/announcements/{ann_id}` | Bearer (super_admin) | Delete Super Admin Announcement |
| `GET` | `/api/v1/onboarding/admin-profile` | Public (None) | Get Admin Profile |
| `PUT` | `/api/v1/onboarding/admin-profile` | Public (None) | Save Admin Profile |
| `POST` | `/api/v1/onboarding/admin-profile` | Public (None) | Save Admin Profile |
| `GET` | `/api/v1/admin/employee-onboarding` | Bearer (admin_or_hr) | List Progress |
| `GET` | `/api/v1/admin/employee-onboarding/{employee_id}` | Bearer (admin_or_hr) | Get Progress Details |
| `PUT` | `/api/v1/admin/employee-onboarding/{employee_id}/document/{doc_id}/verify` | Bearer (admin_or_hr) | Verify Onboarding Document |
| `GET` | `/api/v1/hr-admin/onboarding/admin-profile` | Public (None) | Get HR Admin Profile (Alias) |
| `PUT` | `/api/v1/hr-admin/onboarding/admin-profile` | Public (None) | Update Admin Profile (Alias) |
| `POST` | `/api/v1/hr-admin/onboarding/admin-profile` | Public (None) | Create/Update Admin Profile (Alias) |
| `GET` | `/api/v1/exports/face-attendance` | Bearer (export_permission) | Export Face Attendance |
| `POST` | `/api/v1/referrals` | Bearer (admin_or_hr) | Submit employee referral |
| `GET` | `/api/v1/referrals` | Bearer (admin_or_hr) | List all employee referrals |
| `PUT` | `/api/v1/referrals/{id}/status` | Bearer (admin_or_hr) | Update employee referral status |
| `POST` | `/api/v1/automations/rules` | Bearer (admin_or_hr) | Create automation rule |
| `GET` | `/api/v1/automations/rules` | Bearer (admin_or_hr) | List automation rules |
| `GET` | `/api/v1/helpdesk/admin/tickets` | Bearer (Authenticated) | 7. Helpdesk - Get All Helpdesk Tickets (Admin/Manager) |
| `POST` | `/api/v1/helpdesk/admin/faqs` | Bearer (Authenticated) | 12. Helpdesk - Create or Update FAQ (Admin) |
| `GET` | `/api/v1/helpdesk/admin/metrics` | Bearer (Authenticated) | 14. Helpdesk - Get SLA & KPI Metrics (Admin/Executive) |
| `GET` | `/api/v1/settings/` | Bearer (Authenticated) | Get Settings |
| `PUT` | `/api/v1/settings/` | Bearer (Authenticated) | Update Settings |
| `GET` | `/api/v1/settings/workflow` | Bearer (Authenticated) | Get Settings Section |
| `GET` | `/api/v1/settings/leave` | Bearer (Authenticated) | Get Settings Section |
| `PUT` | `/api/v1/settings/workflow` | Bearer (Authenticated) | Update Settings Section Endpoint |
| `PUT` | `/api/v1/settings/leave` | Bearer (Authenticated) | Update Settings Section Endpoint |
| `GET` | `/api/v1/settings/employment-types` | Bearer (Authenticated) | List Employment Types |
| `POST` | `/api/v1/settings/employment-types` | Bearer (Authenticated) | Create Employment Type |
| `GET` | `/api/v1/settings/designations` | Bearer (Authenticated) | List Designations |
| `POST` | `/api/v1/settings/designations` | Bearer (Authenticated) | Create Designation |
| `GET` | `/api/v1/settings/holidays` | Bearer (Authenticated) | List Holidays |
| `POST` | `/api/v1/settings/holidays` | Bearer (Authenticated) | Create Holiday |
| `GET` | `/api/v1/employee-health/` | Bearer (Authenticated) | Get Health Overview |
| `GET` | `/api/v1/employee-health` | Bearer (Authenticated) | Get Health Overview |
| `GET` | `/api/v1/employee-health/records` | Bearer (Authenticated) | List Health Records |
| `POST` | `/api/v1/employee-health/dashboard` | Bearer (Authenticated) | Get Employee Health Dashboard |
| `GET` | `/api/v1/employee-health/dashboard` | Bearer (Authenticated) | Employee Health Dashboard |
| `POST` | `/api/v1/employee-health/kpi` | Bearer (Authenticated) | Get Employee Health Kpis |
| `GET` | `/api/v1/employee-health/kpi` | Bearer (Authenticated) | Employee Health KPIs |
| `POST` | `/api/v1/employee-health/burnout-trend` | Bearer (Authenticated) | Get Employee Burnout Trend |
| `GET` | `/api/v1/employee-health/burnout-trend` | Bearer (Authenticated) | Employee Burnout Trend |
| `POST` | `/api/v1/employee-health/overtime` | Bearer (Authenticated) | Get Employee Overtime |
| `GET` | `/api/v1/employee-health/overtime` | Bearer (Authenticated) | Employee Health Overtime Metrics |
| `GET` | `/api/v1/holidays/` | Bearer (Authenticated) | List Holidays |
| `GET` | `/api/v1/holidays` | Bearer (Authenticated) | List Holidays |
| `GET` | `/api/v1/dashboard/` | Bearer (Authenticated) | Get Landing Dashboard |
| `GET` | `/api/v1/dashboard` | Bearer (Authenticated) | Get Landing Dashboard |
| `POST` | `/api/v2/employee-support/chat` | Bearer (employee_or_above) | Chat with the Employee Support AI Assistant |
| `POST` | `/api/v2/employee-support/tickets` | Bearer (employee_or_above) | Create a support ticket manually |
| `GET` | `/api/v2/employee-support/tickets/my` | Bearer (employee_or_above) | Retrieve logged tickets for current employee |
| `PATCH` | `/api/v2/employee-support/tickets/{ticket_id}` | Bearer (employee_or_above) | Update support ticket status or comment |
| `GET` | `/api/v2/employee-support/hr-copilot/stats` | Bearer (employee_or_above) | Aggregate support statistics for HR managers |
| `POST` | `/api/v2/workflows/definitions` | Bearer (admin_or_manager) | Register a new workflow rule definition |
| `POST` | `/api/v2/workflows/trigger` | Bearer (admin_or_manager) | Manually trigger a workflow process instance |
| `PATCH` | `/api/v2/workflows/steps/{step_id}/decision` | Bearer (admin_or_manager) | Submit approval or rejection step decision |
| `GET` | `/api/v2/workflows/instances/my-pending` | Bearer (admin_or_manager) | Get pending approval workflow steps assigned to user |
| `POST` | `/api/v2/tax/calculate` | Bearer (Authenticated) | Run TDS tax calculation |
| `POST` | `/api/v2/tax/declarations/{declaration_id}/approve` | Bearer (Authenticated) | Approve tax declaration |
| `POST` | `/api/v2/tax/declarations/{declaration_id}/reject` | Bearer (Authenticated) | Reject tax declaration |
| `POST` | `/api/v2/tax/proofs/{proof_id}/verify` | Bearer (Authenticated) | Verify tax proof document |
| `POST` | `/api/v2/tax/year-end-process` | Bearer (Authenticated) | Lock FY and generate Form 16 |
| `GET` | `/api/v2/tax/audit-logs/{employee_id}` | Bearer (Authenticated) | Get tax audit logs for employee |
| `POST` | `/api/v2/policies/chat` | Bearer (employee_or_above) | Query company policies chatbot using vector search context |
| `GET` | `/api/v2/travel` | Bearer (employee_or_above) | List all travel requests with filtering and searching |
| `GET` | `/api/v2/travel/stats` | Bearer (employee_or_above) | Get travel request summary statistics |
| `POST` | `/api/v2/travel` | Bearer (employee_or_above) | Create a new travel request |
| `PUT` | `/api/v2/travel/{id}` | Bearer (employee_or_above) | Update travel request details |
| `POST` | `/api/v2/travel/{id}/advance` | Bearer (employee_or_above) | Advance travel request to the next workflow stage |
| `DELETE` | `/api/v2/travel/{id}` | Bearer (employee_or_above) | Delete a travel request |
| `POST` | `/api/v2/productivity/logs` | Bearer (admin_or_manager) | Record daily tracked employee productivity metrics |
| `POST` | `/api/v2/productivity/forecast/{employee_id}` | Bearer (admin_or_manager) | Compile AI workforce productivity predictions and recommendations |
| `POST` | `/api/v2/compensation/benchmarks` | Bearer (admin_or_manager) | Register market salary benchmarks |
| `POST` | `/api/v2/compensation/recommendations/{employee_id}` | Bearer (admin_or_manager) | Compile AI compensation recommendations for staff members |
| `POST` | `/api/v2/behavioural/sessions` | Bearer (admin_or_manager) | Create custom behavioral interview session |
| `POST` | `/api/v2/behavioural/questions/{question_id}/respond` | Bearer (admin_or_manager) | Submit candidate response and evaluate STAR metrics |
| `POST` | `/api/v2/skill-gap/analyze` | Bearer (admin_or_manager, admin_or_manager) | Analyze skill gap for an employee |
| `POST` | `/api/v2/shifts/plans` | Bearer (admin_or_manager, admin_or_manager) | Generate AI-optimized shift plan |
| `POST` | `/api/v2/digital-twin/sync` | Bearer (admin_or_manager, admin_or_manager) | Sync and forecast employee digital twin |
| `POST` | `/api/v2/career-path/predict` | Bearer (employee_or_above, employee_or_above) | Predict AI career path for an employee |
| `GET` | `/api/v2/career-path/predictions` | Bearer (employee_or_above, employee_or_above) | Get saved career path predictions for the current employee |
| `POST` | `/api/v2/learning/recommend` | Bearer (employee_or_above) | Generate personalized learning recommendations |
| `GET` | `/api/v2/learning/recommendations` | Bearer (employee_or_above) | Get saved learning recommendations for the current employee |
| `POST` | `/api/v2/risk/assess` | Bearer (admin_or_manager, admin_or_manager) | Compute AI employee risk profile |
| `POST` | `/api/v2/matching/score` | Bearer (admin_or_manager) | Compute AI match score between resume and job |
| `POST` | `/api/v2/matching/batch-score` | Bearer (admin_or_manager) | Batch match multiple resumes against a single job |
| `GET` | `/api/v2/matching/history/{resume_document_id}` | Bearer (admin_or_manager) | Get match score history for a resume |
| `POST` | `/api/v2/coding-assessment/submit` | Bearer (admin_or_manager) | Submit code and get AI evaluation |
| `GET` | `/api/v2/coding-assessment/{assessment_id}` | Bearer (admin_or_manager) | Get coding assessment details |
| `POST` | `/api/v2/ranking/rank` | Bearer (admin_or_manager) | AI-rank candidates for a job |
| `GET` | `/api/v2/ranking/top/{job_id}` | Bearer (admin_or_manager) | Get pre-ranked candidates for a job from stored scores |
| `POST` | `/api/v2/resume-parser/upload-and-parse` | Bearer (admin_or_manager) | Upload resume and run full AI parsing pipeline |
| `GET` | `/api/v2/resume-parser/{document_id}` | Bearer (admin_or_manager) | Get parsed resume document data |
| `GET` | `/api/v2/resume-parser/ocr/engines/status` | Bearer (admin_or_manager) | Check OCR engine availability |
| `POST` | `/api/v2/screening/screen` | Bearer (admin_or_manager) | AI-screen a single candidate |
| `POST` | `/api/v2/screening/batch-screen` | Bearer (admin_or_manager) | Batch screen multiple candidates for a job |
| `POST` | `/api/v2/screening/results/{screening_id}/decision` | Bearer (admin_or_manager) | Record human decision and update application workflow stage |
| `GET` | `/api/v2/screening/history/{application_id}` | Bearer (admin_or_manager) | Get screening history for an application |
| `GET` | `/api/v2/offer-letters/download/{filename}` | Bearer (admin_or_manager) | Download a generated offer letter file |
| `POST` | `/api/v2/interview/submit-answers` | Bearer (admin_or_manager) | Submit candidate answers and get full evaluation |
| `POST` | `/api/v2/interview/evaluate-answer` | Bearer (admin_or_manager) | Evaluate a single interview answer |
| `GET` | `/api/v2/interview/session/{session_id}` | Bearer (admin_or_manager) | Get interview session details |
| `POST` | `/api/v2/resume-ats-checker/check` | Bearer (Authenticated) | Check resume ATS score and get detailed diagnostic report |
| `POST` | `/v2/resume-ats-checker/check` | Bearer (Authenticated) | Check resume ATS score and get detailed diagnostic report |
| `POST` | `/api/v1/resume-ats-checker/check` | Bearer (Authenticated) | Check resume ATS score and get detailed diagnostic report |
| `POST` | `/resume-ats-checker/check` | Bearer (Authenticated) | Check resume ATS score and get detailed diagnostic report |
| `GET` | `/api/public/careers` | Public (None) | List all published jobs for career portal |
| `GET` | `/api/public/careers/search` | Public (None) | Search career portal jobs |
| `GET` | `/api/public/careers/filter` | Public (None) | Filter career portal jobs |
| `GET` | `/api/public/careers/{slug}` | Public (None) | Get job detail by slug |
| `POST` | `/api/public/careers/apply/{slug}` | Public (None) | Apply for a job posting by ID or slug |
| `POST` | `/api/public/careers/{slug}/apply` | Public (None) | Apply for a job posting |
| `GET` | `/api/public/careers/apply/{ukey}` | Public (None) | Get job detail by unique channel key |
| `POST` | `/api/public/careers/apply/{ukey}` | Public (None) | Apply for a job posting using unique channel key |
| `GET` | `/settings/summary` | Bearer (Authenticated) | Get Settings Summary |
| `GET` | `/settings/general` | Bearer (Authenticated) | Get General Settings |
| `PUT` | `/settings/general` | Bearer (Authenticated) | Update General Settings |
| `GET` | `/settings/company` | Bearer (Authenticated) | Get Company Settings |
| `PATCH` | `/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `POST` | `/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `PUT` | `/settings/company` | Bearer (Authenticated) | Update Company Settings |
| `POST` | `/settings/company/logo` | Bearer (Authenticated) | Upload company logo |
| `GET` | `/settings/roles` | Bearer (Authenticated) | Get Roles |
| `POST` | `/settings/roles` | Bearer (Authenticated) | Create Role |
| `PUT` | `/settings/roles/{role_id}` | Bearer (Authenticated) | Update Role |
| `DELETE` | `/settings/roles/{role_id}` | Bearer (Authenticated) | Delete Role |
| `GET` | `/settings/permissions` | Bearer (Authenticated) | Get Permissions |
| `GET` | `/settings/audit-logs` | Bearer (Authenticated) | Get Audit Logs |
| `GET` | `/settings/security` | Bearer (Authenticated) | Get Security |
| `PUT` | `/settings/security` | Bearer (Authenticated) | Update Security |
| `GET` | `/settings/integrations` | Bearer (Authenticated) | Get Integrations |
| `PUT` | `/settings/integrations` | Bearer (Authenticated) | Toggle Integration |
| `GET` | `/settings/hr` | Bearer (Authenticated) | Get Hr Settings |
| `POST` | `/settings/hr` | Bearer (Authenticated) | Update Hr Settings |
| `PUT` | `/settings/hr` | Bearer (Authenticated) | Update Hr Settings |
| `POST` | `/settings/mfa/enable` | Bearer (Authenticated) | Enable Mfa |
| `POST` | `/settings/mfa/disable` | Bearer (Authenticated) | Disable Mfa |
| `GET` | `/settings/mfa/status` | Bearer (Authenticated) | Get Mfa Status |
| `POST` | `/settings/mfa/verify` | Bearer (Authenticated) | Verify Mfa |
| `GET` | `/onboarding/admin-profile` | Public (None) | Get Admin Profile |
| `PUT` | `/onboarding/admin-profile` | Public (None) | Save Admin Profile |
| `POST` | `/onboarding/admin-profile` | Public (None) | Save Admin Profile |
| `GET` | `/hr-admin/onboarding/admin-profile` | Public (None) | Get HR Admin Profile (Alias) |
| `PUT` | `/hr-admin/onboarding/admin-profile` | Public (None) | Update Admin Profile (Alias) |
| `POST` | `/hr-admin/onboarding/admin-profile` | Public (None) | Create/Update Admin Profile (Alias) |
| `GET` | `/health` | Public (None) | Health Check |
| `GET` | `/health/ready` | Public (None) | Health Ready |
| `GET` | `/` | Public (None) | Root |
| `GET` | `/favicon.ico` | Public (None) | Favicon |
| `GET` | `/api/v1/cors-debug` | Public (None) | Cors Debug |

### Collaboration & Helpdesk (139 endpoints)

| Method | Endpoint | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/announcements` | Bearer (admin_or_hr) | Create announcement |
| `GET` | `/api/v1/announcements` | Bearer (Authenticated) | List announcements |
| `GET` | `/api/v1/announcements/{id}` | Bearer (Authenticated) | Get announcement details |
| `PUT` | `/api/v1/announcements/{id}` | Bearer (admin_or_hr) | Update announcement parameters |
| `DELETE` | `/api/v1/announcements/{id}` | Bearer (admin_or_hr) | Delete announcement |
| `PATCH` | `/api/v1/announcements/{id}/publish` | Bearer (admin_or_hr) | Publish announcement |
| `PATCH` | `/api/v1/announcements/{id}/archive` | Bearer (admin_or_hr) | Archive announcement |
| `POST` | `/api/v1/calendar/events` | Bearer (admin_or_hr) | Create a new calendar event |
| `GET` | `/api/v1/calendar/events` | Bearer (Authenticated) | List calendar events |
| `GET` | `/api/v1/calendar/events/{id}` | Bearer (Authenticated) | Get calendar event details |
| `PUT` | `/api/v1/calendar/events/{id}` | Bearer (admin_or_hr) | Update calendar event |
| `DELETE` | `/api/v1/calendar/events/{id}` | Bearer (admin_or_hr) | Delete calendar event |
| `POST` | `/api/v1/calendar/holidays` | Bearer (admin_or_hr) | Create a new holiday entry |
| `GET` | `/api/v1/calendar/holidays` | Bearer (Authenticated) | List holidays |
| `PUT` | `/api/v1/calendar/holidays/{id}` | Bearer (admin_or_hr) | Update holiday details |
| `DELETE` | `/api/v1/calendar/holidays/{id}` | Bearer (admin_or_hr) | Delete holiday entry |
| `POST` | `/api/v1/calendar/meetings` | Bearer (Authenticated) | Schedule a meeting |
| `GET` | `/api/v1/calendar/meetings` | Bearer (Authenticated) | List scheduled meetings |
| `GET` | `/api/v1/calendar/meetings/{id}` | Bearer (Authenticated) | Get meeting details by ID |
| `PUT` | `/api/v1/calendar/meetings/{id}` | Bearer (Authenticated) | Update scheduled meeting |
| `DELETE` | `/api/v1/calendar/meetings/{id}` | Bearer (Authenticated) | Cancel / delete meeting |
| `GET` | `/api/v1/calendar/birthdays` | Bearer (Authenticated) | Get today's employee birthdays |
| `GET` | `/api/v1/calendar/anniversaries` | Bearer (Authenticated) | Get today's employee work joining anniversaries |
| `GET` | `/api/v1/calendar/dashboard` | Bearer (Authenticated) | Get calendar dashboard view |
| `POST` | `/api/v1/news` | Bearer (admin_or_hr) | Create news article |
| `GET` | `/api/v1/news` | Bearer (Authenticated) | List news articles |
| `GET` | `/api/v1/news/{id}` | Bearer (Authenticated) | Get news article details |
| `PUT` | `/api/v1/news/{id}` | Bearer (admin_or_hr) | Update news article |
| `DELETE` | `/api/v1/news/{id}` | Bearer (admin_or_hr) | Delete news article |
| `PATCH` | `/api/v1/news/{id}/publish` | Bearer (admin_or_hr) | Publish news article |
| `POST` | `/api/v1/events` | Bearer (admin_or_hr) | Create event |
| `GET` | `/api/v1/events` | Bearer (Authenticated) | List events |
| `GET` | `/api/v1/events/{id}` | Bearer (Authenticated) | Get event details |
| `PUT` | `/api/v1/events/{id}` | Bearer (admin_or_hr) | Update event details |
| `DELETE` | `/api/v1/events/{id}` | Bearer (admin_or_hr) | Delete event |
| `PATCH` | `/api/v1/events/{id}/publish` | Bearer (admin_or_hr) | Publish event |
| `PATCH` | `/api/v1/events/{id}/cancel` | Bearer (admin_or_hr) | Cancel event |
| `POST` | `/api/v1/events/{id}/register` | Bearer (Authenticated) | Register for event |
| `POST` | `/api/v1/polls` | Bearer (admin_or_hr) | Create poll |
| `GET` | `/api/v1/polls` | Bearer (Authenticated) | List polls |
| `GET` | `/api/v1/polls/{id}` | Bearer (Authenticated) | Get poll details |
| `POST` | `/api/v1/polls/{id}/vote` | Bearer (Authenticated) | Cast vote on a poll option |
| `PATCH` | `/api/v1/polls/{id}/close` | Bearer (admin_or_hr) | Close poll |
| `DELETE` | `/api/v1/polls/{id}` | Bearer (admin_or_hr) | Delete poll |
| `GET` | `/api/v1/settings/notifications` | Bearer (Authenticated) | Get Notifications |
| `PATCH` | `/api/v1/settings/notifications` | Bearer (Authenticated) | Update Notifications |
| `PUT` | `/api/v1/settings/notifications` | Bearer (Authenticated) | Update Notifications |
| `GET` | `/api/v1/global-notifications/notifications` | Bearer (Authenticated) | Get all notifications |
| `POST` | `/api/v1/global-notifications/notifications/{notif_id}/read` | Bearer (Authenticated) | Mark notification as read |
| `POST` | `/api/v1/global-notifications/notifications/read-all` | Bearer (Authenticated) | Mark all notifications as read |
| `DELETE` | `/api/v1/global-notifications/notifications/{notif_id}` | Bearer (Authenticated) | Delete/Archive notification |
| `GET` | `/api/v1/global-notifications/automation-rules` | Bearer (Authenticated) | List all automation rules |
| `POST` | `/api/v1/global-notifications/automation-rules` | Bearer (Authenticated) | Create automation rule |
| `POST` | `/api/v1/global-notifications/automation-rules/{rule_id}/toggle` | Bearer (Authenticated) | Toggle automation rule active status |
| `POST` | `/api/v1/global-notifications/automation-rules/{rule_id}/test` | Bearer (Authenticated) | Trigger test notification for automation rule |
| `GET` | `/api/v1/global-notifications/activity` | Bearer (Authenticated) | Get automation activity logs |
| `POST` | `/api/v1/global-notifications/activity/{act_id}/retry` | Bearer (Authenticated) | Retry failed automation activity |
| `GET` | `/api/v1/global-notifications/scheduled-jobs` | Bearer (Authenticated) | Get scheduled jobs calendar |
| `POST` | `/api/v1/global-notifications/scheduled-jobs/{job_id}/toggle` | Bearer (Authenticated) | Pause or resume scheduled job |
| `GET` | `/api/v1/global-notifications/preferences` | Bearer (Authenticated) | Get notification preferences |
| `PUT` | `/api/v1/global-notifications/preferences` | Bearer (Authenticated) | Update notification preferences |
| `GET` | `/api/v1/connect/colleagues` | Bearer (Authenticated) | 1. User Discovery - List Colleagues |
| `GET` | `/api/v1/connect/search` | Bearer (Authenticated) | 2. Unified Search |
| `GET` | `/api/v1/connect/conversations` | Bearer (Authenticated) | 3. Get Conversations |
| `POST` | `/api/v1/connect/conversations` | Bearer (Authenticated) | 4. Create or Retrieve Direct Conversation |
| `GET` | `/api/v1/connect/conversations/{conversationId}/messages` | Bearer (Authenticated) | 5. Get Conversation Messages |
| `POST` | `/api/v1/connect/conversations/{conversationId}/messages` | Bearer (Authenticated) | 6. Send Conversation Message |
| `POST` | `/api/v1/connect/messages/{messageId}/reactions` | Bearer (Authenticated) | 7. Toggle Message Reaction |
| `PATCH` | `/api/v1/connect/messages/{messageId}/pin` | Bearer (Authenticated) | 8. Pin/Unpin Message |
| `DELETE` | `/api/v1/connect/messages/{messageId}` | Bearer (Authenticated) | 9. Delete Message |
| `GET` | `/api/v1/connect/messages/{parentMessageId}/thread` | Bearer (Authenticated) | 10. Get Message Thread |
| `POST` | `/api/v1/connect/messages/{parentMessageId}/thread` | Bearer (Authenticated) | 11. Post Thread Reply |
| `GET` | `/api/v1/connect/channels` | Bearer (Authenticated) | 12. Get Channels |
| `POST` | `/api/v1/connect/channels` | Bearer (Authenticated) | 13. Create Channel |
| `GET` | `/api/v1/connect/channels/{channelId}` | Bearer (Authenticated) | 14. Get Channel Details |
| `PATCH` | `/api/v1/connect/channels/{channelId}` | Bearer (Authenticated) | 14b. Update Channel |
| `DELETE` | `/api/v1/connect/channels/{channelId}` | Bearer (Authenticated) | 14c. Delete Channel |
| `POST` | `/api/v1/connect/channels/{channelId}/members` | Bearer (Authenticated) | 14d. Add Channel Members |
| `DELETE` | `/api/v1/connect/channels/{channelId}/members/{userId}` | Bearer (Authenticated) | 14e. Remove Channel Member |
| `GET` | `/api/v1/connect/channels/{channelId}/messages` | Bearer (Authenticated) | 15. Get Channel Messages |
| `POST` | `/api/v1/connect/channels/{channelId}/messages` | Bearer (Authenticated) | 16. Send Channel Message |
| `POST` | `/api/v1/connect/channels/{channelId}/leave` | Bearer (Authenticated) | 17. Leave Channel |
| `PATCH` | `/api/v1/connect/channels/{channelId}/archive` | Bearer (Authenticated) | 18. Archive Channel |
| `GET` | `/api/v1/connect/calls/ice-servers` | Bearer (Authenticated) | 19a. Get ICE Servers |
| `GET` | `/api/v1/connect/calls/history` | Bearer (Authenticated) | 19. Get Call History |
| `GET` | `/api/v1/connect/calls/{callId}` | Bearer (Authenticated) | 20a. Get Call Details |
| `POST` | `/api/v1/connect/calls/initiate` | Bearer (Authenticated) | 20. Initiate Call |
| `PATCH` | `/api/v1/connect/calls/{callId}/status` | Bearer (Authenticated) | 21. Update Call Status |
| `POST` | `/api/v1/connect/calls/{callId}/signal` | Bearer (Authenticated) | 22. WebRTC Signaling Relay |
| `GET` | `/api/v1/connect/meetings` | Bearer (Authenticated) | 23. Get Meetings |
| `POST` | `/api/v1/connect/meetings` | Bearer (Authenticated) | 24. Create Meeting |
| `GET` | `/api/v1/connect/meetings/{meetingId}` | Bearer (Authenticated) | 25. Get Meeting Details |
| `POST` | `/api/v1/connect/meetings/{meetingId}/join` | Bearer (Authenticated) | 26. Join Meeting |
| `POST` | `/api/v1/connect/meetings/{meetingId}/leave` | Bearer (Authenticated) | 27. Leave Meeting |
| `POST` | `/api/v1/connect/meetings/{meetingId}/messages` | Bearer (Authenticated) | 28. Send Meeting Message |
| `GET` | `/api/v1/connect/files` | Bearer (Authenticated) | 29. Get Shared Files |
| `POST` | `/api/v1/connect/files/upload` | Bearer (Authenticated) | 30. Upload Shared File |
| `DELETE` | `/api/v1/connect/files/{fileId}` | Bearer (Authenticated) | 31. Delete Shared File |
| `PUT` | `/api/v1/connect/presence` | Bearer (Authenticated) | 32. Update User Presence |
| `POST` | `/api/v1/connect/presence/batch` | Bearer (Authenticated) | 33. Batch Presence Lookup |
| `GET` | `/api/v1/connect/notifications` | Bearer (Authenticated) | 34. Get Notifications |
| `PATCH` | `/api/v1/connect/notifications/{notificationId}/read` | Bearer (Authenticated) | 35. Mark Notification as Read |
| `DELETE` | `/api/v1/connect/notifications` | Bearer (Authenticated) | 36. Clear Notifications |
| `GET` | `/api/v1/connect/settings/sound` | Bearer (Authenticated) | 37. Get Sound Settings |
| `PUT` | `/api/v1/connect/settings/sound` | Bearer (Authenticated) | 38. Update Sound Settings |
| `POST` | `/api/v1/connect/mail/dispatch` | Bearer (Authenticated) | 40. Connect Mail Dispatch |
| `GET` | `/api/v1/helpdesk/tickets/my` | Bearer (Authenticated) | 1. Helpdesk - Get My Support Tickets |
| `POST` | `/api/v1/helpdesk/tickets` | Bearer (Authenticated) | 2. Helpdesk - Create Support Ticket |
| `GET` | `/api/v1/helpdesk/tickets/{ticketId}` | Bearer (Authenticated) | 3. Helpdesk - Get Ticket by ID |
| `GET` | `/api/v1/helpdesk/tickets/{ticketId}/comments` | Bearer (Authenticated) | 4. Helpdesk - Get Ticket Discussion Comments |
| `POST` | `/api/v1/helpdesk/tickets/{ticketId}/comments` | Bearer (Authenticated) | 5. Helpdesk - Add Ticket Comment |
| `POST` | `/api/v1/helpdesk/tickets/attachments/upload` | Bearer (Authenticated) | 6. Helpdesk - Upload Ticket Attachment |
| `PATCH` | `/api/v1/helpdesk/tickets/{ticketId}/status` | Bearer (Authenticated) | 8. Helpdesk - Update Ticket Status |
| `PATCH` | `/api/v1/helpdesk/tickets/{ticketId}/assign` | Bearer (Authenticated) | 9. Helpdesk - Assign Ticket to Agent |
| `POST` | `/api/v1/helpdesk/tickets/{ticketId}/internal-notes` | Bearer (Authenticated) | 10. Helpdesk - Add Internal Staff Note |
| `GET` | `/api/v1/helpdesk/faqs` | Bearer (Authenticated) | 11. Helpdesk - Get Knowledge Base FAQs |
| `GET` | `/api/v1/notifications/stream` | Bearer (Authenticated) | Stream Notifications |
| `GET` | `/api/v1/notifications/unread-count` | Bearer (Authenticated) | Get Unread Count |
| `GET` | `/api/v1/notifications/unread` | Bearer (Authenticated) | List Legacy Unread Notifications |
| `POST` | `/api/v1/notifications/read-all` | Bearer (Authenticated) | Mark All Read |
| `POST` | `/api/v1/notifications/read` | Bearer (Authenticated) | Mark Many Read |
| `GET` | `/api/v1/notifications/` | Bearer (Authenticated) | List Notifications |
| `GET` | `/api/v1/notifications` | Bearer (Authenticated) | List Notifications |
| `POST` | `/api/v1/notifications/{id}/read` | Bearer (Authenticated) | Mark Notification Read |
| `POST` | `/api/v1/notifications/{id}/unread` | Bearer (Authenticated) | Mark Notification Unread |
| `POST` | `/api/v1/notifications/{id}/archive` | Bearer (Authenticated) | Archive Notification |
| `GET` | `/settings/notifications` | Bearer (Authenticated) | Get Notifications |
| `PATCH` | `/settings/notifications` | Bearer (Authenticated) | Update Notifications |
| `PUT` | `/settings/notifications` | Bearer (Authenticated) | Update Notifications |
| `GET` | `/notifications/stream` | Bearer (Authenticated) | Stream Notifications |
| `GET` | `/notifications/unread-count` | Bearer (Authenticated) | Get Unread Count |
| `GET` | `/notifications/unread` | Bearer (Authenticated) | List Legacy Unread Notifications |
| `POST` | `/notifications/read-all` | Bearer (Authenticated) | Mark All Read |
| `POST` | `/notifications/read` | Bearer (Authenticated) | Mark Many Read |
| `GET` | `/notifications/` | Bearer (Authenticated) | List Notifications |
| `GET` | `/notifications` | Bearer (Authenticated) | List Notifications |
| `POST` | `/notifications/{id}/read` | Bearer (Authenticated) | Mark Notification Read |
| `POST` | `/notifications/{id}/unread` | Bearer (Authenticated) | Mark Notification Unread |
| `POST` | `/notifications/{id}/archive` | Bearer (Authenticated) | Archive Notification |

## 7. Authentication & Authorization

### Authentication Flows
1. **Registration (`POST /api/v1/auth/register`)**: Creates an inactive user account, generates a 6-digit cryptographically secure OTP, hashes the OTP, and sends a verification email via SMTP.
2. **Email Verification (`POST /api/v1/auth/verify-email`)**: Verifies the OTP within the 10-minute expiry window. Upon success, marks the account verified and active.
3. **Login (`POST /api/v1/auth/login`)**: Validates email/password against bcrypt hash (12 rounds). Verifies account is active, verified, not suspended/terminated, and associated employee/manager profile is active. Returns an RS256 Bearer access token and sets an HttpOnly refresh cookie.
4. **Session Refresh (`POST /api/v1/auth/refresh-token`)**: Supports refresh via request body or HttpOnly cookie (`ofc360_refresh_token`). Issues a fresh access token and rotates the refresh token with a 15-second grace window to prevent race conditions during rapid concurrent client refreshes.
5. **Password Management (`/forgot-password`, `/reset-password`, `/change-password`)**: Rate-limited password reset flow with secure single-use reset tokens.
6. **Logout (`POST /api/v1/auth/logout`)**: Adds the access token to the Redis blacklist with a TTL matching token expiry, revokes the refresh token in PostgreSQL, and clears all session cookies.
7. **Social OAuth (`/github`, `/google`)**: Secure OAuth callback exchange for single sign-on.

### Canonical Role-Based Access Control (RBAC)
OFC360 implements six canonical system roles defined in `RoleEnum` (`app/models/user/role.py`):

| Role | Code | Scope & Privileges |
| --- | --- | --- |
| **Super Admin** | `super_admin` | Global platform administration. Immutable security lock: strictly restricted to `superadmin@ofc360.com`. Manages tenant companies, platform health, and global organizations. |
| **HR Admin** | `hr_admin` | Organization-level HR administration. Full authority over company employees, payroll execution, recruitment pipelines, leave policies, and company documents. |
| **Manager** | `manager` | Team management. Oversees direct reports, approves leave and regularization requests, conducts performance evaluations, and tracks team attendance. |
| **Employee** | `employee` | Standard employee self-service. Access to personal attendance, timesheets, leave applications, payslip downloads, personal documents, and company connect. |
| **Executive** | `executive` | C-Suite leadership (CEO, CTO, CFO, COO, CMO, etc.). Access to company-wide analytics, workforce forecasting, executive copilots, and strategic reporting. |
| **IT Admin** | `it_admin` | Technical administration. Manages system settings, IP whitelists, security audit logs, MFA enforcement, and active user sessions. |

> [!IMPORTANT]
> **Single Super Admin Security Lock**: The platform enforces that only `superadmin@ofc360.com` can hold the `super_admin` role. Any attempt to elevate another account to `super_admin` or reassign the official email is blocked at both ORM validator and startup migration levels.

### RBAC Dependency Checks
Endpoints are guarded by specific FastAPI dependencies from `app/core/rbac.py`:
- `require_super_admin`: Validates official Super Admin identity.
- `require_hr_admin`: Allows `hr_admin` and `super_admin`.
- `require_admin`: Allows `super_admin`, `hr_admin`, and `it_admin`.
- `require_admin_or_manager`: Allows `super_admin`, `hr_admin`, `it_admin`, `manager`, and `executive`.
- `require_executive`: Allows `executive`, `hr_admin`, and `super_admin`.
- `require_it_admin`: Allows `it_admin` and `super_admin`.
- `require_employee_or_above`: Allows any authenticated platform role.
- `require_roles(*roles)`: Dynamic dependency factory for custom role sets.

## 8. Database

### Database Architecture
- **Engine**: PostgreSQL 16 managed through SQLAlchemy 2.0 with the asynchronous `asyncpg` driver.
- **Connection Pooling**: `create_async_engine` configured with connection pool parameters:
  - `pool_size = 5` (Default pool connections)
  - `max_overflow = 5` (Burst connections under heavy concurrent loads)
  - `pool_timeout = 30` (Seconds to wait for a connection before timing out)
  - `pool_recycle = 300` (Recycles connections every 5 minutes to prevent stale sockets)
  - `pool_pre_ping = True` (Tests connection liveness with `SELECT 1` before issuing to worker)
- **Session Lifecycle**: Handled via `get_db_session` dependency. Every request gets an isolated `AsyncSession` (`expire_on_commit=False`, `autoflush=False`). Errors trigger automatic rollback.

### Multi-Tenant Isolation Architecture
OFC360 employs row-level multi-tenancy enforced at the SQLAlchemy ORM layer:
1. **Context Variable (`tenant_id_ctx`)**: Set during request authentication to the authenticated user's `company_id`.
2. **Global Query Interceptor (`do_orm_execute`)**: Automatically appends `with_loader_criteria` to every ORM query for entities containing a `company_id` column:
   ```python
   target_cls.company_id == tenant_id_ctx.get()
   ```
   This guarantees that no user can read another organization's records even if SQL queries omit the WHERE clause.
3. **Automatic Assignment (`before_flush`)**: Automatically injects `obj.company_id = tenant_id_ctx.get()` on newly created records.
4. **Administrative Bypass**: Platform Super Admin endpoints explicitly pass `execution_options(bypass_tenant=True)` to inspect global cross-company metrics.

## 9. Database Models

The database schema comprises **244 tables** organized into 21 business domains:

| Business Domain | Tables Count | Key Tables | Purpose & Core Entities |
| --- | --- | --- | --- |
| **Authentication & Security** | 20 | `users`, `user_sessions`, `refresh_tokens`, `otps`, `password_resets`, `user_mfa`, `security_roles`, `security_policies`, `ip_whitelist`, `security_audit_logs` | User identities, credential hashes, multi-factor auth, sessions, IP whitelists, and token lifecycle |
| **Organization & Companies** | 10 | `companies`, `departments`, `company_settings`, `designations` | Multi-tenant organizations, organizational hierarchies, corporate configuration, and job designations |
| **Employees & Core HR** | 15 | `employees`, `employee_addresses`, `employee_documents`, `employee_education`, `employee_experience`, `employee_skills`, `employee_emergency_contacts`, `employee_bank_accounts`, `employee_invitations` | Employee master profiles, statutory identifiers, qualifications, banking info, and invitations |
| **Managers & Hierarchy** | 6 | `managers`, `manager_addresses`, `manager_documents`, `manager_education`, `manager_experience`, `manager_skills`, `hierarchy_audit_logs` | Management directory, departmental reporting relationships, and organizational hierarchy tracking |
| **Recruitment & ATS** | 31 | `jobs`, `job_skills`, `job_requisitions`, `applications`, `application_documents`, `candidates`, `candidate_crm_notes`, `candidate_referrals`, `interviews`, `interview_rounds`, `offers`, `scorecard_templates`, `recruitment_vendors` | Complete hiring pipeline: job requisitions, candidate sourcing, interviews, evaluations, and offers |
| **AI Recruitment & Screening** | 3 | `ai_resume_documents`, `candidate_match_scores`, `ai_screening_results`, `coding_assessment_records`, `hr_copilot_queries` | Automated resume parsing, candidate-job matching scores, AI screening summaries, and coding tests |
| **Onboarding** | 2 | `onboarding_progress`, `employee_onboarding`, `employee_policy_acceptances` | New-hire onboarding workflows, task checklists, document submission verification, and policy sign-offs |
| **Attendance & Time** | 8 | `attendances`, `attendance_breaks`, `attendance_regularization_requests`, `timesheets`, `timesheet_entries`, `shift_plans`, `shift_plan_entries`, `shifts` | Clock-in/out logging, geolocation/biometric data, break tracking, regularization, timesheets, and shift planning |
| **Leave & Holidays** | 5 | `leave_requests`, `leave_policies`, `employee_leave_policies`, `holiday_calendar`, `holidays` | Leave balance tracking, annual accruals, leave requests, manager approval flows, and company holidays |
| **Payroll & Compensation** | 26 | `payroll_runs`, `payroll_periods`, `payroll_run_employees`, `payslips`, `pay_components`, `compensations`, `compensation_revisions`, `variable_inputs`, `payment_batches`, `payment_batch_bank_files`, `full_and_final_settlements`, `salary_structures`, `statutory_compliance_configs`, `advance_loans`, `reimbursement_claims`, `bank_advice_files` | Comprehensive payroll processing engine: salary structures, earnings, deductions, PF/ESI/PT/TDS, bank disbursement advice, loans, and FnF |
| **Performance & Goals** | 7 | `performance_review_cycles`, `employee_performance_goals`, `performance_reviews`, `performance_kpis`, `generated_goals`, `employee_productivity_logs`, `productivity_forecasting_runs` | Quarterly/annual review cycles, OKRs, KPI tracking, AI goal recommendations, and productivity metrics |
| **Documents & Templates** | 16 | `document_categories`, `company_documents`, `document_templates`, `document_versions`, `document_signatures`, `document_verifications`, `document_expiry_tracking`, `document_audit_logs`, `document_ocr_records` | Document repository, version history, template merging, digital signatures, OCR records, and expiry alarms |
| **Exit & Separation** | 4 | `employee_exits`, `knowledge_transfers`, `asset_returns`, `clearance_requests`, `exit_interviews`, `fnf_settlements`, `exit_documents` | Resignation lifecycle, multi-department clearance approvals, knowledge handover, and exit interviews |
| **Calendar & Meetings** | 8 | `calendar_events`, `meetings`, `meeting_participants`, `calendar_notifications`, `event_reminders` | Corporate events, scheduling, calendar integrations, meeting participants, and automated notifications |
| **Collaboration & Communication** | 18 | `connect_conversations`, `connect_conversation_participants`, `connect_channels`, `connect_channel_members`, `connect_messages`, `connect_message_reactions`, `connect_call_logs`, `connect_meetings`, `announcements`, `company_news`, `company_events`, `polls`, `notification_center` | Real-time chat, group channels, WebRTC call signaling, company announcements, news, and employee polls |
| **Helpdesk & Support** | 7 | `helpdesk_tickets`, `helpdesk_comments`, `helpdesk_internal_notes`, `helpdesk_attachments`, `helpdesk_faqs` | Internal employee ticketing system, priority SLA tracking, attachments, private agent notes, and FAQs |
| **AI Engines & Intelligence** | 25 | `ai_conversations`, `ai_messages`, `agent_runs`, `ai_compensation_recommendations`, `behavioural_interview_sessions`, `emotion_aware_chat_sessions`, `org_hierarchy_snapshots`, `skill_gap_analyses`, `employee_digital_twins`, `career_path_predictions`, `workforce_forecast_runs`, `hr_analytics_snapshots`, `hr_attrition_predictions` | Advanced intelligence modules: attrition risk forecasting, skill gap analysis, workforce planning, and copilot query history |
| **Health & Wellness** | 3 | `employee_wellness_logs`, `wellness_escalation_rules`, `wellness_anonymous_chat_sessions`, `employee_health_records` | Confidential mental wellness logging, anonymous support chat, escalation triggers, and medical records |
| **Compliance & Audit** | 26 | `compliance_records`, `compliance_audit_logs`, `compliance_obligations`, `compliance_documents`, `audit_logs`, `analysis_audit_logs` | Comprehensive enterprise audit trail capturing entity mutations, auth changes, and statutory compliance status |
| **Billing & Subscriptions** | 1 | `subscriptions`, `payment_transactions` | Enterprise billing plans, seat allocation, subscription renewal status, and Razorpay transaction records |
| **Assets Management** | 3 | `assets`, `asset_assignment_history`, `asset_maintenance_records` | IT and physical asset tracking, serial numbers, allocation history, return conditions, and maintenance |

## 10. Alembic Migrations

Database migrations are managed via Alembic in `alembic/`. Schema modifications are strictly applied through migrations; direct database modifications or runtime schema creation (`Base.metadata.create_all`) are forbidden.

### Key Migration Commands
```bash
# 1. Apply all pending migrations to the latest revision
alembic upgrade head

# 2. Generate a new revision after updating SQLAlchemy models
alembic revision --autogenerate -m "describe_your_changes"

# 3. Verify single head and check for schema drift (must report zero drift)
alembic check

# 4. Rollback one revision
alembic downgrade -1

# 5. Resolve multiple heads if branches diverge
alembic merge heads -m "merge_divergent_heads"
```

### Production Migration Architecture
In production and Docker environments, migrations run with **PostgreSQL Advisory Locking** to prevent race conditions during multi-instance rolling deployments:
- `scripts/run_migrations.py`: Acquires lock `SELECT pg_advisory_lock(483921747)`, verifies that exactly one head exists (`alembic heads`), confirms database revision matches local scripts, executes `alembic upgrade head`, and releases the lock.
- `docker-entrypoint.sh`: Automatically invokes `alembic upgrade head` before booting Uvicorn whenever `RUN_MIGRATIONS=true` is set.

## 11. Environment Variables

All configuration parameters are defined in `app/core/config.py` and loaded from `.env`. Sensitive credentials must never be committed.

| Variable | Required | Purpose | Example |
| --- | --- | --- | --- |
| `APP_NAME` | No | Display name of the application | `OFC HR – Office Function Consolidator` |
| `APP_VERSION` | No | Application semantic version | `2.0.0` |
| `ENVIRONMENT` | Yes | Runtime environment (`local`, `development`, `production`) | `production` |
| `DEBUG` | No | Enable debug mode (disable in production) | `false` |
| `ENABLE_DOCS` | No | Override for public docs (/docs, /redoc) | `false` |
| `LOG_LEVEL` | No | Python logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `DATABASE_URL` | **Yes** | Async PostgreSQL connection string | `postgresql+asyncpg://user:pass@host:5432/ofc360` |
| `DB_POOL_SIZE` | No | SQLAlchemy connection pool size | `5` |
| `DB_MAX_OVERFLOW` | No | SQLAlchemy maximum pool overflow | `5` |
| `DB_POOL_TIMEOUT` | No | Connection acquisition timeout in seconds | `30` |
| `DB_POOL_RECYCLE` | No | Connection recycling duration in seconds | `300` |
| `FORCE_IPV4_DB` | No | Workaround for IPv6-only resolution issues | `false` |
| `SECRET_KEY` | **Yes** | Symmetric secret key (32+ chars) for OTPs and sessions | `generate_via_openssl_rand_hex_32` |
| `JWT_ALGORITHM` | No | Cryptographic algorithm for JWTs | `RS256` |
| `JWT_PRIVATE_KEY` | **Yes (Prod)** | RSA Private Key (PEM format) for signing JWTs | `-----BEGIN RSA PRIVATE KEY-----...` |
| `JWT_PUBLIC_KEY` | **Yes (Prod)** | RSA Public Key (PEM format) for verifying JWTs | `-----BEGIN PUBLIC KEY-----...` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Access token validity duration | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | Refresh token validity duration | `30` |
| `SUPER_ADMIN_PASSWORD` | **Yes (Prod)** | Initial password for `superadmin@ofc360.com` (12+ chars) | `strong_admin_password` |
| `RESET_SUPER_ADMIN_PASSWORD` | No | Force-reset Super Admin password on next startup | `false` |
| `REDIS_URL` | **Yes (Prod)** | Redis connection URL for token blacklist and caching | `redis://redis:6379/0` |
| `CELERY_BROKER_URL` | No | Celery broker URL | `redis://redis:6379/1` |
| `CELERY_RESULT_BACKEND` | No | Celery result backend URL | `redis://redis:6379/2` |
| `USE_CELERY` | No | Toggle Celery async processing (falls back to sync if false) | `true` |
| `BACKEND_CORS_ORIGINS` | No | JSON list or comma-separated list of allowed origins | `["https://app.ofc360.com","http://localhost:8080"]` |
| `SMTP_HOST` | **Yes (Prod)** | SMTP relay server hostname | `smtp.sendgrid.net` |
| `SMTP_PORT` | No | SMTP relay server port | `587` |
| `SMTP_USERNAME` | **Yes (Prod)** | SMTP authentication username | `apikey` |
| `SMTP_PASSWORD` | **Yes (Prod)** | SMTP authentication password or API key | `smtp_password` |
| `SMTP_FROM_EMAIL` | No | Default outbound sender email address | `no-reply@ofc360.com` |
| `SMTP_FROM_NAME` | No | Outbound sender display name | `OFC360 Portal` |
| `SMTP_USE_TLS` | No | Enable STARTTLS (standard on port 587) | `true` |
| `SMTP_USE_SSL` | No | Enable direct SSL (standard on port 465) | `false` |
| `CLOUDINARY_CLOUD_NAME` | **Yes (Prod)** | Cloudinary cloud account name | `cloudinary_name` |
| `CLOUDINARY_API_KEY` | **Yes (Prod)** | Cloudinary API key | `cloudinary_key` |
| `CLOUDINARY_API_SECRET` | **Yes (Prod)** | Cloudinary API secret | `cloudinary_secret` |
| `OLLAMA_ENABLED` | No | Enable local Ollama AI engine integration | `true` |
| `OLLAMA_BASE_URL` | No | Ollama HTTP daemon endpoint | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | No | Primary LLM model name | `qwen3:30b` |
| `OLLAMA_TIMEOUT` | No | Ollama inference timeout in seconds | `120` |
| `RAZORPAY_KEY_ID` | No | Razorpay payment gateway Key ID | `rzp_live_key_id` |
| `RAZORPAY_KEY_SECRET` | No | Razorpay payment gateway Key Secret | `rzp_live_secret` |
| `RAZORPAY_WEBHOOK_SECRET` | No | Razorpay webhook signature validation secret | `rzp_webhook_secret` |
| `GITHUB_CLIENT_ID` | No | GitHub OAuth application Client ID | `github_client_id` |
| `GITHUB_CLIENT_SECRET` | No | GitHub OAuth application Client Secret | `github_client_secret` |
| `GOOGLE_CLIENT_ID` | No | Google OAuth Client ID | `google_client_id` |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth Client Secret | `google_client_secret` |

## 12. Local Development

### Prerequisites
- Python 3.11 (`python --version`)
- PostgreSQL 16 (`psql --version`)
- Redis 7 (`redis-server --version`)
- C/C++ compiler and CMake (required to build `dlib` C-extensions for facial recognition)

### Step-by-Step Setup
```bash
# 1. Navigate to the backend directory
cd apiofc360

# 2. Create and activate a Python 3.11 virtual environment
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 3. Upgrade pip and build tools
pip install --upgrade pip "setuptools<81" wheel

# 4. Install dlib dependency
python scripts/install_dlib.py

# 5. Install Python dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 6. Configure environment variables
cp .env.example .env
# Edit .env with your local PostgreSQL and Redis credentials

# 7. Apply database migrations
alembic upgrade head

# 8. Run database integrity and drift checks
make db-check

# 9. Start the local development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 13. Running the Backend

### Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production Server (Direct / VM)
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips='*'
```

### Celery Background Worker
```bash
celery -A app.workers.celery_app worker --loglevel=info --concurrency=4 -Q default,resume_parsing,notifications
```

### Docker Compose (Full Stack)
```bash
# Build and start PostgreSQL, Redis, FastAPI, and Celery Worker
docker compose up -d --build

# View live unified logs
docker compose logs -f

# Shut down services and preserve volumes
docker compose down
```

## 14. Background Jobs & Automation

### Celery Architecture
- **App Entry**: `app.workers.celery_app.celery_app`
- **Broker**: Redis (`settings.CELERY_BROKER_URL`, default `redis://localhost:6379/1`)
- **Result Backend**: Redis (`settings.CELERY_RESULT_BACKEND`, default `redis://localhost:6379/2`)
- **Timeouts**: Soft time limit = 300s, hard time limit = 600s (`CELERY_TASK_TIME_LIMIT`).
- **Task Routing**:
  - `resume_parsing` queue: `app.workers.resume_tasks.parse_resume`, `generate_embedding`
  - `notifications` queue: `app.workers.notification_tasks.send_email`
  - `default` queue: `app.workers.payroll_tasks.*`

### Payroll Batch Processing Engine
> [!NOTE]
> **Payroll Autopilot Status**: The codebase **does not** contain a headless auto-pilot cron daemon that executes payroll automatically without human initiation. Instead, the payroll automation engine is designed as an asynchronous, state-tracked batch processing pipeline:

1. **Run Calculation (`process_payroll_run_task`)**: Triggered by HR Admin. Executes `PayrollRunService.execute_run_calculation`, consolidating attendance logs, overtime policies, bonus plans, deductions, and advance loan installments into gross/net salary calculations for all active employees.
2. **Batch Payslip Generation (`generate_payslips_batch_task`)**: Asynchronously compiles ReportLab PDF payslips with company letterhead, storing paths and generating provision slips.
3. **Bank Disbursement Advice (`generate_bank_file_task`)**: Generates structured bank advice files (HDFC, ICICI, SBI, and Generic NEFT format) for corporate net banking uploads.
4. **Statutory Report Generation (`generate_statutory_report_task`)**: Generates ECR/ESI text files, PT challans, and Form 16 / TDS Section 192 quarterly reports.
5. **State Tracking (`PayrollJobTracker`)**: Uses Redis keys `payroll:job:{job_id}` to store progress percentages (0-100%), error states, and processed record counts for UI polling.

### In-Process Scheduled Background Loops
Managed as background tasks on the FastAPI event loop during application startup (`app/main.py`):
- `run_document_expiry_scheduler()`: Runs once every 24 hours (`await asyncio.sleep(86400)`). Scans active employee and company documents against `DOCUMENT_EXPIRY_WARNING_DAYS` (30 days), generates warning audit logs, and sends notification reminders.
- `auto_screen_unscreened_leads()`: Executes 2 seconds after startup. Queries all candidate applications lacking match scores and initiates resume analysis and match evaluation.

## 15. Email System

All outbound transactional emails are processed by `EmailService` (`app/services/email_service.py`):
- **Transport**: Standard Python `smtplib` executed asynchronously in worker threads via `asyncio.to_thread(_send_via_smtp)` to ensure non-blocking HTTP request processing.
- **Security Modes**: Supports STARTTLS (port 587, `SMTP_USE_TLS=true`) or direct SSL (port 465, `SMTP_USE_SSL=true`).
- **Template Engine**: Custom regex-based rendering engine supporting variable replacement (`{{ key }}`), conditional blocks (`{% if key %}...{% else %}...{% endif %}`), and fallback plain-text conversion.
- **Retry Policy**: Up to 3 attempts with exponential back-off (1s, 2s). Hard authentication errors or recipient rejections abort immediately without retrying.
- **Local Dev Behavior**: When `ENVIRONMENT=local` or `DEBUG=true`, failed SMTP deliveries do not raise HTTP 500; instead, the email content is cleanly dumped to the terminal console (`[DEV EMAIL LOG]`) for rapid local testing.
- **Transactional Templates**: Account verification OTP (`verify_email.html`), login OTP (`login_verify_otp.html`), welcome message (`welcome_email.html`), password reset token (`password_reset_email.html`), employee account activation (`employee_activation.html`), and onboarding invitation (`employee_onboarding_invite.html`).

## 16. CORS (Cross-Origin Resource Sharing)

CORS is configured in `app/main.py` using Starlette's `CORSMiddleware`. It is registered as the **outermost ASGI layer** to guarantee that preflight `OPTIONS` requests receive immediate `200 OK` / `204 No Content` responses at the network edge before reaching authentication or rate limiters.

### Supported Origins
- **Production Origins**:
  - `https://ofc360.com`
  - `https://www.ofc360.com`
  - `https://api.ofc360.com`
  - `https://app.ofc360.com`
  - `https://ofc360.vercel.app`
- **Local Development Origins**:
  - `http://localhost:8080`, `http://127.0.0.1:8080`
  - `http://localhost:3000`, `http://127.0.0.1:3000`
  - `http://localhost:5173`, `http://127.0.0.1:5173`
  - `http://localhost:4173`, `http://127.0.0.1:4173`
  - Subnet matching regex (`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) for mobile and LAN testing.
- **Behavior**:
  - `allow_credentials = True`
  - `allow_methods = ["*"]`
  - `allow_headers = ["*"]`
  - `expose_headers = ["Authorization", "Content-Type", "Content-Disposition", "X-Process-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining"]`
  - `max_age = 86400` (Preflight cache duration = 24 hours)

## 17. API Error Handling

FastAPI application error handlers are centralized in `app/core/exceptions.py`:

### Exception Hierarchy
```text
AppException (Base Exception)
├── ValidationException (HTTP 400 - Business rule failure)
├── BadRequestException (HTTP 400 - Malformed request)
├── UnauthorizedException (HTTP 401 - Authentication missing or expired)
├── ForbiddenException (HTTP 403 - Permission denied or inactive account)
├── NotFoundException (HTTP 404 - Resource does not exist)
├── ConflictException (HTTP 409 - Resource uniqueness conflict)
└── DatabaseException (HTTP 500 - Internal database query failure)
```

### Handlers Installed
- **`AppException` Handler**: Formats custom application exceptions into standard `APIResponse` envelopes.
- **`RequestValidationError` Handler**: Catches Pydantic schema validation failures, extracts invalid field paths, and returns clean error lists under HTTP 422.
- **`StarletteHTTPException` Handler**: Intercepts framework-level HTTP errors (404, 405, 500) and formats them into JSON envelopes.
- **Global Unhandled Exception Handler**: Catches unexpected runtime crashes, masks sensitive internals in production (`Internal server error`), logs stack traces with request context, and ensures CORS headers are attached.

## 18. Security

- **Password Hashing**: Implemented via Passlib with Bcrypt (`rounds=12`). Passwords are never logged or stored in plain text.
- **Asymmetric JWT Signing (RS256)**: Tokens are signed with a 2048-bit RSA Private Key (`JWT_PRIVATE_KEY`) and verified using the corresponding Public Key (`JWT_PUBLIC_KEY`).
- **Token Revocation & Blocklist**: Redis-backed stateless token blacklisting. When a user logs out or an administrator changes an account password, the token is added to `token:blacklist` and `user:{user_id}:revoked_before` is updated.
- **Session Cookies**: In production, cookies enforce `__Host-` prefix, `Secure=True`, `HttpOnly=True`, and `SameSite=Strict`.
- **SQL Injection Protections**: Powered strictly by SQLAlchemy 2.0 parameterized queries and ORM type binding. Zero raw string concatenation.
- **Tenant Isolation Guardrails**: Automated query filtering prevents cross-tenant data leaks.
- **File Upload Security**: Uploaded files are validated against allowed extensions (`.pdf`, `.doc`, `.docx`, `.png`, `.jpg`), file size limits (10MB-20MB), and sanitized filenames. Document upload directories (`/app/uploads/documents`) are **never mounted as public static directories**.
- **Security Headers**: Injected on all HTTP responses: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, and `Referrer-Policy: strict-origin-when-cross-origin`.

## 19. Docker

### Multi-Stage Production Dockerfile
The repository includes an optimized multi-stage `Dockerfile` based on `python:3.11-slim-bookworm`:
1. **Stage 1 (Builder)**: Installs build essentials, cmake, pkg-config, OpenBLAS, LAPACK, and libpq. Compiles `dlib` with parallel C++ optimizations into a virtual environment `/opt/venv`.
2. **Stage 2 (Runner)**: Minimal Debian runtime containing only shared libraries (`libpq5`, `libgl1`, `libopenblas0`, `curl`, `gosu`). Copies pre-compiled `/opt/venv`, creates non-root user `appuser` (UID 10001), and compiles Python bytecode with `compileall`.
3. **Healthcheck Probe**: `curl -f http://localhost:8000/health || exit 1` every 15s.

### Docker Compose Architecture (`docker-compose.yml`)

| Service | Image / Build | Container Name | Ports | Healthcheck Probe |
| --- | --- | --- | --- | --- |
| `db` | `postgres:16-alpine` | `ofc360_db` | `127.0.0.1:5432:5432` | `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}` |
| `redis` | `redis:7-alpine` | `ofc360_redis` | `127.0.0.1:6379:6379` | `redis-cli ping` |
| `api` | Built from `Dockerfile` | `ofc360_api` | `0.0.0.0:8000:8000` | `curl -f http://localhost:8000/health` |
| `celery_worker` | Built from `Dockerfile` | `ofc360_celery_worker` | None (Internal) | `celery inspect ping` |

## 20. Testing

Testing is orchestrated with `pytest` and `pytest-asyncio` (`pytest.ini`). The repository includes **72 comprehensive test suites** covering auth, RBAC, payroll, recruitment, attendance, documents, and migrations.

### Test Execution Commands
```bash
# 1. Run all test suites
pytest

# 2. Run database migration and schema integrity tests (Makefile)
make db-check

# 3. Run specific test domains
pytest tests/test_auth_endpoints_comprehensive.py -v
pytest tests/test_payroll_full_suite.py -v
pytest tests/test_super_admin_security_lock.py -v
pytest tests/test_multi_tenant_data_isolation.py -v
pytest tests/test_alembic_single_head.py -v

# 4. Run tests with coverage report
pytest --cov=app --cov-report=term-missing
```

## 21. Deployment

### Production Deployment Topology
```text
Vercel Frontend (app.ofc360.com)
      │ HTTPS / WSS
      ▼
Reverse Proxy / Cloud Load Balancer (Nginx / Render Gateway)
      │ Port 8000
      ▼
FastAPI Uvicorn Application (ofc360_api)
      ├───────────────────────────────┐
      ▼                               ▼
PostgreSQL 16 Database        Redis 7 (Cache & Queues)
                                      ▲
                                      │ Tasks & Results
                             Celery Background Worker
                                      ▼
                             Local Ollama Runtime (Host Port 11434)
```

### Automated Pre-Deployment Script (`scripts/predeploy.sh`)
The repository includes a production deployment runner that guarantees zero downtime:
1. Verifies/recreates virtual environment and upgrades pip.
2. Installs requirements from `requirements.txt`.
3. Pre-compiles all Python syntax via `python -m compileall -q app alembic`.
4. Validates configuration settings without exposing secret values.
5. Runs `python scripts/run_migrations.py` under an advisory lock.

## 22. Health Checks & Monitoring

### Liveness Probe (`GET /health`)
- **Path**: `GET /health` or `HEAD /health`
- **Authentication**: Public (None)
- **Behavior**: Executes `SELECT 1` against PostgreSQL.
- **Response Shape**:
```json
{
  "status": "healthy",
  "database": "connected",
  "app": "OFC HR – Office Function Consolidator (Human Resources)",
  "version": "2.0.0",
  "environment": "production"
}
```

### Readiness Probe (`GET /health/ready`)
- **Path**: `GET /health/ready`
- **Authentication**: Public (None)
- **Behavior**: Checks PostgreSQL connectivity AND queries Ollama LLM health status. Returns `HTTP 200` if both are operational, or `HTTP 503 Service Unavailable` if either dependency is down.
- **Response Shape**:
```json
{
  "ready": true,
  "database": "connected",
  "llm": {
    "healthy": true,
    "provider": "ollama",
    "model": "qwen3:30b"
  }
}
```

## 23. API Documentation

When enabled via `ENABLE_DOCS=true` or running in `ENVIRONMENT=development` / `local`, interactive API specifications are available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

> [!TIP]
> In production (`ENVIRONMENT=production` and `DEBUG=false`), `/docs`, `/redoc`, and `/openapi.json` return `HTTP 404 Not Found` with `Cache-Control: no-store` headers by default to prevent API surface discovery. Set `ENABLE_DOCS=true` only if public documentation is explicitly required.

## 24. Troubleshooting

### 1. HTTP 401 Unauthorized
- **Symptom**: `Invalid token type` or `Access token has expired`.
- **Fix**: Call `/api/v1/auth/refresh-token` with the refresh token or check if the token was revoked in Redis via logout.

### 2. HTTP 403 Forbidden
- **Symptom**: `Access denied` or `HR Admin access required`.
- **Fix**: Verify user role in JWT claims. Ensure the employee profile is in `ACTIVE` status and not `TERMINATED` or `DEACTIVATED`.

### 3. HTTP 422 Unprocessable Entity
- **Symptom**: Validation error listing specific fields.
- **Fix**: Inspect the response `errors` array. Ensure dates use ISO format (`YYYY-MM-DD`), UUIDs are well-formed 36-character strings, and emails match valid regex.

### 4. CORS Preflight Failure / Missing Access-Control-Allow-Origin
- **Symptom**: Browser blocks fetch with CORS error.
- **Fix**: Verify your frontend origin in `.env` (`BACKEND_CORS_ORIGINS`). Test configuration directly using `GET /api/v1/cors-debug`.

### 5. Database Connection Failures (IPv6 / Supabase / Direct)
- **Symptom**: Connection timed out or DNS resolution failure.
- **Fix**: If using an IPv6-only cloud database provider, set `FORCE_IPV4_DB=true` in `.env`. Ensure your `DATABASE_URL` starts with `postgresql+asyncpg://`.

### 6. Multiple Alembic Heads Detected
- **Symptom**: `FATAL: Multiple Alembic heads detected!` during migration.
- **Fix**: Run `alembic merge heads -m "merge_heads"` and verify with `python scripts/check_migrations.py`.

### 7. Celery Worker Disconnection
- **Symptom**: Celery worker logs `Error 111 connecting to localhost:6379`.
- **Fix**: Verify `REDIS_URL` and `CELERY_BROKER_URL`. In local dev without Redis, set `USE_CELERY=false` to execute tasks synchronously.

## 25. Production Readiness Checklist

| Component | Status | Verification & Codebase Evidence |
| --- | --- | --- |
| **Environment Variables** | Verified | Strict Pydantic `validate_production_safety` validator prevents empty secrets in production |
| **Database Engine** | Verified | PostgreSQL 16 with asyncpg, connection pooling, pre-ping liveness, and connection recycling |
| **Schema Migrations** | Verified | 90 Alembic migrations, single head enforcement in CI, PostgreSQL advisory locking in deploy script |
| **Multi-Tenant Isolation** | Verified | Automatic `do_orm_execute` with `with_loader_criteria` on all company tables |
| **Authentication** | Verified | RS256 JWT, refresh token rotation with 15s grace, Redis token blocklist, HttpOnly session cookies |
| **Super Admin Security Lock** | Verified | Immutable identity enforced: only `superadmin@ofc360.com` is permitted as Super Admin |
| **Role-Based Access Control** | Verified | 6 canonical roles + C-Suite mapping with strict FastAPI dependencies (`require_*`) |
| **CORS Configuration** | Verified | Outermost ASGI middleware layer, credentials enabled, explicit origins list, debug endpoint |
| **Security Headers** | Verified | `SecurityHeadersMiddleware` injects X-Content-Type-Options, X-Frame-Options, CSP, HSTS |
| **Rate Limiting** | Verified | Global Redis sliding window (100/min) + tight limits on login (5/min), register, OTP, and AI |
| **Error Handling** | Verified | Standard `APIResponse` envelope, sanitized 500 error messages, structured logging |
| **Task Queues & Workers** | Verified | Celery 5.4 over Redis with graceful synchronous fallback when `USE_CELERY=false` |
| **Email System** | Verified | Real SMTP with STARTTLS/SSL, template engine, exponential backoff retries, dev console fallback |
| **Document Storage** | Verified | Cloudinary integration + local `/app/uploads` storage with private non-static document mounts |
| **AI Runtime Isolation** | Verified | Ollama on-premise integration exclusively; external cloud LLM providers disabled in code |
| **Automated Testing** | Verified | 72 automated test suites covering auth, RBAC, models, migrations, and APIs |
| **Containerization** | Verified | Multi-stage Dockerfile, non-root `appuser` (UID 10001), healthchecks, docker-compose ready |

## 26. API ↔ Frontend Integration

To connect an enterprise frontend client (React / Next.js / Vite) to this backend:

### Base URLs
- **Development**: `http://localhost:8000`
- **Production**: `https://api.ofc360.com`

### Required Request Headers
```http
Authorization: Bearer <jwt_access_token>
Content-Type: application/json
Accept: application/json
```

### Client Response Parsing
Every response conforms to the standard envelope:
```typescript
interface APIResponse<T> {
  success: boolean;
  message: string;
  data: T;
  errors: Array<{ field?: string; message: string }> | null;
}
```

### Dual-Key Compatibility
Analytical and dashboard endpoints return both `snake_case` and `camelCase` keys in response bodies (e.g. `workforce_size` and `workforceSize`), eliminating the need for client-side key conversion layers.

## 27. Contributing

1. **Branching Model**: Create feature branches from `main` (`feature/your-feature-name` or `fix/your-bug-fix`).
2. **Database Modifications**:
   - Never modify database tables or columns directly via SQL.
   - Update SQLAlchemy models in `app/models/`.
   - Autogenerate migration: `alembic revision --autogenerate -m "describe_change"`.
   - Verify that `make db-check` passes with zero schema drift.
3. **Code Quality**:
   - Follow PEP 8 standards with strict type annotations.
   - Run syntax verification: `python -m compileall app alembic`.
4. **Testing**:
   - Add unit/integration tests under `tests/` for all new endpoints.
   - Run `pytest` and ensure all suites pass before opening a pull request.

## 28. License

Proprietary and Confidential. Copyright © 2026 OFC360. All rights reserved. Unauthorized copying, reverse engineering, or redistribution is strictly prohibited.

## 29. Maintainers

- **Engineering Team**: OFC360 Core Platform Team
- **Repository Author**: vinit sharma (`sharmavinit54538@gmail.com`)
- **Technical Inquiries**: `support@ofc360.com`




# OFC360 Recruitment Module - API Integration Guide

## Overview

This document describes all registered Recruitment API endpoints, their authentication requirements, request/response formats, and frontend integration specifications for the AI Video Interview system.

---

## Base URLs

- **v1 REST API:** `/api/v1/recruitment/*`
- **v2 REST API:** `/api/v2/*`
- **Public Career Portal:** `/api/public/careers/*`
- **HR Dashboard:** `/api/hr/interviews/*`
- **WebSocket:** `/api/v2/interview-ws/*`

---

## Authentication

### Admin/HR Endpoints
Require Bearer token with roles: `super_admin`, `hr_admin`, `manager` (where specified)
```
Authorization: Bearer <access_token>
```

### Candidate Interview Endpoints
Require valid invitation token (no Bearer token):
```
# Via query parameter
GET /api/v2/interview-bot/sessions/{session_id}/start?invitation_token=xxx

# Or via WebSocket
WS /api/v2/interview-ws/session/{invitation_token}
```

---

## Job Management

### Create Job
```
POST /api/v1/jobs
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: application/json

{
  "title": "Senior Python Developer",
  "department": "Engineering",
  "designation": "Senior Python Developer",
  "employment_type": "FULL_TIME",
  "experience_required": "5-8 years",
  "min_experience": 5,
  "max_experience": 8,
  "min_salary": 120000,
  "max_salary": 180000,
  "location": "San Francisco, CA",
  "vacancies": 2,
  "job_description": "We are looking for...",
  "responsibilities": "- Design...",
  "requirements": "- Python...",
  "benefits": "- Health...",
  "skills": ["Python", "FastAPI", "PostgreSQL"],
  "rounds": ["Screening", "Technical", "HR"]
}
```

### List Jobs
```
GET /api/v1/jobs?status=PUBLISHED&department=Engineering&page=1&limit=20
Authorization: Bearer <token> (optional for public)
```

### Get Job Detail
```
GET /api/v1/jobs/{id}
Authorization: Bearer <token> (optional)
```

### Update Job
```
PUT /api/v1/jobs/{id}
Authorization: Bearer <token> (hr_admin, manager)
```

### Publish Job
```
POST /api/v1/jobs/{id}/publish
Authorization: Bearer <token> (hr_admin, manager, recruiter)
{
  "channel_name": "career_site",
  "is_active": true
}
```

### Generate AI Job Description
```
POST /api/v1/jobs/generate-description
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: application/json

{
  "job_title": "Senior Python Developer",
  "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
  "location": "San Francisco, CA",
  "experience_min": 5,
  "experience_max": 8,
  "employment_type": "Full-time",
  "department": "Engineering",
  "seniority_level": "Senior",
  "work_mode": "Hybrid",
  "salary_min": 120000,
  "salary_max": 180000,
  "currency": "USD"
}
```

---

## Public Career Portal

### List Published Jobs
```
GET /api/public/careers
```
Response: `APIResponse<list[JobResponse]>`

### Search Jobs
```
GET /api/public/careers/search?q=python
```

### Filter Jobs
```
GET /api/public/careers/filter?department=Engineering&location=Remote
```

### Get Job by Slug
```
GET /api/public/careers/{slug}
```

### Apply by Slug
```
POST /api/public/careers/{slug}/apply
Content-Type: multipart/form-data

Form Fields:
- first_name, last_name, email, phone
- country, state, city
- current_company, current_designation (optional)
- current_ctc, expected_ctc (optional)
- notice_period, highest_qualification (optional)
- experience_years, is_fresher (optional)
- linkedin_url, portfolio_url (optional)
- cover_letter (optional)
- declaration_checked: true (required)
- resume_file: PDF/DOCX ≤ 5MB (required)
```

### Get Job by Channel Key
```
GET /api/public/careers/channel/{ukey}
```

### Apply by Channel Key
```
POST /api/public/careers/channel/{ukey}/apply
Content-Type: multipart/form-data
(Same form fields as above)
```

---

## Candidate & Application Management

### List Applications (HR)
```
GET /api/v1/recruitment/applications?job_id=xxx&status=APPLIED&page=1&limit=20
Authorization: Bearer <token> (hr_admin, manager)
```

### Get Application Detail
```
GET /api/v1/recruitment/applications/{id}
Authorization: Bearer <token> (hr_admin, manager)
```

### Update Application Status
```
PUT /api/v1/recruitment/applications/{id}/status
Authorization: Bearer <token> (hr_admin, manager)
{
  "status": "SHORTLISTED"
}
```

---

## AI Resume Screening & ATS

### Upload & Screen Resume
```
POST /api/v1/recruitment/resumes/upload
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: multipart/form-data

- file: PDF/DOCX/TXT/PNG/JPG ≤ 10MB
- job_id: UUID (optional)
```

### Parse Resume Direct
```
POST /api/v1/recruitment/resumes/parse
Authorization: Bearer <token> (hr_admin, manager)
{
  "raw_text": "resume text...",
  "job_id": "uuid (optional)"
}
```

### List Parsed Candidates
```
GET /api/v1/recruitment/candidates?search=python&status=COMPLETED&page=1&limit=20
Authorization: Bearer <token> (hr_admin, manager)
```

### Get Candidate Profile
```
GET /api/v1/recruitment/candidates/{candidate_id}
Authorization: Bearer <token> (hr_admin, manager)
```

### Get ATS Analysis
```
GET /api/v1/recruitment/candidates/{candidate_id}/ats
Authorization: Bearer <token> (hr_admin, manager)
```

### Match Candidate to Job
```
POST /api/v1/recruitment/candidates/{candidate_id}/match/{job_id}
Authorization: Bearer <token> (hr_admin, manager)
```

### Match All Candidates for Job
```
POST /api/v1/recruitment/jobs/{job_id}/match
Authorization: Bearer <token> (hr_admin, manager)
```

---

## AI Screening v2

### Screen Single Candidate
```
POST /api/v2/screening/screen
Authorization: Bearer <token> (hr_admin, manager)
{
  "resume_document_id": "uuid",
  "job_id": "uuid",
  "model": "llama3 (optional)",
  "auto_apply_decision": false
}
```

### Batch Screen
```
POST /api/v2/screening/batch-screen
Authorization: Bearer <token> (hr_admin, manager)
{
  "job_id": "uuid",
  "resume_document_ids": ["uuid1", "uuid2"],
  "model": "llama3 (optional)",
  "auto_apply_decisions": false
}
```

### Trigger Job Screening Run
```
POST /api/v2/screening/jobs/{job_id}/run
Authorization: Bearer <token> (hr_admin, manager)
{
  "application_ids": ["uuid1", "uuid2"],
  "model": "llama3 (optional)"
}
```

### Get Screening Results
```
GET /api/v2/screening/jobs/{job_id}/results?decision=SHORTLIST&page=1&limit=20
Authorization: Bearer <token> (hr_admin, manager)
```

### Submit Human Decision
```
POST /api/v2/screening/results/{screening_id}/decision
Authorization: Bearer <token> (hr_admin, manager)
{
  "action": "SHORTLIST",
  "reason": "Strong technical background"
}
```

---

## Traditional Interview Management

### Initiate Interview
```
POST /api/v1/interviews/applications/{id}/send-interview
Authorization: Bearer <token> (hr_admin, manager)
?round_names=["Screening", "Technical", "HR"]
```

### Schedule Interview (Candidate - Token Based)
```
POST /api/v1/interviews/schedule
Content-Type: application/json

{
  "invitation_token": "secure_token_from_email",
  "interview_date": "2026-11-20",
  "interview_time": "10:00:00",
  "mode": "ONLINE",
  "meeting_url": "https://meet.example.com/abc123"
}
```

### List Interviews (HR)
```
GET /api/v1/interviews/interviews?status=SCHEDULED&page=1&limit=20
Authorization: Bearer <token> (hr_admin, manager)
```

### Get Interview Detail
```
GET /api/v1/interviews/interviews/{id}
Authorization: Bearer <token> (hr_admin, manager)
```

### Complete Round
```
PATCH /api/v1/interviews/interviews/rounds/{round_id}/pass
Authorization: Bearer <token> (hr_admin, manager)
{
  "feedback": "Good technical knowledge",
  "score": "8/10",
  "interviewer_name": "John Doe"
}
```

---

## AI Video Interview (v2)

### Initialize Session (Admin/HR)
```
POST /api/v2/interview-bot/sessions
Authorization: Bearer <token> (hr_admin, manager)
{
  "candidate_id": "uuid",
  "job_id": "uuid",
  "interview_type": "VIDEO",
  "round_id": "uuid (optional)"
}
```

### Start Session (Candidate)
```
POST /api/v2/interview-bot/sessions/{session_id}/start?invitation_token=xxx
```
Response:
```json
{
  "session_id": "uuid",
  "first_question": {
    "id": "uuid",
    "text": "Explain async vs sync...",
    "type": "TECHNICAL",
    "difficulty": "MEDIUM"
  }
}
```

### Submit Answer (Candidate - Text)
```
POST /api/v2/interview-bot/sessions/{session_id}/answer?invitation_token=xxx
Content-Type: application/json

{
  "question_id": "uuid",
  "candidate_response": "My answer...",
  "code_output": "optional",
  "duration_seconds": 120,
  "emotion": {"calm": 0.8, "confident": 0.7},
  "communication": {"pace_wpm": 130, "filler_word_count": 2},
  "proctoring": {"tab_switches": 0, "gaze_deviation_detected": false},
  "model": "llama3"
}
```
Response:
```json
{
  "session_status": "IN_PROGRESS",
  "score_logged": 8,
  "evaluation_status": "COMPLETED",
  "evaluation": "Good understanding...",
  "next_question": {
    "id": "uuid",
    "text": "Follow-up: How would you handle...",
    "type": "TECHNICAL",
    "difficulty": "HARD"
  }
}
```

### Proctor Alert (Candidate)
```
POST /api/v2/interview-bot/sessions/{session_id}/proctor-alert?invitation_token=xxx
{
  "alert_type": "TAB_SWITCH",
  "details": "Candidate switched tabs 3 times"
}
```

### Finalize Session (Admin/HR)
```
POST /api/v2/interview-bot/sessions/{session_id}/finalize
Authorization: Bearer <token> (hr_admin, manager)
```
Response:
```json
{
  "scorecard_id": "uuid",
  "final_recommendation": "HIRE",
  "justification": "Strong technical skills...",
  "anti_cheating": {"total_warnings": 0, "suspicious_activity_flagged": false},
  "emotion": {"predominant_state": "calm", "confidence": 0.85},
  "communication": {"average_pace_wpm": 125}
}
```

---

## WebSocket Real-Time Interview (Audio/Video Pipeline)

### Connect
```
WS /api/v2/interview-ws/session/{invitation_token}
```

### Message Types

**Client → Server**
| Type | Description |
|------|-------------|
| `audio_chunk` | Binary audio data (opus/webm) |
| `answer_text` | Text fallback for answer |
| `device_check` | Camera/microphone test results |
| `consent` | Recording consent |
| `proctor_alert` | Tab switch, gaze deviation, etc. |
| `ping` | Heartbeat |
| `reconnect` | Explicit reconnection |

**Server → Client**
| Type | Description |
|------|-------------|
| `session_started` | Session info + first question |
| `question_audio` | Base64-encoded TTS audio |
| `question_text` | Question text |
| `answer_evaluated` | Score + feedback + next question |
| `transcription_partial` | Interim STT result |
| `transcription_final` | Final STT result |
| `tts_audio` | Base64-encoded TTS audio |
| `tts_complete` | TTS finished |
| `session_completed` | Final scorecard |
| `proctor_ack` | Proctor alert acknowledged |
| `pong` | Heartbeat response |
| `reconnected` | Reconnection confirmed |
| `error` | Error message |
| `device_check_result` | Device check outcome |
| `consent_result` | Consent outcome |

### Message Flow

**1. Client → Server: Device Check**
```json
{
  "type": "device_check",
  "has_camera": true,
  "has_microphone": true,
  "camera_test_passed": true,
  "microphone_test_passed": true,
  "browser_info": "Chrome/120.0.0"
}
```

**Server → Client: Device Check Result**
```json
{
  "type": "device_check_result",
  "success": true,
  "message": "Device check passed. You may proceed."
}
```

**2. Client → Server: Consent**
```json
{
  "type": "consent",
  "consent_given": true
}
```

**Server → Client: Consent Result**
```json
{
  "type": "consent_result",
  "success": true,
  "message": "Consent recorded. You may now start the interview."
}
```

**3. Server → Client: Session Started**
```json
{
  "type": "session_started",
  "session_id": "uuid",
  "invitation_id": "uuid",
  "round_name": "Technical Round",
  "job_title": "Senior Python Developer",
  "company_name": "Acme Corp",
  "total_questions": 7,
  "current_question_index": 0,
  "first_question": {
    "id": "uuid",
    "text": "Explain async/await...",
    "type": "TECHNICAL",
    "difficulty": "MEDIUM"
  },
  "grace_period_ends_at": "2026-11-17T12:30:00Z"
}
```

**4. Server → Client: Question Audio (TTS)**
```json
{
  "type": "question_audio",
  "question_id": "uuid",
  "audio_data": "base64_encoded_mp3",
  "format": "mp3",
  "sample_rate": 22050
}
```

**5. Client → Server: Audio Chunk**
```json
// Binary message (WebSocket binary frame)
// Raw opus/webm audio data
```

**Server → Client: Partial Transcription (Interim)**
```json
{
  "type": "transcription_partial",
  "question_id": "uuid",
  "text": "I think the answer is...",
  "is_final": false,
  "confidence": 0.7
}
```

**Server → Client: Final Transcription**
```json
{
  "type": "transcription_final",
  "question_id": "uuid",
  "text": "I think the answer is async await...",
  "confidence": 0.92,
  "language": "en"
}
```

**Server → Client: Answer Evaluated**
```json
{
  "type": "answer_evaluated",
  "question_id": "uuid",
  "score_logged": 8,
  "evaluation_status": "COMPLETED",
  "evaluation": "Good understanding of async patterns...",
  "next_question": {
    "id": "uuid",
    "text": "How do you handle exceptions in async code?",
    "type": "TECHNICAL",
    "difficulty": "HARD"
  },
  "session_status": "IN_PROGRESS"
}
```

**Server → Client: TTS Audio for Feedback/Next Question**
```json
{
  "type": "tts_audio",
  "audio_data": "base64_encoded_mp3",
  "format": "mp3",
  "sample_rate": 22050
}
```

**6. Server → Client: Session Completed**
```json
{
  "type": "session_completed",
  "scorecard_id": "uuid",
  "final_recommendation": "HIRE",
  "justification": "Excellent technical depth..."
}
```

### Reconnection
```json
// Client → Server
{"type": "reconnect"}

// Server → Client
{"type": "reconnected", "grace_period_ends_at": "2026-11-17T12:30:00Z"}
```

### Proctoring
```json
// Client → Server
{"type": "proctor_alert", "alert_type": "TAB_SWITCH", "details": "Tab switched at 10:15:30"}

// Server → Client
{"type": "proctor_ack", "alert_type": "TAB_SWITCH"}
```

### Ping/Pong
```json
{"type": "ping"} → {"type": "pong"}
```

---

## HR Interview Dashboard

### List Interview Sessions
```
GET /api/hr/interviews?job_id=xxx&candidate_id=xxx&status=COMPLETED&date_from=2026-11-01&page=1&limit=20
Authorization: Bearer <token> (hr_admin, manager)
```
Returns both traditional and AI video interviews.

### Get Interview Detail
```
GET /api/hr/interviews/{id}
Authorization: Bearer <token> (hr_admin, manager)
```
Response includes:
- Traditional: rounds, schedules, feedback
- AI Video: questions, responses, scores, transcript, scorecard

### Add HR Feedback
```
POST /api/hr/interviews/{id}/feedback
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: application/x-www-form-urlencoded

feedback=HR notes about candidate...
```

### Override AI Recommendation
```
POST /api/hr/interviews/{id}/override
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: application/x-www-form-urlencoded

recommendation=HIRE&reason=Exceptional problem-solving demonstrated
```
Valid recommendations: `STRONG_HIRE`, `HIRE`, `MAYBE`, `REJECT`

### Advance Candidate
```
POST /api/hr/interviews/{id}/advance
Authorization: Bearer <token> (hr_admin, manager)
Content-Type: application/x-www-form-urlencoded

action=SHORTLIST&round_name=Final Round
```
Actions: `SHORTLIST`, `SCHEDULE_ROUND`, `REJECT`, `HOLD`

---

## Job Requisitions

### Create Requisition
```
POST /api/v1/requisitions
Authorization: Bearer <token> (hr_admin, manager, recruiter)
{
  "title": "Senior Python Developer",
  "department": "Engineering",
  "vacancies": 2,
  "min_experience": 5,
  "max_experience": 8,
  "min_salary": 120000,
  "max_salary": 180000,
  "description": "We need a senior developer..."
}
```

### Approve Requisition
```
POST /api/v1/requisitions/{id}/approve
Authorization: Bearer <token> (hr_admin, manager)
{
  "requisition_id": "uuid",
  "approve": true,
  "location": "San Francisco, CA",
  "employment_type": "FULL_TIME"
}
```

---

## Offers & Hiring

### Create Offer
```
POST /api/v1/recruitment/offers
Authorization: Bearer <token> (hr_admin, manager)
{
  "application_id": "uuid",
  "ctc": 150000,
  "joining_date": "2026-12-01",
  "offer_expiry_date": "2026-11-30"
}
```

### Update Offer Status
```
PATCH /api/v1/recruitment/offers/{id}/status
Authorization: Bearer <token> (hr_admin, manager)

# Status transitions: SENT → ACCEPTED/REJECTED/EXPIRED/WITHDRAWN
# ACCEPTED triggers employee onboarding creation
```

---

## Interview Recording & Media

### Start Recording (via WebSocket consent)
Recording starts automatically after consent is given via WebSocket.

### Get Recordings for Session
```
GET /api/hr/interviews/{id}/recordings
Authorization: Bearer <token> (hr_admin, manager)
```

### Get Recording Stream
```
GET /api/hr/interviews/{id}/recordings/{recording_id}/stream?start_byte=0&end_byte=1024
Authorization: Bearer <token> (hr_admin, manager)
```

### Download Recording
```
GET /api/hr/interviews/{id}/recordings/{recording_id}/download
Authorization: Bearer <token> (hr_admin, manager)
```

### Generate Download URL
```
GET /api/hr/interviews/{id}/recordings/{recording_id}/download-url
Authorization: Bearer <token> (hr_admin, manager)
```

---

## Recruitment Analytics

### Get Dashboard Stats
```
GET /api/v1/recruitment/analytics
Authorization: Bearer <token> (hr_admin, manager, super_admin)
```

### Get Full Analytics
```
GET /api/v1/recruitment/recruitment-analytics?department=Engineering&start_date=2026-01-01&end_date=2026-11-30
Authorization: Bearer <token> (hr_admin, manager, super_admin)
```

Response includes:
- Job metrics (total, active, draft, closed, requisitions)
- Applicant metrics (candidates, applications, talent pool)
- Pipeline breakdown (applied, shortlisted, interviewed, offered, hired, rejected)
- Conversion rates (stage-to-stage, overall hire rate, time-to-hire)
- Funnel visualization
- Department & source breakdowns

---

## STT/TTS Provider Integration

### STT Providers
```python
from app.services.stt import get_stt_provider, get_stt_router

# Get specific provider
provider = get_stt_provider("deepgram")

# Or get best available
provider = await get_stt_router()
```

### TTS Providers
```python
from app.services.tts import get_tts_provider, get_tts_router

# Get specific provider
provider = get_tts_provider("elevenlabs")

# Or get best available
provider = await get_tts_router()
```

---

## Error Formats

### Standard Error Response
```json
{
  "success": false,
  "message": "Human-readable error description",
  "data": null,
  "errors": ["Detailed error 1", "Detailed error 2"]
}
```

### HTTP Status Codes
- `200` - Success
- `201` - Created
- `400` - Bad Request (validation error)
- `401` - Unauthorized (invalid/expired token)
- `403` - Forbidden (insufficient permissions, cross-tenant access)
- `404` - Not Found
- `409` - Conflict (duplicate, already used)
- `410` - Gone (expired invitation)
- `422` - Unprocessable Entity (validation failed)
- `500` - Internal Server Error
- `503` - Service Unavailable (LLM/provider down)

---

## Rate Limits

- Resume upload: 10 requests/minute per user/IP
- AI screening: 50 requests/minute per company
- Interview WebSocket: 1 connection per invitation token
- General API: 1000 requests/minute per user
- STT/TTS: Provider-specific limits apply

---

## Frontend Integration Requirements

### AI Video Interview Flow

1. **Candidate receives email** with invitation link: `https://app.ofc360.com/interview/join?token={invitation_token}`

2. **Join Page** (`/interview/join?token=xxx`):
   - Call `GET /api/v2/interview-bot/sessions/{session_id}/start?invitation_token=xxx` to validate
   - Display company, role, round info
   - Show "Start Interview" button

3. **Device Check Page**:
   - Request camera/microphone permissions
   - Test video preview, audio level meter
   - Call `POST /api/hr/interviews/join/{token}/device-check` with results

4. **Consent Page**:
   - Display recording/privacy notice
   - Call `POST /api/hr/interviews/join/{token}/consent` with `consent_given=true`

5. **Interview Page**:
   - Establish WebSocket: `WS /api/v2/interview-ws/session/{invitation_token}`
   - Handle message types: `session_started`, `answer_evaluated`, `session_completed`, `proctor_ack`
   - Send `audio_chunk` messages with candidate response
   - Display questions, collect answers (text/voice/video)
   - Show progress: current question X of Y
   - Handle reconnection gracefully

6. **Completion**:
   - Display final recommendation summary
   - Thank candidate, provide next steps info

### HR Dashboard Integration

1. **Interview List Page**:
   - Call `GET /api/hr/interviews` with filters
   - Display paginated table with type badges (Traditional / AI Video)
   - Status filters: All, Scheduled, In Progress, Completed, Interrupted

2. **Interview Detail Page**:
   - Call `GET /api/hr/interviews/{id}`
   - Traditional: Show rounds, schedules, feedback
   - AI Video: Show question timeline, responses, scores, transcript, scorecard
   - Play recordings (if available)
   - Add feedback: `POST /api/hr/interviews/{id}/feedback`
   - Override: `POST /api/hr/interviews/{id}/override`
   - Advance: `POST /api/hr/interviews/{id}/advance`

---

## External Service Dependencies

| Service | Purpose | Required For | Config |
|---------|---------|--------------|--------|
| Ollama / LLM | Question generation, evaluation, scoring | AI Video Interview, AI Screening | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| PostgreSQL | Primary data store | All features | `DATABASE_URL` |
| Redis | Token blacklist, caching, rate limiting | Auth, Screening, Rate limits | `REDIS_URL` |
| Email Service | Invitations, notifications | Career portal, Interview scheduling | `SMTP_*` settings |
| S3/MinIO | Resume storage, recordings | File uploads, interview recordings | `S3_*` settings |
| TURN Server | WebRTC NAT traversal | Video interview media | `TURN_*` settings |

---

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Ollama/LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
AI_SCREENING_THRESHOLD=0.75
AI_REJECTION_THRESHOLD=0.4
AI_AUTO_REJECT_ENABLED=false

# Email
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=<sendgrid-api-key>
SMTP_TLS=true
EMAIL_FROM=noreply@ofc360.com
EMAIL_FROM_NAME=OFC360 Recruitment

# File Storage
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY_ID=AKI...
S3_SECRET_ACCESS_KEY=...
S3_BUCKET=ofc360-prod-uploads
S3_REGION=us-east-1
S3_PUBLIC_URL=https://cdn.ofc360.com

# WebRTC
TURN_SERVER=turn:turn.ofc360.com:3478
TURN_TLS_SERVER=turns:turn.ofc360.com:5349
TURN_USERNAME=ofc360
TURN_PASSWORD=<turn-secret>
TURN_REALM=ofc360.com

# STT Providers
DEEPGRAM_API_KEY=xxx
DEEPGRAM_MODEL=nova-2
OPENAI_API_KEY=xxx
GOOGLE_CLOUD_CREDENTIALS_PATH=/path/to/credentials.json
GOOGLE_CLOUD_PROJECT_ID=my-project

# TTS Providers
ELEVENLABS_API_KEY=xxx
ELEVENLABS_MODEL=eleven_multilingual_v2
OPENAI_API_KEY=xxx
OPENAI_TTS_MODEL=tts-1
AZURE_TTS_API_KEY=xxx
AZURE_TTS_REGION=eastus
GOOGLE_CLOUD_CREDENTIALS_PATH=/path/to/credentials.json

# Security
ENVIRONMENT=production
SUPER_ADMIN_PASSWORD=secure-password
```

---

## Versioning & Deprecation

- **v1** (`/api/v1/recruitment/*`): Stable, legacy REST endpoints
- **v2** (`/api/v2/*`): New AI-powered endpoints (screening, interview bot)
- **Public** (`/api/public/careers/*`): Unauthenticated career portal
- **HR** (`/api/hr/interviews/*`): Administrative review dashboard
- **WebSocket** (`/api/v2/interview-ws/*`): Real-time interview communication

### Deprecation Policy
- 6-month notice for breaking changes
- Both versions maintained during transition
- Migration guides provided for major changes

---

## Support & Monitoring

### Health Checks
- `GET /health` - Basic service health
- `GET /health/db` - Database connectivity
- `GET /health/redis` - Redis connectivity
- `GET /health/ollama` - LLM service availability
- `GET /health/stt` - STT provider availability
- `GET /health/tts` - TTS provider availability

### Key Metrics to Monitor
- Interview completion rate
- AI evaluation latency (p50, p95, p99)
- Screening decision accuracy
- Cross-tenant access attempts (should be 0)
- WebSocket connection duration
- Token expiry/reconnection rate
- STT transcription accuracy
- TTS synthesis latency
- Recording upload success rate

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | Nov 2026 | AI Video Interview backend, STT/TTS providers, recording, WebSocket pipeline |
| 1.5.0 | Oct 2026 | AI Screening v2, multi-tenant fixes, job requisition workflow |
| 1.0.0 | Sep 2026 | Initial recruitment module release |
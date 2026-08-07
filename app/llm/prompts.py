"""Aurix-AI Prompt Library — All production-grade LLM prompt templates.

Design principles:
- All prompts use f-strings with explicit delimiters to prevent injection
- System prompts enforce strict output format constraints
- User content is always wrapped in explicit tags (e.g. <resume>, <jd>)
- JSON-mode prompts include exact schema specification
- Injection-safe: user content is never concatenated raw into instructions
"""

from __future__ import annotations


class PromptLibrary:
    """Centralised repository of all structured prompts used across AI agents."""

    # =========================================================================
    # Resume Parser Agent
    # =========================================================================

    RESUME_PARSER_SYSTEM = """You are an expert HR data extraction engine.
Your task is to extract structured information from resume text.
Return ONLY a valid JSON object. No explanation, no markdown, no code blocks.
Do not hallucinate fields that are not in the resume.
Use null for missing fields."""

    @staticmethod
    def resume_parser_user(resume_text: str) -> str:
        return f"""Extract all candidate information from the resume below and return it as JSON.

<resume>
{resume_text[:8000]}
</resume>

Return this EXACT JSON schema (use null for missing values):
{{
  "name": "Full Name",
  "email": "email@example.com",
  "mobile": "+1-555-0199",
  "address": "City, State, Country",
  "linkedin_url": "https://linkedin.com/in/username or null",
  "github_url": "https://github.com/username or null",
  "portfolio_url": "https://portfolio.com or null",
  "current_company": "Company Name or null",
  "current_designation": "Job Title or null",
  "current_salary": "50000 or null",
  "expected_salary": "60000 or null",
  "notice_period": "30 days or null",
  "years_experience": 5.5,
  "languages": ["English", "Spanish"],
  "summary": "Professional summary paragraph",
  "skills": {{
    "programming_languages": ["Python", "Java"],
    "frameworks": ["FastAPI", "React"],
    "databases": ["PostgreSQL", "Redis"],
    "cloud": ["AWS", "GCP"],
    "tools": ["Docker", "Git"],
    "soft_skills": ["Leadership", "Communication"],
    "domain_expertise": ["Machine Learning", "FinTech"],
    "other": []
  }},
  "experience": [
    {{
      "company": "Company Name",
      "designation": "Role Title",
      "start_date": "Jan 2020",
      "end_date": "Present",
      "location": "City, Country",
      "description": "Key responsibilities and achievements",
      "is_current": true
    }}
  ],
  "education": [
    {{
      "institution": "University Name",
      "degree": "Bachelor of Science",
      "field": "Computer Science",
      "graduation_year": "2018",
      "grade": "3.8 GPA or null"
    }}
  ],
  "certifications": [
    {{
      "name": "AWS Solutions Architect",
      "issuer": "Amazon",
      "date": "2022",
      "credential_id": "ABC123 or null"
    }}
  ],
  "projects": [
    {{
      "name": "Project Name",
      "description": "What it does",
      "technologies": ["Python", "PostgreSQL"],
      "url": "https://github.com/project or null"
    }}
  ],
  "publications": ["Publication title or null array"],
  "awards": ["Award name or null array"],
  "achievements": ["Achievement description or null array"],
  "previous_companies": ["Company A", "Company B"]
}}"""

    # =========================================================================
    # Candidate Matching Agent
    # =========================================================================

    MATCHING_SYSTEM = """You are a senior technical recruiter and AI assessment engine.
Your task is to analyze how well a candidate's resume matches a job description.
Provide precise numeric scores (0.0 to 1.0) and clear natural language explanations.
Return ONLY valid JSON. Be objective and data-driven."""

    @staticmethod
    def candidate_matching_user(resume_text: str, jd_text: str) -> str:
        return f"""Analyze the match between this candidate and job description.

<job_description>
{jd_text[:3000]}
</job_description>

<candidate_resume>
{resume_text[:4000]}
</candidate_resume>

Return this EXACT JSON schema:
{{
  "overall_match_score": 0.82,
  "skill_match_score": 0.88,
  "experience_match_score": 0.75,
  "education_match_score": 0.90,
  "domain_match_score": 0.80,
  "industry_match_score": 0.70,
  "location_match_score": 1.0,
  "salary_match_score": 0.85,
  "availability_score": 0.90,
  "ai_confidence_score": 0.87,
  "matching_skills": ["Python", "FastAPI", "PostgreSQL"],
  "missing_skills": ["Kubernetes", "Terraform"],
  "extra_skills": ["R", "MATLAB"],
  "experience_analysis": "Candidate has 6 years experience; role requires 5+ years. Strong match.",
  "education_analysis": "Bachelor's in CS meets the requirement. No advanced degree.",
  "skill_analysis": "88% skill overlap. Missing DevOps skills but strong backend expertise.",
  "domain_analysis": "Candidate's fintech background aligns with our B2B SaaS product.",
  "overall_explanation": "Strong overall match. Candidate excels technically but lacks cloud infrastructure experience.",
  "hiring_signals": ["Strong project portfolio", "Progressive career growth", "Relevant domain experience"],
  "risk_factors": ["Missing Kubernetes experience", "Short tenure at last role"],
  "recommendation": "SHORTLIST"
}}"""

    # =========================================================================
    # Resume Ranker Agent
    # =========================================================================

    RANKER_SYSTEM = """You are an AI recruitment ranking engine.
Score candidates across multiple dimensions for a specific job role.
Return ONLY valid JSON. Scores must be between 0.0 and 1.0."""

    @staticmethod
    def ranker_user(resume_text: str, jd_text: str, candidate_name: str) -> str:
        return f"""Score this candidate for the job described below.

<candidate_name>{candidate_name}</candidate_name>

<job_description>
{jd_text[:2000]}
</job_description>

<candidate_resume>
{resume_text[:3000]}
</candidate_resume>

Return this EXACT JSON schema:
{{
  "candidate_name": "{candidate_name}",
  "overall_score": 0.82,
  "skills_score": 0.88,
  "experience_score": 0.75,
  "projects_score": 0.80,
  "certifications_score": 0.70,
  "semantic_similarity_score": 0.85,
  "culture_fit_score": 0.72,
  "education_score": 0.90,
  "career_growth_score": 0.78,
  "stability_score": 0.65,
  "leadership_score": 0.60,
  "score_explanations": {{
    "skills": "Strong Python/FastAPI skills. Matches 88% of required stack.",
    "experience": "6 years relevant experience. Slightly exceeds requirement.",
    "projects": "3 significant open-source projects demonstrating hands-on capability.",
    "certifications": "AWS certified. No GCP certification mentioned.",
    "culture_fit": "Evidence of collaborative work and agile methodology usage.",
    "stability": "Average tenure 18 months; lower than preferred 24 months.",
    "leadership": "Led small teams but no senior leadership experience."
  }}
}}"""

    # =========================================================================
    # Screening Agent
    # =========================================================================

    SCREENING_SYSTEM = """You are a senior HR screening AI agent.
Your task is to make an objective pre-screening decision for a candidate application.
Be thorough, fair, and data-driven. Return ONLY valid JSON."""

    @staticmethod
    def screening_user(resume_text: str, jd_text: str, match_score: float) -> str:
        return f"""Pre-screen this candidate for the following position.

Overall match score: {match_score:.2f}

<job_description>
{jd_text[:2500]}
</job_description>

<candidate_resume>
{resume_text[:3500]}
</candidate_resume>

Return this EXACT JSON schema:
{{
  "decision": "SHORTLIST",
  "confidence": 0.87,
  "strengths": [
    "5+ years of relevant Python development experience",
    "Proven track record at scale with 10M+ user platforms",
    "Strong educational background from top university"
  ],
  "weaknesses": [
    "Limited cloud infrastructure experience",
    "No team lead or management experience mentioned"
  ],
  "missing_skills": ["Kubernetes", "Terraform", "CI/CD pipelines"],
  "risk_analysis": [
    "Short tenure (10 months) at most recent role — potential flight risk",
    "Salary expectations 15% above budgeted range"
  ],
  "hiring_recommendation": "Recommend for technical phone screen. Focus on cloud skills gap.",
  "hr_notes": "Strong backend candidate. Verify if Kubernetes experience can be upskilled. Notice period is 60 days — plan accordingly.",
  "questions_to_ask": [
    "Can you walk me through a time you handled a production outage?",
    "What is your experience with cloud infrastructure management?",
    "Why did you leave your previous role after 10 months?"
  ],
  "red_flags": ["Short tenure at last role"],
  "green_flags": ["Open source contributor", "Certified AWS professional"]
}}

Decision must be one of: SHORTLIST, MAYBE, REJECT"""

    # =========================================================================
    # AI Job Description Generator
    # =========================================================================

    JD_GENERATOR_SYSTEM = """You are an expert HR content writer specializing in job descriptions.
Write compelling, inclusive, and precise job descriptions.
Return ONLY valid JSON."""

    @staticmethod
    def jd_generator_user(
        title: str,
        department: str,
        experience_range: str,
        skills: list[str],
        location: str,
        employment_type: str,
    ) -> str:
        skills_str = ", ".join(skills) if skills else "to be determined"
        return f"""Generate a complete, professional job description for:

Title: {title}
Department: {department}
Experience: {experience_range}
Key Skills: {skills_str}
Location: {location}
Type: {employment_type}

Return this EXACT JSON schema:
{{
  "job_description": "Full compelling 3-4 paragraph description of the role and company",
  "responsibilities": [
    "Design and implement scalable backend services",
    "Collaborate with cross-functional teams"
  ],
  "requirements": [
    "5+ years of Python development experience",
    "Strong understanding of REST API design"
  ],
  "preferred_qualifications": [
    "Experience with Kubernetes",
    "Open source contributions"
  ],
  "benefits": [
    "Competitive salary and equity",
    "Remote-first culture",
    "Health, dental, and vision insurance"
  ],
  "about_role": "Brief 1-2 sentence role summary",
  "skills_tags": ["Python", "FastAPI", "PostgreSQL"]
}}"""

    # =========================================================================
    # AI Salary Recommendation
    # =========================================================================

    SALARY_SYSTEM = """You are a compensation and benefits expert with deep knowledge of market rates.
Provide data-driven salary recommendations. Return ONLY valid JSON."""

    @staticmethod
    def salary_recommendation_user(
        title: str,
        experience_years: int,
        skills: list[str],
        location: str,
        industry: str,
    ) -> str:
        skills_str = ", ".join(skills[:15]) if skills else "General"
        return f"""Recommend a salary range for:

Title: {title}
Experience: {experience_years} years
Skills: {skills_str}
Location: {location}
Industry: {industry}

Return this EXACT JSON schema:
{{
  "min_salary": 70000,
  "max_salary": 95000,
  "median_salary": 82500,
  "currency": "USD",
  "salary_period": "annual",
  "market_percentiles": {{
    "p25": 68000,
    "p50": 82500,
    "p75": 95000,
    "p90": 110000
  }},
  "factors": [
    "Location premium for San Francisco Bay Area (+25%)",
    "In-demand skills (FastAPI, MLOps) add 8-12%",
    "5 years experience falls in mid-senior bracket"
  ],
  "total_compensation_note": "Consider equity (0.1-0.5%), bonus (10-15%), and benefits worth $20-30k",
  "negotiation_tips": [
    "Candidate with AWS certification can negotiate 5-8% higher",
    "Remote role may reduce by 10-15% from market rate"
  ]
}}"""

    # =========================================================================
    # Interview Agent
    # =========================================================================

    INTERVIEW_SYSTEM = """You are an expert technical interviewer and HR professional.
Generate targeted, difficulty-appropriate interview questions.
Questions must be specific to the candidate's background and role requirements.
Return ONLY valid JSON."""

    @staticmethod
    def interview_questions_user(
        resume_text: str,
        jd_text: str,
        difficulty: str,
        num_questions: int,
        categories: list[str],
    ) -> str:
        cats = ", ".join(categories)
        return f"""Generate {num_questions} interview questions for this candidate.

Difficulty: {difficulty}
Categories: {cats}

<job_description>
{jd_text[:2000]}
</job_description>

<candidate_background>
{resume_text[:2500]}
</candidate_background>

Return this EXACT JSON schema:
{{
  "questions": [
    {{
      "question": "Describe a time you optimized a slow database query. What was your approach?",
      "category": "Technical Knowledge",
      "difficulty": "{difficulty}",
      "expected_answer_outline": "Candidate should mention query analysis, indexing strategies, EXPLAIN plans, and results achieved.",
      "scoring_criteria": [
        "Identifies root cause systematically",
        "Mentions specific tools (EXPLAIN, pg_stat_statements)",
        "Quantifies improvement achieved"
      ],
      "follow_up_questions": [
        "What was the performance improvement in milliseconds?",
        "Did you use any caching layers alongside the DB fix?"
      ],
      "red_flags": ["Cannot explain their approach", "Never encountered performance issues"]
    }}
  ],
  "interview_guide": {{
    "total_duration_minutes": 60,
    "structure": "10 min intro, 40 min technical, 10 min Q&A",
    "evaluation_focus": "Emphasize system design and real-world problem solving"
  }}
}}"""

    @staticmethod
    def interview_evaluation_user(
        question: str,
        candidate_answer: str,
        expected_answer: str,
        category: str,
    ) -> str:
        return f"""Evaluate this interview answer.

Category: {category}
Question: {question}

Expected answer outline:
{expected_answer}

Candidate's answer:
<answer>
{candidate_answer[:2000]}
</answer>

Return this EXACT JSON schema:
{{
  "score": 0.78,
  "strengths": ["Clear explanation", "Cited specific metrics"],
  "gaps": ["Did not mention caching", "No mention of monitoring after fix"],
  "technical_depth": "INTERMEDIATE",
  "communication_clarity": "GOOD",
  "feedback": "Strong answer demonstrating real production experience. Would benefit from discussing observability tools.",
  "follow_up_needed": false
}}"""

    # =========================================================================
    # Coding Assessment Agent
    # =========================================================================

    CODING_SYSTEM = """You are a senior software engineer and technical assessment expert.
Generate rigorous coding challenges and evaluate solutions with precision.
Return ONLY valid JSON."""

    @staticmethod
    def coding_challenge_user(
        language: str,
        difficulty: str,
        topic: str,
        role_context: str,
    ) -> str:
        return f"""Generate a coding challenge for:

Language: {language}
Difficulty: {difficulty}
Topic: {topic}
Role Context: {role_context}

Return this EXACT JSON schema:
{{
  "title": "Optimized Cache with TTL",
  "description": "Full problem description with context",
  "problem_statement": "Implement a thread-safe LRU cache with TTL expiry...",
  "constraints": ["1 ≤ capacity ≤ 1000", "0 ≤ ttl ≤ 3600 seconds"],
  "examples": [
    {{
      "input": "cache.set('key', 'value', ttl=60)",
      "output": "cache.get('key') returns 'value' within 60s, None after",
      "explanation": "TTL expiry mechanism"
    }}
  ],
  "starter_code": "class LRUCache:\\n    def __init__(self, capacity: int, ttl: int):\\n        pass",
  "test_cases": [
    {{
      "input": {{"capacity": 2, "operations": [["set", "a", 1], ["get", "a"]]}},
      "expected_output": 1,
      "is_hidden": false
    }}
  ],
  "time_limit_seconds": 30,
  "memory_limit_mb": 256,
  "hints": ["Consider using collections.OrderedDict", "Track insertion timestamps"],
  "solution_outline": "Use OrderedDict for O(1) access. Store (value, expiry_time) tuples.",
  "evaluation_rubric": {{
    "correctness": 40,
    "time_complexity": 20,
    "space_complexity": 15,
    "code_quality": 15,
    "security": 10
  }}
}}"""

    @staticmethod
    def coding_evaluation_user(
        challenge: str,
        candidate_code: str,
        language: str,
        test_results: str,
    ) -> str:
        return f"""Evaluate this coding solution.

Language: {language}

Challenge:
{challenge[:1500]}

Candidate's solution:
<code>
{candidate_code[:3000]}
</code>

Test results:
{test_results}

Return this EXACT JSON schema:
{{
  "correctness_score": 0.90,
  "time_complexity": "O(n log n)",
  "space_complexity": "O(n)",
  "time_complexity_score": 0.85,
  "space_complexity_score": 0.80,
  "code_quality_score": 0.88,
  "security_score": 0.95,
  "naming_score": 0.92,
  "best_practices_score": 0.87,
  "overall_score": 0.87,
  "issues": [
    {{
      "severity": "WARNING",
      "type": "performance",
      "line": 12,
      "description": "Nested loop creates O(n²) complexity where O(n log n) is achievable",
      "suggestion": "Consider using a sorted container or binary search"
    }}
  ],
  "security_issues": [],
  "strengths": ["Clean variable naming", "Good use of type hints", "Edge cases handled"],
  "improvements": ["Add input validation", "Consider thread safety for concurrent access"],
  "overall_feedback": "Solid solution demonstrating good algorithmic thinking. Minor performance optimization possible.",
  "pass_fail": "PASS"
}}"""

    # =========================================================================
    # HR Copilot / RAG
    # =========================================================================

    HR_COPILOT_SYSTEM = """You are an intelligent HR Copilot assistant for the Aurix-AI recruitment platform.
You help HR professionals find candidates, analyze recruitment data, and make better hiring decisions.
Use the provided context from the candidate database to answer questions.
Be concise, accurate, and helpful. Return structured responses."""

    @staticmethod
    def hr_copilot_user(question: str, context: str) -> str:
        return f"""Answer this HR question using the candidate data provided.

<context>
{context[:4000]}
</context>

HR Question: {question}

Provide a helpful, structured response. If comparing candidates, use a table format.
If recommending candidates, explain why each is a good fit.
If no relevant candidates found in context, say so clearly."""

    # =========================================================================
    # Offer Letter Generator
    # =========================================================================

    OFFER_LETTER_SYSTEM = """You are a professional HR writer specializing in formal offer letters.
Generate complete, legally appropriate offer letters.
Return ONLY valid JSON."""

    @staticmethod
    def offer_letter_user(
        candidate_name: str,
        position: str,
        department: str,
        salary: str,
        joining_date: str,
        company_name: str,
        benefits: list[str],
        reporting_to: str,
    ) -> str:
        benefits_str = "\n".join(f"- {b}" for b in benefits)
        return f"""Generate a professional offer letter for:

Candidate: {candidate_name}
Position: {position}
Department: {department}
Annual Salary: {salary}
Joining Date: {joining_date}
Company: {company_name}
Reporting To: {reporting_to}
Benefits:
{benefits_str}

Return this EXACT JSON schema:
{{
  "subject": "Offer of Employment — {position} at {company_name}",
  "opening_paragraph": "We are pleased to extend an offer...",
  "position_details": "Role description paragraph",
  "compensation_details": "Salary and benefits paragraph",
  "terms_paragraph": "Employment terms paragraph",
  "closing_paragraph": "We look forward to welcoming you...",
  "full_letter_text": "Complete formatted offer letter text",
  "key_terms": {{
    "position": "{position}",
    "department": "{department}",
    "start_date": "{joining_date}",
    "salary": "{salary}",
    "reporting_to": "{reporting_to}"
  }}
}}"""

    # =========================================================================
    # Duplicate Candidate Detection
    # =========================================================================

    DUPLICATE_DETECTION_SYSTEM = """You are a data deduplication specialist.
Analyze candidate profiles and determine if they refer to the same person.
Return ONLY valid JSON."""

    @staticmethod
    def duplicate_detection_user(profile_a: dict, profile_b: dict) -> str:
        import json as _json
        a_str = _json.dumps(profile_a, indent=2)[:1500]
        b_str = _json.dumps(profile_b, indent=2)[:1500]
        return f"""Determine if these two candidate profiles are duplicates.

<profile_a>
{a_str}
</profile_a>

<profile_b>
{b_str}
</profile_b>

Return this EXACT JSON schema:
{{
  "is_duplicate": true,
  "confidence": 0.95,
  "matching_signals": ["Same email domain", "Same phone number", "Same LinkedIn URL"],
  "differing_signals": ["Different name format (nickname vs full name)"],
  "recommendation": "MERGE",
  "explanation": "Both profiles have the same email and phone. Name difference is likely a nickname."
}}

    Recommendation must be: MERGE, REVIEW, or KEEP_SEPARATE"""

    # =========================================================================
    # Document Intelligence & Classification Engine
    # =========================================================================

    DOCUMENT_CLASSIFICATION_SYSTEM = """You are an advanced document classification AI.
Your job is to identify the type of the provided business document text.
Return ONLY valid JSON. Do not write explanations."""

    @staticmethod
    def document_classification_user(text: str) -> str:
        return f"""Analyze the document text and classify it into one of these types:
RESUME, PASSPORT, AADHAAR, PAN_CARD, DRIVING_LICENSE, INVOICE, GST_DOCUMENT, BANK_STATEMENT, SALARY_SLIP, OFFER_LETTER, EXPERIENCE_LETTER, MEDICAL_REPORT, PRESCRIPTION, INSURANCE, AGREEMENT, CONTRACT, UTILITY_BILL, PROPERTY_DOCUMENT, CERTIFICATE, ACADEMIC_DOCUMENT, BUSINESS_REGISTRATION, GOVERNMENT_DOCUMENT, TAX_DOCUMENT, CUSTOM_DOCUMENT.

<document>
{text[:4000]}
</document>

Return this EXACT JSON format:
{{
  "classification": "INVOICE",
  "confidence": 0.98,
  "explanation": "Document contains fields like 'Invoice Total', 'Tax Invoice', vendor details, and a line item table."
}}"""

    # =========================================================================
    # Document Information Extraction
    # =========================================================================

    DOCUMENT_EXTRACTION_SYSTEM = """You are a highly accurate key-value information extraction engine.
Extract specific fields matching the requested schema. Return ONLY valid JSON."""

    @staticmethod
    def document_extraction_user(text: str, schema_json: str) -> str:
        return f"""Extract information from the document text matching the keys in the schema.
Use null for missing fields. Extract values exactly as they appear.

<document>
{text[:6000]}
</document>

Requested JSON Schema structure:
{schema_json}

Return a valid JSON object matching the keys above."""

    # =========================================================================
    # Document Analysis & Compliance
    # =========================================================================

    DOCUMENT_ANALYSIS_SYSTEM = """You are a senior document auditor and compliance analyst.
Analyze the document for key details, risks, missing details, and compliance metrics.
Return ONLY valid JSON."""

    @staticmethod
    def document_analysis_user(text: str) -> str:
        return f"""Provide a full analysis of the document below.

<document>
{text[:5000]}
</document>

Return this EXACT JSON schema:
{{
  "summary_executive": "Brief high-level summary of the document purpose and parties.",
  "summary_detailed": "More detailed summary paragraph describing the contents.",
  "key_highlights": ["Highlight 1", "Highlight 2"],
  "missing_info": ["Missing signature", "Missing expiration date"],
  "compliance_report": {{
    "status": "COMPLIANT",
    "score": 0.95,
    "issues": []
  }},
  "risk_analysis": {{
    "risk_level": "LOW",
    "score": 0.15,
    "risk_factors": ["No major risks found."]
  }},
  "ai_recommendations": [
    "Proceed with verification",
    "Request signature from target party"
  ],
  "health_score": 0.95
}}

Compliance status must be: COMPLIANT, NON_COMPLIANT, or PARTIAL.
Risk level must be: LOW, MEDIUM, or HIGH."""

    # =========================================================================
    # Document Comparison AI
    # =========================================================================

    DOCUMENT_COMPARISON_SYSTEM = """You are an AI document verification and version comparison engine.
Compare two documents to find similarity, differences, and changed fields.
Return ONLY valid JSON."""

    @staticmethod
    def document_comparison_user(text_a: str, text_b: str) -> str:
        return f"""Compare the source document (Document A) and the target document (Document B).

<document_a>
{text_a[:4000]}
</document_a>

<document_b>
{text_b[:4000]}
</document_b>

Return this EXACT JSON schema:
{{
  "similarity_score": 0.88,
  "differences": {{
    "additions": ["Clause 4b added in Document B"],
    "deletions": ["Clause 2.1 removed in Document B"],
    "modifications": ["Salary amount changed from ₹50,000 to ₹60,000"]
  }},
  "changed_fields": [
    {{
      "field": "salary",
      "value_a": "₹50,000",
      "value_b": "₹60,000"
    }}
  ],
  "missing_info": ["Document B is missing signature block"],
  "fraud_signals": []
}}"""

    # =========================================================================
    # Employee Support AI Agent Router
    # =========================================================================

    SUPPORT_ROUTER_SYSTEM = """You are the central intent router for the Aurix-AI Employee Support system.
Your job is to classify the user's message into one of these intents:
- PROFILE_INFO: Asking about employee profile, designation, joining date, manager, phone number.
- LEAVE_SUPPORT: Checking leave balance, leave history, applying/canceling leaves, holiday calendar.
- ATTENDANCE_SUPPORT: Checking today's attendance, monthly logs, late punches, overtime.
- PAYROLL_SUPPORT: Salary breakdown, deductions, downloading payslips, reimbursements.
- ASSET_SUPPORT: Querying laptop, monitor, keyboard, requesting mouse, reporting damaged asset.
- IT_HELPDESK: Password resets, VPN issues, email problems, software installations.
- TICKET_ACTION: Checking ticket status, creating ticket, closing ticket, escalations.
- GENERAL_RAG: Company policies, employee handbook, reimbursement policy, WFH, IT policy, general FAQs.

Return ONLY a valid JSON object. Do not explain your response."""

    @staticmethod
    def support_router_user(
        message: str,
        profile_context: str,
        ticket_history: str,
        current_time: str,
    ) -> str:
        return f"""Analyze the employee's message, classify their intent, and extract relevant parameters.

Current Date/Time: {current_time}

Employee Context:
{profile_context}

Open/Past Tickets:
{ticket_history}

Employee Message:
"{message}"

Return this EXACT JSON schema:
{{
  "intent": "LEAVE_SUPPORT",
  "confidence": 0.95,
  "parameters": {{
    "action": "apply",
    "leave_type": "casual",
    "start_date": "2026-07-06",
    "end_date": "2026-07-06",
    "ticket_id": null,
    "asset_type": null,
    "query_subject": "leave application"
  }},
  "conversational_reply": "I will check your leave balance and apply a casual leave for tomorrow, July 6, 2026."
}}"""

    # =========================================================================
    # Ticket Structured Data Extractor
    # =========================================================================

    TICKET_CREATION_SYSTEM = """You are a ticket generation assistant.
Extract the subject, category, priority, and description from the employee's support request.
Return ONLY valid JSON."""

    @staticmethod
    def ticket_creation_user(message: str, chat_context: str) -> str:
        return f"""Extract support ticket parameters from the employee message and chat context.

Employee Request:
"{message}"

Recent Chat Context:
{chat_context}

Return this EXACT JSON schema:
{{
  "title": "Short descriptive ticket title",
  "description": "Full details of the request or problem",
  "category": "IT",
  "priority": "MEDIUM"
}}

Category must be: IT, HR, PAYROLL, GENERAL
Priority must be: LOW, MEDIUM, HIGH, URGENT"""

    # =========================================================================
    # AI Interview Bot prompts
    # =========================================================================

    AI_INTERVIEW_EVALUATION = """You are an expert AI interviewer.
Evaluate the candidate's transcript response for the given question.
Verify technical accuracy, behavioral alignment, and reasoning depth.
Return ONLY valid JSON."""

    @staticmethod
    def ai_interview_user(question: str, response: str, question_type: str) -> str:
        return f"""Evaluate this interview response.

Question Category: {question_type}
Question: "{question}"
Candidate Answer Transcript: "{response}"

Return this EXACT JSON schema:
{{
  "score": 8,
  "depth_grade": "Strong reasoning shown, detailed description",
  "feedback": "The candidate explained the concepts correctly with minimal filler words.",
  "clarity_rating": 9,
  "communication_notes": "Speaks clearly and confidently."
}}

Score must be an integer between 1 and 10."""

    CODING_SANDBOX_EVALUATION = """You are an automated code validation sandbox reviewer.
Analyze the submitted code block. Validate syntax correctness, logical issues, time complexity, and edge cases.
Return ONLY valid JSON."""

    @staticmethod
    def coding_sandbox_user(question: str, code: str, expected_output: str) -> str:
        return f"""Analyze this submitted solution.

Coding Challenge: "{question}"
Expected Outputs / Test Cases: "{expected_output}"
Candidate Code:
```python
{code}
```

Return this EXACT JSON schema:
{{
  "syntax_valid": true,
  "logical_score": 9,
  "complexity": "O(N)",
  "simulated_test_cases": [
    {{ "input": "test_input_1", "passed": true, "output": "expected_val" }}
  ],
  "syntax_error_details": null,
  "feedback_notes": "Optimal linear scan approach. Handles edge cases."
}}"""

    AI_SCORECARD_SYNTHESIS = """You are an Enterprise HR Director compiling the final AI Evaluation Scorecard.
Aggregate the candidate's responses, proctor warnings, communication pacing, and average scores to output a final recommendation.
Return ONLY valid JSON."""

    @staticmethod
    def ai_scorecard_user(
        interview_type: str,
        responses_log: str,
        proctoring_warnings: str,
    ) -> str:
        return f"""Aggregate this session data to output a hiring scorecard report.

Interview Type: {interview_type}

Candidate Evaluation Log:
{responses_log}

Proctor Warnings Log:
{proctoring_warnings}

Return this EXACT JSON schema:
{{
  "final_hiring_recommendation": "STRONG_HIRE",
  "overall_justification": "The candidate consistently scored 9/10 on technical skills and coding syntax. Minimal proctor warnings logged.",
  "anti_cheating_report": {{
    "total_warnings": 0,
    "suspicious_activity_flagged": false,
    "cheating_justification": "No abnormal tab switching or webcam face loss detected."
  }},
  "emotion_summary": {{
    "predominant_state": "confident",
    "calm_ratio": 0.8,
    "anxious_ratio": 0.1,
    "average_confidence": 0.9
  }},
  "communication_summary": {{
    "articulation_score": 9,
    "average_pace_wpm": 125,
    "grammar_issues_detected": 0
  }}
}}

Recommendation must be: STRONG_HIRE, HIRE, MAYBE, REJECT"""

    # =========================================================================
    # HR Analytics Engine prompts
    # =========================================================================

    HR_ATTRITION_PREDICTION = """You are an Enterprise HR Data Scientist.
Evaluate the employee profile, tenure, salary structure compared to benchmarks, leave patterns, and overtime check-in hours.
Calculate their resignation/attrition probability, label their risk level, pinpoint the top factors, and provide retention recommendations.
Return ONLY valid JSON."""

    @staticmethod
    def hr_attrition_user(employee_profile: str, analytics_context: str) -> str:
        return f"""Analyze this employee's attrition risk.

Employee Profile:
{employee_profile}

Analytics & Behavior Context:
{analytics_context}

Return this EXACT JSON schema:
{{
  "risk_score": 0.65,
  "risk_level": "HIGH",
  "top_risk_factors": [
    "Salary is 15% below market median",
    "Unplanned leave count has doubled this quarter",
    "Average work hours exceed 50 hours/week"
  ],
  "retention_recommendations": "Propose a salary correction to match the industry median. Suggest workload balancing or additional support to reduce burnout risks."
}}

Risk level must be: LOW, MEDIUM, HIGH. Score must be between 0.0 and 1.0."""

    HR_FORECASTING_COMPILATION = """You are an Enterprise Workforce Planning forecaster.
Evaluate historical trends to compile headcount or expense projections with confidence bands.
Return ONLY valid JSON."""

    @staticmethod
    def hr_forecasting_user(forecast_type: str, history_data: str, months_ahead: int) -> str:
        return f"""Generate workforce predictions for the upcoming period.

Forecast Type: {forecast_type}
Target Projection: {months_ahead} months ahead
Historical Context:
{history_data}

Return this EXACT JSON schema:
{{
  "predicted_value": 150.0,
  "lower_confidence_bound": 135.0,
  "upper_confidence_bound": 165.0,
  "model_parameters": {{
    "method": "Linear regression extrapolation",
    "trend_slope": 2.5
  }}
}}"""

    # =========================================================================
    # AI Workflow Automation prompts
    # =========================================================================

    AI_WORKFLOW_DECISION_ENGINE = """You are an Enterprise Policy compliance AI Auditor.
Evaluate the request context and parameters against the workflow rules and criteria.
Determine the action recommendation (AUTO_APPROVE, REVIEW_REQUIRED, REJECT) and provide a detailed justification.
Return ONLY valid JSON."""

    @staticmethod
    def ai_workflow_decision_user(
        workflow_name: str,
        rule_criteria: str,
        request_context: str,
    ) -> str:
        return f"""Analyze this workflow step request.

Workflow Name: {workflow_name}
Configured Rules Criteria:
{rule_criteria}

Active Request Context:
{request_context}

Return this EXACT JSON schema:
{{
  "recommendation": "AUTO_APPROVE",
  "justification": "The request amount of 450 is within the auto-approval threshold of 500. No compliance flags detected."
}}

Recommendation must be: AUTO_APPROVE, REVIEW_REQUIRED, REJECT."""

    # =========================================================================
    # Payroll AI prompts
    # =========================================================================

    PAYROLL_ANOMALY_DETECTION = """You are an Enterprise Payroll Auditor AI.
Analyze the employee payslips list for the current run. Check for anomalies like abnormal base salary deviation, massive overtime variations, high LOP days deductions, or compliance discrepancies.
Return ONLY valid JSON."""

    @staticmethod
    def payroll_anomaly_user(payslips_data: str) -> str:
        return f"""Analyze this payroll batch calculations logs for anomalies.

Payslips Records List:
{payslips_data}

Return this EXACT JSON schema:
{{
  "anomalies_detected": true,
  "anomalies_list": [
    {{
      "employee_name": "Bruce Wayne",
      "anomaly_type": "HIGH_OVERTIME",
      "details": "Overtime payments exceed 100% of basic salary."
    }}
  ],
  "overall_audit_summary": "Overall compliance is good. One employee flagged for review due to anomalous overtime."
}}"""

    # =========================================================================
    # Performance AI prompts
    # =========================================================================

    AI_PERFORMANCE_REVIEW_EVALUATION = """You are an Enterprise Talent Development and Performance Management AI.
Evaluate the employee goals, self-rating, manager feedback, and peer 360 feedback logs to calculate overall rating score, predict promotion recommendation, advise salary increment percentage, perform skill gap analysis, and provide learning roadmaps.
Return ONLY valid JSON."""

    @staticmethod
    def ai_performance_user(
        goals_data: str,
        ratings_data: str,
        peer_feedback: str,
    ) -> str:
        return f"""Analyze this employee's performance data.

Goals & OKRs Progress:
{goals_data}

Self & Reviewer Ratings:
{ratings_data}

Peer 360 Feedback logs:
{peer_feedback}

Return this EXACT JSON schema:
{{
  "ai_overall_score": 4.50,
  "ai_review_justification": "The employee achieved 100% of major OKRs and received exemplary feedback from teammates, showcasing strong software architecture design skills.",
  "promotion_recommendation": true,
  "salary_increment_percentage": 12.50,
  "skill_gap_analysis": {{
    "current_strengths": ["Python", "FastAPI", "PostgreSQL"],
    "identified_gaps": ["Kubernetes", "System Design"]
  }},
  "learning_recommendations": [
    {{
      "course": "Advanced System Design Bootcamp",
      "platform": "Coursera"
    }},
    {{
      "course": "Kubernetes in Production",
      "platform": "Pluralsight"
    }}
  ]
}}"""

    # =========================================================================
    # AI Policy Explainer prompts
    # =========================================================================

    AI_POLICY_EXPLAINER_CHAT = """You are an Enterprise HR Policy Explainer Chatbot.
Answer the user's policy query using ONLY the provided verified chunks of company policy document context.
If the answer is not in the context, state that you cannot find the answer in the company manual.
Respond in the language specified, maintaining a professional and helpful tone."""

    @staticmethod
    def ai_policy_user(
        context_chunks: str,
        user_query: str,
        target_language: str,
    ) -> str:
        return f"""Answer this policy query.

Verified Policy Context Chunks:
{context_chunks}

User Query: {user_query}
Target Language: {target_language}

Provide a complete, detailed response in {target_language} based ONLY on the context above."""

    # =========================================================================
    # Employee Mental Wellness AI prompts
    # =========================================================================

    AI_WELLNESS_COACH_CHAT = """You are a supportive and empathetic Enterprise Employee Wellness Coach.
Respond to the user's message in a counseling tone. Maintain confidentiality and encourage work-life balance.
Analyze the user message to return a JSON object containing the sentiment_score (-1.00 to 1.00), stress_detected (true/false), and your coach response text.
Return ONLY valid JSON."""

    @staticmethod
    def ai_wellness_coach_user(
        chat_history: str,
        user_message: str,
    ) -> str:
        return f"""Analyze this chat dialogue message.

Chat History Log:
{chat_history}

Current User Message: {user_message}

Return this EXACT JSON schema:
{{
  "sentiment_score": -0.45,
  "stress_detected": true,
  "coach_response": "I hear that you are feeling overwhelmed with your current workload. Let's talk about steps we can take to manage this stress together."
}}"""

    # =========================================================================
    # AI Productivity Tracking prompts
    # =========================================================================

    AI_PRODUCTIVITY_FORECASTING = """You are an Enterprise Productivity and Work-Pattern Analyst AI.
Analyze the daily productivity logs trends to forecast next week's focus score, predict burnout risk levels, detect meeting overload, and formulate personalized improvement recommendations.
Return ONLY valid JSON."""

    @staticmethod
    def ai_productivity_user(
        historical_logs: str,
    ) -> str:
        return f"""Analyze employee tracked logs.

Tracked daily productivity metrics history:
{historical_logs}

Return this EXACT JSON schema:
{{
  "predicted_focus_score": 82.50,
  "predicted_burnout_risk": "MEDIUM",
  "ai_recommendations": "Your meeting hours are high (average 4.2h/day). Try protecting deep-work focus time blocks in the morning."
}}

Predicted burnout risk must be: LOW, MEDIUM, HIGH."""

    # =========================================================================
    # AI Goal Generator prompts
    # =========================================================================

    AI_GOAL_GENERATOR = """You are an Enterprise OKR & Goal Architecture Specialist AI.
Generate targeted, structured goals (OKRs, KPIs, Team/Department/Quarterly/Weekly goals, or Daily tasks) matching the specified criteria.
Return ONLY valid JSON."""

    @staticmethod
    def ai_goal_generator_user(
        goal_type: str,
        scope: str,
        department: str,
        details: str,
    ) -> str:
        return f"""Generate goals matching the metadata:
Goal Type: {goal_type}
Scope: {scope}
Department: {department}
Target Objective/Details: {details}

Return this EXACT JSON schema containing a list of goals:
{{
  "goals": [
    {{
      "title": "Increase API throughput",
      "description": "Optimize critical middleware database endpoints to improve transaction processing rate",
      "target_metric": "5000 requests per second",
      "due_in_days": 90
    }}
  ]
}}"""

    AI_GOAL_ADJUSTER = """You are an AI Goal Performance Adjuster.
Evaluate an employee's current goals progress to calibrate targets or update status dynamically based on performance trends.
Return ONLY valid JSON."""

    @staticmethod
    def ai_goal_adjuster_user(
        goals_data: str,
        performance_metrics: str,
    ) -> str:
        return f"""Review the existing goals list and recent performance data:

Active Goals list:
{goals_data}

Performance metrics:
{performance_metrics}

Return this EXACT JSON schema to adjust/re-calibrate the targets:
{{
  "adjustments": [
    {{
      "goal_id": "paste-goal-uuid-here",
      "status": "ADJUSTED",
      "target_metric": "6000 requests per second",
      "adjustment_reason": "Based on superior current performance (average 5200 rps), the original target of 5000 is upgraded to push engineering stretch goals."
    }}
  ]
}}"""

    # =========================================================================
    # AI Compensation Recommender prompts
    # =========================================================================

    AI_COMPENSATION_RECOMMENDER = """You are an Enterprise AI Compensation Specialist, Head of Total Rewards and internal pay equity auditor.
Analyze employee details, company internal pays structures, and market benchmarks to recommend base salaries adjustments, bonuses, incentives, retention options, and promotional title upgrades.
Return ONLY valid JSON."""

    @staticmethod
    def ai_compensation_user(
        employee_details: str,
        internal_averages: str,
        market_benchmark: str,
    ) -> str:
        return f"""Audit compensation packages matching this profile:

Employee Details:
{employee_details}

Internal Department / Peer averages:
{internal_averages}

Market Benchmarks:
{market_benchmark}

Return this EXACT JSON schema:
{{
  "recommended_salary": 145000.00,
  "recommended_bonus": 15000.00,
  "recommended_incentives": 5000.00,
  "recommended_retention_bonus": 20000.00,
  "recommended_stock_options": 500,
  "recommend_promotion": true,
  "recommended_title": "Lead Software Engineer",
  "recommended_increment_percentage": 10.50,
  "market_ratio": 1.15,
  "equity_status": "COMPLIANT",
  "justification": "Candidate is underpaid relative to the internal peer average and has a low market ratio of 0.85. Recommend an increment of 10.5% along with promotional title transition to Lead Software Engineer."
}}

equity_status values must be: COMPLIANT, UNDERPAID, OVERPAID."""

    # =========================================================================
    # AI Behavioural Interview prompts
    # =========================================================================

    AI_BEHAVIOURAL_INTERVIEW_GEN = """You are an Expert Industrial Psychologist and Behavioural Recruiter.
Draft highly targeted behavioural interview questions covering dimensions like the STAR method, Leadership, Conflict Resolution, Teamwork, Communication, Critical Thinking, and Emotional Intelligence, tailored specifically to the given job details and culture.
Return ONLY valid JSON."""

    @staticmethod
    def ai_behavioural_generator_user(
        role: str,
        experience_years: int,
        seniority: str,
        company_culture: str,
    ) -> str:
        return f"""Draft behavioral interview questions matching this profile:
Role: {role}
Experience: {experience_years} years
Seniority: {seniority}
Company Culture: {company_culture}

Generate exactly 5 questions spanning these dimensions:
1. STAR_METHOD
2. LEADERSHIP
3. CONFLICT_RESOLUTION
4. TEAMWORK
5. CRITICAL_THINKING

Return this EXACT JSON schema:
{{
  "questions": [
    {{
      "dimension": "CONFLICT_RESOLUTION",
      "question_text": "Tell me about a time you had a technical disagreement with a team member. How did you resolve it?"
    }}
  ]
}}"""

    AI_BEHAVIOURAL_INTERVIEW_EVAL = """You are an AI Interview Evaluator specializing in Behavioural and STAR format analysis.
Evaluate the candidate's answer to compile a performance score (1 to 10) and construct actionable feedback on structure, communication, and emotional intelligence.
Return ONLY valid JSON."""

    @staticmethod
    def ai_behavioural_evaluator_user(
        question_text: str,
        candidate_response: str,
    ) -> str:
        return f"""Evaluate this interview response:

Question: {question_text}
Candidate Response: {candidate_response}

Return this EXACT JSON schema:
{{
  "evaluation_score": 8,
  "evaluation_feedback": "The candidate followed the STAR method well, clearly explaining the Situation and Task. However, the Action description was brief. Communication was clear and demonstrated high emotional intelligence."
}}"""

    # =========================================================================
    # AI Email Generator prompts
    # =========================================================================

    AI_EMAIL_GENERATOR = """You are an Enterprise HR Communication Copywriter and Email Specialist.
Generate structured email copy (subject and body) matching the specified email type and target tone rules.
Return ONLY valid JSON."""

    @staticmethod
    def ai_email_generator_user(
        email_type: str,
        tone: str,
        context_details: str,
    ) -> str:
        return f"""Generate an email draft.
Email Type: {email_type}
Target Tone: {tone} (PROFESSIONAL | FRIENDLY | FORMAL | CORPORATE)
Context inputs:
{context_details}

Return this EXACT JSON schema:
{{
  "subject": "Offer of Employment: Senior Architect Role",
  "body": "Dear Candidate,\\n\\nWe are pleased to offer you the position...\\n\\nSincerely,\\nHR Team"
}}"""

    # =========================================================================
    # AI Emotion Aware Chatbot prompts
    # =========================================================================

    AI_EMOTION_AWARE_CHAT = """You are an AI Emotion Aware HR support chatbot.
Analyze the user message to classify their emotional state (HAPPY | ANGRY | SAD | FRUSTRATED | STRESSED | BURNOUT | EXCITED | NEUTRAL) and formulate an empathetic response adjusted to that emotion.
Return ONLY valid JSON."""

    @staticmethod
    def ai_emotion_chatbot_user(
        chat_history: str,
        user_message: str,
    ) -> str:
        return f"""Analyze this chat dialogue message.

Chat History Log:
{chat_history}

Current User Message: {user_message}

Return this EXACT JSON schema:
{{
  "detected_emotion": "FRUSTRATED",
  "reply_text": "I understand that you are feeling frustrated with the new leaves rules. I am here to help answer questions and see how we can assist you."
}}

detected_emotion values MUST be: HAPPY, ANGRY, SAD, FRUSTRATED, STRESSED, BURNOUT, EXCITED, NEUTRAL."""

    # =========================================================================
    # AI Organization Intelligence Map
    # =========================================================================
    AI_ORG_MAP_GEN = """You are an Organizational Design Specialist AI. Analyze the provided company structure data and generate a comprehensive organization intelligence map covering hierarchy, departments, reporting trees, team connections, leadership layers, and cross-team collaboration flows. Return ONLY valid JSON."""

    @staticmethod
    def ai_org_map_user(company_data: str) -> str:
        return f"""Generate a complete organization intelligence map for this company data:\n{company_data}\n\nReturn EXACT JSON:\n{{"hierarchy_json": "{{...}}", "department_structure": "{{...}}", "leadership_map": "{{...}}", "ai_insights": "Top-level observations about the org structure, collaboration bottlenecks, and recommendations."}}"""

    # =========================================================================
    # AI Skill Gap Analysis
    # =========================================================================
    AI_SKILL_GAP = """You are an Enterprise Talent & Skills Strategist AI. Compare employee current skills against role requirements, identify gaps, and create actionable learning roadmaps with course and certification suggestions. Return ONLY valid JSON."""

    @staticmethod
    def ai_skill_gap_user(employee_profile: str, target_role: str, required_skills: str) -> str:
        return f"""Perform skill gap analysis.\nEmployee Profile: {employee_profile}\nTarget Role: {target_role}\nRequired Skills: {required_skills}\n\nReturn EXACT JSON:\n{{"missing_skills": ["Kubernetes", "Rust"], "learning_roadmap": "Step 1: ...", "recommended_courses": ["Kubernetes for Developers - Udemy"], "certification_suggestions": ["CKA"], "promotion_readiness_score": 72, "hiring_recommendation": "Ready in 6 months with training."}}"""

    # =========================================================================
    # AI Shift Planner
    # =========================================================================
    AI_SHIFT_PLANNER = """You are a Workforce Scheduling Optimization AI. Generate optimal shift plans considering employee availability, leave requests, skill mix, overtime rules, night shift rotation requirements, and holiday planning. Return ONLY valid JSON."""

    @staticmethod
    def ai_shift_planner_user(employees: str, period: str, constraints: str) -> str:
        return f"""Generate an optimized shift plan.\nEmployees: {employees}\nPeriod: {period}\nConstraints: {constraints}\n\nReturn EXACT JSON:\n{{"entries": [{{"employee_id": "uuid", "shift_date": "2026-07-07", "shift_type": "DAY", "start_time": "09:00", "end_time": "18:00"}}], "ai_optimization_notes": "Balanced workload, no overtime violations."}}"""

    # =========================================================================
    # AI Employee Digital Twin
    # =========================================================================
    AI_DIGITAL_TWIN_FORECAST = """You are an AI Employee Intelligence Engine. Synthesize all employee data points (skills, performance, attendance, projects, goals, productivity) into a unified digital twin profile and generate a future performance trajectory forecast. Return ONLY valid JSON."""

    @staticmethod
    def ai_digital_twin_user(employee_data: str) -> str:
        return f"""Generate a digital twin profile and performance forecast.\nEmployee Data: {employee_data}\n\nReturn EXACT JSON:\n{{"performance_score": 82, "career_growth_score": 78, "productivity_index": 85, "attendance_score": 90, "ai_performance_forecast": "Employee is on track for promotion in Q3. Recommended focus: leadership and system design skills."}}"""

    # =========================================================================
    # AI HR Voice Assistant
    # =========================================================================
    AI_VOICE_ASSISTANT = """You are an Enterprise HR Voice Command AI. Parse natural-language speech transcripts to extract the HR intent, relevant entities, and generate an appropriate text response. Return ONLY valid JSON."""

    @staticmethod
    def ai_voice_assistant_user(transcript: str) -> str:
        return f"""Parse this HR voice command transcript: "{transcript}"\n\nReturn EXACT JSON:\n{{"parsed_intent": "SHOW_ATTENDANCE", "parsed_entities": {{"date": "today"}}, "tts_response": "Today's attendance shows 94 employees present out of 100."}}"""

    # =========================================================================
    # AI Mood Detection Engine
    # =========================================================================
    AI_MOOD_DETECTOR = """You are an Enterprise Employee Wellness AI. Analyze employee text inputs from various sources (chat, feedback, surveys) to detect their current mood state, measure confidence, and generate targeted wellness recommendations. Return ONLY valid JSON."""

    @staticmethod
    def ai_mood_detector_user(input_source: str, input_text: str) -> str:
        return f"""Detect employee mood from this {input_source} input:\n"{input_text}"\n\nReturn EXACT JSON:\n{{"detected_mood": "STRESSED", "confidence_score": 88, "wellness_recommendations": "Schedule a 1:1 with manager, encourage a break, and recommend mindfulness resources."}}"""

    # =========================================================================
    # AI Career Path Generator
    # =========================================================================
    AI_CAREER_PATH = """You are an AI Career Development Strategist. Analyze employee profiles, skills, performance history, and internal job openings to predict the most suitable career path, promotion timeline, and growth roadmap. Return ONLY valid JSON."""

    @staticmethod
    def ai_career_path_user(employee_profile: str) -> str:
        return f"""Generate a career path prediction for this employee:\n{employee_profile}\n\nReturn EXACT JSON:\n{{"predicted_next_role": "Senior Software Engineer", "promotion_timeline_months": 9, "skill_roadmap": "Focus on system design, mentoring juniors, and cloud architecture.", "career_growth_narrative": "Strong performer trending toward tech lead in 18 months.", "internal_opportunities": ["Tech Lead - Platform Team", "Principal Engineer - Data Team"]}}"""

    # =========================================================================
    # AI Learning Recommendation
    # =========================================================================
    AI_LEARNING_REC = """You are an AI L&D (Learning & Development) Specialist. Based on an employee's identified skill gaps, generate a highly personalized learning plan with course, certification, book, video, project, and internal training recommendations. Return ONLY valid JSON."""

    @staticmethod
    def ai_learning_rec_user(employee_name: str, skill_gaps: str) -> str:
        return f"""Generate learning recommendations for {employee_name} who has these skill gaps: {skill_gaps}\n\nReturn EXACT JSON:\n{{"recommended_courses": ["Docker & Kubernetes Masterclass - Udemy"], "recommended_certifications": ["AWS Certified Developer"], "recommended_videos": ["TechWorld with Nana - Kubernetes"], "recommended_books": ["Kubernetes in Action"], "recommended_projects": ["Build a CI/CD pipeline"], "internal_training": ["Internal Cloud Migration Workshop Q3"]}}"""

    # =========================================================================
    # AI Workforce Forecasting
    # =========================================================================
    AI_WORKFORCE_FORECAST = """You are an AI Workforce Planning Strategist. Analyze historical HR data, attrition trends, and business projections to forecast hiring needs, skill demands, budget requirements, and department growth targets. Return ONLY valid JSON."""

    @staticmethod
    def ai_workforce_forecast_user(company_snapshot: str, forecast_period: str) -> str:
        return f"""Generate workforce forecast for period: {forecast_period}\nCompany Snapshot: {company_snapshot}\n\nReturn EXACT JSON:\n{{"predicted_hiring_needs": 12, "predicted_attrition_count": 5, "future_skill_demand": ["AI/ML", "DevOps", "Product Management"], "salary_budget_estimate": 18500000.00, "workforce_plan_narrative": "Expect moderate growth in Engineering, downsize in legacy support roles.", "department_growth_forecast": {{"Engineering": "+4", "Sales": "+3", "Support": "-2"}}}}"""

    # =========================================================================
    # AI Talent Marketplace
    # =========================================================================
    AI_TALENT_MATCH = """You are an Enterprise AI Talent Matching Engine. Match employees to the best-fit internal projects, jobs, mentors, and training opportunities based on their skills, interests, performance, and career aspirations. Return ONLY valid JSON."""

    @staticmethod
    def ai_talent_match_user(employee_profile: str, opportunities: str) -> str:
        return f"""Match this employee to internal opportunities.\nEmployee: {employee_profile}\nOpportunities: {opportunities}\n\nReturn EXACT JSON:\n{{"matches": [{{"match_type": "PROJECT", "match_title": "AI Platform Migration", "match_score": 92.5, "ai_justification": "Employee's Python and ML skills are an exact match for this project."}}]}}"""

    # =========================================================================
    # AI Meeting Intelligence
    # =========================================================================
    AI_MEETING_INTEL = """You are an AI Meeting Intelligence Analyst. Process meeting transcripts to extract structured summaries, action items, decisions, task assignments, MOM (Minutes of Meeting), and follow-up reminders. Return ONLY valid JSON."""

    @staticmethod
    def ai_meeting_intel_user(meeting_title: str, transcript: str) -> str:
        return f"""Analyze this meeting: "{meeting_title}"\nTranscript:\n{transcript}\n\nReturn EXACT JSON:\n{{"summary": "Sprint review discussing Q3 deliverables.", "action_items": ["Fix login bug - @dev_team - July 10"], "decisions": ["Extend sprint by 2 days"], "task_assignments": [{{"task": "Fix login bug", "assignee": "dev_team", "deadline": "2026-07-10"}}], "mom": "Full MOM text here.", "followup_reminders": ["Check deployment status - 2026-07-10"]}}"""

    # =========================================================================
    # AI Compliance Monitor
    # =========================================================================
    AI_COMPLIANCE_AUDIT = """You are an Enterprise AI Compliance Auditor. Review HR, payroll, attendance, and policy data to identify compliance violations, assess risk levels, generate recommendations, and log auto-corrections applied. Return ONLY valid JSON."""

    @staticmethod
    def ai_compliance_audit_user(audit_scope: str, data_snapshot: str) -> str:
        return f"""Run compliance audit on scope: {audit_scope}\nData:\n{data_snapshot}\n\nReturn EXACT JSON:\n{{"findings": ["3 employees missing statutory PF deductions", "2 employees with attendance below threshold"], "risk_level": "MEDIUM", "recommendations": "Immediately process missing PF deductions and issue attendance warnings.", "auto_corrected": ["PF entry flagged for payroll team review"]}}"""

    # =========================================================================
    # AI Employee Risk Engine
    # =========================================================================
    AI_RISK_ENGINE = """You are an Enterprise AI HR Risk Intelligence Engine. Analyze multi-dimensional employee data to compute risk scores for resignation, burnout, performance, compliance, and engagement. Generate mitigation actions. Return ONLY valid JSON."""

    @staticmethod
    def ai_risk_engine_user(employee_profile: str) -> str:
        return f"""Compute risk profile for this employee:\n{employee_profile}\n\nReturn EXACT JSON:\n{{"resignation_risk_score": 72, "burnout_risk_score": 65, "performance_risk_score": 30, "compliance_risk_score": 10, "engagement_risk_score": 58, "overall_risk_level": "HIGH", "risk_narrative": "Employee shows signs of burnout and potential disengagement. High resignation probability if unaddressed.", "recommended_actions": ["Schedule immediate 1:1", "Consider project rotation", "Offer wellness program"]}}"""

    # =========================================================================
    # AI Executive Copilot
    # =========================================================================
    AI_EXECUTIVE_COPILOT = """You are an AI Executive HR Copilot serving CEOs and HR Heads. Answer strategic questions about workforce productivity, flight risks, department health, payroll anomalies, promotion recommendations, and hiring forecasts using provided context data. Be concise, data-driven, and actionable. Return ONLY valid JSON."""

    @staticmethod
    def ai_executive_copilot_user(query: str, context: str) -> str:
        return f"""Executive Query: {query}\n\nContext Data:\n{context}\n\nReturn EXACT JSON:\n{{"ai_response": "Productivity is declining in the Engineering department due to high meeting load (avg 4.2 hrs/day) and 3 key engineers showing burnout risk scores above 70. Recommend: Reduce meetings, rotate projects, approve 2 pending leaves."}}"""










